# 0071. Pair the comparison, derive the band from the quantum, and end in a three-state decision

- **Status**: accepted
- **Date**: 2026-09-04
- **Deciders**: Phase A assurance program (WO-A09)
- **Supersedes**: [ADR 0044](0044-eval-cost-accuracy-and-regression-thresholds.md)'s
  regression-gate half (its price-table half stands)
- **Follows**: [ADR 0070](0070-eval-integrity-provenance.md) (run provenance),
  [ADR 0050](0050-eval-runner-hardening.md) (durability and the
  product/harness cost split),
  [ADR 0074](0074-deterministic-groundedness.md) (deterministic
  per-claim outcomes — §5b below answers the pairing question 0074
  deliberately left open)

## Context

ADR 0044 split the nightly gate by metric class and gave the 0-1 score
metrics a flat ±0.10 band. It was right about the class split and it was
honest about the band: it calls its thresholds "priors, not measured
spread" in its own consequences section. Two years of that band being
inoperative are now measurable.

**The band filters nothing for half the research metrics.**
`completeness` and `retrieval_recall` are both
`matched / len(expected_topics)`, and 19 of the 20 benchmark queries
declare four expected topics. So those metrics can only take the values
0, 0.25, 0.5, 0.75, 1.0 — and 0.10 sits *below* one step. One borderline
topic decision flipping is a delta of 0.25 and a guaranteed red. A gate
that fires on the smallest possible movement of the instrument is not a
filter; it is a random number generator with a changelog.

**`critic_score` is the product grading itself.** It is produced by
`src/agents/critic.py`, a component of the workflow under test, and
`critic.py` coerces an unparseable judge response to `0.0`. A parse
failure therefore arrives at the differ as a full-scale quality collapse
that is indistinguishable from a real one, on a metric the system
assigns to itself.

**`--repeats` bought nothing.** The learning lane could run three
repeats, which produced record ids `s.r1`, `s.r2`, `s.r3` that the
differ then compared *pairwise* — `r1` against `r1`. Three repeats cost
triple and yielded three single-run comparisons instead of one better
estimate. The research lane had no `--repeats` at all, while
`REPEATS_FOR_CONFIDENCE = 3` was advertised in its sibling module.

**Nothing computed a variance, an interval or an N.** `regression_diff`
compared exactly two numbers. `docs/eval.md`'s "The statistics, honestly"
already said so.

And the constraint that decides the design: **at 20 benchmark queries
and 15 learning scenarios, most single-metric moves are not separable
from noise, and no amount of arithmetic changes that.** The only
question is whether the report says so.

## Decision

### 1. Pairing is the default path, not an option

`02-STANDARDS.md` §2.3, verified against primary sources: detecting a
5-point gain against an 80% baseline needs roughly **906 items per arm
unpaired** and roughly **77 paired** under McNemar at low discordance.
`src/eval/stats.py` reproduces both numbers from their published
formulae rather than quoting them —
`unpaired_required_per_arm(baseline_rate=0.80, delta=0.05)` returns 906,
and `mcnemar_required_pairs(delta=0.05, discordance=0.05)` returns 77 —
and `tests/test_eval_stats.py` asserts them.

The 77 is Connor's formula with the power term switched off: the
smallest sample at which such a move is significant *at all*, at the
lowest discordance a 5-point difference can have. At 80% power the same
move needs 155. Both are an order of magnitude below 906, which is the
finding; presenting 77 as an 80%-power figure would not be, so the
function takes `power` explicitly and the docs state which is which.

Every comparison the differ makes is therefore over the **intersection**
of the two runs' tasks, and `paired_bootstrap_delta` estimates the mean
paired delta by resampling tasks — and, when repeats exist, repeats
within tasks.

### 2. Repeats are aggregated by task before anything is diffed

Both lanes. `aggregate_repeats` groups summary rows on the lane's
`task_field` (`query_id` on the research lane, `scenario_id` on the
learning one) and reduces each metric to the mean of its non-null
values, keeping the individual values so the bootstrap can resample
within a task. Three repeats now buy a tighter estimate of one number
instead of three separate comparisons.

The research runner gains `--repeats N`. Records gain a `record_id`
(`q`, `q.r2`, `q.r3`) beside the `query_id` that keeps naming the query.
The first repeat keeps the bare `query_id`, so a default campaign writes
exactly the filenames, summary rows and resume keys it always did, and
`CampaignShape.legacy_id_field` lets a campaign started before this ADR
resume without re-paying.

### 3. The score epsilon is derived from each metric's quantum

`score_epsilon(field, threshold, lane)` returns
`max(threshold, 1.5 x quantum)` for a metric with a declared quantum,
and `threshold` for everything else. `completeness` and
`retrieval_recall` declare 0.25 — the coarsest step any benchmark query
can take — so their band is 0.375: **one flipped topic decision passes,
two fire.** A metric with a fine denominator keeps ADR 0010's 0.10 judge
noise floor.

The quantum is declared, not inferred from the data. Inferring a
denominator from observed values guesses wrong exactly when a run is
degenerate, which is when the gate matters most.

### 4. `critic_score` is demoted from gate to diagnostic

