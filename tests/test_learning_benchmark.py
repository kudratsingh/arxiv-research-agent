"""Invariant tests for the guided-read learning benchmark.

The research benchmark's invariants are pinned by
`tests/test_benchmark_queries.py` — no duplicate ids, no empty fields,
ids are stable slugs — so an accidental edit fails loudly instead of
silently skewing results. This file does the same job for the learning
benchmark, which needs more: a scenario is a persona, a paper, and a
script, and the three have to agree with each other.

The heavy lifting lives in `learning_benchmark.validate_benchmark()` so
WO-W09's judges and WO-W10's simulator can run the same checks on a
scenario subset they were handed. The tests here assert the shipped set
passes, then poke individual invariants with deliberately broken copies
so a validator that silently stopped checking would fail.
"""

import copy
import re
from pathlib import Path

from src.eval.learning_benchmark import (
    ASSESSMENT_OUTCOMES,
    BENCHMARK_PAPERS,
    LEARNER_TURN_INTENTS,
    LEARNING_SCENARIOS,
    PERSONAS,
    PHASE_W_PROGRESS_EVENT_KINDS,
    SCRIPT_KINDS,
    LearningScenario,
    get_paper,
    get_persona,
    get_scenario,
    get_scenarios,
    scenario_order,
    validate_benchmark,
    validate_scenario,
)
from src.tools.chunker import SECTION_HEADERS

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _broken(scenario_id: str) -> LearningScenario:
    """A deep copy of a shipped scenario, safe to mutate in a test."""
    original = get_scenario(scenario_id)
    assert original is not None, scenario_id
    return copy.deepcopy(original)


