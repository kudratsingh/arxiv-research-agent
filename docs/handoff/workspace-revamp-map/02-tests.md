# Workspace test inventory: what pins the current DOM and behaviour

The current tests don't block a single-focused-paper Today by themselves: every unit test that renders Today uses a one-item edition. What breaks them is **duplicate accessible names** and **moving controls out of the component the test renders**. Unit tests render `LiveToday`, `LiveRadar` and the other pages without the Shell, and run under jsdom with CSS turned off, so anything hidden only by CSS still counts as a match.

## 0. Runners and configs
- **Vitest**, unit project (`vitest.config.mts:450-476`): jsdom, `globals: true`, `css: false`, includes `tests/**/*.test.{ts,tsx}`, `@` alias, a stub for `next/font/local`, setup file `vitest.setup.ts` (jest-dom, `cleanup`, `uninstallFakeEventSource`, `clearTestTheme`).
  - **Global coverage thresholds** (`vitest.config.mts:441-446`): statements 98.15, branches 94.0, functions 91.8, lines 99.11. New Today, queue and control-bar code needs its own tests or coverage drops below these.
- **`web/playwright.workspace.config.ts`**: `testDir ./workspace-e2e`, `next dev` on :3126 with **`WORKSPACE_PREVIEW=1` only**. It runs `daily.spec.ts` against the **fictional preview** (`/today`, `/interests`, `/library`, i.e. `components/daily/*`), not the live routes.
  - Projects: desktop 1440×1000 and mobile Pixel 7 at 390×844.
  - The only live-workspace link is the shared `daily.css`, which `Shell.tsx:7` imports.
- **`live-workspace-e2e/playwright.config.ts`**: runs `live.spec.ts` and `readiness.spec.ts` against an existing stack (`WORKSPACE_LIVE_URL` or `127.0.0.1:3137`), desktop 1440×1000 and mobile 390×844, workers 1.
- **`playwright.scientific.config.ts`**: runs only `scientific-sample.walkthrough.ts`.

## 1. Inventory by component

### A. WorkspaceShell / `app/(live)/template.tsx` / `layout.tsx`
- **`experience.test.tsx:122`** "keeps a separately labelled live shell and preserves preview access"
  - Renders `<WorkspaceShell><p>Child</p></WorkspaceShell>`.
  - `link /Fictional preview/` has href `/today` (`Shell.tsx:37-39`).
  - `link /Radar/` has href `/workspace/radar` (nav, `Shell.tsx:10-16,55-63`).
  - `getByRole("main")` contains "Child" (`Shell.tsx:83`).
- **`routes.test.tsx:47`** "requires an explicit live flag…"
  - `Layout()` throws "not found" unless `WORKSPACE_LIVE=1`; otherwise it returns its children.
- **`routes.test.tsx:56`** "mounts the real Today in its own shell…"
  - Renders `<Template><TodayPage/></Template>`.
  - `findByRole heading level 1` has text "What changed".
  - `getByRole("main")` contains that h1.
  - `link /Fictional preview/` has href `/today`.
  - Clicking `getByText(/Source checks:/)` reveals button "Check sources now".
- **`live.spec.ts:39-47`**
  - h1 contains "What changed".
  - `getByText("Real source metadata · private server saves · generation off")` is visible, on desktop and mobile (`Shell.tsx:46`).
- **`live.spec.ts:97-100`**
  - `getByRole("navigation",{name:"Research workspace"}).getByRole("link",{name:/Library/}).click()` must work at 390px.
  - Today this works because `daily.css:784-805` turns the sidebar nav into a visible top row on mobile.
- **`live.spec.ts:215-227`**
  - First Tab focuses link "Skip to main content" (`SkipLink`, `Shell.tsx:22`).
  - Enter focuses `getByRole("main")` (`#main tabIndex=-1`).
  - At most 16 further Tabs must reach the Reader link "Your notes".
- **Not asserted anywhere:** brand text "Research workspace" / "A place to follow a question.", "Local workspace", the sidebar note, "Research a question ↗" (live shell), the nav labels Today / Interests / "Sources & checks", the icons, and `aria-current`.

### B. LiveToday (`Today.tsx`) and the Common pieces it renders
The fetch mock is at `experience:34-115` and `stage1:73-119`. All calls go through `workspaceRequest` (`api.ts:47-67`): POST with a JSON body when a body is given, otherwise GET with `no-store`.

