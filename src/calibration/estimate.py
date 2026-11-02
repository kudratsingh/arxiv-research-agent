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
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import StrictContractModel

if TYPE_CHECKING:
    from src.config import Settings

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


class MeasuredRoleTokens(StrictContractModel):
    """Measured input/output token quantiles for one funded-path role."""

    input_min: Annotated[int, Field(ge=0)]
    input_median: Annotated[int, Field(ge=0)]
    input_max: Annotated[int, Field(ge=0)]
    output_min: Annotated[int, Field(ge=0)]
    output_median: Annotated[int, Field(ge=0)]
    output_max: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def ordered(self) -> MeasuredRoleTokens:
        if not (
            self.input_min <= self.input_median <= self.input_max
            and self.output_min <= self.output_median <= self.output_max
        ):
            raise ValueError("measured token quantiles must be min <= median <= max")
        return self


#: What a caller may hand :func:`reestimate_from_measurements` for one
#: role. Three shapes, because three places produce them: the parsed
#: model, the compact ledger shape whose values are per-direction rows
#: (``{"min": {"input": ..., "output": ...}, ...}``), and the flat shape
#: whose values are token counts (``{"input_min": ..., ...}``). The two
#: mapping shapes differ in their *value* type, so the alias admits both
#: and :func:`reestimate_from_measurements` narrows per branch rather
#: than trusting the caller.
MeasuredRoleInput = MeasuredRoleTokens | Mapping[str, Mapping[str, int] | int]


