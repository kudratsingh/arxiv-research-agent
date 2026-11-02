"""Measured fixed-graph costing: real routes, revision edges and worst-pass caps.

Price rows are synthetic arithmetic fixtures, never current provider quotes.
All gateway/agent responses used below are injected; no provider is constructed.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.calibration.estimate import (
    MeasuredRoleTokens,
    reestimate_from_measurements,
    reestimate_measured_tokens,
    render,
)
from src.config import Settings

pytestmark = pytest.mark.unit
ROLES = (
    "planner",
    "reader",
    "synthesizer",
    "critic",
    "completeness",
    "faithfulness",
    "retrieval_recall",
)
PRICES = {"claude-sonnet-4-6": {"input": 1.0, "output": 2.0}}
VERIFIED = "2026-09-05"


def compact():
    return {
        role: {
            "min": {"input": 10, "output": 2},
            "median": {"input": 20, "output": 4},
            "max": {"input": 30, "output": 6},
        }
        for role in ROLES
    }


def estimate(roles=None, **kwargs):
    cfg = kwargs.pop("config", Settings(_env_file=None, max_papers=3, max_iterations=3))
    return reestimate_from_measurements(
        compact() if roles is None else roles,
        config=cfg,
        revision_count=kwargs.pop("revision_count", 0),
        episodes=kwargs.pop("episodes", 2),
        prices=kwargs.pop("prices", PRICES),
        prices_last_verified=kwargs.pop("prices_last_verified", VERIFIED),
        **kwargs,
    )


def calls(lines):
    return {line.label: line.calls for line in lines}


def test_full_table_retains_quantiles_and_rederives_expected_and_both_caps():
    roles = compact()
    roles["planner"] = MeasuredRoleTokens(
        input_min=10, input_median=20, input_max=30, output_min=2, output_median=4, output_max=6
    )
    result = estimate(roles, revision_count=2)
    assert calls(result.judge_lines) == {
        "planner": 6,
        "reader": 18,
        "synthesizer": 6,
        "critic": 6,
        "completeness": 2,
        "faithfulness": 2,
        "retrieval_recall": 2,
    }
    assert calls(result.worst_case_lines) == {
        "planner": 6,
        "reader": 18,
        "synthesizer": 12,
        "critic": 6,
        "completeness": 2,
        "faithfulness": 2,
        "retrieval_recall": 2,
    }
    # Expected: 42 calls at20/4 tokens and synthetic1/2 USD/M = .001176.
    # Worst: 48 calls at30/6 = .002016; x1.25 = .002520.
    assert result.model_cost_usd(PRICES) == Decimal("0.001176")
    assert result.per_episode_cap_usd == "0.001260"
    assert result.campaign_cap_usd == "0.002520"
    assert result.measured_roles["planner"] == roles["planner"]
    assert result.measured_roles["critic"].output_min == 2
    assert result.maximum_critic_passes == 3
    assert result.measured_revision_targets == ("planner", "planner")
    assert all(line.input_tokens_per_call == 20 for line in result.judge_lines)
    assert all(line.input_tokens_per_call == 30 for line in result.worst_case_lines)
    assert result.requires_repricing and not result.campaign_started


@pytest.mark.parametrize(
    "revisions,expected", [(0, (2, 6, 2, 2)), (1, (4, 12, 4, 4)), (2, (6, 18, 6, 6))]
)
def test_zero_one_and_worst_revisions_count_initial_critic_and_normal_synthesis(
    revisions, expected
):
    result = estimate(revision_count=revisions)
    assert tuple(calls(result.judge_lines)[role] for role in ROLES[:4]) == expected
    assert all(calls(result.judge_lines)[role] == 2 for role in ROLES[4:])
    # A lucky no-revision sample never reduces the frozen worst-pass envelope.
    assert result.campaign_cap_usd == "0.002520"


@pytest.mark.parametrize(
    "target,expected",
    [("planner", (4, 12, 4, 4)), ("search", (2, 12, 4, 4)), ("synthesizer", (2, 6, 4, 4))],
)
def test_revision_targets_follow_actual_fixed_graph_edges(target, expected, monkeypatch):
    from langgraph.graph import StateGraph

    from src.graph import workflow
    from src.graph.state import ResearchState

    observed = Counter()

    def planner(state):
        observed["planner"] += 1
        return {}

    def search(state):
        return {}

    def reader(state):
        observed["reader"] += 3
        return {}

    def synthesizer(state):
        observed["synthesizer"] += 1
        return {}

    def critic(state):
        observed["critic"] += 1
        iteration = state.get("iteration", 0)
        return {
            "iteration": iteration + 1,
            "revision_needed": iteration == 0,
            "revision_target": target if iteration == 0 else "",
        }

    for role, agent in (
        ("planner", planner),
        ("search", search),
        ("reader", reader),
        ("synthesizer", synthesizer),
        ("critic", critic),
    ):
        monkeypatch.setattr(workflow, role + "_agent", agent)
    graph = StateGraph(ResearchState)
    workflow._build_fixed_pipeline(graph, lambda name, agent: agent)
    graph.compile().invoke(
        {"query": "Synthetic fixed-graph counting", "iteration": 0, "messages": []}
    )
    result = estimate(revision_count=1, revision_targets=(target,))
    assert tuple(calls(result.judge_lines)[role] for role in ROLES[:4]) == expected
    assert tuple(observed[role] * 2 for role in ROLES[:4]) == expected


def test_actual_critic_iteration_ceiling_is_total_passes(monkeypatch):
    from src.agents import critic

    cfg = Settings(_env_file=None, use_mock_data=False, max_iterations=3)
    monkeypatch.setattr(critic, "settings", cfg)
    monkeypatch.setattr(
        critic,
        "call_llm_json",
        lambda **kwargs: {
            "average_score": 0.1,
            "revision_needed": True,
            "revision_target": "planner",
        },
    )
    state = {
        "query": "Synthetic",
        "paper_analyses": [],
        "draft_report": "Synthetic",
        "iteration": 0,
    }
    assert critic.critic_agent(state)["revision_needed"]
    final = critic.critic_agent({**state, "iteration": 2})
    assert not final["revision_needed"] and final["iteration"] == 3


def test_settings_resolve_actual_role_and_judge_models():
    cfg = Settings(
        _env_file=None,
        max_papers=3,
        max_iterations=3,
        planner_model="claude-opus-4-6",
        reader_model="claude-haiku-4-5",
        critic_model="claude-haiku-4-5",
        eval_judge_model="claude-opus-4-6",
    )
    prices = {
        **PRICES,
        "claude-haiku-4-5": {"input": 0.5, "output": 1.0},
        "claude-opus-4-6": {"input": 3.0, "output": 6.0},
    }
    result = estimate(config=cfg, prices=prices)
    assert {line.label: line.model_id for line in result.judge_lines} == {
        "planner": cfg.model_for("planner"),
        "reader": cfg.model_for("reader"),
        "synthesizer": cfg.model_for("synthesizer"),
        "critic": cfg.model_for("critic"),
        **{role: cfg.eval_judge_model for role in ROLES[4:]},
    }
    # Hand-priced role arithmetic: per episode expected420µ, worst1260µ.
    assert result.model_cost_usd(prices) == Decimal("0.000840")
    assert result.per_episode_cap_usd == "0.001575"
    assert result.campaign_cap_usd == "0.003150"
    with pytest.raises(KeyError):
        estimate(config=cfg, prices=PRICES)


def test_one_pass_ceiling_and_upward_rounding_do_not_erase_tiny_caps():
    result = estimate(config=Settings(_env_file=None, max_iterations=1, max_papers=3))
    assert result.per_episode_cap_usd == "0.000525"
    assert calls(result.worst_case_lines)["synthesizer"] == 4
    tiny = estimate(
        episodes=3, prices={"claude-sonnet-4-6": {"input": 0.0000001, "output": 0.0000002}}
    )
    assert tiny.per_episode_cap_usd == "0.000001"
    assert tiny.campaign_cap_usd == "0.000003"


def test_min_median_max_and_stale_estimate_provenance_render_and_roundtrip():
    result = estimate(prices_last_verified="2020-01-01")
    assert result.requires_repricing and "ESTIMATE" in result.note
    assert result.prices_last_verified == "2020-01-01"
    wire = result.model_dump_json()
    assert result.__class__.model_validate_json(wire) == result
    rendered = render(result, today=date(2026, 11, 2))
    assert "cap basis: observed-max tokens" in rendered
    assert "min/median/max input 10/20/30, output 2/4/6" in rendered
    assert "STALE PRICES" in rendered
    assert "One in-flight reader fan-out" in rendered


def test_missing_critic_and_partial_quantiles_never_fall_back_to_zero():
    roles = compact()
    roles.pop("critic")
    with pytest.raises(KeyError, match="critic"):
        estimate(roles)
    roles = compact()
    roles["planner"]["median"].pop("input")
    with pytest.raises(KeyError):
        estimate(roles)
    flat = {key: 1 for key in ("input_min", "input_max", "output_min", "output_max")}
    roles = compact()
    roles["planner"] = flat
    with pytest.raises(KeyError):
        estimate(roles)


def test_supported_flat_compact_aliases_and_default_configuration(monkeypatch):
    import src.config

    cfg = Settings(_env_file=None, max_iterations=3, max_papers=3)
    monkeypatch.setattr(src.config, "settings", cfg)
    roles = compact()
    roles["planner"] = {
        "input_min": 10,
        "median_input": 20,
        "input_max": 30,
        "output_min": 2,
        "median_output": 4,
        "output_max": 6,
    }
    roles["reader"] = {
        q: {direction + "_tokens": count for direction, count in row.items()}
        for q, row in roles["reader"].items()
    }
    first = reestimate_measured_tokens(
        roles,
        revision_count=0,
        max_papers=3,
        judge_model=cfg.eval_judge_model,
        prices=PRICES,
        prices_last_verified=VERIFIED,
    )
    assert first.judge_lines[0].calls == 60
    monkeypatch.setattr("src.calibration.estimate.current_price_table", lambda: (PRICES, VERIFIED))
    assert reestimate_from_measurements(roles, revision_count=0).model_cost_usd(
        PRICES
    ) == first.model_cost_usd(PRICES)
    full = {
        role: MeasuredRoleTokens(
            input_min=1, input_median=2, input_max=3, output_min=1, output_median=2, output_max=3
        ).model_dump()
        for role in ROLES
    }
    assert estimate(full).measured_roles["reader"].input_median == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"revision_count": -1},
        {"revision_count": 3},
        {"revision_count": 1.5},
        {"episodes": 0},
        {"max_papers": 0},
        {"revision_targets": ("search",)},
        {"revision_count": 1, "revision_targets": ("reader",)},
        {"max_papers": 4},
        {"judge_model": "claude-haiku-4-5"},
    ],
)
def test_invalid_counts_targets_or_frozen_overrides_refuse(kwargs):
    with pytest.raises(ValueError):
        estimate(**kwargs)


@pytest.mark.parametrize("flag", ["enable_supervisor", "enable_verifier", "enable_query_refiner"])
def test_unsupported_graph_roles_refuse(flag):
    cfg = Settings(_env_file=None, max_papers=3).model_copy(update={flag: True})
    with pytest.raises(ValueError, match="only the fixed legacy graph"):
        estimate(config=cfg)


def test_unsupported_policy_controller_unknown_roles_bad_prices_and_shapes():
    for change in (
        {"research_policy": "fixed_verify_repair"},
        {"compute_controller": "deterministic"},
    ):
        cfg = Settings(_env_file=None, max_papers=3).model_copy(update=change)
        with pytest.raises(ValueError, match="only the fixed legacy graph"):
            estimate(config=cfg)
    with pytest.raises(ValueError, match="unmodeled measured roles"):
        estimate({**compact(), "supervisor": compact()["critic"]})
    for rate in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="finite non-negative"):
            estimate(prices={"claude-sonnet-4-6": {"input": rate, "output": 1}})
    for wrong in (1, {"input": 1.1, "output": 1}, {"input": True, "output": 1}):
        roles = compact()
        roles["planner"]["median"] = wrong
        with pytest.raises(ValueError):
            estimate(roles)
    with pytest.raises(ValidationError):
        MeasuredRoleTokens(
            input_min=-1, input_median=2, input_max=3, output_min=1, output_median=2, output_max=3
        )
    with pytest.raises(ValueError, match="min <= median"):
        MeasuredRoleTokens(
            input_min=3, input_median=2, input_max=4, output_min=1, output_median=1, output_max=1
        )
    with pytest.raises(ValueError, match="supplied together"):
        reestimate_from_measurements(compact(), revision_count=0, prices=PRICES)
