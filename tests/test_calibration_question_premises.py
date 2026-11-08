"""Blinding, fixed-denominator prose scoring and protected probe MockTransport.

Every expected label below is SYNTHETIC. Real reviewer worksheets remain blank.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from src.calibration import question_premises as q
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_authorization import case_bindings, record_external
from src.workspace.d5_scope import limits_for
from src.workspace.qualification_budget import census
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_d5_procedural_intents import source

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
SEEDS = Path(__file__).parent / "fixtures/d5/question-premises/seeds.json.gz"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def suite():
    return q.build(q.read(SEEDS)["seeds"][3:4], seed=7319, salt="synthetic-evaluator-only-salt")


def labels(worksheet, key, *, provenance="synthetic"):
    result = deepcopy(worksheet)
    for r in result["items"]:
        k = key["items"][r["id"]]
        r.update(
            reviewer="Synthetic grader fixture"
            if provenance == "synthetic"
            else "Test declared reviewer",
            reviewed_at="2026-11-08T00:00:00Z",
            provenance=provenance,
        )
        r["judgments"].update(
            premise=k["proposed_premise"],
            expected_disposition=k["proposed_disposition"],
            reason="Synthetic logic fixture; not actual human evidence.",
        )
    return result


def verdict(probe, decision="pass"):
    ctx = json.loads(probe["body"]["messages"][0]["content"])
    return {
        "checks": [
            {
                "claim_id": x["claim_id"],
                "input_digest": x["input_digest"],
                "decision": "supported",
                "reason": "Synthetic claim support, separate from prose disposition.",
            }
            for x in ctx["claim_inputs"]
        ],
        "prose_review": {
            "pass": "procedural_only",
            "reject": "unscored_factual_content",
            "abstain": "abstain",
        }[decision],
        "prose_findings": []
        if decision == "pass"
        else [
            {
                "field": "questions",
                "index": probe["target"]["index"],
                "reason": "Synthetic located premise decision.",
            }
        ],
    }


async def test_matched_sets_are_opaque_reproducible_and_only_question_varies():
    seeds = q.read(SEEDS)["seeds"]
    packet, key, worksheet = q.build(seeds, seed=7319, salt="private-synthetic-salt")
    assert (packet, key, worksheet) == q.build(seeds, seed=7319, salt="private-synthetic-salt")
    assert len(packet["probes"]) == 28 and len(key["items"]) == 28
    assert len([s for s in seeds if s["cohort"] == "regression"]) == 3
    for s in seeds:
        group = [p for p in packet["probes"] if key["items"][p["id"]]["matched_set"] == s["key"]]
        assert len(group) == 4
        baseline = None
        for p in group:
            ctx = json.loads(p["body"]["messages"][0]["content"])
            assert "expected_label" not in json.dumps(p["body"]) and s["key"] not in json.dumps(
                p["body"]
            )
            assert len(ctx["draft"]["claims"]) == len(s["context"]["draft"]["claims"])
            ctx["unscored_prose"]["questions"][s["slot"]] = "<only changed slot>"
            if baseline is None:
                baseline = ctx
            assert baseline == ctx
    assert all(all(v is None for v in r["judgments"].values()) for r in worksheet["items"])
    q.validate_packet(packet)


async def test_exact_false_pass_false_reject_and_separate_claim_support():
    p, key, w = suite()
    responses = {
        x["id"]: verdict(
            x, "pass" if key["items"][x["id"]]["proposed_disposition"] == "accept" else "reject"
        )
        for x in p["probes"]
    }
    ids = {v["variant"]: k for k, v in key["items"].items()}
    responses[ids["unsupported_premise"]] = verdict(
        next(x for x in p["probes"] if x["id"] == ids["unsupported_premise"]), "pass"
    )
    responses[ids["neutral"]] = verdict(
        next(x for x in p["probes"] if x["id"] == ids["neutral"]), "reject"
    )
    r = q.score(p, responses, labels(w, key))
    assert r["prose"]["false_pass"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert r["prose"]["false_reject"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert r["claim_support_machine_only"] == {"supported": 4, "unsupported": 0, "abstain": 0}
    assert not r["checker_qualified"] and r["outcome"] == "HOLD"  # synthetic labels


async def test_abstention_missing_invalid_keep_every_intended_denominator():
    p, key, w = suite()
    ids = {v["variant"]: k for k, v in key["items"].items()}
    by = {x["id"]: x for x in p["probes"]}
    responses = {
        ids["neutral"]: verdict(by[ids["neutral"]], "abstain"),
        ids["scored_premise"]: verdict(by[ids["scored_premise"]], "reject"),
        ids["supported_unscored"]: verdict(by[ids["supported_unscored"]], "reject"),
    }
    responses[ids["scored_premise"]]["prose_findings"][0]["field"] = "proposal"
    responses[ids["scored_premise"]]["prose_findings"][0]["index"] = None
    r = q.score(p, responses, labels(w, key))
    assert r["counts"]["missing"] == 1 and r["counts"]["invalid"] == 1
    assert r["prose"]["false_pass"]["denominator"] == r["prose"]["false_reject"]["denominator"] == 2
    assert r["prose"]["acceptable_abstentions"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert r["prose"]["acceptable_operational_blocks"] == {
        "numerator": 2,
        "denominator": 2,
        "rate": 1.0,
    }
    assert r["prose"]["worst_case_false_pass"] == {"numerator": 1, "denominator": 2, "rate": 0.5}
    assert r["prose"]["response_coverage"] == {"numerator": 2, "denominator": 4, "rate": 0.5}


@pytest.mark.parametrize(
    "fault", ["missing_verdict", "wrong_index", "malformed_findings", "digest"]
)
async def test_invalid_findings_and_incomplete_claim_batches_are_not_passes(fault):
    p, key, w = suite()
    probe = p["probes"][0]
    payload = verdict(probe, "reject")
    if fault == "missing_verdict":
        payload["checks"] = []
    elif fault == "wrong_index":
        payload["prose_findings"][0]["index"] = 2
    elif fault == "digest":
        payload["checks"][0]["input_digest"] = "wrong"
    else:
        payload["prose_findings"] = []
    r = q.score(p, {probe["id"]: payload}, labels(w, key))
    assert (
        r["counts"]["invalid"] == 1 and r["counts"]["missing"] == 3 and r["counts"]["complete"] == 0
    )
    assert (
        r["prose"]["response_coverage"]["denominator"] == 4
        and r["prose"]["response_coverage"]["numerator"] == 0
    )


async def test_positive_or_negative_only_and_blank_labels_remain_unscored():
    p, key, w = suite()
    responses = {x["id"]: verdict(x) for x in p["probes"]}
    blank = q.score(p, responses, w)
    assert blank["outcome"] == "HOLD" and blank["prose"]["false_pass"]["rate"] is None
    for disposition in ["accept", "reject"]:
        reviews = labels(w, key, provenance="independent_human")
        for item in reviews["items"]:
            item["judgments"]["expected_disposition"] = disposition
        r = q.score(p, responses, reviews)
        assert r["outcome"] == "HOLD"
        assert (
            r["prose"]["false_pass" if disposition == "accept" else "false_reject"]["rate"] is None
        )


@pytest.mark.parametrize("fault", ["stale", "duplicate", "mutated", "no_attribution", "timestamp"])
async def test_reviews_are_input_bound_and_attributed(fault):
    p, key, w = suite()
    reviews = labels(w, key)
    if fault == "stale":
        reviews["packet_digest"] = "old"
    elif fault == "duplicate":
        reviews["items"].append(reviews["items"][0])
    elif fault == "mutated":
        reviews["items"][0]["question"] = "A different question"
    elif fault == "timestamp":
        reviews["items"][0]["reviewed_at"] = "2026-11-08T00:00:00"
    else:
        reviews["items"][0]["reviewer"] = None
    with pytest.raises(ValueError):
        q.score(p, {}, reviews)


def prepare_production_probe(store, variant):
    from src.calibration.premise_preflight import bind
    from src.workspace.d5_freeze import restore_input

    support.program(store)
    service, selection = source(store)
    sealed = service.preview("a", selection).request
    p, key, worksheet = q.build(
        q.read(SEEDS)["seeds"][:1], seed=7319, salt="synthetic-evaluator-only-salt"
    )
    probe = next(x for x in p["probes"] if key["items"][x["id"]]["variant"] == variant)
    compiled = {
        item["id"]: {
            "owner": "d5-premise-test",
            "stage": "D",
            "input": q.compile_probe(
                sealed, item, packet_digest=p["packet_digest"], scope_id="d5-premise-synthetic"
            ).snapshot(),
        }
        for item in p["probes"]
    }
    # Structural simulation of attributed reviews in a permanently offline DB.
    # These test objects never populate an actual independent-review worksheet.
    completed = labels(worksheet, key, provenance="independent_human")
    compiled = bind(p, completed, compiled, scope_id="d5-premise-synthetic")["compiled"]
    inputs = restore_input(compiled[probe["id"]]["input"])
    now = datetime.now(UTC)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
        history = census(conn, "a")
    receipt = {
        "approved": True,
        "approved_by": "Synthetic disposable fixture, not owner authority",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "packet_digest": p["packet_digest"],
        "scope_id": "d5-premise-synthetic",
        "limits": limits_for(inputs.settings),
        "members": ["d5-premise-test"],
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "transport_mode": "mock",
        "authorization_kind": "offline_fixture",
        "stages": ["D"],
    }
    record_external(
        store,
        packet_digest=p["packet_digest"],
        scope_id="d5-premise-synthetic",
        program_id="evaluation",
        compiled=compiled,
        receipt=receipt,
        expected_history=history,
    )
    return p, probe, inputs


@pytest.mark.parametrize("decision", ["pass", "reject", "abstain"])
async def test_production_checker_path_preserves_blind_body_and_diagnostic_outcome(
    store, decision, monkeypatch
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    p, probe, inputs = prepare_production_probe(store, "unsupported_premise")
    calls = []

    async def transport(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        assert body == probe["body"]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-premise",
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(verdict(probe, decision))}],
            },
        )

    adapter = q.PremiseProbeAdapter(
        store, "d5-premise-test", inputs, transport=httpx.MockTransport(transport)
    )
    job = adapter.start(inputs.settings["d5_request_id"])
    result = await adapter.advance(job["id"])
    assert (
        len(calls) == 2
        and result["state"] == "ready"
        and result["result"]["checker_qualified"] is False
    )
    assert (
        result["steps"][0]["output"]["prose_review"]
        == {"pass": "procedural_only", "reject": "unscored_factual_content", "abstain": "abstain"}[
            decision
        ]
    )
    assert result["workflow_usd"] == result["checker_usd"] == "0"


async def test_source_supported_unscored_is_a_contract_false_pass_not_unsupported_truth():
    p, key, w = suite()
    responses = {x["id"]: verdict(x, "pass") for x in p["probes"]}
    r = q.score(p, responses, labels(w, key))
    assert r["false_pass_by_premise"]["supported_unscored"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert r["false_pass_by_premise"]["unsupported"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert r["counts"]["false_pass"] == 2 and r["counts"]["unacceptable"] == 2


@pytest.mark.parametrize(
    "fault", ["permission", "producer", "request", "wire", "duplicate", "unknown_response"]
)
async def test_packet_and_request_bindings_refuse_drift(fault):
    p, key, w = suite()
    if fault == "unknown_response":
        with pytest.raises(ValueError, match="unknown_probe"):
            q.score(p, {"unknown": {}}, w)
        return
    if fault == "permission":
        p["approved"] = True
    elif fault == "producer":
        p["producer"] = {}
    elif fault == "duplicate":
        p["probes"].append(p["probes"][0])
    elif fault == "request":
        p["probes"][0]["body"]["max_tokens"] = 999
    else:
        p["probes"][0]["body"]["max_tokens"] = 999
        p["probes"][0]["request_digest"] = _digest(p["probes"][0]["body"])
    p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError):
        q.validate_packet(p)


async def test_invalid_matched_seed_and_blinding_leak_are_rejected():
    seeds = q.read(SEEDS)["seeds"][:1]
    with pytest.raises(ValueError):
        q.build(seeds, seed=1, salt="")
    with pytest.raises(ValueError):
        q.build(seeds + seeds, seed=1, salt="salt")
    bad = deepcopy(seeds)
    bad[0]["slot"] = 99
    with pytest.raises(ValueError):
        q.build(bad, seed=1, salt="salt")
    bad = deepcopy(seeds)
    bad[0]["context"]["unscored_prose"]["proposal"] = "expected_label: accept"
    with pytest.raises(ValueError, match="blinding_leak"):
        q.build(bad, seed=1, salt="salt")


@pytest.mark.parametrize("bad", ["field", "missing_verdict", "malformed"])
async def test_production_probe_refuses_invalid_results_without_replay(store, bad):
    _, probe, inputs = prepare_production_probe(store, "neutral")
    calls = []

    async def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        payload = verdict(probe, "reject")
        if bad == "field":
            payload["prose_findings"][0].update(field="proposal", index=None)
        elif bad == "missing_verdict":
            payload["checks"] = []
        else:
            payload["prose_findings"] = []
        return httpx.Response(
            200,
            json={
                "id": "synthetic-invalid-premise",
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(payload)}],
            },
        )

    adapter = q.PremiseProbeAdapter(
        store, "d5-premise-test", inputs, transport=httpx.MockTransport(transport)
    )
    job = adapter.start(inputs.settings["d5_request_id"])
    with pytest.raises(ValueError):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] == "failed" and result["result"] is None and len(calls) == 2


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("code_sha256", "wrong", "producer_drift"),
        ("request_digest", "wrong", "request_binding_drift"),
    ],
)
async def test_production_probe_binds_its_calibration_code_and_exact_request(
    store, field, value, error
):
    from dataclasses import replace

    _, _, inputs = prepare_production_probe(store, "neutral")
    changed = replace(
        inputs,
        settings={
            **inputs.settings,
            "premise_calibration": {**inputs.settings["premise_calibration"], field: value},
        },
    )

    async def never(_):
        raise AssertionError("No HTTP permitted")

    with pytest.raises(AdmissionError, match=error):
        q.PremiseProbeAdapter(
            store, "d5-premise-test", changed, transport=httpx.MockTransport(never)
        )


async def test_simulated_independent_reviews_exercise_pass_fail_and_uncertain_hold():
    # Synthetic test objects model attributed human inputs; no real worksheet is populated.
    p, key, w = suite()
    reviews = labels(w, key, provenance="independent_human")
    responses = {
        x["id"]: verdict(
            x, "pass" if key["items"][x["id"]]["proposed_disposition"] == "accept" else "reject"
        )
        for x in p["probes"]
    }
    r = q.score(p, responses, reviews)
    assert r["outcome"] == "PASS_OBSERVED_SMALL_SAMPLE" and not r["checker_qualified"]
    bad = next(x for x in p["probes"] if key["items"][x["id"]]["proposed_disposition"] == "reject")
    responses[bad["id"]] = verdict(bad, "pass")
    assert q.score(p, responses, reviews)["outcome"] == "FAIL"
    reviews["items"][0]["judgments"].update(premise="uncertain", expected_disposition="abstain")
    assert q.score(p, responses, reviews)["outcome"] == "HOLD"