**`experience.test.tsx` (Today tests):**
- **`:137`** "shows a real stored edition, check receipts and durable undo"
  - Link named exactly "A controlled retrieval study", href contains `arxiv%3A`.
  - Click `getByText(/Source checks: 1 of 2/)`, then `getByText(/No successful check recorded/)` (`Common.tsx:211,237`).
  - Click button `/^Save A controlled/` → POST `reading` with `{work_id, revision, request_id, data:{status:"saved", anchor, version_id, snoozed_until:null}}`. Status contains "Saved on the server: saved".
  - Click "Undo last change" → POST `reading`. Status contains "unread".
  - Click `/^Snooze one day/` → POST `reading` with status `snoozed` and `snoozed_until` = now + 24h. Then `queryByRole("article")` must be null.
- **`:160`** "creates a genuinely different reading-window edition and keeps model calls off"
  - Click "5 min" → POST `profile` `{revision:1, request_id, data:{…minutes:5}}`, then POST `edition` `{}`, then GET `state` (`Today.tsx:123-125`).
  - `waitFor` an `edition` call; `profile.minutes` becomes 5.
  - Button `/Generation awaiting approval/` is disabled (`Common.tsx:256-258`).
  - Click `/Source checks:/`, then "Check sources now" → POST `refresh` with body `toEqual({source_ids:[]})`.
- **`:178`** "distinguishes no edition, successful emptiness, failed checks and connection failure"
  - `findByText` exact for each state: "Make your first bounded check.", "No matching items in the available checks.", "Nothing new matched this reading window." (`Today.tsx:219,229-230`).
  - When `state` returns 503: "No fictional items have been substituted.", then button "Retry connection" (`Common.tsx:173-176`), then GET `state`, then h1.
- **`:214`** "does not silently retry a conflicting reading state"
  - `reading` returns 409; click `/^Dismiss/`; status contains "another tab"; exactly one `reading` call.
- **`:223`** "shows committed partial source results…"
  - `getByText(/Source checks: 1 of 1 available/)`, `getByText("1 limited source windows")` exact, title link present.
- **`:244`** "pins an earlier edition's metadata and reader link…"
  - Link "An earlier controlled retrieval study" with href containing `version=arxiv%3A2610.00001%3Av1`.
  - Text "An earlier retrieval abstract." exact.
  - **No** link named "A controlled retrieval study".
- **`:266`** "does not substitute newer source material…"
  - Text `/Their newer versions have not been substituted/` (`Today.tsx:213-214`); no `article`.
- **`:936`** "does not claim a failed refresh or reading-window change succeeded"
  - `refresh` returns 503 → status "retry when the service is available"; title link still present.
  - `profile` returns 409 on "45 min" → status "another tab"; minutes stay 15.

**`stage1.test.tsx` (Today via ActivityCard compact, `Today.tsx:174-181`):**
- **`:124`** "shows the server's edited-earlier-question activity…"
  - `findByText("An earlier question, edited most recently")`; "Not the newest saved activity" is absent.
  - Link "An earlier controlled retrieval study →" with href containing `entry=entry-a` and `version=arxiv%3A2610.00001%3Av1`.
  - Text "Latest activity · your question".
- **`:168`** "pins and unpins through revision-guarded preferences…"
  - Click "Pin this question" → POST `profile` matching `{revision:1, data:{pinned_entry_id:"entry-a"}}`.
  - Text "Pinned · your question"; **no** `edition` call.
  - Click "Unpin saved item" → pinned becomes null; text "Latest activity · your question".
- **`:189`** "keeps a failed pin unconfirmed…"
  - `profile` returns 409 → status "another tab"; the retry reuses the same `request_id`.

**`readiness.spec.ts:5`** "Today puts the saved thread and first reading item within reach"
- POST `/api/workspace/entries` to seed an entry.
- Heading "Continue your question" (`ActivityCard.tsx:31,61`) must sit above `.daily-item h3` `.first()` on the y-axis.
- On mobile, that first `h3` must have y < 800.
- `getByText("Edition details")` must be visible (`Today.tsx:258`).

**`live.spec.ts:322-381`** (inside the test at :252)
- `.workspace-activity` contains the latest body.
- Click text "Source and pin options" (`ActivityCard.tsx:95`), then "Pin this question"; `.workspace-activity` contains "Pinned · your question".
- `.workspace-activity` `getByRole("link")` must be a single link; clicking it focuses `#workspace-entry-<id>`.
- "Unpin saved item"; then "Latest activity · reading location".
- Playwright strict mode means `.workspace-activity` must match exactly one element.

### C. WorkCard (direct unit tests; also used by Today, Library and Radar)
- **`retained.test.tsx:85`**
  - `render(<WorkCard item status={vi.fn()}/>)`.
  - Text "PDF excerpts" (`WorkCard.tsx:38`) and `/Selected original PDF pages/` (`:87`).
  - Link "Read & investigate →" with href containing the encoded `first_anchor` (`:101-113`).
