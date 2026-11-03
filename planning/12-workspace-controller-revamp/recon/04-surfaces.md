# Live workspace frontend map (read-only)

The live routes split into six list or form surfaces, plus the Reader. Each surface page loads the full workspace state again with `GET state`. The surfaces share three pieces: `WorkCard` for list items, `useReadingActions` for reading-state writes, and `Common` for messages, loading and coverage. The redesign has to deal with three things the current code does not do:
- **No shared state:** nothing is shared between routes, and `template.tsx` remounts the shell on every navigation.
- **No focus in the URL:** none of the surfaces keeps a "focused item" in the URL.
- **Shared stylesheet:** the preview app also uses `daily.css`.

Paths below are under `/home/user/arxiv-research-agent/web/`. All `file:line` references were checked against the files.

## 0. Plumbing

**Routes and layout**
- `app/(live)/layout.tsx:8` calls `notFound()` unless `WORKSPACE_LIVE=1`. It is a server component.
- `app/(live)/template.tsx:10` wraps every live route in `<WorkspaceShell>`.
  - Because it is a template, the shell **remounts on each navigation**. Any sidebar state kept there is lost.
- Route files:
  - `today/page.tsx:3` renders `<LiveToday/>`.
  - `radar/page.tsx:3` renders `<LiveRadar/>`, with no Suspense because it does not use `useSearchParams`.
  - `library/page.tsx:5-7` renders `<LiveLibrary/>` inside Suspense; fallback "Opening your Library…".
  - `interests/page.tsx:3` renders `<LiveInterests/>`.
  - `operations/page.tsx:3` renders `<LiveOperations/>`.
  - `review/page.tsx:6-10` renders `<CandidateReview/>` inside Suspense; fallback "Opening candidate review…".
  - `items/[id]/page.tsx:9-19` decodes the id (`notFound` on bad encoding) and renders `<LiveReader id/>` inside Suspense; fallback "Opening your source…". Reader is outside this slice.

**`lib/workspace/api.ts`**
- `Serialized<T>` (`:5-9`) strips optionality (`-?`). Every optional schema field is therefore typed as **required** on the client.
- Types are exported at `:11-34`.
- `workspaceRequest(path, body?, signal?)` (`:47-67`):
  - Calls `requestWorkspaceJSON` (`lib/api/client.ts:51-63`), which goes to `/api/workspace/${path}`. It sends GET when `body===undefined`, otherwise a JSON POST.
  - `refresh` has a 120s timeout (`client.ts:63`).
  - Errors are mapped to one `WorkspaceError` message each for 409, 401/403, other statuses and network failure (`:56-65`).
- `requestId()` returns `crypto.randomUUID()` (`:69-71`).
- `displayDate` (`:73-85`) returns "Date unknown" for empty or invalid input.
- `readerHref(item, version?, anchor?, entryId?, returnTo?)` (`:87-100`) builds `/workspace/items/{id}?version&entry&return_to#anchor`.
- `readingMaterial(item, versionId?)` (`:103-110`) returns `{version, pdf: retained_materials.find(format==="pdf"), scope: available_scopes[0] ?? access_state}`.
- `normalizeReaderReturnTo` (`:113-140`) keeps only:
  - `/workspace/today`, with **all params dropped**;
  - `/workspace/library?view`, where view ∈ saved|notes|read|archived|all;
  - `/workspace/radar` with q, source_id, access_state, status, days (cursor and as_of are dropped);
  - `/workspace/review?packet`, matching `review-[a-f0-9]{32}`.
- `errorMessage` is at `:142-146`.

**`useWorkspace.ts`**
- State: `state`, `error`, `loading` (`:7-9`).
- `reload()` sends `GET state` (`:10-21`).
- The mount effect sends `GET state` with an AbortController (`:22-36`).
- Returns `{state, setState, error, loading, reload}` (`:37`). No consumer in this slice reads `loading`; they all branch on `!state`.

**`useReadingActions.ts(state, setState, announce)`**
- Holds `busy` (`:18`) and a **single-slot** `undo` (`:19-22`).
- `attempts` (`:23`) is a fingerprint-to-request_id map, so a retry is idempotent.
- `write(item, data, reversible=true)` (`:24-63`):
  - Returns early if `busy` (`:25`).
  - Sends `POST reading {work_id, revision: item.reading.revision, data:{status, anchor, version_id, snoozed_until}, request_id}` and receives `ReadingRevision` (`:26-39`).
  - Patches `state.works[i].reading` (`:40-45`).
  - Records the previous reading data for undo (`:46-56`).
  - Announces "Saved on the server: {status}." (`:57`).
- Returns `{busy, hasUndo, undo(), write, status(item, s)}` (`:64-79`).
  - `status()` keeps the anchor, uses `reading.version_id || item.version_id`, and sets snooze to now + 24h (`:75-77`).
  - `undo()` writes with `reversible=false`.

## 1. `Shell.tsx`: `WorkspaceShell({children})`

- **Hooks:** `usePathname()` (`:19`).
- **Imports:** `daily.css` and `workspace.css` (`:7-8`).
- **Render order:**
  1. `div.daily-app.workspace-app.font-ui` (`:21`).
  2. `<SkipLink/>` (`:22`).
  3. `header.daily-header` (`:23`), containing:
     - brand `Link.daily-brand` to `/workspace/today` (`:24-34`): mark "r·", text "Research workspace", subtitle `.daily-brand-sub` "A place to follow a question.";
     - `.daily-header-actions` (`:35`) with `<ThemeToggle/>` (`:36`) and link "Fictional preview ↗" to `/today` (`:37-39`).
  4. `.daily-preview-bar.workspace-mode` (`:42-48`): "Local workspace" and "Real source metadata · private server saves · generation off".
  5. `.daily-frame` (`:49`), containing `aside.daily-sidebar` (`:50`):
     - `nav[aria-label="Research workspace"]` (`:51`). Items from `NAVIGATION` (`:10-16`): Today ◷, Radar ⌕, Library ▤, Interests ◎, "Sources & checks" ↻. `aria-current="page"` comes from `path.startsWith(href)` (`:59`). **Review and Items are not in the nav.**
     - `.daily-sidebar-note` (`:67-77`): "Your workspace" / "Discover. Understand. Keep the thread." and link "Research a question ↗" to `/`.
     - `p.daily-storage` (`:78-81`): the local-account / draft disclaimer.
  6. `main#main.daily-main[tabIndex=-1]` (`:83-85`).
