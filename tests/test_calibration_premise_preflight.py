"""Synthetic review declarations only; no actual human worksheet is populated."""

from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from src.calibration import premise_preflight as p
from src.calibration import question_premises as q
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_authorization import case_bindings
from tests import test_calibration_question_premises as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")


def example():
    packet, key, blank = support.suite()
    return packet, support.labels(blank, key, provenance="independent_human"), blank


def damage(reviews, fault):
    row = reviews["items"][0]
    if fault == "blank":
        row["judgments"] = dict.fromkeys(row["judgments"])
    elif fault == "uncertain":
        row["judgments"].update(premise="uncertain", expected_disposition="abstain")
    elif fault == "synthetic":
        row["provenance"] = "synthetic"
    elif fault == "stale":
        reviews["packet_digest"] = "old"
    elif fault == "mismatched":
        row["scored_claims"][0]["text"] += " changed"
    elif fault == "missing":
        reviews["items"].pop()
    elif fault == "duplicate":
        reviews["items"].append(deepcopy(row))
    elif fault == "attribution":
        row["reviewer"] = " "
    elif fault == "reason":
        row["judgments"]["reason"] = " "
    elif fault == "future":
        row["reviewed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    elif fault == "revision":
        reviews["revision"] = "wrong"
    elif fault == "one_direction":
        for item in reviews["items"]:
            item["judgments"].update(premise="none", expected_disposition="accept")
    elif fault == "contradiction":
        row["judgments"].update(premise="unsupported", expected_disposition="accept")


@pytest.mark.parametrize(
    "fault",
    [
        "blank",
        "uncertain",
        "synthetic",
        "stale",
        "mismatched",
        "missing",
        "duplicate",
        "attribution",
        "reason",
        "future",
        "revision",
        "one_direction",
        "contradiction",
    ],
)
async def test_refuses_invalid_reviews_before_any_transport(fault):
    packet, reviews, _ = example()
    damage(reviews, fault)
    with pytest.raises(AdmissionError):
        p.validate_reviews(packet, reviews)


async def test_validated_four_reviews_both_directions_and_content_digest():
    packet, reviews, _ = example()
    checked = p.validate_reviews(packet, reviews)
    assert checked["reviewed_items"] == 4 and checked["accept"] == checked["reject"] == 2
    assert checked["worksheet_digest"] == _digest(reviews)
    assert checked["probe_ids"] == [x["id"] for x in packet["probes"]]


@pytest.mark.parametrize(
    "fault",
    [
        "blank",
        "uncertain",
        "synthetic",
        "stale",
        "mismatched",
        "absent",
        "digest",
        "scope",
        "validator",
        "case",
        "request",
        "target",
        "envelope",
    ],
)
async def test_production_constructor_refuses_before_client_or_count(store, monkeypatch, fault):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    _, _, inputs = support.prepare_production_probe(store, "neutral")
    settings = deepcopy(inputs.settings)
    proof = p.unpack_proof(settings["premise_calibration"]["preflight"])
    if fault in {"blank", "uncertain", "synthetic", "stale", "mismatched"}:
        damage(proof["reviews"], fault)
    elif fault == "absent":
        settings["premise_calibration"].pop("preflight")
    elif fault == "digest":
        proof["worksheet_digest"] = "wrong"
    elif fault == "scope":
        proof["scope_id"] = "d5-other"
    elif fault == "validator":
        proof["validator_sha256"] = "wrong"
    elif fault == "envelope":
        proof["envelope"]["jobs"] = 5
    elif fault == "case":
        settings["d5_case_id"] = "other"
    elif fault == "request":
        settings["d5_request_id"] += "-other"
    else:
        settings["premise_calibration"]["target"] = {"field": "questions", "index": 1}
    if fault != "absent":
        settings["premise_calibration"]["preflight"] = p.pack_proof(proof)
    calls = []

    async def never(request):
        calls.append(request)
        raise AssertionError("No mocked contact may be reached")

    def no_client(*args, **kwargs):
        raise AssertionError("Invalid prereview must refuse before client construction")

    monkeypatch.setattr(httpx, "AsyncClient", no_client)
    with pytest.raises(AdmissionError):
        q.PremiseProbeAdapter(
            store,
            "d5-premise-test",
            replace(inputs, settings=settings),
            transport=httpx.MockTransport(never),
        )
    assert calls == []


def compiled_inputs(packet, inputs):
    compiled = {}
    for probe in packet["probes"]:
        raw = inputs.snapshot()
        raw["settings"] = deepcopy(raw["settings"])
        settings = raw["settings"]
        settings.update(
            d5_case_id=probe["id"],
            d5_request_id="d5-premise-synthetic-" + probe["id"],
            probe_wire_digest=probe["request_digest"],
        )
        context = json.loads(probe["body"]["messages"][0]["content"])
        settings["probe_context"]["unscored_prose"] = context["unscored_prose"]
        settings["premise_calibration"].update(
            request_digest=probe["request_digest"], target=probe["target"]
        )
        compiled[probe["id"]] = {"owner": "d5-premise-test", "stage": "D", "input": raw}
    return compiled


async def test_scope_and_all_input_hashes_change_with_review_only(store):
    packet, _, inputs = support.prepare_production_probe(store, "neutral")
    proof = p.unpack_proof(inputs.settings["premise_calibration"]["preflight"])
    compiled = compiled_inputs(packet, inputs)
    original = deepcopy(compiled)
    result = p.bind(packet, proof["reviews"], compiled, scope_id="d5-premise-synthetic")
    changed = deepcopy(proof["reviews"])
    changed["items"][0]["judgments"]["reason"] += " Additional review rationale."
    other = p.bind(packet, changed, compiled, scope_id="d5-premise-synthetic")
    assert compiled == original  # no caller mutation
    assert result["scope"]["case_bindings_digest"] == _digest(case_bindings(result["compiled"]))
    assert result["scope_digest"] != other["scope_digest"]
    assert all(
        result["scope"]["case_bindings"][i]["input_digest"]
        != other["scope"]["case_bindings"][i]["input_digest"]
        for i in compiled
    )
    assert result["approved"] is False and result["scope"]["approved"] is False
    for entry in result["compiled"].values():
        p.validate_bound_input(entry["input"])
    with pytest.raises(AdmissionError):
        p.bind(packet, changed, {}, scope_id="d5-premise-synthetic")


async def test_cli_blank_refuses_before_input_read_and_writes_hold(tmp_path):
    packet, _, blank = example()
    for name, value in (("packet", packet), ("blank", blank)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    out = tmp_path / "receipt.json"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.calibration.premise_preflight",
            "--packet",
            str(tmp_path / "packet.json"),
            "--reviews",
            str(tmp_path / "blank.json"),
            "--inputs",
            str(tmp_path / "must-not-read.json"),
            "--scope-id",
            "d5-test",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 2
    receipt = json.loads(out.read_text())
    assert receipt["status"] == "HOLD" and receipt["approved"] is False
    assert receipt["new_provider_contacts"] == 0 and receipt["new_spend_usd"] == "0"
    assert "must-not-read" not in receipt["reason"]


@pytest.mark.parametrize("value", [None, "not-base64", "A" * 24001, p.pack_proof({})[:-4]])
async def test_missing_malformed_or_truncated_proof_refuses(value):
    with pytest.raises(AdmissionError):
        p.unpack_proof(value)


async def test_cli_success_binds_exact_scope_inputs_and_raw_file_hash(
    store, tmp_path, monkeypatch, capsys
):
    packet, _, inputs = support.prepare_production_probe(store, "neutral")
    proof = p.unpack_proof(inputs.settings["premise_calibration"]["preflight"])
    compiled = compiled_inputs(packet, inputs)
    for name, value in (("packet", packet), ("reviews", proof["reviews"]), ("inputs", compiled)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    args = [
        "--packet",
        str(tmp_path / "packet.json"),
        "--reviews",
        str(tmp_path / "reviews.json"),
        "--inputs",
        str(tmp_path / "inputs.json"),
        "--scope-id",
        "d5-premise-synthetic",
        "--out",
        str(tmp_path / "receipt.json"),
    ]
    monkeypatch.setattr(sys, "argv", ["preflight", *args])
    p.main()
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["status"] == "READY_FOR_APPROVAL" and receipt["approved"] is False
    assert (
        receipt["review_file_sha256"]
        == p.hashlib.sha256((tmp_path / "reviews.json").read_bytes()).hexdigest()
    )
    assert receipt["receipt_digest"] == _digest(
        {k: v for k, v in receipt.items() if k != "receipt_digest"}
    )
    assert receipt["scope"]["worksheet_digest"] == receipt["reviews"]["worksheet_digest"]
    assert all(
        e["input"]["settings"]["premise_calibration"]["pre_review_digest"]
        == receipt["reviews"]["worksheet_digest"]
        for e in receipt["compiled"].values()
    )
    assert "independent_human" not in capsys.readouterr().out
    # Also test the real module invocation, with separate immutable output.
    args[-1] = str(tmp_path / "receipt-subprocess.json")
    done = subprocess.run(
        [sys.executable, "-m", "src.calibration.premise_preflight", *args],
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads((tmp_path / "receipt-subprocess.json").read_text()) == receipt
    # The old external scope grants are exact input hashes; a changed worksheet
    # cannot be attached to them by a caller claiming the same packet.
    changed = deepcopy(compiled)
    changed[next(iter(changed))]["input"]["settings"]["probe_context"]["unscored_prose"][
        "questions"
    ][0] += " mutation"
    with pytest.raises(AdmissionError):
        p.bind(packet, proof["reviews"], changed, scope_id="d5-premise-synthetic")
    with pytest.raises(AdmissionError):
        p.bind(packet, proof["reviews"], compiled, scope_id="bad")
    bad_model = deepcopy(compiled)
    bad_model[next(iter(bad_model))]["input"]["model_id"] = "claude-sonnet-5-5"
    with pytest.raises(AdmissionError, match="transmitted_request_drift"):
        p.bind(packet, proof["reviews"], bad_model, scope_id="d5-premise-synthetic")
    for field, value in (("owner", "owner"), ("stage", "B")):
        bad = deepcopy(compiled)
        bad[next(iter(bad))][field] = value
        with pytest.raises(AdmissionError):
            p.bind(packet, proof["reviews"], bad, scope_id="d5-premise-synthetic")
    bad = deepcopy(compiled)
    bad[next(iter(bad))]["input"]["settings"]["d5_case_id"] = "other"
    with pytest.raises(AdmissionError):
        p.bind(packet, proof["reviews"], bad, scope_id="d5-premise-synthetic")
    # Refusal through the same CLI entry point, before reading missing inputs.
    (tmp_path / "reviews.json").write_text(
        json.dumps(
            {"revision": packet["revision"], "packet_digest": packet["packet_digest"], "items": []}
        )
    )
    args[-1] = str(tmp_path / "refused.json")
    monkeypatch.setattr(sys, "argv", ["preflight", *args])
    with pytest.raises(SystemExit, match="2"):
        p.main()
    assert json.loads((tmp_path / "refused.json").read_text())["status"] == "HOLD"


@pytest.mark.parametrize("payload", ['{"reviewer":"a","reviewer":"b"}', "[]", "x" * 1_000_001])
async def test_review_reader_refuses_duplicate_keys_nonobjects_and_oversize(tmp_path, payload):
    path = tmp_path / "reviews.json"
    path.write_text(payload)
    with pytest.raises((AdmissionError, ValueError)):
        p.read_reviews(path)


async def test_proof_decoder_refuses_expansion_and_nonobject():
    for proof in ({"large": "x" * 1_000_001}, []):
        with pytest.raises(AdmissionError):
            p.unpack_proof(p.pack_proof(proof))
