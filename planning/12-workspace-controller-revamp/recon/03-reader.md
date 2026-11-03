# Reader slice: paper reader and its sub-surfaces (read-only audit)

Paths below are relative to `/home/user/arxiv-research-agent/web`. Network calls go to `/api/workspace/<path>`. A call is GET when it has no body and POST when it does (`lib/api/client.ts:56-63`).

## 1. Component tree, state and hooks

**Route `app/(live)/workspace/items/[id]/page.tsx`**
- Server component. It awaits `params`, runs `decodeURIComponent(id)` and calls `notFound()` on a malformed id (9-15).
- It wraps everything in `<Suspense fallback={<p className="daily-muted">Opening your source…</p>}>` (17-19). The Suspense is required because `LiveReader` uses `useSearchParams`.
- The page renders inside `WorkspaceShell` via `app/(live)/template.tsx:10`, inside `<main id="main" tabIndex={-1} className="daily-main">` (`Shell.tsx:83-85`).
- `app/(live)/layout.tsx` returns 404 unless `WORKSPACE_LIVE=1`.

**`LiveReader({id})`** (`Reader.tsx:33-66`)
- `useWorkspace()` (34) returns `{state, setState, error, reload}`. `loading` is not used.
  - The hook has no cache and no context (`lib/workspace/useWorkspace.ts:6-37`).
  - Every mount does `GET state`, which returns the whole WorkspaceState (`works`, `editions`, `profile`, `sources`, …).
- `useSearchParams()` (35) reads `version` (36), `entry` (37) and `return_to` (38, run through `normalizeReaderReturnTo`).
- There is no `useRouter` and no `usePathname` anywhere in the reader slice.
- Render states:
  - No state yet: `<LoadingState>` (39), from `Common.tsx:15-36`. It shows `p.daily-muted[aria-busy]`, or on error `div.workspace-alert.error` with a "Retry connection" button that calls `reload()`, which does `GET state`.
  - Item not found: `div.daily-empty` with an h1 and the Link "Open Library →" to `/workspace/library` (41-53).
  - Otherwise: `<ReaderContent key={principal:work_id:version:entry}>` (55-65).
    - Because the key includes `version` and `entry`, any change to those search params remounts `ReaderContent`. This includes the reader's own `replaceState`: Next 16.4.4 patches `history.replaceState` so `useSearchParams` updates (`node_modules/next/dist/client/components/app-router.js:302-313`).

**`ReaderContent`** (82-927). All hooks sit before the early return at 454; any new hooks must go above that line.
- `initial`, a lazy `useState` (100-151). It:
  - picks a version from `entry.version_id || ?version || item.reading.version_id || item.version_id` (104-109);
  - reads `window.location.hash` (111-117). This is safe because `ReaderContent` only mounts client-side, after the fetch.
  - uses the first PDF anchor (`preferredAnchor`) only when there is no entry, no source-anchor fragment and no prior reading revision on this version (118-122);
  - calls `loadDraft` from sessionStorage (124) and returns `{version, fragment, scope, entryId, sourceAnchor, draft, recovery, notice}`.
- `versionId` (152).
- `active`, one of `"source" | "understand" | "notes"` (153-159). It starts as `"notes"` when an entry is requested, or from a `#notes` / `#understand` fragment.
- `draft: ReaderDraft` (160), `notice` (161), `busy` (162), `draftStorage` (163), `selection` (164), `pdfActive` (165).
- `sourceAnchor` (166-173), in this priority: entry/draft/PDF anchor, then a source-anchor fragment, then `item.reading.anchor` if the version matches, then `${scope}:0`.
- Refs: `source` (the abstract `<p>`, 174), `jumpToSource` (175), `attempts`, an idempotency map from fingerprint to request_id (176).
- Derived values:
  - `versions`, with a fallback that synthesizes a single version from `item` (177-195);
  - `material` (196-198), `sourceScope` (199), `knownPDF` (200);
  - `entries` and `otherEntries`, split by version (201-206);
  - `anchorMatch`, `start`, `end`, `sourceCharacters`, `hasPassage` (447-453).
- Effects:
  - (207-214) focus and center-scroll `#workspace-entry-<entryId>` on a deep link;
  - (215-222) after `onSource`, focus `#source` and center-scroll `#source mark`.
