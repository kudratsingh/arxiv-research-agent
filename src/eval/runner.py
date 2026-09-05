"""Batch eval runner.

Invokes the workflow on each benchmark query, scores the resulting
report with the five metrics in `src/eval/metrics.py`, and writes a
layered output artifact:

    outputs/eval/<run_id>/
        queries/<query_id>.json  — full record per query
        summary.jsonl            — machine-readable per-query line
        summary.md               — human-readable table + aggregates

Design (see ADR 0008, hardened by ADR 0050):
  - Queries run sequentially. Parallelism is a follow-up — rate limits
    on arXiv and Anthropic dominate at Phase-2 scale.
  - Per-query error tolerance: a broken query is captured with its
    traceback and reported, but does not abort the run. That isolation
    now also covers the *scoring* half: a judge failure downgrades the
    affected metric to `None` and keeps the paid workflow output.
  - Fresh workflow per query (via `build_workflow()`) for isolation —
    LangGraph state does not leak between runs. The compiled graph's
    checkpointer is closed after every query (ADR 0050).
  - Crash-safe: every completed query is written to disk immediately,
    so a kill, an OOM, or a pulled plug loses at most the in-flight
    query. `--resume` re-enters a killed campaign without re-paying.
  - Interrupt-safe: Ctrl-C *and* SIGTERM flush partial results — the
    in-flight query included — before exit.
  - Cost accounting separates the product from the harness: the
    workflow's spend and the judges' spend are distinct fields, so the
    published README figure and the regression gate describe the agent
    rather than the eval rig (ADR 0050, revisiting ADR 0044).

Usage:
    python -m src.eval.runner
    python -m src.eval.runner --queries hallucination-mitigation,rag-multi-hop
    python -m src.eval.runner --output-dir outputs/eval/manual-run-a
    python -m src.eval.runner --output-dir outputs/eval/manual-run-a --resume
    python -m src.eval.runner --max-budget-usd 25

Exit codes:
    0   — every attempted query succeeded
    1   — configuration error (no ANTHROPIC_API_KEY)
    2   — usage error (non-empty output directory without --resume)
    3   — completed, but at least one query errored
    4   — every attempted query errored
    5   — stopped early on the --max-budget-usd ceiling
    130 — interrupted (Ctrl-C / SIGTERM); partial results are on disk
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import sys
import time
import traceback
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any, NamedTuple

from dotenv import load_dotenv

from src.eval.benchmark_queries import (
    BENCHMARK_QUERIES,
    RESEARCH_DATASET_VERSION,
    BenchmarkQuery,
)
from src.eval.groundedness import measure_groundedness, paired_outcomes
from src.eval.metrics import (
    RESEARCH_RUBRICS,
    measure_citation_accuracy,
    measure_citation_resolution,
    measure_completeness,
    measure_faithfulness,
    measure_retrieval_recall,
)
from src.eval.provenance import (
    PROVENANCE_KEY,
    RunProvenance,
    capture,
    provenance_markdown,
    seed_campaign,
)
from src.graph.state import ResearchState
from src.graph.workflow import build_workflow
from src.observability import (
    bind_run_id,
    get_logger,
    reset_run_id,
    start_cost_tracking,
)

load_dotenv()

log = get_logger(__name__)

DEFAULT_OUTPUT_ROOT = Path("outputs/eval")

# Exit codes. `main()` returns exactly one of these; the docstring
# above is the operator-facing copy of this table. Distinct codes for
# "some queries failed" vs "everything failed" vs "budget stop" exist
# so a wrapper script can tell a quality problem from an outage from a
# policy stop without parsing stdout (ADR 0050).
EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_USAGE = 2
EXIT_PARTIAL_FAILURE = 3
EXIT_ALL_FAILED = 4
EXIT_BUDGET_STOP = 5
EXIT_INTERRUPTED = 130  # conventional 128 + SIGINT

# Longest exception text allowed into a summary.md table cell.
_ERROR_CELL_MAX = 200

#: The tier name the research campaign records in its provenance block.
#: The research lane has one tier — it always drives the real workflow —
#: so the field names the *lane* rather than pretending to a
#: scripted/funded split this campaign does not have. Whether a run was
#: nonetheless against mock data is a separate provenance field, because
#: that is the question that decides if the numbers mean anything.
RESEARCH_TIER = "research"

#: Repeats per query below which a comparison against a baseline is not
#: believable, from `planning/05-agentic-upgrade-plan.md` ("Judge noise
#: mandates repeat runs"). `simulate_learner` declares the same number
#: for the learning lane and cannot share this one: that module imports
#: this one, so a shared constant would have to live here and be
#: imported there, which is a change to a file this work order does not
#: own. Both quote the same planning document, and
#: `tests/test_eval_stats.py` pins them equal.
REPEATS_FOR_CONFIDENCE = 3


def research_provenance() -> RunProvenance:
    """Provenance for one research-campaign record.

    A function rather than a module constant: the judge model, the
    product model and the commit are read when the record is created, so
    a campaign that outlives a settings change records what actually
    scored each query (ADR 0070).
    """
    return capture(
        tier=RESEARCH_TIER,
        dataset_version=RESEARCH_DATASET_VERSION,
        rubrics=RESEARCH_RUBRICS,
    )


class EvalInterrupted(KeyboardInterrupt):
    """Ctrl-C / SIGTERM carrying the in-flight query's partial record.

    Subclasses `KeyboardInterrupt` (and so `BaseException`) on purpose:
    every `except Exception` between here and `main()` must keep
    ignoring it, while `main()` gets the chance to persist the record
    of the query that was already paid for when the signal landed.
    """

    def __init__(self, record: dict[str, Any]) -> None:
        super().__init__(record.get("error", "interrupted"))
        self.record = record


# ---------------------------------------------------------------------------
# State + record construction
# ---------------------------------------------------------------------------


def _initial_state(query: str, run_id: str) -> ResearchState:
    """Fresh `ResearchState` for a single workflow invocation."""
    return {
        "run_id": run_id,
        "query": query,
        "sub_questions": [],
        "search_queries": [],
        "papers": [],
        "paper_analyses": [],
        "draft_report": "",
        "citations": [],
        "critique": "",
        "quality_score": 0.0,
        "revision_needed": False,
        "revision_target": "",
        "iteration": 0,
        "next_action": "",
        "loop_iterations": 0,
        "stop_reason": "",
        "verified": False,
        "unsupported_claims": [],
        "missing_evidence": [],
        "verifier_recommendation": "",
        "evidence": [],
        "tried_search_queries": [],
        "reader_analysis_complete": True,
        "reader_missing_context": "",
        "reader_requested_sections": [],
        "prior_context": "",
        "messages": [],
    }


def _serialize_state(state: ResearchState) -> dict[str, Any]:
    """JSON-safe snapshot of `state` — drops non-serializable messages."""
    return {k: v for k, v in state.items() if k != "messages"}


def _compute_metrics(
    state: ResearchState, benchmark_query: BenchmarkQuery
) -> tuple[dict[str, Any], str | None]:
    """Score a completed run with all five metrics. Never raises.

    Each metric is computed inside its own guard: three of the five are
    LLM-as-judge calls, and a judge that times out, 429s past its
    retries, or truncates into invalid JSON must not cost us the
    workflow output we already paid for (ADR 0050). A failed metric
    lands as `None` in the returned dict — `_get_score` already reads
    that as "no score" — and its message is folded into the second
    return value.

    The two citation metrics are both deterministic and both free.
    `citation_resolution_rate` is the one the gate reads (ADR 0074);
    `citation_accuracy` is computed alongside it because ADR 0070
    forbids dropping a row field and the README block still averages it,
    not because it is still trusted — see `metrics.py`.

    Returns:
        `(metrics, metrics_error)` where `metrics` maps every metric
        name to its result dict or `None`, and `metrics_error` is a
        `"; "`-joined summary of the failures or `None` when all five
        scored.
    """
    report = state.get("draft_report", "")
    papers = state.get("papers", [])
    citations = state.get("citations", [])
    topics = benchmark_query["expected_topics"]

    scorers: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        (
            "citation_resolution_rate",
            lambda: dict(measure_citation_resolution(report, papers, citations)),
        ),
        (
            "citation_accuracy",
            lambda: dict(measure_citation_accuracy(report, citations)),
        ),
        ("completeness", lambda: dict(measure_completeness(report, topics))),
        (
            "faithfulness",
            lambda: dict(measure_faithfulness(report, papers, citations)),
        ),
        (
            "retrieval_recall",
            lambda: dict(measure_retrieval_recall(papers, topics)),
        ),
    ]

    metrics: dict[str, Any] = {}
    failures: list[str] = []
    for name, scorer in scorers:
        try:
            metrics[name] = scorer()
        except Exception as exc:  # noqa: BLE001 — isolation is the point
            metrics[name] = None
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            log.exception(
                "eval_metric_failed",
                extra={
                    "query_id": benchmark_query["query_id"],
                    "metric": name,
                },
            )

    return metrics, ("; ".join(failures) if failures else None)


def _claim_outcomes(state: ResearchState) -> dict[str, bool] | None:
    """Per-claim groundedness verdicts for one finished run.

    `{claim_id: grounded}` from `groundedness.paired_outcomes` — the
    shape `src/eval/stats.py`'s McNemar path consumes, and the follow-up
    ADR 0074 left open when it noted that "nothing hands it one yet".
    `regression_diff` reads it off the summary row, namespaces each
    claim by its query and pairs the two arms on it (WO-C1).

    Computed rather than read off `_compute_metrics`: that function's
    citation entry goes through `measure_citation_resolution`, which
    projects the result down to a rate and drops the claim list. Calling
    the deterministic check a second time costs microseconds, no
    network and no model, and leaves `citation_resolution_rate`
    byte-identical to what it was — which matters, because changing a
    *score* here would rebaseline every campaign.

    Returns `None` when the check itself fails, so a row can say "not
    computed" rather than "computed and empty". Never raises: a scorer
    must not cost the campaign the paid workflow output it already has
    (ADR 0050).
    """
    try:
        return paired_outcomes(
            measure_groundedness(
                str(state.get("draft_report") or ""),
                list(state.get("papers") or []),
                list(state.get("citations") or []),
            )
        )
    except Exception:  # noqa: BLE001 — isolation is the point
        log.exception("eval_metric_failed", extra={"metric": "groundedness"})
        return None


def _cost_delta(
    after: dict[str, Any], before: dict[str, Any]
) -> dict[str, Any]:
    """Spend recorded between two snapshots of the same accumulator.

    Used to attribute the judges' own LLM calls to the harness rather
    than to the workflow under test (ADR 0050). Only the scalar totals
    are differenced — the `per_model` breakdown is left to the two
    snapshots that bracket it.
    """
    fields = (
        "total_cost_usd",
        "total_input_tokens",
        "total_output_tokens",
        "total_cache_read_input_tokens",
        "total_cache_creation_input_tokens",
        "call_count",
    )
    delta: dict[str, Any] = {}
    for field in fields:
        start = before.get(field) or 0
        end = after.get(field) or 0
        value = end - start
        delta[field] = round(value, 6) if isinstance(value, float) else value
    return delta


def research_record_id(query_id: str, repeat: int) -> str:
    """Durable record key for one query's `repeat`-th run.

    The first repeat keeps the bare `query_id`, so a default campaign —
    every campaign before ADR 0071 — writes exactly the filenames,
    summary rows and resume keys it always did, and a campaign already
    on disk stays resumable. Later repeats take the `.rN` suffix the
    learning lane already uses; benchmark ids are kebab-case, so the
    suffix cannot collide with one.

    Args:
        query_id: The benchmark query.
        repeat: 1-based repeat index.

    Returns:
        The record id.
    """
    return query_id if repeat <= 1 else f"{query_id}.r{repeat}"


def _split_research_record_id(value: str) -> tuple[str, int]:
    """Inverse of `research_record_id`; an unsuffixed id is repeat 1.

    Deliberately local rather than shared with `simulate_learner`'s
    equivalent: that module imports this one, so the dependency can only
    run one way, and each lane owns the id scheme it writes.
    """
    query_id, _, suffix = value.rpartition(".r")
    if query_id and suffix.isdigit():
        return query_id, int(suffix)
    return value, 1


def _run_and_score(
    benchmark_query: BenchmarkQuery, *, repeat: int = 1
) -> dict[str, Any]:
    """Invoke the workflow, apply metrics, capture timing / errors / costs.

    Never raises for a workflow or judge failure — errors are captured
    on the record so the outer loop keeps making progress (ADR 0008).
    The one exception that does leave this function is
    `EvalInterrupted`, which carries the partial record out to `main()`
    so a Ctrl-C'd query's spend is still written down.

    The returned record splits harness spend from product spend:
    `costs` / `elapsed_sec` cover the workflow invocation only, while
    `judge_costs` / `scoring_sec` cover the metric calls that follow it.

    Args:
        benchmark_query: The query to run and score.
        repeat: 1-based repeat index within the campaign. `query_id`
            keeps naming the *query* on every repeat and `record_id`
            distinguishes them, which is what lets the regression differ
            aggregate repeats by task instead of comparing `r1` to `r1`
            (ADR 0071).
    """
    run_id = uuid.uuid4().hex[:16]
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()
    app: Any = None

    record: dict[str, Any] = {
        "run_id": run_id,
        "record_id": research_record_id(benchmark_query["query_id"], repeat),
        "query_id": benchmark_query["query_id"],
        "repeat": repeat,
        "query": benchmark_query["query"],
        "domain": benchmark_query["domain"],
        "elapsed_sec": 0.0,
        "scoring_sec": None,
        "costs": costs.as_dict(),
        "judge_costs": None,
        "state": None,
        "metrics": None,
        "groundedness": None,
        "metrics_error": None,
        "error": None,
        # Captured here, at record creation, rather than when the
        # summary is rendered: `rebuild_summaries` re-derives
        # `summary.jsonl` from the durable records — possibly days later
        # on a `--resume` — and a block captured then would describe the
        # rebuild instead of the run that produced the score (ADR 0070).
        PROVENANCE_KEY: research_provenance(),
    }

    log.info(
        "eval_query_started",
        extra={
            "query_id": benchmark_query["query_id"],
            "domain": benchmark_query["domain"],
        },
    )
    try:
        try:
            # `enable_hitl=False`: the nightly benchmark runs unattended;
            # letting the workflow pause for plan review would hang the
            # runner. Matches the per-query `hitl_bypass` on POST
            # /research for other programmatic callers. See ADR 0030.
            app = build_workflow(enable_hitl=False)
            config = {"configurable": {"thread_id": run_id}}
            final_state = app.invoke(
                _initial_state(benchmark_query["query"], run_id), config=config
            )
        except Exception as exc:
            record["elapsed_sec"] = time.monotonic() - start
            record["costs"] = costs.as_dict()
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc()
            log.exception(
                "eval_query_failed",
                extra={
                    "query_id": benchmark_query["query_id"],
                    "elapsed_sec": round(record["elapsed_sec"], 2),
                    **record["costs"],
                },
            )
            return record

        # Workflow spend is snapshotted here, *before* the judges run —
        # everything after this line is harness cost (ADR 0050).
        record["elapsed_sec"] = time.monotonic() - start
        record["costs"] = costs.as_dict()
        record["state"] = _serialize_state(final_state)

        report = str(final_state.get("draft_report") or "")
        if not report.strip():
            # No report means nothing to score: `measure_citation_accuracy`
            # and `measure_faithfulness` both short-circuit an empty
            # report to a free 1.0, which would publish a run that
            # produced nothing as a perfect one. Record it as the failure
            # it is and skip two wasted judge calls (ADR 0050).
            # `measure_citation_resolution` would say `no_citations`
            # rather than 1.0 here, which is the honest answer — but a
            # run that produced no report is an error, not a score, and
            # the record still belongs in the errored bucket.
            stop_reason = final_state.get("stop_reason") or "unknown"
            record["error"] = f"NoReportProduced: stop_reason={stop_reason}"
            log.warning(
                "eval_query_no_report",
                extra={
                    "query_id": benchmark_query["query_id"],
                    "stop_reason": stop_reason,
                    "elapsed_sec": round(record["elapsed_sec"], 2),
                },
            )
            return record

        scoring_start = time.monotonic()
        metrics, metrics_error = _compute_metrics(final_state, benchmark_query)
        record["groundedness"] = _claim_outcomes(final_state)
        record["scoring_sec"] = time.monotonic() - scoring_start
        record["metrics"] = metrics
        record["metrics_error"] = metrics_error
        record["judge_costs"] = _cost_delta(costs.as_dict(), record["costs"])

        log.info(
            "eval_query_completed",
            extra={
                "query_id": benchmark_query["query_id"],
                "elapsed_sec": round(record["elapsed_sec"], 2),
                "scoring_sec": round(record["scoring_sec"], 2),
                "citation_accuracy": _get_score(metrics, "citation_accuracy"),
                "completeness": _get_score(metrics, "completeness"),
                "faithfulness": _get_score(metrics, "faithfulness"),
                "metrics_error": metrics_error,
                "judge_cost_usd": record["judge_costs"]["total_cost_usd"],
                **record["costs"],
            },
        )
        return record
    except KeyboardInterrupt as exc:
        # The operator (or a container stop) cut in mid-query. The spend
        # already happened, so hand the partial record to `main()`
        # rather than dropping it, then keep unwinding.
        record["error"] = f"Interrupted: {type(exc).__name__}"
        record["costs"] = costs.as_dict()
        if not record["elapsed_sec"]:
            record["elapsed_sec"] = time.monotonic() - start
        raise EvalInterrupted(record) from exc
    finally:
        _close_workflow(app)
        reset_run_id(token)


def _close_workflow(app: Any) -> None:
    """Release the compiled graph's checkpointer connection.

    `build_workflow` opens the saver through an `ExitStack` and attaches
    it as `_checkpointer_exit_stack` for exactly this. The eval runner
    compiles one graph per query, so skipping the close leaks a
    connection/fd per query — inert against SQLite at benchmark size,
    but a real drain against a Postgres backend's connection ceiling
    (ADR 0050, closing the shape ADR 0034 named).
    """
    exit_stack = getattr(app, "_checkpointer_exit_stack", None)
    if exit_stack is None:
        return
    try:
        exit_stack.close()
    except Exception:  # noqa: BLE001 — teardown must not mask the result
        log.exception("eval_checkpointer_close_failed")


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------


def _get_score(metrics: Any, metric_name: str) -> float | None:
    """Safely pull the `score` field from a metric result dict."""
    if not isinstance(metrics, dict):
        return None
    metric = metrics.get(metric_name)
    if isinstance(metric, dict):
        value = metric.get("score")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _get_count(metrics: Any, metric_name: str, field: str) -> int | None:
    """Safely pull an integer counter out of a metric result dict."""
    if not isinstance(metrics, dict):
        return None
    metric = metrics.get(metric_name)
    if isinstance(metric, dict):
        value = metric.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _get_reason(metrics: Any, metric_name: str) -> str | None:
    """Safely pull a metric's `reason` string.

    A `None` score is only honest if the row also says *why*. ADR 0074's
    metrics carry a reason code beside an empty denominator
    (`no_citations`), and dropping it on the way into `summary.jsonl`
    would leave a reader unable to tell "nothing was measured" from
    "the metric failed".
    """
    if not isinstance(metrics, dict):
        return None
    metric = metrics.get(metric_name)
    if isinstance(metric, dict):
        value = metric.get("reason")
        if isinstance(value, str) and value:
            return value
    return None


def _summary_line(record: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields that go into `summary.jsonl` / `summary.md`.

    `cost_usd` / `llm_calls` / `elapsed_sec` describe the **workflow**
    only. The judges' own spend rides in `judge_cost_usd` /
    `judge_llm_calls`, and `total_cost_usd` is their sum — the number
    that answers "what did this benchmark query cost me to run".
    Before ADR 0050 the three product fields silently included judge
    spend, so summaries older than that ADR are not comparable on cost.

    `provenance` is copied through from the record rather than captured
    here, and a record written before ADR 0070 has none — such a row
    arrives with an empty block and fails the provenance check, which is
    the correct answer: a row that cannot name its judge, its rubric
    versions or its commit cannot participate in a comparison.

    `record_id` names the run and `query_id` names the *query*, which
    on a `--repeats 3` campaign three rows share. That split is what the
    regression differ groups on to aggregate repeats before diffing
    (ADR 0071); at one repeat the two are the same string.

    The citation signal is three fields, added rather than substituted
    because ADR 0070 forbids removing one: `citation_resolution_rate` is
    the gated metric, `citations_checked` is its denominator, and
    `citation_resolution_reason` says why the rate is `None` when it is.
    A rate published without its denominator is the defect ADR 0074 was
    written about, so the row carries all three or none of them.
    `citation_accuracy` stays beside them as a diagnostic.
    """
    metrics = record.get("metrics")
    state = record.get("state") or {}
    costs = record.get("costs") or {}
    judge_costs = record.get("judge_costs") or {}
    workflow_cost = costs.get("total_cost_usd")
    judge_cost = judge_costs.get("total_cost_usd")
    return {
        "record_id": record.get("record_id") or record["query_id"],
        "query_id": record["query_id"],
        "repeat": record.get("repeat", 1),
        "elapsed_sec": record.get("elapsed_sec"),
        "scoring_sec": record.get("scoring_sec"),
        "error": record.get("error"),
        "metrics_error": record.get("metrics_error"),
        "citation_resolution_rate": _get_score(metrics, "citation_resolution_rate"),
        "citations_checked": _get_count(
            metrics, "citation_resolution_rate", "total_citations"
        ),
        "citation_resolution_reason": _get_reason(
            metrics, "citation_resolution_rate"
        ),
        "citation_accuracy": _get_score(metrics, "citation_accuracy"),
        "completeness": _get_score(metrics, "completeness"),
        "faithfulness": _get_score(metrics, "faithfulness"),
        "retrieval_recall": _get_score(metrics, "retrieval_recall"),
        # The legacy `[Author, Year]` tag count, still sourced from the
        # legacy metric so its meaning does not change under a reader of
        # an older summary. `citations_checked` above is the new metric's
        # denominator and is the one to read.
        "total_citations": _get_count(
            metrics, "citation_accuracy", "total_citations"
        ),
        "critic_score": state.get("quality_score"),
        "iterations": state.get("iteration"),
        "cost_usd": workflow_cost,
        "llm_calls": costs.get("call_count"),
        "judge_cost_usd": judge_cost,
        "judge_llm_calls": judge_costs.get("call_count"),
        "total_cost_usd": (
            None
            if workflow_cost is None and judge_cost is None
            else round((workflow_cost or 0.0) + (judge_cost or 0.0), 6)
        ),
        "loop_iterations": state.get("loop_iterations"),
        "stop_reason": state.get("stop_reason"),
        # `{claim_id: grounded}` for every claim the deterministic check
        # decided, added by WO-C1 so the funded lane's rows can be
        # compared per claim rather than only per mean. A record written
        # before it carries `None`, which `regression_diff` reads as "no
        # claims" rather than as an empty comparison — additive, so no
        # existing field moved and no campaign was rebaselined.
        "paired_outcomes": record.get("groundedness"),
        "claims_decided": (
            None
            if not isinstance(record.get("groundedness"), dict)
            else len(record["groundedness"])
        ),
        PROVENANCE_KEY: record.get(PROVENANCE_KEY) or {},
    }


