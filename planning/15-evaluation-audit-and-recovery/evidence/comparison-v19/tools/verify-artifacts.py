# ruff: noqa: E402
"""Read-only test of frozen packet artifacts, hashes, privacy and same-packet proof."""

import argparse
from collections import Counter
from pathlib import Path

from comparison_artifact_support import _digest, load_packet, read, scan_package, sha

from src.workspace.assistance_keyed_checks import schemas as probe_schemas
from src.workspace.d5_campaign_operator import template
from src.workspace.d5_freeze import compile_inputs
from src.workspace.provider_schema_compat import guard

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--packet-dir", type=Path, required=True)
parser.add_argument("--application-commit", required=True)
parser.add_argument("--require-replay", action="store_true")
args = parser.parse_args()
root = args.packet_dir.resolve()
packet_path, packet = load_packet(root, args.application_commit)
identity = read(root / "IDENTITY.json")
assert identity["application_commit"] == args.application_commit
assert identity["packet_digest"] == packet["packet_digest"]
assert identity["packet_file_sha256"] == sha(packet_path)
assert identity["proposal_digest"] == packet["campaign_extension"]["proposal_digest"]
assert identity["scope_id"] == "d5-" + packet["packet_digest"][:24]
compiled = compile_inputs(packet)
assert read(root / "compiled-inputs.json.gz") == compiled
assert identity["compiled_inputs_digest"] == _digest(compiled)
assert identity["compiled_inputs_file_sha256"] == sha(root / "compiled-inputs.json.gz")
assert read(root / "AUTHORIZATION-TEMPLATE.json") == template(packet)
public_authorization = read(root / "AUTHORIZATION-TEMPLATE.json")
assert public_authorization["approved"] is False
assert all(
    public_authorization[key] is None
    for key in ("approved_by", "approval_source", "approved_at", "expires_at")
)
assert public_authorization["budget_adjustment_approved"] is False
assert public_authorization["historical_uncertainty_exception_approved"] is False
assert read(root / "PROPOSAL.json") == packet["campaign_extension"]
assert _digest(packet["campaign_extension"]["core"]) == identity["proposal_digest"]
assert read(root / "ANSWERABILITY.json") == packet["answerability"]
assert read(root / "SCORING.json") == packet["scoring"]
routes = read(root / "ROUTES-AND-LIMITS.json")
assert routes["operation_routes"] == packet["operation_routes"]
assert routes["operation_deadlines"] == packet["operation_deadlines"]
assert routes["campaign_limits"] == packet["limits"]
assert routes["programme_limits"] == packet["campaign_extension"]["core"]["limits"]
assert routes["period_limits"] == packet["campaign_extension"]["core"]["period_limits"]
assert routes["expiry_policy"] == packet["expiry_policy"]
assert routes["campaign_limits"]["new_usd"] == "14.00"
assert routes["programme_limits"]["usd"] == "22"
assert routes["period_limits"] == {"day_usd": "22", "month_usd": "22"}
assert (
    read(root / "SOURCE-BINDINGS.json") == packet["source_bindings"] == identity["source_bindings"]
)
assert identity["source_bindings_digest"] == _digest(packet["source_bindings"])
machine = read(root / "MACHINE-REFERENCE.json")
assert machine["human_qualification"] is False and machine["human_labels"] is None
assert machine["references"] == packet["probe_references"]
assert (
    machine["reference_digest"]
    == packet["probe_reference_digest"]
    == _digest(machine["references"])
)
assert Counter(v["reference"] for v in machine["references"].values()) == {
    "supported": 10,
    "unsupported": 10,
}
provenance = read(root / "SOURCE-PROVENANCE.json")
assert (
    provenance["bibliographic_provenance_newly_verified"] is False
    and provenance["new_intake"] is False
)
assert provenance["held_out_evidence"] is False
assert provenance["development_paper_ids"] == ["2210.03629v3", "2310.11511v1"]
assert provenance["evaluation_snapshot_kind"] == "inherited_exposed_benchmark_abstracts"
index = read(root / "REQUEST-INDEX.json.gz")
assert list(index) == packet["schedule"] and len(index) == 14
assert identity["request_index_digest"] == _digest(index)
assert identity["request_index_file_sha256"] == sha(root / "REQUEST-INDEX.json.gz")
for case in [*packet["cases"], *packet["probes"]]:
    key = case["id"]
    probe = key in {p["id"] for p in packet["probes"]}
    row = index[key]
    body = case["wire"] if probe else case["sealed"]["candidate_initial_wire"]
    assert row["initial_message_body"] == body
    assert row["initial_message_digest"] == _digest(body)
    count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
    assert row["paired_count_body"] == count and row["paired_count_digest"] == _digest(count)
    assert count["model"] == body["model"] == row["model"]
    assert row["input_digest"] == _digest(compiled[key]["input"])
    context = __import__("json").loads(body["messages"][0]["content"])
    schemas = probe_schemas(context, probe=True) if probe else case["sealed"]["response_schemas"]
    assert read(root / row["local_output_schema"]) == schemas["local"]
    assert (
        read(root / row["wire_output_schema"])
        == schemas["wire"]
        == body["output_config"]["format"]["schema"]
    )
    selected = read(root / row["selected_public_context"])
    assert selected["selected_units"] == case["sealed"]["units"]
    assert selected["selected_sources"] == case["sealed"]["sources"]
    assert selected["exact_initial_request_context"] == context
    if not probe:
        assert row["future_dynamic_requests"]["operations"] == [
            "check",
            "one_repair_if_required",
            "mandatory_recheck_after_repair",
        ]
    assert guard(body)["planning_headroom_pass"] and guard(count)["planning_headroom_pass"]
