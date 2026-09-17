"""Offline calibration packets and completed-label ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.calibration.__main__ import main
from src.calibration.labels import LabelType
from src.calibration.packets import (
    SubmittedLabelFile,
    build_packets,
    build_synthetic_labels,
    ingest_labels,
    load_registered_cases,
    render_report,
    write_packets,
)

pytestmark = pytest.mark.unit


class TestTheOfflinePackets:
    def test_the_two_packets_are_complete_blinded_and_answer_free(self) -> None:
        cases = load_registered_cases()
        packets = build_packets()

        assert len(cases) == 30
        assert [packet.packet_id for packet in packets] == ["expert-a", "expert-b"]
        expected_ids = {case.blinded_item_id for case in cases}
        real_ids = {case.case_id for case in cases}
        for packet in packets:
            assert {item.blinded_item_id for item in packet.items} == expected_ids
            rendered = packet.model_dump_json()
            assert not real_ids.intersection(rendered.split('"'))
            assert "expected_decision" not in rendered
            assert "slice_tags" not in rendered
            assert "rationale_id" not in rendered
            assert all(item.response.decision is None for item in packet.items)

    def test_pairwise_material_is_swapped_between_independent_packets(self) -> None:
        first, second = build_packets()
        by_first = {item.blinded_item_id: item for item in first.items}
        by_second = {item.blinded_item_id: item for item in second.items}
        pair_ids = {
            item.blinded_item_id
            for item in first.items
            if item.label_type is LabelType.PAIRWISE_PREFERENCE
        }

        assert len(pair_ids) == 6
        for item_id in pair_ids:
            a = by_first[item_id]
            b = by_second[item_id]
            assert (a.presentation_order, b.presentation_order) == ("ab", "ba")
            assert a.material.report_excerpt == b.material.second_excerpt
            assert a.material.second_excerpt == b.material.report_excerpt

    def test_writing_packets_produces_only_operator_outputs(self, tmp_path: Path) -> None:
        paths = write_packets(tmp_path)

        assert {path.name for path in paths} == {
            "README.md",
            "expert-a.json",
            "expert-b.json",
            "synthetic-labels.json",
        }
        assert all(path.parent == tmp_path for path in paths)
        SubmittedLabelFile.model_validate_json(
            (tmp_path / "synthetic-labels.json").read_text(encoding="utf-8")
        )


class TestCompletedLabelIngestion:
    def _write(self, tmp_path: Path, payload: Any) -> Path:
        path = tmp_path / "labels.json"
        if hasattr(payload, "model_dump_json"):
            path.write_text(payload.model_dump_json(), encoding="utf-8")
        else:
            path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_the_synthetic_file_exercises_every_required_measurement(
        self, tmp_path: Path
    ) -> None:
        report = ingest_labels(self._write(tmp_path, build_synthetic_labels()))

        assert report.overall.items == 30
        assert report.overall.exact_agreement.numerator == 27
        assert report.overall.exact_agreement.denominator == 29
        assert report.overall.false_pass.numerator == 1
        assert report.overall.false_pass.denominator == 15
        assert report.overall.false_fail.numerator == 1
        assert report.overall.false_fail.denominator == 8
        assert report.overall.abstention.numerator == 1
        assert report.overall.abstention.denominator == 30
        assert report.overall.phi == pytest.approx(0.8083333333)
        assert len(report.slices) == 15
        assert all(slice_report.items > 0 for slice_report in report.slices)

    def test_the_markdown_publishes_each_rate_with_its_denominator(
        self, tmp_path: Path
    ) -> None:
        report = ingest_labels(self._write(tmp_path, build_synthetic_labels()))
        rendered = render_report(report)

        assert "| all | 30 | 27/29 (93.1%) | +0.808" in rendered
        assert "| ambiguous-comparative |" in rendered
        assert "False-pass denominators are registered reference-fail items" in rendered
        assert "Pairwise decisions contribute to exact agreement" in rendered

    def test_a_filled_expert_packet_can_be_ingested_directly(self, tmp_path: Path) -> None:
        packet = build_packets()[0].model_dump(mode="json")
        packet["annotator_id"] = "ann-expert1"
        synthetic = {
            label.blinded_item_id: label for label in build_synthetic_labels().labels
        }
        for item in packet["items"]:
            label = synthetic[item["blinded_item_id"]]
            item["response"] = {
                "decision": label.decision,
                "confidence": label.confidence.value,
                "rationale": label.rationale,
            }

        report = ingest_labels(self._write(tmp_path, packet))

        assert report.packet_id == "expert-a"
        assert report.annotator_id == "ann-expert1"
        assert report.overall.items == 30

    def test_ba_pairwise_decisions_are_normalized_to_report_identity(
        self, tmp_path: Path
    ) -> None:
        packet = build_packets()[1].model_dump(mode="json")
        packet["annotator_id"] = "ann-expert2"
        expected = {case.blinded_item_id: case for case in load_registered_cases()}
        for item in packet["items"]:
            decision = expected[item["blinded_item_id"]].expected_decision
            if item["presentation_order"] == "ba" and decision in {"first", "second"}:
                decision = "second" if decision == "first" else "first"
            item["response"] = {
                "decision": decision,
                "confidence": "high",
                "rationale": "Synthetic order-normalization proof.",
            }

        report = ingest_labels(self._write(tmp_path, packet))

        assert report.overall.exact_agreement.numerator == 30
        assert report.overall.exact_agreement.denominator == 30

    def test_missing_unknown_or_duplicate_items_are_refused(self, tmp_path: Path) -> None:
        valid = build_synthetic_labels().model_dump(mode="json")

        missing = dict(valid)
        missing["labels"] = valid["labels"][:-1]
        with pytest.raises(ValueError, match="coverage mismatch"):
            ingest_labels(self._write(tmp_path, missing))

        duplicate = dict(valid)
        duplicate["labels"] = [*valid["labels"], valid["labels"][0]]
        with pytest.raises(ValidationError, match="unique"):
            ingest_labels(self._write(tmp_path, duplicate))

        unknown = dict(valid)
        unknown["labels"] = [dict(item) for item in valid["labels"]]
        unknown["labels"][0]["blinded_item_id"] = "itm-000000000000"
        with pytest.raises(ValueError, match="coverage mismatch"):
            ingest_labels(self._write(tmp_path, unknown))

    def test_a_completed_packet_cannot_change_the_material(self, tmp_path: Path) -> None:
        packet = build_packets()[0].model_dump(mode="json")
        packet["annotator_id"] = "ann-expert1"
        synthetic = {
            label.blinded_item_id: label for label in build_synthetic_labels().labels
        }
        for item in packet["items"]:
            label = synthetic[item["blinded_item_id"]]
            item["response"] = {
                "decision": label.decision,
                "confidence": label.confidence.value,
                "rationale": label.rationale,
            }
        packet["items"][0]["material"]["report_excerpt"] = "tampered"

        with pytest.raises(ValueError, match="changed registered material"):
            ingest_labels(self._write(tmp_path, packet))

    def test_a_submitted_label_cannot_change_the_registered_type(self, tmp_path: Path) -> None:
        payload = build_synthetic_labels().model_dump(mode="json")
        payload["labels"][0]["label_type"] = "citation_correctness"
        payload["labels"][0]["decision"] = "correct"

        with pytest.raises(ValueError, match="label type does not match"):
            ingest_labels(self._write(tmp_path, payload))

    def test_the_cli_writes_packets_and_reports_the_synthetic_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        output = tmp_path / "packets"
        assert main(["packets", "--output", str(output)]) == 0
        capsys.readouterr()

        assert (
            main(
                [
                    "report",
                    "--labels",
                    str(output / "synthetic-labels.json"),
                ]
            )
            == 0
        )
        stdout = capsys.readouterr().out
        assert "# Offline calibration label report" in stdout
        assert "| all | 30 | 27/29 (93.1%)" in stdout

        report_path = output / "report.md"
        assert (
            main(
                [
                    "report",
                    "--labels",
                    str(output / "synthetic-labels.json"),
                    "--output",
                    str(report_path),
                ]
            )
            == 0
        )
        assert report_path.read_text(encoding="utf-8").startswith(
            "# Offline calibration label report"
        )

        malformed = output / "malformed.json"
        malformed.write_text("[]", encoding="utf-8")
        assert main(["report", "--labels", str(malformed)]) == 2
        assert "calibration input refused" in capsys.readouterr().err
