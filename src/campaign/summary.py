"""Campaign-level cost categories, denominators, and the statistics caveat.

Two jobs, and both are deliberately thin.

**Cost, in the categories ADR 0050 and ADR 0071 already split.** Workflow
spend is the policy under test; judge spend is the harness scoring it; and
a third category exists for paid tools and infrastructure, which nothing in
this repository spends today and which is therefore reported as zero rather
than folded into one of the other two. A single "total cost" number was the
defect ADR 0050 was written about — summaries older than it are not
comparable on cost because judge spend was hidden inside the product's.

**Statistics are delegated, never reimplemented.** `src/eval/stats.py`
owns McNemar, the required-pairs calculation, the paired bootstrap and the
small-sample caveat, and this module calls it. A second implementation of
a confidence interval is a second set of assumptions nobody will keep in
sync, and the interesting number here — how many paired items this design
would need — is exactly the one `stats` already computes.

The aggregation guard belongs here too: `assert_aggregatable` refuses to
combine a snapshot campaign with a live one. RFC 09 §7 and 07 §6 Stage 4
both say a live-retrieval sweep is separately reported, and the only way
to make that stick is to fail when someone tries.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Annotated, Final

from pydantic import Field

from src.campaign.errors import CampaignError
from src.campaign.ledger import DenominatorLedger, DenominatorReport, LedgerStatus
from src.campaign.manifest import CampaignManifestV1, CorpusModeChoice
from src.contracts.kernel import Digest, MoneyUsd, StrictContractModel
from src.contracts.run_manifest import CampaignId

#: The effect size and discordance the required-pairs figure is quoted at.
#: 07 §7 names a five-point move as the smallest difference worth acting
#: on, and `mcnemar_required_pairs` documents why the pair is the honest
#: default: at `delta == discordance` the power term vanishes and the
#: answer is the smallest sample at which such a move is significant at
#: all — a floor, quoted as a floor.
DEFAULT_DELTA: Final[float] = 0.05
DEFAULT_DISCORDANCE: Final[float] = 0.05


class CostCategories(StrictContractModel):
    """Campaign spend, split the way approval and analysis both need it.

    Attributes:
        workflow_usd: The policy under test.
        judge_usd: The harness scoring it. Separate because a judge
            failure is not a policy failure and a judge's cost is not the
            product's cost.
        harness_usd: Paid tools, data sources and infrastructure. Zero in
            this repository, and reported rather than omitted so a later
            campaign that does spend here cannot hide it inside the other
            two.
        total_usd: The sum, which is the number a cap is compared against.
    """

    workflow_usd: MoneyUsd
    judge_usd: MoneyUsd
    harness_usd: MoneyUsd
    total_usd: MoneyUsd


class ArmSummary(StrictContractModel):
    """One arm's accounting, over the whole denominator rather than the wins."""

    arm_id: str
    expected: Annotated[int, Field(ge=0)]
    completed: Annotated[int, Field(ge=0)]
    errored: Annotated[int, Field(ge=0)]
    cancelled: Annotated[int, Field(ge=0)]
    timed_out: Annotated[int, Field(ge=0)]
    budget_stopped: Annotated[int, Field(ge=0)]
    null_metric: Annotated[int, Field(ge=0)]
    excluded: Annotated[int, Field(ge=0)]
    not_started: Annotated[int, Field(ge=0)]
    workflow_usd: MoneyUsd
    judge_usd: MoneyUsd


class CampaignSummary(StrictContractModel):
    """What a campaign can honestly say about itself once it has stopped."""

    campaign_id: CampaignId
    corpus_mode: CorpusModeChoice
    protocol_digest: Digest
    lock_digest: Digest
    denominators: DenominatorReport
    costs: CostCategories
    arms: tuple[ArmSummary, ...]
    repeats: Annotated[int, Field(ge=1)]
    paired_items: Annotated[int, Field(ge=0)]
    required_pairs: Annotated[int, Field(ge=1)]
    small_sample_caveat: str | None
    power_statement: str


def aggregate_costs(
    ledger: DenominatorLedger, *, harness_usd: MoneyUsd = "0.000000"
) -> CostCategories:
    """Sum the reconciled ledger's per-episode spend into the three categories.

    Args:
        ledger: A reconciled ledger.
        harness_usd: Paid tool, data or infrastructure spend the caller
            observed. Defaults to zero because nothing in this repository
            spends there; it is a parameter rather than a constant so a
            campaign that does can report it without a schema change.

    Returns:
        The three categories and their total.
    """
    workflow = sum(
        (Decimal(entry.workflow_cost_usd) for entry in ledger.entries), Decimal("0")
    )
    judge = sum((Decimal(entry.judge_cost_usd) for entry in ledger.entries), Decimal("0"))
    harness = Decimal(harness_usd)
    return CostCategories(
        workflow_usd=f"{workflow:.6f}",
        judge_usd=f"{judge:.6f}",
        harness_usd=f"{harness:.6f}",
        total_usd=f"{workflow + judge + harness:.6f}",
    )