- **`retained.test.tsx:93`**
  - With `versionId` = latest: no "PDF excerpts". After a rerender with the earlier `versionId`: "PDF excerpts" appears.
- **Accessible names:** `aria-label` is `Save|Unsave ${title}`, `Dismiss ${title}` and `Snooze one day ${title}` (`WorkCard.tsx:119,131,139`).

### D. ActivityCard, AllocationReceipt, InterestCoverage (`activity.test.tsx`, `stage1.test.tsx`)
**`activity.test.tsx`:**
- **`:23`** With no work: `/source is unavailable in the loaded view/` and "A reading location is saved for this source version."; **no** link and **no** button.
- **`:41`** Link `${title} →` with href containing the encoded version_id. After rerender: link "Earlier retained source version →" with href containing `old%3Aretained%3Av1`.
- **`:71`** Button "Pin this next action" → `onPin("action-id")`; button "Pin this item" → `onPin("legacy-entry")`.
- **`:104`** `/no recorded exploration allocation/` and `/not-configured/`.
- **`:133`** "1 exploration item" (exact), `/among 9 selected \(11.1%\)/`, "Matching terms available · no connected source", "None for this selection", "No adapter currently monitors this custom interest."

**`stage1.test.tsx`:**
- **`:410`** `/15 min · 0 exploration items/`, `/among 3 selected \(0%\). Requested cap: 30%/`, `/45 min · 2 exploration items/`, `/22.2%/`.
- **`:439`** Click "Inspect this edition’s allocation", then "7" (exact), `/no items/`, `/no recorded exploration allocation/`.
- **`:362`** (Interests)
  - Region "What these interests actually monitor"; click "Neural architectures".
  - Expect `/transformer, attention/`, "arXiv cs.LG", "Computer Science", "Browse only · no matching vocabulary".
  - Typing in textbox "Your current research question" shows `/Your draft is not applied here yet/`.

### E. LiveReader, RetainedSourceReader, SyntheticWorkbench
**`experience.test.tsx`:**
- **`:280`** Heading "Retained feed excerpt"; "Anchor: excerpt:0"; no "Retained source abstract".
- **`:294`** Type into textbox "Your question"; `entries` returns 503; "Save question" → POST `entries`. Status contains "still here"; draft kept in `sessionStorage`. Retry → "saved on the server", with the same `request_id` and `id`.
- **`:314`**
  - Recovered value "Recovered unsaved text"; text "Notes on other source versions".
  - Combobox "Source version" → h1 "An earlier controlled retrieval study"; link "Open original source ↗" points at the v1 URL; `/You are reading an earlier retained version/`.
  - "Edit note", textbox "Your note", "Save note" → `entries` `data.version_id = v1`.
  - "View latest source version".
- **`:378`**
  - Hash restore: `/Resumed source passage at character offsets 2–12/`.
  - Selection inside `.daily-source-text p` → `Selected source passage: “…”`; saved anchor is `abstract:0:N`.
- **`:414`** (`it.each`, abstract and excerpt) Code-point offsets: `#source-anchor`, `.daily-source-text p` textContent, anchor `${scope}:9:14`, `/…9–14/`.
- **`:485`**
  - `/No abstract or full text was acquired/`; clicking link "Your notes" sends a POST `reading`.
  - Combobox "Save as" → `next-action`; textbox "Your next action"; "Save next action" with a 409 → "another tab".
- **`:510`** "This source is not in the loaded workspace."
- **`:519`** "This retained source version is unavailable."
- **`:872`**
  - "draft recovery is unavailable", `/Draft recovery is unavailable. Copy your text/`.
  - "Save to Library" with a 409; "Mark read" → status `read`; "Archive" → `archived`.
- **`:905`** "is saved on the server"; "Edit question"; "Cancel edit" → "saved note was not changed".

**`stage1.test.tsx`:**
- **`:206`**
  - `#workspace-entry-entry-a` receives focus; link "← Library" has href `/workspace/library?view=notes`.
  - `#source-anchor` text "earlier"; "Edit question" inside the entry.
- **`:241`** "Save or explicitly discard", "Discard unsaved draft", `entries` body matching `{id:"entry-a", revision:2, data:{version_id, anchor}}`, "Pin question".
- **`:287`** `/That saved item is unavailable in this account/`; link "← Today" has href `/workspace/today`.

**`retained.test.tsx`:**
- **`:74`** Heading "Retained document excerpts"; GET `materials/<MAT>`.
- **`:143`**
  - Button "Find retained PDF excerpts"; label "Retained document"; regions `/Original page 3, characters/` and `/…7…/`.
  - `/This is an excerpt of the paper/`, link "Open original PDF ↗".
  - `.workspace-retained-text mark`; summary "Source version, hash and extraction receipt"; region "Retained source provenance".
  - Button "Return to this version’s abstract or metadata".
