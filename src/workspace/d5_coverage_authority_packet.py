"""Prospective one-case coverage-authority development packet; no approval or contact."""

from __future__ import annotations

import argparse
import os
import subprocess
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_contract import schemas
from src.workspace.assistance_coverage import AUTHORITATIVE_COVERAGE_REVISION
from src.workspace.d5_coverage_policy import SHAPED_LIMITS, SHAPED_PROFILE

REVISION = "d5-coverage-authority-development-packet-v3"
PREDECESSOR = "22b8e13bc39d78cb1203f2e613c7c488d7f5a403234840d5ae15dcfa3d44a477"
CASE_ID = "development-v10-learn-coverage"
EXPECTED = (32, 63, 87, "1.828877")
ROOT = Path(__file__).resolve().parents[2]
PREDECESSOR_PATH = (
    ROOT
    / "planning/14-explore-and-research-modes/d5/evidence/coverage-shapes-v9/packet.json.gz"
)


def predecessor() -> dict[str, Any]:
    from src.workspace.d5_benchmark import read

    value = read(PREDECESSOR_PATH)
    if (
        value["packet_digest"] != PREDECESSOR
        or _digest({k: v for k, v in value.items() if k != "packet_digest"}) != PREDECESSOR
    ):
        raise AdmissionError("coverage_authority_predecessor_changed")
    return value


def reseal(original: dict[str, Any]) -> dict[str, Any]:
    """Change schema/prompt/producer only; preserve source selection and task."""
    import json

    from src.workspace.assistance import build_wire, capacity, producer_binding

    result = deepcopy(original)
    result["schema_revision"] = AUTHORITATIVE_COVERAGE_REVISION
    result["task_policy"]["revision"] = AUTHORITATIVE_COVERAGE_REVISION
    result["producer"]["code"] = producer_binding()
    result["response_schemas"] = schemas(
        list(result["units"]),
        purpose=result["response_purpose"],
        revision=AUTHORITATIVE_COVERAGE_REVISION,
        task_policy=result["task_policy"],
    )
    for stage in ("draft", "repair"):
        result["stage_contracts"][stage]["output_schema"] = result["response_schemas"]["wire"]
    context = json.loads(original["candidate_initial_wire"]["messages"][0]["content"])
    context["sealed_request"]["schema_revision"] = AUTHORITATIVE_COVERAGE_REVISION
    context["sealed_request"]["task_policy"] = result["task_policy"]
    context["output_schema"] = result["response_schemas"]["wire"]
    result["candidate_initial_wire"] = build_wire(context)
    result["capacity"] = capacity(result)
    return result


def expected_case(corpus: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from src.workspace.d5_coverage_packet import canonical_request

    old = predecessor()["cases"][0]
    sealed = reseal(
        canonical_request(old["sealed"], corpus) if corpus is not None else old["sealed"]
    )
    return {
        **deepcopy(old),
        "id": CASE_ID,
        "sealed": sealed,
        "wire_digest": _digest(sealed["candidate_initial_wire"]),
        "predecessor_case": old["id"],
        "prior_outcome": "failed; immutable and not replayed",
    }


def verify_shapes(packet: dict[str, Any]) -> None:
    from anthropic import transform_schema

    from src.workspace.assistance import CoverageChecks
    from src.workspace.d5_coverage_packet import measurement_bindings
    from src.workspace.d5_coverage_policy import PROGRAM_LIMITS
    from src.workspace.d5_operations import ROUTES

    if (
        packet.get("predecessor_packet") != PREDECESSOR
        or packet.get("limits") != SHAPED_LIMITS
        or packet.get("scope_profile") != SHAPED_PROFILE
        or packet.get("planned_development_cases") != [CASE_ID]
        or packet.get("measurement_cases") != [CASE_ID]
        or packet.get("cases") != [expected_case(packet["corpus"])]
        or packet.get("probes") != []
        or packet.get("measurement_reuse") != []
        or packet.get("human_qualification") is not False
        or packet.get("operation_routes") != ROUTES
        or packet.get("measurements") != measurement_bindings(packet["cases"])
        or packet.get("checker_schemas")
        != {"local": CoverageChecks.model_json_schema(), "wire": transform_schema(CoverageChecks)}
        or packet["programme"]["limits"] != PROGRAM_LIMITS
        or packet["programme"]["capacity_proposal_digest"]
        != packet["programme_amendment"]["proposal_digest"]
        or packet["program_id"] != packet["programme"]["program_id"]
    ):
        raise AdmissionError("coverage_authority_schedule_schema_or_binding_changed")
    expiry = datetime.fromisoformat(packet["programme"]["expires_at"])
    if expiry.tzinfo is None:
        raise AdmissionError("coverage_authority_expiry_required")


def freeze(snapshot: dict[str, Any]) -> dict[str, Any]:
    from anthropic import transform_schema

    from src.workspace.assistance import CoverageChecks
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_coverage_packet import measurement_bindings
    from src.workspace.d5_freeze import code_bindings
    from src.workspace.d5_operations import ROUTES

    old = predecessor()
    version_ids = {c["version_id"] for c in old["corpus"]}
    corpus = [
        r["data"]
        for r in snapshot["tables"]["workspace_versions"]
        if r["version_id"] in version_ids
    ]
    packet = {
        **deepcopy(old),
        "revision": REVISION,
        "approved": False,
        "predecessor_packet": PREDECESSOR,
        "scope_profile": SHAPED_PROFILE,
        "limits": deepcopy(SHAPED_LIMITS),
        "cases": [expected_case(corpus)],
        "corpus": corpus,
        "planned_development_cases": [CASE_ID],
        "measurement_cases": [CASE_ID],
        "measurement_reuse": [],
        "program_id": snapshot["program_id"],
        "history": snapshot["history"],
        "snapshot_digest": _digest(snapshot),
        "programme": snapshot["programme"],
        "programme_amendment": {
            "proposal_digest": snapshot["programme"]["capacity_proposal_digest"]
        },
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "operation_routes": ROUTES,
        "checker_schemas": {
            "local": CoverageChecks.model_json_schema(),
            "wire": transform_schema(CoverageChecks),
        },
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "follow_up": "One fresh Learn diagnostic; comparison and full abstention are offline controls only. Not held-out validation or human qualification.",
    }
    packet.pop("packet_digest", None)
    packet["measurements"] = measurement_bindings(packet["cases"])
    packet["packet_digest"] = _digest(packet)
    verify_shapes(packet)
    return packet


def main() -> None:
    from src.workspace.d5_benchmark import database, read, write
    from src.workspace.d5_coverage_replay import capture
    from src.workspace.store import WorkspaceStore

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["capture", "freeze"])
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise AdmissionError("coverage_offline_disabled_key_required")
    if args.verb == "capture":
        with database(os.environ["D5_LEDGER_POSTGRES_URL"]) as pool:
            store = WorkspaceStore(pool)
            value = capture(store, store, "research-evaluation-20261105-v1", expected=EXPECTED)
        write(args.snapshot, value)
    else:
        if args.packet is None:
            parser.error("--packet required")
        write(args.packet, freeze(read(args.snapshot)))


if __name__ == "__main__":
    main()
