"""Redis-backed implementation of the `JobStore` Protocol.

Durability + horizontal-scale variant of `InMemoryJobStore` (ADR
0025). Selected by `settings.job_store = "redis"` and pointed at
`settings.redis_url`. Design in ADR 0027.

Storage layout: each job is one key `job:{job_id}` holding the
JSON-serialized persistent fields of the `Job` dataclass. Terminal
jobs get a TTL of `settings.api_job_retention_sec` so Redis handles
retention without an explicit sweeper.

Local instance cache: workers keep every `Job` they create in an
in-process dict so the `event_queue` (which is not serializable and
lives only in the worker that runs the job) is reachable for
streaming. Requests hitting a different worker still get the
persistent snapshot via Redis, but streaming events requires the
originating worker — a normal deployment pattern for SSE (sticky
sessions / job-affinity routing).

## Cross-worker HITL resume (ADR 0034)

`resume_event` also lives only on the runner's worker — an
`asyncio.Event` bound to the runner's loop. The audit flagged this
as a real bug: a `POST /research/{id}/review` submitted to worker B
would set a fresh Event on B's reconstructed Job, and A's runner
would never wake.

`publish_remote_resume` (called from the review endpoint) publishes
the decision to `hitl:resume:{job_id}` on Redis pub/sub;
`watch_for_remote_resume` (called from A's runner during the HITL
pause) subscribes and hydrates the local job when the message
arrives. Same-worker resume still works via the direct
`resume_event.set()` in the endpoint; the pub/sub covers the
different-worker case.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import asdict, fields
from typing import Any

import redis.asyncio as redis_async

from src.api.jobs import Job, JobStatus
from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

JOB_KEY_PREFIX = "job:"
HITL_RESUME_CHANNEL_PREFIX = "hitl:resume:"


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _hitl_resume_channel(job_id: str) -> str:
    """Pub/sub channel for HITL resume notifications (ADR 0034)."""
    return f"{HITL_RESUME_CHANNEL_PREFIX}{job_id}"


def _persistent_fields() -> set[str]:
    """Fields on `Job` that go over the wire to Redis.

    Excluded:
      - `event_queue`: `asyncio.Queue` bound to the runner worker.
      - `resume_event`: `asyncio.Event`, same rationale — HITL resume
        is a worker-local signal. Cross-worker resume uses the
        `hitl:resume:{job_id}` pub/sub channel; see ADR 0034 and
        `publish_remote_resume` / `watch_for_remote_resume` below.
    """
    return {f.name for f in fields(Job)} - {"event_queue", "resume_event"}


def _job_to_json(job: Job) -> str:
    """Serialize the persistent portion of a `Job` to a JSON string."""
    data = asdict(job)
    keep = _persistent_fields()
    persistent = {k: v for k, v in data.items() if k in keep}
    # The status field is a StrEnum; asdict emits its str value already,
    # but be defensive if a subclass overrides.
    persistent["status"] = str(job.status)
    return json.dumps(persistent, separators=(",", ":"))


def _job_from_json(payload: str) -> Job:
    """Reconstruct a `Job` from Redis JSON.

    The reconstructed job gets a fresh empty `event_queue` — that's
    correct: only the worker that created the job holds its live
    queue.
    """
    data = json.loads(payload)
    status = JobStatus(data.get("status", "pending"))
    return Job(
        job_id=data["job_id"],
        query=data["query"],
        status=status,
        created_at=float(data["created_at"]),
        started_at=data.get("started_at"),
        completed_at=data.get("completed_at"),
        result=data.get("result"),
        error=data.get("error"),
        error_type=data.get("error_type"),
        cost_usd=data.get("cost_usd"),
        llm_calls=data.get("llm_calls"),
        iterations=data.get("iterations"),
        quality_score=data.get("quality_score"),
        hitl_bypass=bool(data.get("hitl_bypass", False)),
        conversation_id=data.get("conversation_id"),
        plan=data.get("plan"),
        resume_action=data.get("resume_action"),
        resume_plan=data.get("resume_plan"),
    )


class RedisJobStore:
    """Persistent + shared JobStore backed by Redis.

    Not a subclass of a base store — implements the same duck-typed
    surface as `InMemoryJobStore`, satisfying the `JobStore`
    Protocol declared in `src.api.jobs`.
    """

    def __init__(
        self,
        client: redis_async.Redis,
        *,
        key_prefix: str = JOB_KEY_PREFIX,
        retention_sec: int | None = None,
    ) -> None:
        self._client = client
        self._key_prefix = key_prefix
        self._retention_sec = (
            retention_sec if retention_sec is not None else settings.api_job_retention_sec
        )
        # Local cache of jobs this worker is currently handling. Keeps
        # the live `event_queue` reachable across GET-then-stream
        # request pairs on the same worker.
        self._local: dict[str, Job] = {}

    def _key(self, job_id: str) -> str:
        return f"{self._key_prefix}{job_id}"

    async def create(self, job: Job) -> None:
        # Local cache first so streaming picks up the live queue,
        # even if the Redis write races behind.
        self._local[job.job_id] = job
        await self._client.set(self._key(job.job_id), _job_to_json(job))

    async def get(self, job_id: str) -> Job | None:
        # Prefer the local instance — it's the only place with the
        # live event_queue. Fall through to Redis for jobs running
        # on another worker or persisted from a previous restart.
        local = self._local.get(job_id)
        if local is not None:
            return local
        payload = await self._client.get(self._key(job_id))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode()
        return _job_from_json(payload)

    async def update(self, job: Job) -> None:
        # Preserve the local cache invariant: if we own this job's
        # runner, keep our instance authoritative for streaming.
        if job.job_id in self._local:
            self._local[job.job_id] = job

        serialized = _job_to_json(job)
        if job.is_terminal() and self._retention_sec > 0:
            await self._client.set(
                self._key(job.job_id), serialized, ex=self._retention_sec
            )
        else:
            await self._client.set(self._key(job.job_id), serialized)

    async def evict_older_than(self, retention_sec: int) -> int:
        """Redis handles retention via key TTL, so this is a no-op.

        The Protocol requires the method for cross-implementation
        compatibility with `InMemoryJobStore`, but under Redis the
        TTL set in `update()` when a job goes terminal drives
        eviction. `retention_sec` here is documentation-only:
        adjusting the runtime retention window happens through
        `settings.api_job_retention_sec` before jobs become terminal.
        """
        return 0

    async def close(self) -> None:
        """Release the Redis connection pool. Called from the
        FastAPI lifespan on shutdown."""
        await self._client.aclose()

    # ---- ADR 0034: cross-worker HITL resume ---------------------

    async def publish_remote_resume(
        self,
        job_id: str,
        action: str,
        plan: dict[str, Any] | None,
    ) -> None:
        """Fan out a resume decision to any worker running the job.

        Called from `POST /research/{id}/review`. The runner's
        worker may be a different process — even in single-worker
        deployments this is safe and cheap (Redis local-loop
        publish, no consumer means no work).
        """
        payload = json.dumps(
            {"action": action, "plan": plan}, separators=(",", ":")
        )
        await self._client.publish(_hitl_resume_channel(job_id), payload)

    async def watch_for_remote_resume(self, job: Job) -> None:
        """Subscribe to `hitl:resume:{job_id}`; hydrate + wake on message.

        Runs as a background task spawned by the runner during
        `_handle_hitl_pause`. On the first message received:

        1. Populates `job.resume_action` and `job.resume_plan` from
           the payload (the review endpoint already wrote them to
           Redis, but the runner might be holding a stale local
           copy).
        2. Sets `job.resume_event`, which is what the runner's
           `wait_for` is awaiting.

        The task is cancelled from `_handle_hitl_pause`'s `finally`
        clause once the resume completes (same-worker path fires
        the event directly, and the pub/sub subscription is torn
        down without ever seeing a message). Cancellation cleans up
        the pubsub connection.
        """
        pubsub = self._client.pubsub()
        try:
            await pubsub.subscribe(_hitl_resume_channel(job.job_id))
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                try:
                    parsed = json.loads(data) if data else {}
                except (ValueError, TypeError):
                    log.warning(
                        "hitl_resume_bad_payload",
                        extra={"job_id": job.job_id, "payload": data},
                    )
                    continue
                job.resume_action = parsed.get("action")
                job.resume_plan = parsed.get("plan")
                job.resume_event.set()
                log.info(
                    "hitl_resume_received_via_pubsub",
                    extra={
                        "job_id": job.job_id,
                        "action": job.resume_action,
                    },
                )
                return
        except asyncio.CancelledError:
            # Normal path when the same-worker resume beats the
            # pub/sub message. Cleanup runs in `finally`.
            raise
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(_hitl_resume_channel(job.job_id))
            with contextlib.suppress(Exception):
                await pubsub.aclose()  # type: ignore[no-untyped-call]


def build_redis_client(url: str) -> redis_async.Redis:
    """Construct the async Redis client from a URL.

    Kept out of the store class so tests can inject a `fakeredis`
    client without touching URL parsing.
    """
    return redis_async.from_url(url, decode_responses=False)
