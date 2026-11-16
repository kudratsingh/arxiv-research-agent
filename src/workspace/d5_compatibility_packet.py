"""Frozen small schema diagnostic. Offline construction grants no authority."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

from psycopg import sql

from src.llm import RequestProfile, _build_request_kwargs
from src.workspace import assistance_capacity_contract as capacity
from src.workspace import assistance_compact_encoding as codec
from src.workspace import assistance_keyed_checks as checker
from src.workspace import assistance_keyed_contract as keyed
from src.workspace.admission import AdmissionError, GenerationInput, SourceRef, _digest
from src.workspace.d5_adapter import checker_context
from src.workspace.d5_capacity_policy import POLICY, ROUTES
from src.workspace.material import SourceMaterial, SourceSpan

REVISION = "d5-provider-compatibility-diagnostic-v1"
SUCCESSOR_REVISION = "d5-consistency-compatibility-diagnostic-v18"
PROGRAM_ID = "research-evaluation-20261105-v1"
PROGRAM_LIMITS = {"jobs": 64, "messages": 160, "counts": 200, "USD": "20", "concurrency": 1}
LIMITS = {"jobs": 6, "messages": 6, "counts": 6, "new_USD": "1.80", "concurrency": 1}
EXPIRY = "2026-11-21T11:03:57Z"
ORDER = (
    "learn-accepted-control",
    "learn-list-control",
    "learn-compact",
    "research-compact",
    "checker-small",
    "checker-maximum",
)


def producer() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    files = [
        *sorted((root / "src").rglob("*.py")),
        root / "requirements-lock.txt",
        root / "pyproject.toml",
    ]
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def materials(packet: dict[str, Any]) -> tuple[SourceMaterial, ...]:
    return tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in packet["materials"]
    )


def order(packet: dict[str, Any]) -> tuple[str, ...]:
    if packet.get("revision") == SUCCESSOR_REVISION:
        from src.workspace.d5_consistency_packet import ORDER as successor_order
        return successor_order
    return ORDER


def allows_received_rejections(packet: dict[str, Any]) -> bool:
    return packet.get("revision") == REVISION


def verify(packet: dict[str, Any]) -> None:
    if packet.get("revision") == SUCCESSOR_REVISION:
        from src.workspace.d5_consistency_packet import verify as verify_successor
        verify_successor(packet)
        return
    if (
        packet.get("revision") != REVISION
        or packet.get("code") != producer()
        or packet.get("limits") != LIMITS
        or packet.get("SDK") != {"anthropic": version("anthropic"), "pydantic": version("pydantic")}
    ):
        raise AdmissionError("diagnostic_code_revision_or_limits_drift")
    if _digest({k: v for k, v in packet.items() if k != "packet_digest"}) != packet.get(
        "packet_digest"
    ):
        raise AdmissionError("diagnostic_packet_digest_drift")
    if tuple(c["id"] for c in packet["cases"]) != ORDER:
        raise AdmissionError("diagnostic_case_order_drift")
    for c in packet["cases"]:
        route = ROUTES["check_recheck_probe" if c["family"] == "checker" else "draft_repair"]
        body = c["body"]
        if (
            body.get("thinking") != route["thinking"]
            or body.get("max_tokens") != route["output_tokens"]
            or body.get("output_config", {}).get("effort") != route["effort"]
            or c["reservation_USD"] != ("0.50" if c["family"] == "checker" else "0.20")
        ):
            raise AdmissionError("diagnostic_settings_or_reservation_drift")
        from src.workspace.provider_schema_compat import guard

        guard(body)
        if c["request_digest"] != _digest(c["body"]) or c["count_digest"] != _digest(
            {k: v for k, v in c["body"].items() if k not in {"max_tokens", "temperature"}}
        ):
            raise AdmissionError("diagnostic_exact_request_drift")
        model = "claude-opus-5-5" if c["family"] == "checker" else "claude-sonnet-5-5"
        if c["body"]["model"] != model:
            raise AdmissionError("diagnostic_model_drift")
        if c["body"]["output_config"]["format"]["schema"] != c["schemas"]["wire"]:
            raise AdmissionError("diagnostic_schema_binding_drift")


def _wire(context: dict[str, Any], schema: dict[str, Any], *, check: bool) -> dict[str, Any]:
    route = ROUTES["check_recheck_probe" if check else "draft_repair"]
    system = (
        "Check every exact supplied claim, qualification, coverage part and prose location. Return every required judgment; preserve negative and uncertain judgments. Citation identity is not whole-claim support. These are fixed development fixtures, not human gold."
        if check
        else "Use only the selected retained public passages. Emit atomic qualified cited claims. Return only JSON matching the supplied schema. Required coverage is the sole answer/context mapping. All substantive text belongs to cited claims; questions/actions use neutral intents. Full abstention has no claims/references. Comparison-only notes do not answer the comparison. These outputs are quarantined compatibility diagnostics, not approved assistance."
    )
    value = _build_request_kwargs(
        profile=RequestProfile(route["model"], None, False, route["effort"], True),
        prompt=json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        system_prompt=system,
        cache_system=False,
        max_tokens=route["output_tokens"],
        schema=None,
    )
    value["thinking"] = deepcopy(route["thinking"])
    value.setdefault("output_config", {}).update(
        effort=route["effort"], format={"type": "json_schema", "schema": schema}
    )
    return value


def _source_notes(
    case: dict[str, Any], count: int, *, maximum: bool = False
) -> tuple[dict[str, Any], dict[str, Any]]:
    sealed = deepcopy(case["sealed"])
    pol = {**sealed["task_policy"], codec.KEY: codec.REVISION}
    if maximum:
        pol["requested_parts"] = [
            {
                **pol["requested_parts"][0],
                "id": f"p{i + 1}",
                "request": f"Structural diagnostic part {i + 1}; assess declared source context, not an independent research result.",
                "kind": "comparison",
            }
            for i in range(8)
        ]
    sealed["task_policy"] = pol
    units = list(sealed["units"].items())
    claims = []
    for i in range(count):
        handle, unit = units[i % len(units)]
        paragraph = next(x.strip() for x in unit["quote"].split("\n\n") if x.strip())
        claims.append({"text": paragraph, "handles": [handle], "required_scope": unit["scope"]})
    value = {
        "response": {
            "disposition": "comparison_abstention",
            "claims": claims,
            "background_claims": [f"c{i + 1}" for i in range(count)],
            "assumption_claims": [],
            "limitation_claims": [],
            "comparison_claims": [],
            "comparison_basis": [],
            "gaps": ["source_scope"],
            "questions": [{"intent": "counterevidence", "claim_ids": []}],
            "proposal": "inspect_evaluation",
            "coverage": {
                part["id"]: {
                    "status": "lacks_evidence",
                    "gap_reasons": ["common_evaluation"],
                    "answer_claim_ids": [],
                    "context_claim_ids": [f"c{i + 1}" for i in range(count)],
                }
                for part in pol["requested_parts"]
            },
        }
    }
    keyed.normalize(value, list(sealed["units"]), sealed["response_purpose"], pol)
    return sealed, value


def freeze(
    snapshot: dict[str, Any],
    predecessor: dict[str, Any],
    accepted_request: dict[str, Any],
    accepted_policy: dict[str, Any],
) -> dict[str, Any]:
    if (
        len(
            set(snapshot["history"]["generation_job_ids"])
            - set(snapshot["programme_baseline"]["generation_job_ids"])
        )
        != 38
        or snapshot["history"]["messages"] != 72
        or snapshot["history"]["counts"] != 97
        or snapshot["history"]["known_usd"] != "2.138481"
        or snapshot["history"]["unknown_usd"] != "2.075066"
        or snapshot["history"]["pending_usd"] != "2.075066"
        or snapshot["history"]["active_jobs"]
    ):
        raise AdmissionError("diagnostic_38_72_97_baseline_required")
    if (
        predecessor["packet_digest"]
        != "35292dcc485d8d7f6f7c126453a8dce17409c470debe2b56828898cef8f57d6d"
        or _digest({k: v for k, v in predecessor.items() if k != "packet_digest"})
        != predecessor["packet_digest"]
    ):
        raise AdmissionError("diagnostic_archived_predecessor_drift")
    cases = []
    mat = materials(predecessor)
    for key, mode, encoding in [
        (ORDER[0], "learn", "accepted-v15r2"),
        (ORDER[1], "learn", codec.LIST_CONTROL),
        (ORDER[2], "learn", codec.REVISION),
        (ORDER[3], "research", codec.REVISION),
    ]:
        source = predecessor["cases"][0 if mode == "learn" else 1]
        sealed = deepcopy(source["sealed"])
        if encoding == "accepted-v15r2":
            pol = deepcopy(accepted_policy)
            schemas = {
                "local": capacity.schemas(list(sealed["units"]), sealed["response_purpose"], pol)[
                    "local"
                ],
                "wire": deepcopy(accepted_request["output_config"]["format"]["schema"]),
            }
        else:
            pol = {**sealed["task_policy"], codec.KEY: encoding}
            schemas = keyed.schemas(list(sealed["units"]), sealed["response_purpose"], pol)
        context = {
            "case": key,
            "purpose": "quarantined schema compatibility diagnostic",
            "question": source["question"],
            "selected_evidence": sealed["units"],
            "task_policy": {k: v for k, v in pol.items() if k != codec.KEY},
            "format_rule": "Variable emitted claims are named c1,c2,... by the server in list order. Coverage alone maps sealed parts to answer/context positions; no claim IDs or reverse mapping inside a claim. Accepted-v15r2 control uses its original schema. No private notes/history/profile.",
        }
        body = _wire(context, schemas["wire"], check=False)
        cases.append(
            {
                "id": key,
                "family": mode,
                "encoding": encoding,
                "body": body,
                "schemas": schemas,
                "policy": pol,
                "purpose": sealed["response_purpose"],
                "units": sealed["units"],
                "source_case": source["id"],
                "reservation_USD": "0.20",
                "machine_reference": None,
                "human_labels": None,
                "conditional": "learn-compact complete and locally valid"
                if key == ORDER[3]
                else None,
            }
        )
    for key, count, maximum in [(ORDER[4], 2, False), (ORDER[5], 12, True)]:
        sealed, draft = _source_notes(predecessor["cases"][1], count, maximum=maximum)
        context = checker_context(sealed, draft, mat)
        schemas = checker.schemas(context)
        body = _wire(context, schemas["wire"], check=True)
        cases.append(
            {
                "id": key,
                "family": "checker",
                "encoding": checker.REVISION,
                "body": body,
                "schemas": schemas,
                "context": context,
                "fixed_draft": draft,
                "policy": sealed["task_policy"],
                "purpose": sealed["response_purpose"],
                "units": sealed["units"],
                "source_case": predecessor["cases"][1]["id"],
                "reservation_USD": "0.50",
                "machine_reference": None,
                "human_labels": None,
                "fixture_provenance": "Machine-authored source paragraph controls. Maximum repeats retained paragraphs for shape/cardinality stress, not independent factual samples.",
                "conditional": "checker-small complete and locally valid" if maximum else None,
            }
        )
    for case in cases:
        case["request_digest"] = _digest(case["body"])
        case["count_digest"] = _digest(
            {k: v for k, v in case["body"].items() if k not in {"max_tokens", "temperature"}}
        )
    value = {
        "revision": REVISION,
        "SDK": {"anthropic": version("anthropic"), "pydantic": version("pydantic")},
        "code": producer(),
        "program_id": snapshot["program_id"],
        "programme_limits": PROGRAM_LIMITS,
        "programme_expiry": snapshot["programme"]["record"]["programme_expires_at"],
        "limits": LIMITS,
        "basis_members": snapshot["members"],
        "basis": snapshot["history"],
        "programme_baseline": snapshot["programme_baseline"],
        "programme_parent": snapshot["programme"],
        "snapshot_digest": _digest(snapshot),
        "source_bindings": {
            kind: {
                row[key]: _digest(row["data"])
                for row in snapshot["tables"][table]
                if row[key] in predecessor["source_bindings"][kind]
            }
            for kind, table, key in [
                ("versions", "workspace_versions", "version_id"),
                ("materials", "workspace_material", "material_id"),
            ]
        },
        "predecessor_source_bindings": predecessor["source_bindings"],
        "materials": predecessor["materials"],
        "parent_stopped_scope": snapshot["parent_stopped_scope"],
        "retained_liabilities": snapshot["retained_liabilities"],
        "cases": cases,
        "private_context": {"notes": False, "history": False, "preferences": False},
        "everyday_generation": False,
        "progression": {
            "baseline_rejection": "stop",
            "learn_list_received_grammar_rejection": "may continue to declared learn-compact with full hold retained, only if explicitly approved",
            "research": "only after complete locally valid learn-compact",
            "checker_small": "independent fixed-evidence diagnostic",
            "checker_maximum": "only after complete locally valid checker-small",
            "unexpected_provider_error_or_NEW_uncertain_completion": "stop",
            "drift_budget_expiry_revocation_cancellation": "stop",
            "repairs": 0,
            "automatic_retries": 0,
            "acceptance_axes": [
                "remote_compiler_acceptance",
                "complete_output",
                "local_semantic_validity",
                "provenance",
                "research_quality_unmeasured",
            ],
        },
        "new_approval": False,
        "human_qualification": False,
        "full_campaign_readiness": "NOT ESTABLISHED; any later campaign requires explicit adoption of the exact compatible encoding and separate frozen bindings",
    }
    value["packet_digest"] = _digest(value)
    verify(value)
    return value


def compile_inputs(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    verify(packet)
    return _compile_inputs(packet)


def _compile_inputs(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scope = "compat-" + packet["packet_digest"][:24]
    result = {}
    for case in packet["cases"]:
        refs = {}
        for unit in case["units"].values():
            material = next(
                m for m in packet["materials"] if m["material_id"] == unit["material_id"]
            )
            refs[material["material_id"]] = SourceRef(
                material["work_id"],
                material["version_id"],
                material["material_id"],
                material["content_hash"],
                material["scope"],
            )
        route = ROUTES["check_recheck_probe" if case["family"] == "checker" else "draft_repair"]
        request_id = "compat-" + packet["packet_digest"][:16] + "-" + case["id"]
        settings = {
            "compatibility_revision": packet["revision"],
            "compatibility_scope": scope,
            "compatibility_packet_digest": packet["packet_digest"],
            "case_id": case["id"],
            "wire": case["body"],
            "input_tokens": 40000,
            "output_tokens": route["output_tokens"],
            "timeout_seconds": 240 if case["family"] == "checker" else 120,
            "response_bytes": 4194304,
            "max_calls": 1,
            "max_repairs": 0,
            "price_estimate_usd_per_million": route["prices"],
            "d5_capacity_policy": deepcopy(POLICY),
        }
        inputs = GenerationInput(
            "deep_dive", route["model"], packet["revision"], tuple(refs[k] for k in sorted(refs)), settings
        )
        result[case["id"]] = {
            "owner": "compat-" + packet["packet_digest"][:12] + "-" + case["id"],
            "request_id": request_id,
            "input": inputs.snapshot(),
            "reservation_USD": case["reservation_USD"],
        }
    return result


def observed(
    payload: dict[str, Any], case: dict[str, Any], packet: dict[str, Any]
) -> dict[str, Any]:
    if packet.get("revision") == SUCCESSOR_REVISION:
        from src.workspace.d5_consistency_packet import observed as observe_successor
        return observe_successor(payload, case, packet)
    if case["family"] == "checker":
        from src.workspace.assistance_coverage import validate_review

        normalized = checker.normalize(payload, case["context"])
        check = checker.checks_model().model_validate(normalized)
        validate_review(check, case["context"])
        check.validate_locations(case["context"].get("unscored_prose", {}))
        return {
            "normalized": normalized,
            "current_response_digest": case["context"]["checked_response_digest"],
            "human_labels": None,
            "research_quality": "UNMEASURED",
        }
    from src.workspace.grounding import EvidenceRef

    units = case["units"]
    purpose = case["purpose"]
    pol = case["policy"]
    if case["encoding"] == "accepted-v15r2":
        draft, claims = capacity.resolve_draft(
            payload,
            {k: EvidenceRef(**v) for k, v in units.items()},
            materials(packet),
            purpose=purpose,
            policy=pol,
        )
        envelope, coverage = capacity.normalize(payload, list(units), purpose, pol)
        rendered = capacity.render(payload, list(units), purpose, pol)
    else:
        draft, claims = keyed.resolve_draft(
            payload,
            {k: EvidenceRef(**v) for k, v in units.items()},
            materials(packet),
            purpose=purpose,
            policy=pol,
        )
        envelope, coverage = keyed.normalize(payload, list(units), purpose, pol)
        rendered = keyed.render(payload, list(units), purpose, pol)
    from src.workspace.grounding import validate_claims

    provenance = validate_claims(claims, materials(packet))
    if any(not r.identity_resolved or not r.scope_compatible for r in provenance.assessments):
        raise AdmissionError("diagnostic_provenance_invalid")
    return {
        "normalized": envelope,
        "coverage": coverage,
        "reader_view": rendered,
        "draft": draft.model_dump(mode="json"),
        "provenance": asdict(provenance),
        "human_labels": None,
        "research_quality": "UNMEASURED; no dynamic checker was dispatched",
    }


def strict_json(text: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise AdmissionError("diagnostic_duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(value: str) -> Any:
        raise AdmissionError("diagnostic_nonfinite_json")

    result = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(result, dict):
        raise AdmissionError("diagnostic_object_required")
    return result


def plain_json_alternative(case: dict[str, Any]) -> dict[str, Any]:
    """Offline candidate only: no extra paid identity or relaxed local validator."""
    value = deepcopy(case["body"])
    value["output_config"].pop("format")
    return {
        "body": value,
        "local_schema": case["schemas"]["local"],
        "local_validation": "unchanged; duplicate keys/truncation/provenance/whole-claim gates mandatory",
        "live_in_scope": False,
        "reliability": "No remote grammar guarantee. Fences, malformed JSON, missing fields and semantic failures remain failures. No automatic repair/retry is authorized.",
    }


def capture(
    store: Any, program_id: str, *, stopped_scope_id: str = "d5-35292dcc485d8d7f6f7c1264"
) -> dict[str, Any]:
    """Read-only census; no migration, grant, reservation or financial changes."""
    from src.workspace.d5_fixture import FINANCIAL_TABLES, PUBLIC_TABLES, financial_rows
    from src.workspace.qualification_budget import census
    from src.workspace.schemas import ProfileData

    with store.pool.connection() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        members = sorted(
            r[0]
            for r in conn.execute(
                "SELECT owner FROM workspace_evaluation_members WHERE program_id=%s", (program_id,)
            )
        )
        if not members:
            raise AdmissionError("diagnostic_programme_members_required")
        baseline = census(conn, members[0], members=members)
        programme_baseline = conn.execute(
            "SELECT baseline FROM workspace_evaluation_programs WHERE program_id=%s", (program_id,)
        ).fetchone()[0]
        stopped = conn.execute(
            "SELECT to_jsonb(t) FROM workspace_d5_scopes t WHERE scope_id=%s",
            (stopped_scope_id,),
        ).fetchone()
        if not stopped or stopped[0]["state"] != "stopped":
            raise AdmissionError("diagnostic_stopped_predecessor_required")
        liabilities = [
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
                (members,),
            )
        ]
        tables = {
            name: [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))
                )
            ]
            for name in PUBLIC_TABLES
        }
        if any(r["visibility_owner"] is not None for r in tables["workspace_works"]):
            raise AdmissionError("campaign_v16_public_context_only")
        tables.update({name: financial_rows(conn, name) for name in FINANCIAL_TABLES})
        extras: dict[str, Any] = {}
        for table, key in (
            ("workspace_programme_amendments", "recorded_amendments"),
            ("workspace_programme_successor_amendments", "recorded_successor_amendments"),
            ("workspace_programme_third_amendments", "recorded_third_amendments"),
            ("workspace_programme_capacity_amendments", "recorded_capacity_amendments"),
            ("workspace_d5_scopes", "historical_scopes"),
            ("workspace_d5_stage_authorizations", "historical_stage_grants"),
            ("workspace_d5_case_runs", "historical_case_runs"),
            ("workspace_d5_campaign_extensions", "recorded_campaign_extensions"),
            ("workspace_d5_campaign_revocations", "recorded_campaign_revocations"),
            ("workspace_d5_campaign_outcomes", "recorded_campaign_outcomes"),
            ("workspace_d5_campaign_successors", "recorded_campaign_successors"),
            (
                "workspace_d5_campaign_successor_revocations",
                "recorded_campaign_successor_revocations",
            ),
            ("workspace_d5_capacity_revisions", "recorded_capacity_revisions"),
            (
                "workspace_d5_capacity_revision_revocations",
                "recorded_capacity_revision_revocations",
            ),
            ("workspace_d5_keyed_continuations", "recorded_keyed_continuations"),
            (
                "workspace_d5_keyed_continuation_revocations",
                "recorded_keyed_continuation_revocations",
            ),
        ):
            if (
                table
                in {
                    "workspace_d5_keyed_continuations",
                    "workspace_d5_keyed_continuation_revocations",
                }
                and not conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
            ):
                extras[key] = []
                continue
            extras[key] = [
                r[0]
                for r in conn.execute(
                    sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(table))
                )
            ]
        p = programme_parent(conn, program_id)
    return {
        "tables": tables,
        **extras,
        "programme": p,
        "members": members,
        "programme_baseline": programme_baseline,
        "parent_stopped_scope": stopped[0],
        "retained_liabilities": liabilities,
        "history": baseline,
        "program_id": program_id,
        "profile": ProfileData().model_dump(mode="json"),
        "profile_authority": "Unused synthetic storage profile; ranking uses retained owner-authoritative benchmark profile, never owner notes/history.",
        "provenance": "Read-only stopped v16r2 census; all three liabilities retained without settlement.",
    }


def programme_parent(conn: Any, program_id: str) -> dict[str, Any]:
    """Bind immutable programme authority without reapplying old two-hold rules."""
    row = conn.execute(
        "SELECT to_jsonb(t) FROM workspace_d5_capacity_revisions t WHERE program_id=%s AND extension_id=%s",
        (program_id, program_id + "-capacity-v15"),
    ).fetchone()
    if not row:
        raise AdmissionError("diagnostic_original_programme_receipt_required")
    value = row[0]
    record = value["record"]
    if (
        _digest(record) != value["authorization_digest"]
        or record.get("approved") is not True
        or not record.get("programme_expires_at")
        or record.get("campaign_extension", {}).get("core", {}).get("limits")
        != {"new_jobs": 64, "messages": 160, "counts": 200, "usd": "20", "concurrency": 1}
    ):
        raise AdmissionError("diagnostic_original_programme_binding_drift")
    revoked = conn.execute(
        "SELECT 1 FROM workspace_d5_capacity_revision_revocations WHERE extension_id=%s",
        (value["extension_id"],),
    ).fetchone()
    if revoked:
        raise AdmissionError("diagnostic_programme_revoked")
    return cast(dict[str, Any], value)
