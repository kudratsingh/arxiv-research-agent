from __future__ import annotations
import json
from pathlib import Path
import pytest
from src.calibration.pool import build_pool

pytestmark = pytest.mark.unit

def test_pool_reads_episode_state_and_verdicts_and_blinds(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"; run.mkdir(parents=True)
    (run / "episode-state.json").write_text(json.dumps({"campaign_id":"c1","arm_id":"A","papers":[{"id":"p1","abstract":"abstract text"}],"reader":{"chunks":[]}}))
    (run / "scores.json").write_text(json.dumps({"scores":{"faithfulness":{"claims":[{"paper_id":"p1","claim":"claim","supported":False}]},"completeness":{"coverage":[{"topic":"topic","covered":None,"reason":"no evidence"}]}}}))
    out = build_pool("c1", tmp_path)
    payload=json.loads(out.read_text())
    assert payload["suite_revision"] == "1.1.0"
    assert payload["stress_set_separate"] is True
    assert payload["strata_counts"] == {"completeness:abstain": 1, "faithfulness:failed": 1}
    assert all(item["item_id"].startswith("itm-") for item in payload["items"])

def test_pool_refuses_missing_campaign(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no episode verdicts"):
        build_pool("missing", tmp_path)
