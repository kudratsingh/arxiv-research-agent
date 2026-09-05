"""No-cost qualification for the in-memory shadow bridge (P0-WO05).

The bridge's whole promise is negative — a run must end exactly as it
would have ended without it — so most of what is asserted here is that
something did *not* happen: a hook that raises does not fail a job, a
degraded run stops recording rather than stopping the run, a session job
gets no shadow at all, and a `contract_shadow=off` process never reaches
a contract module.

The positive half is the trajectory itself: `run.admitted` first and
bound to the sealed manifest, one action pair per node, one usage delta
per model call, a terminal event that matches the job row, and a JSONL
export that survives a round trip through the contract's own importer
with its hash chain intact.

No network, no provider, no model, and no compiled graph: the policy
shape comes from a stand-in whose only job is to answer `get_graph()`.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.api.jobs import Job, JobStatus
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts import shadow_bridge as bridge
from src.contracts.trajectory import fold_trajectory, import_jsonl, verify_trajectory
from src.observability.costs import LlmCallObservation, RunCosts

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Edge:
    def __init__(self, source: str, target: str, conditional: bool = False) -> None:
        self.source = source
        self.target = target
        self.conditional = conditional


class _Graph:
    def __init__(self, nodes: list[str], edges: list[_Edge]) -> None:
        self.nodes = {name: object() for name in nodes}
        self.edges = edges


class _AppStub:
    """A compiled-graph stand-in exposing only `get_graph()`."""

    def __init__(self, nodes: list[str] | None = None) -> None:
        names = nodes or ["planner", "search", "reader", "synthesizer", "critic"]
        self._graph = _Graph(
            [*names, "__start__", "__end__"],
            [
                _Edge("__start__", names[0]),
                *(
                    _Edge(left, right)
                    for left, right in zip(names, names[1:], strict=False)
                ),
                _Edge(names[-1], "__end__", conditional=True),
            ],
        )

    def get_graph(self) -> _Graph:
        return self._graph


FIXED_PIPELINE = ("planner", "search", "reader", "synthesizer", "critic")


def config(**overrides: Any) -> Settings:
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_semantic_scholar": False,
        "enable_checkpointing": False,
        "contract_shadow": "shadow",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def research_job(job_id: str = "job-1", **overrides: Any) -> Job:
    job = Job(job_id=job_id, query="why do LLMs hallucinate?", hitl_bypass=True)
    for name, value in overrides.items():
        setattr(job, name, value)
    return job


@pytest.fixture(autouse=True)
def _clean_registry() -> Any:
    bridge.reset_registry()
    yield
    bridge.reset_registry()


def open_run(cfg: Settings | None = None, job: Job | None = None) -> bridge.ShadowRun:
    run = bridge.start_research_job(
        job or research_job(),
        _AppStub(),
        config=cfg or config(),
        cost_ceiling_usd=2.0,
    )
    assert run is not None
    return run


def model_call(cost: float = 0.0, model: str = "claude-sonnet-4-6") -> LlmCallObservation:
    return LlmCallObservation(
        model=model,
        input_tokens=120,
        output_tokens=40,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cost_usd=cost,
        retries=0,
        latency_ms=12.5,
    )


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


class TestTheSwitch:
    def test_off_is_the_default_and_opens_nothing(self) -> None:
        assert shipped_settings.contract_shadow == "off"
        assert bridge.shadow_enabled(config(contract_shadow="off")) is False
        assert (
            bridge.start_research_job(
                research_job(), _AppStub(), config=config(contract_shadow="off"),
                cost_ceiling_usd=2.0,
            )
            is None
        )
        assert bridge.retained_run_ids() == ()

    def test_a_session_job_is_never_shadowed_by_the_research_binding(self) -> None:
        session = research_job(job_id="session-1", kind="session")
        assert (
            bridge.start_research_job(
                session, _AppStub(), config=config(), cost_ceiling_usd=2.0
            )
            is None
        )

    def test_a_metered_provider_declines_instead_of_sealing(self) -> None:
        """The fail-closed path, seen from the bridge rather than the binder."""
        assert (
            bridge.start_research_job(
                research_job(),
                _AppStub(),
                config=config(use_mock_data=False),
                cost_ceiling_usd=2.0,
            )
            is None
        )

    def test_the_scripted_hooks_are_none_unless_the_switch_is_on(self) -> None:
        assert bridge.scripted_research_hooks(config(contract_shadow="off")) is None
        assert isinstance(
            bridge.scripted_research_hooks(config()), bridge.ScriptedResearchHooks
        )


# ---------------------------------------------------------------------------
# The trajectory
# ---------------------------------------------------------------------------


class TestTheTrajectory:
    def test_run_admitted_is_first_and_binds_the_sealed_manifest(self) -> None:
        run = open_run()
        events = run.events()
        assert events[0].event_type == "run.admitted"
        assert events[0].run_seq == 1
        assert events[0].attempt_id is None
        assert all(
            event.manifest_digest == run.episode.manifest_digest for event in events
        )
        assert events[0].payload["admission_receipt_digest"] == (
            run.episode.manifest.payload.admission_resolution.receipt_ref.digest
        )
        assert [event.event_type for event in events[1:3]] == [
            "attempt.started",
            "budget.established",
        ]
        assert events[2].payload["episode_cap"] == "2.000000"

    def test_one_task_spec_is_compiled_and_reused_by_every_event(self) -> None:
        run = open_run()
        for node in FIXED_PIPELINE:
            bridge.observe_node(run, node, {})
        spec_ids = {event.task_spec_id for event in run.events()}
        digests = {event.task_spec_full_digest for event in run.events()}
        assert spec_ids == {run.episode.task_spec.task_spec_id}
        assert digests == {run.episode.task_ref.full_digest}

    def test_the_node_sequence_survives_the_round_trip(self) -> None:
        run = open_run()
        for node in FIXED_PIPELINE:
            bridge.observe_node(run, node, {"draft_report": "x"})
        assert run.node_trajectory() == FIXED_PIPELINE

        job = research_job()
        job.status = JobStatus.succeeded
        job.result = "# A report\n"
        bridge.observe_job_terminal(run, job)

        exported = run.export_jsonl()
        events = import_jsonl(exported)
        verify_trajectory(events)
        assert len(events) == len(run.events())
        assert [event.event_hash for event in events] == [
            event.event_hash for event in run.events()
        ]
        assert exported.count("\n") == len(events)

    def test_one_model_call_produces_one_usage_delta(self) -> None:
        run = open_run()
        costs = RunCosts()
        for _ in range(3):
            costs.record("claude-sonnet-4-6", 120, 40, 0.0)
            bridge.observe_model_call(run, model_call(), costs)
        assert len(run.model_call_events()) == 3
        assert run.node_trajectory() == ()

        job = research_job()
        job.status = JobStatus.succeeded
        job.result = "report"
        job.llm_calls = 3
        bridge.observe_job_terminal(run, job)

        fold = fold_trajectory(run.events())
        assert fold.total_llm_calls == job.llm_calls
        assert fold.total_input_tokens == 360
        assert fold.total_output_tokens == 120

    def test_a_priced_call_carries_the_manifests_price_table(self) -> None:
        run = open_run()
        bridge.observe_model_call(run, model_call(cost=0.125))
        usage = run.model_call_events()[0].usage_delta
        assert usage is not None
        assert usage.estimated_cost_usd == "0.125000"
        assert usage.price_table_ref == (
            run.episode.manifest.payload.providers.pricing.table_ref
        )

    def test_the_budget_warning_fires_once_and_only_near_the_ceiling(self) -> None:
        run = open_run()
        costs = RunCosts()
        costs.record("claude-sonnet-4-6", 1, 1, 0.5)
        bridge.observe_model_call(run, model_call(cost=0.5), costs)
        assert not [
            event for event in run.events() if event.event_type == "budget.threshold_reached"
        ]

        costs.record("claude-sonnet-4-6", 1, 1, 1.4)
        bridge.observe_model_call(run, model_call(cost=1.4), costs)
        bridge.observe_model_call(run, model_call(cost=0.01), costs)
        warnings = [
            event for event in run.events() if event.event_type == "budget.threshold_reached"
        ]
        assert len(warnings) == 1
        assert warnings[0].payload["spent"] == "1.900000"

    def test_the_plan_review_pause_is_a_checkpoint_and_a_human_request(self) -> None:
        run = open_run()
        bridge.observe_review_requested(
            run, pause_number=1, pending=("search",), deadline_seconds=600
        )
        bridge.observe_review_answered(run, pause_number=1, action="revise")
        types = [event.event_type for event in run.events()]
        assert types[-3:] == ["checkpoint.saved", "hitl.requested", "hitl.responded"]
        request, responded = run.events()[-2], run.events()[-1]
        assert request.payload["request_kind"] == "plan_review"
        assert responded.payload["response_kind"] == "revise"
        # No plan text anywhere: an edited plan is user-authored.
        assert responded.payload["response_artifact_id"] is None

    def test_an_answer_without_an_open_request_records_nothing(self) -> None:
        run = open_run()
        before = len(run.events())
        bridge.observe_review_answered(run, pause_number=1, action="approve")
        assert len(run.events()) == before


# ---------------------------------------------------------------------------
# Terminal mapping
# ---------------------------------------------------------------------------


class TestTerminalOutcomesMatchTheJobRow:
    @pytest.mark.parametrize(
        ("status", "error_type", "expected"),
        [
            (JobStatus.succeeded, None, "run.completed"),
            (JobStatus.failed, "upstream_model", "run.failed"),
            (JobStatus.cancelled, None, "run.cancelled"),
            (JobStatus.failed, "cost_budget_exceeded", "run.budget_stopped"),
        ],
    )
    def test_each_job_outcome_maps_to_one_terminal_event(
        self, status: JobStatus, error_type: str | None, expected: str
    ) -> None:
        run = open_run(job=research_job(job_id=f"job-{status.value}-{error_type}"))
        job = research_job(job_id=f"job-{status.value}-{error_type}")
        job.status = status
        job.error_type = error_type
        job.result = "a partial report"
        job.cost_usd = 2.0
        bridge.observe_job_terminal(run, job)
        assert fold_trajectory(run.events()).terminal_event_type == expected

    def test_a_cancellation_records_the_request_before_the_outcome(self) -> None:
        run = open_run()
        job = research_job()
        job.status = JobStatus.cancelled
        bridge.observe_job_terminal(run, job)
        assert [event.event_type for event in run.events()][-2:] == [
            "run.cancel_requested",
            "run.cancelled",
        ]

    def test_a_budget_stop_keeps_the_report_the_run_already_paid_for(self) -> None:
        run = open_run()
        job = research_job()
        job.status = JobStatus.failed
        job.error_type = "cost_budget_exceeded"
        job.result = "# Partial report\n"
        job.cost_usd = 2.0
        bridge.observe_job_terminal(run, job)

        types = [event.event_type for event in run.events()]
        assert types[-3:] == ["candidate.created", "budget.exhausted", "run.budget_stopped"]
        stopped = run.events()[-1]
        assert stopped.payload["partial"] is True
        assert stopped.payload["last_good_artifact_id"] is not None

    def test_an_unregistered_failure_code_falls_back_to_the_canonical_one(self) -> None:
        run = open_run()
        job = research_job()
        job.status = JobStatus.failed
        job.error_type = "something_nobody_registered"
        bridge.observe_job_terminal(run, job)
        assert run.events()[-1].payload["failure_class"] == "internal_unexpected"

    def test_a_terminal_event_is_appended_exactly_once(self) -> None:
        run = open_run()
        job = research_job()
        job.status = JobStatus.succeeded
        job.result = "report"
        bridge.observe_job_terminal(run, job)
        count = len(run.events())
        # A second call would try to append past the terminal event; the
        # store refuses and the containment absorbs it.
        bridge.observe_job_terminal(run, job)
        assert run.degraded is True
        assert len(run.events()) == count


# ---------------------------------------------------------------------------
# Failure containment
# ---------------------------------------------------------------------------


class TestFailureContainment:
    def test_a_hook_that_raises_degrades_the_shadow_and_nothing_else(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        run = open_run()

        def _boom(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("the bridge broke")

        monkeypatch.setattr(run, "node_completed", _boom)
        with caplog.at_level("WARNING", logger="src.contracts.shadow_bridge"):
            bridge.observe_node(run, "planner", {})
            bridge.observe_node(run, "search", {})
            bridge.observe_node(run, "reader", {})

        assert run.degraded is True
        # One line, not one per node, and always under the same name.
        warnings = [
            record for record in caplog.records if record.levelname == "WARNING"
        ]
        assert [record.getMessage() for record in warnings] == ["contract_shadow_failed"]
        assert getattr(warnings[0], "hook", None) == "observe_node"

    def test_a_degraded_run_stops_recording_but_keeps_what_it_had(self) -> None:
        run = open_run()
        bridge.observe_node(run, "planner", {})
        run.degraded = True
        bridge.observe_node(run, "search", {})
        bridge.observe_model_call(run, model_call())
        job = research_job()
        job.status = JobStatus.succeeded
        job.result = "report"
        bridge.observe_job_terminal(run, job)
        assert run.node_trajectory() == ("planner",)
        assert fold_trajectory(run.events()).terminal_event_type is None

    def test_every_facade_entry_point_tolerates_a_missing_run(self) -> None:
        bridge.observe_node(None, "planner", {})
        bridge.observe_model_call(None, model_call())
        bridge.observe_review_requested(None, pause_number=1, pending=(), deadline_seconds=1)
        bridge.observe_review_answered(None, pause_number=1, action=None)
        bridge.observe_job_terminal(None, research_job())
        bridge.observe_episode_terminal(None, error=None, report="")
        assert bridge.episode_block(None) is None
        assert bridge.parity_report(None, bridge.legacy_job_outcome(research_job())) == ()

    def test_a_degraded_run_reports_no_parity_verdict_at_all(self) -> None:
        run = open_run()
        run.degraded = True
        assert bridge.parity_report(run, bridge.legacy_job_outcome(research_job())) == ()


# ---------------------------------------------------------------------------
# Registry, parity and record blocks
# ---------------------------------------------------------------------------


class TestTheRegistryAndItsReaders:
    def test_the_registry_is_bounded_and_keeps_the_newest(self) -> None:
        for index in range(bridge.MAX_RETAINED_RUNS + 3):
            open_run(job=research_job(job_id=f"job-{index}"))
        retained = bridge.retained_run_ids()
        assert len(retained) == bridge.MAX_RETAINED_RUNS
        assert retained[-1] == f"job-{bridge.MAX_RETAINED_RUNS + 2}"
        assert bridge.shadow_run(retained[-1]) is not None
        assert bridge.shadow_run("job-0") is None

    def test_a_canned_run_has_zero_parity_mismatches(self) -> None:
        job = research_job()
        run = open_run(job=job)
        for node in FIXED_PIPELINE:
            bridge.observe_node(run, node, {})
        job.status = JobStatus.succeeded
        job.result = "# A cited report [Ji, 2023]\n"
        job.llm_calls = 0
        job.cost_usd = 0.0
        bridge.observe_job_terminal(run, job)

        legacy = bridge.legacy_job_outcome(job)
        state = {"query": job.query, "draft_report": job.result}
        assert bridge.parity_report(run, legacy, state) == ()

    def test_a_corrupted_legacy_row_is_reported_field_by_field(self) -> None:
        job = research_job()
        run = open_run(job=job)
        job.status = JobStatus.succeeded
        job.result = "a report"
        bridge.observe_job_terminal(run, job)

        corrupted = bridge.legacy_job_outcome(job).model_copy(
            update={"llm_calls": 7, "query": "a different question"}
        )
        fields = {item.field for item in bridge.parity_report(run, corrupted)}
        assert fields == {"llm_calls", "objective"}

    def test_the_record_block_is_bounded_ids_and_digests(self) -> None:
        job = research_job()
        run = open_run(job=job)
        job.status = JobStatus.succeeded
        job.result = "# secret-looking report body\n"
        bridge.observe_job_terminal(run, job)

        block = bridge.episode_block(run)
        assert block is not None
        encoded = json.dumps(block)
        assert block["manifest_digest"] == run.episode.manifest_digest
        assert block["arm_id"] == "A"
        assert block["policy_id"] == "research_fixed"
        assert block["terminal_event_type"] == "run.completed"
        assert block["degraded"] is False
        # The report body is addressed, never carried.
        assert "secret-looking report body" not in encoded
        assert job.query not in encoded
        assert len(block["trajectory_jsonl"].splitlines()) == block["event_count"]

    def test_the_block_can_be_asked_for_without_the_export(self) -> None:
        run = open_run()
        job = research_job()
        job.status = JobStatus.succeeded
        job.result = "report"
        bridge.observe_job_terminal(run, job)
        block = bridge.episode_block(run, include_trajectory=False)
        assert block is not None
        assert "trajectory_jsonl" not in block

    def test_an_eval_record_projects_onto_the_same_legacy_view(self) -> None:
        legacy = bridge.legacy_eval_outcome(
            {
                "query": "a benchmark question",
                "error": None,
                "costs": {"total_cost_usd": 0.25, "call_count": 4},
                "state": {"draft_report": "a report"},
            }
        )
        assert legacy.surface == "eval_record"
        assert legacy.status == "succeeded"
        assert legacy.llm_calls == 4
        assert legacy.cost_usd == "0.250000"
        assert legacy.report_digest is not None

        errored = bridge.legacy_eval_outcome({"query": "q", "error": "boom"})
        assert errored.status == "failed"
        assert errored.report_digest is None


# ---------------------------------------------------------------------------
# The scripted campaign's hooks
# ---------------------------------------------------------------------------


class TestScriptedResearchHooks:
    def test_the_hooks_open_stream_and_close_one_episode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg = config()
        # The scripted seam seals before its graph exists, so the shape
        # comes from the cached reader rather than from an app in hand.
        monkeypatch.setattr(
            bridge, "graph_shape", lambda _config: bridge.read_graph_shape(_AppStub())
        )
        hooks = bridge.ScriptedResearchHooks(cfg)
        query = {
            "query_id": "hallucination-mitigation",
            "query": "What reduces hallucination?",
            "domain": "nlp",
            "expected_topics": ["rag", "grounding"],
        }
        ctx = hooks.before_episode(query, 1)
        assert ctx is not None
        for node in FIXED_PIPELINE:
            hooks.on_stream_event(ctx, "updates", {node: {"draft_report": "x"}})
        # `values` chunks carry the whole state and are not node updates.
        hooks.on_stream_event(ctx, "values", {"draft_report": "x"})
        hooks.on_stream_event(ctx, "updates", {"__interrupt__": {}})
        assert ctx.node_trajectory() == FIXED_PIPELINE

        record: dict[str, Any] = {"error": None, "query_id": query["query_id"]}
        before = dict(record)
        hooks.after_episode(ctx, record, {"draft_report": "# report\n"})

        # The seam's rule: `contracts` and nothing else.
        assert set(record) - set(before) == {bridge.CONTRACTS_RECORD_KEY}
        assert all(record[key] is before[key] for key in before)
        assert isinstance(record[bridge.CONTRACTS_RECORD_KEY], dict)
        assert record[bridge.CONTRACTS_RECORD_KEY]["terminal_event_type"] == "run.completed"

    def test_the_hooks_are_inert_without_a_context(self) -> None:
        hooks = bridge.ScriptedResearchHooks(config())
        record: dict[str, Any] = {"error": None}
        hooks.on_stream_event(None, "updates", {"planner": {}})
        hooks.after_episode(None, record, {})
        assert record == {"error": None}

    def test_a_failed_episode_records_a_failure_not_a_completion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run = open_run()
        bridge.observe_episode_terminal(
            run, error="RuntimeError: boom", report="", error_code="upstream_model"
        )
        assert fold_trajectory(run.events()).terminal_event_type == "run.failed"
        assert run.events()[-1].payload["failure_class"] == "upstream_model"


def test_the_bridge_never_writes_user_text_into_a_payload() -> None:
    """A structural sweep: no event payload may contain the query or report."""
    job = research_job()
    run = open_run(job=job)
    for node in FIXED_PIPELINE:
        bridge.observe_node(run, node, {"draft_report": "the report body"})
    bridge.observe_model_call(run, model_call())
    job.status = JobStatus.succeeded
    job.result = "the report body"
    bridge.observe_job_terminal(run, job)

    exported = run.export_jsonl()
    assert job.query not in exported
    assert "the report body" not in exported
