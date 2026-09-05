"""Regression diff for eval runs.

Given two `summary.jsonl` files (baseline + current), produce a
markdown diff and exit non-zero if any metric regressed on any query.
Wired into the nightly CI workflow (see
`.github/workflows/eval-nightly.yml`) so a real quality regression on
`main` fails the run and pages the maintainer.

Metrics are judged by class, not by one scalar (ADR 0044, revisiting
ADR 0010's single global threshold):

- **Score metrics** (0-1 LLM-judge outputs) regress on an absolute
  drop larger than `--threshold` (default 0.10 — typical judge noise
  per ADR 0010).
- **Resource metrics** (`iterations`, `llm_calls`, `cost_usd`) regress
  only when the increase clears BOTH a per-metric absolute floor and a
  relative band (`RESOURCE_THRESHOLDS`). One extra critic revision or
  a $0.02 cost wiggle is ordinary run-to-run variance and must not
  fail the nightly; the floors are sized so it can't.

Both classes stay direction-aware: cost going down is an improvement,
a score going up is an improvement.

A query that the baseline has and the current run does not is also a
regression (ADR 0050): the usual cause is a truncated batch, and the
aggregate below it re-averages over the survivors, so "no regressions"
on a shrunken denominator is the most dangerous kind of green.
`--allow-removed` opts a deliberate subset run out.

The report also names any metric the current run stopped scoring (a
judge failure leaves it `null` since ADR 0050, which makes its delta
`None` and its query read `unchanged`). That is reported, not gated —
a flaky judge is a harness fault, not a product regression — but it is
never silent, because a mean over two of twenty queries must not print
like a mean over twenty.

Since ADR 0050 the runner reports `cost_usd` / `llm_calls` /
`elapsed_sec` as *workflow* figures with the eval judges' own spend
split into separate fields, so the resource bands below now gate the
product rather than the harness. Summaries produced before that ADR
conflate the two and read a few percent high on cost.

**Two lanes** (WO-W11). The research campaign
(`src/eval/runner.py`) and the guided-read campaign
(`src/eval/simulate_learner.py`) write different fields into different
`summary.jsonl` files, so the differ carries one `MetricLane` per
campaign: its id field, its metric set, its thresholds, its report
vocabulary.

**Statistics, and a three-state decision** (ADR 0071, superseding ADR
0044's bands). Four things changed:

- **Repeats are aggregated by task before anything is diffed**, on both
  lanes. Three runs of one query are three observations of that query,
  not three queries; comparing `r1` to `r1` cost triple and bought
  nothing.
- **The comparison is paired** — the baseline and the candidate are
  scored on the same tasks, and `src/eval/stats.py` estimates the mean
  paired delta with a hierarchical bootstrap that resamples tasks, and
  repeats within tasks. Pairing is worth an order of magnitude of
  sample size, which at 20 queries is the difference between a gate
  that can measure something and one that cannot.
- **The score epsilon is derived from each metric's quantum** instead
  of one shared 0.10. `completeness` and `retrieval_recall` move in
  steps of `1/len(expected_topics)`, so a flat 0.10 filtered nothing
  for them and one flipped topic decision was a guaranteed red.
- **The report ends in PROMOTE / HOLD / ROLLBACK**, and says plainly
  when N is too small to separate a move from noise. At this
  repository's N that is usually the answer, and printing it is the
  point: an honest gate that says "cannot distinguish" is worth more
  than a confident one that cannot.

**No model call happens anywhere in this module.** A judge inside a
gate is an attack surface, not a control — content-preserving wrappers
flip 57-100% of LLM-judge verdicts. `tests/test_regression_diff.py`
holds that as an assertion, not as an intention.

**Rows must be comparable before they may be compared.** Since ADR 0070
every summary row carries a `provenance` block. When the two runs
disagree on the *instrument* — judge model, rubric versions, dataset
fingerprint, tier, mock mode — this module refuses the comparison and
exits 3 rather than reporting a movement that is really a
reconfiguration. A run that carries no block at all is unknown rather
than incomparable: it is compared, with a warning.

That machinery is what carries the citation-metric swap. The research
lane gates on `citation_resolution_rate` (ADR 0074) rather than
`citation_accuracy`, which returned 1.0 for a report with zero
citations; a row scored before the swap and one scored after disagree on
`provenance.rubric_versions`, so this module refuses them as
incomparable instead of diffing a metric against a different metric.

Usage:
    python -m src.eval.regression_diff baseline.jsonl current.jsonl
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --threshold 0.05
    python -m src.eval.regression_diff baseline.jsonl current.jsonl --output diff.md
    python -m src.eval.regression_diff baseline.jsonl subset.jsonl --allow-removed
    python -m src.eval.regression_diff base.jsonl cur.jsonl --lane learning

Exit codes:
    0 — PROMOTE or HOLD: no regression was established
    1 — ROLLBACK: one or more regressions detected
    2 — invalid input (missing current file, bad JSONL)
    3 — the two runs are not comparable; no verdict was reached
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from statistics import fmean
from typing import Any, Final, Literal, NamedTuple, TypedDict

from src.eval.provenance import PROVENANCE_KEY
from src.eval.stats import (
    BootstrapResult,
    Interval,
    McNemarResult,
    PairedSample,
    mcnemar,
    mcnemar_required_pairs,
    paired_bootstrap_delta,
    pass_hat_k,
    power_statement,
    rule_of_three,
    small_sample_caveat,
    wilson_interval,
)

# Absolute epsilon floor for the 0-1 score metrics only — resource
# metrics below have their own bands, and a metric with a declared
# quantum gets a wider band still (`score_epsilon`). 0.10 is ADR 0010's
# estimate of typical LLM-as-judge noise on a single run.
DEFAULT_THRESHOLD = 0.10

# Exit statuses. `main()` returns exactly one; the docstring above is
# the operator-facing copy.
EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_INVALID = 2
EXIT_INCOMPARABLE = 3

# Quantisation step of the metrics whose score is a ratio over a small
# hand-declared denominator. `completeness` and `retrieval_recall` are
# both `matched / len(expected_topics)`, and 19 of the 20 benchmark
# queries declare four topics (one declares five), so the coarsest step
# a single query can take is 0.25 — the value used here, because a band
# has to survive the coarsest query it will meet, not the average one.
#
# Declared rather than inferred from the data: inferring a denominator
# from observed values guesses wrong exactly when a run is degenerate
# (every query scoring 0.0 or 1.0), which is when the gate matters
# most. When a query's topic list changes, this constant is what has to
# move, and `tests/test_regression_diff.py` pins it against the
# dataset.
# `citation_resolution_rate` is deliberately **not** here, and the
# reasoning is the same one the learning lane already applies to its
# observed rates (`LEARNING_LANE.score_quanta`, empty for the same
# cause). Its quantum is `1 / denominator`, and unlike `completeness`
# that denominator is not declared by the dataset — it is the number of
# identifiers the report itself cited, which the run chooses. It is 1 on
# this repository's own e2e fixture, and a declared quantum has to
# survive the coarsest case it will meet, so declaring one would mean
# declaring 1.0 and handing the metric a band of 1.5: a gate that can
# never fire.
#
# The widening rule also has no purchase here. `score_epsilon`'s wider
# band exists to absorb *judge* noise (ADR 0044, revisiting ADR 0010),
# and this check has no judge: given a report and a corpus it returns
# the same number forever. What is left to filter is product variance,
# which the flat `--threshold` floor already does — see `score_epsilon`.
SCORE_QUANTA: dict[str, float] = {
    "completeness": 0.25,
    "retrieval_recall": 0.25,
}

# How many quanta a quantised metric must move before the gate calls it
# a regression. Strictly between 1 and 2 so that one flipped judge
# decision passes and two do not — which is the whole defect ADR 0044's
# flat 0.10 left open, since 0.10 sits *below* one step and therefore
# fired on every single flip.
#
# 1.5 rather than 1.01: the band is compared against a *task* delta, and
# a task whose repeats were aggregated can move by a fraction of a step,
# so the midpoint keeps the rule "one step is noise, two steps are a
# regression" true for both a single run and an aggregate.
QUANTUM_TOLERANCE: Final[float] = 1.5

# Provenance fields whose disagreement between the two runs makes a
# comparison meaningless, because the *instrument* moved rather than the
# thing being measured (ADR 0070, ADR 0071).
#
# `product_model` is deliberately absent: a product model change is
# exactly what a regression diff exists to evaluate, so it is reported
# as context, never as a refusal. `code_commit` and `seed` differ by
# construction. `harness_version` is absent because an additive schema
# bump leaves every field this module reads in place, and a removal is
# already forbidden by ADR 0070.
COMPARABILITY_FIELDS: Final[tuple[str, ...]] = (
    "judge_model",
    "rubric_versions",
    "dataset_version",
    "tier",
    "mock_mode",
)

# Reserved keys on an aggregated task row. Underscore-prefixed because
# no `summary.jsonl` field is, so they cannot collide with a metric a
# lane adds later; they carry the repeat structure that a mean throws
# away and the bootstrap needs back.
REPEAT_VALUES_KEY: Final[str] = "_repeat_values"
REPEAT_COUNT_KEY: Final[str] = "_repeats"
ERRORED_REPEATS_KEY: Final[str] = "_errored_repeats"
PROVENANCE_BLOCKS_KEY: Final[str] = "_provenance_blocks"

# The effect the power statement is written about: a 5-point move
# against an 80% baseline. Not a threshold anything is gated on — it is
# the yardstick `02-STANDARDS.md` §2.3's 77-versus-906 finding is
# quoted at, and printing the gate's own N against it is what turns
# "the sample is small" into a number.
GATE_EFFECT_SIZE: Final[float] = 0.05
GATE_BASELINE_RATE: Final[float] = 0.80

# Bootstrap seed used when a caller does not pick one. Fixed rather than
# drawn so two runs of the differ over the same summaries produce the
# same interval — a gate whose verdict moves when nothing moved is not a
# gate.
DEFAULT_SEED: Final[int] = 0

# Metrics that gate the research lane. Kept as a tuple so ordering in
# the report is stable.
#
# `critic_score` was removed from this list by ADR 0071 and moved to
# `RESEARCH_INFORMATIONAL_FIELDS`. Two reasons, and the second is the
# one that forced it: the critic is a component of the product grading
# its own output, so gating on it lets the system decide whether it
# regressed; and `critic.py` coerces an unparseable judge response to
# `0.0`, which arrives at this module as a full-scale quality collapse
# indistinguishable from a real one. It is still diffed and still
# printed — as a diagnostic.
# `citation_accuracy` was removed from this list by ADR 0074 and moved
# to `RESEARCH_INFORMATIONAL_FIELDS`, replaced by
# `citation_resolution_rate`. It is not that the old metric was
# imprecise — it is inverted: it returns 1.0 for a report with zero
# citations, and it resolves `[Author, Year]` tags against the citation
# list the synthesizer itself wrote, so a fabricated entry validates
# itself. On this repository's e2e fixture, where the report cites
# `arxiv:2311.05232` and the retrieved corpus holds `2311.09000`, it
# scores 1.0; `citation_resolution_rate` scores 0.0 over a denominator
# of 1. The field stays on the row and stays in the report — ADR 0070
# forbids removing one — but it no longer decides anything.
METRIC_FIELDS: tuple[str, ...] = (
    "citation_resolution_rate",
    "completeness",
    "faithfulness",
    "retrieval_recall",
    "iterations",
    "llm_calls",
    "cost_usd",
)

# Research-lane fields that are tabulated but never gate. See the notes
# on `critic_score` and `citation_accuracy` above.
RESEARCH_INFORMATIONAL_FIELDS: tuple[str, ...] = (
    "citation_accuracy",
    "critic_score",
)

# Per-metric bands for the count / dollar metrics: (absolute_floor,
# relative_fraction). A move counts as significant only when it
# exceeds BOTH — the floor stops penny/single-unit wiggles on small
# baselines, the relative band stops "large baseline, proportionally
# tiny drift" from firing. Rationale (ADR 0044):
#
# - `iterations` moves in steps of 1 and the critic asking for one
#   extra revision is ordinary nondeterminism. Floor 1.0 means a +1
#   never fires; +2 with a >50% relative rise does.
# - `llm_calls`: one critic revision adds ~2-3 calls (re-synthesize,
#   re-critique, re-verify) and one extra rankable paper adds 1 reader
#   call. Floor 4.0 absorbs a single ordinary event; 25% catches call
#   count runaway on any realistic baseline (~12-45 calls).
# - `cost_usd`: floor $0.10 so a $0.02 wiggle never fires; 25%
#   matches the documented "cost creep > 25%" gate in the README.
#
# These are priors, not measured spread — nothing in src/eval computes
# run-to-run variance yet. Re-derive them from a 3-repeat baseline
# once we have one (docs/eval.md).
RESOURCE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "iterations": (1.0, 0.50),
    "llm_calls": (4.0, 0.25),
    "cost_usd": (0.10, 0.25),
}

# Direction each metric should move for "improvement". Quality metrics
# get better as they rise; cost / iteration / call-count metrics get
# better as they fall. Anything not listed defaults to "higher_better"
# so we don't silently mistreat a new field.
METRIC_DIRECTIONS: dict[str, str] = {
    "citation_resolution_rate": "higher_better",
    "citation_accuracy": "higher_better",
    "completeness": "higher_better",
    "faithfulness": "higher_better",
    "retrieval_recall": "higher_better",
    "critic_score": "higher_better",
    "iterations": "lower_better",
    "llm_calls": "lower_better",
    "cost_usd": "lower_better",
}


# ---------------------------------------------------------------------------
# Lanes
#
# One campaign, one lane. Everything that differs between the research
# runner's summaries and the learner simulator's — the id field, the
# metric set, the bands, the words the report uses for its unit — lives
# in a `MetricLane` so the diff logic itself stays single-copy. The
# research lane is assembled from the module-level constants above, so
# `--lane research` output is byte-for-byte what it was before this
# structure existed.
# ---------------------------------------------------------------------------


class CostReference(NamedTuple):
    """A per-unit cost range quoted from a planning document.

    Rendered as a clearly-labelled row beside the measured means. It is
    a **prior from a plan**, never a measurement: the whole point of
    printing it is to let a reader see how far the campaign's real cost
    sits from what the plan assumed, and a row that could be mistaken
    for data would defeat that.

    Attributes:
        field: Metric field the estimate is about.
        low: Low end of the planned range, in USD.
        high: High end of the planned range, in USD.
        source: Human-readable citation for the estimate.
    """

    field: str
    low: float
    high: float
    source: str


class MetricLane(NamedTuple):
    """One campaign's field set, thresholds and report vocabulary.

    Attributes:
        name: CLI name (`--lane <name>`).
        id_field: Summary-line key that identifies a *record* — one run
            of one task. On a campaign with repeats, several records
            share a task.
        unit_singular: What one record is ("query", "session").
        unit_plural: Plural of the same.
        title: H1 of the rendered report.
        metric_fields: Fields that are diffed **and** gate the run.
        informational_fields: Fields that are tabulated but never gate.
            Harness spend lives here: ADR 0050's split says the gate
            reads the product, and a judge that got more expensive is
            not a product regression. So does `critic_score`, which ADR
            0071 demoted.
        resource_thresholds: Per-metric `(absolute_floor, relative)`
            bands. A field listed here is judged on both legs; a field
            absent from it is judged on the score epsilon.
        directions: Per-metric `higher_better` / `lower_better`.
        columns: `(header, field)` pairs for the per-record table, in
            render order.
        cost_reference: Optional planned-cost row, or `None`.
        task_field: Summary-line key naming the *task* a record scored —
            the benchmark query, the scenario. Repeats of one task share
            it, and it is the unit repeats are aggregated over and the
            unit the bootstrap resamples, because the query is what is
            independent, not the run. Defaults to `id_field` for a lane
            whose records are its tasks.
        score_quanta: Per-metric quantisation step, for metrics whose
            score is a ratio over a small declared denominator. Absent
            means "continuous enough for the flat epsilon".
        primary_metric: The metric predeclared as the comparison's
            subject. Its interval is always computed; every other
            metric's is diagnostic, because twenty per-metric tests on
            twenty queries manufacture false alarms by arithmetic
            (`02-STANDARDS.md` §2.3).
    """

    name: str
    id_field: str
    unit_singular: str
    unit_plural: str
    title: str
    metric_fields: tuple[str, ...]
    informational_fields: tuple[str, ...]
    resource_thresholds: dict[str, tuple[float, float]]
    directions: dict[str, str]
    columns: tuple[tuple[str, str], ...]
    cost_reference: CostReference | None
    task_field: str = ""
    score_quanta: dict[str, float] = {}  # noqa: RUF012 — frozen by NamedTuple
    primary_metric: str = ""

    @property
    def tabulated_fields(self) -> tuple[str, ...]:
        """Every field the report carries: gated ones first, then the rest."""
        return self.metric_fields + self.informational_fields

    @property
    def group_field(self) -> str:
        """The key repeats are aggregated on — `task_field` or the id."""
        return self.task_field or self.id_field


RESEARCH_LANE = MetricLane(
    name="research",
    id_field="query_id",
    unit_singular="query",
    unit_plural="queries",
    title="Eval regression diff",
    metric_fields=METRIC_FIELDS,
    informational_fields=RESEARCH_INFORMATIONAL_FIELDS,
    resource_thresholds=RESOURCE_THRESHOLDS,
    directions=METRIC_DIRECTIONS,
    columns=(
        ("Cit.Res. Δ", "citation_resolution_rate"),
        ("Cit.Acc. Δ", "citation_accuracy"),
        ("Complete. Δ", "completeness"),
        ("Faithful. Δ", "faithfulness"),
        ("Recall Δ", "retrieval_recall"),
        ("Critic Δ", "critic_score"),
        ("Iter Δ", "iterations"),
        ("Calls Δ", "llm_calls"),
        ("$ Δ", "cost_usd"),
    ),
    cost_reference=None,
    # A research record *is* its query: `--repeats` gives repeats of one
    # query the record ids `q`, `q.r2`, `q.r3` while leaving `query_id`
    # naming the query on all three, so the summary rows group on it
    # without the differ having to parse an id.
    task_field="query_id",
    score_quanta=SCORE_QUANTA,
    # Predeclared, and this is the hand-off ADR 0071 wrote down rather
    # than pre-empting: `faithfulness` held the slot while the only
    # citation signal was the judged one, and the citation metric was
    # named as "the better long-run choice once WO-A16's deterministic
    # groundedness replaces the judged version". That happened here, so
    # the slot moves.
    #
    # Why it is better: the primary metric is the one whose interval is
    # always computed and whose movement can HOLD a promotion, so it
    # should be the least arguable number in the report.
    # `citation_resolution_rate` is deterministic, costs nothing, does
    # not drift when a model is upgraded, and yields a per-claim binary
    # outcome McNemar can pair on. `faithfulness` is a judge whose
    # agreement with a human has never been measured in this repository
    # — it still gates, and still gets a diagnostic interval whenever it
    # moves adversely.
    #
    # What it costs: a run that cited nothing scores `None` rather than
    # a number, so it leaves the primary's paired sample instead of
    # contributing a 1.0 to it. `_decide` refuses to reach a verdict
    # when that empties the sample entirely, rather than passing a
    # campaign nobody measured.
    primary_metric="citation_resolution_rate",
)

# The guided-read campaign's fields, from
# `simulate_learner.summary_line`. Three classes, and the class is what
# decides the rule (ADR 0044):
#
# - **Rubric scores** — `shame_free_score`, `plan_coherence` — are 0-1
#   LLM-judge outputs and take the flat score threshold, exactly as the
#   research judges do.
# - **Deterministic outcome rates** — `shame_free`,
#   `downscope_honest`, `progress_events_evidence_linked`,
#   `injection_contained` — are booleans per session. `_score` reads a
#   bool as 1.0/0.0 (Python's `bool` is an `int`), so a per-session
#   True→False flip is a delta of -1.0 and the aggregate is the *rate*
#   over the campaign. They therefore also sit on the threshold leg,
#   where any flip clears any sane epsilon. That is intended: these are
#   not judged, they are observed, and one session that stopped
#   containing an injection is a regression at any threshold.
# - **Resource metrics** — `expectation_failures`, `llm_calls`,
#   `cost_usd` — take two-leg bands, below.
LEARNING_METRIC_FIELDS: tuple[str, ...] = (
    "shame_free",
    "shame_free_score",
    # ADR 0072's deterministic pedagogy scan, which `simulate_learner`
    # writes and nothing read: the deny-list failed pytest and was
    # invisible to the campaign gate. Two columns because they answer
    # different questions — `pedagogy_clean` is the per-session boolean
    # a gate reads, and `pedagogy_violations` is the count that says
    # whether an already-failing session got worse.
    #
    # A campaign written before ADR 0072 carries neither, which reads
    # here as an absent field: delta `None`, no gate effect, and the
    # `Compared` column says `0 / N`. That is the correct answer —
    # `simulate_learner` distinguishes "never scanned" (`None`) from
    # "scanned and clean" (`0`), and this differ must not collapse them.
    "pedagogy_clean",
    "pedagogy_violations",
    "downscope_honest",
    "plan_coherence",
    "progress_events_evidence_linked",
    "injection_contained",
    "expectation_failures",
    "llm_calls",
    "cost_usd",
)

# Harness spend. Tabulated so a campaign's total is legible, never
# gated: ADR 0050's rule is that the gate reads the product, and the
# judges and the simulated learner are both rig.
LEARNING_INFORMATIONAL_FIELDS: tuple[str, ...] = (
    "learner_cost_usd",
    "judge_cost_usd",
    "total_cost_usd",
)

# Two-leg bands for the learning lane's count / dollar metrics.
# Rationale, in the same shape as `RESOURCE_THRESHOLDS`:
#
# - `expectation_failures` counts WO-W08 structural expectations a
#   session stopped meeting. Zero tolerance is deliberate: `(0.0, 0.0)`
#   means a rise of one fires and a rise of zero does not. It is listed
#   here rather than left to the score epsilon so that every
#   `lower_better` field in this lane has an explicit, reviewed band —
#   the invariant ADR 0044 exists to protect.
# - `llm_calls` is the session graph's own call count. A session makes
#   roughly 4-8 calls (check-in, tutor turns, assessment); floor 2.0
#   absorbs one extra tutor turn, 25% catches a routing loop.
# - `cost_usd` is the per-session product cost. `01` §6.1 estimates
#   $0.07-0.17 a session, so the research lane's $0.10 floor would be
#   most of a whole session and a 50% cost rise could never fire.
#   $0.05 still swallows penny-level wiggles at this scale; the 25%
#   relative leg is the research lane's, unchanged.
#
# Priors, like every other threshold in this file — no funded learning
# campaign has run (W-OD-1), so nothing here is measured spread.
LEARNING_RESOURCE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "expectation_failures": (0.0, 0.0),
    # Same zero tolerance, and for the same reason: a banned pedagogy
    # scalar reaching learner-facing copy is not variance. `(0.0, 0.0)`
    # means one extra hit fires and zero extra does not.
    "pedagogy_violations": (0.0, 0.0),
    "llm_calls": (2.0, 0.25),
    "cost_usd": (0.05, 0.25),
}

LEARNING_METRIC_DIRECTIONS: dict[str, str] = {
    "shame_free": "higher_better",
    "shame_free_score": "higher_better",
    "pedagogy_clean": "higher_better",
    "pedagogy_violations": "lower_better",
    "downscope_honest": "higher_better",
    "plan_coherence": "higher_better",
    "progress_events_evidence_linked": "higher_better",
    "injection_contained": "higher_better",
    "expectation_failures": "lower_better",
    "llm_calls": "lower_better",
    "cost_usd": "lower_better",
}

LEARNING_LANE = MetricLane(
    name="learning",
    id_field="record_id",
    unit_singular="session",
    unit_plural="sessions",
    title="Learning-eval regression diff",
    metric_fields=LEARNING_METRIC_FIELDS,
    informational_fields=LEARNING_INFORMATIONAL_FIELDS,
    resource_thresholds=LEARNING_RESOURCE_THRESHOLDS,
    directions=LEARNING_METRIC_DIRECTIONS,
    columns=(
        ("Shame-free Δ", "shame_free"),
        ("Shame rubric Δ", "shame_free_score"),
        ("Pedagogy Δ", "pedagogy_clean"),
        ("Pedagogy hits Δ", "pedagogy_violations"),
        ("Downscope Δ", "downscope_honest"),
        ("Plan coherence Δ", "plan_coherence"),
        ("Evidence Δ", "progress_events_evidence_linked"),
        ("Injection Δ", "injection_contained"),
        ("Unmet Δ", "expectation_failures"),
        ("Calls Δ", "llm_calls"),
        ("$ Δ", "cost_usd"),
    ),
    # The learning lane's records are `<scenario>.rN`, so the task is
    # named by its own column rather than parsed back out of the id.
    task_field="scenario_id",
    # Empty on purpose. The learning lane's coarse metrics are the
    # per-session booleans, whose quantum is 1.0 — deriving a band from
    # that would give them an epsilon of 1.5 and make them ungatable.
    # They are *observed*, not judged, and one session that stopped
    # containing an injection is a regression at any epsilon, so they
    # keep the flat threshold they have always had.
    score_quanta={},
    # Predeclared: the pedagogy outcome is what the guided-read product
    # claims, it is deterministic rather than judged, and it is binary
    # per session — which makes it the one metric on either lane that
    # McNemar can be run on directly.
    primary_metric="shame_free",
    cost_reference=CostReference(
        field="cost_usd",
        low=0.07,
        high=0.17,
        source=(
            "planning/07-learning-platform/01-LEARNING-AGENT.md §6.1, "
            '"Session online total"'
        ),
    ),
)

#: Selectable lanes, by `--lane` name.
LANES: dict[str, MetricLane] = {
    RESEARCH_LANE.name: RESEARCH_LANE,
    LEARNING_LANE.name: LEARNING_LANE,
}


class QueryDiff(TypedDict):
    """Per-record diff between baseline and current runs.

    `query_id` holds whatever the lane's `id_field` names — a benchmark
    query id on the research lane, a `<scenario>.rN` record id on the
    learning one. The key keeps its original name because it is the
    diff's identity slot, and renaming it would break every existing
    consumer of a research report for no gain.
    """

    query_id: str
    status: str  # "unchanged" | "regressed" | "improved" | "new" | "removed" | "errored" | "recovered"
    baseline_error: str | None
    current_error: str | None
    deltas: dict[str, float | None]  # metric_field -> current - baseline


class Comparability(NamedTuple):
    """Whether two campaigns' provenance permits comparing them at all.

    Attributes:
        comparable: False when the two runs disagree on a
            `COMPARABILITY_FIELDS` value, or when one run disagrees with
            itself. Either way the instrument moved, and a delta
            measured across it describes the reconfiguration rather than
            the product.
        conflicts: Human-readable descriptions of each disagreement.
        notes: Things worth saying that are not refusals — a run with no
            provenance block at all, a dirty working tree, a product
            model that moved (which is what a comparison is *for*).
    """

    comparable: bool
    conflicts: tuple[str, ...]
    notes: tuple[str, ...]


class MetricStatistics(NamedTuple):
    """The statistical view of one metric's paired comparison.

    Attributes:
        field: Metric name.
        bootstrap: Paired bootstrap over tasks, or `None` when fewer
            than one task carried the metric in both runs.
        mcnemar: McNemar's test, present only when the metric is binary
            on every paired task in both runs — the case pairing was
            built for, and the form WO-A16's per-claim groundedness
            outcomes will arrive in.
        epsilon: The band this metric had to clear to gate.
        primary: Whether this is the lane's predeclared metric. Every
            other row is diagnostic and uncorrected for multiplicity.
    """

    field: str
    bootstrap: BootstrapResult | None
    mcnemar: McNemarResult | None
    epsilon: float
    primary: bool


class Reliability(NamedTuple):
    """A binary success rate over tasks, with what it supports.

    Attributes:
        label: What succeeded, for the report's row.
        successes: Tasks that succeeded.
        tasks: Tasks scored.
        interval: Wilson interval for the rate.
        pass_k: `pass^k` across repeats, or `None` at one repeat where
            it is the rate itself.
        repeats: The `k` in `pass^k`.
    """

    label: str
    successes: int
    tasks: int
    interval: Interval
    pass_k: float | None
    repeats: int

    @property
    def rate(self) -> float:
        """Observed success rate."""
        return self.successes / self.tasks if self.tasks else 0.0


class Decision(NamedTuple):
    """The gate's three-state verdict.

    Attributes:
        verdict: `PROMOTE` — no regression, and the comparison had
            enough paired items to have found one. `ROLLBACK` — a
            regression cleared its band, or the run lost records.
            `HOLD` — everything else, and at this repository's N that is
            usually the honest answer: no regression was seen, and this
            comparison could not have seen one.
        reasons: Why, in the order they were decided.
    """

    verdict: Literal["PROMOTE", "HOLD", "ROLLBACK"]
    reasons: tuple[str, ...]


class RegressionReport(TypedDict):
    """Aggregate diff over two eval runs."""

    diffs: list[QueryDiff]
    has_regressions: bool
    lane: MetricLane
    threshold: float
    allow_removed: bool
    unscored: dict[str, int]
    aggregate_baseline: dict[str, float | None]
    aggregate_current: dict[str, float | None]
    aggregate_deltas: dict[str, float | None]
    comparability: Comparability
    statistics: dict[str, MetricStatistics]
    reliability: list[Reliability]
    decision: Decision
    paired_tasks: int
    repeats: int


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_rows(
    path: Path, *, lane: MetricLane = RESEARCH_LANE
) -> list[dict[str, Any]]:
    """Read a `summary.jsonl` file into its rows, in file order.

    One row per *record*: a campaign run with `--repeats 3` yields three
    rows per task. Aggregating them is `aggregate_repeats`' job, and it
    is deliberately a separate step — the raw rows are what the
    provenance check has to read, because a campaign whose repeats were
    produced by two different judges is exactly the thing a mean would
    hide.

    Args:
        path: The summary file. A missing file reads as empty.
        lane: Which campaign wrote it — the research lane keys on
            `query_id`, the learning lane on `record_id`.

    Returns:
        The rows.

    Raises:
        ValueError: The file is not valid JSONL, or a line carries no id.
    """
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}: invalid JSONL on line {line_no}: {exc.msg}"
            ) from exc
        record_id = record.get(lane.id_field)
        if not isinstance(record_id, str) or not record_id:
            raise ValueError(
                f"{path}: line {line_no} has no {lane.id_field}"
            )
        rows.append(record)
    return rows


def _group_key(row: Mapping[str, Any], lane: MetricLane) -> str:
    """The task a row belongs to.

    Falls back to the record id when the lane's task column is absent,
    which is what a summary written before the column existed looks
    like. Falling back means such a campaign aggregates nothing rather
    than collapsing unrelated records together — the safe direction, and
    the report's repeat count makes it visible.
    """
    task = row.get(lane.group_field)
    if isinstance(task, str) and task:
        return task
    return str(row[lane.id_field])


def aggregate_repeats(
    rows: Sequence[Mapping[str, Any]], *, lane: MetricLane = RESEARCH_LANE
) -> dict[str, dict[str, Any]]:
    """Collapse a campaign's repeats into one row per task.

    Three runs of one benchmark query are three observations of that
    query, not three queries. Before ADR 0071 the differ compared `r1`
    to `r1` and `r2` to `r2`, so three repeats cost triple and still
    produced three single-run comparisons — the exact opposite of what
    repeats are for.

    Each metric becomes the mean of its non-null values across the
    task's repeats, and the individual values are kept under
    `REPEAT_VALUES_KEY` so the bootstrap can resample within a task
    instead of treating three repeats as three independent tasks (which
    would report an interval about `sqrt(3)` too narrow).

    `error` survives only when **every** repeat errored: a task that
    produced two good runs and one failure is a measurement of the two,
    and `ERRORED_REPEATS_KEY` carries the count so the report can say so
    rather than the mean quietly absorbing it.

    Args:
        rows: Summary rows, from one campaign.
        lane: Which campaign wrote them.

    Returns:
        `{task_id: aggregated_row}`.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(_group_key(row, lane), []).append(row)

    aggregated: dict[str, dict[str, Any]] = {}
    for task_id, group in grouped.items():
        merged: dict[str, Any] = dict(group[0])
        merged[lane.group_field] = task_id
        values: dict[str, tuple[float, ...]] = {}
        for field in lane.tabulated_fields:
            present = tuple(
                value
                for value in (_score(dict(row), field) for row in group)
                if value is not None
            )
            values[field] = present
            merged[field] = fmean(present) if present else None
        errors = [row.get("error") for row in group if row.get("error")]
        merged["error"] = errors[0] if len(errors) == len(group) else None
        merged["metrics_error"] = next(
            (row.get("metrics_error") for row in group if row.get("metrics_error")),
            None,
        )
        merged[REPEAT_VALUES_KEY] = values
        merged[REPEAT_COUNT_KEY] = len(group)
        merged[ERRORED_REPEATS_KEY] = len(errors)
        # Every repeat's block, not the first one's: `--resume` can
        # re-enter a campaign under a different judge model, and a task
        # whose three repeats were graded by two instruments must not
        # present as one measurement.
        merged[PROVENANCE_BLOCKS_KEY] = [
            block
            for block in (row.get(PROVENANCE_KEY) for row in group)
            if isinstance(block, dict) and block
        ]
        aggregated[task_id] = merged
    return aggregated


