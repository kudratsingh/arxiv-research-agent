"""WO-W10: the learner-simulation benchmark.

Three layers, matching how the card's acceptance criteria are provable:

  - Pure helpers (script alignment, outcome scoring, summary shape,
    the repeat warning) are tested directly.
  - The **scripted tier runs for real** against WO-W03's compiled graph
    in mock mode, over the whole 15-scenario set, with client
    construction monkeypatched to explode — the WO-W03 c5 assertion,
    carried up to a whole campaign (c1).
  - `main()` is exercised with `run_scenario` monkeypatched, so campaign
    behaviour (durable records, `--resume`, budget stop, exit codes,
    interrupt flush) is tested without a graph at all — the discipline
    `tests/test_eval_runner.py` established for the research runner.

No test in this file makes a paid call. The funded tier is exercised
only through a monkeypatched `call_llm_json`; the first real funded
campaign is deferred to **W-OD-1**.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.eval import learning_metrics as metrics_module
from src.eval import simulate_learner as sim
from src.eval.learning_benchmark import (
    LEARNING_SCENARIOS,
    get_paper,
    get_persona,
    get_scenario,
)
from src.eval.runner import (
    EXIT_ALL_FAILED,
    EXIT_BUDGET_STOP,
    EXIT_CONFIG,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_PARTIAL_FAILURE,
    EXIT_USAGE,
    EvalInterrupted,
    load_records,
    persist_record,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Settings + zero-spend harness
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    """The canonical mock-mode configuration, per `test_guided_session_graph`."""
    values: dict[str, object] = {
        "anthropic_api_key": "local-preview-disabled",
        "use_mock_data": True,
        "enable_api_auth": True,
        "api_keys": "alice:sk_alice",
        "enable_checkpointing": True,
        "checkpoint_backend": "sqlite",
        "checkpoint_db_path": str(tmp_path / "sim.sqlite"),
        "enable_learner_profile": True,
        "enable_session_loop": True,
        "enable_prompt_isolation": True,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _patch_settings(monkeypatch: pytest.MonkeyPatch, configured: Settings) -> None:
    """Rebind `settings` on every module the session path reads it from.

    `src.learning.memory` is in this list and is **not** in
    `test_guided_session_graph._patch_settings`: `progress_update_agent`
    calls `generate_session_memory` unconditionally, and that module
    checks its own `settings.use_mock_data`. Without this line the memory
    node takes the live branch and is saved only by `call_llm` raising on
    a missing key — which is not a guarantee, it is an accident.
    """
    from src.agents import assessment as assessment_module
    from src.agents import tutor as tutor_module
    from src.graph import workflow as workflow_module
    from src.learning import memory as memory_module

    for module in (
        tutor_module,
        assessment_module,
        memory_module,
        workflow_module,
        sim,
    ):
        monkeypatch.setattr(module, "settings", configured)


def _forbid_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any Anthropic client construction fail the test.

    This is the WO-W03 c5 assertion. `src.llm._get_client` is the single
    choke point every paid path funnels through — `call_llm`, and so
    `call_llm_json`, calls it before touching the network — so exploding
    here catches a spend the per-module mock branches missed, including
    one introduced by a future edit to a node this test does not know
    about.
    """
    import src.llm as llm_module

    def _boom() -> Any:
        raise AssertionError("Anthropic client constructed in the scripted tier")

    monkeypatch.setattr(llm_module, "_get_client", _boom)


@pytest.fixture
def _zero_spend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_settings(monkeypatch, _settings(tmp_path))
    _forbid_client(monkeypatch)