def reestimate_from_measurements(
    measured_roles: Mapping[str, MeasuredRoleInput],
    *,
    revision_count: int,
    episodes: int = 60,
    max_papers: int | None = None,
    judge_model: str | None = None,
    config: Settings | None = None,
    revision_targets: Sequence[Literal["planner", "search", "synthesizer"]] | None = None,
    prices: Mapping[str, Mapping[str, float]] | None = None,
    prices_last_verified: str | None = None,
    priced_on: str = "1970-01-01",
) -> CostEstimate:
    """Re-price the fixed W12 graph without constructing any model client.

    ``revision_count`` counts completed extra passes: zero still includes the
    initial critic. Explicit targets follow ``route_after_critique``; without
    them, planner revisions conservatively repeat the whole workflow. Expected
    lines use median tokens and normal synthesis attempts. Caps use observed
    maximum tokens, the configured TOTAL critic-pass ceiling, full planner
    revisions and both possible synthesis attempts per pass. Judges run once
    after the final report. SDK retries/unknown billing are not measured here.

    Optional legacy paper/model arguments remain usable; when ``config`` is
    supplied they must agree with it, so a model route is never silently priced
    differently from that effective configuration. Unsupported graph policies
    are refused rather than assigned the fixed graph's cost.
    """
    from src.config import settings as default_config

    cfg = config if config is not None else default_config
    papers = cfg.max_papers if max_papers is None else max_papers
    judge = cfg.eval_judge_model if judge_model is None else judge_model
    if (
        type(revision_count) is not int
        or revision_count < 0
        or type(episodes) is not int
        or episodes <= 0
        or type(papers) is not int
        or papers <= 0
        or revision_count >= cfg.max_iterations
    ):
        raise ValueError(
            "revision_count must fit max_iterations total critic passes; episodes/max_papers must be positive integers"
        )
    if config is not None and (papers != cfg.max_papers or judge != cfg.eval_judge_model):
        raise ValueError("paper bound and judge route must match the supplied configuration")
    if (
        cfg.research_policy != "legacy"
        or cfg.enable_supervisor
        or cfg.enable_verifier
        or cfg.enable_query_refiner
        or cfg.compute_controller != "off"
    ):
        raise ValueError(
            "measured estimator supports only the fixed legacy graph without supervisor, verifier, refiner or controller"
        )
    targets = (
        tuple(revision_targets) if revision_targets is not None else ("planner",) * revision_count
    )
    if len(targets) != revision_count or any(
        target not in {"planner", "search", "synthesizer"} for target in targets
    ):
        raise ValueError("revision_targets must name one routable target per completed revision")
    if (prices is None) != (prices_last_verified is None):
        raise ValueError("prices and prices_last_verified must be supplied together")
    table, verified = current_price_table() if prices is None else (prices, prices_last_verified)
    assert verified is not None
    date.fromisoformat(verified)
    date.fromisoformat(priced_on)

    def count(value: Mapping[str, int] | int, field: str) -> int:
        if type(value) is not int:
            raise ValueError(f"measured field {field!r} must be an integer token count")
        return value

    def quantile(role: str) -> MeasuredRoleTokens:
        raw = measured_roles[role]
        if isinstance(raw, MeasuredRoleTokens):
            return raw
        if "median" in raw:

            def token(quantile_name: str, direction: str) -> int:
                row = raw[quantile_name]
                if not isinstance(row, Mapping):
                    raise ValueError(
                        f"measured quantile {quantile_name!r} must map direction to token count"
                    )
                key = direction if direction in row else f"{direction}_tokens"
                return count(row[key], key)

            return MeasuredRoleTokens(
                input_min=token("min", "input"),
                input_median=token("median", "input"),
                input_max=token("max", "input"),
                output_min=token("min", "output"),
                output_median=token("median", "output"),
                output_max=token("max", "output"),
            )
        return MeasuredRoleTokens(
            input_min=count(raw["input_min"], "input_min"),
            input_median=count(
                raw["input_median"] if "input_median" in raw else raw["median_input"],
                "input_median",
            ),
            input_max=count(raw["input_max"], "input_max"),
            output_min=count(raw["output_min"], "output_min"),
            output_median=count(
                raw["output_median"] if "output_median" in raw else raw["median_output"],
                "output_median",
            ),
            output_max=count(raw["output_max"], "output_max"),
        )

    workflow_roles = ("planner", "reader", "synthesizer", "critic")
    judge_roles = ("completeness", "faithfulness", "retrieval_recall")
    roles = workflow_roles + judge_roles
    if set(measured_roles) - set(roles):
        raise ValueError("unmodeled measured roles require a different cost model")
    measured = {role: quantile(role) for role in roles}
    expected_calls = {
        "planner": 1 + targets.count("planner"),
        "reader": papers * (1 + sum(target in {"planner", "search"} for target in targets)),
        "synthesizer": 1 + revision_count,
        "critic": 1 + revision_count,
        **dict.fromkeys(judge_roles, 1),
    }
    worst_calls = {
        "planner": cfg.max_iterations,
        "reader": papers * cfg.max_iterations,
        "synthesizer": 2 * cfg.max_iterations,
        "critic": cfg.max_iterations,
        **dict.fromkeys(judge_roles, 1),
    }
    models = {role: cfg.model_for(role) for role in workflow_roles}
    models.update(dict.fromkeys(judge_roles, judge))
    # Estimates refuse unpriced/negative/non-finite rows; no runtime fallback.
    for model in set(models.values()):
        row = table[model]
        for direction in ("input", "output"):
            rate = Decimal(str(row[direction]))
            if not rate.is_finite() or rate < 0:
                raise ValueError("prices must be finite non-negative USD per million tokens")

    def lines(counts: Mapping[str, int], maximum: bool) -> tuple[JudgeCallLine, ...]:
        return tuple(
            JudgeCallLine(
                label=role,
                model_id=models[role],
                calls=episodes * counts[role],
                input_tokens_per_call=measured[role].input_max
                if maximum
                else measured[role].input_median,
                output_tokens_per_call=measured[role].output_max
                if maximum
                else measured[role].output_median,
                note=(
                    "Stage-1 observed maximum per-call tokens; full planner passes and synthesis corrective retry"
                    if maximum
                    else "Stage-1 measured median per-call tokens; initial pass plus declared revision targets"
                ),
            )
            for role in roles
        )

    expected_lines, worst_lines = lines(expected_calls, False), lines(worst_calls, True)
    # Do not round each tiny line down before deriving a cap. Round the envelope
    # UP to a micro-dollar, then multiply so the campaign covers every episode.
    worst_total = sum(
        (
            Decimal(line.calls)
            * (
                Decimal(line.input_tokens_per_call) * Decimal(str(table[line.model_id]["input"]))
                + Decimal(line.output_tokens_per_call)
                * Decimal(str(table[line.model_id]["output"]))
            )
            / Decimal(TOKENS_PER_MILLION)
            for line in worst_lines
        ),
        Decimal(0),
    )
    per_episode = (worst_total / Decimal(episodes) * Decimal("1.25")).quantize(
        Decimal("0.000001"), rounding=ROUND_CEILING
    )
    cap = per_episode * episodes
    return CostEstimate(
        estimate_id="w12-measured-reestimate",
        revision="2.0.0",
        prepared_for=f"W12 fixed arm-A baseline, {episodes} episodes, {revision_count} completed revisions; at most {cfg.max_iterations} critic passes",
        priced_on=priced_on,
        prices_last_verified=verified,
        judge_lines=expected_lines,
        worst_case_lines=worst_lines,
        measured_roles=measured,
        measured_revision_targets=targets,
        maximum_critic_passes=cfg.max_iterations,
        per_episode_cap_usd=f"{per_episode:.6f}",
        campaign_cap_usd=f"{cap:.6f}",
        overshoot_behaviour="One in-flight reader fan-out; both caps use 1.25x observed-max tokens at full planner-pass and synthesis-retry ceilings, rounded up per episode. SDK retries/unknown billing require separate reservations.",
        stop_conditions=CALIBRATION_STOP_CONDITIONS[:2],
        note="Measured-token re-estimate; prices remain ESTIMATE. Missing revision targets conservatively mean planner revisions. Observed token maxima are measurements, not hard provider output limits or an approval. Actual routes and quantiles are retained; SDK retries, caching and unknown spend are not inferred.",
    )


