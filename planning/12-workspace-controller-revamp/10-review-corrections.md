# 10 · Review corrections (errata). These override 00–09

Produced 2026-11-03 by two independent read-only reviewers who checked the kit against the code:
- a **fact-check** of every file:line, test and label claim;
- a **cold-read executability** pass, done as the implementing agent would.

A third, requirements-coverage reviewer was stopped by the owner's time limit before it reported.

**Rule for the implementing agent:** where an entry below conflicts with 00–09, **this file wins**. Apply each fix as you reach the work order it touches. Record each one you apply in STATUS.md under 'Deviations from the kit'.

Most blockers share one root cause. The live e2e suite runs every spec twice, once at 1440 px and once at **390×844 mobile**. It uses strict single-match locators. So:
- any control a spec touches must be **visible without opening the drawer**, and
- it must **exist once per page**: never in both the Shell footer and the page, never in both the sidebar and the stage.
- Buttons that submit a form must stay in that form, or be rendered through a portal with `form="<form-id>"`.

**7 blockers, 24 major, 51 minor.**

## E01 · [blocker] 03-screens-and-flows.md

**Where:** §1.3 drawer bullet (line 101-103) together with §4 'Sidebar slot' (back link), §5 'Sidebar slot' (filter form), §8 'Sidebar slot' (schedule summary), §9 'Sidebar slot' (Prepare buttons, '{n} candidates · {k} labelled'); 07 §5 e2e table

**Problem:** Below 768px every sidebar-slot section lives inside the closed off-canvas drawer. The live suite runs every test a second time in a 390x844 'mobile' project (16 = 8 tests x 2), and these specs act on controls the kit moves into the sidebar slot. Following the kit as written: Radar searchbox fill and 'Apply filters' click; Review 'Prepare…' click and the visible '{n} candidates · 0 labelled' heading; reader '← Library' / '← Candidate review' clicks; 'Recurring schedule disabled' toBeVisible (exact, so a copy in both sidebar and stage is a strict-mode error); Library 'Export notes as Markdown' click. All of these fail on mobile. 07 §5 lists none of these pins.

