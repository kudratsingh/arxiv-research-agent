"""The four exception handlers, end to end (ADR 0064).

Before this work order `create_app` registered no exception handlers at
all. The consequences were three separate findings and they are asserted
here as three separate properties:

1. An unhandled exception produced an untyped Starlette 500 with no
   structured body and no ERROR log on that path. Now it produces the
   envelope, the `internal_unexpected` code, an ERROR record — and
   crucially *not* the exception's own text, which in production is a
   psycopg DSN or an httpx URL.
2. Three inconsistent error shapes shipped. Now every one of them
   carries the same `error` object, while `detail` keeps its existing
   value so the current web client and the recorded contract fixtures
   in `web/contract/fixtures/` keep working. Those two halves are what
   most of this file is about: the envelope is *additive*, and a test
   that only checked the new half would let a silent client regression
   through.
3. `job.error` carried `f"{type(exc).__name__}: {exc}"`. The last class
   here simulates the psycopg failure that motivated the finding.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api import create_app
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.config import Settings, settings
from src.errors import ERROR_CODES

pytestmark = pytest.mark.integration


#: A stand-in for the class of exception that made this work order
#: necessary. `psycopg.OperationalError`'s message embeds the host, the
#: port and the user, and `redis`/`httpx` messages embed URLs; none of
#: it may reach a client, an SSE frame or a metric attribute.
class _SimulatedOperationalError(Exception):
    """Shaped like psycopg's, message and all."""


_DSN_TEXT = (
    'connection to server at "db.internal.example" (10.0.0.4), port 5432 '
    'failed: FATAL: password authentication failed for user "arxiv_app"'
)


