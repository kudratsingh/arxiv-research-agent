# WO-S2b — the review-pause cold load comes back under budget

Status: **DELIVERED** (branch `assurance/wo-s2b-cls-fallback`, rebased onto
`a7ac479`)

The debt WO-S2 recorded rather than absorbed, paid back. `S2-SCROLLERS.md`
holds the trade this file closes; the S-series index is the coordinator's, so
this file is S2b only.

Every number below was measured on the seeded local stack (`stack.sh`, project
`arxiv-s2b-e2e`), against `origin/main` at `037c39a` — **with S2 and S3 both in
the tree** — for the "before" column, and against this branch for the "after"
one. The before column was taken by putting `PlanEditor.tsx` back to `main`'s
copy, rebuilding the `web` image and re-running the same scripts, so the two
columns differ by exactly this change and by nothing else. The branch was then
rebased onto `a7ac479` (P0-WO10), which touches **no file under `web/`**, so
every browser measurement below stands unchanged on the rebased tree; the
suites were re-run on it regardless.

## The regression, and why it existed

WO-S2 took `workspace.css`'s `14rem` cap off the run row at the review pause,
which is what made `Approve plan` reachable. That cap was also the thing that
had been absorbing `PlanEditorFields`' arrival. With the editor free to take
its real height, a cold load at 1280x900 read:

* t≈203 ms — the editor's Suspense fallback mounts, **200 px** tall;
* t≈231 ms — the lazy chunk resolves and the form takes its real height,
  **586 px**;
* the 161 px strip of reading column still visible below it is pushed off
  screen, and Chromium charges **0.05113** against 04 §8.2's **0.02**.

Nothing was slow, and nothing was wrong with how the fallback looked. **It was
386 px too short.** The same arithmetic at 412x915: a 424 px fallback for a
1,172 px form, 748 px short.

`main` hid that arrival by clipping the editor, which is precisely why the
approve control could not be reached. So the fix cannot be to clip it again,
and it cannot be to weaken S2's `data-run="review"` rule.

## The fix — reserve the space from the plan, which is already in hand

`PlanEditorFallback` in `web/components/patterns/PlanEditor.tsx` is now a
structural mirror of the form it holds the place of.

**The row counts come from the plan** — `initialDraft?.subQuestions ??
plan.sub_questions ?? []` and the same for the arXiv column, which is exactly
what `PlanEditorFields` opens with (`draftToValues(initialDraft ??
planToDraft(plan))`). Reading the plan when a draft has been restored would
reserve the wrong number of rows, which is the same shift wearing a different
coat.

**Everything whose height depends on the viewport is the form's own markup
with the form's own copy** — the same `fieldset`/`legend`, the same column
hint paragraph, the same empty note, the same add control, the same actions
row with the same two button labels and the same consequence sentence. That is
not decoration and it is the only way to be exact:

* `PLAN.subQuestionsHint` wraps to two lines at 1280 and the arXiv hint wraps
  to one, so the two columns have different natural heights and the grid row
  takes the taller — a token-arithmetic reservation would have to predict
  where a sentence wraps;
* the actions row is `flex-wrap`, and below `md` it wraps onto a second line.
  Where it wraps is decided by the two buttons' widths, which are their
  labels' widths. `PLAN.approve` and never `PLAN.revise`: the form opens
  un-edited, so `PLAN.approve` is the label on screen the frame the chunk
  lands.

**Only the two boxes whose height is constant are placeholders**, and both are
token expressions rather than pixel constants:

| box | reserved as | value |
|---|---|---|
| row label | `var(--text-ui-sm-line)` | 20 px |
| row field (`rows={2}`, `p-3`, 1px border each edge) | `calc(2 * var(--text-ui-base-line) + 2 * var(--space-3) + 2px)` | 74 px |
| row character counter | `var(--text-ui-xs-line)` | 16 px |
| remove control | `ew-target ew-target--md` | 40 px, **44 px under `pointer: coarse`** |

The `ew-target--md` class rather than a fixed height is load-bearing:
`primitives.css` raises `--ew-target-size` to `--size-target-coarse` on every
touch device, so a hardcoded 40 px block would under-reserve by 4 px per
control on every phone. The add and action controls are real `Button`s for the
same reason, plus one more — a `Button`'s width is its label plus
`CONTROL_PADDING`, and that width is what decides the wrap.

**Over-reserving is the same defect with the sign flipped**, which is why the
e2e assertion is an equality and not a `>=`: a fallback taller than the form
shifts the page *up* when the chunk lands.

