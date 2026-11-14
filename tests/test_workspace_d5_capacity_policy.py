"""Prospective byte/cardinality policy is explicit, finite and not semantic proof."""
import json
from copy import deepcopy

import pytest

from src.workspace.admission import GenerationInput, SourceRef
from src.workspace.d5_capacity_policy import (
    MAX_INTERNAL_BYTES,
    POLICY,
    capacity_for,
    enabled,
    envelope,
    json_bytes,
    monetary_envelope,
    observations,
    protect,
    validate,
)

pytestmark = pytest.mark.unit


def test_policy_requires_exact_versioned_settings():
    validate(deepcopy(POLICY))
    assert not enabled({})
    assert enabled({"d5_capacity_policy": deepcopy(POLICY)})
    for value in ({}, {**POLICY, "max_repairs": 2}, {**POLICY, "revision": "future"}):
        with pytest.raises(ValueError, match="d5_capacity_policy_drift"):
            validate(value)
        with pytest.raises(ValueError):
            enabled({"d5_capacity_policy": value})
    assert capacity_for("learn")["max_claims"] == 8
    assert capacity_for("research")["max_claims"] == 12
    with pytest.raises(ValueError, match="mode_required"):
        capacity_for("unknown")


def test_byte_guards_preserve_unicode_and_escaping_without_truncation():
    value = "科学\\\"\n" * 100
    original = value
    protect(value, len(value.encode()))
    with pytest.raises(ValueError, match="capacity_exceeded"):
        protect(value, len(value.encode()) - 1)
    assert value == original
    item = {"reason": value}
    n = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode())
    assert json_bytes(item) == n
    protect(item, n)
    with pytest.raises(ValueError):
        protect(item, n - 1)
    with pytest.raises(ValueError):
        json_bytes({"bad": float("nan")})


def test_soft_targets_are_observations_never_rejections():
    value = {"claim_reviews": [{"reason": "長" * 1000}], "claims": [{"text": "s" * 1000}]}
    before = deepcopy(value)
    seen = observations(value)
    assert [r["characters"] for r in seen] == [1000, 1000]
    assert all(r["disposition"] == "formatting_observation_only" for r in seen)
    assert value == before
    assert observations({"reason": "x" * 110, "text": "short", "other": 3}) == []


def test_complete_four_stage_envelope_and_money_are_not_token_measurements():
    result = envelope({"units": {"u": {"quote": "科学" * 100}}, "candidate_initial_wire": {"prompt": "source"}})
    assert set(result["stage_input_bytes_max"]) == {"draft", "check", "repair", "recheck"}
    assert result["input_bytes_reserved"] == sum(result["stage_input_bytes_max"].values())
    assert result["provider_token_counts"] is result["actual_provider_usage"] is None
    assert result["max_calls"] == 4 and result["max_repairs"] == 1
    assert result["normalized_output_bytes_max"] >= 4 * POLICY["compact_checker_utf8_bytes"]
    assert all(v <= MAX_INTERNAL_BYTES for v in result["stage_input_bytes_max"].values())
    with pytest.raises(ValueError):
        envelope({"padding": "x" * MAX_INTERNAL_BYTES})
    assert monetary_envelope() == {"draft_or_repair": "0.16", "check_recheck_or_probe": "0.4", "workflow": "1.12", "ten_workflows_four_probes": "12.80"}


def test_sealed_input_has_versioned_generous_serialization_guard():
    source = SourceRef("work", "version", "material", "sha256:hash", "abstract")
    settings = {"padding": "科学" * 10000}
    legacy = GenerationInput("deep_dive", "model", "revision", (source,), settings)
    with pytest.raises(ValueError, match="invalid_sealed_input"):
        legacy.snapshot()
    settings["d5_capacity_policy"] = deepcopy(POLICY)
    new = GenerationInput("deep_dive", "model", "revision", (source,), settings)
    assert new.snapshot()["settings"]["padding"] == settings["padding"]
    settings["padding"] = "x" * MAX_INTERNAL_BYTES
    with pytest.raises(ValueError, match="invalid_sealed_input"):
        new.snapshot()


def test_consolidated_budget_preserves_estimates_and_overlapping_holds_once():
    from decimal import Decimal

    from src.workspace.d5_campaign_v15_policy import LIMITS, PROGRAM_LIMITS
    known, holds = Decimal("2.110597"), Decimal("0.425066") + Decimal("0.45")
    total = known + holds + Decimal(LIMITS["new_usd"]) + Decimal(LIMITS["headroom_usd"])
    assert total == Decimal("18.985663")
    assert Decimal(PROGRAM_LIMITS["usd"]) - total == Decimal("1.014337")
    assert (36 + LIMITS["jobs"], 70 + LIMITS["messages"], 95 + LIMITS["counts"]) == (50, 114, 139)
    assert PROGRAM_LIMITS["new_jobs"] >= 50 and PROGRAM_LIMITS["messages"] >= 114 and PROGRAM_LIMITS["counts"] >= 139
