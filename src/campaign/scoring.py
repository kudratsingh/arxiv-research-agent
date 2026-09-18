"""The live judge scorer: real rubrics, its own accumulator, its own cap.

Until LE-S a campaign had exactly two scorers. `deterministic_scorer`
computes the two free checks and names the three it skipped;
`MockJudgeScorer` (ADR 0095) executes all five against a checked-in
fixture at `$0.000000`. Neither calls a model, and `execute_campaign`
refused outright to run a campaign that budgeted judge calls without a
scorer — correctly, because scoring less than the protocol declared is
worse than not running. So the funded path had no scorer at all: the
thing a funded baseline exists to produce could not be produced.

This is that scorer, and three properties are what make it safe to point
at a credential.

**It runs under its own accumulator and its own cap (EL-02).** The
episode runner calls `start_cost_tracking()` and never resets it, so
before this module a judge call made after the graph returned would have
been recorded against the *workflow's* accumulator — which is the number
the arm is judged on, and which `src.llm._check_cost_budget` compares
against the episode's workflow cap. A judged episode that had spent its
workflow budget would have had its judges refused as if the policy were
over budget. `judge_cost_scope` opens a fresh accumulator with
`judge_cost_usd_max` bound as its effective cap and restores the caller's
bindings in `finally`, so judge dollars are judge dollars, the reported
`judge_cost_usd` and `judge_model_calls` are real rather than the
hard-coded `"0.000000"` / `0` they were, and the ledger — which
`budget_stop_reached` sums workflow + judge from — gets the truth.

**It never raises (EL-01, EL-03).** A judge that times out, 429s past its
retries or truncates into invalid JSON costs that metric and nothing
else: the metric is `None` with a reason, the other four are scored, and
`completion.json` is still written. That is `src/eval/runner.py`'s
`_compute_metrics` contract, which is why this module reuses it rather
than re-deriving five call sites — the guard per metric is the property,
and two copies of it would drift.

**It reads the persisted snapshot, not the live state (EL-05).** The
scorer declares `score_persisted`, so `_run_one_episode` hands it the
parse of the `episode-state.json` it just wrote. A `rejudge` pass weeks
later reads the same file and therefore the same inputs; a judge fed the
graph's in-memory dictionary could never be re-run against them.

That file is also what makes ADR 0100's D-3 Option A reachable. The
faithfulness judge takes the reader's ranked chunks per cited paper when
a caller supplies them and records `source_scope` either way, and the
campaign is the caller that can: the chunks are in the snapshot it just
wrote, and nowhere else after the process exits. The offline runner and
the mock judge supply nothing and stay on `abstract_only`, which is a
different instrument and says so.

It refuses to construct under mock data or the zero-spend sentinel, the
mirror of `build_mock_judge_scorer`'s guard and for the same reason: the
two scorers are each other's opposite, and a surface that quietly works
under both configurations is a surface that scored something other than
what the operator asked for.

See [ADR 0101](../../docs/decisions/0101-the-funded-episode-path.md).
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Mapping, Sequence
from decimal import Decimal
from typing import Any, Final, cast

from src.campaign.errors import CampaignError
from src.campaign.execute import (
    PRIMARY_METRIC,
    EpisodeRun,
    EpisodeScores,
    deterministic_scorer,
)
from src.campaign.ledger import EpisodeScoreReceipt
from src.campaign.matrix import PlannedEpisode
from src.config import Settings
from src.contracts.kernel import MoneyUsd
from src.llm import LOCAL_PREVIEW_DISABLED_API_KEY
from src.observability import get_logger

log = get_logger(__name__)

#: The three rubrics that cost money, in the order `_compute_metrics`
#: runs them. Named here because "which metrics are judged" is the
#: question the judge-failure stop rule is asked, and reading it off a
#: dict of five would count the two free ones as judges that never fail.
JUDGED_METRICS: Final[tuple[str, ...]] = (
    "completeness",
    "faithfulness",
    "retrieval_recall",
)

#: Every metric `src/eval/runner.py::_compute_metrics` returns, judged and
#: free. Used to split its `"; "`-joined failure summary back into one
#: reason per metric: the summary is built as `f"{name}: {type}: {exc}"`
#: per failure, and an exception message may itself contain `"; "`, so the
#: split is anchored on these names rather than on the separator.
ALL_METRICS: Final[tuple[str, ...]] = (
    "citation_resolution_rate",
    "citation_accuracy",
    *JUDGED_METRICS,
)

#: Why one metric has no score. A closed vocabulary, because a campaign
#: report reads these to decide whether a missing score is an instrument
#: problem (stop the campaign) or a property of the episode (do not).
REASON_BUDGET: Final[str] = "judge_budget_exhausted"
REASON_FAILED: Final[str] = "judge_failed"
REASON_NO_QUERY: Final[str] = "no_benchmark_query"


@contextlib.contextmanager
def judge_cost_scope(cap_usd: float) -> Iterator[Any]:
    """Run the judges on their own accumulator, under their own ceiling.

    The two `ContextVar`s in `src/observability/costs.py` are a run's
    spend and a run's ceiling, and both are process-context state that
    somebody else set. `start_cost_tracking()` replaces the first and
    hands back no token; `bind_effective_cost_cap` hands back a token for
    the second. So this swaps the first by hand — reading the previous
    accumulator out of the module's own `ContextVar` and putting it back
    in `finally` — and uses the token for the second.

    Reaching for `_current_costs` is deliberate and is the smaller evil:
    the alternative is a second accumulator abstraction in this package,
    and then `record_llm_call` would have to know which of the two to
    write to. The gateway must keep exactly one notion of "the current
    run's spend"; what changes here is *which* run is current.

    Args:
        cap_usd: The judges' ceiling for this episode. Zero or negative
            binds no cap, which is the right answer for a campaign whose
            judge allocation is zero — there is nothing to enforce and
            the judges will not be called.

    Yields:
        The judges' own `RunCosts`, whose totals are the episode's real
        `judge_cost_usd` and `judge_model_calls`.
    """
    from src.observability.costs import (
        _current_costs,
        bind_effective_cost_cap,
        reset_effective_cost_cap,
        start_cost_tracking,
    )

    previous = _current_costs.get()
    costs = start_cost_tracking()
    token = bind_effective_cost_cap(cap_usd) if cap_usd > 0 else None
    try:
        yield costs
    finally:
        if token is not None:
            reset_effective_cost_cap(token)
        _current_costs.set(previous)


class LiveJudgeScorer:
    """Score one episode's five metrics, three of them with a real judge.

    Selected by `python -m src.campaign run --live-judge`. Constructing
    it is refused on the two configurations where a judge cannot mean
    what it says: mock data (the five fixture papers of ADR 0041, where
    every agent is model-free under ADR 0080) and the zero-spend
    sentinel.
    """

    def __init__(
        self,
        config: Settings,
        *,
        judge_cost_usd_max: MoneyUsd = "0.000000",
    ) -> None:
        """
        Args:
            config: The campaign's settings. Read for the judge model and
                for the two refusals; the judges themselves run under
                whatever `bound_settings` installed, which is the same
                object.
            judge_cost_usd_max: The episode's approved judge allocation,
                from the sealed `EpisodeBudget`. Bound as the effective
                cap for the judge pass and for nothing else.

        Raises:
            CampaignError: Mock data is on, or the credential is the
                repository's zero-spend sentinel.
        """
        if config.use_mock_data:
            raise CampaignError(
                "live judge scoring cannot run under USE_MOCK_DATA=true; the "
                "fixture corpus has no judge to be live about. Use "
                "--mock-judge, which executes the same three rubrics "
                "deterministically at zero cost"
            )
        secret = config.anthropic_api_key
        key = secret.get_secret_value() if secret is not None else ""
        if not key or key == LOCAL_PREVIEW_DISABLED_API_KEY:
            raise CampaignError(
                "live judge scoring requires a credential that can pay; "
                "ANTHROPIC_API_KEY is unset or is the zero-spend sentinel. "
                "Possessing one is still not authorization — the campaign's "
                "approval record is checked separately"
            )
        self._config = config
        self._cap = float(Decimal(judge_cost_usd_max))
        self._queries = self._benchmark_queries()

    @staticmethod
    def _benchmark_queries() -> Mapping[str, Any]:
        """The suite's expected-topic sets, indexed by case id.

        Imported at construction rather than at module import for the
        reason every heavy import in this package is local: a process
        that only plans a matrix must not pay for the benchmark module.
        """
        from src.eval.benchmark_queries import BENCHMARK_QUERIES

        return {query["query_id"]: query for query in BENCHMARK_QUERIES}

    def __call__(self, episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
        """Score from the run's live state.

        The `EpisodeScorer` half of the surface, kept so that this scorer
        can be used anywhere the others can — a test, a recovery tool, a
        caller that has an `EpisodeRun` and no snapshot. The campaign
        loop calls `score_persisted` instead.
        """
        return self.score_persisted(episode, run, {})

    def score_persisted(
        self,
        episode: PlannedEpisode,
        run: EpisodeRun,
        state: Mapping[str, Any],
    ) -> EpisodeScores:
        """Score from the snapshot that was written before this was called.

        Never raises. Every failure mode below is a metric that came back
        `None` with a reason beside it, and an episode whose five metrics
        all failed is still a completed episode with a written receipt.
        """
        free = self._free_scores(episode, run)
        detail: dict[str, Any] = dict(free.detail)
        judge_state = self._judge_state(run, state)
        query = self._queries.get(episode.case_id)
        if query is None:
            # Not an error: a campaign may legitimately run a case the
            # benchmark module has no expected-topic set for, and the
            # honest answer is three absent rubrics with a reason rather
            # than a raised exception that costs the episode its receipt.
            return self._scores(
                episode,
                free,
                detail,
                metrics=dict.fromkeys(ALL_METRICS),
                reasons=dict.fromkeys(JUDGED_METRICS, REASON_NO_QUERY),
                judge_cost_usd="0.000000",
                judge_model_calls=0,
                state=state,
            )

        chunks = self._ranked_chunks(state)
        with judge_cost_scope(self._cap) as costs:
            metrics, failures = self._compute(judge_state, query, chunks)
            judge_cost = Decimal(str(round(float(costs.total_cost_usd), 6)))
            judge_calls = int(costs.call_count)

        reasons = _reasons_for(metrics, failures)
        if any(reason == REASON_BUDGET for reason in reasons.values()):
            log.warning(
                "campaign_judge_budget_exhausted",
                extra={
                    "run_id": episode.run_id,
                    "case_id": episode.case_id,
                    "arm_id": episode.arm_id,
                    "cap_usd": f"{self._cap:.6f}",
                    "spent_usd": f"{judge_cost:.6f}",
                    "judge_model_calls": judge_calls,
                },
            )
        return self._scores(
            episode,
            free,
            detail,
            metrics=metrics,
            reasons=reasons,
            judge_cost_usd=f"{judge_cost:.6f}",
            judge_model_calls=judge_calls,
            state=state,
        )

    @staticmethod
    def _free_scores(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
        """The two deterministic checks, guarded.

        `deterministic_scorer` computes `measure_citation_resolution` and
        ADR 0074's groundedness check without a guard of its own — it is
        called from a loop that used to let a scorer's exception
        propagate, so it never needed one. It does now: this scorer's
        promise is that *nothing* it does costs the episode its receipt,
        and that has to include the free half.
        """
        try:
            return deterministic_scorer(episode, run)
        except Exception as exc:  # noqa: BLE001 — a scorer never strands an episode
            log.exception(
                "campaign_episode_scoring_failed",
                extra={
                    "case_id": episode.case_id,
                    "arm_id": episode.arm_id,
                    "repeat_index": episode.repeat_index,
                    "error_type": type(exc).__name__,
                },
            )
            return EpisodeScores(
                receipt=EpisodeScoreReceipt(
                    run_id=episode.run_id,
                    primary_metric_available=False,
                    null_reason=f"the free checks raised {type(exc).__name__}"[:200],
                ),
                primary_metric=PRIMARY_METRIC,
                primary_score=None,
                detail={
                    "judges_run": False,
                    "scoring_error": f"{type(exc).__name__}: {exc}"[:500],
                },
            )

    @staticmethod
    def _judge_state(run: EpisodeRun, state: Mapping[str, Any]) -> dict[str, Any]:
        """The state the rubrics read, preferring the persisted snapshot.

        D-3 Option A asks the faithfulness judge to read the abstract
        *and* the reader's ranked chunks for cited papers, and
        `state["evidence"]` is where those chunks are: `EvidenceClaim.
        source_text` is the ranked chunk verbatim (ADR 0016). So the
        snapshot's `evidence` list is handed through under the key the
        metric layer already reads, and a snapshot whose chunk text was
        reduced away hands through the reduced list — the judge falls
        back to abstracts and EL-09 records that it did.

        The live `run.state` is the fallback for the `__call__` path,
        which has no snapshot.
        """
        if not state:
            return dict(run.state)
        report = state.get("report")
        text = str(report.get("text") or "") if isinstance(report, Mapping) else ""
        return {
            "draft_report": text or run.report,
            "papers": list(state.get("papers") or []),
            "citations": list(state.get("citations") or []),
            "paper_analyses": list(state.get("paper_analyses") or []),
            "evidence": list(state.get("evidence") or []),
        }

    @staticmethod
    def _ranked_chunks(state: Mapping[str, Any]) -> dict[str, list[str]]:
        """The snapshot's per-paper ranked chunks, as the judge takes them.

        ADR 0100's D-3 Option A input, and the reason EL-05's snapshot
        keeps chunk text at all: `measure_faithfulness` shows the judge
        each cited paper's ranked chunks beside its abstract when a
        caller supplies them, and records `source_scope` either way. The
        campaign is the caller that can — the chunks are in the file it
        just wrote — and the offline runner and the mock judge stay on
        `abstract_only` by passing nothing.

        A snapshot reduced past level 0 has the digests and not the text
        (EL-05), so this returns the papers whose text survived and the
        judge falls back to abstracts for the rest. That is the honest
        degradation: `source_scope` will say `abstract_only` if nothing
        survived, and a campaign report that averages two scopes is a
        campaign report reading two instruments.
        """
        reader = state.get("reader") if isinstance(state, Mapping) else None
        chunks = reader.get("chunks") if isinstance(reader, Mapping) else None
        if not isinstance(chunks, Mapping):
            return {}
        by_paper: dict[str, list[str]] = {}
        for paper_id, entries in chunks.items():
            if not isinstance(entries, list):
                continue
            texts = [
                str(entry["text"])
                for entry in entries
                if isinstance(entry, Mapping) and str(entry.get("text") or "")
            ]
            if texts:
                by_paper[str(paper_id)] = texts
        return by_paper

    @staticmethod
    def _compute(
        state: Mapping[str, Any],
        query: Any,
        chunks_by_paper: Mapping[str, Sequence[str]] | None,
    ) -> tuple[Mapping[str, Any], str | None]:
        """`src/eval/runner.py::_compute_metrics`, reused rather than copied.

        That function guards each of the five metrics separately and
        documents that it never raises (ADR 0050: a judge failure must
        not cost us the workflow output we already paid for). Reusing it
        is what keeps the campaign's five numbers and the sequential
        runner's five numbers the same numbers — a second implementation
        would be a second definition of `faithfulness`.

        The `cast` is the TypedDict boundary: `ResearchState` is a `dict`
        at runtime and the snapshot is a plain mapping with the keys the
        metrics read, which is exactly what a `TypedDict` annotation
        cannot express for a value built at runtime.
        """
        from src.eval.runner import _compute_metrics

        return _compute_metrics(cast(Any, dict(state)), query, chunks_by_paper)

    def _scores(
        self,
        episode: PlannedEpisode,
        free: EpisodeScores,
        detail: dict[str, Any],
        *,
        metrics: Mapping[str, Any],
        reasons: Mapping[str, str],
        judge_cost_usd: MoneyUsd,
        judge_model_calls: int,
        state: Mapping[str, Any],
    ) -> EpisodeScores:
        """Assemble the scores in the layout the report already reads.

        `detail["metrics"]` is keyed exactly as `MockJudgeScorer` keys
        it, so `report.py::_score_block` reads a live-judged record and a
        mock-judged record through the same path and needed no change.
        `citation_accuracy` sits beside the block rather than inside it
        for the same reason: it is not one of the five the report reads,
        and adding a sixth key to a layout another module parses is how a
        reader starts disagreeing with a writer.
        """
        # A *missing block* is a judge that failed; a block whose `score`
        # is `None` is a judge that answered and had no denominator to
        # divide by (ADR 0100's `empty_report`, `no_cited_claims`,
        # `all_sources_unavailable`). Only the first is an instrument
        # problem, and only the first may trip the judge-failure stop
        # rule — a campaign of blank reports is a finding about the arm.
        failures = tuple(name for name in JUDGED_METRICS if metrics.get(name) is None)
        retention = state.get("retention") if isinstance(state, Mapping) else None
        detail.update(
            {
                "judges_run": True,
                "live_judge": True,
                "judge_model": self._config.eval_judge_model,
                "judge_temperature": self._config.eval_judge_temperature,
                "faithfulness_source_scope": _source_scope(metrics.get("faithfulness")),
                "judge_rubrics_skipped": list(failures),
                "judge_metric_failures": list(failures),
                "judge_failure_reasons": dict(sorted(reasons.items())),
                "judge_cost_usd": judge_cost_usd,
                "judge_model_calls": judge_model_calls,
                "judge_cost_usd_max": f"{self._cap:.6f}",
                "scored_from_persisted_state": bool(state),
                "state_retention_level": (
                    retention.get("level") if isinstance(retention, Mapping) else None
                ),
                "metrics": {
                    "citation_resolution": metrics.get("citation_resolution_rate"),
                    "supported_claim_precision": free.primary_score,
                    "completeness": metrics.get("completeness"),
                    "faithfulness": metrics.get("faithfulness"),
                    "retrieval_recall": metrics.get("retrieval_recall"),
                },
                "citation_accuracy": metrics.get("citation_accuracy"),
            }
        )
        return EpisodeScores(
            receipt=EpisodeScoreReceipt(
                run_id=episode.run_id,
                primary_metric_available=free.receipt.primary_metric_available,
                null_reason=free.receipt.null_reason,
            ),
            primary_metric=PRIMARY_METRIC,
            primary_score=free.primary_score,
            detail=detail,
            judge_cost_usd=judge_cost_usd,
            judge_model_calls=judge_model_calls,
        )


def _source_scope(block: Any) -> str | None:
    """What the faithfulness judge was shown, as the metric recorded it.

    Lifted to the top of the detail because it is the field that decides
    whether two episodes' faithfulness scores may be averaged together
    (ADR 0100: `abstract_only` and `abstract_and_chunks` are different
    instruments), and a reader should not have to open the metric block
    to find out which one a campaign ran.
    """
    if isinstance(block, Mapping) and "source_scope" in block:
        return str(block["source_scope"])
    return None


def _reasons_for(metrics: Mapping[str, Any], failures: str | None) -> dict[str, str]:
    """One reason code per judged metric that has no score.

    `_compute_metrics` returns its failures as one `"; "`-joined string
    of `f"{name}: {type}: {exc}"` fragments, because its own consumer
    writes the whole string into a record field. A stop rule needs them
    apart, so they are split on the metric names rather than on the
    separator — an exception message containing `"; "` would otherwise
    shift every reason after it onto the wrong metric.

    The distinction that matters is budget versus everything else. A
    metric lost to `CostBudgetExceeded` means the judges reached the
    episode's judge allocation and the *next* episode will behave
    identically; a metric lost to a provider error may not recur. Only
    the second should be able to trip the judge-failure stop rule into
    reading an instrument outage where there is a budget line.
    """
    text = failures or ""
    positions: list[tuple[int, str]] = []
    for name in ALL_METRICS:
        needle = f"{name}: "
        cursor = 0
        while (index := text.find(needle, cursor)) >= 0:
            if index == 0 or text[index - 2 : index] == "; ":
                positions.append((index, name))
                break
            cursor = index + 1
    positions.sort()
    fragments: dict[str, str] = {}
    for order, (start, name) in enumerate(positions):
        end = positions[order + 1][0] if order + 1 < len(positions) else len(text)
        fragments[name] = text[start:end].rstrip("; ")
    reasons: dict[str, str] = {}
    for name in JUDGED_METRICS:
        if metrics.get(name) is not None:
            continue
        fragment = fragments.get(name, "")
        reasons[name] = REASON_BUDGET if "CostBudgetExceeded" in fragment else REASON_FAILED
    return reasons


def build_live_judge_scorer(
    config: Settings, *, judge_cost_usd_max: MoneyUsd = "0.000000"
) -> LiveJudgeScorer:
    """Construct the live scorer, or refuse and say which door is shut.

    The mirror of `build_mock_judge_scorer`, and named the same way for
    the same reason: the CLI should read as one line per scorer, and the
    refusal should come from the constructor rather than from the first
    judge call halfway through a funded campaign.
    """
    return LiveJudgeScorer(config, judge_cost_usd_max=judge_cost_usd_max)


__all__ = [
    "ALL_METRICS",
    "JUDGED_METRICS",
    "REASON_BUDGET",
    "REASON_FAILED",
    "REASON_NO_QUERY",
    "LiveJudgeScorer",
    "build_live_judge_scorer",
    "judge_cost_scope",
]
