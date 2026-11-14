"""Prospective exactly-once generated identities, with lossless coverage reasons.

Historical v15 schemas and outputs remain under their original validators. These
pure adapters retain the existing substantive checks and never create permission.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from enum import StrEnum
from functools import lru_cache
from types import GenericAlias
from typing import Any, Literal, cast

from anthropic import transform_schema
from pydantic import BaseModel, Field, create_model, model_validator

from src.workspace import assistance_capacity_contract as prior
from src.workspace.assistance_contract import (
    ABSTENTION_INTENTS,
    ACTION_INTENTS,
    QUESTION_INTENTS,
    digest,
    render_gaps,
)
from src.workspace.assistance_coverage import GAP_TEXT, reverse_index
from src.workspace.assistance_coverage_shapes import EvidenceGap, OmissionGap
from src.workspace.assistance_policy import CONTEXT_REQUESTS
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE
from src.workspace.grounding import EvidenceRef, ResearchClaim
from src.workspace.material import SourceMaterial

REVISION = "workspace-assistance-keyed-v16"
NORMALIZATION_REVISION = "workspace-assistance-keyed-normalization-v16"


def _new(name: str, *, __base__: Any, **fields: Any) -> type[BaseModel]:
    return cast(type[BaseModel], create_model(name, __base__=__base__, **fields))


def prior_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get("revision") != REVISION:
        raise ValueError("sealed_keyed_revision_mismatch")
    value = {**policy, "revision": prior.REVISION}
    prior.validate_policy(value)
    return value


def seal_policy(context: Any, mode: str, count: int, question: str) -> dict[str, Any]:
    return {**prior.seal_policy(context, mode, count, question), "revision": REVISION}


@lru_cache(maxsize=64)
def _fixed(value: str) -> Any:
    # SDK transform drops const, but preserves one-value enum definitions.
    factory = cast(Any, StrEnum)
    return factory("KeyedFixed_" + value, {"VALUE": value})


def _refs(identifier: Any, minimum: int = 0, maximum: int = 12) -> tuple[Any, Any]:
    return GenericAlias(tuple, (identifier, ...)), Field(min_length=minimum, max_length=maximum)


def _coverage(
    identity: str,
    policy: dict[str, Any],
    identifier: Any,
    *,
    full: bool,
    comparison_only: bool = False,
) -> type[BaseModel]:
    refs = {} if full else {"context_claim_ids": _refs(identifier)}
    gap_type: Any = _fixed("application_context") if policy["missing_context"] else EvidenceGap
    evidence = _new(
        "KeyedEvidenceGap_" + identity + str(full),
        __base__=prior._Closed,
        status=(_fixed("lacks_evidence"), ...),
        gap_reasons=(GenericAlias(tuple, (gap_type, ...)), Field(min_length=1, max_length=10)),
        **refs,
    )
    record: Any = evidence
    if not policy["missing_context"]:
        omission = _new(
            "KeyedOmission_" + identity + str(full),
            __base__=prior._Closed,
            status=(_fixed("omitted"), ...),
            gap_reasons=(tuple[OmissionGap, ...], Field(min_length=1, max_length=2)),
            **refs,
        )
        record = evidence | omission
    unanswered_record = record
    if not full:
        answered = _new(
            "KeyedAnswered_" + identity,
            __base__=prior._Closed,
            status=(_fixed("answered"), ...),
            gap_reasons=(
                GenericAlias(tuple, (_fixed("none"), ...)),
                Field(min_length=1, max_length=1),
            ),
            answer_claim_ids=_refs(identifier, minimum=1),
            **refs,
        )
        record = answered | record
    # Named required properties make identity completeness structural. Reused
    # record definitions avoid a copy of each branch for each requested part.
    return _new(
        "KeyedCoverage_" + identity + str(full) + str(comparison_only),
        __base__=prior._Closed,
        **{
            p["id"]: (
                unanswered_record if comparison_only and p["kind"] == "comparison" else record,
                ...,
            )
            for p in policy["requested_parts"]
        },
    )


def response_model(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    return _model(
        tuple(sorted(set(handles))), purpose, json.dumps(policy, sort_keys=True, ensure_ascii=False)
    )


@lru_cache(maxsize=128)
def _model(handles: tuple[str, ...], purpose: str, encoded: str) -> type[BaseModel]:
    from typing import get_args

    policy = json.loads(encoded)
    old_policy = prior_policy(policy)
    old_model = prior.response_model(handles, purpose, old_policy)
    identity = digest([list(handles), purpose, policy])[7:23]
    count = CLAIMS_BY_MODE[policy["mode"]]
    identifiers = Literal[tuple(f"c{i}" for i in range(1, count + 1))]  # type: ignore[valid-type]
    branches: list[Any] = []
    for original in get_args(old_model.model_fields["response"].annotation) or (
        old_model.model_fields["response"].annotation,
    ):
        full = get_args(original.model_fields["disposition"].annotation) == ("full_abstention",)
        fields: dict[str, Any] = {
            "coverage": (_coverage(identity, policy, identifiers, full=full), ...)
        }
        if full:
            fields.update(
                disposition=(_fixed("full_abstention"), ...),
                reason=(
                    _fixed(
                        "application_context_required"
                        if policy["missing_context"]
                        else "insufficient_selected_evidence"
                    ),
                    ...,
                ),
                next_action=(_fixed("request_context"), ...),
            )
            if policy["missing_context"]:
                fields["context_requests"] = (
                    _new(
                        "KeyedContext_" + identity,
                        __base__=prior._Closed,
                        **{k: (_fixed("required"), ...) for k in policy["missing_context"]},
                    ),
                    ...,
                )
        else:
            factory = cast(Any, StrEnum)
            allowed = [v for v in policy["allowed_dispositions"] if v != "full_abstention"]
            fields["disposition"] = (
                factory("KeyedDisposition_" + identity, {v: v for v in allowed}),
                ...,
            )
        if not full:
            old_claim = get_args(original.model_fields["claims"].annotation)[0]
            # The name is authoritative. No claim_id is generated inside the
            # claim value, so a conflicting second identity cannot be supplied.
            claim_fields = {
                name: (field.annotation, deepcopy(field))
                for name, field in old_claim.model_fields.items()
                if name != "claim_id"
            }
            claim_value = _new("KeyedClaim_" + identity, __base__=prior._Closed, **claim_fields)
            slots = {
                f"c{i}": (claim_value if i == 1 else claim_value | None, ...)
                for i in range(1, count + 1)
            }
            fields["claims"] = (
                _new("KeyedClaims_" + identity, __base__=prior._Closed, **slots),
                ...,
            )
            for name in (
                "background_claims",
                "assumption_claims",
                "limitation_claims",
                "comparison_claims",
                "comparison_basis",
            ):
                if name in original.model_fields:
                    fields[name] = _refs(identifiers, maximum=count)
            question_intents = [
                "measured_and_proposed",
                "methods",
                "qualifications",
                "implementation",
                "counterevidence",
                "application_scope",
            ]
            factory = cast(Any, StrEnum)
            neutral_question = _new(
                "KeyedNeutralQuestion_" + identity,
                __base__=prior.CapacityQuestion,
                intent=(
                    factory("KeyedNeutralIntent_" + identity, {v: v for v in question_intents}),
                    ...,
                ),
                claim_ids=_refs(identifiers, maximum=count),
            )
            cited_question = _new(
                "KeyedCitedQuestion_" + identity,
                __base__=prior.CapacityQuestion,
                intent=(_fixed("investigate_claim"), ...),
                claim_ids=_refs(identifiers, minimum=1, maximum=count),
            )
            question = neutral_question | cited_question
            fields["questions"] = (
                GenericAlias(tuple, (question, ...)),
                Field(min_length=1, max_length=3),
            )
        if full:
            branches.append(_new("Keyed" + original.__name__, __base__=original, **fields))
        else:
            for disposition in allowed:
                specific = {**fields, "disposition": (_fixed(disposition), ...)}
                if disposition == "comparison_abstention":
                    specific["coverage"] = (
                        _coverage(identity, policy, identifiers, full=False, comparison_only=True),
                        ...,
                    )
                    for key in ("comparison_claims", "comparison_basis"):
                        if key in original.model_fields:
                            specific[key] = _refs(identifiers, maximum=0)
                elif policy["task_intent"] == "comparison":
                    specific["comparison_claims"] = _refs(identifiers, minimum=1, maximum=count)
                    specific["comparison_basis"] = _refs(identifiers, minimum=2, maximum=count)
                branches.append(
                    _new("Keyed" + disposition + original.__name__, __base__=original, **specific)
                )
    annotation = branches[0]
    for branch in branches[1:]:
        annotation = annotation | branch

    class Envelope(prior._Closed):
        @model_validator(mode="after")
        def complete(self) -> Envelope:
            _normalize_validated(self.model_dump(mode="json"), handles, purpose, policy)
            return self

    return _new(
        "KeyedResponse_" + identity,
        __base__=Envelope,
        response=(
            annotation,
            Field(
                description="Exactly one named entry per sealed requested part; several missing details belong in that entry's gap_reasons. Claim IDs are the named slots; null means unused. Never emit a second identity or model-authored reverse mapping."
            ),
        ),
    )


def schemas(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
    model = response_model(handles, purpose, policy)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def _normalize_validated(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior._bounded(
        payload, prior._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
    )
    old_policy = prior_policy(policy)
    value = deepcopy(payload["response"])
    full = value["disposition"] == "full_abstention"
    keyed = value.pop("coverage")
    reasons: dict[str, list[str]] = {}
    groups: dict[str, list[Any]] = {"lacks_evidence": []}
    if not full:
        groups["answered"] = []
        if not policy["missing_context"]:
            groups["omitted"] = []
        slots = value["claims"]
        value["claims"] = [
            {"claim_id": key, **item} for key, item in slots.items() if item is not None
        ]
    elif not policy["missing_context"]:
        groups["omitted"] = []
    for key, row in keyed.items():
        reasons[key] = row["gap_reasons"]
        if len(set(reasons[key])) != len(reasons[key]):
            raise ValueError("duplicate_gap_reason")
        status = row["status"]
        item = {k: deepcopy(v) for k, v in row.items() if k not in {"status", "gap_reasons"}}
        item["part_id"] = key
        if status != "answered":
            item["gap"] = reasons[key][0]
        groups[status].append(item)
    value["coverage"] = groups
    # Reuse, rather than relax, the historical substantive validators. All
    # reasons have already been typed by the status-specific wire/local model.
    normalized, coverage = prior.normalize({"response": value}, handles, purpose, old_policy)
    for key, row in coverage.items():
        row["gap_reasons"] = reasons[key]
    return normalized, coverage


def normalize(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    prior._bounded(
        payload, prior._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
    )
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return _normalize_validated(parsed.model_dump(mode="json"), handles, purpose, policy)


def _legacy_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, row in coverage.items():
        if set(row) - {"status", "gap", "gap_reasons", "answer_claim_ids", "context_claim_ids"}:
            raise ValueError("unknown_coverage_field")
        reasons = row.get("gap_reasons", [row["gap"]])
        if not reasons or row["gap"] != reasons[0]:
            raise ValueError("inconsistent_gap_reason_summary")
        result[key] = {k: v for k, v in row.items() if k != "gap_reasons"}
    return result


def wire_payload(
    envelope: dict[str, Any], coverage: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    """Lossless inverse for owned normalized data; never convert a live failure."""
    old = prior.wire_payload(envelope, _legacy_coverage(coverage), prior_policy(policy))
    value = old["response"]
    full = value["disposition"] == "full_abstention"
    value.pop("coverage")
    keyed = {}
    for part in policy["requested_parts"]:
        key = part["id"]
        row = coverage[key]
        reasons = row.get("gap_reasons", [row["gap"]])
        if not reasons or row["gap"] != reasons[0]:
            raise ValueError("inconsistent_gap_reason_summary")
        item = {"status": row["status"], "gap_reasons": list(reasons)}
        if not full:
            item["context_claim_ids"] = list(row.get("context_claim_ids", []))
            if row["status"] == "answered":
                item["answer_claim_ids"] = list(row["answer_claim_ids"])
        elif row.get("answer_claim_ids") or row.get("context_claim_ids"):
            raise ValueError("full_abstention_forbids_claim_references")
        keyed[key] = item
    value["coverage"] = keyed
    if not full:
        by_id = {
            c["claim_id"]: {k: v for k, v in c.items() if k != "claim_id"} for c in value["claims"]
        }
        value["claims"] = {
            f"c{i}": by_id.get(f"c{i}") for i in range(1, CLAIMS_BY_MODE[policy["mode"]] + 1)
        }
    return {"response": value}


def render(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    envelope, coverage = normalize(payload, handles, purpose, policy)
    draft = prior.normalized_draft(envelope, purpose)
    requests = [CONTEXT_REQUESTS[k] for k in policy["missing_context"]]
    rows = []
    for part in policy["requested_parts"]:
        row = coverage[part["id"]]
        texts = [
            f"Not answered within the {CLAIMS_BY_MODE[policy['mode']]}-claim budget."
            if reason == "claim_budget"
            else GAP_TEXT[reason]
            for reason in row["gap_reasons"]
            if reason != "none"
        ]
        rows.append({**part, **row, "gap_texts": texts, "gap_text": " ".join(texts)})
    return {
        **draft.model_dump(mode="json"),
        "questions": [
            QUESTION_INTENTS[q.intent]
            + (" Refer to cited claims " + ", ".join(q.claim_ids) + "." if q.claim_ids else "")
            for q in draft.questions
        ],
        "gaps": render_gaps(draft.gaps),
        "proposal": " ".join(requests) if requests else ACTION_INTENTS[draft.proposal],
        "abstention": ABSTENTION_INTENTS.get(draft.abstention or "", draft.abstention),
        "response_disposition": envelope["response"]["disposition"],
        "context_requests": requests,
        "comparison_unanswered": envelope["response"]["disposition"] == "comparison_abstention",
        "request_coverage": rows,
        "coverage_complete": all(r["status"] == "answered" for r in rows),
        "claim_request_index": reverse_index(coverage),
        "coverage_basis": "Declared coverage; machine checks are unqualified and human review is unmeasured",
    }


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: str,
    policy: dict[str, Any],
) -> tuple[prior.CapacityDraft, tuple[ResearchClaim, ...]]:
    normalized, coverage = normalize(payload, list(catalog), purpose, policy)
    # Exact evidence checks use the existing implementation on a lossless
    # normalized-owned inverse. The additional reasons do not change evidence.
    return prior.resolve_draft(
        prior.wire_payload(normalized, _legacy_coverage(coverage), prior_policy(policy)),
        catalog,
        materials,
        purpose=purpose,
        policy=prior_policy(policy),
    )
