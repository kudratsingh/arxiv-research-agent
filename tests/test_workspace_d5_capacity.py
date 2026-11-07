"""Operation-aware cumulative capacity; synthetic ledger, no provider contacts."""

from copy import deepcopy
from decimal import Decimal

import pytest

from src.workspace import qualification_budget as budget
from src.workspace.admission import AdmissionError
from tests import test_workspace_evaluation_program as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "operation,messages,counts,allowed",
    [
        ("workflow", 77, 77, False),
        ("workflow", 76, 76, True),
        ("probe", 79, 79, True),
        ("probe", 79, 80, False),
        ("measurement", 80, 79, True),
        ("measurement", 80, 80, False),
    ],
)
def test_complete_operation_capacity_matches_sealed_calls_at_80_contact_boundary(
    store, monkeypatch, operation, messages, counts, allowed
):
    support.program(store)
    with store.pool.connection() as conn:
        history = budget.census(conn, "a")
    history.update(messages=messages, counts=counts)
    monkeypatch.setattr(budget, "census", lambda *args, **kwargs: deepcopy(history))
    policy = {
        "program_id": "evaluation",
        "program_authorization_digest": support.AUTH,
        "purpose": "workspace-d5-qualification-only",
    }
    with store.pool.connection() as conn:
        kwargs = dict(
            reserve_usd=Decimal("0") if operation == "measurement" else Decimal("0.15"),
            current_job=None,
            next_endpoint=None,
            reserve_operation=operation,
        )
        if allowed:
            report = budget.guard_program(conn, "a", policy, **kwargs)
            assert report["counts"] == counts and report["messages"] == messages
        else:
            with pytest.raises(AdmissionError, match="capacity_required"):
                budget.guard_program(conn, "a", policy, **kwargs)


def test_capacity_cannot_invent_an_operation_or_fund_measurement(store):
    support.program(store)
    policy = {
        "program_id": "evaluation",
        "program_authorization_digest": support.AUTH,
        "purpose": "workspace-d5-qualification-only",
    }
    for operation, amount in [("skip-checks", Decimal("0")), ("measurement", Decimal("0.01"))]:
        with store.pool.connection() as conn, pytest.raises(AdmissionError):
            budget.guard_program(
                conn,
                "a",
                policy,
                reserve_usd=amount,
                current_job=None,
                next_endpoint=None,
                reserve_operation=operation,
            )


def test_single_call_reservation_cannot_be_requested_by_a_legacy_workflow_policy(store):
    support.program(store)
    with store.pool.connection() as conn, pytest.raises(AdmissionError, match="sealed_operation"):
        budget.guard_program(
            conn,
            "a",
            {"program_id": "evaluation", "program_authorization_digest": support.AUTH},
            reserve_usd=Decimal("0.15"),
            current_job=None,
            next_endpoint=None,
            reserve_operation="probe",
        )
