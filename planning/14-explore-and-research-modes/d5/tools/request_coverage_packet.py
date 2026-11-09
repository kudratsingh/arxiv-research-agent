"""Export a prospective, unapproved three-case development packet. No provider I/O.

Run from worktree root, via stdin. Only the named disposable database is writable.
Export never creates a programme, grant, reservation, contact or funded job.
"""

import argparse
import gzip
import hashlib
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from anthropic import transform_schema
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.workspace.assistance import AssistanceService, CoverageChecks, producer_binding
from src.workspace.assistance_contract import digest
from src.workspace.assistance_coverage import COVERAGE_REVISION
from src.workspace.assistance_routes import NewAssistanceInput
from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.d5_adapter import qualification_producer
from src.workspace.d5_operations import ROUTES
from src.workspace.store import WorkspaceStore

ROOT = Path.cwd()
FILES = (
    [
        "src/workspace/" + p
        for p in (
            "assistance.py",
            "assistance_routes.py",
            "assistance_policy.py",
            "assistance_coverage.py",
            "assistance_contract.py",
            "d5_adapter.py",
            "d5_results.py",
            "d5_operations.py",
            "provider_adapter.py",
            "admission.py",
            "qualification_budget.py",
            "qualification_accounting.py",
            "grounding.py",
        )
    ]
    + [
        "web/components/workspace/" + p
        for p in ("AssistancePanel.tsx", "AssistanceTaskContext.tsx", "QualificationResult.tsx")
    ]
    + [
        "web/lib/workspace/assistanceTypes.ts",
        "web/contract/openapi.json",
        "planning/14-explore-and-research-modes/d5/tools/request_coverage_packet.py",
    ]
)


def bindings():
    return {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FILES}


