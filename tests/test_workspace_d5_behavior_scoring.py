"""Prospective D5 scorer controls with actual journal binding and synthetic judgments."""

import gzip
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import checker_context, initial_context, prepare_input
from src.workspace.d5_answerability import score_parts
from src.workspace.d5_behavior_scoring import POLICY, score_campaign
from src.workspace.d5_capacity_policy import DEADLINES
from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
from src.workspace.d5_comparison_transport import checker_payload, draft_payload
from src.workspace.d5_operations import wire
from src.workspace.d5_report_binding import message_output
from src.workspace.material import SourceMaterial, SourceSpan

pytestmark = pytest.mark.unit

PACKET_PATH = (
    Path(__file__).resolve().parents[1]
    / "planning/15-evaluation-audit-and-recovery/evidence/comparison-v19/packet.json.gz"
)


def read_packet():
    return json.loads(gzip.decompress(PACKET_PATH.read_bytes()))


def retained_materials(packet):
    return tuple(
        SourceMaterial(**{**source, "spans": tuple(SourceSpan(**span) for span in source["spans"])})
        for source in packet["materials"]
    )


def ideal_draft(case, reference, *, claim_count=3):
    context = initial_context(case["sealed"])
    payload = draft_payload(context, long=False)
    response = payload["response"]
    if response["disposition"] == "full_abstention":
        return payload
    rows = [
        row
        for row in reference["rows"]
        if row["case_id"] == case.get("reference_case_id", case["id"])
    ]
    units = case["sealed"]["units"]
    handles = list(units)
    # These findings exercise claim IDs and real evidence identity only. The
    # preassigned checker observations are not a semantic review of this text.
    response["claims"] = [
        {
            "text": f"Synthetic finding {index + 1}, exercising one whole-claim judgment.",
            "handles": [handles[index % len(handles)]],
            "required_scope": units[handles[index % len(handles)]]["scope"],
        }
        for index in range(claim_count)
    ]
    ids = [f"c{index + 1}" for index in range(claim_count)]
    response["background_claims"] = ids[:1]
    response["questions"][0]["context_claim_ids"] = ids[:1]
    for row in rows:
        status = {
            "answer": "answered",
            "bounded_partial_answer": "partial",
            "comparison_only_abstention": "lacks_evidence",
        }[row["expected_behavior"]]
        answers = ids if status != "lacks_evidence" else []
        response["coverage"][row["part_id"]] = {
            "status": status,
            "gap_reasons": {
                "answered": ["none"],
                "partial": ["methods"],
                "lacks_evidence": ["common_evaluation"],
            }[status],
            "answer_claim_ids": answers,
            "context_claim_ids": [] if answers else ids,
        }
    return payload


def synthetic_snapshot(case, draft, materials, routes, *, mutate_review=None, recheck=False):
    context = checker_context(case["sealed"], draft, materials)
    checker = checker_payload(context, long=False)
    if mutate_review:
        mutate_review(checker)
    steps, contacts = [], []
    initial = initial_context(case["sealed"])
    fixture_steps = [("draft", initial, draft), ("check", context, checker)]
    if recheck:
        fixture_steps.extend(
            [("repair", {**initial, "phase": "repair"}, draft), ("check", context, checker)]
        )
    for stage, call_context, payload in fixture_steps:
        body = wire(call_context, routes)
        request_digest = _digest(body)
        count_body = {
            name: value for name, value in body.items() if name not in {"max_tokens", "temperature"}
        }
        common = {
            "stage": stage,
            "state": "completed",
            "generation_request_digest": request_digest,
        }
        contacts.append(
            {
                **common,
                "ordinal": len(contacts),
                "endpoint": "messages/count_tokens",
                "body": count_body,
                "request_digest": _digest(count_body),
                "response": {"input_tokens": 100},
            }
        )
        message = {
            **common,
            "ordinal": len(contacts),
            "endpoint": "messages",
            "body": body,
            "request_digest": request_digest,
            "response": {
                "id": f"synthetic-{stage}",
                "type": "message",
                "model": body["model"],
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(payload)}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        }
        contacts.append(message)
        steps.append(
            {"stage": stage, "request_digest": request_digest, "output": message_output(message)}
        )
    return {
        "id": "synthetic-" + case["id"],
        "case_id": case["id"],
        "request": case["sealed"],
        "state": "ready",
        "simulated": True,
        "source_binding_intact": True,
        "workflow_usd": "0",
        "checker_usd": "0",
        "unknown_usd": "0",
        "latency_seconds": None,
        "steps": steps,
        "contacts": contacts,
    }


