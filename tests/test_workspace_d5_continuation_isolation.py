"""Protected disposable rehearsal of the actual ten-case continuation protocol."""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import d5_campaign, d5_freeze
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_case_isolation import _contact_accounting
from src.workspace.d5_comparison_transport import assert_paired_contacts
from src.workspace.d5_continuation_policy import CASE_MAP
from tests.d5_case_isolation_fixtures import FaultTransport, job_ledger
from tests.d5_case_isolation_fixtures import continuation_factory as _factory
from tests.d5_case_isolation_fixtures import fixture_campaign as fixture_campaign
from tests.d5_case_isolation_fixtures import prepared_campaign as prepared_campaign

DEVELOPMENT = "continuation-v20-dev-learn"
EVALUATION = "continuation-v20-research-memory"
SEMANTIC_FAILURE = "answered_requires_complete_answer_without_gaps"
pytestmark = pytest.mark.integration


async def test_actual_v20_packet_without_recorded_scope_cannot_dispatch(prepared_campaign):
    store, packet = prepared_campaign
    calls = {}
    with pytest.raises(AdmissionError, match="campaign_active_external_authorization_required"):
        await d5_campaign.run(store, packet, offline=True, transport_factory=_factory(calls))
    assert calls == {}


@pytest.mark.timeout(240)
async def test_actual_v20_complete_scope_preserves_exact_10_job_28_pair_denominator(
    fixture_campaign,
):
    store, packet, compiled = fixture_campaign
    calls = {}
    report = await d5_campaign.run(
        store, packet, offline=True, transport_factory=_factory(calls, repair_all=True)
    )
    assert report["stop"] is None, report["stop"]
    assert list(calls) == list(compiled) == list(CASE_MAP)
    assert len(report["outcomes"]) == 10
    assert report["denominators"]["evaluation_workflows"] == 4
    assert report["denominators"]["completed_workflows"] == 4
    assert report["denominators"]["probe_records"] == 20
    assert report["accounting"]["new_scope"]["messages"] == 28
    assert report["accounting"]["new_scope"]["counts"] == 28
    assert report["accounting"]["new_scope"]["unknown_usd"] == "0"
    assert report["accounting"]["retained_hold_usd"] == "2.275066"
    assert report["human_labels"] is None
    for key, handler in calls.items():
        data, _ = job_ledger(store, report["outcomes"][key]["job_id"])
        expected = 1 if compiled[key]["stage"] == "D" else 4
        assert_paired_contacts(data["adapter"], handler, expected)


