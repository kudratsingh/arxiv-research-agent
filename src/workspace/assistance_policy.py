"""Task-bound response revision. Pure construction/validation; no provider or approval."""

from __future__ import annotations

import json
from functools import reduce
from operator import or_
from typing import Any, Literal

from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, Field, create_model

TASK_REVISION = "workspace-assistance-task-bound-v7"
TaskIntent = Literal["answer", "comparison", "application_assessment"]
CONTEXT_REQUESTS = {
    "vehicle_configuration": "Provide the vehicle and configuration to be assessed.",
    "operating_envelope": "Provide the operating envelope and intended conditions.",
    "safety_objectives": "Provide the safety objectives and acceptance criteria.",
    "validation_evidence": "Provide the relevant validation evidence and its limits.",
}


class ApplicationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    vehicle_configuration: str = Field(default="", max_length=1000)
    operating_envelope: str = Field(default="", max_length=1000)
    safety_objectives: str = Field(default="", max_length=1000)
    validation_evidence: str = Field(default="", max_length=1000)


class TaskContext(BaseModel):
    """Application/user input, sealed before generation; never model output."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    intent: TaskIntent = "answer"
    application_context: ApplicationContext = Field(default_factory=ApplicationContext)


def seal_task_policy(context: TaskContext, mode: str, source_count: int) -> dict[str, Any]:
    if mode not in {"learn", "research"} or type(source_count) is not int or source_count < 1:
        raise ValueError("task_policy_context_required")
    if mode != "research" and context.intent != "answer":
        raise ValueError("research_task_intent_required")
    values = {k: v.strip() for k, v in context.application_context.model_dump().items()}
    if context.intent != "application_assessment" and any(values.values()):
        raise ValueError("application_context_requires_assessment_intent")
    required = list(CONTEXT_REQUESTS) if context.intent == "application_assessment" else []
    missing = [k for k in required if not values[k]]
    allowed = ["full_abstention"]
    if not missing:
        if context.intent != "comparison" or source_count >= 2:
            allowed.append("answer")
        if context.intent == "comparison":
            allowed.append("comparison_abstention")
    return {
        "revision": TASK_REVISION,
        "task_intent": context.intent,
        "mode": mode,
        "selected_work_count": source_count,
        "application_context": values,
        "required_context": required,
        "missing_context": missing,
        "allowed_dispositions": allowed,
        "context_basis": "Explicitly supplied context, not verified source evidence",
    }


def validate_task_policy(policy: dict[str, Any]) -> None:
    context = TaskContext.model_validate(
        {
            "intent": policy.get("task_intent"),
            "application_context": policy.get("application_context"),
        }
    )
    if policy != seal_task_policy(
        context, policy.get("mode", ""), policy.get("selected_work_count", 0)
    ):
        raise ValueError("sealed_task_policy_changed")


def task_response_model(
    handles: list[str], purpose: str, policy: dict[str, Any]
) -> type[BaseModel]:
    from src.workspace.assistance_contract import PROCEDURAL_REVISION, response_model

    validate_task_policy(policy)
    # The existing per-request evidence-handle enum and semantic limits stay authoritative.
    original = response_model(handles, purpose=purpose, revision=PROCEDURAL_REVISION)  # type: ignore[arg-type]
    from src.workspace.assistance_contract import digest

    identity = digest([handles, purpose, policy])[7:23]
    full_fields: dict[str, Any] = {
        "disposition": (Literal["full_abstention"], ...),
        "reason": (
            Literal["application_context_required"]
            if policy["missing_context"]
            else Literal["insufficient_selected_evidence"],
            ...,
        ),
        "next_action": (Literal["request_context"], ...),
    }
    if policy["missing_context"]:
        request_fields: dict[str, Any] = {
            k: (Literal["required"], ...) for k in policy["missing_context"]
        }
        requests = create_model(
            "RequiredContext_" + identity,
            __config__=ConfigDict(extra="forbid", frozen=True),
            **request_fields,
        )
        full_fields["context_requests"] = (requests, ...)
    full = create_model(
        "FullAbstention_" + identity,
        __config__=ConfigDict(extra="forbid", frozen=True),
        __doc__="Full abstention has no claims, claim references, comparison or free factual prose.",
        **full_fields,
    )
    branches: list[type[BaseModel]] = [full]
    claims_annotation = original.model_fields["claims"].annotation
    if "answer" in policy["allowed_dispositions"]:
        branches.append(
            create_model(
                "TaskAnswer_" + identity,
                __base__=original,
                disposition=(Literal["answer"], ...),
                abstention=(type(None), ...),
                claims=(claims_annotation, Field(min_length=1, max_length=6)),
            )
        )
    if "comparison_abstention" in policy["allowed_dispositions"]:
        # Single-paper shape excludes comparison conclusions/bases while retaining checked notes.
        notes = response_model(handles, purpose="single_paper", revision=PROCEDURAL_REVISION)
        branches.append(
            create_model(
                "ComparisonNotes_" + identity,
                __base__=notes,
                disposition=(Literal["comparison_abstention"], ...),
                abstention=(Literal["comparison_evidence_required"], ...),
                claims=(notes.model_fields["claims"].annotation, Field(min_length=1, max_length=6)),
            )
        )
    return create_model(
        "TaskResponse_" + identity,
        __config__=ConfigDict(extra="forbid", frozen=True),
        response=(
            reduce(or_, branches),
            Field(
                description="Only the sealed task's allowed disposition; entire JSON <=8000 UTF-8 bytes."
            ),
        ),
    )


def task_schemas(handles: list[str], purpose: str, policy: dict[str, Any]) -> dict[str, Any]:
    model = task_response_model(handles, purpose, policy)
    return {"local": model.model_json_schema(), "wire": transform_schema(model)}


def normalize_task_output(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    """Validate before normalizing for existing claim/prose/checker paths."""
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 8000:
        raise ValueError("assistance_response_too_large")
    parsed = task_response_model(handles, purpose, policy).model_validate(payload)
    value: dict[str, Any] = parsed.model_dump(mode="json")["response"]
    disposition = value.pop("disposition")
    if disposition == "full_abstention":
        normalized: dict[str, Any] = {
            "claims": [],
            "background_claims": [],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [{"intent": "application_scope", "claim_ids": []}],
            "proposal": "request_context",
            "abstention": value["reason"],
        }
    else:
        normalized = value
    if purpose == "research_comparison":
        normalized.setdefault("comparison_claims", [])
        normalized.setdefault("comparison_basis", [])
    if (
        disposition == "answer"
        and policy["task_intent"] == "comparison"
        and not normalized.get("comparison_claims")
    ):
        raise ValueError("comparison_answer_requires_scored_comparison")
    return normalized


def render_task_output(
    payload: dict[str, Any], handles: list[str], purpose: str, policy: dict[str, Any]
) -> dict[str, Any]:
    from src.workspace.assistance_contract import render_gaps, render_procedures

    normalized = normalize_task_output(payload, handles, purpose, policy)
    rendered = render_procedures(normalized)
    requests = [CONTEXT_REQUESTS[k] for k in policy["missing_context"]]
    if requests:
        rendered["proposal"] = " ".join(requests)
    return {
        **normalized,
        **rendered,
        "gaps": render_gaps(normalized["gaps"]),
        "response_disposition": payload["response"]["disposition"],
        "context_requests": requests,
        "comparison_unanswered": payload["response"]["disposition"] == "comparison_abstention",
    }
