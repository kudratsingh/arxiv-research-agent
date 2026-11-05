"""Retained failure regressions and compact provenance contracts; no provider."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator
from psycopg.types.json import Jsonb
from pydantic import TypeAdapter

from src.workspace import provider_adapter as p
from src.workspace.evidence_contract import draft_schema, evidence_catalog
from src.workspace.executor import _material
from src.workspace.grounding import GroundingError, ResearchClaim, validate_claims
from src.workspace.material import extract_text
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parent / "fixtures" / "qualification_failures"


def compact(kind, handles):
    return {"kind": kind, "abstention": None, "title": "Evidence-limited review",
            "claims": [{"claim_id": "c1", "text": "The source describes a bounded evaluation.",
                        "handles": [handles[0]], "section": "overview"}],
            "question": "Which conditions were evaluated?", "proposal": None,
            "limitation": "Only selected retained passages were examined."}


def test_real_max_tokens_receipt_and_incomplete_json_are_both_reproduced():
    raw = (FIXTURES / "sonnet46-max-tokens.json").read_bytes()
    manifest = json.loads((FIXTURES / "receipt-manifest.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest["original_response_sha256"]
    response = json.loads(raw)
    assert response["stop_reason"] == "max_tokens" and response["usage"]["output_tokens"] == 1200
    with pytest.raises(p.AdmissionError, match="incomplete_output"):
        p.response_output(response, "claude-sonnet-4-6")
    with pytest.raises(json.JSONDecodeError):
        json.loads(response["content"][0]["text"])
    # Even a false end_turn flag cannot turn the retained JSON prefix into a result.
    with pytest.raises(json.JSONDecodeError):
        p.response_output({**response, "stop_reason": "end_turn"}, "claude-sonnet-4-6")


def test_recovered_claim_prefix_has_four_exact_quote_offset_failures_not_support():
    response = json.loads((FIXTURES / "sonnet46-max-tokens.json").read_text())
    text = response["content"][0]["text"]
    index = text.index("[", text.index('"claims":')) + 1
    recovered = []
    while True:
        index += len(text[index:]) - len(text[index:].lstrip(" ,\n\t"))
        try:
            claim, index = json.JSONDecoder().raw_decode(text, index)
        except json.JSONDecodeError:
            break
        recovered.append(TypeAdapter(ResearchClaim).validate_python(claim))
    assert len(recovered) == 4
    material = _material(json.loads((FIXTURES / "source-material.json").read_text()))
    for claim in recovered:
        with pytest.raises(GroundingError, match="quote_not_in_retained_span"):
            validate_claims([claim], [material])
    assert [len(c.evidence[0].quote) for c in recovered] == [68, 110, 160, 144]
    assert all(c.evidence[0].end - c.evidence[0].start == 875 for c in recovered)
    # The old model-authored metadata is explicitly forbidden on the new wire.
    with pytest.raises(ValueError):
        draft_schema("summary").model_validate({"kind": "summary", "title": "Do not accept",
            "claims": [asdict(recovered[0])], "question": None, "proposal": None,
            "limitation": "Unaccepted prefix"})


def test_unicode_and_repeated_text_are_resolved_by_handle_not_substring_search():
    text = ("αβ🙂 cafe\u0301 repeated text. " * 60)
    first = extract_text(text, work_id="work", version_id="v1", scope="abstract")
    second = extract_text(text, work_id="work", version_id="v2", scope="abstract")
    ids = {s.span_id for s in first.spans}
    catalog = evidence_catalog([first], ids)
    assert catalog == evidence_catalog([first], ids)
    assert not catalog.keys() & evidence_catalog([second], {s.span_id for s in second.spans}).keys()
    assert len({(r.span_id, r.start, r.end) for r in catalog.values()}) == len(catalog)
    for ref in catalog.values():
        span = next(s for s in first.spans if s.span_id == ref.span_id)
        assert ref.quote == span.text[ref.start - span.start:ref.end - span.start]
        assert ref.end - ref.start == len(ref.quote) <= 240
        ref.quote.encode("utf-8")


@pytest.mark.parametrize("kind,count,budget", [("summary", 2, 1800), ("deep_dive", 3, 2800)])
def test_realistic_maximal_compact_outputs_validate_local_and_exact_transformed_wire(kind, count, budget):
    data = compact(kind, ["e0123456789ab"])
    data.update(title="T" * 96, question="Q" * 120, limitation="L" * 160,
                proposal="Propose a fixed baseline." if kind == "deep_dive" else None)
    data["claims"] = [{"claim_id": f"c{i+1}", "text": "F" * 180,
                       "handles": ["e0123456789ab", "e123456789abc"], "section": "overview"}
                      for i in range(count)]
    model = draft_schema(kind)
    model.model_validate(data)
    Draft202012Validator(transform_schema(model)).validate(data)
    assert len(json.dumps(data).encode()) < budget
    # Byte size is a payload bound, not a token measurement.
    with pytest.raises(ValueError):
        model.model_validate({**data, "claims": data["claims"] + [data["claims"][0]]})
    missing_kind = {k: v for k, v in data.items() if k != "kind"}
    with pytest.raises(ValueError):
        model.model_validate(missing_kind)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(missing_kind))


def test_resolution_produces_exact_refs_but_never_claims_factual_support(store):
    _, material_id, _ = support.support.source(store, abstract="αβ🙂 exact quote. " * 50)
    inputs = p.prepare(store, "a", "summary", [material_id])
    instance = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(lambda _: None))
    context = json.loads(instance.request()["body"]["messages"][0]["content"])
    output = compact("summary", [context["evidence"][1]["handle"]])
    draft = instance._draft(output)
    _, materials = instance._context()
    report = validate_claims(draft.claims, materials)
    assert report.assessments[0].identity_resolved and report.checked == report.supported == 0
    ref = draft.claims[0].evidence[0]
    assert ref.quote == context["evidence"][1]["text"] and ref.start == 240
    assert ref.version_id == inputs.sources[0].version_id
    with pytest.raises(p.AdmissionError, match="unknown_handle"):
        instance._draft(compact("summary", ["e000000000000"]))


@pytest.mark.parametrize("field", ["pages", "spans"])
def test_mutated_retained_material_refuses_before_new_request(store, field):
    inputs = support.prepared(store)
    instance = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(lambda _: None))
    with store.pool.connection() as conn:
        data = conn.execute("SELECT data FROM workspace_material WHERE material_id=%s", (inputs.sources[0].material_id,)).fetchone()[0]
        if field == "pages":
            data["pages"][0] += " mutated"
        else:
            data["spans"][0]["text"] += " mutated"
        conn.execute("UPDATE workspace_material SET data=%s WHERE material_id=%s", (Jsonb(data), inputs.sources[0].material_id))
    with pytest.raises(ValueError):
        instance.request()


def test_previous_version_handle_is_not_a_new_version_reference(store):
    _, m1, _ = support.support.source(store, 1)
    first = p.prepare(store, "a", "summary", [m1])
    a1 = p.QualificationAdapter(store, "a", first, transport=httpx.MockTransport(lambda _: None))
    h1 = json.loads(a1.request()["body"]["messages"][0]["content"])["evidence"][0]["handle"]
    _, m2, _ = support.support.source(store, 2)
    a2 = p.QualificationAdapter(store, "a", p.prepare(store, "a", "summary", [m2]), transport=httpx.MockTransport(lambda _: None))
    with pytest.raises(p.AdmissionError, match="unknown_handle"):
        a2._draft(compact("summary", [h1]))


def test_exact_metadata_observation_keeps_metadata_scope_not_paper_excerpt(store):
    item = support.support.support.ingest(store, access_state="metadata")
    material = extract_text("release tag sdk==0.4.12", work_id=item["work_id"], version_id=item["version_id"], scope="metadata")
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_material VALUES (%s,%s,%s,%s,%s)",
            (material.material_id, material.version_id, material.content_hash, material.scope, Jsonb(asdict(material))))
    inputs = p.prepare(store, "a", "summary", [material.material_id])
    adapter = p.QualificationAdapter(store, "a", inputs, transport=httpx.MockTransport(lambda _: None))
    handle = next(iter(evidence_catalog([material], {s.span_id for s in material.spans})))
    draft = adapter._draft(compact("summary", [handle]))
    claim = draft.claims[0]
    assert claim.required_scope == claim.evidence[0].scope == "metadata"
    report = validate_claims(draft.claims, [material])
    assert report.assessments[0].scope_compatible and report.checked == 0


@pytest.mark.asyncio
async def test_explicit_insufficient_evidence_abstention_has_no_checker_or_zero_pass_rate(store):
    adapter, transport, job = support.setup(store)

    def abstain(value):
        output = json.loads(value["content"][0]["text"])
        output.update(claims=[], proposal=None, abstention="The selected abstract cannot establish the requested deployment result.")
        return {**value, "content": [{"type": "text", "text": json.dumps(output)}]}

    transport.change = abstain
    result = await adapter.advance(job)
    assert result["state"] == "ready" and result["result"]["content_status"] == "abstained"
    assert len(transport.calls) == 2  # one paired count/draft, no pointless checker
    assert result["result"]["grounding"]["total_factual"] == 0
    assert result["result"]["grounding"]["support_ratio"] is None
    assert not result["result"]["everyday_generation"]


@pytest.mark.asyncio
async def test_missing_checker_verdict_is_not_accepted_as_support(store):
    adapter, transport, job = support.setup(store)
    await adapter.advance(job)
    transport.change = lambda v: {**v, "content": [{"type": "text", "text": json.dumps({"checks": []})}]}
    with pytest.raises(ValueError):
        await adapter.advance(job)
    result = adapter.snapshot(job)
    assert result["state"] == "failed" and result["result"] is None
