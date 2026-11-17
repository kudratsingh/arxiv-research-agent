"""Score prospective D5 behavior against a frozen selected-evidence reference.

Current-response judgments come from the raw journal. The reference describes
what a response can do with the supplied evidence, including partial answers
and abstention. The resulting gate measures machine-reviewed behavior.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any, get_args

from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_coverage_shapes import EvidenceGap
from src.workspace.d5_campaign_report import ratio, score_probes, score_workflow
from src.workspace.grounding import EvidenceRef, _materials, _resolve
from src.workspace.material import SourceMaterial

POLICY = "workspace-campaign-behavior-scoring-v20"
MIN_REVIEWED_CLAIMS = 20
MIN_PROBES_PER_LABEL = 10
MIN_COMPLETION_PERCENT = 90

_EXPECTED_STATUS = {
    "answer": "answered",
    "bounded_partial_answer": "partial",
    "comparison_only_abstention": "lacks_evidence",
    "full_application_abstention": "lacks_evidence",
}


def _reference_rows(case: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ref_id = case.get("reference_case_id", case["id"])
    selected = [row for row in rows if row["case_id"] == ref_id]
    parts = case["sealed"]["task_policy"]["requested_parts"]
    if not parts or [row["part_id"] for row in selected] != [part["id"] for part in parts]:
        raise AdmissionError("behavior_reference_part_ids_mismatch")
    if any(
        row["requested_part"] != part
        or row["request_digest"] != _digest(part)
        or row["expected_behavior"] not in _EXPECTED_STATUS
        or (row["answerability"] == "answerable") != (row["expected_behavior"] == "answer")
        for row, part in zip(selected, parts, strict=True)
    ):
        raise AdmissionError("behavior_reference_part_binding_mismatch")
    return selected


def _selected_evidence_intact(
    units: dict[str, Any], rows: list[dict[str, Any]], materials: Sequence[SourceMaterial]
) -> bool:
    if not units:
        return False
    digests = {handle: _digest(unit) for handle, unit in units.items()}
    for row in rows:
        expected = row["selected_evidence"]
        if len(expected) != len(digests) or digests != {
            item["handle"]: item["reference_digest"] for item in expected
        }:
            return False
    try:
        retained = _materials(materials)
        return all(_resolve(EvidenceRef(**unit), retained) is not None for unit in units.values())
    except (ValueError, TypeError):
        return False


def _current_workflow(
    case: dict[str, Any],
    snapshot: dict[str, Any] | None,
    materials: Sequence[SourceMaterial],
    routes: Any,
) -> dict[str, Any]:
    """Use legacy causal binding and normalized current judgments on raw input."""
    try:
        if snapshot is not None and (
            snapshot.get("case_id", case["id"]) != case["id"]
            or snapshot.get("request", case["sealed"]) != case["sealed"]
        ):
            raise ValueError("snapshot_case_or_request_mismatch")
        return score_workflow(case, snapshot, materials, routes=routes)
    except (ValueError, KeyError, IndexError, TypeError):
        result = score_workflow(case, None, materials, routes=routes)
        result["state"] = (snapshot or {}).get("state", "unavailable")
        result["assessment_binding"]["reason"] = "invalid_raw_snapshot"
        return result


def _review(
    workflow: dict[str, Any], snapshot: dict[str, Any] | None, evidence_intact: bool
) -> dict[str, Any]:
    errors: list[str] = []
    missing: list[str] = []
    binding = workflow["assessment_binding"]
    bound = binding["status"] == "bound"
    # A terminal negative recheck can complete the contract without reaching
    # ready. Incomplete repair attempts and rejected drafts have no such credit.
    completed_recheck = (
        workflow["state"] == "failed"
        and bound
        and snapshot is not None
        and len(snapshot["steps"]) == 4
        and binding["checker_ordinal"] == len(snapshot["contacts"]) - 1
    )
    provenance_error = not evidence_intact or (snapshot or {}).get("source_binding_intact") is False
    complete = (workflow["completion"] or completed_recheck) and not provenance_error
    if provenance_error:
        errors.append("invalid_provenance")
    elif workflow["mechanical_provenance"] is False:
        errors.append("invalid_contract_output")
    if not complete:
        missing.append("workflow_incomplete")

    # The binding proves the final step is the completed checker of the current
    # draft or repair and that its stored output matches the normalized verdict.
    priority = (
        snapshot["steps"][-1]["output"].get("priority_review") if bound and snapshot else None
    )
    support = workflow["whole_claim_support"]
    quality = workflow["claim_quality"]
    if not bound or any(
        workflow.get(key) is None
        for key in (
            "whole_claim_support",
            "claim_quality",
            "machine_coverage",
            "prose_review",
            "prose_findings",
            "prose_uncertainties",
            "coverage_critiques",
        )
    ):
        missing.append("current_judgments_unavailable")

    claims = workflow["claims"]
    reviewed = support["checked"] if support else 0
    assessed = support["assessments"] if support else ()
    supported_ids = {item["claim_id"] for item in assessed if item["decision"] == "supported"}
    unsupported_ids = {item["claim_id"] for item in assessed if item["decision"] == "unsupported"}
    bundled = sum(item["atomicity"] == "bundled" for item in quality or ())
    qualifications = [value for item in quality or () for value in item["qualifications"].values()]
    lost = qualifications.count("lost")
    if reviewed != len(claims) or reviewed != len(supported_ids) + len(unsupported_ids):
        missing.append("whole_claim_support_unresolved")
    if unsupported_ids:
        errors.append("unsupported_claim")
    if bundled:
        errors.append("bundled_findings")
    if lost:
        errors.append("lost_qualifications")
    if (
        len(quality or ()) != len(claims)
        or "uncertain" in qualifications
        or any(item["atomicity"] == "uncertain" for item in quality or ())
    ):
        missing.append("claim_quality_unresolved")
    if workflow["prose_findings"]:
        errors.append("unsupported_factual_prose")
    if workflow.get("prose_uncertainties") or workflow["prose_review"] in {None, "abstain"}:
        missing.append("prose_review_unresolved")
    if priority == "violated":
        errors.append("priority_violated")
    elif priority != "respected":
        missing.append("priority_review_unresolved")

    return {
        "errors": errors,
        "missing": missing,
        "reviewed": len(supported_ids) + len(unsupported_ids),
        "support_checked": reviewed,
        "contract_complete": complete,
        "supported_ids": supported_ids,
        "unsupported_ids": unsupported_ids,
        "bundled": bundled,
        "lost": lost,
        "review_complete": not missing,
    }


def _part_score(
    workflow: dict[str, Any], ref: dict[str, Any], review: dict[str, Any]
) -> dict[str, Any]:
    part = ref["part_id"]
    declared: dict[str, Any] = next(
        (r for r in workflow["declared_coverage"] or () if r["id"] == part), {}
    )
    decision = next(
        (r["decision"] for r in workflow["machine_coverage"] or () if r["part_id"] == part), None
    )
    status = declared.get("status")
    answer_ids = set(declared.get("answer_claim_ids", ()))
    context_ids = set(declared.get("context_claim_ids", ()))
    expected = ref["expected_behavior"]
    expected_status = _EXPECTED_STATUS[expected]
    disposition = workflow["response_disposition"]
    gaps = set(declared.get("gap_reasons", ()))
    critiques = [
        item for item in workflow.get("coverage_critiques") or () if item["part_id"] == part
    ]
    errors = list(review["errors"])
    missing = list(review["missing"])
    fulfillment = "UNSCORED"
    if decision in {None, "uncertain"} or status is None:
        missing.append("part_coverage_unresolved")
    else:
        if status != decision:
            errors.append("coverage_disagreement")
        if decision != expected_status:
            errors.append("unexpected_coverage")
        if critiques:
            errors.append("coverage_critique")
        if expected_status in {"answered", "partial"}:
            if not answer_ids:
                errors.append("answer_findings_missing")
            elif not missing and not answer_ids <= review["supported_ids"]:
                errors.append("answer_findings_unsupported")
            if expected_status == "partial" and (
                not gaps or not gaps <= set(get_args(EvidenceGap))
            ):
                errors.append("partial_requires_evidence_gaps")
        elif expected == "comparison_only_abstention":
            if disposition != "comparison_abstention" or answer_ids:
                errors.append("comparison_abstention_required")
        elif (
            disposition != "full_abstention"
            or answer_ids
            or context_ids
            or workflow["claims"]
            or gaps != {"application_context"}
        ):
            errors.append("full_application_abstention_required")

        if not missing:
            if (answer_ids | context_ids) & review["unsupported_ids"] or (
                expected_status == "lacks_evidence" and decision in {"answered", "partial"}
            ):
                fulfillment = "unsupported_answer"
            elif decision == "omitted" or (
                decision == "lacks_evidence" and expected_status != "lacks_evidence"
            ):
                fulfillment = "omitted_answer"
            elif not errors and expected_status == "answered":
                fulfillment = "met"
            elif (
                decision == "partial"
                and answer_ids
                and answer_ids <= review["supported_ids"]
                and not review["errors"]
            ):
                fulfillment = "partial"
            else:
                fulfillment = "unmet"
    # The run can retain a known error while its current part judgment is unscored.
    behavior = "UNSCORED" if missing else "FAIL" if errors else "PASS"
    return {
        "case_id": workflow["id"],
        "reference_case_id": ref["case_id"],
        "part_id": part,
        "reference_answerability": ref["answerability"],
        "expected_behavior": expected,
        "limitation_origins": ref["limitation_origins"],
        "declared_status": status,
        "current_machine_status": decision,
        "behavior": behavior,
        "request_fulfillment": fulfillment,
        "full_answer_credit": None if fulfillment == "UNSCORED" else fulfillment == "met",
        "coverage_critiques": critiques if decision is not None else None,
        "errors": errors,
        "missing": missing,
        "human_judgment": None,
    }


def score_campaign(
    cases: list[dict[str, Any]],
    snapshots: dict[str, Any],
    materials: Sequence[SourceMaterial],
    reference: dict[str, Any],
    probe_references: dict[str, Any],
    probe_verdicts: dict[str, Any],
    *,
    routes: Any = None,
) -> dict[str, Any]:
    """Score only the supplied evaluation cohort against its current journals.

    The caller supplies the frozen scope and its separately collected probe
    verdicts. Development and historical results do not enter its denominators.
    """
    evaluated = [case for case in cases if case["cohort"] == "evaluation_exposed_corpus"]
    protocol_cohorts = {case.get("protocol_cohort") for case in evaluated}
    if len(protocol_cohorts) > 1:
        raise AdmissionError("behavior_evaluation_cohort_mixed")
    if len({c["id"] for c in evaluated}) != len(evaluated) or len(
        {c.get("reference_case_id", c["id"]) for c in evaluated}
    ) != len(evaluated):
        raise AdmissionError("behavior_evaluation_identity_reused")
    matrix = {k: v for k, v in reference.items() if k != "matrix_digest"}
    if reference["matrix_digest"] != _digest(matrix):
        raise AdmissionError("behavior_reference_matrix_digest_mismatch")

    parts = []
    workflows = []
    totals: Counter[str] = Counter(
        dict.fromkeys(
            (
                "completed_workflows",
                "reviewed_workflows",
                "unrun_workflows",
                "failed_workflows",
                "generated_claim_findings",
                "support_checked_claim_findings",
                "reviewed_claim_findings",
                "supported_claim_findings",
                "unsupported_claim_findings",
                "bundled_claim_findings",
                "lost_qualifications",
            ),
            0,
        )
    )
    for case in evaluated:
        rows = _reference_rows(case, reference["rows"])
        snapshot = snapshots.get(case["id"])
        workflow = _current_workflow(case, snapshot, materials, routes)
        evidence_intact = _selected_evidence_intact(case["sealed"]["units"], rows, materials)
        review = _review(workflow, snapshot, evidence_intact)
        scores = [_part_score(workflow, row, review) for row in rows]
        parts.extend(scores)
        review_complete = review["review_complete"] and all(
            score["behavior"] != "UNSCORED" for score in scores
        )
        workflows.append(
            {
                **workflow,
                "reference_case_id": rows[0]["case_id"],
                "reference_evidence_intact": evidence_intact,
                "contract_complete": review["contract_complete"],
                "review_complete": review_complete,
                "behavior_errors": review["errors"],
                "review_gaps": review["missing"],
            }
        )
        totals.update(
            {
                "completed_workflows": review["contract_complete"],
                "reviewed_workflows": review_complete,
                "unrun_workflows": workflow["state"] == "unrun",
                "failed_workflows": workflow["state"] == "failed",
                "generated_claim_findings": len(workflow["claims"]),
                "support_checked_claim_findings": review["support_checked"],
                "reviewed_claim_findings": review["reviewed"],
                "supported_claim_findings": len(review["supported_ids"]),
                "unsupported_claim_findings": len(review["unsupported_ids"]),
                "bundled_claim_findings": review["bundled"],
                "lost_qualifications": review["lost"],
            }
        )

    probes = score_probes(probe_references, probe_verdicts)
    positive, negative = probes["false_reject"], probes["false_pass"]
    planned_probes = positive["planned"] + negative["planned"]
    probe_sufficient = (
        positive["planned"] == negative["planned"] >= MIN_PROBES_PER_LABEL
        and probes["unique_claim_evidence_pairs"] == planned_probes
    )
    probe_complete = probe_sufficient and all(
        group["decisive"] == group["planned"] for group in (positive, negative)
    )
    part_counts = Counter(part["behavior"] for part in parts)
    need_counts = Counter(part["request_fulfillment"] for part in parts)
    completion_sufficient = bool(evaluated) and (
        100 * totals["completed_workflows"] >= MIN_COMPLETION_PERCENT * len(evaluated)
    )
    reasons = []
    errors = any(part["errors"] for part in parts) or positive["errors"] or negative["errors"]
    if errors:
        reasons.append("observed_behavior_or_checker_error")
    if totals["failed_workflows"]:
        reasons.append("failed_workflow_states")
    if not parts or part_counts["UNSCORED"]:
        reasons.append("part_review_incomplete")
    if not completion_sufficient:
        reasons.append("workflow_completion_below_minimum")
    if totals["reviewed_claim_findings"] < MIN_REVIEWED_CLAIMS:
        reasons.append("reviewed_claim_findings_below_minimum")
    if not probe_complete:
        reasons.append("balanced_decisive_probe_coverage_incomplete")
    gate = "FAIL" if errors else "HOLD" if reasons else "PASS"
    simulated = any((snapshots.get(case["id"]) or {}).get("simulated") for case in evaluated)
    return {
        "scoring_policy": POLICY,
        "reference_matrix_digest": reference["matrix_digest"],
        "basis": "Synthetic software evidence only" if simulated else "Current machine judgments",
        "behavioral_gate": gate,
        "gate_reasons": reasons,
        "machine_quality": "HOLD" if simulated else "PASS_MACHINE_ONLY" if gate == "PASS" else gate,
        "denominators": {
            "evaluation_workflows": len(evaluated),
            **totals,
            "workflow_completion": ratio(totals["completed_workflows"], len(evaluated)),
            "unscored_claim_findings": (
                totals["generated_claim_findings"] - totals["reviewed_claim_findings"]
            ),
            "requested_parts": len(parts),
            "scored_parts": part_counts["PASS"] + part_counts["FAIL"],
            "unscored_parts": part_counts["UNSCORED"],
            "behaviorally_correct_parts": part_counts["PASS"],
            "behaviorally_incorrect_parts": part_counts["FAIL"],
            "behavioral_correctness_among_scored": ratio(
                part_counts["PASS"], part_counts["PASS"] + part_counts["FAIL"]
            ),
            "part_review_coverage": ratio(part_counts["PASS"] + part_counts["FAIL"], len(parts)),
            "probe_records": planned_probes,
            "human_reviewed_claims": 0,
        },
        "request_fulfillment_counts": {
            status: need_counts[status]
            for status in (
                "met",
                "partial",
                "unmet",
                "omitted_answer",
                "unsupported_answer",
                "UNSCORED",
            )
        },
        "parts": parts,
        "workflows": workflows,
        "probe_scores": probes,
        "human_qualification": False,
    }
