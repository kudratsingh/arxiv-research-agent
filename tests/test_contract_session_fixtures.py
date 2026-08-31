"""WO-W03 endpoint recordings stay valid against their OpenAPI models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.api.sessions import SessionAccepted, SessionDetail, SessionTurnAccepted

pytestmark = pytest.mark.unit

FIXTURE_ROOT = Path("web/contract/fixtures")


def _body(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURE_ROOT / f"{name}.json").read_text())
    assert isinstance(value, dict)
    body = value.get("body")
    assert isinstance(body, dict)
    return body


def test_session_endpoint_recordings_match_response_models() -> None:
    accepted = SessionAccepted.model_validate(_body("learn.session.accepted"))
    awaiting = SessionDetail.model_validate(_body("learn.session.awaiting"))
    turn = SessionTurnAccepted.model_validate(_body("learn.session.turn.accepted"))

    assert accepted.session_id == awaiting.session_id == turn.session_id
    assert awaiting.status == "awaiting_learner"
    assert awaiting.turn is not None
    assert awaiting.turn["kind"] == "reflection"
    assert turn.accepted is True