It moves to the research lane's `informational_fields`: still diffed,
still printed, marked *(not gated)*, never able to fail a run on its
own. A product component grading its own output is not a control, and
its parse-failure `0.0` makes it actively misleading.

`citation_accuracy` still returns 1.0 for a report with zero citations,
and WO-A16 found something worse: on the repository's own e2e fixture,
which cites `arxiv:2311.05232` while the mock corpus contains
`2311.09000`, `measure_citation_accuracy` scores **1.0** where
A16's `citation_resolution_rate` scores **0.0**. The metric is not
merely imprecise; it is inverted on the failure it exists to catch.
That is a live demonstration of why it does not belong in a gate
unaccompanied — and the fix belongs to whoever owns
`src/eval/metrics.py`, not here.

This gate reads `citation_accuracy` from the summary row because that is
the only citation signal any summary row carries: ADR
[0074](0074-deterministic-groundedness.md) shipped
`src/eval/groundedness.py` as a library and deliberately did not wire it
into `runner.py`'s row. When it is wired, the honest metric becomes the
better predeclared primary metric than `faithfulness`, and this module
needs no change to read it — only `RESEARCH_LANE.primary_metric` moves.

### 5b. An unmatched claim is excluded from the test, and counted

ADR 0074's `paired_outcomes` returns `{claim_id: grounded}` keyed by a
content-derived id that is stable across arms, and left one question
open on purpose: **is a claim id present in one arm and absent from the
other discordant, or out of scope?** It moves the p-value directly —
McNemar's discordant cells *are* the test — so it is a statistical
decision and `pair_binary_outcomes` in `src/eval/stats.py` makes it.

The answer: **neither concordant nor discordant.** It is counted,
returned as `unmatched_baseline` / `unmatched_candidate`, and excluded
from the statistic.

- **Not discordant.** "Did not make the claim" is not "failed to support
  the claim". Scoring the absence as a loss punishes an arm for being
  appropriately conservative — the exact behaviour a groundedness metric
  should reward.
- **Not concordant.** That would dilute the discordant cells with items
  the arms never disagreed about, because one of them never spoke.
- **Not a silent intersection.** Intersecting quietly is the cleanest
  arithmetic and hides the case that matters most: a candidate that
  stops making a claim it used to get right is a movement worth seeing,
  and an intersection buries it in a shrinking denominator.

`n=14 comparable, 6 unmatched` is a more useful sentence than a p-value
over 14 that does not say it was 20. That is also the shape ADR 0074
chose for its own undecidable quotes — `grounded=None` with a visible
`excluded` count beside `source_coverage` — and consistency there is
worth having. The cost is stated rather than hidden: a large unmatched
count means the two arms wrote about different things, and the p-value
is then a statement about a subset whose size the caller has to read.

### 5. Rows must be comparable before they may be compared

ADR 0070 put a `provenance` block on every row so this question could be
asked. `check_comparability` refuses the comparison when the two runs
disagree on `judge_model`, `rubric_versions`, `dataset_version`, `tier`
or `mock_mode` — or when one run disagrees with itself, which a
`--resume` can produce. The CLI exits **3** and reaches no verdict.

`product_model` is deliberately not in that set: a product model change
is usually what a regression diff exists to evaluate, so it is reported
as a note. A run carrying **no** block is *unknown*, not *different* —
refusing there would turn every pre-ADR-0070 baseline into a permanent
red — so the comparison proceeds with the missing attribution stated.

### 6. The report ends in PROMOTE / HOLD / ROLLBACK, and admits its N

- **ROLLBACK** — a regression cleared its band, or the run lost records.
  Exit 1, as before.
- **PROMOTE** — no regression, on a comparison with enough paired items
  to have found one.
- **HOLD** — neither. Nothing cleared a band, and nothing here can rule
  out a move that did not.

**The safety veto is not part of this decision, and it outranks it.**
ADR [0072](0072-adversarial-safety-suite.md)'s categorical hard
violations — a secret exfiltrated, an unauthorised tool called, egress
to a non-allowlisted host — are absolute zero, and absolute zero is not
a statistical claim: no baseline, interval or sample size makes a
violation less of one. Where the two gates compose, the safety veto
evaluates **first** and is **binding** even while this statistical arm
is advisory. Nothing here can promote past it, and nothing here should
try to soften it with an interval.

`pedagogy_clean` and `pedagogy_violations` — ADR 0072's deterministic
deny-list scan — are gated by this differ's learning lane, which is what
turns "fails pytest, invisible to the campaign gate" into a metric. Both
columns, because a boolean cannot say whether an already-failing session
got worse; zero tolerance on the count, because a banned pedagogy scalar
in learner-facing copy is not run-to-run variance. A campaign predating
0072 carries `None` rather than `0`, and this differ reads that as an
absent comparison rather than a clean one — the same "never measured is
not measured-and-fine" distinction ADR 0070 made with `code_dirty`.

At 20 queries and 15 scenarios, **HOLD is the answer**, and the report
prints the arithmetic: 20 paired items against the 155 an 80%-powered
5-point test needs. It also prints `pass^k` beside every success rate,
Wilson intervals rather than Wald, and the rule of three on a clean
sweep — zero failures in 20 runs bounds the failure rate near 15%, not
at zero.

