"""Run from worktree root using python - < this file. No provider or database."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from src.workspace.assistance import producer_binding
from src.workspace.assistance_contract import schemas
from src.workspace.assistance_policy import TASK_REVISION, render_task_output
from src.workspace.d5_adapter import qualification_producer
from tests.test_workspace_task_policy import (
    ARCHIVE,
    NORMAL,
    RETRIEVAL,
    SAFETY,
    policy,
    response,
    validate,
)

root = Path("outputs/d5/full-abstention-v7/schema-render-controls")
root.mkdir(parents=True, exist_ok=True)
report = {
    "revision": TASK_REVISION,
    "approved": False,
    "basis": "Archived public inputs with synthetic envelopes; software regressions only",
    "provider_contacts": 0,
    "token_count_contacts": 0,
    "new_spend_usd": "0",
    "human_qualification": False,
    "producer": producer_binding(),
    "cases": [],
}
for identity in (SAFETY, RETRIEVAL, NORMAL):
    case = ARCHIVE["cases"][identity]
    projected = response(identity)
    local_wire = schemas(
        list(case["units"]),
        purpose=case["purpose"],
        revision=TASK_REVISION,
        task_policy=policy(identity),
    )
    for schema in local_wire.values():
        Draft202012Validator(schema).validate(projected)
    _, claims = validate(identity, projected)
    rendered = render_task_output(projected, list(case["units"]), case["purpose"], policy(identity))
    artifact = {
        "identity": identity,
        "task_policy": policy(identity),
        "source_units": case["units"],
        "original_archived_output": case["output"],
        "synthetic_projection": projected,
        "schemas": local_wire,
        "rendered": rendered,
    }
    path = root / (identity + ".json")
    path.write_text(json.dumps(artifact, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
    report["cases"].append(
        {
            "identity": identity,
            "factual_claims": len(claims),
            "disposition": rendered["response_disposition"],
            "comparison_unanswered": rendered["comparison_unanswered"],
            "context_requests": rendered["context_requests"],
            "local_and_wire_valid": True,
            "artifact": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    )
summary = Path("outputs/d5/full-abstention-v7/SCHEMA-RENDER-REPORT.json")
summary.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
print(
    json.dumps(
        {"report": str(summary), "cases": len(report["cases"]), "contacts": 0, "qualified": False}
    )
)


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


binding = {
    "revision": TASK_REVISION,
    "type": "offline software regression revision, not a provider validation packet",
    "approved": False,
    "provider_contacts": 0,
    "token_count_contacts": 0,
    "human_qualification": False,
    "archived_packet": "1429b39296792b8bc3d5530d28bcc56600048b149310fc10df30c2ee6048a7a7",
    "producer": report["producer"],
    "qualification_producer": qualification_producer(),
    "controls": [],
}
for control in report["cases"]:
    artifact = json.loads(Path(control["artifact"]).read_text())
    binding["controls"].append(
        {
            "identity": control["identity"],
            "task_policy": artifact["task_policy"],
            "local_schema_sha256": canonical_hash(artifact["schemas"]["local"]),
            "wire_schema_sha256": canonical_hash(artifact["schemas"]["wire"]),
            "selected_units_sha256": canonical_hash(artifact["source_units"]),
            "original_output_sha256": canonical_hash(artifact["original_archived_output"]),
            "synthetic_projection_sha256": canonical_hash(artifact["synthetic_projection"]),
            "rendered_sha256": canonical_hash(artifact["rendered"]),
            "factual_claims": control["factual_claims"],
            "disposition": control["disposition"],
        }
    )
for name in (
    "tests/test_workspace_task_policy.py",
    "tests/test_workspace_task_assistance.py",
    "web/tests/workspace/assistance-panel.test.tsx",
    "web/components/workspace/AssistancePanel.tsx",
    "web/components/workspace/AssistanceTaskContext.tsx",
    "web/lib/workspace/assistanceTypes.ts",
    "web/package-lock.json",
    "web/components/workspace/QualificationResult.tsx",
    "web/tests/workspace/qualification-result.test.tsx",
):
    binding.setdefault("regression_and_ui_files", {})[name] = hashlib.sha256(
        Path(name).read_bytes()
    ).hexdigest()
binding["offline_revision_digest"] = canonical_hash(binding)
destination = Path(
    "planning/14-explore-and-research-modes/d5/evidence/task-bound-v7/OFFLINE-REVISION.json"
)
destination.write_text(json.dumps(binding, sort_keys=True, indent=2) + "\n")
print(
    json.dumps({"offline_revision_digest": binding["offline_revision_digest"], "approved": False})
)
