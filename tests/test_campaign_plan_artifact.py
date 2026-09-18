"""The published plan artifact is the registry's answer, byte for byte.

`campaigns/w12-arm-a-baseline.plan.json` is the design
`docs/agent-engineering/16-w12-approval-packet-draft.md` §1 describes,
written where a reviewer can read it in a diff. A checked-in file
derived from a registry is a file that can rot silently: the suite gains
a case, a digest moves, an arm's settings row changes, and the artifact
goes on describing a campaign nobody can plan any more.

So nothing here reads the file for its expectations. Every test
re-derives the artifact from `eval_registry/` through the same code the
CLI runs and compares. The equality is *byte* equality rather than
object equality on purpose: the file is read by people, and a change in
key order or indentation that leaves the objects equal is still a change
to what they read.

The two fields the artifact deliberately omits — `episode_key` and
`run_id` — get their own test, because "we left these out" is a claim
that has to be checked in both directions: they must be absent from the
file, and the reason must still be true of the plan.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.campaign.baseline import (
    VOLATILE_FIELDS,
    W12_BASELINE_ARMS,
    W12_BASELINE_ARTIFACT_PATH,
    W12_BASELINE_LIVE_ARTIFACT_PATH,
    W12_BASELINE_LIVE_CORPUS_MODE,
    W12_BASELINE_REPEATS,
    CampaignPlanArtifact,
    arm_declaration_digest,
    artifact_command,
    baseline_request,
    build_plan_artifact,
    build_w12_baseline_artifact,
    is_w12_baseline,
    render_plan_artifact,
    write_plan_artifact,
)
from src.campaign.cli import _config
from src.campaign.errors import CampaignError
from src.campaign.planner import dry_run, plan_campaign
from src.contracts.registry import LocalRegistry

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_ROOT = REPO_ROOT / "eval_registry"
ARTIFACT = REPO_ROOT / W12_BASELINE_ARTIFACT_PATH
LIVE_ARTIFACT = REPO_ROOT / W12_BASELINE_LIVE_ARTIFACT_PATH

#: 16 §1's own arithmetic, spelled out rather than read off the artifact.
EXPECTED_CASES = 20
EXPECTED_EPISODES = EXPECTED_CASES * W12_BASELINE_REPEATS * len(W12_BASELINE_ARMS)


@pytest.fixture(scope="module")
def derived() -> CampaignPlanArtifact:
    """The artifact re-derived from the registry, once for the module."""
    return build_w12_baseline_artifact(_config(), registry_root=REGISTRY_ROOT)


@pytest.fixture(scope="module")
def stored() -> dict[str, Any]:
    """The checked-in file, parsed. Never a source of an expectation."""
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


@pytest.mark.integration
@pytest.mark.contract
class TestTheArtifactIsTheRegistrysAnswer:
    """The whole point: the file and the tree cannot drift apart."""

    def test_the_file_is_the_bytes_the_builder_produces(
        self, derived: CampaignPlanArtifact
    ) -> None:
        assert ARTIFACT.read_text(encoding="utf-8") == render_plan_artifact(derived), (
            "campaigns/w12-arm-a-baseline.plan.json is not what the registry "
            "derives today. Regenerate it with the command the file's "
            "`produced_by` field names, and read the diff before committing: a "
            "moved digest means the campaign a reader of 16 §1 would plan is "
            "not the campaign that document describes."
        )

    def test_the_command_in_the_file_is_the_command_that_writes_it(
        self, stored: dict[str, Any]
    ) -> None:
        request = baseline_request(_config(), registry_root=REGISTRY_ROOT)
        assert stored["produced_by"] == artifact_command(
            request, output=W12_BASELINE_ARTIFACT_PATH
        )

    def test_regenerating_it_is_idempotent(
        self, derived: CampaignPlanArtifact, tmp_path: pathlib.Path
    ) -> None:
        """Two writes of one artifact are the same file, not merely equal."""
        first = write_plan_artifact(tmp_path / "a" / "plan.json", derived)
        second = write_plan_artifact(tmp_path / "b" / "plan.json", derived)
        assert first.read_bytes() == second.read_bytes()


@pytest.mark.integration
@pytest.mark.contract
class TestTheScopeIsTheOneThePacketDescribes:
    """16 §1's table, checked against the artifact rather than quoted."""

    def test_it_is_arm_a_only_and_sixty_episodes(
        self, stored: dict[str, Any]
    ) -> None:
        assert [arm["arm_id"] for arm in stored["arms"]] == ["A"]
        assert stored["repeats"] == W12_BASELINE_REPEATS
        assert len(stored["case_ids"]) == EXPECTED_CASES
        assert stored["expected_episode_count"] == EXPECTED_EPISODES
        assert stored["planned_episode_count"] == EXPECTED_EPISODES
        assert stored["excluded_episode_count"] == 0
        assert len(stored["design"]) == EXPECTED_EPISODES

    def test_the_case_set_is_the_task_sets_own_order(
        self, stored: dict[str, Any]
    ) -> None:
        from src.campaign.planner import suite_case_ids

        assert tuple(stored["case_ids"]) == suite_case_ids(
            REGISTRY_ROOT, "research-policy-v1"
        )

    def test_the_arm_declaration_digest_is_the_arms_own(
        self, derived: CampaignPlanArtifact, stored: dict[str, Any]
    ) -> None:
        """The digest replicate groups are derived from, not a new hash."""
        plan = plan_campaign(
            _config(),
            baseline_request(_config(), registry_root=REGISTRY_ROOT),
            resolver=LocalRegistry(REGISTRY_ROOT),
        )
        expected = arm_declaration_digest(plan.manifest.payload.arms)
        assert stored["arm_declaration_digest"] == expected
        assert derived.arm_declaration_digest == expected
        assert [arm.declaration_digest for arm in derived.arms] == [
            arm.declaration_digest for arm in plan.manifest.payload.arms
        ]

    def test_the_digests_are_the_sealed_manifests(
        self, stored: dict[str, Any]
    ) -> None:
        plan = plan_campaign(
            _config(),
            baseline_request(_config(), registry_root=REGISTRY_ROOT),
            resolver=LocalRegistry(REGISTRY_ROOT),
        )
        payload = plan.manifest.payload
        assert stored["campaign_id"] == payload.campaign_id
        assert stored["protocol_digest"] == payload.protocol_digest
        assert stored["lock_digest"] == payload.lock_digest