- **ThemeToggle** (`components/patterns/ThemeToggle.tsx`) is native radios in a fieldset: Light, Dark, System.

## 2. `Common.tsx`

| Export | Lines | What it renders |
|---|---|---|
| `Message({children})` | `:7-13` | `p.daily-muted[role=status]`. The single live region per route. |
| `LoadingState({error, retry})` | `:15-36` | With an error: `div.workspace-alert.error` with h1 "Workspace unavailable", the error text, "No fictional items have been substituted.", and button "Retry connection" (`.daily-secondary`, calls `retry`). Without: `p.daily-muted[aria-busy]` "Opening your local workspace…". Every page shows this while `!state`. |
| `ServiceNotice({error})` | `:38-48` | When a reload fails after state already loaded: `.workspace-alert.error`, "The records below are the last loaded view…". |
| `sourceAvailable(s)` | `:50-52` | True when status ∈ ok, success, not_modified, partial. |
| `Coverage({sources, children})` | `:54-97` | `details.daily-coverage[data-complete]`. Summary: status dot, "Source checks: {good} of {n} available" and a span with "Unavailable checks" / "{k} limited source windows" / "Bounded metadata checks". Limited means `partial` or `receipt.truncated===true`. Then `{children}`, a bounds paragraph, and a `ul` of name + status + last success (or "Limited fetch committed; …" / "No successful check recorded"). |
| `GenerationBoundary()` | `:99-114` | `.daily-generation`: eyebrow "Grounded analysis · later milestone", h3 "Follow the source first.", and a disabled button "Generation awaiting approval". |

## 3. Today: `Today.tsx` → `LiveToday` (no props)

**State and hooks**
- `useWorkspace` (`:26`); `notice`, `refreshing`, `savingProfile` (`:27-29`).
- `pending` ref: idempotency map (`:30`).
- `useReadingActions(state, setState, setNotice)` (`:31`).
- No URL state at all: no search params and no router.

**Derived data**
- `latest = state.editions[0]` (`:33`).
- `ordered` (`:34-58`) maps `latest.work_ids` to `state.works`.
  - If `latest.work_versions[id]` exists, it overlays that retained `works[].versions[]` entry: version_id, version_label, title, url, authors, abstract, access_state, content_hash.
  - **The item is dropped** if that version is missing from `works[].versions`.
- `visible` (`:59-65`) excludes `dismissed` and `archived`, and `snoozed` with a future `snoozed_until`. `saved` and `read` items **stay visible**.
- `activity = state.latest_activity`; `activityWork` is found by `work_id` (`:66-69`).

**Network calls**
- `pin(entryId|null)` (`:70-93`):
  - `POST profile {revision: profile.revision, data:{...profile.data, pinned_entry_id}, request_id}`, then `reload()`.
  - Notice: "Saved item pinned. Its source version and passage stay attached." or "Saved item unpinned. The latest activity is shown again."
- `refresh()` (`:94-111`):
  - `POST refresh {source_ids: []}` (all sources); the response is a full `WorkspaceState`, passed to `setState`.
  - Notices: before, "Checking a bounded set of public source metadata. No model is running."; after, "Source check completed. Inspect coverage for unavailable or limited sources."
- `minutes(5|15|45)` (`:112-134`):
  - `POST profile {..., data:{...data, minutes}}`, then `POST edition {}`, then `reload()`.
  - The edition endpoint has no request body in the schema (`schema.d.ts:4166-4185`); `{}` is sent only to force a POST.
  - Notice: "{v}-minute preference saved; a new bounded edition was prepared from stored metadata."

**Render order**, inside `div.workspace-today` (`:136`):
1. `.daily-page-meta` (`:137-150`): eyebrow "Edition {displayDate(latest.created_at)}" or "Your first local briefing", and link "Edit your interests ↗" to `/workspace/interests`.
2. `.daily-intro` (`:151-173`): h1 "What changed.", p "A short reading list for your next question.", and `fieldset.daily-time` (legend "Time for reading") with buttons "5 min", "15 min", "45 min". Each has `aria-pressed={profile.data.minutes===v}`, is disabled by `savingProfile`, and calls `minutes(v)`.
3. `<ActivityCard compact>` (`:174-181`). `pinned` is true when `activity.entry_id === profile.data.pinned_entry_id`.
4. `<ServiceNotice>` (`:182`), then `<Message>{notice}` (`:183`).
5. When `actions.hasUndo`: `.workspace-toolbar` with button "Undo last change" (`.daily-secondary`, disabled by `actions.busy`) (`:184-192`).
6. `.daily-columns` (`:193`), left column:
   - `<Coverage sources={latest?.coverage ?? state.sources}>` (`:195-202`). Its child `.workspace-toolbar` holds button "Check sources now" / "Checking sources…" (`.daily-button`, calls `refresh`) and link "Search all stored items →" to `/workspace/radar`.
   - `section[aria-labelledby=live-changes]` (`:203-256`):
     - `.daily-section-heading` with h2 "Changes to consider" and "{visible.length} items · {latest.status}" or "No edition yet".
     - `p.workspace-version-notice` when `ordered.length < work_ids.length` (`:211-216`).
     - Then one of:
       - with no edition: `.daily-empty` "Make your first bounded check." (`:217-224`);
       - with nothing visible: `.daily-empty` "No matching items in the available checks." if any source is unavailable, otherwise "Nothing new matched this reading window." (`:225-236`);
       - otherwise `WorkCard`s with `versionId={latest.work_versions[id]}`, `returnTo="/workspace/today"`, `lead={index===0}` (`:238-248`).
     - Footer `p.daily-muted.workspace-toolbar`: "That's this edition's shortlist… profile revision {latest.profile_revision}…" (`:250-255`).
   - `details.workspace-edition-details` (`:257-263`): summary "Edition details · {work_ids.length} items · about {latest.minutes} minutes", containing `<AllocationReceipt allocation={latest.allocation} minutes={latest.minutes}/>`.
