"""Unit tests for the shared Anthropic client wrapper.

Focuses on how `_get_client` constructs the SDK client from
`settings` — retry policy, timeout, api key, and singleton behavior —
and on the three things ADR 0051 made `call_llm` responsible for:

  - the per-run spend ceiling, checked before every call, which is the
    only enforcement point the CLI and eval paths ever get;
  - retry visibility, read off the SDK's own `retries_taken` rather
    than by wrapping a second retry loop around the first;
  - a bounded call chain, so one flaky call cannot consume a whole
    API job's timeout budget.

The live `client.messages.create` round trip is exercised in
integration tests (which need a real API key) and via the metric /
agent tests where `call_llm_json` is monkeypatched.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest

from src import llm as llm_module
from src.cancellation import (
    CancelToken,
    JobCancelledError,
    bind_cancel_token,
    reset_cancel_token,
)
from src.config import Settings
from src.llm import MAX_RETRIES, REQUEST_TIMEOUT_SEC
from src.observability import costs as costs_module
from src.observability.costs import CostBudgetExceeded, start_cost_tracking

pytestmark = pytest.mark.unit


class _FakeAnthropic:
    """Records constructor kwargs so tests can assert on them."""

    instances: list[_FakeAnthropic] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeAnthropic.instances.append(self)


def _override_settings(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> Settings:
    """Replace `llm.settings` with a fresh Settings carrying the given overrides."""
    fresh = Settings(**overrides)
    monkeypatch.setattr(llm_module, "settings", fresh)
    return fresh


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level client between tests so each test gets a fresh construction."""
    monkeypatch.setattr(llm_module, "_client", None)
    _FakeAnthropic.instances.clear()


@pytest.fixture(autouse=True)
def _no_cost_accumulator() -> Any:
    """Start every test with no run bound.

    `call_llm`'s budget check is a no-op without an accumulator, and
    ContextVar state set by one test is visible to the next in the same
    pytest context — without this, a cost-cap test would silently arm
    the ceiling for every test that ran after it.
    """
    token = costs_module._current_costs.set(None)
    try:
        yield
    finally:
        costs_module._current_costs.reset(token)


