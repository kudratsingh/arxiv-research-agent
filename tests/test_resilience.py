"""The resilience policy's primitives (ADR 0068).

Four claims, each of which the repository could not make before:

- a retry budget throttles *retries* and nothing else, so a healthy
  caller cannot tell it is there;
- backoff is Full Jitter, drawn over the whole interval rather than
  around its ceiling;
- an HTTP retry envelope is clamped against the job budget the way
  `src/llm.py` has always clamped the model's, and says so when it
  bites;
- a wait inside a node is interruptible, so a cancelled job does not
  sleep through its drain window.

The transport-level half — that these actually change what a real
`requests` call does over a real socket — is
`tests/test_resilience_transport.py`, which is a different tier.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator

import pytest

from src.cancellation import CancelToken, JobCancelledError, bind_cancel_token, reset_cancel_token
from src.config import Settings
from src.errors import UpstreamError
from src.observability.metrics import DEGRADATION_RUNG_WEAKENED_GUARANTEE
from src.resilience import (
    DEPENDENCY_ARXIV,
    DEPENDENCY_HTTP,
    RetryBudget,
    clamped_retry_envelope,
    degradation_counts,
    full_jitter_delay,
    get_retry_budget,
    interruptible_sleep,
    record_degradation,
    reset_clamp_warnings,
    reset_degradation_counts,
    reset_retry_budgets,
)
from src.tools.arxiv_search import ArxivUnavailableError

pytestmark = pytest.mark.unit


class FakeClock:
    """A monotonic source a test moves by hand.

    The budget's refill is a function of elapsed time, so the only way
    to test it without sleeping is to own the clock. Not the shared
    `frozen_clock` fixture: this one is passed in as `time_source`
    rather than patched globally, which keeps the rest of the process
    on the real clock.
    """

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _budget(
    *,
    capacity: float = 3.0,
    refill_per_sec: float = 1.0,
    success_refund: float = 0.5,
    clock: FakeClock | None = None,
) -> RetryBudget:
    return RetryBudget(
        name="test",
        capacity=capacity,
        refill_per_sec=refill_per_sec,
        success_refund=success_refund,
        time_source=clock or FakeClock(),
    )


@pytest.fixture(autouse=True)
def _isolate_process_state() -> Iterator[None]:
    """Budgets, degradation counters and clamp warnings are process-wide;
    the suite is one process.

    Autouse, and on both sides of the test, because the leak is silent
    in exactly one direction: a test that drains a shared bucket makes
    a *later* test fail, in a different file, with an error that names
    neither of them. The clamp's warn-once set leaks the same way and
    worse — it makes a later test see *no* warning, which reads as the
    warning having been removed.
    """
    reset_retry_budgets()
    reset_degradation_counts()
    reset_clamp_warnings()
    yield
    reset_retry_budgets()
    reset_degradation_counts()
    reset_clamp_warnings()


class TestTheBudgetIsAPassThroughWhileItIsFull:
    """The property that makes this a budget and not a breaker."""

    def test_a_full_budget_grants_every_retry_it_is_asked_for(self) -> None:
        budget = _budget(capacity=10.0)
        assert [budget.try_spend() for _ in range(10)] == [True] * 10

    def test_a_granted_retry_costs_exactly_one_token(self) -> None:
        budget = _budget(capacity=3.0)
        budget.try_spend()
        assert budget.tokens == pytest.approx(2.0)

    def test_nothing_is_spent_by_a_success(self) -> None:
        """A first attempt never consults the budget; only a retry does.

        Asserted through the accounting rather than through a call
        count: `on_success` is the *only* thing a healthy call does to
        the bucket, and it must move tokens up, never down.
        """
        clock = FakeClock()
        budget = _budget(capacity=3.0, success_refund=0.5, clock=clock)
        budget.try_spend()
        budget.on_success()
        assert budget.tokens == pytest.approx(2.5)


class TestExhaustion:
    def test_the_budget_refuses_once_it_is_empty(self) -> None:
        budget = _budget(capacity=2.0)
        assert budget.try_spend() is True
        assert budget.try_spend() is True
        assert budget.try_spend() is False

    def test_a_refusal_is_counted(self) -> None:
        budget = _budget(capacity=1.0)
        budget.try_spend()
        budget.try_spend()
        budget.try_spend()
        assert budget.exhaustions == 2

    def test_an_exhausted_budget_stays_exhausted_without_time_or_successes(self) -> None:
        """The point of the mechanism: during an outage, retries stop.

        No time passes (the clock is frozen) and no call succeeds, so
        there is no source of tokens — which is exactly the state a
        dependency-wide outage produces.
        """
        clock = FakeClock()
        budget = _budget(capacity=1.0, clock=clock)
        budget.try_spend()
        assert [budget.try_spend() for _ in range(5)] == [False] * 5


class TestRefill:
    def test_time_returns_tokens_at_the_configured_rate(self) -> None:
        clock = FakeClock()
        budget = _budget(capacity=10.0, refill_per_sec=2.0, clock=clock)
        for _ in range(10):
            budget.try_spend()
        assert budget.tokens == pytest.approx(0.0)

        clock.advance(3.0)

        assert budget.tokens == pytest.approx(6.0)

    def test_time_refill_is_the_only_recovery_a_dead_dependency_offers(self) -> None:
        """Why `refill_per_sec` must be > 0, stated as a test.

        With no time refill, a fully drained bucket could only be
        refilled by successes — which is precisely what an outage is
        denying — so the process would never retry again, even after
        the dependency came back.
        """
        clock = FakeClock()
        budget = _budget(capacity=1.0, refill_per_sec=0.5, clock=clock)
        budget.try_spend()
        assert budget.try_spend() is False

        clock.advance(2.0)

        assert budget.try_spend() is True

    def test_refill_never_exceeds_capacity(self) -> None:
        clock = FakeClock()
        budget = _budget(capacity=3.0, refill_per_sec=1.0, clock=clock)
        clock.advance(10_000.0)
        assert budget.tokens == pytest.approx(3.0)

    def test_a_success_refunds_its_ratio_share(self) -> None:
        clock = FakeClock()
        budget = _budget(capacity=5.0, refill_per_sec=0.0001, success_refund=0.2, clock=clock)
        for _ in range(5):
            budget.try_spend()
        for _ in range(5):
            budget.on_success()
        assert budget.tokens == pytest.approx(1.0, abs=1e-3)

    def test_a_success_refund_never_exceeds_capacity(self) -> None:
        budget = _budget(capacity=2.0, success_refund=1.0)
        for _ in range(10):
            budget.on_success()
        assert budget.tokens == pytest.approx(2.0)


class TestConcurrentSpending:
    def test_two_threads_cannot_over_issue_the_last_token(self) -> None:
        """The graph runs nodes in a thread pool, so one budget is contended.

        Without the lock, two threads read the same token count and both
        spend it — over-issuing retries at the exact moment the budget
        exists to withhold them.
        """
        budget = _budget(capacity=50.0, refill_per_sec=0.0001)
        granted: list[bool] = []
        granted_lock = threading.Lock()
        start = threading.Barrier(8)

        def worker() -> None:
            start.wait()
            for _ in range(25):
                ok = budget.try_spend()
                with granted_lock:
                    granted.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sum(granted) == 50


class TestTheSharedBudgetRegistry:
    def test_one_budget_per_dependency_shared_across_callers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.resilience.settings", Settings(enable_retry_budget=True))
        first = get_retry_budget(DEPENDENCY_ARXIV)
        second = get_retry_budget(DEPENDENCY_ARXIV)
        assert first is second

    def test_dependencies_do_not_share_a_bucket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An arXiv outage must not spend the retries PDF downloads need."""
        monkeypatch.setattr("src.resilience.settings", Settings(enable_retry_budget=True))
        assert get_retry_budget(DEPENDENCY_ARXIV) is not get_retry_budget(DEPENDENCY_HTTP)

    def test_the_flag_off_removes_the_budget_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.resilience.settings", Settings(enable_retry_budget=False))
        assert get_retry_budget(DEPENDENCY_ARXIV) is None

    def test_an_unknown_dependency_is_refused_rather_than_invented(self) -> None:
        """A typo would otherwise create a private bucket that never throttles."""
        with pytest.raises(ValueError, match="unknown retry-budget dependency"):
            get_retry_budget("arixv")

    def test_settings_are_read_at_first_use_not_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "src.resilience.settings",
            Settings(enable_retry_budget=True, retry_budget_capacity=7),
        )
        budget = get_retry_budget(DEPENDENCY_ARXIV)
        assert budget is not None
        assert budget.capacity == pytest.approx(7.0)