**Evidence:** web/live-workspace-e2e/playwright.config.ts projects desktop+mobile (390x844), testMatch **/*.spec.ts; live.spec.ts:157-162 (searchbox, Apply filters), :103 (Export link), :177-179 (Recurring schedule disabled, exact), :352 ('← Library'), :406-430 (Prepare button, heading), :456 ('← Candidate review')

**Fix:** Add a row to 07 §5 and a rule to 03 §1.3: 'live.spec runs in a 390px mobile project; any control a spec touches must be visible without opening the drawer, or the spec gets a minimal helper recorded in STATUS as pinned old layout.' Defaults: keep the reader back link in the stage header row (inside main, before the tabs; it stays within the 16-Tab budget). Keep 'Recurring schedule disabled' and the Review '{n} candidates · {k} labelled' h2 in the stage only. For Radar filters, Review Prepare and the Library export, add `async function openControls(page){ const t = page.getByRole('button',{name:'Queue & controls'}); if (await t.isVisible()) await t.click(); }` to live.spec.ts and call it before live.spec.ts:159, :103 and :406.

## E02 · [blocker] 03-screens-and-flows.md

**Where:** §4 Reader, 'Sidebar slot' bullet 'section outline: Source / Understand / Notes tabs as nav rows' (line 315) and 'Control bar' bullet (lines 321-325)

**Problem:** (a) The reader tabs are `<a>` links in `<nav aria-label="Reading sections">` inside main. Moving them into the sidebar puts 'Your notes' in the aside, which comes before main in the DOM, so Tabbing forward from main never reaches it. Duplicating them as outline links instead makes `getByRole('link',{name:'Your notes',exact:true})` match two elements, a strict-mode error. (b) Putting 'Save question' and the note composer in the control bar breaks the pinned Tab sequence: Your notes → Save as → Your question → Save question.

**Evidence:** web/components/workspace/Reader.tsx:598-616 (tabs are links in main); live.spec.ts:215-243 (Skip → main → ≤16 Tabs → 'Your notes' → Enter → Tab 'Save as' → Tab textbox → Tab 'Save question'); live.spec.ts:77,221 exact link name; recon/03-reader.md §5 'Focus contract'

**Fix:** Rewrite §4: 'Keep `nav[aria-label="Reading sections"]` and its three tab links in main, in their current position. A sidebar outline, if any, must be buttons with different names (e.g. "Jump to Source section") and never links named Source/Understand/Your notes. Keep the note composer (Save as, Your question, Save question) inside #notes, with nothing focusable before it. The bar may hold only ⏮/⏭ and the header actions Save to Library / Mark read / Archive, moved and not copied.'

## E03 · [blocker] 03-screens-and-flows.md

**Where:** §2.1 Footer 'Export notes as Markdown ↗' (line 144) and §6 Library sidebar 'Export notes as Markdown ↗' (line 359)

**Problem:** On /workspace/library the Shell footer link and Library's own link both match /Export notes as Markdown/. live.spec clicks `page.getByRole('link',{name:/Export notes as Markdown/})`, and Playwright's strict mode rejects two matches.

**Evidence:** web/components/workspace/Library.tsx:58-65; web/live-workspace-e2e/live.spec.ts:97-103

**Fix:** Render the export link once per page. Keep it in the Shell footer and delete the §6 bullet: Library.tsx:58-65's link moves, it is not copied. Note in 07 §5 that live.spec.ts:103 pins exactly one such link and that it must be reachable at 390px (see the mobile-drawer finding).

## E04 · [blocker] 03-screens-and-flows.md

**Where:** §8 Sources & checks, 'Bar' bullet: '"Save preferences · keep schedule disabled" when the schedule draft is dirty' (line 394)

**Problem:** live.spec asserts that the button 'Save preferences · keep schedule disabled' is visible right after loading /workspace/operations, with no draft. The button is also the schedule form's submit button, so rendering it through the bar portal takes it out of the `<form>`.

**Evidence:** web/live-workspace-e2e/live.spec.ts:180-184; web/components/workspace/Operations.tsx:165-205 (button is the form's last child and always rendered)

**Fix:** Replace the bullet with: 'Bar: always render the schedule submit button with its current label ("Save preferences · keep schedule disabled" / "Pause schedule and save preferences"), `type="submit" form="workspace-schedule-form"`, and give the stage form `id="workspace-schedule-form"`. Show a separate "unsaved" marker when the draft is dirty.'

## E05 · [blocker] 03-screens-and-flows.md

**Where:** §9 Review 'Stage. The focused candidate' (line 404) and 05 WO-6.3 Acceptance 'All 418 lines of review.test.tsx semantics are preserved'

**Problem:** Rendering only the focused candidate contradicts the tests WO-6.3 says must stay green. review.test expects all candidates mounted (30 radios for 10 candidates; 2 articles for a 2-candidate packet). Unsaved judgments live in each mounted CandidateFeedback's local state, so unmounting on ⏮/⏭ silently drops drafts (recon/04 §12.5, which the kit omits). Hiding the others with `hidden` does not help, because Testing Library excludes hidden nodes from getAllByRole.

**Evidence:** web/tests/workspace/review.test.tsx:120 (`getAllByRole('radio')` length 30), :302 (`getAllByRole('article')` length 2); web/components/workspace/CandidateReview.tsx:284-291 (draft state per card); recon/04-surfaces.md §12 item 5

**Fix:** Choose a default in 03 §9: 'Stage keeps every CandidateFeedback rendered in packet order. ⏮/⏭, the queue and keys 1/2/3 move a highlighted current candidate (`aria-current`, `scrollIntoView({block:"nearest"})` in the handler) and act on it. This preserves review.test.tsx:120/:302 and live.spec.ts:431 ("first article").' If a single-candidate stage is still wanted, require lifting drafts into a `Map` keyed `${packet.id}:${work_id}` in CandidateReview, and list review.test.tsx:120 and :302 as allowed 'pinned old layout' edits.

## E06 · [blocker] 03-screens-and-flows.md

**Where:** §6 Library 'Sidebar slot' view chips 'Keep the <select> "Library view" for test parity, or update its tests' (lines 352-354) and 'Stage. The focused work, followed by its notebook entries' (lines 361-363); 07 §5 table

**Problem:** live.spec itself pins `combobox 'Library view'` (toHaveValue 'notes'), so 'update its tests' would mean weakening an e2e spec. On /workspace/library?view=notes it also finds the `<article>` holding the earlier question's text and its 'Resume this question →' link without selecting any work. The CI DB holds entries on more than one work from earlier specs, so a stage that shows only the default-focused work's entries can hide that article. 07 §5 omits both pins.

**Evidence:** web/live-workspace-e2e/live.spec.ts:323-333, :353-355; web/components/workspace/Library.tsx:100-163

**Fix:** 03 §6: 'Keep the native `<select>` labelled "Library view" (chips may sit beside it and write the same value). In the notes view the stage lists notebook entries for every work in the view, with the focused work first. Alternatively, when `?entry=` or a return focus names a work, focus it.' Add to 07 §5: 'live.spec.ts:323-357: combobox "Library view", article containing the entry text, "Resume this question →", return URL `?view=notes$`.'

## E07 · [blocker] 04-architecture.md

**Where:** §1 Changed files row `lib/workspace/api.ts` (line 42) and §4 'Library. … focus is added' / 'Reader return … keep focus on the Today, Radar and Library paths' (lines 178-181)

**Problem:** After the reader's '← Library' click, live.spec asserts the URL matches `/\/workspace\/library\?view=notes$/`. If Library builds its return_to with focus and normalizeReaderReturnTo keeps it, the URL becomes `?view=notes&focus=…` and the `$`-anchored regex fails. The Review return has the same `$` pin (`?packet=<id>$`).

**Evidence:** web/live-workspace-e2e/live.spec.ts:352-353 (`toHaveURL(/\/workspace\/library\?view=notes$/)`), :457-459; web/lib/workspace/api.ts:121-136 (params appended after view)

**Fix:** Change 04 §1/§4 to: '`normalizeReaderReturnTo` keeps `focus` only for `/workspace/today` (and optionally `/workspace/radar`). Library and Review return URLs stay exactly `?view=<filter>` / `?packet=<id>` (live.spec.ts:353, :457-459). Library focus is restored from `sessionStorage` or defaults to the first work.' Update 03 §3 'Open' to match.

## E08 · [major] 02-design-system.md

**Where:** §6 Implementation 'one `<path d>` per colour key … giving five paths' and Moods table (sleepy: eye groups hidden, closed-eyes path; alert: pupils centred; idle blink: eyes scale Y); 05 WO-1.2 test 'renders … 5 paths'

**Problem:** With one path per colour, the K path holds the pupils and the mouth (row 8), and the W path holds both eyes. Eyes therefore cannot blink, hide (sleepy) or re-centre (alert) independently of the mouth. 'Sleepy' needs a sixth closed-eye path and 'alert' a different pupil geometry, which contradicts the '5 paths' test. 'Pupils centred' is also impossible in the 2-px-wide eyes (x4–5).

**Evidence:** 02-design-system.md:239-273; 05-phases-and-work-orders.md:99

**Fix:** Specify paths by part: body R, shade D, highlight H, eye whites W, pupils K (x5/x11, rows 5–6) and mouth K (x7–8, row 8). Wrap eye whites and pupils in `<g class="ws-mascot-eyes">`, add `ws-mascot-closed` (K at x4–5 and x10–11, row 5, hidden unless sleepy) and `ws-mascot-alert-pupils` (K at x5/x11, rows 4–5). Change the WO-1.2 test to 'exactly these 8 paths/classes, eyes group hidden when data-mood=sleepy'.

## E09 · [major] 02-design-system.md

**Where:** §8 Dialogs ("Native <dialog> with showModal()"); also 03 §3 Prev/next "Scroll the stage to top", 03 §11, 05 WO-7.1 tests

**Problem:** The unit environment (jsdom 30.0.1) does not implement `HTMLDialogElement.showModal`/`close`, `Element.prototype.scrollIntoView` or `Element.prototype.scrollTo`, and neither vitest.setup.ts nor any test stubs them. Calling them unguarded throws a TypeError in the palette, shortcuts and today-controller tests. jsdom also never fires `cancel` on Escape.

**Evidence:** node probe with web/node_modules/jsdom@30.0.1: typeof dialog.showModal === 'undefined', typeof el.scrollIntoView === 'undefined', typeof el.scrollTo === 'undefined'; repo precedent uses optional calls: Reader.tsx:213,221 and RetainedSource.tsx:121 `scrollIntoView?.({ block: "center" })`

**Fix:** Add to 02 §8 / 04 §5: "Call `el.scrollIntoView?.({block:'nearest'})` and `stage.scrollTo?.({top:0})` (or set `stage.scrollTop = 0`). Feature-detect `typeof dialog.showModal === 'function'`. Handle Esc with an explicit keydown handler, not only the native `cancel` event. In palette/shortcuts tests, stub `HTMLDialogElement.prototype.showModal`/`close` in beforeEach (set/remove `open`, dispatch `close`) and restore them afterwards."

## E10 · [major] 02-design-system.md

**Where:** §6 Mascot sizes: "72px in empty states, with a speech-bubble line such as 'Nothing new matched…' … The speech-bubble text *is* the existing empty-state copy, so tests keep passing." (also 02 §8 Empty state, 03 §3 item 5)

**Problem:** A bubble line plus the verbatim heading puts the same copy on the page twice, which breaks the exact *ByText queries. Making the duplicate aria-hidden does not help: Testing Library's *ByText matches aria-hidden nodes, because its default ignore is only 'script, style'.

**Evidence:** tests/workspace/experience.test.tsx:185, :191, :200 (findByText exact on the three Today empty headings), :1067 getByText("No items in this view.")

**Fix:** Replace the sentence with: "The empty-state copy renders exactly once: the existing `<h2>` heading IS the speech bubble, styled beside the mascot. The mascot SVG contains no text, and the copy is never repeated, not even with aria-hidden."

## E11 · [major] 03-screens-and-flows.md

**Where:** §1.1 desktop wireframe sidebar row 'RESUME  Continue your question ▸' (line 39); §1.3 drawer list '…question, resume, footer links…' (line 102); mobile wireframe (lines 79-98)

**Problem:** The wireframes put the resume/ActivityCard in the sidebar, which is the drawer on mobile. §3 Stage item 2 and 07 §5 put it in the stage above the paper. If the agent follows the wireframes, readiness.spec fails: it needs h2 'Continue your question' visible and above `.daily-item h3`. live.spec.ts:360/:375 also click 'Source and pin options' on mobile.

**Evidence:** web/live-workspace-e2e/readiness.spec.ts:16-21; live.spec.ts:360-379; web/components/workspace/ActivityCard.tsx:31,61 (h2 'Continue your question')

**Fix:** Remove 'RESUME…' from the §1.1 sidebar and draw it as a one-line strip above the cover in the stage. Delete 'resume' from the §1.3 drawer list. Add a 'Continue your question' strip line between 'What changed.' and the cover in the mobile wireframe.

## E12 · [major] 03-screens-and-flows.md

**Where:** §7 Interests 'The bar holds … "Save interests and question" (primary), plus "Discard draft…"' (lines 377-379); §8 bar schedule save; 04 §3

**Problem:** Both are buttons inside the page's `<form onSubmit>`. A portal moves them out of the form element in the DOM, so a click no longer submits; React's tree does not create a form owner. The kit does not mention this, and the Interests unit tests click 'Save interests and question'.

**Evidence:** web/components/workspace/Interests.tsx:119,334,351,356; web/components/workspace/Operations.tsx:165,200

**Fix:** Add to 04 §3: 'A submit button rendered through ControlBar must carry `type="submit" form="<form id>"`. Give the Interests form `id="workspace-interests-form"` and the schedule form `id="workspace-schedule-form"`. Non-submit buttons (Discard) keep their onClick.'

## E13 · [major] 03-screens-and-flows.md

**Where:** §3 Flows 'Prev/next. `history.replaceState(null, "", "?focus=<id>")`' (line 288)

**Problem:** This contradicts 04 §4. A raw replaceState fires neither popstate nor the `workspace:url` event that `useQueryParam` (useSyncExternalStore) subscribes to, so the focused paper would not re-render. It also throws away any other query params.

**Evidence:** 04-architecture.md:150-167 (subscribe to popstate + 'workspace:url'; setQueryParam dispatches EVENT)

**Fix:** Replace it with: '`setQueryParam("focus", id, "replace")` from `lib/workspace/urlState.ts`. It preserves other params and dispatches `workspace:url`.'

## E14 · [major] 03-screens-and-flows.md

**Where:** §1.4 keyboard map footnote '* Arrow keys and Enter act only when focus is on body, the stage or the control bar' (lines 128-129); 04 §5 guards

**Problem:** With focus on any bar button (e.g. Dismiss), Enter natively clicks that button, and the window keydown handler also clicks `[data-command="open"]`. The item is dismissed and the reader opens. The 04 §5 guards exclude only input/textarea/select/contenteditable, not buttons, links or summaries.

**Evidence:** 03-screens-and-flows.md:114-129; 04-architecture.md:203-206

**Fix:** Footnote: 'Enter, ←, → act only when `event.target` is `document.body`, `main#main` or the `.ws-bar` container itself. They are ignored when the target is (or is inside) `a, button, summary, [role=radio], [role=tab]` or any form field.' Add the same guard to 04 §5 and a test to shortcuts.test.tsx.

## E15 · [major] 03-screens-and-flows.md

**Where:** §2.1 Footer ("Export notes as Markdown ↗") together with §6 Library sidebar slot ("Export notes as Markdown ↗")

**Problem:** Following the kit puts two links named "Export notes as Markdown ↗" on /workspace/library: one in the Shell footer, which appears on every route, and one in Library's own slot. The live e2e clicks this link with a strict single-match locator, so it would fail on both projects.

**Evidence:** web/components/workspace/Library.tsx:59-65 (existing <a href="/api/workspace/export" download>); web/live-workspace-e2e/live.spec.ts:103 `page.getByRole("link", { name: /Export notes as Markdown/ }).click()` (Playwright strict mode)

**Fix:** Render the export link exactly once per page. Keep it in the Shell footer and delete the "Export notes as Markdown ↗" bullet from 03 §6's Library sidebar slot (and remove the existing link from Library.tsx). Alternatively, hide the footer copy when the pathname starts with /workspace/library. Add a 07 §5 row: "live.spec.ts:103 | exactly one link matching /Export notes as Markdown/ on Library".

## E16 · [major] 03-screens-and-flows.md

**Where:** §8 Sources & checks, Bar: "…and 'Save preferences · keep schedule disabled' when the schedule draft is dirty"

**Problem:** The e2e expects this button to be visible as soon as /workspace/operations loads, with nothing edited. Showing it only when the draft is dirty fails the test. Today it is always rendered.

**Evidence:** web/live-workspace-e2e/live.spec.ts:176-184 (goto operations, then expect button /Save preferences · keep schedule disabled/ toBeVisible); web/components/workspace/Operations.tsx:200-204 (unconditional)

**Fix:** Replace the clause with: "'Save preferences · keep schedule disabled' is always rendered and visible (disabled only while busy), whether or not the draft is dirty." Add live.spec.ts:176-191 ("Recurring schedule disabled" text, the always-visible Save preferences button, .workspace-receipt) to the 07 §5 table.

## E17 · [major] 03-screens-and-flows.md

**Where:** §4 Reader, Sidebar slot: "The reader's section outline: Source / Understand / Notes tabs as nav rows"

**Problem:** The "Your notes" link lives in the existing `nav[aria-label="Reading sections"]`. If that nav moves to the sidebar (the aside comes before main in DOM order, per 04 §2), the e2e loop never reaches it: it tabs forward from main at most 16 times. If the nav is copied instead of moved, the page has two links named "Your notes" and every single-match query breaks.

**Evidence:** web/components/workspace/Reader.tsx:598-616; live.spec.ts:215-227 (Skip→main, then ≤16 Tabs to link "Your notes"); live.spec.ts:77; retained.test.tsx:341,450; experience.test.tsx:495 (getByRole("link",{name:"Your notes"}))

**Fix:** Replace the bullet with: "Keep the existing `<nav aria-label=\"Reading sections\">` (Source / Understand / Your notes links) inside `main`, above the reader body. The sidebar may show an outline only if its controls have different names (e.g. buttons 'Jump to source / understand / notes'); never a second link named 'Your notes'."

## E18 · [major] 03-screens-and-flows.md

**Where:** §2.4 'Per route' ("Save interests and question" in the bar), §7 Interests bar, §8 Operations bar ("Save preferences · keep schedule disabled")

**Problem:** Both buttons are implicit submit buttons inside a `<form onSubmit>`. A button portaled into the bar sits outside that form in the DOM, so it is no longer associated with it and clicking it submits nothing. The inline fallback has the same problem if `<ControlBar>` is placed outside the `<form>` in JSX. The existing save tests would fail.

**Evidence:** web/components/workspace/Interests.tsx:119 (<form onSubmit>) and :333-335 (submit button); Operations.tsx:169 (<form onSubmit>) and :200-204; experience.test.tsx:771 clicks /Save preferences/ and expects a `schedule` call

**Fix:** Add to 03 §2.4 and 04 §3: "A form's submit button rendered through ControlBar must be `<button type=\"submit\" form={formId}>`, with `formId` from `useId()` set on the `<form id>`. Otherwise keep the submit button inside the form in the stage."

## E19 · [major] 03-screens-and-flows.md

**Where:** §5 Radar, Bar: "⏭ on the last item of a page offers 'Next page →'"

**Problem:** The sidebar keeps the existing "Next page →" button. A bar control with the same name makes two buttons named "Next page →". The Radar unit fixture returns one item per page, so the focused item is always the last one and both copies would render, failing findByRole/getByRole.

**Evidence:** web/components/workspace/Radar.tsx:285-297; tests/workspace/experience.test.tsx:711 findByRole("button",{name:"Next page →"}) and :734 getByRole(...) ; fixture items = current.works (1 work)

**Fix:** Replace with: "The bar's ⏭ keeps its own name (e.g. 'Next paper'). On the last item it is disabled, or it clicks the existing sidebar 'Next page →' button programmatically. Never render a second control named exactly 'Next page →' or 'First page'."

## E20 · [major] 04-architecture.md

**Where:** §2 Shell `<header className="ws-stage-header">breadcrumb · route action slot · status line</header>`, 'Breadcrumb … or from the stage-header slot' (line 99-100); §3 Slots (only `sidebar` and `bar`); 03 §2.2-§2.3

**Problem:** The Shell must render the breadcrumb `n / N`, Today's primary 'Read & investigate' link (href depends on the focused item) and the status-line source fragment and dot (`5/5 sources`, ok/limited/failed). The Shell has no workspace state. useWorkspace is not shared: each call issues its own GET state and goes stale after page writes. §3 defines no header slot, and 'route action slot' / 'stage-header slot' are never specified.

**Evidence:** web/lib/workspace/useWorkspace.ts:6-37 (per-call fetch, no shared cache); 04-architecture.md:80 and :111-127

**Fix:** Add a third slot to 04 §3: `WorkspaceSlots` gets `header: HTMLElement|null`, and `StageHeaderSlot` (portal with the same inline fallback) renders the page-provided `{position?: {n, N}, sources?: {ok, total, worst}, action?: ReactNode}` into a `<div ref={setHeaderNode}>` inside `.ws-stage-header`. The Shell always renders the static pinned status text itself and never calls `useWorkspace`. Update 03 §2.2/§2.3 to say the source fragment and action come from this slot.

## E21 · [major] 04-architecture.md

**Where:** §2 Shell shape (lines 79-83: `ws-bar-slot` only) vs 03 §2.4 'Row 1, the composer' and 'Per route … show only the composer row plus their own primary action'; 05 WO-2.2 owns Composer.tsx

**Problem:** The kit never says who renders the composer. The Shell sketch has only an empty bar-slot div, while 03 §2.4 implies the composer is present on every route and pages fill the rest. If pages render it through ControlBar, every route must import it. If the Shell renders it, its DOM position relative to the slot (and so the Tab order and row order 0/1/2) is undefined.

**Evidence:** 04-architecture.md:79-83; 03-screens-and-flows.md:185-207

**Fix:** State in 04 §2: 'The Shell owns the bar container: `<div className="ws-bar"><Composer/><div ref={setBarNode} className="ws-bar-slot"/></div>` as the last child of main. Pages portal only the player/actions (and optional Message) into `ws-bar-slot`. Unit tests without the Shell have no composer, and no existing test needs one.'

## E22 · [major] 04-architecture.md

**Where:** §4 'Radar already writes its params with pushState. Add `focus` to its `navigate()` and `fromURL()`…' (lines 176-177)

**Problem:** Radar's `navigate()` calls `setApplied(next)`, which re-runs the items fetch effect, and it pushes a history entry. Routing focus through it re-requests GET items, flips `loading`, and adds a Back entry on every ⏮/⏭ step. That contradicts 'Prev/next is instant' (06 §3) and the replace-not-push rule.

**Evidence:** web/components/workspace/Radar.tsx:68-98 (navigate → pushState + setApplied; effect on [applied] fetches items)

**Fix:** Replace with: 'Read Radar focus with `useQueryParam("focus")` and write it with `setQueryParam("focus", id, "replace")`. Do not add it to `navigate()`/`fromURL()`: navigate() rebuilds the URL from filters/cursor/as_of, so filter and page changes already drop focus.'

## E23 · [major] 04-architecture.md

**Where:** §6 Pre-authorized ratchet item 2 'Live route JS rows … Same ratchet entry shape' (lines 273-278)

**Problem:** Raising any `/workspace/*` JS ceiling also needs the pinned literal in tests/budgets.test.ts updated, or the full vitest suite fails. Item 1 lists its test literals (:668, :677); item 2 does not.

**Evidence:** web/tests/budgets.test.ts:682-688; web/budgets.json:373 (route-js-live-today …)

**Fix:** Append to item 2: 'Update the row's `budgetBytes`/`budgetLabel` in budgets.json (:373-460) and the matching literal `["route-js-live-<id>", 169_984, null]` in tests/budgets.test.ts:682-688, with the comment updated.'

## E24 · [major] 04-architecture.md

**Where:** §6 Budgets, item 2 "Live route JS rows … Same ratchet entry shape."

**Problem:** Raising a live JS ceiling also requires updating its pinned literal in tests/budgets.test.ts. Otherwise "row %s carries the ratified ceiling in bytes" fails. Item 1 mentions this only for the CSS rows (:668, :677). The ratchet test also requires `why.length > 80` (strictly), not "at least 80".

**Evidence:** web/tests/budgets.test.ts:682-687 (route-js-live-today/radar/interests/library/items-reader/operations at 169_984; route-js-live-review has no literal); :714 `expect(entry.why.length).toBeGreaterThan(80)`; :727-750 newest entry's `to` must equal budgetBytes, and each `from` must equal the previous `to`

**Fix:** Append to item 2: "For each raised row, update its literal in tests/budgets.test.ts:682-687 (review has none). The ratchet entry's `from` is 169984 and its `to` is the new budgetBytes, and update `budgetLabel`." In item 1, change "a why of at least 80 characters" to "a why longer than 80 characters".

## E25 · [major] 04-architecture.md

**Where:** §2 Shell sketch: `<div className="workspace-app ws-app font-ui" …>`

**Problem:** Today the Shell root is `daily-app workspace-app font-ui`. The sketch drops `daily-app`, which turns off 21 `.daily-app`-scoped rules in daily.css. These include the `:focus-visible` outline, input/select/textarea/label styling and the disabled-button cursor. Phases P2–P6 still render the old page content inside the new Shell (Gate G2), so every workspace control would lose its focus ring and form styling.

**Evidence:** web/components/workspace/Shell.tsx:21; web/components/daily/daily.css:1-35, 273, 483-502 (`.daily-app :focus-visible { outline: 2px solid var(--color-focus) }` at :14-16)

**Fix:** Change the sketch to `className="daily-app workspace-app ws-app font-ui"` and add: "Keep `daily-app` on the root until controller.css re-provides focus-visible, form-control and disabled styles under `.ws-app`. Remove it in the same commit that removes the last `daily-*` dependency."

## E26 · [major] 05-phases-and-work-orders.md

**Where:** Intro 'P4, P5 and P6 own disjoint component files, so they may run in parallel… each work order appends to its own fenced section of controller.css' (lines 29-32); 09 prompt 'they own disjoint files'

**Problem:** The parallel phases are not disjoint. (1) experience.test.tsx holds interleaved tests for the reader (P4, :279-546), Radar/Library/Import (P5, :547-743, :1003, :1116) and Interests/Operations (P6, :548-604, :744, :957, :1074). stage1.test.tsx holds reader and Library tests but is owned by WO-3.1. retained.test.tsx (P4) tests WorkCard (P5). (2) Common.tsx, ActivityCard.tsx and AllocationReceipt.tsx are listed as changed in 04 §1 but owned by no WO. FocusPaper/Queue/PlayerBar/Slots (P3) will be extended by Radar, Operations and Review. (3) Three branches that each append a fence at the end of controller.css conflict in git at the same hunk.

**Evidence:** web/tests/workspace/experience.test.tsx describe blocks at :121, :279, :547, :705, :779, :956; web/tests/workspace/retained.test.tsx:18,91 (imports WorkCard, asserts 'Read & investigate →'); 04-architecture.md:39

**Fix:** Add a WO-3.3 'Prepare parallel phases': split experience.test.tsx into per-route files with no assertion changes; pre-create empty fences in controller.css (`/* == P4 reader == */\n\n/* == end P4 == */` etc., separated by blank lines); assign Common/ActivityCard/AllocationReceipt to WO-3.1 (LoadingState/ServiceNotice moods to WO-7.2); freeze the P3 component APIs, with any change landing on the base branch first. Otherwise state 'run P4 → P5 → P6 sequentially' and update 09.

## E27 · [major] 05-phases-and-work-orders.md

**Where:** WO-1.4 'Apply the ratchet … only when a breach is real. It is normally done once, in P7 or P8' (lines 136-139); 06 §2 G3 'Budgets run, with any ratchet recorded'; 04 §6 'Raise the ceiling once'

**Problem:** There is 87 B of emitted-CSS headroom. WO-1.1's three-block palette fence alone (about 36 properties × 3) will breach at P1, and controller.css adds more in P2–P6 while workspace.css cannot be deleted until P4–P6 have folded their rules. The kit gives no rule for the intermediate gates: ratchet at P1, which consumes the 'once', or leave budgets red at G1–G6. G3 explicitly runs budgets.

**Evidence:** STATUS.md:30 (17,321 / 17,408, 87 B); web/budgets.json:269-279

**Fix:** Add to WO-1.4 and 06 §2: 'From WO-1.1 until WO-7.5, emitted-css is expected to exceed 17,408 B. G1–G6 record the measured bytes and the overrun in STATUS and are not blocked by it; no ratchet is applied before WO-7.5. G7 requires every row green (after deleting components/workspace/workspace.css), with the single ratchet if still needed.'

## E28 · [major] 05-phases-and-work-orders.md

**Where:** WO-2.1 footer 'Shortcuts' and WO-2.2 '/-prefixed text runs a command' (lines 157-187) vs 03 §2.4 'filter the command palette inline' and WO-7.1 (palette and ShortcutsDialog built in P7)

**Problem:** P2 must wire `?` / the 'Shortcuts' footer entry, the ⌘K chip and key, and slash commands that 'filter the command palette inline'. The palette and shortcuts dialog are only built in P7, so G2's 'keyboard plumbing is tested' and WO-2.2's acceptance cannot be checked as specified.

**Evidence:** 03-screens-and-flows.md:188-193; 05-phases-and-work-orders.md:358-368

**Fix:** WO-2.2 Do: '`/word [arg]` runs the first registry entry whose name starts with `word` (click its [data-command] or call location.assign). No palette UI yet. ⌘K and `?` are reserved but inert until WO-7.1.' WO-2.1: 'Render the "Shortcuts" button and the ⌘K chip in WO-7.1.' WO-7.1: add inline palette filtering for `/` text.

## E29 · [major] 05-phases-and-work-orders.md

**Where:** WO-3.1 Tests '`j` and `k` work' (line 228) and WO-6.3 'keys 1, 2 and 3' / 'new tests cover focus and keys'

**Problem:** `useWorkspaceShortcuts` lives in the Shell (04 §2), but Today and Review tests render the page without it, so key presses do nothing. Rendering `WorkspaceShell` calls `usePathname`, which review.test.tsx's and stage1.test.tsx's `next/navigation` mocks do not define, and an undefined mock export throws. The kit never says how key tests should be mounted.

**Evidence:** web/tests/workspace/review.test.tsx:8-10, stage1.test.tsx:17-19 (useSearchParams only); recon/02-tests.md §(d)

**Fix:** Add to WO-3.1/WO-6.3 and 07 §2.9: 'Keyboard tests render `<WorkspaceShell>{page}</WorkspaceShell>` in the new test files (today-controller.test.tsx, review keys) with `vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/today", useSearchParams: () => new URLSearchParams(window.location.search) }))`. Never add `usePathname` to LiveReader, LiveLibrary or CandidateReview, whose existing test mocks lack it.'

