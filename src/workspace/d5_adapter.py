"""Qualification-only D5 contract over the production guarded provider adapter.

No approval writer, no everyday execution endpoint. MockTransport and provider
execution share context, admission, contact journal, pricing and recovery code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from anthropic import transform_schema
from psycopg.types.json import Jsonb
from pydantic import Field

from src.workspace.admission import (
    AdmissionError,
    GenerationAdmission,
    GenerationInput,
    SourceRef,
    _digest,
)
from src.workspace.assistance import CANDIDATE_MODEL, Checks, build_wire, producer_binding
from src.workspace.assistance_contract import (
    PROCEDURAL_REVISION,
    coherent_units,
    contract_revision,
    render_gaps,
    render_procedures,
    resolve_draft,
    response_purpose,
    schemas,
)
from src.workspace.context_store import WorkspaceContext
from src.workspace.d5_scope import D5Admission, guard_scope
from src.workspace.executor import FakeExecutor
from src.workspace.grounding import (
    ClaimKind,
    EvidenceRef,
    ResearchClaim,
    claim_input_digest,
    validate_claims,
)
from src.workspace.measurement import MeasurementAdapter
from src.workspace.provider_adapter import QualificationAdapter, StudyDraft, response_output
from src.workspace.qualification_accounting import settle_failed_response

ADAPTER_REVISION = "workspace-d5-qualification-v1"


def qualification_producer() -> dict[str, Any]:
    import anthropic
    import httpx
    import pydantic

    root = Path(__file__).resolve().parents[1]
    files = (
        "workspace/d5_adapter.py",
        "workspace/d5_operations.py",
        "workspace/programme_amendments.py",
        "workspace/programme_successors.py",
        "workspace/programme_third_amendment.py",
        "workspace/programme_capacity.py",
        "workspace/migrations/017_programme_capacity_amendments.sql",
        "workspace/migrations/016_programme_third_amendments.sql",
        "workspace/migrations/015_programme_successor_amendments.sql",
        "workspace/d5_measurements.py",
        "workspace/migrations/014_programme_amendments.sql",
        "workspace/d5_scope.py",
        "workspace/d5_authorization.py",
        "workspace/provider_adapter.py",
        "workspace/measurement.py",
        "workspace/admission.py",
        "workspace/qualification_budget.py",
        "workspace/qualification_accounting.py",
        "workspace/d5_freeze.py",
        "workspace/d5_benchmark.py",
        "workspace/d5_scoring.py",
        "workspace/d5_reviews.py",
        "workspace/d5_review_scoring.py",
        "workspace/d5_fixture.py",
        "workspace/d5_results.py",
        "workspace/d5_operator.py",
        "workspace/migrations/012_d5_qualification_scope.sql",
        "workspace/migrations/013_d5_stage_authorizations.sql",
        "llm.py",
        "llm_models.py",
    )
    return {
        "code": {
            name: "sha256:" + hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in files
        },
        "dependencies": {
            "anthropic": anthropic.__version__,
            "httpx": httpx.__version__,
            "pydantic": pydantic.__version__,
        },
    }


_QUALIFICATION_LOADED = qualification_producer()


class D5StudyDraft(StudyDraft):
    abstention: str | None = Field(default=None, max_length=180)


def seal_procedural_request(sealed: dict[str, Any]) -> dict[str, Any]:
    """Prospective schema/prompt binding; never modify a historical request."""
    from copy import deepcopy

    value = deepcopy(sealed)
    value["schema_revision"] = PROCEDURAL_REVISION
    value["response_schemas"] = schemas(
        list(value["units"]), purpose=value["response_purpose"], revision=PROCEDURAL_REVISION
    )
    context = json.loads(value["candidate_initial_wire"]["messages"][0]["content"])
    context["sealed_request"]["schema_revision"] = PROCEDURAL_REVISION
    context["output_schema"] = value["response_schemas"]["wire"]
    value["candidate_initial_wire"] = build_wire(context)
    return value


def prepare_input(
    sealed: dict[str, Any],
    *,
    scope_id: str,
    packet_digest: str,
    case_id: str,
    operation: str = "workflow",
    probe_wire: dict[str, Any] | None = None,
    programme_amendment_digest: str | None = None,
    operation_routes: dict[str, Any] | None = None,
    repair_located_prose: bool = False,
) -> GenerationInput:
    if operation not in {"workflow", "measurement", "probe"}:
        raise AdmissionError("d5_operation_required")
    sources = tuple(
        SourceRef(s["work_id"], s["version_id"], s["material_id"], s["content_hash"], s["scope"])
        for s in sealed["sources"]
    )
    # The packet preserves the full preview. The execution record retains one
    # copy of selected text, not parent spans plus repeated wire/schema copies.
    # This keeps the existing 32k sealed-input bound; no provider cap is raised.
    compact = {
        k: sealed[k]
        for k in (
            "schema_revision",
            "kind",
            "producer",
            "assistance",
            "project_context",
            "units",
            "version_hashes",
            "settings",
            "selection",
            "capacity",
            "private_context",
        )
    }
    compact["sources"] = [
        {k: s[k] for k in ("work_id", "version_id", "material_id", "content_hash", "scope")}
        for s in sealed["sources"]
    ]
    compact["response_schemas_digest"] = _digest(sealed["response_schemas"])
    compact["response_purpose"] = sealed.get("response_purpose", "research_comparison")
    compact["candidate_initial_wire_digest"] = _digest(sealed["candidate_initial_wire"])
    compact["full_preview_digest"] = _digest(sealed)
    probe_context = None
    if probe_wire is not None:
        original = json.loads(probe_wire["messages"][0]["content"])
        probe_context = {k: v for k, v in original.items() if k not in {"draft", "output_schema"}}
        probe_context["claims"] = [
            {
                **{k: v for k, v in claim.items() if k != "evidence"},
                "handles": [
                    next(key for key, value in sealed["units"].items() if value == ref)
                    for ref in claim["evidence"]
                ],
            }
            for claim in original["draft"]["claims"]
        ]
    settings = {
        "qualification_producer": _QUALIFICATION_LOADED,
        "program_amendment_proposal_digest": programme_amendment_digest,
        "d5_scope_id": scope_id,
        "d5_packet_digest": packet_digest,
        "d5_case_id": case_id,
        "d5_request_id": scope_id + "-" + case_id,
        "d5_operation": operation,
        "d5_request": compact,
        "input_tokens": 20000,
        "output_tokens": 1800 if operation == "probe" else 4000,
        "timeout_seconds": 30,
        "response_bytes": 131072,
        "max_calls": 1 if operation in {"probe", "measurement"} else 4,
        "max_repairs": 0 if operation in {"probe", "measurement"} else 1,
        "price_estimate_usd_per_million": {
            "input": "2",
            "output": "10",
            "verified_at": "2026-11-06",
        },
        "selection": sealed["selection"],
        "research_task": sealed["assistance"]["follow_up"],
        "probe_context": probe_context,
        "probe_wire_digest": _digest(probe_wire) if probe_wire else None,
    }
    if repair_located_prose or sealed["schema_revision"] == PROCEDURAL_REVISION:
        settings["located_prose_repair"] = "first-check-only-v1"
    model = CANDIDATE_MODEL
    if operation_routes is not None and operation != "measurement":
        from src.workspace.d5_operations import route, validate

        validate(operation_routes)
        settings["operation_routes"] = operation_routes
        if operation == "probe":
            selected = route(operation_routes, "check")
            model = selected["model"]
            settings["output_tokens"] = selected["output_tokens"]
            settings["price_estimate_usd_per_million"] = selected["prices"]
    return GenerationInput("deep_dive", model, ADAPTER_REVISION, sources, settings)


class D5Adapter(QualificationAdapter):
    admission_type: type[GenerationAdmission] = D5Admission
    revision = ADAPTER_REVISION
    abstention_is_final = False

    def start(
        self, request_id: str, amount_usd: str | None = None, *, now: datetime | None = None
    ) -> dict[str, Any]:
        if self.inputs.settings["d5_operation"] != "workflow":
            raise AdmissionError("d5_workflow_operation_required")
        amount = amount_usd or ("0.45" if self.inputs.settings.get("operation_routes") else "0.40")
        return super().start(request_id, amount, now=now)

    def _complete_http_body(self, job_id: str, ordinal: int, status: int, body: bytes) -> None:
        # Credential headers never enter the journal. If an upstream error echoes
        # one, redact that value before preserving the bounded complete body.
        text = body.decode("utf-8", errors="replace").replace(self.api_key, "[credential redacted]")
        self._record(
            job_id,
            ordinal,
            {
                "http_status": status,
                "complete_body": True,
                "raw_body": text,
                "body_digest": hashlib.sha256(body).hexdigest(),
                "usage_validated": False,
            },
        )

    def _quarantine_failure(self, job_id: str, reason: str) -> None:
        snapshot = self.snapshot(job_id)
        contacts = snapshot.get("contacts", [])
        # No Messages dispatch and all count replies are known: do not invent a
        # paid unknown hold just because content/admission was refused.
        known_no_messages = not contacts or all(
            c.get("endpoint") == "messages/count_tokens" and c.get("state") == "completed"
            for c in contacts
        )
        if known_no_messages:
            with self.store.pool.connection() as conn:
                self.control._lock(conn, self.owner)
                state, _, data = self.control._job(conn, self.owner, job_id)
                reservation = conn.execute(
                    "SELECT workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s FOR UPDATE",
                    (job_id,),
                ).fetchone()
                if reservation and reservation[0] == reservation[1] == 0:
                    next_state = "cancelled" if state == "cancelled" else "failed"
                    data["result"] = None
                    data.setdefault("accounting_audits", {})["d5-no-messages"] = {
                        "content_accepted": False,
                        "reason": reason,
                        "contacts_digest": _digest(contacts),
                        "financial_basis": "No Messages dispatch; completed count-only or pre-dispatch refusal",
                        "prior_unknown_usd": str(reservation[2]),
                        "unknown_usd": "0",
                    }
                    conn.execute(
                        "UPDATE workspace_generation_jobs SET state=%s,data=%s WHERE id=%s",
                        (next_state, Jsonb(data), job_id),
                    )
                    conn.execute(
                        "UPDATE workspace_spend_reservations SET unknown=0,state=%s WHERE job_id=%s",
                        (next_state, job_id),
                    )
        else:
            try:
                settle_failed_response(
                    self.store, self.owner, job_id, receipt_id="d5-contract-stop", reason=reason
                )
            except (AdmissionError, KeyError, TypeError, ValueError):
                self.control.recover(self.owner, job_id)
        with self.store.pool.connection() as conn:
            conn.execute(
                "UPDATE workspace_d5_scopes SET state='stopped',data=jsonb_set(data,'{stop_reason}',%s)WHERE scope_id=%s AND state='active'",
                (Jsonb(reason), self.inputs.settings["d5_scope_id"]),
            )

    async def advance(self, job_id: str, *, cancelled: Any = lambda: False) -> dict[str, Any]:
        try:
            return await QualificationAdapter.advance(self, job_id, cancelled=cancelled)
        except BaseException as exc:
            self._quarantine_failure(job_id, type(exc).__name__)
            raise

    def _context(self) -> tuple[list[dict[str, Any]], Any]:
        settings = self.inputs.settings
        sealed = settings.get("d5_request", {})
        operation = settings.get("d5_operation")
        routes = settings.get("operation_routes")
        if routes:
            from src.workspace.d5_operations import route, validate

            validate(routes)
        probe_route = route(routes, "check") if routes and operation == "probe" else None
        if (
            qualification_producer() != _QUALIFICATION_LOADED
            or settings.get("qualification_producer") != _QUALIFICATION_LOADED
            or self.inputs.model_id != (probe_route["model"] if probe_route else CANDIDATE_MODEL)
            or self.inputs.prompt_revision != ADAPTER_REVISION
            or operation not in {"workflow", "measurement", "probe"}
            or settings.get("input_tokens") != 20000
            or settings.get("output_tokens")
            != (
                probe_route["output_tokens"]
                if probe_route
                else 1800
                if operation == "probe"
                else 4000
            )
            or settings.get("timeout_seconds") != 30
            or settings.get("response_bytes") != 131072
            or settings.get("max_calls") != (1 if operation in {"probe", "measurement"} else 4)
            or settings.get("max_repairs") != (0 if operation in {"probe", "measurement"} else 1)
            or settings.get("price_estimate_usd_per_million")
            != (
                probe_route["prices"]
                if probe_route
                else {"input": "2", "output": "10", "verified_at": "2026-11-06"}
            )
            or sealed.get("schema_revision")
            not in {
                contract_revision(response_purpose(sealed["assistance"]["mode"], sealed["units"])),
                PROCEDURAL_REVISION,
            }
            or sealed.get("producer", {}).get("code") != producer_binding()
        ):
            raise AdmissionError("d5_settings_schema_or_producer_drift")
        control = FakeExecutor(self.store)
        with self.store.pool.connection() as conn:
            self.control._sources(conn, self.owner, self.inputs.snapshot())
            materials = tuple(
                material
                for source in self.inputs.sources
                for material in control._sources(conn, self.owner, [source.material_id])
            )
            for version_id, expected in sealed["version_hashes"].items():
                row = conn.execute(
                    "SELECT data->>'content_hash' FROM workspace_versions WHERE version_id=%s",
                    (version_id,),
                ).fetchone()
                if row is None or row[0] != expected:
                    raise AdmissionError("d5_source_version_drift")
            project = sealed.get("project_context")
            if project:
                current = WorkspaceContext._project(conn, self.owner, project["id"])
                actual = {
                    "id": current["id"],
                    "revision": current["revision"],
                    **{k: current["data"][k] for k in ("question", "scope", "constraints")},
                }
                if actual != project or current["data"]["status"] != "active":
                    raise AdmissionError("d5_project_revision_drift")
            if (
                self.mode == "provider"
                and conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone()
            ):
                raise AdmissionError("provider_forbidden_in_offline_fixture_database")
        catalog = coherent_units(materials, set(sealed["selection"]["span_ids"]))
        if any(
            key not in catalog or asdict(catalog[key]) != value
            for key, value in sealed["units"].items()
        ):
            raise AdmissionError("d5_selected_evidence_drift")
        if sealed["response_schemas_digest"] != _digest(
            schemas(
                list(sealed["units"]),
                purpose=response_purpose(sealed["assistance"]["mode"], sealed["units"]),
                revision=sealed["schema_revision"],
            )
        ):
            raise AdmissionError("d5_local_or_wire_schema_drift")
        if sealed["settings"] != {
            "temperature": None,
            "thinking": {"type": "between_tools"},
            "effort": "medium",
            "structured_outputs": True,
            "max_repairs": 1,
        }:
            raise AdmissionError("d5_model_settings_drift")
        if sealed.get("response_purpose") != response_purpose(
            sealed["assistance"]["mode"], sealed["units"]
        ):
            raise AdmissionError("d5_response_purpose_drift")
        expected_sources = tuple(
            SourceRef(
                s["work_id"], s["version_id"], s["material_id"], s["content_hash"], s["scope"]
            )
            for s in sealed["sources"]
        )
        if (
            self.inputs.sources != expected_sources
            or settings.get("selection") != sealed["selection"]
            or settings.get("research_task") != sealed["assistance"]["follow_up"]
        ):
            raise AdmissionError("d5_source_or_task_binding_drift")
        return sealed["sources"], materials

    def _initial(self) -> dict[str, Any]:
        sealed = self.inputs.settings["d5_request"]
        compact = {
            k: sealed[k]
            for k in (
                "schema_revision",
                "kind",
                "assistance",
                "project_context",
                "units",
                "settings",
                "private_context",
            )
        }
        compact["assistance"] = {
            k: sealed["assistance"][k]
            for k in ("mode", "depth", "background", "direction", "follow_up")
        }
        return {
            "phase": "draft",
            "role": "workflow",
            "sealed_request": compact,
            "output_schema": schemas(
                list(sealed["units"]),
                purpose=response_purpose(sealed["assistance"]["mode"], sealed["units"]),
                revision=sealed["schema_revision"],
            )["wire"],
        }

    def request(self, job_id: str | None = None) -> dict[str, Any]:
        _, materials = self._context()
        settings = self.inputs.settings
        sealed = settings["d5_request"]
        steps = self.snapshot(job_id).get("steps", []) if job_id else []
        if job_id:
            snapshot = self.snapshot(job_id)
            completed = [
                contact
                for contact in snapshot.get("contacts", [])
                if contact.get("endpoint") == "messages" and contact.get("state") == "completed"
            ]
            if len(completed) != len(steps):
                raise AdmissionError("d5_preceding_response_journal_mismatch")
            for step, contact in zip(steps, completed, strict=True):
                original = self._response_output(contact["response"], contact["body"])
                stored = {key: value for key, value in step["output"].items() if key != "grounding"}
                if (
                    original != stored
                    or contact["generation_request_digest"] != step["request_digest"]
                ):
                    raise AdmissionError("d5_preceding_output_binding_drift")
        if settings["d5_operation"] == "probe":
            if steps:
                raise AdmissionError("d5_probe_already_completed")
            body = self._probe_wire()
            if not isinstance(body, dict):
                raise AdmissionError("d5_probe_wire_required")
            context = json.loads(body["messages"][0]["content"])
            if (
                context.get("phase") != "check"
                or body.get("max_tokens") != settings["output_tokens"]
            ):
                raise AdmissionError("d5_probe_contract_drift")
            if (
                body.get("output_config", {}).get("format", {}).get("schema")
                != transform_schema(Checks)
                or context.get("role") != "checker"
            ):
                raise AdmissionError("d5_probe_schema_drift")
            self._checked_draft({})
            rebuilt = self._wire({**context, "output_schema": transform_schema(Checks)})
            if rebuilt != body:
                raise AdmissionError("d5_probe_wire_drift")
            return {"stage": "check", "body": body, "request_digest": _digest(body)}
        phase = (
            "draft"
            if not steps
            else "check"
            if steps[-1]["stage"] in {"draft", "repair"}
            else "repair"
        )
        if len(steps) >= 4 or phase == "repair" and len(steps) != 2:
            raise AdmissionError("d5_four_stage_limit")
        value = self._initial()
        value["phase"] = phase
        if phase in {"check", "repair"}:
            workflow = steps[-1]["output"] if phase == "check" else steps[0]["output"]
            draft, claims = resolve_draft(
                workflow,
                {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
                materials,
                purpose=response_purpose(sealed["assistance"]["mode"], sealed["units"]),
                revision=sealed["schema_revision"],
            )
            if phase == "check":
                value["role"] = "checker"
                value["sealed_request"].pop("units")
                value["output_schema"] = transform_schema(Checks)
                value["draft"] = {"claims": [asdict(c) for c in claims]}
                value["claim_inputs"] = [
                    {"claim_id": c.claim_id, "input_digest": claim_input_digest(c, materials)}
                    for c in claims
                ]
                value["unscored_prose"] = {
                    k: workflow[k]
                    for k in (
                        "background",
                        "comparison",
                        "comparison_basis",
                        "assumptions",
                        "gaps",
                        "questions",
                        "proposal",
                        "abstention",
                    )
                    if k in workflow
                }
                value["unscored_prose"].update(render_procedures(workflow))
            else:
                checked = self._checks(
                    {
                        k: steps[-1]["output"][k]
                        for k in ("checks", "prose_review", "prose_findings")
                    }
                )
                # Digest/provenance checks happen before this repair is counted.
                from src.workspace.grounding import SupportCheck

                report = validate_claims(
                    claims,
                    materials,
                    tuple(
                        SupportCheck(
                            c.claim_id,
                            c.input_digest,
                            c.decision,
                            steps[-1]["model_id"],
                            self.revision + ":check",
                            c.reason,
                        )
                        for c in checked.checks
                    ),
                )
                value["draft"] = {
                    "claims": [
                        {"claim_id": c.claim_id, "text": c.text, "kind": c.kind} for c in claims
                    ]
                }
                value["previous_grounding"] = asdict(report)
                value["previous_prose_review"] = checked.model_dump(mode="json")
                value["procedural_draft"] = {
                    k: workflow[k] for k in ("gaps", "questions", "proposal", "abstention")
                }
        body = self._wire(value)
        if phase == "draft" and _digest(body) != sealed["candidate_initial_wire_digest"]:
            raise AdmissionError("d5_initial_wire_drift")
        if (
            len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
            > sealed["capacity"]["stage_input_bytes_max"][phase]
        ):
            raise AdmissionError("d5_complete_stage_capacity_exceeded")
        return {"stage": phase, "body": body, "request_digest": _digest(body)}

    def _wire(self, context: dict[str, Any]) -> dict[str, Any]:
        routes = self.inputs.settings.get("operation_routes")
        if routes:
            from src.workspace.d5_operations import wire

            return wire(context, routes)
        return build_wire(context)

    def _response_output(self, response: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        if self.inputs.settings.get("operation_routes") and body["model"] == "claude-opus-5-5":
            from src.workspace.d5_operations import verdict_text

            text = verdict_text(response)
            # Keep the original strict model/stop/all-or-nothing object parser.
            return response_output(
                {**response, "content": [{"type": "text", "text": text}]}, body["model"]
            )
        return super()._response_output(response, body)

    def _billing_input(self, wire: dict[str, Any]) -> dict[str, Any]:
        routes = self.inputs.settings.get("operation_routes")
        if not routes:
            return super()._billing_input(wire)
        from src.workspace.d5_operations import route

        selected = route(routes, wire["stage"])
        if wire["body"]["model"] != selected["model"]:
            raise AdmissionError("d5_operation_model_drift")
        return {
            **self.inputs.snapshot(),
            "model_id": selected["model"],
            "settings": {
                **self.inputs.settings,
                "price_estimate_usd_per_million": selected["prices"],
            },
        }

    def _probe_wire(self) -> dict[str, Any]:
        context = self.inputs.settings.get("probe_context")
        if not isinstance(context, dict):
            raise AdmissionError("d5_probe_context_required")
        units = self.inputs.settings["d5_request"]["units"]
        body_context = {k: v for k, v in context.items() if k != "claims"}
        try:
            body_context["draft"] = {
                "claims": [
                    {
                        **{k: v for k, v in claim.items() if k != "handles"},
                        "evidence": [units[key] for key in claim["handles"]],
                    }
                    for claim in context["claims"]
                ]
            }
        except KeyError as exc:
            raise AdmissionError("d5_probe_unselected_evidence") from exc
        body_context["output_schema"] = transform_schema(Checks)
        body = self._wire(body_context)
        if _digest(body) != self.inputs.settings["probe_wire_digest"]:
            raise AdmissionError("d5_probe_wire_drift")
        return body

    def _draft(self, output: dict[str, Any]) -> StudyDraft:
        _, materials = self._context()
        sealed = self.inputs.settings["d5_request"]
        draft, claims = resolve_draft(
            output,
            {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
            materials,
            purpose=response_purpose(sealed["assistance"]["mode"], sealed["units"]),
            revision=sealed["schema_revision"],
        )
        procedural = render_procedures(output)
        report = validate_claims(claims, materials)
        if any(not item.scope_compatible for item in report.assessments):
            raise AdmissionError("d5_draft_scope_incompatible")
        return D5StudyDraft.model_validate(
            {
                "kind": "deep_dive",
                "title": "Quarantined D5 assistance",
                "claims": [asdict(c) for c in claims],
                "abstention": procedural["abstention"],
                "sections": [{"name": "overview", "claim_ids": [c.claim_id for c in claims]}]
                if claims
                else [],
                "questions": procedural["questions"],
                "proposed_actions": [procedural["proposal"]] if procedural["proposal"] else [],
                "limitations": render_gaps(draft.gaps),
            }
        )

    def _checks(self, output: dict[str, Any]) -> Any:
        return Checks.model_validate(output)

    def _review_complete(self, grounding: Any, snapshot: dict[str, Any], checks: Any) -> bool:
        if checks.prose_review != "procedural_only":
            # _response_authorization already bound every finding to an exact
            # existing rendered field/index before this state transition.
            # Only the first, decisive finding gets the existing single repair.
            if (
                checks.prose_review == "unscored_factual_content"
                and len(snapshot["steps"]) == 1
                and self.inputs.settings["d5_operation"] == "workflow"
                and self.inputs.settings.get("located_prose_repair") == "first-check-only-v1"
            ):
                return False
            raise AdmissionError("d5_unscored_factual_prose")
        return self._check_complete(grounding, snapshot)

    def _contact_scope(self, conn: Any, job_id: str, endpoint: str) -> None:
        _, policy = self.control._policy(
            conn, self.owner, self.inputs.snapshot(), datetime.now(UTC)
        )
        guard_scope(
            conn, self.owner, self.inputs.snapshot(), policy, endpoint=endpoint, job_id=job_id
        )

    def _dispatch_scope(self, conn: Any, job_id: str) -> None:
        _, policy = self.control._policy(
            conn, self.owner, self.inputs.snapshot(), datetime.now(UTC)
        )
        guard_scope(conn, self.owner, self.inputs.snapshot(), policy, job_id=job_id)

    def _response_authorization(self, job_id: str) -> None:
        with self.store.pool.connection() as conn:
            _, policy = self.control._policy(
                conn, self.owner, self.inputs.snapshot(), datetime.now(UTC)
            )
            bound = guard_scope(conn, self.owner, self.inputs.snapshot(), policy, job_id=job_id)
            snapshot = self.snapshot(job_id)
            last = snapshot["contacts"][-1]
            if (
                self.inputs.settings.get("operation_routes")
                and last["body"]["model"] == "claude-opus-5-5"
            ):
                from src.workspace.d5_operations import verdict_text

                text = verdict_text(last["response"])
            else:
                text = last["response"].get("content", [{}])[0].get("text", "")

            def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                value = {}
                for key, item in pairs:
                    if key in value:
                        raise AdmissionError("d5_duplicate_json_key")
                    value[key] = item
                return value

            if isinstance(text, str):

                def invalid(value: str) -> Any:
                    raise AdmissionError("d5_nonfinite_json")

                parsed = json.loads(text, object_pairs_hook=unique, parse_constant=invalid)
                if last["stage"] == "check":
                    context = json.loads(last["body"]["messages"][0]["content"])
                    checks = Checks.model_validate(parsed)
                    checks.validate_locations(context.get("unscored_prose", {}))
                    expected = {c["claim_id"]: c["input_digest"] for c in context["claim_inputs"]}
                    actual = {c.claim_id: c.input_digest for c in checks.checks}
                    if len(actual) != len(checks.checks) or actual != expected:
                        raise AdmissionError("d5_checker_claim_binding_drift")
                if len(text.encode()) > 8000:
                    raise AdmissionError("d5_compact_output_exceeded")
            response_id = last["response"].get("id")
            receipt_count = conn.execute(
                "SELECT count(*) FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c WHERE j.owner=ANY(%s)AND c->>'endpoint'='messages'AND c->'response'->>'id'=%s",
                (bound["members"], response_id),
            ).fetchone()
            if receipt_count is None:
                raise AdmissionError("d5_receipt_census_unavailable")
            found = receipt_count[0]
            if found > 1:
                raise AdmissionError("d5_duplicate_provider_response_id")
        self._context()

    def _usage_within_stage(self, ins: int, outs: int, wire: dict[str, Any]) -> bool:
        return ins <= 20000 and outs <= wire["body"]["max_tokens"]


class D5MeasurementAdapter(D5Adapter, MeasurementAdapter):
    allowed_endpoints = frozenset({"messages/count_tokens"})

    def start(
        self, request_id: str, amount_usd: str | None = None, *, now: datetime | None = None
    ) -> dict[str, Any]:
        return MeasurementAdapter.start(self, request_id, amount_usd or "0", now=now)

    async def advance(self, job_id: str, *, cancelled: Any = lambda: False) -> dict[str, Any]:
        try:
            return await MeasurementAdapter.advance(self, job_id, cancelled=cancelled)
        except BaseException as exc:
            self._quarantine_failure(job_id, type(exc).__name__)
            raise

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        job_id: str | None = None,
        ordinal: int | None = None,
    ) -> dict[str, Any]:
        if path != "messages/count_tokens" or self.inputs.settings["d5_operation"] != "measurement":
            raise AdmissionError("d5_measurement_messages_forbidden")
        expected = {
            k: v
            for k, v in self.request(job_id)["body"].items()
            if k not in {"max_tokens", "temperature"}
        }
        if body != expected:
            raise AdmissionError("d5_named_count_body_required")
        return await QualificationAdapter._post(self, path, body, job_id=job_id, ordinal=ordinal)


class D5ProbeAdapter(D5Adapter):
    def start(
        self, request_id: str, amount_usd: str | None = None, *, now: datetime | None = None
    ) -> dict[str, Any]:
        required = "0.15" if self.inputs.settings.get("operation_routes") else "0.08"
        amount_usd = amount_usd or required
        if self.inputs.settings["d5_operation"] != "probe" or Decimal(amount_usd) != Decimal(
            required
        ):
            raise AdmissionError("d5_probe_scope_required")
        return self._start(request_id, amount_usd, now=now)

    def _checked_draft(self, snapshot: dict[str, Any]) -> StudyDraft:
        _, materials = self._context()
        body = self._probe_wire()
        context = json.loads(body["messages"][0]["content"])
        claims = tuple(
            ResearchClaim(
                **{
                    **c,
                    "kind": ClaimKind(c["kind"]),
                    "evidence": tuple(EvidenceRef(**r) for r in c["evidence"]),
                }
            )
            for c in context["draft"]["claims"]
        )
        allowed = list(self.inputs.settings["d5_request"]["units"].values())
        for claim in claims:
            if any(asdict(ref) not in allowed for ref in claim.evidence):
                raise AdmissionError("d5_probe_unselected_evidence")
            if claim_input_digest(claim, materials) != next(
                c["input_digest"]
                for c in context["claim_inputs"]
                if c["claim_id"] == claim.claim_id
            ):
                raise AdmissionError("d5_probe_claim_binding_drift")
        return StudyDraft.model_validate(
            {
                "kind": "deep_dive",
                "title": "Quarantined adversarial checker diagnostic",
                "claims": [asdict(c) for c in claims],
                "sections": [{"name": "overview", "claim_ids": [c.claim_id for c in claims]}],
            }
        )

    def _check_complete(self, grounding: Any, snapshot: dict[str, Any]) -> bool:
        return True
