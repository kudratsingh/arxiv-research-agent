# 07 · Test impact: what will break, what may change, what must not

The complete inventory (every test, query and request body, with file:line)
is [recon/02-tests.md](recon/02-tests.md). This file is the decision layer
on top of it.

## 1. The rule

- **May update:** assertions that pin **old layout**. Examples: where a
  control sits, how many cards render, wrapper markup, a class that only
  styled the old design.
- **Must not weaken:** assertions that pin **product truth**:
  - request paths and bodies (`reading`, `profile` then `edition` then
    `state`, `refresh {source_ids:[]}`, `entries`, `review/feedback` …);
  - idempotent `request_id` reuse on retry;
  - honesty copy (§4);
  - draft and conflict behaviour;
  - "exactly one status region";
  - axe cleanliness.

Every test edit gets a one-line reason in the commit body:
`test(workspace): <file> — pinned old layout: <what>`.

## 2. Today traps

Recon §(a) has the details.

1. **Duplicate names.**
   - Queue rows are `<button>`s named "Show paper N of M: ‹title›", never
     links named exactly by the title. `experience.test.tsx:143, :241,
     :252, :946` use `getByRole("link", {name: title})`. `:262` requires
     **no** link named by the latest title when v1 is pinned.
   - The focused card's `h3` link keeps the title as its name and its href
     (`arxiv%3A`, `version=…v1`).
   - Before relying on visible queue titles, grep the tests for exact
     `getByText(<title>)`. If any exist, either keep queue titles out of the
     accessible text (`aria-hidden` visual duplicate plus a named button), or
     update the query to scope within the stage.
2. **`<article>` count.** The focused card is the only `<article>`. Queue
   rows are not articles. Empty and unavailable states render no article
   (`experience:158, :275`).
3. **Action buttons exist once.**
   - Today's Save/Unsave, Dismiss and "Snooze one day" live in the control
     bar only, with `aria-label`s exactly `Save|Unsave ${title}`,
     `Dismiss ${title}` and `Snooze one day ${title}`. Same prefixes as
     `WorkCard.tsx:119,131,139`, so `/^Save A controlled/` keeps matching.
   - "Undo last change" exists once.
   - `FocusPaper` (forked) has **no** status buttons. `WorkCard` keeps
     its buttons for Library and Radar lists, and Library tests use
     `/^Unsave A controlled/` on it.
4. **One status region.** `getByRole("status")` is used in `experience:152,
   :156, :220, :943, :951` and `stage1:199`. `retained.test.tsx:190` uses
   `getAllByRole("status")` with length 1. Never add another; that includes
   the palette, toasts and the progress bar. A static scan forbids new
   literal `role="status"` outside `daily/Announcement.tsx`,
   `patterns/TraceSpine.tsx` and `workspace/Common.tsx`.
