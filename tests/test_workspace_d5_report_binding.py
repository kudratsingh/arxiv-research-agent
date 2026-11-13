"""AUD-01: synthetic archived production replay, never live quality evidence."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.workspace.admission import _digest
from src.workspace.d5_campaign_report import score_workflow
from src.workspace.material import SourceMaterial, SourceSpan

pytestmark = pytest.mark.unit


def fixture(*, current=True):
    data = json.loads(
        gzip.decompress(
            (Path(__file__).parent / "fixtures/d5/aud01-synthetic-replay.json.gz").read_bytes()
        )
    )
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in data["materials"]
    )
    case, snapshot = data["case"], data["snapshot"]
    if current:
        # A separately labelled synthetic successor: no archived bytes change.
        # Rebuild current requests around the original mock verdicts; this is
        # software binding evidence, never a new successful provider result.
        from src.workspace.d5_adapter import checker_context
        from src.workspace.d5_operations import ROUTES, wire

        for index in (1, 3):
            body = wire(
                checker_context(case["sealed"], snapshot["steps"][index - 1]["output"], materials),
                ROUTES,
            )
            fingerprint = _digest(body)
            snapshot["steps"][index]["request_digest"] = fingerprint
            snapshot["contacts"][2 * index + 1].update(
                body=body, request_digest=fingerprint, generation_request_digest=fingerprint
            )
            count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
            snapshot["contacts"][2 * index].update(
                body=count, request_digest=_digest(count), generation_request_digest=fingerprint
            )
    return case, snapshot, materials


def uncertain_recheck(snapshot):
    snapshot["state"] = "uncertain"
    snapshot["steps"] = snapshot["steps"][:3]
    snapshot["contacts"][-1].update(state="dispatching", response=None)


def coverage_only_repair(snapshot):
    output = snapshot["steps"][2]["output"]
    assert output["response"]["coverage"]["p1"]["status"] == "lacks_evidence"
    output["response"]["coverage"]["p1"] = {
        "status": "answered",
        "answer_claim_ids": ["c1"],
        "context_claim_ids": [],
        "gap": "none",
    }
    # This is an owned synthetic mutation, not a corrected provider result.
    response = snapshot["contacts"][5]["response"]
    response["content"][0]["text"] = json.dumps(output, ensure_ascii=False)


def test_coverage_only_repair_with_uncertain_recheck_has_no_current_judgments():
    case, snapshot, materials = fixture()
    coverage_only_repair(snapshot)
    uncertain_recheck(snapshot)
    before = _digest(snapshot)
    result = score_workflow(case, snapshot, materials)
    assert result["completion"] is False
    assert result["mechanical_provenance"] is True
    assert all(
        result[k] is None
        for k in ["machine_coverage", "claim_quality", "prose_review", "whole_claim_support"]
    )
    assert result["assessment_binding"]["status"] == "unavailable"
    assert _digest(snapshot) == before


def test_audit_checker_projection_does_not_attach_earlier_assessments():
    case, snapshot, materials = fixture()
    coverage_only_repair(snapshot)
    uncertain_recheck(snapshot)
    # The audit's owned in-memory checker projection excludes count receipts.
    snapshot["contacts"] = [c for c in snapshot["contacts"] if c["endpoint"] == "messages"]
    result = score_workflow(case, snapshot, materials)
    assert result["completion"] is False
    assert all(
        result[k] is None
        for k in ["machine_coverage", "claim_quality", "prose_review", "whole_claim_support"]
    )


def replace_output(snapshot, step_index, payload):
    ordinal = 2 * step_index + 1
    snapshot["steps"][step_index]["output"] = deepcopy(payload)
    snapshot["contacts"][ordinal]["response"]["content"][-1]["text"] = json.dumps(
        {k: v for k, v in payload.items() if k != "grounding"}, ensure_ascii=False
    )


def fresh_recheck(case, snapshot, materials):
    from src.workspace.assistance_coverage import fixture_checks
    from src.workspace.d5_adapter import checker_context
    from src.workspace.d5_operations import ROUTES, verdict_text, wire

    context = checker_context(case["sealed"], snapshot["steps"][2]["output"], materials)
    body = wire(context, ROUTES)
    prior = json.loads(verdict_text(snapshot["contacts"][7]["response"]))
    payload = fixture_checks(prior, context)
    replace_output(snapshot, 3, payload)
    fingerprint = _digest(body)
    snapshot["steps"][3]["request_digest"] = fingerprint
    snapshot["contacts"][7].update(
        body=body, request_digest=fingerprint, generation_request_digest=fingerprint
    )
    count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
    snapshot["contacts"][6].update(
        body=count, request_digest=_digest(count), generation_request_digest=fingerprint
    )


def assert_unavailable(case, snapshot, materials):
    before = _digest(snapshot)
    result = score_workflow(case, snapshot, materials)
    assert not result["completion"]
    assert all(
        result[k] is None
        for k in [
            "machine_coverage",
            "claim_quality",
            "prose_review",
            "prose_findings",
            "whole_claim_support",
        ]
    )
    assert result["assessment_binding"]["status"] == "unavailable"
    assert _digest(snapshot) == before
    return result


def test_valid_repair_recheck_binds_latest_even_when_check_bodies_are_identical():
    case, snapshot, materials = fixture()
    assert snapshot["steps"][1]["request_digest"] == snapshot["steps"][3]["request_digest"]
    result = score_workflow(case, snapshot, materials)
    assert result["completion"] and result["mechanical_provenance"]
    assert result["assessment_binding"]["status"] == "bound"
    assert result["assessment_binding"]["current_response_ordinal"] == 5
    assert result["assessment_binding"]["checker_ordinal"] == 7
    assert result["whole_claim_support"]["supported"] == 1


def test_valid_draft_check_has_current_judgments():
    case, snapshot, materials = fixture()
    snapshot["steps"][1] = deepcopy(snapshot["steps"][3])
    snapshot["contacts"][3] = deepcopy(snapshot["contacts"][7])
    snapshot["contacts"][3]["ordinal"] = 3
    snapshot["steps"] = snapshot["steps"][:2]
    snapshot["contacts"] = snapshot["contacts"][:4]
    result = score_workflow(case, snapshot, materials)
    assert result["completion"] and result["assessment_binding"]["checker_ordinal"] == 3
    assert result["machine_coverage"] is not None


def test_changed_coverage_and_bound_completed_recheck_gets_only_new_assessments():
    case, snapshot, materials = fixture()
    coverage_only_repair(snapshot)
    fresh_recheck(case, snapshot, materials)
    result = score_workflow(case, snapshot, materials)
    assert result["completion"] and result["assessment_binding"]["status"] == "bound"
    assert result["machine_coverage"][0]["decision"] == "answered"
    assert all(c["human_support"] is None for c in result["claims"])


@pytest.mark.parametrize("change", ["coverage", "prose", "section", "claim"])
def test_old_context_cannot_assess_changed_content_even_after_a_completed_check(change):
    case, snapshot, materials = fixture()
    value = snapshot["steps"][2]["output"]
    if change == "coverage":
        coverage_only_repair(snapshot)
    else:
        if change == "prose":
            from src.workspace.assistance_contract import QUESTION_INTENTS

            old = value["response"]["questions"][0]["intent"]
            value["response"]["questions"][0]["intent"] = next(
                k for k in QUESTION_INTENTS if k != old
            )
        elif change == "section":
            value["response"]["background_claims"] = []
            value["response"]["assumption_claims"] = ["c1"]
        else:
            value["response"]["claims"][0]["text"] += " Additional finding."
        replace_output(snapshot, 2, value)
    result = assert_unavailable(case, snapshot, materials)
    assert result["mechanical_provenance"] is True
    assert (
        result["assessment_binding"]["reason"] == "checker_context_does_not_bind_current_response"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "ordinal_bool",
        "duplicate_ordinal",
        "out_of_order",
        "missing_count",
        "missing_response",
        "wrong_request_hash",
        "wrong_step_hash",
        "changed_step_only",
        "duplicate_check",
        "wrong_stage",
        "wrong_model",
        "truncated",
        "missing_check_step",
        "no_workflow_steps",
        "malformed_json",
        "duplicate_json",
        "nonfinite_json",
        "nonobject_json",
        "stale_coverage_digest",
        "duplicate_claim_review",
    ],
)
def test_malformed_or_missing_bindings_cannot_supply_current_judgments(mutation):
    from src.workspace.d5_operations import verdict_text

    case, snapshot, materials = fixture()
    if mutation == "ordinal_bool":
        snapshot["contacts"][0]["ordinal"] = False
    elif mutation == "duplicate_ordinal":
        snapshot["contacts"][7]["ordinal"] = 3
    elif mutation == "out_of_order":
        snapshot["contacts"][3], snapshot["contacts"][7] = (
            snapshot["contacts"][7],
            snapshot["contacts"][3],
        )
    elif mutation == "missing_count":
        snapshot["contacts"][6]["response"] = None
    elif mutation == "missing_response":
        snapshot["contacts"][7]["response"] = None
    elif mutation == "wrong_request_hash":
        snapshot["contacts"][7]["request_digest"] = "bad"
    elif mutation == "wrong_step_hash":
        snapshot["steps"][3]["request_digest"] = "bad"
    elif mutation == "changed_step_only":
        snapshot["steps"][2]["output"]["response"]["gaps"] = ["protocol"]
    elif mutation == "duplicate_check":
        extra = deepcopy(snapshot["contacts"][7])
        extra["ordinal"] = 8
        snapshot["contacts"].append(extra)
    elif mutation == "wrong_stage":
        snapshot["steps"][3]["stage"] = "repair"
    elif mutation == "wrong_model":
        snapshot["contacts"][7]["response"]["model"] = "other-model"
    elif mutation == "truncated":
        snapshot["contacts"][7]["response"]["stop_reason"] = "max_tokens"
    elif mutation == "missing_check_step":
        snapshot["steps"] = snapshot["steps"][:3]
    elif mutation == "no_workflow_steps":
        snapshot["steps"] = []
    elif mutation in {"malformed_json", "duplicate_json", "nonfinite_json", "nonobject_json"}:
        raw = verdict_text(snapshot["contacts"][7]["response"])
        value = (
            "{"
            if mutation == "malformed_json"
            else raw[:-1] + ',"priority_review":"respected"}'
            if mutation == "duplicate_json"
            else '{"checks":NaN}'
            if mutation == "nonfinite_json"
            else "[]"
        )
        snapshot["contacts"][7]["response"]["content"][-1]["text"] = value
    else:
        value = json.loads(verdict_text(snapshot["contacts"][7]["response"]))
        if mutation == "stale_coverage_digest":
            value["coverage_checks"][0]["input_digest"] = "sha256:" + "0" * 64
        else:
            value["checks"].append(deepcopy(value["checks"][0]))
        replace_output(snapshot, 3, value)
    assert_unavailable(case, snapshot, materials)


def test_pending_repair_does_not_leave_prior_draft_judgments_current():
    case, snapshot, materials = fixture()
    snapshot["state"] = "uncertain"
    snapshot["steps"] = snapshot["steps"][:2]
    snapshot["contacts"] = snapshot["contacts"][:6]
    snapshot["contacts"][5].update(state="dispatching", response=None)
    assert_unavailable(case, snapshot, materials)


def test_unrun_and_no_response_cases_remain_unscored():
    case, snapshot, materials = fixture()
    result = score_workflow(case, None, materials)
    assert not result["completion"] and result["human_review"] is None
    snapshot["steps"] = []
    assert_unavailable(case, snapshot, materials)


def test_archived_checks_remain_historical_under_the_new_whole_response_binding():
    case, snapshot, materials = fixture(current=False)
    result = assert_unavailable(case, snapshot, materials)
    assert result["mechanical_provenance"] is True
    assert (
        result["assessment_binding"]["reason"] == "checker_context_does_not_bind_current_response"
    )


@pytest.mark.parametrize("change", ["model", "settings", "count_body", "evidence"])
def test_self_consistent_hashes_do_not_make_drifted_check_or_evidence_current(change):
    case, snapshot, materials = fixture()
    body = snapshot["contacts"][7]["body"]
    if change == "evidence":
        next(iter(case["sealed"]["units"].values()))["quote"] += " altered"
    else:
        if change == "model":
            body["model"] = "other-model"
            snapshot["contacts"][7]["response"]["model"] = "other-model"
        elif change == "settings":
            body["output_config"]["effort"] = "low"
        count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
        if change == "count_body":
            count["model"] = "other-model"
        fingerprint = _digest(body)
        snapshot["steps"][3]["request_digest"] = fingerprint
        snapshot["contacts"][7].update(
            request_digest=fingerprint, generation_request_digest=fingerprint
        )
        snapshot["contacts"][6].update(
            body=count, request_digest=_digest(count), generation_request_digest=fingerprint
        )
    assert_unavailable(case, snapshot, materials)
