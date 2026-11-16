"""Prospective exact-identity checker contracts; pure offline transformations.

Only judgments come from the wire. Identities and digests come from the sealed
current context after exact key validation. Completion status, context sealing,
support and scientific quality remain independent caller responsibilities.
Historical v15 models and responses are never changed or migrated here.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from types import GenericAlias
from typing import Annotated, Any, Literal

from anthropic import transform_schema
from pydantic import AfterValidator, BaseModel, Field, TypeAdapter, create_model, model_validator

from src.workspace.assistance_capacity_contract import (
    ClaimKey,
    PartReview,
    ProbeSupportReview,
    QualityReview,
    SupportReview,
    _bounded,
    _Closed,
    _limits,
    _Reason,
    _validate_locations,
)
from src.workspace.assistance_capacity_contract import (
    ProseFinding as PriorProseFinding,
)
from src.workspace.assistance_contract import digest
from src.workspace.assistance_coverage import Retention
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE, MAX_PARTS
from src.workspace.grounding import SupportDecision

REVISION = "workspace-assistance-keyed-checks-v16"
NORMALIZATION_REVISION = "workspace-assistance-keyed-normalization-v16"
_MAX_CLAIMS = max(CLAIMS_BY_MODE.values())


class _Revision(StrEnum):
    V16 = REVISION


class _ClaimJudgment(_Reason):
    """Judge this exact current claim; the server supplies its digest and ID."""

    decision: SupportDecision
    atomicity: Literal["atomic", "bundled", "uncertain"]
    qualifications: Retention


class _PartJudgment(_Reason):
    """Judge the whole exact requested part; the server supplies its binding."""

    decision: Literal["answered", "lacks_evidence", "omitted", "uncertain"]


class _SupportJudgment(_Reason):
    """Support judgment for this exact opaque probe; do not echo its binding."""

    decision: SupportDecision


def _structure(claims: Any, parts: Any, review: str, findings: Any) -> None:
    for rows, key in ((claims, "claim_id"), (parts, "part_id")):
        if len({getattr(row, key) for row in rows}) != len(rows):
            raise ValueError("keyed_duplicate_" + key)
    if (review == "procedural_only") != (not findings):
        raise ValueError("prose_finding_required_or_inconsistent")
    if len({(row.field, row.index, row.reason) for row in findings}) != len(findings):
        raise ValueError("duplicate_prose_finding")


class ProseFinding(PriorProseFinding):
    """Exact current v16 list locations are bounded by context, not legacy index2."""

    index: int | None = Field(ge=0, strict=True)


class _ProseChecks(_Closed):
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[ProseFinding, ...]

    def validate_locations(self, prose: dict[str, Any]) -> None:
        _validate_locations(self.prose_findings, prose)


class CoverageChecks(_ProseChecks):
    """v15 normalized judgments with independently located prose findings."""

    checks: tuple[SupportReview, ...] = Field(max_length=_MAX_CLAIMS)
    claim_quality: tuple[QualityReview, ...] = Field(max_length=_MAX_CLAIMS)
    coverage_checks: tuple[PartReview, ...] = Field(max_length=MAX_PARTS)
    priority_review: Literal["respected", "violated", "uncertain"]

    @model_validator(mode="after")
    def complete_structure(self) -> CoverageChecks:
        _structure(self.checks, self.coverage_checks, self.prose_review, self.prose_findings)
        support = {row.claim_id: row.input_digest for row in self.checks}
        quality = {row.claim_id: row.input_digest for row in self.claim_quality}
        if len(quality) != len(self.claim_quality) or support != quality:
            raise ValueError("claim_quality_binding_mismatch")
        _bounded(
            self.model_dump(mode="json"),
            _limits()["normalized_checker_utf8_bytes"],
            "capacity_normalized_checks_bytes_exceeded",
        )
        return self


class ProbeChecks(_ProseChecks):
    checks: tuple[ProbeSupportReview, ...] = Field(max_length=_MAX_CLAIMS)

    @model_validator(mode="after")
    def complete_structure(self) -> ProbeChecks:
        _structure(self.checks, (), self.prose_review, self.prose_findings)
        _bounded(
            self.model_dump(mode="json"),
            _limits()["normalized_checker_utf8_bytes"],
            "capacity_normalized_checks_bytes_exceeded",
        )
        return self


def checks_model() -> type[CoverageChecks]:
    return CoverageChecks


def finding_capacity() -> dict[str, Any]:
    """Prospective v16 findings are byte-bounded, without count-based omission.

    Historical capacity policy and v15 count guards remain unchanged. Exact
    context locations, nonblank reasons and duplicate rejection remain required.
    """
    return {
        "revision": "workspace-assistance-keyed-finding-capacity-v16",
        "aggregate_findings_limit": None,
        "per_location_findings_limit": None,
        "compact_checker_utf8_bytes": _limits()["compact_checker_utf8_bytes"],
        "normalized_checker_utf8_bytes": _limits()["normalized_checker_utf8_bytes"],
    }


def probe_checks_model(identifiers: Sequence[str] | None = None) -> type[ProbeChecks]:
    if identifiers is None:
        return ProbeChecks
    selected = list(identifiers)
    if not selected:
        raise ValueError("keyed_context_identity_invalid")
    # Validate the same identity rules without inventing evidence digests.
    _identities(selected, probe=True)
    row = create_model(
        "KeyedProbeSupport_" + digest(selected)[7:23],
        __base__=ProbeSupportReview,
        claim_id=(Literal[tuple(selected)], ...),
    )
    return create_model(
        "KeyedProbeChecks_" + digest(selected)[7:23],
        __base__=ProbeChecks,
        checks=(GenericAlias(tuple, (row, ...)), Field(max_length=_MAX_CLAIMS)),
    )


def _identities(values: list[Any], *, probe: bool, parts: bool = False) -> None:
    allowed = {f"p{i}" for i in range(1, MAX_PARTS + 1)} if parts else set(ClaimKey)
    maximum = MAX_PARTS if parts else _MAX_CLAIMS
    if (
        len(values) > maximum
        or any(
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 120
            or (not probe and value not in allowed)
            for value in values
        )
        or len(set(values)) != len(values)
    ):
        raise ValueError("keyed_context_identity_invalid")


def _context(
    context: dict[str, Any], *, probe: bool
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not isinstance(context, dict):
        raise ValueError("keyed_context_invalid")
    result: list[list[dict[str, str]]] = []
    for collection, key in (("claim_inputs", "claim_id"), ("coverage_inputs", "part_id")):
        if probe and collection == "coverage_inputs":
            result.append([])
            continue
        rows = context.get(collection)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("keyed_context_inputs_required")
        identifiers = [row.get(key) for row in rows]
        _identities(identifiers, probe=probe and key == "claim_id", parts=key == "part_id")
        validated = []
        for row in rows:
            # Existing field models enforce the exact server digest syntax.
            field = ProbeSupportReview.model_fields["input_digest"]
            TypeAdapter(field.rebuild_annotation()).validate_python(row.get("input_digest"))
            validated.append({key: row[key], "input_digest": row["input_digest"]})
        result.append(validated)
    return result[0], result[1]


def prose_locations(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Catalog only exact nonblank locations in the current unscored prose.

    Stable opaque keys follow sorted allowed field names and ascending existing
    list indices. Descriptions locate text already present in the request; no
    prose, private context, digest or model-authored location is copied here.
    """
    prose = context.get("unscored_prose", {})
    if not isinstance(prose, dict):
        raise ValueError("keyed_context_prose_invalid")
    result: dict[str, dict[str, Any]] = {}
    for field in sorted(
        ("background", "assumptions", "comparison", "gaps", "questions", "proposal", "abstention")
    ):
        value = prose.get(field)
        candidates: list[tuple[int | None, Any]]
        if field in {"assumptions", "gaps", "questions"}:
            candidates = list(enumerate(value)) if isinstance(value, list) else []
        else:
            candidates = [(None, value)]
        for index, text in candidates:
            if not isinstance(text, str) or not text.strip():
                continue
            location = field + (f"[{index}]" if index is not None else "")
            result[f"l{len(result) + 1}"] = {
                "field": field,
                "index": index,
                "description": f"Independent finding reasons for exact unscored_prose.{location}; its text is already in the request. Empty array means no finding at this location.",
            }
    return result


