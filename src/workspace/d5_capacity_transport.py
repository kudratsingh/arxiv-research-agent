"""Mock-only v15 campaign responses for the unchanged protected execution path.

Counts, usage and every judgment are deliberately synthetic software controls.
Copied source passages and valid wire schemas establish no scientific quality,
provider compatibility, measured token capacity, or remote acceptance. This
module reads no credential and constructs no HTTP client or provider connection.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from src.workspace.admission import _digest
from src.workspace.assistance_capacity_contract import (
    REVISION,
    normalize_checks,
    response_model,
    validate_policy,
)
from src.workspace.assistance_coverage import QUALIFICATIONS
from src.workspace.d5_capacity_policy import CHECKS_REVISION, CLAIMS_BY_MODE, POLICY

_SCENARIOS = frozenset(
    {
        "normal",
        "long_narratives",
        "byte_count",
        "oversized",
        "uncertain",
        "timeout",
        "truncated",
        "max_tokens",
        "checker_max_tokens",
        "reject",
        "unsupported",
        "wrong_digest",
        "missing_judgment",
        "prose",
        "provider_error",
        "duplicate_response_id",
    }
)


def _reason(*, negative: bool = False, long: bool = False) -> str:
    lead = (
        "Synthetic negative software verdict: the requested scientific conclusion remains unsupported or uncertain in this controlled response. "
        if negative
        else "Synthetic positive software verdict: the fixture copies the supplied identity and preserves the configured judgment fields. "
    )
    detail = (
        "This does not establish semantic support, scientific correctness, calibrated uncertainty, or human qualification. "
        "A source's reported study scope, comparator, metric definition and conditions must still be assessed independently; "
        "citation resolution alone cannot certify the whole finding. Unicode/JSON controls: "
        'café, naïve, Δ, 条件, 🚀, a quoted "qualification", a backslash \\ and a line break\nremain part of this complete explanation. '
    )
    return lead + detail * (3 if long else 2)


def _claim_text(reference: dict[str, Any], index: int, *, long: bool) -> str:
    # Never shorten a retained quotation or invent a scientific measurement.
    # Repeated references deliberately exercise cardinality, not claim diversity.
    quote = reference["quote"]
    framing = (
        f"Synthetic offline claim {index}, attributed to the selected {reference['scope']} passage: {quote}\n"
        "The attribution retains the passage's own scope and qualifications, including conditional wording and reported comparators or metrics. "
        "Its quotation is preserved in full; the transport does not infer unreported methods, experimental settings, causal conclusions, "
        "cross-source compatibility or applicability to a new system. This duplicated software fixture is not an independently established scientific finding. "
        'Unicode/escaping control: café, Δ, 条件, 🚀, "quoted qualification" and \\.'
    )
    if long:
        framing += (
            " The complete selected wording above remains the only source content in this synthetic row; "
            "retaining it does not prove atomicity, material-qualification recall or whole-claim support."
        ) * 3
    return framing


def draft_payload(context: dict[str, Any], *, long: bool = False) -> dict[str, Any]:
    """Build new-contract wire data directly, without legacy fixture/model reuse."""
    sealed = context["sealed_request"]
    if sealed.get("schema_revision") != REVISION:
        raise ValueError("capacity_transport_requires_v15_contract")
    policy = sealed["task_policy"]
    validate_policy(policy)
    units = sealed["units"]
    if not units:
        raise ValueError("capacity_transport_selected_units_required")
    handles = sorted(units)
    first_by_work: dict[str, str] = {}
    for handle in handles:
        first_by_work.setdefault(units[handle]["work_id"], handle)
    ordered = list(first_by_work.values())
    ordered += [handle for handle in handles if handle not in ordered]
    purpose = (
        "research_comparison"
        if policy["mode"] == "research" and len(first_by_work) >= 2
        else "single_paper"
    )
    groups: dict[str, list[dict[str, Any]]] = {"lacks_evidence": []}
    if not policy["missing_context"]:
        groups["omitted"] = []
    if policy["allowed_dispositions"] == ["full_abstention"]:
        response: dict[str, Any] = {
            "disposition": "full_abstention",
            "reason": "application_context_required"
            if policy["missing_context"]
            else "insufficient_selected_evidence",
            "next_action": "request_context",
            "coverage": groups,
        }
        if policy["missing_context"]:
            response["context_requests"] = {key: "required" for key in policy["missing_context"]}
        for part in policy["requested_parts"]:
            groups["lacks_evidence"].append(
                {
                    "part_id": part["id"],
                    "gap": "application_context" if policy["missing_context"] else "source_scope",
                }
            )
    else:
        count = CLAIMS_BY_MODE[policy["mode"]]
        claims = []
        for index in range(1, count + 1):
            handle = ordered[(index - 1) % len(ordered)]
            reference = units[handle]
            claims.append(
                {
                    "claim_id": f"c{index}",
                    "text": _claim_text(reference, index, long=long),
                    "handles": [handle],
                    "required_scope": reference["scope"],
                }
            )
        ids = [claim["claim_id"] for claim in claims]
        disposition = (
            "answer" if "answer" in policy["allowed_dispositions"] else "comparison_abstention"
        )
        response = {
            "disposition": disposition,
            "claims": claims,
            "background_claims": ids,
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [{"intent": "investigate_claim", "claim_ids": [ids[-1]]}],
            "proposal": "inspect_scope",
            "coverage": groups,
        }
        comparisons = (
            policy["task_intent"] == "comparison"
            and disposition == "answer"
            and purpose == "research_comparison"
        )
        if purpose == "research_comparison":
            response.update(
                comparison_claims=["c1"] if comparisons else [],
                comparison_basis=["c1", "c2"] if comparisons else [],
            )
        groups["answered"] = []
        for index, part in enumerate(policy["requested_parts"]):
            if part["kind"] == "comparison" and not comparisons:
                groups["lacks_evidence"].append(
                    {
                        "part_id": part["id"],
                        "gap": "common_evaluation",
                        "context_claim_ids": ids if index == 0 else [],
                    }
                )
            else:
                answer_ids = ["c1"] if part["kind"] == "comparison" else ids
                groups["answered"].append(
                    {
                        "part_id": part["id"],
                        "answer_claim_ids": answer_ids,
                        "context_claim_ids": [key for key in ids if key not in answer_ids]
                        if index == 0
                        else [],
                    }
                )
    result = {"response": response}
    response_model(handles, purpose, policy).model_validate(result)
    return result


def checker_payload(
    context: dict[str, Any], *, negative: bool = False, reject: bool = False, long: bool = False
) -> dict[str, Any]:
    """Complete exact-digest synthetic judgments; negative verdicts remain real data."""
    reason = _reason(negative=negative or reject, long=long)
    declared = {row["id"]: row["status"] for row in context["declared_coverage"]}
    result = {
        "revision": CHECKS_REVISION,
        "claim_reviews": [
            {
                **row,
                "decision": "unsupported" if reject else "supported",
                "atomicity": "atomic",
                "qualifications": dict.fromkeys(QUALIFICATIONS, "retained"),
                "reason": reason,
            }
            for row in context["claim_inputs"]
        ],
        "coverage_checks": [
            {
                **row,
                "decision": "uncertain" if negative and index == 0 else declared[row["part_id"]],
                "reason": reason,
            }
            for index, row in enumerate(context["coverage_inputs"])
        ],
        "prose_review": "procedural_only",
        "prose_findings": [],
        "priority_review": "uncertain"
        if negative and not context["coverage_inputs"]
        else "respected",
    }
    normalize_checks(result)
    return result


def probe_payload(context: dict[str, Any], *, long: bool = False) -> dict[str, Any]:
    from src.workspace.d5_campaign_packet import PROBE_CONTROLS

    # Exact frozen text membership proves diagnostic plumbing only. It is not an
    # independent determination of whether the underlying claim is true.
    negatives = {negative for _, _, negative in PROBE_CONTROLS}
    texts = {claim["claim_id"]: claim["text"] for claim in context["draft"]["claims"]}
    return {
        "checks": [
            {
                **row,
                "decision": "unsupported" if texts[row["claim_id"]] in negatives else "supported",
                "reason": _reason(long=long),
            }
            for row in context["claim_inputs"]
        ],
        "prose_review": "procedural_only",
        "prose_findings": [],
    }


class CapacityCampaignTransport:
    """An httpx.MockTransport handler only; no credential or network client."""

    def __init__(self, key: str, *, repair_all: bool = False, scenario: str = "normal"):
        if scenario not in _SCENARIOS:
            raise ValueError("unknown_capacity_transport_scenario")
        self.key, self.repair_all, self.scenario = key, repair_all, scenario
        self.checks = 0
        self.contacts: list[tuple[str, str]] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
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
            raise ValueError("capacity_transport_endpoint_required")
        context = json.loads(body["messages"][0]["content"])
        if self.scenario in {"uncertain", "timeout"} and context["phase"] == "check":
            raise httpx.ReadTimeout(
                "Synthetic mock uncertainty; no provider contact", request=request
            )
        if self.scenario == "provider_error":
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Synthetic mock provider error",
                    },
                    "request_id": "synthetic-capacity-error-" + self.key,
                },
            )
        long = self.scenario == "long_narratives"
        if context["phase"] == "check":
            self.checks += 1
            if "coverage_inputs" in context:
                # Full abstention still has coverage rows, so an uncertain first
                # part exercises the same real repair gate as a factual draft.
                negative = (self.repair_all or self.key.endswith("dev-learn")) and self.checks == 1
                payload = checker_payload(
                    context,
                    negative=negative,
                    reject=self.scenario in {"reject", "unsupported"},
                    long=long,
                )
                if self.scenario == "wrong_digest" and payload["claim_reviews"]:
                    payload["claim_reviews"][0]["input_digest"] = "sha256:" + "0" * 64
                if self.scenario == "missing_judgment" and payload["claim_reviews"]:
                    payload["claim_reviews"].pop()
                if self.scenario == "prose":
                    payload.update(
                        prose_review="unscored_factual_content",
                        prose_findings=[
                            {
                                "field": "gaps",
                                "index": 0,
                                "reason": _reason(negative=True, long=long),
                            }
                        ],
                    )
            else:
                payload = probe_payload(context, long=long)
        else:
            payload = draft_payload(context, long=long)
        result = {
            "id": "synthetic-capacity-"
            + self.key
            + ("" if self.scenario == "duplicate_response_id" else "-" + str(len(self.contacts))),
            "model": body["model"],
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        }
        if body["model"] == "claude-opus-5-5":
            result["content"].insert(
                0,
                {
                    "type": "thinking",
                    "thinking": "Synthetic reasoning block; no remote model execution or semantic judgment occurred.",
                },
            )
        if self.scenario == "truncated" and context["phase"] == "draft":
            result.update(
                stop_reason="max_tokens", content=[{"type": "text", "text": '{"response":'}]
            )
        if self.scenario in {"max_tokens", "checker_max_tokens"} and context["phase"] == "check":
            result["stop_reason"] = "max_tokens"
        return httpx.Response(200, json=result)
