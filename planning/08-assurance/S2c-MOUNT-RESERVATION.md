# WO-S2c — the run panel holds its place on a phone

Status: **DELIVERED** (branch `assurance/wo-s2c-mount-reservation`, rebased
onto `344e90e`)

The residual `S2b-CLS-FALLBACK.md` measured and deliberately did not absorb,
paid back. That file holds the trade this one closes; the S-series index is
the coordinator's, so this file is S2c only.

Every number below was measured on the seeded local stack (`stack.sh`,
project `arxiv-s2c-e2e`, ports 13270/18270). The **before** column was taken
by putting the five changed source files back to `origin/main`'s copies,
rebuilding the `web` image and re-running the same scripts; the **after**
column is this branch through the same scripts against the same stack. The
two columns therefore differ by exactly this change and by nothing else. The
branch was then rebased onto `344e90e` (CAP-05, WO-D7, WO-INF2, P0-WO07b,
CAP-10), none of which touches a file under `web/` — `git diff c3371fd
344e90e -- web/` is empty — so every browser measurement stands on the
rebased tree; the suites were re-run on it regardless.

## The two shifts, and why neither was S2b's to fix

S2b closed the review pause at 1280x900 — 0.05113 → 0.00002 — by making
`PlanEditor`'s Suspense fallback an exact mirror of the form it holds the
place of. It said plainly that this did not touch 412x915, and why: the
fallback is a **descendant** of the box that moves there.

At plain 412x915, over 16 cold loads of the review pause on `origin/main`:

| entry | value | on how many of 16 loads |
|---|---|---|
| `div.ew-thread__timeline` [y 410, h 435] and `div.ew-thread__composer` [y 845, h 70], both out of view | **0.55191** | 4 |
| `section.flex` [y 506, h 409] → [y 530, h 385], with a 32px `div.flex` above it moving the same 24px | **0.01147** | 9 |
| neither | 0.00000 | 4 |

Both were reproduced frame by frame in Chromium rather than inferred.

### 0.55191 — the panel mounts in a shape it does not keep

`/c/{id}?job={id}` issues two reads at once. On the loads that are charged,
`GET /conversations/{id}` answers first, so the thread paints — and the run
row asks the panel what it is looking at while `GET /research/{id}` is still
in flight. `hasActiveRun` is true (the URL named a job), `isReviewPause` is
false (no plan has arrived), so the row writes `data-run="attached"`: *a run
is on this page AND events are arriving*, about a run whose status has not
been read. The frame log, at 412x915:

```
t=64   .ew-thread--loading            composer [y 629, h 286]                 doc 915
t=96   data-run="attached"   row 224  timeline [y 410, h 435]  composer y 845  doc 1131
t=116  data-run="review"     row 1769 timeline [y 1955]         composer y 2633 doc 2919
```

The first transition is free and is designed to be: `.ew-thread--loading` and
`.ew-thread` are different element trees, so every node in the loaded frame is
newly inserted, and a node that did not exist a frame ago cannot have moved.
The second transition moves nodes that are already on screen. That is what a
layout shift is, and 435px of reading column plus 70px of composer leaving a
915px viewport is 0.55191 of a 0.02 budget.

At 1280x900 the same two frames occur — the row goes 224 → 995 — and Chromium
charges **nothing** for it, which is why S2b's 0.00002 was honest and why this
defect could sit undetected behind a green desktop number. The gate below is
therefore an equality on the geometry at both widths, not a CLS threshold at
one.

### 0.01147 — the `Live` badge cannot join a line that is already full

The spine's status line is a `flex-wrap` row: the announcement, its detail,
and the ambient `Live` badge, which mounts when the socket opens
(`model.live` is `connection === "open"`). WO-W13c fixed this line once
already — the badge's baseline is synthesised from a 16px mark, so joining an
`items-baseline` row grew it from 20px to 23px; `spine.css` rule 4 centres the
badge instead.

At 412 CSS px the badge joins nothing. `RUN_STATUS_LINE.awaitingReview` —
"Waiting for your review. The run is paused and not spending." — already takes
both lines the row wraps to, so the badge lands on a **third**:

```
t=89   data-live="false"  announcement row h=40  spine h=296   (no badge)
t=102  data-live="true"   announcement row h=64  spine h=320   badge [y 454, h 20]
```

24px, taken out of the reading column, on every cold load where the socket
opens after first paint — and taken back, upwards, every time a socket drops
on a phone mid-run, which is the same defect rule 4 exists to prevent. An
alignment cannot stop a wrap.

## The fix — two reservations, both exact

### 1. The loading frame is the run panel's mount reservation

