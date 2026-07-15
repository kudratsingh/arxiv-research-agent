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
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest

from src.api.auth import RedisRateLimiter

pytestmark = pytest.mark.integration


@pytest.fixture
async def shared_backend() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


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
        with pytest.raises(Exception) as exc:
            await rl.check_and_record("k", now=103.0)
        assert getattr(exc.value, "status_code", None) == 429
        headers = getattr(exc.value, "headers", {})
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
        with pytest.raises(Exception) as exc:
            await worker_a.check_and_record("k", now=102.0)
        assert getattr(exc.value, "status_code", None) == 429
