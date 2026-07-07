# Agentic upgrade plan (Sprint 2 focus)

The current system is **agentic-lite**: five agents wired as a fixed
DAG with one conditional edge (`critic → planner|search|synthesizer`)
and a hard iteration cap. Sprint 2 converts that DAG into a supervisor
loop — observe → decide → act → observe again — with recovery actions,
runtime self-verification, and budget-based stopping. This plan
captures the sequencing, the constraints, and what "success" looks
like.

Written after Sprint 1 wrap (2026-07-07). Sources: the review recorded
verbatim in [PR #19 discussion] plus the individual proposals in the
same review, prioritized and sanity-checked against what's already
built.

## Why this ordering and not the reviewer's original list

The outside review offered a 12-item wish list. Not all of it earns
its cost. The ranking below reflects three constraints:

1. **The harness must exist before the loop lands.** Sprint 1 built
   it. That means "harness-first" is no longer a to-do; we're free to
   build the loop and immediately measure whether autonomy paid for
   itself. This is exactly the sequence the reviewer endorsed.
2. **Loop cost is real.** A supervisor call between every step adds
   ~7-10 LLM calls per query. At Sonnet prices that's roughly a
   1.7-2× cost multiplier. The eval harness and cost tracker will
   surface this immediately.
3. **Unconstrained supervisors thrash.** The action space must be a
   strict enum with JSON validation and a fixed-order fallback on
   parse failure. Loose supervisors regress the metrics they were
   meant to improve.

## The plan, in priority order

### 1. Baseline eval freeze (prerequisite, ~1 day)

Before writing any loop code, run the 20-query benchmark three times
on `main` at Sprint 1's final commit. Store the three `summary.jsonl`
files as the baseline for every future comparison. **Loop code is only
"working" once it beats this baseline on quality without blowing the
cost budget.**

The three-repeat rule matters — with 20 queries and LLM judges, a
single run has enough judge noise that a 0.05 aggregate delta could
be signal or luck. Paired per-query diffs across repeats separate the
two.

### 2. Regression differ: add `iterations`, `llm_calls`, `cost_usd` (~1 day)

Currently `regression_diff.METRIC_FIELDS` covers only the four LLM-
judged metrics + critic score. Loop-induced cost creep and iteration
runaway won't show up. Adding these three fields to the differ (and
their per-query threshold checks) is a small change that guards
against the primary loop failure mode: quality holds steady but cost
5×'s.

### 3. Supervisor agent (~3-5 days) — **the actual upgrade**

- **File:** `src/agents/supervisor.py`
- **State additions** (full list, all merged into `ResearchState`):
  ```python
  research_goal: str                # the original user query, immutable
  next_action: str                  # supervisor's last decision
  open_tasks: list[ResearchTask]    # see item 5.75 below
  completed_tasks: list[ResearchTask]
  evidence: list[EvidenceClaim]     # see item 5
  tool_history: list[ToolCall]      # {tool, input, output_summary,
                                    #  success, cost_usd, timestamp}
  evidence_gaps: list[str]          # sub-questions with weak/no evidence
  confidence: float                 # aggregate self-assessment
  cost_budget_remaining: float      # updated after each LLM call
  budget_used: dict[str, float]     # per-tool spend
  stop_reason: str                  # "quality_reached" | "budget_reached" |
                                    # "max_iterations_reached" | "no_progress"
  ```
- **Settings additions** (all in `src/config.py`):
  ```python
  enable_supervisor: bool = False        # keep fixed pipeline default
  min_quality_score: float = 0.75        # supervisor stops above this
  min_faithfulness_score: float = 0.85   # verifier-driven stop threshold
  max_search_rounds: int = 3             # supervisor refuses more searches
  max_reader_rounds: int = 2             # supervisor refuses more reads
  max_cost_usd: float = 2.00             # supervisor stops above this
  max_loop_iterations: int = 20          # hard cap orthogonal to critic's
  ```
- **Action enum (strict):** `plan | search | read | verify |
  synthesize | critique | stop`. Any judge response outside the enum
  → drop to the fixed pipeline's next step. Not a fatal error; a
  recoverable fallback.
- **Prompt:** one system prompt with the enum + one-line rubric per
  action + a `stop_when` list from settings
  (`min_quality_score`, `min_faithfulness_score`, `max_cost_usd`,
  `max_search_rounds`, `max_reader_rounds`). Response is
  `{next_action, reason, stop_reason?}` in structured JSON.
- **Workflow rewrite:** `workflow.py` gains a "supervisor" node whose
  conditional edge picks the next real node. All other nodes emit
  back to the supervisor when they finish.
- **Budget enforcement:** supervisor sees `cost_budget_remaining`
  and refuses actions that would exceed it. On stop, records
  `stop_reason` on the final state.
