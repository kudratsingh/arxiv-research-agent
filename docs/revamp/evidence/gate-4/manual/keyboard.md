# Keyboard walk — focus order and focus restoration

Produced by [WO-27](../../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence),
criterion 2:

> `keyboard.md` walks skip link, rail, drawer, composer, plan arrays,
> approve/revise/cancel, diagnostics disclosure, report headings/links/tables,
> export, deletion dialog, and error recovery — each with observed focus order
> **and** restoration.

**Machine-readable:** [`keyboard/`](keyboard/) — one TSV per surface, written
by `web/e2e/keyboard.spec.ts` on the run this document reports.

---

## 0. Method, and what it is not

**How every stop below was produced.** A synthesised `Tab` (or `Shift+Tab`,
`Enter`, `Escape`, `ArrowDown`) driving the real product in headless Chromium
1234 through Playwright 1.62.1, against the seeded Compose stack. Where focus
landed was then read back from `document.activeElement` for the element facts,
and from **Playwright's ARIA snapshot** for the role and the accessible name —
the real accessible-name computation, not a heuristic over `aria-label` and
`textContent`. A walk that derived the name itself would be reporting this
file's guess at the algorithm, and a name it got wrong would look like a
product defect.

**This is legitimate keyboard evidence.** The browser's own sequential focus
navigation algorithm decides where focus goes; nothing here places it. Reading
where it landed is an observation, and the whole walk is a merged gate — it
runs in CI on every PR and goes red when any of it stops being true, rather
than being a one-off recording.

**Three things it cannot establish, stated here rather than implied away:**

1. **Comprehensibility.** Whether the observed order makes sense to someone who
   cannot see the layout is a judgement, not a measurement. The order is
   recorded; §11 collects the judgements and marks them as prose.
