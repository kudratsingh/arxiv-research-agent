# 00 · Charter: the research workspace becomes a controller

Status: **AUTHORIZED BY THE OWNER, 2026-11-03.** Implementation has not started.
Baseline commit: `18096be` on `claude/youthful-dirac-69v19d`. This branch is
`codex/daily-workspace-readiness` (`916f038`) plus the handoff docs.

## 1. The owner's words, verbatim

These messages came in order during the 2026-11-03 session. They are the
mandate. Where any later document in this kit appears to disagree with them,
these win.

> "I need a full revamp of the frontend of my arxiv agent application, it
> should be like a highly integrated vscode terminal or codex/claude code style
> controller, where only 1 main paper is being highlighted and then i can move
> to the next, and i can see the order of contents in a sidebar, there should
> just be one large sidebar for now with all needed controls, but in a user
> friendly highly polished frontend style, change the colors too to something
> that has more contrast like black and white for text and red accents and
> designs for a polished frontend think cartoonish or modern/integrated designs
> like the claude mascot on this frontend, the control bar at the bottom of the
> claude code chat in browser also has a nice design"

> "spotify has a nice frontend and designs that we can use"

> "[screenshot of the Claude Code web app] this layout is also nice and clean"

The owner's original screenshots showed the current live workspace at
`/workspace/today`, `/workspace/radar` and `/workspace/library`. They used the
dark teal theme, the long list of identical cards, and the old sidebar with
Today / Radar / Library / Interests / Sources & checks.
[`evidence/before/`](evidence/before/) holds equivalent captures from the
seeded local stack.

## 2. What this is

This is a **frontend-only re-architecture of the live research workspace**,
meaning the `(live)` route group `/workspace/*`. It turns the long scrolling
page into an **integrated controller**:

1. **One paper in focus at a time.** The main stage shows exactly one paper,
   large and readable. The user moves to the next or previous paper with
   buttons and keys.
2. **One large sidebar.** It holds the brand, navigation, the **ordered queue**
   (the "order of contents") and **every control** for the current screen.
3. **A floating bottom control bar.** It is modelled on the Claude Code web
   composer and Spotify's now-playing bar. It holds the actions for the
   focused paper: prev / next, Save, Dismiss, Snooze, Undo and open the reader.
   It also has a "search or type / for commands" input.
4. **A high-contrast palette.** Black and white for text and surfaces, with
   **red** as the single accent. It ships in both dark and light themes.
5. **An original cartoon mascot.** A pixel character in the house red, used
   for brand, empty states and busy states.
6. **The polish of a consumer product.** That means the clean layout of Claude
   Code web, the media-library feel of Spotify, and the keyboard-first density
   of VS Code.

## 3. What this is not

- **Not a backend change.** No route in `src/`, no schema and no API contract
  changes. Every capability the UI has today must still be reachable,
  backed by the same `workspaceRequest` calls with the same bodies.
- **Not a product-truth change.** The workspace's honesty rules stay intact
  (§5.3). The redesign changes how things look and where they sit, not what
  the product claims.
- **Not a restyle of the rest of the app.** The Evidence Workbench (`/`,
  `/c/[id]`), the learn routes (`/learn/*`) and the fictional preview (`/today`
  etc., `components/daily/*`) are **out of scope**. Changing them would
  invalidate visual goldens and axe baselines for no owner-requested gain.
  [05 · P9](05-phases-and-work-orders.md) records an optional, separately
  approved follow-up.
- **Not model spend.** Generation stays off. Nothing in this kit enables a
  paid call. `ANTHROPIC_API_KEY=local-preview-disabled` everywhere.
