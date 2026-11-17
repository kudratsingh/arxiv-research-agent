"""Automatic exact count -> fit -> generation under ONE externally recorded scope.

No owner permission writer. Offline fixture authorization is isolated/explicit.
Terminal content rejections stay failed; no retries, replacement IDs or tuning.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import D5Adapter, D5ProbeAdapter


class CampaignTransport:
    """Wire-valid synthetic controls; never real token or checker-quality evidence."""

    def __init__(self, key: str, *, repair_all: bool = False, scenario: str = "normal"):
        self.key, self.repair_all, self.scenario = key, repair_all, scenario
        self.checks = 0
        self.contacts: list[tuple[str, str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        from src.workspace.assistance import LocalAssistanceTransport

        body = json.loads(request.content)
        self.contacts.append((request.url.path, _digest(body)))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(
                200, json={"input_tokens": 20001 if self.scenario == "oversized" else 100}
            )
        context = json.loads(body["messages"][0]["content"])
        if self.scenario == "uncertain" and context["phase"] == "check":
            raise httpx.ReadTimeout(
                "Synthetic uncertain contact; no provider contacted", request=request
            )
        result = LocalAssistanceTransport.fixture(request).json()
        payload = json.loads(result["content"][0]["text"])
        compact_checker = "claim_reviews" in payload
        if compact_checker:
            from src.workspace.assistance_compact_checks import normalize

            payload = normalize(payload)
        if context["phase"] == "check":
            self.checks += 1
            if "coverage_checks" in payload:
                for c in payload["checks"]:
                    c["decision"] = "supported"
                    c["reason"] = (
                        "Synthetic positive software control; no independent semantic or human evidence"
                    )
            if (
                "coverage_checks" in payload
                and (self.repair_all or self.key.endswith("dev-learn"))
                and self.checks == 1
            ):
                payload["coverage_checks"][0]["decision"] = "uncertain"
            if "coverage_checks" not in payload:
                # This lexical fixture proves score plumbing only, not meaning.
                from src.workspace.d5_campaign_packet import PROBE_CONTROLS

                negative_texts = {n for _, _, n in PROBE_CONTROLS}
                texts = {c["claim_id"]: c["text"] for c in context["draft"]["claims"]}
                for c in payload["checks"]:
                    c["decision"] = (
                        "unsupported" if texts[c["claim_id"]] in negative_texts else "supported"
                    )
                    c["reason"] = "Synthetic transport control, not independent factual judgment"
            if self.scenario == "reject" and "coverage_checks" in payload:
                for c in payload["checks"]:
                    c["decision"] = "unsupported"
        result.update(
            id="synthetic-campaign-" + self.key + "-" + str(len(self.contacts)),
            model=body["model"],
            usage={"input_tokens": 100, "output_tokens": 100},
        )
        result["content"][0]["text"] = json.dumps(payload)
        if self.scenario == "truncated" and context["phase"] == "draft":
            result.update(
                stop_reason="max_tokens", content=[{"type": "text", "text": '{"response":'}]
            )
        if compact_checker:
            from src.workspace.assistance_compact_checks import compact_fixture

            for row in (
                *payload["checks"],
                *payload["claim_quality"],
                *payload["coverage_checks"],
                *payload["prose_findings"],
            ):
                row["reason"] = "Synthetic software control; no independent semantic qualification."
            result["content"][0]["text"] = json.dumps(compact_fixture(payload))
        return httpx.Response(200, json=result)


def preflight(store: Any, packet: dict[str, Any]) -> None:
    from src.workspace.d5_benchmark import check_storage
    from src.workspace.d5_campaign_extension import guard_exception
    from src.workspace.d5_campaign_packet import compile_campaign
    from src.workspace.d5_campaign_policy import audit_outcomes
    from src.workspace.d5_freeze import verify

    verify(packet)
    check_storage(store, packet)
    compiled = compile_campaign(packet)
    owner = next(iter(compiled.values()))["owner"]
    with store.pool.connection() as conn:
        policy = conn.execute(
            "SELECT data FROM workspace_budget_policies WHERE owner=%s", (owner,)
        ).fetchone()
        scope = conn.execute(
            "SELECT state,expires_at FROM workspace_d5_scopes WHERE scope_id=%s",
            ("d5-" + packet["packet_digest"][:24],),
        ).fetchone()
        from datetime import UTC, datetime

        if not policy or not scope or scope[0] != "active" or datetime.now(UTC) >= scope[1]:
            raise AdmissionError("campaign_active_external_authorization_required")
        guard_exception(conn, policy[0])
        audit_outcomes(conn, policy[0]["d5_scope_id"])


async def run(
    store: Any,
    packet: dict[str, Any],
    *,
    offline: bool,
    transport_factory: Any = None,
    cancelled: Any = lambda: False,
    checkpoint_after: int | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    from src.workspace.d5_campaign_packet import compile_campaign, verify_dispatch_identity
    from src.workspace.d5_campaign_policy import audit_outcomes, record_outcome
    from src.workspace.d5_campaign_report import results
    from src.workspace.d5_case_isolation import (
        REVISION as ISOLATION_REVISION,
    )
    from src.workspace.d5_case_isolation import (
        preserve_failed_case,
        require_progression,
        stop_details,
    )
    from src.workspace.d5_freeze import restore_input

    verify_dispatch_identity(packet)
    with store.pool.connection() as conn:
        fixture = bool(conn.execute("SELECT 1 FROM workspace_d5_fixture_marker").fetchone())
    if (
        fixture != offline
        or offline
        and os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or transport_factory is not None
        and not offline
    ):
        raise AdmissionError("campaign_transport_database_mismatch")
    preflight(store, packet)
    compiled = compile_campaign(packet)
    scope = "d5-" + packet["packet_digest"][:24]
    isolate_evaluations = packet.get("revision") == ISOLATION_REVISION
    stop = None
    advanced = 0
    for key, entry in compiled.items():
        local_stage = "dispatch_gate"
        job_id = None
        try:
            verify_dispatch_identity(packet)  # no packet/producer tuning between cases
            with store.pool.connection() as conn:
                done = audit_outcomes(conn, scope)
            if key in done:
                continue
            if cancelled():
                raise AdmissionError("campaign_cancelled_no_dispatch")
            if isolate_evaluations:
                with store.pool.connection() as conn:
                    require_progression(conn, scope, packet["packet_digest"], key, entry)
            inputs = restore_input(entry["input"])
            kwargs: dict[str, Any]
            if offline:
                if transport_factory is not None:
                    transport = transport_factory(key)
                elif packet.get("revision") == "d5-comparison-machine-campaign-v19":
                    from src.workspace.d5_comparison_transport import ComparisonCampaignTransport

                    transport = ComparisonCampaignTransport(key)
                elif packet.get("revision") == "d5-keyed-machine-campaign-v16":
                    from src.workspace.d5_keyed_transport import KeyedCampaignTransport

                    transport = KeyedCampaignTransport(key)
                else:
                    transport = CampaignTransport(key)
                kwargs = {"transport": httpx.MockTransport(transport)}
            else:
                # Only an explicitly authorized runner reaches credential loading.
                kwargs = {
                    "api_key": os.environ.get("ANTHROPIC_API_KEY", "local-preview-disabled"),
                    "enabled": True,
                }
            local_stage = "case_start"
            adapter = (D5ProbeAdapter if inputs.settings["d5_operation"] == "probe" else D5Adapter)(
                store, entry["owner"], inputs, **kwargs
            )
            started = time.monotonic()
            job = adapter.start(inputs.settings["d5_request_id"])
            job_id = job["id"]
            cached_ready = job["state"] == "ready"
            try:
                if job["state"] not in {"running", "ready"}:
                    raise AdmissionError("campaign_stopped_identity_no_replay")
                stages = (
                    ("check",)
                    if inputs.settings["d5_operation"] == "probe"
                    else ("draft", "check", "repair", "recheck")
                )
                for stage in stages:
                    if job["state"] == "ready":
                        break
                    local_stage = stage
                    job = await adapter.advance(job["id"], cancelled=cancelled)
                if job["state"] != "ready":
                    raise AdmissionError("campaign_incomplete_workflow_stop")
            except (Exception, asyncio.CancelledError) as exc:
                if isolate_evaluations:
                    if cancelled():
                        raise AdmissionError("campaign_cancelled_no_dispatch") from exc
                    if not preserve_failed_case(adapter, job["id"], entry, exc):
                        raise
                else:
                    with store.pool.connection() as conn:
                        failed = conn.execute(
                            "SELECT state,data FROM workspace_generation_jobs WHERE id=%s",
                            (job["id"],),
                        ).fetchone()
                    if (
                        not failed
                        or failed[0] != "failed"
                        or not failed[1].get("campaign_content_rejection")
                    ):
                        raise
            if isolate_evaluations and entry["stage"] == "B":
                local_stage = "development_contract"
                from src.workspace.d5_campaign_v19_policy import (
                    development_contract as comparison_development_contract,
                )

                with store.pool.connection() as conn:
                    comparison_development_contract(conn, scope, key)
            local_stage = "outcome"
            if not cached_ready:
                with store.pool.connection() as conn:
                    conn.execute(
                        "UPDATE workspace_generation_jobs SET data=jsonb_set(data,'{d5_elapsed_seconds}',%s) WHERE id=%s AND NOT(data ? 'd5_elapsed_seconds')",
                        (Jsonb(time.monotonic() - started), job["id"]),
                    )
            terminal = record_outcome(store, scope, key, job["id"], _digest(entry["input"]))
            if (
                packet.get("revision")
                in {
                    "d5-comprehensive-machine-campaign-v15",
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }
                and terminal["state"] == "failed"
            ):
                if inputs.settings["d5_operation"] == "probe":
                    raise AdmissionError("campaign_probe_contract_incomplete")
                from src.workspace.d5_campaign_v15_policy import (
                    development_contract as current_contract,
                )

                if packet.get("revision") in {
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }:
                    from src.workspace.d5_campaign_v16_policy import (
                        development_contract as current_contract,
                    )
                if packet.get("revision") == "d5-comparison-machine-campaign-v19":
                    from src.workspace.d5_campaign_v19_policy import (
                        development_contract as current_contract,
                    )
                with store.pool.connection() as conn:
                    current_contract(conn, scope, key)
            advanced += 1
            if progress is not None:
                progress(terminal)
            if (
                packet.get("revision")
                in {
                    "d5-complete-machine-campaign-v14",
                    "d5-comprehensive-machine-campaign-v15",
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }
                and entry["stage"] == "B"
            ):
                from src.workspace.d5_campaign_v14_policy import development_contract

                if packet.get("revision") in {
                    "d5-comprehensive-machine-campaign-v15",
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }:
                    from src.workspace.d5_campaign_v15_policy import development_contract

                if packet.get("revision") in {
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }:
                    from src.workspace.d5_campaign_v16_policy import development_contract
                    from src.workspace.d5_campaign_v19_policy import (
                        development_contract as comparison_contract,
                    )

                    if packet.get("revision") == "d5-comparison-machine-campaign-v19":
                        development_contract = comparison_contract
                with store.pool.connection() as conn:
                    development_contract(conn, scope, key)
            if checkpoint_after is not None and advanced >= checkpoint_after:
                break  # Durable progress under the same approval; no new scope.
        except (Exception, asyncio.CancelledError) as exc:
            stop = {
                "case_id": key,
                "error_class": type(exc).__name__,
                "reason": str(exc)
                if packet.get("revision")
                in {
                    "d5-comprehensive-machine-campaign-v15",
                    "d5-keyed-machine-campaign-v16",
                    "d5-comparison-machine-campaign-v19",
                }
                else str(exc)[:1200],
                "remaining_cases": list(compiled)[list(compiled).index(key) + 1 :],
                "automatic_retries": 0,
            }
            with store.pool.connection() as conn:
                if isolate_evaluations:
                    row = (
                        conn.execute(
                            "SELECT data FROM workspace_generation_jobs WHERE id=%s",
                            (job_id,),
                        ).fetchone()
                        if job_id
                        else None
                    )
                    contacts = row[0].get("adapter", {}).get("contacts", []) if row else []
                    stop.update(
                        stop_details(
                            exc, entry["stage"], local_stage, contacts[-1] if contacts else {}
                        )
                    )
                    conn.execute(
                        "UPDATE workspace_d5_scopes "
                        "SET state=CASE WHEN state='revoked' THEN state ELSE 'stopped' END,"
                        "data=jsonb_set(data,'{campaign_stop}',%s) WHERE scope_id=%s "
                        "AND NOT(data ? 'campaign_stop')",
                        (Jsonb(stop), scope),
                    )
                else:
                    conn.execute(
                        "UPDATE workspace_d5_scopes SET state='stopped',data=jsonb_set(data,'{campaign_stop}',%s) WHERE scope_id=%s AND state='active'",
                        (Jsonb(stop), scope),
                    )
            break
    return results(store, packet, stop=stop)


def main() -> None:
    from src.workspace.d5_benchmark import database, read, write
    from src.workspace.d5_campaign_packet import freeze, verify_dispatch_identity
    from src.workspace.d5_campaign_report import markdown, results
    from src.workspace.d5_fixture import install
    from src.workspace.store import WorkspaceStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "verb",
        choices=[
            "freeze",
            "freeze-v14",
            "freeze-v15",
            "freeze-v16",
            "freeze-v16r2",
            "freeze-v19",
            "verify",
            "offline",
            "run",
            "report",
        ],
    )
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fixture-repair-all", action="store_true")
    args = parser.parse_args()
    if args.fixture_repair_all and args.verb != "offline":
        raise AdmissionError("campaign_fixture_option_offline_only")
    if args.verb == "verify":
        from src.workspace.d5_freeze import verify

        verify(read(args.packet))
        print("Verified frozen campaign; no authority or contacts created")
        return
    with database(os.environ["D5_POSTGRES_URL"]) as pool:
        store = WorkspaceStore(pool)
        if args.verb in {
            "freeze",
            "freeze-v14",
            "freeze-v15",
            "freeze-v16",
            "freeze-v16r2",
            "freeze-v19",
        }:
            if (
                args.snapshot is None
                or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
                or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
            ):
                raise AdmissionError("campaign_freeze_offline_snapshot_required")
            captured = read(args.snapshot)
            install(store, captured, fixture=True)
            if args.verb == "freeze-v19":
                from src.workspace.d5_campaign_v19_packet import freeze as freeze_comparison

                write(args.packet, freeze_comparison(store, captured))
            elif args.verb in {"freeze-v16", "freeze-v16r2"}:
                from src.workspace.d5_campaign_v16_packet import freeze as freeze_keyed

                write(
                    args.packet,
                    freeze_keyed(store, captured, union_safe=args.verb == "freeze-v16r2"),
                )
            elif args.verb == "freeze-v15":
                from src.workspace.d5_campaign_v15_packet import freeze as freeze_capacity

                write(args.packet, freeze_capacity(store, captured))
            elif args.verb == "freeze-v14":
                from src.workspace.d5_campaign_v14_packet import freeze as freeze_successor

                write(args.packet, freeze_successor(store, captured))
            else:
                write(args.packet, freeze(store, captured))
            return
        packet = read(args.packet)
        # Reports may be recomputed after expiry, but never from mutated inputs
        # or another producer. This does not grant execution permission.
        verify_dispatch_identity(packet)
        if args.verb == "offline":
            from src.workspace.d5_benchmark import check_storage
            from src.workspace.d5_campaign_operator import authorize_fixture

            if args.snapshot is None:
                parser.error("offline requires original --snapshot and empty disposable storage")
            captured = read(args.snapshot)
            if _digest(captured) != packet["snapshot_digest"]:
                raise AdmissionError("campaign_snapshot_binding_drift")
            install(store, captured, fixture=True)
            check_storage(store, packet)
            authorize_fixture(store, packet)
        if args.out is None:
            parser.error("run/report requires new --out directory")
        transport_type: Any = CampaignTransport
        if packet.get("revision") == "d5-comparison-machine-campaign-v19":
            from src.workspace.d5_comparison_transport import ComparisonCampaignTransport

            transport_type = ComparisonCampaignTransport
        elif packet.get("revision") == "d5-keyed-machine-campaign-v16":
            from src.workspace.d5_keyed_transport import KeyedCampaignTransport

            transport_type = KeyedCampaignTransport
        factory = (
            (lambda key: transport_type(key, repair_all=True)) if args.fixture_repair_all else None
        )
        report = (
            results(store, packet)
            if args.verb == "report"
            else asyncio.run(
                run(
                    store,
                    packet,
                    offline=args.verb == "offline",
                    transport_factory=factory,
                    progress=lambda r: print(
                        json.dumps({"checkpoint": r["case_id"], "state": r["state"]}), flush=True
                    ),
                )
            )
        )
        write(args.out / "results.json", report)
        rendered = markdown(report)
        (args.out / "REPORT.md").write_text(rendered)
        from html import escape

        (args.out / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>D5 machine-only campaign</title><pre>"
            + escape(rendered)
            + "</pre>"
        )
        print(
            json.dumps(
                {
                    "packet": packet["packet_digest"],
                    "denominators": report["denominators"],
                    "machine_quality": report["machine_quality"],
                    "stop": report["stop"],
                    "new_provider_contacts": 0 if args.verb == "offline" else None,
                }
            )
        )


if __name__ == "__main__":
    main()
