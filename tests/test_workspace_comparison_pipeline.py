"""V19 production-pipeline regressions in disposable Postgres, with mock HTTP.

Synthetic grants, token counts, usage and judgments prove software mechanics.
They provide no provider acceptance, scientific truth or human qualification.
"""

from __future__ import annotations

from copy import deepcopy

import httpx
import pytest

from src.workspace import d5_adapter as adapter_module
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_campaign_report import score_workflow
from src.workspace.d5_capacity_policy import ROUTES
from src.workspace.d5_report_binding import ReportBindingError, current_check
from src.workspace.d5_results import QualificationResults
from tests import test_workspace_d5_adapter as legacy
from tests.comparison_v19_pipeline import (
    SyntheticTransport,
    assert_paired_contacts,
    retain_report,
    setup,
)
from tests.d5_capacity_gate import export_rows

store = legacy.store
if hasattr(legacy, "workspace_pg"):
    workspace_pg_proc, workspace_pg = legacy.workspace_pg_proc, legacy.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def open_adapter(store, inputs, handler):
    return adapter_module.D5Adapter(
        store, "d5-run", inputs, transport=httpx.MockTransport(handler)
    )


def bound_current(adapter, inputs, final):
    _, materials = adapter._context()
    return current_check(
        dict(inputs.settings["d5_request"]), final, materials, routes=ROUTES
    )


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("scenario", ["repair", "residual", "uncertain_quality", "uncertain_check", "uncertain_recheck"])
async def test_v19_repair_recheck_persistence_and_current_report_binding(
    store, monkeypatch, mode, scenario
):
    inputs = setup(store, monkeypatch, mode)
    handler = SyntheticTransport(scenario)
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        count = 2 if scenario == "uncertain_check" else 4
        for index in range(count):
            if index == count - 1 and scenario != "repair":
                with pytest.raises((AdmissionError, httpx.ReadTimeout)):
                    await adapter.advance(job["id"])
            else:
                await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert_paired_contacts(final, handler, count)
        assert handler.phases == ["draft", "check", "repair", "check"][:count]
        persisted = QualificationResults(store).snapshot("d5-run", job["id"])
        assert persisted["source_binding_intact"]
        assert persisted["factual_acceptance"] is False
        assert persisted["human_review"] is None and persisted["checker_qualified"] is False
        assert persisted["everyday_generation"] is False
        assert persisted["simulated"] is True
        assert final["steps"] == persisted["steps"]
        _, materials = adapter._context()
        report = score_workflow(
            {
                "id": "case", "cohort": "synthetic", "pipeline": mode,
                "sealed": dict(inputs.settings["d5_request"]),
                "ranking": None, "edition": None, "evidence_selection": None, "baselines": None,
            }, persisted, materials, routes=ROUTES,
        )
        retain_report(mode, scenario, report)
        assert report["human_review"] is None and report["human_qualified"] is False
        if scenario == "repair":
            assert final["state"] == persisted["state"] == "ready"
            bound = bound_current(adapter, inputs, final)
            assert bound["binding"]["completed_checker_after_current_response"] is True
            assert bound["binding"]["checker_ordinal"] == 7
            assert bound["binding"]["current_response_digest"] == _digest(final["steps"][2]["output"])
            assert bound["raw_verdict"]["coverage_critiques"] == []
            assert report["coverage_critiques"] == []
            assert report["prose_uncertainties"] == []
            assert report["machine_request_outcome"]["quality_gate"] == "PASS"
            assert report["machine_request_outcome"]["full_answer_credit"] is False
            assert report["completion"] is True, report["assessment_binding"]
            assert report["assessment_binding"] == bound["binding"]
            assert report["claims"] and report["whole_claim_support"]
            assert handler.outputs[0] != handler.outputs[1], "Repair changes a claim, so an old check cannot bind."
            restarted = open_adapter(store, inputs, handler)
            assert restarted.start(inputs.settings["d5_request_id"])["id"] == job["id"]
            assert restarted.snapshot(job["id"])["steps"] == final["steps"]
            assert len(handler.contacts) == 8
            assert persisted["assistance_output"] is not None
            assert_lossless_persistence(inputs, persisted, handler)
            stale = deepcopy(final)
            stale["steps"] = final["steps"][:3]
            stale["contacts"] = final["contacts"][:6]
            with pytest.raises(ReportBindingError, match="no_completed_check_after_current_response"):
                bound_current(adapter, inputs, stale)
        elif scenario in {"residual", "uncertain_quality"}:
            assert final["state"] == "failed" and persisted["result"] is None
            bound = bound_current(adapter, inputs, final)
            assert bound["raw_verdict"]["coverage_critiques"]
            if scenario == "residual":
                assert bound["raw_verdict"]["prose_findings"]
            else:
                assert bound["raw_verdict"]["prose_uncertainties"]
                assert any(p["decision"] == "uncertain" for p in bound["raw_verdict"]["coverage_checks"])
            assert persisted["assistance_output"] is None
            assert report["completion"] is False
            assert report["assessment_binding"]["status"] == "bound"
            assert report["coverage_critiques"] == bound["raw_verdict"]["coverage_critiques"]
            assert report["prose_uncertainties"] == bound["raw_verdict"]["prose_uncertainties"]
            assert report["machine_request_outcome"]["quality_gate"] != "PASS"
            assert report["machine_request_outcome"]["full_answer_credit"] is False
            if scenario == "residual":
                assert report["prose_findings"]
        else:
            assert final["state"] == "uncertain" and persisted["result"] is None
            assert float(persisted["unknown_usd"]) > 0
            assert report["completion"] is False
            assert report["assessment_binding"]["status"] == "unavailable"
            with pytest.raises(ReportBindingError, match="no_completed_check_after_current_response"):
                bound_current(adapter, inputs, final)
        if scenario != "repair":
            restarted = open_adapter(store, inputs, handler)
            with pytest.raises(AdmissionError):
                await restarted.advance(job["id"])
            with pytest.raises(AdmissionError):
                restarted.start(inputs.settings["d5_request_id"])
            assert len(handler.contacts) == 2 * count
    finally:
        export_rows(store, "v19-pipeline-" + mode + "-" + scenario)


