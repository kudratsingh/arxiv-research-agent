# Personal review and grounded-executor checkpoint

2026-11-03, continuing reviewed PR #282 `403e5fae6f32bec04702b2ecd9c905216d38c2b7`.
That remote head and its worktree were unchanged when this batch began.
The new branch is `codex/daily-workspace-next`, stacked on #282. PR #281 and
#282 remain draft and unmerged. The shared owner checkout and original local
changes were preserved. No ADR number was consumed: the workspace proposal
remains unnumbered and the existing 0103 reservation is untouched.

## Open the connected workspace

Open **http://127.0.0.1:3137/workspace/today** if the owner app is running.
For a stopped app, use [the everyday operation guide](19-everyday-operation.md).
The original fictional preview stays separate on port 3127. Live records,
controlled browser tests, fixture CI data and fake generated output have
separate evidence labels; none substitutes for another.

1. In **Interests**, inspect selected matching terms and active/limited/
   unconnected source coverage. Authored ML parents expand to their descendants;
   broad catalogue fields without connected terms remain browsing navigation.
   Edit streams, custom terms, exclusions and reading time normally.
2. In **Today**, compare 15 and 45 minutes. Five-minute slots are planning
   estimates. Exploration is an upper cap on the **final** item count, rounded
   down. At 15%, three items allow zero exploration; nine allow one. At 30%,
   those allow zero and two. Zero exploration adds none. Sparse direct matches
   shorten the edition rather than silently exceeding the cap. The receipt
   shows actual/planned counts and unused slots; old editions without a receipt
   are labelled instead of being retrospectively rewritten.
3. Open a source, select text and save a question. Repeat on another paper;
   edit the first question. The last committed activity wins, including edits,
   using a database sequence rather than flattened source order or client time.
   **Keep the thread** links to its exact work/version/passage. Pin a question
   if desired; unpin restores latest activity. Reader return, reload and Library
   resume preserve the original version even when the work has a new revision.
4. Open **Review candidate usefulness**. Prepare the ten-item packet explicitly.
   Inspect each actual source, matching reason, evidence scope and five-minute
   estimate. Mark useful / maybe / irrelevant and optionally explain why; only
   an explicit Save persists a judgment. All initial labels are blank. Conflicts
   preserve the draft and require reconciliation. Older packets keep their
   frozen source version. Today itself remains a short edition.
5. In Reader's **Understand** section, use the synthetic workbench explicitly.
   Load retained material, choose bounded passages, inspect the exact JSON
   context, then run the fixture pipeline. Notes/history/preferences are excluded
   and the optional typed question starts blank. Inspect findings and source
   links, limitations, inferences and proposed experiments separately. Every
   result says fake/synthetic, with workflow/checker/unknown counters and $0.
   Paid controls remain disabled and the paid endpoint refuses before a client.
6. Search Radar for **ReAct** or **Self-RAG**. Open retained selected-page text,
   inspect original PDF page numbers and extraction warnings, select a passage
   and resume it from a saved question. The source remains an excerpt, not a
   full-paper reading. Abstract/feed-only items retain their useful manual reader.

## Ten-item review to return

`outputs/workspace-next/owner-usefulness-review-10.md` and its JSON companion
contain ten real stored candidates ranked against the unchanged owner profile.
Each has source URL/ID, exact version, matching reason, evidence scope and an
estimated five-minute metadata inspection. All ten owner labels and reasons
are blank. No usefulness precision, owner approval or scientific-quality score
was inferred. In-app preparation persists a new frozen packet only when the
owner explicitly asks for one.

The initial feed receipt remains 83 works / 158 immutable versions after the
previous normalization, with three partial arXiv windows. Two additional old
scientific qualification papers are independent public samples; they are not
new Today discoveries. Two PDF GETs transferred 2,038,932 bytes. No new metadata
refresh was needed for this batch's tests or rankings.

## Verification and evidence boundaries

Write-based checks run only as `workspace-verification` in a disposable database
on ports 8139/3139, with public metadata copied and no private owner notes or
profile copied. The browser guard refuses `personal-local` before any write.
The real-public-source local walkthrough and the offline CI seed are distinct.
The latter validates durable behavior without public HTTP requests.

Focused production screenshots are under `outputs/workspace-next/screenshots/`:
Today, question return, blank review, synthetic workbench, plus source-failure
recovery where noted. Desktop is 1440 px and phone is 390 px. Browser traces and
full receipts are under `web/build/workspace-live/` and
`web/build/workspace-next-scientific/`. Screenshots and private outputs are not
committed. Controlled save/API failures are labelled as injections, never real
source-outage observations.

The fake pipeline has source/request/stage binding, split accounting, atomic
reservations, cancelled/uncertain states, bounded repair and recheck, cache
invalidation and restart tests. These establish mechanics. They do not measure
real model tokens, semantic factual support, checker calibration or usefulness.
Equations/tables/figures remain explicitly unqualified where extraction lost
structure; see [the inspected sample](18-fulltext-qualification.md).

The reviewed source checkpoint has 3,710 web tests / zero skips and passes all
unchanged web coverage floors and production route/CSS ceilings. Fourteen real
API desktop/mobile cases and two scientific PDF cases pass against the
production standalone build. Final commit attribution, Python gates and CI
must be read from the final verification receipt and PR checks, not inferred
from an earlier commit or the old #282 run.

## Next implementation sequence

1. Owner reviews the finite briefing, return experience and ten real candidates;
   adjust reversible relevance preferences based on actual labels.
2. Finish actual paid gateway/settings/schema/token enforcement behind the
   disabled gate; measure exact proposed request tokens and qualify the actual
   checker with representative human labels. Fake counters cannot replace this.
3. Review the refreshed [unexecuted trial packet](15-grounded-generation-approval-packet.md).
   A specific later GO must name model, public context, one-off scope and caps.
4. Run a separately approved tiny trial, inspect every claim/source pair and
   publish its small denominators. Real grounded summaries and guided deep dives
   remain explicit W8/W9 milestones; a bookmark dashboard or fixture output
   cannot complete them.
5. Only after owner confirmation of time/timezone, review worker deployment and
   activate recurrence. Until then refresh is manual; sleep produces no delivery.

Remaining owner choices are the ten usefulness judgments, reader depth and
whether/when to approve a concrete paid qualification, and a schedule time if
recurrence is desired. Hardware constraints are needed only for realistic
experiment feasibility; proposed experiments remain unexecuted and feasibility
unknown in the meantime.