# Descriptive alias for callers that use the work-order wording.
reestimate_measured_tokens = reestimate_from_measurements


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
    worst_case_lines: tuple[JudgeCallLine, ...] = ()
    measured_roles: Mapping[str, MeasuredRoleTokens] = Field(default_factory=dict)
    measured_revision_targets: tuple[str, ...] = ()
    maximum_critic_passes: int | None = None
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
            raise ValueError("an estimate without stop conditions is a budget, not a plan (07 §9)")
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
        if self.worst_case_lines:
            rendered.append(
                f"  cap basis: observed-max tokens, up to {self.maximum_critic_passes} total critic passes and two synthesis attempts/pass"
            )
            for worst in self.worst_case_lines:
                rendered.append(
                    f"    {worst.label}: {worst.calls} calls on {worst.model_id}, {worst.input_tokens_per_call} in / {worst.output_tokens_per_call} out"
                )
            for role, measured in self.measured_roles.items():
                rendered.append(
                    f"    measured {role}: min/median/max input {measured.input_min}/{measured.input_median}/{measured.input_max}, output {measured.output_min}/{measured.output_median}/{measured.output_max}"
                )
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
    judge_lines = [
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
        )
    ]
    if pairwise_items:
        judge_lines.append(
            JudgeCallLine(
                label="pairwise verdicts, both orders",
                model_id=judge_model,
                calls=pairwise_items * 2,
                input_tokens_per_call=3600,
                output_tokens_per_call=200,
                note="Two calls per pair, because a pair judged in one order cannot separate a preference from a position.",
            )
        )
    judge_lines.append(
        JudgeCallLine(
            label="repeat pass for judge self-consistency",
            model_id=judge_model,
            calls=items,
            input_tokens_per_call=2200,
            output_tokens_per_call=200,
            note="A second independent reading of every single-item probe estimates judge variance.",
        )
    )
    expert_lines = [
        ExpertTimeLine(
            label="claim-support and citation labelling",
            role="annotator",
            items=items,
            minutes_per_item=6.0,
            annotators_per_item=2,
            note="Two annotators per item are the minimum that can produce a disagreement.",
        )
    ]
    if pairwise_items:
        expert_lines.append(
            ExpertTimeLine(
                label="pairwise preference labelling",
                role="annotator",
                items=pairwise_items,
                minutes_per_item=8.0,
                annotators_per_item=2,
                note="Pairwise labeling is deferred until a pairwise judge exists.",
            )
        )
    expert_lines.extend(
        [
            ExpertTimeLine(
                label="adjudication of disputed items",
                role="adjudicator",
                items=max(1, items // 4),
                minutes_per_item=10.0,
                annotators_per_item=1,
                note="The disputed fraction is a planning figure, not a measurement.",
            ),
            ExpertTimeLine(
                label="guide authoring and annotator calibration session",
                role="reviewer",
                items=1,
                minutes_per_item=240.0,
                annotators_per_item=1,
                note="One session to agree the guide before labeling.",
            ),
        ]
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
        judge_lines=tuple(judge_lines),
        expert_lines=tuple(expert_lines),
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
