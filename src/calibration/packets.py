"""Offline expert-labeling packets, and the agreement report they feed.

A packet is the half of a calibration campaign that leaves the machine.
It is rendered from the sealed registry, carries only the material an
annotator has to read, and deliberately omits the real case id, the
reference decision, the authored rationale and the slice tags — the four
fields that would turn labeling into transcription.

**The blinding key travels separately.** Everything needed to un-blind a
packet — which registry case each ``itm-…`` really is, which slices it
belongs to, and which presentation order that packet used — lives in a
:class:`PacketManifest` written outside every packet directory and marked
evaluator-only. The annotator receives one directory and the steward
keeps the manifest, so handing over the wrong file is a visible mistake
rather than a silent one.

**Order is randomised, not assigned.** 14 §7.3 asks for two things that
pull in opposite directions: every pairwise item must be seen in *both*
orders, and no annotator may see the same pair twice (that measures their
memory, not their judgement). So the two packets split each pair's
orders, and which packet gets ``ab`` is a seeded coin flip per item
rather than a property of the packet — otherwise "packet B" would just be
a synonym for "the swapped one". The item order inside each packet is
shuffled under the same seed. The seed defaults to the registered
blinding plan's, so the default packet set is reproducible by anybody
holding the repository.

Nothing here calls a model, a provider or the network, and nothing here
starts a labeling campaign: 14 §12 and §14 still gate expert time on real
material.
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.calibration.blinding import BlindingPlan, PairOrder
from src.calibration.labels import (
    NON_DECISIONS,
    Confidence,
    LabelType,
    binary_outcome,
    decision_vocabulary,
)
from src.calibration.metrics import AbstentionPolicy, agreement, error_rates
from src.calibration.suite import (
    BLINDING_PLAN_ID,
    CALIBRATION_REGISTRY_ROOT,
    CONTENT_DIRNAME,
    LABEL_SET_ID,
    OBJECT_REVISION,
    REPO_ROOT,
    BlindingPlanContent,
    CalibrationContentEnvelope,
    CalibrationItemContent,
    ExpectedLabelValue,
    locator,
)
from src.contracts.kernel import StrictContractModel, canonical_json, sha256_digest
from src.contracts.registry import LabelSet, RegistryEnvelope, TaskCase
from src.eval.stats import wilson_interval

PACKET_SCHEMA_VERSION: Final[str] = "1.0.0"

#: The two independent annotator slots. Two, because 14 §5 adjudicates
#: disagreement between two labels and cannot adjudicate one.
PACKET_IDS: Final[tuple[str, str]] = ("expert-a", "expert-b")

#: Where a generated packet set lands. ``outputs/`` is ignored and a
#: generated packet is never committed: it is an operator artifact whose
#: retention is still an open owner decision (14 §14).
DEFAULT_OUTPUT_ROOT: Final[Path] = REPO_ROOT / "outputs" / "calibration"

#: Carried at the top of every manifest. The manifest *is* the blinding
#: key; a sentence saying so beats a filename convention nobody reads.
MANIFEST_HANDLING: Final[str] = (
    "EVALUATOR ONLY. This manifest is the blinding key: it maps every blinded "
    "item back to its registry case, names each item's slices, and records the "
    "presentation order each packet used. Never send it, or any line of it, to "
    "an annotator. Hand over only the expert-<slot>/ directory."
)

#: The abstention policy every report below is computed under, from
#: 14 §9.2. Declared rather than defaulted, and carried in the report.
REPORT_ABSTENTION_POLICY: Final[AbstentionPolicy] = AbstentionPolicy.EXCLUDED

#: What an annotator is told. Five sentences, because the sixth would not
#: be read and the fifth is the one that prevents the most common return.
INSTRUCTIONS: Final[tuple[str, ...]] = (
    "Work independently. Do not seek an answer key or another annotator's labels.",
    "Choose exactly one allowed decision, one confidence bucket, and write a rationale.",
    "For pairwise items, first and second name only the order shown to you here.",
    "Do not include your name or email; the campaign steward assigns a pseudonym.",
    "Leave nothing blank: a partially filled packet is refused, not partially scored.",
)


class PacketMaterial(StrictContractModel):
    """The verbatim text an annotator reads for one item.

    Pairwise material is stored in *presentation* order: ``report_excerpt``
    is whatever this packet shows first. Which registry candidate that
    was is in the manifest, not here.
    """

    report_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    cited_source: str | None = None
    source_excerpt: str | None = None
    rubric_item: str | None = None
    second_excerpt: str | None = None


class BlankResponse(StrictContractModel):
    """The three fields an annotator fills in. Blank by construction."""

    decision: None = None
    confidence: None = None
    rationale: None = None


class PacketItem(StrictContractModel):
    """One blinded item as an annotator receives it.

    There is no ``presentation_order`` field, and its absence is the
    design: an annotator who can see that *this* item was swapped knows
    something about the item that the item is not supposed to tell them.
    The order is in the manifest, which is how ingestion recovers it.
    """

    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    material: PacketMaterial
    allowed_decisions: tuple[str, ...]
    response: BlankResponse = BlankResponse()

    @model_validator(mode="after")
    def shape_matches_label_type(self) -> PacketItem:
        pairwise = self.label_type is LabelType.PAIRWISE_PREFERENCE
        if pairwise != (self.material.second_excerpt is not None):
            raise ValueError("second_excerpt is required only for pairwise items")
        if self.allowed_decisions != decision_vocabulary(self.label_type):
            raise ValueError("allowed_decisions do not match the registered vocabulary")
        return self


class LabelPacket(StrictContractModel):
    """One annotator's whole packet. ``annotator_id`` is filled by the steward."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: Annotated[str, StringConstraints(pattern=r"^expert-[ab]$")]
    annotator_id: None = None
    instructions: tuple[str, ...]
    items: tuple[PacketItem, ...]

    @model_validator(mode="after")
    def item_ids_are_unique(self) -> LabelPacket:
        ids = [item.blinded_item_id for item in self.items]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("packet item ids must be non-empty and unique")
        return self


