"""No-cost qualification for the campaign orchestrator (P0-WO07).

Everything here runs against the repository's real `eval_registry/` tree
and against *stand-in* graph shapes. The registry is real because the
claim under test is that a campaign pins registry objects by exact
revision and digest, and a fixture registry would only prove the fixture
was pinned. The graphs are stand-ins for W05's reason: policy identity is
read from a graph's structure, so handing the classifier four structures
and checking four answers tests the rule rather than this week's wiring —
and it does it without compiling a workflow.

Nothing in this module touches the network, a provider, or a model. Two
tests say so explicitly rather than relying on the conftest guards, since
"the dry run initializes no provider" is an acceptance criterion and not
an ambient property.
"""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest

from src.campaign.approval import (
    LocalApprovalRecordBackend,
    NoCredentialProbe,
    SettingsCredentialProbe,
    campaign_approval_record,
)
from src.campaign.arms import (
    ARM_IDS,
    COMMON_FROZEN_SETTINGS,
    ArmId,
    arm_settings,
    ceiling_settings,
    declare_arm,
)
from src.campaign.cli import main as campaign_main
from src.campaign.episode import (
    assert_not_overwriting,
    campaign_lock_ref,
    seal_campaign_episode,
)
from src.campaign.errors import CampaignError
from src.campaign.ledger import (
    DenominatorLedger,
    EpisodeOutcome,
    LedgerStatus,
    read_outcomes,
    reconcile,
)
from src.campaign.manifest import CampaignLineage, derive_campaign_id
from src.campaign.matrix import block_arm_order, rerun_of
from src.campaign.planner import (
    CampaignPlan,
    CampaignRequest,
    campaign_status,
    default_campaign_budget,
    default_episode_budget,
    dry_run,
    load_campaign,
    plan_campaign,
    preflight_approval,
    rebuild_plan,
    resume_campaign,
    resume_episode,
    seal_next_episode,
    write_campaign,
)
from src.campaign.summary import aggregate_costs, assert_aggregatable, summarize
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.kernel import ImmutableObjectRef, sha256_digest
from src.contracts.registry import IntendedUse, LocalRegistry, RegistryRole, TaskSet
from src.contracts.research_binding import GraphShape
from src.contracts.run_manifest import (
    ApprovalStatus,
    CompletionReceipt,
    CompletionStatus,
    RunLineage,
    RunReason,
    derive_episode_key,
    derive_replicate_group_id,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_ROOT = REPO_ROOT / "eval_registry"
SUITE_ID = "research-policy-v1"


# ---------------------------------------------------------------------------
# Fixtures: real registry, stand-in graphs
# ---------------------------------------------------------------------------


def config(**overrides: Any) -> Settings:
    """The shipped settings on a mock, no-cost research surface."""
    base = {
        "use_mock_data": True,
        "enable_tracing": False,
        "enable_metrics": False,
        "enable_checkpointing": False,
        "enable_semantic_scholar": False,
    }
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


FIXED_NODES = ("planner", "search", "reader", "synthesizer", "critic")


def graph_for(*extra: str) -> GraphShape:
    """A graph shape with the fixed pipeline's nodes plus whatever else."""
    nodes = tuple(sorted({*FIXED_NODES, *extra}))
    return GraphShape(
        nodes=nodes,
        conditional_sources=("supervisor",) if "supervisor" in nodes else ("critic",),
        edges=tuple(sorted(f"{node}->next" for node in nodes)),
        digest=sha256_digest({"nodes": list(nodes)}),
    )


ARM_GRAPHS: dict[ArmId, GraphShape] = {
    "A": graph_for(),
    "B": graph_for(),
    "C": graph_for("verify", "repair"),
    "D": graph_for("supervisor", "verifier"),
    "E": graph_for("supervisor", "verifier"),
}


def registry(root: Path | None = None) -> LocalRegistry:
    return LocalRegistry(root or REGISTRY_ROOT)


def all_case_ids(root: Path | None = None) -> tuple[str, ...]:
    tree = root or REGISTRY_ROOT
    resolver = registry(tree)
    suite = resolver.resolve(
        suite_ref(tree, SUITE_ID),
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    task_set = resolver.resolve(
        suite.task_set_ref,  # type: ignore[union-attr]
        role=RegistryRole.EVALUATOR,
        intended_use=IntendedUse.DEVELOPMENT,
    ).payload
    assert isinstance(task_set, TaskSet)
    return tuple(ref.id for ref in task_set.case_refs)


def request(
    *,
    cases: tuple[str, ...] = ("hallucination-mitigation", "rag-multi-hop"),
    arms: tuple[ArmId, ...] = ("A", "B", "C", "D", "E"),
    repeats: int = 2,
    seed: int = 7,
    corpus_mode: str = "snapshot",
    workflow_usd: str = "0.000000",
    judge_usd: str = "0.000000",
    campaign_usd: str = "0.000000",
    approval_id: str | None = None,
    lineage: CampaignLineage | None = None,
    root: Path | None = None,
    cfg: Settings | None = None,
) -> CampaignRequest:
    tree = root or REGISTRY_ROOT
    return CampaignRequest(
        protocol_id="research-policy-v1-stage-0",
        stage="stage-0-qualification",
        suite_ref=suite_ref(tree, SUITE_ID),
        case_ids=cases,
        arms=arms,
        repeats=repeats,
        corpus_mode=corpus_mode,  # type: ignore[arg-type]
        seed=seed,
        approval_id=approval_id,
        episode_budget=default_episode_budget(
            cfg or config(), arms, workflow_usd=workflow_usd, judge_usd=judge_usd
        ),
        campaign_budget=default_campaign_budget(campaign_usd),
        output_root="campaigns",
        lineage=lineage,
    )


def planned(**kwargs: Any) -> CampaignPlan:
    cfg = kwargs.pop("cfg", None) or config()
    root = kwargs.get("root")
    return plan_campaign(cfg, request(cfg=cfg, **kwargs), resolver=registry(root))


# ---------------------------------------------------------------------------
# The registry lock
# ---------------------------------------------------------------------------


class TestTheLockPinsEveryRegistryObject:
    def test_every_resolved_ref_carries_an_exact_revision_and_digest(self) -> None:
        lock = planned().manifest.payload.lock
        assert lock.resolved_refs
        resolver = registry()
        for ref in lock.resolved_refs:
            envelope = resolver.resolve(
                ref, role=RegistryRole.EVALUATOR, intended_use=IntendedUse.DEVELOPMENT
            )
            assert envelope.object_ref() == ref
            assert ref.revision.count(".") == 2
            assert ref.digest.startswith("sha256:")

    def test_the_manifest_pins_the_lock_by_digest(self) -> None:
        payload = planned().manifest.payload
        assert payload.lock_digest == sha256_digest(payload.lock)
        ref = campaign_lock_ref(payload.campaign_id, payload.lock_digest)
        assert ref.kind == "campaign_lock"
        assert ref.digest == payload.lock_digest

    def test_an_alias_is_not_even_expressible_as_a_reference(self) -> None:
        with pytest.raises(ValueError):
            ImmutableObjectRef(
                kind="benchmark_suite",
                id=SUITE_ID,
                revision="latest",
                digest="sha256:" + "0" * 64,
            )

    def test_a_reference_whose_digest_moved_is_refused(self) -> None:
        real = suite_ref(REGISTRY_ROOT, SUITE_ID)
        substituted = real.model_copy(update={"digest": "sha256:" + "1" * 64})
        with pytest.raises(CampaignError, match="does not resolve"):
            plan_campaign(
                config(),
                request().model_copy(update={"suite_ref": substituted}),
                resolver=registry(),
            )

    def test_a_changed_registry_object_fails_the_lock(self, tmp_path: Path) -> None:
        """Edit one case's content and the lock refuses the whole campaign.

        The digest sidecar is left alone, which is the tamper an operator
        would actually make by hand: the payload moved and the envelope's
        own integrity check is what catches it.
        """
        tree = tmp_path / "registry"
        shutil.copytree(REGISTRY_ROOT, tree)
        victim = tree / "task_case" / "hallucination-mitigation" / "1.0.0.json"
        payload = json.loads(victim.read_text(encoding="utf-8"))
        payload["payload"]["task_input"]["objective"] = "a different question entirely"
        victim.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(CampaignError):
            plan_campaign(config(), request(root=tree), resolver=registry(tree))

    def test_a_case_outside_the_suite_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="does not resolve"):
            planned(cases=("hallucination-mitigation", "not-a-real-case"))


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


class TestTheMatrixEnumeratesTheWholeDesign:
    def test_twenty_by_three_by_five_enumerates_exactly_the_expected_keys(self) -> None:
        cases = all_case_ids()
        assert len(cases) == 20
        plan = planned(cases=cases, repeats=3)
        payload = plan.manifest.payload
        assert payload.expected_episode_count == 20 * 3 * 5
        assert payload.planned_episode_count == 20 * 3 * 4
        assert payload.excluded_episode_count == 20 * 3

        expected: set[str] = set()
        for task_ref in payload.task_refs:
            for arm in payload.arms:
                group = derive_replicate_group_id(
                    payload.campaign_id, task_ref, arm.declaration_digest
                )
                for repeat in range(3):
                    expected.add(derive_episode_key(group, repeat))
        assert {episode.episode_key for episode in plan.episodes} == expected

    def test_the_same_task_and_registry_refs_appear_across_a_paired_block(self) -> None:
        plan = planned(repeats=3)
        blocks: dict[tuple[str, int], set[str]] = {}
        for episode in plan.episodes:
            key = (episode.case_id, episode.repeat_index)
            blocks.setdefault(key, set()).add(
                f"{episode.task_ref.full_digest}|{episode.case_ref.digest}"
            )
        assert all(len(values) == 1 for values in blocks.values())
        # One TaskSpec per case, reused across every repeat as well.
        by_case = {
            episode.case_id: episode.task_ref.task_spec_id for episode in plan.episodes
        }
        assert len(set(by_case.values())) == len(by_case)

    def test_interleaving_is_deterministic_from_the_seed(self) -> None:
        first = [episode.arm_id for episode in planned(seed=7).episodes]
        again = [episode.arm_id for episode in planned(seed=7).episodes]
        other = [episode.arm_id for episode in planned(seed=8).episodes]
        assert first == again
        assert first != other

    def test_no_arm_is_always_first_in_its_block(self) -> None:
        cases = all_case_ids()
        plan = planned(cases=cases, repeats=3)
        leaders = {
            episode.arm_id for episode in plan.episodes if episode.order_in_block == 0
        }
        assert len(leaders) > 1, "one arm led every block; the interleaving is not one"

    def test_the_block_order_helper_is_a_permutation(self) -> None:
        order = block_arm_order(ARM_IDS, seed=3, case_id="rag-multi-hop", repeat_index=1)
        assert sorted(order) == sorted(ARM_IDS)

    def test_blocks_are_repeat_major_so_a_truncated_campaign_covers_the_benchmark(
        self,
    ) -> None:
        plan = planned(cases=("hallucination-mitigation", "rag-multi-hop"), repeats=2)
        first_block_repeats = {
            episode.repeat_index
            for episode in plan.episodes
            if episode.block_index < 2
        }
        assert first_block_repeats == {0}


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


class TestArmsAreClaimsUntilAGraphEarnsThem:
    def test_arm_e_is_capability_missing_and_never_runnable(self) -> None:
        arm = declare_arm("E", graph=ARM_GRAPHS["E"])
        assert arm.status == "capability_missing"
        assert not arm.runnable
        assert "adaptive_compute_router" in arm.missing_capabilities

    def test_arm_c_needs_the_compiled_verify_repair_stage(self) -> None:
        assert declare_arm("C", graph=ARM_GRAPHS["C"]).status == "available"
        assert declare_arm("C", graph=ARM_GRAPHS["B"]).status == "capability_missing"

    def test_a_graph_that_runs_another_arm_cannot_seal_this_one(
        self, tmp_path: Path
    ) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A", "C"), repeats=1)
        write_campaign(tmp_path, plan)
        episode = next(item for item in plan.runnable if item.arm_id == "C")
        with pytest.raises(CampaignError, match="not the declared arm"):
            seal_next_episode(
                config(),
                root=tmp_path,
                plan=plan,
                episode=episode,
                graph=ARM_GRAPHS["A"],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_every_arm_freezes_the_common_settings(self) -> None:
        for arm_id in ARM_IDS:
            settings = arm_settings(config(), arm_id)
            for name, value in COMMON_FROZEN_SETTINGS.items():
                assert getattr(settings, name) == value, (arm_id, name)

    def test_a_ceiling_configuration_that_will_not_load_refuses(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The envelope is always loadable today; the refusal still has to exist.

        A future arm whose flags contradict each other would otherwise
        surface as a raw pydantic error from inside the planner, which
        names a field rather than the campaign.
        """
        import src.campaign.arms as arms_module

        def _refuse(values: Any) -> Settings:
            raise ValueError("contrived")

        monkeypatch.setattr(arms_module.Settings, "model_validate", _refuse)
        with pytest.raises(CampaignError, match="ceiling settings are not loadable"):
            ceiling_settings(config(), ("A", "D"))

    def test_the_ceiling_configuration_is_the_most_permissive_arm(self) -> None:
        ceiling = ceiling_settings(config(), ("A", "B", "C", "D"))
        assert ceiling.enable_supervisor
        assert ceiling.enable_evidence_store
        assert ceiling.research_policy == "legacy"

    def test_the_arm_table_overrides_a_contradictory_base_configuration(self) -> None:
        """A deployment with the supervisor on still gets arm C's fixed graph.

        The arm table is applied over the base settings and re-validated,
        so the combination CAP-02 refuses to boot is a combination this
        package cannot plan either — and a base configuration that would
        have contradicted it is normalized rather than inherited.
        """
        settings = arm_settings(config(enable_supervisor=True), "C")
        assert settings.enable_supervisor is False
        assert settings.enable_evidence_store is True
        assert settings.research_policy == "fixed_verify_repair"


# ---------------------------------------------------------------------------
# Identity: repeat, resume, rerun
# ---------------------------------------------------------------------------


class TestIdentitySeparatesRepeatResumeAndRerun:
    def test_a_repeat_is_a_new_run_in_the_same_replicate_group(self) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=3)
        episodes = sorted(plan.runnable, key=lambda item: item.repeat_index)
        assert [item.repeat_index for item in episodes] == [0, 1, 2]
        assert len({item.run_id for item in episodes}) == 3
        assert len({item.replicate_group_id for item in episodes}) == 1
        assert len({item.output_path for item in episodes}) == 3

    def test_a_resume_keeps_the_run_id_and_mints_a_new_attempt(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        first = resume_episode(
            tmp_path, campaign_id=plan.campaign_id, episode=episode
        )
        second = resume_episode(
            tmp_path, campaign_id=plan.campaign_id, episode=episode
        )
        assert first.startswith("att_") and second.startswith("att_")
        assert first != second
        manifest_dir = tmp_path / plan.campaign_id / episode.output_path
        stored = json.loads((manifest_dir / "run-manifest.json").read_text())
        assert stored["payload"]["identity"]["run_id"] == episode.run_id

    def test_a_terminal_receipt_blocks_resume(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        with pytest.raises(CampaignError, match="terminal completion"):
            resume_episode(tmp_path, campaign_id=plan.campaign_id, episode=episode)

    def test_a_rerun_is_a_new_run_with_its_own_directory_and_lineage(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        again = rerun_of(episode)
        assert again.episode_key == episode.episode_key
        assert again.run_id != episode.run_id
        assert again.output_path != episode.output_path
        sealed = seal_campaign_episode(
            config(),
            campaign=plan.manifest,
            episode=again,
            task_spec=plan.task_spec_for(again.case_id),
            graph=ARM_GRAPHS[again.arm_id],
            approval_backend=LocalApprovalRecordBackend(),
            lineage=RunLineage(
                kind="rerun",
                parent_run_id=episode.run_id,
                reason="diagnosing a provider error",
            ),
        )
        assert sealed.manifest.payload.lineage is not None
        assert sealed.manifest.payload.lineage.parent_run_id == episode.run_id

    def test_the_campaign_id_moves_when_the_cap_moves(self) -> None:
        cheap = planned().campaign_id
        expensive = plan_campaign(
            config(),
            request(
                workflow_usd="1.000000",
                judge_usd="0.500000",
                campaign_usd="30.000000",
                approval_id="approval_stage-one",
            ),
            resolver=registry(),
        ).campaign_id
        assert cheap != expensive

    def test_a_raised_cap_refuses_resume_and_names_lineage(
        self, tmp_path: Path
    ) -> None:
        plan = planned()
        write_campaign(tmp_path, plan)
        raised = request(
            workflow_usd="1.000000",
            judge_usd="0.500000",
            campaign_usd="30.000000",
            approval_id="approval_stage-one",
        )
        with pytest.raises(CampaignError, match="new campaign with lineage"):
            resume_campaign(tmp_path, campaign_id=plan.campaign_id, request=raised)

    def test_a_changed_protocol_refuses_resume(self, tmp_path: Path) -> None:
        plan = planned(repeats=2)
        write_campaign(tmp_path, plan)
        with pytest.raises(CampaignError, match="different campaign"):
            resume_campaign(
                tmp_path, campaign_id=plan.campaign_id, request=request(repeats=3)
            )

    def test_an_unchanged_request_resumes_the_same_matrix(self, tmp_path: Path) -> None:
        plan = planned()
        write_campaign(tmp_path, plan)
        resumed, pending = resume_campaign(
            tmp_path, campaign_id=plan.campaign_id, request=request()
        )
        assert resumed.campaign_id == plan.campaign_id
        assert [item.episode_key for item in resumed.episodes] == [
            item.episode_key for item in plan.episodes
        ]
        assert len(pending) == plan.manifest.payload.planned_episode_count

    def test_a_new_campaign_with_lineage_supersedes_the_old_one(self) -> None:
        first = planned()
        lineage = CampaignLineage(
            kind="cap_raised",
            supersedes_campaign_id=first.campaign_id,
            supersedes_manifest_digest=first.manifest.integrity.payload_sha256,
            reason="stage 1 approved a larger cap",
        )
        second = plan_campaign(
            config(),
            request(
                workflow_usd="1.000000",
                judge_usd="0.500000",
                campaign_usd="30.000000",
                approval_id="approval_stage-one",
                lineage=lineage,
            ),
            resolver=registry(),
        )
        assert second.manifest.payload.lineage is not None
        assert (
            second.manifest.payload.lineage.supersedes_campaign_id == first.campaign_id
        )
        assert second.campaign_id != first.campaign_id

    def test_the_campaign_id_is_a_function_of_protocol_lock_and_lineage(self) -> None:
        payload = planned().manifest.payload
        assert payload.campaign_id == derive_campaign_id(
            protocol_digest=payload.protocol_digest,
            lock_digest=payload.lock_digest,
            lineage=None,
        )


# ---------------------------------------------------------------------------
# Denominators
# ---------------------------------------------------------------------------


class TestTheDenominatorKeepsEveryEpisode:
    def test_the_ledger_is_written_before_any_episode_runs(self, tmp_path: Path) -> None:
        plan = planned()
        directory = write_campaign(tmp_path, plan)
        stored = json.loads((directory / "campaign-ledger.json").read_text())
        assert stored["report"]["expected"] == plan.manifest.payload.expected_episode_count
        statuses = {entry["status"] for entry in stored["entries"]}
        assert statuses <= {"not_started", "excluded"}

    def test_injected_outcomes_reconcile_with_the_correct_counts(self) -> None:
        plan = planned(cases=all_case_ids()[:6], arms=("A", "B", "C", "D", "E"), repeats=1)
        runnable = plan.runnable
        assert len(runnable) == 24
        injected = (
            _outcome(runnable[0], CompletionStatus.SUCCEEDED),
            _outcome(runnable[1], CompletionStatus.FAILED, RunReason.PROVIDER_ERROR),
            _outcome(runnable[2], CompletionStatus.CANCELLED, RunReason.OPERATOR_INTERRUPT),
            _outcome(runnable[3], CompletionStatus.FAILED, RunReason.TIMEOUT),
            _outcome(
                runnable[4],
                CompletionStatus.BUDGET_STOPPED,
                RunReason.CAMPAIGN_BUDGET_EXHAUSTED,
            ),
            _outcome(runnable[5], CompletionStatus.SUCCEEDED, metric=False),
        )
        reconciled = reconcile(
            plan.ledger, injected, reconciled_at="2026-09-05T12:00:00Z"
        )
        counts = reconciled.report.counts
        assert counts[LedgerStatus.COMPLETED.value] == 1
        assert counts[LedgerStatus.ERRORED.value] == 1
        assert counts[LedgerStatus.CANCELLED.value] == 1
        assert counts[LedgerStatus.TIMED_OUT.value] == 1
        assert counts[LedgerStatus.BUDGET_STOPPED.value] == 1
        assert counts[LedgerStatus.NULL_METRIC.value] == 1
        assert counts[LedgerStatus.EXCLUDED.value] == 6
        assert counts[LedgerStatus.NOT_STARTED.value] == 24 - 6
        assert reconciled.report.accounted == reconciled.report.expected == 30
        assert reconciled.report.analysis_denominator == 24

    def test_a_failure_never_leaves_the_denominator(self) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=2)
        reconciled = reconcile(
            plan.ledger,
            [_outcome(item, CompletionStatus.FAILED, RunReason.SCHEMA_ERROR) for item in plan.runnable],
            reconciled_at="2026-09-05T12:00:00Z",
        )
        assert reconciled.report.analysis_denominator == 2
        assert reconciled.report.counts[LedgerStatus.ERRORED.value] == 2

    def test_every_excluded_slot_names_its_reason(self) -> None:
        ledger = planned().ledger
        excluded = [
            entry for entry in ledger.entries if entry.status is LedgerStatus.EXCLUDED
        ]
        assert excluded
        assert all(entry.exclusion_reason == "arm_capability_missing" for entry in excluded)

    def test_an_outcome_from_outside_the_plan_is_refused(self) -> None:
        plan = planned()
        stray = _outcome(plan.runnable[0], CompletionStatus.SUCCEEDED).model_copy(
            update={"episode_key": "sha256:" + "9" * 64}
        )
        with pytest.raises(CampaignError, match="outside the campaign plan"):
            reconcile(plan.ledger, [stray], reconciled_at="2026-09-05T12:00:00Z")

    def test_status_reconciles_from_the_receipts_on_disk(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        ledger = campaign_status(tmp_path, plan.campaign_id)
        assert ledger.report.counts[LedgerStatus.COMPLETED.value] == 1
        assert ledger.report.accounted == ledger.report.expected

    def test_a_null_metric_receipt_is_read_from_the_score_sidecar(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        directory = tmp_path / plan.campaign_id / episode.output_path
        (directory / "scores.json").write_text(
            json.dumps(
                {
                    "schema_kind": "episode-score-receipt",
                    "schema_version": "1.0.0",
                    "run_id": episode.run_id,
                    "primary_metric_available": False,
                    "null_reason": "judge returned no parsable verdict",
                }
            ),
            encoding="utf-8",
        )
        rebuilt = rebuild_plan(*load_campaign(tmp_path / plan.campaign_id))
        outcomes = read_outcomes(tmp_path / plan.campaign_id, rebuilt.ledger)
        assert [outcome.ledger_status for outcome in outcomes] == [LedgerStatus.NULL_METRIC]


class TestCompletedEpisodesAreNeverOverwritten:
    def test_a_completed_episode_directory_refuses_a_second_seal(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        with pytest.raises(CampaignError, match="never overwritten"):
            assert_not_overwriting(tmp_path / plan.campaign_id, episode)
        with pytest.raises(CampaignError):
            seal_next_episode(
                config(),
                root=tmp_path,
                plan=plan,
                episode=episode,
                graph=ARM_GRAPHS[episode.arm_id],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_a_sealed_manifest_refuses_a_second_seal(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        with pytest.raises(CampaignError, match="already sealed"):
            seal_next_episode(
                config(),
                root=tmp_path,
                plan=plan,
                episode=episode,
                graph=ARM_GRAPHS[episode.arm_id],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_a_sealed_campaign_manifest_refuses_a_second_write(
        self, tmp_path: Path
    ) -> None:
        plan = planned()
        write_campaign(tmp_path, plan)
        with pytest.raises(CampaignError, match="refusing to overwrite"):
            write_campaign(tmp_path, plan)

    def test_a_resumed_campaign_skips_the_episodes_already_finished(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        _, pending = resume_campaign(tmp_path, campaign_id=plan.campaign_id)
        assert episode.episode_key not in {item.episode_key for item in pending}
        assert len(pending) == plan.manifest.payload.planned_episode_count - 1


# ---------------------------------------------------------------------------
# Corpus modes
# ---------------------------------------------------------------------------


class TestSnapshotAndLiveNeverAggregate:
    def test_two_corpus_modes_cannot_share_a_summary(self) -> None:
        snapshot = planned()
        live_cfg = config(use_mock_data=False)
        live = plan_campaign(
            live_cfg,
            request(corpus_mode="live", cfg=live_cfg),
            resolver=registry(),
        )
        first = summarize(snapshot.manifest, snapshot.ledger)
        second = summarize(live.manifest, live.ledger)
        assert first.corpus_mode == "snapshot"
        assert second.corpus_mode == "live"
        with pytest.raises(CampaignError, match="live-retrieval campaign"):
            assert_aggregatable([first, second])

    def test_a_snapshot_campaign_refuses_to_seal_a_live_episode(
        self, tmp_path: Path
    ) -> None:
        """The campaign says `snapshot`; the settings say live arXiv."""
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=1)
        write_campaign(tmp_path, plan)
        with pytest.raises(CampaignError, match="corpus_mode"):
            seal_campaign_episode(
                config(use_mock_data=False),
                campaign=plan.manifest,
                episode=plan.runnable[0],
                task_spec=plan.task_spec_for("hallucination-mitigation"),
                graph=ARM_GRAPHS["A"],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_two_locks_cannot_share_a_summary(self) -> None:
        first = summarize(planned().manifest, planned().ledger)
        other = planned(cases=all_case_ids()[:4])
        second = summarize(other.manifest, other.ledger)
        with pytest.raises(CampaignError, match="different registry revisions"):
            assert_aggregatable([first, second])


# ---------------------------------------------------------------------------
# The dry run
# ---------------------------------------------------------------------------


class TestTheDryRunSpendsAndInitializesNothing:
    def test_it_enumerates_every_planned_episode_with_a_zero_cost_status(self) -> None:
        plan = planned(repeats=3)
        report = dry_run(plan)
        assert report.expected_episode_count == len(report.episodes)
        assert {episode.projected_cost_usd for episode in report.episodes} == {"0.000000"}
        assert report.chargeable is False
        assert report.provider_initialized is False
        assert report.network_calls == 0
        excluded = [item for item in report.episodes if item.status == "excluded"]
        assert excluded and all(
            item.exclusion_reason == "arm_capability_missing" for item in excluded
        )

    def test_it_touches_no_provider_client_and_opens_no_socket(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The acceptance criterion, asserted rather than assumed.

        The conftest guards already refuse both, but a guard that refuses
        is not evidence that nothing tried: this installs counting spies
        so the test fails on the attempt, and names the call that made it.
        """
        import src.llm as llm_module

        touched: list[str] = []
        monkeypatch.setattr(
            llm_module, "_get_client", lambda: touched.append("llm._get_client")
        )
        monkeypatch.setattr(
            socket.socket,
            "connect",
            lambda self, address: touched.append(f"socket.connect{address}"),
        )
        report = dry_run(planned(cases=all_case_ids()[:5], repeats=3))
        assert touched == []
        assert report.planned_episode_count == 5 * 3 * 4

    def test_it_writes_nothing(self, tmp_path: Path) -> None:
        dry_run(planned())
        assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Approval admission
# ---------------------------------------------------------------------------


def _chargeable_request(cfg: Settings) -> CampaignRequest:
    return request(
        cases=("hallucination-mitigation",),
        arms=("A",),
        repeats=1,
        corpus_mode="live",
        workflow_usd="1.500000",
        judge_usd="0.500000",
        campaign_usd="20.000000",
        approval_id="approval_stage-one-smoke",
        cfg=cfg,
    )


def _approval(campaign_id: str, **overrides: Any) -> Any:
    base: dict[str, Any] = {
        "approval_id": "approval_stage-one-smoke",
        "campaign_id": campaign_id,
        "stage": "stage-0-qualification",
        "provider": "anthropic",
        "total_cost_usd_max": "20.000000",
        "episode_allocation_usd_max": "2.000000",
        "workflow_allocation_usd_max": "1.500000",
        "judge_allocation_usd_max": "0.500000",
        "approved_by": "owner",
        "approved_at": "2026-09-01T00:00:00Z",
        "expires_at": "2026-12-01T00:00:00Z",
    }
    base.update(overrides)
    return campaign_approval_record(**base)


class TestApprovalAdmitsAndAKeyDoesNot:
    def test_a_chargeable_campaign_is_rejected_before_credential_lookup(self) -> None:
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        probe = SettingsCredentialProbe(cfg)
        with pytest.raises(CampaignError, match="admission failed closed"):
            seal_campaign_episode(
                cfg,
                campaign=plan.manifest,
                episode=plan.runnable[0],
                task_spec=plan.task_spec_for("hallucination-mitigation"),
                graph=ARM_GRAPHS["A"],
                approval_backend=LocalApprovalRecordBackend(),
                credential_probe=probe,
            )
        assert probe.calls == 0, "a credential was read before approval was verified"

    def test_a_matching_record_admits_a_metered_provider(self) -> None:
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        backend = LocalApprovalRecordBackend([_approval(plan.campaign_id)])
        calls: list[str] = []
        sealed = seal_campaign_episode(
            cfg,
            campaign=plan.manifest,
            episode=plan.runnable[0],
            task_spec=plan.task_spec_for("hallucination-mitigation"),
            graph=ARM_GRAPHS["A"],
            approval_backend=backend,
            credential_probe=lambda: calls.append("credential"),
        )
        assert sealed.chargeable
        assert sealed.manifest.payload.providers.llm.metered
        assert sealed.manifest.payload.approval.status_at_seal is ApprovalStatus.APPROVED
        assert backend.calls == 1
        assert calls == ["credential"], "the credential is read after approval, once"

    def test_an_api_key_alone_never_admits(self) -> None:
        """The disabled placeholder is truthy and cannot pay; neither is approval."""
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        backend = LocalApprovalRecordBackend([_approval(plan.campaign_id)])
        with pytest.raises(CampaignError, match="not authorization to spend"):
            seal_campaign_episode(
                cfg,
                campaign=plan.manifest,
                episode=plan.runnable[0],
                task_spec=plan.task_spec_for("hallucination-mitigation"),
                graph=ARM_GRAPHS["A"],
                approval_backend=backend,
                credential_probe=SettingsCredentialProbe(cfg),
            )

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"status": ApprovalStatus.PENDING}, "status is pending"),
            ({"expires_at": "2026-09-02T00:00:00Z"}, "expired"),
            ({"stage": "stage-9-other"}, "stage does not match"),
            ({"provider": "someone-else"}, "provider does not match"),
            ({"total_cost_usd_max": "1.000000", "episode_allocation_usd_max": "1.000000",
              "workflow_allocation_usd_max": "0.500000", "judge_allocation_usd_max": "0.500000"},
             "cap is insufficient"),
        ],
    )
    def test_an_approval_that_does_not_cover_the_plan_is_refused(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        backend = LocalApprovalRecordBackend([_approval(plan.campaign_id, **overrides)])
        with pytest.raises(CampaignError, match=message):
            preflight_approval(plan, backend, verified_at="2026-09-05T00:00:00Z")

    def test_a_zero_cost_campaign_never_reads_a_credential(self) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=1)
        probe = NoCredentialProbe()
        sealed = seal_campaign_episode(
            config(),
            campaign=plan.manifest,
            episode=plan.runnable[0],
            task_spec=plan.task_spec_for("hallucination-mitigation"),
            graph=ARM_GRAPHS["A"],
            approval_backend=LocalApprovalRecordBackend(),
            credential_probe=probe,
        )
        assert not sealed.chargeable
        assert probe.calls == 0
        assert sealed.manifest.payload.approval.status_at_seal is ApprovalStatus.NOT_REQUIRED

    def test_the_zero_cost_probe_refuses_if_it_is_ever_called(self) -> None:
        """It must never run, so the thing it does when it runs is a refusal."""
        with pytest.raises(CampaignError, match="must not read a credential"):
            NoCredentialProbe()()

    def test_a_positive_cap_without_an_approval_id_is_not_expressible(self) -> None:
        with pytest.raises(CampaignError, match="stand in for authorization"):
            request(
                workflow_usd="1.000000", campaign_usd="10.000000", approval_id=None
            ) and plan_campaign(config(), request(campaign_usd="10.000000"), resolver=registry())

    def test_approval_records_load_from_a_file_outside_this_package(
        self, tmp_path: Path
    ) -> None:
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        path = tmp_path / "approvals.json"
        path.write_text(
            json.dumps([_approval(plan.campaign_id).model_dump(mode="json")]),
            encoding="utf-8",
        )
        backend = LocalApprovalRecordBackend.from_file(path)
        assert backend.record_ids == ("approval_stage-one-smoke",)
        assert preflight_approval(plan, backend, verified_at="2026-09-05T00:00:00Z")

    def test_a_malformed_approval_file_admits_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "approvals.json"
        path.write_text('{"not": "a list"}', encoding="utf-8")
        with pytest.raises(CampaignError, match="JSON list"):
            LocalApprovalRecordBackend.from_file(path)


