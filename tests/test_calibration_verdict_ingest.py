"""Production-shaped judge verdicts are accepted only under the probe lock."""

import json
from pathlib import Path

import pytest

from src.calibration.__main__ import main
from src.calibration.packets import ingest_verdicts

pytestmark = pytest.mark.unit


def _payload() -> dict:
    versions = {
        "completeness": "2.0.0",
        "faithfulness": "2.0.0",
        "groundedness": "1.0.0",
        "retrieval_recall": "2.0.0",
    }
    return {
        "judge_probe_lock": {
            "id": "instrument-under-calibration",
            "revision": "1.0.0",
            "rubric_versions": versions,
        },
        "verdicts": [
            {
                "blinded_item_id": "itm-0123456789ab",
                "rubric_name": "retrieval_recall",
                "rubric_version": versions["retrieval_recall"],
                "coverage": [{"topic": "t1", "covered": None}],
            }
        ],
    }


def test_measured_verdicts_ingest_with_none_as_abstention(tmp_path: Path) -> None:
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    report = ingest_verdicts(path)
    assert report.basis == "measured"
    assert report.verdicts_ingested == 1
    assert report.abstentions == 1


def test_verdict_ingest_refuses_rubric_lock_drift(tmp_path: Path) -> None:
    payload = _payload()
    payload["verdicts"][0]["rubric_version"] = "9.9.9"
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        ingest_verdicts(path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.update({"judge_probe_lock": "bad"}), "missing"),
        (lambda p: p.update({"judge_probe_lock": {"id": "bad", "revision": "1.0.0"}}), "does not match"),
        (lambda p: p.update({"verdicts": []}), "non-empty"),
        (lambda p: p.update({"verdicts": ["bad"]}), "each verdict"),
        (lambda p: p.update({"verdicts": [{"provenance": {"judge_probe_lock": {"id": "other"}}}]}), "provenance"),
        (lambda p: p.update({"verdicts": [{"blinded_item_id": "x", "rubric_name": "faithfulness", "rubric_version": "1.0.0"}]}), "provenance"),
    ],
)
def test_verdict_ingest_rejects_malformed_inputs(tmp_path: Path, change, message: str) -> None:
    payload = _payload()
    change(payload)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        ingest_verdicts(path)


def test_cli_reports_measured_verdicts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "verdicts.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    assert main(["ingest", str(path), "--manifest", str(path)]) == 0
    assert '"basis": "measured"' in capsys.readouterr().out


@pytest.mark.parametrize("raw", [[], {"judge_probe_lock": {"id": "instrument-under-calibration", "revision": "1.0.0", "rubric_versions": {"faithfulness": "0.0.0"}}, "verdicts": []}])
def test_ingest_rejects_non_object_or_lock_version_drift(tmp_path: Path, raw) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_verdicts(path)


def test_ingest_supports_scores_metrics_layout_and_duplicate_guard(tmp_path: Path) -> None:
    payload = _payload()
    row = payload["verdicts"][0]
    row.pop("coverage")
    row.pop("rubric_name")
    row.pop("rubric_version")
    row["scores"] = {
        "metrics": {
            "retrieval_recall": {
                "rubric_version": "2.0.0",
                "coverage": [{"topic": "t1", "covered": True}],
            }
        }
    }
    path = tmp_path / "nested.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert ingest_verdicts(path).verdicts_ingested == 1
    payload["verdicts"].append(dict(payload["verdicts"][0]))
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        ingest_verdicts(path)


def test_ingest_rejects_non_list_verdict_entries(tmp_path: Path) -> None:
    payload = _payload()
    payload["verdicts"][0]["coverage"] = {"topic": "t1"}
    path = tmp_path / "not-list.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a list"):
        ingest_verdicts(path)
