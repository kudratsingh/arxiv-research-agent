"""Mock-only production-shaped response controls, never scientific acceptance."""

import asyncio
import json
from copy import deepcopy

import httpx
import pytest
from anthropic import transform_schema
from jsonschema import Draft202012Validator

from src.workspace import assistance_capacity_contract as contract
from src.workspace.admission import _digest
from src.workspace.assistance_coverage import validate_review
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.d5_capacity_policy import CLAIMS_BY_MODE, MAX_NORMALIZED_CHECK_BYTES, ROUTES
from src.workspace.d5_capacity_transport import CapacityCampaignTransport, draft_payload
from src.workspace.d5_operations import verdict_text
from tests.test_workspace_task_policy import ARCHIVE, NORMAL, RETRIEVAL

pytestmark = pytest.mark.unit


def context(mode="research", *, parts=8, intent="answer", unit_count=12):
    case = ARCHIVE["cases"][NORMAL if mode == "learn" else RETRIEVAL]
    references = list(case["units"].values())
    # Alias exact retained references only for schema/cardinality controls. This
    # does not create independent evidence or qualify a claim as supported.
    units = {f"u{i}": references[(i - 1) % len(references)] for i in range(1, unit_count + 1)}
    pol = contract.seal_policy(
        CoverageTaskContext.model_validate(
            {
                "intent": intent,
                "requested_parts": [
                    {
                        "id": f"p{i}",
                        "request": f"Request part {i}",
                        "kind": "comparison" if intent == "comparison" else "answer",
                    }
                    for i in range(1, parts + 1)
                ],
            }
        ),
        mode,
        len({u["work_id"] for u in units.values()}),
        "Task",
    )
    return {
        "phase": "draft",
        "role": "workflow",
        "sealed_request": {
            "schema_revision": contract.REVISION,
            "assistance": {"mode": mode},
            "units": units,
            "task_policy": pol,
        },
    }


def purpose(value):
    sealed = value["sealed_request"]
    return (
        "research_comparison"
        if sealed["task_policy"]["mode"] == "research"
        and len({u["work_id"] for u in sealed["units"].values()}) >= 2
        else "single_paper"
    )


