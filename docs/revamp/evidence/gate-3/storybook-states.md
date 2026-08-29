# State index — story → state → baseline screenshot → axe

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criteria 1 and 2. The browsable build is [`storybook/`](storybook/) — open
`storybook/index.html` and append `?path=/story/<story-id>` to reach any row
below.

**Criterion 1's blocker rule covers two lists, not one:** every
[§4](../../06-WORK-ORDERS.md#4-state-coverage-map) state, **and** every module
in RC-10's union component table. Both are tabulated here, and
[§3](#3-the-criterion-1-failure) records where the second list fails.

**Verdict: criterion 1 FAILS.** Two §4 rows and three RC-10 modules have no
story. Criterion 2 passes.

---

## 1. The §4 state coverage map

The **axe** column is the state-level result from the WO-22 gate — the audit of
the assembled route in the running app, at 1440 × 1200, in both themes
([`axe/summary.tsv`](axe/summary.tsv)). Per-*story* axe results are in
[§4](#4-rc-10s-union-component-table). "Baseline screenshot" is the retained
Gate 1 capture this state replaces; `—` means the baseline never captured it.

| # | State | Story ID | Replaces (baseline screenshot) | axe (light / dark) |
|---|---|---|---|:-:|
| 1 | Landing | `features-querycomposer--empty` | [`home-desktop-full.png`](../../baseline/screenshots/home-desktop-full.png) · [`home-mobile-full.png`](../../baseline/screenshots/home-mobile-full.png) | 0 / 0 |
| 2 | Rail loading | `threadrail--loading` | [`sidebar-loading-desktop.png`](../../baseline/screenshots/sidebar-loading-desktop.png) | 0 / 0 |
| 3 | Rail empty | `threadrail--empty` | — | 0 / 0 |
| 4 | Rail / backend error | `threadrail--error` · `features-querycomposer--upstream-down` | [`backend-offline-desktop.png`](../../baseline/screenshots/backend-offline-desktop.png) | 0 / 0 |
| 5 | Empty thread | **✗ none** — §4 names `ThreadTimeline/Empty` | [`conversation-empty-desktop.png`](../../baseline/screenshots/conversation-empty-desktop.png) · [`conversation-empty-mobile-full.png`](../../baseline/screenshots/conversation-empty-mobile-full.png) | 0 / 0 |
| 6 | Thread loading | `shell-skeleton--loading` (and `shell-skeleton--loaded`, `shell-skeleton--narrow`) | [`conversation-loading-desktop.png`](../../baseline/screenshots/conversation-loading-desktop.png) | 0 / 0 |
| 7 | Populated briefing | `patterns-reportreader--long-with-headings` | [`conversation-populated-desktop-full.png`](../../baseline/screenshots/conversation-populated-desktop-full.png) · [`conversation-populated-mobile-full.png`](../../baseline/screenshots/conversation-populated-mobile-full.png) | 0 / 0 |
| 8 | Dark mode | theme **axis** on every story — plus explicit `*--dark` stories in 22 of the 34 groups | [`conversation-populated-dark-desktop.png`](../../baseline/screenshots/conversation-populated-dark-desktop.png) | 0 / 0 |
| 9 | Plan review | `patterns-planeditor--default` | [`plan-review-desktop.png`](../../baseline/screenshots/plan-review-desktop.png) · [`plan-review-mobile-full.png`](../../baseline/screenshots/plan-review-mobile-full.png) | 0 / 0 |
| 10 | Running | `patterns-tracespine--running-with-checkpoint` | [`running-desktop.png`](../../baseline/screenshots/running-desktop.png) | 0 / 0 |
| 11 | Reconnecting | `patterns-tracespine--reconnecting` | [`reconnecting-desktop.png`](../../baseline/screenshots/reconnecting-desktop.png) | deferred¹ |
| 12 | Rejoined after reload | `patterns-tracespine--running-no-checkpoint` | — | deferred¹ |
| 13 | Cancelled | `patterns-tracespine--cancelled` | [`cancelled-desktop.png`](../../baseline/screenshots/cancelled-desktop.png) | 0 / 0 |
| 14 | Failed with partial briefing | `patterns-reportreader--partial-from-failed-run` | [`failed-partial-desktop.png`](../../baseline/screenshots/failed-partial-desktop.png) · [`failed-partial-mobile.png`](../../baseline/screenshots/failed-partial-mobile.png)² | 0 / 0 |
| 15 | Failed, no result | `patterns-tracespine--failed` · `patterns-statusbanner--severities` | — | 0 / 0 |
| 16 | Expired run | `patterns-tracespine--unavailable` | [`expired-job-desktop.png`](../../baseline/screenshots/expired-job-desktop.png) | 0 / 0 |
| 17 | Submission error | `features-querycomposer--failed-with-orphan-thread` (and the `features-querycomposer--*` failure set) | [`submission-error-desktop.png`](../../baseline/screenshots/submission-error-desktop.png) | 0 / 0 |
| 18 | Rate limited (429) | `patterns-statusbanner--rate-limited` · `patterns-statusbanner--rate-limited-retry-after` | — | 0 / 0 |
| 19 | Unauthorized (401) | `patterns-statusbanner--unauthorized` | — | 0 / 0 |
| 20 | Validation (422) | `patterns-planeditor--validation-422` · `features-querycomposer--validation` | — | 0 / 0 |
| 21 | Thread not found (inline) | `shell-notfoundproduct--default`³ | [`conversation-not-found-desktop.png`](../../baseline/screenshots/conversation-not-found-desktop.png) | 0 / 0 |
| 22 | Route not found (404) | `shell-notfoundframework--default`³ | [`framework-not-found-desktop.png`](../../baseline/screenshots/framework-not-found-desktop.png) | 0 / 0 |
| 23 | Export refused (409) | `patterns-exportdisclosure--unavailable-no-report` · `patterns-exportdisclosure--refused-409` | — | 0 / 0 |
| 24 | Delete confirmation | `threadrail--delete-confirm` | — | deferred¹ |
| 25 | Stream recycled (`stream_timeout`) | `patterns-tracespine--stream-timeout` | — | deferred¹ |
| A | Handoff `router.push('/c/{id}?job=')` | E2E only — slice step 1→2, all five projects | — | deferred¹ |
| B | No active job (`/c/[id]` without `?job=`) | **✗ none** — §4 names `ThreadTimeline/NoActiveRun` | — | 0 / 0 |
| C | Attached — status unknown | `patterns-tracespine--status-unknown` | — | 0 / 0 |
| D | Review submitted, not settled | `patterns-planeditor--submitting` (and `--submitting-cancel`, `--resolving`) | — | deferred¹ |
| E | Review conflict (409) | `patterns-planeditor--conflict-409` | — | deferred¹ |
| F | Proxy misconfigured 503 / upstream 502 | `patterns-statusbanner--proxy-misconfigured` · `patterns-statusbanner--upstream-down` · `features-querycomposer--proxy-misconfigured` | — | 0 / 0 |

¹ **"deferred" is about the axe column only, not about story coverage.** Eight
§4 rows have no *resting layout* for the browser tier to audit as its own
state, and `web/e2e/support/states.ts` records each with a reason in
`DEFERRED_STATES`: row 8 is a theme axis rather than a layout; 11, 12 and 25
are stream transitions asserted for behaviour in `stream.spec.ts` and
`attach.spec.ts`; 24 needs two clicks after navigation and is held by
`tests/threads/confirmDialog.test.tsx`; A is a navigation, asserted end to end
as slice step 1→2; D and E are entered by *resolving* a review and are asserted
in `slice.spec.ts` step 3. Every one of them still has a story, and every story
was axe-audited — see [§4](#4-rc-10s-union-component-table).
`web/e2e/reflow.spec.ts` holds the partition with a test of its own: swept ∪
deferred must equal §4 exactly, in both directions.

² `failed-partial-mobile.png` is a byte-identical duplicate of
`conversation-populated-mobile-full.png` in the retained baseline — a Gate 1
capture defect, recorded in
[`reflow/README.md` §5](reflow/README.md#5-two-caveats) and not corrected here.

³ See [§2](#2-4s-story-group-names-versus-the-shipped-story-ids).

**Twenty of the thirty-one rows are audited as their own state in the running
app, in both themes, at zero violations. Two rows have no story.**

---

## 2. §4's story-group names versus the shipped story IDs

§4's "Story group" column was written before the components were built, and
some of its names did not survive contact with the implementation. **None of
these is a coverage gap.** Most are a layer prefix the §4 shorthand omitted;
only the two `Shell/NotFound*` rows are a genuine rename, and in both cases the
shipped story's own file header names the §2.2 row it serves — which is how
they can be matched with confidence rather than by resemblance.

| §4 says | Shipped as | Evidence |
|---|---|---|
| `Shell/NotFoundInline` (row 21) | **`Shell/NotFoundProduct`** | `components/app/NotFoundProduct.stories.tsx` header: "03 §2.2 row 21, the 404 the PRODUCT raises" |
| `Shell/NotFoundProduct` (row 22) | **`Shell/NotFoundFramework`** | `components/app/NotFoundFramework.stories.tsx` header: "03 §2.2 row 22, the 404 the FRAMEWORK raises" |
| `QueryComposer/*` | **`Features/QueryComposer/*`** | layer prefix only |
| `TraceSpine/*`, `PlanEditor/*`, `ReportReader/*`, `StatusBanner/*`, `SectionRail/*`, `MetricsStrip/*`, `CheckpointLedger/*`, `ThemeToggle/*`, `ExportDisclosure/*` | **`Patterns/…`** | layer prefix only |
| `ThreadRail/*` | **`ThreadRail/*`** (meta title on `components/patterns/ThreadList.stories.tsx`) and **`ThreadRail/Drawer/*`** (on `components/features/ThreadDrawer.stories.tsx`) | RC-12's lexicon: the component is `ThreadList`, the surface is the thread rail |

`Diagnostics/*` ships with no layer prefix, matching WO-16 criterion 9's
wording exactly.

---

## 3. The criterion-1 failure

**Two §4 rows and three RC-10 modules have no story.**

| Missing story group | Named by | Owner |
|---|---|---|
| `ThreadTimeline/Empty` | §4 row 5, "Empty thread" | **WO-20** |
| `ThreadTimeline/NoActiveRun` | §4 row B, "No active job (`/c/[id]` without `?job=`)" | **WO-20** |
| `ActiveRunPanel/*` | RC-10 union table, `features/` | **WO-20** |
| `EmptyState/*` | RC-10 union table, `patterns/` | **WO-14** |

`components/features/ThreadTimeline.tsx`,
`components/features/ActiveRunPanel.tsx` and
`components/patterns/EmptyState.tsx` all exist and all ship; none has a
`.stories.tsx`.

**How it slipped, precisely.** RC-10's union table lists all three modules. But
RC-10's discharge sentence says the §5.3 story list "must be extended for
exactly **four** modules — `Diagnostics`, `SectionRail`, `CheckpointLedger`,
and `ThemeToggle`", and
[`04` §5.3](../../04-ARCHITECTURE.md#53-the-degraded-state-matrix-as-stories)'s
own group list (ConversationRail, ComposerCard, TraceSpine, PlanEditor,
ReportReader, MetricsStrip, ExportMenu, FailureNotice, Shell) contains none of
the three either. So no work-order card was ever given the criterion: **WO-20's
card has no story criterion at all**, and WO-14 criterion 9's list does not
include `EmptyState`. RC-10's arithmetic was short by three — and the four
cards that *were* given named story criteria to discharge RC-10 (WO-08 c11,
WO-15 c11, WO-16 c9, WO-18 c10) all delivered.

**What is established for rows 5 and B despite the gap.** Both are reachable
and audited in the running app. The e2e state `thread-empty` claims
`rows: ["5", "B"]`, is swept by the axe gate in light and dark at 1440 × 1200
at zero violations, and by the reflow sweep at 320 / 360 / 412 — which is
WO-20 criterion 7's evidence ("Every state in §4 is reachable in the running
app, evidenced by the Playwright state sweep"). What is missing is the
Storybook half, and only the Storybook half. Both modules are also visible in
[`coverage-summary.md` §4](coverage-summary.md#4-the-lowest-covered-files-and-why)
as two of the six lowest-covered files, which is the same gap seen from a
different instrument.

**This work order does not fix it.** The fix belongs to WO-20 and WO-14.

---

## 4. RC-10's union component table

Criterion 1's second list — the union of the brief's and the architecture's
component inventories, resolved onto the three-layer structure.

The **axe** column is the authoritative per-story result: WO-06 wires
`a11y: { test: "error" }` with the baseline tag set into
`.storybook/preview.tsx`, and the Vitest Storybook project executes every story
as a component test with that axe run attached. `npx vitest run
--project=storybook` on this commit: **34 files, 261 stories, 261 passed.** A
violation fails the story, so "261/261" *is* the axe result for every story in
the table below.

| Layer | Module | Story group | Stories | axe |
|---|---|---|---:|:-:|
| `primitives/` | `Button` | `Primitives/Button` | 12 | ✅ |
| `primitives/` | `Field` | `Primitives/Field` | 10 | ✅ |
| `primitives/` | `Textarea` | `Primitives/Textarea` | 11 | ✅ |
| `primitives/` | `Disclosure` | `Primitives/Disclosure` | 9 | ✅ |
| `primitives/` | `Dialog` | `Primitives/Dialog` | 7 | ✅ |
| `primitives/` | `Menu` | `Primitives/Menu` | 9 | ✅ |
| `primitives/` | `StatusBadge` | `Primitives/StatusBadge` | 9 | ✅ |
| `primitives/` | `Skeleton` | `Primitives/Skeleton` | 9 | ✅ |
| `primitives/` | `VisuallyHidden` | `Primitives/VisuallyHidden` | 6 | ✅ |
| `primitives/` | `ScrollRegion` | `Primitives/ScrollRegion` | 7 | ✅ |
| `primitives/` | `SkipLink` | `Primitives/SkipLink` | 6 | ✅ |
| `patterns/` | `TraceSpine` | `Patterns/TraceSpine` | 20 | ✅ |
| `patterns/` | `CheckpointLedger` | `Patterns/CheckpointLedger` | 10 | ✅ |
| `patterns/` | `PlanEditor` | `Patterns/PlanEditor` | 13 | ✅ |
| `patterns/` | `ReportReader` | `Patterns/ReportReader` | 11 | ✅ |
| `patterns/` | `SectionRail` | `Patterns/SectionRail` | 7 | ✅ |
| `patterns/` | `MetricsStrip` | `Patterns/MetricsStrip` | 5 | ✅ |
| `patterns/` | `ExportDisclosure` | `Patterns/ExportDisclosure` | 7 | ✅ |
| `patterns/` | `Diagnostics` | `Diagnostics` | 5 | ✅ |
| `patterns/` | `ThreadList` | `ThreadRail` | 8 | ✅ |
| `patterns/` | **`EmptyState`** | **✗ none** | **0** | — |
| `patterns/` | `StatusBanner` | `Patterns/StatusBanner` | 23 | ✅ |
| `patterns/` | `ConfirmDialog` | `ThreadRail/Delete Confirm` + `Primitives/Dialog` | 1 + 7 | ✅ |
| `patterns/` | `ThemeToggle` | `Patterns/ThemeToggle` | 6 | ✅ |
| `features/` | `QueryComposer` | `Features/QueryComposer` | 16 | ✅ |
| `features/` | **`ActiveRunPanel`** | **✗ none** | **0** | — |
| `features/` | **`ThreadTimeline`** | **✗ none** | **0** | — |
| `features/` | `ThreadRail` | `ThreadRail` | 8 | ✅ |
| `features/` | `ThreadDrawer` | `ThreadRail/Drawer` | 2 | ✅ |
| `app/` | `WorkbenchShell` | `Shell/WorkbenchShell` | 9 | ✅ |
| `app/` | `NotFound` | `Shell/NotFoundProduct` + `Shell/NotFoundFramework` | 2 + 2 | ✅ |
| `app/` | `RouteError` | `Shell/ErrorBoundary` | 3 | ✅ |

**29 of the 32 union modules have stories. Three do not** — the criterion-1
failure in [§3](#3-the-criterion-1-failure).

RC-10 said `ConfirmDialog` and `SkipLink` were "already covered by §5.3" and
needed nothing added; both are confirmed covered above. The four RC-10 named as
needing new stories — `Diagnostics` (WO-16 c9), `SectionRail` (WO-18 c10),
`CheckpointLedger` (WO-15 c11) and `ThemeToggle` (WO-08 c11) — all shipped,
with 5, 7, 10 and 6 stories respectively. **They cannot pass by absence, and
they did not.**

Not in RC-10's union table but shipped anyway, and audited on the same terms:
`Shell/Skeleton` (3), `Shell/SkipLinkFocused` (1), `Shell/IdentitySlot` (1),
and the three `Foundations/*` groups (12) that document the token layer.

### A second, unscoped axe pass — reported, not gated

As a cross-check this pack also ran `axe.run(document)` in real Chromium over
each story's whole iframe at 1440 × 900, in light and dark — 522 runs. **It is
not a gate and is not presented as one**, because a story is a component
fragment, not a page: 414 of the 522 runs flag `landmark-one-main`, 412 flag
`page-has-heading-one` and 273 flag `region`, all of which are document-level
rules that a fragment cannot satisfy and which the composed routes *do* satisfy
(see [`axe-diff.md`](axe-diff.md), 40/40 at zero).

Two findings from that pass are **not** document-level and are worth handing to
WO-27's full-matrix pass:

| Story | Mode | Rule | Nodes |
|---|---|---|---:|
| `shell-workbenchshell--drawer-closed` | light, dark | `scrollable-region-focusable` | 1 |
| `shell-workbenchshell--drawer-open` | light, dark | `scrollable-region-focusable` | 1 |
| `diagnostics--unknown-event` | light | `color-contrast` | 26 |

Neither appears in the composed-route gate, which is at zero for every state in
both themes, and neither is visible to the Vitest a11y run because jsdom cannot
compute colour or scroll geometry. They are observations about the story
harness's own render, offered as leads rather than as defects.

---

## 5. Which ruling branch was taken

WO-26 is decision-dependent: it inherits every Gate 2 ruling, and the card
requires the state index to record which branch was taken wherever a ruling had
alternatives. Rulings are [`DECISIONS.md`](../../DECISIONS.md) D-010 unless
noted.

| Ruling | Branch ratified | The rejected branch | Where it is visible in this pack |
|---|---|---|---|
| **9 — trace-spine blind spot** | **"the dimensioned static void is approved; the fallback is a status-only chip, never invented stages"** — the full spine, with the unobserved region drawn as a visible, static, dimensioned gap | A status-only chip with no spine. WO-15 would have dropped L→S, `CheckpointLedger` would not exist, and the 12–13 `TraceSpine/*` stories would have been about five. | **20 `Patterns/TraceSpine/*` stories and 10 `Patterns/CheckpointLedger/*` stories exist.** The count is the evidence: the fallback branch cannot produce them. |
| **10 — web-container healthcheck** | **probe `/api/healthz`, require HTTP 200, but do *not* fail on `status: "degraded"`** | Fail on `degraded` — which restarts the web container because the *backend* is unwell | **Owned by WO-30, still in flight on `feat/wo-30-proxy-hardening`. Nothing in this pack exercises it.** The e2e stack's `--wait` uses the base compose file's existing healthchecks, not the ruled-on one. |
| 2 — partial-report export exposure | Failure banner **above** a still-rendered briefing; export offered on failed runs with a non-empty `result` | Keep `ReportView`'s early return as designed behaviour — `ReportReader/PartialFromFailedRun` and one `ExportDisclosure` state would not exist | `patterns-reportreader--partial-from-failed-run`, `patterns-exportdisclosure--on-failed-run`, `patterns-exportdisclosure--refused-409`; §4 row 14; slice step 5 on all five projects |
| 4 — `error_type` vocabulary (RC-16) | Mapped sentence is primary; the raw string is never primary but is always one disclosure away | Raw string only — WO-12 would drop M→S | `patterns-statusbanner--mapped-error-types`, `--unmapped-error-type`, `--error-type-not-reported` |
| 6 — product lexicon (RC-12) | thread / run / briefing / checkpoint, with the three-register split (copy and component names take the lexicon; API-shaped identifiers keep the API's noun) | conversation / job / report throughout | `ThreadRail`, `ThreadRail/Drawer`, `Patterns/ThreadList` — while `/api/conversations` and the `['conversations', …]` query keys are unchanged |
| 8 — two-family plan editor | Sub-questions in the UI face, arXiv queries in mono, with an `aria-describedby` hint | One family for both columns | `patterns-planeditor--two-families` |
| 3 — deletion copy | "Delete thread" plus the honest second sentence about job-store retention | Different copy | `threadrail--delete-confirm` |
| 5 — `hitl_bypass` | Stays unavailable in the UI, absence enforced by test | Expose it | absence |
| 7 — typefaces | Three OFL families including RC-20's Literata Italic 400 — eight logical faces | Fewer families | [`fonts.md`](fonts.md) — 103,476 B of 122,880 B |
| 11 — bundle budgets | RC-01's seven-row table ratified | — | [`budget-report.md`](budget-report.md); two rows have since moved under the ratchet rule, both recorded in [`known-gaps.md` §5](known-gaps.md#5-every-budget-that-had-to-be-raised) |
| 12 — `job.plan = None` permanence | Accepted as a backend fact for this revamp (R-16) | Durable plan lineage now | `patterns-tracespine--succeeded-from-history` |
| 13 — review deadline | Not exposed; no countdown | A countdown | absence |
| 14 — MT-01 seams | S1 / S2 / S5 as specified; reserved names only, no files | Omit the seams | `shell-identityslot--empty` renders nothing; the `owner` slot is zero-height |
| 15 — `last-event-id` | Declared reserved in the proxy allowlist, no code change | Drop it | WO-30 |

D-012's rulings that this pack carries: **7** (WO-20's two unwired edges, which
that ruling requires be restated in `known-gaps.md` — they are, in
[§4](known-gaps.md#4-wo-20s-two-unwired-edges)); **3** (WO-22's nine
`PENDING_COMPOSITION` pins, all deleted by WO-20 — the register is now empty);
**4** (the `/` budget ratchet, "accessibility gate beats budget row"); and
**6** (the axe audit viewport pinned at the baseline's 1440 × 1200).

---

## 6. What this file does not establish

- **A story is not a route.** A story renders a component with fixed props and
  no network; it proves that component's markup and styling in three modes at
  five widths. That the assembled route reaches the same state is the
  Playwright sweep's claim ([`playwright/`](playwright/)), not this file's.
- **The axe column is a rule result, not a verdict.** Zero violations means
  those rules passed on that render, in Chrome, at those dimensions.
- **Forced colours is a fourth mode, and it is not part of criterion 2.** The
  theme toolbar offers `forced-colors` and 21 of the 34 story groups ship an explicit
  `ForcedColours` export, but criterion 2 names light, dark and reduced-motion,
  and that is what §7 measures. A full forced-colors pass on the trace spine
  and status marks is RC-17's, scheduled in WO-27.
- **Nothing here is an accessibility conformance claim.** See
  [`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim).

---

## 7. Criterion 2 — every story in three modes at five widths

Machine-readable: [`storybook/render-matrix.json`](storybook/render-matrix.json).

Every one of the **261** stories was loaded in real Chromium against the static
build in each of the three modes criterion 2 names — light, dark,
reduced-motion — at each of RC-14's five widths. **261 × 3 × 5 = 3,915
renders.**

A combination counts as rendered when Storybook sets `body.sb-show-main`, shows
no error overlay, and the page raises no uncaught error. That is Storybook's
own mount signal; waiting on `#storybook-root` having children would be wrong,
because several stories render nothing on purpose (a closed drawer, a closed
dialog) and 7–8 combinations per pass are legitimately empty.

| Mode | 320 | 412 | 768 | 1024 | 1440 |
|---|:-:|:-:|:-:|:-:|:-:|
| light | 261 mounted | 261 | 261 | 261 | 261 |
| dark | 261 | 261 | 261 | 261 | 261 |
| reduced-motion | 261 | 261 | 261 | 261 | 261 |

**3,915 / 3,915 mounted. 0 error overlays. 0 uncaught React errors.
Criterion 2 passes.**

### The three modes are three distinct renders

Asserting "it rendered" proves nothing if the mode never took effect, so the
decorators' own output was read back off `:root` on every render. 3,805 of the
3,915 combinations were sampled (the remainder are the by-design empty renders,
which have no root attributes to read):

| Mode | `data-theme` observed | `data-reduced-motion` observed |
|---|---|---|
| light | `light` × 1,160 · `dark` × 110 | absent × 1,210 · `reduce` × 60 |
| dark | `dark` × 1,160 · `light` × 110 | absent × 1,210 · `reduce` × 60 |
| reduced-motion | `light` × 1,155 · `dark` × 110 | **`reduce` × 1,265 — all of them** |

The motion decorator took effect in **100 %** of reduced-motion renders.

The 110-per-mode theme deviations are not decorator failures: they are exactly
the **22 story groups that pin their own `globals`** — 22 × 5 widths = 110. In
light mode the deviants are the `*--dark` stories, which pin `theme: "dark"`
deliberately. In dark mode they are the `*--forced-colours` stories, which pin
`theme: "forced-colors"`; the decorator then writes the underlying theme to
`data-theme` and signals the mode through `data-forced-colors="active"`
instead, exactly as `decorators/theme.tsx` documents. A story-level global
winning over a toolbar global is Storybook's defined precedence, and it is why
those stories exist.

The same arithmetic holds for motion: the 60 `reduce` renders inside light and
dark mode are the 12 story groups that pin `motion: "reduce"` themselves,
12 × 5 = 60.

### 48 play-function assertions that do not hold in every combination

Separate from rendering, and worth recording because **the merged gate cannot
see it**: the Vitest Storybook project runs each story once, in jsdom, at one
default viewport. This pack runs each story fifteen times in a real browser at
five real widths with real CSS transitions and no `waitFor` retry. On those
terms, 6 of 261 stories emit a play-function assertion error in some
combinations — 48 of 3,915. **Every one of them still mounted**; the error
comes from the story's own `play`, not from React.

They fall into two clean groups, and the pattern in each is the diagnosis.

**Group 1 — three `ThreadRail` overlay stories, light and dark only, all five
widths (30 combinations).**

| Story | Fails in | Passes in |
|---|---|---|
| `threadrail--delete-confirm` | light, dark — 320/412/768/1024/1440 | **reduced-motion, all five widths** |
| `threadrail--row-menu-open` | light, dark — all five | **reduced-motion, all five** |
| `threadrail-drawer--open` | light, dark — all five | **reduced-motion, all five** |

Each asserts `toBeVisible()` on an element inside a Radix overlay. That they
pass under `prefers-reduced-motion` at *every* width, and fail without it at
*every* width, is the tell: `web/app/tokens.css` collapses the duration tokens
to 1 ms under reduced motion, so the assertion lands after the enter transition
instead of during it. This is a timing race in the play function, not a defect
in the component. Owner: **WO-14**.

**Group 2 — three `Shell` stories, all three modes, 320 and 412 only (18
combinations).**

| Story | Fails in | What the play function looks for |
|---|---|---|
| `shell-errorboundary--workspace` | all modes — 320, 412 | `role="navigation"` named "Threads" |
| `shell-notfoundframework--default` | all modes — 320, 412 | `role="navigation"` named "Threads" |
| `shell-workbenchshell--rail-collapse-toggle` | all modes — 320, 412 | `role="button"` named "Collapse the rail" |

All three pass at 768, 1024 and 1440 and fail only below the `md` breakpoint —
because **below `md` the product deliberately does not render the rail at
all**. That is WO-08's mobile repair, and `web/e2e/reflow.spec.ts` asserts it
directly ("below md the rail is absent from the layout, not merely narrow":
`data-rail-mode="drawer"`, zero `nav` elements inside the shell). The play
functions encode a desktop-only assumption that nothing declares. The
components are behaving correctly; the stories do not say which viewport they
are meaningful at. Owners: **WO-08** (`WorkbenchShell`) and **WO-09**
(`ErrorBoundary`, `NotFoundFramework`).

Neither group is a rendering failure and neither is fixed here — this work
order produces evidence. Both are new information: they exist only because
criterion 2 asks for the five widths, and nothing in the merged tooling varies
the viewport.
