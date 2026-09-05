"""Blinding and randomisation for a judge-calibration run.

03 §7 asks for three things before a judge's numbers mean anything:
blind the judge's input to candidate identity and experiment arm,
randomise pairwise ordering, and test for position bias. This module is
those three as objects a campaign can be checked against rather than a
paragraph a campaign can forget.

**Blinding is a mapping, not a redaction pass.** The item a judge sees is
addressed by ``itm-<12 hex>`` derived from a salted digest of the real
case id (:func:`blind_item_id`). The salt lives in an evaluator-only
content object and never appears in a label, a verdict or a report, so
the blinded corpus can be handed around without handing around the key.
Redaction — stripping arm names out of prose — is the second layer, not
the first: :func:`leaked_identity_terms` exists to catch the cases where
the identity leaked through the *content* after the identifiers were
already clean.

**Both orders, always.** ``docs/eval.md`` records the current state of
the evidence: verbosity bias has collapsed below 0.011 across 21
measured judges, and position bias has not. The control it names is
swap/AB+BA averaging. So a pairwise item is not sampled into one order —
it is presented in *both*, which makes position bias a measured quantity
rather than an assumption, and makes the preference estimate the average
of the two orders rather than a coin flip about which order it got.

**The randomisation is seeded and local.** :func:`assign_presentations`
takes a seed and uses its own :class:`random.Random`, exactly as
``src/eval/stats.py``'s bootstrap does, so a plan is reproducible and
never perturbs the campaign's global generator. What the seed pins is
the *presentation schedule*: the Anthropic Messages API exposes no
sampling seed, so a seeded schedule does not make a judge deterministic
and this module does not pretend it does.
"""

from __future__ import annotations

import hashlib
import random
import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import Annotated, Final

from pydantic import Field, StringConstraints, model_validator

from src.contracts.kernel import (
    ImmutableObjectRef,
    Rfc3339Utc,
    SemVer,
    StrictContractModel,
)

#: Fields that must not reach the judge, from 03 §7.2 and 12 §3.6.
#: Candidate identity and arm are the two 03 names; the rest are the
#: fields that *reconstruct* them — a report tagged with its policy id,
#: its model, its run id or its cost is not blinded, it is blinded in the
#: one field somebody remembered.
HIDDEN_FROM_JUDGE: Final[frozenset[str]] = frozenset(
    {
        "arm_id",
        "candidate_id",
        "policy_id",
        "model_id",
        "prompt_version",
        "run_id",
        "repeat_index",
        "campaign_id",
        "cost_usd",
        "latency_ms",
        "split_membership",
        "reference_answer",
        "expected_label",
    }
)

#: Length of the blinded suffix, in hex characters. 48 bits: the corpus
#: is hundreds of items, so collisions are not the risk — guessing is,
#: and a 12-character opaque id is not reversible without the salt while
#: staying short enough to say out loud in an adjudication meeting.
BLINDED_SUFFIX_LEN: Final[int] = 12


class Presentation(StrEnum):
    """How an item is shown to a judge."""

    SINGLE = "single"
    PAIRWISE = "pairwise"


class PairOrder(StrEnum):
    """Which order a pair was shown in.

    ``AB`` and ``BA`` name *presentation* order, not candidate identity:
    which report is A is itself part of the blinding, and the judge sees
    neither letter.
    """

    AB = "ab"
    BA = "ba"


def blind_item_id(salt: str, real_id: str) -> str:
    """Return the blinded id for one real case id under one salt.

    ``sha256(salt + "\\x00" + real_id)``, truncated. The NUL separator is
    not decoration: without it ``("ab", "cd")`` and ``("a", "bcd")``
    hash to the same value, and a campaign that salts per slice would get
    two slices sharing an id.

    Deterministic and pure, so the same corpus blinds identically in a
    plan, in a test, and in a later audit that has the salt.

    Args:
        salt: The campaign's evaluator-only salt. Never checked in, never
            carried in a label; a plan references it by digest.
        real_id: The registry case id being blinded.

    Returns:
        ``itm-<12 lowercase hex>``.

    Raises:
        ValueError: The salt is empty. A blinding with no salt is a
            reversible one — the digest of a public case id is a lookup
            table anyone can build.
    """
    if not salt:
        raise ValueError("blinding requires a non-empty salt; an unsalted digest is reversible")
    payload = f"{salt}\x00{real_id}".encode()
    return f"itm-{hashlib.sha256(payload).hexdigest()[:BLINDED_SUFFIX_LEN]}"


