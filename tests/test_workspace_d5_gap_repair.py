"""Actual failed196-character v6 gap, offline synthetic corrections only."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from anthropic import transform_schema
from jsonschema import ValidationError as WireError
from jsonschema import validate
from psycopg.types.json import Jsonb

from src.workspace import assistance as a
from src.workspace import assistance_contract as c
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_operations import ROUTES
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_store import ingest

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
FIX = Path(__file__).parent / "fixtures/d5/stage-b-v6"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def original():
    return json.loads((FIX / "dev-compare.draft.provider-text.json").read_text())


def source(store):
    service, selection = support.support.setup(store, "research")
    materials = json.loads((FIX / "selected-materials.json").read_text())
    for m in materials:
        ingest(
            store,
            work_id=m["work_id"],
            version_id=m["version_id"],
            source_record_id=m["work_id"],
            abstract="Retained public evidence has separately pinned provenance.",
        )
        with store.pool.connection() as conn:
            conn.execute(
                "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s)",
                (m["material_id"], m["version_id"], m["content_hash"], m["scope"], Jsonb(m)),
            )
    wanted = {h for claim in original()["claims"] for h in claim["handles"]}
    units = [
        u
        for m in materials
        for u in service.catalog("a", m["work_id"], m["version_id"])["units"]
        if u["id"] in wanted
    ]
    first = units[0]["reference"]
    return service, selection.model_copy(
        update={
            "work_id": first["work_id"],
            "version_id": first["version_id"],
            "material_ids": tuple(dict.fromkeys(u["reference"]["material_id"] for u in units)),
            "span_ids": tuple(dict.fromkeys(u["reference"]["span_id"] for u in units)),
            "unit_ids": tuple(u["id"] for u in units),
        }
    )


class Responses:
    def __init__(self, scenario):
        self.scenario = scenario
        self.calls = []
        self.checks = 0

    async def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        ctx = json.loads(body["messages"][0]["content"])
        if ctx["phase"] == "check":
            self.checks += 1
            assert all(
                value in c.EVIDENCE_REQUESTS.values() for value in ctx["unscored_prose"]["gaps"]
            )
            output = {
                "checks": [
                    {
                        "claim_id": x["claim_id"],
                        "input_digest": x["input_digest"],
                        "decision": "unsupported"
                        if self.scenario in {"repair", "bad_repair"} and self.checks == 1
                        else "supported",
                        "reason": "Synthetic decision, not independent quality evidence",
                    }
                    for x in ctx["claim_inputs"]
                ],
                "prose_review": "procedural_only",
                "prose_findings": [],
            }
            if self.scenario == "hidden_prose":
                output.update(
                    prose_review="unscored_factual_content",
                    prose_findings=[
                        {
                            "field": "proposal",
                            "index": None,
                            "reason": "Unscored scientific assertion",
                        }
                    ],
                )
        else:
            output = original()
            if self.scenario != "original":
                output["gaps"] = ["evaluation", "ablations"]
            if self.scenario == "bad_repair" and ctx["phase"] == "repair":
                output["gaps"] = original()["gaps"]
            if self.scenario == "hidden_prose":
                output["proposal"] = "Method A improves accuracy over method B."
            if self.scenario == "comparison":
                output["comparison_claims"] = ["c1", "c3"]
                output["comparison_basis"] = ["c1", "c3"]
                output["abstention"] = None
        if self.scenario not in {"original", "bad_repair"}:
            validate(output, body["output_config"]["format"]["schema"])
        return httpx.Response(
            200,
            json={
                "id": f"synthetic-{len(self.calls)}",
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(output)}],
            },
        )


async def test_original196_gap_remains_failed_through_production_adapter(store):
    payload = original()
    assert len(payload["gaps"][0]) == 196
    old = json.loads((FIX / "original-compare-wire.json").read_text())["output_config"]["format"][
        "schema"
    ]
    validate(payload, old)
    with pytest.raises(ValueError, match="invalid_bounded_explanation"):
        c.response_model(
            [h for x in payload["claims"] for h in x["handles"]], revision=c.CITED_REVISION
        ).model_validate(payload)
    inputs = support.setup(store, mode="research", routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses("original")
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    with pytest.raises(ValueError):
        await adapter.advance(job["id"])
    assert adapter.snapshot(job["id"])["state"] == "failed" and len(transport.calls) == 2
    assert (
        json.loads(adapter.snapshot(job["id"])["contacts"][-1]["response"]["content"][0]["text"])[
            "gaps"
        ][0]
        == payload["gaps"][0]
    )


@pytest.mark.parametrize("scenario", ["corrected", "comparison", "repair"])
async def test_synthetic_corrected_compare_and_four_stage_repair_use_real_controls(store, scenario):
    inputs = support.setup(store, mode="research", routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses(scenario)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4 if scenario == "repair" else 2):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and not result["result"]["everyday_generation"]
    assert len(transport.calls) == (8 if scenario == "repair" else 4)
    assert result["result"]["draft"]["limitations"] == c.render_gaps(["evaluation", "ablations"])


async def test_codes_do_not_exempt_remaining_factual_prose(store):
    inputs = support.setup(store, mode="research", routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses("hidden_prose")
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(ValueError, match="d5_unscored_factual_prose"):
        await adapter.advance(job["id"])
    assert adapter.snapshot(job["id"])["result"] is None and len(transport.calls) == 4


@pytest.mark.parametrize("value", ["", "evaluation!", "x" * 196, "評価", "EVALUATION"])
async def test_wire_and_local_both_refuse_invalid_gap_code(value):
    payload = original()
    payload["gaps"] = [value]
    handles = [h for x in payload["claims"] for h in x["handles"]]
    schema = c.schemas(handles)
    with pytest.raises(WireError):
        validate(payload, schema["wire"])
    with pytest.raises(ValueError):
        c.response_model(handles).model_validate(payload)


@pytest.mark.parametrize("size,valid", [(1, True), (180, True), (181, False), (0, False)])
async def test_unicode_question_boundary_remains_explicit_and_local(size, valid):
    payload = original()
    payload["gaps"] = ["evaluation"]
    payload["questions"] = ["é" * size]
    handles = [h for x in payload["claims"] for h in x["handles"]]
    schema = c.schemas(handles)
    assert "180 Unicode characters" in schema["wire"]["properties"]["questions"]["description"]
    validate(payload, schema["wire"])
    if valid:
        c.response_model(handles).model_validate(payload)
    else:
        with pytest.raises(ValueError):
            c.response_model(handles).model_validate(payload)


async def test_all_stage_schemas_disclose_sdk_local_bounds_and_semantic_rules():
    handles = [h for x in original()["claims"] for h in x["handles"]]
    for purpose in ["single_paper", "research_comparison"]:
        schema = c.schemas(handles, purpose=purpose)
        assert "8000" in schema["wire"]["description"]
        assert "180 Unicode characters" in schema["wire"]["properties"]["questions"]["description"]
    checker = transform_schema(a.Checks)
    assert "8000" in checker["description"] and "duplicate" in checker["description"]
    assert "240" in checker["$defs"]["Verdict"]["properties"]["reason"]["description"]


@pytest.mark.parametrize(
    "state,decision,identity,matching,allowed",
    [
        ("ready", "supported", True, True, True),
        ("ready", "unsupported", True, True, False),
        ("ready", "abstain", True, True, False),
        ("failed", "supported", True, True, False),
        ("ready", "supported", False, True, False),
        ("ready", "supported", True, False, False),
    ],
)
async def test_C_requires_successful_bound_development_not_a_ready_label(
    state, decision, identity, matching, allowed
):
    from src.workspace.admission import AdmissionError
    from src.workspace.d5_scope import require_development

    class Cursor:
        def fetchone(self):
            return (
                state,
                {
                    "grounding": {
                        "assessments": [
                            {
                                "decision": decision,
                                "identity_resolved": identity,
                                "scope_compatible": True,
                            }
                        ]
                    }
                },
                "bound" if matching else "different",
            )

    class Conn:
        def execute(self, *args):
            return Cursor()

    if allowed:
        require_development(Conn(), "d5-test", {"dev": {"stage": "B", "input_digest": "bound"}})
    else:
        with pytest.raises(AdmissionError, match="successful_development"):
            require_development(Conn(), "d5-test", {"dev": {"stage": "B", "input_digest": "bound"}})
    with pytest.raises(AdmissionError):
        require_development(Conn(), "d5-test", {})


async def test_a_stopped_scope_cannot_be_reopened_by_a_new_packet_or_grant(store):
    from src.workspace.admission import AdmissionError
    from src.workspace.d5_authorization import grant_external, stage_template

    inputs = support.setup(store, routes=deepcopy(ROUTES), stages=["A"])
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_d5_scopes SET state='stopped' WHERE scope_id='d5-test'")
        before = conn.execute("SELECT to_jsonb(t) FROM workspace_d5_scopes t").fetchone()[0]
    template = stage_template(store, "d5-test", ["B"])
    assert template["approved"] is False  # A read-only template grants nothing.
    from datetime import UTC, datetime

    template.update(
        approved=True, approved_by="Synthetic fixture", approved_at=datetime.now(UTC).isoformat()
    )
    with pytest.raises(AdmissionError):
        grant_external(store, "d5-test", template)
    adapter = D5Adapter(
        store,
        "d5-run",
        inputs,
        transport=httpx.MockTransport(
            lambda _: (_ for _ in ()).throw(AssertionError("no contact"))
        ),
    )
    with pytest.raises(AdmissionError):
        adapter.start(inputs.settings["d5_request_id"])
    with store.pool.connection() as conn:
        assert conn.execute("SELECT to_jsonb(t) FROM workspace_d5_scopes t").fetchone()[0] == before


async def test_invalid_repair_gap_stops_before_recheck(store):
    inputs = support.setup(store, mode="research", routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses("bad_repair")
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    await adapter.advance(job["id"])
    with pytest.raises(ValueError):
        await adapter.advance(job["id"])
    assert adapter.snapshot(job["id"])["state"] == "failed"
    assert len(transport.calls) == 6 and transport.checks == 1


@pytest.mark.parametrize(
    "gaps,valid",
    [
        ([], False),
        (["methods"], True),
        (["evaluation", "ablations", "counterevidence"], True),
        (["methods"] * 4, False),
    ],
)
async def test_gap_cardinality_bounds_visible_and_locally_enforced(gaps, valid):
    payload = original()
    payload["gaps"] = gaps
    handles = [h for claim in payload["claims"] for h in claim["handles"]]
    model = c.response_model(handles)
    if valid:
        value = model.model_validate(payload)
        validate(value.model_dump(mode="json"), c.schemas(handles)["wire"])
    else:
        with pytest.raises(ValueError):
            model.model_validate(payload)
    assert "maxItems: 3" in c.schemas(handles)["wire"]["properties"]["gaps"]["description"]
