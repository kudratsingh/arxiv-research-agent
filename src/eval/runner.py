"""Batch eval runner.

Invokes the workflow on each benchmark query, scores the resulting
report with the four metrics in `src/eval/metrics.py`, and writes a
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

from src.eval.benchmark_queries import BENCHMARK_QUERIES, BenchmarkQuery
from src.eval.metrics import (
    measure_citation_accuracy,
    measure_completeness,
    measure_faithfulness,
    measure_retrieval_recall,
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
    """Score a completed run with all four metrics. Never raises.

    Each metric is computed inside its own guard: three of the four are
    LLM-as-judge calls, and a judge that times out, 429s past its
    retries, or truncates into invalid JSON must not cost us the
    workflow output we already paid for (ADR 0050). A failed metric
    lands as `None` in the returned dict — `_get_score` already reads
    that as "no score" — and its message is folded into the second
    return value.

    Returns:
        `(metrics, metrics_error)` where `metrics` maps every metric
        name to its result dict or `None`, and `metrics_error` is a
        `"; "`-joined summary of the failures or `None` when all four
        scored.
    """
    report = state.get("draft_report", "")
    papers = state.get("papers", [])
    citations = state.get("citations", [])
    topics = benchmark_query["expected_topics"]

    scorers: list[tuple[str, Callable[[], dict[str, Any]]]] = [
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


def _run_and_score(benchmark_query: BenchmarkQuery) -> dict[str, Any]:
    """Invoke the workflow, apply metrics, capture timing / errors / costs.

    Never raises for a workflow or judge failure — errors are captured
    on the record so the outer loop keeps making progress (ADR 0008).
    The one exception that does leave this function is
    `EvalInterrupted`, which carries the partial record out to `main()`
    so a Ctrl-C'd query's spend is still written down.

    The returned record splits harness spend from product spend:
    `costs` / `elapsed_sec` cover the workflow invocation only, while
    `judge_costs` / `scoring_sec` cover the metric calls that follow it.
    """
    run_id = uuid.uuid4().hex[:16]
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()
    app: Any = None

    record: dict[str, Any] = {
        "run_id": run_id,
        "query_id": benchmark_query["query_id"],
        "query": benchmark_query["query"],
        "domain": benchmark_query["domain"],
        "elapsed_sec": 0.0,
        "scoring_sec": None,
        "costs": costs.as_dict(),
        "judge_costs": None,
        "state": None,
        "metrics": None,
        "metrics_error": None,
        "error": None,
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


def _summary_line(record: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields that go into `summary.jsonl` / `summary.md`.

    `cost_usd` / `llm_calls` / `elapsed_sec` describe the **workflow**
    only. The judges' own spend rides in `judge_cost_usd` /
    `judge_llm_calls`, and `total_cost_usd` is their sum — the number
    that answers "what did this benchmark query cost me to run".
    Before ADR 0050 the three product fields silently included judge
    spend, so summaries older than that ADR are not comparable on cost.
    """
    metrics = record.get("metrics")
    state = record.get("state") or {}
    costs = record.get("costs") or {}
    judge_costs = record.get("judge_costs") or {}
    workflow_cost = costs.get("total_cost_usd")
    judge_cost = judge_costs.get("total_cost_usd")
    return {
        "query_id": record["query_id"],
        "elapsed_sec": record.get("elapsed_sec"),
        "scoring_sec": record.get("scoring_sec"),
        "error": record.get("error"),
        "metrics_error": record.get("metrics_error"),
        "citation_accuracy": _get_score(metrics, "citation_accuracy"),
        "completeness": _get_score(metrics, "completeness"),
        "faithfulness": _get_score(metrics, "faithfulness"),
        "retrieval_recall": _get_score(metrics, "retrieval_recall"),
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


def _summary_markdown(records: list[dict[str, Any]], run_id: str) -> str:
    """Human-readable rollup with per-query table and aggregate row."""
    lines_summary = [_summary_line(r) for r in records]
    workflow_cost = sum(r.get("cost_usd") or 0.0 for r in lines_summary)
    judge_cost = sum(r.get("judge_cost_usd") or 0.0 for r in lines_summary)
    errors = sum(1 for r in records if r.get("error"))
    scoring_failures = sum(1 for r in records if r.get("metrics_error"))
    lines = [
        f"# Eval run `{run_id}`",
        "",
        f"- **Queries**: {len(records)}",
        f"- **Errors**: {errors}",
        f"- **Partial scores** (judge failed, run kept): {scoring_failures}",
        f"- **Workflow cost**: ${workflow_cost:.4f}",
        f"- **Judge cost**: ${judge_cost:.4f}",
        f"- **Total cost**: ${workflow_cost + judge_cost:.4f}",
        "",
        "## Per-query results",
        "",
        "| Query | Cit.Acc. | Complete. | Faithful. | Recall | Critic | Iter | Sec | $ | Calls | Judge $ | Error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for s in lines_summary:
        note = s["error"] or s["metrics_error"]
        lines.append(
            "| "
            + " | ".join(
                [
                    s["query_id"],
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
            f"- Mean citation accuracy: {_mean(successful, 'citation_accuracy')}",
            f"- Mean completeness: {_mean(successful, 'completeness')}",
            f"- Mean faithfulness: {_mean(successful, 'faithfulness')}",
            f"- Mean retrieval recall: {_mean(successful, 'retrieval_recall')}",
            f"- Mean critic score: {_mean(successful, 'critic_score')}",
            f"- Mean workflow cost per query: {_mean(successful, 'cost_usd')}",
            f"- Mean workflow LLM calls per query: {_mean(successful, 'llm_calls')}",
            f"- Mean judge cost per query: {_mean(successful, 'judge_cost_usd')}",
        ]

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
    """

    records_dirname: str
    id_field: str
    summary_line: Callable[[dict[str, Any]], dict[str, Any]]
    summary_markdown: Callable[[list[dict[str, Any]], str], str]
    order_key: Callable[[str], tuple[int, str]]


def _queries_dir(output_dir: Path, shape: CampaignShape | None = None) -> Path:
    """Directory holding one full JSON record per completed record."""
    return output_dir / (shape or RESEARCH_CAMPAIGN).records_dirname


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

    path = queries_dir / f"{record[layout.id_field]}.json"
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
        if isinstance(payload, dict) and isinstance(
            payload.get(layout.id_field), str
        ):
            records[payload[layout.id_field]] = payload
        else:
            log.warning("eval_record_malformed", extra={"path": str(path)})
    return records


def _benchmark_order(query_id: str) -> tuple[int, str]:
    """Sort key placing benchmark queries in their canonical order.

    Unknown IDs (a renamed or retired query whose record is still in
    the directory) sort after the known ones, alphabetically, so the
    rebuild is deterministic whatever the directory holds.
    """
    for index, query in enumerate(BENCHMARK_QUERIES):
        if query["query_id"] == query_id:
            return (index, query_id)
    return (len(BENCHMARK_QUERIES), query_id)


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
    id_field="query_id",
    summary_line=_summary_line,
    summary_markdown=_summary_markdown,
    order_key=_benchmark_order,
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
        f"  cit={_fmt(line['citation_accuracy'])}",
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

    selected = _select_queries(args.queries)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)

    problem = _check_output_dir(output_dir, resume=args.resume)
    if problem:
        print(problem, file=sys.stderr)
        return EXIT_USAGE

    already_done = load_records(output_dir) if args.resume else {}
    pending = [q for q in selected if q["query_id"] not in already_done]
    skipped = len(selected) - len(pending)

    print(
        f"Eval run {run_id}: {len(pending)} queries -> {output_dir}"
        + (f" (resuming, {skipped} already done)" if skipped else "")
    )

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
        for i, benchmark_query in enumerate(pending, 1):
            print(
                f"[{i}/{len(pending)}] {benchmark_query['query_id']}: "
                f"{benchmark_query['query']}"
            )
            record = _run_and_score(benchmark_query)
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
                    f"(spent ${spend:.4f} over {attempted} queries). "
                    f"Stopping — {len(pending) - i} queries not run."
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
