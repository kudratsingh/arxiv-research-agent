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
    stop = None
    advanced = 0
    for key, entry in compiled.items():
        try:
            verify_dispatch_identity(packet)  # no packet/producer tuning between cases
            with store.pool.connection() as conn:
                done = audit_outcomes(conn, scope)
            if key in done:
                continue
            if cancelled():
                raise AdmissionError("campaign_cancelled_no_dispatch")
            inputs = restore_input(entry["input"])
            kwargs: dict[str, Any]
            if offline:
                transport = transport_factory(key) if transport_factory else CampaignTransport(key)
                kwargs = {"transport": httpx.MockTransport(transport)}
            else:
                # Only an explicitly authorized runner reaches credential loading.
                kwargs = {
                    "api_key": os.environ.get("ANTHROPIC_API_KEY", "local-preview-disabled"),
                    "enabled": True,
                }
            adapter = (D5ProbeAdapter if inputs.settings["d5_operation"] == "probe" else D5Adapter)(
                store, entry["owner"], inputs, **kwargs
            )
            started = time.monotonic()
            job = adapter.start(inputs.settings["d5_request_id"])
            cached_ready = job["state"] == "ready"
            try:
                if job["state"] not in {"running", "ready"}:
                    raise AdmissionError("campaign_stopped_identity_no_replay")
                for _ in range(1 if inputs.settings["d5_operation"] == "probe" else 4):
                    if job["state"] == "ready":
                        break
                    job = await adapter.advance(job["id"], cancelled=cancelled)
                if job["state"] != "ready":
                    raise AdmissionError("campaign_incomplete_workflow_stop")
            except (Exception, asyncio.CancelledError):
                with store.pool.connection() as conn:
                    failed = conn.execute(
                        "SELECT state,data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
                    ).fetchone()
                if (
                    not failed
                    or failed[0] != "failed"
                    or not failed[1].get("campaign_content_rejection")
                ):
                    raise
            if not cached_ready:
                with store.pool.connection() as conn:
                    conn.execute(
                        "UPDATE workspace_generation_jobs SET data=jsonb_set(data,'{d5_elapsed_seconds}',%s) WHERE id=%s AND NOT(data ? 'd5_elapsed_seconds')",
                        (Jsonb(time.monotonic() - started), job["id"]),
                    )
            terminal = record_outcome(store, scope, key, job["id"], _digest(entry["input"]))
            advanced += 1
            if progress is not None:
                progress(terminal)
            if checkpoint_after is not None and advanced >= checkpoint_after:
                break  # Durable progress under the same approval; no new scope.
        except (Exception, asyncio.CancelledError) as exc:
            stop = {
                "case_id": key,
                "error_class": type(exc).__name__,
                "reason": str(exc)[:1200],
                "remaining_cases": list(compiled)[list(compiled).index(key) + 1 :],
                "automatic_retries": 0,
            }
            with store.pool.connection() as conn:
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
    parser.add_argument("verb", choices=["freeze", "verify", "offline", "run", "report"])
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
        if args.verb == "freeze":
            if (
                args.snapshot is None
                or os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
                or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
            ):
                raise AdmissionError("campaign_freeze_offline_snapshot_required")
            captured = read(args.snapshot)
            install(store, captured, fixture=True)
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
        factory = (
            (lambda key: CampaignTransport(key, repair_all=True))
            if args.fixture_repair_all
            else None
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