**The mirror is `aria-hidden`**, for the reason `Skeleton`'s bars are — a
placeholder read aloud is a stutter of nothing — and every control in it
carries `disabled` rather than `aria-disabled`, so nothing inside the hidden
subtree is focusable (`aria-hidden-focus` stays clean) and a `getByRole` query
for `Approve plan` cannot match two elements while the chunk is in flight.
The clipped region name the old fallback carried through `Skeleton`'s `label`
is kept.

### What is NOT imported, and why the copy is stated twice

`PLAN_LIST_SPECS` — the table `PlanEditorFields` reads the same four strings
out of — lives in `lib/plan/schema.ts`, which is 460 lines of resolver and 422
mapping and is the module the lazy chunk already pulls. An eager value import
of it from `PlanEditor` would very likely relocate the whole module into
`/c/[id]`'s chunk union to read four strings, on a route with 4,126 B of
headroom. So the strings come from `lib/copy/plan` — the dictionary
`PLAN_LIST_SPECS` itself is built from, and which this file already imports —
and only the *pairing* of sentence to column is stated twice.
`web/tests/plan/fallback.test.tsx` compares the two statements field by field
so they cannot drift.

## Measured, before → after

### The regression itself

| | before | after |
|---|---|---|
| fallback box / form box, 1280x900 | 200 px / **586 px** | 586 px / **586 px** |
| fallback box / form box, 412x915 | 424 px / **1,172 px** | 1,172 px / **1,172 px** |
| plan-editor `section` height, while loading → loaded, 1280x900 | 356 → 742 | 742 → 742 |
| plan-editor `section` height, while loading → loaded, 412x915 | 620 → 1,368 | 1,368 → 1,368 |
| **cold-load CLS, review pause, plain 1280x900** (n=5; min / median / max) | 0.05113 / 0.05115 / 0.05115 | **0.00000 / 0.00000 / 0.00002** |
| cold-load CLS, review pause, plain 412x915 (n=16; min / median / max) | 0.00000 / 0.56339 / 0.56339 | 0.01147 / 0.56339 / 0.56339 |

**The reservation is exact, not generous.** 586 px against 586 px and 1,172 px
against 1,172 px, to the pixel, at both audited widths — which is the whole
claim, and is asserted rather than merely reported (below).

**The 1280x900 residual is 0.00002**, and it is not the editor: it is a 16 px
`svg` glyph in the shell header moving 52 px sideways at t≈130 ms. It is
present on `main` too, inside the 0.05115 figure above.

### The 412x915 residual, which S2b does not fix and does not cause

At a plain (non-device-emulated) 412 px viewport the review pause carries two
shifts, and **both are identical before and after** — same nodes, same rects,
same values, same distribution over 16 cold loads each:

1. **0.55191** — `div.ew-thread__timeline` (435 px at y=410) and
   `div.ew-thread__composer` (70 px at y=845) both pushed entirely out of
   view at t≈105-230 ms. This is the run panel **appearing** after first
   paint, not the editor **growing**: it is charged the moment the paused
   run's panel mounts at all, and the fallback lives inside that panel, so
   its height cannot cause it. On roughly three quarters of cold loads the
   panel mounts late enough to be charged; on the rest it is on the first
   painted frame and the entry does not exist.
2. **0.01147** — the plan-editor `section` and a 32 px `div` above it both
   move down 24 px at t≈115-170 ms, inside `section[data-surface="active-run"]`.
   The mover is a **sibling above** the editor in the run panel; the fallback
   is a descendant of the box that moves and cannot push its own ancestor
   down.

Both are pre-existing behaviour of the surface WO-S2 delivered, and closing
them is a different work order (it is a *mount* reservation in the run panel,
not a *growth* reservation in the editor). They are recorded here rather than
absorbed, and `plan-fallback.spec.ts` deliberately does not gate on 412 —
gating on it would pin a flake to this change. The **gated** measurement at
that width is `cls.spec.ts`'s `@device` block at the Pixel 7 profile, which
reads 0.00000 on this state before and after.

### The three measurements S2b must not move

| | S2 recorded (before) | this branch (after) |
|---|---|---|
| three checkpoints into a live run, 1280x900 | 0.00016 | **0.00016** |
| three checkpoints into a live run, 412x915 | 0.00004 | **0.00004** |
| `@device` cold-load sweep, Pixel 7 — `landing` | 0.00000 | **0.00000** |
| `@device` — `thread-empty` | 0.00000 | **0.00000** |
| `@device` — `thread-populated` | 0.00000 | **0.00000** |
| `@device` — `plan-review` | 0.00000 | **0.00000** |

Identical to five decimal places. Neither could have moved by construction —
a live run mounts no `PlanEditor` at all — but they were re-measured rather
than assumed.

