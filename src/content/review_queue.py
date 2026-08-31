"""Render the owner's review queue from a path manifest.

`02` §3.1's third step — "**Human approves** — a review queue ... showing
proposal + rubric verdict" — is a UI in Phase L. In Phase W it is a
markdown file next to the manifest, regenerated from it, because the
reviewer is one person working through a list and a file is the cheapest
thing that cannot drift from the content it describes.

The queue's job is to make the ~10–20 hours `02` §5 budgets **startable**.
It does that by splitting the work in two:

- **Curation review** — is this the right paper, in the right place, with
  an honest rationale and a lawful link? Every entry has one. Nothing
  blocks it; it can start the hour this merges.
- **Briefing review** — is this companion accurate? Blocked on W-OD-2,
  because there is no briefing to review until the generation campaign
  runs.

The file is generated, never hand-edited: `--check` fails when the
committed copy has drifted from the manifest, the same drift discipline
`web/contract/openapi.json` uses.

    .venv/bin/python -m src.content.review_queue --check
    .venv/bin/python -m src.content.review_queue --write
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from src.content.loader import LoadedPath, content_root, load_content_root
from src.content.schema import ALL_RULES, ContentValidationError, Entry, PathManifest

#: The generated file's name inside a path directory.
REVIEW_QUEUE_FILENAME: Final = "REVIEW-QUEUE.md"

#: The command that regenerates it, quoted in the file's own header.
REGENERATE_COMMAND: Final = ".venv/bin/python -m src.content.review_queue --write"

#: What "approve this entry" actually asks a human to confirm. Machine
#: -checked facts are deliberately absent — the validator already refuses
#: a manifest that gets them wrong, and re-checking them by hand is how a
#: review queue becomes theatre.
CURATION_CHECKS: Final[tuple[str, ...]] = (
    "The paper belongs on this path at all.",
    "Its position is right: a reader arriving from the previous entry is "
    "ready for this one.",
    "The rationale is true, and is a reason rather than a description.",
    "The vocabulary list is what a reader must already hold — not a "
    "summary of the paper's contributions.",
    "The time estimate is honest for someone reading this for the first "
    "time.",
    "The attribution names the right people.",
)

BRIEFING_CHECKS: Final[tuple[str, ...]] = (
    "Every factual claim about the paper is correct.",
    "The 'read closely vs skim' guidance matches the paper's actual "
    "sections.",
    "The 'what superseded it' section is dated and is not overstated.",
    "Nothing is quoted that should be paraphrased, and every quote is "
    "attributed.",
    "The prose is worth a reader's time — this is the differentiator, "
    "and a mediocre briefing is worse than no path.",
)


@dataclass(frozen=True)
class QueueItem:
    """One thing the owner has to decide about."""

    position: int
    resource_id: str
    title: str
    url: str
    kind: str
    status: str
    rationale: str
    minutes_low: int
    minutes_high: int
    blocked_by: str | None
    note: str


@dataclass(frozen=True)
class ReviewQueue:
    """Everything awaiting the owner on one path."""

    path_id: str
    title: str
    manifest: PathManifest
    curation: tuple[QueueItem, ...]
    briefings: tuple[QueueItem, ...]

    @property
    def curation_hours(self) -> tuple[float, float]:
        return _hours(self.curation)

    @property
    def briefing_hours(self) -> tuple[float, float]:
        return _hours(self.briefings)

    @property
    def total_hours(self) -> tuple[float, float]:
        low_a, high_a = self.curation_hours
        low_b, high_b = self.briefing_hours
        return (low_a + low_b, high_a + high_b)


def _hours(items: Sequence[QueueItem]) -> tuple[float, float]:
    low = sum(i.minutes_low for i in items) / 60
    high = sum(i.minutes_high for i in items) / 60
    return (round(low, 1), round(high, 1))


def _hours_text(bounds: tuple[float, float]) -> str:
    """`2.3 h` when the estimate is a point, `10–20 h` when it is a range."""
    low, high = bounds
    return f"{low:g} h" if low == high else f"{low:g}–{high:g} h"


def _briefing_note(path: LoadedPath, entry: Entry) -> str:
    if entry.briefing_file is None:
        return "no briefing companion planned"
    if entry.resource_id in path.briefings:
        return f"draft present: `{entry.briefing_file}`"
    return f"not generated yet: `{entry.briefing_file}`"


def build_queue(path: LoadedPath) -> ReviewQueue:
    """Derive the review queue for one loaded path.

    Args:
        path: A validated path.

    Returns:
        The queue: curation items for every entry still `proposed`, and
        briefing items for every paper whose companion is not yet
        reviewed.
    """
    manifest = path.manifest
    per_entry = manifest.review.curation_minutes_per_entry
    generation = manifest.generation
    low_h, high_h = (
        generation.est_review_hours_per_briefing if generation else (1.0, 2.0)
    )
    blocked_by = generation.decision if generation else None

    curation: list[QueueItem] = []
    briefings: list[QueueItem] = []
    for entry in manifest.entries:
        if entry.status == "proposed":
            curation.append(
                QueueItem(
                    position=entry.position,
                    resource_id=entry.resource_id,
                    title=entry.title,
                    url=entry.canonical_url,
                    kind=entry.kind,
                    status=entry.status,
                    rationale=entry.rationale,
                    minutes_low=per_entry,
                    minutes_high=per_entry,
                    blocked_by=None,
                    note=entry.sequencing.note or "",
                )
            )
        needs_briefing_review = (
            entry.kind == "paper"
            and entry.briefing_file is not None
            and not entry.reviewed_by
        )
        if needs_briefing_review:
            briefings.append(
                QueueItem(
                    position=entry.position,
                    resource_id=entry.resource_id,
                    title=entry.title,
                    url=entry.canonical_url,
                    kind=entry.kind,
                    status=entry.status,
                    rationale=entry.rationale,
                    minutes_low=int(low_h * 60),
                    minutes_high=int(high_h * 60),
                    blocked_by=blocked_by,
                    note=_briefing_note(path, entry),
                )
            )
    return ReviewQueue(
        path_id=manifest.path_id,
        title=manifest.title,
        manifest=manifest,
        curation=tuple(curation),
        briefings=tuple(briefings),
    )


def _short(title: str, limit: int = 58) -> str:
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def render_markdown(queue: ReviewQueue) -> str:
    """Render the queue as the committed `REVIEW-QUEUE.md`."""
    manifest = queue.manifest
    generation = manifest.generation
    lines: list[str] = []
    add = lines.append

    add(f"# Review queue — {queue.title}")
    add("")
    add(
        f"> **Generated file — do not edit by hand.** Regenerate with "
        f"`{REGENERATE_COMMAND}`."
    )
    add(
        f"> Source of truth: `content/paths/{queue.path_id}/path.json` "
        f"(version {manifest.version}, updated {manifest.updated_at})."
    )
    add("")
    add(
        "This is the human half of the vetting pipeline "
        "(`planning/07-learning-platform/02-CONTENT.md` §3.1). Nothing on "
        "this path publishes until the reviewer named below moves it past "
        "`proposed`, and the loader refuses to serve anything that has not "
        "moved."
    )
    add("")
    add(f"**Reviewer:** {manifest.review.owner}")
    add(
        "**Owner decisions this path waits on:** "
        + ", ".join(f"`{d}`" for d in manifest.review.decisions)
    )
    add(f"**Path status:** `{manifest.status}`")
    add("")

    add("## The hours, split by what blocks them")
    add("")
    add("| Work | Items | Estimate | Blocked by |")
    add("|---|---|---|---|")
    add(
        f"| Curation review | {len(queue.curation)} | "
        f"{_hours_text(queue.curation_hours)} | — **can start now** |"
    )
    add(
        f"| Briefing review | {len(queue.briefings)} | "
        f"{_hours_text(queue.briefing_hours)} | "
        + (f"`{generation.decision}`" if generation else "—")
        + " |"
    )
    add(f"| **Total** | | **{_hours_text(queue.total_hours)}** | |")
    add("")
    add(
        "The briefing figure is `02` §5's 1–2 review-hours per briefing "
        "carried verbatim, not re-estimated. It is the long pole, and "
        "nobody should pretend otherwise."
    )
    add("")

    add("## 1. Curation review — available now, no spend")
    add("")
    if queue.curation:
        add("| # | Entry | Kind | Rationale as written |")
        add("|---|---|---|---|")
        for item in queue.curation:
            add(
                f"| {item.position} | [{_short(item.title)}]({item.url})"
                f"<br>`{item.resource_id}` | {item.kind} | {item.rationale} |"
            )
        add("")
        add("For each entry, confirm:")
        add("")
        for check in CURATION_CHECKS:
            add(f"- [ ] {check}")
        add("")
        add(
            "Then edit the manifest entry: set `status` to `approved`, and "
            "set `reviewed_by` and `reviewed_at`. To reject, set `status` "
            "to `rejected` and write `rejection_reason` — `02` §3.1 keeps "
            "rejects and their reasons as a calibration set, so a rejection "
            "is an edit, not a deletion."
        )
    else:
        add("Nothing proposed. Every entry has been through review.")
    add("")

    add("## 2. Briefing review — blocked")
    add("")
    if generation is not None:
        add(
            f"Blocked on **`{generation.decision}`**. Status: "
            f"`{generation.status}`."
        )
        add("")
        add(
            f"- Pipeline: {generation.pipeline}\n"
            f"- Ceiling: `${generation.max_budget_usd:.2f}` total, "
            f"~`${generation.est_cost_usd_per_briefing:.2f}` per briefing\n"
            f"- Command: `{generation.command}`"
        )
        add("")
        add(f"{generation.note}")
        add("")
    if queue.briefings:
        add("| # | Entry | Companion | Estimate |")
        add("|---|---|---|---|")
        for item in queue.briefings:
            add(
                f"| {item.position} | `{item.resource_id}` | {item.note} | "
                f"{_hours_text((item.minutes_low / 60, item.minutes_high / 60))} |"
            )
        add("")
        add("For each briefing, confirm:")
        add("")
        for check in BRIEFING_CHECKS:
            add(f"- [ ] {check}")
        add("")
        add(
            "Then set `reviewed_by` / `reviewed_at` in **both** the "
            "manifest entry and the briefing file's provenance header, and "
            "move the entry to `approved`. The loader refuses to start if "
            "the two disagree."
        )
    else:
        add("No briefing companions are awaiting review.")
    add("")

    add("## What you do not have to check")
    add("")
    add(
        "`src/content/schema.py` refuses to load a manifest that breaks any "
        "of these, so a loading path has already passed them:"
    )
    add("")
    for rule in ALL_RULES:
        add(f"- `{rule}`")
    add("")
    add(
        "In particular: every paper link is an arXiv abs page, no field "
        "exists that could hold full text or a PDF, abstracts cannot be "
        "stored without attribution, citation-ancestry claims carry a "
        "Semantic Scholar link-back, and nothing unreviewed can reach "
        "`approved`. Spend the review hours on judgement, not on "
        "re-checking the machine."
    )
    add("")
    return "\n".join(lines) + "\n"


def _queue_paths(root: Path) -> list[LoadedPath]:
    """Non-fixture paths, which are the only ones a human reviews."""
    return [p for p in load_content_root(root).values() if not p.manifest.fixture]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m src.content.review_queue",
        description="Generate the owner's review queue from a path manifest.",
    )
    parser.add_argument("--root", default=None, help="Content root.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--write", action="store_true", help="Write REVIEW-QUEUE.md files."
    )
    group.add_argument(
        "--check",
        action="store_true",
        help="Fail if a committed REVIEW-QUEUE.md has drifted.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else content_root()
    try:
        paths = _queue_paths(root)
    except ContentValidationError as exc:
        print(f"content validation failed: {exc}", file=sys.stderr)
        return 2

    drifted: list[str] = []
    for path in paths:
        rendered = render_markdown(build_queue(path))
        target = path.directory / REVIEW_QUEUE_FILENAME
        if args.write:
            target.write_text(rendered, encoding="utf-8")
            print(f"wrote {target}")
            continue
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != rendered:
            drifted.append(str(target))
    if drifted:
        print(
            "review queue is stale:\n  "
            + "\n  ".join(drifted)
            + f"\nregenerate with: {REGENERATE_COMMAND}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wiring
    raise SystemExit(main())