7. `aside.daily-context[aria-label="Continue your research"]` (`:265-298`): eyebrow "Keep the thread", h2, `.daily-thread` showing "Your current question" = `profile.data.research_question` or "Add your current research question in Interests.", `<GenerationBoundary/>`, link "Your saved work →" to `/workspace/library`, and `p.workspace-review-link` with link "Review candidate usefulness →" to `/workspace/review`.

### `WorkCard.tsx` — props `{item, lead?, busy?, versionId?, returnTo?, status(item, s)}` (`:11-25`)

**Derived values**
- `readingVersion = versionId || reading.version_id || item.version_id` (`:26-27`).
- `readingMaterial` gives `{version, pdf, scope}` (`:28`).
- `readingAnchor` is the saved anchor when `reading.revision>0` and the version matches. Otherwise it is `pdf.first_anchor`, or `${access_state}:0` (`:29-32`).

**Render**, as `article.daily-item[.daily-item-lead]` (`:34`):
1. `.daily-item-meta`: kind, version_label, "PDF text" / "PDF excerpts" / scope, and `span.daily-saved` with the status unless it is unread (`:35-42`).
2. `h3 > Link` to `readerHref(item, readingVersion, readingAnchor, undefined, returnTo)` (`:43-56`).
3. `p.daily-item-change`: abstract **truncated to 320 characters**, or a PDF or metadata fallback (`:57-63`).
4. `p.workspace-version-notice` "A newer source version is available…", only when there is no `versionId` and the saved version differs from the current one (`:64-71`).
5. `details.daily-reason`, summary "Why this appeared": `reasons.join(" · ")` plus a ranking disclaimer (`:72-81`).
6. `p.daily-caveat` "Available evidence" with five variants (`:82-93`).
7. `.daily-item-footer`: "{source_id} · Published {date}" or "Publication date unknown", and link "Read & investigate →" (`:94-114`).
8. `.workspace-card-actions` (`:115-144`), all `.daily-text-button`, disabled by `busy`:
   - "Save" / "Unsave": `aria-pressed`, aria-label "Save {title}" / "Unsave {title}"; sets saved, or unread when already saved.
   - "Dismiss": aria-label "Dismiss {title}"; sets dismissed.
   - "Snooze one day": aria-label "Snooze one day {title}"; sets snoozed.
   - **There is no Read or Archive on cards.** Those exist only in Reader.

### `ActivityCard.tsx` — props `{activity, work?, pinned, busy, onPin, compact=false}` (`:12-26`)

- With no activity (`:27-39`): `.daily-thread.workspace-activity.workspace-continuation` (when compact) with h2 "Continue your question" and "No saved activity yet".
- `sourceTitle` (`:40-47`) comes from `work.versions[activity.version_id].title`, else "Earlier retained source version".
- `options` fragment (`:48-57`):
  - `time` "Saved {updated_at}";
  - "{version_id} · {anchor}";
  - when `entry_id` is set, a button labelled "Unpin saved item" or "Pin this {entry_kind}" that calls `onPin(pinned ? null : entry_id)`.
- Body (`:58-97`): span "Pinned" or "Latest activity", plus " · your {entry_kind}" or " · reading location"; then the body text; then link `.workspace-activity-link` "{sourceTitle} →" to `readerHref(work, activity.version_id, anchor, entry_id, "/workspace/today")`, or an unavailable-source message. When compact, `options` sit inside `details.workspace-continuation-options` with summary "Source and pin options".

### `AllocationReceipt.tsx` — props `{allocation, minutes?, compact=false}`

- Required numeric keys (`:14-22`): slots, requested_fraction, planned_max_exploration_slots, max_exploration_slots, actual_exploration_slots, actual_items, unused_slots. `actual_fraction` may be number or null.
- If any key is missing or invalid: "This earlier edition has no recorded exploration allocation…" (`:23-37`).
- Otherwise `.workspace-allocation[-compact]`: "{min} min · {n} exploration item(s) among {actual_items} selected ({actual% or 'no items'}). Requested cap: {req%}."
  - Compact adds "{unused} of {slots} reading slots unused…".
  - Full adds `details`, summary "Inspect this edition's allocation", with `dl.workspace-allocation-details` (`:44-82`).

## 4. Radar: `Radar.tsx` → `LiveRadar`

**URL handling.** It uses raw `window.location` and `history`, not Next hooks.
- `fromURL()` (`:33-45`) reads q, source_id, access_state, status, days (default "7"), cursor and as_of.
- The mount effect loads the URL and listens to `popstate` (`:57-67`).
- `navigate(next)` calls `history.pushState("/workspace/radar?…")` and sets `applied` (`:88-97`).

**State:** `filters` (draft), `applied`, `page: {items, next_cursor, as_of}`, `notice`, `loading`, and `actions` (`:48-56`).

**Network:** effect on `[applied]` sends `GET items?{q,source_id,access_state,status,days,limit=20}[&cursor][&as_of]` and receives an ItemPage (`:68-86`; query params at `schema.d.ts:4186-4197`).

