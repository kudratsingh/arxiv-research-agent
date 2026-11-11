"""Prospective, immutable D5 system benchmark. No execution or authorization.

End-to-end cases use the production mode ranker and its finite edition. Reference
IDs are diagnostic annotations only and never replace retrieved source context.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anthropic import transform_schema

from src.workspace.admission import AdmissionError, GenerationInput, _digest
from src.workspace.assistance import AssistanceInput, AssistanceService, Checks, build_wire
from src.workspace.assistance_contract import REVISION
from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.d5_adapter import prepare_input, qualification_producer, seal_procedural_request
from src.workspace.d5_evidence import POLICY, select
from src.workspace.d5_scope import LIMITS
from src.workspace.grounding import ClaimKind, EvidenceRef, ResearchClaim, claim_input_digest
from src.workspace.material import SourceMaterial, SourceSpan
from src.workspace.mode_ranking import (
    MODE_POLICY_VERSION,
    known_mode_date,
    rank_mode_items,
    select_mode_edition,
)
from src.workspace.store import WorkspaceStore

REVISION_BENCHMARK = "d5-system-benchmark-v1"
CLOCK = "2026-11-05T12:00:00+00:00"
RUN_OWNER = "d5-v7-validation-run"
COUNT_OWNER = "d5-v7-validation-measure"
QUESTIONS = (
    (
        "dev-learn",
        "development",
        "learn",
        "Explain ReAct's mechanism and what its excerpts cannot establish.",
    ),
    (
        "dev-compare",
        "development",
        "research",
        "Compare ReAct and Self-RAG evidence and evaluation limitations.",
    ),
    ("learn-method", "fresh_system", "learn", "Explain the reported mechanism and prerequisites."),
    ("learn-assumptions", "fresh_system", "learn", "Which assumptions qualify the main result?"),
    (
        "learn-build",
        "fresh_system",
        "learn",
        "What would an implementer need beyond this abstract?",
    ),
    ("learn-results", "fresh_system", "learn", "Distinguish measured results from proposed use."),
    (
        "research-memory",
        "fresh_system",
        "research",
        "How do agent memory and context management methods address long research workflows?",
    ),
    (
        "research-retrieval",
        "fresh_system",
        "research",
        "How do retrieval and incomplete relevance judgments affect RAG evaluation?",
    ),
    (
        "research-evaluation",
        "fresh_system",
        "research",
        "What assumptions limit LLM judge evaluation and claim verification?",
    ),
    (
        "research-insufficient",
        "fresh_system",
        "research",
        "Does reinforcement learning control evidence establish safe deployment on my unspecified hardware?",
    ),
)

# A new cohort, fixed before its outputs exist. v7r2 cases remain diagnostics.
PROCEDURAL_QUESTIONS = (
    *QUESTIONS[:2],
    (
        "v8-learn-mechanism",
        "fresh_system",
        "learn",
        "Describe the selected method's inputs, steps and outputs; distinguish stated prerequisites from unavailable details.",
    ),
    (
        "v8-learn-conditions",
        "fresh_system",
        "learn",
        "Which stated conditions bound the selected abstract's claims, and what remains unspecified?",
    ),
    (
        "v8-learn-reproduce",
        "fresh_system",
        "learn",
        "Plan what source evidence to collect before attempting a small reproducible implementation.",
    ),
    (
        "v8-learn-measurement",
        "fresh_system",
        "learn",
        "Which claims report measured results, and what applications, if any, does the excerpt propose?",
    ),
    (
        "v8-research-memory",
        "fresh_system",
        "research",
        "What evidence describes memory error persistence and valid-information retention in agents?",
    ),
    (
        "v8-research-retrieval",
        "fresh_system",
        "research",
        "Compare how selected sources evaluate retrieval relevance, noting incompatible tasks and missing judgments.",
    ),
    (
        "v8-research-verification",
        "fresh_system",
        "research",
        "What evidence supports uncertainty-aware claim verification, and what counterevidence or validation is missing?",
    ),
    (
        "v8-research-insufficient",
        "fresh_system",
        "research",
        "Can these abstracts establish a safe learned controller for an unspecified Rocket Twin vehicle and operating envelope?",
    ),
)


def question_specifications(revision: str | None) -> tuple[Any, ...]:
    if revision is None:
        return QUESTIONS
    if revision == "procedural-v8":
        return PROCEDURAL_QUESTIONS
    raise AdmissionError("d5_unknown_frozen_cohort")


def case_pool(corpus: list[Any], cohort: str, excluded: list[str]) -> list[Any]:
    return [i for i in corpus if cohort != "fresh_system" or i["version_id"] not in excluded]


def reading_minutes(key: str, mode: str, index: int) -> int:
    return 45 if key == "learn-results" or mode == "learn" and index - 2 >= 3 else 15


def execution_owners(packet: dict[str, Any]) -> tuple[str, str]:
    """A new prospective cohort cannot reuse stopped financial identities."""
    from src.workspace.d5_coverage_packet import is_packet, owners

    if is_packet(packet):
        return owners(packet)
    if packet.get("cohort_revision") == "procedural-v8":
        return "d5-v8-validation-run", "d5-v8-validation-measure"
    return RUN_OWNER, COUNT_OWNER


def code_bindings() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    names = [
        "d5_freeze.py",
        "d5_coverage_policy.py",
        "d5_coverage_packet.py",
        "d5_coverage_shapes_packet.py",
        "d5_coverage_authority_packet.py",
        "d5_coverage_replay.py",
        "d5_operations.py",
        "programme_amendments.py",
        "programme_successors.py",
        "programme_third_amendment.py",
        "programme_capacity.py",
        "migrations/017_programme_capacity_amendments.sql",
        "migrations/016_programme_third_amendments.sql",
        "migrations/015_programme_successor_amendments.sql",
        "d5_measurements.py",
        "migrations/014_programme_amendments.sql",
        "d5_benchmark.py",
        "d5_scope.py",
        "d5_authorization.py",
        "d5_scoring.py",
        "d5_reviews.py",
        "d5_review_scoring.py",
        "d5_fixture.py",
        "d5_results.py",
        "d5_routes.py",
        "d5_operator.py",
        "d5_evidence.py",
        "mode_ranking.py",
        "ranking.py",
        "grounding.py",
        "material.py",
        "assistance.py",
        "assistance_contract.py",
        "assistance_coverage_shapes.py",
        "executor.py",
        "context_store.py",
        "migrations/012_d5_qualification_scope.sql",
        "migrations/013_d5_stage_authorizations.sql",
    ]
    paths = [root / "src/workspace" / name for name in names]
    paths += [
        root / "web/components/workspace/QualificationResult.tsx",
        root / "web/components/workspace/ScoredSections.tsx",
        root / "web/components/workspace/AssistancePanel.tsx",
        root / "planning/14-explore-and-research-modes/d5/tools/prepare-opus-v5.py",
        root / "planning/14-explore-and-research-modes/d5/tools/prepare-capacity-v8.py",
        root / "planning/14-explore-and-research-modes/d5/tools/prepare-prose-v6.py",
        root / "planning/14-explore-and-research-modes/d5/tools/prepare-gap-v7.py",
    ]
    paths += [
        root / name
        for name in (
            "web/components/workspace/ReaderContent.tsx",
            "web/components/workspace/LearningThread.tsx",
            "web/lib/workspace/assistanceTypes.ts",
            "web/lib/workspace/assistanceLinks.ts",
            "web/contract/openapi.json",
            "src/api/app.py",
        )
    ]
    if any(not path.is_file() for path in paths):
        raise AdmissionError("d5_implementation_incomplete_cannot_freeze")
    return {
        str(p.relative_to(root)): "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
    }


def verify(packet: dict[str, Any]) -> None:
    content = {k: v for k, v in packet.items() if k != "packet_digest"}
    if packet.get("packet_digest") != _digest(content) or packet.get("approved") is not False:
        raise AdmissionError("d5_packet_digest_or_permission_changed")
    if packet.get("code") != code_bindings() or packet.get("adapter") != qualification_producer():
        raise AdmissionError("d5_frozen_producer_changed")
    for case in packet["cases"]:
        if case.get("sealed") and case["wire_digest"] != _digest(
            case["sealed"]["candidate_initial_wire"]
        ):
            raise AdmissionError("d5_wire_digest_changed")
    from src.workspace.d5_coverage_packet import is_packet, verify_controls

    if is_packet(packet):
        verify_controls(packet)
        return
    if packet.get("planned_development_cases", ["dev-learn", "dev-compare"]) not in (
        ["dev-learn"],
        ["dev-learn", "dev-compare"],
    ):
        raise AdmissionError("d5_declared_development_scope_required")
    verify_discovery(packet)


def verify_discovery(packet: dict[str, Any]) -> None:
    """Re-execute production discovery from frozen inputs, never references.

    This runs in both offline and paid admission verification. Frozen context is
    not blindly trusted just because its packet digest was recomputed.
    """
    materials = [
        SourceMaterial(
            **{
                **m,
                "pages": tuple(m["pages"]),
                "warnings": tuple(m["warnings"]),
                "page_numbers": tuple(m["page_numbers"]) if m["page_numbers"] is not None else None,
                "spans": tuple(SourceSpan(**s) for s in m["spans"]),
            }
        )
        for m in packet["materials"]
    ]
    specifications = question_specifications(packet.get("cohort_revision"))
    if len(packet["cases"]) != len(specifications):
        raise AdmissionError("d5_frozen_case_count_changed")
    for index, (case, specification) in enumerate(
        zip(packet["cases"], specifications, strict=True)
    ):
        key, cohort, mode, question = specification
        if (case["id"], case["cohort"], case["mode"], case["question"]) != specification:
            raise AdmissionError("d5_frozen_question_or_cohort_changed")
        ranked = rank_mode_items(
            case_pool(packet["corpus"], cohort, packet.get("heldout_excluded_versions", [])),
            packet["profile"],
            product_mode=mode,
            project={"question": question, "scope": "Declared public retained corpus only"}
            if mode == "research"
            else None,
            now=datetime.fromisoformat(packet["clock"]),
        )
        edition, allocation = select_mode_edition(
            ranked,
            reading_minutes(key, mode, index),
            product_mode=mode,
            exploration=packet["profile"].get("exploration", 0.15),
        )
        records = [
            {
                "work_id": item["work_id"],
                "version_id": item["version_id"],
                "relevance": item["mode_relevance"],
                "reasons": item["reasons"],
            }
            for item in ranked
        ]
        if (
            records != case["ranking"]
            or [i["work_id"] for i in edition] != case["edition"]
            or allocation != case["allocation"]
        ):
            raise AdmissionError("d5_ranking_or_edition_replay_changed")
        ordered = edition
        if cohort == "development":
            work_ids = ["arxiv:2210.03629"] + (["arxiv:2310.11511"] if mode == "research" else [])
            ordered = [
                next(i for i in packet["corpus"] if i["work_id"] == work) for work in work_ids
            ]
        elif mode == "learn":
            ordered = edition[index - 2 : index - 1]
        selected = []
        receipts = []
        for item in ordered:
            evidence = select(
                [
                    m
                    for m in materials
                    if m.work_id == item["work_id"] and m.version_id == item["version_id"]
                ],
                question=question,
                max_units=1,
            )
            receipts.append({"work_id": item["work_id"], "selection": evidence})
            selected.extend(evidence["selected"])
            if len(selected) >= (2 if mode == "research" else 1):
                break
        expected = {u["id"]: u["reference"] for u in selected}
        if receipts != case["evidence_selection"] or expected != (case.get("sealed") or {}).get(
            "units", {}
        ):
            raise AdmissionError("d5_retrieved_evidence_substitution_refused")


def compile_inputs(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    verify(packet)
    from src.workspace.d5_coverage_packet import compile_controls, is_packet

    if is_packet(packet):
        return compile_controls(packet)
    run_owner, count_owner = execution_owners(packet)
    scope_id = "d5-" + packet["packet_digest"][:24]
    compiled = {}
    for case in packet["cases"]:
        if not case.get("sealed"):
            continue  # An upstream failure is visible, not replaced with references.
        key = case["id"]
        if case["cohort"] == "development" and key not in packet.get(
            "planned_development_cases", ["dev-learn", "dev-compare"]
        ):
            continue
        compiled[key] = {
            "owner": run_owner,
            "stage": "B" if case["cohort"] == "development" else "C",
            "input": prepare_input(
                case["sealed"],
                scope_id=scope_id,
                packet_digest=packet["packet_digest"],
                case_id=key,
                programme_amendment_digest=packet.get("programme_amendment", {}).get(
                    "proposal_digest"
                ),
                operation_routes=packet.get("operation_routes"),
            ).snapshot(),
        }
    for case in packet["probes"]:
        key = case["id"]
        compiled[key] = {
            "owner": run_owner,
            "stage": "D",
            "input": prepare_input(
                case["sealed"],
                scope_id=scope_id,
                packet_digest=packet["packet_digest"],
                case_id=key,
                programme_amendment_digest=packet.get("programme_amendment", {}).get(
                    "proposal_digest"
                ),
                operation="probe",
                probe_wire=case["wire"],
                operation_routes=packet.get("operation_routes"),
            ).snapshot(),
        }
    for index, key in enumerate(packet["measurement_cases"]):
        case = next(c for c in packet["cases"] if c["id"] == key)
        if not case.get("sealed"):
            continue
        mid = "measure-" + str(index + 1)
        compiled[mid] = {
            "owner": count_owner,
            "stage": "A",
            "input": prepare_input(
                case["sealed"],
                scope_id=scope_id,
                packet_digest=packet["packet_digest"],
                case_id=mid,
                programme_amendment_digest=packet.get("programme_amendment", {}).get(
                    "proposal_digest"
                ),
                operation="measurement",
                operation_routes=packet.get("operation_routes"),
            ).snapshot(),
        }
    return compiled


def restore_input(raw: dict[str, Any]) -> GenerationInput:
    from src.workspace.admission import SourceRef

    return GenerationInput(
        raw["kind"],
        raw["model_id"],
        raw["prompt_revision"],
        tuple(SourceRef(**s) for s in raw["sources"]),
        raw["settings"],
    )


def freeze(
    store: WorkspaceStore,
    profile: dict[str, Any],
    history: dict[str, Any],
    *,
    cohort_revision: str | None = None,
    heldout_excluded_versions: list[str] | None = None,
) -> dict[str, Any]:
    """Writes only explicit isolated proposal projects; never permission rows."""
    store.migrate()
    service = AssistanceService(store)
    items = store.works(RUN_OWNER)
    # No principal's notes, reading state or browser history enter the corpus.
    corpus = [
        {k: v for k, v in item.items() if k not in {"entries", "reading", "context"}}
        for item in items
    ]
    with store.pool.connection() as conn:
        material_rows = conn.execute(
            "SELECT m.material_id FROM workspace_material m JOIN workspace_versions v USING(version_id) JOIN workspace_works w USING(work_id) WHERE w.visibility_owner IS NULL ORDER BY m.material_id"
        ).fetchall()
        materials = [
            service.executor._sources(conn, RUN_OWNER, [row[0]])[0] for row in material_rows
        ]
        provenance = [
            r[0]
            for r in conn.execute(
                "SELECT data FROM workspace_material_provenance ORDER BY material_id"
            )
        ]
        source_receipts = [
            r[0] for r in conn.execute("SELECT receipt FROM workspace_ingest_runs ORDER BY id")
        ]
    by_work: dict[str, list[Any]] = {}
    for material in materials:
        by_work.setdefault(material.work_id, []).append(material)
    context = WorkspaceContext(store)
    cases = []
    excluded = sorted(set(heldout_excluded_versions or []))
    for index, (key, cohort, mode, question) in enumerate(question_specifications(cohort_revision)):
        pool = case_pool(corpus, cohort, excluded)
        baseline_pool = rank_mode_items(pool, profile, now=datetime.fromisoformat(CLOCK))
        project = {"question": question, "scope": "Declared public retained corpus only"}
        ranked = rank_mode_items(
            pool,
            profile,
            product_mode=mode,
            project=project if mode == "research" else None,
            now=datetime.fromisoformat(CLOCK),
        )
        minutes = reading_minutes(key, mode, index)
        edition, allocation = select_mode_edition(
            ranked, minutes, product_mode=mode, exploration=profile.get("exploration", 0.15)
        )
        ordered = edition
        if cohort == "development":
            ids = ["arxiv:2210.03629"] + (["arxiv:2310.11511"] if mode == "research" else [])
            ordered = [next(item for item in corpus if item["work_id"] == work) for work in ids]
        elif mode == "learn":
            focus = index - 2
            ordered = edition[focus : focus + 1]
        selected = []
        failures = []
        for item in ordered:
            selected_result = select(
                [m for m in by_work.get(item["work_id"], []) if m.version_id == item["version_id"]],
                question=question,
                max_units=1,
            )
            failures.append({"work_id": item["work_id"], "selection": selected_result})
            if selected_result["selected"]:
                selected.extend(selected_result["selected"])
            if len(selected) >= (2 if mode == "research" else 1):
                break
        case: dict[str, Any] = {
            "id": key,
            "cohort": cohort,
            "mode": mode,
            "question": question,
            "pipeline": "fixed_evidence_diagnostic"
            if cohort == "development"
            else "end_to_end_system",
            "ranking": [
                {
                    "work_id": i["work_id"],
                    "version_id": i["version_id"],
                    "relevance": i["mode_relevance"],
                    "reasons": i["reasons"],
                }
                for i in ranked
            ],
            "edition": [i["work_id"] for i in edition],
            "allocation": allocation,
            "evidence_selection": failures,
            "human_review": None,
            "sealed": None,
            "upstream_failure": "no_eligible_retrieved_evidence" if not selected else None,
            "baselines": {
                "chronological": [
                    i["work_id"]
                    for i in sorted(
                        (i for i in baseline_pool if known_mode_date(i)),
                        key=lambda i: (known_mode_date(i), i["work_id"]),
                        reverse=True,
                    )
                ],
                "chronological_missing_dates": sum(
                    known_mode_date(i) is None for i in baseline_pool
                ),
                "declared_term": [i["work_id"] for i in baseline_pool],
                "judgments": "Proposed relevance only; owner usefulness and literature recall unmeasured",
            },
        }
        if selected:
            refs = [u["reference"] for u in selected]
            pid = (
                "project-" + hashlib.sha256(key.encode()).hexdigest()[:32]
                if mode == "research"
                else None
            )
            revision = None
            if pid:
                for owner in (RUN_OWNER, COUNT_OWNER):
                    result = context.write_project(
                        owner,
                        ProjectWrite(
                            id=pid,
                            revision=0,
                            request_id="freeze-" + key,
                            data=ProjectData(
                                title="Experimental · " + key,
                                question=question,
                                scope=project["scope"],
                                constraints="No private notes, no source expansion; retained scopes only",
                            ),
                        ),
                    )
                    revision = result["revision"]
            value = AssistanceInput(
                task_context=None,  # Historical benchmark revisions retain their declared schemas.
                mode="research" if mode == "research" else "learn",
                work_id=refs[0]["work_id"],
                version_id=refs[0]["version_id"],
                material_ids=tuple(dict.fromkeys(r["material_id"] for r in refs)),
                span_ids=tuple(dict.fromkeys(r["span_id"] for r in refs)),
                unit_ids=tuple(u["id"] for u in selected),
                follow_up=question,
                project_id=pid,
                project_revision=revision,
            )
            case["sealed"] = service.preview(RUN_OWNER, value).request
            if cohort_revision == "procedural-v8":
                case["sealed"] = seal_procedural_request(case["sealed"])
            case["wire_digest"] = _digest(case["sealed"]["candidate_initial_wire"])
            case["source_scopes"] = [r["scope"] for r in refs]
        cases.append(case)
    probes = []
    usable = [c for c in cases if c["cohort"] == "fresh_system" and c["sealed"]]
    if not usable:
        raise AdmissionError("d5_no_system_evidence")
    # Five separately cited judgments per batch; not independently labelled gold.
    for batch, assertion in enumerate(
        (
            "This evidence guarantees safe production deployment on all hardware.",
            "This method always outperforms every alternative under identical conditions.",
            "The result requires no assumptions or evaluation limitations.",
            "This abstract establishes all full-paper implementation and reproducibility details.",
        )
    ):
        chosen = [usable[(batch * 5 + i) % len(usable)] for i in range(5)]
        units = {k: v for c in chosen for k, v in c["sealed"]["units"].items()}
        sealed = json.loads(json.dumps(chosen[0]["sealed"]))
        sources = {s["material_id"]: s for c in chosen for s in c["sealed"]["sources"]}
        sealed.update(
            units=units,
            sources=list(sources.values()),
            version_hashes={k: v for c in chosen for k, v in c["sealed"]["version_hashes"].items()},
        )
        sealed["project_context"] = None
        sealed["selection"] = {
            "material_ids": list(sources),
            "span_ids": list(dict.fromkeys(r["span_id"] for r in units.values())),
        }
        from src.workspace.assistance_contract import contract_revision, response_purpose, schemas

        sealed["response_purpose"] = response_purpose(sealed["assistance"]["mode"], units)
        sealed["schema_revision"] = contract_revision(sealed["response_purpose"])
        sealed["response_schemas"] = schemas(list(units), purpose=sealed["response_purpose"])
        claims = []
        for i, c in enumerate(chosen):
            ref = EvidenceRef(**next(iter(c["sealed"]["units"].values())))
            claims.append(
                ResearchClaim(
                    "c" + str(i + 1),
                    assertion,
                    ClaimKind.FACTUAL,
                    (ref,),
                    required_scope="full_text" if batch == 3 else ref.scope,
                )
            )
        stage = {
            "phase": "check",
            "role": "checker",
            "sealed_request": {"schema_revision": REVISION, "private_context": False},
            "draft": {"claims": [asdict(c) for c in claims]},
            "claim_inputs": [
                {"claim_id": c.claim_id, "input_digest": claim_input_digest(c, materials)}
                for c in claims
            ],
            "unscored_prose": {},
            "output_schema": transform_schema(Checks),
        }
        probes.append(
            {
                "id": "probe-" + str(batch + 1),
                "cohort": "fixed_checker_diagnostic",
                "sealed": sealed,
                "wire": build_wire(stage),
                "human_labels": [None] * 5,
                "proposed": "unsupported_or_abstain",
                "annotation_basis": "Machine-authored adversarial assertions, not human gold",
            }
        )
    payload = {
        "revision": REVISION_BENCHMARK,
        "application_commit": subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", "src", "web"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
        ).strip(),
        "checker_schema": {"local": Checks.model_json_schema(), "wire": transform_schema(Checks)},
        "execution": {
            "model": "claude-sonnet-5-5",
            "thinking": {"type": "between_tools"},
            "effort": "medium",
            "temperature": None,
            "input_tokens_raw_max": 20000,
            "input_tokens_measured_max": 16000,
            "workflow_output_tokens": 4000,
            "checker_output_tokens": 1800,
            "max_stages": 4,
            "max_repairs": 1,
            "pricing_estimate_usd_per_million": {
                "input": "2",
                "output": "10",
                "verified_at": "2026-11-06",
            },
        },
        "approved": False,
        "created_at": datetime.now(UTC).isoformat(),
        "clock": CLOCK,
        "profile": {
            k: profile[k]
            for k in ("topics", "custom_topics", "exclusions", "streams", "minutes", "exploration")
        },
        "profile_authority_hash": _digest(profile),
        "corpus": corpus,
        "materials": [asdict(m) for m in materials],
        "material_provenance": provenance,
        "intake_receipts": source_receipts,
        "cases": cases,
        "probes": probes,
        "measurement_cases": [
            "dev-learn",
            "dev-compare",
            "research-retrieval",
            "research-insufficient",
        ],
        "ranking_policy": MODE_POLICY_VERSION,
        "selection_policy": POLICY,
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "history": history,
        "program_id": "research-evaluation-20261105-v1",
        "limits": LIMITS,
        "scoring": {
            "completion_required": 8,
            "fresh_cases": 8,
            "generated_fact_reviews_min": 20,
            "adversarial_reviews_min": 20,
            "false_pass_max": 0,
            "provenance_required": 1,
            "human_missing": "HOLD",
            "minimum_feasibility": "7 potentially answerable fresh cases x 6 claims = 42 slots; 20 not guaranteed. Fewer observed facts means HOLD, no added cases.",
            "correlation": "Report by case/source; claims are not independent samples",
        },
        "review_policy": {
            "format": "d5-human-review-v1",
            "scorer_version": "d5-reviewed-quality-v1",
            "storage": "Append-only external sidecars; exact original packet/run/output/evidence binding, explicit adjudication, no raw/accounting/approval writes",
            "missing": "null/UNSCORED/HOLD; failed required provenance cannot be overridden",
            "checker_denominators": "Conditional on decisive human and machine judgments; abstentions, insufficient and unreviewable labels reported separately",
            "minimums": "Unchanged scoring thresholds; unique fully reviewed fresh generated facts only, decisive observed probe labels, never assumed negativity",
        },
        "human_rubric": [
            "whole-claim support",
            "atomicity",
            "qualification retained",
            "comparison compatibility",
            "counterevidence",
            "omissions",
            "personal usefulness",
        ],
        "stop_rules": [
            "first contract/admission/provider failure",
            "unknown completion",
            "revocation or source/project/schema/settings/producer drift",
            "any monetary/contact/capacity refusal",
        ],
        "historical_cases": "q01 development; q02/q03 historical failures; q04 stopped; original 0/9 aggregate unchanged; no replay",
        "coverage": "Replay of retained public metadata/abstracts and two bounded PDF samples; no fresh intake or full-paper extraction qualification",
        "dynamic_requests": "Checks, repair and recheck derive only from actual preceding journalled outputs under frozen code; exact digests recorded at creation",
    }
    payload["packet_digest"] = _digest(payload)
    if cohort_revision is not None:
        payload.update(cohort_revision=cohort_revision, heldout_excluded_versions=excluded)
        payload["packet_digest"] = _digest(
            {k: v for k, v in payload.items() if k != "packet_digest"}
        )
    return dict(json.loads(json.dumps(payload, ensure_ascii=False)))
