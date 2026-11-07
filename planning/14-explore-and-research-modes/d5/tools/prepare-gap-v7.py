"""Offline-only v7 freeze/replay. Read using python - < file from worktree root.

Synthetic approvals are restricted to disposable, permanently provider-disabled
storage. All historical responses, receipts and stopped scopes remain unchanged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import database, read, run, write
from src.workspace.d5_fixture import authorize_fixture, install, prepare_projects
from src.workspace.d5_freeze import freeze, verify
from src.workspace.d5_operations import OPUS_LIMITS, ROUTES, wire
from src.workspace.d5_scoring import markdown
from src.workspace.programme_third_amendment import record_external
from src.workspace.store import WorkspaceStore

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("verb", choices=["seal", "replay"])
for name in ["packet", "snapshot", "successor", "out"]:
    parser.add_argument("--" + name, type=Path, required=True)
a = parser.parse_args()
if (
    os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
    or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
):
    raise AdmissionError("offline_sentinel_required")
if a.out.exists():
    raise AdmissionError("new_report_directory_required")
a.out.mkdir(parents=True)
captured = read(a.snapshot)
successor = read(a.successor)
assert successor["approved"] is False
with database(os.environ["D5_POSTGRES_URL"]) as pool:
    store = WorkspaceStore(pool)
    install(store, captured, fixture=True)
    if a.verb == "seal":
        p = freeze(store, captured["profile"], captured["history"])
        p.update(
            program_id=captured["program_id"],
            snapshot_digest=_digest(captured),
            profile_authority=captured["profile_authority"],
            operation_routes=deepcopy(ROUTES),
            limits=deepcopy(OPUS_LIMITS),
            predecessor_packet_digest="7e21713caee474fbafa31d197a754e232a66fac670143e5ddbae5b0ccb90389f",
            programme_amendment=successor,
            planned_development_cases=["dev-learn", "dev-compare"],
            measurement_cases=["dev-compare"],
            require_supported_development=True,
            measurement_reuse={},
            fresh_measurement_cases=["measure-1"],
            historical_paid_baseline={
                "programme_jobs": 10,
                "Messages": 17,
                "counts": 35,
                "estimated_usd": "0.351961",
                "pending_usd": "0",
                "unknown_usd": "0",
            },
            historical_development={
                "dev-learn": "Completed v6, preserved; changed draft/check schemas require a new live development run.",
                "dev-compare": "Rejected v6 196-character gap, preserved; never replayed or accepted.",
            },
        )
        p["execution"].update(
            operation_routes=deepcopy(ROUTES),
            checker_model="claude-opus-5-5",
            checker_output_tokens=3200,
            checker_effort="high",
            checker_thinking={"type": "adaptive"},
        )
        for probe in p["probes"]:
            context = json.loads(probe["wire"]["messages"][0]["content"])
            probe["wire"] = wire({**context, "output_schema": p["checker_schema"]["wire"]}, ROUTES)
        p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
        verify(p)
        write(a.packet, p)
    else:
        p = read(a.packet)
        verify(p)
        prepare_projects(store, p)
        synthetic = deepcopy(successor)
        now = datetime.now(UTC)
        synthetic.update(
            approved=True,
            approved_by="Synthetic offline fixture, not owner approval",
            approved_at=now.isoformat(),
            expires_at=min(
                now + timedelta(days=1),
                datetime.fromisoformat(successor["amendment"]["predecessor_expiry"]),
            ).isoformat(),
            authorization_kind="offline_fixture",
            transport_mode="mock",
            authorization_reference="Disposable v7 replay only",
        )
        write(a.out / "SYNTHETIC-amendment.json", record_external(store, synthetic))
        # Explicit machine-opinion test fixture, never independent labels.
        # The default honest fixture abstains on paraphrases; preserve its
        # refusal separately. This positive scenario exercises C's controls.
        import httpx

        from src.workspace import d5_fixture

        class SyntheticDevelopment(d5_fixture.ReplayTransport):
            check_number = 0

            async def __call__(self, request):
                response = await super().__call__(request)
                if request.url.path.endswith("count_tokens") or self.case_id not in {
                    "dev-learn",
                    "dev-compare",
                }:
                    return response
                raw = response.json()
                payload = json.loads(raw["content"][0]["text"])
                if "checks" in payload:
                    self.check_number += 1
                    for check in payload["checks"]:
                        check["decision"] = "unsupported" if self.check_number == 1 else "supported"
                        check["reason"] = (
                            "Synthetic progression fixture; not human or provider quality evidence."
                        )
                    raw["content"][0]["text"] = json.dumps(payload)
                return httpx.Response(200, json=raw)

        d5_fixture.ReplayTransport = SyntheticDevelopment
        authorize_fixture(store, p, stages=("A", "B"))
        asyncio.run(run(store, p, "A", offline=True))
        asyncio.run(run(store, p, "B", offline=True))
        try:
            asyncio.run(run(store, p, "C", offline=True))
        except AdmissionError as e:
            assert str(e) == "d5_stage_not_authorized"
            write(a.out / "C-refusal.json", {"reason": str(e), "provider_contacts": 0})
        else:
            raise AssertionError("C must require separate approval")
        # Synthetic append-only C/D grant only inside a fixture database.
        from src.workspace.d5_authorization import grant_external, stage_template

        receipt = stage_template(store, "d5-" + p["packet_digest"][:24], ["C", "D"])
        receipt.update(
            approved=True,
            approved_by="Synthetic fixture, never owner labels",
            approved_at=now.isoformat(),
        )
        grant_external(store, receipt["scope_id"], receipt)
        asyncio.run(run(store, p, "C", offline=True))
        r = asyncio.run(run(store, p, "D", offline=True))
        write(a.out / "SYNTHETIC-results.json", r)
        (a.out / "SYNTHETIC-REPORT.md").write_text(markdown(r))
        with pool.connection() as c:
            old = c.execute(
                "SELECT state,data FROM workspace_d5_scopes WHERE scope_id='d5-7e21713caee474fbafa31d19'"
            ).fetchone()
            assert old and old[0] == "stopped"
            assert (
                c.execute(
                    "SELECT count(*) FROM workspace_programme_successor_amendments"
                ).fetchone()[0]
                == 1
            )
            write(
                a.out / "preservation.json",
                {
                    "v6_scope": "stopped",
                    "old_scope_digest": _digest(old[1]),
                    "original22_job_receipt_unchanged": True,
                    "actual_provider_contacts": 0,
                    "new_spend_usd": "0",
                },
            )
    write(
        a.out / "identity.json",
        {
            "packet_digest": p["packet_digest"],
            "application_commit": p["application_commit"],
            "planned_development_cases": p["planned_development_cases"],
            "fresh_count_requests": p["fresh_measurement_cases"],
            "amendment_proposal_digest": successor["proposal_digest"],
            "maximum_new_jobs": 14,
            "maximum_new_Messages": 44,
            "maximum_new_counts": 45,
            "actual_provider_contacts": 0,
            "new_spend_usd": "0",
        },
    )
    print(json.dumps(read(a.out / "identity.json")))
