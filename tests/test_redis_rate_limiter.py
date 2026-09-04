"""Redis-backed rate limiter (ADR 0037).

The ADR-0033 `InMemoryRateLimiter` is per-worker, so a 100/hour cap
under 4-worker uvicorn becomes 400/hour effective. `RedisRateLimiter`
uses a shared ZSET on `ratelimit:{key_id}` so the counter is
correct across processes.

These tests exercise the pipeline shape against `fakeredis`:
under-cap, over-cap → 429 with `Retry-After`, sliding window, and
per-key isolation. The two-clients-one-backend fixture models
"two workers hitting the same Redis" — the same pattern used for
the ADR-0034 HITL and ADR-0035 SSE tests.

ADR 0068 adds the failure half: what the limiter does when the shared
counter is *not* there. `TestARedisOutageDegradesRatherThanFiveHundreds`
is that half, and it needs a Redis that fails rather than one that
works — which is what the doubles below are for.
"""

from __future__ import annotations

from typing import Any

import fakeredis.aioredis
import pytest

from src.api.auth import RedisRateLimiter
from src.errors import RateLimitedError
from src.resilience import degradation_counts, reset_degradation_counts

pytestmark = [pytest.mark.integration, pytest.mark.security]


@pytest.fixture
async def shared_backend() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


