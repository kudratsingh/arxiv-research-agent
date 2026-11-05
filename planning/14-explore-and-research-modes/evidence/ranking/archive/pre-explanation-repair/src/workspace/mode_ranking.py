"""Predeclared, model-free Learn/Research ordering over an already visible pool.

The caller owns source/access/date/status filters and owner visibility. This
module preserves legacy exclusions/hidden-state handling, never fetches records,
and never treats a lexical score as factual support or a personal judgment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from src.workspace.ranking import _tokens, rank_items, select_edition

MODE_POLICY_VERSION = "workspace-modes-lexical-v1"


def known_mode_date(item: Mapping[str, Any]) -> datetime | None:
    """Publication/update only; neither announcement nor acquisition is inferred.

    Keep legacy update-before-publication precedence and reject naive/invalid
    values. An invalid supplied update is not silently replaced by another date.
    """
    raw = item.get("updated_at") or item.get("published_at")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value.astimezone(UTC) if value.tzinfo is not None else None


def _mode(product_mode: str) -> None:
    if product_mode not in {"learn", "research"}:
        raise ValueError("unknown_product_mode")


def _project_terms(project: Mapping[str, Any] | None) -> tuple[set[str], set[str]]:
    if project is None or not isinstance(project.get("question"), str) or not project["question"].strip():
        raise ValueError("research_project_question_required")
    scope = project.get("scope", "")
    if not isinstance(scope, str):
        raise ValueError("project_scope_must_be_text")
    return _tokens(project["question"]), _tokens(scope)


def rank_mode_items(
    items: Sequence[Mapping[str, Any]],
    profile: Mapping[str, Any],
    *,
    product_mode: str = "learn",
    project: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    include_hidden: bool = False,
) -> list[dict[str, Any]]:
    """Attach legacy receipts plus exact predeclared mode components and reasons.

    Research receives ProjectData, not its revision envelope. Existing question
    spellings are disabled in the profile arm for both modes. Input dictionaries
    and missing dates are preserved, including announcement metadata that is
    deliberately ineligible for this policy's freshness score.
    """
    _mode(product_mode)
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("timezone_required")
    question, scope = _project_terms(project) if product_mode == "research" else (set(), set())
    declared_profile = {**profile, "research_question": "", "researchQuestion": ""}
    originals: dict[str, Mapping[str, Any]] = {}
    for item in items:
        originals.setdefault(str(item["work_id"]), item)
    # Reuse authored terms, hidden-state checks, exclusions and score rounding.
    # Only the legacy announced_at fallback is disabled for policy v1.
    declared = rank_items(
        [{**item, "announced_at": None} for item in items], declared_profile,
        now=current, include_hidden=include_hidden,
    )
    result = []
    for item in declared:
        original = originals[str(item["work_id"])]
        if "announced_at" in original:
            item["announced_at"] = original["announced_at"]
        else:
            item.pop("announced_at", None)
        title = _tokens(str(item.get("title", "")))
        abstract = _tokens(str(item.get("abstract", "")))
        qt, qa = sorted(question & title), sorted(question & abstract)
        st, sa = sorted(scope & title), sorted(scope & abstract)
        q, s = 3 * len(qt) + len(qa), 3 * len(st) + len(sa)
        p = item["relevance"]["keyword_score"]
        date = known_mode_date(item)
        eligible = product_mode == "learn" or q > 0 or s > 0
        if not eligible:
            continue
        normalized = min(1, p / 24)
        components = [int(q > 0), q, s, normalized, item["relevance"]["recency"]]
        item["mode_relevance"] = {
            "policy_version": MODE_POLICY_VERSION, "product_mode": product_mode,
            "eligible": eligible, "question_score": q, "scope_score": s,
            "profile_keyword_score": p, "bounded_profile_score": normalized,
            "question_tokens": sorted(question), "scope_tokens": sorted(scope),
            "question_title_matches": qt, "question_abstract_matches": qa,
            "scope_title_matches": st, "scope_abstract_matches": sa,
            "freshness": item["relevance"]["recency"],
            "known_date": date.isoformat() if date else None,
            "date_basis": ("updated_at" if item.get("updated_at") else "published_at") if date else None,
            "read_penalty": 2 if (item.get("reading") or {}).get("status") == "read" else 0,
            "sort_components": components if product_mode == "research" else [item["relevance"]["score"]],
        }
        if product_mode == "research":
            item["reasons"] = [
                reason if not reason.startswith("Exploration:") else
                "No declared-interest match; Research does not require profile overlap."
                for reason in item["reasons"]
            ]
            item["reasons"].append(
                f"Project question overlap {q}; scope overlap {s}. Scope is a relevance signal, not a hard filter."
            )
        item["reasons"].append("Lexical relevance is not factual support or owner usefulness.")
        result.append(item)
    if product_mode == "research":
        result.sort(key=lambda item: (
            *(-value for value in item["mode_relevance"]["sort_components"]), str(item["work_id"]),
        ))
    return result


def select_mode_edition(
    ranked: Sequence[Mapping[str, Any]],
    minutes: int,
    *,
    product_mode: str = "learn",
    exploration: float = 0.15,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Finite five-minute slots; Learn variety precedes the legacy cap allocator.

    Round-robin stream order is first appearance in the ranked direct list;
    within-stream rank order stays unchanged. Research has no exploration quota.
    """
    _mode(product_mode)
    if minutes not in {5, 15, 45} or not 0 <= exploration <= 0.3:
        raise ValueError("invalid_edition_bounds")
    if product_mode == "research":
        eligible = []
        for item in ranked:
            receipt = item.get("mode_relevance", {})
            if receipt.get("product_mode") != "research" or receipt.get("policy_version") != MODE_POLICY_VERSION:
                raise ValueError("research_mode_ranking_required")
            if receipt.get("eligible"):
                eligible.append(dict(item))
        result = eligible[:minutes // 5]
        return result, {
            "policy_version": MODE_POLICY_VERSION, "product_mode": product_mode,
            "minutes": minutes, "slots": minutes // 5, "actual_items": len(result),
            "unused_slots": minutes // 5 - len(result), "eligible_candidates": len(eligible),
            "requested_fraction": None, "max_exploration_slots": None,
            "planned_max_exploration_slots": None, "actual_exploration_slots": None,
            "actual_fraction": None, "rounding": "finite_question_scope_matches_no_exploration_quota",
        }
    groups: dict[str, list[dict[str, Any]]] = {}
    adjacent = []
    for item in ranked:
        value = dict(item)
        if item.get("relevance", {}).get("matched_terms"):
            groups.setdefault(str(item.get("stream", "custom")), []).append(value)
        else:
            adjacent.append(value)
    varied = [group[index] for index in range(max(map(len, groups.values()), default=0))
              for group in groups.values() if index < len(group)]
    result, allocation = select_edition([*varied, *adjacent], minutes, exploration=exploration)
    return result, {**allocation, "policy_version": MODE_POLICY_VERSION,
                    "product_mode": product_mode, "direct_stream_order": list(groups),
                    "variety": "stable_first_occurrence_stream_round_robin"}
