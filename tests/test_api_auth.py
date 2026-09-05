"""API-key auth + rate limiting (ADR 0033).

Split into (a) pure-function tests over the auth module, (b) an
end-to-end HTTPX suite that exercises the FastAPI app under
`enable_api_auth=True` to prove the router-level dependency actually
gates every /research and /conversations route, and (c) app-wiring
tests for the pieces `create_app` assembles from settings: the
HTTP-level 429 path, the file-backed hot-reload keystore (ADR 0037),
and the opt-in CORS middleware.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from src.api.app import create_app
from src.api.auth import (
    ApiKeyPrincipal,
    InMemoryRateLimiter,
    _lookup_principal,
    parse_api_keys,
)
from src.api.jobs import InMemoryJobStore
from src.config import Settings
from src.errors import RateLimitedError

pytestmark = [pytest.mark.unit, pytest.mark.security]


@asynccontextmanager
async def _booted_app(
    monkeypatch: pytest.MonkeyPatch, overridden: Settings
) -> AsyncIterator[httpx.AsyncClient]:
    """Boot `create_app` under an overridden `Settings` instance.

    Patches the module-level `settings` in both `src.api.app` (read
    at `create_app` time for keystore / limiter / CORS wiring) and
    `src.api.auth` (read per-request by `require_principal`). The
    lifespan runs so `app.state` is fully populated.
    """
    from src.api import app as app_module
    from src.api import auth as auth_module

    monkeypatch.setattr(app_module, "settings", overridden)
    monkeypatch.setattr(auth_module, "settings", overridden)

    app = create_app(
        build_workflow=lambda: MagicMock(),
        store=InMemoryJobStore(),
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


class TestParseApiKeys:
    def test_empty_string_yields_empty_map(self) -> None:
        assert parse_api_keys(SecretStr("")) == {}
        assert parse_api_keys(SecretStr("  ")) == {}

    def test_parses_single_pair(self) -> None:
        keys = parse_api_keys(SecretStr("internal:sk_a"))
        assert keys == {"sk_a": ApiKeyPrincipal(key_id="internal")}

    def test_parses_multiple_pairs_with_whitespace(self) -> None:
        keys = parse_api_keys(SecretStr(" internal:sk_a , partner:sk_b ,"))
        assert keys == {
            "sk_a": ApiKeyPrincipal(key_id="internal"),
            "sk_b": ApiKeyPrincipal(key_id="partner"),
        }

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="separator"):
            parse_api_keys(SecretStr("just-a-secret"))

    def test_empty_name_or_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_api_keys(SecretStr(":sk_a"))
        with pytest.raises(ValueError, match="empty"):
            parse_api_keys(SecretStr("name:"))

    def test_duplicate_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            parse_api_keys(SecretStr("internal:sk_a,partner:sk_a"))

    def test_duplicate_name_raises(self) -> None:
        # ADR 0042: the name is what rows get stamped with under
        # ADR 0036 ownership — two secrets sharing a name would
        # silently merge two tenants' data.
        with pytest.raises(ValueError, match="duplicate principal name"):
            parse_api_keys(SecretStr("internal:sk_a,internal:sk_b"))


class TestLoadKeystoreDuplicateNames:
    def test_duplicate_name_in_file_raises(self, tmp_path: Path) -> None:
        # `json.loads` alone would silently keep the LAST value for a
        # repeated key — the parser must reject instead (ADR 0042).
        path = tmp_path / "keys.json"
        path.write_text('{"partner": "sk_a", "partner": "sk_b"}')
        from src.api.auth import load_keystore_from_file

        with pytest.raises(ValueError, match="duplicate principal name"):
            load_keystore_from_file(path)


class TestLookupPrincipal:
    def test_hit_returns_principal(self) -> None:
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        assert _lookup_principal("sk_a", store) == ApiKeyPrincipal(key_id="internal")

    def test_miss_returns_none(self) -> None:
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        assert _lookup_principal("sk_b", store) is None

    def test_empty_keystore_returns_none(self) -> None:
        assert _lookup_principal("sk_a", {}) is None

    def test_non_ascii_presented_key_is_a_miss_not_a_crash(self) -> None:
        # `hmac.compare_digest` raises TypeError on non-ASCII str —
        # before ADR 0042 this was an unauthenticated 500. Starlette
        # decodes headers as latin-1, so the wire value for utf-8
        # bytes is the latin-1 view of them.
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        wire_view = "ключ".encode().decode("latin-1")
        assert _lookup_principal(wire_view, store) is None

    def test_non_latin1_direct_call_is_a_miss(self) -> None:
        # Not reachable over HTTP (headers arrive latin-1-decoded);
        # direct callers must still get a miss, not an encode error.
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        assert _lookup_principal("ключ", store) is None

    def test_ascii_key_matches_despite_non_ascii_secret_in_keystore(
        self,
    ) -> None:
        # The old str-comparison loop compared EVERY secret, so one
        # non-ASCII secret anywhere in the keystore 500'd every
        # request — including ones presenting a correct ASCII key.
        store = {
            "sk_a": ApiKeyPrincipal(key_id="internal"),
            "sk_café": ApiKeyPrincipal(key_id="partner"),
        }
        assert _lookup_principal("sk_a", store) == ApiKeyPrincipal(
            key_id="internal"
        )

    def test_non_ascii_secret_matches_its_utf8_wire_bytes(self) -> None:
        # A client sending the utf-8 bytes of a non-ASCII secret must
        # authenticate: the wire bytes are recovered from Starlette's
        # latin-1 decode and compared against the secret's utf-8.
        store = {"sk_café": ApiKeyPrincipal(key_id="partner")}
        wire_view = "sk_café".encode().decode("latin-1")
        assert _lookup_principal(wire_view, store) == ApiKeyPrincipal(
            key_id="partner"
        )


class TestInMemoryRateLimiter:
    @pytest.mark.asyncio
    async def test_under_limit_never_raises(self) -> None:
        rl = InMemoryRateLimiter(limit_per_hour=5)
        for _ in range(5):
            await rl.check_and_record("k")

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(self) -> None:
        rl = InMemoryRateLimiter(limit_per_hour=3)
        await rl.check_and_record("k", now=100.0)
        await rl.check_and_record("k", now=101.0)
        await rl.check_and_record("k", now=102.0)
        with pytest.raises(RateLimitedError) as exc:
            await rl.check_and_record("k", now=103.0)
        # ADR 0064: the limiter raises the taxonomy's `RateLimitedError`
        # rather than a bare `HTTPException`, so the status is read off
        # the class and the code is assertable.
        assert exc.value.http_status == 429
        assert exc.value.code == "rate_limited"
        assert exc.value.retryable is True
        assert "Retry-After" in (exc.value.headers or {})

    @pytest.mark.asyncio
    async def test_window_slides(self) -> None:
        rl = InMemoryRateLimiter(limit_per_hour=2, window_sec=100)
        await rl.check_and_record("k", now=0.0)
        await rl.check_and_record("k", now=50.0)
        # Third call at t=200 — earliest two are outside the 100s
        # window, so this should succeed.
        await rl.check_and_record("k", now=200.0)

    @pytest.mark.asyncio
    async def test_buckets_are_isolated_per_key(self) -> None:
        rl = InMemoryRateLimiter(limit_per_hour=1)
        await rl.check_and_record("alice", now=100.0)
        # Alice is at cap, but bob starts fresh.
        await rl.check_and_record("bob", now=100.0)


# ---- End-to-end route gating -------------------------------------------


@pytest.fixture
async def app_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """Boot the FastAPI app with auth on + a known key.

    Uses `asgi_lifespan.LifespanManager` so the lifespan runs (that's
    where `app.state.api_keys` gets populated). The routes under
    test either fail auth before touching the workflow, or hit
    `/conversations` which never invokes it — so a `MagicMock`
    factory is enough.
    """
    from src.api import app as app_module
    from src.api import auth as auth_module
    from src.config import Settings

    overridden = Settings(
        enable_api_auth=True, api_keys="internal:sk_test"
    )
    monkeypatch.setattr(app_module, "settings", overridden)
    monkeypatch.setattr(auth_module, "settings", overridden)

    app = create_app(
        build_workflow=lambda: MagicMock(),
        store=InMemoryJobStore(),
    )
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            yield client


@pytest.mark.asyncio
async def test_healthz_never_requires_key(app_client: httpx.AsyncClient) -> None:
    """`/healthz` must stay open — it's what the container orchestrator
    hits and blocking it behind a key breaks liveness probes."""
    r = await app_client.get("/healthz")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_submit_without_key_returns_401(
    app_client: httpx.AsyncClient,
) -> None:
    r = await app_client.post("/research", json={"query": "hi"})
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_api_key"


@pytest.mark.asyncio
async def test_submit_with_bad_key_returns_401(
    app_client: httpx.AsyncClient,
) -> None:
    r = await app_client.post(
        "/research",
        json={"query": "hi"},
        headers={"X-API-Key": "sk_wrong"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_conversation_list_gated(
    app_client: httpx.AsyncClient,
) -> None:
    """The unauthenticated info-disclosure bug from the audit —
    `GET /conversations` returning everyone's threads — is closed
    when auth is on."""
    r = await app_client.get("/conversations")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_conversation_delete_gated(
    app_client: httpx.AsyncClient,
) -> None:
    r = await app_client.delete("/conversations/anything")
    assert r.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_key",
    [
        "ключ".encode(),  # utf-8 Cyrillic — every byte >= 0x80
        b"sk_\xff",  # single high byte, curl-style probe
        b"sk_test\xc2\xa0",  # correct key + copy-pasted NBSP
    ],
)
async def test_non_ascii_key_returns_401_not_500(
    app_client: httpx.AsyncClient, raw_key: bytes
) -> None:
    """Regression for the ADR 0042 auth fix: any byte >= 0x80 in
    `X-API-Key` used to raise TypeError inside `hmac.compare_digest`
    and surface as an unauthenticated 500 with a traceback."""
    r = await app_client.post(
        "/research",
        json={"query": "hi"},
        headers={"X-API-Key": raw_key},  # type: ignore[dict-item]
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_valid_key_reaches_handler(
    app_client: httpx.AsyncClient,
) -> None:
    r = await app_client.post(
        "/conversations",
        json={"title": "gated demo"},
        headers={"X-API-Key": "sk_test"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "gated demo"


# ---- Rate limiting over HTTP -------------------------------------------


@pytest.mark.asyncio
async def test_submit_over_hourly_limit_returns_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Drive `POST /research` past `api_key_hourly_limit` through the
    real app and assert the 429 the audit found untested.

    The unit tests over `InMemoryRateLimiter` prove the window math;
    this proves the wiring — `submit_research` actually calls
    `enforce_rate_limit` with the limiter `create_app` built from
    settings. Delete that call and this test fails.
    """
    overridden = Settings(
        enable_api_auth=True,
        api_keys="internal:sk_test",
        api_key_hourly_limit=2,
    )
    async with _booted_app(monkeypatch, overridden) as client:
        for _ in range(2):
            r = await client.post(
                "/research",
                json={"query": "q", "hitl_bypass": True},
                headers={"X-API-Key": "sk_test"},
            )
            assert r.status_code == 202

        r = await client.post(
            "/research",
            json={"query": "q", "hitl_bypass": True},
            headers={"X-API-Key": "sk_test"},
        )
        assert r.status_code == 429
        detail = r.json()["detail"]
        assert detail["error"] == "rate_limited"
        assert detail["key_id"] == "internal"
        assert detail["limit_per_hour"] == 2
        # Retry-After tells a well-behaved client when the window
        # frees up; it must be present and positive.
        assert int(r.headers["Retry-After"]) >= 1

        # Read routes are not throttled — status polling while
        # rate-limited must keep working (ADR 0033: only the
        # LLM-cost-bearing submit route is limited).
        r = await client.get(
            "/conversations", headers={"X-API-Key": "sk_test"}
        )
        assert r.status_code == 200