- Functions: `pin` (223-248), `editEntry` (249-265), `edit` (267-282, which writes the sessionStorage draft on every keystroke), `selectPassage` (283-305), `reading` (306-343), `save` (344-394), `tab` (395-411), `viewVersion` (412-446).

**`RetainedSourceReader`** (`RetainedSource.tsx:52-380`). It has `key={material.version_id}` (`Reader.tsx:689-702`).
- Props: `workId`, `versionId`, `anchor`, `onNavigate` (= `setSourceAnchor`), `onSelect`, `onActive` (= `setPdfActive`), `announce` (= `setNotice`).
- State: `materials` (69), `document` (70; this shadows the global, so the code uses `window.document` at 119), `loading` (71), `error` (72). Ref: `controller` AbortController (73).
- `parseMaterialAnchor` (12-24) parses `material:<id>:page:<n>:<start>:<end>`.
- Effects:
  - (78-103) when the anchor is a material anchor, it auto-fetches `GET materials/<id>` and calls `onActive(true/false)`;
  - (104) aborts on unmount;
  - (105-122) center-scrolls `#retained-span-<span_id>`.
- `originalPDF()` (26-50) accepts only https links from provenance.

**`SyntheticWorkbench`** (`SyntheticWorkbench.tsx:29-599`). It has `key={material.version_id}` (`Reader.tsx:738-754`).
- Props: `workId`, `versionId`, `announce` (= `setNotice`), `onSource`.
- State: `materials`, `material`, `kind`, `spanIds`, `includeQuestion`, `question`, `preview`, `job`, `history`, `busy`, `failure` (40-50).
- Refs: `attempts` (51), `stop` (52), `currentJob` (53). The unmount effect sets `stop` (54-59).
- Bounds: summary allows 4 spans / 8,000 B; deep dive allows 8 / 16,000 (60-61). `oversized` is computed at 70.
- Child `SyntheticDraft` (601-680).

**`lib/workspace/drafts.ts`**
- sessionStorage key `arxiv-agent.workspace-drafts.v1` (2). The scope is `JSON.stringify([owner, work, version])` (11-13).
- `ReaderDraft` = `{id, revision, body, kind: question|note|next-action, anchor}` (3-9).
- Limits: 250,000 characters (16, 58) and 40 entries (58). The functions throw when full or malformed (16, 24, 44, 59); callers catch this and set `draftStorage = false`.

## 2. User-facing controls

**Header (`Reader.tsx`)**

| Control | Label | Handler | Network |
|---|---|---|---|
| `Link.daily-link` (490-499) | "← " + Candidate review / Radar / Library / Today, chosen by the `returnTo` prefix | navigates to `returnTo`, `prefetch={false}` | none |
| `a.daily-link` (532-539) | "Open original source ↗" | opens `material.url \|\| item.url` in a new tab | none |
| `button.daily-secondary[aria-pressed]` (540-551) | "Save to Library" / "Remove from saved items" | `reading("saved" or "unread")` | POST `reading` |
| `button.daily-text-button` (552-558) | "Mark read" | `reading("read")` | POST `reading` |
| `button.daily-text-button` (559-565) | "Archive" | `reading("archived")` | POST `reading` |
| `select` in `label.workspace-form-stack` (568-585), only when there are 2 or more versions | "Source version"; options "{label} · latest observed / earlier retained version" | `viewVersion` | none; `replaceState`, which causes a remount |
| `button.daily-text-button` (590-595), only on an older version; not gated by `busy` | "View latest source version" | `viewVersion(item.version_id)` | none |
| `nav.daily-reader-tabs` `a` × 3 (598-616), `aria-current="location"` | "Source", "Understand", "Your notes" | `tab(id)`: focus the panel, `replaceState #id`, then call `reading()` | **POST `reading` on every tab click** |
| abstract `<p>` `onMouseUp` / `onKeyUp` (645-649) | (text selection) | `selectPassage` → sets anchor `scope:start:end` | none |