def ideal_snapshots(cases, packet, materials, *, claim_count=3):
    return {
        case["id"]: synthetic_snapshot(
            case,
            ideal_draft(case, packet["answerability"], claim_count=claim_count),
            materials,
            packet["operation_routes"],
        )
        for case in cases
        if case["cohort"] == "evaluation_exposed_corpus"
    }


@pytest.fixture(scope="module")
def frozen():
    packet = read_packet()
    materials = retained_materials(packet)
    snapshots = ideal_snapshots(packet["cases"], packet, materials)
    return packet, materials, snapshots


def score(packet, materials, snapshots, *, cases=None, probe_references=None, verdicts=None):
    references = packet["probe_references"] if probe_references is None else probe_references
    return score_campaign(
        packet["cases"] if cases is None else cases,
        snapshots,
        materials,
        packet["answerability"],
        references,
        {key: row["reference"] for key, row in references.items()}
        if verdicts is None
        else verdicts,
        routes=packet["operation_routes"],
    )


def test_ideal_control_passes_behavior_while_legacy_all_parts_met_gate_remains_impossible(frozen):
    packet, materials, snapshots = frozen
    before = _digest(snapshots)
    result = score(packet, materials, snapshots)
    assert result["scoring_policy"] == POLICY
    assert result["behavioral_gate"] == "PASS"
    assert result["machine_quality"] == "HOLD"
    assert not result["human_qualification"]
    assert result["denominators"] == {
        "evaluation_workflows": 8,
        "completed_workflows": 8,
        "reviewed_workflows": 8,
        "unrun_workflows": 0,
        "failed_workflows": 0,
        "generated_claim_findings": 21,
        "support_checked_claim_findings": 21,
        "reviewed_claim_findings": 21,
        "supported_claim_findings": 21,
        "unsupported_claim_findings": 0,
        "bundled_claim_findings": 0,
        "lost_qualifications": 0,
        "workflow_completion": 1,
        "unscored_claim_findings": 0,
        "requested_parts": 24,
        "scored_parts": 24,
        "unscored_parts": 0,
        "behaviorally_correct_parts": 24,
        "behaviorally_incorrect_parts": 0,
        "behavioral_correctness_among_scored": 1,
        "part_review_coverage": 1,
        "probe_records": 20,
        "human_reviewed_claims": 0,
    }
    assert result["request_fulfillment_counts"] == {
        "met": 7,
        "partial": 13,
        "unmet": 4,
        "omitted_answer": 0,
        "unsupported_answer": 0,
        "UNSCORED": 0,
    }
    assert sum(part["full_answer_credit"] for part in result["parts"]) == 7
    assert sum(row["reference_answerability"] == "insufficient" for row in result["parts"]) == 5
    condition = next(
        part
        for part in result["parts"]
        if part["case_id"] == "campaign-eval-learn-conditions" and part["part_id"] == "p1"
    )
    assert condition["reference_answerability"] == "insufficient"
    assert condition["behavior"] == "PASS" and condition["request_fulfillment"] == "partial"
    legacy = [
        row
        for workflow in result["workflows"]
        for row in score_parts(workflow, packet["answerability"])
    ]
    assert sum(row["request_fulfillment"] == "met" for row in legacy) == 7
    assert sum(row["request_fulfillment"] == "unmet" for row in legacy) == 17
    assert not all(row["request_fulfillment"] == "met" for row in legacy)
    assert _digest(snapshots) == before


def test_fresh_case_ids_bind_exact_original_references_and_keep_development_out(frozen):
    packet, materials, old_snapshots = frozen
    cases = [
        deepcopy(case)
        for case in packet["cases"]
        if case["cohort"] == "development" or "-eval-research-" in case["id"]
    ]
    for case in cases[2:]:
        case["reference_case_id"] = case["id"]
        case["protocol_cohort"] = "d5-behavior-continuation-v20"
        case["id"] = case["id"].replace("campaign-eval-", "continuation-v20-")
    snapshots = ideal_snapshots(cases, packet, materials, claim_count=7)
    result = score(packet, materials, old_snapshots | snapshots, cases=cases)
    assert result["behavioral_gate"] == "PASS"
    assert result["denominators"]["evaluation_workflows"] == 4
    assert result["denominators"]["requested_parts"] == 12
    assert result["denominators"]["reviewed_claim_findings"] == 21
    assert all(part["case_id"].startswith("continuation-v20-") for part in result["parts"])
    assert all(
        part["reference_case_id"].startswith("campaign-eval-research-") for part in result["parts"]
    )

    with pytest.raises(AdmissionError, match="behavior_evaluation_cohort_mixed"):
        score(packet, materials, old_snapshots | snapshots, cases=[*cases, packet["cases"][2]])

    incomplete = dict(snapshots)
    incomplete.pop(cases[-1]["id"])
    result = score(packet, materials, old_snapshots | incomplete, cases=cases)
    assert result["behavioral_gate"] == "HOLD"
    assert result["denominators"]["workflow_completion"] == 0.75
    assert result["denominators"]["unscored_parts"] == 3

    cases[-1]["sealed"]["task_policy"]["requested_parts"][0]["request"] += " Changed."
    with pytest.raises(AdmissionError, match="behavior_reference_part_binding_mismatch"):
        score(packet, materials, snapshots, cases=cases)


