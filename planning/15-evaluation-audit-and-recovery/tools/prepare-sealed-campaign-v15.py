"""Prepare an unapproved packet from a preserved census in disposable storage.

Run from the worktree root with python - < this-file --arguments. No real
credential, authorization, contact, live migration or accounting mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path

import src
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_campaign_operator import template
from src.workspace.d5_campaign_v15_packet import freeze
from src.workspace.d5_capacity_policy import POLICY, monetary_envelope
from src.workspace.d5_fixture import install
from src.workspace.d5_freeze import compile_inputs, verify
from tests.d5_campaign_gate import storage

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--snapshot", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
if Path.cwd() != Path(src.__file__).resolve().parents[1] or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled" or os.environ.get("WORKSPACE_D5_OFFLINE") != "1":
    raise AdmissionError("packet_prepare_worktree_disabled_key_required")
if args.out.exists():
    raise AdmissionError("choose_new_immutable_packet_directory")
captured = read(args.snapshot)
with storage() as store:
    install(store, captured, fixture=True)
    packet = freeze(store, captured)
    verify(packet)
    compiled = compile_inputs(packet)
    blank = template(packet)
assert blank["approved"] is False and all(blank[k] is False for k in ("capacity_amendment_approved", "budget_adjustment_approved", "expiry_adjustment_approved", "historical_uncertainty_exception_approved"))
write(args.out / "packet.json.gz", packet)
write(args.out / "compiled-inputs.json.gz", compiled)
write(args.out / "AUTHORIZATION-TEMPLATE.json", blank)
write(args.out / "PROPOSAL.json", packet["campaign_extension"])
write(args.out / "ANSWERABILITY.json", packet["answerability"])
write(args.out / "CHECKER-SCHEMAS.json", packet["checker_schemas"])
write(args.out / "ROUTES-AND-LIMITS.json", {k: packet[k] for k in ("limits", "operation_routes", "operation_deadlines", "capacity_policy", "expiry_policy", "progression")})
write(args.out / "IDENTITY.json", {"packet_digest": packet["packet_digest"], "application_commit": packet["application_commit"], "proposal_digest": packet["campaign_extension"]["proposal_digest"], "snapshot_digest": packet["snapshot_digest"], "predecessor_packet": packet["predecessor_packet"], "scope_id": blank["scope_id"], "existing_programme_expiry": packet["programme"]["programme_expires_at"], "approved": False, "provider_contacts": 0, "count_contacts": 0})
index, metrics = [], []
def shape(value):
    if isinstance(value, dict):
        children = [shape(x) for x in value.values()]
        return (1 + sum(x[0] for x in children), int("anyOf" in value) + sum(x[1] for x in children), len(value.get("anyOf", [])) + sum(x[2] for x in children))
    if isinstance(value, list):
        children = [shape(x) for x in value]
        return (sum(x[0] for x in children), sum(x[1] for x in children), sum(x[2] for x in children))
    return (0, 0, 0)
for case in (*packet["cases"], *packet["probes"]):
    settings = compiled[case["id"]]["input"]["settings"]
    body = case.get("wire") or case["sealed"]["candidate_initial_wire"]
    count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
    schema = body["output_config"]["format"]["schema"]
    nodes, branches, alternatives = shape(schema)
    index.append({"case_id": case["id"], "stage": compiled[case["id"]]["stage"], "input_digest": _digest(compiled[case["id"]]["input"]), "initial_request": body, "initial_request_digest": _digest(body), "paired_count_request": count, "paired_count_digest": _digest(count), "model": body["model"], "settings": {k: settings[k] for k in ("operation_routes", "operation_deadlines", "d5_capacity_policy")}, "selected_evidence": case["sealed"]["units"], "future_dynamic_requests": "Exact response-dependent bodies and paired digests are created under frozen templates from actual preceding outputs, never invented here."})
    metrics.append({"case_id": case["id"], "wire_schema_digest": _digest(schema), "compact_utf8_bytes": len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")).encode()), "schema_nodes": nodes, "anyOf_sites": branches, "anyOf_alternatives": alternatives, "provider_acceptance": "UNMEASURED"})
write(args.out / "REQUEST-INDEX.json.gz", {"requests": index, "private_notes_history": "excluded", "provider_measurements": None})
write(args.out / "SCHEMA-METRICS.json", metrics)
known, holds, new, buffer = map(Decimal, ("2.110597", "0.875066", "14", "2"))
write(args.out / "BUDGET.json", {"basis": "Estimated standard token charges; not measured usage or invoice", "model_envelope": monetary_envelope(), "known_usd": str(known), "retained_overlapping_holds_usd": str(holds), "new_scope_cap_usd": str(new), "additional_buffer_usd": str(buffer), "total_with_buffer_usd": str(known + holds + new + buffer), "proposed_cumulative_cap_usd": "20", "remaining_after_buffer_usd": str(Decimal(20) - known - holds - new - buffer), "cumulative_after_maximum_scope": {"jobs": 50, "messages": 114, "counts": 139}, "proposed_programme_caps": packet["campaign_extension"]["core"]["limits"], "activated": False})
write(args.out / "PREPARATION-RECEIPT.json", {"packet_digest": packet["packet_digest"], "snapshot_digest": _digest(captured), "snapshot_file_sha256": hashlib.sha256(args.snapshot.read_bytes()).hexdigest(), "application_commit": packet["application_commit"], "capacity_policy_digest": _digest(POLICY), "external_authorization": False, "real_contacts": 0, "live_ledger_mutations": 0})
print(json.dumps({"packet_digest": packet["packet_digest"], "application_commit": packet["application_commit"], "proposal_digest": packet["campaign_extension"]["proposal_digest"], "scope_id": blank["scope_id"], "approved": False}))