**Notes form (783-840)**
- `select` "Save as" with options Question / Note / "Next action · proposal" (784-796). Calls `edit({kind})`.
- `textarea#workspace-note-body`, labelled "Your {kind}": required, 6 rows, max 10,000 characters (797-807). Calls `edit({body})`.
- Submit `button.daily-button` "Save {kind}" / "Saving…", disabled when `busy` or the body is empty (809-814). Calls `save` → POST `entries` with `{id, revision, data:{work_id, version_id, kind, body, anchor}, request_id}`.
- `button.daily-text-button` "Discard unsaved draft" / "Cancel edit" (815-838). It clears the local draft only; no network.

**Saved entries (846-899), per entry**
- "Edit {kind}" → `editEntry` (866-871).
- `a` "Source context →" (872-883). This is a plain `<a>`, not `Link`.
- "Pin {kind}" / "Unpin saved item" → POST `profile` with `{revision, data:{...profile, pinned_entry_id}}` (884-898).
- Other-version links: `a` "{body[:100]} · {version_id} →" with the `entry` param (906-917).

**Version-unavailable view**
- Link "Choose the latest observed version →" (471-483).

**`RetainedSource.tsx`**
- "Find retained PDF excerpts" / "Opening retained material…" (206-214) → GET `materials?work_id&version_id`.
- `select` "Retained document", with the placeholder "Choose retained material" (223-242) → `open(id)` → GET `materials/<id>`. On success it calls `onNavigate` with the first span and `announce(...)`.
- "Return to this version’s abstract or metadata" (257-266) → `onNavigate("abstract:0")`. The anchor is hardcoded to `abstract:0`, even for excerpt or metadata scope.
- `a` "Open original PDF ↗" (287-296).
- `details.workspace-source-receipt` with summary "Source version, hash and extraction receipt" (298-325).
- `pre[role=region][tabIndex=0]` "Retained source provenance" (317-324).
- Per-span text selection → `onSelect(material:…)` (358-362, 169-195).

**`SyntheticWorkbench.tsx`**
- "Choose retained source context" (261-267) → GET `materials?…`.
- "Load this version’s synthetic checkpoints" (268-274) → GET `generation/jobs`.
- `select` "Synthetic workflow" (285-296), local only.
- `select` "Source context" (298-316) → GET `materials/<id>`.
- Span checkboxes inside `fieldset.workspace-span-picker` (334-371).
- Checkbox "Include a question I type for this synthetic request" (378-389).
- `textarea` "Optional request question", max 4,000 characters (390-404).
- "Preview exact synthetic request" (405-411) → POST `generation/preview`.
- `details open` "Inspect request JSON and permitted context" (434-446).
- "Run synthetic workflow · $0" (447-453) → POST `generation/jobs`, then up to 4 × POST `generation/jobs/<id>/advance`.
- History buttons "{kind} · {state} · {id}" (463-475), local only.
- "Reload checkpoint" → GET `generation/jobs/<id>` (504-510).
- "Cancel synthetic run" → POST `…/cancel` (512-517). It is not disabled by `busy`.
- "Advance one synthetic step" → POST `…/advance` (519-526). It is hidden while busy.
- "Recover expired checkpoint" → POST `…/recover` (527-537).
- `details` "Synthetic check diagnostics · not a quality score" (575-588).
- `SyntheticDraft` "Inspect retained evidence · …" (630-646) → `onSource(anchor)`. In `Reader.tsx:743-753` this sets `jumpToSource`, sets `active = "source"`, does `replaceState #anchor`, and sends POST `reading`.

**`Common.tsx`**
- `GenerationBoundary`: a disabled button "Generation awaiting approval" (109-111).

**Idempotency:** request_id is reused for the same fingerprint. Keep this. See `Reader.tsx:228-230, 320-322, 357-359` and `SyntheticWorkbench.tsx:155-157`.

## 3. Render order and classNames

1. `div.daily-page-meta`: the back `Link.daily-link` and `span.daily-eyebrow` "Source reader · retained {scope} / retained document text" (489-504).
2. `ServiceNotice`: `div.workspace-alert.error`, rendered only on error (505; `Common.tsx:38-48`).
3. `Message`: `p.daily-muted[role=status]`, always mounted (506; `Common.tsx:7-13`).
4. Optional `p.workspace-version-notice`, "That saved item is unavailable…" (507-512).
5. `header.daily-reader-header` containing:
   - `div.daily-item-meta` with three spans: kind, version_label, access_state;
   - `h1.workspace-reader-title`;
   - `p` with authors · published date;
   - `div.workspace-card-actions` (513-567).
