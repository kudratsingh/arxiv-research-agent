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
- **State:** new `next_action: str` field; `settings.enable_supervisor:
  bool = False` gate keeps the fixed pipeline default.
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

### 4. Verifier agent (~2 days) — **best effort:quality ratio** — **DONE**

- **File:** `src/agents/verifier.py` (ADR
  [0015](../docs/decisions/0015-verifier-agent-runtime-faithfulness.md),
  docs [`docs/agents/verifier.md`](../docs/agents/verifier.md)).
- Promoted the ADR-0007 offline faithfulness judge into an in-loop
  node. Behind `settings.enable_verifier: bool = False`, **independent
  of `enable_supervisor`** so the loop and the verifier can be A/B'd
  separately against the Sprint 1 baseline.
- Response schema shipped:
  ```
  {
    verified: bool,
    unsupported_claims: [...],
    missing_evidence: [...],
    recommended_action: "read_more" | "search_more" | "revise_report" | ""
  }
  ```
- Recommended action feeds into the supervisor's next decision — the
  supervisor's system prompt gains a `verify` action line and a
  deviation hint only when the flag is on.
- Short-circuits for empty draft and no-citations paths (no LLM call
  in either); conservative fallback on malformed judge output
  (`verified=False, recommendation="revise_report"`).

### 5. Evidence store — verifier substrate

Split into two halves so blast radius stays manageable:

**5a. Substrate + verifier upgrade (~2 days) — DONE**

- **Type:** `EvidenceClaim` TypedDict in `src/graph/state.py` with
  `{claim, paper_id, section, source_text, relevance_score,
  supports_question}`. Kept alongside `PaperAnalysis` in state; the
  reader emits both under the flag.
- **Reader** ships an evidence-path prompt (`EVIDENCE_SYSTEM_PROMPT`)
  that extends the base analysis response with a `claims: [...]`
  list. Each claim carries a 1-based `chunk_index` into numbered
  ranked chunks; the reader hydrates `source_text` / `section` /
  `relevance_score` server-side so those fields can't be
  paraphrased by the LLM. Single LLM call per paper (unchanged);
  `max_tokens` raised to 1536 on the evidence path.
- **Verifier** picks its dossier at call time: `_dossier_from_evidence`
  (chunks) when the flag is on and `state.evidence` is populated;
  `build_source_index` (abstracts) otherwise. Papers cited but
  lacking evidence claims fall back to their abstract in the same
  dossier block.
- Behind `settings.enable_evidence_store: bool = False`, **independent
  of `enable_supervisor` / `enable_verifier`**. Fixed pipeline stays
  byte-identical to Sprint 1 baseline (reader base-path prompts
  unchanged). ADR
  [0016](../docs/decisions/0016-evidence-store-source-text-verifier.md),
  docs [`docs/agents/reader.md`](../docs/agents/reader.md) and
  [`docs/agents/verifier.md`](../docs/agents/verifier.md).

**5b. Synthesizer swap (~2 days) — NEXT**

- Synthesizer prefers `state.evidence` over `paper_analyses` when
  populated. Every sentence in the report should trace to at least
  one claim ID.
- Evidence-aware `open_questions: list[str]` and `evidence_gaps:
  list[str]` state fields, produced by the verifier or a follow-up
  agent so the supervisor can route to `search` / `read` with
  concrete gap descriptions.
- Update the completeness / citation-accuracy metrics if the swap
  changes the report's shape enough to matter.

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
