# 04 · Architecture: how to build it inside this repo's rules

All paths are relative to `web/` unless they start with `planning/`. Read
[recon/01-guardrails.md](recon/01-guardrails.md) once before writing code.
This file applies it.

## 1. File plan

### New files

All new components go in `components/workspace/`. Do **not** put them in
`patterns/`, `features/` or `primitives/`: those folders force copy into
`lib/copy` or pin story counts.

| File | Purpose |
|---|---|
| `components/workspace/controller.css` | The new stylesheet: shell, sidebar, stage, control bar, focus card, cover tiles, mascot, chips, kbd, dialogs, drawer, responsive rules. All selectors are scoped under `.workspace-app`. **No hex, rgb or hsl; no `font-family`.** |
| `components/workspace/Slots.tsx` | `WorkspaceSlots` provider, `SidebarSection`, `ControlBar` (portal with inline fallback, §3) |
| `components/workspace/Mascot.tsx` | Jazzy ([02 §6](02-design-system.md#6-mascot-jazzy)) |
| `components/workspace/Icon.tsx` | Inline SVG icon set ([02 §5](02-design-system.md#5-iconography)) |
| `components/workspace/CoverTile.tsx` | Deterministic cover art ([02 §7](02-design-system.md#7-cover-tiles-spotify-album-art-idea)) |
| `components/workspace/Queue.tsx` | `QueueList` and `QueueRow` (buttons, equalizer, status glyphs) |
| `components/workspace/FocusPaper.tsx` | The focused paper card. It is forked from `WorkCard` and has **no** status buttons. |
| `components/workspace/PlayerBar.tsx` | The control bar's route content: mini cover, prev/open/next, progress, actions |
| `components/workspace/Composer.tsx` | The search / slash-command input in the bar |
| `components/workspace/CommandPalette.tsx` | `⌘K` dialog. **Lazy**: loaded with `next/dynamic` or `import()` on first open. |
| `components/workspace/ShortcutsDialog.tsx` | `?` cheat sheet. Lazy, or folded into the palette. |
| `lib/workspace/queue.ts` | Pure functions: `todayQueue`, `libraryQueue`, `resolveFocus`, `neighbours`, `readerTarget` (extracted from `WorkCard.tsx:26-32`), `coverSeed` (FNV-1a) |
| `lib/workspace/urlState.ts` | `useQueryParam(name)` built on `useSyncExternalStore`, plus `setQueryParam(name, value, mode)` |
| `lib/workspace/commands.ts` | The `data-command` vocabulary and the keyboard map. Shared by the Shell handler, the palette and tests. |

### Changed files

| File | Change |
|---|---|
| `app/tokens.css` | **Append** the scoped palette fence ([02 §1](02-design-system.md#1-where-the-tokens-live-mechanics)). |
| `components/workspace/Shell.tsx` | Rewrite: the IDE layout, slots provider, keyboard handler, drawer, status line. |
| `components/workspace/Today.tsx` | Becomes the controller: queue, focus, slots. |
| `components/workspace/{Radar,Library,Reader,Interests,Operations,CandidateReview,Import,Common,ActivityCard,AllocationReceipt,InterestCoverage,RetainedSource,SyntheticWorkbench}.tsx` | Move controls into slots, adopt `ws-*` classes, keep behaviour. |
| `components/workspace/WorkCard.tsx` | Keep it for Library and Radar lists if they stay lists. Restyle only. |
| `components/workspace/workspace.css` | Fold its still-needed rules into `controller.css`, then **delete it**. That frees about 2.3 KB gz of CSS budget. |
| `lib/workspace/api.ts` | `normalizeReaderReturnTo` allows `focus` on `/workspace/today`, `/workspace/radar` and `/workspace/library`. |
| `budgets.json`, `tests/budgets.test.ts` | Only through the ratchet in §6. |
| Tests | See [07](07-test-impact.md). |

### Leave alone

| Path | Why |
|---|---|
| `components/daily/*`, `daily.css`, `app/(daily)/*` | Fictional preview. Shared CSS stays byte-identical. |
| `components/patterns/ThemeToggle.*` | Re-skin from `controller.css` under `.workspace-app` only. |
| `app/(workspace)`, `app/(learn)` | Out of scope. |
| `src/` | No backend changes. |

## 2. Shell

```tsx
// components/workspace/Shell.tsx (shape, not final code)
"use client";
export function WorkspaceShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();                       // allowed: mocked in shell tests
  const [sidebarNode, setSidebarNode] = useState<HTMLElement | null>(null);
  const [barNode, setBarNode] = useState<HTMLElement | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  useWorkspaceShortcuts();                          // one window keydown listener (§5)
  return (
    <WorkspaceSlots sidebar={sidebarNode} bar={barNode}>
      <div className="workspace-app ws-app font-ui" data-drawer={drawerOpen ? "open" : "closed"}>
        <SkipLink />
        <aside className="ws-sidebar" aria-label="Workspace controls">
          <div className="ws-brand">…<Mascot mood="idle" />Research workspace …</div>
          <nav aria-label="Research workspace">…six NavRow links (one per route)…</nav>
          <button className="ws-drawer-toggle" aria-expanded={drawerOpen} onClick={…}>Queue & controls</button>
          <div className="ws-drawer">
            <div ref={setSidebarNode} className="ws-sidebar-slot" />   {/* pages portal here */}
            <footer className="ws-sidebar-footer">…export · Fictional preview ↗ · Research a question ↗ · Shortcuts · <ThemeToggle/> · storage line…</footer>
          </div>
        </aside>
        <main id="main" tabIndex={-1} className="ws-stage">
          <header className="ws-stage-header">breadcrumb · route action slot · status line</header>
          {children}
          <div ref={setBarNode} className="ws-bar-slot" />            {/* control bar portals here; LAST in main */}
        </main>
      </div>
    </WorkspaceSlots>
  );
}
```

- **Ref callbacks.** `ref={setNode}` stores the DOM node in state through a
  ref callback. It does **not** read `ref.current` during render, and it does
  not call `setState` in an effect, so it satisfies the React Compiler lint
  rules.
- **Mobile.** `.ws-drawer` is static inside the aside on desktop. Below
  768px it becomes an off-canvas sheet. Brand, nav and the toggle stay
  visible, so `live.spec.ts:97-100` passes. Close the drawer on route change:
  derive "closed" from the path stored alongside the open flag, not from an
  effect.
- **Breadcrumb.** Derive it from `usePathname()`. The `n / N` part comes from
  the page through a small `ControlBar` prop, or from the stage-header slot.
- **Root class.** Keep `workspace-app` on the root. The scoped palette keys
  off it, and existing CSS and tests may reference it. Add `ws-app` for new
  rules.

## 3. Slots: sidebar and control bar

The problem: pages own their data, but their controls must *appear* in the
Shell's sidebar and bottom bar. Unit tests render pages **without** the
Shell and still expect every control to exist exactly once.

```tsx
// components/workspace/Slots.tsx (shape)
const SlotContext = createContext<{ sidebar: HTMLElement | null; bar: HTMLElement | null } | null>(null);

export function WorkspaceSlots({ sidebar, bar, children }) {
  return <SlotContext.Provider value={{ sidebar, bar }}>{children}</SlotContext.Provider>;
}

/** Renders into the Shell sidebar; inline when there is no Shell (unit tests, storybook). */
export function SidebarSection({ label, children }: { label: string; children: React.ReactNode }) {
  const slots = useContext(SlotContext);
  const body = <section className="ws-side-section" aria-label={label}>{children}</section>;
  if (!slots) return body;                 // no Shell → inline, exactly once
  if (!slots.sidebar) return null;         // Shell mounting → nothing (avoids a one-frame duplicate)
  return createPortal(body, slots.sidebar);
}
// ControlBar is identical, targeting slots.bar.
```

- **Why this shape.**
  - `LiveToday` rendered alone gets its sidebar sections inline, below the
    stage content in DOM order, so every existing test query still finds one
    element.
  - Inside the Shell it gets them in the sidebar.
  - Pages render real content only after `state` loads, by which time the
    slot nodes exist.
  - React context passes through portals, so handlers and state work
    normally.
- **Section labels.** Use distinct `aria-label`s ("Up next", "Reading time",
  "Source checks", "Your question"). They must not collide with test-pinned
  names. For example, don't label a section "Radar".
- **Single status region.** The page keeps rendering `<Message>`
  (`Common.tsx`) once. It may render *inside* the `ControlBar` portal so
  announcements sit near the actions. Do not add a second
  `role="status"`/`<output>` anywhere. A scan forbids new literal
  `role="status"` outside three files.

## 4. URL state and focus

```ts
// lib/workspace/urlState.ts (shape)
const EVENT = "workspace:url";
function subscribe(cb: () => void) {
  window.addEventListener("popstate", cb); window.addEventListener(EVENT, cb);
  return () => { window.removeEventListener("popstate", cb); window.removeEventListener(EVENT, cb); };
}
export function useQueryParam(name: string): string | null {
  return useSyncExternalStore(subscribe,
    () => new URLSearchParams(window.location.search).get(name),
    () => null);
}
export function setQueryParam(name: string, value: string | null, mode: "replace" | "push" = "replace") {
  const url = new URL(window.location.href);
  if (value === null) url.searchParams.delete(name); else url.searchParams.set(name, value);
  window.history[mode === "push" ? "pushState" : "replaceState"](null, "", `${url.pathname}${url.search}${url.hash}`);
  window.dispatchEvent(new Event(EVENT));
}
```

- **No `useRouter`.** It is not mocked in any test file. Use no
  `usePathname` in `LiveToday`: `stage1.test.tsx` lacks that mock.
- **Pure focus rule** in `queue.ts`:
  `resolveFocus(visible: WorkItem[], editionOrder: string[], focusId: string | null): WorkItem | null`.
  It implements [03 §3](03-screens-and-flows.md#3-today-the-focused-paper)
  rules 1–3. It is derived in render, so no state and no effect.
- **Radar** already writes its params with `pushState`. Add `focus` to its
  `navigate()` and `fromURL()`, and clear it when filters change.
- **Library.** The `view` param stays. `focus` is added.
- **Reader return.** Extend `normalizeReaderReturnTo` to keep `focus` on the
  Today, Radar and Library paths (≤500 chars, no control characters). Add
  tests in `tests/workspace/api.test.ts`.

## 5. Commands, shortcuts and palette: one mechanism

Actions are **real buttons** carrying a `data-command` attribute, for
example:

```tsx
<button data-command="save" aria-keyshortcuts="S" …>Save<span className="sr-only"> {title}</span></button>
```

Vocabulary in `lib/workspace/commands.ts`:
- `next`, `prev`, `open`
- `save`, `dismiss`, `snooze`, `undo`, `mark-read`
- `check-sources`, `time-5`, `time-15`, `time-45`
- `label-useful`, `label-maybe`, `label-irrelevant`

How the pieces use it:
- **Keyboard.** `useWorkspaceShortcuts()` is one `keydown` listener on
  `window`, added in a `useEffect`. Subscribing is fine; no `setState` in
  the effect body. It maps keys to command names, then runs
  `document.querySelector('[data-command="save"]:not(:disabled)')?.click()`.
  - Guards: `event.defaultPrevented`, `event.isComposing`, target is
    `input` / `textarea` / `select` / `[contenteditable]`, or the target sits
    inside an open `dialog` that isn't the palette.
  - Ctrl, Meta and Alt are only accepted for `⌘K` / `Ctrl+K`.
  - `g`-sequences keep `{key, at}` in a ref that is written only in the
    handler.
- **Palette.** On open it lists:
  1. global commands (go-to routes, theme, sidebar, export, shortcuts);
  2. every **enabled** `[data-command]` element currently in the document,
     labelled by its `aria-label` or text.

  Selecting an entry clicks it. So the palette can never offer an action
  that the page doesn't currently allow.
- **Slash commands.** The composer uses the same registry: `/save`, `/next`,
  `/radar`, `/time 15`, `/theme dark`.
- **Theme commands** click the existing `ThemeToggle` radios:
  `input[name="theme-preference"][value="dark"]`. No new theme logic.
- **Route commands** use buttons that call `window.location.assign(href)`.
  They are **not `<a>` links**, so the Shell keeps exactly one `/Radar/` link.
- **Why this design.** It is tiny (no registry state, no effects that set
  state). It is testable through plain clicks and `keydown` events. The
  visible button is always the source of truth.

## 6. Budgets

Measured at `916f038` with `npm run budgets`, which runs `next build` and
then `scripts/route-budgets.mjs`.

| Row | Measured | Ceiling | Headroom |
|---|---|---|---|
| **emitted-css (all)** | 17,321 | 17,408 | **87 B** |
| `/workspace/today` JS | 157,032 | 169,984 | 12,952 |
| `/workspace/radar` JS | 155,497 | 169,984 | 14,487 |
| `/workspace/interests` JS | 162,655 | 169,984 | **7,329** |
| `/workspace/library` JS | 157,829 | 169,984 | 12,155 |
| `/workspace/items/[id]` JS | 162,472 | 169,984 | **7,512** |
| `/workspace/operations` JS | 153,632 | 169,984 | 16,352 |
| `/workspace/review` JS | 154,792 | 169,984 | 15,192 |

**Reduce first.**
- Delete `workspace.css`, about 2.3 KB gz, after folding the needed rules
  into `controller.css`.
- Write compact CSS: shared custom properties, no duplicate theme blocks
  outside `tokens.css`, and grouped selectors.
- Lazy-load the palette and the shortcuts dialog.
- Keep icons to the listed set.
- Build mascot paths at module load from the grid. It is a short string
  array, not 256 `<rect>`s.

**Pre-authorized ratchet.** The owner authorizes it through this kit. Use it
only if a row still breaches after the reductions above.

1. **emitted-css.**
   - Raise the ceiling once to the smallest multiple of 512 B that is at
     least `measured × 1.06`, with a **hard cap of 26,624 B (26 KiB)**.
   - Append a `ratchet` entry to `budgets.json`, following the shape of the
     existing `emitted-css` entries: `row`, `from`, `to`, `date`, `pr`,
     `measuredBytes`, `headroom`, and a `why` of at least 80 characters.
   - Suggested `why` (fill the numbers): *"Workspace controller revamp
     (planning/12): one focused paper, a full-height control sidebar, a
     floating control bar, a scoped black/white/red palette in two themes,
     cover tiles and mascot. workspace.css (≈2.3 KB gz) was deleted and
     replaced. All emitted CSS measured N B; the ceiling is M B (+x%). No
     JS ceiling or measurement-script change."*
   - Update the row's `budgetBytes` and `budgetLabel` (`budgets.json:269+`).
   - Move `derived-total-first-load` by the **same delta**, with its own
     ratchet entry. The precedent text is the 2026-11-02 entry ("Follows CSS
     allowance by …").
   - Update the literals in `tests/budgets.test.ts:668` and `:677`, with the
     comment updated.
2. **Live route JS rows.**
   - Only after lazy-loading. For each breaching `/workspace/*` row, raise
     the ceiling to `measured × 1.05`, rounded up to 1 KiB.
   - **Cap: +8 KiB per route.**
   - Same ratchet entry shape. **Never** touch shared runtime, the
     Workbench, learn or daily rows.

Anything beyond these caps: **stop and ask the owner.**

## 7. CSS rules of the road

- Scope every selector under `.workspace-app` or `.ws-app`. Never style bare
  elements globally.
- Use **longhands when a border uses `var()`** (precedent in `tokens.css`;
  jsdom drops shorthands containing `var()` in computed-style tests).
- Any `outline: none` must be paired with a replacement in the **same rule**
  (`policy.test.tsx:201-208`).
- Fonts are set with the `font:` shorthand plus `var(--font-*)`. Never
  `font-family`.
- Wrap keyframes in `@media (prefers-reduced-motion: no-preference)`, or
  disable them under `reduce`.
- Layout uses CSS grid for the shell. Below 768px, collapse to a single
  column with the drawer. Use `100dvh` and `overscroll-behavior: contain`
  on scrollers.
- **Class prefix `ws-`** for new classes. Keep only the legacy classes that
  tests or e2e pin:

  | Class | Pinned by |
  |---|---|
  | `.daily-item` (with an `h3`) | `readiness.spec` |
  | `.workspace-activity` | `live.spec` |
  | `.workspace-receipt` | `live.spec` |

  Plus any class a unit test queries; grep `tests/workspace` for
  `querySelector(` and `.className`.

## 8. Accessibility contract

These rules are checked by axe in `live.spec` and by unit tests:
- **Landmarks.** One `main#main`. One `nav[aria-label="Research workspace"]`.
  `aside[aria-label="Workspace controls"]`. Dialogs are labelled.
- **Headings.** One `h1` per page, the page title. The focused item title is
  an `h3`, inside a section headed by an `h2`; it can be visually hidden,
  e.g. "Now reading". Don't skip levels.
- **Queue.**
  - An `<ol>` of `<li><button aria-current="true|undefined">`.
  - The accessible name is "Show paper N of M: ‹title›".
  - Selection does **not** move focus. The status region announces "Paper N
    of M" only if no other message is pending. This is optional; don't
    spam it.
- **Progress.** `role="progressbar"` with `aria-valuenow`, `aria-valuemin`
  and `aria-valuemax`, plus `aria-valuetext`.
- **Shortcuts.** Each shortcut button carries `aria-keyshortcuts`, and the
  visible `kbd` hint is `aria-hidden`.
- **Targets.** At least 24px everywhere, 32px default, 44px on
  `(pointer: coarse)`.
- **Motion.** Respect reduced motion.
- **Contrast.** Follow the floors in [02 §2.3](02-design-system.md#23-contrast-floors-computed-2026-11-03-re-verify-in-a-unit-test).
  axe "serious/critical" must be zero.
- **Drawer.** `aria-expanded` on the toggle. Focus moves into the drawer on
  open and returns to the toggle on close. Esc closes.