@pytest.mark.unit
class TestAPublishedPlanAuthorizesNothing:
    """The properties that make an artifact safe to commit."""

    def test_the_file_declares_zero_everywhere(self, stored: dict[str, Any]) -> None:
        assert stored["chargeable"] is False
        assert stored["approval_id"] is None
        assert stored["provider_initialized"] is False
        assert stored["network_calls"] == 0
        assert stored["campaign_budget"]["total_cost_usd_max"] == "0.000000"
        for field in (
            "total_cost_usd_max",
            "workflow_cost_usd_max",
            "judge_cost_usd_max",
        ):
            assert stored["episode_budget"][field] == "0.000000"

    def test_the_type_refuses_a_positive_cap(
        self, derived: CampaignPlanArtifact
    ) -> None:
        """Not a convention: a chargeable plan cannot be expressed here."""
        payload = derived.model_dump(mode="json")
        payload["campaign_budget"]["total_cost_usd_max"] = "75.000000"
        with pytest.raises(ValueError, match="declares no spend"):
            CampaignPlanArtifact.model_validate_json(json.dumps(payload))

    def test_the_type_refuses_a_partial_design(
        self, derived: CampaignPlanArtifact
    ) -> None:
        payload = derived.model_dump(mode="json")
        payload["design"] = payload["design"][:10]
        with pytest.raises(ValueError, match="every planned slot"):
            CampaignPlanArtifact.model_validate_json(json.dumps(payload))

    def test_a_chargeable_plan_cannot_be_published(self) -> None:
        """The refusal a funded twin meets if it is ever pointed here.

        `CampaignProtocol` already refuses a zero-cap plan that names an
        approval, so the only way to reach a plan with an approval id is
        to make it genuinely chargeable — which is exactly the plan this
        file must never hold.
        """
        cfg = _config()
        request = baseline_request(cfg, registry_root=REGISTRY_ROOT)
        funded = request.model_copy(
            update={
                "approval_id": "approval_pretend",
                "episode_budget": request.episode_budget.model_copy(
                    update={
                        "workflow_cost_usd_max": "1.200000",
                        "judge_cost_usd_max": "0.300000",
                        "total_cost_usd_max": "1.500000",
                        "judge_model_calls_max": 3,
                    }
                ),
                "campaign_budget": request.campaign_budget.model_copy(
                    update={"total_cost_usd_max": "75.000000"}
                ),
            }
        )
        plan = plan_campaign(cfg, funded, resolver=LocalRegistry(REGISTRY_ROOT))
        assert plan.manifest.payload.protocol.chargeable
        with pytest.raises(CampaignError, match="cannot claim an approval"):
            build_plan_artifact(
                plan,
                request=funded,
                produced_by="python -m src.campaign dry-run",
                derived_from=str(REGISTRY_ROOT),
            )


