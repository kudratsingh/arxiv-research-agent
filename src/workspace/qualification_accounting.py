"""Audited completion accounting, independent of whether content is accepted.

No HTTP client, credential loading or approval writer. Completed metered replies
can close a failed job's unused hold; incomplete external receipts cannot.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, GenerationAdmission, _digest, _money
from src.workspace.store import WorkspaceStore


def priced_usage(response: dict[str, Any], sealed: dict[str, Any]) -> tuple[int, int, Decimal]:
    usage = response.get("usage", {})
    ins, outs = usage.get("input_tokens"), usage.get("output_tokens")
    if (
        response.get("model") != sealed["model_id"]
        or any(type(n) is not int or n < 0 for n in (ins, outs))
        or any(usage.get(k, 0) for k in ("cache_read_input_tokens", "cache_creation_input_tokens"))
        or usage.get("service_tier", "standard") != "standard"
        or usage.get("inference_geo", "global") != "global"
        or usage.get("speed", "standard") != "standard"
    ):
        raise AdmissionError("invalid_or_unpriced_usage")
    rates = sealed["settings"]["price_estimate_usd_per_million"]
    cost = (
        Decimal(ins) * _money(rates["input"]) + Decimal(outs) * _money(rates["output"])
    ) / 1_000_000
    return ins, outs, cost


def settle_failed_response(
    store: WorkspaceStore,
    owner: str,
    job_id: str,
    *,
    receipt_id: str,
    expected_contacts_digest: str | None = None,
    reason: str = "content_rejected",
) -> dict[str, Any]:
    """Close known completed usage, never accept content or replay the job.

    All contacts must have complete durable responses. Existing known charges
    may not decrease. A receipt binds the original journal and historical rates,
    not today's model/prices. A repeated identical audit is a no-op.
    """
    if not receipt_id.strip() or len(receipt_id) > 120:
        raise AdmissionError("receipt_required")
    control = GenerationAdmission(store)
    with store.pool.connection() as conn:
        control._lock(conn, owner)
        state, input_digest, data = control._job(conn, owner, job_id)
        if _digest(data["sealed_input"]) != input_digest:
            raise AdmissionError("accounting_sealed_input_drift")
        contacts = data.get("adapter", {}).get("contacts", [])
        digest = _digest(contacts)
        if expected_contacts_digest is not None and expected_contacts_digest != digest:
            raise AdmissionError("accounting_journal_drift")
        audits = data.setdefault("accounting_audits", {})
        if receipt_id in audits:
            if audits[receipt_id]["contacts_digest"] != digest:
                raise AdmissionError("accounting_journal_drift")
            return dict(audits[receipt_id])
        if state not in {"running", "uncertain", "failed", "cancelled", "budget_stopped"}:
            raise AdmissionError("failed_content_reconciliation_required")
        if not contacts or any(c.get("state") != "completed" for c in contacts):
            raise AdmissionError("external_completion_still_uncertain")
        sealed = data["sealed_input"]
        totals = {"workflow": Decimal(0), "checker": Decimal(0)}
        messages = []
        for contact in contacts:
            response = contact.get("response")
            if not isinstance(response, dict):
                raise AdmissionError("complete_response_required")
            if contact["endpoint"] == "messages/count_tokens":
                count = response.get("input_tokens")
                if type(count) is not int or count < 0:
                    raise AdmissionError("invalid_count_response")
                continue
            if contact["endpoint"] != "messages":
                raise AdmissionError("unrecognized_billing_endpoint")
            billing = sealed
            routes = sealed["settings"].get("operation_routes")
            if routes:
                from src.workspace.d5_operations import route

                stage = contact["stage"]
                selected = route(routes, stage)
                body = contact["body"]
                if (
                    body.get("model") != selected["model"]
                    or body.get("thinking") != selected["thinking"]
                    or body.get("max_tokens") != selected["output_tokens"]
                    or body.get("output_config", {}).get("effort") != selected["effort"]
                    or _digest(body) != contact["generation_request_digest"]
                ):
                    raise AdmissionError("accounting_operation_binding_drift")
                billing = {
                    **sealed,
                    "model_id": selected["model"],
                    "settings": {
                        **sealed["settings"],
                        "price_estimate_usd_per_million": selected["prices"],
                    },
                }
            ins, outs, cost = priced_usage(response, billing)
            if not isinstance(response.get("id"), str) or not response["id"].strip():
                raise AdmissionError("provider_receipt_id_required")
            if contact["stage"] not in {"draft", "repair", "check"}:
                raise AdmissionError("unrecognized_usage_role")
            role = "checker" if contact["stage"] == "check" else "workflow"
            if data["adapter"]["mode"] == "provider":
                totals[role] += cost
            messages.append(
                {
                    "id": response["id"],
                    "response_digest": _digest(response),
                    "input_tokens": ins,
                    "output_tokens": outs,
                    "role": role,
                }
            )
        if len({m["id"] for m in messages}) != len(messages):
            raise AdmissionError("unique_completed_message_receipts_required")
        reservation = conn.execute(
            "SELECT amount,workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s FOR UPDATE",
            (job_id,),
        ).fetchone()
        if reservation is None:
            raise AdmissionError("reservation_missing")
        amount, workflow, checker, unknown = reservation
        if totals["workflow"] < workflow or totals["checker"] < checker:
            raise AdmissionError("known_spend_cannot_decrease")
        now = datetime.now(UTC)
        data["usage_events"].append(
            {
                "day": now.date().isoformat(),
                "month": now.date().replace(day=1).isoformat(),
                "workflow": str(totals["workflow"] - workflow),
                "judge": str(totals["checker"] - checker),
            }
        )
        next_state = (
            "budget_stopped"
            if sum(totals.values()) > amount
            else (state if state in {"cancelled", "budget_stopped"} else "failed")
        )
        audit = {
            "receipt_id": receipt_id,
            "contacts_digest": digest,
            "reason": reason,
            "recorded_at": now.isoformat(),
            "historical_rates": sealed["settings"]["price_estimate_usd_per_million"],
            "messages": messages,
            "prior_state": state,
            "state": next_state,
            "prior_unknown_usd": str(unknown),
            "unknown_usd": "0",
            "released_unused_usd": str(max(Decimal(0), amount - sum(totals.values()))),
            "workflow_usd": str(totals["workflow"]),
            "checker_usd": str(totals["checker"]),
            "content_accepted": False,
            "invoice_verified": False,
        }
        audit["financial_basis"] = (
            "completed metered Messages responses"
            if messages
            else "completed valid count-only contacts; no Messages dispatch"
        )
        audits[receipt_id] = audit
        data["result"] = None
        data["adapter"].update(
            workflow_usd=str(totals["workflow"]), checker_usd=str(totals["checker"])
        )
        conn.execute(
            "UPDATE workspace_generation_jobs SET state=%s,data=%s WHERE id=%s",
            (next_state, Jsonb(data), job_id),
        )
        conn.execute(
            "UPDATE workspace_spend_reservations SET workflow=%s,judge=%s,unknown=0,state=%s WHERE job_id=%s",
            (totals["workflow"], totals["checker"], next_state, job_id),
        )
        return audit
