"""Job kinds and the `awaiting_learner` parking (ADR 0057, WO-W01).

The sibling of `tests/test_api_hitl.py`, one parking over. Where that
file drives an `InterruptingStub` that pauses after the planner and is
reviewed once, `TurnTakingStub` here pauses on *every* turn and must be
resumed on every one of them — which is the single structural
difference between the two kinds and the reason the pause policy is a
parameter rather than a branch.

What these tests are actually protecting is the claim that a session
job is an ordinary job: it takes the same lease, the same semaphore,
the same cancel token, the same cost accumulator and the same terminal
persistence the research path spent fifty ADRs getting right. So the
assertions are deliberately about the *lifecycle* — status transitions,
frames, cross-worker resume, timeout, redrive — and say nothing about
what a turn contains, which is WO-W03's to define.

No paid model is reachable from any of this: the stub graph is the only
graph, and `ANTHROPIC_API_KEY` is never read.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
import pytest

from src.api import runner as runner_module
from src.api.jobs import (
    DEFAULT_JOB_KIND,
    JOB_KINDS,
    PARKED_STATUSES,
    TERMINAL_STATUSES,
    InMemoryJobStore,
    Job,
    JobStatus,
)
from src.api.redis_store import RedisJobStore
from src.api.redriver import ORPHANED_ERROR_TYPE, JobRedriver
from src.api.runner import (
    JOB_KIND_RUNTIMES,
    RESEARCH_RUNTIME,
    SESSION_RUNTIME,
    SESSION_TURN_STATE_KEY,
    SessionTurnTimeoutError,
    run_job,
    runtime_for,
)
from src.config import settings

pytestmark = pytest.mark.integration


class TurnTakingStub:
    """Fake compiled session graph that interrupts once per turn.

    Mirrors `test_api_hitl.py::InterruptingStub`'s contract against the
    runner's async surface, with one difference that is the whole point:
    it re-arms its interrupt on *every* resume until `turns` of them
    have happened. A runner that auto-resumed any of those would drive
    the session to its end with nobody in the chair, and the turn count
    assertions below are what would catch it.
    """

    def __init__(self, *, turns: int = 2) -> None:
        self.turns = turns
        self.turns_taken = 0
        self.state_values: dict[str, Any] = {}
        self.update_state_calls: list[dict[str, Any]] = []
        self._interrupted = False

    async def astream(
        self,
        state: dict[str, Any] | None,
        config: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if state is not None:
            self.state_values = dict(state)
        self.turns_taken += 1
        if self.turns_taken <= self.turns:
            update = {
                SESSION_TURN_STATE_KEY: {
                    "turn_number": self.turns_taken,
                    "prompt": f"turn {self.turns_taken}",
                }
            }
            self.state_values = {**self.state_values, **update}
            yield {"tutor": update}
            self._interrupted = True
            return

        self._interrupted = False
        closing = {"draft_report": "session complete", SESSION_TURN_STATE_KEY: {}}
        self.state_values = {**self.state_values, **closing}
        yield {"wrap_up": closing}

    async def aget_state(self, config: dict[str, Any] | None = None) -> Any:
        next_nodes: tuple[str, ...] = ("tutor",) if self._interrupted else ()
        return SimpleNamespace(next=next_nodes, values=dict(self.state_values))

    async def aupdate_state(
        self, config: dict[str, Any] | None, values: dict[str, Any]
    ) -> None:
        self.update_state_calls.append(dict(values))
        self.state_values = {**self.state_values, **values}


class RecordingStore(InMemoryJobStore):
    """InMemoryJobStore that records every status written through it."""

    def __init__(self) -> None:
        super().__init__()
        self.status_history: list[JobStatus] = []

    async def update(self, job: Job) -> None:
        self.status_history.append(job.status)
        await super().update(job)


def _session_job(job_id: str = "sess-1") -> Job:
    return Job(job_id=job_id, query="teach me attention", kind="session")


def _drain_frames(job: Job) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    while not job.event_queue.empty():
        frames.append(job.event_queue.get_nowait())
    return frames


async def _wait_for_status(
    store: InMemoryJobStore,
    job_id: str,
    target: JobStatus,
    *,
    timeout_sec: float = 5.0,
) -> Job:
    deadline = time.monotonic() + timeout_sec
    while True:
        job = await store.get(job_id)
        assert job is not None
        if job.status == target or job.is_terminal():
            return job
        if time.monotonic() > deadline:
            raise TimeoutError(f"job {job_id} still {job.status} after {timeout_sec}s")
        await asyncio.sleep(0.01)


async def _wait_for_turn(
    store: InMemoryJobStore,
    job_id: str,
    turn_number: int,
    *,
    timeout_sec: float = 5.0,
) -> Job:
    """Wait until the job is parked on a specific turn.

    Deliberately not "wait for `running`, then wait for parked again":
    a resumed session re-parks within a few event-loop ticks, so the
    intermediate `running` is a state a poller can miss entirely, and
    a test that waits to observe it hangs on a system that is working
    perfectly. The turn number is the thing that actually advances.
    """
    deadline = time.monotonic() + timeout_sec
    while True:
        job = await store.get(job_id)
        assert job is not None
        parked_here = (
            job.status == JobStatus.awaiting_learner
            and (job.turn or {}).get("turn_number") == turn_number
        )
        if parked_here or job.is_terminal():
            return job
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"job {job_id} never parked on turn {turn_number} "
                f"(status={job.status}, turn={job.turn})"
            )
        await asyncio.sleep(0.005)


# ---------------------------------------------------------------------------
# The kind field itself.
# ---------------------------------------------------------------------------


class TestJobKind:
    def test_the_default_is_research_so_nothing_existing_changes_meaning(
        self,
    ) -> None:
        assert DEFAULT_JOB_KIND == "research"
        assert Job(job_id="j", query="q").kind == "research"

    def test_every_declared_kind_has_a_runtime(self) -> None:
        """The dispatch table is total, checked against the type itself.

        A kind added to the `Literal` without a runtime would fall
        through `runtime_for` to the research policy — a session that
        auto-resumes past every turn, which is silent rather than loud.
        """
        assert set(JOB_KIND_RUNTIMES) == JOB_KINDS

    def test_unknown_kinds_fall_back_loudly(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A row from a worker with a wider vocabulary keeps running."""
        with caplog.at_level("WARNING"):
            assert runtime_for("curriculum") is RESEARCH_RUNTIME
        assert "api_job_unknown_kind" in caplog.text

    @pytest.mark.parametrize("kind", [None, 7, ["session"], {"kind": "session"}])
    def test_runtime_lookup_is_total_even_for_impossible_inputs(
        self, kind: object
    ) -> None:
        """`run_job` resolves the runtime before its containment `try`.

        It promises never to raise, so this lookup has to be total for
        inputs the annotation says cannot occur — an unhashable one
        would otherwise `TypeError` straight out of `run_job` and leave
        the job non-terminal with its SSE clients hanging, which is the
        precise failure the containment block exists to prevent.
        """
        assert runtime_for(kind) is RESEARCH_RUNTIME  # type: ignore[arg-type]

    def test_the_parked_statuses_are_non_terminal(self) -> None:
        assert {
            JobStatus.pending_review,
            JobStatus.awaiting_learner,
        } == PARKED_STATUSES
        assert not (PARKED_STATUSES & TERMINAL_STATUSES)
        assert Job(
            job_id="j", query="q", status=JobStatus.awaiting_learner
        ).is_parked()

    def test_a_parked_session_is_not_awaiting_review(self) -> None:
        """`POST /research/{id}/review`'s guard must stay narrow.

        The review endpoint pushes an approve/revise/cancel action into
        a graph that expects one; a session graph has no idea what to
        do with one, so it must 409 rather than resume.
        """
        job = _session_job()
        job.status = JobStatus.awaiting_learner
        assert job.is_parked()
        assert not job.is_awaiting_review()