@pytest.mark.timeout(240)
async def test_wire_valid_early_evaluation_failure_preserves_and_continues_once(fixture_campaign):
    from src.workspace.d5_adapter import D5Adapter

    store, packet, compiled = fixture_campaign
    calls = {}
    factory = _factory(calls, EVALUATION, "semantic", repair_all=True)
    report = await d5_campaign.run(store, packet, offline=True, transport_factory=factory)
    assert report["stop"] is None, report["stop"]
    assert list(calls) == list(compiled)
    assert len(report["outcomes"]) == len(compiled)
    outcome = report["outcomes"][EVALUATION]
    assert outcome["state"] == "failed"
    assert outcome["quality_acceptance"] is None and outcome["pipeline_contract_accepted"] is False
    failure = outcome["content_rejection"]
    assert (failure["case_id"], failure["stage"], failure["local_stage"]) == (
        EVALUATION,
        "C",
        "draft",
    )
    assert failure["classification"] == "isolated_evaluation_first_draft_semantic_failure"
    assert failure["reason_code"] == SEMANTIC_FAILURE
    assert failure["accepted"] is False
    assert len(calls[EVALUATION].contacts) == 2
    assert sum(key.startswith("continuation-v20-probe-") for key in calls) == 4
    assert report["denominators"]["completed_workflows"] == 3
    assert report["denominators"]["failed_workflows"] == 1
    failed_parts = [part for part in report["parts"] if part["case_id"] == EVALUATION]
    assert failed_parts and all(part["behavior"] == "UNSCORED" for part in failed_parts)
    assert report["accounting"]["new_scope"]["messages"] == 25
    assert report["accounting"]["new_scope"]["counts"] == 25
    assert report["accounting"]["new_scope"]["unknown_usd"] == "0"
    assert report["accounting"]["retained_hold_usd"] == "2.275066"
    data, reservation = job_ledger(store, outcome["job_id"])
    assert data["adapter"]["steps"] == [] and data["result"] is None
    assert reservation[-2:] == (0, "failed")
    assert_paired_contacts(data["adapter"], calls[EVALUATION], 1)

    def forbidden_factory(key):
        raise AssertionError("sealed identity was dispatched twice")

    repeated = await d5_campaign.run(
        store, packet, offline=True, transport_factory=forbidden_factory
    )
    assert repeated["outcomes"] == report["outcomes"]

    # Assert that corruption fails the closed-journal proof even after HTTP 200.
    entry = compiled[EVALUATION]
    adapter = D5Adapter(
        store,
        entry["owner"],
        d5_freeze.restore_input(entry["input"]),
        transport=httpx.MockTransport(calls[EVALUATION]),
    )
    for mutation, code in (
        ("contact_state", "complete_contact_journal"),
        ("count_body", "paired_request_or_model_binding"),
        ("raw_digest", "response_body_receipt_drift"),
        ("accounting", "failed_accounting_receipt_drift"),
    ):
        changed = deepcopy(data)
        count, message = changed["adapter"]["contacts"]
        if mutation == "contact_state":
            message["state"] = "dispatching"
        elif mutation == "count_body":
            count["body"]["model"] = "substituted-model"
        elif mutation == "raw_digest":
            message["http_body_receipt"]["received_sha256"] = "0" * 64
        else:
            changed["accounting_audits"]["completed-failure"]["checker_usd"] = "1"
        with pytest.raises(AdmissionError, match=code):
            _contact_accounting(adapter, changed, reservation)
    with pytest.raises(AdmissionError, match="failed_accounting_receipt_drift"):
        _contact_accounting(adapter, data, (*reservation[:3], 1, "failed"))


@pytest.mark.parametrize(
    ("bad_case", "fault", "stage", "reason"),
    [
        (DEVELOPMENT, "semantic", "draft", SEMANTIC_FAILURE),
        (DEVELOPMENT, "missing_checker", "check", None),
        (EVALUATION, "missing_checker", "check", None),
        (EVALUATION, "wire_invalid", "draft", "validation_error"),
        (EVALUATION, "max_tokens", "draft", "max_tokens"),
        (EVALUATION, "usage", "draft", "invalid_or_unpriced_usage"),
        (EVALUATION, "model", "draft", "invalid_or_unpriced_usage"),
        (EVALUATION, "transport", "draft", "ReadTimeout"),
        (EVALUATION, "http_400", "draft", "http_400"),
        (EVALUATION, "count_fit", "draft", "input_measurement_exceeds_cap_or_invalid"),
        (EVALUATION, "cancel", "draft", "campaign_cancelled"),
    ],
)
async def test_systemic_failures_stop_without_more_dispatch(
    fixture_campaign,
    bad_case,
    fault,
    stage,
    reason,
):
    store, packet, compiled = fixture_campaign
    calls = {}
    factory = _factory(calls, bad_case, fault)
    report = await d5_campaign.run(store, packet, offline=True, transport_factory=factory)
    assert list(calls) == list(compiled)[: list(compiled).index(bad_case) + 1]
    stop = report["stop"]
    assert stop["case_id"] == bad_case
    assert stop["stage"] == compiled[bad_case]["stage"]
    assert stop["local_stage"] == stage
    if reason:
        assert stop["reason_code"] == reason
    assert stop["automatic_retries"] == 0
    assert bad_case not in report["outcomes"]
    scope = "d5-" + packet["packet_digest"][:24]
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT state,data->'campaign_stop' FROM workspace_d5_scopes WHERE scope_id=%s",
            (scope,),
        ).fetchone()
    assert row == ("stopped", stop)
    with pytest.raises(AdmissionError, match="active_external_authorization_required"):
        await d5_campaign.run(store, packet, offline=True, transport_factory=factory)


