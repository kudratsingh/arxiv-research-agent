"""Prospective v14 compact wire format; no provider, ledger or approval I/O.

Coverage groups replace repeated per-part unions. Only normalization derives the
historical v10 view; every historical schema and validation path stays intact.
Compactness is offline evidence, never proof of remote grammar acceptance.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from enum import StrEnum
from types import GenericAlias
from typing import Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model, model_validator

from src.workspace.assistance_contract import (
    MAX_DRAFT_BYTES,
    PROCEDURAL_REVISION,
    ResponsePurpose,
    digest,
)
from src.workspace.assistance_coverage import AUTHORITATIVE_COVERAGE_REVISION
from src.workspace.assistance_coverage_shapes import EvidenceGap, OmissionGap, ShapedEnvelope

REVISION = "workspace-assistance-compact-coverage-v14"


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def legacy_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Owned, strictly validated v10 policy for existing render/resolve paths."""
    from src.workspace.assistance_coverage import prior_policy

    if policy.get("revision") != REVISION:
        raise ValueError("sealed_compact_revision_mismatch")
    old = deepcopy(policy)
    old["revision"] = AUTHORITATIVE_COVERAGE_REVISION
    prior_policy(old)
    return old


class _ClaimKey(StrEnum):
    C1 = "c1"
    C2 = "c2"
    C3 = "c3"
    C4 = "c4"
    C5 = "c5"
    C6 = "c6"


def _references(minimum: int = 0) -> tuple[Any, Any]:
    return (
        tuple[_ClaimKey, ...],
        Field(
            min_length=minimum,
            max_length=6,
            description="At most six distinct emitted IDs; answer/context cannot overlap.",
        ),
    )


def _rows(model: type[BaseModel]) -> tuple[Any, Any]:
    return (
        GenericAlias(tuple, (model, ...)),
        Field(
            max_length=8,
            description="Zero to eight rows; every sealed part exactly once across all groups.",
        ),
    )


def _coverage_model(identity: str, policy: dict[str, Any], *, full: bool) -> type[BaseModel]:
    factory = cast(Callable[[str, dict[str, str]], type[StrEnum]], StrEnum)
    part_type = factory(
        "CompactPart_" + identity, {p["id"]: p["id"] for p in policy["requested_parts"]}
    )
    part: Any = (part_type, ...)
    common: dict[str, Any] = {} if full else {"context_claim_ids": _references()}
    evidence_fields: dict[str, Any] = {
        "part_id": part,
        "gap": (Literal["application_context"] if policy["missing_context"] else EvidenceGap, ...),
        **common,
    }
    evidence = create_model(
        "CompactGap_" + ("Full_" if full else "Claims_") + identity,
        __base__=_Closed,
        **evidence_fields,
    )
    fields: dict[str, Any] = {}
    if not full:
        answered_fields: dict[str, Any] = {
            "part_id": part,
            "answer_claim_ids": _references(1),
            **common,
        }
        answered = create_model("CompactAnswered_" + identity, __base__=_Closed, **answered_fields)
        fields["answered"] = _rows(answered)
    fields["lacks_evidence"] = _rows(evidence)
    if not policy["missing_context"]:
        omitted_fields: dict[str, Any] = {"part_id": part, "gap": (OmissionGap, ...), **common}
        omitted = create_model(
            "CompactOmitted_" + ("Full_" if full else "Claims_") + identity,
            __base__=_Closed,
            **omitted_fields,
        )
        fields["omitted"] = _rows(omitted)
    return create_model(
        "CompactCoverage_" + ("Full_" if full else "Claims_") + identity,
        __base__=_Closed,
        **fields,
    )


