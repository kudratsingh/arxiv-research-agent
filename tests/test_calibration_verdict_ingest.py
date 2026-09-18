"""Production-shaped judge verdicts are accepted only under the probe lock."""

import json
from pathlib import Path

import pytest

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