# ---------------------------------------------------------------------------
# Cost categories and statistics
# ---------------------------------------------------------------------------


class TestCostsAreSplitAndStatisticsAreDelegated:
    def test_workflow_judge_and_harness_are_reported_separately(self) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A", "B"), repeats=1)
        reconciled = reconcile(
            plan.ledger,
            [
                _outcome(
                    plan.runnable[0],
                    CompletionStatus.SUCCEEDED,
                    workflow="0.250000",
                    judge="0.050000",
                ),
                _outcome(
                    plan.runnable[1],
                    CompletionStatus.SUCCEEDED,
                    workflow="0.350000",
                    judge="0.070000",
                ),
            ],
            reconciled_at="2026-09-05T12:00:00Z",
        )
        costs = aggregate_costs(reconciled, harness_usd="0.010000")
        assert costs.workflow_usd == "0.600000"
        assert costs.judge_usd == "0.120000"
        assert costs.harness_usd == "0.010000"
        assert costs.total_usd == "0.730000"

    def test_the_summary_reports_required_pairs_and_the_small_sample_caveat(self) -> None:
        from src.eval.stats import mcnemar_required_pairs, small_sample_caveat

        plan = planned(cases=all_case_ids(), repeats=3)
        summary = summarize(plan.manifest, plan.ledger)
        assert summary.paired_items == 60
        assert summary.required_pairs == mcnemar_required_pairs(
            delta=0.05, discordance=0.05
        )
        assert summary.small_sample_caveat == small_sample_caveat(60)
        assert "paired items" in summary.power_statement
        assert str(summary.required_pairs) in summary.power_statement

    def test_a_small_campaign_carries_the_caveat(self) -> None:
        summary = summarize(*_plan_and_ledger())
        assert summary.small_sample_caveat is not None
        assert "approximate at n=" in summary.small_sample_caveat

    def test_a_budget_stop_resumes_only_under_the_same_cap(self) -> None:
        from src.campaign.planner import budget_stop_reached

        plan = planned(cases=("hallucination-mitigation",), arms=("A", "B"), repeats=1)
        spent = reconcile(
            plan.ledger,
            [
                _outcome(
                    plan.runnable[0],
                    CompletionStatus.SUCCEEDED,
                    workflow="6.000000",
                    judge="0.000000",
                )
            ],
            reconciled_at="2026-09-05T12:00:00Z",
        )
        assert budget_stop_reached(spent, "5.000000")
        assert not budget_stop_reached(spent, "50.000000")
        assert not budget_stop_reached(spent, "0.000000")

    def test_every_arm_is_summarized_over_the_whole_denominator(self) -> None:
        plan = planned(repeats=2)
        summary = summarize(plan.manifest, plan.ledger)
        assert {arm.arm_id for arm in summary.arms} == set(ARM_IDS)
        for arm in summary.arms:
            assert arm.expected == 2 * 2
        excluded = next(arm for arm in summary.arms if arm.arm_id == "E")
        assert excluded.excluded == 4


