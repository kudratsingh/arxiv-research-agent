"""The terminal SSE frame cannot be delivered (WO-A06 scenario 7).

The terminal frame is every connected client's close signal. When the
pub/sub transport is down, the frame is retried three times and the
give-up is escalated to an ERROR — and the two things that must remain
true through all of it are that **the job row is still correct** and
that **the failure is visible**.

Both are easy to get wrong in the same direction. A publish failure
that propagated would leave the job wedged non-terminal with its
clients hanging; a publish failure that were swallowed silently would
leave the clients hanging *and* leave no trace of why. The runner's
answer is neither: absorb, escalate, and let the durable row be the
source of truth.

Nothing in the suite asserted any of the five SSE failure events before
this file — they were all registered in `KNOWN_EVENTS` and never
exercised.

| leg | terminal-frame failure | intermediate-frame failure |
|---|---|---|
| code | the job's own outcome code, unchanged by the delivery failure |
| event | `sse_terminal_publish_failed` ×3 → `sse_terminal_publish_gave_up` | `sse_publish_failed` |
| metric | `research_jobs_total{status, error_type}` — recorded either way |
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection
from typing import Any

import pytest

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import _TERMINAL_PUBLISH_ATTEMPTS, run_job
from src.errors import AppError

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]

REPORT = "# Findings\n\nThe report the client will never be told about."

#: The frames that carry a job's close signal. Named here so the
#: terminal-frame tests can break *only* the delivery path under test
#: and leave progress frames working — two faults at once would make it
#: impossible to say which handler produced which line.
TERMINAL_FRAMES = frozenset({"job_completed", "job_failed", "job_cancelled"})


class _UndeliverableStore(InMemoryJobStore):
    """A store whose pub/sub transport is down, but whose rows are fine.

    Deliberately *only* the publish path fails. Breaking the write too
    would conflate two faults, and the property under test here is
    precisely that a dead fan-out does not corrupt the durable record —
    which is only observable while the writes still work.
    """

    def __init__(self, *, fails: Collection[str] | None = None) -> None:
        super().__init__()
        self._fails = frozenset(fails) if fails is not None else None
        self.attempts: list[str] = []

    async def publish_event(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        if self._fails is None or event in self._fails:
            self.attempts.append(event)
            raise ConnectionError("redis://cache.internal:6379 connection reset")


async def _run_to_success(store: InMemoryJobStore, workflow: Any) -> Job:
    job = Job(job_id="undeliverable", query="q", hitl_bypass=True)
    await store.create(job)
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job


class TestTheTerminalFrameCannotBeDelivered:
    async def test_the_job_row_is_correct_and_the_give_up_is_an_error(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        no_backoff: None,
    ) -> None:
        store = _UndeliverableStore(fails=TERMINAL_FRAMES)
        workflow = scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}])

        job = await _run_to_success(store, workflow)

        # The row is the source of truth and it is intact — status,
        # report and all. A client that reconnects and polls gets the
        # right answer even though the stream told it nothing.
        assert job.status == JobStatus.succeeded
        stored = await store.get("undeliverable")
        assert stored is not None
        assert stored.status == JobStatus.succeeded
        assert stored.result == REPORT

        # A succeeded job carries no code; the metric attribute is the
        # literal `none` so every terminal series has the same shape.
        triple.assert_triple(
            code=None,
            event="sse_terminal_publish_gave_up",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
        assert triple.one_record("sse_terminal_publish_gave_up").levelno == logging.ERROR

    async def test_every_attempt_is_logged_before_the_give_up(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        no_backoff: None,
    ) -> None:
        """Three WARNINGs then one ERROR, and the count is the contract.

        An operator reading `sse_terminal_publish_gave_up` needs to know
        the transport was actually retried rather than abandoned on the
        first blip, and the per-attempt lines are the only evidence of
        that. Asserting the number also pins the retry budget itself:
        silently dropping to one attempt would leave this green if the
        assertion were merely "at least one".
        """
        store = _UndeliverableStore(fails=TERMINAL_FRAMES)
        workflow = scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}])

        await _run_to_success(store, workflow)

        retried = triple.records("sse_terminal_publish_failed")
        assert len(retried) == _TERMINAL_PUBLISH_ATTEMPTS
        assert [r.levelno for r in retried] == [logging.WARNING] * _TERMINAL_PUBLISH_ATTEMPTS
        assert [getattr(r, "attempt", None) for r in retried] == [1, 2, 3]
        assert {getattr(r, "event", None) for r in retried} == {"job_completed"}
        assert store.attempts == ["job_completed"] * _TERMINAL_PUBLISH_ATTEMPTS

    async def test_no_terminal_frame_is_smuggled_onto_the_local_queue(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        frames: Any,
        no_backoff: None,
    ) -> None:
        """The failure is visible, not papered over.

        Falling back to the in-process queue would look like a fix and
        would not be one: under the pub/sub store the SSE consumer is
        subscribed to the channel, not to this queue, so a frame put
        there reaches nobody while making the logs claim delivery
        succeeded. The honest outcome is the ERROR line.
        """
        store = _UndeliverableStore(fails=TERMINAL_FRAMES)
        workflow = scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}])

        job = await _run_to_success(store, workflow)

        assert frames(job) == []
        assert triple.records("sse_terminal_publish_gave_up") != []

    async def test_a_failed_jobs_code_survives_a_dead_transport(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        no_backoff: None,
    ) -> None:
        """Two faults at once: the run failed *and* nobody can be told.

        The delivery failure must not overwrite the reason the job
        failed — which is the value the metric series and the client's
        eventual poll both key on.
        """
        store = _UndeliverableStore(fails=TERMINAL_FRAMES)
        workflow = scripted_workflow(raises=RuntimeError("node exploded"))

        job = await _run_to_success(store, workflow)

        assert job.status == JobStatus.failed
        assert job.error_type == AppError.code
        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": "internal_unexpected"},
        )
        assert triple.records("sse_terminal_publish_gave_up") != []


class TestAnIntermediateFrameCannotBeDelivered:
    async def test_a_dropped_progress_frame_degrades_the_stream_not_the_job(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """Not every frame is worth failing a run over.

        `node_completed` is progress; losing it costs a client a
        progress bar. The distinction from the terminal frame is
        deliberate and is the reason the two have different handlers:
        one attempt, one WARNING, and the run carries on to produce the
        report the user asked for.
        """
        store = _UndeliverableStore(fails={"node_completed"})
        workflow = scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}])

        job = await _run_to_success(store, workflow)

        assert job.status == JobStatus.succeeded
        assert job.result == REPORT
        record = triple.assert_triple(
            code=None,
            event="sse_publish_failed",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
        assert record.levelno == logging.WARNING
        assert getattr(record, "event", None) == "node_completed"
        # One attempt, not three: an intermediate frame has no retry
        # budget, because the next frame is along shortly anyway.
        assert store.attempts == ["node_completed"]
