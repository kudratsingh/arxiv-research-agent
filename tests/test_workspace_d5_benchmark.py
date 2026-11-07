"""Frozen pipeline replay with synthetic public inputs and real Postgres.

These are software/adversarial fixtures, not a scientific or owner quality set.
"""

from __future__ import annotations

from contextlib import nullcontext, suppress
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import check_storage, read, run, write
from src.workspace.d5_evidence import assess, select
from src.workspace.d5_fixture import authorize_fixture, install, snapshot
from src.workspace.d5_freeze import compile_inputs, freeze, restore_input, verify
from src.workspace.d5_scoring import factual_gate, markdown
from src.workspace.material import extract_text
from src.workspace.qualification_budget import census
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_store import ingest

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def corpus(store):
    support.program(store)
    for index, work in enumerate(
        [
            "arxiv:2210.03629",
            "arxiv:2310.11511",
            "arxiv:2611.90001",
            "arxiv:2611.90002",
            "arxiv:2611.90003",
            "arxiv:2611.90004",
        ]
    ):
        ingest(
            store,
            work_id=work,
            version_id=work + ":v1",
            title=f"Synthetic memory retrieval agent evaluation control study {index}",
            abstract="Agents use retrieval and memory to evaluate claims with source verification. However, this method requires external tools and does not establish safe hardware deployment or general reasoning.",
        )
    profile = {
        "topics": ["study:17"],
        "custom_topics": ["retrieval", "agent", "memory"],
        "exclusions": [],
        "streams": ["core", "rocket-twin", "spatial"],
        "minutes": 15,
        "exploration": 0.15,
        "research_question": "Private question excluded from provider context",
    }
    with store.pool.connection() as conn:
        history = census(conn, "a")
        conn.execute("INSERT INTO workspace_profiles VALUES('profile',1,%s)", (Jsonb(profile),))
    packet = freeze(store, profile, history)
    packet["program_id"] = "evaluation"
    packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
    return packet


async def test_complete_frozen_system_replay_uses_real_ranker_admission_journal_and_report(
    store, monkeypatch, tmp_path
):
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    packet = corpus(store)
    verify(packet)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, packet)
    report = await run(store, packet, "all", offline=True)
    assert len(report["cases"]) == 10 and sum(c["completion"] for c in report["cases"]) == 10
    assert len([c for c in report["cases"] if c["pipeline"] == "end_to_end_system"]) == 8
    assert report["accounting"]["actual_new_provider_contacts"] == 0
    assert report["accounting"]["new_scope"]["messages"] <= 44
    assert report["accounting"]["new_scope"]["counts"] <= 48
    assert all(c["human_review"] is None and not c["accepted_result"] for c in report["cases"])
    assert "UNSCORED" in markdown(report)
    assert len(compile_inputs(packet)) == 18
    for entry in compile_inputs(packet).values():
        assert restore_input(entry["input"]).snapshot() == entry["input"]
    path = tmp_path / "packet.json.gz"
    write(path, packet)
    assert read(path) == packet
    with pytest.raises(AdmissionError):
        write(path, packet)
    # Stable retry identities only inspect completed work, no new contacts.
    before = report["accounting"]["new_scope"]
    again = await run(store, packet, "all", offline=True)
    assert again["accounting"]["new_scope"]["messages"] == before["messages"]
    # Exact upstream source mutation is refused, not replaced by a known answer.
    with store.pool.connection() as conn:
        conn.execute(
            "UPDATE workspace_versions SET data=jsonb_set(data,'{content_hash}',%s)",
            (Jsonb("changed"),),
        )
    with pytest.raises(AdmissionError, match="frozen_source"):
        check_storage(store, packet)


@pytest.mark.parametrize("provenance", [None, False])
async def test_bad_required_provenance_cannot_pass_even_with_sufficient_human_labels(provenance):
    assert factual_gate(provenance=provenance, human_support=True, human_omissions=True) == "FAIL"
    assert factual_gate(provenance=True, human_support=True, human_omissions=True) == "PASS"
    assert factual_gate(provenance=True, human_support=None, human_omissions=True) == "UNSCORED"
    assert factual_gate(provenance=True, human_support=False, human_omissions=True) == "FAIL"


