"""The funded episode path: snapshot, live judge, cap, recovery, stop rules.

Its own module rather than a section of `tests/test_campaign_execution.py`,
for the reason that module's own header gives: it installs a
module-scoped tripwire over `src.llm._get_client` before any per-test
fixture runs, and several claims here are specifically about what happens
*at* the gateway — a judge call priced against one accumulator rather
than another, a graph stopped between calls by a bound cap. A test whose
subject is that seam cannot live under a fixture that replaces it.

Six groups, one per work-order item.

1. **EL-05, the snapshot.** Every episode of a real mock-mode pass writes
   `episode-state.json` before it is scored; the file carries the
   planner's decomposition, the papers with their ids, the citations, the
   evidence, the reader's ranked chunks grouped by paper, the critic's
   decision per pass, the abstract-only tally, the retrieval window and
   the ids it returned; it excludes `messages`; it fits its byte bound;
   and it passes the ADR 0096 structural screen. A snapshot that cannot
   fit or cannot pass is *reduced* through four declared levels and, in
   the last resort, stubbed — never raised.
2. **EL-17, the per-episode cap.** A fake graph whose nodes spend real
   (fake-priced) money through the real gateway checks stops mid-graph
   with `BUDGET_STOPPED`, keeps the partial report, and overshoots by at
   most one reader fan-out.
3. **EL-01/EL-02, the live judge.** The scorer refuses to construct under
   mock data and under the sentinel; it writes the same
   `detail["metrics"]` layout the mock scorer writes; its calls land on
   its *own* accumulator with its *own* cap, leaving the workflow's
   untouched; and a judge cap reached mid-pass nulls the remaining
   rubrics with `judge_budget_exhausted` while the episode completes.
4. **EL-03, scoring never strands.** A scorer that raises still leaves a
   `completion.json`, and an episode interrupted between its snapshot and
   its receipt is scored from the snapshot on the next pass without the
   graph running again.
5. **EL-15, the stop rules.** Provider drift, source drift and the judge
   failure rate each stop the pass between episodes with everything
   already completed kept and counted.
6. **The log contract.** Every name and field added here is in the closed
   registry.

Nothing in this module makes a model call or opens a socket, and a spy
over both proves it rather than a promise.
"""

from __future__ import annotations

import json
import socket
import tempfile
from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

import src.llm as llm_module
from src.campaign.errors import CampaignError
from src.campaign.execute import (
    COMPLETION_FILENAME,
    EPISODE_STATE_FILENAME,
    JUDGE_FAILURE_EARLY_TRIGGER,
    MAX_EPISODE_STATE_BYTES,
    PRIMARY_METRIC,
    RECORD_FILENAME,
    SCORES_FILENAME,
    STATE_RETENTION_LEVELS,
    EpisodeRun,
    EpisodeScores,
    EpisodeStatePolicy,
    GraphEpisodeRunner,
    _StopRules,
    arm_graph_probe,
    build_episode_state,
    execute_campaign,
    provider_fingerprint,
    read_episode_state,
    write_episode_state,
)
from src.campaign.ledger import EpisodeScoreReceipt, LedgerStatus
from src.campaign.matrix import PlannedEpisode
from src.campaign.scoring import (
    JUDGED_METRICS,
    REASON_BUDGET,
    REASON_FAILED,
    build_live_judge_scorer,
    judge_cost_scope,
)
from src.config import Settings
from src.contracts.run_manifest import CompletionStatus, RunReason
from src.observability.logging import ALLOWED_EXTRA_KEYS, KNOWN_EVENTS
from tests.test_campaign_execution import (
    SCRIPTED_REPORT,
    SLICE_CASES,
    ScriptedRunner,
    available_scorer,
    config,
    install_tripwire,
    materialize,
    request,
)

#: One judged benchmark case, so the live scorer has an expected-topic
#: set to score against. Named rather than taken from the slice, because
#: the slice is chosen for speed and this one is chosen for being in
#: `BENCHMARK_QUERIES`.
JUDGED_CASE = "hallucination-mitigation"

#: A priced model id, so `record_llm_call` computes a real number rather
#: than falling back and warning. Haiku, because its $1/$5 rates make the
#: arithmetic in the cap assertions readable.
PRICED_MODEL = "claude-haiku-4-5"


def paid_config(**overrides: Any) -> Settings:
    """A configuration the live judge scorer will consent to construct under.

    Not mock data and not the sentinel, which are precisely the two the
    scorer refuses. The key is a placeholder that is deliberately *not*
    `sk-`-shaped: a credential-shaped string in a test fixture is one
    copy-paste away from an artifact body, and the ADR 0096 screen would
    refuse that body rather than the mistake that produced it.
    """
    return config(
        use_mock_data=False,
        anthropic_api_key=SecretStr("funded-path-test-key"),
        anthropic_model=PRICED_MODEL,
        eval_judge_model=PRICED_MODEL,
        **overrides,
    )


def planned_episode(directory: Path) -> PlannedEpisode:
    """One real `PlannedEpisode`, taken from a materialized one-slot campaign.

    Real rather than hand-built: every identity on it — `episode_key`,
    `run_id`, `output_path` — is derived from the sealed protocol and the
    registry lock, and a constructed one would let a test agree with a
    derivation it had copied rather than with the one that runs.
    """
    cfg = config()
    plan = materialize(
        directory, cfg, request(cfg, cases=(JUDGED_CASE,), arms=("A",), repeats=1)
    )
    return plan.runnable[0]


@cache
def sample_episode() -> PlannedEpisode:
    """The same real episode, materialized once for the whole module.

    Cached because materializing a campaign resolves the registry, seals
    a manifest and writes a directory — a second of wall clock that
    dozens of assertions here do not need repeated, and which cannot be
    repeated into the same root anyway (`seal` refuses to overwrite,
    correctly).
    """
    return planned_episode(Path(tempfile.mkdtemp(prefix="le-s-episode-")))


def rich_run(**overrides: Any) -> EpisodeRun:
    """An `EpisodeRun` carrying one of everything the snapshot claims to keep."""
    state: dict[str, Any] = {
        "draft_report": SCRIPTED_REPORT,
        "sub_questions": ["what is measured", "how is it measured"],
        "search_queries": ["retrieval grounding", "citation faithfulness"],
        "tried_search_queries": ["retrieval grounding"],
        "papers": [
            {
                "id": "2401.00001",
                "title": "On Grounding",
                "authors": ["A. Author"],
                "abstract": "An abstract about grounding.",
                "url": "https://arxiv.org/abs/2401.00001",
                "pdf_url": "https://arxiv.org/pdf/2401.00001",
            }
        ],
        "citations": [
            {
                "paper_id": "2401.00001",
                "title": "On Grounding",
                "authors": ["A. Author"],
                "year": "2024",
                "url": "https://arxiv.org/abs/2401.00001",
            }
        ],
        "paper_analyses": [
            {
                "paper_id": "2401.00001",
                "title": "On Grounding",
                "key_findings": ["grounding helps"],
                "methodology": "a study",
                "results_summary": "it helped",
                "limitations": "small n",
                "relevance": 0.9,
            }
        ],
        "evidence": [
            {
                "claim": "grounding helps",
                "paper_id": "2401.00001",
                "section": "results",
                "source_text": "The ranked chunk the reader actually read.",
                "relevance_score": 0.81,
                "supports_question": "what is measured",
            }
        ],
        "stop_reason": "critic_approved",
        "iteration": 2,
        "loop_iterations": 0,
        "verified": True,
        "verification_verdict": "pass",
        "verification_reason": "",
        "repair_count": 0,
        "repair_action": "",
        "messages": [object()],
    }
    state.update(overrides.pop("state", {}))
    return EpisodeRun(
        status=CompletionStatus.SUCCEEDED,
        reason=None,
        visited=("planner", "search", "reader", "synthesizer", "critic"),
        state=state,
        workflow_cost_usd="0.012345",
        model_calls=7,
        elapsed_seconds=1.5,
        iterations=(
            {
                "node": "critic",
                "quality_score": 0.4,
                "revision_needed": True,
                "revision_target": "synthesizer",
                "iteration": 1,
                "critique": "thin on evidence",
            },
            {
                "node": "critic",
                "quality_score": 0.9,
                "revision_needed": False,
                "revision_target": "",
                "iteration": 2,
            },
        ),
        reader_fallbacks={
            "abstract_only_count": 1,
            "reasons": {"no_pdf_url": 1},
            "papers": [{"paper_id": "2401.00002", "reason": "no_pdf_url"}],
        },
        **overrides,
    )


