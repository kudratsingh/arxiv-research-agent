"""Deterministic Phase W engagement reporting (WO-W18).

The metric definition is carried from SR-10 without reinterpretation:
"do invited users return in week 2 without being nudged — a 7-day-return
proxy against 00 §6.1's >=40% target". The observation window is 14 UTC
calendar days. A return is a ``session_completed`` event on day 7 or later
after that principal's first completed session. Principals who have not yet
had seven observable days are reported as immature and excluded from the
return-rate denominator; they are never counted as failures early.

The report is a pure fold over progress events and persisted job accounting.
It contains no app-open, time-in-app, notification, or mastery fields. Phase W
has no notification channel, so the absence of nudging is structural.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

from src.api.jobs import Job
from src.learning.progress_store import ProgressEvent

WINDOW_DAYS = 14
RETURN_AFTER_DAYS = 7
SESSION_EVIDENCE_PREFIX = "session:"


@dataclass(frozen=True)
class DailySessions:
    """Completed sessions for one principal on one UTC day."""

    principal_key_id: str
    day: str
    completed_sessions: int
    event_ids: tuple[str, ...]


@dataclass(frozen=True)
class PrincipalReturn:
    """One principal's auditable 7-day-return outcome."""

    principal_key_id: str
    first_session_day: str
    observable_days: int
    returned_7d: bool | None
    return_day: str | None
    session_event_ids: tuple[str, ...]


@dataclass(frozen=True)
class SessionCost:
    """Persisted cost joined to one completed guided-read session."""

    principal_key_id: str
    session_id: str
    event_id: str
    cost_usd: float | None


@dataclass(frozen=True)
class EngagementReport:
    """The complete, refused-metrics-safe report schema."""

    window_start: str
    window_end: str
    completed_sessions: int
    principals_observed: int
    principals_eligible_for_7d: int
    principals_returned_7d: int
    return_rate_7d: float | None
    daily_sessions: tuple[DailySessions, ...]
    principal_returns: tuple[PrincipalReturn, ...]
    session_costs: tuple[SessionCost, ...]
    guided_session_cost_usd: float
    guided_session_cost_observations: int
    guided_session_cost_missing: int
    research_cost_usd_excluded: float

    def to_json_dict(self) -> dict[str, Any]:
        # JSON round-trip turns the immutable tuple internals into the arrays
        # the CLI/report schema promises its consumers.
        return cast(dict[str, Any], json.loads(json.dumps(asdict(self))))


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"timestamp is not ISO-8601: {value!r}") from exc


def _window(start: str | date) -> tuple[date, date]:
    first = date.fromisoformat(start) if isinstance(start, str) else start
    return first, first + timedelta(days=WINDOW_DAYS - 1)


def _session_id(event: ProgressEvent) -> str | None:
    ref = event.evidence_ref or ""
    if not ref.startswith(SESSION_EVIDENCE_PREFIX):
        return None
    session_id = ref.removeprefix(SESSION_EVIDENCE_PREFIX).split("#", 1)[0].strip()
    return session_id or None


def compute_engagement(
    events: Sequence[ProgressEvent],
    jobs: Sequence[Job],
    *,
    window_start: str | date,
) -> EngagementReport:
    """Fold events and job costs into the Phase W 14-day report."""
    first_day, last_day = _window(window_start)
    sessions = sorted(
        (
            event
            for event in events
            if event.kind == "session_completed" and first_day <= _day(event.ts) <= last_day
        ),
        key=lambda event: (event.principal_key_id, event.ts, event.event_id),
    )

    grouped: dict[tuple[str, date], list[ProgressEvent]] = {}
    by_principal: dict[str, list[ProgressEvent]] = {}
    for event in sessions:
        day = _day(event.ts)
        grouped.setdefault((event.principal_key_id, day), []).append(event)
        by_principal.setdefault(event.principal_key_id, []).append(event)

    daily = tuple(
        DailySessions(
            principal_key_id=principal,
            day=day.isoformat(),
            completed_sessions=len(bucket),
            event_ids=tuple(event.event_id for event in bucket),
        )
        for (principal, day), bucket in sorted(grouped.items())
    )

    returns: list[PrincipalReturn] = []
    for principal, bucket in sorted(by_principal.items()):
        started = _day(bucket[0].ts)
        observable_days = (last_day - started).days + 1
        eligible = observable_days > RETURN_AFTER_DAYS
        return_event = next(
            (event for event in bucket[1:] if (_day(event.ts) - started).days >= RETURN_AFTER_DAYS),
            None,
        )
        returns.append(
            PrincipalReturn(
                principal_key_id=principal,
                first_session_day=started.isoformat(),
                observable_days=observable_days,
                returned_7d=(return_event is not None) if eligible else None,
                return_day=(
                    _day(return_event.ts).isoformat() if return_event is not None else None
                ),
                session_event_ids=tuple(event.event_id for event in bucket),
            )
        )

    job_by_id = {job.job_id: job for job in jobs}
    costs: list[SessionCost] = []
    seen_session_ids: set[str] = set()
    for event in sessions:
        session_id = _session_id(event)
        if session_id is None or session_id in seen_session_ids:
            continue
        seen_session_ids.add(session_id)
        job = job_by_id.get(session_id)
        cost = job.cost_usd if job is not None and job.kind == "session" else None
        costs.append(
            SessionCost(
                principal_key_id=event.principal_key_id,
                session_id=session_id,
                event_id=event.event_id,
                cost_usd=cost,
            )
        )

    observed_costs = [item.cost_usd for item in costs if item.cost_usd is not None]
    research_cost = sum(job.cost_usd or 0.0 for job in jobs if job.kind == "research")
    eligible_returns = [item for item in returns if item.returned_7d is not None]
    returned = sum(item.returned_7d is True for item in eligible_returns)
    return EngagementReport(
        window_start=first_day.isoformat(),
        window_end=last_day.isoformat(),
        completed_sessions=len(sessions),
        principals_observed=len(returns),
        principals_eligible_for_7d=len(eligible_returns),
        principals_returned_7d=returned,
        return_rate_7d=(returned / len(eligible_returns) if eligible_returns else None),
        daily_sessions=daily,
        principal_returns=tuple(returns),
        session_costs=tuple(costs),
        guided_session_cost_usd=round(sum(observed_costs), 6),
        guided_session_cost_observations=len(observed_costs),
        guided_session_cost_missing=sum(item.cost_usd is None for item in costs),
        research_cost_usd_excluded=round(research_cost, 6),
    )


