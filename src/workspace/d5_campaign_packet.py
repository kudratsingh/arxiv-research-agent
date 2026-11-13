"""Frozen complete machine campaign over exposed retained public inputs. No grant."""

from __future__ import annotations

import json
import random
import subprocess
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anthropic import transform_schema

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_policy import LIMITS, PROFILE
from src.workspace.d5_deadlines import POLICY as DEADLINES
from src.workspace.d5_operations import ROUTES

REVISION = "d5-complete-machine-campaign-v13"
BASE = "1429b39296792b8bc3d5530d28bcc56600048b149310fc10df30c2ee6048a7a7"
ROOT = Path(__file__).resolve().parents[2]
BUILD_OWNER = "d5-campaign-public-build"
QUESTIONS = (
    (
        "eval-learn-mechanism",
        "learn",
        "What sequence of operations does the selected source describe? Separate established steps from prerequisites unavailable in the retained text.",
    ),
    (
        "eval-learn-conditions",
        "learn",
        "Which population, task and evaluation conditions limit each reported result in this source? Keep comparator and metric definitions with the claims.",
    ),
    (
        "eval-learn-experiment",
        "learn",
        "What information in this retained source is enough to outline a reproducible experiment, and which implementation or protocol details must be requested?",
    ),
    (
        "eval-learn-measurement",
        "learn",
        "Explain one reported empirical finding with its metric and scope, and distinguish it from hypothesised applications.",
    ),
    (
        "eval-research-memory",
        "research",
        "Which selected evidence explains how agent memory is updated and how incorrect information can persist? Separate mechanisms from measurements.",
    ),
    (
        "eval-research-retrieval",
        "research",
        "Compare selected retrieval and RAG methods only on compatible evaluation evidence. State unavailable common tasks, baselines, relevance judgments and counterevidence.",
    ),
    (
        "eval-research-verification",
        "research",
        "What measurements in the selected sources support trustworthy claim verification? Preserve uncertainty, abstention and calibration limits.",
    ),
    (
        "eval-research-insufficient",
        "research",
        "Can the selected sources justify a learned controller for a vehicle whose configuration, operating conditions, safety criteria and validation data have not been supplied?",
    ),
)

# Codex-authored proposed references on exposed retained abstracts, not human
# gold. Complete evidence units and their qualifications remain available.
PROBE_CONTROLS = (
    (
        "ucbe894d1356a18e9f328",
        "In the KEEPER abstract, self-consistency bias is defined as persistence of incorrect claims already present in incoming memory.",
        "The KEEPER abstract defines self-consistency bias as retention of correct claims newly introduced by corrective observations.",
    ),
    (
        "uf3d98db2c5a285f07e68",
        "The selected fairness-benchmark abstract describes a protocol paper in which no model has yet been evaluated.",
        "The selected fairness-benchmark abstract reports completed model evaluations and measured fairness results.",
    ),
    (
        "u0f7bbc40b13700658755",
        "On the 87 runs reported in the selected oversight abstract, the two best live supervisors are statistically tied.",
        "On the 87 reported runs, the selected oversight abstract establishes a statistically significant unique winner among the two best live supervisors.",
    ),
    (
        "ud9a2a9dc8b369bebaa4c",
        "In the selected CLR-Bench excerpt, ACE and Dynamic Cheatsheet learn from feedback alone with the stronger GPT-6-Sol model.",
        "In the selected CLR-Bench excerpt, ACE and Dynamic Cheatsheet cannot learn from feedback alone with the stronger GPT-6-Sol model.",
    ),
    (
        "u076920f78b07ea94b891",
        "For the cost-effective SOTA LLMs evaluated in the selected P-ContextBench abstract, temporal-tracking accuracy is below 60%.",
        "For the cost-effective SOTA LLMs evaluated in the selected P-ContextBench abstract, temporal-tracking accuracy is at least 90%.",
    ),
    (
        "uc983ca9c897cb6079772",
        "The selected TensorSSM abstract reports experiments across diverse tensor datasets without relying on strict spatial assumptions.",
        "The selected TensorSSM abstract says its experiments require strict spatial assumptions.",
    ),
    (
        "ucbe894d1356a18e9f328",
        "Among the conditions evaluated in the KEEPER abstract, reward-related prediction has the highest task performance before and after offline reinforcement learning, outperforming joint supervision.",
        "Among the conditions evaluated in the KEEPER abstract, joint supervision outperforms reward-related prediction both before and after offline reinforcement learning.",
    ),
    (
        "uf3d98db2c5a285f07e68",
        "The selected fairness protocol abstract says its pre-registration commits the hypotheses, metrics, exclusion rules and analysis plan for a subsequent pilot.",
        "The selected fairness protocol abstract says the pilot was completed before its hypotheses and exclusion rules were specified.",
    ),
    (
        "u0f7bbc40b13700658755",
        "Based on its reported contrast on the same 87 runs, the selected oversight abstract cautions that post-hoc diagnostic performance can be a poor proxy for live oversight.",
        "The selected oversight abstract concludes that the strongest post-hoc diagnostician is guaranteed to be the strongest live supervisor on those runs.",
    ),
    (
        "ud9a2a9dc8b369bebaa4c",
        "For the stronger GPT-6-Sol comparison, the selected CLR-Bench excerpt reports 78% accuracy against 53% with the certifying model.",
        "For the stronger GPT-6-Sol comparison, the selected CLR-Bench excerpt reports 53% accuracy against 78% with the certifying model.",
    ),
)


