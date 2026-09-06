"""The campaign execution loop, at zero cost (P0-WO07b).

`docs/agent-engineering/15-stage0-qualification-report.md` §7.2 named one
remaining code item before a funded baseline could be requested: W07
planned, locked, sealed and reconciled a campaign and never *ran* one.
This module is the evidence that it now does, and every claim it makes is
measured rather than declared.

Five groups, in the order the work order asks for them.

1. **The full runnable matrix.** 20 queries x 3 repeats x arms A-E = 300
   episodes end to end under mock mode, with nothing excluded. That last
   clause is CAP-09's (ADR 0091): until arm E had a listwise selector and
   a marginal-stop rule it was `capability_missing`, its 60 slots entered
   the ledger as excluded-with-reason, and this module asserted the
   exclusion "so the gap closes loudly". It closed. The ledger now
   reconciles 300 completed, 0 excluded and nothing else; every episode
   reports `llm_calls=0`; the campaign's total is exactly `$0.000000`;
   and a counting spy installed over `src.llm._get_client` — *and* one
   over `socket.socket.connect` — stays empty for the whole pass.
2. **Resume.** An interrupted campaign skips what finished, never
   rewrites an episode directory, and appends a second attempt to an
   episode whose manifest was sealed and whose receipt was not.
3. **The budget stop.** A cap smaller than the matrix stops the campaign
   between episodes with the unrun slots still in the denominator;
   resuming under the same cap continues; raising the cap is refused and
   the remedy is a new campaign with lineage.
4. **Admission.** A metered provider is refused before the credential is
   read when no approval record covers the campaign, admitted when one
   does, and never admitted by the presence of an API key alone.
5. **Denominators.** Injected errors, cancellations, timeouts and null
   metrics land in their own ledger buckets and stay in the denominator.

Nothing here is canned. Group 1 drives the real compiled graph for every
one of the 300 episodes; the fault-injection groups use a scripted runner
because the property under test is the *loop's* accounting, and a graph
that cannot be made to time out on demand would not test it.
"""

from __future__ import annotations

