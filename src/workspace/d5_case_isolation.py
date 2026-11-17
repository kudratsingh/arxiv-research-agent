"""Prospective progression for fully settled v20 evaluation failures."""

from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import io
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import httpx
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from src.workspace.admission import AdmissionError, _digest, _money
from src.workspace.d5_campaign_v19_policy import development_contract, require_development_contracts
from src.workspace.d5_deadlines import remaining
from src.workspace.d5_operations import route, verdict_text
from src.workspace.d5_report_binding import ReportBindingError, json_object
from src.workspace.d5_scope import guard_scope
from src.workspace.grounding import SupportCheck, validate_claims
from src.workspace.qualification_accounting import priced_usage

if TYPE_CHECKING:
    from src.workspace.d5_adapter import D5Adapter

REVISION = "d5-behavior-continuation-v20"
SEMANTIC_CODES = frozenset({"answered_requires_complete_answer_without_gaps"})
QUALITY_CODES = frozenset(
    {
        "d5_request_or_claim_quality_unresolved",
        "d5_whole_claim_support_unresolved",
        "d5_unscored_factual_prose",
    }
)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise AdmissionError(reason)


def require_progression(
    conn: Any, scope_id: str, packet_digest: str, case_id: str, entry: dict[str, Any]
) -> None:
    """Require the prospectively authorized protocol and both development contracts."""
    row = conn.execute(
        "SELECT state,packet_digest,data FROM workspace_d5_scopes WHERE scope_id=%s",
        (scope_id,),
    ).fetchone()
    settings = entry["input"]["settings"]
    if (
        not row
        or row[0] != "active"
        or row[1] != packet_digest
        or row[2].get("authorization_record", {}).get("campaign_revision") != REVISION
        or settings.get("d5_campaign_revision") != REVISION
        or settings.get("d5_case_id") != case_id
        or settings.get("d5_scope_id") != scope_id
        or settings.get("d5_packet_digest") != packet_digest
        or row[2]["cases"].get(case_id, {}).get("stage") != entry["stage"]
    ):
        raise AdmissionError("campaign_v20_progression_authorization_binding_drift")
    if entry["stage"] != "B":
        require_development_contracts(conn, {**row[2], "id": scope_id})
    if conn.execute(
        "SELECT 1 FROM workspace_d5_campaign_outcomes o "
        "LEFT JOIN workspace_spend_reservations r ON r.job_id=o.job_id "
        "WHERE o.scope_id=%s AND o.record->>'state'='failed' "
        "AND (r.state IS DISTINCT FROM 'failed' OR r.unknown IS DISTINCT FROM 0 "
        "OR o.record->'content_rejection'->>'classification' IS NULL) LIMIT 1",
        (scope_id,),
    ).fetchone():
        raise AdmissionError("campaign_v20_prior_failed_accounting_receipt_drift")


def _semantic_code(error: BaseException) -> str | None:
    if type(error) is ValidationError:
        errors = error.errors()
        if len(errors) == 1 and errors[0]["type"] == "value_error" and not errors[0]["loc"]:
            cause = errors[0].get("ctx", {}).get("error")
            if (
                type(cause) is ValueError
                and len(cause.args) == 1
                and isinstance(cause.args[0], str)
                and cause.args[0] in SEMANTIC_CODES
            ):
                return str(cause.args[0])
    return None


def _quality_code(error: BaseException) -> str | None:
    if (
        type(error) is AdmissionError
        and len(error.args) == 1
        and isinstance(error.args[0], str)
        and error.args[0] in QUALITY_CODES
    ):
        return error.args[0]
    return None


def eligible_error(error: BaseException | None) -> bool:
    """Permit only a typed candidate to reach the adapter's preliminary receipt."""
    return error is not None and bool(_semantic_code(error) or _quality_code(error))