`ActiveRunPanel` gains a third exported predicate beside `hasActiveRun` and
`isReviewPause`, for the same reason those two are exported — the row's
geometry and the panel's contents must answer from one expression or they
drift:

```ts
export function isRunUnread(state: JobState): boolean {
  return state.phase === "attaching" && state.detail === null;
}
```

`ThreadTimeline` holds `ThreadSkeleton` while that is true. **Nothing new is
designed and nothing new is reserved**: the frame is byte-identical to the one
the transcript's own wait already uses, and `loading.tsx` already documents
three paths that reach it. This is the fourth — *the transcript is here, and
the run it names is not*. What changes is when the frame is released, and the
consequence is that the run row mounts **once**, at the height it keeps.

**`detail === null` and not the phase alone.** `machine.ts`'s
`review_conflict` cell sends the machine back through `attaching` with the
detail it already read still in hand. A hold keyed on the phase alone would
take the plan editor, the conflict banner and the user's own edits off screen
at exactly the moment WO-S3 exists to keep them there — the same defect, one
surface up.

**The hold is latched to the mount, and that is load-bearing.** `attaching`
with a null detail is also true a beat after *any new* attach: a follow-up
submission (`freshRun` clears the detail, `submit_accepted` moves to
`attaching`), or the rail moving to another run. Falling back to a skeleton
there would throw the whole transcript away every time somebody asks a second
question. So `painted` latches when the loaded frame is returned and the hold
never applies again. It is set during render rather than in an effect: React
re-runs the component immediately and discards the first pass without
committing it, so the latch costs no extra commit and no extra paint —
`react-hooks/set-state-in-effect` and `react-hooks/refs` refuse the other two
spellings anyway.

### 2. The `Live` badge's box is reserved wherever a socket is expected

`lib/spine/state.ts` gains `SOCKET_EXPECTED`, which is **not** `STREAMING` and
differs from it by exactly one id:

| set | question | members |
|---|---|---|
| `STREAMING` | are frames still expected? | `running_observed`, `rejoined`, `reconnecting`, `recycled` |
| `SOCKET_EXPECTED` | is a connection expected to be open? | those four **plus `awaiting_review`** |

At the review pause no frames are expected — the run is stopped and spending
nothing until the reader answers — and the stream is open the whole time the
pause lasts. Writing the two as one set would put a `Live` badge on a settled
run or take the age off a paused one.

In those five states `TraceSpine` renders **the real `StatusBadge`, with the
real word and the real classes**, and hides it with
`visibility: hidden` until the connection is actually open. Identical markup
is the only reservation that can be exact here, because the box that decides
where the row wraps is the badge's own width: anything narrower under-reserves
at some width and anything wider over-reserves at another. `visibility` and
not `opacity` or a zero size — it is the one value that keeps the box while
dropping both the paint and the accessibility tree. `ambient` follows `live`
rather than the slot, so the pulse still runs only while a socket is open
(criterion 8); `.ew-pulse` animates opacity alone, so the reserved box and the
live one are the same size either way.

The five terminal states and `submitting` reserve nothing, which is what keeps
a finished run from holding a line open for a badge that is not coming.

## Measured, before → after

### The residual this work order was given

| | before | after |
|---|---|---|
| cold-load CLS, review pause, **plain 412x915** (n=16; min / median / max) | 0.00000 / 0.01147 / **0.56339** | **0.00000 / 0.00000 / 0.00000** |
| — of which the mount shift (`div.ew-thread__timeline` + `div.ew-thread__composer`) | **0.55191**, on 4 of 16 loads | absent, 0 of 16 |
| — of which the badge shift (`section.flex` + `div.flex`, 24px) | **0.01147**, on 9 of 16 loads | absent, 0 of 16 |
| cold-load CLS, review pause, 412x915, with `GET /research/{id}` held 600 ms (n=3) | 0.56339 / 0.56339 / 0.55191 | **0.00000 / 0.00000 / 0.00000** |
| cold-load CLS, review pause, **plain 1280x900** (n=16; min / median / max) | 0.00000 / 0.00000 / **0.00002** | **0.00000 / 0.00000 / 0.00000** |

**412x915 is 0.00000, not merely under 0.02.** Both components are closed, and
the 1280x900 residual S2b recorded — 0.00002 from a 16px `svg` glyph in the
shell header, present on `main` inside the 0.05115 figure too — is gone with
them: it was charged on the frame the row flipped, and there is no longer such
a frame.

### The reservations, as equalities

| | before | after |
|---|---|---|
| run row: first painted height / settled height, 1280x900 | 224 / **995** | 995 / **995** |
| run row: first painted height / settled height, 412x915 | 224 / **1,769** | 1,769 / **1,769** |
| run row: `data-run` on the frame it first exists | `attached` | **`review`** |
| spine announcement row: first painted / settled, 412x915 | 40 / **64** | 64 / **64** |
| spine announcement row: first painted / settled, 1280x900 | 20 / 20 | 20 / 20 |