import json
import logging
import socket
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import src.llm as llm_module
from src.campaign.approval import (
    LocalApprovalRecordBackend,
    NoCredentialProbe,
    campaign_approval_record,
)
from src.campaign.arms import ARM_IDS, ArmId
from src.campaign.errors import CampaignError
from src.campaign.execute import (
    COMPLETION_FILENAME,
    PRIMARY_METRIC,
    PROJECTION_FILENAME,
    RECORD_FILENAME,
    SCORES_FILENAME,
    TRAJECTORY_FILENAME,
    CampaignRunReport,
    EpisodeRecord,
    EpisodeRun,
    EpisodeScores,
    aggregate_by_task,
    arm_graph_probe,
    execute_campaign,
    load_episode_records,
)
from src.campaign.ledger import EpisodeScoreReceipt, LedgerStatus
from src.campaign.manifest import CampaignLineage
from src.campaign.matrix import PlannedEpisode
from src.campaign.planner import (
    CampaignPlan,
    CampaignRequest,
    default_campaign_budget,
    default_episode_budget,
    plan_campaign,
    rebuild_plan,
    resume_campaign,
    write_campaign,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.registry import (
    IntendedUse,
    LocalRegistry,
    RegistryRole,
    TaskSet,
)
from src.contracts.run_manifest import CompletionReceipt, CompletionStatus, RunReason
from src.contracts.trajectory import import_jsonl, verify_trajectory
from src.observability.logging import (
    _STANDARD_LOG_KEYS,
    ALLOWED_EXTRA_KEYS,
    KNOWN_EVENTS,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_ROOT = REPO_ROOT / "eval_registry"
SUITE_ID = "research-policy-v1"

#: 07 §5's full v1 design, spelled out rather than read off the plan: a
#: test that took its expectation from the object under test would agree
#: with any matrix.
FULL_SUITE_CASES = 20
FULL_SUITE_REPEATS = 3
#: Every arm is runnable since CAP-09 (ADR 0091). Kept as its own name
#: rather than replaced by `ARM_IDS` so that the day an arm is declared
#: before it is built, the two counts separate again without this module
#: having to rediscover that it needs them.
RUNNABLE_ARMS: tuple[ArmId, ...] = ARM_IDS
EXPECTED_EPISODES = FULL_SUITE_CASES * FULL_SUITE_REPEATS * len(ARM_IDS)
PLANNED_EPISODES = FULL_SUITE_CASES * FULL_SUITE_REPEATS * len(RUNNABLE_ARMS)
EXCLUDED_EPISODES = EXPECTED_EPISODES - PLANNED_EPISODES

#: A two-case slice for everything that is not the full-matrix claim.
SLICE_CASES: tuple[str, ...] = ("hallucination-mitigation", "rag-multi-hop")

#: The report a scripted runner hands back. Deliberately free of the
#: phrase `chain-of-thought`, which W11-F1 records the artifact store as
#: refusing — this module is not the place to re-litigate that finding.
SCRIPTED_REPORT = "# Briefing\n\nA scripted result for one campaign slot.\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def config(**overrides: Any) -> Settings:
    """The shipped settings on a mock, no-cost, durably-recorded surface."""
    base: dict[str, Any] = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_checkpointing": False,
        "enable_semantic_scholar": False,
        "enable_hitl": False,
        "contract_shadow": "shadow",
        "contract_event_capture": "evaluation_only",
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def registry() -> LocalRegistry:
    return LocalRegistry(REGISTRY_ROOT)


def suite_case_ids() -> tuple[str, ...]:
    """The suite's own case order, read from the registry as an evaluator."""
    suite = registry().resolve(
        suite_ref(REGISTRY_ROOT, SUITE_ID),
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    task_set = registry().resolve(
        suite.task_set_ref,
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    assert isinstance(task_set, TaskSet)
    return tuple(ref.id for ref in task_set.case_refs)


def request(
    cfg: Settings,
    *,
    cases: Sequence[str] | None = None,
    arms: tuple[ArmId, ...] = ARM_IDS,
    repeats: int = FULL_SUITE_REPEATS,
    **overrides: Any,
) -> CampaignRequest:
    base = CampaignRequest(
        protocol_id="research-policy-v1-stage-0",
        stage="stage-0-qualification",
        suite_ref=suite_ref(REGISTRY_ROOT, SUITE_ID),
        case_ids=tuple(cases) if cases is not None else suite_case_ids(),
        arms=arms,
        repeats=repeats,
        corpus_mode="snapshot",
        seed=0,
        episode_budget=default_episode_budget(cfg, arms),
        campaign_budget=default_campaign_budget(),
    )
    if not overrides:
        return base
    patched = base.model_copy(update=overrides)
    assert isinstance(patched, CampaignRequest)
    return patched


def materialize(root: Path, cfg: Settings, req: CampaignRequest) -> CampaignPlan:
    """Plan and write a campaign, then rebuild it exactly as `run` would."""
    plan = plan_campaign(cfg, req, resolver=registry())
    write_campaign(root, plan)
    manifest, specs = plan.manifest, plan.task_specs
    return rebuild_plan(manifest, specs)


@dataclass
class ProviderTripwire:
    """A counting spy over the two doors a paid call would have to open.

    Installed *over* `tests/conftest.py`'s ambient guards rather than in
    place of them, and the difference is the whole claim: a guard proves
    that nothing escaped, a spy proves that the code path was never
    taken. Five of the six agents on the research path swallow
    `Exception`, so a guard that fired would still leave a report behind.
    """

    clients: list[str]
    connects: list[str]

    @property
    def touched(self) -> list[str]:
        return [*self.clients, *self.connects]


def install_tripwire(patch: pytest.MonkeyPatch) -> ProviderTripwire:
    tripwire = ProviderTripwire(clients=[], connects=[])
    patch.setattr(llm_module, "_get_client", lambda: tripwire.clients.append("client"))
    patch.setattr(
        socket.socket, "connect", lambda *_a, **_k: tripwire.connects.append("connect")
    )
    return tripwire


class ScriptedRunner:
    """An `EpisodeRunner` that returns what it was told to, per arm.

    The loop's accounting is what these tests are about, and a real graph
    cannot be asked to time out, be cancelled or cost a dollar on demand
    without either a network or a lie. So the faults are scripted and the
    *loop* is real: it still seals a manifest, opens a trajectory, writes
    every artifact and reconciles a ledger for each scripted outcome.
    """

    def __init__(
        self,
        *,
        status: CompletionStatus = CompletionStatus.SUCCEEDED,
        reason: RunReason | None = None,
        report: str = SCRIPTED_REPORT,
        workflow_cost_usd: str = "0.000000",
        model_calls: int = 0,
        per_arm: Mapping[str, tuple[CompletionStatus, RunReason | None]] | None = None,
    ) -> None:
        self.status = status
        self.reason = reason
        self.report = report
        self.workflow_cost_usd = workflow_cost_usd
        self.model_calls = model_calls
        self.per_arm = dict(per_arm or {})
        self.calls: list[str] = []

    def __call__(
        self,
        config: Settings,
        *,
        episode: PlannedEpisode,
        objective: str,
        run_id: str,
        on_node: Any,
    ) -> EpisodeRun:
        del config, objective, run_id
        self.calls.append(f"{episode.case_id}/{episode.arm_id}")
        status, reason = self.per_arm.get(episode.arm_id, (self.status, self.reason))
        on_node("planner")
        on_node("synthesizer")
        return EpisodeRun(
            status=status,
            reason=reason,
            visited=("planner", "synthesizer"),
            state={"draft_report": self.report, "papers": [], "citations": []},
            workflow_cost_usd=self.workflow_cost_usd,
            model_calls=self.model_calls,
            elapsed_seconds=0.0,
        )


def available_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    """Score every episode as having produced its primary metric.

    Used where the *scoring* is not the property under test. The real
    default scorer would call a scripted report with no citations a null
    metric, which is correct and would drown the bucket being asserted.
    """
    del run
    return EpisodeScores(
        receipt=EpisodeScoreReceipt(run_id=episode.run_id, primary_metric_available=True),
        primary_metric=PRIMARY_METRIC,
        primary_score=1.0,
        detail={"scripted": True},
    )


def null_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    """Score every episode as complete-but-unmeasured."""
    del run
    return EpisodeScores(
        receipt=EpisodeScoreReceipt(
            run_id=episode.run_id,
            primary_metric_available=False,
            null_reason="scripted null metric",
        ),
        primary_metric=PRIMARY_METRIC,
        primary_score=None,
        detail={"scripted": True},
    )


def read_record(directory: Path, episode: PlannedEpisode) -> EpisodeRecord:
    path = directory / episode.output_path / RECORD_FILENAME
    return EpisodeRecord.model_validate_json(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. The full runnable matrix, at exactly zero
# ---------------------------------------------------------------------------


@dataclass
class MatrixRun:
    """One executed full matrix, shared by the assertions about it."""

    report: CampaignRunReport
    plan: CampaignPlan
    directory: Path
    tripwire: ProviderTripwire


@pytest.fixture(scope="module")
def full_matrix(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MatrixRun]:
    """Run 20 x 3 x 5 once, through the real graph, and share the result.

    Module-scoped because the pass costs seconds and every assertion
    below is about the *same* pass; running it per test would be four
    identical campaigns. The tripwire is installed inside this fixture
    rather than relying on the per-test guards, because a module-scoped
    fixture is set up before them and the measurement has to cover the
    whole pass.
    """
    root = tmp_path_factory.mktemp("campaign-full-matrix")
    with pytest.MonkeyPatch.context() as patch:
        tripwire = install_tripwire(patch)
        cfg = config()
        plan = materialize(root, cfg, request(cfg))
        report = execute_campaign(
            cfg,
            root=root,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            sink_root=root / "trajectories",
        )
        yield MatrixRun(
            report=report,
            plan=plan,
            directory=root / plan.campaign_id,
            tripwire=tripwire,
        )


class TestTheFullMatrixRunsAtZeroCost:
    #: `integration`, not `e2e`: `tests/test_documented_claims.py::
    #: TestTheE2eTier::test_the_marker_and_the_directory_are_the_same_set`
    #: requires every `e2e`-marked module to live under `tests/e2e/`,
    #: whose module and test counts README.md pins as equalities. The
    #: precedent for a whole-graph run in the flat tree is
    #: `tests/test_stage0_qualification.py`, and staying here also keeps
    #: this evidence inside the coverage selection, which `-m "not e2e"`
    #: would otherwise drop.
    pytestmark = [pytest.mark.integration, pytest.mark.contract]

    # The measured pass is ~16s locally against a 60s per-test ceiling.
    # Raised for this one test rather than globally: a loaded CI runner
    # that is 3x slower should report a result, not a timeout, and every
    # other test in this module is fast.
    @pytest.mark.timeout(300)
    def test_every_planned_episode_runs_and_the_ledger_accounts_for_all_three_hundred(
        self, full_matrix: MatrixRun
    ) -> None:
        report = full_matrix.report
        assert report.attempted == PLANNED_EPISODES
        assert report.completed == PLANNED_EPISODES
        assert report.pending_after == 0
        assert report.stop_reason == "completed"
        assert report.counts == {
            "not_started": 0,
            "completed": PLANNED_EPISODES,
            "errored": 0,
            "cancelled": 0,
            "timed_out": 0,
            "budget_stopped": 0,
            "null_metric": 0,
            "excluded": EXCLUDED_EPISODES,
        }
        denominators = report.summary.denominators
        assert denominators.expected == EXPECTED_EPISODES
        assert denominators.accounted == EXPECTED_EPISODES
        assert denominators.analysis_denominator == PLANNED_EPISODES

    def test_the_campaign_spent_nothing_and_made_no_model_call(
        self, full_matrix: MatrixRun
    ) -> None:
        """The claim this whole work order exists to make, measured twice.

        Once in aggregate — the summary's three cost categories are each
        exactly zero — and once per episode, because an aggregate of 300
        rounded numbers could hide a small one.
        """
        costs = full_matrix.report.summary.costs
        assert (costs.workflow_usd, costs.judge_usd, costs.harness_usd) == (
            "0.000000",
            "0.000000",
            "0.000000",
        )
        assert costs.total_usd == "0.000000"
        assert full_matrix.report.model_calls == 0

        records = load_episode_records(full_matrix.directory, full_matrix.plan)
        assert len(records) == PLANNED_EPISODES
        assert {record.model_calls for record in records} == {0}
        assert {record.workflow_cost_usd for record in records} == {"0.000000"}
        assert {record.judge_cost_usd for record in records} == {"0.000000"}
        assert {record.judge_model_calls for record in records} == {0}

    def test_no_provider_client_was_constructed_and_no_socket_was_opened(
        self, full_matrix: MatrixRun
    ) -> None:
        assert full_matrix.tripwire.touched == []

    def test_arm_e_contributed_sixty_run_slots_and_nothing_was_excluded(
        self, full_matrix: MatrixRun
    ) -> None:
        """The assertion this module used to make, inverted by CAP-09.

        It read `test_arm_e_contributed_sixty_excluded_slots_with_a_typed_reason`
        and it was right to: nothing in this repository selected a
        candidate listwise or decided a marginal stop, so arm E's sixty
        slots could only be excluded-with-reason. ADR 0091 built both,
        `UNRUNNABLE_ARMS` emptied, and the same sixty slots now run —
        under the deterministic compute controller with the branch tier
        available to it as T2, at exactly the same zero cost as every
        other arm, because the mock selector makes no model call.
        """
        ledger = json.loads(
            (full_matrix.directory / "campaign-ledger.json").read_text(encoding="utf-8")
        )
        assert [
            entry for entry in ledger["entries"] if entry["status"] == "excluded"
        ] == []

        arm_e = [
            episode for episode in full_matrix.plan.runnable if episode.arm_id == "E"
        ]
        assert len(arm_e) == FULL_SUITE_CASES * FULL_SUITE_REPEATS
        # And every one of them has a directory with a terminal receipt:
        # a runnable episode is one that ran, not one that was planned.
        for episode in arm_e:
            target = full_matrix.directory / episode.output_path
            assert (target / COMPLETION_FILENAME).is_file()

    def test_arm_e_sealed_a_manifest_naming_the_arm_and_its_bounds(
        self, full_matrix: MatrixRun
    ) -> None:
        """RFC 09 §7.2's arm-E snapshot, read off a sealed episode.

        The tiers, the router version, the branch cap, the selection
        method and the marginal-stop version are *manifest inputs* —
        which tier a given episode actually selected is a runtime fact
        RFC 09 keeps out of the snapshot on purpose, so this asserts the
        inputs and nothing about the routing.
        """
        episode = next(
            item for item in full_matrix.plan.runnable if item.arm_id == "E"
        )
        target = full_matrix.directory / episode.output_path
        manifest = json.loads(
            (target / "run-manifest.json").read_text(encoding="utf-8")
        )
        policy = manifest["payload"]["policy"]
        assert policy["policy_kind"] == "research_arm"
        assert policy["arm_id"] == "E"
        assert policy["selector"] == "adaptive_verified"
        assert policy["capabilities"]["adaptive_compute"] is True
        assert policy["runtime_flags"]["enable_supervisor"] is False
        assert policy["config"]["allowed_tiers"] == ["T0", "T1", "T2"]
        assert policy["config"]["selection"] == "listwise"
        assert policy["config"]["marginal_stop_policy_version"] == "1.0.0"
        assert {
            "adaptive_compute_router",
            "candidate_branching",
            "candidate_lineage_selector",
            "marginal_stop",
        } <= set(policy["graph_capabilities"])

    def test_every_episode_wrote_the_files_rfc_09_requires(
        self, full_matrix: MatrixRun
    ) -> None:
        """RFC 09 §5.3's episode layout, checked on a sample of one per arm.

        One per arm rather than all 300: the writer is the same code
        path for every slot, and the arms differ in what the *graph*
        does, which is what the sample is chosen along.
        """
        for arm in RUNNABLE_ARMS:
            episode = next(
                item for item in full_matrix.plan.runnable if item.arm_id == arm
            )
            target = full_matrix.directory / episode.output_path
            for name in (
                "run-manifest.json",
                "run-manifest.sha256",
                PROJECTION_FILENAME,
                "policy-runtime-projection.sha256",
                TRAJECTORY_FILENAME,
                "trajectory-ref.json",
                "verification.jsonl",
                "artifacts/index.json",
                RECORD_FILENAME,
                SCORES_FILENAME,
                COMPLETION_FILENAME,
            ):
                assert (target / name).is_file(), f"arm {arm} is missing {name}"
            assert list((target / "attempts").glob("att_*.json"))

    def test_each_episodes_trajectory_verifies_against_the_durable_sink(
        self, full_matrix: MatrixRun
    ) -> None:
        """The ledger on disk, read back with nothing from the live run."""
        for arm in RUNNABLE_ARMS:
            episode = next(
                item for item in full_matrix.plan.runnable if item.arm_id == arm
            )
            target = full_matrix.directory / episode.output_path
            events = import_jsonl(
                (target / TRAJECTORY_FILENAME).read_text(encoding="utf-8")
            )
            verify_trajectory(events)
            assert events[0].event_type == "run.admitted"
            assert events[-1].event_type == "budget.reconciled"

            ref = json.loads((target / "trajectory-ref.json").read_text(encoding="utf-8"))
            assert ref["durable"] is True
            assert ref["event_count"] == len(events)
            assert ref["head_event_hash"] == events[-1].event_hash
            sink_events = Path(ref["run_directory"]) / ref["events_file"]
            assert sink_events.is_file()
            assert import_jsonl(sink_events.read_text(encoding="utf-8")) == events

    def test_the_completion_receipt_binds_the_manifest_the_episode_sealed(
        self, full_matrix: MatrixRun
    ) -> None:
        """A receipt that named a different manifest would prove nothing."""
        for episode in full_matrix.plan.runnable[:8]:
            target = full_matrix.directory / episode.output_path
            receipt = CompletionReceipt.model_validate_json(
                (target / COMPLETION_FILENAME).read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (target / "run-manifest.json").read_text(encoding="utf-8")
            )
            assert receipt.run_id == episode.run_id
            assert receipt.manifest_digest == manifest["integrity"]["payload_sha256"]
            assert receipt.status is CompletionStatus.SUCCEEDED
            assert receipt.reason is None

    def test_the_arms_ran_the_graphs_their_manifests_declared(
        self, full_matrix: MatrixRun
    ) -> None:
        """The node route per arm, read off the records rather than the run.

        Arm A and B share the fixed pipeline; arm C adds the verify
        stage CAP-02 compiles for it; arm D alternates with the
        supervisor. A campaign whose arms all took the same route would
        be four samples of one policy.
        """
        routes: dict[str, set[tuple[str, ...]]] = {}
        for record in load_episode_records(full_matrix.directory, full_matrix.plan):
            routes.setdefault(record.arm_id, set()).add(tuple(record.node_route))
        assert routes["A"] == {("planner", "search", "reader", "synthesizer", "critic")}
        assert routes["B"] == routes["A"]
        assert all("verify" in route for route in routes["C"])
        assert all(route[0] == "supervisor" for route in routes["D"])

    def test_repeats_are_aggregated_by_task_through_the_stats_module(
        self, full_matrix: MatrixRun
    ) -> None:
        """One row per (case, arm), not one per episode.

        `src/eval/regression_diff.py` already says why: three repeats
        per task diffed row-by-row compares `r1` to `r1`, which is an
        arbitrary pairing. The interval and the reliability statistic
        come from `src/eval/stats.py`; nothing in `src/campaign/`
        computes either.
        """
        records = load_episode_records(full_matrix.directory, full_matrix.plan)
        rows = aggregate_by_task(records)
        assert len(rows) == FULL_SUITE_CASES * len(RUNNABLE_ARMS)
        assert {row.repeats for row in rows} == {FULL_SUITE_REPEATS}
        for row in rows:
            assert row.scored == FULL_SUITE_REPEATS
            assert row.interval is not None
            assert 0.0 <= row.interval[0] <= row.interval[1] <= 1.0
            assert row.pass_hat_k is not None

        from src.eval.stats import pass_hat_k, wilson_interval

        sample = rows[0]
        assert sample.pass_hat_k == pass_hat_k(
            sample.successes, sample.scored, sample.scored
        )
        assert sample.interval == tuple(wilson_interval(sample.successes, sample.scored))

    def test_a_second_pass_runs_nothing_and_overwrites_nothing(
        self, full_matrix: MatrixRun
    ) -> None:
        """Idempotence, which is also the property resume rests on."""
        before = {
            path: path.stat().st_mtime_ns
            for path in sorted(full_matrix.directory.rglob(COMPLETION_FILENAME))
        }
        again = execute_campaign(
            config(),
            root=full_matrix.directory.parent,
            plan=full_matrix.plan,
            graph_probe=arm_graph_probe(config()),
            sink_root=full_matrix.directory.parent / "trajectories",
        )
        assert again.attempted == 0
        assert again.skipped_already_complete == PLANNED_EPISODES
        assert again.counts["completed"] == PLANNED_EPISODES
        after = {
            path: path.stat().st_mtime_ns
            for path in sorted(full_matrix.directory.rglob(COMPLETION_FILENAME))
        }
        assert after == before


# ---------------------------------------------------------------------------
# 2. Resume
# ---------------------------------------------------------------------------


class TestKillAndResume:
    pytestmark = [pytest.mark.integration, pytest.mark.contract]

    def test_a_resumed_campaign_skips_what_finished_and_finishes_the_rest(
        self, tmp_path: Path
    ) -> None:
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES, arms=("A", "B"), repeats=2)
        )
        directory = tmp_path / plan.campaign_id
        probe = arm_graph_probe(cfg)

        first = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=probe,
            sink_root=tmp_path / "trajectories",
            max_episodes=3,
        )
        assert first.attempted == 3
        assert first.stop_reason == "episode_limit_reached"
        assert first.counts["not_started"] == 5
        finished = {
            path.parent
            for path in directory.rglob(COMPLETION_FILENAME)
        }
        stamps = {path: path.stat().st_mtime_ns for path in sorted(finished)}

        # The kill: a fresh plan object rebuilt from disk, exactly as the
        # `run` verb does it in a second process.
        reopened, pending = resume_campaign(tmp_path, campaign_id=plan.campaign_id)
        assert len(pending) == 5

        second = execute_campaign(
            cfg,
            root=tmp_path,
            plan=reopened,
            graph_probe=probe,
            sink_root=tmp_path / "trajectories",
        )
        assert second.attempted == 5
        assert second.skipped_already_complete == 3
        assert second.pending_after == 0
        assert second.counts["completed"] == 8
        assert second.counts["not_started"] == 0
        assert {
            path: path.stat().st_mtime_ns for path in sorted(stamps)
        } == stamps, "a completed episode's receipt was rewritten"

    def test_an_interrupted_episode_appends_an_attempt_and_keeps_its_manifest(
        self, tmp_path: Path
    ) -> None:
        """RFC 09 §11.3: a sealed manifest with no receipt is resumable.

        Not a repeat and not a rerun — the run id does not move, the
        directory does not move, and the sealed manifest is not written
        twice. What a second attempt adds is a second attempt receipt.
        """
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        directory = tmp_path / plan.campaign_id
        probe = arm_graph_probe(cfg)
        execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=probe,
            sink_root=tmp_path / "trajectories",
        )
        episode = plan.runnable[0]
        target = directory / episode.output_path
        manifest_before = (target / "run-manifest.json").read_bytes()
        first_attempts = sorted(path.name for path in (target / "attempts").iterdir())
        assert len(first_attempts) == 1

        # Simulate the crash: the receipt never landed.
        (target / COMPLETION_FILENAME).unlink()

        again = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=probe,
            sink_root=tmp_path / "trajectories",
        )
        assert again.attempted == 1
        assert again.counts["completed"] == 1
        assert (target / "run-manifest.json").read_bytes() == manifest_before
        attempts = sorted(path.name for path in (target / "attempts").iterdir())
        assert len(attempts) == 2
        assert set(first_attempts) < set(attempts)
        record = read_record(directory, episode)
        assert record.run_id == episode.run_id
        assert record.attempt_id not in first_attempts

    def test_a_manifest_sealed_under_a_different_configuration_is_refused(
        self, tmp_path: Path
    ) -> None:
        """"A run that cannot prove what it ran is not data" (16 §5)."""
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        directory = tmp_path / plan.campaign_id
        episode = plan.runnable[0]
        target = directory / episode.output_path
        execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            sink_root=tmp_path / "trajectories",
        )
        (target / COMPLETION_FILENAME).unlink()

        # The checkout moved under the interrupted run: a different
        # `max_papers` gives a different settings digest and therefore a
        # different manifest.
        moved = config(max_papers=7)
        with pytest.raises(CampaignError, match="different configuration"):
            execute_campaign(
                moved,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(moved),
                sink_root=tmp_path / "trajectories",
            )