def snapshot_of(
    tmp_path: Path, run: EpisodeRun, *, policy: EpisodeStatePolicy | None = None
) -> Mapping[str, Any]:
    """Write one snapshot into a scratch directory and read it back."""
    episode = sample_episode()
    return write_episode_state(
        tmp_path / "episode",
        campaign_id="camp_test",
        episode=episode,
        objective="what does grounding measure?",
        run=run,
        sealed_at="2026-01-01T00:00:00Z",
        corpus_mode="supplied",
        live_access_allowed=False,
        source_snapshot_ref="sha256:" + "a" * 64,
        policy=policy or EpisodeStatePolicy(),
    )


# ---------------------------------------------------------------------------
# 1. EL-05 — the snapshot
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTheEpisodeStateIsPersistedBeforeScoring:
    """`episode-state.json` exists, is complete, and is bounded."""

    def test_every_episode_of_a_real_pass_writes_its_state(
        self, tmp_path: Path
    ) -> None:
        """The whole loop, on the real graph, writes one snapshot per slot."""
        with pytest.MonkeyPatch.context() as patch:
            tripwire = install_tripwire(patch)
            cfg = config()
            plan = materialize(
                tmp_path, cfg, request(cfg, cases=SLICE_CASES, arms=("A",), repeats=1)
            )
            report = execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(cfg),
                sink_root=tmp_path / "trajectories",
            )
        assert report.attempted == len(SLICE_CASES)
        assert not tripwire.touched
        directory = tmp_path / plan.campaign_id
        for episode in plan.runnable:
            path = directory / episode.output_path / EPISODE_STATE_FILENAME
            assert path.is_file(), f"{episode.output_path} wrote no state snapshot"
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            assert snapshot["schema_kind"] == "campaign-episode-state"
            assert snapshot["run_id"] == episode.run_id
            assert snapshot["retrieval"]["retrieved_ids"] == [
                paper["id"] for paper in snapshot["papers"]
            ]
            assert path.stat().st_size <= MAX_EPISODE_STATE_BYTES

    def test_the_state_is_written_before_the_scorer_is_called(
        self, tmp_path: Path
    ) -> None:
        """Order, observed rather than asserted from the source.

        The scorer records whether the file was on disk at the moment it
        ran. EL-05's claim is about that ordering and nothing else: a
        snapshot written afterwards would be a snapshot a judge could not
        have read.
        """
        seen: list[bool] = []

        def watching_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
            seen.append(
                (
                    tmp_path
                    / plan.campaign_id
                    / episode.output_path
                    / EPISODE_STATE_FILENAME
                ).is_file()
            )
            return available_scorer(episode, run)

        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=ScriptedRunner(),
            scorer=watching_scorer,
            sink_root=tmp_path / "trajectories",
        )
        assert seen == [True]


@pytest.mark.unit
class TestTheSnapshotKeepsWhatAJudgeReads:
    """Every field EL-05 names is in the file, and `messages` is not."""

    def test_it_carries_the_plan_the_papers_and_the_evidence(
        self, tmp_path: Path
    ) -> None:
        snapshot = snapshot_of(tmp_path, rich_run())
        assert snapshot["plan"]["sub_questions"] == [
            "what is measured",
            "how is it measured",
        ]
        assert snapshot["plan"]["search_queries"] == [
            "retrieval grounding",
            "citation faithfulness",
        ]
        assert [paper["id"] for paper in snapshot["papers"]] == ["2401.00001"]
        assert snapshot["papers"][0]["abstract"] == "An abstract about grounding."
        assert snapshot["citations"][0]["paper_id"] == "2401.00001"
        assert snapshot["paper_analyses"][0]["relevance"] == 0.9
        assert snapshot["evidence"][0]["source_text"].startswith("The ranked chunk")

    def test_the_ranked_chunks_are_grouped_by_the_paper_they_came_from(
        self, tmp_path: Path
    ) -> None:
        """D-3 Option A's per-paper index, which the faithfulness judge reads."""
        chunks = snapshot_of(tmp_path, rich_run())["reader"]["chunks"]
        assert list(chunks) == ["2401.00001"]
        assert chunks["2401.00001"][0]["text"].startswith("The ranked chunk")
        assert chunks["2401.00001"][0]["section"] == "results"
        assert chunks["2401.00001"][0]["digest"].startswith("sha256:")

    def test_it_carries_the_critics_decision_for_every_pass(
        self, tmp_path: Path
    ) -> None:
        """The final state keeps only the last score; the snapshot keeps both."""
        iterations = snapshot_of(tmp_path, rich_run())["iterations"]
        assert [item["quality_score"] for item in iterations] == [0.4, 0.9]
        assert [item["revision_target"] for item in iterations] == ["synthesizer", ""]
        assert iterations[0]["critique"] == "thin on evidence"

    def test_it_carries_the_abstract_only_tally_and_its_reasons(
        self, tmp_path: Path
    ) -> None:
        fallbacks = snapshot_of(tmp_path, rich_run())["reader"]["abstract_only"]
        assert fallbacks["abstract_only_count"] == 1
        assert fallbacks["reasons"] == {"no_pdf_url": 1}

    def test_it_carries_the_retrieval_window_and_the_ids_it_returned(
        self, tmp_path: Path
    ) -> None:
        retrieval = snapshot_of(tmp_path, rich_run())["retrieval"]
        assert retrieval["corpus_mode"] == "supplied"
        assert retrieval["live_access_allowed"] is False
        assert retrieval["window_opened_at"] == "2026-01-01T00:00:00Z"
        assert retrieval["window_closed_at"] >= retrieval["window_opened_at"]
        assert retrieval["retrieved_ids"] == ["2401.00001"]

    def test_it_carries_the_outcome_and_the_stop_reason(self, tmp_path: Path) -> None:
        outcome = snapshot_of(tmp_path, rich_run())["outcome"]
        assert outcome["status"] == "succeeded"
        assert outcome["stop_reason"] == "critic_approved"
        assert outcome["iteration_count"] == 2
        assert outcome["node_route"][0] == "planner"
        assert outcome["workflow_cost_usd"] == "0.012345"

    def test_messages_never_reach_the_file(self, tmp_path: Path) -> None:
        """The one exclusion that is load-bearing rather than defensive.

        `messages` is a verbatim copy of every prompt and completion the
        run made, is not JSON-serializable, and would put the run's own
        model output inside the file a judge reads.
        """
        snapshot = snapshot_of(tmp_path, rich_run())
        assert "messages" not in snapshot
        assert "messages" in snapshot["retention"]["excluded_keys"]

        def keys(node: Any) -> Iterator[str]:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    yield str(key)
                    yield from keys(value)
            elif isinstance(node, list):
                for item in node:
                    yield from keys(item)

        # `excluded_keys` names it, so a substring search over the body
        # would match the declaration rather than the data. The key is
        # what has to be absent.
        assert "messages" not in set(keys(snapshot))


