"""Separate, externally authorized one-call schema diagnostic over the real ledger.

This is not a research workflow and cannot publish assistance. The core durable
reservation, exact paired-count transport and raw receipts are reused. New
authority may only be recorded by the explicit operator command, never the runner.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from psycopg import sql
from psycopg.types.json import Jsonb

from src.workspace import d5_compatibility_packet as spec
from src.workspace.admission import AdmissionError, GenerationAdmission, _digest
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_benchmark import database, read, write
from src.workspace.d5_operations import verdict_text
from src.workspace.provider_adapter import QualificationAdapter
from src.workspace.qualification_accounting import priced_usage, settle_failed_response
from src.workspace.qualification_budget import census
from src.workspace.store import WorkspaceStore

GRAMMAR_ERROR = "The compiled grammar is too large, which would cause performance issues. Simplify your tool schemas or reduce the number of strict tools."


def received_rejection(data: dict[str, Any], case_id: str) -> bool:
    if case_id not in {"learn-list-control", "learn-compact", "research-compact"}:
        return False
    contacts = data.get("adapter", {}).get("contacts", [])
    if len(contacts) != 2:
        return False
    last = contacts[-1]
    receipt = last.get("response", {})
    if (
        last.get("endpoint") != "messages"
        or last.get("state") != "completed"
        or receipt.get("http_status") != 400
        or receipt.get("complete_body") is not True
    ):
        return False
    try:
        value = spec.strict_json(receipt["raw_body"])
    except (ValueError, KeyError, TypeError):
        return False
    return bool(
        value.get("type") == "error"
        and value.get("error") == {"type": "invalid_request_error", "message": GRAMMAR_ERROR}
        and "usage" not in value
        and data.get("compatibility_observation", {}).get("expected_received_grammar_rejection")
        is True
    )


def template(packet: dict[str, Any]) -> dict[str, Any]:
    spec.verify(packet)
    return {
        "approved": False,
        "approved_by": None,
        "approved_at": None,
        "approval_source": None,
        "expires_at": None,
        "authorization_kind": "owner",
        "transport_mode": "provider",
        "packet_digest": packet["packet_digest"],
        "scope_id": "compat-" + packet["packet_digest"][:24],
        "limits": packet["limits"],
        "programme_limits": packet["programme_limits"],
        "programme_expiry": packet["programme_expiry"],
        "retained_liability_exception_approved": False,
        "anticipated_received_rejection_continuation_approved": False,
        "retained_liabilities": packet["retained_liabilities"],
        "case_order": list(spec.ORDER),
        "case_bindings_digest": _digest(spec.compile_inputs(packet)),
    }


def _authorization(packet: dict[str, Any], value: dict[str, Any], fixture: bool) -> None:
    expected = template(packet)
    mutable = {
        "approved",
        "approved_by",
        "approved_at",
        "approval_source",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "retained_liability_exception_approved",
        "anticipated_received_rejection_continuation_approved",
    }
    if set(value) != set(expected) or any(
        value[k] != expected[k] for k in expected if k not in mutable
    ):
        raise AdmissionError("diagnostic_authorization_binding_drift")
    if (
        value.get("approved") is not True
        or not value.get("approved_by")
        or not value.get("approval_source")
        or value.get("retained_liability_exception_approved") is not True
        or value.get("anticipated_received_rejection_continuation_approved") is not True
    ):
        raise AdmissionError("diagnostic_explicit_owner_approval_required")
    try:
        start = datetime.fromisoformat(value["approved_at"])
        expiry = datetime.fromisoformat(value["expires_at"])
        end = datetime.fromisoformat(packet["programme_expiry"])
        valid = all(
            x.tzinfo and x.utcoffset() == timedelta(0) for x in [start, expiry, end]
        ) and start <= datetime.now(UTC) < expiry <= min(start + timedelta(hours=24), end)
    except (TypeError, ValueError):
        valid = False
    if (
        not valid
        or value["authorization_kind"] != ("offline_fixture" if fixture else "owner")
        or value["transport_mode"] != ("mock" if fixture else "provider")
    ):
        raise AdmissionError("diagnostic_expired_or_wrong_authorization")


def _fixture(conn: Any) -> bool:
    return bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())


def _sources(conn: Any, packet: dict[str, Any]) -> None:
    for label, table, key in [
        ("versions", "workspace_versions", "version_id"),
        ("materials", "workspace_material", "material_id"),
    ]:
        expected = packet["source_bindings"][label]
        actual = {
            r[0]: _digest(r[1])
            for r in conn.execute(
                sql.SQL("SELECT {},data FROM {} WHERE {}=ANY(%s)").format(
                    sql.Identifier(key), sql.Identifier(table), sql.Identifier(key)
                ),
                (list(expected),),
            )
        }
        if actual != expected:
            raise AdmissionError("diagnostic_source_or_version_drift")


def _scope(conn: Any, packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    spec.verify(packet)
    row = conn.execute(
        "SELECT state,authorization_digest,data FROM workspace_d5_scopes WHERE scope_id=%s FOR UPDATE",
        ("compat-" + packet["packet_digest"][:24],),
    ).fetchone()
    if not row or row[0] != "active":
        raise AdmissionError("diagnostic_active_external_scope_required")
    data = row[2]
    record = data.get("authorization_record", {})
    _authorization(packet, record, _fixture(conn))
    if _digest(record) != row[1] or data.get("packet") != packet:
        raise AdmissionError("diagnostic_stored_authorization_drift")
    return record, data


def guard(
    conn: Any,
    packet: dict[str, Any],
    *,
    owner: str,
    current_job: str | None = None,
    endpoint: str | None = None,
    reserve: Decimal | None = None,
) -> dict[str, Any]:
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
        ("evaluation:" + packet["program_id"],),
    )
    _scope(conn, packet)
    _sources(conn, packet)
    if spec.programme_parent(conn, packet["program_id"]) != packet["programme_parent"]:
        raise AdmissionError("diagnostic_programme_parent_drift")
    old = census(
        conn,
        packet["basis_members"][0],
        members=packet["basis_members"],
        job_ids=sorted(packet["basis"]["contact_checkpoints"]),
    )
    if old != packet["basis"]:
        raise AdmissionError("diagnostic_historical_history_or_holds_drift")
    prior = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
        (packet["parent_stopped_scope"]["scope_id"],),
    ).fetchone()
    if not prior or prior[0] != packet["parent_stopped_scope"]:
        raise AdmissionError("diagnostic_parent_scope_drift")
    compiled = spec.compile_inputs(packet)
    owners = [v["owner"] for v in compiled.values()]
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
            (packet["program_id"],),
        )
    )
    if set(members) != set(packet["basis_members"]) | set(owners) or owner not in owners:
        raise AdmissionError("diagnostic_programme_membership_drift")
    total = census(conn, owner, members=members)
    new = census(conn, owner, members=owners)
    if any(j != current_job for j in total["active_jobs"]):
        raise AdmissionError("diagnostic_one_job_at_a_time")
    current_key = next(k for k, v in compiled.items() if v["owner"] == owner)
    for key, entry in compiled.items():
        jid = "gen-" + _digest([entry["owner"], entry["request_id"]])[:40]
        row = conn.execute(
            "SELECT state,data FROM workspace_generation_jobs WHERE id=%s", (jid,)
        ).fetchone()
        if not row or jid == current_job:
            continue
        obs = row[1].get("compatibility_observation", {})
        if row[0] in {"uncertain", "running", "reserved"} and not received_rejection(row[1], key):
            raise AdmissionError("diagnostic_new_uncertainty")
        if (
            obs.get("stop_required")
            or obs.get("remote_compiler_acceptance") is None
            or (key == spec.ORDER[0] and obs.get("remote_compiler_acceptance") is not True)
        ):
            raise AdmissionError("diagnostic_prior_stop_condition")
    rows = {r["case"]: r for r in _snapshots(conn, packet)}
    index = spec.ORDER.index(current_key)
    for earlier in spec.ORDER[:index]:
        if rows[earlier]["state"] == "unrun" and earlier != "research-compact":
            raise AdmissionError("diagnostic_packet_order_required")
    for target, prerequisite in [
        ("research-compact", "learn-compact"),
        ("checker-maximum", "checker-small"),
    ]:
        if current_key == target and not (rows[prerequisite]["observation"] or {}).get(
            "local_semantic_validity"
        ):
            raise AdmissionError("diagnostic_prerequisite_incomplete")
    jobs = len(
        set(total["generation_job_ids"]) - set(packet["programme_baseline"]["generation_job_ids"])
    )
    if (
        jobs + (reserve is not None) > 64
        or total["messages"] + (endpoint == "messages" or reserve is not None) > 160
        or total["counts"] + (endpoint == "messages/count_tokens" or reserve is not None) > 200
    ):
        raise AdmissionError("diagnostic_programme_capacity_exceeded")
    if (
        len(new["generation_job_ids"]) + (reserve is not None) > 6
        or new["messages"] + (endpoint == "messages" or reserve is not None) > 6
        or new["counts"] + (endpoint == "messages/count_tokens" or reserve is not None) > 6
    ):
        raise AdmissionError("diagnostic_scope_capacity_exceeded")
    if Decimal(total["known_usd"]) + max(
        Decimal(total["pending_usd"]), Decimal(total["unknown_usd"])
    ) + (reserve or 0) > 20 or Decimal(new["known_usd"]) + max(
        Decimal(new["pending_usd"]), Decimal(new["unknown_usd"])
    ) + (reserve or 0) > Decimal("1.80"):
        raise AdmissionError("diagnostic_budget_exceeded")
    return new


def record(
    store: WorkspaceStore, packet: dict[str, Any], authorization: dict[str, Any]
) -> dict[str, Any]:
    spec.verify(packet)
    compiled = spec.compile_inputs(packet)
    scope = authorization["scope_id"]
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            ("evaluation:" + packet["program_id"],),
        )
        _authorization(packet, authorization, _fixture(conn))
        _sources(conn, packet)
        if conn.execute("SELECT 1 FROM workspace_d5_scopes WHERE scope_id=%s", (scope,)).fetchone():
            raise AdmissionError("diagnostic_scope_already_recorded_no_renewal")
        if (
            spec.programme_parent(conn, packet["program_id"]) != packet["programme_parent"]
            or census(conn, packet["basis_members"][0], members=packet["basis_members"])
            != packet["basis"]
        ):
            raise AdmissionError("diagnostic_activation_baseline_drift")
        prior = conn.execute(
            "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
            (packet["parent_stopped_scope"]["scope_id"],),
        ).fetchone()
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s",
                (packet["program_id"],),
            )
        )
        if (
            not prior
            or prior[0] != packet["parent_stopped_scope"]
            or members != packet["basis_members"]
        ):
            raise AdmissionError("diagnostic_activation_scope_or_membership_drift")
        digest = _digest(authorization)
        data = {"packet": packet, "authorization_record": authorization, "diagnostic_only": True}
        conn.execute(
            "INSERT INTO workspace_d5_scopes(scope_id,packet_digest,authorization_digest,state,expires_at,data) VALUES(%s,%s,%s,'active',%s,%s)",
            (
                scope,
                packet["packet_digest"],
                digest,
                datetime.fromisoformat(authorization["expires_at"]),
                Jsonb(data),
            ),
        )
        program_row = conn.execute(
            "SELECT authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
            (packet["program_id"],),
        ).fetchone()
        if not program_row:
            raise AdmissionError("diagnostic_programme_missing")
        program_auth = program_row[0]
        for key, c in compiled.items():
            policy = {
                "approved": True,
                "approval_record": {
                    "approval_id": digest,
                    "approved_by": authorization["approved_by"],
                    "approved_at": authorization["approved_at"],
                },
                "valid_from": authorization["approved_at"],
                "expires_at": authorization["expires_at"],
                "model_ids": [c["input"]["model_id"]],
                "source_scopes": sorted({s["scope"] for s in c["input"]["sources"]}),
                "allow_private_context": False,
                "per_job_usd": c["reservation_USD"],
                "day_usd": "20",
                "month_usd": "20",
                "transport_mode": authorization["transport_mode"],
                "purpose": "workspace-schema-compatibility-diagnostic",
                "everyday_generation": False,
                "request_id": c["request_id"],
                "request_digest": _digest(c["input"]),
                "compatibility_scope": scope,
                "program_id": packet["program_id"],
                "program_authorization_digest": program_auth,
                "case_id": key,
            }
            conn.execute(
                "INSERT INTO workspace_evaluation_members(owner,program_id) VALUES(%s,%s)",
                (c["owner"], packet["program_id"]),
            )
            conn.execute(
                "INSERT INTO workspace_budget_policies(owner,approval_id,data) VALUES(%s,%s,%s)",
                (c["owner"], digest, Jsonb(policy)),
            )
    return {
        "scope_id": scope,
        "authorization_digest": digest,
        "expires_at": authorization["expires_at"],
        "provider_contacts": 0,
    }


class DiagnosticAdmission(GenerationAdmission):
    @staticmethod
    def _policy(
        conn: Any, owner: str, inputs: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any]]:
        approval, policy = GenerationAdmission._policy(conn, owner, inputs, now)
        row = conn.execute(
            "SELECT data FROM workspace_d5_scopes WHERE scope_id=%s",
            (policy.get("compatibility_scope"),),
        ).fetchone()
        if (
            not row
            or policy.get("purpose") != "workspace-schema-compatibility-diagnostic"
            or policy.get("request_digest") != _digest(inputs)
            or policy.get("everyday_generation") is not False
        ):
            raise AdmissionError("diagnostic_bound_policy_required")
        packet = row[0]["packet"]
        entry = spec.compile_inputs(packet).get(policy["case_id"])
        if (
            not entry
            or entry["owner"] != owner
            or entry["input"] != inputs
            or entry["request_id"] != policy["request_id"]
        ):
            raise AdmissionError("diagnostic_exact_case_binding_required")
        guard(
            conn,
            packet,
            owner=owner,
            current_job="gen-" + _digest([owner, policy["request_id"]])[:40],
        )
        return approval, policy

    def _admit_reservation(
        self, conn: Any, owner: str, policy: dict[str, Any], amount: Decimal
    ) -> None:
        packet = conn.execute(
            "SELECT data->'packet' FROM workspace_d5_scopes WHERE scope_id=%s",
            (policy["compatibility_scope"],),
        ).fetchone()[0]
        entry = spec.compile_inputs(packet)[policy["case_id"]]
        if amount != Decimal(entry["reservation_USD"]):
            raise AdmissionError("diagnostic_reservation_drift")
        guard(conn, packet, owner=owner, reserve=amount)


class DiagnosticAdapter(QualificationAdapter):
    admission_type = DiagnosticAdmission
    revision = spec.REVISION
    _complete_http_body = D5Adapter._complete_http_body
    _partial_http_body = D5Adapter._partial_http_body
    _contact_timing = D5Adapter._contact_timing

    def _context(self) -> tuple[list[dict[str, Any]], Any]:
        with self.store.pool.connection() as conn:
            row = conn.execute(
                "SELECT data->'packet' FROM workspace_d5_scopes WHERE scope_id=%s",
                (self.inputs.settings["compatibility_scope"],),
            ).fetchone()
            if not row:
                raise AdmissionError("diagnostic_scope_required")
            self.packet = row[0]
            spec.verify(self.packet)
            entry = spec.compile_inputs(self.packet)[self.inputs.settings["case_id"]]
            if entry["owner"] != self.owner or entry["input"] != self.inputs.snapshot():
                raise AdmissionError("diagnostic_input_drift")
            if _fixture(conn) != (self.mode == "mock"):
                raise AdmissionError("diagnostic_fixture_provider_boundary")
            _sources(conn, self.packet)
        return [asdict_source(s) for s in self.inputs.sources], spec.materials(self.packet)

    def request(self, job_id: str | None = None) -> dict[str, Any]:
        self._context()
        case = next(c for c in self.packet["cases"] if c["id"] == self.inputs.settings["case_id"])
        return {
            "stage": "check" if case["family"] == "checker" else "draft",
            "body": deepcopy(case["body"]),
            "request_digest": case["request_digest"],
        }

    def start(
        self, request_id: str, amount_usd: str | None = None, *, now: datetime | None = None
    ) -> dict[str, Any]:
        entry = spec.compile_inputs(self.packet)[self.inputs.settings["case_id"]]
        if request_id != entry["request_id"] or amount_usd not in {None, entry["reservation_USD"]}:
            raise AdmissionError("diagnostic_named_job_only")
        return self._start(request_id, entry["reservation_USD"], now=now)

    def _contact_scope(self, conn: Any, job_id: str, endpoint: str) -> None:
        guard(conn, self.packet, owner=self.owner, current_job=job_id, endpoint=endpoint)

    def _dispatch_scope(self, conn: Any, job_id: str) -> None:
        guard(conn, self.packet, owner=self.owner, current_job=job_id)

    def _timeout_seconds(self, path: str, contact: dict[str, Any], data: dict[str, Any]) -> float:
        origin = datetime.fromisoformat(data["created_at"])
        remaining = 600 - (datetime.now(UTC) - origin).total_seconds()
        if remaining <= 0:
            raise AdmissionError("diagnostic_workflow_deadline")
        return min(
            remaining,
            60 if path.endswith("count_tokens") else float(self.inputs.settings["timeout_seconds"]),
        )

    def _observe(self, job_id: str, value: dict[str, Any]) -> None:
        with self.store.pool.connection() as conn:
            self.control._lock(conn, self.owner)
            _, _, data = self.control._job(conn, self.owner, job_id)
            if "compatibility_observation" in data:
                raise AdmissionError("diagnostic_result_immutable")
            data["compatibility_observation"] = value
            conn.execute(
                "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job_id)
            )

    async def advance(self, job_id: str, *, cancelled: Any = lambda: False) -> dict[str, Any]:
        if self.snapshot(job_id)["state"] != "running":
            raise AdmissionError("diagnostic_no_replay")
        case = next(c for c in self.packet["cases"] if c["id"] == self.inputs.settings["case_id"])
        obs = {
            "case_id": case["id"],
            "remote_compiler_acceptance": None,
            "complete_output": None,
            "local_semantic_validity": None,
            "research_quality": "UNMEASURED",
            "human_labels": None,
            "content_accepted": False,
            "diagnostic_only": True,
        }
        try:
            if cancelled():
                raise AdmissionError("diagnostic_cancelled")
            wire = self.request(job_id)
            ordinal = self._contact(job_id, wire, "messages/count_tokens")
            response = await self._post(
                "messages/count_tokens",
                {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}},
                job_id=job_id,
                ordinal=ordinal,
            )
            self._record(job_id, ordinal, response)
            count = response.get("input_tokens")
            if type(count) is not int or not 0 <= count <= 32000:
                raise AdmissionError("diagnostic_input_count_does_not_fit")
            if cancelled():
                raise AdmissionError("diagnostic_cancelled")
            ordinal = self._contact(job_id, wire, "messages")
            response = await self._post("messages", wire["body"], job_id=job_id, ordinal=ordinal)
            self._record(job_id, ordinal, response)
            ins, outs, cost = priced_usage(response, self.inputs.snapshot())
            role = "checker" if case["family"] == "checker" else "workflow"
            amounts = {"workflow_usd": "0", "judge_usd": "0"}
            amounts["judge_usd" if role == "checker" else "workflow_usd"] = str(
                cost if self.mode == "provider" else Decimal(0)
            )
            self.control.reconcile(
                self.owner,
                job_id,
                receipt_id="diagnostic-metered",
                workflow_usd=amounts["workflow_usd"],
                judge_usd=amounts["judge_usd"],
            )
            if ins > 40000 or outs > wire["body"]["max_tokens"]:
                raise AdmissionError("diagnostic_actual_usage_exceeded")
            obs.update(
                remote_compiler_acceptance=True,
                input_count=count,
                usage={"input_tokens": ins, "output_tokens": outs},
                usage_basis="synthetic fixture"
                if self.mode == "mock"
                else "provider reported; prices estimate",
            )
            if not isinstance(response.get("id"), str) or not response["id"].strip():
                raise AdmissionError("diagnostic_provider_receipt_id_required")
            with self.store.pool.connection() as conn:
                guard(conn, self.packet, owner=self.owner, current_job=job_id)
                repeated = conn.execute(
                    "SELECT 1 FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c WHERE j.id<>%s AND c->'response'->>'id'=%s",
                    (job_id, response["id"]),
                ).fetchone()
                if repeated:
                    raise AdmissionError("diagnostic_duplicate_provider_receipt")
            if cancelled():
                raise AdmissionError("diagnostic_cancelled")
            text = verdict_text(response)
            obs["complete_output"] = response.get("stop_reason") == "end_turn"
            if response.get("model") != self.inputs.model_id or not obs["complete_output"]:
                raise AdmissionError("diagnostic_model_or_incomplete_output")
            parsed = spec.strict_json(text)
            from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

            Draft202012Validator(case["schemas"]["wire"]).validate(parsed)
            normalized = spec.observed(parsed, case, self.packet)
            obs.update(local_semantic_validity=True, observed=normalized)
            self.control.reconcile(
                self.owner,
                job_id,
                receipt_id="diagnostic-complete",
                final=True,
                result=obs,
                workflow_usd=amounts["workflow_usd"],
                judge_usd=amounts["judge_usd"],
            )
            self._observe(job_id, obs)
        except BaseException as exc:
            snapshot = self.snapshot(job_id)
            last = snapshot["contacts"][-1] if snapshot["contacts"] else {}
            received = last.get("response", {})
            if (
                last.get("endpoint") == "messages"
                and received.get("http_status") == 400
                and received.get("complete_body")
                and received.get("raw_body")
            ):
                try:
                    error = json.loads(received["raw_body"])["error"]
                except (KeyError, ValueError, TypeError):
                    error = {}
                if (
                    error.get("type") == "invalid_request_error"
                    and error.get("message") == GRAMMAR_ERROR
                ):
                    obs.update(
                        remote_compiler_acceptance=False,
                        expected_received_grammar_rejection=True,
                        complete_response_received=True,
                    )
            obs.update(error_class=type(exc).__name__, reason=str(exc))
            obs["stop_required"] = isinstance(exc, AdmissionError) and str(exc) not in {
                "diagnostic_model_or_incomplete_output",
                "diagnostic_duplicate_json_key",
                "diagnostic_nonfinite_json",
                "diagnostic_object_required",
            }
            if obs["remote_compiler_acceptance"] is True:
                obs["local_semantic_validity"] = False
            self._observe(job_id, obs)
            try:
                settle_failed_response(
                    self.store,
                    self.owner,
                    job_id,
                    receipt_id="diagnostic-failed-content",
                    reason="diagnostic_only_not_accepted_content",
                )
            except (AdmissionError, KeyError, TypeError, ValueError):
                self.control.recover(self.owner, job_id)
        return self.snapshot(job_id)


def asdict_source(source: Any) -> dict[str, Any]:
    from dataclasses import asdict

    return asdict(source)


def _snapshots(
    conn: Any, packet: dict[str, Any], compiled: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    rows = []
    for key, entry in (compiled if compiled is not None else spec.compile_inputs(packet)).items():
        job_id = "gen-" + _digest([entry["owner"], entry["request_id"]])[:40]
        row = conn.execute(
            "SELECT state,data FROM workspace_generation_jobs WHERE id=%s AND owner=%s",
            (job_id, entry["owner"]),
        ).fetchone()
        rows.append(
            {
                "case": key,
                "state": row[0] if row else "unrun",
                "job_id": job_id if row else None,
                "observation": row[1].get("compatibility_observation") if row else None,
            }
        )
    return rows


def snapshots(
    store: WorkspaceStore, packet: dict[str, Any], compiled: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    with store.pool.connection() as conn:
        return _snapshots(conn, packet, compiled)


async def run(
    store: WorkspaceStore,
    packet: dict[str, Any],
    *,
    transport: httpx.MockTransport | None = None,
    api_key: str = "local-preview-disabled",
    enabled: bool = False,
    progress: Any = None,
) -> dict[str, Any]:
    spec.verify(packet)
    compiled = spec.compile_inputs(packet)
    if any(row["state"] != "unrun" for row in snapshots(store, packet, compiled)):
        raise AdmissionError("diagnostic_scope_not_fresh_no_replay")
    results: dict[str, Any] = {}
    stop = None
    for case in packet["cases"]:
        key = case["id"]
        prerequisite = (
            "learn-compact"
            if key == "research-compact"
            else "checker-small"
            if key == "checker-maximum"
            else None
        )
        if prerequisite and not results.get(prerequisite, {}).get("local_semantic_validity"):
            results[key] = {
                "skipped": "prerequisite incomplete or locally invalid",
                "research_quality": "UNMEASURED",
            }
            continue
        entry = compiled[key]
        from src.workspace.d5_freeze import restore_input

        try:
            adapter = DiagnosticAdapter(
                store,
                entry["owner"],
                restore_input(entry["input"]),
                transport=transport,
                api_key=api_key,
                enabled=enabled,
            )
            job = adapter.start(entry["request_id"])
            await adapter.advance(job["id"])
        except Exception as exc:
            stop = {"case": key, "reason": type(exc).__name__ + ":" + str(exc)}
            break
        row = next(r for r in snapshots(store, packet, compiled) if r["case"] == key)
        obs = row["observation"]
        results[key] = obs
        if progress:
            progress({"case": key, **obs})
        expected = bool(
            obs.get("expected_received_grammar_rejection")
            and key in {"learn-list-control", "learn-compact", "research-compact"}
        )
        if (
            obs.get("stop_required")
            or (row["state"] == "uncertain" and not expected)
            or obs.get("remote_compiler_acceptance") is None
            or (
                key == "learn-accepted-control"
                and obs.get("remote_compiler_acceptance") is not True
            )
        ):
            stop = {
                "case": key,
                "reason": "unexpected provider/binding/accounting/uncertainty or baseline rejection",
            }
            break
    with store.pool.connection() as conn:
        owners = [v["owner"] for v in compiled.values()]
        members = packet["basis_members"] + owners
        accounting: dict[str, Any] = {
            "cumulative": census(conn, members[0], members=members),
            "new_scope": census(conn, owners[0], members=owners),
            "held_policy": "pending and unknown overlap; count max once, never sum",
        }
        accounting["cumulative"]["funded_programme_jobs"] = len(
            set(accounting["cumulative"]["generation_job_ids"])
            - set(packet["programme_baseline"]["generation_job_ids"])
        )
        accounting["new_scope"]["funded_jobs"] = len(accounting["new_scope"]["generation_job_ids"])
        conn.execute(
            "UPDATE workspace_d5_scopes SET state=%s WHERE scope_id=%s AND state='active'",
            ("stopped", "compat-" + packet["packet_digest"][:24]),
        )
    return {
        "packet_digest": packet["packet_digest"],
        "cases": [{"id": key, **results.get(key, {"state": "unrun"})} for key in spec.ORDER],
        "stop": stop,
        "human_qualification": False,
        "full_campaign_ready": False,
        "everyday_generation": False,
        "accounting": accounting,
        "durable_jobs": snapshots(store, packet, compiled),
    }


def reports(out: Path, result: dict[str, Any]) -> None:
    """Readable axes, not a synthetic research-quality score or acceptance."""
    targets = [out, out.with_suffix(".md"), out.with_suffix(".html")]
    if any(p.exists() for p in targets):
        raise AdmissionError("diagnostic_report_exists_preserve_original")
    rows = [
        "# Quarantined schema compatibility diagnostic",
        "",
        "Provider observations are separate from research quality. Human labels remain blank.",
        "",
        "| Identity | Compiler | Complete | Local validity | Quality |",
        "|---|---|---|---|---|",
    ]
    for c in result["cases"]:
        rows.append(
            "| "
            + " | ".join(
                str(c.get(k, "UNRUN"))
                for k in [
                    "id",
                    "remote_compiler_acceptance",
                    "complete_output",
                    "local_semantic_validity",
                    "research_quality",
                ]
            )
            + " |"
        )
    text = (
        "\n".join(rows) + "\n\nAccounting and exact passages: see the companion immutable JSON.\n"
    )
    write(out, result)
    targets[1].write_text(text)
    targets[2].write_text(
        "<!doctype html><html lang='en'><meta charset='utf-8'><title>Quarantined diagnostic</title><body><pre>"
        + html.escape(text)
        + "</pre></body></html>"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["verify", "template", "record", "run"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise AdmissionError("diagnostic_output_exists_preserve_original")
    packet = read(args.packet)
    spec.verify(packet)
    if args.verb == "verify":
        write(
            args.out,
            {"packet_digest": packet["packet_digest"], "verified": True, "provider_contacts": 0},
        )
        return
    if args.verb == "template":
        write(args.out, template(packet))
        return
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if args.verb == "record":
            if args.authorization is None:
                parser.error("record requires external authorization")
            write(args.out, record(store, packet, read(args.authorization)))
            return
        if args.out.exists():
            raise AdmissionError("diagnostic_output_exists_no_replay")
        result = asyncio.run(
            run(
                store,
                packet,
                api_key=os.environ.get("ANTHROPIC_API_KEY", "local-preview-disabled"),
                enabled=True,
                progress=lambda v: print(json.dumps(v, default=str), flush=True),
            )
        )
        reports(args.out, result)


if __name__ == "__main__":
    main()
