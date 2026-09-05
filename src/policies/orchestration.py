"""Orchestrator-workers: the branch tier's planning, execution and merge.

`docs/agent-engineering/02-target-architecture.md` §4 gives tier T2 one
job — "diverse search branches or candidate outlines, listwise
selection, verification" — and `01-current-architecture.md` §6 records
that parallel candidate search is *absent*: the reader parallelises
papers within one trajectory, which is a different thing entirely. This
module is the first half of that tier (ADR 0086): N bounded workers,
each researching one sub-question on its own isolated state, and a
deterministic merge that unions their evidence tables with provenance.

The second half — comparing candidate outlines and *selecting* one — is
CAP-09 and is deliberately not here. What this module delivers is
diversified retrieval with provenance, and the branch/candidate lineage
a selector will need (RFC 10 §6.3–§6.4).

## The shape

```text
planner -> lead -> workers -> merge -> synthesizer -> verify -> ...
```

- **lead** turns the plan's sub-questions into at most
  `orchestration_max_branches` branches, in the plan's own order. No
  model call: the planner already decomposed the question, and asking a
  second model to re-decompose it would make the branch set
  non-deterministic for no measured gain.
- **workers** executes each planned branch — search, then reader, on a
  state built by `initial_research_state` and touched by nothing else —
  and records what it found and what it spent.
- **merge** unions the evidence tables, deduplicates papers by
  `canonical_paper_key`, and writes one provenance row per retained
  paper. Also no model call.

## Isolation, and what it is worth

A branch never receives the parent state object and never writes to it.
`branch_input_state` builds a complete fresh `ResearchState` from the
canonical constructor, and the only things that leave a branch are the
three collections `_execute_branch` reads off the agents' returned
updates. That is what makes the failure claim checkable: a branch whose
search raises, whose reader raises, or which is cancelled mid-flight
contributes nothing and *can* contribute nothing to a sibling, because
there is no shared object for a partial write to land in.

Branch messages are dropped on purpose. The graph's message trajectory
is a record of the *nodes* a run visited, and appending five branches'
worth of `search` / `reader` messages would make the transcript disagree
with the node stream that every other shape's e2e test compares it to.

## Branches run one after another

Sequential, on the node's own executor thread (ADR 0047 already bounds
that thread against `api_max_concurrent_jobs`), for two reasons that
both point the same way. Determinism: the merge order has to be a
function of the plan, and a thread pool would make it a function of
scheduling. And cost: the run's ceiling is enforced at the shared
`call_llm` choke point against one accumulator, and N branches racing
each other through that check is exactly the stale-read RFC 10 §8.7
describes. The parallelism T2 asks for is in the *retrieval* — N
different questions against the corpus — not in the wall clock.

## Caps

Three, and each is enforced somewhere it cannot be skipped:

| Cap | Setting | Enforced by |
|---|---|---|
| branches per run | `orchestration_max_branches` | `plan_branches` slices the sub-question list |
| papers per branch | `orchestration_max_papers_per_branch` | the branch's paper list is sliced before the reader, which makes it the branch's *model-call* cap too — the reader makes exactly one call per paper |
| dollars per branch | `orchestration_branch_cost_share` | `bind_effective_cost_cap` at the shared choke point |

The third has a documented reach, stated here rather than left to be
discovered: `bind_effective_cost_cap` binds a `ContextVar`, and
`propagate_run_context` (`src/observability/logging.py`) carries three
ContextVars into the reader's per-paper fan-out threads — the request
context, the cost accumulator and the cancel token — of which the
effective cap is not one. Inside that fan-out the choke point therefore
falls back to `settings.max_cost_usd`, so **the run ceiling always
holds** and a branch can overshoot only its own *share*, by at most the
calls of one bounded fan-out. The branch record carries the spend it
actually made, so the overshoot is visible rather than assumed. Closing
it properly means adding the cap to `propagate_run_context`, which lives
in a fenced module and is recorded as ADR 0086's follow-up.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from langchain_core.messages import AIMessage

from src.agents.reader import reader_agent
from src.agents.search import search_agent
from src.cancellation import JobCancelledError, check_cancelled
from src.config import settings
from src.graph.state import (
    EvidenceClaim,
    EvidenceProvenance,
    PaperAnalysis,
    PaperMetadata,
    ResearchState,
    WorkerBranch,
    initial_research_state,
)
from src.observability.costs import (
    CostBudgetExceeded,
    bind_effective_cost_cap,
    current_costs,
    effective_cost_cap,
    reset_effective_cost_cap,
)
from src.tools.arxiv_search import canonical_paper_key

#: Branch id prefixes. Both obey the trajectory contract's `BranchId`
#: pattern (`^branch_[a-z0-9][a-z0-9_-]{0,63}$`), so the graph's
#: identifier and the trajectory's are one string rather than two.
PLANNED_BRANCH_PREFIX: Final[str] = "branch_w"
REPAIR_BRANCH_PREFIX: Final[str] = "branch_r"

#: What RFC 10 §8.6's `branch.created` calls the axis these branches
#: differ along. One value, because this policy diversifies on exactly
#: one thing; a second axis (date window, citation direction) would be a
#: second value and a second ADR.
DIVERSITY_DIMENSION: Final[str] = "sub_question"

STATUS_PLANNED: Final[str] = "planned"
STATUS_SUCCEEDED: Final[str] = "succeeded"
STATUS_FAILED: Final[str] = "failed"
STATUS_CANCELLED: Final[str] = "cancelled"
STATUS_BUDGET_STOPPED: Final[str] = "budget_stopped"

BRANCH_STATUSES: Final[tuple[str, ...]] = (
    STATUS_PLANNED,
    STATUS_SUCCEEDED,
    STATUS_FAILED,
    STATUS_CANCELLED,
    STATUS_BUDGET_STOPPED,
)
"""Every status a branch record can carry, for callers that enumerate."""

#: Search queries one branch may run. A module constant rather than a
#: setting for ADR 0070's reason: a threshold an operator can move is a
#: threshold no evaluation can attribute a result to. Sized against the
#: planner's own instruction — "1-2 targeted queries" per sub-question —
#: plus the branch's own question, plus one spare.
MAX_QUERIES_PER_BRANCH: Final[int] = 4

#: Reason code for a branch the run's ceiling stopped before it started.
REASON_BUDGET_EXHAUSTED: Final[str] = "cost_budget_exceeded"

#: Reason code when a branch was cancelled with its job.
REASON_CANCELLED: Final[str] = "cancelled"

#: Reason code for a failure that carries no `src/errors.py` code.
REASON_UNEXPECTED: Final[str] = "internal_unexpected"


@dataclass(frozen=True)
class BranchOutcome:
    """What one worker produced. Empty on every failure path.

    Frozen, and deliberately only the three collections: a branch's
    contribution to the run is its evidence and the papers behind it,
    and anything else it happened to compute (messages, recovery
    signals, its own critique) is scoped to the branch and stays there.
    """

    papers: list[PaperMetadata] = field(default_factory=list)
    paper_analyses: list[PaperAnalysis] = field(default_factory=list)
    evidence: list[EvidenceClaim] = field(default_factory=list)


BranchExecutor = Callable[[ResearchState, WorkerBranch], BranchOutcome]
"""How one branch is carried out. Injectable so a test can fail one."""


@dataclass(frozen=True)
class MergedEvidence:
    """The deterministic union of every succeeded branch's table."""

    papers: list[PaperMetadata]
    paper_analyses: list[PaperAnalysis]
    evidence: list[EvidenceClaim]
    provenance: list[EvidenceProvenance]
    branches: list[WorkerBranch]