def _nonblank_finding_reason(value: str) -> str:
    return _Reason(reason=value).reason


_ProseReason = Annotated[
    str, Field(min_length=1, strict=True), AfterValidator(_nonblank_finding_reason)
]


def _wire_model(context: dict[str, Any], *, probe: bool) -> type[BaseModel]:
    claims, parts = _context(context, probe=probe)
    locations = prose_locations(context)
    identity = digest(
        [REVISION, probe, [r["claim_id"] for r in claims], [r["part_id"] for r in parts], locations]
    )[7:23]
    claim_fields: dict[str, Any] = {
        f"row_{i}": (
            _SupportJudgment if probe else _ClaimJudgment,
            Field(alias=row["claim_id"]),
        )
        for i, row in enumerate(claims)
    }
    claim_rows = create_model("KeyedClaims_" + identity, __base__=_Closed, **claim_fields)
    prose_fields: dict[str, Any] = {
        key: (
            tuple[_ProseReason, ...],
            Field(description=location["description"]),
        )
        for key, location in locations.items()
    }
    prose_model = create_model("KeyedProse_" + identity, __base__=_Closed, **prose_fields)
    fields: dict[str, Any] = {
        "prose_findings": (prose_model, ...),
        "revision": (_Revision, ...),
        "checks" if probe else "claim_reviews": (claim_rows, ...),
    }
    if not probe:
        part_fields: dict[str, Any] = {
            f"row_{i}": (_PartJudgment, Field(alias=row["part_id"])) for i, row in enumerate(parts)
        }
        part_rows = create_model("KeyedParts_" + identity, __base__=_Closed, **part_fields)
        fields.update(
            coverage_checks=(part_rows, ...),
            priority_review=(Literal["respected", "violated", "uncertain"], ...),
        )
    return create_model("KeyedChecks_" + identity, __base__=_ProseChecks, **fields)


