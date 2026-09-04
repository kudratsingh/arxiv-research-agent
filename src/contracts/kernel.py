"""Shared identity, encoding, and validation rules for P0 contracts.

``agent-contract-json/v1`` is a deliberately narrow RFC 8785 profile.  Contract
documents use strings for timestamps and money, and reject binary floats.  As a
result, the only JSON number admitted here is an I-JSON-safe integer; its RFC
8785 representation is identical to the ordinary base-10 JSON representation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StringConstraints,
    TypeAdapter,
)

CONTRACT_DIGEST_PROFILE = "agent-contract-json/v1"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_RFC3339_UTC_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)


class ContractErrorCode(StrEnum):
    """Stable machine-readable failure categories shared by P0 contracts."""

    SCHEMA_INVALID = "contract.schema_invalid"
    DIGEST_INVALID = "contract.digest_invalid"
    REF_INVALID = "contract.ref_invalid"
    REDACTION_REQUIRED = "contract.redaction_required"
    INCOMPATIBLE_VERSION = "contract.incompatible_version"


class ContractError(ValueError):
    """A contract failure with a stable code and human-readable detail."""

    def __init__(self, code: ContractErrorCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class CanonicalizationError(ContractError):
    """The supplied value cannot be encoded by the v1 digest profile."""

    def __init__(self, detail: str) -> None:
        super().__init__(ContractErrorCode.SCHEMA_INVALID, detail)


class StrictContractModel(BaseModel):
    """Closed, immutable, non-coercing base for persisted contract models."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_strip_whitespace=True,
    )


Digest: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$"),
]
SemVer: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$"),
]
MoneyUsd: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^(0|[1-9][0-9]*)\.[0-9]{6}$"),
]


def _validate_rfc3339_utc(value: str) -> str:
    if not _RFC3339_UTC_RE.fullmatch(value):
        raise ValueError("timestamp must be RFC 3339 UTC with a trailing Z")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("timestamp contains an invalid calendar date or time") from exc
    return value


Rfc3339Utc: TypeAlias = Annotated[
    str,
    StringConstraints(
        pattern=(
            r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
            r"[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
        )
    ),
    AfterValidator(_validate_rfc3339_utc),
]


class ImmutableObjectRef(StrictContractModel):
    """Transport-independent identity of immutable contract content."""

    kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,127}$")]
    revision: SemVer
    digest: Digest


class RetentionPolicyRef(ImmutableObjectRef):
    """Typed immutable reference that can point only to a retention policy."""

    kind: Literal["retention_policy"]


class DataClass(StrEnum):
    """Content sensitivity, ordered from least to most restrictive."""

    PUBLIC = "public"
    INTERNAL = "internal"
    USER_CONFIDENTIAL = "user_confidential"
    LEARNER_SENSITIVE = "learner_sensitive"

    @property
    def rank(self) -> int:
        return _DATA_CLASS_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, DataClass):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:
        if not isinstance(other, DataClass):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, DataClass):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, DataClass):
            return NotImplemented
        return self.rank >= other.rank

    @classmethod
    def most_restrictive(cls, *values: DataClass) -> DataClass:
        if not values:
            raise ValueError("at least one data class is required")
        return max(values, key=lambda value: value.rank)


_DATA_CLASS_RANK = {
    DataClass.PUBLIC: 0,
    DataClass.INTERNAL: 1,
    DataClass.USER_CONFIDENTIAL: 2,
    DataClass.LEARNER_SENSITIVE: 3,
}


def _utf16_sort_key(value: str) -> bytes:
    """Return the RFC 8785 property-name ordering key."""

    try:
        return value.encode("utf-16be")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("strings must not contain lone Unicode surrogates") from exc


def _normalize_json(value: Any, *, path: str = "$") -> Any:
    if isinstance(value, BaseModel):
        return _normalize_json(value.model_dump(mode="json"), path=path)
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            _utf16_sort_key(value)
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            raise CanonicalizationError(
                f"{path} is outside the I-JSON safe-integer range"
            )
        return value
    if isinstance(value, float):
        raise CanonicalizationError(
            f"{path} is a binary float; contract decimals must be fixed-format strings"
        )
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise CanonicalizationError(f"{path} contains a non-string object key")
        ordered: dict[str, Any] = {}
        for key in sorted(value, key=_utf16_sort_key):
            ordered[key] = _normalize_json(value[key], path=f"{path}.{key}")
        return ordered
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _normalize_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise CanonicalizationError(f"{path} has unsupported type {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize a JSON value using ``agent-contract-json/v1``."""

    normalized = _normalize_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical UTF-8 bytes hashed by immutable references."""

    try:
        return canonical_json(value).encode("utf-8")
    except UnicodeEncodeError as exc:  # Defensive; normalization rejects surrogates.
        raise CanonicalizationError("strings must be valid Unicode") from exc


def sha256_digest(value: Any) -> str:
    """Return an algorithm-prefixed digest of canonical contract content."""

    hexdigest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return f"sha256:{hexdigest}"


def require_digest(value: Any, expected: str) -> None:
    """Raise a coded failure unless ``expected`` matches canonical content."""

    try:
        validated = TypeAdapter(Digest).validate_python(expected, strict=True)
    except ValueError as exc:
        raise ContractError(
            ContractErrorCode.DIGEST_INVALID,
            "expected digest must use sha256:<64 lowercase hex>",
        ) from exc
    actual = sha256_digest(value)
    if actual != validated:
        raise ContractError(
            ContractErrorCode.DIGEST_INVALID,
            f"digest mismatch: expected {validated}, computed {actual}",
        )


class _SharedKernelSchema(StrictContractModel):
    """Schema-only envelope exposing every shared primitive to consumers."""

    object_ref: ImmutableObjectRef
    retention_policy_ref: RetentionPolicyRef
    data_class: DataClass
    amount_usd: MoneyUsd
    occurred_at: Rfc3339Utc
    error_code: ContractErrorCode


def shared_kernel_json_schema() -> dict[str, Any]:
    """Export JSON Schema for the complete shared-kernel wire vocabulary."""

    schema = _SharedKernelSchema.model_json_schema(mode="validation")
    schema["$id"] = "https://arxiv-research-agent.dev/schemas/agent-contract-json/v1/kernel"
    schema["title"] = "Agent contract shared kernel v1"
    return schema
