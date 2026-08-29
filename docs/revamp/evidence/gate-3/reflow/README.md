# Reflow — no horizontal scroll at 320 / 360 / 412 px

Produced by [WO-26](../../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criterion 5.

- [`measurements.json`](measurements.json) — every sample, machine-readable.
- [`after/`](after/) — the settled page at each width, for the two routes the
  retained baseline captured at phone width.

---

## 1. The assertion

[`04` §8.3](../../../04-ARCHITECTURE.md#83-the-mobile-narrow-strip-repair)
states it verbatim: `document.scrollingElement.scrollWidth <=
document.scrollingElement.clientWidth`. `web/e2e/reflow.spec.ts` asserts it on
every §4 state at each of `NARROW_WIDTHS` = 320 / 360 / 412, and
`web/e2e/device.spec.ts` re-asserts a subset at the two device projects' own
widths (Pixel 7 at 412 × 915, iPhone 15 at 393 × 852).

The merged spec asserts but does not record — the numbers exist only inside
failure messages — so this directory is produced by a recorder that re-runs the
identical sweep through the same `STATES` table and the same `measureReflow()`
helper and writes down what it saw. It asserts nothing the merged spec does not
already assert.

## 2. Results — 60 samples, 0 failures

**20 states × 3 widths = 60 samples. Every one passes, and every one is exactly
flush: the maximum `scrollWidth − clientWidth` across the whole sweep is 0.**
No sample reported a `widestOverflow` element.

Cells are `scrollWidth / clientWidth`.

| State | §4 rows | Path | 320 | 360 | 412 |
|---|---|---|---|---|---|
| `landing` | 1 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `rail-loading` | 2+6 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `rail-empty` | 3 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `rail-error-upstream` | 4+F | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `rail-error-proxy-503` | F | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `thread-empty` | 5+B | `/c/baseline-empty` | 320 / 320 | 360 / 360 | 412 / 412 |
| `thread-populated` | 7 | `/c/baseline-populated` | 320 / 320 | 360 / 360 | 412 / 412 |
| `plan-review` | 9 | `/c/baseline-populated?job=baseline-plan-review` | 320 / 320 | 360 / 360 | 412 / 412 |
| `running` | 10 | `/c/baseline-populated?job=baseline-running` | 320 / 320 | 360 / 360 | 412 / 412 |
| `cancelled` | 13 | `/c/baseline-populated?job=baseline-cancelled` | 320 / 320 | 360 / 360 | 412 / 412 |
| `failed-partial` | 14 | `/c/baseline-populated?job=baseline-failed-partial` | 320 / 320 | 360 / 360 | 412 / 412 |
| `failed-no-result` | 15+23 | `/c/baseline-populated?job=baseline-failed` | 320 / 320 | 360 / 360 | 412 / 412 |
| `expired` | 16 | `/c/baseline-populated?job=baseline-expired` | 320 / 320 | 360 / 360 | 412 / 412 |
| `submission-error-500` | 17 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `rate-limited-429` | 18 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `unauthorized-401` | 19 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `validation-422` | 20 | `/` | 320 / 320 | 360 / 360 | 412 / 412 |
| `thread-not-found-inline` | 21 | `/c/baseline-not-found` | 320 / 320 | 360 / 360 | 412 / 412 |
| `route-not-found` | 22 | `/baseline-no-such-route` | 320 / 320 | 360 / 360 | 412 / 412 |
| `attached-status-unknown` | C | `/c/baseline-populated?job=baseline-running` | 320 / 320 | 360 / 360 | 412 / 412 |

The states that live in the thread rail are measured with the drawer **open**.
Below `md` the rail is not in the layout at all and `ThreadRailBridge` is not
even mounted until the drawer is asked for, so measuring those states any other
way would be measuring a page that does not contain them.

Every state is also gated against a content sentinel before it is measured —
"no horizontal scroll" is trivially true of a blank page, and that is exactly
how a responsive assertion rots into a tautology.

### The eight §4 rows that are not swept here

Rows **8**, **11**, **12**, **24**, **25**, **A**, **D** and **E** have no
resting layout to measure and are recorded in `DEFERRED_STATES` with a reason
each: row 8 is a theme *axis* rather than a layout; 11, 12 and 25 are stream
transitions asserted for behaviour in `stream.spec.ts` and `attach.spec.ts`; 24
needs two clicks after navigation and is held by
`tests/threads/confirmDialog.test.tsx`; A is a navigation, asserted end to end
as slice step 1→2; D and E are entered by *resolving* a review and are asserted
in `slice.spec.ts` step 3.

`web/e2e/reflow.spec.ts` holds the partition with a test of its own: swept ∪
deferred must equal §4 exactly, in both directions, so a row cannot be quietly
dropped and a row cannot be invented.

---

## 3. Before and after

The retained baseline captured two states at phone width. Both are 412 px wide:

| State | Before (retained Gate 1 baseline) | After |
|---|---|---|
| Landing | [`home-mobile-full.png`](../../../baseline/screenshots/home-mobile-full.png) — 412 × 915 | [`after/landing-412.png`](after/landing-412.png) |
| Populated thread | [`conversation-populated-mobile-full.png`](../../../baseline/screenshots/conversation-populated-mobile-full.png) — 412 × 1200 | [`after/thread-populated-412.png`](after/thread-populated-412.png) |

Two narrower widths are recorded for the same two routes, which the baseline
never captured:

| Width | Landing | Populated thread |
|---:|---|---|
| 320 | [`after/landing-320.png`](after/landing-320.png) | [`after/thread-populated-320.png`](after/thread-populated-320.png) |
| 360 | [`after/landing-360.png`](after/landing-360.png) | [`after/thread-populated-360.png`](after/thread-populated-360.png) |

### The work surface — the number that actually moved

| Route | Viewport | Work surface before (04 §8.3) | Work surface now | Floor (WO-08 c4) |
|---|---:|---:|---:|---:|
| `/` | 412 px | 156 px | **412 px** | ≥ 380 px |
| `/c/baseline-populated` | 412 px | 156 px | **412 px** | ≥ 380 px |

Measured on `[data-workbench-shell] .ew-shell__surface`. The surface is now the
**whole viewport**: the 256 px rail is gone from the layout below `md` rather
than merely narrowed, which `web/e2e/reflow.spec.ts`'s last test asserts
directly (`data-rail-mode="drawer"`, zero `nav` elements inside the shell, and
a labelled header disclosure as the way in).

---

## 4. The honest correction to criterion 5's premise

WO-21 criterion 5 says the sweep "fails before WO-08, passes after". **The
first half is wrong, and WO-08 said so before this work order ran** (PR #88;
the header of `web/e2e/reflow.spec.ts` records it): the sweep is green on
`1f3f45a` too, on both routes and all three widths.

The reason is worth keeping, because it is why `scrollWidth` alone is a weak
gate. `ConversationsShell.tsx:27` was `<div class="flex-1 overflow-hidden">`. A
flex item whose `overflow` is not `visible` has an automatic minimum size of
**0**, so the content column collapsed to whatever the 256 px rail left over
instead of pushing the document wider. The old shell **clipped**; it never
panned, and `scrollWidth` cannot see a clip. That is also why Lighthouse scored
98–99 on a UI whose usable content was roughly 108 px wide — the baseline
README says so in as many words.

**The measurement that actually goes red→green is the work surface**, in §3
above. The reflow sweep is kept beside it as a genuine regression guard: the
new shell is CSS Grid with `minmax(0, 1fr)`, which *can* overflow if a future
surface drops `min-w-0`, and then this sweep is the assertion that catches it.

---

## 5. Two caveats

1. **A byte-identical baseline screenshot.**
   `baseline/screenshots/failed-partial-mobile.png` is a byte-for-byte
   duplicate of `conversation-populated-mobile-full.png` — both 64,347 B, both
   MD5 `9a63f0bbda7115a5325aa4a83f8bc898`. The Gate 1 "failed-partial mobile"
   capture does not depict the failed-partial state. It is recorded here rather
   than corrected: the retained baseline is evidence already taken, and this
   work order does not edit it.
2. **`scrollWidth <= clientWidth` is not usability.** No horizontal scroll is a
   necessary condition, not a sufficient one. Reflow at 200 % and 400 % zoom,
   phone landscape, and a very long unbroken report are all WO-27's, and none of
   them is established here. See [`../known-gaps.md`](../known-gaps.md).
