"""The published four-request packet is inactive and bound to exact current code."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.workspace import d5_compatibility as ctl
from src.workspace import d5_compatibility_packet as previous
from src.workspace import d5_consistency_packet as spec
from src.workspace.admission import _digest
from src.workspace.d5_benchmark import read

pytestmark = [pytest.mark.unit, pytest.mark.contract]
ROOT = (
    Path(__file__).resolve().parents[1]
    / "planning/15-evaluation-audit-and-recovery/evidence/consistency-v18"
)


def test_frozen_four_request_artifacts_match_actual_code_schemas_and_operator():
    packet = read(ROOT / "packet.json.gz")
    spec.verify(packet)
    identity = read(ROOT / "IDENTITY.json")
    proposal = read(ROOT / "PROPOSAL.json")
    assert identity["packet"] == packet["packet_digest"] == proposal["packet_digest"]
    assert (
        identity["proposal"]
        == proposal["proposal_digest"]
        == _digest({k: v for k, v in proposal.items() if k != "proposal_digest"})
    )
    assert identity["compile_inputs_digest"] == _digest(previous.compile_inputs(packet))
    assert identity["frozen_code_digest"] == _digest(packet["code"])
    assert proposal["application"] == identity["application"]
    assert packet["limits"] == {
        "jobs": 4,
        "messages": 4,
        "counts": 4,
        "new_USD": "1.40",
        "concurrency": 1,
    }
    assert tuple(c["id"] for c in packet["cases"]) == spec.ORDER
    assert not packet["new_approval"] and not identity["approved"] and not proposal["approved"]
    assert read(ROOT / "AUTHORIZATION-TEMPLATE.json") == ctl.template(packet)
    index = read(ROOT / "REQUEST-INDEX.json")["requests"]
    for case, row in zip(packet["cases"], index, strict=True):
        directory = ROOT / "requests" / case["id"]
        assert read(directory / "message.json.gz") == case["body"]
        assert read(directory / "local-schema.json.gz") == case["schemas"]["local"]
        assert read(directory / "wire-schema.json.gz") == case["schemas"]["wire"]
        assert read(directory / "public-context.json.gz") == case["context"]
        count = read(directory / "paired-count.json.gz")
        assert count == {
            k: v for k, v in case["body"].items() if k not in {"max_tokens", "temperature"}
        }
        assert _digest(count) == row["count_digest"] == case["count_digest"]
        assert _digest(case["body"]) == row["request_digest"] == case["request_digest"]
        assert _digest(case["schemas"]["wire"]) == row["wire_schema_digest"]
        if case["family"] == "checker":
            assert read(directory / "synthetic-fixed-draft.json.gz") == case["fixed_draft"]
    assert _digest(index) == proposal["request_index_digest"]
    assert proposal["capacity_or_expiry_change"] is False
    assert proposal["new_received_rejection_continuation_exception"] is False
    assert datetime.fromisoformat(packet["programme_expiry"]) == datetime(
        2026, 11, 21, 11, 3, 57, tzinfo=UTC
    )
    assert (
        packet["basis"]["known_usd"] == "2.252281" and packet["basis"]["unknown_usd"] == "2.275066"
    )
