"""Execute only pre-existing external approvals; never create/enable permission.

Default credentials refuse before client construction. This is a quarantined
experiment tool, not an everyday generator. Outputs contain retained public
source and experiment results; handle them as local research artifacts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Literal

import httpx

from src.tools.postgres_pool import close_pool, get_pool
from src.workspace.admission import (
    DISABLED_KEY,
    AdmissionError,
    GenerationInput,
    SourceRef,
    _digest,
)
from src.workspace.measurement import MeasurementAdapter
from src.workspace.provider_adapter import QualificationAdapter
from src.workspace.store import WorkspaceStore


def bound_jobs(
    store: WorkspaceStore, owner: str, packet: dict[str, Any]
) -> list[tuple[dict[str, Any], GenerationInput]]:
    jobs = []
    if (
        packet.get("revision") != "workspace-qualification-packet-v2"
        or len(packet.get("jobs", [])) != 4
    ):
        raise AdmissionError("four_request_v2_packet_required")
    for job in packet["jobs"]:
        raw = job["sealed_input"]
        inputs = GenerationInput(
            **{**raw, "sources": tuple(SourceRef(**s) for s in raw["sources"])}
        )

        # Rebuild rather than trusting exported schemas/digests or caller text.
        def no_contact(request: httpx.Request) -> httpx.Response:
            raise AssertionError("packet binding is read-only")

        adapter = QualificationAdapter(
            store, owner, inputs, transport=httpx.MockTransport(no_contact)
        )
        wire = adapter.request()
        count = {k: v for k, v in wire["body"].items() if k not in {"max_tokens", "temperature"}}
        digest = _digest(inputs.snapshot())
        if (
            job["input_digest"] != digest
            or job["initial_generation"] != wire
            or job["initial_count_request"] != count
            or job["count_request_digest"] != _digest(count)
            or job["measurement_request_id"] != "measurement-" + digest[:40]
            or job["proposed_request_id"] != "qualification-" + digest[:40]
        ):
            raise AdmissionError("packet_request_drift")
        jobs.append((job, inputs))
    if len({job["input_digest"] for job, _ in jobs}) != 4:
        raise AdmissionError("four_distinct_requests_required")
    return jobs


async def execute(
    store: WorkspaceStore,
    owner: str,
    packet: dict[str, Any],
    mode: Literal["measurement", "experiment"],
    *,
    request_id: str | None = None,
    transport: httpx.MockTransport | None = None,
    api_key: str = DISABLED_KEY,
    enabled: bool = False,
) -> dict[str, Any]:
    if mode not in {"measurement", "experiment"}:
        raise AdmissionError("qualification_mode_required")
    jobs = bound_jobs(store, owner, packet)
    if mode == "measurement":
        if request_id is not None:
            raise AdmissionError("measurement_runs_four_named_counts")
    else:
        jobs = [(job, inputs) for job, inputs in jobs if job["proposed_request_id"] == request_id]
        if len(jobs) != 1:
            raise AdmissionError("named_experiment_request_required")
    results = []
    for job, inputs in jobs:
        adapter_type = MeasurementAdapter if mode == "measurement" else QualificationAdapter
        adapter = adapter_type(
            store, owner, inputs, transport=transport, api_key=api_key, enabled=enabled
        )
        started = adapter.start(
            job["measurement_request_id"] if mode == "measurement" else job["proposed_request_id"],
            "0" if mode == "measurement" else "0.40" if inputs.kind == "deep_dive" else "0.25",
        )
        if started["state"] == "running" and not started.get("newly_started"):
            adapter.control.recover(owner, started["id"])
            raise AdmissionError("interrupted_job_requires_reconciliation")
        result = adapter.snapshot(started["id"])
        while result["state"] == "running":
            result = await adapter.advance(started["id"])
        if result["state"] != "ready":
            raise AdmissionError("terminal_job_requires_review")
        results.append(result)
    return {
        "mode": mode,
        "experiment_only": True,
        "everyday_generation": False,
        "checker_qualified": False,
        "transport": "mock" if transport is not None else "provider",
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--mode", choices=["measurement", "experiment"], required=True)
    parser.add_argument("--request-id")
    parser.add_argument(
        "--allow-provider-contact",
        action="store_true",
        help="Operator intent only; existing separate approval still required",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = asyncio.run(
            execute(
                WorkspaceStore(get_pool()),
                args.owner,
                json.loads(args.packet.read_text()),
                args.mode,
                request_id=args.request_id,
                api_key=os.environ.get("ANTHROPIC_API_KEY", DISABLED_KEY),
                enabled=args.allow_provider_contact,
            )
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print("Quarantined run complete; everyday generation remains disabled")
    finally:
        close_pool()


if __name__ == "__main__":
    main()
