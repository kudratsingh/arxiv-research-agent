# Reflow and zoom — 320 CSS px, phone landscape, 200 %, 400 %, and a very long unbroken report

Produced by [WO-27](../../../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence),
criterion 4:

> `reflow/` covers 320 CSS px, phone landscape, 200 % and 400 % zoom, and a very
> long unbroken report.

Every `.tsv` in this directory was written by `web/e2e/zoom.spec.ts` on the run
this document reports.

---

## 0. How zoom was produced, and what that does not reproduce

**SC 1.4.10 is written in CSS pixels.** "Content can be presented without loss
of information or functionality, and without requiring scrolling in two
dimensions … at a width equivalent to 320 CSS pixels", and the note is explicit
that 320 CSS px is "equivalent to a starting viewport width of 1280px wide at
400 % zoom".

Browser zoom multiplies the CSS pixel, so a 1280 px window at 400 % and a
320 px window at 100 % present the **same CSS-pixel width** to the layout. The
second is the one a headless browser can be put in deterministically, and it is
what the rows below do. Each row names the zoom level it is equivalent to and
the viewport that produces it.

**What this does not reproduce.** The other half of real zoom: the scaled-up
rasterisation of text and the sub-pixel rounding that comes with a
`deviceScaleFactor` other than 1. A user at 400 % on a 1280 px window sees the
same *layout* as these measurements and different *glyph rendering*. Nothing
here claims otherwise.

**What this adds to `reflow.spec.ts`.** WO-08's sweep is the structural guard —
`scrollWidth <= clientWidth` at 320 / 360 / 412 on every §4 state — and it
already runs. It does **not** cover landscape (where the constraint is height,
not width), the two zoom equivalences above 320, or a report whose content is a
single unbreakable token, which is the one input a `max-width` reading column
cannot defend itself against.

---

## 1. The four presentations × four surfaces

Four surfaces rather than all twenty §4 states: `reflow.spec.ts` already sweeps
the table at three widths, and repeating twenty-two states across four more
presentations would be eighty-eight navigations to re-prove one assertion.
These four are the ones where the **content** rather than the shell is the
risk — a plan editor full of textareas, a briefing with a table, a run panel
with a scrollable diagnostics table, and the composer.

Cells are `scrollWidth / clientWidth`; every one is flush, and no sample
reported an overflowing element.

| Presentation | Viewport | `landing` | `report` | `plan-review` | `running` |
|---|---|---|---|---|---|
| **320 CSS px** — SC 1.4.10's reflow width (≡ 1280 px at 400 %) | 320 × 900 | 320 / 320 | 320 / 320 | 320 / 320 | 320 / 320 |
| **Phone landscape** — a Pixel 7 rotated | 915 × 412 | 915 / 915 | 915 / 915 | 915 / 915 | 915 / 915 |
| **200 % zoom** — 1280 px window, 640 CSS px of layout | 640 × 512 | 640 / 640 | 640 / 640 | 640 / 640 | 640 / 640 |
| **400 % zoom** — 1280 px window, 320 CSS px of layout | 320 × 256 | 320 / 320 | 320 / 320 | 320 / 320 | 320 / 320 |

**16 samples, 16 flush, 0 overflowing elements.** Per-sample files are
`<presentation>.<surface>.tsv`.

The routes measured:

| Surface | Path |
|---|---|
| `landing` | `/` |
| `report` | `/c/baseline-populated` |
| `plan-review` | `/c/baseline-populated?job=baseline-plan-review` |
| `running` | `/c/baseline-populated?job=baseline-running` |

---

## 2. What makes 320 work: the rail is absent, not narrow

Asserted separately, because a future change could satisfy the width
measurement by putting the rail back and letting the page pan — which would
pass every row above and reproduce the original defect in a new form.

