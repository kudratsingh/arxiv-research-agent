"""Append-only, unapproved v20 continuation on the unchanged programme envelope.

Historical grants are audited as immutable ancestors, never renewed. Only the
operator with an exact externally approved packet may insert a new scope receipt.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_continuation_policy import (
    CASE_MAP,
    LIMITS,
    PERIOD_LIMITS,
    PROGRAM_LIMITS,
    PROGRAMME_EXPIRY,
    REVISION,
)
from src.workspace.qualification_budget import census

PROGRAM_ID = "research-evaluation-20261105-v1"
EXTENSION_ID = PROGRAM_ID + "-behavior-v20"
AUTHORITY_REVISION = "programme-behavior-continuation-v20"
SNAPSHOT_DIGEST = "c6469eb57e44aec05237225198e0da266df15e3e187ce6cc4e8292d0535a776e"
PARENT_SCOPE = "d5-00cc2c78e66fcc58c16a5afc"
PARENT_ROW = "f521d303ec1237c675a6258dcde0eb806963b95b3e49ee053d07a31b5ad0ebff"
PARENT_SCOPE_ROW = "1d9317ff9d151c798dcf826bc37f5f384b24e46446a7b2bd9d6851d26fe48936"
HISTORY_DIGEST = "6d9d84152c62f465b86dd3c239583563e22db5c7d12a9aadef755225035ffe34"
MEMBERS_DIGEST = "d082b73cc6a0f55c47cf55bd9b3d87ac643cbe633e320dad80a585814b06ac3e"
HOLDS_DIGEST = "a0b28c5adb2a224a499af5a69d984b8a8bd2bbd057d51c2a4b729c4851f799bd"


def proposal(
    conn: Any, program_id: str, plan_digest: str, snapshot: dict[str, Any]
) -> dict[str, Any]:
    if program_id != PROGRAM_ID or _digest(snapshot) != SNAPSHOT_DIGEST:
        raise AdmissionError("continuation_exact_52_101_126_snapshot_required")
    parent = next(
        (r for r in snapshot["recorded_keyed_continuations"] if r["scope_id"] == PARENT_SCOPE), None
    )
    if not parent or _digest(parent) != PARENT_ROW:
        raise AdmissionError("continuation_exact_stopped_v19_parent_required")
    core = {
        "revision": AUTHORITY_REVISION,
        "extension_id": EXTENSION_ID,
        "program_id": program_id,
        "parent_v19": {
            "extension_id": parent["extension_id"],
            "authorization_digest": parent["authorization_digest"],
            "row_digest": PARENT_ROW,
            "scope_id": PARENT_SCOPE,
            "scope_row_digest": PARENT_SCOPE_ROW,
        },
        "capacity_ancestor": {
            "extension_id": snapshot["programme"]["extension_id"],
            "authorization_digest": snapshot["programme"]["authorization_digest"],
            "row_digest": _digest(snapshot["programme"]),
        },
        "snapshot_digest": SNAPSHOT_DIGEST,
        "basis_members": snapshot["members"],
        "basis": snapshot["history"],
        "retained_exceptions": snapshot["retained_liabilities"],
        "limits": PROGRAM_LIMITS,
        "period_limits": PERIOD_LIMITS,
        "campaign_limits": LIMITS,
        "plan_digest": plan_digest,
        "programme_expiry": PROGRAMME_EXPIRY,
        "expiry_policy": {"campaign_max_seconds_from_approval": 86400, "programme_renewal": False},
        "capacity_change": False,
        "budget_change": False,
    }
    value = {"core": core, "proposal_digest": _digest(core), "approved": False}
    validate_proposal(conn, value, fresh=True)
    return value


def validate_proposal(conn: Any, value: dict[str, Any], *, fresh: bool) -> dict[str, Any]:
    core = value.get("core", {})
    if (
        value.get("approved") is not False
        or value.get("proposal_digest") != _digest(core)
        or core.get("revision") != AUTHORITY_REVISION
        or core.get("extension_id") != EXTENSION_ID
        or core.get("program_id") != PROGRAM_ID
        or core.get("snapshot_digest") != SNAPSHOT_DIGEST
        or core.get("limits") != PROGRAM_LIMITS
        or core.get("period_limits") != PERIOD_LIMITS
        or core.get("campaign_limits") != LIMITS
        or core.get("programme_expiry") != PROGRAMME_EXPIRY
        or core.get("expiry_policy")
        != {"campaign_max_seconds_from_approval": 86400, "programme_renewal": False}
        or core.get("capacity_change") is not False
        or core.get("budget_change") is not False
        or not isinstance(core.get("plan_digest"), str)
        or len(core["plan_digest"]) != 64
    ):
        raise AdmissionError("continuation_proposal_policy_or_digest_drift")
    row = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_keyed_continuations t WHERE scope_id=%s",
        (PARENT_SCOPE,),
    ).fetchone()
    scope = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s", (PARENT_SCOPE,)
    ).fetchone()
    if (
        not row
        or _digest(row[0]) != PARENT_ROW
        or not scope
        or _digest(scope[0]) != PARENT_SCOPE_ROW
        or scope[0]["state"] != "stopped"
    ):
        raise AdmissionError("continuation_stopped_v19_receipt_drift")
    parent = row[0]
    if (
        _digest(parent["record"]) != parent["authorization_digest"]
        or core.get("parent_v19")
        != {
            "extension_id": parent["extension_id"],
            "authorization_digest": parent["authorization_digest"],
            "row_digest": PARENT_ROW,
            "scope_id": PARENT_SCOPE,
            "scope_row_digest": PARENT_SCOPE_ROW,
        }
        or conn.execute(
            "SELECT 1 FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
            (parent["extension_id"],),
        ).fetchone()
    ):
        raise AdmissionError("continuation_parent_revoked_or_unbound")
    # Audit the original 46-contact prefix, all ancestors and four holds without
    # invoking or renewing the now-stopped parent's time-limited execution grant.
    from src.workspace.d5_campaign_v19_extension import validate_proposal as prior_validate

    prior_validate(conn, parent["record"]["campaign_extension"], fresh=False)
    ancestor = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_capacity_revisions t WHERE extension_id=%s",
        (parent["predecessor_extension_id"],),
    ).fetchone()
    if not ancestor or core.get("capacity_ancestor") != {
        "extension_id": ancestor[0]["extension_id"],
        "authorization_digest": ancestor[0]["authorization_digest"],
        "row_digest": _digest(ancestor[0]),
    }:
        raise AdmissionError("continuation_programme_ancestor_drift")
    prior_members = core.get("basis_members", [])
    basis = core.get("basis", {})
    if (
        _digest(prior_members) != MEMBERS_DIGEST
        or _digest(basis) != HISTORY_DIGEST
        or _digest(core.get("retained_exceptions")) != HOLDS_DIGEST
    ):
        raise AdmissionError("continuation_historical_prefix_or_holds_drift")
    members = sorted(
        r[0]
        for r in conn.execute(
            "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (PROGRAM_ID,)
        )
    )
    if not set(prior_members).issubset(members) or fresh and members != prior_members:
        raise AdmissionError("continuation_member_baseline_drift")
    actual = census(
        conn,
        prior_members[0],
        members=prior_members,
        job_ids=None if fresh else sorted(basis["contact_checkpoints"]),
    )
    if actual != basis:
        raise AdmissionError("continuation_historical_financial_drift")
    return dict(core)


def _validate_receipt(conn: Any, receipt: dict[str, Any], *, fresh: bool) -> dict[str, Any]:
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_continuation_packet import producer_bindings
    from src.workspace.d5_freeze import code_bindings

    core = validate_proposal(conn, receipt.get("campaign_extension", {}), fresh=fresh)
    try:
        start, end = (datetime.fromisoformat(receipt[k]) for k in ("approved_at", "expires_at"))
        valid_time = all(
            t.tzinfo and t.utcoffset() == timedelta(0) for t in (start, end)
        ) and start <= datetime.now(UTC) < end <= min(
            start + timedelta(hours=24), datetime.fromisoformat(PROGRAMME_EXPIRY)
        )
    except (KeyError, TypeError, ValueError):
        valid_time = False
    fixture = bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())
    import os

    transport_ok = (
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
    digest = receipt.get("packet_digest")
    if (
        receipt.get("approved") is not True
        or not isinstance(receipt.get("approved_by"), str)
        or not receipt["approved_by"].strip()
        or not isinstance(receipt.get("approval_source"), str)
        or not receipt["approval_source"].strip()
        or receipt.get("campaign_revision") != REVISION
        or receipt.get("limits") != LIMITS
        or receipt.get("programme_limits") != PROGRAM_LIMITS
        or receipt.get("period_limits") != PERIOD_LIMITS
        or receipt.get("programme_expires_at") != PROGRAMME_EXPIRY
        or receipt.get("capacity_amendment_approved") is not False
        or receipt.get("budget_adjustment_approved") is not False
        or receipt.get("historical_uncertainty_exception_approved") is not True
        or receipt.get("code_bindings") != code_bindings()
        or receipt.get("adapter_binding") != qualification_producer()
        or receipt.get("continuation_producer") != producer_bindings()
        or receipt.get("case_order") != list(CASE_MAP)
        or receipt.get("stages") != ["B", "C", "D"]
        or not isinstance(digest, str)
        or len(digest) != 64
        or receipt.get("scope_id") != "d5-" + digest[:24]
        or receipt.get("members") != ["d5-continuation-" + digest[:16] + "-run"]
        or not transport_ok
        or not valid_time
    ):
        raise AdmissionError("continuation_exact_external_authorization_required")
    expected = receipt.get("source_bindings", {})
    actual = {
        label: {
            r[0]: _digest(r[1])
            for r in conn.execute(
                f"SELECT {key},data FROM {table} WHERE {key}=ANY(%s)",
                (list(expected.get(label, {})),),
            )
        }
        for label, table, key in (
            ("versions", "workspace_versions", "version_id"),
            ("materials", "workspace_material", "material_id"),
        )
    }
    if not expected.get("versions") or not expected.get("materials") or actual != expected:
        raise AdmissionError("continuation_source_bindings_drift")
    return core


def record_external(
    store: Any, receipt: dict[str, Any], *, packet: dict[str, Any]
) -> dict[str, Any]:
    from src.workspace.d5_continuation_packet import template

    expected = template(packet)
    mutable = {
        "approved",
        "approved_by",
        "approved_at",
        "approval_source",
        "expires_at",
        "authorization_kind",
        "transport_mode",
        "historical_uncertainty_exception_approved",
    }
    if set(expected) != set(receipt) or any(
        expected[k] != receipt[k] for k in expected if k not in mutable
    ):
        raise AdmissionError("continuation_exact_verified_packet_required")
    with store.pool.connection() as conn:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("evaluation:" + PROGRAM_ID,)
        )
        prior = conn.execute(
            "SELECT authorization_digest FROM workspace_d5_keyed_continuations WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()
        digest = _digest(receipt)
        if prior:
            found = active(conn, PROGRAM_ID, receipt["campaign_extension"]["proposal_digest"])
            if prior[0] != digest or found is None or found[0] != receipt:
                raise AdmissionError("continuation_immutable_no_renewal")
            return {"authorization_digest": digest, "duplicate": True, "provider_contacts": 0}
        core = _validate_receipt(conn, receipt, fresh=True)
        ancestor = core["capacity_ancestor"]
        conn.execute(
            "INSERT INTO workspace_d5_keyed_continuations(program_id,revision,extension_id,predecessor_extension_id,predecessor_authorization_digest,proposal_digest,authorization_digest,packet_digest,scope_id,record,expires_at,programme_expires_at) VALUES(%s,8,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                PROGRAM_ID,
                EXTENSION_ID,
                ancestor["extension_id"],
                ancestor["authorization_digest"],
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
        "duplicate": False,
        "provider_contacts": 0,
        "limits_unchanged": True,
        "historical_holds_retained_USD": "2.275066",
    }


def active(
    conn: Any, program_id: str, required: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if (
        program_id != PROGRAM_ID
        or not conn.execute("SELECT to_regclass('workspace_d5_keyed_continuations')").fetchone()[0]
    ):
        return None
    row = conn.execute(
        "SELECT record,authorization_digest,proposal_digest,packet_digest,scope_id,expires_at,programme_expires_at,predecessor_extension_id,predecessor_authorization_digest FROM workspace_d5_keyed_continuations WHERE extension_id=%s",
        (EXTENSION_ID,),
    ).fetchone()
    if not row or required is not None and required != row[2]:
        return None
    receipt, digest, pdigest, packet, scope, expiry, end, ancestor_id, ancestor_digest = row
    core = _validate_receipt(conn, receipt, fresh=False)
    if (
        _digest(receipt) != digest
        or receipt["campaign_extension"]["proposal_digest"] != pdigest
        or receipt["packet_digest"] != packet
        or receipt["scope_id"] != scope
        or datetime.fromisoformat(receipt["expires_at"]) != expiry
        or datetime.fromisoformat(PROGRAMME_EXPIRY) != end
        or ancestor_id != core["capacity_ancestor"]["extension_id"]
        or ancestor_digest != core["capacity_ancestor"]["authorization_digest"]
        or conn.execute(
            "SELECT 1 FROM workspace_d5_keyed_continuation_revocations WHERE extension_id=%s",
            (EXTENSION_ID,),
        ).fetchone()
    ):
        raise AdmissionError("continuation_revoked_or_receipt_corrupt")
    return receipt, core


def guard_exception(
    conn: Any,
    policy: dict[str, Any],
    found: tuple[dict[str, Any], dict[str, Any]],
    current_job: str | None,
) -> dict[str, Any]:
    from src.workspace.d5_campaign_v19_extension import guard_exception as inherited_guard

    return inherited_guard(conn, policy, found, current_job)