class _ExplodingWorkflow:
    """A compiled-graph stand-in whose first node raises a driver error."""

    async def astream(
        self, state: dict[str, Any], config: dict[str, Any] | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        raise _SimulatedOperationalError(_DSN_TEXT)
        yield {}  # pragma: no cover - unreachable, keeps this a generator


def _app_with_a_raising_route() -> FastAPI:
    """The real app, plus one route that fails the way production does.

    Added after `create_app` rather than inside `src/` so the failure
    path under test is the *handler*, not a route written to be handled.
    """
    app = create_app()

    async def boom() -> None:
        raise _SimulatedOperationalError(_DSN_TEXT)

    app.router.add_api_route("/_test_boom", boom, methods=["GET"])
    return app


def _client(app: FastAPI, *, raise_app_exceptions: bool = False) -> AsyncClient:
    return AsyncClient(
        # Starlette's `ServerErrorMiddleware` always re-raises after the
        # `Exception` handler has produced its response, so the response
        # is only observable when the transport is told not to re-raise.
        # That is a property of the test harness, not of the server: a
        # real uvicorn worker sends the body and logs the traceback.
        transport=ASGITransport(app=app, raise_app_exceptions=raise_app_exceptions),
        base_url="http://test",
    )


class TestTheUnhandledPath:
    """The handler whose absence was the finding."""

    async def test_an_unhandled_exception_answers_with_the_envelope(self) -> None:
        app = _app_with_a_raising_route()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.get("/_test_boom")

        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "internal_unexpected"
        assert body["error"]["code"] in ERROR_CODES
        assert body["error"]["retryable"] is False
        assert body["detail"] == "internal_unexpected"

    async def test_no_part_of_the_driver_message_reaches_the_client(self) -> None:
        """The whole point. Asserted on the raw bytes, not on one field.

        Checking `body["error"]["message"]` alone would pass while the
        text sat in `detail`, or in a header, so this looks at
        everything the client can see.
        """
        app = _app_with_a_raising_route()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.get("/_test_boom")

        visible = resp.text + repr(dict(resp.headers))
        for fragment in (
            "db.internal.example",
            "10.0.0.4",
            "5432",
            "arxiv_app",
            "password authentication",
            "_SimulatedOperationalError",
        ):
            assert fragment not in visible, fragment

    async def test_it_logs_at_error_with_the_traceback_and_the_detail(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = _app_with_a_raising_route()
        with caplog.at_level(logging.WARNING, logger="src.api.app"):
            async with LifespanManager(app), _client(app) as client:
                    await client.get("/_test_boom")

        records = [r for r in caplog.records if r.message == "api_request_failed"]
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.exc_info is not None
        # The text the client did not get is here instead, which is the
        # other half of the contract: nothing is lost, it moves.
        assert _DSN_TEXT in getattr(record, "error", "")
        assert getattr(record, "error_type", None) == "internal_unexpected"

    async def test_the_request_id_ties_the_body_to_the_log_line(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Without this the envelope's `request_id` is decoration.

        There is no request-id middleware yet (WO-A10 adds it), so the
        id is minted in the handler — but it still has to be the *same*
        id in the header, the body and the log record, or an operator
        cannot get from a user's screenshot to the traceback.
        """
        app = _app_with_a_raising_route()
        with caplog.at_level(logging.WARNING, logger="src.api.app"):
            async with LifespanManager(app), _client(app) as client:
                    resp = await client.get("/_test_boom")

        record = next(r for r in caplog.records if r.message == "api_request_failed")
        assert resp.json()["error"]["request_id"] == resp.headers["X-Request-Id"]
        assert getattr(record, "request_id", None) == resp.headers["X-Request-Id"]


class TestTheTypedPaths:
    """`AppError`, and the legacy `detail` values that must not move."""

    async def test_a_404_keeps_its_detail_and_gains_the_envelope(self) -> None:
        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.get("/research/does-not-exist")

        assert resp.status_code == 404
        body = resp.json()
        # `web/contract/fixtures/error.404.json` records exactly this.
        assert body["detail"] == "job_not_found"
        assert body["error"] == {
            "code": "job_not_found",
            "message": "That job is not available.",
            "retryable": False,
            "request_id": resp.headers["X-Request-Id"],
        }

    async def test_a_state_conflict_keeps_the_status_the_client_parses(self) -> None:
        """`web/lib/api/errors.ts` regexes `(status=...)` out of `detail`.

        Dropping the suffix would not fail anything on the Python side
        and would quietly downgrade the review surface's sentence to
        generic copy, so it is pinned here — on both halves.
        """
        app = create_app()
        job = Job(job_id="conflicted", query="q", status=JobStatus.running)
        async with LifespanManager(app):
            await app.state.store.create(job)
            async with _client(app) as client:
                resp = await client.post(
                    "/research/conflicted/review", json={"action": "approve"}
                )

        assert resp.status_code == 409
        body = resp.json()
        assert body["detail"] == "job_not_awaiting_review (status=running)"
        assert body["error"]["code"] == "job_not_awaiting_review"
        # The same fact, said in words, for a client that reads the
        # envelope instead of regexing the legacy string.
        assert "still running" in body["error"]["message"]

    async def test_a_validation_error_keeps_fastapis_field_array(self) -> None:
        """The 422 array is what renders per-field messages in the plan editor."""
        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.post("/research", json={"query": ""})

        assert resp.status_code == 422
        body = resp.json()
        assert isinstance(body["detail"], list)
        assert body["detail"][0]["loc"][0] == "body"
        assert body["error"]["code"] == "invalid_request"
        assert body["error"]["code"] in ERROR_CODES

    async def test_a_rate_limit_keeps_its_object_detail_and_retry_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The 429 is the other shape the client reads structurally."""
        import src.api.app as app_module
        import src.api.auth as auth_module
        import src.api.routes as routes_module

        limited = Settings(
            enable_api_auth=True,
            api_keys="internal:sk_test",
            api_key_hourly_limit=1,
        )
        monkeypatch.setattr(app_module, "settings", limited)
        monkeypatch.setattr(auth_module, "settings", limited)
        monkeypatch.setattr(routes_module, "settings", limited)

        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                headers = {"X-API-Key": "sk_test"}
                first = await client.post(
                    "/research", json={"query": "q", "hitl_bypass": True}, headers=headers
                )
                assert first.status_code == 202
                resp = await client.post(
                    "/research", json={"query": "q", "hitl_bypass": True}, headers=headers
                )

        assert resp.status_code == 429
        body = resp.json()
        assert body["detail"] == {
            "error": "rate_limited",
            "key_id": "internal",
            "limit_per_hour": 1,
        }
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["retryable"] is True
        assert int(resp.headers["Retry-After"]) >= 1

    async def test_a_401_keeps_its_www_authenticate_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A header carried by an `AppError` survives the handler."""
        import src.api.app as app_module
        import src.api.auth as auth_module

        authed = Settings(enable_api_auth=True, api_keys="internal:sk_test")
        monkeypatch.setattr(app_module, "settings", authed)
        monkeypatch.setattr(auth_module, "settings", authed)

        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.post("/research", json={"query": "q"})

        assert resp.status_code == 401
        assert resp.headers["WWW-Authenticate"].startswith("ApiKey")
        assert resp.json()["detail"] == "missing_api_key"
        assert resp.json()["error"]["code"] == "missing_api_key"


class TestTheHttpExceptionPath:
    """Code this taxonomy has not reached yet still gets an envelope.

    `src/api/learn.py` belongs to another work order and still raises
    `HTTPException`. That is the case the third handler exists for, and
    it is the reason the handler maps a `detail` string back to a code
    instead of assuming every failure came from `src/errors.py`.
    """

    async def test_a_raw_http_exception_still_carries_a_code(self) -> None:
        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.get("/learn/paths")

        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"] == "learn_content_disabled"
        assert body["error"]["code"] == "learn_content_disabled"
        assert body["error"]["code"] in ERROR_CODES

    async def test_a_status_with_no_matching_code_falls_back_to_its_family(
        self,
    ) -> None:
        """A 405 from the router names nothing in `ERROR_CODES`.

        It still must not answer with a bare number, or a client has
        nothing to branch on for exactly the failures nobody
        anticipated.
        """
        app = create_app()
        async with LifespanManager(app), _client(app) as client:
                resp = await client.post("/healthz")

        assert resp.status_code == 405
        assert resp.json()["error"]["code"] in ERROR_CODES


class TestTheJobRecord:
    """`job.error` for the failure that motivated the finding."""

    async def test_a_driver_failure_leaves_no_joined_exception_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.api.runner as runner_module

        monkeypatch.setattr(runner_module, "settings", Settings())
        job = Job(job_id="db-down", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(job, _ExplodingWorkflow(), store, asyncio.Semaphore(1))

        assert job.status is JobStatus.failed
        # The old value was `"_SimulatedOperationalError: connection to
        # server at ..."`. Both halves of that are gone.
        assert job.error == "internal_unexpected"
        assert job.error_type == "internal_unexpected"
        assert job.error_type in ERROR_CODES
        assert ":" not in (job.error or "")
        for fragment in ("db.internal.example", "10.0.0.4", "arxiv_app"):
            assert fragment not in (job.error or "")

    async def test_the_terminal_sse_frame_carries_the_code_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The frame is the other door the leak went through.

        `routes.py`'s terminal replay and the runner's own frame both
        publish `job.error`, so a fix that only cleaned the REST body
        would still hand the DSN to every connected SSE client.
        """
        import src.api.runner as runner_module

        monkeypatch.setattr(runner_module, "settings", Settings())
        job = Job(job_id="db-down-sse", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(job, _ExplodingWorkflow(), store, asyncio.Semaphore(1))

        frames: list[dict[str, Any]] = []
        while not job.event_queue.empty():
            frames.append(job.event_queue.get_nowait())
        terminal = frames[-1]
        assert terminal["event"] == "job_failed"
        assert terminal["data"]["error"] == "internal_unexpected"
        assert _DSN_TEXT not in str(terminal)


def test_the_settings_module_is_untouched_by_this_file() -> None:
    """Guard for the monkeypatching above, which rebinds `settings`.

    Several tests here swap the module-level `settings` in three
    modules. A leak would silently turn auth on for every test that ran
    afterwards, which is the kind of failure that shows up two files
    later and gets blamed on the wrong change.
    """
    assert settings.enable_api_auth is False
