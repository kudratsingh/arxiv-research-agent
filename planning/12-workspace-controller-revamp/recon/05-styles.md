**Styling layer audit: live workspace vs. (daily) preview** (read-only, branch `claude/youthful-dirac-69v19d`)

Legend: **D** = `web/components/daily/daily.css`, **W** = `web/components/workspace/workspace.css`, `d/` = `web/components/daily/`, `w/` = `web/components/workspace/`. In "Defined", the first line is the base rule; the rest are descendant, override or media rules.

## 0. How the stylesheets load (needed context)

- **Live shell:**
  - `app/(live)/template.tsx:3,10` → `w/Shell.tsx` (client component).
  - `w/Shell.tsx:7-8` imports **D, then W**, so W wins ties on source order.
  - The root is `<div className="daily-app workspace-app font-ui">` at `w/Shell.tsx:21`.
  - The route group is gated by `WORKSPACE_LIVE=1` (`app/(live)/layout.tsx:8`).
- **Preview shell:**
  - `app/(daily)/template.tsx:14,18` → `d/DailyShell.tsx`.
  - `d/DailyShell.tsx:6` imports **D** only.
  - The root is `daily-app font-ui` at `d/DailyShell.tsx:12`.
  - The route group is gated by `WORKSPACE_PREVIEW=1` (`app/(daily)/layout.tsx:4`).
  - Storybook renders DailyShell too: `d/Workspace.stories.tsx:19-49`.
- **Global CSS:** `app/layout.tsx:18-19` imports `fonts/fallback.css` and `globals.css`.
  - `globals.css:3` imports `tokens.css`, then Tailwind base/components/utilities (`globals.css:5-7`).
  - Body is `bg-canvas text-ink antialiased` (`globals.css:15`).
  - Tailwind preflight is active, so buttons start transparent, borders start at 0 solid, headings inherit size/weight, `ul` has no list style, and `fieldset`/`legend` have no padding.
- **Co-residence:** the workspace links to the preview with a client `<Link href="/today">` (`w/Shell.tsx:37-39`). Under the App Router, React 19's hoisted stylesheets are not removed on client navigation. Assume D, W and any new sheet can all be in the document at once.
- **Workspace imports no shared primitives or patterns** apart from `SkipLink` and `ThemeToggle` (`w/Shell.tsx:5-6`). It has no inline `style={{}}` and no `position: fixed`/`sticky` anywhere in D or W.
- **Name collisions to avoid:** `components/features/workspace.css` is a different file using `.ew-thread__*` and `.ew-landing`. `ew-*` is also used by primitives, `tokens.css` and the workbench.

## 1. Class inventory