@pytest.mark.unit
class TestTheSnapshotIsBoundedAndScreened:
    """A snapshot that will not fit, or will not pass, is reduced not refused."""

    def test_a_snapshot_over_its_bound_drops_the_chunk_text_first(
        self, tmp_path: Path
    ) -> None:
        """Level 1: the judge loses verbatim chunks and keeps their digests."""
        run = rich_run(
            state={
                "evidence": [
                    {
                        "claim": f"claim {index}",
                        "paper_id": "2401.00001",
                        "section": "results",
                        "source_text": "x" * 4000,
                        "relevance_score": 0.5,
                        "supports_question": "what is measured",
                    }
                    for index in range(40)
                ]
            }
        )
        snapshot = snapshot_of(
            tmp_path, run, policy=EpisodeStatePolicy(max_bytes=120_000)
        )
        assert snapshot["retention"]["level"] == 1
        assert snapshot["retention"]["level_name"] == "chunk-text-dropped"
        assert snapshot["retention"]["chunk_text_retained"] is False
        assert snapshot["evidence"][0]["source_text"] == ""
        assert snapshot["evidence"][0]["source_text_chars"] == 4000
        assert snapshot["evidence"][0]["source_text_digest"].startswith("sha256:")
        assert "exceeds" in snapshot["retention"]["reduced_because"]

    def test_a_bound_nothing_can_fit_still_leaves_an_identifiable_record(
        self, tmp_path: Path
    ) -> None:
        """Level 3, then the stub: an episode is never left with no record."""
        snapshot = snapshot_of(
            tmp_path, rich_run(), policy=EpisodeStatePolicy(max_bytes=1)
        )
        assert snapshot["retention"]["level_name"] == "stub"
        assert snapshot["retention"]["screen"] == "refused"
        assert snapshot["run_id"].startswith("run_")
        assert (tmp_path / "episode" / EPISODE_STATE_FILENAME).is_file()

    def test_a_body_the_adr_0096_screen_refuses_is_reduced_not_raised(
        self, tmp_path: Path
    ) -> None:
        """A structural reasoning marker in a chunk costs the chunks, not the run.

        ADR 0096 narrowed the artifact screen to markers a producer
        authored — `<thinking>`, `<scratchpad>`, `reasoning_content` — so
        a retrieved abstract can no longer be refused for its subject.
        What can still be refused is a chunk that quotes a delimiter, and
        the answer to that is level 1, not an exception: the episode has
        already been paid for.
        """
        run = rich_run(
            state={
                "evidence": [
                    {
                        "claim": "a claim",
                        "paper_id": "2401.00001",
                        "section": "results",
                        "source_text": "<thinking>not for storage</thinking>",
                        "relevance_score": 0.5,
                        "supports_question": "what is measured",
                    }
                ]
            }
        )
        snapshot = snapshot_of(tmp_path, run)
        assert snapshot["retention"]["level"] == 1
        assert "private reasoning" in snapshot["retention"]["reduced_because"]
        assert "<thinking>" not in json.dumps(snapshot)

    def test_the_declared_levels_are_the_ones_that_can_be_built(
        self, tmp_path: Path
    ) -> None:
        """Every level in the closed tuple produces a snapshot."""
        episode = sample_episode()
        for level, name in enumerate(STATE_RETENTION_LEVELS):
            built = build_episode_state(
                campaign_id="camp_test",
                episode=episode,
                objective="q",
                run=rich_run(),
                sealed_at="2026-01-01T00:00:00Z",
                snapshot_at="2026-01-01T00:01:00Z",
                corpus_mode="supplied",
                live_access_allowed=False,
                source_snapshot_ref=None,
                policy=EpisodeStatePolicy(),
                level=level,
            )
            assert built["retention"]["level_name"] == name
            assert built["run_id"] == episode.run_id

    def test_retention_can_be_switched_off_by_the_campaign(
        self, tmp_path: Path
    ) -> None:
        """The setting EL-05 asks for, exposed as the campaign's own policy."""
        snapshot = snapshot_of(
            tmp_path, rich_run(), policy=EpisodeStatePolicy(retain_reader_chunks=False)
        )
        assert snapshot["retention"]["chunk_text_retained"] is False
        assert snapshot["evidence"][0]["source_text"] == ""
        assert snapshot["evidence"][0]["source_text_digest"].startswith("sha256:")
        # Still level 0: nothing was reduced *because it did not fit*.
        assert snapshot["retention"]["level"] == 0

    def test_an_unreadable_snapshot_reads_back_as_absent(self, tmp_path: Path) -> None:
        (tmp_path / EPISODE_STATE_FILENAME).write_text("{not json", encoding="utf-8")
        assert read_episode_state(tmp_path) is None
        assert read_episode_state(tmp_path / "nowhere") is None


# ---------------------------------------------------------------------------
# 2. EL-17 — the per-episode cap binds inside the graph
# ---------------------------------------------------------------------------


class _SpendingGraph:
    """A compiled graph whose nodes spend through the real gateway checks.

    Not a mock of the cap: every node calls `src.llm._check_cost_budget`
    — the gateway's own pre-call guard, reading the same two
    `ContextVar`s a real call reads — and then records a priced call
    through `record_llm_call`. So what is under test is the *binding*:
    with the episode's cap bound as the effective cap, the guard refuses
    the next call at the episode's number rather than at the deployment's
    `max_cost_usd`.

    `fan_out` models the one place this graph issues calls in parallel.
    The reader checks the budget once and then fires `max_workers` calls,
    so the honest overshoot bound is one fan-out's spend — which is what
    16 §3.4 says at campaign scale and what this reproduces at episode
    scale.
    """

    def __init__(self, *, per_call: int, nodes: int, fan_out: int = 1) -> None:
        self.per_call = per_call
        self.nodes = nodes
        self.fan_out = fan_out

    def stream(self, state: Mapping[str, Any], **_: Any) -> Iterator[Any]:
        from src.llm import _check_cost_budget
        from src.observability.costs import record_llm_call

        report = ""
        for index in range(self.nodes):
            _check_cost_budget()
            for _ in range(self.fan_out):
                record_llm_call(
                    PRICED_MODEL, input_tokens=self.per_call, output_tokens=self.per_call
                )
            node = f"node{index}"
            if index == 1:
                report = "# Partial\n\nWhat the run had produced when it stopped.\n"
            yield "updates", {node: {"iteration": index}}
            yield "values", {**dict(state), "draft_report": report}


