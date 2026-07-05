"""Entry point for the arxiv research agent."""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.graph.workflow import build_workflow

load_dotenv()


def run(query: str) -> str:
    """Run the research agent on a query and return the final report.

    Args:
        query: Natural language research question.

    Returns:
        The final markdown research briefing.
    """
    app = build_workflow()

    initial_state = {
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

    return final_state["draft_report"]


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

    # Save to outputs/
    os.makedirs("outputs", exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"outputs/report_{timestamp}.md"
    with open(filename, "w") as f:
        f.write(report)

    print(report)
    print(f"\nReport saved to {filename}")


if __name__ == "__main__":
    main()