def discovery(base: dict[str, Any], index: int, materials: Any) -> dict[str, Any]:
    from src.workspace.d5_evidence import select
    from src.workspace.mode_ranking import known_mode_date, rank_mode_items, select_mode_edition

    key, mode, question = QUESTIONS[index]
    clock = datetime.fromisoformat(base["clock"])
    project = {"question": question, "scope": "Frozen retained public sources only"}
    ranked = rank_mode_items(
        base["corpus"],
        base["profile"],
        product_mode=mode,
        project=project if mode == "research" else None,
        now=clock,
    )
    edition, allocation = select_mode_edition(
        ranked,
        45 if mode == "learn" and index == 3 else 15,
        product_mode=mode,
        exploration=base["profile"]["exploration"],
    )
    ordered = edition[index : index + 1] if mode == "learn" else edition
    units, selections = {}, []
    for item in ordered:
        chosen = select(
            [
                m
                for m in materials
                if m.work_id == item["work_id"] and m.version_id == item["version_id"]
            ],
            question=question,
            max_units=1,
        )
        selections.append({"work_id": item["work_id"], "selection": chosen})
        units.update({u["id"]: u["reference"] for u in chosen["selected"]})
        if len(units) >= (1 if mode == "learn" else 2):
            break
    baseline = rank_mode_items(base["corpus"], base["profile"], now=clock)
    return {
        "id": key,
        "cohort": "evaluation_exposed_corpus",
        "mode": mode,
        "question": question,
        "pipeline": "end_to_end_system",
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
        "evidence_selection": selections,
        "selected_units": units,
        "human_review": None,
        "upstream_failure": None if units else "no_eligible_retrieved_evidence",
        "baselines": {
            "chronological": [
                i["work_id"]
                for i in sorted(
                    (i for i in baseline if known_mode_date(i)),
                    key=lambda i: (known_mode_date(i), i["work_id"]),
                    reverse=True,
                )
            ],
            "chronological_missing_dates": sum(known_mode_date(i) is None for i in baseline),
            "declared_term": [i["work_id"] for i in baseline],
            "judgments": "Unjudged; no owner usefulness or literature-recall label",
        },
    }


def predecessor() -> dict[str, Any]:
    from src.workspace.d5_benchmark import read

    p = read(
        ROOT
        / "planning/14-explore-and-research-modes/d5/evidence/qualification-v8r4b/packet.json.gz"
    )
    if (
        p["packet_digest"] != BASE
        or _digest({k: v for k, v in p.items() if k != "packet_digest"}) != BASE
    ):
        raise AdmissionError("campaign_archived_baseline_changed")
    return p


