# Experience and design

## Experience thesis

The home screen answers three questions: what changed, why it matters to my
research, and what I should do with it. The reader keeps the original source,
the agent's explanation and the user's own thinking distinguishable. The
daily briefing and guided deep dive are the first complete experience.

Evolve the Evidence Workbench's existing components, self-hosted fonts and
tokens. The proposal is a calm research instrument with dense, readable
information and generous reading space. Keep the prompt available within a
task; make the daily research state the home page.

## Navigation and routes

These are proposed browser routes; backend names are in [04](04-architecture-and-technology.md).
Existing research and guided-read routes remain reachable during migration.

| Destination | Route proposal | Main action |
|---|---|---|
| Today | `/today` | Review today's changes; choose a deep dive |
| Radar | `/radar` | Browse/search the incoming stream and filters |
| Library | `/library` | Resume saved material, notes and reading queues |
| Source and reader | `/library/items/[id]` | Read, inspect evidence, annotate and ask |
| Research projects | `/projects`, `/projects/[id]` | Follow a question, compare sources and plan work |
| Interests | `/interests` | Search and tune topics, lenses, exclusions and coverage |
| Preferences | `/settings` | Schedule, source connections, local data and budgets |

The eventual root route redirects to Today after setup. Do not silently remove
the existing query workflow: provide “Research a question” in the header and
the command menu. The implementation ADR chooses final route names once
existing route collisions and navigation contracts are checked.

## Onboarding that can be revised

1. Choose a starting lens: ML student/researcher, a custom field, or a question.
2. Search broad disciplines and drill into study areas. Suggest a rich ML
   preset, but keep all choices editable. Allow a pasted paper/DOI/arXiv ID and
   a free-text research goal. Validate external addresses server-side.
3. Choose depth and reading time; add exclusions. Skill level is per topic.
4. Show coverage before saving: live connector available, metadata only,
   manually configured source, or not connected. Broad selection never
   implies a global web search is running.
5. Choose local check time and IANA timezone, then preview a sample briefing.
   State that the local process must run; catch-up happens when it resumes.
6. Enter the workspace. Source credentials and paid generation are optional
   later settings; the no-key experience remains usable.

Do not force the user through the entire classification tree or ask for a
comprehensive academic biography. Save partial progress and allow skip/edit.
Proposed ML preset: foundation models, reasoning, retrieval, agents, evaluation,
efficient training/inference, interpretability, robustness and ML systems.

## Today

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Research workspace          Search anything…       Research a question │
├───────────────┬─────────────────────────────────────┬───────────────────┤
│ Today         │ Monday briefing                    │ Your research     │
│ Radar         │ Since last visit · 15 min           │ Retrieval quality │
│ Library       │ Checked 5 of 6 sources · details    │ Next: inspect     │
│ Projects      │                                     │ baseline settings │
│               │ THREE CHANGES TO CONSIDER           │                   │
│ Interests     │ [Paper] Result under a new setting  │ Continue reading  │
│ Settings      │ Why matched · evidence scope        │ section + scroll  │
│               │ Changed since the saved version     │                   │
│               │ [Read] [Save] [Less like this]       │ One open question │
│               │                                     │                   │
│               │ From your topics     Adjacent work  │ Schedule / status │
│               │ Finite grouped stream; no repeats   │                   │
└───────────────┴─────────────────────────────────────┴───────────────────┘
```

Source status is textual and actionable. “No new matching items” is different
from “One source could not be checked.” A refresh keeps the existing briefing
visible, with a discreet progress indicator. Dates have a local display and an
absolute timestamp on demand. A delayed paper is labelled newly discovered,
not newly published. Updated content must not jump the current reading focus.

Each cluster shows title, source kind, source/publication date, why matched,
what changed, access scope and actions. A generated blurb is visually labelled
as generated. A source-provided abstract is labelled “Source abstract.” Group
a release article and its paper; keep two distinct papers in a shared topic
as distinct works. Show “already in your library” and read state.

Reading-time controls reduce the selected briefing, not the underlying saved
inbox. “Done for today” closes the finite edition without deleting unread
items. Catch-up offers an interval summary plus a manageable set, not seven
separate digests after a missed week. There is an explicit route to all items.

## Guided deep dive

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Today   Paper title     v2 · full text available      Save / Export   │
├────────────┬─────────────────────────────┬──────────────────────────────┤
│ Outline    │ Source text / PDF           │ Understand this work         │
│ Abstract   │                             │ Question + active scope      │
│ Method     │ selected passage            │ [Overview] [Assumptions]     │
│ Results    │ ▌highlight                  │ [Compare] [Build]            │
│ Limits     │                             │                              │
│ Notes      │ claim, table or equation    │ Explanation → source spans   │
│            │                             │ What is unknown              │
│            │                             │ [Pin question] [Save note]   │
│            │                             │ Ask about this selection…    │
└────────────┴─────────────────────────────┴──────────────────────────────┘
```