def check_context(value, draft):
    sealed = value["sealed_request"]
    rendered = contract.render(draft, list(sealed["units"]), purpose(value), sealed["task_policy"])
    return {
        **deepcopy(value),
        "phase": "check",
        "role": "checker",
        "draft": {"claims": draft["response"].get("claims", [])},
        "claim_inputs": [
            {"claim_id": claim["claim_id"], "input_digest": "sha256:" + _digest(claim)}
            for claim in draft["response"].get("claims", [])
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


def wire(value, *, probe=False):
    selected = ROUTES["check_recheck_probe" if value["phase"] == "check" else "draft_repair"]
    if value["phase"] == "check":
        schema = (
            transform_schema(contract.probe_checks_model())
            if probe
            else contract.check_schemas()["wire"]
        )
    else:
        sealed = value["sealed_request"]
        schema = contract.schemas(list(sealed["units"]), purpose(value), sealed["task_policy"])[
            "wire"
        ]
    return {
        "model": selected["model"],
        "messages": [{"role": "user", "content": json.dumps(value)}],
        "thinking": selected["thinking"],
        "max_tokens": selected["output_tokens"],
        "output_config": {
            "effort": selected["effort"],
            "format": {"type": "json_schema", "schema": schema},
        },
    }


def send(transport, body, *, count=False):
    request = httpx.Request(
        "POST",
        "https://offline.invalid/v1/messages" + ("/count_tokens" if count else ""),
        json=body,
    )
    return asyncio.run(transport(request))


def output(response):
    raw = response.json()
    return json.loads(
        verdict_text(raw) if raw["model"] == "claude-opus-5-5" else raw["content"][0]["text"]
    )


@pytest.mark.parametrize("mode", ["learn", "research"])
@pytest.mark.parametrize("scenario", ["normal", "long_narratives"])
def test_maximum_complete_drafts_preserve_sources_and_pass_both_exact_schemas(mode, scenario):
    ctx = context(mode)
    transport = CapacityCampaignTransport("synthetic-max", scenario=scenario)
    body = wire(ctx)
    raw = send(transport, body).json()
    value = output(httpx.Response(200, json=raw))
    sealed = ctx["sealed_request"]
    for schema in contract.schemas(
        list(sealed["units"]), purpose(ctx), sealed["task_policy"]
    ).values():
        Draft202012Validator(schema).validate(value)
    assert raw["model"] == body["model"] and raw["stop_reason"] == "end_turn"
    assert len(value["response"]["claims"]) == CLAIMS_BY_MODE[mode]
    assert len(sealed["units"]) == 12
    assert all(len(c["text"]) > 500 for c in value["response"]["claims"])
    for claim in value["response"]["claims"]:
        assert sealed["units"][claim["handles"][0]]["quote"] in claim["text"]
    assert "Synthetic offline claim" in value["response"]["claims"][0]["text"]


@pytest.mark.parametrize("mode", ["learn", "research"])
def test_complete_checkers_retain_long_reasons_and_exact_digests_above_old_8kb(mode):
    ctx = context(mode)
    draft = draft_payload(ctx)
    checked = check_context(ctx, draft)
    transport = CapacityCampaignTransport("synthetic-long", scenario="long_narratives")
    body = wire(checked)
    raw = send(transport, body)
    value = output(raw)
    for schema in contract.check_schemas().values():
        Draft202012Validator(schema).validate(value)
    normalized = contract.normalize_checks(value)
    assert len(json.dumps(normalized).encode()) > 8000
    assert len(json.dumps(normalized).encode()) < MAX_NORMALIZED_CHECK_BYTES
    assert len(value["claim_reviews"]) == CLAIMS_BY_MODE[mode]
    assert len(value["coverage_checks"]) == 8
    checks = contract.checks_model().model_validate(normalized)
    validate_review(checks, checked)
    checks.validate_locations(checked["unscored_prose"])
    assert [c["input_digest"] for c in value["claim_reviews"]] == [
        c["input_digest"] for c in checked["claim_inputs"]
    ]
    for source, support, quality in zip(
        value["claim_reviews"], normalized["checks"], normalized["claim_quality"], strict=True
    ):
        assert 512 < len(source["reason"]) <= 1500
        assert source["reason"] == support["reason"] == quality["reason"]
        assert "🚀" in support["reason"] and "\\" in support["reason"] and "\n" in support["reason"]
    assert raw.json()["content"][0]["type"] == "thinking"


@pytest.mark.parametrize("intent", ["answer", "comparison", "application_assessment"])
def test_four_stages_use_negative_first_check_then_complete_repair_and_recheck(intent):
    ctx = context(intent=intent)
    transport = CapacityCampaignTransport("synthetic-all-repairs", repair_all=True)
    draft = output(send(transport, wire(ctx)))
    first_ctx = check_context(ctx, draft)
    first = output(send(transport, wire(first_ctx)))
    assert first["coverage_checks"][0]["decision"] == "uncertain"
    repair_ctx = {
        **deepcopy(ctx),
        "phase": "repair",
        "previous_prose_review": contract.normalize_checks(first),
    }
    repaired = output(send(transport, wire(repair_ctx)))
    final_ctx = check_context(ctx, repaired)
    final = output(send(transport, wire(final_ctx)))
    assert [row["decision"] for row in final["coverage_checks"]] == [
        row["status"] for row in final_ctx["declared_coverage"]
    ]
    assert final["priority_review"] == "respected"
    assert transport.checks == 2 and len(transport.contacts) == 4
    if intent == "application_assessment":
        assert draft["response"]["disposition"] == "full_abstention"
        assert "claims" not in draft["response"]
        assert all(
            row["gap"] == "application_context"
            for row in draft["response"]["coverage"]["lacks_evidence"]
        )
    if intent == "comparison":
        r = repaired["response"]
        by_id = {c["claim_id"]: c for c in r["claims"]}
        works = {
            ctx["sealed_request"]["units"][h]["work_id"]
            for key in r["comparison_basis"]
            for h in by_id[key]["handles"]
        }
        assert len(works) >= 2


def test_development_default_repair_only_affects_first_check():
    ctx = context("learn")
    transport = CapacityCampaignTransport("campaign-dev-learn")
    checked = check_context(ctx, draft_payload(ctx))
    first = output(send(transport, wire(checked)))
    second = output(send(transport, wire(checked)))
    assert first["coverage_checks"][0]["decision"] == "uncertain"
    assert second["coverage_checks"][0]["decision"] == "answered"


def test_support_only_probe_preserves_planned_frozen_positive_and_negative_controls():
    from src.workspace.d5_campaign_packet import PROBE_CONTROLS

    claims = [
        {"claim_id": f"c{i + 1}", "text": text} for i, text in enumerate(PROBE_CONTROLS[0][1:])
    ]
    ctx = {
        "phase": "check",
        "role": "checker",
        "draft": {"claims": claims},
        "claim_inputs": [
            {"claim_id": c["claim_id"], "input_digest": "sha256:" + _digest(c)} for c in claims
        ],
        "unscored_prose": {},
    }
    transport = CapacityCampaignTransport("synthetic-probe", repair_all=True)
    value = output(send(transport, wire(ctx, probe=True)))
    Draft202012Validator(transform_schema(contract.probe_checks_model())).validate(value)
    parsed = contract.probe_checks_model().model_validate(value)
    assert [row.decision for row in parsed.checks] == ["supported", "unsupported"]
    assert [row.input_digest for row in parsed.checks] == [
        row["input_digest"] for row in ctx["claim_inputs"]
    ]
    assert "coverage_checks" not in value and "claim_quality" not in value
    assert all(len(row.reason) > 512 for row in parsed.checks)


@pytest.mark.parametrize("scenario,expected", [("normal", 100), ("oversized", 32001)])
def test_paired_count_receipts_are_explicitly_synthetic_and_exact(scenario, expected):
    transport = CapacityCampaignTransport("synthetic-count", scenario=scenario)
    body = wire(context())
    counted = {key: value for key, value in body.items() if key != "max_tokens"}
    assert send(transport, counted, count=True).json() == {"input_tokens": expected}
    assert transport.contacts == [("/v1/messages/count_tokens", _digest(counted))]
    assert transport.checks == 0


def test_byte_based_count_scenario_is_a_heuristic_and_uses_exact_received_bytes():
    transport = CapacityCampaignTransport("synthetic-byte-count", scenario="byte_count")
    body = wire(context())
    request = httpx.Request("POST", "https://offline.invalid/v1/messages/count_tokens", json=body)
    response = asyncio.run(transport(request))
    assert response.json()["input_tokens"] == max(1, len(request.content) // 3)


@pytest.mark.parametrize("scenario", ["truncated", "max_tokens", "checker_max_tokens"])
def test_incomplete_provider_controls_remain_explicitly_incomplete(scenario):
    transport = CapacityCampaignTransport("synthetic-truncation", scenario=scenario)
    ctx = context()
    if scenario != "truncated":
        ctx = check_context(ctx, draft_payload(ctx))
    raw = send(transport, wire(ctx)).json()
    assert raw["stop_reason"] == "max_tokens"
    if scenario == "truncated":
        with pytest.raises(ValueError):
            json.loads(raw["content"][0]["text"])
    else:
        assert json.loads(verdict_text(raw))["claim_reviews"]


@pytest.mark.parametrize("scenario", ["reject", "unsupported"])
def test_negative_complete_support_verdicts_remain_negative(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = CapacityCampaignTransport("synthetic-negative", scenario=scenario)
    value = output(send(transport, wire(checked)))
    assert all(row["decision"] == "unsupported" for row in value["claim_reviews"])
    contract.normalize_checks(value)


@pytest.mark.parametrize("scenario", ["wrong_digest", "missing_judgment"])
def test_bad_bindings_are_not_repaired_by_transport(scenario):
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = CapacityCampaignTransport("synthetic-bad-binding", scenario=scenario)
    value = contract.normalize_checks(output(send(transport, wire(checked))))
    with pytest.raises(ValueError, match="binding_mismatch"):
        validate_review(contract.checks_model().model_validate(value), checked)


def test_uncertainty_is_a_timeout_exception_and_never_fabricates_a_complete_response():
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    transport = CapacityCampaignTransport("synthetic-timeout", scenario="uncertain")
    with pytest.raises(httpx.ReadTimeout, match="no provider contact"):
        send(transport, wire(checked))
    assert len(transport.contacts) == 1 and transport.checks == 0


def test_mock_client_uses_only_local_handler_and_copies_count_receipt_body():
    transport = CapacityCampaignTransport("synthetic-client")
    body = wire(context("learn"))

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(transport), trust_env=False
        ) as client:
            counted = {k: v for k, v in body.items() if k != "max_tokens"}
            count = await client.post(
                "https://offline.invalid/v1/messages/count_tokens", json=counted
            )
            generated = await client.post("https://offline.invalid/v1/messages", json=body)
        return count, generated

    count, generated = asyncio.run(run())
    assert count.json() == {"input_tokens": 100}
    assert len(output(generated)["response"]["claims"]) == 8
    assert len(transport.contacts) == 2


def test_complete_negative_prose_finding_keeps_exact_existing_location():
    ctx = context()
    checked = check_context(ctx, draft_payload(ctx))
    value = output(
        send(CapacityCampaignTransport("synthetic-prose", scenario="prose"), wire(checked))
    )
    normalized = contract.normalize_checks(value)
    parsed = contract.checks_model().model_validate(normalized)
    parsed.validate_locations(checked["unscored_prose"])
    assert parsed.prose_review == "unscored_factual_content"
    assert parsed.prose_findings[0].field == "gaps" and parsed.prose_findings[0].index == 0
    assert len(parsed.prose_findings[0].reason) > 512


def test_synthetic_http_error_retains_provider_shaped_error_without_usage():
    result = send(
        CapacityCampaignTransport("synthetic-error", scenario="provider_error"), wire(context())
    )
    assert result.status_code == 400
    assert result.json()["error"]["type"] == "invalid_request_error"
    assert "usage" not in result.json()


def test_transport_refuses_unknown_scenario_and_legacy_draft_revision():
    with pytest.raises(ValueError, match="unknown_capacity_transport_scenario"):
        CapacityCampaignTransport("synthetic-unknown", scenario="silently_accept")
    ctx = context()
    ctx["sealed_request"]["schema_revision"] = "workspace-assistance-compact-coverage-v14"
    with pytest.raises(ValueError, match="requires_v15_contract"):
        draft_payload(ctx)
