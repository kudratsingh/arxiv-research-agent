# Reduced motion, and forced colours

Produced by [WO-27](../../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence),
criteria **5** and **6**.

- Criterion 5 — "`reduced-motion.md` confirms no status meaning is motion-only
  and that live regions do not announce every frame — the test
  [`03` §3.7](../../../03-DESIGN-BRIEF.md#37-motion) says the policy must
  pass."
- Criterion 6 — "A forced-colors pass on the trace spine and status marks
  (RC-17)."

They are one file because they are one question asked twice.
[`03` §3.4](../../../03-DESIGN-BRIEF.md#34-status-is-never-colour-alone) ranks
the channels a status is carried on — "a distinct word, a distinct mark shape
and a colour, in that order of precedence" — and each criterion removes one of
them and asks whether the information survived.

**Machine-readable:** [`motion/`](motion/) and
[`forced-colors/`](forced-colors/), written by `web/e2e/motion.spec.ts` on the
run this document reports.

---

## 0. Method, stated before any result

Every number below was measured in headless **Chromium 1234 / Playwright
1.62.1**, against the seeded Compose stack (`web/e2e/support/stack.sh`,
`web/e2e/fixtures/seed.sh`), by `web/e2e/motion.spec.ts` — which is a merged
gate, not a one-off recorder: it runs in CI on every PR and goes red if any
claim here stops being true.

`prefers-reduced-motion` is applied with `page.emulateMedia({ reducedMotion:
"reduce" })` and forced colours with `page.emulateMedia({ forcedColors:
"active" })`. Neither is a simulation of the media query: §3 below **proves**
the second one replaces author colours rather than merely matching the query,
because a forced-colours pass that only matched the query would be a green tick
over an unforced page.

**Chromium only, and why.** `forcedColors` emulation is a Chromium capability;
Firefox and WebKit match the media feature and force nothing, so a
cross-engine sweep would pass without measuring anything. That is the same
reason `@cls` is pinned to chromium in `web/playwright.config.ts`, and the tag
carries the same note.

---

## 1. Criterion 5 — the durations collapse

[`03` §3.7](../../../03-DESIGN-BRIEF.md#37-motion): "Under `@media
(prefers-reduced-motion: reduce)` all transition and animation durations become
1ms."

Read off `:root` in a real render on `/c/baseline-populated?job=baseline-running`
with the diagnostics disclosure open — deliberately, because the only
transform transition on the route lives on its chevron and a sweep of the
resting page would report "nothing moves" and mean "nothing was mounted".

| Token | no-preference | reduce |
|---|---|---|
| `--duration-fast` | 120ms | **1ms** |
| `--duration-base` | 160ms | **1ms** |
| `--duration-slow` | 240ms | **1ms** |
| `--duration-ambient` | 2400ms | **1ms** |

Source: [`motion/durations.tsv`](motion/durations.tsv).

## 2. Criterion 5 — nothing is left moving, and nothing is lost

### 2.1 What was moving, and what stopped

Every element on the route whose composited `animation-duration` or
`transition-duration` exceeds 1.5 ms — the threshold sits just above the
policy's own 1 ms so that a collapsed duration does not read as motion.

| Condition | Elements still moving |
|---|---|
| `no-preference` | **13** |
| `reduce` | **0** |

The premise is asserted as well as the conclusion: if nothing moved in the
first condition the second would be vacuous, so the spec fails when the
`no-preference` count is zero.

The thirteen are, by kind: colour transitions on `Button`, `Textarea` and
`Disclosure` triggers (`transition-colors duration-fast`), the disclosure
chevron's `transform` at `--duration-base`, two `.ew-enter` opacity entrances
on disclosure panels at `--duration-base`, and the one looping animation in the
product — `.ew-pulse`, `--duration-ambient`, opacity only, attached to the
`Live` mark. Full list, both conditions:
[`motion/moving-elements.tsv`](motion/moving-elements.tsv).

`.ew-pulse` is disabled outright rather than collapsed
(`components/primitives/primitives.css`), because a 1 ms *infinite* pulse is a
flicker rather than a still mark. The spec asserts its computed
`animation-name` is `none` under reduced motion, with the word *Live* and the
`ring` mark both still painted — which is
[`03` §3.7](../../../03-DESIGN-BRIEF.md#37-motion)'s "a static filled mark plus
the word *Live*", as a measurement.

### 2.2 No status meaning is motion-only

The trace spine's four segments, read in both conditions. The assertion is an
**equality**: the segment name, its `data-status`, its `data-mark` shape and
its full text are identical with motion allowed and with motion removed.

| Segment | `data-status` | Mark | Painted | Word channel |
|---|---|---|---|---|
| Question | `observed` | `circle` | yes | "Question · observed" + the visible word *observed* |
| Plan | `not-observed` | `dashed-rule` | yes | "Plan · not observed" + *not observed* |
| Run | `not-observed` | `dashed-rule` | yes | "Run · not observed" + *not observed* |
| Report | `not-observed` | `dashed-rule` | yes | "Report · not observed" + *not observed* |

Identical in both conditions. Source:
[`motion/status-channels.tsv`](motion/status-channels.tsv).

The one status the spine **draws** rather than writes is the blind-spot void
(`03` §5.8): a dashed top rule that becomes **dotted** when the observation is
stale. `spine.css` says it in as many words — "a break is a shape" — and the
measurement confirms the shape is unchanged under reduced motion:
`border-top-style: dotted`, `border-top-width: 2px`, in both conditions. The
void has no animation and no transition in any media condition, which
`web/tests/patterns/TraceSpine.test.tsx` already asserts mechanically.

**So removing motion removes no information.** That is the test
[`03` §3.7](../../../03-DESIGN-BRIEF.md#37-motion) asks for, and it passes.

## 3. Criterion 5 — live regions do not announce every frame

The second half of criterion 5, and the one that needs a denominator.

**Method.** A `MutationObserver` is installed over every `[role="status"]`,
`[role="alert"]`, `[role="log"]` and `[aria-live]` element **before
navigation**, so a region that appears mid-stream is watched from its first
paint. The stream for `baseline-running` is then served as a burst of **40 real
`node_completed` frames** (`{ node, state_delta }`, the shape
`lib/api/events.ts` pins from the backend). A seeded row cannot supply a burst
— nothing is driving it, so it delivers no checkpoints at all and the region
would trivially say one thing forever.

**Result.**

| Region | Text changes over 40 frames |
|---|---|
| the single `role="status"` (the spine's announcement line) | **2** |
| the single `role="alert"` (`StatusBanner`, user-triggered only) | **0** |
| the diagnostics `role="log"` — collapsed by default | 2 |

The frames arrived: the diagnostics ring reported **42** records held — the 40
checkpoints plus the client's own transport notes for the connection opening
and for the interruption that ends the burst.

The two things the status region said, in order:

> Rejoined this run. Earlier checkpoints are not replayed.
>
> Reconnecting. Checkpoints during the gap are not replayed.

Two **material transitions** — attaching to a run already in progress, and the
connection dropping — over forty checkpoints. Not one of the forty produced an
announcement.

Source: [`motion/live-regions.tsv`](motion/live-regions.tsv), which lists every
sample with its timestamp.

**Why this is the right shape and not luck.** The checkpoint count and the
run's age live **outside** the status region, in a sibling marked
`data-spine-part="detail"` (`TraceSpine.tsx`). That separation is what makes
per-frame churn unannounceable rather than merely unlikely: the region's text
is `model.announcement` and nothing else. The spec asserts the count is ≤ 5
rather than exactly 2 — the claim is the order of magnitude, and a golden
number would go red the day a legitimate transition is added.

**The gate also asserts the census.** Every live region observed over the run
is one of the three above; a fourth would fail the test.
[`03` §7.3](../../../03-DESIGN-BRIEF.md#73-live-regions) allows exactly two
product-wide plus the collapsed log.

### 3.1 A defect this measurement depended on, and the fix

The diagnostics `role="log"` is tolerated as a third live region **only**
because its disclosure is collapsed by default and a collapsed panel is
`hidden`. It was not.

`Disclosure` renders its panel as `<div hidden={!isOpen}
className={cx(..., panelClassName)}>`, and `hidden` hides through the
user-agent stylesheet's `[hidden] { display: none }`. **The cascade resolves
origin before specificity**, so any author declaration of `display` beats it
outright — including a single utility class. `Diagnostics` passes
`panelClassName="flex flex-col gap-3"`.

The collapsed panel was therefore displayed, its controls were in the tab
order, and its live region was live and announcing every frame — a third
announcing region where §7.3 allows two, under a trigger reporting
`aria-expanded="false"`.

**axe cannot see this.** There is no rule for "`aria-expanded` disagrees with
what is displayed", so WO-22's sweep and WO-27's own full matrix were green
over it in both themes at all three widths. It was found by pressing Tab and
watching where focus went ([`keyboard.md` §7](keyboard.md#7-diagnostics)).

Fixed in `components/primitives/primitives.css` with
`.ew-disclosure-panel[hidden] { display: none }` — specificity (0,2,0), which
no single utility class can outrank — plus the class on the panel in
`Disclosure.tsx`, so the policy covers every caller and not only the one that
was caught. Regression tests: `web/tests/primitives/Disclosure.test.tsx`
("a closed panel stays closed under a caller's layout class"), which computes
`display: none` on a hidden panel whose caller passed `flex` **and** `display:
flex` on the same panel once open, so the fix cannot degrade into ignoring
`panelClassName`.

---

## 4. Criterion 6 — the forced-colours pass

### 4.1 First, that the emulation is real

A synthetic `<p>` with author colours, measured under
`emulateMedia({ forcedColors: "active" })`:

| Property | Author value | Composited value |
|---|---|---|
| `color` | `red` | `rgb(0, 0, 0)` — `CanvasText` |
| `background-color` | `lime` | `rgb(255, 255, 255)` — `Canvas` |
| `border-top-color` | `blue` | `rgb(0, 0, 0)` |
| `border-top-style` | `dashed` | `dashed` — **unchanged** |

Source: [`forced-colors/emulation-proof.tsv`](forced-colors/emulation-proof.tsv).

Author colours are replaced; border **style** is not. That second row is why
the spine's dashed/dotted void keeps meaning something in this mode, and it is
asserted rather than assumed.

### 4.2 The spine and the status marks

Measured in both of Chromium's forced palettes.

| Palette | `Canvas` | `CanvasText` |
|---|---|---|
| light | `rgb(255, 255, 255)` | `rgb(0, 0, 0)` |
| dark | `rgb(0, 0, 0)` | `rgb(255, 255, 255)` |

For every segment, in both palettes:

- **the word survives** — the segment's text still contains its status word,
  asserted against `data-status` rather than against a string typed here;
- **the shape survives** — `data-mark` is present and the mark's box is
  non-zero;
- **the hue does not survive** — every painted `[data-mark]` is now one of the
  reader's palette colours, not one of the product's;
- the void's `border-top-style` is still `dashed`/`dotted` with a non-zero
  width.

Sources: [`forced-colors/spine.light.tsv`](forced-colors/spine.light.tsv),
[`forced-colors/spine.dark.tsv`](forced-colors/spine.dark.tsv).

After the fix in §4.3, in the light forced palette:

| Segment | `data-status` | Mark | Painted | Mark colour |
|---|---|---|---|---|
| Question | `observed` | `circle` | 16×16 | `rgb(0, 0, 0)` — `CanvasText` |
| Plan | `not-observed` | `dashed-rule` | 16×16 | `rgb(0, 0, 0)` |
| Run | `not-observed` | `dashed-rule` | 16×16 | `rgb(0, 0, 0)` |
| Report | `not-observed` | `dashed-rule` | 16×16 | `rgb(0, 0, 0)` |

and the void: `border-top-style: dotted`, `border-top-color: rgb(0, 0, 0)`.

The `Live` badge's `ring` mark comes back as `rgb(0, 0, 159)` — `LinkText`
rather than `CanvasText` — because it sits inside a link and `color: inherit`
takes whatever its parent was forced to. That is the reason the fix inherits
rather than naming a system colour: hard-coding `CanvasText` would have made
the one mark in a link the wrong colour for its context.

### 4.3 Defect A — the status marks opted out of the reader's palette

**Found and fixed in this PR.**

Chromium's user-agent stylesheet puts `forced-color-adjust:
preserve-parent-color` on SVG content, which means "take the parent's
already-forced colour". A `<svg>` carrying its **own** `color` declaration —
which every `Mark` does, through the tone class that gives it its hue — has
nothing to inherit and keeps the author value.

Measured on this commit before the fix, in the **light** forced palette
(`Canvas` white, `CanvasText` black):

| Mark | Class | Composited colour | Should have been |
|---|---|---|---|
| `circle` (Question · observed) | `text-signature-text` | `rgb(16, 102, 106)` | `CanvasText` |
| `dashed-rule` (Plan / Run / Report · not observed) | `text-ink-faint` | `rgb(90, 115, 123)` | `CanvasText` |

and in the **dark** forced palette (`Canvas` black, `CanvasText` white):

| Mark | Class | Composited colour |
|---|---|---|
| `circle` | `text-signature-text` | `rgb(88, 199, 194)` |
| `dashed-rule` | `text-ink-faint` | `rgb(140, 165, 172)` |

Every *word* beside them was correctly forced. Only the marks were not.

**Why it matters even though those particular values are legible.** Chromium's
emulated palettes are two of an unbounded set: a forced-colors palette is the
reader's, chosen in their OS, and it can be any pair of colours. A shape drawn
in a hue the product picked is precisely what the mode exists to prevent, and
§3.4 makes the mark the second of three channels — it has to work when the
third is gone.

**Fix.** `components/primitives/primitives.css`:

```css
@media (forced-colors: active) {
  svg[data-mark] {
    color: inherit;
  }
}
```

`color: inherit` rather than `CanvasText`, because §3.4 makes the mark the
redundant channel *beside its word* — so the right forced colour is whatever
that word ended up being: `CanvasText` in the spine, `LinkText` inside a link,
the button's forced colour inside a button. Inheriting gets all three right and
hard-codes none of them. `svg[data-mark]` rather than a bare `[data-mark]`
because (0,1,1) beats the (0,1,0) of the Tailwind tone utility regardless of
which stylesheet Next injects last.

**Regression tests.** `web/e2e/motion.spec.ts` — "the spine keeps its word and
its shape in the {light,dark} forced palette", which fails on this commit
without the rule — plus `web/tests/primitives/policy.test.tsx`, which asserts
the rule's presence, its `color: inherit`, its element+attribute specificity,
and that every `Mark` still renders an `svg[data-mark]` for it to match.

### 4.4 Defect B — the selected theme was invisible in forced colours

**Found and fixed in this PR.**

`ThemeToggle` distinguishes the chosen theme with `background-color:
var(--color-primary)` on the label span, and nothing else — no border, no
weight change, no underline. Forced colours replaces every author background
with `Canvas`. Measured in the light forced palette before the fix:

| Option | Checked | `color` | `background-color` |
|---|---|---|---|
| light | no | `rgb(0, 0, 0)` | `rgba(255, 255, 255, 0)` |
| dark | no | `rgb(0, 0, 0)` | `rgba(255, 255, 255, 0)` |
| system | **yes** | `rgb(0, 0, 0)` | `rgb(255, 255, 255)` |

White on a white `Canvas` against transparent on the same `Canvas`: the three
options were indistinguishable, and which theme was selected was not
represented at all. SC 1.4.1.

**Fix.** `components/patterns/ThemeToggle.css`:

```css
@media (forced-colors: active) {
  .ew-theme-option input:checked + span {
    background-color: Highlight;
    color: HighlightText;
  }
}
```

System colour keywords are the exception to the replacement — a value the
author already wrote as a system colour is honoured — and `Highlight` /
`HighlightText` is the pair the platform guarantees to be a legible selection
in whatever theme the reader chose. That is why the fix is two declarations and
**not** `forced-color-adjust: none`, which would keep the product's own hues
and defeat the mode outright.

Post-fix measurement
([`forced-colors/theme-control.tsv`](forced-colors/theme-control.tsv)):

| Option | Checked | `color` | `background-color` |
|---|---|---|---|
| light | no | `rgb(0, 0, 0)` | `rgba(255, 255, 255, 0)` |
| dark | no | `rgb(0, 0, 0)` | `rgba(255, 255, 255, 0)` |
| system | **yes** | `rgb(255, 255, 255)` — `HighlightText` | `rgba(5, 0, 73, 0.8)` — `Highlight` |

The selected option is now the only one painted in the reader's own selection
colours, and the spec asserts the pair is distinct from every unselected
option's rather than asserting the two keywords resolved to anything in
particular — a reader whose `Highlight` happens to equal their `Canvas` would
still be a failure, and the assertion catches it.

**Regression tests.** `web/e2e/motion.spec.ts` — "the theme control's selected
option is visible in forced colours" — plus
`web/tests/shell/themeToggle.test.tsx`, which asserts the rule names system
colours, does not reach for `forced-color-adjust`, and that the selector
`input:checked + span` still matches what the component renders.

---

## 5. What this pass does **not** establish

1. **That a reader can see it.** Every claim here is a composited-style
   measurement. Whether the resulting contrast is comfortable at a real screen
   size, in a real high-contrast theme, for a real person, is not measured and
   is not claimed.
2. **Any palette other than Chromium's two.** The forced palettes above are the
   ones Chromium emulates. A Windows High Contrast theme with a user-chosen
   pair was not tested; the fixes are written so that whatever the pair is, the
   product uses it rather than its own.
3. **Firefox and WebKit under forced colours.** Neither implements the
   emulation, so neither was swept. The fixes are pure CSS with no
   engine-specific mechanism.
4. **That the announcements are comprehensible.** §3 counts region changes and
   quotes their text. Whether a screen reader speaks them well, and whether a
   listener understands the result, is
   [`screen-reader.md`](screen-reader.md) — which is a protocol awaiting a
   human operator and **has not been executed**.
5. **Motion beyond the two routes swept.** `/` and `/c/[id]` carry every
   animation the product has (three keyframes and one transition, all
   inventoried by `web/tests/primitives/policy.test.tsx`), but the sweep itself
   visits the run route only.
