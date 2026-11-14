"""Mock-only v16 production-shaped transport; never a provider or gold judge.

All counts/usage/judgments are synthetic software controls. Source quotations and
frozen probe text exercise plumbing only. The received request is retained before
any synthetic fixture conversion; no client, credentials or network are used.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from src.workspace import assistance_capacity_contract as prior
from src.workspace import assistance_keyed_checks as checks
from src.workspace import assistance_keyed_contract as draft
from src.workspace import d5_capacity_transport as fixtures
from src.workspace.admission import _digest
from src.workspace.d5_capacity_policy import POLICY

_SCENARIOS = fixtures._SCENARIOS | {
    "unknown_key",
    "duplicate_json_key",
    "truncated_checker",
    "http400",
    "same_location_findings",
    "different_findings_same_location",
    "grammar_error",
}
_INVALID_WIRE = {
    "wrong_digest",
    "missing_judgment",
    "unknown_key",
    "duplicate_json_key",
    "truncated_checker",
    "truncated",
}


def _purpose(context: dict[str, Any]) -> str:
    sealed = context["sealed_request"]
    return (
        "research_comparison"
        if sealed["task_policy"]["mode"] == "research"
        and len({row["work_id"] for row in sealed["units"].values()}) >= 2
        else "single_paper"
    )


def draft_payload(context: dict[str, Any], *, long: bool = False) -> dict[str, Any]:
    """Adapt a freshly generated synthetic v15 fixture, never a live response."""
    sealed = context["sealed_request"]
    if sealed.get("schema_revision") != draft.REVISION:
        raise ValueError("keyed_transport_requires_v16_contract")
    synthetic = deepcopy(context)
    synthetic["sealed_request"]["schema_revision"] = prior.REVISION
    synthetic["sealed_request"]["task_policy"] = draft.prior_policy(sealed["task_policy"])
    old = fixtures.draft_payload(synthetic, long=long)
    envelope, coverage = prior.normalize(
        old, list(sealed["units"]), _purpose(context), synthetic["sealed_request"]["task_policy"]
    )
    result = draft.wire_payload(envelope, coverage, sealed["task_policy"])
    draft.response_model(
        list(sealed["units"]), _purpose(context), sealed["task_policy"]
    ).model_validate(result)
    return result


def checker_payload(
    context: dict[str, Any], *, negative: bool = False, reject: bool = False, long: bool = False
) -> dict[str, Any]:
    value = fixtures.checker_payload(context, negative=negative, reject=reject, long=long)
    return checks.compact(prior.normalize_checks(value), context)


def probe_payload(context: dict[str, Any], *, long: bool = False) -> dict[str, Any]:
    return checks.compact(fixtures.probe_payload(context, long=long), context, probe=True)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("synthetic_duplicate_json_key:" + key)
        result[key] = value
    return result


class KeyedCampaignTransport:
    """Use only as an httpx.MockTransport handler; usage100 is not measured."""

    def __init__(self, key: str, *, repair_all: bool = False, scenario: str = "normal"):
        if scenario not in _SCENARIOS:
            raise ValueError("unknown_keyed_transport_scenario")
        self.key, self.repair_all, self.scenario = key, repair_all, scenario
        self.checks = 0
        self.contacts: list[tuple[str, str]] = []
        self.request_bodies: list[bytes] = []
        self.schema_validations: list[dict[str, Any]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.request_bodies.append(bytes(request.content))
        body = json.loads(request.content)
        self.contacts.append((request.url.path, _digest(body)))
        if request.url.path.endswith("/messages/count_tokens"):
            count = (
                POLICY["paired_input_tokens_fit"] + 1
                if self.scenario == "oversized"
                else max(1, len(request.content) // 3)
                if self.scenario == "byte_count"
                else 100
            )
            return httpx.Response(200, json={"input_tokens": count})
        if not request.url.path.endswith("/messages"):
            raise ValueError("keyed_transport_endpoint_required")
        context = json.loads(body["messages"][0]["content"])
        phase = context["phase"]
        if self.scenario in {"uncertain", "timeout"} and phase == "check":
            raise httpx.ReadTimeout(
                "Synthetic mock uncertainty; no provider contact", request=request
            )
        if self.scenario in {"provider_error", "http400", "grammar_error"}:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Synthetic mock compiled grammar is too large; no provider contact",
                    },
                    "request_id": "synthetic-keyed-error-" + self.key,
                },
            )
        long = self.scenario == "long_narratives"
        if phase == "check":
            self.checks += 1
            probe = "coverage_inputs" not in context
            if probe:
                payload = probe_payload(context, long=long)
            else:
                negative = (self.repair_all or self.key.endswith("dev-learn")) and self.checks == 1
                payload = checker_payload(
                    context,
                    negative=negative,
                    reject=self.scenario in {"reject", "unsupported"},
                    long=long,
                )
            collection = "checks" if probe else "claim_reviews"
            judgments = payload[collection] or payload.get("coverage_checks", {})
            if self.scenario == "wrong_digest" and judgments:
                # v16 never echoes a digest: injecting one is explicitly forbidden.
                judgments[next(iter(judgments))]["input_digest"] = "sha256:" + "0" * 64
            if self.scenario == "missing_judgment" and judgments:
                judgments.pop(next(iter(judgments)))
            if self.scenario == "unknown_key":
                judgments["unknown-synthetic-id"] = deepcopy(next(iter(judgments.values())))
            if self.scenario in {
                "prose",
                "same_location_findings",
                "different_findings_same_location",
            }:
                payload.update(
                    prose_review="unscored_factual_content",
                    prose_findings=[
                        {
                            "field": "gaps",
                            "index": 0,
                            "reason": fixtures._reason(negative=True, long=long),
                        }
                    ],
                )
                if self.scenario != "prose":
                    payload["prose_findings"].append(
                        {
                            "field": "gaps",
                            "index": 0,
                            "reason": "Independent synthetic scope finding at this same existing location.",
                        }
                    )
        else:
            payload = draft_payload(context, long=long)
        text = json.dumps(payload, ensure_ascii=False)
        stop = "end_turn"
        if self.scenario == "duplicate_json_key":
            if phase != "check":
                # Reproduce duplicate part identity without pretending it is a map.
                coverage = payload["response"]["coverage"]
                key = next(iter(coverage))
                insertion = (
                    json.dumps(key) + ":" + json.dumps(coverage[key], ensure_ascii=False) + ","
                )
                text = text.replace('"coverage": {', '"coverage": {' + insertion, 1)
            else:
                text = '{"revision":' + json.dumps(checks.REVISION) + "," + text[1:]
        if (self.scenario == "truncated" and phase == "draft") or (
            self.scenario == "truncated_checker" and phase == "check"
        ):
            text, stop = '{"response":' if phase == "draft" else '{"claim_reviews":', "max_tokens"
        if self.scenario in {"max_tokens", "checker_max_tokens"} and phase == "check":
            stop = "max_tokens"
        # Inspect the exact schema supplied by this actual request. Deliberate
        # negative controls are returned unchanged and their failures retained.
        schema = body["output_config"]["format"]["schema"]
        try:
            parsed = json.loads(text, object_pairs_hook=_unique_object)
            errors = [error.message for error in Draft202012Validator(schema).iter_errors(parsed)]
        except ValueError as exc:
            errors = [str(exc)]
        self.schema_validations.append(
            {
                "request_digest": _digest(body),
                "phase": phase,
                "scenario": self.scenario,
                "errors": errors,
            }
        )
        if errors and self.scenario not in _INVALID_WIRE:
            raise ValueError("synthetic_output_request_schema_mismatch:" + ";".join(errors))
        result = {
            "id": "synthetic-keyed-"
            + self.key
            + ("" if self.scenario == "duplicate_response_id" else "-" + str(len(self.contacts))),
            "model": body["model"],
            "stop_reason": stop,
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        }
        if body["model"] == "claude-opus-5-5":
            result["content"].insert(
                0,
                {
                    "type": "thinking",
                    "thinking": "Synthetic reasoning block; no model execution or semantic judgment occurred.",
                },
            )
        return httpx.Response(200, json=result)


# Match the existing mock runner import interface during prospective integration.
CapacityCampaignTransport = KeyedCampaignTransport
