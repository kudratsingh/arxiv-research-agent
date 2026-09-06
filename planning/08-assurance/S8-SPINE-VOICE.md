# WO-S8 — The spine speaks to a researcher, and the metrics survive a reload

**Lane:** assurance (bumblebee) · **Branch:** `assurance/wo-s8-spine-voice` ·
**Base:** `origin/main` 3d0d588 · **Model spend:** zero

Closes the two items the frontend presentability survey left open after S2c
(S8, and the outstanding half of S9). Both are product bugs on the surface
the product is most identified with: the checkpoint spine.

---

## 1. What was wrong

### 1.1 The spine reported the observer, not the research

Four findings, in the order the survey ranked them:

| # | Finding | Where |
|---|---|---|
| 1 | `SPINE_SEGMENTS` ended in **`Report`** while every other surface in the product said **Briefing** | `web/lib/copy/trace.ts` |
| 2 | A **succeeded** run loaded from thread history printed `No longer available` three times and said its plan and checkpoints "are not stored" | `web/lib/spine/state.ts`, `web/lib/copy/trace.ts` |
| 3 | Internal node ids (`reader`, `planner`) printed verbatim with nothing on screen saying what kind of word they are | `web/components/patterns/CheckpointLedger.tsx` |
| 4 | A run still under way announced the observer's epistemic state and nothing about the run | `web/lib/copy/trace.ts` |

Finding 2 is the one that matters most, and it is a category error rather
than a wording preference. **"We did not observe this" and "this did not
happen" are different claims.** `unavailable`'s word is
`RUN_STATUS_WORD.expired` — "No longer available" — the word reserved for a
run the server answered `404` for. The `historic` row (`status === succeeded`
with an empty ledger: a reload, or a thread reached from the rail) used that
word for its first three segments. So a run that **worked**, whose briefing
was on screen and exportable, was described in the vocabulary of a run that
is gone; and its status line — "This briefing was produced outside this
session. Its plan and checkpoints are not stored." — never once said the run
succeeded.

The plan clause made it worse by being selectively true. `job.plan` is erased
on resume for *every* run (D-010, `schemas.py:98-124`), watched or not, and
the `succeeded` row does not mention it. Printing it only in `historic` made
an unwatched run look degraded relative to a watched one when the two are
identical in that respect.

### 1.2 The metrics did not survive a reload