To the pixel, at both audited widths. **Over-reserving is the same defect with
the sign flipped**, which is why every row above is asserted as an equality and
not as a bound: a row taller than the pause would shift the page *up* when the
real height arrived.

### The measurements S2c must not move

| | before | after |
|---|---|---|
| three checkpoints into a live run, 1280x900 (n=5) | 0.00016 | **0.00016** |
| three checkpoints into a live run, 412x915 (n=5) | 0.00004 | **0.00004** |
| `@device` cold-load sweep, Pixel 7 — `landing` (n=4) | 0.00000 | **0.00000** |
| `@device` — `thread-empty` | 0.00000 | **0.00000** |
| `@device` — `thread-populated` | 0.00000 | **0.00000** |
| `@device` — `plan-review` | 0.00000 | **0.00000** |

Both columns are fresh measurements on this stack, not carried over from
S2b's record. The three-checkpoint figures reproduce S2b's to five decimals
and the sources are the same two zero-distance entries (`span.text-ink-muted`
and `span.ew-spine-void` at 1280; `span.ew-spine-void` alone at 412). The
`@device` `thread-populated` row is the known pre-existing flake — 0.03957 to
0.13614 on `main` at plain 412 — and read 0.00000 on all four repeats in both
columns.

**`web/e2e/reach.spec.ts` passes, all four**, including the fourth, which
asserts that a live run at desktop width still gets the bounded row and the
fixed frame. **`web/e2e/plan-fallback.spec.ts` passes, all three**: S2b's
586/586 and 1172/1172 fallback mirror is untouched. S2's rule is untouched —
`workspace.css` is not edited by this change, the `data-run="review"` selector
still puts the shell into document mode, and the comment recording the
reverted 0.01911 experiment stands.

### No golden moves

The 48 committed `@visual` baselines and the 5 README captures were all
re-rendered against this branch: **55 `@visual` tests pass and 9 `readme`
tests pass**, so none of WO-D6's 18 regenerated goldens or 2 README images
needs a regeneration pass.

The one that had to be checked by hand is `reconnecting` at 412, which is the
only committed state that now carries a *reserved* badge — the socket is down
in that capture, so `main` rendered no badge and this branch renders a hidden
one. It does not move the picture: "Reconnecting…" is one line at 412, so the
badge fits beside it and the row is 20px in both trees. The 24px this work
order is about is specific to the review pause's two-line sentence.

### Route budgets

Both columns taken on `96a058f` — `main` reads the same four figures there as
it does on `c3371fd`, and `web/` is byte-identical again at `344e90e`, so the
rebases moved nothing here either.

| row | before | after | delta | ceiling |
|---|---|---|---|---|
| `/c/[id]` first-load JS | 188,828 B | **188,924 B** | +96 B | 192,512 B |
| `/` first-load JS | 163,144 B | 163,137 B | -7 B | 166,912 B |
| all emitted CSS | 11,499 B | **11,518 B** | +19 B | 12,288 B |
| derived cold-cache transfer for `/c/[id]` | 303,803 B | 303,918 B | +115 B | 314,368 B |

Every row PASS; `/c/[id]` keeps 3,588 B of headroom. No ratchet entry is
needed or taken. The 96 B is the predicate, the latch and the reserved
badge's branch; the 19 B of CSS is `.ew-spine-live--reserved`.

## The assertions that stop it regressing

**`web/e2e/mount-reservation.spec.ts`**, four tests, tagged `@cls` so they run
in the chromium project the per-PR CI job carries.

1. *the outcome* — cold-load CLS on the review pause at **412x915** is
   `<= 0.02`, measured from before the first byte of page script with
   `buffered: true`, with every shift's sources in the failure message.
2. *the mechanism, the panel* — at 1280x900 and at 412x915, the run row's
   height on the frame it first exists equals its settled height, and its
   `data-run` on that frame is `review` and not `attached`.
3. *the mechanism, the badge* — at 412x915, the spine's announcement row's
   height on the frame it first exists equals its settled height.

**Each test holds the one response whose lateness is its subject** — `GET
/api/research/{id}` for the panel, the SSE stream for the badge — rather than
racing it. That is not a convenience: on `main` the mount shift was charged on
4 of 16 plain cold loads, and a gate that fires a quarter of the time is not a
gate. Holding makes the worst case certain, and the worst case is a superset
of the plain load's, so anything that passes held passes unheld. The URL
predicate matches `/api/research/{id}` and not `/api/research/{id}/stream` for
the reason `support/paid-path.ts` gives about globs.