**Render order** (fragment):
1. `.daily-page-meta`: "Radar · actual stored metadata" and "No generated summaries" (`:100-103`).
2. `.daily-intro`: h1 "A wider view. / Your terms, your pace." (`:104-116`).
3. `<ServiceNotice>` (`:117`).
4. `p.workspace-review-link` with link "Review a finite candidate set →" to `/workspace/review` (`:118-122`).
5. `form` (submit calls `navigate({filters, cursor:null, asOf:null})`), containing `.workspace-controls` (`:123-214`):
   - search "Search titles and abstracts" (maxLength 200);
   - select "Source": "All checked sources", each `state.sources[]` name, "Manually saved" (value `manual`);
   - select "Date window": Past day (1), Past seven days (7), Past thirty days (30), All stored dates (0);
   - select "Available material": Any access state, Abstract, Metadata/link, Excerpt, Full text;
   - select "Reading state": Any reading state, unread, saved, read, archived, dismissed, snoozed;
   - button "Apply filters" (`.daily-secondary`, disabled while loading).
6. `.workspace-toolbar`: "Undo last change" (when hasUndo), and `<Message>` with "Loading this stored result window…" or `notice` (`:215-228`).
7. `.daily-section-heading`: h2 "Stored source records", "{n} on this page · stable observation cutoff" (`:229-234`).
8. A `WorkCard` per `page.items` (`:235-260`):
   - Each item is merged with `state.works` reading and entries.
   - `returnTo` is the current location; the normalizer drops cursor and as_of.
   - No `versionId` is passed.
9. Empty state `.daily-empty`: "No stored items match these filters." (`:261-269`).
10. `.workspace-list-pagination` (`:270-299`):
    - "First page": `{cursor:null, asOf: page.as_of}`, disabled when there is no cursor.
    - "Next page →": shown only when `next_cursor` exists.
    - There is no previous-page control.

## 5. Library: `Library.tsx` → `LiveLibrary` (plus `Import.tsx`)

**Hooks and state**
- `useSearchParams().get("view")` (`:22`). Allowed values: saved|notes|read|archived|all, default saved (`:24-27`).
- `notice`, `manual`, `busy`, `actions` (`:19-28`).

**Filter** (`:30-36`):
- `all` means entries exist or status ≠ unread.
- `notes` means entries exist.
- Otherwise status must equal the view.
- **Dismissed and snoozed items appear only under `all`.**

**Network**
- `saveManual` (`:37-54`): `POST manual {value: manual.trim()}` returns a WorkItem, then `reload()`. Notice: "Saved {title}. Access remains {access_state}; …".
- Export is a plain `<a href="/api/workspace/export" download="research-notes.md">` (`:59-65`).

**Render order:**
1. `.daily-page-meta`: "Your library · server-backed" and "Export notes as Markdown ↗".
2. `.daily-intro`: h1 "Keep the source. / Keep your thinking." (`:67-78`).
3. `<ServiceNotice>`.
4. `form.workspace-form-stack` (`:80-101`): input "Save an arXiv ID, DOI or source URL" (required, maxLength 2048, placeholder "arXiv:2601.01234 · 10.1234/example · https://…"), and button "Save source link" / "Saving source…".
5. `.workspace-toolbar` (`:102-132`):
   - select "Library view": Saved, With notes or questions, Read, Archived, All personal state. On change it calls `history.replaceState("/workspace/library?view=…")`, which `useSearchParams` picks up.
   - Undo, and `<Message>`.
6. A `section` per work (`:133-167`):
   - `WorkCard` with `returnTo="/workspace/library?view={filter}"`.
   - One `article.daily-notebook-entry` per `item.entries`: "Your {kind}", body, "Source {version_id} · {anchor}", and link "Resume this question →" to `readerHref(item, entry.version_id, entry.anchor, entry.id, returnTo)`.
7. Empty state `section.daily-empty` (`:168-183`): "Save something worth returning to." for saved, otherwise "No items in this view.", plus link "Back to Today →".
8. `<PreviewImport revision={profile.revision} reload announce={setNotice}/>` (`:184-188`).

### `Import.tsx` → `PreviewImport`

- **State:** `record`, `preview`, `importProfile`, `busy`, `baseRevision`, `original`, `pasted` (`:20-26`).
- **`inspect(raw?)`** (`:27-61`):
  - Reads `localStorage[PREVIEW_KEY]` unless raw input is supplied, then runs `parsePreview` (`lib/daily/store`).
  - Sends `POST import/preview {record, profile_revision: revision, import_profile}` and receives ImportPreview.
- **`apply()`** (`:62-82`): blocked when there are conflicts; sends `POST import/apply {record, profile_revision: baseRevision, import_profile, digest}`, then `reload()`.
- **Render** inside `section.workspace-import` (`:84-219`):
  1. Eyebrow "Explicit one-time transfer", h2 "Bring your preview notes with you."
  2. Checkbox "Also import the preview interests and research question"; toggling it resets the preview.
  3. Button "Preview browser import".
  4. `details.workspace-import-file`, summary "Import an export from a different preview address":
     - file input "Preview JSON file" (≤200000 bytes);
     - textarea "Or paste exported preview JSON" (maxLength 200000);
     - button "Preview exported JSON" (disabled when busy or empty).
  5. When a preview exists, `.workspace-alert` with h3 "Review this transfer":
     - counts "{entries_new} new notes/questions/actions", "{entries_existing} already imported";
     - "Profile will change after confirmation" or "Your server profile stays as it is";
     - "Browser original retained";
     - then either the conflict list or button "Confirm import" (`.daily-button`);
     - link "Export supplied original" (a `data:` URL, file `research-preview-original.json`).