- **No copied artwork.** Borrow *patterns* from Claude Code, Spotify and
  VS Code: layout, interaction and density. Never their logos, mascots, icons,
  names, trade dress or exact colours. The mascot is original
  ([02 §6](02-design-system.md#6-mascot-jazzy)).

## 4. Success criteria

The owner judges these by eye. Each one is also checkable.

| # | The owner should be able to say… | Checked by |
|---|---|---|
| S1 | "Today shows me one paper, big and clear, and I can step to the next one." | Exactly one focused paper is rendered. Prev/next buttons and `j`/`k` change it. `?focus=` survives reload and back. |
| S2 | "I can see the whole list in order in the sidebar, and where I am in it." | The sidebar queue lists all visible edition items in edition order. The current item is highlighted. A progress readout says `n / N`. |
| S3 | "Everything I need is in one sidebar." | Nav, queue, reading time, source checks, current question, theme and exports are all in the sidebar on desktop. No second sidebar. |
| S4 | "The bottom bar feels like the Claude Code composer." | A floating rounded bar with an input and action row, keyboard hints, and the primary red action. |
| S5 | "It's black, white and red, and it's crisp." | Scoped palette in both themes. Every text pair is at least 4.5:1, UI marks at least 3:1, verified by a unit test plus axe. |
| S6 | "It has a cute mascot and looks polished, like a real product." | The mascot appears in the brand, empty states and busy states. Before/after screenshots are reviewed. |
| S7 | "Nothing I could do before is lost." | Every control in [recon/04-surfaces.md](recon/04-surfaces.md) is still reachable. All unit, typecheck and lint checks pass. The live e2e specs pass on the local stack. |
| S8 | "It works on my phone." | At 390px: the nav stays visible, the focused paper is above the fold, and queue and controls open in a drawer. |

## 5. Principles that bind every phase

### 5.1 Design

1. **Focus over feed.** One primary object per screen: the paper, the
   result or the item. Everything else is navigation or context.
2. **The sidebar is the control surface.** If it is a setting, a filter, a
   list or a mode, it lives in the sidebar. The main stage is for reading.
3. **Red means "you are here" or "the main action".** It marks the current
   queue row, the primary button, the progress fill, the focus cue, the
   mascot and the brand. It is never used for decoration and never as the
   only signal for an error ([02 §2.4](02-design-system.md#24-the-red-problem-accent-vs-error)).
4. **Keyboard-first, never keyboard-only.** Every shortcut has a visible
   button. Every button shows its shortcut on hover or focus.
5. **Calm motion.** Short transitions of 120–240ms. Ambient motion (the
   equalizer and mascot blink) is off under `prefers-reduced-motion`.

### 5.2 Engineering

1. **Frontend-only, zero new runtime dependencies.** Inline SVG icons, CSS
   patterns and native `<dialog>`. Anything else needs an owner decision.
2. **Respect the governance.** The rules in
   [recon/01-guardrails.md](recon/01-guardrails.md) are mechanical. Lint,
   tests, budgets and CSP will fail the build. Work with them; a rule is only
   relaxed through an explicit, recorded ratchet ([04 §6](04-architecture.md#6-budgets)).
3. **Components work with or without the Shell.** Unit tests render pages
   without the Shell, so sidebar and control-bar content must render inline
   when no Shell slot exists ([04 §3](04-architecture.md#3-slots-sidebar-and-control-bar)).
4. **URL is state.** The focused item, filters and views live in the query
   string, written with the History API. This is the pattern `Radar.tsx`
   already uses. Never use `useRouter`, which is not mocked in tests.

### 5.3 Product truth: unchanged, non-negotiable

The live workspace has an established honesty voice. The revamp keeps every
rule:
- Real source metadata only, and no fictional items in the live workspace.
  "No fictional items have been substituted."
- **A failed save stays a draft; it is never labelled saved.** Status copy such
  as "Saved on the server: …" appears only after a successful server write.
- Source checks show real coverage, including partial or failed checks and
  "a failed check cannot establish that nothing changed".
- The "Available evidence" caveat stays on the focused paper: abstract-only,
  excerpt, PDF excerpts, or metadata.
- "Why this appeared" stays. Ranking is declared terms plus metadata, not a
  quality score.
- Generation stays visibly off ("Generation awaiting approval", disabled).
- The text "Real source metadata · private server saves · generation off"
  stays visible on desktop and on mobile.

## 6. Constraints, in one place

- **Branch:** work on `claude/youthful-dirac-69v19d`, or the branch the owner
  names. Commit per work order. Push after each phase gate. **Do not open a PR
  unless the owner asks.**
- **Budget:** zero model spend.
- **Scope:** `web/` only, except that this kit's own `STATUS.md` is updated as
  you go.
- **Ratchets:** do not edit `budgets.json` ceilings, coverage thresholds or
  token parity files except as written in
  [04 §6](04-architecture.md#6-budgets). Record the reason in the commit body.
- **Tests:** a test that pins *old layout* may be updated. A test that pins
  *product truth* (copy semantics, request bodies, honesty states) may not be
  weakened. [07](07-test-impact.md) says which is which.
