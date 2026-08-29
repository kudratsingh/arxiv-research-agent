# Known gaps — what Gate 3 does *not* establish

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criterion 9. Companion to [`README.md`](README.md).

This file exists because an evidence pack that lists only what it proves is a
sales document. Everything below is a real limit of this pack, stated with the
work order that closes it.

---

## 0. The headline list

1. **Manual keyboard and screen-reader passes are not done** — WO-27.
2. **Visual-regression baselines do not exist** — WO-28.
3. **CSP is not enforced** — WO-30, in flight on `feat/wo-30-proxy-hardening`.
4. **Lighthouse is not wired to a nightly** — WO-29.
5. **Two budgets were raised under the ratchet rule**, `/` first-load JS
   148,480 → 167,936 B (WO-20) and the shared framework/runtime chunk
   122,880 → 141,312 B (WO-23). Both justifications are in
   [§5](#5-every-budget-that-had-to-be-raised).
6. **Three high-severity dependency advisories are accepted by name**, all in
   the Storybook dev chain — [§6](#6-the-audit-gate-exceptions).
7. **This pack claims no accessibility conformance** — [§9](#9-what-this-pack-does-not-claim).
8. **Five Storybook coverage rows are missing** — §4 rows **5** and **B**, and
   the RC-10 union modules **`ThreadTimeline`**, **`ActiveRunPanel`** (WO-20)
   and **`EmptyState`** (WO-14). This is criterion 1's failure, reported rather
   than fixed — [§1](#1-the-criterion-1-failure).
9. **One merged e2e assertion is flaky** — [§2](#2-a-flaky-assertion-in-the-merged-suite).
10. **One product defect is pinned as an expected failure** — the theme
    hydration flash, [§3](#3-a-pinned-product-defect).
11. **Two edges of WO-20's route composition are deliberately unwired** —
    [§4](#4-wo-20s-two-unwired-edges), carried here by D-012 ruling 7.
12. **Nothing in CI runs the slice steps on the four non-chromium projects**,
    even though they pass there — [§2a](#2a-the-slice-steps-are-green-off-chromium-but-ci-never-runs-them-there).
13. **Three §8.2 mobile performance budgets are breached** — CLS 0.134 against
    0.02 on every mobile route, and LCP and Performance on `/c/[id]` —
    [§2c](#2c-the-mobile-cls-regression). Criterion 7 fails on them.
14. **Six stories carry play-function assertions that do not hold at every
    viewport or with animation enabled** — [§2d](#2d-play-functions-that-depend-on-viewport-or-motion).

---

## 1. The criterion-1 failure

WO-26 criterion 1 says a state with no story is a Gate 3 blocker, across two
lists: every [§4](../../06-WORK-ORDERS.md#4-state-coverage-map) state **and**
every module in RC-10's union component table.

**Three modules in RC-10's union table have no story, and two §4 rows therefore
have no story either.**

| Missing | RC-10 layer | Consequence |
|---|---|---|
| `ThreadTimeline` | `features/` | §4 row 5 (`ThreadTimeline/Empty`) and row B (`ThreadTimeline/NoActiveRun`) have no story |
| `ActiveRunPanel` | `features/` | no §4 row names it directly; it is an RC-10 union row |
| `EmptyState` | `patterns/` | no §4 row names it directly; it is an RC-10 union row |

How it slipped: RC-10's union table lists all three, but RC-10's discharge
sentence says the §5.3 story list "must be extended for exactly **four**
modules — `Diagnostics`, `SectionRail`, `CheckpointLedger`, and
`ThemeToggle`", and
[`04` §5.3](../../04-ARCHITECTURE.md#53-the-degraded-state-matrix-as-stories)'s
own group list names none of the three. So no card was ever given the
criterion: **WO-20's card has no story criterion at all**, and WO-14 c9's story
list does not include `EmptyState`. RC-10's arithmetic was short by three.

**This is not a fix WO-26 may make.** The owning work orders are **WO-20**
(`ThreadTimeline/*`, `ActiveRunPanel/*`) and **WO-14** (`EmptyState/*`).

What *is* established for those rows: §4 rows 5 and B are reachable and audited
in the running app. The e2e state `thread-empty` claims `rows: ["5", "B"]` and
is swept by the axe gate in light and dark and by the reflow sweep at 320 / 360
/ 412 — which is WO-20 criterion 7's evidence. The Storybook half is what is
missing, and only the Storybook half.

---

## 2. A flaky assertion in the merged suite

`web/e2e/stream.spec.ts:30` — *"an interrupted 200 stream is narrated, not
raced"* (`@stream`) — is intermittently red.

- Assertion: `expect(stream.opens()).toBe(1)` after waiting up to 15 s for the
  text *"connection interrupted; browser is retrying"*.
- Observed on this commit: **3 failures in 12 runs**, on chromium, webkit and
  firefox alike; received `2` where `1` was expected. The evidence run recorded
  in [`playwright/`](playwright/) is one of the green ones — which is exactly
  the problem, and why this is written down rather than left to whichever run a
  reader happens to look at.
- Cause is in the harness, not the product. `interruptStream()` in
  `web/e2e/support/intercept.ts` counts **every** open of
  `/api/research/{id}/stream`, and its own interface comment describes the
  counter as "how many times the **browser** has opened the stream for this
  job". The test's stated premise is that the browser's own `EventSource`
  reconnect is the *correct* behaviour and the UI must narrate rather than race
  it — but `toBe(1)` goes red the moment that reconnect's backoff elapses
  inside the 15 s wait. The assertion cannot distinguish the browser's retry
  from a client-initiated second open, which is the only thing it means to
  forbid.

**Owner: WO-21 criterion 4.** It is not evidence of a defect in WO-10's job
machine. Per-PR CI runs chromium only with `retries: 1`, so it will usually
retry green and report as flaky rather than failing the job — which is exactly
why it is written down here.

---

## 2a. The slice steps are green off chromium, but CI never runs them there

WO-26 criterion 3 asks for the five slice steps on all five browser projects.
They pass — **45 of 45**, measured and recorded in
[`playwright/`](playwright/) §2. But the merged
`web/playwright.config.ts` puts `@slice` in `CHROMIUM_ONLY`, matching **WO-21
criterion 6**'s narrower wording ("green end to end *on chromium*"), so no CI
job runs them on firefox, webkit, `Pixel 7` or `iPhone 15` — not even the
nightly full matrix, because `E2E_FULL_MATRIX` changes which *projects* are
installed and invoked, not which tests each project greps.

The evidence in this pack was produced by an evidence-only config that drops
the per-project grep filters for one run. That config is under `web/build/`,
which `.gitignore` excludes: **it is not part of this diff and it does not run
in CI.** Whether the merged config should be widened is **WO-21's** call.

## 2b. Two unit tests are load-sensitive

During this pack's production, `npm run test -- --coverage` was run once
concurrently with the Storybook render matrix and two tests failed on timeouts:
`components/app/SkipLinkFocused.stories.tsx > Focused` ("Test timed out in
5000ms") and
`tests/features/routeComposition.test.tsx > loads no Markdown pipeline at all
for a thread with no turns` (asserted while the route was still showing its
loading skeleton).

**Both pass in isolation and both pass in the uncontended run this pack
reports** — they are contention artifacts, not defects, and they are recorded
only so that a reader who sees them go red on a loaded CI runner knows they
have been seen before. Neither has a work order attached.

## 2c. The mobile CLS regression

**Cumulative Layout Shift on mobile is 0.134 against a §8.2 ceiling of 0.02.
The retained baseline measured 0.** It is the single most serious finding in
this pack.

One element accounts for essentially all of it, with an identical score to five
decimal places on all four mobile routes:

```
score 0.1335722986308643
body > div.ew-shell > main#main
<main id="main" aria-label="Workbench" class="ew-shell__main">
```

An identical score across four structurally different routes means the shift is
**the shell, not the content**. Desktop measures 0.000 on all four states, so
it is in the branch that runs below the `md` breakpoint — the one that resolves
`data-rail-mode` to `drawer` and drops the rail from the layout.

Consequential breaches on the same routes: LCP on `/c/[id]` rises from ~2.38 s
to 3.24–3.70 s against a 2.50 s ceiling, and the mobile Performance score falls
to 85–88 against ≥ 95. `/`'s LCP *improved* (1.96 → 1.81 s), and every desktop
budget holds.

**Owner: WO-08** for the shift itself; **WO-08 and WO-20** jointly for the
`/c/[id]` LCP regression, which this pack does not have the trace to attribute.

Three gates could each have caught this, and none was pointed at it:
`web/e2e/cls.spec.ts` is tagged `@cls` and therefore pinned to the chromium
**desktop** project, and it measures a live run rather than the cold load;
WO-02's CLS proof predates WO-08's shell; and **Lighthouse is not in CI at
all** — that is WO-29, and this is exactly the class of regression a nightly
LHCI run exists to catch. Full analysis in
[`lighthouse-diff.md` §4](lighthouse-diff.md#4-the-three-breaches).

## 2d. Play functions that depend on viewport or motion

Criterion 2's render matrix runs every story in a real browser at five widths.
On those terms 6 of 261 stories emit a play-function assertion error in some
combinations — 48 of 3,915. **Every one of them still mounted**; the error is
the story's own `play`, not React, and the merged Vitest gate cannot see any of
it because it runs once, in jsdom, at one viewport.

- Three `ThreadRail` overlay stories (`--delete-confirm`, `--row-menu-open`,
  `ThreadRail/Drawer --open`) assert `toBeVisible()` on a Radix overlay and
  fail in light and dark at **all five widths**, while passing under
  reduced-motion at all five — a timing race against the enter transition.
  Owner: **WO-14**.
- Three `Shell` stories (`ErrorBoundary/Workspace`,
  `NotFoundFramework/Default`, `WorkbenchShell/RailCollapseToggle`) look for the
  expanded rail, which the product deliberately does not render below `md`.
  They fail at **320 and 412 only**. The components are correct; the stories do
  not declare which viewport they are meaningful at. Owners: **WO-08** and
  **WO-09**.

Detail in
[`storybook-states.md` §7](storybook-states.md#7-criterion-2--every-story-in-three-modes-at-five-widths).

## 3. A pinned product defect

`web/e2e/theme.spec.ts:123` — *"a stored dark preference survives hydration"* —
is declared an expected failure:

```ts
test.fail(
  true,
  "Known defect: ThemeToggle's hydration-pass effect overwrites " +
    "data-theme with the OS resolution. See the comment above this test.",
);
```

Measured on the seeded stack: with `arxiv-agent.theme` stored as `"dark"`,
`<html>` is correctly `data-theme="dark"` before first paint and then flips to
`light` a few hundred milliseconds later while `data-theme-preference` stays
`"dark"`. The user picks dark, sees dark, then watches the page turn light.

Cause: `serverThemePreference()` returns `"system"`, so React's hydration render
uses that snapshot; the effect runs once with `preference === "system"`, passes
its `if (preference !== "system") return` guard, writes
`data-theme = resolve("system")` = `light`, and never restores it when the
client snapshot (`"dark"`) arrives.

The pre-paint script is not at fault and neither is the storage key. **WO-01
owns the theme foundation and WO-08 owns `ThemeToggle`.** The suite is green
while the bug exists and goes red the moment somebody fixes it — deleting the
`test.fail()` line is part of the fix.

---

## 4. WO-20's two unwired edges

Carried here because [`DECISIONS.md`](../../DECISIONS.md) D-012 ruling 7 says
so in as many words: *"To be restated in WO-26's `known-gaps.md`."*

- `LandingComposer`'s `createThread` mutation and its `unreachable` prop stay
  **unwired**, pending a shared QueryClient that would cost `/` roughly 8 KB.
- As a consequence, `/c/[id]` runs **two Query caches** whose only shared key is
  `conversations.detail`.

Both are accepted residuals, not oversights.

---

## 5. Every budget that had to be raised

Two of RC-01's seven ceilings have moved under the ratchet rule
([`04` §8.4](../../04-ARCHITECTURE.md#84-enforcement--a-ci-check-not-an-aspiration)).
The other five are unchanged. Both records live in `web/budgets.json`'s
`ratchet` array; both are summarised honestly below, including the alternative
that was rejected.

### 5.1 `/` first-load JS: 148,480 B → 167,936 B (WO-20, PR #101)

Measured on the merged branch: **158,899 B**. The new ceiling is +5.7 % over
that measurement — deliberately tighter than RC-01's ~8 % convention, because
the row is now measured against the finished surface rather than projected from
the legacy one.

Why the old ceiling could not hold: 148,480 B was +8.2 % over a measured
baseline of 137,272 B, and **that baseline is the legacy landing page** —
`QueryForm`, a textarea and a button, with no counter, no billability
disclosure, no normalised failure and no guarded submission path. The
redesigned `/` is the composer plus the job machine, and `useJobRun().submit`
is the only permitted route to `POST /research` (R-01, H6, MUST-KEEP 3): the
endpoint has no idempotency key, so the machine's submission token is what
stops a duplicate response buying a second run. `lib/job/` therefore cannot
leave the route.

**The rejected alternative was built and measured, not assumed.** Putting the
composer behind `React.lazy` — the way `ThreadRailBridge` already treats the
rail — lands `/` at **143,426 B**, inside the old ceiling. It is rejected
because Next resolves a lazy boundary's *fallback* into the prerendered HTML
(verified on that build: `index.html` carried the rail's
`data-thread-rail-state="loading"`, not its rows). `/` would therefore ship a
document with no `h1` and fail `page-has-heading-one` — which WO-22 criterion 2
gates at zero. The only fallback that keeps the `h1` is the composer itself,
whose sole refusal label is "Generating plan…", a sentence that would be false
on every first paint. D-012 ruling 4 records the trade in five words:
**"Accessibility gate beats budget row."**

Across the two routes the composition is **net negative**: 158,899 + 182,784 =
341,683 B against main's 146,447 + 199,425 = 345,872 B, because retiring
`ConversationThread` takes the static `react-markdown` import off `/c/[id]`.
The raise buys 19,456 B of ceiling on one route and gives back 16,641 B of
payload on the other.

### 5.2 Shared framework/runtime chunk: 122,880 B → 141,312 B (WO-23, PR #77)

Measured on untouched `main`: **130,865 B**. RC-01 set 120 KiB for this row
*without* a measured baseline — its own headroom column reads "—" — and the
ceiling was infeasible from day one: React DOM (63,370 B) plus the Next
app-router client runtime (65,603 B) already total 128,973 B before any
application code exists. Neither chunk is ours to cut. 141,312 B is 8.0 %
headroom over the measurement, matching the headroom the other RC-01 rows
embody.

### 5.3 What did *not* need raising

The font row held. WO-02 shipped all eight logical faces in five variable woff2
files totalling **103,476 B** against the ratified 122,880 B — 84.2 %, with
19,404 B of headroom — so RC-01's mitigation ladder stopped at its first rung.
See [`fonts.md`](fonts.md).

---

## 6. The audit-gate exceptions

`npm run audit:gate` splits the dependency gate. The **production** tree
(`npm audit --audit-level=high --omit=dev`) is gated at **zero** advisories and
consults no exception list at all. The **full** tree is gated against
`web/audit-exceptions.json`, which today holds **three entries carrying two
upstream advisories**:

| Package | npm advisory ids | Severity | Chain |
|---|---|---|---|
| `image-size` | 1138808, 1138809 | high | `@storybook/nextjs-vite > vite-plugin-storybook-nextjs > image-size` |
| `vite-plugin-storybook-nextjs` | 1138808, 1138809 | high | `@storybook/nextjs-vite > vite-plugin-storybook-nextjs` |
| `@storybook/nextjs-vite` | 1138808, 1138809 | high | `@storybook/nextjs-vite` |

Both advisories — [GHSA-w3rx-r6r6-pgpr](https://github.com/advisories/GHSA-w3rx-r6r6-pgpr)
and [GHSA-5p2g-fcmc-qvqq](https://github.com/advisories/GHSA-5p2g-fcmc-qvqq) —
are CWE-835 infinite-loop denial-of-service defects in `image-size`'s ICNS and
JXL/HEIF parsers, with **no published fix** (`fixAvailable: false`). The
package is reached only from `@storybook/nextjs-vite`, a devDependency: it
parses image files at Storybook build time so `next/image` can be mocked, and
the only images it is ever handed are the ones in this repository. Nothing that
ships to a browser or to the container reaches this code.

As the file itself puts it: *"the reported total of three is three packages
carrying two upstream GHSAs, not three distinct defects."* The gate fails on a
**stale** exception as well as an unlisted one, so the entries cannot outlive
their advisories quietly.

---

## 7. What the other Gate 4 work orders still owe

| Not done | Work order | State |
|---|---|---|
| Manual keyboard walk (skip link, rail, drawer, composer, plan arrays, approve/revise/cancel, diagnostics disclosure, report headings/links/tables, export, deletion dialog, error recovery) with observed focus order **and restoration** | WO-27 | not started |
| Screen-reader transcripts — VoiceOver + Safari (macOS and iOS), NVDA + Firefox | WO-27 | not started |
| Reflow at 200 % and 400 % zoom, phone landscape, and a very long unbroken report | WO-27 | not started |
| Forced-colors pass on the trace spine and status marks (RC-17) | WO-27 | not started |
| Full-matrix axe (every state × light/dark × 320/412/1440) | WO-27 | not started — this pack audits at **1440 only**, in light and dark |
| Visual-regression snapshot baselines | WO-28 | not started |
| Lighthouse CI (`web/lighthouserc.json`, `.github/workflows/nightly.yml`) with the §8.2 assertions encoded per state and form factor | WO-29 | not started |
| CSP — Report-Only then enforcing, per-request nonce carrying the pre-paint theme script | WO-30 | **in flight** on `feat/wo-30-proxy-hardening` |
| Redacted structured proxy logging; the `/api/healthz` container probe; `resolveUpstreamPrincipal` extraction (MT-01 seam S1) | WO-30 | in flight |
| Deleting the nine retired legacy modules, the `lib/api.ts` / `lib/types.ts` shims, and the WO-01 ESLint path allowlist; ratcheting coverage and budgets | WO-31 | not started — the modules are retired from the **render path** only and remain on disk |
| ADR 0055 (architecture confirmation) and ADR 0056 (design tokens); `docs/architecture.md`, `docs/testing.md`, `docs/development.md` refresh | WO-32 | not started |
| Gate 4 evidence pack and `residual-risks.md` | WO-33 | not started |

---

## 8. Specified but never scheduled

These are in
[`06` §7](../../06-WORK-ORDERS.md#7-not-scheduled) with their reasons. They are
repeated here so no reader mistakes their absence for an oversight:

- A partial-result marker **inside** the exported file, and export filenames
  following the product lexicon — both are upstream `Content-Disposition` /
  exporter changes and sit outside the frozen-backend boundary.
- Durable plan lineage on finished runs (`job.plan = None` on resume), and any
  review-deadline countdown (`api_hitl_timeout_sec` is server config, not an
  API field).
- Structured paper / evidence inspection; thread rename; search and filter;
  post-approval cancellation; page counts and totals; retry-this-run.
- Determinate progress, percentages, ETAs, "step 3 of 5", "currently running:
  X", "failed in stage X" — impossible under this contract and **actively
  prevented** by WO-12's forbidden-string gate.
- Accounts, login, avatars, sharing, per-user views — MT-01, a separate backend
  workstream with its own gated proposal. Only the seams are built. `/login`,
  `/settings` and `web/app/api/auth/[...]/route.ts` are reserved names with **no
  files created**.
- Field Core Web Vitals SLOs, RUM, session replay, error-tracking SaaS.
- Tailwind 4, TypeScript 7, Turbopack — each needs its own ADR.
- Thread-history virtualization, deferred until measured.
- A second Storybook story for every theme × viewport combination — deliberately
  not scheduled, because the global decorators cover the matrix without writing
  4× the stories.

---

## 9. What this pack does not claim

**This pack claims no accessibility conformance.**
[`05` §4.1](../../05-MIGRATION.md#41-gate-3--foundation--first-vertical-slice)
states the limit and this file restates it: *"Gate 3 explicitly does not claim
accessibility conformance. Automation cannot establish keyboard order, focus
restoration, announcement quality, or reflow usability — the same limit the
Gate 1 baseline recorded."*

Concretely, nothing in this pack establishes:

- that the keyboard order is sensible, or that focus is restored after a dialog,
  a drawer or a route change;
- that anything a screen reader announces is comprehensible, correctly ordered,
  or announced at the right moment;
- that a live region announces once rather than on every frame;
- that reflow at 320 px is *usable* — only that it does not scroll horizontally;
- that the product meets WCAG 2.1 AA, or any other conformance target.

Two further non-claims:

- **The Lighthouse numbers are single local lab runs on a seeded stack, not
  field p75 values.** They are regression guards against the same lab setup and
  nothing more. See [`lighthouse-diff.md`](lighthouse-diff.md), which repeats
  the baseline's provenance disclosure verbatim.
- **The axe results are a rule-by-rule comparison, not a verdict.** Zero
  violations of six named rules across forty audits means those forty renders
  pass those rules in Chrome at 1440×1200 in two themes. It does not mean the
  product is accessible.
