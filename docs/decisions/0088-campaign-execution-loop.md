# 0088. Run a planned campaign from an injected runner, and write the terminal receipt last

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent engineering program (P0-WO07b)
- **Depends on**: ADR [0050](0050-eval-runner-hardening.md),
  ADR [0070](0070-eval-integrity-provenance.md),
  ADR [0071](0071-eval-statistics-and-gates.md),
  ADR [0074](0074-deterministic-groundedness.md),
  ADR [0080](0080-mock-mode-covers-the-whole-research-graph.md),
  ADR [0082](0082-campaign-lock-repeats-and-denominators.md),
  ADR [0083](0083-runtime-event-bridge-and-artifact-adapter.md)
- **Implements**: P0-WO07's execution half in
  [`docs/agent-engineering/12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
  §13, closing the one remaining code item named in
  [`15-stage0-qualification-report.md`](../agent-engineering/15-stage0-qualification-report.md)
  §7.2

## Context

ADR 0082 built `src/campaign/`: it resolves a registry lock, derives a
campaign id from the protocol, compiles the `cases x repeats x arms`
matrix, declares the five arms, opens a denominator ledger before
anything runs, and seals one episode's `RunManifest` into its own
directory. W11's qualification report then had to state plainly that the
package **never ran an episode**. There was no `async def` and no `await`
in it; nothing wrote `completion.json`, so `read_outcomes`, `reconcile`
and `summarize` had only ever seen receipts a test hand-wrote; and
`budget_stop_reached` — the between-episodes enforcement
`CampaignBudget.enforcement` advertises to anyone reading a manifest —
had no production caller at all.

That gap is not cosmetic. Four claims the W12 approval packet needs to
make are unprovable without a loop:

- **The denominator survives contact with a real run.** A ledger written
  before the campaign and reconciled from receipts a test wrote proves
  the arithmetic, not the plumbing.
- **The cap stops something.** "Enforcement is between episodes with
  in-flight overshoot risk" is a claim about code that did not exist.
- **A metered provider is refused before a credential is read.** The
  admission controller has always been able to say so; nothing had ever
  asked it in the course of running a campaign.
- **The whole matrix costs nothing under mock mode.** 300 planned slots
  had been *enumerated* at zero cost. None had been *executed*.

Four constraints shaped the answer:

1. `build_workflow` dispatches on the process-global `settings`
   singleton, and every agent module binds its own `settings` name. A
   campaign running four arms in one process has to install each arm's
   configuration across all of them, and a module left out produces a
   half-overridden arm — a wrong answer with no error.
2. Three of the five research metrics are LLM-as-judge calls. This work
   order spends nothing, so it cannot run them, and it must not pretend
   the episodes were scored as the protocol declared.
3. RFC 09 §11.3 distinguishes a *resume* (same run id, new attempt, all
   seven preconditions re-checked) from a *repeat* (a new run) and a
   *rerun* (a new run id and directory with lineage). A loop that
   re-sealed an interrupted episode's manifest would collapse the first
   into the third.
4. A crash is the normal case for a 240-episode pass, not the exception.
   Whatever marks an episode "done" has to be the last thing written.

## Decision

A new module, `src/campaign/execute.py`, plus a `run` verb on the
existing CLI. Six decisions are load-bearing.

### 1. The loop owns the order and nothing else

`execute_campaign` does exactly this per episode, and RFC 09 §5.1 fixes
every step's position: seal the manifest into the episode directory
(where a metered provider without approval fails closed) → open W08's
durable trajectory, whose first event is `run.admitted` binding the
manifest digest → drive the policy → record the terminal → score →
write the episode's artifacts → reconcile the ledger → check the
campaign cap before the next episode. The loop computes no policy, no
score and no money of its own.

### 2. The runner, the graph probe, the scorer and the credential probe
are injected

The planner already refuses to compile a graph and says why. The
executor takes the same position for the same reason and extends it:
`GraphEpisodeRunner` is the only object in the package that installs a
settings binding across `SETTINGS_CONSUMERS` and compiles the real
graph, so a test can drive the loop's *accounting* with a scripted
runner without a graph that can be asked to time out on demand — and a
future concurrent or remote executor is a different runner rather than a
different loop.

### 3. The default scorer is free, and a judge-budgeted campaign must
supply its own

`deterministic_scorer` runs only the checks that cost nothing:
`measure_citation_resolution` and ADR 0074's groundedness check. The
primary outcome is **supported-claim precision** — of the claims the
report made, the fraction its cited sources support — which is what 07
§7's D1 actually optimizes and is computable without a model. A report
with no checkable claim is a **null metric with a reason**, not a zero:
counted in the denominator, absent from the numerator. And
`execute_campaign` refuses to run with the default scorer when the
protocol budgets judge model calls, rather than quietly scoring less
than the protocol declared.

### 4. `completion.json` is written last, and it is the only resume key

Every other episode file — the projection and its sidecar, the
trajectory copy and its sink reference, the verification lines, the
artifact index, the attempt receipt, the record, the score receipt — is
written first. A crash anywhere before the terminal receipt leaves an
episode that is *pending*, which is the truth, and RFC 09 §11.1 says so:
a process that stopped without a terminal receipt is
"interrupted/unknown, not success". "Pending" therefore means exactly
"runnable and no terminal `completion.json`", and resume is not a mode —
running a campaign twice *is* the resume.

### 5. An interrupted episode re-seals to compare, never to overwrite

When an episode directory already holds a manifest and no receipt, the
loop re-seals the episode using the stored manifest's own `created_at`
and compares digests. Equal means the configuration is unchanged and
`validate_resume` is asked for a new attempt id — same run id, same
directory, a second attempt receipt beside the first. Different means
the checkout, the settings, the prompts or the registry moved under an
interrupted run, and that is `manifest_mismatch`: refused, because a run
that cannot prove what it ran is not data.

### 6. The durable trajectory stays where ADR 0083 put it; the episode
directory keeps a copy and a reference

Events go to `outputs/trajectories/runs/<run_id>/` — one content-
addressed artifact store shared across the campaign rather than the same
briefing duplicated into 240 directories. The episode directory holds
RFC 09 §5.3's `trajectory.jsonl` plus a `trajectory-ref.json` naming the
sink, its head hash and its event count, so the two copies can be
checked against each other. `artifacts/index.json` names each artifact,
its content address and **whether the store actually holds the bytes** —
because the store may refuse a body (W11-F1), and a digest-only
reference is a fact worth recording rather than an absence. The
`durable` flag on that reference is measured from the sink, not assumed,
so an episode recorded only in memory says so.

## Alternatives considered

- **Put the loop inside `src/eval/runner.py`.** The runner is a
  sequential driver over one configuration with a timestamped output
  root, and ADR 0082's rollback story is "stop using the campaign CLI".
  Threading a campaign through it would have made the rollback a revert
  and put arm switching inside the module the nightly benchmark depends
  on. The runner is untouched by this change.
- **Compile one graph for the whole campaign and switch arms with a
  flag.** The compiled shape *is* the arm; a single graph reused across
  arms would seal four manifests against one shape, which is precisely
  the defect W11-F2 caught in the shape cache.
- **Run the judges under a zero cap and let them fail.** Three failed
  judge calls per episode is 720 provider attempts on a campaign whose
  headline claim is zero. Not running them, and saying which rubrics
  were skipped in the record, is the honest version.
- **Score every episode as a success when it produced a report.** That
  makes "the report cited nothing" and "every claim was supported" the
  same number. The null-metric bucket already exists for exactly this.
- **Write `completion.json` first and patch it.** A receipt is the one
  terminal fact; RFC 09 §5.2 says it is written exactly once. A patched
  receipt is a mutable outcome record, which is the thing the whole
  manifest design refuses.
- **Mark the full-matrix test `e2e`.** The repository pins the e2e
  tier's module and test counts as equalities in `README.md` and
  requires every `e2e`-marked module to live under `tests/e2e/`. The
  measured pass is ~16s, so it runs in the `integration` tier with a
  raised per-test timeout — following `tests/test_stage0_qualification.py`,
  which put whole-graph runs in the flat tree for the same reason, and
  keeping this evidence inside the coverage selection.

## Consequences

- **Positive**: the campaign package can now be *run*. The full 20 x 3 x
  5 development matrix executes end to end in ~16 seconds at exactly
  `$0.000000` with `llm_calls=0` on all 240 episodes, reconciling 240
  completed and 60 excluded with nothing in any other bucket, while a
  counting spy over `src.llm._get_client` and `socket.socket.connect`
  stays empty. `budget_stop_reached` has a caller; `read_outcomes`,
  `reconcile` and `summarize` see receipts the loop wrote; the resume,
  cap and admission rules are executable rather than documented.
- **Negative**: `src/campaign/` now imports `src/graph/` and the agent
  modules, and mutates their `settings` bindings for the duration of an
  episode. That is a real coupling, confined to `GraphEpisodeRunner` and
  reversed in a `finally`, and it is the cost of settings being bound
  per module. Episodes run sequentially, so a funded campaign's wall
  clock is the sum of its episodes; concurrency would multiply the
  in-flight overshoot by the concurrency and is deliberately not built.
- **Follow-ups**: the three judge rubrics still need a scorer for a
  funded run (W10/W12); `TaskArmAggregate` folds repeats by task through
  `src/eval/stats.py` but no arm-versus-arm contrast is computed here;
  and W12 remains blocked on an owner's approval record, re-verified
  prices and expert labeling time — none of which this ADR changes.
