"""Calibration consumes the real campaign writer, not an invented scores fixture."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from src.calibration.pool import build_pool
from src.campaign.execute import arm_graph_probe, execute_campaign
from src.campaign.planner import (
    CampaignRequest,
    default_campaign_budget,
    default_episode_budget,
    plan_campaign,
    write_campaign,
)
from src.config import Settings
from src.contracts.benchmark_adapters import suite_ref
from src.contracts.registry import LocalRegistry
from src.eval.mock_judge import build_mock_judge_scorer

pytestmark = pytest.mark.integration
REGISTRY = Path(__file__).resolve().parents[1] / "eval_registry"


@pytest.fixture(scope="module")
def emitted_episode(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[str, Path, Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("calibration-emitted")
    config = Settings(
        _env_file=None,
        use_mock_data=True,
        anthropic_api_key="local-preview-disabled",
        enable_tracing=False,
        enable_metrics=False,
        enable_checkpointing=False,
        enable_semantic_scholar=False,
        enable_hitl=False,
        contract_shadow="shadow",
        contract_event_capture="evaluation_only",
    )
    request = CampaignRequest(
        protocol_id="research-policy-v1-stage-0",
        stage="stage-0-qualification",
        suite_ref=suite_ref(REGISTRY, "research-policy-v1"),
        case_ids=("hallucination-mitigation",),
        arms=("A",),
        repeats=1,
        corpus_mode="snapshot",
        seed=0,
        episode_budget=default_episode_budget(config, ("A",)),
        campaign_budget=default_campaign_budget(),
    )
    plan = plan_campaign(config, request, resolver=LocalRegistry(REGISTRY))
    write_campaign(root, plan)
    result = execute_campaign(
        config,
        root=root,
        plan=plan,
        graph_probe=arm_graph_probe(config),
        scorer=build_mock_judge_scorer(config),
        sink_root=root / "trajectories",
    )
    assert result.model_calls == 0
    directory = root / plan.campaign_id
    record_path = next(directory.rglob("episode-record.json"))
    record = json.loads(record_path.read_text())
    assert record["scores"]["judges_run"] is True
    assert record["scores"]["metrics"]["faithfulness"]["claims"]
    assert (record_path.parent / "scores.json").exists()
    return plan.campaign_id, root, record_path.parent, record


def test_real_emitted_record_is_read_and_source_scope_is_preserved(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, root, episode_dir, record = emitted_episode
    out = build_pool(campaign_id, root, output=tmp_path / "pool.json")
    pool = json.loads(out.read_text())
    assert pool["items"]
    faithfulness = [item for item in pool["items"] if item["slice"] == "faithfulness"]
    assert len(faithfulness) == len(record["scores"]["metrics"]["faithfulness"]["claims"])
    assert {item["source_scope"] for item in faithfulness} == {"abstract_only"}
    assert all(item["chunks"] == "" for item in faithfulness)
    assert pool["stress_set_separate"] is True
    assert all("real_id" not in item for item in pool["items"])


def _copy_episode(
    emitted: tuple[str, Path, Path, dict[str, Any]], target: Path
) -> tuple[str, Path, dict[str, Any], dict[str, Any]]:
    campaign_id, _, episode_dir, _ = emitted
    copied = target / "one-episode"
    shutil.copytree(episode_dir, copied)
    state = json.loads((copied / "episode-state.json").read_text())
    record = json.loads((copied / "episode-record.json").read_text())
    return campaign_id, copied, state, record


def _write_inputs(directory: Path, state: dict[str, Any], record: dict[str, Any]) -> None:
    (directory / "episode-state.json").write_text(json.dumps(state))
    (directory / "episode-record.json").write_text(json.dumps(record))


def test_grouped_chunks_only_appear_when_the_metric_actually_saw_them(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    paper = state["papers"][0]
    paper_id = paper["id"]
    state["reader"]["chunks"] = {
        paper_id: [{"text": "First retained chunk."}, {"text": "Second retained chunk."}],
        "another-paper": [{"text": "Never attach this unrelated chunk."}],
    }
    faithfulness = record["scores"]["metrics"]["faithfulness"]
    faithfulness["claims"] = [
        {
            "claim": "An explicit factual claim.",
            "paper_id": paper_id,
            "supported": False,
            "reason": "Source contradicts it.",
        }
    ]
    faithfulness["source_scope"] = "abstract_and_chunks"
    _write_inputs(episode, state, record)
    first = json.loads(
        build_pool(campaign_id, tmp_path, output=tmp_path / "first.json").read_text()
    )
    claim = next(item for item in first["items"] if item["slice"] == "faithfulness")
    assert claim["abstract"] == paper["abstract"]
    assert claim["chunks"] == "First retained chunk.\n\nSecond retained chunk."
    assert claim["source_scope"] == "abstract_and_chunks" and claim["material_complete"]
    assert claim["judge_verdict"] == "failed"
    # The same retained snapshot is not evidence that an abstract-only judge saw
    # those chunks. Annotators must receive the same substrate the judge did.
    faithfulness["source_scope"] = "abstract_only"
    _write_inputs(episode, state, record)
    second = json.loads(
        build_pool(campaign_id, tmp_path, output=tmp_path / "second.json").read_text()
    )
    claim = next(item for item in second["items"] if item["slice"] == "faithfulness")
    assert claim["chunks"] == "" and claim["source_scope"] == "abstract_only"


def test_retrieval_gets_the_entire_indexed_paper_list_completeness_gets_report(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    pool = json.loads(build_pool(campaign_id, tmp_path, output=tmp_path / "pool.json").read_text())
    retrieval = [item for item in pool["items"] if item["slice"] == "retrieval_recall"]
    completeness = [item for item in pool["items"] if item["slice"] == "completeness"]
    assert len(retrieval) == len(record["scores"]["metrics"]["retrieval_recall"]["coverage"])
    assert retrieval[0]["label_type"] == "retrieval_recall"
    assert retrieval[0]["source_scope"] == "retrieved_titles_and_abstracts"
    assert [(p["paper_id"], p["abstract"]) for p in retrieval[0]["papers"]] == [
        (p["id"], p["abstract"]) for p in state["papers"]
    ]
    assert [p["index"] for p in retrieval[0]["papers"]] == list(range(len(state["papers"])))
    assert completeness[0]["report"] == state["report"]["text"]
    assert completeness[0]["source_scope"] == "report" and completeness[0]["chunks"] == ""


def test_none_verdict_stays_abstain_and_null_metric_is_recorded_without_fake_claim(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    record["scores"]["metrics"]["faithfulness"] = {
        "score": None,
        "source_scope": "abstract_only",
        "claims": [
            {
                "claim": "Missing source.",
                "supported": None,
                "reason": "Source missing",
                "paper_id": None,
            }
        ],
    }
    record["scores"]["metrics"]["completeness"] = None
    record["scores"]["metrics"]["retrieval_recall"] = {
        "score": None,
        "reason": "no_expected_topics",
        "coverage": [],
    }
    record["scores"]["judge_failure_reasons"] = {"completeness": "judge_failed"}
    _write_inputs(episode, state, record)
    pool = json.loads(build_pool(campaign_id, tmp_path, output=tmp_path / "pool.json").read_text())
    assert pool["strata_counts"] == {"faithfulness:abstain": 1}
    claim = pool["items"][0]
    assert claim["judge_verdict"] == "abstain" and claim["abstention_reason"] == "Source missing"
    assert claim["abstract"] == "" and claim["chunks"] == "" and not claim["material_complete"]
    assert {item["metric"]: item["reason"] for item in pool["unscored_metrics"]} == {
        "completeness": "judge_failed",
        "retrieval_recall": "no_expected_topics",
    }
    assert all(item["score"] is None for item in pool["unscored_metrics"])
    # A failed instrument can produce diagnostics without fabricating calibration
    # items; the empty label pool is explicit rather than converted into zeroes.
    record["scores"]["metrics"]["faithfulness"] = None
    _write_inputs(episode, state, record)
    empty = json.loads(
        build_pool(campaign_id, tmp_path, output=tmp_path / "empty.json").read_text()
    )
    assert empty["items"] == [] and len(empty["unscored_metrics"]) == 3


def test_blinding_is_stable_after_relocation_and_scans_real_report_text(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, first, state, record = _copy_episode(emitted_episode, tmp_path / "first")
    _, second, _, _ = _copy_episode(emitted_episode, tmp_path / "second")
    a = build_pool(campaign_id, first, output=tmp_path / "a.json").read_text()
    b = build_pool(campaign_id, second, output=tmp_path / "b.json").read_text()
    assert a == b
    c = json.loads(
        build_pool(campaign_id, second, output=tmp_path / "c.json", seed="another-seed").read_text()
    )
    assert json.loads(a)["items"][0]["item_id"] != c["items"][0]["item_id"]
    state["report"]["text"] = "The arm-A system produced this report."
    _write_inputs(first, state, record)
    with pytest.raises(ValueError, match="blinding leak"):
        build_pool(campaign_id, first, output=tmp_path / "leaked.json")
    assert not (tmp_path / "leaked.json").exists()


def test_actual_record_is_authoritative_over_stale_legacy_scores(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    (episode / "scores.json").write_text(
        json.dumps(
            {"scores": {"faithfulness": {"claims": [{"claim": "wrong file", "supported": True}]}}}
        )
    )
    pool = json.loads(build_pool(campaign_id, tmp_path, output=tmp_path / "pool.json").read_text())
    assert all(item["claim"] != "wrong file" for item in pool["items"])
    (episode / "episode-record.json").write_text("truncated JSON")
    with pytest.raises(ValueError, match="invalid emitted episode record"):
        build_pool(campaign_id, tmp_path, output=tmp_path / "corrupt.json")


def test_missing_scope_reduced_material_and_missing_report_are_explicit(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    metric = record["scores"]["metrics"]["faithfulness"]
    metric["claims"] = [
        {"claim": "Claim.", "paper_id": state["papers"][0]["id"], "supported": True}
    ]
    metric.pop("source_scope", None)
    state["report"] = {"digest": "not-retained"}
    _write_inputs(episode, state, record)
    pool = json.loads(build_pool(campaign_id, tmp_path, output=tmp_path / "pool.json").read_text())
    claim = next(item for item in pool["items"] if item["slice"] == "faithfulness")
    coverage = next(item for item in pool["items"] if item["slice"] == "completeness")
    assert (
        claim["source_scope"] == "unrecorded"
        and claim["material_gap"] == "judge_source_scope_not_recorded"
    )
    assert (
        not coverage["material_complete"] and coverage["material_gap"] == "report_text_not_retained"
    )
    metric["source_scope"] = "abstract_and_chunks"
    state["reader"]["chunk_text_retained"] = False
    _write_inputs(episode, state, record)
    pool = json.loads(
        build_pool(campaign_id, tmp_path, output=tmp_path / "reduced.json").read_text()
    )
    claim = next(item for item in pool["items"] if item["slice"] == "faithfulness")
    assert claim["material_gap"] == "judged_chunk_text_not_retained"
    state["papers"][0]["abstract"] = ""
    _write_inputs(episode, state, record)
    pool = json.loads(
        build_pool(campaign_id, tmp_path, output=tmp_path / "no-text.json").read_text()
    )
    claim = next(item for item in pool["items"] if item["slice"] == "faithfulness")
    assert claim["material_gap"] == "source_text_not_retained"


def test_legacy_pool_inputs_remain_readable_but_never_invent_scope(tmp_path: Path) -> None:
    episode = tmp_path / "episode"
    episode.mkdir()
    state = {
        "campaign_id": "legacy-campaign-c7",
        "papers": [{"id": "p", "abstract": "a source"}],
        "reader": {"chunks": [{"paper_id": "p", "chunk": "legacy ranked text"}]},
    }
    record = {
        "scores": {
            "faithfulness": {
                "source_scope": "abstract_and_chunks",
                "claims": [{"claim": "claim", "paper_id": "p", "supported": True}],
            }
        }
    }
    (episode / "episode-state.json").write_text(json.dumps(state))
    (episode / "record.json").write_text("broken legacy file")
    (episode / "scores.json").write_text(json.dumps(record))
    pool = json.loads(
        build_pool("legacy-campaign-c7", tmp_path, output=tmp_path / "pool.json").read_text()
    )
    assert pool["items"][0]["chunks"] == "legacy ranked text"
    assert pool["items"][0]["judge_verdict"] == "passed"
    (episode / "scores.json").write_text("[]")
    with pytest.raises(ValueError, match="no episode verdicts"):
        build_pool("legacy-campaign-c7", tmp_path, output=tmp_path / "empty.json")


def test_retained_empty_report_is_not_confused_with_missing_text(
    emitted_episode: tuple[str, Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    campaign_id, episode, state, record = _copy_episode(emitted_episode, tmp_path)
    state["report"]["text"] = ""
    _write_inputs(episode, state, record)
    pool = json.loads(build_pool(campaign_id, tmp_path, output=tmp_path / "pool.json").read_text())
    coverage = next(item for item in pool["items"] if item["slice"] == "completeness")
    assert coverage["report"] == "" and coverage["material_complete"]
    assert coverage["material_gap"] is None