def _record_total_cost(record: dict[str, Any]) -> float:
    """Workflow + judge dollars for one record, for campaign budgeting."""
    costs = record.get("costs") or {}
    judge_costs = record.get("judge_costs") or {}
    return float(costs.get("total_cost_usd") or 0.0) + float(
        judge_costs.get("total_cost_usd") or 0.0
    )


def _fmt(value: Any) -> str:
    """Format a scalar for the markdown table."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_cell_text(value: Any) -> str:
    """Format free text (exception messages) for a markdown table cell.

    Exception text is uncontrolled — an SDK error body can carry a `|`
    or a newline, either of which corrupts the table from that row
    down. Escape both and cap the length; the untruncated text stays in
    `queries/<id>.json` and in `summary.jsonl` (ADR 0050).
    """
    if not value:
        return "-"
    text = " ".join(str(value).split())
    text = text.replace("|", "\\|")
    if len(text) > _ERROR_CELL_MAX:
        text = text[: _ERROR_CELL_MAX - 1] + "…"
    return text


def _mean(rows: list[dict[str, Any]], field: str) -> str:
    """Mean of `rows[*][field]`, ignoring `None`s. Returns `-` when empty."""
    values = [r[field] for r in rows if r.get(field) is not None]
    if not values:
        return "-"
    return f"{sum(values) / len(values):.3f}"


def _scored(rows: list[dict[str, Any]], field: str) -> int:
    """How many rows actually carry a value for `field`.

    Printed beside a mean over a metric that can honestly be `None`: a
    0.95 over three of twenty runs and a 0.95 over twenty are different
    claims, and a bare mean cannot tell them apart (ADR 0074).
    """
    return sum(1 for row in rows if row.get(field) is not None)


def _summary_markdown(records: list[dict[str, Any]], run_id: str) -> str:
    """Human-readable rollup with per-query table and aggregate row."""
    lines_summary = [_summary_line(r) for r in records]
    workflow_cost = sum(r.get("cost_usd") or 0.0 for r in lines_summary)
    judge_cost = sum(r.get("judge_cost_usd") or 0.0 for r in lines_summary)
    errors = sum(1 for r in records if r.get("error"))
    scoring_failures = sum(1 for r in records if r.get("metrics_error"))
    repeats = max((r.get("repeat") or 1 for r in lines_summary), default=1)
    queries = len({r["query_id"] for r in lines_summary})
    lines = [
        f"# Eval run `{run_id}`",
        "",
        f"- **Queries**: {queries}",
        f"- **Runs**: {len(records)}",
        f"- **Repeats per query**: {repeats}",
        f"- **Errors**: {errors}",
        f"- **Partial scores** (judge failed, run kept): {scoring_failures}",
        f"- **Workflow cost**: ${workflow_cost:.4f}",
        f"- **Judge cost**: ${judge_cost:.4f}",
        f"- **Total cost**: ${workflow_cost + judge_cost:.4f}",
    ]
    warning = repeat_warning(repeats)
    if warning:
        # In the artifact, not only on the terminal that produced it:
        # the summary is what a reader opens weeks later, and the
        # repeat count is the first thing that decides whether its
        # aggregates support a comparison (ADR 0071).
        lines += ["", f"> {warning}"]
    lines += [
        "",
        "## Per-run results",
        "",
        "| Run | Cit.Res. | Cited | Cit.Acc. | Complete. | Faithful. | Recall | Critic | Iter | Sec | $ | Calls | Judge $ | Error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for s in lines_summary:
        note = s["error"] or s["metrics_error"]
        lines.append(
            "| "
            + " | ".join(
                [
                    s["record_id"],
                    # The rate and the denominator it is over, side by
                    # side: a `-` under Cit.Res. with a 0 beside it is
                    # "this report cited nothing", which is a finding,
                    # not a missing measurement.
                    _fmt(s["citation_resolution_rate"]),
                    _fmt(s["citations_checked"]),
                    _fmt(s["citation_accuracy"]),
                    _fmt(s["completeness"]),
                    _fmt(s["faithfulness"]),
                    _fmt(s["retrieval_recall"]),
                    _fmt(s["critic_score"]),
                    _fmt(s["iterations"]),
                    _fmt(s["elapsed_sec"]),
                    _fmt(s["cost_usd"]),
                    _fmt(s["llm_calls"]),
                    _fmt(s["judge_cost_usd"]),
                    _fmt_cell_text(note),
                ]
            )
            + " |"
        )

    successful = [s for s in lines_summary if not s["error"]]
    if successful:
        lines += [
            "",
            "## Aggregates (successful runs only)",
            "",
            f"- Mean citation resolution: "
            f"{_mean(successful, 'citation_resolution_rate')} "
            f"({_scored(successful, 'citation_resolution_rate')} of "
            f"{len(successful)} runs cited anything)",
            f"- Mean citation accuracy *(not gated)*: "
            f"{_mean(successful, 'citation_accuracy')}",
            f"- Mean completeness: {_mean(successful, 'completeness')}",
            f"- Mean faithfulness: {_mean(successful, 'faithfulness')}",
            f"- Mean retrieval recall: {_mean(successful, 'retrieval_recall')}",
            f"- Mean critic score: {_mean(successful, 'critic_score')}",
            f"- Mean workflow cost per run: {_mean(successful, 'cost_usd')}",
            f"- Mean workflow LLM calls per run: {_mean(successful, 'llm_calls')}",
            f"- Mean judge cost per run: {_mean(successful, 'judge_cost_usd')}",
        ]

    lines += provenance_markdown(lines_summary)

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


class CampaignShape(NamedTuple):
    """The parts of a durable campaign layout that vary by campaign type.

    ADR 0050's crash-safety properties are not specific to research
    queries: write the full record the moment it exists, append its
    summary row rather than rewriting the file at the end, and rebuild
    both summaries from what is on disk so a subset run cannot publish
    itself as a whole campaign. WO-W10's learner-simulation campaign
    needs those guarantees over a differently-shaped record, so the
    three functions below take what differs as one value instead of
    being copied into a second module.

    Attributes:
        records_dirname: Subdirectory holding one JSON file per record.
        id_field: Record key naming the record — also its filename.
        summary_line: Projects one record onto its `summary.jsonl` row.
        summary_markdown: Renders `summary.md` from records and run id.
        order_key: Canonical sort key for a record id, so a rebuild is
            deterministic whatever the output directory happens to hold.
        legacy_id_field: Key an older record used before `id_field`
            existed, read only when `id_field` is absent. The research
            campaign gained `record_id` with ADR 0071's `--repeats`;
            without this fallback a `--resume` into a campaign started
            before it would treat every record on disk as malformed and
            re-pay for the whole batch.
    """

    records_dirname: str
    id_field: str
    summary_line: Callable[[dict[str, Any]], dict[str, Any]]
    summary_markdown: Callable[[list[dict[str, Any]], str], str]
    order_key: Callable[[str], tuple[int, str]]
    legacy_id_field: str | None = None


def _queries_dir(output_dir: Path, shape: CampaignShape | None = None) -> Path:
    """Directory holding one full JSON record per completed record."""
    return output_dir / (shape or RESEARCH_CAMPAIGN).records_dirname


def _record_key(record: dict[str, Any], layout: CampaignShape) -> str | None:
    """The durable key for one record: `id_field`, else `legacy_id_field`.

    The fallback is what keeps ADR 0071's `record_id` additive. A record
    written by an earlier harness — or by a caller that only knows about
    `query_id` — still persists to the same filename and resumes under
    the same key, so adding a repeat dimension cost no existing campaign
    its resumability.
    """
    for field in (layout.id_field, layout.legacy_id_field):
        value = record.get(field) if field else None
        if isinstance(value, str) and value:
            return value
    return None


def persist_record(
    output_dir: Path,
    record: dict[str, Any],
    *,
    shape: CampaignShape | None = None,
) -> None:
    """Write one query's record to disk, immediately.

    Two writes per query, both cheap next to a multi-minute LLM run:
    the full record as `queries/<query_id>.json`, and its summary line
    appended to `summary.jsonl`. Appending (rather than rewriting the
    file from an in-memory list at the end) is what makes a hard kill
    lose at most the in-flight query, and what stops a re-run from
    truncating a previous campaign's rows (ADR 0050).

    Args:
        output_dir: Campaign directory; created if it does not exist.
        record: The full per-record dict to persist.
        shape: Campaign layout. Defaults to the research campaign, so
            existing callers are unaffected.
    """
    layout = shape or RESEARCH_CAMPAIGN
    queries_dir = _queries_dir(output_dir, layout)
    queries_dir.mkdir(parents=True, exist_ok=True)

    key = _record_key(record, layout)
    if key is None:
        raise KeyError(layout.id_field)
    path = queries_dir / f"{key}.json"
    path.write_text(
        json.dumps(record, indent=2, default=str), encoding="utf-8"
    )

    with (output_dir / "summary.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(layout.summary_line(record), default=str) + "\n")
        handle.flush()


def load_records(
    output_dir: Path, *, shape: CampaignShape | None = None
) -> dict[str, dict[str, Any]]:
    """Read every `queries/*.json` record already in `output_dir`.

    The per-query files are the durable layer — `summary.jsonl` and
    `summary.md` are both derived from them. Unreadable files are
    skipped with a log line rather than failing the campaign: one
    corrupt record must not cost us the other nineteen.

    Args:
        output_dir: Campaign directory to read.
        shape: Campaign layout. Defaults to the research campaign.

    Returns:
        Records keyed by their id field, empty when nothing is on disk.
    """
    layout = shape or RESEARCH_CAMPAIGN
    queries_dir = _queries_dir(output_dir, layout)
    if not queries_dir.is_dir():
        return {}

    records: dict[str, dict[str, Any]] = {}
    for path in sorted(queries_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.exception("eval_record_unreadable", extra={"path": str(path)})
            continue
        record_id = _record_key(payload, layout) if isinstance(payload, dict) else None
        if record_id is not None:
            records[record_id] = payload
        else:
            log.warning("eval_record_malformed", extra={"path": str(path)})
    return records


def _benchmark_order(record_id: str) -> tuple[int, str]:
    """Sort key placing records in benchmark order, then repeat order.

    Unknown IDs (a renamed or retired query whose record is still in
    the directory) sort after the known ones, alphabetically, so the
    rebuild is deterministic whatever the directory holds.
    """
    query_id, repeat = _split_research_record_id(record_id)
    for index, query in enumerate(BENCHMARK_QUERIES):
        if query["query_id"] == query_id:
            return (index, f"{repeat:04d}")
    return (len(BENCHMARK_QUERIES), record_id)


def rebuild_summaries(
    output_dir: Path, run_id: str, *, shape: CampaignShape | None = None
) -> list[dict[str, Any]]:
    """Regenerate `summary.jsonl` + `summary.md` from `queries/*.json`.

    Derived from what is on disk rather than from the in-memory list so
    a partial re-run (`--queries` subset, `--resume`) cannot publish a
    subset as if it were the whole campaign — the failure mode that
    made `readme_update` report "3 / 3 queries" for a 20-query run
    (ADR 0050).

    Args:
        output_dir: Campaign directory to rebuild in place.
        run_id: Campaign id, used as the summary's title.
        shape: Campaign layout. Defaults to the research campaign.

    Returns the records the summaries were built from, in benchmark
    order.
    """
    layout = shape or RESEARCH_CAMPAIGN
    by_id = load_records(output_dir, shape=layout)
    records = [
        by_id[query_id]
        for query_id in sorted(by_id, key=layout.order_key)
    ]
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_jsonl = "\n".join(
        json.dumps(layout.summary_line(r), default=str) for r in records
    )
    (output_dir / "summary.jsonl").write_text(
        summary_jsonl + ("\n" if summary_jsonl else ""), encoding="utf-8"
    )
    (output_dir / "summary.md").write_text(
        layout.summary_markdown(records, run_id), encoding="utf-8"
    )
    return records


#: The research campaign's layout — the default for every function
#: above, so `runner.py`'s own behaviour is unchanged by the
#: parameterization WO-W10 needed.
RESEARCH_CAMPAIGN = CampaignShape(
    records_dirname="queries",
    id_field="record_id",
    summary_line=_summary_line,
    summary_markdown=_summary_markdown,
    order_key=_benchmark_order,
    legacy_id_field="query_id",
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _select_queries(query_ids: list[str] | None) -> list[BenchmarkQuery]:
    """Filter `BENCHMARK_QUERIES` by explicit IDs, preserving requested order."""
    if not query_ids:
        return list(BENCHMARK_QUERIES)
    lookup = {q["query_id"]: q for q in BENCHMARK_QUERIES}
    unknown = [qid for qid in query_ids if qid not in lookup]
    if unknown:
        raise SystemExit(f"Unknown query IDs: {', '.join(unknown)}")
    return [lookup[qid] for qid in query_ids]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-run the workflow on benchmark queries and score."
    )
    parser.add_argument(
        "--queries",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=None,
        help="Comma-separated benchmark query IDs. Default: all.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory. Default: outputs/eval/<utc-timestamp>/",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Re-enter an interrupted campaign: skip queries whose "
            "queries/<id>.json already exists in --output-dir, and fold "
            "those records into the final summary. Required to write "
            "into a non-empty output directory at all."
        ),
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help=(
            f"Runs per query. {REPEATS_FOR_CONFIDENCE} is the bar before "
            "a delta against a baseline is believable on a benchmark "
            "this small; the regression differ aggregates repeats by "
            "query before diffing, so N repeats buy a tighter estimate "
            "of one number rather than N separate comparisons "
            "(ADR 0071). Default: 1. Note that N repeats cost N times "
            "as much."
        ),
    )
    parser.add_argument(
        "--max-budget-usd",
        type=float,
        default=None,
        help=(
            "Stop the campaign once accumulated workflow+judge spend "
            "reaches this ceiling. Checked between queries, so the "
            "final query can overshoot by its own cost."
        ),
    )
    return parser.parse_args(argv)


def repeat_warning(repeats: int) -> str | None:
    """The three-repeat warning, or `None` when the campaign earned silence.

    The research lane's copy of the rule the learning lane has had since
    WO-W10, and the reason `REPEATS_FOR_CONFIDENCE` was advertised in
    code while no research campaign could act on it: until ADR 0071
    there was no `--repeats` flag here at all.

    It warns rather than refuses — one repeat is a perfectly good smoke
    run, and it is only a *comparison against a baseline* that needs
    three.
    """
    if repeats >= REPEATS_FOR_CONFIDENCE:
        return None
    return (
        f"WARNING: this campaign ran {repeats} repeat(s) per query. "
        f"{REPEATS_FOR_CONFIDENCE} repeats are the bar before a delta against "
        "a baseline is believable on an LLM-judged benchmark this small "
        '(planning/05-agentic-upgrade-plan.md, "Judge noise mandates repeat '
        'runs"). Read single-run differences as noise, not as a regression.'
    )


def _check_output_dir(output_dir: Path, *, resume: bool) -> str | None:
    """Refuse to write into a populated directory. Returns an error message.

    Without this, a repair run (`--queries a,b` into last night's
    directory) appends to one campaign's `summary.jsonl` and overwrites
    two of its records — silently destroying campaign data that cost
    real money. `--resume` is the explicit opt-in (ADR 0050).
    """
    if resume or not output_dir.exists():
        return None
    if not output_dir.is_dir():
        return f"Error: output path exists and is not a directory: {output_dir}"
    if any(output_dir.iterdir()):
        return (
            f"Error: output directory {output_dir} is not empty. Re-running "
            "into it would overwrite a previous campaign's records. Pass "
            "--resume to continue that campaign (completed queries are "
            "skipped, not re-paid), or choose a fresh --output-dir."
        )
    return None


def _install_interrupt_handler() -> Callable[[], None]:
    """Make SIGTERM take the same graceful path as Ctrl-C.

    `kill`, `docker stop` and an Actions cancellation all send SIGTERM,
    whose default disposition terminates the process without unwinding
    — no `finally`, no flush. Raising `KeyboardInterrupt` from the
    handler routes them into the same partial-flush path SIGINT already
    had (ADR 0050).

    Returns a callable that restores the previous handler. No-ops when
    called off the main thread (a test harness, say), where
    `signal.signal` is not available.
    """

    def _raise_interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    try:
        previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    except (ValueError, OSError, AttributeError):
        return lambda: None

    def _restore() -> None:
        with contextlib.suppress(ValueError, OSError):
            signal.signal(signal.SIGTERM, previous)

    return _restore


def _print_result(record: dict[str, Any]) -> None:
    """One-line per-query stdout report."""
    line = _summary_line(record)
    if record.get("error"):
        print(f"  ERROR: {record['error']}")
        return
    cost = line["cost_usd"]
    judge_cost = line["judge_cost_usd"]
    parts = [
        # `cres` is the gated citation metric and `n` its denominator.
        # `cit` is the legacy diagnostic, kept on the line so an operator
        # watching a campaign can see the two disagree — which is the
        # whole demonstration in ADR 0074.
        f"  cres={_fmt(line['citation_resolution_rate'])}",
        f"n={_fmt(line['citations_checked'])}",
        f"cit={_fmt(line['citation_accuracy'])}",
        f"comp={_fmt(line['completeness'])}",
        f"faith={_fmt(line['faithfulness'])}",
        f"in {(record.get('elapsed_sec') or 0.0):.1f}s",
    ]
    if cost is not None:
        parts.append(f"${cost:.4f}")
    if judge_cost:
        parts.append(f"(judge ${judge_cost:.4f})")
    if line["stop_reason"]:
        parts.append(f"stop={line['stop_reason']}")
    print(" ".join(parts))
    if record.get("metrics_error"):
        print(f"  PARTIAL SCORE: {record['metrics_error']}")


def _exit_code(
    *,
    attempted: int,
    errored: int,
    interrupted: bool,
    budget_stopped: bool,
) -> int:
    """Map a campaign outcome onto an exit status.

    Precedence is "why is the campaign incomplete" before "how did the
    queries go": an interrupted or budget-stopped run is reported as
    such even when the queries it did run all passed, because the
    remaining queries were never attempted. `make eval` returning 0 on
    a batch where every query errored was the defect this closes
    (ADR 0050).
    """
    if interrupted:
        return EXIT_INTERRUPTED
    if budget_stopped:
        return EXIT_BUDGET_STOP
    if attempted and errored == attempted:
        return EXIT_ALL_FAILED
    if errored:
        return EXIT_PARTIAL_FAILURE
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY not set. "
            "Copy .env.example to .env and add your key."
        )
        return EXIT_CONFIG

    if args.repeats < 1:
        print("Error: --repeats must be at least 1.", file=sys.stderr)
        return EXIT_USAGE

    selected = _select_queries(args.queries)

    # Pinned before the first query, so every record's `seed` field
    # describes the generator state the campaign actually ran under.
    # It does not make the campaign reproducible — the judges are
    # sampled and the API takes no seed — and ADR 0070 says so rather
    # than letting the field imply otherwise.
    seed_campaign()

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)

    problem = _check_output_dir(output_dir, resume=args.resume)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_USAGE

    already_done = load_records(output_dir) if args.resume else {}
    # One entry per (query, repeat), in query-major order so a
    # budget-stopped campaign has every query's first repeat before it
    # has any query's second — a truncated campaign that covered the
    # whole benchmark once is worth far more than one that ran three
    # repeats of the first third.
    pending = [
        (benchmark_query, repeat)
        for repeat in range(1, args.repeats + 1)
        for benchmark_query in selected
        if research_record_id(benchmark_query["query_id"], repeat) not in already_done
    ]
    skipped = (len(selected) * args.repeats) - len(pending)

    print(
        f"Eval run {run_id}: {len(pending)} runs "
        f"({len(selected)} queries x {args.repeats} repeat(s)) -> {output_dir}"
        + (f" (resuming, {skipped} already done)" if skipped else "")
    )
    warning = repeat_warning(args.repeats)
    if warning:
        print(warning)

    attempted = 0
    errored = 0
    # A judge failure is not a query failure — the run is kept and the
    # exit code stays clean — but it is a hole in the night's data, so
    # the closing line names it rather than leaving it for whoever
    # opens summary.md (ADR 0050).
    partially_scored = 0
    spend = sum(_record_total_cost(r) for r in already_done.values())
    interrupted = False
    budget_stopped = False
    restore_handler = _install_interrupt_handler()
    try:
        for i, (benchmark_query, repeat) in enumerate(pending, 1):
            print(
                f"[{i}/{len(pending)}] "
                f"{research_record_id(benchmark_query['query_id'], repeat)}: "
                f"{benchmark_query['query']}"
            )
            record = _run_and_score(benchmark_query, repeat=repeat)
            attempted += 1
            if record.get("error"):
                errored += 1
            if record.get("metrics_error"):
                partially_scored += 1
            persist_record(output_dir, record)
            _print_result(record)

            spend += _record_total_cost(record)
            if args.max_budget_usd is not None and spend >= args.max_budget_usd:
                budget_stopped = True
                print(
                    f"\nBudget ceiling ${args.max_budget_usd:.2f} reached "
                    f"(spent ${spend:.4f} over {attempted} runs). "
                    f"Stopping — {len(pending) - i} runs not made."
                )
                break
    except KeyboardInterrupt as exc:
        interrupted = True
        print("\nInterrupted — flushing partial results.")
        partial = getattr(exc, "record", None)
        if isinstance(partial, dict):
            attempted += 1
            errored += 1
            spend += _record_total_cost(partial)
            persist_record(output_dir, partial)
    finally:
        restore_handler()
        if output_dir.exists():
            records = rebuild_summaries(output_dir, run_id)
            print(f"\nWrote {len(records)} record(s) to {output_dir}")
            print(f"Summary: {output_dir / 'summary.md'}")
            print(
                f"{attempted - errored}/{attempted} succeeded, "
                f"{errored} errored"
                + (
                    f", {partially_scored} partially scored"
                    if partially_scored
                    else ""
                )
                + (f", {skipped} reused" if skipped else "")
                + f", total ${spend:.4f}"
            )

    return _exit_code(
        attempted=attempted,
        errored=errored,
        interrupted=interrupted,
        budget_stopped=budget_stopped,
    )


if __name__ == "__main__":
    sys.exit(main())