@pytest.mark.integration
class TestThePerEpisodeCapBindsInsideTheGraph:
    """EL-17: the stop is between calls, not after the graph returns."""

    def test_a_graph_that_crosses_its_cap_is_budget_stopped_with_its_draft(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One node costs $1.20 at Haiku's rates, the draft appears after
        # the second, and a $3.00 cap is crossed on the fourth — so the
        # stop lands *after* there is something to keep, which is the
        # half of ADR 0051 this asserts.
        monkeypatch.setattr(
            "src.graph.workflow.build_workflow",
            lambda **_kwargs: _SpendingGraph(per_call=200_000, nodes=8),
        )
        episode = sample_episode()
        run = GraphEpisodeRunner(workflow_cost_usd_max="3.000000")(
            paid_config(),
            episode=episode,
            objective="a query that spends",
            run_id=episode.run_id,
            on_node=lambda _node: None,
        )
        assert run.status is CompletionStatus.BUDGET_STOPPED
        assert run.reason is RunReason.EPISODE_BUDGET_EXHAUSTED
        assert run.report.startswith("# Partial")
        assert "cap reached mid-graph" in (run.detail or "")
        assert run.model_calls == 3, "the graph ran past the call that crossed the cap"

    def test_the_overshoot_is_bounded_by_one_reader_fan_out(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """16 §3.4's bound, at episode scale and measured.

        One call of 200k input + 200k output tokens at Haiku's $1/$5
        prices is $0.20 + $1.00 = $1.20, so a four-way fan-out is $4.80.
        The cap is $5.00: the guard lets the fan-out that crosses it
        complete and refuses the next node's, which bounds total spend at
        cap + one fan-out and at nothing more.
        """
        cap = 5.0
        fan_out = 4
        monkeypatch.setattr(
            "src.graph.workflow.build_workflow",
            lambda **_kwargs: _SpendingGraph(
                per_call=200_000, nodes=8, fan_out=fan_out
            ),
        )
        episode = sample_episode()
        run = GraphEpisodeRunner(workflow_cost_usd_max=f"{cap:.6f}")(
            paid_config(),
            episode=episode,
            objective="a query that spends",
            run_id=episode.run_id,
            on_node=lambda _node: None,
        )
        one_call = 200_000 * 1.0 / 1e6 + 200_000 * 5.0 / 1e6
        assert run.status is CompletionStatus.BUDGET_STOPPED
        assert float(run.workflow_cost_usd) <= cap + one_call * fan_out
        assert float(run.workflow_cost_usd) > cap

    def test_a_graph_inside_its_cap_is_not_stopped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The binding must not stop a run that stayed inside its budget."""
        monkeypatch.setattr(
            "src.graph.workflow.build_workflow",
            lambda **_kwargs: _SpendingGraph(per_call=1000, nodes=3),
        )
        episode = sample_episode()
        run = GraphEpisodeRunner(workflow_cost_usd_max="1.000000")(
            paid_config(),
            episode=episode,
            objective="a cheap query",
            run_id=episode.run_id,
            on_node=lambda _node: None,
        )
        assert run.status is CompletionStatus.SUCCEEDED
        assert run.model_calls == 3

    def test_the_cap_does_not_leak_into_the_next_episode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `finally` that resets the binding, observed from outside."""
        from src.observability.costs import effective_cost_cap

        monkeypatch.setattr(
            "src.graph.workflow.build_workflow",
            lambda **_kwargs: _SpendingGraph(per_call=200_000, nodes=8),
        )
        episode = sample_episode()
        GraphEpisodeRunner(workflow_cost_usd_max="1.000000")(
            paid_config(),
            episode=episode,
            objective="a query that spends",
            run_id=episode.run_id,
            on_node=lambda _node: None,
        )
        assert effective_cost_cap(99.0) == 99.0


# ---------------------------------------------------------------------------
# 3. EL-01 / EL-02 — the live judge and its cost isolation
# ---------------------------------------------------------------------------


class _JudgeSurface:
    """A judge responder installed at the metric module's own seam.

    The same seam `src/eval/mock_judge.py` uses, and for the same reason:
    `src.eval.metrics.call_llm_json` is the one name every rubric calls,
    so replacing it exercises every line of the metric layer without a
    provider. What this adds is the *cost*: each answer records a priced
    call through `record_llm_call` and checks the budget through the
    gateway's own `_check_cost_budget`, so the accumulator the judges
    land on and the cap that stops them are the real ones.
    """

    def __init__(self, *, tokens: int = 1000, fail_after: int | None = None) -> None:
        self.tokens = tokens
        self.fail_after = fail_after
        self.calls = 0
        self.prompts: dict[str, str] = {}

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        from src.eval.metrics import (
            COMPLETENESS_SYSTEM_PROMPT,
            FAITHFULNESS_SYSTEM_PROMPT,
        )
        from src.llm import _check_cost_budget
        from src.observability.costs import record_llm_call

        _check_cost_budget()
        self.calls += 1
        record_llm_call(
            PRICED_MODEL, input_tokens=self.tokens, output_tokens=self.tokens
        )
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError("the judge returned something unusable")
        system = str(kwargs.get("system_prompt") or "")
        prompt = str(kwargs.get("prompt") or "")
        if system == COMPLETENESS_SYSTEM_PROMPT:
            self.prompts["completeness"] = prompt
            return {"coverage": [{"topic": "t", "covered": True, "reason": "r"}]}
        if system == FAITHFULNESS_SYSTEM_PROMPT:
            self.prompts["faithfulness"] = prompt
            return {
                "claims": [
                    {
                        "claim": "c",
                        "cite": "[Author, 2024]",
                        "supported": True,
                        "reason": "r",
                    }
                ]
            }
        return {
            "coverage": [
                {"topic": "t", "covered": True, "paper_ids": [0], "reason": "r"}
            ]
        }


@pytest.fixture
def judge(monkeypatch: pytest.MonkeyPatch) -> Iterator[_JudgeSurface]:
    """Install a priced judge responder for the duration of one test."""
    surface = _JudgeSurface()
    monkeypatch.setattr("src.eval.metrics.call_llm_json", surface)
    yield surface


@pytest.mark.unit
class TestTheLiveJudgeScorerRefusesTheFreeConfigurations:
    """A judge that would not be live is refused at construction."""

    def test_mock_data_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="USE_MOCK_DATA"):
            build_live_judge_scorer(config(use_mock_data=True))

    def test_the_zero_spend_sentinel_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="zero-spend sentinel"):
            build_live_judge_scorer(
                config(
                    use_mock_data=False,
                    anthropic_api_key=SecretStr("local-preview-disabled"),
                )
            )

    def test_an_absent_credential_is_refused(self) -> None:
        with pytest.raises(CampaignError, match="credential that can pay"):
            build_live_judge_scorer(
                config(use_mock_data=False, anthropic_api_key=SecretStr(""))
            )


