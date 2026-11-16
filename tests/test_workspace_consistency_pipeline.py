"""Four-stage production pipeline with explicitly synthetic successor outputs.

Real admission, exact counts, schemas, binding and persistence; mocked HTTP only.
These fixtures establish no provider acceptance, scientific quality or human review.
"""

from __future__ import annotations

import json
from copy import deepcopy

import httpx
import pytest
from jsonschema import Draft202012Validator

from src.workspace import assistance_compact_encoding as compact
from src.workspace import assistance_consistency_contract as codec
from src.workspace import d5_adapter as adapter_module
from src.workspace import d5_capacity_transport as capacity_fixture
from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance import capacity
from src.workspace.d5_campaign_v16_packet import upgrade
from src.workspace.d5_capacity_policy import DEADLINES, POLICY, ROUTES
from src.workspace.d5_operations import wire
from tests import test_workspace_consistency_contract as samples
from tests import test_workspace_d5_adapter as old
from tests.d5_capacity_gate import export_rows

store = old.store
if hasattr(old, "workspace_pg"):
    workspace_pg_proc, workspace_pg = old.workspace_pg_proc, old.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


def setup(store, monkeypatch, mode, intent="answer"):
    prepare = adapter_module.prepare_input

    def prospective(sealed, **kwargs):
        from src.workspace.assistance_policy import CoverageTaskContext

        sealed = deepcopy(sealed)
        sealed["assistance"]["task_context"] = CoverageTaskContext(intent=intent).model_dump(
            mode="json"
        )
        sealed = upgrade(sealed, union_safe=True)
        sealed["task_policy"][codec.KEY] = codec.REVISION
        sealed["response_schemas"] = codec.schemas(
            list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
        )
        for stage in ["draft", "repair"]:
            sealed["stage_contracts"][stage]["output_schema"] = sealed["response_schemas"]["wire"]
        sealed["candidate_initial_wire"] = wire(adapter_module.initial_context(sealed), ROUTES)
        sealed["capacity"] = capacity(sealed)
        kwargs.update(
            capacity_policy=POLICY,
            operation_routes=ROUTES,
            operation_deadlines=DEADLINES,
            repair_located_prose=True,
        )
        return prepare(sealed, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(adapter_module, "prepare_input", prospective)
        return old.setup(store, mode=mode, comparison=mode == "research")


class Transport:
    def __init__(self, scenario="repair"):
        self.scenario = scenario
        self.contacts = []
        self.checks = 0

    async def __call__(self, request):
        body = json.loads(request.content)
        self.contacts.append((request.url.path, body))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        context = json.loads(body["messages"][0]["content"])
        if context["phase"] == "check":
            self.checks += 1
            if self.scenario == "uncertain_recheck" and self.checks == 2:
                raise httpx.ReadTimeout("Synthetic uncertain recheck", request=request)
            value = samples.synthetic_verdict(context)
            if (
                self.checks == 1 and self.scenario not in {"clear", "comparison_notes"}
            ) or self.scenario == "residual":
                first = next(iter(value["coverage_checks"]))
                value["coverage_checks"][first]["critiques"] = [
                    "Synthetic coverage-only criticism requiring the one bounded repair."
                ]
                if self.scenario == "residual" and self.checks == 2:
                    key = next(iter(value["prose_findings"]))
                    value["prose_findings"][key] = [
                        "Synthetic residual factual assertion; must remain blocked."
                    ]
        else:
            # Test-only conversion of newly generated synthetic fixtures; never
            # mutate, repair or credit an archived provider response.
            oldcontext = deepcopy(context)
            oldcontext["sealed_request"]["schema_revision"] = "workspace-assistance-capacity-v15"
            oldcontext["sealed_request"]["task_policy"] = __import__(
                "src.workspace.assistance_keyed_contract", fromlist=["prior_policy"]
            ).prior_policy(oldcontext["sealed_request"]["task_policy"])
            raw = capacity_fixture.draft_payload(oldcontext, long=True)
            from src.workspace.assistance_capacity_contract import normalize
            from src.workspace.assistance_compact_encoding import wire_payload

            sealed = context["sealed_request"]
            purpose = (
                "research_comparison"
                if sealed["assistance"]["mode"] == "research"
                else "single_paper"
            )
            envelope, coverage = normalize(
                raw, list(sealed["units"]), purpose, oldcontext["sealed_request"]["task_policy"]
            )
            prior = wire_payload(
                envelope, coverage, {**sealed["task_policy"], codec.KEY: compact.REVISION}
            )
            value = samples.synthetic_upgrade(prior)
            if self.scenario == "comparison_notes":
                generated = value["response"]
                generated.update(comparison_claims=[], comparison_basis=[])
                for row in generated["coverage"].values():
                    row.update(
                        status="lacks_evidence",
                        gap_reasons=["common_evaluation"],
                        answer_claim_ids=[],
                        context_claim_ids=[f"c{i + 1}" for i in range(len(generated["claims"]))],
                    )
        Draft202012Validator(body["output_config"]["format"]["schema"]).validate(value)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-v18-workflow-" + str(len(self.contacts)),
                "type": "message",
                "model": body["model"],
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("scenario", ["repair", "residual", "uncertain_recheck"])
async def test_actual_four_stage_pipeline_current_response_binding(
    store, monkeypatch, mode, scenario
):
    inputs = setup(store, monkeypatch, mode)
    handler = Transport(scenario)
    adapter = adapter_module.D5Adapter(
        store, "d5-run", inputs, transport=httpx.MockTransport(handler)
    )
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        for index in range(4):
            if index == 3 and scenario in {"residual", "uncertain_recheck"}:
                with pytest.raises((AdmissionError, httpx.ReadTimeout)):
                    await adapter.advance(job["id"])
            else:
                await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        phases = [
            json.loads(body["messages"][0]["content"])["phase"]
            for path, body in handler.contacts
            if path.endswith("/messages")
        ]
        assert phases == ["draft", "check", "repair", "check"]
        assert len(handler.contacts) == 8
        from src.workspace.d5_report_binding import ReportBindingError, current_check

        _, materials = adapter._context()
        sealed = dict(inputs.settings["d5_request"])
        if scenario == "repair":
            assert final["state"] == "ready" and len(final["steps"]) == 4
            bound = current_check(sealed, final, materials, routes=ROUTES)
            assert bound["binding"]["completed_checker_after_current_response"] is True
            assert bound["binding"]["current_response_digest"] == _digest(
                final["steps"][2]["output"]
            )
            assert bound["binding"]["checker_ordinal"] == 7
            assert bound["raw_verdict"]["coverage_critiques"] == []
        elif scenario == "residual":
            assert final["state"] == "failed"
            bound = current_check(sealed, final, materials, routes=ROUTES)
            assert (
                bound["raw_verdict"]["coverage_critiques"]
                and bound["raw_verdict"]["prose_findings"]
            )
        else:
            assert final["state"] == "uncertain"
            with pytest.raises(
                ReportBindingError, match="no_completed_check_after_current_response"
            ):
                current_check(sealed, final, materials, routes=ROUTES)
        # No retry, fifth Messages request or invented current checker allowed.
        if scenario != "repair":
            with pytest.raises(AdmissionError):
                await adapter.advance(job["id"])
            assert len(handler.contacts) == 8
    finally:
        export_rows(store, "v18-pipeline-" + mode + "-" + scenario)


async def test_successor_dependencies_are_bound_without_growing_legacy_producer_metadata(
    store, monkeypatch
):
    from dataclasses import replace

    inputs = setup(store, monkeypatch, "learn")
    files = inputs.settings["qualification_producer"]["code"]
    assert "workspace/assistance_consistency_contract.py" not in files
    assert "workspace/assistance_consistency_checks.py" not in files
    assert inputs.settings["consistency_producer"] == adapter_module.consistency_producer()
    for fault in ["absent", "wrong"]:
        settings = dict(inputs.settings)
        if fault == "absent":
            settings.pop("consistency_producer")
        else:
            settings["consistency_producer"] = {}
        with pytest.raises(AdmissionError, match="consistency_producer_drift"):
            adapter_module.D5Adapter(
                store,
                "d5-run",
                replace(inputs, settings=settings),
                transport=httpx.MockTransport(lambda _: None),
            )
    monkeypatch.setattr(adapter_module, "consistency_producer", lambda: {})
    with pytest.raises(AdmissionError, match="consistency_producer_drift"):
        adapter_module.D5Adapter(
            store, "d5-run", inputs, transport=httpx.MockTransport(lambda _: None)
        )


@pytest.mark.parametrize(
    "intent,scenario,disposition",
    [
        ("application_assessment", "clear", "full_abstention"),
        ("comparison", "comparison_notes", "comparison_abstention"),
    ],
)
async def test_both_abstention_forms_complete_mandatory_check_without_answer_credit(
    store, monkeypatch, intent, scenario, disposition
):
    from src.workspace.d5_report_binding import current_check
    from src.workspace.d5_results import QualificationResults

    inputs = setup(store, monkeypatch, "research", intent=intent)
    handler = Transport(scenario)
    adapter = adapter_module.D5Adapter(
        store, "d5-run", inputs, transport=httpx.MockTransport(handler)
    )
    try:
        job = adapter.start(inputs.settings["d5_request_id"])
        await adapter.advance(job["id"])
        await adapter.advance(job["id"])
        final = adapter.snapshot(job["id"])
        assert final["state"] == "ready" and len(handler.contacts) == 4
        assert [step["stage"] for step in final["steps"]] == ["draft", "check"]
        _, materials = adapter._context()
        bound = current_check(dict(inputs.settings["d5_request"]), final, materials, routes=ROUTES)
        assert bound["binding"]["completed_checker_after_current_response"] is True
        result = QualificationResults(store).snapshot("d5-run", job["id"])
        output = result["assistance_output"]
        assert output["response_disposition"] == disposition
        assert (
            not output["coverage_complete"] and not output["request_outcome"]["full_answer_credit"]
        )
        assert all(not part["answer_claim_ids"] for part in output["request_coverage"])
        assert result["factual_acceptance"] is False and result["human_review"] is None
        if disposition == "full_abstention":
            assert not output["claims"] and len(output["context_requests"]) == 4
        else:
            assert output["claims"] and output["comparison_unanswered"]
    finally:
        export_rows(store, "v18-mandatory-check-" + disposition)