| class | defined | scope | used by (file:line) |
|---|---|---|---|
| daily-app | D:1,6-11,14,17-19,22,25,30,33,273,483,488-490,502,913,975 | SHARED | d/DailyShell.tsx:12; w/Shell.tsx:21 |
| daily-brand | D:45,756 | SHARED | d/DailyShell.tsx:15; w/Shell.tsx:24 |
| daily-brand-mark | D:52,63,760 | SHARED | d/DailyShell.tsx:16; w/Shell.tsx:25 |
| daily-brand-sub | D:68,764 | SHARED | d/DailyShell.tsx:21; w/Shell.tsx:30 |
| daily-button | D:418,430,435 | SHARED | d/Interests:254; d/Reader:244; d/Today:88; w/Import:198; w/Interests:333; w/Reader:810; w/SyntheticWorkbench:448; w/Today:197 |
| daily-caveat | D:324,330 | SHARED | d/Today:141; w/WorkCard:82 |
| daily-columns | D:215,705,721 | SHARED | d/Library:58; d/Today:58; w/Today:193 |
| daily-context | D:361,365,709,724 | SHARED | d/Library:100; d/Today:195; w/Today:265 |
| daily-coverage | D:220,227,236,240,249-250,254,844,847; W:491-493 | SHARED | d/Today:60; w/Common:61 (`data-complete`) |
| daily-dot | D:89 | SHARED | d/DailyShell:34; w/Shell:43 |
| daily-edition-end | D:445,453,456,904 | preview-only | d/Today:178 |
| daily-empty | D:461,464 | SHARED | d/Library:89; d/Today:82; w/CandidateReview:205,244; w/Library:169; w/Radar:262; w/Reader:43,456; w/Today:218,226 |
| daily-eyebrow | D:154,817 | SHARED | d/DailyShell:58; d/Interests:36,177; d/Library:39,101,110; d/Reader:33,114,129,176,260; d/Today:26,196,252,264; w/CandidateReview:129; w/Common:102; w/Import:85; w/Interests:98; w/Library:58,144; w/Operations:71,101,146,223; w/Radar:101; w/Reader:466,500,673,711,765,858; w/Shell:68; w/SyntheticWorkbench:247,610; w/Today:138,266 |
| daily-filters | D:479 | SHARED | d/Interests:115; w/Interests:188 |
| daily-form-footer | D:662,668,901 | SHARED | d/Reader:240; w/Reader:808 |
| daily-frame | D:96,699,784 | SHARED | d/DailyShell:38; w/Shell:49 |
| daily-generation | D:404,411,415 | SHARED | d/Reader:155; d/Today:251; w/Common:101; w/Operations:242 |
| daily-header | D:36,735,751 | SHARED | d/DailyShell:14; w/Shell:23 |
| daily-header-actions | D:74,738,768,773 | SHARED | d/DailyShell:26; w/Shell:35 |
| daily-interest-summary | D:534,538,541,544,553,558,561,744 | SHARED | d/Interests:176; w/Interests:252 |
| daily-interests-grid | D:468,473,715,741 | SHARED | d/Interests:108; w/Interests:175 |
| daily-intro | D:173,180,185,189,712,820,826,829; W:454,482-484 | SHARED | d/Interests:41; d/Library:44; d/Today:36; w/CandidateReview:136; w/Interests:105; w/Library:67; w/Operations:76; w/Radar:104; w/Today:151 |
| daily-item | D:281,298,851; W:488 | SHARED | d/Library:63; d/Today:111; w/CandidateReview:330; w/WorkCard:34 |
| daily-item-change | D:305; W:298 | SHARED | d/Today:133; w/CandidateReview:355; w/WorkCard:57 |
| daily-item-footer | D:334,342,346,857,860,864-865 | SHARED | d/Today:144; w/WorkCard:94 |
| daily-item-lead | D:302,854; W:489 | SHARED | d/Today:111 (template literal); w/WorkCard:34 (template literal) |
| daily-item-meta | D:285,293 | SHARED | d/Library:64; d/Reader:38; d/Today:114; w/CandidateReview:333; w/Reader:514; w/WorkCard:35 |
| daily-lens | D:920,928,934,941,945,969 | SHARED | d/Interests:51; w/Interests:120 |
| daily-link | D:168,400,773; W:215 | SHARED | d/DailyShell:28; d/Interests:37; d/Library:40,80,94,117; d/Reader:30,264,284; d/Today:29,150,221,242,272,277; w/AllocationReceipt:64; w/CandidateReview:132,231,371; w/Import:111,208; w/Interests:101; w/Library:60,160,179; w/Operations:119; w/Radar:119; w/Reader:49,479,490,536,880,907; w/RetainedSource:289,299; w/Shell:37; w/SyntheticWorkbench:435,576; w/Today:146,200,284,292; w/WorkCard:102 |
| daily-main | D:150,694,702,810 | SHARED | d/DailyShell:74; w/Shell:83 |
| daily-muted | D:688 | SHARED | app/(live)/workspace/items/[id]/page.tsx:17, library/page.tsx:5, review/page.tsx:7; d/Interests:143; d/Library:129; d/Reader:164; w/AllocationReceipt:32,58; w/CandidateReview:201,225,234,438; w/Common:9,32; w/Import:87,114; w/InterestCoverage:22,33,74; w/Interests:168,184,294,314; w/Library:97; w/Operations:74,150,213; w/Radar:102; w/Reader:777; w/RetainedSource:217,251; w/Today:251 |
| daily-notebook-entry | D:676,683 | SHARED | d/Library:109; w/Library:143; w/Reader:465 |
| daily-notes-panel | D:640,649,653,658,732,893,898 | SHARED | d/Reader:171; w/Reader:760 |
| daily-page-meta | D:160,813,817; W:479-481 | SHARED | d/Interests:35; d/Library:38; d/Reader:29; d/Today:25; w/CandidateReview:128; w/Interests:97; w/Library:57; w/Operations:70; w/Radar:100; w/Reader:489; w/Today:137 |
| daily-preview-bar | D:79,776,780 | SHARED | d/DailyShell:33; w/Shell:42 |
| daily-reader-grid | D:595,729,881,884 | SHARED | d/Reader:89; w/Reader:617 |
| daily-reader-header | D:567,571,575,870 | SHARED | d/Reader:37; w/Reader:513 |
| daily-reader-tabs | D:580,586,591,873,877 | SHARED | d/Reader:68; w/Reader:598 |
| daily-reason | D:310,315,319 | SHARED | d/Today:134; w/CandidateReview:360; w/WorkCard:72 |
| daily-saved | D:358 | SHARED | d/Today:125; w/WorkCard:40 |
| daily-saved-entries | D:672,675,682,917; W:212,215,227 | SHARED | d/Reader:256; w/Reader:841 |
| daily-secondary | D:419,438,442 | SHARED | d/Interests:74,180,245; d/Library:50,57; d/Reader:54,161; d/Today:181; w/CandidateReview:152,163,418; w/Common:27,109; w/Import:104,163; w/Interests:339; w/Library:94,124; w/Operations:132,200; w/Radar:211,218,272,286; w/Reader:541; w/RetainedSource:207; w/SyntheticWorkbench:262,406,513,521,531; w/Today:186 |
| daily-section-heading | D:264,272,277,839 | SHARED | d/Reader:96; d/Today:94; w/CandidateReview:215; w/Interests:177; w/Operations:92,208; w/Radar:229; w/Reader:625; w/Today:204 |
| daily-sidebar | D:102,109,114,122,128,787,793,797,803; W:1,328,331,335,342 | SHARED | d/DailyShell:39; w/Shell:50 |
| daily-sidebar-note | D:134,139,806 | SHARED | d/DailyShell:57; w/Shell:67 |
| daily-source-attribution | D:607 | SHARED | d/Reader:106; w/Reader:639 |
| daily-source-boundary | D:620,625 | SHARED | d/Reader:113; w/Reader:672 |
| daily-source-panel | D:601,887 | SHARED | d/Reader:92; w/Reader:621 |
| daily-source-text | D:613,616,890; W:179 | SHARED | d/Reader:110; w/Reader:644 |
| daily-status-dot | D:243 | SHARED | d/Today:62; w/Common:63 |
| daily-storage | D:143,807 | SHARED | d/DailyShell:68; w/Shell:78 |
| daily-streams | D:952,956,959,964 | preview-only | d/Today:259 |
| daily-text-button | D:351,917; W:56,212 | SHARED | d/Reader:269; d/Today:158; w/ActivityCard:53; w/CandidateReview:426,450; w/Reader:553,560,591,818,867,885; w/RetainedSource:258; w/SyntheticWorkbench:269,465,505,632; w/WorkCard:117,129,137 |
| daily-thread | D:369,372,378,381,391,395,400 | SHARED | d/Reader:136; d/Today:203,230; w/ActivityCard:29,59; w/Reader:722; w/Today:272 |
| daily-time | D:193,201,206,211,832,835; W:485-486 | SHARED | d/Today:45; w/Today:160 |
| daily-topic-list | D:505,510,518,524,527,908 | SHARED | d/Interests:147; w/Interests:213 |
| daily-understand-panel | D:631,635 | SHARED | d/Reader:124; w/Reader:707 |
| daily-warning | D:261 | preview-only | d/Today:74 |
| font-ui | Tailwind (`tailwind.config.ts:84-91`) | SHARED | d/DailyShell:12; w/Shell:21 |
| sr-only | Tailwind built-in | SHARED | d/Today:171; w/WorkCard:126,134,142 |
| error | W:34 (`.workspace-alert.error`) | live | w/Common:23,40 |
| workspace-app | W:1,179,204,212,215,227,328,331,335,342 | live | w/Shell:21 |
| workspace-mode | W:5 | live | w/Shell:42 |
| workspace-toolbar | W:8,15,358,490 | live | w/CandidateReview:150; w/Interests:332; w/Library:102; w/Radar:215; w/RetainedSource:204; w/Today:184,196,251 |
| workspace-alert | W:18,28,31,34 | live | w/CandidateReview:197; w/Common:23,40; w/Import:171; w/Operations:156 |
| workspace-controls | W:37,45-46 (`!important`),320,323,355 | live | w/Radar:129 |
| workspace-card-actions | W:49,56 | live | w/CandidateReview:417; w/Reader:531; w/SyntheticWorkbench:260,503; w/WorkCard:115 |
| workspace-source-list | W:59 | live | w/Operations:96 |
| workspace-source | W:64,70,77,80-81,87,91,94,345,348,352 | live | w/Operations:98 |
| workspace-note-context | W:99,104 | live | w/ActivityCard:49,52; w/CandidateReview:238,366; w/Library:148; w/Operations:234; w/Reader:468,667,776,862; w/RetainedSource:349; w/SyntheticWorkbench:255,321,569,623,674 |
| workspace-version-notice | W:107 | live | w/CandidateReview:444; w/InterestCoverage:27; w/Reader:508,587,772,902; w/RetainedSource:245,267; w/SyntheticWorkbench:330,373,415,495,590; w/Today:212; w/WorkCard:67 |
| workspace-import | W:113,118,121,126 | live | w/Import:84; w/Operations:143,207 |
| workspace-import-file | W:133,137 | live | w/Import:110 |
| workspace-topic-count | W:141 | live | w/InterestCoverage:41; w/Interests:256,269 |
| workspace-origin | W:147 | live | w/Reader:679; w/RetainedSource:302; w/SyntheticWorkbench:433,488 |
| workspace-list-pagination | W:152 | live | w/Radar:270 |
| workspace-reader-title | W:158 | live | w/Reader:519 |
| workspace-form-stack | W:161,164 | live | w/Library:81; w/Operations:143; w/Reader:569; w/SyntheticWorkbench:283,457 |
| workspace-check-label | W:167 (`!important`),173 | live | w/CandidateReview:396; w/Import:92 |
| workspace-inline-note | W:183,187 | live | w/Operations:220 |
| workspace-date | W:191 | **UNUSED** | none |
| workspace-receipt | W:194 | live | w/Operations:123; w/RetainedSource:321; w/SyntheticWorkbench:439,580 |
| workspace-activity | W:223 | live | w/ActivityCard:29,59 |
| workspace-activity-link | W:218,467,474 | live | w/ActivityCard:77 |
| workspace-activity-body | W:466,473 | live | w/ActivityCard:68 |
| workspace-focused-entry | W:227 | live | w/Reader:851 |
| workspace-allocation | W:231,240,243 | live | w/AllocationReceipt:46 |
| workspace-allocation-details | W:246,252 | live | w/AllocationReceipt:67 |
| workspace-allocation-compact | W:255 | live | w/AllocationReceipt:46 (template literal) |
| workspace-allocation-previews | W:259 | live | w/Interests:299 |
| workspace-interest-coverage | W:263 | live | w/InterestCoverage:16 |
| workspace-interest-row | W:268,274,277 | live | w/InterestCoverage:38 |
| workspace-review-link | W:280 | live | w/Radar:118; w/Today:289 |
| workspace-review-intro | W:283 | live | w/CandidateReview:225 |
| workspace-review-method | W:286,290 | live | w/CandidateReview:230 |
| workspace-review-candidate | W:294,298 | live | w/CandidateReview:330 |
| workspace-feedback | W:301,309,315 | live | w/CandidateReview:384 |
| workspace-retained-source | W:363,369 | live | w/RetainedSource:201 |
| workspace-retained-passage | W:373 | live | w/RetainedSource:342 |
| workspace-retained-text | W:377 | live | w/RetainedSource:359 |
| workspace-source-receipt | W:382 | live | w/RetainedSource:298 |
| workspace-synthetic | W:364,370,385,389,392 | live | w/SyntheticWorkbench:244 |
| workspace-synthetic-preview / -result | W:397-398 | live | w/SyntheticWorkbench:421 / :482 |
| workspace-span-picker | W:405,412,415,421,427 | live | w/SyntheticWorkbench:334 |
| workspace-inline-checkbox | W:416 (`!important`),422 | live | w/SyntheticWorkbench:378 |
| workspace-usage | W:432,437,441 | live | w/SyntheticWorkbench:539 |
| workspace-synthetic-draft | W:446,450 | live | w/SyntheticWorkbench:609 |
| workspace-today | W:454,479-493 | live | w/Today:136 |
| workspace-continuation | W:455,463-467,473-474,487 | live | w/ActivityCard:29 |
| workspace-continuation-options | W:475 | live | w/ActivityCard:95 |
| workspace-edition-details | W:476-477 | live | w/Today:257 |

