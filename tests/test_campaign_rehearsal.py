"""The funded path, walked to the credential and no further.

`docs/agent-engineering/16-w12-approval-packet-draft.md` §8 lists three
preconditions a funded arm-A baseline still owes. What it could not say
before `python -m src.campaign rehearse` existed is whether anything
*else* was missing, because the only way to find out was to fund a run
and watch it fail.

These tests hold the rehearsal to the four claims that make its answer
worth anything:

1. **It walks the real path.** The manifest it seals is sealed by
   `seal_next_episode` against a graph compiled from this checkout, not
   a fixture; the approval check is `execute_campaign`'s own pre-flight.
2. **It stops at the credential and nowhere else.** Both doors — the
   admission controller's probe and `src.llm`'s constructor — refuse
   under the zero-spend sentinel, and every step before them passes.
   The funded shape (a live corpus, positive caps, an approval record an
   owner would have created) is rehearsed too, because the zero-cost
   plan cannot exercise the approval machinery at all.
3. **It never dials and never spends.** Asserted against the harness's
   own socket guard and spend guard rather than against a promise.
4. **It leaves nothing behind.** The campaign directory is enumerated
   before and after and compared.
"""

from __future__ import annotations

import json
import pathlib
import socket
from collections.abc import Sequence
from datetime import date
from typing import Any

import pytest
from pydantic import SecretStr

from src.campaign.approval import campaign_approval_record
from src.campaign.arms import ArmId
from src.campaign.errors import CampaignError
from src.campaign.planner import (
    CampaignRequest,
    default_campaign_budget,
    default_episode_budget,
    plan_campaign,
    rebuild_plan,
    suite_case_ids,
    write_campaign,
)
from src.campaign.rehearse import (
    CREDENTIAL_BOUNDARY,
    REHEARSAL_STEPS,
    RehearsalReport,
    rehearse_campaign,
)
from src.config import Settings
from src.config import settings as shipped_settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.registry import LocalRegistry
from src.observability.logging import ALLOWED_EXTRA_KEYS, KNOWN_EVENTS

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_ROOT = REPO_ROOT / "eval_registry"
SUITE_ID = "research-policy-v1"

#: A two-case slice. The rehearsal seals exactly one episode whatever the
#: matrix size, so a sixty-slot design would buy nothing but seconds.
SLICE: tuple[str, ...] = ("hallucination-mitigation", "rag-multi-hop")

#: A date after `PRICES_LAST_VERIFIED` by more than the freshness window,
#: supplied rather than read from a clock so the price line is the same
#: sentence on every run.
TODAY = date(2026, 9, 17)


class FakeAnthropic:
    """Stands in for the SDK so `_get_client`'s real body runs.

    `tests/conftest.py`'s spend guard delegates to the real constructor
    when `src.llm.anthropic.Anthropic` has been replaced, which is the
    seam `tests/test_llm.py::TestGetClient` already uses. Installing it
    here is what makes the rehearsal's last step a test of *production*
    refusal logic rather than of the harness's.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


def config(**overrides: Any) -> Settings:
    """The shipped settings on the campaign's own no-cost surface."""
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
    if "anthropic_api_key" in overrides:
        # `model_copy` does not validate, and the field is a `SecretStr`
        # (WO-C4) that production code unwraps. A test that passed a bare
        # string would be testing an object `Settings` cannot produce.
        overrides["anthropic_api_key"] = SecretStr(str(overrides["anthropic_api_key"]))
    patched = shipped_settings.model_copy(update={**base, **overrides})
    assert isinstance(patched, Settings)
    return patched