## 6. Interests: `Interests.tsx` → `LiveInterests` (plus `InterestCoverage.tsx`)

**State:** `draft: ProfileData|null`, `baseRevision`, `notice`, `busy`, `query`, `field`, `customRaw`, `exclusionsRaw`, `attempts` (`:26-35`).
- `data = draft ?? profile.data` (`:37`).
- `change(partial)` (`:55-60`) captures `baseRevision` on the first edit. Notice: "You have unsaved interest changes."

**Catalogue:** `lib/daily/topics.json` has 384 topics: 243 authored_study_area, 96 authored_ml_topic, 26 external_field, 15 authored_ml_group, 4 external_domain. Streams come from `STREAMS` (`lib/daily/profile.ts:4`).
- Visible topics (`:45-54`):
  - With a query: substring match on id + label.
  - With no query and no field: only `authored_ml_group` and `external_field`.
  - With a field: descendants found through the `parents` chain (`inField`, `:39-44`).

**`save`** (`:61-94`):
- `POST profile {revision: baseRevision ?? profile.revision, data:{...data, custom_topics: lines(customRaw), exclusions: lines(exclusionsRaw)}, request_id}`, then `POST edition {}`, then `reload()`, then clear the draft.
- `lines()` (`:18-23`) splits on newlines, trims, and drops empty lines.

**Render order:**
1. `.daily-page-meta`: "Your research lens · revision {n}" and "Back to Today →" (`:97-104`).
2. `.daily-intro`: h1 "Follow a field. / Or your own question." (`:105-117`).
3. `<ServiceNotice>`.
4. `form` (`:119`):
   - `section.daily-lens` (`:120-174`):
     - textarea "Your current research question" (4 rows, max 2000);
     - select "Daily reading window": 5 minutes, 15 minutes, 45 minutes;
     - `fieldset` legend "Your research streams": a checkbox per stream (label plus `small` detail), and a coverage disclaimer.
   - `.daily-interests-grid` (`:175-326`):
     - section with h2 "Fields and detailed topics" and "{384} catalogue entries · {26} field anchors", an intake disclaimer, then `.daily-filters`: search "Find a topic" (placeholder "Retrieval, control, evaluation…") and select "Browse a field" ("All fields" plus the field topics).
     - `.daily-topic-list`: a checkbox per topic, with a `small` hint that depends on the topic (`:230-242`). Empty state: "No catalogue entries match. Add a custom interest."
     - `aside.daily-interest-summary`:
       - h2 "Your terms and boundaries";
       - textarea "Custom interests or watch terms", hint "One term per line";
       - textarea "Exclude these terms", hint "Exclusions take priority over positive matches";
       - select "Exploration allocation": "0% · only explicit matches", "15% upper bound · round down", "30% upper bound · round down" (values 0, 0.15, 0.3);
       - `.workspace-allocation-previews`: h3 "Current saved preference, by reading window", plus a compact `AllocationReceipt` per `state.allocation_previews`, plus a draft note;
       - "{n} topics selected…".
   - `<InterestCoverage coverage={state.interest_coverage} sources={state.sources} draft={draft!==null}/>` (`:327-331`).
   - `.workspace-toolbar` (`:332-355`):
     - submit "Save interests and question" / "Saving interests…" (`.daily-button`);
     - when a draft exists, "Discard draft and reload saved profile", which clears the draft and calls `reload()`;
     - `<Message>`.

**`InterestCoverage`** (`:5-83`): `section.workspace-interest-coverage`, h2 "What these interests actually monitor".
- With a draft, a `.workspace-version-notice` "Your draft is not applied here yet…".
- Empty state: "No saved interest coverage is available yet."
- Otherwise a `details.workspace-interest-row` per interest:
  - summary: label plus `.workspace-topic-count` with "Browse only · no matching vocabulary", "Matching terms available · no connected source", or "Matching terms configured · limited source scope";
  - "Matches these terms:";
  - for `descendant_terms`, "{n} detailed descendant topics";
  - "Configured sources:", with names looked up in `sources`;
  - the limitations.

## 7. Operations: `Operations.tsx` → `LiveOperations`

**State:** `notice`, `busy`, `draft: ScheduleData|null`, `attempts`; `schedule = draft ?? state.schedule` (`:15-21`).

**Network**
- `check(id)` (`:22-39`): `POST refresh {source_ids:[id]}` returns WorkspaceState, passed to `setState`.
- `save` (`:40-67`): `POST schedule {revision: state.schedule.revision, data:{enabled:false, timezone, local_time}, request_id}`, then `reload()`.
  - **`enabled` is always false. There is no control that enables the schedule.**

**Render order:**
1. `.daily-page-meta`: "Sources & checks · local operations" and "No external delivery".
2. `.daily-intro`: h1 "Know what was checked. / And what wasn't."
3. `<ServiceNotice>`, then `<Message>` (`:89-90`).
4. `section[aria-labelledby=source-health]` (`:91-141`):
   - heading "Source health and coverage", "{n} configured sources";
   - `.workspace-source-list` containing an `article.workspace-source` per source:
     - header h2 with the name and status eyebrow;
     - `dl` with Last success and Scope;
     - `details`, summary "Inspect this check's receipt", containing `pre.workspace-receipt[role=region]` with the receipt JSON;
     - button "Check {name} now".
5. `section.workspace-form-stack.workspace-import` (`:142-206`):
   - "Local schedule · awaiting your time", h2 "A regular check, when you choose.";
   - `.workspace-alert`: "A recurring schedule is enabled" or "Recurring schedule disabled", plus "Next check: …" or "None scheduled";
   - form: input "IANA timezone" (required, placeholder America/Los_Angeles), input[type=time] "Proposed local check time", and button "Pause schedule and save preferences" or "Save preferences · keep schedule disabled".