**Summary of shared surface**
- 55 of D's 58 `daily-*` classes are used by both the preview and the live workspace. Only `daily-edition-end`, `daily-streams` and `daily-warning` are preview-only.
- **Any edit to D changes the preview.**
- Every `workspace-*` class is live-only. `workspace-date` is dead.

**Where W overrides D-owned markup (all scoped under `workspace-*` ancestors)**
- W:1-4 sidebar nav spacing
- W:56-58 text-button height
- W:179-182 source text `pre-wrap`
- W:204-211 `mark`
- W:212-217, 227-230 saved entries
- W:298-300 item-change `pre-wrap`
- W:327-344 mobile nav scroller
- W:453-494 Today compaction
- W:463-464 `.workspace-continuation > div` removes the `.daily-thread` rail and dot from D:372-390

**Why W needs `!important` today (W:47, W:168, W:417)**
D's element rules under `.daily-app` outrank single classes:
- `.daily-app label {display:block}` at D:483 is (0,1,1).
- `.daily-app input:not([type=checkbox]):not([type=radio])` at D:488 is (0,3,1).

D also has other blanket rules that affect everything inside `.daily-app`:
- `:focus-visible` outline (D:6-16)
- button cursor and disabled state (D:22-29)
- link hover underline (D:33-35)
- `.daily-app h2` at 18px/600 (D:272-276)
- inputs/selects/textareas forced to `display:block; width:100%; margin:8px 0 16px` (D:488-501)
- every button gets `min-height: 44px` under `pointer: coarse` (D:974-978)

