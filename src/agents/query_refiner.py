"""Query refiner agent — recovery action for weak search results.

The supervisor loop's `search` action re-runs whatever's in
`state.search_queries`. Without a way to generate *new* queries, "search
again" is just "search the same thing again" — the loop thrashes
instead of recovers. The refiner closes that gap: given the original
question, what has already been tried, what the retrieved papers cover,
and any critic / verifier feedback, it emits a fresh set of queries
targeted at the gaps.

Design (ADR 0018):
- **Supervisor-only.** Under the fixed pipeline the refiner is never
  invoked; the fixed pipeline has no re-search. Gated by
  `settings.enable_query_refiner`.
- **Dedupe against history.** Refiner appends the currently-in-flight
  `search_queries` into `tried_search_queries` and drops any LLM
  output that duplicates something already tried. Normalization is
  lowercase + strip.
- **Fail closed, not open.** If the LLM returns nothing usable
  (exception, empty list, all duplicates), the refiner **keeps the
  current `search_queries` unchanged** and logs a warning. Better to
  re-run a weak query than to blank out the state and stall the loop.
"""

from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.graph.state import ResearchState
from src.llm import call_llm_json
from src.observability import get_logger

log = get_logger(__name__)


QUERY_REFINER_SYSTEM_PROMPT = """\
You are an arXiv search query refiner. The current search queries have
already been tried and produced weak or incomplete results. Your job:
propose a fresh set of arXiv search queries that target the specific
gaps in coverage, not the same territory again.

Inputs you will see:
- The user's original research question.
- The planner's sub-questions.
- The queries already tried (do NOT repeat any of them, even
  paraphrased).
- Titles + abstracts of papers already retrieved (informs what is
  already covered — don't chase these topics).
- Optional critic feedback and/or verifier-reported missing evidence
  (this is where the gaps are — target these directly).

Rules:
- Emit at most {max_queries} new queries.
- Queries must be concise keyword phrases (not full sentences), the
  same style arXiv search takes. Standard ML/AI terminology.
- Each new query MUST be meaningfully different from every already-
  tried query. Rewording is not enough — go after a distinct angle,
  synonym family, methodology, benchmark, or subfield.
- Prefer queries that target the listed gaps (missing evidence,
  critic-flagged coverage holes) over broad rewordings of the
  original question.
- If you cannot identify any genuinely new angle, return an empty
  list — do not pad with paraphrases.

Return JSON only, no markdown fencing:
{{
  "queries": ["...", "..."],
  "reason": "one-sentence explanation of what gap each cluster targets"
}}
"""


def _normalize(query: str) -> str:
    """Lowercase + strip, for dedup comparisons."""
    return query.strip().lower()


def _format_papers_block(state: ResearchState) -> str:
    """Compact papers list — title + first 40 words of abstract per paper.

    Kept short so the refiner prompt stays cheap; the LLM only needs
    to know what territory has already been covered, not the papers'
    full contents.
    """
    papers = state.get("papers", [])
    if not papers:
        return "(no papers retrieved yet)"

    lines: list[str] = []
    for paper in papers:
        title = paper.get("title", "(untitled)")
        abstract = (paper.get("abstract") or "").split()
        summary = " ".join(abstract[:40])
        suffix = "..." if len(abstract) > 40 else ""
        lines.append(f"- {title}\n    {summary}{suffix}")
    return "\n".join(lines)


def _build_user_prompt(state: ResearchState) -> str:
    """Assemble the refiner's user message."""
    sub_questions = state.get("sub_questions", [])
    current_queries = state.get("search_queries", [])
    tried = state.get("tried_search_queries", [])
    critique = state.get("critique", "")
    missing = state.get("missing_evidence", [])

    all_tried = list(tried) + list(current_queries)
    tried_lines = "\n".join(f"  - {q}" for q in all_tried) or "  (none)"
    sub_q_lines = "\n".join(f"  - {q}" for q in sub_questions) or "  (none)"
    missing_lines = "\n".join(f"  - {m}" for m in missing) or "  (none reported)"

    parts = [
        f"Original research question: {state.get('query', '(unknown)')}",
        "",
        "Planner sub-questions:",
        sub_q_lines,
        "",
        "Already-tried search queries:",
        tried_lines,
        "",
        "Papers already retrieved (title + abstract head):",
        _format_papers_block(state),
        "",
        "Verifier-reported missing evidence:",
        missing_lines,
    ]
    if critique:
        parts.extend(["", "Critic feedback (address these gaps):", critique])

    return "\n".join(parts)


def _keep_current(state: ResearchState, reason: str) -> dict[str, Any]:
    """Partial update that leaves search state alone. Logs why."""
    log.warning("query_refiner_kept_current", extra={"reason": reason})
    return {
        "messages": [
            AIMessage(
                content=f"query_refiner -> kept current queries: {reason}",
                name="query_refiner",
            )
        ]
    }


def query_refiner_agent(state: ResearchState) -> dict[str, Any]:
    """Emit a fresh set of search queries targeted at coverage gaps.

    Reads: `query`, `sub_questions`, `search_queries` (currently in
    flight), `tried_search_queries` (history), `papers`, `critique`,
    `missing_evidence`.

    Writes: `search_queries` (replaced with the refined set) and
    `tried_search_queries` (extended with the queries that just moved
    out of `search_queries`). Only takes those actions when the LLM
    returns non-empty, non-duplicate output.

    Args:
        state: Full `ResearchState`.

    Returns:
        Partial state update. When the LLM output is unusable, only a
        `messages` entry is returned — `search_queries` stays intact so
        the supervisor can decide to search again or give up.
    """
    current_queries = list(state.get("search_queries", []))
    tried = list(state.get("tried_search_queries", []))

    user_prompt = _build_user_prompt(state)
    system_prompt = QUERY_REFINER_SYSTEM_PROMPT.format(
        max_queries=settings.query_refiner_max_queries
    )

    try:
        parsed = call_llm_json(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model_name=settings.query_refiner_model or None,
            max_tokens=1024,
            cache_system=settings.enable_prompt_caching,
        )
    except Exception as exc:  # noqa: BLE001 — recoverable, log + hold
        return _keep_current(
            state, f"LLM call failed ({type(exc).__name__})"
        )

    raw_queries = parsed.get("queries", [])
    if not isinstance(raw_queries, list):
        return _keep_current(state, "LLM returned non-list 'queries' field")

    # Dedup against everything already tried (history + currently
    # in-flight). Preserve order of first occurrence within this batch.
    forbidden = {_normalize(q) for q in tried + current_queries}
    seen_this_batch: set[str] = set()
    fresh: list[str] = []
    for raw in raw_queries[: settings.query_refiner_max_queries]:
        if not isinstance(raw, str):
            continue
        candidate = raw.strip()
        if not candidate:
            continue
        key = _normalize(candidate)
        if key in forbidden or key in seen_this_batch:
            continue
        seen_this_batch.add(key)
        fresh.append(candidate)

    if not fresh:
        return _keep_current(
            state, "LLM returned no queries distinct from history"
        )

    reason = str(parsed.get("reason", "")).strip() or "(no reason given)"
    return {
        "search_queries": fresh,
        "tried_search_queries": tried + current_queries,
        "messages": [
            AIMessage(
                content=(
                    f"query_refiner -> {len(fresh)} new queries "
                    f"(dropped {len(raw_queries) - len(fresh)} dupes). {reason}"
                ),
                name="query_refiner",
            )
        ],
    }