def _complete_body(contact: dict[str, Any], maximum: int) -> None:
    receipt = contact["http_body_receipt"]
    size = receipt["received_bytes"]
    _require(
        type(size) is int
        and 0 < size <= maximum
        and receipt["http_status"] == 200
        and receipt["complete_body"] is True
        and receipt["credential_redacted"] is False
        and "partial_response" not in contact,
        "campaign_v20_complete_http_200_receipt_required",
    )
    compressed = base64.b64decode(receipt["body_gzip_base64"], validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(size + 1)
    _require(
        len(raw) == size
        and hashlib.sha256(raw).hexdigest() == receipt["received_sha256"]
        and json_object(raw.decode("utf-8")) == contact["response"],
        "campaign_v20_response_body_receipt_drift",
    )


def _contact_accounting(
    adapter: D5Adapter, data: dict[str, Any], reservation: tuple[Any, ...]
) -> dict[str, Any]:
    """Reprice paired, complete receipts and match the durable failed settlement."""
    from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

    settings = adapter.inputs.settings
    snapshot = data["adapter"]
    contacts = snapshot["contacts"]
    _require(
        snapshot["mode"] == adapter.mode
        and 2 <= len(contacts) <= 8
        and len(contacts) % 2 == 0
        and all(
            type(c["ordinal"]) is int and c["ordinal"] == i and c["state"] == "completed"
            for i, c in enumerate(contacts)
        ),
        "campaign_v20_complete_contact_journal_required",
    )
    totals = {"workflow": Decimal(0), "checker": Decimal(0)}
    receipts = {}
    audit_messages = []
    for index, (count, message) in enumerate(zip(contacts[::2], contacts[1::2], strict=True)):
        stage = ("draft", "check", "repair", "check")[index]
        body = message["body"]
        digest = _digest(body)
        estimate = count["response"]["input_tokens"]
        selected = route(settings["operation_routes"], stage)
        _require(
            count["endpoint"] == "messages/count_tokens"
            and message["endpoint"] == "messages"
            and count["stage"] == message["stage"] == stage
            and count["request_digest"] == _digest(count["body"])
            and count["generation_request_digest"]
            == message["generation_request_digest"]
            == message["request_digest"]
            == digest
            and count["body"]
            == {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
            and type(estimate) is int
            and 0 <= estimate * 5 <= int(settings["input_tokens"]) * 4
            and body["model"] == selected["model"]
            and body["max_tokens"] == selected["output_tokens"]
            and body["thinking"] == selected["thinking"]
            and body["output_config"]["effort"] == selected["effort"],
            "campaign_v20_paired_request_or_model_binding_drift",
        )
        for contact in (count, message):
            _complete_body(contact, int(settings["response_bytes"]))
        response = message["response"]
        _require(response["stop_reason"] == "end_turn", "campaign_v20_end_turn_required")
        text = (
            verdict_text(response)
            if body["model"] == "claude-opus-5-5"
            else response["content"][0]["text"]
        )
        payload = json_object(text)
        _require(
            adapter._response_output(response, body) is not None
            and Draft202012Validator(body["output_config"]["format"]["schema"]).is_valid(payload),
            "campaign_v20_wire_valid_response_required",
        )
        wire = {"stage": stage, "body": body}
        ins, outs, cost = priced_usage(response, adapter._billing_input(wire))
        _require(adapter._usage_within_stage(ins, outs, wire), "usage_cap_exceeded")
        role = "checker" if stage == "check" else "workflow"
        if adapter.mode == "provider":
            totals[role] += cost
        receipts[f"contact-{message['ordinal']}"] = _digest(
            {
                "workflow": str(totals["workflow"]),
                "judge": str(totals["checker"]),
                "unknown": "0",
                "final": False,
                "result": None,
            }
        )
        audit_messages.append(
            {
                "id": response["id"],
                "response_digest": _digest(response),
                "input_tokens": ins,
                "output_tokens": outs,
                "role": role,
            }
        )
    amount, workflow, checker, unknown, state = reservation
    audit: dict[str, Any] = data["accounting_audits"]["completed-failure"]
    events = data["usage_events"]
    _require(
        state == "failed"
        and unknown == 0
        and workflow == totals["workflow"] == _money(snapshot["workflow_usd"])
        and checker == totals["checker"] == _money(snapshot["checker_usd"])
        and workflow == sum(_money(e["workflow"]) for e in events)
        and checker == sum(_money(e["judge"]) for e in events)
        and workflow + checker <= amount
        and data["receipts"] == receipts
        and audit["contacts_digest"] == _digest(contacts)
        and audit["messages"] == audit_messages
        and len({m["id"] for m in audit_messages}) == len(audit_messages)
        and all(isinstance(m["id"], str) and m["id"].strip() for m in audit_messages)
        and audit["historical_rates"] == settings["price_estimate_usd_per_million"]
        and audit["state"] == "failed"
        and audit["content_accepted"] is False
        and _money(audit["unknown_usd"]) == 0
        and _money(audit["workflow_usd"]) == workflow
        and _money(audit["checker_usd"]) == checker
        and _money(audit["released_unused_usd"]) == amount - workflow - checker,
        "campaign_v20_failed_accounting_receipt_drift",
    )
    return audit


def _replay_quality_rejection(adapter: D5Adapter, snapshot: dict[str, Any], code: str) -> None:
    steps = snapshot["steps"]
    checked = {"steps": steps[:-1]}
    current = steps[-1]
    output = {k: v for k, v in current["output"].items() if k != "grounding"}
    verdict = adapter._checks(output)
    _, materials = adapter._context()
    draft = adapter._checked_draft(checked)
    grounding = validate_claims(
        draft.claims,
        materials,
        tuple(
            SupportCheck(
                check.claim_id,
                check.input_digest,
                check.decision,
                current["model_id"],
                adapter.revision + ":check",
                check.reason,
            )
            for check in verdict.checks
        ),
    )
    try:
        adapter._review_complete(grounding, checked, verdict)
    except AdmissionError as replay:
        _require(replay.args == (code,), "campaign_v20_quality_replay_mismatch")
    else:
        raise AdmissionError("campaign_v20_quality_replay_mismatch")


def preserve_failed_case(
    adapter: D5Adapter,
    job_id: str,
    entry: dict[str, Any],
    error: BaseException,
) -> bool:
    """Promote an exact failed receipt to an immutable v20 outcome input."""
    semantic = _semantic_code(error)
    quality = _quality_code(error)
    stage = entry["stage"]
    if not ((stage == "C" and semantic) or (stage in {"B", "C"} and quality)):
        return False

    sealed = adapter.inputs.snapshot()
    settings = sealed["settings"]
    scope_id, case_id = settings["d5_scope_id"], settings["d5_case_id"]
    initial = (
        adapter.request()
    )  # Rebuild the authorized first request from current input and sources.
    with adapter.store.pool.connection() as conn:
        adapter.control._lock(conn, adapter.owner)
        state, input_digest, data = adapter.control._job(conn, adapter.owner, job_id)
        _, policy = adapter.control._policy(conn, adapter.owner, sealed, datetime.now(UTC))
        adapter.control._sources(conn, adapter.owner, sealed)
        bound = guard_scope(conn, adapter.owner, sealed, policy, job_id=job_id)
        remaining(data)
        authorization_chain = list(
            dict.fromkeys((bound["authorization_digest"], bound["stage_authorizations"][stage]))
        )
        receipt = data.get("campaign_content_rejection", {})
        snapshot = data["adapter"]
        contacts = snapshot["contacts"]
        reservation = conn.execute(
            "SELECT amount,workflow,judge,unknown,state FROM workspace_spend_reservations "
            "WHERE job_id=%s AND owner=%s FOR UPDATE",
            (job_id, adapter.owner),
        ).fetchone()
        run = conn.execute(
            "SELECT input_digest,job_id FROM workspace_d5_case_runs WHERE scope_id=%s AND case_id=%s",
            (scope_id, case_id),
        ).fetchone()
        _require(
            state == "failed"
            and settings.get("d5_campaign_revision") == REVISION
            and bound["authorization_record"].get("campaign_revision") == REVISION
            and bound["case"]["stage"] == stage
            and settings["d5_operation"] == "workflow"
            and data["result"] is None
            and data["policy_digest"] == _digest(policy)
            and data["d5_authorization_chain"] == authorization_chain
            and data["sealed_input"] == sealed == entry["input"]
            and run == (input_digest, job_id)
            and input_digest == _digest(sealed)
            and receipt.get("input_digest") == input_digest
            and receipt.get("contacts_digest") == _digest(contacts)
            and receipt.get("error_class") == type(error).__name__
            and receipt.get("accepted") is False,
            "campaign_v20_failed_case_binding_drift",
        )
        _require(
            len(contacts) >= 2 and contacts[1]["body"] == initial["body"],
            "campaign_v20_initial_request_binding_drift",
        )
        if reservation is None:
            raise AdmissionError("campaign_v20_failed_case_reservation_missing")
        audit = _contact_accounting(adapter, data, reservation)
        if semantic:
            _require(
                len(contacts) == 2
                and snapshot["steps"] == []
                and receipt.get("error_codes") == [semantic],
                "campaign_v20_first_draft_failure_required",
            )
            output = adapter._response_output(contacts[1]["response"], contacts[1]["body"])
            try:
                adapter._draft(output)
            except ValidationError as replay:
                _require(
                    _semantic_code(replay) == semantic, "campaign_v20_semantic_replay_mismatch"
                )
            else:
                raise AdmissionError("campaign_v20_semantic_replay_mismatch")
            classification = "isolated_evaluation_first_draft_semantic_failure"
        elif quality:
            # This validates the latest complete checker against the actual draft/repair.
            development_contract(conn, scope_id, case_id)
            _require(receipt.get("error") == quality, "campaign_v20_quality_rejection_drift")
            _replay_quality_rejection(adapter, snapshot, quality)
            classification = "complete_negative_quality_verdict"
        else:
            raise AdmissionError("campaign_v20_failure_classification_missing")
        data["campaign_content_rejection"] = {
            **receipt,
            "case_id": case_id,
            "stage": stage,
            "local_stage": "recheck" if len(contacts) == 8 else contacts[-1]["stage"],
            "classification": classification,
            "reason_code": semantic or str(error),
            "failed_accounting_digest": _digest(audit),
        }
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s AND owner=%s",
            (Jsonb(data), job_id, adapter.owner),
        )
    return True


def stop_details(
    error: BaseException, stage: str, local_stage: str, last_contact: Any
) -> dict[str, Any]:
    response = last_contact.get("response") if isinstance(last_contact, dict) else None
    stop_reason = response.get("stop_reason") if isinstance(response, dict) else None
    classification, code = "unexpected_exception", type(error).__name__
    if isinstance(error, asyncio.CancelledError) or (
        isinstance(error, AdmissionError) and error.args == ("campaign_cancelled_no_dispatch",)
    ):
        classification, code = "cancellation", "campaign_cancelled"
    elif isinstance(error, httpx.HTTPStatusError):
        classification, code = "provider_http_error", f"http_{error.response.status_code}"
    elif isinstance(error, (TimeoutError, httpx.RequestError)):
        classification, code = "unknown_provider_completion", type(error).__name__
    elif stop_reason == "max_tokens":
        classification, code = "output_capacity_failure", "max_tokens"
    elif isinstance(error, ValidationError):
        classification, code = (
            "response_contract_failure",
            _semantic_code(error) or "validation_error",
        )
    elif isinstance(error, (json.JSONDecodeError, ReportBindingError)):
        classification, code = "response_contract_failure", type(error).__name__
    elif isinstance(error, AdmissionError):
        code = str(error)
        classification = {
            "input_measurement_exceeds_cap_or_invalid": "input_capacity_or_invalid_count",
            "usage_cap_exceeded": "usage_capacity_failure",
            "invalid_or_unpriced_usage": "usage_or_model_binding_failure",
            "campaign_development_contract_incomplete": "development_contract_failure",
            "campaign_accounting_or_outcome_corruption": "accounting_corruption",
            "campaign_v20_prior_failed_accounting_receipt_drift": "accounting_corruption",
        }.get(code, "admission_or_contract_failure")
    return {
        "stage": stage,
        "local_stage": local_stage,
        "classification": classification,
        "reason_code": code,
    }