**Attribute and state selectors in use**
- `[aria-current]`: nav (D:128, D:803) and reader tabs (D:591)
- `button[aria-pressed="true"]`: D:211, set at w/Today:166 and d/Today:50
- `.daily-reader-grid > [data-active="false"]`: D:884, set at w/Reader:622,708,761 and d/Reader:93,126,172
- `.daily-coverage[data-complete="true"]`: W:493, set at w/Common:61

## 2. Breakpoints and current mobile behaviour

| Query | File:lines | Effect |
|---|---|---|
| `min-width:1500px` | D:693-697 | `.daily-main` padding-inline 64px |
| `max-width:1150px` | D:698-719 | sidebar 192px → 152px; main padding 28px; Today aside 260px → 220px; intro h1 38px → 32px; interests aside 300px → 250px |
| `max-width:850px` | D:720-749, D:968-972 | Today, Reader, notes, interests and lens grids drop to 1 column; the asides stack under a top border; header padding 16px 20px |
| `max-width:700px` | W:319-326 | Radar `.workspace-controls` 3 → 2 columns, first label spans the row |
| `max-width:640px` | W:478-494 | Today compaction (below) |
| `max-width:600px` | D:750-911, W:327-361 | main "mobile" mode (below) |
| `pointer:coarse` | D:974-978 | all `.daily-app button` get `min-height: var(--size-target-coarse)` (44px) |
| `prefers-reduced-motion` | D:912-916; `tokens.css:303-310`; `primitives.css:221-226` | `scroll-behavior:auto`; durations drop to 1ms; `ew-enter`/`ew-pulse` removed |

