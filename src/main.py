"""Entry point for the arxiv research agent."""

import os
import sys
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.graph.workflow import build_workflow
from src.observability import (
    bind_run_id,
    get_logger,
    reset_run_id,
    start_cost_tracking,
)

load_dotenv()

log = get_logger(__name__)


def _new_run_id() -> str:
    """Generate a short, unique run identifier."""
    return uuid.uuid4().hex[:16]


def run(query: str, run_id: str | None = None) -> str:
    """Run the research agent on a query and return the final report.

    Sets up per-run structured-logging context and a fresh cost
    accumulator so callers get end-of-run cost + timing summaries
    without manual bookkeeping.

    Args:
        query: Natural language research question.
        run_id: Optional pre-assigned run identifier. Defaults to a
            fresh uuid4 hex prefix.

    Returns:
        The final markdown research briefing.
    """
    run_id = run_id or _new_run_id()
    token = bind_run_id(run_id)
    costs = start_cost_tracking()
    start = time.monotonic()

    log.info("run_started", extra={"query": query})
    try:
        app = build_workflow()

        initial_state = {
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
            "messages": [],
        }

        final_state = app.invoke(initial_state)

        log.info(
            "run_completed",
            extra={
                "elapsed_sec": round(time.monotonic() - start, 2),
                "iterations": final_state.get("iteration"),
                "quality_score": final_state.get("quality_score"),
                **costs.as_dict(),
            },
        )
        return final_state["draft_report"]
    except Exception:
        log.exception(
            "run_failed",
            extra={
                "elapsed_sec": round(time.monotonic() - start, 2),
                **costs.as_dict(),
            },
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

    os.makedirs("outputs", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"outputs/report_{timestamp}.md"
    with open(filename, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to {filename}")


if __name__ == "__main__":
    main()