def main():
    args = argparse.ArgumentParser(description=__doc__)
    group = args.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", type=Path)
    group.add_argument("--verify", type=Path)
    opts = args.parse_args()
    assert os.environ.get("ANTHROPIC_API_KEY") == "local-preview-disabled"
    assert os.environ.get("WORKSPACE_D5_OFFLINE") == "1", "Explicitly enable offline previews only"
    if opts.verify:
        data = json.loads(gzip.decompress(opts.verify.read_bytes()))
        packet_digest = data.pop("packet_digest")
        assert digest(data) == packet_digest
        assert data["code_bindings"] == bindings()
        assert (
            data["producer"] == producer_binding()
            and data["qualification_producer"] == qualification_producer()
        )
        assert not data["approved"] and data["provider_contacts"] == 0
        for c in data["cases"]:
            assert digest(c["sealed"]) == c["request_digest"]
            assert digest(c["initial_wire"]) == c["wire_digest"]
        print(json.dumps({"verified": packet_digest, "approved": False, "contacts": 0}))
        return
    assert not opts.export.exists(), "Choose a new prospective revision, never overwrite"
    url = os.environ["D5_COVERAGE_PACKET_DB"]
    parsed = urlsplit(url)
    assert (
        parsed.hostname in ("localhost", "127.0.0.1")
        and parsed.port == 15488
        and parsed.path == "/workspace_d5_coverage_packet_v8"
    )
    archive = json.loads(
        gzip.decompress(
            (ROOT / "tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz").read_bytes()
        )
    )
    selected = ["v8-learn-conditions", "v8-research-retrieval", "v8-research-insufficient"]
    cases = []
    with ConnectionPool(url, min_size=1, max_size=2) as pool:
        store = WorkspaceStore(pool)
        store.migrate()
        service = AssistanceService(store)
        for case_id in selected:
            case = archive["cases"][case_id]
            refs = list(case["units"].values())
            owner = "coverage-proposal-only"
            for m in archive["materials"]:
                if m["material_id"] not in {r["material_id"] for r in refs}:
                    continue
                # Copied public retained material. This is replay, not fresh intake.
                work = {
                    "work_id": m["work_id"],
                    "version_id": m["version_id"],
                    "source_id": "arxiv-cs-ai",
                    "source_record_id": m["work_id"],
                    "title": "Archived public development control",
                    "url": "https://arxiv.org/abs/" + m["work_id"].removeprefix("arxiv:"),
                    "abstract": m["pages"][0],
                    "access_state": m["scope"],
                    "version_label": m["version_id"].split(":")[-1],
                    "first_seen_at": "2026-11-08T00:00:00Z",
                    "fetched_at": "2026-11-08T00:00:00Z",
                    "content_hash": m["source_hash"],
                }
                store.ingest(
                    "arxiv-cs-ai",
                    [work],
                    {"status": "snapshot_replay", "fetched_at": work["fetched_at"]},
                    {},
                )
                with pool.connection() as conn:
                    conn.execute(
                        "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s) ON CONFLICT(material_id) DO NOTHING",
                        (
                            m["material_id"],
                            m["version_id"],
                            m["content_hash"],
                            m["scope"],
                            Jsonb(m),
                        ),
                    )
            pid = None
            if case["mode"] == "research":
                pid = "project-" + hashlib.sha256(case_id.encode()).hexdigest()[:32]
                WorkspaceContext(store).write_project(
                    owner,
                    ProjectWrite(
                        id=pid,
                        revision=0,
                        request_id=case_id,
                        data=ProjectData(
                            title="Unapproved development context",
                            question=case["question"],
                            scope="Selected archived public abstracts only",
                            constraints="No human qualification; no provider execution without separate approval",
                        ),
                    ),
                )
            intent = (
                "application_assessment"
                if case_id.endswith("insufficient")
                else "comparison"
                if case_id.endswith("retrieval")
                else "answer"
            )
            value = NewAssistanceInput(
                mode=case["mode"],
                work_id=refs[0]["work_id"],
                version_id=refs[0]["version_id"],
                material_ids=tuple(dict.fromkeys(r["material_id"] for r in refs)),
                span_ids=tuple(dict.fromkeys(r["span_id"] for r in refs)),
                unit_ids=tuple(case["units"]),
                follow_up=case["question"],
                project_id=pid,
                project_revision=1 if pid else None,
                task_context={"intent": intent, "requested_parts": case["requested_parts"]},
            )
            preview = service.preview(owner, value)
            cases.append(
                {
                    "id": "development-" + case_id,
                    "cohort": "archived_development_not_held_out",
                    "input": value.model_dump(mode="json"),
                    "sealed": preview.request,
                    "request_digest": digest(preview.request),
                    "initial_wire": preview.request["candidate_initial_wire"],
                    "wire_digest": digest(preview.request["candidate_initial_wire"]),
                    "initial_count_request": {
                        k: v
                        for k, v in preview.request["candidate_initial_wire"].items()
                        if k not in ("max_tokens", "temperature")
                    },
                }
            )
    data = {
        "revision": "request-coverage-development-proposal-v1",
        "contract": COVERAGE_REVISION,
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "code_bindings": bindings(),
        "producer": producer_binding(),
        "qualification_producer": qualification_producer(),
        "approved": False,
        "provider_contacts": 0,
        "workflow_grants": False,
        "historical_packet": archive["packet_digest"],
        "intake_basis": "Retained public snapshot replay, not fresh intake; local replay metadata observation clock 2026-11-08 is synthetic and not a publication or successful-fetch claim",
        "baseline": {
            "jobs": 30,
            "messages": 61,
            "counts": 81,
            "estimated_usd": "1.779493",
            "pending_usd": "0",
            "unknown_usd": "0",
        },
        "cases": cases,
        "checker_wire_schema": transform_schema(CoverageChecks),
        "routes": ROUTES,
        "limits_proposal": {
            "initial_counts": 3,
            "jobs": 3,
            "messages_max": 12,
            "paired_counts_max": 12,
            "per_job_usd": "0.45",
            "new_usd_max": "1.35",
            "max_repairs": 1,
            "max_calls_per_job": 4,
            "input_allowance": 16000,
        },
        "dynamic_requests": "Actual checks, repair and recheck are response-derived under the bound code/schema, journaled with exact digests; future output-dependent requests are not invented.",
        "human_review": None,
    }
    data["packet_digest"] = digest(data)
    opts.export.parent.mkdir(parents=True, exist_ok=True)
    opts.export.write_bytes(
        gzip.compress((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode(), mtime=0)
    )
    print(
        json.dumps(
            {
                "packet_digest": data["packet_digest"],
                "cases": len(cases),
                "approved": False,
                "provider_contacts": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