- **`:190`** "Mark read" → `reading` `data.anchor`; link "Understand"; **`getAllByRole("status")` has length 1**.
- **`:231`** `Anchor: material:…`.
- **`:259` / `:356`** `/Retained material could not be opened/`, "notes and saved anchor are unchanged".
- **`:283`** `/No document pages are retained/`.
- **`:323`** `#notes` receives focus, then a Tab lands on "Save as".
- **`:368`** "Understand", "Choose retained source context", "Source context", "Preview exact synthetic request", "Run synthetic workflow · $0", `/Inspect retained evidence/`. `#source` receives focus; the hash contains the encoded anchor.
- **`:413`** `/Equation and table structure is not reconstructed/`.
- **`:453`** "← Radar", heading "Source metadata", `/Add a research question in Interests/`, "Anchor: metadata:0", "Remove from saved items".

**`synthetic.test.tsx` (`:100`–`:614`, all against SyntheticWorkbench)**
- Endpoints: `materials`, `materials/<id>`, POST `generation/preview` `{kind, material_ids, span_ids, question}`, POST `generation/jobs` `{expected_digest, material_ids, request_id…}`, `generation/jobs/<id>/advance|cancel|recover`, GET `generation/jobs`.
- Asserted copy is listed in section (c).

### F. LiveLibrary and Import
- **`experience:601, :638, :671, :780, :834`**
  - POST `import/preview` (with `import_profile`), POST `import/apply` (with `digest`; the record must be the same across retries), POST `manual` `{value}`.
- **`experience:1003`**
  - Uses WorkCard's `/^Unsave A controlled/` and `/A newer source version is available/` (`WorkCard.tsx:68`).
  - Combobox "Library view" with `rerender`; links "Resume this question →", "A read source"; text "No items in this view."
- **`stage1:302, :337`**
  - Link "A saved source without notes".
  - "Resume this question →" with href containing `return_to=%2Fworkspace%2Flibrary%3Fview%3Dnotes` and `entry=entry-a`.
- **`live.spec:97-106`**: link `/Export notes as Markdown/` triggers a `.md` download.
- **`live.spec:324-357`**: Library view "notes"; article filtered by text; "Resume this question →"; "← Library".

### G–I. Interests, Radar, Operations
- **Interests:** `experience:548, :579, :957`; `live:167-171` (`/384 catalogue entries/`).
- **Radar:** `experience:706, :1116`
  - GET `items?…` with `days=30`, `cursor=next-page`, `status=read`.
  - The URL gets `as_of=`; popstate restores filters.
  - `live:154-162`: heading "Stored source records", URL `q=retrieval`.
- **Operations:** `experience:744, :1074`
  - POST `refresh` `{source_ids:["arxiv-cs-lg"]}`; POST `schedule` with `data` matching `{enabled:false, local_time:"08:15"}`.
  - `live:176-201`: `.workspace-receipt` (`Operations.tsx:123`) contains "request_count"; axe reports no serious or critical violations.

### J. CandidateReview (`review.test.tsx:113`–`:418`; `live.spec:402`)
- Endpoints: GET `state`, GET `review?packet_id=`, POST `review/prepare` `{request_id}`, POST `review/feedback` `{packet_id, work_id, version_id, revision, label, reason, request_id}`.
- Shape: 30 radios (3 per candidate), articles named by title, URL `?packet=<id>`.

### K. api and drafts (`api.test.ts:178`–`:292`)
- POST `/api/workspace/profile` with `Content-Type: application/json` and no `credentials`.
- GET uses `no-store`; 409 → "another tab"; 401/403/503 → `WorkspaceError`; a 15s timeout applies.
- `readerHref` encoding; `displayDate` returns "Date unknown"; draft scoping and size bounds.

### L. Preview-only (`components/daily/*`): affected only through shared CSS, ThemeToggle or SkipLink
- `tests/daily/experience.test.tsx:21-200`, `tests/daily/routes.test.tsx:200-221`, `store.test.ts`.
- `routes.test.tsx:107` (PreviewLibrary "Download preview JSON for explicit import").
- `workspace-e2e/daily.spec.ts`:
  - `:5` runs a full axe pass (wcag2a/2aa/21aa) and requires `scrollWidth <= innerWidth`.
  - `:127` radio "Dark" sets `data-theme=dark` and runs axe.
  - `:140` keyboard flow: "Skip to main content", then `#main`.