# ---------------------------------------------------------------------------
# 3. The campaign budget stop
# ---------------------------------------------------------------------------


def chargeable(
    tmp_path: Path,
    *,
    campaign_usd: str,
    episode_usd: str,
    cases: Sequence[str] = SLICE_CASES,
    arms: tuple[ArmId, ...] = ("A", "B"),
    lineage: CampaignLineage | None = None,
) -> tuple[Settings, CampaignPlan, LocalApprovalRecordBackend]:
    """A campaign whose approval really does cover a metered episode.

    `use_mock_data=False` is what makes the provider metered in this
    checkout, and it is also what makes the source scope live — so the
    campaign declares `live`, because a campaign whose own seal refuses
    its corpus mode is not a campaign.
    """
    from src.contracts.run_manifest import EpisodeBudget

    cfg = config(use_mock_data=False)
    base = default_episode_budget(cfg, arms)
    budget = base.model_copy(
        update={
            "workflow_cost_usd_max": episode_usd,
            "judge_cost_usd_max": "0.000000",
            "total_cost_usd_max": episode_usd,
        }
    )
    assert isinstance(budget, EpisodeBudget)
    plan = plan_campaign(
        cfg,
        request(
            cfg,
            cases=cases,
            arms=arms,
            repeats=1,
            approval_id="approval_w07b-budget",
            episode_budget=budget,
            campaign_budget=default_campaign_budget(campaign_usd),
            corpus_mode="live",
            lineage=lineage,
        ),
        resolver=registry(),
    )
    write_campaign(tmp_path, plan)
    backend = LocalApprovalRecordBackend(
        [
            campaign_approval_record(
                approval_id="approval_w07b-budget",
                campaign_id=plan.campaign_id,
                stage="stage-0-qualification",
                provider="anthropic",
                resources=("provider_call",),
                total_cost_usd_max=campaign_usd,
                episode_allocation_usd_max=episode_usd,
                workflow_allocation_usd_max=episode_usd,
                judge_allocation_usd_max="0.000000",
                approved_by="w07b-budget-fixture",
                approved_at="2026-09-01T00:00:00Z",
                expires_at="2026-12-01T00:00:00Z",
            )
        ]
    )
    return cfg, rebuild_plan(plan.manifest, plan.task_specs), backend


