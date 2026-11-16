"""Versioned checker with structural finding categories and derived aggregates.

Coverage critiques belong to the exact part review. Unsupported factual prose
and uncertainty use separate exact-location lists. The model supplies no global
prose-clear flag. Required empty lists are explicit judgments; missing lists
are rejected. Nothing here grants factual or human qualification.
"""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from typing import Any, Literal, Self

from anthropic import transform_schema
from pydantic import BaseModel, Field, create_model, model_validator

from src.workspace import assistance_keyed_checks as previous
from src.workspace.assistance_capacity_contract import (
    QualityReview,
    SupportReview,
    _bounded,
    _Closed,
    _limits,
    _Reason,
    _validate_locations,
)
from src.workspace.assistance_contract import digest

REVISION = "workspace-assistance-consistency-checks-v18"
NORMALIZATION_REVISION = "workspace-assistance-consistency-normalization-v18"


def enabled(context: dict[str, Any]) -> bool:
    return context.get("checker_normalization_revision") == NORMALIZATION_REVISION


class PartReview(_Reason):
    part_id: str
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")
    decision: Literal["answered", "partial", "lacks_evidence", "omitted", "uncertain"]


class CoverageCritique(_Reason):
    part_id: str
    input_digest: str = Field(strict=True, pattern=r"^sha256:[a-f0-9]{64}$")


class Checks(_Closed):
    checks: tuple[SupportReview, ...] = Field(max_length=12)
    claim_quality: tuple[QualityReview, ...] = Field(max_length=12)
    coverage_checks: tuple[PartReview, ...] = Field(max_length=8)
    prose_review: Literal["procedural_only", "unscored_factual_content", "abstain"]
    prose_findings: tuple[previous.ProseFinding, ...]
    prose_uncertainties: tuple[previous.ProseFinding, ...]
    coverage_critiques: tuple[CoverageCritique, ...]
    priority_review: Literal["respected", "violated", "uncertain"]

    @model_validator(mode="after")
    def complete(self) -> Self:
        for rows, key in [
            (self.checks, "claim_id"),
            (self.claim_quality, "claim_id"),
            (self.coverage_checks, "part_id"),
        ]:
            if len({getattr(r, key) for r in rows}) != len(rows):
                raise ValueError("duplicate_checker_identity")
        if {r.claim_id: r.input_digest for r in self.checks} != {
            r.claim_id: r.input_digest for r in self.claim_quality
        }:
            raise ValueError("claim_quality_binding_mismatch")
        expected = (
            "unscored_factual_content"
            if self.prose_findings
            else "abstain"
            if self.prose_uncertainties
            else "procedural_only"
        )
        if self.prose_review != expected:
            raise ValueError("derived_prose_state_mismatch")
        parts = {p.part_id: p.input_digest for p in self.coverage_checks}
        if any(parts.get(c.part_id) != c.input_digest for c in self.coverage_critiques):
            raise ValueError("coverage_critique_binding_mismatch")
        for rows, keys in [
            (self.prose_findings, ("field", "index", "reason")),
            (self.prose_uncertainties, ("field", "index", "reason")),
            (self.coverage_critiques, ("part_id", "input_digest", "reason")),
        ]:
            if len({tuple(getattr(r, k) for k in keys) for r in rows}) != len(rows):
                raise ValueError("duplicate_checker_finding")
        _bounded(
            self.model_dump(mode="json"),
            _limits()["normalized_checker_utf8_bytes"],
            "capacity_normalized_checks_bytes_exceeded",
        )
        return self

    def validate_locations(self, prose: dict[str, Any]) -> None:
        _validate_locations(self.prose_findings, prose)
        _validate_locations(self.prose_uncertainties, prose)


def checks_model() -> type[Checks]:
    return Checks


def _model(context: dict[str, Any]) -> type[BaseModel]:
    claims, parts = previous._context(context, probe=False)
    locations = previous.prose_locations(context)
    return _bound_model(json.dumps([claims, parts, locations], sort_keys=True))


