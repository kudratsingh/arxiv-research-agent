"""The supervisor's routing call fails and the run keeps going (WO-B3).

Every other file in this tier asserts a failure that *ended* a run. This
one asserts a failure that did not, which is why it was invisible: the
supervisor's `except Exception` returned the fixed-pipeline route, the
loop carried on, the job ended `succeeded`, and
`research_jobs_total{error_type}` — the series an on-call engineer reads
first — never moved. A model-provider incident and a healthy afternoon
produced the same run-level telemetry.

| fault | code | event | metric |
|---|---|---|---|
| provider refuses the routing call | `upstream_model` | `supervisor_provider_outage` | `llm_upstream_errors_total{status}` |
| judge answers with unparseable JSON | *(none)* | `supervisor_llm_failed_fallback_to_default` | `llm_calls_total`, and `llm_upstream_errors_total` records **nothing** |
| job cancelled during the routing call | `cancelled_job` | `api_job_failed` | `research_jobs_total{status="failed", error_type="cancelled_job"}` |

**On the metric leg of row one.** `llm_upstream_errors_total` moved
before this work order too — `src/llm.py` counts the failed call on its
way to raising `UpstreamModel`, whichever node made it. So the open item
this file closes overstated its case when it said no alert on any series
could see the outage: the *call* was always counted. What no series
could see was the outage's consequence — that a run had been routed by
nothing, and had then reported success. The fix is therefore not a new
counter; it is a log event at ERROR carrying the same code the same
outage produces in every other node, plus a `stop_reason` of
`llm_failed` on the run itself, so the three legs describe one incident
instead of one call.

**Why the flag is turned on explicitly.** `enable_supervisor` is off in
the shipped defaults, so nothing in the rest of the suite executes this
node — which is exactly the window in which to fix it, and exactly the
reason a test that forgot to turn the flag on would pass while asserting
nothing. Each test below pins `settings.enable_supervisor=True` on the
agent module's own handle and `test_the_flag_this_file_depends_on`
proves the flag still selects the loop shape it names.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from src import llm as llm_module
from src.agents import supervisor as sup
from src.agents.supervisor import supervisor_agent
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.cancellation import current_cancel_token
from src.config import Settings
from src.errors import JOB_ERROR_TYPES, JobCancelled, UpstreamModel
from src.graph.state import ResearchState

from .conftest import ScriptedWorkflow, TripleObserver

pytestmark = [pytest.mark.unit, pytest.mark.fault]


def _routing_state(**overrides: Any) -> ResearchState:
    """A state the fixed-pipeline fallback routes to `plan` from.

    Empty of everything, so `_default_next_action` takes its first
    branch. The fallback's own routing table is unit-tested elsewhere;
    what matters here is that a route came back at all.
    """
    base: dict[str, Any] = {
        "query": "q?",
        "sub_questions": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "critique": "",
        "iteration": 0,
        "loop_iterations": 0,
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


class _FailingSdkClient:
    """The Anthropic SDK after it has exhausted its own retries.

    Same shape as `test_model_provider_faults.py`'s — the surface
    `call_llm` reaches for is `messages.with_raw_response.create` — so
    the routing call fails the way every other node's call fails.
    """

    def __init__(self, raises: Exception) -> None:
        self.calls = 0
        self._raises = raises
        self.messages = SimpleNamespace(with_raw_response=self)

    def create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        raise self._raises


class _GarbageSdkClient:
    """A provider that answers, with a body that is not JSON.

    The malformed judge ADR 0014's fallback was written for. Driven
    through the real client surface rather than by monkeypatching
    `call_llm_json`, because the distinction under test is between two
    exceptions that both arrive at the same `except` — and a stub that
    raised the exception directly would prove nothing about which one
    the provider actually produces.
    """

    def __init__(self, text: str) -> None:
        self.messages = SimpleNamespace(with_raw_response=self)
        self._text = text

    def create(self, **_kwargs: Any) -> Any:
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=5,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        parsed = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)], usage=usage
        )
        return SimpleNamespace(retries_taken=0, parse=lambda: parsed)


def _status_error(status_code: int) -> Exception:
    """A real `anthropic.APIStatusError`, built from a real response."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        status_code,
        request=request,
        headers={"request-id": f"req_{status_code}"},
        json={"error": {"type": "overloaded_error"}},
    )
    return llm_module.anthropic.APIStatusError("upstream", response=response, body=None)


