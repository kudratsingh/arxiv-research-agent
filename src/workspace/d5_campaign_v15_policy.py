"""Prospective complete-response capacity; no grant, contact or settlement.

The v13 constants stay unchanged. These limits require a new exact owner
receipt, including the proposed dollar adjustment and both retained holds.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_capacity_policy import ROUTES as ROUTES
from src.workspace.d5_capacity_policy import enabled as capacity_enabled

REVISION = "d5-comprehensive-machine-campaign-v15"
LIMITS: dict[str, Any] = {
    "jobs": 14, "messages": 44, "counts": 44, "usd": "20", "concurrency": 1,
    "workflow_usd": "1.20", "probe_usd": "0.50", "headroom_usd": "2.00", "new_usd": "14.00",
}
PROGRAM_LIMITS = {"new_jobs": 64, "messages": 160, "counts": 200, "usd": "20", "concurrency": 1}
PROGRESSION = {
    "revision": "development-bound-complete-checks-v1",
    "development_jobs": 2,
    "before_evaluation": "Both development identities must have complete, input-bound final checker responses after their current draft/repair. A valid negative quality verdict is not a broken contract and does not become accepted content.",
    "broken_development_contract": "STOP; no evaluation or probe dispatch",
    "negative_development_quality": "Preserve failure, allow the next sealed identity when its complete response contract is proven",
    "evaluation_content_rejection": "Preserve fully metered failures and continue unrelated sealed cases",
    "provider_error_or_new_uncertainty": "STOP; no retry or replacement identity",
}


def enabled(settings: Mapping[str, Any]) -> bool:
    return capacity_enabled(dict(settings))


def development_contract(conn: Any, scope_id: str, case_id: str) -> dict[str, Any]:
    """Recompute protocol evidence; never infer quality from successful parsing."""
    from src.workspace.assistance import checks_model
    from src.workspace.assistance_coverage import validate_review
    from src.workspace.d5_capacity_policy import ASSISTANCE_REVISION
    from src.workspace.d5_report_binding import current_check
    from src.workspace.material import SourceMaterial, SourceSpan

    row = conn.execute(
        "SELECT r.input_digest,j.id,j.state,j.input_digest,j.data FROM workspace_d5_case_runs r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.scope_id=%s AND r.case_id=%s",
        (scope_id, case_id),
    ).fetchone()
    if not row:
        raise AdmissionError("campaign_development_contract_incomplete")
    expected, job_id, state, actual, data = row
    inputs = data.get("sealed_input", {})
    settings = inputs.get("settings", {})
    if (
        state not in {"ready", "failed"}
        or expected != actual
        or _digest(inputs) != expected
        or not enabled(settings)
        or settings.get("d5_case_id") != case_id
        or settings.get("d5_scope_id") != scope_id
    ):
        raise AdmissionError("campaign_development_binding_drift")
    sealed = settings["d5_request"]
    materials = []
    for source in inputs["sources"]:
        material = conn.execute(
            "SELECT data FROM workspace_material WHERE material_id=%s", (source["material_id"],)
        ).fetchone()
        if not material:
            raise AdmissionError("campaign_development_material_unavailable")
        value = material[0]
        materials.append(
            SourceMaterial(
                **{
                    **value,
                    "spans": tuple(SourceSpan(**s) for s in value["spans"]),
                }
            )
        )
    try:
        binding = current_check(sealed, data.get("adapter", {}), tuple(materials), routes=ROUTES)
        verdict = checks_model(ASSISTANCE_REVISION).model_validate(binding["raw_verdict"])
        validate_review(verdict, binding["context"])
        verdict.validate_locations(binding["context"].get("unscored_prose", {}))
        expected_claims = {
            c["claim_id"]: c["input_digest"] for c in binding["context"]["claim_inputs"]
        }
        if (
            len(verdict.checks) != len(expected_claims)
            or {c.claim_id: c.input_digest for c in verdict.checks} != expected_claims
        ):
            raise ValueError("checker_claim_binding_mismatch")
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise AdmissionError("campaign_development_contract_incomplete") from exc
    return {
        "revision": PROGRESSION["revision"],
        "case_id": case_id,
        "job_id": job_id,
        "input_digest": expected,
        "contract_complete": True,
        "assessment_binding": binding["binding"],
        "quality_accepted": state == "ready",
        "quality_is_human_qualified": False,
        "verdict_digest": _digest(binding["raw_verdict"]),
    }


def require_development_contracts(conn: Any, bound: dict[str, Any]) -> list[dict[str, Any]]:
    required = [k for k, v in bound["cases"].items() if v["stage"] == "B"]
    if len(required) != 2:
        raise AdmissionError("campaign_two_development_contracts_required")
    return [development_contract(conn, bound["id"], key) for key in required]