@pytest.mark.integration
@pytest.mark.contract
class TestWhatTheArtifactDeliberatelyOmits:
    """`episode_key` and `run_id`, and the reason they cannot be published."""

    def test_neither_volatile_field_is_in_the_file(self) -> None:
        raw = ARTIFACT.read_text(encoding="utf-8")
        for name in ("episode_key", "run_id"):
            assert f'"{name}"' not in raw

    def test_the_file_names_both_omissions_and_says_why(
        self, stored: dict[str, Any]
    ) -> None:
        assert tuple(stored["volatile_fields_omitted"]) == VOLATILE_FIELDS
        assert any("compiled_at" in line for line in VOLATILE_FIELDS)

    def test_the_reason_is_still_true_of_a_plan(self) -> None:
        """Two plans of one protocol differ in exactly the omitted fields.

        The claim the omission rests on, checked rather than asserted: if
        these two ever stopped moving, the artifact would be poorer than
        it needs to be and this test would say so.
        """
        cfg = _config()
        request = baseline_request(cfg, registry_root=REGISTRY_ROOT)
        registry = LocalRegistry(REGISTRY_ROOT)
        # An hour apart, because `compile_case_task` stamps to the second
        # and two plans inside one second do agree — which is a fact about
        # the stamp's resolution rather than about the digest's inputs.
        noon = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
        first = dry_run(plan_campaign(cfg, request, resolver=registry, now=noon))
        second = dry_run(
            plan_campaign(
                cfg, request, resolver=registry, now=noon + timedelta(hours=1)
            )
        )

        assert first.campaign_id == second.campaign_id
        assert first.protocol_digest == second.protocol_digest
        assert first.lock_digest == second.lock_digest
        assert [item.output_path for item in first.episodes] == [
            item.output_path for item in second.episodes
        ]
        assert [item.episode_key for item in first.episodes] != [
            item.episode_key for item in second.episodes
        ]
        assert [item.run_id for item in first.episodes] != [
            item.run_id for item in second.episodes
        ]


@pytest.mark.unit
class TestTheArtifactDescribesItself:
    """The prose in the file is derived from the scope, not typed."""

    def test_the_w12_scope_earns_the_packet_preface(
        self, stored: dict[str, Any]
    ) -> None:
        assert "16-w12-approval-packet-draft.md §1" in stored["describes"]
        assert f"{EXPECTED_EPISODES} episodes" in stored["describes"]
        assert "authorizes nothing" in stored["describes"]

    def test_another_scope_does_not_claim_to_be_the_packets(self) -> None:
        cfg = _config()
        other = baseline_request(cfg, registry_root=REGISTRY_ROOT, repeats=1)
        assert not is_w12_baseline(other)
        plan = plan_campaign(cfg, other, resolver=LocalRegistry(REGISTRY_ROOT))
        artifact = build_plan_artifact(
            plan,
            request=other,
            produced_by=artifact_command(other, output="campaigns/other.json"),
            derived_from=str(REGISTRY_ROOT),
        )
        assert "16-w12-approval-packet-draft.md" not in artifact.describes
        assert f"{EXPECTED_CASES} episodes" in artifact.describes

    def test_an_unknown_arm_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="unknown arms"):
            baseline_request(
                _config(),
                registry_root=REGISTRY_ROOT,
                arms=("Z",),  # type: ignore[arg-type]
            )


