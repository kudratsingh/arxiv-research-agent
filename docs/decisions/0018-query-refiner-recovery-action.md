# 0018. Query refiner — new `refine_query` supervisor action

- **Status**: accepted
- **Date**: 2026-07-08
- **Depends on**: ADR
  [0014](0014-supervisor-loop-behind-flag.md)

## Context

The supervisor loop's `search` action re-runs whatever's in
`state.search_queries`. When the first search returns weak or
incomplete results, the supervisor's only recovery move — "search
again" — re-runs *the same failing queries*. That is not a recovery
action; it's a retry-with-nothing-changed loop that thrashes.

Sprint 2 item 6 in
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md)
calls this out as the difference between a supervisor that recovers
and a supervisor that thrashes. The verifier (ADR 0015) already emits
`missing_evidence`; the evidence-store synthesizer (ADR 0017) already
tells the LLM to route uncovered topics into "Open Questions". Both
of those describe gaps but neither can act on them at the search
layer. This ADR adds the action.

Same constraints as previous Sprint 2 agents:

1. **Fixed pipeline stays untouched.** The fixed pipeline is a linear
   DAG with no re-search — `refine_query` has no home there and adds
   no value. Supervisor-only, flag-gated.
2. **Independent flag.** The refiner should be A/B'able against a
   supervisor-only baseline so we can tell whether "supervisor +
   refiner" recovers better than "supervisor alone" — separately from
   the verifier and evidence-store flags.
3. **Fail closed, not open.** A refiner that returns empty or all-
   duplicate output must NOT blank the state. Better to re-run a weak
   query than to stall the loop with nothing to search for.

## Decision

Add `src/agents/query_refiner.py` with
`query_refiner_agent(state) -> partial state`. Gate with
`settings.enable_query_refiner: bool = False`, independent of every
other Sprint 2 flag. Add `refine_query` to the supervisor's
`VALID_ACTIONS`; `_available_actions()` strips it when the flag is
off. `route_after_supervisor` returns `END` on any flag-disabled
action so a stale checkpoint carrying `refine_query` cannot wedge the
graph.

### `refine_query` in the supervisor's toolkit

When the flag is on, the supervisor's system prompt gains:

```
- refine_query : Generate fresh search queries targeted at
  coverage gaps (do NOT re-run the same weak search)
```

plus a deviation hint telling it to prefer `refine_query` over `search`
when the last search returned few / weak papers or when the verifier
reports `missing_evidence`. The action enum in the response schema is
computed from `_available_actions()` so the LLM only sees the actions
that are actually wired.

### State additions

- `tried_search_queries: list[str]` — flat history of every search
  query the supervisor loop has run in this workflow. Populated only
  when the refiner runs; empty otherwise (fixed pipeline reads it as
  `[]`). Refiner appends the currently-in-flight `search_queries`
  into `tried_search_queries` at the moment of replacement, so the
  history reflects "what was in flight at the moment refine_query
  was picked."

No `open_questions` / `evidence_gaps` state fields land here — the
refiner reads verifier's `missing_evidence` and critic's `critique`
directly. Adding intermediate fields would just add another producer
to maintain without clear consumers.

### Dedup and fail-closed policy

The refiner LLM is told, in the system prompt, to never repeat an
already-tried query and to return an empty list when it can't find a
genuinely new angle. On top of that, the refiner enforces dedup
server-side:

- `forbidden = tried_search_queries ∪ current search_queries`,
  normalized (lowercase + strip).
- Candidates that normalize to something in `forbidden` are dropped.
- Candidates that normalize-duplicate each other within the batch are
  deduped, preserving first-occurrence order.

If the filtered set is empty (LLM exception, non-list `queries`
field, empty list, all duplicates), the refiner **keeps current
`search_queries` and `tried_search_queries` intact** and logs
`query_refiner_kept_current` with the reason. The message trail
carries a "kept current queries" note so downstream analysis can
bucket these fail-closed rounds.

### Prompt input surface

The refiner sees, in this order:

1. Original research question.
2. Planner sub-questions.
3. Every already-tried query (`tried_search_queries + current
   search_queries`).
4. Papers already retrieved — titles + first 40 words of each
   abstract. Enough to signal what territory has been covered without
   inflating prompt cost.
5. Verifier-reported `missing_evidence`.
6. Critic feedback (`state.critique`) when present.

Critic feedback and verifier `missing_evidence` are the specifically-
gap-targeted inputs; the LLM is told to prefer queries that go after
those over broad rewordings of the original question.

## Alternatives considered

**Make the refiner an implicit pre-step of `search`.** Every `search`
action would run the refiner first when the supervisor asked to re-
search. Rejected because the supervisor should see the recovery
action as a first-class choice — the whole point of the loop is
letting the supervisor decide *when* to recover, not baking the
decision into another node. Also breaks A/B measurability.

**Return new queries and let the supervisor push them into
`search_queries` on its next turn.** Would keep the refiner
side-effect-free. Rejected because it forces the supervisor to
understand the refiner's output schema — cleaner to have the refiner
write the state field directly (like every other agent) and have
the supervisor just pick `search` next.

**Delete tried queries from `search_queries` before running.**
Considered as an alternative to fail-closed. Rejected because it can
leave `search_queries` empty on the next supervisor turn, at which
point `search` fires with nothing and produces zero papers — worse
than repeating a weak query.

**Track `tried_search_queries` inside the search agent instead of the
refiner.** Would accumulate history even without the refiner
enabled. Rejected because the history is meaningless when there's no
consumer for it, and touching the search agent under an unrelated
flag violates the "fixed pipeline stays untouched" invariant.

**Add `open_questions` / `evidence_gaps` state fields as producer
+ consumer of gap info.** Considered — the plan mentions them.
Rejected as premature: today the verifier's `missing_evidence` and
the critic's `critique` are the only gap producers, and the refiner
is their only consumer. Adding intermediate fields with no other
producers/consumers is YAGNI. Revisit if a critic-side or planner-
side gap-tracker lands.

## Consequences

**Wins**

- `refine_query` is a first-class supervisor action; the loop can
  now recover from weak search instead of thrashing.
- Independent flag preserves A/B measurability of the four
  configurations: `fixed` / `sup-only` / `sup+ver` / `sup+ver+ref`
  (and combinations with evidence-store).
- Fail-closed policy means a broken refiner cannot blank state or
  stall the loop — worst case is a re-run of the previous search.
- Verifier `missing_evidence` finally has a downstream actuator.

**Tradeoffs**

- Refiner adds one LLM call per invocation (~1024 tokens output cap,
  cheap Sonnet call). Loop cost tax on top of the supervisor's tax
  when the flag is on. Bounded by `max_loop_iterations` and
  `max_cost_usd`.
- Prompt input surface can be large — every already-tried query,
  every paper title+abstract head, missing_evidence, critique. Kept
  under budget by the abstract-head truncation and the flat-list
  history shape.
- One more flag combination in the sweep. Documented in the ADR list.

**Non-goals (deferred)**

- Evidence-store-aware refiner. The refiner reads
  `state.missing_evidence` regardless of whether it came from an
  abstract-based or chunk-based verifier judgment; no direct
  dependency on the evidence store flag.
- `open_questions` / `evidence_gaps` state fields. See alternatives.
- Search-side caching so refined queries don't re-hit arXiv for
  overlapping papers. Sprint 4 item.