def schemas(context: dict[str, Any], *, probe: bool = False) -> dict[str, Any]:
    """Generate required current keys and the actual SDK-transformed schema."""
    from src.workspace import assistance_consistency_checks as consistency
    if consistency.enabled(context):
        return consistency.schemas(context, probe=probe)

    model = _wire_model(context, probe=probe)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def normalize(
    raw: dict[str, Any], context: dict[str, Any], *, probe: bool = False
) -> dict[str, Any]:
    """Validate exact keys, then attach only server-supplied identities/digests."""
    from src.workspace import assistance_consistency_checks as consistency
    if consistency.enabled(context):
        return consistency.normalize(raw, context, probe=probe)

    claims, parts = _context(context, probe=probe)
    _bounded(raw, _limits()["compact_checker_utf8_bytes"], "capacity_compact_checks_bytes_exceeded")
    value = (
        _wire_model(context, probe=probe).model_validate(raw).model_dump(mode="json", by_alias=True)
    )
    rows = value["checks" if probe else "claim_reviews"]
    result: dict[str, Any] = {
        "checks": [
            {**binding, **{key: rows[binding["claim_id"]][key] for key in ("decision", "reason")}}
            for binding in claims
        ],
        "prose_review": value["prose_review"],
        "prose_findings": [
            {"field": location["field"], "index": location["index"], "reason": reason}
            for key, location in prose_locations(context).items()
            for reason in value["prose_findings"][key]
        ],
    }
    if not probe:
        result.update(
            claim_quality=[
                {
                    **binding,
                    **{
                        key: rows[binding["claim_id"]][key]
                        for key in ("atomicity", "qualifications", "reason")
                    },
                }
                for binding in claims
            ],
            coverage_checks=[
                {**binding, **value["coverage_checks"][binding["part_id"]]} for binding in parts
            ],
            priority_review=value["priority_review"],
        )
    model = ProbeChecks if probe else CoverageChecks
    return model.model_validate(result).model_dump(mode="json")


def compact(
    normalized: dict[str, Any], context: dict[str, Any], *, probe: bool = False
) -> dict[str, Any]:
    """Exact fixture inverse; refuse mismatched bindings, ordering or reasons."""
    from src.workspace import assistance_consistency_checks as consistency
    if consistency.enabled(context):
        return consistency.compact(normalized, context, probe=probe)

    _context(context, probe=probe)
    model = ProbeChecks if probe else CoverageChecks
    value = model.model_validate(normalized).model_dump(mode="json")
    claims = {}
    for i, support in enumerate(value["checks"]):
        row = {key: support[key] for key in ("decision", "reason")}
        if not probe:
            quality = value["claim_quality"][i]
            if any(support[key] != quality[key] for key in ("claim_id", "input_digest", "reason")):
                raise ValueError("keyed_compact_conflicting_claim_review")
            row.update({key: quality[key] for key in ("atomicity", "qualifications")})
        claims[support["claim_id"]] = row
    locations = prose_locations(context)
    reverse = {(value["field"], value["index"]): key for key, value in locations.items()}
    findings: dict[str, list[str]] = {key: [] for key in locations}
    for finding in value["prose_findings"]:
        key = reverse.get((finding["field"], finding["index"]))
        if key is None:
            raise ValueError("checker_prose_location_mismatch")
        findings[key].append(finding["reason"])
    raw = {
        "revision": REVISION,
        "checks" if probe else "claim_reviews": claims,
        "prose_review": value["prose_review"],
        "prose_findings": findings,
    }
    if not probe:
        raw.update(
            coverage_checks={
                row["part_id"]: {key: row[key] for key in ("decision", "reason")}
                for row in value["coverage_checks"]
            },
            priority_review=value["priority_review"],
        )
    if normalize(raw, context, probe=probe) != value:
        raise ValueError("keyed_compact_binding_or_order_mismatch")
    return raw
