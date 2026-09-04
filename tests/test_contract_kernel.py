"""No-cost qualification tests for the shared P0 contract kernel."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from src.contracts import (
    CONTRACT_DIGEST_PROFILE,
    CanonicalizationError,
    ContractError,
    ContractErrorCode,
    DataClass,
    ImmutableObjectRef,
    RetentionPolicyRef,
    StrictContractModel,
    canonical_json,
    require_digest,
    sha256_digest,
    shared_kernel_json_schema,
)

FIXTURE = Path(__file__).parent / "fixtures" / "contracts" / "shared_kernel_v1.json"
VALID_DIGEST = "sha256:" + "a" * 64


class ExampleContract(StrictContractModel):
    ref: ImmutableObjectRef


def _ref(**overrides: Any) -> dict[str, Any]:
    return {
        "kind": "source_snapshot",
        "id": "arxiv-1706-03762",
        "revision": "1.0.0",
        "digest": VALID_DIGEST,
        **overrides,
    }


@pytest.mark.unit
def test_golden_canonical_bytes_and_digest() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["profile"] == CONTRACT_DIGEST_PROFILE
    assert canonical_json(fixture["payload"]) == fixture["canonical"]
    assert sha256_digest(fixture["payload"]) == fixture["digest"]
    require_digest(fixture["payload"], fixture["digest"])


@pytest.mark.unit
def test_key_order_and_process_restart_do_not_change_digest() -> None:
    left = {"z": [3, 2, 1], "a": {"right": True, "left": None}}
    right = {"a": {"left": None, "right": True}, "z": [3, 2, 1]}
    expected = sha256_digest(left)
    assert sha256_digest(right) == expected

    script = (
        "from src.contracts import sha256_digest; "
        "print(sha256_digest({'a': {'right': True, 'left': None}, 'z': [3, 2, 1]}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == expected


@pytest.mark.unit
def test_semantic_change_changes_digest() -> None:
    assert sha256_digest({"limit": 1}) != sha256_digest({"limit": 2})


@pytest.mark.unit
def test_rfc8785_uses_utf16_property_order() -> None:
    # U+1F600 sorts before U+FFFD by UTF-16 code units, but after it by code point.
    assert canonical_json({"\ufffd": 1, "\U0001f600": 2}) == '{"😀":2,"�":1}'


@pytest.mark.unit
@pytest.mark.parametrize(
    "value, message",
    [
        ({"cost": 0.1}, "binary float"),
        ({"large": 9_007_199_254_740_992}, "safe-integer"),
        ({1: "not a key"}, "non-string object key"),
        ({"surrogate": "\ud800"}, "lone Unicode surrogate"),
        ({"bytes": b"no"}, "unsupported type bytes"),
    ],
)
def test_canonical_profile_rejects_ambiguous_values(value: Any, message: str) -> None:
    with pytest.raises(CanonicalizationError, match=message):
        canonical_json(value)


@pytest.mark.unit
def test_strict_models_reject_coercion_unknown_fields_and_mutation() -> None:
    contract = ExampleContract(ref=ImmutableObjectRef(**_ref()))
    with pytest.raises(ValidationError):
        ExampleContract.model_validate({"ref": _ref(), "unexpected": True})
    with pytest.raises(ValidationError):
        ImmutableObjectRef.model_validate(_ref(revision=1))
    with pytest.raises(ValidationError):
        contract.ref.id = "changed"  # type: ignore[misc]


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "Source"},
        {"id": "contains_underscore"},
        {"revision": "1.0"},
        {"revision": "01.0.0"},
        {"digest": "a" * 64},
        {"digest": "sha256:" + "A" * 64},
    ],
)
def test_malformed_immutable_refs_fail(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ImmutableObjectRef.model_validate(_ref(**overrides))


@pytest.mark.unit
def test_retention_ref_is_kind_constrained() -> None:
    ref = RetentionPolicyRef.model_validate(
        _ref(kind="retention_policy", id="retain-30-days")
    )
    assert ref.kind == "retention_policy"
    with pytest.raises(ValidationError):
        RetentionPolicyRef.model_validate(_ref())


@pytest.mark.unit
def test_data_class_order_is_explicit() -> None:
    assert DataClass.PUBLIC < DataClass.INTERNAL
    assert DataClass.PUBLIC <= DataClass.INTERNAL
    assert DataClass.INTERNAL < DataClass.USER_CONFIDENTIAL
    assert DataClass.USER_CONFIDENTIAL < DataClass.LEARNER_SENSITIVE
    assert DataClass.LEARNER_SENSITIVE > DataClass.USER_CONFIDENTIAL
    assert DataClass.LEARNER_SENSITIVE >= DataClass.USER_CONFIDENTIAL
    assert DataClass.INTERNAL <= DataClass.INTERNAL
    assert DataClass.INTERNAL >= DataClass.INTERNAL
    assert DataClass.most_restrictive(
        DataClass.PUBLIC, DataClass.LEARNER_SENSITIVE, DataClass.INTERNAL
    ) is DataClass.LEARNER_SENSITIVE
    with pytest.raises(ValueError, match="at least one"):
        DataClass.most_restrictive()


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_usd", "01.000000"),
        ("amount_usd", "1.0"),
        ("amount_usd", 1.0),
        ("occurred_at", "2026-02-30T00:00:00Z"),
        ("occurred_at", "2026-09-04T16:00:00+00:00"),
        ("occurred_at", "2026-09-04T16:00:00.1234567Z"),
    ],
)
def test_schema_export_rejects_bad_money_and_timestamps(field: str, value: Any) -> None:
    from pydantic import TypeAdapter

    from src.contracts.kernel import _SharedKernelSchema

    payload = {
        "object_ref": _ref(),
        "retention_policy_ref": _ref(
            kind="retention_policy", id="retain-30-days"
        ),
        "data_class": DataClass.PUBLIC,
        "amount_usd": "0.000000",
        "occurred_at": "2026-09-04T16:00:00Z",
        "error_code": ContractErrorCode.SCHEMA_INVALID,
    }
    payload[field] = value
    with pytest.raises(ValidationError):
        TypeAdapter(_SharedKernelSchema).validate_python(payload, strict=True)


@pytest.mark.unit
def test_digest_failures_have_stable_codes() -> None:
    with pytest.raises(ContractError) as malformed:
        require_digest({}, "not-a-digest")
    assert malformed.value.code is ContractErrorCode.DIGEST_INVALID

    with pytest.raises(ContractError) as mismatch:
        require_digest({}, VALID_DIGEST)
    assert mismatch.value.code is ContractErrorCode.DIGEST_INVALID


@pytest.mark.unit
def test_schema_export_contains_shared_definitions() -> None:
    schema = shared_kernel_json_schema()
    assert schema["$id"].endswith("/agent-contract-json/v1/kernel")
    assert schema["additionalProperties"] is False
    assert {"ImmutableObjectRef", "RetentionPolicyRef"} <= set(schema["$defs"])
    assert schema["properties"]["amount_usd"]["pattern"].endswith("[0-9]{6}$")
    assert schema["properties"]["occurred_at"]["pattern"].endswith("Z$")
    assert "kind" in schema["$defs"]["RetentionPolicyRef"]["required"]