class ManifestEntry(StrictContractModel):
    """The blinding key for one item in one packet."""

    position: Annotated[int, Field(ge=1)]
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    case_id: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    label_type: LabelType
    slice_tags: tuple[str, ...]
    presentation_order: Literal["ab", "ba"] | None = None

    @model_validator(mode="after")
    def order_matches_label_type(self) -> ManifestEntry:
        pairwise = self.label_type is LabelType.PAIRWISE_PREFERENCE
        if pairwise != (self.presentation_order is not None):
            raise ValueError("presentation_order is recorded only for pairwise items")
        return self


class PacketKey(StrictContractModel):
    """One packet's entries, in the order the annotator sees them."""

    packet_id: Annotated[str, StringConstraints(pattern=r"^expert-[ab]$")]
    entries: tuple[ManifestEntry, ...]

    @model_validator(mode="after")
    def positions_are_contiguous(self) -> PacketKey:
        positions = [entry.position for entry in self.entries]
        if positions != list(range(1, len(positions) + 1)):
            raise ValueError("manifest positions must be contiguous from 1")
        ids = [entry.blinded_item_id for entry in self.entries]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("manifest item ids must be non-empty and unique")
        return self


class PacketManifest(StrictContractModel):
    """The evaluator-only half of a packet set.

    Carries identity, slice membership and presentation order — and not
    the reference decisions. The answer key stays in the sealed registry
    and is resolved at ingest time, so a leaked manifest reveals which
    case an item is, never what the right answer was.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_set_id: Annotated[str, StringConstraints(pattern=r"^pkt-[0-9a-f]{12}$")]
    seed: Annotated[int, Field(ge=0)]
    label_set_ref: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    blinding_plan_ref: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    handling: Annotated[str, StringConstraints(min_length=1, max_length=600)]
    packets: tuple[PacketKey, ...]

    @model_validator(mode="after")
    def every_packet_covers_the_same_items(self) -> PacketManifest:
        if [key.packet_id for key in self.packets] != list(PACKET_IDS):
            raise ValueError(f"a manifest describes exactly {list(PACKET_IDS)}")
        covered = [
            frozenset(entry.blinded_item_id for entry in key.entries)
            for key in self.packets
        ]
        if len(set(covered)) != 1:
            raise ValueError("every packet in a set must cover the same items")
        return self

    def key_for(self, packet_id: str) -> PacketKey:
        """Return one packet's key.

        Args:
            packet_id: The annotator slot.

        Returns:
            The key.

        Raises:
            ValueError: No packet in this set carries that id.
        """
        for key in self.packets:
            if key.packet_id == packet_id:
                return key
        raise ValueError(
            f"{packet_id!r} is not a packet of set {self.packet_set_id}; "
            f"this manifest describes {[key.packet_id for key in self.packets]}"
        )


class PacketSet(StrictContractModel):
    """Two blinded packets and the key that un-blinds them."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_set_id: Annotated[str, StringConstraints(pattern=r"^pkt-[0-9a-f]{12}$")]
    seed: Annotated[int, Field(ge=0)]
    packets: tuple[LabelPacket, ...]
    manifest: PacketManifest

    @model_validator(mode="after")
    def the_set_and_its_key_agree(self) -> PacketSet:
        if [packet.packet_id for packet in self.packets] != list(PACKET_IDS):
            raise ValueError(f"a packet set contains exactly {list(PACKET_IDS)}")
        if self.manifest.packet_set_id != self.packet_set_id:
            raise ValueError("manifest describes a different packet set")
        if self.manifest.seed != self.seed:
            raise ValueError("manifest seed differs from the packet set's")
        return self

    def packet(self, packet_id: str) -> LabelPacket:
        """Return one packet by slot id.

        Args:
            packet_id: The annotator slot.

        Returns:
            The packet.

        Raises:
            ValueError: No packet carries that id.
        """
        for packet in self.packets:
            if packet.packet_id == packet_id:
                return packet
        raise ValueError(f"{packet_id!r} is not a packet of set {self.packet_set_id}")