def test_omitting_available_content_can_fail_with_the_expected_status_label(frozen):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]
    draft = ideal_draft(case, packet["answerability"])

    def critique(raw):
        raw["coverage_checks"]["p1"]["critiques"] = ["Available finding omitted."]

    changed = synthetic_snapshot(
        case, draft, materials, packet["operation_routes"], mutate_review=critique
    )
    result = score(packet, materials, snapshots | {case["id"]: changed})
    part = result["parts"][0]
    assert part["current_machine_status"] == part["declared_status"] == "partial"
    assert part["behavior"] == result["behavioral_gate"] == "FAIL"
    assert part["errors"] == ["coverage_critique"]
    assert part["full_answer_credit"] is False


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("blanket_abstention", "unexpected_coverage"),
        ("false_completeness", "unexpected_coverage"),
        ("claim_budget_partial", "partial_requires_evidence_gaps"),
    ],
)
def test_status_casting_cannot_replace_the_expected_evidence_behavior(frozen, kind, error):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]
    draft = ideal_draft(case, packet["answerability"])
    coverage = draft["response"]["coverage"]
    if kind == "blanket_abstention":
        for part in coverage.values():
            part.update(
                status="lacks_evidence",
                gap_reasons=["source_scope"],
                context_claim_ids=part["answer_claim_ids"],
                answer_claim_ids=[],
            )
    elif kind == "false_completeness":
        coverage["p1"].update(status="answered", gap_reasons=["none"])
    else:
        coverage["p1"]["gap_reasons"] = ["claim_budget"]
    changed = synthetic_snapshot(case, draft, materials, packet["operation_routes"])
    result = score(packet, materials, snapshots | {case["id"]: changed})
    assert result["parts"][0]["behavior"] == result["behavioral_gate"] == "FAIL"
    assert error in result["parts"][0]["errors"]
    assert result["parts"][0]["full_answer_credit"] is False


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("unsupported_claim", "FAIL"),
        ("bundled_claim", "FAIL"),
        ("lost_qualification", "FAIL"),
        ("factual_prose", "FAIL"),
        ("priority_violation", "FAIL"),
        ("support_abstention", "HOLD"),
        ("uncertain_atomicity", "HOLD"),
        ("uncertain_qualification", "HOLD"),
        ("uncertain_coverage", "HOLD"),
        ("uncertain_prose", "HOLD"),
        ("uncertain_priority", "HOLD"),
    ],
)
def test_current_bound_judgments_gate_beyond_labels(frozen, kind, expected):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]
    draft = ideal_draft(case, packet["answerability"])

    def mutate(raw):
        claim = raw["claim_reviews"]["c1"]
        if kind in {"unsupported_claim", "support_abstention"}:
            claim["decision"] = "unsupported" if kind == "unsupported_claim" else "abstain"
        elif kind in {"bundled_claim", "uncertain_atomicity"}:
            claim["atomicity"] = "bundled" if kind == "bundled_claim" else "uncertain"
        elif kind in {"lost_qualification", "uncertain_qualification"}:
            claim["qualifications"]["conditions"] = (
                "lost" if kind == "lost_qualification" else "uncertain"
            )
        elif kind in {"factual_prose", "uncertain_prose"}:
            field = "prose_findings" if kind == "factual_prose" else "prose_uncertainties"
            raw[field][next(iter(raw[field]))] = ["Synthetic finding."]
        elif kind in {"priority_violation", "uncertain_priority"}:
            raw["priority_review"] = "violated" if kind == "priority_violation" else "uncertain"
        else:
            raw["coverage_checks"]["p1"]["decision"] = "uncertain"

    changed = synthetic_snapshot(
        case, draft, materials, packet["operation_routes"], mutate_review=mutate
    )
    result = score(packet, materials, snapshots | {case["id"]: changed})
    part = result["parts"][0]
    assert result["behavioral_gate"] == expected
    if expected == "HOLD":
        assert part["behavior"] == part["request_fulfillment"] == "UNSCORED"
        assert part["full_answer_credit"] is None
    else:
        assert part["behavior"] == "FAIL" and part["full_answer_credit"] is False
    if kind == "unsupported_claim":
        assert part["request_fulfillment"] == "unsupported_answer"
        assert result["denominators"]["unsupported_claim_findings"] == 1


