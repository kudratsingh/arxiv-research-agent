"""Redis goes away — at submit, mid-job, and during SSE fan-out
(WO-A06 scenario 1).

`RedisJobStore` catches `WatchError` and nothing else: every one of its
methods propagates a `ConnectionError` to its caller by design, because
the runner's `_persist_terminal` owns the retry-and-absorb policy and
swallowing lower down would hide a downed Redis from it. That design
only pays off if each caller up the chain does something honest with
what it gets, and this file asserts what each of them does.

Three moments, three different right answers:

| moment | code | event | metric |
|---|---|---|---|
| at submit | `internal_unexpected`, HTTP 500 | `api_request_failed` | `research_jobs_total` **does not move** |
| over-cap rejection | `rate_limited`, HTTP 429 | `api_request_rejected` | `rate_limit_rejections_total{backend="redis"}` |
| mid-job terminal write | the job's own outcome code | `api_job_terminal_persist_retry` ×3 → `api_job_terminal_persist_failed` | `research_jobs_total{status, error_type}` |
| SSE fan-out | the job's own outcome code | `sse_terminal_publish_failed` → `sse_terminal_publish_gave_up` | `research_jobs_total{status, error_type}` |

The submit row is the one worth reading twice. A Redis outage at
submit is **invisible to every job metric**, because the request never
became a job — the only signal is the ERROR log. That is not a bug in
this test; it is the RED-metrics gap WO-A07 is filling, and writing it
down here is what stops it from being rediscovered.

The rate limiter's *outage* behaviour is deliberately not pinned here;
see `test_resilience_faults.py` and WO-A04.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import fakeredis.aioredis
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis import exceptions as redis_exceptions

from src.api.app import create_app
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.redis_store import RedisJobStore
from src.api.runner import _TERMINAL_PERSIST_ATTEMPTS, run_job
from src.config import Settings
from src.errors import AppError, RateLimitedError

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.integration, pytest.mark.fault]

#: A message shaped like the ones a real client raises. Every fragment
#: of it is checked for absence from the response body, because the
#: whole point of ADR 0064's boundary is that a driver message names
#: the host, the port and sometimes the password.
OUTAGE_TEXT = "Error 111 connecting to redis://:s3cr3t@cache.internal:6379. Connection refused."

REPORT = "# Findings\n\nA report the store will not accept."


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        # Starlette's `ServerErrorMiddleware` re-raises after the bare
        # `Exception` handler has produced its response, so the 500 body
        # is only observable when the transport is told not to re-raise.
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    )


class _StoreWithNoRedis(InMemoryJobStore):
    """A store whose every write hits a refused connection."""

    async def create(self, job: Job) -> None:
        raise redis_exceptions.ConnectionError(OUTAGE_TEXT)


class _TerminalWriteRefusingStore(InMemoryJobStore):
    """Redis goes away partway through the run.

    Only the *terminal* write is refused. Breaking every write would
    fail the job on its first `running` transition, which is a
    different fault with a different right answer — and it would hide
    the one under test, because a job that never reached a terminal
    state cannot demonstrate that the terminal state was counted
    anyway.
    """

    def __init__(self) -> None:
        super().__init__()
        self.refused = 0

    async def update(self, job: Job) -> None:
        if not job.is_terminal():
            await super().update(job)
            return
        self.refused += 1
        raise redis_exceptions.ConnectionError(OUTAGE_TEXT)


class TestRedisIsDownAtSubmit:
    async def test_the_client_gets_a_code_and_none_of_the_drivers_message(
        self, triple: TripleObserver, scripted_workflow: type[ScriptedWorkflow]
    ) -> None:
        app = create_app(
            build_workflow=lambda: scripted_workflow(), store=_StoreWithNoRedis()
        )

        async with LifespanManager(app), _client(app) as http:
            resp = await http.post(
                "/research", json={"query": "q", "hitl_bypass": True}
            )

        assert resp.status_code == 500
        body = resp.json()
        # Leg 1 — the code, read off the surface the client actually sees.
        assert body["error"]["code"] == AppError.code
        assert body["detail"] == AppError.code

        # Asserted over the whole visible response rather than one
        # field, so the text cannot survive in `detail` or a header.
        visible = resp.text + repr(dict(resp.headers))
        for fragment in ("cache.internal", "s3cr3t", "6379", "Connection refused"):
            assert fragment not in visible, fragment

        # Leg 2 — the event. It is an ERROR with the traceback, and the
        # driver text lives here, which is the other half of the deal:
        # nothing is lost, it moves.
        record = triple.one_record("api_request_failed")
        assert record.levelno == logging.ERROR
        assert getattr(record, "error_type", None) == AppError.code
        assert OUTAGE_TEXT in getattr(record, "error", "")

        # Leg 3 — the metric, and the honest answer is that it did not
        # move. A submit that never became a job cannot appear in a job
        # counter, so during a Redis outage the fleet looks *idle*
        # rather than failing. WO-A07's RED metrics are what close this.
        triple.assert_not_recorded("research_jobs_total")

    async def test_the_request_id_ties_the_body_to_the_log_line(
        self, triple: TripleObserver, scripted_workflow: type[ScriptedWorkflow]
    ) -> None:
        """Without this, an outage leaves an operator with two piles.

        The client has a 500 with an opaque code; the log has a
        traceback. The request id is the only thing that joins them,
        and it has to be the same value in the header, the body and the
        record.
        """
        app = create_app(
            build_workflow=lambda: scripted_workflow(), store=_StoreWithNoRedis()
        )

        async with LifespanManager(app), _client(app) as http:
            resp = await http.post(
                "/research", json={"query": "q", "hitl_bypass": True}
            )

        request_id = resp.headers["X-Request-Id"]
        assert resp.json()["error"]["request_id"] == request_id
        assert getattr(triple.one_record("api_request_failed"), "request_id", None) == request_id


class TestTheRedisRateLimiterRejectsOverCap:
    """The limiter is the one Redis caller with a metric of its own.

    Only the *over-cap* half is asserted here. The limiter's behaviour
    when Redis is unreachable — today an unguarded `pipe.execute()` and
    therefore a 500 — is WO-A04's deliverable 6, which changes it to
    degrade to the in-memory backend and increment a degradation
    counter. Pinning today's 500 would hand that work order a red test
    for behaviour it is deliberately replacing, so the outage half
    lives in `test_resilience_faults.py` as a skip that names it.
    """

    @staticmethod
    def _limited_app(
        monkeypatch: pytest.MonkeyPatch,
        store: RedisJobStore,
        workflow: type[ScriptedWorkflow],
    ) -> FastAPI:
        import src.api.app as app_module
        import src.api.auth as auth_module
        import src.api.routes as routes_module

        limited = Settings(
            enable_api_auth=True,
            api_keys="internal:sk_test",
            api_key_hourly_limit=1,
            rate_limit_backend="redis",
        )
        for module in (app_module, auth_module, routes_module):
            monkeypatch.setattr(module, "settings", limited)
        # `create_app` reuses the store's `_client` for the limiter
        # rather than opening a second pool, so injecting one store
        # arms both subsystems against the same fake Redis.
        return create_app(build_workflow=lambda: workflow(), store=store)

    async def test_a_genuine_rejection_records_the_code_the_event_and_the_metric(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        redis_client = fakeredis.aioredis.FakeRedis()
        app = self._limited_app(
            monkeypatch, RedisJobStore(redis_client), scripted_workflow
        )
        headers = {"X-API-Key": "sk_test"}

        try:
            async with LifespanManager(app), _client(app) as http:
                first = await http.post(
                    "/research", json={"query": "q", "hitl_bypass": True}, headers=headers
                )
                assert first.status_code == 202
                resp = await http.post(
                    "/research", json={"query": "q", "hitl_bypass": True}, headers=headers
                )
        finally:
            await redis_client.aclose()

        assert resp.status_code == 429
        record = triple.assert_triple(
            code=resp.json()["error"]["code"],
            event="api_request_rejected",
            instrument="rate_limit_rejections_total",
            attributes={"backend": "redis"},
        )
        assert resp.json()["error"]["code"] == RateLimitedError.code
        # A 4xx is a client problem worth seeing, not an incident.
        assert record.levelno == logging.WARNING


class TestRedisIsDownMidJob:
    async def test_the_outcome_is_still_counted_and_still_recoverable(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        no_backoff: None,
    ) -> None:
        """A store that will not take the last write must not also make
        the fleet look idle.

        `record_job_terminal` fires before the write and outside the
        retry loop precisely so this holds: the job reached its terminal
        state whether or not the store accepted the row. And because
        the row is gone, the ERROR line carries the whole report — the
        only remaining copy.
        """
        store = _TerminalWriteRefusingStore()
        job = Job(job_id="unwritable", query="q", hitl_bypass=True)
        await store.create(job)

        await run_job(
            job,
            scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}]),
            store,
            asyncio.Semaphore(1),
        )

        assert job.status == JobStatus.succeeded
        assert store.refused == _TERMINAL_PERSIST_ATTEMPTS

        record = triple.assert_triple(
            code=None,
            event="api_job_terminal_persist_failed",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
        assert record.levelno == logging.ERROR
        assert getattr(record, "result", None) == REPORT

        retries = triple.records("api_job_terminal_persist_retry")
        assert len(retries) == _TERMINAL_PERSIST_ATTEMPTS
        assert [getattr(r, "attempt", None) for r in retries] == [1, 2, 3]


class TestRedisIsDownDuringSseFanOut:
    async def test_the_real_store_propagates_and_the_runner_escalates(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        no_backoff: None,
    ) -> None:
        """Driven through the real `RedisJobStore`, not a hand-written double.

        Two things only this arrangement can show. First, that
        `publish_event` really does let a `ConnectionError` out — the
        store catches `WatchError` and nothing else, and a stray
        `except Exception` added there would turn the runner's
        escalation into silence with no other test noticing. Second,
        that the row still lands: the write path and the fan-out path
        are separate Redis calls, and only the latter is broken here.
        """
        redis_client = fakeredis.aioredis.FakeRedis()
        store = RedisJobStore(redis_client)

        def _refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise redis_exceptions.ConnectionError(OUTAGE_TEXT)

        job = Job(job_id="unpublishable", query="q", hitl_bypass=True)
        await store.create(job)
        monkeypatch_target = redis_client.publish
        assert callable(monkeypatch_target)
        redis_client.publish = _refuse  # type: ignore[method-assign]

        try:
            await run_job(
                job,
                scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}]),
                store,
                asyncio.Semaphore(1),
            )
            redis_client.publish = monkeypatch_target  # type: ignore[method-assign]
            stored = await store.get("unpublishable")
        finally:
            await redis_client.aclose()

        assert stored is not None
        assert stored.status == JobStatus.succeeded
        assert stored.result == REPORT

        triple.assert_triple(
            code=None,
            event="sse_terminal_publish_gave_up",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
