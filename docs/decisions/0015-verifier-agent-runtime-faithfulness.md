# 0015. Verifier agent — runtime faithfulness check as a supervisor action

- **Status**: accepted
- **Date**: 2026-07-07
- **Depends on**: ADR [0007](0007-faithfulness-single-call-abstracts.md),
  ADR [0014](0014-supervisor-loop-behind-flag.md)

## Context

ADR 0014 landed the supervisor loop behind `settings.enable_supervisor`.
Its action space is intentionally minimal (`plan | search | read |
synthesize | critique | stop`) so we can measure whether the loop
itself pays for its own cost before we widen the action space.

The plan for Sprint 2 (see
[`planning/05-agentic-upgrade-plan.md`](../../planning/05-agentic-upgrade-plan.md),
items 4 and 5) calls out the verifier as **the best effort:quality
ratio** upgrade to that action space: ADR 0007 already spent the
prompt-engineering budget building a calibrated faithfulness judge, and
that judge is already run offline every eval cycle. The Sprint 2 unlock
is not new prompt work — it's promoting that same judge into an in-loop
node whose output drives the supervisor's next choice.

Two constraints dominate the design:

1. **Independent from the supervisor flag**. The supervisor and the
   verifier are two separate experiments on the Sprint 1 baseline. We
   want to be able to answer "did the loop help?" and "did the verifier
   help?" separately, on paired diffs, without confounding the two.
   That rules out coupling `verify` to `enable_supervisor`.
2. **The fixed pipeline stays untouched**. The verifier is a
   supervisor-only node — under the fixed pipeline it must not run,
   even by accident. That keeps the Sprint 1 baseline immutable while
   we A/B against it.

## Decision

Add `src/agents/verifier.py` with `verifier_agent(state) -> partial
state`. Gate its availability with `settings.enable_verifier: bool =
False`, independent of `settings.enable_supervisor`.

### Where it sits in the graph

- **Fixed pipeline (`enable_supervisor=False`)**: verifier is not
  wired. It cannot run.
- **Supervisor loop, verifier off (`enable_supervisor=True,
  enable_verifier=False`)**: baseline for measuring "did the loop help
  by itself". `verify` is stripped from the action enum
  (`_available_actions()` in `src/agents/supervisor.py`); the verifier
  node is not added to the graph; the prompt does not advertise
  `verify`. A stale-checkpoint `next_action="verify"` falls through to
  `END` via `route_after_supervisor` — the graph cannot wedge.
- **Supervisor loop, verifier on (both flags true)**: `verify` is a
  valid supervisor action; the verifier node is wired between
  `supervisor` and `supervisor` (like every other action node). The
  supervisor's system prompt gets an extra action line and a deviation
  hint telling it to run `verify` when a fresh draft exists.

### Response schema

Extends ADR 0007's per-claim judge output with a runtime recovery
recommendation:

```json
{
  "verified": true,
  "unsupported_claims": ["..."],
  "missing_evidence": ["..."],
  "recommended_action": "read_more|search_more|revise_report|",
  "reason": "one-sentence overall diagnosis"
}
```

`recommended_action` is intent-shaped (`"what's wrong"`), not
routing-shaped (`"what to do next"`), so the supervisor stays the sole
owner of routing choices. The mapping is straightforward — `read_more →
read`, `search_more → search` or `plan`, `revise_report → synthesize` —
but the supervisor makes the call, informed by the rest of state.

### State additions (`ResearchState`)

- `verified: bool` — true iff every cited claim resolved and no
  sub-question is missing evidence.
- `unsupported_claims: list[str]` — verbatim strings the judge flagged.
- `missing_evidence: list[str]` — topics or sub-questions that lack a
  cited source.
- `verifier_recommendation: str` — one of `read_more | search_more |
  revise_report | ""`.

Under the fixed pipeline (or with verifier disabled) these stay at
defaults; the supervisor's state summary omits them so the prompt
signal stays clean.