@pytest.mark.parametrize("kind", ["no_check", "stale_check", "missing_quality", "wrong_case"])
def test_missing_or_unbound_judgments_are_unscored_even_with_supplied_bound_label(frozen, kind):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]
    changed = deepcopy(snapshots[case["id"]])
    if kind == "no_check":
        changed["steps"].pop()
        changed["contacts"] = changed["contacts"][:2]
    elif kind == "stale_check":
        current = changed["steps"][0]["output"]
        current["response"]["claims"][0]["text"] += " A changed current response."
        changed["contacts"][1]["response"]["content"][-1]["text"] = json.dumps(current)
    elif kind == "missing_quality":
        response = changed["contacts"][-1]["response"]["content"][-1]
        raw = json.loads(response["text"])
        raw["claim_reviews"]["c1"].pop("qualifications")
        response["text"] = json.dumps(raw)
    else:
        changed["case_id"] = "a-different-case"
    changed["assessment_binding"] = {"status": "bound"}
    result = score(packet, materials, snapshots | {case["id"]: changed})
    assert result["workflows"][0]["assessment_binding"]["status"] == "unavailable"
    assert result["behavioral_gate"] == "HOLD"
    assert result["denominators"]["unsupported_claim_findings"] == 0
    assert result["denominators"]["unscored_parts"] == 3
    if kind != "wrong_case":
        assert result["denominators"]["unscored_claim_findings"] == 3
    assert result["parts"][0]["full_answer_credit"] is None


@pytest.mark.parametrize("kind", ["reference_units", "retained_material"])
def test_invalid_provenance_cannot_receive_behavioral_credit(frozen, kind):
    packet, materials, snapshots = frozen
    case = deepcopy(packet["cases"][2])
    if kind == "reference_units":
        next(iter(case["sealed"]["units"].values()))["quote"] += " Altered."
    else:
        wrong = next(iter(case["sealed"]["units"].values()))["material_id"]
        materials = tuple(
            replace(item, source_hash="sha256:wrong") if item.material_id == wrong else item
            for item in materials
        )
    result = score(packet, materials, snapshots, cases=[case])
    assert result["behavioral_gate"] == "FAIL"
    assert result["workflows"][0]["reference_evidence_intact"] is False
    assert "invalid_provenance" in result["parts"][0]["errors"]
    assert result["parts"][0]["full_answer_credit"] is None


def test_empty_support_does_not_pass_the_claim_denominator_even_for_required_abstention(frozen):
    packet, materials, snapshots = frozen
    result = score(packet, materials, snapshots, cases=[packet["cases"][-1]])
    assert result["denominators"]["completed_workflows"] == 1
    assert result["denominators"]["behaviorally_correct_parts"] == 3
    assert result["denominators"]["reviewed_claim_findings"] == 0
    assert result["workflows"][0]["whole_claim_support"]["support_ratio"] is None
    assert result["behavioral_gate"] == "HOLD"
    assert "reviewed_claim_findings_below_minimum" in result["gate_reasons"]


@pytest.mark.parametrize(
    ("case_filter", "probe_mode", "expected"),
    [
        ("empty", "all", "HOLD"),
        ("all", "empty", "HOLD"),
        ("all", "missing", "HOLD"),
        ("all", "abstain", "HOLD"),
        ("all", "wrong", "FAIL"),
        ("all", "unbalanced", "HOLD"),
    ],
)
def test_empty_and_incomplete_denominators_or_checker_failures_cannot_pass(
    frozen, case_filter, probe_mode, expected
):
    packet, materials, snapshots = frozen
    refs = deepcopy(packet["probe_references"])
    verdicts = {key: row["reference"] for key, row in refs.items()}
    key = next(iter(refs))
    if probe_mode == "empty":
        refs = verdicts = {}
    elif probe_mode == "missing":
        verdicts.pop(key)
    elif probe_mode == "abstain":
        verdicts[key] = "abstain"
    elif probe_mode == "wrong":
        verdicts[key] = "unsupported" if verdicts[key] == "supported" else "supported"
    elif probe_mode == "unbalanced":
        refs.pop(key)
    result = score(
        packet,
        materials,
        snapshots,
        cases=[] if case_filter == "empty" else None,
        probe_references=refs,
        verdicts=verdicts,
    )
    assert result["behavioral_gate"] == expected
    if case_filter == "empty":
        assert result["denominators"]["workflow_completion"] is None
        assert result["denominators"]["behavioral_correctness_among_scored"] is None


