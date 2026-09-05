"""The controller's wiring: the switch, the two graphs, and the effort.

`tests/test_compute_policy.py` proves the decision. This module proves
everything the decision is plugged into, and the claim that carries the
work order is the first one below: **with `COMPUTE_CONTROLLER=off` —
the shipped default — nothing at all is different.** One graph is
compiled, its node and edge listing is the one already on record, and
the kwargs every agent sends are the ones ADR 0077's golden fixture
pins.

The rest of the file is the on-path, in the order a run meets it:

1. the switch, and the three flags it refuses because each of them
   already claims the shape the controller is choosing;
2. the compiled pair — one checkpointer, two shapes, the primary
   unchanged — and what W05's binding calls each of them;
3. `Settings.effort_for`, which is the only place a tier changes what
   goes on the wire;
4. every one of the nine agents naming itself at its call site, so
   CAP-01's per-agent effort fields stop being fields nothing reads.

Zero spend throughout: the graphs are compiled and never executed, and
every agent below is driven against a double.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import src.graph.workflow as workflow_module
from src.agents import assessment as assessment_module
from src.agents import critic as critic_module
from src.agents import planner as planner_module
from src.agents import query_refiner as refiner_module
from src.agents import reader as reader_module
from src.agents import supervisor as supervisor_module
from src.agents import synthesizer as synthesizer_module
from src.agents import tutor as tutor_module
from src.agents import verifier as verifier_module
from src.config import EFFORT_AGENTS, TIER_EFFORT_LEVELS, Settings
from src.config import settings as shipped_settings
from src.contracts.research_binding import classify_policy_shape
from src.graph.session_state import initial_session_state
from src.policies.compute import bind_compute_tier, reset_compute_tier
from tests.test_graph_shape_golden import compile_listing

pytestmark = pytest.mark.unit

#: The flag combination the controller is designed for: it picks the
#: shape, so nothing else may. `enable_evidence_store` is on because it
#: is what makes T0 arm B and T1 arm C rather than arm A and a
#: capability gap — recommended by ADR 0085 and, deliberately, not
#: required by it.
CONTROLLER_ON: dict[str, Any] = {
    "compute_controller": "deterministic",
    "enable_evidence_store": True,
    "enable_checkpointing": False,
}


def configured(**overrides: Any) -> Settings:
    """The shipped settings with `enable_checkpointing` off and overrides.

    Checkpointing is off for the reason `tests/test_graph_shape_golden.py`
    gives: a saver is a connection, not a shape, and leaving it on would
    open a SQLite file per test.
    """
    patched = shipped_settings.model_copy(
        update={"enable_checkpointing": False, **overrides}
    )
    assert isinstance(patched, Settings)
    return patched


@pytest.fixture
def graph_settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Rebind `src.graph.workflow.settings` for one test."""

    def _install(**overrides: Any) -> Settings:
        patched = configured(**overrides)
        monkeypatch.setattr(workflow_module, "settings", patched)
        return patched

    return _install


@pytest.fixture
def built(graph_settings: Callable[..., Settings]) -> Iterator[Callable[..., Any]]:
    """Build a workflow and close its checkpointer stack afterwards."""
    apps: list[Any] = []

    def _build(**overrides: Any) -> Any:
        graph_settings(**overrides)
        app = workflow_module.build_workflow(enable_hitl=False)
        apps.append(app)
        return app

    yield _build
    for app in apps:
        stack = getattr(app, "_checkpointer_exit_stack", None)
        if stack is not None:
            stack.close()


def _nodes(app: Any) -> set[str]:
    return {
        str(name) for name in app.get_graph().nodes if not str(name).startswith("__")
    }


# ---------------------------------------------------------------------------
# 1. Off is today
# ---------------------------------------------------------------------------


