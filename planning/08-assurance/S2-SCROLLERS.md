# WO-S2 — the plan editor and the briefing become reachable

Status: **DELIVERED** (branch `assurance/wo-s2-scrollers`, rebased onto
`17d2916`, which contains WO-S3)

Two of the S-series product bugs the frontend presentability survey returned,
authorised by the owner through ruling R6. This file records S2 only; S3 has
its own file (`S3-APPROVE-FAILURE.md`) and the S-series index is the
coordinator's, so two branches cannot collide on one file.

All measurements below were taken on the seeded local stack, against
`origin/main` at `17d2916` for the "before" column and this branch for the
"after" one. Taking them against `17d2916` rather than against `30d40b2`
matters: WO-S3 renders `PLAN.cancelHint` and a review-failure banner inside
the same row, so the editor is ~28px taller than the survey measured it.

## The two defects

**A — the plan editor was unreachable.** `workspace.css` capped the run row at
`14rem` whenever a run was attached. At the review pause that row holds the
plan editor, so the editor was a 994px surface inside a 223px box with no
visible scrollbar. `Approve plan` sat at y=1007 on a 900px viewport and at
y=1785 on a 915px one. The user was parked on a run that was paused and
spending nothing, with no visible way to resume or cancel it.

**B — on a phone the briefing and Export were off screen and the page did not
scroll.** The reading column was a 219px porthole over 1,235px of briefing;
`Briefing` (y=655) and `Export` (y=650) fell below the porthole's 629px bottom
edge, and `document.body.scrollHeight` was exactly 915 — the viewport. The
journey could not be finished on a phone at all.

The committed visual golden `e2e/__screenshots__/darwin/plan-review-light-412.png`
is a photograph of defect A, and `submission-error-500-light-412.png` is a
photograph of a third instance of the same cause: the landing page's own `h1`
clipped off the top of a centred overflow column that nothing could scroll.

## Root cause — one, not two

`.ew-shell` is a fixed application frame at every width: `height: 100dvh`, with
`overflow: hidden` on both `.ew-shell__main` and `.ew-shell__surface`. Inside
it the thread route nests two more scrollers — the 14rem run row and the
reading column. A fixed frame can only ever offer a nested scroller when its
content does not fit, and a nested scroller inside a page the reader has
already learned does not scroll is, in practice, a clip: the platform paints
its scrollbar only while it is moving.

Neither existing gate could see it. `reflow.spec.ts` measures the horizontal
axis, and a porthole does not pan. `axe.spec.ts` audits the accessibility
tree, and a control inside a scroll region is in the tree, focusable and
named. `cls.spec.ts` asks that things do NOT move, and the fixed box that hid
the editor is exactly what made that true.

## The fix

Where the frame fits it stays. Where it demonstrably does not, the shell stops
being a frame and becomes a document — `height: auto` with the viewport as a
floor rather than a ceiling, both clips lifted, so the page scrolls.

1. **The review pause, at every width.** `data-run` on the run row gains a
   third value, `review`, written by `ThreadTimeline` from `isReviewPause`,
   which is `ActiveRunPanel`'s own mount condition for `PlanEditor` rather
   than a copy of it — including WO-S3's third disjunct, the 409, where the
   editor stays mounted with the user's edits in it. The 14rem bound applies
   to `attached` and not to `review`, and `.ew-shell:has(…[data-run="review"])`
   puts the shell into document mode so the uncapped row has somewhere to go.
2. **Below `md`, always.** The same document mode, from the media query.

The `attached` bound is **not** lifted below `md`. That was written, measured
and reverted: see the CLS section.

## Measured, before → after

| | before | after |
|---|---|---|
| run row hidden px, 1280x900, review pause | 771 | **0** |
| run row hidden px, 412x915, review pause | 1545 | **0** |
| `Approve plan` viewport top, 1280x900 | 1007 (of 900) | 1007, page scrolls to 1873 |
| `Approve plan` viewport top, 412x915 | 1785 (of 915) | 1785, page scrolls to 2919 |
| `document.body.scrollHeight` at 412x915 | 915 (== viewport) | **1931** |
| reading column hidden px, 412x915 | 1016 | **0** |
| follow-up composer, 412x915 | fixed 286px of the viewport | in flow, scrolls with the page |
| reading column hidden px, 1280x900 | 583 | 583 (frame kept) |

## The CLS trade, stated rather than absorbed

The 14rem row is a deliberate mitigation holding 0.038 of shift, so this is a
trade and not a free win.

**Criterion 5 is unchanged.** Three checkpoints released into a live run
measure 0.00016 at 1280x900 and 0.00004 at 412x915 — identical before and
after, because a live run's row is still the bounded box. Lifting that bound
below `md` was tried: the ledger gaining its horizontal scrollbar pushed the
reading column 20px and the same measurement went to 0.01911. It was reverted,
and the reason is a comment in `workspace.css`.

**The gated cold-load measurement is unchanged.** `cls.spec.ts`'s `@device`
block, at the Pixel 7 profile, reads 0.00000 on all four audited states before
and after.

**One regression, above budget, and it is the trade.** Cold-loading a review
pause on a plain (non-mobile-emulated) 1280x900 viewport moves from 0.00000 to
**0.05113**, against 04 §8.2's 0.02. The cause is exact: at t≈203ms the thread
and the plan editor's Suspense fallback mount; at t≈231ms the lazy
`PlanEditorFields` chunk resolves, the editor grows to its real height, and
the 161px strip of reading column still visible below it is pushed off screen.
`main` absorbed that arrival by clipping the editor — which is precisely why
`Approve plan` was unreachable. **The editor's height is not known until its
chunk lands; you can hide the arrival or you can show the editor.**

The same shape, smaller, on `thread-populated` at a plain 412x915: 0.00000–
0.01254 before, 0.04515 after, from the report body reflowing as the Markdown
pipeline lands — the same reflow, previously hidden because the briefing was.

The mitigation that would close it is to size `PlanEditor`'s Suspense fallback
from the plan it already has (`sub_questions.length`, `arxiv_queries.length`)
rather than from a fixed skeleton, the way `ThreadSkeleton` sizes itself from
the loaded header's own geometry. That is a change to a surface WO-S3 has just
rewritten, and it is design work rather than layout, so it is **not** in this
PR. The number is on the record instead.

## The assertion that stops it regressing

`web/e2e/reach.spec.ts`, four tests, tagged `@reflow` so the chromium project
CI runs carries them. Three fail on `origin/main` with the numbers above
printed in the failure message; the fourth passes on both sides on purpose —
it asserts that a LIVE run at desktop width still gets the bounded row and the
fixed frame, so a future change cannot satisfy the other three by deleting
criterion 5.

Every assertion scrolls the **document** and nothing else. A locator's
`scrollIntoViewIfNeeded` would scroll the hidden inner scroller and pass
against the defect.

## Known stale, deliberately not regenerated

18 `@visual` goldens under `e2e/__screenshots__/darwin/` and
`docs/images/workbench-plan-review.png` are stale after this change, as they
already were after WO-S3. Both sets are darwin-only and both skip in CI, so
neither goes red. The coordinator is sequencing one regeneration after S2 and
S3 have both landed; regenerating here would produce a diff the next pass
throws away.
