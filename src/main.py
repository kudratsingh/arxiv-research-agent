"""Entry point for the arxiv research agent.

CLI counterpart to the API's job runner: one query in, one markdown
briefing out, written under `outputs/`.

Failure handling here is shaped by one fact about this graph (ADR
0052): the synthesizer runs before the critic, so a failure in a
*later* node happens with a finished report already sitting in the
checkpoint. The pre-0052 CLI re-raised and exited, and that report —
already paid for, in full — was unreachable, because nothing on the
CLI surface reads a checkpoint. `run` now salvages it to
`outputs/<run_id>-recovered.md` before re-raising, and logs the
`thread_id` on every failure so a manual recovery is possible even
when the salvage itself cannot run.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.graph.state import initial_research_state
from src.graph.workflow import build_workflow
from src.observability import (
    bind_run_id,
    get_logger,
    reset_run_id,
    start_cost_tracking,
)

load_dotenv()

log = get_logger(__name__)

#: Where reports (and salvaged partials) land.
OUTPUT_DIR = Path("outputs")


def _new_run_id() -> str:
    """Generate a short, unique run identifier."""
    return uuid.uuid4().hex[:16]


def _recover_draft_report(app: Any, config: dict[str, Any], run_id: str) -> Path | None:
    """Salvage a finished report from the checkpoint after a failed run.

    Best-effort by construction: this runs from an `except` block, and
    anything it raises would mask the real failure the caller is about
    to re-raise. Every step is therefore guarded and a miss returns
    None rather than propagating.

    Checkpointing may also be off entirely
    (`settings.enable_checkpointing=False`), in which case
    `get_state` has no saver to read and raises — same treatment.

    Args:
        app: The compiled graph the failed run was invoked on.
        config: The same `configurable.thread_id` config that run used
            — the checkpoint is per-thread, and the wrong thread reads
            as empty rather than as an error.
        run_id: Names the output file.

    Returns:
        Path to the written file, or None when there was nothing to
        recover (no checkpoint, empty `draft_report`, unwritable
        output directory).
    """
    try:
        snapshot = app.get_state(config)
    except Exception as exc:
        log.warning(
            "run_recovery_state_unavailable",
            extra={"thread_id": run_id, "error": str(exc)},
        )
        return None

    values = getattr(snapshot, "values", None) or {}
    draft = values.get("draft_report") or ""
    if not isinstance(draft, str) or not draft.strip():
        log.info(
            "run_recovery_nothing_to_recover",
            extra={"thread_id": run_id},
        )
        return None

    dest = OUTPUT_DIR / f"{run_id}-recovered.md"
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_text(draft)
    except OSError as exc:
        log.warning(
            "run_recovery_write_failed",
            extra={"thread_id": run_id, "path": str(dest), "error": str(exc)},
        )
        return None

    log.info(
        "run_recovery_wrote_partial",
        extra={
            "thread_id": run_id,
            "path": str(dest),
            "report_chars": len(draft),
        },
    )
    return dest


def run(query: str, run_id: str | None = None) -> str:
    """Run the research agent on a query and return the final report.

    Sets up per-run structured-logging context and a fresh cost
    accumulator so callers get end-of-run cost + timing summaries
    without manual bookkeeping.

    On failure the exception is re-raised unchanged — the caller's
    exit code and traceback are the contract — but not before the
    checkpoint is checked for a report the run already produced. See
    the module docstring for why that matters.

    Args:
        query: Natural language research question.
        run_id: Optional pre-assigned run identifier. Defaults to a
            fresh uuid4 hex prefix. Doubles as the checkpoint
            `thread_id`.

    Returns:
        The final markdown research briefing.
    """
    run_id = run_id or _new_run_id()
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()
    # Bound before the try so the failure path can name the thread even
    # when `build_workflow` itself is what blew up.
    app: Any = None
    # thread_id gates checkpoint isolation — one thread per run so
    # resuming the same run picks up where it left off, and unrelated
    # runs don't share state.
    config: dict[str, Any] = {"configurable": {"thread_id": run_id}}

    log.info("run_started", extra={"query": query})
    try:
        # CLI is a fire-and-forget entry point — no way to accept a
        # mid-run plan review from stdin. Bypass HITL; the API path
        # (ADR 0030) is where reviewers actually approve plans.
        app = build_workflow(enable_hitl=False)

        final_state = app.invoke(initial_research_state(query, run_id), config=config)

        log.info(
            "run_completed",
            extra={
                "elapsed_sec": round(time.monotonic() - start, 2),
                "iterations": final_state.get("iteration"),
                "quality_score": final_state.get("quality_score"),
                **costs.as_dict(),
            },
        )
        report: str = final_state["draft_report"]
        return report
    except Exception:
        recovered: Path | None = None
        if app is not None:
            recovered = _recover_draft_report(app, config, run_id)
        log.exception(
            "run_failed",
            extra={
                "elapsed_sec": round(time.monotonic() - start, 2),
                # The thread_id is the only handle on this run's
                # checkpoint. Logging it unconditionally means a
                # failure the salvage could not handle is still
                # recoverable by hand.
                "thread_id": run_id,
                "recovered_path": str(recovered) if recovered else None,
                **costs.as_dict(),
            },
        )
        if recovered is not None:
            print(
                f"\nRun failed, but a report was recovered from the "
                f"checkpoint: {recovered}",
                file=sys.stderr,
            )
        else:
            print(
                f"\nRun failed with no recoverable report. Checkpoint "
                f"thread_id: {run_id}",
                file=sys.stderr,
            )
        raise
    finally:
        reset_run_id(token)


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m src.main \"<research question>\"")
        sys.exit(1)

    query = sys.argv[1]
    print(f"Researching: {query}\n")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)

    report = run(query)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"report_{timestamp}.md"
    filename.write_text(report)

    print(report)
    print(f"\nReport saved to {filename}")


if __name__ == "__main__":
    main()
