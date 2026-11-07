"""Owner-scoped read model for quarantined results, no provider construction.

Historical completed results retain their question/producer. Source drift hides
claims rather than silently using a newer material or regenerating the result.
"""

from __future__ import annotations

from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_contract import resolve_draft
from src.workspace.d5_adapter import ADAPTER_REVISION
from src.workspace.executor import FakeExecutor
from src.workspace.grounding import EvidenceRef, validate_claims
from src.workspace.store import WorkspaceStore


class QualificationResults:
    def __init__(self, store: WorkspaceStore):
        self.store = store

    def snapshot(self, owner: str, job_id: str) -> dict[str, Any]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            row = conn.execute(
                "SELECT state,input_digest,data FROM workspace_generation_jobs WHERE owner=%s AND id=%s",
                (owner, job_id),
            ).fetchone()
            if not row or row[2]["sealed_input"]["prompt_revision"] != ADAPTER_REVISION:
                raise AdmissionError("d5_qualification_result_unavailable")
            state, fingerprint, data = row
            inputs = data["sealed_input"]
            sealed = inputs["settings"]["d5_request"]
            reservation = conn.execute(
                "SELECT workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s",
                (job_id,),
            ).fetchone()
            if reservation is None:
                raise AdmissionError("d5_reservation_receipt_missing")
            adapter = data.get("adapter", {})
            output = None
            intact = True
            claims = []
            if data.get("result") and inputs["settings"]["d5_operation"] == "workflow":
                try:
                    materials = tuple(
                        FakeExecutor(self.store)._sources(conn, owner, [s["material_id"]])[0]
                        for s in inputs["sources"]
                    )
                    workflow = [
                        s for s in adapter.get("steps", []) if s["stage"] in {"draft", "repair"}
                    ][-1]
                    output = {k: v for k, v in workflow["output"].items() if k != "grounding"}
                    _, resolved = resolve_draft(
                        output,
                        {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
                        materials,
                        purpose=sealed.get("response_purpose", "research_comparison"),
                        revision=sealed["schema_revision"],
                    )
                    report = validate_claims(resolved, materials)
                    intact = _digest(inputs) == fingerprint and all(
                        c.identity_resolved for c in report.assessments
                    )
                    for vid, expected in sealed["version_hashes"].items():
                        version = conn.execute(
                            "SELECT data->>'content_hash' FROM workspace_versions WHERE version_id=%s",
                            (vid,),
                        ).fetchone()
                        intact = intact and version is not None and version[0] == expected
                    from dataclasses import asdict

                    claims = [asdict(c) for c in resolved] if intact else []
                except (ValueError, KeyError, IndexError, TypeError):
                    intact = False
                if not intact:
                    output = None
            return {
                "id": job_id,
                "state": state if intact else "stale",
                **adapter,
                "result": data.get("result") if intact else None,
                "assistance_output": output,
                "resolved_claims": claims,
                "request": sealed,
                "operation": inputs["settings"]["d5_operation"],
                "packet_digest": inputs["settings"]["d5_packet_digest"],
                "case_id": inputs["settings"]["d5_case_id"],
                "producer": inputs["settings"]["qualification_producer"],
                "simulated": adapter.get("mode") == "mock",
                "quarantined": True,
                "human_review": None,
                "factual_acceptance": False,
                "checker_qualified": False,
                "source_binding_intact": intact,
                "everyday_generation": False,
                "workflow_usd": str(reservation[0]),
                "checker_usd": str(reservation[1]),
                "unknown_usd": str(reservation[2]),
                "latency_seconds": data.get("d5_elapsed_seconds"),
                "accounting_audits": data.get("accounting_audits", {}),
                "authorization_chain": data.get("d5_authorization_chain", []),
            }

    def jobs(self, owner: str, work: str, version: str) -> list[dict[str, Any]]:
        self.store._owner(owner)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM workspace_generation_jobs WHERE owner=%s AND data->'sealed_input'->>'prompt_revision'=%s AND data->'sealed_input'->'settings'->>'d5_operation'='workflow' AND data->'sealed_input'->'settings'->'d5_request'->'assistance'->>'work_id'=%s AND data->'sealed_input'->'settings'->'d5_request'->'assistance'->>'version_id'=%s ORDER BY id LIMIT 20",
                (owner, ADAPTER_REVISION, work, version),
            ).fetchall()
        return [self.snapshot(owner, row[0]) for row in rows]
