"""Offline expert-label packets and deterministic calibration summaries.

Packets are rendered from the sealed calibration registry, but deliberately
omit the real case id, reference decision, authored rationale, and slice tags.
The report path resolves those evaluator-only fields only after a completed
label file is ingested.  Nothing in this module calls a model or the network.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints, model_validator

from src.calibration.labels import (
    NON_DECISIONS,
    Confidence,
    LabelType,
    binary_outcome,
    decision_vocabulary,
)
from src.calibration.metrics import AbstentionPolicy, agreement, error_rates
from src.calibration.suite import (
    CALIBRATION_REGISTRY_ROOT,
    LABEL_SET_ID,
    OBJECT_REVISION,
    CalibrationContentEnvelope,
    CalibrationItemContent,
    ExpectedLabelValue,
    locator,
)
from src.contracts.kernel import StrictContractModel, canonical_json
from src.contracts.registry import LabelSet, RegistryEnvelope, TaskCase

PACKET_SCHEMA_VERSION: Final[str] = "1.0.0"
PACKET_IDS: Final[tuple[str, str]] = ("expert-a", "expert-b")


class PacketMaterial(StrictContractModel):
    report_excerpt: Annotated[str, StringConstraints(min_length=1, max_length=4000)]
    cited_source: str | None = None
    source_excerpt: str | None = None
    rubric_item: str | None = None
    second_excerpt: str | None = None


class BlankResponse(StrictContractModel):
    decision: None = None
    confidence: None = None
    rationale: None = None


class PacketItem(StrictContractModel):
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    presentation_order: Literal["ab", "ba"] | None = None
    material: PacketMaterial
    allowed_decisions: tuple[str, ...]
    response: BlankResponse = BlankResponse()

    @model_validator(mode="after")
    def shape_matches_label_type(self) -> PacketItem:
        pairwise = self.label_type is LabelType.PAIRWISE_PREFERENCE
        if pairwise != (self.presentation_order is not None):
            raise ValueError("presentation_order is required only for pairwise items")
        if pairwise != (self.material.second_excerpt is not None):
            raise ValueError("second_excerpt is required only for pairwise items")
        if self.allowed_decisions != decision_vocabulary(self.label_type):
            raise ValueError("allowed_decisions do not match the registered vocabulary")
        return self


class LabelPacket(StrictContractModel):
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


class CompletedResponse(StrictContractModel):
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: Confidence
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class CompletedPacketItem(StrictContractModel):
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    presentation_order: Literal["ab", "ba"] | None = None
    material: PacketMaterial
    allowed_decisions: tuple[str, ...]
    response: CompletedResponse

    @model_validator(mode="after")
    def completed_response_matches_the_item(self) -> CompletedPacketItem:
        pairwise = self.label_type is LabelType.PAIRWISE_PREFERENCE
        if pairwise != (self.presentation_order is not None):
            raise ValueError("presentation_order is required only for pairwise items")
        if self.allowed_decisions != decision_vocabulary(self.label_type):
            raise ValueError("allowed_decisions do not match the registered vocabulary")
        if self.response.decision not in self.allowed_decisions:
            raise ValueError("completed decision is outside the allowed vocabulary")
        return self


class CompletedLabelPacket(StrictContractModel):
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
    blinded_item_id: Annotated[str, StringConstraints(pattern=r"^itm-[0-9a-f]{12}$")]
    label_type: LabelType
    presentation_order: Literal["ab", "ba"] | None = None
    decision: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    confidence: Confidence
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=2000)]

    @model_validator(mode="after")
    def decision_and_order_are_valid(self) -> SubmittedLabel:
        if self.decision not in decision_vocabulary(self.label_type):
            raise ValueError(
                f"{self.decision!r} is not valid for {self.label_type.value}"
            )
        pairwise = self.label_type is LabelType.PAIRWISE_PREFERENCE
        if pairwise != (self.presentation_order is not None):
            raise ValueError("presentation_order is required only for pairwise labels")
        return self


class SubmittedLabelFile(StrictContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: Annotated[str, StringConstraints(pattern=r"^expert-[ab]$|^synthetic-proof$")]
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
    case_id: str
    blinded_item_id: str
    label_type: LabelType
    slice_tags: tuple[str, ...]
    expected_decision: str
    material: CalibrationItemContent


class RateSummary(StrictContractModel):
    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=0)]
    rate: float | None


class SliceLabelReport(StrictContractModel):
    slice_id: str
    items: Annotated[int, Field(ge=0)]
    decided: Annotated[int, Field(ge=0)]
    exact_agreement: RateSummary
    phi: float | None
    false_pass: RateSummary
    false_fail: RateSummary
    abstention: RateSummary


class LabelIngestReport(StrictContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: str
    annotator_id: str
    source_label_set: str
    overall: SliceLabelReport
    slices: tuple[SliceLabelReport, ...]


def _read_registry(path: Path) -> RegistryEnvelope:
    return RegistryEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def _read_content(path: Path) -> CalibrationContentEnvelope:
    return CalibrationContentEnvelope.model_validate_json(path.read_text(encoding="utf-8"))


def load_registered_cases(
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> tuple[RegisteredCase, ...]:
    """Resolve packet material and answer keys through sealed registry refs."""
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


def _packet_item(case: RegisteredCase, *, packet_id: str) -> PacketItem:
    pairwise = case.label_type is LabelType.PAIRWISE_PREFERENCE
    order: Literal["ab", "ba"] | None = None
    report = case.material.report_excerpt
    second = case.material.second_excerpt
    if pairwise:
        order = "ab" if packet_id == "expert-a" else "ba"
        if order == "ba":
            assert second is not None
            report, second = second, report
    return PacketItem(
        blinded_item_id=case.blinded_item_id,
        label_type=case.label_type,
        presentation_order=order,
        material=PacketMaterial(
            report_excerpt=report,
            cited_source=case.material.cited_source,
            source_excerpt=case.material.source_excerpt,
            rubric_item=case.material.rubric_item,
            second_excerpt=second,
        ),
        allowed_decisions=decision_vocabulary(case.label_type),
    )


def build_packets(
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> tuple[LabelPacket, LabelPacket]:
    cases = load_registered_cases(root)
    instructions = (
        "Work independently. Do not seek an answer key or another annotator's labels.",
        "Choose exactly one allowed decision, one confidence bucket, and write a rationale.",
        "For pairwise items, first and second refer only to the displayed order.",
        "Do not include your name or email; the campaign steward assigns a pseudonym.",
    )
    return tuple(
        LabelPacket(
            packet_id=packet_id,
            instructions=instructions,
            items=tuple(_packet_item(case, packet_id=packet_id) for case in cases),
        )
        for packet_id in PACKET_IDS
    )  # type: ignore[return-value]


def build_synthetic_labels(
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> SubmittedLabelFile:
    """Create a deterministic dry-run file; these are not expert labels."""
    labels: list[SubmittedLabel] = []
    positive_changed = negative_changed = abstained = False
    for case in load_registered_cases(root):
        decision = case.expected_decision
        order: Literal["ab", "ba"] | None = None
        outcome = binary_outcome(decision)
        if case.label_type is LabelType.PAIRWISE_PREFERENCE:
            order = "ab"
        elif outcome is False and not negative_changed:
            decision = decision_vocabulary(case.label_type)[0]
            negative_changed = True
        elif outcome is True and not positive_changed:
            vocabulary = decision_vocabulary(case.label_type)
            decision = next(value for value in vocabulary if binary_outcome(value) is False)
            positive_changed = True
        elif not abstained:
            vocabulary = decision_vocabulary(case.label_type)
            candidates = [value for value in vocabulary if value in NON_DECISIONS]
            if candidates:
                decision = candidates[-1]
                abstained = True
        labels.append(
            SubmittedLabel(
                blinded_item_id=case.blinded_item_id,
                label_type=case.label_type,
                presentation_order=order,
                decision=decision,
                confidence=Confidence.HIGH,
                rationale="Synthetic dry-run decision; not an expert label.",
            )
        )
    if not (positive_changed and negative_changed and abstained):
        raise ValueError("registry lacks the decisions needed for the synthetic dry run")
    return SubmittedLabelFile(
        packet_id="synthetic-proof",
        annotator_id="ann-synthetic",
        labels=tuple(labels),
    )


def write_packets(output_root: Path, root: Path = CALIBRATION_REGISTRY_ROOT) -> tuple[Path, ...]:
    output_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for packet in build_packets(root):
        path = output_root / f"{packet.packet_id}.json"
        path.write_text(canonical_json(packet) + "\n", encoding="utf-8")
        written.append(path)
    synthetic = output_root / "synthetic-labels.json"
    synthetic.write_text(canonical_json(build_synthetic_labels(root)) + "\n", encoding="utf-8")
    written.append(synthetic)
    readme = output_root / "README.md"
    readme.write_text(
        "# Offline calibration packets\n\n"
        "The two expert packets contain the same blinded items in independent "
        "presentation orders. The steward assigns a pseudonymous annotator_id, then "
        "the expert fills every response in their packet; the completed packet can be "
        "passed directly to `python -m src.calibration report`. Never add names or "
        "emails. "
        "`synthetic-labels.json` exists only to exercise ingestion and is not an "
        "expert label set.\n",
        encoding="utf-8",
    )
    written.append(readme)
    return tuple(written)


def _normalise_pairwise(decision: str, order: str | None) -> str:
    if order != "ba" or decision not in {"first", "second"}:
        return decision
    return "second" if decision == "first" else "first"


def _rate(numerator: int, denominator: int) -> RateSummary:
    return RateSummary(
        numerator=numerator,
        denominator=denominator,
        rate=None if denominator == 0 else numerator / denominator,
    )


def _slice_report(
    slice_id: str,
    rows: Sequence[tuple[RegisteredCase, SubmittedLabel]],
) -> SliceLabelReport:
    exact_numerator = 0
    exact_denominator = 0
    abstentions = 0
    triples: list[tuple[str, bool | None, bool | None]] = []
    for case, submitted in rows:
        observed = _normalise_pairwise(submitted.decision, submitted.presentation_order)
        if submitted.decision in NON_DECISIONS:
            abstentions += 1
        else:
            exact_denominator += 1
            exact_numerator += observed == case.expected_decision
        if case.label_type is not LabelType.PAIRWISE_PREFERENCE:
            triples.append(
                (
                    case.blinded_item_id,
                    binary_outcome(case.expected_decision),
                    binary_outcome(observed),
                )
            )
    errors = error_rates(triples, policy=AbstentionPolicy.EXCLUDED)
    agreement_report = agreement(triples, policy=AbstentionPolicy.EXCLUDED)
    return SliceLabelReport(
        slice_id=slice_id,
        items=len(rows),
        decided=exact_denominator,
        exact_agreement=_rate(exact_numerator, exact_denominator),
        phi=agreement_report.phi,
        false_pass=_rate(errors.false_pass.numerator, errors.false_pass.denominator),
        false_fail=_rate(errors.false_fail.numerator, errors.false_fail.denominator),
        abstention=_rate(abstentions, len(rows)),
    )


def ingest_labels(
    label_path: Path,
    root: Path = CALIBRATION_REGISTRY_ROOT,
) -> LabelIngestReport:
    raw_text = label_path.read_text(encoding="utf-8")
    raw = json.loads(raw_text)
    if not isinstance(raw, dict):
        raise ValueError("label file must be a JSON object")
    if "items" in raw:
        packet = CompletedLabelPacket.model_validate_json(raw_text)
        expected_packet = next(
            candidate for candidate in build_packets(root) if candidate.packet_id == packet.packet_id
        )
        expected_by_id = {item.blinded_item_id: item for item in expected_packet.items}
        for item in packet.items:
            expected = expected_by_id.get(item.blinded_item_id)
            if expected is None:
                continue
            if (
                item.label_type is not expected.label_type
                or item.presentation_order != expected.presentation_order
                or item.material != expected.material
                or item.allowed_decisions != expected.allowed_decisions
            ):
                raise ValueError(
                    f"{item.blinded_item_id}: completed packet changed registered material"
                )
        submitted = SubmittedLabelFile(
            packet_id=packet.packet_id,
            annotator_id=packet.annotator_id,
            labels=tuple(
                SubmittedLabel(
                    blinded_item_id=item.blinded_item_id,
                    label_type=item.label_type,
                    presentation_order=item.presentation_order,
                    decision=item.response.decision,
                    confidence=item.response.confidence,
                    rationale=item.response.rationale,
                )
                for item in packet.items
            ),
        )
    else:
        submitted = SubmittedLabelFile.model_validate_json(raw_text)
    cases = load_registered_cases(root)
    by_id = {case.blinded_item_id: case for case in cases}
    submitted_by_id = {label.blinded_item_id: label for label in submitted.labels}
    missing = sorted(set(by_id) - set(submitted_by_id))
    unknown = sorted(set(submitted_by_id) - set(by_id))
    if missing or unknown:
        raise ValueError(f"label coverage mismatch; missing={missing}, unknown={unknown}")
    rows: list[tuple[RegisteredCase, SubmittedLabel]] = []
    for item_id, case in sorted(by_id.items()):
        label = submitted_by_id[item_id]
        if label.label_type is not case.label_type:
            raise ValueError(f"{item_id}: submitted label type does not match registry")
        rows.append((case, label))
    slice_ids = sorted({tag for case in cases for tag in case.slice_tags})
    slices = tuple(
        _slice_report(
            slice_id,
            [(case, label) for case, label in rows if slice_id in case.slice_tags],
        )
        for slice_id in slice_ids
    )
    return LabelIngestReport(
        packet_id=submitted.packet_id,
        annotator_id=submitted.annotator_id,
        source_label_set=f"{LABEL_SET_ID}@{OBJECT_REVISION}",
        overall=_slice_report("all", rows),
        slices=slices,
    )


def _format_rate(rate: RateSummary) -> str:
    value = "n/a" if rate.rate is None else f"{rate.rate:.1%}"
    return f"{rate.numerator}/{rate.denominator} ({value})"


def render_report(report: LabelIngestReport) -> str:
    lines = [
        "# Offline calibration label report",
        "",
        f"Packet: `{report.packet_id}`  ",
        f"Annotator: `{report.annotator_id}`  ",
        f"Reference: `{report.source_label_set}`",
        "",
        "| Slice | Items | Exact agreement | Phi/MCC | False pass | False fail | Abstention |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for entry in (report.overall, *report.slices):
        phi = "n/a" if entry.phi is None else f"{entry.phi:+.3f}"
        lines.append(
            f"| {entry.slice_id} | {entry.items} | {_format_rate(entry.exact_agreement)} "
            f"| {phi} | {_format_rate(entry.false_pass)} | {_format_rate(entry.false_fail)} "
            f"| {_format_rate(entry.abstention)} |"
        )
    lines.extend(
        [
            "",
            "False-pass denominators are registered reference-fail items; false-fail "
            "denominators are registered reference-pass items. Abstention denominators "
            "include every item in the row. Pairwise decisions contribute to exact "
            "agreement and abstention after presentation-order normalization, and have "
            "no pass/fail projection.",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "LabelIngestReport",
    "LabelPacket",
    "SubmittedLabelFile",
    "build_packets",
    "build_synthetic_labels",
    "ingest_labels",
    "load_registered_cases",
    "render_report",
    "write_packets",
]
