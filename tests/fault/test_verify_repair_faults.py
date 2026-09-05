"""What arm C does when the run is stopped mid-policy (ADR 0076).

The verify-and-repair policy adds three node executions to the critical
path — a verification, a repair, and a second verification — and two of
them come *after* the report exists. So the two ways a run is stopped
have to be asked again for this shape, because the answers are not
inherited from the fixed pipeline:

- **A cancel that lands mid-repair.** The repair re-enters the graph at
  a node that costs money. ADR 0047's cooperative check runs at node
  entry, so the question is whether the nodes the repair queued behind
  it stop, or whether the run finishes a repair for a job nobody is
  waiting for any more.
- **A cost ceiling that trips inside the verification.** ADR 0051 puts
  the check in `src.llm.call_llm`, ahead of every call, so the ceiling
  arrives as an exception raised *through* an agent. The verifier
  catches `Exception` broadly and falls back to a recoverable verdict,
  which for this class of exception would convert "stop, you are over
  budget" into "carry on, the judge is unavailable" — and, under this
  policy, carry on into a repair, a second synthesis and a second
  verification. That is the specific overspend the ceiling exists to
  stop, so the propagation is asserted at two levels: the node, and the
  job the runner ends.

Everything is canned, nothing is billed. `_spend_over_the_cap` records
against the run's accumulator the way a real call does, so the assertion
reads the number the runner actually reads.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

import src.agents.critic as critic_module
import src.agents.planner as planner_module
import src.agents.reader as reader_module
import src.agents.search as search_module
import src.agents.synthesizer as synthesizer_module
import src.agents.verifier as verifier_module
import src.api.runner as runner_module
import src.graph.workflow as workflow_module
from src.api.jobs import InMemoryJobStore, Job, JobStatus
from src.api.runner import run_job
from src.cancellation import (
    CancelToken,
    JobCancelledError,
    bind_cancel_token,
    reset_cancel_token,
)
from src.config import Settings
from src.errors import BudgetExceededRun
from src.graph.state import initial_research_state
from src.graph.workflow import build_workflow
from src.observability.costs import CostBudgetExceeded, current_costs

pytestmark = [pytest.mark.unit, pytest.mark.fault]

#: Well over `Settings().max_cost_usd`, so the cap fires on the value
#: rather than on the shipped default's exact figure.
OVERSPEND_USD = 250.0

PLANNER_RESPONSE: dict[str, Any] = {
    "sub_questions": ["What fails?", "What fixes it?"],
    "search_queries": ["failure modes", "mitigations"],
}
READER_RESPONSE: dict[str, Any] = {
    "key_findings": ["Retrieval grounds generation."],
    "methodology": "Survey.",
    "results_summary": "Fewer unsupported claims.",
    "limitations": "Abstract-only.",
    "relevance": 0.9,
}
SYNTHESIZER_RESPONSE: dict[str, Any] = {
    "draft_report": "# Findings\n\nGrounded generation helps [Ji, 2023].\n",
    "citations": [
        {
            "paper_id": "http://arxiv.org/abs/2311.09000",
            "title": "A Survey on Hallucination in Large Language Models",
            "authors": ["Ziwei Ji"],
            "year": "2023",
            "url": "http://arxiv.org/abs/2311.09000",
        }
    ],
}
CRITIC_RESPONSE: dict[str, Any] = {
    "scores": {
        "completeness": 0.9,
        "accuracy": 0.9,
        "coherence": 0.9,
        "depth": 0.8,
        "balance": 0.9,
    },
    "average_score": 0.88,
    "critique": "Fine.",
    "revision_needed": False,
    "revision_target": "none",
}
VERIFIER_REPORTS_AN_OVERCLAIM: dict[str, Any] = {
    "verified": False,
    "unsupported_claims": ["Grounded generation removes every error."],
    "missing_evidence": [],
    "recommended_action": "revise_report",
    "reason": "over-claims the cited excerpt",
}


def _canned(response: dict[str, Any]) -> Callable[..., dict[str, Any]]:
    """A `call_llm_json` stand-in that ignores its prompt arguments."""

    def _call(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return dict(response)

    return _call


@pytest.fixture
def arm_c_graph(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Install arm C's settings and can every network-touching seam.

    Per module, because `settings` and `call_llm_json` are both bound
    into each agent's namespace at import — the asymmetry
    `tests/e2e/conftest.py` documents. The runner keeps a *default*
    `Settings` (see `pinned_runner_settings`): its cost cap is the one
    under test and must be the shipped value, not this policy's.
    """
    patched = Settings(
        research_policy="fixed_verify_repair",
        enable_supervisor=False,
        enable_evidence_store=True,
        enable_verifier=False,
        enable_checkpointing=False,
        use_mock_data=True,
        enable_tracing=False,
        enable_semantic_scholar=False,
    )
    monkeypatch.setattr(search_module, "settings", patched)
    monkeypatch.setattr(workflow_module, "settings", patched)
    # The five agents get the same settings with mock mode *off* (ADR
    # 0080). Their own mock branch returns before `call_llm_json`, so
    # without this every patch below would be dead code and these tests
    # would drive the fixture instead of the policy. `search` keeps
    # `use_mock_data=True` because the corpus is still the fixture one —
    # `settings` is bound per module, so the two halves separate.
    mock_off = patched.model_copy(update={"use_mock_data": False})
    for module in (
        planner_module,
        reader_module,
        synthesizer_module,
        verifier_module,
        critic_module,
    ):
        monkeypatch.setattr(module, "settings", mock_off)

    monkeypatch.setattr(planner_module, "call_llm_json", _canned(PLANNER_RESPONSE))
    monkeypatch.setattr(reader_module, "call_llm_json", _canned(READER_RESPONSE))
    monkeypatch.setattr(
        synthesizer_module, "call_llm_json", _canned(SYNTHESIZER_RESPONSE)
    )
    monkeypatch.setattr(critic_module, "call_llm_json", _canned(CRITIC_RESPONSE))
    monkeypatch.setattr(reader_module, "parse_pdf", lambda url: "")
    monkeypatch.setattr(
        search_module,
        "rank_papers_by_relevance",
        lambda query, papers, top_k: list(papers)[:top_k],
    )
    return patched