@pytest.mark.integration
class TestTheLiveJudgeScoresTheThreeRubrics:
    """EL-01: five metrics, the mock scorer's layout, and no exception."""

    def test_it_writes_the_layout_the_report_already_reads(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        from src.campaign.report import _score_block

        episode = sample_episode()
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(episode, rich_run())

        assert judge.calls == 3
        metrics = scores.detail["metrics"]
        assert set(metrics) == {
            "citation_resolution",
            "supported_claim_precision",
            "completeness",
            "faithfulness",
            "retrieval_recall",
        }
        record = _record_for(scores)
        for key in ("completeness", "faithfulness", "retrieval_recall"):
            assert _score_block(record, key) is not None
        assert scores.detail["judges_run"] is True
        assert scores.detail["live_judge"] is True
        assert scores.detail["judge_metric_failures"] == []

    def test_a_judge_failure_costs_that_metric_and_no_other(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EL-01's isolation clause, and the reason `_compute_metrics` is reused."""
        surface = _JudgeSurface(fail_after=1)
        monkeypatch.setattr("src.eval.metrics.call_llm_json", surface)
        episode = sample_episode()
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(episode, rich_run())

        assert scores.detail["metrics"]["completeness"] is not None
        assert scores.detail["metrics"]["faithfulness"] is None
        assert scores.detail["metrics"]["retrieval_recall"] is None
        assert scores.detail["judge_failure_reasons"]["faithfulness"] == REASON_FAILED
        # The free half is unaffected: the deterministic checks never
        # went near a provider.
        assert scores.detail["metrics"]["citation_resolution"] is not None
        assert scores.primary_metric == PRIMARY_METRIC

    def test_a_case_with_no_benchmark_query_nulls_the_rubrics_with_a_reason(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=("rag-multi-hop",), arms=("A",), repeats=1)
        )
        episode = plan.runnable[0].model_copy(update={"case_id": "not-a-benchmark-case"})
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(episode, rich_run())
        assert judge.calls == 0
        assert set(scores.detail["judge_failure_reasons"].values()) == {
            "no_benchmark_query"
        }

    def test_the_persisted_ranked_chunks_reach_the_faithfulness_judge(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        """D-3 Option A, end to end: the snapshot is what widens the judge.

        ADR 0100 made `measure_faithfulness` take the reader's ranked
        chunks and record `source_scope` either way; ADR 0101's snapshot
        is the only copy of those chunks that survives the process. This
        asserts the join: the text goes in the prompt and the scope comes
        back on the record.
        """
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer.score_persisted(
            sample_episode(), rich_run(), snapshot_of(tmp_path, rich_run())
        )
        assert "The ranked chunk the reader actually read." in judge.prompts[
            "faithfulness"
        ]
        assert scores.detail["faithfulness_source_scope"] == "abstract_and_chunks"
        assert scores.detail["judge_temperature"] == paid_config().eval_judge_temperature

    def test_without_a_snapshot_the_judge_stays_on_abstracts(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        """The `EpisodeScorer` path has no file to read, and says so."""
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(sample_episode(), rich_run())
        assert "The ranked chunk the reader actually read." not in judge.prompts[
            "faithfulness"
        ]
        assert scores.detail["faithfulness_source_scope"] == "abstract_only"

    def test_a_snapshot_whose_chunk_text_was_reduced_away_falls_back(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        """A reduced snapshot degrades the scope rather than the episode."""
        reduced = snapshot_of(
            tmp_path, rich_run(), policy=EpisodeStatePolicy(retain_reader_chunks=False)
        )
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer.score_persisted(sample_episode(), rich_run(), reduced)
        assert scores.detail["faithfulness_source_scope"] == "abstract_only"
        assert scores.detail["judge_metric_failures"] == []

    def test_a_judged_metric_with_no_denominator_is_not_a_judge_failure(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        """ADR 0100's `score: None` is an answer, not an instrument problem.

        A blank report makes every judged metric report `None` with a
        reason. That is a finding about the arm and must not trip the
        judge-failure stop rule, which is about the *judge* failing.
        """
        blank = rich_run(state={"draft_report": ""})
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(sample_episode(), blank)
        assert scores.detail["metrics"]["faithfulness"]["score"] is None
        assert scores.detail["metrics"]["faithfulness"]["reason"]
        assert scores.detail["judge_metric_failures"] == []

    def test_it_reads_the_persisted_snapshot_rather_than_the_live_state(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        """EL-05's point: a re-judge later must see the same inputs.

        The snapshot's report text is deliberately different from the
        run's, so which one the judges read is observable rather than
        inferred.
        """
        episode = sample_episode()
        snapshot = snapshot_of(tmp_path, rich_run())
        edited = dict(snapshot)
        edited["report"] = {"text": "# From the snapshot\n\nDifferent text.\n"}
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer.score_persisted(episode, rich_run(), edited)
        assert scores.detail["scored_from_persisted_state"] is True
        assert scores.detail["state_retention_level"] == 0


@pytest.mark.integration
class TestJudgeCostIsolation:
    """EL-02: judge dollars are judge dollars."""

    def test_the_judges_do_not_spend_the_workflows_accumulator(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        from src.observability.costs import start_cost_tracking

        workflow = start_cost_tracking()
        workflow.record(PRICED_MODEL, 1000, 1000, 0.006)
        episode = sample_episode()
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")
        scores = scorer(episode, rich_run())

        # The workflow's accumulator is exactly where it was left.
        assert workflow.call_count == 1
        assert workflow.total_cost_usd == pytest.approx(0.006)
        # The judges' is real, and it is the number the ledger carries.
        assert scores.judge_model_calls == 3
        assert float(scores.judge_cost_usd) > 0.0
        assert scores.detail["judge_model_calls"] == 3

    def test_the_caller_s_accumulator_is_restored_even_when_the_body_raises(
        self,
    ) -> None:
        from src.observability.costs import current_costs, start_cost_tracking

        outer = start_cost_tracking()
        with pytest.raises(RuntimeError), judge_cost_scope(1.0) as inner:
            assert current_costs() is inner
            raise RuntimeError("boom")
        assert current_costs() is outer

    def test_a_judge_cap_reached_nulls_the_rest_and_completes_the_episode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason code EL-02 names, and the episode still finishes.

        One judge call of 1M input + 1M output tokens at Haiku's rates is
        $1 + $5 = $6, so a $2 judge allocation is crossed by the first
        rubric and the guard refuses the second and third.
        """
        surface = _JudgeSurface(tokens=1_000_000)
        monkeypatch.setattr("src.eval.metrics.call_llm_json", surface)
        episode = sample_episode()
        scorer = build_live_judge_scorer(paid_config(), judge_cost_usd_max="2.000000")
        scores = scorer(episode, rich_run())

        assert surface.calls == 1
        assert scores.detail["metrics"]["completeness"] is not None
        assert scores.detail["judge_failure_reasons"] == {
            "faithfulness": REASON_BUDGET,
            "retrieval_recall": REASON_BUDGET,
        }
        assert float(scores.judge_cost_usd) == pytest.approx(6.0)
        # The episode is still scored: the free primary metric survived.
        assert scores.receipt.run_id == episode.run_id

    def test_the_judged_metric_names_are_the_three_rubrics(self) -> None:
        assert JUDGED_METRICS == ("completeness", "faithfulness", "retrieval_recall")

    def test_no_socket_was_opened_by_any_of_it(
        self, tmp_path: Path, judge: _JudgeSurface
    ) -> None:
        with pytest.MonkeyPatch.context() as patch:
            connects: list[str] = []
            patch.setattr(
                socket.socket, "connect", lambda *_a, **_k: connects.append("connect")
            )
            clients: list[str] = []
            patch.setattr(llm_module, "_get_client", lambda: clients.append("client"))
            episode = sample_episode()
            build_live_judge_scorer(paid_config(), judge_cost_usd_max="1.000000")(
                episode, rich_run()
            )
        assert not connects
        assert not clients


# ---------------------------------------------------------------------------
# 4. EL-03 — a scorer never strands a paid episode
# ---------------------------------------------------------------------------


def _record_for(scores: EpisodeScores) -> Any:
    """A minimal object `report.py::_score_block` can read.

    `_score_block` reads exactly one attribute, so a namespace carrying
    it is a truer test than building a whole `EpisodeRecord`: what is
    under test is the *layout* of `scores`, not the record schema.
    """
    from types import SimpleNamespace

    return SimpleNamespace(scores=dict(scores.detail))


def _exploding_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    del episode, run
    raise RuntimeError("the scorer fell over")


@pytest.mark.integration
class TestAScorerNeverStrandsAPaidEpisode:
    """EL-03: persist, then score, then complete — and score cannot raise."""

    def test_a_scorer_that_raises_still_leaves_a_completion_receipt(
        self, tmp_path: Path
    ) -> None:
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=ScriptedRunner(),
            scorer=_exploding_scorer,
            sink_root=tmp_path / "trajectories",
        )
        episode = plan.runnable[0]
        target = tmp_path / plan.campaign_id / episode.output_path
        assert (target / COMPLETION_FILENAME).is_file()
        assert (target / SCORES_FILENAME).is_file()
        assert (target / EPISODE_STATE_FILENAME).is_file()
        record = json.loads((target / RECORD_FILENAME).read_text(encoding="utf-8"))
        assert record["primary_metric_available"] is False
        assert "RuntimeError" in record["scores"]["scoring_error"]
        assert report.counts["null_metric"] == 1

    def test_an_unscored_episode_is_scored_from_its_snapshot_not_re_run(
        self, tmp_path: Path
    ) -> None:
        """The recovery half. The graph must not run a second time.

        The first pass is interrupted exactly where EL-03 says it used to
        strand: after the snapshot and before the receipt. The second
        pass must produce the receipt without the runner being called
        again, because the episode's money has already been spent.
        """
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=1)
        )
        runner = ScriptedRunner()
        with pytest.raises(_HarnessInterrupted):
            execute_campaign(
                cfg,
                root=tmp_path,
                plan=plan,
                graph_probe=arm_graph_probe(cfg),
                runner=runner,
                scorer=_bridge_breaking_scorer,
                sink_root=tmp_path / "trajectories",
            )
        assert len(runner.calls) == 1
        target = tmp_path / plan.campaign_id / plan.runnable[0].output_path
        assert (target / EPISODE_STATE_FILENAME).is_file()
        assert not (target / COMPLETION_FILENAME).is_file()

        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=runner,
            scorer=available_scorer,
            sink_root=tmp_path / "trajectories",
        )
        assert len(runner.calls) == 1, "the graph ran again for an episode already paid for"
        assert report.completed == 1
        record = json.loads((target / RECORD_FILENAME).read_text(encoding="utf-8"))
        assert "scored from persisted state" in record["detail"]
        assert record["node_route"] == ["planner", "synthesizer"]

    def test_a_snapshot_without_its_report_is_re_run_rather_than_mis_scored(
        self, tmp_path: Path
    ) -> None:
        """A wrong score is worse than a repeated run, and this is that line."""
        from src.campaign.execute import _recoverable_run

        target = tmp_path / "episode"
        snapshot_of(
            tmp_path, rich_run(), policy=EpisodeStatePolicy(max_bytes=1500)
        )
        assert read_episode_state(target) is not None
        assert _recoverable_run(target, sample_episode()) is None


class _HarnessInterrupted(BaseException):
    """Stands in for the operator's Ctrl-C, without being pytest's.

    `_score_safely` absorbs `Exception` on purpose, so nothing a *scorer*
    can raise will strand an episode any more — which means the only way
    to reproduce the interruption the recovery path exists for is
    something that is not an `Exception` at all. A real `KeyboardInterrupt`
    would be the honest article and would also abort the pytest session,
    so this is its stand-in: same base class, same escape from every
    `except Exception` in the tree.
    """


def _bridge_breaking_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    """Interrupt the pass between the snapshot and the receipt."""
    del episode, run
    raise _HarnessInterrupted


# ---------------------------------------------------------------------------
# 5. EL-15 — the stop rules
# ---------------------------------------------------------------------------


#: Distinguishes "use the default fingerprint" from "this episode
#: recorded none". `None` cannot: an empty mapping is the case the rule
#: has to return `None` for, and `fingerprint or default` would quietly
#: substitute the default for it.
_DEFAULT_FINGERPRINT: Any = object()


def _executed(
    tmp_path: Path,
    *,
    fingerprint: Any = _DEFAULT_FINGERPRINT,
    corpus_mode: str = "supplied",
    source_ref: str | None = "sha256:" + "a" * 64,
    judges_run: bool = False,
    failures: tuple[str, ...] = (),
) -> Any:
    """One `ExecutedEpisode`, carrying only what a stop rule reads."""
    from src.campaign.execute import EpisodeRecord, ExecutedEpisode

    episode = sample_episode()
    record = EpisodeRecord.model_construct(model_calls=0, judge_model_calls=0)
    return ExecutedEpisode(
        episode=episode,
        record=record,
        outcome=None,  # type: ignore[arg-type]
        directory=tmp_path,
        provider_fingerprint=(
            {"routes": {"default": PRICED_MODEL}}
            if fingerprint is _DEFAULT_FINGERPRINT
            else fingerprint
        ),
        corpus_mode=corpus_mode,
        source_snapshot_ref=source_ref,
        judge_metric_failures=failures,
        judges_run=judges_run,
    )


@pytest.mark.unit
class TestTheStopRules:
    """EL-15: three rules that were prose in the packet and now run."""

    def test_provider_drift_stops_when_the_model_route_moves(
        self, tmp_path: Path
    ) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        assert rules.observe(_executed(tmp_path)) is None
        triggered = rules.observe(
            _executed(tmp_path, fingerprint={"routes": {"default": "claude-opus-5"}})
        )
        assert triggered is not None
        assert triggered[0] == "provider_drift"
        assert "routes" in triggered[1]

    def test_provider_drift_stops_when_the_price_table_date_moves(
        self, tmp_path: Path
    ) -> None:
        first = {"routes": {"default": PRICED_MODEL}, "prices_last_verified": "2026-08-20"}
        later = {"routes": {"default": PRICED_MODEL}, "prices_last_verified": "2026-09-01"}
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        assert rules.observe(_executed(tmp_path, fingerprint=first)) is None
        triggered = rules.observe(_executed(tmp_path, fingerprint=later))
        assert triggered is not None and triggered[0] == "provider_drift"

    def test_an_unchanged_instrument_never_stops(self, tmp_path: Path) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        for _ in range(5):
            assert rules.observe(_executed(tmp_path)) is None

    def test_source_drift_stops_when_the_resolved_mode_is_not_the_declared_one(
        self, tmp_path: Path
    ) -> None:
        """A `snapshot` campaign resolves to `supplied`; `live` does not."""
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        triggered = rules.observe(_executed(tmp_path, corpus_mode="live"))
        assert triggered is not None
        assert triggered[0] == "source_drift"
        assert "declared 'snapshot'" in triggered[1]

    def test_source_drift_stops_when_the_snapshot_digest_moves(
        self, tmp_path: Path
    ) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        assert rules.observe(_executed(tmp_path)) is None
        triggered = rules.observe(
            _executed(tmp_path, source_ref="sha256:" + "b" * 64)
        )
        assert triggered is not None
        assert triggered[0] == "source_drift"
        assert "source boundary moved" in triggered[1]

    def test_the_judge_rule_is_inert_when_no_judge_ran(self, tmp_path: Path) -> None:
        """A free-scored campaign has no judge to fail and no denominator."""
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        for _ in range(30):
            assert rules.observe(_executed(tmp_path, failures=("faithfulness",))) is None

    def test_three_of_the_first_ten_judged_episodes_stops_the_campaign(
        self, tmp_path: Path
    ) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        triggered = None
        for index in range(JUDGE_FAILURE_EARLY_TRIGGER):
            triggered = rules.observe(
                _executed(tmp_path, judges_run=True, failures=("faithfulness",))
            )
            if index < JUDGE_FAILURE_EARLY_TRIGGER - 1:
                assert triggered is None
        assert triggered is not None
        assert triggered[0] == "judge_failure_rate"
        assert "3 of 3 judged episode(s)" in triggered[1]

    def test_after_the_early_window_the_rule_is_a_rate(self, tmp_path: Path) -> None:
        """Two failures in fifty is under a tenth and must not stop."""
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        for index in range(50):
            failures = ("completeness",) if index in (7, 19) else ()
            assert (
                rules.observe(
                    _executed(tmp_path, judges_run=True, failures=failures)
                )
                is None
            )

    def test_the_rule_reads_any_judged_metric_not_the_primary_score(
        self, tmp_path: Path
    ) -> None:
        """EL-24's rewording, and the reason it matters.

        The primary metric is deterministic here, so a judge outage moves
        no primary score at all; a rule worded on it would never fire.
        `retrieval_recall` alone is enough.
        """
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        triggered = None
        for _ in range(JUDGE_FAILURE_EARLY_TRIGGER):
            triggered = rules.observe(
                _executed(tmp_path, judges_run=True, failures=("retrieval_recall",))
            )
        assert triggered is not None and triggered[0] == "judge_failure_rate"


@pytest.mark.integration
class TestAStoppedCampaignKeepsWhatItCompleted:
    """A stop rule is an experiment outcome, not an error (07 §9)."""

    def test_the_run_report_names_the_rule_and_what_it_saw(
        self, tmp_path: Path
    ) -> None:
        # Three repeats of one case, because the early half of the rule
        # is "three of the first ten" and two episodes cannot reach it.
        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=SLICE_CASES[:1], arms=("A",), repeats=3)
        )
        report = execute_campaign(
            cfg,
            root=tmp_path,
            plan=plan,
            graph_probe=arm_graph_probe(cfg),
            runner=ScriptedRunner(),
            scorer=_drifting_scorer,
            sink_root=tmp_path / "trajectories",
        )
        assert report.stop_reason == "judge_failure_rate"
        assert report.stop_detail is not None
        assert "judged episode(s)" in report.stop_detail
        # The episodes it did finish are finished, and counted.
        assert report.attempted >= 1
        assert report.counts[LedgerStatus.COMPLETED.value] == report.attempted


def _drifting_scorer(episode: PlannedEpisode, run: EpisodeRun) -> EpisodeScores:
    """Score every episode as judged, with a judged metric missing."""
    del run
    return EpisodeScores(
        receipt=EpisodeScoreReceipt(run_id=episode.run_id, primary_metric_available=True),
        primary_metric=PRIMARY_METRIC,
        primary_score=1.0,
        detail={
            "judges_run": True,
            "judge_metric_failures": ["faithfulness"],
            "metrics": {"faithfulness": None},
        },
    )


@pytest.mark.unit
class TestTheProviderFingerprintIsReadFromTheSealedManifest:
    """Not from live settings: the manifest is what the episode was admitted on."""

    def test_it_names_the_routes_the_prices_and_the_lock(
        self, tmp_path: Path
    ) -> None:
        from src.campaign.approval import (
            LocalApprovalRecordBackend,
            NoCredentialProbe,
        )
        from src.campaign.episode import seal_campaign_episode

        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=(JUDGED_CASE,), arms=("A",), repeats=1)
        )
        episode = plan.runnable[0]
        sealed = seal_campaign_episode(
            cfg,
            campaign=plan.manifest,
            episode=episode,
            task_spec=plan.task_spec_for(episode.case_id),
            graph=arm_graph_probe(cfg)(episode.arm_id),
            approval_backend=LocalApprovalRecordBackend(),
            credential_probe=NoCredentialProbe(),
        )
        fingerprint = provider_fingerprint(sealed.manifest)
        assert set(fingerprint) == {
            "provider",
            "api_protocol_version",
            "routes",
            "prices_last_verified",
            "price_table_digest",
            "dependency_lock_digest",
        }
        assert fingerprint["routes"]["default"] == cfg.anthropic_model
        assert fingerprint["dependency_lock_digest"].startswith("sha256:")


# ---------------------------------------------------------------------------
# 6. The log contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTheLogContract:
    """Every name and field this order added is in the closed registry."""

    def test_the_new_event_names_are_registered(self) -> None:
        assert {
            "campaign_episode_recovered",
            "campaign_episode_scoring_failed",
            "campaign_episode_state_written",
            "campaign_judge_budget_exhausted",
            "campaign_stop_rule_triggered",
            "campaign_smoke_started",
            "campaign_smoke_probe",
            "campaign_smoke_completed",
        } <= KNOWN_EVENTS

    def test_the_new_extra_keys_are_registered(self) -> None:
        assert {
            "approval_id",
            "judge_model_calls",
            "probe",
            "retention_level",
        } <= ALLOWED_EXTRA_KEYS


# ---------------------------------------------------------------------------
# 7. The seams the six groups above drive only indirectly
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTheRoutingDecisionReader:
    """What `_routing_decision` keeps, and what it declines to invent."""

    def test_a_critic_update_becomes_a_decision(self) -> None:
        from src.campaign.execute import _routing_decision

        decision = _routing_decision(
            "critic",
            {"quality_score": 0.7, "revision_needed": False, "critique": "fine"},
        )
        assert decision == {
            "node": "critic",
            "quality_score": 0.7,
            "revision_needed": False,
            "critique": "fine",
        }

    def test_a_node_without_a_decision_is_not_one(self) -> None:
        """A `search` update is a result, not a routing choice."""
        from src.campaign.execute import _routing_decision

        assert _routing_decision("search", {"papers": [{"id": "x"}]}) is None

    def test_a_decision_node_that_reported_nothing_is_not_one_either(self) -> None:
        """An empty update from a decision node records no decision.

        The guard matters because LangGraph emits an update per node
        whether or not the node wrote anything the snapshot cares about,
        and a bare `{"node": "critic"}` entry in the iteration list would
        read as a pass that happened.
        """
        from src.campaign.execute import _routing_decision

        assert _routing_decision("critic", {}) is None
        assert _routing_decision("critic", "not a mapping") is None


@pytest.mark.unit
class TestTheReaderFallbackObserver:
    """The abstract-only tally, read off the only place it exists."""

    def test_it_tallies_the_reason_of_every_degraded_paper(self) -> None:
        import logging

        from src.campaign.execute import _ReaderFallbackObserver

        logger = logging.getLogger(_ReaderFallbackObserver.LOGGER_NAME)
        with _ReaderFallbackObserver() as observer:
            for paper_id, reason in (
                ("2401.1", "no_pdf_url"),
                ("2401.2", "no_chunks"),
                ("2401.3", "no_pdf_url"),
            ):
                logger.info(
                    "reader_paper_abstract_only",
                    extra={"paper_id": paper_id, "reason": reason, "pdf_url": ""},
                )
            # A line from the same logger that is not this one.
            logger.info("reader_completed", extra={"n_papers": 3})
            summary = observer.summary()

        assert summary["abstract_only_count"] == 3
        assert summary["reasons"] == {"no_chunks": 1, "no_pdf_url": 2}
        assert summary["papers"][0] == {"paper_id": "2401.1", "reason": "no_pdf_url"}

    def test_it_detaches_itself_when_the_episode_ends(self) -> None:
        import logging

        from src.campaign.execute import _ReaderFallbackObserver

        logger = logging.getLogger(_ReaderFallbackObserver.LOGGER_NAME)
        before = len(logger.handlers)
        with _ReaderFallbackObserver() as observer:
            assert len(logger.handlers) == before + 1
        logger.info(
            "reader_paper_abstract_only",
            extra={"paper_id": "2401.9", "reason": "no_text", "pdf_url": ""},
        )
        assert len(logger.handlers) == before
        assert observer.summary()["abstract_only_count"] == 0

    def test_an_observer_that_breaks_does_not_break_the_line(self) -> None:
        """A logging handler that throws takes the log line down with it."""
        import logging

        from src.campaign.execute import _CollectingHandler

        class _Hostile(list[Any]):
            def append(self, item: Any) -> None:
                raise RuntimeError("the sink refused")

        handler = _CollectingHandler(_Hostile())
        errors: list[str] = []
        handler.handleError = lambda record: errors.append(record.getMessage())  # type: ignore[method-assign]
        record = logging.LogRecord(
            "src.agents.reader", logging.INFO, __file__, 1,
            "reader_paper_abstract_only", (), None,
        )
        record.paper_id = "2401.1"  # type: ignore[attr-defined]
        record.reason = "no_text"  # type: ignore[attr-defined]
        handler.emit(record)
        assert errors == ["reader_paper_abstract_only"]


@pytest.mark.unit
class TestTheBudgetStopCarriesWhateverDraftExists:
    """ADR 0051 put `partial_report` on the exception; this keeps it."""

    def test_a_draft_on_the_exception_is_kept_when_the_stream_had_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.observability.costs import CostBudgetExceeded

        class _RaisingGraph:
            def stream(self, state: Mapping[str, Any], **_: Any) -> Iterator[Any]:
                yield "updates", {"planner": {}}
                raise CostBudgetExceeded(
                    spent_usd=2.0, cap_usd=1.0, partial_report="# Salvaged\n"
                )

        monkeypatch.setattr(
            "src.graph.workflow.build_workflow", lambda **_kwargs: _RaisingGraph()
        )
        episode = sample_episode()
        run = GraphEpisodeRunner(workflow_cost_usd_max="1.000000")(
            paid_config(),
            episode=episode,
            objective="a query that spends",
            run_id=episode.run_id,
            on_node=lambda _node: None,
        )
        assert run.status is CompletionStatus.BUDGET_STOPPED
        assert run.report == "# Salvaged\n"

    def test_a_wrapped_budget_exception_is_not_filed_as_unknown(self) -> None:
        """`_reason_for`'s mapping, for the node that catches and re-raises."""
        from src.campaign.execute import _reason_for
        from src.observability.costs import CostBudgetExceeded

        assert (
            _reason_for(CostBudgetExceeded(spent_usd=2.0, cap_usd=1.0))
            is RunReason.EPISODE_BUDGET_EXHAUSTED
        )
        assert _reason_for(TimeoutError()) is RunReason.TIMEOUT
        assert _reason_for(ValueError()) is RunReason.UNKNOWN


@pytest.mark.unit
class TestTheSnapshotWriterNeverRaises:
    """Every failure mode leaves a record rather than an exception."""

    def test_a_builder_that_raises_at_every_level_still_leaves_a_stub(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(**_kwargs: Any) -> Any:
            raise ValueError("the state would not serialize")

        monkeypatch.setattr("src.campaign.execute.build_episode_state", explode)
        snapshot = write_episode_state(
            tmp_path,
            campaign_id="camp_test",
            episode=sample_episode(),
            objective="q",
            run=rich_run(),
            sealed_at="2026-01-01T00:00:00Z",
            corpus_mode="supplied",
            live_access_allowed=False,
            source_snapshot_ref=None,
            policy=EpisodeStatePolicy(),
        )
        assert snapshot["retention"]["level_name"] == "stub"
        assert "ValueError" in snapshot["retention"]["reduced_because"]
        assert (tmp_path / EPISODE_STATE_FILENAME).is_file()


@pytest.mark.unit
class TestTheStopRulesSayNothingWithoutEvidence:
    """A rule with no fact to read reports nothing rather than guessing."""

    def test_provider_drift_needs_a_fingerprint(self, tmp_path: Path) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        assert rules.observe(_executed(tmp_path, fingerprint={})) is None

    def test_source_drift_needs_a_resolved_mode(self, tmp_path: Path) -> None:
        rules = _StopRules(campaign_id="camp_x", corpus_mode="snapshot")
        assert rules.observe(_executed(tmp_path, corpus_mode="")) is None


@pytest.mark.unit
class TestScoringDelegatesToAStateAwareScorer:
    """`score_persisted` is preferred, and a failure in it is still a null."""

    def test_a_state_aware_scorer_is_handed_the_snapshot(
        self, tmp_path: Path
    ) -> None:
        from src.campaign.execute import _score_safely

        seen: list[Mapping[str, Any]] = []

        class _StateAware:
            def score_persisted(
                self,
                episode: PlannedEpisode,
                run: EpisodeRun,
                state: Mapping[str, Any],
            ) -> EpisodeScores:
                seen.append(state)
                return available_scorer(episode, run)

            def __call__(
                self, episode: PlannedEpisode, run: EpisodeRun
            ) -> EpisodeScores:
                raise AssertionError("the state-aware path must win")

        snapshot = snapshot_of(tmp_path, rich_run())
        scores = _score_safely(
            _StateAware(),
            episode=sample_episode(),
            run=rich_run(),
            state=snapshot,
            campaign_id="camp_test",
        )
        assert seen == [snapshot]
        assert scores.primary_score == 1.0


@pytest.mark.unit
class TestRecoveryRefusesASnapshotItCannotTrust:
    """Three shapes that mean "run the graph" rather than "score this"."""

    @staticmethod
    def _write(tmp_path: Path, snapshot: Mapping[str, Any]) -> Path:
        target = tmp_path / "episode"
        target.mkdir(parents=True, exist_ok=True)
        (target / EPISODE_STATE_FILENAME).write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        return target

    def test_a_reduced_away_report_is_not_scoreable(self, tmp_path: Path) -> None:
        from src.campaign.execute import _recoverable_run

        reduced = build_episode_state(
            campaign_id="camp_test",
            episode=sample_episode(),
            objective="q",
            run=rich_run(),
            sealed_at="2026-01-01T00:00:00Z",
            snapshot_at="2026-01-01T00:01:00Z",
            corpus_mode="supplied",
            live_access_allowed=False,
            source_snapshot_ref=None,
            policy=EpisodeStatePolicy(),
            level=2,
        )
        assert reduced["report"]["text"] == ""
        assert reduced["report"]["chars"] > 0
        target = self._write(tmp_path, reduced)
        assert _recoverable_run(target, sample_episode()) is None

    def test_an_unreadable_status_is_not_scoreable(self, tmp_path: Path) -> None:
        from src.campaign.execute import _recoverable_run

        snapshot = build_episode_state(
            campaign_id="camp_test",
            episode=sample_episode(),
            objective="q",
            run=rich_run(),
            sealed_at="2026-01-01T00:00:00Z",
            snapshot_at="2026-01-01T00:01:00Z",
            corpus_mode="supplied",
            live_access_allowed=False,
            source_snapshot_ref=None,
            policy=EpisodeStatePolicy(),
        )
        snapshot["outcome"]["status"] = "not-a-completion-status"
        target = self._write(tmp_path, snapshot)
        assert _recoverable_run(target, sample_episode()) is None

    def test_a_stub_is_not_scoreable(self, tmp_path: Path) -> None:
        from src.campaign.execute import _recoverable_run

        target = self._write(
            tmp_path, {"schema_kind": "campaign-episode-state", "retention": {}}
        )
        assert _recoverable_run(target, sample_episode()) is None


@pytest.mark.unit
class TestTheRunVerbResolvesOneScorer:
    """`--mock-judge` and `--live-judge` are alternatives, not a precedence."""

    @staticmethod
    def _args(argv: list[str]) -> Any:
        from src.campaign.cli import _parser

        return _parser().parse_args(argv)

    def test_naming_both_is_refused(self, tmp_path: Path) -> None:
        from src.campaign.cli import _scorer

        with pytest.raises(CampaignError, match="name one"):
            _scorer(
                self._args(
                    ["run", "--campaign-id", "camp_x", "--mock-judge", "--live-judge"]
                ),
                config(),
                tmp_path,
            )

    def test_naming_neither_leaves_the_free_scorer(self, tmp_path: Path) -> None:
        from src.campaign.cli import _scorer

        assert _scorer(self._args(["run", "--campaign-id", "camp_x"]), config(), tmp_path) is None

    def test_live_judge_reads_the_sealed_judge_allocation(
        self, tmp_path: Path
    ) -> None:
        """The cap comes from the manifest, not from a command-line flag.

        What an episode's judges may spend is part of the protocol an
        approval covered, so an operator cannot raise it at the prompt —
        they would have to plan a different campaign, which moves the
        campaign id.
        """
        from src.campaign.cli import _scorer

        cfg = config()
        plan = materialize(
            tmp_path, cfg, request(cfg, cases=(JUDGED_CASE,), arms=("A",), repeats=1)
        )
        scorer = _scorer(
            self._args(["run", "--campaign-id", plan.campaign_id, "--live-judge"]),
            paid_config(),
            tmp_path,
        )
        assert scorer is not None
        assert scorer.__class__.__name__ == "LiveJudgeScorer"

    def test_mock_judge_still_resolves_the_fixture_scorer(
        self, tmp_path: Path
    ) -> None:
        from src.campaign.cli import _scorer

        scorer = _scorer(
            self._args(["run", "--campaign-id", "camp_x", "--mock-judge"]),
            config(anthropic_api_key=SecretStr("local-preview-disabled")),
            tmp_path,
        )
        assert scorer.__class__.__name__ == "MockJudgeScorer"