**`web/e2e/reach.spec.ts` passes, all four**, including the fourth, which
asserts that a live run at desktop width still gets the bounded row and the
fixed frame. S2's rule is untouched: `workspace.css` is not edited by this
change, the `data-run="review"` selector still puts the shell into document
mode, and the comment recording the reverted 0.01911 experiment stands.

### Route budgets

| row | before | after | delta | ceiling |
|---|---|---|---|---|
| `/c/[id]` first-load JS | 188,386 B | **188,827 B** | +441 B | 192,512 B |
| `/` first-load JS | 163,133 B | 163,140 B | +7 B | 166,912 B |
| all emitted CSS | 11,491 B | 11,499 B | +8 B | 12,288 B |
| derived cold-cache transfer for `/c/[id]` | 303,353 B | 303,802 B | +449 B | 314,368 B |

Every row PASS; `/c/[id]` keeps 3,685 B of headroom. No ratchet entry is
needed or taken. The 441 B is the mirror's markup and the two extra copy
references; it is not `lib/plan/schema.ts`, which is why that module is not
imported here.

## The assertions that stop it regressing

**`web/e2e/plan-fallback.spec.ts`**, three tests, tagged `@cls` so they run in
the chromium project the per-PR CI job carries.

1. *the outcome* — cold-load CLS on the review pause at 1280x900 is
   `<= 0.02`, measured from before the first byte of page script with
   `buffered: true`, with every shift's sources in the failure message.
2. *the mechanism*, at 1280x900 and at 412x915 — every route chunk is held by
   the same 600 ms, which puts the fallback on screen without having to guess
   which content-hashed, minified chunk is the lazy one; then the fallback's
   box and the form's box are compared for **equality**.

Test 1 alone would not be enough. A CLS number is a measurement of a race: on
a fast enough machine the chunk can land before anything is painted and score
zero over a fallback that reserves nothing. Test 2 cannot pass that way.

All three are **red on `origin/main`**, with the numbers this file reports
printed in their failure messages:

```
cold-load CLS on the review pause is 0.05113 against 04 §8.2's 0.02 ceiling
  … sources: div.ew-thread__timeline [y 739, h 161] -> [0, 0]
at 1280x900 the fallback reserves 200px for a form that takes 586px
at 412x915 the fallback reserves 424px for a form that takes 1172px
```

**`web/tests/plan/fallback.test.tsx`**, thirteen tests, holds the half that
will actually rot — the row counts come from the plan and from `initialDraft`;
the column chrome equals `PLAN_LIST_SPECS` field by field; the field box is a
token expression and no bare pixel appears in the reservation; the mirror is
hidden from the accessibility tree, exposes no button by role, and leaves
nothing focusable. Eleven of the thirteen are red against `main`'s
`PlanEditor`; the two that are not are the `aria-busy` name and one structural
check the old fallback happened to satisfy.

jsdom has no layout engine, so the pixel claim cannot live there — which is
why it lives in Chromium, and why this file states both.

## Gate

* `npm test -- --run` — 3,527 passed over 160 files with a production build
  present, 3,518 passed / 9 skipped without one (the nine are
  `bundle.test.ts`'s build-manifest half, which skips when `.next` is absent —
  and which re-checks React Hook Form's absence from the first load against
  the bytes that actually ship, so the +441 B row above is gated too)
* `npx tsc --noEmit` — clean
* `npm run lint` — clean
* `npm run budgets` — every row PASS (table above)
* `npx playwright test --project=chromium --grep-invert @visual` — 265 passed
  / 6 skipped, plus one flake (below)
* `--project="Pixel 7" --project="iPhone 15"` — 37 passed / 4 skipped, plus
  one flake (below)
* `pytest -m "not e2e"` — 4,417 passed / 55 skipped / 34 deselected (4,054 before the rebase onto W10, which adds 363 Python tests and no web file)

Two flakes were observed once each and re-ran green, and neither renders a
plan editor:

* `keyboard.spec.ts` "the skip link moves focus into main" on `/` — 39/39
  green on `--repeat-each=3`;
* `cls.spec.ts` `@device` `thread-populated` at the Pixel 7 profile — 16/16
  green on `--repeat-each=4`. This one has measured backing: on a plain 412 px
  viewport that state's cold-load CLS ranges 0.03957-0.13614 **on `main`**,
  from `article.ew-report` reflowing as the Markdown pipeline lands. It is a
  pre-existing intermittency in a state with no `PlanEditor` on it.

## Known stale, deliberately not regenerated

The 18 `@visual` goldens under `e2e/__screenshots__/darwin/` and
`docs/images/workbench-plan-review.png` are still stale, as they have been
since S3. Both sets are darwin-only and both skip in CI. The coordinator is
sequencing **one** regeneration after this lands; regenerating here would
produce a diff that pass throws away. The chromium e2e run above therefore
excludes `@visual`.