- **Loop safety:** hard cap on total supervisor invocations
  (`settings.max_loop_iterations`, default 20). This is orthogonal
  to `max_iterations` (per-critic revision cap) — the two limits
  serve different failure modes.

**Interview framing (verbatim):**

> "I converted a fixed pipeline to a supervisor loop and measured
> whether autonomy paid for itself. On the 20-query benchmark, the
> loop lifted faithfulness from X.XX to Y.YY at Z% higher cost — or
> it didn't, and that's a good story too."

### 4. Verifier agent (~2 days) — **best effort:quality ratio**

- **File:** `src/agents/verifier.py`
- Promote the ADR-0007 offline faithfulness judge into an in-loop
  node. Runs after synthesizer, before critic. Same prompt shape,
  but the response drives the loop:
  ```
  {
    verified: bool,
    unsupported_claims: [...],
    missing_evidence: [...],
    recommended_action: "read_more" | "search_more" | "revise_report"
  }
  ```
- Recommended action feeds into supervisor's next decision.
- **Why this is the best ROI item:** the prompt already exists,
  tested, calibrated. The unlock is the loop wiring, not new prompt
  engineering.

### 5. Evidence store (~3 days) — verifier substrate

- **File:** `src/evidence/store.py`
- **Type:** `EvidenceClaim` with `{claim, paper_id, section,
  source_text, relevance_score, supports_question}`.
- Reader stops emitting free-form summaries; emits `list[EvidenceClaim]`
  keyed by which sub-question / open task each supports.
- Verifier judges against `source_text` (real chunk), not against
  abstracts. This is the concrete fix for the ADR-0007 known
  limitation ("abstracts are a lower bound on paper content").
- Synthesizer writes from claims, not paper analyses. Every
  sentence in the report should trace to at least one claim ID.
- State: `evidence: list[EvidenceClaim]`, `open_questions:
  list[str]`, `evidence_gaps: list[str]`.

### 5.5. Tool registry — turn each agent into a callable tool (~1 day)

- **File:** `src/tools/tool_registry.py`
- Right now agents are graph nodes only. The supervisor needs a
  uniform tool interface to call them:
  ```python
  TOOLS: dict[str, ToolSpec] = {
      "plan":       ToolSpec(fn=planner_agent,     args_schema=PlannerArgs),
      "search":     ToolSpec(fn=search_agent,      args_schema=SearchArgs),
      "read":       ToolSpec(fn=reader_agent,      args_schema=ReaderArgs),
      "synthesize": ToolSpec(fn=synthesizer_agent, args_schema=SynthesizerArgs),
      "critique":   ToolSpec(fn=critic_agent,      args_schema=CriticArgs),
      "verify":     ToolSpec(fn=verifier_agent,    args_schema=VerifierArgs),
      "refine_query": ToolSpec(fn=query_refiner,   args_schema=RefinerArgs),
  }
  ```
- Each `ToolSpec` carries: the callable, a pydantic args schema, a
  short description the supervisor prompt can read, and cost/latency
  metadata the supervisor uses when reasoning about budgets.
- **Why this matters:** with a registry, "add a new capability" is
  "add a `ToolSpec`", not "rewrite `workflow.py`". Also unblocks the
  MCP adapter later — MCP tools serialize from `ToolSpec` almost
  directly.

### 5.75. Research plan as first-class objects (~1 day)

- **Type:** `ResearchTask` TypedDict added to `graph/state.py`:
  ```python
  class ResearchTask(TypedDict):
      id: str                       # kebab-case slug
      question: str                 # the sub-question in prose
      status: Literal["not_started", "in_progress",
                      "weak_evidence", "complete"]
      search_queries: list[str]     # queries tried for this task
      evidence_ids: list[str]       # EvidenceClaim IDs supporting it
      confidence: float             # 0.0-1.0 self-assessed
  ```
- State: `open_tasks: list[ResearchTask]`,
  `completed_tasks: list[ResearchTask]`.
- Planner emits tasks (not just `sub_questions` — the current field
  becomes a projection over `open_tasks[*].question` for
  back-compat).
- Supervisor picks the next action by looking at tasks with the
  lowest `confidence` and the emptiest `evidence_ids`.
- Synthesizer writes the report grouping by completed tasks — the
  task structure becomes the report outline.

### 6. Query refiner (~2 days) — real recovery action

- **File:** `src/agents/query_refiner.py`
- Takes: original query, failed / weak search queries, papers
  already found, missing topics, critic feedback. Returns: new
  search queries targeted at gaps.
- Without this, the supervisor's "search again" choice just re-runs
  the same failing queries. It's the difference between a supervisor
  that recovers and a supervisor that thrashes.

### 7. Reader-requests-more-chunks (~1 day)

