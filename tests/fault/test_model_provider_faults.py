"""The model provider answers 429, 500, or nothing at all
(WO-A06 scenario 3).

Every fault here is driven end to end — a graph node calls `call_llm`,
the SDK raises, and the exception travels out of the stream into
`run_job` — because that is the only arrangement in which all three
legs are real at once. A test that called `call_llm` directly would see
the LLM metric and the LLM log line but never the code, and the code is
the leg that turns out to be wrong.

| fault | code | events | metrics |
|---|---|---|---|
| HTTP 429 | `upstream_model` | `llm_upstream_error`, `api_job_failed` | `llm_upstream_errors_total{status="429"}`, `research_jobs_total` |
| HTTP 500 | `upstream_model` | same | `…{status="500"}` |
| timeout | `upstream_model` | same | `…{status="connection"}` |
| every paper died on the provider | `upstream_model` | `api_job_failed` | `research_jobs_total{error_type="upstream_model"}` |
| papers found, none readable | `upstream_paper_read` | `api_job_failed` | `research_jobs_total{error_type="upstream_paper_read"}` |

**The gap this file found, and WO-A17 closed.** WO-A06 was written
expecting a job to terminate with `upstream_model` after the retry
envelope is spent. No such code existed: WO-A01 shipped
`upstream_arxiv`, `upstream_paper_read` and `upstream_model_output`, and
nothing in `src/llm.py` converted an SDK error into any of them. A
model-provider outage — the single most likely upstream failure this
system has — reached `research_jobs_total{error_type}` as
`internal_unexpected`, indistinguishable from a null dereference,
*unless* it passed through the reader's fan-out, which converted it to
`upstream_paper_read` on the way out. The same outage carried a
different code depending on which node happened to be running, and that
inconsistency was the part that mattered: neither name is one an
on-call engineer can act on if the other is equally likely.

`src/llm.py` now raises `errors.UpstreamModel` from both SDK failure
branches, and the reader raises the same class when *every* paper died
on the provider — keeping `upstream_paper_read` for the case it was
named for. The tests below are the ones that found the gap, rewritten
to pin the fix rather than the symptom.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from src import llm as llm_module
from src.agents.reader import AllPaperAnalysesFailedError
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.errors import JOB_ERROR_TYPES, UpstreamModel, UpstreamPaperRead

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]

MODEL = "claude-sonnet-4-6"


def _status_error(status_code: int) -> Exception:
    """A real `anthropic.APIStatusError` for `status_code`.

    Built from a real `httpx.Response` rather than a stand-in, because
    `call_llm` reads `exc.status_code` and `exc.request_id` off the
    SDK's own parsing of it — a hand-rolled double would let those two
    reads rot without anything failing.
    """
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"request-id": f"req_{status_code}"},
        json={"error": {"type": "overloaded_error"}},
    )
    return llm_module.anthropic.APIStatusError("upstream", response=response, body=None)


def _timeout_error() -> Exception:
    """A real `anthropic.APITimeoutError`.

    A subclass of `APIConnectionError`, which is why it carries no HTTP
    status and is reported under `connection` — the distinction between
    "our timeout is too tight" and "the network is broken" lives in the
    `detail` field, not in the status.
    """
    return llm_module.anthropic.APITimeoutError(
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


class _FailingSdkClient:
    """The Anthropic SDK after it has exhausted its own retries.

    Mirrors the surface `call_llm` reaches for — `messages
    .with_raw_response.create` — and counts calls, which is how the
    "no second retry loop" property below is checked.
    """

    def __init__(self, raises: Exception) -> None:
        self.calls = 0
        self._raises = raises
        self.messages = SimpleNamespace(with_raw_response=self)

    def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise self._raises


class _RetryingSdkClient:
    """A client that succeeds, having quietly burned `retries_taken` attempts."""

    def __init__(self, retries_taken: int) -> None:
        self.messages = SimpleNamespace(with_raw_response=self)
        self._retries_taken = retries_taken

    def create(self, **_kwargs: Any) -> Any:
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        parsed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="ok")], usage=usage
        )
        return SimpleNamespace(retries_taken=self._retries_taken, parse=lambda: parsed)


async def _run_job_whose_node_calls_the_model(
    job_id: str, workflow_factory: type[ScriptedWorkflow]
) -> Job:
    """Run a job whose only node makes one model call."""
    job = Job(job_id=job_id, query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    workflow = workflow_factory(on_stream=lambda: llm_module.call_llm("prompt", model_name=MODEL))
    await run_job(job, workflow, store, asyncio.Semaphore(1))
    return job


class TestTheProviderRefusesTheCall:
    @pytest.mark.parametrize(
        ("build_error", "status"),
        [
            (lambda: _status_error(429), "429"),
            (lambda: _status_error(500), "500"),
            (_timeout_error, "connection"),
        ],
        ids=["rate_limited", "server_error", "timeout"],
    )
    async def test_the_failure_is_counted_logged_and_lands_on_the_job(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        monkeypatch: pytest.MonkeyPatch,
        build_error: Any,
        status: str,
    ) -> None:
        """One outage, four observations, and they have to agree.

        The status attribute is the whole value of the LLM metric: 429
        and 500 mean different things to an on-call engineer (throttled
        versus broken) and a counter that collapsed them would answer
        neither question.

        The code is `upstream_model` and not `internal_unexpected`,
        which is the half this test found and WO-A17 fixed. The old
        answer was the code reserved for "an exception nobody typed is
        one nobody predicted" — so the most predictable failure in the
        system shared a metric series with genuine bugs, and an alert on
        that series could not tell a provider incident from a
        deployment regression.
        """
        client = _FailingSdkClient(build_error())
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        job = await _run_job_whose_node_calls_the_model("upstream", scripted_workflow)

        assert job.status == JobStatus.failed
        assert job.error_type == UpstreamModel.code
        # It is a code a *run* can end as, so the frontend's copy
        # dictionary owes it a sentence.
        assert job.error_type in JOB_ERROR_TYPES
        # The job record carries a code, never the SDK's message.
        assert job.error == job.error_type

        upstream = triple.assert_triple(
            code=job.error_type,
            event="llm_upstream_error",
            instrument="llm_upstream_errors_total",
            attributes={"model": MODEL, "status": status},
        )
        assert getattr(upstream, "status", None) == status
        assert getattr(upstream, "elapsed_ms", 0.0) >= 0.0

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": UpstreamModel.code},
        )

    async def test_the_sdk_owns_the_retry_envelope_and_nothing_wraps_it(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exactly one request leaves this process per `call_llm`.

        By the time an `APIStatusError` escapes, the SDK has already
        burned every attempt it was configured for. An app-level retry
        loop on top would multiply the wall clock by the envelope
        without the SDK's backoff, and would silently blow the job
        timeout that `_retry_envelope` was written to stay inside.
        """
        client = _FailingSdkClient(_status_error(500))
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        await _run_job_whose_node_calls_the_model("envelope", scripted_workflow)

        assert client.calls == 1
        # And exactly one upstream error, not one per notional attempt.
        assert len(triple.records("llm_upstream_error")) == 1

    async def test_retries_the_sdk_absorbed_are_still_counted(
        self,
        triple: TripleObserver,
        pinned_runner_settings: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A throttled fleet that recovers must not look like a healthy one.

        `retries_taken` is the SDK's own count of attempts it discarded
        before the one that returned. Without it, a run being rate
        limited on every call is indistinguishable from a run that is
        merely slow — the two have completely different fixes.
        """
        # No run accumulator is bound on purpose: the OTel counters are
        # bumped unconditionally, because a call made outside a run
        # still spent money and a fleet's spend rate must not depend on
        # whether the caller remembered to open one.
        monkeypatch.setattr(llm_module, "_get_client", lambda: _RetryingSdkClient(3))

        llm_module.call_llm("prompt", model_name=MODEL)

        assert triple.point("llm_retries_total", model=MODEL).value == 3
        assert triple.point("llm_calls_total", model=MODEL).value == 1
        # No upstream error: the call succeeded in the end.
        assert triple.points("llm_upstream_errors_total") == []


class TestTheReaderNamesTheRightUpstream:
    """The node that used to give the same outage a second name.

    The reader is the only node with a fan-out, so it is the only one
    that can distinguish "one paper's analysis was unusable" from "the
    provider is down". WO-A17 makes it say which: a total failure whose
    every cause was an `UpstreamModel` is a provider outage and is
    reported as one; a total failure with any other cause keeps
    `upstream_paper_read`, which is what that code was named for.
    """

    async def test_a_provider_outage_across_the_whole_fan_out_is_a_model_outage(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """Same outage, same code, whichever node was running.

        This is the assertion the class above could not make before: a
        429 that lands in the reader now reaches
        `research_jobs_total{error_type}` under the same name as a 429
        that lands in the planner. An operator alerting on that series
        gets one signal for one incident instead of two for the same
        one.
        """
        job = Job(job_id="provider-outage", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(
            job,
            scripted_workflow(
                raises=UpstreamModel(log_detail="all 3 paper analyses failed")
            ),
            store,
            asyncio.Semaphore(1),
        )

        assert job.status == JobStatus.failed
        assert job.error_type == UpstreamModel.code
        assert job.error_type in JOB_ERROR_TYPES

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": UpstreamModel.code},
        )

    async def test_papers_that_are_merely_unreadable_keep_their_own_code(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
    ) -> None:
        """The distinction the fix must not collapse.

        `AllPaperAnalysesFailedError` is re-parented onto
        `UpstreamPaperRead`, and it stays that way: "papers were found
        but none of them could be read" is a different incident from a
        provider outage, with a different fix, and folding the two into
        one code to make the previous test pass would have traded one
        misnaming for another.
        """
        job = Job(job_id="unreadable", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)

        await run_job(
            job,
            scripted_workflow(raises=AllPaperAnalysesFailedError("every analysis failed")),
            store,
            asyncio.Semaphore(1),
        )

        assert job.status == JobStatus.failed
        assert job.error_type == UpstreamPaperRead.code
        # It is a code a *run* is allowed to end as, so the frontend's
        # copy dictionary has a sentence for it.
        assert job.error_type in JOB_ERROR_TYPES

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": UpstreamPaperRead.code},
        )