@pytest.mark.parametrize(("decision", "gate"), [("unsupported", "FAIL"), ("abstain", "HOLD")])
def test_completed_terminal_recheck_preserves_contract_and_review_distinction(
    frozen, decision, gate
):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]

    def mutate(raw):
        raw["claim_reviews"]["c1"]["decision"] = decision

    changed = synthetic_snapshot(
        case,
        ideal_draft(case, packet["answerability"]),
        materials,
        packet["operation_routes"],
        mutate_review=mutate,
        recheck=True,
    )
    changed["state"] = "failed"
    result = score(packet, materials, snapshots | {case["id"]: changed})
    workflow = result["workflows"][0]
    assert workflow["assessment_binding"]["checker_ordinal"] == 7
    assert workflow["contract_complete"] and not workflow["completion"]
    assert result["denominators"]["failed_workflows"] == 1
    assert result["denominators"]["completed_workflows"] == 8
    assert result["behavioral_gate"] == gate


def test_unsupported_comparison_answer_fails_even_with_two_sources_and_clean_synthetic_check(
    frozen,
):
    packet, materials, _snapshots = frozen
    case = next(case for case in packet["cases"] if case["id"].endswith("-eval-research-retrieval"))
    draft = ideal_draft(case, packet["answerability"])
    response = draft["response"]
    response["claims"][0]["handles"] = list(case["sealed"]["units"])
    response["coverage"]["p1"].update(
        status="answered",
        gap_reasons=["none"],
        answer_claim_ids=["c1"],
        context_claim_ids=["c2", "c3"],
    )
    snapshot = synthetic_snapshot(case, draft, materials, packet["operation_routes"])
    result = score(packet, materials, {case["id"]: snapshot}, cases=[case])
    part = result["parts"][0]
    assert result["workflows"][0]["response_disposition"] == "answer"
    assert result["workflows"][0]["whole_claim_support"]["unsupported"] == 0
    assert part["behavior"] == result["behavioral_gate"] == "FAIL"
    assert part["request_fulfillment"] == "unsupported_answer"
    assert "comparison_abstention_required" in part["errors"]


@pytest.mark.parametrize(
    "field", ["valid", "units", "task_policy", "full_preview_digest", "missing"]
)
def test_compact_snapshot_requires_exact_canonical_request(frozen, field):
    packet, materials, snapshots = frozen
    case = packet["cases"][2]
    snapshot = deepcopy(snapshots[case["id"]])
    snapshot["packet_digest"] = packet["packet_digest"]
    snapshot["request"] = deepcopy(
        prepare_input(
            case["sealed"],
            scope_id="test-synthetic-compact",
            packet_digest=packet["packet_digest"],
            case_id=case["id"],
            capacity_policy=CAPACITY_POLICY,
            operation_deadlines=DEADLINES,
            operation_routes=packet["operation_routes"],
        ).settings["d5_request"]
    )
    assert snapshot["request"] != case["sealed"]
    if field == "units":
        units = snapshot["request"]["units"]
        units[next(iter(units))]["quote"] += " Changed."
    elif field == "task_policy":
        snapshot["request"]["task_policy"]["requested_parts"][0]["request"] += " Changed."
    elif field == "full_preview_digest":
        snapshot["request"][field] = "sha256:other"
    elif field == "missing":
        del snapshot["request"]
    result = score(packet, materials, snapshots | {case["id"]: snapshot})
    workflow = result["workflows"][0]
    if field == "valid":
        assert workflow["assessment_binding"]["status"] == "bound"
        assert result["behavioral_gate"] == "PASS"
    else:
        assert workflow["assessment_binding"]["reason"] == "invalid_raw_snapshot"
        assert result["behavioral_gate"] == "HOLD"
        assert result["denominators"]["unscored_parts"] == 3