# ---------------------------------------------------------------------------
# The sealed episode manifest
# ---------------------------------------------------------------------------


class TestTheEpisodeManifestCarriesTheCampaign:
    def test_it_pins_the_lock_the_registry_and_the_task(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        payload = plan.manifest.payload
        sealed = load_campaign(tmp_path / plan.campaign_id)[0]
        assert sealed.integrity.payload_sha256 == plan.manifest.integrity.payload_sha256
        stored = json.loads(
            (tmp_path / plan.campaign_id / episode.output_path / "run-manifest.json").read_text()
        )
        manifest = stored["payload"]
        assert manifest["campaign_lock_ref"]["digest"] == payload.lock_digest
        assert manifest["identity"]["campaign_id"] == plan.campaign_id
        registry_section = manifest["registry_resolution"]
        assert registry_section["suite_ref"]["id"] == SUITE_ID
        assert registry_section["task_case_ref"]["id"] == episode.case_id
        assert not registry_section["suite_ref"]["id"].startswith("shadow-unresolved")
        assert registry_section["split_assignment_ref"]["revision"] == "1.0.0"

    def test_the_runtime_projection_digest_matches_the_manifest(
        self, tmp_path: Path
    ) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=1)
        write_campaign(tmp_path, plan)
        sealed = seal_next_episode(
            config(),
            root=tmp_path,
            plan=plan,
            episode=plan.runnable[0],
            graph=ARM_GRAPHS["A"],
            approval_backend=LocalApprovalRecordBackend(),
        )
        assert (
            sealed.projection.integrity.payload_sha256
            == sealed.manifest.payload.policy_runtime_projection.artifact_ref.digest
        )

    def test_the_task_set_survives_a_round_trip(self, tmp_path: Path) -> None:
        plan = planned()
        write_campaign(tmp_path, plan)
        manifest, specs = load_campaign(tmp_path / plan.campaign_id)
        assert [spec.task_spec_id for spec in specs] == [
            spec.task_spec_id for spec in plan.task_specs
        ]
        assert manifest.payload.task_refs == plan.manifest.payload.task_refs

    def test_a_substituted_task_spec_is_refused_on_load(self, tmp_path: Path) -> None:
        plan = planned()
        directory = write_campaign(tmp_path, plan)
        path = directory / "task-set.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["task_specs"][0]["objective"] = "a question nobody selected"
        path.write_text(json.dumps(stored), encoding="utf-8")
        with pytest.raises(CampaignError, match="does not match its sealed ref"):
            load_campaign(directory)


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


