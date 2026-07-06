"""Per-run LLM cost tracking.

Wraps every Claude call with a lightweight accumulator so main / runner
can log a per-run cost summary and the nightly regression diff can
catch cost creep. Uses a `ContextVar` for per-run isolation so
concurrent workflows in a future multi-tenant server won't share
counters.

Prices reflect Anthropic's public list price at project inception; a
follow-up will read them from `settings` so we can override without a
code change. Missing model prices fall back to Sonnet and log a
warning — we want to catch a stale price table, not silently under-
report cost.

See ADR 0012 for design rationale.
"""

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from src.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Price table — USD per 1M tokens (input / output)
# ---------------------------------------------------------------------------

PRICES_USD_PER_MILLION: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
}

_FALLBACK_MODEL = "claude-sonnet-4-6"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return the estimated cost in USD for a completed LLM call.

    Falls back to Sonnet pricing when the model isn't in the table (and
    logs a warning). This prevents silent under-reporting when we
    onboard a new model without updating the table.
    """
    prices = PRICES_USD_PER_MILLION.get(model)
    if prices is None:
        log.warning(
            "unknown_model_pricing_fallback",
            extra={"model": model, "fallback": _FALLBACK_MODEL},
        )
        prices = PRICES_USD_PER_MILLION[_FALLBACK_MODEL]
    return (
        input_tokens * prices["input"] / 1_000_000
        + output_tokens * prices["output"] / 1_000_000
    )


# ---------------------------------------------------------------------------
# Per-run accumulator
# ---------------------------------------------------------------------------


@dataclass
class RunCosts:
    """Cumulative LLM usage for a single run.

    Thread-safe: reader fans out per-paper LLM calls across a pool, and
    every worker calls `record` on the same instance. The lock is
    per-instance so unrelated runs don't contend.
    """

    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    call_count: int = 0
    per_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self, model: str, input_tokens: int, output_tokens: int, cost_usd: float
    ) -> None:
        with self._lock:
            self.total_cost_usd += cost_usd
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.call_count += 1

            slot = self.per_model.setdefault(
                model,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "call_count": 0,
                },
            )
            slot["input_tokens"] += input_tokens
            slot["output_tokens"] += output_tokens
            slot["cost_usd"] += cost_usd
            slot["call_count"] += 1

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot for log / summary emission."""
        with self._lock:
            return {
                "total_cost_usd": round(self.total_cost_usd, 6),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "call_count": self.call_count,
                "per_model": {
                    model: {
                        "input_tokens": slot["input_tokens"],
                        "output_tokens": slot["output_tokens"],
                        "cost_usd": round(slot["cost_usd"], 6),
                        "call_count": slot["call_count"],
                    }
                    for model, slot in self.per_model.items()
                },
            }


_current_costs: ContextVar[RunCosts | None] = ContextVar(
    "current_costs", default=None
)


def current_costs() -> RunCosts | None:
    """Return the run's cost accumulator, or `None` when no run is active."""
    return _current_costs.get()


def start_cost_tracking() -> RunCosts:
    """Create a fresh accumulator and bind it to the current context.

    Idempotent per context — calling twice returns two independent
    accumulators (the second replaces the first for subsequent
    `current_costs()` reads).
    """
    costs = RunCosts()
    _current_costs.set(costs)
    return costs


def record_llm_call(
    model: str, input_tokens: int, output_tokens: int
) -> None:
    """Record a completed LLM call against the current run's accumulator.

    Silently no-ops when no accumulator is bound so unit tests /
    ad-hoc scripts calling `call_llm` without opening a run don't
    crash. Emits a structured log line for every call so eval /
    downstream processors can trace cost per query per agent.
    """
    cost = estimate_cost(model, input_tokens, output_tokens)
    log.info(
        "llm_call",
        extra={
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        },
    )
    costs = _current_costs.get()
    if costs is not None:
        costs.record(model, input_tokens, output_tokens, cost)
