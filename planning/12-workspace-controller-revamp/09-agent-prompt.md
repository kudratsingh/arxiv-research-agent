# 09 · Copyable prompt for the implementation agent

Paste everything inside the fence into the coding agent that has the
`arxiv-research-agent` repository. The kit itself is in the repo at
`planning/12-workspace-controller-revamp/` on branch
`claude/youthful-dirac-69v19d`. If the agent cannot reach that branch, send
the whole kit directory with the prompt.

```text
You are implementing a full frontend revamp of the LIVE research workspace in
kudratsingh/arxiv-research-agent — the Next.js routes /workspace/* (Today,
Radar, Library, Interests, Sources & checks, Review, and the reader at
/workspace/items/[id]). The complete planning kit is in the repo at:

  planning/12-workspace-controller-revamp/

Branch: claude/youthful-dirac-69v19d (it already contains the kit and the
daily-workspace code this revamp builds on; do NOT start from main — main
does not have the workspace UI). Commit to this branch; push after each
phase gate; do NOT open a pull request unless I ask.

WHAT I WANT (my words): "a highly integrated vscode terminal or codex/claude
code style controller, where only 1 main paper is being highlighted and then
i can move to the next, and i can see the order of contents in a sidebar,
there should just be one large sidebar for now with all needed controls, but
in a user friendly highly polished frontend style, change the colors to
something that has more contrast like black and white for text and red
accents … think cartoonish or modern/integrated designs like the claude
mascot … the control bar at the bottom of the claude code chat in browser
also has a nice design." I also want Spotify's frontend patterns used, and
the Claude Code web app layout (left sidebar with a highlighted "recents"
style list, clean centre column, floating rounded composer bar at the
bottom) as the base. Borrow patterns only — no copied logos, mascots, icons
or brand colours. The mascot must be our own (spec in the kit: "Jazzy", a
red pixel bookmark creature).

READ FIRST, IN THIS ORDER:
  1. README.md                (map of the kit, decisions, how to use it)
  1b. 10-review-corrections.md (ERRATA — 82 verified review findings with exact
      fixes; where it conflicts with 00–09 it WINS. Most blockers: the live e2e
      runs at 390px with strict single-match locators, so any control a spec
      touches must be visible without opening the drawer and exist once per page)
  2. 00-charter.md            (my words, goals, non-goals, success criteria S1–S8, product-truth rules)
  3. 03-screens-and-flows.md  (exact layout per route, wireframes, keyboard map, control bar)
  4. 02-design-system.md      (palette with contrast table, type, mascot grid, cover tiles, components)
  5. 04-architecture.md       (file plan, slots with inline fallback, URL state, data-command keyboard/palette, budgets + pre-authorised ratchet)
  6. 05-phases-and-work-orders.md (P0–P8 work orders — execute in order)
  7. 06-gates-and-verification.md and 07-test-impact.md
  8. 08-local-stack.md        (verified recipe to run the real stack with seeded data; screenshots; live e2e 16/16 baseline)
  9. recon/01-guardrails.md   (the mechanical rules: colour literals only in app/tokens.css, 23 --color-* names, no font-family, CSP no <style>, React-Compiler lint rules, budgets, coverage)
 10. recon/02-tests.md        (what every existing test pins)

HOW TO WORK:
- Execute phases P0 → P8 from 05-phases-and-work-orders.md. Each phase ends
  at a gate in 06; do not start the next phase until the gate is green.
  P4, P5, P6 may run in parallel worktrees (they own disjoint files; each
  appends to its own fenced section of controller.css).
- One commit per work order, conventional messages. Update
  planning/12-workspace-controller-revamp/STATUS.md at every gate with the
  commit SHA, command outputs (paste, never hand-type numbers), screenshots
  and deviations.
- Frontend only (web/). No backend changes, no new runtime dependencies,
  zero model spend: ANTHROPIC_API_KEY=local-preview-disabled everywhere.
  Never click "Check sources now" on the local stack (it hits the network).
- Keep every existing capability reachable and keep the product-truth copy
  and request bodies exactly (charter §5.3, 07 §1 and §4). You may update
  tests that pin OLD LAYOUT; you may not weaken tests that pin product truth.
  Give a one-line reason for every test edit in the commit body.
- Budgets: reduce first (delete workspace.css after folding it into the new
  controller.css, lazy-load the command palette). The CSS and live-route JS
  ratchets in 04 §6 are pre-authorised up to their caps; beyond the caps,
  stop and ask me.
- Verify like a user: run the real stack (08), look at the screens in dark
  and light at 1440 and 390, step through all 9 seeded papers with the
  keyboard, run axe, run the live e2e suite. Take before/after screenshots
  (deviceScaleFactor 2) into evidence/after/.
- Before declaring done, run an independent adversarial review of the full
  diff (product truth, accessibility, React/lint correctness, visual fidelity
  to 02/03, budgets/CSP) and fix confirmed findings.

DEFINITION OF DONE: 06-gates-and-verification.md §4 — S1–S8 each
demonstrated by a test or screenshot linked in STATUS; lint, typecheck, full
vitest and coverage thresholds green; budgets green (ratchets recorded within
caps); live e2e green on the local stack; axe zero serious/critical across
routes × themes × widths; fictional preview and Evidence Workbench visually
unchanged; branch pushed.

If something in the kit is wrong or contradicts the code, trust the code,
note the discrepancy in STATUS.md, and choose the option that best serves
the charter. If a decision is genuinely mine to make (anything listed under
"Open decisions" in README.md beyond its stated default, or exceeding a
budget cap), ask me — otherwise use the kit's defaults and keep going.

When you finish each gate, send me a short update with the Today
screenshots (dark + light, desktop + mobile) so I can steer early.
```