class _BrokenPipeline:
    """A pipeline context manager whose `execute` always fails."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aenter__(self) -> _BrokenPipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, _name: str) -> Any:
        """Buffer any queued command, which is what a real pipeline does."""
        return lambda *args, **kwargs: None

    async def execute(self) -> list[Any]:
        raise self._exc


class _BrokenRedis:
    """A client whose every call raises, standing in for a down Redis.

    The builtin `ConnectionError` rather than `redis.exceptions`': the
    limiter's guard is deliberately not keyed on one client library's
    exception tree, and using an unrelated type proves it.
    """

    def pipeline(self, *, transaction: bool = True) -> _BrokenPipeline:
        return _BrokenPipeline(ConnectionError("redis is down"))

    async def zrem(self, *args: Any, **kwargs: Any) -> int:
        raise ConnectionError("redis is down")

    async def zrange(self, *args: Any, **kwargs: Any) -> list[Any]:
        raise ConnectionError("redis is down")


class _WorkingPipeline(_BrokenPipeline):
    """A pipeline that answers "two records", which is over a cap of one."""

    async def execute(self) -> list[Any]:
        return [0, 1, 2, True]


class _BrokenAfterPipeline(_BrokenRedis):
    """Redis that answers the pipeline and then dies on the rollback.

    The over-cap branch makes two more round trips after `execute`, and
    a guard that covered only the pipeline would leave them exposed —
    on the branch that runs during exactly the traffic a Redis blip
    tends to accompany.
    """

    def pipeline(self, *, transaction: bool = True) -> _BrokenPipeline:
        return _WorkingPipeline(ConnectionError("unused"))


class TestRedisRateLimiter:
    @pytest.mark.asyncio
    async def test_under_limit_never_raises(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        rl = RedisRateLimiter(shared_backend, limit_per_hour=5)
        for _ in range(5):
            await rl.check_and_record("k")

    @pytest.mark.asyncio
    async def test_over_limit_raises_429(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        rl = RedisRateLimiter(shared_backend, limit_per_hour=3)
        for i in range(3):
            await rl.check_and_record("k", now=100.0 + i)
        with pytest.raises(RateLimitedError) as exc:
            await rl.check_and_record("k", now=103.0)
        assert exc.value.http_status == 429
        headers = exc.value.headers or {}
        assert "Retry-After" in headers
        assert int(headers["Retry-After"]) > 0

    @pytest.mark.asyncio
    async def test_window_slides(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        rl = RedisRateLimiter(
            shared_backend, limit_per_hour=2, window_sec=100
        )
        await rl.check_and_record("k", now=0.0)
        await rl.check_and_record("k", now=50.0)
        # Third at t=200: first two are outside the 100s window.
        await rl.check_and_record("k", now=200.0)

    @pytest.mark.asyncio
    async def test_over_limit_rolls_back_the_current_record(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The Redis backend adds the current record BEFORE checking
        the count (single-pipeline fast path). When over cap, it
        rolls the record back via ZREM so a subsequent under-cap
        recovery attempt still succeeds."""
        from src.api.auth import RATE_LIMIT_KEY_PREFIX

        rl = RedisRateLimiter(
            shared_backend, limit_per_hour=2, window_sec=100
        )
        await rl.check_and_record("k", now=0.0)
        await rl.check_and_record("k", now=1.0)
        with pytest.raises(Exception):  # noqa: B017
            await rl.check_and_record("k", now=2.0)
        # After the rollback we should have exactly 2 records, not 3.
        count = await shared_backend.zcard(f"{RATE_LIMIT_KEY_PREFIX}k")
        assert count == 2

    @pytest.mark.asyncio
    async def test_buckets_are_isolated_per_key(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        rl = RedisRateLimiter(shared_backend, limit_per_hour=1)
        await rl.check_and_record("alice", now=100.0)
        # Alice at cap, but bob starts fresh.
        await rl.check_and_record("bob", now=100.0)

    @pytest.mark.asyncio
    async def test_counter_shared_across_client_instances(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The production win: two 'workers' (two RedisRateLimiter
        instances against the same Redis) see the same counter. This
        is what the InMemoryRateLimiter can't do."""
        worker_a = RedisRateLimiter(shared_backend, limit_per_hour=2)
        worker_b = RedisRateLimiter(shared_backend, limit_per_hour=2)
        await worker_a.check_and_record("k", now=100.0)
        await worker_b.check_and_record("k", now=101.0)
        # Third submit from either worker should hit the shared cap.
        with pytest.raises(RateLimitedError) as exc:
            await worker_a.check_and_record("k", now=102.0)
        assert exc.value.http_status == 429


class TestARedisOutageDegradesRatherThanFiveHundreds:
    """ADR 0068. The limiter used to be the outage.

    `check_and_record` ran an unguarded `pipe.execute()`, so a Redis
    blip raised through the FastAPI dependency and — with no exception
    handlers registered before ADR 0064 — answered every submit with an
    opaque 500. A defence that converts a dependency's bad minute into
    a total outage of the product is worse than the burst it prevents,
    which is why the policy is **degrade and serve**.

    What "degrade" must mean is the other half, and these tests pin it:
    a real per-worker limiter takes over, the weaker guarantee is
    counted and logged, and the 429 path still works while degraded.
    """

    @pytest.mark.asyncio
    async def test_a_redis_failure_serves_the_request_instead_of_raising(self) -> None:
        rl = RedisRateLimiter(_BrokenRedis(), limit_per_hour=5)
        await rl.check_and_record("k", now=100.0)

    @pytest.mark.asyncio
    async def test_the_degradation_is_counted(self) -> None:
        reset_degradation_counts()
        rl = RedisRateLimiter(_BrokenRedis(), limit_per_hour=5)
        await rl.check_and_record("k", now=100.0)
        await rl.check_and_record("k", now=101.0)
        assert degradation_counts()[("rate_limiter", "redis_unavailable")] == 2

    @pytest.mark.asyncio
    async def test_the_degradation_names_its_cause_at_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        rl = RedisRateLimiter(_BrokenRedis(), limit_per_hour=5)
        with caplog.at_level("WARNING"):
            await rl.check_and_record("k", now=100.0)
        record = next(r for r in caplog.records if r.getMessage() == "resilience_degraded")
        assert record.levelname == "WARNING"
        assert record.component == "rate_limiter"
        assert record.error == "ConnectionError"

    @pytest.mark.asyncio
    async def test_the_fallback_still_enforces_a_cap(self) -> None:
        """Degrading is not the same as switching the limiter off.

        A fleet of N workers caps a key at N x the limit while Redis is
        away, which is the ADR-0037 pre-Redis behaviour — weaker than
        the shared counter, and enormously stronger than nothing.
        """
        rl = RedisRateLimiter(_BrokenRedis(), limit_per_hour=2)
        await rl.check_and_record("k", now=100.0)
        await rl.check_and_record("k", now=101.0)
        with pytest.raises(RateLimitedError) as caught:
            await rl.check_and_record("k", now=102.0)
        assert caught.value.http_status == 429
        assert caught.value.code == "rate_limited"

    @pytest.mark.asyncio
    async def test_the_fallback_window_persists_across_failures(self) -> None:
        """One limiter, not one per failed request.

        A fallback constructed per failure would forget every request it
        had just counted, so a Redis outage would cap nothing at all
        while appearing to.
        """
        rl = RedisRateLimiter(_BrokenRedis(), limit_per_hour=1)
        await rl.check_and_record("k", now=100.0)
        with pytest.raises(RateLimitedError):
            await rl.check_and_record("k", now=101.0)

    @pytest.mark.asyncio
    async def test_a_failure_after_the_pipeline_also_degrades(self) -> None:
        """The rollback and the `Retry-After` read are Redis calls too.

        Guarding only `pipe.execute()` would have left two more
        unguarded round trips on the over-cap path — the branch that
        runs during exactly the traffic spike a Redis blip accompanies.
        """
        rl = RedisRateLimiter(_BrokenAfterPipeline(), limit_per_hour=1)
        await rl.check_and_record("k", now=100.0)

    @pytest.mark.asyncio
    async def test_a_healthy_redis_is_untouched_by_any_of_this(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The degradation path must be unreachable while Redis works."""
        reset_degradation_counts()
        rl = RedisRateLimiter(shared_backend, limit_per_hour=2)
        await rl.check_and_record("k", now=100.0)
        await rl.check_and_record("k", now=101.0)
        with pytest.raises(RateLimitedError):
            await rl.check_and_record("k", now=102.0)
        assert degradation_counts() == {}
