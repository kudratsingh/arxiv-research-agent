"""Independent pure controls for successor revocation and frozen probe context.

These tests use in-memory connection doubles and immutable packet derivatives.
No database, provider, credential loader or token-count endpoint is used.
"""

import json
from argparse import Namespace
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from src.workspace import d5_campaign_operator as operator
from src.workspace import d5_campaign_v14_packet as successor
from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance_compact_checks import (
    COMPACT_NORMALIZATION_REVISION,
)
from src.workspace.assistance_compact_checks import (
    schemas as checker_schemas,
)
from src.workspace.d5_adapter import initial_context
from src.workspace.d5_answerability import matrix
from src.workspace.d5_campaign_packet import plan_digest
from src.workspace.d5_campaign_v14_extension import REVISION as EXTENSION_REVISION
from src.workspace.d5_campaign_v14_policy import LIMITS, PROGRESSION, REVISION, ROUTES
from src.workspace.d5_operations import wire

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")


@pytest.mark.parametrize(
    "revision,extension,expected_table",
    [
        (REVISION, "program-campaign-v6", "workspace_d5_campaign_successor_revocations"),
        (
            "d5-consolidated-machine-campaign-v13",
            "program-campaign-v5",
            "workspace_d5_campaign_revocations",
        ),
    ],
)
def test_cli_revocation_dispatches_to_its_own_revision(
    monkeypatch, revision, extension, expected_table
):
    queries = []

    class Connection:
        def execute(self, statement, params=None):
            queries.append((str(statement), params))

    @contextmanager
    def connection():
        yield Connection()

    class Pool:
        pass

    pool = Pool()
    pool.connection = connection

    @contextmanager
    def database(_):
        yield pool

    packet = {
        "revision": revision,
        "packet_digest": "a" * 64,
        "program_id": "program",
        "campaign_extension": {"core": {"extension_id": extension}},
    }
    authorization = {
        "packet_digest": packet["packet_digest"],
        "approved_by": "Synthetic attribution only",
        "scope_id": "d5-" + packet["packet_digest"][:24],
    }
    args = Namespace(
        verb="revoke",
        packet=Path("packet"),
        authorization=Path("authorization"),
        receipt=Path("receipt"),
    )
    writes = []
    monkeypatch.setattr("argparse.ArgumentParser.parse_args", lambda _: args)
    monkeypatch.setattr("src.workspace.d5_benchmark.database", database)
    monkeypatch.setattr(
        "src.workspace.d5_benchmark.read",
        lambda path: packet if path == args.packet else authorization,
    )
    monkeypatch.setattr(
        "src.workspace.d5_benchmark.write", lambda path, value: writes.append(value)
    )
    monkeypatch.setenv("D5_POSTGRES_URL", "pure-no-network")
    operator.main()
    inserts = [(query, params) for query, params in queries if query.startswith("INSERT")]
    assert len(inserts) == 1
    assert inserts[0][0].startswith("INSERT INTO " + expected_table + " ")
    assert inserts[0][1][0] == extension
    assert writes == [{"revoked": True, "provider_contacts": 0}]


def pure_packet():
    """Contract-verifier control, not an activatable receipt or funded packet."""
    packet = deepcopy(successor.predecessor())
    packet.update(
        revision=REVISION,
        limits=LIMITS,
        operation_routes=ROUTES,
        progression=PROGRESSION,
        measurement_cases=[],
        checker_schemas=checker_schemas(),
        checker_normalization_revision=COMPACT_NORMALIZATION_REVISION,
        predecessor_packet=successor.BASE,
    )
    for case in packet["cases"]:
        case["sealed"] = successor.upgrade(case["sealed"])
        case["sealed"]["candidate_initial_wire"] = wire(initial_context(case["sealed"]), ROUTES)
        case["wire_digest"] = _digest(case["sealed"]["candidate_initial_wire"])
    for probe in packet["probes"]:
        context = json.loads(probe["wire"]["messages"][0]["content"])
        context["output_schema"] = probe["wire"]["output_config"]["format"]["schema"]
        probe["wire"] = wire(context, ROUTES)
    packet["answerability"] = matrix(packet["cases"])
    packet["campaign_extension"] = {
        "core": {"revision": EXTENSION_REVISION, "basis": packet["history"]}
    }
    refresh_plan(packet)
    successor.verify_packet(packet)
    return packet


