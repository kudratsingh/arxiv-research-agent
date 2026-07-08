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


class EvidenceClaim(TypedDict):
    """A single factual claim traced to its source chunk (ADR 0016).

    Emitted by the reader when `settings.enable_evidence_store` is on.
    Feeds the verifier — which judges the claim against `source_text`
    (a real ranked chunk, not the abstract) — and, in a follow-up PR,
    the synthesizer, which will write from claims rather than free-
    form paper analyses.

    Fields:
      - `claim`: the factual assertion the reader extracted (paraphrase OK).
      - `paper_id`: matches `PaperMetadata.id`.
      - `section`: source section from the chunker (e.g. "results").
      - `source_text`: the ranked chunk verbatim; what the verifier judges.
      - `relevance_score`: cosine similarity from the chunk ranker.
      - `supports_question`: the sub-question this claim answers, or
        the empty string if the reader couldn't attribute it.
    """

    claim: str
    paper_id: str
    section: str
    source_text: str
    relevance_score: float
    supports_question: str


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

    Verifier fields (`verified`, `unsupported_claims`, `missing_evidence`,
    `verifier_recommendation`) are populated only when
    `settings.enable_verifier` is on AND the supervisor picks `verify`.
    See ADR 0015.

    Evidence store field (`evidence`) is populated only when
    `settings.enable_evidence_store` is on. Under the fixed pipeline
    or with the flag off it stays empty. See ADR 0016.
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
    # Verifier fields (unused under the fixed pipeline or with verifier off).
    verified: bool
    unsupported_claims: list[str]
    missing_evidence: list[str]
    verifier_recommendation: str  # "read_more" | "search_more" | "revise_report" | ""
    # Evidence store (populated only when enable_evidence_store is on).
    evidence: list[EvidenceClaim]
    messages: Annotated[list, add_messages]