6. Optional `label.workspace-form-stack` with the version `select` (568-585).
7. Optional `div.workspace-version-notice` for an earlier version (586-597).
8. `nav.daily-reader-tabs[aria-label="Reading sections"]` (598-616).
9. `div.daily-reader-grid` (617-924):
   - a. `section#source.daily-source-panel[tabIndex=-1][data-active]` (618-703):
     - `div.daily-section-heading` with `h2#retained-source-title` and a version span;
     - when `!pdfActive`: `p.daily-source-attribution`, `div.daily-source-text > p[ref=source]` (with `mark#source-anchor`), an optional `p.workspace-note-context`, and `div.daily-source-boundary` (containing `p.workspace-origin`);
     - then `section.workspace-retained-source`, which contains `div.workspace-toolbar`, `select`, notices, `details.workspace-source-receipt > pre.workspace-receipt`, and `section.workspace-retained-passage#retained-span-*[tabIndex=-1]` with `p.workspace-retained-text`.
   - b. `aside#understand.daily-understand-panel[tabIndex=-1][data-active]` (704-756):
     - eyebrow, `h2#understand-live-title`, the research-question `p`, `div.daily-thread`;
     - `section.workspace-synthetic`: `.workspace-card-actions`, `.workspace-form-stack`, `fieldset.workspace-span-picker`, `label.workspace-inline-checkbox`, `div.workspace-synthetic-preview`, `section.workspace-synthetic-result`, `dl.workspace-usage`, `div.workspace-synthetic-draft`;
     - `div.daily-generation`.
   - c. `section#notes.daily-notes-panel[tabIndex=-1][data-active]` (757-923):
     - intro `div`: eyebrow, `h2#your-live-notes`, `blockquote.workspace-version-notice`, `p.workspace-note-context` "Anchor: …", `p.daily-muted`;
     - `form` with `div.daily-form-footer`;
     - `div.daily-saved-entries`, containing `article#workspace-entry-*[tabIndex=-1]` (gets `.workspace-focused-entry` when focused) and `div.workspace-version-notice`.

**Layout (`daily.css`)**
- Grid is `1.2fr | minmax(260px, 1fr)` (595-600). Source sits left and Understand right. `#notes` spans the full row with its own two-column grid (640-648). Saved entries span the full row (672-674).
- At 850px and below, the grid becomes one column (729-734).
- At 600px and below (block 750-911), the grid becomes `display:block` and **`.daily-reader-grid > [data-active="false"] { display:none }`** (884-886). Tabs only switch visible panels on mobile.
- On desktop, all three panels are visible. `tab()` focuses with `preventScroll:true` (397), so clicking "Your notes" moves focus but does not scroll.

**`daily.css` is shared with the fictional preview** (`components/daily/DailyShell.tsx:6`). The preview reader `components/daily/Reader.tsx` uses the same `daily-reader-*`, `daily-source-*` and `daily-notes-panel` classes. Scope the new styles under `.workspace-app` (`Shell.tsx:21`), or the preview and `tests/daily/*` will be affected.

## 4. Back navigation and adding "next paper"

**Back navigation**
- `return_to` is whitelisted by `normalizeReaderReturnTo` (`lib/workspace/api.ts:113-140`). Only these are allowed, and anything else falls back to `/workspace/today`:
  - `/workspace/today`;
  - `/workspace/library?view=` (saved, notes, read, archived, all);
  - `/workspace/radar` with `q`, `source_id`, `access_state`, `status`, `days`. **`cursor` and `as_of` are dropped**, even though Radar passes its full search (`Radar.tsx:251-255`), so going back from a page-2 item lands on page 1;
  - `/workspace/review?packet=review-<32hex>`.
- "Back" is a fresh `Link` navigation, not `router.back()` (`Reader.tsx:490`). The list page remounts and refetches `state`, and scroll position is not restored.
- `return_to` is re-emitted by `readerHref` (`api.ts:87-100`; params in the order version, entry, return_to; then `#anchor`) and by `viewVersion`'s `replaceState` (439-443). `viewVersion` drops `entry`.
- Callers that set it: Today `"/workspace/today"` (`Today.tsx:243`), Library `"/workspace/library?view=${filter}"` (`Library.tsx:138, 157`), Radar (`Radar.tsx:251`), Review (`CandidateReview.tsx:343, 372`).

