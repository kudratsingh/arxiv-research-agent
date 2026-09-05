"""Observability primitives — structured logging, run-scoped context, cost tracking, metrics.

Public surface:

    from src.observability import (
        get_logger, bind_run_id, current_run_id,
        bind_context, current_context, hash_principal,
        start_cost_tracking, current_costs, record_llm_call,
        configure_metrics, register_runtime_gauges, shutdown_metrics,
    )

See ADR 0012 for the logging + cost core, ADR 0013 for tracing,
ADR 0049 for the OTel metrics layer, ADR 0051 for the spend
ceiling (`CostBudgetExceeded`, raised from `src.llm.call_llm` as well
as from the API runner) and the price-coverage check
(`unpriced_models`), ADR 0067 for the correlation context
(`RequestContext`, `bind_context`, `hash_principal`) and the log
contract (`KNOWN_EVENTS`, `ALLOWED_EXTRA_KEYS`, `redact_text`), and
ADR 0066 for the OpenTelemetry GenAI semantic conventions — the span
helpers (`workflow_span`, `agent_span`, `tool_span`, `llm_span`), the
trace-continuity pair (`inject_trace_context`,
`attached_trace_context`) and the conventional record helpers.

Every `gen_ai.*` name those emit is a constant in
`src.observability.semconv`, which is deliberately *not* re-exported
here: a conventional attribute name should be reached for from the
name table explicitly, not arrived at by autocomplete from a package
that also exports thirty other things.
"""

from src.observability.context import (
    SERVICE_NAME,
    SERVICE_VERSION,
    RequestContext,
    attach_context,
    bind_context,
    clear_context,
    context_fields,
    current_context,
    hash_principal,
    principal_salt_is_ephemeral,
    reset_context,
)
from src.observability.costs import (
    PRICES_USD_PER_MILLION,
    CostBudgetExceeded,
    RunCosts,
    bind_effective_cost_cap,
    current_costs,
    effective_cost_cap,
    estimate_cost,
    record_llm_call,
    reset_effective_cost_cap,
    start_cost_tracking,
    unpriced_models,
)
from src.observability.logging import (
    ALLOWED_EXTRA_KEYS,
    KNOWN_EVENTS,
    USER_CONTENT_KEYS,
    JsonFormatter,
    bind_run_id,
    content_capture_enabled,
    current_run_id,
    dropped_extra_key_counts,
    get_logger,
    propagate_run_context,
    redact_text,
    redact_url,
    reset_dropped_extra_key_counts,
    reset_run_id,
)
from src.observability.metrics import (
    DEGRADATION_RUNG_CACHE_STALE,
    DEGRADATION_RUNG_STREAMING_PARTIAL,
    DEGRADATION_RUNG_WEAKENED_GUARANTEE,
    configure_metrics,
    metrics_enabled,
    record_agent_invocation,
    record_degradation_rung,
    record_genai_client_call,
    record_job_terminal,
    record_llm_usage,
    record_rate_limit_rejection,
    record_tool_execution,
    record_workflow_invocation,
    register_runtime_gauges,
    shutdown_metrics,
)
from src.observability.tracing import (
    agent_span,
    attached_trace_context,
    configure_tracing,
    get_tracer,
    inject_trace_context,
    llm_span,
    note_inference_call,
    shutdown_tracing,
    tool_span,
    trace_sample_ratio,
    traced_node,
    traced_tool,
    workflow_span,
)

__all__ = [
    "ALLOWED_EXTRA_KEYS",
    "DEGRADATION_RUNG_CACHE_STALE",
    "DEGRADATION_RUNG_STREAMING_PARTIAL",
    "DEGRADATION_RUNG_WEAKENED_GUARANTEE",
    "JsonFormatter",
    "KNOWN_EVENTS",
    "PRICES_USD_PER_MILLION",
    "SERVICE_NAME",
    "SERVICE_VERSION",
    "USER_CONTENT_KEYS",
    "CostBudgetExceeded",
    "RequestContext",
    "RunCosts",
    "attach_context",
    "bind_context",
    "bind_effective_cost_cap",
    "bind_run_id",
    "clear_context",
    "configure_metrics",
    "configure_tracing",
    "content_capture_enabled",
    "context_fields",
    "current_context",
    "current_costs",
    "current_run_id",
    "dropped_extra_key_counts",
    "estimate_cost",
    "effective_cost_cap",
    "get_logger",
    "get_tracer",
    "hash_principal",
    "metrics_enabled",
    "principal_salt_is_ephemeral",
    "propagate_run_context",
    "record_degradation_rung",
    "record_job_terminal",
    "record_llm_call",
    "reset_context",
    "reset_dropped_extra_key_counts",
    "reset_effective_cost_cap",
    "record_llm_usage",
    "record_rate_limit_rejection",
    "redact_text",
    "redact_url",
    "register_runtime_gauges",
    "reset_run_id",
    "shutdown_metrics",
    "start_cost_tracking",
    "traced_node",
    "agent_span",
    "attached_trace_context",
    "inject_trace_context",
    "llm_span",
    "note_inference_call",
    "record_agent_invocation",
    "record_genai_client_call",
    "record_tool_execution",
    "record_workflow_invocation",
    "shutdown_tracing",
    "tool_span",
    "trace_sample_ratio",
    "traced_tool",
    "workflow_span",
    "unpriced_models",
]
