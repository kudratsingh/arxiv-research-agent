"""Observability primitives — structured logging, run-scoped context, cost tracking.

Public surface:

    from src.observability import (
        get_logger, bind_run_id, current_run_id,
        start_cost_tracking, current_costs, record_llm_call,
    )

See ADR 0012 for design rationale.
"""

from src.observability.costs import (
    PRICES_USD_PER_MILLION,
    RunCosts,
    current_costs,
    estimate_cost,
    record_llm_call,
    start_cost_tracking,
)
from src.observability.logging import (
    JsonFormatter,
    bind_run_id,
    current_run_id,
    get_logger,
    propagate_run_context,
    reset_run_id,
)

__all__ = [
    "JsonFormatter",
    "PRICES_USD_PER_MILLION",
    "RunCosts",
    "bind_run_id",
    "current_costs",
    "current_run_id",
    "estimate_cost",
    "get_logger",
    "propagate_run_context",
    "record_llm_call",
    "reset_run_id",
]
