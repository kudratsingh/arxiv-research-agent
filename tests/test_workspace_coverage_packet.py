"""Frozen development schedule, exact stage schemas and policy boundary controls."""

from __future__ import annotations

import gzip
import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.workspace import d5_coverage_policy as policy
from src.workspace import d5_coverage_replay as replay
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_benchmark import read
from src.workspace.d5_coverage_packet import CASE_IDS, PREDECESSOR, freeze_controls
from src.workspace.d5_freeze import compile_inputs, verify
from src.workspace.qualification_budget import PROGRAM_LIMITS

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def packet():
    m = read(
        ROOT
        / "planning/14-explore-and-research-modes/d5/evidence/request-coverage-v8/proposal.json.gz"
    )
    archive = json.loads(
        gzip.decompress(
            (ROOT / "tests/fixtures/d5/stage-c-v8r4b/coverage-controls.json.gz").read_bytes()
        )
    )
    binding = {
        "program_id": "unit",
        "capacity_proposal_digest": "capacity",
        "limits": policy.PROGRAM_LIMITS,
        "expires_at": "2026-11-14T07:24:01+00:00",
    }
    snap = {
        "tables": {
            "workspace_material": [{"data": v} for v in archive["materials"]],
            "workspace_versions": [],
        },
        "program_id": "unit",
        "history": {},
        "profile": {},
    }
    return freeze_controls(m, snap, binding)


def test_named_development_cases_compile_to_exact_A_B_bindings(packet):
    verify(packet)
    compiled = compile_inputs(packet)
    assert set(compiled) == set(CASE_IDS) | {"measure-1", "measure-2", "measure-3"}
    assert sum(v["stage"] == "A" for v in compiled.values()) == 3
    assert sum(v["stage"] == "B" for v in compiled.values()) == 3
    assert packet["probes"] == [] and all(c["cohort"] == "development" for c in packet["cases"])
    for row in packet["measurements"]:
        c = next(c for c in packet["cases"] if c["id"] == row["workflow"])
        assert row["body"] == {
            k: v
            for k, v in c["sealed"]["candidate_initial_wire"].items()
            if k not in {"max_tokens", "temperature"}
        }
        assert row["request_digest"] == _digest(row["body"])
        assert row["model"] == "claude-sonnet-5-5"
    assert packet["limits"]["new_usd"] == "1.35"
    assert all(
        e["input"]["settings"]["d5_scope_profile"] == policy.PROFILE for e in compiled.values()
    )


@pytest.mark.parametrize(
    "change",
    [
        "held_out",
        "id",
        "order",
        "extra",
        "limits",
        "model",
        "measurement",
        "checker",
        "reuse",
        "context",
        "source",
        "approval",
        "code",
        "predecessor",
    ],
)
def test_recomputed_digest_cannot_broaden_or_drift_scope(packet, change):
    p = deepcopy(packet)
    if change == "held_out":
        p["cases"][0]["cohort"] = "fresh_system"
    elif change == "id":
        p["cases"][0]["id"] = "new-held-out"
    elif change == "order":
        p["cases"].reverse()
    elif change == "extra":
        p["cases"].append(deepcopy(p["cases"][0]))
    elif change == "limits":
        p["limits"]["messages"] = 13
    elif change == "model":
        p["operation_routes"]["check_recheck_probe"]["model"] = "unapproved"
    elif change == "measurement":
        p["measurements"][0]["body"]["model"] = "unapproved"
    elif change == "checker":
        p["checker_schemas"]["wire"] = {}
    elif change == "reuse":
        p["measurement_reuse"] = {"measure-1": {"old": "receipt"}}
    elif change == "context":
        p["cases"][0]["question"] = "Different request"
    elif change == "source":
        p["cases"][0]["sealed"]["units"] = {}
    elif change == "approval":
        p["approved"] = True
    elif change == "code":
        p["code"] = {}
    else:
        p["predecessor_proposal"] = "other"
    p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
    with pytest.raises((AdmissionError, KeyError)):
        verify(p)


def test_new_freeze_cannot_approve_or_replace_predecessor(packet):
    with pytest.raises(AdmissionError):
        freeze_controls({"packet_digest": PREDECESSOR, "approved": True}, {}, {})


class Rows:
    def __init__(self, values):
        self.values = iter(values)

    def execute(self, *_):
        return SimpleNamespace(fetchone=lambda: next(self.values))


def metadata():
    expiry = datetime.now(UTC) + timedelta(hours=10)
    receipt = {"amendment": {"amended_limits": policy.PROGRAM_LIMITS}}
    row = (receipt, _digest(receipt), "capacity", expiry)
    expected = {
        "program_id": "unit",
        "original_authorization_digest": "original",
        "capacity_authorization_digest": row[1],
        "capacity_proposal_digest": "capacity",
        "limits": policy.PROGRAM_LIMITS,
        "expires_at": expiry.isoformat(),
    }
    return row, expected, expiry


