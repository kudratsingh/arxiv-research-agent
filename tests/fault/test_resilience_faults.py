"""The two faults WO-A04 owns, held open rather than guessed at
(WO-A06 scenario 8, and the rate limiter's outage half).

Both tests here are skipped. Neither is a placeholder for work nobody
intends to do: each names the deliverable that unblocks it, and each
says what it will assert, so landing WO-A04 is a matter of deleting a
decorator and filling in one attribute set rather than rediscovering
the scenario from scratch.

`skip` and not `xfail`. `xfail_strict = true` is on, so an `xfail` that
starts passing fails the suite — which is precisely what would happen
the moment WO-A04 merged, turning a peer's green PR red for no reason
anyone would enjoy diagnosing.

---

**Scenario 8 as written no longer exists.** WO-A06 asked for "breaker
open (from A04 if merged)". WO-A04 was revised on 2026-09-04 to build a
**retry token bucket instead of a circuit breaker**, and instructs its
author in as many words not to implement a breaker: the bucket adds no
second mode to test, is roughly twenty lines against the Redis that
already exists, and addresses the measured problem — multiplicative
retry amplification across five levels — directly. So the fault to
assert is not "the breaker is open" but "the retry budget is exhausted",
which is a different observable with a different triple.

**The rate limiter's outage half** is WO-A04 deliverable 6. Today
`RedisRateLimiter.check_and_record` runs an unguarded `pipe.execute()`,
so a Redis outage reaches the boundary as `internal_unexpected` and a
500 — and `rate_limit_rejections_total` stays flat, because
`record_rate_limit_rejection` fires only on a genuine over-cap. A04
replaces that with degrade-and-serve plus a degradation counter.
Asserting today's behaviour would pin exactly what A04 is removing.
"""

from __future__ import annotations

import pytest

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


@pytest.mark.skip(
    reason=(
        "WO-A04 deliverable 6 makes the rate limiter degrade to the in-memory "
        "backend on a Redis failure instead of raising; pinning today's 500 "
        "would hand that work order a red test."
    )
)
def test_the_rate_limiter_degrades_to_memory_rather_than_refusing_service() -> None:
    """The triple to assert once the limiter degrades.

    - **code** — none. A degraded limiter *serves* the request, so the
      submit answers 202 where it answers 500 today.
    - **event** — the degradation line WO-A04 adds, at WARNING, naming
      the backend it fell back to.
    - **metric** — the degradation counter. It has to be separate from
      `rate_limit_rejections_total{backend}`: "the limiter is down" and
      "a key hit its cap" are different operational facts, and folding
      them into one series would make a Redis outage look like a
      traffic spike.

    Fail-open versus fail-closed is a real decision and WO-A04's ADR
    0068 is where the reasoning belongs; this tier only asserts that
    whichever way it goes, it is *visible*. Today it is not: an outage
    contributes nothing to any rate-limit series at all.
    """
