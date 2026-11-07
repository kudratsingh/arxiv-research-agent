"""Production D5 adapter/admission path, synthetic external scope and transport.

Every database is a disposable pytest schema. No provider credential/contact.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import assistance as a
from src.workspace import d5_adapter as d
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_authorization import case_bindings, record_external, revoke
from src.workspace.d5_results import QualificationResults
from src.workspace.d5_scope import guard_scope
from src.workspace.qualification_budget import census
from tests import test_workspace_assistance as support
from tests.test_workspace_evaluation_program import program

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store, operation="workflow", stages=None, *, mode="learn", comparison=False, routes=None):
    program(store)
    service, value = support.setup(store, mode)
    if comparison:
        from tests.test_workspace_store import ingest

        item = ingest(
            store,
            work_id="arxiv:0000.00002",
            version_id="arxiv:0000.00002:v1",
            source_record_id="0000.00002",
            abstract="A second method failed under a different evaluation setting.",
        )
        unit = service.catalog("a", item["work_id"], item["version_id"])["units"][0]
        value = value.model_copy(
            update={
                "material_ids": (*value.material_ids, unit["reference"]["material_id"]),
                "span_ids": (*value.span_ids, unit["reference"]["span_id"]),
                "unit_ids": (*value.unit_ids, unit["id"]),
            }
        )
    preview = service.preview("a", value)
    if mode == "research":
        from src.workspace.context_schemas import ProjectData, ProjectWrite
        from src.workspace.context_store import WorkspaceContext

        project = preview.request["project_context"]
        WorkspaceContext(store).write_project(
            "d5-run",
            ProjectWrite(
                id=project["id"],
                revision=0,
                request_id="synthetic-context",
                data=ProjectData(
                    title="Synthetic research context",
                    question=project["question"],
                    scope=project["scope"],
                    constraints=project["constraints"],
                ),
            ),
        )
    inputs = d.prepare_input(
        preview.request,
        scope_id="d5-test",
        packet_digest="packet",
        case_id="case",
        operation=operation,
        operation_routes=routes,
    )
    compiled = {
        "case": {
            "owner": "d5-run",
            "input": inputs.snapshot(),
            "stage": "A" if operation == "measurement" else "B",
        }
    }
    now = datetime.now(UTC)
    receipt = {
        "approved": True,
        "approved_by": "Synthetic fixture, not owner approval",
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "packet_digest": "packet",
        "scope_id": "d5-test",
        "limits": __import__("src.workspace.d5_scope", fromlist=["limits_for"]).limits_for(
            inputs.settings
        ),
        "members": ["d5-run"],
        "case_bindings_digest": _digest(case_bindings(compiled)),
        "transport_mode": "mock",
        "authorization_kind": "offline_fixture",
        "stages": stages if stages is not None else ["A", "B", "C", "D"],
    }
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
        history = census(conn, "a")
    record_external(
        store,
        packet_digest="packet",
        scope_id="d5-test",
        program_id="evaluation",
        compiled=compiled,
        receipt=receipt,
        expected_history=history,
    )
    return inputs


class Transport:
    def __init__(self, decision="supported"):
        self.calls = []
        self.decision = decision

    async def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        raw = a.LocalAssistanceTransport.fixture(
            httpx.Request("POST", "https://offline.invalid", json=body)
        ).json()
        output = json.loads(raw["content"][0]["text"])
        if "checks" in output:
            for check in output["checks"]:
                check["decision"] = self.decision
            raw["content"][0]["text"] = json.dumps(output)
        raw.update(
            id="synthetic-" + str(len(self.calls)),
            usage={"input_tokens": 100, "output_tokens": 100},
        )
        return httpx.Response(200, json=raw)


async def test_production_d5_pipeline_two_calls_and_real_scoped_journal(store):
    inputs = setup(store)
    transport = Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"], "0.40")
    first = await adapter.advance(job["id"])
    assert first["state"] == "running"
    result = await adapter.advance(job["id"])
    assert result["state"] == "ready", result
    assert (
        len(transport.calls) == 4
        and result["result"]["experiment_only"]
        and not result["result"]["checker_qualified"]
    )
    assert result["workflow_usd"] == result["checker_usd"] == "0"
    assert [s["stage"] for s in result["steps"]] == ["draft", "check"]
    assert adapter.start(inputs.settings["d5_request_id"], "0.40")["state"] == "ready"
    assert len(transport.calls) == 4


async def test_same_adapter_bounded_failed_repair_remains_quarantined(store):
    inputs = setup(store)
    transport = Transport("unsupported")
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"], "0.40")
    for _ in range(4):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and result["result"]["grounding"]["unsupported"] > 0
    assert len(transport.calls) == 8 and [s["stage"] for s in result["steps"]] == [
        "draft",
        "check",
        "repair",
        "check",
    ]
    assert not result["result"]["everyday_generation"]


async def test_measurement_authorization_forbids_messages(store):
    inputs = setup(store, "measurement")
    transport = Transport()
    adapter = d.D5MeasurementAdapter(
        store, "d5-run", inputs, transport=httpx.MockTransport(transport)
    )
    job = adapter.start(inputs.settings["d5_request_id"])
    result = await adapter.advance(job["id"])
    assert result["state"] == "ready"
    assert len(transport.calls) == 1 and transport.calls[0][0].endswith("count_tokens")
    with pytest.raises(AdmissionError):
        await d.D5Adapter.advance(adapter, job["id"])


@pytest.mark.parametrize(
    "mutation", ["quote", "offset", "version", "schema", "settings", "producer", "task", "source"]
)
async def test_pre_dispatch_binding_drift_has_zero_contacts(store, mutation):
    from dataclasses import replace

    inputs = setup(store)
    settings = json.loads(json.dumps(inputs.settings))
    sealed = settings["d5_request"]
    ref = next(iter(sealed["units"].values()))
    if mutation == "quote":
        ref["quote"] += " invented"
    elif mutation == "offset":
        ref["start"] += 1
    elif mutation == "version":
        sealed["version_hashes"] = {inputs.sources[0].version_id: "wrong"}
    elif mutation == "schema":
        sealed["response_schemas_digest"] = "wrong"
    elif mutation == "settings":
        sealed["settings"]["effort"] = "high"
    elif mutation == "producer":
        settings["qualification_producer"] = {}
    elif mutation == "task":
        settings["research_task"] = "unapproved question"
    elif mutation == "source":
        settings["selection"] = {}
    transport = Transport()
    with pytest.raises((AdmissionError, ValueError)):
        d.D5Adapter(
            store,
            "d5-run",
            replace(inputs, settings=settings),
            transport=httpx.MockTransport(transport),
        )
    assert transport.calls == []


async def test_revocation_before_count_and_duplicate_no_replay(store):
    inputs = setup(store)
    transport = Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    revoke(store, "d5-test")
    with pytest.raises(AdmissionError):
        await adapter.advance(job["id"])
    assert transport.calls == []
    with pytest.raises(AdmissionError):
        adapter.start(inputs.settings["d5_request_id"])
    assert QualificationResults(store).snapshot("d5-run", job["id"])["result"] is None


async def test_cancel_before_any_call_is_durable_across_adapter_restart(store):
    inputs = setup(store)
    transport = Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"], cancelled=lambda: True)
    restarted = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    assert restarted.snapshot(job["id"])["state"] == "cancelled"
    with pytest.raises(AdmissionError):
        await restarted.advance(job["id"])
    assert transport.calls == []


@pytest.mark.parametrize(
    "scenario",
    [
        "truncated",
        "schema",
        "duplicate_key",
        "nonfinite",
        "wrong_handle",
        "missing_usage",
        "timeout",
        "invalid_outer",
        "prose",
    ],
)
async def test_completed_bad_content_vs_uncertain_completion_are_separate(store, scenario):
    inputs = setup(store)
    normal = Transport()

    async def handler(request):
        response = await normal(request)
        if request.url.path.endswith("count_tokens"):
            return response
        raw = response.json()
        if scenario == "timeout":
            raise httpx.ReadTimeout("Synthetic lost reply", request=request)
        if scenario == "invalid_outer":
            return httpx.Response(200, content=b'{"broken":')
        if scenario == "missing_usage":
            raw.pop("usage")
        elif scenario == "truncated":
            raw.update(stop_reason="max_tokens")
            raw["content"][0]["text"] = '{"claims":['
        elif scenario == "duplicate_key":
            raw["content"][0]["text"] = '{"claims":[],"claims":[]}'
        elif scenario == "nonfinite":
            raw["content"][0]["text"] = '{"claims":NaN}'
        elif scenario == "schema":
            raw["content"][0]["text"] = "{}"
        elif scenario == "wrong_handle":
            output = json.loads(raw["content"][0]["text"])
            output["claims"][0]["handles"] = ["unselected"]
            raw["content"][0]["text"] = json.dumps(output)
        elif scenario == "prose" and '"checks"' in raw["content"][0]["text"]:
            output = json.loads(raw["content"][0]["text"])
            output["prose_review"] = "unscored_factual_content"
            raw["content"][0]["text"] = json.dumps(output)
        return httpx.Response(200, json=raw)

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    if scenario == "prose":
        await adapter.advance(job["id"])
    with pytest.raises((AdmissionError, ValueError, httpx.ReadTimeout, json.JSONDecodeError)):
        await adapter.advance(job["id"])
    stored = QualificationResults(store).snapshot("d5-run", job["id"])
    assert stored["result"] is None and not stored["factual_acceptance"]
    assert stored["state"] != "ready"
    if scenario in {"timeout", "missing_usage", "invalid_outer"}:
        assert float(stored["unknown_usd"]) > 0
    else:
        assert stored["unknown_usd"] == "0" and stored["accounting_audits"]
    count = len(normal.calls)
    with pytest.raises((AdmissionError, ValueError)):
        await adapter.advance(job["id"])
    assert len(normal.calls) == count


async def test_oversized_measured_input_stops_before_messages_and_releases_only_known_zero(store):
    inputs = setup(store)
    calls = []

    async def oversized(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"input_tokens": 16001})

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(oversized))
    job = adapter.start(inputs.settings["d5_request_id"])
    with pytest.raises(AdmissionError, match="input_measurement"):
        await adapter.advance(job["id"])
    assert len(calls) == 1 and calls[0].endswith("count_tokens")
    result = QualificationResults(store).snapshot("d5-run", job["id"])
    assert result["unknown_usd"] == "0" and result["state"] == "failed" and not result["result"]


async def test_real_result_read_model_reloads_exact_claims_and_hides_source_drift(store):
    inputs = setup(store)
    transport = Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    await adapter.advance(job["id"])
    service = QualificationResults(store)
    result = service.snapshot("d5-run", job["id"])
    assert result["simulated"] and result["resolved_claims"] and result["assistance_output"]
    assert result["source_binding_intact"]
    assert (
        service.jobs("d5-run", inputs.sources[0].work_id, inputs.sources[0].version_id)[0]["id"]
        == job["id"]
    )
    with pytest.raises(AdmissionError):
        service.snapshot("other", job["id"])
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_versions SET data=jsonb_set(data,'{content_hash}',%s) WHERE version_id=%s",
            (Jsonb("changed"), inputs.sources[0].version_id),
        )
    result = service.snapshot("d5-run", job["id"])
    assert (
        result["state"] == "stale"
        and result["assistance_output"] is None
        and result["resolved_claims"] == []
    )


@pytest.mark.parametrize("amount", ["0.1", "0.41"])
async def test_four_stage_money_envelope_cannot_be_underreserved_or_overfunded(store, amount):
    inputs = setup(store)
    transport = Transport()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    with pytest.raises(AdmissionError):
        adapter.start(inputs.settings["d5_request_id"], amount)
    assert transport.calls == []


@pytest.mark.parametrize(
    "guard",
    [
        "scope",
        "receipt",
        "fixture",
        "case",
        "stage",
        "cap_messages",
        "cap_counts",
        "capacity",
        "headroom",
        "amount",
    ],
)
async def test_scoped_financial_and_external_authorization_guards(store, guard):
    from datetime import UTC, datetime

    inputs = setup(store)
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(Transport()))
    job = adapter.start(inputs.settings["d5_request_id"])
    with store.pool.connection() as conn:
        _, policy = adapter.control._policy(conn, "d5-run", inputs.snapshot(), datetime.now(UTC))
        if guard == "scope":
            policy["d5_scope_id"] = "different"
        elif guard == "receipt":
            conn.execute(
                "UPDATE workspace_d5_scopes SET data=jsonb_set(data,'{authorization_record,approved}', 'false')"
            )
        elif guard == "fixture":
            policy["transport_mode"] = "provider"
        elif guard in {"case", "stage"}:
            # Exact external receipt binding is checked before case lookup.
            settings = dict(inputs.settings)
            settings["d5_case_id"] = "unapproved" if guard == "case" else "case"
            if guard == "case":
                from src.workspace.d5_scope import scope

                with pytest.raises(AdmissionError):
                    scope(
                        conn,
                        "d5-run",
                        {**inputs.snapshot(), "settings": settings},
                        policy,
                        datetime.now(UTC),
                    )
                return
            conn.execute(
                "UPDATE workspace_d5_scopes SET data=jsonb_set(data,'{stages}', '[\"A\"]')"
            )
        elif guard in {"cap_messages", "cap_counts", "capacity"}:
            data = conn.execute(
                "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
            ).fetchone()[0]
            endpoint = "messages/count_tokens" if guard == "cap_counts" else "messages"
            number = 41 if guard == "capacity" else 48 if guard == "cap_counts" else 44
            data["adapter"]["contacts"] = [
                {"endpoint": endpoint, "state": "completed", "ordinal": i} for i in range(number)
            ]
            conn.execute(
                "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
            )
        elif guard == "headroom":
            conn.execute(
                "UPDATE workspace_spend_reservations SET workflow=8.8,state='failed' WHERE job_id=%s",
                (job["id"],),
            )
            conn.execute(
                "UPDATE workspace_generation_jobs SET state='failed' WHERE id=%s", (job["id"],)
            )
        from decimal import Decimal

        kwargs = {"job_id": job["id"]}
        if guard in {"capacity", "headroom", "amount"}:
            kwargs["amount"] = Decimal("0.41" if guard == "amount" else "0.40")
        elif guard in {"cap_messages", "cap_counts"}:
            kwargs["endpoint"] = "messages/count_tokens" if guard == "cap_counts" else "messages"
        with pytest.raises(AdmissionError):
            guard_scope(conn, "d5-run", inputs.snapshot(), policy, **kwargs)


@pytest.mark.parametrize(
    "field,value",
    [
        ("approved", False),
        ("approved_by", ""),
        ("packet_digest", "wrong"),
        ("members", []),
        ("stages", ["unknown"]),
        ("expires_at", "bad"),
        ("authorization_kind", "owner"),
        ("transport_mode", "provider"),
    ],
)
async def test_operator_refuses_invalid_or_self_approved_scope_receipts(store, field, value):
    inputs = setup(store)
    with store.pool.connection() as conn:
        receipt = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes"
        ).fetchone()[0]
        history = census(conn, "a")
    receipt[field] = value
    compiled = {"case": {"owner": "d5-run", "input": inputs.snapshot(), "stage": "B"}}
    with pytest.raises(AdmissionError):
        record_external(
            store,
            packet_digest="packet",
            scope_id="d5-test",
            program_id="evaluation",
            compiled=compiled,
            receipt=receipt,
            expected_history=history,
        )


async def test_read_only_api_never_offers_approval_dispatch_or_foreign_results(client, store):
    inputs = setup(store)
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(Transport()))
    job = adapter.start(inputs.settings["d5_request_id"])
    # API fixture is principal a, not the isolated d5-run owner.
    response = await client.get(
        "/workspace/qualification/results",
        params={"work_id": inputs.sources[0].work_id, "version_id": inputs.sources[0].version_id},
    )
    assert response.status_code == 200 and response.json() == []
    assert (await client.get("/workspace/qualification/results/" + job["id"])).status_code == 422
    assert (
        await client.post("/workspace/qualification/results/" + job["id"] + "/advance", json={})
    ).status_code == 404


client = support.client


async def test_dynamic_response_journal_and_capacity_tampering_refuse_before_next_count(store):
    from dataclasses import replace

    inputs = setup(store)
    transport = Transport()
    changed = json.loads(json.dumps(inputs.settings))
    changed["d5_request"]["capacity"]["stage_input_bytes_max"]["draft"] = 1
    preview = d.D5Adapter(
        store, "d5-run", replace(inputs, settings=changed), transport=httpx.MockTransport(transport)
    )
    with pytest.raises(AdmissionError, match="capacity"):
        preview.request()
    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with store.pool.connection() as conn:
        data = conn.execute(
            "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job["id"],)
        ).fetchone()[0]
        data["adapter"]["steps"][0]["output"]["claims"][0]["text"] = "Tampered preceding output"
        conn.execute(
            "UPDATE workspace_generation_jobs SET data=%s WHERE id=%s", (Jsonb(data), job["id"])
        )
    with pytest.raises(AdmissionError, match="preceding_output"):
        await adapter.advance(job["id"])
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "reply", ["http_error", "outer_invalid", "oversized_usage", "duplicate_response_id"]
)
async def test_completed_receipts_and_stage_limits_cannot_be_confused_with_accepted_content(
    store, reply
):
    inputs = setup(store)
    normal = Transport()

    async def handler(request):
        response = await normal(request)
        if request.url.path.endswith("count_tokens"):
            return response
        if reply == "http_error":
            return httpx.Response(
                400, json={"error": "Synthetic schema rejection local-preview-disabled"}
            )
        if reply == "outer_invalid":
            return httpx.Response(200, content=b"{")
        value = response.json()
        if reply == "oversized_usage":
            value["usage"]["output_tokens"] = 4001
        if reply == "duplicate_response_id":
            value["id"] = "same-synthetic-response"
        return httpx.Response(200, json=value)

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    if reply == "duplicate_response_id":
        await adapter.advance(job["id"])
    with pytest.raises((AdmissionError, ValueError, httpx.HTTPStatusError)):
        await adapter.advance(job["id"])
    result = QualificationResults(store).snapshot("d5-run", job["id"])
    assert result["state"] != "ready" and result["result"] is None
    if reply == "http_error":
        raw = result["contacts"][-1]["response"]["raw_body"]
        assert "[credential redacted]" in raw and "local-preview-disabled" not in raw


async def test_every_successful_stage_obeys_exact_local_and_transformed_wire_schemas(store):
    import jsonschema

    inputs = setup(store)
    normal = Transport("unsupported")
    phases = []

    async def validate(request):
        response = await normal(request)
        if not request.url.path.endswith("count_tokens"):
            wire = json.loads(request.content)
            output = json.loads(response.json()["content"][0]["text"])
            jsonschema.Draft202012Validator(wire["output_config"]["format"]["schema"]).validate(
                output
            )
            phase = json.loads(wire["messages"][0]["content"])["phase"]
            phases.append(phase)
            if phase == "check":
                a.Checks.model_validate(output)
        return response

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(validate))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        await adapter.advance(job["id"])
    assert phases == ["draft", "check", "repair", "check"]


async def test_explicit_abstention_still_requires_mandatory_check_and_stays_unscored(store):
    from src.workspace.d5_scoring import score_case

    inputs = setup(store)
    normal = Transport()

    async def abstain(request):
        response = await normal(request)
        if request.url.path.endswith("count_tokens"):
            return response
        raw = response.json()
        out = json.loads(raw["content"][0]["text"])
        if "claims" in out:
            out.update(
                claims=[],
                abstention="The retained abstract does not establish the requested deployment conditions.",
            )
        else:
            out["checks"] = []
        raw["content"][0]["text"] = json.dumps(out)
        return httpx.Response(200, json=raw)

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(abstain))
    job = adapter.start(inputs.settings["d5_request_id"])
    first = await adapter.advance(job["id"])
    assert first["state"] == "running"
    final = await adapter.advance(job["id"])
    assert final["state"] == "ready" and final["result"]["content_status"] == "abstained"
    assert len(normal.calls) == 4
    materials = adapter._context()[1]
    case = {
        "id": "fixture",
        "cohort": "development",
        "pipeline": "fixed_evidence_diagnostic",
        "ranking": [],
        "edition": [],
        "sealed": inputs.settings["d5_request"],
    }
    score = score_case(case, QualificationResults(store).snapshot("d5-run", job["id"]), materials)
    assert (
        score["provenance"] is None
        and score["factual_gate"] == "UNSCORED"
        and not score["accepted_result"]
    )


@pytest.mark.parametrize(
    "mode,comparison", [("learn", False), ("research", False), ("research", True)]
)
async def test_purpose_specific_four_stage_contract_and_exact_wire(store, mode, comparison):
    """All outputs are synthetic; the real stopped Stage B identity is never run."""
    import jsonschema

    from src.workspace.assistance_contract import response_model

    inputs = setup(store, mode=mode, comparison=comparison)
    normal = Transport("unsupported")
    stages = []

    async def handler(request):
        response = await normal(request)
        if request.url.path.endswith("count_tokens"):
            return response
        wire = json.loads(request.content)
        context = json.loads(wire["messages"][0]["content"])
        output = json.loads(response.json()["content"][0]["text"])
        jsonschema.Draft202012Validator(wire["output_config"]["format"]["schema"]).validate(output)
        if context["phase"] == "check":
            a.Checks.model_validate(output)
        else:
            purpose = "research_comparison" if comparison else "single_paper"
            response_model(
                list(inputs.settings["d5_request"]["units"]), purpose=purpose
            ).model_validate(output)
            assert ("comparison_basis" in output) is comparison
        stages.append(context["phase"])
        return response

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        result = await adapter.advance(job["id"])
    assert stages == ["draft", "check", "repair", "check"]
    assert result["state"] == "ready" and not result["result"]["everyday_generation"]
    assert result["result"]["grounding"]["unsupported"] > 0  # Not factual acceptance.


@pytest.mark.parametrize(
    "field",
    ["background", "assumptions", "gaps", "questions", "proposal", "abstention", "comparison"],
)
async def test_unverified_factual_prose_is_sent_to_checker_and_cannot_bypass_it(store, field):
    inputs = setup(
        store,
        mode="research" if field == "comparison" else "learn",
        comparison=field == "comparison",
    )
    normal = Transport()
    factual = "Unverified: every agent is safe on all hardware without validation."
    seen = []

    async def handler(request):
        response = await normal(request)
        if request.url.path.endswith("count_tokens"):
            return response
        raw = response.json()
        context = json.loads(json.loads(request.content)["messages"][0]["content"])
        output = json.loads(raw["content"][0]["text"])
        if "claims" in output:
            output[field] = [factual] if field in {"assumptions", "gaps", "questions"} else factual
        else:
            seen.append(context["unscored_prose"][field])
            output["prose_review"] = "unscored_factual_content"
        raw["content"][0]["text"] = json.dumps(output)
        return httpx.Response(200, json=raw)

    adapter = d.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(AdmissionError, match="unscored_factual_prose"):
        await adapter.advance(job["id"])
    result = QualificationResults(store).snapshot("d5-run", job["id"])
    assert (
        result["state"] == "failed" and result["result"] is None and result["human_review"] is None
    )
    assert seen == [[factual] if field in {"assumptions", "gaps", "questions"} else factual]
    assert len(normal.calls) == 4  # No repair or extra provider work.