class TestTheCampaignBudgetStop:
    pytestmark = [pytest.mark.integration, pytest.mark.contract]

    def test_a_cap_smaller_than_the_matrix_stops_between_episodes(
        self, tmp_path: Path
    ) -> None:
        """The stop `CampaignBudget.enforcement` has always advertised.

        Four planned episodes at $1.00 each against a $3.00 cap: three
        run, the fourth never starts, and it stays `not_started` in the
        denominator rather than disappearing from it. That is 07 §9's
        rule — stopping is an experiment outcome — made arithmetic.
        """
        cfg, plan, backend = chargeable(
            tmp_path, campaign_usd="3.000000", episode_usd="1.000000"
        )
        runner = ScriptedRunner(workflow_cost_usd="1.000000")
        credentials: list[str] = []
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            approval_backend=backend,
            graph_probe=arm_graph_probe(config()),
            runner=runner,
            scorer=available_scorer,
            credential_probe=lambda: credentials.append("credential"),
            sink_root=tmp_path / "trajectories",
        )
        assert report.stop_reason == "campaign_cap_reached"
        assert report.attempted == 3
        assert report.counts["completed"] == 3
        assert report.counts["not_started"] == 1
        assert report.summary.denominators.expected == 4
        assert report.summary.denominators.analysis_denominator == 4
        assert report.observed_cost_usd == "3.000000"
        # A metered episode reads a credential — after its approval
        # verified, once per seal, and never before.
        assert len(credentials) == 3

    def test_resume_under_the_same_cap_continues_and_stops_again_at_it(
        self, tmp_path: Path
    ) -> None:
        cfg, plan, backend = chargeable(
            tmp_path, campaign_usd="3.000000", episode_usd="1.000000"
        )
        common: dict[str, Any] = {
            "root": tmp_path,
            "approval_backend": backend,
            "graph_probe": arm_graph_probe(config()),
            "runner": ScriptedRunner(workflow_cost_usd="1.000000"),
            "scorer": available_scorer,
            "credential_probe": lambda: None,
            "sink_root": tmp_path / "trajectories",
        }
        first = execute_campaign(cfg, plan=plan, max_episodes=2, **common)
        assert first.attempted == 2
        assert first.observed_cost_usd == "2.000000"

        reopened, pending = resume_campaign(tmp_path, campaign_id=plan.campaign_id)
        assert len(pending) == 2
        second = execute_campaign(cfg, plan=reopened, **common)
        assert second.skipped_already_complete == 2
        assert second.attempted == 1, "the cap allowed exactly one more episode"
        assert second.stop_reason == "campaign_cap_reached"
        assert second.observed_cost_usd == "3.000000"
        assert second.counts["completed"] == 3
        assert second.counts["not_started"] == 1

    def test_a_raised_cap_is_refused_and_becomes_a_new_campaign_with_lineage(
        self, tmp_path: Path
    ) -> None:
        """RFC 09 §11.1's rule, and the remedy the refusal names.

        The campaign id is derived from the protocol, so a raised cap
        *cannot* resume: it is a different id, a different directory and
        a different ledger, and the old campaign's completed episodes are
        referenced by lineage rather than re-homed.
        """
        cfg, plan, backend = chargeable(
            tmp_path, campaign_usd="3.000000", episode_usd="1.000000"
        )
        execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            approval_backend=backend,
            graph_probe=arm_graph_probe(config()),
            runner=ScriptedRunner(workflow_cost_usd="1.000000"),
            scorer=available_scorer,
            credential_probe=lambda: None,
            sink_root=tmp_path / "trajectories",
        )
        raised = request(
            cfg,
            cases=SLICE_CASES,
            arms=("A", "B"),
            repeats=1,
            approval_id="approval_w07b-budget",
            episode_budget=plan.manifest.payload.protocol.episode_budget,
            campaign_budget=default_campaign_budget("9.000000"),
            corpus_mode="live",
        )
        with pytest.raises(CampaignError, match="new campaign with lineage"):
            resume_campaign(tmp_path, campaign_id=plan.campaign_id, request=raised)

        successor_cfg, successor, successor_backend = chargeable(
            tmp_path,
            campaign_usd="9.000000",
            episode_usd="1.000000",
            lineage=CampaignLineage(
                kind="cap_raised",
                supersedes_campaign_id=plan.campaign_id,
                supersedes_manifest_digest=plan.manifest.integrity.payload_sha256,
                reason="the stage-0 cap was raised after review",
            ),
        )
        assert successor.campaign_id != plan.campaign_id
        assert successor.manifest.payload.lineage is not None
        assert (
            successor.manifest.payload.lineage.supersedes_campaign_id
            == plan.campaign_id
        )
        report = execute_campaign(
            successor_cfg,
            root=tmp_path,
            plan=successor,
            approval_backend=successor_backend,
            graph_probe=arm_graph_probe(config()),
            runner=ScriptedRunner(workflow_cost_usd="1.000000"),
            scorer=available_scorer,
            credential_probe=lambda: None,
            sink_root=tmp_path / "trajectories",
        )
        assert report.attempted == 4
        assert report.stop_reason == "completed"
        # The superseded campaign is untouched: three episodes, one never
        # started, exactly as its own cap left it.
        old = json.loads(
            (tmp_path / plan.campaign_id / "campaign-ledger.json").read_text(
                encoding="utf-8"
            )
        )
        assert old["report"]["counts"]["completed"] == 3
        assert old["report"]["counts"]["not_started"] == 1