6. `section.workspace-import` "Durable local work" (`:207-241`): "{n} recorded tasks", and an `article.workspace-inline-note` per task with kind · status/state, Due, reason, Attempt. Tasks are untyped dicts. Empty state: "No queued or recorded scheduled tasks…".
7. `.daily-generation` "Generation stays separate." (`:242-249`).

## 8. Review: `CandidateReview.tsx` → `CandidateReview` and `CandidateFeedback`

**Hooks and state**
- `useWorkspace` (`:22`); `useSearchParams().get("packet")` (`:23`).
- `index: ReviewIndex|null`, `error`, `notice`, `preparing`, `attempts` (`:24-28`).
- `wrongPacket = selectedPacket && packet.id !== selectedPacket` (`:53`).

**Network**
- Effect on `[selectedPacket]` (`:29-49`): `GET review[?packet_id=]`. A 404 shows "This candidate review is unavailable in this account…".
- `prepare()` (`:54-90`):
  - `POST review/prepare {profile_revision, request_id}` returns ReviewPacket.
  - The new packet id is prepended to `packet_ids`, then `history.replaceState("/workspace/review?packet=…")`.
  - Notice: "Candidate set prepared from stored metadata…".
- `saveAcknowledged` (`:91-110`) patches the item's feedback and recomputes `labelled_count`.
- `reloadSaved()` (`:111-125`): GET review again, then `reload()`.

**Render order:**
1. `.daily-page-meta`: "Your usefulness judgments · no automatic labels" and "Back to Today →".
2. `.daily-intro`: h1 "What deserves / your attention?"
3. `<ServiceNotice>`.
4. `.workspace-toolbar` (`:150-195`):
   - "Prepare up to 10 candidates" / "Prepare another candidate set" / "Preparing candidates…". Disabled when preparing, or loading with no error, or `wrongPacket` with no error.
   - "Reload saved review".
   - When `packet_ids.length > 1`: select "Saved candidate set" with options "Current review" or "Review {id last 8}". On change it clears the index and calls `history.pushState`.
   - `<Message>`.
5. Then one of (`:196-266`):
   - error: `.workspace-alert`;
   - loading: "Opening the saved candidate set…";
   - no packet: `.daily-empty` "Choose a small set to review.";
   - a packet:
     - `.daily-section-heading` h2 "{n} candidates · {labelled} labelled", "Frozen {as_of} · interests revision {r}";
     - `p.workspace-review-intro`;
     - `details.workspace-review-method`, summary "How this set was selected": selection, limitations, "Ranking policy {v} · {id}";
     - `<Coverage sources={packet.coverage}/>`;
     - empty state "No eligible stored candidates.", or a `CandidateFeedback` per item, keyed `${packet.id}:${work_id}`.

**`CandidateFeedback`**, props `{candidate, position, packetId, onSaved, announce}` (`:271-283`)
- **Local** draft state: `saved`, `label`, `reason`, `busy`, `attempts` (`:284-288`).
- `changed`, `canSave` (`:289-290`).
- `remoteChanged = candidate.feedback.revision > saved.revision` (`:291`).
- `save` (`:293-327`): `POST review/feedback {packet_id, work_id, version_id, revision: saved.revision, label, reason, request_id}` returns UsefulnessFeedback.
- **Render** as `article.workspace-review-candidate.daily-item` (`:329-462`):
  1. Meta: "Candidate {n}", version_label, evidence_scope, "Not labelled" or "Your label: {x}".
  2. h2 link to `readerHref(item, version_id, "{evidence_scope}:0", undefined, "/workspace/review?packet=…")`.
  3. Abstract truncated to **600 code points**.
  4. `details.daily-reason`, summary "Why it is in this review".
  5. "{source_id} · {version_id} · 5-minute reading estimate".
  6. Link "Inspect retained source →".
  7. `form.workspace-feedback`:
     - fieldset legend "Your usefulness judgment for candidate {n}" with radios Useful, Maybe, Irrelevant;
     - textarea "Optional reason for candidate {n}" (max 2000);
     - `.workspace-card-actions`: "Save judgment for candidate {n}" / "Saving judgment…", and "Clear this label" when a label is saved (clears locally only, then the user saves);
     - an unsaved-judgment note;
     - when `remoteChanged`, a `.workspace-version-notice` with "Discard draft and load saved judgment".

## 9. WorkspaceState shape

Schema lines are in `lib/api/generated/schema.d.ts`; usage is cited per component above.

**`WorkspaceState`** (`:3033`)
- `principal_key_id`: used only by Reader.
- `profile: ProfileRevision {revision, data}` (`:2210`).
- `works: WorkItem[]`, `sources: SourceStatus[]`, `editions: Edition[]`, `schedule: ScheduleRevision`.
- `tasks: dict[]`: untyped; Operations reads id, kind, status|state, due_at, reason, attempts|attempt.
- `generation: "approval_required"`, `as_of`, `activity: Activity[]`: unused in this slice.
- `latest_activity: Activity|null`, `interest_coverage: InterestCoverage[]`, `allocation_previews: dict[]` (minutes plus the allocation keys from section 3).

**`Edition`** (`:1049`): `id` (unused), `created_at`, `profile_revision`, `minutes`, `work_ids[]`, `work_versions{work_id→version_id}`, `coverage: SourceStatus[]`, `status: string`, `allocation{}`. Only `editions[0]` is used.

