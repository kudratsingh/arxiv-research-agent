"""Unit tests for the SSE streaming loop (ADR 0038).

The loop used to live as a closure inside `stream_research`, which
made it untestable and hid a real bug: each iteration raced a fresh
`drainer.__anext__()` task against a sleep and cancelled the loser,
so the first idle heartbeat threw `CancelledError` into the drainer
at its suspension point and permanently closed it. The stream then
died with no terminal frame. `test_stream_survives_idle_heartbeat`
below is the regression guard for exactly that.

Everything here drives `sse_event_stream` directly with a scripted
drainer, a fake disconnect probe and (for the deadline test) a fake
clock — no FastAPI, no Redis, no multi-second sleeps.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from src.api import redis_store
from src.api.jobs import Job, JobStatus
from src.api.routes import stream_research
from src.api.streaming import (
    STREAM_CLOSING_EVENT_NAMES,
    STREAM_TIMEOUT_EVENT,
    TERMINAL_EVENT_NAMES,
    closes_stream,
    format_heartbeat,
    format_sse,
    is_terminal_event,
    sse_event_stream,
)

pytestmark = pytest.mark.unit

HEARTBEAT = 0.05
KEEPALIVE = b": heartbeat\n\n"

# A frame step is a dict; a float step is "stay quiet for N seconds".
Step = float | dict[str, Any]


def _event(name: str, **data: Any) -> dict[str, Any]:
    return {"event": name, "data": dict(data)}


async def _scripted(steps: Sequence[Step]) -> AsyncGenerator[dict[str, Any], None]:
    """Play `steps` out, then park instead of ending.

    Parking rather than returning keeps `StopAsyncIteration` out of
    the picture unless a test asks for it, so "the stream ended" can
    only mean the loop decided to stop.
    """
    for step in steps:
        if isinstance(step, dict):
            yield step
        else:
            await asyncio.sleep(step)
    await asyncio.Event().wait()


class RecordingDrainer:
    """Drainer wrapper that counts reads and `aclose` calls.

    The loop is required to close its drainer on every exit path;
    counting here is how the tests observe that without reaching for
    a real Redis pubsub.
    """

    def __init__(self, source: AsyncGenerator[dict[str, Any], None]) -> None:
        self._source = source
        self.reads = 0
        self.aclose_calls = 0
        self.cleaned_up = False

    def __aiter__(self) -> RecordingDrainer:
        return self

    async def __anext__(self) -> dict[str, Any]:
        frame = await self._source.__anext__()
        self.reads += 1
        return frame

    async def aclose(self) -> None:
        self.aclose_calls += 1
        await self._source.aclose()
        self.cleaned_up = True


def _drainer(*steps: Step) -> RecordingDrainer:
    return RecordingDrainer(_scripted(steps))


async def _connected() -> bool:
    """Disconnect probe for a client that stays put."""
    return False


class DisconnectAfter:
    """Disconnect probe that flips to True on the Nth poll."""

    def __init__(self, polls: int) -> None:
        self._polls = polls
        self.calls = 0

    async def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self._polls


class FakeClock:
    """Monotonic clock that advances a fixed step per read.

    Lets the deadline test cross `max_duration_sec` after two loop
    iterations instead of sleeping for an hour.
    """

    def __init__(self, step: float) -> None:
        self.step = step
        self.t = 0.0

    def __call__(self) -> float:
        self.t += self.step
        return self.t


class ManualClock:
    """Clock that only moves when the test moves it.

    The deadline-flush tests need the deadline to fire at one exact
    point in the loop, which a per-read step cannot express.
    """

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


async def _collect(stream: AsyncIterator[bytes], *, timeout: float = 5.0) -> list[bytes]:
    """Drain the stream to a list, failing fast if it never ends."""

    async def _run() -> list[bytes]:
        return [chunk async for chunk in stream]

    return await asyncio.wait_for(_run(), timeout=timeout)


def _events(chunks: Sequence[bytes]) -> list[str]:
    """Event names of the non-keepalive frames, in order."""
    names: list[str] = []
    for chunk in chunks:
        text = chunk.decode()
        if text.startswith("event: "):
            names.append(text.split("\n", 1)[0][len("event: ") :])
    return names


def _payload(chunk: bytes) -> dict[str, Any]:
    data_line = next(
        line for line in chunk.decode().splitlines() if line.startswith("data: ")
    )
    parsed: dict[str, Any] = json.loads(data_line[len("data: ") :])
    return parsed


class TestIdleHeartbeat:
    """The ADR 0038 regression: idling must not kill the drainer."""

    async def test_stream_survives_idle_heartbeat(self) -> None:
        # Quiet for three heartbeat intervals, then a real event and
        # a terminal frame. Under the old FIRST_COMPLETED + cancel()
        # loop the first idle heartbeat closed the drainer and the
        # stream ended here with no further frames.
        drainer = _drainer(
            HEARTBEAT * 3,
            _event("node_completed", node="planner"),
            _event("job_completed", job_id="j1"),
        )

        chunks = await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )

        # At least one *idle* keepalive beyond the on-open one.
        assert chunks.count(KEEPALIVE) >= 2
        assert _events(chunks) == ["node_completed", "job_completed"]
        # The event survived the heartbeats rather than being eaten
        # by a cancelled read.
        assert drainer.reads == 2

    async def test_multiple_idle_heartbeats_then_terminal(self) -> None:
        drainer = _drainer(HEARTBEAT * 4, _event("job_failed", error="boom"))

        chunks = await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )

        assert chunks.count(KEEPALIVE) >= 3
        assert _events(chunks) == ["job_failed"]
        assert _payload(chunks[-1]) == {"error": "boom"}


class TestNoFrameLoss:
    @pytest.mark.parametrize("delay", [0.045, 0.05, 0.055])
    async def test_event_landing_on_the_heartbeat_boundary_is_delivered(
        self, delay: float
    ) -> None:
        # A frame arriving within scheduling noise of the heartbeat
        # deadline is the window where the old loop dropped a frame
        # it had already pulled off the queue.
        drainer = _drainer(
            delay,
            _event("node_started", node="search"),
            _event("node_completed", node="search"),
            _event("job_completed", job_id="j2"),
        )

        chunks = await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )

        assert _events(chunks) == [
            "node_started",
            "node_completed",
            "job_completed",
        ]


class TestTerminalHandling:
    async def test_stops_on_terminal_and_does_not_read_past_it(self) -> None:
        drainer = _drainer(
            _event("plan_ready", plan={"sub_questions": []}),
            _event("job_completed", job_id="j3"),
            _event("node_completed", node="never-read"),
        )

        chunks = await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )

        # `plan_ready` is a HITL pause (ADR 0030), not a close signal.
        assert _events(chunks) == ["plan_ready", "job_completed"]
        assert drainer.reads == 2
        assert drainer.aclose_calls == 1

    async def test_exhausted_drainer_ends_the_stream(self) -> None:
        async def empty() -> AsyncGenerator[dict[str, Any], None]:
            if False:  # pragma: no cover - typing anchor for an empty generator
                yield {}

        drainer = RecordingDrainer(empty())

        chunks = await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )

        assert chunks == [KEEPALIVE]
        assert drainer.aclose_calls == 1


class TestDisconnect:
    async def test_disconnect_ends_the_stream(self) -> None:
        # Silent job: without the disconnect probe this would run to
        # the deadline, so ending at all proves the probe fired.
        drainer = _drainer(HEARTBEAT * 50)
        probe = DisconnectAfter(polls=2)

        chunks = await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=probe,
                heartbeat_sec=HEARTBEAT,
                max_duration_sec=30.0,
            ),
            timeout=1.0,
        )

        # Detection latency is bounded by the heartbeat interval, so
        # the frame count tracks the number of polls, not the job.
        assert chunks == [KEEPALIVE, KEEPALIVE, KEEPALIVE]
        assert probe.calls == 3
        assert drainer.aclose_calls == 1

    async def test_disconnect_before_first_read_still_sends_keepalive(self) -> None:
        drainer = _drainer(HEARTBEAT * 50)

        chunks = await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=DisconnectAfter(polls=0),
                heartbeat_sec=HEARTBEAT,
            ),
            timeout=1.0,
        )

        assert chunks == [KEEPALIVE]
        # Nothing was ever pulled from the drainer.
        assert drainer.reads == 0
        assert drainer.aclose_calls == 1


class TestDeadline:
    async def test_deadline_emits_stream_timeout_and_closes(self) -> None:
        drainer = _drainer(HEARTBEAT * 100)
        # `now` is read once for the deadline, then once per loop:
        # deadline = 1 + 3 = 4, crossed on the third iteration.
        clock = FakeClock(step=1.0)

        chunks = await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=_connected,
                heartbeat_sec=HEARTBEAT,
                max_duration_sec=3.0,
                now=clock,
                job_id="j4",
            ),
            timeout=1.0,
        )

        assert _events(chunks) == [STREAM_TIMEOUT_EVENT]
        payload = _payload(chunks[-1])
        assert payload["job_id"] == "j4"
        assert payload["reconnect"] is True
        assert payload["reason"] == "max_duration_exceeded"
        assert drainer.aclose_calls == 1

    @staticmethod
    async def _park_a_finished_read(
        frame: dict[str, Any], job_id: str
    ) -> tuple[
        AsyncGenerator[bytes, None], RecordingDrainer, ManualClock, list[bytes]
    ]:
        """Reproduce the ADR 0048 window, step by step.

        The loop has to be *suspended at its keepalive yield* with a
        read task that has since completed, and the deadline has to
        fire on the next resume. Driving the generator by hand is the
        only way to pin that ordering; a wall-clock race would pass
        against the buggy code often enough to be worthless.
        """
        drainer = _drainer(HEARTBEAT * 2, frame)
        clock = ManualClock()
        stream = sse_event_stream(
            drainer,
            is_disconnected=_connected,
            heartbeat_sec=HEARTBEAT,
            max_duration_sec=1.0,
            now=clock,
            job_id=job_id,
        )

        chunks = [await stream.__anext__()]  # keepalive on open
        # One idle interval: the read task is created and left pending.
        chunks.append(await stream.__anext__())
        assert chunks == [KEEPALIVE, KEEPALIVE]

        # The drainer produces its frame while the loop sits in that
        # yield, so the task is done before the loop looks again...
        await asyncio.sleep(HEARTBEAT * 3)
        assert drainer.reads == 1
        # ...and the deadline passes in the same gap.
        clock.t = 5.0
        return stream, drainer, clock, chunks

    async def test_terminal_frame_beats_the_deadline_to_the_wire(self) -> None:
        # The frame the old loop dropped on the floor: a client whose
        # job ended microseconds before the hour was told
        # `stream_timeout` and sent to reconnect to a finished job.
        stream, drainer, _clock, chunks = await self._park_a_finished_read(
            _event("job_completed", job_id="j9"), "j9"
        )

        chunks.append(await stream.__anext__())
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

        # The frame is delivered, and `stream_timeout` is *not*
        # appended after it: the job ended, so a reconnect signal
        # would be a lie about a stream with nothing left to say.
        assert _events(chunks) == ["job_completed"]
        assert _payload(chunks[-1]) == {"job_id": "j9"}
        assert drainer.aclose_calls == 1

    async def test_non_terminal_frame_is_flushed_then_the_timeout(self) -> None:
        # Same flush, but the pending frame is mid-job: the client
        # gets the work it paid for *and* the reconnect signal.
        stream, drainer, _clock, chunks = await self._park_a_finished_read(
            _event("node_completed", node="synthesizer"), "j10"
        )

        chunks.append(await stream.__anext__())
        chunks.append(await stream.__anext__())
        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

        assert _events(chunks) == ["node_completed", STREAM_TIMEOUT_EVENT]
        assert _payload(chunks[-1])["reconnect"] is True
        assert drainer.aclose_calls == 1

    async def test_deadline_shortens_the_final_wait(self) -> None:
        # With `remaining` under the heartbeat interval the loop must
        # wake at the deadline rather than one heartbeat past it. The
        # heartbeat here is far longer than the wall-clock budget, so
        # dropping the `min(heartbeat_sec, remaining)` clamp makes the
        # loop sleep through the whole interval and the collect times
        # out — which is the only way this asserts the clamp at all.
        drainer = _drainer(60.0)
        clock = FakeClock(step=0.001)

        chunks = await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=_connected,
                heartbeat_sec=30.0,
                max_duration_sec=0.002,
                now=clock,
            ),
            timeout=1.0,
        )

        assert _events(chunks) == [STREAM_TIMEOUT_EVENT]


class TestDrainerCleanup:
    """`aclose` is what stops a disconnected client leaking a Redis
    pubsub connection — it has to run on every exit path."""

    async def test_aclose_on_terminal(self) -> None:
        drainer = _drainer(_event("job_cancelled", job_id="j5"))
        await _collect(
            sse_event_stream(
                drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
            )
        )
        assert drainer.aclose_calls == 1
        assert drainer.cleaned_up

    async def test_aclose_on_disconnect(self) -> None:
        drainer = _drainer(HEARTBEAT * 50)
        await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=DisconnectAfter(polls=1),
                heartbeat_sec=HEARTBEAT,
            ),
            timeout=1.0,
        )
        assert drainer.aclose_calls == 1
        assert drainer.cleaned_up

    async def test_aclose_on_deadline(self) -> None:
        drainer = _drainer(HEARTBEAT * 100)
        await _collect(
            sse_event_stream(
                drainer,
                is_disconnected=_connected,
                heartbeat_sec=HEARTBEAT,
                max_duration_sec=1.0,
                now=FakeClock(step=1.0),
            ),
            timeout=1.0,
        )
        assert drainer.aclose_calls == 1
        assert drainer.cleaned_up

    async def test_aclose_on_drainer_exception(self) -> None:
        async def exploding() -> AsyncGenerator[dict[str, Any], None]:
            yield _event("node_started", node="planner")
            raise RuntimeError("pubsub died")

        drainer = RecordingDrainer(exploding())

        with pytest.raises(RuntimeError, match="pubsub died"):
            await _collect(
                sse_event_stream(
                    drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
                )
            )

        assert drainer.aclose_calls == 1

    async def test_aclose_when_consumer_abandons_the_stream(self) -> None:
        # StreamingResponse drops the generator when the socket goes
        # away; the pending read must be cancelled and the drainer
        # closed rather than left holding a connection.
        drainer = _drainer(HEARTBEAT * 100)
        stream = sse_event_stream(
            drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
        )

        assert await stream.__anext__() == KEEPALIVE
        await stream.aclose()

        assert drainer.aclose_calls == 1


class _StubStore:
    """Store surface `stream_research` touches, wired to one drainer.

    Advertising `subscribe_events` is what puts the route on the ADR
    0035 cross-worker path, which is the one that holds a Redis
    pubsub connection worth leaking.
    """

    def __init__(self, job: Job, drainer: RecordingDrainer) -> None:
        self._job = job
        self._drainer = drainer

    async def get(self, job_id: str) -> Job:
        return self._job

    def subscribe_events(self, job_id: str) -> RecordingDrainer:
        return self._drainer


def _request(store: _StubStore) -> Request:
    """Minimal ASGI request carrying the lifespan state the route reads."""

    async def receive() -> dict[str, Any]:  # pragma: no cover - never polled
        return {"type": "http.request"}

    app = SimpleNamespace(
        state=SimpleNamespace(
            store=store,
            workflow=None,
            semaphore=None,
            max_concurrent_jobs=1,
            tasks=set(),
            conversation_store=None,
        )
    )
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/research/j7/stream",
        "headers": [],
        "query_string": b"",
        "app": app,
    }
    return Request(scope, receive)


class TestRouteClosesTheStream:
    """The route delegates the loop, so it also owns closing it.

    `StreamingResponse` abandons its body iterator when the socket
    goes away — it never calls `aclose()` on it — so the finalization
    the route does see arrives as a `GeneratorExit` at its own `yield
    chunk`, outside the inner `__anext__`. Iterating the delegate with
    a bare `async for` leaves it for the async-generator finalizer,
    which is one leaked pubsub connection per disconnected client.
    """

    async def test_abandoned_response_closes_the_drainer(self) -> None:
        job = Job(job_id="j7", query="q", status=JobStatus.running)
        drainer = _drainer(HEARTBEAT * 100)
        response = await stream_research(
            "j7", _request(_StubStore(job, drainer)), principal=None
        )
        body = cast(AsyncGenerator[bytes, None], response.body_iterator)

        assert await body.__anext__() == KEEPALIVE
        await body.aclose()

        # Deterministically, in the same tick — not "eventually, at GC".
        assert drainer.aclose_calls == 1
        assert drainer.cleaned_up

    async def test_terminal_job_replays_without_touching_the_drainer(self) -> None:
        # The replay path predates ADR 0038 and must stay unchanged:
        # one frame, no subscription, no keepalive.
        job = Job(
            job_id="j8",
            query="q",
            status=JobStatus.succeeded,
            result="# Report",
        )
        drainer = _drainer(HEARTBEAT * 100)
        response = await stream_research(
            "j8", _request(_StubStore(job, drainer)), principal=None
        )
        body = cast(AsyncGenerator[bytes, None], response.body_iterator)

        chunks = [chunk async for chunk in body]

        assert _events(chunks) == ["job_completed"]
        assert drainer.reads == 0
        assert drainer.aclose_calls == 0


class TestImmediateKeepalive:
    async def test_first_chunk_is_a_keepalive_before_any_read(self) -> None:
        # Time-to-first-byte must not depend on how long the first
        # graph node takes; proxies that buffer until first output
        # need bytes immediately.
        drainer = _drainer(HEARTBEAT * 100, _event("job_completed", job_id="j6"))
        stream = sse_event_stream(
            drainer, is_disconnected=_connected, heartbeat_sec=HEARTBEAT
        )

        first = await asyncio.wait_for(stream.__anext__(), timeout=0.01)

        assert first == KEEPALIVE
        assert drainer.reads == 0
        await stream.aclose()


class TestWireFormatAndConstants:
    """Extends `tests/test_api_streaming.py` with the ADR 0038 bits."""

    def test_keepalive_matches_format_heartbeat(self) -> None:
        assert format_heartbeat() == KEEPALIVE

    def test_stream_timeout_frame_is_a_normal_sse_event(self) -> None:
        frame = format_sse(STREAM_TIMEOUT_EVENT, {"reconnect": True})
        assert frame.startswith(b"event: stream_timeout\n")
        assert frame.endswith(b"\n\n")
        assert _payload(frame) == {"reconnect": True}

    def test_stream_timeout_is_not_a_job_outcome(self) -> None:
        # The two sets answer different questions: `stream_timeout`
        # closes the connection but the job is still running, so a
        # client must reconnect rather than mark the job finished.
        assert STREAM_TIMEOUT_EVENT not in TERMINAL_EVENT_NAMES
        assert not is_terminal_event(STREAM_TIMEOUT_EVENT)
        assert closes_stream(STREAM_TIMEOUT_EVENT)

    def test_closing_set_is_a_superset_of_the_terminal_set(self) -> None:
        assert TERMINAL_EVENT_NAMES < STREAM_CLOSING_EVENT_NAMES
        extra = STREAM_CLOSING_EVENT_NAMES - TERMINAL_EVENT_NAMES
        assert extra == {STREAM_TIMEOUT_EVENT}

    @pytest.mark.parametrize(
        "name", ["node_started", "node_completed", "plan_ready", "heartbeat"]
    )
    def test_non_terminal_events_keep_the_stream_open(self, name: str) -> None:
        assert not closes_stream(name)

    def test_terminal_status_map_covers_exactly_the_terminal_names(
        self,
    ) -> None:
        from src.api.streaming import TERMINAL_EVENT_STATUS

        assert set(TERMINAL_EVENT_STATUS) == TERMINAL_EVENT_NAMES

    def test_terminal_status_map_matches_the_real_job_statuses(self) -> None:
        # The map is plain strings to keep `src.api.jobs` out of this
        # module's imports, so the enum has to be pinned from here or
        # a renamed `JobStatus` member would silently start suppressing
        # every terminal frame of that kind (ADR 0048).
        from src.api.jobs import TERMINAL_STATUSES, JobStatus
        from src.api.routes import _terminal_event_name
        from src.api.streaming import TERMINAL_EVENT_STATUS

        assert set(TERMINAL_EVENT_STATUS.values()) == {
            s.value for s in TERMINAL_STATUSES
        }
        # And each name maps to the status the replay path derives it
        # from — the two must agree or a replayed frame would be read
        # as contradicting the row it was built from.
        for event, status_value in TERMINAL_EVENT_STATUS.items():
            job = Job(job_id="j", query="q", status=JobStatus(status_value))
            assert _terminal_event_name(job) == event

    def test_store_reuses_the_shared_terminal_set(self) -> None:
        # The pub/sub reader in `RedisJobStore` asks the same question
        # this module answers, so it imports this constant rather than
        # keeping a copy. Identity, not equality: a copy that drifted
        # would leave a subscriber hanging until the client
        # disconnects, and equality would not catch the re-introduction
        # of a separately-defined duplicate.
        assert redis_store.TERMINAL_EVENT_NAMES is TERMINAL_EVENT_NAMES