def assert_lossless_persistence(inputs, persisted, handler):
    from src.workspace import assistance_comparison_contract as codec

    sealed = inputs.settings["d5_request"]
    wire = handler.outputs[-1]
    normalized, coverage = codec.normalize(
        wire, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
    )
    assert codec.wire_payload(normalized, coverage, sealed["task_policy"]) == wire
    rendered = persisted["assistance_output"]
    assert rendered["question_references"] == wire["response"]["questions"]
    assert rendered["question_references"][0]["premise_claim_ids"] == []
    assert rendered["question_references"][1]["premise_claim_ids"]
    for row in rendered["request_coverage"]:
        source = wire["response"]["coverage"][row["id"]]
        assert row["status"] == source["status"] == "partial"
        assert row["gap_reasons"] == source["gap_reasons"] == ["methods", "protocol"]
        assert row["answer_claim_ids"] == source["answer_claim_ids"]
        assert row["context_claim_ids"] == source["context_claim_ids"]
    assert not rendered["coverage_complete"]
    assert rendered["request_outcome"]["full_answer_credit"] is False


@pytest.mark.parametrize("mode", ["learn", "research"])
async def test_v19_semantically_invalid_first_draft_is_terminal_without_repair(
    store, monkeypatch, mode
):
    inputs = setup(store, monkeypatch, mode)
    handler = SyntheticTransport("invalid_draft")
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        with pytest.raises((AdmissionError, ValueError), match="answered_requires_complete_answer_without_gaps"):
            await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "failed" and final["steps"] == []
        assert handler.phases == ["draft"]
        assert_paired_contacts(final, handler, 1)
        result = QualificationResults(store).snapshot("d5-run", job["id"])
        assert result["result"] is None and result["assistance_output"] is None
        assert result["unknown_usd"] == "0" and result["accounting_audits"]
        restarted = open_adapter(store, inputs, handler)
        with pytest.raises(AdmissionError):
            await restarted.advance(job["id"])
        assert len(handler.contacts) == 2
    finally:
        export_rows(store, "v19-invalid-first-draft-" + mode)


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("after_draft", [False, True])
async def test_v19_cancellation_is_durable_and_duplicate_does_not_dispatch(
    store, monkeypatch, mode, after_draft
):
    inputs = setup(store, monkeypatch, mode)
    handler = SyntheticTransport("clear")
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        assert adapter.start(inputs.settings["d5_request_id"])["id"] == job["id"]
        if after_draft:
            await adapter.advance(job["id"])
        await adapter.advance(job["id"], cancelled=lambda: True)
        restarted = open_adapter(store, inputs, handler)
        final = restarted.snapshot(job["id"])
        assert final["state"] == "cancelled"
        assert len(handler.contacts) == (2 if after_draft else 0)
        assert len(final["steps"]) == (1 if after_draft else 0)
        with pytest.raises(AdmissionError):
            await restarted.advance(job["id"])
        with pytest.raises(AdmissionError):
            restarted.start(inputs.settings["d5_request_id"])
        assert len(handler.contacts) == (2 if after_draft else 0)
        result = QualificationResults(store).snapshot("d5-run", job["id"])
        assert result["result"] is None and result["assistance_output"] is None
    finally:
        export_rows(store, "v19-cancel-" + mode + "-" + str(after_draft))


