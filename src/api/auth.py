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

from fastapi import HTTPException, Request, status

from src.config import settings
from src.observability import get_logger

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
    accidentally share a key.
    """
    keys: dict[str, ApiKeyPrincipal] = {}
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
    match: ApiKeyPrincipal | None = None
    for secret, principal in keystore.items():
        if hmac.compare_digest(secret, presented):
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


def _raise_429(key_id: str, limit_per_hour: int, retry_after_sec: int) -> None:
    """Shared 429 response shape so both backends emit the same
    detail + Retry-After header."""
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "rate_limited",
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
                _raise_429(key_id, self.limit_per_hour, retry_after)
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

    def _key(self, key_id: str) -> str:
        return f"{self._key_prefix}{key_id}"

    async def check_and_record(
        self, key_id: str, *, now: float | None = None
    ) -> None:
        ts = now if now is not None else time.time()
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
        if current_count > self.limit_per_hour:
            # Over cap: roll back this record and 429.
            await self._client.zrem(redis_key, member)
            # Retry-After = seconds until the oldest surviving entry
            # falls out of the window.
            oldest = await self._client.zrange(
                redis_key, 0, 0, withscores=True
            )
            if oldest:
                _, oldest_ts = oldest[0]
                retry_after = int(float(oldest_ts) + self.window_sec - ts) + 1
            else:
                retry_after = self.window_sec
            _raise_429(key_id, self.limit_per_hour, retry_after)


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

    Same duplicate-secret + empty-value validation as
    `parse_api_keys`. Errors raise `ValueError` with the path in
    the message so log grep pinpoints the bad file.
    """
    text = Path(path).read_text(encoding="utf-8")
    try:
        raw = json.loads(text)
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
    raises `HTTPException(401)` on missing / unknown key.

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="api_auth_misconfigured",
        )

    presented = request.headers.get(API_KEY_HEADER)
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_api_key",
            headers={"WWW-Authenticate": f"ApiKey header={API_KEY_HEADER}"},
        )

    principal = _lookup_principal(presented, keystore)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_api_key",
        )
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
