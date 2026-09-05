"""Two tiers, one process, real graphs (ADR 0085).

`tests/test_compute_controller_runtime.py` proves the runner selects the
right *stub*. This tier answers the question only compiled graphs and
real agent code can: does a run the controller escalated actually verify
and repair, and does a run it did not actually skip the whole stage —
in the same process, off one compiled pair, with nothing but the query
different between them?

That is the property `research_policy` cannot have. It picks the shape
once at settings load (ADR 0076), so a deployment is arm B or arm C for
its whole life. The four trajectories below are two of each, minutes
apart, from one `build_workflow` call.

| Query | Tier | Nodes after the synthesizer |
|---|---|---|
| "how do transformers work" | T0 | critic |
| "compare GPT-4 and BERT" | T1 | verify, critic |
| "compare GPT-4 and BERT" (verifier reports a gap) | T1 | verify, repair, search, reader, synthesizer, verify, critic |

Zero spend is the tier's autouse assertion (`zero_spend_ledger`) and it
matters here for the reason it matters in
`tests/e2e/test_verify_repair.py`: an escalated run costs a second
synthesis and two verifications, so a controller that escalated a run to
a *real* model would be the most expensive mistake in this work order.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from typing import Any

import pytest

from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.graph.workflow import build_workflow, compute_tier_graphs

pytestmark = pytest.mark.e2e

#: The modules that bind `src.config.settings` on the path a tiered run
#: takes. The tier's own list plus the verifier (only wired into a graph
#: under the escalated shape) and the runner, which is what reads the
#: controller switch.
CONTROLLER_SETTINGS_CONSUMERS: tuple[str, ...] = (
    "src.agents.assessment",
    "src.agents.critic",
    "src.agents.planner",
    "src.agents.reader",
    "src.agents.search",
    "src.agents.synthesizer",
    "src.agents.tutor",
    "src.agents.verifier",
    "src.api.app",
    "src.api.routes",
    "src.api.runner",
    "src.graph.workflow",
    "src.learning.memory",
)

#: The controller's recommended configuration (ADR 0085): it owns the
#: shape, so `research_policy` stays `legacy` and neither the supervisor
#: nor the supervisor's verify action is on; the evidence store is what
#: makes T0 arm B and T1 arm C rather than arm A and a capability gap.
CONTROLLER: dict[str, Any] = {
    "compute_controller": "deterministic",
    "research_policy": "legacy",
    "enable_supervisor": False,
    "enable_evidence_store": True,
    "enable_verifier": False,
    "enable_checkpointing": False,
    "enable_hitl": False,
}

#: Short, one entity, no cue — the table's `default_t0` row.
QUIET_QUERY = "how do transformers work"

#: A comparison word and two named systems — two escalations, so a run
#: that reaches T1 here is not resting on a single rule.
ESCALATED_QUERY = "compare GPT-4 and BERT"

FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")

VERIFIER_PASSES: dict[str, Any] = {
    "verified": True,
    "unsupported_claims": [],
    "missing_evidence": [],
    "recommended_action": "",
    "reason": "every cited claim resolves against a listed source",
}

VERIFIER_REPORTS_A_GAP: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": [],
    "missing_evidence": ["quantisation error rates under 4-bit inference"],
    "recommended_action": "search_more",
    "reason": "no cited source covers the second sub-question",
}


@pytest.fixture
def verifier_script(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Sequence[dict[str, Any]]], dict[str, int]]:
    """Script the judge: the Nth verification gets the Nth response.

    The same fixture `tests/e2e/test_verify_repair.py` uses, and for the
    same reason: "the verifier ran twice" is an assertion in its own
    right, because a graph that skipped re-verification would still pass
    a node-sequence check if it routed correctly for the wrong reason.
    """

    def _install(script: Sequence[dict[str, Any]]) -> dict[str, int]:
        calls = {"count": 0}
        responses = list(script)

        def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            index = min(calls["count"], len(responses) - 1)
            calls["count"] += 1
            return dict(responses[index])

        monkeypatch.setattr("src.agents.verifier.call_llm_json", _call)
        return calls

    return _install


async def _run(app: Any, query: str, job_id: str) -> tuple[Job, list[str]]:
    """Drive one job through the runner; return it and its node sequence.

    The nodes are read off the SSE frames rather than off the graph,
    which is deliberate: they are what a client saw, so a run that
    routed correctly while telling its clients something else would
    fail here.
    """
    job = Job(job_id=job_id, query=query, hitl_bypass=True)
    store = InMemoryJobStore()
    await store.create(job)
    await run_job(job, app, store, asyncio.Semaphore(1))

    nodes: list[str] = []
    while not job.event_queue.empty():
        frame = job.event_queue.get_nowait()
        if frame["event"] == "node_completed":
            nodes.append(str(frame["data"]["node"]))
    return job, nodes


@pytest.fixture
async def tiered_app(
    install_settings: Callable[..., Any],
    research_llm_surface: Callable[..., None],
) -> Any:
    """One compiled pair, built the way the API lifespan builds it."""
    install_settings(modules=CONTROLLER_SETTINGS_CONSUMERS, **CONTROLLER)
    research_llm_surface()
    app = await build_workflow(async_checkpointer=True, enable_hitl=False)
    try:
        yield app
    finally:
        stack = getattr(app, "_checkpointer_aexit_stack", None)
        if stack is not None:
            await stack.aclose()


class TestOnePairOfGraphsServesBothTiers:
    async def test_the_pair_is_compiled_once_and_holds_both_shapes(
        self, tiered_app: Any
    ) -> None:
        graphs = compute_tier_graphs(tiered_app)
        assert graphs is not None
        assert set(graphs) == {"T0", "T1"}
        assert graphs["T0"] is tiered_app

    async def test_a_quiet_query_never_reaches_a_verification(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        """The control arm, and the reason the default stays cheap.

        The verifier is scripted anyway: a run that reached it despite
        the fixed shape would be served a canned verdict instead of
        hitting the harness spend guard, and the call counter below is
        what turns that into a failure rather than a pass.
        """
        calls = verifier_script([VERIFIER_PASSES])

        job, nodes = await _run(tiered_app, QUIET_QUERY, "cap04-e2e-quiet")

        assert job.status is JobStatus.succeeded
        assert nodes == list(FIXED_PIPELINE)
        assert "verify" not in nodes
        assert calls["count"] == 0

    async def test_an_escalated_query_is_verified_before_the_critic(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        calls = verifier_script([VERIFIER_PASSES])

        job, nodes = await _run(tiered_app, ESCALATED_QUERY, "cap04-e2e-loud")

        assert job.status is JobStatus.succeeded
        assert nodes == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert calls["count"] == 1

    async def test_an_escalated_query_repairs_a_reported_gap(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        """The whole reason escalating is worth three extra nodes.

        Same trajectory `tests/e2e/test_verify_repair.py` pins for arm
        C, reached here without `RESEARCH_POLICY` being set at all —
        which is the deliverable: the *run* chose it.
        """
        calls = verifier_script([VERIFIER_REPORTS_A_GAP, VERIFIER_PASSES])

        job, nodes = await _run(tiered_app, ESCALATED_QUERY, "cap04-e2e-repair")

        assert job.status is JobStatus.succeeded
        assert nodes == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "repair",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "critic",
        ]
        assert calls["count"] == 2, "the repaired report must be verified again"

    async def test_both_tiers_run_back_to_back_in_one_process(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        """The claim in one test, and the one `research_policy` cannot make.

        Two queries, one compiled pair, one process, two different
        shapes — and the cheap run stays cheap after the expensive one
        has been through, which is what says the tier is per-run rather
        than a process-wide latch that happened to be set correctly.
        """
        verifier_script([VERIFIER_PASSES])

        _, loud = await _run(tiered_app, ESCALATED_QUERY, "cap04-e2e-pair-1")
        _, quiet = await _run(tiered_app, QUIET_QUERY, "cap04-e2e-pair-2")
        _, loud_again = await _run(tiered_app, ESCALATED_QUERY, "cap04-e2e-pair-3")

        assert "verify" in loud
        assert "verify" not in quiet
        assert quiet == list(FIXED_PIPELINE)
        assert loud_again == loud

    async def test_the_frames_a_client_sees_carry_no_new_key(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        """Deliverable 5's negative half, against the real runner.

        The allocation is recorded on the trajectory and deliberately
        not in SSE: `node_completed` is two keys, and a third would move
        a frame shape `tests/test_contract_sse_events.py` pins.
        """
        verifier_script([VERIFIER_PASSES])
        job = Job(
            job_id="cap04-e2e-frames", query=ESCALATED_QUERY, hitl_bypass=True
        )
        store = InMemoryJobStore()
        await store.create(job)
        await run_job(job, tiered_app, store, asyncio.Semaphore(1))

        frames: list[dict[str, Any]] = []
        while not job.event_queue.empty():
            frames.append(job.event_queue.get_nowait())

        assert [frame["event"] for frame in frames][0] == "job_started"
        assert [frame["event"] for frame in frames][-1] == "job_completed"
        node_frames = [f for f in frames if f["event"] == "node_completed"]
        assert node_frames
        assert all(set(f["data"]) == {"node", "state_delta"} for f in node_frames)


class TestTheEscalatedRunIsStillFree:
    async def test_neither_tier_spends_anything(
        self, tiered_app: Any, verifier_script: Callable[..., dict[str, int]]
    ) -> None:
        """Restated as an assertion rather than left to the autouse guard.

        The tier's ledger fails a *model call*; this fails a job whose
        recorded cost moved, which is the number an operator reads and
        the one the eval baselines compare against.
        """
        verifier_script([VERIFIER_REPORTS_A_GAP, VERIFIER_PASSES])

        quiet, _ = await _run(tiered_app, QUIET_QUERY, "cap04-e2e-free-1")
        loud, _ = await _run(tiered_app, ESCALATED_QUERY, "cap04-e2e-free-2")

        assert quiet.cost_usd == 0.0
        assert loud.cost_usd == 0.0
