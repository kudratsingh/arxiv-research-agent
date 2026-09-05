"""Shared state schema for the research agent workflow."""

from typing import Annotated, Any, Literal, TypedDict

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


class VerifyRepairState(TypedDict, total=False):
    """CAP-02's policy keys — optional on purpose (ADR 0076).

    `total=False` is the whole point of this block existing separately.
    `ResearchState` is otherwise total, and three initial-state
    constructors build it as a literal: `initial_research_state` below,
    `src/api/runner.py::_initial_state`, and `src/eval/runner.py::
    _initial_state`. The eval runner's copy is fenced to another work
    order, and `src/eval/simulate_research.py` builds the scripted
    research tier's state from the canonical constructor — so a *total*
    key added here would either fail `mypy --strict` on a file this lane
    must not touch, or move the scripted tier's committed baseline,
    which this lane must not regenerate.

    Optional keys avoid both. Every consumer reads them through `.get()`
    with a default, which is the same discipline the supervisor and
    verifier fields already rely on in practice, and the constructors
    stay byte-identical to each other — the drift guard in
    `tests/test_cli_run_recovery.py` keeps its full strength rather than
    being loosened to accommodate a key one of the three cannot set.

    The keys are written by the `verify` and `repair` nodes of the
    `fixed_verify_repair` policy and by nothing else; under `legacy`
    they never appear on the state at all, which is what makes their
    presence in a checkpoint or an SSE frame a positive signal that arm
    C ran.

    Fields:
      - `verification_verdict`: `pass` when every cited claim resolved,
        `fail` when the judge reported a problem, `abstain` when it
        could not judge (empty draft, no citations, upstream error or
        unusable output). Never coerced between the three.
      - `verification_reason`: stable snake_case code for the verdict.
        Reused from `src/errors.py`'s vocabulary where one fits —
        `upstream_model`, `upstream_model_output` — and documented in
        ADR 0076 otherwise.
      - `repair_count`: repairs attempted, capped at 1 per run.
      - `repair_action`: the repair the run selected, from
        `src/policies/repair.py::REPAIR_ACTIONS`.
    """

    verification_verdict: Literal["pass", "fail", "abstain", ""]
    verification_reason: str
    repair_count: int
    repair_action: str


class ResearchState(VerifyRepairState):
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

    Query refiner field (`tried_search_queries`) is populated only
    when `settings.enable_query_refiner` is on AND the supervisor
    picks `refine_query`. Under the fixed pipeline it stays empty.
    See ADR 0018.

    Reader-recovery fields (`reader_analysis_complete`,
    `reader_missing_context`, `reader_requested_sections`) are
    populated only when `settings.enable_reader_recovery` is on.
    Under the fixed pipeline or with the flag off,
    `reader_analysis_complete` stays at its default (`True`) so any
    default-consuming code sees "nothing to recover from". See ADR
    0019.

    Verify-and-repair fields are inherited from `VerifyRepairState`
    above and are the one **optional** block in this schema: they are
    written only under `settings.research_policy="fixed_verify_repair"`
    and are absent from the state entirely otherwise. See ADR 0076.
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
    # Query refiner history — flat list of every search query the
    # supervisor loop has ever run for this workflow, used by the
    # refiner to dedupe against already-tried queries.
    tried_search_queries: list[str]
    # Reader-recovery signals (populated only when the flag is on).
    # `analysis_complete` defaults to True so consumers reading the
    # field on a fresh state don't spuriously trigger a re-read.
    reader_analysis_complete: bool
    reader_missing_context: str
    reader_requested_sections: list[str]
    # Conversation follow-up context (Sprint 5 PR 4, ADR 0032).
    # Populated by the API runner right before the workflow starts
    # when the job runs in a conversation with prior jobs. Blank
    # string outside conversation mode.
    prior_context: str
    messages: Annotated[list[Any], add_messages]


def initial_research_state(
    query: str, run_id: str, *, prior_context: str = ""
) -> ResearchState:
    """Build a complete `ResearchState` for a fresh workflow invocation.

    Lives beside the TypedDict it mirrors so the two are edited
    together (ADR 0052). Three entry points — the CLI, the API runner,
    and the eval runner — each carried their own literal, and the CLI's
    had drifted ten keys behind: `ResearchState` is a *total*
    TypedDict, so a run started from that literal was already invalid
    against its own schema, and only survived because every consumer
    reads through `.get()` with a default. The next field added would
    have been a silent behavioural difference between `make run` and
    the same query submitted to the API.

    Defaults follow the schema's documented contract rather than
    "empty": `reader_analysis_complete` starts True so a consumer
    reading it on a fresh state sees "nothing to recover from"
    (state.py's ADR 0019 note), and every collection starts empty so
    the reducers append rather than merge.

    The `VerifyRepairState` keys are deliberately *not* set here. They
    are optional (ADR 0076) and a fresh run has not been verified, so
    setting `verification_verdict=""` would put a value on the state
    that means the same thing as its absence while making the three
    constructors — one of which this lane does not own — disagree. The
    verify node writes all four the first time it runs.

    Args:
        query: The natural-language research question.
        run_id: Per-run identifier; also the checkpoint `thread_id`.
        prior_context: Retrieved prior-report chunks for a
            conversation follow-up (ADR 0032). Empty outside
            conversation mode.

    Returns:
        A `ResearchState` with every key present.
    """
    return {
        "run_id": run_id,
        "query": query,
        "sub_questions": [],
        "search_queries": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "tried_search_queries": [],
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "prior_context": prior_context,
        "messages": [],
    }