async def test_freeze_and_fixture_boundaries_fail_closed(store, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    packet = corpus(store)
    with pytest.raises(AdmissionError):
        await run(store, packet, "A", offline=True)
    with pytest.raises(AdmissionError):
        install(store, {"tables": {}}, fixture=True)
    altered = {**packet, "approved": True}
    with pytest.raises(AdmissionError):
        verify(altered)
    altered = {**packet, "code": {}}
    altered["packet_digest"] = _digest({k: v for k, v in altered.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError, match="producer"):
        verify(altered)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, packet)
    with pytest.raises(AdmissionError, match="previous_stage"):
        await run(store, packet, "C", offline=True)
    path = tmp_path / "bad.json"
    path.write_text("[]")
    with pytest.raises(AdmissionError):
        read(path)
    from src.workspace.d5_benchmark import database

    for url in [
        "postgresql://remote:15488/workspace_d5_x",
        "postgresql://localhost:5432/owner",
        "postgresql://localhost:15488/owner",
    ]:
        with pytest.raises(AdmissionError):
            database(url)


@pytest.mark.parametrize("field", ["ranking", "evidence_selection", "question"])
async def test_rehashed_packet_cannot_replace_actual_discovery_with_reference_context(
    store, field, monkeypatch
):
    from copy import deepcopy

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    packet = corpus(store)
    changed = deepcopy(packet)
    case = changed["cases"][2]
    if field == "ranking":
        case["ranking"].reverse()
    elif field == "evidence_selection":
        case["evidence_selection"] = []
    else:
        case["question"] = "Post-hoc different question"
    changed["packet_digest"] = _digest({k: v for k, v in changed.items() if k != "packet_digest"})
    with pytest.raises(AdmissionError):
        verify(changed)


async def test_snapshot_excludes_policy_notes_and_private_works(store, monkeypatch):
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    corpus(store)
    captured = snapshot(store, store, "evaluation", "profile")
    assert (
        captured["profile"]["research_question"] == ""
        and captured["profile_authority"]["research_question_digest"]
    )
    assert (
        "workspace_entries" not in captured["tables"]
        and "workspace_budget_policies" not in captured["tables"]
    )
    with pytest.raises(AdmissionError):
        snapshot(store, store, "missing", "profile")
    with pytest.raises(AdmissionError):
        snapshot(store, store, "evaluation", "missing")
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_works SET visibility_owner='private'")
    with pytest.raises(AdmissionError, match="private_works"):
        snapshot(store, store, "evaluation", "profile")


async def test_cli_freeze_verify_report_operator_template_and_explicit_fixture_scope(
    store, monkeypatch, tmp_path, capsys
):
    from src.workspace import d5_benchmark as command
    from src.workspace import d5_operator as operator

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
    corpus(store)
    captured = snapshot(store, store, "evaluation", "profile")
    capture_path = tmp_path / "snapshot.json"
    write(capture_path, captured)
    packet_path = tmp_path / "packet.json.gz"
    monkeypatch.setattr(command, "database", lambda _: nullcontext(store.pool))
    monkeypatch.setattr(operator, "database", lambda _: nullcontext(store.pool))

    def invoke(module, *args):
        monkeypatch.setattr("sys.argv", [module.__name__, *map(str, args)])
        module.main()

    invoke(command, "freeze", "--packet", packet_path, "--snapshot", capture_path)
    packet = read(packet_path)
    invoke(command, "verify", "--packet", packet_path)
    receipt = tmp_path / "approval.json"
    invoke(operator, "template", "--packet", packet_path, "--receipt", receipt)
    assert read(receipt)["approved"] is False
    with pytest.raises(AdmissionError):
        invoke(operator, "record", "--packet", packet_path, "--receipt", receipt)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, packet)
    with store.pool.connection() as conn:
        recorded = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes"
        ).fetchone()[0]
    receipt2 = tmp_path / "fixture-approval.json"
    write(receipt2, recorded)
    invoke(operator, "record", "--packet", packet_path, "--receipt", receipt2)
    # Report mode is read-only and leaves unexecuted cases incomplete/unscored.
    invoke(command, "report", "--packet", packet_path, "--out", tmp_path / "report")
    report = read(tmp_path / "report/results.json")
    assert not any(c["completion"] for c in report["cases"])
    assert (tmp_path / "report/index.html").exists()
    import asyncio

    await asyncio.to_thread(
        invoke, command, "offline", "--packet", packet_path, "--out", tmp_path / "executed"
    )
    assert sum(c["completion"] for c in read(tmp_path / "executed/results.json")["cases"]) == 10
    invoke(operator, "revoke", "--packet", packet_path, "--receipt", receipt2)
    with store.pool.connection() as conn:
        assert conn.execute("SELECT state FROM workspace_d5_scopes").fetchone()[0] == "revoked"