# ---------------------------------------------------------------------------
# Criterion 2 — park, frame, resume, timeout.
# ---------------------------------------------------------------------------


class TestSessionParking:
    async def test_parks_in_awaiting_learner_and_emits_turn_ready(self) -> None:
        stub = TurnTakingStub(turns=1)
        store = RecordingStore()
        job = _session_job()
        await store.create(job)

        task = asyncio.create_task(
            run_job(job, stub, store, asyncio.Semaphore(1), timeout_sec=30)
        )
        parked = await _wait_for_status(store, job.job_id, JobStatus.awaiting_learner)
        assert parked.status == JobStatus.awaiting_learner
        # The frame is published after the store write, so a client that
        # polls the instant it arrives cannot read `running`.
        assert store.status_history.index(JobStatus.awaiting_learner) >= 0
        assert parked.turn == {"turn_number": 1, "prompt": "turn 1"}

        frames = _drain_frames(job)
        turn_frames = [f for f in frames if f["event"] == "turn_ready"]
        assert len(turn_frames) == 1
        assert turn_frames[0]["data"] == {
            "job_id": job.job_id,
            "turn": {"turn_number": 1, "prompt": "turn 1"},
        }
        # A pause frame, not an outcome: nothing terminal went out.
        assert not [f for f in frames if f["event"].startswith("job_")and f["event"] != "job_started"]

        job.resume_payload = {"learner_reply": "because it weights tokens"}
        job.resume_event.set()
        await asyncio.wait_for(task, timeout=5)

        settled = await store.get(job.job_id)
        assert settled is not None
        assert settled.status == JobStatus.succeeded
        # Unparked cleanly: nothing left over to make the next park
        # return instantly.
        assert settled.turn is None
        assert settled.resume_payload is None
        assert not settled.resume_event.is_set()
        # The learner's reply reached the graph.
        assert stub.update_state_calls == [
            {"learner_reply": "because it weights tokens"}
        ]

    async def test_every_turn_parks_rather_than_auto_resuming(self) -> None:
        """The one structural difference from plan review.

        `_handle_hitl_pause` reviews pause 1 and auto-resumes the rest.
        A session doing that would answer its own questions.
        """
        stub = TurnTakingStub(turns=3)
        store = RecordingStore()
        job = _session_job("sess-many")
        await store.create(job)

        task = asyncio.create_task(
            run_job(job, stub, store, asyncio.Semaphore(1), timeout_sec=30)
        )
        for expected_turn in (1, 2, 3):
            parked = await _wait_for_turn(store, job.job_id, expected_turn)
            assert parked.status == JobStatus.awaiting_learner, expected_turn
            assert parked.turn == {
                "turn_number": expected_turn,
                "prompt": f"turn {expected_turn}",
            }
            job.resume_payload = {"learner_reply": f"answer {expected_turn}"}
            job.resume_event.set()

        await asyncio.wait_for(task, timeout=5)
        settled = await store.get(job.job_id)
        assert settled is not None and settled.status == JobStatus.succeeded
        assert store.status_history.count(JobStatus.awaiting_learner) == 3
        assert len(stub.update_state_calls) == 3

    async def test_turn_timeout_ends_the_job_in_a_terminal_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "settings",
            settings.model_copy(update={"session_turn_timeout_sec": 1}),
        )
        stub = TurnTakingStub(turns=1)
        store = RecordingStore()
        job = _session_job("sess-timeout")
        await store.create(job)

        await run_job(job, stub, store, asyncio.Semaphore(1), timeout_sec=30)

        settled = await store.get(job.job_id)
        assert settled is not None
        assert settled.status == JobStatus.failed
        assert settled.is_terminal()
        assert settled.error_type == "session_turn_timeout"
        # The message names the parking, not the parking's owner.
        assert settled.error == "awaiting_learner exceeded 1s"
        # ...and the terminal row does not still advertise the turn it
        # was waiting on. A `failed` job carrying an open question would
        # tell the Ledger a session is mid-flight when it is over.
        assert settled.turn is None
        frames = _drain_frames(job)
        assert frames[-1]["event"] == "job_failed"
        assert frames[-1]["data"]["error_type"] == "session_turn_timeout"

    async def test_the_turn_timeout_is_its_own_setting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not `api_hitl_timeout_sec` wearing a different name.

        The two wait on different humans doing different things, so a
        deployment that lengthens plan review must not silently
        lengthen every learner turn.
        """
        monkeypatch.setattr(
            runner_module,
            "settings",
            settings.model_copy(
                update={"api_hitl_timeout_sec": 3600, "session_turn_timeout_sec": 1}
            ),
        )
        stub = TurnTakingStub(turns=1)
        store = RecordingStore()
        job = _session_job("sess-own-timeout")
        await store.create(job)

        started = time.monotonic()
        await run_job(job, stub, store, asyncio.Semaphore(1), timeout_sec=30)
        assert time.monotonic() - started < 30

        settled = await store.get(job.job_id)
        assert settled is not None and settled.error_type == "session_turn_timeout"

    async def test_the_pause_ceiling_is_a_turn_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A session that never ends fails loudly instead of silently.

        The research path bounds its resume loop with
        `max_iterations + 2`, which for a session would fail an
        ordinary conversation on turn four.
        """
        monkeypatch.setattr(
            runner_module,
            "settings",
            settings.model_copy(update={"session_max_turns": 2}),
        )
        assert SESSION_RUNTIME.max_pauses() == 2
        stub = TurnTakingStub(turns=99)
        store = RecordingStore()
        job = _session_job("sess-runaway")
        await store.create(job)

        async def resume_forever() -> None:
            while True:
                await asyncio.sleep(0.01)
                if job.status == JobStatus.awaiting_learner:
                    job.resume_payload = {"learner_reply": "again"}
                    job.resume_event.set()

        pump = asyncio.create_task(resume_forever())
        try:
            await asyncio.wait_for(
                run_job(job, stub, store, asyncio.Semaphore(1), timeout_sec=30),
                timeout=10,
            )
        finally:
            pump.cancel()

        settled = await store.get(job.job_id)
        assert settled is not None
        assert settled.status == JobStatus.failed
        assert "still interrupted after 2 resumes" in (settled.error or "")


