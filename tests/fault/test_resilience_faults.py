"""The two faults WO-A04 owns, held open rather than guessed at
(WO-A06 scenario 8, and the rate limiter's outage half).

**One of the two is now asserted; the other is still skipped.** Neither
was ever a placeholder for work nobody intended to do: each names the
deliverable that unblocks it and says what it will assert, so landing
the dependency is a matter of deleting a decorator and filling in one
attribute set rather than rediscovering the scenario from scratch. The
rate limiter's half is the proof that this pays: it was written by
WO-A06, waited two waves, and the assertion below is very close to the
one its docstring specified — down to requiring that the degradation
counter stay *separate* from `rate_limit_rejections_total`.

`skip` and not `xfail`. `xfail_strict = true` is on, so an `xfail` that
starts passing fails the suite — which is precisely what would have
happened the moment WO-A04 merged, turning a peer's green PR red for no
reason anyone would enjoy diagnosing.

---

**Scenario 8 as written no longer exists**, and is still skipped. WO-A06
asked for "breaker open (from A04 if merged)". WO-A04 was revised on
2026-09-04 to build a **retry token bucket instead of a circuit
breaker**, and instructs its author in as many words not to implement a
breaker: the bucket adds no second mode to test, is roughly twenty lines
against the Redis that already exists, and addresses the measured
problem — multiplicative retry amplification across five levels —
directly. So the fault to assert is not "the breaker is open" but "the
retry budget is exhausted", which is a different observable with a
different triple, and it has no emitter yet.

**The rate limiter's outage half is live.** WO-A04 deliverable 6 landed
the degrade-and-serve behaviour, so the code and event legs became true;
what kept the decorator on for another two waves was the **metric** leg,
because `record_degradation` was an in-process `Counter` and a WARNING
rather than an OTel instrument (ADR 0068 deferred the fold-in). WO-D5
supplied it (`research_degradations_total`, ADR 0081) and the test below
now asserts all three, plus the separation the original docstring
insisted on: an outage moves the degradation counter and leaves
`rate_limit_rejections_total` completely flat, because fail-open means
nobody was rejected.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from redis import exceptions as redis_exceptions

from src.api.auth import RedisRateLimiter
from src.resilience import degradation_counts, reset_degradation_counts

from .conftest import TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]


@pytest.mark.skip(
    reason=(
        "WO-A04 owns the retry token bucket that replaced this work order's "
        "circuit breaker; `src/resilience.py` does not exist on this branch."
    )
)
def test_an_exhausted_retry_budget_sheds_retries_without_failing_the_success_path() -> None:
    """The triple to assert once `src/resilience.py` lands.

    - **code** — the bucket throttles *retries*, so a call that has no
      budget left surfaces as whatever the underlying dependency's
      failure already was (`upstream_arxiv` for arXiv, and today
      `internal_unexpected` for the model provider). The bucket must
      not invent a code of its own, because "we chose not to retry" is
      not a different failure from the caller's point of view.
    - **event** — a new registered name in `KNOWN_EVENTS`, emitted when
      the budget is refused, carrying the dependency it was refused for.
    - **metric** — a counter of refused retries by dependency. That
      number is the whole point of preferring a bucket to a breaker:
      it is a continuous measure of how much load shedding is
      happening, rather than a mode flag that is either on or off.

    And the property that distinguishes a bucket from a breaker at all:
    with the budget exhausted, a request that *succeeds on its first
    attempt* must be entirely unaffected. A breaker fails those too.
    """


class _RedisWithNoPipeline:
    """A Redis client whose pipeline is gone, and nothing else.

    The limiter reaches Redis through exactly one call — a transactional
    pipeline in `RedisRateLimiter._count` — so breaking that and leaving
    every other command working isolates the limiter's outage from the
    job store's. That isolation is the point: the request has to still
    be *served*, and a client that failed everything could not show it.
    """

    def __init__(self) -> None:
        self.pipeline_attempts = 0

    def pipeline(self, *_args: Any, **_kwargs: Any) -> Any:
        self.pipeline_attempts += 1
        raise redis_exceptions.ConnectionError(
            "Error 111 connecting to cache.internal:6379. Connection refused."
        )


async def test_the_rate_limiter_degrades_to_memory_rather_than_refusing_service(
    triple: TripleObserver, caplog: pytest.LogCaptureFixture
) -> None:
    """The triple this test was written to hold open, now assertable.

    It was skipped for two waves and the reason changed underneath it.
    WO-A04 landed the degrade-and-serve behaviour, so the code and event
    legs became true — but the **metric** leg this docstring demanded
    did not exist: `record_degradation` kept an in-process `Counter` and
    wrote a WARNING, and ADR 0068 recorded the OTel fold-in as a
    follow-up rather than editing a peer's file mid-wave. WO-D5 is that
    follow-up (ADR 0081), and the assertion below is the one this file
    has been holding a decorator open for.

    - **code** — none. A degraded limiter *serves* the request: nothing
      raises out of `check_and_record`.
    - **event** — `resilience_degraded` at WARNING, naming the component
      and a bounded reason, and carrying the exception's class name
      rather than its message (ADR 0042).
    - **metric** — `research_degradations_total{rung="weakened_guarantee",
      component="rate_limiter"}`, and **not**
      `rate_limit_rejections_total`. "The limiter is down" and "a key hit
      its cap" are different operational facts, and folding them into one
      series would make a Redis outage look like a traffic spike. That
      separation is asserted here in both directions.
    """
    reset_degradation_counts()
    client = _RedisWithNoPipeline()
    # Comfortably above the two calls below: the fallback is a *real*
    # limiter, so a cap of 1 would 429 the second call and the fault
    # under test would be hidden behind a rejection that is working as
    # designed. What is being asserted here is the degradation, not the
    # fallback's own arithmetic.
    limiter = RedisRateLimiter(client, limit_per_hour=5)

    with caplog.at_level(logging.WARNING):
        # Twice, on one key: fail-open serves both, and the counter has
        # to move on both. A degradation that counted only its first
        # occurrence would make a five-minute outage and a five-hour one
        # look the same.
        await limiter.check_and_record("key-a")
        await limiter.check_and_record("key-a")

    assert client.pipeline_attempts == 2, "the limiter stopped trying Redis"

    # Leg 2 — the event, at WARNING, with the class name and not the
    # message. The DSN in the exception text must not reach the log.
    record = triple.records("resilience_degraded")[0]
    assert record.levelno == logging.WARNING
    assert getattr(record, "component", None) == "rate_limiter"
    assert getattr(record, "reason", None) == "redis_unavailable"
    assert getattr(record, "error", None) == "ConnectionError"
    assert "cache.internal" not in record.getMessage()

    # Leg 3 — the metric that did not exist when this test was written.
    point = triple.point(
        "research_degradations_total",
        rung="weakened_guarantee",
        component="rate_limiter",
    )
    assert point.value == 2, "both degraded submits have to count, not just the first"

    # The separation this docstring insisted on, asserted rather than
    # described: an outage moves the degradation counter and leaves the
    # rejection counter completely flat. Nobody was rejected — that is
    # what fail-open means, and it is why an operator watching only
    # `rate_limit_rejections_total` sees an idle limiter during an
    # outage (docs/runbooks/redis-loss.md opens on this).
    triple.assert_not_recorded("rate_limit_rejections_total")

    # And the in-process counter ADR 0068 shipped still agrees with the
    # instrument, so `/healthz` and the dashboard cannot fork.
    assert degradation_counts()[("rate_limiter", "redis_unavailable")] == 2