**`WorkItem`** (`:2952`)
- Identity and source: `work_id`, `version_id`, `source_id`, `source_record_id`, `title`, `url`, `authors[]`, `abstract`, `access_state`, `categories[]`.
- Dates: `published_at`, `updated_at`, the precisions, `first_seen_at`, `fetched_at`.
- Also `content_hash`, `version_label`, `kind`.
- `versions: MaterialVersion[]` (`:2058`): version_id, version_label, abstract, access_state, content_hash, fetched_at, source_scope, title, url, authors, reading_access_state, available_scopes, retained_materials.
- `reading: ReadingRevision`, `entries: EntryRevision[]` (`:1093`): work_id, version_id, kind question|note|next-action, body, anchor, id, revision, updated_at, activity_sequence.
- `reasons[]`, `reading_access_state`, `available_scopes[]`, `retained_materials: RetainedAvailability[]` (`:2505`): material_id, version_id, scope, format pdf|text, quality, complete, page_count, retained_pages, first_anchor, warnings.

**Other schemas**

| Schema | Line | Fields |
|---|---|---|
| `ProfileData` | `:2181` | topics[], custom_topics[], exclusions[], streams[], minutes 5\|15\|45 (default 15), research_question, exploration (default 0.15), pinned_entry_id |
| `ReadingData` / `ReadingRevision` | `:2374` / `:2395` | status unread\|saved\|read\|archived\|dismissed\|snoozed, anchor (default "abstract:0"), version_id, snoozed_until; Revision adds revision, updated_at, activity_sequence |
| `Activity` | `:956` | sequence, entry_id, work_id, version_id, kind entry\|reading, entry_kind, body, anchor, revision, updated_at |
| `SourceStatus` | `:2901` | source_id, name, status (default not_checked), last_success_at, receipt{} (`receipt.truncated` is read) |
| `ScheduleRevision` | `:2668` | enabled, timezone, local_time, revision, next_check |
| `InterestCoverage` | `:1652` | topic_id, label, matching_mode descendant_terms\|literal_terms\|browse_only, terms, descendant_ids, source_ids, status active\|limited\|unconnected, limitations |
| `ItemPage` | `:1677` | items, next_cursor, as_of |
| `ReviewIndex` | `:2576` | packet?, packet_ids |
| `ReviewPacket` | `:2582` | id, created_at, as_of, profile_revision, policy_version, items, coverage, selection, limitations, labelled_count |
| `ReviewCandidate` | `:2561` | work, matching_reason[], evidence_scope, estimated_minutes 5, feedback |
| `UsefulnessFeedback` | `:2919` | revision, label, reason, updated_at |
| `ImportPreview` | `:1622` | digest, entries_new, entries_existing, conflicts[], profile_will_change, original_retained |

## 10. Network calls by surface

All paths are relative to `/api/workspace/`.

| Surface | Calls |
|---|---|
| Every page | `GET state` |
| Today | `POST profile`; `POST edition {}`; `POST refresh {source_ids:[]}`; `POST reading` (through the hook) |
| Radar | `GET items?…`; `POST reading` |
| Library | `POST manual`; `POST reading`; `GET export` (anchor link); `POST import/preview`; `POST import/apply` |
| Interests | `POST profile`; `POST edition {}` |
| Operations | `POST refresh {source_ids:[id]}`; `POST schedule` |
| Review | `GET review?packet_id`; `POST review/prepare`; `POST review/feedback` |

Every mutation except refresh, manual and import reuses its `request_id` per payload fingerprint through a `useRef` map. Keep this in the redesign.

## 11. Labels pinned by tests

Renaming any of these breaks tests.

**Unit tests** (`tests/workspace/experience.test.tsx`, `stage1.test.tsx`, `review.test.tsx`):
- Buttons: "5 min", "45 min", "Check sources now", "Undo last change", /^Save A controlled/, /^Unsave …/, /^Dismiss/, /^Snooze one day/, "Retry connection", /Generation awaiting approval/, "Pin this question", "Unpin saved item", "Apply filters", "First page", "Next page →", "Save source link", "Preview browser import", "Preview exported JSON", "Confirm import", "Save interests and question", /Save preferences/, "Check arXiv cs.LG now", "Prepare up to 10 candidates", "Prepare another candidate set", "Reload saved review", "Clear this label".
- Comboboxes: Source, Date window, Available material, Reading state, Library view, Daily reading window, Browse a field, Exploration allocation.
- Searchboxes: "Search titles and abstracts", "Find a topic".
- Text fields: "IANA timezone", "Proposed local check time", "Preview JSON file", "Or paste exported preview JSON", /Exclude these terms/.
- Radios: Useful, Maybe, Irrelevant.
- Links: "Resume this question →", "Inspect retained source →", "Export supplied original", /Fictional preview/, /Radar/.
- Text and headings: "Make your first bounded check.", "Nothing new matched this reading window.", "No matching items in the available checks.", "No stored items match these filters.", "No items in this view.", "Choose a small set to review.", "Opening the saved candidate set…", "{n} candidates · {k} labelled", "No eligible stored candidates.", /Source checks: 1 of 2/, "1 limited source windows", "Latest activity · your question", "Pinned · your question", "Inspect this edition's allocation", "Recurring schedule disabled", "Browse only · no matching vocabulary", /Your draft is not applied here yet/, /15 min · 0 exploration items/.

**Live end-to-end** (`live-workspace-e2e/live.spec.ts`): navigation "Research workspace" (`:98`), "Skip to main content" (`:217`), heading "Stored source records" (`:156`), the text "Inspect this check's receipt" (`:186`), "Save judgment for candidate 1" (`:447`), and textbox "Your current research question" (`:169`).

**Bundle budgets:** `tests/budgets.test.ts:121-127,212` budgets the seven live routes.

## 12. Constraints for the revamp

1. **Shared state.** Lift `useWorkspace` into a client provider mounted from `app/(live)/layout.tsx`, or move `WorkspaceShell` from `template.tsx` to the layout.
   - Today, each route fetches `GET state` itself and the shell remounts on every navigation.
   - A global sidebar queue, time budget and coverage view need one shared state plus `setState`, so that refresh, reading and profile writes update both the sidebar and the stage.