### Cheap failure modes are cheap on purpose

- **Empty draft** — verifier short-circuits with `verified=True` and no
  LLM call. Prevents the supervisor from paying for a verification
  round before synthesis has even happened.
- **Draft with no citations** — same short-circuit. There is nothing to
  verify in ADR 0007's frame; the critic will catch the "no citations"
  problem.
- **LLM exception / malformed JSON** — falls back to `verified=False,
  verifier_recommendation="revise_report"`. Not fatal; the supervisor
  can route to another synthesis pass. Chosen deliberately over
  "assume verified" so a broken judge cannot let unverified drafts
  slip through.
- **Judge output contradicts itself** — if the judge returns
  `verified=True` but also flags unsupported claims or missing
  evidence, the verifier downgrades to `verified=False`. `verified`
  must mean "no follow-up needed".

### Shared source-index logic

`build_source_index` in `src/eval/metrics.py` is now the shared join
between citations and paper abstracts, used by both the offline
faithfulness metric (ADR 0007) and the runtime verifier. Same
normalization rules; keeps the online and offline judges reading from
the same substrate so their scores are comparable.

## Alternatives considered

**Bundle verifier launch with a `verify` action always in
`enable_supervisor`.** Simpler code path — no second flag. Rejected
because it destroys the ability to A/B the supervisor and the verifier
separately against the Sprint 1 baseline. If the combined "supervisor
+ verifier" configuration regressed cost without lifting quality, we
couldn't tell which one is at fault without a re-run.

**Run the verifier as a fixed pipeline node between synthesizer and
critic (no supervisor).** Would let us test verifier value without the
supervisor. Rejected because it changes the fixed pipeline — which is
the baseline every Sprint 2 experiment compares against. The verifier
belongs in the supervisor era.

**Make `recommended_action` mirror the supervisor's action enum
directly (`search`, `read`, `synthesize`, ...).** Would remove a level
of indirection. Rejected because it forces the verifier prompt to know
about routing concerns (`plan` vs `search`, `synthesize` vs `revise`).
Keeping recommendations at the diagnostic layer keeps the two prompts
independently editable.

**Ship the evidence store now so the verifier judges chunks, not
abstracts.** That's Sprint 2 item 5. Bundling would push this PR well
past ~800 additions and mix two independent changes (verifier wiring
vs. reader emission format). Ship them sequentially, evaluate each
against the baseline. The verifier's known limitation (inherits ADR
0007's abstract-only source) is temporary; item 5 fixes it.

## Consequences

**Wins**

- One net-new action (`verify`) in the supervisor's toolkit, guarded
  behind its own flag so it can be A/B'd against a supervisor-only
  configuration.
- No new prompt engineering — reuses ADR 0007's calibrated judge.
- Shared `build_source_index` means the runtime and offline
  faithfulness judges read the same substrate.
- Conservative fallback behavior — a broken judge cannot let a bad
  draft through; it can only cost us an extra synthesis loop.

**Tradeoffs**

- One extra flag combination to test. Documented explicitly:
  three configurations are supported (`fixed`, `sup-only`, `sup+ver`);
  `sup-off + ver-on` is a no-op by design.
- Verifier inherits ADR 0007's "abstracts are a lower bound" limitation
  until the evidence store lands.
- The supervisor's system prompt now branches on `enable_verifier`. It
  stays a single template with two `{}` interpolations — deliberate
  choice over two entirely separate prompts, to keep divergence
  visible in one place.

**Non-goals (deferred)**

- Evidence store with `EvidenceClaim` (Sprint 2 item 5). Reader emits
  free-form summaries today; verifier judges against paper abstracts,
  not chunks.
- Cost-aware verifier gating ("skip verify if we're near budget"). The
  supervisor's own budget short-circuit is sufficient for now — if
  we're near budget the supervisor stops before calling any node,
  verifier included.