class TestTheSwitchOffChangesNothing:
    def test_the_default_is_off(self) -> None:
        assert Settings().compute_controller == "off"
        assert Settings().tier_effort_overrides == {}

    def test_no_second_graph_is_compiled(self, built: Callable[..., Any]) -> None:
        app = built()
        assert workflow_module.compute_tier_graphs(app) is None

    def test_the_compiled_listing_is_the_one_already_on_record(self) -> None:
        """The controller adds no node and no edge to the default graph.

        Read off the same `compile_listing` the golden fixture is
        rendered by, so this is comparing against the committed
        pre-CAP-04 shape rather than against a second opinion.
        """
        golden = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "graph"
            / "legacy-shapes.txt"
        ).read_text(encoding="utf-8")
        listing = compile_listing()
        assert listing in golden
        assert "verify" not in listing

    def test_a_stub_workflow_is_returned_untouched(self) -> None:
        """`compute_tier_graphs` answers "no" for anything it did not build.

        The runner falls back to the graph it was handed on this answer,
        which is what keeps every injected test factory and the guided
        session graph working with the switch in either position.
        """
        assert workflow_module.compute_tier_graphs(object()) is None
        assert workflow_module.compute_tier_graphs(None) is None


# ---------------------------------------------------------------------------
# 2. The switch, and what it refuses
# ---------------------------------------------------------------------------


class TestTheSwitchRefusesASecondClaimantOnTheShape:
    def test_the_controller_loads_on_its_own(self) -> None:
        """No companion flag is required, which is deliberate.

        Arm C refuses to load without its three flags because the
        manifest's *label* depends on them (ADR 0076). This switch does
        not: the classifier reads the graph the controller selected and
        reports it honestly either way, so a refusal here would be
        strictness with nothing to protect.
        """
        assert Settings(compute_controller="deterministic").compute_controller == (
            "deterministic"
        )

    @pytest.mark.parametrize(
        "overrides,expected",
        [
            ({"enable_supervisor": True}, "enable_supervisor must be false"),
            ({"enable_verifier": True}, "enable_verifier must be false"),
            (
                {
                    "research_policy": "fixed_verify_repair",
                    "enable_evidence_store": True,
                },
                "research_policy must be legacy",
            ),
        ],
    )
    def test_a_second_claimant_on_the_shape_is_refused_at_load(
        self, overrides: dict[str, Any], expected: str
    ) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Settings(compute_controller="deterministic", **overrides)
        assert expected in str(excinfo.value)
        assert "ADR 0085" in str(excinfo.value)

    def test_the_refusal_names_every_offending_flag_at_once(self) -> None:
        """One boot attempt has to be enough to fix the whole file."""
        with pytest.raises(ValidationError) as excinfo:
            Settings(
                compute_controller="deterministic",
                enable_supervisor=True,
                enable_verifier=True,
            )
        message = str(excinfo.value)
        assert "enable_supervisor must be false" in message
        assert "enable_verifier must be false" in message


class TestTheTierEffortMapIsCheckedAtLoad:
    @pytest.mark.parametrize(
        "overrides,expected",
        [
            ({"T2.verifier": "high"}, "is not '<tier>.<agent>'"),
            ({"T1.librarian": "high"}, "is not '<tier>.<agent>'"),
            ({"verifier": "high"}, "is not '<tier>.<agent>'"),
            ({"T1.verifier": "off"}, "'off' is not a member"),
            ({"T1.verifier": ""}, "is not one of"),
            # `xhigh` arrived with Opus 4.7; the shipped default model
            # answers a request carrying it with an HTTP 400, which is
            # exactly what ADR 0077 refuses to boot into.
            ({"T1.verifier": "xhigh"}, "is not supported by the routed model"),
        ],
    )
    def test_a_bad_key_or_level_is_refused(
        self, overrides: dict[str, str], expected: str
    ) -> None:
        with pytest.raises(ValidationError) as excinfo:
            Settings(tier_effort_overrides=overrides)
        assert expected in str(excinfo.value)

    def test_a_supported_level_on_a_declared_agent_loads(self) -> None:
        loaded = Settings(tier_effort_overrides={"T1.verifier": "high"})
        assert loaded.tier_effort_overrides == {"T1.verifier": "high"}

    def test_the_map_is_checked_whether_or_not_the_controller_is_on(self) -> None:
        """A map that only failed when someone turned the switch on
        would have moved the error away from the change that caused it."""
        with pytest.raises(ValidationError):
            Settings(compute_controller="off", tier_effort_overrides={"T9.x": "high"})

    def test_off_is_not_a_level_the_map_declares(self) -> None:
        assert "off" not in TIER_EFFORT_LEVELS
        assert "" not in TIER_EFFORT_LEVELS


