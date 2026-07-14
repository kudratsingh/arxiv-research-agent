"""Per-principal Job + Conversation scoping (ADR 0036).

ADR 0033 landed API-key auth but explicitly deferred ownership
scoping — once auth was on, only key holders could hit the
endpoints, but two different key holders could still read each
other's jobs and conversations. This closes that gap.

The tests come in two flavors:

- Pure ownership-helper tests over `_check_ownership` and
  `_principal_key_id` — cheap, no HTTP.
- End-to-end HTTPX tests with two API keys configured; verify
  that principal A's resources are 404 from principal B's
  perspective, and that A's list responses don't include B's rows.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import HTTPException

from src.api.app import create_app
from src.api.auth import ApiKeyPrincipal
from src.api.jobs import InMemoryJobStore
from src.api.routes import _check_ownership, _principal_key_id

pytestmark = pytest.mark.unit


class TestOwnershipHelper:
    def test_auth_off_never_blocks(self) -> None:
        # `caller is None` == auth off. Any resource is visible.
        _check_ownership(None, None, detail="job_not_found")
        _check_ownership("some_owner", None, detail="job_not_found")

    def test_auth_on_matching_key_passes(self) -> None:
        caller = ApiKeyPrincipal(key_id="alice")
        _check_ownership("alice", caller, detail="job_not_found")

    def test_auth_on_mismatched_key_returns_404(self) -> None:
        caller = ApiKeyPrincipal(key_id="alice")
        with pytest.raises(HTTPException) as exc:
            _check_ownership("bob", caller, detail="job_not_found")
        assert exc.value.status_code == 404
        # 404, not 403 — leaking "this exists but you can't touch it"
        # is an info-disclosure vector.
        assert exc.value.detail == "job_not_found"

    def test_auth_on_null_owner_is_invisible(self) -> None:
        """Legacy rows written before ADR 0036 have `principal_key_id=None`.
        Under auth-on they must NOT be visible — otherwise turning auth
        on doesn't actually isolate legacy data."""
        caller = ApiKeyPrincipal(key_id="alice")
        with pytest.raises(HTTPException) as exc:
            _check_ownership(None, caller, detail="conversation_not_found")
        assert exc.value.status_code == 404


class TestPrincipalKeyIdHelper:
    def test_auth_off_returns_none(self) -> None:
        assert _principal_key_id(None) is None

    def test_auth_on_returns_key_id(self) -> None:
        assert _principal_key_id(ApiKeyPrincipal(key_id="alice")) == "alice"


# ---- End-to-end cross-principal isolation -----------------------------


@pytest.fixture
async def two_principal_client() -> AsyncIterator[httpx.AsyncClient]:
    """Boot the app with auth on + two known keys.

    Alice: `X-API-Key: sk_alice`. Bob: `X-API-Key: sk_bob`.
    """
    from src.api import app as app_module
    from src.api import auth as auth_module
    from src.config import Settings

    overridden = Settings(
        enable_api_auth=True,
        api_keys="alice:sk_alice,bob:sk_bob",
    )
    # `settings` is imported at module-level in both — patch both
    # so `require_principal` and `create_app` see the override.
    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(app_module, "settings", overridden)
    mp.setattr(auth_module, "settings", overridden)

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

    mp.undo()