**Today compaction at ≤640px (W:478-494)**
- Page meta becomes one line with ellipsis.
- Intro becomes a grid: h1 (1.7rem) beside the time picker; the intro `p` is hidden.
- Continuation goes to 1 column.
- Lead h3 is 1.55rem.
- The coverage `<details>` gets tighter.

**Main mobile mode at ≤600px (D:750-911, W:327-361)**
- **Header:** brand shrinks; actions (ThemeToggle and link) stack in a column, right-aligned (D:768-772).
- **Frame:** `.daily-frame` becomes `display:block` (D:784).
- **Sidebar → top strip:**
  - The sidebar turns into a horizontal tab strip (D:787-805).
  - Links get `min-height:44px`; the active link gets a bottom 2px signature rule.
  - Sidebar note and storage text are hidden (D:806-809).
  - In the workspace the strip scrolls sideways: nav `min-width:465px`, icon stacked over a 12px label, `nowrap` (W:327-344).
- **Main:** padding 24px 18px 48px (D:810-812).
- **Today:** intro, section heading and coverage `li` all switch to columns; item-footer controls get 44px height (D:820-869).
- **Reader:**
  - Tabs spread evenly at 44px (D:873-880).
  - `.daily-reader-grid` becomes `display:block` and inactive panels are hidden (D:881-886), so the mobile reader is tabbed while the desktop reader shows all panels.
  - Notes panel is flattened (D:893-900).
- **Operations source cards:** `dl` goes to 1 column (W:345-354).
- **Toolbar:** buttons grow to fill (W:358-360).