def response_model(handles: list[str], purpose: str, policy: dict[str, Any]) -> type[BaseModel]:
    """Two root branches maximum; one claim/evidence definition for all claims."""
    from src.workspace.assistance_contract import response_model as old_model
    from src.workspace.assistance_policy import task_response_model

    sealed = deepcopy(policy)
    old = legacy_policy(sealed)
    from src.workspace.assistance_coverage import prior_policy

    task_policy = prior_policy(old)
    selected = sorted(set(handles))
    # The old constructor enforces selected catalog and purpose bounds.
    original = old_model(
        selected, purpose=cast(ResponsePurpose, purpose), revision=PROCEDURAL_REVISION
    )
    identity = digest([selected, purpose, sealed])[7:23]
    task = task_response_model(selected, purpose, task_policy)

    task_annotation = task.model_fields["response"].annotation
    task_variants = get_args(task_annotation) or (task_annotation,)
    full_original = next(
        v
        for v in task_variants
        if get_args(v.model_fields["disposition"].annotation) == ("full_abstention",)
    )
    full = create_model(
        "CompactFull_" + identity,
        __base__=full_original,
        coverage=(_coverage_model(identity, old, full=True), ...),
    )
    branches: Any = full
    allowed = tuple(d for d in old["allowed_dispositions"] if d != "full_abstention")
    if allowed:
        fields: dict[str, Any] = {
            name: (field.annotation, deepcopy(field))
            for name, field in original.model_fields.items()
            if name != "abstention"
        }
        original_claim = get_args(original.model_fields["claims"].annotation)[0]
        claim = create_model(
            "CompactClaim_" + identity, __base__=original_claim, claim_id=(_ClaimKey, ...)
        )
        from src.workspace.assistance_contract import ProceduralQuestion

        question = create_model(
            "CompactQuestion_" + identity, __base__=ProceduralQuestion, claim_ids=_references()
        )
        for name in (
            "background_claims",
            "assumption_claims",
            "limitation_claims",
            "comparison_claims",
            "comparison_basis",
        ):
            if name in fields:
                fields[name] = _references()
        fields["questions"] = (
            GenericAlias(tuple, (question, ...)),
            Field(min_length=1, max_length=3),
        )
        fields["claims"] = (
            GenericAlias(tuple, (claim, ...)),
            Field(
                min_length=1,
                max_length=6,
                description="One to six atomic cited claims; retain study scope, comparator, metric definition and conditions. Nonblank text <=360 Unicode characters; one to three distinct selected handles each.",
            ),
        )
        fields["disposition"] = (Literal[allowed], ...)
        fields["coverage"] = (_coverage_model(identity, old, full=False), ...)
        claim_bearing = create_model("CompactClaims_" + identity, __base__=_Closed, **fields)
        branches = full | claim_bearing

    class LocalEnvelope(ShapedEnvelope):
        model_config = ConfigDict(extra="forbid", frozen=True)

        @classmethod
        def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
            schema = super().model_json_schema(*args, **kwargs)

            def remove_titles(value: Any) -> None:
                if isinstance(value, dict):
                    value.pop("title", None)
                    for child in value.values():
                        remove_titles(child)
                elif isinstance(value, list):
                    for child in value:
                        remove_titles(child)

            remove_titles(schema)
            return schema

        @model_validator(mode="after")
        def strict_legacy_semantics(self) -> LocalEnvelope:
            _normalize_validated(self.model_dump(mode="json"), selected, purpose, sealed)
            return self

    return create_model(
        "CompactDraft_" + identity,
        __base__=LocalEnvelope,
        response=(
            branches,
            Field(
                description="Complete JSON <=8000 UTF-8 bytes, at most six atomic claims. Coverage alone maps every sealed part exactly once. Comparison-only notes cannot answer a comparison; no claims.part_ids. Full abstention forbids all claims and claim references. All factual prose remains subject to whole-claim evidence, scope, qualification and semantic review."
            ),
        ),
    )