# ---- File-backed keystore through create_app (ADR 0037) ----------------


@pytest.mark.asyncio
async def test_keystore_file_is_loaded_and_hot_reloaded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Boot with `api_keys_file` set: the file is the keystore, and a
    rotation on disk propagates without a restart.

    The reloader polls mtime every `api_keys_reload_interval_sec`
    (floored at 1s), so the rotation half of this test waits up to a
    few poll cycles. `os.utime` forces the mtime forward — same-second
    writes on coarse-mtime filesystems would otherwise be invisible.
    """
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps({"internal": "sk_old"}), encoding="utf-8")

    overridden = Settings(
        enable_api_auth=True,
        api_keys_file=str(keys_file),
        api_keys_reload_interval_sec=1,
    )
    async with _booted_app(monkeypatch, overridden) as client:
        # Initial load: the file's key is live, an unknown one is not.
        r = await client.post(
            "/conversations",
            json={"title": "file-keyed"},
            headers={"X-API-Key": "sk_old"},
        )
        assert r.status_code == 201
        r = await client.get(
            "/conversations", headers={"X-API-Key": "sk_new"}
        )
        assert r.status_code == 401

        # Rotate on disk. Bump mtime explicitly so the poll sees it.
        keys_file.write_text(
            json.dumps({"internal": "sk_new"}), encoding="utf-8"
        )
        future = time.time() + 10
        os.utime(keys_file, (future, future))

        deadline = time.monotonic() + 5.0
        status_code = None
        while time.monotonic() < deadline:
            r = await client.get(
                "/conversations", headers={"X-API-Key": "sk_new"}
            )
            status_code = r.status_code
            if status_code == 200:
                break
            await asyncio.sleep(0.1)
        assert status_code == 200, "rotated key never became live"

        # The revoked key stops working — rotation actually swaps the
        # keystore rather than unioning old + new.
        r = await client.get(
            "/conversations", headers={"X-API-Key": "sk_old"}
        )
        assert r.status_code == 401


# ---- CORS wiring through create_app (ADR 0033) -------------------------


@pytest.mark.asyncio
async def test_cors_enabled_when_origins_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overridden = Settings(
        api_cors_allow_origins="https://ui.example.com"
    )
    async with _booted_app(monkeypatch, overridden) as client:
        r = await client.get(
            "/healthz", headers={"Origin": "https://ui.example.com"}
        )
        assert (
            r.headers.get("access-control-allow-origin")
            == "https://ui.example.com"
        )

        # Preflight for the submit route with the auth header.
        r = await client.options(
            "/research",
            headers={
                "Origin": "https://ui.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        assert r.status_code == 200
        assert "POST" in r.headers.get("access-control-allow-methods", "")

        # An origin outside the allow-list gets no CORS grant.
        r = await client.get(
            "/healthz", headers={"Origin": "https://evil.example.com"}
        )
        assert "access-control-allow-origin" not in r.headers


@pytest.mark.asyncio
async def test_cors_absent_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty `api_cors_allow_origins` (the default) installs no CORS
    middleware at all — same-origin only."""
    async with _booted_app(monkeypatch, Settings()) as client:
        r = await client.get(
            "/healthz", headers={"Origin": "https://ui.example.com"}
        )
        assert "access-control-allow-origin" not in r.headers