class BlindingPlan(StrictContractModel):
    """What is hidden, how orders are drawn, and under which seed.

    Attributes:
        plan_id: Stable id.
        revision: Semantic revision. Changing what is hidden or how
            orders are drawn changes the instrument, so it changes the
            revision and, per 03 §7.7, triggers recalibration.
        salt_ref: Reference to the evaluator-only salt object. The salt
            itself is never a field here — a plan is reviewable material
            and a salt in it would blind nobody.
        hidden_fields: Fields withheld from the judge's input. Must
            include every field in :data:`HIDDEN_FROM_JUDGE`; a plan may
            hide more, never less.
        seed: Seed for the presentation schedule.
        presentation: Single or pairwise.
        both_orders: Pairwise items are shown in both orders. Fixed
            ``True`` for pairwise plans: a design that samples one order
            per pair cannot separate a preference from a position, and
            the correction is not available after the fact.
        judge_sees_reference: Fixed ``False``. Present as a field so the
            answer is written down in the plan a reviewer reads, rather
            than being an absence they have to notice.
    """

    plan_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    revision: SemVer
    salt_ref: ImmutableObjectRef
    hidden_fields: tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]
    seed: Annotated[int, Field(ge=0)]
    presentation: Presentation
    both_orders: bool = True
    judge_sees_reference: bool = False
    created_at: Rfc3339Utc

    @model_validator(mode="after")
    def hides_at_least_the_required_fields(self) -> BlindingPlan:
        if len(set(self.hidden_fields)) != len(self.hidden_fields):
            raise ValueError("hidden_fields must be unique")
        missing = sorted(HIDDEN_FROM_JUDGE - set(self.hidden_fields))
        if missing:
            raise ValueError(
                f"a blinding plan must hide at least the required fields; missing {missing}"
            )
        if self.judge_sees_reference:
            raise ValueError(
                "a judge that sees the reference answer is not being calibrated against it"
            )
        if self.presentation is Presentation.PAIRWISE and not self.both_orders:
            raise ValueError(
                "a pairwise plan must present both orders; one order per pair cannot "
                "separate a preference from a position (docs/eval.md)"
            )
        return self


class PresentationAssignment(StrictContractModel):
    """One scheduled presentation of one item.

    Attributes:
        sequence: Position in the schedule, from 1. Contiguous across the
            whole schedule, so a gap is a dropped presentation rather
            than a rounding difference.
        blinded_item_id: What is shown.
        presentation: Single or pairwise.
        order: For pairwise, which order. ``None`` for single.
    """

    sequence: Annotated[int, Field(ge=1)]
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    presentation: Presentation
    order: PairOrder | None = None

    @model_validator(mode="after")
    def order_matches_presentation(self) -> PresentationAssignment:
        if (self.presentation is Presentation.PAIRWISE) != (self.order is not None):
            raise ValueError("a pairwise assignment has an order and a single one does not")
        return self


def assign_presentations(
    blinded_item_ids: Sequence[str], *, plan: BlindingPlan
) -> tuple[PresentationAssignment, ...]:
    """Draw the presentation schedule for a blinded corpus.

    Single-item plans produce one assignment per item, shuffled. Pairwise
    plans produce **two** — ``ab`` and ``ba`` — and shuffle the flattened
    list, so the two orders of one pair are not adjacent. Adjacency is
    the thing worth avoiding: a judge shown the same pair twice in a row
    is answering a memory question, and the two readings stop being
    independent.

    The input is sorted before shuffling, so the schedule depends on the
    *set* of items and the seed rather than on the order a caller
    happened to pass them in.

    Args:
        blinded_item_ids: Blinded ids, distinct.
        plan: The blinding plan, which supplies the seed and the mode.

    Returns:
        The schedule, ``sequence`` contiguous from 1.

    Raises:
        ValueError: The ids are not distinct, or one is not blinded.
    """
    unique = sorted(set(blinded_item_ids))
    if len(unique) != len(blinded_item_ids):
        raise ValueError("presentation ids must be distinct")
    for item_id in unique:
        if not re.fullmatch(r"itm-[0-9a-f]{12}", item_id):
            raise ValueError(f"{item_id!r} is not a blinded item id")

    if plan.presentation is Presentation.PAIRWISE:
        slots: list[tuple[str, PairOrder | None]] = [
            (item_id, order) for item_id in unique for order in (PairOrder.AB, PairOrder.BA)
        ]
    else:
        slots = [(item_id, None) for item_id in unique]

    rng = random.Random(plan.seed)
    rng.shuffle(slots)
    return tuple(
        PresentationAssignment(
            sequence=index,
            blinded_item_id=item_id,
            presentation=plan.presentation,
            order=order,
        )
        for index, (item_id, order) in enumerate(slots, start=1)
    )


def leaked_identity_terms(rendered: str, forbidden: Iterable[str]) -> tuple[str, ...]:
    """Return the forbidden terms that appear in a rendered judge input.

    The second layer of blinding. The first layer removes the *fields*;
    this one catches the identity that came back through the content — a
    report that says "the verify-and-repair pass found", a source excerpt
    that names the model, an arm label left in a heading. It is a check
    a campaign runs against every rendered prompt before sending it, and
    a finding is an integrity violation rather than a warning: see
    :data:`src.calibration.metrics.INTEGRITY_VIOLATION_CLASSES`.

    Matching is case-insensitive and word-boundary anchored, so ``arm-c``
    is found in "the arm-c report" and not inside "harm-caused". Terms
    are matched literally; a caller passing a regex gets its characters
    escaped, because a blinding check is not the place to run a pattern
    somebody typed.

    Args:
        rendered: The exact text that would be sent to the judge.
        forbidden: Terms that must not appear — arm ids, policy names,
            model ids, candidate names.

    Returns:
        The terms found, sorted and deduplicated. Empty when clean.
    """
    found: set[str] = set()
    for term in forbidden:
        if not term:
            continue
        pattern = re.compile(rf"(?<![0-9A-Za-z]){re.escape(term)}(?![0-9A-Za-z])", re.IGNORECASE)
        if pattern.search(rendered):
            found.add(term)
    return tuple(sorted(found))