def request_for(
    cfg: Settings,
    *,
    cases: Sequence[str] = SLICE,
    arms: tuple[ArmId, ...] = ("A",),
    corpus_mode: str = "snapshot",
    **overrides: Any,
) -> CampaignRequest:
    base = CampaignRequest(
        protocol_id="research-policy-v1-stage-0",
        stage="stage-0-qualification",
        suite_ref=suite_ref(REGISTRY_ROOT, SUITE_ID),
        case_ids=tuple(cases),
        arms=arms,
        repeats=1,
        corpus_mode=corpus_mode,  # type: ignore[arg-type]
        seed=0,
        episode_budget=default_episode_budget(cfg, arms),
        campaign_budget=default_campaign_budget(),
    )
    if not overrides:
        return base
    patched = base.model_copy(update=overrides)
    assert isinstance(patched, CampaignRequest)
    return patched


def materialize(root: pathlib.Path, cfg: Settings, req: CampaignRequest) -> str:
    plan = plan_campaign(cfg, req, resolver=LocalRegistry(REGISTRY_ROOT))
    write_campaign(root, plan)
    return plan.campaign_id


def census(directory: pathlib.Path) -> set[str]:
    return {str(path.relative_to(directory)) for path in directory.rglob("*")}


def walk(report: RehearsalReport) -> dict[str, str]:
    return {step.step: step.outcome for step in report.steps}


@pytest.fixture
def sentinel_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let `_get_client`'s real body run, against a fake SDK class."""
    import src.llm as llm_module

    monkeypatch.setattr(llm_module, "_client", None)
    monkeypatch.setattr(llm_module.anthropic, "Anthropic", FakeAnthropic)


