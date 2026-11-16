"""Prospective context/premise roles and lossless partial request coverage.

The v17 format remains unchanged. Only the sealed v18 codec selects this model.
Identity is server-owned; coverage is the only claim-to-part mapping. Aggregate
coverage describes explicit declarations, never semantic support or human review.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from copy import deepcopy
from functools import lru_cache
from types import GenericAlias
from typing import Any, Literal, Self, cast, get_args

from anthropic import transform_schema
from pydantic import BaseModel, Field, create_model, model_validator

from src.workspace import assistance_capacity_contract as capacity
from src.workspace import assistance_compact_encoding as previous
from src.workspace.assistance_contract import (
    ABSTENTION_INTENTS,
    ACTION_INTENTS,
    QUESTION_INTENTS,
    EvidenceRequest,
    digest,
    render_gaps,
)
from src.workspace.assistance_coverage import GAP_TEXT, reverse_index
from src.workspace.assistance_coverage_shapes import EvidenceGap, OmissionGap
from src.workspace.assistance_policy import CONTEXT_REQUESTS
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE
from src.workspace.grounding import ClaimKind, EvidenceRef, ResearchClaim, validate_claims
from src.workspace.material import SourceMaterial

REVISION = "workspace-assistance-consistency-wire-v18"
KEY = previous.KEY
STATUS = ("answered", "partial", "lacks_evidence", "omitted")


def enabled(policy: dict[str, Any] | None) -> bool:
    return bool(policy and policy.get(KEY) == REVISION)


def prior_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if not enabled(policy):
        raise ValueError("consistency_codec_revision_required")
    return previous.prior_policy({**policy, KEY: previous.REVISION})


class Question(capacity._Closed):
    intent: Literal[
        "measured_and_proposed",
        "methods",
        "qualifications",
        "implementation",
        "counterevidence",
        "application_scope",
        "investigate_claim",
    ]
    context_claim_ids: tuple[capacity.ClaimKey, ...] = Field(max_length=12)
    premise_claim_ids: tuple[capacity.ClaimKey, ...] = Field(max_length=12)

    @property
    def claim_ids(self) -> tuple[capacity.ClaimKey, ...]:
        """Compatibility view for core reference validation, not a second mapping."""
        return (*self.context_claim_ids, *self.premise_claim_ids)

    @model_validator(mode="after")
    def roles(self) -> Self:
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("duplicate_or_overlapping_question_reference")
        if self.intent == "investigate_claim":
            if not self.premise_claim_ids:
                raise ValueError("question_premise_requires_scored_claim")
        elif self.premise_claim_ids:
            raise ValueError("neutral_question_forbids_factual_premise")
        return self


class Draft(capacity._Closed):
    """Role-aware normalized draft; reuse core safeguards without a wire mapping."""

    claims: tuple[capacity.CapacityClaim, ...] = Field(max_length=12)
    background_claims: tuple[capacity.ClaimKey, ...] = Field(max_length=12)
    assumption_claims: tuple[capacity.ClaimKey, ...] = Field(max_length=12)
    limitation_claims: tuple[capacity.ClaimKey, ...] = Field(max_length=12)
    gaps: tuple[EvidenceRequest, ...] = Field(min_length=1, max_length=3)
    questions: tuple[Question, ...] = Field(min_length=1, max_length=3)
    proposal: Literal[
        "inspect_methods",
        "inspect_evaluation",
        "seek_counterevidence",
        "inspect_scope",
        "request_context",
    ]
    abstention: (
        Literal[
            "insufficient_selected_evidence",
            "application_context_required",
            "comparison_evidence_required",
        ]
        | None
    )
    comparison_claims: tuple[capacity.ClaimKey, ...] = Field(default=(), max_length=12)
    comparison_basis: tuple[capacity.ClaimKey, ...] = Field(default=(), max_length=12)

    @model_validator(mode="after")
    def references(self) -> Self:
        value = self.model_dump(mode="json")
        value["questions"] = [
            {"intent": q.intent, "claim_ids": list(q.claim_ids)} for q in self.questions
        ]
        capacity.CapacityDraft.model_validate(value)
        capacity._bounded(
            self.model_dump(mode="json"),
            capacity._limits()["internal_json_bytes"],
            "capacity_internal_output_exceeded",
        )
        return self


def _new(name: str, fields: dict[str, Any], base: Any = capacity._Closed) -> type[BaseModel]:
    return cast(type[BaseModel], create_model(name, __base__=base, **fields))


def response_model(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    prior_policy(policy)
    return _model(tuple(sorted(set(handles))), purpose, json.dumps(policy, sort_keys=True))


@lru_cache(maxsize=128)
def _model(handles: tuple[str, ...], purpose: str, encoded: str) -> type[BaseModel]:
    policy = json.loads(encoded)
    old = previous.response_model(handles, purpose, {**policy, KEY: previous.REVISION})
    alternatives = get_args(old.model_fields["response"].annotation) or (
        old.model_fields["response"].annotation,
    )
    identity = digest([REVISION, handles, purpose, policy])[7:23]
    count = CLAIMS_BY_MODE[policy["mode"]]
    identifier = cast(Any, Literal)[tuple(f"c{i}" for i in range(1, count + 1))]
    reasons = tuple(
        dict.fromkeys(["none", *previous._values(EvidenceGap), *previous._values(OmissionGap)])
    )
    row = _new(
        "ConsistencyPart_" + identity,
        {
            "status": (
                Literal["answered", "partial", "lacks_evidence", "omitted"],
                Field(
                    description="answered: nonempty answer refs, [none]. partial: nonempty answer refs and genuine remaining gaps. lacks_evidence: no answer refs, evidence reasons. omitted: no answer refs, omission reasons. Context is never answer credit."
                ),
            ),
            "gap_reasons": (
                GenericAlias(tuple, (cast(Any, Literal)[reasons], ...)),
                Field(min_length=1, max_length=10),
            ),
            "answer_claim_ids": (GenericAlias(tuple, (identifier, ...)), Field(max_length=count)),
            "context_claim_ids": (GenericAlias(tuple, (identifier, ...)), Field(max_length=count)),
        },
    )
    question = _new(
        "ConsistencyQuestion_" + identity,
        {
            "context_claim_ids": (
                GenericAlias(tuple, (identifier, ...)),
                Field(
                    max_length=count,
                    description="Related claim positions for navigation/topic context. These links assert no factual premise. Neutral intents may link context.",
                ),
            ),
            "premise_claim_ids": (
                GenericAlias(tuple, (identifier, ...)),
                Field(
                    max_length=count,
                    description="Factual premises, only for investigate_claim. Each must refer to an emitted cited claim, whose whole support is checked. Empty for neutral intents. No new assertion may be introduced by a question.",
                ),
            ),
        },
        Question,
    )
    branches = []
    for original in alternatives:
        fields = previous._fields(original)
        full = "full_abstention" in previous._values(
            original.model_fields["disposition"].annotation
        )
        if not full:
            # One-value enum survives the SDK; const does not. This tag is
            # structural, and aggregate answer coverage is server-derived.
            from src.workspace.assistance_keyed_contract import _fixed

            fields["disposition"] = (
                _fixed("answer"),
                Field(
                    description="Claim-bearing body marker only. Full/partial/insufficient request coverage is derived from the required part records; this marker grants no full-answer credit."
                ),
            )
            fields["coverage"] = (
                _new(
                    "ConsistencyCoverage_" + identity,
                    {
                        p["id"]: (
                            row,
                            Field(
                                description="Exactly this sealed requested part; preserve every remaining gap."
                            ),
                        )
                        for p in policy["requested_parts"]
                    },
                ),
                ...,
            )
            fields["questions"] = (
                GenericAlias(tuple, (question, ...)),
                Field(min_length=1, max_length=3),
            )
        branches.append(_new("Consistency" + original.__name__, fields))
    union: Any = branches[0]
    for branch in branches[1:]:
        union = union | branch

    class Envelope(capacity._Closed):
        @model_validator(mode="after")
        def complete(self) -> Self:
            _normalize(self.model_dump(mode="json"), purpose, policy)
            return self

    return _new("ConsistencyResponse_" + identity, {"response": (union, ...)}, Envelope)


def _normalize(
    payload: dict[str, Any], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    capacity._bounded(
        payload, capacity._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
    )
    value = deepcopy(payload["response"])
    full = value["disposition"] == "full_abstention"
    raw = value.pop("coverage")
    if set(raw) != {p["id"] for p in policy["requested_parts"]}:
        raise ValueError("exact_sealed_part_coverage_required")
    if full:
        allowed = {"disposition", "reason", "next_action"} | (
            {"context_requests"} if policy["missing_context"] else set()
        )
        if (
            set(value) != allowed
            or value["reason"]
            != (
                "application_context_required"
                if policy["missing_context"]
                else "insufficient_selected_evidence"
            )
            or value["next_action"] != "request_context"
        ):
            raise ValueError("full_abstention_shape_or_reason_mismatch")
        if policy["missing_context"] and value["context_requests"] != dict.fromkeys(
            policy["missing_context"], "required"
        ):
            raise ValueError("full_abstention_context_requests_mismatch")
    if not full:
        value["claims"] = [{"claim_id": f"c{i + 1}", **c} for i, c in enumerate(value["claims"])]
    ids = {c["claim_id"] for c in value.get("claims", [])}
    coverage: dict[str, Any] = {}
    used: set[str] = set()
    omitted = False
    evidence_reasons = set(previous._values(EvidenceGap))
    omission_reasons = set(previous._values(OmissionGap))
    for part in policy["requested_parts"]:
        item = raw[part["id"]]
        status = item["status"]
        gaps = item["gap_reasons"]
        answer = item.get("answer_claim_ids", [])
        context = item.get("context_claim_ids", [])
        refs = [*answer, *context]
        if (
            status not in STATUS
            or not gaps
            or set(gaps) - (evidence_reasons | omission_reasons | {"none"})
        ):
            raise ValueError("invalid_coverage_status_or_gap_reason")
        if full and (
            status != "lacks_evidence"
            or (policy["missing_context"] and gaps != ["application_context"])
        ):
            raise ValueError("full_abstention_requires_evidence_gaps")
        if len(set(gaps)) != len(gaps):
            raise ValueError("duplicate_gap_reason")
        if len(set(refs)) != len(refs) or set(refs) - ids:
            raise ValueError("duplicate_or_unknown_coverage_reference")
        if full and refs:
            raise ValueError("full_abstention_forbids_claim_references")
        if status == "answered":
            if not answer or gaps != ["none"]:
                raise ValueError("answered_requires_complete_answer_without_gaps")
        elif status == "partial":
            if not answer or "none" in gaps:
                raise ValueError("partial_requires_answer_and_real_remaining_gaps")
        elif answer:
            raise ValueError("unanswered_part_forbids_answer_references")
        if status == "lacks_evidence" and (not set(gaps) <= evidence_reasons):
            raise ValueError("evidence_absence_requires_evidence_gap_reasons")
        if status == "omitted" and (not set(gaps) <= omission_reasons):
            raise ValueError("omission_requires_omission_reasons")
        if omitted and refs:
            raise ValueError("prioritize_requested_parts_before_lower_priority_context")
        omitted = omitted or status == "omitted"
        if (
            part["kind"] == "comparison"
            and answer
            and not set(answer) <= set(value.get("comparison_claims", []))
        ):
            raise ValueError("source_notes_cannot_answer_comparison")
        used.update(refs)
        coverage[part["id"]] = {
            "status": status,
            "gap": gaps[0],
            "gap_reasons": gaps,
            "answer_claim_ids": answer,
            "context_claim_ids": context,
        }
    if used != ids:
        raise ValueError("orphaned_claim_outside_request")
    if not full:
        comparison_parts = [p for p in policy["requested_parts"] if p["kind"] == "comparison"]
        comparison_answer = any(coverage[p["id"]]["answer_claim_ids"] for p in comparison_parts)
        comparison_abstention = bool(comparison_parts) and not comparison_answer
        if comparison_abstention and (
            value.get("comparison_claims") or value.get("comparison_basis")
        ):
            raise ValueError("comparison_notes_cannot_claim_comparison_findings")
        if comparison_answer and not value.get("comparison_claims"):
            raise ValueError("comparison_answer_requires_scored_comparison")
        value["disposition"] = "comparison_abstention" if comparison_abstention else "answer"
        value["abstention"] = "comparison_evidence_required" if comparison_abstention else None
        Draft.model_validate({k: v for k, v in value.items() if k != "disposition"})
    capacity._bounded(
        {"response": value, "coverage": coverage},
        capacity._limits()["internal_json_bytes"],
        "capacity_internal_output_exceeded",
    )
    return {"response": value}, coverage


def schemas(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
    model = response_model(handles, purpose, policy)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def normalize(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    capacity._bounded(
        payload, capacity._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
    )
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return _normalize(parsed.model_dump(mode="json"), purpose, policy)


def normalized_draft(envelope: dict[str, Any], purpose: str) -> Draft:
    value = deepcopy(envelope["response"])
    disposition = value.pop("disposition")
    if disposition == "full_abstention":
        value = {
            "claims": [],
            "background_claims": [],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [
                {"intent": "application_scope", "context_claim_ids": [], "premise_claim_ids": []}
            ],
            "proposal": "request_context",
            "abstention": value["reason"],
        }
    if purpose == "research_comparison":
        value.setdefault("comparison_claims", [])
        value.setdefault("comparison_basis", [])
    return Draft.model_validate(value)


def coverage_summary(coverage: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(r["status"] for r in coverage.values())
    if any(k not in STATUS for k in counts):
        raise ValueError("invalid_coverage_status")
    status = (
        "answered"
        if counts["answered"] == len(coverage)
        else "partial"
        if any(r["answer_claim_ids"] for r in coverage.values())
        else "insufficient_evidence"
        if counts["lacks_evidence"]
        else "omitted"
    )
    return {
        "status": status,
        "parts": len(coverage),
        "fully_answered_parts": counts["answered"],
        "partial_parts": counts["partial"],
        "insufficient_evidence_parts": counts["lacks_evidence"],
        "omitted_parts": counts["omitted"],
        "full_answer_credit": None if status == "answered" else False,
        "basis": "Derived from explicit declared coverage only; relevance, support and human usefulness remain unmeasured.",
    }


def wire_payload(
    envelope: dict[str, Any], coverage: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    value = deepcopy(envelope["response"])
    full = value["disposition"] == "full_abstention"
    if not full:
        value["disposition"] = "answer"
        value.pop("abstention", None)
        claims = value["claims"]
        if [c["claim_id"] for c in claims] != [f"c{i + 1}" for i in range(len(claims))]:
            raise ValueError("consistency_cannot_renumber_existing_claims")
        value["claims"] = [{k: v for k, v in c.items() if k != "claim_id"} for c in claims]
    if set(coverage) != {p["id"] for p in policy["requested_parts"]}:
        raise ValueError("exact_sealed_part_coverage_required")
    value["coverage"] = {}
    for part in policy["requested_parts"]:
        row = coverage[part["id"]]
        if set(row) - {"status", "gap", "gap_reasons", "answer_claim_ids", "context_claim_ids"}:
            raise ValueError("unknown_coverage_field")
        if full and (row.get("answer_claim_ids") or row.get("context_claim_ids")):
            raise ValueError("full_abstention_forbids_claim_references")
        if row["gap"] != row["gap_reasons"][0]:
            raise ValueError("inconsistent_gap_reason_summary")
        value["coverage"][part["id"]] = {
            k: deepcopy(row[k])
            for k in (
                "status",
                "gap_reasons",
                *(() if full else ("answer_claim_ids", "context_claim_ids")),
            )
        }
    _normalize(
        {"response": value},
        "research_comparison" if "comparison_claims" in value else "single_paper",
        policy,
    )
    return {"response": value}


def render(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    envelope, coverage = normalize(payload, handles, purpose, policy)
    draft = normalized_draft(envelope, purpose)
    rows = []
    for part in policy["requested_parts"]:
        row = coverage[part["id"]]
        texts = [
            f"Not answered within the {CLAIMS_BY_MODE[policy['mode']]}-claim budget."
            if g == "claim_budget"
            else GAP_TEXT[g]
            for g in row["gap_reasons"]
            if g != "none"
        ]
        rows.append({**part, **row, "gap_texts": texts, "gap_text": " ".join(texts)})
    questions = []
    for q in draft.questions:
        suffix = (
            " Context links (not factual premises): " + ", ".join(q.context_claim_ids) + "."
            if q.context_claim_ids
            else ""
        )
        suffix += (
            " Relies on cited premise claims: " + ", ".join(q.premise_claim_ids) + "."
            if q.premise_claim_ids
            else ""
        )
        questions.append(QUESTION_INTENTS[q.intent] + suffix)
    requests = [CONTEXT_REQUESTS[k] for k in policy["missing_context"]]
    comparisons = [
        coverage[p["id"]] for p in policy["requested_parts"] if p["kind"] == "comparison"
    ]
    return {
        **draft.model_dump(mode="json"),
        "questions": questions,
        "question_references": [q.model_dump(mode="json") for q in draft.questions],
        "gaps": render_gaps(draft.gaps),
        "proposal": " ".join(requests) if requests else ACTION_INTENTS[draft.proposal],
        "abstention": ABSTENTION_INTENTS.get(draft.abstention or "", draft.abstention),
        "response_disposition": envelope["response"]["disposition"],
        "context_requests": requests,
        "comparison_unanswered": bool(comparisons)
        and not any(r["answer_claim_ids"] for r in comparisons),
        "comparison_incomplete": bool(comparisons)
        and any(r["status"] != "answered" for r in comparisons),
        "request_coverage": rows,
        "coverage_complete": all(r["status"] == "answered" for r in rows),
        "request_outcome": coverage_summary(coverage),
        "claim_request_index": reverse_index(coverage),
        "coverage_basis": "Explicit declaration, not semantic acceptance; partial coverage earns no full-answer credit.",
    }


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: str,
    policy: dict[str, Any],
) -> tuple[Draft, tuple[ResearchClaim, ...]]:
    envelope, _ = normalize(payload, list(catalog), purpose, policy)
    draft = normalized_draft(envelope, purpose)
    claims = []
    for c in draft.claims:
        if any(h not in catalog for h in c.handles):
            raise ValueError("unselected_evidence_handle")
        claim = ResearchClaim(
            c.claim_id,
            c.text,
            ClaimKind.FACTUAL,
            tuple(catalog[h] for h in c.handles),
            required_scope=c.required_scope,
        )
        check = validate_claims([claim], materials)
        if any(not a.identity_resolved or not a.scope_compatible for a in check.assessments):
            raise ValueError("assistance_evidence_identity_or_scope_failed")
        claims.append(claim)
    if draft.comparison_claims:
        by_id = {c.claim_id: c for c in claims}
        if len({r.work_id for key in draft.comparison_basis for r in by_id[key].evidence}) < 2:
            raise ValueError("comparison_requires_two_separately_cited_sources")
    return draft, tuple(claims)
