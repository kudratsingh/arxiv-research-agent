"""Unit tests for the shared retrying HTTP session.

Verifies the `urllib3.Retry` policy is wired correctly: retry count,
backoff factor, retryable statuses, allowed methods, and that both
`http://` and `https://` schemes get the retry adapter.

`TestTheAdrZeroSixtyEightPolicy` covers what that policy gained
afterwards — Full Jitter, the call-chain clamp, a bounded `Retry-After`
and the retry token bucket — as properties of the `Retry` object the
adapter carries. That they change what a real socket does is
`tests/test_resilience_transport.py`'s claim, and a different tier.
"""

from collections.abc import Iterator

import pytest
from urllib3.util.retry import RequestHistory, Retry

from src.config import Settings
from src.resilience import reset_retry_budgets
from src.tools import http_session as http_session_module
from src.tools.http_session import (
    RETRYABLE_STATUSES,
    BudgetedRetry,
    build_retrying_session,
)

pytestmark = pytest.mark.unit


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


@pytest.fixture(autouse=True)
def _isolate_budgets() -> Iterator[None]:
    """The budget registry is process-wide and this file builds into it."""
    reset_retry_budgets()
    yield
    reset_retry_budgets()


class TestTheAdrZeroSixtyEightPolicy:
    """Full Jitter, the call-chain clamp, and a bounded `Retry-After`.

    All three are properties of the `Retry` object the adapter carries,
    so they are asserted here on the object; that they change what a
    real socket does is `tests/test_resilience_transport.py`'s job.
    """

    def _retry_policy(self, session) -> BudgetedRetry:
        return session.get_adapter("https://arxiv.org").max_retries

    def test_the_policy_is_the_budgeted_one(self) -> None:
        assert isinstance(self._retry_policy(build_retrying_session()), BudgetedRetry)

    def test_the_backoff_ceiling_comes_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """urllib3's own default is 120s — a fifth of a default job
        budget spent asleep inside one request."""
        monkeypatch.setattr(
            http_session_module, "settings", Settings(http_backoff_max_sec=7.0)
        )
        assert self._retry_policy(build_retrying_session()).backoff_max == 7.0

    def test_backoff_is_full_jitter_rather_than_urllib3s_addend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The draw covers `[0, min(cap, base * 2**n)]`, not a narrow
        band around the top of it — which is what decorrelates a fleet
        that all failed at the same instant."""
        monkeypatch.setattr(
            http_session_module,
            "settings",
            Settings(http_backoff_factor=1.0, http_backoff_max_sec=100.0),
        )
        policy = self._retry_policy(build_retrying_session())
        # Four consecutive non-redirect errors => attempt index 3 =>
        # ceiling of 8s.
        history = tuple(
            RequestHistory("GET", "https://arxiv.org", None, 503, None) for _ in range(4)
        )
        with_history = policy.new(history=history)

        draws = [with_history.get_backoff_time() for _ in range(400)]

        assert max(draws) <= 8.0
        assert min(draws) < 1.0
        assert max(draws) > 6.0

    def test_the_first_retry_is_still_immediate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Kept identical to the base class: only the shape of the draw
        changes, not when backoff starts."""
        policy = self._retry_policy(build_retrying_session())
        assert policy.get_backoff_time() == 0.0

    def test_a_declared_timeout_clamps_the_retry_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_session_module,
            "settings",
            Settings(
                http_max_retries=5,
                api_job_timeout_sec=600,
                http_call_chain_budget_fraction=0.25,
            ),
        )
        # 150s of budget at 60s per attempt affords two attempts, so
        # one retry survives out of the five configured.
        session = build_retrying_session(timeout_sec=60.0)
        assert self._retry_policy(session).total == 1

    def test_no_declared_timeout_leaves_the_count_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Every call site that has not yet declared its per-attempt
        timeout keeps exactly the behaviour it had."""
        monkeypatch.setattr(
            http_session_module, "settings", Settings(http_max_retries=5)
        )
        assert self._retry_policy(build_retrying_session()).total == 5

    def test_retry_after_is_bounded_by_the_call_chain_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """urllib3 honours a `Retry-After` of up to six hours by default.

        A delay longer than the chain's whole budget cannot help the
        job — the job times out first — so sleeping a worker thread
        through it is the worst of both outcomes.
        """
        monkeypatch.setattr(
            http_session_module,
            "settings",
            Settings(api_job_timeout_sec=600, http_call_chain_budget_fraction=0.25),
        )
        policy = self._retry_policy(build_retrying_session())
        assert policy.retry_after_max == 150
        assert policy.retry_after_max < Retry.DEFAULT_RETRY_AFTER_MAX

    def test_the_budget_is_attached_when_the_flag_is_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            http_session_module, "settings", Settings(enable_retry_budget=True)
        )
        monkeypatch.setattr(
            "src.resilience.settings", Settings(enable_retry_budget=True)
        )
        reset_retry_budgets()
        assert self._retry_policy(build_retrying_session()).budget is not None

    def test_the_flag_off_restores_the_pre_budget_behaviour(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.resilience.settings", Settings(enable_retry_budget=False)
        )
        reset_retry_budgets()
        assert self._retry_policy(build_retrying_session()).budget is None
