"""A worker dies mid-job (WO-A06 scenario 5).

Under `job_store=redis` a non-terminal row carries no TTL, so a worker
that exits without a terminal write leaves the job `running` forever:
`GET /research/{id}` keeps answering `running` and the SSE stream hangs
waiting for a frame nobody will publish. The lease is what tells "the
owner is dead" apart from "the owner is busy", and the redriver is what
acts on the answer.

| moment | code | event | metric |
|---|---|---|---|
| lease expired, row reclaimed | `orphaned` | `job_redriver_reclaimed` | `research_jobs_total{status="failed", error_type="orphaned"}` |
| lease still held | *(none — nothing happens)* | no `job_redriver_reclaimed` | `research_jobs_total` **does not move** |
| runner loses its lease | *(none — the run continues)* | `job_lease_lost` | *(no instrument on this branch)* |

`tests/test_job_redriver.py` already pins the report counters and the
row. What it does not assert — and what a fleet is actually judged on
during a rolling restart — is that reclaiming a job is *counted*, that
it is counted **exactly once**, and that a healthy job's lease keeps it
out of the counter entirely. A redriver that reaped healthy work would
show up here as a `research_jobs_total{error_type="orphaned"}` point
that should not exist.

Two properties are asserted that only the metric can see:

- **The at-most-once rule.** `running` and the parked statuses are
  always failed, never requeued, because they already made LLM calls
  and restarting them would bill the operator twice for work that is
  no longer recoverable. A second sweep over the same reclaimed row
  must add nothing.
- **No duration.** `record_job_terminal` is called with
  `duration_sec=None` on this path on purpose: `completed_at -
  started_at` for a reclaimed job spans however long the row sat
  orphaned before a sweep noticed, which is a property of the sweep
  interval and not of the work. Feeding it to the histogram would drag
  every p95 toward the sweep cadence.
"""

from __future__ import annotations

import time
from typing import Any

import fakeredis.aioredis
import pytest

from src.api.jobs import Job, JobStatus
from src.api.redis_store import RedisJobStore
from src.api.redriver import ORPHANED_ERROR_TYPE, JobRedriver
from src.errors import JOB_ERROR_TYPES, JobOrphaned

from .conftest import TripleObserver

pytestmark = [pytest.mark.integration, pytest.mark.fault]

DEAD_WORKER = "worker-that-died"
SURVIVOR = "worker-that-swept"


@pytest.fixture
async def backend() -> Any:
    """One fakeredis client standing in for the Redis both workers share."""
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
async def store(backend: Any) -> RedisJobStore:
    """The surviving worker's view of the shared Redis."""
    return RedisJobStore(backend, retention_sec=3600)


async def _seed_abandoned(
    store: RedisJobStore, job_id: str, status: JobStatus
) -> Job:
    """Leave a row behind exactly as a killed worker would.

    Written through the store and then evicted from its local cache,
    because a restarted process only ever sees what is in Redis — and
    handing the sweep the same `Job` object the test holds would hide
    any serialization problem between them.
    """
    job = Job(
        job_id=job_id,
        query="a query whose worker did not survive it",
        status=status,
        started_at=time.time() - 60,
    )
    await store.update(job)
    store._local.pop(job_id, None)  # noqa: SLF001 - simulating a cold process
    return job


