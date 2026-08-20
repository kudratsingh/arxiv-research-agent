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

## Cross-worker SSE (ADR 0035)

Same pattern applied to node events. `publish_event` (called from
the runner for every `job_started` / `node_completed` / `plan_ready`
/ terminal event) publishes to `events:{job_id}`; `subscribe_events`
(consumed by `stream_research` when the store supports it) reads
that channel and yields frames until a terminal event. The local
`event_queue` on `Job` is bypassed entirely for RedisJobStore — a
`_put_event` under multi-worker would fill an unread queue on the
runner's worker until the blocking terminal `put()` deadlocks.

## Worker leases + redrive scan (ADR 0038)

Non-terminal jobs are written without a TTL on purpose — a stuck job
is a diagnostic signal, not garbage. The failure mode it created
was: a worker dies mid-job (deploy, OOM, scale-in) and its row stays
`running` forever, so `GET /research/{id}` lies and the SSE stream
hangs waiting for a terminal frame nobody will publish.

`joblease:{job_id}` is what makes "orphaned" decidable. The runner
holds it for as long as it owns the job and re-expires it every
`job_lease_refresh_sec`; the key's TTL outliving the worker is the
signal that the worker is gone. `scan_jobs` + `try_acquire_redrive_lock`
are the primitives the startup redriver (`src.api.redriver`) uses to
reconcile whatever the previous generation of workers left behind.

These are duck-typed extras rather than `JobStore` Protocol members,
for the same reason `subscribe_events` and `publish_remote_resume`
are: `InMemoryJobStore` has nothing to reconcile, since nothing
survives its process.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, fields
from typing import Any

import redis.asyncio as redis_async

from src.api.jobs import Job, JobStatus
from src.api.streaming import TERMINAL_EVENT_NAMES
from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

JOB_KEY_PREFIX = "job:"
HITL_RESUME_CHANNEL_PREFIX = "hitl:resume:"
EVENTS_CHANNEL_PREFIX = "events:"
# ADR 0038. Deliberately not a sub-prefix of `job:` — `SCAN MATCH
# job:*` in `scan_jobs` must not trip over lease keys.
LEASE_KEY_PREFIX = "joblease:"
REDRIVE_LOCK_KEY = "redrive:lock"

# How many keys Redis returns per SCAN round trip. SCAN's COUNT is a
# hint, not a guarantee; 200 keeps each round trip short enough that
# the server's event loop stays responsive during a sweep.
_SCAN_BATCH = 200

# Runner terminal event names — the pub/sub reader stops iterating on
# any of these. Imported from `src.api.streaming` rather than copied:
# a private duplicate that drifted from the streaming module's copy
# would leave a subscriber hanging until the client disconnects, and
# there is no reason for the two to answer this question differently.
# Note this is the *narrow* set — `stream_timeout` closes a
# connection without ending the job, so it deliberately does not
# appear here (see `STREAM_CLOSING_EVENT_NAMES`).


def _job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def _hitl_resume_channel(job_id: str) -> str:
    """Pub/sub channel for HITL resume notifications (ADR 0034)."""
    return f"{HITL_RESUME_CHANNEL_PREFIX}{job_id}"


def _events_channel(job_id: str) -> str:
    """Pub/sub channel for SSE events (ADR 0035)."""
    return f"{EVENTS_CHANNEL_PREFIX}{job_id}"


def _lease_key(job_id: str) -> str:
    """Key holding the id of the worker that currently owns the job.

    Presence of this key is the liveness proof the redriver checks
    before reclaiming a non-terminal job (ADR 0038).
    """
    return f"{LEASE_KEY_PREFIX}{job_id}"


