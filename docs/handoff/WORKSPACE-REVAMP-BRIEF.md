# Handoff brief: research workspace frontend revamp

**Branch:** `claude/youthful-dirac-69v19d` (pushed). **Status:** discovery done, design agreed, **no UI code written yet**.
**Read first:** this file, then the five reports in `docs/handoff/workspace-revamp-map/` (`01-guardrails.md` is the most important).

---

## 1. What the user asked for

The user's words, lightly edited:

> Full revamp of the frontend of my arxiv agent application. It should feel like a highly integrated VS Code terminal or a Codex / Claude Code style controller. Only **one main paper is highlighted** at a time, and I can **move to the next**. I can see the **order of contents in a sidebar**. There should be **just one large sidebar for now with all needed controls**, in a user-friendly, highly polished style. Change the colours to something with **more contrast: black and white for text, red accents**. Think **cartoonish or modern/integrated designs, like the Claude mascot**. The **control bar at the bottom of the Claude Code chat in the browser** has a nice design.

The user added three references later:
- **Spotify** has a nice frontend and designs we can use.
- **The Claude Code web app layout** is "nice and clean". Their screenshot showed:
  - Left sidebar: a small header row with icons; nav rows (New, Search, Artifacts, Scheduled, Customize, More); then a "Recents" list with a rounded highlight on the active row.
  - Centre column: a slim top bar (title + dropdown, icon buttons, "Share").
  - A floating rounded composer at the bottom: "+", "Type / for commands", mic icon.
  - Neutral near-black panels with thin borders.
- The user's original screenshots were of the current live workspace: `/workspace/today`, `/radar`, `/library` in the dark teal theme.

## 2. Timeline so far

1. **Found the right code.** The UI in the user's screenshots is not on `main`. It lives on the `codex/daily-workspace-*` branches, stacked preview ⊂ live ⊂ next ⊂ readiness. `codex/daily-workspace-readiness` (916f038) is the tip.
2. **Moved the branch.** Fast-forwarded `claude/youthful-dirac-69v19d` (it had no commits of its own) to `origin/codex/daily-workspace-readiness` and pushed it. That brought in 23 commits on top of main.
3. **Installed dependencies** with `cd web && npm ci`.
4. **Ran a baseline.** All green at 916f038:
   - `npx vitest run tests/workspace tests/daily tests/shell tests/tokens.test.ts tests/copy tests/primitives`: 53 files, 1417 tests pass.
   - `npm run typecheck`: clean.
   - `npm run lint`: clean.
5. **Ran a 6-agent read-only mapping workflow.** Five reports finished and are saved verbatim in `docs/handoff/workspace-revamp-map/`:
   - `01-guardrails.md`: every ESLint, token, CSP, budget and coverage rule, with file:line references and tested palette options.
   - `02-tests.md`: every test that pins the DOM, what breaks under a focused-paper design, and the router mocks.
   - `03-reader.md`: Reader / RetainedSource / SyntheticWorkbench structure, controls and fragile bits.
   - `04-surfaces.md`: Today, Radar, Library, Interests, Operations, CandidateReview, Import, etc. Includes the state shape and the controls for each surface.
   - `05-styles.md`: class inventory, which classes `daily.css` and `workspace.css` share with the fictional preview, and how ThemeToggle works.
   - **Not finished:** the **run-path** report (how to boot a seeded live workspace locally for screenshots). See §6, step 0.
6. **Agreed the design direction** with the user in chat (§3). No code has been written.

## 3. Agreed design spec

This blends four references: the Claude Code web layout (the base), Spotify, VS Code, and a black/white/red palette with a mascot.

### Shell: `components/workspace/Shell.tsx`

**Left sidebar.** One large sidebar, about 320–360px. Top to bottom:
1. **Header row:** original pixel mascot + "Research" + icon buttons (collapse sidebar, theme).
2. **Primary nav** as icon rows: Today, Radar, Library, Interests, Sources & checks, Review. Keep the `<nav aria-label="Research workspace">`.
3. **"Up next" queue**, like Claude Code's "Recents" and Spotify's library list:
   - Numbered rows in edition order.
   - The current paper gets a rounded red-tinted highlight and a small animated red "equalizer" (now-reading) mark.
   - Status icons: saved, read, snoozed.
   - Optional filter chips: Today / Saved / Notes.
4. **Controls:** reading time 5 / 15 / 45, a source-check status summary with "Check sources now", and "Your current question".
5. **Footer:** local-workspace status text, export notes, "Research a question ↗", "Fictional preview ↗".