@lru_cache(maxsize=128)
def _bound_model(encoded: str) -> type[BaseModel]:
    # A complete immutable binding key, never a cached judgment or provider result.
    claims, parts, locations = json.loads(encoded)
    identity = digest([REVISION, claims, parts, locations])[7:23]
    prose_fields: dict[str, Any] = {
        key: (
            tuple[previous._ProseReason, ...],
            Field(
                description=f"Exact {r['field']}"
                + (f"[{r['index']}]" if r["index"] is not None else "")
                + ". Empty list explicitly means no finding at this location."
            ),
        )
        for key, r in locations.items()
    }
    prose = create_model(
        "ConsistencyLocations_" + identity,
        __base__=_Closed,
        **prose_fields,
    )
    claim_fields: dict[str, Any] = {
        "r" + str(i): (previous._ClaimJudgment, Field(alias=r["claim_id"]))
        for i, r in enumerate(claims)
    }
    claim_rows = create_model("ConsistencyClaims_" + identity, __base__=_Closed, **claim_fields)
    part = create_model(
        "ConsistencyPartJudgment_" + identity,
        __base__=_Reason,
        decision=(
            Literal["answered", "partial", "lacks_evidence", "omitted", "uncertain"],
            Field(
                description="answered: complete; partial: useful answers plus remaining gaps; lacks_evidence: no answer available; omitted: available but unanswered. Judge independently of declared coverage."
            ),
        ),
        critiques=(
            tuple[previous._ProseReason, ...],
            Field(
                description="Missing/partial request details or generic evidence-gap criticism. These block coverage acceptance but are not unsupported factual-prose assertions. Preserve all independent critiques."
            ),
        ),
    )
    part_fields: dict[str, Any] = {
        "r" + str(i): (part, Field(alias=r["part_id"])) for i, r in enumerate(parts)
    }
    part_rows = create_model("ConsistencyParts_" + identity, __base__=_Closed, **part_fields)
    from src.workspace.assistance_keyed_contract import _fixed

    return create_model(
        "ConsistencyChecks_" + identity,
        __base__=_Closed,
        revision=(_fixed(REVISION), ...),
        claim_reviews=(claim_rows, ...),
        coverage_checks=(part_rows, ...),
        prose_findings=(
            prose,
            Field(
                description="Only substantive factual assertions outside the scored claims. Coverage/detail criticism belongs in the relevant coverage_checks.critiques."
            ),
        ),
        prose_uncertainties=(
            prose,
            Field(
                description="Exact locations whose factual-premise status cannot be decided. Do not invent a clear judgment; uncertainty blocks acceptance."
            ),
        ),
        priority_review=(Literal["respected", "violated", "uncertain"], ...),
    )


def schemas(context: dict[str, Any], *, probe: bool = False) -> dict[str, Any]:
    if probe:
        raise ValueError("consistency_workflow_checker_not_probe")
    model = _model(context)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def normalize(
    raw: dict[str, Any], context: dict[str, Any], *, probe: bool = False
) -> dict[str, Any]:
    if probe:
        raise ValueError("consistency_workflow_checker_not_probe")
    claims, parts = previous._context(context, probe=False)
    _bounded(raw, _limits()["compact_checker_utf8_bytes"], "capacity_compact_checks_bytes_exceeded")
    value = _model(context).model_validate(raw).model_dump(mode="json", by_alias=True)
    locations = previous.prose_locations(context)

    def findings(key: str) -> list[dict[str, Any]]:
        return [
            {"field": r["field"], "index": r["index"], "reason": reason}
            for name, r in locations.items()
            for reason in value[key][name]
        ]

    factual = findings("prose_findings")
    uncertain = findings("prose_uncertainties")
    result = {
        "checks": [
            {**b, **{k: value["claim_reviews"][b["claim_id"]][k] for k in ("decision", "reason")}}
            for b in claims
        ],
        "claim_quality": [
            {
                **b,
                **{
                    k: value["claim_reviews"][b["claim_id"]][k]
                    for k in ("atomicity", "qualifications", "reason")
                },
            }
            for b in claims
        ],
        "coverage_checks": [
            {**b, **{k: value["coverage_checks"][b["part_id"]][k] for k in ("decision", "reason")}}
            for b in parts
        ],
        "coverage_critiques": [
            {**b, "reason": reason}
            for b in parts
            for reason in value["coverage_checks"][b["part_id"]]["critiques"]
        ],
        "prose_findings": factual,
        "prose_uncertainties": uncertain,
        "prose_review": "unscored_factual_content"
        if factual
        else "abstain"
        if uncertain
        else "procedural_only",
        "priority_review": value["priority_review"],
    }
    checks = Checks.model_validate(result)
    checks.validate_locations(context.get("unscored_prose", {}))
    return checks.model_dump(mode="json")


