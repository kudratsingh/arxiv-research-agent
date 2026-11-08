"""Captured v7r2 question/verdict, production controls, synthetic offline transport.

Original provider outputs stay failed. Corrected responses and every following
verdict/count are synthetic software evidence, never provider or human quality.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from jsonschema import ValidationError, validate
from psycopg.types.json import Jsonb

from src.workspace import assistance_contract as c
from src.workspace.admission import AdmissionError
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_operations import ROUTES
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_store import ingest

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]
FIX = Path(__file__).parent / "fixtures/d5/stage-c-v7r2"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def original():
    return json.loads((FIX / "learn-results.draft.provider-text.json").read_text())


def finding():
    return json.loads((FIX / "learn-results.check.provider-text.json").read_text())


def source(store):
    service, selection = support.support.setup(store)
    material = json.loads((FIX / "selected-materials.json").read_text())[0]
    ingest(
        store,
        work_id=material["work_id"],
        version_id=material["version_id"],
        source_record_id=material["work_id"],
        abstract="Selected retained abstract is separately pinned.",
    )
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s)",
            (
                material["material_id"],
                material["version_id"],
                material["content_hash"],
                material["scope"],
                Jsonb(material),
            ),
        )
    units = service.catalog("a", material["work_id"], material["version_id"])["units"]
    wanted = {h for claim in original()["claims"] for h in claim["handles"]}
    units = [u for u in units if u["id"] in wanted]
    assert len(units) == 1
    return service, selection.model_copy(
        update={
            "work_id": material["work_id"],
            "version_id": material["version_id"],
            "material_ids": (material["material_id"],),
            "span_ids": tuple(u["reference"]["span_id"] for u in units),
            "unit_ids": tuple(u["id"] for u in units),
        }
    )


class Responses:
    def __init__(
        self, *, legacy=False, residual=False, malformed=False, uncertain=False, scenario="learn"
    ):
        self.legacy, self.residual, self.malformed, self.uncertain, self.scenario = (
            legacy,
            residual,
            malformed,
            uncertain,
            scenario,
        )
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
            if self.legacy and self.checks == 1:
                output = finding()
                assert {x["claim_id"]: x["input_digest"] for x in output["checks"]} == {
                    x["claim_id"]: x["input_digest"] for x in ctx["claim_inputs"]
                }
                assert ctx["unscored_prose"]["questions"][0] == original()["questions"][0]
            else:
                output = {
                    "checks": [
                        {
                            "claim_id": x["claim_id"],
                            "input_digest": x["input_digest"],
                            "decision": "supported",
                            "reason": "Synthetic fixture; human support unmeasured.",
                        }
                        for x in ctx["claim_inputs"]
                    ],
                    "prose_review": "procedural_only",
                    "prose_findings": [],
                }
            if self.residual or self.malformed or self.uncertain:
                output.update(
                    prose_review="abstain" if self.uncertain else "unscored_factual_content",
                    prose_findings=[
                        {
                            "field": "questions",
                            "index": 2 if self.malformed else 0,
                            "reason": finding()["prose_findings"][0]["reason"],
                        }
                    ],
                )
            assert ctx["unscored_prose"]["questions"]
        else:
            if self.legacy:
                output = original()
                if ctx["phase"] == "repair":
                    assert (
                        ctx["previous_prose_review"]["prose_findings"]
                        == finding()["prose_findings"]
                    )
                    assert ctx["procedural_draft"]["questions"][0] == original()["questions"][0]
                    output["questions"][0] = c.QUESTION_INTENTS["measured_and_proposed"]
            else:
                units = ctx["sealed_request"]["units"]
                handles = list(units)
                output = {
                    "claims": [
                        {
                            "claim_id": "c1",
                            "text": units[handles[0]]["quote"][:110],
                            "handles": [handles[0]],
                            "required_scope": units[handles[0]]["scope"],
                        }
                    ],
                    "background_claims": ["c1"],
                    "assumption_claims": [],
                    "limitation_claims": [],
                    "gaps": ["methods"],
                    "questions": [{"intent": "measured_and_proposed", "claim_ids": []}],
                    "proposal": "request_context",
                    "abstention": None,
                }
                if self.scenario == "comparison":
                    output["claims"].append(
                        {
                            "claim_id": "c2",
                            "text": units[handles[1]]["quote"][:110],
                            "handles": [handles[1]],
                            "required_scope": units[handles[1]]["scope"],
                        }
                    )
                    output.update(comparison_claims=["c1", "c2"], comparison_basis=["c1", "c2"])
                if self.scenario == "insufficient":
                    output.update(
                        claims=[], background_claims=[], abstention="application_context_required"
                    )
        validate(output, body["output_config"]["format"]["schema"])
        return httpx.Response(
            200,
            json={
                "id": "synthetic-" + str(len(self.calls)),
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(output)}],
            },
        )


async def test_captured_v7_failure_remains_failure_without_new_repair_policy(store):
    inputs = support.setup(store, routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses(legacy=True)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(AdmissionError, match="d5_unscored_factual_prose"):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] == "failed" and result["result"] is None and len(transport.calls) == 4
    assert json.loads(result["contacts"][1]["response"]["content"][0]["text"]) == original()
    assert json.loads(result["contacts"][3]["response"]["content"][0]["text"]) == finding()


async def test_exact_captured_finding_can_take_one_bound_repair_and_mandatory_recheck(store):
    inputs = support.setup(
        store, routes=deepcopy(ROUTES), source_setup=source, repair_located_prose=True
    )
    transport = Responses(legacy=True)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and len(transport.calls) == 8
    assert [x["stage"] for x in result["steps"]] == ["draft", "check", "repair", "check"]
    assert result["result"]["draft"]["questions"][0] == c.QUESTION_INTENTS["measured_and_proposed"]
    assert result["steps"][0]["output"]["questions"][0] == original()["questions"][0]
    assert not result["result"]["checker_qualified"]


@pytest.mark.parametrize("scenario", ["learn", "comparison", "insufficient"])
async def test_neutral_intents_use_production_adapter_and_render_checked_text(store, scenario):
    inputs = support.setup(
        store,
        mode="research" if scenario == "comparison" else "learn",
        comparison=scenario == "comparison",
        routes=deepcopy(ROUTES),
        procedural_contract=True,
    )
    transport = Responses(scenario=scenario)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(2):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and len(transport.calls) == 4
    assert result["result"]["draft"]["questions"] == [c.QUESTION_INTENTS["measured_and_proposed"]]
    from src.workspace.d5_results import QualificationResults

    displayed = QualificationResults(store).snapshot("d5-run", job["id"])
    assert displayed["source_binding_intact"]
    assert displayed["assistance_output"]["questions"] == result["result"]["draft"]["questions"]
    assert isinstance(displayed["steps"][0]["output"]["questions"][0], dict)
    if scenario == "insufficient":
        assert result["result"]["content_status"] == "abstained"
        assert (
            result["result"]["draft"]["abstention"]
            == c.ABSTENTION_INTENTS["application_context_required"]
        )


@pytest.mark.parametrize("mode", ["residual", "malformed", "uncertain"])
async def test_located_repair_is_bounded_and_residual_or_uncertain_prose_rejects(store, mode):
    inputs = support.setup(store, routes=deepcopy(ROUTES), procedural_contract=True)
    transport = Responses(**{mode: True})
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    if mode == "residual":
        await adapter.advance(job["id"])
        await adapter.advance(job["id"])
    with pytest.raises(ValueError):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] == "failed" and result["result"] is None
    assert len(transport.calls) == (8 if mode == "residual" else 4)


@pytest.mark.parametrize(
    "field,value",
    [
        ("questions", [original()["questions"][0]]),
        ("questions", [{"intent": "invented", "claim_ids": []}]),
        ("questions", [{"intent": "methods", "claim_ids": ["u-invalid"]}]),
        ("proposal", "The method guarantees safe deployment."),
        ("gaps", ["The method is unsafe."]),
        ("abstention", "The method cannot generalize."),
    ],
)
async def test_free_procedural_assertions_are_not_wire_or_local_valid(field, value):
    raw = original()
    raw.update(
        gaps=["methods"],
        questions=[{"intent": "methods", "claim_ids": []}],
        proposal="request_context",
    )
    raw[field] = value
    handles = [h for x in raw["claims"] for h in x["handles"]]
    with pytest.raises(ValidationError):
        validate(
            raw, c.schemas(handles, purpose="single_paper", revision=c.PROCEDURAL_REVISION)["wire"]
        )
    with pytest.raises(ValueError):
        c.response_model(
            handles, purpose="single_paper", revision=c.PROCEDURAL_REVISION
        ).model_validate(raw)


@pytest.mark.parametrize(
    "ids,intent,valid",
    [
        ([], "investigate_claim", False),
        (["c1"], "investigate_claim", True),
        (["c6"], "methods", True),
        (["c1", "c1"], "methods", False),
        (["c1"], "methods", True),
    ],
)
async def test_premise_references_need_unique_emitted_scored_claims(ids, intent, valid):
    raw = original()
    raw.update(
        gaps=["methods"],
        questions=[{"intent": intent, "claim_ids": ids}],
        proposal="request_context",
    )
    model = c.response_model(
        [h for x in raw["claims"] for h in x["handles"]],
        purpose="single_paper",
        revision=c.PROCEDURAL_REVISION,
    )
    if valid:
        model.model_validate(raw)
    else:
        with pytest.raises(ValueError):
            model.model_validate(raw)


async def test_schema_bounds_refs_and_rendering_cover_procedural_fields():
    raw = original()
    raw.update(
        gaps=["methods"],
        questions=[{"intent": "investigate_claim", "claim_ids": ["c1"]}],
        proposal="inspect_methods",
    )
    model = c.response_model(
        [h for x in raw["claims"] for h in x["handles"]],
        purpose="single_paper",
        revision=c.PROCEDURAL_REVISION,
    )
    assert "c1" in c.render_procedures(raw)["questions"][0]
    assert c.render_procedures(raw)["proposal"] == c.ACTION_INTENTS["inspect_methods"]
    for change, error in [
        (
            {
                "claims": [],
                "background_claims": [],
                "assumption_claims": [],
                "limitation_claims": [],
                "questions": [{"intent": "methods", "claim_ids": []}],
                "abstention": None,
            },
            "claims_or_abstention",
        ),
        (
            {
                "claims": [raw["claims"][0]],
                "questions": [{"intent": "methods", "claim_ids": ["c6"]}],
                "background_claims": [],
                "limitation_claims": [],
            },
            "section_reference",
        ),
        (
            {
                "claims": [{**raw["claims"][0], "text": " "}],
                "background_claims": [],
                "limitation_claims": [],
            },
            "blank_claim",
        ),
        (
            {
                "claims": [{**raw["claims"][0], "handles": raw["claims"][0]["handles"] * 2}],
                "background_claims": [],
                "limitation_claims": [],
            },
            "duplicate_handle",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            model.model_validate({**raw, **change})
    # Multiple sources retain separate identities, never a joined quote.
    comparison = c.response_model(
        [h for x in raw["claims"] for h in x["handles"]],
        purpose="research_comparison",
        revision=c.PROCEDURAL_REVISION,
    )
    for basis, claims, error in [
        (["c6", "c6"], ["c1"], "comparison_basis"),
        (["c1"], ["c1"], "separate_evidence"),
        (["c1", "c2"], [], "basis_without"),
    ]:
        with pytest.raises(ValueError, match=error):
            comparison.model_validate(
                {**raw, "comparison_claims": claims, "comparison_basis": basis}
            )


async def test_new_cohort_and_eligibility_partition_are_reproducible(store):
    from src.workspace.admission import _digest
    from src.workspace.d5_freeze import (
        PROCEDURAL_QUESTIONS,
        freeze,
        question_specifications,
        verify,
    )
    from tests.test_workspace_d5_benchmark import corpus

    previous = corpus(store)
    excluded = [previous["corpus"][0]["version_id"]]
    p = freeze(
        store,
        {**previous["profile"], "research_question": ""},
        previous["history"],
        cohort_revision="procedural-v8",
        heldout_excluded_versions=excluded,
    )
    verify(p)
    assert [x["id"] for x in p["cases"]] == [x[0] for x in PROCEDURAL_QUESTIONS]
    assert all(
        excluded[0] not in [x["version_id"] for x in case["ranking"]]
        for case in p["cases"]
        if case["cohort"] == "fresh_system"
    )
    assert all(
        case["sealed"]["schema_revision"] == c.PROCEDURAL_REVISION
        for case in p["cases"]
        if case.get("sealed")
    )
    changed = deepcopy(p)
    changed["cases"][2]["question"] = "A changed held-out question"
    changed["packet_digest"] = _digest({k: v for k, v in changed.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError, match="question_or_cohort"):
        verify(changed)
    with pytest.raises(AdmissionError, match="unknown_frozen_cohort"):
        question_specifications("unknown")


@pytest.mark.parametrize("mutation", ["digest", "duplicate", "missing"])
async def test_prose_repair_cannot_rescue_an_invalid_claim_verdict_batch(store, mutation):
    inputs = support.setup(store, routes=deepcopy(ROUTES), procedural_contract=True)
    transport = Responses(residual=True)

    async def handler(request):
        response = await transport(request)
        if request.url.path.endswith("count_tokens"):
            return response
        raw = response.json()
        payload = json.loads(raw["content"][0]["text"])
        if "checks" in payload:
            if mutation == "digest":
                payload["checks"][0]["input_digest"] = "wrong"
            elif mutation == "duplicate":
                payload["checks"].append(payload["checks"][0])
            else:
                payload["checks"] = []
            raw["content"][0]["text"] = json.dumps(payload)
        return httpx.Response(200, json=raw)

    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(AdmissionError, match="checker_claim_binding"):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] == "failed" and result["result"] is None and len(transport.calls) == 4
