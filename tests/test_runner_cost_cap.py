"""Runner-level cost cap (ADR 0033).

The supervisor loop has its own `max_cost_usd` short-circuit, but the
fixed-DAG path has none. The runner's `on_node` callback is the one
place both shapes flow through, so the enforcement lives there.
"""

from __future__ import annotations

import pytest

from src.api.runner import CostBudgetExceeded, _enforce_cost_cap
from src.observability.costs import RunCosts

pytestmark = pytest.mark.unit


def test_under_cap_does_not_raise() -> None:
    costs = RunCosts()
    costs.record("claude-sonnet-4-6", input_tokens=100, output_tokens=50, cost_usd=0.10)
    _enforce_cost_cap(costs, cap_usd=2.00)  # no raise


def test_at_or_above_cap_raises_with_context() -> None:
    costs = RunCosts()
    costs.record(
        "claude-opus-4-7", input_tokens=1000, output_tokens=1000, cost_usd=1.50
    )
    costs.record(
        "claude-opus-4-7", input_tokens=1000, output_tokens=1000, cost_usd=0.55
    )
    with pytest.raises(CostBudgetExceeded) as exc_info:
        _enforce_cost_cap(costs, cap_usd=2.00)
    exc = exc_info.value
    assert exc.cap_usd == 2.00
    assert exc.spent_usd == pytest.approx(2.05, abs=0.01)
    assert "2.05" in str(exc) or "2.0500" in str(exc)
    assert "2.00" in str(exc)


def test_cap_at_boundary_raises() -> None:
    """Boundary: spend exactly at the cap must abort before the NEXT
    node runs. Otherwise a single expensive call sits right at the
    limit and the next node happily blows past it."""
    costs = RunCosts()
    costs.record(
        "claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0, cost_usd=2.00
    )
    with pytest.raises(CostBudgetExceeded):
        _enforce_cost_cap(costs, cap_usd=2.00)


def test_zero_cost_never_raises() -> None:
    costs = RunCosts()
    _enforce_cost_cap(costs, cap_usd=0.01)  # empty accumulator, no raise