@pytest.mark.asyncio
async def test_bob_cannot_read_alices_conversation(
    two_principal_client: httpx.AsyncClient,
) -> None:
    client = two_principal_client

    # Alice creates a conversation.
    r = await client.post(
        "/conversations",
        json={"title": "alice thread"},
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 201
    conversation_id = r.json()["conversation_id"]

    # Alice can read it.
    r = await client.get(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "alice thread"

    # Bob gets 404 — indistinguishable from "id doesn't exist".
    r = await client.get(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_bob"},
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "conversation_not_found"


@pytest.mark.asyncio
async def test_bob_cannot_delete_alices_conversation(
    two_principal_client: httpx.AsyncClient,
) -> None:
    client = two_principal_client

    r = await client.post(
        "/conversations",
        json={"title": "alice's protected thread"},
        headers={"X-API-Key": "sk_alice"},
    )
    conversation_id = r.json()["conversation_id"]

    r = await client.delete(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_bob"},
    )
    assert r.status_code == 404

    # Confirm Alice's row is still there.
    r = await client.get(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_list_conversations_filters_by_principal(
    two_principal_client: httpx.AsyncClient,
) -> None:
    client = two_principal_client

    for title in ("alice A", "alice B"):
        await client.post(
            "/conversations",
            json={"title": title},
            headers={"X-API-Key": "sk_alice"},
        )
    for title in ("bob X", "bob Y", "bob Z"):
        await client.post(
            "/conversations",
            json={"title": title},
            headers={"X-API-Key": "sk_bob"},
        )

    r = await client.get(
        "/conversations", headers={"X-API-Key": "sk_alice"}
    )
    assert r.status_code == 200
    alice_titles = {c["title"] for c in r.json()}
    assert alice_titles == {"alice A", "alice B"}

    r = await client.get(
        "/conversations", headers={"X-API-Key": "sk_bob"}
    )
    assert r.status_code == 200
    bob_titles = {c["title"] for c in r.json()}
    assert bob_titles == {"bob X", "bob Y", "bob Z"}


@pytest.mark.asyncio
async def test_bob_cannot_start_a_job_in_alices_conversation(
    two_principal_client: httpx.AsyncClient,
) -> None:
    """Piggybacking on another principal's conversation is a real
    concern: `POST /research` accepts a `conversation_id`, so a
    caller could otherwise dump their (cost-bearing) job into
    someone else's thread and pollute the retriever."""
    client = two_principal_client

    r = await client.post(
        "/conversations",
        json={"title": "alice private"},
        headers={"X-API-Key": "sk_alice"},
    )
    conversation_id = r.json()["conversation_id"]

    r = await client.post(
        "/research",
        json={"query": "piggyback", "conversation_id": conversation_id},
        headers={"X-API-Key": "sk_bob"},
    )
    # 404 as if the conversation didn't exist — no leak that it's
    # someone else's.
    assert r.status_code == 404
    assert r.json()["detail"] == "conversation_not_found"


@pytest.mark.asyncio
async def test_alice_can_stream_her_own_conversation(
    two_principal_client: httpx.AsyncClient,
) -> None:
    """Positive case: same-principal access still works. Sanity-check
    the ownership plumbing didn't accidentally break authorized
    access."""
    client = two_principal_client

    r = await client.post(
        "/conversations",
        json={"title": "self-read"},
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 201
    conversation_id = r.json()["conversation_id"]

    r = await client.get(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 200

    # Delete cleanly too.
    r = await client.delete(
        f"/conversations/{conversation_id}",
        headers={"X-API-Key": "sk_alice"},
    )
    assert r.status_code == 204


# ---- Auth-off backward compat ----------------------------------------


@pytest.fixture
async def auth_off_client() -> AsyncIterator[httpx.AsyncClient]:
    """Same shape as `two_principal_client` but with auth OFF. Every
    request should behave exactly as pre-ADR-0036."""
    from src.api import app as app_module
    from src.api import auth as auth_module
    from src.config import Settings

    overridden = Settings(enable_api_auth=False)
    import pytest as _pytest

    mp = _pytest.MonkeyPatch()
    mp.setattr(app_module, "settings", overridden)
    mp.setattr(auth_module, "settings", overridden)

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

    mp.undo()


@pytest.mark.asyncio
async def test_auth_off_conversations_are_globally_visible(
    auth_off_client: httpx.AsyncClient,
) -> None:
    """Under auth off no principal is tracked; the demo-scale shared
    namespace stays intact."""
    r = await auth_off_client.post(
        "/conversations", json={"title": "public"}
    )
    conversation_id = r.json()["conversation_id"]

    # No `X-API-Key` header — auth off allows anonymous.
    r = await auth_off_client.get(f"/conversations/{conversation_id}")
    assert r.status_code == 200

    r = await auth_off_client.get("/conversations")
    assert any(c["title"] == "public" for c in r.json())