def _clean(value: Any) -> list[str]:
    """Non-empty stripped strings out of a state list field, safely."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _dedup(values: Iterable[str]) -> list[str]:
    """First occurrence wins, order preserved, case-folded comparison."""
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        kept.append(value)
    return kept


def _branch_queries(
    question: str, plan_queries: Sequence[str], index: int, branches: int
) -> list[str]:
    """The queries branch `index` runs: its own question, then its share.

    The planner emits one flat `search_queries` list with no mapping
    back to the sub-question that motivated each entry, so the mapping
    is made here and made deterministically: branch `i` of `n` takes
    every `n`-th planned query starting at `i`. Every planned query
    reaches exactly one branch, no query is run twice, and the same plan
    always produces the same assignment.

    The branch's own question leads, because it is the one query that is
    certainly on topic for this branch — a plan whose queries are all
    about sub-question one would otherwise leave branch two searching
    for someone else's question.
    """
    if branches <= 0:
        return [question]
    share = list(plan_queries)[index::branches]
    return _dedup([question, *share])[:MAX_QUERIES_PER_BRANCH]


def _branch_questions(state: ResearchState) -> list[str]:
    """The questions this run branches on, in the planner's order.

    Falls back to the research question itself when the plan carries no
    sub-questions — a one-branch run is a degenerate orchestration and
    still produces a report, which is strictly better than a policy that
    refuses to run because the planner was terse.
    """
    questions = _dedup(_clean(state.get("sub_questions", [])))
    if questions:
        return questions
    query = str(state.get("query", "") or "").strip()
    return [query] if query else []


def _is_repair_pass(state: ResearchState) -> bool:
    """Whether the lead is being re-entered by a retrieval repair.

    CAP-02's repair rewrites `search_queries` to the gaps the verifier
    named and routes back into the pipeline. Under this policy that
    re-entry adds branches rather than replacing the run's retrieval:
    the merged evidence from the first pass is what the report was built
    on, and a repair that discarded it would be a re-plan wearing a
    repair's name. See ADR 0086 §Decision.
    """
    return bool(state.get("worker_branches")) and (
        str(state.get("repair_action", "") or "") == "retrieve_missing_evidence"
    )


def plan_branches(state: ResearchState) -> list[WorkerBranch]:
    """Turn the plan into bounded worker branches, deterministically.

    Pure over the state and the settings' three caps: no model call, no
    clock, no I/O. The same plan always produces the same branch list in
    the same order, which is what makes `merge_branches` reproducible
    and what lets an evaluation attribute a result to the branching
    rather than to the scheduler.

    On a repair pass the already-executed branches are kept as they are
    and the gap queries become *new* branches appended after them, so
    branch ids stay unique for the life of the run and the merge sees
    both passes.

    Args:
        state: The graph state as the planner (or the repair) left it.

    Returns:
        Every branch this run has, planned ones last.
    """
    repairing = _is_repair_pass(state)
    existing: list[WorkerBranch] = (
        list(state.get("worker_branches", []) or []) if repairing else []
    )
    if repairing:
        questions = _dedup(_clean(state.get("search_queries", [])))
        prefix = REPAIR_BRANCH_PREFIX
        plan_queries: list[str] = []
    else:
        questions = _branch_questions(state)
        prefix = PLANNED_BRANCH_PREFIX
        plan_queries = _dedup(_clean(state.get("search_queries", [])))

    limit = max(1, int(settings.orchestration_max_branches))
    selected = questions[:limit]
    max_papers = max(1, int(settings.orchestration_max_papers_per_branch))
    share = float(settings.orchestration_branch_cost_share) * float(
        settings.max_cost_usd
    )

    planned: list[WorkerBranch] = []
    for offset, question in enumerate(selected):
        index = len(existing) + offset
        planned.append(
            WorkerBranch(
                branch_id=f"{prefix}{index:02d}",
                index=index,
                sub_question=question,
                search_queries=(
                    [question]
                    if repairing
                    else _branch_queries(question, plan_queries, offset, len(selected))
                ),
                status=STATUS_PLANNED,
                reason="",
                max_papers=max_papers,
                cost_share_usd=round(share, 6),
                paper_ids=[],
                analysis_count=0,
                evidence_count=0,
                llm_calls=0,
                cost_usd=0.0,
                papers=[],
                paper_analyses=[],
                evidence=[],
            )
        )
    return existing + planned


def branch_input_state(state: ResearchState, branch: WorkerBranch) -> ResearchState:
    """Build the isolated state one branch runs on.

    Built by the canonical constructor rather than by copying the
    parent, which is the whole isolation guarantee in one line: the
    branch holds no reference to any object the parent or a sibling can
    see, so there is nothing for a partial write to leak through. Every
    key is present, so the agents' `.get()` defaults never differ from
    what a top-level run would see.

    The branch's `query` is its **sub-question**. That is the
    diversification: `search_agent` ranks the candidate pool against
    `query`, so N branches with N questions retrieve N differently
    ranked corpora, where N copies of the original query would retrieve
    the same one N times and call it a branch set.

    Args:
        state: The parent state, read for `run_id` and `prior_context`
            and for nothing else.
        branch: The branch record whose scope and caps apply.

    Returns:
        A complete `ResearchState` scoped to this branch alone.
    """
    scoped = initial_research_state(
        branch["sub_question"],
        str(state.get("run_id", "") or ""),
        prior_context=str(state.get("prior_context", "") or ""),
    )
    scoped["sub_questions"] = [branch["sub_question"]]
    scoped["search_queries"] = list(branch["search_queries"])
    return scoped


def _execute_branch(state: ResearchState, branch: WorkerBranch) -> BranchOutcome:
    """Search, then read, for one sub-question. The default executor.

    The two agents are called as functions on a branch-scoped state
    rather than re-implemented, so a branch runs the same retrieval and
    the same reader — including the reader's own per-paper fan-out,
    containment and cancellation checks — that every other shape runs.

    The paper cap is applied between them, which is the only place it
    can bind: `search_agent` ranks against `settings.max_papers` and the
    reader spends one model call per paper it is handed.
    """
    scoped = branch_input_state(state, branch)
    search_update = search_agent(scoped)
    scoped["papers"] = list(search_update.get("papers", []))[: branch["max_papers"]]
    if not scoped["papers"]:
        return BranchOutcome()
    reader_update = reader_agent(scoped)
    return BranchOutcome(
        papers=list(scoped["papers"]),
        paper_analyses=list(reader_update.get("paper_analyses", [])),
        evidence=list(reader_update.get("evidence", [])),
    )


def _failure_code(exc: BaseException) -> str:
    """The typed code a branch failure is recorded under.

    `src/errors.py`'s vocabulary wherever the exception carries one —
    `not_found_papers`, `upstream_arxiv`, `upstream_paper_read`,
    `upstream_model` — because a branch failure is the same fact as a
    run failure, one level down, and inventing a second vocabulary for
    it would make the two uncountable together (ADR 0064).
    """
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else REASON_UNEXPECTED


def _settled(
    branch: WorkerBranch,
    *,
    status: str,
    reason: str = "",
    outcome: BranchOutcome | None = None,
    llm_calls: int = 0,
    cost_usd: float = 0.0,
) -> WorkerBranch:
    """A new branch record with its outcome written. Never mutates."""
    result = outcome or BranchOutcome()
    settled: WorkerBranch = {
        **branch,
        "status": status,
        "reason": reason,
        "paper_ids": [paper["id"] for paper in result.papers],
        "analysis_count": len(result.paper_analyses),
        "evidence_count": len(result.evidence),
        "llm_calls": llm_calls,
        "cost_usd": round(cost_usd, 6),
        "papers": list(result.papers),
        "paper_analyses": list(result.paper_analyses),
        "evidence": list(result.evidence),
    }
    return settled


def run_branches(
    state: ResearchState, *, execute: BranchExecutor | None = None
) -> list[WorkerBranch]:
    """Execute every planned branch, in order, containing each failure.

    Four outcomes per branch and each is a *record*, never a silent
    skip:

    - `succeeded` — the branch's evidence is in its record;
    - `failed` — one exception, contained, with the typed code that
      caused it. The next branch runs;
    - `budget_stopped` — the branch's own cost share ran out. The run's
      ceiling has *not* been reached, so the next branch still runs;
    - `cancelled` — the job was cancelled. Nothing after it runs and the
      exception propagates, because a cancelled job must stop rather
      than finish the remaining branches on a run nobody is waiting for
      (ADR 0047).

    A `CostBudgetExceeded` raised against the *run's* ceiling rather
    than a branch's share is re-raised unchanged, so the existing
    budget-stopped outcome — a partial report, `run.budget_stopped` on
    the trajectory — is produced by the code that already produces it
    (ADR 0051). Nothing here does its own cost accounting.

    Args:
        state: The graph state the lead node left.
        execute: How one branch is carried out. Defaults to
            `_execute_branch`; injected by tests that need a branch to
            fail in a particular way.

    Returns:
        Every branch record, settled, in the order they were planned.

    Raises:
        JobCancelledError: The job was cancelled between or during
            branches.
        CostBudgetExceeded: The run's own ceiling was reached.
    """
    run = execute or _execute_branch
    outer_cap = effective_cost_cap(settings.max_cost_usd)
    costs = current_costs()
    settled: list[WorkerBranch] = []
    branches = list(state.get("worker_branches", []) or [])

    for position, branch in enumerate(branches):
        if branch["status"] != STATUS_PLANNED:
            settled.append(branch)
            continue
        # Between branches, not only between papers: a cancelled job
        # must not start a branch it will throw away, and the reader's
        # own check only fires once a branch has already reached it.
        check_cancelled()

        spent_before = costs.total_cost_usd if costs is not None else 0.0
        calls_before = costs.call_count if costs is not None else 0
        share = float(branch["cost_share_usd"])
        branch_cap = (
            min(outer_cap, spent_before + share) if share > 0 else outer_cap
        )
        token = bind_effective_cost_cap(branch_cap)
        try:
            outcome = run(state, branch)
        except CostBudgetExceeded as exc:
            if exc.cap_usd >= outer_cap:
                # The run's ceiling, not this branch's share. ADR 0051's
                # path owns this: a partial report and a budget-stopped
                # job, produced by the runner rather than reinvented.
                raise
            settled.append(
                _settled(
                    branch,
                    status=STATUS_BUDGET_STOPPED,
                    reason=REASON_BUDGET_EXHAUSTED,
                    llm_calls=(costs.call_count - calls_before) if costs else 0,
                    cost_usd=(costs.total_cost_usd - spent_before) if costs else 0.0,
                )
            )
            continue
        except BaseException as exc:  # noqa: BLE001 — see the docstring
            cancelled = isinstance(exc, JobCancelledError)
            settled.append(
                _settled(
                    branch,
                    status=STATUS_CANCELLED if cancelled else STATUS_FAILED,
                    reason=REASON_CANCELLED if cancelled else _failure_code(exc),
                    llm_calls=(costs.call_count - calls_before) if costs else 0,
                    cost_usd=(costs.total_cost_usd - spent_before) if costs else 0.0,
                )
            )
            if cancelled or not isinstance(exc, Exception):
                # A cancelled job stops here; the remaining branches keep
                # their `planned` status so the record shows what was
                # never attempted. A BaseException that is not an
                # Exception (KeyboardInterrupt, SystemExit) is not a
                # branch failure and is never contained.
                for pending in branches[position + 1 :]:
                    settled.append(pending)
                raise
            continue
        finally:
            reset_effective_cost_cap(token)

        settled.append(
            _settled(
                branch,
                status=STATUS_SUCCEEDED,
                outcome=outcome,
                llm_calls=(costs.call_count - calls_before) if costs else 0,
                cost_usd=(costs.total_cost_usd - spent_before) if costs else 0.0,
            )
        )
    return settled


def merge_branches(
    branches: Sequence[WorkerBranch], *, base: MergedEvidence | None = None
) -> MergedEvidence:
    """Union every succeeded branch's table onto the base, deterministically.

    Order is a function of the base, the branch list and each branch's
    own output, and of nothing else: the base first, then branches in
    planned order, and within a branch the reader's order. Two runs over
    the same inputs therefore produce byte-identical merged evidence,
    which is the property `tests/test_orchestration_policy.py` asserts
    and the one a candidate comparison rests on.

    **Incremental on purpose.** The merge node hands in what the run has
    already merged as `base`, because the graph can re-enter the branch
    tier twice: a retrieval repair adds one branch per named gap, and a
    critic asking for more retrieval adds a whole new set. A merge that
    started empty each time would replace the run's evidence with the
    newest pass's, which is precisely the "reflect again" recovery
    `02-target-architecture.md` §5 rejects — the repair is supposed to
    *add* the missing source, not throw the found ones away. It is also
    what lets the merge release each branch's bulk output afterwards:
    a re-merged trimmed branch contributes nothing new because its
    contribution is already in the base.

    Papers are deduplicated on `canonical_paper_key` — ADR 0041's key,
    the same one `deduplicate_papers` uses — so the versioned arXiv form
    one branch retrieved and the unversioned form another retrieved are
    one paper with two branches in its provenance rather than two
    papers. The *first* branch to find a paper owns its position and its
    metadata; the later branch is recorded in the provenance row.

    Evidence claims are deduplicated on (paper, section, claim text),
    because two branches reading the same paper for two different
    sub-questions frequently extract the same sentence and the
    synthesizer should see it once.

    Args:
        branches: Every branch record, settled.
        base: What the run has already merged, or `None` for a first
            pass.

    Returns:
        The merged tables, the provenance, and the branch records with
        their bulk output emptied — the merge is where those collections
        stop being needed, and carrying them into every later checkpoint
        would double the run's state for no reader.
    """
    seed = base or MergedEvidence([], [], [], [], [])
    papers: list[PaperMetadata] = list(seed.papers)
    analyses: list[PaperAnalysis] = list(seed.paper_analyses)
    evidence: list[EvidenceClaim] = list(seed.evidence)
    # The nested lists are copied, not shared: this function must be
    # able to run twice over the same base and produce the same answer,
    # which it could not if the first call had appended into the base's
    # own rows.
    provenance: dict[str, EvidenceProvenance] = {
        row["canonical_id"]: EvidenceProvenance(
            {
                **row,
                "branch_ids": list(row["branch_ids"]),
                "sub_questions": list(row["sub_questions"]),
            }
        )
        for row in seed.provenance
    }
    seen_papers = {canonical_paper_key(paper["id"]) for paper in papers}
    seen_analyses = {canonical_paper_key(a["paper_id"]) for a in analyses}
    seen_claims: set[tuple[str, str, str]] = {
        (canonical_paper_key(claim["paper_id"]), claim["section"], claim["claim"])
        for claim in evidence
    }

    for branch in branches:
        if branch["status"] != STATUS_SUCCEEDED:
            continue
        for paper in branch["papers"]:
            key = canonical_paper_key(paper["id"])
            row = provenance.get(key)
            if row is None:
                provenance[key] = EvidenceProvenance(
                    paper_id=paper["id"],
                    canonical_id=key,
                    branch_ids=[branch["branch_id"]],
                    sub_questions=[branch["sub_question"]],
                    claim_count=0,
                )
            elif branch["branch_id"] not in row["branch_ids"]:
                row["branch_ids"].append(branch["branch_id"])
                row["sub_questions"].append(branch["sub_question"])
            if key not in seen_papers:
                seen_papers.add(key)
                papers.append(paper)
        for analysis in branch["paper_analyses"]:
            key = canonical_paper_key(analysis["paper_id"])
            if key in seen_analyses:
                continue
            seen_analyses.add(key)
            analyses.append(analysis)
        for claim in branch["evidence"]:
            key = canonical_paper_key(claim["paper_id"])
            fingerprint = (key, claim["section"], claim["claim"])
            if fingerprint in seen_claims:
                continue
            seen_claims.add(fingerprint)
            evidence.append(claim)
            row = provenance.get(key)
            if row is not None:
                row["claim_count"] += 1

    trimmed = [
        WorkerBranch({**branch, "papers": [], "paper_analyses": [], "evidence": []})
        for branch in branches
    ]
    return MergedEvidence(
        papers=papers,
        paper_analyses=analyses,
        evidence=evidence,
        provenance=[provenance[key] for key in provenance],
        branches=trimmed,
    )


# ---------------------------------------------------------------------------
# The three graph nodes
# ---------------------------------------------------------------------------


def lead_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: plan the branch set. No model call, by design.

    The planner has already decomposed the question into sub-questions
    and the lead's job is to bound them, not to re-decompose them. A
    second decomposition would spend a call, make the branch set
    non-deterministic, and put two disagreeing plans in one run.

    Returns:
        Partial state update carrying every branch, planned ones last.
    """
    branches = plan_branches(state)
    planned = [branch for branch in branches if branch["status"] == STATUS_PLANNED]
    if planned:
        questions = "; ".join(branch["sub_question"] for branch in planned)
        summary = f"Planned {len(planned)} worker branch(es): {questions}"
    else:
        summary = "Planned no worker branches (the plan carried no question)."
    return {
        "worker_branches": branches,
        "messages": [AIMessage(content=summary, name="lead")],
    }