def _normalize_validated(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    import json

    from src.workspace.assistance_contract import response_model as old_model
    from src.workspace.assistance_coverage import normalize as old_normalize
    from src.workspace.assistance_coverage import prior_policy
    from src.workspace.assistance_policy import normalize_task_output

    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_DRAFT_BYTES:
        raise ValueError("assistance_response_too_large")
    old = legacy_policy(policy)
    value = deepcopy(payload["response"])
    grouped = value.pop("coverage")
    coverage: dict[str, Any] = {}
    for status, rows in grouped.items():
        for row in rows:
            part_id = row["part_id"]
            if part_id in coverage:
                raise ValueError("duplicate_or_overlapping_coverage_part")
            coverage[part_id] = {
                "status": status,
                **{k: v for k, v in row.items() if k != "part_id"},
                **({"gap": "none"} if status == "answered" else {}),
            }
    if set(coverage) != {p["id"] for p in old["requested_parts"]}:
        raise ValueError("exact_sealed_part_coverage_required")
    if value["disposition"] != "full_abstention":
        value["abstention"] = None
        if value["disposition"] == "comparison_abstention":
            if value.get("comparison_claims") or value.get("comparison_basis"):
                raise ValueError("source_notes_cannot_answer_comparison")
            value.pop("comparison_claims", None)
            value.pop("comparison_basis", None)
            value["abstention"] = "comparison_evidence_required"
    value["coverage"] = {p["id"]: coverage[p["id"]] for p in old["requested_parts"]}
    base, resolved_coverage = old_normalize({"response": value}, handles, purpose, old)
    normalized = normalize_task_output(base, handles, purpose, prior_policy(old))
    old_model(
        handles, purpose=cast(ResponsePurpose, purpose), revision=PROCEDURAL_REVISION
    ).model_validate(normalized)
    return base, resolved_coverage


def normalize(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the existing task envelope and canonical per-part coverage tuple."""
    import json

    if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_DRAFT_BYTES:
        raise ValueError("assistance_response_too_large")
    parsed = response_model(handles, purpose, policy).model_validate(payload)
    return _normalize_validated(parsed.model_dump(mode="json"), handles, purpose, policy)


def fixture_payload(
    payload: dict[str, Any], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    """Owned synthetic v10-to-v14 derivative; never mutate archived provider data.

    The caller must label this a synthetic successor. This conversion establishes
    no evidence truth, provider compatibility, or acceptance of its input.
    """
    from pydantic import TypeAdapter

    from src.workspace.assistance_coverage import CoverageRecord
    from src.workspace.assistance_coverage_shapes import coverage_type

    old = legacy_policy(policy)
    value = deepcopy(payload["response"])
    if set(payload) != {"response"} or set(value["coverage"]) != {
        part["id"] for part in old["requested_parts"]
    }:
        raise ValueError("exact_sealed_part_coverage_required")
    full = value["disposition"] == "full_abstention"
    if not full and (
        "abstention" not in value
        or value["abstention"]
        != (
            "comparison_evidence_required"
            if value["disposition"] == "comparison_abstention"
            else None
        )
    ):
        raise ValueError("fixture_abstention_disposition_mismatch")
    source_row = TypeAdapter(coverage_type(full=full, missing_context=bool(old["missing_context"])))
    groups: dict[str, list[dict[str, Any]]] = {} if full else {"answered": []}
    groups["lacks_evidence"] = []
    if not old["missing_context"]:
        groups["omitted"] = []
    for part in old["requested_parts"]:
        row = deepcopy(value["coverage"][part["id"]])
        # Validate every source field before removing redundant wire structure.
        # Otherwise dropping gap/status/empty references could repair rejected input.
        source_row.validate_python(row)
        CoverageRecord.model_validate({"answer_claim_ids": [], "context_claim_ids": [], **row})
        status = row.pop("status")
        if status == "answered":
            row.pop("gap")
        if full:
            if any(k.endswith("claim_ids") for k in row):
                raise ValueError("full_abstention_forbids_claim_references")
        else:
            row.setdefault("context_claim_ids", [])
            if status != "answered" and row.pop("answer_claim_ids", []):
                raise ValueError("unanswered_part_forbids_answer_references")
        groups[status].append({"part_id": part["id"], **row})
    value["coverage"] = groups
    if not full:
        value.pop("abstention")
        if purpose == "research_comparison":
            value.setdefault("comparison_claims", [])
            value.setdefault("comparison_basis", [])
    return {"response": value}