**Hash use is overloaded**
- The hash is either a tab (`source`, `understand`, `notes`) or a source anchor (`abstract|excerpt|full_text:s:e`, `material:…`).
- `tab()` persists the **tab name as the server reading anchor**: the anchor sent is `"understand"` or `"notes"` unless it is a material anchor (403-410). WorkCard then reopens the reader at `#notes` through `item.reading.anchor` (`WorkCard.tsx:29-32`).
- Renaming the ids `source`, `understand` or `notes` would break anchors already stored.

**Queue data available inside the reader**
- The reader has the full `WorkspaceState` from `useWorkspace`, including `editions` (schema `Edition`: `id`, `minutes`, `work_ids[]` ordered, `work_versions{}`, `coverage`, `allocation`; `lib/api/generated/schema.d.ts:1049-1071`), `works`, `profile.data.minutes`, and each item's `reading.status` and `snoozed_until`.
- The reader currently uses none of this ordering.
- **Today queue:** derivable in the reader. The logic is inline and not exported, in `Today.tsx:33-65`:
  - start from `editions[0].work_ids`;
  - map through `work_versions`, dropping an item if its pinned version is missing;
  - filter out dismissed, archived and actively snoozed items.
  - Extract it to `lib/workspace` (for example `todayQueue(state, now)`) and reuse it in both places.
  - For next/prev hrefs, reuse WorkCard's target rule (`WorkCard.tsx:26-32`): `version = editionVersion || reading.version_id || version_id`; `anchor` = the reading anchor if the revision is above 0 and the version matches, else the PDF `first_anchor`, else `${access_state}:0`. Then call `readerHref(item, version, anchor, undefined, "/workspace/today")`.
- **Library queue:** derivable from `state.works` plus the `view` in `returnTo` (`Library.tsx:30-36`, inline filter).
- **Radar:** not in WorkspaceState. It comes from the paginated server endpoint GET `items?{filters}&limit=20&cursor` (`Radar.tsx:68-86`; the `WorkPage` type is local to Radar). The cursor is lost through `return_to`, so the queue would have to be refetched or passed along (for example an id list in sessionStorage).
- **Review:** comes from a separate packet endpoint.

**Status actions the control bar would need**
- The reader's `reading()` always sends `snoozed_until: null` (317) and has no "dismiss" or "snooze" control.
- `useReadingActions.status` (`lib/workspace/useReadingActions.ts:68-78`) supports snoozed (+24h), dismissed and undo. But it uses `item.reading.anchor`, not the reader's live `sourceAnchor` and version.
- The better path is to extend `reading()` with an optional `snoozed_until` and add undo there.

**Remounts and drafts on next/prev**
- Each `/workspace/items/X` → `/workspace/items/Y` navigation remounts the page, so `useWorkspace` repeats `GET state` (the full payload) on every next/prev. Add a shared context or cache if that cost matters.
- Unsaved drafts survive navigation in sessionStorage per (owner, work, version) and are recovered with a notice (124-136). There is no leave-guard.
- There is no focus management after navigation; only the `entry` deep link focuses something.

## 5. Fragile to restyle

**Single live region**
- Every reader message (Reader, RetainedSource `announce`, Synthetic `announce`) goes into one always-mounted `p[role=status]` (`Common.tsx:9`).
- Tests require exactly one: `getAllByRole("status")` has length 1 (`tests/workspace/retained.test.tsx:229`), and `getByRole("status")` is used throughout `tests/workspace/experience.test.tsx`, `stage1.test.tsx` and `live-workspace-e2e/live.spec.ts`.
- A control-bar toast must reuse this region, not add a new one. Keep it mounted when empty.

**Selection offsets depend on DOM text**
- `selectPassage` counts code points of `Range` text inside `p[ref=source]` (283-305). RetainedSource does the same inside `p.workspace-retained-text` (186-190).
- Any extra element or text node inside those `<p>` elements (line numbers, icons, a mascot) corrupts the stored anchors.
- `white-space: pre-wrap` is required (`workspace.css:186-189, 377-381`).
- Tests select by class: `.daily-source-text p` (`experience.test.tsx:392, 435, 472`) and `.workspace-retained-text` (`retained.test.tsx:162, 238`).
- Do not use `::first-letter` drop-cap styling on a text node that has a mark split (`daily.css:616-619`).