@pytest.mark.parametrize("amount", ["0.40", "0.400000", "1.000000000000000000000"])
async def test_exact_snapshot_reconstruction_into_second_real_postgres_schema(
    store, request, monkeypatch, tmp_path, amount
):
    from src.workspace.d5_fixture import prepare_projects
    from tests.test_workspace_store import store as factory

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    packet = corpus(store)
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_spend_reservations SET amount=%s WHERE amount>0", (amount,))
        packet["history"] = census(conn, "a")
    captured = snapshot(store, store, "evaluation", "profile")
    assert all(
        isinstance(r["amount"], str) for r in captured["tables"]["workspace_spend_reservations"]
    )
    from src.workspace.d5_fixture import financial_rows

    with (
        store.pool.connection() as conn,
        pytest.raises(AdmissionError, match="financial_table_required"),
    ):
        financial_rows(conn, "workspace_budget_policies")
    generator = factory.__wrapped__(request)
    other = next(generator)
    try:
        from src.workspace import d5_benchmark as command

        packet["snapshot_digest"] = _digest(captured)
        packet["packet_digest"] = _digest({k: v for k, v in packet.items() if k != "packet_digest"})
        packet_path = tmp_path / "packet.json"
        snapshot_path = tmp_path / "snapshot.json"
        write(packet_path, packet)
        write(snapshot_path, captured)
        monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
        monkeypatch.setattr(command, "database", lambda _: nullcontext(other.pool))
        monkeypatch.setattr(
            "sys.argv",
            [
                "d5_benchmark",
                "init",
                "--packet",
                str(packet_path),
                "--snapshot",
                str(snapshot_path),
                "--offline-fixture",
            ],
        )
        command.main()
        prepare_projects(other, packet)
        check_storage(other, packet)
        with other.pool.connection() as conn:
            members = [r[0] for r in conn.execute("SELECT owner FROM workspace_evaluation_members")]
            assert census(conn, members[0], members=members) == packet["history"]
            assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
            assert (
                conn.execute("SELECT count(*) FROM workspace_d5_fixture_marker").fetchone()[0] == 1
            )
        authorize_fixture(other, packet)
        report = await run(other, packet, "A", offline=True)
        assert report["accounting"]["new_scope"]["messages"] == 0
        assert report["accounting"]["new_scope"]["counts"] == 4
    finally:
        with suppress(StopIteration):
            next(generator)