### M. Static scans that will hit a restyle
- **`tests/patterns/TraceSpine.test.tsx:489-496`**: only three files under `components/` may contain a literal `role="status"`: `daily/Announcement.tsx`, `patterns/TraceSpine.tsx` and `workspace/Common.tsx`.
- **`tests/tokens.test.ts:709-747`**: no hex, `rgb()` or `hsl()` literal anywhere in `web/` outside `app/tokens.css`. The new black/white/red palette must be added as tokens there, and the contrast checks recompute from that file (`:422`).
- **`tests/fonts.test.ts:225`**: no `font-family` outside `tokens.css`.
- **`tests/primitives/policy.test.tsx:201-208`**: no `outline:none` or `outline:0` without a replacement in any `.css` file.
- **`tests/budgets.test.ts:121-127,212`** and `budgets.json`: the `workspace/*` routes are budgeted.
- **`tests/shell/routing.test.ts:62-102`**: the exact route list, and every page must live inside the `(live)` group.

## (a) What breaks if Today shows ONE focused paper and lists the rest as queue links or buttons
Every unit test of Today uses `workspace()`, whose edition contains exactly one work (`fixtures.ts:108,131`). Nothing breaks from "only one card" itself. These do break:

1. **Duplicate title link.** If a queue entry is a link whose name equals the title (or the edition-pinned title), these fail with "multiple elements":
   - `getByRole("link",{name:"A controlled retrieval study"})` at `experience:143, :241, :946`.
   - `"An earlier controlled retrieval study"` at `experience:252`.
   - `experience:262` requires **no** link named "A controlled retrieval study" when v1 is pinned. A queue that shows the latest title would break it.
   - The focused title must stay a link to `readerHref`: `experience:144` checks for `arxiv%3A`, `:257` for `version=…v1`.
   - Fix: make queue entries buttons, or give them distinct names.
2. **`<article>` count.** `experience:158` (after Snooze) and `:275` (unavailable version) require `queryByRole("article")` to be null. Queue items must not be `<article>`, and the empty focus stage must render none.
3. **Action buttons moved to the control bar:**
   - `/^Save A controlled/` (`experience:150`) and `/^Snooze one day/` (`:157`) need names that *start* with those words plus the title. A bare "Save" or "Snooze" breaks them.
   - `/^Dismiss/` (`:219`) and "Undo last change" (`:155`) must each match **one** button. Keeping the WorkCard buttons *and* adding bar buttons breaks them.
   - Library relies on WorkCard's `/^Unsave A controlled/` (`experience:1047`), so don't strip the buttons out of the shared WorkCard. Fork a Today-only component instead.
4. **A second status region.** `getByRole("status")` at `experience:152, :156, :220, :943, :951` and `stage1:199` needs exactly one. Don't add `role="status"` or `<output>` (the TraceSpine scan forbids the literal anyway).
5. **A second h1.** `load()` (`experience:118-119`) and `routes:62` use `findByRole heading level 1` and expect "What changed". The focused paper's title must not be an h1.
6. **Controls moved out of `LiveToday` into a Shell sidebar.** `LiveToday` is rendered *without* the Shell in experience and stage1, so all of these must still be rendered by `LiveToday` (or by its subtree, laid out by CSS) and appear **once**:
   - "5 min" and "45 min" (`experience:164, :950`)
   - "Check sources now" (`:173, :942`; `routes:73`)
   - `/Source checks: N of M available/` (`:145, :172, :237, :941`; `routes:71`)
   - "1 limited source windows" (`:239`) and `/No successful check recorded/` (`:147`)
   - "Generation awaiting approval" (`:170`)
   - The empty-state headings (`:185, :191, :200`), and "Pin this question" / "Unpin saved item" / the activity link (`stage1:153-202`)
   - A portal into a Shell slot fails here unless it falls back to rendering inline.
   - Under `css:false`, two copies kept for responsive layout both count, so it fails as a duplicate.
7. **Repeated abstract text.** "An earlier retrieval abstract." (`experience:260`) is an exact `getByText`. Don't repeat the abstract snippet in the queue.
8. **E2E:**
   - `readiness:16-21` needs a `.daily-item h3` below the h2 "Continue your question" and, on mobile, at y < 800.
   - `readiness:23` needs "Edition details" visible.
   - `live:323-379` needs exactly one `.workspace-activity` containing one link, plus the "Source and pin options" summary.
9. **No test covers multiple items in Today**, prev/next, or queue order. New tests are needed for those, and for the coverage thresholds. Build fixtures with `work({work_id…})` and push them into `editions[0].work_ids`.

