"""Versioned contracts for reproducible agent runs.

The package is intentionally independent from runtime configuration and agent
code.  Trust-boundary models may import it without initializing providers,
reading environment variables, or accessing repository state.
"""

from src.contracts.kernel import (
    CONTRACT_DIGEST_PROFILE,
    CanonicalizationError,
    ContractError,
    ContractErrorCode,
    DataClass,
    Digest,
    ImmutableObjectRef,
    MoneyUsd,
    RetentionPolicyRef,
    Rfc3339Utc,
    SemVer,
    StrictContractModel,
    canonical_json,
    canonical_json_bytes,
    require_digest,
    sha256_digest,
    shared_kernel_json_schema,
)

__all__ = [
    "CONTRACT_DIGEST_PROFILE",
    "CanonicalizationError",
    "ContractError",
    "ContractErrorCode",
    "DataClass",
    "Digest",
    "ImmutableObjectRef",
    "MoneyUsd",
    "RetentionPolicyRef",
    "Rfc3339Utc",
    "SemVer",
    "StrictContractModel",
    "canonical_json",
    "canonical_json_bytes",
    "require_digest",
    "sha256_digest",
    "shared_kernel_json_schema",
]