async def test_scientific_selection_keeps_qualifications_unicode_and_repeated_exact_offsets():
    text = "The agent’s naïve policy improves the reported metric on a small benchmark. However, the result requires tools and does not establish general reasoning."
    material = extract_text(
        text, work_id="arxiv:2611.00001", version_id="arxiv:2611.00001:v1", scope="abstract"
    )
    selected = select([material], question="agent metric")
    ref = selected["selected"][0]["reference"]
    assert (
        ref["quote"] == text
        and "However" in ref["quote"]
        and material.pages[0][ref["start"] : ref["end"]] == text
    )
    assert select([], question="missing")["selected"] == []
    short = extract_text(
        "Too little.", work_id=material.work_id, version_id=material.version_id, scope="abstract"
    )
    assert not select([short], question="little")["selected"]
    from src.workspace.assistance_contract import coherent_units

    pdf = replace(
        material,
        page_count=1,
        page_numbers=(1,),
        scope="excerpt",
        pages=("Published as a conference paper\nTITLE\nAuthors a@b.example\nABSTRACT\n" + text,),
        spans=(),
    )
    from src.workspace.material import _build

    pdf = _build(
        work_id=pdf.work_id,
        version_id=pdf.version_id,
        source_hash=pdf.source_hash,
        scope=pdf.scope,
        parser_revision=pdf.parser_revision,
        pages=list(pdf.pages),
        page_count=1,
        quality="unqualified",
        warnings=[],
        complete=False,
        page_numbers=[1],
    )
    units = coherent_units([pdf], {s.span_id for s in pdf.spans})
    ref = next(iter(units.values()))
    assert ref.quote.startswith("The agent") and "Authors" not in ref.quote
    assert pdf.pages[0][ref.start : ref.end] == ref.quote
    bad = replace(pdf, warnings=("unreliable original page 1 extraction",))
    assert not assess(ref, bad)["eligible"]


async def test_selection_explicitly_labels_layout_and_front_matter_failures():

    material = extract_text(
        "A valid sentence with a substantive scientific qualification and enough words to preserve meaningful context.",
        work_id="arxiv:2611.00001",
        version_id="arxiv:2611.00001:v1",
        scope="abstract",
    )
    for text in [
        "Preprint. Words describe a long enough scientific sentence with numerous terms to pass the short text filter.",
        "a@b.org author list with enough words to describe a long scientific author affiliation and publication.",
        "0001 + 0002 = 0003 *** / [] {} 0 0 0 0 0 0 0 0",
    ]:
        from src.workspace.grounding import evidence_ref

        ref = replace(evidence_ref(material, material.spans[0]), quote=text)
        assert not assess(ref, material)["eligible"]
    damaged = replace(material, spans=())
    assert select([damaged], question="x")["rejected"][0]["reason"] == "no_coherent_unit"


async def test_probe_requests_are_frozen_and_cannot_expand_selected_handles(store, monkeypatch):
    import httpx

    from src.workspace.d5_adapter import D5ProbeAdapter
    from src.workspace.d5_fixture import ReplayTransport

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    packet = corpus(store)
    entry = compile_inputs(packet)["probe-1"]
    original = restore_input(entry["input"])
    for change in ["missing", "unselected", "text"]:
        from copy import deepcopy

        settings = deepcopy(original.settings)
        if change == "missing":
            settings["probe_context"] = None
        elif change == "unselected":
            settings["probe_context"]["claims"][0]["handles"] = ["not-approved"]
        else:
            settings["probe_context"]["claims"][0]["text"] = "Changed assertion"
        adapter = D5ProbeAdapter(
            store,
            entry["owner"],
            replace(original, settings=settings),
            transport=httpx.MockTransport(ReplayTransport(change)),
        )
        with pytest.raises(AdmissionError):
            adapter.request()


