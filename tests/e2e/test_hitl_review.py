"""The human-in-the-loop breakpoint, driven to each of its three ends.

WO-A15 deliverable 4. `tests/test_api_hitl.py` covers this flow
thoroughly against a *stub* workflow: it proves the route, the parking,
the resume signal and the error cases. What a stub cannot show is
whether the decision reaches the graph — whether an approval resumes
from the checkpoint instead of restarting, and whether a revision is
the plan the rest of the run actually uses rather than a field written
to a job row and forgotten.

So this drives the real compiled graph behind the real app, and reads
the answer out of the checkpointer: after the run, the thread's final
state must carry the reviewer's words. That is the assertion the ADR
0030 design rests on, and it is unavailable from either side alone —
the API never exposes `sub_questions` on a finished job, and a
graph-level test never sees the review route.

Three endings, because they are three different terminal states and the
reviewer picks between them: revise, approve, cancel.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from src.observability.costs import RunCosts

pytestmark = pytest.mark.e2e

#: How long a poll waits for the job to reach the status it is after.
#: Never approached on a healthy run; bounded so a stall fails with the
#: status it was stuck on rather than being killed by the 60-second
#: per-test ceiling with nothing to say.
POLL_TIMEOUT_SEC = 30.0

#: What the reviewer replaces the planner's plan with. Distinct strings,
#: so an assertion that finds them cannot be satisfied by the canned
#: planner output leaking through.
REVISED_PLAN: dict[str, list[str]] = {
    "sub_questions": [
        "Which hallucination mitigations survive out-of-distribution input?",
        "What does the reviewer think the planner missed?",
    ],
    "search_queries": ["out of distribution hallucination benchmark"],
}


async def _wait_for_status(
    client: AsyncClient, job_id: str, *wanted: str
) -> dict[str, Any]:
    """Poll a job until it reports one of `wanted`, or fail saying why."""
    deadline = asyncio.get_running_loop().time() + POLL_TIMEOUT_SEC
    body: dict[str, Any] = {}
    while asyncio.get_running_loop().time() < deadline:
        response = await client.get(f"/research/{job_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in wanted:
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(
        f"job {job_id} never reached {wanted}; last status "
        f"{body.get('status')!r} ({body.get('error_type')}: {body.get('error')})"
    )


@pytest.fixture
async def hitl_client(
    install_settings: Callable[..., Any],
    research_llm_surface: Callable[..., None],
    tmp_path: Path,
) -> AsyncIterator[tuple[AsyncClient, Path]]:
    """The production app with the HITL breakpoint armed.

    Yields the checkpoint database alongside the client, because the
    reviewer's decision is only provable from the graph's own state and
    that is where it lives. HITL is on and `hitl_bypass` is *not* set on
    the requests below — the opposite of every other module in this
    tier, which is the point.
    """
    checkpoints = tmp_path / "e2e-hitl.sqlite"
    install_settings(
        enable_checkpointing=True,
        checkpoint_backend="sqlite",
        checkpoint_db_path=str(checkpoints),
        enable_hitl=True,
        enable_api_auth=False,
    )
    research_llm_surface()

    from src.api.app import create_app

    app = create_app()
    async with LifespanManager(app, startup_timeout=30), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, checkpoints


def _final_plan(checkpoints: Path, job_id: str) -> dict[str, Any]:
    """Read the finished thread's plan straight out of the checkpointer.

    A second, sync-saver graph over the same database rather than the
    app's own: the question is what the *durable* state says, which is
    what a resumed worker or the redriver would read, not what the
    process that ran the job happens to still hold in memory.
    """
    from src.graph.workflow import build_workflow

    app = build_workflow(enable_hitl=False)
    try:
        snapshot = app.get_state({"configurable": {"thread_id": job_id}})
    finally:
        app._checkpointer_exit_stack.close()
    values = dict(snapshot.values)
    return {
        "sub_questions": list(values.get("sub_questions") or []),
        "search_queries": list(values.get("search_queries") or []),
        "messages": [
            str(getattr(message, "name", "") or "")
            for message in values.get("messages") or []
        ],
        "iteration": values.get("iteration"),
        "citations": list(values.get("citations") or []),
    }


class TestPlanReview:
    async def test_a_run_parks_for_review_and_shows_the_reviewer_the_plan(
        self,
        hitl_client: tuple[AsyncClient, Path],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """The pause is real, and the plan it shows is the planner's own.

        A breakpoint that parks but shows an empty plan is a review the
        human cannot perform. The `interrupt_after=["planner"]` compile
        flag and the runner's `pause_number == 1` policy have to agree
        for this to hold, and neither is observable from the other side.
        """
        client, _ = hitl_client
        planner = e2e_fixtures("research_llm_responses")["planner"]

        submit = await client.post("/research", json={"query": "why hallucination?"})
        assert submit.status_code == 202, submit.text
        job_id = submit.json()["job_id"]

        parked = await _wait_for_status(client, job_id, "pending_review")
        assert parked["result"] is None, "nothing is reportable before the review"
        assert parked["plan"] is not None
        assert parked["plan"]["sub_questions"] == planner["sub_questions"]
        assert parked["plan"]["search_queries"] == planner["search_queries"]

        # A review the API cannot dispatch is refused rather than
        # silently accepted: `revise` with no plan is the mistake a
        # client makes, and it must not resume the run.
        bad = await client.post(
            f"/research/{job_id}/review", json={"action": "revise"}
        )
        assert bad.status_code == 422
        assert (await _wait_for_status(client, job_id, "pending_review"))["plan"]

        # Clean up: a parked job holds the lifespan's drain open.
        cancelled = await client.post(
            f"/research/{job_id}/review", json={"action": "cancel"}
        )
        assert cancelled.status_code == 200
        assert (await _wait_for_status(client, job_id, "cancelled"))["status"] == (
            "cancelled"
        )

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_a_revised_plan_is_the_plan_the_rest_of_the_run_uses(
        self,
        hitl_client: tuple[AsyncClient, Path],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Revise → resume → succeeded, with the reviewer's words in the state.

        The failure this catches is the plausible one: a `revise` that
        persists on the job row, returns 200, resumes the run, and
        never reaches `aupdate_state` — so the human edits the plan, the
        UI says accepted, and the agent researches the plan the human
        rejected. Nothing on the HTTP surface would show it, because a
        finished job does not expose its sub-questions.
        """
        client, checkpoints = hitl_client
        planner = e2e_fixtures("research_llm_responses")["planner"]

        submit = await client.post("/research", json={"query": "why hallucination?"})
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]
        await _wait_for_status(client, job_id, "pending_review")

        review = await client.post(
            f"/research/{job_id}/review",
            json={"action": "revise", "plan": REVISED_PLAN},
        )
        assert review.status_code == 200
        # The response is a snapshot taken at accept time, not the
        # settled outcome — the resume is asynchronous.
        assert review.json() == {
            "job_id": job_id,
            "status": "pending_review",
            "action": "revise",
        }

        finished = await _wait_for_status(client, job_id, "succeeded", "failed")
        assert finished["status"] == "succeeded", finished
        assert finished["result"]
        assert finished["iterations"] == 1
        assert usd(finished["cost_usd"]) == "$0.0000"
        assert finished["llm_calls"] == 0
        # The plan slot is cleared once the review is resolved, so a
        # client cannot mistake a settled job for one still awaiting a
        # decision.
        assert finished["plan"] is None

        state = _final_plan(checkpoints, job_id)
        assert state["sub_questions"] == REVISED_PLAN["sub_questions"]
        assert state["search_queries"] == REVISED_PLAN["search_queries"]
        assert state["sub_questions"] != planner["sub_questions"]
        # Resumed from the checkpoint, not restarted: the planner ran
        # once, before the review, and its output was replaced rather
        # than regenerated. A second `planner` here would mean the
        # reviewer's edit was overwritten by a re-plan.
        assert state["messages"] == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "critic",
        ]
        assert state["iteration"] == 1
        assert state["citations"]

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_an_approval_resumes_the_run_on_the_plan_it_was_shown(
        self,
        hitl_client: tuple[AsyncClient, Path],
        e2e_fixtures: Callable[[str], dict[str, Any]],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Approve → resume unchanged → succeeded.

        The mirror of the revision test, and it fails against a
        different bug: an `approve` that writes an empty plan over the
        state, or that restarts the graph, would still finish and still
        look right from the outside.
        """
        client, checkpoints = hitl_client
        planner = e2e_fixtures("research_llm_responses")["planner"]

        submit = await client.post("/research", json={"query": "why hallucination?"})
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]
        await _wait_for_status(client, job_id, "pending_review")

        review = await client.post(
            f"/research/{job_id}/review", json={"action": "approve"}
        )
        assert review.status_code == 200

        finished = await _wait_for_status(client, job_id, "succeeded", "failed")
        assert finished["status"] == "succeeded", finished
        assert finished["result"]
        assert usd(finished["cost_usd"]) == "$0.0000"
        assert finished["llm_calls"] == 0

        # A resolved review is resolved: reviewing again is a conflict,
        # not a second resume.
        again = await client.post(
            f"/research/{job_id}/review", json={"action": "approve"}
        )
        assert again.status_code == 409

        state = _final_plan(checkpoints, job_id)
        assert state["sub_questions"] == planner["sub_questions"]
        assert state["search_queries"] == planner["search_queries"]
        assert state["messages"] == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "critic",
        ]
        assert state["citations"]

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_a_cancelled_review_ends_the_run_without_a_report(
        self,
        hitl_client: tuple[AsyncClient, Path],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """Cancel → `cancelled`, and nothing downstream of the planner ran.

        The third terminal state, and the one where the trajectory
        assertion carries the weight: a run that cancelled *after*
        searching and reading would report `cancelled` just the same,
        having spent the money the cancel was meant to save.
        """
        client, checkpoints = hitl_client

        submit = await client.post("/research", json={"query": "abandon this"})
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]
        await _wait_for_status(client, job_id, "pending_review")

        review = await client.post(
            f"/research/{job_id}/review", json={"action": "cancel"}
        )
        assert review.status_code == 200

        finished = await _wait_for_status(client, job_id, "cancelled", "failed")
        assert finished["status"] == "cancelled", finished
        assert not finished["result"]

        # The planner ran because the breakpoint is *after* it; nothing
        # past it did.
        state = _final_plan(checkpoints, job_id)
        assert state["messages"] == ["planner"]
        assert state["citations"] == []

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0

    async def test_a_bypassed_run_never_offers_a_review(
        self,
        hitl_client: tuple[AsyncClient, Path],
        zero_spend_ledger: RunCosts,
        usd: Callable[[float | None], str],
    ) -> None:
        """`hitl_bypass` skips the pause with the breakpoint still armed.

        This is the flag the eval runner and every programmatic client
        set, and it is the one that must not quietly stop working: a
        campaign whose jobs park for a human review that never comes
        fails thirty minutes later on `hitl_timeout`, one job at a time.
        """
        client, _ = hitl_client

        submit = await client.post(
            "/research", json={"query": "no review please", "hitl_bypass": True}
        )
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]

        finished = await _wait_for_status(client, job_id, "succeeded", "failed")
        assert finished["status"] == "succeeded", finished
        assert finished["plan"] is None
        assert finished["iterations"] == 1
        assert usd(finished["cost_usd"]) == "$0.0000"
        assert finished["llm_calls"] == 0

        # A job that never parked has no review to resolve.
        refused = await client.post(
            f"/research/{job_id}/review", json={"action": "approve"}
        )
        assert refused.status_code == 409

        assert usd(zero_spend_ledger.total_cost_usd) == "$0.0000"
        assert zero_spend_ledger.call_count == 0