class CompletedResponse(StrictContractModel):
    """A filled response. Every field required; a blank one is not a label."""

    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: Confidence
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class CompletedPacketItem(StrictContractModel):
    """One item of a returned packet."""

    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    material: PacketMaterial
    allowed_decisions: tuple[str, ...]
    response: CompletedResponse

    @model_validator(mode="after")
    def completed_response_matches_the_item(self) -> CompletedPacketItem:
        if self.allowed_decisions != decision_vocabulary(self.label_type):
            raise ValueError("allowed_decisions do not match the registered vocabulary")
        if self.response.decision not in self.allowed_decisions:
            raise ValueError(
                f"{self.response.decision!r} is outside the vocabulary of "
                f"{self.label_type.value}"
            )
        return self


class CompletedLabelPacket(StrictContractModel):
    """A packet handed back with every response filled in."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: Annotated[str, StringConstraints(pattern=r"^expert-[ab]$")]
    annotator_id: Annotated[str, StringConstraints(pattern=r"^ann-[a-z0-9]{4,32}$")]
    instructions: tuple[str, ...]
    items: tuple[CompletedPacketItem, ...]

    @model_validator(mode="after")
    def item_ids_are_unique(self) -> CompletedLabelPacket:
        ids = [item.blinded_item_id for item in self.items]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("completed packet item ids must be non-empty and unique")
        return self


class SubmittedLabel(StrictContractModel):
    """One decision, in the compact file shape.

    No presentation order: an annotator never learns it and cannot report
    it. Ingestion reads the order from the manifest.
    """

    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: Confidence
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def decision_is_in_the_vocabulary(self) -> SubmittedLabel:
        if self.decision not in decision_vocabulary(self.label_type):
            raise ValueError(f"{self.decision!r} is not valid for {self.label_type.value}")
        return self


class SubmittedLabelFile(StrictContractModel):
    """The compact alternative to handing back the whole packet."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: Annotated[str, StringConstraints(pattern=r"^expert-[ab]$")]
    annotator_id: Annotated[str, StringConstraints(pattern=r"^ann-[a-z0-9]{4,32}$")]
    labels: tuple[SubmittedLabel, ...]

    @model_validator(mode="after")
    def item_ids_are_unique(self) -> SubmittedLabelFile:
        ids = [label.blinded_item_id for label in self.labels]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("submitted label ids must be non-empty and unique")
        return self


@dataclass(frozen=True)
class RegisteredCase:
    """One registry case, with both halves resolved. Evaluator-only."""

    case_id: str
    blinded_item_id: str
    label_type: LabelType
    slice_tags: tuple[str, ...]
    expected_decision: str
    material: CalibrationItemContent


@dataclass(frozen=True)
class ResolvedLabel:
    """One submitted decision, un-blinded against the registry."""

    blinded_item_id: str
    case_id: str
    label_type: LabelType
    slice_tags: tuple[str, ...]
    expected_decision: str
    presentation_order: Literal["ab", "ba"] | None
    shown_decision: str
    decision: str


class RateSummary(StrictContractModel):
    """One rate, both its counts, and its Wilson interval (14 §9.3)."""

    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=0)]
    rate: float | None
    interval_low: float | None
    interval_high: float | None

    @model_validator(mode="after")
    def an_absent_rate_has_an_absent_interval(self) -> RateSummary:
        bounds = (self.interval_low, self.interval_high)
        if (self.rate is None) != (bounds == (None, None)):
            raise ValueError("a rate and its interval are present or absent together")
        if (self.interval_low is None) != (self.interval_high is None):
            raise ValueError("an interval has two bounds or none")
        return self


class SliceLabelReport(StrictContractModel):
    """Agreement for one slice, in the form 14 §9.1 fixed.

    Raw agreement is never published without φ and both positive rates:
    they are fields of the same object and cells of the same table row.
    """

    slice_id: str
    items: Annotated[int, Field(ge=0)]
    binary_items: Annotated[int, Field(ge=0)]
    pairwise_items: Annotated[int, Field(ge=0)]
    raw_agreement: RateSummary
    phi: float | None
    annotator_positive: RateSummary
    reference_positive: RateSummary
    exact_decision_match: RateSummary
    false_pass: RateSummary
    false_fail: RateSummary
    abstention: RateSummary
    unresolved_reference: RateSummary
    pairwise_agreement: RateSummary
    pairwise_non_decision: RateSummary