@pytest.mark.parametrize("defect", ["none", "missing", "hash", "expiry", "binding", "limits"])
def test_programme_metadata_recheck_after_shared_guard(defect):
    row, expected, expiry = metadata()
    if defect == "missing":
        row = None
    elif defect == "hash":
        row = (row[0], "bad", row[2], row[3])
    elif defect == "expiry":
        row = (*row[:3], datetime.now(UTC) - timedelta(seconds=1))
    elif defect == "binding":
        expected["original_authorization_digest"] = "other"
    elif defect == "limits":
        expected["limits"] = PROGRAM_LIMITS
    conn = Rows([("original",), row])
    if defect == "none":
        policy.validate_programme(conn, "unit", expected, expiry, already_guarded=True)
    else:
        with pytest.raises(AdmissionError):
            policy.validate_programme(conn, "unit", expected, expiry, already_guarded=True)


@pytest.mark.parametrize("defect", ["missing", "bad_limits", "expired", "valid"])
def test_registration_full_programme_audit(defect, monkeypatch):
    row, expected, expiry = metadata()
    from src.workspace import programme_amendments as amendments

    monkeypatch.setattr(
        amendments,
        "effective_limits",
        lambda *a, **kw: PROGRAM_LIMITS if defect == "bad_limits" else policy.PROGRAM_LIMITS,
    )
    if defect == "missing":
        row = None
    elif defect == "expired":
        row = (*row[:3], datetime.now(UTC) - timedelta(seconds=1))
    if defect == "valid":
        assert policy.programme(Rows([("original",), row]), "unit") == expected
    else:
        with pytest.raises(AdmissionError):
            policy.programme(Rows([("original",), row]), "unit")


def test_parent_A_only_24h_and_exact_schedule(monkeypatch):
    now = datetime.now(UTC)
    compiled = {
        str(i): {
            "stage": "A" if i < 3 else "B",
            "input": {"settings": {"d5_programme_binding": {"sealed": "programme"}}},
        }
        for i in range(6)
    }
    receipt = {
        "stages": ["A"],
        "approved_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    called = []
    monkeypatch.setattr(policy, "validate_programme", lambda *a, **kw: called.append(a))
    policy.registration(None, "unit", compiled, receipt)
    assert len(called) == 1
    for change in ("B", "expiry", "schedule", "binding"):
        c, r = deepcopy(compiled), deepcopy(receipt)
        if change == "B":
            r["stages"] = ["A", "B"]
        elif change == "expiry":
            r["expires_at"] = (now + timedelta(days=2)).isoformat()
        elif change == "schedule":
            c.pop("5")
        else:
            c["0"]["input"]["settings"]["d5_programme_binding"] = {}
        with pytest.raises(AdmissionError):
            policy.registration(None, "unit", c, r)


@pytest.mark.parametrize(
    "stage,history,amount,endpoint,ids,refused",
    [
        ("A", {"counts": 3}, None, "messages/count_tokens", 1, True),
        ("A", {}, None, "messages", 0, True),
        ("B", {"messages": 12}, None, "messages", 3, True),
        ("B", {"counts": 12}, None, "messages/count_tokens", 3, True),
        ("B", {"counts": 9}, Decimal(".45"), None, 2, True),
        ("B", {}, Decimal(".45"), None, 3, True),
        ("B", {"known_usd": ".9"}, Decimal(".45"), None, 2, False),
        ("B", {"known_usd": ".900001"}, Decimal(".45"), None, 2, True),
        ("B", {"pending_usd": ".91"}, Decimal(".45"), None, 2, True),
        ("D", {}, None, None, 0, True),
    ],
)
def test_stage_caps_and_complete_workflow_spend(
    stage, history, amount, endpoint, ids, refused, monkeypatch
):
    monkeypatch.setattr(policy, "validate_programme", lambda *a, **kw: None)
    monkeypatch.setattr(policy, "measurements", lambda *a: None)
    h = {
        "messages": 0,
        "counts": 0,
        "known_usd": "0",
        "pending_usd": "0",
        "unknown_usd": "0",
        **history,
    }
    monkeypatch.setattr(policy, "census", lambda *a, **kw: h)
    conn = SimpleNamespace(execute=lambda *a: [(str(i),) for i in range(ids)])
    bound = {
        "id": "unit",
        "program_id": "unit",
        "authorization_record": {
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        },
        "case": {"stage": stage},
        "stage_authorizations": {"A": "a", "B": "b"},
        "cases": {},
        "members": ["unit"],
    }
    settings = {
        "program_amendment_proposal_digest": "capacity",
        "d5_programme_binding": {"capacity_proposal_digest": "capacity"},
    }
    if refused:
        with pytest.raises(AdmissionError):
            policy.guard(conn, bound, "unit", settings, amount=amount, endpoint=endpoint)
    else:
        policy.guard(conn, bound, "unit", settings, amount=amount, endpoint=endpoint)


def test_offline_fixture_grant_refuses_unmarked_database(packet):
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(fetchone=lambda: None))
    store = SimpleNamespace(pool=SimpleNamespace(connection=lambda: nullcontext(conn)))
    with pytest.raises(AdmissionError, match="fixture_database_required"):
        replay.fixture_A(store, packet)


