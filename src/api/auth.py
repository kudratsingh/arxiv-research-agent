"""API-key authentication + per-key rate limiting.

The FastAPI surface ships gated behind an `X-API-Key` header when
`settings.enable_api_auth` is on. Three defenses live here:

- **Key authentication** (ADR 0033) — `require_principal` is a
  FastAPI dependency that reads `X-API-Key`, looks it up in the
  app-scoped keystore, and returns an `ApiKeyPrincipal`. Missing
  or unknown key => 401.
- **Sliding-window rate limit** (ADR 0033 + ADR 0037) — pluggable:
  `InMemoryRateLimiter` (per-worker deque, single-process
  deployments) or `RedisRateLimiter` (shared ZSET on
  `ratelimit:{key_id}`, correct under multi-worker uvicorn).
- **Hot-reloadable keystore** (ADR 0037) — when
  `settings.api_keys_file` is set, the app loads keys from a JSON
  file at startup AND polls its mtime; on change, the new keys
  swap into `app.state.api_keys` atomically without a restart.

All three are opt-in behind `enable_api_auth`; local dev and the
eval runner path stay unchanged.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import time
import uuid
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fastapi import Request

from src.config import settings
from src.errors import (
    ApiAuthMisconfigured,
    InvalidApiKey,
    MissingApiKey,
    RateLimitedError,
)
from src.observability import get_logger
from src.observability.metrics import record_rate_limit_rejection
from src.resilience import record_degradation

log = get_logger(__name__)

API_KEY_HEADER = "X-API-Key"
RATE_LIMIT_KEY_PREFIX = "ratelimit:"


@dataclass(frozen=True)
class ApiKeyPrincipal:
    """A validated API-key holder.

    `key_id` is the display name from `settings.api_keys` — used in
    logs and as the rate-limit bucket key. The raw key is NOT
    retained on the principal so a log emission that dumps the
    dataclass can't leak it.
    """

    key_id: str


def parse_api_keys(raw: str) -> dict[str, ApiKeyPrincipal]:
    """Turn the `settings.api_keys` string into a `{secret: principal}` map.

    Format: comma-separated `name:secret` pairs. Whitespace around
    each element is stripped. Empty entries are ignored so a trailing
    comma is harmless. Duplicate secrets raise `ValueError` — a silent
    overwrite would mask a misconfiguration where two clients
    accidentally share a key. Duplicate names raise too (ADR 0042):
    the name is what `principal_key_id` rows are stamped with under
    ADR 0036, so two secrets sharing a name would silently merge two
    tenants' data.
    """
    keys: dict[str, ApiKeyPrincipal] = {}
    seen_names: set[str] = set()
    for chunk in raw.split(","):
        entry = chunk.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError(
                f"api_keys entry {entry!r} missing 'name:secret' separator"
            )
        name, secret = entry.split(":", 1)
        name = name.strip()
        secret = secret.strip()
        if not name or not secret:
            raise ValueError(
                f"api_keys entry {entry!r} has empty name or secret"
            )
        if secret in keys:
            raise ValueError(
                f"api_keys contains duplicate secret for principal {name!r}"
            )
        if name in seen_names:
            raise ValueError(
                f"api_keys contains duplicate principal name {name!r}"
            )
        seen_names.add(name)
        keys[secret] = ApiKeyPrincipal(key_id=name)
    return keys


def _lookup_principal(
    presented: str, keystore: dict[str, ApiKeyPrincipal]
) -> ApiKeyPrincipal | None:
    """Constant-time key lookup.

    A plain `keystore.get(presented)` leaks timing information about
    which prefix matched. Compare every configured secret with
    `hmac.compare_digest` and return the first match.
    """
    # Compare bytes, not str: `hmac.compare_digest` raises TypeError
    # on non-ASCII str operands, and Starlette decodes header values
    # as latin-1 — so a single byte >= 0x80 in `X-API-Key` would
    # otherwise turn into an unauthenticated 500 instead of the 401
    # every other bad-key path returns (ADR 0042). Encoding the
    # presented value back to latin-1 recovers the exact wire bytes;
    # configured secrets are utf-8, matching what a well-behaved
    # client sends for a non-ASCII secret.
    try:
        presented_bytes = presented.encode("latin-1")
    except UnicodeEncodeError:
        # Not reachable via HTTP (headers arrive latin-1-decoded);
        # a direct caller handed us something no wire request can
        # produce, which can't match any configured secret.
        return None
    match: ApiKeyPrincipal | None = None
    for secret, principal in keystore.items():
        if hmac.compare_digest(secret.encode("utf-8"), presented_bytes):
            # Don't return early — keep the comparison loop uniform
            # across all keys so timing stays constant.
            match = principal
    return match


class RateLimiter(Protocol):
    """Structural interface — both backends duck-type this shape.

    Kept as a Protocol (not a base class) so the in-memory dataclass
    and the Redis wrapper have zero coupling. `check_and_record`
    is `async` so the Redis backend can await pipeline results
    without threading the loop through executors.
    """

    limit_per_hour: int

    async def check_and_record(
        self, key_id: str, *, now: float | None = None
    ) -> None: ...


def _raise_429(
    key_id: str, limit_per_hour: int, retry_after_sec: int, *, backend: str
) -> None:
    """Shared 429 response shape so both backends emit the same
    detail + Retry-After header.

    Also the single point where `rate_limit_rejections_total` is
    recorded (ADR 0049) — hence `backend`, which the counter needs and
    the response does not. Attributing by backend rather than by
    `key_id` keeps the metric's cardinality bounded at two: the
    rejected principal is already named in the 429 body and the
    request log.

    Args:
        key_id: Principal that hit the cap; surfaced in the response.
        limit_per_hour: The cap that was hit.
        retry_after_sec: Seconds until the window frees a slot.
        backend: Limiter implementation raising this — `memory` or
            `redis`, matching `settings.rate_limit_backend`.

    Raises:
        RateLimitedError: Always; 429 with a `Retry-After` header.
    """
    record_rate_limit_rejection(backend=backend)
    # ADR 0064: this is one of exactly two places where `detail` is not
    # the bare code. The object shape predates the taxonomy and the
    # current web client reads `limit_per_hour` off it to compose "This
    # key allows N requests an hour" (`web/lib/api/errors.ts`), and
    # `web/contract/fixtures/error.429.json` records it. The envelope is
    # added beside it rather than in place of it.
    raise RateLimitedError(
        log_detail=f"key_id={key_id} over {limit_per_hour}/hour",
        public_message=(
            f"Rate limit reached. Try again in about "
            f"{max(retry_after_sec, 1)} seconds."
        ),
        wire_detail={
            "error": RateLimitedError.code,
            "key_id": key_id,
            "limit_per_hour": limit_per_hour,
        },
        headers={"Retry-After": str(max(retry_after_sec, 1))},
    )


@dataclass
class InMemoryRateLimiter:
    """In-memory sliding-window submit counter, keyed by principal.

    Not designed to be perfect — the goal is to keep a single API
    key from bursting past `api_key_hourly_limit` requests / hour.
    Correct under one uvicorn worker; multi-worker deployments
    should select the Redis backend (ADR 0037) so the counter is
    shared across processes.
    """

    limit_per_hour: int
    window_sec: int = 3600
    _buckets: dict[str, deque[float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def check_and_record(
        self, key_id: str, *, now: float | None = None
    ) -> None:
        """Raise 429 when the principal is over quota; otherwise record.

        Records the submit timestamp on the same call — the caller
        does not need a separate "record" step, and the check +
        record are atomic under the lock.
        """
        ts = now if now is not None else time.time()
        cutoff = ts - self.window_sec
        async with self._lock:
            bucket = self._buckets.setdefault(key_id, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit_per_hour:
                retry_after = int(bucket[0] + self.window_sec - ts) + 1
                _raise_429(
                    key_id,
                    self.limit_per_hour,
                    retry_after,
                    backend="memory",
                )
            bucket.append(ts)


class RedisRateLimiter:
    """Shared sliding-window submit counter via a Redis ZSET (ADR 0037).

    Storage: `ratelimit:{key_id}` is a sorted set whose members are
    submit-timestamp UUIDs and whose scores are the timestamps
    themselves. The whole check-and-record cycle runs in one Redis
    pipeline round trip:

    1. `ZREMRANGEBYSCORE` prunes anything older than the window.
    2. `ZCARD` counts what's left.
    3. `ZADD` records the current submit.
    4. `EXPIRE` bumps the TTL so idle keys eventually vacate Redis.

    Steps 3 and 4 run unconditionally; if `ZCARD` says we're at or
    over the cap we roll back with `ZREM` before raising 429. That
    keeps the fast path (under cap) to a single round trip. The
    small race under adversarial load — two concurrent requests
    might both squeak past at the boundary — is acceptable at demo
    scale; a stricter implementation would use a Lua script.

    **A Redis failure degrades rather than raises** (ADR 0068). Before
    that, an unguarded `pipe.execute()` meant a Redis blip answered
    every submit with an opaque 500 — the rate limiter, a *defence*,
    became the outage. Fail-open is the deliberate choice: the counter
    exists to stop one key bursting past a courtesy quota, not to
    protect a secret, and refusing every request because the counter is
    unavailable trades a small over-serve for a total one. The fallback
    is a real per-worker limiter, not an absence of one, so a fleet of
    N workers still caps a key at N x `api_key_hourly_limit` while
    Redis is away — and `resilience.record_degradation` makes the
    weaker guarantee visible instead of silent.
    """

    def __init__(
        self,
        client: Any,
        *,
        limit_per_hour: int,
        window_sec: int = 3600,
        key_prefix: str = RATE_LIMIT_KEY_PREFIX,
    ) -> None:
        self._client = client
        self.limit_per_hour = limit_per_hour
        self.window_sec = window_sec
        self._key_prefix = key_prefix
        # Built eagerly and kept for the limiter's lifetime, so a
        # degradation that spans several requests accumulates in one
        # window. A fallback constructed per failure would forget every
        # request it had just counted and cap nothing at all.
        self._fallback = InMemoryRateLimiter(
            limit_per_hour=limit_per_hour, window_sec=window_sec
        )

    def _key(self, key_id: str) -> str:
        return f"{self._key_prefix}{key_id}"

    async def check_and_record(
        self, key_id: str, *, now: float | None = None
    ) -> None:
        ts = now if now is not None else time.time()
        try:
            retry_after = await self._count(key_id, ts)
        except Exception as exc:  # noqa: BLE001 - see the class docstring
            # Every Redis failure mode lands here on purpose: a
            # connection error, a timeout, a MOVED from a resharded
            # cluster, a decode error from a key some other tenant
            # wrote. Narrowing the catch would mean enumerating a
            # client library's exception tree and being wrong about it
            # during an incident, and the correct response is the same
            # for all of them.
            record_degradation(
                component="rate_limiter",
                reason="redis_unavailable",
                error=type(exc).__name__,
            )
            await self._fallback.check_and_record(key_id, now=ts)
            return
        if retry_after is not None:
            # Raised out here rather than inside `_count`, so the
            # `except` above can be as wide as it is without ever
            # swallowing the 429 the limiter exists to produce.
            _raise_429(
                key_id, self.limit_per_hour, retry_after, backend="redis"
            )

    async def _count(self, key_id: str, ts: float) -> int | None:
        """Record the submit and report whether it went over the cap.

        Args:
            key_id: Principal being counted.
            ts: Timestamp of this submit.

        Returns:
            None when the principal is under its cap. Otherwise the
            `Retry-After` seconds for the 429 the caller must raise.

        Raises:
            Exception: whatever the Redis client raises. The caller
                turns that into a degradation, never into a 500.
        """
        cutoff = ts - self.window_sec
        redis_key = self._key(key_id)
        member = uuid.uuid4().hex

        async with self._client.pipeline(transaction=True) as pipe:
            pipe.zremrangebyscore(redis_key, 0, cutoff)
            pipe.zadd(redis_key, {member: ts})
            pipe.zcard(redis_key)
            pipe.expire(redis_key, self.window_sec + 60)
            results = await pipe.execute()

        current_count = int(results[2])
        if current_count <= self.limit_per_hour:
            return None
        # Over cap: roll back this record and 429.
        await self._client.zrem(redis_key, member)
        # Retry-After = seconds until the oldest surviving entry
        # falls out of the window.
        oldest = await self._client.zrange(redis_key, 0, 0, withscores=True)
        if oldest:
            _, oldest_ts = oldest[0]
            return int(float(oldest_ts) + self.window_sec - ts) + 1
        return self.window_sec


def build_rate_limiter(
    limit_per_hour: int,
    backend: str,
    *,
    redis_client: Any = None,
) -> RateLimiter:
    """Construct the configured rate-limiter backend.

    `backend` mirrors `settings.rate_limit_backend`. `redis_client`
    is required for the Redis backend and ignored otherwise. Unknown
    backend raises `ValueError` at startup — the operator sees the
    misconfiguration before traffic starts.
    """
    if backend == "redis":
        if redis_client is None:
            raise RuntimeError(
                "rate_limit_backend=redis requires a Redis client; "
                "the compose stack + `job_store=redis` wire this."
            )
        return RedisRateLimiter(
            redis_client, limit_per_hour=limit_per_hour
        )
    if backend == "memory":
        return InMemoryRateLimiter(limit_per_hour=limit_per_hour)
    raise ValueError(
        f"Unknown rate_limit_backend={backend!r}; expected 'memory' or 'redis'."
    )


# ---- Hot-reloadable keystore (ADR 0037) ---------------------------


def load_keystore_from_file(
    path: str | Path,
) -> dict[str, ApiKeyPrincipal]:
    """Parse a JSON keystore file into a `{secret: principal}` map.

    File shape: a JSON object with `{name: secret}` pairs. Example:

        {"internal": "sk_a123", "partner": "sk_b456"}

    Same duplicate-secret + duplicate-name + empty-value validation
    as `parse_api_keys`. Duplicate names need an `object_pairs_hook`
    because `json.loads` silently keeps the last value for a repeated
    key — exactly the silent overwrite the check exists to prevent.
    Errors raise `ValueError` with the path in the message so log
    grep pinpoints the bad file.
    """
    text = Path(path).read_text(encoding="utf-8")

    def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for pair_key, pair_value in pairs:
            if pair_key in obj:
                raise ValueError(
                    f"api_keys_file {str(path)!r}: duplicate principal "
                    f"name {pair_key!r}"
                )
            obj[pair_key] = pair_value
        return obj

    try:
        raw = json.loads(text, object_pairs_hook=_object_pairs)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"api_keys_file {str(path)!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"api_keys_file {str(path)!r} must be a JSON object "
            f"of {{name: secret}}; got {type(raw).__name__}"
        )
    keys: dict[str, ApiKeyPrincipal] = {}
    for name, secret in raw.items():
        if not isinstance(name, str) or not isinstance(secret, str):
            raise ValueError(
                f"api_keys_file {str(path)!r}: name and secret must be strings"
            )
        name_s = name.strip()
        secret_s = secret.strip()
        if not name_s or not secret_s:
            raise ValueError(
                f"api_keys_file {str(path)!r}: empty name or secret"
            )
        if secret_s in keys:
            raise ValueError(
                f"api_keys_file {str(path)!r}: duplicate secret for {name_s!r}"
            )
        keys[secret_s] = ApiKeyPrincipal(key_id=name_s)
    return keys


class KeystoreReloader:
    """Background mtime-polling reloader for `settings.api_keys_file`.

    Runs as an asyncio task spawned in the FastAPI lifespan. Every
    `interval_sec` it checks the file's mtime; on change, re-parses
    and swaps `app.state.api_keys` with the new dict. Parse errors
    are logged and the current keystore is retained — a bad edit
    doesn't lock legitimate callers out.
    """

    def __init__(
        self,
        path: str | Path,
        apply: Any,
        *,
        interval_sec: float = 30.0,
    ) -> None:
        self._path = Path(path)
        # `apply` receives the newly-parsed keystore dict; the caller
        # decides how to swap it in (usually `setattr(app.state, ...)`).
        self._apply = apply
        self._interval = float(interval_sec)
        self._last_mtime: float | None = None

    async def initial_load(self) -> dict[str, ApiKeyPrincipal]:
        """Load once at startup, seed `_last_mtime`.

        Raises rather than returning empty on a bad initial file:
        booting an auth-on app with a broken keystore should fail
        fast, not silently allow everyone in.
        """
        stat = self._path.stat()
        self._last_mtime = stat.st_mtime
        keys = load_keystore_from_file(self._path)
        log.info(
            "keystore_initial_load",
            extra={"path": str(self._path), "n_keys": len(keys)},
        )
        return keys

    async def run(self) -> None:
        """Poll loop — cancelled by the lifespan on shutdown."""
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self._check_once()
            except asyncio.CancelledError:
                log.info(
                    "keystore_reloader_stopped",
                    extra={"path": str(self._path)},
                )
                raise
            except Exception:  # noqa: BLE001
                # Never let a bad poll iteration kill the reloader.
                log.exception(
                    "keystore_reloader_iteration_failed",
                    extra={"path": str(self._path)},
                )

    async def _check_once(self) -> None:
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            log.warning(
                "keystore_file_missing",
                extra={"path": str(self._path)},
            )
            return
        if self._last_mtime is not None and mtime == self._last_mtime:
            return
        try:
            keys = load_keystore_from_file(self._path)
        except ValueError as exc:
            log.error(
                "keystore_reload_parse_failed",
                extra={"path": str(self._path), "error": str(exc)},
            )
            return
        self._last_mtime = mtime
        result = self._apply(keys)
        if isinstance(result, Awaitable):
            await result
        log.info(
            "keystore_reloaded",
            extra={"path": str(self._path), "n_keys": len(keys)},
        )


async def require_principal(request: Request) -> ApiKeyPrincipal | None:
    """FastAPI dependency: validate `X-API-Key` when auth is on.

    Returns `None` in the auth-off path so tests and local dev keep
    working. Returns an `ApiKeyPrincipal` in the auth-on path;
    raises `MissingApiKey` / `InvalidApiKey` (both 401) otherwise.

    Reads the app-scoped keystore from `request.app.state.api_keys`
    — populated at startup by `create_app`. Missing keystore under
    `enable_api_auth=True` is a misconfiguration, not a policy
    lookup miss; raise 500 so the operator sees it.
    """
    if not settings.enable_api_auth:
        return None

    keystore: dict[str, ApiKeyPrincipal] | None = getattr(
        request.app.state, "api_keys", None
    )
    if not keystore:
        raise ApiAuthMisconfigured(
            log_detail="enable_api_auth is on and app.state.api_keys is empty"
        )

    presented = request.headers.get(API_KEY_HEADER)
    if not presented:
        raise MissingApiKey(
            headers={"WWW-Authenticate": f"ApiKey header={API_KEY_HEADER}"}
        )

    principal = _lookup_principal(presented, keystore)
    if principal is None:
        # Deliberately does not say *which* key was presented, and
        # never echoes it: an error body is a log line somebody else
        # can read.
        raise InvalidApiKey()
    return principal


async def enforce_rate_limit(
    request: Request, principal: ApiKeyPrincipal | None
) -> None:
    """Apply the per-key hourly limit — call from mutating routes.

    No-op when auth is off (`principal is None`) or when no limiter
    is bound. Otherwise records the submit and raises 429 when the
    key is over quota. Async because the Redis backend is async;
    the in-memory backend also awaits an `asyncio.Lock`.
    """
    if principal is None:
        return
    limiter: RateLimiter | None = getattr(
        request.app.state, "rate_limiter", None
    )
    if limiter is None:
        return
    await limiter.check_and_record(principal.key_id)
