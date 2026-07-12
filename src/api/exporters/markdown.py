"""Markdown exporter — prepends a metadata header block, then the report body verbatim."""

from __future__ import annotations

from datetime import UTC, datetime

from src.api.jobs import Job


def render_markdown(job: Job) -> bytes:
    """Return the job's report as Markdown bytes.

    Adds a small metadata header (query, run date, cost, iterations,
    quality score) above the body so a downloaded file is
    self-describing even outside the API context. Preserves the
    synthesizer's markdown verbatim.
    """
    header = _header(job)
    body = job.result or "_(no report body)_"
    return f"{header}\n\n{body}\n".encode()


def _header(job: Job) -> str:
    lines: list[str] = []
    lines.append(f"# Research briefing — {job.job_id}")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Query | {_escape_md(job.query)} |")
    lines.append(
        "| Completed | "
        f"{datetime.fromtimestamp(job.completed_at or 0, tz=UTC).isoformat()} |"
        if job.completed_at is not None
        else "| Completed | (still running) |"
    )
    if job.iterations is not None:
        lines.append(f"| Iterations | {job.iterations} |")
    if job.quality_score is not None:
        lines.append(f"| Quality | {job.quality_score:.2f} |")
    if job.cost_usd is not None:
        lines.append(f"| Cost | ${job.cost_usd:.4f} |")
    elapsed = job.elapsed_sec()
    if elapsed is not None:
        lines.append(f"| Elapsed | {elapsed:.1f}s |")
    return "\n".join(lines)


def _escape_md(text: str) -> str:
    """Escape the `|` character so it doesn't split table cells."""
    return text.replace("|", "\\|").replace("\n", " ").strip()
