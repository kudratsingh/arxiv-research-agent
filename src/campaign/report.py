"""The campaign report: quality, cost, latency, errors, lineage.

`summarize()` answers "what did this campaign spend and how many of its
episodes count". This module answers the question after it — **what did
each arm actually produce** — and writes it as one markdown document an
operator or an owner reads without opening a single JSON file.

Three rules shape it.

**Every number is read from a record.** Quality comes from the episode
records' scores, cost and latency from the same records, denominators
from the reconciled ledger, error counts from the durable trajectories
the records point at, and lineage from the sealed campaign manifest and
the sealed per-episode run manifests. Nothing here estimates, samples or
interpolates: a figure this module cannot read, it does not print.

**A metric that did not run is not a zero.** The free scorer runs two of
the five research instruments and records `judges_run: false` with the
three skipped rubric names; a report that showed those three as `0.000`
would be describing an instrument that was never switched on. Each arm's
row says how many of its episodes ran judges, and an unrun metric prints
`not run` with the reason.

**An undetectable error class is not an absent one.** 15 §7.1 maps 03
§8's thirteen failure classes onto the codes that exist on `main`, and
one of them — task understanding — has no runtime code at all. That
class prints `not detected from records` and says why; only a class this
module actually reads a signal for prints a count, and only then does
`0` mean zero.

Three more classes used to print it, because eight degradation codes
existed only as log lines and a campaign record keeps no log. ADR 0097
put those eight on the trajectory as `degradation.recorded`, so
planning/decomposition is now a record class, and retrieval miss and
synthesis/organization are counted on a judge-free pass as a floor —
their rubric half is still missing and their note still says so.

The report is derived, never authoritative: it is rebuilt from the
records on every call, and it **writes nothing** — the ledger is
reconciled in memory, because a report that rewrote the ledger would have
changed the campaign it claims to be describing. `status` is the verb
that rewrites it. `python -m src.campaign report --campaign-id <id>`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import fmean, stdev
from typing import Annotated, Any, Final, Literal

from pydantic import Field

from src.campaign.errors import CampaignError
from src.campaign.execute import EpisodeRecord, load_episode_records
from src.campaign.ledger import (
    DenominatorReport,
    LedgerStatus,
    read_outcomes,
    reconcile,
)
from src.campaign.planner import load_campaign, rebuild_plan
from src.campaign.summary import CampaignSummary, summarize
from src.contracts.kernel import (
    Digest,
    MoneyUsd,
    Rfc3339Utc,
    StrictContractModel,
    sha256_digest,
)
from src.contracts.run_manifest import ManifestFileStore
from src.eval.stats import (
    PairedSample,
    paired_bootstrap_delta,
    small_sample_caveat,
    wilson_interval,
)

REPORT_SCHEMA_VERSION: Final[str] = "1.0.0"

#: The five research instruments a campaign row records, in the order
#: `docs/eval.md` prints them. Four are `src/eval/metrics.RESEARCH_RUBRICS`
#: and the fifth — citation resolution — is the deterministic check that
#: rides beside them.
MetricId = Literal[
    "supported_claim_precision",
    "citation_resolution_rate",
    "completeness",
    "faithfulness",
    "retrieval_recall",
]

METRIC_IDS: Final[tuple[MetricId, ...]] = (
    "supported_claim_precision",
    "citation_resolution_rate",
    "completeness",
    "faithfulness",
    "retrieval_recall",
)

#: Which instrument produces each metric. The split is the one ADR 0050
#: made for cost and 14 §1 made for trust: a deterministic check and a
#: model judge are not the same kind of evidence and never share a column
#: without saying which is which.
JUDGE_METRICS: Final[frozenset[str]] = frozenset(
    {"completeness", "faithfulness", "retrieval_recall"}
)

#: What each metric's pooled rate is over. Both halves come out of the
#: episode's own scores, so a rate in this report is a ratio of two
#: counts a reader can find in `episode-record.json`.
_METRIC_UNITS: Final[Mapping[str, str]] = {
    "supported_claim_precision": "claims",
    "citation_resolution_rate": "citations",
    "completeness": "expected topics",
    "faithfulness": "decided claims",
    "retrieval_recall": "expected topics",
}


# ---------------------------------------------------------------------------
# The failure taxonomy, and what each class can actually be read from
# ---------------------------------------------------------------------------


Detection = Literal["record", "judge", "undetectable"]


@dataclass(frozen=True)
class TaxonomyClass:
    """One of 03 §8's thirteen classes, and how 15 §7.1 says to find it.

    Attributes:
        class_id: Stable id for the row.
        label: 15 §7.1's own wording for the class.
        detection: ``record`` when a campaign record carries the signal;
            ``judge`` when only a rubric score can see it, which makes
            the count conditional on the judges having run; and
            ``undetectable`` when the class's codes exist only as log
            lines or not at all.
        signals: What this module reads, named so a reader can check it.
        note: Why an ``undetectable`` class is undetectable, or what a
            ``judge`` class is conditional on.
        record_signal: Set on a ``judge`` class that ADR 0097 also gave a
            record-borne signal. Such a class is counted even on a
            judge-free pass — the count is then a floor rather than the
            whole class, which is what its note has to say.
    """

    class_id: str
    label: str
    detection: Detection
    signals: tuple[str, ...]
    note: str | None = None
    record_signal: bool = False


#: The thirteen classes, in 15 §7.1's order. Codes named in that table
#: but carried only by `src/observability/logging.py` are called out
#: rather than silently counted as zero — a campaign record keeps no log.
TAXONOMY: Final[tuple[TaxonomyClass, ...]] = (
    TaxonomyClass(
        class_id="task_understanding",
        label="task understanding",
        detection="undetectable",
        signals=(),
        note=(
            "15 §7.1: no code; a quality judgement, not a runtime event. Judged, "
            "not detected."
        ),
    ),
    TaxonomyClass(
        class_id="planning_decomposition",
        label="planning / decomposition",
        detection="record",
        signals=(
            "trajectory degradation.recorded (error_code): "
            "planner_plan_fallback_to_query, planner_response_unparseable",
        ),
        note=(
            "ADR 0097 put both codes on the trajectory. Until then they were "
            "log-only and this class read `not detected from records`."
        ),
    ),
    TaxonomyClass(
        class_id="retrieval_miss",
        label="retrieval miss",
        detection="judge",
        signals=(
            "scores.metrics.retrieval_recall",
            "trajectory degradation.recorded (error_code): "
            "search_empty_keeping_prior_papers",
        ),
        note=(
            "counted as expected topics the retrieval-recall rubric left uncovered, "
            "plus ADR 0097's empty-round degradations, which are counted whether or "
            "not the judges ran."
        ),
        record_signal=True,
    ),
    TaxonomyClass(
        class_id="source_quality_freshness",
        label="source-quality / freshness miss",
        detection="record",
        signals=("trajectory source.rejected (rejection_codes)",),
    ),
    TaxonomyClass(
        class_id="parsing_chunking_ranking",
        label="parsing / chunking / ranking",
        detection="record",
        signals=(
            "trajectory tool.failed / action.failed (error_class)",
            "trajectory degradation.recorded (error_code): "
            "reader_degraded_to_abstract_only, reader_paper_abstract_only",
        ),
        note=(
            "ADR 0097 closed the half of this class that was invisible: a failed "
            "extraction already reached the trajectory, a degraded one reached "
            "nothing."
        ),
    ),
    TaxonomyClass(
        class_id="evidence_to_claim",
        label="evidence-to-claim reasoning",
        detection="record",
        signals=(
            "scores.claim_count - scores.supported_claim_count",
            "trajectory claim.evidence_unlinked",
        ),
    ),
    TaxonomyClass(
        class_id="synthesis_organization",
        label="synthesis / organization",
        detection="judge",
        signals=(
            "scores.metrics.completeness",
            "episode reason no_report_produced",
            "trajectory degradation.recorded (error_code): "
            "synthesizer_response_unparseable, synthesizer_retry_budget_exhausted",
        ),
        note=(
            "counted as expected topics the completeness rubric left uncovered, plus "
            "ADR 0097's synthesizer degradations, which are counted whether or not "
            "the judges ran."
        ),
        record_signal=True,
    ),
    TaxonomyClass(
        class_id="citation_provenance",
        label="citation / provenance",
        detection="record",
        signals=(
            "scores.citation_resolution_rate.unresolved",
            "trajectory degradation.recorded (error_code): "
            "synthesizer_citations_dropped",
        ),
        note=(
            "an unresolved citation was always countable; ADR 0097 added the one "
            "the synthesizer dropped before it could be resolved at all."
        ),
    ),
    TaxonomyClass(
        class_id="verification",
        label="verification false pass / false fail",
        detection="record",
        signals=("trajectory verification.completed (verdict), verification.malformed",),
    ),
    TaxonomyClass(
        class_id="tool_runtime",
        label="tool / runtime failure",
        detection="record",
        signals=(
            "trajectory tool.failed / action.failed / run.failed / failure.recorded",
            "episode reason provider_error, tool_error, schema_error, "
            "infrastructure_lost, judge_partial_failure",
        ),
    ),
    TaxonomyClass(
        class_id="budget_timeout_stop",
        label="budget / timeout / premature stop",
        detection="record",
        signals=(
            "ledger status budget_stopped / timed_out",
            "episode reason timeout, episode_budget_exhausted, "
            "campaign_budget_exhausted, operator_interrupt",
            "trajectory run.budget_stopped / budget.exhausted",
        ),
    ),
    TaxonomyClass(
        class_id="safety_policy_refusal",
        label="safety / policy refusal",
        detection="record",
        signals=(
            "episode reason privacy_or_security_stop, benchmark_contamination, "
            "policy_error",
            "trajectory action.skipped (reason_code)",
        ),
    ),
    TaxonomyClass(
        class_id="human_interface",
        label="human-interface failure",
        detection="record",
        signals=("trajectory hitl.timed_out / hitl.cancelled",),
    ),
)

#: Episode reasons that belong to one taxonomy class each. A reason the
#: table does not name is reported under `tool_runtime` rather than
#: dropped, because an unclassified failure is still a failure.
_REASON_CLASS: Final[Mapping[str, str]] = {
    "timeout": "budget_timeout_stop",
    "episode_budget_exhausted": "budget_timeout_stop",
    "campaign_budget_exhausted": "budget_timeout_stop",
    "operator_interrupt": "budget_timeout_stop",
    "privacy_or_security_stop": "safety_policy_refusal",
    "benchmark_contamination": "safety_policy_refusal",
    "policy_error": "safety_policy_refusal",
    "no_report_produced": "synthesis_organization",
    "provider_error": "tool_runtime",
    "tool_error": "tool_runtime",
    "schema_error": "tool_runtime",
    "infrastructure_lost": "tool_runtime",
    "judge_partial_failure": "tool_runtime",
    "manifest_mismatch": "tool_runtime",
    "checkpoint_incompatible": "tool_runtime",
    "integrity_failure": "tool_runtime",
    "approval_missing": "safety_policy_refusal",
    "approval_expired": "safety_policy_refusal",
    "approval_revoked": "safety_policy_refusal",
    "unknown": "tool_runtime",
}

#: Trajectory event types that instantiate a class, with the payload key
#: that names the code. `None` means the event itself is the code.
_EVENT_CLASS: Final[Mapping[str, tuple[str, str | None]]] = {
    "source.rejected": ("source_quality_freshness", "rejection_codes"),
    "tool.failed": ("parsing_chunking_ranking", "error_class"),
    "action.failed": ("parsing_chunking_ranking", "error_class"),
    "claim.evidence_unlinked": ("evidence_to_claim", "reason_code"),
    "verification.completed": ("verification", "verdict"),
    "verification.malformed": ("verification", "error_class"),
    "repair.failed": ("verification", "error_class"),
    "repair.exhausted": ("verification", "stop_reason_code"),
    "run.failed": ("tool_runtime", "failure_class"),
    "failure.recorded": ("tool_runtime", "failure_class"),
    "run.budget_stopped": ("budget_timeout_stop", "stop_reason_code"),
    "budget.exhausted": ("budget_timeout_stop", None),
    "run.cancelled": ("budget_timeout_stop", None),
    "action.skipped": ("safety_policy_refusal", "reason_code"),
    "hitl.timed_out": ("human_interface", None),
    "hitl.cancelled": ("human_interface", "reason_code"),
    "checkpoint.invalid": ("tool_runtime", "failure_codes"),
}

#: The event ADR 0097 added, kept out of `_EVENT_CLASS` because its
#: class is in its payload rather than fixed by its type — it is the
#: only event in the contract that can land in any of five classes.
DEGRADATION_EVENT: Final[str] = "degradation.recorded"

#: A `verification.completed` whose verdict is `pass` is the check
#: working, not a failure. Only these two verdicts are counted.
_VERIFICATION_FAILURE_VERDICTS: Final[frozenset[str]] = frozenset({"fail", "abstain"})


# ---------------------------------------------------------------------------
# The report, as an object before it is markdown
# ---------------------------------------------------------------------------


class MetricRow(StrictContractModel):
    """One research metric, for one arm, pooled over its episodes.

    Attributes:
        metric_id: The instrument.
        instrument: `deterministic` or `llm_judge`.
        episodes_scored: Episodes whose record carried this metric.
        episodes_missing: Episodes whose record did not — a skipped
            rubric or a null-metric episode. Published beside the scored
            count so a rate over four episodes cannot be read as a rate
            over sixty.
        numerator: Pooled successes, summed over the scored episodes.
        denominator: Pooled trials, in `unit`.
        unit: What the denominator counts.
        rate: `numerator / denominator`, or `None` at a zero denominator.
        interval_low: Wilson lower bound, or `None`.
        interval_high: Wilson upper bound, or `None`.
        mean_episode_score: The unweighted mean of the per-episode
            scores. Beside the pooled rate rather than instead of it: the
            two differ whenever episodes have different denominators, and
            a reader deserves to see that rather than be handed whichever
            one the author preferred.
        abstentions: Claims the instrument declined to decide. Excluded
            from the denominator and reported, never silently dropped.
        not_run_reason: Why the metric has no numbers at all.
    """

    metric_id: str
    instrument: Literal["deterministic", "llm_judge"]
    episodes_scored: Annotated[int, Field(ge=0)]
    episodes_missing: Annotated[int, Field(ge=0)]
    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=0)]
    unit: str
    rate: float | None
    interval_low: float | None
    interval_high: float | None
    mean_episode_score: float | None
    abstentions: Annotated[int, Field(ge=0)] = 0
    not_run_reason: str | None = None
    interval_label: str = "pooled, assumes independence — not for gating"


class VarianceRow(StrictContractModel):
    """Per-query repeat variation for one metric and arm."""

    query_id: str
    arm_id: str
    metric_id: str
    episodes_scored: Annotated[int, Field(ge=0)]
    mean: float | None
    sd: float | None
    minimum: float | None
    maximum: float | None


class VarianceInterval(StrictContractModel):
    """Query-first nested bootstrap interval for an arm metric."""

    arm_id: str
    metric_id: str
    query_count: Annotated[int, Field(ge=0)]
    episodes_scored: Annotated[int, Field(ge=0)]
    point: float | None
    interval_low: float | None
    interval_high: float | None
    seed: Annotated[int, Field(ge=0)]
    resamples: Annotated[int, Field(ge=1)]
    method: str = "query-first resampling, then repeats"


class BaselineDifficultyRow(StrictContractModel):
    """Difficulty values by query, from the baseline arm's scores."""

    query_id: str
    arm_id: str
    metrics: Mapping[str, float | None]


