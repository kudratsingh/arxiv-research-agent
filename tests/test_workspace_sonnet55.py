"""Sonnet5.5 migration contracts; only isolated Postgres and MockTransport."""

from dataclasses import replace
from decimal import Decimal

import httpx
import pytest

from src.llm_models import capabilities_for
from src.workspace import qualification_run
from src.workspace.admission import AdmissionError, _digest
from tests import test_workspace_measurement as measurement
from tests import test_workspace_provider_adapter as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


@pytest.mark.parametrize("kind,cap", [("summary", 1200), ("deep_dive", 2400)])
def test_sonnet55_seals_compatible_shape_and_verified_rates(store, kind, cap):
    inputs = support.prepared(store, kind)
    settings = inputs.settings
    adapter = support.p.QualificationAdapter(
        store, "a", inputs,
        transport=httpx.MockTransport(lambda _: pytest.fail("no contact")),
    )
    body = adapter.request()["body"]
    assert inputs.model_id == body["model"] == "claude-sonnet-5-5"
    assert inputs.prompt_revision == "workspace-qualification-adapter-v8-single-selected-evidence"
    assert body["thinking"] == {"type": "between_tools"}
    assert body["output_config"]["effort"] == settings["effort"] == "medium"
    assert body["max_tokens"] == cap
    assert not {"temperature", "top_p", "top_k", "tools", "tool_choice"} & body.keys()
    assert settings["temperature"] is settings["checker_temperature"] is None
    assert settings["price_estimate_usd_per_million"] == {
        "input": "2", "output": "10", "verified_at": "2026-11-04"
    }
    caps = capabilities_for(inputs.model_id)
    assert caps.structured_outputs and not caps.sampling_params
    assert caps.supports_effort("medium")
    # Same pre-existing ceilings, conservative one-repair/four-call bound.
    bound = (Decimal(settings["input_tokens"]) * 2 + Decimal(cap) * 10) * 4 / 1_000_000
    assert bound * Decimal("1.25") <= Decimal("0.40" if kind == "deep_dive" else "0.25")


@pytest.mark.parametrize("change", [{"thinking": "adaptive"}, {"effort": "high"}])
def test_changed_thinking_effort_refused_as_sealed_drift(store, change):
    inputs = support.prepared(store)
    changed = replace(inputs, settings={**inputs.settings, **change})
    with pytest.raises(AdmissionError, match="sealed_execution_drift"):
        support.p.QualificationAdapter(
            store, "a", changed,
            transport=httpx.MockTransport(lambda _: pytest.fail("drift must refuse before contact")),
        )


def test_v2_and_old_model_approval_cannot_authorize_new_requests(store):
    packet = measurement.fixture(store)
    with pytest.raises(AdmissionError, match="bounded_v8_single_evidence_packet_required"):
        qualification_run.bound_jobs(store, "a", {**packet, "revision": "workspace-qualification-packet-v2"})
    _, inputs = qualification_run.bound_jobs(store, "a", packet)[0]
    support.admission.policy(
        store, model_ids=["claude-sonnet-4-6"], purpose="workspace-qualification",
        request_digest=_digest(inputs.snapshot()), request_id="one",
        transport_mode="mock", everyday_generation=False,
    )
    adapter = support.p.QualificationAdapter(
        store, "a", inputs,
        transport=httpx.MockTransport(lambda _: pytest.fail("old approval must refuse before contact")),
    )
    with pytest.raises(AdmissionError, match="outside_approved_scope"):
        adapter.start("one", "0.25")
    assert _digest(inputs.snapshot()) == packet["jobs"][0]["input_digest"]
