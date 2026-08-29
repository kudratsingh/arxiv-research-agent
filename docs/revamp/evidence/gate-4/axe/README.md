# Full-matrix axe — every state × light/dark × 320 / 412 / 1440

Produced by [WO-27](../../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence),
criterion 1:

> Full-matrix axe: every state × light/dark × 320/412/1440, zero violations,
> allowlist still empty.

- [`summary.tsv`](summary.tsv) — one row per state per theme per width, 120
  rows.
- `<state>.<theme>.<width>.json` — 120 retained reports.

---

## 1. The result

**20 states × 2 themes × 3 widths = 120 reports. 0 violations. 0 of the six
gated rules. 0 unlisted rules. `web/e2e/axe-allowlist.json` is still empty.**

| | 320 | 412 | 1440 | total |
|---|---:|---:|---:|---:|
| reports | 40 | 40 | 40 | **120** |
| violations | 0 | 0 | 0 | **0** |
| gated-rule violations | 0 | 0 | 0 | **0** |
| unlisted-rule violations | 0 | 0 | 0 | **0** |
| passing rule results | 1,576 | 1,564 | 1,648 | **4,788** |
| incomplete rule results | 26 | 8 | 0 | **34** |
| incomplete nodes | 76 | 32 | 0 | **108** |