At 320 × 900: `data-rail-mode="drawer"`, **zero** `#workbench-rail` elements in
the document, and the labelled header button that opens the drawer is visible.
That is [`04` §8.3](../../../../04-ARCHITECTURE.md#83-the-mobile-narrow-strip-repair)
repair step 1, as a measurement.

---

## 3. A very long unbroken report

The one input a `max-width` reading column cannot defend itself against: a
token with no break opportunity in it. Reports are model output containing
URLs, DOIs, base64 fragments and arXiv identifiers, so this is a realistic
worst case rather than an adversarial one.

**Method.** The conversation read (`GET /api/conversations/baseline-populated`)
is intercepted and the **last** turn's report — the one the thread expands on
load — is replaced with:

- a **4,000-character** single unbroken token,
- a **600-character** URL,
- a Markdown table with a **400-character** unbreakable cell,

and the result is rendered through the real Markdown pipeline at **320 CSS
px**. Rewriting the wire response rather than the DOM is deliberate: the claim
is about the pipeline and the reading column together, and a `textContent`
assignment would bypass both.

**Result** ([`long-unbroken-report.tsv`](long-unbroken-report.tsv)):

| Measure | Value |
|---|---|
| `scrollWidth` | **320** |
| `clientWidth` | **320** |
| `.ew-report` `overflow-wrap` | `break-word` |
| `.ew-report` `word-break` | `normal` |
| `.ew-report` `max-width` | 670.48 px |
| widest descendant right edge | 4319 px |
| widest overflowing element | `table` @ 4319 px |

**The last two rows are the point, and they are a pass, not a failure.** The
table really is 4,319 px wide — a 400-character unbreakable cell cannot be
anything else — and **the document is still exactly 320 px.** The table
overflows inside its own `ScrollRegion` (`overflow-x: auto`, asserted), which
is the whole design: the *table* pans and the *page* does not. The 4,000-
character prose token wraps instead, because `overflow-wrap: break-word` gives
it break opportunities that a table cell's layout does not.

Both halves are asserted: the document does not pan, and the region that does
is a labelled, focusable scroll region — which is also §8 of
[`keyboard.md`](../keyboard.md), where it is reached by `Tab`.

---

## 4. Phone landscape, measured rather than assumed

Landscape is in this criterion because the constraint there is **height**, and
nothing else in the suite is short. `main` is a grid whose bottom row is a
sticky composer; on a 412 px-tall viewport the header, the composer and the
composer's own hint text could between them leave the content row with a
handful of pixels, which would be a loss of functionality at a supported
orientation (SC 1.3.4).

Measured at 915 × 412 ([`phone-landscape.geometry.tsv`](phone-landscape.geometry.tsv)):

| Measure | CSS px |
|---|---|
| viewport height | 412 |
| `header` | 51 |
| `main` | **361** |
| the landing composer's form box | 414.1 |
| the submit button's bottom edge | **399** |
| does `main` scroll vertically | **no** |

`main` keeps 361 of 412 px — 88 % of the viewport — and the submit control's
bottom edge sits at 399, thirteen pixels inside the fold. Nothing needs
scrolling to reach the primary action, and the gate asserts both: `main` is
taller than 120 px, and `Generate plan` is in the viewport.

The form's own box (414.1 px) is taller than `main` because it is the sticky
grid row plus the process strip above it; the part a user must reach is the
button, and the button is on screen. Recorded here because a reader comparing
those two numbers would otherwise reasonably ask.

---

## 5. What this pass does **not** establish

1. **Real browser zoom.** §0 — the layout is reproduced exactly, the
   rasterisation is not.
2. **Text-only zoom** (SC 1.4.4, 200 % text without resizing the viewport) is a
   different success criterion and is not measured here.
3. **The whole §4 table at these four presentations.** Four surfaces, chosen in
   §1 for the reason given. `reflow.spec.ts` covers all twenty states at
   320/360/412.
4. **Anything about the report's *content* at these widths** beyond overflow —
   whether a 4,319 px table is comfortable to read by panning is a judgement,
   and it is not made here.
5. **Non-chromium engines.** `@a11y` is chromium-only; see
   `web/playwright.config.ts`.
