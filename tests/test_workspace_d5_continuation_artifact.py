"""Frozen v20 deliverables must describe the actual inactive executable requests."""

import gzip
import hashlib
import json
from pathlib import Path

import pytest

from src.workspace.admission import _digest
from src.workspace.d5_continuation_packet import compile_packet, template, verify_packet
from src.workspace.provider_schema_compat import guard

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "planning/15-evaluation-audit-and-recovery/evidence/behavior-v20"


def read(name):
    path = PACKAGE / name
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def test_delivered_initial_requests_match_the_protected_runner_and_count_bodies():
    packet = read("packet.json.gz")
    verify_packet(packet)
    compiled = compile_packet(packet)
    index = read("REQUEST-INDEX.json")
    assert list(index) == packet["schedule"] == list(compiled)
    sources = {case["id"]: case for case in [*packet["cases"], *packet["probes"]]}
    for key, metadata in index.items():
        source = sources[key]
        wire = source["wire"] if "wire" in source else source["sealed"]["candidate_initial_wire"]
        message = read(f"requests/{key}.initial.json")
        count = read(f"requests/{key}.paired-count.json")
        assert message == wire
        assert count == {k: v for k, v in message.items() if k not in {"max_tokens", "temperature"}}
        assert metadata["initial_message_digest"] == _digest(message)
        assert metadata["initial_paired_count_digest"] == _digest(count)
        assert metadata["input_digest"] == _digest(compiled[key]["input"])
        guard(message)
        guard(count)


def test_shipped_template_has_no_live_approval_and_mock_proof_is_not_quality_credit():
    packet = read("packet.json.gz")
    authorization = read("AUTHORIZATION-TEMPLATE.json")
    assert authorization == template(packet)
    assert authorization["approved"] is False
    assert authorization["expires_at"] is None
    assert authorization["approved_by"] is authorization["approval_source"] is None
    assert authorization["historical_uncertainty_exception_approved"] is False
    proof = read("PROTECTED-MOCK-REPLAY.json")
    assert proof["packet_digest"] == packet["packet_digest"]
    assert proof["quality"] == "HOLD"
    assert proof["human_labels"] is None
    assert proof["provider_contacts"] == 0 and proof["new_spend_USD"] == "0"
    assert proof["actual_mock_messages"] == proof["actual_mock_counts"] == 28
    assert set(proof["cases"]) == set(packet["schedule"])
    assert all(value["state"] == "ready" for value in proof["cases"].values())
    assert all(value["binding"] == "bound" for value in proof["probe_bindings"].values())


def test_public_identity_and_manifest_preserve_the_exact_frozen_bytes():
    packet = read("packet.json.gz")
    identity = read("IDENTITY.json")
    assert identity["packet_digest"] == packet["packet_digest"]
    assert (
        identity["packet_file_sha256"]
        == hashlib.sha256((PACKAGE / "packet.json.gz").read_bytes()).hexdigest()
    )
    assert identity["proposal_digest"] == packet["campaign_extension"]["proposal_digest"]
    assert identity["application_commit"] == packet["application_commit"]
    assert identity["new_scope"] == {"jobs": 10, "messages": 28, "paired_counts": 28, "USD": "9.20"}
    manifest = read("MANIFEST.json")
    assert manifest["packet_digest"] == packet["packet_digest"]
    paths = [row["path"] for row in manifest["files"]]
    assert len(paths) == len(set(paths))
    assert {
        "packet.json.gz",
        "REQUEST-INDEX.json",
        "PROPOSAL.json",
        "AUTHORIZATION-TEMPLATE.json",
    } <= set(paths)
    for row in manifest["files"]:
        path = (PACKAGE / row["path"]).resolve()
        assert path.is_relative_to(PACKAGE.resolve())
        assert path.stat().st_size == row["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]


def test_synthetic_behavior_reachability_does_not_grant_full_fulfillment_or_quality():
    proof = read("SCORING-DEMONSTRATION.json")
    assert proof["unchanged_v19_gate"] == {
        "possible_met_parts": 7,
        "required_met_parts": 24,
        "reachable": False,
    }
    current = proof["prospective_four_case_reachability"]
    assert current["behavioral_gate"] == "PASS" and current["machine_quality"] == "HOLD"
    assert current["denominators"]["reviewed_claim_findings"] == 21
    assert current["request_fulfillment_counts"] == {
        "met": 3,
        "partial": 5,
        "unmet": 4,
        "omitted_answer": 0,
        "unsupported_answer": 0,
        "UNSCORED": 0,
    }
    assert proof["claim_truth_established"] is False
    assert proof["independent_labels"] is False and proof["human_labels"] is None