@pytest.mark.parametrize("notes_only", [False, True])
async def test_v19_research_qualitative_comparison_and_source_notes_credit(
    store, monkeypatch, notes_only
):
    inputs = setup(store, monkeypatch, "research")
    handler = SyntheticTransport("source_notes" if notes_only else "clear")
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        await adapter.advance(job["id"])
        await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "ready"
        assert handler.phases == ["draft", "check"]
        assert_paired_contacts(final, handler, 2)
        bound = bound_current(adapter, inputs, final)
        assert bound["binding"]["checker_ordinal"] == 3
        result = QualificationResults(store).snapshot("d5-run", job["id"])
        output = result["assistance_output"]
        comparative = next(r for r in output["request_coverage"] if r["kind"] == "comparison")
        if notes_only:
            assert comparative["answer_claim_ids"] == [] and comparative["context_claim_ids"]
            assert comparative["status"] == "lacks_evidence"
            assert output["comparison_unanswered"]
            assert output["response_disposition"] == "comparison_abstention"
            assert not output["request_outcome"]["full_answer_credit"]
        else:
            assert comparative["answer_claim_ids"] == ["c3"]
            assert output["comparison_claims"] == output["comparison_basis"] == ["c3"]
            assert output["comparison_evidence_handles"] == {
                "c3": handler.outputs[0]["response"]["claims"][2]["handles"]
            }
            assert not output["comparison_unanswered"]
            assert output["response_disposition"] == "answer"
            assert "different evaluation setting" in handler.outputs[0]["response"]["claims"][2]["text"]
        assert result["human_review"] is None and result["factual_acceptance"] is False
    finally:
        export_rows(store, "v19-research-" + ("source-notes" if notes_only else "qualitative"))


@pytest.mark.parametrize("scenario", ["single_source_comparison", "pooled_source_comparison"])
async def test_v19_each_comparative_answer_requires_its_own_two_source_bases(
    store, monkeypatch, scenario
):
    inputs = setup(store, monkeypatch, "research")
    handler = SyntheticTransport(scenario)
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        with pytest.raises((AdmissionError, ValueError), match="comparison_finding_requires_separately_cited_source_bases"):
            await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "failed" and final["steps"] == []
        assert_paired_contacts(final, handler, 1)
        assert handler.phases == ["draft"]
        assert QualificationResults(store).snapshot("d5-run", job["id"])["result"] is None
        with pytest.raises(AdmissionError):
            await adapter.advance(job["id"])
        assert len(handler.contacts) == 2
    finally:
        export_rows(store, "v19-each-comparison-basis-" + scenario)