# ---------------------------------------------------------------------------
# 4. Admission
# ---------------------------------------------------------------------------


class TestAdmissionGatesTheProvider:
    pytestmark = [pytest.mark.integration, pytest.mark.security]

    def test_a_metered_campaign_without_an_approval_record_is_refused_first(
        self, tmp_path: Path
    ) -> None:
        """Refused before a credential is read, and before episode one.

        The backend holds no record for the id the protocol names, so the
        pre-flight fails — which is the ordering RFC 09 §10.2 requires:
        the approval is verified, and only then may a credential be
        looked at. Nothing ran, nothing was sealed, and the probe was
        never called.
        """
        cfg, plan, _ = chargeable(
            tmp_path, campaign_usd="3.000000", episode_usd="1.000000"
        )
        credentials: list[str] = []
        runner = ScriptedRunner()
        with pytest.raises(CampaignError, match="approval"):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                approval_backend=LocalApprovalRecordBackend(),
                graph_probe=arm_graph_probe(config()),
                runner=runner,
                scorer=available_scorer,
                credential_probe=lambda: credentials.append("credential"),
                sink_root=tmp_path / "trajectories",
            )
        assert credentials == []
        assert runner.calls == []
        assert not list((tmp_path / plan.campaign_id).glob("episodes/*/*/*/*"))

    def test_the_same_campaign_is_admitted_with_the_record(
        self, tmp_path: Path
    ) -> None:
        cfg, plan, backend = chargeable(
            tmp_path, campaign_usd="9.000000", episode_usd="1.000000"
        )
        credentials: list[str] = []
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            approval_backend=backend,
            graph_probe=arm_graph_probe(config()),
            runner=ScriptedRunner(workflow_cost_usd="1.000000"),
            scorer=available_scorer,
            credential_probe=lambda: credentials.append("credential"),
            sink_root=tmp_path / "trajectories",
        )
        assert report.attempted == 4
        assert report.counts["completed"] == 4
        assert len(credentials) == 4
        assert backend.calls >= 4

    def test_an_api_key_alone_never_admits_a_metered_provider(
        self, tmp_path: Path
    ) -> None:
        """Invariant 10, at campaign scale.

        A zero-cost campaign against a metered provider carries a real
        key and no approval, and every one of its episodes fails
        admission at the seal. The credential probe is `NoCredentialProbe`
        — it raises if it is ever reached — so a passing test says the
        refusal happened *before* the key was consulted, not because of
        what the key was.
        """
        cfg = config(use_mock_data=False)
        plan = materialize(
            tmp_path,
            cfg,
            request(
                cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1, corpus_mode="live"
            ),
        )
        assert plan.manifest.payload.protocol.approval_id is None
        assert plan.manifest.payload.protocol.chargeable is False
        runner = ScriptedRunner()
        with pytest.raises(CampaignError, match="admission failed closed"):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                approval_backend=LocalApprovalRecordBackend(),
                graph_probe=arm_graph_probe(config()),
                runner=runner,
                scorer=available_scorer,
                credential_probe=NoCredentialProbe(),
                sink_root=tmp_path / "trajectories",
            )
        assert runner.calls == []

    def test_a_campaign_that_budgets_judges_refuses_the_free_scorer(
        self, tmp_path: Path
    ) -> None:
        """Scoring less than the protocol declared is a silent wrong answer."""
        from src.contracts.run_manifest import EpisodeBudget

        cfg = config()
        base = default_episode_budget(cfg, ("A",))
        budget = base.model_copy(update={"judge_model_calls_max": 3})
        assert isinstance(budget, EpisodeBudget)
        plan = materialize(
            tmp_path,
            cfg,
            request(
                cfg,
                cases=SLICE_CASES[:1],
                arms=("A",),
                repeats=1,
                episode_budget=budget,
            ),
        )
        with pytest.raises(CampaignError, match="judge model calls"):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(cfg),
                runner=ScriptedRunner(),
                sink_root=tmp_path / "trajectories",
            )


