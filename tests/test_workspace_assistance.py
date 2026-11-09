"""D5 real PostgreSQL and MockTransport checks; no live quality certification."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest
from psycopg.types.json import Jsonb

from src.workspace import assistance as a
from src.workspace import assistance_contract as c
from src.workspace import grounding as g
from src.workspace.context_schemas import ProjectData, ProjectWrite
from src.workspace.context_store import WorkspaceContext
from src.workspace.executor import FakeExecutor
from src.workspace.material import extract_text
from src.workspace.store import ConflictError, WorkspaceStore
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration
PID = "project-" + "d" * 32


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store, mode="learn"):
    item = support.ingest(
        store,
        abstract="Agents improve accuracy on the small benchmark. However, this requires external tools and does not establish general reasoning.",
    )
    if mode == "research":
        WorkspaceContext(store).write_project(
            "a",
            ProjectWrite(
                id=PID,
                revision=0,
                request_id="project",
                data=ProjectData(
                    title="Research example",
                    question="Which settings support the reported improvements?",
                ),
            ),
        )
    service = a.AssistanceService(store)
    units = service.catalog("a", item["work_id"], item["version_id"])["units"]
    value = a.AssistanceInput(
        task_context=None,  # This helper pins the historical response contract.
        mode=mode,
        work_id=item["work_id"],
        version_id=item["version_id"],
        material_ids=tuple(dict.fromkeys(u["reference"]["material_id"] for u in units)),
        span_ids=tuple(dict.fromkeys(u["reference"]["span_id"] for u in units)),
        unit_ids=tuple(u["id"] for u in units),
        project_id=PID if mode == "research" else None,
        project_revision=1 if mode == "research" else None,
    )
    return service, value


def queue(service, value, key="one"):
    preview = service.preview("a", value)
    return service.submit(
        "a", a.SubmitWrite(input=value, request_id=key, expected_digest=preview.request_digest)
    )


def wire_payload(refs, **extra):
    return {
        "claims": [
            {
                "claim_id": "c1",
                "text": "A proposed claim",
                "handles": list(refs),
                "required_scope": "abstract",
            }
        ],
        "background_claims": [],
        "assumption_claims": [],
        "limitation_claims": [],
        "comparison_claims": [],
        "comparison_basis": [],
        "gaps": ["source_scope"],
        "questions": ["What would falsify this?"],
        "proposal": "",
        "abstention": None,
        **extra,
    }


@pytest.mark.parametrize("mode", ["learn", "research"])
def test_real_pipeline_sealed_wire_usage_restart_and_no_paid_policies(store, mode):
    service, value = setup(store, mode)
    preview = service.preview("a", value)
    assert preview.request["capacity"]["max_calls"] == 4
    assert preview.request["capacity"]["provider_token_counts"] is None
    job = queue(service, value)
    assert job.state == "queued" and not service.get("a", job.id)["wire_records"]
    assert FakeExecutor(store).list("a") == []
    with pytest.raises(ValueError, match="versioned_assistance"):
        FakeExecutor(store).advance("a", job.id)
    first = service.action("a", job.id, "advance")
    assert first["state"] == "checking", first
    restarted = a.AssistanceService(WorkspaceStore(store.pool))
    result = restarted.action("a", job.id, "advance")
    assert result["state"] == "ready", result
    assert result["simulated"] and result["human_review"] is None
    assert (
        not result["quality"]["factual_acceptance"] and not result["quality"]["checker_qualified"]
    )
    assert result["assistance_output"]["claims"]
    assert (
        result["usage"]["workflow"]["input_tokens"] > 0
        and result["usage"]["checker"]["input_tokens"] > 0
    )
    assert result["usage"]["actual_usd"] == "0.000000"
    for record in result["wire_records"]:
        assert record["digest"] == c.digest(record["request"])
        output = json.loads(record["response"]["content"][0]["text"])
        __import__("jsonschema").Draft202012Validator(
            record["request"]["output_config"]["format"]["schema"]
        ).validate(output)
    assert (
        "units"
        not in json.loads(result["wire_records"][1]["request"]["messages"][0]["content"])[
            "sealed_request"
        ]
    )
    assert restarted.get("a", job.id) == result
    assert restarted.jobs("a", value.work_id, value.version_id)[0]["id"] == job.id
    assert restarted.jobs("b", value.work_id, value.version_id) == []
    with pytest.raises(ValueError):
        restarted.get("b", job.id)
    assert queue(service, value, "cached").cached
    with store.pool.connection() as conn:
        for table in (
            "workspace_budget_policies",
            "workspace_generation_jobs",
            "workspace_spend_reservations",
        ):
            assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0


def test_multi_source_and_nonadjacent_evidence_stays_separate_with_qualifications():
    text = (
        "A method improved only on one small benchmark. "
        + "Other context. " * 110
        + "The second result contradicted the first."
    )
    material = extract_text(text, work_id="paper", version_id="paper:v1", scope="abstract")
    catalog = c.coherent_units([material], {s.span_id for s in material.spans})
    ids = list(catalog)
    assert len(ids) >= 2 and "only" in catalog[ids[0]].quote
    payload = wire_payload([ids[0], ids[1]])
    _, claims = c.resolve_draft(payload, catalog, [material])
    assert len(claims[0].evidence) == 2
    assert all(ref.quote == text[ref.start : ref.end] for ref in claims[0].evidence)
    report = g.validate_claims(claims, [material])
    assert report.supported == 0 and report.support_ratio is None


@pytest.mark.parametrize(
    "case", ["wrong_version", "quote", "offset", "material_hash", "unselected", "scope"]
)
def test_exact_evidence_negative_cases(case):
    material = extract_text(
        "Café 🧪 repeated. Café 🧪 repeated. Only a synthetic setting was tested.",
        work_id="unicode",
        version_id="unicode:v1",
        scope="abstract",
    )
    catalog = c.coherent_units([material], {material.spans[0].span_id})
    key, ref = next(iter(catalog.items()))
    changes = {
        "wrong_version": {"version_id": "unicode:v2"},
        "quote": {"quote": "fabricated"},
        "offset": {"start": ref.start + 1},
    }
    payload = wire_payload([key])
    if case in changes:
        catalog[key] = replace(ref, **changes[case])
    if case == "material_hash":
        material = replace(material, pages=("Changed text",))
    if case == "unselected":
        payload["claims"][0]["handles"] = ["u-unknown"]
    if case == "scope":
        payload["claims"][0]["required_scope"] = "full_text"
        _, claims = c.resolve_draft(payload, catalog, [material])
        report = g.validate_claims(claims, [material])
        assert not report.assessments[0].scope_compatible and report.supported == 0
    else:
        with pytest.raises(ValueError):
            c.resolve_draft(payload, catalog, [material])


@pytest.mark.parametrize(
    "case",
    [
        "unsupported_meaning",
        "missing_qualification",
        "misleading_comparison",
        "contradiction",
        "insufficient",
    ],
)
def test_identity_never_becomes_semantic_pass(case):
    material = extract_text(
        "Accuracy improved only with the external tool. It failed without the tool.",
        work_id="counter",
        version_id="counter:v1",
        scope="abstract",
    )
    catalog = c.coherent_units([material], {material.spans[0].span_id})
    value = wire_payload(list(catalog))
    value["claims"][0]["text"] = {
        "unsupported_meaning": "The tool understands all tasks.",
        "missing_qualification": "Accuracy improved in every setting.",
        "misleading_comparison": "It outperformed another method.",
        "contradiction": "It succeeded without the tool.",
        "insufficient": "It is safe in production.",
    }[case]
    _, claims = c.resolve_draft(value, catalog, [material])
    report = g.validate_claims(claims, [material])
    assert report.assessments[0].identity_resolved and report.supported == 0
    # Proposed synthetic support review, not an independent human gold label.
    check = g.SupportCheck(
        "c1",
        g.claim_input_digest(claims[0], [material]),
        g.SupportDecision.UNSUPPORTED,
        "proposed-fixture-review",
        "d5-v1",
        case,
    )
    assert g.validate_claims(claims, [material], [check]).unsupported == 1


@pytest.mark.parametrize("case", ["truncated", "json", "schema", "model", "unselected"])
def test_wire_failures_stop_before_checker_and_keep_raw_response(store, case):
    service, value = setup(store)
    job = queue(service, value)

    def handler(request):
        response = a.LocalAssistanceTransport.fixture(request)
        raw = response.json()
        if case == "truncated":
            raw["stop_reason"] = "max_tokens"
        if case == "json":
            raw["content"][0]["text"] = '{"claims":'
        if case == "schema":
            raw["content"][0]["text"] = "{}"
        if case == "model":
            raw["model"] = "other"
        if case == "unselected":
            output = json.loads(raw["content"][0]["text"])
            output["claims"][0]["handles"] = ["missing"]
            raw["content"][0]["text"] = json.dumps(output)
        return httpx.Response(200, json=raw)

    adapter = a.LocalAssistanceTransport(store, "a", job.id, handler)
    result = service.executor.advance("a", job.id, provider=adapter)
    assert result.state == "failed" and result.result is None
    saved = service.get("a", job.id)
    assert len(saved["wire_records"]) == 1 and saved["wire_records"][0]["response"]
    assert not saved["assistance_output"]


def test_project_question_revision_sealed_and_changes_stop_dispatch(store):
    service, value = setup(store, "research")
    preview = service.preview("a", value)
    assert preview.request["project_context"]["revision"] == 1
    assert "notes" not in preview.request["project_context"]
    job = queue(service, value)
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_projects SET revision=2 WHERE owner='a'")
    with pytest.raises(ConflictError):
        service.preview("a", value)
    result = service.action("a", job.id, "advance")
    assert result["state"] == "stale" and not result["wire_records"]


def test_no_transport_or_submission_without_offline_sentinel(store, monkeypatch):
    service, value = setup(store)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "real-key-must-not-be-used")
    with pytest.raises(ValueError, match="sentinel"):
        queue(service, value)
    with pytest.raises(ValueError, match="sentinel"):
        a.LocalAssistanceTransport(store, "a", "unused")
    monkeypatch.delenv("WORKSPACE_D5_OFFLINE")
    with pytest.raises(ValueError, match="disabled"):
        service.preview("a", value)


def test_cancel_recovery_and_budget_refusal_never_replay(store):
    service, value = setup(store)
    cancelled = queue(service, value)
    assert service.action("a", cancelled.id, "cancel")["state"] == "cancelled"
    assert not service.action("a", cancelled.id, "advance")["wire_records"]
    job = queue(service, value, "lost")
    past = datetime.fromisoformat(store.cutoff()) - timedelta(minutes=5)
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_fake_generation_jobs SET lease_until=%s,lease_owner='lost',state='drafting',data=%s WHERE id=%s",
            (
                past,
                Jsonb(
                    {
                        "next_phase": "draft",
                        "repairs": 0,
                        "steps": [
                            {
                                "ordinal": 0,
                                "phase": "draft",
                                "state": "running",
                                "request_digest": "lost",
                                "request": {},
                                "input_tokens": 123,
                                "unknown_recorded": False,
                                "output_tokens": 0,
                            }
                        ],
                    }
                ),
                job.id,
            ),
        )
    assert service.action("a", job.id, "recover")["state"] == "interrupted"
    assert not service.action("a", job.id, "advance")["wire_records"]
    job = queue(service, value, "budget")
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_fake_generation_reservations SET max_input_tokens=1 WHERE job_id=%s",
            (job.id,),
        )
    assert service.action("a", job.id, "advance")["state"] == "budget_stopped"
    assert not service.get("a", job.id)["wire_records"]


def test_bounded_repair_recheck_failure_remains_unaccepted(store):
    service, value = setup(store)
    job = queue(service, value)

    def handler(request):
        response = a.LocalAssistanceTransport.fixture(request)
        raw = response.json()
        output = json.loads(raw["content"][0]["text"])
        if "checks" in output:
            for check in output["checks"]:
                check["decision"] = "unsupported"
        raw["content"][0]["text"] = json.dumps(output)
        return httpx.Response(200, json=raw)

    adapter = a.LocalAssistanceTransport(store, "a", job.id, handler)
    states = [service.executor.advance("a", job.id, provider=adapter).state for _ in range(4)]
    assert states == ["checking", "repairing", "checking", "failed"]
    result = service.get("a", job.id)
    assert (
        result["usage"]["used_calls"] == 4
        and not result["result"]
        and not result["assistance_output"]
    )
    assert [r["phase"] for r in result["wire_records"]] == ["draft", "check", "repair", "check"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("claims", []),
        ("comparison_basis", ["absent"]),
        ("assumptions", [" "]),
        ("gaps", ["x" * 181]),
    ],
)
def test_bounded_response_refuses_missing_claims_and_invalid_sections(field, value):
    with pytest.raises(ValueError):
        c.response_model(["u1"]).model_validate(wire_payload(["u1"], **{field: value}))


def test_catalog_bounds_abstention_and_coherent_edge_handling():
    for handles in ([], [str(i) for i in range(9)]):
        with pytest.raises(ValueError):
            c.response_model(handles)
    long = extract_text(
        "x" * 1700 + ". Short complete conclusion.",
        work_id="long",
        version_id="long:v1",
        scope="abstract",
    )
    units = c.coherent_units([long], {s.span_id for s in long.spans})
    assert all(len(r.quote) <= c.MAX_UNIT_CHARS for r in units.values())
    for scope, text in [("metadata", "Metadata only."), ("abstract", "")]:
        material = extract_text(text, work_id="empty", version_id="empty:v1", scope=scope)
        with pytest.raises(ValueError, match="unavailable"):
            c.coherent_units([material], {s.span_id for s in material.spans})
    payload = wire_payload([], claims=[], abstention="Insufficient evidence.")
    assert c.response_model(["u1"]).model_validate(payload).abstention
    with pytest.raises(ValueError, match="capacity"):
        a.capacity({"units": {"u": "x" * 20000}})


@pytest.mark.parametrize(
    "case",
    [
        "duplicate",
        "missing",
        "version",
        "learn_project",
        "research_missing",
        "wrong_materials",
        "bad_parent",
    ],
)
def test_preview_refuses_drift_and_unowned_context(store, case):
    service, value = setup(store)
    changes = {
        "duplicate": {"unit_ids": value.unit_ids * 2},
        "missing": {"unit_ids": ("missing",)},
        "version": {"version_id": "wrong:v1"},
        "learn_project": {"project_id": PID},
        "research_missing": {"mode": "research"},
        "wrong_materials": {"material_ids": ("missing",)},
        "bad_parent": {"parent_job": "fake-" + "a" * 40},
    }[case]
    with pytest.raises(ValueError):
        service.preview("a", value.model_copy(update=changes))
    assert service.jobs("a", value.work_id, value.version_id) == []


@pytest.mark.parametrize("body", ["not-json", "[]", "null"])
def test_known_completed_invalid_envelope_preserves_receipt_without_unknown_hold(store, body):
    service, value = setup(store)
    job = queue(service, value)
    adapter = a.LocalAssistanceTransport(
        store, "a", job.id, lambda request: httpx.Response(200, text=body)
    )
    result = service.executor.advance("a", job.id, provider=adapter)
    assert result.state == "failed" and not result.result
    saved = service.get("a", job.id)
    assert saved["wire_records"][0]["response"]["invalid_json_body"] == body
    assert saved["usage"]["workflow"]["output_tokens"] > 0
    assert saved["usage"]["unknown"]["output_tokens"] == 0


@pytest.mark.parametrize("prose", ["abstain", "unscored_factual_content"])
def test_substantive_unscored_prose_cannot_pass_by_hiding_outside_claims(store, prose):
    service, value = setup(store)
    job = queue(service, value)
    service.action("a", job.id, "advance")

    def handler(request):
        raw = a.LocalAssistanceTransport.fixture(request).json()
        content = json.loads(raw["content"][0]["text"])
        content["prose_review"] = prose
        raw["content"][0]["text"] = json.dumps(content)
        return httpx.Response(200, json=raw)

    result = service.executor.advance(
        "a", job.id, provider=a.LocalAssistanceTransport(store, "a", job.id, handler)
    )
    assert result.state == "failed" and not result.result
    assert not service.get("a", job.id)["quality"]["factual_acceptance"]


def test_current_candidate_wire_matches_dispatch_and_completed_source_drift_is_visible(store):
    service, value = setup(store)
    preview = service.preview("a", value)
    job = queue(service, value)
    service.action("a", job.id, "advance")
    result = service.action("a", job.id, "advance")
    assert preview.request["candidate_initial_wire"] == result["wire_records"][0]["request"]
    content = json.loads(result["wire_records"][0]["request"]["messages"][0]["content"])
    assert set(content["sealed_request"]["assistance"]) == {
        "mode",
        "depth",
        "background",
        "direction",
        "follow_up",
    }
    assert "origin" not in content["sealed_request"]["assistance"]
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_versions SET data=jsonb_set(data,'{content_hash}','\"changed\"') WHERE version_id=%s",
            (value.version_id,),
        )
    changed = service.get("a", job.id)
    assert (
        changed["state"] == "stale"
        and changed["result"] is None
        and changed["assistance_output"] is None
    )
    assert changed["wire_records"] == result["wire_records"]
    with pytest.raises(ValueError, match="invalid_assistance_action"):
        service.action("a", job.id, "approve")


from tests import test_workspace_api as api_support  # noqa: E402

client = api_support.client


@pytest.mark.asyncio
async def test_api_routes_require_explicit_submission_and_preserve_owner_boundaries(client, store):
    service, value = setup(store)
    catalog = await client.get(
        "/workspace/assistance/catalog",
        params={"work_id": value.work_id, "version_id": value.version_id},
    )
    assert catalog.status_code == 200 and catalog.json()["units"]
    assert (
        await client.get(
            "/workspace/assistance/jobs",
            params={"work_id": value.work_id, "version_id": value.version_id},
        )
    ).json() == []
    preview = await client.post(
        "/workspace/assistance/preview", json={"input": value.model_dump(mode="json")}
    )
    assert preview.status_code == 200
    submitted = await client.post(
        "/workspace/assistance/jobs",
        json={
            "input": value.model_dump(mode="json"),
            "request_id": "api",
            "expected_digest": preview.json()["request_digest"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    jid = submitted.json()["id"]
    assert not submitted.json()["wire_records"]
    assert (
        await client.get("/workspace/assistance/jobs/" + jid, headers={"X-API-Key": "key-b"})
    ).status_code == 422
    for suffix in ("advance", "advance", "recover", "cancel"):
        assert (
            await client.post("/workspace/assistance/jobs/" + jid + "/" + suffix)
        ).status_code == 200
    assert (await client.get("/workspace/assistance/jobs/" + jid)).json()["state"] == "ready"
    assert (
        await client.post("/workspace/assistance/preview", json={"input": {}})
    ).status_code == 422


@pytest.mark.parametrize("start,end", [(5, 82), (5, 12), (0, 52), (0, 10), (0, 1)])
def test_coherent_units_omit_clipped_sentences_without_expanding_selection(start, end):
    text = "A partial opening sentence. Complete retained sentence. Another closing qualification."
    material = extract_text(text, work_id="edge", version_id="edge:v1", scope="abstract")
    span = replace(material.spans[0], start=start, end=end, text=text[start:end])
    material = replace(material, spans=(span,))
    try:
        units = c.coherent_units([material], {span.span_id})
    except ValueError as error:
        assert "unavailable" in str(error)
    else:
        assert all(start <= ref.start < ref.end <= end for ref in units.values())
        assert all(ref.quote == text[ref.start : ref.end] for ref in units.values())
        assert all(not ref.quote.startswith("tial") for ref in units.values())


def test_multiple_sources_required_for_comparison_and_mutated_spans_refuse():
    material = extract_text(
        "Only a small benchmark was tested.\n\n No broad result follows. ",
        work_id="a",
        version_id="a:v1",
        scope="abstract",
    )
    catalog = c.coherent_units([material], {material.spans[0].span_id})
    handle = next(iter(catalog))
    claim = wire_payload([handle])["claims"][0]
    comparison = wire_payload(
        [handle],
        claims=[claim, {**claim, "claim_id": "c2"}],
        comparison_claims=["c1", "c2"],
        comparison_basis=["c1", "c2"],
    )
    with pytest.raises(ValueError, match="two_separately"):
        c.resolve_draft(comparison, catalog, [material])
    other = extract_text(
        "The method failed on a different benchmark.",
        work_id="b",
        version_id="b:v1",
        scope="abstract",
    )
    both = c.coherent_units([material, other], {material.spans[0].span_id, other.spans[0].span_id})
    comparison["claims"][1]["handles"] = [
        next(key for key, ref in both.items() if ref.work_id == "b")
    ]
    _, claims = c.resolve_draft(comparison, both, [material, other])
    assert len(claims) == 2 and len({r.work_id for claim in claims for r in claim.evidence}) == 2
    corrupt = replace(
        material, spans=(replace(material.spans[0], text="x" * len(material.spans[0].text)),)
    )
    with pytest.raises(ValueError, match="provenance|content_drift"):
        c.coherent_units([corrupt], {corrupt.spans[0].span_id})
    broken = {handle: replace(catalog[handle], quote="Fabricated quote")}
    with pytest.raises(ValueError, match="identity|quote_not_in_retained_span"):
        c.resolve_draft(wire_payload([handle]), broken, [material])
    for changes in (
        {"comparison": "No declared basis"},
        {"claims": [{**claim, "text": " "}]},
        {"claims": [{**claim, "handles": [handle, handle]}]},
    ):
        with pytest.raises(ValueError):
            c.response_model([handle]).model_validate(wire_payload([handle], **changes))


def test_project_catalog_and_follow_up_are_owned_versioned_and_not_history_context(store):
    service, value = setup(store, "research")
    catalog = service.catalog("a", value.work_id, value.version_id, PID)
    assert catalog["units"]
    with pytest.raises(ValueError):
        service.catalog("b", value.work_id, value.version_id, PID)
    job = queue(service, value)
    service.action("a", job.id, "advance")
    service.action("a", job.id, "advance")
    follow = value.model_copy(update={"parent_job": job.id, "follow_up": "What is missing?"})
    assert service.preview("a", follow).request["assistance"]["parent_job"] == job.id
    with pytest.raises(ValueError, match="follow_up"):
        service.preview(
            "a",
            value.model_copy(
                update={
                    "parent_job": queue(
                        service,
                        value.model_copy(update={"follow_up": "Different queued task"}),
                        "pending-follow",
                    ).id
                }
            ),
        )


def test_two_source_pipeline_survives_shared_executor_canonical_selection_order(store):
    service, value = setup(store, "research")
    item = support.ingest(
        store,
        work_id="arxiv:0000.00002",
        version_id="arxiv:0000.00002:v1",
        source_record_id="0000.00002",
        abstract="A second method failed under a different evaluation setting.",
    )
    units = service.catalog("a", item["work_id"], item["version_id"])["units"]
    other = units[0]
    materials = tuple(
        sorted((*value.material_ids, other["reference"]["material_id"]), reverse=True)
    )
    spans = tuple(sorted((*value.span_ids, other["reference"]["span_id"]), reverse=True))
    value = value.model_copy(
        update={
            "material_ids": materials,
            "span_ids": spans,
            "unit_ids": (*value.unit_ids, other["id"]),
        }
    )
    job = queue(service, value)
    assert service.action("a", job.id, "advance")["state"] == "checking"
    result = service.action("a", job.id, "advance")
    assert result["state"] == "ready"
    assert len(result["assistance_output"]["claims"]) == 2
    assert result["assistance_output"]["comparison_basis"] == ["c1", "c2"]
    assert len({ref["work_id"] for ref in result["request"]["units"].values()}) == 2


def test_wire_capacity_contradiction_refuses_before_inflight_or_transport(store):
    service, value = setup(store)
    job = queue(service, value)
    with store.pool.connection() as conn:
        row = list(service.executor._row(conn, "a", job.id))
        materials = service.executor._sources(conn, "a", value.material_ids)
        row[5]["capacity"]["stage_input_bytes_max"]["draft"] = 1
        with pytest.raises(ValueError, match="sealed_stage_capacity"):
            service.executor._stage(tuple(row), materials)
    saved = service.get("a", job.id)
    assert saved["state"] == "queued" and saved["usage"]["used_calls"] == 0
    assert saved["usage"]["unknown"] == {"input_tokens": 0, "output_tokens": 0}
    assert not saved["wire_records"]


def test_producer_code_binding_preserves_old_output_but_refuses_queued_drift(store, monkeypatch):
    service, value = setup(store)
    job = queue(service, value)
    assert job.request["producer"]["code"] == a.producer_binding()
    service.action("a", job.id, "advance")
    service.action("a", job.id, "advance")
    pending_value = value.model_copy(update={"follow_up": "New explicit task"})
    pending = queue(service, pending_value, "pending-producer")
    monkeypatch.setattr(
        a, "producer_binding", lambda: {"workspace/assistance.py": "sha256:new-producer"}
    )
    changed = service.action("a", pending.id, "advance")
    assert changed["state"] == "stale" and not changed["wire_records"]
    old = service.get("a", job.id)
    assert old["result"] and old["request"]["producer"]["code"] != a.producer_binding()
    with pytest.raises(ValueError, match="producer_code_changed"):
        service.preview("a", value)
    monkeypatch.setattr(a, "_LOADED_PRODUCER", a.producer_binding())
    assert service.preview("a", value).request_digest != job.request_digest