## E30 · [major] 07-test-impact.md

**Where:** §5 E2E specs table (and 03 §6 Library stage "The focused work, followed by its notebook entries")

**Problem:** The table leaves out the Library e2e pins. The e2e looks for a specific note among every `<article>` on /workspace/library?view=notes. If the stage shows only the focused work's entries, that note is missing whenever another work is focused first. The spec also pins the native select and the exact back link.

**Evidence:** web/live-workspace-e2e/live.spec.ts:324-333 (combobox "Library view" = notes; getByRole("article").filter({has: text}) → link "Resume this question →"), :352-356 (link "← Library" exact → URL /workspace/library?view=notes, combobox still notes); Library.tsx:143 `<article className="daily-notebook-entry">`

**Fix:** Add 07 §5 rows: "live.spec.ts:324-333 | `<select>` 'Library view' + every notebook entry in the view as an `<article>` holding its body and a 'Resume this question →' link" and "live.spec.ts:352-356 | exact link '← Library' returns to ?view=notes". In 03 §6, say: "In the notes view, the stage lists every notebook entry in the view (one `<article class=\"daily-notebook-entry\">` each), not only the focused work's. Keep the native 'Library view' select (chips may sit beside it)."

## E31 · [major] 08-local-stack.md

**Where:** §4 Seed (lines 73-81) and §7 '# backend must be on DB=workspace' (line 143)