def owners(packet: dict[str, Any]) -> tuple[str, str]:
    actor = "d5-campaign-" + packet["packet_digest"][:16] + "-run"
    return actor, actor


def plan_digest(packet: dict[str, Any]) -> str:
    return _digest(
        {
            k: packet[k]
            for k in (
                "cases",
                "probes",
                "probe_references",
                "profile",
                "clock",
                "operation_routes",
                "operation_deadlines",
                "limits",
                "scoring",
                "answerability",
                "code",
                "adapter",
                "source_bindings",
            )
        } | ({"progression": packet["progression"], "checker_normalization_revision": packet["checker_normalization_revision"]} if packet.get("revision") == "d5-complete-machine-campaign-v14" else {})
    )


def selection(
    store: Any,
    key: str,
    mode: Any,
    question: str,
    units: dict[str, Any],
    *,
    intent: Any = "answer",
    probe: bool = False,
) -> dict[str, Any]:
    from src.workspace.assistance import AssistanceInput, AssistanceService
    from src.workspace.assistance_coverage import RequestedPart
    from src.workspace.assistance_policy import CoverageTaskContext, TaskContext
    from src.workspace.context_schemas import ProjectData, ProjectWrite
    from src.workspace.context_store import WorkspaceContext

    refs = list(units.values())
    pid = "project-" + _digest(key)[:32] if mode == "research" else None
    if pid:
        WorkspaceContext(store).write_project(
            BUILD_OWNER,
            ProjectWrite(
                id=pid,
                revision=0,
                request_id="freeze-" + key,
                data=ProjectData(
                    title="Experimental · " + key,
                    question=question,
                    scope="Frozen retained public sources only",
                    constraints="No private notes/history, source expansion or everyday generation",
                ),
            ),
        )
    parts = (
        RequestedPart(
            id="p1", request=question, kind="comparison" if intent == "comparison" else "answer"
        ),
        RequestedPart(
            id="p2",
            request="State separately cited source facts and retain study scope, comparator, metric definition and conditions.",
            kind="source_note",
        ),
        RequestedPart(
            id="p3",
            request="Identify missing evidence or required details without inventing findings.",
            kind="answer",
        ),
    )
    value = AssistanceInput(
        mode=mode,
        work_id=refs[0]["work_id"],
        version_id=refs[0]["version_id"],
        material_ids=tuple(dict.fromkeys(r["material_id"] for r in refs)),
        span_ids=tuple(dict.fromkeys(r["span_id"] for r in refs)),
        unit_ids=tuple(units),
        follow_up=question,
        project_id=pid,
        project_revision=1 if pid else None,
        task_context=TaskContext(intent="answer")
        if probe
        else CoverageTaskContext(intent=intent, requested_parts=parts),
    )
    request = AssistanceService(store).preview(BUILD_OWNER, value).request
    if request["units"] != units:
        raise AdmissionError("campaign_exact_selected_units_changed")
    return request