# ---------------------------------------------------------------------------
# c1 — the scripted tier runs the whole set with zero paid calls
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_zero_spend")
class TestScriptedTierRunsTheFullSet:
    def test_every_scenario_completes_with_zero_spend(self) -> None:
        # THE c1 CHECK. The whole benchmark, through the real compiled
        # session graph, with client construction fatal.
        assert len(LEARNING_SCENARIOS) == 15
        for scenario in LEARNING_SCENARIOS:
            record = sim.run_scenario(
                scenario,
                repeat=1,
                tier=sim.TIER_SCRIPTED,
                judges=False,
                learner_model="",
            )
            assert record["error"] is None, record["error"]
            assert record["costs"]["total_cost_usd"] == 0.0
            assert record["costs"]["call_count"] == 0
            assert record["learner_costs"]["call_count"] == 0
            assert record["judge_costs"] is None
            assert record["turns_delivered"] >= 2

    def test_every_scenario_emits_evidence_linked_progress_events(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            outcomes = record["outcomes"]
            assert outcomes["progress_events_evidence_linked"], scenario["scenario_id"]
            assert outcomes["unlinked_progress_events"] == []

    def test_no_scenario_produces_shaming_copy(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            assert record["outcomes"]["shame_free"], record["outcomes"]["shame_findings"]

    def test_the_judged_copy_is_not_vacuously_clean(self) -> None:
        # A shame scan over an empty list passes. Pin that the copy the
        # scan sees is the tutor's actual words, and that the learner's
        # own text is excluded — an adversarial script plants shaming
        # language deliberately, and scoring the product for it would
        # fail the session for an attack it contained.
        scenario = get_scenario("novice-transformer-baseline")
        assert scenario is not None
        persona = get_persona(scenario["persona_id"])
        paper = get_paper(scenario["paper_id"])
        assert persona is not None and paper is not None
        run = sim.drive_session(
            scenario,
            persona,
            paper,
            "copy-probe",
            tier=sim.TIER_SCRIPTED,
            learner_model="",
            costs_snapshot=dict,
        )
        copy_texts = sim.learner_facing_copy(run.state, run.replies)
        assert len(copy_texts) >= 5
        assert any("Explain the paper's central move" in text for text in copy_texts)
        for reply in run.replies:
            assert all(reply.text not in text for text in copy_texts)

    def test_the_adversarial_probes_are_delivered_and_contained(self) -> None:
        # ADR 0020's property observed end to end: the probe really does
        # enter the session as learner text (otherwise containment is
        # trivially true) and never reaches a control field.
        adversarial = [s for s in LEARNING_SCENARIOS if s["script_kind"] == "adversarial"]
        assert len(adversarial) == 2
        for scenario in adversarial:
            probe = scenario["expectations"]["injection_probe"]
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            delivered = [t["text"] for t in record["transcript"]]
            assert any(probe in text for text in delivered), "probe was never planted"
            assert record["outcomes"]["injection_contained"] is True
            assert record["outcomes"]["injection_leaks"] == []

    def test_a_leaked_probe_is_reported_rather_than_ignored(self) -> None:
        # Mutation check: the containment outcome is only worth anything
        # if a leak fails it.
        scenario = get_scenario("switcher-rlhf-injection-in-explain-back")
        assert scenario is not None
        probe = scenario["expectations"]["injection_probe"]
        leaked = {
            "session_plan": {"downscope_reason": f"mode {probe}"},
            "assessment": {"status": "recorded_ungraded", "guidance_only": True},
            "progress_events": [
                {"kind": "session_completed", "evidence_ref": "session:x"}
            ],
        }
        outcomes = sim.compute_outcomes(scenario, leaked, [])
        assert outcomes.injection_contained is False
        assert "session_plan" in outcomes.injection_leaks
        assert any("control field" in f for f in outcomes.expectation_failures)

    def test_the_time_poor_scripts_get_an_honest_downscope(self) -> None:
        for scenario_id in (
            "switcher-scaling-laws-time-poor",
            "engineer-transformer-time-poor",
        ):
            scenario = get_scenario(scenario_id)
            assert scenario is not None
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            outcomes = record["outcomes"]
            assert outcomes["downscope_honest"] is True
            assert outcomes["plan_sections"] == 1

    def test_the_assessment_judge_being_off_never_fabricates_an_outcome(self) -> None:
        # ADR 0060: with the judge off the honest record is
        # `recorded_ungraded` (or nothing at all when the learner ended
        # before the explain-back), never a grade.
        for scenario in LEARNING_SCENARIOS:
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            assert record["outcomes"]["observed_assessment"] in (
                "recorded_ungraded",
                "none",
            )
            assessment = record["state"]["assessment"]
            assert not any(
                key in assessment for key in ("score", "grade", "mastery", "level")
            )

    def test_unmet_expectations_are_exactly_the_recorded_baseline(self) -> None:
        # The recorded baseline is now empty, and that is a resolution
        # rather than a relaxation. WO-W10 pinned one divergence here:
        # `engineer-rlhf-profile-note-injection` allowed a single plan
        # section while `check_in` allocates two for its declared
        # 15 minutes (`_fallback_plan`: <=10 min -> 1, <=20 min -> 2).
        # WO-W11 read the scenario's intent — an injection script at the
        # persona's standing budget, not a time-poor one — and moved the
        # *expectation* to 2, matching the graph's documented rule and
        # the other two 15-minute scenarios. No graph behaviour changed.
        #
        # The assertion stays exact so a *new* divergence still fails
        # here rather than being averaged away.
        unmet: dict[str, list[str]] = {}
        for scenario in LEARNING_SCENARIOS:
            record = sim.run_scenario(
                scenario, repeat=1, tier=sim.TIER_SCRIPTED, judges=False, learner_model=""
            )
            failures = record["outcomes"]["expectation_failures"]
            if failures:
                unmet[scenario["scenario_id"]] = failures
        assert unmet == {}

    def test_the_fifteen_minute_scenarios_agree_with_the_graphs_plan_rule(
        self,
    ) -> None:
        # The regression guard for WO-W11 item 7. `check_in` allocates
        # plan sections from the declared budget; a scenario that
        # declares 15 minutes and expects fewer than two sections is
        # asking the graph for something its documented rule forbids,
        # which is how the original divergence arose.
        for scenario in LEARNING_SCENARIOS:
            if scenario["declared_minutes_today"] != 15:
                continue
            assert scenario["expectations"]["max_plan_sections"] >= 2, scenario[
                "scenario_id"
            ]


# ---------------------------------------------------------------------------
# Script alignment
# ---------------------------------------------------------------------------


class TestScriptAlignment:
    def test_the_closing_explain_back_waits_for_the_explain_back_turn(self) -> None:
        scenario = get_scenario("switcher-scaling-laws-time-poor")
        assert scenario is not None
        persona = get_persona(scenario["persona_id"])
        assert persona is not None
        # Two scripted turns; the graph asks four questions. Turn 0 lands
        # on the opening reflection, the closer is held through both
        # guided questions and delivered to the explain-back.
        reply, cursor = sim._scripted_voice(scenario, persona, {"kind": "reflection"}, 0)
        assert (reply.source, cursor) == ("script", 1)
        held, cursor = sim._scripted_voice(
            scenario, persona, {"kind": "guided_question"}, cursor
        )
        assert held.text == sim.SCRIPT_EXHAUSTED_REPLY
        assert (held.source, cursor) == ("filler", 1)
        closer, cursor = sim._scripted_voice(
            scenario, persona, {"kind": "explain_back"}, cursor
        )
        assert closer.intent == "explain_back"
        assert cursor == 2

    def test_an_end_session_turn_ends_the_session(self) -> None:
        scenario = get_scenario("novice-seq2seq-abandons-midway")
        assert scenario is not None
        persona = get_persona(scenario["persona_id"])
        assert persona is not None
        reply, cursor = sim._scripted_voice(
            scenario, persona, {"kind": "guided_question"}, 1
        )
        assert reply.end_requested is True
        assert reply.intent == "end_session"
        assert cursor == 2

    def test_a_session_that_ends_early_writes_no_assessment_event(self) -> None:
        scenario = get_scenario("novice-seq2seq-abandons-midway")
        assert scenario is not None
        assert scenario["expectations"]["expected_assessment"] == "unassessed"
        assert scenario["expectations"]["expected_progress_events"] == [
            "session_completed"
        ]

    def test_record_ids_round_trip_and_sort_in_benchmark_order(self) -> None:
        first = sim.record_id("novice-transformer-baseline", 1)
        second = sim.record_id("engineer-scaling-laws-skeptic", 2)
        assert first == "novice-transformer-baseline.r1"
        assert sim.simulation_order(first) < sim.simulation_order(second)
        assert sim.simulation_order("novice-transformer-baseline.r2") > sim.simulation_order(
            first
        )
        # An unknown id (a retired scenario whose record is still on
        # disk) sorts last rather than crashing the rebuild.
        assert sim.simulation_order("retired.r1")[0] == len(LEARNING_SCENARIOS)


# ---------------------------------------------------------------------------
# c4 — summary shape and the cost split
# ---------------------------------------------------------------------------


def _record(
    record_id: str = "novice-transformer-baseline.r1",
    *,
    err: str | None = None,
    cost: float = 0.0,
    learner: float = 0.0,
    judge: float | None = None,
) -> dict[str, Any]:
    """A record shaped like `run_scenario`'s output."""
    scenario_id = record_id.rpartition(".r")[0]
    return {
        "record_id": record_id,
        "run_id": "abc",
        "scenario_id": scenario_id,
        "persona_id": "novice-undergrad",
        "paper_id": "arxiv:1706.03762",
        "script_kind": "baseline",
        "repeat": 1,
        "tier": "scripted",
        "elapsed_sec": 1.0,
        "scoring_sec": None if judge is None else 0.5,
        "costs": {"total_cost_usd": cost, "call_count": 2},
        "learner_costs": {"total_cost_usd": learner, "call_count": 1},
        "judge_costs": None if judge is None else {"total_cost_usd": judge, "call_count": 2},
        "state": {"assessment": {}},
        "transcript": [],
        "turns_delivered": 4,
        "filler_replies": 0,
        "outcomes": None
        if err
        else {
            "shame_free": True,
            "shame_findings": [],
            "downscope_honest": None,
            "plan_sections": 3,
            "progress_events_evidence_linked": True,
            "unlinked_progress_events": [],
            "injection_contained": None,
            "injection_leaks": [],
            "observed_assessment": "recorded_ungraded",
            "observed_progress_events": ["assessment", "session_completed"],
            "expectation_failures": [],
        },
        "metrics": None
        if judge is None
        else {
            "shame_free_copy": {"score": 0.9},
            "session_plan_coherence": {"score": 0.8},
        },
        "metrics_error": None,
        "error": err,
    }


class TestSummaryShape:
    def test_the_cost_split_names_three_payers(self) -> None:
        # THE c4 CHECK. ADR 0050 separates the product from the harness;
        # this campaign's harness has two halves, so `cost_usd` must
        # describe the session graph alone.
        row = sim.summary_line(_record(cost=0.20, learner=0.05, judge=0.03))
        assert row["cost_usd"] == 0.20
        assert row["learner_cost_usd"] == 0.05
        assert row["judge_cost_usd"] == 0.03
        assert row["total_cost_usd"] == 0.28
        assert row["llm_calls"] == 2
        assert row["learner_llm_calls"] == 1
        assert row["judge_llm_calls"] == 2

    def test_judged_outcomes_ride_in_the_summary_row(self) -> None:
        row = sim.summary_line(_record(judge=0.03))
        for field in (
            "shame_free",
            "shame_free_score",
            "downscope_honest",
            "plan_coherence",
            "progress_events_evidence_linked",
            "injection_contained",
            "observed_assessment",
            "expectation_failures",
        ):
            assert field in row
        assert row["shame_free_score"] == 0.9
        assert row["plan_coherence"] == 0.8

    def test_an_unjudged_row_reports_no_score_rather_than_a_zero(self) -> None:
        row = sim.summary_line(_record())
        assert row["shame_free_score"] is None
        assert row["plan_coherence"] is None
        assert row["judge_cost_usd"] is None
        assert row["shame_free"] is True

    def test_a_failed_session_summarises_without_raising(self) -> None:
        row = sim.summary_line(_record(err="RuntimeError: boom"))
        assert row["error"] == "RuntimeError: boom"
        assert row["shame_free"] is None
        assert row["expectation_failures"] is None

    def test_summary_markdown_names_the_honesty_caveat(self) -> None:
        text = sim.summary_markdown([_record(cost=0.2, judge=0.1)], "sim-x")
        assert "process metrics" in text
        assert "Session cost" in text and "Judge cost" in text
        assert "novice-transformer-baseline" in text

    def test_summary_markdown_prints_cost_against_the_plans_estimate(self) -> None:
        # WO-W11 c4: Gate W2's cost question is answered by the eval
        # plumbing, with the plan's number labelled as an estimate in the
        # row so it cannot be read as a measurement.
        text = sim.summary_markdown([_record(cost=0.2, judge=0.1)], "sim-x")
        low, high = sim.PLANNED_SESSION_COST_USD
        assert "Cost per session vs the plan's estimate" in text
        assert f"{low:.2f} – {high:.2f}" in text
        assert "**not a measurement**" in text
        assert "01-LEARNING-AGENT.md §6.1" in text
        assert "Measured mean `cost_usd` over 1 session(s)" in text

    def test_the_cost_row_quotes_the_product_cost_not_the_total(self) -> None:
        # `cost_usd` alone. Quoting the harness's spend as what a session
        # costs a learner is the exact confusion ADR 0050 split apart.
        text = sim.summary_markdown([_record(cost=0.2, judge=5.0)], "sim-x")
        assert "| 0.2000 |" in text

    def test_a_campaign_with_no_cost_column_prints_no_cost_row(self) -> None:
        record = _record()
        record["costs"]["total_cost_usd"] = None
        text = sim.summary_markdown([record], "sim-x")
        assert "Cost per session vs the plan's estimate" not in text


class TestRepeatWarning:
    def test_a_single_run_campaign_is_warned_about(self) -> None:
        warning = sim.repeat_warning(1)
        assert warning is not None
        assert "Judge noise mandates repeat runs" in warning
        assert str(sim.REPEATS_FOR_CONFIDENCE) in warning

    def test_three_repeats_earn_silence(self) -> None:
        assert sim.repeat_warning(sim.REPEATS_FOR_CONFIDENCE) is None
        assert sim.repeat_warning(5) is None

    def test_the_warning_reaches_the_markdown_summary(self) -> None:
        text = sim.summary_markdown([_record()], "sim-x")
        assert "Repeat discipline" in text


# ---------------------------------------------------------------------------
# Rubric judges — canned responses only, never a paid call
# ---------------------------------------------------------------------------


def _is_shame_judge(kwargs: dict[str, Any]) -> bool:
    """Which judge a canned `call_llm_json` stub was just asked for.

    Compared against the prompt constant itself rather than sniffed for a
    keyword: a substring guess silently routes both judges to the same
    canned answer the moment the prompt is reworded, and a test that
    passes because the wrong judge failed is worse than no test.
    """
    return kwargs.get("system_prompt") == metrics_module.SHAME_FREE_COPY_SYSTEM_PROMPT


def _shame_free_response(quotes: list[str] | None = None) -> dict[str, Any]:
    return {
        "score": 0.95,
        "respects_effort": {"score": 1.0, "reason": "No blame."},
        "avoids_deficit_framing": {"score": 0.9, "reason": "Describes the plan."},
        "offers_a_next_step": {"score": 1.0, "reason": "Names one question."},
        "offending_quotes": quotes or [],
        "summary": "Copy is descriptive rather than evaluative.",
    }


class TestJudgeIsolation:
    def test_one_failed_judge_keeps_the_other(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # `runner._compute_metrics`'s discipline: a judge that dies costs
        # its own metric, never the session that was already paid for.
        _patch_settings(monkeypatch, _settings(tmp_path))
        scenario = get_scenario("switcher-scaling-laws-time-poor")
        assert scenario is not None

        def _fake(**kwargs: Any) -> dict[str, Any]:
            if _is_shame_judge(kwargs):
                raise RuntimeError("judge timeout")
            return {
                "score": 0.7,
                "section_ordering": {"score": 0.7, "reason": "ok"},
                "time_budget": {"score": 0.8, "reason": "fits"},
                "check_placement": {"score": 0.6, "reason": "one check"},
                "downscope_honesty": {"score": 1.0, "reason": "states the cut"},
                "summary": "Honest one-section plan.",
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", _fake)
        state = {
            "session_plan": {
                "available_minutes": 10,
                "downscoped": True,
                "downscope_reason": "Reduced to fit the declared 10-minute window.",
                "sections": [{"name": "introduction", "mode": "close"}],
            }
        }
        metrics, error = sim.run_judges(scenario, state, [])
        assert metrics["shame_free_copy"] is None
        assert metrics["session_plan_coherence"] is not None
        assert metrics["session_plan_coherence"]["downscope_honesty"]["score"] == 1.0
        assert "shame_free_copy" in str(error)


# ---------------------------------------------------------------------------
# c3 — the funded tier's refusals
# ---------------------------------------------------------------------------


class TestFundedTierRefusals:
    def test_funded_without_a_budget_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # THE c3 CHECK. An uncapped paid campaign never starts.
        monkeypatch.setattr(sim, "settings", _settings(tmp_path, use_mock_data=False))
        code = sim.main(["--tier", "funded", "--output-dir", str(tmp_path / "out")])
        assert code == EXIT_CONFIG
        err = capsys.readouterr().err
        assert "--max-budget-usd" in err
        assert "W-OD-1" in err
        assert not (tmp_path / "out").exists()

    def test_judges_without_a_budget_are_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sim, "settings", _settings(tmp_path))
        code = sim.main(["--judges", "--output-dir", str(tmp_path / "out")])
        assert code == EXIT_CONFIG
        assert "--max-budget-usd" in capsys.readouterr().err

    def test_a_non_positive_budget_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(sim, "settings", _settings(tmp_path, use_mock_data=False))
        code = sim.main(
            ["--tier", "funded", "--max-budget-usd", "0", "--output-dir", str(tmp_path)]
        )
        assert code == EXIT_CONFIG

    def test_funded_against_mock_mode_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A "funded" campaign that bills nothing measures nothing.
        monkeypatch.setattr(sim, "settings", _settings(tmp_path, use_mock_data=True))
        code = sim.main(
            ["--tier", "funded", "--max-budget-usd", "15", "--output-dir", str(tmp_path)]
        )
        assert code == EXIT_CONFIG
        assert "USE_MOCK_DATA" in capsys.readouterr().err

    def test_scripted_against_live_models_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The symmetric refusal, and the more important one: the scripted
        # tier advertises zero spend, so it must not quietly bill.
        monkeypatch.setattr(sim, "settings", _settings(tmp_path, use_mock_data=False))
        code = sim.main(["--output-dir", str(tmp_path)])
        assert code == EXIT_CONFIG
        assert "zero spend" in capsys.readouterr().err

    def test_a_graph_without_a_checkpointer_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Every learner turn is a durable interrupt; without a
        # checkpointer the graph cannot pause at all.
        configured = Settings(  # type: ignore[arg-type]
            anthropic_api_key="local-preview-disabled",
            use_mock_data=True,
            enable_checkpointing=False,
        )
        monkeypatch.setattr(sim, "settings", configured)
        code = sim.main(["--output-dir", str(tmp_path)])
        assert code == EXIT_CONFIG
        assert "ENABLE_CHECKPOINTING" in capsys.readouterr().err

    def test_a_bad_repeat_count_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(sim, "settings", _settings(tmp_path))
        assert sim.main(["--repeats", "0", "--output-dir", str(tmp_path)]) == EXIT_CONFIG


class TestFundedTierLearner:
    def test_the_model_learner_only_fills_unscripted_turns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The probe has to arrive verbatim or the containment check
        # measures nothing, so scripted text always wins over the model.
        scenario = get_scenario("switcher-rlhf-injection-in-explain-back")
        assert scenario is not None
        persona = get_persona(scenario["persona_id"])
        assert persona is not None
        calls: list[dict[str, Any]] = []

        def _fake(**kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"reply": "Improvised learner answer."}

        monkeypatch.setattr(sim, "call_llm_json", _fake)

        scripted, cursor = sim._model_voice(
            scenario, persona, {"kind": "reflection"}, 0, model_name="cheap-model"
        )
        assert scripted.source == "script"
        assert calls == []

        improvised, cursor = sim._model_voice(
            scenario, persona, {"kind": "guided_question", "prompt": "Why?"}, 2,
            model_name="cheap-model",
        )
        assert improvised.source == "model"
        assert improvised.text == "Improvised learner answer."
        assert cursor == 2
        assert calls[0]["model_name"] == "cheap-model"

    def test_a_mute_model_learner_falls_back_rather_than_aborting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scenario = get_scenario("switcher-scaling-laws-time-poor")
        assert scenario is not None
        persona = get_persona(scenario["persona_id"])
        assert persona is not None

        def _boom(**_: Any) -> dict[str, Any]:
            raise RuntimeError("overloaded")

        monkeypatch.setattr(sim, "call_llm_json", _boom)
        reply, cursor = sim._model_voice(
            scenario, persona, {"kind": "guided_question"}, 1, model_name=""
        )
        assert reply.text == sim.SCRIPT_EXHAUSTED_REPLY
        assert reply.source == "filler"
        assert cursor == 1


# ---------------------------------------------------------------------------
# c2 — durability, resume, budget stop, exit codes
# ---------------------------------------------------------------------------


def _fake_runs(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[str, dict[str, Any]],
    *,
    seen: list[str] | None = None,
) -> None:
    """Replace `run_scenario` with a canned per-scenario outcome table."""

    def _fake(scenario: Any, **kwargs: Any) -> dict[str, Any]:
        key = sim.record_id(scenario["scenario_id"], kwargs["repeat"])
        if seen is not None:
            seen.append(key)
        return outcomes[key]

    monkeypatch.setattr(sim, "run_scenario", _fake)


def _three_ids() -> list[str]:
    return [s["scenario_id"] for s in LEARNING_SCENARIOS[:3]]


def main_with(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str]
) -> int:
    """`main()` under mock-mode settings, with `--output-dir` appended."""
    monkeypatch.setattr(sim, "settings", _settings(tmp_path))
    return sim.main([*argv, "--output-dir", str(tmp_path / "out")])


class TestCampaignDiscipline:
    def test_all_succeed_exits_zero_and_writes_everything(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        _fake_runs(monkeypatch, {k: _record(k, cost=0.1) for k in keys})

        code = main_with(
            monkeypatch, tmp_path, ["--scenarios", ",".join(ids)]
        )

        assert code == EXIT_OK
        out = tmp_path / "out"
        assert set(load_records(out, shape=sim.SIMULATION_CAMPAIGN)) == set(keys)
        assert (out / "summary.md").is_file()
        assert (out / "summary.jsonl").is_file()
        assert (out / "scenarios").is_dir()

    def test_records_survive_a_mid_campaign_kill(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # THE c2 CRASH-SAFETY CHECK. Scenario 2 raises `EvalInterrupted`
        # (what a SIGTERM becomes). Scenario 1's completed record and
        # scenario 2's partial record must both be on disk; scenario 3
        # must never have been attempted.
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        seen: list[str] = []
        partial = _record(keys[1], err="Interrupted: KeyboardInterrupt", cost=0.4)

        def _fake(scenario: Any, **kwargs: Any) -> dict[str, Any]:
            key = sim.record_id(scenario["scenario_id"], kwargs["repeat"])
            seen.append(key)
            if key == keys[1]:
                raise EvalInterrupted(partial)
            return _record(key, cost=0.2)

        monkeypatch.setattr(sim, "run_scenario", _fake)

        code = main_with(monkeypatch, tmp_path, ["--scenarios", ",".join(ids)])

        assert code == EXIT_INTERRUPTED
        assert seen == keys[:2]
        on_disk = load_records(tmp_path / "out", shape=sim.SIMULATION_CAMPAIGN)
        assert set(on_disk) == {keys[0], keys[1]}
        assert on_disk[keys[1]]["error"].startswith("Interrupted")
        assert (tmp_path / "out" / "summary.md").is_file()

    def test_resume_skips_completed_scenarios(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # THE c2 RESUME CHECK. Without it a re-entered campaign re-pays
        # for every session it already ran.
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        out = tmp_path / "out"
        persist_record(out, _record(keys[0], cost=0.3), shape=sim.SIMULATION_CAMPAIGN)
        seen: list[str] = []
        _fake_runs(
            monkeypatch, {k: _record(k, cost=0.1) for k in keys}, seen=seen
        )

        code = main_with(
            monkeypatch, tmp_path, ["--scenarios", ",".join(ids), "--resume"]
        )

        assert code == EXIT_OK
        assert seen == keys[1:]
        assert set(load_records(out, shape=sim.SIMULATION_CAMPAIGN)) == set(keys)

    def test_a_populated_directory_without_resume_is_a_usage_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "summary.jsonl").write_text("{}\n", encoding="utf-8")
        assert main_with(monkeypatch, tmp_path, []) == EXIT_USAGE

    def test_the_budget_ceiling_stops_the_campaign(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # THE c3 CEILING CHECK. `EXIT_BUDGET_STOP` semantics preserved,
        # and the learner's spend counts toward the ceiling — it is
        # money, whichever side of the product boundary it sits on.
        monkeypatch.setattr(sim, "settings", _settings(tmp_path, use_mock_data=False))
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        seen: list[str] = []
        _fake_runs(
            monkeypatch,
            {k: _record(k, cost=4.0, learner=2.0, judge=1.0) for k in keys},
            seen=seen,
        )

        code = sim.main(
            [
                "--tier", "funded",
                "--max-budget-usd", "6",
                "--scenarios", ",".join(ids),
                "--output-dir", str(tmp_path / "out"),
            ]
        )

        assert code == EXIT_BUDGET_STOP
        assert seen == keys[:1]
        assert "Budget ceiling $6.00 reached" in capsys.readouterr().out

    def test_a_single_errored_scenario_is_partial_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        outcomes = {k: _record(k) for k in keys}
        outcomes[keys[1]] = _record(keys[1], err="RuntimeError: graph blew up")
        _fake_runs(monkeypatch, outcomes)
        code = main_with(monkeypatch, tmp_path, ["--scenarios", ",".join(ids)])
        assert code == EXIT_PARTIAL_FAILURE

    def test_every_scenario_erroring_is_all_failed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        _fake_runs(monkeypatch, {k: _record(k, err="boom") for k in keys})
        code = main_with(monkeypatch, tmp_path, ["--scenarios", ",".join(ids)])
        assert code == EXIT_ALL_FAILED

    def test_repeats_produce_one_durable_record_each(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = _three_ids()[:1]
        keys = [sim.record_id(ids[0], r) for r in (1, 2, 3)]
        _fake_runs(monkeypatch, {k: _record(k) for k in keys})

        code = main_with(
            monkeypatch, tmp_path, ["--scenarios", ids[0], "--repeats", "3"]
        )

        assert code == EXIT_OK
        assert set(load_records(tmp_path / "out", shape=sim.SIMULATION_CAMPAIGN)) == set(
            keys
        )
        # Three repeats clear the bar, so no warning is printed.
        assert "Judge noise mandates repeat runs" not in capsys.readouterr().out

    def test_a_single_repeat_campaign_prints_the_warning(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        ids = _three_ids()[:1]
        _fake_runs(monkeypatch, {sim.record_id(ids[0], 1): _record(sim.record_id(ids[0], 1))})
        main_with(monkeypatch, tmp_path, ["--scenarios", ids[0]])
        assert "Judge noise mandates repeat runs" in capsys.readouterr().out

    def test_an_unknown_scenario_id_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        with pytest.raises(SystemExit, match="Unknown scenario IDs: nope"):
            main_with(monkeypatch, tmp_path, ["--scenarios", "nope"])

    def test_the_rebuilt_summary_covers_the_whole_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # ADR 0050: summaries derive from what is on disk, so a subset
        # re-run cannot publish itself as a whole campaign.
        ids = _three_ids()
        keys = [sim.record_id(i, 1) for i in ids]
        out = tmp_path / "out"
        for key in keys[:2]:
            persist_record(out, _record(key), shape=sim.SIMULATION_CAMPAIGN)
        _fake_runs(monkeypatch, {keys[2]: _record(keys[2])})

        main_with(
            monkeypatch, tmp_path, ["--scenarios", ids[2], "--resume"]
        )

        rows = [
            json.loads(line)
            for line in (out / "summary.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert {row["record_id"] for row in rows} == set(keys)


class TestJudgedOutcomesReachTheSummary:
    def test_a_real_campaign_emits_judged_outcomes_in_summary_jsonl(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # THE c4 END-TO-END CHECK: the real session graph in mock mode,
        # judges canned rather than called, and the judged outcomes
        # landing in `summary.jsonl` beside the cost split. `--judges`
        # still demands a ceiling, which is why the budget flag is here
        # on a campaign that will spend nothing.
        _patch_settings(monkeypatch, _settings(tmp_path))
        _forbid_client(monkeypatch)

        def _canned(**kwargs: Any) -> dict[str, Any]:
            if _is_shame_judge(kwargs):
                return _shame_free_response()
            return {
                "score": 0.75,
                "section_ordering": {"score": 0.8, "reason": "opens on the intro"},
                "time_budget": {"score": 0.9, "reason": "one section fits"},
                "check_placement": {"score": 0.5, "reason": "one check"},
                "downscope_honesty": {"score": 1.0, "reason": "states the cut"},
                "summary": "Honest downscoped plan.",
            }

        monkeypatch.setattr(metrics_module, "call_llm_json", _canned)
        out = tmp_path / "out"

        code = sim.main(
            [
                "--scenarios", "engineer-transformer-time-poor",
                "--judges",
                "--max-budget-usd", "5",
                "--output-dir", str(out),
            ]
        )

        assert code == EXIT_OK
        rows = [
            json.loads(line)
            for line in (out / "summary.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert len(rows) == 1
        row = rows[0]
        # Judged outcomes: both rubric scores and both deterministic ones.
        assert row["shame_free_score"] == 0.95
        assert row["plan_coherence"] == 0.75
        assert row["shame_free"] is True
        assert row["downscope_honest"] is True
        assert row["progress_events_evidence_linked"] is True
        assert row["metrics_error"] is None
        # The three-payer cost split is present and separate, and the
        # session graph spent nothing because mock mode is the point.
        for field in (
            "cost_usd",
            "llm_calls",
            "learner_cost_usd",
            "judge_cost_usd",
            "judge_llm_calls",
            "total_cost_usd",
        ):
            assert field in row
        assert row["cost_usd"] == 0.0
        assert row["total_cost_usd"] == 0.0
        # The full record keeps the judges' own output for audit.
        record = load_records(out, shape=sim.SIMULATION_CAMPAIGN)[
            "engineer-transformer-time-poor.r1"
        ]
        assert record["metrics"]["session_plan_coherence"]["downscope_honesty"][
            "score"
        ] == 1.0
        assert record["scoring_sec"] is not None


class TestCampaignShapeIsolation:
    def test_the_research_campaign_layout_is_unchanged(self) -> None:
        # The `CampaignShape` parameterization must leave `runner.py`'s
        # own behaviour alone: its tests are untouched, and its defaults
        # still name the research layout.
        from src.eval.runner import RESEARCH_CAMPAIGN

        assert RESEARCH_CAMPAIGN.records_dirname == "queries"
        assert RESEARCH_CAMPAIGN.id_field == "query_id"
        assert sim.SIMULATION_CAMPAIGN.records_dirname == "scenarios"
        assert sim.SIMULATION_CAMPAIGN.id_field == "record_id"

    def test_the_two_campaigns_do_not_share_a_directory(self, tmp_path: Path) -> None:
        persist_record(tmp_path, _record("novice-transformer-baseline.r1"),
                       shape=sim.SIMULATION_CAMPAIGN)
        assert (tmp_path / "scenarios").is_dir()
        assert not (tmp_path / "queries").exists()
        assert load_records(tmp_path) == {}