class TestFullJitter:
    """`sleep = random(0, min(cap, base * 2**attempt))`."""

    def test_the_delay_never_exceeds_the_exponential_ceiling(self) -> None:
        rng = random.Random(1)
        for attempt in range(6):
            ceiling = min(20.0, 1.0 * 2**attempt)
            for _ in range(200):
                assert 0.0 <= full_jitter_delay(attempt, base_sec=1.0, cap_sec=20.0, rng=rng) <= ceiling

    def test_the_cap_binds_before_the_exponent_explodes(self) -> None:
        rng = random.Random(2)
        for _ in range(200):
            assert full_jitter_delay(30, base_sec=1.0, cap_sec=5.0, rng=rng) <= 5.0

    def test_the_draw_covers_the_whole_interval_rather_than_its_top(self) -> None:
        """The property that separates Full Jitter from "exponential plus a bit".

        urllib3's own `backoff_jitter` adds a small uniform term on top
        of the full exponential delay, so every worker still wakes
        inside a narrow window near the ceiling. Full Jitter draws from
        zero, which is what decorrelates a synchronised fleet — so the
        sample has to reach both ends.
        """
        rng = random.Random(3)
        draws = [full_jitter_delay(3, base_sec=1.0, cap_sec=100.0, rng=rng) for _ in range(500)]
        assert min(draws) < 0.8
        assert max(draws) > 7.2

    def test_a_zero_base_yields_no_delay(self) -> None:
        assert full_jitter_delay(5, base_sec=0.0, cap_sec=20.0) == 0.0