@pytest.mark.parametrize("mode", ["learn", "research"])
async def test_v19_full_abstention_still_requires_completed_current_checker(
    store, monkeypatch, mode
):
    inputs = setup(store, monkeypatch, mode)
    handler = SyntheticTransport("full_abstention")
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        await adapter.advance(job["id"])
        draft_only = adapter.snapshot(job["id"])
        assert draft_only["state"] != "ready"
        with pytest.raises(ReportBindingError, match="no_completed_check_after_current_response"):
            bound_current(adapter, inputs, draft_only)
        await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "ready"
        assert_paired_contacts(final, handler, 2)
        assert handler.phases == ["draft", "check"]
        assert bound_current(adapter, inputs, final)["binding"]["checker_ordinal"] == 3
        result = QualificationResults(store).snapshot("d5-run", job["id"])
        output = result["assistance_output"]
        assert output["response_disposition"] == "full_abstention" and not output["claims"]
        assert not output["request_outcome"]["full_answer_credit"]
        for row in output["request_coverage"]:
            assert row["status"] == "lacks_evidence"
            assert row["gap_reasons"] == ["methods", "protocol"]
            assert not row["answer_claim_ids"] and not row["context_claim_ids"]
        assert result["factual_acceptance"] is False and result["human_review"] is None
    finally:
        export_rows(store, "v19-full-abstention-" + mode)


@pytest.mark.parametrize("scenario", ["unsupported_performance", "false_full_comparison"])
async def test_v19_citations_do_not_override_semantic_comparison_or_coverage_rejection(
    store, monkeypatch, scenario
):
    from src.workspace.assistance_policy import render_task_output

    inputs = setup(
        store, monkeypatch, "research",
        comparison_request="Contrast the selected method descriptions and compare performance under compatible tasks, metrics and conditions; preserve remaining gaps.",
    )
    handler = SyntheticTransport(scenario)
    adapter = open_adapter(store, inputs, handler)
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        for index in range(4):
            if index == 3:
                with pytest.raises(AdmissionError):
                    await adapter.advance(job["id"])
            else:
                await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "failed"
        assert handler.phases == ["draft", "check", "repair", "check"]
        assert_paired_contacts(final, handler, 4)
        bound = bound_current(adapter, inputs, final)
        assert bound["binding"]["checker_ordinal"] == 7
        assert bound["binding"]["current_response_digest"] == _digest(final["steps"][2]["output"])
        sealed = inputs.settings["d5_request"]
        final_wire = handler.outputs[-1]
        comparative = final_wire["response"]["claims"][2]
        assert len({sealed["units"][h]["work_id"] for h in comparative["handles"]}) == 2
        persisted = QualificationResults(store).snapshot("d5-run", job["id"])
        assert persisted["source_binding_intact"] and persisted["result"] is None
        assert persisted["assistance_output"] is None and not persisted["factual_acceptance"]
        _, materials = adapter._context()
        report = score_workflow(
            {
                "id": "case", "cohort": "synthetic", "pipeline": "research",
                "sealed": dict(sealed), "ranking": None, "edition": None,
                "evidence_selection": None, "baselines": None,
            }, persisted, materials, routes=ROUTES,
        )
        retain_report("research", scenario, report)
        assert report["assessment_binding"] == bound["binding"]
        assert not report["completion"] and report["mechanical_provenance"]
        assert report["machine_request_outcome"]["quality_gate"] == "FAIL"
        assert report["machine_request_outcome"]["full_answer_credit"] is False
        assert report["coverage_critiques"] == bound["raw_verdict"]["coverage_critiques"]
        part = next(p for p in bound["raw_verdict"]["coverage_checks"] if p["part_id"] == "p1")
        if scenario == "unsupported_performance":
            finding = next(c for c in bound["raw_verdict"]["checks"] if c["claim_id"] == "c3")
            assert finding["decision"] == "unsupported"
            assert part["decision"] == "lacks_evidence"
            assert report["whole_claim_support"]["unsupported"] > 0
        else:
            assert all(c["decision"] == "supported" for c in bound["raw_verdict"]["checks"])
            declared = render_task_output(
                final_wire, list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
            )
            assert declared["coverage_complete"]
            assert all(p["status"] == "answered" for p in report["declared_coverage"])
            assert part["decision"] == "partial"
            assert report["machine_request_outcome"]["coverage_disagreements"] == ["p1"]
        with pytest.raises(AdmissionError):
            await adapter.advance(job["id"])
        assert len(handler.contacts) == 8
    finally:
        export_rows(store, "v19-semantic-comparison-" + scenario)
