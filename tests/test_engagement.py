"""WO-W18 deterministic engagement and cost reporting."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from src.api.jobs import Job
from src.learning.engagement import (
    EngagementReport,
    _job_from_mapping,
    compute_engagement,
    main,
    render_markdown,
)
from src.learning.progress_store import ProgressEvent

FIXTURE = Path(__file__).parent / "fixtures" / "learning" / "engagement_14_day.json"


def _fixture() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _report() -> EngagementReport:
    raw = _fixture()
    events = [ProgressEvent.from_json_dict(item) for item in raw["events"]]
    jobs = [_job_from_mapping(item) for item in raw["jobs"]]
    return compute_engagement(events, jobs, window_start="2026-08-01")


class TestGoldenCohort:
    def test_the_14_day_report_matches_the_hand_computed_golden(self) -> None:
        raw = _fixture()
        assert _report().to_json_dict() == raw["expected"]

    def test_return_means_day_seven_or_later(self) -> None:
        outcomes = {item.principal_key_id: item for item in _report().principal_returns}
        assert outcomes["pilot-01"].returned_7d is True
        assert outcomes["pilot-01"].return_day == "2026-08-08"
        # A day-3 repeat is a session but not the week-2 return proxy.
        assert outcomes["pilot-02"].returned_7d is False

    def test_mid_window_pilot_is_immature_not_a_failure(self) -> None:
        outcomes = {item.principal_key_id: item for item in _report().principal_returns}
        assert outcomes["pilot-03"].observable_days == 5
        assert outcomes["pilot-03"].returned_7d is None
        assert _report().principals_eligible_for_7d == 2

    def test_non_session_events_and_out_of_window_sessions_are_excluded(self) -> None:
        report = _report()
        assert report.completed_sessions == 6
        assert "pilot-04" not in {item.principal_key_id for item in report.principal_returns}


class TestCostJoin:
    def test_guided_read_and_research_spend_are_separate(self) -> None:
        report = _report()
        assert report.guided_session_cost_usd == 1.5
        assert report.guided_session_cost_observations == 5
        assert report.guided_session_cost_missing == 1
        assert report.research_cost_usd_excluded == 0.75

    def test_research_job_cannot_be_joined_as_a_session_cost(self) -> None:
        event = ProgressEvent.from_json_dict(
            {
                "event_id": "evt-1",
                "principal_key_id": "pilot-1",
                "ts": "2026-08-01T00:00:00Z",
                "kind": "session_completed",
                "payload": {},
                "evidence_ref": "session:same-id",
            }
        )
        report = compute_engagement(
            [event],
            [Job(job_id="same-id", query="research", kind="research", cost_usd=9.0)],
            window_start="2026-08-01",
        )
        assert report.guided_session_cost_usd == 0
        assert report.guided_session_cost_missing == 1
        assert report.research_cost_usd_excluded == 9.0


class TestRefusedMetrics:
    @pytest.mark.parametrize("forbidden", ["app_open", "minute", "notification", "mastery"])
    def test_report_schema_has_no_refused_metric(self, forbidden: str) -> None:
        names = {field.name.lower() for field in dataclasses.fields(EngagementReport)}
        assert not any(forbidden in name for name in names)

    def test_sr10_definition_is_in_the_module_docstring(self) -> None:
        from src.learning import engagement

        assert engagement.__doc__ is not None
        assert "return in week 2 without being nudged" in engagement.__doc__
        assert "7-day-return" in engagement.__doc__

    def test_markdown_names_denominators_and_small_n(self) -> None:
        rendered = render_markdown(_report())
        assert "Eligible for a 7-day outcome: 2" in rendered
        assert "7-day return: **50.0%**" in rendered
        assert "one person moves the rate by at least 20 percentage points" in rendered
        assert "Research-run spend excluded" in rendered


class TestCli:
    def test_cli_writes_the_same_report(self, tmp_path: Path) -> None:
        raw = _fixture()
        events_path = tmp_path / "events.json"
        jobs_path = tmp_path / "jobs.json"
        output = tmp_path / "gate-w2" / "engagement.md"
        events_path.write_text(json.dumps({"events": raw["events"]}), encoding="utf-8")
        jobs_path.write_text(json.dumps({"jobs": raw["jobs"]}), encoding="utf-8")
        assert (
            main(
                [
                    "--events",
                    str(events_path),
                    "--jobs",
                    str(jobs_path),
                    "--window-start",
                    "2026-08-01",
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        assert output.read_text(encoding="utf-8") == render_markdown(_report())

    @pytest.mark.parametrize(
        "raw",
        [
            {"job_id": "x", "kind": "unknown", "cost_usd": 1.0},
            {"job_id": "x", "kind": "session", "cost_usd": -0.1},
            {"job_id": "x", "kind": "session", "cost_usd": True},
        ],
    )
    def test_cli_job_parser_refuses_invalid_accounting(self, raw: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            _job_from_mapping(raw)
