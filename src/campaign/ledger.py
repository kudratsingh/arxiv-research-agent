"""The expected-denominator ledger: every planned episode, accounted for.

Work-order invariant 11 is the whole reason this file exists: *failed,
cancelled, timed-out, budget-stopped and partially scored episodes remain
in artifacts and denominators.* The failure mode it forbids is not
malice, it is arithmetic — a report that divides by "the episodes that
produced a number" and calls the result a rate.

So the ledger is written **before any episode runs**, with one entry per
slot of the declared design matrix, and reconciliation may only move an
entry from `not_started` to one of the terminal categories. It can never
add an entry, drop one, or leave the accounted total below the expected
one; `DenominatorReport` refuses to be built if it does.

Two denominators are reported, and the difference between them is the
only place an episode may legitimately leave the analysis:

- `expected` counts every declared slot, including the arms this
  checkout cannot run;
- `analysis` subtracts only *declared exclusions*, each of which carries
  a typed reason recorded before the campaign started.

Everything else — errors, timeouts, cancellations, budget stops and null
metrics — stays in both.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from src.campaign.errors import CampaignError
from src.campaign.matrix import ExclusionReason, PlannedEpisode
from src.contracts.kernel import (
    Digest,
    MoneyUsd,
    Rfc3339Utc,
    StrictContractModel,
)
from src.contracts.run_manifest import (
    CampaignId,
    CompletionReceipt,
    CompletionStatus,
    RunId,
    RunReason,
)


class LedgerStatus(StrEnum):
    """Every state a declared episode can be accounted in.

    `NOT_STARTED` is a real outcome, not a gap: a campaign stopped by its
    budget leaves episodes in it, and a report that silently shrank its
    denominator to the attempted ones would overstate coverage.
    """

    NOT_STARTED = "not_started"
    COMPLETED = "completed"
    ERRORED = "errored"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    BUDGET_STOPPED = "budget_stopped"
    NULL_METRIC = "null_metric"
    EXCLUDED = "excluded"


#: Statuses that mean an episode was attempted and reached a terminal
#: receipt. `NULL_METRIC` is here deliberately: the *episode* completed,
#: and only its primary metric is missing.
TERMINAL_STATUSES: frozenset[LedgerStatus] = frozenset(
    {
        LedgerStatus.COMPLETED,
        LedgerStatus.ERRORED,
        LedgerStatus.CANCELLED,
        LedgerStatus.TIMED_OUT,
        LedgerStatus.BUDGET_STOPPED,
        LedgerStatus.NULL_METRIC,
    }
)


class EpisodeScoreReceipt(StrictContractModel):
    """The one fact a scorer owes the denominator.

    Deliberately minimal. Rubrics, judges and score schemas belong to
    W10/W11; the denominator needs exactly one bit — did this episode
    produce its primary outcome measure — and asking for more here would
    couple the ledger to a scoring design that has not been decided.

    A completed episode with `primary_metric_available=false` is a null
    metric: it stays in the denominator and is not a success.
    """

    schema_kind: Literal["episode-score-receipt"] = "episode-score-receipt"
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: RunId
    primary_metric_available: bool
    null_reason: Annotated[str, Field(max_length=200)] | None = None

    @model_validator(mode="after")
    def null_is_explained(self) -> EpisodeScoreReceipt:
        if not self.primary_metric_available and not self.null_reason:
            raise ValueError("a missing primary metric must say why")
        return self


class EpisodeOutcome(StrictContractModel):
    """What one episode actually did, as the reconciler consumes it."""

    episode_key: Digest
    run_id: RunId
    status: CompletionStatus
    reason: RunReason | None = None
    workflow_cost_usd: MoneyUsd = "0.000000"
    judge_cost_usd: MoneyUsd = "0.000000"
    primary_metric_available: bool = True

    @property
    def ledger_status(self) -> LedgerStatus:
        """Map a terminal receipt onto its denominator category.

        The one non-obvious mapping is `TIMEOUT`: the completion vocabulary
        calls it a failure with a reason, and the denominator wants it
        separated, because "the policy produced a wrong answer" and "the
        harness ran out of wall clock" are different findings and
        collapsing them hides an infrastructure problem inside a quality
        number (07 §9's "repeated infrastructure failures" stop
        condition).
        """
        if self.status is CompletionStatus.CANCELLED:
            return LedgerStatus.CANCELLED
        if self.status is CompletionStatus.BUDGET_STOPPED:
            return LedgerStatus.BUDGET_STOPPED
        if self.status is CompletionStatus.FAILED:
            if self.reason is RunReason.TIMEOUT:
                return LedgerStatus.TIMED_OUT
            return LedgerStatus.ERRORED
        if not self.primary_metric_available:
            return LedgerStatus.NULL_METRIC
        return LedgerStatus.COMPLETED


class LedgerEntry(StrictContractModel):
    """One declared slot and its current accounting."""

    episode_key: Digest
    run_id: RunId
    case_id: str
    arm_id: str
    repeat_index: Annotated[int, Field(ge=0)]
    output_path: str
    status: LedgerStatus
    reason: RunReason | None = None
    exclusion_reason: ExclusionReason | None = None
    workflow_cost_usd: MoneyUsd = "0.000000"
    judge_cost_usd: MoneyUsd = "0.000000"

    @model_validator(mode="after")
    def exclusions_carry_a_reason(self) -> LedgerEntry:
        if self.status is LedgerStatus.EXCLUDED and self.exclusion_reason is None:
            raise ValueError("an excluded episode must name its reason")
        if self.status is not LedgerStatus.EXCLUDED and self.exclusion_reason is not None:
            raise ValueError("only an excluded episode carries an exclusion reason")
        return self


class DenominatorReport(StrictContractModel):
    """Counts by status, with the two denominators the analysis may use."""

    expected: Annotated[int, Field(ge=1)]
    accounted: Annotated[int, Field(ge=0)]
    analysis_denominator: Annotated[int, Field(ge=0)]
    counts: Mapping[str, int]

    @model_validator(mode="after")
    def nothing_is_lost(self) -> DenominatorReport:
        if sum(self.counts.values()) != self.accounted:
            raise ValueError("status counts do not sum to the accounted total")
        if self.accounted != self.expected:
            raise ValueError(
                "every declared episode must be accounted: "
                f"{self.accounted} of {self.expected}"
            )
        excluded = self.counts.get(LedgerStatus.EXCLUDED.value, 0)
        if self.analysis_denominator != self.expected - excluded:
            raise ValueError("the analysis denominator drops more than the exclusions")
        return self


class DenominatorLedger(StrictContractModel):
    """The campaign's full accounting, written before its first episode."""

    schema_kind: Literal["campaign-denominator-ledger"] = "campaign-denominator-ledger"
    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: CampaignId
    written_at: Rfc3339Utc
    entries: tuple[LedgerEntry, ...]
    report: DenominatorReport

    @model_validator(mode="after")
    def entries_match_the_report(self) -> DenominatorLedger:
        if len(self.entries) != self.report.expected:
            raise ValueError("ledger entries do not match the expected denominator")
        keys = [entry.episode_key for entry in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError("ledger contains duplicate episode keys")
        return self


def open_ledger(
    *, campaign_id: CampaignId, episodes: Sequence[PlannedEpisode], written_at: Rfc3339Utc
) -> DenominatorLedger:
    """Build the ledger that is written before any episode runs.

    Args:
        campaign_id: The campaign.
        episodes: Every declared slot from the matrix compiler.
        written_at: Seal time.

    Returns:
        A ledger in which every runnable slot is `not_started` and every
        excluded slot already carries its typed reason.

    Raises:
        CampaignError: The matrix is empty.
    """
    if not episodes:
        raise CampaignError("a campaign with no episodes has no denominator")
    entries = tuple(
        LedgerEntry(
            episode_key=episode.episode_key,
            run_id=episode.run_id,
            case_id=episode.case_id,
            arm_id=episode.arm_id,
            repeat_index=episode.repeat_index,
            output_path=episode.output_path,
            status=(
                LedgerStatus.NOT_STARTED if episode.runnable else LedgerStatus.EXCLUDED
            ),
            exclusion_reason=episode.exclusion_reason,
        )
        for episode in episodes
    )
    return DenominatorLedger(
        campaign_id=campaign_id,
        written_at=written_at,
        entries=entries,
        report=_report(entries),
    )


def reconcile(
    ledger: DenominatorLedger,
    outcomes: Iterable[EpisodeOutcome],
    *,
    reconciled_at: Rfc3339Utc,
) -> DenominatorLedger:
    """Fold observed outcomes into the ledger without changing its shape.

    Args:
        ledger: The ledger written before the campaign ran.
        outcomes: One outcome per attempted episode.
        reconciled_at: Reconciliation time.

    Returns:
        A new ledger with the same entries in the same order, each
        carrying its terminal status and accumulated spend.

    Raises:
        CampaignError: An outcome names an episode the campaign never
            planned, or names an excluded one. Both are corruption: the
            first means the denominator is missing a slot, the second
            means something ran an episode the design excluded.
    """
    by_key = {outcome.episode_key: outcome for outcome in outcomes}
    known = {entry.episode_key for entry in ledger.entries}
    unknown = sorted(set(by_key) - known)
    if unknown:
        raise CampaignError(
            f"outcomes reference {len(unknown)} episode(s) outside the campaign plan"
        )
    updated: list[LedgerEntry] = []
    for entry in ledger.entries:
        outcome = by_key.get(entry.episode_key)
        if outcome is None:
            updated.append(entry)
            continue
        if entry.status is LedgerStatus.EXCLUDED:
            raise CampaignError(
                f"an excluded episode produced an outcome: {entry.case_id}/{entry.arm_id}"
            )
        if outcome.run_id != entry.run_id:
            raise CampaignError(
                f"outcome run id does not match the planned run for {entry.episode_key}"
            )
        updated.append(
            entry.model_copy(
                update={
                    "status": outcome.ledger_status,
                    "reason": outcome.reason,
                    "workflow_cost_usd": outcome.workflow_cost_usd,
                    "judge_cost_usd": outcome.judge_cost_usd,
                }
            )
        )
    frozen = tuple(updated)
    return DenominatorLedger(
        campaign_id=ledger.campaign_id,
        written_at=reconciled_at,
        entries=frozen,
        report=_report(frozen),
    )


def read_outcomes(root: Path, ledger: DenominatorLedger) -> tuple[EpisodeOutcome, ...]:
    """Read every terminal receipt the campaign directory holds.

    An episode directory with no `completion.json` has not finished, and
    that is left as `not_started` rather than guessed at — RFC 09 §11.1
    is explicit that a process crash with no terminal receipt is
    "interrupted/unknown, not success and not automatically safe to
    resume".

    Args:
        root: The campaign root directory.
        ledger: The ledger naming the episodes to look for.

    Returns:
        One outcome per episode that wrote a terminal receipt.

    Raises:
        CampaignError: A receipt exists but is unreadable or invalid. A
            corrupt receipt is not a missing one; guessing would put a
            wrong number in a denominator.
    """
    outcomes: list[EpisodeOutcome] = []
    for entry in ledger.entries:
        directory = root / entry.output_path
        receipt_path = directory / "completion.json"
        if not receipt_path.is_file():
            continue
        try:
            receipt = CompletionReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            raise CampaignError(
                f"completion receipt for {entry.output_path} is invalid: {exc}"
            ) from exc
        outcomes.append(
            EpisodeOutcome(
                episode_key=entry.episode_key,
                run_id=receipt.run_id,
                status=receipt.status,
                reason=receipt.reason,
                workflow_cost_usd=receipt.accumulated_workflow_cost_usd,
                judge_cost_usd=receipt.accumulated_judge_cost_usd,
                primary_metric_available=_primary_metric_available(directory),
            )
        )
    return tuple(outcomes)


def _primary_metric_available(directory: Path) -> bool:
    """Read the scorer's one bit, defaulting to available when unscored.

    Absent `scores.json` means the episode was not scored at all, which
    is not the same as a null metric — an unscored episode is `completed`
    and the campaign's score coverage is a separate number. Only an
    explicit `primary_metric_available: false` makes a null metric.
    """
    path = directory / "scores.json"
    if not path.is_file():
        return True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EpisodeScoreReceipt.model_validate(payload).primary_metric_available
    except (OSError, ValueError) as exc:
        raise CampaignError(f"score receipt in {directory.name} is invalid: {exc}") from exc


def _report(entries: Sequence[LedgerEntry]) -> DenominatorReport:
    counts = {status.value: 0 for status in LedgerStatus}
    for entry in entries:
        counts[entry.status.value] += 1
    excluded = counts[LedgerStatus.EXCLUDED.value]
    return DenominatorReport(
        expected=len(entries),
        accounted=len(entries),
        analysis_denominator=len(entries) - excluded,
        counts=counts,
    )


__all__ = [
    "TERMINAL_STATUSES",
    "DenominatorLedger",
    "DenominatorReport",
    "EpisodeOutcome",
    "EpisodeScoreReceipt",
    "LedgerEntry",
    "LedgerStatus",
    "open_ledger",
    "read_outcomes",
    "reconcile",
]