async def test_missing_revision_in_durable_authority_stops_before_factory(fixture_campaign):
    store, packet, _ = fixture_campaign
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_d5_scopes SET data=data #- '{authorization_record,campaign_revision}' "
            "WHERE scope_id=%s",
            ("d5-" + packet["packet_digest"][:24],),
        )
    calls = {}
    # The stored authorization digest is checked before entering the case loop.
    with pytest.raises(AdmissionError, match="^continuation_registered_scope_binding_drift$"):
        await d5_campaign.run(
            store, packet, offline=True, transport_factory=_factory(calls, EVALUATION, "semantic")
        )
    assert calls == {}
    with store.pool.connection() as conn:
        assert conn.execute(
            "SELECT count(*) FROM workspace_d5_case_runs WHERE scope_id=%s",
            ("d5-" + packet["packet_digest"][:24],),
        ).fetchone() == (0,)


async def test_complete_negative_quality_development_keeps_its_bound_verdict(fixture_campaign):
    store, packet, _ = fixture_campaign
    calls = {}
    bad = FaultTransport(CASE_MAP[DEVELOPMENT], fault="negative_quality")
    bad.scenario = "final_negative"
    factory = _factory(calls, "", "")

    def transport(key):
        if key == DEVELOPMENT:
            calls[key] = bad
            return bad
        return factory(key)

    report = await d5_campaign.run(
        store, packet, offline=True, transport_factory=transport, checkpoint_after=3
    )
    assert report["stop"] is None, report["stop"]
    assert report["outcomes"][DEVELOPMENT]["state"] == "failed"
    assert report["outcomes"][DEVELOPMENT]["content_rejection"]["classification"] == (
        "complete_negative_quality_verdict"
    )
    assert report["outcomes"][EVALUATION]["state"] == "ready"
    assert len(bad.contacts) == 8


@pytest.mark.parametrize(
    ("mutation", "reason", "local_stage", "state"),
    [
        ("expiry", "d5_scope_missing_revoked_expired_or_drifted", "case_start", "stopped"),
        (
            "revocation",
            "campaign_v20_progression_authorization_binding_drift",
            "dispatch_gate",
            "revoked",
        ),
        ("unbound_activity", "continuation_post_baseline_activity_drift", "case_start", "stopped"),
        ("source_drift", "source_material_changed_or_inaccessible", "case_start", "stopped"),
        ("packet_drift", "continuation_frozen_protocol_drift", "dispatch_gate", "stopped"),
    ],
)
async def test_mid_campaign_global_gate_has_exact_next_case_and_no_new_contact(
    fixture_campaign,
    mutation,
    reason,
    local_stage,
    state,
):
    from src.workspace.executor import ExecutorError

    store, packet, compiled = fixture_campaign
    scope = "d5-" + packet["packet_digest"][:24]
    next_case = list(compiled)[1]
    second = compiled[next_case]
    calls = {}

    def progress(outcome):
        assert outcome["case_id"] == DEVELOPMENT
        with store.pool.connection() as conn:
            if mutation == "expiry":
                conn.execute(
                    "UPDATE workspace_d5_scopes SET expires_at=clock_timestamp() "
                    "- interval '1 second' WHERE scope_id=%s",
                    (scope,),
                )
            elif mutation == "revocation":
                conn.execute(
                    "UPDATE workspace_d5_scopes SET state='revoked' WHERE scope_id=%s", (scope,)
                )
            elif mutation == "source_drift":
                conn.execute(
                    "UPDATE workspace_material SET content_hash='synthetic-drift' WHERE material_id=%s",
                    (second["input"]["sources"][0]["material_id"],),
                )
            elif mutation == "unbound_activity":
                # Unregistered jobs are rejected before they can exhaust programme capacity.
                data = {
                    "sealed_input": second["input"],
                    "usage_events": [],
                    "receipts": {},
                    "result": None,
                }
                for index in range(11):
                    job_id = f"synthetic-exhaustion-{index}"
                    conn.execute(
                        "INSERT INTO workspace_generation_jobs VALUES(%s,%s,'synthetic','failed',%s,%s)",
                        (job_id, second["owner"], _digest(data["sealed_input"]), Jsonb(data)),
                    )
                    conn.execute(
                        "INSERT INTO workspace_spend_reservations "
                        "VALUES(%s,%s,0.01,clock_timestamp(),clock_timestamp(),0,0,0,'failed')",
                        (job_id, second["owner"]),
                    )
            else:
                packet["code"] = {"synthetic": "post-approval producer mutation"}

    try:
        report = await d5_campaign.run(
            store,
            packet,
            offline=True,
            transport_factory=_factory(calls, "", ""),
            progress=progress,
        )
        stop = report["stop"]
    except (ExecutorError, AdmissionError) as exc:
        # A later report recomputation can also correctly refuse corrupted inputs.
        assert mutation in {"source_drift", "packet_drift"}, exc
        stop = None
    assert list(calls) in ([DEVELOPMENT], [DEVELOPMENT, next_case])
    if next_case in calls:
        assert not calls[next_case].contacts
    with store.pool.connection() as conn:
        found_state, persisted = conn.execute(
            "SELECT state,data->'campaign_stop' FROM workspace_d5_scopes WHERE scope_id=%s",
            (scope,),
        ).fetchone()
    assert found_state == state
    assert (persisted["case_id"], persisted["stage"], persisted["local_stage"]) == (
        next_case,
        "B",
        local_stage,
    )
    assert persisted["reason_code"] == reason
    assert persisted["automatic_retries"] == 0
    if stop is not None:
        assert stop == persisted