**Centre column.**
- A slim top bar showing the breadcrumb (`today › 2 / 3`) and paper title, with a red primary **"Read & investigate"** button where Claude Code has "Share", plus icon actions.
- Below it, **one focused paper** in a calm centred column (about 760–860px max):
  - A generated **cover tile** (Spotify album-art idea): deterministic pattern chosen from a hash of `work_id`, done with CSS classes and `data-pattern` only. No inline colour literals.
  - Kind / version / access chips in mono.
  - A big title. It must **not** be an `h1`; the page `h1` stays "What changed".
  - The full abstract, "Why this appeared", "Available evidence", source and date.
  - A subtle red gradient wash at the top, like Spotify's colour-from-artwork header.

**Bottom control bar.** A floating rounded bar in the style of the Claude Code composer, merged with Spotify's "now playing" bar:
- An input, "Search stored papers or type / for commands". Enter jumps to `/workspace/radar?q=…`.
- Below the input, a row of controls: ⏮ prev, Save, Dismiss, Snooze one day, Undo, ⏭ next.
- A thin progress bar showing your place in the queue.
- Keyboard: `j`/`k` or ←/→ for prev/next, `s` save, `d` dismiss, `z` snooze, `o`/Enter open the reader. Shortcuts must be ignored while focus is in an input.

**Optional:** a ⌘K command palette using a native `<dialog>` (watch the JS budget).

**Mobile (390px).** The sidebar collapses into a top section or drawer, but the **nav must stay visible and clickable at 390px** (e2e `live.spec.ts:97-100`). The control bar becomes a compact bottom bar.

### Palette

Scoped to the workspace root. Use the `--ws-*` prefix for new names, never `--color-*`.

| Role | Dark | Light |
|---|---|---|
| Canvas | #0A0A0A–#121212 (Spotify-like panels) | #FFFFFF / #F5F5F5 |
| Panel / raised | #111113 / #18181B | white / #FAFAFA |
| Border | #27272A / #3F3F46 | #E4E4E7 / #8A8A93 |
| Ink | #FAFAFA | #0A0A0A |
| Muted | #A1A1AA | #52525B |
| Faint | #8B8B94 | #67676F |
| Red fill (white text on it) | #E0242B (4.7:1) | #D7191F (5.2:1) |
| Red text | #FF5A5F (6.4:1 on black) | #C8102E (5.9:1 on white) |
| Red-tint row highlight | #2A0D0F | #FDECEC |

The guardrails agent also verified #D70000 and #FF4D4D as AA-safe. **Re-check contrast for every pair you actually use.**

### Mascot

An **original** red bookmark-ribbon pixel critter, `components/workspace/Mascot.tsx`:
- 16×16 grid, `shape-rendering="crispEdges"`, `aria-hidden`.
- Shape: rounded-top body, white eyes with dark pupils, small arm nubs, and a V-notch at the bottom that forms two legs.
- It must **not** copy Anthropic's or Spotify's artwork.
- Colour comes from `currentColor` plus CSS classes. **No hex, no `<style>` element.**
- Moods via `data-mood` (idle blink / busy hop / sleepy for empty states). Keyframes must be off under `prefers-reduced-motion`.

Use it in the sidebar header, the empty states (as a speech bubble), and while checking sources.

**Fonts:** only the 3 existing families. Title and UI in `var(--font-ui)` bold, abstract in `var(--font-report)`, meta and kbd hints in `var(--font-mono)`. Use the `font:` shorthand with a `var()`. **Never** write `font-family`.

## 4. Hard constraints

Details are in `01-guardrails.md` and `02-tests.md`.

- **Colour literals:** hex / rgb / hsl are allowed **only in `web/app/tokens.css`**. This covers comments, CSS, tests and `.svg` files (`tokens.test.ts:709-754`, ESLint `eslint.config.mjs:18-33`).
- **Palette mechanism: Option B, already tested green.** Append a fenced block at the **end** of `app/tokens.css` that redeclares the 23 existing `--color-*` roles plus new `--ws-*` vars under these selectors:
  - `.workspace-app`
  - `:root[data-theme="dark"] .workspace-app`
  - `@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) .workspace-app {…} }`

  Rules for that block:
  - Never add a second bare `:root{}`.
  - Never add properties to the 4 theme blocks.
  - Never add new `--color-*` names (the storybook test counts exactly 23).
  - `body` sits outside the scope; use `:root:has(.workspace-app)` if the page background must change.
- **CSS budget is the tightest constraint: 87 B headroom** for all emitted CSS (17,321 / 17,408 B gz).
  - Real room comes from rewriting `workspace.css`, about 2.4 KB gz.
  - Raising the ceiling means editing `budgets.json:272`, adding a ratchet entry with a `why` of at least 80 characters, updating `derived-total-first-load` (:307), and changing the `budgets.test.ts:668,677` literals. Explain the change in the PR.
