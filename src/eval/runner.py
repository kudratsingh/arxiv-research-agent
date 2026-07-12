"""Batch eval runner.

Invokes the workflow on each benchmark query, scores the resulting
report with the three metrics in `src/eval/metrics.py`, and writes a
layered output artifact:

    outputs/eval/<run_id>/
        queries/<query_id>.json  — full record per query
        summary.jsonl            — machine-readable per-query line
        summary.md               — human-readable table + aggregates

Design (see ADR 0008):
  - Queries run sequentially. Parallelism is a follow-up — rate limits
    on arXiv and Anthropic dominate at Phase-2 scale.
  - Per-query error tolerance: a broken query is captured with its
    traceback and reported, but does not abort the run.
  - Fresh workflow per query (via `build_workflow()`) for isolation —
    LangGraph state does not leak between runs.
  - Interrupt-safe: Ctrl-C flushes partial results to disk before exit.

Usage:
    python -m src.eval.runner
    python -m src.eval.runner --queries hallucination-mitigation,rag-multi-hop
    python -m src.eval.runner --output-dir outputs/eval/manual-run-a
"""

import argparse
import json
import os
import sys
import time
import traceback
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
) -> dict[str, Any]:
    """Score a completed run with all four metrics."""
    report = state.get("draft_report", "")
    papers = state.get("papers", [])
    topics = benchmark_query["expected_topics"]
    return {
        "citation_accuracy": dict(
            measure_citation_accuracy(report, state.get("citations", []))
        ),
        "completeness": dict(
            measure_completeness(report, topics)
        ),
        "faithfulness": dict(
            measure_faithfulness(
                report,
                papers,
                state.get("citations", []),
            )
        ),
        "retrieval_recall": dict(
            measure_retrieval_recall(papers, topics)
        ),
    }


def _run_and_score(benchmark_query: BenchmarkQuery) -> dict[str, Any]:
    """Invoke the workflow, apply metrics, capture timing / errors / costs.

    Never raises — errors are captured on the record so the outer loop
    keeps making progress.
    """
    run_id = uuid.uuid4().hex[:16]
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()

    log.info(
        "eval_query_started",
        extra={
            "query_id": benchmark_query["query_id"],
            "domain": benchmark_query["domain"],
        },
    )
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
        elapsed = time.monotonic() - start
        log.exception(
            "eval_query_failed",
            extra={
                "query_id": benchmark_query["query_id"],
                "elapsed_sec": round(elapsed, 2),
                **costs.as_dict(),
            },
        )
        reset_run_id(token)
        return {
            "run_id": run_id,
            "query_id": benchmark_query["query_id"],
            "query": benchmark_query["query"],
            "domain": benchmark_query["domain"],
            "elapsed_sec": elapsed,
            "costs": costs.as_dict(),
            "state": None,
            "metrics": None,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }

    metrics = _compute_metrics(final_state, benchmark_query)
    elapsed = time.monotonic() - start
    costs_snapshot = costs.as_dict()
    log.info(
        "eval_query_completed",
        extra={
            "query_id": benchmark_query["query_id"],
            "elapsed_sec": round(elapsed, 2),
            "citation_accuracy": metrics["citation_accuracy"]["score"],
            "completeness": metrics["completeness"]["score"],
            "faithfulness": metrics["faithfulness"]["score"],
            **costs_snapshot,
        },
    )
    reset_run_id(token)
    return {
        "run_id": run_id,
        "query_id": benchmark_query["query_id"],
        "query": benchmark_query["query"],
        "domain": benchmark_query["domain"],
        "elapsed_sec": elapsed,
        "costs": costs_snapshot,
        "state": _serialize_state(final_state),
        "metrics": metrics,
        "error": None,
    }


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