async def test_prior_isolation_accounting_corruption_stops_before_next_case(fixture_campaign):
    store, packet, compiled = fixture_campaign
    calls = {}

    def progress(outcome):
        if outcome["case_id"] == EVALUATION:
            with store.pool.connection() as conn:
                conn.execute(
                    "UPDATE workspace_spend_reservations SET state='running' WHERE job_id=%s",
                    (outcome["job_id"],),
                )

    report = await d5_campaign.run(
        store,
        packet,
        offline=True,
        transport_factory=_factory(calls, EVALUATION, "semantic"),
        progress=progress,
    )
    assert list(calls) == list(compiled)[:3]
    assert report["stop"]["case_id"] == list(compiled)[3]
    assert report["stop"]["local_stage"] == "dispatch_gate"
    assert report["stop"]["classification"] == "accounting_corruption"
    assert report["outcomes"][EVALUATION]["state"] == "failed"


@pytest.mark.timeout(180)
async def test_unresolved_final_checker_stops_scope_even_with_decisive_negative(
    fixture_campaign,
):
    import json

    from jsonschema import Draft202012Validator

    class MixedChecker(FaultTransport):
        async def __call__(self, request):
            response = await super().__call__(request)
            if request.url.path.endswith("/messages") and self.checks == 2:
                body = json.loads(request.content)
                wire = response.json()
                verdict = json.loads(wire["content"][-1]["text"])
                if verdict.get("claim_reviews"):
                    assert any(
                        review["decision"] == "unsupported"
                        for review in verdict["claim_reviews"].values()
                    )
                verdict["priority_review"] = "uncertain"
                Draft202012Validator(body["output_config"]["format"]["schema"]).validate(verdict)
                wire["content"][-1]["text"] = json.dumps(verdict)
                return httpx.Response(200, json=wire)
            return response

    store, packet, compiled = fixture_campaign
    calls = {}
    bad = MixedChecker(CASE_MAP[DEVELOPMENT], repair_all=True)
    bad.scenario = "final_negative"

    def only_development(key):
        assert key == DEVELOPMENT
        calls[key] = bad
        return bad

    report = await d5_campaign.run(store, packet, offline=True, transport_factory=only_development)
    assert list(calls) == [DEVELOPMENT]
    assert len(bad.contacts) == 8
    assert report["stop"]["case_id"] == DEVELOPMENT
    assert report["stop"]["local_stage"] == "recheck"
    assert report["stop"]["reason_code"] == "campaign_v20_checker_judgment_unresolved"
    assert report["outcomes"] == {}
    assert report["denominators"]["unrun_workflows"] == 4
    with store.pool.connection() as conn:
        row = conn.execute(
            "SELECT j.id,j.state FROM workspace_generation_jobs j "
            "JOIN workspace_d5_case_runs r ON j.id=r.job_id "
            "WHERE r.case_id=%s AND r.packet_digest=%s",
            (DEVELOPMENT, packet["packet_digest"]),
        ).fetchone()
    assert row and row[1] == "failed"
    data, reservation = job_ledger(store, row[0])
    assert reservation[-2:] == (0, "failed")
    assert data["adapter"]["steps"][-1]["output"]["priority_review"] == "uncertain"
    assert "classification" not in data["campaign_content_rejection"]
    assert data["sealed_input"] == compiled[DEVELOPMENT]["input"]


