# 0082. Derive the campaign id, enumerate the whole matrix, and keep every episode in the denominator

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: Agent engineering program (P0-WO07)
- **Depends on**: ADR [0050](0050-eval-runner-hardening.md),
  ADR [0070](0070-eval-integrity-provenance.md),
  ADR [0071](0071-eval-statistics-and-gates.md),
  ADR [0076](0076-fixed-verify-repair-research-policy.md),
  ADR [0078](0078-contract-shadow-for-the-research-path.md),
  ADR [0079](0079-benchmark-registry-migration-and-parity.md)
- **Implements**: P0-WO07 in
  [`docs/agent-engineering/12-p0-work-orders.md`](../agent-engineering/12-p0-work-orders.md)
  §13

## Context

Six P0 contract packages have landed. The registry (W02/W06) can resolve
a suite into exact revisions and digests; the manifest (W03) can seal an
episode and fail chargeable admission closed; the binding (W05) can seal
a *shadow* episode from a live configuration. What none of them can do is
run an experiment: there is no object that says "these twenty cases,
these five arms, three repeats, this cap", and no artifact that says what
the answer's denominator was.

`src/eval/runner.py` is the closest thing today, and ADR 0050 and ADR
0071 already gave it the two properties that matter most — durable
per-query records and a `--repeats` flag whose repeats are independent
samples rather than resumes. But it is a *sequential runner over one
configuration*: one process, one arm, one output directory keyed by a
timestamp. It has no notion of a locked registry revision, no arm set, no
approval, and no accounting for the episodes it never attempted.

Four hazards forced the shape of this work order now:

- **A campaign that can raise its own cap is not capped.** RFC 09 §11.1
  says a campaign stopped by its budget may continue only under the same
  immutable cap, and that raising one creates a *new* campaign with
  lineage. With a hand-chosen campaign id that rule is a convention, and
  conventions are what get skipped at 2am on the night a run dies.
- **A denominator computed from the rows that exist is a lie.** The
  numerator is the episodes that produced a number; the denominator has
  to be the episodes that were *supposed to*. Work-order invariant 11
  says so, and the only way to make it true is to write the denominator
  down before anything runs.
- **Arm E does not exist and arm C did not until last week.** A campaign
  that silently planned four arms because the fifth is unimplemented
  would be reporting a different experiment than the one it declared.
- **A live campaign cannot be admitted at all today.** W05's shadow seals
  only under `USE_MOCK_DATA`, because a metered provider with no approval
  record fails admission — correctly. Something has to be able to supply
  an approval record, without that something becoming an approval
  authority.

## Decision

A new package, `src/campaign/`, wrapping the existing runner rather than
changing it. Nine decisions inside it are load-bearing.

### 1. The campaign id is derived from what defines a campaign

`derive_campaign_id` hashes the frozen `CampaignProtocol`, the W02
`CampaignLock`, and the lineage edge. RFC 09 §4 says a campaign id is new
when the protocol, arm set, task set, aggregate cap or approval scope
changes; the protocol carries every one of those, so the rule is
arithmetic rather than discipline.

Two consequences, and both are the point. Re-planning an unchanged
protocol against an unchanged registry lock lands on the same id and
therefore **resumes**. Raising a cap by one cent lands on a different id
and therefore **cannot** — `resume` re-derives the id from the request it
was given, compares it with the id on disk, and refuses with the remedy
named: create a new campaign with lineage to the old one.

### 2. The whole design matrix is enumerated, including the slots nothing will run

`cases x repeats x arms` over **all five** declared arms. Arm E is
declared `capability_missing` from `ARM_REQUIRED_CAPABILITIES` and is
never runnable; its slots enter the ledger as `excluded` with a typed
reason. So 07 §5's full v1 design reports as 20 x 3 x 5 = 300 expected,
240 planned, 60 excluded — rather than as a 240-episode experiment that
never mentions the arm it could not run.

### 3. Arm order is interleaved, predeclared, and seeded per block

07 §6 Stage 3 asks for interleaving so provider or source drift over an
evening cannot align with one arm. `block_arm_order` seeds a
`random.Random` from the campaign seed, the case id and the repeat index,
so the order is fixed before the campaign starts, recomputable from the
manifest for any single block, and different across blocks.

### 4. Identity is derived; the replicate group is keyed on the arm *declaration*

`replicate_group_id` = `sha256(campaign, task ref, arm declaration)`,
`episode_key` adds the repeat index, `run_id` = `sha256(episode key,
rerun generation)`. The group is keyed on the arm's declared settings
rather than on its compiled `PolicySnapshot`, because a group has to be
nameable before a graph exists — the plan is written first. The compiled
graph is checked against the declaration at *seal* time instead, which is
the stronger ordering: a plan cannot claim a capability, and a seal
cannot proceed without one.

