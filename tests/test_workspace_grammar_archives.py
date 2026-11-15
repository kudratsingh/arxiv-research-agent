"""Exact old requests are custody controls, never new provider-success evidence."""

import hashlib
import json
from pathlib import Path

import pytest

from src.workspace.admission import _digest
from src.workspace.d5_compatibility import GRAMMAR_ERROR
from src.workspace.provider_schema_compat import guard

pytestmark = [pytest.mark.unit, pytest.mark.contract]
ROOT = Path(__file__).parent / "fixtures/d5/grammar-v16r2"


def test_exact_archived_request_response_and_structural_facts():
    lineage = json.loads((ROOT / "LINEAGE.json").read_text())
    for name, entry in lineage["files"].items():
        raw = (ROOT / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"] and len(raw) == entry["bytes"]
    accepted = json.loads((ROOT / "v15r2-accepted-learn-request.json").read_text())
    rejected = json.loads((ROOT / "v16r2-rejected-learn-request.json").read_text())
    error = json.loads((ROOT / "v16r2-received-http400.json").read_text())
    assert accepted["model"] == rejected["model"] == "claude-sonnet-5-5"
    assert accepted["max_tokens"] == rejected["max_tokens"] == 8000
    assert accepted["thinking"] == rejected["thinking"] == {"type": "between_tools"}
    for body, size, defs, sha in [
        (accepted, 7531, 14, "68ffc868491d3e63f9d339ec3daa38ed3fc699536a1f079d8eb07c379bb0b9c1"),
        (rejected, 10565, 24, "17f952e22242130714f3862c6260962602389b4388ef4b458761912b45acd925"),
    ]:
        schema = body["output_config"]["format"]["schema"]
        assert len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()) == size
        assert len(schema["$defs"]) == defs and _digest(schema) == sha
        assert guard(body)["documented_limits_pass"]
    assert error["error"] == {"type": "invalid_request_error", "message": GRAMMAR_ERROR}
    assert "usage" not in error and error["request_id"] == "req_011Ch4ajrrUD98caVDiX8ybq"


@pytest.mark.parametrize("key", ["synthetic-placeholder", "synthetic-newline\nplaceholder"])
@pytest.mark.parametrize("transport", [False, True])
def test_diagnostic_reasons_never_persist_credentials_or_header_reprs(key, transport):
    import httpx

    from src.workspace.d5_compatibility import safe_reason

    for message in ("Header: " + key, "Header repr: " + repr(key)):
        error = httpx.LocalProtocolError(message) if transport else ValueError(message)
        reason = safe_reason(error, key)
        assert key not in reason and repr(key)[1:-1] not in reason
        assert reason == "LocalProtocolError" if transport else "[credential redacted]" in reason