def _as_text(value: Any) -> str | None:
    """Normalize a Redis reply to `str`.

    `build_redis_client` uses `decode_responses=False`, so replies
    arrive as `bytes`; tests may inject a client configured either
    way. Returns None for a missing key.
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


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
        # ADR 0036: legacy Redis rows without this field are None.
        # `principal_key_id` is a persistent field so it round-
        # trips through `_job_to_json` on write.
        principal_key_id=data.get("principal_key_id"),
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
        # ADR 0038: lease and redrive-lock keys carry the same
        # namespace as job rows. Two deployments sharing one Redis
        # under distinct `key_prefix` values must not collide on job
        # leases — and, the worse half, must not contend for a single
        # global redrive lock, where one deployment's sweep would
        # silence the other's entirely. The default prefix reproduces
        # the module-level constants exactly, so the common case keeps
        # the historic key names.
        _stem = key_prefix.rstrip(":")
        self._lease_prefix = (
            LEASE_KEY_PREFIX if key_prefix == JOB_KEY_PREFIX else f"{_stem}lease:"
        )
        self._redrive_lock_key = (
            REDRIVE_LOCK_KEY
            if key_prefix == JOB_KEY_PREFIX
            else f"{_stem}redrive:lock"
        )
        self._retention_sec = (
            retention_sec if retention_sec is not None else settings.api_job_retention_sec
        )
        # Local cache of jobs this worker is currently handling. Keeps
        # the live `event_queue` reachable across GET-then-stream
        # request pairs on the same worker.
        self._local: dict[str, Job] = {}

    def _key(self, job_id: str) -> str:
        return f"{self._key_prefix}{job_id}"

    def _lease_key(self, job_id: str) -> str:
        """Lease key for this store's namespace.

        The module-level `_lease_key` is the default-prefix form;
        this honours a custom `key_prefix` so co-tenant deployments
        cannot claim each other's leases.
        """
        return f"{self._lease_prefix}{job_id}"

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

    # ---- ADR 0035: cross-worker SSE events ---------------------

    async def publish_event(
        self, job_id: str, event: str, data: dict[str, Any]
    ) -> None:
        """Fan out one SSE event to any streamer subscribed to the job.

        Called from the runner's `_put_event` / `_put_terminal_event`
        for every frame the SSE endpoint would otherwise pull off
        `job.event_queue`. Under multi-worker uvicorn this is the
        only delivery mechanism that actually reaches the streaming
        endpoint if that endpoint is running on a different worker
        than the runner.
        """
        payload = json.dumps(
            {"event": event, "data": data}, separators=(",", ":")
        )
        await self._client.publish(_events_channel(job_id), payload)

    async def subscribe_events(
        self, job_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield SSE frames from `events:{job_id}` until a terminal event.

        Consumed by `stream_research` under RedisJobStore. Terminates
        cleanly on any of `job_completed` / `job_failed` /
        `job_cancelled`, matching the `drain_events` semantics for
        `InMemoryJobStore`. Handles pub/sub connection cleanup in
        `finally` so a cancelled subscription (client disconnect)
        doesn't leak a Redis connection.

        Malformed payloads are logged and skipped — a rogue
        publisher on the same channel can't crash the stream.
        """
        pubsub = self._client.pubsub()
        try:
            await pubsub.subscribe(_events_channel(job_id))
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if isinstance(raw, bytes):
                    raw = raw.decode()
                try:
                    parsed = json.loads(raw) if raw else None
                except (ValueError, TypeError):
                    log.warning(
                        "sse_event_bad_payload",
                        extra={"job_id": job_id, "payload": raw},
                    )
                    continue
                if not isinstance(parsed, dict) or "event" not in parsed:
                    log.warning(
                        "sse_event_bad_shape",
                        extra={"job_id": job_id, "payload": raw},
                    )
                    continue
                yield parsed
                if parsed.get("event") in TERMINAL_EVENT_NAMES:
                    return
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(_events_channel(job_id))
            with contextlib.suppress(Exception):
                await pubsub.aclose()  # type: ignore[no-untyped-call]

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

    # ---- ADR 0038: worker leases + redrive scan -----------------

    async def _compare_and_apply(
        self, key: str, token: str, *, ttl_sec: int | None
    ) -> bool:
        """Re-expire or delete `key`, but only while `token` still owns it.

        The check and the write have to be one atomic step: between a
        plain GET and a plain EXPIRE the lease can expire and be taken
        by another worker, and we would then extend *their* lease.
        WATCH/MULTI/EXEC gives that atomicity — Redis aborts the EXEC
        if anything touched the key after the WATCH, which is exactly
        the "someone else took it" case.

        (`EVAL` with a three-line Lua script is the more common idiom
        for this, but it is unavailable on part of our test matrix —
        `fakeredis` only implements EVAL when the optional `lupa`
        native extension is installed. Optimistic locking is
        supported everywhere and carries the same guarantee.)

        Args:
            key: Lease or lock key to operate on.
            token: Owner id the stored value must still equal.
            ttl_sec: New TTL in seconds, or None to delete the key.

        Returns:
            True if we still owned the key and the write landed;
            False if the lease was lost (expired, deleted, or taken
            by another owner).
        """
        try:
            async with self._client.pipeline() as pipe:
                await pipe.watch(key)
                if _as_text(await pipe.get(key)) != token:
                    await pipe.unwatch()  # type: ignore[no-untyped-call]
                    return False
                pipe.multi()  # type: ignore[no-untyped-call]
                if ttl_sec is None:
                    pipe.delete(key)
                else:
                    pipe.expire(key, ttl_sec)
                results = await pipe.execute()
        except redis_async.WatchError:
            # The key changed under us between WATCH and EXEC — by
            # definition we no longer own the lease.
            return False
        return bool(results) and bool(results[0])

    async def acquire_lease(
        self, job_id: str, worker_id: str, ttl_sec: int
    ) -> bool:
        """Claim `joblease:{job_id}` for `worker_id` if it is unheld.

        Args:
            job_id: Job whose lease is being claimed.
            worker_id: Process-unique id of the claiming worker.
            ttl_sec: Lease lifetime; the runner must refresh inside it.

        Returns:
            True if this worker now holds the lease, False if another
            worker already does.
        """
        acquired = await self._client.set(
            self._lease_key(job_id), worker_id, nx=True, ex=ttl_sec
        )
        return bool(acquired)

    async def refresh_lease(
        self, job_id: str, worker_id: str, ttl_sec: int
    ) -> bool:
        """Extend a lease this worker still owns.

        Args:
            job_id: Job whose lease is being extended.
            worker_id: Owner id that must still match the stored value.
            ttl_sec: New lease lifetime.

        Returns:
            False when the lease was lost — it expired and someone
            else claimed it, or a redriver already reclaimed the job.
            The runner treats that as a diagnostic, not a kill signal.
        """
        return await self._compare_and_apply(
            self._lease_key(job_id), worker_id, ttl_sec=ttl_sec
        )

    async def release_lease(self, job_id: str, worker_id: str) -> None:
        """Drop a lease this worker owns, so the job is reclaimable now.

        Owner-checked: a worker that already lost its lease must not
        delete the successor's claim.

        Args:
            job_id: Job whose lease is being released.
            worker_id: Owner id that must still match the stored value.
        """
        await self._compare_and_apply(
            self._lease_key(job_id), worker_id, ttl_sec=None
        )

    async def has_lease(self, job_id: str) -> bool:
        """Whether any worker currently holds the job's lease.

        Args:
            job_id: Job to check.

        Returns:
            True while a live worker owns the job. The redriver uses
            this to leave healthy jobs on other workers alone during
            a rolling restart.
        """
        return bool(await self._client.exists(self._lease_key(job_id)))

    async def scan_jobs(self, *, max_scan: int) -> tuple[list[Job], bool]:
        """Read up to `max_scan` persisted jobs via cursor-based SCAN.

        Deliberately SCAN and not KEYS: `KEYS job:*` blocks the Redis
        event loop for the whole keyspace, which on a production
        instance means a stall for every other client. SCAN trades
        exactness (it can return duplicates, and misses keys created
        mid-sweep) for bounded per-call work; the redriver only needs
        a good-enough snapshot of what the previous generation of
        workers left behind, and duplicates are deduplicated here.

        A key whose payload will not deserialize is logged as
        `job_scan_bad_payload` and skipped rather than aborting the
        sweep — one corrupt row must not block reconciling the rest.

        Args:
            max_scan: Upper bound on keys examined, so a huge keyspace
                cannot stall startup.

        Returns:
            `(jobs, scan_capped)` — the deserialized jobs, and whether
            the cap stopped the sweep early. A True flag means the
            result is a partial view and must not be reported as a
            complete reconciliation.
        """
        pattern = f"{self._key_prefix}*"
        seen: set[str] = set()
        jobs: list[Job] = []
        cursor = 0
        examined = 0
        capped = False

        while True:
            cursor, batch = await self._client.scan(
                cursor=cursor, match=pattern, count=_SCAN_BATCH
            )
            keys = [k for k in (_as_text(raw) for raw in batch) if k is not None]
            fresh = [k for k in keys if k not in seen]
            seen.update(fresh)

            if examined + len(fresh) > max_scan:
                fresh = fresh[: max_scan - examined]
                capped = True
            examined += len(fresh)

            if fresh:
                payloads = await self._client.mget(fresh)
                for key, raw in zip(fresh, payloads, strict=True):
                    payload = _as_text(raw)
                    if payload is None:
                        # Key expired between the SCAN and the MGET.
                        continue
                    try:
                        jobs.append(_job_from_json(payload))
                    except (ValueError, TypeError, KeyError):
                        log.warning("job_scan_bad_payload", extra={"key": key})

            if capped or cursor == 0:
                break

        return jobs, capped

    async def try_acquire_redrive_lock(
        self, ttl_sec: int, *, token: str
    ) -> bool:
        """Claim the cluster-wide right to run one redrive sweep.

        Every worker boots at once after a deploy. Without this lock
        each of them would scan the same keyspace and race to reclaim
        the same orphaned jobs, publishing duplicate terminal frames.

        The TTL is what stops a worker that dies mid-sweep from
        wedging the lock permanently.

        Args:
            ttl_sec: How long the claim survives without a release.
            token: Owner id stored in the key, so the release is
                owner-checked.

        Returns:
            True if this worker won and should sweep, False if another
            worker is already sweeping.
        """
        acquired = await self._client.set(
            self._redrive_lock_key, token, nx=True, ex=ttl_sec
        )
        return bool(acquired)

    async def release_redrive_lock(self, token: str) -> None:
        """Release the redrive lock if `token` still owns it.

        Args:
            token: Owner id that must still match the stored value.
                A sweep that overran its TTL will not stomp on the
                worker that legitimately took the lock next.
        """
        await self._compare_and_apply(
            self._redrive_lock_key, token, ttl_sec=None
        )


def build_redis_client(url: str) -> redis_async.Redis:
    """Construct the async Redis client from a URL.

    Kept out of the store class so tests can inject a `fakeredis`
    client without touching URL parsing.
    """
    return redis_async.from_url(url, decode_responses=False)
