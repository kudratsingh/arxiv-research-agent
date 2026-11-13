"""Machine references and conditional error denominators; no human evidence."""

from copy import deepcopy

import pytest

from src.workspace.d5_campaign_report import score_probes

pytestmark = pytest.mark.unit


def references():
    return {
        key: {
            "reference": label,
            "evidence": {"span_id": span},
            "matched_pair": span,
            "claim_digest": key,
        }
        for key, label, span in [
            ("s1", "supported", "a"),
            ("u1", "unsupported", "a"),
            ("s2", "supported", "b"),
            ("u2", "unsupported", "b"),
        ]
    }


def test_both_error_directions_and_acceptable_abstention_block_exact_denominators():
    refs = references()
    before = deepcopy(refs)
    report = score_probes(
        refs, {"u1": "supported", "u2": "abstain", "s1": "unsupported", "s2": "abstain"}
    )
    assert report["false_pass"] == {
        "planned": 2,
        "observed": 2,
        "decisive": 1,
        "errors": 1,
        "error_rate_conditional": 1.0,
        "abstentions": 1,
        "missing_or_invalid": 0,
    }
    assert report["false_reject"] == report["false_pass"]
    assert report["acceptable_abstention_blocks"] == 1
    assert report["unique_evidence"] == 2 and report["matched_sets"] == 2
    assert report["independent_samples"] is False and refs == before


def test_missing_malformed_and_abstaining_verdicts_cannot_become_perfect_scores():
    report = score_probes(references(), {"u1": "abstain", "s1": "wrong field/index"})
    assert report["false_pass"]["error_rate_conditional"] is None
    assert report["false_pass"]["abstentions"] == 1
    assert report["false_pass"]["missing_or_invalid"] == 1
    assert report["false_reject"]["observed"] == 0
    assert report["false_reject"]["missing_or_invalid"] == 2
    assert report["false_reject"]["error_rate_conditional"] is None


@pytest.mark.parametrize(
    "label,missing", [("supported", "false_pass"), ("unsupported", "false_reject")]
)
def test_single_polarity_reference_set_has_no_opposite_error_rate(label, missing):
    refs = {k: v for k, v in references().items() if v["reference"] == label}
    result = score_probes(refs, {k: label for k in refs})
    assert result[missing]["planned"] == 0
    assert result[missing]["error_rate_conditional"] is None


def test_empty_reference_and_verdict_sets_remain_unscored():
    report = score_probes({}, {})
    assert report["false_pass"]["error_rate_conditional"] is None
    assert report["false_reject"]["error_rate_conditional"] is None


def test_compiled_models_key_every_scope_and_export_fresh_schema_objects():
    from src.workspace.assistance_contract import response_model, schemas
    from src.workspace.assistance_coverage import (
        AUTHORITATIVE_COVERAGE_REVISION,
        seal_coverage_policy,
    )
    from src.workspace.assistance_policy import CoverageTaskContext

    policy = seal_coverage_policy(
        CoverageTaskContext(),
        "learn",
        1,
        "Explain this source",
        revision=AUTHORITATIVE_COVERAGE_REVISION,
    )
    model = response_model(
        ["u1"], purpose="single_paper", revision=AUTHORITATIVE_COVERAGE_REVISION, task_policy=policy
    )
    assert model is response_model(
        ["u1"],
        purpose="single_paper",
        revision=AUTHORITATIVE_COVERAGE_REVISION,
        task_policy=deepcopy(policy),
    )
    assert model is not response_model(
        ["u2"], purpose="single_paper", revision=AUTHORITATIVE_COVERAGE_REVISION, task_policy=policy
    )
    exported = schemas(
        ["u1"], purpose="single_paper", revision=AUTHORITATIVE_COVERAGE_REVISION, task_policy=policy
    )
    before = deepcopy(exported)
    exported["wire"].clear()
    assert (
        schemas(
            ["u1"],
            purpose="single_paper",
            revision=AUTHORITATIVE_COVERAGE_REVISION,
            task_policy=policy,
        )
        == before
    )
    changed = deepcopy(policy)
    changed["requested_parts"][0]["request"] = "Different question"
    assert model is not response_model(
        ["u1"],
        purpose="single_paper",
        revision=AUTHORITATIVE_COVERAGE_REVISION,
        task_policy=changed,
    )