5. **One `h1`.** "What changed" stays the `h1`. The paper title is an `h3`.
6. **Controls render from `LiveToday` itself.** Tests render it without
   the Shell, so `SidebarSection` must fall back to inline
   ([04 §3](04-architecture.md#3-slots-sidebar-and-control-bar)). Under
   `css:false`, responsive duplicates count, so never render two copies
   for desktop and mobile.
7. **Abstract text appears once.** `getByText("An earlier retrieval abstract.")`
   is exact, so the focused card shows the abstract and the queue shows no
   abstract snippet.
8. **The fixture has one work.** All existing Today tests use `workspace()`
   from `tests/workspace/fixtures.ts`, which has one edition item. Add a
   **multi-item fixture builder** (e.g. `workspaceWith(n)`) rather than
   editing `workspace()`; many tests depend on it.
9. **Router mocks.**
   - `LiveToday` may use `useSearchParams` but not `usePathname` or
     `useRouter`. `stage1.test.tsx` lacks `usePathname`, and no file mocks
     `useRouter`.
   - Prefer `useQueryParam` (`useSyncExternalStore` over `location.search`),
     which needs no mock.
   - Tests set the URL with `window.history.replaceState(...)` before
     `render`, and simulate back with `fireEvent.popState(window)`.

## 3. Shell assertions that must keep holding

Recon §(b) has the details.

- `experience:122-135`:
  - a link containing "Fictional preview" with `href="/today"`;
  - **exactly one** `/Radar/` link inside the Shell, with href
    `/workspace/radar`;
  - one `main` containing the child.
- `routes:56-75`:
  - `<Template><TodayPage/></Template>` gives an `h1` "What changed" inside
    `main`;
  - clicking "Source checks:" reveals "Check sources now". With the Shell,
    this lives in the sidebar portal, which is still in the document, so it
    passes.
- `live.spec:39-47`: "Real source metadata · private server saves ·
  generation off" is visible on desktop **and** 390px.
- `live.spec:97-100`: `navigation "Research workspace"` contains a visible,
  clickable link `/Library/` at 390px.
- `live.spec:215-227`:
  - the first Tab reaches "Skip to main content", and Enter focuses `main`;
  - at most 16 Tabs reach the reader's "Your notes". Keep sidebar
    focusables out of `main`; the bar comes after the content.
- **Free to change:** brand text, "Local workspace" label, sidebar note,
  nav labels other than Radar and Library, icons, `aria-current`.

## 4. Copy that must stay character-for-character

The full list is in recon §(c). These are the most at-risk during a
redesign:

| Group | Strings |
|---|---|
| Shell | "Skip to main content" · "Real source metadata · private server saves · generation off" · nav label "Research workspace" |
| Today | `h1` "What changed." · "5 min" / "15 min" / "45 min" · "Undo last change" · "Check sources now" · `Source checks: N of M available` · `${n} limited source windows` · "No successful check recorded" · "Generation awaiting approval" |
| Today empty and failure states | "Make your first bounded check." · "No matching items in the available checks." · "Nothing new matched this reading window." · "No fictional items have been substituted." · "Retry connection" |
| Today activity and edition | "Edition details" · "Continue your question" · "Source and pin options" · "Pin this question" · "Unpin saved item" |
| Reader | "Save question" · "Mark read" · "Save to Library" · "Archive" · "Your notes" · "← Library" / "← Today" / "← Radar" |
| Library | "Resume this question →" · "No items in this view." · "Export notes as Markdown" |
| Radar | "Stored source records" |
| Review | "Save judgment for candidate N" · radios Useful / Maybe / Irrelevant |

Keep these as visible text or accessible names exactly as today. Visual
restyling (case, weight, icons beside them) is fine. **Do not uppercase via
the text itself**: use `text-transform`, which does not change the
accessible name in jsdom.

## 5. E2E specs (live; run on the local stack)

| Spec | Pins | Plan |
|---|---|---|
| `readiness.spec.ts:16-21` | `.daily-item h3` placed after the `h2` "Continue your question"; on mobile, title y < 800 | Keep class `daily-item` on `FocusPaper` and the title as an `h3`. Keep `ActivityCard` (`h2` "Continue your question") above it in the stage. |
| `readiness.spec.ts:23` | "Edition details" visible | Keep the Edition details disclosure in the stage, not the drawer |
| `live.spec.ts:323-379` | Exactly one `.workspace-activity` with one link plus the "Source and pin options" summary | Keep the class and structure |
| `live.spec.ts:176-201` | `.workspace-receipt` contains "request_count" | Keep the class on the Operations receipt |
| `live.spec.ts:196-200, :601-606` | axe: no serious/critical | New palette must pass |
| `workspace-e2e/daily.spec.ts` | Fictional preview tier | Must stay green. Don't touch `daily.css` or the daily components. |

If a spec must change because it pinned old layout (e.g. it counted cards on
Today), change it minimally and record why in STATUS.

## 6. New tests to add

These are required for coverage (lines 99.11% global) and for the owner's
new behaviour:

| File | Covers |
|---|---|
| `tests/workspace/palette.test.ts` | Scoped palette contrast floors in both themes; dark blocks identical |
| `tests/workspace/queue.test.ts` | `todayQueue`, `libraryQueue`, `resolveFocus` (rules 1–3), `neighbours`, `readerTarget`, `coverSeed` |
| `tests/workspace/urlState.test.ts` | `useQueryParam` / `setQueryParam`, popstate, replace vs push |
| `tests/workspace/shell.test.tsx` | Landmarks, slots inline vs portal (never twice), drawer, status line, footer links |
| `tests/workspace/shortcuts.test.tsx` | Key → `data-command` click, guards (inputs, disabled, modifiers), `g`-sequences, `/` focus, composer submit |
| `tests/workspace/today-controller.test.tsx` | Multi-item queue order, focus default, prev/next by button and key, `?focus` persistence and popstate, auto-advance on dismiss/snooze, undo returns, last item disables next, queue row names and `aria-current`, single `article`/`status`/`h1` |
| `tests/workspace/mascot.test.tsx`, `cover.test.tsx` | Rendering, moods, determinism |
| `tests/workspace/palette-command.test.tsx` | ⌘K / Ctrl+K open, lists enabled commands, filter, Enter, Esc, focus return |
| `tests/workspace/api.test.ts` (extend) | `normalizeReaderReturnTo` keeps a valid `focus`, drops a hostile one |
| Reader, Radar, Library, Review tests (extend) | Focus params, prev/next hrefs, Review keys `1` / `2` / `3` |