def summarize(
    manifest: CampaignManifestV1,
    ledger: DenominatorLedger,
    *,
    harness_usd: MoneyUsd = "0.000000",
) -> CampaignSummary:
    """Build the campaign summary, denominators and caveat included.

    The paired-item count is the campaign's *comparable* denominator: one
    item per (case, repeat) block, which is what a paired contrast between
    two arms is actually run over. Quoting the episode count instead would
    inflate it by the number of arms.

    Args:
        manifest: The sealed campaign manifest.
        ledger: The reconciled ledger.
        harness_usd: Observed paid tool/infrastructure spend.

    Returns:
        The summary.

    Raises:
        CampaignError: The ledger belongs to a different campaign.
    """
    from src.eval.stats import mcnemar_required_pairs, power_statement, small_sample_caveat

    payload = manifest.payload
    if ledger.campaign_id != payload.campaign_id:
        raise CampaignError("ledger and manifest describe different campaigns")
    paired_items = len(payload.protocol.case_ids) * payload.protocol.repeats
    return CampaignSummary(
        campaign_id=payload.campaign_id,
        corpus_mode=payload.protocol.corpus_mode,
        protocol_digest=payload.protocol_digest,
        lock_digest=payload.lock_digest,
        denominators=ledger.report,
        costs=aggregate_costs(ledger, harness_usd=harness_usd),
        arms=_arm_summaries(manifest, ledger),
        repeats=payload.protocol.repeats,
        paired_items=paired_items,
        required_pairs=mcnemar_required_pairs(
            delta=DEFAULT_DELTA, discordance=DEFAULT_DISCORDANCE
        ),
        small_sample_caveat=small_sample_caveat(paired_items),
        power_statement=power_statement(paired_items, delta=DEFAULT_DELTA),
    )


def assert_aggregatable(summaries: Sequence[CampaignSummary]) -> None:
    """Refuse to combine campaigns that are not the same experiment.

    Two rules, both from RFC 09 §7 and 07 §6 Stage 4: a snapshot campaign
    and a live-retrieval campaign never share an aggregate, and two
    campaigns over different registry locks are not measuring the same
    task set. Either one silently combined produces a number that looks
    like more evidence and is less.

    Raises:
        CampaignError: The summaries disagree on corpus mode or lock.
    """
    if len(summaries) < 2:
        return
    modes = {summary.corpus_mode for summary in summaries}
    if len(modes) > 1:
        raise CampaignError(
            "a controlled-source campaign and a live-retrieval campaign cannot "
            f"aggregate into one summary (found {sorted(modes)}); report the "
            "live sweep separately"
        )
    locks = {summary.lock_digest for summary in summaries}
    if len(locks) > 1:
        raise CampaignError(
            "campaigns locked to different registry revisions cannot aggregate "
            "into one summary"
        )


def _arm_summaries(
    manifest: CampaignManifestV1, ledger: DenominatorLedger
) -> tuple[ArmSummary, ...]:
    blocks = len(manifest.payload.protocol.case_ids) * manifest.payload.protocol.repeats
    summaries: list[ArmSummary] = []
    for arm in manifest.payload.arms:
        entries = [entry for entry in ledger.entries if entry.arm_id == arm.arm_id]
        counts = {status: 0 for status in LedgerStatus}
        workflow = Decimal("0")
        judge = Decimal("0")
        for entry in entries:
            counts[entry.status] += 1
            workflow += Decimal(entry.workflow_cost_usd)
            judge += Decimal(entry.judge_cost_usd)
        summaries.append(
            ArmSummary(
                arm_id=arm.arm_id,
                expected=blocks,
                completed=counts[LedgerStatus.COMPLETED],
                errored=counts[LedgerStatus.ERRORED],
                cancelled=counts[LedgerStatus.CANCELLED],
                timed_out=counts[LedgerStatus.TIMED_OUT],
                budget_stopped=counts[LedgerStatus.BUDGET_STOPPED],
                null_metric=counts[LedgerStatus.NULL_METRIC],
                excluded=counts[LedgerStatus.EXCLUDED],
                not_started=counts[LedgerStatus.NOT_STARTED],
                workflow_usd=f"{workflow:.6f}",
                judge_usd=f"{judge:.6f}",
            )
        )
    return tuple(summaries)


__all__ = [
    "DEFAULT_DELTA",
    "DEFAULT_DISCORDANCE",
    "ArmSummary",
    "CampaignSummary",
    "CostCategories",
    "aggregate_costs",
    "assert_aggregatable",
    "summarize",
]