- Reader can respond with `{analysis_complete: false,
  missing_context: "...", request_more_sections: ["results",
  "limitations"]}`.
- Supervisor sees this and re-invokes reader with a narrower brief.
- Complements the query refiner: refiner recovers at search layer,
  this recovers at reading layer.

### 8. Prompt-injection isolation on the reader (~2 days)

Called out by the outside review and by our own
[`01-enterprise-gaps.md`](01-enterprise-gaps.md). **This escalates in
severity once the supervisor loop lands** because routing decisions
depend on text influenced by arXiv PDFs. A malicious paper could try
to redirect the loop.

- Tag paper text as untrusted in the prompt.
- Never let untrusted text populate control tokens the supervisor
  reads.
- Add a small adversarial-prompts test in `tests/test_reader.py`.

### 8.5. Claim-first synthesis (~3 days) — cleaner reports, easier verification

The reviewer's item 11. Rework synthesis from
`analyses → report` to `evidence → claims → outline → report → verify → revise`.

- **File:** `src/agents/claim_builder.py`
- Takes: `list[EvidenceClaim]` (from the reader / evidence store).
- Emits: `list[SupportedClaim]` — each with `claim_text`,
  `supporting_evidence_ids: list[str]`, `confidence`. Deduplicates
  overlapping claims across papers.
- **File:** `src/agents/outline_builder.py`
- Takes: `list[SupportedClaim]` + `list[ResearchTask]`.
- Emits: a hierarchical outline mapping tasks → sections → claims.
  Synthesizer walks this outline instead of free-forming from
  paper analyses.
- **Why this matters:**
  - **Faithfulness by construction:** every sentence in the report
    traces to a claim, and every claim traces to evidence. The
    verifier's job becomes trivial: "does the report's claim set
    equal `SupportedClaim[*]`?" instead of "extract claims from
    prose then match them to sources."
  - **Debuggability:** a bad report is now diagnosable at the
    outline layer without re-running the whole workflow.
  - **Interviews:** "I moved from prose-summary synthesis to
    claim-first synthesis so the report is faithful by construction"
    is a strong sentence.

### 9. Skills registry — **deferred to Sprint 6+**

Reviewer flagged this as valuable-but-not-core. Each skill
(`literature_survey`, `method_comparison`, ...) multiplies the eval
surface without proving the loop's core quality. Land after the
supervisor + verifier + evidence store have measurable wins.

### 10. MCP adapter — **deferred to Sprint 6+**

Expose the tools as an MCP server for external agent frameworks.
Framing-only value until the tools themselves are proven. Same
argument as skills: it multiplies interfaces without validating what
the interfaces expose.

## Cross-cutting concerns worth calling out

### Judge noise mandates repeat runs

Twenty queries × LLM judges = enough per-query noise that a single
aggregate delta is untrustworthy. Two mitigations, both cheap:

- **Paired per-query diffs** over aggregates. `regression_diff`
  already exposes this; the reviewer's read matches ours.
- **3 repeat runs** before believing a "supervisor beats baseline"
  claim. Cost: ~$45 for the baseline + $45 for each supervisor
  candidate. Acceptable.

### Prompt injection is now a control risk, not just a quality risk

Under the fixed pipeline, a jailbreak in a paper's abstract at worst
produces a bad report. Under the supervisor loop, a jailbreak can
redirect the loop — trigger repeated searches, stall on a false
"stop", or influence which sub-question the supervisor prioritizes.
Isolation on the reader boundary becomes load-bearing.

### Checkpointing matters more with a loop

Sprint 1 landed `SqliteSaver` — replayable state is how loop
regressions get debugged. When a supervisor makes a bad decision,
the debug story is "load the checkpoint just before the bad decision,
replay". Without checkpointing, this becomes "re-run the whole
workflow with print statements". Good that we already have it.

## What "success" looks like

- Faithfulness ↑ **≥ 5 points** on the 20-query benchmark (paired
  per-query, majority of queries improved).
- Retrieval recall ↑ or unchanged (supervisor should recover from
  weak search).
- Cost per query ≤ **1.8×** baseline (loop cost is the tax we pay
  for autonomy).
- No new judge-noise regressions on completeness / citation accuracy.
- `stop_reason` distribution surfaces: some `quality_reached`, some
  `budget_reached`, some `max_iterations_reached`.

The reviewer's framing that captures the deliverable:

> "I moved from a fixed graph to a tool-using agent loop. The
> supervisor observes the current state, selects the next tool,
> executes it, then updates state before deciding again."

If we can point at a paired-diff run showing the supervisor's number
beat the fixed pipeline's number — that's the whole win. If it
didn't, the harness we built in Sprint 1 tells us why, and we iterate
on the supervisor prompt without ripping out infrastructure.