def workers_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: run the branches and record what each one did.

    Raises the first branch's exception when *no* branch succeeded, so a
    run whose every branch found nothing fails with the same typed
    outcome the fixed pipeline would have produced — `not_found_papers`
    when arXiv answered with nothing, `upstream_arxiv` on an outage,
    `upstream_paper_read` when the papers could not be read. A node that
    returned an empty evidence table instead would hand the synthesizer
    nothing and let a fluent, sourceless briefing ship (ADR 0041).

    One succeeded branch is enough to continue: that is the point of
    branching, and the merge records the failures beside the successes.

    Returns:
        Partial state update carrying every settled branch record.
    """
    branches = run_branches(state)
    succeeded = [b for b in branches if b["status"] == STATUS_SUCCEEDED]
    failed = [b for b in branches if b["status"] in (STATUS_FAILED, STATUS_BUDGET_STOPPED)]

    if not succeeded and failed:
        raise _branch_failure(failed)

    detail = ", ".join(
        f"{b['branch_id']}:{b['status']}"
        + (f"({b['reason']})" if b["reason"] else "")
        for b in branches
    )
    summary = (
        f"{len(succeeded)} of {len(branches)} branch(es) succeeded — {detail}."
    )
    return {
        "worker_branches": branches,
        "messages": [AIMessage(content=summary, name="workers")],
    }


def _branch_failure(failed: Sequence[WorkerBranch]) -> Exception:
    """The exception a run with no successful branch fails with.

    The first failure's code, re-raised as its own error class, because
    it is a failure that actually happened rather than a summary
    invented for the occasion. `src/errors.py`'s registry maps the code
    back to the class, so the job's `error_type` is exactly what a
    single-trajectory run would have carried.
    """
    from src.errors import ServiceUnavailableError, error_class_for_code

    reason = failed[0]["reason"]
    error_class = error_class_for_code(reason) or ServiceUnavailableError
    return error_class(
        log_detail=(
            f"all {len(failed)} worker branch(es) failed; first reason: {reason}"
        )
    )


def merge_node(state: ResearchState) -> dict[str, Any]:
    """Graph node: union the branch tables into the run's evidence.

    The one place the branch results become the run's results. After it
    the graph is the fixed evidence path again — synthesizer, verify,
    critic — reading `evidence`, `papers` and `paper_analyses` exactly
    as it does under every other policy, which is what keeps the
    downstream agents unchanged by this work order.

    Returns:
        Partial state update: the merged tables, the provenance, and the
        branch records with their bulk output released.
    """
    merged = merge_branches(
        list(state.get("worker_branches", []) or []),
        base=MergedEvidence(
            papers=list(state.get("papers", []) or []),
            paper_analyses=list(state.get("paper_analyses", []) or []),
            evidence=list(state.get("evidence", []) or []),
            provenance=list(state.get("merged_evidence_provenance", []) or []),
            branches=[],
        ),
    )
    summary = (
        f"Merged {len(merged.evidence)} evidence claim(s) across "
        f"{len(merged.papers)} deduplicated paper(s) from "
        f"{sum(1 for b in merged.branches if b['status'] == STATUS_SUCCEEDED)} "
        f"branch(es)."
    )
    return {
        "papers": merged.papers,
        "paper_analyses": merged.paper_analyses,
        "evidence": merged.evidence,
        "merged_evidence_provenance": merged.provenance,
        "worker_branches": merged.branches,
        "messages": [AIMessage(content=summary, name="merge")],
    }