# ---------------------------------------------------------------------------
# 3. Two shapes, one checkpointer
# ---------------------------------------------------------------------------


class TestTheControllerCompilesBothShapesOnce:
    def test_both_tiers_are_compiled_and_t0_is_the_primary_graph(
        self, built: Callable[..., Any]
    ) -> None:
        """T0 is the graph the deployment would have compiled anyway.

        Reusing it rather than compiling the same edges twice is what
        makes "off is today" and "T0 is today" the same claim.
        """
        app = built(**CONTROLLER_ON)
        graphs = workflow_module.compute_tier_graphs(app)
        assert graphs is not None
        assert set(graphs) == {"T0", "T1"}
        assert graphs["T0"] is app

    def test_the_primary_shape_is_unchanged_by_turning_the_controller_on(
        self,
    ) -> None:
        off = compile_listing(enable_evidence_store=True)
        on = compile_listing(**CONTROLLER_ON)
        assert on == off
        assert "verify" not in on

    def test_the_escalated_shape_is_arm_cs_graph(
        self, built: Callable[..., Any]
    ) -> None:
        graphs = workflow_module.compute_tier_graphs(built(**CONTROLLER_ON))
        assert graphs is not None
        assert _nodes(graphs["T1"]) == {
            "planner",
            "search",
            "reader",
            "synthesizer",
            "verify",
            "repair",
            "critic",
        }
        assert _nodes(graphs["T0"]) == {
            "planner",
            "search",
            "reader",
            "synthesizer",
            "critic",
        }

    def test_one_checkpointer_serves_both_shapes(
        self, graph_settings: Callable[..., Settings], tmp_path: Path
    ) -> None:
        """ADR 0034's leak, closed for the second graph too.

        Two independently built graphs would open two savers — under
        `SqliteSaver`, two writers on one file — so the alternate shape
        is compiled against the primary's checkpointer and the primary
        keeps the only teardown handle.
        """
        graph_settings(
            compute_controller="deterministic",
            enable_evidence_store=True,
            enable_checkpointing=True,
            checkpoint_backend="sqlite",
            checkpoint_db_path=str(tmp_path / "tiers.sqlite"),
        )
        app = workflow_module.build_workflow(enable_hitl=False)
        try:
            graphs = workflow_module.compute_tier_graphs(app)
            assert graphs is not None
            assert graphs["T0"].checkpointer is graphs["T1"].checkpointer
            # One stack, on the primary, which is the object the API
            # lifespan already closes.
            assert getattr(app, "_checkpointer_exit_stack", None) is not None
            assert getattr(graphs["T1"], "_checkpointer_exit_stack", None) is None
        finally:
            app._checkpointer_exit_stack.close()