**Breakpoint mismatch**
- The two sheets use 600/640/700/850/1150/1500.
- Tokens define 480/768/1024/1280 (`tokens.css:87-90`). Tailwind's md/lg/xl equal these; Tailwind sm is 640.
- Media queries cannot use `var()`, so nothing enforces the tokens.

**Where it is tested**
- `live-workspace-e2e/playwright.config.ts:24-30`: desktop 1440×1000; mobile 390×844 with `isMobile` and `hasTouch` (so `pointer:coarse` applies).
- `workspace-e2e/daily.spec.ts:24-28`: preview must have no horizontal overflow.
- `live-workspace-e2e/readiness.spec.ts:16-21`: the "Continue your question" heading must sit above the first `.daily-item h3`, and on mobile that item's top must be under 800px.

## 3. ThemeToggle

- **Storage:** key `arxiv-agent.theme` (`lib/tokens.ts:211`), values `light | dark | system` (`:217`).
  - It is one of only two keys the product may persist (`:196-210`).
  - The other, `arxiv-agent.rail-collapsed`, is reserved and unused (`:214`). It is the sanctioned key if you want to persist sidebar collapse.
- **DOM attributes on `<html>`:**
  - `data-theme` = the resolved `light|dark` (`:224`).
  - `data-theme-preference` = the raw choice (`:232`).
- **Pre-paint script:** `themeInitScript` (`lib/tokens.ts:255-268`) is inlined with the CSP nonce in `app/layout.tsx:66`.
  - It reads storage; an invalid or missing value becomes `system`.
  - It resolves `system` through `matchMedia`, writes both attributes, and adds an OS `change` listener only if the preference was `system` at load.
- **CSS side:**
  - `tokens.css` has `:root` light (25-192), `@media (prefers-color-scheme: dark) :root` (195-226), `:root[data-theme="dark"]` (230-261) and `:root[data-theme="light"]` (265-296).
  - The attribute selectors are (0,2,0), so they beat the media `:root`.
  - Tailwind uses `darkMode: ["class", '[data-theme="dark"]']` (`tailwind.config.ts:64`).
- **Component (`components/patterns/ThemeToggle.tsx`):**
  - Markup: `<fieldset data-theme-toggle className="flex min-w-0 items-center rounded-md border border-border-subtle p-1 {className}">` (221-231). The legend is visually hidden; its text "Theme" comes from `lib/copy/shell.ts:62-67`.
  - Three `<label class="ew-theme-option"><input type=radio name="theme-preference" class="ew-visually-hidden"><span class="block rounded-sm px-2 py-1 text-ui-xs font-medium text-ink-muted">Light|Dark|System</span></label>` (236-250).
  - State comes from `useSyncExternalStore` reading `data-theme-preference`; the server snapshot is always `system` (99-115, 150-154).
  - `setThemePreference` writes both attributes plus storage inside try/catch (133-143).
  - It keeps following the OS while the preference is `system` (159-172) and adopts a click made before hydration (205-214).
  - The `className` prop reaches the fieldset only (145-147).
- **ThemeToggle.css:** checked state is `input:checked + span` with background `--color-primary` and text `--color-primary-on` (24-27); focus ring uses longhands (33-38); forced colours map the checked state to `Highlight`/`HighlightText` (63-68).
- **Tests on it:**
  - `tests/shell/themeToggle.test.tsx:274,291` requires the forced-colors block and the `.ew-theme-option input:checked` hook.
  - `tests/shell/layout.test.ts:175-199` requires no literal colours and the focus ring longhands in ThemeToggle.css.
  - Do not edit ThemeToggle.css. It is shared with `components/app/WorkbenchShell.tsx:507` and `d/DailyShell.tsx:27`.
- **Can it be re-skinned with CSS only? Yes.**
  - Target `[data-theme-toggle]`, `.ew-theme-option > span`, `.ew-theme-option input:checked + span`, and `:has(input[value="dark"])` for per-option icons.
  - Use at least (0,2,0) to beat Tailwind utilities (0,1,0), and (0,3,1) to beat ThemeToggle.css:24. Load order between `globals.css` and route CSS is not guaranteed, so do not rely on it.
  - **Caveat:** if you override the checked `background-color` at (0,3,1), you also beat the forced-colors rule (0,2,1) and bring back the WO-27 defect. Repeat `@media (forced-colors: active) { … input:checked + span { background-color: Highlight; color: HighlightText } }` at the same specificity.
  - Option height today is 12px text + 2×4px padding = 24px, which is only `--size-target-min`. Raise it in the sidebar.
  - The label text cannot change via CSS. Keep the text as the accessible name; icons go in `::before`.