def load_summary(
    path: Path, *, lane: MetricLane = RESEARCH_LANE
) -> dict[str, dict[str, Any]]:
    """Read a `summary.jsonl` file into one aggregated row per task.

    `load_rows` then `aggregate_repeats`. A campaign that ran one repeat
    per task — every campaign before ADR 0071 — comes back exactly as it
    did before, because the mean of one value is that value.

    Returns an empty dict when the file does not exist so first-run
    diffs (no baseline yet) degrade gracefully instead of crashing.
    Malformed JSON is a hard error.

    Args:
        path: The summary file. A missing file reads as empty.
        lane: Which campaign wrote it.

    Returns:
        `{task_id: aggregated_row}`.

    Raises:
        ValueError: The file is not valid JSONL, or a line carries no id.
    """
    return aggregate_repeats(load_rows(path, lane=lane), lane=lane)


# ---------------------------------------------------------------------------
# Diffing
# ---------------------------------------------------------------------------


def _score(record: dict[str, Any], field: str) -> float | None:
    """Extract a scalar metric value from a summary line, defensively."""
    value = record.get(field)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def score_epsilon(
    field: str, threshold: float, lane: MetricLane = RESEARCH_LANE
) -> float:
    """The band a 0-1 score metric must clear, derived from its quantum.

    ADR 0044 gave every score metric the same 0.10, justified as typical
    LLM-judge noise. That reasoning holds for a metric with a fine
    denominator and breaks completely for one whose score can only take
    the values `k/4`: for `completeness` and `retrieval_recall` the flat
    band sat *below* one step, so a single borderline topic decision
    flipping was a guaranteed red and the epsilon filtered nothing.

    A metric with a declared quantum gets `QUANTUM_TOLERANCE` steps
    instead — one step passes, two fire — floored at `threshold` so a
    fine-grained metric never gets a *narrower* band than the judge
    noise estimate.

    A metric with no declared quantum gets the flat `threshold`, and for
    the deterministic ones that is a floor rather than a noise estimate:
    `citation_resolution_rate` has no judge to be noisy, so what 0.10
    filters is the product's own run-to-run variation. On a typical
    report citing three to five identifiers one unresolved citation
    moves the score 0.20-0.33 and fires; a task aggregated over three
    repeats needs two of fifteen to go unresolved (0.133) before it
    clears, and one (0.067) does not. See the note above `SCORE_QUANTA`
    for why declaring a quantum for it would make it ungatable.

    Args:
        field: Metric name.
        threshold: The flat score epsilon, from `--threshold`.
        lane: Which campaign's quanta to read.

    Returns:
        The absolute move this metric must exceed.
    """
    quantum = lane.score_quanta.get(field)
    if quantum is None:
        return threshold
    return max(threshold, QUANTUM_TOLERANCE * quantum)