class TestTheRetryEnvelopeClamp:
    """The shape `src/llm.py:62-91` established, applied to HTTP."""

    def test_an_envelope_that_fits_is_left_alone(self) -> None:
        assert (
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=25.0, budget_sec=150.0, dependency="arxiv"
            )
            == 3
        )

    def test_an_envelope_that_does_not_fit_is_trimmed(self) -> None:
        # 4 attempts x 60s = 240s against a 150s budget: only two
        # attempts are affordable, so one retry survives.
        assert (
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=60.0, budget_sec=150.0, dependency="arxiv"
            )
            == 1
        )

    def test_one_attempt_always_survives_an_absurd_timeout(self) -> None:
        """Refusing to call at all is a worse answer than one long attempt.

        `src/llm.py` makes the same choice for the same reason: a
        per-attempt timeout larger than the whole budget is an
        operator's explicit decision, not a bug to route around.
        """
        assert (
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=9_000.0, budget_sec=150.0, dependency="arxiv"
            )
            == 0
        )

    def test_the_clamp_says_so_when_it_bites(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            clamped_retry_envelope(
                configured_retries=5, timeout_sec=100.0, budget_sec=150.0, dependency="arxiv"
            )
        records = [r for r in caplog.records if r.getMessage() == "retry_envelope_clamped"]
        assert len(records) == 1
        assert records[0].levelname == "WARNING"
        assert records[0].dependency == "arxiv"  # type: ignore[attr-defined]
        assert records[0].configured_max_retries == 5  # type: ignore[attr-defined]
        assert records[0].max_retries == 0  # type: ignore[attr-defined]

    def test_a_clamp_that_does_not_bite_stays_quiet(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=1.0, budget_sec=150.0, dependency="arxiv"
            )
        assert [r for r in caplog.records if r.getMessage() == "retry_envelope_clamped"] == []

    def test_the_same_clamp_says_it_once_however_often_it_happens(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Once per distinct clamp per process, not once per call.

        `pdf_parser` builds a session per download and a run downloads
        one PDF per paper, so before this the same clamp announced
        itself ten times a job. The way a WARNING stops being read is by
        repeating; `costs._unpriced_warned` is the same guard for the
        same reason, and this follows it rather than inventing a second
        shape.

        The clamp itself is not deduplicated — only its reporting. Every
        call still returns the trimmed count.
        """
        with caplog.at_level("WARNING"):
            returned = [
                clamped_retry_envelope(
                    configured_retries=3,
                    timeout_sec=60.0,
                    budget_sec=150.0,
                    dependency="http",
                )
                for _ in range(10)
            ]

        assert returned == [1] * 10
        assert (
            len([r for r in caplog.records if r.getMessage() == "retry_envelope_clamped"])
            == 1
        )

    def test_a_clamp_that_differs_in_any_respect_still_speaks(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The half that keeps warn-once from becoming warn-never.

        `dependency` is a two-value vocabulary and every non-arXiv
        caller shares `http`, so two call sites can clamp to the same
        retry count for completely different reasons. Keyed on the whole
        determinant, both are reported; keyed on `(dependency,
        clamped)`, the second misconfiguration would be silenced on the
        strength of having reported the first.
        """
        with caplog.at_level("WARNING"):
            # Same dependency, same clamped value (1), different
            # per-attempt cost — a different fact about a different
            # call site.
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=60.0, budget_sec=150.0, dependency="http"
            )
            clamped_retry_envelope(
                configured_retries=3, timeout_sec=70.0, budget_sec=150.0, dependency="http"
            )

        records = [r for r in caplog.records if r.getMessage() == "retry_envelope_clamped"]
        assert len(records) == 2
        assert [r.timeout_sec for r in records] == [60.0, 70.0]  # type: ignore[attr-defined]


class TestDegradationIsVisible:
    """`02-STANDARDS.md` §5.3: every rung emits a distinct marker."""

    def test_a_degradation_is_counted_by_component_and_reason(self) -> None:
        record_degradation(
            rung=DEGRADATION_RUNG_WEAKENED_GUARANTEE,
            component="rate_limiter",
            reason="redis_unavailable",
        )
        record_degradation(
            rung=DEGRADATION_RUNG_WEAKENED_GUARANTEE,
            component="rate_limiter",
            reason="redis_unavailable",
        )
        assert degradation_counts()[("rate_limiter", "redis_unavailable")] == 2

    def test_a_degradation_logs_at_warning_with_its_cause(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            record_degradation(
                rung=DEGRADATION_RUNG_WEAKENED_GUARANTEE,
                component="rate_limiter",
                reason="redis_unavailable",
                error="ConnectionError",
            )
        record = next(r for r in caplog.records if r.getMessage() == "resilience_degraded")
        assert record.levelname == "WARNING"
        assert record.component == "rate_limiter"  # type: ignore[attr-defined]
        assert record.reason == "redis_unavailable"  # type: ignore[attr-defined]
        assert record.error == "ConnectionError"  # type: ignore[attr-defined]
        # `reason` is a log field and `rung` is a metric attribute, and
        # they do not cross. ADR 0081's cardinality argument rests on
        # that split, so it is asserted rather than assumed.
        assert not hasattr(record, "rung")

    def test_the_snapshot_cannot_be_mutated_through(self) -> None:
        record_degradation(
            rung=DEGRADATION_RUNG_WEAKENED_GUARANTEE,
            component="rate_limiter",
            reason="redis_unavailable",
        )
        snapshot = dict(degradation_counts())
        snapshot[("rate_limiter", "redis_unavailable")] = 99
        assert degradation_counts()[("rate_limiter", "redis_unavailable")] == 1

    def test_the_rung_is_required_rather_than_defaulted(self) -> None:
        """A defaulted rung would silently mis-attribute the next caller.

        The default could only be `weakened_guarantee` — the rung of the
        only caller on this branch — so a second caller degrading down a
        *different* rung would be counted under this one with no signal
        at all. That is "degradation makes the dashboard look better
        while the product gets worse" reintroduced one layer above the
        place `record_degradation` exists to prevent it (ADR 0081).
        """
        with pytest.raises(TypeError):
            record_degradation(  # type: ignore[call-arg]
                component="rate_limiter", reason="redis_unavailable"
            )


class TestInterruptibleSleep:
    def test_it_waits_when_nothing_is_cancelled(self) -> None:
        started = time.monotonic()
        interruptible_sleep(0.15, poll_sec=0.01)
        assert time.monotonic() - started >= 0.14

    def test_a_non_positive_wait_returns_at_once(self) -> None:
        started = time.monotonic()
        interruptible_sleep(0.0)
        assert time.monotonic() - started < 0.05

    def test_an_already_cancelled_job_never_sleeps(self) -> None:
        token = CancelToken("job-1")
        token.cancel("shutdown")
        scope = bind_cancel_token(token)
        try:
            started = time.monotonic()
            with pytest.raises(JobCancelledError):
                interruptible_sleep(30.0)
            assert time.monotonic() - started < 0.5
        finally:
            reset_cancel_token(scope)

    def test_a_cancel_mid_wait_is_noticed_within_one_poll(self) -> None:
        """The measured failure this closes: a cancelled job could burn
        its whole 30s drain window on `time.sleep(3)` calls it was never
        going to use (`01-BASELINE.md` §2)."""
        token = CancelToken("job-2")
        scope = bind_cancel_token(token)
        canceller = threading.Timer(0.05, token.cancel, args=("job_timeout",))
        try:
            canceller.start()
            started = time.monotonic()
            with pytest.raises(JobCancelledError):
                interruptible_sleep(10.0, poll_sec=0.01)
            assert time.monotonic() - started < 1.0
        finally:
            canceller.cancel()
            reset_cancel_token(scope)

    def test_no_bound_token_means_no_behaviour_change(self) -> None:
        """The CLI and the eval runner call the agents directly."""
        interruptible_sleep(0.01)


class TestTheFailFastFailureIsAnUpstreamCode:
    def test_an_exhausted_budget_surfaces_as_upstream_arxiv(self) -> None:
        """Not a new code, and deliberately so.

        A retry budget changes *when* a dependency's failure is
        reported, never *what* it is: arXiv is still the thing that did
        not answer. `ArxivUnavailableError` already carries
        `upstream_arxiv`, and the transport test proves this is the
        class a budget-exhausted search actually raises.
        """
        assert issubclass(ArxivUnavailableError, UpstreamError)
        assert ArxivUnavailableError.code == "upstream_arxiv"
        assert ArxivUnavailableError.retryable is True
