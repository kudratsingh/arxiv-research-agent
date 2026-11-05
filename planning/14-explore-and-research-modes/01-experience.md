# Connected experience

## Navigation and layout

Keep the controller's large sidebar, one focused reading stage and compact
player. Put the visible **Explore & Learn / Research** switch near the top of
the sidebar and in a compact mobile heading control. It must be operable without
opening the drawer where required by the live browser contracts. Research adds
an active-project selector with question/scope context, not another permanent
sidebar. Keep Library, sources, coverage and operations shared.

Today and Radar reflect the chosen mode. Reader retains **Source / Understand /
Your notes** and adapts the available assistance, without duplicating forms.
Manual Source and notes always work while generation is disabled. No enabled
teaching button should merely return an invented answer or silent fixture.
Unavailable capabilities explain what is pending.

Proposed URL shape (not shipped): `mode=learn|research`, `project=<owned-id>` in
Research, plus existing focus/view/query/cursor/version/anchor context. Learning
threads have a stable id when saved. A URL selects existing owned context; it
does not create a project, mutate preferences or save an entry on page load.
Unknown mode values fall back visibly to learning. Unknown/unowned project ids
show unavailable context without leaking another principal's project.

## Journey A: daily Explore & Learn

1. Open Today with no research question. See a finite edition for the reading
   window, its actual source coverage and last successful checks.
2. Focus one paper. Inspect matching terms, variety/exploration allocation,
   publication-date uncertainty and available source scope.
3. Open its exact version in Reader, read retained text, save a question or a
   personal connection. Optional prerequisite vocabulary can be recorded manually.
4. Return to the same queue item. Resume later from Library or recent activity.
5. Use **Investigate this** only if the idea deserves a research project.

Foundational items are explicitly curated or identified by a declared rule;
old does not automatically mean foundational. Unknown publication dates get
no invented freshness. No general question is required to obtain candidates.

## Journey B: Research

1. Select/create a project with a question and optional scope/constraints.
2. Search and review question-specific candidates, including out-of-interest
   matches. Keep why-this-matched separate from whether the evidence supports
   an answer. Contradictory results stay discoverable.
3. Attach an exact source version and passage as evidence. Capture an observation,
   an assumption or hypothesis with its own type and provenance.
4. Compare methods with dataset, evaluation conditions and known limitations.
   Missing comparative evidence is an explicit gap, not a filled table cell.
5. Record a proposed experiment with baseline, variables, resources, metric and
   stopping condition. Do not run it automatically.
6. Resume the project's saved question or exact evidence passage from Library.

## Cross-mode actions

**Investigate this** offers an existing project or explicit new-project form.
Preview carried context: work/version, selected passage, selected question/note
links. Never duplicate or move all notes implicitly. Display retry-safe pending,
failed, conflicting and successful states; repeated success returns the same
link/project, not another copy. Preserve the original learning return context.

**Learn this prerequisite** opens a learning thread linked to the originating
project, question and exact source. The owner can declare what needs explaining
without receiving a paid answer. A visible **Return to project** restores that
project's focused evidence/version/passage and current queue filters.

A shared note can reference a work/version and several projects/threads. Its
text has one revision history. Context-specific annotations do not silently
change the shared source's identity or availability.

## Reader assistance by purpose

| Area | Learning view | Research view |
|---|---|---|
| Source | Same retained text and exact anchors | Same retained text and exact anchors |
| Understand | Terms, prerequisites, equation/code explanation, self-check | Claim/evidence, assumptions, comparisons, limitations |
| Your notes | Questions, observations, concept links | Questions, evidence notes, hypotheses, proposed next actions |
| Generated work | Learning explanation/dive, gated | Evidence answer/comparison/dive, gated |

Both generated views must show the exact approved submitted context, evidence
scope, source/version, cited spans, uncertainty and spend receipts. Private
notes, preferences and reading history remain excluded by default. A profile
may affect local ranking without being sent remotely.

## Navigation, drafts and mobile

Reuse the shared navigation policy for the actual scrolling container. A route
lands at its heading; queue changes land at the new paper header; explicit
Reader section/question/passage takes priority; Back/Forward restores context.
Switching modes must pass the same unsaved-draft/pending-write protections.
Do not claim the existing browser-storage/Back-Forward draft limitation is fixed
by introducing a new URL field; add a regression that reproduces and repairs it.

At 390×844 keep a full focused title and at least two lines of available abstract
unobscured above the collapsed player, including after mode/queue changes and
Reader return. Search stays collapsed until requested. All shortcuts have visible
controls; typing never triggers queue or labeling commands. Jazzy remains the
original mascot, with restrained reduced-motion-aware transitions.
