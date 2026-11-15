"""Offline guard for actual SDK-transformed strict request schemas.

Published ceilings are not a remote compiler specification. Count both physical
schema declarations and conservatively expanded reference uses; never assume a
shared definition is a free grammar parameter. No provider/client I/O occurs.
"""

from __future__ import annotations

from typing import Any

from src.workspace.admission import AdmissionError, _digest

REVISION = "anthropic-structured-schema-compat-v1"
DOCUMENTATION = "https://platform.claude.com/docs/en/build-with-claude/structured-outputs"
POLICY: dict[str, Any] = {
    "revision": REVISION,
    "documented_limits": {"union_parameters": 16, "optional_parameters": 24, "strict_tools": 20},
    "planning_limits": {"expanded_union_nodes": 12, "optional_parameters": 16},
    "references": "Count each reachable use, including mutually exclusive alternatives; reject cycles/external references. This is conservative analysis, not the provider compiler's undocumented counting algorithm.",
    "remaining_uncertainty": "Internal grammar-size and compilation-time limits can reject schemas below every explicit ceiling. Local validation, counts and schema byte size do not prove remote acceptance.",
}


class ProviderSchemaError(AdmissionError):
    """Refuse a prospective request before count or Messages dispatch."""


def _union(value: dict[str, Any]) -> bool:
    return "anyOf" in value or isinstance(value.get("type"), list) and len(value["type"]) > 1


def _target(root: dict[str, Any], ref: Any) -> dict[str, Any]:
    if not isinstance(ref, str) or not ref.startswith("#/"):
        raise ProviderSchemaError("provider_schema_external_or_invalid_reference")
    target: Any = root
    try:
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise ProviderSchemaError("provider_schema_unresolved_reference") from exc
    if not isinstance(target, dict):
        raise ProviderSchemaError("provider_schema_reference_must_be_object")
    return target


def _resolved_union(
    root: dict[str, Any], node: dict[str, Any], chain: tuple[str, ...] = ()
) -> bool:
    if _union(node):
        return True
    if "$ref" not in node:
        return False
    ref = node["$ref"]
    if ref in chain:
        raise ProviderSchemaError("provider_schema_recursive_reference")
    return _resolved_union(root, _target(root, ref), (*chain, ref))


def schema_metrics(schema: dict[str, Any]) -> dict[str, Any]:
    """Separate anyOf nodes from union-valued object properties and optionals."""
    if not isinstance(schema, dict):
        raise ProviderSchemaError("provider_schema_object_required")
    result: dict[str, Any] = {
        "schema_digest": _digest(schema),
        "direct_union_properties": 0,
        "resolved_union_properties": 0,
        "anyof_nodes": 0,
        "type_array_nodes": 0,
        "optional_properties": 0,
        "expanded_union_properties": 0,
        "expanded_union_nodes": 0,
        "expanded_optional_properties": 0,
        "reference_uses": 0,
    }
    visited = 0

    def visit(node: Any, chain: tuple[str, ...], *, expand: bool) -> None:
        nonlocal visited
        visited += 1
        if visited > 100000:
            raise ProviderSchemaError("provider_schema_analysis_bound_exceeded")
        if isinstance(node, list):
            for item in node:
                visit(item, chain, expand=expand)
            return
        if not isinstance(node, dict):
            return
        if "oneOf" in node:
            raise ProviderSchemaError("provider_schema_unsupported_oneof")
        if "allOf" in node and any(isinstance(x, dict) and "$ref" in x for x in node["allOf"]):
            raise ProviderSchemaError("provider_schema_allof_reference_unsupported")
        if "$ref" in node:
            target = _target(schema, node["$ref"])
            if expand:
                ref = node["$ref"]
                if ref in chain:
                    raise ProviderSchemaError("provider_schema_recursive_reference")
                result["reference_uses"] += 1
                visit(target, (*chain, ref), expand=True)
                node = {k: v for k, v in node.items() if k != "$ref"}
        if _union(node):
            if expand:
                result["expanded_union_nodes"] += 1
            else:
                result["anyof_nodes"] += int("anyOf" in node)
                result["type_array_nodes"] += int(
                    isinstance(node.get("type"), list) and len(node["type"]) > 1
                )
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            raise ProviderSchemaError("provider_schema_properties_object_required")
        required = node.get("required", [])
        if not isinstance(required, list):
            raise ProviderSchemaError("provider_schema_required_array_required")
        for name, value in properties.items():
            if not isinstance(value, dict):
                raise ProviderSchemaError("provider_schema_property_object_required")
            if expand:
                result["expanded_union_properties"] += int(_resolved_union(schema, value))
                result["expanded_optional_properties"] += int(name not in required)
            else:
                result["direct_union_properties"] += int(_union(value))
                result["resolved_union_properties"] += int(_resolved_union(schema, value))
                result["optional_properties"] += int(name not in required)
        for key, value in node.items():
            if expand and key in {"$defs", "$def", "definitions"}:
                continue
            visit(value, chain, expand=expand)

    visit(schema, (), expand=False)
    visit(schema, (), expand=True)
    return result


