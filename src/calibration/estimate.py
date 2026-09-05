"""Cost and time estimate template for a judge-calibration campaign.

12 §16 asks for "a cost/time estimate template with stop conditions" and
12 §18 lists what a funded request must present: exact model ids and
*verified* prices, the exact slice and repeat count, per-episode and
campaign caps with in-flight overshoot behaviour, the owner/expert
labeling budget, and stopping rules. This module is that template, plus
one filled example.

**The example is an example.** :attr:`CostEstimate.requires_repricing`
is fixed ``True`` and :attr:`CostEstimate.approved` does not exist: there
is no field in this schema a caller can set to make an estimate into an
approval, because 12 §2 D9 blocks every live baseline, model judge and
paid label, and an object that could represent an approval is an object
somebody will eventually point at instead of the ledger.

**The price table is read, not copied.** :func:`current_price_table`
imports ``src/observability/costs.py`` inside the function rather than at
module scope, so the schema stays importable without pulling the
settings and metrics stack into a pure package, and so the estimate is
priced from the table the product actually bills against.
:func:`price_staleness` compares ``PRICES_LAST_VERIFIED`` against a date
the caller supplies — never against a clock — and says in words when the
table is old enough that the estimate must be re-derived.

**Expert time is the binding constraint, and the template makes that
visible.** At the item counts :mod:`src.calibration.sampling` derives,
the model spend of a calibration run is small change and the expert hours
are not. An estimate that reported only dollars would answer the easy
question.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import StrictContractModel

#: How long a verified price may stand before an estimate built on it
#: has to be re-derived. Thirty days is not a market fact — provider
#: prices move on no schedule — it is the interval at which "I checked
#: recently" stops being a defensible claim in an approval packet.
PRICE_FRESHNESS_DAYS: Final[int] = 30

#: USD per million tokens, so an estimate divides once and says so.
TOKENS_PER_MILLION: Final[int] = 1_000_000


def current_price_table() -> tuple[dict[str, dict[str, float]], str]:
    """Read the product's live price table and its verification date.

    Imported inside the function on purpose: ``src/observability/costs.py``
    pulls in settings, logging and the metrics registry, and a schema
    module that a test can import in isolation is worth more than one
    import statement saved.

    Returns:
        The table, and the ``PRICES_LAST_VERIFIED`` date string beside it.
    """
    from src.observability.costs import (  # noqa: PLC0415
        PRICES_LAST_VERIFIED,
        PRICES_USD_PER_MILLION,
    )

    return {model: dict(prices) for model, prices in PRICES_USD_PER_MILLION.items()}, (
        PRICES_LAST_VERIFIED
    )


def price_staleness(verified_on: str, *, today: date) -> str | None:
    """The sentence an estimate owes its reader when its prices are old.

    ``None`` when the table is fresh — a staleness note printed on every
    estimate is a staleness note nobody reads.

    Args:
        verified_on: ``YYYY-MM-DD``, from ``PRICES_LAST_VERIFIED``.
        today: The date to measure against, supplied by the caller. This
            module reads no clock: a pure estimate that changes when it
            is run is not reproducible, and an approval packet is a
            document with a date on it.

    Returns:
        A sentence, or ``None``.

    Raises:
        ValueError: `verified_on` is not an ISO date.
    """
    checked = date.fromisoformat(verified_on)
    age = (today - checked).days
    if age <= PRICE_FRESHNESS_DAYS:
        return None
    return (
        f"**The prices behind this estimate were last verified {verified_on}, "
        f"{age} days before {today.isoformat()}.** 12 §18 requires exact "
        "then-current provider and model ids with verified prices in the approval "
        "packet, so this estimate must be re-derived against a fresh table before it "
        "is presented. Do not scale the totals below by a remembered price change."
    )


class JudgeCallLine(StrictContractModel):
    """One priced line of model spend.

    Attributes:
        label: What the line is for.
        model_id: The public model id, priced from the product's table.
        calls: How many calls.
        input_tokens_per_call: Prompt tokens, including the item and the
            rubric.
        output_tokens_per_call: Completion tokens.
        note: Where the token counts came from. An estimate whose token
            counts have no stated basis is a guess with a decimal point.
    """

    label: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    model_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    calls: Annotated[int, Field(ge=0)]
    input_tokens_per_call: Annotated[int, Field(ge=0)]
    output_tokens_per_call: Annotated[int, Field(ge=0)]
    note: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    def cost_usd(self, prices: Mapping[str, Mapping[str, float]]) -> Decimal:
        """Cost of this line, in USD, at the given price table.

        Raises:
            KeyError: The model is not in the table. Deliberately not a
                fallback: ``costs.py`` falls back to Sonnet at runtime so
                a live call is never unpriced, but an *estimate* built on
                a fallback would under-report by up to 3.3x with nothing
                in the number to say so.
        """
        row = prices[self.model_id]
        million = Decimal(TOKENS_PER_MILLION)
        total_input = Decimal(self.calls * self.input_tokens_per_call)
        total_output = Decimal(self.calls * self.output_tokens_per_call)
        cost = (
            total_input * Decimal(str(row["input"])) + total_output * Decimal(str(row["output"]))
        ) / million
        return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


class ExpertTimeLine(StrictContractModel):
    """One line of human time.

    Attributes:
        label: What the time is for.
        role: ``annotator``, ``adjudicator`` or ``reviewer``.
        items: How many items.
        minutes_per_item: Measured or estimated minutes each.
        annotators_per_item: How many people see each item. Two is the
            minimum that can produce a disagreement, and a set with no
            disagreements has no adjudication lineage to inspect.
        note: Where the per-item minutes came from.
    """

    label: Annotated[str, StringConstraints(min_length=1, max_length=120)]
    role: Literal["annotator", "adjudicator", "reviewer"]
    items: Annotated[int, Field(ge=0)]
    minutes_per_item: Annotated[float, Field(gt=0.0)]
    annotators_per_item: Annotated[int, Field(ge=1)]
    note: Annotated[str, StringConstraints(min_length=1, max_length=500)]

    @property
    def minutes(self) -> float:
        """Total human minutes on this line."""
        return self.items * self.minutes_per_item * self.annotators_per_item

    @property
    def hours(self) -> float:
        """Total human hours on this line."""
        return self.minutes / 60.0


class StopCondition(StrictContractModel):
    """One rule that halts the campaign, and what happens when it fires.

    07 §9 is explicit that stopping is an experiment outcome: completed
    work is preserved and the reason is published, and an arm is not
    silently restarted until it produces a better sample. So every
    condition carries its ``on_trigger`` action rather than leaving it to
    whoever is watching.

    Attributes:
        condition_id: Stable id.
        trigger: What is observed.
        on_trigger: What happens. Never "investigate".
    """

    condition_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    trigger: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    on_trigger: Annotated[str, StringConstraints(min_length=1, max_length=400)]


class CostEstimate(StrictContractModel):
    """A priced, timed campaign plan that is explicitly not an approval.

    Attributes:
        estimate_id: Stable id.
        revision: Semantic revision.
        prepared_for: What is being estimated.
        priced_on: The date the prices were read, ``YYYY-MM-DD``.
        prices_last_verified: ``PRICES_LAST_VERIFIED`` at that moment.
        judge_lines: Model spend.
        expert_lines: Human time.
        per_episode_cap_usd: The per-episode ceiling the campaign runs
            under.
        campaign_cap_usd: The campaign ceiling.
        overshoot_behaviour: What happens to in-flight work when a cap is
            reached. 12 §18 asks for this by name because a ceiling with
            no in-flight rule is a ceiling that is crossed once per
            concurrency unit.
        stop_conditions: Every rule that halts the run.
        requires_repricing: Fixed ``True``.
        campaign_started: Fixed ``False``.
        note: What this estimate is and is not.
    """

    estimate_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    revision: Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
    prepared_for: Annotated[str, StringConstraints(min_length=1, max_length=300)]
    priced_on: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    prices_last_verified: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    judge_lines: tuple[JudgeCallLine, ...] = ()
    expert_lines: tuple[ExpertTimeLine, ...] = ()
    per_episode_cap_usd: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{6}$")]
    campaign_cap_usd: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{6}$")]
    overshoot_behaviour: Annotated[str, StringConstraints(min_length=1, max_length=600)]
    stop_conditions: tuple[StopCondition, ...]
    requires_repricing: Literal[True] = True
    campaign_started: Literal[False] = False
    note: Annotated[str, StringConstraints(min_length=1, max_length=1500)]

    @model_validator(mode="after")
    def caps_and_conditions_are_present(self) -> CostEstimate:
        if not self.stop_conditions:
            raise ValueError(
                "an estimate without stop conditions is a budget, not a plan (07 §9)"
            )
        ids = [condition.condition_id for condition in self.stop_conditions]
        if len(set(ids)) != len(ids):
            raise ValueError("stop condition ids must be unique")
        if Decimal(self.per_episode_cap_usd) > Decimal(self.campaign_cap_usd):
            raise ValueError("the per-episode cap cannot exceed the campaign cap")
        return self

    def model_cost_usd(self, prices: Mapping[str, Mapping[str, float]]) -> Decimal:
        """Total model spend at the given price table."""
        total = Decimal("0")
        for line in self.judge_lines:
            total += line.cost_usd(prices)
        return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    @property
    def expert_hours(self) -> float:
        """Total human hours across every line."""
        return sum(line.hours for line in self.expert_lines)

    def exceeds_cap(self, prices: Mapping[str, Mapping[str, float]]) -> bool:
        """Whether the estimated model spend is already over the cap.

        A cap below the estimate is not a stricter campaign, it is a
        campaign that stops halfway with a partial sample — which 07 §9
        says to publish, not to quietly re-run.
        """
        return self.model_cost_usd(prices) > Decimal(self.campaign_cap_usd)

    def lines(self, prices: Mapping[str, Mapping[str, float]], *, today: date) -> list[str]:
        """Render the estimate for an approval packet.

        Args:
            prices: The price table to cost against.
            today: The date to measure price staleness against.

        Returns:
            Lines, no trailing newlines. The first and last say what this
            document is, because a table of numbers extracted from the
            middle is exactly how an estimate becomes a quote.
        """
        rendered = [
            f"ESTIMATE ONLY — NOT AN APPROVAL ({self.estimate_id}@{self.revision})",
            f"  prepared for      {self.prepared_for}",
            f"  priced on         {self.priced_on}"
            f" (table last verified {self.prices_last_verified})",
            "  model spend",
        ]
        for line in self.judge_lines:
            rendered.append(
                f"    {line.label}: {line.calls} calls on {line.model_id}, "
                f"{line.input_tokens_per_call} in / {line.output_tokens_per_call} out "
                f"= ${line.cost_usd(prices)}"
            )
        rendered.append(f"    total model spend ${self.model_cost_usd(prices)}")
        rendered.append("  expert time")
        for expert in self.expert_lines:
            rendered.append(
                f"    {expert.label}: {expert.items} items x "
                f"{expert.minutes_per_item:g} min x {expert.annotators_per_item} "
                f"{expert.role}(s) = {expert.hours:.1f} h"
            )
        rendered.append(f"    total expert time {self.expert_hours:.1f} h")
        rendered.append(
            f"  caps              ${self.per_episode_cap_usd} per episode, "
            f"${self.campaign_cap_usd} per campaign"
        )
        rendered.append(f"  overshoot         {self.overshoot_behaviour}")
        rendered.append("  stop conditions")
        rendered.extend(
            f"    {condition.condition_id}: {condition.trigger} -> {condition.on_trigger}"
            for condition in self.stop_conditions
        )
        staleness = price_staleness(self.prices_last_verified, today=today)
        if staleness:
            rendered.append(f"  STALE PRICES      {staleness}")
        rendered.append(f"  note              {self.note}")
        rendered.append(
            "NOTHING IN THIS ESTIMATE HAS BEEN RUN. No judge, provider or paid "
            "labeling call has been made for P0-WO10, and D9 blocks every one of them "
            "until an owner records an approval."
        )
        return rendered


#: The stop conditions this protocol proposes. Adapted from 07 §9 to a
#: calibration run: the failure modes of a labeling campaign are not the
#: failure modes of a policy comparison, and reusing 07's list verbatim
#: would leave the ones that matter here unstated.
CALIBRATION_STOP_CONDITIONS: Final[tuple[StopCondition, ...]] = (
    StopCondition(
        condition_id="campaign-cap-reached",
        trigger="Cumulative model spend reaches the campaign cap.",
        on_trigger=(
            "Stop issuing calls, finish in-flight ones, publish the partial report with "
            "its denominators, and treat the stop as an outcome rather than a pause."
        ),
    ),
    StopCondition(
        condition_id="episode-cap-reached",
        trigger="One item's judging exceeds the per-episode cap.",
        on_trigger=(
            "Score that item null, keep it in the denominator, and continue. A null is "
            "a result; dropping the item would shrink the denominator silently."
        ),
    ),
    StopCondition(
        condition_id="expert-budget-reached",
        trigger="Approved annotator or adjudicator hours are exhausted.",
        on_trigger=(
            "Stop labeling. Report per-slice coverage against the plan and name every "
            "slice that fell short; an under-covered slice is reported unmeasured, "
            "never interpolated from its neighbours."
        ),
    ),
    StopCondition(
        condition_id="instrument-moved",
        trigger=(
            "A judge prompt, rubric version, model route or source representation "
            "changes mid-campaign."
        ),
        on_trigger=(
            "Stop. Labels collected before and after measure two instruments; resume "
            "as a new campaign against a new probe lock rather than pooling them."
        ),
    ),
    StopCondition(
        condition_id="blinding-breach",
        trigger="Any rendered judge input is found to name an arm, model or candidate.",
        on_trigger=(
            "Stop immediately and discard every verdict produced after the breach was "
            "introduced. An integrity violation is gated at absolute zero and no "
            "interval applies to it."
        ),
    ),
    StopCondition(
        condition_id="annotator-disagreement-collapse",
        trigger=(
            "Adjudication backlog exceeds a quarter of labelled items, or one "
            "annotator's decisions diverge from every other's on more than half of "
            "the shared items."
        ),
        on_trigger=(
            "Pause labeling and revise the annotation guide. Resume under a new "
            "guideline revision; do not re-label the backlog under the old one."
        ),
    ),
    StopCondition(
        condition_id="labels-would-be-edited",
        trigger="Anyone proposes changing a label after seeing a judge's verdict on it.",
        on_trigger=(
            "Refuse. RFC 11 §11 forbids editing a label to favour a candidate, and a "
            "judge verdict is a candidate result. A genuine labelling error is fixed "
            "by a superseding record with its own rationale, not by an edit."
        ),
    ),
)


def worked_example(
    *,
    items: int,
    pairwise_items: int,
    prices: Mapping[str, Mapping[str, float]],
    prices_last_verified: str,
    priced_on: str,
    judge_model: str = "claude-sonnet-5",
) -> CostEstimate:
    """Fill the template for a calibration run of `items` items.

    The token counts are stated rather than derived, and the note says
    where each came from: the current research judges are batched
    extract-and-judge prompts carrying a report excerpt and a source
    excerpt, which is the shape the numbers below assume. They are the
    first thing to re-derive against a real prompt before an approval.

    Args:
        items: Single-item probes to be judged.
        pairwise_items: Pairs, each judged in both orders.
        prices: The price table.
        prices_last_verified: ``PRICES_LAST_VERIFIED``.
        priced_on: The date the table was read.
        judge_model: The model id to price against. A pinned public id,
            not a route: 12 §18 asks for the exact then-current model id
            in the approval packet, and this estimate names the one it
            was costed on so a substitution is visible.

    Returns:
        The estimate.

    Raises:
        KeyError: `judge_model` is not in the price table.
    """
    if judge_model not in prices:
        raise KeyError(
            f"{judge_model} is not in the price table; an estimate priced at a "
            "fallback would under-report by up to 3.3x"
        )
    return CostEstimate(
        estimate_id="judge-calibration-pilot",
        revision="1.0.0",
        prepared_for=(
            f"AE-004 judge calibration: {items} single-item probes and "
            f"{pairwise_items} pairs judged in both orders, against one instrument."
        ),
        priced_on=priced_on,
        prices_last_verified=prices_last_verified,
        judge_lines=(
            JudgeCallLine(
                label="single-item verdicts",
                model_id=judge_model,
                calls=items,
                input_tokens_per_call=2200,
                output_tokens_per_call=200,
                note=(
                    "One call per item. Input is the judge rubric prompt (about 400 "
                    "tokens for the four in src/eval/metrics.py), a report excerpt and "
                    "a source excerpt; output is one decision plus a one-sentence "
                    "reason in the JSON shape those judges already return. Re-derive "
                    "against the real prompt before any approval."
                ),
            ),
            JudgeCallLine(
                label="pairwise verdicts, both orders",
                model_id=judge_model,
                calls=pairwise_items * 2,
                input_tokens_per_call=3600,
                output_tokens_per_call=200,
                note=(
                    "Two calls per pair, because a pair judged in one order cannot "
                    "separate a preference from a position. Input carries two report "
                    "excerpts, so it is larger than a single-item call."
                ),
            ),
            JudgeCallLine(
                label="repeat pass for judge self-consistency",
                model_id=judge_model,
                calls=items,
                input_tokens_per_call=2200,
                output_tokens_per_call=200,
                note=(
                    "A second independent reading of every single-item probe. The "
                    "Messages API exposes no sampling seed, so judge variance is real "
                    "and unmeasured; one repeat is the cheapest estimate of it and the "
                    "first line to cut if the cap binds."
                ),
            ),
        ),
        expert_lines=(
            ExpertTimeLine(
                label="claim-support and citation labelling",
                role="annotator",
                items=items,
                minutes_per_item=6.0,
                annotators_per_item=2,
                note=(
                    "Six minutes assumes the annotator reads a report excerpt and a "
                    "source excerpt and writes a one-sentence rationale. Two "
                    "annotators per item is the minimum that can produce a "
                    "disagreement; the worked set in "
                    "tests/fixtures/calibration/labelled_set.json records 50-210 "
                    "seconds per label as an authored illustration, not a measurement."
                ),
            ),
            ExpertTimeLine(
                label="pairwise preference labelling",
                role="annotator",
                items=pairwise_items,
                minutes_per_item=8.0,
                annotators_per_item=2,
                note=(
                    "Longer than a single item because the annotator reads two "
                    "excerpts. Annotators see one order only; the swap is a judge "
                    "control, and asking a person to read the same pair twice measures "
                    "their memory."
                ),
            ),
            ExpertTimeLine(
                label="adjudication of disputed items",
                role="adjudicator",
                items=max(1, items // 4),
                minutes_per_item=10.0,
                annotators_per_item=1,
                note=(
                    "Assumes a quarter of items are disputed, which is a planning "
                    "figure and not a measurement: the disputed fraction is itself an "
                    "output of the first campaign, and the "
                    "annotator-disagreement-collapse stop condition fires at exactly "
                    "this rate."
                ),
            ),
            ExpertTimeLine(
                label="guide authoring and annotator calibration session",
                role="reviewer",
                items=1,
                minutes_per_item=240.0,
                annotators_per_item=1,
                note=(
                    "A fixed cost paid once per guideline revision: writing the guide, "
                    "walking two annotators through the worked examples, and settling "
                    "the first disagreements together. Omitting it is how two "
                    "annotators end up as two populations."
                ),
            ),
        ),
        per_episode_cap_usd="0.050000",
        campaign_cap_usd="25.000000",
        overshoot_behaviour=(
            "Caps are checked before each call and again against the accumulated "
            "total after it returns. In-flight calls are allowed to finish and are "
            "counted, so the realised total may exceed the cap by at most one "
            "concurrency unit's worth of calls; the campaign records the overshoot "
            "rather than hiding it. No retry is issued after a cap is reached."
        ),
        stop_conditions=CALIBRATION_STOP_CONDITIONS,
        note=(
            "An estimate, not a quote and not an approval. The token counts are "
            "assumptions about prompts that have not been written; the disputed "
            "fraction is a planning figure; and the prices must be re-verified against "
            "the provider's published list before this is presented (12 §18). The "
            "number that decides this campaign is the expert hours, not the dollars: "
            "the model spend here is roughly the cost of a coffee and the human time "
            "is roughly a working week."
        ),
    )


def default_example(*, items: int, pairwise_items: int, priced_on: str) -> CostEstimate:
    """The worked example, priced from the product's live table.

    Args:
        items: Single-item probes.
        pairwise_items: Pairs.
        priced_on: The date the table was read, supplied by the caller.

    Returns:
        The estimate.
    """
    prices, verified = current_price_table()
    return worked_example(
        items=items,
        pairwise_items=pairwise_items,
        prices=prices,
        prices_last_verified=verified,
        priced_on=priced_on,
    )


def render(estimate: CostEstimate, *, today: date) -> str:
    """Render an estimate as text, priced from the product's live table."""
    prices, _ = current_price_table()
    return "\n".join(estimate.lines(prices, today=today))


def total_lines(estimates: Sequence[CostEstimate], *, today: date) -> list[str]:
    """Render several estimates, each with its own caps and stop rules.

    Deliberately does not sum them. Two estimates with different caps and
    different stop conditions do not add up to one campaign, and a
    combined total would be the number an approval got read from.
    """
    rendered: list[str] = []
    for estimate in estimates:
        rendered.extend(render(estimate, today=today).splitlines())
        rendered.append("")
    return rendered