All four are **red on `origin/main`**, printing the numbers this file reports:

```
cold-load CLS on the review pause at 412x915 is 0.56339 against 04 §8.2's 0.02 ceiling
  … [{"value":0.55191,"sources":[{"node":"div.ew-thread__timeline","from":[410,435],"to":[0,0]}, …
     {"value":0.01147,"sources":[{"node":"section.flex","from":[506,409],"to":[530,385]}, …
at 1280x900 the run row first painted at 224px and settled at 995px
at 412x915 the run row first painted at 224px and settled at 1769px
at 412x915 the announcement row first painted at 40px and settled at 64px
```

**`web/tests/features/mountReservation.test.tsx`**, five tests, holds the half
that will actually rot — the predicate's truth table across the machine's
phases, the 409 re-attach it must NOT fire on, the hold itself, the re-attach
that must never take the transcript away again, and the `?job=`-less thread
that is not held at all. The hold test is red without
`ThreadTimeline`'s guard, with the message "the thread painted before the run
it names had been read".

**`web/tests/patterns/TraceSpine.test.tsx`** gains two: the reserved badge is
the same word and the same mark with `visibility: hidden` and no pulse, in
exactly the states where a socket is expected and nowhere else; and
`SOCKET_EXPECTED` is those five ids, stated once so a later edit cannot
quietly reserve a line on a run that has ended. WO-W13c's own test keeps its
claim, widened by one clause: a badge is on the line whenever one is live
**or still expected**.

`web/tests/features/routeComposition.test.tsx` has one query scoped to the
timeline. That is the claim rather than a narrowing of it: the spine carries a
`Live` badge of its own, so a document-wide `getAllByText("Live")` answered
"the timeline marks exactly one turn" only for as long as that badge happened
to be absent — which in jsdom it always was, because nothing there opens a
socket. A real browser with a real stream had two matches all along.

jsdom has no layout engine, so no pixel claim lives there — which is why the
equalities live in Chromium and why this file states both halves.

## Gate

* `npm test -- --run` — 3,529 passed over 161 files with a production build
  present (3,520 passed / 9 skipped without one; the nine are
  `bundle.test.ts`'s build-manifest half)
* `npx tsc --noEmit` — clean
* `npm run lint` — clean
* `npm run budgets` — every row PASS (table above)
* `npm run build-storybook` — completed; `npm run audit:gate` — exit 0
* `npx playwright test --project=chromium --grep-invert @visual` — 271 passed
  / 5 skipped
* `--project=chromium e2e/visual.spec.ts` — 55 passed; `--project=readme` — 9
  passed
* `--project="Pixel 7" --project="iPhone 15"` — 38 passed / 4 skipped
* `pytest -m "not e2e"` — **5,025 passed / 54 skipped / 53 deselected on the
  pre-rebase base (`c3371fd`)**. On the rebased tree the shared `.venv` cannot
  collect three modules — see below.

No flake was observed in any of the runs above.

### The one gate that does not pass locally, and why it is not this change

After the rebase past CAP-05, `pytest -m "not e2e"` stops at collection:

```
ModuleNotFoundError: No module named 'httpx2'
  tests/test_llm.py
  tests/fault/test_model_provider_faults.py
  tests/fault/test_supervisor_routing_faults.py
```

CAP-05 (PR #231) moved the Anthropic SDK to 1.x and pinned
`httpx2==2.12.0` in both lockfiles; the SHARED `.venv` at
`arxiv-research-agent/.venv` still holds `anthropic 0.116.0` and no `httpx2`,
because nothing has re-installed it since that merge. It is an environment
gap, not a tree gap: the standing constraint forbids `pip install` into that
venv, and CI installs from the lockfiles and is unaffected.

**Proven not to be this change** two ways: this branch's diff contains no
Python file at all, and the identical collection error reproduces on a clean
`origin/main` working tree (`git stash` → `pytest tests/test_llm.py` → same
`ModuleNotFoundError`) in the same venv.

With those three modules ignored, the suite is **4,998 passed / 54 skipped /
53 deselected** plus four failures that are all consequences of the ignore —
`test_documented_claims.py`'s three suite-count claims and the e2e marker
count, which compare the README's floor against the number of tests actually
collected. Nothing else is red.

## What this work order did NOT do

It did not weaken S2's document-mode rule and it did not touch S2b's fallback
mirror. `workspace.css` is unedited; `PlanEditor.tsx` is unedited. The three
trades this sequence has recorded — S2's 14rem cap, S2b's fallback height,
and the 0.01911 lift-the-cap-below-`md` experiment that was measured and
reverted — all stand exactly as they were written.