class TestWhatTheBindingCallsEachShape:
    def test_with_the_evidence_store_on_the_tiers_are_arms_b_and_c(
        self, built: Callable[..., Any]
    ) -> None:
        """The effective policy id follows the *selected graph*.

        Nothing in `src/api/runner.py` names a policy id: W05's binding
        reads the compiled shape it is handed, so selecting T1 for a run
        is what makes that run's manifest say arm C.
        """
        patched = configured(**CONTROLLER_ON)
        graphs = workflow_module.compute_tier_graphs(built(**CONTROLLER_ON))
        assert graphs is not None
        t0 = classify_policy_shape(patched, graphs["T0"])
        t1 = classify_policy_shape(patched, graphs["T1"])
        assert (t0.arm_id, t0.policy_id) == ("B", "research_fixed_evidence")
        assert (t1.arm_id, t1.policy_id) == ("C", "research_fixed_verify_repair")

    def test_without_the_evidence_store_the_classifier_says_so(
        self, built: Callable[..., Any]
    ) -> None:
        """The reason ADR 0085 recommends the flag instead of requiring it.

        A verify graph with no evidence path is not arm C, and the
        binding already refuses to call it one — so the honest record
        exists without this work order adding a refusal of its own.
        """
        overrides = {**CONTROLLER_ON, "enable_evidence_store": False}
        patched = configured(**overrides)
        graphs = workflow_module.compute_tier_graphs(built(**overrides))
        assert graphs is not None
        t0 = classify_policy_shape(patched, graphs["T0"])
        t1 = classify_policy_shape(patched, graphs["T1"])
        assert (t0.arm_id, t0.policy_id) == ("A", "research_fixed")
        assert t1.arm_id is None
        assert t1.policy_id == "research_capability_missing"
        assert "evidence_store" in t1.missing_capabilities


# ---------------------------------------------------------------------------
# 4. The tier reaches the request, and only where it is aimed
# ---------------------------------------------------------------------------


@pytest.fixture
def on_tier() -> Iterator[Callable[[str], None]]:
    """Bind a compute tier for the body of one test."""
    tokens: list[Any] = []

    def _bind(tier: str) -> None:
        tokens.append(bind_compute_tier(tier))  # type: ignore[arg-type]

    yield _bind
    for token in reversed(tokens):
        reset_compute_tier(token)


class TestTheTierOverrideReachesOneAgentAndNoOther:
    def test_no_tier_bound_means_the_adr_0077_answer(self) -> None:
        loaded = Settings(tier_effort_overrides={"T1.verifier": "high"})
        assert loaded.effort_for("verifier") == ""
        assert loaded.effort_for("planner") == ""

    def test_a_bound_tier_raises_only_the_agent_the_key_names(
        self, on_tier: Callable[[str], None]
    ) -> None:
        loaded = Settings(tier_effort_overrides={"T1.verifier": "high"})
        on_tier("T1")
        assert loaded.effort_for("verifier") == "high"
        for agent in EFFORT_AGENTS:
            if agent != "verifier":
                assert loaded.effort_for(agent) == ""
        # And nothing at all for a call that carries no agent identity.
        assert loaded.effort_for() == ""

    def test_the_override_applies_only_on_the_tier_it_names(
        self, on_tier: Callable[[str], None]
    ) -> None:
        loaded = Settings(tier_effort_overrides={"T1.verifier": "high"})
        on_tier("T0")
        assert loaded.effort_for("verifier") == ""

    def test_the_tier_outranks_the_agent_field_and_the_global(
        self, on_tier: Callable[[str], None]
    ) -> None:
        loaded = Settings(
            llm_effort="low",
            verifier_effort="medium",
            tier_effort_overrides={"T1.verifier": "high"},
        )
        on_tier("T1")
        assert loaded.effort_for("verifier") == "high"
        # The agent field still governs an agent the map does not name.
        assert loaded.effort_for("planner") == "low"

    def test_an_empty_map_never_consults_the_tier_at_all(
        self, on_tier: Callable[[str], None]
    ) -> None:
        """The default path, asserted with a tier bound anyway.

        Two independent defaults have to fail before an escalated run's
        request changes: the controller has to be on *and* the map has to
        name the agent.
        """
        loaded = Settings(verifier_effort="medium")
        on_tier("T1")
        assert loaded.effort_for("verifier") == "medium"
        assert loaded.tier_effort_for("verifier") == ""


# ---------------------------------------------------------------------------
# 5. Every agent names itself
# ---------------------------------------------------------------------------


