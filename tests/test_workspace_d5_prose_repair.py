"""Preserved v5 failure and synthetic corrections. No independent quality labels."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from jsonschema import validate
from psycopg.types.json import Jsonb

from src.workspace import assistance as a
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
FIX = Path(__file__).parent / "fixtures/d5/stage-b-v5"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def source(store):

    material = json.loads((FIX / "selected-materials.json").read_text())[0]
    item = ingest(
        store,
        work_id=material["work_id"],
        version_id=material["version_id"],
        abstract="Public metadata fixture; retained excerpts are separately versioned.",
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
    service = a.AssistanceService(store)
    units = service.catalog("a", item["work_id"], item["version_id"])["units"]
    wanted = json.loads((FIX / "original-draft.json").read_text())["claims"][0]["handles"][0]
    unit = next(u for u in units if u["id"] == wanted)
    ref = unit["reference"]
    value = a.AssistanceInput(
        mode="learn",
        work_id=ref["work_id"],
        version_id=ref["version_id"],
        material_ids=(ref["material_id"],),
        span_ids=(ref["span_id"],),
        unit_ids=(wanted,),
    )
    return service, value


def corrected():
    old = json.loads((FIX / "original-draft.json").read_text())
    value = {k: deepcopy(old[k]) for k in ("claims", "abstention")}
    value["claims"][4]["text"] = (
        "The excerpt says the result perhaps reflects a trade-off between factuality and flexibility, motivating the combination of the two methods."
    )
    value.update(
        background_claims=["c1"],
        assumption_claims=[],
        limitation_claims=["c3", "c4"],
        gaps=["Inspect the full method section and evaluation tables before drawing conclusions."],
        questions=[
            "What prompt structure and action space are described in the full methods?",
            "Does further evidence establish any performance gains for combined methods, and under what conditions?",
        ],
        proposal="Read the method section and evaluation tables; record supported findings as cited claims.",
    )
    return value


class Responses:
    def __init__(self, scenario="corrected"):
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
            value = {
                "checks": [
                    {
                        "claim_id": x["claim_id"],
                        "input_digest": x["input_digest"],
                        "decision": "unsupported"
                        if self.scenario == "repair" and self.checks == 1 and x["claim_id"] == "c5"
                        else "supported",
                        "reason": "Synthetic test decision; no human qualification",
                    }
                    for x in ctx["claim_inputs"]
                ],
                "prose_review": "procedural_only",
                "prose_findings": [],
            }
            if self.scenario == "presupposition":
                assert "How large are the gains" in ctx["unscored_prose"]["questions"][0]
                value.update(
                    prose_review="unscored_factual_content",
                    prose_findings=[
                        {
                            "field": "questions",
                            "index": 0,
                            "reason": "The question presupposes a gain not established by a scored claim.",
                        }
                    ],
                )
        else:
            value = corrected()
            if self.scenario == "legacy":
                value = json.loads((FIX / "original-draft.json").read_text())
            if self.scenario == "presupposition":
                value["questions"] = ["How large are the gains of the combined method?"]
            if self.scenario == "repair" and ctx["phase"] == "draft":
                value["claims"][4]["text"] = json.loads((FIX / "original-draft.json").read_text())[
                    "claims"
                ][4]["text"]
        if self.scenario != "legacy":
            validate(value, body["output_config"]["format"]["schema"])
        return httpx.Response(
            200,
            json={
                "id": f"synthetic-{len(self.calls)}",
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(value)}],
            },
        )


async def test_original_provider_payload_is_preserved_and_refused_by_new_schema(store):
    original = json.loads((FIX / "original-draft.json").read_text())
    verdict = json.loads((FIX / "original-checker.json").read_text())
    assert (
        "perhaps" not in original["claims"][4]["text"]
        and verdict["prose_review"] == "unscored_factual_content"
    )
    inputs = support.setup(store, routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses("legacy")
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    with pytest.raises(ValueError):
        await adapter.advance(job["id"])
    assert len(transport.calls) == 2 and adapter.snapshot(job["id"])["state"] == "failed"


@pytest.mark.parametrize("scenario", ["corrected", "repair"])
async def test_cited_sections_and_qualified_c5_use_scored_claims_and_bounded_repair(
    store, scenario
):
    inputs = support.setup(store, routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses(scenario)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    for _ in range(4 if scenario == "repair" else 2):
        result = await adapter.advance(job["id"])
    assert result["state"] == "ready" and not result["result"]["everyday_generation"]
    steps = result["steps"]
    assert [x["stage"] for x in steps] == (
        ["draft", "check", "repair", "check"] if scenario == "repair" else ["draft", "check"]
    )
    final = next(s["output"] for s in reversed(steps) if s["stage"] in {"draft", "repair"})
    claim = next(c for c in final["claims"] if c["claim_id"] == "c5")
    assert (
        "perhaps" in claim["text"]
        and "CoT-SC" not in claim["text"]
        and final["background_claims"] == ["c1"]
    )
    assert "perhaps" in next(iter(inputs.settings["d5_request"]["units"].values()))["quote"]
    assert "background" not in final and "assumptions" not in final
    assert len(transport.calls) == (8 if scenario == "repair" else 4)


async def test_presupposed_finding_in_question_still_blocks_acceptance_and_locates_field(store):
    inputs = support.setup(store, routes=deepcopy(ROUTES), source_setup=source)
    transport = Responses("presupposition")
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    with pytest.raises(AdmissionError, match="unscored_factual_prose"):
        await adapter.advance(job["id"])
    result = adapter.snapshot(job["id"])
    assert result["state"] == "failed" and result["result"] is None and len(transport.calls) == 4
    verdict = json.loads(result["contacts"][-1]["response"]["content"][0]["text"])
    assert (
        verdict["prose_findings"][0]["field"] == "questions"
        and verdict["prose_findings"][0]["index"] == 0
    )


@pytest.mark.parametrize("field", ["background_claims", "assumption_claims", "limitation_claims"])
async def test_unknown_or_duplicate_section_ids_cannot_borrow_support(field):
    value = corrected()
    value[field] = ["c1", "c1"]
    with pytest.raises(ValueError):
        c.response_model(value["claims"][0]["handles"], purpose="single_paper").model_validate(
            value
        )
    value[field] = ["c9"]
    with pytest.raises(ValueError):
        c.response_model(value["claims"][0]["handles"], purpose="single_paper").model_validate(
            value
        )


@pytest.mark.parametrize(
    "review,findings",
    [
        ("unscored_factual_content", []),
        ("abstain", []),
        ("procedural_only", [{"field": "proposal", "index": None, "reason": "A hidden assertion"}]),
    ],
)
async def test_checker_must_locate_nonprocedural_or_uncertain_prose(review, findings):
    with pytest.raises(ValueError):
        a.Checks.model_validate({"checks": [], "prose_review": review, "prose_findings": findings})


@pytest.mark.parametrize(
    "field,index,prose",
    [
        ("questions", None, {"questions": ["An assertion?"]}),
        ("proposal", 0, {"proposal": "An assertion"}),
        ("proposal", None, {}),
        ("questions", 1, {"questions": ["An assertion?"]}),
        ("questions", 0, {"questions": "An assertion?"}),
        ("proposal", None, {"proposal": " "}),
        ("proposal", None, {"proposal": []}),
    ],
)
async def test_checker_location_must_identify_actual_nonempty_field(field, index, prose):
    with pytest.raises(ValueError):
        value = a.Checks.model_validate(
            {
                "checks": [],
                "prose_review": "unscored_factual_content",
                "prose_findings": [{"field": field, "index": index, "reason": "Unscored"}],
            }
        )
        value.validate_locations(prose)


async def test_checker_duplicate_locations_refused_and_scalar_location_valid():
    finding = {"field": "proposal", "index": None, "reason": "Unscored assertion"}
    value = {"checks": [], "prose_review": "unscored_factual_content", "prose_findings": [finding]}
    a.Checks.model_validate(value).validate_locations({"proposal": "A substantive assertion"})
    with pytest.raises(ValueError, match="duplicate_prose_finding"):
        a.Checks.model_validate({**value, "prose_findings": [finding, finding]})


async def test_research_comparison_uses_scored_claim_references_from_each_source(store):
    from tests.test_workspace_d5_opus import Mixed

    inputs = support.setup(store, routes=deepcopy(ROUTES), mode="research", comparison=True)
    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(Mixed()))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    result = await adapter.advance(job["id"])
    output = result["steps"][0]["output"]
    assert result["state"] == "ready"
    assert (
        output["comparison_claims"] == ["c1", "c2"]
        and output["comparison_basis"] == ["c1", "c2"]
        and "comparison" not in output
    )
    units = inputs.settings["d5_request"]["units"]
    assert len({units[h]["work_id"] for claim in output["claims"] for h in claim["handles"]}) == 2


async def test_insufficient_evidence_has_empty_scored_sections_and_mandatory_check(store):
    from tests.test_workspace_d5_opus import Mixed

    inputs = support.setup(store, routes=deepcopy(ROUTES))
    delegate = Mixed()

    async def handler(request):
        response = await delegate(request)
        if request.url.path.endswith("count_tokens"):
            return response
        raw = response.json()
        output = json.loads(raw["content"][-1]["text"])
        if "claims" in output:
            output.update(
                claims=[],
                background_claims=[],
                assumption_claims=[],
                limitation_claims=[],
                abstention="Insufficient selected evidence to answer; inspect additional sources.",
            )
        else:
            output["checks"] = []
        raw["content"][-1]["text"] = json.dumps(output)
        return httpx.Response(200, json=raw)

    adapter = D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    job = adapter.start(inputs.settings["d5_request_id"])
    await adapter.advance(job["id"])
    result = await adapter.advance(job["id"])
    assert (
        result["state"] == "ready"
        and result["result"]["content_status"] == "abstained"
        and len(delegate.calls) == 4
    )


async def test_legacy_payload_is_read_only_versioned_not_silently_current():
    from src.workspace.material import SourceMaterial, SourceSpan

    data = json.loads((FIX / "selected-materials.json").read_text())
    materials = [
        SourceMaterial(
            **{
                **m,
                "pages": tuple(m["pages"]),
                "warnings": tuple(m["warnings"]),
                "page_numbers": tuple(m["page_numbers"]) if m["page_numbers"] else None,
                "spans": tuple(SourceSpan(**s) for s in m["spans"]),
            }
        )
        for m in data
    ]
    catalog = c.coherent_units(materials, {s.span_id for m in materials for s in m.spans})
    old = json.loads((FIX / "original-draft.json").read_text())
    selected = {h for claim in old["claims"] for h in claim["handles"]}
    catalog = {h: ref for h, ref in catalog.items() if h in selected}
    legacy, claims = c.resolve_draft(
        old, catalog, materials, purpose="single_paper", revision=c.LEGACY_REVISION
    )
    assert len(claims) == 6 and legacy.claims[4].text == old["claims"][4]["text"]
    with pytest.raises(ValueError):
        c.resolve_draft(old, catalog, materials, purpose="single_paper")
