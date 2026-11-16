"""Offline synthetic v19 campaign transport over the real SDK request shape.

No HTTP client, credential or provider is used. Every output and count is a new
software fixture, not replayed provider text or independent semantic evidence.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from src.workspace import assistance_comparison_contract as codec
from src.workspace import assistance_consistency_checks as checks
from src.workspace import assistance_keyed_checks as probe_checks
from src.workspace.admission import _digest
from src.workspace.d5_capacity_transport import _reason
from src.workspace.d5_keyed_transport import probe_payload
from src.workspace.provider_schema_compat import guard


def _purpose(context: dict[str, Any]) -> str:
    sealed = context["sealed_request"]
    return sealed.get("response_purpose") or (
        "research_comparison"
        if sealed["task_policy"]["mode"] == "research"
        and len({r["work_id"] for r in sealed["units"].values()}) >= 2
        else "single_paper"
    )


def draft_payload(context: dict[str, Any], *, long: bool = True) -> dict[str, Any]:
    """Generate source-attributed findings; coverage is the only part mapping."""
    sealed = context["sealed_request"]
    policy, units = sealed["task_policy"], sealed["units"]
    if not codec.enabled(policy):
        raise ValueError("comparison_transport_requires_v19_encoding")
    if policy["allowed_dispositions"] == ["full_abstention"]:
        response: dict[str, Any] = {
            "disposition": "full_abstention",
            "reason": "application_context_required"
            if policy["missing_context"]
            else "insufficient_selected_evidence",
            "next_action": "request_context",
            "coverage": {
                p["id"]: {
                    "status": "lacks_evidence",
                    "gap_reasons": [
                        "application_context" if policy["missing_context"] else "source_scope"
                    ],
                }
                for p in policy["requested_parts"]
            },
        }
        if policy["missing_context"]:
            response["context_requests"] = dict.fromkeys(policy["missing_context"], "required")
    else:
        by_work: dict[str, str] = {}
        for handle, reference in sorted(units.items()):
            by_work.setdefault(reference["work_id"], handle)
        selected = list(by_work.values())[:2]
        if not selected:
            raise ValueError("comparison_transport_selected_units_required")
        claims = []
        for handle in selected:
            reference = units[handle]
            claims.append(
                {
                    "text": "The selected source reports: "
                    + reference["quote"]
                    + (
                        " This synthetic attribution preserves the supplied study scope and qualifiers; the excerpt alone does not establish unreported implementation settings, a common benchmark, causal validity or applicability to an unrelated system."
                        if long
                        else ""
                    ),
                    "handles": [handle],
                    "required_scope": reference["scope"],
                }
            )
        compare = any(p["kind"] == "comparison" for p in policy["requested_parts"])
        comparative = compare and len(selected) == 2 and "answer" in policy["allowed_dispositions"]
        if comparative:
            first, second = selected
            claims.append(
                {
                    "text": "The selected descriptions differ in their reported scope: the first states "
                    + units[first]["quote"]
                    + " The second states "
                    + units[second]["quote"]
                    + " This is a qualitative comparison of the cited descriptions. These excerpts do not establish compatible performance measurements or a shared evaluation protocol, so no quantitative superiority follows from this synthetic contrast.",
                    "handles": [first, second],
                    "required_scope": units[first]["scope"],
                }
            )
        ids = [f"c{i + 1}" for i in range(len(claims))]
        coverage = {}
        for part in policy["requested_parts"]:
            comparison = part["kind"] == "comparison"
            answers = [ids[-1]] if comparison and comparative else [] if comparison else ids
            coverage[part["id"]] = {
                "status": "partial" if answers else "lacks_evidence",
                "gap_reasons": ["methods", "protocol"] if answers else ["common_evaluation"],
                "answer_claim_ids": answers,
                "context_claim_ids": [key for key in ids if key not in answers],
            }
        response = {
            "disposition": "answer",
            "claims": claims,
            "background_claims": ids[: len(selected)],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [
                {"intent": "methods", "context_claim_ids": ids[:1], "premise_claim_ids": []}
            ],
            "proposal": "inspect_methods",
            "coverage": coverage,
        }
    if context.get("phase") == "repair" and response.get("claims"):
        response["claims"][0]["text"] += (
            " This fresh synthetic repair preserves the remaining methods and protocol gaps explicitly. Mutable source text is never inferred. User-facing usefulness remains unmeasured."
        )
    value = {"response": response}
    codec.response_model(list(units), _purpose(context), policy).model_validate(value)
    return value


def checker_payload(
    context: dict[str, Any], *, negative: bool = False, long: bool = True
) -> dict[str, Any]:
    """Supply complete synthetic judgments bound to this exact response context."""
    reason = _reason(negative=negative, long=long)
    declared = {p["id"]: p["status"] for p in context["declared_coverage"]}
    locations = probe_checks.prose_locations(context)
    value = {
        "revision": checks.REVISION,
        "claim_reviews": {
            c["claim_id"]: {
                "decision": "supported",
                "reason": reason,
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(
                    ["study_scope", "comparator", "metric_definition", "conditions"], "retained"
                ),
            }
            for c in context["claim_inputs"]
        },
        "coverage_checks": {
            p["part_id"]: {
                "decision": declared[p["part_id"]],
                "reason": reason,
                "critiques": [
                    "Synthetic request-detail critique requiring the bounded repair. " + reason
                ]
                if negative and i == 0
                else [],
            }
            for i, p in enumerate(context["coverage_inputs"])
        },
        "prose_findings": {key: [] for key in locations},
        "prose_uncertainties": {key: [] for key in locations},
        "priority_review": "respected",
    }
    checks.normalize(value, context)
    return value


class ComparisonCampaignTransport:
    """MockTransport handler; all counts and usage are synthetic, unmeasured."""

    def __init__(self, key: str, *, repair_all: bool = False, scenario: str = "normal"):
        if scenario not in {
            "normal",
            "long_narratives",
            "uncertain",
            "timeout",
            "provider_error",
            "http400",
            "grammar_error",
            "truncated",
            "truncated_checker",
            "checker_max_tokens",
            "oversized",
            "final_negative",
        }:
            raise ValueError("unknown_comparison_transport_scenario")
        self.key, self.repair_all, self.scenario = key, repair_all, scenario
        self.checks = 0
        self.contacts: list[tuple[str, str]] = []
        self.request_bodies: list[bytes] = []
        self.schema_validations: list[dict[str, Any]] = []
        self.outputs: list[dict[str, Any]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.contacts.append((request.url.path, _digest(body)))
        self.request_bodies.append(bytes(request.content))
        if request.url.path.endswith("/messages/count_tokens"):
            guard(body)
            return httpx.Response(
                200, json={"input_tokens": 32001 if self.scenario == "oversized" else 100}
            )
        if not request.url.path.endswith("/messages"):
            raise ValueError("comparison_transport_endpoint_required")
        guard(body)
        context = json.loads(body["messages"][0]["content"])
        phase = context["phase"]
        if self.scenario in {"uncertain", "timeout"} and phase == "check":
            raise httpx.ReadTimeout(
                "Synthetic offline uncertainty; no provider contact", request=request
            )
        if self.scenario in {"provider_error", "http400", "grammar_error"}:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Synthetic offline schema rejection; no provider contact",
                    },
                },
            )
        if phase == "check":
            self.checks += 1
            probe = "coverage_inputs" not in context
            payload = (
                probe_payload(context, long=True)
                if probe
                else checker_payload(context, negative=self.repair_all and self.checks == 1)
            )
            if not probe and self.scenario == "final_negative" and self.checks >= 2:
                if payload["claim_reviews"]:
                    first = next(iter(payload["claim_reviews"]))
                    payload["claim_reviews"][first]["decision"] = "unsupported"
                    payload["claim_reviews"][first]["reason"] = (
                        "Synthetic final whole-claim support rejection after complete repair/recheck; resolving citations do not establish semantic support. "
                        + _reason(negative=True, long=True)
                    )
                else:
                    first = next(iter(payload["coverage_checks"]))
                    payload["coverage_checks"][first]["critiques"] = [
                        "Synthetic final coverage rejection after complete recheck."
                    ]
        else:
            payload = draft_payload(context)
        schema = body["output_config"]["format"]["schema"]
        errors = [e.message for e in Draft202012Validator(schema).iter_errors(payload)]
        self.schema_validations.append(
            {
                "request_digest": _digest(body),
                "phase": phase,
                "errors": errors,
                "response_utf8_bytes": len(json.dumps(payload, ensure_ascii=False).encode()),
            }
        )
        if errors:
            raise ValueError("synthetic_output_request_schema_mismatch:" + ";".join(errors))
        self.outputs.append(deepcopy(payload))
        text, stop = json.dumps(payload, ensure_ascii=False), "end_turn"
        if (
            self.scenario == "truncated"
            and phase == "draft"
            or self.scenario == "truncated_checker"
            and phase == "check"
        ):
            text, stop = '{"response":', "max_tokens"
        if self.scenario == "checker_max_tokens" and phase == "check":
            stop = "max_tokens"
        content = [{"type": "text", "text": text}]
        if body["model"] == "claude-opus-5-5":
            content.insert(
                0,
                {
                    "type": "thinking",
                    "thinking": "Synthetic reasoning block; no model execution or semantic judgment.",
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "synthetic-v19-" + self.key + "-" + str(len(self.contacts)),
                "type": "message",
                "model": body["model"],
                "stop_reason": stop,
                "content": content,
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )


def assert_paired_contacts(
    adapter: dict[str, Any], transport: ComparisonCampaignTransport, messages: int
) -> None:
    """Check each real SDK count body and immutable production contact journal."""
    contacts = adapter["contacts"]
    assert len(contacts) == len(transport.contacts) == len(transport.request_bodies) == 2 * messages
    for index in range(messages):
        offset = index * 2
        count, generation = contacts[offset : offset + 2]
        count_body, message_body = [
            json.loads(x) for x in transport.request_bodies[offset : offset + 2]
        ]
        assert transport.contacts[offset][0].endswith("/messages/count_tokens")
        assert transport.contacts[offset + 1][0].endswith("/messages")
        assert count_body == {
            k: v for k, v in message_body.items() if k not in {"max_tokens", "temperature"}
        }
        assert count["body"] == count_body and generation["body"] == message_body
        assert count["ordinal"] == offset and generation["ordinal"] == offset + 1
        assert count["request_digest"] == _digest(count_body)
        assert (
            count["generation_request_digest"]
            == generation["request_digest"]
            == generation["generation_request_digest"]
            == _digest(message_body)
        )
        assert count["stage"] == generation["stage"]
        assert count["state"] == generation["state"] == "completed"
        assert count["response"] == {"input_tokens": 100}


CapacityCampaignTransport = ComparisonCampaignTransport