class ArmQuality(StrictContractModel):
    """One arm's five metrics, and whether its judges ran."""

    arm_id: str
    episodes: Annotated[int, Field(ge=0)]
    scored_episodes: Annotated[int, Field(ge=0)]
    null_metric_episodes: Annotated[int, Field(ge=0)]
    judges_run_episodes: Annotated[int, Field(ge=0)]
    skipped_rubrics: tuple[str, ...]
    metrics: tuple[MetricRow, ...]


class ArmCost(StrictContractModel):
    """One arm's spend, model calls and latency, all from its records."""

    arm_id: str
    episodes: Annotated[int, Field(ge=0)]
    workflow_usd: MoneyUsd
    judge_usd: MoneyUsd
    total_usd: MoneyUsd
    model_calls: Annotated[int, Field(ge=0)]
    judge_model_calls: Annotated[int, Field(ge=0)]
    latency_total_seconds: float
    latency_mean_seconds: float | None
    latency_p50_seconds: float | None
    latency_p95_seconds: float | None
    latency_max_seconds: float | None


class TaxonomyRow(StrictContractModel):
    """One failure class, counted or explicitly not counted."""

    class_id: str
    label: str
    detection: str
    signals: tuple[str, ...]
    counted: bool
    episodes: Annotated[int, Field(ge=0)]
    occurrences: Annotated[int, Field(ge=0)]
    codes: Mapping[str, int]
    note: str | None = None


