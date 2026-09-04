"""The path a real client takes: submit, stream, fetch, export.

WO-A15 deliverable 3. Every step here exists in a test somewhere
already; the sequence does not. `tests/test_api_smoke_e2e.py` submits
through the production wiring and polls for a terminal status;
`tests/test_api_export_route.py` exports a job a stub produced; the SSE
tests call `sse_event_stream` or `stream_research` directly, or drain
`job.event_queue` after the fact. **No test consumed the stream over
HTTP**, which means the one thing a browser actually does with this API
— open an `EventSource` and read frames until a terminal one — was
never driven end to end.

**Why this module runs a real server.** `httpx.ASGITransport` does not
stream: `handle_async_request` runs the whole ASGI app to completion and
collects `body_parts` before it returns, so a `client.stream(...)` over
it hands back an SSE response only once the job has already finished.
That is enough to read the frames, but not enough to prove the property
that matters — that a client attached *during* the run is told what is
happening while it happens. So the app is served by uvicorn on an
ephemeral loopback port and driven over a real socket. The conftest
network guard allows loopback by design (`pytest-postgresql` binds one
too); nothing here leaves the machine.

Two properties are only visible from here.

The **frame trajectory**: `job_started`, one `node_completed` per graph
node in pipeline order, then exactly one terminal frame and a closed
stream. Polling `GET /research/{id}` proves the job finished; it says
nothing about whether the client watching it was told what happened, or
whether the stream ever closed.

The **zero-spend claim as the user reads it**: `run_job` binds its own
cost accumulator inside the job's context, so this test's own ledger
cannot see the job's spend. The load-bearing assertions are therefore
`cost_usd` and `llm_calls` on the job row, the `cost_usd` on the
terminal frame, and the `$0.0000` the markdown exporter writes into the
document the user downloads.

The first graph node is held at a gate until the client has read the
stream's opening keepalive. Without it the run can reach a terminal
state before the client attaches, and the route then replays a single
terminal frame and closes — a legal outcome (the second test asserts
it) that would quietly turn the frame-trajectory assertion into an
assertion about one frame.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from httpx import AsyncClient

from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: The nodes a `node_completed` frame can name, in pipeline order.
PIPELINE_NODES = ("planner", "search", "reader", "synthesizer", "critic")

#: How long the gated node waits to be released, and how long the
#: client waits for a terminal frame. Both bounded well under the
#: suite's 60-second per-test ceiling so a stall reports its own cause
#: rather than being killed by the timeout plugin with no explanation.
GATE_TIMEOUT_SEC = 20.0
STREAM_TIMEOUT_SEC = 30.0
TERMINAL_TIMEOUT_SEC = 30.0

#: Loopback only. The guard in `tests/conftest.py` refuses anything
#: else, which is the property that makes "runs a real server" and
#: "runs offline" both true.
SERVER_HOST = "127.0.0.1"


def _parse_frames(chunk: str) -> list[tuple[str, dict[str, Any]]]:
    """Decode the SSE frames in one buffer, ignoring heartbeat comments.

    Deliberately a parser rather than a substring check: `event:` and
    `data:` are the two lines a client routes on, and a frame whose data
    is not JSON is a frame a browser's `EventSource` handler throws on.
    """
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in chunk.split("\n\n"):
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = line[len("data: ") :]
        if name:
            frames.append((name, json.loads(payload) if payload else {}))
    return frames


async def _read_until_terminal(
    client: AsyncClient, stream_url: str, on_attached: Callable[[], None]
) -> list[tuple[str, dict[str, Any]]]:
    """Consume one job's SSE stream from attach to close.

    `on_attached` fires once the first bytes arrive. `sse_event_stream`
    writes its opening keepalive before it awaits anything, so receiving
    those bytes is the proof that the generator is running past its
    terminal-replay check and the job's frames now have a reader.
    """
    from src.api.streaming import TERMINAL_EVENT_NAMES

    frames: list[tuple[str, dict[str, Any]]] = []
    buffer = ""
    attached = False
    async with client.stream("GET", stream_url, timeout=STREAM_TIMEOUT_SEC) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        async for text in response.aiter_text():
            if not attached:
                attached = True
                on_attached()
            buffer += text
            # Anything before the last blank-line separator is a whole
            # frame; whatever follows it may still be partial.
            complete, separator, buffer = buffer.rpartition("\n\n")
            if not separator:
                continue
            frames.extend(_parse_frames(complete + "\n\n"))
            if any(name in TERMINAL_EVENT_NAMES for name, _ in frames):
                break
    return frames


@pytest.fixture
async def live_server(
    install_settings: Callable[..., Any],
    research_llm_surface: Callable[..., None],
    e2e_fixtures: Callable[[str], dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, threading.Event]]:
    """The production app on a loopback port, with node one at a gate.

    No injected workflow factory and no injected store: whatever
    `create_app` wires by default is what gets driven, which is the only
    configuration that can catch the class of break ADR 0040 records —
    a shipped wiring that no test exercised because every test replaced
    it.
    """
    install_settings(
        enable_checkpointing=True,
        checkpoint_backend="sqlite",
        checkpoint_db_path=str(tmp_path / "e2e-http.sqlite"),
        # Shipped default, left on: the request opts out per job with
        # `hitl_bypass`, which is the path the eval runner and every
        # programmatic client take. `test_hitl_review.py` drives the
        # other side of this flag.
        enable_hitl=True,
        enable_api_auth=False,
    )
    research_llm_surface()

    gate = threading.Event()
    planner_response = e2e_fixtures("research_llm_responses")["planner"]

    def _gated_planner(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        # Runs on the graph's node executor, never on the event loop, so
        # blocking here holds the job open without stalling the server
        # that is serving the stream.
        assert gate.wait(GATE_TIMEOUT_SEC), "planner gate was never released"
        return dict(planner_response)

    monkeypatch.setattr("src.agents.planner.call_llm_json", _gated_planner)

    from src.api.app import create_app

    config = uvicorn.Config(
        create_app(),
        host=SERVER_HOST,
        port=0,  # the kernel picks a free one; no fixed port to collide on
        log_config=None,  # defer to the repository's JSON logger, as serve.py does
        lifespan="on",
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve(), name="e2e-uvicorn")
    try:
        deadline = asyncio.get_running_loop().time() + 20.0
        while not server.started:
            assert not serving.done(), "server exited during startup"
            assert asyncio.get_running_loop().time() < deadline, "server never started"
            await asyncio.sleep(0.01)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with AsyncClient(
            base_url=f"http://{SERVER_HOST}:{port}", timeout=TERMINAL_TIMEOUT_SEC
        ) as client:
            yield client, gate
    finally:
        # Release before shutting down: a job still parked at the gate
        # holds a node-executor thread, and uvicorn's graceful drain
        # would wait on it for nothing.
        gate.set()
        server.should_exit = True
        await serving


class TestHttpSurface:
    async def test_a_client_submits_streams_fetches_and_exports_one_job(
        self,
        live_server: tuple[AsyncClient, threading.Event],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """One job, four calls, and the frames a browser would have seen."""
        client, gate = live_server

        submit = await client.post(
            "/research",
            json={"query": "why do LLMs hallucinate?", "hitl_bypass": True},
        )
        assert submit.status_code == 202, submit.text
        accepted = submit.json()
        job_id = accepted["job_id"]
        # The client follows the URLs the API handed it rather than
        # rebuilding them, because those strings are the contract.
        assert accepted["status_url"] == f"/research/{job_id}"
        assert accepted["stream_url"] == f"/research/{job_id}/stream"

        frames = await _read_until_terminal(client, accepted["stream_url"], gate.set)
        names = [name for name, _ in frames]

        # The frame trajectory. `job_started` first, one node frame per
        # graph node in pipeline order, exactly one terminal frame, and
        # it is last — a second terminal frame, or a stream that stayed
        # open past one, is a client that never stops reconnecting.
        assert names[0] == "job_started"
        assert names[-1] == "job_completed"
        assert names.count("job_completed") == 1
        assert [
            data["node"] for name, data in frames if name == "node_completed"
        ] == list(PIPELINE_NODES)
        # No frame outside the documented registry reached the wire.
        assert set(names) <= {"job_started", "node_completed", "job_completed"}

        terminal = next(data for name, data in frames if name == "job_completed")
        assert terminal["job_id"] == job_id
        assert terminal["iterations"] == 1
        assert terminal["quality_score"] == pytest.approx(0.88)
        # The terminal frame carries the spend, so a client that only
        # ever watches the stream still learns what the run cost —
        # both numbers, for the reason `zero_spend_ledger` gives.
        assert usd(terminal["cost_usd"]) == "$0.0000"
        assert terminal["llm_calls"] == 0
        # Pinned as an exact key set because the *live* `job_completed`
        # frame and the one the route replays to a late client are built
        # by different code and do not agree: this one has
        # `quality_score` and `llm_calls`, the replay (second test) has
        # `status`, `error` and `error_type` instead. A client reading
        # `status` off a live frame gets a KeyError, which is why the
        # two are asserted separately rather than through one helper.
        assert set(terminal) == {
            "job_id",
            "iterations",
            "quality_score",
            "cost_usd",
            "llm_calls",
            "elapsed_sec",
        }

        detail = await client.get(accepted["status_url"])
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "succeeded"
        assert body["kind"] == "research"
        assert body["iterations"] == 1
        assert body["quality_score"] == pytest.approx(0.88)
        assert body["result"], "a succeeded job must carry its report"
        assert body["error"] is None and body["error_type"] is None

        # The job's own ledger, which is the one that saw the run: the
        # accumulator this test holds is bound to a different context.
        assert usd(body["cost_usd"]) == "$0.0000"
        assert body["llm_calls"] == 0

        export = await client.get(f"/research/{job_id}/export", params={"format": "md"})
        assert export.status_code == 200
        assert export.headers["content-type"].startswith("text/markdown")
        assert (
            export.headers["content-disposition"]
            == f'attachment; filename="research-{job_id}.md"'
        )
        assert export.headers["cache-control"] == "no-store"
        document = export.text
        assert body["result"] in document
        # The zero-spend claim as the user reads it, in the file they
        # downloaded — not as a float in a JSON body.
        assert "| Cost | $0.0000 |" in document

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_a_client_that_attaches_after_the_job_ends_still_learns_the_outcome(
        self,
        live_server: tuple[AsyncClient, threading.Event],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """A terminal job replays one frame and closes.

        This is what makes a reconnect idempotent, and it is the half of
        the streaming contract the happy path above cannot reach: there,
        the client is attached for the whole run. Here it arrives after
        the end, which is what a browser does when the tab was closed
        and reopened, and it must still be told the job succeeded rather
        than being held on an open connection that has nothing to say.
        """
        client, gate = live_server
        gate.set()  # no need to hold this job open; we want it finished

        submit = await client.post(
            "/research", json={"query": "late attach", "hitl_bypass": True}
        )
        assert submit.status_code == 202
        accepted = submit.json()

        deadline = asyncio.get_running_loop().time() + TERMINAL_TIMEOUT_SEC
        body: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            body = (await client.get(accepted["status_url"])).json()
            if body["status"] in ("succeeded", "failed", "cancelled"):
                break
            await asyncio.sleep(0.02)
        assert body.get("status") == "succeeded", body

        frames = await _read_until_terminal(
            client, accepted["stream_url"], lambda: None
        )
        assert [name for name, _ in frames] == ["job_completed"]
        replayed = frames[0][1]
        # The replay is the route's own snapshot, not the runner's live
        # frame, so it answers the question a reconnecting client is
        # actually asking — what happened — with a status and an error
        # slot rather than with per-run telemetry.
        assert replayed["job_id"] == accepted["job_id"]
        assert replayed["status"] == "succeeded"
        assert replayed["error"] is None and replayed["error_type"] is None
        assert usd(replayed["cost_usd"]) == "$0.0000"

        assert usd(body["cost_usd"]) == "$0.0000"
        assert body["llm_calls"] == 0
        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0