## 4. Fonts

| Role | Family / faces | Declared | CSS var | Tailwind |
|---|---|---|---|---|
| UI / body | Atkinson Hyperlegible Next, variable 400–700, preload on | `app/fonts/fonts.ts:50-69` | `--font-ui` (`tokens.css:135`) | `font-ui`; `font-sans` is an alias (`tailwind.config.ts:90`) |
| Report serif | Literata roman variable 400–600 (optical size pinned at 17) + italic **400 only**, preload off | `fonts.ts:81-142` | `--font-report` (`tokens.css:136`) | `font-report` |
| Mono | IBM Plex Mono static 400 and 500, preload off | `fonts.ts:148-162` | `--font-mono` (`tokens.css:137`) | `font-mono` |

- **How the stack resolves:** the variables are put on `<html>` via `fontVariables` (`fonts.ts:165`, `app/layout.tsx:45`). Each stack is: webfont var → metric-adjusted fallback (`app/fonts/fallback.css:37-79`) → generic.
- **Type scale tokens:**
  - `--text-ui-{xs,sm,base,lg,xl}-{size,line,tracking}`
  - `--text-report-{small,body,h3,h2,h1}-*`
  - `--text-display-*`
  - `--text-mono-{xs,sm}-*`
  - Defined at `tokens.css:145-179`, available as Tailwind `text-ui-sm` etc.
  - The minimum rendered size is 12px (`tokens.css:139-143`).
- **Usage rules, enforced by `tests/fonts.test.ts`:**
  - No `font-family:`, `fontFamily:` or `font-[…]` anywhere outside the exempt list (`:225-244`, list at `:190-198`).
  - No family names in source (`:210-223`).
  - So use the `font:` shorthand with the variable, as D does (D:59, D:155, D:181: `font: 500 38px/1.2 var(--font-report)`), or the Tailwind utilities.
  - Remember the shorthand resets weight, style and line-height.
- **Weight and style limits:** no Literata above 600; italic exists only at 400. `.ew-report` sets `font-synthesis-style: none` (`tokens.css:404`).
- **Design-brief rule** (`tokens.css:358-360`): "the report never uses the UI family and the chrome never uses the report family". The current daily headings already use the serif for page titles and paper titles.

## 5. Recommendations for a self-contained revamp stylesheet

1. **Fully decouple from D.**
   - Remove `import "@/components/daily/daily.css"` (`w/Shell.tsx:7`) and the `daily-app` class (`w/Shell.tsx:21`).
   - Migrate every workspace `daily-*` class to a new prefix (for example `ws-*`).
   - Never edit `daily.css`: 55 of its classes are shared, and the preview, its Storybook stories and `workspace-e2e/daily.spec.ts` depend on them.
   - Dropping `daily-app` also removes the blanket element rules and the need for W's three `!important`s.
   - Leaving any `daily-*` class in workspace markup makes its styling depend on whether D happens to be loaded (sheets co-reside after client navigation).
2. **Namespace everything.**
   - Use one root class such as `.ws-app`; every selector starts with `.ws-app` or a `ws-` class.
   - No bare `:root`, `body` or element selectors at top level. If needed, use `:root:has(.ws-app)` for the overscroll background.
   - Avoid the `ew-*`, `daily-*` and old `workspace-*` prefixes.
   - Keep specificity at or below (0,2,1), except for the ThemeToggle overrides.
   - Replace W (494 lines) rather than adding beside it, and delete `workspace-date`.