def _research_state(**overrides: Any) -> Any:
    """The slice of `ResearchState` the seven research agents read."""
    base: dict[str, Any] = {
        "run_id": "cap04",
        "query": "Q?",
        "sub_questions": ["a"],
        "search_queries": ["q"],
        "papers": [],
        "paper_analyses": [
            {
                "paper_id": "p1",
                "title": "T",
                "key_findings": ["k"],
                "methodology": "m",
                "results_summary": "r",
                "limitations": "l",
                "relevance": 0.5,
            }
        ],
        "draft_report": "body [Smith, 2023].",
        "citations": [
            {
                "paper_id": "p1",
                "title": "T",
                "authors": ["Jane Smith"],
                "year": "2023",
                "url": "",
            }
        ],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "tried_search_queries": [],
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "messages": [],
    }
    base.update(overrides)
    return base


def _session_state(**overrides: Any) -> Any:
    state = initial_session_state(
        {
            "principal_key_id": "alice",
            "tier1": {"time_budget_min_per_day": 25},
            "session_spec": {
                "available_minutes": 25,
                "title": "Attention Is All You Need",
                "reading_guidance": [{"name": "Method", "mode": "close"}],
            },
        },
        "cap04-session",
        "Guided read",
    )
    state["session_plan"] = {"sections": [{"name": "Method", "mode": "close"}]}
    state["turn_number"] = 3
    state["learner_reply"] = "It removes recurrence."
    state.update(overrides)
    return state


#: Every response field any of the nine agents reads, unioned, so one
#: double serves all of them — the shape `tests/test_agent_model_routing.py`
#: already uses for the same reason.
_UNION_RESPONSE: dict[str, Any] = {
    "sub_questions": ["s"],
    "search_queries": ["q"],
    "key_findings": ["k"],
    "methodology": "m",
    "results_summary": "r",
    "limitations": "l",
    "relevance": 0.5,
    "draft_report": "body",
    "citations": [],
    "scores": {
        "completeness": 0.9,
        "accuracy": 0.9,
        "citation_quality": 0.9,
        "clarity": 0.9,
    },
    "critique": "fine",
    "revision_needed": False,
    "revision_target": "",
    "verified": True,
    "unsupported_claims": [],
    "missing_evidence": [],
    "recommended_action": "",
    "reason": "ok",
    "next_action": "stop",
    "stop_reason": "supervisor_stop",
    "queries": ["q1", "q2"],
    "feedback": "good",
    "prompt": "what next?",
    "sections": [{"name": "Method", "mode": "close"}],
    "gaps": [],
    "strengths": [],
    "follow_up_probe": "Where does order come from?",
    "evidence": [],
}


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[str]:
    """Record the `agent=` every call from `module` carries."""
    seen: list[str] = []

    def fake(**kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs.get("agent", "<missing>"))
        return dict(_UNION_RESPONSE)

    monkeypatch.setattr(module, "call_llm_json", fake)
    return seen