def inspect_request(body: dict[str, Any]) -> dict[str, Any]:
    """Aggregate output schema plus every strict tool, as the docs require."""
    output = body.get("output_config", {}).get("format")
    schemas: list[tuple[str, dict[str, Any]]] = []
    if output is not None:
        if (
            not isinstance(output, dict)
            or output.get("type") != "json_schema"
            or not isinstance(output.get("schema"), dict)
        ):
            raise ProviderSchemaError("provider_schema_output_format_required")
        schemas.append(("output", output["schema"]))
    strict_tools = 0
    for index, tool in enumerate(body.get("tools", [])):
        if not isinstance(tool, dict):
            raise ProviderSchemaError("provider_schema_tool_object_required")
        if tool.get("strict") is not True:
            continue
        strict_tools += 1
        if not isinstance(tool.get("input_schema"), dict):
            raise ProviderSchemaError("provider_schema_strict_tool_schema_required")
        schemas.append((f"strict_tool_{index}", tool["input_schema"]))
    if not schemas:
        raise ProviderSchemaError("provider_schema_strict_schema_required")
    reports = [{"location": name, **schema_metrics(schema)} for name, schema in schemas]
    unions = max(
        sum(r[k] for r in reports)
        for k in (
            "direct_union_properties",
            "resolved_union_properties",
            "expanded_union_properties",
        )
    )
    optional = max(
        sum(r[k] for r in reports) for k in ("optional_properties", "expanded_optional_properties")
    )
    nodes = sum(r["expanded_union_nodes"] for r in reports)
    limits = POLICY["documented_limits"]
    planned = POLICY["planning_limits"]
    documented = (
        unions <= limits["union_parameters"]
        and optional <= limits["optional_parameters"]
        and strict_tools <= limits["strict_tools"]
    )
    planning = (
        nodes <= planned["expanded_union_nodes"] and optional <= planned["optional_parameters"]
    )
    return {
        "revision": REVISION,
        "request_digest": _digest(body),
        "schemas": reports,
        "union_parameters_conservative": unions,
        "optional_parameters_conservative": optional,
        "expanded_union_nodes": nodes,
        "strict_tools": strict_tools,
        "documented_limits_pass": documented,
        "planning_headroom_pass": planning,
        "remote_compiler_acceptance": "UNMEASURED",
    }


def guard(body: dict[str, Any], *, headroom: bool = True) -> dict[str, Any]:
    report = inspect_request(body)
    if not report["documented_limits_pass"]:
        raise ProviderSchemaError("provider_schema_documented_limit_exceeded")
    if headroom and not report["planning_headroom_pass"]:
        raise ProviderSchemaError("provider_schema_planning_headroom_exceeded")
    return report