**Problem:** §3 exports a single POSTGRES_URL (DB=workspace_rich by default). §4 then runs `migrate`, the CI seed ('— DB "workspace"') and the rich seed under that one URL, so both seeds land in workspace_rich and the `workspace` DB is never migrated or seeded. The live e2e then fails (`state.sources.length` 5, principal e2e). §7 never says how to switch the running API to DB=workspace.

**Evidence:** 08-local-stack.md:64-81; tools/rich_seed.py:17 (reads POSTGRES_URL); web/live-workspace-e2e/live.spec.ts:18-20

**Fix:** Replace §4 with explicit per-DB lines: `U=postgresql://workspace:workspace-local-only@127.0.0.1:15438`; `for DB in workspace workspace_rich; do POSTGRES_URL=$U/$DB WORKSPACE_RATE_DATABASE_URL=$U/$DB $VENV/bin/python -m src.workspace migrate; done`; `POSTGRES_URL=$U/workspace WORKSPACE_RATE_DATABASE_URL=$U/workspace WORKSPACE_E2E_SEED=1 E2E_PRINCIPAL=e2e $VENV/bin/python - < web/e2e/fixtures/workspace_seed.py`; `POSTGRES_URL=$U/workspace_rich WORKSPACE_RATE_DATABASE_URL=$U/workspace_rich WORKSPACE_OWNER=e2e WORKSPACE_MINUTES=45 $VENV/bin/python - < planning/12-workspace-controller-revamp/tools/rich_seed.py`. In §7, add: stop uvicorn (first line of §8), re-export both URLs with /workspace, and rerun the §5 uvicorn line.

## E32 · [minor] 00-charter.md

**Where:** Header 'Baseline commit: `18096be`'

**Problem:** 18096be contains only the handoff brief. The kit is at f5be574 (HEAD), and the code baseline is 916f038 (STATUS, 04 §6).

**Evidence:** git log: f5be574 kit, 18096be brief, 916f038 code