A repeat is a new run in the same group. A resume recomputes the same run
id and appends an attempt (W03's `validate_resume`). A rerun takes the
next generation, a new run id, a new directory, and `RunLineage`.

### 5. One TaskSpec per case, compiled once and persisted

Compiled under the campaign's *ceiling* configuration — the most
permissive arm's flags — so the spec owns maximum permissions and each
arm's effective policy is narrower or equal, which the admission
controller proves at every seal. It is written to `task-set.json` and
pinned by digest in the campaign manifest, and `resume` **loads** it
rather than recompiling: `task_spec_id` is a digest over the whole spec
including its compilation timestamp, so a recompiled spec would derive a
different replicate group and land the resumed campaign in a different
set of directories.

### 6. The ledger is written before the first episode and only ever folds outcomes in

`open_ledger` writes one entry per declared slot before anything runs.
`reconcile` may move an entry from `not_started` to `completed`,
`errored`, `cancelled`, `timed_out`, `budget_stopped` or `null_metric` —
and to nothing else. `DenominatorReport` refuses to be constructed if the
accounted total is not the expected total, so a lost episode is a
validation error rather than a smaller denominator. Two numbers are
reported: `expected` (every slot) and `analysis_denominator` (`expected`
minus declared exclusions). Failures, timeouts, cancellations, budget
stops and null metrics stay in both.

`TIMEOUT` is separated from the other failures deliberately: "the policy
produced a wrong answer" and "the harness ran out of wall clock" are
different findings, and collapsing them hides an infrastructure problem
inside a quality number.

### 7. Approval is read, never minted; credentials are read after it, never before

`LocalApprovalRecordBackend` satisfies W03's `ApprovalBackend` by
delegating every check to `FakeLocalApprovalBackend`, and adds only what
a campaign needs: loading records from a file an operator controls, and
counting verifications. `resolve_admission` calls the backend first and
the credential probe second, so "rejected before credential lookup" is a
property of the call graph. `SettingsCredentialProbe` refuses the
repository's disabled placeholder explicitly — a truthy key that cannot
pay must not make a zero-spend checkout look authorized.

This is what unblocks a metered provider in a *test*. It changes nothing
about authorization: a live campaign still requires the owner's D9
approval, recorded outside this repository, and **P0-WO12 remains
blocked**.

### 8. Snapshot and live are different experiments

The corpus mode is a campaign-level field. `_assert_corpus_mode` refuses
to seal an episode whose settings resolve to live retrieval under a
campaign declared `snapshot`, and `assert_aggregatable` refuses to
combine two summaries that disagree on corpus mode or on registry lock.
07 §6 Stage 4 says the live sweep is separately reported; this is what
makes that stick.

### 9. Costs split three ways; statistics are delegated

`CostCategories` reports workflow, judge and harness spend separately —
ADR 0050's split, plus a third category for paid tools and
infrastructure that is zero here and reported rather than folded into the
other two. Repeat aggregation, McNemar, the required-pairs figure and the
small-sample caveat all come from `src/eval/stats.py`; nothing is
reimplemented.

## Alternatives considered

- **A random campaign id, with the cap rule enforced by review** — the
  RFC's own recommended form. Rejected because it makes the most
  dangerous operation (spending more than was approved) a matter of
  remembering, and because it makes a legitimate resume harder than an
  illegitimate one: an operator who has lost the id has to grep a
  directory listing, while one who wants a bigger cap only has to not
  create a new campaign.
- **Planning only the runnable arms** — smaller matrix, simpler code.
  Rejected: the denominator would then describe the experiment we could
  run rather than the one we declared, and the reader of a scorecard
  would have no way to see that a fifth arm was dropped.
- **Compiling a graph per arm inside the planner** to resolve arm
  capability at plan time. Rejected because `build_workflow` reads the
  process-global settings singleton, so probing five arms would mean
  mutating that singleton five times inside a planner. The graph probe is
  injected instead, arms are `unverified` when none is supplied, and
  capability is proved at seal time by the process that actually has a
  compiled graph. (`shadow_bridge.graph_shape` is additionally unsafe for
  this: its cache key omits `research_policy`, so arms B and C would
  share a cached shape.)
- **Extending `src/eval/runner.py` in place** with campaign flags.
  Rejected under the work order's own rollback rule: the sequential
  runner must stay callable and byte-identical, and a campaign that
  wrote into `outputs/eval/<timestamp>/` could not be rolled back by
  simply not using it.
- **Recompiling TaskSpecs on resume** instead of persisting them.
  Rejected: it changes every derived identity, which is the one thing a
  resume must not do.
- **Reimplementing the statistics inside the campaign summary** so the
  package has no `src/eval` dependency. Rejected: a second confidence
  interval is a second set of assumptions, and they will diverge.

## Consequences

- **Positive**: a campaign is now an object with an identity, a locked
  registry revision, a written-down denominator and an approval story.
  W11 can produce its Stage-0 qualification report from
  `python -m src.campaign dry-run` output without running anything, and
  W12's approval packet can name an exact matrix and cap.
- **Positive**: the episode manifests a campaign seals fill in the four
  sections W05 recorded as `unresolved` — the campaign id, the lock ref,
  the registry resolution and the budgets.
- **Negative**: arms are `unverified` at plan time. A campaign directory
  written by `plan` does not yet prove that arm C is runnable in this
  checkout; the proof arrives when the first arm-C episode seals, and
  refuses the episode if it does not.
- **Negative**: the campaign layout is a second output root beside
  `outputs/eval/`. Two places to look until a later work order decides
  which is authoritative.
- **Negative**: `harness_usd` is a parameter that nothing currently
  populates. It is reported as zero rather than omitted, which is the
  honest shape but is also a field with no producer yet.
- **Follow-ups**: W08 owns writing trajectories and artifacts into the
  episode directories this package creates; W11 consumes the dry-run
  plan and the ledger; W12 stays blocked on D9. Executing a planned
  campaign — the loop that invokes the runner once per episode — is
  deliberately not in this work order: it needs W08's event bridge to
  produce the receipts the ledger reconciles.
