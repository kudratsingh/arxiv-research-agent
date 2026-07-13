"""API-key authentication + per-key rate limiting (ADR 0033).

The FastAPI surface ships gated behind an `X-API-Key` header when
`settings.enable_api_auth` is on. Two orthogonal defenses live here:

- **Key authentication** — `require_principal` is a FastAPI
  dependency that reads `X-API-Key`, looks it up in the app-scoped
  keystore (parsed from `settings.api_keys` at startup), and returns
  an `ApiKeyPrincipal`. Missing / unknown key => 401.
- **Sliding-window rate limit** — `RateLimiter` records submit
  timestamps per principal and refuses when the trailing hour
  exceeds `settings.api_key_hourly_limit`. Refusal => 429 with a
  `Retry-After` header.

Both are opt-in behind `enable_api_auth` so the local-dev / eval
runner path (no key configured) keeps working unchanged. Under the
production-scale mandate this is the minimum viable gate to keep an
exposed deployment from draining the Anthropic account.

## Not in scope for this bundle

- **Per-principal ownership** on Jobs / Conversations. When auth is
  on, only holders of a valid key can hit the endpoints — so the
  "any anonymous user reads any conversation" issue is much reduced.
  A follow-up PR adds `principal_key_id` scoping on the stores so
  one authenticated tenant can't read another's data.
- **Rate limit persistence** — counters live in per-worker memory.
  Under multi-worker uvicorn the effective limit is
  `api_key_hourly_limit * n_workers`. Follow-up PR moves to Redis.
"""

from __future__ import annotations

import hmac
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from fastapi import HTTPException, Request, status

from src.config import settings

API_KEY_HEADER = "X-API-Key"


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


@dataclass
class RateLimiter:
    """In-memory sliding-window submit counter, keyed by principal.

    Not designed to be perfect — the goal is to keep a single API
    key from bursting past `api_key_hourly_limit` requests / hour.
    Bounded memory: each bucket is capped at the limit + a small
    slack so a stuck deque can't grow unbounded.
    """

    limit_per_hour: int
    window_sec: int = 3600
    _buckets: dict[str, deque[float]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def check_and_record(self, key_id: str, *, now: float | None = None) -> None:
        """Raise 429 when the principal is over quota; otherwise record.

        Records the submit timestamp on the same call — the caller
        does not need a separate "record" step, and the check +
        record are atomic under the lock.
        """
        ts = now if now is not None else time.time()
        cutoff = ts - self.window_sec
        with self._lock:
            bucket = self._buckets.setdefault(key_id, deque())
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit_per_hour:
                retry_after = int(bucket[0] + self.window_sec - ts) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "rate_limited",
                        "key_id": key_id,
                        "limit_per_hour": self.limit_per_hour,
                    },
                    headers={"Retry-After": str(max(retry_after, 1))},
                )
            bucket.append(ts)


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


def enforce_rate_limit(request: Request, principal: ApiKeyPrincipal | None) -> None:
    """Apply the per-key hourly limit — call from mutating routes.

    No-op when auth is off (`principal is None`) or when no limiter
    is bound. Otherwise records the submit and raises 429 when the
    key is over quota.
    """
    if principal is None:
        return
    limiter: RateLimiter | None = getattr(
        request.app.state, "rate_limiter", None
    )
    if limiter is None:
        return
    limiter.check_and_record(principal.key_id)
