"""Archived failures are development controls, never fresh held-out successes."""

import gzip
import json
import runpy
from pathlib import Path

import pytest

from src.workspace.assistance_contract import resolve_draft
from src.workspace.assistance_coverage import COVERAGE_REVISION, RequestedPart, seal_coverage_policy
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial, SourceSpan

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "planning/14-explore-and-research-modes/d5/tools/request_coverage_report.py"
ARCHIVE = json.loads(
    gzip.decompress(
        (ROOT / "tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz").read_bytes()
    )
)


def test_eight_archived_cases_remain_negative_or_partial_controls():
    report = runpy.run_path(str(TOOL))["controls"]()
    assert len(report["results"]) == 8
    assert sum(r["original_claims"] for r in report["results"]) == 41
    assert sum(len(r["baseline_findings"]["bundled"]) for r in report["results"]) == 18
    assert sum(len(r["baseline_findings"]["lost_qualifications"]) for r in report["results"]) == 2
    assert sum(r["synthetic_quality_gate_blocked"] for r in report["results"]) == 7
    assert all(not r["coverage_complete"] for r in report["results"])
    safety = next(r for r in report["results"] if r["case_id"].endswith("insufficient"))
    assert safety["original_claims"] == 4 and safety["synthetic_claims"] == 0
    assert all(
        len(r["synthetic_output"]["response"].get("claims", [])) <= 6 for r in report["results"]
    )
    assert report["new_provider_contacts"] == 0


@pytest.mark.parametrize(
    "case_id,text",
    [
        (
            "v8-research-memory",
            "In CLR-Bench with the certifying model, six self-evolution methods exclude only 6–12% of unseen members from the count, compared with 20% from keeping raw practice history; this is the benchmark’s exclusion-from-count metric, not a direct measure of incorrect-memory persistence.",
        ),
        (
            "v8-research-verification",
            "In ProClaim’s consensus scientific claim-verification evaluation, persisting the evidence state outside the model context improves performance over in-context accumulation on this task; the selected abstract does not report confidence-calibration or abstention-threshold measurements.",
        ),
    ],
)
def test_synthetic_scope_and_metric_restoration_preserves_provenance_without_quality_credit(
    case_id, text
):
    control = next(
        r for r in runpy.run_path(str(TOOL))["controls"]()["results"] if r["case_id"] == case_id
    )
    output = control["synthetic_output"]
    output["response"]["claims"][2]["text"] = text
    c = ARCHIVE["cases"][case_id]
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in ARCHIVE["materials"]
    )
    _, claims = resolve_draft(
        output,
        {h: EvidenceRef(**r) for h, r in c["units"].items()},
        materials,
        purpose=c["purpose"],
        revision=COVERAGE_REVISION,
        task_policy=control["task_policy"],
    )
    assert claims[2].text == text
    assert len(claims) <= 6
    # Structural/provenance acceptance of a manually authored fixture is not
    # independent support evidence, nor a repaired provider result.
    assert control["synthetic_quality_gate_blocked"]


def test_explicit_requested_parts_take_priority_over_generic_fallback():
    pol = seal_coverage_policy(
        CoverageTaskContext(
            requested_parts=(
                RequestedPart(id="p1", request="Primary metric"),
                RequestedPart(id="p2", request="Conditions"),
            )
        ),
        "learn",
        1,
        "whole request",
    )
    assert [p["request"] for p in pol["requested_parts"]] == ["Primary metric", "Conditions"]
