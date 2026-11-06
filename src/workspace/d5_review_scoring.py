"""Deterministic review grading; provenance failures are never human-overridable.

Conditional checker error rates exclude checker abstentions and indeterminate
human judgments. Their counts/coverage are reported, never silently negatives.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any

from src.workspace.admission import _digest
from src.workspace.d5_reviews import ReviewItem, catalog


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def machine_checks(job: dict[str, Any]) -> dict[str, str | None]:
    steps = [s for s in job.get("steps", []) if s["stage"] in {"check", "recheck", "probe"}]
    # A probe's actual journal stage is check, not its proposed negative label.
    return (
        {c["claim_id"]: c.get("decision") for c in steps[-1]["output"].get("checks", [])}
        if steps
        else {}
    )


def checker_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    decisive = [r for r in rows if r["human"] in {"supported", "unsupported"}]
    pairs = [r for r in decisive if r["machine"] in {"supported", "unsupported"}]
    negatives = [r for r in pairs if r["human"] == "unsupported"]
    positives = [r for r in pairs if r["human"] == "supported"]
    false_passes = [r for r in negatives if r["machine"] == "supported"]
    false_failures = [r for r in positives if r["machine"] == "unsupported"]
    abstentions = [r for r in decisive if r["machine"] == "abstain"]
    return {
        "eligible": len(rows),
        "human_decisive": len(decisive),
        "paired_decisions": len(pairs),
        "human_indeterminate": sum(r["human"] in {"insufficient", "unreviewable"} for r in rows),
        "human_missing": sum(r["human"] is None for r in rows),
        "machine_missing": sum(
            r["machine"] not in {"supported", "unsupported", "abstain"} for r in decisive
        ),
        "agreement": ratio(sum(r["human"] == r["machine"] for r in pairs), len(pairs)),
        "false_passes": len(false_passes),
        "false_pass_denominator": len(negatives),
        "false_pass_rate": ratio(len(false_passes), len(negatives)),
        "false_failures": len(false_failures),
        "false_fail_denominator": len(positives),
        "false_fail_rate": ratio(len(false_failures), len(positives)),
        "abstentions": len(abstentions),
        "abstention_denominator": len(pairs) + len(abstentions),
        "abstention_rate": ratio(len(abstentions), len(pairs) + len(abstentions)),
        "disagreements": [r for r in pairs if r["human"] != r["machine"]],
        "abstained_items": abstentions,
        "denominator_policy": "Error rates and agreement conditional on a supported/unsupported human label AND checker decision. Checker abstentions excluded from those denominators, reported separately. Human insufficient/unreviewable/missing never treated as negative.",
    }


def claim_counts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        k: sum(r["human"] == k for r in rows)
        for k in ("supported", "unsupported", "insufficient", "unreviewable")
    }
    reviewed = sum(counts.values())
    decisive = counts["supported"] + counts["unsupported"]
    return {
        "eligible": len(rows),
        "reviewed": reviewed,
        **counts,
        "missing": len(rows) - reviewed,
        "decisive": decisive,
        "review_coverage": ratio(reviewed, len(rows)),
        "factual_support": ratio(counts["supported"], decisive),
        "atomicity": ratio(
            sum(r["atomic"] is True for r in rows), sum(isinstance(r["atomic"], bool) for r in rows)
        ),
        "non_atomic": sum(r["atomic"] is False for r in rows),
        "omitted_qualifications": sum(r["qualifications_retained"] is False for r in rows),
        "qualification_review_coverage": ratio(
            sum(isinstance(r["qualifications_retained"], bool) for r in rows), len(rows)
        ),
    }


def case_outcome(
    case: dict[str, Any], labels: dict[str, Any], rows: list[dict[str, Any]], output: dict[str, Any]
) -> tuple[str, list[str]]:
    failures: list[str] = []
    missing: list[str] = []
    if not case["completion"]:
        (
            failures
            if case.get("workflow_state") in {"failed", "cancelled", "interrupted"}
            else missing
        ).append("workflow_not_completed")
    if case["provenance"] is False:
        failures.append("mechanical_provenance_failed")
    if rows and case["provenance"] is not True:
        failures.append("required_provenance_unscored_or_failed")
    for row in rows:
        if row["human"] == "unsupported":
            failures.append("unsupported_claim:" + row["claim_id"])
        if row["human"] not in {"supported", "unsupported"}:
            missing.append("claim_support:" + row["claim_id"])
        for field in ("atomic", "qualifications_retained"):
            if row[field] is False:
                failures.append(field + ":" + row["claim_id"])
            elif row[field] is not True:
                missing.append(field + ":" + row["claim_id"])
    for field, good in (("complete", True), ("material_omissions", False)):
        if labels.get(field) is None:
            missing.append(field)
        elif labels[field] is not good:
            failures.append(field)
    for field in ("comparison_compatible", "counterevidence_handled", "appropriate_abstention"):
        value = labels.get(field)
        required = (
            field == "comparison_compatible"
            and bool(output.get("comparison"))
            or field == "appropriate_abstention"
            and bool(output.get("abstention"))
        )
        if value is False:
            failures.append(field)
        elif value is None or (required and value is not True):
            missing.append(field)
    if labels.get("prose_support") == "unsupported":
        failures.append("unsupported_substantive_prose")
    elif labels.get("prose_support") not in {"supported", "procedural_only"}:
        missing.append("substantive_prose_review")
    if not rows and not output.get("abstention"):
        missing.append("no_claims_or_explicit_abstention")
    return (
        ("FAIL", sorted(set(failures + missing)))
        if failures
        else ("HOLD", sorted(set(missing)))
        if missing
        else ("PASS", [])
    )


def grade_report(
    packet: dict[str, Any], original: dict[str, Any], records: dict[str, ReviewItem] | None = None
) -> dict[str, Any]:
    report = deepcopy(original)
    records = records or {}
    targets = catalog(packet, original)
    claim_rows: list[dict[str, Any]] = []
    probe_rows: list[dict[str, Any]] = []
    case_results = {c["id"]: c for c in report["cases"]}
    for target, item in targets.items():
        if item["kind"] not in {"claim", "probe"}:
            continue
        review = records.get(target)
        labels = review.judgments.model_dump() if review else {}
        observed = item["observed"]
        row = {
            "target": target,
            "case_id": item["case_id"],
            "job_id": item["job_id"],
            "claim_id": observed["claim_id"],
            "claim_digest": _digest(observed["claim"]),
            "evidence_digest": _digest(observed["evidence"]),
            "human": labels.get("support"),
            "atomic": labels.get("atomic"),
            "qualifications_retained": labels.get("qualifications_retained"),
            "machine": machine_checks(report["raw_results"][item["case_id"]]).get(
                observed["claim_id"]
            ),
            "review_provenance": review.provenance if review else None,
            "unique_fact": _digest(
                {"text": observed["claim"].get("text"), "evidence": observed["evidence"]}
            ),
        }
        (probe_rows if item["kind"] == "probe" else claim_rows).append(row)
    case_findings = []
    for case_id, case in case_results.items():
        target_item = next(
            (i for i in targets.values() if i["kind"] == "case" and i["case_id"] == case_id), None
        )
        review = records.get(target_item["target"]) if target_item else None
        labels = review.judgments.model_dump() if review else {}
        rows = [r for r in claim_rows if r["case_id"] == case_id]
        output = target_item["observed"]["output"] if target_item else {}
        case["workflow_state"] = report["raw_results"].get(case_id, {}).get("state")
        outcome, reasons = case_outcome(case, labels, rows, output)
        case.update(
            human_review=review.model_dump() if review else None,
            whole_claim_support=claim_counts(rows)["factual_support"],
            atomicity=claim_counts(rows)["atomicity"],
            comparisons=labels.get("comparison_compatible"),
            counterevidence=labels.get("counterevidence_handled"),
            omissions=labels.get("material_omissions"),
            accepted_result=outcome == "PASS",
            review_outcome=outcome,
            review_reasons=reasons,
        )
        case["factual_gate"] = (
            "FAIL" if outcome == "FAIL" else "PASS" if outcome == "PASS" and rows else "UNSCORED"
        )
        by_id = {r["claim_id"]: r for r in rows}
        for claim in case["claims"]:
            row = by_id.get(claim["claim_id"], {})
            claim.update(
                human_support=row.get("human"),
                atomicity=row.get("atomic"),
                qualifications_retained=row.get("qualifications_retained"),
            )
        case_findings.append(
            {
                "id": case_id,
                "cohort": case["cohort"],
                "outcome": outcome,
                "reasons": reasons,
                "judgments": labels,
            }
        )
        retrieval_items = [
            i for i in targets.values() if i["kind"] == "retrieval" and i["case_id"] == case_id
        ]
        judged = [
            (i, records[i["target"]].judgments) for i in retrieval_items if i["target"] in records
        ]
        edition = next(c["edition"] for c in packet["cases"] if c["id"] == case_id)
        selected = {w if isinstance(w, str) else w["work_id"] for w in edition}
        relevance = [
            (i, j)
            for i, j in judged
            if j.relevance in {"relevant", "irrelevant"}
            and i["observed"]["work"]["work_id"] in selected
        ]
        references = [(i, j) for i, j in judged if isinstance(j.known_reference, bool)]
        known = [i for i, j in references if j.known_reference]
        case["retrieval"].update(
            judged_selected=len(relevance),
            judgment_coverage=ratio(len(relevance), len(selected)),
            precision_judged=ratio(
                sum(j.relevance == "relevant" for _, j in relevance), len(relevance)
            ),
            precision_selected=ratio(
                sum(j.relevance == "relevant" for _, j in relevance), len(selected)
            )
            if len(relevance) == len(selected)
            else None,
            known_reference_judgments=len(references),
            known_references_observed=len(known),
            known_reference_recall=ratio(
                sum(i["observed"]["work"]["work_id"] in selected for i in known), len(known)
            )
            if len(references) == len(retrieval_items)
            else None,
            owner_usefulness=labels.get("usefulness")
            if review and review.reviewer_role == "owner" and review.provenance != "synthetic"
            else None,
            proposed_usefulness=labels.get("usefulness"),
        )
    fresh_ids = {c["id"] for c in report["cases"] if c["cohort"] == "fresh_system"}
    fresh_rows = [r for r in claim_rows if r["case_id"] in fresh_ids]
    fresh_cases = [c for c in report["cases"] if c["id"] in fresh_ids]
    reviewed_facts = {
        r["unique_fact"]
        for r in fresh_rows
        if r["human"] in {"supported", "unsupported"}
        and isinstance(r["atomic"], bool)
        and isinstance(r["qualifications_retained"], bool)
    }
    decisive_probes = [r for r in probe_rows if r["human"] in {"supported", "unsupported"}]
    checker = checker_metrics(fresh_rows + probe_rows)
    reasons = []
    policy = packet["scoring"]
    if sum(c["completion"] for c in fresh_cases) < policy["completion_required"]:
        reasons.append("completion_minimum_not_met")
    if len(reviewed_facts) < policy["generated_fact_reviews_min"]:
        reasons.append("generated_fact_review_minimum_not_met")
    if len(decisive_probes) < policy["adversarial_reviews_min"]:
        reasons.append("adversarial_review_minimum_not_met")
    if checker["false_passes"] > policy["false_pass_max"]:
        reasons.append("checker_false_pass_limit_exceeded")
    if checker["false_pass_rate"] is None:
        reasons.append("checker_false_pass_denominator_missing")
    if any(c["review_outcome"] == "HOLD" for c in fresh_cases):
        reasons.append("required_case_or_claim_reviews_missing")
    failures = (
        any(c["review_outcome"] == "FAIL" for c in fresh_cases)
        or checker["false_passes"] > policy["false_pass_max"]
    )
    outcome = "FAIL" if failures else "HOLD" if reasons else "PASS"
    accepted = [c for c in fresh_cases if c["accepted_result"]]

    def money(value: Any) -> Decimal | None:
        try:
            amount = Decimal(str(value))
            return amount if amount.is_finite() and amount >= 0 else None
        except InvalidOperation:
            return None

    costs = [money(c[k]) for c in fresh_cases for k in ("workflow_usd", "checker_usd")]
    total_cost = sum((v for v in costs if v is not None), Decimal(0))
    known_cost = all(v is not None for v in costs) and all(
        money(c["unknown_usd"]) == 0 for c in fresh_cases
    )
    bases = {r.provenance for r in records.values() if r.judgments.model_dump(exclude_none=True)}
    basis = (
        "unreviewed"
        if not bases
        else "synthetic"
        if "synthetic" in bases
        else "machine_assisted_human"
        if "machine_assisted_human" in bases
        else "independent_human"
    )
    report["quality"] = {
        "outcome": outcome,
        "reasons": reasons,
        "basis": basis,
        "qualification_outcome": "HOLD"
        if basis != "independent_human"
        or any(v.get("simulated") for v in report["raw_results"].values())
        else outcome,
        "claims_by_cohort": {
            cohort: claim_counts(
                [r for r in claim_rows if case_results[r["case_id"]]["cohort"] == cohort]
            )
            for cohort in sorted({c["cohort"] for c in report["cases"]})
        },
        "probe_claims": claim_counts(probe_rows),
        "case_rubric": {
            field: {
                "eligible": len(fresh_cases),
                "reviewed": sum(
                    c["judgments"].get(field) is not None
                    for c in case_findings
                    if c["id"] in fresh_ids
                ),
                "missing": sum(
                    c["judgments"].get(field) is None for c in case_findings if c["id"] in fresh_ids
                ),
                "not_applicable": sum(
                    c["judgments"].get(field) == "not_applicable"
                    for c in case_findings
                    if c["id"] in fresh_ids
                ),
                "findings": {
                    c["id"]: c["judgments"].get(field)
                    for c in case_findings
                    if c["id"] in fresh_ids
                },
            }
            for field in (
                "complete",
                "material_omissions",
                "comparison_compatible",
                "counterevidence_handled",
                "appropriate_abstention",
                "prose_support",
            )
        },
        "cost_policy": "Fresh workflow plus mandatory checker spend, including failed fresh cases, divided by accepted fresh results. Development/probe overhead remains in unchanged accounting; unknown/missing/invalid costs make this metric unscored.",
        "checker": checker,
        "checker_by_cohort": {
            cohort: checker_metrics(
                [r for r in claim_rows if case_results[r["case_id"]]["cohort"] == cohort]
            )
            for cohort in sorted({c["cohort"] for c in report["cases"]})
        },
        "checker_probes": checker_metrics(probe_rows),
        "case_findings": case_findings,
        "claim_findings": claim_rows,
        "probe_findings": probe_rows,
        "policy": policy,
        "minimum_count_policy": "Generated minimum counts unique (text,evidence) facts with decisive support and atomicity/qualification labels, fresh system only. Probe minimum counts decisive support labels, never proposed negativity. Synthetic grading PASS is not human qualification.",
    }
    report["denominators"] = {
        "fresh_system_cases": len(fresh_cases),
        "fresh_completed": sum(c["completion"] for c in fresh_cases),
        "eligible_generated_claims": len(fresh_rows),
        "reviewed_generated_claims": claim_counts(fresh_rows)["reviewed"],
        "generated_fact_reviews_for_minimum": len(reviewed_facts),
        "human_supported_generated_claims": sum(
            r["human"] == "supported" and r["review_provenance"] == "independent_human"
            for r in fresh_rows
        ),
        "human_judged_adversarial_items": sum(
            r["review_provenance"] == "independent_human" for r in decisive_probes
        ),
        "adversarial_reviews_for_minimum": len(decisive_probes),
        "accepted_results": len(accepted),
        "known_reference_judgments": sum(
            c["retrieval"]["known_reference_judgments"] for c in fresh_cases
        ),
        "cost_per_accepted_result": str(total_cost / len(accepted))
        if accepted and known_cost
        else None,
    }
    report.update(
        human_labels=None if not records else {k: v.model_dump() for k, v in records.items()},
        acceptance=outcome
        + ": "
        + (", ".join(reasons) if reasons else "predeclared observed-label gates met")
        + " ("
        + basis
        + ")",
        checker_qualified=False,
        everyday_generation=False,
    )
    return report