async def test_count_only_then_separately_recorded_funded_stage_runs_same_protected_cli(
    store, monkeypatch, tmp_path
):
    from src.workspace import d5_operator as operator

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("D5_POSTGRES_URL", "postgresql://localhost:15488/workspace_d5_tests")
    packet = corpus(store)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, packet, stages=("A",))
    measured = await run(store, packet, "A", offline=True)
    assert (
        measured["accounting"]["new_scope"]["counts"] == 4
        and measured["accounting"]["new_scope"]["messages"] == 0
    )
    with pytest.raises(AdmissionError, match="stage_not_authorized"):
        await run(store, packet, "B", offline=True)
    packet_path = tmp_path / "packet.json"
    receipt_path = tmp_path / "funded.json"
    write(packet_path, packet)
    monkeypatch.setattr(operator, "database", lambda _: nullcontext(store.pool))
    monkeypatch.setattr(
        "sys.argv",
        [
            "operator",
            "stage-template",
            "--packet",
            str(packet_path),
            "--receipt",
            str(receipt_path),
            "--stages",
            "B",
        ],
    )
    operator.main()
    receipt = read(receipt_path)
    assert receipt["approved"] is False
    receipt.update(
        approved=True,
        approved_by="Synthetic fixture, not owner approval",
        approved_at=__import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
    )
    receipt_path.write_text(__import__("json").dumps(receipt))
    monkeypatch.setattr(
        "sys.argv",
        ["operator", "grant", "--packet", str(packet_path), "--receipt", str(receipt_path)],
    )
    operator.main()
    funded = await run(store, packet, "B", offline=True)
    assert all(
        funded["raw_results"][name]["state"] == "ready" for name in ["dev-learn", "dev-compare"]
    )
    assert funded["accounting"]["new_scope"]["messages"] <= 8
    with store.pool.connection() as conn:
        parent = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes"
        ).fetchone()[0]
    assert parent["stages"] == ["A"]


async def test_successor_explicitly_reuses_completed_A_receipts_but_B_C_D_still_need_separate_approval(
    store, monkeypatch
):
    from copy import deepcopy

    from src.workspace import d5_fixture as fixture
    from src.workspace import d5_freeze as frozen
    from src.workspace.d5_measurements import make_link

    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    old_packet = corpus(store)
    with store.pool.connection() as conn:
        conn.execute("INSERT INTO workspace_d5_fixture_marker VALUES(TRUE,'offline_only','{}')")
    authorize_fixture(store, old_packet, stages=("A",))
    measured = await run(store, old_packet, "A", offline=True)
    with store.pool.connection() as conn:
        auth = conn.execute(
            "SELECT data->'authorization_record' FROM workspace_d5_scopes"
        ).fetchone()[0]
        owners = [x[0] for x in conn.execute("SELECT owner FROM workspace_evaluation_members")]
        before = census(conn, owners[0], members=owners)
    links = {
        key: make_link(store, value["id"], auth) for key, value in measured["raw_results"].items()
    }
    successor = deepcopy(old_packet)
    successor.update(
        history=before, measurement_reuse=links, predecessor_packet=old_packet["packet_digest"]
    )
    successor["packet_digest"] = _digest(
        {k: v for k, v in successor.items() if k != "packet_digest"}
    )
    for module in (frozen, fixture):
        monkeypatch.setattr(module, "RUN_OWNER", "d5-successor-run")
        monkeypatch.setattr(module, "COUNT_OWNER", "d5-successor-measure")
    fixture.prepare_projects(store, successor)
    authorize_fixture(store, successor, stages=("B",))
    result = await run(store, successor, "B", offline=True)
    assert set(result["raw_results"]) == {"dev-learn", "dev-compare"}
    assert all(result["raw_results"][k]["state"] == "ready" for k in result["raw_results"])
    after = result["accounting"]["cumulative"]
    assert (
        after["counts"] - before["counts"] == 4
    )  # Only mandatory paired draft/check counts, no repeated preliminary A.
    for key, checkpoint in before["contact_checkpoints"].items():
        assert after["contact_checkpoints"][key] == checkpoint
    with store.pool.connection() as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM workspace_generation_jobs WHERE owner='d5-successor-measure'"
            ).fetchone()[0]
            == 0
        )
        proofs = conn.execute(
            "SELECT data->'d5_measurement_basis' FROM workspace_generation_jobs WHERE owner='d5-successor-run'"
        ).fetchall()
        assert len(proofs) == 2 and all(len(x[0]) == 4 for x in proofs)
    with pytest.raises(AdmissionError, match="stage_not_authorized"):
        await run(store, successor, "C", offline=True)
    with pytest.raises(AdmissionError, match="previous_stage_not_complete"):
        await run(store, successor, "D", offline=True)
