"""Disabled-by-default generation admission; no provider SDK or approval writer.

Production routes still refuse generation. The qualification-only adapter in
provider_adapter consumes sealed retained input, applies wire/token/call limits
and journals contacts over these reservations. Its mocked transport tests do
not qualify a checker. No API key or numeric cap is approval.

UTC accounting periods use the time a cumulative receipt is recorded. Unknown
billing and unused active reservations carry into every new period until
reconciled. Receipts are injected evidence; this module does not verify bills
against a provider. Recovery never reconstructs a possibly billed provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from psycopg.types.json import Jsonb

from src.workspace.store import ConflictError, WorkspaceStore

DISABLED_KEY = "local-preview-disabled"
ACTIVE = {"reserved", "running", "uncertain"}
SCOPES = {"metadata", "abstract", "excerpt", "full_text"}
MAX_LEDGER_JOBS = 10_000


class AdmissionError(ValueError):
    """A stable refusal reason; never includes private prompt text or keys."""


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise AdmissionError("invalid_sealed_input") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, Decimal, int)):
        raise AdmissionError("invalid_money")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AdmissionError("invalid_money") from exc
    if not amount.is_finite() or not 0 <= amount <= 1_000_000:
        raise AdmissionError("invalid_money")
    return amount


def _now(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise AdmissionError("timezone_required")
    return instant.astimezone(UTC)


def _policy_time(value: Any) -> datetime:
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None or instant.utcoffset() != UTC.utcoffset(instant):
            raise ValueError("UTC required")
        return instant
    except (TypeError, ValueError) as exc:
        raise AdmissionError("invalid_approval_validity") from exc


@dataclass(frozen=True)
class SourceRef:
    work_id: str
    version_id: str
    material_id: str
    content_hash: str
    scope: str


@dataclass(frozen=True)
class GenerationInput:
    kind: Literal["summary", "deep_dive"]
    model_id: str
    prompt_revision: str
    sources: tuple[SourceRef, ...]
    settings: Mapping[str, Any]
    private_question: str = ""

    def snapshot(self) -> dict[str, Any]:
        if (
            self.kind not in {"summary", "deep_dive"}
            or not self.model_id.strip()
            or not self.prompt_revision.strip()
            or not 1 <= len(self.sources) <= 10
            or len({source.material_id for source in self.sources}) != len(self.sources)
            or len(self.private_question) > 4000
            or any(
                source.scope not in SCOPES
                or any(
                    not value.strip() or len(value) > 300
                    for value in (
                        source.work_id,
                        source.version_id,
                        source.material_id,
                        source.content_hash,
                    )
                )
                for source in self.sources
            )
        ):
            raise AdmissionError("invalid_sealed_input")
        value = {
            "kind": self.kind,
            "model_id": self.model_id,
            "prompt_revision": self.prompt_revision,
            "sources": [asdict(source) for source in self.sources],
            "settings": dict(self.settings),
            "private_question": self.private_question,
        }
        encoded = _json(value)
        if len(encoded) > 32_000:
            raise AdmissionError("invalid_sealed_input")
        return dict(json.loads(encoded))


class GenerationAdmission:
    """Owner-serialized reservation, single-start fence and conservative recovery."""

    def __init__(self, store: WorkspaceStore):
        self.store = store

    @staticmethod
    def _request_id(policy: dict[str, Any], request_id: str) -> None:
        """Extension point for a qualification approval's single named job."""

    def _lock(self, conn: Any, owner: str) -> None:
        self.store._owner(owner)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("generation:" + owner,)
        )

    @staticmethod
    def _policy(
        conn: Any, owner: str, inputs: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any]]:
        row = conn.execute(
            "SELECT approval_id,data FROM workspace_budget_policies WHERE owner=%s FOR UPDATE",
            (owner,),
        ).fetchone()
        if not row or row[1].get("approved") is not True:
            raise AdmissionError("owner_approval_required")
        approval_id, data = row
        provenance = data.get("approval_record")
        if (
            not approval_id.strip()
            or not isinstance(provenance, dict)
            or provenance.get("approval_id") != approval_id
            or not isinstance(provenance.get("approved_by"), str)
            or not provenance["approved_by"].strip()
        ):
            raise AdmissionError("approval_provenance_required")
        if (
            not _policy_time(provenance.get("approved_at"))
            <= _policy_time(data.get("valid_from"))
            <= now
            < _policy_time(data.get("expires_at"))
        ):
            raise AdmissionError("approval_not_effective")
        if (
            not isinstance(data.get("model_ids"), list)
            or inputs["model_id"] not in data["model_ids"]
            or not isinstance(data.get("source_scopes"), list)
            or any(source["scope"] not in data["source_scopes"] for source in inputs["sources"])
            or (inputs["private_question"] and data.get("allow_private_context") is not True)
        ):
            raise AdmissionError("outside_approved_scope")
        caps = [_money(data.get(key)) for key in ("per_job_usd", "day_usd", "month_usd")]
        if not 0 < caps[0] <= caps[1] <= caps[2]:
            raise AdmissionError("invalid_approved_caps")
        return str(approval_id), dict(data)

    @staticmethod
    def _sources(conn: Any, owner: str, inputs: dict[str, Any]) -> None:
        for source in inputs["sources"]:
            row = conn.execute(
                "SELECT m.content_hash,m.source_scope FROM workspace_material m JOIN workspace_versions v ON v.version_id=m.version_id JOIN workspace_works w ON w.work_id=v.work_id WHERE m.material_id=%s AND v.version_id=%s AND v.work_id=%s AND (w.visibility_owner IS NULL OR w.visibility_owner=%s)",
                (source["material_id"], source["version_id"], source["work_id"], owner),
            ).fetchone()
            if not row or row != (source["content_hash"], source["scope"]):
                raise AdmissionError("source_material_changed_or_inaccessible")

    @staticmethod
    def _exposure(conn: Any, owner: str, now: datetime) -> tuple[Decimal, Decimal]:
        rows = conn.execute(
            "SELECT r.amount,r.workflow,r.judge,r.unknown,r.state,j.data FROM workspace_spend_reservations r JOIN workspace_generation_jobs j ON j.id=r.job_id WHERE r.owner=%s LIMIT %s",
            (owner, MAX_LEDGER_JOBS + 1),
        ).fetchall()
        if len(rows) > MAX_LEDGER_JOBS:
            raise AdmissionError("ledger_requires_rollup")
        day = month = Decimal(0)
        today, this_month = now.date().isoformat(), now.date().replace(day=1).isoformat()
        for amount, workflow, judge, unknown, state, data in rows:
            # Unresolved spend/unused holds remain charged across midnight.
            pending = unknown + (
                max(Decimal(0), amount - workflow - judge - unknown)
                if state in ACTIVE
                else Decimal(0)
            )
            day += pending
            month += pending
            all_workflow = all_judge = Decimal(0)
            for event in data.get("usage_events", []):
                event_day = date.fromisoformat(event["day"])
                if event["month"] != event_day.replace(day=1).isoformat():
                    raise AdmissionError("ledger_reconciliation_required")
                all_workflow += _money(event["workflow"])
                all_judge += _money(event["judge"])
                known = _money(event["workflow"]) + _money(event["judge"])
                if event["day"] == today:
                    day += known
                if event["month"] == this_month:
                    month += known
            if all_workflow != workflow or all_judge != judge:
                raise AdmissionError("ledger_reconciliation_required")
        return day, month

    @staticmethod
    def _job(conn: Any, owner: str, job_id: str) -> tuple[str, str, dict[str, Any]]:
        row = conn.execute(
            "SELECT state,input_digest,data FROM workspace_generation_jobs WHERE owner=%s AND id=%s FOR UPDATE",
            (owner, job_id),
        ).fetchone()
        if not row:
            raise AdmissionError("job_not_found")
        return str(row[0]), str(row[1]), dict(row[2])

    def reserve(
        self,
        owner: str,
        request_id: str,
        inputs: GenerationInput,
        amount_usd: str | Decimal,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self.store._owner(owner)
        if not request_id.strip() or len(request_id) > 120:
            raise AdmissionError("invalid_request_id")
        sealed, amount, instant = inputs.snapshot(), _money(amount_usd), _now(now)
        fingerprint = _digest(sealed)
        job_id = "gen-" + _digest([owner, request_id])[:40]
        self.store.migrate()
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            approval_id, policy = self._policy(conn, owner, sealed, instant)
            self._request_id(policy, request_id)
            self._sources(conn, owner, sealed)
            prior = conn.execute(
                "SELECT state,input_digest,data FROM workspace_generation_jobs WHERE owner=%s AND id=%s",
                (owner, job_id),
            ).fetchone()
            if prior:
                if prior[1] != fingerprint or _money(prior[2]["reserved_usd"]) != amount:
                    raise ConflictError("generation retry changed sealed input or reservation")
                return {
                    "id": job_id,
                    "state": prior[0],
                    "input_digest": fingerprint,
                    "cached": prior[0] == "ready",
                    "result": prior[2].get("result"),
                }
            cached = conn.execute(
                "SELECT id,data FROM workspace_generation_jobs WHERE owner=%s AND input_digest=%s AND state='ready' AND approval_id=%s ORDER BY id LIMIT 1",
                (owner, fingerprint, approval_id),
            ).fetchone()
            if cached:
                return {
                    "id": cached[0],
                    "state": "ready",
                    "input_digest": fingerprint,
                    "cached": True,
                    "result": cached[1]["result"],
                }
            day, month = self._exposure(conn, owner, instant)
            if amount <= 0 or amount > _money(policy["per_job_usd"]):
                raise AdmissionError("job_cap_exceeded")
            if day + amount > _money(policy["day_usd"]):
                raise AdmissionError("day_cap_exceeded")
            if month + amount > _money(policy["month_usd"]):
                raise AdmissionError("month_cap_exceeded")
            data = {
                "sealed_input": sealed,
                "policy_digest": _digest(policy),
                "approval_record": policy["approval_record"],
                "reserved_usd": str(amount),
                "created_at": instant.isoformat(),
                "usage_events": [],
                "receipts": {},
            }
            conn.execute(
                "INSERT INTO workspace_generation_jobs VALUES (%s,%s,%s,'reserved',%s,%s)",
                (job_id, owner, approval_id, fingerprint, Jsonb(data)),
            )
            conn.execute(
                "INSERT INTO workspace_spend_reservations(job_id,owner,amount,day,month,state) VALUES (%s,%s,%s,%s,%s,'reserved')",
                (job_id, owner, amount, instant.date(), instant.date().replace(day=1)),
            )
            return {
                "id": job_id,
                "state": "reserved",
                "input_digest": fingerprint,
                "cached": False,
                "result": None,
            }

    def construct_provider(
        self,
        owner: str,
        job_id: str,
        effective_input: GenerationInput,
        factory: Callable[[dict[str, Any]], Any],
        *,
        mode: Literal["disabled", "fake", "live"] = "disabled",
        api_key: str = DISABLED_KEY,
        now: datetime | None = None,
    ) -> Any:
        # The production default and sentinel reject before factory construction.
        if (
            mode == "disabled"
            or mode not in {"fake", "live"}
            or (
                mode == "live"
                and (
                    not api_key.strip()
                    or api_key == DISABLED_KEY
                    or os.environ.get("ANTHROPIC_API_KEY") == DISABLED_KEY
                )
            )
            or (mode == "fake" and api_key != DISABLED_KEY)
        ):
            raise AdmissionError("provider_disabled")
        sealed, instant = effective_input.snapshot(), _now(now)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            state, fingerprint, data = self._job(conn, owner, job_id)
            _, policy = self._policy(conn, owner, sealed, instant)
            self._sources(conn, owner, sealed)
            if _digest(sealed) != fingerprint or _digest(policy) != data["policy_digest"]:
                raise AdmissionError("sealed_execution_drift")
            if state != "reserved":
                raise AdmissionError("job_already_started_or_terminal")
            conn.execute(
                "UPDATE workspace_generation_jobs SET state='running' WHERE id=%s", (job_id,)
            )
            conn.execute(
                "UPDATE workspace_spend_reservations SET state='running' WHERE job_id=%s", (job_id,)
            )
        # No database locks or transactions survive into injected/provider work.
        try:
            return factory(sealed)
        except Exception:
            self.recover(owner, job_id)
            raise

    def reconcile(
        self,
        owner: str,
        job_id: str,
        *,
        receipt_id: str,
        workflow_usd: str | Decimal,
        judge_usd: str | Decimal,
        unknown_usd: str | Decimal = "0",
        final: bool = False,
        result: Any = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Apply an idempotent cumulative receipt, keeping role costs distinct.

        Only a receipt may reduce uncertainty; known spend never decreases.
        An overshoot is retained and stops the job rather than being rolled back.
        """
        workflow, judge, unknown = map(_money, (workflow_usd, judge_usd, unknown_usd))
        instant = _now(now)
        if not receipt_id.strip() or len(receipt_id) > 120:
            raise AdmissionError("receipt_required")
        if not isinstance(final, bool):
            raise AdmissionError("invalid_usage_transition")
        receipt = {
            "workflow": str(workflow),
            "judge": str(judge),
            "unknown": str(unknown),
            "final": final,
            "result": result,
        }
        receipt_digest = _digest(receipt)
        self.store.migrate()
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            state, _, data = self._job(conn, owner, job_id)
            old = conn.execute(
                "SELECT amount,workflow,judge FROM workspace_spend_reservations WHERE job_id=%s",
                (job_id,),
            ).fetchone()
            if old is None:
                raise AdmissionError("reservation_missing")
            if receipt_id in data["receipts"]:
                if data["receipts"][receipt_id] != receipt_digest:
                    raise ConflictError("usage receipt changed")
                return {
                    "id": job_id,
                    "state": state,
                    "workflow_usd": str(old[1]),
                    "judge_usd": str(old[2]),
                }
            if (
                state == "reserved"
                or (state == "ready" and not final)
                or workflow < old[1]
                or judge < old[2]
                or len(data["receipts"]) >= 100
            ):
                raise AdmissionError("invalid_usage_transition")
            data["usage_events"].append(
                {
                    "day": instant.date().isoformat(),
                    "month": instant.date().replace(day=1).isoformat(),
                    "workflow": str(workflow - old[1]),
                    "judge": str(judge - old[2]),
                }
            )
            data["receipts"][receipt_id] = receipt_digest
            overshot = workflow + judge + unknown > old[0]
            next_state = (
                "budget_stopped"
                if overshot
                else state
                if state in {"cancelled", "budget_stopped"}
                else "uncertain"
                if unknown or (state == "uncertain" and not final)
                else "ready"
                if final
                else "running"
            )
            if next_state == "ready":
                data["result"] = result
            conn.execute(
                "UPDATE workspace_generation_jobs SET state=%s,data=%s WHERE id=%s",
                (next_state, Jsonb(data), job_id),
            )
            conn.execute(
                "UPDATE workspace_spend_reservations SET workflow=%s,judge=%s,unknown=%s,state=%s WHERE job_id=%s",
                (workflow, judge, unknown, next_state, job_id),
            )
            return {
                "id": job_id,
                "state": next_state,
                "workflow_usd": str(workflow),
                "judge_usd": str(judge),
                "unknown_usd": str(unknown),
            }

    def _stop(self, owner: str, job_id: str, cancel: bool) -> dict[str, Any]:
        self.store.migrate()
        with self.store.pool.connection() as conn:
            self._lock(conn, owner)
            state, _, _ = self._job(conn, owner, job_id)
            row = conn.execute(
                "SELECT amount,workflow,judge,unknown FROM workspace_spend_reservations WHERE job_id=%s",
                (job_id,),
            ).fetchone()
            if row is None:
                raise AdmissionError("reservation_missing")
            unknown = max(row[3], row[0] - row[1] - row[2]) if state == "running" else row[3]
            next_state = (
                "cancelled"
                if cancel and state in ACTIVE
                else "uncertain"
                if state == "running"
                else state
            )
            conn.execute(
                "UPDATE workspace_generation_jobs SET state=%s WHERE id=%s", (next_state, job_id)
            )
            conn.execute(
                "UPDATE workspace_spend_reservations SET state=%s,unknown=%s WHERE job_id=%s",
                (next_state, unknown, job_id),
            )
            return {"id": job_id, "state": next_state, "unknown_usd": str(unknown)}

    def cancel(self, owner: str, job_id: str) -> dict[str, Any]:
        """Release only unstarted work; in-flight billing remains uncertain."""
        return self._stop(owner, job_id, True)

    def recover(self, owner: str, job_id: str) -> dict[str, Any]:
        """Fence a lost running job; never retry its provider automatically."""
        return self._stop(owner, job_id, False)