@pytest.mark.integration
@pytest.mark.contract
class TestTheWalkStopsAtTheCredential:
    """The zero-cost campaign, rehearsed under the sentinel."""

    @pytest.fixture
    def report(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> RehearsalReport:
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        return rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

    def test_it_stops_at_the_credential_boundary(
        self, report: RehearsalReport
    ) -> None:
        assert report.stopped_at == CREDENTIAL_BOUNDARY

    def test_every_step_before_the_boundary_passed(
        self, report: RehearsalReport
    ) -> None:
        outcomes = walk(report)
        boundary = REHEARSAL_STEPS.index(CREDENTIAL_BOUNDARY)
        assert [outcomes[step] for step in REHEARSAL_STEPS[:boundary]] == [
            "passed"
        ] * boundary

    def test_both_provider_doors_refuse(self, report: RehearsalReport) -> None:
        outcomes = walk(report)
        assert outcomes["provider-credential-probed"] == "refused"
        assert outcomes["provider-client-constructed"] == "refused"

    def test_the_refusals_are_the_productions_own_words(
        self, report: RehearsalReport
    ) -> None:
        details = {step.step: step.detail for step in report.steps}
        assert "not authorization to spend" in details["provider-credential-probed"]
        assert (
            "local-preview-disabled structurally disables"
            in details["provider-client-constructed"]
        )

    def test_the_seal_is_a_real_manifest_against_a_real_graph(
        self, report: RehearsalReport
    ) -> None:
        detail = next(
            step.detail
            for step in report.steps
            if step.step == "episode-manifest-sealed"
        )
        assert "sealed against the compiled graph as sha256:" in detail

    def test_no_episode_ran_and_nothing_was_charged(
        self, report: RehearsalReport
    ) -> None:
        assert report.episodes_run == 0
        assert report.model_calls == 0
        assert report.network_calls == 0

    def test_the_message_names_the_three_owed_preconditions(
        self, report: RehearsalReport
    ) -> None:
        assert set(report.owed) == {
            "approval-record",
            "priced-model-ids",
            "measured-token-counts",
        }
        for name in report.owed:
            assert name in report.message
        assert "complete up to the credential boundary" in report.message

    def test_the_report_round_trips_as_json(
        self, report: RehearsalReport
    ) -> None:
        """The CLI prints it, so it has to survive `model_dump(mode="json")`."""
        again = RehearsalReport.model_validate_json(
            json.dumps(report.model_dump(mode="json"))
        )
        assert again == report


@pytest.mark.integration
@pytest.mark.contract
class TestTheFundedShapeReachesTheSameDoor:
    """The shape that would actually spend: live corpus, caps, approval.

    The zero-cost plan cannot exercise the approval machinery — a
    campaign with a zero cap is refused if it names an approval at all —
    so a rehearsal of it can only report that no record was needed.
    This is the other half: a campaign a funded run would be, with a
    record built the way an operator would build one, rehearsed under
    the sentinel. It is the strongest form of "nothing else is missing".
    """

    @pytest.fixture
    def report(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> RehearsalReport:
        cfg = config(use_mock_data=False)
        base = request_for(cfg, corpus_mode="live")
        funded = base.model_copy(
            update={
                "approval_id": "approval_rehearsal-fixture",
                "episode_budget": base.episode_budget.model_copy(
                    update={
                        "workflow_cost_usd_max": "1.200000",
                        "judge_cost_usd_max": "0.300000",
                        "total_cost_usd_max": "1.500000",
                        "judge_model_calls_max": 3,
                    }
                ),
                "campaign_budget": base.campaign_budget.model_copy(
                    update={"total_cost_usd_max": "75.000000"}
                ),
            }
        )
        assert isinstance(funded, CampaignRequest)
        plan = plan_campaign(cfg, funded, resolver=LocalRegistry(REGISTRY_ROOT))
        write_campaign(tmp_path, plan)
        record = campaign_approval_record(
            approval_id="approval_rehearsal-fixture",
            campaign_id=plan.campaign_id,
            stage="stage-0-qualification",
            provider="anthropic",
            total_cost_usd_max="75.000000",
            episode_allocation_usd_max="1.500000",
            workflow_allocation_usd_max="1.200000",
            judge_allocation_usd_max="0.300000",
            approved_by="rehearsal-fixture",
            approved_at="2026-09-17T00:00:00Z",
            expires_at="2027-09-17T00:00:00Z",
        )
        from src.campaign.approval import LocalApprovalRecordBackend

        return rehearse_campaign(
            cfg,
            root=tmp_path,
            campaign_id=plan.campaign_id,
            approval_backend=LocalApprovalRecordBackend([record]),
            approval_id="approval_rehearsal-fixture",
            today=TODAY,
        )

    def test_the_chargeable_campaign_also_stops_at_the_credential(
        self, report: RehearsalReport
    ) -> None:
        assert report.chargeable is True
        assert report.stopped_at == CREDENTIAL_BOUNDARY

    def test_the_approval_was_verified_against_the_plan(
        self, report: RehearsalReport
    ) -> None:
        step = next(
            item for item in report.steps if item.step == "approval-verified"
        )
        assert step.outcome == "passed"
        assert "approval_rehearsal-fixture covers this campaign" in step.detail
        assert "receipt sha256:" in step.detail

    def test_the_approval_record_is_no_longer_owed(
        self, report: RehearsalReport
    ) -> None:
        assert "approval-record" not in report.owed
        assert set(report.owed) == {"priced-model-ids", "measured-token-counts"}


@pytest.mark.integration
@pytest.mark.security
class TestTheGuardsAndTheLeavings:
    """No socket, no spend, no artifact."""

    def test_the_walk_opens_no_socket(
        self,
        tmp_path: pathlib.Path,
        sentinel_sdk: None,
        monkeypatch: pytest.MonkeyPatch,
        guard_exceptions: tuple[type[BaseException], type[BaseException]],
    ) -> None:
        """A counting spy over the harness's own guard, not a promise.

        The guard alone proves nothing escaped; the spy proves the code
        path was never taken, which is the stronger claim when the graph
        under it swallows exceptions.
        """
        network_denied, _ = guard_exceptions
        with socket.socket() as probe, pytest.raises(network_denied):
            probe.connect(("api.anthropic.com", 443))

        connects: list[str] = []
        monkeypatch.setattr(
            socket.socket, "connect", lambda *_a, **_k: connects.append("connect")
        )
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))

        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

        assert connects == []
        assert report.network_calls == 0

    def test_it_leaves_the_campaign_directory_exactly_as_it_found_it(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        directory = tmp_path / campaign_id
        before = census(directory)

        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

        assert report.artifacts_written == ()
        assert census(directory) == before

    def test_it_does_not_rewrite_the_ledger_it_reads(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        ledger = tmp_path / campaign_id / "campaign-ledger.json"
        before = ledger.read_bytes()

        rehearse_campaign(cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY)

        assert ledger.read_bytes() == before

    def test_a_credential_that_could_pay_refuses_without_an_approval(
        self, tmp_path: pathlib.Path
    ) -> None:
        cfg = config(anthropic_api_key="sk-live-looking-key")
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))

        with pytest.raises(CampaignError, match="could pay and no --approval-id"):
            rehearse_campaign(
                cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
            )

    def test_the_sentinel_is_not_what_that_refusal_is_about(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        """Refusing the zero-spend key would make the rehearsal useless."""
        cfg = config(anthropic_api_key="local-preview-disabled")
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))

        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

        assert report.stopped_at == CREDENTIAL_BOUNDARY

    def test_an_unmaterialized_campaign_is_refused(
        self, tmp_path: pathlib.Path
    ) -> None:
        with pytest.raises(CampaignError, match="is not materialized"):
            rehearse_campaign(
                config(), root=tmp_path, campaign_id="camp_nothing", today=TODAY
            )


