"""Causal current-response bindings from the existing immutable contact journal."""

from __future__ import annotations

import json
from typing import Any

from src.workspace.admission import _digest
from src.workspace.d5_adapter import checker_context
from src.workspace.d5_operations import ROUTES, verdict_text, wire
from src.workspace.provider_adapter import response_output


class ReportBindingError(ValueError):
    """A missing or inconsistent journal cannot supply current judgments."""


def json_object(text: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ReportBindingError("duplicate_json_key")
            value[key] = item
        return value

    def nonfinite(_: str) -> Any:
        raise ReportBindingError("nonfinite_json")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(value, dict):
        raise ReportBindingError("json_object_required")
    return value


def message_output(contact: dict[str, Any]) -> dict[str, Any]:
    body, response = contact["body"], contact["response"]
    if body["model"] == "claude-opus-5-5":
        response = {**response, "content": [{"type": "text", "text": verdict_text(response)}]}
    parsed = response_output(response, body["model"])
    if json_object(response["content"][0]["text"]) != parsed:
        raise ReportBindingError("response_parse_mismatch")
    return parsed


def current_check(
    sealed: dict[str, Any], snapshot: dict[str, Any], materials: Any
) -> dict[str, Any]:
    """Bind one completed check after the latest validated workflow response.

    Request hashes are not unique stage identities: an unchanged repair may
    legitimately produce the same check body twice. Ordinals and step order
    distinguish those contacts; whole responses and canonical contexts bind
    their claims, coverage, section references and rendered prose.
    """
    contacts = snapshot.get("contacts", [])
    steps = snapshot.get("steps", [])
    messages: list[dict[str, Any]] = []
    for ordinal, contact in enumerate(contacts):
        if (
            not isinstance(contact, dict)
            or type(contact.get("ordinal")) is not int
            or contact["ordinal"] != ordinal
            or contact.get("endpoint") not in {"messages", "messages/count_tokens"}
            or not isinstance(contact.get("body"), dict)
            or contact.get("request_digest") != _digest(contact["body"])
        ):
            raise ReportBindingError("malformed_or_out_of_order_contact_journal")
        if contact["endpoint"] == "messages" and contact.get("state") == "completed":
            count = contacts[ordinal - 1] if ordinal else {}
            if (
                count.get("endpoint") != "messages/count_tokens"
                or count.get("state") != "completed"
                or not count.get("response")
                or count.get("generation_request_digest") != contact["request_digest"]
                or contact.get("generation_request_digest") != contact["request_digest"]
                or count.get("stage") != contact.get("stage")
                or count.get("body")
                != {
                    k: v
                    for k, v in contact["body"].items()
                    if k not in {"max_tokens", "temperature"}
                }
            ):
                raise ReportBindingError("completed_message_without_bound_paired_count")
            messages.append(contact)
    stages = [step.get("stage") for step in steps]
    if (
        not stages
        or stages != ["draft", "check", "repair", "check"][: len(stages)]
        or len(steps) > 4
        or len(messages) != len(steps)
    ):
        raise ReportBindingError("completed_response_step_journal_mismatch")
    parsed_outputs = []
    for step, contact in zip(steps, messages, strict=True):
        parsed = message_output(contact)
        stored = {k: v for k, v in step["output"].items() if k != "grounding"}
        if (
            step.get("stage") != contact.get("stage")
            or step.get("request_digest") != contact["request_digest"]
            or stored != parsed
        ):
            raise ReportBindingError("response_step_or_request_binding_mismatch")
        parsed_outputs.append(parsed)
    selected = max(i for i, stage in enumerate(stages) if stage in {"draft", "repair"})
    producer = messages[selected]
    if any(
        c["endpoint"] == "messages"
        and c.get("stage") in {"draft", "repair"}
        and c["ordinal"] > producer["ordinal"]
        for c in contacts
    ):
        raise ReportBindingError("newer_workflow_response_unavailable")
    if selected + 1 == len(steps):
        raise ReportBindingError("no_completed_check_after_current_response")
    contact = messages[selected + 1]
    if contact["stage"] != "check" or contact["ordinal"] <= producer["ordinal"]:
        raise ReportBindingError("checker_does_not_follow_current_response")
    expected_wire = wire(checker_context(sealed, parsed_outputs[selected], materials), ROUTES)
    expected = json_object(expected_wire["messages"][0]["content"])
    if (
        contact["body"] != expected_wire
        or json_object(contact["body"]["messages"][0]["content"]) != expected
    ):
        raise ReportBindingError("checker_context_does_not_bind_current_response")
    return {
        "contact": contact,
        "context": expected,
        "raw_verdict": parsed_outputs[selected + 1],
        "binding": {
            "status": "bound",
            "current_response_digest": _digest(parsed_outputs[selected]),
            "current_response_ordinal": producer["ordinal"],
            "checker_ordinal": contact["ordinal"],
            "checker_request_digest": contact["request_digest"],
            "checked_context_digest": _digest(expected),
            "completed_checker_after_current_response": True,
        },
    }