@pytest.mark.integration
@pytest.mark.contract
class TestTheVerbThatWritesIt:
    """`dry-run --artifact` is the only thing dry-run writes."""

    def test_dry_run_writes_the_artifact_and_nothing_else(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import src.campaign.cli as cli_module
        from src.campaign.cli import EXIT_OK, main

        monkeypatch.setattr(cli_module, "shipped_settings", _config())
        target = tmp_path / "published" / "plan.json"
        before = set(tmp_path.rglob("*"))

        code = main(
            [
                "dry-run",
                "--arms",
                "A",
                "--repeats",
                str(W12_BASELINE_REPEATS),
                "--output-root",
                str(tmp_path / "campaigns"),
                "--artifact",
                str(target),
            ]
        )

        assert code == EXIT_OK
        assert str(target) in capsys.readouterr().out
        assert set(tmp_path.rglob("*")) - before == {target.parent, target}
        written = json.loads(target.read_text(encoding="utf-8"))
        assert written["chargeable"] is False
        assert written["expected_episode_count"] == EXPECTED_EPISODES

    def test_the_verb_reproduces_the_checked_in_file(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The command in `produced_by` is the command that writes it."""
        import src.campaign.cli as cli_module
        from src.campaign.cli import EXIT_OK, main

        monkeypatch.setattr(cli_module, "shipped_settings", _config())
        target = tmp_path / W12_BASELINE_ARTIFACT_PATH
        argv = [
            "dry-run",
            "--suite",
            "research-policy-v1",
            "--arms",
            ",".join(W12_BASELINE_ARMS),
            "--repeats",
            str(W12_BASELINE_REPEATS),
            "--seed",
            "0",
            "--corpus-mode",
            "snapshot",
            "--artifact",
            str(target),
        ]
        assert main([*argv, "--output-root", str(tmp_path / "unused")]) == EXIT_OK

        produced = json.loads(target.read_text(encoding="utf-8"))
        stored_file = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        # `produced_by` names the path it was asked to write, which is a
        # tmp_path here; everything the registry fixes must be identical.
        produced.pop("produced_by")
        stored_file.pop("produced_by")
        assert produced == stored_file

    def test_plan_refuses_the_flag(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import src.campaign.cli as cli_module
        from src.campaign.cli import EXIT_REFUSED, main

        monkeypatch.setattr(cli_module, "shipped_settings", _config())
        code = main(
            [
                "plan",
                "--arms",
                "A",
                "--repeats",
                "1",
                "--cases",
                "hallucination-mitigation",
                "--output-root",
                str(tmp_path / "campaigns"),
                "--artifact",
                str(tmp_path / "plan.json"),
            ]
        )

        assert code == EXIT_REFUSED
        assert "--artifact belongs to dry-run" in capsys.readouterr().err
        assert not (tmp_path / "plan.json").exists()


@pytest.mark.unit
class TestTheSuiteResolverFailsClosed:
    """`suite_case_ids` refuses a ref that resolves to the wrong thing.

    Both branches are fail-closed guards over a registry this repository
    controls, so neither fires in normal use — which is exactly why they
    need a test: a guard nothing exercises is a guard nobody knows is
    inverted.
    """

    class _Envelope:
        def __init__(self, payload: Any) -> None:
            self.payload = payload

    def test_a_ref_that_is_not_a_benchmark_suite_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.campaign.planner import suite_case_ids
        from src.contracts import registry as registry_module

        def resolve(self: Any, ref: Any, **kwargs: Any) -> Any:
            return TestTheSuiteResolverFailsClosed._Envelope("not a suite")

        monkeypatch.setattr(registry_module.LocalRegistry, "resolve", resolve)
        with pytest.raises(CampaignError, match="did not resolve to a benchmark suite"):
            suite_case_ids(REGISTRY_ROOT, "research-policy-v1")

    def test_a_task_set_ref_that_is_not_a_task_set_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.campaign.planner import suite_case_ids
        from src.contracts import registry as registry_module
        from src.contracts.benchmark_adapters import suite_ref

        real = registry_module.LocalRegistry.resolve
        suite = real(
            registry_module.LocalRegistry(REGISTRY_ROOT),
            suite_ref(REGISTRY_ROOT, "research-policy-v1"),
            role=registry_module.RegistryRole.EVALUATOR,
            intended_use=registry_module.IntendedUse.DEVELOPMENT,
        ).payload
        seen: list[int] = []

        def resolve(self: Any, ref: Any, **kwargs: Any) -> Any:
            seen.append(1)
            payload = suite if len(seen) == 1 else "not a task set"
            return TestTheSuiteResolverFailsClosed._Envelope(payload)

        monkeypatch.setattr(registry_module.LocalRegistry, "resolve", resolve)
        with pytest.raises(CampaignError, match="did not resolve to a task set"):
            suite_case_ids(REGISTRY_ROOT, "research-policy-v1")


@pytest.mark.unit
class TestTheRecordedRegistryRoot:
    """`derived_from` is the repository's name for the path, not the shell's."""

    def test_an_absolute_path_inside_the_tree_is_recorded_relatively(self) -> None:
        from src.campaign.baseline import repo_relative

        assert repo_relative(REGISTRY_ROOT) == "eval_registry"

    def test_a_path_outside_the_tree_is_recorded_as_given(
        self, tmp_path: pathlib.Path
    ) -> None:
        from src.campaign.baseline import repo_relative

        assert repo_relative(tmp_path) == str(tmp_path)

    def test_the_checked_in_file_names_the_repositorys_registry(
        self, stored: dict[str, Any]
    ) -> None:
        assert stored["derived_from"] == "eval_registry"


@pytest.mark.integration
@pytest.mark.contract
class TestTheLiveVariantIsPublishedBesideIt:
    """Two plans, one decision, and neither of them approved (W20b).

    W20 found that 16 §1's planned `corpus_mode=snapshot` resolves to
    `USE_MOCK_DATA=true`: the funded run the packet describes would
    charge nothing and measure nothing, while §5's source-drift clause
    is about a corpus only the `live` variant plans. The remedy is not
    to rewrite §1 — the owner has not chosen — so the live design is
    published beside the snapshot one and held to the same byte
    equality, and the packet presents them side by side.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def live(cls) -> CampaignPlanArtifact:
        return build_w12_baseline_artifact(
            _config(),
            registry_root=REGISTRY_ROOT,
            output=W12_BASELINE_LIVE_ARTIFACT_PATH,
            corpus_mode=W12_BASELINE_LIVE_CORPUS_MODE,
        )

    def test_the_live_file_is_the_bytes_the_builder_produces(
        self, live: CampaignPlanArtifact
    ) -> None:
        assert LIVE_ARTIFACT.read_text(encoding="utf-8") == render_plan_artifact(live), (
            "campaigns/w12-arm-a-baseline-live.plan.json is not what the "
            "registry derives today. Regenerate it with the command the "
            "file's `produced_by` field names and read the diff."
        )

    def test_the_two_plans_differ_in_the_corpus_mode_and_its_consequences(
        self, live: CampaignPlanArtifact, stored: dict[str, Any]
    ) -> None:
        """Same design, one field apart — which is what makes them a choice.

        The identities that *derive* from the corpus mode are expected to
        move: the campaign id, the sealed protocol digest and the
        registry lock digest all take it as input, and a variant that
        left them alone would not be a different campaign.
        """
        published = json.loads(LIVE_ARTIFACT.read_text(encoding="utf-8"))
        assert published["corpus_mode"] == "live"
        assert stored["corpus_mode"] == "snapshot"
        derived_identities = {
            "campaign_id",
            "corpus_mode",
            "describes",
            "lock_digest",
            "produced_by",
            "protocol_digest",
        }
        moved = {key for key in stored if stored[key] != published.get(key)}
        assert moved == derived_identities
        assert published["design"] == stored["design"]
        assert published["case_ids"] == stored["case_ids"]
        assert published["arm_declaration_digest"] == stored["arm_declaration_digest"]
        assert live.campaign_id != stored["campaign_id"]

    def test_the_live_plan_authorizes_no_more_than_the_other_one(self) -> None:
        """A live corpus is not a funded one: still zero, still unapproved."""
        published = json.loads(LIVE_ARTIFACT.read_text(encoding="utf-8"))
        assert published["chargeable"] is False
        assert published["approval_id"] is None
        assert published["network_calls"] == 0
        assert published["provider_initialized"] is False
        assert published["campaign_budget"]["total_cost_usd_max"] == "0.000000"
        for field in (
            "total_cost_usd_max",
            "workflow_cost_usd_max",
            "judge_cost_usd_max",
        ):
            assert published["episode_budget"][field] == "0.000000"

    def test_the_live_scope_is_published_as_the_funded_baseline(self) -> None:
        """The funded baseline identity follows the declared live scope."""
        published = json.loads(LIVE_ARTIFACT.read_text(encoding="utf-8"))
        assert not published["describes"].startswith("The funded arm-A baseline of")
        request = baseline_request(
            _config(),
            registry_root=REGISTRY_ROOT,
            corpus_mode=W12_BASELINE_LIVE_CORPUS_MODE,
        )
        assert is_w12_baseline(request)
        assert published["produced_by"] == artifact_command(
            request, output=W12_BASELINE_LIVE_ARTIFACT_PATH
        )