def _summary_line(record: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields that go into `summary.jsonl` / `summary.md`."""
    metrics = record.get("metrics")
    state = record.get("state") or {}
    costs = record.get("costs") or {}
    return {
        "query_id": record["query_id"],
        "elapsed_sec": record.get("elapsed_sec"),
        "error": record.get("error"),
        "citation_accuracy": _get_score(metrics, "citation_accuracy"),
        "completeness": _get_score(metrics, "completeness"),
        "faithfulness": _get_score(metrics, "faithfulness"),
        "retrieval_recall": _get_score(metrics, "retrieval_recall"),
        "critic_score": state.get("quality_score"),
        "iterations": state.get("iteration"),
        "cost_usd": costs.get("total_cost_usd"),
        "llm_calls": costs.get("call_count"),
        "loop_iterations": state.get("loop_iterations"),
        "stop_reason": state.get("stop_reason"),
    }


def _fmt(value: Any) -> str:
    """Format a scalar for the markdown table."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _mean(rows: list[dict[str, Any]], field: str) -> str:
    """Mean of `rows[*][field]`, ignoring `None`s. Returns `-` when empty."""
    values = [r[field] for r in rows if r.get(field) is not None]
    if not values:
        return "-"
    return f"{sum(values) / len(values):.3f}"


def _summary_markdown(records: list[dict[str, Any]], run_id: str) -> str:
    """Human-readable rollup with per-query table and aggregate row."""
    total_cost = sum(
        (r.get("costs") or {}).get("total_cost_usd", 0.0) or 0.0
        for r in records
    )
    lines = [
        f"# Eval run `{run_id}`",
        "",
        f"- **Queries**: {len(records)}",
        f"- **Errors**: {sum(1 for r in records if r.get('error'))}",
        f"- **Total cost**: ${total_cost:.4f}",
        "",
        "## Per-query results",
        "",
        "| Query | Cit.Acc. | Complete. | Faithful. | Recall | Critic | Iter | Sec | $ | Calls | Error |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        s = _summary_line(record)
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
                    s["error"] or "-",
                ]
            )
            + " |"
        )

    successful = [
        _summary_line(r) for r in records if not r.get("error")
    ]
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
            f"- Mean cost per query: {_mean(successful, 'cost_usd')}",
            f"- Mean LLM calls per query: {_mean(successful, 'llm_calls')}",
        ]

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def _write_output(
    output_dir: Path, records: list[dict[str, Any]], run_id: str
) -> None:
    """Write `queries/*.json`, `summary.jsonl`, and `summary.md`."""
    queries_dir = output_dir / "queries"
    queries_dir.mkdir(parents=True, exist_ok=True)

    for record in records:
        path = queries_dir / f"{record['query_id']}.json"
        path.write_text(
            json.dumps(record, indent=2, default=str), encoding="utf-8"
        )

    summary_jsonl = "\n".join(
        json.dumps(_summary_line(r)) for r in records
    )
    (output_dir / "summary.jsonl").write_text(
        summary_jsonl + ("\n" if summary_jsonl else ""), encoding="utf-8"
    )

    (output_dir / "summary.md").write_text(
        _summary_markdown(records, run_id), encoding="utf-8"
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
    return parser.parse_args(argv)


def _print_result(record: dict[str, Any]) -> None:
    """One-line per-query stdout report."""
    if record.get("error"):
        print(f"  ERROR: {record['error']}")
        return
    metrics = record["metrics"]
    costs = record.get("costs") or {}
    cost_str = f" ${costs.get('total_cost_usd', 0.0):.4f}" if costs else ""
    print(
        f"  cit={metrics['citation_accuracy']['score']:.2f} "
        f"comp={metrics['completeness']['score']:.2f} "
        f"faith={metrics['faithfulness']['score']:.2f} "
        f"in {record['elapsed_sec']:.1f}s{cost_str}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "Error: ANTHROPIC_API_KEY not set. "
            "Copy .env.example to .env and add your key."
        )
        return 1

    selected = _select_queries(args.queries)

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / run_id)

    print(
        f"Eval run {run_id}: {len(selected)} queries -> {output_dir}"
    )

    records: list[dict[str, Any]] = []
    try:
        for i, benchmark_query in enumerate(selected, 1):
            print(
                f"[{i}/{len(selected)}] {benchmark_query['query_id']}: "
                f"{benchmark_query['query']}"
            )
            record = _run_and_score(benchmark_query)
            records.append(record)
            _print_result(record)
    except KeyboardInterrupt:
        print("\nInterrupted — flushing partial results.")
    finally:
        if records:
            _write_output(output_dir, records, run_id)
            print(f"\nWrote {len(records)} record(s) to {output_dir}")
            print(f"Summary: {output_dir / 'summary.md'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
