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
