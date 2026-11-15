"""Prospective compact wire codec; no permissions or remote compatibility claim.

Claims are a variable sequence. c1..cN are assigned by the server in response
order, never supplied as a second mapping. Required coverage keys come from the
sealed task. Semantic checks use the unchanged rich v16 model and evidence gates.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from enum import StrEnum
from functools import lru_cache
from types import GenericAlias
from typing import Any, Literal, Self, cast, get_args

from anthropic import transform_schema
from pydantic import BaseModel, Field, create_model, model_validator

from src.workspace import assistance_capacity_contract as capacity
from src.workspace import assistance_keyed_encoding as prior
from src.workspace.assistance_contract import digest
from src.workspace.assistance_coverage_shapes import EvidenceGap, OmissionGap
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE
from src.workspace.grounding import EvidenceRef, ResearchClaim
from src.workspace.material import SourceMaterial

KEY = prior.KEY
REVISION = "workspace-assistance-compact-wire-v17"
LIST_CONTROL = "workspace-assistance-variable-claims-v17-control"
REVISIONS = frozenset({REVISION, LIST_CONTROL})


def prior_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get(KEY) not in REVISIONS:
        raise ValueError("compact_encoding_revision_mismatch")
    result = {**policy, KEY: prior.REVISION}
    prior.legacy_policy(result)
    return result


def _values(annotation: Any) -> list[str]:
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return [x.value for x in annotation]
    return list(get_args(annotation))


def _fields(model: type[BaseModel]) -> dict[str, Any]:
    return {name: (field.annotation, deepcopy(field)) for name, field in model.model_fields.items()}


def _new(name: str, fields: dict[str, Any], base: Any = capacity._Closed) -> type[BaseModel]:
    return cast(type[BaseModel], create_model(name, __base__=base, **fields))


def _to_prior(payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(payload)
    response = value["response"]
    if response["disposition"] == "full_abstention":
        return value
    claims = response["claims"]
    cap = CLAIMS_BY_MODE[policy["mode"]]
    response["claims"] = {
        f"c{i}": claims[i - 1] if i <= len(claims) else deepcopy(prior.UNUSED)
        for i in range(1, cap + 1)
    }
    if policy[KEY] == REVISION:
        for row in response["coverage"].values():
            if row["status"] != "answered":
                if row["answer_claim_ids"]:
                    raise ValueError("compact_unanswered_part_forbids_answer_references")
                row.pop("answer_claim_ids")
    return value


def response_model(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    prior_policy(policy)
    return _model(tuple(sorted(set(handles))), purpose, json.dumps(policy, sort_keys=True))


@lru_cache(maxsize=128)
def _model(handles: tuple[str, ...], purpose: str, encoded: str) -> type[BaseModel]:
    policy = json.loads(encoded)
    old_policy = prior_policy(policy)
    old = prior.response_model(handles, purpose, old_policy)
    annotation = old.model_fields["response"].annotation
    alternatives = get_args(annotation) or (annotation,)
    identity = digest([policy, handles, purpose])[7:23]
    count = CLAIMS_BY_MODE[policy["mode"]]
    identifiers = cast(Any, Literal)[tuple(f"c{i}" for i in range(1, count + 1))]
    branches = []
    for original in alternatives:
        fields = _fields(original)
        if "full_abstention" not in _values(original.model_fields["disposition"].annotation):
            claim_model = original.model_fields["claims"].annotation.model_fields["c1"].annotation
            fields["claims"] = (
                GenericAlias(tuple, (claim_model, ...)),
                Field(
                    min_length=1,
                    max_length=count,
                    description=(
                        f"Emit only actual atomic qualified claims, between1and{count}. "
                        "Do not emit unused placeholders or IDs. The server names the first "
                        "claim c1, the second c2, etc. Coverage alone maps parts to these "
                        "positions. Claims may not carry claim_id or part_ids."
                    ),
                ),
            )
            if policy[KEY] == REVISION:
                reasons = tuple(
                    dict.fromkeys(["none", *_values(EvidenceGap), *_values(OmissionGap)])
                )
                row = _new(
                    "CompactCoverageRow_" + identity,
                    {
                        "status": (Literal["answered", "lacks_evidence", "omitted"], ...),
                        "gap_reasons": (
                            GenericAlias(tuple, (cast(Any, Literal)[reasons], ...)),
                            Field(min_length=1, max_length=10),
                        ),
                        "answer_claim_ids": (GenericAlias(tuple, (identifiers, ...)), Field(max_length=count)),
                        "context_claim_ids": (GenericAlias(tuple, (identifiers, ...)), Field(max_length=count)),
                    },
                )
                fields["coverage"] = (
                    _new(
                        "CompactCoverage_" + identity,
                        {
                            part["id"]: (
                                row,
                                Field(
                                    description=(
                                        "answered: nonempty answer_claim_ids and gap_reasons=[none]. "
                                        "lacks_evidence/omitted: answer_claim_ids=[] and reasons of the "
                                        "corresponding category. Context references do not answer a part. "
                                        "No duplicates or answer/context overlap; several gaps stay here."
                                    )
                                ),
                            )
                            for part in policy["requested_parts"]
                        },
                    ),
                    ...,
                )
                factory = cast(Any, StrEnum)
                question_intents = [
                    "measured_and_proposed",
                    "methods",
                    "qualifications",
                    "implementation",
                    "counterevidence",
                    "application_scope",
                    "investigate_claim",
                ]
                class NeutralQuestion(capacity.CapacityQuestion):
                    @model_validator(mode="after")
                    def neutral_references(self) -> Self:
                        if self.intent != "investigate_claim" and self.claim_ids:
                            raise ValueError("compact_neutral_question_forbids_claim_premise")
                        return self

                question = _new(
                    "CompactQuestion_" + identity,
                    {
                        "intent": (
                            factory(
                                "CompactQuestionIntent_" + identity,
                                {x: x for x in question_intents},
                            ),
                            ...,
                        ),
                        "claim_ids": (
                            GenericAlias(tuple, (identifiers, ...)),
                            Field(
                                max_length=count,
                                description="investigate_claim requires emitted claim positions; neutral procedural intents require an empty list.",
                            ),
                        ),
                    },
                    NeutralQuestion,
                )
                fields["questions"] = (GenericAlias(tuple, (question, ...)), Field(min_length=1, max_length=3))
        branches.append(_new("Compact" + original.__name__, fields))
    combined: Any = branches[0]
    for branch in branches[1:]:
        combined = combined | branch

    class Envelope(capacity._Closed):
        @model_validator(mode="after")
        def semantics(self) -> Self:
            value = self.model_dump(mode="json")
            capacity._bounded(
                value, capacity._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
            )
            prior.normalize(_to_prior(value, policy), handles, purpose, old_policy)
            return self

    return _new(
        "CompactResponse_" + identity,
        {
            "response": (
                combined,
                Field(
                    description=(
                        "Required part keys are sealed. Full abstention has no claims or references. "
                        "Only emitted claim positions exist; all references must resolve. Preserve "
                        "independent facts and every study qualification. No reverse mapping."
                    )
                ),
            )
        },
        Envelope,
    )


def schemas(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
    model = response_model(handles, purpose, policy)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def normalize(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = response_model(handles, purpose, policy).model_validate(payload).model_dump(mode="json")
    return prior.normalize(_to_prior(value, policy), handles, purpose, prior_policy(policy))


def wire_payload(
    envelope: dict[str, Any], coverage: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    value = prior.wire_payload(envelope, coverage, prior_policy(policy))
    response = value["response"]
    if response["disposition"] != "full_abstention":
        claims = response["claims"]
        active = [(key, row) for key, row in claims.items() if row != prior.UNUSED]
        if [key for key, _ in active] != [f"c{i}" for i in range(1, len(active) + 1)]:
            raise ValueError("compact_cannot_renumber_existing_claims")
        response["claims"] = [row for _, row in active]
        if policy[KEY] == REVISION:
            for row in response["coverage"].values():
                row.setdefault("answer_claim_ids", [])
    return value


def render(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    value = response_model(handles, purpose, policy).model_validate(payload).model_dump(mode="json")
    return prior.render(_to_prior(value, policy), handles, purpose, prior_policy(policy))


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: str,
    policy: dict[str, Any],
) -> tuple[capacity.CapacityDraft, tuple[ResearchClaim, ...]]:
    value = (
        response_model(list(catalog), purpose, policy)
        .model_validate(payload)
        .model_dump(mode="json")
    )
    return prior.resolve_draft(
        _to_prior(value, policy), catalog, materials, purpose=purpose, policy=prior_policy(policy)
    )
