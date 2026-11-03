"""Inspectable lexical ranking and reading-budget selection, without models.

Scores measure matching signals, never personal usefulness or factual quality.
The owner's later relevance labels remain empty in the candidate export.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from src.workspace.interests import topic_stream, topic_terms

POLICY_VERSION = "workspace-lexical-v2"
STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "build",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "our",
        "own",
        "that",
        "the",
        "their",
        "them",
        "these",
        "this",
        "through",
        "to",
        "useful",
        "we",
        "what",
        "when",
        "which",
        "with",
        "you",
        "your",
    ]
)
TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    "ml:agents-and-tool-use": (
        "agent",
        "agentic",
        "tool use",
        "planning",
        "autonomous",
        "context management",
        "research automation",
    ),
    "ml:retrieval-and-memory": (
        "retrieval",
        "rag",
        "reranking",
        "knowledge",
        "memory",
        "citation graph",
    ),
    "ml:evaluation-and-responsible-ml": (
        "evaluation",
        "benchmark",
        "verification",
        "calibration",
        "uncertainty",
        "reproducible",
    ),
    "ml:reasoning-and-inference-time-compute": (
        "reasoning",
        "inference",
        "test-time",
        "routing",
        "compute",
    ),
    "ml:ml-systems-and-efficiency": (
        "inference",
        "efficient",
        "caching",
        "latency",
        "quantization",
        "compute",
    ),
    "ml:machine-learning-for-science": (
        "scientific",
        "simulation",
        "digital twin",
        "differentiable",
        "system identification",
    ),
    "study:22/control-systems": ("control", "controller", "pid", "sim-to-real", "model-based"),
    "ml:embodied-intelligence/model-based-reinforcement-learning": (
        "model-based",
        "reinforcement learning",
        "control",
        "world model",
    ),
    "ml:multimodal-and-perception/3d-perception": ("3d", "spatial", "scene", "navigation"),
    "ml:generative-models/controllable-generation": (
        "controllable",
        "procedural",
        "generation",
        "unreal",
    ),
    "ml:embodied-intelligence": ("embodied", "navigation", "sim-to-real", "robot"),
}
STREAM_TOPICS = {
    "core": tuple(list(TOPIC_TERMS)[:5]),
    "rocket-twin": tuple(list(TOPIC_TERMS)[5:8]),
    "spatial": tuple(list(TOPIC_TERMS)[8:]),
}
SOURCE_COVERAGE = {
    "core": ["arxiv-cs-lg", "arxiv-cs-ai", "arxiv-cs-cl", "hugging-face-blog", "google-research"],
    "rocket-twin": ["arxiv-cs-lg", "arxiv-cs-ai", "google-research"],
    "spatial": ["arxiv-cs-ai", "arxiv-cs-lg", "hugging-face-blog"],
}


def _tokens(value: str) -> set[str]:
    return {t for t in re.findall(r"[\w-]+", value.lower()) if len(t) >= 3 and t not in STOP_WORDS}


def _contains(text: str, term: str) -> bool:
    # Word boundaries avoid `rag` matching `fragment`, but permit agent/agents
    # only where the authored vocabulary explicitly includes the singular.
    return (
        bool(term.strip())
        and re.search(r"(?<!\w)" + re.escape(term.lower()) + r"s?(?!\w)", text) is not None
    )


def _date(item: Mapping[str, Any]) -> datetime | None:
    raw = item.get("updated_at") or item.get("published_at") or item.get("announced_at")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except ValueError:
        return None


def _chronological_key(item: Mapping[str, Any]) -> tuple[float, str]:
    date = _date(item)
    return -(date.timestamp() if date else 0), str(item["work_id"])


def _state(item: Mapping[str, Any], states: Mapping[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    return states.get(str(item["work_id"]), item.get("reading") or {})


def rank_items(
    items: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    states: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    mode: str = "relevance",
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """Rank one fixed candidate window with deterministic reasons and tie breaks.

    Exclusions are hard constraints for every baseline. Disabled streams remove
    their topics; a manually selected topic/custom concept remains independent.
    Profile question terms contribute only after a topic/custom match, avoiding
    a generic question about research matching every publication. No click is a
    preference update. Unknown publication times receive no recency bonus.
    """
    if mode not in {"relevance", "chronological", "keyword"}:
        raise ValueError("unknown_ranking_mode")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("timezone_required")
    state_map = states or {}
    enabled_streams = set(profile.get("streams", ["core", "rocket-twin", "spatial"]))
    topics = list(profile.get("topics", []))
    terms = [
        (term, topic)
        for topic in topics
        if topic_stream(topic) in enabled_streams
        for term in topic_terms(topic, TOPIC_TERMS)
    ]
    custom = list(profile.get("custom_topics", profile.get("customTopics", [])))
    terms.extend((str(term), "custom interest") for term in custom)
    exclusions = [str(v) for v in profile.get("exclusions", [])]
    question = _tokens(str(profile.get("research_question", profile.get("researchQuestion", ""))))
    ranked: list[dict[str, Any]] = []
    seen_works: set[str] = set()
    for item in items:
        work_id = str(item["work_id"])
        if work_id in seen_works:
            continue
        seen_works.add(work_id)
        state = _state(item, state_map)
        status = state.get("status", "unread")
        snoozed_until = state.get("snoozed_until")
        snoozed = False
        if status == "snoozed" and isinstance(snoozed_until, str):
            try:
                snoozed = datetime.fromisoformat(snoozed_until.replace("Z", "+00:00")) > current
            except (ValueError, TypeError):
                snoozed = True  # malformed persisted snooze stays hidden pending repair
        if not include_hidden and (status in {"archived", "dismissed"} or snoozed):
            continue
        text = " ".join(
            (
                str(item.get("title", "")),
                str(item.get("abstract", "")),
                " ".join(item.get("categories") or []),
            )
        ).lower()
        if any(_contains(text, term) for term in exclusions):
            continue
        matches = sorted({term.lower() for term, _ in terms if _contains(text, term)})
        matched_topics = sorted({topic for term, topic in terms if _contains(text, term)})
        question_matches = sorted(_tokens(text) & question) if matches else []
        keyword_score = min(24, len(matches) * 4) + min(6, len(question_matches))
        date = _date(item)
        age = max(0.0, (current - date).total_seconds() / 86400) if date else None
        recency = max(0.0, 3.0 - age * 0.4) if age is not None else 0.0
        score = keyword_score + recency - (2 if status == "read" else 0)
        stream = next(
            (
                name
                for name in ("core", "rocket-twin", "spatial")
                if name in enabled_streams and any(t != "custom interest" and topic_stream(t) == name for t in matched_topics)
            ),
            "custom" if matches else "exploration",
        )
        reasons = (
            [f"Matches {', '.join(matches[:5])}."]
            if matches
            else ["Exploration: no direct declared-interest match."]
        )
        if question_matches:
            reasons.append(f"Also shares question terms: {', '.join(question_matches[:4])}.")
        if status == "read":
            reasons.append("Already marked read; ranked lower.")
        if date is None:
            reasons.append("Publication/update date unknown; no recency bonus.")
        ranked.append(
            {
                **item,
                "reasons": reasons,
                "stream": stream,
                "minutes": 5,
                "relevance": {
                    "score": round(score, 3),
                    "keyword_score": keyword_score,
                    "recency": round(recency, 3),
                    "matched_terms": matches,
                    "matched_topics": matched_topics,
                    "question_terms": question_matches,
                    "policy_version": POLICY_VERSION,
                    "baseline": mode,
                },
            }
        )
    if mode == "chronological":
        ranked.sort(key=_chronological_key)
    elif mode == "keyword":
        ranked.sort(key=lambda item: (-item["relevance"]["keyword_score"], str(item["work_id"])))
    else:
        ranked.sort(key=lambda item: (-item["relevance"]["score"], str(item["work_id"])))
    return ranked


def choose_edition(
    items: Sequence[Mapping[str, Any]], minutes: int, *, exploration: float = 0.15
) -> list[dict[str, Any]]:
    """Five-minute slots; exploration never exceeds the saved final-count cap."""
    return select_edition(items, minutes, exploration=exploration)[0]


def select_edition(items: Sequence[Mapping[str, Any]], minutes: int, *, exploration: float = 0.15) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Largest feasible finite edition, rounding exploration down on FINAL count.

    Three slots cannot contain a whole exploratory item below a 30% cap. Nine
    slots permit one at 15% or two at 30%. Sparse direct matches shorten the
    edition; unrelated items never fill space by exceeding the percentage.
    """
    if minutes not in {5, 15, 45} or not 0 <= exploration <= 0.3:
        raise ValueError("invalid_edition_bounds")
    slots = minutes // 5
    direct = [dict(item) for item in items if item.get("relevance", {}).get("matched_terms")]
    adjacent = [dict(item) for item in items if not item.get("relevance", {}).get("matched_terms")]
    def budget(count: int) -> int:
        return int((Decimal(count) * Decimal(str(exploration))).to_integral_value(rounding=ROUND_FLOOR))
    count = min(slots, len(direct) + len(adjacent))
    while count and max(0, count - len(direct)) > min(len(adjacent), budget(count)):
        count -= 1
    exploratory = min(len(adjacent), budget(count))
    result = direct[:count - exploratory] + adjacent[:exploratory]
    allocation = {"minutes": minutes, "slots": slots, "requested_fraction": exploration,
                  "planned_max_exploration_slots": budget(slots), "max_exploration_slots": budget(count),
                  "actual_exploration_slots": exploratory, "actual_items": len(result),
                  "actual_fraction": exploratory / len(result) if result else None,
                  "unused_slots": slots - len(result), "rounding": "floor_final_count"}
    return result, allocation


def comparison_sample(
    items: Sequence[Mapping[str, Any]], profile: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Same-candidate ranking mechanics; usefulness labels await the owner."""
    return {
        "policy_version": POLICY_VERSION,
        "candidate_count": len(items),
        "rankings": {
            mode: [item["work_id"] for item in rank_items(items, profile, now=now, mode=mode)]
            for mode in ("chronological", "keyword", "relevance")
        },
        "labels": [{"work_id": item["work_id"], "useful": None, "reason": None} for item in items],
        "status": "awaiting_owner_labels",
    }
