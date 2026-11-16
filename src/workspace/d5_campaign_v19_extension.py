"""Prospective append-only v19 authority. No provider contacts or implicit grant."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, TypeGuard, cast

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.qualification_budget import census

REVISION = "programme-comparison-contract-successor-v19"
PROGRAM_ID = "research-evaluation-20261105-v1"
PROGRAMME_EXPIRY = "2026-11-21T11:03:57+00:00"
SNAPSHOT_DIGEST = "a767c3c158763f99acc58be2555559aa2668f430959c76421f9226e110d2beb8"
PARENT_DIGEST = "e04732bb950b9a1d173aefe6efec97bf8ae19ab917d5186c8d2d1f1f1605013a"
PARENT_SCOPE_DIGEST = "a2a9a4417afd3a34391049a1544c3ff026397ef7ed1e3406dba170df2c65ed4b"
SCOPE_DIGEST = "d484636d4c109efa582ee2d5546c497efe1348d82f4151f5a759d4b6cd03ab7b"
HISTORY_DIGEST = "5c8f1ad418a4903d73ad5cf1544551f41e24443b29b51a61579f1278657f9b79"
BASIS_MEMBERS_DIGEST = "606d6bdb063d3a8bf3056842e0237e173f38fb1362b0d7422eeaa61b99439afe"
HOLDS_DIGEST = "a0b28c5adb2a224a499af5a69d984b8a8bd2bbd057d51c2a4b729c4851f799bd"
SCOPE_ID = "compat-fa06446ac6cb32e6a4bd0eca"
LIMITS = {"new_jobs": 64, "messages": 160, "counts": 200, "usd": "22", "concurrency": 1}
PERIOD_LIMITS = {"day_usd": "22", "month_usd": "22"}
CAMPAIGN_LIMITS = {
    "jobs": 14,
    "messages": 44,
    "counts": 44,
    "usd": "22",
    "new_usd": "14.00",
    "workflow_usd": "1.20",
    "probe_usd": "0.50",
    "headroom_usd": "2.00",
    "concurrency": 1,
}
EXPIRY_POLICY = {
    "programme_expires_at": PROGRAMME_EXPIRY,
    "campaign_max_seconds_from_approval": 86400,
    "programme_renewal": False,
}


def _fail() -> None:
    raise AdmissionError("campaign_v19_binding_or_census_drift")


def proposal(
    conn: Any, program_id: str, plan_digest: str, snapshot: dict[str, Any]
) -> dict[str, Any]:
    if (
        program_id != PROGRAM_ID
        or not isinstance(plan_digest, str)
        or not plan_digest.strip()
        or _digest(snapshot) != SNAPSHOT_DIGEST
    ):
        _fail()
    parent = snapshot["programme"]
    scopes = [s for s in snapshot["historical_scopes"] if s["scope_id"] == SCOPE_ID]
    history = snapshot["history"]
    if (
        _digest(parent) != PARENT_DIGEST
        or len(scopes) != 1
        or _digest(scopes[0]) != SCOPE_DIGEST
        or _digest(history) != HISTORY_DIGEST
        or len(
            set(history["generation_job_ids"])
            - set(snapshot["programme_baseline"]["generation_job_ids"])
        )
        != 46
        or len(snapshot["retained_liabilities"]) != 4
    ):
        _fail()
    core = {
        "revision": REVISION,
        "extension_id": program_id + "-comparison-v19",
        "program_id": program_id,
        "parent": {
            "extension_id": parent["extension_id"],
            "authorization_digest": parent["authorization_digest"],
            "row_digest": PARENT_DIGEST,
        },
        "stopped_v18_scope": {"scope_id": SCOPE_ID, "row_digest": SCOPE_DIGEST},
        "snapshot_digest": SNAPSHOT_DIGEST,
        "basis_members": deepcopy(snapshot["members"]),
        "basis": deepcopy(history),
        "retained_exceptions": deepcopy(snapshot["retained_liabilities"]),
        "limits": deepcopy(LIMITS),
        "period_limits": deepcopy(PERIOD_LIMITS),
        "campaign_limits": deepcopy(CAMPAIGN_LIMITS),
        "plan_digest": plan_digest,
        "programme_expiry": PROGRAMME_EXPIRY,
        "expiry_policy": deepcopy(EXPIRY_POLICY),
        "liability_policy": "Four named holds retained exactly once; no settlement or replay; stop on new uncertainty.",
    }
    value = {"core": core, "proposal_digest": _digest(core), "approved": False}
    validate_proposal(conn, value)
    return value


def _predecessor_seal(conn: Any) -> dict[str, Any]:
    from src.workspace.d5_campaign_extension import predecessor_seal

    return predecessor_seal(conn, PROGRAM_ID)


def _audit_campaign_ancestors(conn: Any, parent: dict[str, Any]) -> None:
    """Read exact v15/v14/v13 closed scopes and inherited receipt/revocation rows.

    This verifies retained identities without reviving expired predecessors or
    invoking their obsolete two-hold census. Base amendment ancestors are
    independently checked by _predecessor_seal on every validation.
    """
    from psycopg import sql

    try:
        scope = conn.execute(
            "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
            (parent["scope_id"],),
        ).fetchone()
        if (
            not scope
            or _digest(scope[0]) != PARENT_SCOPE_DIGEST
            or scope[0].get("state") != "stopped"
            or scope[0].get("packet_digest") != parent["packet_digest"]
            or scope[0].get("authorization_digest") != parent["authorization_digest"]
        ):
            raise AdmissionError("campaign_v19_parent_stopped_scope_drift")
        binding = parent["record"]["campaign_extension"]["core"]["parent"]
        for table, revocations in (
            ("workspace_d5_campaign_successors", "workspace_d5_campaign_successor_revocations"),
            ("workspace_d5_campaign_extensions", "workspace_d5_campaign_revocations"),
        ):
            row = conn.execute(
                sql.SQL("SELECT to_jsonb(t) FROM {} t WHERE program_id=%s").format(
                    sql.Identifier(table)
                ),
                (PROGRAM_ID,),
            ).fetchone()
            if not row or _digest(row[0]) != binding["row_digest"]:
                raise AdmissionError("campaign_v19_campaign_ancestor_row_drift")
            actual = row[0]
            scope = conn.execute(
                "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
                (binding["scope_id"],),
            ).fetchone()
            revoked = conn.execute(
                sql.SQL("SELECT 1 FROM {} WHERE extension_id=%s").format(
                    sql.Identifier(revocations)
                ),
                (actual["extension_id"],),
            ).fetchone()
            if (
                actual.get("program_id") != PROGRAM_ID
                or actual.get("scope_id") != binding["scope_id"]
                or not scope
                or _digest(scope[0]) != binding["stopped_scope_digest"]
                or scope[0].get("state") != "stopped"
                or scope[0].get("packet_digest") != actual.get("packet_digest")
                or scope[0].get("authorization_digest") != actual.get("authorization_digest")
                or revoked
            ):
                raise AdmissionError("campaign_v19_campaign_ancestor_scope_or_revocation_drift")
            binding = actual["record"]["campaign_extension"]["core"]["parent"]
    except (KeyError, TypeError) as exc:
        raise AdmissionError("campaign_v19_campaign_ancestor_binding_missing") from exc


def _expected_receipt_bindings() -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_campaign_v19_packet import predecessor
    from src.workspace.d5_freeze import code_bindings

    old = predecessor()
    return {
        "code_bindings": code_bindings(),
        "adapter_binding": qualification_producer(),
        "source_bindings": old["source_bindings"],
        "case_order": old["schedule"],
    }


def _sha256(value: Any) -> TypeGuard[str]:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def validate_proposal(conn: Any, value: dict[str, Any], *, fresh: bool = True) -> dict[str, Any]:
    core = value.get("core", {})
    if (
        value.get("approved") is not False
        or value.get("proposal_digest") != _digest(core)
        or core.get("revision") != REVISION
        or core.get("program_id") != PROGRAM_ID
        or core.get("extension_id") != PROGRAM_ID + "-comparison-v19"
        or core.get("snapshot_digest") != SNAPSHOT_DIGEST
        or core.get("limits") != LIMITS
        or core.get("period_limits") != PERIOD_LIMITS
        or core.get("campaign_limits") != CAMPAIGN_LIMITS
        or core.get("programme_expiry") != PROGRAMME_EXPIRY
        or core.get("expiry_policy") != EXPIRY_POLICY
        or not isinstance(core.get("plan_digest"), str)
        or not core["plan_digest"].strip()
    ):
        _fail()
    parent = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_capacity_revisions t WHERE program_id=%s AND extension_id=%s",
        (PROGRAM_ID, PROGRAM_ID + "-capacity-v15"),
    ).fetchone()
    stopped = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s", (SCOPE_ID,)
    ).fetchone()
    if (
        not parent
        or _digest(parent[0]) != PARENT_DIGEST
        or not stopped
        or _digest(stopped[0]) != SCOPE_DIGEST
        or core.get("parent")
        != {
            "extension_id": parent[0]["extension_id"],
            "authorization_digest": parent[0]["authorization_digest"],
            "row_digest": PARENT_DIGEST,
        }
        or core.get("stopped_v18_scope") != {"scope_id": SCOPE_ID, "row_digest": SCOPE_DIGEST}
        or conn.execute(
            "SELECT 1 FROM workspace_d5_capacity_revision_revocations WHERE extension_id=%s",
            (parent[0]["extension_id"],),
        ).fetchone()
    ):
        _fail()
    try:
        retained_seal = parent[0]["record"]["campaign_extension"]["core"]["parent"][
            "predecessor_seal"
        ]
    except (KeyError, TypeError) as exc:
        raise AdmissionError("campaign_v19_predecessor_binding_missing") from exc
    _audit_campaign_ancestors(conn, parent[0])
    if _predecessor_seal(conn) != retained_seal:
        raise AdmissionError("campaign_v19_predecessor_or_revocation_drift")
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (PROGRAM_ID,)
        )
    )
    prior_members = core.get("basis_members", [])
    if (
        _digest(prior_members) != BASIS_MEMBERS_DIGEST
        or sorted(set(prior_members)) != prior_members
        or not set(prior_members).issubset(members)
        or (fresh and members != prior_members)
    ):
        _fail()
    basis = core.get("basis", {})
    if _digest(basis) != HISTORY_DIGEST:
        _fail()
    actual = census(
        conn,
        prior_members[0],
        members=prior_members,
        job_ids=None if fresh else sorted(basis["contact_checkpoints"]),
    )
    if actual != basis:
        _fail()
    holds = [
        dict(
            job_id=r[0],
            owner=r[1],
            state=r[2],
            amount=r[3],
            unknown=r[4],
            data_digest=_digest(r[5]),
        )
        for r in conn.execute(
            "SELECT j.id,j.owner,j.state,r.amount::text,r.unknown::text,j.data FROM workspace_generation_jobs j JOIN workspace_spend_reservations r ON r.job_id=j.id WHERE j.owner=ANY(%s) AND r.unknown>0 ORDER BY j.id",
            (prior_members,),
        )
    ]
    if (
        _digest(holds) != HOLDS_DIGEST
        or holds != core.get("retained_exceptions")
        or len(holds) != 4
        or sum(Decimal(h["unknown"]) for h in holds) != Decimal("2.275066")
    ):
        _fail()
    return cast(dict[str, Any], core)


def _validate_receipt(conn: Any, receipt: dict[str, Any], *, fresh: bool) -> dict[str, Any]:
    core = validate_proposal(conn, receipt.get("campaign_extension", {}), fresh=fresh)
    try:
        start, expiry, end = (
            datetime.fromisoformat(receipt[k])
            for k in ("approved_at", "expires_at", "programme_expires_at")
        )
        valid = (
            all(t.tzinfo and t.utcoffset() == timedelta(0) for t in (start, expiry, end))
            and start <= datetime.now(UTC) < expiry <= min(start + timedelta(hours=24), end)
            and end.isoformat() == PROGRAMME_EXPIRY
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    fixture = bool(conn.execute("SELECT to_regclass('workspace_d5_fixture_marker')").fetchone()[0])
    if fixture:
        fixture = bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())
    import os

    allowed_identity = (
        not fixture
        and receipt.get("authorization_kind") == "owner"
        and receipt.get("transport_mode") == "provider"
    ) or (
        fixture
        and receipt.get("authorization_kind") == "offline_fixture"
        and receipt.get("transport_mode") == "mock"
        and os.environ.get("WORKSPACE_D5_OFFLINE") == "1"
        and os.environ.get("ANTHROPIC_API_KEY") == "local-preview-disabled"
    )
    expected = _expected_receipt_bindings()
    packet_digest = receipt.get("packet_digest")
    binding_identity = (
        _sha256(packet_digest)
        and _sha256(core.get("plan_digest"))
        and _sha256(receipt.get("case_bindings_digest"))
        and receipt.get("scope_id") == "d5-" + packet_digest[:24]
        and receipt.get("members") == ["d5-campaign-" + packet_digest[:16] + "-run"]
        and all(receipt.get(key) == value for key, value in expected.items())
    )
    if (
        receipt.get("approved") is not True
        or not allowed_identity
        or not binding_identity
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or not isinstance(receipt.get("approval_source"), str)
        or not receipt["approval_source"].strip()
        or receipt.get("budget_adjustment_approved") is not True
        or receipt.get("historical_uncertainty_exception_approved") is not True
        or receipt.get("limits") != CAMPAIGN_LIMITS
        or receipt.get("programme_limits") != LIMITS
        or receipt.get("period_limits") != PERIOD_LIMITS
        or receipt.get("stages") != ["B", "C", "D"]
        or len(receipt.get("case_order", [])) != 14
        or len(set(receipt["case_order"])) != 14
        or not receipt.get("packet_digest")
        or not receipt.get("scope_id")
        or not valid
    ):
        raise AdmissionError("campaign_v19_external_owner_authorization_required")
    return core


def _verify_packet_receipt(packet: dict[str, Any] | None, receipt: dict[str, Any]) -> None:
    """The external writer needs the real packet, not caller-asserted digests."""
    from src.workspace.d5_campaign_operator import template

    if (
        not isinstance(packet, dict)
        or packet.get("revision") != "d5-comparison-machine-campaign-v19"
    ):
        raise AdmissionError("campaign_v19_verified_frozen_packet_required")
    expected = template(packet)
    operator_fields = {
        "approved",
        "approved_by",
        "approved_at",
        "approval_source",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "budget_adjustment_approved",
        "historical_uncertainty_exception_approved",
    }
    if set(receipt) != set(expected) or any(
        receipt[k] != expected[k] for k in expected if k not in operator_fields
    ):
        raise AdmissionError("campaign_v19_exact_packet_receipt_binding_required")


def record_external(
    store: Any, receipt: dict[str, Any], *, packet: dict[str, Any] | None = None
) -> dict[str, Any]:
    if receipt.get("approved") is not True:
        raise AdmissionError("campaign_v19_explicit_owner_approval_required")
    _verify_packet_receipt(packet, receipt)
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + PROGRAM_ID,)
        )
        digest = _digest(receipt)
        prior = conn.execute(
            "SELECT authorization_digest FROM workspace_d5_keyed_continuations WHERE extension_id=%s",
            (PROGRAM_ID + "-comparison-v19",),
        ).fetchone()
        if prior:
            if prior[0] != digest:
                raise AdmissionError("campaign_v19_immutable_or_revoked")
            # Validate the persisted row, its unchanged expiry and every safety
            # binding. Re-recording is idempotent after metered progress, never
            # a new grant or a renewal based on a different approval timestamp.
            found = active(
                conn, PROGRAM_ID, receipt.get("campaign_extension", {}).get("proposal_digest")
            )
            if found is None or found[0] != receipt:
                raise AdmissionError("campaign_v19_immutable_or_revoked")
            return {"authorization_digest": digest, "duplicate": True}
        core = _validate_receipt(conn, receipt, fresh=True)
        conn.execute(
            "INSERT INTO workspace_d5_keyed_continuations(program_id,revision,extension_id,predecessor_extension_id,predecessor_authorization_digest,proposal_digest,authorization_digest,packet_digest,scope_id,record,expires_at,programme_expires_at) VALUES(%s,8,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                PROGRAM_ID,
                core["extension_id"],
                core["parent"]["extension_id"],
                core["parent"]["authorization_digest"],
                receipt["campaign_extension"]["proposal_digest"],
                digest,
                receipt["packet_digest"],
                receipt["scope_id"],
                Jsonb(receipt),
                datetime.fromisoformat(receipt["expires_at"]),
                datetime.fromisoformat(PROGRAMME_EXPIRY),
            ),
        )
    return {
        "authorization_digest": digest,
        "limits": deepcopy(LIMITS),
        "period_limits": deepcopy(PERIOD_LIMITS),
        "retained_liability_usd": "2.275066",
        "financial_rows_changed": False,
        "provider_contacts": 0,
    }


def active(
    conn: Any, program_id: str, required: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if program_id != PROGRAM_ID:
        return None
    if not conn.execute("SELECT to_regclass('workspace_d5_keyed_continuations')").fetchone()[0]:
        return None
    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id,expires_at,programme_expires_at,predecessor_extension_id,predecessor_authorization_digest FROM workspace_d5_keyed_continuations WHERE extension_id=%s",
        (PROGRAM_ID + "-comparison-v19",),
    ).fetchone()
    if not row or required is not None and required != row[2]:
        return None
    receipt, digest, pdigest, packet, scope, expiry, end, parent, parent_auth = row
    core = _validate_receipt(conn, receipt, fresh=False)
    if (
        _digest(receipt) != digest
        or receipt["campaign_extension"]["proposal_digest"] != pdigest
        or receipt["packet_digest"] != packet
        or receipt["scope_id"] != scope
        or datetime.fromisoformat(receipt["expires_at"]) != expiry
        or datetime.fromisoformat(PROGRAMME_EXPIRY) != end
        or core["parent"]["extension_id"] != parent
        or core["parent"]["authorization_digest"] != parent_auth
        or conn.execute(
            "SELECT 1 FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
            (core["extension_id"],),
        ).fetchone()
    ):
        raise AdmissionError("campaign_v19_revoked_or_receipt_drift")
    return receipt, core


def guard_exception(
    conn: Any,
    policy: dict[str, Any],
    found: tuple[dict[str, Any], dict[str, Any]],
    current_job: str | None,
) -> dict[str, Any]:
    receipt, core = found
    if policy.get("d5_scope_id") != receipt["scope_id"] or policy.get(
        "d5_authorization_digest"
    ) != _digest(receipt):
        raise AdmissionError("campaign_v19_exception_scope_mismatch")
    excluded = [item["job_id"] for item in core["retained_exceptions"]]
    members = [
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (PROGRAM_ID,)
        )
    ]
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM workspace_generation_jobs WHERE owner=ANY(%s) AND NOT(id=ANY(%s))",
            (members, excluded),
        )
    ]
    rest = census(conn, members[0], members=members, job_ids=ids)
    contacts = conn.execute(
        "SELECT j.id,j.state,c.value->>'state' FROM workspace_generation_jobs j CROSS JOIN LATERAL jsonb_array_elements(COALESCE(j.data->'adapter'->'contacts','[]')) c WHERE j.owner=ANY(%s) AND NOT(j.id=ANY(%s)) AND c.value->>'state' IN('running','dispatching')",
        (members, excluded),
    )
    if Decimal(rest["unknown_usd"]) or any(
        state == "dispatching" or jid != current_job or job_state != "running"
        for jid, job_state, state in contacts
    ):
        raise AdmissionError("campaign_v19_new_external_uncertainty")
    return {
        "retained_exceptions": core["retained_exceptions"],
        "retained_liability_usd": "2.275066",
        "settled": False,
    }