def _drive_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass PDF, chunk and rank so the reader reaches its model call."""
    monkeypatch.setattr(reader_module, "parse_pdf", lambda _url: "full text")
    monkeypatch.setattr(
        reader_module,
        "chunk_paper",
        lambda _t: [{"section": "method", "text": "m", "chunk_index": 0}],
    )
    monkeypatch.setattr(
        reader_module,
        "rank_chunks_by_relevance",
        lambda _c, _s, top_k, preferred_sections=None: [
            {
                "section": "method",
                "text": "method body",
                "chunk_index": 0,
                "relevance_score": 0.9,
            }
        ],
    )
    reader_module._analyze_paper(
        {
            "id": "p",
            "title": "T",
            "authors": ["A"],
            "abstract": "abs",
            "url": "",
            "pdf_url": "",
        },
        "Q?",
        ["a"],
    )


#: `(agent name, module, how to reach its `call_llm_json` call site)`.
#: One row per member of `src.config.EFFORT_AGENTS`; the test below
#: asserts the two lists agree, so an agent added to the settings
#: without a call site — or the reverse — fails here rather than
#: shipping a field nothing reads.
AGENT_DRIVERS: tuple[tuple[str, Any, Callable[[pytest.MonkeyPatch], None]], ...] = (
    ("planner", planner_module, lambda _m: planner_module.planner_agent(_research_state())),
    ("reader", reader_module, _drive_reader),
    (
        "synthesizer",
        synthesizer_module,
        lambda _m: synthesizer_module.synthesizer_agent(_research_state()),
    ),
    ("critic", critic_module, lambda _m: critic_module.critic_agent(_research_state())),
    (
        "verifier",
        verifier_module,
        lambda _m: verifier_module.verifier_agent(_research_state()),
    ),
    (
        "supervisor",
        supervisor_module,
        lambda _m: supervisor_module.supervisor_agent(_research_state()),
    ),
    (
        "query_refiner",
        refiner_module,
        lambda _m: refiner_module.query_refiner_agent(_research_state()),
    ),
    ("tutor", tutor_module, lambda _m: tutor_module.tutor_agent(_session_state())),
    (
        "assessment",
        assessment_module,
        lambda _m: assessment_module.assessment_judge(_session_state()),
    ),
)


class TestEveryCallSiteNamesItsAgent:
    def test_the_driver_table_covers_exactly_the_effort_agents(self) -> None:
        assert tuple(name for name, _, _ in AGENT_DRIVERS) == EFFORT_AGENTS

    @pytest.mark.parametrize(
        "name,module,drive", AGENT_DRIVERS, ids=[row[0] for row in AGENT_DRIVERS]
    )
    def test_the_agent_reaches_the_gateway_under_its_own_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        module: Any,
        drive: Callable[[pytest.MonkeyPatch], None],
    ) -> None:
        """CAP-01 landed nine `<agent>_effort` fields no call site passed.

        This is the assertion that closes that: the effort an operator
        sets for the reader has to reach the reader's request, and it can
        only do that if the reader's call names itself.
        """
        monkeypatch.setattr(
            module, "settings", configured(use_mock_data=False, enable_prompt_isolation=True)
        )
        seen = _spy(monkeypatch, module)
        drive(monkeypatch)
        assert seen, f"{name} never reached call_llm_json"
        assert set(seen) == {name}

    def test_the_tutor_names_itself_on_its_second_call_site_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one agent with two call sites, so both are pinned."""
        monkeypatch.setattr(tutor_module, "settings", configured(use_mock_data=False))
        seen = _spy(monkeypatch, tutor_module)
        tutor_module.check_in_agent(_session_state())
        assert set(seen) == {"tutor"}


class TestTheGatewayCarriesTheAgentThrough:
    def test_call_llm_json_forwards_the_agent_to_call_llm(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The link between a call site and `resolve_profile`.

        Asserted on `src.llm.call_llm` rather than on the request body
        because the body only differs once an effort is configured —
        this is the plumbing, and `TestTheTierOverrideReachesOneAgent`
        above is what it plumbs.
        """
        from src import llm as llm_module

        seen: dict[str, Any] = {}

        def fake(*args: Any, **kwargs: Any) -> str:
            seen.update(kwargs)
            return "{}"

        monkeypatch.setattr(llm_module, "call_llm", fake)
        llm_module.call_llm_json("p", agent="verifier")
        assert seen["agent"] == "verifier"

    def test_the_default_profile_sends_no_effort_for_any_agent(self) -> None:
        """Golden, restated where a reader of this file will look for it.

        `tests/test_llm_request_golden.py` pins the request body; this
        pins the resolution that feeds it, for every agent at once, so
        "flags off is byte-identical" has an assertion per agent rather
        than one for the gateway's anonymous call.
        """
        from src.llm import resolve_profile

        loaded = Settings()
        for agent in EFFORT_AGENTS:
            assert loaded.effort_for(agent) == ""
            assert resolve_profile(loaded.model_for(agent), agent).effort == ""
