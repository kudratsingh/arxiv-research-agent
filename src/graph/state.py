"""Shared state schema for the research agent workflow."""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class PaperMetadata(TypedDict):
    """Metadata for a retrieved arXiv paper."""

    id: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: str


class PaperAnalysis(TypedDict):
    """Structured analysis extracted from a paper."""

    paper_id: str
    title: str
    key_findings: list[str]
    methodology: str
    results_summary: str
    limitations: str
    relevance: float


class Citation(TypedDict):
    """A citation reference used in the synthesized report."""

    paper_id: str
    title: str
    authors: list[str]
    year: str
    url: str


class ResearchState(TypedDict):
    """Full state passed through the LangGraph workflow.

    Each agent reads from this state and returns a partial update.
    The `messages` field uses LangGraph's add_messages reducer to
    append rather than overwrite.

    `run_id` is a per-run identifier propagated through structured
    logs and cost tracking so a downstream analyzer can group every
    event by the workflow invocation that produced it.

    Supervisor fields (`next_action`, `loop_iterations`, `stop_reason`)
    are populated when the supervisor loop is enabled
    (`settings.enable_supervisor`). They stay at their defaults under
    the fixed pipeline.
    """

    run_id: str
    query: str
    sub_questions: list[str]
    search_queries: list[str]
    papers: list[PaperMetadata]
    paper_analyses: list[PaperAnalysis]
    draft_report: str
    citations: list[Citation]
    critique: str
    quality_score: float
    revision_needed: bool
    revision_target: str  # "planner" | "search" | "synthesizer"
    iteration: int
    # Supervisor loop fields (unused under the fixed pipeline).
    next_action: str
    loop_iterations: int
    stop_reason: str
    messages: Annotated[list, add_messages]