- **JS headroom:** about 7.3 KB on `/workspace/interests` and `/workspace/items/[id]`. Shell code counts on all 7 routes.
- **`daily.css` is shared with the fictional preview** (`components/daily/*`, routes `/today` etc., e2e `workspace-e2e/daily.spec.ts`). Scope new styles under `.workspace-app` or a new file; don't change shared classes.
- **CSP:** `style-src 'self'` means no `<style>` tags. `style={{}}` attributes are allowed but discouraged; prefer classes.
- **Lint:** `--max-warnings 0`, and the React Compiler rules are errors. In particular, no `setState` inside an effect (e.g. `useEffect(()=>setIndex(0))`) and no reading `ref.current` during render. **Derive the focus index from the URL or state during render.**
- **Placement:** keep new components in `components/workspace/`. Putting them in `patterns/` or `features/` would force all copy into `lib/copy`, and `primitives/` has a fixed story count.
- **Routes:** the route set is exact (`tests/shell/routing.test.ts`). Don't add or rename `/workspace/*` pages.
- **Coverage:** global thresholds of about 99.1% lines, enforced in CI. New code needs tests.
- **Routing hooks:** `next/navigation` mocks define only `usePathname` and `useSearchParams`, and some files only `useSearchParams`.
  - `LiveToday` may use `useSearchParams`, but not `usePathname` or `useRouter`.
  - Use `window.history.replaceState` / `pushState` + `popstate` for a `?focus=` param (the pattern `Radar.tsx` already uses).

### Test traps for the focused-paper Today

See `02-tests.md` §(a) and §(b).
- **Queue rows must not create duplicate accessible names.**
  - Make queue rows **buttons** (not links named exactly after the title), or give them distinct names.
  - `experience.test.tsx:262` requires *no* link named after the latest title when v1 is pinned.
  - Don't repeat the abstract text in the queue.
- **Queue rows must not be `<article>`.** `queryByRole("article")` must be null after a snooze.
- **Keep the bar's actions unique.**
  - Buttons named `/^Save <title>/`, `/^Snooze one day/`, `/^Dismiss/` and "Undo last change" must each match exactly one element.
  - Either move the actions into the control bar **with those same accessible names** and remove them from the Today card, or keep them on the card. Not both.
  - **Fork a Today-only focus card.** Library still relies on `WorkCard`'s `/^Unsave …/` buttons.
- **One status region:** exactly one `role="status"` (the `Message` in `Common.tsx`). Don't add more; a scan forbids new literal `role="status"`.
- **Render controls in `LiveToday` itself:**
  - Unit tests render `LiveToday` **without** the Shell. Every Today control ("5 min", "Check sources now", "Source checks: N of M", "Generation awaiting approval", the empty-state headings, the activity card / "Pin this question") must still be rendered by `LiveToday`, exactly once.
  - If you portal them into a Shell sidebar slot, **fall back to rendering inline** when there is no Shell. jsdom has CSS off, so responsive duplicates count twice.
- **Shell:**
  - Exactly one `main#main` (tabIndex -1, SkipLink target).
  - No `h1` in the Shell.
  - Keep the link containing "Fictional preview" → `/today`.
  - Exactly one `/Radar/` link inside the Shell.
  - Keep the text "Real source metadata · private server saves · generation off" visible on desktop and at 390px.
  - Don't put focusable chrome inside `<main>` ahead of the content (at most 16 Tabs to the Reader's "Your notes").
- **E2E** (not runnable without the stack): keep these selectors and names, or update the specs.
  - `.daily-item h3` placed after the h2 "Continue your question" (`readiness.spec.ts`).
  - "Edition details".
  - `.workspace-activity` with the "Source and pin options" summary.
  - `.workspace-receipt`.
  - Axe at AA with zero serious violations.

## 5. Key files

- **Shell and routes:** `web/components/workspace/Shell.tsx`, `web/app/(live)/{layout,template}.tsx`, `web/app/(live)/workspace/*/page.tsx`.
- **Surfaces:**
  - `Today.tsx`, `WorkCard.tsx`, `ActivityCard.tsx`, `AllocationReceipt.tsx`, `Common.tsx`
  - `Radar.tsx`, `Library.tsx`, `Import.tsx`
  - `Interests.tsx`, `InterestCoverage.tsx`
  - `Operations.tsx`, `CandidateReview.tsx`
  - `Reader.tsx` (927 lines), `RetainedSource.tsx`, `SyntheticWorkbench.tsx`