# ---------------------------------------------------------------------------
# Criterion 2 — the ADR 0034 cross-worker property, for the new parking.
# ---------------------------------------------------------------------------


@pytest.fixture
async def shared_backend() -> AsyncIterator[fakeredis.aioredis.FakeRedis]:
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


class TestCrossWorkerTurnResume:
    async def test_a_turn_submitted_to_another_worker_wakes_the_runner(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The property ADR 0034 bought, inherited rather than rebuilt.

        Worker A's runner is parked in `awaiting_learner`; worker B
        receives the learner's turn. The channel is the same
        `hitl:resume:{job_id}` — it is keyed by job id, not by what the
        job is waiting for — so nothing new had to be stood up.
        """
        worker_a = RedisJobStore(shared_backend, retention_sec=60)
        worker_b = RedisJobStore(shared_backend, retention_sec=60)
        job = _session_job("sess-xworker")

        watch = asyncio.create_task(worker_a.watch_for_remote_resume(job))
        await asyncio.sleep(0.05)

        await worker_b.publish_remote_resume(
            job_id=job.job_id,
            action="turn",
            plan=None,
            payload={"learner_reply": "self-attention scores"},
        )

        await asyncio.wait_for(job.resume_event.wait(), timeout=1.0)
        await asyncio.wait_for(watch, timeout=1.0)

        assert job.resume_payload == {"learner_reply": "self-attention scores"}
        # The plan-review fields stay empty: a turn is not a plan.
        assert job.resume_plan is None

    async def test_a_plan_review_message_still_carries_no_payload(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The additive key is additive in both directions."""
        worker_a = RedisJobStore(shared_backend, retention_sec=60)
        worker_b = RedisJobStore(shared_backend, retention_sec=60)
        job = Job(job_id="research-xworker", query="q")

        watch = asyncio.create_task(worker_a.watch_for_remote_resume(job))
        await asyncio.sleep(0.05)
        await worker_b.publish_remote_resume(
            job_id=job.job_id,
            action="approve",
            plan=None,
        )
        await asyncio.wait_for(job.resume_event.wait(), timeout=1.0)
        await asyncio.wait_for(watch, timeout=1.0)

        assert job.resume_action == "approve"
        assert job.resume_payload is None


# ---------------------------------------------------------------------------
# Criterion 1's other half — the new fields survive Redis.
# ---------------------------------------------------------------------------


class TestRedisRoundTrip:
    async def test_kind_turn_and_resume_payload_round_trip(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        store = RedisJobStore(shared_backend, retention_sec=60)
        job = _session_job("sess-roundtrip")
        job.status = JobStatus.awaiting_learner
        job.turn = {"turn_number": 2, "prompt": "why does it help?"}
        job.resume_payload = {"learner_reply": "longer range context"}
        await store.update(job)
        store._local.pop(job.job_id, None)

        restored = await store.get(job.job_id)
        assert restored is not None
        assert restored.kind == "session"
        assert restored.status == JobStatus.awaiting_learner
        assert restored.turn == {"turn_number": 2, "prompt": "why does it help?"}
        assert restored.resume_payload == {"learner_reply": "longer range context"}

    async def test_a_row_written_before_kinds_existed_reads_as_research(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Forward compatibility in the direction that actually happens.

        A rolling deploy has old workers writing rows a new worker
        reads. Those rows have no `kind`, and they are research jobs.
        """
        store = RedisJobStore(shared_backend, retention_sec=60)
        await shared_backend.set(
            "job:legacy-row",
            '{"job_id":"legacy-row","query":"q","status":"running",'
            '"created_at":1.0}',
        )
        restored = await store.get("legacy-row")
        assert restored is not None
        assert restored.kind == "research"
        assert runtime_for(restored.kind) is RESEARCH_RUNTIME

    async def test_a_kind_from_the_future_is_logged_not_crashed(
        self,
        shared_backend: fakeredis.aioredis.FakeRedis,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        store = RedisJobStore(shared_backend, retention_sec=60)
        await shared_backend.set(
            "job:future-row",
            '{"job_id":"future-row","query":"q","status":"running",'
            '"kind":"curriculum","created_at":1.0}',
        )
        with caplog.at_level("WARNING"):
            restored = await store.get("future-row")
        assert restored is not None
        assert restored.kind == "research"
        assert "job_kind_unknown" in caplog.text


# ---------------------------------------------------------------------------
# Criterion 3 — the redriver, and retention.
# ---------------------------------------------------------------------------


class TestRedriveOfParkedSessions:
    async def test_a_parked_session_on_a_live_worker_is_left_alone(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """The criterion-3 property: parked is not stale.

        A live runner refreshes the job's lease for the whole time it
        waits, so a learner taking ten minutes over a passage looks
        exactly like a reviewer taking ten minutes over a plan — which
        is to say, like a healthy job.
        """
        store = RedisJobStore(shared_backend, retention_sec=3600)
        peer = RedisJobStore(shared_backend, retention_sec=3600)
        job = _session_job("sess-parked-live")
        job.status = JobStatus.awaiting_learner
        job.started_at = time.time() - 3600
        await store.update(job)
        store._local.pop(job.job_id, None)
        # The worker that owns it is alive and holding the lease.
        assert await peer.acquire_lease(job.job_id, "live-worker", 90)

        report = await JobRedriver(store, worker_id="booting").sweep()

        assert report.skipped_live == 1
        assert report.orphaned == 0
        after = await store.get(job.job_id)
        assert after is not None
        assert after.status == JobStatus.awaiting_learner
        assert after.error_type is None

    async def test_an_orphaned_parked_session_is_failed_never_requeued(
        self, shared_backend: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Same policy as an orphaned `pending_review`, for the same reason.

        The turns already made LLM calls and the mid-session state
        lived in the dead worker's process. Requeueing would bill the
        operator twice for a session it cannot reconstruct — so it is
        failed even with requeue explicitly turned on.
        """
        store = RedisJobStore(shared_backend, retention_sec=3600)
        job = _session_job("sess-orphan")
        job.status = JobStatus.awaiting_learner
        job.started_at = time.time() - 3600
        await store.update(job)
        store._local.pop(job.job_id, None)

        resubmitted: list[str] = []

        async def resubmit(reclaimed: Job) -> None:
            resubmitted.append(reclaimed.job_id)

        report = await JobRedriver(
            store,
            worker_id="booting",
            requeue_pending=True,
            resubmit=resubmit,
        ).sweep()

        assert report.failed == 1
        assert report.requeued == 0
        assert resubmitted == []
        after = await store.get(job.job_id)
        assert after is not None
        assert after.status == JobStatus.failed
        assert after.error_type == ORPHANED_ERROR_TYPE

    async def test_retention_still_never_evicts_a_parked_job(self) -> None:
        """Job retention semantics are unchanged (criterion 3).

        `evict_older_than` drops terminal rows only. A parked session is
        non-terminal, so it is never garbage — same as a parked review,
        and same as a stuck `running` job, which the module docstring
        calls a diagnostic signal rather than garbage.
        """
        store = InMemoryJobStore()
        parked = _session_job("sess-old")
        parked.status = JobStatus.awaiting_learner
        parked.completed_at = time.time() - 10_000
        done = Job(job_id="done", query="q", status=JobStatus.succeeded)
        done.completed_at = time.time() - 10_000
        await store.create(parked)
        await store.create(done)

        evicted = await store.evict_older_than(60)

        assert evicted == 1
        assert await store.get("sess-old") is not None
        assert await store.get("done") is None


# ---------------------------------------------------------------------------
# The research path, asserted from the session side.
# ---------------------------------------------------------------------------


class TestResearchIsUntouched:
    async def test_a_research_job_still_gets_the_research_runtime(self) -> None:
        assert runtime_for("research") is RESEARCH_RUNTIME
        assert runtime_for("session") is SESSION_RUNTIME
        assert RESEARCH_RUNTIME.on_pause is not SESSION_RUNTIME.on_pause

    async def test_the_research_outer_timeout_still_adds_the_hitl_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pre-ADR-0057 arithmetic, moved but not changed."""
        monkeypatch.setattr(
            runner_module,
            "settings",
            settings.model_copy(
                update={"enable_hitl": True, "api_hitl_timeout_sec": 1800}
            ),
        )
        job = Job(job_id="j", query="q")
        assert RESEARCH_RUNTIME.outer_timeout(job, 600.0) == 2400.0
        job.hitl_bypass = True
        assert RESEARCH_RUNTIME.outer_timeout(job, 600.0) == 600.0

    async def test_the_session_outer_timeout_covers_every_turn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            runner_module,
            "settings",
            settings.model_copy(
                update={"session_turn_timeout_sec": 60, "session_max_turns": 5}
            ),
        )
        assert SESSION_RUNTIME.outer_timeout(_session_job(), 600.0) == 900.0

    def test_the_session_timeout_error_is_a_plain_exception(self) -> None:
        """Load-bearing for `web/tests/copy/errorTypeDrift.test.ts`.

        That test derives the frontend's error vocabulary by matching
        `class X(Exception)` in `src/`. A shared base class between the
        two parking timeouts would drop both out of the enumeration and
        silently un-map them.
        """
        assert SessionTurnTimeoutError.__bases__ == (Exception,)