2. **Focus in the URL.** A focused item needs a URL parameter (e.g. `?focus=<work_id>`) so it survives Reader round-trips.
   - `normalizeReaderReturnTo` (`api.ts:121-135`) currently drops **all** Today params and Radar cursor/as_of. Extend its allowlist, and its tests in `stage1.test.tsx`.
3. **Queue shrinkage.** Dismiss, snooze and archive remove an item from Today's `visible` list (`Today.tsx:59-65`). The focus pointer must move to the item now at the same index rather than skip one. Save and read keep the item in the queue.
4. **Undo is per instance.** Undo lives inside each `useReadingActions` instance. The stage and the bottom bar must share one instance per page.
5. **Review drafts are local.** Unsaved judgments live in each mounted `CandidateFeedback` (`CandidateReview.tsx:284-291`). If only the focused candidate is mounted, unsaved drafts are lost on prev/next. Either lift them into a map keyed `${packet.id}:${work_id}` or keep all candidates mounted and hidden.
6. **Time-budget conflict.** A global time-budget control writes `profile.revision`. While an Interests draft exists, that bumps the revision under `baseRevision` (`Interests.tsx:57,65`) and makes the draft save fail with 409. Disable the sidebar budget while an Interests draft exists, or route it into the draft.
7. **New actions need no new API.** "Mark read" and "Archive" are not on list cards today; only Reader has them. Both work through the existing `actions.status(item, "read"|"archived")`. Reader writes reading state itself (`Reader.tsx:325`), not through the hook.
8. **Shared stylesheet.** `daily.css` (978 lines) is also imported by the fictional preview's `components/daily/DailyShell.tsx`. Scope the new styles under `.workspace-app` or new class names.
9. **Abstract truncation.** The stage can show the full abstract; `WorkCard` currently cuts at 320 characters (`:58-59`).

## 13. Proposed placement

**Global left sidebar (every route), top to bottom:**
- Brand and mascot.
- "Local workspace" mode badge (from `Shell:42-48`).
- Navigation: Today, Radar, Library, **Review** (promoted into the nav), Interests, Sources & checks. Keep `nav aria-label="Research workspace"`.
- The current surface's **ordered queue**, with each item's reading-status chip and "{n} items · {edition status}".
- Time budget 5/15/45, through `minutes()`.
- Source checks summary ("Source checks: x of n available") with "Check sources now" and an expandable list.
- Research question with "Edit your interests ↗".
- Continue/pinned activity (compact `ActivityCard`).
- Footer: ThemeToggle, "Export notes as Markdown ↗", "Fictional preview ↗", "Research a question ↗", and the storage disclaimer.

**Floating bottom control bar:** prev/next plus the context actions listed per surface, "Undo last change", and the single `role=status` message. Keyboard shortcuts must be suppressed while focus is in a form field.

| Surface | Sidebar (surface section) | Main stage | Bottom bar |
|---|---|---|---|
| **Today** | Queue = `visible` in edition order; edition status; "Edition details" disclosure (AllocationReceipt); link "Search all stored items →" | Focused WorkCard (lead): meta, full abstract, version notice, "Why this appeared", Available evidence, source/date, "Read & investigate →"; the missing-version notice; the three empty states; shortlist footer (profile revision); GenerationBoundary | ◀ · Save/Unsave · Dismiss · Snooze one day · Mark read (new) · Open → · ▶ · Undo |
| **Radar** | The filter form (5 controls plus "Apply filters"); result queue = `page.items`; "First page" and "Next page →"; "Review a finite candidate set →" | Focused WorkCard (merged reading state); "Stored source records" heading with count; empty state | Same as Today; ▶ at the end of a page triggers "Next page →" |
| **Library** | "Library view" as segmented tabs (Saved, Notes, Read, Archived, All); queue = filtered works; "Save source link" quick-add; "Import preview notes" entry point | Focused WorkCard plus its notebook entries, each with "Resume this question →"; empty state with "Back to Today →"; the PreviewImport panel when opened | ◀ · Save/Unsave · Dismiss · Snooze · Mark read · Archive (new) · Open → · ▶ · Undo |
| **Review** | "Saved candidate set" picker; "Prepare up to 10 / another"; "Reload saved review"; candidate queue with label chips; "{n} candidates · {k} labelled"; packet Coverage; "How this set was selected" | Focused candidate: meta, title link, 600-character abstract, "Why it is in this review", the estimate line, "Inspect retained source →", optional reason textarea, remote-changed notice with "Discard draft and load saved judgment" | ◀ · Useful/Maybe/Irrelevant (keep native radios) · "Save judgment for candidate N" · "Clear this label" · ▶; an unsaved-draft indicator |
| **Interests** | Section index (Question & window, Streams, Topics, Terms & boundaries, Coverage); revision number; time budget disabled while a draft exists | The whole form: question, reading-window select, streams, topic search/browse/list, custom terms, exclusions, exploration, allocation previews, InterestCoverage | "Save interests and question" · "Discard draft and reload saved profile" · "unsaved changes" status; no prev/next |
| **Sources & checks** | Queue = sources with status dots; "Check sources now" (all); schedule state ("Recurring schedule disabled" / next check); task count | Focused source: name, status, last success, scope, the receipt `pre` (keep "Inspect this check's receipt"); schedule form; durable tasks list; generation note | ◀ source · "Check {name} now" · ▶; "Save preferences · keep schedule disabled" when the schedule draft is dirty |
| **Reader** (`items/[id]`, not in this slice) | Queue is the `return_to` list, so the sidebar stays meaningful | The Reader body | Reader's existing Save to Library / Mark read / Archive and note actions. These use Reader's own `POST reading`, not the hook. |

Every capability that exists today is reachable somewhere in this layout. The only additions are Read and Archive on list items, which the API already supports.