The six rules gated at zero are the ones the retained Gate 1 baseline fails —
`landmark-one-main`, `region`, `aria-allowed-role`, `listitem`,
`color-contrast`, `page-has-heading-one`
([`04` §7.4](../../../04-ARCHITECTURE.md#74-axe-in-ci)). None of them fails
anywhere in this matrix, and `parseAllowlist` refuses to let any of the six
into the allowlist at all, so "zero" here is unqualified rather than
suppressed.

## 2. Where each leg comes from

The matrix is assembled from **two specs in one `npm run e2e` invocation**, not
duplicated across them.

| Width | Spec | Why |
|---|---|---|
| 320, 412 | `web/e2e/axe-matrix.spec.ts` (WO-27) | The two widths nothing audited before. |
| 1440 | `web/e2e/axe.spec.ts` (WO-22) | Already audits every state in both themes at exactly 1440. |

WO-22's sweep is pinned to a **1440 × 1200** window on purpose, and its header
says why: comparability with the twelve retained baseline reports "is not only
about the tag set: `color-contrast` and `landmark-one-main` both depend on what
is on screen, and a report taken at a different width can differ from the
baseline for reasons that have nothing to do with the redesign." Widening that
sweep would have traded WO-22's claim for this one; re-running it at 1440 here
would have added forty navigations and forty full-document axe runs to every CI
run for a second copy of reports that already exist.

Both legs use the same `analyze()`, the same tag set, the same six gated rules,
the same `partition()` and the same empty allowlist — a second gate with
slightly different thresholds would be two standards, and the one that mattered
would be whichever ran last.

## 3. Why the narrow legs were worth taking

Below `md` the product is **structurally a different document**, not a narrower
one: the rail is removed from the layout entirely
([`04` §8.3](../../../04-ARCHITECTURE.md#83-the-mobile-narrow-strip-repair)
repair step 1) and reached through a modal drawer instead. At 320 and 412 there
are landmarks that do not exist at 1440, a dialog that does not exist at 1440,
and a set of composited backgrounds `color-contrast` had never been measured
against.

It found a defect on the first run, and it is exactly of that kind — see §5.

The rail states (`rail-loading`, `rail-empty`, `rail-error-*`) are audited with
the **drawer open**, because at those widths the rail does not exist until the
header's disclosure button is pressed, and `WorkbenchShell` does not even mount
`ThreadRailBridge` until it is. Auditing them closed would be auditing a page
the state does not occur on. `reflow.spec.ts` does the same thing for the same
reason.

## 4. What is in each report, and what was trimmed

The Gate 3 pack retained 44 **untrimmed** reports at ~280 kB each — 12 MB —
because `resultTypes` is left at its default and `passes` therefore carries
every node axe checked. This matrix is nearly three times as large, and 36 MB
of mostly-`passes` in a docs directory is not evidence anybody can read or
diff.

So each retained report keeps the engine, the tag set, the URL, the timestamp,
the four counts, and **every violation and incomplete result in full**, and
drops the `passes` array. What that costs is the ability to re-derive a
contrast measurement for a node that PASSED — which is WO-22 criterion 4's
instrument, not this one's, and WO-22's untrimmed 1440 reports in
[`../../gate-3/axe/`](../../gate-3/axe/) still carry it. The untrimmed reports
for this sweep exist in the CI artifact (`web/build/e2e/axe/` and
`web/build/e2e/a11y/axe/`); they are not committed.

Engine and tags on every report, asserted on the run rather than declared here:
`axe-core 4.13.x`, `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa,
best-practice`.

## 5. The defect the matrix found, and the fix

`scrollable-region-focusable` — **serious**, WCAG 2.1.1 and 2.1.3 — on
`.ew-thread__timeline`, on `thread-empty` (§4 rows 5 and B) in **both themes at
320**, and nowhere else.

`.ew-thread__timeline` is `overflow-y: auto`, so it is a scroll container at
every width. With turns in it that is fine: the turn buttons are focusable
content and a keyboard user reaches the scroll by reaching them. With **no**
turns its only child is an `EmptyState`, which has no focusable descendant —
and at 320 CSS px the empty state is taller than the row. A region that
scrolls and cannot be focused.

**The width is why nothing caught it before.** WO-22's sweep audits every state
at 1440, where the empty state fits and the container does not scroll at all;
the rule is inapplicable there. It fails at 320 and passes at 412.

**Fix** (`web/components/features/ThreadTimeline.tsx`): when — and only when —
the timeline has no turns, it carries `role="region"`, `aria-label`,
`tabIndex={0}` and `ew-focusable`. That is `ScrollRegion`'s contract applied to
the element that actually scrolls rather than nested inside it, and
`role="region"` rather than a bare `tabindex` because a `div[tabindex="0"]`
with no role trips `focus-order-semantics` (best-practice, in this gate's tag
set) and cannot carry `aria-label` without tripping `aria-prohibited-attr`
either.

The populated timeline is unchanged and gains no focus stop.

**Regression test:** the four `thread-empty` rows of this matrix, which are red
on this commit without the fix.

## 6. The 108 incomplete nodes

`incomplete` is axe's "a human has to look at this", not a violation. Two rules
account for all of them, both only at the narrow widths.

### `aria-hidden-focus` — 64 nodes, 16 reports, the four rail states at 320 and 412

Targets: `.ew-shell`, `.ew-skip-link`, and Radix's own focus guards, while the
**thread drawer is open**. Radix's `hideOthers()` marks the rest of the
document `aria-hidden="true"` without `inert`, so axe finds focusable elements
inside an `aria-hidden` subtree and cannot determine whether they are reachable.

**Resolved by [`../manual/keyboard.md` §4](../manual/keyboard.md#4-mobile-drawer--trap-and-restoration).**
Twelve `Tab` presses inside the open drawer: not one stop escaped it. The
focus trap makes them unreachable, which is precisely the fact axe could not
establish on its own — and is a good illustration of why criterion 2 exists
beside criterion 1.

### `color-contrast` — 44 nodes, 18 reports, thread states at 320 only

Targets are inside `.ew-thread__turn` — the collapsed turn rows. axe returns
`incomplete` for `color-contrast` when it cannot resolve the composited
background of a node, which at 320 happens to the turn rows that are partly
outside the timeline's own scroll box. Not a measurement of a bad ratio: a
measurement axe declined to make.

Every node axe *could* measure passed: 4,788 passing rule results across the
matrix, 0 `color-contrast` violations, and
[`../../gate-3/axe/contrast-proof.tsv`](../../gate-3/axe/contrast-proof.tsv)
carries WO-22's real-render proof of the three replacement pairs.

## 7. What this does **not** claim

**No accessibility conformance.** This is 120 automated reports from one engine
in one browser. axe checks a subset of WCAG and cannot check keyboard order,
focus restoration, announcement quality or screen-reader comprehension
([`04` §7.4](../../../04-ARCHITECTURE.md#74-axe-in-ci)). Two of those four are
[`../manual/keyboard.md`](../manual/keyboard.md); the other two are
[`../manual/screen-reader.md`](../manual/screen-reader.md), **which has not been
executed**.

The matrix is also the *reachable* state table, not the whole of §4: rows 8,
11, 12, 24, 25, A, D and E have no distinct resting layout on this commit and
are accounted for in `DEFERRED_STATES` with the reason for each, which
`reflow.spec.ts` asserts partitions §4 exactly.
