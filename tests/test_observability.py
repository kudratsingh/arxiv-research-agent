"""Unit tests for the observability package.

Covers structured JSON logging, run-scoped ContextVars, cost tracking
(price table + accumulator + per-model breakdown), and cross-thread
context propagation via `contextvars.copy_context().run(...)`.
"""

from __future__ import annotations

import datetime as dt
import faulthandler
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.config import Settings
from src.observability import (
    PRICES_USD_PER_MILLION,
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
from src.observability.costs import resolved_model_ids, unpriced_models

pytestmark = pytest.mark.unit


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
        # 1M input at $1, 1M output at $5 -> 6.0
        result = estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert result == pytest.approx(6.0)

    def test_opus_much_pricier(self) -> None:
        # 1M input at $5, 1M output at $25 -> 30
        result = estimate_cost("claude-opus-4-7", 1_000_000, 1_000_000)
        assert result == pytest.approx(30.0)

    def test_frontier_tier_priced_above_opus(self) -> None:
        # 1M input at $10, 1M output at $50 -> 60. Priced at the Sonnet
        # fallback this would read $18, and a $2.00 cap would permit
        # ~$6.60 of real spend (ADR 0051).
        assert estimate_cost("claude-fable-5", 1_000_000, 1_000_000) == (
            pytest.approx(60.0)
        )

    def test_zero_tokens_zero_cost(self) -> None:
        assert estimate_cost("claude-sonnet-4-6", 0, 0) == 0.0

    def test_unknown_model_falls_back_to_sonnet_and_warns(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # Silently under-reporting cost for a new model is exactly what
        # the warning + Sonnet fallback protects against.
        costs_module.reset_unpriced_warnings()
        with caplog.at_level(logging.WARNING, logger="src.observability.costs"):
            result = estimate_cost("claude-unknown-99", 1_000_000, 0)
        assert result == pytest.approx(3.0)
        warnings = [
            r
            for r in caplog.records
            if r.message == "unknown_model_pricing_fallback"
        ]
        assert len(warnings) == 1
        assert warnings[0].model == "claude-unknown-99"

    def test_unknown_model_warns_once_per_id(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One line per model id per process, not one per call.

        ADR 0051: the reader alone makes `max_papers` calls per pass, so
        an off-table model used to emit hundreds of identical WARNINGs
        in a run — which is how the line that matters got lost in the
        lines that don't. Mutation-check: dropping the `_unpriced_warned`
        guard makes this see three warnings for `-a` instead of one.
        """
        costs_module.reset_unpriced_warnings()
        with caplog.at_level(logging.WARNING, logger="src.observability.costs"):
            for _ in range(3):
                estimate_cost("claude-offtable-a", 1000, 1000)
            estimate_cost("claude-offtable-b", 1000, 1000)

        warned = [
            r.model
            for r in caplog.records
            if r.message == "unknown_model_pricing_fallback"
        ]
        assert warned == ["claude-offtable-a", "claude-offtable-b"]

    def test_reset_seam_lets_a_warned_model_warn_again(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        costs_module.reset_unpriced_warnings()
        with caplog.at_level(logging.WARNING, logger="src.observability.costs"):
            estimate_cost("claude-offtable-c", 1000, 1000)
            costs_module.reset_unpriced_warnings()
            estimate_cost("claude-offtable-c", 1000, 1000)

        warned = [
            r
            for r in caplog.records
            if r.message == "unknown_model_pricing_fallback"
        ]
        assert len(warned) == 2


class TestPriceTableCoverage:
    """The price table must cover every Claude id the config can route to.

    A model that reaches production routing without a price row is
    priced at the Sonnet fallback — wrong by up to 5x in either
    direction, and since ADR 0033 that error feeds `max_cost_usd`
    enforcement, not just reporting. See ADR 0044.
    """

    def test_shipped_defaults_are_fully_priced(self) -> None:
        assert unpriced_models(Settings()) == set()

    def test_resolution_follows_runtime_values_not_field_defaults(self) -> None:
        """The old version of this test was vacuous and hid a P1.

        Every `<agent>_model` field defaults to `""`, so a check built
        from `field.default` only ever examined the single literal
        `anthropic_model` default — a deployment that sets
        `ANTHROPIC_MODEL` or any per-agent override to an off-table id
        passed it untouched, then priced every call at the Sonnet
        fallback (ADR 0051). Resolution has to read runtime *values*.
        """
        config = Settings(
            anthropic_model="claude-opus-5",
            reader_model="claude-haiku-4-5",
        )
        resolved = resolved_model_ids(config)

        assert "claude-opus-5" in resolved
        assert "claude-haiku-4-5" in resolved
        # Empty overrides resolve to the base model, not to "".
        assert "" not in resolved
        # Untouched routing fields inherit the base, so the base is the
        # only other id in play.
        assert resolved == {"claude-opus-5", "claude-haiku-4-5"}

    def test_runtime_model_off_the_table_is_detected(self) -> None:
        """The check has to be able to *fail*, or it guarantees nothing.

        Mutation-check for the test above: this is the case the vacuous
        version reported clean.
        """
        assert unpriced_models(
            Settings(anthropic_model="claude-something-new-9")
        ) == {"claude-something-new-9"}

    def test_runtime_per_agent_override_off_the_table_is_detected(self) -> None:
        assert unpriced_models(
            Settings(reader_model="claude-cheapo-0")
        ) == {"claude-cheapo-0"}

    def test_resolution_covers_every_routing_field(self) -> None:
        """A new agent's routing field must be picked up automatically.

        `resolved_model_ids` derives the field list from the model
        rather than a hand-kept tuple, so this asserts the derivation
        rather than a snapshot of today's agents.
        """
        routing = [
            name
            for name in Settings.model_fields
            if name.endswith("_model") and name != "anthropic_model"
        ]
        assert routing, "expected per-agent routing fields on Settings"
        for name in routing:
            marker = f"claude-marker-{name}"
            config = Settings(**{name: marker})
            assert marker in resolved_model_ids(config), name

    def test_covers_adr_0021_recommended_overrides(self) -> None:
        # ADR 0021 recommends routing reader / supervisor / query
        # refiner to Haiku. Both the dated id it names and the bare
        # canonical id an operator is likely to type must be priced —
        # the Haiku reader is the highest-volume agent, so a fallback
        # to Sonnet pricing would overstate its cost 3x+.
        for model in ("claude-haiku-4-5", "claude-haiku-4-5-20251001"):
            assert model in PRICES_USD_PER_MILLION, model

    def test_haiku_alias_and_dated_id_priced_identically(self) -> None:
        assert (
            PRICES_USD_PER_MILLION["claude-haiku-4-5"]
            == PRICES_USD_PER_MILLION["claude-haiku-4-5-20251001"]
        )

    def test_last_verified_is_a_real_date(self) -> None:
        # The staleness tripwire only works if the constant stays a
        # parseable ISO date.
        dt.date.fromisoformat(costs_module.PRICES_LAST_VERIFIED)


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

    def test_record_llm_call_feeds_the_metrics_choke_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR 0049 hangs `llm_cost_usd_total` / `llm_calls_total` off
        this function so every LLM call site is covered from one place.

        Asserted here, at the accumulator's own tests, because the
        coupling runs the other way too: a refactor that moved cost
        estimation out of `record_llm_call` would silently take the
        metrics with it. What the counters do with the numbers is
        `tests/test_otel_metrics.py`'s business.
        """
        seen: list[tuple[str, float]] = []
        monkeypatch.setattr(
            costs_module,
            "record_llm_usage",
            lambda *, model, cost_usd: seen.append((model, cost_usd)),
        )

        start_cost_tracking()
        record_llm_call("claude-haiku-4-5", 1_000_000, 0)

        # Haiku input is $1 / 1M tokens — the same figure the
        # accumulator was handed, not a separately computed one.
        assert seen == [("claude-haiku-4-5", pytest.approx(1.0))]

    def test_metrics_are_off_by_default(self) -> None:
        """The default deployment installs no meter provider, so the
        record points above cost one `None` check and nothing else."""
        from src.config import Settings
        from src.observability import metrics as metrics_module

        assert Settings().enable_metrics is False
        assert metrics_module.metrics_enabled() is False


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


# ---------------------------------------------------------------------------
# ADR 0051 — stderr JSON purity, SDK retry visibility, crash diagnostics
# ---------------------------------------------------------------------------


class _RootConfigHarness:
    """Run `_configure_root_once` against a throwaway root logger state.

    The function is a once-per-process side effect on global logging
    state, so every test that wants to observe it has to reset the
    guard, snapshot the handlers and levels it touches, and put them
    back afterwards.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch
        self._root = logging.getLogger()
        self._handlers = list(self._root.handlers)
        self._level = self._root.level
        touched = (
            *logging_module._NOISY_LOGGERS,
            logging_module._SDK_RETRY_LOGGER,
        )
        self._levels = {n: logging.getLogger(n).level for n in touched}

    def run(self, *, log_level: str = "INFO") -> None:
        self._monkeypatch.setattr(logging_module, "_configured_root", False)
        self._monkeypatch.setattr(
            logging_module, "settings", Settings(log_level=log_level)
        )
        logging_module._configure_root_once()

    def restore(self) -> None:
        self._root.handlers = self._handlers
        self._root.setLevel(self._level)
        for name, level in self._levels.items():
            logging.getLogger(name).setLevel(level)


@pytest.fixture
def root_config(monkeypatch: pytest.MonkeyPatch):
    harness = _RootConfigHarness(monkeypatch)
    try:
        yield harness
    finally:
        harness.restore()


class TestStderrIsParseable:
    """`logs sink to stderr` is only useful if stderr is machine-readable.

    A measured full-workflow run emitted 22 JSON lines and 34 non-JSON
    ones — tqdm bars and library INFO chatter — with one JSON record
    physically split by an interleaved progress bar, i.e. records lost
    to a parser rather than merely surrounded by noise (ADR 0051).
    """

    def test_ml_stack_loggers_are_demoted(
        self, root_config: _RootConfigHarness
    ) -> None:
        # `sentence_transformers` matters twice over: the demotion also
        # turns its tqdm bars off, because the library's own default is
        # `show_progress_bar = logger.getEffectiveLevel() in (INFO, DEBUG)`.
        root_config.run()
        for name in ("sentence_transformers", "transformers", "huggingface_hub"):
            assert logging.getLogger(name).level == logging.WARNING, name

    def test_progress_bar_env_is_defaulted(
        self, root_config: _RootConfigHarness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Progress bars and the tokenizers fork warning write straight to
        # stderr, bypassing `logging` entirely — a logger level cannot
        # reach them, only these env vars can.
        for key in logging_module._QUIET_LIBRARY_ENV:
            monkeypatch.delenv(key, raising=False)

        root_config.run()

        import os

        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert os.environ["TOKENIZERS_PARALLELISM"] == "false"
        assert os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    def test_operator_env_override_is_respected(
        self, root_config: _RootConfigHarness, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`setdefault`, not `environ[...] = `.

        Someone debugging a model download must still be able to turn
        the bars back on.
        """
        monkeypatch.setenv("HF_HUB_DISABLE_PROGRESS_BARS", "0")

        root_config.run()

        import os

        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "0"


class TestSdkRetryVisibility:
    """ADR 0042 demoted the whole `anthropic` tree to WARNING, which
    silenced `_base_client`'s `"Retrying request..."` INFO line — the
    only in-process signal that the SDK is absorbing 429s / 529s /
    timeouts. ADR 0051 re-opens exactly that child."""

    def test_retry_logger_survives_the_blanket_demotion(
        self, root_config: _RootConfigHarness
    ) -> None:
        # Mutation-check: deleting the `_SDK_RETRY_LOGGER` line leaves
        # the child at NOTSET, inheriting `anthropic`'s WARNING, and
        # `isEnabledFor(INFO)` goes False.
        root_config.run(log_level="INFO")

        retry_logger = logging.getLogger(logging_module._SDK_RETRY_LOGGER)
        assert retry_logger.isEnabledFor(logging.INFO)
        # Its siblings stay quiet — only this one child is re-opened.
        assert not logging.getLogger("anthropic").isEnabledFor(logging.INFO)

    def test_warning_log_level_still_means_warning(
        self, root_config: _RootConfigHarness
    ) -> None:
        """The retry line is worth having, not worth overriding the
        operator's chosen verbosity for."""
        root_config.run(log_level="WARNING")

        retry_logger = logging.getLogger(logging_module._SDK_RETRY_LOGGER)
        assert not retry_logger.isEnabledFor(logging.INFO)
        assert retry_logger.isEnabledFor(logging.WARNING)

    def test_debug_leaves_every_library_logger_alone(
        self, root_config: _RootConfigHarness
    ) -> None:
        """ADR 0042's escape hatch: at DEBUG nothing is demoted, so
        `ANTHROPIC_LOG=debug` still works."""
        before = logging.getLogger("httpx").level
        root_config.run(log_level="DEBUG")
        assert logging.getLogger("httpx").level == before


class TestFaulthandler:
    """A SIGSEGV in torch / faiss / tokenizers kills the process with no
    Python output at all — an audit reproduced one inside MiniLM's
    pooling forward pass under the reader's fan-out. `faulthandler` is
    what turns exit 139 into a stack trace (ADR 0051)."""

    def test_enables_when_not_already_armed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []
        monkeypatch.setattr(
            logging_module.faulthandler, "is_enabled", lambda: False
        )
        monkeypatch.setattr(
            logging_module.faulthandler,
            "enable",
            lambda: calls.append(True),
        )

        logging_module._enable_faulthandler()

        assert calls == [True]

    def test_does_not_re_arm_an_enabled_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pytest arms it for us; re-arming would rebind the output file
        # to whatever stderr happens to be right now.
        calls: list[bool] = []
        monkeypatch.setattr(
            logging_module.faulthandler, "is_enabled", lambda: True
        )
        monkeypatch.setattr(
            logging_module.faulthandler,
            "enable",
            lambda: calls.append(True),
        )

        logging_module._enable_faulthandler()

        assert calls == []

    @pytest.mark.parametrize(
        "exc",
        [
            # Every way CPython's `faulthandler_get_fileno` refuses,
            # measured against the real interpreter rather than guessed:
            #   sys.stderr = None       -> RuntimeError
            #   sys.stderr = StringIO() -> io.UnsupportedOperation
            #                              (a ValueError *and* an OSError)
            #   sys.stderr with no fileno -> AttributeError
            RuntimeError("sys.stderr is None"),
            io.UnsupportedOperation("fileno"),
            AttributeError("'object' object has no attribute 'fileno'"),
            OSError("bad file descriptor"),
        ],
        ids=["stderr-is-none", "captured-stream", "no-fileno", "bad-fd"],
    )
    def test_unavailable_stderr_does_not_break_logging_setup(
        self, monkeypatch: pytest.MonkeyPatch, exc: BaseException
    ) -> None:
        """`enable()` needs a real fd and does not always get one.

        Crash diagnostics are a bonus; losing them must never stop the
        app from configuring its logging. The `RuntimeError` case is the
        one that matters most and the one an except-tuple written from
        memory misses: a stderr-detached process would otherwise lose
        *all* logging in order to save the crash handler.

        Mutation-check: dropping `RuntimeError` from the except tuple in
        `_enable_faulthandler` fails the first parameter case.
        """

        def _boom() -> None:
            raise exc

        monkeypatch.setattr(
            logging_module.faulthandler, "is_enabled", lambda: False
        )
        monkeypatch.setattr(logging_module.faulthandler, "enable", _boom)

        logging_module._enable_faulthandler()  # must not raise

    def test_real_enable_refuses_a_none_stderr_with_runtimeerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pins the interpreter behaviour the except tuple is written for.

        If a future CPython changes which exception `enable()` raises for
        a detached stderr, this fails and the tuple above gets revisited
        — rather than the guard silently stopping guarding.
        """
        monkeypatch.setattr(
            logging_module.faulthandler, "is_enabled", lambda: False
        )
        monkeypatch.setattr(sys, "stderr", None)

        with pytest.raises(RuntimeError):
            faulthandler.enable()

        logging_module._enable_faulthandler()  # must not raise


class TestRecordLlmCallRetryFields:
    def test_retries_and_latency_reach_the_log_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The `llm_call` line is where a throttled fleet becomes
        visible: a 240s call with 3 discarded attempts used to look
        identical to a fast one."""
        start_cost_tracking()
        with caplog.at_level(logging.INFO, logger="src.observability.costs"):
            record_llm_call(
                "claude-sonnet-4-6", 100, 50, latency_ms=1234.56, retries=3
            )

        record = next(r for r in caplog.records if r.message == "llm_call")
        assert record.retries == 3
        assert record.latency_ms == pytest.approx(1234.6)

    def test_untimed_call_omits_latency_rather_than_faking_it(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        start_cost_tracking()
        with caplog.at_level(logging.INFO, logger="src.observability.costs"):
            record_llm_call("claude-sonnet-4-6", 100, 50)

        record = next(r for r in caplog.records if r.message == "llm_call")
        assert not hasattr(record, "latency_ms")
        assert record.retries == 0