## (b) What breaks if the Shell's header, preview bar or nav markup changes
- **`experience:129` / `routes:69`**: there must be a link containing "Fictional preview" with href `/today`.
- **`experience:131`**: exactly one link matching `/Radar/`, with href `/workspace/radar`, inside the Shell alone. A second Radar-named link in the Shell breaks it.
- **`experience:135`, `routes:65`, `live:220`**: exactly one `main`, which must contain the page's h1 and be the `#main` (`tabIndex=-1`) target of SkipLink.
- **`routes:62`**: the Shell must not render any h1 (for example a brand h1).
- **`live:44-47`**: the text "Real source metadata · private server saves · generation off" must stay visible on desktop and on a 390px mobile viewport.
- **`live:97-100`**: one `<nav aria-label="Research workspace">` containing exactly one link matching `/Library/`. It must be visible and clickable at 390px, so an off-canvas or collapsed sidebar fails on mobile. Changing the brand text is safe; changing the nav's aria-label is not.
- **`live:215-227`**: the first Tab must hit "Skip to main content". After main receives focus, at most 16 Tabs may reach the Reader's "Your notes". Don't insert focusable sidebar or control-bar elements inside `<main>` ahead of the page content.
- **`daily.css` is shared** with the preview (`Shell.tsx:7`, `DailyShell.tsx:6`). Editing shared classes changes the preview screenshots and axe results in `daily.spec:5, :99, :127`. Scope new styles under `.workspace-app` or a new file.
- **ThemeToggle is shared** with the preview: `daily.spec:129` checks radio "Dark", plus `tests/shell/themeToggle.test.tsx`.
- **Free to change:** brand copy, "Local workspace", the sidebar note, "Research a question ↗", the Today / Interests / "Sources & checks" labels, icons, and `aria-current`.

## (c) Copy asserted verbatim
Assume an exact or regex match unless the entry says "substring". Each group starts with its source file.

- **Shell** (`Shell.tsx`)
  - "Fictional preview" (regex)
  - "Radar" (regex)
  - "Library" (regex, scoped to the nav)
  - nav aria-label "Research workspace"
  - "Real source metadata · private server saves · generation off"
  - "Skip to main content"
- **Today** (`Today.tsx` / `Common.tsx` / `ActivityCard.tsx` / `AllocationReceipt.tsx`)
  - h1 "What changed" (substring)
  - "5 min", "45 min"
  - "Undo last change"
  - "Check sources now"
  - `Source checks: N of M available` (regex)
  - "1 limited source windows" (template `${n} limited source windows`)
  - "No successful check recorded" (regex)
  - "Generation awaiting approval" (regex)
  - "Make your first bounded check."
  - "No matching items in the available checks."
  - "Nothing new matched this reading window."
  - "Their newer versions have not been substituted" (regex)
  - "Workspace unavailable"-path strings: "No fictional items have been substituted.", "Retry connection"
  - "Edition details" (substring)
  - "Continue your question"
  - "Source and pin options"
  - "Pin this question", "Pin this next action", "Pin this item", "Unpin saved item"
  - "Latest activity · your question", "Pinned · your question", "Latest activity · reading location"
  - "<title> →"
  - "Earlier retained source version →"
  - "source is unavailable in the loaded view" (regex)
  - "A reading location is saved for this source version."
  - "Inspect this edition’s allocation"
  - `N min · K exploration items` and "1 exploration item"
  - "among N selected (P%). Requested cap: X%"
  - "no items"
  - "no recorded exploration allocation"
- **Status notices** (substring)
  - "Saved on the server: saved", "unread"
  - "another tab"
  - "retry when the service is available"
  - "still here"
  - "saved on the server", "is saved on the server"
  - "Reading state saved on the server"
  - "Recovered your unsaved draft"
  - "unavailable"
- **WorkCard** (`WorkCard.tsx`)
  - aria-labels "Save ", "Unsave ", "Dismiss ", "Snooze one day " followed by the title (prefix regex)
  - "Read & investigate →"
  - "PDF excerpts"
  - "Selected original PDF pages" (regex)
  - "A newer source version is available" (regex)
- **Reader** (`Reader.tsx` / `RetainedSource.tsx`)
  - "Retained feed excerpt", "Retained source abstract", "Retained document excerpts", "Source metadata"
  - "Anchor: <anchor>"
  - "Your question", "Your note", "Your next action"
  - "Save question", "Save note", "Save next action"
  - "Edit question", "Edit note", "Cancel edit"
  - "Save as"
  - "Source version"
  - "Notes on other source versions"
  - "You are reading an earlier retained version" (regex)
  - "View latest source version"
  - "Open original source ↗", "Open original PDF ↗"
  - "Resumed source passage at character offsets a–b" (en dash)
  - `Selected source passage: “…”`
  - "No abstract or full text was acquired"
  - "Your notes", "Understand", "Source" (exact)
  - "This source is not in the loaded workspace."
  - "This retained source version is unavailable."
  - "Draft recovery is unavailable. Copy your text" and "draft recovery is unavailable"
  - "Save to Library", "Remove from saved items"
  - "Mark read", "Archive"
  - "← Library", "← Today", "← Radar", "← Candidate review"
  - "That saved item is unavailable in this account"
  - "Save or explicitly discard"
  - "Discard unsaved draft"
  - "Pin question"
  - "saved note was not changed"
  - "Add a research question in Interests"
  - "Find retained PDF excerpts"
  - "Retained document"
  - "Original page N, characters" (regex)
  - "This is an excerpt of the paper. Omitted pages have not been read or reconstructed."
  - "Source version, hash and extraction receipt"
  - "Retained source provenance"
  - "Return to this version’s abstract or metadata"
  - "Retained material could not be opened" and "notes and saved anchor are unchanged"
  - "No document pages are retained"
  - "Equation and table structure is not reconstructed"
