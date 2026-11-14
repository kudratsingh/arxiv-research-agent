"""Machine-only scorecard; never rewrites evidence, human labels or accounting."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from src.workspace.admission import _digest


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def score_probes(references: dict[str, Any], verdicts: dict[str, Any]) -> dict[str, Any]:
    groups = {}
    for label in ("supported", "unsupported"):
        keys = [key for key, value in references.items() if value["reference"] == label]
        decisions = [verdicts.get(key) for key in keys]
        valid = [d for d in decisions if d in {"supported", "unsupported", "abstain"}]
        decisive = [d for d in valid if d != "abstain"]
        errors = sum(
            d == ("unsupported" if label == "supported" else "supported") for d in decisive
        )
        groups[label] = {
            "planned": len(keys),
            "observed": len(valid),
            "decisive": len(decisive),
            "errors": errors,
            "error_rate_conditional": ratio(errors, len(decisive)),
            "abstentions": valid.count("abstain"),
            "missing_or_invalid": len(keys) - len(valid),
        }
    return {
        "basis": "Frozen machine-reference controls, not human gold; raw checker verdicts, separate from mechanical scope overrides",
        "false_pass": groups["unsupported"],
        "false_reject": groups["supported"],
        "acceptable_abstention_blocks": groups["supported"]["abstentions"],
        "unique_evidence": len({_digest(r["evidence"]) for r in references.values()}),
        "unique_claim_evidence_pairs": len({r["claim_digest"] for r in references.values()}),
        "matched_sets": len({r["matched_pair"] for r in references.values()}),
        "independent_samples": False,
    }


def score_workflow(
    case: dict[str, Any], snapshot: dict[str, Any] | None, materials: Any, *, routes: Any = None
) -> dict[str, Any]:
    from src.workspace.assistance import checks_model
    from src.workspace.assistance_contract import resolve_draft
    from src.workspace.assistance_policy import render_task_output
    from src.workspace.d5_report_binding import ReportBindingError, current_check
    from src.workspace.grounding import (
        EvidenceRef,
        SupportCheck,
        claim_input_digest,
        validate_claims,
    )

    result: dict[str, Any] = {
        "id": case["id"],
        "cohort": case["cohort"],
        "pipeline": case["pipeline"],
        "state": snapshot["state"] if snapshot else "unrun",
        "completion": bool(snapshot and snapshot["state"] == "ready"),
        "requested_parts": case["sealed"]["task_policy"]["requested_parts"],
        "claims": [],
        "declared_coverage": None,
        "machine_coverage": None,
        "claim_quality": None,
        "prose_review": None,
        "prose_findings": None,
        "assessment_binding": {"status": "unavailable", "reason": "no_current_completed_check"},
        "abstention": None,
        "response_disposition": None,
        "mechanical_provenance": None,
        "whole_claim_support": None,
        "human_review": None,
        "human_qualified": False,
        "retrieval": {
            "ranking": case["ranking"],
            "edition": case["edition"],
            "selection": case["evidence_selection"],
            "baselines": case["baselines"],
            "known_reference_recall": None,
            "owner_usefulness": None,
            "literature_recall": None,
        },
    }
    if not snapshot:
        return result
    result.update(
        workflow_usd=snapshot["workflow_usd"],
        checker_usd=snapshot["checker_usd"],
        unknown_usd=snapshot["unknown_usd"],
        latency_seconds=snapshot["latency_seconds"],
        raw_result_id=snapshot["id"],
        simulated=snapshot["simulated"],
    )
    drafts = [s for s in snapshot.get("steps", []) if s["stage"] in {"draft", "repair"}]
    if not drafts:
        result["completion"] = False
        return result
    sealed = case["sealed"]
    output = {k: v for k, v in drafts[-1]["output"].items() if k != "grounding"}
    try:
        draft, claims = resolve_draft(
            output,
            {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
            materials,
            purpose=sealed["response_purpose"],
            revision=sealed["schema_revision"],
            task_policy=sealed["task_policy"],
        )
        rendered = render_task_output(
            output, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
        )
        result["declared_coverage"] = rendered.get("request_coverage")
        result["abstention"] = rendered.get("abstention")
        result["response_disposition"] = rendered.get("response_disposition")
        provenance = validate_claims(claims, materials)
        result["mechanical_provenance"] = (
            all(a.identity_resolved and a.scope_compatible for a in provenance.assessments)
            if claims
            else None
        )
        result["claims"] = [
            {**asdict(c), "input_digest": claim_input_digest(c, materials), "human_support": None}
            for c in claims
        ]
        try:
            bound = current_check(sealed, snapshot, materials, routes=routes)
            contact, context, raw = bound["contact"], bound["context"], bound["raw_verdict"]
            body = contact["body"]
            parsed = checks_model(sealed["schema_revision"]).model_validate(raw)
            from src.workspace.assistance_coverage import validate_review

            validate_review(parsed, context)
            parsed.validate_locations(context.get("unscored_prose", {}))
            expected = {c.claim_id: claim_input_digest(c, materials) for c in claims}
            actual = {c.claim_id: c.input_digest for c in parsed.checks}
            # A prior check must not be attached to a later repair that has not been checked.
            if actual == expected and len(actual) == len(parsed.checks):
                reviews = tuple(
                    SupportCheck(
                        c.claim_id,
                        c.input_digest,
                        c.decision,
                        body["model"],
                        "campaign-machine-check",
                        c.reason,
                    )
                    for c in parsed.checks
                )
                grounding = validate_claims(claims, materials, reviews)
                result.update(
                    assessment_binding=bound["binding"],
                    whole_claim_support=asdict(grounding),
                    machine_coverage=raw.get("coverage_checks"),
                    claim_quality=raw.get("claim_quality"),
                    prose_review=raw.get("prose_review"),
                    prose_findings=raw.get("prose_findings"),
                )
            else:
                raise ReportBindingError("checker_claim_binding_mismatch")
        except (ValueError, KeyError, TypeError, IndexError) as exc:
            result["completion"] = False
            result["assessment_binding"] = {
                "status": "unavailable",
                "reason": str(exc)
                if isinstance(exc, ReportBindingError)
                else "invalid_or_unbound_checker",
            }
    except (ValueError, KeyError, TypeError):
        result["completion"] = False
        result["mechanical_provenance"] = False
        result["scoring_error"] = "invalid_or_unbound_output; no quality pass"
    return result


def results(
    store: Any, packet: dict[str, Any], *, stop: dict[str, Any] | None = None
) -> dict[str, Any]:
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_freeze import compile_inputs
    from src.workspace.d5_results import QualificationResults
    from src.workspace.executor import FakeExecutor
    from src.workspace.qualification_budget import census

    compiled = compile_inputs(packet)
    scope = "d5-" + packet["packet_digest"][:24]
    snapshots = {}
    with store.pool.connection() as conn:
        for key, e in compiled.items():
            row = conn.execute(
                "SELECT job_id FROM workspace_d5_case_runs WHERE scope_id=%s AND case_id=%s",
                (scope, key),
            ).fetchone()
            if row:
                snapshots[key] = QualificationResults(store).snapshot(e["owner"], row[0])
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (packet["program_id"],),
            )
        )
        total = census(conn, members[0], members=members)
        baseline = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s",
            (packet["program_id"],),
        ).fetchone()[0]
        total["funded_programme_jobs"] = len(
            set(total["generation_job_ids"]) - set(baseline["generation_job_ids"])
        )
        new = census(
            conn,
            next(iter(compiled.values()))["owner"],
            members=sorted({e["owner"] for e in compiled.values()}),
        )
        outcomes = audit_outcomes(conn, scope)
        materials = tuple(
            FakeExecutor(store)._sources(
                conn, next(iter(compiled.values()))["owner"], [m["material_id"]]
            )[0]
            for m in packet["materials"]
        )
    cases = [score_workflow(c, snapshots.get(c["id"]), materials, routes=packet.get("operation_routes")) for c in packet["cases"]]
    verdicts = {}
    for probe in packet["probes"]:
        observed = snapshots.get(probe["id"], {})
        for step in observed.get("steps", []):
            if step["stage"] == "check":
                verdicts.update({v["claim_id"]: v["decision"] for v in step["output"]["checks"]})
    probes = score_probes(packet["probe_references"], verdicts)
    from src.workspace.d5_answerability import score_parts

    evaluation = [c for c in cases if c["cohort"] != "development"]
    part_scores = [r for c in evaluation for r in score_parts(c, packet["answerability"])]
    facts = [c for case in evaluation for c in case["claims"]]
    supported = sum((c.get("whole_claim_support") or {}).get("supported", 0) for c in evaluation)
    checked = sum((c.get("whole_claim_support") or {}).get("checked", 0) for c in evaluation)
    complete = sum(c["completion"] for c in evaluation)
    probe_complete = all(
        v["observed"] == v["planned"] for v in (probes["false_pass"], probes["false_reject"])
    )
    rejected = sum(c["state"] == "failed" for c in evaluation)
    mechanically_complete = sum(c["completion"] for c in cases)
    coverage = []
    bundled = lost = 0
    for case in evaluation:
        declared = case.get("declared_coverage") or {}
        if isinstance(declared, list):
            declared = {r["id"]: r for r in declared}
        primary = declared.get("p1", {})
        reviews = case.get("machine_coverage") or []
        primary_review: dict[str, Any] = next((r for r in reviews if r["part_id"] == "p1"), {})
        expected_abstention = "insufficient" in case["id"]
        coverage.append(
            {
                "case_id": case["id"],
                "primary_declared_status": primary.get("status"),
                "primary_machine_status": primary_review.get("decision"),
                "request_answered": primary.get("status")
                == primary_review.get("decision")
                == "answered",
                "expected_application_abstention": expected_abstention,
                "abstention_observed": bool(case.get("abstention")),
                "comparison_remains_unanswered": "retrieval" in case["id"]
                and primary.get("status") != "answered",
            }
        )
        for claim in case.get("claim_quality") or []:
            bundled += claim["atomicity"] == "bundled"
            lost += sum(v == "lost" for v in claim["qualifications"].values())
    missing_primary = sum(
        not c["request_answered"] and not c["expected_application_abstention"] for c in coverage
    )
    bad_provenance = any(c["mechanical_provenance"] is False for c in evaluation)
    quality = (
        "FAIL"
        if rejected
        or bad_provenance
        or bundled
        or lost
        or probes["false_pass"]["errors"]
        or probes["false_reject"]["errors"]
        else "HOLD"
    )
    simulated = bool(snapshots) and all(s["simulated"] for s in snapshots.values())
    if (
        not simulated
        and quality != "FAIL"
        and not missing_primary
        and all(r["request_fulfillment"] == "met" for r in part_scores)
        and complete == 8
        and len(facts) >= 20
        and checked == supported == len(facts)
        and probe_complete
        and not any(
            probes[k]["abstentions"] or probes[k]["errors"] for k in ("false_pass", "false_reject")
        )
    ):
        quality = "PASS_MACHINE_ONLY"
    report = {
        "packet_digest": packet["packet_digest"],
        "application_commit": packet["application_commit"],
        "basis": "SIMULATED SOFTWARE EVIDENCE ONLY"
        if simulated
        else "Quarantined machine-only exposed-corpus evaluation; no human qualification",
        "cases": cases,
        "raw_results": snapshots,
        "outcomes": outcomes,
        "probe_scores": probes,
        "probe_reference_digest": packet["probe_reference_digest"],
        "denominators": {
            "evaluation_workflows": 8,
            "completed_evaluation": complete,
            "failed_evaluation": rejected,
            "unrun_evaluation": sum(c["state"] == "unrun" for c in evaluation),
            "generated_evaluation_claims": len(facts),
            "machine_checked_claims": checked,
            "machine_supported_claims": supported,
            "human_reviewed_claims": 0,
            "probe_records": 20,
        },
        "machine_quality": quality,
        "request_coverage": coverage,
        "answerability": {
            "matrix_digest": packet["answerability"]["matrix_digest"],
            "scoring_policy": packet["scoring"]["revision"],
            "parts": part_scores,
            "denominator": 24,
            "counts": {
                status: sum(r["request_fulfillment"] == status for r in part_scores)
                for status in (
                    "met",
                    "partial",
                    "unmet",
                    "omitted_answer",
                    "unsupported_answer",
                    "UNSCORED",
                )
            },
            "human_review": None,
        },
        "claim_quality_counts": {
            "bundled": bundled,
            "lost_qualifications": lost,
            "unanswered_primary_requests": missing_primary,
        },
        "human_qualification": False,
        "human_labels": None,
        "checker_qualified": False,
        "everyday_generation": False,
        "stop": stop,
        "accounting": {
            "cumulative": total,
            "historical": packet["history"],
            "new_scope": new,
            "retained_hold_usd": "0.425066",
            "hold_is_pending_unknown_overlap_not_additive": True,
            "new_estimated_usd": new["known_usd"],
            "cost_per_mechanically_completed_workflow": float(
                Decimal(new["known_usd"]) / mechanically_complete
            )
            if mechanically_complete and not simulated
            else None,
            "cost_per_quality_accepted_result": float(Decimal(new["known_usd"]) / complete)
            if quality == "PASS_MACHINE_ONLY" and complete
            else None,
            "invoice_confirmed": False,
        },
        "historical_results": "v7r2 3/8, v8r4b and all stopped development cohorts remain unchanged and separate; no failures replayed into historical passes",
        "limitations": "Frozen public snapshot, known extraction limits, exposed sources, proposed machine references and correlated claims. Human usefulness/qualification and literature recall remain unmeasured.",
    }

    if packet.get("revision") == "d5-comprehensive-machine-campaign-v15":
        from src.workspace.d5_capacity_outcomes import classify_outcome
        from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY
        diagnostics = {}
        by_case = {case["id"]: case for case in cases}
        for key in compiled:
            case = by_case.get(key, {})
            observed = snapshots.get(key, {})
            outcome = dict(outcomes.get(key, {"state": case.get("state", "unrun")}))
            if key not in outcomes and stop and stop["case_id"] == key:
                outcome["content_rejection"] = {"error": stop["reason"], "error_class": stop["error_class"], "accepted": False}
            if case.get("completion") and case.get("assessment_binding", {}).get("status") == "bound":
                outcome.update(mechanical_complete=True, quality_acceptance=True)
            diagnostics[key] = classify_outcome(outcome, {**observed, "binding": case.get("assessment_binding")})
        report["outcome_diagnostics"] = diagnostics
        report["capacity_policy"] = CAPACITY_POLICY
        report["diagnostic_basis"] = "Formatting observations never gate. Execution/contract/capacity and machine quality remain separate; no human qualification."
        if simulated:
            report["machine_quality"] = "HOLD"
            report["simulation_disposition"] = "Software behavior only; token fit, remote schema acceptance and model quality remain unmeasured."
        report["accounting"]["retained_hold_usd"] = "0.875066"
        report["accounting"]["retained_hold_components"] = [
            {"kind": "unknown_upstream_completion", "usd": "0.425066"},
            {"kind": "received_http400_usage_unvalidated", "usd": "0.45"},
        ]
        report["accounting"]["new_scope"]["models"] = sorted({c.get("body", {}).get("model") for snapshot in snapshots.values() for c in snapshot.get("contacts", []) if isinstance(c.get("body", {}).get("model"), str)})
    return {
        **report,
        "analysis_receipt": {
            "revision": "workspace-campaign-analysis-capacity-v2" if packet.get("revision") == "d5-comprehensive-machine-campaign-v15" else "workspace-campaign-analysis-v1",
            "original_packet_digest": packet["packet_digest"],
            "raw_results_digest": _digest(snapshots),
            "report_digest_excluding_receipt": _digest(report),
            "scoring_policy": packet["scoring"]["revision"],
            "answerability_matrix_digest": packet["answerability"]["matrix_digest"],
            "scorer_code": {
                name: value
                for name, value in packet["code"].items()
                if name.endswith(
                    ("d5_campaign_report.py", "d5_report_binding.py", "d5_answerability.py") + (("d5_capacity_outcomes.py", "d5_capacity_policy.py") if packet.get("revision") == "d5-comprehensive-machine-campaign-v15" else ())
                )
            },
            "human_review_digest": None,
            "historical_records_modified": False,
        },
    }


def markdown(report: dict[str, Any]) -> str:
    rows = [
        "# D5 consolidated campaign — machine only",
        "",
        report["basis"],
        "",
        "| Case | Cohort | State | Provenance |",
        "|---|---|---|---|",
    ]
    rows += [
        f"| {c['id']} | {c['cohort']} | {c['state']} | {c['mechanical_provenance']} |"
        for c in report["cases"]
    ]
    rows += [
        "",
        "Machine quality: " + report["machine_quality"],
        "",
        "Human qualification and everyday generation remain disabled.",
        "",
        report["limitations"],
        "",
        "```json",
        json.dumps(
            {
                k: report[k]
                for k in ("denominators", "answerability", "probe_scores", "accounting", "stop")
            },
            indent=2,
        ),
        "```",
        "",
        "## Exact claims and retained passages",
    ]
    for c in report["cases"]:
        rows += [
            "",
            "### " + c["id"],
            "",
            "Declared coverage (not independently verified fulfillment):",
            "",
            json.dumps(c["declared_coverage"], ensure_ascii=False),
            "",
            "Machine coverage: " + json.dumps(c["machine_coverage"], ensure_ascii=False),
        ]
        for claim in c["claims"]:
            rows += ["", claim["claim_id"] + ": " + claim["text"]]
            for ref in claim["evidence"]:
                rows += [
                    "",
                    f"Source `{ref['work_id']}` · version `{ref['version_id']}` · {ref['scope']} · page {ref['page']} · offsets {ref['start']}–{ref['end']} · span `{ref['span_id']}`",
                    "",
                    "> " + ref["quote"].replace("\n", "\n> "),
                ]
    return "\n".join(rows) + "\n"
