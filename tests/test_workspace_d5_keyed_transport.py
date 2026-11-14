"""Synthetic transport controls; zero provider contacts or scientific credit."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest

from src.workspace import assistance_keyed_checks as checks
from src.workspace import assistance_keyed_contract as draft
from src.workspace.admission import _digest
from src.workspace.assistance_coverage import QUALIFICATIONS, validate_review
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE, ROUTES
from src.workspace.d5_keyed_transport import (
    CapacityCampaignTransport,
    KeyedCampaignTransport,
    draft_payload,
)
from src.workspace.d5_operations import verdict_text
from tests.test_workspace_d5_capacity_transport import context as old_context
from tests.test_workspace_d5_capacity_transport import purpose

pytestmark = pytest.mark.unit


def context(mode="research", *, intent="answer"):
    value = old_context(mode, intent=intent)
    value["sealed_request"]["schema_revision"] = draft.REVISION
    value["sealed_request"]["task_policy"]["revision"] = draft.REVISION
    return value


def check_context(value, payload):
    sealed = value["sealed_request"]
    envelope, _ = draft.normalize(
        payload, list(sealed["units"]), purpose(value), sealed["task_policy"]
    )
    rendered = draft.render(payload, list(sealed["units"]), purpose(value), sealed["task_policy"])
    claims = envelope["response"].get("claims", [])
    return {
        **deepcopy(value),
        "phase": "check",
        "role": "checker",
        "draft": {"claims": claims},
        "claim_inputs": [
            {"claim_id": row["claim_id"], "input_digest": "sha256:" + _digest(row)}
            for row in claims
        ],
        "coverage_inputs": [
            {"part_id": row["id"], "input_digest": "sha256:" + _digest(row)}
            for row in rendered["request_coverage"]
        ],
        "declared_coverage": rendered["request_coverage"],
        "unscored_prose": {
            key: rendered[key] for key in ("gaps", "questions", "proposal", "abstention")
        },
    }


def wire(value):
    route = ROUTES["check_recheck_probe" if value["phase"] == "check" else "draft_repair"]
    if value["phase"] == "check":
        schema = checks.schemas(value, probe="coverage_inputs" not in value)["wire"]
    else:
        sealed = value["sealed_request"]
        schema = draft.schemas(list(sealed["units"]), purpose(value), sealed["task_policy"])["wire"]
    return {
        "model": route["model"],
        "messages": [{"role": "user", "content": json.dumps(value)}],
        "max_tokens": route["output_tokens"],
        "thinking": route["thinking"],
        "output_config": {
            "effort": route["effort"],
            "format": {"type": "json_schema", "schema": schema},
        },
    }


def send(transport, body, *, count=False):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), trust_env=False
        ) as client:
            return await client.post(
                "https://offline.invalid/v1/messages" + ("/count_tokens" if count else ""),
                json=body,
            )

    return asyncio.run(run())


def output(response):
    return json.loads(verdict_text(response.json()))


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("scenario", ["normal", "long_narratives"])
def test_maximum_drafts_and_checkers_follow_actual_wire_schema_and_preserve_sources(mode, scenario):
    ctx = context(mode)
    original = deepcopy(ctx)
    transport = CapacityCampaignTransport("synthetic-max", scenario=scenario)
    body = wire(ctx)
    payload = output(send(transport, body))
    sealed = ctx["sealed_request"]
    envelope, coverage = draft.normalize(
        payload, list(sealed["units"]), purpose(ctx), sealed["task_policy"]
    )
    assert len(payload["response"]["claims"]) == CLAIMS_BY_MODE[mode]
    assert len(coverage) == 8
    for row in envelope["response"]["claims"]:
        assert sealed["units"][row["handles"][0]]["quote"] in row["text"]
        assert len(row["text"]) > 500
    checked = check_context(ctx, payload)
    checker_body = wire(checked)
    response = send(transport, checker_body)
    value = output(response)
    normalized = checks.normalize(value, checked)
    parsed = checks.checks_model().model_validate(normalized)
    validate_review(parsed, checked)
    parsed.validate_locations(checked["unscored_prose"])
    assert len(parsed.checks) == CLAIMS_BY_MODE[mode]
    assert len(parsed.coverage_checks) == 8
    assert all(
        row.qualifications.model_dump() == dict.fromkeys(QUALIFICATIONS, "retained")
        for row in parsed.claim_quality
    )
    assert all(len(row.reason) > 512 for row in parsed.checks)
    assert response.json()["content"][0]["type"] == "thinking"
    assert response.json()["model"] == checker_body["model"]
    assert response.json()["usage"] == {"input_tokens": 100, "output_tokens": 100}
    assert all(row["errors"] == [] for row in transport.schema_validations)
    assert json.loads(transport.request_bodies[0]) == body
    assert ctx == original
    assert len({response.json()["id"], send(transport, checker_body).json()["id"]}) == 2


@pytest.mark.parametrize("intent", ["answer", "comparison", "application_assessment"])
def test_all_four_stages_and_full_abstention_use_real_repair_gate(intent):
    ctx = context(intent=intent)
    transport = KeyedCampaignTransport("synthetic-four", repair_all=True)
    payload = output(send(transport, wire(ctx)))
    first_context = check_context(ctx, payload)
    first = output(send(transport, wire(first_context)))
    assert first["coverage_checks"]["p1"]["decision"] == "uncertain"
    repair = {
        **deepcopy(ctx),
        "phase": "repair",
        "previous_prose_review": checks.normalize(first, first_context),
    }
    repaired = output(send(transport, wire(repair)))
    final_context = check_context(ctx, repaired)
    final = output(send(transport, wire(final_context)))
    assert [row["decision"] for row in final["coverage_checks"].values()] == [
        row["status"] for row in final_context["declared_coverage"]
    ]
    assert transport.checks == 2 and len(transport.contacts) == 4
    assert not any(row["errors"] for row in transport.schema_validations)
    if intent == "application_assessment":
        assert "claims" not in payload["response"]
        assert all(
            row["gap_reasons"] == ["application_context"]
            for row in payload["response"]["coverage"].values()
        )


def test_development_learn_first_check_only_requires_repair():
    ctx = context("learn")
    checked = check_context(ctx, draft_payload(ctx))
    transport = KeyedCampaignTransport("campaign-dev-learn")
    assert (
        output(send(transport, wire(checked)))["coverage_checks"]["p1"]["decision"] == "uncertain"
    )
    assert output(send(transport, wire(checked)))["coverage_checks"]["p1"]["decision"] == "answered"


def test_five_opaque_probe_controls_remain_support_only_and_synthetic():
    from src.workspace.d5_campaign_packet import PROBE_CONTROLS

    texts = [
        PROBE_CONTROLS[0][1],
        PROBE_CONTROLS[0][2],
        PROBE_CONTROLS[1][1],
        PROBE_CONTROLS[1][2],
        PROBE_CONTROLS[2][1],
    ]
    claims = [{"claim_id": f"blind-{i}:opaque", "text": text} for i, text in enumerate(texts)]
    ctx = {
        "phase": "check",
        "draft": {"claims": claims},
        "claim_inputs": [
            {"claim_id": row["claim_id"], "input_digest": "sha256:" + _digest(row)}
            for row in claims
        ],
    }
    transport = KeyedCampaignTransport("synthetic-probe")
    value = output(send(transport, wire(ctx)))
    normalized = checks.normalize(value, ctx, probe=True)
    assert [row["decision"] for row in normalized["checks"]] == [
        "supported",
        "unsupported",
        "supported",
        "unsupported",
        "supported",
    ]
    assert set(value) == {"revision", "checks", "prose_review", "prose_findings"}
    assert set(value["checks"]) == {row["claim_id"] for row in claims}


@pytest.mark.parametrize(
    "scenario",
    ["wrong_digest", "missing_judgment", "unknown_key", "duplicate_json_key", "truncated_checker"],
)
def test_deliberately_invalid_checker_responses_are_retained_at_boundary(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = KeyedCampaignTransport("synthetic-invalid", scenario=scenario)
    response = send(transport, wire(checked))
    assert transport.schema_validations[-1]["errors"]
    text = verdict_text(response.json())
    if scenario in {"duplicate_json_key", "truncated_checker"}:
        if scenario == "duplicate_json_key":
            assert text.count('"revision"') == 2
        else:
            assert response.json()["stop_reason"] == "max_tokens"
            with pytest.raises(ValueError):
                json.loads(text)
    else:
        value = json.loads(text)
        with pytest.raises(ValueError):
            checks.normalize(value, checked)
        if scenario == "wrong_digest":
            assert "input_digest" in next(iter(value["claim_reviews"].values()))


@pytest.mark.parametrize("scenario", ["truncated", "duplicate_json_key"])
def test_archived_draft_failures_stay_incomplete_or_duplicate(scenario):
    transport = KeyedCampaignTransport("synthetic-archive", scenario=scenario)
    response = send(transport, wire(context()))
    text = verdict_text(response.json())
    assert transport.schema_validations[-1]["errors"]
    if scenario == "truncated":
        assert response.json()["stop_reason"] == "max_tokens"
        with pytest.raises(ValueError):
            json.loads(text)
    else:
        assert text.count('"p1"') >= 2
        assert "synthetic_duplicate_json_key:p1" in transport.schema_validations[-1]["errors"][0]


@pytest.mark.parametrize("scenario", ["max_tokens", "checker_max_tokens"])
def test_complete_json_at_max_tokens_remains_an_incomplete_provider_stop(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = KeyedCampaignTransport("synthetic-stop", scenario=scenario)
    response = send(transport, wire(checked))
    checks.normalize(output(response), checked)
    assert response.json()["stop_reason"] == "max_tokens"
    assert transport.schema_validations[-1]["errors"] == []


@pytest.mark.parametrize("scenario", ["reject", "unsupported"])
def test_negative_support_is_preserved(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    value = output(
        send(KeyedCampaignTransport("synthetic-reject", scenario=scenario), wire(checked))
    )
    assert all(row["decision"] == "unsupported" for row in value["claim_reviews"].values())


@pytest.mark.parametrize(
    "scenario", ["prose", "same_location_findings", "different_findings_same_location"]
)
def test_same_location_independent_findings_keep_full_location_validation(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    value = output(
        send(KeyedCampaignTransport("synthetic-prose", scenario=scenario), wire(checked))
    )
    normalized = checks.normalize(value, checked)
    parsed = checks.checks_model().model_validate(normalized)
    parsed.validate_locations(checked["unscored_prose"])
    assert len(parsed.prose_findings) == (1 if scenario == "prose" else 2)
    assert len({(row.field, row.index) for row in parsed.prose_findings}) == 1


@pytest.mark.parametrize("scenario", ["uncertain", "timeout"])
def test_uncertainty_has_no_fabricated_response(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = KeyedCampaignTransport("synthetic-uncertainty", scenario=scenario)
    with pytest.raises(httpx.ReadTimeout, match="no provider contact"):
        send(transport, wire(checked))
    assert transport.checks == 0


@pytest.mark.parametrize("scenario", ["provider_error", "http400", "grammar_error"])
def test_archived_grammar_failure_is_http400_without_fabricated_usage(scenario):
    result = send(KeyedCampaignTransport("synthetic-error", scenario=scenario), wire(context()))
    assert result.status_code == 400
    assert "compiled grammar is too large" in result.json()["error"]["message"]
    assert "usage" not in result.json()


@pytest.mark.parametrize(
    "scenario,expected", [("normal", 100), ("oversized", 32001), ("byte_count", None)]
)
def test_counts_are_explicitly_synthetic_receipts(scenario, expected):
    transport = KeyedCampaignTransport("synthetic-count", scenario=scenario)
    body = wire(context())
    response = send(transport, body, count=True)
    assert response.json()["input_tokens"] == (
        max(1, len(transport.request_bodies[0]) // 3) if expected is None else expected
    )
    assert transport.contacts == [("/v1/messages/count_tokens", _digest(body))]
    assert transport.checks == 0


def test_request_schema_mismatch_is_not_hidden_by_fixture_validation():
    body = wire(context())
    body["output_config"]["format"]["schema"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    with pytest.raises(ValueError, match="synthetic_output_request_schema_mismatch"):
        send(KeyedCampaignTransport("synthetic-schema-mismatch"), body)


def test_unknown_scenario_endpoint_and_old_revision_are_rejected():
    with pytest.raises(ValueError, match="unknown_keyed_transport_scenario"):
        KeyedCampaignTransport("synthetic", scenario="invented")
    with pytest.raises(ValueError, match="requires_v16_contract"):
        draft_payload(old_context())
    with pytest.raises(ValueError, match="keyed_transport_endpoint_required"):
        asyncio.run(
            KeyedCampaignTransport("synthetic")(
                httpx.Request("POST", "https://offline.invalid/wrong", json={})
            )
        )


def test_duplicate_response_identity_scenario_remains_detectable():
    transport = KeyedCampaignTransport("synthetic-duplicate", scenario="duplicate_response_id")
    body = wire(context())
    assert send(transport, body).json()["id"] == send(transport, body).json()["id"]
