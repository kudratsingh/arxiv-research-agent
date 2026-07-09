"""Unit tests for the observability package.

Covers structured JSON logging, run-scoped ContextVars, cost tracking
(price table + accumulator + per-model breakdown), and cross-thread
context propagation via `contextvars.copy_context().run(...)`.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.observability import (
    JsonFormatter,
    RunCosts,
    bind_run_id,
    current_costs,
    current_run_id,
    estimate_cost,
    propagate_run_context,
    record_llm_call,
    reset_run_id,
    start_cost_tracking,
)
from src.observability import costs as costs_module
from src.observability import logging as logging_module


@pytest.fixture(autouse=True)
def _reset_context_vars() -> None:
    """Fully reset the observability ContextVars between tests.

    Tests that start cost tracking or bind a run_id in this module
    would otherwise leak state into subsequent tests via the module-
    level ContextVars. Direct `.set(None)` / `.set("-")` at teardown.
    """
    yield
    costs_module._current_costs.set(None)
    logging_module._run_id.set("-")


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------


def _make_record(
    msg: str = "hello",
    *,
    level: int = logging.INFO,
    extra: dict[str, object] | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="src.test",
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_produces_valid_json_line(self) -> None:
        formatter = JsonFormatter()
        out = formatter.format(_make_record())
        payload = json.loads(out)
        assert payload["message"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "src.test"
        assert payload["run_id"] == "-"  # no bind_run_id in scope

    def test_extra_fields_land_in_payload(self) -> None:
        formatter = JsonFormatter()
        out = formatter.format(
            _make_record(extra={"query_id": "q1", "cost_usd": 0.42})
        )
        payload = json.loads(out)
        assert payload["query_id"] == "q1"
        assert payload["cost_usd"] == 0.42

    def test_run_id_from_contextvar_appears_in_payload(self) -> None:
        formatter = JsonFormatter()
        token = bind_run_id("rid-abc")
        try:
            out = formatter.format(_make_record())
        finally:
            reset_run_id(token)
        payload = json.loads(out)
        assert payload["run_id"] == "rid-abc"

    def test_exception_captured(self) -> None:
        formatter = JsonFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                name="src.test",
                level=logging.ERROR,
                pathname="t.py",
                lineno=1,
                msg="fail",
                args=(),
                exc_info=sys.exc_info(),
            )
        payload = json.loads(formatter.format(record))
        assert "exception" in payload
        assert "RuntimeError" in payload["exception"]


class TestRunIdContext:
    def test_default_is_dash(self) -> None:
        assert current_run_id() == "-"

    def test_bind_and_reset(self) -> None:
        token = bind_run_id("rid-x")
        assert current_run_id() == "rid-x"
        reset_run_id(token)
        assert current_run_id() == "-"

    def test_nested_bind_reset_restores_outer(self) -> None:
        outer = bind_run_id("outer")
        inner = bind_run_id("inner")
        assert current_run_id() == "inner"
        reset_run_id(inner)
        assert current_run_id() == "outer"
        reset_run_id(outer)
        assert current_run_id() == "-"


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------


class TestEstimateCost:
    def test_sonnet_input_output_math(self) -> None:
        # 1_000_000 input tokens at $3, 500_000 output tokens at $15 -> 3 + 7.5 = 10.5
        result = estimate_cost("claude-sonnet-4-6", 1_000_000, 500_000)
        assert result == pytest.approx(10.5)

    def test_haiku_much_cheaper(self) -> None:
        # 1M input at $0.8, 1M output at $4 -> 4.8
        result = estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert result == pytest.approx(4.8)

    def test_opus_much_pricier(self) -> None:
        # 1M input at $15, 1M output at $75 -> 90
        result = estimate_cost("claude-opus-4-7", 1_000_000, 1_000_000)
        assert result == pytest.approx(90.0)

    def test_zero_tokens_zero_cost(self) -> None:
        assert estimate_cost("claude-sonnet-4-6", 0, 0) == 0.0

    def test_unknown_model_falls_back_to_sonnet(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Silently under-reporting cost for a new model is exactly what
        # the warning + Sonnet fallback protects against.
        with caplog.at_level(logging.WARNING, logger="src.observability.costs"):
            result = estimate_cost("claude-unknown-99", 1_000_000, 0)
        assert result == pytest.approx(3.0)


class TestRunCosts:
    def test_starts_empty(self) -> None:
        costs = RunCosts()
        assert costs.total_cost_usd == 0.0
        assert costs.call_count == 0
        assert costs.per_model == {}

    def test_record_accumulates_totals(self) -> None:
        costs = RunCosts()
        costs.record("claude-sonnet-4-6", 1000, 500, 0.01)
        costs.record("claude-sonnet-4-6", 2000, 1000, 0.02)
        assert costs.total_input_tokens == 3000
        assert costs.total_output_tokens == 1500
        assert costs.total_cost_usd == pytest.approx(0.03)
        assert costs.call_count == 2

    def test_record_breaks_down_per_model(self) -> None:
        costs = RunCosts()
        costs.record("claude-sonnet-4-6", 1000, 500, 0.01)
        costs.record("claude-haiku-4-5-20251001", 5000, 200, 0.005)
        assert set(costs.per_model.keys()) == {
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
        }
        assert costs.per_model["claude-sonnet-4-6"]["call_count"] == 1
        assert costs.per_model["claude-haiku-4-5-20251001"]["call_count"] == 1

    def test_as_dict_json_safe(self) -> None:
        costs = RunCosts()
        costs.record("claude-sonnet-4-6", 1000, 500, 0.01)
        # Must serialize cleanly — no locks, no non-primitive types.
        json.dumps(costs.as_dict())

    def test_record_is_thread_safe(self) -> None:
        costs = RunCosts()

        def worker() -> None:
            for _ in range(100):
                costs.record("claude-sonnet-4-6", 10, 5, 0.001)

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(worker) for _ in range(8)]
            for f in futures:
                f.result()

        assert costs.call_count == 8 * 100
        assert costs.total_input_tokens == 8 * 100 * 10


# ---------------------------------------------------------------------------
# Prompt-cache token accounting (ADR 0022) — cost math + accumulator buckets.
# ---------------------------------------------------------------------------


class TestCacheTokenPricing:
    def test_cache_read_priced_at_ten_percent(self) -> None:
        # Sonnet input is $3/M. Cache read should be $0.30/M → 1M read = 0.30.
        result = estimate_cost(
            "claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cache_read_input_tokens=1_000_000,
        )
        assert result == pytest.approx(0.30)

    def test_cache_write_priced_at_one_hundred_twenty_five_percent(self) -> None:
        # Sonnet input is $3/M. Cache write premium: $3.75/M.
        result = estimate_cost(
            "claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cache_creation_input_tokens=1_000_000,
        )
        assert result == pytest.approx(3.75)

    def test_all_four_buckets_additive(self) -> None:
        # 500k regular input @ $3/M -> 1.5
        # 500k output @ $15/M -> 7.5
        # 500k cache read @ $0.30/M -> 0.15
        # 500k cache write @ $3.75/M -> 1.875
        result = estimate_cost(
            "claude-sonnet-4-6",
            input_tokens=500_000,
            output_tokens=500_000,
            cache_read_input_tokens=500_000,
            cache_creation_input_tokens=500_000,
        )
        assert result == pytest.approx(1.5 + 7.5 + 0.15 + 1.875)

    def test_cache_defaults_to_zero_when_omitted(self) -> None:
        # Existing callers that don't know about cache tokens must
        # get the same result as before.
        without = estimate_cost("claude-sonnet-4-6", 1_000_000, 500_000)
        with_zero = estimate_cost(
            "claude-sonnet-4-6",
            1_000_000,
            500_000,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        assert without == with_zero


class TestRunCostsCacheAccumulation:
    def test_cache_tokens_accumulate_at_totals_and_per_model(self) -> None:
        costs = RunCosts()
        costs.record(
            "claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.05,
            cache_read_input_tokens=900,
            cache_creation_input_tokens=200,
        )
        costs.record(
            "claude-sonnet-4-6",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.05,
            cache_read_input_tokens=900,
            cache_creation_input_tokens=0,
        )
        assert costs.total_cache_read_input_tokens == 1800
        assert costs.total_cache_creation_input_tokens == 200
        slot = costs.per_model["claude-sonnet-4-6"]
        assert slot["cache_read_input_tokens"] == 1800
        assert slot["cache_creation_input_tokens"] == 200

    def test_as_dict_carries_cache_buckets(self) -> None:
        costs = RunCosts()
        costs.record(
            "claude-sonnet-4-6",
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.001,
            cache_read_input_tokens=100,
            cache_creation_input_tokens=20,
        )
        snapshot = costs.as_dict()
        assert snapshot["total_cache_read_input_tokens"] == 100
        assert snapshot["total_cache_creation_input_tokens"] == 20
        model_slot = snapshot["per_model"]["claude-sonnet-4-6"]
        assert model_slot["cache_read_input_tokens"] == 100
        assert model_slot["cache_creation_input_tokens"] == 20

    def test_record_backward_compatible_signature(self) -> None:
        # Callers that don't pass cache kwargs still work, and cache
        # buckets stay at 0.
        costs = RunCosts()
        costs.record("claude-sonnet-4-6", 10, 5, 0.001)
        assert costs.total_cache_read_input_tokens == 0
        assert costs.total_cache_creation_input_tokens == 0


class TestCurrentCostsAndRecordCall:
    def test_current_costs_is_none_when_not_started(self) -> None:
        assert current_costs() is None

    def test_start_cost_tracking_binds_new_accumulator(self) -> None:
        costs = start_cost_tracking()
        assert current_costs() is costs
        # Cleanup by starting a fresh no-op accumulator; ContextVar isolation
        # limits leakage but keep tests hygienic.

    def test_record_llm_call_updates_current_accumulator(self) -> None:
        costs = start_cost_tracking()
        record_llm_call("claude-sonnet-4-6", 1000, 500)
        assert costs.call_count == 1
        assert costs.total_input_tokens == 1000
        assert costs.total_output_tokens == 500
        assert costs.total_cost_usd > 0.0

    def test_record_llm_call_no_op_when_no_accumulator(self) -> None:
        # Force the ContextVar back to None for this test.
        token = costs_module._current_costs.set(None)
        try:
            # Should not raise.
            record_llm_call("claude-sonnet-4-6", 100, 50)
        finally:
            costs_module._current_costs.reset(token)


class TestCrossThreadContextPropagation:
    def test_propagate_carries_run_id_and_costs_across_workers(self) -> None:
        token = bind_run_id("rid-parent")
        costs = start_cost_tracking()
        try:
            def worker(tokens: int) -> tuple[str, int]:
                record_llm_call("claude-sonnet-4-6", tokens, tokens)
                return current_run_id(), tokens

            wrapped = propagate_run_context(worker)

            with ThreadPoolExecutor(max_workers=3) as ex:
                results = list(ex.map(wrapped, [100, 200, 300]))
        finally:
            reset_run_id(token)

        assert all(rid == "rid-parent" for rid, _ in results)
        # Three fan-out calls all recorded into the parent's accumulator.
        assert costs.call_count == 3
        assert costs.total_input_tokens == 600

    def test_bare_thread_pool_does_not_propagate(self) -> None:
        """Without propagate_run_context, workers don't inherit ContextVars."""
        token = bind_run_id("rid-parent")
        start_cost_tracking()
        try:
            def worker() -> str:
                return current_run_id()

            with ThreadPoolExecutor(max_workers=1) as ex:
                observed = ex.submit(worker).result()
        finally:
            reset_run_id(token)

        # Bare ThreadPoolExecutor doesn't inherit ContextVar — worker sees default.
        assert observed == "-"

    def test_propagate_restores_worker_thread_context(self) -> None:
        """After a wrapped call returns, the worker's default context is unchanged."""
        # Worker with no parent context.
        def snapshot_worker() -> str:
            return current_run_id()

        # Establish a fresh worker thread and observe its default state.
        with ThreadPoolExecutor(max_workers=1) as ex:
            baseline = ex.submit(snapshot_worker).result()
            assert baseline == "-"

            # Now bind on parent, wrap, invoke — must not leak into worker.
            token = bind_run_id("rid-parent")
            try:
                wrapped = propagate_run_context(lambda: current_run_id())
                inside = ex.submit(wrapped).result()
            finally:
                reset_run_id(token)
            assert inside == "rid-parent"

            # Same worker, next submit — must be back to default.
            after = ex.submit(snapshot_worker).result()
            assert after == "-"


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------


class TestGetLogger:
    def test_returns_configured_logger(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Reset the module-level guard so we can verify configuration runs.
        monkeypatch.setattr(logging_module, "_configured_root", False)
        # Snapshot handlers to restore later.
        root = logging.getLogger()
        old_handlers = list(root.handlers)
        try:
            logger = logging_module.get_logger("src.observability.test")
            assert isinstance(logger, logging.Logger)
            # Handler was attached to the root.
            assert any(
                isinstance(h.formatter, JsonFormatter)
                for h in root.handlers
            )
        finally:
            # Restore prior handler list to avoid duplicate JSON handlers
            # bleeding into other tests' captured logs.
            root.handlers = old_handlers