def test_profile_and_operation_bindings_cannot_be_substituted(packet):
    from src.workspace.d5_adapter import prepare_input
    from src.workspace.d5_scope import limits_for, valid_limits

    assert limits_for({"d5_scope_profile": policy.PROFILE}) == policy.LIMITS
    assert valid_limits(policy.LIMITS)
    assert not valid_limits({**policy.LIMITS, "counts": 16})
    with pytest.raises(AdmissionError):
        limits_for({"d5_scope_profile": "unknown"})
    c = packet["cases"][0]["sealed"]
    for profile, binding, operation in [
        ("unknown", {}, "workflow"),
        (policy.PROFILE, None, "workflow"),
        (policy.PROFILE, {}, "probe"),
    ]:
        with pytest.raises(AdmissionError):
            prepare_input(
                c,
                scope_id="d5-unit",
                packet_digest="unit",
                case_id="case",
                operation=operation,
                scope_profile=profile,
                programme_binding=binding,
            )


def test_predecessor_contents_cannot_be_rewritten(packet, monkeypatch):
    import src.workspace.d5_benchmark as benchmark

    monkeypatch.setattr(
        benchmark, "read", lambda *_: {"packet_digest": PREDECESSOR, "approved": True}
    )
    with pytest.raises(AdmissionError, match="predecessor_manifest"):
        verify(packet)


@pytest.mark.parametrize(
    "key,enabled", [("local-preview-disabled", "0"), ("synthetic-not-a-real-key", "1")]
)
def test_cli_stops_without_explicit_offline_sentinel(tmp_path, monkeypatch, key, enabled):
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", enabled)
    monkeypatch.setattr(
        "sys.argv", ["coverage", "capture", "--snapshot", str(tmp_path / "snapshot.json.gz")]
    )
    with pytest.raises(AdmissionError, match="offline_disabled_key"):
        replay.main()
    assert not list(tmp_path.iterdir())


def test_cli_freeze_and_replay_entrypoints_are_separate_from_real_authorization(
    packet, tmp_path, monkeypatch
):
    import src.workspace.d5_benchmark as benchmark
    from src.workspace.d5_coverage_packet import markdown_controls

    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"programme": packet["programme"]}))
    manifest = (
        ROOT
        / "planning/14-explore-and-research-modes/d5/evidence/request-coverage-v8/proposal.json.gz"
    )
    p = tmp_path / "packet.json.gz"
    monkeypatch.setattr(replay, "freeze_controls", lambda *args: packet)
    monkeypatch.setattr(
        "sys.argv",
        [
            "coverage",
            "freeze",
            "--snapshot",
            str(snapshot),
            "--proposal",
            str(manifest),
            "--packet",
            str(p),
        ],
    )
    replay.main()
    assert read(p)["approved"] is False
    monkeypatch.setenv("D5_POSTGRES_URL", "ignored-fixture")
    monkeypatch.setattr(benchmark, "database", lambda *_: nullcontext(object()))

    async def fake(*_):
        return {"B": {"cases": [{"completion": True}]}}

    monkeypatch.setattr(replay, "replay", fake)
    monkeypatch.setattr(
        "sys.argv",
        [
            "coverage",
            "replay",
            "--snapshot",
            str(snapshot),
            "--packet",
            str(p),
            "--out",
            str(tmp_path / "out"),
        ],
    )
    replay.main()
    assert (tmp_path / "out/REPLAY.json").exists()
    with pytest.raises(SystemExit):
        replay.main()
    text = markdown_controls(
        {
            "basis": "Synthetic control",
            "cases": [{"id": "x", "state": "ready"}],
            "acceptance": "HOLD",
        }
    )
    assert "development" in text and "HOLD" in text


def test_capture_cli_does_not_write_permission(tmp_path, monkeypatch):
    import src.workspace.d5_benchmark as benchmark

    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-preview-disabled")
    monkeypatch.setenv("WORKSPACE_D5_OFFLINE", "1")
    monkeypatch.setenv("D5_PUBLIC_POSTGRES_URL", "public")
    monkeypatch.setenv("D5_LEDGER_POSTGRES_URL", "ledger")
    monkeypatch.setattr(benchmark, "database", lambda *_: nullcontext(object()))
    monkeypatch.setattr(
        replay, "capture", lambda *args: {"synthetic": "snapshot only", "approval_created": False}
    )
    path = tmp_path / "snapshot.json.gz"
    monkeypatch.setattr("sys.argv", ["coverage", "capture", "--snapshot", str(path)])
    replay.main()
    assert read(path)["approval_created"] is False