**Fix:** 'Code baseline `916f038`; kit commit `f5be574` on `claude/youthful-dirac-69v19d`.'

## E33 · [minor] 01-references.md

**Where:** §3 Spotify table row 'Hover reveals play affordance on rows | Hover or focus reveals `↵ open` on queue rows'

**Problem:** Queue rows are 'Show paper N of M' buttons, so Enter selects the paper and does not open the reader (02 §8, 04 §8). The hint promises a different action.

**Evidence:** 02-design-system.md:329; 04-architecture.md:317-320

**Fix:** Change to 'Hover or focus reveals a `↵ show` hint; opening is `o` or the bar's open button.'

## E34 · [minor] 01-references.md

**Where:** §1 table 'Breadcrumb `Today › 3 / 9`'; §2 'Rounded 16px container'; §3 'rounded panels (12px)'

**Problem:** These conflict with 03 §2.2 (`workspace › today › 03 / 09`) and 02 §4 (`--ws-radius-xl` 18px for the control bar, `--ws-radius-lg` 14px for panels).

**Evidence:** 02-design-system.md:177-183; 03-screens-and-flows.md:154

**Fix:** Change 01 to breadcrumb `workspace › today › 03 / 09`, bar radius 18px (`--ws-radius-xl`) and panel radius 14px (`--ws-radius-lg`).

## E35 · [minor] 01-references.md

**Where:** §4 'One mono status strip that always shows `● Local workspace · Real source metadata · private server saves · generation off` (this exact text is test-pinned)'

**Problem:** Only 'Real source metadata · private server saves · generation off' is pinned. 'Local workspace' is free to change (07 §3).

**Evidence:** 07-test-impact.md:184-193; live.spec.ts:44-47

**Fix:** '…(only "Real source metadata · private server saves · generation off" is test-pinned; keep it as the sole text of its own element).'

## E36 · [minor] 02-design-system.md

**Where:** §8 Progress '4px track (`border-subtle`)' vs §2.3 rule 'UI marks (… progress fill and track) are at least 3:1'

**Problem:** border-subtle against surface/raised is 1.22/1.13 (dark) and 1.28 (light), below the kit's own 3:1 floor, so a contrast test covering 'every pair the UI actually uses' fails.

**Evidence:** Computed WCAG ratios: #262626/#141414=1.22, #262626/#1C1C1C=1.13, #E3E3E3/#FFFFFF=1.28

**Fix:** Either use `--color-border-strong` for the track (3.46/3.20 dark, 3.45 light) or drop 'and track' from the rule and add 'primary fill vs track ≥ 3:1 (4.63 dark / 4.20 light)' to the §2.3 table.

## E37 · [minor] 02-design-system.md

**Where:** §4 Motion 'Use only the existing duration and easing tokens' vs table (equalizer 1.1s, blink 140ms every ~6s, hop 400ms)

**Problem:** None of these durations exists as a token (only 0/120/160/240/2400ms), so the agent must break one of the two instructions.

**Evidence:** web/app/tokens.css:182-186

**Fix:** 'Keyframe animations may use literal durations, but only inside `@media (prefers-reduced-motion: no-preference)`. Transitions use the duration tokens.'

## E38 · [minor] 02-design-system.md

**Where:** §8 Sidebar panel 'persist per viewer in localStorage … key `workspace-sidebar`'; 04 §2 'Close the drawer on route change: derive "closed" from the path…'

**Problem:** The Shell is mounted from app/(live)/template.tsx, which remounts on every navigation, so the drawer closes on its own. Reading localStorage during render causes an SSR hydration mismatch, and setState in an effect is a lint error. The kit gives no pattern.

**Evidence:** web/app/(live)/template.tsx:1-12

**Fix:** 04 §2: 'The Shell lives in template.tsx and remounts per route, so the drawer resets without extra logic. Read the collapsed flag with `useSyncExternalStore(subscribe, () => read("workspace-sidebar"), () => "expanded")` (try/catch), and write it in the toggle handler.'

## E39 · [minor] 02-design-system.md

**Where:** §1 '`--ws-canvas-outer` value is declared in the same scoped block on `:root:has(.workspace-app)` variants, or just let `.workspace-app` be `min-height: 100dvh`'

**Problem:** `--ws-canvas-outer` is missing from the §2.1 variable table, and the either/or leaves the decision to the agent.

**Evidence:** 02-design-system.md:37-41, :73-89

**Fix:** Pick one: 'Make `.workspace-app` `min-height: 100dvh` with `background: var(--color-canvas)`; no `--ws-canvas-outer`.'

## E40 · [minor] 02-design-system.md

**Where:** §2.1 Important note: "check whether `tests/tokens.test.ts` treats a `--ws-success` green as a forbidden 'success hue'. The ban at `:302-320` is on role names in tokens.json…"

**Problem:** This is already settled and the description is wrong. Lines 302-320 assert that `lib/tokens.ts` `color` has no `success`/`warning` key and that the `:root` rule declares no `--color-success`/`--color-warning`. `--ws-success` inside `.workspace-app` trips neither. None of the other tokens.css checks look outside `:root`, the dark `:root` blocks or the media `:root`. storybook.test.ts counts only distinct `--color-*` names, so redeclaring the 23 under `.workspace-app` keeps the count at 23.

**Evidence:** web/tests/tokens.test.ts:199-219 (ruleFor exact chains), :252-259 (declaredColours reads ROOT/DARK_ATTRIBUTE only), :302-320; web/tests/storybook.test.ts:127-130 (Set of `^\s*(--color-[a-z-]+):` names); other parsers take the first match (tests/primitives/support/css.ts:103-111, TraceSpine.test.tsx:856-859, shell/layout.test.ts:69)

**Fix:** Replace the note with: "Verified: `--ws-success` and every `--ws-*` variable in the scoped block, and the `.workspace-app` `--color-*` redeclarations, pass tokens.test.ts and storybook.test.ts. Lines 302-320 only forbid `success`/`warning` keys in lib/tokens.ts `color` and `--color-success`/`--color-warning` on `:root`. Still never put `--ws-*` on bare `:root` (that breaks the parity test at :277-280)."

## E41 · [minor] 02-design-system.md

**Where:** §8 Progress: "4px track (`border-subtle`)" vs §2.3 rule "UI marks (… progress fill and track) are at least 3:1"

**Problem:** `border-subtle` against `surface` is 1.22:1 (dark) and 1.28:1 (light), and against `canvas` 1.31 / 1.18. The kit's own 3:1 floor for the track fails. The fill against the track is 4.63 / 4.20.

