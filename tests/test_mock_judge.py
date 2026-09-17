"""The opt-in, zero-spend mock judge and its campaign records."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from src.campaign.errors import CampaignError
from src.campaign.execute import EpisodeRun
from src.campaign.matrix import PlannedEpisode
from src.config import Settings
from src.contracts.run_manifest import CompletionStatus
from src.eval.mock_judge import (
    MOCK_JUDGE_FIXTURE_PATH,
    MockCompletenessOutput,
    MockJudgeFixture,
    build_mock_judge_scorer,
    load_mock_judge_fixture,
)
from src.graph.state import Citation, PaperMetadata

pytestmark = pytest.mark.unit


def _config(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "use_mock_data": True,
        "anthropic_api_key": "local-preview-disabled",
    }
    values.update(overrides)
    return Settings(**values)


def _episode() -> PlannedEpisode:
    return cast(
        PlannedEpisode,
        SimpleNamespace(
            case_id="hallucination-mitigation",
            arm_id="A",
            run_id="run_00000000000000000000000000000001",
        ),
    )


def _run() -> EpisodeRun:
    paper = PaperMetadata(
        id="https://arxiv.org/abs/2401.00001",
        title="Fixture paper",
        authors=["Ada Example"],
        abstract="A fixture abstract supports one synthetic claim.",
        url="https://arxiv.org/abs/2401.00001",
        pdf_url="https://arxiv.org/pdf/2401.00001",
    )
    citation = Citation(
        paper_id=paper["id"],
        title=paper["title"],
        authors=paper["authors"],
        year="2024",
        url=paper["url"],
    )
    return EpisodeRun(
        status=CompletionStatus.SUCCEEDED,
        reason=None,
        visited=("planner", "search", "reader", "synthesizer", "critic"),
        state={
            "draft_report": (
                "# Briefing\n\nA fixture claim (arXiv:2401.00001) "
                "[Example, 2024]."
            ),
            "papers": [paper],
            "citations": [citation],
            "evidence": [],
        },
    )


class TestTheFixtureAndSchemas:
    def test_the_checked_in_fixture_is_strict_and_complete(self) -> None:
        fixture = load_mock_judge_fixture()

        assert fixture.fixture_id == "research-mock-judge-v1"
        assert len(fixture.pairwise_case_ids) == 6
        assert fixture.faithfulness.abstain_at == 1

    def test_an_unknown_fixture_field_is_refused(self) -> None:
        payload = MOCK_JUDGE_FIXTURE_PATH.read_text(encoding="utf-8").replace(
            '"schema_version": "1.0.0",',
            '"schema_version": "1.0.0", "unknown": true,',
        )

        with pytest.raises(ValidationError):
            MockJudgeFixture.model_validate_json(payload)

    def test_a_malformed_structured_response_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            MockCompletenessOutput.model_validate(
                {"coverage": [{"topic": "x", "covered": "yes", "reason": "x"}]}
            )


class TestTheMockJudgeScorer:
    def test_it_runs_all_five_metrics_and_records_the_instrument(self) -> None:
        scores = build_mock_judge_scorer(_config())(_episode(), _run())

        assert scores.detail["judges_run"] is True
        assert scores.detail["judge_rubrics_skipped"] == []
        assert set(scores.detail["metrics"]) == {
            "citation_resolution",
            "supported_claim_precision",
            "completeness",
            "faithfulness",
            "retrieval_recall",
        }
        records = scores.detail["judge_records"]
        assert [record["rubric_name"] for record in records] == [
            "completeness",
            "faithfulness",
            "retrieval_recall",
        ]
        assert all(record["leaked_identity_terms"] == [] for record in records)
        assert scores.judge_model_calls == 0
        assert scores.judge_cost_usd == "0.000000"

    def test_position_control_uses_blinded_ids_and_both_randomised_orders(self) -> None:
        scores = build_mock_judge_scorer(_config())(_episode(), _run())
        control = scores.detail["calibration_position_control"]
        readings = control["readings"]

        assert control["plan"]["presentation"] == "pairwise"
        assert control["plan"]["both_orders"] is True
        assert len(readings) == 12
        ids = {reading["blinded_item_id"] for reading in readings}
        assert len(ids) == 6
        for item_id in ids:
            assert item_id.startswith("itm-")
            orders = {
                reading["presentation_order"]
                for reading in readings
                if reading["blinded_item_id"] == item_id
            }
            assert orders == {"ab", "ba"}

    def test_faithfulness_null_is_recorded_as_a_mock_abstention(self) -> None:
        fixture = load_mock_judge_fixture().model_copy(
            update={
                "faithfulness": load_mock_judge_fixture().faithfulness.model_copy(
                    update={"abstain_at": 1}
                )
            }
        )
        scorer = build_mock_judge_scorer(_config())
        scorer.fixture = fixture

        scores = scorer(_episode(), _run())

        assert scores.detail["judge_abstentions"] == 1
        faithfulness = next(
            record
            for record in scores.detail["judge_records"]
            if record["rubric_name"] == "faithfulness"
        )
        assert faithfulness["response"]["claims"][0]["supported"] is None

    @pytest.mark.parametrize(
        "config",
        [
            _config(use_mock_data=False),
            _config(anthropic_api_key="some-real-shaped-key"),
        ],
    )
    def test_it_refuses_any_path_that_is_not_structurally_free(
        self, config: Settings
    ) -> None:
        with pytest.raises(CampaignError, match="requires"):
            build_mock_judge_scorer(config)

    def test_fixture_path_is_packaged_beside_the_module(self) -> None:
        assert Path(MOCK_JUDGE_FIXTURE_PATH).is_file()
