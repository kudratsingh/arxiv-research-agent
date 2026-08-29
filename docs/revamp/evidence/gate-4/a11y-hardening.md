# Gate 4 — accessibility hardening and the manual-evidence pack

Produced by [WO-27](../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence)
on branch `feat/wo-27-a11y-hardening`, against the seeded local Compose stack
(`web/e2e/support/stack.sh`, `web/e2e/fixtures/seed.sh`) in headless Chromium
through Playwright 1.62.1.

**Unlike the Gate 3 pack, this work order is allowed to fix things, and did.**
Criterion 7 says so: "Any defect found is fixed **in this PR**, with its
regression test." Four defects were found and fixed; they are listed in §2 with
the test that holds each one.

**This pack claims no accessibility conformance.** See §4.

---

## 1. The seven criteria

| # | Criterion | Verdict | Where |
|---|---|:-:|---|
| 1 | Full-matrix axe: every state × light/dark × 320/412/1440, zero violations, allowlist still empty | ✅ **PASS** | [`axe/README.md`](axe/README.md) — 120 reports, 0 violations, 0 gated, allowlist empty |
| 2 | `keyboard.md` walks eleven surfaces, each with observed focus order **and** restoration | ✅ **PASS** | [`manual/keyboard.md`](manual/keyboard.md) — 13 walks, scripted-keyboard method stated |
| 3 | `screen-reader.md` transcribes VoiceOver + Safari (macOS and iOS) and NVDA + Firefox | ❌ **NOT DONE** | [`manual/screen-reader.md`](manual/screen-reader.md) — **protocol only, awaiting a human operator** |
| 4 | `reflow/` covers 320 CSS px, phone landscape, 200 % and 400 % zoom, and a very long unbroken report | ✅ **PASS** | [`manual/reflow/README.md`](manual/reflow/README.md) — 16 samples flush, plus the unbroken-token case |
| 5 | No status meaning is motion-only; live regions do not announce every frame | ✅ **PASS** | [`manual/reduced-motion.md` §1–3](manual/reduced-motion.md) — 13 moving elements → 0; 2 status changes over 40 frames |
| 6 | A forced-colors pass on the trace spine and status marks (RC-17) | ✅ **PASS** | [`manual/reduced-motion.md` §4](manual/reduced-motion.md#4-criterion-6--the-forced-colours-pass) — after two fixes |
| 7 | Any defect found is fixed **in this PR**, with its regression test | ✅ **PASS** | §2 below |

**Six of seven pass. Criterion 3 is not met and is a Gate 4 blocker.**

### Criterion 3, stated plainly

WO-27 was executed by an automated agent on macOS. **NVDA does not run on
macOS**, and a VoiceOver transcript cannot be synthesised — VoiceOver's speech
is produced by the platform from the accessibility tree plus its own verbosity,
punctuation and rotor state, and the tree is the *input* to a screen reader,
not its output. Writing out what a screen reader "would have said" would be a
fabrication in the shape of evidence.

So [`manual/screen-reader.md`](manual/screen-reader.md) is a **prepared
protocol**: three environments, three scenarios (the plan-review decision, a
reconnect announcement, a terminal outcome), exact steps, what a pass sounds
like, blank transcription blocks and a verdict table per scenario. Every
transcription block is empty and must stay empty until a person has run it.

**Gate 4 does not close on this criterion until a human executes it.**

---

## 2. Criterion 7 — the four defects found and fixed

| # | Defect | Found by | Fix | Regression test |
|---|---|---|---|---|
| 1 | **A collapsed `Disclosure` was not collapsed.** `hidden` hides via the UA sheet's `[hidden] { display: none }`; the cascade resolves origin before specificity, so `Diagnostics`' `panelClassName="flex flex-col gap-3"` beat it. The panel was displayed, its two controls were in the tab order, and its `role="log" aria-live` region was **live and announcing every SSE frame** under a trigger reporting `aria-expanded="false"` — a third live region where [`03` §7.3](../../03-DESIGN-BRIEF.md#73-live-regions) allows two, and SC 4.1.2. | criterion 2, the keyboard walk | `.ew-disclosure-panel[hidden] { display: none }` in `primitives.css` (specificity (0,2,0)) + the class in `Disclosure.tsx`, so **every** caller is covered | `web/tests/primitives/Disclosure.test.tsx` — asserts both directions: `display: none` closed under a caller's `flex`, `display: flex` open |
| 2 | **Status marks opted out of the reader's forced palette.** Chromium puts `forced-color-adjust: preserve-parent-color` on SVG; a `<svg>` with its own `color` (every `Mark`, via its tone class) keeps the author hue while every word beside it is forced. Measured in both palettes. | criterion 6 | `@media (forced-colors: active) { svg[data-mark] { color: inherit } }` in `primitives.css` | `web/e2e/motion.spec.ts` (both palettes, red without the rule) + `web/tests/primitives/policy.test.tsx` |
| 3 | **The selected theme was invisible in forced colours.** The `:checked` state is a background tint and nothing else; forced colours replaces every author background with `Canvas`, so all three options measured identically. SC 1.4.1. | criterion 6 | `@media (forced-colors: active)` → `background-color: Highlight; color: HighlightText` in `ThemeToggle.css` | `web/e2e/motion.spec.ts` + `web/tests/shell/themeToggle.test.tsx` |
| 4 | **`scrollable-region-focusable` (serious, SC 2.1.1/2.1.3)** on `.ew-thread__timeline` for an **empty** thread at **320 only**: the container scrolls and its only child, an `EmptyState`, has no focusable descendant. Invisible at 1440, where the rule is inapplicable. | criterion 1, the narrow legs | the empty timeline carries `role="region"` + `aria-label` + `tabIndex={0}` + `ew-focusable`; the populated one is unchanged | the four `thread-empty` rows of the matrix, red without the fix |

### Two more things this branch repaired, outside the seven criteria

| Item | What | Why it is here |
|---|---|---|
| **Six story play functions** — `known-gaps.md` §2d / headline item 14 | Three `ThreadRail` overlay stories raced a Radix enter transition (`toBeVisible()` beside a `findBy*`); three `Shell` stories looked for the rail at 320 and 412, where the product deliberately has none. 48 of 3,915 render-matrix combinations. | The WO-27 brief names it. Group 1 now retries the visibility check; group 2 branches on [`web/.storybook/storyRail.ts`](../../../web/.storybook/storyRail.ts) and asserts something true in **both** presentations rather than skipping. |
| **`stream.spec.ts`'s flaky assertion** — `known-gaps.md` §2 / headline item 9 | `expect(stream.opens()).toBe(1)` conflated the browser's own `EventSource` retry (the behaviour being confirmed) with a client-initiated second open (the behaviour being forbidden). 3 failures in 12 runs, and defect 1 above made it worse by lengthening the wait. | The two are separated by **time**, not by count. `StreamInterceptor` now records open timestamps and the assertion is on the gaps against `RACE_FLOOR_MS`. 12/12 green on chromium, 6/6 on firefox + webkit. |

`stream.spec.ts` also stopped asserting on a sentence the product does not show
a user: it was waiting for the *diagnostics* wording to be **visible**, which it
only ever was because of defect 1. It now asserts the spine's single
`role="status"` — "Reconnecting. Checkpoints during the gap are not replayed."
— and the diagnostics note separately, as a hidden record.

---

## 3. What is in here

| Path | Criterion | What it is |
|---|---|---|
| [`axe/`](axe/) | 1 | 120 retained axe reports (`<state>.<theme>.<width>.json`), [`summary.tsv`](axe/summary.tsv), and [`README.md`](axe/README.md) with the defect the matrix found. |
| [`manual/keyboard.md`](manual/keyboard.md) | 2 | Eleven surfaces walked with a scripted keyboard, with the method and its three limits stated first. |
| [`manual/keyboard/`](manual/keyboard/) | 2 | The raw focus traces — one TSV per walk, role / accessible name / region / focus ring / which element paints it. |
| [`manual/screen-reader.md`](manual/screen-reader.md) | 3 | **A protocol, not results.** Three environments, three scenarios, blank transcription blocks. |
| [`manual/reflow/`](manual/reflow/) | 4 | [`README.md`](manual/reflow/README.md) plus 18 per-sample TSVs. |
| [`manual/reduced-motion.md`](manual/reduced-motion.md) | 5, 6 | Durations, moving elements, status channels, live-region counts, and the forced-colours pass with both fixes. |
| [`manual/motion/`](manual/motion/) | 5 | Raw TSVs: durations, moving elements, status channels, live-region samples with timestamps. |
| [`manual/forced-colors/`](manual/forced-colors/) | 6 | Raw TSVs: the emulation proof, the spine in both palettes, the theme control. |

Everything under `manual/keyboard/`, `manual/reflow/`, `manual/motion/` and
`manual/forced-colors/` is written by the specs themselves on every run, so the
prose above can be re-derived rather than taken on trust.

## 4. What this pack does **not** claim

1. **No accessibility conformance, of any level.** Not WCAG 2.2 A, not AA. What
   is claimed is exactly what is measured: 120 axe reports with zero
   violations, thirteen scripted keyboard walks, sixteen reflow samples, a
   motion pass and a forced-colours pass — from **one engine, in one browser,
   on twenty reachable states.**
2. **Nothing about screen readers.** Criterion 3 is not done (§1).
3. **Nothing about comprehension.** Whether the observed focus order, the
   announcements or the recovery copy make sense to a person is a judgement.
   [`keyboard.md` §12](manual/keyboard.md) collects the judgements this branch
   is willing to make and marks them as prose.
4. **One engine.** `@a11y` is chromium-only, for three reasons written on the
   tag in `web/playwright.config.ts`: axe comparability, `forcedColors`
   emulation (which the other two engines do not implement), and genuine
   cross-engine differences in sequential focus navigation.
5. **One palette pair.** The forced-colours pass uses Chromium's two emulated
   palettes. A reader's own high-contrast theme is any pair of colours; the
   fixes are written so that whatever the pair is, the product uses it.
6. **Real browser zoom is not reproduced** — only its layout. See
   [`reflow/README.md` §0](manual/reflow/README.md).
7. **Twenty states, not thirty-one.** The matrix covers the §4 rows that have a
   distinct resting layout on this commit; the rest are in `DEFERRED_STATES`
   with a reason each, and `reflow.spec.ts` asserts the two lists partition §4
   exactly.
8. **Two structural observations are reported rather than fixed**, because both
   are specified behaviour and changing either would be a design ruling:
   the two `<h1>` elements on a populated thread and the briefing's own title
   being absent from the section rail
   ([`keyboard.md` §8](manual/keyboard.md#8-report--headings-links-and-tables)),
   and the plan editor's mixed use of `disabled` versus `aria-disabled`
   ([`keyboard.md` §6](manual/keyboard.md#6-plan-editor--the-arrays-and-the-decisions),
   owner WO-17). Both are carried into the screen-reader protocol as questions
   for the operator.

## 5. How to reproduce

```
cd web
npm ci
npm run e2e:stack:up
npm run e2e:stack:seed
npm run e2e -- --project=chromium
```

The axe matrix, the keyboard walks, the reflow sweep, the motion pass and the
forced-colours pass are all merged gates in that run — they are not a separate
recorder. Artifacts land in `web/build/e2e/a11y/` and `web/build/e2e/axe/`.

`ANTHROPIC_API_KEY` is overwritten with `local-preview-disabled` in the
Playwright process before any test loads, the Compose overlay pins the same
value on the `app` service, and `POST /api/research` is intercepted in-browser.
Nothing in this pack can reach a model provider.