Initial reader supports source metadata/abstract, linked original, notes and
questions. Full-text content and generated answers appear only when available
and authorized. Reuse the existing session/research jobs for bounded work;
verify the fit rather than mislabelling the old fixture briefing as a paper.
The first local source pane uses safe extracted text with the original-source
link. Passage-based generated assistance requires retained page/section/offset
anchors. Inline PDF rendering and synchronized PDF highlights are a later
bounded UI decision; the wireframe's PDF label does not commit a renderer.

Every generated answer records its scope: selected passage, this source,
selected comparison set or an explicitly requested external search. Asking
“Is this true?” should expose evidence and limitations. It should not silently
launch an unbounded web investigation. A missing method section leads to
“The available abstract does not establish this,” with an option to open the
source. Retrieval snippets do not count as reading a full document.

Offer levels: quick intuition, technical explanation, and derivation/prerequisite
help. “Explain this equation” identifies the actual equation, defines symbols,
states conditions and labels any illustrative derivation. “Check my
understanding” reuses guided-reading assessment with its honest ungraded status;
it does not claim measured mastery. User edits are never overwritten by a
regenerated summary.

### The signature interaction

A **question thread** connects the moment in the briefing to its sources,
assumptions, the user's question and a next experiment. Display it as a compact
vertical trace with meaningful labels: “Question”, “Evidence”, “Assumption”,
“Test next”. Every link navigates to its real object. The trace is populated
only by recorded activity. This carries the existing checkpoint-spine idea
into personal research continuity without inventing a history.

## Radar, interests and relationships

Radar offers list-first research filters: topic, lens, source kind, publication
and discovery windows, already read, access and saved status. Preserve filter
URLs and back navigation. A “Why shown?” disclosure lists the actual matching
signals. Unknown dates remain unknown. Excluded topics and muted sources are
visible and reversible; a deliberate “search outside my interests” overrides
them for that search only.

The interest picker uses searchable hierarchy plus selected chips. Study
levels and goals are facets, not sibling academic fields. A topic may map to
several taxonomies or source categories. Put coverage beside the topic and
offer manual source configuration if needed. A custom topic is valid even if
no current official category maps exactly.

Relationships begin as readable lists or tables: “cites”, “same problem”,
“comparison suggested”, “reported extension” and “conflicting evidence under
these settings”. Each has its origin and supporting span. A later graph is an
optional view over these records; it must add useful navigation beyond the
list and have a keyboard-accessible alternative.

## Projects and durable memory

A project contains a research question, short editable context, chosen sources,
notes, assumptions, hypotheses and experiment proposals/results. User-authored
content, quoted evidence and generated content have distinct authorship. The
project's weekly review shows what changed, unresolved questions and next
actions. Save a reproducible synthesis snapshot with input source versions;
do not overwrite earlier conclusions when inputs change.

Library entries support save/read/snooze/archive, collection membership,
annotations, last-read anchor and portable export. Archive removes an item
from the current work queue without erasing notes. Source deletion, source
removal, local content deletion and removal of a personal note are different
actions with concrete descriptions.

## Visual system and responsive behavior

Use the existing cool blue-grey canvas, white surfaces, blue actions and teal
research-context accent. Proposed palette is the existing token system:
canvas `#F3F7F8`, surface `#FFFFFF`, ink `#172B31`, primary `#275DAD`,
signature `#167D7F`, review `#C47A17`. These are references for design; code
colours still live only in the repository's canonical token files and themes.
Preserve Atkinson Hyperlegible Next for interface/body, Literata for reading,
IBM Plex Mono for compact dates/data. Do not add a hosted font or new icon
system for this transformation.

Prefer information rows with deliberate spacing over walls of identical cards.
Paper titles and research questions lead; metrics are subordinate. Group with
source/context labels, not decorative numbers. Colour never carries evidence
status by itself. Keep the existing dark-theme contract. Minimal motion is
reserved for an explicit panel transition or progress; respect reduced motion.

At wide widths the source and reading assistance can coexist; either panel can
expand. At tablet widths use two columns and a collapsible outline. At phone
widths use Source / Understand / Notes tabs, retaining selection and scroll
when switching. The brief works at 390 px, keyboard navigation reaches every
action, and a user can complete the daily loop without dragging a graph.

## State and acceptance checklist

Include fixtures/stories for first use, no interests, no matching items,
some sources unavailable, all sources unavailable, stale cached edition,
local process resumed, generation disabled, cap reached, queued/running/
cancelled deep dive, abstract-only source, denied full text, parser failure,
contradictory sources, correction/retraction, missing date, user note edit,
source-version update and corrupted import. Keep saved notes usable through
source or model failures.

Before expanding screens, owner review should complete one coherent task:
select an ML lens, understand why a cluster appeared, read a cited passage,
pin a question, save a next action, and reopen at the same place. Assess the
real interaction at desktop and phone size, including a failed source. Apply
[WCAG 2.2](https://www.w3.org/TR/WCAG22/) alongside existing axe, focus,
screen-reader and route-budget practices; automated checks do not replace the
human reading review.
