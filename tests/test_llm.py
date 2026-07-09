"""Unit tests for the shared Anthropic client wrapper.

Focuses on how `_get_client` constructs the SDK client from
`settings` — retry policy, timeout, api key, and singleton behavior.
The actual `client.messages.create` call is exercised in integration
tests (which need a real API key) and via the metric / agent tests
where `call_llm_json` is monkeypatched.
"""

from typing import Any

import pytest

from src import llm as llm_module
from src.config import Settings
from src.llm import MAX_RETRIES, REQUEST_TIMEOUT_SEC


class _FakeAnthropic:
    """Records constructor kwargs so tests can assert on them."""

    instances: list["_FakeAnthropic"] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeAnthropic.instances.append(self)


def _override_settings(
    monkeypatch: pytest.MonkeyPatch, **overrides: Any
) -> None:
    """Replace `llm.settings` with a fresh Settings carrying the given overrides."""
    fresh = Settings(**overrides)
    monkeypatch.setattr(llm_module, "settings", fresh)


@pytest.fixture(autouse=True)
def _reset_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the module-level client between tests so each test gets a fresh construction."""
    monkeypatch.setattr(llm_module, "_client", None)
    _FakeAnthropic.instances.clear()


class TestGetClient:
    def test_uses_configured_max_retries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, anthropic_api_key="sk-test")
        monkeypatch.setattr(llm_module.anthropic, "Anthropic", _FakeAnthropic)

        client = llm_module._get_client()

        assert isinstance(client, _FakeAnthropic)
        assert client.kwargs["max_retries"] == MAX_RETRIES

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


class TestRetryPolicyConstants:
    def test_max_retries_reasonable_bound(self) -> None:
        # Sanity — don't want an unbounded retry storm nor a value so low
        # a single flaky 429 kills an eval run.
        assert 2 <= MAX_RETRIES <= 10

    def test_timeout_bounded_below_sdk_default(self) -> None:
        # Anthropic SDK default is 600s (10 minutes). Ours must be lower to
        # make hung requests fail loudly and hand off to retry.
        assert 30.0 <= REQUEST_TIMEOUT_SEC < 600.0


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
    def __init__(self, text: str, usage: _FakeUsage) -> None:
        self.content = [_FakeBlock(text)]
        self.usage = usage


class _FakeMessages:
    def __init__(
        self, text: str = '{"ok": true}', usage: _FakeUsage | None = None
    ) -> None:
        self.calls: list[dict[str, Any]] = []
        self._text = text
        self._usage = usage or _FakeUsage()

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return _FakeResponse(self._text, self._usage)


class _FakeClient:
    def __init__(
        self, text: str = '{"ok": true}', usage: _FakeUsage | None = None
    ) -> None:
        self.messages = _FakeMessages(text, usage)


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