**Evidence:** WCAG ratio recomputed from the kit hexes (#262626/#141414, #E3E3E3/#FFFFFF)

**Fix:** Either use `border-strong` for the track (3.46 / 3.45 on surface) or change the §2.3 rule to "progress fill ≥3:1 against both its track and the surface; the track is decorative". Add the chosen pair to the WO-1.1 contrast test.

## E42 · [minor] 02-design-system.md

**Where:** §8 Sidebar panel: "persist per viewer in `localStorage` under try/catch, key `workspace-sidebar`"

**Problem:** The key breaks the repo's naming (`arxiv-agent.*`). The RC-05 note limits persisted keys product-wide. Reading localStorage during render would also cause a hydration mismatch, so the kit should name the repo's pattern.

**Evidence:** web/lib/tokens.ts THEME_STORAGE_KEY "arxiv-agent.theme", RAIL_COLLAPSED_STORAGE_KEY "arxiv-agent.rail-collapsed"; web/lib/daily/store.ts:4 "arxiv-agent.workspace-preview.v1"; tests/shell/shell.test.tsx:237 ("RC-05 allows exactly two keys product-wide"); pattern in components/app/WorkbenchShell.tsx:222-260 (useSyncExternalStore, server snapshot false, try/catch)

**Fix:** Change to: "key `arxiv-agent.workspace-sidebar`, defined in lib/workspace (not lib/tokens.ts, whose keys tokens.test.ts:599-606 pins). Read it through useSyncExternalStore with server snapshot `false`, following WorkbenchShell.tsx:222-260. Record the extra key as an RC-05 deviation in STATUS."

## E43 · [minor] 03-screens-and-flows.md

**Where:** §3 Stage item 7 '`AllocationReceipt` (`.workspace-receipt`)' (line 259)

**Problem:** AllocationReceipt uses `.workspace-allocation`. The e2e-pinned `.workspace-receipt` is the Operations receipt `<pre>`, as 07 §5 and 04 §7 correctly say.

**Evidence:** web/components/workspace/AllocationReceipt.tsx:46; Operations.tsx:123

**Fix:** Change it to '`AllocationReceipt` (`.workspace-allocation`)'. Add: '`.workspace-receipt` belongs to the Operations receipt `<pre>` (live.spec.ts:189).'

## E44 · [minor] 03-screens-and-flows.md

**Where:** §8 Stage '(`details` "Inspect this check's receipt")' (line 390); also recon/04-surfaces.md §11/§13

**Problem:** The code and tests use U+2019 (’). An agent copying the kit's straight apostrophe breaks `getByText('Inspect this check’s receipt', {exact:true})`.

**Evidence:** web/components/workspace/Operations.tsx:120; live.spec.ts:186; experience.test.tsx:760

**Fix:** Write it as "Inspect this check’s receipt" (U+2019) and add it to 07 §4's verbatim table.

## E45 · [minor] 03-screens-and-flows.md

**Where:** §4 Reader 'Back to {Today | Library | Radar | Review}' and Control bar '"Pin this question" / "Unpin saved item"' (lines 307, 323); 07 §4 Reader row

**Problem:** The reader's pin button is `Pin ${kind}` ('Pin question'). 'Pin this question' is Today's ActivityCard label. The Review back link is '← Candidate review', which 07 §4 omits even though it is e2e-pinned.

**Evidence:** web/components/workspace/Reader.tsx:489-498, ~896-898; live.spec.ts:456

**Fix:** 03 §4: 'Pin question' / 'Unpin saved item'; back labels '← Today', '← Library', '← Radar', '← Candidate review'. Add '← Candidate review' to the 07 §4 Reader row.

## E46 · [minor] 03-screens-and-flows.md

**Where:** §5 Radar 'Bar. … ⏭ on the last item of a page offers "Next page →"' (line 346)

**Problem:** If the bar's ⏭ is relabelled or duplicated as 'Next page →', there are two buttons with that name. The Radar unit test uses a single-item page with next_cursor set, so the focused item is the last one, and `findByRole('button',{name:'Next page →'})` then fails on multiple matches.

**Evidence:** web/tests/workspace/experience.test.tsx:106-111 (items = current.works, 1 work), :707-711

**Fix:** 'On the last item, ⏭ keeps its own name (e.g. "Next paper") and clicks the sidebar's existing "Next page →" button (data-command `next-page`). Never render a second element named "Next page →".'

## E47 · [minor] 03-screens-and-flows.md

**Where:** §2.2 Row 1 'This is a link with the exact accessible name "Read & investigate →" only if it is the only one on the page. See 07 §2 for the duplicate-name rule' (lines 155-159); §2.4 Row 2 'round red open button'

**Problem:** 07 §2 has no rule about 'Read & investigate'. The kit never fixes the accessible names of the header action or the bar's round open button, or says whether FocusPaper keeps WorkCard's footer 'Read & investigate →' link. If any of these is named exactly by the title, it collides with the h3 link (experience:143, :241).

**Evidence:** 07-test-impact.md:114-128; web/tests/workspace/retained.test.tsx:91

**Fix:** State: 'Today header action: link "Read & investigate" (data-command="open"). Bar open: button or link with aria-label "Open in reader". FocusPaper has no footer "Read & investigate →" link. WorkCard keeps it (retained.test.tsx:91).' Fix the cross-reference to point to this text.

## E48 · [minor] 03-screens-and-flows.md

**Where:** §1.4 header 'These are suppressed when focus is in input…' and row '`Esc` | Close dialog or drawer; blur the input' (lines 109-126); 04 §5 guards

**Problem:** The input guard suppresses every key, which would also swallow Esc (blur the input) and ⌘K inside the composer. That contradicts the Esc row and usual ⌘K behaviour.

**Evidence:** 03-screens-and-flows.md:109-126; 04-architecture.md:203-206

**Fix:** In 03 §1.4 and 04 §5: 'Escape and ⌘K/Ctrl+K are exempt from the field guard. All other keys are ignored in fields.'

## E49 · [minor] 03-screens-and-flows.md

**Where:** §1.2 Tablet 'a queue mini-map of numbered dots, and a theme toggle' (lines 71-74)

**Problem:** A second, focusable copy of the queue or a second ThemeToggle breaks the 'exactly once' rules under css:false (07 §2.6): duplicate 'Show paper …' buttons and duplicate `theme-preference` radios.

**Evidence:** 07-test-impact.md:148-152

**Fix:** 'The rail shows the same queue `<ol>` restyled by CSS (numbers only) and a theme-cycle button. It never renders a second list or a second ThemeToggle.'

## E50 · [minor] 03-screens-and-flows.md

**Where:** §3 Stage item 7: "`AllocationReceipt` (`.workspace-receipt`)"

**Problem:** `AllocationReceipt` does not carry `.workspace-receipt`. Its root class is `.workspace-allocation`, and the Today disclosure is `details.workspace-edition-details`. The `.workspace-receipt` class that live.spec pins is on the Operations, RetainedSource and SyntheticWorkbench `<pre>` receipts.

**Evidence:** web/components/workspace/AllocationReceipt.tsx:46; Today.tsx:257; Operations.tsx:123; RetainedSource.tsx:321; SyntheticWorkbench.tsx:439,580; live.spec.ts:189

**Fix:** Change to "`details.workspace-edition-details` with `AllocationReceipt` (`.workspace-allocation`)". Note that `.workspace-receipt` must stay on the Operations/RetainedSource/SyntheticWorkbench receipt `<pre>`s.

## E51 · [minor] 03-screens-and-flows.md

**Where:** §3 "logic from `Today.tsx:33-62`" (repeated in 05 WO-1.3 "`Today.tsx:33-62`")

**Problem:** The range cuts off the `visible` filter that drops dismissed, archived and actively snoozed items. It runs through line 65.

**Evidence:** web/components/workspace/Today.tsx:33-58 (pinned versions) and :59-65 (visible filter)

**Fix:** Replace `Today.tsx:33-62` with `Today.tsx:33-65` in both files.

## E52 · [minor] 03-screens-and-flows.md

**Where:** §4 Reader Control bar: "'Save question', 'Mark read', 'Pin this question' / 'Unpin saved item' (labels e2e-pinned)" and Sidebar "Back to {Today | Library | Radar | Review}"

**Problem:** The reader has no "Pin this question". Its per-entry buttons read `Pin ${kind}` (e.g. "Pin question") or "Unpin saved item", inside each saved entry. "Pin this question" is the Today ActivityCard control. The Review back link reads "← Candidate review", not "Review", and the e2e pins it exactly.

**Evidence:** web/components/workspace/Reader.tsx:895-897 and :490-499; ActivityCard.tsx:55; live.spec.ts:361-363 (Today), :456 ("← Candidate review" exact)

**Fix:** Change to "…'Save question', 'Mark read', 'Save to Library', 'Archive', and the per-entry 'Pin {kind}' / 'Unpin saved item' buttons (keep them on their entries)". Change the back-link list to "← Today | ← Library | ← Radar | ← Candidate review (exact)".

## E53 · [minor] 03-screens-and-flows.md

**Where:** §8 Bar: "'Check {name} now' if the API supports per-source checks (it posts `refresh {source_ids:[id]}`)"

**Problem:** This is not conditional. The per-source check already exists and both its label and request body are pinned by a unit test.

**Evidence:** web/components/workspace/Operations.tsx:22-28 and :131-137; tests/workspace/experience.test.tsx:762-767 (button "Check arXiv cs.LG now" → refresh body source_ids ["arxiv-cs-lg"])

**Fix:** Replace with "the existing 'Check {name} now' button (posts `refresh {source_ids:[id]}`; label and body pinned by experience.test.tsx:762-767), exactly once per page".

## E54 · [minor] 03-screens-and-flows.md

**Where:** §2.1 Footer: storage line "(11–12px, faint; keep it)"

**Problem:** This contradicts 02 §3, "Minimum rendered size is 12px anywhere", and the house rule recorded in tokens.json typography.rules[0] (tests/tokens.test.ts:677-706).

**Evidence:** 02-design-system.md §3; web/tests/tokens.test.ts:701-706

**Fix:** Change "(11–12px, faint; keep it)" to "(12px, ink-faint; keep it)".

## E55 · [minor] 03-screens-and-flows.md

**Where:** §3 Flows, Prev/next: "`history.replaceState(null, "", "?focus=<id>")`"

**Problem:** A bare `history.replaceState` fires no event, so `useQueryParam` (useSyncExternalStore over popstate plus the custom `workspace:url` event, 04 §4) never re-reads and the focused paper does not change.

**Evidence:** 04-architecture.md §4 sketch: only `setQueryParam` dispatches `workspace:url`

**Fix:** Replace with "`setQueryParam(\"focus\", id, \"replace\")` (04 §4), which calls replaceState and dispatches `workspace:url`".

## E56 · [minor] 03-screens-and-flows.md

**Where:** §1.3 Mobile wireframe (stage starts "What changed. 03 / 09" then the cover/title)

**Problem:** The wireframe leaves out the resume strip. readiness.spec requires the h2 "Continue your question" to be visible and above the first `.daily-item h3`, with that title at y < 800 on 390×844. So the strip, plus the wrapping status line and nav row, must fit above the fold.

**Evidence:** web/live-workspace-e2e/readiness.spec.ts:16-21

**Fix:** Insert a "Continue your question · …" one-line strip between the h1 row and the cover in the mobile sketch. Add: "Budget: top bar + nav row + status line + h1 + resume strip + 96px cover + title ≤ 800px."

## E57 · [minor] 04-architecture.md

**Where:** §6 'Delete `workspace.css`' (line 243); 09 prompt 'delete workspace.css after folding it'

**Problem:** Two files have that name. components/features/workspace.css is the Evidence Workbench stylesheet, imported by ThreadTimeline, and must not be touched.

**Evidence:** web/components/features/ThreadTimeline.tsx:74; web/components/workspace/Shell.tsx:8

**Fix:** Always write `components/workspace/workspace.css` (and add 'not components/features/workspace.css').

## E58 · [minor] 04-architecture.md

**Where:** §2 Shell root `className="workspace-app ws-app font-ui"`

**Problem:** The current root also has `daily-app`, and daily.css has 21 `.daily-app …` base rules (form-control font inheritance and others). WO-2.1 keeps importing daily.css for not-yet-migrated pages, but the sketch silently drops the class, so those pages lose their base styling between G2 and G6.

**Evidence:** web/components/workspace/Shell.tsx:21; grep -c '^.daily-app' components/daily/daily.css = 21

**Fix:** 'Keep `daily-app` on the root until P7, and remove it in the WO-7.5 cleanup together with the daily.css import.'

## E59 · [minor] 04-architecture.md

**Where:** §8 Queue 'The status region announces "Paper N of M" only if no other message is pending'

**Problem:** After Dismiss or Snooze, auto-advance changes focus. An announcement would overwrite 'Saved on the server: dismissed.', which 03 §3 and the tests read from the single status region, and 'pending' is undefined.

**Evidence:** 03-screens-and-flows.md:284-287; experience.test.tsx:152-156

**Fix:** 'Announce "Paper N of M" only on explicit prev/next/queue clicks, never on auto-advance or after a write, or drop the announcement.'

## E60 · [minor] 04-architecture.md

**Where:** §4 "No useRouter. It is not mocked in any test file. Use no usePathname in LiveToday: stage1.test.tsx lacks that mock." (same claim in 07 §2.9)

**Problem:** `useRouter` is mocked in many test files, just none under tests/workspace. The usePathname gap is also wider than stage1: retained.test.tsx and review.test.tsx mock only `useSearchParams`, and synthetic.test.tsx and activity.test.tsx have no next/navigation mock at all.

**Evidence:** useRouter mocked in tests/HomePage.test.tsx:43-45, tests/features/LandingComposer.test.tsx:52-54, tests/shell/wiring.test.tsx:42-45, shell/recovery.test.tsx:79-82, shell/identity.test.tsx:48-51, shell/conversationRoute.test.tsx:37-41, threads/rail.test.tsx:40-44, threads/bridge.test.tsx:41-45. tests/workspace mocks: experience & routes = usePathname+useSearchParams; stage1, retained, review = useSearchParams only.

**Fix:** Replace with: "No tests/workspace file mocks useRouter, so do not use it. usePathname is mocked only in experience.test.tsx and routes.test.tsx, so it may be used only in the Shell, never in LiveToday, LiveReader or CandidateReview (rendered by stage1, retained and review). SyntheticWorkbench, ActivityCard, AllocationReceipt and InterestCoverage are rendered with no next/navigation mock, so they must not call any next/navigation hook."

## E61 · [minor] 04-architecture.md

**Where:** §7 table of legacy classes "Keep only the legacy classes that tests or e2e pin"

**Problem:** The table leaves out selectors that tests query directly.

**Evidence:** tests/workspace/retained.test.tsx:162,238 `.workspace-retained-text`; retained.test.tsx:436,505 and experience.test.tsx:392,435,472 `.daily-source-text p`; stage1.test.tsx:220 and live.spec.ts:334 `#workspace-entry-<id>`; stage1.test.tsx:226 `#source-anchor`; live.spec.ts:600-601 `#source mark`

**Fix:** Add rows: `.workspace-retained-text` (retained.test), `.daily-source-text p` (retained/experience), `id="workspace-entry-<id>"` (stage1, live.spec), `id="source-anchor"` (stage1), `#source mark` (live.spec).

## E62 · [minor] 04-architecture.md

**Where:** §1 CommandPalette.tsx row: "Lazy: loaded with `next/dynamic` or `import()` on first open"

**Problem:** Lazy loading is allowed and keeps the palette out of the gated number. route-budgets.mjs counts only rootMainFiles plus the chunks of the route entry's clientModules, and a measured React.lazy split already dropped out of a row. The repo's precedent, though, is `React.lazy(() => import(...))` + Suspense, not next/dynamic. A boundary only works if nothing imports the lazy module statically.

**Evidence:** web/scripts/route-budgets.mjs:205-239; budgets.json:43 (React.lazy composer build measured 143,426 B vs 158,899 B for `/`); components/app/WorkbenchShell.tsx:120-128 and components/patterns/PlanEditor.tsx:23-27 (lazy chosen over next/dynamic so Vitest and Storybook need no Next stand-in)

**Fix:** Change to "Lazy: `const CommandPalette = lazy(() => import(\"./CommandPalette\"))` behind `<Suspense fallback={null}>`, mounted only after first open (precedent WorkbenchShell.tsx:120-128). Nothing else may import CommandPalette.tsx or ShortcutsDialog.tsx statically; shared data lives in lib/workspace/commands.ts. Verify the live route rows did not grow with `npm run budgets`."

## E63 · [minor] 04-architecture.md

**Where:** §1 Leave alone table: "`src/` | No backend changes." (file states "All paths are relative to `web/`")

**Problem:** There is no web/src. The backend lives at the repository root.

**Evidence:** `ls web/src` → no such directory; backend at /home/user/arxiv-research-agent/src

**Fix:** Change `src/` to `../src/ (repository root)`.

## E64 · [minor] 05-phases-and-work-orders.md

**Where:** WO-5.2 Acceptance 'the notes-view return from the reader is preserved (`experience.test.tsx:1054-1069`)'; WO-6.3 'All 418 lines of `review.test.tsx`'

**Problem:** experience:1054-1069 is the view-select test, not the reader return. The return tests are stage1.test.tsx:206-226 and :315-357, plus live.spec.ts:352-355. review.test.tsx has 449 lines; its tests span :113-:418.

**Evidence:** web/tests/workspace/stage1.test.tsx:223-226; wc -l review.test.tsx = 449

**Fix:** WO-5.2: '(stage1.test.tsx:206-226, :315-357; live.spec.ts:352-355)'. WO-6.3: 'All tests in review.test.tsx (:113-:418)'.

## E65 · [minor] 05-phases-and-work-orders.md

**Where:** WO-1.2 Owns '`lib/workspace/queue.ts` (`coverSeed` only)', WO-1.3 Owns '`lib/workspace/queue.ts`… `lib/workspace/commands.ts`', WO-2.2 Owns '`lib/workspace/commands.ts` (keymap)'

**Problem:** The same files are owned by two WOs each. G1 requires 100% coverage of commands.ts, but it is unclear what commands.ts holds at P1 versus P2. 07 §6 also places coverSeed tests in queue.test.ts while WO-1.2 puts them in cover.test.tsx.

**Evidence:** 05-phases-and-work-orders.md:93,108-114,177-181; 07-test-impact.md:238

**Fix:** 'WO-1.3 creates commands.ts with the vocabulary and key map (pure data plus `commandForKey(event, sequence)`), fully tested. WO-2.2 only consumes it. coverSeed tests live in cover.test.tsx.' Update 07 §6 to match.

## E66 · [minor] 05-phases-and-work-orders.md

**Where:** WO-6.3 Acceptance: "All 418 lines of `review.test.tsx` semantics are preserved"

**Problem:** review.test.tsx has 449 lines, not 418.

**Evidence:** `wc -l web/tests/workspace/review.test.tsx` → 449

**Fix:** Change to "All 449 lines of `review.test.tsx`…", or drop the count.

## E67 · [minor] 05-phases-and-work-orders.md

**Where:** WO-5.2 Acceptance: "the notes-view return from the reader is preserved (`experience.test.tsx:1054-1069`)"

**Problem:** Those lines test switching the Library view select with rerenders, not the return from the reader. The notes-view return is pinned elsewhere.

**Evidence:** experience.test.tsx:1053-1072 (selectOptions notes/read/archived/all); reader return: stage1.test.tsx:212-226 ("← Library" href /workspace/library?view=notes), stage1.test.tsx:319-357 (Resume link return_to contains view=notes); live.spec.ts:352-356

**Fix:** Replace the citation with "(stage1.test.tsx:212-226 and :319-357, live.spec.ts:352-356; view switching in experience.test.tsx:1053-1072)".

## E68 · [minor] 05-phases-and-work-orders.md

**Where:** WO-1.2 Acceptance: "Lint clean, including the no-hex and no-`font-family` rules"

**Problem:** ESLint has no font-family rule. The ban is a repository scan in tests/fonts.test.ts, which also rejects the three family names anywhere, comments included, outside its exemption list.

**Evidence:** web/eslint.config.mjs (only tokens/no-literal-colour, primitives/no-data-layer, copy/no-inline-text); web/tests/fonts.test.ts:212-223 (family names) and :225-238 (`font-family:`, `font-[`, `fontFamily:`)

**Fix:** Replace with "`npm run lint` clean (no-literal-colour) and `npx vitest run tests/fonts.test.ts tests/tokens.test.ts` green (font-family / family-name scan and literal-colour scan)."

## E69 · [minor] 05-phases-and-work-orders.md

**Where:** WO-2.2 Tests: "`g` then `l` navigates; `location.assign` is stubbed" (also 03 §11 and 04 §5 route commands)

**Problem:** In jsdom 30, `window.location.assign` is non-configurable and non-writable, so `vi.spyOn(window.location, "assign")` throws "Cannot redefine property". Unstubbed, jsdom only logs "Not implemented: navigation".

**Evidence:** node probe: Object.getOwnPropertyDescriptor(location,'assign') → {configurable:false, writable:false}; precedent tests/shell/recovery.test.tsx:438 `vi.stubGlobal("location", { reload })`

**Fix:** Say: "Stub with `vi.stubGlobal(\"location\", { ...window.location, assign: vi.fn() })` (precedent tests/shell/recovery.test.tsx:438) and `vi.unstubAllGlobals()` afterwards. Do not use vi.spyOn(window.location, 'assign')."

## E70 · [minor] 05-phases-and-work-orders.md

**Where:** WO-1.3 Tests: "100% line and branch coverage of these modules" (urlState.ts)

**Problem:** The inline `() => null` getServerSnapshot in `useQueryParam` never runs in jsdom client renders. It only runs during server render and hydration. Coverage then counts an uncovered function, the problem the repo documents for every useSyncExternalStore server snapshot.

**Evidence:** web/vitest.config.mts:155-160 (getServerSnapshot functions run during hydration only); precedent: exported `serverThemePreference` (components/patterns/ThemeToggle.tsx) and `serverRailCollapsed` (components/app/WorkbenchShell.tsx:243-246) so tests can call them directly

**Fix:** In 04 §4, export a named `serverQueryParam(): null` and pass it as the third argument, and add a direct unit test for it in tests/workspace/urlState.test.ts.

## E71 · [minor] 05-phases-and-work-orders.md

**Where:** WO-0.1 Record: "The expected baseline is 53 workspace-related files and 1,417 tests on the subset"

**Problem:** The subset is never defined in 05. Running `npx vitest run` as listed will not produce 53 / 1,417. The figure comes from a specific filter, and the `tests/workspace` filter also matches tests/workspaceIdentity.test.ts, which accounts for the 53rd file.

**Evidence:** planning/12…/STATUS.md:16; find tests/{workspace,daily,shell,copy,primitives} -name '*.test.*' + tests/tokens.test.ts = 52, + tests/workspaceIdentity.test.ts = 53

**Fix:** Append: "Subset command: `npx vitest run tests/workspace tests/daily tests/shell tests/tokens.test.ts tests/copy tests/primitives` (vitest path filters are substrings, so this also runs tests/workspaceIdentity.test.ts)."

## E72 · [minor] 06-gates-and-verification.md

**Where:** §2 G1 '`queue.ts`, `urlState.ts` and `commands.ts` have 100% line coverage'

**Problem:** WO-1.3 requires 100% line and branch coverage of the same modules.

**Evidence:** 05-phases-and-work-orders.md:121

**Fix:** Change G1 to '100% line and branch coverage'.

## E73 · [minor] 06-gates-and-verification.md

**Where:** §2 G7 'axe reports zero serious/critical issues on all routes × 2 themes × 2 widths'; 05 WO-7.4

**Problem:** No spec or script does this, since live.spec runs axe on only some pages in the default theme. The agent must invent the harness, and a new file under live-workspace-e2e/ silently joins the 16-test baseline.

**Evidence:** web/live-workspace-e2e/playwright.config.ts testMatch '**/*.spec.ts'

**Fix:** Name the deliverable: 'Add live-workspace-e2e/controller-axe.spec.ts (7 routes × colorScheme light/dark; widths come from the existing desktop/mobile projects). The suite count rises from 16, which is recorded in STATUS.'

## E74 · [minor] 06-gates-and-verification.md

**Where:** §4 item 6 'The fictional preview … and the Evidence Workbench (/) are visually unchanged' vs 05 WO-8.1 step 6 'Optionally … daily.spec'

**Problem:** DoD requires proof, but the only check is optional, and the Workbench visual goldens are darwin baselines that cannot run here (05 P9.1).

**Evidence:** 05-phases-and-work-orders.md:412-414, :440-442

**Fix:** Make it mechanical: '`git diff --stat 916f038 -- web/components/daily web/app/(daily) web/app/(workspace) web/components/features web/components/patterns` is empty, the tokens.css diff is append-only after the last existing fence, and `PLAYWRIGHT_BROWSERS_PATH=$PWB npx --no-install playwright test -c playwright.workspace.config.ts` passes.'

## E75 · [minor] 07-test-impact.md

**Where:** §2 item 4 '`retained.test.tsx:190` uses `getAllByRole("status")` with length 1'

**Problem:** Wrong line number.

**Evidence:** web/tests/workspace/retained.test.tsx:229

**Fix:** `retained.test.tsx:229`.

## E76 · [minor] 07-test-impact.md

**Where:** §2.4 "`retained.test.tsx:190` uses `getAllByRole("status")` with length 1"

**Problem:** Wrong line. Line 190 is the start of a test title. The assertion is at line 229.

**Evidence:** web/tests/workspace/retained.test.tsx:229 `expect(screen.getAllByRole("status")).toHaveLength(1);`

**Fix:** Replace `retained.test.tsx:190` with `retained.test.tsx:229`.

## E77 · [minor] 07-test-impact.md

**Where:** §2.1 third bullet: "keep queue titles out of the accessible text (aria-hidden visual duplicate plus a named button)"

**Problem:** aria-hidden keeps a node out of *ByRole queries but not out of *ByText queries. Testing Library's getByText matches aria-hidden text, so this technique does not prevent duplicate getByText matches.

**Evidence:** @testing-library/dom default `ignore: 'script, style'` for *ByText; no current tests/workspace test calls getByText on a work title (grep)

**Fix:** Replace with "If a test needs getByText(<title>), scope it with `within(screen.getByRole('main'))` or the focused `article`. aria-hidden does not hide text from *ByText."

## E78 · [minor] 07-test-impact.md

**Where:** §5 E2E specs table (Review route; 03 §9 sidebar placement of "{n} candidates · {k} labelled")

**Problem:** The table leaves out the Review e2e pins. The count line must remain a heading, each candidate must remain an `<article>` holding the radios, the reason textbox, "Save judgment for candidate 1" and an "Inspect retained source →" link, and the back link must read "← Candidate review" and return to ?packet=.

**Evidence:** web/live-workspace-e2e/live.spec.ts:425-430 and :440-445 (heading exact "N candidates · 0 labelled"), :431-454 (getByRole("article").first() → radio Maybe, textbox "Optional reason for candidate 1", button, link), :455-467

**Fix:** Add a 07 §5 row: "live.spec.ts:402-470 | heading 'N candidates · K labelled' (keep it a heading wherever it moves); candidate cards stay `<article>`s containing radios, 'Optional reason for candidate N', 'Save judgment for candidate N' and 'Inspect retained source →'; '← Candidate review' returns to ?packet=".

## E79 · [minor] 08-local-stack.md

**Where:** §6 Screenshots; also 05 WO-0.2 'light and dark into `$WORK/before/`' and WO-8.1 '2 themes … deviceScaleFactor: 2'

**Problem:** tools/shot.cjs has no theme or DPR option, and it names files `${width}-${route}.png`, so a dark run overwrites the light run. WO-0.2/WO-8.1 cannot be met without editing the tool, and §6 also uses `$WORK/shots`, not `$WORK/before`.

**Evidence:** planning/12-workspace-controller-revamp/tools/shot.cjs:7-14; web/lib/tokens.ts:211

**Fix:** Add env knobs to tools/shot.cjs (`THEME=light|dark` → `colorScheme` plus the localStorage `arxiv-agent.theme` preference; `DPR` → `deviceScaleFactor`) and name files `${name}-${THEME}-${route}.png`. Document `THEME=dark DPR=2 node … $WORK/before` in §6.

## E80 · [minor] 08-local-stack.md

**Where:** §5 Start Next with `next dev` / intro "Use this stack for … manual QA"

**Problem:** CSP is switched off in development, so this stack cannot catch CSP violations: a Mascot `<style>` element, injected stylesheets or nonce problems. 02 §6 depends on CSP to rule these out.

**Evidence:** web/lib/server/csp.ts:168 `return env["NODE_ENV"] === "development" ? "off" : "enforce";`

**Fix:** Add to §5: "CSP is off under `next dev` (lib/server/csp.ts:168). Before G8, run once against a production server (`npm run build && npx next start -p 3000` with the same env) and check the browser console for CSP violations on all 7 routes."

## E81 · [minor] recon/00-first-session-brief.md

**Where:** Line 3 '**Read first:** this file' and §3 Palette table

**Problem:** The superseded brief tells the reader to read it first and gives a different palette (#E0242B, #111113, #A1A1AA, …), a 320–360px sidebar and a `today › 2 / 3` breadcrumb, all of which conflict with 02/03.

**Evidence:** recon/00-first-session-brief.md:3, :77-93

**Fix:** Prepend: '> Kit note: superseded by 00–09. Where this brief disagrees with 02-design-system.md or 03-screens-and-flows.md, those win.'

## E82 · [minor] recon/03-reader.md

**Where:** §5 'Route JS budget' (156,214 B, about 13.7 KB headroom)

**Problem:** This conflicts with the fresh measurement in recon/01 §4, 04 §6 and STATUS (162,472 / 169,984, 7,512 B headroom).

**Evidence:** recon/01-guardrails.md:128; 04-architecture.md:238

**Fix:** Annotate: 'Stale; use 162,472 B / 7,512 B headroom (recon/01 §4).'