class TestTheCommandLine:
    def test_dry_run_prints_the_plan_and_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = campaign_main(
            [
                "dry-run",
                "--registry-root",
                str(REGISTRY_ROOT),
                "--output-root",
                str(tmp_path),
                "--cases",
                "hallucination-mitigation,rag-multi-hop",
                "--repeats",
                "2",
            ]
        )
        assert code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["expected_episode_count"] == 2 * 2 * 5
        assert report["chargeable"] is False
        assert list(tmp_path.iterdir()) == []

    def test_plan_materializes_the_campaign_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            campaign_main(
                [
                    "plan",
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--output-root",
                    str(tmp_path),
                    "--cases",
                    "hallucination-mitigation",
                    "--repeats",
                    "1",
                ]
            )
            == 0
        )
        written = json.loads(capsys.readouterr().out)
        directory = Path(written["directory"])
        for name in (
            "campaign-manifest.json",
            "campaign-manifest.sha256",
            "campaign-lock.json",
            "campaign-lock.sha256",
            "task-set.json",
            "campaign-ledger.json",
        ):
            assert (directory / name).is_file(), name
        assert sorted(path.name for path in (directory / "arm-configs").iterdir()) == [
            "A.json",
            "B.json",
            "C.json",
            "D.json",
            "E.json",
        ]

        assert (
            campaign_main(
                [
                    "status",
                    "--output-root",
                    str(tmp_path),
                    "--campaign-id",
                    written["campaign_id"],
                ]
            )
            == 0
        )
        status = json.loads(capsys.readouterr().out)
        assert status["expected"] == 5
        assert status["counts"]["not_started"] == 4
        assert status["counts"]["excluded"] == 1

        assert (
            campaign_main(
                [
                    "resume",
                    "--output-root",
                    str(tmp_path),
                    "--campaign-id",
                    written["campaign_id"],
                ]
            )
            == 0
        )
        resumed = json.loads(capsys.readouterr().out)
        assert len(resumed["pending"]) == 4

    def test_a_chargeable_plan_without_approval_records_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = campaign_main(
            [
                "dry-run",
                "--registry-root",
                str(REGISTRY_ROOT),
                "--output-root",
                str(tmp_path),
                "--cases",
                "hallucination-mitigation",
                "--repeats",
                "1",
                "--corpus-mode",
                "live",
                "--episode-workflow-usd",
                "1.000000",
                "--campaign-usd",
                "10.000000",
                "--approval-id",
                "approval_not-on-file",
            ]
        )
        assert code == 3
        assert "approval is missing" in capsys.readouterr().err

    def test_resume_and_status_require_a_campaign_id(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert campaign_main(["resume", "--output-root", str(tmp_path)]) == 2
        assert "--campaign-id is required" in capsys.readouterr().err

    def test_an_unknown_arm_is_refused(self, tmp_path: Path) -> None:
        assert (
            campaign_main(
                [
                    "dry-run",
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--output-root",
                    str(tmp_path),
                    "--arms",
                    "A,Z",
                ]
            )
            == 3
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan_and_ledger() -> tuple[Any, DenominatorLedger]:
    plan = planned()
    return plan.manifest, plan.ledger


def _sealed_episode(root: Path) -> tuple[CampaignPlan, Any]:
    """A materialized one-arm campaign with its single episode sealed."""
    plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=1)
    write_campaign(root, plan)
    episode = plan.runnable[0]
    seal_next_episode(
        config(),
        root=root,
        plan=plan,
        episode=episode,
        graph=ARM_GRAPHS["A"],
        approval_backend=LocalApprovalRecordBackend(),
    )
    return plan, episode


def _write_completion(
    root: Path, plan: CampaignPlan, episode: Any, status: CompletionStatus
) -> None:
    directory = root / plan.campaign_id / episode.output_path
    stored = json.loads((directory / "run-manifest.json").read_text(encoding="utf-8"))
    receipt = CompletionReceipt(
        run_id=episode.run_id,
        manifest_digest=stored["integrity"]["payload_sha256"],
        status=status,
        reason=None if status is CompletionStatus.SUCCEEDED else RunReason.UNKNOWN,
        completed_at="2026-09-05T12:00:00Z",
        accumulated_workflow_cost_usd="0.000000",
        accumulated_judge_cost_usd="0.000000",
    )
    (directory / "completion.json").write_text(
        receipt.model_dump_json(), encoding="utf-8"
    )


def _outcome(
    episode: Any,
    status: CompletionStatus,
    reason: RunReason | None = None,
    *,
    metric: bool = True,
    workflow: str = "0.000000",
    judge: str = "0.000000",
) -> EpisodeOutcome:
    return EpisodeOutcome(
        episode_key=episode.episode_key,
        run_id=episode.run_id,
        status=status,
        reason=reason,
        workflow_cost_usd=workflow,
        judge_cost_usd=judge,
        primary_metric_available=metric,
    )


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------
#
# Every model in this package validates itself, and each validator exists
# because the invalid state it rejects would produce a campaign whose
# numbers cannot be trusted. A validator with no test is a comment, so
# each one is constructed invalid here and asserted to refuse.


def _rebuilt(model: Any, **overrides: Any) -> Any:
    """Re-run a contract model's validators with some fields replaced.

    `model_copy(update=...)` deliberately skips validation, which is the
    wrong tool for testing a validator. This re-invokes the constructor
    with the model's own nested objects, so strict mode is satisfied and
    only the named field is different.
    """
    fields = {name: getattr(model, name) for name in type(model).model_fields}
    fields.update(overrides)
    return type(model)(**fields)


class TestTheManifestRefusesAnIncoherentCampaign:
    def test_a_lineage_that_is_not_a_rerun_cannot_name_a_rerun_parent(self) -> None:
        base = CampaignLineage(
            kind="cap_raised",
            supersedes_campaign_id="camp_abc",
            supersedes_manifest_digest="sha256:" + "0" * 64,
            reason="stage 1 approved a larger cap",
        )
        with pytest.raises(ValueError, match="only a rerun carries"):
            _rebuilt(base, rerun_of_campaign_id="camp_abc")
        with pytest.raises(ValueError, match="same campaign"):
            _rebuilt(base, kind="rerun", rerun_of_campaign_id="camp_other")

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"case_ids": ("a", "a")}, "case ids must be non-empty and unique"),
            ({"arms": ("A", "A")}, "arms must be non-empty and unique"),
            (
                {"campaign_budget": default_campaign_budget("0.000000"),
                 "approval_id": "approval_something"},
                "cannot carry an approval id",
            ),
        ],
    )
    def test_the_protocol_refuses_an_incoherent_design(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        protocol = planned().manifest.payload.protocol
        with pytest.raises(ValueError, match=message):
            _rebuilt(protocol, **overrides)

    def test_the_protocol_refuses_a_suite_ref_that_is_not_a_suite(self) -> None:
        protocol = planned().manifest.payload.protocol
        wrong = protocol.suite_ref.model_copy(update={"kind": "task_set"})
        with pytest.raises(ValueError, match="must reference a benchmark suite"):
            _rebuilt(protocol, suite_ref=wrong)

    def test_the_protocol_refuses_an_episode_cap_above_the_campaign_cap(self) -> None:
        protocol = plan_campaign(
            config(),
            request(
                workflow_usd="1.000000",
                judge_usd="0.500000",
                campaign_usd="30.000000",
                approval_id="approval_stage-one",
            ),
            resolver=registry(),
        ).manifest.payload.protocol
        with pytest.raises(ValueError, match="spend the whole campaign cap"):
            _rebuilt(protocol, campaign_budget=default_campaign_budget("1.000000"))

    @pytest.mark.parametrize(
        ("field", "message"),
        [
            ("protocol_digest", "protocol digest does not address"),
            ("lock_digest", "lock digest does not address"),
        ],
    )
    def test_a_digest_that_addresses_nothing_is_refused(
        self, field: str, message: str
    ) -> None:
        payload = planned().manifest.payload
        with pytest.raises(ValueError, match=message):
            _rebuilt(payload, **{field: "sha256:" + "0" * 64})

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"expected_episode_count": 999}, "not cases x repeats x arms"),
            ({"planned_episode_count": 1}, "not cases x repeats x runnable arms"),
            ({"excluded_episode_count": 99}, "do not account for the matrix"),
            ({"campaign_id": "camp_someone-elses"}, "not derived from this protocol"),
        ],
    )
    def test_the_counts_and_the_id_must_follow_from_the_design(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        payload = planned().manifest.payload
        with pytest.raises(ValueError, match=message):
            _rebuilt(payload, **overrides)

    def test_a_manifest_whose_arms_are_not_the_protocols_is_refused(self) -> None:
        payload = planned().manifest.payload
        with pytest.raises(ValueError, match="do not match the protocol"):
            _rebuilt(payload, arms=payload.arms[:-1])

    def test_a_task_set_that_is_not_one_spec_per_case_is_refused(self) -> None:
        payload = planned().manifest.payload
        with pytest.raises(ValueError, match="one TaskSpec per selected case"):
            _rebuilt(payload, task_refs=payload.task_refs[:1])
        with pytest.raises(ValueError, match="compiled to the same TaskSpec"):
            _rebuilt(payload, task_refs=(payload.task_refs[0], payload.task_refs[0]))

    def test_a_validation_receipt_for_another_lock_is_refused(self) -> None:
        payload = planned().manifest.payload
        other = payload.registry_validation_receipt.model_copy(
            update={"lock_digest": "sha256:" + "0" * 64}
        )
        with pytest.raises(ValueError, match="validated a different lock"):
            _rebuilt(payload, registry_validation_receipt=other)

    def test_a_validation_receipt_ref_that_addresses_nothing_is_refused(self) -> None:
        payload = planned().manifest.payload
        ref = payload.registry_validation_receipt_ref
        with pytest.raises(ValueError, match="does not address the receipt"):
            _rebuilt(
                payload,
                registry_validation_receipt_ref=ref.model_copy(
                    update={"digest": "sha256:" + "0" * 64}
                ),
            )

    def test_a_tampered_envelope_no_longer_validates(self) -> None:
        from src.campaign.manifest import CampaignIntegrity, CampaignManifestV1

        manifest = planned().manifest
        with pytest.raises(ValueError, match="does not address its payload"):
            CampaignManifestV1(
                integrity=CampaignIntegrity(payload_sha256="sha256:" + "0" * 64),
                payload=manifest.payload,
            )

    def test_a_missing_sidecar_or_a_moved_digest_is_not_a_campaign(
        self, tmp_path: Path
    ) -> None:
        from src.campaign.manifest import CampaignManifestStore

        store = CampaignManifestStore()
        with pytest.raises(CampaignError, match="must both exist"):
            store.load(tmp_path)
        plan = planned()
        directory = write_campaign(tmp_path, plan)
        (directory / "campaign-manifest.sha256").write_text(
            "sha256:" + "0" * 64 + "  campaign-manifest.json\n", encoding="utf-8"
        )
        with pytest.raises(CampaignError, match="sidecar mismatch"):
            store.load(directory)

    def test_an_unparseable_manifest_is_refused(self, tmp_path: Path) -> None:
        from src.campaign.manifest import CampaignManifestStore

        plan = planned()
        directory = write_campaign(tmp_path, plan)
        (directory / "campaign-manifest.json").write_text("{", encoding="utf-8")
        with pytest.raises(CampaignError, match="manifest is invalid"):
            CampaignManifestStore().load(directory)


class TestTheMatrixAndLedgerRefuseIncoherentSlots:
    def test_a_planned_episode_must_explain_itself(self) -> None:
        episode = planned().episodes[0]
        runnable = next(item for item in planned().episodes if item.runnable)
        with pytest.raises(ValueError, match="must name its reason"):
            _rebuilt(runnable, runnable=False, exclusion_reason=None)
        excluded = next(item for item in planned().episodes if not item.runnable)
        with pytest.raises(ValueError, match="cannot carry an exclusion reason"):
            _rebuilt(excluded, runnable=True)
        with pytest.raises(ValueError, match="must reference a task case"):
            _rebuilt(
                runnable,
                case_ref=episode.case_ref.model_copy(update={"kind": "task_set"}),
            )

    def test_a_negative_rerun_generation_is_refused(self) -> None:
        from src.campaign.matrix import derive_run_id

        with pytest.raises(CampaignError, match="non-negative"):
            derive_run_id("sha256:" + "0" * 64, rerun_index=-1)

    def test_an_excluded_slot_has_nothing_to_rerun(self) -> None:
        excluded = next(item for item in planned().episodes if not item.runnable)
        with pytest.raises(CampaignError, match="nothing to rerun"):
            rerun_of(excluded)

    def test_an_empty_matrix_is_refused(self) -> None:
        from src.campaign.matrix import compile_matrix

        payload = planned().manifest.payload
        with pytest.raises(CampaignError, match="at least one arm and one case"):
            compile_matrix(
                campaign_id=payload.campaign_id,
                arms=(),
                case_refs=payload.lock.case_refs,
                task_refs={},
                repeats=1,
                seed=1,
            )
        with pytest.raises(CampaignError, match="repeats must be positive"):
            compile_matrix(
                campaign_id=payload.campaign_id,
                arms=payload.arms,
                case_refs=payload.lock.case_refs,
                task_refs={},
                repeats=0,
                seed=1,
            )

    def test_a_case_without_a_compiled_task_spec_is_refused(self) -> None:
        from src.campaign.matrix import compile_matrix

        payload = planned().manifest.payload
        with pytest.raises(CampaignError, match="without a compiled TaskSpec"):
            compile_matrix(
                campaign_id=payload.campaign_id,
                arms=payload.arms,
                case_refs=payload.lock.case_refs,
                task_refs={},
                repeats=1,
                seed=1,
            )

    def test_a_null_metric_must_say_why(self) -> None:
        from src.campaign.ledger import EpisodeScoreReceipt

        with pytest.raises(ValueError, match="must say why"):
            EpisodeScoreReceipt(
                run_id="run_" + "a" * 32, primary_metric_available=False
            )

    def test_a_ledger_entry_pairs_exclusion_with_its_reason(self) -> None:
        entry = planned().ledger.entries[0]
        excluded = next(
            item
            for item in planned().ledger.entries
            if item.status is LedgerStatus.EXCLUDED
        )
        with pytest.raises(ValueError, match="must name its reason"):
            _rebuilt(entry, status=LedgerStatus.EXCLUDED, exclusion_reason=None)
        with pytest.raises(ValueError, match="only an excluded episode"):
            _rebuilt(excluded, status=LedgerStatus.COMPLETED)

    def test_a_report_that_loses_an_episode_is_refused(self) -> None:

        report = planned().ledger.report
        with pytest.raises(ValueError, match="do not sum to the accounted total"):
            _rebuilt(report, accounted=report.accounted + 1, expected=report.expected + 1)
        with pytest.raises(ValueError, match="must be accounted"):
            _rebuilt(report, expected=report.expected + 1)
        with pytest.raises(ValueError, match="drops more than the exclusions"):
            _rebuilt(report, analysis_denominator=0)

    def test_a_ledger_whose_entries_do_not_match_its_report_is_refused(self) -> None:
        ledger = planned().ledger
        with pytest.raises(ValueError, match="do not match the expected denominator"):
            _rebuilt(ledger, entries=ledger.entries[:-1])
        with pytest.raises(ValueError, match="duplicate episode keys"):
            _rebuilt(ledger, entries=(ledger.entries[0],) * len(ledger.entries))

    def test_a_campaign_with_no_episodes_has_no_denominator(self) -> None:
        from src.campaign.ledger import open_ledger

        with pytest.raises(CampaignError, match="no denominator"):
            open_ledger(
                campaign_id="camp_empty", episodes=(), written_at="2026-09-05T00:00:00Z"
            )

    def test_an_excluded_episode_that_produced_an_outcome_is_corruption(self) -> None:
        plan = planned()
        excluded = next(
            item for item in plan.ledger.entries if item.status is LedgerStatus.EXCLUDED
        )
        stray = EpisodeOutcome(
            episode_key=excluded.episode_key,
            run_id=excluded.run_id,
            status=CompletionStatus.SUCCEEDED,
        )
        with pytest.raises(CampaignError, match="excluded episode produced an outcome"):
            reconcile(plan.ledger, [stray], reconciled_at="2026-09-05T00:00:00Z")

    def test_an_outcome_whose_run_id_moved_is_refused(self) -> None:
        plan = planned()
        outcome = _outcome(plan.runnable[0], CompletionStatus.SUCCEEDED).model_copy(
            update={"run_id": "run_" + "b" * 32}
        )
        with pytest.raises(CampaignError, match="does not match the planned run"):
            reconcile(plan.ledger, [outcome], reconciled_at="2026-09-05T00:00:00Z")

    def test_an_invalid_receipt_is_not_a_missing_one(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        directory = tmp_path / plan.campaign_id / episode.output_path
        (directory / "completion.json").write_text("{}", encoding="utf-8")
        rebuilt = rebuild_plan(*load_campaign(tmp_path / plan.campaign_id))
        with pytest.raises(CampaignError, match="completion receipt for"):
            read_outcomes(tmp_path / plan.campaign_id, rebuilt.ledger)

    def test_an_invalid_score_sidecar_is_refused(self, tmp_path: Path) -> None:
        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        directory = tmp_path / plan.campaign_id / episode.output_path
        (directory / "scores.json").write_text("[]", encoding="utf-8")
        rebuilt = rebuild_plan(*load_campaign(tmp_path / plan.campaign_id))
        with pytest.raises(CampaignError, match="score receipt"):
            read_outcomes(tmp_path / plan.campaign_id, rebuilt.ledger)


class TestArmDeclarationsRefuseIncoherence:
    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"selector": "fixed_evidence"}, "arm id and selector do not match"),
            ({"status": "capability_missing"}, "must name what is missing"),
            ({"missing_capabilities": ("something",)}, "only a capability_missing arm"),
            ({"runnable": False}, "is runnable"),
        ],
    )
    def test_a_runnable_arm_declaration_is_checked(
        self, overrides: dict[str, Any], message: str
    ) -> None:
        arm = declare_arm("A", graph=ARM_GRAPHS["A"])
        with pytest.raises(ValueError, match=message):
            _rebuilt(arm, **overrides)

    def test_a_capability_missing_arm_cannot_be_runnable(self) -> None:
        arm = declare_arm("E", graph=ARM_GRAPHS["E"])
        with pytest.raises(ValueError, match="cannot be runnable"):
            _rebuilt(arm, runnable=True)

    def test_an_available_arm_must_cite_a_graph(self) -> None:
        arm = declare_arm("A", graph=ARM_GRAPHS["A"])
        with pytest.raises(ValueError, match="must cite the graph"):
            _rebuilt(arm, graph_digest=None)

    def test_an_unprobed_arm_is_unverified_rather_than_available(self) -> None:
        arm = declare_arm("C")
        assert arm.status == "unverified"
        assert arm.runnable
        assert arm.graph_digest is None

    def test_classifying_arm_e_refuses_whatever_the_graph_looks_like(self) -> None:
        from src.campaign.arms import classify_arm

        with pytest.raises(CampaignError, match="capability_missing"):
            classify_arm(config(), "E", ARM_GRAPHS["D"])

    def test_arm_settings_that_will_not_load_are_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.campaign.arms as arms_module

        def _refuse(values: Any) -> Settings:
            raise ValueError("contrived")

        monkeypatch.setattr(arms_module.Settings, "model_validate", _refuse)
        with pytest.raises(CampaignError, match="arm A settings are not loadable"):
            arm_settings(config(), "A")