@pytest.fixture
def node_pool() -> Iterator[ThreadPoolExecutor]:
    """The pool ADR 0047's async build dispatches nodes onto."""
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cap02-pool")
    try:
        yield pool
    finally:
        pool.shutdown(wait=True)


def _spend_over_the_cap() -> None:
    """Bill the run's accumulator the way a real agent call does."""
    costs = current_costs()
    assert costs is not None, "the runner must have started cost tracking"
    costs.record(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cost_usd=OVERSPEND_USD,
    )


class TestACancelLandingMidRepair:
    async def test_the_nodes_queued_behind_the_repair_never_run(
        self,
        arm_c_graph: Settings,
        node_pool: ThreadPoolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cancel during the repaired synthesis; the run stops there.

        The cancel is raised from inside the *second* synthesizer call —
        the one the repair queued — so the repair is genuinely in flight
        rather than not yet started. ADR 0047's check runs at node
        entry, so the synthesis that was already running finishes and
        the second verification never starts: a cancelled job does not
        pay for the verification of a report nobody will read.
        """
        visited: list[str] = []
        calls = {"verify": 0, "synthesize": 0}

        def _verifier(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["verify"] += 1
            return dict(VERIFIER_REPORTS_AN_OVERCLAIM)

        token = CancelToken("cancel-mid-repair")

        def _synthesizer(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["synthesize"] += 1
            if calls["synthesize"] == 2:
                token.cancel("cancelled_by_user")
            return dict(SYNTHESIZER_RESPONSE)

        monkeypatch.setattr(verifier_module, "call_llm_json", _verifier)
        monkeypatch.setattr(synthesizer_module, "call_llm_json", _synthesizer)

        app = await build_workflow(
            enable_hitl=False, async_checkpointer=True, node_executor=node_pool
        )
        scope = bind_cancel_token(token)
        try:
            with pytest.raises(JobCancelledError):
                async for chunk in app.astream(
                    initial_research_state("cancel me", "cancel-mid-repair")
                ):
                    visited.extend(node for node in chunk if node != "__interrupt__")
        finally:
            reset_cancel_token(scope)
            await app._checkpointer_aexit_stack.aclose()

        assert visited == [
            "planner",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "repair",
            "synthesizer",
        ]
        assert calls["verify"] == 1, "the re-verification must not have been paid for"


class TestTheCeilingTrippingInsideTheVerification:
    def test_the_node_propagates_the_stop_instead_of_abstaining(
        self, arm_c_graph: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The narrow assertion, at the seam where it would be lost.

        `verify_node` reaches the judge through the same broad
        `except Exception` that turns a provider outage into an
        abstention. A budget stop caught there would read as "the judge
        was unavailable", and the policy would carry on spending.
        """

        def _over_budget(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise CostBudgetExceeded(spent_usd=OVERSPEND_USD, cap_usd=2.0)

        monkeypatch.setattr(verifier_module, "call_llm_json", _over_budget)

        state = initial_research_state("q", "verify-over-budget")
        state["draft_report"] = SYNTHESIZER_RESPONSE["draft_report"]
        state["citations"] = list(SYNTHESIZER_RESPONSE["citations"])

        with pytest.raises(CostBudgetExceeded):
            verifier_module.verify_node(state)

    async def test_the_job_ends_as_a_budget_stop_with_its_report_intact(
        self,
        arm_c_graph: Settings,
        node_pool: ThreadPoolExecutor,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The whole outcome, through the real runner and the real graph.

        The ceiling trips on the first verification, after the
        synthesizer has already produced a report. Both halves of ADR
        0051 §2 are asserted: the job is `failed` with
        `cost_budget_exceeded`, because the caller must know the report
        is partial, and the report the money already bought is still
        attached to it.
        """
        monkeypatch.setattr(runner_module, "settings", Settings())

        def _over_budget(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            # Exactly what `src.llm.call_llm`'s pre-flight check does
            # once the accumulator is over the cap (ADR 0051).
            _spend_over_the_cap()
            costs = current_costs()
            assert costs is not None
            raise CostBudgetExceeded(
                spent_usd=costs.total_cost_usd, cap_usd=Settings().max_cost_usd
            )

        monkeypatch.setattr(verifier_module, "call_llm_json", _over_budget)

        app = await build_workflow(
            enable_hitl=False, async_checkpointer=True, node_executor=node_pool
        )
        job = Job(job_id="armc-capped", query="q", hitl_bypass=True)
        store = InMemoryJobStore()
        await store.create(job)
        try:
            await run_job(job, app, store, asyncio.Semaphore(1))
        finally:
            await app._checkpointer_aexit_stack.aclose()

        assert job.status == JobStatus.failed
        assert job.error_type == BudgetExceededRun.code
        assert job.result == SYNTHESIZER_RESPONSE["draft_report"]

        stored = await store.get("armc-capped")
        assert stored is not None
        assert stored.status == JobStatus.failed
        assert stored.error_type == BudgetExceededRun.code