class ArmLineage(StrictContractModel):
    """What identifies an arm's execution, read from sealed material.

    Attributes:
        arm_digest: sha256 over the sealed `ArmDeclaration` in the
            campaign manifest — the arm as the protocol froze it, and
            itself covered by the protocol digest.
        graph_digest: The compiled graph the episodes actually ran, read
            from one sealed run manifest. Two arms can share one: arms A
            and B differ by settings rather than by graph shape (15 §3.1),
            and a lineage table that hid that would be describing a
            difference the run did not have.
        graph_digest_read_from: The run id the graph digest was read
            from, so the claim is checkable against one file.
    """

    arm_id: str
    selector: str
    runnable: bool
    status: str
    episodes: Annotated[int, Field(ge=0)]
    arm_digest: Digest
    graph_digest: str | None
    graph_capabilities: tuple[str, ...]
    graph_digest_read_from: str | None
    policy_version: str | None


class EpisodeLineageRow(StrictContractModel):
    """One episode's identity, for the traceability appendix."""

    case_id: str
    arm_id: str
    repeat_index: Annotated[int, Field(ge=0)]
    run_id: str
    ledger_status: str
    manifest_digest: str
    trajectory_events: Annotated[int, Field(ge=0)]


class CampaignReport(StrictContractModel):
    """Everything the markdown prints, before it is printed."""

    schema_kind: Literal["campaign-report"] = "campaign-report"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: str
    generated_at: Rfc3339Utc
    directory: str
    corpus_mode: str
    stage: str
    protocol_id: str
    protocol_digest: Digest
    lock_digest: Digest
    repeats: Annotated[int, Field(ge=1)]
    seed: Annotated[int, Field(ge=0)]
    denominators: DenominatorReport
    records_read: Annotated[int, Field(ge=0)]
    trajectories_read: Annotated[int, Field(ge=0)]
    trajectory_events_read: Annotated[int, Field(ge=0)]
    trajectories_unavailable: tuple[str, ...]
    workflow_usd: MoneyUsd
    judge_usd: MoneyUsd
    harness_usd: MoneyUsd
    total_usd: MoneyUsd
    model_calls: Annotated[int, Field(ge=0)]
    judge_model_calls: Annotated[int, Field(ge=0)]
    quality: tuple[ArmQuality, ...]
    variance: tuple[VarianceRow, ...] = ()
    variance_intervals: tuple[VarianceInterval, ...] = ()
    baseline_difficulty: tuple[BaselineDifficultyRow, ...] = ()
    small_sample_caveat: str | None = None
    cost: tuple[ArmCost, ...]
    taxonomy: tuple[TaxonomyRow, ...]
    lineage: tuple[ArmLineage, ...]
    episodes: tuple[EpisodeLineageRow, ...]
    summary: CampaignSummary


# ---------------------------------------------------------------------------
# Reading the records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EpisodeEvents:
    """One episode's trajectory, reduced to what the taxonomy reads."""

    run_id: str
    count: int
    rows: tuple[tuple[str, str, tuple[str, ...], Mapping[str, Any]], ...]


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _trajectory_path(record: EpisodeRecord, sink_root: Path | None) -> Path:
    """Where this episode's durable events are.

    The record names its own run directory, which is the only path that
    is guaranteed to be the one the events were written to. `sink_root`
    overrides it for the case the whole tree was moved after the run, and
    then the run id — not the recorded path — is what locates the file.
    """
    if sink_root is not None:
        return sink_root / "runs" / record.run_id / record.trajectory.events_file
    return Path(record.trajectory.run_directory) / record.trajectory.events_file


