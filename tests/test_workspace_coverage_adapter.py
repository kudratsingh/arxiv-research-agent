"""New policy through production admission, transport, durable results; synthetic only."""

import json

import httpx
import pytest
from jsonschema import validate

from src.workspace.admission import AdmissionError
from src.workspace.assistance_coverage import COVERAGE_REVISION, decorate_fixture, fixture_checks
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.d5_adapter import D5Adapter
from src.workspace.d5_operations import ROUTES
from src.workspace.d5_results import QualificationResults
from tests import test_workspace_d5_adapter as support
from tests.test_workspace_task_assistance import archived_source
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL, SAFETY, response

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc, workspace_pg = support.workspace_pg_proc, support.workspace_pg
pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


class Transport:
    def __init__(self, case, defect=None, persistent=False):
        self.case, self.defect, self.persistent = case, defect, persistent
        self.calls, self.checks = [], 0

    async def __call__(self, req):
        body = json.loads(req.content)
        self.calls.append((req.url.path, body))
        if req.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        ctx = json.loads(body["messages"][0]["content"])
        if ctx["phase"] == "check":
            self.checks += 1
            data = fixture_checks(
                {
                    "checks": [
                        {
                            "claim_id": c["claim_id"],
                            "input_digest": c["input_digest"],
                            "decision": "supported",
                            "reason": "Synthetic test verdict.",
                        }
                        for c in ctx["claim_inputs"]
                    ],
                    "prose_review": "procedural_only",
                    "prose_findings": [],
                },
                ctx,
            )
            if self.defect and (self.persistent or self.checks == 1):
                if self.defect == "bundle":
                    data["claim_quality"][0]["atomicity"] = "bundled"
                elif self.defect == "qualification":
                    data["claim_quality"][0]["qualifications"]["metric_definition"] = "lost"
                elif self.defect == "coverage":
                    data["coverage_checks"][0]["decision"] = "uncertain"
                elif self.defect == "stale":
                    data["coverage_checks"][0]["input_digest"] = "wrong"
                elif self.defect == "missing":
                    data["claim_quality"] = []
                elif self.defect == "unsupported":
                    data["checks"][0]["decision"] = "unsupported"
                elif self.defect == "prose":
                    data["prose_review"] = "unscored_factual_content"
                    data["prose_findings"] = [
                        {"field": "proposal", "index": None, "reason": "Synthetic factual premise"}
                    ]
        else:
            data = decorate_fixture(response(self.case), ctx["sealed_request"]["task_policy"])
        validate(data, body["output_config"]["format"]["schema"])
        return httpx.Response(
            200,
            json={
                "id": f"synthetic-{len(self.calls)}",
                "model": body["model"],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 100},
                "content": [{"type": "text", "text": json.dumps(data)}],
            },
        )


def runtime(store, case, transport):
    def setup(store):
        service, value = archived_source(case)(store)
        return service, value.model_copy(
            update={"task_context": CoverageTaskContext(intent=value.task_context.intent)}
        )

    inputs = support.setup(
        store,
        mode=ARCHIVE["cases"][case]["mode"],
        routes=ROUTES,
        source_setup=setup,
        repair_located_prose=True,
    )
    return D5Adapter(store, "d5-run", inputs, transport=httpx.MockTransport(transport)), inputs


@pytest.mark.parametrize("case", [NORMAL, RETRIEVAL, SAFETY])
async def test_production_adapter_coverage_and_durable_rendering(store, case):
    t = Transport(case)
    a, inputs = runtime(store, case, t)
    ctx = json.loads(a.request()["body"]["messages"][0]["content"])
    assert ctx["sealed_request"]["schema_revision"] == COVERAGE_REVISION
    assert (
        ctx["sealed_request"]["task_policy"]["requested_parts"][0]["request"]
        == ARCHIVE["cases"][case]["question"]
    )
    job = a.start(inputs.settings["d5_request_id"])
    for _ in range(2):
        job = await a.advance(job["id"])
    assert job["state"] == "ready"
    check = json.loads(t.calls[-1][1]["messages"][0]["content"])
    assert check["review_evidence"] == inputs.settings["d5_request"]["units"]
    assert len(check["coverage_inputs"]) == 1
    snapshot = QualificationResults(store).snapshot("d5-run", job["id"])
    assert snapshot["assistance_output"]["coverage_complete"] is False
    assert snapshot["request_quality"]["priority_review"] == "respected"
    assert snapshot["source_binding_intact"] and snapshot["human_review"] is None
    assert snapshot["workflow_usd"] == snapshot["checker_usd"] == "0"
    assert len(t.calls) == 4


@pytest.mark.parametrize("defect", ["bundle", "qualification", "coverage", "unsupported", "prose"])
async def test_first_quality_failure_uses_existing_single_repair(store, defect):
    t = Transport(NORMAL, defect)
    a, inputs = runtime(store, NORMAL, t)
    job = a.start(inputs.settings["d5_request_id"])
    for _ in range(4):
        job = await a.advance(job["id"])
    assert job["state"] == "ready"
    assert len(t.calls) == 8 and t.checks == 2
    repair = json.loads(t.calls[4][1]["messages"][0]["content"])
    assert repair["phase"] == "repair"
    if defect in ("bundle", "qualification", "coverage"):
        assert "claim_quality" in repair["previous_prose_review"]
        assert len(repair["previous_declared_coverage"]) == 1


@pytest.mark.parametrize(
    "defect", ["bundle", "qualification", "coverage", "unsupported", "prose", "missing", "stale"]
)
async def test_unresolved_and_unbound_quality_cannot_pass(store, defect):
    t = Transport(NORMAL, defect, persistent=True)
    a, inputs = runtime(store, NORMAL, t)
    job = a.start(inputs.settings["d5_request_id"])
    with pytest.raises((AdmissionError, ValueError)):
        for _ in range(4):
            job = await a.advance(job["id"])
    assert a.snapshot(job["id"])["state"] == "failed"
    assert len(t.calls) == (4 if defect in ("missing", "stale") else 8)