- **Synthetic** (`SyntheticWorkbench.tsx`)
  - "Choose retained source context"
  - "Source context"
  - "Preview exact synthetic request"
  - "Run synthetic workflow · $0"
  - "Your notes, profile and reading history are excluded"
  - "Exact synthetic request JSON"
  - "Synthetic checkpoint · {ready|cancelled|queued|checking|interrupted}"
  - "1200 in / 300 out"
  - "This result has not qualified a real model"
  - "Inspect retained evidence"
  - "Synthetic check diagnostics · not a quality score"
  - "Synthetic check diagnostics"
  - "Inference · proposal, not verified", "Inference · unverified proposal"
  - "Include a question I type for this synthetic request"
  - "Optional request question"
  - "Synthetic workflow"
  - "Choose a smaller explicit passage set"
  - "The synthetic action did not complete"
  - "Advance one synthetic step"
  - "Cancel synthetic run"
  - "Load this version’s synthetic checkpoints"
  - "summary · interrupted · <id>", "summary · ready partial · <id>"
  - "Recover expired checkpoint"
  - "Reload checkpoint"
  - "No retained text is available"
  - "No synthetic checkpoints are retained"
  - "identical synthetic result reused from cache"
  - "Stopped: fixture_abstained"
  - "Cancellation requested"
- **Library and Import** (`Library.tsx` / `Import.tsx`)
  - "Preview browser import"
  - "1 new notes/questions/actions"
  - "Confirm import"
  - "Import saved on the server"
  - "Nothing was imported"
  - "Save an arXiv ID, DOI or source URL"
  - "Save source link"
  - "Access remains metadata"
  - "Import an export from a different preview address"
  - "Or paste exported preview JSON"
  - "Preview exported JSON"
  - "unsupported schema"
  - "Also import the preview interests and research question"
  - "Profile will change after confirmation"
  - "Preview JSON file"
  - "Export supplied original" (download `research-preview-original.json`)
  - "limited to 200 KB"
  - "file could not be read"
  - "Resume this question →"
  - "Library view" (options `saved`, `notes`, `read`, `archived`, `all`)
  - "No items in this view."
  - "Export notes as Markdown" (regex)
- **Interests** (`Interests.tsx` / `InterestCoverage.tsx`)
  - "Your current research question"
  - "Custom interests or watch terms"
  - "Daily reading window"
  - "Save interests and question"
  - "Discard draft and reload saved profile"
  - "Find a topic"
  - "Browse a field"
  - "Exclude these terms"
  - "Exploration allocation"
  - "No catalogue entries match. Add a custom interest."
  - "What these interests actually monitor"
  - "Browse only · no matching vocabulary"
  - "Your draft is not applied here yet"
  - "384 catalogue entries"
  - "Matching terms available · no connected source"
  - "None for this selection"
  - h1 "Follow a field.Or your own question." — the same h1 rule applies as for the h1 bullets under Radar, Library and Operations below.
- **Radar** (`Radar.tsx`)
  - "Search titles and abstracts"
  - "Source"
  - "Date window"
  - "Available material"
  - "Reading state"
  - "Apply filters"
  - "Next page →"
  - "First page"
  - "Stored source records"
  - "No stored items match these filters."
  - h1 "A wider view.Your terms, your pace." — compared without a space, so the `<br/>` structure is pinned (`routes:88-91`).
- **Library h1** "Keep the source.Keep your thinking." — same `<br/>` rule as the Radar h1.
- **Operations** (`Operations.tsx`)
  - "Recurring schedule disabled"
  - "Inspect this check’s receipt"
  - "Check arXiv cs.LG now" (template `Check {name} now`)
  - "Proposed local check time"
  - "Save preferences" (regex)
  - "Save preferences · keep schedule disabled" (regex)
  - "IANA timezone"
  - "Pause schedule and save preferences"
  - "remain disabled"
  - "Source timeout"
  - h1 "Know what was checked.And what wasn’t." — same `<br/>` rule as the Radar h1.