class LabelIngestReport(StrictContractModel):
    """What one completed packet says about one annotator."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_set_id: Annotated[str, StringConstraints(pattern=r"^pkt-[0-9a-f]{12}$")]
    packet_id: str
    annotator_id: str
    seed: Annotated[int, Field(ge=0)]
    source_label_set: str
    abstention_policy: str
    labels_ingested: Annotated[int, Field(ge=0)]
    overall: SliceLabelReport
    slices: tuple[SliceLabelReport, ...]


def _read_registry(path: Path) -> RegistryEnvelope:
    return RegistryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def _read_content(path: Path) -> CalibrationContentEnvelope:
    return CalibrationContentEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def registered_blinding_plan(root: Path = CALIBRATION_REGISTRY_ROOT) -> BlindingPlan:
    """Return the suite's registered blinding plan.

    The plan is where the default seed comes from, so the default packet
    set is reproducible by anybody holding the repository rather than by
    whoever happened to type a number.

    Args:
        root: Registry root.

    Returns:
        The plan.

    Raises:
        ValueError: The registered object is not a blinding plan.
    """
    path = (
        root / CONTENT_DIRNAME / "blinding_plan" / BLINDING_PLAN_ID / f"{OBJECT_REVISION}.json"
    )
    envelope = _read_content(path)
    if not isinstance(envelope.payload, BlindingPlanContent):
        raise ValueError(f"{path} is not a blinding plan")
    return envelope.payload.plan


def load_registered_cases(
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> tuple[RegisteredCase, ...]:
    """Resolve packet material and answer keys through sealed registry refs.

    Args:
        root: Registry root.

    Returns:
        Every registered case, sorted by blinded item id so the order is
        a property of the corpus rather than of the file system.

    Raises:
        ValueError: A ref resolves to the wrong kind of object, or a case
            and its expected label disagree about the label type.
    """
    label_path = root / "label_set" / LABEL_SET_ID / f"{OBJECT_REVISION}.json"
    label_envelope = _read_registry(label_path)
    if not isinstance(label_envelope.payload, LabelSet):
        raise ValueError(f"{label_path} is not a label set")

    cases: list[RegisteredCase] = []
    for label in label_envelope.payload.labels:
        target = _read_registry(root / locator(label.target_ref, content=False))
        if not isinstance(target.payload, TaskCase):
            raise ValueError(f"{label.label_id}: target is not a task case")
        item_refs = [
            ref for ref in target.payload.evaluator_refs if ref.kind == "calibration_item"
        ]
        if len(item_refs) != 1:
            raise ValueError(f"{label.label_id}: expected exactly one calibration item")
        item_envelope = _read_content(root / locator(item_refs[0], content=True))
        value_envelope = _read_content(root / locator(label.value_ref, content=True))
        if not isinstance(item_envelope.payload, CalibrationItemContent):
            raise ValueError(f"{label.label_id}: evaluator ref is not calibration material")
        if not isinstance(value_envelope.payload, ExpectedLabelValue):
            raise ValueError(f"{label.label_id}: value ref is not an expected label")
        item = item_envelope.payload
        value = value_envelope.payload
        label_type = LabelType(item.label_type)
        if value.label_type != label_type.value:
            raise ValueError(f"{label.label_id}: item and expected label types differ")
        cases.append(
            RegisteredCase(
                case_id=target.payload.case_id,
                blinded_item_id=item.blinded_item_id,
                label_type=label_type,
                slice_tags=target.payload.slice_tags,
                expected_decision=value.decision,
                material=item,
            )
        )
    return tuple(sorted(cases, key=lambda case: case.blinded_item_id))


def _order_value(order: PairOrder | None) -> Literal["ab", "ba"] | None:
    if order is None:
        return None
    return "ab" if order is PairOrder.AB else "ba"


def _packet_item(case: RegisteredCase, *, order: PairOrder | None) -> PacketItem:
    """Render one registry case as the annotator will see it.

    A ``ba`` order swaps the two excerpts rather than labelling them, so
    the annotator's "the first one" is a position and the manifest is the
    only thing that can map it back to a candidate.
    """
    report = case.material.report_excerpt
    second = case.material.second_excerpt
    # A pairwise case always carries both excerpts — ``PacketItem`` refuses
    # one that does not — so the second clause narrows the type rather than
    # guarding a case the registry can produce.
    if order is PairOrder.BA and second is not None:
        report, second = second, report
    return PacketItem(
        blinded_item_id=case.blinded_item_id,
        label_type=case.label_type,
        material=PacketMaterial(
            report_excerpt=report,
            cited_source=case.material.cited_source,
            source_excerpt=case.material.source_excerpt,
            rubric_item=case.material.rubric_item,
            second_excerpt=second,
        ),
        allowed_decisions=decision_vocabulary(case.label_type),
    )


def _packet_set_id(seed: int, blinded_ids: Sequence[str]) -> str:
    """Name a packet set by what determines it: corpus, seed and shape."""
    digest = sha256_digest(
        {
            "schema_version": PACKET_SCHEMA_VERSION,
            "label_set": f"{LABEL_SET_ID}@{OBJECT_REVISION}",
            "packets": list(PACKET_IDS),
            "seed": seed,
            "items": sorted(blinded_ids),
        }
    )
    return f"pkt-{digest.removeprefix('sha256:')[:12]}"


def _draw_orders(
    cases: Sequence[RegisteredCase], rng: random.Random
) -> dict[str, dict[str, PairOrder | None]]:
    """Split each pairwise item's two orders across the two packets.

    Which packet gets ``ab`` is drawn per item, so "the second packet" is
    not a synonym for "the swapped one" and an annotator comparing notes
    with a colleague learns nothing from their slot.
    """
    orders: dict[str, dict[str, PairOrder | None]] = {}
    first, second = PACKET_IDS
    for case in cases:
        if case.label_type is LabelType.PAIRWISE_PREFERENCE:
            first_sees_ab = rng.random() < 0.5
            orders[case.blinded_item_id] = {
                first: PairOrder.AB if first_sees_ab else PairOrder.BA,
                second: PairOrder.BA if first_sees_ab else PairOrder.AB,
            }
        else:
            orders[case.blinded_item_id] = {first: None, second: None}
    return orders


def build_packet_set(
    *, seed: int | None = None, root: Path = CALIBRATION_REGISTRY_ROOT
) -> PacketSet:
    """Render the two blinded packets and their manifest.

    Deterministic: the same registry and the same seed produce the same
    packet set, byte for byte, including its ``packet_set_id``.

    Args:
        seed: Presentation seed. Defaults to the registered blinding
            plan's seed.
        root: Registry root.

    Returns:
        The packet set.

    Raises:
        ValueError: The seed is negative, or the registry cannot be
            resolved into packet material.
    """
    cases = load_registered_cases(root)
    if not cases:
        raise ValueError("the label set resolved to no cases")
    resolved_seed = registered_blinding_plan(root).seed if seed is None else seed
    if resolved_seed < 0:
        raise ValueError("a presentation seed is a non-negative integer")
    rng = random.Random(resolved_seed)
    orders = _draw_orders(cases, rng)

    packets: list[LabelPacket] = []
    keys: list[PacketKey] = []
    for packet_id in PACKET_IDS:
        shown = list(cases)
        rng.shuffle(shown)
        packets.append(
            LabelPacket(
                packet_id=packet_id,
                instructions=INSTRUCTIONS,
                items=tuple(
                    _packet_item(case, order=orders[case.blinded_item_id][packet_id])
                    for case in shown
                ),
            )
        )
        keys.append(
            PacketKey(
                packet_id=packet_id,
                entries=tuple(
                    ManifestEntry(
                        position=position,
                        blinded_item_id=case.blinded_item_id,
                        case_id=case.case_id,
                        label_type=case.label_type,
                        slice_tags=case.slice_tags,
                        presentation_order=_order_value(
                            orders[case.blinded_item_id][packet_id]
                        ),
                    )
                    for position, case in enumerate(shown, start=1)
                ),
            )
        )

    packet_set_id = _packet_set_id(resolved_seed, [case.blinded_item_id for case in cases])
    return PacketSet(
        packet_set_id=packet_set_id,
        seed=resolved_seed,
        packets=tuple(packets),
        manifest=PacketManifest(
            packet_set_id=packet_set_id,
            seed=resolved_seed,
            label_set_ref=f"{LABEL_SET_ID}@{OBJECT_REVISION}",
            blinding_plan_ref=f"{BLINDING_PLAN_ID}@{OBJECT_REVISION}",
            handling=MANIFEST_HANDLING,
            packets=tuple(keys),
        ),
    )


def _readme(packet_set: PacketSet) -> str:
    """The steward's hand-over instructions, written beside the packets.

    Chiefly the one rule the whole design rests on: the two annotator
    directories go out and ``manifest.json`` stays, because the manifest
    is the blinding key and sending it un-blinds the set.
    """
    return (
        f"# Calibration packet set `{packet_set.packet_set_id}`\n\n"
        f"Seed `{packet_set.seed}`; reference set "
        f"`{packet_set.manifest.label_set_ref}`.\n\n"
        "## What to hand over\n\n"
        "Send one annotator the `expert-a/` directory and the other `expert-b/`.\n"
        "Send nothing else. `manifest.json` is the blinding key and stays with the\n"
        "steward: it names every item's registry case, its slices, and the\n"
        "presentation order that packet used.\n\n"
        "## What the annotator does\n\n"
        "1. Replace `annotator_id: null` with the pseudonym you assign (`ann-...`).\n"
        "2. Fill `decision`, `confidence` and `rationale` on every item.\n"
        "3. Return the file. A partially filled packet is refused, not scored.\n\n"
        "## What you do with it\n\n"
        "```\n"
        "python -m src.calibration ingest <returned-packet.json> \\\n"
        "  --manifest manifest.json --output report.md\n"
        "```\n\n"
        "Nothing in this directory is committed: `outputs/` is ignored, and the\n"
        "retention rule for human labels is still an open owner decision\n"
        "(docs/agent-engineering/14-judge-calibration-protocol.md §12, §14).\n"
    )


def write_packet_set(
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    *,
    seed: int | None = None,
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> tuple[Path, ...]:
    """Write one packet set under ``<output_root>/<packet_set_id>/``.

    The layout is the separation this work order asks for::

        <packet_set_id>/expert-a/packet.json   <- handed over
        <packet_set_id>/expert-b/packet.json   <- handed over
        <packet_set_id>/manifest.json          <- blinding key, kept
        <packet_set_id>/README.md

    Args:
        output_root: Directory the set is created in.
        seed: Presentation seed; the registered plan's by default.
        root: Registry root.

    Returns:
        Every path written, packets first.
    """
    packet_set = build_packet_set(seed=seed, root=root)
    base = output_root / packet_set.packet_set_id
    written: list[Path] = []
    for packet in packet_set.packets:
        directory = base / packet.packet_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "packet.json"
        path.write_text(canonical_json(packet) + "\n", encoding="utf-8")
        written.append(path)
    manifest_path = base / "manifest.json"
    manifest_path.write_text(canonical_json(packet_set.manifest) + "\n", encoding="utf-8")
    written.append(manifest_path)
    readme_path = base / "README.md"
    readme_path.write_text(_readme(packet_set), encoding="utf-8")
    written.append(readme_path)
    return tuple(written)


def _normalise_pairwise(decision: str, order: Literal["ab", "ba"] | None) -> str:
    """Map a shown-order preference back onto registry candidate identity."""
    if order != "ba" or decision not in {"first", "second"}:
        return decision
    return "second" if decision == "first" else "first"


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _blank_rows(rows: list[Any], *, nested: bool) -> tuple[str, ...]:
    """Name the rows that are not fully answered, in either file shape.

    All three fields are required together: a decision with no rationale
    is not a labelled item, because 03 §7.8 sends disagreements to an
    adjudicator who cannot review a verdict that gives no reason.
    """
    fields = ("decision", "confidence", "rationale")
    blank: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            blank.append(f"#{index}")
            continue
        identifier = str(row.get("blinded_item_id") or f"#{index}")
        source: object = row.get("response") if nested else row
        if not isinstance(source, dict) or any(
            not _filled(source.get(field)) for field in fields
        ):
            blank.append(identifier)
    return tuple(blank)


def _unlabelled_ids(raw: dict[str, Any]) -> tuple[str, ...]:
    """Return the ids of items a file left blank.

    Pydantic would refuse these too, but as a validation dump over a
    thirty-item file. A partially filled packet is the single most likely
    thing to come back from an offline labeler, so it gets a sentence that
    names the items instead.
    """
    items = raw.get("items")
    if isinstance(items, list):
        return _blank_rows(items, nested=True)
    labels = raw.get("labels")
    if isinstance(labels, list):
        return _blank_rows(labels, nested=False)
    return ()


def _load_submission(
    raw_text: str, packet_set: PacketSet
) -> tuple[str, str, dict[str, tuple[LabelType, str, Confidence]]]:
    """Parse either accepted file shape into one decision map.

    Args:
        raw_text: The label file's text.
        packet_set: The set re-rendered from the manifest's seed.

    Returns:
        ``(packet_id, annotator_id, {item_id: (label_type, decision, confidence)})``.

    Raises:
        ValueError: The file is malformed, partially labelled, names a
            packet this set does not contain, or (for a returned packet)
            changed the material it was sent with.
    """
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"label file is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("label file must be a JSON object")
    blank = _unlabelled_ids(raw)
    if blank:
        raise ValueError(
            f"label file is only partially labelled; {len(blank)} unlabelled "
            f"item(s): {sorted(blank)}"
        )
    if "items" in raw:
        packet = CompletedLabelPacket.model_validate_json(raw_text)
        reference = {
            item.blinded_item_id: item for item in packet_set.packet(packet.packet_id).items
        }
        for item in packet.items:
            sent = reference.get(item.blinded_item_id)
            if sent is None:
                continue
            if (
                item.label_type is not sent.label_type
                or item.material != sent.material
                or item.allowed_decisions != sent.allowed_decisions
            ):
                raise ValueError(
                    f"{item.blinded_item_id}: the returned packet changed registered "
                    "material; re-render the packet set and re-label"
                )
        return (
            packet.packet_id,
            packet.annotator_id,
            {
                item.blinded_item_id: (
                    item.label_type,
                    item.response.decision,
                    item.response.confidence,
                )
                for item in packet.items
            },
        )
    submitted = SubmittedLabelFile.model_validate_json(raw_text)
    return (
        submitted.packet_id,
        submitted.annotator_id,
        {
            label.blinded_item_id: (label.label_type, label.decision, label.confidence)
            for label in submitted.labels
        },
    )


def _summary(numerator: int, denominator: int) -> RateSummary:
    """Wrap one count pair with its rate and Wilson interval."""
    if denominator == 0:
        return RateSummary(
            numerator=numerator,
            denominator=denominator,
            rate=None,
            interval_low=None,
            interval_high=None,
        )
    bounds = wilson_interval(numerator, denominator)
    return RateSummary(
        numerator=numerator,
        denominator=denominator,
        rate=numerator / denominator,
        interval_low=bounds.low,
        interval_high=bounds.high,
    )


def _slice_report(slice_id: str, rows: Sequence[ResolvedLabel]) -> SliceLabelReport:
    """Compute one slice's report from already-un-blinded labels."""
    binary_rows = [row for row in rows if row.label_type is not LabelType.PAIRWISE_PREFERENCE]
    pairwise_rows = [row for row in rows if row.label_type is LabelType.PAIRWISE_PREFERENCE]
    triples = [
        (
            row.blinded_item_id,
            binary_outcome(row.expected_decision),
            binary_outcome(row.decision),
        )
        for row in binary_rows
    ]
    report = agreement(triples, policy=REPORT_ABSTENTION_POLICY)
    errors = error_rates(triples, policy=REPORT_ABSTENTION_POLICY)
    counts = report.counts
    decided = counts.decided
    exact_denominator = sum(1 for row in binary_rows if row.decision not in NON_DECISIONS)
    exact_numerator = sum(
        1
        for row in binary_rows
        if row.decision not in NON_DECISIONS and row.decision == row.expected_decision
    )
    pairwise_decided = sum(1 for row in pairwise_rows if row.decision not in NON_DECISIONS)
    pairwise_hits = sum(
        1
        for row in pairwise_rows
        if row.decision not in NON_DECISIONS and row.decision == row.expected_decision
    )
    return SliceLabelReport(
        slice_id=slice_id,
        items=len(rows),
        binary_items=len(binary_rows),
        pairwise_items=len(pairwise_rows),
        raw_agreement=_summary(counts.true_pass + counts.true_fail, decided),
        phi=report.phi,
        annotator_positive=_summary(counts.true_pass + counts.false_pass, decided),
        reference_positive=_summary(counts.true_pass + counts.false_fail, decided),
        exact_decision_match=_summary(exact_numerator, exact_denominator),
        false_pass=_summary(errors.false_pass.numerator, errors.false_pass.denominator),
        false_fail=_summary(errors.false_fail.numerator, errors.false_fail.denominator),
        abstention=_summary(errors.abstention.numerator, errors.abstention.denominator),
        unresolved_reference=_summary(
            errors.unresolved_reference.numerator,
            errors.unresolved_reference.denominator,
        ),
        pairwise_agreement=_summary(pairwise_hits, pairwise_decided),
        pairwise_non_decision=_summary(
            len(pairwise_rows) - pairwise_decided, len(pairwise_rows)
        ),
    )