class TestThePlannerRefusesWhatItCannotProve:
    def test_a_case_with_no_compiled_spec_is_named(self) -> None:
        with pytest.raises(CampaignError, match="no TaskSpec was compiled"):
            planned().task_spec_for("a-case-nobody-selected")

    def test_a_dry_run_must_enumerate_every_slot(self) -> None:

        report = dry_run(planned())
        with pytest.raises(ValueError, match="must enumerate every planned episode"):
            _rebuilt(report, episodes=report.episodes[:-1])

    def test_resuming_an_absent_campaign_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(CampaignError, match="no campaign directory"):
            resume_campaign(tmp_path, campaign_id="camp_never-planned")

    def test_a_campaign_directory_without_a_task_set_is_refused(
        self, tmp_path: Path
    ) -> None:
        plan = planned()
        directory = write_campaign(tmp_path, plan)
        (directory / "task-set.json").unlink()
        with pytest.raises(CampaignError, match="no compiled task set"):
            load_campaign(directory)

    def test_an_unparseable_task_set_is_refused(self, tmp_path: Path) -> None:
        plan = planned()
        directory = write_campaign(tmp_path, plan)
        (directory / "task-set.json").write_text("{", encoding="utf-8")
        with pytest.raises(CampaignError, match="task set is invalid"):
            load_campaign(directory)

    def test_a_task_set_of_the_wrong_length_is_refused(self, tmp_path: Path) -> None:
        from src.campaign.planner import CampaignTaskSet

        plan = planned()
        directory = write_campaign(tmp_path, plan)
        (directory / "task-set.json").write_text(
            CampaignTaskSet(
                campaign_id=plan.campaign_id, task_specs=plan.task_specs[:1]
            ).model_dump_json(),
            encoding="utf-8",
        )
        with pytest.raises(CampaignError, match="does not match the manifest"):
            load_campaign(directory)

    def test_resuming_an_episode_with_no_sealed_manifest_is_refused(
        self, tmp_path: Path
    ) -> None:
        plan = planned(cases=("hallucination-mitigation",), arms=("A",), repeats=1)
        write_campaign(tmp_path, plan)
        with pytest.raises(CampaignError, match="no resumable manifest"):
            resume_episode(
                tmp_path, campaign_id=plan.campaign_id, episode=plan.runnable[0]
            )

    def test_an_invalid_completion_receipt_blocks_the_resume_decision(
        self, tmp_path: Path
    ) -> None:
        plan, episode = _sealed_episode(tmp_path)
        directory = tmp_path / plan.campaign_id / episode.output_path
        (directory / "completion.json").write_text("[]", encoding="utf-8")
        with pytest.raises(CampaignError, match="completion receipt is invalid"):
            resume_episode(
                tmp_path, campaign_id=plan.campaign_id, episode=episode
            )

    def test_an_incoherent_episode_budget_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="episode budget is not coherent"):
            default_episode_budget(
                config(enable_supervisor=False), ("A",), workflow_usd="1.00"
            )

    def test_the_pending_summary_counts_what_is_left(self, tmp_path: Path) -> None:
        from src.campaign.planner import pending_summary

        plan, episode = _sealed_episode(tmp_path)
        _write_completion(tmp_path, plan, episode, CompletionStatus.SUCCEEDED)
        _, pending = resume_campaign(tmp_path, campaign_id=plan.campaign_id)
        counts = pending_summary(plan, pending)
        assert counts["expected"] == 1
        assert counts["planned"] == 1
        assert counts["pending"] == 0
        assert counts["already_complete"] == 1

    def test_campaign_spend_sums_the_reconciled_entries(self) -> None:
        from decimal import Decimal

        from src.campaign.episode import campaign_spend

        plan = planned(cases=("hallucination-mitigation",), arms=("A", "B"), repeats=1)
        reconciled = reconcile(
            plan.ledger,
            [
                _outcome(
                    plan.runnable[0],
                    CompletionStatus.SUCCEEDED,
                    workflow="0.100000",
                    judge="0.020000",
                )
            ],
            reconciled_at="2026-09-05T00:00:00Z",
        )
        assert campaign_spend(reconciled.entries) == Decimal("0.120000")

    def test_the_null_task_store_keeps_nothing_and_says_so(self) -> None:
        from src.campaign.episode import _NullTaskStore

        store = _NullTaskStore()
        spec = planned().task_specs[0]
        assert store.put(spec) is None
        assert store.get(spec.task_spec_id) is None

    def test_a_lock_that_resolves_the_wrong_number_of_refs_is_refused(self) -> None:
        from src.campaign.episode import registry_resolution

        payload = planned().manifest.payload
        stripped = payload.lock.model_copy(
            update={
                "resolved_refs": tuple(
                    ref for ref in payload.lock.resolved_refs if ref.kind != "task_set"
                )
            }
        )
        sources = None
        with pytest.raises(CampaignError, match="expected one"):
            registry_resolution(stripped, payload.lock.case_refs[0], sources)

    def test_sealing_an_excluded_episode_is_refused(self) -> None:
        plan = planned()
        excluded = next(item for item in plan.episodes if not item.runnable)
        with pytest.raises(CampaignError, match="is excluded"):
            seal_campaign_episode(
                config(),
                campaign=plan.manifest,
                episode=excluded,
                task_spec=plan.task_spec_for(excluded.case_id),
                graph=ARM_GRAPHS[excluded.arm_id],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_sealing_against_another_campaigns_task_spec_is_refused(self) -> None:
        plan = planned()
        other = planned(cases=all_case_ids()[:3])
        episode = plan.runnable[0]
        with pytest.raises(CampaignError, match="not the one this episode was planned"):
            seal_campaign_episode(
                config(),
                campaign=plan.manifest,
                episode=episode,
                task_spec=other.task_specs[0],
                graph=ARM_GRAPHS[episode.arm_id],
                approval_backend=LocalApprovalRecordBackend(),
            )

    def test_an_unreadable_approval_file_admits_nothing(self, tmp_path: Path) -> None:
        with pytest.raises(CampaignError, match="unreadable"):
            LocalApprovalRecordBackend.from_file(tmp_path / "absent.json")

    def test_an_approval_file_of_the_wrong_shape_admits_nothing(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "approvals.json"
        path.write_text('[{"approval_id": "nope"}]', encoding="utf-8")
        with pytest.raises(CampaignError, match="file is invalid"):
            LocalApprovalRecordBackend.from_file(path)

    def test_an_approval_scope_that_does_not_add_up_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="not internally consistent"):
            campaign_approval_record(
                approval_id="approval_bad-scope",
                campaign_id="camp_abc",
                stage="stage-0",
                provider="anthropic",
                total_cost_usd_max="1.000000",
                episode_allocation_usd_max="5.000000",
                workflow_allocation_usd_max="1.000000",
                judge_allocation_usd_max="1.000000",
                approved_by="owner",
                approved_at="2026-09-01T00:00:00Z",
                expires_at="2026-12-01T00:00:00Z",
            )

    def test_an_approval_record_with_a_backwards_window_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="record is invalid"):
            campaign_approval_record(
                approval_id="approval_backwards",
                campaign_id="camp_abc",
                stage="stage-0",
                provider="anthropic",
                total_cost_usd_max="1.000000",
                episode_allocation_usd_max="1.000000",
                workflow_allocation_usd_max="0.500000",
                judge_allocation_usd_max="0.500000",
                approved_by="owner",
                approved_at="2026-12-01T00:00:00Z",
                expires_at="2026-09-01T00:00:00Z",
            )

    def test_a_credential_probe_without_a_key_refuses(self) -> None:
        cfg = config().model_copy(update={"anthropic_api_key": None})
        assert isinstance(cfg, Settings)
        with pytest.raises(CampaignError, match="no provider credential"):
            SettingsCredentialProbe(cfg)()

    def test_the_summary_refuses_a_ledger_from_another_campaign(self) -> None:
        first = planned()
        other = planned(cases=all_case_ids()[:3])
        with pytest.raises(CampaignError, match="different campaigns"):
            summarize(first.manifest, other.ledger)

    def test_one_summary_always_aggregates_with_itself(self) -> None:
        summary = summarize(*_plan_and_ledger())
        assert assert_aggregatable([summary]) is None

    def test_the_default_case_selection_is_the_suites_own_order(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No `--cases`: the CLI reads the registry rather than guessing."""
        assert (
            campaign_main(
                [
                    "dry-run",
                    "--registry-root",
                    str(REGISTRY_ROOT),
                    "--output-root",
                    str(tmp_path),
                    "--arms",
                    "A",
                    "--repeats",
                    "1",
                ]
            )
            == 0
        )
        report = json.loads(capsys.readouterr().out)
        assert report["expected_episode_count"] == 20
        assert [item["case_id"] for item in report["episodes"]] == list(all_case_ids())

    def test_the_cli_reads_approval_records_from_the_named_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = config(use_mock_data=False)
        plan = plan_campaign(cfg, _chargeable_request(cfg), resolver=registry())
        path = tmp_path / "approvals.json"
        path.write_text(
            json.dumps([_approval(plan.campaign_id).model_dump(mode="json")]),
            encoding="utf-8",
        )
        code = campaign_main(
            [
                "dry-run",
                "--registry-root",
                str(REGISTRY_ROOT),
                "--output-root",
                str(tmp_path),
                "--cases",
                "hallucination-mitigation",
                "--arms",
                "A",
                "--seed",
                "7",
                "--repeats",
                "1",
                "--corpus-mode",
                "live",
                "--episode-workflow-usd",
                "1.500000",
                "--episode-judge-usd",
                "0.500000",
                "--campaign-usd",
                "20.000000",
                "--approval-id",
                "approval_stage-one-smoke",
                "--approval-records",
                str(path),
            ]
        )
        assert code == 0
        assert json.loads(capsys.readouterr().out)["chargeable"] is True