def render_markdown(report: EngagementReport) -> str:
    """Render an auditable Gate W2 markdown report."""
    rate = "not yet measurable" if report.return_rate_7d is None else f"{report.return_rate_7d:.1%}"
    lines = [
        "# Phase W engagement report",
        "",
        f"Observation window: **{report.window_start} through {report.window_end}** "
        f"({WINDOW_DAYS} UTC calendar days).",
        "",
        "> 7-day-return proxy: a completed session on day 7 or later after "
        "the principal's first completed session, without nudging.",
        "",
        f"- Completed sessions: {report.completed_sessions}",
        f"- Principals observed: {report.principals_observed}",
        f"- Eligible for a 7-day outcome: {report.principals_eligible_for_7d}",
        f"- Returned on day 7 or later: {report.principals_returned_7d}",
        f"- 7-day return: **{rate}**",
        "",
        "## Principal outcomes",
        "",
        "| Principal | First session | Observable days | Outcome | Return day | Evidence events |",
        "|---|---:|---:|---|---:|---|",
    ]
    for outcome_item in report.principal_returns:
        outcome = (
            "immature"
            if outcome_item.returned_7d is None
            else "returned"
            if outcome_item.returned_7d
            else "did not return"
        )
        lines.append(
            f"| {outcome_item.principal_key_id} | {outcome_item.first_session_day} | "
            f"{outcome_item.observable_days} | {outcome} | "
            f"{outcome_item.return_day or '-'} | "
            f"{', '.join(outcome_item.session_event_ids)} |"
        )

    lines.extend(
        [
            "",
            "## Sessions per UTC day",
            "",
            "| Principal | Day | Completed sessions | Evidence events |",
            "|---|---:|---:|---|",
        ]
    )
    for daily_item in report.daily_sessions:
        lines.append(
            f"| {daily_item.principal_key_id} | {daily_item.day} | "
            f"{daily_item.completed_sessions} | {', '.join(daily_item.event_ids)} |"
        )

    lines.extend(
        [
            "",
            "## Persisted cost accounting",
            "",
            f"Guided-session spend: **${report.guided_session_cost_usd:.4f}** "
            f"across {report.guided_session_cost_observations} costed sessions "
            f"({report.guided_session_cost_missing} missing cost records).",
            f"Research-run spend excluded from that figure: "
            f"**${report.research_cost_usd_excluded:.4f}**.",
            "",
            "| Principal | Session | Cost (USD) | Completion event |",
            "|---|---|---:|---|",
        ]
    )
    for cost_item in report.session_costs:
        rendered_cost = "missing" if cost_item.cost_usd is None else f"{cost_item.cost_usd:.4f}"
        lines.append(
            f"| {cost_item.principal_key_id} | {cost_item.session_id} | "
            f"{rendered_cost} | {cost_item.event_id} |"
        )
    lines.extend(
        [
            "",
            "Small-N warning: with at most five pilots, one person moves the rate "
            "by at least 20 percentage points. Read the denominator and evidence "
            "rows; do not treat this proxy as a population estimate.",
            "",
        ]
    )
    return "\n".join(lines)


def _job_from_mapping(raw: Mapping[str, Any]) -> Job:
    kind = raw.get("kind")
    if kind not in {"research", "session"}:
        raise ValueError(f"job {raw.get('job_id')!r} has invalid kind {kind!r}")
    cost = raw.get("cost_usd")
    if cost is not None and (
        not isinstance(cost, (int, float)) or isinstance(cost, bool) or cost < 0
    ):
        raise ValueError(f"job {raw.get('job_id')!r} has invalid cost_usd")
    return Job(
        job_id=str(raw["job_id"]),
        query=str(raw.get("query") or "engagement import"),
        kind=kind,
        principal_key_id=(
            str(raw["principal_key_id"]) if raw.get("principal_key_id") is not None else None
        ),
        cost_usd=float(cost) if cost is not None else None,
    )


def _load_inputs(path: Path, key: str) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(values, list) or any(not isinstance(v, dict) for v in values):
        raise ValueError(f"{path}: expected object with a {key!r} list")
    return values


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the Phase W engagement report")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    events = [ProgressEvent.from_json_dict(raw) for raw in _load_inputs(args.events, "events")]
    jobs = [_job_from_mapping(raw) for raw in _load_inputs(args.jobs, "jobs")]
    rendered = render_markdown(compute_engagement(events, jobs, window_start=args.window_start))
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    raise SystemExit(main())
