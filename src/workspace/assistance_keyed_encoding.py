"""Versioned union-reduced encoding; legacy v16 wire remains replayable.

Required c1..c8/c12 keys remain. An unused slot is one canonical empty record,
not a nullable union. Conditional content/reference checks still run through the
unchanged v16 semantic contract before any checker may see a draft.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from enum import Enum, StrEnum
from functools import lru_cache
from typing import Any, Literal, Self, cast, get_args

from anthropic import transform_schema
from pydantic import BaseModel, Field, create_model, model_validator

from src.workspace import assistance_capacity_contract as capacity
from src.workspace import assistance_keyed_contract as legacy
from src.workspace.assistance_contract import digest
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE, MAX_CITATIONS, MAX_CLAIM_CHARACTERS
from src.workspace.grounding import EvidenceRef, ResearchClaim
from src.workspace.material import SourceMaterial

REVISION = "workspace-assistance-keyed-encoding-v16r2"
KEY = "wire_encoding_revision"
UNUSED = {"text": "", "handles": [], "required_scope": "unused"}


def legacy_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if policy.get(KEY) != REVISION:
        raise ValueError("keyed_encoding_revision_mismatch")
    result = {k: v for k, v in policy.items() if k != KEY}
    legacy.prior_policy(result)
    return result


def _values(annotation: Any) -> list[str]:
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [x.value for x in annotation]
    return list(get_args(annotation))


def _fields(model: type[BaseModel]) -> dict[str, Any]:
    return {name: (field.annotation, deepcopy(field)) for name, field in model.model_fields.items()}


def _new(name: str, fields: dict[str, Any], base: Any = capacity._Closed) -> type[BaseModel]:
    return cast(type[BaseModel], create_model(name, __base__=base, **fields))


def _old_payload(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    response = result["response"]
    if response["disposition"] != "full_abstention":
        response["claims"] = {
            key: None if slot["required_scope"] == "unused" else slot
            for key, slot in response["claims"].items()
        }
    return result


def response_model(handles: Sequence[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    return _model(tuple(sorted(set(handles))), purpose, json.dumps(policy, sort_keys=True))


@lru_cache(maxsize=128)
def _model(handles: tuple[str, ...], purpose: str, encoded: str) -> type[BaseModel]:
    policy = json.loads(encoded)
    old_policy = legacy_policy(policy)
    old = legacy.response_model(handles, purpose, old_policy)
    annotation = old.model_fields["response"].annotation
    old_branches = get_args(annotation) or (annotation,)
    normal = [
        b
        for b in old_branches
        if "full_abstention" not in _values(b.model_fields["disposition"].annotation)
    ]
    full = [
        b
        for b in old_branches
        if "full_abstention" in _values(b.model_fields["disposition"].annotation)
    ]
    identity = digest([REVISION, handles, purpose, policy])[7:23]
    branches: list[Any] = []
    if normal:
        template = next(
            (b for b in normal if "answer" in _values(b.model_fields["disposition"].annotation)),
            normal[0],
        )
        claims_map = template.model_fields["claims"].annotation
        active = claims_map.model_fields["c1"].annotation
        active_fields = _fields(active)
        slot_fields = _fields(active)
        slot_fields["text"] = (
            str,
            Field(
                max_length=MAX_CLAIM_CHARACTERS,
                strict=True,
                description='For an unused slot use exactly text="", handles=[], required_scope="unused". An emitted claim is one atomic qualified finding and requires selected evidence.',
            ),
        )
        citations = min(
            [
                MAX_CITATIONS,
                *[
                    m.max_length
                    for m in active.model_fields["handles"].metadata
                    if hasattr(m, "max_length")
                ],
            ]
        )
        slot_fields["handles"] = (
            active_fields["handles"][0],
            Field(min_length=0, max_length=citations),
        )
        scopes = [*_values(active_fields["required_scope"][0]), "unused"]
        slot_fields["required_scope"] = (Literal[tuple(scopes)], Field(...))

        class CanonicalSlot(capacity._Closed):
            @model_validator(mode="after")
            def validate_slot(self) -> Self:
                value = self.model_dump(mode="json")
                if value["required_scope"] == "unused":
                    if value != UNUSED:
                        raise ValueError("noncanonical_unused_claim_slot")
                else:
                    active.model_validate(value)
                return self

        slot = _new("UnionSafeSlot_" + identity, slot_fields, CanonicalSlot)
        fields = _fields(template)
        count = CLAIMS_BY_MODE[policy["mode"]]
        fields["claims"] = (
            _new(
                "UnionSafeClaims_" + identity,
                {f"c{i}": (active if i == 1 else slot, ...) for i in range(1, count + 1)},
            ),
            ...,
        )
        allowed = [d for b in normal for d in _values(b.model_fields["disposition"].annotation)]
        factory = cast(Any, StrEnum)
        fields["disposition"] = (
            factory("UnionSafeDisposition_" + identity, {v: v for v in allowed}),
            Field(...),
        )
        # Shared normal-body fields avoid copying the whole coverage map for
        # comparison abstention. Cross-field disposition semantics are unchanged
        # and still checked by the original v16 validator below.
        if len(allowed) > 1:
            for name in ("comparison_claims", "comparison_basis"):
                if name in fields:
                    fields[name] = (
                        fields[name][0],
                        Field(
                            min_length=0,
                            max_length=count,
                            description="Empty for comparison_abstention. An answered comparison requires independently cited source bases; the local reciprocal checks remain mandatory.",
                        ),
                    )
        branches.append(_new("UnionSafeNormal_" + identity, fields))
    for template in full:
        fields = _fields(template)
        old_coverage = template.model_fields["coverage"].annotation
        parts = {}
        for name, field in old_coverage.model_fields.items():
            alternatives = get_args(field.annotation) or (field.annotation,)
            evidence = next(
                b
                for b in alternatives
                if "lacks_evidence" in _values(b.model_fields["status"].annotation)
            )
            parts[name] = (evidence, ...)
        # Full abstention declares that none of the requested parts is answered;
        # it cannot carry claims/context notes or relabel evidence gaps omissions.
        fields["coverage"] = (_new("UnionSafeFullCoverage_" + identity, parts), ...)
        branches.append(_new("UnionSafeFull_" + identity, fields))
    combined = branches[0]
    for b in branches[1:]:
        combined = combined | b

    class Envelope(capacity._Closed):
        @model_validator(mode="after")
        def semantic_contract(self) -> Self:
            payload = self.model_dump(mode="json")
            capacity._bounded(
                payload, capacity._limits()["raw_draft_utf8_bytes"], "capacity_draft_bytes_exceeded"
            )
            legacy.normalize(_old_payload(payload), handles, purpose, old_policy)
            return self

    return _new(
        "UnionSafeResponse_" + identity,
        {
            "response": (
                combined,
                Field(
                    description="Required named claim and part identities. Use canonical empty claim records for unused c2..cap slots, never null. Full abstention has no claims/references and all requested parts lack evidence. A comparison-only abstention may retain cited context but cannot answer the comparison."
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
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return legacy.normalize(
        _old_payload(parsed.model_dump(mode="json")), handles, purpose, legacy_policy(policy)
    )


def wire_payload(
    envelope: dict[str, Any], coverage: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    value = legacy.wire_payload(envelope, coverage, legacy_policy(policy))
    if value["response"]["disposition"] != "full_abstention":
        value["response"]["claims"] = {
            key: deepcopy(UNUSED) if slot is None else slot
            for key, slot in value["response"]["claims"].items()
        }
    if value["response"]["disposition"] == "full_abstention" and any(
        row["status"] != "lacks_evidence" for row in value["response"]["coverage"].values()
    ):
        raise ValueError("full_abstention_requires_evidence_gaps")
    return value


def render(
    payload: dict[str, Any], handles: Sequence[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return legacy.render(
        _old_payload(parsed.model_dump(mode="json")), handles, purpose, legacy_policy(policy)
    )


def resolve_draft(
    payload: dict[str, Any],
    catalog: dict[str, EvidenceRef],
    materials: Sequence[SourceMaterial],
    *,
    purpose: str,
    policy: dict[str, Any],
) -> tuple[capacity.CapacityDraft, tuple[ResearchClaim, ...]]:
    parsed = response_model(list(catalog), purpose, policy).model_validate(payload)
    return legacy.resolve_draft(
        _old_payload(parsed.model_dump(mode="json")),
        catalog,
        materials,
        purpose=purpose,
        policy=legacy_policy(policy),
    )
