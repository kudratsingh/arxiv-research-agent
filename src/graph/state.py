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


class WorkerBranch(TypedDict):
    """One orchestrator-worker branch: its scope, its caps, its result.

    CAP-03's unit of parallel work (ADR 0086). A branch is one
    sub-question researched on its own isolated state — its own search,
    its own reader pass, its own evidence table — so that a fault in one
    branch cannot reach another and so a later listwise selector
    (CAP-09) has siblings to compare.

    `branch_id` is the trajectory's `BranchId` (RFC 10 §6.3) and obeys
    that contract's `^branch_[a-z0-9][a-z0-9_-]{0,63}$` shape, so the
    identifier the graph carries and the identifier the trajectory
    records are the same string rather than two conventions that have to
    be joined afterwards.

    The three bulk fields — `papers`, `paper_analyses`, `evidence` — are
    the branch's raw output and are **emptied by the merge node** once
    they have been unioned. Keeping them would double every checkpoint
    the run writes; the counts, the paper ids and
    `merged_evidence_provenance` are what a reader of the finished state
    needs, and the trajectory has already recorded the branch by then.

    Fields:
      - `branch_id`: `branch_w<NN>` for a planned branch, `branch_r<NN>`
        for one a retrieval repair added.
      - `index`: position in the run's branch list; the merge's order.
      - `sub_question`: the one question this branch researches. It is
        also the branch state's `query`, which is what makes retrieval
        diverse rather than N repetitions of one ranking.
      - `search_queries`: the queries this branch is allowed to run.
      - `status`: `planned` until the workers node executes it, then
        `succeeded`, `failed`, `cancelled` or `budget_stopped`.
      - `reason`: a typed code — `src/errors.py`'s vocabulary for a
        failure, `""` while planned or on success.
      - `max_papers`: this branch's hard paper cap, and therefore its
        model-call cap: the reader makes exactly one call per paper.
      - `cost_share_usd`: dollars this branch was allowed to add.
      - `paper_ids`, `analysis_count`, `evidence_count`: what it found.
      - `llm_calls`, `cost_usd`: what it spent, measured off the run's
        one cost accumulator rather than a second ledger.
    """

    branch_id: str
    index: int
    sub_question: str
    search_queries: list[str]
    status: str
    reason: str
    max_papers: int
    cost_share_usd: float
    paper_ids: list[str]
    analysis_count: int
    evidence_count: int
    llm_calls: int
    cost_usd: float
    papers: list[PaperMetadata]
    paper_analyses: list[PaperAnalysis]
    evidence: list[EvidenceClaim]


class EvidenceProvenance(TypedDict):
    """Which branches contributed one paper to the merged evidence.

    The merge deduplicates papers by canonical id (ADR 0041's
    `canonical_paper_key`), so a paper two branches both retrieved
    appears once in `papers` and once here, naming both branches. That
    pairing is the provenance CAP-03 delivers: a claim in the merged
    evidence can be traced to the branch, the sub-question and the paper
    it came from.

    Fields:
      - `paper_id`: the retained paper's id (the first branch's form).
      - `canonical_id`: the dedup key both branches agreed on.
      - `branch_ids`: every branch that found it, in branch order.
      - `sub_questions`: those branches' questions, in the same order.
      - `claim_count`: merged evidence claims that cite this paper.
    """

    paper_id: str
    canonical_id: str
    branch_ids: list[str]
    sub_questions: list[str]
    claim_count: int


class OrchestrationState(TypedDict, total=False):
    """CAP-03's policy keys — optional, for `VerifyRepairState`'s reason.

    `total=False` for exactly the argument that block makes: three
    initial-state constructors build `ResearchState` as a literal and
    one of them belongs to another work order, so a *total* key added
    here would either fail `mypy --strict` on a file this lane must not
    touch or move the scripted research tier's committed baseline.

    Both keys are written only under
    `settings.research_policy="orchestrated_workers"` (or the compute
    controller's T2), and by nothing else. Under every other policy they
    never appear on the state at all, which is what makes their presence
    in a checkpoint a positive signal that the branch tier ran.

    Fields:
      - `worker_branches`: every branch the lead planned, in order,
        carrying its own outcome after the workers node runs.
      - `merged_evidence_provenance`: one entry per deduplicated paper
        in the merged evidence, naming the branches that found it.
    """

    worker_branches: list[WorkerBranch]
    merged_evidence_provenance: list[EvidenceProvenance]


class ResearchState(VerifyRepairState, OrchestrationState):
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

    Orchestration fields are inherited from `OrchestrationState` and are
    optional for the same reason: they are written only under
    `settings.research_policy="orchestrated_workers"` (or the compute
    controller's T2 selection of that shape) and are absent otherwise.
    See ADR 0086.
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