@pytest.fixture
def supervisor_enabled(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Turn the supervisor on, on the handle the agent actually reads.

    `src/agents/supervisor.py` reads `settings` at call time so a flag
    can be flipped without re-importing; this is that seam, used the
    way the module documents it.
    """
    pinned = Settings(enable_supervisor=True)
    monkeypatch.setattr(sup, "settings", pinned)
    return pinned


async def _run_routing_through_a_job(
    job_id: str,
    workflow_factory: type[ScriptedWorkflow],
    *,
    before_routing: Any = None,
) -> tuple[Job, list[dict[str, Any]]]:
    """Run a job whose only work is one supervisor routing decision.

    Driven through `run_job` rather than by calling `supervisor_agent`
    alone, because half of what this file asserts is what the *run*
    reported afterwards — and a direct call cannot show that a swallowed
    outage still ends `succeeded`.
    """
    decisions: list[dict[str, Any]] = []

    def _route() -> None:
        if before_routing is not None:
            before_routing()
        decisions.append(supervisor_agent(_routing_state()))

    job = Job(job_id=job_id, query="q", hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    await run_job(
        job,
        workflow_factory(updates=[{"planner": {"iteration": 1}}], on_stream=_route),
        store,
        asyncio.Semaphore(1),
    )
    return job, decisions


class TestTheProviderRefusesTheRoutingCall:
    async def test_the_outage_is_reported_even_though_the_run_continues(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        supervisor_enabled: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The defect, stated as an assertion: both halves at once.

        The run still finishes — a supervisor that refuses to route
        strands work the fixed pipeline could have completed, so
        tolerating the failure is the right call and is unchanged. What
        changed is that tolerating it is no longer the same as hiding
        it. The job reports `succeeded`, and in the same test the outage
        is on all three contracts under the code every other node would
        have given it.
        """
        client = _FailingSdkClient(_status_error(503))
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        job, decisions = await _run_routing_through_a_job(
            "supervisor-outage", scripted_workflow
        )

        # The run was not derailed, and it did get a route.
        assert job.status == JobStatus.succeeded
        assert decisions[0]["next_action"] == "plan"

        record = triple.assert_triple(
            code=UpstreamModel.code,
            event="supervisor_provider_outage",
            instrument="llm_upstream_errors_total",
            attributes={
                "model": llm_module.settings.anthropic_model,
                "status": "503",
            },
        )
        # `assert_triple` proves the line agrees with the code; these
        # two prove it says which route the run was left on, which is
        # the question asked immediately afterwards.
        assert getattr(record, "fallback", None) == "plan"
        assert record.levelname == "ERROR"

        # And the code is one a run could legitimately have *ended* as,
        # so an operator correlating this line with a failed run
        # elsewhere in the fleet is comparing like with like.
        assert UpstreamModel.code in JOB_ERROR_TYPES

    async def test_the_run_level_series_still_reports_a_success(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        supervisor_enabled: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Written down because it is the residue, not the fix.

        A tolerated failure is a successful run by definition, so
        `research_jobs_total{status="succeeded"}` is what moves and
        `error_type` is `none`. Asserting it stops a later reader from
        assuming the outage shows up there, and stops a later change
        from making the job fail without anyone deciding to.
        """
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: _FailingSdkClient(_status_error(529))
        )

        job, _ = await _run_routing_through_a_job(
            "supervisor-outage-run", scripted_workflow
        )

        assert job.status == JobStatus.succeeded
        assert job.error_type is None
        triple.point(
            "research_jobs_total", status="succeeded", error_type="none"
        )

    async def test_a_fallback_that_stops_says_the_router_never_answered(
        self,
        triple: TripleObserver,
        supervisor_enabled: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The run-level attribution, and the worst case of the old bug.

        When the fallback lands on `stop` — every pipeline field already
        populated — the loop ends. It used to end with
        `stop_reason="supervisor_stop"`, the same value a judge writes
        when it decides the work is done, so a run the provider ended
        was recorded as a run the supervisor chose to end. `llm_failed`
        is the bucket ADR 0014's module docstring has advertised since
        the beginning and nothing emitted.
        """
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: _FailingSdkClient(_status_error(500))
        )

        finished = _routing_state(
            sub_questions=["a"],
            papers=[{"id": "p"}],
            paper_analyses=[{"id": "p"}],
            draft_report="a report",
            critique="a critique",
        )
        result = supervisor_agent(finished)

        assert result["next_action"] == "stop"
        assert result["stop_reason"] == sup.LLM_FAILED_STOP_REASON
        triple.one_record("supervisor_provider_outage")


class TestTheJudgeAnswersWithGarbage:
    async def test_a_parse_failure_does_not_look_like_an_outage(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        supervisor_enabled: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The distinction the fix exists to make, asserted from both sides.

        A malformed judge is one run's problem and the fallback was
        written for it (ADR 0014); an outage is every concurrent run's
        problem and had no signal at all. Folding them back together —
        by logging the provider event on both, or by dropping the
        provider branch — would restore the defect while keeping the new
        event name, which is the way this fix is most likely to be
        undone.

        The negative leg is the load-bearing one: a provider that
        answered must not move the upstream-error counter, or an alert
        on that series learns to cry wolf at every truncated body.
        """
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: _GarbageSdkClient("not json at all")
        )

        job, decisions = await _run_routing_through_a_job(
            "supervisor-garbage", scripted_workflow
        )

        assert job.status == JobStatus.succeeded
        assert decisions[0]["next_action"] == "plan"

        record = triple.assert_triple(
            code=None,
            event="supervisor_llm_failed_fallback_to_default",
            instrument="llm_calls_total",
            attributes={"model": llm_module.settings.anthropic_model},
        )
        assert record.levelname == "WARNING"
        # There is no taxonomy code for "the judge answered badly", so
        # the line carries the exception class instead — a name, not a
        # contract, and deliberately not one of `ERROR_CODES`.
        assert getattr(record, "error_type", None) == "JSONDecodeError"

        triple.assert_not_recorded("llm_upstream_errors_total")
        assert triple.records("supervisor_provider_outage") == []


class TestCancellationIsNotABadRoute:
    async def test_a_cancelled_job_stops_instead_of_being_routed(
        self,
        triple: TripleObserver,
        scripted_workflow: type[ScriptedWorkflow],
        pinned_runner_settings: Any,
        supervisor_enabled: Settings,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The half of the swallow that was worse than the outage.

        `call_llm` checks the cancel token before it constructs a client
        (ADR 0047) — that check is the only thing that stops the spend
        on a job the runner has already given up on, because a node
        thread cannot be killed. The old bare `except` caught the
        `JobCancelledError` it raises and answered with a route, so a
        cancelled job's supervisor went on dispatching nodes and each of
        those nodes had to discover the cancellation again.

        Driven through the real checkpoint: the token is the one
        `run_job` bound for this job, cancelled the way the timeout path
        cancels it.
        """
        client = _FailingSdkClient(_status_error(500))
        monkeypatch.setattr(llm_module, "_get_client", lambda: client)

        def _cancel_this_job() -> None:
            token = current_cancel_token()
            assert token is not None
            token.cancel("job_timeout")

        job, decisions = await _run_routing_through_a_job(
            "supervisor-cancelled",
            scripted_workflow,
            before_routing=_cancel_this_job,
        )

        # No route was produced, and the run ended on the cancellation
        # rather than on whatever node the fallback would have picked.
        assert decisions == []
        assert job.status == JobStatus.failed
        assert job.error_type == JobCancelled.code
        assert job.error_type in JOB_ERROR_TYPES

        triple.assert_triple(
            code=job.error_type,
            event="api_job_failed",
            instrument="research_jobs_total",
            attributes={"status": "failed", "error_type": JobCancelled.code},
        )
        # The client was never constructed, so the cancelled job spent
        # nothing on the routing call it was about to make.
        assert client.calls == 0
        assert triple.points("llm_calls_total") == []
        assert triple.records("supervisor_provider_outage") == []


def test_the_flag_this_file_depends_on_still_selects_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The premise of every test above, checked rather than assumed.

    `enable_supervisor` is off by default, so a change that stopped the
    flag wiring the supervisor into the graph would leave this whole
    file passing while testing a node nothing runs. Reading the built
    graph is the cheapest way to keep the premise honest.
    """
    from src.graph import workflow as workflow_module

    monkeypatch.setattr(
        workflow_module, "settings", Settings(enable_supervisor=True)
    )
    built = workflow_module._build_graph_shape(lambda name, fn: fn)
    assert "supervisor" in built.nodes

    monkeypatch.setattr(
        workflow_module, "settings", Settings(enable_supervisor=False)
    )
    assert "supervisor" not in workflow_module._build_graph_shape(
        lambda name, fn: fn
    ).nodes