@pytest.mark.unit
class TestTheReportIsAClosedShape:
    """A rehearsal that skipped a step could not report itself."""

    def test_every_declared_step_is_reported_in_order(self) -> None:
        assert REHEARSAL_STEPS[-1] == "provider-client-constructed"
        assert CREDENTIAL_BOUNDARY in REHEARSAL_STEPS

    def test_a_short_walk_is_not_a_report(self) -> None:
        payload = {
            "campaign_id": "camp_x",
            "directory": "/tmp/x",
            "chargeable": False,
            "stopped_at": "campaign-loaded",
            "steps": [
                {"step": "campaign-loaded", "outcome": "passed", "detail": "d"}
            ],
            "preconditions": [],
            "pending_episodes": 0,
            "message": "m",
        }
        with pytest.raises(ValueError, match="reports every declared step"):
            RehearsalReport.model_validate_json(json.dumps(payload))

    def test_an_undeclared_step_is_refused(self) -> None:
        from src.campaign.rehearse import RehearsalStep

        with pytest.raises(ValueError, match="not one of the declared"):
            RehearsalStep.model_validate_json(
                json.dumps({"step": "invented", "outcome": "passed", "detail": "d"})
            )


@pytest.mark.unit
class TestTheLogContract:
    """The two names the rehearsal emits are in the closed registry."""

    def test_both_events_are_registered(self) -> None:
        assert {
            "campaign_rehearsal_started",
            "campaign_rehearsal_stopped",
        } <= KNOWN_EVENTS

    def test_the_fields_it_binds_are_allowed(self) -> None:
        assert {"campaign_id", "stop_reason", "preconditions_owed"} <= (
            ALLOWED_EXTRA_KEYS
        )


@pytest.mark.integration
@pytest.mark.contract
class TestWhatTheRehearsalFound:
    """The seal refuses when the deployment and the design disagree.

    Not a defect in the rehearsal — it is the rehearsal's whole output.
    `corpus_mode: snapshot` resolves to the *supplied* corpus, which is
    `use_mock_data` (ADR 0041/0080); a deployment with mock mode off and
    a snapshot campaign is a design that cannot seal, and an operator
    should learn that from a rehearsal rather than from episode one.
    """

    def test_a_snapshot_campaign_under_live_retrieval_refuses_to_seal(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        cfg = config(use_mock_data=False)
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))

        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

        assert report.stopped_at == "episode-manifest-sealed"
        detail = next(
            step.detail
            for step in report.steps
            if step.step == "episode-manifest-sealed"
        )
        assert "corpus_mode=snapshot" in detail
        assert "stopped early" in report.message

    def test_the_walk_continues_past_a_refusal_so_one_run_is_enough(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        cfg = config(use_mock_data=False)
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))

        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

        outcomes = walk(report)
        assert outcomes["episode-manifest-sealed"] == "refused"
        assert outcomes["provider-credential-probed"] == "refused"
        assert outcomes["provider-client-constructed"] == "refused"