def _significant(
    field: str,
    magnitude: float,
    threshold: float,
    baseline: float | None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Whether a directional move of `magnitude` is big enough to matter.

    `magnitude` is the absolute size of the move in the direction under
    test (adverse for regressions, favorable for improvements) and must
    be positive to ever return True.

    Score metrics compare against `score_epsilon`. Resource metrics must
    clear both legs of the lane's band; when the baseline is missing or
    non-positive the relative leg has no meaningful denominator, so the
    absolute floor alone decides.
    """
    band = lane.resource_thresholds.get(field)
    if band is None:
        return magnitude > score_epsilon(field, threshold, lane)
    floor, relative = band
    if magnitude <= floor:
        return False
    if baseline is None or baseline <= 0:
        return True
    return magnitude > relative * baseline


def _is_regression(
    field: str,
    delta: float,
    threshold: float,
    baseline: float | None = None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Whether a per-metric delta counts as a regression, per direction.

    `higher_better` metrics regress when they drop; `lower_better`
    metrics (cost, iterations, llm_calls) regress when they rise. The
    magnitude required depends on the metric class — see
    `_significant`.
    """
    direction = lane.directions.get(field, "higher_better")
    adverse = -delta if direction == "higher_better" else delta
    return adverse > 0 and _significant(field, adverse, threshold, baseline, lane)


def _is_improvement(
    field: str,
    delta: float,
    threshold: float,
    baseline: float | None = None,
    lane: MetricLane = RESEARCH_LANE,
) -> bool:
    """Symmetric of `_is_regression` — did this metric get meaningfully better?"""
    direction = lane.directions.get(field, "higher_better")
    favorable = delta if direction == "higher_better" else -delta
    return favorable > 0 and _significant(field, favorable, threshold, baseline, lane)


def _query_status(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
    deltas: dict[str, float | None],
    threshold: float,
    lane: MetricLane = RESEARCH_LANE,
) -> str:
    """Classify a single query's baseline-vs-current shape.

    Regression / improvement definitions honor per-metric direction —
    `cost_usd` rising beyond its band is a regression, not an
    improvement, even though the raw delta is positive.
    """
    if baseline is None and current is not None:
        return "new"
    if current is None and baseline is not None:
        return "removed"
    assert baseline is not None and current is not None  # type narrowing

    baseline_err = baseline.get("error")
    current_err = current.get("error")

    if current_err and not baseline_err:
        return "errored"
    if baseline_err and not current_err:
        return "recovered"

    # Only the lane's *gated* fields decide status. Informational
    # columns (harness spend) are diffed and printed but never flip a
    # run red or green — ADR 0050's product-vs-harness line.
    gated = [
        (field, deltas.get(field))
        for field in lane.metric_fields
        if deltas.get(field) is not None
    ]

    regressed = any(
        delta is not None
        and _is_regression(field, delta, threshold, _score(baseline, field), lane)
        for field, delta in gated
    )
    if regressed:
        return "regressed"

    improved = any(
        delta is not None
        and _is_improvement(field, delta, threshold, _score(baseline, field), lane)
        for field, delta in gated
    )
    if improved:
        return "improved"

    return "unchanged"


def diff_summaries(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
    *,
    allow_removed: bool = False,
    lane: MetricLane = RESEARCH_LANE,
    seed: int = DEFAULT_SEED,
) -> RegressionReport:
    """Compute per-record diffs and aggregate rollups.

    Args:
        baseline: `{id: summary_line}` from the reference run.
        current: `{id: summary_line}` from the new run.
        threshold: Minimum drop (as a raw score delta, e.g. `0.1`) that
            counts as a regression on a 0-1 score metric. Resource
            metrics ignore it — they are judged by the lane's
            two-leg bands.
        allow_removed: Treat a record present in `baseline` but missing
            from `current` as expected rather than as a regression. Set
            it for a deliberate subset run (`--queries a,b` diffed
            against a full baseline); leave it off for the nightly,
            where a vanished record means a truncated batch and the
            aggregate silently re-averages over a smaller denominator
            (ADR 0050).
        lane: Which campaign's fields and thresholds to use. Defaults
            to the research lane, so existing callers are unaffected.
        seed: Seed for the paired bootstrap, so two runs of the differ
            over the same summaries produce the same interval.

    Returns:
        `RegressionReport` with per-record status, per-metric deltas,
        aggregate rollups over records present in both runs, the
        provenance comparability check, the paired statistics and the
        PROMOTE / HOLD / ROLLBACK decision.
    """
    diffs: list[QueryDiff] = []
    query_ids = sorted(set(baseline) | set(current))

    for query_id in query_ids:
        b = baseline.get(query_id)
        c = current.get(query_id)

        deltas: dict[str, float | None] = {}
        for field in lane.tabulated_fields:
            b_val = _score(b, field) if b else None
            c_val = _score(c, field) if c else None
            if b_val is None or c_val is None:
                deltas[field] = None
            else:
                deltas[field] = c_val - b_val

        diffs.append(
            QueryDiff(
                query_id=query_id,
                status=_query_status(b, c, deltas, threshold, lane),
                baseline_error=(b or {}).get("error"),
                current_error=(c or {}).get("error"),
                deltas=deltas,
            )
        )

    aggregate_baseline = _aggregate_over_shared(baseline, current, lane)
    aggregate_current = _aggregate_over_shared(current, baseline, lane)
    aggregate_deltas: dict[str, float | None] = {}
    for field in lane.tabulated_fields:
        base_val = aggregate_baseline.get(field)
        cur_val = aggregate_current.get(field)
        aggregate_deltas[field] = (
            None if base_val is None or cur_val is None else cur_val - base_val
        )

    # A query that stopped producing data is a regression in signal:
    # the batch was truncated (kill, budget stop, interrupted run) and
    # the aggregate below quietly re-averages over whatever survived.
    # Green on a shrunken denominator is the failure ADR 0050 closes.
    gating_statuses = ("regressed", "errored") + (
        () if allow_removed else ("removed",)
    )

    report = RegressionReport(
        diffs=diffs,
        has_regressions=any(d["status"] in gating_statuses for d in diffs),
        lane=lane,
        threshold=threshold,
        allow_removed=allow_removed,
        unscored=_unscored_counts(baseline, current, lane),
        aggregate_baseline=aggregate_baseline,
        aggregate_current=aggregate_current,
        aggregate_deltas=aggregate_deltas,
        comparability=check_comparability(baseline, current),
        statistics=compute_statistics(
            baseline,
            current,
            lane=lane,
            threshold=threshold,
            aggregate_deltas=aggregate_deltas,
            seed=seed,
        ),
        reliability=_reliability(current, lane),
        # Filled in below: `decide` reads the report it is deciding on,
        # which is the only way its rules can be stated once instead of
        # being re-derived from the pieces.
        decision=Decision(verdict="HOLD", reasons=()),
        paired_tasks=len(set(baseline) & set(current)),
        repeats=max(
            (_repeat_count(row) for row in current.values()),
            default=1,
        ),
    )
    report["decision"] = decide(report)
    return report


def _unscored_counts(
    baseline: dict[str, dict[str, Any]],
    current: dict[str, dict[str, Any]],
    lane: MetricLane = RESEARCH_LANE,
) -> dict[str, int]:
    """Per metric: shared queries the baseline scored and the current run did not.

    Since ADR 0050 a judge that times out or truncates no longer aborts
    the campaign — it leaves that one metric `null` on the record and
    records why in `metrics_error`. That is the right trade, but it
    means a metric can quietly lose most of its queries between two
    runs: the deltas go `None`, the query classifies `unchanged`, and
    the aggregate below re-averages over whatever was scored. Same
    shrunken-denominator failure as a truncated batch, one level down,
    so `format_report` states this the same way it states `removed`.

    Counted only when the baseline *had* a value, so a field a summary
    never carried (`llm_calls` in a pre-ADR-0044 file) is absence, not
    lost signal.
    """
    shared = set(baseline) & set(current)
    return {
        field: sum(
            1
            for qid in shared
            if _score(baseline[qid], field) is not None
            and _score(current[qid], field) is None
        )
        for field in lane.tabulated_fields
    }


def _aggregate_over_shared(
    primary: dict[str, dict[str, Any]],
    secondary: dict[str, dict[str, Any]],
    lane: MetricLane = RESEARCH_LANE,
) -> dict[str, float | None]:
    """Mean of `primary`'s scores across queries also present in `secondary`.

    Restricting to shared queries makes baseline/current means directly
    comparable — they're computed over the same set.
    """
    shared = set(primary) & set(secondary)
    result: dict[str, float | None] = {}
    for field in lane.tabulated_fields:
        values = [
            _score(primary[qid], field)
            for qid in shared
            if _score(primary[qid], field) is not None
        ]
        values_typed = [v for v in values if v is not None]  # narrow
        result[field] = (
            sum(values_typed) / len(values_typed) if values_typed else None
        )
    return result


# ---------------------------------------------------------------------------
# Comparability — may these two runs be compared at all?
# ---------------------------------------------------------------------------


def _provenance_blocks(rows: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every provenance block in a campaign, one per record.

    Reads the per-repeat list `aggregate_repeats` stores when it has
    one, and falls back to the row's own block so a hand-built row — a
    test's, or a caller that assembled the mapping itself — is still
    checked.
    """
    blocks: list[dict[str, Any]] = []
    for row in rows.values():
        stored = row.get(PROVENANCE_BLOCKS_KEY)
        if isinstance(stored, list):
            blocks.extend(block for block in stored if isinstance(block, dict) and block)
            continue
        own = row.get(PROVENANCE_KEY)
        if isinstance(own, dict) and own:
            blocks.append(own)
    return blocks


def _provenance_values(blocks: Sequence[Mapping[str, Any]], field: str) -> set[str]:
    """The distinct values `field` takes across `blocks`, as strings.

    `rubric_versions` is a mapping, so it is flattened to a sorted
    `name@version` list first — two rows that ran the same rubrics at
    the same versions must compare equal whatever order the keys
    happened to be written in.
    """
    values: set[str] = set()
    for block in blocks:
        if field not in block:
            continue
        value = block[field]
        if isinstance(value, dict):
            values.add(
                ", ".join(f"{name}@{version}" for name, version in sorted(value.items()))
            )
        else:
            values.add(str(value))
    return values


def check_comparability(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
) -> Comparability:
    """Decide whether these two campaigns measure the same thing.

    ADR 0070 put a `provenance` block on every row precisely so this
    question could be asked. A delta measured across a judge-model swap,
    a rubric edit or a changed benchmark is a measurement of the change
    in instrument; reporting it as a quality movement is the failure the
    block exists to prevent, so this module refuses rather than reports.

    Three outcomes, and the distinction between the last two matters:

    - **Comparable.** Both runs carry blocks and they agree on every
      `COMPARABILITY_FIELDS` value.
    - **Not comparable.** They disagree — or one run disagrees with
      itself, which a resumed campaign can do.
    - **Comparable, with a note.** One or both runs carry no block at
      all. Absence is *unknown*, not *different*: refusing here would
      turn every pre-ADR-0070 baseline into a permanent red, so the
      comparison proceeds and the report says the attribution is
      missing.

    Args:
        baseline: Aggregated baseline rows.
        current: Aggregated current rows.

    Returns:
        The verdict, its conflicts, and any notes.
    """
    baseline_blocks = _provenance_blocks(baseline)
    current_blocks = _provenance_blocks(current)

    notes: list[str] = []
    if baseline and not baseline_blocks:
        notes.append(
            "No baseline row carries a provenance block, so this comparison "
            "cannot confirm the two runs used the same judge, rubrics and "
            "dataset. The usual cause is a summary written before ADR 0070."
        )
    if current and not current_blocks:
        notes.append(
            "No current row carries a provenance block. A row that cannot "
            "name what produced it cannot support a claim about what changed."
        )
    if not baseline_blocks or not current_blocks:
        return Comparability(comparable=True, conflicts=(), notes=tuple(notes))

    conflicts: list[str] = []
    for field in COMPARABILITY_FIELDS:
        baseline_values = _provenance_values(baseline_blocks, field)
        current_values = _provenance_values(current_blocks, field)
        for label, values in (
            ("baseline", baseline_values),
            ("current", current_values),
        ):
            if len(values) > 1:
                conflicts.append(
                    f"the {label} run disagrees with itself on "
                    f"`{field}`: {', '.join(sorted(values))}"
                )
        if (
            len(baseline_values) == 1
            and len(current_values) == 1
            and baseline_values != current_values
        ):
            conflicts.append(
                f"`{field}` moved: baseline {next(iter(baseline_values))!r} "
                f"-> current {next(iter(current_values))!r}"
            )

    product_models = _provenance_values(
        baseline_blocks, "product_model"
    ) | _provenance_values(current_blocks, "product_model")
    if len(product_models) > 1:
        notes.append(
            "The product model differs between the two runs "
            f"({', '.join(sorted(product_models))}). That is not a reason to "
            "refuse the comparison — it is usually its subject — but any "
            "movement below should be read as the model's, not the code's."
        )
    if "True" in _provenance_values(
        baseline_blocks, "code_dirty"
    ) | _provenance_values(current_blocks, "code_dirty"):
        notes.append(
            "At least one run was produced from a dirty working tree, so its "
            "`code_commit` does not identify the code that ran."
        )

    return Comparability(
        comparable=not conflicts, conflicts=tuple(conflicts), notes=tuple(notes)
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def _repeat_values(row: Mapping[str, Any], field: str) -> tuple[float, ...]:
    """One task's individual repeat values for `field`.

    Falls back to the aggregated scalar so a caller that assembled its
    own mapping — every existing test, and any code holding rows it
    built by hand — still produces a one-observation task rather than an
    empty one.
    """
    stored = row.get(REPEAT_VALUES_KEY)
    if isinstance(stored, dict):
        values = stored.get(field)
        if isinstance(values, (tuple, list)):
            return tuple(float(value) for value in values)
    value = _score(dict(row), field)
    return () if value is None else (value,)


def paired_samples(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    field: str,
) -> list[PairedSample]:
    """Tasks scored for `field` in **both** runs, in id order.

    The intersection, always. Scoring the baseline and the candidate on
    the same items is the whole reason a 20-query benchmark can say
    anything at all — unpaired, detecting a 5-point move against an 80%
    baseline would need roughly 906 items per arm.
    """
    return [
        PairedSample(
            task_id=task_id,
            baseline=_repeat_values(baseline[task_id], field),
            candidate=_repeat_values(current[task_id], field),
        )
        for task_id in sorted(set(baseline) & set(current))
        if _repeat_values(baseline[task_id], field)
        and _repeat_values(current[task_id], field)
    ]


def _mcnemar_if_binary(samples: Sequence[PairedSample]) -> McNemarResult | None:
    """McNemar's test, when every paired task is binary in both arms.

    All-or-nothing on purpose. Running the test over the subset of tasks
    that happen to be binary and dropping the rest would select on the
    outcome — the tasks whose repeats disagreed are exactly the
    interesting ones — so a metric that is not binary everywhere simply
    does not get this row.
    """
    if not samples:
        return None
    pairs: list[tuple[bool, bool]] = []
    for sample in samples:
        baseline_mean = fmean(sample.baseline)
        candidate_mean = fmean(sample.candidate)
        if baseline_mean not in (0.0, 1.0) or candidate_mean not in (0.0, 1.0):
            return None
        pairs.append((bool(baseline_mean), bool(candidate_mean)))
    return mcnemar(pairs)


def compute_statistics(
    baseline: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    *,
    lane: MetricLane = RESEARCH_LANE,
    threshold: float = DEFAULT_THRESHOLD,
    aggregate_deltas: Mapping[str, float | None] | None = None,
    seed: int = DEFAULT_SEED,
) -> dict[str, MetricStatistics]:
    """Intervals for the primary metric, and for anything that moved down.

    Not for every metric. `02-STANDARDS.md` §2.3 is explicit that a
    primary metric is predeclared and slices are diagnostic unless a
    multiplicity correction was declared in advance — twenty
    simultaneous per-metric tests on twenty queries manufacture false
    alarms by arithmetic. So the primary metric always gets an interval,
    and the others get one only when their aggregate moved in the
    adverse direction, where a reader is about to ask "is that real?"
    and deserves the answer.

    Args:
        baseline: Aggregated baseline rows.
        current: Aggregated current rows.
        lane: Which campaign's fields to read.
        threshold: The flat score epsilon, for the reported band.
        aggregate_deltas: Per-metric aggregate deltas, used to pick the
            diagnostic metrics. `None` analyses only the primary.
        seed: Bootstrap seed.

    Returns:
        `{field: MetricStatistics}`, in `tabulated_fields` order.
    """
    wanted = {lane.primary_metric} if lane.primary_metric else set()
    for field, delta in (aggregate_deltas or {}).items():
        if delta is None:
            continue
        direction = lane.directions.get(field, "higher_better")
        adverse = -delta if direction == "higher_better" else delta
        if adverse > 0:
            wanted.add(field)

    result: dict[str, MetricStatistics] = {}
    for field in lane.tabulated_fields:
        if field not in wanted:
            continue
        samples = paired_samples(baseline, current, field)
        if not samples:
            continue
        result[field] = MetricStatistics(
            field=field,
            bootstrap=paired_bootstrap_delta(samples, seed=seed),
            mcnemar=_mcnemar_if_binary(samples),
            epsilon=score_epsilon(field, threshold, lane),
            primary=field == lane.primary_metric,
        )
    return result


def _repeat_count(row: Mapping[str, Any]) -> int:
    """How many records were folded into this task's row."""
    count = row.get(REPEAT_COUNT_KEY)
    return count if isinstance(count, int) and count > 0 else 1


def _binary_reliability(
    rows: Mapping[str, Mapping[str, Any]], field: str, label: str
) -> Reliability | None:
    """A binary metric's campaign rate, its Wilson interval and `pass^k`.

    `None` when the metric is not binary — a rate is only a rate when
    the underlying observation is a success or a failure.
    """
    per_task = [values for values in (_repeat_values(rows[task], field) for task in rows) if values]
    if not per_task or any(value not in (0.0, 1.0) for values in per_task for value in values):
        return None
    trials = sum(len(values) for values in per_task)
    successes = int(sum(sum(values) for values in per_task))
    repeats = min(len(values) for values in per_task)
    pass_k = (
        fmean(
            pass_hat_k(int(sum(values)), len(values), repeats) for values in per_task
        )
        if repeats > 1
        else None
    )
    return Reliability(
        label=label,
        successes=successes,
        tasks=trials,
        interval=wilson_interval(successes, trials),
        pass_k=pass_k,
        repeats=repeats,
    )


def _completion_reliability(
    rows: Mapping[str, Mapping[str, Any]], lane: MetricLane
) -> Reliability | None:
    """The campaign's own success rate: records that ran without erroring.

    Present on both lanes and deterministic on both, which makes it the
    one place `pass^k` and the rule of three always have something to
    say — every judged metric on the research lane is a ratio rather
    than a success.
    """
    if not rows:
        return None
    per_task: list[tuple[int, int]] = []
    for row in rows.values():
        repeats = _repeat_count(row)
        errored = row.get(ERRORED_REPEATS_KEY)
        if not isinstance(errored, int):
            errored = repeats if row.get("error") else 0
        per_task.append((repeats - errored, repeats))
    trials = sum(repeats for _, repeats in per_task)
    successes = sum(good for good, _ in per_task)
    repeats = min(repeats for _, repeats in per_task)
    pass_k = (
        fmean(pass_hat_k(good, total, repeats) for good, total in per_task)
        if repeats > 1
        else None
    )
    return Reliability(
        label=f"{lane.unit_plural} that ran without erroring",
        successes=successes,
        tasks=trials,
        interval=wilson_interval(successes, trials),
        pass_k=pass_k,
        repeats=repeats,
    )


def _reliability(
    rows: Mapping[str, Mapping[str, Any]], lane: MetricLane
) -> list[Reliability]:
    """Every binary rate the current run supports, campaign rate first."""
    rates: list[Reliability] = []
    completion = _completion_reliability(rows, lane)
    if completion is not None:
        rates.append(completion)
    for field in lane.metric_fields:
        # Only *gated quality* metrics can be success rates. A resource
        # metric is excluded even when its values happen to be 0 and 1 —
        # the scripted tier's `cost_usd` is $0.00 on every session, and
        # calling that a 0% success rate would be arithmetic dressed as
        # a finding. So is anything `lower_better`.
        if (
            field in lane.resource_thresholds
            or lane.directions.get(field, "higher_better") != "higher_better"
        ):
            continue
        rate = _binary_reliability(rows, field, f"`{field}`")
        if rate is not None:
            rates.append(rate)
    return rates


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def decide(report: RegressionReport) -> Decision:
    """PROMOTE / HOLD / ROLLBACK, with the reasoning attached.

    Order matters, and the first rule is the one ADR 0071 is about: a
    comparison across a moved instrument produces no verdict at all.
    After that, a regression that cleared its band is a ROLLBACK, and
    everything else is PROMOTE only if the comparison had the paired
    items to have found a regression — at 20 queries it does not, so
    the honest answer is HOLD and the report says why.

    Args:
        report: A populated `RegressionReport`.

    Returns:
        The verdict and its reasons.
    """
    lane = report["lane"]
    comparability = report["comparability"]
    if not comparability.comparable:
        return Decision(
            verdict="HOLD",
            reasons=(
                "These two runs were not produced by the same instrument, so "
                "no verdict was reached: "
                + "; ".join(comparability.conflicts)
                + ". Re-establish the baseline under the current "
                "configuration before reading a delta as a quality movement.",
            ),
        )

    if report["has_regressions"]:
        offenders = {
            status: [
                diff["query_id"] for diff in report["diffs"] if diff["status"] == status
            ]
            for status in ("regressed", "errored", "removed")
        }
        reasons = [
            f"{len(ids)} {lane.unit_singular if len(ids) == 1 else lane.unit_plural} "
            f"{status}: {', '.join(sorted(ids))}"
            for status, ids in offenders.items()
            if ids and not (status == "removed" and report["allow_removed"])
        ]
        return Decision(verdict="ROLLBACK", reasons=tuple(reasons))

    paired = report["paired_tasks"]
    if paired == 0:
        return Decision(
            verdict="HOLD",
            reasons=(
                f"No {lane.unit_singular} appears in both runs, so nothing was "
                "compared. The usual cause is a first run with no baseline "
                "yet.",
            ),
        )

    primary = report["statistics"].get(lane.primary_metric)
    if lane.primary_metric and primary is None:
        # The predeclared subject of the comparison was never scored on
        # a single paired task. Reachable since ADR 0074 made the
        # research lane's primary a metric that can honestly report
        # nothing: a campaign whose reports cited no identifiers has no
        # `citation_resolution_rate` anywhere. Promoting on the strength
        # of the secondary metrics would be answering a question nobody
        # asked, so the verdict is HOLD and the report says which metric
        # went unmeasured.
        return Decision(
            verdict="HOLD",
            reasons=(
                f"No {lane.unit_singular} carries a `{lane.primary_metric}` "
                "score in both runs, so the comparison's predeclared primary "
                "metric was never measured. Nothing below is evidence about "
                "it.",
            ),
        )
    if primary is not None and primary.bootstrap is not None:
        interval = primary.bootstrap.interval
        direction = lane.directions.get(lane.primary_metric, "higher_better")
        adverse_bound = interval.high if direction == "higher_better" else interval.low
        if interval.excludes_zero() and (
            adverse_bound < 0 if direction == "higher_better" else adverse_bound > 0
        ):
            return Decision(
                verdict="HOLD",
                reasons=(
                    f"`{lane.primary_metric}` moved {primary.bootstrap.point:+.3f} "
                    f"with a 95% interval of {interval} that excludes zero — "
                    "below the gate's band, but not explained by sampling. "
                    "Investigate before promoting.",
                ),
            )

    required = mcnemar_required_pairs(
        delta=GATE_EFFECT_SIZE, discordance=GATE_EFFECT_SIZE, power=0.8
    )
    if paired < required:
        return Decision(
            verdict="HOLD",
            reasons=(
                f"No metric cleared its band, but {paired} paired "
                f"{lane.unit_plural} cannot detect a "
                f"{GATE_EFFECT_SIZE:.0%} move against a baseline of "
                f"{GATE_BASELINE_RATE:.0%} — about {required} paired "
                "items are needed at 80% power. This is not evidence that "
                "nothing changed; it is evidence that this comparison could "
                "not have told you.",
            ),
        )

    return Decision(
        verdict="PROMOTE",
        reasons=(
            f"No metric cleared its band across {paired} paired "
            f"{lane.unit_plural}, and the comparison carried enough of them "
            "to have found a regression that size.",
        ),
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_delta(delta: float | None) -> str:
    if delta is None:
        return "-"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f}"


def _fmt_score(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def _cost_reference_section(report: RegressionReport) -> list[str]:
    """The per-unit cost table, when the lane quotes a planned estimate.

    Gate W2 asks what a guided-read session costs. This section makes
    the eval plumbing answer it rather than an ad-hoc script: the two
    measured means sit beside the plan's estimate, and the estimate row
    says in the row itself that it is an estimate. Lanes with no
    `cost_reference` (the research lane) render nothing, so their report
    is unchanged.
    """
    reference = report["lane"].cost_reference
    if reference is None:
        return []
    unit = report["lane"].unit_singular
    field = reference.field
    return [
        "",
        f"## Cost per {unit} vs the plan's estimate",
        "",
        f"| Source | $ / {unit} |",
        "|---|---:|",
        f"| Baseline mean `{field}` (measured) "
        f"| {_fmt_score(report['aggregate_baseline'].get(field))} |",
        f"| Current mean `{field}` (measured) "
        f"| {_fmt_score(report['aggregate_current'].get(field))} |",
        f"| Plan estimate — **not a measurement** "
        f"| {reference.low:.2f} – {reference.high:.2f} |",
        "",
        f"The estimate row is a prior quoted from {reference.source}. It was "
        "written before any campaign ran and has never been checked against "
        "one; it is here so the measured rows have something to be read "
        "against, not as a target the campaign passed or failed.",
    ]


def format_report(report: RegressionReport) -> str:
    """Render a `RegressionReport` as a markdown document."""
    lane = report["lane"]
    threshold = report["threshold"]
    resource_lines = "; ".join(
        f"`{field}` > +{floor:g} and > +{relative:.0%}"
        for field, (floor, relative) in lane.resource_thresholds.items()
    )
    removed = sum(1 for d in report["diffs"] if d["status"] == "removed")
    new = sum(1 for d in report["diffs"] if d["status"] == "new")
    shared = len(report["diffs"]) - removed - new
    baseline_total = shared + removed
    removed_note = (
        f"{removed} (not gated: --allow-removed)"
        if report["allow_removed"]
        else str(removed)
    )
    quantised = "; ".join(
        f"`{field}` > {score_epsilon(field, threshold, lane):.2f} "
        f"({QUANTUM_TOLERANCE:g} x its {quantum:g} quantum)"
        for field, quantum in sorted(lane.score_quanta.items())
    )
    decision = report["decision"]
    repeats = report["repeats"]
    lines = [
        f"# {lane.title}",
        "",
        f"- **Decision**: **{decision.verdict}**",
        f"- **Score epsilon**: `{threshold:.2f}` (a 0-1 score drop larger than this is a regression)"
        + (f"; per-quantum bands: {quantised}" if quantised else ""),
        f"- **Resource bands** (both legs must be exceeded): {resource_lines}",
        f"- **{lane.unit_plural.capitalize()}**: {shared} compared, {removed_note} "
        f"missing from the current run, {new} new",
        f"- **Repeats per {lane.unit_singular}**: {repeats}"
        + (
            " — aggregated by "
            f"{lane.group_field} before diffing, so repeats are observations "
            "of one task rather than separate tasks"
            if repeats > 1
            else ""
        ),
        f"- **Regressions detected**: {'yes' if report['has_regressions'] else 'no'}",
    ]

    # A metric the current run stopped scoring contributes nothing to
    # the gate — its delta is `None`, so the query reads `unchanged`.
    # Without this line a night where the faithfulness judge failed on
    # 18 of 20 queries is indistinguishable from a clean one: green
    # tick, "20 compared", a mean quietly taken over the surviving two
    # (ADR 0050).
    lost = {f: n for f, n in report["unscored"].items() if n}
    if lost:
        detail = "; ".join(
            f"`{field}` on {count} of {shared}"
            for field, count in sorted(lost.items())
        )
        lines.append(
            f"- **Unscored in the current run**: {detail}. The baseline "
            "scored these and the current run did not — an eval judge "
            "failed there, so they are absent from the comparison "
            "rather than unchanged by it. Not gated: a flaky judge is a "
            "harness fault, not a product regression. Read "
            "`metrics_error` in the run's summary."
        )

    lines += [
        "",
        # State the denominator: `_aggregate_over_shared` averages over
        # the intersection, so a truncated current run makes these means
        # describe a smaller set than the baseline they sit beside. The
        # `Compared` column carries the same honesty per metric, since a
        # null score shrinks one row's denominator without shrinking the
        # section's.
        f"## Aggregate (over the {shared} of {baseline_total} baseline "
        f"{lane.unit_plural} present in both runs)",
        "",
        "| Metric | Baseline | Current | Delta | Compared |",
        "|---|---:|---:|---:|---:|",
    ]
    for field in lane.tabulated_fields:
        compared = sum(
            1
            for d in report["diffs"]
            if d["status"] not in ("removed", "new")
            and d["deltas"].get(field) is not None
        )
        # Harness columns are printed so a campaign's real cost is
        # legible, and marked so nobody reads them as part of the gate.
        suffix = " *(not gated)*" if field in lane.informational_fields else ""
        lines.append(
            f"| {field}{suffix} "
            f"| {_fmt_score(report['aggregate_baseline'].get(field))} "
            f"| {_fmt_score(report['aggregate_current'].get(field))} "
            f"| {_fmt_delta(report['aggregate_deltas'].get(field))} "
            f"| {compared} / {shared} |"
        )

    lines += _cost_reference_section(report)

    headers = " | ".join(header for header, _ in lane.columns)
    alignment = "|".join("---:" for _ in lane.columns)
    lines += [
        "",
        f"## Per-{lane.unit_singular}",
        "",
        f"| {lane.unit_singular.capitalize()} | Status | {headers} |",
        f"|---|---|{alignment}|",
    ]
    for diff in report["diffs"]:
        cells = " | ".join(
            _fmt_delta(diff["deltas"].get(field)) for _, field in lane.columns
        )
        lines.append(f"| {diff['query_id']} | {diff['status']} | {cells} |")

    errored = [d for d in report["diffs"] if d["status"] == "errored"]
    if errored:
        lines += [
            "",
            "## New errors",
            "",
        ]
        for diff in errored:
            lines.append(
                f"- `{diff['query_id']}`: {diff['current_error']}"
            )

    lines += _decision_section(report)

    return "\n".join(lines) + "\n"


def _decision_section(report: RegressionReport) -> list[str]:
    """The verdict, the intervals behind it, and what N does not support.

    Placed last on purpose: it is the part a reader should leave with,
    and every table above it is the evidence it is drawn from.
    """
    decision = report["decision"]
    lines = [
        "",
        "## Decision",
        "",
        f"### {decision.verdict}",
        "",
    ]
    lines += [f"- {reason}" for reason in decision.reasons]
    lines += [
        "",
        "`PROMOTE` — no regression, on a comparison large enough to have "
        "found one. `ROLLBACK` — a regression cleared its band. `HOLD` — "
        "neither: nothing cleared a band, and nothing here can rule out a "
        "move that did not. A gate that says *cannot distinguish* is worth "
        "more than one that says *fine* on the same evidence.",
    ]
    lines += _comparability_section(report)
    lines += _statistics_section(report)
    lines += _reliability_section(report)
    return lines


def _comparability_section(report: RegressionReport) -> list[str]:
    """The provenance verdict, when there is anything to say about it."""
    comparability = report["comparability"]
    if comparability.comparable and not comparability.notes:
        return []
    lines = ["", "### Comparability", ""]
    if not comparability.comparable:
        lines += [
            "**These runs were produced by different instruments, so this "
            "differ refused to compare them** (ADR 0070, ADR 0071):",
            "",
        ]
        lines += [f"- {conflict}" for conflict in comparability.conflicts]
        lines += [
            "",
            "A judge model, a rubric version or a benchmark that moved "
            "changes what the numbers *mean*; a delta measured across that "
            "change describes the change, not the product. Re-run the "
            "baseline under the current configuration.",
        ]
    lines += [f"- {note}" for note in comparability.notes]
    return lines


def _statistics_section(report: RegressionReport) -> list[str]:
    """Intervals for the primary metric and anything that moved down."""
    lane = report["lane"]
    statistics = report["statistics"]
    paired = report["paired_tasks"]
    lines = ["", "### Statistics", ""]

    if not statistics:
        lines.append(
            "No metric was scored in both runs, so there is nothing to put an "
            "interval on."
        )
        return lines

    lines += [
        f"Primary metric: `{lane.primary_metric}`, predeclared. Every other "
        "row is **diagnostic** — it is here because the metric moved "
        "adversely, it carries no multiplicity correction, and a set of "
        "simultaneous per-metric tests on a benchmark this size produces "
        "false alarms by arithmetic.",
        "",
        "| Metric | Paired Δ | 95% interval | Band | McNemar | Role |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for field in lane.tabulated_fields:
        stat = statistics.get(field)
        if stat is None or stat.bootstrap is None:
            continue
        test = (
            f"b={stat.mcnemar.baseline_only} c={stat.mcnemar.candidate_only}, "
            f"p={stat.mcnemar.p_value:.3f} ({stat.mcnemar.method})"
            if stat.mcnemar is not None
            else "-"
        )
        lines.append(
            f"| `{field}` "
            f"| {stat.bootstrap.point:+.3f} "
            f"| {stat.bootstrap.interval} "
            f"| {stat.epsilon:.2f} "
            f"| {test} "
            f"| {'primary' if stat.primary else 'diagnostic'} |"
        )

    hierarchical = any(
        stat.bootstrap is not None and stat.bootstrap.hierarchical
        for stat in statistics.values()
    )
    resamples = next(
        (
            stat.bootstrap.resamples
            for stat in statistics.values()
            if stat.bootstrap is not None
        ),
        0,
    )
    seed = next(
        (
            stat.bootstrap.seed
            for stat in statistics.values()
            if stat.bootstrap is not None
        ),
        0,
    )
    lines += [
        "",
        f"Intervals are percentile paired bootstraps over {lane.unit_plural} "
        f"({resamples} resamples, seed {seed})"
        + (
            ", resampling repeats within each "
            f"{lane.unit_singular} as well so three repeats are not counted "
            "as three independent observations."
            if hierarchical
            else "."
        ),
        "",
        power_statement(
            paired, delta=GATE_EFFECT_SIZE, baseline_rate=GATE_BASELINE_RATE
        ),
    ]
    caveat = small_sample_caveat(paired)
    if caveat:
        lines += ["", caveat]
    return lines


def _reliability_section(report: RegressionReport) -> list[str]:
    """Success rates with Wilson intervals, `pass^k`, and the rule of three."""
    rates = report["reliability"]
    if not rates:
        return []
    lines = [
        "",
        "### Reliability (current run)",
        "",
        "| Outcome | Rate | 95% Wilson | pass^k |",
        "|---|---:|---:|---:|",
    ]
    for rate in rates:
        pass_k = (
            f"{rate.pass_k:.3f} (k={rate.repeats})"
            if rate.pass_k is not None
            else f"n/a (k={rate.repeats})"
        )
        lines.append(
            f"| {rate.label} "
            f"| {rate.successes} / {rate.tasks} = {rate.rate:.3f} "
            f"| [{rate.interval.low:.3f}, {rate.interval.high:.3f}] "
            f"| {pass_k} |"
        )
    lines += [
        "",
        "`pass^k` is the probability that **all** k repeats succeed — what a "
        "user of a repeated workflow experiences, and the statistic that has "
        "displaced `pass@1`. It reads `n/a` at one repeat, where it is the "
        "rate itself.",
    ]
    # Quoted for the campaign's own completion rate — `rates[0]`, the
    # only row whose denominator is every run — rather than for whichever
    # listed outcome happens to have the fewest observations. `3/n` on a
    # two-observation row is 150%, which is arithmetically true and says
    # nothing; anchoring the sentence to one named denominator is what
    # makes it a claim.
    completion = rates[0]
    if completion.successes == completion.tasks:
        bound = min(1.0, rule_of_three(completion.tasks))
        lines += [
            "",
            "**A clean sweep is not zero risk.** Zero failures in "
            f"{completion.tasks} runs bounds the failure rate at roughly "
            f"**{bound:.1%}** by the rule of three — not at zero. That is "
            "what a green run on a benchmark this size supports.",
        ]
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diff two eval summary.jsonl files; exit 1 on regression."
    )
    parser.add_argument(
        "baseline", type=Path, help="Baseline summary.jsonl (may be missing)"
    )
    parser.add_argument(
        "current", type=Path, help="Current summary.jsonl (must exist)"
    )
    parser.add_argument(
        "--lane",
        choices=sorted(LANES),
        default=RESEARCH_LANE.name,
        help=(
            "Which campaign wrote these summaries. 'research' (default) "
            "reads src/eval/runner.py's fields, keyed by query_id; "
            "'learning' reads src/eval/simulate_learner.py's, keyed by "
            "record_id."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_THRESHOLD,
        help=(
            "Floor for the regression epsilon on the 0-1 score metrics "
            f"(default: {DEFAULT_THRESHOLD}). A metric with a declared "
            "quantum gets a wider band derived from it, so one flipped "
            "judge decision passes and two do not. Count and dollar "
            "metrics use fixed per-metric bands instead — see the lane's "
            "resource thresholds."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help=(
            "Seed for the paired bootstrap "
            f"(default: {DEFAULT_SEED}). Fixed so re-running the differ "
            "over unchanged summaries cannot change its verdict."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Also write the markdown report to this path",
    )
    parser.add_argument(
        "--allow-removed",
        action="store_true",
        help=(
            "Don't fail when a baseline query is missing from the "
            "current run. For deliberate subset runs only — by default "
            "a vanished query is a regression, because a truncated "
            "batch otherwise passes green on a shrunken denominator."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    lane = LANES[args.lane]

    if not args.current.exists():
        print(f"Error: current file not found: {args.current}", file=sys.stderr)
        return EXIT_INVALID

    try:
        baseline = load_summary(args.baseline, lane=lane)
        current = load_summary(args.current, lane=lane)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID

    if not baseline:
        print(
            f"Note: baseline {args.baseline} not found or empty — "
            "treating first run as baseline.",
            file=sys.stderr,
        )

    report = diff_summaries(
        baseline,
        current,
        threshold=args.threshold,
        allow_removed=args.allow_removed,
        lane=lane,
        seed=args.seed,
    )
    markdown = format_report(report)
    print(markdown)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")

    # The decision, not `has_regressions`, decides the status. The two
    # agree except when the runs are not comparable, where a regression
    # may not be asserted at all and the caller is told the comparison
    # failed rather than the product did.
    if not report["comparability"].comparable:
        print(
            "Error: the baseline and current runs are not comparable; "
            "no verdict was reached.",
            file=sys.stderr,
        )
        return EXIT_INCOMPARABLE
    return EXIT_REGRESSION if report["decision"].verdict == "ROLLBACK" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