@pytest.mark.timeout(180)
async def test_direct_adapter_cannot_record_or_advance_past_preliminary_failure(fixture_campaign):
    from pydantic import ValidationError

    from src.workspace.d5_adapter import D5Adapter
    from src.workspace.d5_campaign_policy import job_binding, record_outcome

    store, packet, compiled = fixture_campaign
    scope = "d5-" + packet["packet_digest"][:24]
    result = await d5_campaign.run(
        store, packet, offline=True, transport_factory=_factory({}), checkpoint_after=2
    )
    assert result["stop"] is None
    assert set(result["outcomes"]) == set(list(compiled)[:2])
    failed = compiled[EVALUATION]
    bad = FaultTransport(CASE_MAP[EVALUATION], fault="semantic")
    adapter = D5Adapter(
        store,
        failed["owner"],
        d5_freeze.restore_input(failed["input"]),
        transport=httpx.MockTransport(bad),
    )
    original = adapter.start(adapter.inputs.settings["d5_request_id"])
    job_id = original["id"]
    with pytest.raises(ValidationError, match=SEMANTIC_FAILURE):
        await adapter.advance(job_id)
    assert len(bad.contacts) == 2
    digest = _digest(failed["input"])
    data, reservation = job_ledger(store, job_id)
    assert reservation[-2:] == (0, "failed")
    assert "classification" not in data["campaign_content_rejection"]

    with pytest.raises(AdmissionError, match="campaign_v20_promoted_failure_required"):
        record_outcome(store, scope, EVALUATION, job_id, digest)

    following_id = list(compiled)[3]
    following = compiled[following_id]
    safe = FaultTransport(CASE_MAP[following_id])
    later = D5Adapter(
        store,
        following["owner"],
        d5_freeze.restore_input(following["input"]),
        transport=httpx.MockTransport(safe),
    )
    with pytest.raises(AdmissionError, match="campaign_previous_case_not_terminal"):
        later.start(later.inputs.settings["d5_request_id"])

    # Simulate an old weak recorder that wrote a fully hashed preliminary record.
    # Real order admission must still recheck its terminal classification.
    record = {
        "job_id": job_id,
        "case_id": EVALUATION,
        "state": "failed",
        "input_digest": digest,
        "content_rejection": data["campaign_content_rejection"],
    }
    with store.pool.connection() as conn:
        _, _, binding = job_binding(conn, job_id)
        conn.execute(
            "INSERT INTO workspace_d5_campaign_outcomes "
            "VALUES(%s,%s,%s,%s,%s,%s,clock_timestamp())",
            (scope, EVALUATION, job_id, binding, Jsonb(record), _digest(record)),
        )
    with pytest.raises(AdmissionError, match="campaign_v20_promoted_failure_required"):
        later.start(later.inputs.settings["d5_request_id"])
    with pytest.raises(AdmissionError):
        await adapter.advance(job_id)
    assert len(bad.contacts) == 2 and safe.contacts == []
