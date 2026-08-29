# Gate 3 evidence pack — addendum

**Dated 2026-08-29.** Verified against `origin/main` at
**`d3460a709ca2f33de1749625fbcd1cd0a55317c3`** (`d3460a7`), the merge of
[#111](https://github.com/kudratsingh/arxiv-research-agent/pull/111).

The merged pack ([#107](https://github.com/kudratsingh/arxiv-research-agent/pull/107),
`52ce042`) reported **eight of ten criteria passing and two failing**:
criterion 1 (five Storybook coverage rows missing) and criterion 7 (three
mobile §8.2 budgets breached). Both failures named the work orders that owned
the repair, and both repairs have since merged:

| Failure | Repair | Merged |
|---|---|---|
| Criterion 1 — `ThreadTimeline/*`, `ActiveRunPanel/*`, `EmptyState/*` have no story, so §4 rows **5** and **B** are uncovered | **[#108](https://github.com/kudratsingh/arxiv-research-agent/pull/108)** — 23 stories in three files, no product code changed | `8f0d738` |
| Criterion 7 — mobile CLS 0.134 vs ≤ 0.02, `/c/[id]` mobile LCP 3.24–3.70 s vs ≤ 2.50 s, `/c/[id]` mobile Performance 85–88 vs ≥ 95 | **[#111](https://github.com/kudratsingh/arxiv-research-agent/pull/111)** — the shell disclosure moved to the CSS side, the composer field rendered in the loading frame, two supporting payload changes | `d3460a7` |

**This addendum re-verifies exactly those two criteria on current `main`. It
does not rewrite the pack.** Every other file in
[`docs/revamp/evidence/gate-3/`](.) is WO-26's evidence at `52ce042` and stays
exactly as it was — including
[`storybook-states.md` §3](storybook-states.md#3-the-criterion-1-failure),
[`lighthouse-diff.md` §4](lighthouse-diff.md#4-the-three-breaches) and
[`known-gaps.md` §0 items 8 and 13](known-gaps.md#0-the-headline-list), which
record the two failures as measured at that commit. History stays honest; this
file **supersedes** those verdicts rather than editing them.

**This addendum fixes nothing either.** Its whole diff is this file and
[`lighthouse/addendum/`](lighthouse/addendum/). No product code, test or CI
file was touched, and no measurement below comes from a modified tree.

---

## 0. The two verdicts

| # | Criterion | Pack verdict at `52ce042` | **Addendum verdict at `d3460a7`** |
|---|---|:-:|:-:|
| 1 | State index with **zero** uncovered rows across both blocker lists | ❌ FAIL — 2 §4 rows, 3 RC-10 modules | ✅ **PASS** — 0 uncovered rows on either list; 284/284 stories axe-clean |
| 7 | Four states × mobile + desktop + a 320 px audit against §8.2, plus the bfcache row | ❌ FAIL — 3 mobile budgets breached | ✅ **PASS** — every §8.2 budget holds on all ten runs, both form factors |

One deviation is recorded rather than folded into either verdict: **`/` on
desktop no longer passes the `bf-cache` audit.** It is WO-30's, not criterion
7's, and [§3](#3-the-bfcache-row-rc-18-stated-precisely) says why in full.

With these two, **all ten Gate 3 criteria now pass.** The coordinator ratifies
in [`DECISIONS.md`](../../DECISIONS.md); nothing in this file does.

---

## 1. Criterion 1 — zero uncovered rows, re-verified

### 1.1 What was run

```bash
cd web
npm ci
npm run build-storybook            # -> web/build/storybook (gitignored)
npx vitest run --project=storybook
```

Both on `d3460a7`, with no local modification (`git status` clean).

| Measurement | Pack, `52ce042` | **Now, `d3460a7`** |
|---|---:|---:|
| Story files | 34 | **37** |
| Story groups in the built `index.json` | 34 | **37** |
| Stories | 261 | **284** |
| `npx vitest run --project=storybook` | 261 passed | **284 passed, 0 failed** |

284 − 261 = **23**, which is exactly #108's story count. Nothing else in the
story corpus moved.

**"Passed" is the axe result, not a separate claim.**
`web/.storybook/preview.tsx` sets `a11y: { test: "error" }` with
`options.runOnly.type: "tag"` over the baseline tag set, and
`web/vitest.config.mts`'s `storybook` project compiles each story into a
component test that renders it and runs axe over the result. A violation fails
the story. So **284 passed = 284 stories axe-clean on the baseline rule set**,
on the same terms
[`storybook-states.md` §4](storybook-states.md#4-rc-10s-union-component-table)
used for its 261.

### 1.2 The 23 new stories, each mounting axe-clean

Re-run scoped to the three new files —
`npx vitest run --project=storybook components/features/ThreadTimeline.stories.tsx components/features/ActiveRunPanel.stories.tsx components/patterns/EmptyState.stories.tsx` — **23 tests, 23 passed, 0 failed.** Story IDs are read
back from the built `storybook/index.json`, not transcribed from the PR body.

| Story ID | Group | What it covers | Mounted | axe |
|---|---|---|:-:|:-:|
| `features-threadtimeline--empty` | `Features/ThreadTimeline` | **§4 row 5**, "Empty thread" | ✅ | ✅ |
| `features-threadtimeline--no-active-run` | `Features/ThreadTimeline` | **§4 row B**, "No active job (`/c/[id]` without `?job=`)" | ✅ | ✅ |
| `features-threadtimeline--populated` | `Features/ThreadTimeline` | row 7, composed | ✅ | ✅ |
| `features-threadtimeline--not-found` | `Features/ThreadTimeline` | row 21, the inline 404 branch | ✅ | ✅ |
| `features-threadtimeline--load-error` | `Features/ThreadTimeline` | the retryable `GET /conversations/{id}` failure | ✅ | ✅ |
| `features-threadtimeline--empty-dark` | `Features/ThreadTimeline` | row 8, as an explicit render of row 5 | ✅ | ✅ |
| `features-threadtimeline--empty-forced-colours` | `Features/ThreadTimeline` | RC-17's fourth mode (not part of criterion 2) | ✅ | ✅ |
| `features-activerunpanel--no-active-run` | `Features/ActiveRunPanel` | row B, the panel's half | ✅ | ✅ |
| `features-activerunpanel--succeeded-from-history` | `Features/ActiveRunPanel` | rows 7/10 as the panel sees them | ✅ | ✅ |
| `features-activerunpanel--failed-from-history` | `Features/ActiveRunPanel` | row 15's spine half | ✅ | ✅ |
| `features-activerunpanel--cancelled` | `Features/ActiveRunPanel` | row 13 | ✅ | ✅ |
| `features-activerunpanel--unavailable` | `Features/ActiveRunPanel` | row 16, the expired run | ✅ | ✅ |
| `features-activerunpanel--legend-open` | `Features/ActiveRunPanel` | 03 §5.3's once-per-session legend | ✅ | ✅ |
| `features-activerunpanel--dark` | `Features/ActiveRunPanel` | row 8 | ✅ | ✅ |
| `features-activerunpanel--forced-colours` | `Features/ActiveRunPanel` | RC-17's fourth mode | ✅ | ✅ |
| `patterns-emptystate--default` | `Patterns/EmptyState` | row 3's shape | ✅ | ✅ |
| `patterns-emptystate--with-heading` | `Patterns/EmptyState` | the default `h3` | ✅ | ✅ |
| `patterns-emptystate--heading-level-two` | `Patterns/EmptyState` | row 5's `headingLevel: 2` configuration | ✅ | ✅ |
| `patterns-emptystate--heading-levels` | `Patterns/EmptyState` | the `h2 → h3 → h4` prop range | ✅ | ✅ |
| `patterns-emptystate--with-action` | `Patterns/EmptyState` | "one control at most" | ✅ | ✅ |
| `patterns-emptystate--in-the-rail` | `Patterns/EmptyState` | 260 px (`--layout-rail-width`) | ✅ | ✅ |
| `patterns-emptystate--dark` | `Patterns/EmptyState` | row 8 | ✅ | ✅ |
| `patterns-emptystate--forced-colours` | `Patterns/EmptyState` | RC-17's fourth mode | ✅ | ✅ |

**Group names.** #108 ships `Features/ThreadTimeline`, `Features/ActiveRunPanel`
and `Patterns/EmptyState` where §4 and RC-10 write `ThreadTimeline/*`,
`ActiveRunPanel/*` and `EmptyState/*`. That is the layer prefix
[`storybook-states.md` §2](storybook-states.md#2-4s-story-group-names-versus-the-shipped-story-ids)
already records for nine `Patterns/*` groups and for `Features/QueryComposer`
— "layer prefix only", expressly not a coverage gap — and each new file's
header names the row it serves, the way the two `Shell/NotFound*` files do.

### 1.3 The §4 state coverage map — superseding `storybook-states.md` §1

Same row format. Only **rows 5 and B** change; every other row is
`storybook-states.md`'s, re-verified against the built index rather than
copied — **all 41 story IDs this table names resolve in
`storybook/index.json` at `d3460a7`, none missing.** The `axe` column is the WO-26 state-level result from the
composed-route gate ([`axe/summary.tsv`](axe/summary.tsv)), unchanged by this
addendum; "deferred¹" carries `storybook-states.md` §1's footnote 1 verbatim
(it is about the axe column only, never about story coverage).

| # | State | Story ID | Story? | axe (light / dark) |
|---|---|---|:-:|:-:|
| 1 | Landing | `features-querycomposer--empty` | ✅ | 0 / 0 |
| 2 | Rail loading | `threadrail--loading` | ✅ | 0 / 0 |
| 3 | Rail empty | `threadrail--empty` | ✅ | 0 / 0 |
| 4 | Rail / backend error | `threadrail--error` · `features-querycomposer--upstream-down` | ✅ | 0 / 0 |
| **5** | **Empty thread** | **`features-threadtimeline--empty`** — was **✗ none** | ✅ **new** | 0 / 0 |
| 6 | Thread loading | `shell-skeleton--loading` (+ `--loaded`, `--narrow`) | ✅ | 0 / 0 |
| 7 | Populated briefing | `patterns-reportreader--long-with-headings` | ✅ | 0 / 0 |
| 8 | Dark mode | theme **axis** on every story — plus explicit dark stories in **25 of the 37** groups | ✅ | 0 / 0 |
| 9 | Plan review | `patterns-planeditor--default` | ✅ | 0 / 0 |
| 10 | Running | `patterns-tracespine--running-with-checkpoint` | ✅ | 0 / 0 |
| 11 | Reconnecting | `patterns-tracespine--reconnecting` | ✅ | deferred¹ |
| 12 | Rejoined after reload | `patterns-tracespine--running-no-checkpoint` | ✅ | deferred¹ |
| 13 | Cancelled | `patterns-tracespine--cancelled` | ✅ | 0 / 0 |
| 14 | Failed with partial briefing | `patterns-reportreader--partial-from-failed-run` | ✅ | 0 / 0 |
| 15 | Failed, no result | `patterns-tracespine--failed` · `patterns-statusbanner--severities` | ✅ | 0 / 0 |
| 16 | Expired run | `patterns-tracespine--unavailable` | ✅ | 0 / 0 |
| 17 | Submission error | `features-querycomposer--failed-with-orphan-thread` (+ the failure set) | ✅ | 0 / 0 |
| 18 | Rate limited (429) | `patterns-statusbanner--rate-limited` · `--rate-limited-retry-after` | ✅ | 0 / 0 |
| 19 | Unauthorized (401) | `patterns-statusbanner--unauthorized` | ✅ | 0 / 0 |
| 20 | Validation (422) | `patterns-planeditor--validation-422` · `features-querycomposer--validation` | ✅ | 0 / 0 |
| 21 | Thread not found (inline) | `shell-notfoundproduct--default` (branch: `features-threadtimeline--not-found`) | ✅ | 0 / 0 |
| 22 | Route not found (404) | `shell-notfoundframework--default` | ✅ | 0 / 0 |
| 23 | Export refused (409) | `patterns-exportdisclosure--unavailable-no-report` · `--refused-409` | ✅ | 0 / 0 |
| 24 | Delete confirmation | `threadrail--delete-confirm` | ✅ | deferred¹ |
| 25 | Stream recycled (`stream_timeout`) | `patterns-tracespine--stream-timeout` | ✅ | deferred¹ |
| A | Handoff `router.push('/c/{id}?job=')` | E2E only — slice step 1→2, all five projects | n/a² | deferred¹ |
| **B** | **No active job (`/c/[id]` without `?job=`)** | **`features-threadtimeline--no-active-run`** — was **✗ none** | ✅ **new** | 0 / 0 |
| C | Attached — status unknown | `patterns-tracespine--status-unknown` | ✅ | 0 / 0 |
| D | Review submitted, not settled | `patterns-planeditor--submitting` (+ `--submitting-cancel`, `--resolving`) | ✅ | deferred¹ |
| E | Review conflict (409) | `patterns-planeditor--conflict-409` | ✅ | deferred¹ |
| F | Proxy misconfigured 503 / upstream 502 | `patterns-statusbanner--proxy-misconfigured` · `--upstream-down` · `features-querycomposer--proxy-misconfigured` | ✅ | 0 / 0 |

² Row A is a **navigation**, not a resting layout: `storybook-states.md` §1
records it as e2e-only and criterion 1's blocker rule reads on states with a
story group named for them. It was not one of the pack's two uncovered rows and
its status is unchanged here.

**Uncovered §4 rows: 0.** (Pack: 2.)

### 1.4 RC-10's union component table — superseding `storybook-states.md` §4

Story counts read from the built `index.json`. The three previously-empty rows
are in bold.

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
| `patterns/` | **`EmptyState`** | **`Patterns/EmptyState`** — was **✗ none** | **8** | ✅ |
| `patterns/` | `StatusBanner` | `Patterns/StatusBanner` | 23 | ✅ |
| `patterns/` | `ConfirmDialog` | `ThreadRail` (`--delete-confirm`) + `Primitives/Dialog` | 1 + 7 | ✅ |
| `patterns/` | `ThemeToggle` | `Patterns/ThemeToggle` | 6 | ✅ |
| `features/` | `QueryComposer` | `Features/QueryComposer` | 16 | ✅ |
| `features/` | **`ActiveRunPanel`** | **`Features/ActiveRunPanel`** — was **✗ none** | **8** | ✅ |
| `features/` | **`ThreadTimeline`** | **`Features/ThreadTimeline`** — was **✗ none** | **7** | ✅ |
| `features/` | `ThreadRail` | `ThreadRail` | 8 | ✅ |
| `features/` | `ThreadDrawer` | `ThreadRail/Drawer` | 2 | ✅ |
| `app/` | `WorkbenchShell` | `Shell/WorkbenchShell` | 9 | ✅ |
| `app/` | `NotFound` | `Shell/NotFoundProduct` + `Shell/NotFoundFramework` | 2 + 2 | ✅ |
| `app/` | `RouteError` | `Shell/ErrorBoundary` | 3 | ✅ |

**32 of the 32 union modules have stories. Uncovered RC-10 modules: 0.**
(Pack: 29 of 32.)

Not in RC-10's union table but shipped anyway, and audited on the same terms,
unchanged from the pack: `Shell/Skeleton` (3), `Shell/SkipLinkFocused` (1),
`Shell/IdentitySlot` (1) and the three `Foundations/*` groups (12).

### 1.5 Verdict, and what it does not claim

> **Criterion 1 PASSES at `d3460a7`.** Zero uncovered rows on the §4 state map
> and zero on RC-10's union table — the two lists criterion 1's blocker rule
> reads on. 284 of 284 stories execute as component tests with the baseline
> axe rule set attached, and all 284 pass.

Three limits, so the verdict is not read wider than it is.

- **A story is still not a route** —
  [`storybook-states.md` §6](storybook-states.md#6-what-this-file-does-not-establish)
  governs unchanged. That the assembled `/c/[id]` reaches rows 5 and B remains
  the Playwright sweep's claim (the `thread-empty` state, `rows: ["5", "B"]`),
  which the pack already had green; the Storybook half is what was missing and
  is what is now closed.
- **This addendum did not re-run criterion 2.** The pack's 3,915-render matrix
  covers the 261 stories at `52ce042`; #108 reports 345/345 for its own 23 by
  a replication of the same method. Criterion 2 was already ✅ and is not
  re-litigated here.
- **No accessibility conformance is claimed**, by these 23 stories or any
  other — [`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim)
  stands in full.

`known-gaps.md` §0 item 8 ("Five Storybook coverage rows are missing") and §1
are **superseded by this section**; the coordinator records the closure in
`DECISIONS.md`.

---

## 2. Criterion 7 — the four states, mobile and desktop, plus 320 px

### 2.1 Provenance, repeated because it is the whole caveat

[`04` §8.2](../../04-ARCHITECTURE.md#82-lab-performance-targets):

> Baseline Lighthouse numbers are single local lab runs on the seeded stack,
> not field p75 (`baseline/README.md`). Budgets are therefore **regression
> guards against the same lab setup**, and field Core Web Vitals SLOs stay
> deferred until real traffic exists (`01-RESEARCH.md` performance section).

And the retained baseline's own disclosure, quoted verbatim from
[`baseline/README.md`](../../baseline/README.md):

> Mobile emulation uses Lighthouse's default throttled profile. Scores are one
> local lab run, not field p75 values.

**The same disclosure governs this rerun.** These are **single local lab runs
on one developer machine** — not field p75, not a median of repeats, and not
the same hardware the pack used. A few points of Performance is noise and is
read as noise below. Where a cell landed close to a ceiling it is reported
twice rather than once ([§2.5](#25-the-one-cell-that-came-close-reported-twice)),
so the reader sees the spread instead of the friendlier sample.

### 2.2 The method, identical to the pack's

```bash
# isolated Compose project AND isolated container names (arxiv-g3add-*),
# because the WO-21 overlay's container_names are global to the daemon
docker compose -p arxiv-g3add-e2e \
  -f docker-compose.yml \
  -f web/e2e/support/compose.e2e.yml \
  -f <a third overlay: arxiv-g3add-* names, ports 13260 / 18260> \
  up -d --build --wait
bash web/e2e/fixtures/seed.sh      # baseline-populated / baseline-empty

cd web
npx lighthouse "$URL" \
  --only-categories=performance,accessibility,best-practices \
  --output=json --output-path=<file> \
  --chrome-flags='--headless --no-sandbox --disable-gpu' --quiet \
  [--preset=desktop]                                                  # desktop
  [--screenEmulation.width=320 --screenEmulation.height=568 \
   --screenEmulation.deviceScaleFactor=2 --screenEmulation.mobile]    # 320 px
```

The third overlay is **not committed**: this addendum's diff is allowed to
touch only this file and `lighthouse/addendum/`, so it lives outside the
repository. It changes nothing but the four `container_name`s and the two
published ports.

**The two corpora are directly comparable — verified, not assumed.** Every one
of the ten `configSettings` blocks under [`lighthouse/addendum/`](lighthouse/addendum/)
is identical to its `.gate3.json` counterpart on `lighthouseVersion`,
`formFactor`, the whole `throttling` object, the whole `screenEmulation`
object, `emulatedUserAgent` and `onlyCategories`. Lighthouse **13.4.1** on both
sides. The only difference is the port in the URL (13270 → 13260).

Raw reports: [`lighthouse/addendum/*.addendum.json`](lighthouse/addendum/) —
eleven files, the ten cells plus one repeat sample. The pack's own ten
`lighthouse/*.gate3.json` are untouched, and so are WO-02's six.

### 2.3 Results against the §8.2 budgets

Every number below is re-derived from the committed JSON, on both sides — the
"pack" column is read out of `lighthouse/*.gate3.json`, not transcribed from
`lighthouse-diff.md`'s prose.

| State | Form factor | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---|---:|---:|---:|---:|---:|---:|:-:|
| Landing | mobile | **100** | **100** | **100** | 1.31 s | 52 ms | **0.000** | ✅ |
| Empty thread | mobile | **100** | **100** | **100** | 1.41 s | 58 ms | **0.000** | ✅ |
| Populated report | mobile | **100** | **100** | **100** | 1.42 s | 56 ms | **0.000** | ✅ |
| Plan review | mobile | **100** | **100** | **100** | 1.30 s | 63 ms | **0.000** | ✅ |
| Landing | desktop | **100** | **100** | **100** | 0.36 s | 0 ms | **0.000** | ❌³ |
| Empty thread | desktop | **100** | **100** | **100** | 0.39 s | 0 ms | **0.000** | ❌ |
| Populated report | desktop | 99 | **100** | **100** | 0.98 s | 0 ms | **0.000** | ❌ |
| Plan review | desktop | **100** | **100** | **100** | 0.50 s | 0 ms | 0.000128 | ❌ |
| Landing @ 320 | mobile | 98 | **100** | **100** | 2.41 s | 29 ms | **0.000** | ✅ |
| Landing @ 320 (2nd sample) | mobile | **100** | **100** | **100** | 1.37 s | 7 ms | **0.000** | ✅ |
| Populated report @ 320 | mobile | **100** | **100** | **100** | 1.37 s | 13 ms | **0.000** | ✅ |
| **Budget (mobile)** | | **≥ 95** | **100** | **≥ 100** | **≤ 2.50 s** | **≤ 150 ms** | **≤ 0.02** | — |
| **Budget (desktop)** | | **≥ 98** | **100** | **≥ 100** | **≤ 1.20 s** | **≤ 50 ms** | **≤ 0.02** | — |

³ New since the pack, by design, and **not** a criterion-7 result —
see [§3](#3-the-bfcache-row-rc-18-stated-precisely).

**Every §8.2 budget holds on all ten cells, on both form factors, with room.**

### 2.4 The three breaches, cell by cell

The pack's FAIL numbers → this addendum's measurement → the §8.2 budget.

**Breach 1 — mobile CLS (`lighthouse-diff.md` §4.1).**

| State | Pack (412 px) | **Now** | Budget |
|---|---:|---:|---:|
| Landing | 0.1335722986308643 ❌ | **0** | ≤ 0.02 |
| Empty thread | 0.1335722986308643 ❌ | **0** | ≤ 0.02 |
| Populated report | 0.1341815449412611 ❌ | **0** | ≤ 0.02 |
| Plan review | 0.1335722986308643 ❌ | **0** | ≤ 0.02 |
| Landing @ 320 | 0.08808396151557231 ❌ | **0** | ≤ 0.02 |
| Populated report @ 320 | 0.08808396151557231 ❌ | **0** | ≤ 0.02 |

Not "≤ 0.001" — **exactly zero**, and the `layout-shifts` audit says the same
thing from the other side: it is `notApplicable` with **zero items** on all
four mobile runs, both 320 px runs and three of the four desktop runs. The
`body > div.ew-shell > main#main` element the pack named on all four routes to
five decimal places does not appear in any addendum report.

The pack's own two negligible shifts behave as expected: the populated report's
0.0006 article shift did not recur in this sample (0 exactly, where #111
measured 0.00061 in one of its two), and **`plan-review-desktop`'s trace-spine
shift reproduces to the last digit — 0.0001280343227388144 in the pack and
0.0001280343227388144 here**, on `div.ew-thread__run > section.flex >
section#trace-spine > div.flex`. An identical seventeen-digit float across two
machines, two commits and two Chrome launches is the strongest single piece of
evidence that these two corpora are measuring the same thing.

**Breach 2 — `/c/[id]` mobile LCP (`lighthouse-diff.md` §4.2).**

| State | Baseline | Pack | **Now** | Budget |
|---|---:|---:|---:|---:|
| Landing | 1.96 s | 1.81 s | **1.31 s** | ≤ 2.50 s |
| Empty thread | 2.38 s | 3.24 s ❌ | **1.41 s** | ≤ 2.50 s |
| Populated report | 2.38 s | 3.62 s ❌ | **1.42 s** | ≤ 2.50 s |
| Plan review | 2.28 s | 3.70 s ❌ | **1.30 s** | ≤ 2.50 s |
| Populated report @ 320 | — | 3.61 s ❌ | **1.37 s** | ≤ 2.50 s |

All three `/c/[id]` states are now **below the Gate 1 baseline**, not merely
below the ceiling.

**Breach 3 — `/c/[id]` mobile Performance (`lighthouse-diff.md` §4.3).**

| State | Pack | **Now** | Budget |
|---|---:|---:|---:|
| Empty thread | 88 ❌ | **100** | ≥ 95 |
| Populated report | 85 ❌ | **100** | ≥ 95 |
| Plan review | 85 ❌ | **100** | ≥ 95 |
| Populated report @ 320 | 88 ❌ | **100** | ≥ 95 |

As the pack said, this was a consequence of the other two rather than an
independent finding, and it moves with them.

**Nothing regressed on desktop.** Performance 100 / 100 / 99 / 100 against
≥ 98 (the pack: 100 / 100 / 99 / 99), LCP 0.36 / 0.39 / 0.98 / 0.50 s against
≤ 1.20 s, TBT 0 ms everywhere, CLS 0.000 on three of four and 0.000128 on plan
review. **Accessibility 100 and Best Practices 100 on all eleven runs**, as in
the pack — no audit in either category scores 0 anywhere.

**One honest counter-movement: mobile TBT went up.** 34 → 52 ms on `/`,
20 → 58, 19 → 56 and 18 → 63 ms on the three `/c/[id]` states. Every figure is
inside the ≤ 150 ms ceiling by more than a factor of two and the worst is 63 ms
against a Gate 1 baseline worst of 56 ms, so no budget is at issue — but it is
a real direction of travel across four cells rather than one, and it is
recorded rather than left for someone else to notice. This addendum has one
sample per cell and does not attribute it.

### 2.5 The one cell that came close, reported twice

`Landing @ 320` measured **LCP 2.41 s against a 2.50 s ceiling** — inside by
90 ms, and *up* from the pack's 1.81 s on the same cell. Following #111's own
practice for a cell near a ceiling, the audit was taken a second time:
**LCP 1.37 s, Performance 100, TBT 7 ms, CLS 0.000**. Both samples are
committed ([`home-320.addendum.json`](lighthouse/addendum/home-320.addendum.json),
[`home-320.addendum.run2.json`](lighthouse/addendum/home-320.addendum.run2.json))
and both pass. The first was the opening audit of the batch against a
freshly-started container; the second is consistent with every other cell.
**Neither is discarded**, and the 2.41 s is the number the verdict is stated
against.

### 2.6 The merged regression guard, exercised

#111 added a `@device`-tagged block to `web/e2e/cls.spec.ts` that installs a
`layout-shift` `PerformanceObserver` through `addInitScript` (so it measures
the cold load), waits for `data-rail-mode="drawer"` to resolve, and asserts
total CLS ≤ 0.02 plus "nothing matching `main#main` or `ew-shell__` moved at
all". Run here against the same seeded stack:

```
npx playwright test e2e/cls.spec.ts --project="Pixel 7" --grep @device
  ✓ landing loads with no layout shift at this device's width
  ✓ thread-empty loads with no layout shift at this device's width
  ✓ thread-populated loads with no layout shift at this device's width
  ✓ plan-review loads with no layout shift at this device's width
  4 passed
```

Two independent instruments — Lighthouse's `layout-shifts` audit and
Chromium's raw `layout-shift` entries through Playwright — agree on the same
four states at the same 412 px width. Lighthouse is still not in CI until
**WO-29** ([`known-gaps.md` §0 item 4](known-gaps.md#0-the-headline-list)); this
spec is the gate until it is, and it is merged and green.

### 2.7 Verdict

> **Criterion 7 PASSES at `d3460a7`.** All four audited states, on mobile and
> desktop, plus both 320 px audits, are inside every §8.2 budget: mobile CLS
> **0.000** on every run (ceiling 0.02), mobile LCP **1.30–1.42 s** at 412 px
> and **1.37–2.41 s** at 320 px (ceiling 2.50 s), mobile Performance
> **98–100** (floor 95), desktop Performance **99–100** (floor 98), TBT
> **0–63 ms** (ceilings 50 ms desktop / 150 ms mobile), Accessibility and Best
> Practices **100 on all eleven runs**.

`known-gaps.md` §0 item 13 and §2c ("Three §8.2 mobile performance budgets are
breached") are **superseded by this section**.

---

## 3. The bfcache row (RC-18), stated precisely

RC-18's requirement targets **`/c/[id]`**, because an open `EventSource` made
that route bfcache-ineligible at baseline. `/` is not what the §8.2 / RC-18
gate reads on.

Every `bf-cache` cell, both corpora, read out of the JSON:

| Run | Baseline | Pack (`52ce042`) | **Addendum (`d3460a7`)** |
|---|:-:|:-:|:-:|
| Landing, mobile | ✅ pass | ✅ pass | ✅ pass |
| **Landing, desktop** | ✅ pass | ✅ pass | **❌ 2 reasons — new** |
| Empty thread, mobile | ❌ 2 reasons | ✅ pass | ✅ pass |
| Empty thread, desktop | — | ❌ 2 reasons | ❌ 2 reasons |
| Populated report, mobile | ❌ 2 reasons | ✅ pass | ✅ pass |
| Populated report, desktop | ❌ 2 reasons | ❌ 2 reasons | ❌ 2 reasons |
| Plan review, mobile | ❌ 2 reasons | ✅ pass | ✅ pass |
| Plan review, desktop | — | ❌ 2 reasons | ❌ 2 reasons |
| Landing @ 320 | — | ✅ pass | ✅ pass |
| Populated report @ 320 | — | ✅ pass | ✅ pass |

**`/c/[id]` is unchanged.** It passes on every mobile run and every 320 px run,
and fails on every desktop run — cell for cell what the pack measured and
recorded as a *partial* against RC-18 in
[`lighthouse-diff.md` §6](lighthouse-diff.md#6-the-bfcache-row-rc-18). This
addendum measured no movement there in either direction, so **RC-18's status is
exactly as `lighthouse-diff.md` §6 left it** — improved on the baseline, still
not the clean pass RC-18 asks for, still recorded as a partial. §6's two honest
notes stand with it: the measured failure reason is not the `EventSource` RC-18
predicted, and the mobile/desktop split is reported rather than explained.

**One cell moved, and it is `/` on desktop.**

- **What changed.** WO-30 ([#109](https://github.com/kudratsingh/arxiv-research-agent/pull/109),
  merged at `633b901`, after the pack was cut) added a per-request CSP nonce in
  the middleware. A per-request nonce cannot be statically rendered, so `/`
  became a dynamic route and its document now carries
  `Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate` —
  confirmed on the running stack with `curl -I`, alongside the
  `script-src 'self' 'nonce-…' 'strict-dynamic'` header that is the reason for
  it. `/c/[id]` was already dynamic and already carried the same header, which
  is why only `/` moved.
- **The measured reasons are the two `no-store` items**, verbatim from the
  audit and both classified *Not actionable* by Lighthouse: *"Pages whose main
  resource has cache-control:no-store cannot enter back/forward cache"* and
  *"Back/forward cache is disabled because some JavaScript network request
  received resource with Cache-Control: no-store header"* — the identical pair
  the pack already reported on the four desktop `/c/[id]` cells.
- **Attribution: WO-30, not criterion 7.** It is the priced consequence of an
  enforcing CSP with a per-request nonce, it was flagged in #111's own PR body
  rather than discovered here, and it is on the route the RC-18 gate does not
  read on. Criterion 7's bfcache row is `/c/[id]`, and `/c/[id]` did not move.
- **Status: a known deviation, accepted pending ratification.** Recorded here
  for the coordinator to rule on in `DECISIONS.md` — either as an accepted cost
  of WO-30's CSP, or, if `/`'s bfcache eligibility is judged worth keeping, as
  work for **WO-30** (whether the nonce can be scoped so `/` stays static) or
  **WO-29** (whether a nightly Lighthouse run should assert `bf-cache` per
  route at all). **It is not counted against criterion 7 in
  [§0](#0-the-two-verdicts).**

The other half of RC-18's evidence — the Playwright back-navigation assertion
that the same `job_id` is re-adopted with no second `POST /research` — is the
pack's, green on all five browser projects, and was not re-run here.

---

## 4. The cost boundary

**No paid model call was made at any point in producing this addendum.**

The stack ran with `ANTHROPIC_API_KEY=local-preview-disabled`, pinned on the
`app` container by `web/e2e/support/compose.e2e.yml` and re-pinned by the
third overlay so it cannot be lost to a merge order.
`docker exec arxiv-g3add-app printenv ANTHROPIC_API_KEY` returned
`local-preview-disabled`. The seed writes `baseline-*` rows straight into
Postgres and Redis and never calls `POST /research`; Lighthouse only navigates;
and the one Playwright block run here ([§2.6](#26-the-merged-regression-guard-exercised))
submits nothing — it observes a cold page load. The stack was torn down with
`docker compose -p arxiv-g3add-e2e -f … -f … -f … down` when the run finished.

---

## 5. What this addendum changes, and what ratifies it

**Changed:** two verdicts, from FAIL to PASS, on the evidence in this file and
under [`lighthouse/addendum/`](lighthouse/addendum/).

**Not changed:** every other file in this directory. The pack's
`README.md` verdict table, `storybook-states.md` §3, `lighthouse-diff.md` §4
and `known-gaps.md` items 8 and 13 still say what was true at `52ce042`, and
are meant to. Where this file supersedes one of them it says so by name —
[§1.5](#15-verdict-and-what-it-does-not-claim),
[§2.7](#27-verdict) and [§3](#3-the-bfcache-row-rc-18-stated-precisely).

**The repairs** are [#108](https://github.com/kudratsingh/arxiv-research-agent/pull/108)
(criterion 1, `8f0d738`) and [#111](https://github.com/kudratsingh/arxiv-research-agent/pull/111)
(criterion 7, `d3460a7`); **the coordinator ratifies Gate 3 in
[`DECISIONS.md`](../../DECISIONS.md)** — this addendum records evidence and
rules on nothing.
