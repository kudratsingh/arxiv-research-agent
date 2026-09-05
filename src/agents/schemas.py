"""The JSON each structured agent already asks for, written down (ADR 0076).

Four agents — planner, critic, supervisor, verifier — end their system
prompt with a literal JSON object and then validate what comes back by
hand: `_coerce_str_list`, `_safe_float`, `parsed.get("verified") is
True`, a membership test against a frozenset. Those hand checks are
what makes a malformed judge recoverable rather than fatal (ADR 0041)
and **none of them is being removed**. The models here are a *second*
description of the same shape, for the one thing hand checks cannot do:
tell the provider what to generate.

With `enable_structured_outputs` on and a model whose row allows it,
`call_llm_json` sends the schema as `output_config.format` and the API
constrains generation to satisfy it, which removes the failure mode
those hand checks exist to survive rather than the checks themselves.
With the flag off — the default — nothing here is reachable from a
request and the free-text parse runs exactly as before.

Two rules govern every model below, and both come from the prompts
being instruments (ADR 0070, and the CAP-01 work order's "prompts are
instruments"):

1. **The shape is transcribed from the prompt, never designed.** Every
   field name, every type, and every enum member is what the agent's
   `SYSTEM_PROMPT` already asks for. `tests/test_agent_schemas.py`
   checks the transcription against the prompt text itself, so a prompt
   edit that drifts from a schema fails there rather than in
   production.
2. **Nothing is optional and nothing has a default.** A default would
   let a violation arrive as a plausible-looking value; here it raises,
   the gateway turns it into `upstream_model_output` (ADR 0064), and
   the agent's existing `except` path degrades exactly as it does for
   unparseable JSON today.

One shape is deliberately *not* tightened. The supervisor's
`next_action` is a plain `str`, not an enum, because the enum in its
prompt is built at call time from `_available_actions()` — `verify` and
`refine_query` appear only when their flags are on. A static enum here
would either offer the model an action the deployment has disabled or
forbid one it has enabled, and `supervisor.py`'s own membership test
against `_available_actions()` remains the authority either way.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _hide_docstring_from_the_model(schema: dict[str, Any]) -> None:
    """Drop the class docstring from the generated JSON schema.

    Pydantic puts `__doc__` in the schema as `description`, and this
    schema is *sent to the model* as `output_config.format`. The
    docstrings in this module talk about `planner_agent`'s fallback and
    ADR numbers — notes for a reader of this file, not instructions for
    a model, and shipping them would quietly add prompt text under a
    work order whose whole discipline is that prompt wording does not
    move (ADR 0070).

    Field-level `description=` text stays, deliberately: those are
    transcriptions of what the agent's own prompt already says each
    field means, and they are the part that helps generation land on
    the right shape.
    """
    schema.pop("description", None)


class _AgentOutput(BaseModel):
    """Base for every agent response schema.

    `extra="forbid"` renders as `additionalProperties: false`, which is
    what the structured-output transform wants and what makes the
    schema a statement about the *whole* object rather than a floor
    under it.
    """

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=_hide_docstring_from_the_model
    )


class PlannerOutput(_AgentOutput):
    """`{"sub_questions": [...], "search_queries": [...]}`.

    Both lists stay unbounded here even though the prompt asks for 2-4
    sub-questions and 1-2 queries each: a count is guidance the planner
    should follow, not a wire contract, and `planner_agent` already
    handles a short list by falling back to the raw query.
    """

    sub_questions: list[str] = Field(
        description="Focused sub-questions covering the research question."
    )
    search_queries: list[str] = Field(
        description="Keyword-phrase arXiv search queries for those sub-questions."
    )


class CriticScores(_AgentOutput):
    """The five dimensions the critic's prompt scores, each 0.0-1.0."""

    completeness: float = Field(description="Coverage of the research question.")
    accuracy: float = Field(description="Whether claims are supported by cited papers.")
    coherence: float = Field(description="Structure and logical organisation.")
    depth: float = Field(description="Insight beyond surface-level summary.")
    balance: float = Field(description="Fair representation of differing approaches.")


class CriticOutput(_AgentOutput):
    """The critic's judgment, exactly as its prompt spells it.

    `scores` is carried even though `critic_agent` reads only
    `average_score`: the prompt asks for the five dimensions, and a
    schema that dropped them would change what the model is asked to
    produce — which is a prompt change wearing a schema's clothes.
    """

    scores: CriticScores
    average_score: float = Field(description="Mean of the five dimension scores.")
    critique: str = Field(description="Specific, actionable feedback.")
    revision_needed: bool = Field(description="Whether another revision round is due.")
    revision_target: Literal["planner", "search", "synthesizer", "none"] = Field(
        description="Which node to route back to, or 'none' to approve."
    )


class SupervisorOutput(_AgentOutput):
    """The supervisor's routing decision.

    See the module docstring for why `next_action` is a `str` rather
    than the enum the prompt renders.
    """

    next_action: str = Field(description="The single action to take next.")
    reason: str = Field(description="One-sentence justification.")
    stop_reason: str = Field(
        description=(
            "Why the run stopped; empty string when next_action is not 'stop'."
        )
    )


class VerifierOutput(_AgentOutput):
    """The runtime faithfulness verdict.

    `recommended_action` keeps the empty string as a member because the
    verifier's prompt says to leave it empty when `verified` is true,
    and `VALID_RECOMMENDATIONS` in `src/agents/verifier.py` includes
    `""` for the same reason.
    """

    verified: bool = Field(description="Whether every cited claim is supported.")
    unsupported_claims: list[str] = Field(
        description="Claim texts the sources do not support."
    )
    missing_evidence: list[str] = Field(
        description="Topics or sub-questions with no cited source."
    )
    recommended_action: Literal["read_more", "search_more", "revise_report", ""] = (
        Field(description="Recovery action for the supervisor, empty when verified.")
    )
    reason: str = Field(description="One-sentence overall diagnosis.")