def compact(
    normalized: dict[str, Any], context: dict[str, Any], *, probe: bool = False
) -> dict[str, Any]:
    if probe:
        raise ValueError("consistency_workflow_checker_not_probe")
    value = Checks.model_validate(normalized).model_dump(mode="json")
    locations = previous.prose_locations(context)
    lookup = {(r["field"], r["index"]): key for key, r in locations.items()}

    def findings(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {key: [] for key in locations}
        for row in rows:
            key = lookup.get((row["field"], row["index"]))
            if key is None:
                raise ValueError("checker_prose_location_mismatch")
            out[key].append(row["reason"])
        return out

    rows = {}
    for support, quality in zip(value["checks"], value["claim_quality"], strict=True):
        if any(support[k] != quality[k] for k in ("claim_id", "input_digest", "reason")):
            raise ValueError("keyed_compact_conflicting_claim_review")
        rows[support["claim_id"]] = {k: support[k] for k in ("decision", "reason")} | {
            k: quality[k] for k in ("atomicity", "qualifications")
        }
    parts = {
        r["part_id"]: {k: r[k] for k in ("decision", "reason")}
        | {
            "critiques": [
                c["reason"] for c in value["coverage_critiques"] if c["part_id"] == r["part_id"]
            ]
        }
        for r in value["coverage_checks"]
    }
    raw = {
        "revision": REVISION,
        "claim_reviews": rows,
        "coverage_checks": parts,
        "prose_findings": findings(value["prose_findings"]),
        "prose_uncertainties": findings(value["prose_uncertainties"]),
        "priority_review": value["priority_review"],
    }
    if normalize(raw, context) != value:
        raise ValueError("consistency_compact_binding_or_order_mismatch")
    return raw


def aggregate(checks: Checks, context: dict[str, Any]) -> dict[str, Any]:
    """Reduce complete supplied judgments; missing/empty denominators stay absent."""
    from src.workspace.assistance_coverage import validate_review

    validate_review(checks, context)
    checks.validate_locations(context.get("unscored_prose", {}))
    declared = {r["id"]: r["status"] for r in context["declared_coverage"]}
    counts = Counter(r.decision for r in checks.coverage_checks)
    disagreements = [r.part_id for r in checks.coverage_checks if r.decision != declared[r.part_id]]
    negative_quality = any(
        r.atomicity == "bundled" or "lost" in r.qualifications.model_dump().values()
        for r in checks.claim_quality
    )
    uncertain_quality = any(
        r.atomicity == "uncertain" or "uncertain" in r.qualifications.model_dump().values()
        for r in checks.claim_quality
    )
    negative_coverage = any(
        r.decision != "uncertain" and r.part_id in disagreements for r in checks.coverage_checks
    ) or bool(checks.coverage_critiques)
    coverage_clear = (
        not disagreements and not checks.coverage_critiques and counts["uncertain"] == 0
    )
    complete = coverage_clear and counts["answered"] == len(checks.coverage_checks)
    negative = (
        negative_quality
        or negative_coverage
        or any(c.decision.value == "unsupported" for c in checks.checks)
        or checks.priority_review == "violated"
        or bool(checks.prose_findings)
    )
    uncertain = (
        uncertain_quality
        or counts["uncertain"] > 0
        or any(c.decision.value == "abstain" for c in checks.checks)
        or checks.priority_review == "uncertain"
        or bool(checks.prose_uncertainties)
    )
    gate = "FAIL" if negative else "HOLD" if uncertain else "PASS"
    return {
        "fully_answered_parts": counts["answered"],
        "partial_parts": counts["partial"],
        "insufficient_evidence_parts": counts["lacks_evidence"],
        "omitted_parts": counts["omitted"],
        "uncertain_parts": counts["uncertain"],
        "coverage_disagreements": disagreements,
        "coverage_critique_count": len(checks.coverage_critiques),
        "factual_prose_findings": len(checks.prose_findings),
        "uncertain_prose_findings": len(checks.prose_uncertainties),
        "prose_review": checks.prose_review,
        "coverage_complete": complete,
        "full_answer_credit": bool(complete and gate == "PASS"),
        "quality_gate": gate,
        "scientific_quality": "UNMEASURED",
        "basis": "Derived from complete supplied machine judgments, not human qualification or independent factual evidence.",
    }