def make_probes(
    store: Any, materials: Any
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    from src.workspace.assistance import Checks
    from src.workspace.assistance_contract import coherent_units
    from src.workspace.d5_evidence import assess
    from src.workspace.d5_operations import wire
    from src.workspace.grounding import ClaimKind, EvidenceRef, ResearchClaim, claim_input_digest

    grouped = []
    exclusions = []
    for material in materials:
        if material.scope != "abstract":
            exclusions.append(
                {
                    "material_id": material.material_id,
                    "reason": "probe_reference_set_abstract_only; PDF samples are not extraction-qualified",
                    "retained_unchanged": True,
                }
            )
            continue
        try:
            units = coherent_units([material], {s.span_id for s in material.spans})
        except ValueError as exc:
            exclusions.append(
                {
                    "material_id": material.material_id,
                    "reason": str(exc),
                    "retained_unchanged": True,
                }
            )
            continue
        eligible = [
            (key, asdict(ref))
            for key, ref in units.items()
            if ref.scope in {"abstract", "excerpt"} and assess(ref, material)["eligible"]
        ]
        if eligible:
            grouped.append((material.material_id, eligible))
    pool = {key: ref for _, units in grouped for key, ref in units}
    if any(key not in pool for key, _, _ in PROBE_CONTROLS):
        raise AdmissionError("campaign_frozen_probe_evidence_unavailable")
    buckets: list[list[dict[str, Any]]] = [[], [], [], []]
    refs = {}
    for index in range(10):
        handle, positive, negative = PROBE_CONTROLS[index]
        ref = pool[handle]
        match = "pair-" + str(index + 1)
        for label, offset in (("supported", 0), ("unsupported", 2)):
            identifier = "p" + _digest([match, label, ref, "v12-blind-seed"])[0:18]
            text = positive if label == "supported" else negative
            item = {"claim_id": identifier, "text": text, "handle": handle, "ref": ref}
            buckets[(index + offset) % 4].append(item)
            refs[identifier] = {
                "reference": label,
                "basis": "Machine-authored frozen reference; not human gold",
                "matched_pair": match,
                "claim_digest": _digest({"text": text, "evidence": ref}),
                "evidence": ref,
                "text": text,
            }
    probes = []
    for index, items in enumerate(buckets):
        random.Random(1200 + index).shuffle(items)
        key = "campaign-probe-" + str(index + 1)
        units = {i["handle"]: i["ref"] for i in items}
        sealed = selection(
            store,
            key,
            "research",
            "Assess each statement only against its exact selected retained passages; preserve uncertainty.",
            units,
            probe=True,
        )
        claims = [
            ResearchClaim(
                i["claim_id"],
                i["text"],
                ClaimKind.FACTUAL,
                (EvidenceRef(**i["ref"]),),
                required_scope=i["ref"]["scope"],
            )
            for i in items
        ]
        context = {
            "phase": "check",
            "role": "checker",
            "sealed_request": {
                "schema_revision": sealed["schema_revision"],
                "private_context": False,
            },
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
                "id": key,
                "cohort": "machine_reference_checker_diagnostic",
                "sealed": sealed,
                "wire": wire(context, ROUTES),
                "human_labels": None,
            }
        )
    return probes, refs, exclusions