`MetricsStrip` was rendered only when `ThreadTimeline` had a `JobDetail`, and
its only `JobDetail` was the job machine's — `briefing.live ? state.detail :
null`. The five numbers, the dollar figure among them, existed while this tab
happened to be attached to the run and nowhere else.

That was never a contract limit. `GET /research/{id}` is free and read-only
(`routes.py:215-232`) and reports all five for as long as the record is
retained. What carries no metrics is `ConversationJobSummary`
(`schemas.py:207-214`) — job id, ordinal, query, report, created_at — so the
*thread* read cannot supply them and the *turn* has to ask for its own.

---

## 2. Before / after

Every sentence changed, in full.

| Key | Before | After |
|---|---|---|
| `SPINE_SEGMENTS[3]` | `Report` | `Briefing` |
| `RUN_STATUS_LINE.historic` | "This briefing was produced outside this session. Its plan and checkpoints are not stored." | "Complete. This briefing was produced outside this session, so no checkpoints were observed on this connection." |
| `RUN_STATUS_LINE.rejoined` | "Rejoined this run. Earlier checkpoints are not replayed." | "This run has not finished. Earlier checkpoints are not replayed." |
| `SPINE.ledgerNote` | *(did not exist)* | "Each label is the checkpoint the run reported, shown exactly as it arrived." |

One table row, which is a rendered claim rather than a sentence:

| Row | Before | After |
|---|---|---|
| `SEGMENT_TABLE.historic` | `["unavailable", "unavailable", "unavailable", "complete"]` → "No longer available" ×3 | `["observed", "not-observed", "not-observed", "complete"]` — identical to `succeeded`'s row |

`historic`'s row is now `succeeded`'s verbatim, which is the point: the two
ids differ only in whether this browser saw the checkpoints, `spineStateId`
splits them on exactly that, and RUN is the one computed cell so it follows
the (necessarily empty) ledger down to `not-observed` on its own. The whole
of the difference now lives in the sentence, where it is a statement about
observation rather than a mark that reads as data loss.

Two documented claims moved with it:

- `README.md` — "…`Run` and `Report` not yet observed" → "`Briefing`"; and
  the screenshot blockquote's "its checkpoint spine honestly reports `No
  longer available`", which this change makes false, now describes what the
  spine actually reports.
- `docs/demo.md:513` — "*Question → Plan → Run → Report*" → "*… → Briefing*".

---

## 3. What was considered and rejected

**A node vocabulary (`reader` → "Read the papers").** Rejected, and the
refusal is pinned by a test. It would be a second authority beside the frame;
it would be maintained in the web tier while the graph that emits the labels
is edited in another — `src/graph/` gained `verify`, `repair`, `lead`,
`workers`, `merge` and a router in one campaign wave — and the first label it
did not recognise would be dropped or, worse, mislabelled. 03 §1.5 and WO-15
criterion 2 already settle it: the node set is configuration-dependent and
"the ledger never contains a label that did not arrive in a `node_completed`
payload". An opaque true label beats a familiar false one. The label stays
verbatim; one sentence in the legend now says what kind of word it is.

**Re-voicing the four segments to sub-questions / papers / claims** (the
survey's own suggestion). Rejected: it is more than the data supports. The
spine takes 03 §5.2's four inputs and no others. Papers and claims appear in
none of them and in no field of `JobDetail`. Sub-questions appear in
`plan.sub_questions`, which is non-null during `pending_review` alone
(`schemas.py:98-124`) — where `PlanEditor` is already on screen listing every
one of them. A "Papers" segment would be blank in eleven of twelve states and
redundant in the twelfth. `spineVoice.test.tsx` asserts the refusal so the
next reader of the survey does not have to rediscover it.

**Removing "observed on this connection".** Rejected. It is 03 §5.5's
required qualifier, asserted positively in two gate tests, and it is
load-bearing: the ledger resets on every `EventSource` open (04 §4.4 rule 2),
so a count without it is a claim about the run that nothing in the contract
supports. The fix for "it reads as connection telemetry" is to stop making it
the *first* thing a researcher reads on a settled run, which is what the
`historic` rewrite does — not to delete it. It survives in the new sentence.

**Rewording `observedCheckpoint()` ("observed reader" → "Checkpoint
observed: reader").** Rejected. It is the per-entry reading inside an `<ol>`
whose accessible name is already "Checkpoints observed on this connection";
repeating the category forty times is noise, and §5.5's rule is already
discharged. The visible problem is an *unexplained* id, and rewording a
clipped sentence does not explain it. The legend note does.

**Saying "The run is still going" in `rejoined`,** to match `recycled`.
Rejected: `spineStateId` routes `pending` and `awaiting_learner` to
`rejoined` as readily as `running`, and a queued run is not going anywhere
yet. "has not finished" is true of all three.

**Renaming the legend disclosure's trigger** ("What the marks mean") now that
it carries a sentence about labels. Rejected as churn: a checkpoint's tick
*is* one of the marks, and the trigger is visible text in six committed
goldens.

**Reserving the metrics strip's box while its read is in flight.** Rejected:
a run whose record has expired never gets a strip, so the reservation would
have to be given back, which is the same shift with the sign flipped. The
strip is the last element inside `ReportReader`, below the briefing body, and
the gated cold-load CLS sweep runs at 412 px where it is far below the fold.

---

## 4. What changed

| File | Change |
|---|---|
| `web/lib/copy/trace.ts` | `SPINE_SEGMENTS[3]`, `RUN_STATUS_LINE.historic`, `RUN_STATUS_LINE.rejoined` |
| `web/lib/copy/spine.ts` | `SPINE.ledgerNote` (new) |
| `web/lib/spine/state.ts` | `SEGMENT_TABLE.historic` |
| `web/components/patterns/TraceSpine.tsx` | `SpineLegend` renders the label note (inside the disclosure; `legend="none"` renders neither) |
| `web/components/features/ThreadTimeline.tsx` | `useJobDetail` for an expanded, non-live turn; the strip's source is the machine's detail *or* that read |
| `README.md`, `docs/demo.md` | the two documented claims the change makes false |

`web/lib/copy/index.ts` is untouched: no deny-list entry, no lexicon entry and
no pedagogy entry is added, removed or reworded, so the Python mirror needs no
change.

---

## 5. Evidence

**Regression proof.** 13 of the 21 assertions in the two new files fail with
the five product files taken back to `origin/main`:

```
web/tests/patterns/spineVoice.test.tsx     9 of 16 red on main
web/tests/features/turnMetrics.test.tsx    4 of  5 red on main
```

The 8 that are green on both sides are green **on purpose**: they pin the
limits and the refusals (a collapsed turn issues no read; the live turn keeps
one authority; no segment names a paper or a claim; the count keeps its
qualifier), so a "fix" that bought the numbers with a request storm, or the
voice with an invention, would go red here rather than pass quietly.

Two existing tests changed meaning and both carry the reason in the file:

- `spineState.test.ts` "a run this session watched finish and one loaded from
  history differ only in the ledger" — it *required* `historic`'s three
  `unavailable` cells. It now compares the two rows and additionally asserts
  that nothing on a succeeded run wears the word an expired one wears.
- `spine-copy.test.ts` — its composed sample used `segmentLabel("Report", …)`,
  and it gains a pin tying `SPINE_SEGMENTS.at(-1)` to
  `LANDING.process.at(-1)`, so the two cannot drift apart a second time.

**Gate, on this branch:**

```
web        163 files, 3547 passed / 9 skipped
tsc        clean
eslint     clean (--max-warnings 0)
pytest     5165 passed / 54 skipped / 53 deselected   (-m "not e2e")
budgets    every row PASS
```

**Route budgets**, paired builds on this tree:

| Row | main 3d0d588 | this branch | Δ | ceiling |
|---|---|---|---|---|
| `/c/[id]` first-load JS | 188,920 B | 189,099 B | **+179** | 192,512 B (3,413 B left) |
| `/` first-load JS | 163,135 B | 163,144 B | +9 (noise) | 166,912 B |
| Shared framework/runtime | 131,721 B | 131,722 B | +1 | 139,264 B |
| All emitted CSS | 11,518 B | 11,518 B | 0 | 12,288 B |

No ceiling moves. +179 B is the whole cost of wiring `useJobDetail` into the
route — the module was already written (WO-11) and, until this work order,
had no product caller at all.

**Accessibility.** Checked rather than assumed, because the strip now reaches
states it never reached before, and two expanded turns can now hold two of
them. axe-core over the composed thread with two turns open, best-practice
tags included, reports exactly one violation — `landmark-unique`, on the two
`section[data-report-reader]` elements, both named "Briefing" by
`REPORT.heading`. **The same violation is present on `origin/main`** with the
same two nodes; the metrics regions do not appear in it. So this change
introduces no new violation. The pre-existing one is a finding for the board
rather than this work order's to fix: the e2e axe sweep never expands two
turns, so it cannot see it.

---

## 6. Goldens that move — NOT regenerated

Per the work order, no baseline is regenerated here. Determined from what
each state renders; both suites skip on Linux, so neither goes red in CI.

**`web/e2e/__screenshots__/darwin/` — 28 of 48 expected to move.**

| Cause | States (× light/dark × 1440/412) | Files |
|---|---|---|
| The fourth segment's name | `plan-review`, `running`, `reconnecting`, `cancelled`, `failed-partial`, `expired` | 24 |
| A metrics strip on the auto-expanded history turn | `thread-populated` | 4 |

Unchanged (no spine, no expanded briefing): `landing`,
`submission-error-500`, `rail-error-upstream`, `thread-not-found-inline`,
`route-not-found` — 20 files.

`thread-populated`'s four are the least certain of the 28: the strip is the
last element of the reader and may fall outside the captured viewport at one
or both widths. The regeneration pass will settle it.

**`docs/images/` — 3 of 5 move.**

| Image | Why |
|---|---|
| `workbench-briefing.png` | its spine is the `historic` state — the `No longer available` ×3 this work order removes — and its fourth segment is renamed |
| `workbench-dark.png` | the same shot, dark theme |
| `workbench-plan-review.png` | the 1,068 px clip contains the spine, so the fourth segment's name is in the picture |

Unchanged: `workbench-landing.png`, `workbench-mobile.png` (both `/`, no
spine). `social-preview.png` is a designed graphic with no page behind it.

**The legend note moves nothing.** `ActiveRunPanel` renders the spine with
`legend="disclosure"` and the panel is `hidden` while collapsed, so the new
sentence is in the DOM and out of the paint in every committed capture.

Note for whoever sequences the pass: `README.md`'s prose is corrected in this
PR while its two images are not, so between this merge and the regeneration
the README describes a spine one commit ahead of its pictures. That is the
lesser of the two wrongs — the alternative is a README that makes a false
claim about the shipped product, which is the WO-D6 finding class — but it is
a real gap and it closes with the pass.
