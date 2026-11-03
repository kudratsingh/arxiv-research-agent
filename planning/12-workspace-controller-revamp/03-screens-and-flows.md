# 03 · Screens and flows

This file covers what the owner sees and does on every route. The
**capability inventory** to preserve lives in
[recon/04-surfaces.md](recon/04-surfaces.md); its §13 table is the source for
the placements below. **Exact labels** that tests pin are in
[recon/02-tests.md](recon/02-tests.md) §(c). When this file says "keep label",
copy it character for character.

## 1. Shell anatomy

### 1.1 Desktop (≥1024px), dark

```
┌─ canvas #0A0A0A ─────────────────────────────────────────────────────────────────────────────┐
│ ┌─ SIDEBAR (320–340px, surface, radius-lg) ─┐ ┌─ STAGE (surface, radius-lg) ───────────────────┐ │
│ │ [Jazzy] Research workspace     [◧] [◐]    │ │ workspace › today › 03 / 09        [↗ Read & investigate] │
│ │                                           │ │ ● Local workspace · Real source metadata · private server  │
│ │  ◷ Today                         G T      │ │   saves · generation off · 5/5 sources · ⌘K                │
│ │  ⌕ Radar                                  │ │ ─────────────────────────────────────────────────────────── │
│ │  ▤ Library                                │ │ ░░ red wash ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ │  ◎ Interests                               │ │  EDITION NOV 3 · 08:58          What changed.  (h1, 20px)  │
│ │  ↻ Sources & checks                        │ │  ┌──────────┐  PAPER · v2 · ABSTRACT · arxiv-cs-lg         │
│ │  ☑ Review                                  │ │  │  cover   │  Sparse Mixture-of-Experts Inference on a   │
│ │                                           │ │  │  tile    │  Single GPU via Expert Caching   (h3, 38px) │
│ │  UP NEXT · 9 · ready        [Today][Saved]│ │  │  cs.LG SM│  Hiro Tanaka, Lena Vogt · Published …       │
│ │  01  Budgeted Retrieval for Long-Hor…     │ │  └──────────┘                                              │
│ │      arxiv-cs-lg · abstract               │ │  We describe an expert caching policy for serving sparse   │
│ │  02  Planning with Language Models U…     │ │  mixture-of-experts language models on commodity hardware… │
│ │ ▌▮▮▮ Sparse Mixture-of-Experts Infer…  ●  │ │  (full abstract, 18px report serif, 68ch)                 │
│ │      arxiv-cs-lg · abstract · saved       │ │                                                            │
│ │  04  Tool-Use Agents Need Memory Hyg…     │ │  ▸ Why this appeared                                       │
│ │  …                                        │ │  AVAILABLE EVIDENCE  The source abstract; methods, tables  │
│ │                                           │ │  and full text have not been read.                         │
│ │  READING TIME   ( 5 )( 15 )(●45 )         │ │                                                            │
│ │  SOURCE CHECKS  ● 5 of 5 available  ▸     │ │  ▸ Edition details · 9 items · about 45 minutes            │
│ │                 [ Check sources now ]     │ │                                                            │
│ │  YOUR QUESTION  How can I build a…  ✎     │ │   ╭────────────────────────────────────────────────────╮   │
│ │  RESUME  Continue your question  ▸        │ │   │ ＋  Search stored papers, or type / for commands  ⌘K│   │
│ │                                           │ │   │ [cov] Sparse MoE…  ⏮  ( ↗ )  ⏭  ▬▬▬▬▬▭▭▭ 3/9       │   │
│ │  ── Generation awaiting approval (off) ── │ │   │       arxiv-cs-lg    Save  Dismiss  Snooze  Undo   │   │
│ │  Export notes ↗ · Fictional preview ↗     │ │   ╰────────────────────────────────────────────────────╯   │
│ │  Research a question ↗   Light Dark Sys   │ │                                                            │
│ └───────────────────────────────────────────┘ └────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Structure.** Sidebar and stage are two panels with an 8px gutter on
`canvas`. The sidebar scrolls on its own. The stage scrolls on its own, with
bottom padding equal to the control bar height plus 32px.

**DOM order and landmarks.** This is load-bearing for tests. See
[07](07-test-impact.md) §3.
1. `SkipLink` ("Skip to main content") comes first.
2. `<aside aria-label="Workspace controls">` (the sidebar). It contains
   `<nav aria-label="Research workspace">`, which must be **exactly one**
   per page and hold **exactly one** link matching `/Radar/`, one matching
   `/Library/` and so on.
3. `<main id="main" tabIndex={-1}>` holds the stage: the header, the
   page-rendered content, then **the control bar last in DOM order**. The bar
   is visually fixed at the bottom, so tab order runs content first, then bar.
4. The Shell renders **no `h1`**. The page owns its `h1`.
5. The Shell keeps a link containing **"Fictional preview"** with
   `href="/today"`, in the sidebar footer.
6. The status line text **"Real source metadata · private server saves ·
   generation off"** is visible at all widths. Put it in the stage header, not
   in the drawer.

### 1.2 Tablet (768–1023px)

The sidebar collapses to a 64px icon rail: nav icons, a queue mini-map of
numbered dots, and a theme toggle. An "Expand" button (`[◧]`) slides the
full sidebar over the stage as an overlay. The stage is full width and the
control bar stays.

### 1.3 Mobile (<768px, designed at 390×844)

```
┌───────────────────────────────┐
│ [Jazzy] Research   [☰ Queue]  │  ← top bar; ☰ opens drawer
│ ◷Today ⌕Radar ▤Library ◎ ↻ ☑ │  ← nav row, horizontally scrollable, ALWAYS visible
│ ● Local workspace · Real source│  ← status line (wraps), visible
│   metadata · private server    │
│   saves · generation off       │
├───────────────────────────────┤
│ What changed.        03 / 09   │
│ ┌──────┐ PAPER · v2 · ABSTRACT │
│ │cover │ Sparse Mixture-of-    │  ← focused title above the fold
│ └──────┘ Experts Inference…    │     (readiness.spec needs y < 800)
│ We describe an expert caching… │
│ ▸ Why this appeared            │
│ ▸ Edition details · 9 items    │
│                                │
│╭──────────────────────────────╮│
││ ⏮  Save  Dismiss  Snooze  ⏭ ││  ← compact bar: one row; input
││ ▬▬▬▬▬▬▭▭▭▭  3/9    ( ↗ Read )││     collapses behind a ⌕ button
│╰──────────────────────────────╯│
└───────────────────────────────┘
```

- The drawer (☰ Queue) holds everything that lives in the sidebar on
  desktop: the queue, reading time, source checks, question, resume, footer
  links and the theme.
- **The nav row is outside the drawer**, visible and clickable. This is
  e2e-pinned: `live.spec.ts:97-100` clicks the Library link at 390px.

### 1.4 Global keyboard map

These are suppressed when focus is in `input`, `textarea`, `select` or
`[contenteditable]`, or when a modifier other than the listed one is held.

| Keys | Action | Visible equivalent |
|---|---|---|
| `j` / `→`* | Next item in the current queue | ⏭ button |
| `k` / `←`* | Previous item | ⏮ button |
| `o` / `Enter`* | Open focused item in the reader (Read & investigate) | ↗ button |
| `s` | Save / Unsave focused item | Save button |
| `d` | Dismiss | Dismiss button |
| `z` | Snooze one day | Snooze button |
| `u` | Undo last change | Undo button (only when available) |
| `/` | Focus the control-bar input | Click the input |
| `⌘K` / `Ctrl+K` | Command palette | ⌘K chip in the status line |
| `?` | Keyboard shortcuts dialog | "Shortcuts" link in the sidebar footer |
| `g` then `t` / `r` / `l` / `i` / `s` / `v` | Go to Today / Radar / Library / Interests / Sources / Review | Nav rows (kbd hints on hover) |
| `[` | Collapse / expand sidebar | ◧ button |
| `Esc` | Close dialog or drawer; blur the input | — |

\* Arrow keys and Enter act **only** when focus is on `body`, the stage or
the control bar, never inside a scrolled text region where arrows scroll.

## 2. Shared pieces

### 2.1 Sidebar section order (desktop)

1. **Brand row.** Jazzy (`idle`, blinking), the wordmark "Research
   workspace", a collapse button and a compact theme cycle. The full
   `ThemeToggle` radios sit in the footer.
2. **Nav.** Today · Radar · Library · Interests · Sources & checks · Review.
   Review is promoted into the nav. Today it is only a link inside pages;
   adding it to the nav is allowed (no test pins nav length).
3. **Page slot.** The route's own sections (§3–§9), rendered by the page into
   the sidebar slot ([04 §3](04-architecture.md#3-slots-sidebar-and-control-bar)).
4. **Footer.**
   - "Export notes as Markdown ↗" (`/api/workspace/export`, `download`).
   - "Fictional preview ↗".
   - "Research a question ↗" (to `/`).
   - "Shortcuts".
   - `ThemeToggle`.
   - The storage line "Notes belong to your local account. A failed save
     stays a draft; it is never labelled saved." (11–12px, faint; keep it).

### 2.2 Stage header

- **Row 1.** A mono breadcrumb, `workspace › today › 03 / 09`, then
  right-aligned route actions. Today's action is the primary red
  **"Read & investigate"** link (`href = readerHref(...)`). This is a **link
  with the exact accessible name "Read & investigate →"** only if it is the
  *only* one on the page. See [07](07-test-impact.md) §2 for the duplicate-name
  rule.
- **Row 2.** The status line.
- Below the header is the page content. The page's `h1` sits there as a
  compact 20px title.

### 2.3 Status line content

`●` (ok / limited / failed source summary dot) **Local workspace** ·
**Real source metadata · private server saves · generation off** · `5/5
sources` · `⌘K`. The source fragment repeats the sidebar summary in short
form and must not duplicate the test-pinned "Source checks: N of M available"
text; use a different wording such as `5/5 sources`.

### 2.4 The control bar

```
╭────────────────────────────────────────────────────────────────────────────╮
│ ＋  Search stored papers, or type / for commands                     ⌘K │  row 1
│ ┌──┐ Sparse Mixture-of-Experts Inf…   ⏮   ( ↗ )   ⏭     ▬▬▬▬▬▭▭▭ 03/09   │  row 2
│ └──┘ arxiv-cs-lg · v2                 Save   Dismiss   Snooze   Undo      │
╰────────────────────────────────────────────────────────────────────────────╯
```

- **Width.** Same as the stage reading column (about 820px max), centred,
  16px from the bottom. `raised` surface, `radius-xl`, `shadow-bar`, 1px
  `border-subtle`.
- **Row 1, the composer.** A `<form role="search">` with an input labelled
  "Search stored papers" and the placeholder "Search stored papers, or type /
  for commands".
  - Enter with text: go to `/workspace/radar?q=<text>&days=7` (preserve other
    Radar defaults).
  - Text starting with `/`: filter the command palette inline, then Enter
    runs the top command. Examples: `/next`, `/save`, `/radar`, `/library`,
    `/check` (check sources), `/time 15`, `/theme dark`. The palette and the
    `/` commands share **one command registry**.
  - `＋` opens a small menu: "Save a source link" (goes to Library's quick
    add) and "Add a note" (opens the reader on the notes tab).
- **Row 2, the player.**
  - Left: a mini cover plus the 1-line title and source.
  - Centre: ⏮, a round red **open** button, ⏭.
  - Right: the progress bar and `03/09`.
- **Row 3, actions.** Text buttons with icons: **Save / Unsave**,
  **Dismiss**, **Snooze one day**, **Undo last change** (when available).
  Accessible names keep the existing prefixes plus the title. Examples:
  "Save Sparse Mixture-of-Experts…", "Snooze one day Sparse…". These are the
  only copies on the page; the focused card does not repeat them.
- **Per route.** The bar's content is route-provided through the control-bar
  slot. Routes with no queue (Interests) show only the composer row plus
  their own primary action, for example "Save interests and question".
- **Busy and errors.**
  - While a write is pending, the action buttons are `disabled` and Jazzy
    hops in the mini cover.
  - The outcome text goes to the page's single `Message` (`role="status"`).
    Render it **inside the bar** as a small line (row 0, above the input), or
    keep it in the stage. It must stay the *one* status region.

## 3. Today: the focused paper

**Queue** = Today's `visible` list, in edition order. Extract it as
`todayQueue(state, now)` in `lib/workspace/queue.ts` (logic from
`Today.tsx:33-62`): pinned versions are applied, and dismissed, archived and
actively snoozed items are dropped.

**Focus rule** (derived during render, no effects):
1. `?focus=<work_id>` if it is in the queue.
2. Else, if `?focus` names an item that just left the queue (dismissed or
   snoozed): the **next** visible item after its position in the full edition
   order, or the previous one if it was last.
3. Else the first item.

**Stage** (top to bottom):
1. Eyebrow `EDITION NOV 3, 08:58` (keep "Edition {date}" or "Your first
   local briefing") and the **h1 "What changed."** (keep it). Under it, the
   subtitle "A short reading list for your next question."
2. **Resume strip.** The existing `ActivityCard compact` (`.workspace-activity`
   with "Continue your question" and "Source and pin options", e2e-pinned).
   Render it as a one-line strip above the paper. It may collapse to a chip
   if no activity exists.
3. **Focused paper**, `<article class="daily-item ws-focus">`. It is the
   only `<article>` on the page and **only when an item exists**.
   - Cover tile (168px), then an eyebrow chip row: `PAPER` · `v2` · access
     label (`abstract` / `PDF excerpts` / `PDF text` / `excerpt` /
     `metadata`) · status chip if not unread (`saved`, `read`).
   - **`h3` title**, a link to `readerHref(...)` with the same target rule as
     `WorkCard`. The link name is the title.
   - Authors · `source_id` · "Published …" or "Publication date unknown".
   - **Full abstract.** No 320-char truncation on the focused card. Report
     serif, 68ch. Do not repeat the abstract anywhere else on the page.
   - Newer-version notice (existing copy) when applicable.
   - `details` **"Why this appeared"** (existing copy).
   - **"Available evidence"** caveat (existing copy and logic).
4. A missing-version notice (existing copy) when `ordered.length <
   work_ids.length`.
5. **Empty states** (keep headings verbatim, add Jazzy `sleepy`):
   - "Make your first bounded check."
   - "No matching items in the available checks."
   - "Nothing new matched this reading window."
6. A shortlist footer line (keep "That’s this edition’s shortlist. Its
   source check, profile revision N, and cutoff are retained.").
7. `details` **"Edition details · N items · about M minutes"** with
   `AllocationReceipt` (`.workspace-receipt`). Keep this in the stage: it is
   e2e-visible on mobile.

**Sidebar slot (Today):**
- `UP NEXT · {visible.length} items · {edition status}` with the queue rows.
  Optional chips [Today] [Saved] [Notes]: Saved and Notes are *shortcuts* to
  Library views (links), not filters on Today.
- **Reading time** (`fieldset` legend "Time for reading", buttons "5 min" /
  "15 min" / "45 min" with `aria-pressed`).
- **Source checks.** The `Coverage` disclosure, "Source checks: N of M
  available", with "Check sources now" and "Search all stored items →"
  inside. The full list expands inline.
- **Your question.** The research question text or "Add your current
  research question in Interests.", plus "Edit your interests ↗".
- **Generation boundary**, compacted: "Generation awaiting approval"
  (disabled) plus one line of the existing copy.
- Links: "Your saved work →" and "Review candidate usefulness →".

**Control bar (Today):** ⏮ ⏭ · open · Save/Unsave · Dismiss · Snooze one day
· Undo last change · progress.

**Flows.**
- **Save.** Bar or `s`: POST `reading` with the **same body as today**. The
  status reads "Saved on the server: saved." The queue row shows the
  bookmark glyph. Focus stays.
- **Dismiss / Snooze.** The item leaves `visible`. Focus advances to the next
  item through rule 2, with no extra state. The status reads "Saved on the
  server: dismissed." Undo restores the item, and focus returns to it because
  `?focus` still names it.
- **Prev/next.** `history.replaceState(null, "", "?focus=<id>")` (replace, so
  Back leaves Today instead of walking the queue). Scroll the stage to top,
  run the 160ms cross-fade, and do not move keyboard focus.
- **Open.** A normal link navigation to the reader with
  `return_to=/workspace/today?focus=<id>`.
  - This needs `normalizeReaderReturnTo` to **allow `focus` on
    `/workspace/today`**. Today it drops all Today params. Add `focus`
    validated as an existing `work_id` shape (≤500 chars, no control chars).
  - Add a unit test.
- **Reading time change.** Same three calls as today: profile → edition →
  state. The queue re-derives. If `?focus` is gone, focus falls to the first
  item.

## 4. Reader (`/workspace/items/[id]`)

Fragile areas are in [recon/03-reader.md](recon/03-reader.md) §5. The reader
keeps all its tabs and actions. Changes:

- **Sidebar slot:**
  - "Back to {Today | Library | Radar | Review}": the existing back link,
    whose label is test-pinned (e.g. "← Library").
  - **Up next.** The queue that `return_to` points at:
    - Today: `todayQueue`.
    - Library: the view filter over `state.works`.
    - Radar: the current page is not in state, so show only "Back to
      results", or cache the last result ids in `sessionStorage` (optional).
    - Review: the packet.
  - The reader's **section outline**: Source / Understand / Notes tabs as
    nav rows. Keep the tab ids `source`, `understand` and `notes`; stored
    anchors depend on them.
  - The version picker and retained-material info.
- **Stage.** The existing reader body, restyled: report serif for source
  text, mono for anchors.
- **Control bar.** ⏮ ⏭ go to the previous/next item's reader URL, built with
  the same `readerHref` target rule. Primary actions stay the reader's own:
  "Save question", "Mark read", "Pin this question" / "Unpin saved item"
  (labels e2e-pinned), plus the note composer. These use the reader's own
  `POST reading` path, not `useReadingActions`.
- **Tab order.** At most 16 Tabs from `main` to "Your notes" (`live.spec`).
  Keep sidebar items out of `main` and the bar after the content.

## 5. Radar

- **Sidebar slot.**
  - The filter form, stacked: "Search titles and abstracts", "Source", "Date
    window", "Available material", "Reading state", and "Apply filters".
    Keep all labels and options.
  - "Review a finite candidate set →".
  - **Results queue**, `page.items` as queue rows.
  - "First page" and "Next page →".
- **Stage.** The h1 "A wider view." with the italic "Your terms, your pace."
  (keep it), the eyebrow "Radar · actual stored metadata", and "No generated
  summaries". Below, "Stored source records · N on this page · stable
  observation cutoff", then the **focused result** using the same
  focus-paper component (with Radar's merged reading state), or the empty
  state "No stored items match these filters."
- **Focus param.** `?focus=` is added alongside the existing Radar params.
  `navigate()` keeps it.
- **Bar.** Same as Today. ⏭ on the last item of a page offers "Next page →".
- **The composer** drives this screen: Enter sets `q` and applies.

## 6. Library

- **Sidebar slot.**
  - View chips: **Saved · Notes · Read · Archived · All**. Keep the
    `<select>` "Library view" for test parity, or update its tests. Chips
    must write the same `?view=` via `replaceState`.
  - The queue of filtered works.
  - Quick add: "Save an arXiv ID, DOI or source URL", the input,
    "Save source link", and the disclaimer.
  - "Import preview notes" (`PreviewImport`).
  - "Export notes as Markdown ↗".
- **Stage.**
  - h1 "Keep the source." with "Keep your thinking." (keep it).
  - The focused work, followed by **its notebook entries** (questions,
    notes, next actions), each with "Resume this question →".
  - The empty state "Save something worth returning to." / "No items in this
    view." with "Back to Today →".
- **Bar.** Unlike Today, the card keeps its `WorkCard` Save/Unsave buttons,
  because Library tests use `/^Unsave …/` on WorkCard. **Either** keep the
  buttons on the card and give the bar only ⏮ ⏭ open, **or** move them to the
  bar with the same names and update the Library tests. Pick one per route;
  never both.

## 7. Interests

There is no queue. The sidebar slot becomes a **section index**: Question &
window · Streams · Topics · Terms & boundaries · Coverage, as anchor links to
form sections, plus "Profile revision N". The stage holds the whole form,
restyled with grouped cards. The bar holds the dirty-state line and **"Save
interests and question"** (primary), plus "Discard draft and reload saved
profile". It disables reading-time changes while a draft exists.

## 8. Sources & checks (Operations)

- **Sidebar slot.**
  - A sources queue: each source with a status dot plus a word (`ok`,
    `partial`, `failed`, `not checked`).
  - "Check sources now" (all).
  - The schedule summary ("Recurring schedule disabled" or the next check).
  - A count of recorded tasks.
- **Stage.** The focused source: name, status, last success, receipt
  (`details` "Inspect this check's receipt"); the schedule form; durable
  tasks; the generation note.
- **Bar.** ⏮ ⏭ between sources, "Check {name} now" if the API supports
  per-source checks (it posts `refresh {source_ids:[id]}`), and
  "Save preferences · keep schedule disabled" when the schedule draft is
  dirty.

## 9. Review (candidate usefulness)

- **Sidebar slot.** The "Saved candidate set" picker; "Prepare up to 10
  candidates" / "Prepare another candidate set"; "Reload saved review"; the
  candidate queue with label chips (Useful / Maybe / Irrelevant / Not
  labelled); "{n} candidates · {k} labelled"; the packet coverage; "How this
  set was selected".
- **Stage.** The focused candidate (existing `CandidateFeedback` content). Its
  native radios and "Save judgment for candidate N" stay **in the card**, so
  the form keeps its semantics.
- **Bar.** ⏮ ⏭ between candidates, plus a dirty-draft indicator.
- **Keys.** `1` / `2` / `3` set Useful / Maybe / Irrelevant on the focused
  candidate. They are suppressed in the textarea.

## 10. Global states

| State | Treatment |
|---|---|
| Loading (no state yet) | The Shell renders immediately. The stage shows a skeleton of the focus card plus "Opening your local workspace…" (keep). Jazzy `busy` in the brand. |
| Workspace unavailable (state fetch failed) | The `LoadingState` error box (critical style + ⚠), heading "Workspace unavailable", "No fictional items have been substituted.", and "Retry connection". Jazzy `alert`. |
| Service notice (partial failure after load) | `ServiceNotice` box at the top of the stage (critical style). |
| Source check running | Mascot `busy`. The button reads "Checking sources…". A status message. |
| Conflict (409) | Existing copy in `Message`. The bar actions re-enable. |

## 11. Command palette (⌘K)

- **Mechanics.** A native `<dialog>`, lazy-loaded on first open.
- **Sections.**
  - **Go to:** six routes plus the "Fictional preview" and "Research a
    question" links. Render these as **buttons** that call `location.assign`,
    not `<a>`. A second "Radar"-named link in the Shell would break
    `experience.test.tsx:131`.
  - **This paper:** Open, Save/Unsave, Dismiss, Snooze, Mark read (reader
    only).
  - **Workspace:** Check sources now, Reading time 5/15/45, Theme
    Light/Dark/System, Export notes, Toggle sidebar, Shortcuts.
- **Filtering.** Fuzzy match on label and keywords. ↑/↓ moves through
  results, Enter runs, Esc closes.
- **Registry.** Commands come from one registry that pages extend through
  the control-bar slot context.
