"""Cumulative trial guard across models/jobs. Registration grants no permission."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import ACTIVE, AdmissionError, GenerationAdmission, _digest
from src.workspace.store import WorkspaceStore

LIMITS: dict[str, Any] = {"messages": 16, "counts": 20, "usd": "1.25", "concurrency": 1}
PROGRAM_LIMITS: dict[str, Any] = {
    "new_jobs": 20,
    "messages": 80,
    "counts": 80,
    "usd": "10",
    "concurrency": 1,
}


def census(
    conn: Any, owner: str, *, members: list[str] | None = None, job_ids: list[str] | None = None
) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT j.id,j.state,j.data,r.amount,r.workflow,r.judge,r.unknown "
        "FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id "
        "WHERE j.owner=ANY(%s)"
        + (" AND j.id=ANY(%s)" if job_ids is not None else "")
        + " ORDER BY j.id",
        (members or [owner], job_ids) if job_ids is not None else (members or [owner],),
    ).fetchall()
    contacts = [c for _, _, d, *_ in rows for c in d.get("adapter", {}).get("contacts", [])]
    if any(c.get("endpoint") not in {"messages", "messages/count_tokens"} for c in contacts):
        raise AdmissionError("unrecognized_trial_contact")
    known = sum((w + j for _, _, _, _, w, j, _ in rows), Decimal(0))
    pending = sum(
        (max(u, a - w - j) if state in ACTIVE else u for _, state, _, a, w, j, u in rows),
        Decimal(0),
    )
    return {
        "messages": sum(c["endpoint"] == "messages" for c in contacts),
        "counts": sum(c["endpoint"] == "messages/count_tokens" for c in contacts),
        "known_usd": str(known),
        "pending_usd": str(pending),
        "active_jobs": [i for i, state, *_ in rows if state in {"reserved", "running"}],
        "uncertain_contacts": any(c.get("state") in {"running", "dispatching"} for c in contacts),
        "unknown_usd": str(sum((u for *_, u in rows), Decimal(0))),
        "generation_job_ids": [i for i, _, _, amount, *_ in rows if amount > 0],
        "models": sorted({d["sealed_input"]["model_id"] for _, _, d, *_ in rows}),
        "contact_checkpoints": {
            i: {
                "length": len(d.get("adapter", {}).get("contacts", [])),
                "digest": _digest(d.get("adapter", {}).get("contacts", [])),
            }
            for i, _, d, *_ in rows
        },
        "history_digest": _digest(
            [[i, state, d, str(a), str(w), str(j), str(u)] for i, state, d, a, w, j, u in rows]
        ),
    }


def register_trial(
    store: WorkspaceStore, owner: str, trial_id: str, expected_history_digest: str
) -> dict[str, Any]:
    """One immutable ledger per principal; cannot reset counts by changing IDs."""
    store.migrate()
    control = GenerationAdmission(store)
    with store.pool.connection() as conn:
        control._lock(conn, owner)
        history = census(conn, owner)
        if history["history_digest"] != expected_history_digest:
            raise AdmissionError("trial_history_drift")
        existing = conn.execute(
            "SELECT trial_id,limits,baseline_digest FROM workspace_qualification_trials WHERE owner=%s",
            (owner,),
        ).fetchone()
        if existing:
            if existing != (trial_id, LIMITS, expected_history_digest):
                raise AdmissionError("trial_identity_or_limits_immutable")
        else:
            conn.execute(
                "INSERT INTO workspace_qualification_trials(trial_id,owner,limits,baseline_digest) VALUES (%s,%s,%s,%s)",
                (trial_id, owner, Jsonb(LIMITS), expected_history_digest),
            )
        return {
            "trial_id": trial_id,
            "limits": LIMITS,
            "baseline": history,
            "approval_created": False,
        }


def register_program(
    store: WorkspaceStore,
    owner: str,
    program_id: str,
    parent_trial_id: str,
    authorization_digest: str,
    expected_history_digest: str,
) -> dict[str, Any]:
    """Bind the new explicit scope to historical accounting, not new permission."""
    if len(authorization_digest) != 64 or not program_id.strip():
        raise AdmissionError("program_authorization_identity_required")
    store.migrate()
    with store.pool.connection() as conn:
        GenerationAdmission(store)._lock(conn, owner)
        parent = conn.execute(
            "SELECT owner FROM workspace_qualification_trials WHERE trial_id=%s", (parent_trial_id,)
        ).fetchone()
        if not parent or parent[0] != owner:
            raise AdmissionError("historical_trial_link_required")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + program_id,)
        )
        history = census(conn, owner)
        if history["history_digest"] != expected_history_digest:
            raise AdmissionError("program_history_drift")
        existing = conn.execute(
            "SELECT parent_trial_id,limits,baseline,authorization_digest FROM workspace_evaluation_programs WHERE program_id=%s",
            (program_id,),
        ).fetchone()
        if existing:
            if (existing[0], existing[1], existing[3]) != (
                parent_trial_id,
                PROGRAM_LIMITS,
                authorization_digest,
            ):
                raise AdmissionError("evaluation_program_immutable")
            return {
                "program_id": program_id,
                "baseline": existing[2],
                "limits": existing[1],
                "approval_created": False,
            }
        member = conn.execute(
            "SELECT program_id FROM workspace_evaluation_members WHERE owner=%s", (owner,)
        ).fetchone()
        if member:
            raise AdmissionError("principal_already_bound_to_program")
        conn.execute(
            "INSERT INTO workspace_evaluation_programs(program_id,parent_trial_id,limits,baseline,authorization_digest) VALUES (%s,%s,%s,%s,%s)",
            (
                program_id,
                parent_trial_id,
                Jsonb(PROGRAM_LIMITS),
                Jsonb(history),
                authorization_digest,
            ),
        )
        conn.execute("INSERT INTO workspace_evaluation_members VALUES (%s,%s)", (owner, program_id))
        return {
            "program_id": program_id,
            "baseline": history,
            "limits": PROGRAM_LIMITS,
            "approval_created": False,
        }


def add_program_member(store: WorkspaceStore, program_id: str, owner: str) -> None:
    """An empty isolated principal can join; pre-existing spend cannot disappear."""
    store._owner(owner)
    with store.pool.connection() as conn:
        GenerationAdmission(store)._lock(conn, owner)
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + program_id,)
        )
        if not conn.execute(
            "SELECT program_id FROM workspace_evaluation_programs WHERE program_id=%s",
            (program_id,),
        ).fetchone():
            raise AdmissionError("evaluation_program_required")
        if conn.execute(
            "SELECT 1 FROM workspace_generation_jobs WHERE owner=%s", (owner,)
        ).fetchone():
            raise AdmissionError("nonempty_principal_requires_accounting_import")
        prior = conn.execute(
            "SELECT program_id FROM workspace_evaluation_members WHERE owner=%s", (owner,)
        ).fetchone()
        if prior and prior[0] != program_id:
            raise AdmissionError("principal_already_bound_to_program")
        if not prior:
            conn.execute(
                "INSERT INTO workspace_evaluation_members VALUES (%s,%s)", (owner, program_id)
            )


def guard_program(
    conn: Any,
    owner: str,
    policy: dict[str, Any],
    *,
    reserve_usd: Decimal | None,
    current_job: str | None,
    next_endpoint: str | None,
    reserve_operation: str = "workflow",
) -> dict[str, Any]:
    if (
        reserve_operation not in {"workflow", "probe", "measurement"}
        or (
            reserve_operation != "workflow"
            and policy.get("purpose") != "workspace-d5-qualification-only"
        )
        or (reserve_operation == "measurement" and reserve_usd not in {None, Decimal("0")})
    ):
        raise AdmissionError("program_sealed_operation_capacity_required")
    message_capacity, count_capacity = {"workflow": (4, 4), "probe": (1, 1), "measurement": (0, 1)}[
        reserve_operation
    ]
    program = policy["program_id"]
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + program,))
    row = conn.execute(
        "SELECT p.limits,p.baseline,p.authorization_digest FROM workspace_evaluation_programs p "
        "JOIN workspace_evaluation_members m USING(program_id) WHERE m.owner=%s AND p.program_id=%s FOR UPDATE OF p",
        (owner, program),
    ).fetchone()
    if not row or row[0] != PROGRAM_LIMITS or row[2] != policy.get("program_authorization_digest"):
        raise AdmissionError("cumulative_evaluation_program_required")
    members = [
        m[0]
        for m in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program,)
        ).fetchall()
    ]
    from src.workspace.programme_amendments import effective_limits

    limits = effective_limits(
        conn, program, required_proposal_digest=policy.get("program_amendment_proposal_digest")
    )
    _, baseline, _ = row
    report = census(conn, owner, members=members)
    for job_id, checkpoint in baseline["contact_checkpoints"].items():
        prior = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s AND owner=ANY(%s)",
            (job_id, members),
        ).fetchone()
        if (
            not prior
            or _digest(prior[0].get("adapter", {}).get("contacts", [])[: checkpoint["length"]])
            != checkpoint["digest"]
        ):
            raise AdmissionError("evaluation_historical_contacts_changed")
    if not set(baseline["generation_job_ids"]) <= set(report["generation_job_ids"]) or Decimal(
        report["known_usd"]
    ) < Decimal(baseline["known_usd"]):
        raise AdmissionError("evaluation_history_missing")
    report["new_messages"] = report["messages"] - baseline["messages"]
    report["new_counts"] = report["counts"] - baseline["counts"]
    report["new_jobs"] = len(
        set(report["generation_job_ids"]) - set(baseline["generation_job_ids"])
    )
    if report["new_messages"] < 0 or report["new_counts"] < 0:
        raise AdmissionError("evaluation_history_missing")
    if any(j != current_job for j in report["active_jobs"]):
        raise AdmissionError("program_one_job_at_a_time")
    if (
        report["messages"] + (next_endpoint == "messages") > limits["messages"]
        or report["counts"] + (next_endpoint == "messages/count_tokens") > limits["counts"]
    ):
        raise AdmissionError("program_contact_cap_exceeded")
    if reserve_usd is not None:
        if report["uncertain_contacts"] or Decimal(report["unknown_usd"]):
            raise AdmissionError("program_external_completion_uncertain")
        if reserve_usd > 0 and report["new_jobs"] >= limits["new_jobs"]:
            raise AdmissionError("program_job_cap_exceeded")
        if (
            report["messages"] + message_capacity > limits["messages"]
            or report["counts"] + count_capacity > limits["counts"]
        ):
            raise AdmissionError("program_check_recheck_capacity_required")
    if Decimal(report["known_usd"]) + Decimal(report["pending_usd"]) + (reserve_usd or 0) > Decimal(
        limits["usd"]
    ):
        raise AdmissionError("cumulative_program_cost_cap_exceeded")
    return report


def guard(
    conn: Any,
    owner: str,
    policy: dict[str, Any],
    *,
    reserve_usd: Decimal | None = None,
    current_job: str | None = None,
    next_endpoint: str | None = None,
    reserve_operation: str = "workflow",
) -> dict[str, Any] | None:
    # Old mock fixtures without a trial remain test-only. Provider dispatch and
    # any explicitly registered mock trial always require the cumulative ledger.
    membership = conn.execute(
        "SELECT program_id FROM workspace_evaluation_members WHERE owner=%s", (owner,)
    ).fetchone()
    if membership and policy.get("program_id") != membership[0]:
        raise AdmissionError("program_bound_principal_requires_program_policy")
    if policy.get("program_id"):
        return guard_program(
            conn,
            owner,
            policy,
            reserve_usd=reserve_usd,
            current_job=current_job,
            next_endpoint=next_endpoint,
            reserve_operation=reserve_operation,
        )
    if policy.get("transport_mode") != "provider" and not policy.get("trial_id"):
        return None
    row = conn.execute(
        "SELECT trial_id,limits FROM workspace_qualification_trials WHERE owner=%s FOR UPDATE",
        (owner,),
    ).fetchone()
    if not row or row[0] != policy.get("trial_id") or row[1] != LIMITS:
        raise AdmissionError("cumulative_trial_required")
    report = census(conn, owner)
    if any(i != current_job for i in report["active_jobs"]):
        raise AdmissionError("trial_one_job_at_a_time")
    if report["messages"] > LIMITS["messages"] or report["counts"] > LIMITS["counts"]:
        raise AdmissionError("trial_contact_cap_exceeded")
    if (
        report["messages"] + (next_endpoint == "messages") > LIMITS["messages"]
        or report["counts"] + (next_endpoint == "messages/count_tokens") > LIMITS["counts"]
    ):
        raise AdmissionError("trial_contact_cap_exceeded")
    if reserve_usd is not None:
        if report["uncertain_contacts"] or Decimal(report["unknown_usd"]):
            raise AdmissionError("trial_external_completion_uncertain")
        # Reserve draft/check/repair/recheck capacity before admitting the job.
        if report["messages"] + 4 > LIMITS["messages"] or report["counts"] + 4 > LIMITS["counts"]:
            raise AdmissionError("trial_check_recheck_capacity_required")
    if Decimal(report["known_usd"]) + Decimal(report["pending_usd"]) + (reserve_usd or 0) > Decimal(
        LIMITS["usd"]
    ):
        raise AdmissionError("cumulative_trial_cost_cap_exceeded")
    return report