@pytest.mark.integration
@pytest.mark.contract
class TestThePreconditionsAreDerived:
    """None of the three is transcribed from the packet."""

    @pytest.fixture
    def report(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> RehearsalReport:
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        return rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )

    def test_the_price_line_reads_the_tables_own_date(
        self, report: RehearsalReport
    ) -> None:
        from src.observability.costs import PRICES_LAST_VERIFIED

        line = next(
            item
            for item in report.preconditions
            if item.precondition == "priced-model-ids"
        )
        assert PRICES_LAST_VERIFIED in line.detail
        assert line.owed is True

    def test_the_ids_are_pinned_even_though_the_prices_are_not(
        self, report: RehearsalReport
    ) -> None:
        from src.llm_models import MODEL_CAPABILITIES

        line = next(
            item
            for item in report.preconditions
            if item.precondition == "priced-model-ids"
        )
        assert f"{len(MODEL_CAPABILITIES)} rows, 0 undescribed" in line.detail

    def test_the_token_line_reads_the_campaigns_completed_count(
        self, report: RehearsalReport
    ) -> None:
        line = next(
            item
            for item in report.preconditions
            if item.precondition == "measured-token-counts"
        )
        assert line.owed is True
        assert "0 episode(s) of this campaign have completed" in line.detail

    def test_the_case_set_the_slice_uses_is_in_the_suite(self) -> None:
        """Guards the slice above from naming a case the registry dropped."""
        assert set(SLICE) <= set(suite_case_ids(REGISTRY_ROOT, SUITE_ID))

    def test_a_rebuilt_plan_is_what_the_rehearsal_walked(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        """The pending count is the plan's, not a number the walk invented."""
        cfg = config()
        req = request_for(cfg)
        campaign_id = materialize(tmp_path, cfg, req)
        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )
        from src.campaign.planner import load_campaign

        plan = rebuild_plan(*load_campaign(tmp_path / campaign_id))
        assert report.pending_episodes == len(plan.runnable)