def freeze(store: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.assistance import CoverageChecks
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_answerability import POLICY, matrix
    from src.workspace.d5_campaign_extension import proposal
    from src.workspace.d5_freeze import code_bindings, verify_discovery
    from src.workspace.executor import FakeExecutor

    old = predecessor()
    verify_discovery(old)
    with store.pool.connection() as conn:
        materials = tuple(
            FakeExecutor(store)._sources(conn, BUILD_OWNER, [m["material_id"]])[0]
            for m in old["materials"]
        )
    specifications = [*old["cases"][:2], *(discovery(old, i, materials) for i in range(8))]
    cases = []
    for index, case in enumerate(specifications):
        key = "campaign-" + case["id"]
        intent = (
            "application_assessment"
            if "insufficient" in key
            else "comparison"
            if "compare" in key or "retrieval" in key
            else "answer"
        )
        units = case["sealed"]["units"] if index < 2 else case["selected_units"]
        if not units:
            raise AdmissionError("campaign_upstream_evidence_unavailable_before_freeze")
        sealed = selection(store, key, case["mode"], case["question"], units, intent=intent)
        cases.append(
            {
                **deepcopy(case),
                "id": key,
                "original_case_id": case["id"] if index < 2 else None,
                "cohort": "development" if index < 2 else "evaluation_exposed_corpus",
                "exposure": "Development uses archived controls. Evaluation questions are prospective but corpus/source material is exposed; not fresh independent held-out evidence.",
                "sealed": sealed,
                "wire_digest": _digest(sealed["candidate_initial_wire"]),
            }
        )
    probes, references, exclusions = make_probes(store, materials)
    selected_mids = sorted(
        {r["material_id"] for c in (*cases, *probes) for r in c["sealed"]["units"].values()}
    )
    with store.pool.connection() as conn:
        source_bindings = {
            "versions": {
                r[0]: _digest(r[1])
                for r in conn.execute(
                    "SELECT version_id,data FROM workspace_versions WHERE version_id=ANY(%s)",
                    ([c["version_id"] for c in old["corpus"]],),
                )
            },
            "materials": {
                r[0]: _digest(r[1])
                for r in conn.execute(
                    "SELECT material_id,data FROM workspace_material WHERE material_id=ANY(%s)",
                    (selected_mids,),
                )
            },
        }
    p = {
        "revision": REVISION,
        "approved": False,
        "predecessor_packet": BASE,
        "application_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "created_at": datetime.now(UTC).isoformat(),
        "program_id": snapshot["program_id"],
        "history": snapshot["history"],
        "snapshot_digest": _digest(snapshot),
        "source_bindings": source_bindings,
        "programme": snapshot["programme"],
        "scope_profile": PROFILE,
        "limits": LIMITS,
        "operation_routes": ROUTES,
        "operation_deadlines": DEADLINES,
        "cases": cases,
        "probes": probes,
        "probe_references": references,
        "probe_reference_digest": _digest(references),
        "probe_evidence_exclusions": exclusions,
        "schedule": [c["id"] for c in (*cases, *probes)],
        "measurement_cases": [],
        "human_qualification": False,
        "profile": old["profile"],
        "profile_basis": "Preserved owner-authoritative benchmark profile snapshot; not a synthetic preview or a claim of current preference freshness.",
        "clock": old["clock"],
        "corpus": old["corpus"],
        "materials": [asdict(m) for m in materials],
        "code": code_bindings(),
        "adapter": qualification_producer(),
        "checker_schemas": {
            "local": CoverageChecks.model_json_schema(),
            "wire": transform_schema(CoverageChecks),
        },
        "answerability": matrix(cases),
        "scoring": {
            "revision": POLICY,
            "evaluation_denominator": 8,
            "generated_claims_min": 20,
            "probe_records_min": 20,
            "machine_false_pass_max": 0,
            "machine_false_reject_max": 0,
            "missing": "UNSCORED/HOLD",
            "human_qualification": False,
            "correlation": "Claims and matched probes share cases/passages; not independent samples",
        },
        "stop_policy": "Continue only fully metered content rejection; stop on binding drift, corruption, exceeded budget/contact/capacity, expiry/revocation, provider error or ANY NEW uncertain contact. Never retry or replace identities.",
    }
    with store.pool.connection() as conn:
        p["campaign_extension"] = proposal(conn, p["program_id"], plan_digest(p))
    p["packet_digest"] = _digest(p)
    verify_packet(p)
    return p


def verify_packet(p: dict[str, Any]) -> None:
    if p.get("revision") == "d5-complete-machine-campaign-v14":
        from src.workspace.d5_campaign_v14_packet import verify_packet as verify_successor

        verify_successor(p)
        return
    from src.workspace.assistance_contract import schemas
    from src.workspace.d5_campaign_policy import PROGRAM_LIMITS

    old = predecessor()
    if (
        p.get("revision") != REVISION
        or p.get("limits") != LIMITS
        or p.get("scope_profile") != PROFILE
        or p.get("operation_routes") != ROUTES
        or p.get("operation_deadlines") != DEADLINES
        or p.get("measurement_cases") != []
        or p.get("human_qualification") is not False
    ):
        raise AdmissionError("campaign_frozen_limits_or_policy_drift")
    if (
        len(p["cases"]) != 10
        or len(p["probes"]) != 4
        or p["schedule"] != [c["id"] for c in (*p["cases"], *p["probes"])]
    ):
        raise AdmissionError("campaign_frozen_schedule_drift")
    from src.workspace.material import SourceMaterial, SourceSpan

    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in p["materials"]
    )
    expected = [*old["cases"][:2], *(discovery(old, i, materials) for i in range(8))]
    for index, (c, base) in enumerate(zip(p["cases"], expected, strict=True)):
        units = base["sealed"]["units"] if index < 2 else base["selected_units"]
        if (
            c["id"] != "campaign-" + base["id"]
            or c["cohort"] != ("development" if index < 2 else "evaluation_exposed_corpus")
            or any(
                c[k] != base[k]
                for k in ("question", "ranking", "edition", "evidence_selection", "baselines")
            )
            or c["sealed"]["units"] != units
        ):
            raise AdmissionError("campaign_discovery_or_exposure_binding_drift")
        sealed = c["sealed"]
        if sealed["response_schemas"] != schemas(
            list(sealed["units"]),
            purpose=sealed["response_purpose"],
            revision=sealed["schema_revision"],
            task_policy=sealed["task_policy"],
        ):
            raise AdmissionError("campaign_exact_response_schema_drift")
    from src.workspace.d5_answerability import POLICY, matrix

    if p.get("answerability") != matrix(p["cases"]) or p["scoring"].get("revision") != POLICY:
        raise AdmissionError("campaign_locked_answerability_or_policy_drift")
    refs = p["probe_references"]
    identifiers = [
        c["claim_id"]
        for probe in p["probes"]
        for c in json.loads(probe["wire"]["messages"][0]["content"])["draft"]["claims"]
    ]
    if (
        len(identifiers) != 20
        or len(set(identifiers)) != 20
        or set(identifiers) != set(refs)
        or p["probe_reference_digest"] != _digest(refs)
        or sorted(r["reference"] for r in refs.values())
        != ["supported"] * 10 + ["unsupported"] * 10
    ):
        raise AdmissionError("campaign_locked_balanced_references_required")
    for probe in p["probes"]:
        context = json.loads(probe["wire"]["messages"][0]["content"])
        if any(
            key in json.dumps(context)
            for key in ('"reference"', '"matched_pair"', '"probe_references"')
        ):
            raise AdmissionError("campaign_reference_label_leak")
        for claim in context["draft"]["claims"]:
            reference = refs[claim["claim_id"]]
            if reference["claim_digest"] != _digest(
                {"text": claim["text"], "evidence": claim["evidence"][0]}
            ):
                raise AdmissionError("campaign_reference_claim_drift")
    core = p["campaign_extension"]["core"]
    if (
        core["plan_digest"] != plan_digest(p)
        or core["basis"] != p["history"]
        or core["limits"] != PROGRAM_LIMITS
        or p["campaign_extension"]["proposal_digest"] != _digest(core)
    ):
        raise AdmissionError("campaign_capacity_or_baseline_binding_drift")