def ingest_labels(
    label_path: Path,
    manifest_path: Path,
    *,
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> LabelIngestReport:
    """Un-blind a completed label file and report agreement per slice.

    The manifest is the only thing that can un-blind the file, and it
    carries the seed the set was drawn under — which is enough to
    re-render the packets and prove the file describes *this* set rather
    than a similar-looking one.

    Args:
        label_path: A returned packet, or a compact label file.
        manifest_path: The packet set's manifest.
        root: Registry root.

    Returns:
        The agreement report.

    Raises:
        ValueError: The manifest is not a manifest or no longer matches
            the registry; the label file is malformed, partially
            labelled, or does not cover exactly the packet's items; a
            label contradicts the registered label type; or a returned
            packet changed its material.
    """
    manifest_text = manifest_path.read_text(encoding="utf-8")
    try:
        manifest = PacketManifest.model_validate_json(manifest_text)
    except ValueError as exc:
        raise ValueError(f"{manifest_path} is not a packet manifest: {exc}") from exc
    packet_set = build_packet_set(seed=manifest.seed, root=root)
    if packet_set.packet_set_id != manifest.packet_set_id:
        raise ValueError(
            f"manifest {manifest.packet_set_id} no longer describes this registry "
            f"(it now renders {packet_set.packet_set_id}); the label set moved under it"
        )

    packet_id, annotator_id, decisions = _load_submission(
        label_path.read_text(encoding="utf-8"), packet_set
    )
    key = manifest.key_for(packet_id)
    entries = {entry.blinded_item_id: entry for entry in key.entries}
    missing = sorted(set(entries) - set(decisions))
    unknown = sorted(set(decisions) - set(entries))
    if missing or unknown:
        raise ValueError(
            f"label coverage mismatch against manifest {manifest.packet_set_id}/"
            f"{packet_id}; missing={missing}, unknown={unknown}"
        )

    cases = {case.blinded_item_id: case for case in load_registered_cases(root)}
    rows: list[ResolvedLabel] = []
    for item_id, entry in sorted(entries.items()):
        label_type, decision, _confidence = decisions[item_id]
        if label_type is not entry.label_type:
            raise ValueError(
                f"{item_id}: submitted label type {label_type.value!r} does not match "
                f"the registered {entry.label_type.value!r}"
            )
        case = cases[item_id]
        if case.case_id != entry.case_id:
            raise ValueError(
                f"{item_id}: manifest names case {entry.case_id!r} but the registry "
                f"resolves {case.case_id!r}"
            )
        if decision not in decision_vocabulary(label_type):
            raise ValueError(f"{item_id}: {decision!r} is not valid for {label_type.value}")
        rows.append(
            ResolvedLabel(
                blinded_item_id=item_id,
                case_id=entry.case_id,
                label_type=label_type,
                slice_tags=entry.slice_tags,
                expected_decision=case.expected_decision,
                presentation_order=entry.presentation_order,
                shown_decision=decision,
                decision=_normalise_pairwise(decision, entry.presentation_order),
            )
        )

    slice_ids = sorted({tag for row in rows for tag in row.slice_tags})
    return LabelIngestReport(
        packet_set_id=manifest.packet_set_id,
        packet_id=packet_id,
        annotator_id=annotator_id,
        seed=manifest.seed,
        source_label_set=manifest.label_set_ref,
        abstention_policy=REPORT_ABSTENTION_POLICY.value,
        labels_ingested=len(rows),
        overall=_slice_report("all", rows),
        slices=tuple(
            _slice_report(slice_id, [row for row in rows if slice_id in row.slice_tags])
            for slice_id in slice_ids
        ),
    )


def _format_rate(rate: RateSummary) -> str:
    if rate.rate is None or rate.interval_low is None or rate.interval_high is None:
        return f"{rate.numerator}/{rate.denominator} n/a"
    return (
        f"{rate.numerator}/{rate.denominator} {rate.rate:.1%} "
        f"[{rate.interval_low:.1%}–{rate.interval_high:.1%}]"
    )


def _format_phi(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.3f}"


def render_report(report: LabelIngestReport) -> str:
    """Render the ingest report as markdown, in 14 §9.1's reporting form.

    Raw agreement never appears on a line without φ and both positive
    rates, every rate carries its numerator, denominator and Wilson
    interval, and the abstention policy is stated rather than implied.

    Args:
        report: The ingest report.

    Returns:
        The markdown document.
    """
    lines = [
        "# Offline calibration label report",
        "",
        f"Packet set: `{report.packet_set_id}` (seed `{report.seed}`)  ",
        f"Packet: `{report.packet_id}`  ",
        f"Annotator: `{report.annotator_id}`  ",
        f"Reference set: `{report.source_label_set}`  ",
        f"Abstention policy: `{report.abstention_policy}`  ",
        f"Labels ingested: {report.labels_ingested}",
        "",
        "## Binary axis (claim support, citation correctness, rubric coverage)",
        "",
        "| Slice | Items | Raw agreement | φ/MCC | Annotator pass rate "
        "| Reference pass rate | False pass | False fail | Abstention "
        "| Unresolved reference |",
        "|---|---:|---|---:|---|---|---|---|---|---|",
    ]
    for entry in (report.overall, *report.slices):
        lines.append(
            f"| {entry.slice_id} | {entry.binary_items} "
            f"| {_format_rate(entry.raw_agreement)} | {_format_phi(entry.phi)} "
            f"| {_format_rate(entry.annotator_positive)} "
            f"| {_format_rate(entry.reference_positive)} "
            f"| {_format_rate(entry.false_pass)} | {_format_rate(entry.false_fail)} "
            f"| {_format_rate(entry.abstention)} "
            f"| {_format_rate(entry.unresolved_reference)} |"
        )
    lines.extend(
        [
            "",
            "## Categorical and pairwise",
            "",
            "| Slice | Exact decision match | Pairwise items "
            "| Pairwise agreement | Pairwise non-decisions |",
            "|---|---|---:|---|---|",
        ]
    )
    for entry in (report.overall, *report.slices):
        lines.append(
            f"| {entry.slice_id} | {_format_rate(entry.exact_decision_match)} "
            f"| {entry.pairwise_items} | {_format_rate(entry.pairwise_agreement)} "
            f"| {_format_rate(entry.pairwise_non_decision)} |"
        )
    lines.extend(
        [
            "",
            "Denominators differ on purpose (14 §9.3). False pass is over the items "
            "the reference called fail; false fail is over the items it called pass; "
            "abstention is over items with a resolved reference decision; unresolved "
            "reference is over every item seen. Raw agreement is over items both "
            "sides decided and is published only beside φ and both positive rates, "
            "because κ = q·φ is uninterpretable without them. Every interval is a "
            "95% Wilson interval from `src/eval/stats.py`.",
            "",
            "Pairwise decisions have no pass/fail projection and are reported "
            "separately, normalized back to registry candidate identity using the "
            "manifest's presentation order. Position bias is a judge measurement and "
            "is **not** computed here: 14 §7.3 shows each annotator one order only, "
            "so a single packet cannot separate a preference from a position.",
            "",
            "This report describes one annotator against synthetic reference "
            "decisions. It is not a calibration verdict: 14 §8.4 and §12 keep "
            "promotion claims behind the representative-suite and owner gates.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "INSTRUCTIONS",
    "MANIFEST_HANDLING",
    "PACKET_IDS",
    "PACKET_SCHEMA_VERSION",
    "REPORT_ABSTENTION_POLICY",
    "CompletedLabelPacket",
    "LabelIngestReport",
    "LabelPacket",
    "ManifestEntry",
    "PacketItem",
    "PacketKey",
    "PacketManifest",
    "PacketSet",
    "RateSummary",
    "RegisteredCase",
    "ResolvedLabel",
    "SliceLabelReport",
    "SubmittedLabel",
    "SubmittedLabelFile",
    "build_packet_set",
    "ingest_labels",
    "load_registered_cases",
    "registered_blinding_plan",
    "render_report",
    "write_packet_set",
]