def _read_events(record: EpisodeRecord, sink_root: Path | None) -> _EpisodeEvents | None:
    """Read one episode's events, or `None` when there are none to read.

    Raises:
        CampaignError: The file exists and holds a different number of
            events than the record's `trajectory-ref` counted. A report
            built on a truncated trajectory is worse than one that says
            the trajectory is missing.
    """
    if not record.trajectory.durable:
        return None
    path = _trajectory_path(record, sink_root)
    if not path.is_file():
        return None
    rows: list[tuple[str, str, tuple[str, ...], Mapping[str, Any]]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            payload = event.get("payload")
            rows.append(
                (
                    str(event["event_type"]),
                    str(event["status"]),
                    tuple(str(code) for code in event.get("reason_codes") or ()),
                    payload if isinstance(payload, Mapping) else {},
                )
            )
    except (OSError, KeyError, ValueError) as exc:
        raise CampaignError(
            f"trajectory for {record.run_id} is unreadable: {exc}"
        ) from exc
    if len(rows) != record.trajectory.event_count:
        raise CampaignError(
            f"trajectory for {record.run_id} holds {len(rows)} events; the episode "
            f"record counted {record.trajectory.event_count}"
        )
    return _EpisodeEvents(run_id=record.run_id, count=len(rows), rows=tuple(rows))


def _score_block(record: EpisodeRecord, key: str) -> Mapping[str, Any] | None:
    """Find one metric's block under either layout a record may use.

    A judged episode groups its five rubrics under `metrics`; the free
    scorer writes its two at the top level. Both are read here rather
    than normalised on write, because records already on disk cannot be.
    """
    metrics = record.scores.get("metrics")
    if isinstance(metrics, Mapping):
        block = metrics.get(key)
        if isinstance(block, Mapping):
            return block
    block = record.scores.get(key)
    return block if isinstance(block, Mapping) else None


def _counts_for(record: EpisodeRecord, metric_id: str) -> tuple[int, int, int] | None:
    """Return `(numerator, denominator, abstentions)` for one metric.

    `None` means the record does not carry the metric at all, which is a
    different statement from a zero denominator and is reported as one.
    """
    if metric_id == "supported_claim_precision":
        claims = record.scores.get("claim_count")
        supported = record.scores.get("supported_claim_count")
        if not isinstance(claims, int) or not isinstance(supported, int):
            return None
        return (supported, claims, 0)
    if metric_id == "citation_resolution_rate":
        block = _score_block(record, "citation_resolution_rate") or _score_block(
            record, "citation_resolution"
        )
        if block is None:
            return None
        resolved = block.get("resolved")
        total = block.get("total_citations")
        if not isinstance(resolved, int) or not isinstance(total, int):
            return None
        return (resolved, total, 0)
    if metric_id in ("completeness", "retrieval_recall"):
        block = _score_block(record, metric_id)
        if block is None:
            return None
        if "score" in block and block.get("score") is None:
            return None
        covered = block.get("covered_topics")
        total = block.get("total_topics")
        if not isinstance(covered, int) or not isinstance(total, int):
            return None
        return (covered, total, 0)
    block = _score_block(record, "faithfulness")
    if block is None:
        return None
    if "score" in block and block.get("score") is None:
        return None
    supported = block.get("supported")
    unsupported = block.get("unsupported")
    unavailable = block.get("source_unavailable")
    if not all(isinstance(value, int) for value in (supported, unsupported, unavailable)):
        return None
    assert isinstance(supported, int) and isinstance(unsupported, int)
    assert isinstance(unavailable, int)
    return (supported, supported + unsupported, unavailable)


def _metric_score(record: EpisodeRecord, metric_id: str) -> float | None:
    """Read one episode score, preserving judge ``None`` as unscored."""
    block = _score_block(record, metric_id)
    if metric_id == "supported_claim_precision":
        numerator = record.scores.get("supported_claim_count")
        denominator = record.scores.get("claim_count")
        return (
            numerator / denominator
            if isinstance(numerator, int) and isinstance(denominator, int) and denominator
            else None
        )
    if block is not None and "score" in block:
        value = block.get("score")
        return float(value) if isinstance(value, (int, float)) else None
    counts = _counts_for(record, metric_id)
    if counts is None or counts[1] == 0:
        return None
    return counts[0] / counts[1]


def _variance_rows(
    records: Sequence[EpisodeRecord],
) -> tuple[VarianceRow, ...]:
    grouped: dict[tuple[str, str, MetricId], list[float]] = {}
    for record in records:
        for metric_id in METRIC_IDS:
            score = _metric_score(record, metric_id)
            if score is not None:
                grouped.setdefault((record.case_id, record.arm_id, metric_id), []).append(score)
    rows: list[VarianceRow] = []
    for (query_id, arm_id, metric_id), values in sorted(grouped.items()):
        rows.append(
            VarianceRow(
                query_id=query_id,
                arm_id=arm_id,
                metric_id=metric_id,
                episodes_scored=len(values),
                mean=fmean(values),
                sd=stdev(values) if len(values) > 1 else 0.0,
                minimum=min(values),
                maximum=max(values),
            )
        )
    return tuple(rows)


def _variance_intervals(
    records: Sequence[EpisodeRecord], *, seed: int, resamples: int = 10_000
) -> tuple[VarianceInterval, ...]:
    grouped: dict[tuple[str, MetricId], dict[str, list[float]]] = {}
    for record in records:
        for metric_id in METRIC_IDS:
            score = _metric_score(record, metric_id)
            if score is not None:
                grouped.setdefault((record.arm_id, metric_id), {}).setdefault(
                    record.case_id, []
                ).append(score)
    rows: list[VarianceInterval] = []
    for (arm_id, metric_id), by_query in sorted(grouped.items()):
        samples = tuple(
            PairedSample(query_id, (0.0,), tuple(values))
            for query_id, values in sorted(by_query.items())
        )
        result = paired_bootstrap_delta(samples, seed=seed, resamples=resamples)
        rows.append(
            VarianceInterval(
                arm_id=arm_id,
                metric_id=metric_id,
                query_count=result.tasks,
                episodes_scored=sum(len(values) for values in by_query.values()),
                point=result.point,
                interval_low=result.interval.low,
                interval_high=result.interval.high,
                seed=seed,
                resamples=resamples,
            )
        )
    return tuple(rows)


def _difficulty_rows(
    records: Sequence[EpisodeRecord], *, baseline_arm: str = "A"
) -> tuple[BaselineDifficultyRow, ...]:
    by_query: dict[str, dict[str, list[float]]] = {}
    for record in records:
        if record.arm_id != baseline_arm:
            continue
        for metric_id in METRIC_IDS:
            score = _metric_score(record, metric_id)
            if score is not None:
                by_query.setdefault(record.case_id, {}).setdefault(metric_id, []).append(score)
    return tuple(
        BaselineDifficultyRow(
            query_id=query_id,
            arm_id=baseline_arm,
            metrics={metric: fmean(values) for metric, values in sorted(metrics.items())},
        )
        for query_id, metrics in sorted(by_query.items())
    )


def _skipped_rubrics(records: Sequence[EpisodeRecord]) -> tuple[str, ...]:
    """Every rubric any of these episodes recorded as not run.

    The union rather than the intersection: a rubric skipped in one
    episode is enough for the arm's row to say so, since the report never
    prints a partial instrument as if it had run throughout.
    """
    skipped: set[str] = set()
    for record in records:
        value = record.scores.get("judge_rubrics_skipped")
        if isinstance(value, list):
            skipped.update(str(item) for item in value)
    return tuple(sorted(skipped))


def _metric_row(metric_id: str, records: Sequence[EpisodeRecord]) -> MetricRow:
    """Pool one metric across an arm's episodes into a single reported row.

    Counts are pooled before the rate is taken, so an episode with more
    claims weighs more than one with two — the interval is then about the
    observations, not about a mean of per-episode ratios. An episode that
    did not carry the metric is skipped and counted as missing, and a
    metric no episode carried prints `not run` with the reason instead of
    a zero.
    """
    instrument: Literal["deterministic", "llm_judge"] = (
        "llm_judge" if metric_id in JUDGE_METRICS else "deterministic"
    )
    numerator = 0
    denominator = 0
    abstentions = 0
    scores: list[float] = []
    scored = 0
    for record in records:
        counts = _counts_for(record, metric_id)
        if counts is None:
            continue
        scored += 1
        numerator += counts[0]
        denominator += counts[1]
        abstentions += counts[2]
        if counts[1]:
            scores.append(counts[0] / counts[1])
    missing = len(records) - scored
    not_run: str | None = None
    if scored == 0:
        skipped = _skipped_rubrics(records)
        not_run = (
            f"the {metric_id} rubric was skipped in every episode"
            if metric_id in skipped
            else "no episode record carried this metric"
        )
    interval = wilson_interval(numerator, denominator) if denominator else None
    return MetricRow(
        metric_id=metric_id,
        instrument=instrument,
        episodes_scored=scored,
        episodes_missing=missing,
        numerator=numerator,
        denominator=denominator,
        unit=_METRIC_UNITS[metric_id],
        rate=(numerator / denominator) if denominator else None,
        interval_low=interval.low if interval else None,
        interval_high=interval.high if interval else None,
        mean_episode_score=(sum(scores) / len(scores)) if scores else None,
        abstentions=abstentions,
        not_run_reason=not_run,
    )


def _percentile(values: Sequence[float], quantile: float) -> float | None:
    """Nearest-rank percentile of an observed sample.

    An order statistic of the numbers in hand, not an estimator of a
    population quantity — so it belongs here rather than in
    `src/eval/stats.py`, which owns the estimators and their intervals.
    """
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(quantile * len(ordered) + 0.999999) - 1))
    return ordered[index]


