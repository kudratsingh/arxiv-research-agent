"""Actual sealed builder instructions agree with required v16 wire fields."""

import json
from copy import deepcopy

import pytest

from src.workspace import assistance_keyed_checks as checks
from src.workspace.d5_capacity_wire import CHECK_SYSTEM, build_wire
from src.workspace.programme_amendments import effective_limits
from tests.test_workspace_d5_keyed_transport import check_context, context, draft_payload

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("probe", [False, True])
def test_required_revision_and_named_verdicts_match_actual_builder(mode, probe):
    initial = context(mode)
    ctx = check_context(initial, draft_payload(initial))
    if probe:
        ctx["operation"] = "probe"
        ctx.pop("coverage_inputs")
        ctx["unscored_prose"] = {}
    ctx["output_schema"] = checks.schemas(ctx, probe=probe)["wire"]
    actual = build_wire(ctx)
    sent = json.loads(actual["messages"][0]["content"])
    rule = sent["checker_wire_rule"]
    assert "max_prose_findings" not in sent["capacity_policy"]
    assert sent["capacity_policy"]["keyed_prose_finding_capacity"] == checks.finding_capacity()
    assert sent["capacity_policy"]["keyed_prose_finding_capacity"]["aggregate_findings_limit"] is None
    assert sent["capacity_policy"]["checker_revision"] == checks.REVISION
    assert "fixed revision" in rule
    assert "No revision" not in rule
    assert "must not be echoed" in rule or "Do not echo" in rule
    assert "prose_findings" in rule
    assert "revision" in actual["output_config"]["format"]["schema"]["required"]
    if probe:
        assert "opaque probe key" in rule
        assert "claim slots" not in sent["identity_contract"]
    else:
        assert "claim_reviews" in rule and "coverage_checks" in rule
        assert "with their exact field/index" not in actual["system"]


def test_legacy_prompt_metadata_is_unchanged():
    initial = context("learn")
    ctx = check_context(initial, draft_payload(initial))
    legacy = deepcopy(ctx)
    legacy["sealed_request"]["schema_revision"] = "workspace-assistance-capacity-v15"
    legacy["output_schema"] = {"type": "object", "properties": {}, "additionalProperties": False}
    wire = build_wire(legacy)
    sent = json.loads(wire["messages"][0]["content"])
    assert wire["system"] == CHECK_SYSTEM
    assert "identity_contract" not in sent
    assert "part digest" in sent["checker_wire_rule"]
    assert sent["capacity_policy"]["max_prose_findings"] == 16
    assert "keyed_prose_finding_capacity" not in sent["capacity_policy"]


def test_current_continuation_policy_does_not_fall_back_to_expired_old_amendment(monkeypatch):
    limits = {"new_jobs": 64, "messages": 160, "counts": 200, "usd": "20", "concurrency": 1}
    calls = []

    def active(conn, program, digest):
        calls.append((conn, program, digest))
        return {"approved": True}, {"limits": limits}

    monkeypatch.setattr("src.workspace.d5_campaign_v16_extension.active", active)
    monkeypatch.setattr(
        "src.workspace.d5_campaign_v15_extension.active",
        lambda *_: pytest.fail("obsolete fallback"),
    )
    assert (
        effective_limits(
            "readonly-connection", "programme", required_proposal_digest="exact-proposal"
        )
        == limits
    )
    assert calls == [("readonly-connection", "programme", "exact-proposal")]