for name in ("MANIFEST.json", "MANIFEST-PROTECTED-REPLAY.json"):
    path = root / name
    if path.exists():
        for relative, expected_sha in read(path)["files"].items():
            assert (root / relative).resolve().is_relative_to(root)
            assert sha(root / relative) == expected_sha, relative
if args.require_replay:
    proof = read(root / "PROTECTED-REPLAY.json")
    assert (
        proof["application_commit"] == args.application_commit
        and proof["packet_digest"] == packet["packet_digest"]
    )
    assert proof["packet_file_sha256"] == sha(packet_path)
    assert proof["same_frozen_packet"] is True and proof["new_freeze"] is False
    assert (
        proof["jobs"],
        proof["messages"],
        proof["paired_counts"],
        proof["duplicate_dispatches"],
    ) == (14, 44, 44, 0)
    guards = read(root / "SDK-SCHEMA-GUARDS.json.gz")
    assert (
        guards["packet_digest"] == packet["packet_digest"]
        and guards["application_commit"] == args.application_commit
    )
    assert len(guards["operations"]) == 44
    expected = {c["id"]: 4 for c in packet["cases"]} | {c["id"]: 1 for c in packet["probes"]}
    assert Counter(v["case_id"] for v in guards["operations"]) == expected
    for receipt in guards["operations"]:
        assert receipt["same_model_exact_count_pair"] is True
        assert receipt["synthetic_output_request_schema_validation"]["errors"] == []
        assert (
            receipt["generation_request_digest"]
            == receipt["generation_schema_guard"]["request_digest"]
        )
        assert (
            receipt["paired_count_request_digest"]
            == receipt["paired_count_schema_guard"]["request_digest"]
        )
        for field in ("generation_schema_guard", "paired_count_schema_guard"):
            assert receipt[field]["documented_limits_pass"] is True
            assert receipt[field]["planning_headroom_pass"] is True
            assert receipt[field]["remote_compiler_acceptance"] == "UNMEASURED"
        if receipt["operation_index"] == 0:
            assert (
                receipt["generation_request_digest"]
                == index[receipt["case_id"]]["initial_message_digest"]
            )
            assert (
                receipt["paired_count_request_digest"]
                == index[receipt["case_id"]]["paired_count_digest"]
            )
checked = scan_package(root)
print(
    __import__("json").dumps(
        {
            "passed": True,
            "application_commit": args.application_commit,
            "packet_digest": packet["packet_digest"],
            "initial_identities": 14,
            "privacy_checked_files": len(checked),
            "same_packet_replay_required_and_verified": args.require_replay,
            "real_provider_contacts": 0,
            "approved": False,
        },
        indent=2,
    )
)