class TestBenchmarkIsValid:
    def test_shipped_benchmark_has_no_problems(self) -> None:
        # The single assertion that has to hold for every other card in
        # Track B to mean anything.
        assert validate_benchmark() == []

    def test_every_shipped_scenario_validates_individually(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            assert validate_scenario(scenario) == [], scenario["scenario_id"]


class TestScenarioSetInvariants:
    def test_scenario_count_is_in_the_card_range(self) -> None:
        # WO-W08 sizes the set at ~12-15 scenarios.
        assert 12 <= len(LEARNING_SCENARIOS) <= 15

    def test_scenario_ids_are_unique_kebab_case_slugs(self) -> None:
        ids = [s["scenario_id"] for s in LEARNING_SCENARIOS]
        assert len(ids) == len(set(ids))
        for scenario_id in ids:
            assert SLUG_PATTERN.match(scenario_id), scenario_id

    def test_persona_and_paper_ids_are_stable_slugs(self) -> None:
        for persona in PERSONAS:
            assert SLUG_PATTERN.match(persona["persona_id"]), persona["persona_id"]
        for paper in BENCHMARK_PAPERS:
            # Paper ids are canonical `arxiv:<id>` keys, not slugs.
            assert paper["paper_id"].startswith("arxiv:"), paper["paper_id"]

    def test_required_fields_are_non_empty(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            assert scenario["scenario_id"].strip(), scenario
            assert scenario["persona_id"].strip(), scenario
            assert scenario["paper_id"].strip(), scenario
            assert scenario["notes"].strip(), scenario["scenario_id"]
            assert scenario["turns"], scenario["scenario_id"]
            for turn in scenario["turns"]:
                assert turn["text"].strip(), (scenario["scenario_id"], turn)

    def test_every_turn_intent_and_script_kind_is_known(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            assert scenario["script_kind"] in SCRIPT_KINDS, scenario["scenario_id"]
            for turn in scenario["turns"]:
                assert turn["intent"] in LEARNER_TURN_INTENTS, turn


class TestCoverage:
    """WO-W08 c3: at least one scenario per persona, one time-poor, one adversarial."""

    def test_every_persona_has_a_scenario(self) -> None:
        for persona in PERSONAS:
            assert get_scenarios(persona_id=persona["persona_id"]), persona[
                "persona_id"
            ]

    def test_all_three_planned_personas_are_present(self) -> None:
        # 01 §7.2's three, by id.
        expected = {"novice-undergrad", "career-switcher", "time-poor-engineer"}
        assert {p["persona_id"] for p in PERSONAS} == expected

    def test_a_time_poor_script_exists(self) -> None:
        time_poor = get_scenarios(script_kind="time_poor")
        assert time_poor
        for scenario in time_poor:
            persona = get_persona(scenario["persona_id"])
            assert persona is not None
            # "Time-poor" means declaring less than the standing budget,
            # not merely having a small one.
            assert (
                scenario["declared_minutes_today"]
                < persona["time_budget_min_per_day"]
            )
            assert scenario["expectations"]["requires_downscope_statement"]

    def test_an_adversarial_script_exists_and_plants_a_probe(self) -> None:
        adversarial = get_scenarios(script_kind="adversarial")
        assert adversarial
        for scenario in adversarial:
            probe = scenario["expectations"]["injection_probe"]
            assert probe
            assert any(probe in turn["text"] for turn in scenario["turns"])

    def test_injection_probes_are_unique_across_scenarios(self) -> None:
        # Two scenarios sharing a canary would let a leak in one hide
        # behind the other's expected occurrence.
        probes = [
            s["expectations"]["injection_probe"]
            for s in LEARNING_SCENARIOS
            if s["expectations"]["injection_probe"]
        ]
        assert len(probes) == len(set(probes))

    def test_every_flagship_paper_is_exercised(self) -> None:
        used = {s["paper_id"] for s in LEARNING_SCENARIOS}
        assert used == {p["paper_id"] for p in BENCHMARK_PAPERS}

    def test_an_unassessed_outcome_is_covered(self) -> None:
        # The honest-failure path has to be in the benchmark, or nothing
        # measures WO-W04 c2.
        outcomes = {
            s["expectations"]["expected_assessment"] for s in LEARNING_SCENARIOS
        }
        assert "unassessed" in outcomes
        assert outcomes <= ASSESSMENT_OUTCOMES


class TestPersonaHonesty:
    def test_personas_may_only_declare_skills(self) -> None:
        # A benchmark that handed the system a pre-baked `inferred`
        # skill would be measuring its own fiction (01 §1.2).
        for persona in PERSONAS:
            for skill in persona["declared_skills"]:
                assert skill["source"] == "declared", (persona["persona_id"], skill)
                assert skill["confidence"] == 1.0, (persona["persona_id"], skill)

    def test_preserved_skills_are_skills_the_persona_declared(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            persona = get_persona(scenario["persona_id"])
            assert persona is not None
            declared = {s["skill"] for s in persona["declared_skills"]}
            for skill_name in scenario["expectations"][
                "must_preserve_declared_skills"
            ]:
                assert skill_name in declared, (scenario["scenario_id"], skill_name)


class TestPaperGuidance:
    def test_section_names_come_from_the_chunker(self) -> None:
        # 02 §2.2 keys close-read/skim guidance to the sections the
        # existing chunker detects. If that vocabulary changes, this
        # benchmark should fail rather than drift.
        known = set(SECTION_HEADERS)
        for paper in BENCHMARK_PAPERS:
            for section in [
                *paper["close_read_sections"],
                *paper["skim_sections"],
            ]:
                assert section in known, (paper["paper_id"], section)

    def test_close_read_and_skim_do_not_overlap(self) -> None:
        for paper in BENCHMARK_PAPERS:
            assert not (
                set(paper["close_read_sections"]) & set(paper["skim_sections"])
            ), paper["paper_id"]

    def test_path_positions_form_a_reading_order(self) -> None:
        positions = [p["path_position"] for p in BENCHMARK_PAPERS]
        assert positions == list(range(1, len(BENCHMARK_PAPERS) + 1))


class TestExpectationsAreConsistent:
    def test_every_scenario_expects_a_session_completed_event(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            assert (
                "session_completed"
                in scenario["expectations"]["expected_progress_events"]
            ), scenario["scenario_id"]

    def test_only_phase_w_event_kinds_are_expected(self) -> None:
        # WO-W07 reserves the rest of the 01 §4.4 vocabulary for Phase L
        # and refuses it until a producer exists.
        for scenario in LEARNING_SCENARIOS:
            for kind in scenario["expectations"]["expected_progress_events"]:
                assert kind in PHASE_W_PROGRESS_EVENT_KINDS, (
                    scenario["scenario_id"],
                    kind,
                )

    def test_unassessed_scenarios_expect_no_assessment_event(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            expectations = scenario["expectations"]
            has_event = "assessment" in expectations["expected_progress_events"]
            if expectations["expected_assessment"] == "unassessed":
                assert not has_event, scenario["scenario_id"]
            else:
                assert has_event, scenario["scenario_id"]


class TestScriptShape:
    """WO-W08 c2: the scripts must be executable by WO-W10 unmodified."""

    def test_scripts_open_on_a_check_in(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            assert scenario["turns"][0]["intent"] == "check_in", scenario[
                "scenario_id"
            ]

    def test_scripts_close_unambiguously(self) -> None:
        # The simulator needs a stop condition it can recognise without
        # asking a model whether the session is over.
        for scenario in LEARNING_SCENARIOS:
            assert scenario["turns"][-1]["intent"] in {
                "explain_back",
                "end_session",
            }, scenario["scenario_id"]

    def test_turn_indices_are_dense_and_ordered(self) -> None:
        for scenario in LEARNING_SCENARIOS:
            indices = [t["turn_index"] for t in scenario["turns"]]
            assert indices == list(range(len(indices))), scenario["scenario_id"]


class TestValidatorCatchesBreakage:
    """The validator has to actually check things, not just return `[]`."""

    def test_unknown_persona_is_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["persona_id"] = "no-such-persona"
        assert any("unknown persona_id" in p for p in validate_scenario(scenario))

    def test_unknown_paper_is_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["paper_id"] = "arxiv:0000.00000"
        assert any("unknown paper_id" in p for p in validate_scenario(scenario))

    def test_out_of_order_turns_are_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["turns"][1]["turn_index"] = 7
        assert any("out of order" in p for p in validate_scenario(scenario))

    def test_a_script_that_never_closes_is_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["turns"][-1]["intent"] = "question"
        assert any("must close the session" in p for p in validate_scenario(scenario))

    def test_a_reserved_progress_event_is_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["expectations"]["expected_progress_events"] = [
            "session_completed",
            "assessment",
            "replan",
        ]
        assert any("Phase W does not write" in p for p in validate_scenario(scenario))

    def test_a_fabricated_grade_expectation_is_reported(self) -> None:
        # unassessed + an assessment event is exactly the combination
        # WO-W04 c2 forbids.
        scenario = _broken("novice-bert-off-topic-drift")
        scenario["expectations"]["expected_progress_events"] = [
            "session_completed",
            "assessment",
        ]
        assert any("must not expect" in p for p in validate_scenario(scenario))

    def test_an_unplanted_injection_probe_is_reported(self) -> None:
        scenario = _broken("switcher-rlhf-injection-in-explain-back")
        scenario["expectations"]["injection_probe"] = "NEVER_TYPED_ANYWHERE"
        assert any("appears in no turn" in p for p in validate_scenario(scenario))

    def test_a_silent_downscope_is_reported(self) -> None:
        scenario = _broken("engineer-transformer-time-poor")
        scenario["expectations"]["requires_downscope_statement"] = False
        assert any("downscope statement" in p for p in validate_scenario(scenario))

    def test_preserving_an_undeclared_skill_is_reported(self) -> None:
        scenario = _broken("novice-transformer-baseline")
        scenario["expectations"]["must_preserve_declared_skills"] = ["quantum-optics"]
        assert any("never declared" in p for p in validate_scenario(scenario))


class TestAccessors:
    def test_get_scenarios_returns_a_copy(self) -> None:
        result = get_scenarios()
        result.clear()
        assert LEARNING_SCENARIOS, "get_scenarios() must not expose the internal list"

    def test_filters_are_case_insensitive(self) -> None:
        assert get_scenarios(script_kind="TIME_POOR") == get_scenarios(
            script_kind="time_poor"
        )
        assert get_scenarios(persona_id="CAREER-SWITCHER") == get_scenarios(
            persona_id="career-switcher"
        )

    def test_filters_compose(self) -> None:
        both = get_scenarios(script_kind="adversarial", persona_id="career-switcher")
        assert both
        for scenario in both:
            assert scenario["script_kind"] == "adversarial"
            assert scenario["persona_id"] == "career-switcher"

    def test_unknown_filter_values_select_nothing(self) -> None:
        assert get_scenarios(script_kind="no-such-kind") == []
        assert get_scenarios(persona_id="no-such-persona") == []

    def test_lookups_return_none_when_absent(self) -> None:
        assert get_scenario("no-such-scenario") is None
        assert get_persona("no-such-persona") is None
        assert get_paper("arxiv:0000.00000") is None

    def test_scenario_order_sorts_unknown_ids_last(self) -> None:
        first = LEARNING_SCENARIOS[0]["scenario_id"]
        assert scenario_order(first) == (0, first)
        assert scenario_order("retired-scenario") == (
            len(LEARNING_SCENARIOS),
            "retired-scenario",
        )


class TestZeroSpend:
    """WO-W08: no LLM calls anywhere in this card, enforced structurally."""

    def test_benchmark_modules_reach_no_model_client(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "eval"
        forbidden = ("src.llm", "anthropic", "requests", "httpx")
        for name in ("learning_benchmark.py", "learning_fixtures.py"):
            source = (root / name).read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in source, (name, token)
