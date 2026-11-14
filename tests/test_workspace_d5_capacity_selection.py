"""Persisted-source qualification selection; no generation or authority is created.

Synthetic retained prose exercises exact provenance and finite selection bounds.
Receipt-only controls call the storage hook directly, never provider execution.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from src.workspace.admission import AdmissionError, GenerationAdmission
from src.workspace.assistance import AssistanceInput, AssistanceService
from src.workspace.assistance_contract import coherent_units
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_capacity_policy import ASSISTANCE_REVISION, POLICY
from src.workspace.d5_capacity_selection import build
from src.workspace.executor import ExecutorError, FakeExecutor
from src.workspace.material import extract_text
from tests import test_workspace_store as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc, workspace_pg = support.workspace_pg_proc, support.workspace_pg
pytestmark = pytest.mark.integration
OWNER = "capacity-selection-fixture"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


@pytest.fixture(autouse=True)
def preserve_rows(request, store):
    yield
    root = Path(os.environ.get("D5_TEST_EVIDENCE_DIR", "build/d5-v15-test-evidence"))
    root.mkdir(parents=True, exist_ok=True)
    names = (
        "workspace_works",
        "workspace_versions",
        "workspace_material",
        "workspace_projects",
        "workspace_generation_jobs",
        "workspace_spend_reservations",
        "workspace_budget_policies",
    )
    records = {}
    with store.pool.connection() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
            )
        }
        for name in names:
            if name in existing:
                records[name] = [
                    row[0]
                    for row in conn.execute(
                        sql.SQL("SELECT to_jsonb(t) FROM {} t").format(sql.Identifier(name))
                    )
                ]
    data = json.dumps(
        {
            "test": request.node.nodeid,
            "synthetic": True,
            "real_provider_contacts": 0,
            "real_count_contacts": 0,
            "live_ledger_writes": 0,
            "tables": records,
        },
        ensure_ascii=False,
        indent=2,
    ).encode()
    target = root / (request.node.name + "-" + uuid4().hex + ".json.gz")
    target.write_bytes(gzip.compress(data, mtime=0))
    target.with_suffix(".sha256").write_text(hashlib.sha256(target.read_bytes()).hexdigest() + "\n")


def retained(store, index=0, paragraphs=26):
    # Exactly1000 Unicode code points per paragraph and2000 per persisted span.
    # Each span contains two complete independently selectable <1600-char units.
    pieces = []
    for number in range(paragraphs):
        lead = f"Synthetic passage {index}/{number:02d} Café Δ 条件 retains its comparator, metric definition and conditions; "
        pieces.append(
            lead + ("controlled setting and measurement context; " * 40)[: 998 - len(lead)] + ".\n"
        )
    text = "".join(pieces)
    material = extract_text(
        text,
        work_id=f"arxiv:0000.{index:05d}",
        version_id=f"arxiv:0000.{index:05d}:v1",
        scope="excerpt",
    )
    support.ingest(
        store,
        work_id=material.work_id,
        version_id=material.version_id,
        source_record_id=material.work_id,
        abstract="Synthetic retained-source selection fixture.",
        content_hash=material.source_hash,
    )
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_material VALUES(%s,%s,%s,%s,%s)",
            (
                material.material_id,
                material.version_id,
                material.content_hash,
                material.scope,
                Jsonb(asdict(material)),
            ),
        )
    catalog = coherent_units([material], {span.span_id for span in material.spans})
    # Every other unit selects one exact passage in each distinct persisted span.
    units = {
        key: asdict(value) for number, (key, value) in enumerate(catalog.items()) if number % 2 == 0
    }
    assert len(text) == paragraphs * 1000
    assert len(units) == paragraphs // 2
    return material, units


def material_row(store, material):
    with store.pool.connection() as conn:
        return conn.execute(
            "SELECT to_jsonb(t) FROM workspace_material t WHERE material_id=%s",
            (material.material_id,),
        ).fetchone()[0]


def no_authority_or_paid_work(store):
    with store.pool.connection() as conn:
        for name in (
            "workspace_generation_jobs",
            "workspace_spend_reservations",
            "workspace_budget_policies",
            "workspace_d5_scopes",
        ):
            assert (
                conn.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(name))
                ).fetchone()[0]
                == 0
            )


@pytest.mark.parametrize("mode", ["learn", "research"])
def test_twelve_units_from_long_persisted_material_preserve_exact_selection_hashes_and_offsets(
    store, mode
):
    material, available = retained(store)
    units = dict(list(available.items())[:12])
    before = material_row(store, material)
    question = "Explain each retained passage while preserving all stated conditions."
    value = build(store, OWNER, "twelve-" + mode, mode, question, units)
    assert len(material.pages[0]) == 26000 and len(material.pages[0].encode()) > 16000
    assert value["schema_revision"] == ASSISTANCE_REVISION
    assert value["units"] == units and len(value["units"]) == 12
    assert value["selection"] == {
        "material_ids": [material.material_id],
        "span_ids": [ref["span_id"] for ref in units.values()],
    }
    assert value["assistance"]["unit_ids"] == list(units)
    assert value["assistance"]["span_ids"] == value["selection"]["span_ids"]
    assert len(value["selection"]["span_ids"]) == 12
    assert value["version_hashes"] == {material.version_id: material.source_hash}
    source = value["sources"][0]
    assert (
        source["content_hash"] == material.content_hash
        and source["source_hash"] == material.source_hash
    )
    assert (
        source["parser_revision"] == material.parser_revision
        and source["offset_basis"] == material.offset_basis
    )
    assert sum(len(span["text"].encode()) for span in source["spans"]) > 16000
    expected_spans = {span.span_id: asdict(span) for span in material.spans}
    assert source["spans"] == [expected_spans[key] for key in value["selection"]["span_ids"]]
    for reference in units.values():
        assert material.pages[0][reference["start"] : reference["end"]] == reference["quote"]
        assert reference["source_hash"] == material.source_hash
        assert reference["parser_revision"] == material.parser_revision
        assert reference["material_id"] == material.material_id
    assert material_row(store, material) == before
    if mode == "research":
        assert value["project_context"]["question"] == question
        assert value["project_context"]["id"] == value["assistance"]["project_id"]
    else:
        assert value["project_context"] is None
    no_authority_or_paid_work(store)


def test_legacy_preview_keeps_eight_units_eight_spans_and_16000_source_byte_limits(store):
    material, available = retained(store)
    selected = dict(list(available.items())[:8])
    schema = AssistanceInput.model_json_schema()["properties"]
    assert schema["span_ids"]["maxItems"] == schema["unit_ids"]["maxItems"] == 8
    assert schema["material_ids"]["maxItems"] == 3 and schema["follow_up"]["maxLength"] == 1000
    arguments = dict(
        mode="learn",
        work_id=material.work_id,
        version_id=material.version_id,
        material_ids=(material.material_id,),
        span_ids=tuple(ref["span_id"] for ref in selected.values()),
        unit_ids=tuple(selected),
        follow_up="Explain the selected passages.",
        task_context=None,
    )
    selection = AssistanceInput(**arguments)
    with pytest.raises(ExecutorError, match="^source_selection_too_large_choose_spans$"):
        AssistanceService(store).preview(OWNER, selection)
    limits = (
        FakeExecutor(store)
        .preview(OWNER, "deep_dive", (material.material_id,), span_ids=(material.spans[0].span_id,))
        .limits
    )
    assert limits.max_spans == 8 and limits.max_source_bytes == 16000
    with pytest.raises(ValidationError):
        AssistanceInput(**{**arguments, "unit_ids": tuple(available)[:9]})
    with pytest.raises(ValidationError):
        AssistanceInput(
            **{
                **arguments,
                "span_ids": tuple(ref["span_id"] for ref in list(available.values())[:9]),
            }
        )
    no_authority_or_paid_work(store)


def test_thirteen_units_are_refused_before_creating_work_or_authority(store):
    _, units = retained(store)
    assert len(units) == 13
    with pytest.raises(AdmissionError, match="^capacity_selected_unit_limit$"):
        build(store, OWNER, "thirteen", "learn", "Explain the retained passages.", units)
    no_authority_or_paid_work(store)


def test_four_materials_are_refused_before_creating_work_or_authority(store):
    units = {}
    for index in range(4):
        _, available = retained(store, index=index, paragraphs=2)
        units.update(available)
    assert len(units) == 4
    with pytest.raises(AdmissionError, match="^capacity_material_limit$"):
        build(
            store,
            OWNER,
            "four-materials",
            "research",
            "Compare the retained passages.",
            units,
            intent="comparison",
        )
    no_authority_or_paid_work(store)


@pytest.mark.parametrize("mutation", ["quote", "offset", "source_hash", "handle"])
def test_changed_unit_cannot_reuse_a_persisted_reference(store, mutation):
    material, available = retained(store)
    units = dict(list(available.items())[:12])
    before = material_row(store, material)
    units = deepcopy(units)
    key = next(iter(units))
    if mutation == "quote":
        units[key]["quote"] += " Invented qualification."
    elif mutation == "offset":
        units[key]["start"] += 1
    elif mutation == "source_hash":
        units[key]["source_hash"] = "sha256:" + "0" * 64
    else:
        units["not-a-persisted-unit"] = units.pop(key)
    with pytest.raises(AdmissionError, match="^d5_selected_evidence_drift$"):
        build(store, OWNER, "mutated-" + mutation, "learn", "Explain the retained passages.", units)
    assert material_row(store, material) == before
    no_authority_or_paid_work(store)


@pytest.mark.parametrize("question", ["", " \n\t "])
def test_blank_question_is_refused_without_authority_or_work(store, question):
    _, available = retained(store)
    units = dict(list(available.items())[:12])
    with pytest.raises(AdmissionError, match="^request_question_required$"):
        build(store, OWNER, "blank", "research", question, units)
    no_authority_or_paid_work(store)


@pytest.mark.parametrize(
    "body",
    [
        b' {"preserved":"caf\\u00e9","order":[2,1]}\r\n',
        b"\xff\x80\x00 complete received error body\r\n",
        b'{"echo":"fixture-redaction-token"}',
    ],
)
def test_complete_http_receipt_preserves_received_bytes_after_parsed_response_replaces_summary(
    store, body
):
    # Storage-hook unit control backed by real PG. A deliberately minimal row
    # grants no execution; constructor, HTTP transport and admission are unused.
    job = "synthetic-receipt-only"
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_generation_jobs VALUES(%s,%s,'no-authority','running','unused',%s)",
            (
                job,
                OWNER,
                Jsonb(
                    {"adapter": {"contacts": [{"state": "dispatching", "endpoint": "messages"}]}}
                ),
            ),
        )
    adapter = object.__new__(D5Adapter)
    adapter.store, adapter.owner, adapter.control = store, OWNER, GenerationAdmission(store)
    adapter.inputs = SimpleNamespace(settings={"d5_capacity_policy": deepcopy(POLICY)})
    adapter.api_key = "fixture-redaction-token"
    adapter._complete_http_body(job, 0, 400, body)
    with store.pool.connection() as conn:
        contact = conn.execute(
            "SELECT data->'adapter'->'contacts'->0 FROM workspace_generation_jobs WHERE id=%s",
            (job,),
        ).fetchone()[0]
    receipt = deepcopy(contact["http_body_receipt"])
    expected = body.replace(b"fixture-redaction-token", b"[credential redacted]")
    assert gzip.decompress(base64.b64decode(receipt["body_gzip_base64"], validate=True)) == expected
    assert (
        receipt["received_bytes"] == len(body)
        and receipt["received_sha256"] == hashlib.sha256(body).hexdigest()
    )
    assert receipt["complete_body"] is True and receipt["usage_validated"] is False
    assert receipt["credential_redacted"] is (expected != body)
    assert receipt["http_status"] == 400
    adapter._record(job, 0, {"type": "parsed-response-replacement", "usage_validated": False})
    with store.pool.connection() as conn:
        updated = conn.execute(
            "SELECT data->'adapter'->'contacts'->0 FROM workspace_generation_jobs WHERE id=%s",
            (job,),
        ).fetchone()[0]
        assert conn.execute("SELECT count(*) FROM workspace_spend_reservations").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
    assert updated["http_body_receipt"] == receipt
    assert updated["response"] == {"type": "parsed-response-replacement", "usage_validated": False}


def test_research_question_is_trimmed_once_for_all_sealed_and_persisted_fields(store):
    from src.workspace.context_store import WorkspaceContext

    _, available = retained(store)
    units = dict(list(available.items())[:12])
    question = " \n\tExplain the retained setting and preserve the comparator. \t "
    expected = question.strip()
    value = build(store, OWNER, "trimmed-research", "research", question, units)
    assert value["assistance"]["follow_up"] == expected
    assert value["project_context"]["question"] == expected
    with store.pool.connection() as conn:
        project = WorkspaceContext._project(conn, OWNER, value["project_context"]["id"])
    assert project["data"]["question"] == expected
    no_authority_or_paid_work(store)


def test_complete_http_receipt_is_idempotent_and_rejects_changed_bytes_atomically(store):
    job = "synthetic-idempotent-receipt-only"
    with store.pool.connection() as conn:
        conn.execute(
            "INSERT INTO workspace_generation_jobs VALUES(%s,%s,'no-authority','running','unused',%s)",
            (
                job,
                OWNER,
                Jsonb(
                    {"adapter": {"contacts": [{"state": "dispatching", "endpoint": "messages"}]}}
                ),
            ),
        )
    adapter = object.__new__(D5Adapter)
    adapter.store, adapter.owner, adapter.control = store, OWNER, GenerationAdmission(store)
    adapter.inputs = SimpleNamespace(settings={"d5_capacity_policy": deepcopy(POLICY)})
    adapter.api_key = "fixture-redaction-token"
    original = b'{"type":"error","detail":"original immutable body"}\n'
    adapter._complete_http_body(job, 0, 400, original)

    def row():
        with store.pool.connection() as conn:
            return conn.execute(
                "SELECT data FROM workspace_generation_jobs WHERE id=%s", (job,)
            ).fetchone()[0]

    before = row()
    adapter._complete_http_body(job, 0, 400, original)
    assert row() == before
    with pytest.raises(AdmissionError, match="^d5_complete_body_receipt_immutable$"):
        adapter._complete_http_body(job, 0, 400, b'{"type":"error","detail":"different bytes"}')
    assert row() == before
    contact = row()["adapter"]["contacts"][0]
    assert contact["response"]["raw_body"] == original.decode()
    assert (
        gzip.decompress(base64.b64decode(contact["http_body_receipt"]["body_gzip_base64"]))
        == original
    )