# ---------------------------------------------------------------------------
# 5. Denominators
# ---------------------------------------------------------------------------


class TestEveryOutcomeStaysInTheDenominator:
    pytestmark = [pytest.mark.integration, pytest.mark.contract]

    def test_errors_cancellations_timeouts_and_budget_stops_get_their_own_bucket(
        self, tmp_path: Path
    ) -> None:
        """Work-order invariant 11, one arm per failure mode.

        The four arms are scripted to four different terminal outcomes,
        so the assertion is not only "the counts add up" but "the loop
        told them apart". Collapsing a timeout into an error would hide
        an infrastructure problem inside a quality number, which is the
        stop condition 07 §9 names.
        """
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], repeats=1)
        )
        runner = ScriptedRunner(
            per_arm={
                "A": (CompletionStatus.SUCCEEDED, None),
                "B": (CompletionStatus.FAILED, RunReason.PROVIDER_ERROR),
                "C": (CompletionStatus.CANCELLED, RunReason.OPERATOR_INTERRUPT),
                "D": (CompletionStatus.FAILED, RunReason.TIMEOUT),
                # Arm E used to be the excluded slot that kept this
                # matrix's fifth bucket non-empty. Since CAP-09 it runs
                # like any other arm (ADR 0091), so it is scripted to the
                # one terminal outcome the other four do not cover.
                "E": (CompletionStatus.BUDGET_STOPPED, RunReason.EPISODE_BUDGET_EXHAUSTED),
            }
        )
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=runner,
            scorer=available_scorer,
            sink_root=tmp_path / "trajectories",
        )
        assert report.counts == {
            "not_started": 0,
            "completed": 1,
            "errored": 1,
            "cancelled": 1,
            "timed_out": 1,
            "budget_stopped": 1,
            "null_metric": 0,
            "excluded": 0,
        }
        assert report.summary.denominators.expected == 5
        assert report.summary.denominators.accounted == 5
        assert report.summary.denominators.analysis_denominator == 5
        assert report.completed == 1

        directory = tmp_path / plan.campaign_id
        by_arm = {
            record.arm_id: record
            for record in load_episode_records(directory, plan)
        }
        assert by_arm["B"].ledger_status is LedgerStatus.ERRORED
        assert by_arm["C"].ledger_status is LedgerStatus.CANCELLED
        assert by_arm["D"].ledger_status is LedgerStatus.TIMED_OUT
        assert by_arm["E"].ledger_status is LedgerStatus.BUDGET_STOPPED
        # Every failure still wrote its terminal receipt and its record:
        # "failed episodes remain in artifacts and denominators".
        for arm in RUNNABLE_ARMS:
            episode = next(item for item in plan.runnable if item.arm_id == arm)
            target = directory / episode.output_path
            assert (target / COMPLETION_FILENAME).is_file()
            assert (target / TRAJECTORY_FILENAME).is_file()

    def test_an_episode_that_completes_without_its_primary_metric_is_a_null_metric(
        self, tmp_path: Path
    ) -> None:
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A", "B"), repeats=1)
        )
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=ScriptedRunner(),
            scorer=null_scorer,
            sink_root=tmp_path / "trajectories",
        )
        assert report.counts["null_metric"] == 2
        assert report.counts["completed"] == 0
        assert report.summary.denominators.analysis_denominator == 2
        directory = tmp_path / plan.campaign_id
        for episode in plan.runnable:
            receipt = EpisodeScoreReceipt.model_validate_json(
                (directory / episode.output_path / SCORES_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            assert receipt.primary_metric_available is False
            assert receipt.null_reason == "scripted null metric"
            # The *episode* succeeded; only its metric is missing.
            completion = CompletionReceipt.model_validate_json(
                (directory / episode.output_path / COMPLETION_FILENAME).read_text(
                    encoding="utf-8"
                )
            )
            assert completion.status is CompletionStatus.SUCCEEDED

    def test_the_default_scorer_calls_a_report_with_no_checkable_claims_null(
        self, tmp_path: Path
    ) -> None:
        """The free scorer is honest about what it could not measure.

        A scripted report cites nothing, so ADR 0074's groundedness check
        has no claim to decide and the primary metric is absent. Recorded
        as a null metric with a reason, in the denominator and out of the
        numerator — not as a zero, which would be a measurement nobody
        made.
        """
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=ScriptedRunner(),
            sink_root=tmp_path / "trajectories",
        )
        assert report.counts["null_metric"] == 1
        record = read_record(tmp_path / plan.campaign_id, plan.runnable[0])
        assert record.primary_metric_available is False
        assert record.primary_score is None
        assert record.primary_metric == PRIMARY_METRIC
        assert record.scores["judges_run"] is False


# ---------------------------------------------------------------------------
# 6. The operator's log surface
# ---------------------------------------------------------------------------


class TestTheOperatorCanFollowAPass:
    """P0-WO07c. Four events, and each one answers a distinct question.

    A 240-episode pass runs for tens of seconds in one process and the
    CLI prints nothing until it is over, so the log is the only thing an
    operator watching a campaign has. These assertions are what stop the
    four names being registered and then quietly stopping — the failure
    `KNOWN_EVENTS` exists to catch in the other direction.
    """

    pytestmark = [pytest.mark.integration, pytest.mark.contract]

    def test_a_pass_emits_a_started_and_a_completed_line_per_episode(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES, arms=("A", "B"), repeats=1)
        )
        with caplog.at_level(logging.INFO, logger="src.campaign.execute"):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(cfg),
                sink_root=tmp_path / "trajectories",
            )

        started = _events(caplog, "campaign_episode_started")
        completed = _events(caplog, "campaign_episode_completed")
        assert len(started) == 4
        assert len(completed) == 4

        for record in started:
            assert record.campaign_id == plan.campaign_id
            assert record.arm_id in {"A", "B"}
            assert record.case_id in SLICE_CASES
            assert record.repeat_index == 0
        for record in completed:
            assert record.campaign_id == plan.campaign_id
            assert record.status == "succeeded"
            assert record.ledger_status == "completed"
            # The claim the whole work order rests on, on every line.
            assert record.call_count == 0
            assert record.workflow_cost_usd == "0.000000"
            assert isinstance(record.elapsed_sec, float)

        # Every key the four events pass is on the closed allowlist, and
        # every name is in the closed registry. `tests/test_log_contract.py`
        # asserts this over the *source*; this asserts it over the lines a
        # real pass actually emitted.
        for record in (*started, *completed):
            assert record.getMessage() in KNOWN_EVENTS
            assert _extras(record) <= ALLOWED_EXTRA_KEYS

    def test_a_failing_episode_logs_its_error_type_and_its_traceback(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The one place a failed episode's whole stack survives.

        The episode record keeps a bounded 500-character detail and the
        manifest keeps none at all (RFC 09 §11.2), so a campaign whose
        graph broke on one slot of 240 is otherwise only debuggable by
        re-running it.
        """
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )

        def _explode(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("the graph fell over")

        import src.graph.workflow as workflow_module

        probe = arm_graph_probe(cfg)
        with (
            caplog.at_level(logging.ERROR, logger="src.campaign.execute"),
            pytest.MonkeyPatch.context() as patch,
        ):
            # Patched *after* the probe has compiled its shapes: breaking
            # the builder before that would fail the plan rather than the
            # episode, which is a different test.
            probe("A")
            patch.setattr(workflow_module, "build_workflow", _explode)
            report = execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=probe,
                sink_root=tmp_path / "trajectories",
            )

        assert report.counts["errored"] == 1
        failed = _events(caplog, "campaign_episode_failed")
        assert len(failed) == 1
        assert failed[0].error_type == "RuntimeError"
        assert failed[0].case_id == SLICE_CASES[0]
        assert failed[0].arm_id == "A"
        assert failed[0].exc_info is not None, "the traceback is the point"
        assert failed[0].getMessage() in KNOWN_EVENTS
        assert _extras(failed[0]) <= ALLOWED_EXTRA_KEYS

    def test_the_campaign_cap_stop_is_a_warning_naming_the_cap(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A campaign that stopped short must say so at WARNING.

        07 §9: stopping is an experiment outcome. A pass that quietly
        ended three episodes early at INFO would look identical to one
        that finished.
        """
        cfg, plan, backend = chargeable(
            tmp_path, campaign_usd="3.000000", episode_usd="1.000000"
        )
        with caplog.at_level(logging.WARNING, logger="src.campaign.execute"):
            report = execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                approval_backend=backend,
                graph_probe=arm_graph_probe(config()),
                runner=ScriptedRunner(workflow_cost_usd="1.000000"),
                scorer=available_scorer,
                credential_probe=lambda: None,
                sink_root=tmp_path / "trajectories",
            )

        assert report.stop_reason == "campaign_cap_reached"
        stopped = _events(caplog, "campaign_budget_stop")
        assert len(stopped) == 1
        assert stopped[0].levelno == logging.WARNING
        assert stopped[0].campaign_id == plan.campaign_id
        assert stopped[0].cap_usd == "3.000000"
        assert stopped[0].getMessage() in KNOWN_EVENTS
        assert _extras(stopped[0]) <= ALLOWED_EXTRA_KEYS

    def test_the_campaign_emits_no_event_the_registry_does_not_know(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The closed set, checked against a real pass rather than the AST."""
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        with caplog.at_level(logging.DEBUG, logger="src.campaign.execute"):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(cfg),
                sink_root=tmp_path / "trajectories",
            )
        emitted = {record.getMessage() for record in caplog.records}
        assert emitted, "the pass logged nothing at all"
        assert emitted <= KNOWN_EVENTS, f"unregistered: {sorted(emitted - KNOWN_EVENTS)}"


def _events(
    caplog: pytest.LogCaptureFixture, name: str
) -> list[logging.LogRecord]:
    """Every captured record for one event name, in emission order."""
    return [record for record in caplog.records if record.getMessage() == name]


def _extras(record: logging.LogRecord) -> set[str]:
    """The keys a record attached beyond `logging`'s own standard set."""
    return set(record.__dict__) - _STANDARD_LOG_KEYS


# ---------------------------------------------------------------------------
# 7. The `run` verb
# ---------------------------------------------------------------------------


class TestTheRunVerb:
    pytestmark = [pytest.mark.integration]

    def test_plan_then_run_prints_the_ledger_counts_as_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The operator's path, end to end, through `python -m src.campaign`.

        The CLI reads the deployment's own settings, and the deployment
        this suite runs under is not on mock data — so the *environment*
        is patched rather than the verb, which is exactly what
        `USE_MOCK_DATA=true` does for an operator running the same
        commands.
        """
        import src.campaign.cli as cli_module
        from src.campaign.cli import EXIT_OK, main

        monkeypatch.setattr(cli_module, "shipped_settings", config())

        argv = [
            "--output-root",
            str(tmp_path),
            "--cases",
            SLICE_CASES[0],
            "--arms",
            "A,E",
            "--repeats",
            "1",
            # Without this the durable sink lands on the *deployment's*
            # `contract_event_sink_root`, which is `outputs/trajectories`
            # in the repository the suite is running inside. A test that
            # writes outside `tmp_path` is a test two parallel runs can
            # collide in.
            "--sink-root",
            str(tmp_path / "trajectories"),
        ]
        assert main(["plan", *argv]) == EXIT_OK
        planned = json.loads(capsys.readouterr().out)
        # Two, not one-and-one-excluded: arm E is runnable since CAP-09
        # (ADR 0091), so the operator's smallest useful campaign now
        # exercises the adaptive arm beside the fixed one.
        assert planned["planned_episode_count"] == 2
        assert planned["excluded_episode_count"] == 0

        assert (
            main(["run", "--campaign-id", planned["campaign_id"], *argv]) == EXIT_OK
        )
        ran = json.loads(capsys.readouterr().out)
        assert ran["campaign_id"] == planned["campaign_id"]
        assert ran["attempted"] == 2
        assert ran["completed"] == 2
        assert ran["model_calls"] == 0
        assert ran["observed_cost_usd"] == "0.000000"
        assert ran["stop_reason"] == "completed"
        assert ran["counts"]["excluded"] == 0
        assert ran["analysis_denominator"] == 2

        assert main(["status", "--campaign-id", planned["campaign_id"], *argv]) == EXIT_OK
        status = json.loads(capsys.readouterr().out)
        assert status["counts"]["completed"] == 2
        assert status["expected"] == 2

    def test_run_without_a_campaign_id_is_a_usage_error(self) -> None:
        from src.campaign.cli import EXIT_USAGE, main

        assert main(["run"]) == EXIT_USAGE
