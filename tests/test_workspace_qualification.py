"""Read-only qualification packets retain blank judgments and exact initial wire bodies."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

from src.workspace import qualification as q
from src.workspace.material import extract_text
from tests import test_workspace_executor as support

store = support.store
if hasattr(support, "workspace_pg"):
    workspace_pg_proc = support.workspace_pg_proc
    workspace_pg = support.workspace_pg
pytestmark = pytest.mark.integration


def test_review_pool_is_representative_but_not_a_human_label_or_checker_measurement():
    materials = [
        extract_text(
            "A retained public abstract with a stated limitation.",
            work_id=f"work{i}",
            version_id=f"version{i}",
            scope="abstract",
        )
        for i in range(3)
    ]
    cases = q.review_cases(materials)
    assert len(cases) == 24 and len({c["id"] for c in cases}) == 24
    assert cases == q.review_cases(materials)
    assert {c["challenge_type"] for c in cases} >= {
        "unsupported_generalization",
        "missing_evidence",
        "wrong_source_version",
        "scope_violation",
        "extraction_failure",
    }
    for item in cases:
        assert (
            item["human_label"]
            is item["human_reason"]
            is item["annotator"]
            is item["checker_verdict"]
            is None
        )
        assert item["review_status"] == "unlabelled"
        assert item["source_material"]["complete"]
    assert q.review_cases([]) == []


def test_exact_requests_read_only_and_cli_never_contact_or_approve(
    store, tmp_path, monkeypatch, capsys
):
    item, material, data = support.source(store)
    proposal = {
        "sources": [
            {"material_id": material, "job_kind": "summary"},
            {"material_id": material, "job_kind": "deep_dive"},
        ]
    }
    with store.pool.connection() as conn:
        before = conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0]
    result = q.packet(store, "a", proposal)
    assert len(result["jobs"]) == 2 and len(result["claim_span_review"]) == 8
    assert (
        result["provider_contacts"] == 0
        and not result["approved"]
        and not result["checker_qualified"]
    )
    for job in result["jobs"]:
        body = job["initial_generation"]["body"]
        assert body["model"] == "claude-sonnet-4-6" and "output_config" in body
        assert job["measured_tokens"] is None
        assert job["initial_count_request"] == {
            k: v for k, v in body.items() if k not in {"max_tokens", "temperature"}
        }
        assert json.loads(body["messages"][0]["content"])["sources"][0]["material_id"] == material
    with store.pool.connection() as conn:
        assert (
            conn.execute("SELECT count(*) FROM workspace_generation_jobs").fetchone()[0] == before
        )
        assert conn.execute("SELECT count(*) FROM workspace_budget_policies").fetchone()[0] == 0
    proposal_file, output = tmp_path / "proposal.json", tmp_path / "packet" / "packet.json"
    proposal_file.write_text(json.dumps(proposal))
    monkeypatch.setattr(q, "get_pool", lambda: store.pool)
    close = Mock()
    monkeypatch.setattr(q, "close_pool", close)
    monkeypatch.setattr(
        "sys.argv",
        [
            "qualification",
            "--owner",
            "a",
            "--proposal",
            str(proposal_file),
            "--output",
            str(output),
        ],
    )
    q.main()
    assert (
        json.loads(output.read_text()) == json.loads(json.dumps(result))
        and "provider contacts 0" in capsys.readouterr().out
    )
    close.assert_called_once()
