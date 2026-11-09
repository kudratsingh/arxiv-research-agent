"""Offline engineering controls, NOT a new provider run or scorer for frozen v8r4b.

From the worktree root: python - < planning/14-explore-and-research-modes/d5/tools/request_coverage_report.py
"""

import gzip
import json
from pathlib import Path

from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace.assistance import CoverageChecks
from src.workspace.assistance_contract import digest, resolve_draft, schemas
from src.workspace.assistance_coverage import (
    COVERAGE_REVISION,
    RequestedPart,
    decorate_fixture,
    fixture_checks,
    render,
    review_context,
    review_failed,
    seal_coverage_policy,
)
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial, SourceSpan

ROOT = Path.cwd()
FIXTURE = ROOT / "tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz"


def controls():
    archive = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in archive["materials"]
    )
    results = []
    for case_id, case in archive["cases"].items():
        safety = case_id.endswith("insufficient")
        retrieval = case_id.endswith("retrieval")
        pol = seal_coverage_policy(
            CoverageTaskContext(
                intent="application_assessment"
                if safety
                else "comparison"
                if retrieval
                else "answer",
                requested_parts=tuple(RequestedPart(**p) for p in case["requested_parts"]),
            ),
            case["mode"],
            len({r["work_id"] for r in case["units"].values()}),
            case["question"],
        )
        original = case["output"]
        if safety:
            value = {
                "response": {
                    "disposition": "full_abstention",
                    "reason": "application_context_required",
                    "next_action": "request_context",
                    "context_requests": dict.fromkeys(pol["missing_context"], "required"),
                }
            }
        else:
            value = {
                "response": {
                    **original,
                    "disposition": "comparison_abstention" if retrieval else "answer",
                }
            }
            if retrieval:
                value["response"].pop("comparison_basis")
                value["response"].pop("comparison_claims")
        # Deliberately retain the old scientific statements for negative controls.
        # Metadata is synthetic, all source notes are context, no new coverage credit.
        wrapped = decorate_fixture(value, pol)
        exported = schemas(
            list(case["units"]),
            purpose=case["purpose"],
            revision=COVERAGE_REVISION,
            task_policy=pol,
        )
        for name in ("local", "wire"):
            Draft202012Validator(exported[name]).validate(wrapped)
        refs = {h: EvidenceRef(**r) for h, r in case["units"].items()}
        _, claims = resolve_draft(
            wrapped,
            refs,
            materials,
            purpose=case["purpose"],
            revision=COVERAGE_REVISION,
            task_policy=pol,
        )
        rendered = render(wrapped, list(refs), case["purpose"], pol)
        # Digest binding is tested independently in the production-adapter tests.
        claim_inputs = [
            {"claim_id": c.claim_id, "input_digest": digest({"claim": c.text})} for c in claims
        ]
        ctx = {
            **review_context(pol, rendered, claim_inputs, case["units"]),
            "claim_inputs": claim_inputs,
        }
        check = fixture_checks(
            {"checks": [], "prose_review": "procedural_only", "prose_findings": []}, ctx
        )
        baseline = case["synthetic_baseline_findings"]
        for q in check["claim_quality"]:
            if q["claim_id"] in baseline["bundled"]:
                q["atomicity"] = "bundled"
            if q["claim_id"] in baseline["lost_qualifications"]:
                q["qualifications"][
                    "metric_definition" if case_id.endswith("memory") else "study_scope"
                ] = "lost"
        Draft202012Validator(transform_schema(CoverageChecks)).validate(check)
        blocked = review_failed(CoverageChecks.model_validate(check), rendered)
        results.append(
            {
                "case_id": case_id,
                "original_output_sha256": case["output_sha256"],
                "original_claims": len(original["claims"]),
                "synthetic_claims": len(claims),
                "baseline_findings": baseline,
                "synthetic_quality_gate_blocked": blocked,
                "coverage_complete": rendered["coverage_complete"],
                "request_coverage": rendered["request_coverage"],
                "synthetic_output": wrapped,
                "task_policy": pol,
                "schemas": exported,
                "machine_review": check,
                "remaining": "Source context is not request fulfillment. Semantic repairs and coverage remain unvalidated until a separately approved fresh development run; no human qualification.",
            }
        )
    return {
        "revision": COVERAGE_REVISION,
        "archive_packet": archive["packet_digest"],
        "provenance": "Offline development controls: Codex-attributed synthetic baseline, mocked quality judgments, never provider successes or independent human labels",
        "frozen_results_unchanged": True,
        "new_provider_contacts": 0,
        "new_spend_usd": "0",
        "results": results,
    }


def main():
    report = controls()
    out = ROOT / "outputs/d5/request-coverage-v8/development"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    lines = [
        "# Request-coverage development controls",
        "",
        report["provenance"],
        "",
        "Original machine review: 41 claims, 18 bundled findings, two lost qualifications; 7/8 requests missed. Those results are unchanged.",
        "",
        "| Case | Original claims | Synthetic claims | Known quality defect blocks | Request complete |",
        "|---|---:|---:|---|---|",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['case_id']} | {r['original_claims']} | {r['synthetic_claims']} | {r['synthetic_quality_gate_blocked']} | {r['coverage_complete']} |"
        )
    for r in report["results"]:
        lines += [
            "",
            "## " + r["case_id"],
            "",
            r["remaining"],
            "",
            "Predeclared parts (all context-only or evidence gaps in these deliberately unrepaired controls):",
        ]
        lines += ["- " + p["request"] + " — " + p["status"] for p in r["request_coverage"]]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "cases": len(report["results"]),
                "known_quality_defects_blocked": sum(
                    r["synthetic_quality_gate_blocked"] for r in report["results"]
                ),
                "safety_full_abstention_claims": next(
                    r["synthetic_claims"]
                    for r in report["results"]
                    if r["case_id"].endswith("insufficient")
                ),
                "provider_contacts": 0,
                "output": str(out),
            }
        )
    )


if __name__ == "__main__":
    main()