**Focus contract**
- `tab()` focuses `#source`, `#understand` or `#notes` (tabIndex −1).
- Tests require that after "Your notes" the next Tab lands on "Save as" (`retained.test.tsx:341-344`; `live.spec.ts:228-233`). Nothing focusable may come before the form inside `#notes`.
- E2E: from `main`, "Your notes" must be reached within 16 Tabs (`live.spec.ts:221-227`). Control-bar or sidebar buttons placed in the DOM before the tabs could break this.
- `editEntry` focuses `#workspace-note-body` (264).
- These ids are global and assumed unique: `source`, `understand`, `notes`, `source-anchor`, `retained-*`, `workspace-entry-*`, `*-title`. Rendering two readers, or a next-paper preview, at once would collide. There is also a `#source mark` query (220; `live.spec.ts:600-601`, which expects it visible and in the viewport on 390px mobile).

**Unique accessible names**
- Tests assume one h1 (`experience.test.tsx:347`, `routes.test.tsx:65-66`, `live.spec.ts:54`).
- They assume one button each named "Mark read", "Save to Library" and "Save question" (`retained.test.tsx:221`; `live.spec.ts:67-70, 369` with exact match).
- Tab names "Source", "Understand", "Your notes" must stay link roles.
- Back-link names "← Library", "← Today", "← Candidate review" are asserted (`stage1.test.tsx:223, 297`; `live.spec.ts:352, 456`).
- `getByRole("textbox")` with no name expects exactly one textbox in that scenario (`experience.test.tsx:507`).
- Moving these controls into a control bar is fine. Duplicating them is not.

**Fixed bottom bar**
- `scrollIntoView({block:"center"})` targets (213, 221; `RetainedSource.tsx:121`) and the notes submit button near the page bottom can end up under a fixed bar.
- Playwright clicks on covered elements fail. Needs bottom padding on `main` and handling for the mobile keyboard.
- `.daily-notes-panel` has `scroll-margin-top: 20px` (`daily.css:647`).

**Layout shift (no reservation exists for this route)**
- Loading happens in three steps: the Suspense text, then LoadingState, then the full reader, with no reserved height.
- For items with a PDF anchor, the abstract block renders first. When `GET materials/<id>` resolves, `pdfActive` hides it and swaps in the spans; the heading and eyebrow text change too (500-503, 627-637).
- No CLS e2e covers `/workspace/*`; `e2e/mount-reservation.spec.ts` covers other routes.
- `.daily-notes-panel form > p { min-height: 24px }` (`daily.css:658-660`) is a dead rule: the form has no direct `<p>` children.

**Mobile panels**
- Hiding panels via `data-active="false"` (`daily.css:884-886`) is the only reason the tabs exist on mobile. Keep `data-active` on all three panels or replace the mechanism.

**`busy` is shared**
- One `busy` flag covers tab clicks, save, read, archive and pin. A tab click (POST `reading`) briefly disables all actions and flips the submit label to "Saving…" (403, 813).

**Likely latent bug (verify in a browser)**
- "Source context →" (872-883) is a plain `<a>`. When its search string equals the current URL's (same version and `return_to`, no `entry`), the click becomes a same-document fragment navigation.
- Next ignores popstate with null state (`app-router.js:61-65`) and the reader reads the hash only at mount, so the passage would not be highlighted.

**Route JS budget**
- `/workspace/items/[id]` has a 169,984 B ceiling against a measured 156,214 B, about 13.7 KB headroom (`budgets.json:425-436`, gated by `npm run budgets`).
- A mascot SVG component, a queue sidebar or a new control-bar component counts against this.

**Other**
- Coarse-pointer button min-height (`daily.css:974-978`), `.workspace-card-actions .daily-text-button` min-height 40px (`workspace.css:56-58`), and the `.workspace-focused-entry` outline (`workspace.css:227-230`) are accessibility and target-size affordances to keep.
- `.workspace-app mark` styling (`workspace.css:204-211`) is the only highlight cue: the passage is marked with an underline and sunken background, not by color alone.