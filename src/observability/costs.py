"""Per-run LLM cost tracking.

Wraps every Claude call with a lightweight accumulator so main / runner
can log a per-run cost summary and the nightly regression diff can
catch cost creep. Uses a `ContextVar` for per-run isolation so
concurrent jobs in the API server (each binds its own accumulator in
`src.api.runner`) don't share counters.

Prices reflect Anthropic's public list price as of
`PRICES_LAST_VERIFIED`; a follow-up will read them from `settings` so
we can override without a code change. Missing model prices fall back
to Sonnet and log a warning — we want to catch a stale price table,
not silently under-report cost.

See ADR 0012 for design rationale and ADR 0044 for the price refresh
and coverage guarantee. ADR 0049 hangs the process-wide
`llm_cost_usd_total` / `llm_calls_total` metrics off the same
`record_llm_call` choke point: the per-run accumulator answers "what
did this run cost", the counters answer "what is this deployment
spending, by model", and neither can be derived from the other.

ADR 0051 moves `CostBudgetExceeded` here from `src.api.runner`. The
spend ceiling is now enforced in `src.llm.call_llm` as well as between
graph nodes, and the CLI / eval entry points must not import the API
layer to catch it — so the exception belongs next to the accumulator
it is raised against, not next to one of its raisers.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from src.config import Settings
from src.observability.logging import get_logger
from src.observability.metrics import record_llm_retries, record_llm_usage

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Price table — USD per 1M tokens (input / output)
# ---------------------------------------------------------------------------

# The date the rows below were last checked against Anthropic's
# published pricing. Bump this whenever the table is re-verified, even
# if no number changed — a visibly old date at review time is the
# tripwire for stale prices (ADR 0044). Prices are first-party API
# list prices; time-limited introductory promos (e.g. Sonnet 5's intro
# rate) are deliberately ignored so we over- rather than under-report.
PRICES_LAST_VERIFIED = "2026-08-20"

PRICES_USD_PER_MILLION: dict[str, dict[str, float]] = {
    # Frontier tier — $10 / $50. Above Opus pricing, so an operator who
    # routes one agent here and is priced at the Sonnet fallback would
    # be under-billed 3.3x, and `max_cost_usd` would let a $2 cap pass
    # ~$6.60 of real spend (ADR 0051).
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-mythos-5": {"input": 10.0, "output": 50.0},
    # Opus tier — $5 / $25 across the 4.5+ generations.
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    # Sonnet tier — $3 / $15.
    "claude-sonnet-5": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    # Haiku tier — $1 / $5. The dated id is the ADR 0021 recommended
    # override string; the bare alias covers operators who use the
    # canonical id instead.
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
}

_FALLBACK_MODEL = "claude-sonnet-4-6"

# Model ids already reported as unpriced. The fallback warning must fire
# once per model id per process, not once per call: the reader alone
# makes `max_papers` calls per pass, so an off-table model used to emit
# one WARNING per LLM call — hundreds a run — which is how a line that
# matters got lost in the lines that don't (ADR 0051). Guarded by a lock
# because the reader's fan-out records from a thread pool.
_unpriced_warned: set[str] = set()
_unpriced_lock = threading.Lock()


# Anthropic prompt-caching multipliers (see ADR 0022):
#   Cache read: 10% of the base input token price.
#   Cache write (creation): 125% of the base input token price
#     (25% premium on the first call that stores the cache).
# `input_tokens` from the API's `usage` reflects only the non-cached
# portion when caching is used, so the three token buckets are
# additive at billing time.
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = 1.25


def _warn_unpriced_model_once(model: str) -> None:
    """Emit the unpriced-model WARNING the first time `model` is seen.

    Returns silently on every later call for the same id. The warning
    names the fallback and the price file to edit, because the action it
    asks for is "add a row", not "investigate".
    """
    with _unpriced_lock:
        if model in _unpriced_warned:
            return
        _unpriced_warned.add(model)
    log.warning(
        "unknown_model_pricing_fallback",
        extra={
            "model": model,
            "fallback": _FALLBACK_MODEL,
            "prices_last_verified": PRICES_LAST_VERIFIED,
            "action": (
                "add a row to PRICES_USD_PER_MILLION in "
                "src/observability/costs.py — cost reporting AND "
                "max_cost_usd enforcement are wrong until you do"
            ),
        },
    )


def reset_unpriced_warnings() -> None:
    """Forget which models have already warned.

    Test seam only: the warn-once set is process-global, so a suite that
    asserts on the warning needs a way back to a clean slate without
    reaching into module internals.
    """
    with _unpriced_lock:
        _unpriced_warned.clear()


def resolved_model_ids(config: Settings) -> set[str]:
    """Return every model id `config` can actually route a call to.

    Per-agent routing (ADR 0021) is uniform: each `<agent>_model` field
    is either a model id or `""`, and empty means "use
    `anthropic_model`". So the ids a deployment can bill against are the
    base model plus every non-empty override — derived from the fields
    themselves rather than a hand-kept list, so a new agent's routing
    field is covered the day it is added.

    Args:
        config: The `Settings` instance to resolve. Takes an instance
            rather than reading the module-level singleton, because the
            question worth asking ("is *this* env priced?") is about
            runtime values, not import-time defaults.

    Returns:
        The set of resolved Claude model ids.
    """
    base = config.anthropic_model
    ids = {base}
    for name in type(config).model_fields:
        if name == "anthropic_model" or not name.endswith("_model"):
            continue
        value = getattr(config, name)
        ids.add(value or base)
    return ids


def unpriced_models(config: Settings) -> set[str]:
    """Return the routed model ids that have no row in the price table.

    Non-empty means this deployment will bill some agent's calls at the
    Sonnet fallback. Since ADR 0033 that is not merely a reporting
    error: the same number feeds `max_cost_usd`, so an off-table model
    priced 3.3x low lets a $2.00 cap pass ~$6.60 of real spend
    (ADR 0051).

    Args:
        config: The `Settings` instance to check.

    Returns:
        Resolved model ids missing from `PRICES_USD_PER_MILLION`; empty
        when the deployment is fully priced.
    """
    missing = resolved_model_ids(config) - set(PRICES_USD_PER_MILLION)
    for model in sorted(missing):
        _warn_unpriced_model_once(model)
    return missing


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> float:
    """Return the estimated cost in USD for a completed LLM call.

    Falls back to Sonnet pricing when the model isn't in the table, and
    warns **once per model id** (see `_unpriced_warned`). This prevents
    silent under-reporting when we onboard a new model without updating
    the table — and since ADR 0033 the error is not cosmetic: the same
    number feeds `max_cost_usd` enforcement, so an off-table Fable 5
    would let a $2.00 cap pass ~$6.60 of real spend.

    Cache tokens are priced separately: reads at 10% of the base input
    rate, writes at 125% (Anthropic's 25% first-write premium).
    """
    prices = PRICES_USD_PER_MILLION.get(model)
    if prices is None:
        _warn_unpriced_model_once(model)
        prices = PRICES_USD_PER_MILLION[_FALLBACK_MODEL]
    input_price_per_token = prices["input"] / 1_000_000
    output_price_per_token = prices["output"] / 1_000_000
    return (
        input_tokens * input_price_per_token
        + cache_read_input_tokens * input_price_per_token * _CACHE_READ_MULTIPLIER
        + cache_creation_input_tokens
        * input_price_per_token
        * _CACHE_WRITE_MULTIPLIER
        + output_tokens * output_price_per_token
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
    total_cache_read_input_tokens: int = 0
    total_cache_creation_input_tokens: int = 0
    call_count: int = 0
    per_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        with self._lock:
            self.total_cost_usd += cost_usd
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cache_read_input_tokens += cache_read_input_tokens
            self.total_cache_creation_input_tokens += cache_creation_input_tokens
            self.call_count += 1

            slot = self.per_model.setdefault(
                model,
                {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cost_usd": 0.0,
                    "call_count": 0,
                },
            )
            slot["input_tokens"] += input_tokens
            slot["output_tokens"] += output_tokens
            slot["cache_read_input_tokens"] += cache_read_input_tokens
            slot["cache_creation_input_tokens"] += cache_creation_input_tokens
            slot["cost_usd"] += cost_usd
            slot["call_count"] += 1

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe snapshot for log / summary emission."""
        with self._lock:
            return {
                "total_cost_usd": round(self.total_cost_usd, 6),
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cache_read_input_tokens": self.total_cache_read_input_tokens,
                "total_cache_creation_input_tokens": self.total_cache_creation_input_tokens,
                "call_count": self.call_count,
                "per_model": {
                    model: {
                        "input_tokens": slot["input_tokens"],
                        "output_tokens": slot["output_tokens"],
                        "cache_read_input_tokens": slot.get(
                            "cache_read_input_tokens", 0
                        ),
                        "cache_creation_input_tokens": slot.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cost_usd": round(slot["cost_usd"], 6),
                        "call_count": slot["call_count"],
                    }
                    for model, slot in self.per_model.items()
                },
            }


class CostBudgetExceeded(Exception):
    """A run's accumulated LLM spend crossed ``settings.max_cost_usd``.

    Raised from two places, both reading the same accumulator:

    - `src.llm.call_llm`, *before* issuing a call (ADR 0051). This is
      the choke point every entry point shares — CLI, eval campaign,
      API — so the ceiling now binds on the sync paths that previously
      had none, and a single node's fan-out can no longer overshoot the
      cap by its whole spend.
    - The API runner's `on_node` callback, between graph nodes
      (ADR 0033). Kept as the earlier, coarser stop: it fires even for a
      node that spent without going through `call_llm`.

    Both raisers use this one class so `run_job`'s handler catches
    either without caring which fired first. `partial_report` carries
    the draft the run had already produced when the ceiling hit, so the
    money already spent still yields its artifact.
    """

    def __init__(
        self, spent_usd: float, cap_usd: float, partial_report: str = ""
    ) -> None:
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        self.partial_report = partial_report
        super().__init__(
            f"per-run cost ${spent_usd:.4f} exceeded cap ${cap_usd:.2f}"
        )


def enforce_cost_cap(costs: RunCosts, cap_usd: float) -> None:
    """Raise `CostBudgetExceeded` when the run's spend crosses the cap.

    The cap comes from `settings.max_cost_usd`; passing it in
    explicitly (rather than reading `settings` here) keeps this helper
    unit-testable without env-var gymnastics, and lets the API runner
    read the setting once per job instead of once per node.

    At-or-above, not strictly-above: spend sitting exactly on the limit
    must stop the next call, or one expensive call parks on the ceiling
    and the next one sails past it.
    """
    spent = costs.total_cost_usd
    if spent >= cap_usd:
        raise CostBudgetExceeded(spent_usd=spent, cap_usd=cap_usd)


_current_costs: ContextVar[RunCosts | None] = ContextVar(
    "current_costs", default=None
)

_effective_cost_cap_usd: ContextVar[float | None] = ContextVar(
    "effective_cost_cap_usd", default=None
)


@dataclass(frozen=True)
class LlmCallObservation:
    """One completed model call, as `record_llm_call` saw it.

    A frozen value rather than the accumulator itself: an observer is a
    *reader* of a call that already happened, and handing it the mutable
    `RunCosts` would invite a bookkeeping second opinion. Everything a
    downstream recorder needs to describe the call — the billed model,
    the four token buckets, the priced cost, the retries thrown away —
    is here, and nothing it does not.
    """

    model: str
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    cost_usd: float
    retries: int
    latency_ms: float | None


LlmCallObserver = Callable[[LlmCallObservation], None]
"""Notified once per completed model call, after the accumulator moved."""


_llm_call_observer: ContextVar[LlmCallObserver | None] = ContextVar(
    "llm_call_observer", default=None
)


def bind_llm_call_observer(observer: LlmCallObserver) -> Token[LlmCallObserver | None]:
    """Observe every model call made in this context (P0-WO05, ADR 0078).

    A `ContextVar` for the same reason `_current_costs` is one: the
    reader's per-paper fan-out records from a thread pool, and the API
    runner copies its context into every node thread, so a job's observer
    reaches the calls that job made and no others. A process-global
    callback list would attribute one job's spend to whichever job
    happened to register last.

    The observer is a pure sink. `record_llm_call` calls it *after* the
    accumulator and the counters have already moved, absorbs whatever it
    raises, and never lets it change what was recorded — a broken
    recorder must not be able to lose a call or fail the run that made
    it.

    Args:
        observer: Called with one `LlmCallObservation` per completed
            call. Must not raise; if it does, the failure is logged once
            per call and otherwise ignored.

    Returns:
        The reset token, to be handed to `reset_llm_call_observer` when
        the run's context ends.
    """
    return _llm_call_observer.set(observer)


def reset_llm_call_observer(token: Token[LlmCallObserver | None]) -> None:
    """Restore the previous observer after a run leaves its context."""
    _llm_call_observer.reset(token)


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


def bind_effective_cost_cap(cap_usd: float) -> Token[float | None]:
    """Bind this job's spend ceiling for every call in its context.

    The runner uses the ordinary research ceiling for research jobs and the
    tighter learning-session ceiling for session jobs. Context propagation
    carries the value into executor-backed graph nodes without a second LLM
    client or enforcement path.
    """
    return _effective_cost_cap_usd.set(cap_usd)


def effective_cost_cap(default_cap_usd: float) -> float:
    """Return the run-specific ceiling, or the caller's stable default."""
    cap = _effective_cost_cap_usd.get()
    return default_cap_usd if cap is None else cap


def reset_effective_cost_cap(token: Token[float | None]) -> None:
    """Restore the previous cap after a job leaves its task context."""
    _effective_cost_cap_usd.reset(token)


def record_llm_call(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    latency_ms: float | None = None,
    retries: int = 0,
) -> None:
    """Record a completed LLM call against the current run's accumulator.

    Silently no-ops when no accumulator is bound so unit tests /
    ad-hoc scripts calling `call_llm` without opening a run don't
    crash. Emits a structured log line for every call so eval /
    downstream processors can trace cost per query per agent.

    Cache token buckets default to 0 so existing callers keep working;
    ADR 0022 (prompt caching) sets non-zero values through
    `src.llm.call_llm` when the flag is on.

    The OTel counters are bumped unconditionally — unlike the
    accumulator, which needs a run bound to it. A call made outside a
    run still spent money, and a fleet's spend rate must not depend on
    whether the caller remembered to open one (ADR 0049).

    `latency_ms` and `retries` are the ADR-0051 retry-visibility
    fields. `retries` is the SDK's own `retries_taken` — the number of
    attempts this call threw away before the one that returned — so a
    throttled fleet shows up as `llm_retries_total` climbing rather than
    as unexplained wall-clock. Both default to their no-information
    values so existing callers keep working.

    Args:
        model: Model id the call was billed against.
        input_tokens: Non-cached input tokens from `usage`.
        output_tokens: Output tokens from `usage`.
        cache_read_input_tokens: Tokens served from the prompt cache.
        cache_creation_input_tokens: Tokens written to the prompt cache.
        latency_ms: Wall-clock for the whole call *chain* — retries,
            backoff sleeps and all. `None` when the caller did not time
            it.
        retries: Attempts discarded before the successful one. Their
            token spend is unknowable (`usage` only exists on a 2xx
            body), which is exactly why the count is recorded.
    """
    cost = estimate_cost(
        model,
        input_tokens,
        output_tokens,
        cache_read_input_tokens,
        cache_creation_input_tokens,
    )
    record_llm_usage(model=model, cost_usd=cost)
    if retries:
        record_llm_retries(model=model, retries=retries)
    payload: dict[str, Any] = {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_input_tokens": cache_read_input_tokens,
        "cache_creation_input_tokens": cache_creation_input_tokens,
        "cost_usd": round(cost, 6),
        "retries": retries,
    }
    if latency_ms is not None:
        payload["latency_ms"] = round(latency_ms, 1)
    log.info("llm_call", extra=payload)
    costs = _current_costs.get()
    if costs is not None:
        costs.record(
            model,
            input_tokens,
            output_tokens,
            cost,
            cache_read_input_tokens=cache_read_input_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
        )
    observer = _llm_call_observer.get()
    if observer is not None:
        try:
            observer(
                LlmCallObservation(
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cache_read_input_tokens=cache_read_input_tokens,
                    cache_creation_input_tokens=cache_creation_input_tokens,
                    cost_usd=cost,
                    retries=retries,
                    latency_ms=latency_ms,
                )
            )
        except Exception:
            # The call is already recorded; an observer is a reader.
            # Losing its side record must never cost the run the call it
            # already paid for, so this absorbs and says so once.
            log.warning("llm_call_observer_failed", extra={"model": model}, exc_info=True)