def compile_campaign(p: dict[str, Any]) -> dict[str, Any]:
    from src.workspace.d5_adapter import prepare_input

    actor = owners(p)[0]
    scope = "d5-" + p["packet_digest"][:24]
    compiled = {}
    for index, case in enumerate((*p["cases"], *p["probes"])):
        probe = index >= 10
        compiled[case["id"]] = {
            "owner": actor,
            "stage": "D" if probe else "B" if index < 2 else "C",
            "input": prepare_input(
                case["sealed"],
                scope_id=scope,
                packet_digest=p["packet_digest"],
                case_id=case["id"],
                operation="probe" if probe else "workflow",
                probe_wire=case["wire"] if probe else None,
                programme_amendment_digest=p["campaign_extension"]["proposal_digest"],
                operation_routes=p.get("operation_routes", ROUTES),
                scope_profile=PROFILE,
                operation_deadlines=DEADLINES,
                repair_located_prose=True,
            ).snapshot(),
        }
    return compiled


def verify_dispatch_identity(packet: dict[str, Any]) -> None:
    """Full discovery is replayed at preflight; immutable inputs cannot change.

    No authorization/ledger/source decision is cached. Those are freshly checked
    by production admission at every contact, alongside exact code bindings.
    """
    from src.workspace.d5_adapter import qualification_producer
    from src.workspace.d5_freeze import code_bindings

    if (
        packet.get("approved") is not False
        or _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        != packet.get("packet_digest")
        or code_bindings() != packet["code"]
        or qualification_producer() != packet["adapter"]
    ):
        raise AdmissionError("campaign_frozen_packet_or_producer_drift")
