"""Prospective machine-reference answerability; never producer/checker context.

A quotation does not establish relevance or semantic support. These references
separate what the frozen selected text can answer from the model's behaviour.
They do not change historical thresholds, results or human-review labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest

REFERENCE = "planning/15-evaluation-audit-and-recovery/reference/answerability-v1.json"
POLICY = "workspace-campaign-scoring-v13"


def matrix(cases: list[dict[str, Any]]) -> dict[str, Any]:
    spec = json.loads((Path(__file__).resolve().parents[2] / REFERENCE).read_text())
    expected = {r["case_id"]: r for r in spec["cases"]}
    evaluation = [c for c in cases if c["cohort"] == "evaluation_exposed_corpus"]
    if len(evaluation) != 8 or set(expected) != {c["id"] for c in evaluation}:
        raise AdmissionError("answerability_eight_exact_cases_required")
    rows = []
    for case in evaluation:
        parts = case["sealed"]["task_policy"]["requested_parts"]
        references = expected[case["id"]]["parts"]
        if len(parts) != 3 or [p["id"] for p in parts] != [r["part_id"] for r in references]:
            raise AdmissionError("answerability_exact_parts_required")
        evidence = [
            {
                "handle": key,
                **{
                    k: ref[k]
                    for k in (
                        "work_id",
                        "version_id",
                        "material_id",
                        "source_hash",
                        "parser_revision",
                        "scope",
                        "span_id",
                        "start",
                        "end",
                    )
                },
                "quote_digest": _digest(ref["quote"]),
                "reference_digest": _digest(ref),
            }
            for key, ref in sorted(case["sealed"]["units"].items())
        ]
        for part, reference in zip(parts, references, strict=True):
            rows.append(
                {
                    **reference,
                    "case_id": case["id"],
                    "request": part["request"],
                    "requested_part": part,
                    "request_digest": _digest(part),
                    "task_policy_digest": _digest(case["sealed"]["task_policy"]),
                    "selected_evidence": evidence,
                    "selection_digest": _digest(case["evidence_selection"]),
                    "ranking_digest": _digest(case["ranking"]),
                    "author": spec["author"],
                    "provenance": spec["provenance"],
                    "method": spec["method"],
                    "reviewed_at": spec["reviewed_at"],
                    "human_review": None,
                }
            )
    value = {
        "revision": spec["revision"],
        "scoring_policy": POLICY,
        "reference_file_digest": _digest(spec),
        "rows": rows,
        "basis": "Proposed machine references on exposed retained abstracts; not independent human labels or literature recall",
        "missing": "UNSCORED/HOLD",
        "human_qualified": False,
    }
    return {**value, "matrix_digest": _digest(value)}


def score_parts(case: dict[str, Any], reference: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep reference answerability, current machine review and unmet need separate.

    Consistency with a machine reference is not human confirmation. A partial
    source can justify a bounded answer but cannot make a whole request complete.
    Unbound machine judgments cannot provide either support or coverage scores.
    """
    rows = [r for r in reference["rows"] if r["case_id"] == case["id"]]
    declared = case.get("declared_coverage") or []
    if isinstance(declared, list):
        declared = {r["id"]: r for r in declared}
    reviewed = {r["part_id"]: r for r in case.get("machine_coverage") or []}
    bound = case.get("assessment_binding", {}).get("status") == "bound"
    output = []
    for ref in rows:
        part = ref["part_id"]
        declaration = declared.get(part, {})
        decision = reviewed.get(part, {}).get("decision") if bound else None
        status = declaration.get("status")
        insufficient = ref["answerability"] == "insufficient"
        expected = ref["expected_behavior"]
        full = expected == "full_application_abstention"
        observed = case.get("response_disposition")
        proper = (
            (
                decision == status == "lacks_evidence"
                and (
                    observed == "full_abstention"
                    if full
                    else observed == "comparison_abstention"
                    if expected == "comparison_only_abstention"
                    else True
                )
            )
            if decision not in {None, "uncertain"} and insufficient
            else None
        )
        if decision is None or decision == "uncertain":
            fulfillment = "UNSCORED"
        elif decision == "omitted" or (
            decision == "lacks_evidence" and ref["answerability"] == "answerable"
        ):
            fulfillment = "omitted_answer"
        elif decision == "answered" and insufficient:
            fulfillment = "unsupported_answer"
        elif decision == "answered":
            fulfillment = "met" if ref["answerability"] == "answerable" else "partial"
        else:
            fulfillment = "unmet"
        support = case.get("whole_claim_support")
        unsupported = support.get("unsupported") if support else None
        output.append(
            {
                "case_id": case["id"],
                "part_id": part,
                "reference_answerability": ref["answerability"],
                "expected_behavior": expected,
                "limitation_origins": ref["limitation_origins"],
                "declared_status": status,
                "current_machine_status": decision,
                "coverage_disagreement": decision != status if decision is not None else None,
                "request_fulfillment": fulfillment,
                "appropriate_abstention_machine_reference": proper,
                "research_need_unmet": fulfillment != "met" if fulfillment != "UNSCORED" else None,
                "retrieval_gap": insufficient
                and "application_context" not in ref["limitation_origins"],
                "unsupported_claims_in_case": unsupported,
                "human_judgment": None,
                "basis": "Bound unqualified checker versus frozen machine reference; no semantic fact inferred from citation identity",
            }
        )
    return output
