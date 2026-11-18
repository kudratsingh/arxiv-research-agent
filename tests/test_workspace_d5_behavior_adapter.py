"""Behavior scoring from real isolated qualification snapshots and mock HTTP."""

from copy import deepcopy
from dataclasses import asdict
from types import SimpleNamespace

import httpx
import pytest

from src.workspace import d5_adapter
from src.workspace.admission import _digest
from src.workspace.d5_behavior_scoring import score_campaign
from src.workspace.d5_capacity_policy import ROUTES
from src.workspace.d5_comparison_transport import ComparisonCampaignTransport
from src.workspace.d5_results import QualificationResults
from tests import comparison_v19_pipeline as fixture
from tests import test_workspace_d5_adapter as legacy
from tests.d5_capacity_gate import export_rows

store = legacy.store
if hasattr(legacy, "workspace_pg"):
    workspace_pg_proc, workspace_pg = legacy.workspace_pg_proc, legacy.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def prepare_case(store, monkeypatch, *, mode, application):
    prepare = d5_adapter.prepare_input
    full = {}
    validate = fixture.CoverageTaskContext.model_validate

    def record_preview(sealed, **kwargs):
        full.update(deepcopy(sealed))
        return prepare(sealed, **kwargs)

    def application_task(data):
        parts = [{**part, "kind": "answer"} for part in data["requested_parts"]]
        parts[0]["request"] = "Can these sources support the unspecified application?"
        return validate({**data, "intent": "application_assessment", "requested_parts": parts})

    with monkeypatch.context() as scoped:
        scoped.setattr(d5_adapter, "prepare_input", record_preview)
        if application:
            scoped.setattr(
                fixture, "CoverageTaskContext", SimpleNamespace(model_validate=application_task)
            )
        inputs = fixture.setup(store, scoped, mode)
    case = {
        "id": inputs.settings["d5_case_id"],
        "cohort": "evaluation_exposed_corpus",
        "pipeline": mode,
        "sealed": full,
        "ranking": None,
        "edition": None,
        "evidence_selection": None,
        "baselines": None,
    }
    return inputs, case


def software_reference(case, expected):
    sealed = case["sealed"]
    selected = [
        {"handle": handle, "reference_digest": _digest(ref)}
        for handle, ref in sealed["units"].items()
    ]
    rows = []
    for part, behavior in zip(sealed["task_policy"]["requested_parts"], expected, strict=True):
        rows.append(
            {
                "case_id": case["id"],
                "part_id": part["id"],
                "requested_part": part,
                "request_digest": _digest(part),
                "answerability": "partially_answerable"
                if behavior == "bounded_partial_answer"
                else "insufficient",
                "expected_behavior": behavior,
                "selected_evidence": selected,
                "limitation_origins": [],
            }
        )
    matrix = {"rows": rows, "basis": "Synthetic isolated test expectations"}
    return {**matrix, "matrix_digest": _digest(matrix)}


@pytest.mark.parametrize(
    ("scenario", "expected", "disposition"),
    [
        ("bounded_partial", ["bounded_partial_answer"] * 2, "answer"),
        (
            "comparison_notes",
            ["comparison_only_abstention", "bounded_partial_answer"],
            "comparison_abstention",
        ),
        ("application_context", ["full_application_abstention"] * 2, "full_abstention"),
    ],
)
async def test_bound_qualification_snapshot_reaches_ready_and_scores_behavior(
    store, monkeypatch, scenario, expected, disposition
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    inputs, case = prepare_case(
        store,
        monkeypatch,
        mode="learn" if scenario == "bounded_partial" else "research",
        application=scenario == "application_context",
    )
    if scenario == "comparison_notes":
        handler = fixture.SyntheticTransport("source_notes")
    else:
        handler = ComparisonCampaignTransport(case["id"])
    adapter = d5_adapter.D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(handler))
    reference = software_reference(case, expected)

    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        await adapter.advance(job["id"])
        assert adapter.snapshot(job["id"])["state"] != "ready"
        await adapter.advance(job["id"])
        snapshot = QualificationResults(store).snapshot("d5-run", job["id"])
        assert snapshot["state"] == "ready"
        assert snapshot["simulated"] and snapshot["source_binding_intact"]
        assert snapshot["request"] != case["sealed"]
        assert snapshot["request"] == inputs.snapshot()["settings"]["d5_request"]
        assert not snapshot["factual_acceptance"] and not snapshot["checker_qualified"]
        assert snapshot["human_review"] is None
        assert [step["stage"] for step in snapshot["steps"]] == ["draft", "check"]
        assert [contact["endpoint"] for contact in snapshot["contacts"]] == [
            "messages/count_tokens",
            "messages",
            "messages/count_tokens",
            "messages",
        ]

        _, materials = adapter._context()
        report = score_campaign(
            [case],
            {case["id"]: snapshot},
            materials,
            reference,
            {},
            {},
            routes=ROUTES,
            frozen_materials=[asdict(material) for material in materials],
        )
        fixture.retain_report(
            "behavior-scoring", scenario, {"report": report, "raw_qualification_snapshot": snapshot}
        )
        workflow = report["workflows"][0]
        assert workflow["assessment_binding"]["status"] == "bound"
        assert workflow["assessment_binding"]["checker_ordinal"] == 3
        assert workflow["contract_complete"] and workflow["review_complete"]
        assert workflow["response_disposition"] == disposition
        assert workflow["machine_request_outcome"]["quality_gate"] == "PASS"
        assert workflow["machine_request_outcome"]["full_answer_credit"] is False
        assert [part["behavior"] for part in report["parts"]] == ["PASS", "PASS"]
        assert all(part["full_answer_credit"] is False for part in report["parts"])
        assert report["behavioral_gate"] == report["machine_quality"] == "HOLD"
        assert "reviewed_claim_findings_below_minimum" in report["gate_reasons"]
        if scenario == "comparison_notes":
            part = workflow["declared_coverage"][0]
            assert not part["answer_claim_ids"] and part["context_claim_ids"]
            assert report["parts"][0]["request_fulfillment"] == "unmet"
        if scenario == "application_context":
            assert not workflow["claims"] and snapshot["result"]["content_status"] == "abstained"
            assert workflow["whole_claim_support"]["support_ratio"] is None
            assert report["denominators"]["reviewed_claim_findings"] == 0
    finally:
        export_rows(store, "behavior-scoring-" + scenario)
