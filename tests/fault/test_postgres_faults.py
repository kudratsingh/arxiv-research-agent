"""The Postgres pool is exhausted, or a connection drops mid-query
(WO-A06 scenario 2).

Nothing in `src/` wraps a psycopg failure in an `AppError`. There is no
`upstream_postgres` code the way there is an `upstream_arxiv`, so what
a Postgres fault becomes depends entirely on *who was asking*, and the
three answers are genuinely different:

| caller | code | event | metric |
|---|---|---|---|
| an optional cache | *(none — the run continues)* | `embedding_cache_get_failed` | `research_jobs_total{status="succeeded", error_type="none"}` |
| the conversation append, after a success | *(none — the job already succeeded)* | `conversation_append_failed` | same |
| a graph node | `internal_unexpected` | `api_job_failed` | `research_jobs_total{status="failed", error_type="internal_unexpected"}` |

That third row is the gap, and it is the same one the model provider
has: the most informative thing the system knows about the failure —
that it was the database — is thrown away at the runner boundary and
reaches `research_jobs_total{error_type}` as `internal_unexpected`,
where it is indistinguishable from a null dereference. Reported rather
than patched: `src/errors.py` belongs to WO-A01.

**The exceptions are the library's own.** `psycopg_pool.PoolTimeout`
and `psycopg.OperationalError` are what the handlers under test branch
on, so raising anything else — a bare `TimeoutError`, say — would test
the double instead of the branch. `TestARealPoolIsExhausted` closes the
loop by making a live server produce one, and is skipped where no
Postgres binary is installed, exactly as the other Postgres modules in
this suite are.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Any

import numpy as np
import psycopg
import pytest
from psycopg_pool import ConnectionPool, PoolTimeout

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.errors import AppError

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.integration, pytest.mark.fault]

#: Shaped like a real libpq failure, which is the point: the message
#: names the host, the address, the port and the role. Every fragment
#: is checked for absence from the job record and the terminal frame.
DSN_TEXT = (
    'connection to server at "db.internal.example" (10.0.0.4), port 5432 '
    'failed: FATAL: password authentication failed for user "arxiv_app"'
)

POOL_TEXT = "couldn't get a connection after 30.00 sec"

REPORT = "# Findings\n\nA report produced despite a sick database."


#: pytest-postgresql spawns a real Postgres process. Skipped entirely
#: where the machine has no `postgres` server binary (a libpq-only
#: Homebrew install, say); CI runs on ubuntu-latest with the full
#: server on PATH. Same guard, verbatim, as `tests/test_paper_cache.py`
#: and `tests/test_api_conversations.py`.
_postgres_available = shutil.which("postgres") is not None

if _postgres_available:
    from pytest_postgresql import factories

    postgresql_proc = factories.postgresql_proc(port=None, unixsocketdir="/tmp")
    postgresql_db = factories.postgresql("postgresql_proc")


async def _run(job_id: str, workflow: Any) -> tuple[Job, InMemoryJobStore]:
    job = Job(job_id=job_id, query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job, store


class _ExhaustedEmbeddingCache:
    """Every read and write waits out the pool's timeout and gives up.

    `PoolTimeout` rather than a generic error because that is what an
    exhausted `ConnectionPool` actually raises, and because the guard
    under test catches broadly — a test that raised the guard's own
    exception type would pass against a guard that had been narrowed to
    something else entirely.
    """

    def get_many(self, hashes: list[str], model_name: str) -> dict[str, Any]:
        raise PoolTimeout(POOL_TEXT)

    def put_many(self, entries: Any, model_name: str) -> None:
        raise PoolTimeout(POOL_TEXT)


class _DisconnectedConversationStore:
    """A conversation store whose connection went away mid-query."""

    async def append_job(self, **_kwargs: Any) -> Any:
        raise psycopg.OperationalError(DSN_TEXT)


class TestAnOptionalCacheLosesItsPool:
    async def test_the_run_degrades_to_recompute_and_still_succeeds(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A cache is an optimization; it must never be a job-killer.

        ADR 0028 promised "degrades to recompute, only shows up in the
        logs" and for a while only the write path honoured it. Asserted
        here from inside a real job so the third leg is real: the run
        reaches `succeeded` and is counted as such, which is the claim
        a degradation guard is actually making.
        """
        import src.tools.embedding_cache as cache_module
        import src.tools.embeddings as embeddings_module

        monkeypatch.setattr(
            cache_module, "get_embedding_cache", lambda: _ExhaustedEmbeddingCache()
        )
        recomputed = np.ones((2, 4), dtype=np.float32)
        monkeypatch.setattr(
            embeddings_module, "_encode_uncached", lambda texts: recomputed[: len(texts)]
        )
        encoded: list[Any] = []

        def _node_that_embeds() -> None:
            encoded.append(embeddings_module.encode_texts(["alpha", "beta"]))

        job, _ = await _run(
            "cache-degraded",
            scripted_workflow(
                updates=[{"synthesizer": {"draft_report": REPORT}}],
                on_stream=_node_that_embeds,
            ),
        )

        assert job.status == JobStatus.succeeded
        assert job.result == REPORT
        assert len(encoded) == 1 and encoded[0].shape == (2, 4)

        record = triple.assert_triple(
            code=None,
            event="embedding_cache_get_failed",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
        assert record.levelno == logging.WARNING
        assert POOL_TEXT in getattr(record, "error", "")

        # The fourth assertion, and the one the triple above cannot
        # make. `research_jobs_total{succeeded}` is the *right* answer —
        # the job did succeed — and that is exactly why it could not
        # tell this run apart from one where the cache was healthy. A
        # fleet recomputing every embedding looked identical to a fleet
        # that was fine. `research_degradations_total` is the leg that
        # sees it (ADR 0081, docs/reliability.md §5 rung 1).
        degradation = triple.point(
            "research_degradations_total",
            rung="cache_stale",
            component="embedding_cache",
        )
        assert degradation.value == 1
        # And the cache the fault did *not* touch stays at zero, so the
        # `component` attribute is proven to discriminate rather than
        # merely to be present.
        assert not [
            point
            for point in triple.points("research_degradations_total")
            if dict(point.attributes).get("component") == "paper_cache"
        ]


class TestTheConversationAppendLosesItsConnection:
    async def test_a_finished_job_stays_finished_and_the_gap_is_an_error(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """The report is already paid for; the follow-up link is not.

        A silent miss here means every follow-up query in that
        conversation quietly loses its prior context, with no symptom
        at all until someone notices the answers got worse. So the job
        stays `succeeded` — which is honest, the research did happen —
        and the gap is an ERROR rather than a downgrade of the outcome.
        """
        job = Job(
            job_id="conversation-orphaned",
            query="q",
            hitl_bypass=True,
            conversation_id="conv-1",
        )
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(
            job,
            scripted_workflow(updates=[{"synthesizer": {"draft_report": REPORT}}]),
            store,
            asyncio.Semaphore(1),
            conversation_store=_DisconnectedConversationStore(),
        )

        assert job.status == JobStatus.succeeded
        assert job.result == REPORT

        record = triple.assert_triple(
            code=None,
            event="conversation_append_failed",
            instrument="research_jobs_total",
            attributes={"status": "succeeded", "error_type": "none"},
        )
        assert record.levelno == logging.ERROR
        assert getattr(record, "conversation_id", None) == "conv-1"


class TestAConnectionDropsInsideANode:
    async def test_the_job_fails_with_a_code_and_the_dsn_stays_inside(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        frames: Any,
    ) -> None:
        """The finding that started ADR 0064, on the exception that motivated it.

        `job.error` used to be `f"{type(exc).__name__}: {exc}"`, which
        put this DSN into an API response body, into the terminal SSE
        frame, and into a metric attribute of unbounded cardinality.
        All three surfaces are checked here, and the traceback that
        still holds the text is checked to be in the log where it
        belongs.
        """
        job, store = await _run(
            "db-dropped",
            scripted_workflow(raises=psycopg.OperationalError(DSN_TEXT)),
        )

        assert job.status == JobStatus.failed
        assert job.error_type == AppError.code
        assert job.error == AppError.code

        record = triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": AppError.code},
        )
        assert record.levelno == logging.ERROR
        # The text is not lost, it moves — to the one place it belongs.
        assert DSN_TEXT in getattr(record, "error", "")

        terminal = frames(job)[-1]
        assert terminal["event"] == "job_failed"
        visible = repr(terminal) + repr(await store.get("db-dropped"))
        for fragment in ("db.internal.example", "10.0.0.4", "arxiv_app", "5432"):
            assert fragment not in visible, fragment


@pytest.mark.skipif(
    not _postgres_available,
    reason="postgres server binary not found; install `postgresql` locally to run",
)
class TestARealPoolIsExhausted:
    """Close the loop: make a live server produce the real exception.

    Every other test in this file raises `PoolTimeout` itself, which is
    only as good as the claim that a real exhausted pool raises that
    and not something else. This class is that claim, checked — and it
    then feeds the exception it caught through the same runner boundary
    so the triple is asserted on an exception no test wrote.
    """

    @staticmethod
    def _url(connection: psycopg.Connection) -> str:
        info = connection.info
        return f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"

    async def test_a_second_borrower_of_a_one_connection_pool_times_out(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        postgresql_db: psycopg.Connection,
    ) -> None:
        pool = ConnectionPool(
            self._url(postgresql_db),
            min_size=1,
            max_size=1,
            # Short: the wait is the whole mechanism, and every second
            # of it is a second of this suite's wall clock.
            timeout=0.2,
            open=True,
        )

        def _borrow_a_second_connection() -> None:
            """Ask for a connection the pool does not have to give."""
            with pool.connection():  # pragma: no cover - never entered
                pass

        try:
            # The pool's only connection is held right here, so the
            # borrow below can do nothing but wait out `timeout` — real
            # exhaustion against a real server, not a simulated one.
            with pool.connection(), pytest.raises(PoolTimeout) as raised:
                _borrow_a_second_connection()
        finally:
            pool.close()

        real_timeout = raised.value
        # The claim the rest of this file rests on.
        assert isinstance(real_timeout, PoolTimeout)

        job, _ = await _run(
            "real-pool-timeout", scripted_workflow(raises=real_timeout)
        )

        assert job.status == JobStatus.failed
        assert job.error_type == AppError.code
        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": AppError.code},
        )