class TestGetClient:
    def test_uses_clamped_max_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # At the shipped defaults the configured 4 retries would put the
        # worst-case call chain at 5 x 120s = the whole job timeout, so
        # `_retry_envelope` trims them (ADR 0051). The client must be
        # built from the trimmed number, not the raw setting.
        _override_settings(monkeypatch, anthropic_api_key="sk-test")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        client = llm_module._get_client()

        expected, _ = llm_module._retry_envelope()
        assert isinstance(client, _FakeAnthropic)
        assert client.kwargs["max_retries"] == expected
        assert expected < MAX_RETRIES

    def test_uses_configured_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, anthropic_api_key="sk-test")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        client = llm_module._get_client()

        assert client.kwargs["timeout"] == REQUEST_TIMEOUT_SEC

    def test_passes_api_key_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, anthropic_api_key="sk-my-test-key")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        client = llm_module._get_client()

        assert client.kwargs["api_key"] == "sk-my-test-key"

    def test_missing_api_key_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, anthropic_api_key="")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            llm_module._get_client()

    def test_settings_override_reaches_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Settings-driven config means overriding max_retries / timeout at
        # test time (or via env var in prod) reaches the constructed client.
        # 8 x 45s = 360s fits inside 75% of the 600s job budget, so the
        # clamp has nothing to say here and both values pass through.
        _override_settings(
            monkeypatch,
            anthropic_api_key="sk-test",
            anthropic_max_retries=7,
            anthropic_timeout_sec=45.0,
        )
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        client = llm_module._get_client()

        assert client.kwargs["max_retries"] == 7
        assert client.kwargs["timeout"] == 45.0

    def test_singleton_reuses_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, anthropic_api_key="sk-test")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        first = llm_module._get_client()
        second = llm_module._get_client()

        assert first is second
        assert len(_FakeAnthropic.instances) == 1

    def test_clamped_retries_warn_at_construction(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Overriding an operator's explicit setting has to be legible.

        Silently ignoring `ANTHROPIC_MAX_RETRIES=9` is the kind of thing
        that costs an afternoon to discover, so the clamp announces
        itself once, at WARNING, with both numbers.
        """
        _override_settings(
            monkeypatch,
            anthropic_api_key="sk-test",
            anthropic_max_retries=9,
            anthropic_timeout_sec=200.0,
        )
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        with caplog.at_level(logging.WARNING, logger="src.llm"):
            llm_module._get_client()

        clamped = [
            r for r in caplog.records if r.message == "llm_retry_budget_clamped"
        ]
        assert len(clamped) == 1
        assert clamped[0].configured_max_retries == 9  # type: ignore[attr-defined]
        assert clamped[0].max_retries < 9  # type: ignore[attr-defined]

    def test_unclamped_construction_does_not_warn(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        _override_settings(
            monkeypatch,
            anthropic_api_key="sk-test",
            anthropic_max_retries=2,
            anthropic_timeout_sec=30.0,
        )
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        with caplog.at_level(logging.INFO, logger="src.llm"):
            llm_module._get_client()

        events = {r.message for r in caplog.records}
        assert "llm_client_configured" in events
        assert "llm_retry_budget_clamped" not in events


class TestRetryEnvelope:
    """ADR 0051: the worst-case call chain must fit inside a job.

    The SDK applies `timeout` per *attempt*, so one logical call can
    burn `(max_retries + 1) * timeout` seconds of request time. At the
    shipped defaults that was 5 x 120s = 600s — exactly
    `api_job_timeout_sec` — meaning a single unlucky call could consume
    an entire job and the job would fail with nothing to show.
    """

    def test_shipped_defaults_fit_inside_the_job_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The load-bearing assertion of the whole clamp. Mutation-check:
        # replacing `_retry_envelope`'s body with
        # `return settings.anthropic_max_retries, settings.anthropic_timeout_sec`
        # makes worst_case == 600.0 == the job timeout and this fails.
        fresh = _override_settings(monkeypatch, anthropic_api_key="sk-test")
        max_retries, timeout_sec = llm_module._retry_envelope()

        worst_case = (max_retries + 1) * timeout_sec
        assert worst_case < fresh.api_job_timeout_sec
        # And it must leave real room for the rest of the graph, not
        # squeak under by a second.
        assert worst_case <= fresh.api_job_timeout_sec * 0.75

    def test_timeout_is_never_modified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Attempts get trimmed, the per-attempt timeout does not.

        A shorter timeout abandons slow-but-healthy generations, which
        costs money twice over: Anthropic bills the abandoned attempt
        and no `usage` comes back to record it.
        """
        fresh = _override_settings(
            monkeypatch, anthropic_api_key="sk-test", anthropic_timeout_sec=120.0
        )
        _, timeout_sec = llm_module._retry_envelope()
        assert timeout_sec == fresh.anthropic_timeout_sec

    def test_generous_job_budget_leaves_retries_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(
            monkeypatch,
            anthropic_api_key="sk-test",
            anthropic_max_retries=4,
            anthropic_timeout_sec=60.0,
            api_job_timeout_sec=3600,
        )
        max_retries, _ = llm_module._retry_envelope()
        assert max_retries == 4

    def test_at_least_one_attempt_survives(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A timeout larger than the whole budget still gets one shot.

        Refusing to call at all would be a worse answer than one long
        attempt, and the operator set both numbers deliberately.
        """
        _override_settings(
            monkeypatch,
            anthropic_api_key="sk-test",
            anthropic_max_retries=4,
            anthropic_timeout_sec=600.0,
            api_job_timeout_sec=10,
        )
        max_retries, _ = llm_module._retry_envelope()
        assert max_retries == 0


# ---------------------------------------------------------------------------
# Prompt caching (ADR 0022) — system-prompt block wrapping + usage passthrough.
# ---------------------------------------------------------------------------


class TestBuildSystemParam:
    def test_empty_prompt_returns_not_given(self) -> None:
        from src.llm import _build_system_param

        result = _build_system_param("", cache_system=True)
        assert result is llm_module.anthropic.NOT_GIVEN

    def test_no_cache_returns_plain_string(self) -> None:
        from src.llm import _build_system_param

        assert _build_system_param("sys prompt", cache_system=False) == "sys prompt"

    def test_cache_wraps_in_block_with_ephemeral_marker(self) -> None:
        from src.llm import _build_system_param

        result = _build_system_param("sys prompt", cache_system=True)
        assert isinstance(result, list)
        assert result == [
            {
                "type": "text",
                "text": "sys prompt",
                "cache_control": {"type": "ephemeral"},
            }
        ]


class _FakeUsage:
    def __init__(
        self,
        input_tokens: int = 100,
        output_tokens: int = 50,
        cache_read_input_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = cache_read_input_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    """Stands in for the SDK's `Message`.

    `id`, `model` and `stop_reason` are here because ADR 0066 puts them
    on the `chat` span as `gen_ai.response.{id,model,finish_reasons}`.
    A double that omits a field the code under test reads is a double
    that tests a different function than the one that ships.
    """

    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = usage
        self.id = "msg_fake"
        self.model = "claude-sonnet-4-6"
        self.stop_reason = "end_turn"


class _FakeRawResponse:
    """Stands in for the SDK's `LegacyAPIResponse`.

    `retries_taken` is the field ADR 0051 reads: the SDK's own count of
    attempts it discarded before the one that came back.
    """

    def __init__(self, parsed: _FakeResponse, retries_taken: int) -> None:
        self._parsed = parsed
        self.retries_taken = retries_taken

    def parse(self) -> _FakeResponse:
        return self._parsed


class _FakeRawMessages:
    def __init__(self, parent: _FakeMessages) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeRawResponse:
        return self._parent._create(**kwargs)


class _FakeMessages:
    def __init__(
        self,
        text: str = '{"ok": true}',
        usage: _FakeUsage | None = None,
        retries_taken: int = 0,
        raises: Exception | None = None,
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text
        self._usage = usage or _FakeUsage()
        self._retries_taken = retries_taken
        self._raises = raises
        self.with_raw_response = _FakeRawMessages(self)

    def _create(self, **kwargs: Any) -> _FakeRawResponse:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return _FakeRawResponse(
            _FakeResponse(self._text, self._usage), self._retries_taken
        )


class _FakeClient:
    def __init__(
        self,
        text: str = '{"ok": true}',
        usage: _FakeUsage | None = None,
        retries_taken: int = 0,
        raises: Exception | None = None,
    ) -> None:
        self.messages = _FakeMessages(text, usage, retries_taken, raises)


class TestCallLlmCachePassthrough:
    def test_cache_system_false_sends_plain_system_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _FakeClient()
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)

        llm_module.call_llm(
            "user msg", system_prompt="sys", cache_system=False
        )
        call = client.messages.calls[0]
        assert call["system"] == "sys"

    def test_cache_system_true_sends_block_with_ephemeral(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _FakeClient()
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)

        llm_module.call_llm(
            "user msg", system_prompt="sys", cache_system=True
        )
        call = client.messages.calls[0]
        assert call["system"] == [
            {
                "type": "text",
                "text": "sys",
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def test_cache_tokens_forwarded_to_record_llm_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        usage = _FakeUsage(
            input_tokens=20,
            output_tokens=15,
            cache_read_input_tokens=900,
            cache_creation_input_tokens=0,
        )
        client = _FakeClient(usage=usage)
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        seen: dict[str, Any] = {}

        def fake_record(**kw: Any) -> None:
            seen.update(kw)

        monkeypatch.setattr(llm_module, "record_llm_call", fake_record)

        llm_module.call_llm(
            "user msg", system_prompt="sys", cache_system=True
        )

        assert seen["input_tokens"] == 20
        assert seen["output_tokens"] == 15
        assert seen["cache_read_input_tokens"] == 900
        assert seen["cache_creation_input_tokens"] == 0

    def test_missing_cache_fields_default_to_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Older SDK responses may not carry the cache-token fields;
        # `getattr` with default should keep call_llm from crashing.
        class _StrippedUsage:
            input_tokens = 10
            output_tokens = 5
            # No cache_* attrs.

        client = _FakeClient(usage=_StrippedUsage())  # type: ignore[arg-type]
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            llm_module,
            "record_llm_call",
            lambda **kw: seen.update(kw),
        )

        llm_module.call_llm("u", system_prompt="s", cache_system=True)

        assert seen["cache_read_input_tokens"] == 0
        assert seen["cache_creation_input_tokens"] == 0


# ---------------------------------------------------------------------------
# ADR 0051 — spend ceiling at the one choke point every entry point shares.
# ---------------------------------------------------------------------------


class TestCallLlmCostCeiling:
    """`call_llm` refuses to spend past `settings.max_cost_usd`.

    The API runner has enforced this between graph nodes since ADR 0033,
    but `make run` and `make eval` drive the graph with a bare
    `app.invoke(...)` and installed no such hook — so the two paths
    about to spend real money had no dollar ceiling at all. `call_llm`
    is the only place all three funnel through.
    """

    def _client(self, monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
        client = _FakeClient()
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)
        return client

    def test_untracked_caller_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No accumulator bound means no run to measure — unchanged behaviour.

        A unit test or an ad-hoc script has no budget to exceed, and
        `record_llm_call` already no-ops for exactly this caller.
        """
        _override_settings(monkeypatch, max_cost_usd=0.01)
        client = self._client(monkeypatch)

        llm_module.call_llm("u")

        assert len(client.messages.calls) == 1

    def test_under_cap_proceeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _override_settings(monkeypatch, max_cost_usd=2.00)
        client = self._client(monkeypatch)
        costs = start_cost_tracking()
        costs.record("claude-sonnet-4-6", 100, 50, 0.50)

        llm_module.call_llm("u")

        assert len(client.messages.calls) == 1

    def test_at_or_above_cap_raises_before_spending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point is the *absence* of the call, not the exception.

        Mutation-check: moving `_check_cost_budget()` to after the
        `create` (or dropping it) leaves `CostBudgetExceeded` unraised
        and `calls` non-empty — both halves of this assertion fail.
        """
        _override_settings(monkeypatch, max_cost_usd=2.00)
        client = self._client(monkeypatch)
        costs = start_cost_tracking()
        costs.record("claude-opus-5", 1000, 1000, 2.00)

        with pytest.raises(CostBudgetExceeded) as exc_info:
            llm_module.call_llm("u")

        assert client.messages.calls == []
        assert exc_info.value.cap_usd == 2.00
        assert exc_info.value.spent_usd == pytest.approx(2.00)

    def test_cancellation_outranks_the_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An abandoned job's spend does not matter; its cancellation does.

        Both guards fire on the same call here — `check_cancelled`
        must be the one that wins, so a timed-out job reports
        `timeout` rather than a misleading `cost_budget_exceeded`.
        """
        _override_settings(monkeypatch, max_cost_usd=2.00)
        self._client(monkeypatch)
        costs = start_cost_tracking()
        costs.record("claude-opus-5", 1000, 1000, 5.00)

        token = CancelToken("job-1")
        token.cancel("job_timeout")
        scope = bind_cancel_token(token)
        try:
            with pytest.raises(JobCancelledError):
                llm_module.call_llm("u")
        finally:
            reset_cancel_token(scope)


# ---------------------------------------------------------------------------
# ADR 0051 — retry and upstream-error visibility.
# ---------------------------------------------------------------------------


def _status_error(status_code: int, request_id: str) -> Exception:
    """Build a real `anthropic.APIStatusError` for the given status."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"request-id": request_id},
        json={"error": {"type": "overloaded_error"}},
    )
    return llm_module.anthropic.APIStatusError(
        "overloaded", response=response, body=None
    )


class TestRetryVisibility:
    def test_retries_taken_reaches_the_cost_recorder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The SDK's own count is what gets recorded — no second retry loop.

        Mutation-check: hard-coding `retries=0` in `call_llm` makes this
        fail, which is the whole point — a rate-limited fleet has to be
        distinguishable from a merely slow one.
        """
        client = _FakeClient(retries_taken=3)
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            llm_module, "record_llm_call", lambda **kw: seen.update(kw)
        )

        llm_module.call_llm("u")

        assert seen["retries"] == 3

    def test_latency_is_recorded_on_every_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A 240s `llm_call` line is self-evidently a throttled call, and
        # it costs one field to be able to see that.
        client = _FakeClient()
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        seen: dict[str, Any] = {}
        monkeypatch.setattr(
            llm_module, "record_llm_call", lambda **kw: seen.update(kw)
        )

        llm_module.call_llm("u")

        assert seen["latency_ms"] is not None
        assert seen["latency_ms"] >= 0.0

    def test_status_error_logs_and_counts_then_reraises(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """529s that outlive the SDK's retries must leave a trace.

        By the time this escapes, the SDK has already burned every
        attempt — and before ADR 0051 that produced no log line, no
        metric, and no `usage` to record. The exception itself must
        still propagate untouched.
        """
        client = _FakeClient(raises=_status_error(529, "req_abc123"))
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        counted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            llm_module,
            "record_llm_upstream_error",
            lambda **kw: counted.append(kw),
        )

        with (
            caplog.at_level(logging.WARNING, logger="src.llm"),
            pytest.raises(llm_module.anthropic.APIStatusError),
        ):
            llm_module.call_llm("u", model_name="claude-opus-5")

        assert counted == [{"model": "claude-opus-5", "status": "529"}]
        records = [
            r for r in caplog.records if r.message == "llm_upstream_error"
        ]
        assert len(records) == 1
        assert records[0].status == "529"  # type: ignore[attr-defined]
        assert records[0].request_id == "req_abc123"  # type: ignore[attr-defined]
        assert records[0].elapsed_ms >= 0.0  # type: ignore[attr-defined]

    def test_timeout_is_reported_as_a_connection_failure(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """`APITimeoutError` subclasses `APIConnectionError`.

        It carries no HTTP status, so the class name is what tells a
        timeout apart from a reset — which is the difference between
        "our timeout is too tight" and "the network is broken".
        """
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        client = _FakeClient(
            raises=llm_module.anthropic.APITimeoutError(request=request)
        )
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        counted: list[dict[str, Any]] = []
        monkeypatch.setattr(
            llm_module,
            "record_llm_upstream_error",
            lambda **kw: counted.append(kw),
        )

        with (
            caplog.at_level(logging.WARNING, logger="src.llm"),
            pytest.raises(llm_module.anthropic.APITimeoutError),
        ):
            llm_module.call_llm("u", model_name="claude-sonnet-4-6")

        assert counted == [
            {"model": "claude-sonnet-4-6", "status": "connection"}
        ]
        record = next(
            r for r in caplog.records if r.message == "llm_upstream_error"
        )
        assert record.detail == "APITimeoutError"  # type: ignore[attr-defined]

    def test_successful_call_logs_no_upstream_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = _FakeClient()
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)
        monkeypatch.setattr(llm_module, "record_llm_call", lambda **_: None)

        with caplog.at_level(logging.WARNING, logger="src.llm"):
            llm_module.call_llm("u")

        assert not [
            r for r in caplog.records if r.message == "llm_upstream_error"
        ]
