"""The learn fixtures are what the server actually returns.

The other contract fixtures in `web/contract/fixtures/` are recorded
bytes: CI consumes them and cannot re-derive them, because reproducing
them needs Docker, Redis, Postgres and a seeded stack.

The learn fixtures are different in a way worth exploiting. Their bodies
are a pure function of the manifests committed in `content/` — no store,
no seeding, no clock — so this test re-derives them from the live app on
every run. That makes the drift check *stronger* here than the recorded
bytes are elsewhere: a manifest edit that changes the API response fails
here immediately instead of waiting for someone to re-record.

`bash web/contract/record.sh learn` re-records them through the Next.js
proxy for a reviewer who wants the full transport; the bodies are
identical either way, which is what
`test_the_fixture_headers_say_how_they_were_made` keeps honest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import create_app
from src.config import Settings
from src.content import loader

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "web" / "contract" / "fixtures"

#: fixture name -> the request path it records.
CASES = {
    "learn.paths": "/learn/paths",
    "learn.path.detail": "/learn/paths/fixture-guided-read",
}


def _fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    )
    return payload


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(enable_learn_content=True)
    monkeypatch.setattr("src.api.learn.settings", settings)
    monkeypatch.setattr("src.content.loader.settings", settings)
    loader.clear_cache()


async def _live(path: str) -> tuple[int, Any]:
    app = create_app(build_workflow=lambda: object())
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(path)
    return response.status_code, response.json()


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_fixture_body_is_the_live_response(name: str) -> None:
    status_code, body = await _live(CASES[name])
    fixture = _fixture(name)
    assert fixture["status"] == status_code
    assert fixture["body"] == body


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_fixture_headers_say_how_they_were_made(name: str) -> None:
    recording = _fixture(name)["x-recording"]
    assert recording["authored"] is False
    assert len(recording["commit"]) == 40
    assert "record.sh" in recording["note"]
    assert "ASGITransport" in recording["transport"]


def test_the_listed_path_is_the_labelled_fixture_one() -> None:
    """WO-W15 c3: the demo renders the fixture path, banner and all."""
    body = _fixture("learn.paths")["body"]
    assert [p["path_id"] for p in body["paths"]] == ["fixture-guided-read"]
    assert body["paths"][0]["fixture"] is True
    assert body["paths"][0]["banner"].startswith("FIXTURE CONTENT")


def test_the_detail_fixture_carries_briefings_and_the_posture() -> None:
    body = _fixture("learn.path.detail")["body"]
    assert body["licensing"]["full_text"] == "link-out-only"
    assert len(body["entries"]) == 3
    for entry in body["entries"]:
        assert entry["canonical_url"].startswith("https://arxiv.org/abs/")
        assert "FIXTURE CONTENT" in entry["briefing_markdown"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_no_fixture_byte_offers_a_paper(name: str) -> None:
    """The posture, asserted on the bytes the frontend develops against."""
    raw = (FIXTURES / f"{name}.json").read_text(encoding="utf-8")
    assert "/pdf/" not in raw
    assert ".pdf" not in raw
    assert "youtube.com" not in raw
    assert "youtu.be" not in raw
