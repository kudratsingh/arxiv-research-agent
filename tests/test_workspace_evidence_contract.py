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
from src.workspace.evidence_contract import (
    CompactDraft,
    draft_schema,
    evidence_catalog,
    resolve_handles,
)
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
                        "evidence_handle": handles[0], "section": "overview"}],
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
        draft_schema("summary", ["e0123456789ab"]).model_validate({"kind": "summary", "title": "Do not accept",
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
                proposal="P" * 240)
    data["claims"] = [{"claim_id": f"c{i+1}", "text": "F" * 240,
                       "evidence_handle": "e0123456789ab", "section": "overview"}
                      for i in range(count)]
    model = draft_schema(kind, ["e0123456789ab"])
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
    with pytest.raises(ValueError, match="Input should be"):
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
    with pytest.raises(ValueError, match="Input should be"):
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


def test_retained_complete_development_response_fits_whole_budget_without_token_raise(store):
    raw = (FIXTURES / "sonnet55-complete-display-overflow.json").read_bytes()
    manifest = json.loads((FIXTURES / "receipt-manifest.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest["sonnet55_complete_display_overflow_sha256"]
    response = json.loads(raw)
    output = p.response_output(response, "claude-sonnet-5-5")
    assert response["usage"]["output_tokens"] == 352 < 1200
    assert len(json.dumps(output, ensure_ascii=False).encode()) == 1040 < 1800
    assert [len(c["text"]) for c in output["claims"]] == [166, 182]
    assert len(output["proposal"]) == 177
    with pytest.raises(ValueError):
        draft_schema("summary", ["e0123456789ab"]).model_validate(output)
    assert list(Draft202012Validator(transform_schema(draft_schema("summary", ["e0123456789ab"]))).iter_errors(output))
    # The original response is historical, never translated into an accepted V8 draft.
    inputs = support.prepared(store)
    assert inputs.settings["output_tokens"] == 1200


def test_whole_payload_guard_stays_hard_when_individual_fields_fit():
    data = compact("summary", ["e0123456789ab"])
    data["claims"] = [{"claim_id": f"c{i+1}", "text": "🙂" * 240,
                       "evidence_handle": "e0123456789ab", "section": "overview"} for i in range(2)]
    with pytest.raises(ValueError, match="compact_response_byte_limit"):
        draft_schema("summary", ["e0123456789ab"]).model_validate(data)


def test_adjacent_handles_merge_exactly_without_weakening_duplicate_parent_or_gap_checks():
    material = extract_text("αβ🙂 repeated evidence. " * 80, work_id="work", version_id="v1", scope="abstract")
    catalog = evidence_catalog([material], {s.span_id for s in material.spans})
    keys = list(catalog)
    refs = resolve_handles(catalog, [keys[1], keys[0]], [material])
    assert len(refs) == 1 and refs[0].start == 0 and refs[0].end == 480
    assert refs[0].quote == catalog[keys[0]].quote + catalog[keys[1]].quote
    with pytest.raises(ValueError, match="noncontiguous_or_overlapping"):
        resolve_handles(catalog, [keys[0], keys[2]], [material])
    with pytest.raises(ValueError, match="noncontiguous_or_overlapping"):
        resolve_handles(catalog, [keys[0], keys[0]], [material])


def test_checker_display_allowance_preserves_hard_payload_budget_and_wire_shape():
    valid = {"checks": [{"claim_id": f"c{i+1}", "input_digest": "sha256:" + "a" * 64,
                         "decision": "supported", "reason": "R" * 240} for i in range(3)]}
    p.Checks.model_validate(valid)
    Draft202012Validator(transform_schema(p.Checks)).validate(valid)
    invalid = {"checks": [{**v, "reason": "🙂" * 240} for v in valid["checks"]]}
    with pytest.raises(ValueError, match="checker_response_byte_limit"):
        p.Checks.model_validate(invalid)


@pytest.mark.parametrize("section", ["overview", "method", "assumptions", "comparison"])
def test_summary_section_is_overview_only_in_local_and_exact_wire_schema(section):
    data = compact("summary", ["e0123456789ab"])
    data["claims"][0]["section"] = section
    model = draft_schema("summary", ["e0123456789ab"])
    wire = transform_schema(model)
    claim_ref = wire["properties"]["claims"]["items"]["$ref"].rsplit("/", 1)[-1]
    assert wire["$defs"][claim_ref]["properties"]["section"]["enum"] == ["overview"]
    validator = Draft202012Validator(wire)
    if section == "overview":
        assert model.model_validate(data).claims[0].section == "overview"
        validator.validate(data)
    else:
        with pytest.raises(ValueError):
            model.model_validate(data)
        assert list(validator.iter_errors(data))
        # Preserve the original semantic guard for generic CompactDraft callers.
        with pytest.raises(ValueError, match="summary_bounds_or_sections"):
            CompactDraft.model_validate(data)


@pytest.mark.parametrize("section", ["overview", "method", "assumptions", "comparison"])
def test_study_section_vocabulary_remains_available_locally_and_on_wire(section):
    data = compact("deep_dive", ["e0123456789ab"])
    data["claims"][0]["section"] = section
    model = draft_schema("deep_dive", ["e0123456789ab"])
    assert model.model_validate(data).claims[0].section == section
    Draft202012Validator(transform_schema(model)).validate(data)


def test_retained_v5_complete_comparison_response_stays_unaccepted_by_summary_contract():
    raw = (FIXTURES / "sonnet55-summary-section-mismatch.json").read_bytes()
    manifest = json.loads((FIXTURES / "receipt-manifest.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest["sonnet55_summary_section_mismatch_sha256"]
    retained = json.loads(raw)
    assert retained["result_accepted"] is False and retained["human_labels"] is None
    response = retained["response"]
    assert response["stop_reason"] == "end_turn" and response["usage"]["output_tokens"] == 346
    output = p.response_output(response, "claude-sonnet-5-5")
    assert [claim["section"] for claim in output["claims"]] == ["overview", "comparison"]
    with pytest.raises(ValueError):
        draft_schema("summary", ["e0123456789ab"]).model_validate(output)
    errors = list(Draft202012Validator(transform_schema(draft_schema("summary", ["e0123456789ab"]))).iter_errors(output))
    assert any(list(error.path) == ["claims", 1, "section"] for error in errors)


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
def test_exact_wire_retains_kind_and_finite_claim_id_constraints(kind):
    model = draft_schema(kind, ["e0123456789ab"])
    wire = transform_schema(model)
    assert wire["properties"]["kind"]["enum"] == [kind]
    claim_ref = wire["properties"]["claims"]["items"]["$ref"].rsplit("/", 1)[-1]
    assert wire["$defs"][claim_ref]["properties"]["claim_id"]["enum"] == ["c1", "c2", "c3"]
    validator = Draft202012Validator(wire)
    for claim_id in ["c1", "c2", "c3"]:
        data = compact(kind, ["e0123456789ab"])
        data["claims"][0]["claim_id"] = claim_id
        model.model_validate(data)
        validator.validate(data)
    for wrong_kind in ["deep_dive" if kind == "summary" else "summary", "invented"]:
        data = compact(wrong_kind, ["e0123456789ab"])
        with pytest.raises(ValueError):
            model.model_validate(data)
        assert list(validator.iter_errors(data))
    for wrong_id in ["c0", "c4", "invented", "", "c1\n"]:
        data = compact(kind, ["e0123456789ab"])
        data["claims"][0]["claim_id"] = wrong_id
        with pytest.raises(ValueError):
            model.model_validate(data)
        assert list(validator.iter_errors(data))


def test_runtime_only_semantic_limits_remain_strict_when_wire_cannot_express_them():
    # The SDK describes unsupported cardinality/length constraints rather than
    # enforcing them. Cross-field conditions and UTF8 byte caps also stay local.
    model = draft_schema("summary", ["e0123456789ab"])
    wire = Draft202012Validator(transform_schema(model))
    missing_abstention = compact("summary", ["e0123456789ab"])
    missing_abstention["claims"] = []
    wire.validate(missing_abstention)
    with pytest.raises(ValueError, match="claims_or_explicit_abstention_required"):
        model.model_validate(missing_abstention)
    duplicate = compact("summary", ["e0123456789ab"])
    duplicate["claims"] *= 2
    wire.validate(duplicate)
    with pytest.raises(ValueError, match="duplicate_claim_id"):
        model.model_validate(duplicate)
    blank_claim = compact("summary", ["e0123456789ab"])
    blank_claim["claims"][0]["text"] = " "
    wire.validate(blank_claim)
    with pytest.raises(ValueError, match="invalid_claim_text"):
        model.model_validate(blank_claim)


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
@pytest.mark.parametrize("handles", [["e0123456789ab"], ["e0123456789ab", "e123456789abc", "e23456789abc0"]])
def test_selected_catalog_closes_exact_wire_and_local_handle_enum(kind, handles):
    model = draft_schema(kind, handles)
    wire = transform_schema(model)
    validator = Draft202012Validator(wire)
    claim_name = wire["properties"]["claims"]["items"]["$ref"].rsplit("/", 1)[-1]
    claim_schema = wire["$defs"][claim_name]
    assert "handles" not in claim_schema["properties"]
    assert "evidence_handle" in claim_schema["required"]
    enum_name = claim_schema["properties"]["evidence_handle"]["$ref"].rsplit("/", 1)[-1]
    assert wire["$defs"][enum_name]["type"] == "string"
    assert wire["$defs"][enum_name]["enum"] == sorted(handles)
    for handle in handles:
        data = compact(kind, [handle])
        assert model.model_validate(data).claims[0].evidence_handle == handle
        validator.validate(data)
    # Catalog order and repeated factory calls have the same complete identity.
    assert model.model_json_schema() == draft_schema(kind, list(reversed(handles))).model_json_schema()
    assert wire == transform_schema(draft_schema(kind, handles))
    assert wire != transform_schema(draft_schema(kind, handles + ["e999999999999"]))


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
@pytest.mark.parametrize("bad", [None, "", "unknown", 1, ["e0123456789ab"],
                                 ["e0123456789ab", "e123456789abc"],
                                 "e0123456789ab,e123456789abc"])
def test_unknown_array_multiple_and_missing_handles_fail_both_contracts(kind, bad):
    model = draft_schema(kind, ["e0123456789ab", "e123456789abc"])
    data = compact(kind, ["e0123456789ab"])
    data["claims"][0]["evidence_handle"] = bad
    with pytest.raises(ValueError):
        model.model_validate(data)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(data))
    del data["claims"][0]["evidence_handle"]
    with pytest.raises(ValueError):
        model.model_validate(data)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(data))


@pytest.mark.parametrize("kind", ["summary", "deep_dive"])
@pytest.mark.parametrize("old", [["e0123456789ab"], ["e0123456789ab", "e123456789abc"]])
def test_old_handles_field_is_forbidden_even_with_a_valid_single_handle(kind, old):
    model = draft_schema(kind, ["e0123456789ab", "e123456789abc"])
    data = compact(kind, ["e0123456789ab"])
    data["claims"][0]["handles"] = old
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        model.model_validate(data)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(data))
    del data["claims"][0]["evidence_handle"]
    with pytest.raises(ValueError):
        model.model_validate(data)
    assert list(Draft202012Validator(transform_schema(model)).iter_errors(data))


@pytest.mark.parametrize("kind,handles,error", [("invented", ["e1"], "invalid_draft_kind"),
    ("summary", [], "invalid_selected_handle_enum"),
    ("summary", [None], "invalid_selected_handle_enum"),
    ("summary", [" "], "invalid_selected_handle_enum"),
    ("summary", [f"e{i}" for i in range(201)], "invalid_selected_handle_enum")])
def test_factory_requires_a_bounded_explicit_selected_enum(kind, handles, error):
    with pytest.raises(ValueError, match=error):
        draft_schema(kind, handles)


def test_retained_v7_q03_stays_failed_and_nonadjacent_old_shape_is_rejected_not_repaired():
    raw = (FIXTURES / "sonnet55-v7-q03-nonadjacent-handles.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "a28ad104e0ce32ddd30eae1a4fed3c8a600e84eaa4c570fbfde374ae9dc9198d"
    retained = json.loads(raw)
    assert retained["original_state"] == "failed" and retained["result_accepted"] is False
    assert retained["human_labels"] is None and retained["reservation"]["unknown"] == "0"
    assert retained["checker_count_contacts"] == retained["checker_message_contacts"] == 0
    response = retained["draft_response"]
    assert response["stop_reason"] == "end_turn"
    assert response["usage"]["input_tokens"] == 5575 and response["usage"]["output_tokens"] == 361
    output = p.response_output(response, p.MODEL)
    assert len(output["claims"][1]["handles"]) == 2
    catalog = {row["handle"]: row for row in json.loads(retained["draft_body"]["messages"][0]["content"])["evidence"]}
    first, second = (catalog[h] for h in output["claims"][1]["handles"])
    assert first["group"] == second["group"] and first["end"] < second["start"]
    model = draft_schema("summary", tuple(catalog))
    with pytest.raises(ValueError):
        model.model_validate(output)
    errors = list(Draft202012Validator(transform_schema(model)).iter_errors(output))
    assert any(error.validator == "additionalProperties" for error in errors)
    # The exact historical output is never translated or promoted to a V8 draft.