def refresh_plan(packet):
    core = packet["campaign_extension"]["core"]
    core["plan_digest"] = plan_digest(packet)
    packet["campaign_extension"]["proposal_digest"] = _digest(core)


@pytest.mark.parametrize("field", ["probe_references", "reference"])
def test_frozen_probe_context_cannot_receive_reference_labels(field):
    packet = pure_packet()
    context = json.loads(packet["probes"][0]["wire"]["messages"][0]["content"])
    context[field] = packet["probe_references"]
    context["output_schema"] = packet["probes"][0]["wire"]["output_config"]["format"]["schema"]
    packet["probes"][0]["wire"] = wire(context, ROUTES)
    refresh_plan(packet)
    with pytest.raises(AdmissionError, match="probe_evidence_or_wire_drift"):
        successor.verify_packet(packet)


@pytest.mark.parametrize("mutation", ["cohort", "human_labels", "selected_units"])
def test_frozen_probe_metadata_and_selected_units_remain_pinned(mutation):
    packet = pure_packet()
    probe = packet["probes"][0]
    if mutation == "selected_units":
        probe["sealed"]["units"] = {}
    elif mutation == "human_labels":
        probe["human_labels"] = {"c1": "supported"}
    else:
        probe["cohort"] = "fresh_independent"
    refresh_plan(packet)
    with pytest.raises(AdmissionError, match="probe_evidence_or_wire_drift"):
        successor.verify_packet(packet)


@pytest.mark.parametrize("change", ["revocation", "receipt"])
def test_parent_cannot_adopt_preproposal_legacy_revocation_or_receipt_drift(monkeypatch, change):
    from src.workspace.d5_campaign_v14_extension import parent

    sealed_legacy = {"capacity_revocations": [], "original_programme": "frozen-programme"}
    core = {
        "revision": "programme-consolidated-campaign-v5",
        "limits": {"new_jobs": 47, "messages": 109, "counts": 134, "usd": "10", "concurrency": 1},
        "parent": {"predecessor_seal": deepcopy(sealed_legacy)},
    }
    record = {
        "campaign_extension": {"core": core},
        "packet_digest": "p",
        "scope_id": "stopped",
        "expires_at": "2030-01-01T00:00:00+00:00",
        "approved": True,
        "capacity_amendment_approved": True,
        "historical_uncertainty_exception_approved": True,
    }
    value = {
        "record": record,
        "scope_id": record["scope_id"],
        "packet_digest": record["packet_digest"],
        "extension_id": "program-campaign-v5",
        "authorization_digest": _digest(record),
        "proposal_digest": _digest(core),
        "expires_at": record["expires_at"],
    }
    stopped_scope = {
        "state": "stopped",
        "packet_digest": record["packet_digest"],
        "authorization_digest": value["authorization_digest"],
        "data": {"authorization_record": record},
    }

    class Rows:
        def __init__(self, row):
            self.row = row

        def fetchone(self):
            return self.row

    class Connection:
        def execute(self, query, params=None):
            text = str(query)
            if "FROM workspace_d5_campaign_extensions" in text:
                return Rows((value,))
            if "FROM workspace_d5_scopes" in text:
                return Rows((stopped_scope,))
            if "FROM workspace_d5_campaign_revocations" in text:
                return Rows(None)
            raise AssertionError("Unexpected in-memory query")

    monkeypatch.setattr(
        "src.workspace.d5_campaign_extension.predecessor_seal", lambda *_: deepcopy(sealed_legacy)
    )
    assert parent(Connection(), "program")["predecessor_seal"] == sealed_legacy
    changed = deepcopy(sealed_legacy)
    if change == "revocation":
        changed["capacity_revocations"] = ["new-revocation-digest"]
    else:
        changed["original_programme"] = "changed-programme"
    monkeypatch.setattr("src.workspace.d5_campaign_extension.predecessor_seal", lambda *_: changed)
    with pytest.raises(AdmissionError, match="parent_or_stopped_scope_drift"):
        parent(Connection(), "program")
