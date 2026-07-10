"""Unit tests for the `Job` model and `InMemoryJobStore`."""

from __future__ import annotations

import asyncio
import time

from src.api.jobs import (
    TERMINAL_STATUSES,
    InMemoryJobStore,
    Job,
    JobStatus,
    drain_events,
)


class TestJob:
    def test_defaults(self) -> None:
        job = Job(job_id="abc", query="q")
        assert job.status == JobStatus.pending
        assert job.started_at is None
        assert job.completed_at is None
        assert job.result is None
        assert job.error is None
        assert job.event_queue.maxsize == 1024

    def test_is_terminal_matches_status_set(self) -> None:
        for terminal in (JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled):
            assert Job(job_id="a", query="q", status=terminal).is_terminal()
        for non_terminal in (JobStatus.pending, JobStatus.running):
            assert not Job(job_id="a", query="q", status=non_terminal).is_terminal()

    def test_elapsed_returns_none_before_start(self) -> None:
        job = Job(job_id="abc", query="q")
        assert job.elapsed_sec() is None

    def test_elapsed_uses_completed_at_when_set(self) -> None:
        job = Job(job_id="abc", query="q")
        job.started_at = 100.0
        job.completed_at = 105.5
        assert job.elapsed_sec() == 5.5

    def test_elapsed_falls_back_to_now_while_running(self) -> None:
        job = Job(job_id="abc", query="q")
        job.started_at = time.time() - 2.0
        elapsed = job.elapsed_sec()
        assert elapsed is not None and 1.5 <= elapsed < 3.0

    def test_terminal_status_set_frozen(self) -> None:
        # Regression: the set of terminal statuses is load-bearing for
        # both the drainer and the SSE terminal-frame logic. Guard
        # against silent widening.
        assert frozenset(
            {JobStatus.succeeded, JobStatus.failed, JobStatus.cancelled}
        ) == TERMINAL_STATUSES


class TestInMemoryJobStore:
    async def test_create_then_get(self) -> None:
        store = InMemoryJobStore()
        job = Job(job_id="j1", query="q")
        await store.create(job)
        assert await store.get("j1") is job

    async def test_get_missing_returns_none(self) -> None:
        store = InMemoryJobStore()
        assert await store.get("nope") is None

    async def test_update_replaces(self) -> None:
        store = InMemoryJobStore()
        job = Job(job_id="j1", query="q")
        await store.create(job)
        job.status = JobStatus.running
        await store.update(job)
        got = await store.get("j1")
        assert got is not None
        assert got.status == JobStatus.running

    async def test_evict_older_than_removes_terminal_only(self) -> None:
        store = InMemoryJobStore()
        old_terminal = Job(job_id="old", query="q", status=JobStatus.succeeded)
        old_terminal.completed_at = time.time() - 10_000
        recent_terminal = Job(job_id="new", query="q", status=JobStatus.succeeded)
        recent_terminal.completed_at = time.time() - 5
        running = Job(job_id="run", query="q", status=JobStatus.running)
        running.started_at = time.time() - 10_000  # ancient but non-terminal

        for j in (old_terminal, recent_terminal, running):
            await store.create(j)

        evicted = await store.evict_older_than(retention_sec=3600)
        assert evicted == 1
        assert await store.get("old") is None
        assert await store.get("new") is not None
        # Non-terminal jobs are never evicted regardless of age.
        assert await store.get("run") is not None

    async def test_evict_ignores_terminal_without_completed_at(self) -> None:
        # Defensive: a job that ended without setting completed_at
        # shouldn't crash the evict path.
        store = InMemoryJobStore()
        job = Job(job_id="j", query="q", status=JobStatus.succeeded)
        job.completed_at = None
        await store.create(job)
        assert await store.evict_older_than(retention_sec=1) == 0
        assert await store.get("j") is not None

    async def test_concurrent_creates_are_isolated(self) -> None:
        # Regression for the store lock — concurrent creates from
        # separate tasks should all land without dropping any.
        store = InMemoryJobStore()

        async def create_one(i: int) -> None:
            await store.create(Job(job_id=f"j{i}", query="q"))

        await asyncio.gather(*(create_one(i) for i in range(50)))
        jobs = await store.all_jobs()
        assert len(jobs) == 50


class TestDrainEvents:
    async def test_yields_events_until_terminal(self) -> None:
        job = Job(job_id="j", query="q")
        await job.event_queue.put({"event": "node_started", "data": {"node": "planner"}})
        await job.event_queue.put({"event": "node_completed", "data": {"node": "planner"}})

        # Mark terminal so the drainer knows to exit after draining.
        job.status = JobStatus.succeeded
        await job.event_queue.put(
            {"event": "job_completed", "data": {"job_id": "j"}}
        )

        collected = [event async for event in drain_events(job)]
        assert [e["event"] for e in collected] == [
            "node_started",
            "node_completed",
            "job_completed",
        ]

    async def test_terminates_when_job_terminal_and_queue_empty(self) -> None:
        job = Job(job_id="j", query="q", status=JobStatus.succeeded)
        collected = [event async for event in drain_events(job)]
        assert collected == []