- **Data:** `web/lib/workspace/{api,useWorkspace,useReadingActions,drafts}.ts`.
  - Edition order is `state.editions[0].work_ids`, with pinned versions in `work_versions`.
  - Visible items exclude dismissed and archived items, and snoozed items until `snoozed_until` passes. See `Today.tsx:33-62`.
- **Styles:** `web/components/daily/daily.css` (shared), `web/components/workspace/workspace.css`, `web/app/tokens.css`, `web/components/patterns/ThemeToggle.{tsx,css}`.
  - The theme is set by the `data-theme` light/dark attribute on `<html>`, written pre-paint by `themeInitScript` in `lib/tokens.ts`.
- **Tests:** `web/tests/workspace/*.test.tsx` (fixtures in `tests/workspace/fixtures.ts`; the single-work edition is `work()` / `workspace()`), `web/tests/daily/*`, `web/live-workspace-e2e/*.spec.ts`, `web/workspace-e2e/daily.spec.ts`.

## 6. What still needs to happen, in order

0. **Boot a seeded live workspace for screenshots.** This was unfinished; redo it.
   - Read `web/e2e/fixtures/workspace_seed.py`, `web/scripts/workspace-seed.mjs`, `web/e2e/support/stack.sh`, `web/e2e/support/compose.e2e.yml`, `web/live-workspace-e2e/playwright.config.ts`, the Python workspace router (`grep -rln workspace src/api`), and the README / `docs/development.md` workspace sections.
   - The goal is to run the backend with seeded data plus `cd web && WORKSPACE_LIVE=1 npm run dev`, and to reach `/workspace/today` with several edition items.
   - Chromium + Playwright are preinstalled (`require('playwright')`).
   - If the backend is impractical, write a tiny stub upstream (precedent: `web/e2e/support/stub-upstream.mjs`) that serves `tests/workspace/fixtures.ts`-shaped JSON for `/workspace/state` etc.
   - Take **before** screenshots: dark and light, 1440 and 390 widths.
1. **Palette.** Add the scoped palette block to the end of `app/tokens.css` (Option B, §4). Add a small unit test that asserts the contrast of the scoped pairs, with hex strings assembled so the literal scan doesn't fire.
2. **Mascot.** Write `components/workspace/Mascot.tsx` with a unit test.
3. **Shell rewrite.** Sidebar (brand, nav, page slot, global controls, footer) plus a top bar.
   - Use a **sidebar slot**: a context with a DOM node, where pages `createPortal` into it and fall back to inline when there is no provider.
   - Mobile drawer or stacked layout, keeping the nav visible.
   - Replace `workspace.css` with a new scoped stylesheet to free CSS bytes. Leave `daily.css` alone for the preview, or stop importing it in the live Shell **only if** the live components no longer use its classes; it is still imported by `DailyShell`.
4. **Today.**
   - `?focus=<work_id>` URL state (history API + popstate).
   - A focused paper card (forked from `WorkCard`).
   - Queue rows as buttons in the sidebar slot.
   - The bottom control bar (prev/next, Save / Dismiss / Snooze with the same accessible-name prefixes, Undo, progress).
   - Keyboard shortcuts.
   - Advance to the next item after a dismiss or snooze.
   - Keep every existing Today control, rendered once.
5. **Other surfaces in the new system.**
   - Radar: filters go into the sidebar slot, results use the queue plus focus pattern or a clean list.
   - Library: the view select goes into the sidebar.
   - Interests, Operations, Review: restyle.
   - Reader: prev/next within the edition if state allows (see `03-reader.md` §4); restyle.
6. **Tests.**
   - Update the unit tests that break.
   - Add tests for multi-item queue order, prev/next, keyboard shortcuts, `?focus` persistence and the mascot. Coverage must stay at about 99.1% lines.
7. **Checks.**
   - `cd web && npm run lint && npm run typecheck && npx vitest run`.
   - `npm run budgets` (needs `npm run build`). Raise the CSS ceiling only with a ratchet entry plus a reason if it is unavoidable.
   - Screenshot QA in light, dark and mobile.
   - An axe pass (`@axe-core/playwright` is installed).
   - An independent adversarial review of the diff.
8. **Ship.**
   - Commit in logical chunks: palette+mascot, shell, Today, surfaces, tests.
   - `git push -u origin claude/youthful-dirac-69v19d`.
   - **Don't open a PR unless the user asks.**
   - Commit trailer:
     ```
     Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
     Claude-Session: https://claude.ai/code/session_01NtWetkE3VXSYcJjWZaRzGK
     ```
