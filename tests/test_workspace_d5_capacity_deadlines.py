"""Prospective timers use durable sealed inputs; synthetic time and no provider."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from src.workspace import d5_deadlines as deadlines
from src.workspace.admission import AdmissionError
from src.workspace.d5_capacity_policy import DEADLINES
from src.workspace.d5_capacity_policy import POLICY as CAPACITY_POLICY

pytestmark = pytest.mark.unit


def reservation(*, capacity=True, seconds=0, steps=0):
    settings = {"operation_deadlines": deepcopy(DEADLINES if capacity else deadlines.POLICY)}
    if capacity:
        settings["d5_capacity_policy"] = deepcopy(CAPACITY_POLICY)
    return {
        "created_at": (datetime(2026, 11, 14, tzinfo=UTC) - timedelta(seconds=seconds)).isoformat(),
        "sealed_input": {"settings": settings},
        "adapter": {"steps": [{}] * steps},
    }


@pytest.fixture
def controlled_now(monkeypatch):
    instant = datetime(2026, 11, 14, tzinfo=UTC)
    monkeypatch.setattr(deadlines, "now", lambda: instant)
    return instant


def test_legacy_policy_and_origin_only_callers_remain_exact(controlled_now):
    assert deadlines.POLICY == {
        "revision": "d5-operation-deadlines-v1",
        "count_seconds": 30,
        "draft_seconds": 30,
        "repair_seconds": 30,
        "check_seconds": 120,
        "recheck_seconds": 120,
        "workflow_seconds": 480,
        "origin": "durable_reservation_created_at",
    }
    data = reservation(capacity=False, seconds=31)
    assert deadlines.remaining(data) == 449
    assert deadlines.remaining({"created_at": data["created_at"]}) == 449
    assert deadlines.timeout("messages", {"stage": "check"}, data) == 120
    deadlines.validate(deepcopy(deadlines.POLICY))


@pytest.mark.parametrize(
    "path,stage,steps,expected",
    [
        ("messages/count_tokens", "draft", 0, 60),
        ("messages/count_tokens", "check", 1, 60),
        ("messages", "draft", 0, 120),
        ("messages", "check", 1, 240),
        ("messages", "repair", 2, 120),
        ("messages", "check", 3, 240),
    ],
)
def test_exact_sealed_prospective_operation_timers(controlled_now, path, stage, steps, expected):
    data = reservation(seconds=31, steps=steps)
    assert deadlines.remaining(data) == 1169
    assert deadlines.timeout(path, {"stage": stage}, data) == expected
    deadlines.validate(deepcopy(DEADLINES))


def test_capacity_timer_requires_whole_exact_sealed_policy(controlled_now):
    data = reservation()
    settings = data["sealed_input"]["settings"]
    del settings["d5_capacity_policy"]
    with pytest.raises(AdmissionError, match="capacity_binding_required"):
        deadlines.remaining(data)
    settings["d5_capacity_policy"] = {**deepcopy(CAPACITY_POLICY), "max_repairs": 2}
    with pytest.raises(AdmissionError, match="policy_drift"):
        deadlines.remaining(data)
    settings["d5_capacity_policy"] = deepcopy(CAPACITY_POLICY)
    settings["operation_deadlines"] = deepcopy(deadlines.POLICY)
    with pytest.raises(AdmissionError, match="policy_drift"):
        deadlines.remaining(data)


@pytest.mark.parametrize("policy", [None, {}, "v15", {**DEADLINES, "check_seconds": 241}])
def test_prospective_timer_drift_cannot_extend_horizon(controlled_now, policy):
    data = reservation()
    data["sealed_input"]["settings"]["operation_deadlines"] = policy
    with pytest.raises(AdmissionError, match="policy_drift"):
        deadlines.remaining(data)


def test_loose_timer_values_do_not_enable_the_new_policy(controlled_now):
    data = reservation(capacity=False)
    data["operation_deadlines"] = deepcopy(DEADLINES)
    data["d5_capacity_policy"] = deepcopy(CAPACITY_POLICY)
    assert deadlines.remaining(data) == 480
    assert deadlines.timeout("messages", {"stage": "check"}, data) == 120


def test_workflow1200_caps_each_call_and_restart_keeps_origin(controlled_now):
    data = reservation(seconds=1195, steps=1)
    assert deadlines.remaining(deepcopy(data)) == 5
    assert deadlines.timeout("messages", {"stage": "check"}, data) == 5
    data["created_at"] = (controlled_now - timedelta(seconds=1200)).isoformat()
    with pytest.raises(AdmissionError, match="workflow_deadline_exceeded"):
        deadlines.remaining(deepcopy(data))


def test_prospective_origin_still_requires_timezone_and_cannot_be_in_future(controlled_now):
    data = reservation()
    data["created_at"] = "2026-11-14T00:00:00"
    with pytest.raises(AdmissionError, match="durable_deadline_origin"):
        deadlines.remaining(data)
    data["created_at"] = (controlled_now + timedelta(seconds=1)).isoformat()
    with pytest.raises(AdmissionError, match="clock_precedes"):
        deadlines.remaining(data)
