"""Redis-backed implementation of the `JobStore` Protocol.

Durability + horizontal-scale variant of `InMemoryJobStore` (ADR
0025). Selected by `settings.job_store = "redis"` and pointed at
`settings.redis_url`. Design in ADR 0027.

Storage layout: each job is one key `job:{job_id}` holding the
JSON-serialized persistent fields of the `Job` dataclass. Terminal
jobs get a TTL of `settings.api_job_retention_sec` so Redis handles
retention without an explicit sweeper.

Local instance cache: workers keep the `Job` instances they are
currently handling in an in-process dict so the `event_queue` and
`resume_event` (not serializable, live only in the worker that runs
the job) stay reachable while the job runs. The entry is dropped the
moment the job goes terminal — past that point delivery is pub/sub
(ADR 0035), and a retained entry would both grow the dict without
bound and shadow the Redis retention TTL on the originating worker
(ADR 0040). The drop happens in a `finally`, so a Redis outage that
fails every terminal write still bounds worker memory (ADR 0048).
Requests hitting a different worker still get the persistent
snapshot via Redis.

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
from dataclasses import fields
from typing import Any

import redis.asyncio as redis_async

from src.api.jobs import TERMINAL_STATUSES, Job, JobStatus
from src.api.streaming import TERMINAL_EVENT_NAMES, TERMINAL_EVENT_STATUS
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
    """Serialize the persistent portion of a `Job` to a JSON string.

    Built with per-field `getattr`, deliberately NOT
    `dataclasses.asdict`: `asdict` deep-copies every field *before*
    the persistent filter drops the non-serializable ones, and while
    the runner is parked in `await resume_event.wait()` the Event's
    waiter deque holds a live `Future` that `copy.deepcopy` cannot
    reproduce. Under `asdict`, any `store.update` issued against the
    paused job — which is exactly what the HITL review endpoint does —
    raised `TypeError` and 500'd the review (audit P0).
    """
    keep = _persistent_fields()
    persistent = {
        f.name: getattr(job, f.name) for f in fields(Job) if f.name in keep
    }
    # `json.dumps` serializes the StrEnum's value; make the intent
    # explicit rather than relying on that.
    persistent["status"] = str(job.status)
    return json.dumps(persistent, separators=(",", ":"))


def _status_from_payload(payload: str | None) -> JobStatus | None:
    """Read just the `status` out of a stored row, cheaply.

    Used by every guard that has to answer "what does Redis currently
    say about this job?" without paying for a full `Job`
    reconstruction. Returns None for a missing key *and* for a row
    that will not parse — the callers treat "unknown" as "no opinion",
    which for the refusal guards means letting the write through
    rather than wedging a job behind a corrupt payload.

    Args:
        payload: The raw JSON row, or None when the key is gone.

    Returns:
        The stored status, or None when it cannot be determined.
    """
    if payload is None:
        return None
    try:
        data = json.loads(payload)
        return JobStatus(data.get("status", "pending"))
    except (ValueError, TypeError, AttributeError):
        return None


def _job_from_json(payload: str) -> Job:
    """Reconstruct a `Job` from Redis JSON.

    Symmetric with `_job_to_json`: the accepted keys derive from
    `_persistent_fields()` rather than a hand-enumerated kwarg list,
    so a field added to the `Job` dataclass round-trips without this
    function changing — and a payload written by a newer worker
    degrades to dropping only the keys this build does not know,
    instead of silently truncating fields it merely forgot to name.
    Unknown keys are ignored for the same forward-compatibility
    reason. Explicit coercion is kept only where JSON's type is wider
    than the field's (`status`, `created_at`).

    The reconstructed job gets a fresh empty `event_queue` — that's
    correct: only the worker that created the job holds its live
    queue.
    """
    data = json.loads(payload)
    keep = _persistent_fields()
    kwargs: dict[str, Any] = {k: v for k, v in data.items() if k in keep}
    kwargs["status"] = JobStatus(data.get("status", "pending"))
    kwargs["created_at"] = float(data["created_at"])
    return Job(**kwargs)


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
        # Prefer the local instance for LIVE jobs — it's the only
        # place with the live event_queue / resume_event. Terminal
        # jobs fall through to Redis so the retention TTL and operator
        # deletes stay authoritative on every worker, including the
        # one that ran the job (audit P2: `_local` used to shadow both
        # forever).
        local = self._local.get(job_id)
        if local is not None and not local.is_terminal():
            return local
        payload = await self._client.get(self._key(job_id))
        if payload is None:
            # Redis says the row is gone (TTL fired / operator DEL).
            # Drop any stale local instance so this worker agrees.
            self._local.pop(job_id, None)
            return None
        if isinstance(payload, bytes):
            payload = payload.decode()
        return _job_from_json(payload)

    async def _stored_status(self, job_id: str) -> JobStatus | None:
        """What Redis currently says this job's status is.

        One GET and a partial parse — no `Job` reconstruction, so the
        guards that call it per terminal write do not pay for
        hydrating a full report body.
        """
        raw = await self._client.get(self._key(job_id))
        return _status_from_payload(_as_text(raw))

    async def _terminal_write_refused(self, job: Job) -> bool:
        """Whether a terminal write must be dropped as a late loser.

        The race this closes (ADR 0038 follow-up): a redriver mistakes
        a live job for an orphan and writes `failed/orphaned`; the
        still-running worker later finishes and would silently
        resurrect the row as `succeeded` — after every SSE client
        already saw a terminal `job_failed`. First terminal write
        wins; the loser is logged, not raised (the runner's terminal
        persist path must stay absorbing, and a raise there would be
        retried three times and reported as data loss).

        Args:
            job: The terminal job about to be persisted.

        Returns:
            True when a *different* terminal status is already stored.
            An unreadable or absent row returns False so a corrupt
            payload cannot wedge a job out of ever being finalized.
        """
        stored = await self._stored_status(job.job_id)
        if (
            stored is not None
            and stored in TERMINAL_STATUSES
            and stored != job.status
        ):
            log.warning(
                "job_terminal_transition_refused",
                extra={
                    "job_id": job.job_id,
                    "stored_status": stored.value,
                    "attempted_status": job.status.value,
                },
            )
            return True
        return False

    async def update(self, job: Job) -> None:
        """Persist a job, evicting terminal ones from the local cache.

        The `finally` is load-bearing (ADR 0048). A terminal job's
        `_local` entry has to be dropped on *every* exit — the write
        landing, the refusal guard rejecting it, and either Redis call
        raising. Without it, a sustained outage in which every
        terminal persist attempt failed left one entry per finished
        job in the dict for the process lifetime, so worker memory
        grew monotonically for exactly as long as the outage lasted.

        Evicting on failure does cost this worker something: its `get`
        then falls back to the (stale, still non-terminal) Redis row
        and reports `running` for a job it knows finished. That is the
        *same* answer every other worker in the fleet is already
        giving, and the terminal outcome is recoverable from the
        `api_job_terminal_persist_failed` record the runner logs in
        full. Serving a stale local row past that point buys one
        worker a better answer at the price of an OOM that takes the
        live jobs with it.

        Store failures propagate: the runner's `_persist_terminal`
        owns the retry-and-absorb policy, and swallowing here would
        hide a downed Redis from it.
        """
        try:
            # Refuse a terminal -> different-terminal overwrite: first
            # terminal write wins (see `_terminal_write_refused`).
            if job.is_terminal() and await self._terminal_write_refused(job):
                return

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
        finally:
            # Under this store SSE delivery is pub/sub (ADR 0035), so
            # a terminal job's live queue has no consumer left, and
            # keeping the entry would pin every finished report +
            # Queue + Event for the process lifetime while shadowing
            # the retention TTL (audit P2).
            if job.is_terminal():
                self._local.pop(job.job_id, None)

    async def update_if_status(self, job: Job, *, expected: JobStatus) -> bool:
        """Write `job` only while Redis still shows `expected` (ADR 0048).

        The redriver's reclaim needs more than `update`'s guard. That
        guard is GET-then-SET, and it only refuses *terminal →
        different-terminal*: a job that completes between the sweep's
        re-read and its write goes `running → succeeded` in the gap,
        and the sweep's `failed/orphaned` overwrites a finished report
        because at the moment of the guard's GET the stored status was
        still `succeeded`… only after the sweep had already decided to
        write. Collapsing the check and the write into one
        WATCH/MULTI/EXEC removes the gap: Redis aborts the EXEC if
        anything touched the key after the WATCH, which is precisely
        "the owner finished while we were deciding".

        Uses optimistic locking rather than `EVAL` for the same reason
        `_compare_and_apply` does — `fakeredis` only implements `EVAL`
        with the optional native `lupa` extension.

        A duck-typed extra, not a `JobStore` Protocol member:
        `InMemoryJobStore` has no cross-process race to arbitrate, and
        the redriver already probes the store for `scan_jobs` and
        `acquire_lease` the same way.

        Args:
            job: The mutated job to persist.
            expected: The status the caller observed and is acting on.

        Returns:
            True if the row still read `expected` and the write
            landed. False if it did not — the caller must treat its
            decision as stale and publish nothing.
        """
        key = self._key(job.job_id)
        serialized = _job_to_json(job)
        ttl_sec = (
            self._retention_sec
            if job.is_terminal() and self._retention_sec > 0
            else None
        )
        try:
            async with self._client.pipeline() as pipe:
                await pipe.watch(key)
                stored = _status_from_payload(_as_text(await pipe.get(key)))
                if stored != expected:
                    await pipe.unwatch()  # type: ignore[no-untyped-call]
                    log.info(
                        "job_cas_write_stale",
                        extra={
                            "job_id": job.job_id,
                            "stored_status": stored.value if stored else None,
                            "expected_status": expected.value,
                        },
                    )
                    return False
                pipe.multi()  # type: ignore[no-untyped-call]
                if ttl_sec is None:
                    pipe.set(key, serialized)
                else:
                    pipe.set(key, serialized, ex=ttl_sec)
                results = await pipe.execute()
        except redis_async.WatchError:
            # Someone wrote the row between our WATCH and the EXEC —
            # by definition the status we compared against is stale.
            log.info(
                "job_cas_write_aborted",
                extra={
                    "job_id": job.job_id,
                    "expected_status": expected.value,
                },
            )
            return False

        if not (bool(results) and bool(results[0])):
            return False

        if job.job_id in self._local:
            self._local[job.job_id] = job
        if job.is_terminal():
            self._local.pop(job.job_id, None)
        return True

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

        **Terminal frames are checked against the persisted row**
        (ADR 0048). `update` refuses a terminal → different-terminal
        overwrite, but the caller that lost that race did not know it
        and went on to publish its own terminal frame anyway — so a
        client could see `job_completed` land after `job_failed`, for
        a job whose stored outcome is `failed` and whose `result` it
        will never be able to fetch. Making the refusal observable to
        the *publisher* would mean changing `update`'s `-> None`
        Protocol signature (and `InMemoryJobStore` with it); enforcing
        it here instead needs no Protocol change, and covers every
        publisher — the runner, the redriver, and anything added
        later — at the one point where the frame becomes visible.
        The check costs one GET per terminal frame, which is at most
        one per job.

        A frame is dropped only when the stored status is *itself*
        terminal and disagrees. A missing row (retention TTL fired) or
        a non-terminal row (the terminal persist failed outright)
        still publishes: a subscriber blocked on a close signal is
        worse off without it.
        """
        if event in TERMINAL_EVENT_NAMES:
            stored = await self._stored_status(job_id)
            if (
                stored is not None
                and stored in TERMINAL_STATUSES
                and stored.value != TERMINAL_EVENT_STATUS[event]
            ):
                log.warning(
                    "sse_terminal_frame_suppressed",
                    extra={
                        "job_id": job_id,
                        "event": event,
                        "stored_status": stored.value,
                    },
                )
                return

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

    async def _terminal_keys(self, keys: list[str]) -> set[str]:
        """Subset of `keys` provably holding a terminal job, via TTL.

        The only place a job row is given an expiry is the terminal
        branch of `update` / `update_if_status`, so `TTL >= 0` is a
        proof of terminality that costs an integer reply instead of a
        full report body — which is the whole point (ADR 0048): the
        sweep used to MGET every row in the keyspace and throw the
        terminal ones away immediately after paying to transfer and
        deserialize them, and in a healthy deployment nearly every row
        inside the retention window is terminal.

        `TTL == -2` (key vanished between the SCAN and here) is
        counted too — there is nothing left to hydrate.

        The proof is one-directional: under `retention_sec = 0` a
        terminal row carries no TTL and is *not* reported here, so the
        caller must still drop terminal rows after deserializing.

        Args:
            keys: Job keys from the current SCAN batch.

        Returns:
            The keys worth skipping entirely.
        """
        # `transaction=False` — a plain command pipeline, not MULTI:
        # this is a read-only batch and the rows are independent, so
        # wrapping them in a transaction would only add round-trip
        # bookkeeping.
        async with self._client.pipeline(transaction=False) as pipe:
            for key in keys:
                pipe.ttl(key)
            ttls = await pipe.execute()
        return {
            key
            for key, ttl in zip(keys, ttls, strict=True)
            if isinstance(ttl, int) and ttl != -1
        }

    async def scan_jobs(self, *, max_scan: int) -> tuple[list[Job], bool]:
        """Read the non-terminal persisted jobs via cursor-based SCAN.

        Deliberately SCAN and not KEYS: `KEYS job:*` blocks the Redis
        event loop for the whole keyspace, which on a production
        instance means a stall for every other client. SCAN trades
        exactness (it can return duplicates, and misses keys created
        mid-sweep) for bounded per-call work; the redriver only needs
        a good-enough snapshot of what the previous generation of
        workers left behind, and duplicates are deduplicated here.

        Terminal rows are filtered out *before* their bodies are
        fetched wherever the retention TTL makes that decidable (see
        `_terminal_keys`), and after deserialization otherwise. The
        redriver has nothing to do with a terminal row either way, so
        returning them only cost bandwidth.

        A key whose payload will not deserialize is logged as
        `job_scan_bad_payload` and skipped rather than aborting the
        sweep — one corrupt row must not block reconciling the rest.

        Args:
            max_scan: Upper bound on keys examined, so a huge keyspace
                cannot stall startup. Counted in *keys*, including the
                terminal ones that never become jobs, so the cap
                bounds the work rather than the yield.

        Returns:
            `(jobs, scan_capped)` — the non-terminal jobs, and whether
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
                skip = await self._terminal_keys(fresh)
                hydrate = [k for k in fresh if k not in skip]
                payloads = (
                    await self._client.mget(hydrate) if hydrate else []
                )
                for key, raw in zip(hydrate, payloads, strict=True):
                    payload = _as_text(raw)
                    if payload is None:
                        # Key expired between the SCAN and the MGET.
                        continue
                    try:
                        job = _job_from_json(payload)
                    except (ValueError, TypeError, KeyError):
                        log.warning("job_scan_bad_payload", extra={"key": key})
                        continue
                    if job.is_terminal():
                        # `retention_sec = 0` deployments give terminal
                        # rows no TTL, so the cheap pre-filter cannot
                        # see them. Correctness lives here; the TTL
                        # check is only an optimization on top.
                        continue
                    jobs.append(job)

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
