"""v20 progression over real adapter journals in disposable fixture storage."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import psycopg
import pytest
from jsonschema import Draft202012Validator
from psycopg import sql
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from src.workspace import (
    d5_campaign,
    d5_campaign_operator,
    d5_campaign_packet,
    d5_campaign_policy,
    d5_freeze,
)
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_v19_policy import REVISION as HISTORICAL_REVISION
from src.workspace.d5_case_isolation import (
    REVISION,
    _contact_accounting,
    _semantic_code,
    eligible_error,
    preserve_failed_case,
    stop_details,
)
from src.workspace.d5_comparison_transport import (
    ComparisonCampaignTransport,
    assert_paired_contacts,
)
from src.workspace.store import WorkspaceStore
from tests.d5_comparison_gate import SNAPSHOT, setup

EVALUATION = "campaign-eval-learn-mechanism"
DEVELOPMENT = "campaign-dev-learn"
SEMANTIC_FAILURE = "answered_requires_complete_answer_without_gaps"
HISTORICAL = Path.home() / (
    "Machine-Learning-Projects/arxiv-evidence/campaign-live-v19-20261117T003409Z/"
    "cases/campaign-eval-learn-measurement"
)


@pytest.mark.integration
def test_exact_preserved_measurement_response_replays_without_mutation():
    from src.workspace.assistance_comparison_contract import response_model

    if not HISTORICAL.is_dir():
        pytest.skip("read-only preserved owner-local historical response unavailable")
    expected = {
        "01-draft-message.response.raw": "3be962576f005b6479c87d0b6bfd9f5e48ba9346983f43f4618ffe0b62bffd92",
        "SEALED-REQUEST.json": "7fa9d725e02b5fb476c386b731cfe8e264a46a9a030c4cf6b3cfee9b347f22b4",
        "CONTACT-JOURNAL.json": "19b32a2da0c4bb2b69656a23e25c6317919250e3a0a0db48347664d50161d0cd",
    }
    evidence = {}
    for name, digest in expected.items():
        raw = (HISTORICAL / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == digest
        evidence[name] = json.loads(raw)
    response = evidence["01-draft-message.response.raw"]
    sealed = evidence["SEALED-REQUEST.json"]
    binding = evidence["CONTACT-JOURNAL.json"]
    draft = json.loads(response["content"][0]["text"])
    context = sealed["original_selected_context"]
    body = sealed["initial_generation_request"]
    Draft202012Validator(body["output_config"]["format"]["schema"]).validate(draft)
    assert binding["state"] == "failed" and len(binding["contacts"]) == 2
    assert binding["contacts"][1]["response"] == response
    assert response["stop_reason"] == "end_turn"
    assert draft["response"]["coverage"]["p2"]["status"] == "answered"
    assert not draft["response"]["coverage"]["p2"]["answer_claim_ids"]
    assert draft["response"]["coverage"]["p2"]["context_claim_ids"]
    model = response_model(
        list(context["units"]), context["response_purpose"], context["task_policy"]
    )
    with pytest.raises(ValidationError) as captured:
        model.model_validate(draft)
    assert _semantic_code(captured.value) == SEMANTIC_FAILURE


class FaultTransport(ComparisonCampaignTransport):
    def __init__(self, key, *, fault):
        super().__init__(key, repair_all=fault == "negative_quality")
        self.fault = fault

    async def __call__(self, request):
        response = await super().__call__(request)
        if request.url.path.endswith("count_tokens"):
            if self.fault == "count_fit":
                return httpx.Response(200, json={"input_tokens": 32001})
            return response
        body = json.loads(request.content)
        phase = json.loads(body["messages"][0]["content"])["phase"]
        if self.fault == "missing_checker" and phase == "check":
            malformed = response.json()
            malformed["content"][-1]["text"] = "{}"
            return httpx.Response(200, json=malformed)
        if phase != "draft":
            return response
        wire = response.json()
        if self.fault in {"semantic", "wire_invalid"}:
            draft = json.loads(wire["content"][0]["text"])
            coverage = draft["response"]["coverage"]["p2"]
            coverage.update(
                status="answered",
                gap_reasons=["none"],
                context_claim_ids=coverage["answer_claim_ids"],
                answer_claim_ids=[],
            )
            validator = Draft202012Validator(body["output_config"]["format"]["schema"])
            validator.validate(draft)
            if self.fault == "wire_invalid":
                draft["response"].pop("questions")
                assert not validator.is_valid(draft)
            wire["content"][0]["text"] = json.dumps(draft)
        if self.fault == "max_tokens":
            wire["stop_reason"] = "max_tokens"
        if self.fault == "usage":
            wire["usage"]["cache_read_input_tokens"] = 10
        if self.fault == "model":
            wire["model"] = "synthetic-substituted-model"
        if self.fault == "transport":
            raise httpx.ReadTimeout("synthetic interruption", request=request)
        if self.fault == "http_400":
            return httpx.Response(400, json={"error": {"message": "synthetic grammar rejection"}})
        if self.fault == "cancel":
            raise asyncio.CancelledError
        return httpx.Response(200, json=wire)


@contextmanager
def _storage():
    url = os.environ["WORKSPACE_TEST_POSTGRES_URL"]
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/workspace_d5_tests":
        raise AdmissionError("case_isolation_disposable_test_database_required")
    schema = "ws_test_v20_isolation_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        with ConnectionPool(
            url, min_size=1, max_size=4, kwargs={"options": f"-c search_path={schema},public"}
        ) as pool:
            store = WorkspaceStore(pool)
            store.migrate()
            yield store
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def fixture_campaign(monkeypatch):
    if not SNAPSHOT.exists() or not os.environ.get("WORKSPACE_TEST_POSTGRES_URL"):
        pytest.skip("preserved owner-local input snapshot and disposable test Postgres required")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    with _storage() as store:
        historical = setup(store, authorize=False)
        packet = {**historical, "revision": REVISION}
        verify = d5_freeze.verify
        compile_campaign = d5_campaign_packet.compile_campaign
        compile_inputs = d5_freeze.compile_inputs
        verify_dispatch = d5_campaign_packet.verify_dispatch_identity
        template = d5_campaign_operator.template
        limits_for = d5_campaign_policy.limits_for

        def local_view(value):
            # Exercise v20 execution with an explicitly marked disposable fixture
            # over the prior public corpus. The exact v20 freeze/approval is separate.
            if value is packet:
                if {**value, "revision": HISTORICAL_REVISION} != historical:
                    raise AdmissionError("campaign_frozen_packet_or_producer_drift")
                return historical
            return value

        def fixture_compile(value):
            result = compile_campaign(local_view(value))
            for entry in result.values():
                entry["input"]["settings"]["d5_campaign_revision"] = REVISION
            return result

        def fixture_limits(settings):
            # The legacy fixture still carries its authentic 14-case budget;
            # translate only the runner's prospective opt-in for limit selection.
            if settings.get("d5_campaign_revision") == REVISION:
                return limits_for({**settings, "d5_campaign_revision": HISTORICAL_REVISION})
            return limits_for(settings)

        monkeypatch.setattr(d5_campaign_policy, "limits_for", fixture_limits)
        monkeypatch.setattr(d5_freeze, "verify", lambda value: verify(local_view(value)))
        monkeypatch.setattr(
            d5_freeze, "compile_inputs", lambda value: compile_inputs(local_view(value))
        )
        monkeypatch.setattr(d5_campaign_packet, "compile_campaign", fixture_compile)
        monkeypatch.setattr(
            d5_campaign_packet,
            "verify_dispatch_identity",
            lambda value: verify_dispatch(local_view(value)),
        )
        monkeypatch.setattr(
            d5_campaign_operator,
            "template",
            lambda value: {**template(value), "campaign_revision": REVISION},
        )
        d5_campaign_operator.authorize_fixture(store, historical)
        yield store, packet, historical, fixture_compile(packet)


def _factory(calls, bad_case, fault):
    def factory(key):
        assert key not in calls
        calls[key] = FaultTransport(key, fault=fault if key == bad_case else "")
        return calls[key]

    return factory


def _job(store, job_id):
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s",
            (job_id,),
        ).fetchone()[0]
        reservation = conn.execute(
            "SELECT amount,workflow,judge,unknown,state FROM workspace_spend_reservations "
            "WHERE job_id=%s",
            (job_id,),
        ).fetchone()
    return data, reservation


@pytest.mark.integration
@pytest.mark.timeout(180)
async def test_wire_valid_early_evaluation_failure_preserves_and_continues_once(fixture_campaign):
    from src.workspace.d5_adapter import D5Adapter

    store, packet, _, compiled = fixture_campaign
    calls = {}
    factory = _factory(calls, EVALUATION, "semantic")
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
    assert any(key.startswith("campaign-probe-") for key in calls)
    assert report["denominators"]["completed_evaluation"] == 7
    data, reservation = _job(store, outcome["job_id"])
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


@pytest.mark.integration
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
    store, packet, _, compiled = fixture_campaign
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


@pytest.mark.integration
async def test_v19_still_stops_on_same_evaluation_failure(fixture_campaign):
    store, _, historical, compiled = fixture_campaign
    calls = {}
    report = await d5_campaign.run(
        store, historical, offline=True, transport_factory=_factory(calls, EVALUATION, "semantic")
    )
    assert report["stop"]["case_id"] == EVALUATION
    assert report["stop"]["reason"] == "campaign_development_contract_incomplete"
    assert "classification" not in report["stop"]
    assert list(calls) == list(compiled)[:3]


@pytest.mark.integration
async def test_missing_revision_in_durable_authority_stops_before_factory(fixture_campaign):
    store, packet, _, _ = fixture_campaign
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_d5_scopes SET data=data #- '{authorization_record,campaign_revision}' "
            "WHERE scope_id=%s",
            ("d5-" + packet["packet_digest"][:24],),
        )
    calls = {}
    report = await d5_campaign.run(
        store, packet, offline=True, transport_factory=_factory(calls, EVALUATION, "semantic")
    )
    assert calls == {}
    assert report["stop"]["reason_code"] == "campaign_v20_progression_authorization_binding_drift"


@pytest.mark.integration
async def test_complete_negative_quality_development_keeps_its_bound_verdict(fixture_campaign):
    store, packet, _, _ = fixture_campaign
    calls = {}
    bad = FaultTransport(DEVELOPMENT, fault="negative_quality")
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


@pytest.mark.integration
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
        ("exhaustion", "program_job_cap_exceeded", "case_start", "stopped"),
        ("source_drift", "source_material_changed_or_inaccessible", "case_start", "stopped"),
        ("packet_drift", "campaign_frozen_packet_or_producer_drift", "dispatch_gate", "stopped"),
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

    store, packet, _, compiled = fixture_campaign
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
            elif mutation == "exhaustion":
                data = {
                    "sealed_input": second["input"],
                    "usage_events": [],
                    "receipts": {},
                    "result": None,
                }
                for index in range(18):
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


@pytest.mark.integration
async def test_prior_isolation_accounting_corruption_stops_before_next_case(fixture_campaign):
    store, packet, _, compiled = fixture_campaign
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


@pytest.mark.unit
def test_arbitrary_exception_never_classifies_by_copied_error_text():
    for error in (
        RuntimeError(SEMANTIC_FAILURE),
        ValueError(SEMANTIC_FAILURE),
        RuntimeError("d5_whole_claim_support_unresolved"),
        AdmissionError(SEMANTIC_FAILURE),
    ):
        assert _semantic_code(error) is None
        assert not eligible_error(error)
        assert not preserve_failed_case(None, "unused", {"stage": "C"}, error)
    stop = stop_details(RuntimeError(SEMANTIC_FAILURE), "C", "draft", {})
    assert stop["classification"] == "unexpected_exception"