And it states, in words, that its interval is approximate: below roughly
200 datapoints the central-limit approximation **underestimates**
uncertainty, so the printed interval is narrower than the truth rather
than wider. A gate that prints a normal-approximation interval on N=20
without that sentence is printing a number that is too narrow and
letting the reader believe it.

### 7. No model call may occur inside the gate

`src/eval/stats.py` imports nothing from `src/`; `regression_diff`
imports only `provenance` and `stats`.
`tests/test_regression_diff.py` runs the whole diff with every
`src/llm.py` entry point monkeypatched to raise. Content-preserving
wrappers flip 57–100% of LLM-judge verdicts (`02-STANDARDS.md` §3.4), so
a judge inside a gate is an attack surface rather than a control.

## Alternatives considered

- **Keep one flat epsilon and raise it to 0.30.** Would stop
  `completeness` firing on one step, and would also blind
  `citation_accuracy` and `faithfulness`, whose denominators are large
  enough for 0.10 to be a real filter. The defect was a shared constant,
  not its value.
- **Infer each metric's quantum from the observed values.** Attractive
  because the denominator is visible in the data — and wrong exactly
  when it matters: a run where every query scores 0.0 or 1.0 looks
  binary, and the inferred band would be 1.5.
- **Report an interval for every metric.** Rejected on multiplicity:
  `02-STANDARDS.md` §2.3 says slices are diagnostic unless a correction
  was declared in advance, because simultaneous per-metric tests on 20
  queries produce false alarms by arithmetic. The primary metric is
  predeclared; the others get an interval only when they moved
  adversely, and are labelled diagnostic.
- **A t-interval instead of a bootstrap.** Cheaper, and it assumes a
  distribution the per-task deltas of a quantised judge metric plainly
  do not have. The bootstrap makes no such claim; neither procedure
  repeals the small-sample caveat, and the report says so.
- **The χ² McNemar as the default.** At 20 queries the discordant count
  is single digits, where χ² reports p-values that are too small. The
  exact binomial test is the default; χ² is available and is used only
  above 100 discordant pairs, where the exact test's cost stops being
  free.
- **Make an incomparable pair exit 0 with a warning.** Rejected: it
  would let a rubric bump silently green a red nightly. Exit 3 makes the
  stale baseline visible, and the fix — re-establish the baseline under
  the new configuration — is the correct workflow rather than a flag.
- **A Bayesian treatment.** `02-STANDARDS.md` §2.3 names it as the
  correct tool below a few hundred datapoints, and it is the honest
  long-run answer. It needs a prior this repository has no data to set,
  since no funded campaign has ever run (W-OD-1). Recorded as the
  follow-up; the caveat is what carries the same information today.

## Consequences

- **Positive**: the gate can distinguish one flipped judge decision from
  two. Repeats now do what repeats are for. A judge swap, a rubric bump
  or a changed benchmark stops a comparison instead of moving it. The
  report says what it cannot tell you, which is the most useful thing it
  has to say at this N.
- **Negative**: the research summary row gained two fields
  (`record_id`, `repeat`) and the research campaign's `id_field` moved
  to `record_id` — additive, with a legacy fallback, but a schema change
  nonetheless. The gate is now *less* likely to fire on a single query,
  which is the intended trade and is still a reduction in sensitivity.
  A rubric bump now fails the nightly until the baseline is
  re-established. And a green report saying HOLD reads as weaker than
  one saying "no regressions" — because it is, and it always was.
- **The duplicated Wilson interval is consolidated, without moving a
  safety number.** ADR 0072 carried its own copy of the formula,
  correctly: `stats.py` did not exist on that branch, and a safety gate
  that cannot run until another work order lands is a safety gate that
  does not run. `safety_suite.wilson_interval` now delegates here and
  keeps its own contract in the wrapper — `(0.0, 0.0)` at zero trials,
  where this module raises, and its pinned `Z_95` passed through a `z`
  escape hatch rather than round-tripped via a confidence level (the two
  differ in the last two digits, and every interval that gate prints has
  to use the same `z` for its difference interval to mean anything).
  The shared implementation writes the spread term in ADR 0072's own
  association, so the result is **bit-identical** to the copy it
  replaces over every `(successes, trials)` with `trials <= 300` — not
  merely close. ADR 0072's recorded 3/42 = 2.46%–19.01% baseline is
  unchanged, `pytest -m security` stays green, and
  `tests/test_eval_stats.py` pins both the hand-computed reference
  values and the delegation itself.
- **Follow-ups**: the numbers in every band remain **priors**, because
  no funded campaign has run on either lane (**W-OD-1**). The first
  3-repeat baseline is what turns them into measured spread. Wiring ADR
  0074's groundedness metrics into `runner.py`'s summary row — which
  invalidates every existing baseline and must land with a version note
  — is the step that lets this gate read an honest citation signal and
  move `primary_metric` off `faithfulness`. The Bayesian small-sample
  treatment is unscheduled.
