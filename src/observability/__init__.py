"""Observability primitives — structured logging, run-scoped context, cost tracking, metrics.

Public surface:

    from src.observability import (
        get_logger, bind_run_id, current_run_id,
        start_cost_tracking, current_costs, record_llm_call,
        configure_metrics, register_runtime_gauges, shutdown_metrics,
    )

See ADR 0012 for the logging + cost core, ADR 0013 for tracing,
ADR 0049 for the OTel metrics layer, and ADR 0051 for the spend
ceiling (`CostBudgetExceeded`, raised from `src.llm.call_llm` as well
as from the API runner) and the price-coverage check
(`unpriced_models`).
"""

from src.observability.costs import (
    PRICES_USD_PER_MILLION,
    CostBudgetExceeded,
    RunCosts,
    current_costs,
    estimate_cost,
    record_llm_call,
    start_cost_tracking,
    unpriced_models,
)
from src.observability.logging import (
    JsonFormatter,
    bind_run_id,
    current_run_id,
    get_logger,
    propagate_run_context,
    redact_url,
    reset_run_id,
)
from src.observability.metrics import (
    configure_metrics,
    metrics_enabled,
    record_job_terminal,
    record_llm_usage,
    record_rate_limit_rejection,
    register_runtime_gauges,
    shutdown_metrics,
)
from src.observability.tracing import (
    configure_tracing,
    get_tracer,
    traced_node,
)

__all__ = [
    "JsonFormatter",
    "PRICES_USD_PER_MILLION",
    "CostBudgetExceeded",
    "RunCosts",
    "bind_run_id",
    "configure_metrics",
    "configure_tracing",
    "current_costs",
    "current_run_id",
    "estimate_cost",
    "get_logger",
    "get_tracer",
    "metrics_enabled",
    "propagate_run_context",
    "record_job_terminal",
    "record_llm_call",
    "record_llm_usage",
    "record_rate_limit_rejection",
    "redact_url",
    "register_runtime_gauges",
    "reset_run_id",
    "shutdown_metrics",
    "start_cost_tracking",
    "traced_node",
    "unpriced_models",
]