@pytest.mark.integration
@pytest.mark.contract
class TestTheVerb:
    """`python -m src.campaign rehearse` prints the report and nothing else."""

    def test_the_cli_walks_and_prints_json(
        self,
        tmp_path: pathlib.Path,
        sentinel_sdk: None,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import src.campaign.cli as cli_module
        from src.campaign.cli import EXIT_OK, main

        cfg = config()
        monkeypatch.setattr(cli_module, "shipped_settings", cfg)
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        capsys.readouterr()

        code = main(
            [
                "rehearse",
                "--campaign-id",
                campaign_id,
                "--output-root",
                str(tmp_path),
            ]
        )

        assert code == EXIT_OK
        report = RehearsalReport.model_validate_json(capsys.readouterr().out)
        assert report.campaign_id == campaign_id
        assert report.stopped_at == CREDENTIAL_BOUNDARY
        assert report.artifacts_written == ()

    def test_rehearse_without_a_campaign_id_is_a_usage_error(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from src.campaign.cli import EXIT_USAGE, main

        assert main(["rehearse"]) == EXIT_USAGE
        assert "--campaign-id is required" in capsys.readouterr().err

    def test_the_verb_is_one_of_the_parsers_choices(self) -> None:
        from src.campaign.cli import _parser

        parsed = _parser().parse_args(["rehearse", "--campaign-id", "camp_x"])
        assert parsed.command == "rehearse"


@pytest.mark.integration
@pytest.mark.security
class TestWhatAnOpenDoorLooksLike:
    """The other side of the boundary, without ever using a real key.

    A rehearsal under a credential that *could* pay reports the doors as
    open rather than refusing — and that answer has to be tested, or the
    only thing these tests prove is that a disabled key is disabled. The
    key here is a string with no account behind it and the SDK class is a
    fake, so nothing is constructed that could dial and nothing is called.
    """

    @pytest.fixture
    def report(
        self,
        tmp_path: pathlib.Path,
        sentinel_sdk: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> RehearsalReport:
        import src.llm as llm_module

        cfg = config(anthropic_api_key="sk-no-account-behind-this")
        # Both doors, because they do not read the same object: the
        # admission probe reads the campaign's `Settings` and the gateway
        # reads the process-global singleton. A deployment with a real key
        # has one `.env` behind both; a test has to set both or it is
        # only testing half the boundary.
        monkeypatch.setattr(llm_module, "settings", cfg)
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        return rehearse_campaign(
            cfg,
            root=tmp_path,
            campaign_id=campaign_id,
            approval_id="approval_operator-claim",
            today=TODAY,
        )

    def test_the_walk_reaches_the_end(self, report: RehearsalReport) -> None:
        assert report.stopped_at == REHEARSAL_STEPS[-1]
        assert set(walk(report).values()) == {"passed"}

    def test_it_says_the_door_is_open_rather_than_saying_nothing(
        self, report: RehearsalReport
    ) -> None:
        details = {step.step: step.detail for step in report.steps}
        assert "open at this door" in details["provider-credential-probed"]
        assert "no call was made with it" in details["provider-client-constructed"]
        assert "without refusing" in report.message

    def test_the_gateway_door_says_which_settings_it_read(
        self, report: RehearsalReport
    ) -> None:
        """The asymmetry is reported, not smoothed over.

        `src.llm` is not in `execute_campaign`'s `SETTINGS_CONSUMERS`, so
        a campaign's own `Settings` never reaches the gateway. Two
        credentials in one process is the case that makes the admission
        probe and the client disagree, and the rehearsal names it.
        """
        from src.campaign.execute import SETTINGS_CONSUMERS

        assert "src.llm" not in SETTINGS_CONSUMERS
        detail = next(
            step.detail
            for step in report.steps
            if step.step == "provider-client-constructed"
        )
        assert "process-global settings" in detail

    def test_the_named_record_is_reported_against_the_backend(
        self, report: RehearsalReport
    ) -> None:
        detail = next(
            step.detail for step in report.steps if step.step == "approval-verified"
        )
        assert "approval_operator-claim is absent from the backend" in detail

    def test_an_open_door_does_not_close_a_precondition(
        self, report: RehearsalReport
    ) -> None:
        """A key is not an approval, and a rehearsal never says otherwise."""
        assert "approval-record" in report.owed
        assert "Nothing in this repository authorizes spending" in report.message


@pytest.mark.unit
class TestThePriceLineIsOwedByConstruction:
    """`_message` has no "nothing outstanding" branch, and cannot need one."""

    def test_every_rehearsal_owes_at_least_the_price_line(
        self, tmp_path: pathlib.Path, sentinel_sdk: None
    ) -> None:
        cfg = config()
        campaign_id = materialize(tmp_path, cfg, request_for(cfg))
        report = rehearse_campaign(
            cfg, root=tmp_path, campaign_id=campaign_id, today=TODAY
        )
        assert "priced-model-ids" in report.owed
        assert report.owed != ()

    def test_a_stop_at_a_step_no_rehearsal_declares_is_refused(self) -> None:
        payload = {
            "campaign_id": "camp_x",
            "directory": "/tmp/x",
            "chargeable": False,
            "stopped_at": "somewhere-else",
            "steps": [
                {"step": step, "outcome": "passed", "detail": "d"}
                for step in REHEARSAL_STEPS
            ],
            "preconditions": [],
            "pending_episodes": 0,
            "message": "m",
        }
        with pytest.raises(ValueError, match="is not a rehearsal step"):
            RehearsalReport.model_validate_json(json.dumps(payload))
