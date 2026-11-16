"""Frozen exposed v19 campaign controls, with synthetic offline responses only."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import fields

import httpx
import pytest
from jsonschema import Draft202012Validator

from src.workspace import assistance_comparison_contract as codec
from src.workspace import assistance_consistency_checks as checks
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_adapter import checker_context, initial_context
from src.workspace.d5_campaign_v19_packet import predecessor, upgrade
from src.workspace.d5_comparison_transport import (
    ComparisonCampaignTransport,
    checker_payload,
    draft_payload,
)
from src.workspace.d5_operations import wire
from src.workspace.grounding import EvidenceRef
from src.workspace.material import SourceMaterial, SourceSpan
from src.workspace.provider_schema_compat import guard

pytestmark = pytest.mark.unit


def materials():
    names = {f.name for f in fields(SourceMaterial)}
    return tuple(
        SourceMaterial(
            **{
                k: (tuple(SourceSpan(**s) for s in v) if k == "spans" else v)
                for k, v in row.items()
                if k in names
            }
        )
        for row in predecessor()["materials"]
    )


@pytest.mark.parametrize("index", range(10))
def test_all_frozen_workflow_inputs_use_v19_and_current_response_checker(index):
    old = predecessor()["cases"][index]
    untouched = deepcopy(old)
    sealed = upgrade(old["sealed"])
    assert sealed["units"] == old["sealed"]["units"]
    assert sealed["assistance"]["task_context"] == old["sealed"]["assistance"]["task_context"]
    assert sealed["task_policy"][codec.KEY] == codec.REVISION
    assert sealed["schema_revision"] == "workspace-assistance-keyed-v16"
    context = initial_context(sealed)
    payload = draft_payload(context)
    assert "comparison_claims" not in payload["response"]
    assert "comparison_basis" not in payload["response"]
    guard(sealed["candidate_initial_wire"])
    codec.resolve_draft(
        payload,
        {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
        materials(),
        purpose=sealed["response_purpose"],
        policy=sealed["task_policy"],
    )
    checked = checker_context(sealed, payload, materials())
    assert checked["checker_normalization_revision"] == checks.NORMALIZATION_REVISION
    current = checked["checked_response_digest"]
    verdict = checker_payload(checked, negative=True)
    normalized = checks.normalize(verdict, checked)
    assert normalized["coverage_critiques"]
    final = checker_payload(checked)
    parsed = checks.Checks.model_validate(checks.normalize(final, checked))
    assert checks.aggregate(parsed, checked)["quality_gate"] == "PASS"
    from src.workspace.d5_capacity_policy import ROUTES

    guard(wire(checked, ROUTES))
    Draft202012Validator(checks.schemas(checked)["wire"]).validate(final)
    assert current == checked["checked_response_digest"]
    if payload["response"].get("claims"):
        altered = deepcopy(payload)
        altered["response"]["claims"][0]["text"] += " Fresh synthetic repair wording."
        assert checker_context(sealed, altered, materials())["checked_response_digest"] != current
    assert old == untouched


def test_comparison_claim_each_has_two_works_and_source_notes_receive_no_comparison_credit():
    old = next(c for c in predecessor()["cases"] if c["id"] == "campaign-dev-compare")
    sealed = upgrade(old["sealed"])
    payload = draft_payload(initial_context(sealed))
    comparison = next(
        p for p in sealed["task_policy"]["requested_parts"] if p["kind"] == "comparison"
    )
    row = payload["response"]["coverage"][comparison["id"]]
    for claim_id in row["answer_claim_ids"]:
        claim = payload["response"]["claims"][int(claim_id[1:]) - 1]
        assert len({sealed["units"][h]["work_id"] for h in claim["handles"]}) >= 2
    bad = deepcopy(payload)
    bad["response"]["coverage"][comparison["id"]].update(
        answer_claim_ids=["c1", "c2"], context_claim_ids=["c3"]
    )
    with pytest.raises(ValueError, match="comparison"):
        codec.resolve_draft(
            bad,
            {k: EvidenceRef(**v) for k, v in sealed["units"].items()},
            materials(),
            purpose=sealed["response_purpose"],
            policy=sealed["task_policy"],
        )


def test_v19_upgrade_requires_new_encoding_without_touching_legacy():
    old = predecessor()["cases"][0]["sealed"]
    with pytest.raises(AdmissionError, match="encoding_required"):
        upgrade(old, union_safe=False)
    assert old["task_policy"].get(codec.KEY) != codec.REVISION


@pytest.mark.asyncio
async def test_mock_transport_retains_exact_count_body_and_complete_long_output():
    sealed = upgrade(predecessor()["cases"][1]["sealed"])
    body = sealed["candidate_initial_wire"]
    count = {k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}}
    transport = ComparisonCampaignTransport("synthetic-pair", repair_all=True)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport), trust_env=False
    ) as client:
        assert (
            await client.post("https://offline.invalid/v1/messages/count_tokens", json=count)
        ).json() == {"input_tokens": 100}
        response = (await client.post("https://offline.invalid/v1/messages", json=body)).json()
    assert json.loads(transport.request_bodies[0]) == count
    assert json.loads(transport.request_bodies[1]) == body
    assert transport.contacts[0][1] == _digest(count)
    assert len(response["content"][0]["text"].encode()) > 1000
    assert transport.schema_validations[0]["errors"] == []


@pytest.mark.integration
def test_preserved_full_snapshot_freeze_capture_and_rehashed_drift_controls():
    import os

    from src.workspace.d5_benchmark import read
    from src.workspace.d5_campaign_v19_extension import SNAPSHOT_DIGEST
    from src.workspace.d5_campaign_v19_packet import capture, verify_packet
    from tests.d5_campaign_gate import storage
    from tests.d5_comparison_gate import SNAPSHOT, setup

    if not SNAPSHOT.exists() or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL"):
        pytest.skip("preserved owner-local snapshot and disposable test Postgres required")
    snapshot = read(SNAPSHOT)
    assert _digest(snapshot) == SNAPSHOT_DIGEST
    with storage() as store:
        packet = setup(store, snapshot, authorize=False)
        assert capture(store, snapshot["program_id"], snapshot) == snapshot
        assert packet["schedule"] == predecessor()["schedule"]
        assert [c["cohort"] for c in packet["cases"]] == ["development"] * 2 + [
            "evaluation_exposed_corpus"
        ] * 8
        assert len(packet["probe_references"]) == 20
        assert (
            sorted(r["reference"] for r in packet["probe_references"].values())
            == ["supported"] * 10 + ["unsupported"] * 10
        )
        for change in (
            "counts",
            "question",
            "ranking",
            "source",
            "probe",
            "threshold",
            "basis",
            "period",
            "holds",
            "wire",
        ):
            bad = deepcopy(packet)
            if change == "counts":
                bad["limits"]["counts"] += 1
            elif change == "question":
                bad["cases"][2]["question"] += " Changed."
            elif change == "ranking":
                bad["cases"][2]["ranking"] = {}
            elif change == "source":
                bad["cases"][2]["sealed"]["units"] = {}
            elif change == "probe":
                next(iter(bad["probe_references"].values()))["reference"] = "abstain"
            elif change == "threshold":
                bad["scoring"] = {}
            elif change == "basis":
                bad["campaign_extension"]["core"]["basis"]["counts"] += 1
            elif change == "period":
                bad["campaign_extension"]["core"]["period_limits"]["day_usd"] = "23"
            elif change == "holds":
                bad["campaign_extension"]["core"]["retained_exceptions"] = []
            else:
                bad["wire_encoding_revision"] = "workspace-assistance-consistency-wire-v18"
            bad["campaign_extension"]["proposal_digest"] = _digest(
                bad["campaign_extension"]["core"]
            )
            bad["packet_digest"] = _digest({k: v for k, v in bad.items() if k != "packet_digest"})
            with pytest.raises(AdmissionError):
                verify_packet(bad)


def test_actual_discovery_replays_all_eight_frozen_rank_and_read_selections():
    from src.workspace.d5_campaign_v19_packet import verify_discovery

    verify_discovery(predecessor())


@pytest.mark.parametrize("control", ["rank", "read"])
def test_actual_discovery_rejects_mutated_rank_or_read_code(monkeypatch, control):
    from src.workspace import d5_evidence, mode_ranking
    from src.workspace.d5_campaign_v19_packet import verify_discovery

    called = []
    if control == "rank":
        original = mode_ranking.rank_mode_items

        def changed(*args, **kwargs):
            called.append(True)
            return list(reversed(original(*args, **kwargs)))

        monkeypatch.setattr(mode_ranking, "rank_mode_items", changed)
    else:
        original_select = d5_evidence.select

        def changed_select(*args, **kwargs):
            called.append(True)
            value = original_select(*args, **kwargs)
            return {**value, "selected": []}

        monkeypatch.setattr(d5_evidence, "select", changed_select)
    with pytest.raises(AdmissionError, match="actual_discovery_replay_drift"):
        verify_discovery(predecessor())
    assert called
