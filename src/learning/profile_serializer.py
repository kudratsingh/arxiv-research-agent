"""Render a learner profile into a prompt without lying about it.

Two rules govern this module, and both are enforced at runtime rather
than documented and hoped for:

1. **No prompt ever presents an inferred skill as fact** (01 §1.2).
   Every rendered claim carries its provenance marker inline
   (`[declared]` / `[assessed]` / `[inferred]`), inferred claims are
   confined to the `UNCONFIRMED_HEADING` block, and
   `render_profile_for_prompt` verifies its own output before
   returning — a marker outside its section raises `ProvenanceError`
   instead of reaching a model.
2. **Learner-authored free text is untrusted input.** `profile_note`
   and goal statements are wrapped by
   `src/security/prompt_isolation.py` under
   `settings.enable_prompt_isolation`, the same treatment prior-report
   context gets (ADR 0033), because profile text flows into prompts
   week after week and is the cross-turn injection shape ADR 0020's
   supervisor lesson warns about.

Control-plane fields — skill names, levels, sources, evidence refs,
goal ids, statuses — never need wrapping because the store refuses
anything that is not a slug or a controlled-vocabulary term
(`src/learning/profile_store.py`). Isolation therefore only has to
cover the two genuinely free-text fields, which is why the flag-off
path is still safe against a redirected control token: there is no
control token a learner can write into.

See ADR 0058.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from src.learning.profile_store import (
    LearnerProfile,
    ProvenanceError,
    SkillEntry,
    SkillSource,
)
from src.security.prompt_isolation import (
    LEARNER_TEXT_ISOLATION_INSTRUCTION,
    wrap_untrusted_learner_text,
)

PROFILE_OPEN_TAG: Final = "<learner_profile>"
PROFILE_CLOSE_TAG: Final = "</learner_profile>"

DECLARED_HEADING: Final = "Declared by the learner (they said this):"
ASSESSED_HEADING: Final = (
    "Assessed (an assessment event backs each of these; the evidence id "
    "is on the line):"
)
UNCONFIRMED_HEADING: Final = (
    "Unconfirmed impressions (guesses inferred from behaviour — NOT "
    "facts; do not state them back to the learner as established, and "
    "do not change the plan on them):"
)
NOTE_HEADING: Final = "The learner's own words about themselves:"
GOALS_HEADING: Final = "Goals the learner set:"

EMPTY_PROFILE_TEXT: Final = (
    "The learner has not written a profile yet. Nothing is known about "
    "them; ask rather than assume."
)

# The inline provenance marker for each source. These strings are the
# mechanism the runtime check keys on, so they must be unique and must
# not be producible by learner text — `_scrub_markers` guarantees the
# second half.
PROVENANCE_MARKERS: Final[dict[SkillSource, str]] = {
    "declared": "[declared]",
    "assessed": "[assessed]",
    "inferred": "[inferred]",
}

# Any casing of a marker, so `[Inferred]` cannot slip through the
# scrub the way a plain string replace would let it.
_MARKER_RE: Final = re.compile(
    r"\[(" + "|".join(m.strip("[]") for m in PROVENANCE_MARKERS.values()) + r")\]",
    re.IGNORECASE,
)

_HEADINGS_BY_SOURCE: Final[dict[SkillSource, str]] = {
    "declared": DECLARED_HEADING,
    "assessed": ASSESSED_HEADING,
    "inferred": UNCONFIRMED_HEADING,
}

# Rendering order. `inferred` is last on purpose: the model reads the
# grounded claims first, and the least reliable block is the one
# closest to the instruction that follows.
_SECTION_ORDER: Final[tuple[SkillSource, ...]] = (
    "declared",
    "assessed",
    "inferred",
)


@dataclass(frozen=True, slots=True)
class ProfileSection:
    """One heading plus its rendered lines.

    Exposed so callers and tests can assert on structure instead of
    grepping a blob: the "inferred claims live only under the
    unconfirmed heading" property is a statement about sections.
    """

    heading: str
    lines: tuple[str, ...]
    source: SkillSource | None = None


def _scrub_markers(text: str) -> str:
    """Neutralise provenance markers a learner typed into free text.

    Without this, a learner who writes "[inferred]" in their profile
    note would trip the output check and break their own session — and
    with the isolation flag off they could otherwise plant a marker
    that reads as the system's own labelling. Replacing the brackets
    keeps the words and removes the forgery.
    """
    return _MARKER_RE.sub(lambda m: f"({m.group(1).lower()})", text)


def _render_free_text(text: str, *, isolate: bool) -> str:
    """Prepare learner-authored free text for a prompt."""
    scrubbed = _scrub_markers(" ".join(text.split()))
    if not isolate:
        return scrubbed
    return wrap_untrusted_learner_text(scrubbed)


def _skill_line(entry: SkillEntry) -> str:
    """One claim, provenance first and evidence attached.

    `declared` carries no confidence number: printing "confidence 1.0"
    next to something a person told you invites the model to reason
    about it as a measurement. Non-declared claims print both the
    number and the evidence id, because that pair is what makes them
    checkable.
    """
    marker = PROVENANCE_MARKERS[entry.source]
    if entry.source == "declared":
        return f"- {entry.skill}: {entry.level} {marker}"
    return (
        f"- {entry.skill}: {entry.level} {marker} "
        f"(confidence {entry.confidence:.2f}, evidence {entry.evidence_ref})"
    )


def profile_sections(
    profile: LearnerProfile, *, isolate: bool
) -> tuple[ProfileSection, ...]:
    """Break a profile into the sections the prompt renders.

    Args:
        profile: The record to render.
        isolate: Whether learner-authored free text is tag-wrapped.

    Returns:
        Sections in prompt order. Empty sections are dropped, so a
        learner with no inferred claims produces no "unconfirmed
        impressions" heading at all.
    """
    sections: list[ProfileSection] = []

    facts: list[str] = []
    if profile.academic_level:
        facts.append(f"- academic level: {profile.academic_level} [declared]")
    if profile.time_budget_min_per_day:
        facts.append(
            f"- time budget: {profile.time_budget_min_per_day} min/day "
            "[declared]"
        )
    declared_skills = profile.skills_by_source("declared")
    facts.extend(_skill_line(entry) for entry in declared_skills)
    if facts:
        sections.append(
            ProfileSection(
                heading=DECLARED_HEADING,
                lines=tuple(facts),
                source="declared",
            )
        )

    if profile.goals:
        goal_lines = tuple(
            f"- [{goal.goal_id}] {goal.status}, priority {goal.priority}"
            + (f", target {goal.target_date}" if goal.target_date else "")
            + ": "
            + _render_free_text(goal.statement, isolate=isolate)
            for goal in sorted(
                profile.goals, key=lambda g: (g.priority, g.goal_id)
            )
        )
        sections.append(
            ProfileSection(heading=GOALS_HEADING, lines=goal_lines)
        )

    for source in _SECTION_ORDER:
        if source == "declared":
            # Already rendered above, beside the declared facts.
            continue
        entries = profile.skills_by_source(source)
        if not entries:
            continue
        sections.append(
            ProfileSection(
                heading=_HEADINGS_BY_SOURCE[source],
                lines=tuple(_skill_line(entry) for entry in entries),
                source=source,
            )
        )

    if profile.profile_note:
        sections.append(
            ProfileSection(
                heading=NOTE_HEADING,
                lines=(_render_free_text(profile.profile_note, isolate=isolate),),
            )
        )

    return tuple(sections)


def render_profile_for_prompt(
    profile: LearnerProfile | None, *, isolate: bool | None = None
) -> str:
    """Render the profile block a tutor prompt embeds.

    Args:
        profile: The learner's record, or `None` for a learner who has
            not written one.
        isolate: Override for `settings.enable_prompt_isolation`.
            `None` (the default) reads the flag, matching 01 §1.4.

    Returns:
        The prompt block, tag-delimited so a caller can splice it into
        a larger message unambiguously.

    Raises:
        ProvenanceError: If the rendered text would place an inferred
            claim outside the unconfirmed-impressions block. This is a
            self-check on the module's own output — it should be
            unreachable, and it is asserted by a named test precisely
            so that staying unreachable is not an assumption.
    """
    if isolate is None:
        from src.config import settings

        isolate = settings.enable_prompt_isolation

    if profile is None:
        body = EMPTY_PROFILE_TEXT
    else:
        sections = profile_sections(profile, isolate=isolate)
        if not sections:
            body = EMPTY_PROFILE_TEXT
        else:
            body = "\n\n".join(
                "\n".join((section.heading, *section.lines))
                for section in sections
            )

    rendered = f"{PROFILE_OPEN_TAG}\n{body}\n{PROFILE_CLOSE_TAG}"
    _verify_no_inferred_as_fact(rendered, profile)
    return rendered


def _verify_no_inferred_as_fact(
    rendered: str, profile: LearnerProfile | None
) -> None:
    """Assert every `[inferred]` marker sits under the guess heading.

    Cheap (profiles are capped at `MAX_SKILL_ENTRIES` claims) and it
    turns 01 §1.2's rule from a convention into a property the process
    cannot violate: if a future edit moves an inferred claim into the
    declared block, the render raises rather than the model being
    told a guess is a fact.
    """
    marker = PROVENANCE_MARKERS["inferred"]
    expected = (
        len(profile.skills_by_source("inferred")) if profile is not None else 0
    )
    if rendered.count(marker) != expected:
        raise ProvenanceError(
            f"profile render carries {rendered.count(marker)} inferred "
            f"markers for {expected} inferred claims"
        )
    if expected == 0:
        return

    heading_at = rendered.find(UNCONFIRMED_HEADING)
    if heading_at < 0:
        raise ProvenanceError(
            "profile render carries inferred claims without the "
            "unconfirmed-impressions heading"
        )
    # The unconfirmed block runs from its heading to the next blank
    # line separating sections (or to the closing tag).
    block_end = rendered.find("\n\n", heading_at)
    if block_end < 0:
        block_end = rendered.rfind(PROFILE_CLOSE_TAG)
    block = rendered[heading_at:block_end]
    if block.count(marker) != expected:
        raise ProvenanceError(
            "an inferred claim was rendered outside the "
            "unconfirmed-impressions block"
        )


def profile_isolation_instruction(*, isolate: bool | None = None) -> str:
    """System-prompt clause naming the learner-text boundary.

    Returns the empty string when isolation is off, so a caller can
    unconditionally concatenate it (the reader does the same with its
    own instruction).
    """
    if isolate is None:
        from src.config import settings

        isolate = settings.enable_prompt_isolation
    return LEARNER_TEXT_ISOLATION_INSTRUCTION if isolate else ""


__all__ = [
    "ASSESSED_HEADING",
    "DECLARED_HEADING",
    "EMPTY_PROFILE_TEXT",
    "GOALS_HEADING",
    "NOTE_HEADING",
    "PROFILE_CLOSE_TAG",
    "PROFILE_OPEN_TAG",
    "PROVENANCE_MARKERS",
    "UNCONFIRMED_HEADING",
    "ProfileSection",
    "profile_isolation_instruction",
    "profile_sections",
    "render_profile_for_prompt",
]
