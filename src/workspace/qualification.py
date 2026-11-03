"""Read-only, zero-contact packet builder. This command never writes approvals.

Initial wire bodies are exact. Check/repair bodies depend on future output and
must be sealed and counted immediately before each separately approved contact.
Human judgments remain blank; perturbation categories are engineering intent.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import httpx
from anthropic import transform_schema

from src.tools.postgres_pool import close_pool, get_pool
from src.workspace.admission import _digest
from src.workspace.grounding import ClaimKind, ResearchClaim, evidence_ref
from src.workspace.material import SourceMaterial
from src.workspace.provider_adapter import Checks, QualificationAdapter, StudyDraft, prepare
from src.workspace.store import WorkspaceStore


def review_cases(materials: list[SourceMaterial]) -> list[dict[str, Any]]:
    cases = []
    for material in materials[:3]:
        span = next(span for span in material.spans if span.text.strip())
        ref = evidence_ref(material, span, end=min(span.end, span.start + 250))
        base = ResearchClaim(
            "review", ref.quote, ClaimKind.FACTUAL, (ref,), required_scope=material.scope
        )
        variants = {
            "verbatim_source_statement": base,
            "unsupported_generalization": replace(
                base,
                text="The method guarantees perfect results for every dataset with zero computation.",
            ),
            "missing_evidence": replace(base, evidence=()),
            "wrong_source_version": replace(
                base, evidence=(replace(ref, version_id=ref.version_id + ":different"),)
            ),
            "scope_violation": replace(
                base, required_scope="full_text", required_section="methods"
            ),
            "extraction_failure": replace(
                base, evidence=(replace(ref, quote=ref.quote + " [missing extraction]"),)
            ),
            "unsupported_numeric_result": replace(
                base, text="The method improves every reported result by exactly 99.9 percent."
            ),
            "proposed_experiment": replace(
                base,
                kind=ClaimKind.INFERENCE,
                text="Propose testing this assumption against a fixed baseline.",
                inference_label="Proposed experiment; not a reported finding",
            ),
        }
        for challenge, claim in variants.items():
            claim = replace(
                claim, claim_id="case-" + _digest([material.material_id, challenge])[:20]
            )
            cases.append(
                {
                    "id": claim.claim_id,
                    "challenge_type": challenge,
                    "challenge_basis": "engineering perturbation; not a human judgment or measured checker error",
                    "claim": asdict(claim),
                    "source_material": asdict(material),
                    "human_label": None,
                    "human_reason": None,
                    "annotator": None,
                    "checker_verdict": None,
                    "review_status": "unlabelled",
                }
            )
    return cases


def packet(store: WorkspaceStore, owner: str, proposal: dict[str, Any]) -> dict[str, Any]:
    jobs, selected = [], []

    def no_contact(request: httpx.Request) -> httpx.Response:
        raise AssertionError("packet construction must not contact any transport")

    for item in proposal["sources"]:
        inputs = prepare(
            store, owner, item["job_kind"], [item["material_id"]], span_ids=item.get("span_ids", [])
        )
        adapter = QualificationAdapter(
            store, owner, inputs, transport=httpx.MockTransport(no_contact)
        )
        initial = adapter.request()
        count = {k: v for k, v in initial["body"].items() if k not in {"max_tokens", "temperature"}}
        jobs.append(
            {
                "proposed_request_id": "qualification-" + _digest(inputs.snapshot())[:40],
                "sealed_input": inputs.snapshot(),
                "input_digest": _digest(inputs.snapshot()),
                "initial_generation": initial,
                "initial_count_request": count,
                "count_request_digest": _digest(count),
                "measurement_request_id": "measurement-" + _digest(inputs.snapshot())[:40],
                "measured_tokens": None,
                "dynamic_stages": ["check", "optional repair", "mandatory repair recheck"],
                "status": "unapproved; no provider contact",
            }
        )
        _, materials = adapter._context()
        if item["job_kind"] == "summary":
            selected.append(materials[0])
    return {
        "revision": "workspace-qualification-packet-v2",
        "approved": False,
        "provider_contacts": 0,
        "actual_usd": "0",
        "jobs": jobs,
        "claim_span_review": review_cases(selected),
        "everyday_generation": False,
        "checker_qualified": False,
        "schemas": {
            name: {
                "local": model.model_json_schema(),
                "wire": transform_schema(model),
                "local_digest": _digest(model.model_json_schema()),
                "wire_digest": _digest(transform_schema(model)),
            }
            for name, model in (("draft_and_repair", StudyDraft), ("checker", Checks))
        },
        "measurement_only": {
            "purpose": "workspace-measurement-only",
            "count_contacts_max": 4,
            "messages_contacts_max": 0,
            "count_requests": [
                {
                    "request_id": job["measurement_request_id"],
                    "input_digest": job["input_digest"],
                    "count_request_digest": job["count_request_digest"],
                }
                for job in jobs
            ],
            "approval_record": None,
        },
        "small_sample_caveat": "Four jobs and 24 unlabelled review cases cannot certify a false-pass bound. Human review and a separately scoped larger checker experiment may be needed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument(
        "--proposal",
        type=Path,
        default=Path("planning/11-daily-research-workspace/generation-trial.proposal.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = WorkspaceStore(get_pool())
    try:
        result = packet(store, args.owner, json.loads(args.proposal.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(
            f"Wrote {len(result['jobs'])} exact initial requests and {len(result['claim_span_review'])} unlabelled cases; provider contacts 0, approval false"
        )
    finally:
        close_pool()


if __name__ == "__main__":
    main()