def _arm_quality(arm_id: str, records: Sequence[EpisodeRecord]) -> ArmQuality:
    """One arm's quality block: every metric, plus what did not run.

    The counts beside the rows are what makes them readable — how many
    episodes were scored at all, how many ran judges, which rubrics were
    skipped — so a low rate can be told apart from a thin sample.
    """
    judges_run = sum(1 for record in records if record.scores.get("judges_run") is True)
    return ArmQuality(
        arm_id=arm_id,
        episodes=len(records),
        scored_episodes=sum(1 for record in records if record.primary_metric_available),
        null_metric_episodes=sum(
            1 for record in records if record.ledger_status is LedgerStatus.NULL_METRIC
        ),
        judges_run_episodes=judges_run,
        skipped_rubrics=_skipped_rubrics(records),
        metrics=tuple(_metric_row(metric_id, records) for metric_id in METRIC_IDS),
    )


def _arm_cost(arm_id: str, records: Sequence[EpisodeRecord]) -> ArmCost:
    """One arm's spend and latency, with workflow and judge kept apart.

    ADR 0050's split survives all the way to the printed table: the two
    categories are summed separately and a total is offered beside them
    rather than instead of them. Money is summed as `Decimal`, because a
    campaign total is an accounting figure and not a float.
    """
    workflow = sum((Decimal(record.workflow_cost_usd) for record in records), Decimal("0"))
    judge = sum((Decimal(record.judge_cost_usd) for record in records), Decimal("0"))
    latencies = [record.elapsed_seconds for record in records]
    return ArmCost(
        arm_id=arm_id,
        episodes=len(records),
        workflow_usd=f"{workflow:.6f}",
        judge_usd=f"{judge:.6f}",
        total_usd=f"{workflow + judge:.6f}",
        model_calls=sum(record.model_calls for record in records),
        judge_model_calls=sum(record.judge_model_calls for record in records),
        latency_total_seconds=round(sum(latencies), 3),
        latency_mean_seconds=(
            round(sum(latencies) / len(latencies), 3) if latencies else None
        ),
        latency_p50_seconds=_round(_percentile(latencies, 0.50)),
        latency_p95_seconds=_round(_percentile(latencies, 0.95)),
        latency_max_seconds=round(max(latencies), 3) if latencies else None,
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _taxonomy_rows(
    records: Sequence[EpisodeRecord],
    events: Mapping[str, _EpisodeEvents],
    *,
    judges_ran: bool,
) -> tuple[TaxonomyRow, ...]:
    """Count every class this campaign's records can actually see."""
    occurrences: dict[str, int] = {entry.class_id: 0 for entry in TAXONOMY}
    episodes: dict[str, set[str]] = {entry.class_id: set() for entry in TAXONOMY}
    codes: dict[str, Counter[str]] = {entry.class_id: Counter() for entry in TAXONOMY}

    def hit(class_id: str, code: str, run_id: str, *, times: int = 1) -> None:
        occurrences[class_id] += times
        episodes[class_id].add(run_id)
        codes[class_id][code] += times

    for record in records:
        if record.reason is not None:
            reason = record.reason.value
            hit(_REASON_CLASS.get(reason, "tool_runtime"), reason, record.run_id)
        if record.ledger_status in (LedgerStatus.BUDGET_STOPPED, LedgerStatus.TIMED_OUT):
            hit("budget_timeout_stop", record.ledger_status.value, record.run_id)

        claims = record.scores.get("claim_count")
        supported = record.scores.get("supported_claim_count")
        if isinstance(claims, int) and isinstance(supported, int) and claims > supported:
            hit(
                "evidence_to_claim",
                "unsupported_claim_count",
                record.run_id,
                times=claims - supported,
            )
        citation = _score_block(record, "citation_resolution_rate") or _score_block(
            record, "citation_resolution"
        )
        if citation is not None:
            unresolved = citation.get("unresolved")
            if isinstance(unresolved, list) and unresolved:
                hit(
                    "citation_provenance",
                    "citation_resolution_rate",
                    record.run_id,
                    times=len(unresolved),
                )
        for metric_id, class_id in (
            ("retrieval_recall", "retrieval_miss"),
            ("completeness", "synthesis_organization"),
        ):
            block = _score_block(record, metric_id)
            if block is None:
                continue
            covered = block.get("covered_topics")
            total = block.get("total_topics")
            if isinstance(covered, int) and isinstance(total, int) and total > covered:
                hit(class_id, metric_id, record.run_id, times=total - covered)

        episode_events = events.get(record.run_id)
        if episode_events is None:
            continue
        for event_type, _status, _reasons, payload in episode_events.rows:
            if event_type == DEGRADATION_EVENT:
                # ADR 0097. The one event whose class is read off the
                # payload rather than out of a table here, and
                # deliberately: the site that degraded named its own
                # class, so this module keeps no second code-to-class
                # mapping that could drift from the eight call sites. An
                # unrecognised class is counted under `tool_runtime`
                # rather than dropped — the rule `_REASON_CLASS` uses,
                # for its reason: an unclassified degradation is still a
                # degradation.
                class_id = str(payload.get("taxonomy_class") or "")
                hit(
                    class_id if class_id in occurrences else "tool_runtime",
                    str(payload.get("error_code") or event_type),
                    record.run_id,
                )
                continue
            mapped = _EVENT_CLASS.get(event_type)
            if mapped is None:
                continue
            class_id, key = mapped
            if event_type == "verification.completed":
                verdict = str(payload.get("verdict", ""))
                if verdict not in _VERIFICATION_FAILURE_VERDICTS:
                    continue
                hit(class_id, f"verification.{verdict}", record.run_id)
                continue
            if key is None:
                hit(class_id, event_type, record.run_id)
                continue
            value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    hit(class_id, str(item), record.run_id)
            elif value:
                hit(class_id, str(value), record.run_id)
            else:
                hit(class_id, event_type, record.run_id)

    rows: list[TaxonomyRow] = []
    for entry in TAXONOMY:
        # ADR 0097 added a third way to be countable: a `judge` class
        # that also carries record-borne degradations is counted on a
        # judge-free pass, and its note says the number is a floor. The
        # alternative — printing `not measured` over a trajectory that
        # holds the evidence — is the same laundering this module
        # refuses to do in the other direction.
        counted = (
            entry.detection == "record"
            or entry.record_signal
            or (entry.detection == "judge" and judges_ran)
        )
        note = entry.note
        if entry.detection == "judge" and not judges_ran:
            preamble = (
                "the rubric did not run in this campaign, so this count is only the "
                "degradations the records carry, not the whole class. "
                if entry.record_signal
                else "judges did not run in this campaign, so this class was not "
                "measured. "
            )
            note = (preamble + (entry.note or "")).strip()
        rows.append(
            TaxonomyRow(
                class_id=entry.class_id,
                label=entry.label,
                detection=entry.detection,
                signals=entry.signals,
                counted=counted,
                episodes=len(episodes[entry.class_id]) if counted else 0,
                occurrences=occurrences[entry.class_id] if counted else 0,
                codes=dict(sorted(codes[entry.class_id].items())) if counted else {},
                note=note,
            )
        )
    return tuple(rows)


def _arm_lineage(
    arm: Any,
    records: Sequence[EpisodeRecord],
    directory: Path,
    plan_paths: Mapping[str, str],
) -> ArmLineage:
    """Identity for one arm: the sealed declaration, plus a sealed graph.

    The declaration digest is computed over the manifest's own
    `ArmDeclaration`, so it moves if and only if the protocol's arm moved.
    The graph digest is *read* from the sealed run manifest of the arm's
    first episode, and the report names that episode so the claim can be
    checked against one file rather than taken on trust.
    """
    graph_digest: str | None = None
    policy_version: str | None = None
    capabilities: tuple[str, ...] = ()
    read_from: str | None = None
    if records:
        first = min(records, key=lambda record: record.design_index)
        path = plan_paths.get(first.run_id)
        if path is not None:
            manifest = ManifestFileStore().load(directory / path)
            policy = manifest.payload.policy
            graph_digest = policy.graph_digest
            policy_version = policy.policy_version
            capabilities = tuple(policy.graph_capabilities)
            read_from = first.run_id
    return ArmLineage(
        arm_id=arm.arm_id,
        selector=arm.selector,
        runnable=arm.runnable,
        status=str(arm.status),
        episodes=len(records),
        arm_digest=sha256_digest(arm),
        graph_digest=graph_digest,
        graph_capabilities=capabilities,
        graph_digest_read_from=read_from,
        policy_version=policy_version,
    )


def build_report(
    root: Path,
    campaign_id: str,
    *,
    sink_root: Path | None = None,
    generated_at: Rfc3339Utc | None = None,
) -> CampaignReport:
    """Read a finished campaign's records and build its report.

    Args:
        root: Directory holding campaign roots.
        campaign_id: The campaign to report on.
        sink_root: Override for the durable trajectory root, for a tree
            that moved after the run. Defaults to the path each episode
            record names.
        generated_at: Report timestamp. Defaults to now; a caller that
            needs a byte-stable report supplies one.

    Returns:
        The report.

    Raises:
        CampaignError: The campaign directory is absent or unreadable, or
            a trajectory disagrees with the record that points at it.
    """
    directory = root / campaign_id
    if not directory.is_dir():
        raise CampaignError(f"no campaign directory at {directory}")
    manifest, specs = load_campaign(directory)
    plan = rebuild_plan(manifest, specs)
    stamp = generated_at or _stamp(datetime.now(UTC))
    # Reconciled in memory and never written back. `status` is the verb
    # that rewrites the ledger; a report that rewrote it would change the
    # campaign it claims to be describing.
    ledger = reconcile(
        plan.ledger, read_outcomes(directory, plan.ledger), reconciled_at=stamp
    )
    summary = summarize(manifest, ledger)
    records = load_episode_records(directory, plan)
    plan_paths = {episode.run_id: episode.output_path for episode in plan.runnable}

    events: dict[str, _EpisodeEvents] = {}
    unavailable: list[str] = []
    for record in records:
        episode_events = _read_events(record, sink_root)
        if episode_events is None:
            unavailable.append(record.run_id)
            continue
        events[record.run_id] = episode_events

    by_arm: dict[str, list[EpisodeRecord]] = {}
    for record in records:
        by_arm.setdefault(record.arm_id, []).append(record)
    arm_order = [arm.arm_id for arm in manifest.payload.arms]

    payload = manifest.payload
    judges_ran = any(record.scores.get("judges_run") is True for record in records)
    return CampaignReport(
        campaign_id=campaign_id,
        generated_at=stamp,
        directory=str(directory),
        corpus_mode=payload.protocol.corpus_mode,
        stage=payload.protocol.stage,
        protocol_id=payload.protocol.protocol_id,
        protocol_digest=payload.protocol_digest,
        lock_digest=payload.lock_digest,
        repeats=payload.protocol.repeats,
        seed=payload.protocol.seed,
        denominators=ledger.report,
        records_read=len(records),
        trajectories_read=len(events),
        trajectory_events_read=sum(entry.count for entry in events.values()),
        trajectories_unavailable=tuple(sorted(unavailable)),
        workflow_usd=summary.costs.workflow_usd,
        judge_usd=summary.costs.judge_usd,
        harness_usd=summary.costs.harness_usd,
        total_usd=summary.costs.total_usd,
        model_calls=sum(record.model_calls for record in records),
        judge_model_calls=sum(record.judge_model_calls for record in records),
        quality=tuple(
            _arm_quality(arm_id, by_arm.get(arm_id, ())) for arm_id in arm_order
        ),
        variance=_variance_rows(records),
        variance_intervals=_variance_intervals(records, seed=payload.protocol.seed),
        baseline_difficulty=_difficulty_rows(records),
        small_sample_caveat=small_sample_caveat(
            len({record.case_id for record in records})
        ),
        cost=tuple(_arm_cost(arm_id, by_arm.get(arm_id, ())) for arm_id in arm_order),
        taxonomy=_taxonomy_rows(records, events, judges_ran=judges_ran),
        lineage=tuple(
            _arm_lineage(arm, by_arm.get(arm.arm_id, ()), directory, plan_paths)
            for arm in payload.arms
        ),
        episodes=tuple(
            EpisodeLineageRow(
                case_id=record.case_id,
                arm_id=record.arm_id,
                repeat_index=record.repeat_index,
                run_id=record.run_id,
                ledger_status=record.ledger_status.value,
                manifest_digest=record.manifest_digest,
                trajectory_events=(
                    events[record.run_id].count if record.run_id in events else 0
                ),
            )
            for record in sorted(
                records, key=lambda item: (item.case_id, item.arm_id, item.repeat_index)
            )
        ),
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def _rate_cell(row: MetricRow) -> str:
    if row.not_run_reason is not None:
        return f"not run — {row.not_run_reason}"
    if row.rate is None or row.interval_low is None or row.interval_high is None:
        return f"{row.numerator}/{row.denominator} n/a"
    return (
        f"{row.rate:.3f} [{row.interval_low:.3f}–{row.interval_high:.3f}] "
        f"({row.numerator}/{row.denominator})<br><small>{row.interval_label}</small>"
    )


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def render_report(report: CampaignReport) -> str:
    """Render the report as one markdown document.

    Args:
        report: The built report.

    Returns:
        The markdown.
    """
    lines: list[str] = [
        f"# Campaign report — `{report.campaign_id}`",
        "",
        f"Generated: {report.generated_at}  ",
        f"Directory: `{report.directory}`  ",
        f"Protocol: `{report.protocol_id}` (stage `{report.stage}`, "
        f"corpus mode `{report.corpus_mode}`, {report.repeats} repeats, "
        f"seed {report.seed})  ",
        f"Protocol digest: `{report.protocol_digest}`  ",
        f"Lock digest: `{report.lock_digest}`",
        "",
        "Every number below is read from a record in this campaign: the "
        "reconciled ledger, the episode records, the sealed run manifests, and "
        "the durable trajectories the records point at. Nothing is estimated.",
        "",
        "## Denominators",
        "",
        "| Figure | Value |",
        "|---|---:|",
        f"| Expected episodes | {report.denominators.expected} |",
        f"| Accounted | {report.denominators.accounted} |",
        f"| Analysis denominator | {report.denominators.analysis_denominator} |",
        f"| Episode records read | {report.records_read} |",
        f"| Durable trajectories read | {report.trajectories_read} |",
        f"| Trajectory events read | {report.trajectory_events_read} |",
    ]
    for status, count in sorted(report.denominators.counts.items()):
        lines.append(f"| Ledger: {status} | {count} |")
    lines.extend(
        [
            "",
            f"Paired items {report.summary.paired_items}; "
            f"required pairs at a five-point move {report.summary.required_pairs}. "
            f"{report.summary.power_statement}",
        ]
    )
    if report.summary.small_sample_caveat:
        lines.extend(["", report.summary.small_sample_caveat])
    if report.trajectories_unavailable:
        lines.extend(
            [
                "",
                f"**{len(report.trajectories_unavailable)} episode(s) had no readable "
                "durable trajectory**, so every trajectory-sourced count below is over "
                f"{report.trajectories_read} episodes rather than {report.records_read}: "
                + ", ".join(f"`{run_id}`" for run_id in report.trajectories_unavailable),
            ]
        )

    lines.extend(
        [
            "",
            "## Quality, per arm",
            "",
            "Each cell is the pooled rate over the arm's episodes, with a 95% Wilson "
            "interval from `src/eval/stats.py` and the two counts it came from. "
            "`mean` is the unweighted mean of the per-episode scores, which differs "
            "from the pooled rate whenever episodes had different denominators.",
        ]
    )
    for arm in report.quality:
        lines.extend(
            [
                "",
                f"### Arm {arm.arm_id}",
                "",
                f"Episodes {arm.episodes}; with a primary score {arm.scored_episodes}; "
                f"null metric {arm.null_metric_episodes}; "
                f"**judges_run** on {arm.judges_run_episodes} of {arm.episodes}."
                + (
                    " Skipped rubrics: "
                    + ", ".join(f"`{name}`" for name in arm.skipped_rubrics)
                    + "."
                    if arm.skipped_rubrics
                    else " No rubric was skipped."
                ),
                "",
                "| Metric | Instrument | Pooled rate [95% CI] (n/d) | Unit | mean | "
                "Episodes scored | Missing | Abstentions |",
                "|---|---|---|---|---:|---:|---:|---:|",
            ]
        )
        for row in arm.metrics:
            lines.append(
                f"| `{row.metric_id}` | {row.instrument} | {_rate_cell(row)} "
                f"| {row.unit} | {_score(row.mean_episode_score)} "
                f"| {row.episodes_scored} | {row.episodes_missing} "
                f"| {row.abstentions} |"
            )

    lines.extend(
        [
            "",
            "## Variance and baseline difficulty",
            "",
            "Repeat variation is reported per query, arm and metric. Judge scores "
            "that are `None` are not scored and never enter a zero-valued bucket.",
            "",
            "| Query | Arm | Metric | Episodes scored | Mean | SD | Min | Max |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for variance_row in report.variance:
        lines.append(
            f"| `{variance_row.query_id}` | {variance_row.arm_id} "
            f"| `{variance_row.metric_id}` | {variance_row.episodes_scored} "
            f"| {_score(variance_row.mean)} | {_score(variance_row.sd)} "
            f"| {_score(variance_row.minimum)} | {_score(variance_row.maximum)} |"
        )
    lines.extend(
        [
            "",
            "| Arm | Metric | Queries | Episodes scored | Mean | 95% interval | "
            "Method | Seed |",
            "|---|---|---:|---:|---:|---|---|---:|",
        ]
    )
    for interval_row in report.variance_intervals:
        interval = (
            f"[{interval_row.interval_low:.3f}–{interval_row.interval_high:.3f}]"
            if interval_row.interval_low is not None and interval_row.interval_high is not None
            else "n/a"
        )
        lines.append(
            f"| {interval_row.arm_id} | `{interval_row.metric_id}` "
            f"| {interval_row.query_count} | {interval_row.episodes_scored} "
            f"| {_score(interval_row.point)} | {interval} "
            f"| {interval_row.method} ({interval_row.resamples} resamples) "
            f"| {interval_row.seed} |"
        )
    lines.extend(
        [
            "",
            "The pooled Wilson row above is labelled **pooled, assumes "
            "independence — not for gating**. The interval in this section "
            "resamples queries first and repeats within each drawn query.",
            "",
            "### Per-query baseline difficulty",
            "",
            "| Query | Arm | Metric means |",
            "|---|---|---|",
        ]
    )
    for difficulty_row in report.baseline_difficulty:
        metrics = ", ".join(
            f"`{metric}`={value:.3f}" if value is not None else f"`{metric}`=n/a"
            for metric, value in difficulty_row.metrics.items()
        )
        lines.append(
            f"| `{difficulty_row.query_id}` | {difficulty_row.arm_id} | {metrics or 'n/a'} |"
        )
    if report.small_sample_caveat:
        lines.extend(["", report.small_sample_caveat])

    lines.extend(
        [
            "",
            "## Cost and latency, per arm",
            "",
            "| Arm | Episodes | Workflow $ | Judge $ | Total $ | Model calls | "
            "Judge model calls | Latency total s | mean | p50 | p95 | max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for cost in report.cost:
        lines.append(
            f"| {cost.arm_id} | {cost.episodes} | {cost.workflow_usd} "
            f"| {cost.judge_usd} | {cost.total_usd} | {cost.model_calls} "
            f"| {cost.judge_model_calls} | {cost.latency_total_seconds:.3f} "
            f"| {_seconds(cost.latency_mean_seconds)} "
            f"| {_seconds(cost.latency_p50_seconds)} "
            f"| {_seconds(cost.latency_p95_seconds)} "
            f"| {_seconds(cost.latency_max_seconds)} |"
        )
    lines.extend(
        [
            "",
            f"Campaign total: workflow `${report.workflow_usd}`, judge "
            f"`${report.judge_usd}`, harness `${report.harness_usd}`, total "
            f"`${report.total_usd}`; {report.model_calls} workflow model calls and "
            f"{report.judge_model_calls} judge model calls over "
            f"{report.records_read} episodes.",
            "",
            "Harness spend is a campaign-level category (ADR 0050) and is not "
            "attributed to an arm.",
            "",
            "## Error taxonomy",
            "",
            "03 §8's classes as `15-stage0-qualification-report.md` §7.1 maps them "
            "onto the codes that exist on `main`. A class this campaign's records "
            "carry no signal for prints `not detected from records` rather than `0`: "
            "an unmeasured class is not an absent one.",
            "",
            "| Class | Detected from | Episodes | Occurrences | Codes observed |",
            "|---|---|---:|---:|---|",
        ]
    )
    for failure in report.taxonomy:
        if not failure.counted:
            detail = "not detected from records"
            episodes = occurrences = "—"
        else:
            detail = "; ".join(failure.signals) or "—"
            episodes = str(failure.episodes)
            occurrences = str(failure.occurrences)
        codes = (
            ", ".join(f"`{code}` × {count}" for code, count in failure.codes.items())
            or "—"
        )
        lines.append(
            f"| {failure.label} | {detail} | {episodes} | {occurrences} | {codes} |"
        )
    notes = [failure for failure in report.taxonomy if failure.note]
    if notes:
        lines.extend(["", "Notes:", ""])
        lines.extend(f"- **{failure.label}** — {failure.note}" for failure in notes)

    lines.extend(
        [
            "",
            "## Lineage",
            "",
            "| Arm | Selector | Status | Runnable | Episodes | Arm digest | "
            "Graph digest | Graph capabilities | Policy version | Read from |",
            "|---|---|---|---|---:|---|---|---|---|---|",
        ]
    )
    for identity in report.lineage:
        graph = f"`{identity.graph_digest}`" if identity.graph_digest else "—"
        capabilities = (
            ", ".join(f"`{name}`" for name in identity.graph_capabilities) or "—"
        )
        lines.append(
            f"| {identity.arm_id} | `{identity.selector}` | {identity.status} "
            f"| {identity.runnable} | {identity.episodes} | `{identity.arm_digest}` "
            f"| {graph} | {capabilities} | {identity.policy_version or '—'} "
            f"| {identity.graph_digest_read_from or '—'} |"
        )
    lines.extend(
        [
            "",
            "The arm digest is sha256 over the sealed `ArmDeclaration` this campaign "
            "froze, and is itself covered by the protocol digest above. The graph "
            "digest is read from the sealed run manifest of the episode named in the "
            "last column; two arms may share one, because arms that differ only by "
            "settings compile the same graph (15 §3.1).",
            "",
            "## Episode lineage",
            "",
            f"<details><summary>{len(report.episodes)} episodes</summary>",
            "",
            "| Case | Arm | Repeat | Run id | Ledger status | Manifest digest | Events |",
            "|---|---|---:|---|---|---|---:|",
        ]
    )
    for episode in report.episodes:
        lines.append(
            f"| {episode.case_id} | {episode.arm_id} | {episode.repeat_index} "
            f"| `{episode.run_id}` | {episode.ledger_status} "
            f"| `{episode.manifest_digest}` | {episode.trajectory_events} |"
        )
    lines.extend(["", "</details>", ""])
    return "\n".join(lines) + "\n"


__all__ = [
    "DEGRADATION_EVENT",
    "JUDGE_METRICS",
    "METRIC_IDS",
    "REPORT_SCHEMA_VERSION",
    "TAXONOMY",
    "ArmCost",
    "ArmLineage",
    "ArmQuality",
    "CampaignReport",
    "EpisodeLineageRow",
    "MetricRow",
    "TaxonomyClass",
    "TaxonomyRow",
    "build_report",
    "render_report",
]