2. **Whether the focus ring is noticeable.** The `ring` columns record that an
   indicator is painted, what it is, and which element paints it. Whether it
   stands out against the surface behind it at a real screen size is not
   measured here — [`03` §7.2](../../../03-DESIGN-BRIEF.md#72-keyboard-and-focus)'s
   ≥3:1 requirement is WO-22's contrast proof, not this walk's.
3. **Anything a screen reader does.** That is
   [`screen-reader.md`](screen-reader.md), which is a **protocol awaiting a
   human operator and has not been executed**.

**One engine, deliberately.** Sequential focus navigation genuinely differs
between engines — WebKit's `Tab` skips links unless "Press Tab to highlight
each item" is on — so a cross-engine walk would report platform policy as
product defects. The walk is `@a11y`, which
`web/playwright.config.ts` pins to chromium with that reason written on the
tag.

**Reading the tables.** `ring on` says which element paints the indicator:
`self`, its next `sibling`, or its `parent`. That column exists because of one
control — `ThemeToggle` is three native `<input type="radio">` clipped out of
the layout with the 2px ring painted on the adjacent `<span>` (`ThemeToggle.css`),
which is how the platform's arrow-key semantics are kept. Reading only
`activeElement` there reports the user agent's own `auto 1px` and calls a
correct control a defect; the first draft of this walk did exactly that.

---

## 1. The tab order — skip link → header → rail → main → composer

[`03` §7.2](../../../03-DESIGN-BRIEF.md#72-keyboard-and-focus) states the order
in those words. Observed on `/` at 1440 × 900, light:

| Stop | Role | Accessible name | Region | Ring | On |
|---|---|---|---|---|---|
| 1 | link | Skip to content | chrome | solid 2px @ 2px | self |
| 2 | radio | System | chrome (header) | solid 2px @ 2px | sibling |
| 3 | button | Collapse the rail | rail | solid 2px @ 2px | self |
| 4 | link | New research | rail | solid 2px @ 2px | self |
| 5 | link | Empty research thread | rail | solid 2px @ 2px | self |
| 6 | button | Thread actions: Empty research thread | rail | solid 2px @ 2px | self |
| 7 | link | Scientific claim verification | rail | solid 2px @ 2px | self |
| 8 | button | Thread actions: Scientific claim verification | rail | solid 2px @ 2px | self |
| 9 | textbox | Research question | main | solid 2px @ 2px | self |
| 10 | button | Generate plan | main | solid 2px @ 2px | self |

The document ends after stop 10; the eleventh press leaves the page and the
twelfth re-enters at the skip link.

Asserted, not merely tabulated: the first stop is the skip link; the **last**
rail stop precedes the **first** main stop; the header contributes exactly the
theme control (one radio, because a native radio group is one tab stop — which
is the whole reason it is three native radios rather than a roving-tabindex
imitation); and the composer's two controls are the last things in `main`.

Source: [`keyboard/landing-desktop.tsv`](keyboard/landing-desktop.tsv).

### 1.1 The order is reversible

`Shift+Tab` from stop 8 retraces stops 7 → 1 exactly. A sequence that is not
reversible is a different defect from one in the wrong order, so it is asserted
separately. Source:
[`keyboard/landing-reverse.tsv`](keyboard/landing-reverse.tsv).

### 1.2 Every stop paints an indicator

Across all eleven walks in this document, **no focus stop was observed with no
outline on itself, its next sibling or its parent.** The gate asserts it per
walk, so a control that dropped its ring would fail the surface it is on rather
than a global count. [`03` §7.2](../../../03-DESIGN-BRIEF.md#72-keyboard-and-focus):
"`outline: none` is never written without an equivalent replacement in the same
rule."

---

## 2. Skip link

- Reachable as the **first** stop with no `tabindex` — it is first in the DOM,
  which is what makes that true (`WorkbenchShell.tsx`).
- Focusing it reverses the clip: asserted with `toBeInViewport()`, because a
  skip link that stays clipped is reachable and invisible, which is the failure
  mode SC 2.4.1 is usually implemented into rather than out of.
- Activating it navigates to `#main`, and **the next `Tab` lands inside
  `<main>`** — asserted, because a skip link that moves the URL fragment
  without moving focus is the other common failure.

**Restoration:** not applicable — a skip link moves focus forward and nothing
returns.

---

## 3. Thread rail

Stops 3–8 of §1. Every row contributes two stops, and the destructive control
is one of them: the overflow menu is a real `<button>` in the tab order at full
opacity, which is the defect at `ConversationSidebar.tsx:133` that WO-14
replaced (the old control was `opacity-0` and hover-revealed).

Accessible names are indexed by thread title — `Thread actions: Empty research
thread` — so two rows never present two identically named controls.

**The rail's error state** is walked separately: with `GET /api/conversations`
answering 502, the rail renders an inline `role="alert"` whose **Retry** is
reachable by keyboard and ringed. Source:
[`keyboard/recovery-rail-error.tsv`](keyboard/recovery-rail-error.tsv).

---

## 4. Mobile drawer — trap and restoration

At 412 × 915, after the shell has resolved `data-rail-mode="drawer"`.

**Closed.** The rail is not in the layout at all
([`04` §8.3](../../../04-ARCHITECTURE.md) repair step 1), so the only route to
it is a labelled header button — asserted to be **in the tab order**, because a
drawer trigger that is not reachable makes the rail unreachable. Source:
[`keyboard/drawer-closed.tsv`](keyboard/drawer-closed.tsv).

**Open.** `Enter` on the trigger opens the dialog and moves focus **into** it —
observed landing on `Close the thread drawer`. Twelve presses over a six-stop
dialog:

| Stop | Role | Accessible name | In dialog |
|---|---|---|---|
| 1 | link | New research | yes |
| 2 | link | Empty research thread | yes |
| 3 | button | Thread actions: Empty research thread | yes |
| 4 | link | Scientific claim verification | yes |
| 5 | button | Thread actions: Scientific claim verification | yes |
| 6 | button | Close the thread drawer | yes |
| 7–12 | — | the same six, again | yes |

**Not one stop escaped the dialog**, and the cycle wraps rather than stalling.
This is one of the two surfaces
[`03` §7.2](../../../03-DESIGN-BRIEF.md#72-keyboard-and-focus) allows to trap
focus. Source: [`keyboard/drawer-open.tsv`](keyboard/drawer-open.tsv).

**Restoration.** `Escape` closes the drawer and focus returns to the control
that opened it. Verified by marking the opener with an attribute before opening
and checking `document.activeElement` carries that attribute afterwards —
compared by node identity rather than by locator, because a locator matches
again after a re-render and a restoration that landed on a *different* node
with the same selector is exactly the bug this looks for.

Worth recording: this restoration is the **shell's**, not Radix's.
`DialogContentModal` restores to `Dialog.Trigger`'s ref, and this trigger lives
in the header, outside the drawer's lazily-imported module — so a dialog opened
by anything that is not a `Dialog.Trigger` would restore focus to nothing at
all. `WorkbenchShell` records `event.currentTarget` on open and restores in a
passive effect, which lands after Radix's own layout-effect cleanup.

---

## 5. Composer

Stops 9–10 of §1, and the same two on the follow-up variant inside a thread.

- The textarea is labelled (`Research question` / `Follow-up question`) and
  carries `aria-describedby` pointing at the character counter and, over 8,000
  characters, at the refusal.
- **`Generate plan` never leaves the tab order.** Refusal is `aria-disabled` +
  `aria-busy` with a described reason, never the `disabled` attribute — so a
  keyboard user can always reach the control and hear why it will not act. The
  one place the real `disabled` attribute is used is `Cancel this run` in the
  plan editor; see §6.
- `Cmd/Ctrl+Enter` submits; bare `Enter` inserts a newline.

---

## 6. Plan editor — the arrays, and the decisions

Walked on `/c/baseline-populated?job=baseline-plan-review` at 1440.

**Order.** From the first sub-question the walk reaches, in order: each row's
textarea and its `Remove sub-question N`, then `Add sub-question`, then the
arXiv-query rows and `Add arXiv query`, then `Approve plan`, then `Cancel this
run`. The destructive decision is last. Source:
[`keyboard/plan-editor.tsv`](keyboard/plan-editor.tsv).

**Stable indexed names.**
[`03` §7.2](../../../03-DESIGN-BRIEF.md#72-keyboard-and-focus) requires them —
"`Remove sub-question 2`" — and they are observed as such: three rows, three
distinct accessible names, 1-based.

**Focus on removal.** Driven from the keyboard throughout, not by clicking:
`:focus-visible` follows the interaction modality, so a mouse-driven removal
moves focus correctly and paints no ring, and an evidence table built that way
would report a phantom "no focus ring" finding on a control that has one.

| Action | Focus after | Ring |
|---|---|---|
| Remove sub-question **2** (a middle row) | textbox "Sub-question 2" — the row that took its place | painted |
| Remove the new last row | textbox "Sub-question 1" — clamped to the row before | painted |
| Remove the only remaining row | button "Add sub-question" | painted |

Which is §7.2 exactly: "removal moves focus to the next row, or to the add
control when the list empties." Source:
[`keyboard/plan-removal.tsv`](keyboard/plan-removal.tsv).

**Approve / cancel.** Both reachable, both ringed, in that order. `Approve
plan` carries `aria-describedby` pointing at the billing sentence. `Cancel this
run` carries a visible hint ("Nothing will be searched.").

**One inconsistency, recorded rather than fixed.** The remove/add controls and
`Cancel this run` use the real `disabled` attribute while a decision is in
flight, so they leave the tab order; the primary submit uses `busy` →
`aria-disabled` and stays in it. Both behaviours are defensible and the `Button`
primitive's own doctrine is the second one. It is not a WCAG failure — nothing
becomes unreachable that was reachable and still actionable — so it is reported
here rather than changed under a Gate 4 work order. **Owner: WO-17.**

---

## 7. Diagnostics disclosure

Walked on `/c/baseline-populated?job=baseline-running` at 1440.

- **Collapsed by default**, with `aria-expanded="false"`, and the `role="log"`
  region **hidden** — asserted, and see §7.1.
- `Enter` on the trigger expands it and **leaves focus on the trigger**. The
  panel is the next tab stop, not a focus steal.
- The panel's stops, in order: `region "Diagnostics table"` — a real focus stop,
  on purpose, because a scroll region a keyboard user cannot scroll is a region
  they cannot read (SC 2.1.1) — then `button "Copy diagnostics"`.
- `Escape` does **not** close it. That is the APG behaviour for a disclosure
  and is asserted so the evidence does not imply otherwise.

Source: [`keyboard/diagnostics.tsv`](keyboard/diagnostics.tsv).

### 7.1 The defect this walk found

On this commit before the fix, `aria-expanded="false"` and the panel was on
screen: displayed, its two controls in the tab order, and its `aria-live`
region announcing every SSE frame.

`Disclosure` hides its panel with the `hidden` attribute, which works through
the user-agent stylesheet's `[hidden] { display: none }`. **The cascade
resolves origin before specificity**, so any author `display` declaration beats
it — including one utility class. `Diagnostics` passes `panelClassName="flex
flex-col gap-3"`.

Consequences, all three real: a third announcing live region where
[`03` §7.3](../../../03-DESIGN-BRIEF.md#73-live-regions) allows two; an
`aria-expanded` that was not true (SC 4.1.2); and two extra tab stops on a
surface that claimed to be collapsed.

**axe reports nothing for this** — there is no rule for "`aria-expanded`
disagrees with what is displayed" — so WO-22's sweep and WO-27's own full
matrix were green over it in both themes at all three widths. It took pressing
Tab and looking.

Fixed in `primitives.css` (`.ew-disclosure-panel[hidden] { display: none }`,
specificity (0,2,0)) plus the class in `Disclosure.tsx`, so every caller is
covered and not just the one that was caught. Regression tests in
`web/tests/primitives/Disclosure.test.tsx`, which assert both directions —
`display: none` when closed under a caller's `flex`, and `display: flex` when
open, so the fix cannot degrade into ignoring `panelClassName`.

It also made a merged assertion honest: `stream.spec.ts` was waiting for the
diagnostics wording *"connection interrupted; browser is retrying"* to be
**visible**, which it only ever was because of this defect. It now asserts the
narration a user actually gets — the spine's single `role="status"`,
*"Reconnecting. Checkpoints during the gap are not replayed."* — and asserts
the diagnostics note separately as a hidden record.

---

## 8. Report — headings, links and tables

Walked on `/c/baseline-populated` at 1440.

- The **section rail** (`nav "Sections"`) is derived from the briefing's own
  `h2`/`h3` nodes ([`03` §5](../../../03-DESIGN-BRIEF.md)) and is the keyboard
  route to a heading. Its anchors are reachable, and `Enter` on one moves the
  URL to that heading's fragment.
- Every Markdown **table** is wrapped in a focusable, labelled scroll region —
  `region "Table 1 in this briefing"` — so a table wider than the reading
  column can be panned without a pointer (SC 2.1.1) and without the document
  panning (SC 1.4.10). Focusing one is asserted directly.
- Code blocks get the same treatment (`Code block N in this briefing`).
- Links inside the briefing are ordinary anchors in document order.

Source: [`keyboard/report.tsv`](keyboard/report.tsv).

**A structural observation, not fixed here.** A populated thread has **two
`<h1>` elements**: the page's own (the thread title) and the briefing's
Markdown `#`, which renders inside a `region` whose heading is an `h2`. The
document therefore goes h1 → h2 → h1 → h2. axe reports nothing, because
`heading-order` only flags *increases* of more than one, and the design says so
deliberately — the type scale has a `report-h1` step and
[`03` §5](../../../03-DESIGN-BRIEF.md) defines the section rail as "derived from
the report's own `h2`/`h3` nodes", which is also why the briefing's own title
never appears in that rail.

This is a **design ruling, not a bug**, and changing it would reopen WO-18 on a
specified behaviour rather than fix a defect — so WO-27 reports it instead of
patching it. It is exactly the sort of thing a listener settles: it is carried
into [`screen-reader.md` §6](screen-reader.md#6-known-structural-findings-to-check-by-ear)
as a question for the operator's rotor.

---

## 9. Export

Walked on `/c/baseline-populated` at 1440.

- `Enter` on **Export** expands it (`aria-expanded` flips) and the panel's three
  links follow in order: **Markdown**, **PDF**, **Word**. All three ringed.
- **`Escape` inside the panel closes it and returns focus to the Export
  trigger** — verified by node identity, as in §4.
- `ArrowDown` opens the panel and moves into it, and `Escape` restores again.
  The arrows are an **addition** to `Tab`, not a replacement: the links are
  still ordinary tab stops.

Source: [`keyboard/export.tsv`](keyboard/export.tsv).

---

## 10. Deletion dialog

Reached entirely by keyboard from `/` at 1440.

1. `Enter` on a row's `Thread actions: …` opens the menu and moves focus to
   `menuitem "Open thread"` — the roving focus RC-09 kept the `Menu` primitive
   for, on the one control in the product that really is a menu.
2. `ArrowDown` → `menuitem "Delete thread"`. `Enter` opens the dialog.
3. **The dialog opens with focus on `Cancel`, not on the destructive control** —
   asserted, because a stray `Enter` on an accidental open must not delete a
   thread.
4. Eight `Tab` presses: **not one escaped the dialog.** The other of the two
   surfaces §7.2 allows to trap focus.
5. `Escape` closes it and focus returns to the row's overflow menu — again by
   node identity.

Source: [`keyboard/delete-dialog.tsv`](keyboard/delete-dialog.tsv).

Worth recording: this restoration is `ThreadList`'s, not Radix's, and it has a
second branch the walk does not exercise — when the thread was actually
deleted, the opener is gone from the document and focus goes to
`[data-thread-rail-new]` instead. That branch is covered by
`web/tests/threads/confirmDialog.test.tsx`; reaching it here would require a
destructive mutation against the seeded fixtures.

---

## 11. Error recovery

Three surfaces, each walked and each asserted to offer a focusable recovery
**inside `<main>`** — a recovery surface a keyboard user cannot act on is a
dead end — and to keep the shell around it, so the rail is still a way out.

| Surface | Path | Recovery reached |
|---|---|---|
| Route not found | `/baseline-no-such-route` | link "Start a new question" |
| Thread not found (inline) | `/c/baseline-not-found` | the product 404's primary action |
| Rail read failure (502) | `/` with `GET /api/conversations` → 502 | button "Retry", inside the rail's `role="alert"` |

Sources: [`keyboard/recovery-route-not-found.tsv`](keyboard/recovery-route-not-found.tsv),
[`keyboard/recovery-thread-not-found.tsv`](keyboard/recovery-thread-not-found.tsv),
[`keyboard/recovery-rail-error.tsv`](keyboard/recovery-rail-error.tsv).

---

## 12. Judgements — prose, marked as prose

Everything above is measured. These are not.

1. **The order reads correctly.** Skip link, one theme control, the rail
   top-to-bottom, then the work surface. Nothing doubles back and nothing is
   reached out of visual order.
2. **The rail is long on a real workspace.** Two seeded threads produce four
   stops; a hundred threads produce two hundred, and the skip link is the only
   way past them. That is standard and is what the skip link is for, but a
   second skip target ("skip the thread list") would be a reasonable future
   improvement. Not a defect; not scheduled.
3. **The two focus traps behave.** Both trap, both cycle, both restore, and
   both restore to the element the user left — including the drawer, whose
   trigger is outside the dialog's own module and which therefore had to be
   done by hand.
4. **The plan editor's array is the strongest surface here.** Indexed names and
   correct post-removal focus are the two things this class of control usually
   gets wrong, and both are right.
5. **The scroll regions are the most surprising.** A long briefing puts a
   focus stop on every table and every code block. That is correct — they are
   scrollable and must be operable — but it means a reader tabbing through a
   report meets stops that do nothing visible. Nothing to fix; worth knowing
   before the screen-reader session.

---

## 13. What is still owed

- **Criterion 3 is not met.** [`screen-reader.md`](screen-reader.md) is a
  prepared protocol and has **not been executed**. Nothing in this file
  substitutes for it.
- The walk is chromium-only (§0).
- The three surfaces in §11 are the reachable recovery states; the global error
  boundary (`app/global-error.tsx`) replaces `<html>` and cannot be reached from
  a seeded fixture. Its keyboard behaviour is covered by
  `web/tests/shell/recovery.test.tsx`.
