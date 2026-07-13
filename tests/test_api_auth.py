"""API-key auth + rate limiting (ADR 0033).

Split into (a) pure-function tests over the auth module and (b) an
end-to-end HTTPX suite that exercises the FastAPI app under
`enable_api_auth=True` to prove the router-level dependency actually
gates every /research and /conversations route.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.api.app import create_app
from src.api.auth import (
    ApiKeyPrincipal,
    RateLimiter,
    _lookup_principal,
    parse_api_keys,
)
from src.api.jobs import InMemoryJobStore

pytestmark = pytest.mark.unit


class TestParseApiKeys:
    def test_empty_string_yields_empty_map(self) -> None:
        assert parse_api_keys("") == {}
        assert parse_api_keys("  ") == {}

    def test_parses_single_pair(self) -> None:
        keys = parse_api_keys("internal:sk_a")
        assert keys == {"sk_a": ApiKeyPrincipal(key_id="internal")}

    def test_parses_multiple_pairs_with_whitespace(self) -> None:
        keys = parse_api_keys(" internal:sk_a , partner:sk_b ,")
        assert keys == {
            "sk_a": ApiKeyPrincipal(key_id="internal"),
            "sk_b": ApiKeyPrincipal(key_id="partner"),
        }

    def test_missing_separator_raises(self) -> None:
        with pytest.raises(ValueError, match="separator"):
            parse_api_keys("just-a-secret")

    def test_empty_name_or_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            parse_api_keys(":sk_a")
        with pytest.raises(ValueError, match="empty"):
            parse_api_keys("name:")

    def test_duplicate_secret_raises(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            parse_api_keys("internal:sk_a,partner:sk_a")


class TestLookupPrincipal:
    def test_hit_returns_principal(self) -> None:
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        assert _lookup_principal("sk_a", store) == ApiKeyPrincipal(key_id="internal")

    def test_miss_returns_none(self) -> None:
        store = {"sk_a": ApiKeyPrincipal(key_id="internal")}
        assert _lookup_principal("sk_b", store) is None

    def test_empty_keystore_returns_none(self) -> None:
        assert _lookup_principal("sk_a", {}) is None


class TestRateLimiter:
    def test_under_limit_never_raises(self) -> None:
        rl = RateLimiter(limit_per_hour=5)
        for _ in range(5):
            rl.check_and_record("k")

    def test_over_limit_raises_429(self) -> None:
        rl = RateLimiter(limit_per_hour=3)
        rl.check_and_record("k", now=100.0)
        rl.check_and_record("k", now=101.0)
        rl.check_and_record("k", now=102.0)
        with pytest.raises(Exception) as exc:
            rl.check_and_record("k", now=103.0)
        # HTTPException isn't in the module's public exports so check
        # by attribute rather than isinstance.
        assert getattr(exc.value, "status_code", None) == 429
        assert "Retry-After" in getattr(exc.value, "headers", {})

    def test_window_slides(self) -> None:
        rl = RateLimiter(limit_per_hour=2, window_sec=100)
        rl.check_and_record("k", now=0.0)
        rl.check_and_record("k", now=50.0)
        # Third call at t=200 — earliest two are outside the 100s
        # window, so this should succeed.
        rl.check_and_record("k", now=200.0)

    def test_buckets_are_isolated_per_key(self) -> None:
        rl = RateLimiter(limit_per_hour=1)
        rl.check_and_record("alice", now=100.0)
        # Alice is at cap, but bob starts fresh.
        rl.check_and_record("bob", now=100.0)


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
