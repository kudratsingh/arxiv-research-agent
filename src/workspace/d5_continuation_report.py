"""Versioned behavior reports with independently bound judgments and liabilities."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest


def liabilities(conn: Any, program_id: str, retained: list[dict[str, Any]]) -> dict[str, Any]:
    """Read every liability; verify all authorized rows instead of trusting IDs."""
    from src.workspace.admission import ACTIVE
    from src.workspace.qualification_budget import census

    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
        )
    )
    if not members:
        raise AdmissionError("continuation_programme_members_missing")
    total = census(conn, members[0], members=members)
    expected = {r["job_id"]: r for r in retained}
    if len(expected) != len(retained):
        raise AdmissionError("continuation_duplicate_retained_hold")
    rows, issues = [], []
    found = set()
    for r in conn.execute(
        "SELECT j.id,j.owner,j.state,r.amount::text,r.unknown::text,j.data,r.workflow,r.judge "
        "FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id "
        "WHERE (j.owner=ANY(%s) AND (r.unknown>0 OR j.state=ANY(%s))) OR j.id=ANY(%s) ORDER BY j.id",
        (members, sorted(ACTIVE), list(expected)),
    ):
        actual = {
            "job_id": r[0],
            "owner": r[1],
            "state": r[2],
            "amount": r[3],
            "unknown": r[4],
            "data_digest": _digest(r[5]),
        }
        prior = expected.get(r[0])
        if prior is not None:
            found.add(r[0])
        bound = prior is not None and actual == prior
        classification = (
            "historical_authorized_quarantine"
            if bound
            else "historical_hold_binding_drift"
            if prior
            else "new_external_uncertainty"
            if Decimal(r[4]) > 0
            else "new_pending_reservation"
        )
        if prior and not bound:
            issues.append(
                {
                    "job_id": r[0],
                    "reason": "retained_hold_binding_drift",
                    "expected": prior,
                    "actual": actual,
                }
            )
        rows.append(
            {
                **actual,
                "original_reservation_USD": r[3],
                "pending_exposure_USD": str(
                    max(Decimal(r[4]), Decimal(r[3]) - r[6] - r[7])
                    if r[2] in ACTIVE
                    else Decimal(r[4])
                ),
                "unknown_USD": r[4],
                "classification": classification,
            }
        )
    for missing in sorted(set(expected) - found):
        issues.append(
            {"job_id": missing, "reason": "retained_hold_missing", "expected": expected[missing]}
        )
    retained_rows = [r for r in rows if r["classification"] == "historical_authorized_quarantine"]
    return {
        "basis": "Authoritative programme reservation rows and census; no hardcoded hold amount",
        "financial_integrity": "FAIL" if issues else "PASS",
        "integrity_issues": issues,
        "rows": rows,
        "validated_retained_components": retained_rows,
        "new_liabilities": [
            r
            for r in rows
            if r["classification"] in {"new_external_uncertainty", "new_pending_reservation"}
        ],
        "retained_liability_USD": str(
            sum((Decimal(r["unknown_USD"]) for r in retained_rows), Decimal(0))
        ),
        "expected_retained_liability_USD": str(
            sum((Decimal(r["unknown"]) for r in retained), Decimal(0))
        ),
        "all_unknown_USD": total["unknown_usd"],
        "pending_including_unknown_USD": total["pending_usd"],
        "known_estimated_USD": total["known_usd"],
        "combined_exposure_USD": str(Decimal(total["known_usd"]) + Decimal(total["pending_usd"])),
        "unknown_is_subset_of_pending": True,
        "invoice_confirmed": False,
        "exporter_financial_mutations": 0,
    }


def probe_verdicts(
    case: dict[str, Any], snapshot: dict[str, Any] | None, packet: dict[str, Any], materials: Any
) -> dict[str, Any]:
    """Accept only complete frozen-input-bound probe judgments; never invent them."""
    from dataclasses import asdict

    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
    from jsonschema import ValidationError as SchemaError

    from src.workspace.assistance_keyed_checks import probe_checks_model
    from src.workspace.d5_adapter import prepare_input
    from src.workspace.d5_capacity_policy import MAX_HTTP_BYTES
    from src.workspace.d5_case_isolation import _complete_body
    from src.workspace.d5_operations import route, verdict_text
    from src.workspace.d5_report_binding import ReportBindingError, json_object, message_output
    from src.workspace.grounding import ClaimKind, EvidenceRef, ResearchClaim, claim_input_digest
    from src.workspace.qualification_accounting import priced_usage

    def require(ok: bool, reason: str) -> None:
        if not ok:
            raise ReportBindingError(reason)

    if not snapshot:
        return {"binding": "unavailable", "reason": "probe_unrun", "verdicts": {}}
    try:
        sealed, body = case["sealed"], case["wire"]
        compact = prepare_input(
            sealed,
            scope_id="report-only",
            packet_digest=packet["packet_digest"],
            case_id=case["id"],
            operation="probe",
            probe_wire=body,
            operation_routes=packet["operation_routes"],
            operation_deadlines=packet["operation_deadlines"],
            capacity_policy=packet["capacity_policy"],
        ).settings["d5_request"]
        require(
            snapshot["case_id"] == case["id"]
            and snapshot["packet_digest"] == packet["packet_digest"]
            and snapshot["operation"] == "probe"
            and snapshot["state"] == "ready"
            and snapshot["source_binding_intact"] is True
            and snapshot["request"] == compact,
            "probe_case_packet_source_or_request_drift",
        )
        contacts, steps = snapshot["contacts"], snapshot["steps"]
        require(len(contacts) == 2 and len(steps) == 1, "probe_exact_journal_required")
        count, message = contacts
        for index, contact in enumerate(contacts):
            require(
                type(contact["ordinal"]) is int
                and contact["ordinal"] == index
                and contact["state"] == "completed"
                and contact["stage"] == "check"
                and contact["request_digest"] == _digest(contact["body"])
                and contact["generation_request_digest"] == _digest(body),
                "probe_contact_binding_drift",
            )
            _complete_body(contact, MAX_HTTP_BYTES)
        require(
            count["endpoint"] == "messages/count_tokens"
            and message["endpoint"] == "messages"
            and count["body"]
            == {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
            and message["body"] == body
            and type(count["response"]["input_tokens"]) is int
            and 0 <= count["response"]["input_tokens"] <= 32000,
            "probe_exact_paired_count_required",
        )
        raw = json_object(verdict_text(message["response"]))
        Draft202012Validator(body["output_config"]["format"]["schema"]).validate(raw)
        context = json_object(body["messages"][0]["content"])
        parsed = message_output(message)
        checked = probe_checks_model().model_validate(parsed)
        checked.validate_locations(context.get("unscored_prose", {}))
        require(
            steps[0]["stage"] == "check"
            and steps[0]["request_digest"] == _digest(body)
            and {k: v for k, v in steps[0]["output"].items() if k != "grounding"} == parsed,
            "probe_step_not_bound_to_response",
        )
        claims = [
            ResearchClaim(
                **{
                    **c,
                    "kind": ClaimKind(c["kind"]),
                    "evidence": tuple(EvidenceRef(**r) for r in c["evidence"]),
                }
            )
            for c in context["draft"]["claims"]
        ]
        expected = {c.claim_id: claim_input_digest(c, materials) for c in claims}
        require(
            len(expected) == len(claims)
            and all(asdict(ref) in sealed["units"].values() for c in claims for ref in c.evidence)
            and expected == {r["claim_id"]: r["input_digest"] for r in context["claim_inputs"]}
            and len(expected) == len(context["claim_inputs"])
            and expected == {c.claim_id: c.input_digest for c in checked.checks}
            and len(expected) == len(checked.checks),
            "probe_claim_evidence_or_judgment_drift",
        )
        selected = route(packet["operation_routes"], "check")
        ins, outs, cost = priced_usage(
            message["response"],
            {
                "model_id": body["model"],
                "settings": {"price_estimate_usd_per_million": selected["prices"]},
            },
        )
        require(
            message["response"]["stop_reason"] == "end_turn"
            and ins <= selected["input_tokens"]
            and outs <= selected["output_tokens"]
            and Decimal(snapshot["unknown_usd"]) == 0
            and Decimal(snapshot["workflow_usd"]) == 0
            and Decimal(snapshot["checker_usd"]) == (Decimal(0) if snapshot["simulated"] else cost),
            "probe_completion_or_usage_binding_drift",
        )
        return {
            "binding": "bound",
            "verdicts": {c.claim_id: c.decision for c in checked.checks},
            "request_digest": _digest(body),
            "response_digest": _digest(message["response"]),
            "context_digest": _digest(context),
            "judgments_digest": _digest(parsed),
        }
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        OSError,
        EOFError,
        SchemaError,
        AdmissionError,
    ) as exc:
        return {"binding": "unavailable", "reason": str(exc), "verdicts": {}}


def _bound_probes(packet: dict[str, Any], raw: dict[str, Any], materials: Any) -> dict[str, Any]:
    return {
        p["id"]: probe_verdicts(p, raw.get(p["id"]), packet, materials) for p in packet["probes"]
    }


def results(
    store: Any, packet: dict[str, Any], *, stop: dict[str, Any] | None = None
) -> dict[str, Any]:
    from src.workspace.d5_behavior_scoring import score_campaign
    from src.workspace.d5_campaign_report import _legacy_results, score_workflow
    from src.workspace.d5_freeze import compile_inputs
    from src.workspace.executor import FakeExecutor

    base = _legacy_results(store, packet, stop=stop)
    compiled = compile_inputs(packet)
    with store.pool.connection() as conn:
        materials = tuple(
            FakeExecutor(store)._sources(
                conn, next(iter(compiled.values()))["owner"], [m["material_id"]]
            )[0]
            for m in packet["materials"]
        )
        financial = liabilities(
            conn, packet["program_id"], packet["campaign_extension"]["core"]["retained_exceptions"]
        )
    bindings = _bound_probes(packet, base["raw_results"], materials)
    verdicts = {k: v for b in bindings.values() for k, v in b["verdicts"].items()}
    score = score_campaign(
        packet["cases"],
        base["raw_results"],
        materials,
        packet["answerability"],
        packet["probe_references"],
        verdicts,
        routes=packet["operation_routes"],
    )
    accounting = {
        **base["accounting"],
        "authoritative_liabilities": financial,
        "retained_hold_usd": financial["retained_liability_USD"],
        "retained_hold_components": financial["validated_retained_components"],
        "financial_integrity": financial["financial_integrity"],
        "cost_per_quality_accepted_result": None,
    }
    report = {
        "revision": "d5-behavior-continuation-report-v20",
        "packet_digest": packet["packet_digest"],
        "application_commit": packet["application_commit"],
        "basis": score["basis"],
        "protocol_cohort": packet["revision"],
        "cases": score["workflows"],
        "development_cases": [
            score_workflow(
                c, base["raw_results"].get(c["id"]), materials, routes=packet["operation_routes"]
            )
            for c in packet["cases"]
            if c["cohort"] == "development"
        ],
        "probe_bindings": bindings,
        "case_census": {
            key: {
                "case_id": key,
                "stage": compiled[key]["stage"],
                **base["outcomes"].get(key, {"state": "unrun"}),
            }
            for key in packet["schedule"]
        },
        "financial_integrity": financial["financial_integrity"],
        "raw_results": base["raw_results"],
        "outcomes": base["outcomes"],
        **score,
        "accounting": accounting,
        "stop": stop,
        "human_labels": None,
        "checker_qualified": False,
        "everyday_generation": False,
        "continuation_summary": packet["continuation_lineage"],
        "historical_results": "Original v19 FAIL and eight-case denominator are immutable. This scope has four exposed Research controls; development/history cannot fill its 20-reviewed-claim minimum. Not fresh held-out evidence.",
        "limitations": "Machine-only exposed corpus; inherited abstract bibliography not newly verified; correlated claims/probes; human usefulness and checker reliability unmeasured.",
        "outcome_diagnostics": base.get("outcome_diagnostics", {}),
    }
    if financial["financial_integrity"] != "PASS":
        report["behavioral_gate"] = report["machine_quality"] = "FAIL"
        report["gate_reasons"] = [*report["gate_reasons"], "historical_liability_binding_drift"]
    if financial["new_liabilities"]:
        report["machine_quality"] = "HOLD" if report["machine_quality"] != "FAIL" else "FAIL"
        report["gate_reasons"] = [*report["gate_reasons"], "new_external_liability_unresolved"]
    accepted = [
        c
        for c in report["cases"]
        if c["review_complete"]
        and c["contract_complete"]
        and not c["behavior_errors"]
        and c["state"] == "ready"
        and all(p["behavior"] == "PASS" for p in report["parts"] if p["case_id"] == c["id"])
    ]
    report["machine_behaviorally_satisfactory_results"] = len(accepted)
    accounting["cost_per_behaviorally_satisfactory_result"] = (
        str(Decimal(accounting["new_scope"]["known_usd"]) / len(accepted))
        if accepted and not any(c.get("simulated") for c in accepted)
        else None
    )
    accounting["cost_denominator_basis"] = (
        "All new-scope workflow/checker costs including development and probes; current Research behaviorally satisfactory results only. Not full research-need satisfaction or human acceptance."
    )
    if report["machine_quality"] == "PASS_MACHINE_ONLY":
        accounting["cost_per_quality_accepted_result"] = accounting[
            "cost_per_behaviorally_satisfactory_result"
        ]
    report["analysis_receipt"] = {
        "revision": "d5-behavior-analysis-v20",
        "original_packet_digest": packet["packet_digest"],
        "raw_results_digest": _digest(base["raw_results"]),
        "scoring_policy": score["scoring_policy"],
        "reference_matrix_digest": packet["answerability"]["matrix_digest"],
        "scorer_code": packet["continuation_producer"],
        "report_digest_excluding_receipt": _digest(report),
        "human_review_digest": None,
        "historical_records_modified": False,
    }
    return report


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Prospective D5 continuation — machine only",
        "",
        report["basis"],
        "",
        "Behavioral gate: " + report["behavioral_gate"],
        "Machine quality: " + report["machine_quality"],
        "",
        "| Case | Contract complete | Behavioral errors | Review gaps |",
        "|---|---|---|---|",
    ]
    for c in report["cases"]:
        lines.append(
            f"| {c['id']} | {c.get('contract_complete')} | {c.get('behavior_errors')} | {c.get('review_gaps')} |"
        )
    lines += [
        "",
        "Research-need fulfillment: " + str(report["request_fulfillment_counts"]),
        "",
        report["historical_results"],
        "",
        str(report["denominators"]),
        "",
        "Authoritative financial exposure: "
        + str(report["accounting"]["authoritative_liabilities"]),
        "",
        "Stop: " + str(report["stop"]),
        "",
        report["limitations"],
    ]
    return "\n".join(lines) + "\n"


def analyze_archive(packet_path: Path, result_path: Path, out: Path) -> dict[str, Any]:
    """Read-only, explicitly versioned derivative; never edit an old report."""
    import hashlib

    from src.workspace.d5_behavior_scoring import score_campaign
    from src.workspace.d5_benchmark import read, write
    from src.workspace.d5_compatibility_packet import materials
    from src.workspace.d5_continuation_packet import BASE, predecessor, producer_bindings

    p, original = read(packet_path), read(result_path)
    if (
        p != predecessor()
        or p["packet_digest"] != BASE
        or original["packet_digest"] != BASE
        or original["analysis_receipt"]["raw_results_digest"] != _digest(original["raw_results"])
    ):
        raise ValueError("historical_analysis_original_binding_mismatch")
    source_materials = materials(p)
    bindings = _bound_probes(p, original["raw_results"], source_materials)
    verdicts = {k: v for b in bindings.values() for k, v in b["verdicts"].items()}
    score = score_campaign(
        p["cases"],
        original["raw_results"],
        source_materials,
        p["answerability"],
        p["probe_references"],
        verdicts,
        routes=p["operation_routes"],
    )
    receipt = {
        "at": datetime.now(UTC).isoformat(),
        "revision": "explicit-v19-analysis-under-v20",
        "original_packet_digest": BASE,
        "original_report_file_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "original_raw_result_digest": _digest(original["raw_results"]),
        "original_machine_quality": original["machine_quality"],
        "new_scorer": producer_bindings(),
        "new_scoring_policy": score["scoring_policy"],
        "review_file_digest": None,
        "historical_records_modified": False,
        "financial_records_modified": False,
        "new_provider_contacts": 0,
    }
    value = {
        "original_scope": "v19 immutable",
        "original_frozen_quality": original["machine_quality"],
        "versioned_derivative": score,
        "probe_bindings": bindings,
        "analysis_receipt": receipt,
    }
    write(out, value)
    return value
