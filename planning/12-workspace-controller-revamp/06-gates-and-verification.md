# 06 · Gates and verification

A gate is a list of statements that are mechanically true, or the gate does
not close. Record each closure in [STATUS.md](STATUS.md) with:
- the commit SHA;
- the commands run and their output summary (pass counts, budget numbers);
- links to the screenshots.

**No number in STATUS is typed by hand.** Paste it from command output.

## 1. Standard check set (run at every gate)

```bash
cd web
npm run lint                 # --max-warnings 0
npm run typecheck
npx vitest run               # whole unit suite, not a subset
```

At **G3, G7 and G8**, also run:

```bash
npm run budgets              # builds; prints every row vs ceiling
npm run test -- --coverage   # CI-enforced global thresholds
```

Plus the live e2e suite on the local stack ([08 §7](08-local-stack.md#7-live-e2e-regression-gate)).

## 2. Gate criteria

| Gate | Closes when |
|---|---|
| **G0** | Baseline recorded (lint, typecheck and vitest green; budget rows measured; live e2e 16/16). Local stack runs. Before captures exist. |
| **G1** | Scoped palette in `tokens.css`. The contrast test is green and has been proven to fail on a mutated value. Mascot, CoverTile and Icon exist with tests. `queue.ts`, `urlState.ts` and `commands.ts` have 100% line coverage. The standard set is green. |
| **G2** | The new Shell renders all 7 routes on the local stack without console errors. Shell assertions from [07 §3](07-test-impact.md#3-shell-assertions-that-must-keep-holding) hold. Slots render inline without the Shell and once with it. Keyboard plumbing is tested. Mobile nav is visible at 390px. Standard set green. |
| **G3** | Today has one focused paper, the queue in the sidebar, the control bar, prev/next by button and key, `?focus` persistence, and auto-advance after dismiss/snooze with undo. The multi-item tests listed in WO-3.1 exist and pass. On the local stack (9 items), the keyboard walk-through works. Mobile title at y < 800. Dark/light × desktop/mobile Today screenshots exist. Budgets run, with any ratchet recorded. Live e2e Today specs pass. |
| **G4** | Reader in the frame with edition prev/next. Reader tests green. Live e2e reader flows pass, including at most 16 Tabs to "Your notes". |
| **G5** | Radar and Library in the controller pattern. Their tests are green and new focus tests added. The return-to-Library notes view is preserved. |
| **G6** | Interests, Sources & checks and Review restyled with sidebar placement. Their tests are green. Review keys are tested. |
| **G7** | Palette, motion and responsive QA done. axe reports zero serious/critical issues on all routes × 2 themes × 2 widths. Reduced motion is verified. Budgets are within ceilings, or ratcheted within caps with records. The command palette is lazy. |
| **G8** | Everything in §4. |

## 3. Visual QA checklist

Run this per route, in dark and light, at 1440 and 390 widths.

**Composition**
- [ ] Exactly one primary object in the stage: paper, result, source, candidate or form.
- [ ] The sidebar holds every control for the route. Nothing is control-like in the stage except the item's own content.
- [ ] The control bar is centred over the reading column, floating, and never covers content. The stage has bottom padding.
- [ ] The breadcrumb and status line are present. The status text is complete and readable at 390px.

**Colour and type**
- [ ] Only black, white, greys and red, plus amber or coral for status. No teal or blue left over from the old palette. Grep the rendered CSS for `--color-primary` uses that still look blue: that means a component is outside `.workspace-app`.
- [ ] Red is used only for: current row, primary action, progress, brand, mascot, focus-adjacent accents.
- [ ] Type matches [02 §3](02-design-system.md#3-typography). Titles are crisp and abstracts comfortable at 68ch. No text under 12px.

**Interaction**
- [ ] Hover, focus-visible, active, disabled and busy states exist for every control. The focus ring is visible on every surface, including on red buttons.
- [ ] Prev/next is instant. Stage and queue highlight move together, and the queue auto-scrolls to keep the current row visible (`scrollIntoView({block:"nearest"})` in the click handler, not an effect).

**Delight**
- [ ] The mascot appears in the brand, empty states and busy states. Its blink and hop are subtle. Everything is static under reduced motion.
- [ ] Cover tiles vary across papers and stay consistent for the same paper.

**Responsive and theme**
- [ ] At 390px: no horizontal scroll, the drawer works, the nav row is visible, and the bar is compact and doesn't overlap the title.
- [ ] Light theme is as polished as dark: panel separation, hairlines and shadow on the bar.

**Integrity**
- [ ] Every control in [recon/04-surfaces.md](recon/04-surfaces.md) §13 is still reachable.
- [ ] Honesty copy is intact ([00 §5.3](00-charter.md#53-product-truth-unchanged-non-negotiable)).

## 4. Definition of Done

1. The success criteria S1–S8 in [00 §4](00-charter.md#4-success-criteria)
   are each demonstrated by a screenshot or a test, linked in STATUS.
2. Lint, typecheck, the full vitest suite and coverage thresholds are green.
3. `npm run budgets` is green, with any ratchet within the caps in
   [04 §6](04-architecture.md#6-budgets) and fully recorded.
4. The live e2e suite on the local stack is green. Any spec change is
   justified as "pinned old layout", never "weakened product truth".
5. axe reports zero serious/critical issues across routes, themes and
   widths. A keyboard-only daily loop works.
6. The fictional preview (`/today` etc.) and the Evidence Workbench (`/`)
   are visually unchanged. `daily.css` is byte-identical, unless a change is
   justified.
7. `evidence/after/` holds the final captures, and STATUS has the full
   timeline.
8. The branch is pushed. There is no PR unless the owner asked for one.
