"""Offline documented-limit controls; no remote compiler success is inferred."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.workspace.provider_schema_compat import (
    ProviderSchemaError,
    guard,
    inspect_request,
    schema_metrics,
)

pytestmark = pytest.mark.unit


def schema(count=0, *, optional=0, kind="anyof"):
    props = {
        f"u{i}": (
            {"anyOf": [{"type": "string"}, {"type": "null"}]}
            if kind == "anyof"
            else {"type": ["string", "null"]}
        )
        for i in range(count)
    }
    props.update({f"o{i}": {"type": "string"} for i in range(optional)})
    return {
        "type": "object",
        "properties": props,
        "required": [f"u{i}" for i in range(count)],
        "additionalProperties": False,
    }


def body(value=None):
    return {
        "output_config": {
            "format": {"type": "json_schema", "schema": schema() if value is None else value}
        }
    }


@pytest.mark.parametrize("kind", ["anyof", "type_array"])
def test_documented_union_boundary_and_independent_planning_headroom(kind):
    report = guard(body(schema(16, kind=kind)), headroom=False)
    assert report["union_parameters_conservative"] == 16
    assert report["documented_limits_pass"] and not report["planning_headroom_pass"]
    with pytest.raises(ProviderSchemaError, match="planning_headroom"):
        guard(body(schema(13, kind=kind)))
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(body(schema(17, kind=kind)), headroom=False)
    assert guard(body(schema(12, kind=kind)))["planning_headroom_pass"]


def test_nullable_is_not_optional_and_optional_boundaries():
    report = guard(body(schema(1, optional=24)), headroom=False)
    assert report["union_parameters_conservative"] == 1
    assert report["optional_parameters_conservative"] == 24
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(body(schema(optional=25)), headroom=False)
    with pytest.raises(ProviderSchemaError, match="planning_headroom"):
        guard(body(schema(optional=17)))
    assert guard(body(schema(optional=16)))["planning_headroom_pass"]


def test_shared_aliases_cannot_hide_union_parameters_or_optionals():
    shared = {
        "$defs": {"N": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "type": "object",
        "properties": {f"x{i}": {"$ref": "#/$defs/N"} for i in range(17)},
        "required": [f"x{i}" for i in range(17)],
    }
    report = inspect_request(body(shared))
    m = report["schemas"][0]
    assert (
        m["direct_union_properties"],
        m["anyof_nodes"],
        m["expanded_union_properties"],
        m["expanded_union_nodes"],
    ) == (0, 1, 17, 17)
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(body(shared), headroom=False)
    nested = {
        "$defs": {"S": schema(optional=13)},
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/S"}, "b": {"$ref": "#/$defs/S"}},
        "required": ["a", "b"],
    }
    m = schema_metrics(nested)
    assert m["optional_properties"] == 13 and m["expanded_optional_properties"] == 26
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(body(nested), headroom=False)


def test_array_item_union_nodes_are_distinct_from_object_parameters():
    value = schema()
    value["properties"] = {
        f"a{i}": {"type": "array", "items": schema(1)["properties"]["u0"]} for i in range(13)
    }
    value["required"] = list(value["properties"])
    m = schema_metrics(value)
    assert m["direct_union_properties"] == m["expanded_union_properties"] == 0
    assert m["anyof_nodes"] == m["expanded_union_nodes"] == 13
    with pytest.raises(ProviderSchemaError, match="planning_headroom"):
        guard(body(value))


def test_combined_output_and_strict_tool_limits_ignore_nonstrict_tools():
    value = body(schema(8))
    value["tools"] = [{"strict": True, "input_schema": schema(8)}]
    assert guard(value, headroom=False)["union_parameters_conservative"] == 16
    value["tools"].append({"strict": True, "input_schema": schema(1)})
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(value, headroom=False)
    value = {
        "tools": [{"strict": True, "input_schema": schema()} for _ in range(20)]
        + [{"strict": False}] * 10
    }
    assert guard(value)["strict_tools"] == 20
    value["tools"].append({"strict": True, "input_schema": schema()})
    with pytest.raises(ProviderSchemaError, match="documented_limit"):
        guard(value)


@pytest.mark.parametrize(
    "value,reason",
    [
        ({"$ref": "https://invalid.test/schema"}, "external_or_invalid"),
        ({"$ref": "#/$defs/absent"}, "unresolved"),
        ({"$defs": {"X": {"$ref": "#/$defs/X"}}, "$ref": "#/$defs/X"}, "recursive"),
        ({"$defs": {"X": 3}, "$ref": "#/$defs/X"}, "must_be_object"),
        ({"oneOf": [{"type": "string"}]}, "unsupported_oneof"),
        ({"allOf": [{"$ref": "#/$defs/X"}]}, "allof_reference"),
        ({"properties": []}, "properties_object"),
        ({"required": {}}, "required_array"),
        ({"properties": {"x": True}}, "property_object"),
    ],
)
def test_unsupported_or_ambiguous_reference_shapes_fail_closed(value, reason):
    with pytest.raises(ProviderSchemaError, match=reason):
        inspect_request(body(value))


def test_json_pointer_escaping_and_safe_allof():
    m = schema_metrics(
        {
            "$defs": {"a/b~": {"type": "string"}},
            "allOf": [{"type": "object"}],
            "properties": {"x": {"$ref": "#/$defs/a~1b~0"}},
            "required": ["x"],
        }
    )
    assert m["reference_uses"] == 1 and m["anyof_nodes"] == 0


@pytest.mark.parametrize(
    "value,reason",
    [
        ({}, "strict_schema"),
        ({"output_config": {"format": []}}, "output_format"),
        ({"output_config": {"format": {"type": "text", "schema": {}}}}, "output_format"),
        ({"tools": [True]}, "tool_object"),
        ({"tools": [{"strict": True}]}, "strict_tool_schema"),
    ],
)
def test_request_shape_refusal_precedes_any_possible_contact(value, reason):
    with pytest.raises(ProviderSchemaError, match=reason):
        guard(value)


def test_original_exact_v16_schemas_expose_the_reported_issue():
    root = (
        Path(__file__).resolve().parents[1]
        / "planning/15-evaluation-audit-and-recovery/evidence/keyed-contract-v16"
    )
    samples = json.loads(gzip.decompress((root / "DRAFT-SCHEMAS.json.gz").read_bytes()))
    for key, direct, nodes in [
        ("campaign-dev-learn", 14, 15),
        ("campaign-dev-compare", 21, 23),
        ("campaign-eval-research-memory", 18, 19),
    ]:
        r = inspect_request(body(samples[key]["wire"]))
        m = r["schemas"][0]
        assert (m["direct_union_properties"], m["anyof_nodes"]) == (direct, nodes)
        assert r["optional_parameters_conservative"] == 0
        assert r["remote_compiler_acceptance"] == "UNMEASURED"
        if key != "campaign-dev-learn":
            with pytest.raises(ProviderSchemaError, match="documented_limit"):
                guard(body(samples[key]["wire"]), headroom=False)
    original = deepcopy(samples["campaign-dev-compare"]["wire"])
    schema_metrics(original)
    assert original == samples["campaign-dev-compare"]["wire"]


@pytest.mark.parametrize("probe", [False, True])
def test_maximum_exact_checker_and_probe_schemas_have_no_unions_or_optionals(probe):
    from src.workspace import assistance_keyed_checks
    from tests.test_workspace_assistance_keyed_checks import fixture

    raw, context = fixture(12, 0 if probe else 8, probe=probe)
    context["unscored_prose"] = {"assumptions": [f"Procedural position {i}" for i in range(12)]}
    from jsonschema import Draft202012Validator

    raw["prose_findings"] = {key: [] for key in assistance_keyed_checks.prose_locations(context)}
    schemas = assistance_keyed_checks.schemas(context, probe=probe)
    Draft202012Validator(schemas["wire"]).validate(raw)
    assert len(assistance_keyed_checks.normalize(raw, context, probe=probe)["checks"]) == 12
    report = guard(body(schemas["wire"]))
    assert report["union_parameters_conservative"] == report["expanded_union_nodes"] == 0
    assert report["optional_parameters_conservative"] == 0
    assert len(schemas["wire"]["required"]) >= 4


def test_reference_cycle_at_a_property_and_analysis_work_bound_are_refused():
    with pytest.raises(ProviderSchemaError, match="recursive"):
        schema_metrics(
            {"$defs": {"X": {"$ref": "#/$defs/X"}}, "properties": {"a": {"$ref": "#/$defs/X"}}}
        )
    with pytest.raises(ProviderSchemaError, match="analysis_bound"):
        schema_metrics({"description": [None] * 100001})
    with pytest.raises(ProviderSchemaError, match="object_required"):
        schema_metrics(True)
