"""API-key auth + rate limiting (ADR 0033).

Split into (a) pure-function tests over the auth module and (b) an
end-to-end HTTPX suite that exercises the FastAPI app under
`enable_api_auth=True` to prove the router-level dependency actually
gates every /research and /conversations route.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager

from src.api.app import create_app
from src.api.auth import (
    ApiKeyPrincipal,
    InMemoryRateLimiter,
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

    def test_duplicate_name_raises(self) -> None:
        # ADR 0042: the name is what rows get stamped with under
        # ADR 0036 ownership — two secrets sharing a name would
        # silently merge two tenants' data.
        with pytest.raises(ValueError, match="duplicate principal name"):
            parse_api_keys("internal:sk_a,internal:sk_b")


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
        with pytest.raises(Exception) as exc:
            await rl.check_and_record("k", now=103.0)
        # HTTPException isn't in the module's public exports so check
        # by attribute rather than isinstance.
        assert getattr(exc.value, "status_code", None) == 429
        assert "Retry-After" in getattr(exc.value, "headers", {})

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
