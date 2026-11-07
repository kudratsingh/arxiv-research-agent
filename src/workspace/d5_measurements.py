"""Read-only reuse of completed count receipts; never a count or approval writer.

Only byte-for-byte equal structured request bodies and identical model/settings,
source selection and output allowances can reuse a historical estimate. The
original job/authorization/receipt identities remain historical, never retagged.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.workspace.admission import AdmissionError, GenerationInput, _digest
from src.workspace.d5_adapter import D5MeasurementAdapter
from src.workspace.store import WorkspaceStore

REVISION = "d5-explicit-measurement-link-v1"
SETTINGS = (
    "input_tokens",
    "output_tokens",
    "timeout_seconds",
    "response_bytes",
    "max_calls",
    "max_repairs",
    "price_estimate_usd_per_million",
    "selection",
)


def binding(inputs: dict[str, Any], candidate_digest: str) -> dict[str, Any]:
    settings = inputs["settings"]
    sealed = settings["d5_request"]
    return {
        "model": inputs["model_id"],
        "prompt_revision": inputs["prompt_revision"],
        "candidate_wire_digest": candidate_digest,
        "settings": {k: settings[k] for k in SETTINGS},
        "sealed_settings": sealed["settings"],
        "sources": inputs["sources"],
        "units_digest": _digest(sealed["units"]),
        "version_hashes": sealed["version_hashes"],
        "schema_digest": sealed["response_schemas_digest"],
    }


def _historical(
    store: WorkspaceStore, link: dict[str, Any], *, offline: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT owner,state,input_digest,data FROM workspace_generation_jobs WHERE id=%s",
            (link["job_id"],),
        ).fetchone()
    if not row or row[:2] != (link["owner"], "ready"):
        raise AdmissionError("d5_linked_measurement_not_completed")
    _, _, fingerprint, data = row
    inputs = data["sealed_input"]
    adapter = data.get("adapter", {})
    contacts = adapter.get("contacts", [])
    authorization = link["authorization_record"]
    if (
        link.get("revision") != REVISION
        or _digest(inputs) != fingerprint
        or fingerprint != link["input_digest"]
        or inputs["settings"].get("d5_operation") != "measurement"
        or inputs["settings"].get("d5_packet_digest") != link["packet_digest"]
        or inputs["settings"].get("d5_request_id") != link["request_id"]
        or authorization.get("approved") is not True
        or authorization.get("packet_digest") != link["packet_digest"]
        or authorization.get("stages") != ["A"]
        or data.get("d5_authorization_chain") != [_digest(authorization)]
        or adapter.get("mode") not in ({"mock", "provider"} if offline else {"provider"})
        or authorization.get("transport_mode") != adapter.get("mode")
        or authorization.get("authorization_kind")
        != ("offline_fixture" if adapter.get("mode") == "mock" else "owner")
        or len(contacts) != 1
        or contacts[0].get("endpoint") != "messages/count_tokens"
        or contacts[0].get("state") != "completed"
        or contacts[0].get("ordinal") != 0
    ):
        raise AdmissionError("d5_measurement_receipt_or_authorization_drift")
    contact = contacts[0]
    result = data.get("result") or {}
    count = contact.get("response", {}).get("input_tokens")
    if (
        type(count) is not int
        or count < 0
        or result.get("measurement_only") is not True
        or count != result.get("input_tokens")
        or _digest(contact) != link["contact_receipt_digest"]
        or _digest(contact["response"]) != link["response_digest"]
        or _digest(contact["body"]) != contact["request_digest"]
        or result.get("count_request_digest") != contact["request_digest"]
        or link["count_request_digest"] != contact["request_digest"]
        or link["input_tokens"] != count
        or binding(inputs, contact["generation_request_digest"]) != link["binding"]
    ):
        raise AdmissionError("d5_measurement_contact_binding_drift")
    return inputs, contact


def make_link(store: WorkspaceStore, job_id: str, authorization: dict[str, Any]) -> dict[str, Any]:
    """Export a historical receipt reference only; does not approve any reuse."""
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT owner,state,input_digest,data FROM workspace_generation_jobs WHERE id=%s",
            (job_id,),
        ).fetchone()
    if not row or row[1] != "ready":
        raise AdmissionError("d5_linked_measurement_not_completed")
    owner, _, fingerprint, data = row
    inputs = data["sealed_input"]
    contacts = data.get("adapter", {}).get("contacts", [])
    if len(contacts) != 1:
        raise AdmissionError("d5_measurement_receipt_or_authorization_drift")
    c = contacts[0]
    link = {
        "revision": REVISION,
        "job_id": job_id,
        "owner": owner,
        "input_digest": fingerprint,
        "packet_digest": inputs["settings"]["d5_packet_digest"],
        "request_id": inputs["settings"]["d5_request_id"],
        "authorization_record": authorization,
        "count_request_digest": c["request_digest"],
        "response_digest": _digest(c["response"]),
        "contact_receipt_digest": _digest(c),
        "input_tokens": c["response"]["input_tokens"],
        "binding": binding(inputs, c["generation_request_digest"]),
    }
    _historical(store, link, offline=True)
    return link


def verify_reuse(
    store: WorkspaceStore,
    link: dict[str, Any],
    owner: str,
    inputs: GenerationInput,
    *,
    offline: bool,
) -> dict[str, Any]:
    """Source checks and wire rebuilding use a transport that cannot dispatch."""
    try:
        _, old_contact = _historical(store, link, offline=offline)

        def forbidden(request: httpx.Request) -> httpx.Response:
            raise AssertionError("Measurement reuse must never make an HTTP request")

        wire = D5MeasurementAdapter(
            store, owner, inputs, transport=httpx.MockTransport(forbidden)
        ).request()
        count_body = {
            k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}
        }
        if (
            count_body != old_contact["body"]
            or _digest(count_body) != link["count_request_digest"]
            or binding(inputs.snapshot(), wire["request_digest"]) != link["binding"]
        ):
            raise AdmissionError(
                "d5_measurement_request_model_or_settings_changed_fresh_count_required"
            )
        if link["input_tokens"] > int(inputs.settings["input_tokens"]) // 5 * 4:
            raise AdmissionError("d5_linked_measurement_exceeds_allowance")
    except (KeyError, TypeError, IndexError) as exc:
        raise AdmissionError("d5_measurement_link_malformed") from exc
    return {
        "historical_job_id": link["job_id"],
        "historical_packet_digest": link["packet_digest"],
        "historical_contact_receipt_digest": link["contact_receipt_digest"],
        "count_request_digest": link["count_request_digest"],
        "input_tokens": link["input_tokens"],
        "measured_allowance": 16000,
        "reused": True,
        "new_contacts": 0,
    }


def assess_reuse(
    store: WorkspaceStore, links: dict[str, Any], compiled: dict[str, Any], *, offline: bool
) -> dict[str, Any]:
    """Plan only necessary fresh counts; corrupt receipts/source drift stop planning."""
    from src.workspace.d5_freeze import restore_input

    reused = {}
    fresh = []
    for key, entry in compiled.items():
        if entry["stage"] != "A":
            continue
        if key not in links:
            fresh.append(key)
            continue
        try:
            verify_reuse(
                store, links[key], entry["owner"], restore_input(entry["input"]), offline=offline
            )
        except AdmissionError as exc:
            if str(exc) != "d5_measurement_request_model_or_settings_changed_fresh_count_required":
                raise
            fresh.append(key)
        else:
            reused[key] = links[key]
    return {"measurement_reuse": reused, "fresh_measurement_cases": fresh}
