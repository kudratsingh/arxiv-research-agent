"""Unit tests for the shared retrying HTTP session.

Verifies the `urllib3.Retry` policy is wired correctly: retry count,
backoff factor, retryable statuses, allowed methods, and that both
`http://` and `https://` schemes get the retry adapter.
"""

import pytest
from urllib3.util.retry import Retry

from src.config import Settings
from src.tools import http_session as http_session_module
from src.tools.http_session import RETRYABLE_STATUSES, build_retrying_session


class TestBuildRetryingSession:
    def _retry_policy(self, session) -> Retry:
        adapter = session.get_adapter("https://arxiv.org")
        return adapter.max_retries

    def test_uses_settings_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_session_module,
            "settings",
            Settings(http_max_retries=5, http_backoff_factor=2.0),
        )
        session = build_retrying_session()
        retry = self._retry_policy(session)
        assert retry.total == 5
        assert retry.backoff_factor == 2.0

    def test_explicit_args_override_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_session_module,
            "settings",
            Settings(http_max_retries=3, http_backoff_factor=1.0),
        )
        session = build_retrying_session(max_retries=7, backoff_factor=0.5)
        retry = self._retry_policy(session)
        assert retry.total == 7
        assert retry.backoff_factor == 0.5

    def test_retries_transient_statuses(self) -> None:
        session = build_retrying_session()
        retry = self._retry_policy(session)
        for status in (408, 425, 429, 500, 502, 503, 504):
            assert status in retry.status_forcelist

    def test_does_not_retry_400_or_401(self) -> None:
        # Client errors that aren't going to change on retry.
        session = build_retrying_session()
        retry = self._retry_policy(session)
        assert 400 not in retry.status_forcelist
        assert 401 not in retry.status_forcelist
        assert 403 not in retry.status_forcelist
        assert 404 not in retry.status_forcelist

    def test_respects_retry_after_header(self) -> None:
        session = build_retrying_session()
        retry = self._retry_policy(session)
        assert retry.respect_retry_after_header is True

    def test_allowed_methods_include_get(self) -> None:
        session = build_retrying_session()
        retry = self._retry_policy(session)
        assert "GET" in retry.allowed_methods

    def test_post_not_retried_by_default(self) -> None:
        # POST is not idempotent — must be opt-in per session.
        session = build_retrying_session()
        retry = self._retry_policy(session)
        assert "POST" not in retry.allowed_methods

    def test_http_and_https_both_mounted(self) -> None:
        session = build_retrying_session()
        http_adapter = session.get_adapter("http://example.com")
        https_adapter = session.get_adapter("https://example.com")
        assert http_adapter is not None
        assert https_adapter is not None
        # Same policy on both.
        assert http_adapter.max_retries.total == https_adapter.max_retries.total


class TestRetryableStatusesConstant:
    def test_covers_expected_transient_codes(self) -> None:
        for code in (408, 425, 429, 500, 502, 503, 504):
            assert code in RETRYABLE_STATUSES

    def test_does_not_include_non_transient_codes(self) -> None:
        for code in (200, 301, 400, 401, 403, 404):
            assert code not in RETRYABLE_STATUSES