- **Review** (`CandidateReview.tsx`)
  - "N candidates · K labelled"
  - "Stored candidate N" (article names)
  - "Inspect retained source →"
  - "Only source metadata and the original link are available for this item."
  - "Optional reason for candidate N"
  - "Save judgment for candidate N"
  - "Useful", "Maybe", "Irrelevant"
  - "Your useful label is saved on the server", "Your maybe label is saved on the server"
  - "Clear this label"
  - "Reload saved review"
  - "saved judgment changed elsewhere"
  - "Discard draft and load saved judgment"
  - "Choose a small set to review."
  - "Prepare up to 10 candidates", "Prepare another candidate set"
  - "unavailable in this account"
  - "Saved candidate set"
  - "No eligible stored candidates."
  - "could not complete this request"
  - "Saved review reloaded"
  - "Candidate set prepared from stored metadata"
  - "Opening the saved candidate set…"

**Classes and ids pinned:**
- `.daily-item h3` — `readiness:18`
- `.workspace-activity` — `live:323`–`:379`
- `.workspace-receipt` — `live:189`
- `.daily-source-text p` — `experience:392, :435`; `retained:436, :505`
- `#source-anchor`
- `.workspace-retained-text mark`
- `#source`, `#notes`
- `#workspace-entry-<id>`
- `#retained-span-<id>` — walkthrough
- `#source mark` — `live:599`

## (d) Test helpers, providers and router mocks
- **No providers or wrapper.** Tests call plain `render()` from `@testing-library/react` with `userEvent.setup()`. Global setup is in `vitest.setup.ts`. `next/link` is not mocked and renders a plain `<a>`.
- **`next/navigation` is mocked per file with `vi.mock`.** A hook the factory doesn't define throws `[vitest] No "X" export is defined on the mock`:

  | File | Lines | Defines |
  |---|---|---|
  | `experience.test.tsx` | 16-19 | `usePathname` → `"/workspace/today"`; `useSearchParams` → `new URLSearchParams(window.location.search)` |
  | `routes.test.tsx` | 16-22 | same two hooks, plus `notFound` that throws `Error("not found")` |
  | `stage1.test.tsx` | 17-19 | `useSearchParams` only |
  | `retained.test.tsx` | 13-15 | `useSearchParams` only |
  | `review.test.tsx` | 8-10 | `useSearchParams` only |
  | `synthetic.test.tsx`, `activity.test.tsx`, `api.test.ts` | — | no mock |
  | `daily/experience.test.tsx` | 13 | `usePathname` → `"/today"` |
  | `daily/routes.test.tsx` | 198 | `usePathname` → `"/today"`, `notFound` |

  **`useRouter` is not defined in any of them.**
- **What this allows:**
  - Shell may use `usePathname` and `useSearchParams`.
  - `LiveToday` may use `useSearchParams` (defined in experience, stage1 and routes), but **not** `usePathname` (stage1 lacks it) and **not** `useRouter`.
  - Reader, Library and CandidateReview may use `useSearchParams` only.
  - WorkCard, ActivityCard, AllocationReceipt, InterestCoverage and SyntheticWorkbench may use none of these hooks.
- **URL state pattern.**
  - Components write the URL with `window.history.replaceState` or `pushState`: `Library.tsx:108`, `Radar.tsx:94`, `CandidateReview.tsx:76,177`, `Reader.tsx:398,439,747`.
  - Tests set the URL before render (`beforeEach` calls `replaceState(null,"","/workspace/today")`).
  - Tests simulate soft navigation with `rerender()` (`experience:1054-1069`, `stage1:317-320`) and back/forward with `fireEvent.popState(window)` (`experience:1141`).
  - Use the same pattern for a focused-item URL param (for example `?focus=`) rather than `useRouter`.
- **fetch.** `vi.stubGlobal("fetch", vi.fn(...))` per file.
  - Path is normalised with `new URL(url,"http://localhost").pathname.replace("/api/workspace/","")`.
  - In `experience.test.tsx`, `calls[].path` keeps the query string (`:44`), while `failures` is keyed by pathname.
  - Failure injection: `failures[path] = status`.
- **Fixtures.**
  - `fixtures.ts:5-154`: `work()` and `workspace()` — one work (arxiv:2610.00001, v2 "A controlled retrieval study" plus v1 "An earlier controlled retrieval study" / "An earlier retrieval abstract."), sources arXiv cs.LG (ok) and Hugging Face Blog (failed), one edition `ready_partial` at 15 min with `work_versions:{}` and `allocation:{}`, profile revision 1.
  - `materialFixtures.ts`: `MAT`, `SPAN`, `available()`, `retained()`.
  - `syntheticFixtures.ts`: `draft()`, `preview()`, `job()`.