3. **Palette (black/white/red).**
   - `tokens.css` is the only file allowed literal colours (`tokens.css:4`). `tests/tokens.test.ts:709-763` scans `.css`, `.tsx` and `.svg`, exempting only `tokens.css`, `app/icon.svg` and a test fixture.
   - Do not re-value the 23 global tokens. That would restyle `/`, `/c/[id]`, `/learn` and the preview, and break the parity, contrast and 23-colour checks (`tests/tokens.test.ts:276-300`, `:422+`).
   - Instead, add a new fenced block in `tokens.css`, placed before the WO-18 fence (`:312`), whose header says "NOTHING BELOW DECLARES A CUSTOM PROPERTY" (`:316`). In it, re-declare the existing `--color-*` (and optionally `--elevation-*`) names scoped to the root:
     - `.ws-app {light}`
     - `@media (prefers-color-scheme: dark){ :root:not([data-theme="light"]) .ws-app {dark} }`
     - `:root[data-theme="dark"] .ws-app {dark}`
   - These chains differ from the five `ruleFor` chains (`tests/tokens.test.ts:209-213`), so the parity tests are unaffected.
   - Because the names are reused, ThemeToggle.css, the primitives focus ring and SkipLink's Tailwind `bg-surface`/`text-ink` (SkipLink renders inside the root at `w/Shell.tsx:22`) re-skin automatically, and nothing outside `.ws-app` changes.
   - Add your own contrast unit test; `tokens.json`'s checks will not cover scoped values.
   - Measured contrast:
     - `#FF0000` on white is 4.0:1, which fails AA for body text.
     - `#FF0000` on black is 5.25:1.
     - `#D00000` on white is 5.7:1; `#C00000` on white is 6.48:1.
     - So split `--color-signature` (fill) from `--color-signature-text` (text) and `--color-signature-on` (text on a red fill), as the roles already allow (`tokens.css:44-46`).
   - Mascot SVG: use `currentColor` or `var(--…)` fills only.
4. **Fonts.** Use only the `font:` shorthand with `var(--font-ui|report|mono)` or the Tailwind utilities. Use `--text-*` sizes and keep everything at 12px or above.
5. **Floating bottom control bar.**
   - Position it `fixed` (or `sticky` at the bottom of main) with `padding-bottom: env(safe-area-inset-bottom)`.
   - Reserve space: give main a `padding-bottom` of bar height plus gap, and set `scroll-padding-bottom` on the scroller so focused items are not hidden (WCAG 2.2 SC 2.4.11).
   - Keep `z-index` below SkipLink's 20 (`primitives.css:202`).
   - Use `--elevation-2/3`; in dark mode also step to surface plus a `border-strong` outline (`lib/tokens.ts:47-51`).
   - The brief caps container radius at 6px (`tokens.css:107`, `lib/tokens.ts:110`). This is comment-only, not tested, so a pill-shaped bar is a deliberate deviation to note.
   - Buttons: `min-height: var(--size-target-coarse)` under `pointer:coarse`.
   - Motion: only `var(--duration-*)` and opacity entrances (`primitives.css:22-28`).
6. **Left sidebar.**
   - Desktop: `position:sticky; top:0; height:100dvh; overflow-y:auto; min-width:0`.
   - Mobile (≤767px recommended, matching the token breakpoint): an off-canvas drawer or top strip.
   - Keep 44px targets and the nav landmark labelled "Research workspace" (`w/Shell.tsx:51`; used by `live-workspace-e2e/live.spec.ts:98`).
   - Keep `<main id="main" tabIndex={-1}>` (`w/Shell.tsx:83`) as the SkipLink target (`SkipLink.tsx:32`).
7. **Keep test hooks, or update the tests in the same PR.**
   - `.daily-source-text p`: `tests/workspace/experience.test.tsx:392,435,472`; `tests/workspace/retained.test.tsx:436,505`
   - `.workspace-retained-text`: `retained.test.tsx:162,238`; `live-workspace-e2e/scientific-sample.walkthrough.ts:64`
   - `.workspace-activity`: `live.spec.ts:323-379`
   - `.workspace-receipt`: `live.spec.ts:189`
   - `.daily-item h3` plus the layout assertion: `readiness.spec.ts:18-21`
   - Link "Fictional preview" with `href="/today"`: `tests/workspace/routes.test.tsx:69`, `experience.test.tsx:129`
   - Radar link to `/workspace/radar`: `experience.test.tsx:132-135`
   - If the mobile reader stays tabbed, re-implement the hide-inactive-panel rule (`[data-active="false"]`).
8. **Other mechanical gates.**
   - No `outline: none` or `outline: 0` without a replacement in the same rule, in any `.css` under `web/` (`tests/primitives/policy.test.tsx:140-206`).
   - **CSS size budget:** `budgets.json:269-272` caps gzip CSS summed over every emitted `.css` at 17,408 B. The last measurement was 16,309 B (`budgets.json:158-163`), so there is about 1.1 KB of headroom.
     - D keeps shipping for the preview no matter what.
     - The new sheet must replace W, not add to it. Otherwise you have to ratchet `budgets.json` with a stated reason.
     - Verify with `npm run budgets`.
   - The live routes' JS ceilings are 169,984 B each (`budgets.json:373+`).