class TestTheOwnerIsGone:
    async def test_a_reclaimed_job_carries_a_code_a_warning_and_a_count(
        self, triple: TripleObserver, store: RedisJobStore
    ) -> None:
        """The crashed-worker signature: `running` with no live lease."""
        await _seed_abandoned(store, "orphan", JobStatus.running)

        report = await JobRedriver(store, SURVIVOR).sweep()

        assert (report.orphaned, report.failed, report.requeued) == (1, 1, 0)
        reclaimed = await store.get("orphan")
        assert reclaimed is not None
        assert reclaimed.status == JobStatus.failed
        assert reclaimed.error_type == JobOrphaned.code == ORPHANED_ERROR_TYPE
        assert reclaimed.error_type in JOB_ERROR_TYPES

        record = triple.assert_triple(
            code=reclaimed.error_type,
            event="job_redriver_reclaimed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": ORPHANED_ERROR_TYPE},
        )
        assert getattr(record, "previous_status", None) == "running"
        assert getattr(record, "worker_id", None) == SURVIVOR

        # The one instrument this path deliberately does not touch.
        # A reclaim's elapsed time measures the sweep interval, not the
        # work, and mixing it into the duration histogram would make
        # every latency percentile a function of the redrive cadence.
        triple.assert_not_recorded("research_job_duration_seconds")

    async def test_the_reclaim_is_counted_once_however_often_it_is_swept(
        self, triple: TripleObserver, store: RedisJobStore
    ) -> None:
        """The at-most-once rule, seen from the counter.

        The second sweep finds a terminal row and leaves it alone. If
        it did not, a fleet with a redrive interval of a minute would
        report one failure per minute per dead job forever, and the
        failure rate on a dashboard would be a measure of how long
        nobody looked.
        """
        await _seed_abandoned(store, "orphan-twice", JobStatus.running)
        redriver = JobRedriver(store, SURVIVOR)

        first = await redriver.sweep()
        second = await redriver.sweep()

        assert first.failed == 1
        assert (second.orphaned, second.failed) == (0, 0)
        assert len(triple.records("job_redriver_reclaimed")) == 1
        assert (
            triple.point(
                "research_jobs_total",
                status="failed",
                error_type=ORPHANED_ERROR_TYPE,
            ).value
            == 1
        )

    @pytest.mark.parametrize(
        "status",
        [JobStatus.running, JobStatus.pending_review, JobStatus.awaiting_learner],
        ids=["running", "pending_review", "awaiting_learner"],
    )
    async def test_a_job_that_already_spent_money_is_failed_never_requeued(
        self, triple: TripleObserver, store: RedisJobStore, status: JobStatus
    ) -> None:
        """Restarting these would bill the operator a second time.

        Each has already made LLM calls, and the intermediate state
        lived in the dead worker's process, so what a requeue would buy
        is a fresh run at full price — not a resumption. `requeue_pending`
        is switched on here precisely so the assertion is about the
        status rule rather than about the flag being off.
        """
        resubmitted: list[str] = []

        await _seed_abandoned(store, f"orphan-{status.value}", status)
        report = await JobRedriver(
            store,
            SURVIVOR,
            requeue_pending=True,
            resubmit=lambda job: resubmitted.append(job.job_id),
        ).sweep()

        assert report.requeued == 0
        assert report.failed == 1
        assert resubmitted == []
        triple.assert_triple(
            code=ORPHANED_ERROR_TYPE,
            event="job_redriver_reclaimed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": ORPHANED_ERROR_TYPE},
        )


class TestTheOwnerIsAliveAfterAll:
    async def test_a_live_lease_keeps_a_healthy_job_out_of_the_failure_counter(
        self, triple: TripleObserver, store: RedisJobStore, backend: Any
    ) -> None:
        """The whole reason leases exist, asserted on the metric.

        Worker A is mid-job and holding its lease; worker B boots and
        sweeps. Without the lease check every healthy job in the fleet
        would be failed on every deploy — and the visible symptom would
        be exactly a spike of `error_type="orphaned"` on each rollout,
        which is what this assertion refuses to allow.
        """
        peer = RedisJobStore(backend, retention_sec=3600)
        await _seed_abandoned(store, "still-alive", JobStatus.running)
        assert await peer.acquire_lease("still-alive", DEAD_WORKER, 60)

        report = await JobRedriver(store, SURVIVOR).sweep()

        assert (report.skipped_live, report.orphaned, report.failed) == (1, 0, 0)
        untouched = await store.get("still-alive")
        assert untouched is not None
        assert untouched.status == JobStatus.running
        assert untouched.error_type is None

        assert triple.records("job_redriver_reclaimed") == []
        triple.assert_not_recorded("research_jobs_total")

    async def test_a_lease_that_expires_becomes_reclaimable(
        self, triple: TripleObserver, store: RedisJobStore, backend: Any
    ) -> None:
        """Expiry is the mechanism, not a fixed timeout on the row.

        The lease is a Redis key with a TTL, so "the worker died" is
        expressed as "nobody renewed the key". Deleting it here is what
        the TTL does a few seconds later, and it is the transition that
        turns the previous test's outcome into this one's.
        """
        peer = RedisJobStore(backend, retention_sec=3600)
        await _seed_abandoned(store, "expiring", JobStatus.running)
        assert await peer.acquire_lease("expiring", DEAD_WORKER, 60)

        assert (await JobRedriver(store, SURVIVOR).sweep()).skipped_live == 1

        # The owner stops renewing; the key goes.
        await peer.release_lease("expiring", DEAD_WORKER)
        report = await JobRedriver(store, SURVIVOR).sweep()

        assert report.failed == 1
        reclaimed = await store.get("expiring")
        assert reclaimed is not None and reclaimed.error_type == ORPHANED_ERROR_TYPE
        triple.assert_triple(
            code=reclaimed.error_type,
            event="job_redriver_reclaimed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": ORPHANED_ERROR_TYPE},
        )
