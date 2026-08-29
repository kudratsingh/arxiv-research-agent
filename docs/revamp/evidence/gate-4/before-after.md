# The before/after quality report

[`DECISIONS.md` D-010](../../DECISIONS.md) makes this a Gate 4 requirement in
one line: *"Gate 4 requires the hardening/docs wave **and the before/after
quality report**."* This is that report.

**Before** is the retained Gate 1 baseline — [`docs/revamp/baseline/`](../../baseline/README.md),
captured 2026-08-28 from source commit `e6e8739`, before any revamp work order
existed. **After** is `origin/main` at **`80f6081`**, with every Gate 3 and
Gate 4 work order merged.

Three rules govern every number below.

1. **Re-derived, not transcribed.** Every figure was recomputed from the
   committed JSON or produced by a run reproduced for this pack. Where a
   number came from a run, §8 gives the command. Where two committed corpora
   disagree, both appear.
2. **A third column where the story needs one.** Several of the headline
   improvements are improvements over the *Gate 3 pack*, not over the Gate 1
   baseline — CLS most of all, which was **0 at baseline**, regressed to 0.134
   during the shell rebuild, and is 0 again. Collapsing that into a two-column
   "0.134 → 0.000" would sell a repair as progress. The three-column tables
   below do not.
3. **Lab, not field.** Every performance number on this page is a single local
   lab run against a seeded Compose stack on one machine. **None of it is field
   p75, and [§4.3](../../05-MIGRATION.md#43-what-gate-4-must-not-claim) forbids
   claiming otherwise.** [`README.md` §5](README.md#5-the-four-claims-this-pack-does-not-make)
   restates the prohibition in full.

---

## 0. The headline

| Measure | Gate 1 baseline | Gate 3 pack (`52ce042`) | **Now (`80f6081`)** | Source |
|---|---:|---:|---:|---|
| axe violation rule-entries | **36** | 0 | **0** | §1 |
| axe violation nodes | **77** | 0 | **0** | §1 |
| States failing `landmark-one-main` | **12 of 12** | 0 | **0 of 20** | §1 |
| States failing `region` | **12 of 12** | 0 | **0 of 20** | §1 |
| axe audits taken | 12 | 40 | **120** | §1 |
| Mobile CLS (worst route)† | 0.000 | **0.13418** | **0.00000** | §2 |
| `/c/[id]` mobile LCP† | 2.38 s | **3.62 s** | **1.42 s** | §2 |
| Mobile Performance (worst)† | 98 | **85** | **100** | §2 |
| Lighthouse Accessibility (worst)† | **94** | 100 | **100** | §2 |
| Lighthouse Best Practices† | **96** | 100 | **100** | §2 |
| Gated bundle ceilings | **none — no budget file** | 5 gated + 2 recorded | **5 gated + 2 recorded, six ratcheted down** | §3 |
| Dependency advisories, production tree | 0 of 119 | 0 | **0 of 166** | §4 |
| Vitest tests | **78** in 12 files | 2,970 in 136 | **3,080** in 136 | §5 |
| Playwright tests | **0** — no e2e tier | 208 | **419** across 5 projects | §5 |
| Storybook stories | **0** — no Storybook | 261 | **284**, each axe-clean | §5 |
| CI jobs on the PR path | **5** (frontend: **1**) | 8 (frontend: 4) | **8** (frontend: **4**) | §6 |
| Scheduled workflows | 1 (`nightly-eval`) | 1 | **2** (+ `nightly-lighthouse`) | §6 |

**† The five Lighthouse rows' "Now" column is measured at `d3460a7`, not
`80f6081`.** It is the Gate 3 addendum's corpus, and it is used here because it
is the most recent set taken with **Lighthouse 13.4.1** — the version the
baseline and the Gate 3 pack both used, so the three columns are comparable.
The Gate 4 `lhci` gate runs 12.6.1 and is reported separately in §2.3 as an
absolute measurement rather than a delta. §2.3 and **RR-09** say why. Every
other row in this table is measured at `80f6081`.

---

## 1. Accessibility — 36 violations to 0, and ten times the audit surface

### The baseline, re-derived

Parsed from the twelve committed reports in
[`baseline/axe/`](../../baseline/axe), not read out of any summary:

| Rule | Impact | Nodes | Reports affected |
|---|---|---:|---:|
| `region` | moderate | **48** | **12 of 12** |
| `landmark-one-main` | moderate | **12** | **12 of 12** |
| `color-contrast` | serious | 10 | 5 of 12 |
| `listitem` | serious | 3 | 3 of 12 |
| `aria-allowed-role` | minor | 3 | 3 of 12 |
| `page-has-heading-one` | moderate | 1 | 1 of 12 |
| **Total** | | **77 nodes across 36 rule-entries** | 6 distinct rules |

**The two landmark rules are 60 of the 77 nodes — 78 % of everything axe found
at Gate 1, and they failed on every single page.** Not one baseline state had a
`<main>`; not one had its content inside a landmark. That is the finding the
"12/12" figure names, and it is a claim about *rule × state coverage*, not
about node counts: `landmark-one-main` contributed exactly one node per report
(12), `region` between one and seven (48).

### Now

Parsed from the 120 committed reports in [`axe/`](axe):

| | Baseline | **Now** |
|---|---|---|
| Reports | 12 | **120** |
| Matrix | 12 states, 11 light + 1 dark, **1440 only** | **20 states × light/dark × 320/412/1440** |
| Violation rule-entries | 36 | **0** |
| Violation nodes | 77 | **0** |
| Distinct failing rules | 6 | **0** |
| Allowlist | *n/a — no gate existed* | **empty** — `web/e2e/axe-allowlist.json` is `[]`, 3 bytes |
| axe-core | 4.13.0 | **4.13.0** — identical on all 120 |
| Tag set | `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa, best-practice` | **identical on all 120** |

**The comparison is like for like by construction.** Same engine version, same
six tags, same 1440×1200 audit viewport (pinned deliberately — D-012 ruling 6
records that Playwright's default 1280×720 downgrades below-the-fold contrast
findings to `incomplete` and would have under-reported against the baseline).
The 320 and 412 legs are *additional* surface, not a different measurement.

Two things the zero does **not** absorb, both recorded by WO-27 rather than
buried:

- **34 `incomplete` rule results across 108 nodes**, all at 320 and 412 — 64
  `aria-hidden-focus` nodes on rail states and 44 `color-contrast` nodes on
  thread states at 320. An `incomplete` is axe declining to decide, not a pass.
  [`axe/README.md`](axe/README.md) resolves the `aria-hidden-focus` set by hand
  in [`manual/keyboard.md`](manual/keyboard.md) §4.
- **The matrix found a real serious defect and WO-27 fixed it** —
  `scrollable-region-focusable` on an empty thread's timeline at 320 in both
  themes, invisible at 1440 where the rule is inapplicable. That is the case
  for widening the matrix, made by the matrix.

Beside the route audits, **284 of 284 Storybook stories run axe as component
tests and all pass** (`a11y: { test: "error" }` in
`web/.storybook/preview.tsx`) — [`gate-3/ADDENDUM.md` §1.1](../gate-3/ADDENDUM.md#11-what-was-run).

### And what none of it establishes

**No accessibility conformance is claimed, at any level.** The manual tiers —
thirteen scripted keyboard walks, sixteen reflow samples, a motion pass and a
forced-colours pass — are in [`manual/`](manual/) and are one operator's
scripted observations, not a conformance audit. **The screen-reader pass has
not been executed** ([`manual/screen-reader.md`](manual/screen-reader.md) is a
prepared protocol with every transcription block deliberately empty). See
[`a11y-hardening.md` §4](a11y-hardening.md#4-what-this-pack-does-not-claim) and
**RR-02**.

---

## 2. Performance — the repair, and the improvement, told apart

All figures below are **Lighthouse 13.4.1**, the version the baseline and both
Gate 3 corpora used, so the three columns are directly comparable. The Gate 4
`lhci` gate runs **12.6.1** (the version `@lhci/cli@0.15.1` pins); §2.3 says
why that corpus is *not* used for a delta.

### 2.1 Mobile, the four audited states

| State | Metric | Gate 1 baseline | Gate 3 pack | **Gate 3 addendum (`d3460a7`)** | §8.2 budget |
|---|---|---:|---:|---:|---:|
| Landing | LCP | 1.96 s | 1.81 s | **1.31 s** | ≤ 2.50 s |
| | CLS | 0.000 | **0.13357** | **0.00000** | ≤ 0.02 |
| | Perf | 99 | 95 | **100** | ≥ 95 |
| Empty thread | LCP | 2.38 s | **3.24 s** | **1.41 s** | ≤ 2.50 s |
| | CLS | 0.000 | **0.13357** | **0.00000** | ≤ 0.02 |
| | Perf | 98 | **88** | **100** | ≥ 95 |
| Populated report | LCP | 2.38 s | **3.62 s** | **1.42 s** | ≤ 2.50 s |
| | CLS | 0.000 | **0.13418** | **0.00000** | ≤ 0.02 |
| | Perf | 98 | **85** | **100** | ≥ 95 |
| Plan review | LCP | 2.28 s | **3.70 s** | **1.30 s** | ≤ 2.50 s |
| | CLS | 0.000 | **0.13357** | **0.00000** | ≤ 0.02 |
| | Perf | 98 | **85** | **100** | ≥ 95 |

**Read the middle column.** CLS did not improve from 0.134 — it was **0 at
Gate 1**, broke to 0.134 in the shell rebuild (one shift of `main#main`,
identical to five decimal places on four structurally different routes, so it
was the shell rather than any content), and was repaired by PR
[#111](https://github.com/kudratsingh/arxiv-research-agent/pull/111) before
Gate 3 closed. The honest sentence is **"held at zero, after breaking it and
fixing it"** — not "0.134 → 0.000".

**LCP is a real improvement over the baseline, not just over the regression.**
All three `/c/[id]` states now land at 1.30–1.42 s against a Gate 1 baseline of
2.28–2.38 s: roughly 1 s faster than the page this revamp replaced, on a route
that carries strictly more surface.

### 2.2 Desktop, and the two categories that are not Performance

| Metric | Gate 1 baseline | **Now (`d3460a7`, 13.4.1)** | Budget |
|---|---:|---:|---:|
| Desktop Performance | 100 / 100 | **100 / 100 / 99 / 100** | ≥ 98 |
| Desktop LCP | 0.27 s, 0.51 s | **0.36 / 0.39 / 0.98 / 0.50 s** | ≤ 1.20 s |
| **Accessibility** (all runs) | **94–98** | **100 on all eleven runs** | = 100 |
| **Best Practices** (all runs) | **96 on every run** | **100 on all eleven runs** | = 100 |

Accessibility and Best Practices are the quietest rows here and among the most
substantive: **the baseline never scored 100 on either, on any run**, and the
plan-review state scored 94 on Accessibility — tracking exactly the extra
`color-contrast`, `listitem` and `aria-allowed-role` failures axe found in that
state (§1). Both categories are now pinned at 100 as `error`-level assertions
aggregated **pessimistically** (the worst of three runs), not by median —
[`lhci/README.md` §4.1](lhci/README.md).

### 2.3 The Gate 4 gate itself, and its version caveat

[`lhci/`](lhci/) is the standing gate, not a before/after column:

| Profile | Cells | Result |
|---|---:|---|
| mobile-412 | 4 | **PASS**, `lhci autorun` exit 0 |
| desktop-1350 | 4 | **PASS**, exit 0 (4 `warn`-level `bf-cache` rows recorded as failures — §2.4) |
| mobile-320 | 2 | **PASS**, exit 0 |
| | **80 assertions evaluated** | |

**It is deliberately not differenced against the columns above.**
`@lhci/cli@0.15.1` pins Lighthouse **12.6.1** exactly and offers no supported
way to run a different version; the baseline and both Gate 3 corpora are
**13.4.1**. A delta across a major Lighthouse version is a delta against a
moving scoring curve. [`lhci/README.md` §7](lhci/README.md) states this at
length and reports absolute measurements against the §8.2 ceilings instead.
It is carried as **RR-09**.

### 2.4 Two honest counter-movements

- **`/` lost desktop bfcache eligibility.** A per-request CSP nonce cannot live
  in a cached document, so `/` became dynamic and now serves
  `Cache-Control: … no-store`. Ruled on as **D-014 ruling 3**; RC-18's gate is
  `/c/[id]`, which is unchanged cell for cell. [`ci/csp.md` §5](ci/csp.md).
- **Mobile TBT rose.** 34 → 52 ms on `/`, and 20 → 58, 19 → 56, 18 → 63 ms on
  the three `/c/[id]` states between the Gate 3 pack and the addendum. Every
  figure is inside the ≤ 150 ms ceiling by more than a factor of two, and the
  worst (63 ms) is close to the Gate 1 baseline worst (56 ms) — but it is a
  direction of travel across four cells, it is recorded rather than left to be
  noticed, and neither corpus has the samples to attribute it. On CI runners
  the same metric behaves differently enough to have needed its own ruling —
  §7 and **RR-10**.

---

## 3. Bundles — from no gate at all to six ceilings ratcheted down

**At Gate 1 there was no budget file, no budget script, and no CI check.**
[`00-DISCOVERY.md`](../../00-DISCOVERY.md) records four measured numbers and
nothing that enforced them. The "before" column of this section is therefore
not "a larger bundle" — it is *an unmeasured bundle*.

### 3.1 Measured, then and now

Reproduced for this pack by `npm run budgets` on `80f6081` —
[`budget-report.md`](budget-report.md), generated 2026-08-29T17:24:21Z:

| Row | Gate 1 baseline | **Measured now** | Δ | Ceiling now | Headroom |
|---|---:|---:|---:|---:|---:|
| `/` first-load JS, excl. polyfill | 137,272 B | **158,880 B** | **+21,608** | 166,912 B | +8,032 |
| `/c/[id]` first-load JS, excl. polyfill | 184,745 B | **182,814 B** | **−1,931** | 192,512 B | +9,698 |
| Shared framework/runtime chunk | *never measured* | **131,642 B** | — | 139,264 B | +7,622 |
| All emitted CSS | 4,288 B¹ | **9,604 B** | +5,316 | 11,264 B | +1,660 |
| All self-hosted fonts (woff2) | **0 B** | **103,476 B** | +103,476 | 109,568 B | +6,092 |
| *Derived* `/c/[id]` cold-cache total | *never measured* | **295,894 B** | — | 313,344 B (reported, not gated) | +17,450 |

¹ The retained 4,288 B includes 21 bytes of gzip `FNAME` header that no server
sends; true payload is 4,267 B. [`budget-report.md`](budget-report.md) derives
the 21 bytes exactly rather than absorbing them.

**`/` grew and `/c/[id]` shrank, and both are the same fact.** The baseline `/`
was `QueryForm` — a textarea and a button, no counter, no billability
disclosure, no normalised failure, no guarded submission path. The redesigned
`/` carries the composer *plus* the job machine, because `useJobRun().submit`
is the only permitted route to `POST /research` and the endpoint has no
idempotency key (R-01, H6). Meanwhile `/c/[id]` came in **below its own Gate 1
figure** because WO-20's composition took the static `react-markdown` import
off the route. Across both routes the finished product is lighter than the
legacy one it replaced.

The fonts row is +103,476 B against a baseline of zero, and that is a
deliberate purchase, not a regression: the baseline shipped no self-hosted
typeface at all. Eight logical faces in five variable woff2 files —
[`gate-3/fonts.md`](../gate-3/fonts.md).

### 3.2 The six ceilings WO-31 ratcheted **down**

`git show cf61462 -- web/budgets.json`. Every one moved downward, in one PR,
under the [§8.4](../../04-ARCHITECTURE.md#84-enforcement--a-ci-check-not-an-aspiration)
ratchet rule:

| Row | From | **To** | Δ ceiling | Headroom over the measurement |
|---|---:|---:|---:|---:|
| `route-js-home` | 167,936 B | **166,912 B** | −1,024 | +5.1 % |
| `route-js-conversation` | 199,680 B | **192,512 B** | −7,168 | +5.3 % |
| `shared-framework-runtime` | 141,312 B | **139,264 B** | −2,048 | +5.8 % |
| `emitted-css` | 12,288 B | **11,264 B** | −1,024 | +18.5 % |
| `self-hosted-fonts` | 122,880 B | **109,568 B** | −13,312 | +5.9 % |
| `derived-total-first-load` *(reported only)* | 334,848 B | **313,344 B** | −21,504 | +5.9 % |

**−24,576 B of ceiling across the five gated rows.** WO-31's own framing is the
honest one and is worth preserving: *"the deletions shipped almost no bytes,
and that is the finding rather than a disappointment"* — WO-20 had already
stopped *composing* the nine legacy components and the bundler had already
tree-shaken them, so what WO-31 removed was dead **files**. The ratchet is not
banking a saving; it closes the gap between ceilings *projected from the legacy
surface* and the finished surface that now ships.

Two earlier movements went the other way and both are retained in
`budgets.json`'s `ratchet` array with their reasoning, because a smaller
ceiling does not supersede the argument for why the row sits above RC-01 at
all: `shared-framework-runtime` 122,880 → 141,312 B (WO-23 — React DOM plus the
Next app-router runtime already totalled 128,973 B before any application
code), and `route-js-home` 148,480 → 167,936 B (WO-20 — D-012 ruling 4,
*"accessibility gate beats budget row"*).

### 3.3 One measurement note this pack owes the reader

WO-31 recorded its ratchet measurements at `d3460a7`. **This pack's rebuild at
`80f6081` measures `emitted-css` at 9,604 B against WO-31's 9,507 B (+97 B) and
`/c/[id]` at 182,814 B against 182,776 B (+38 B)** — both above the "under
10 B" oscillation `budgets.json` documents for the JS rows. The cause is
merge order, not drift: **WO-27's accessibility fixes landed *after* WO-31's
ratchet** (`577b4c5` after `cf61462`) and added the `[hidden]` disclosure rule,
the `forced-colors` `svg[data-mark]` rule and the `ThemeToggle` forced-colours
block. Every ceiling still holds, with 1,660 B of CSS headroom remaining. It is
reported here rather than smoothed over, because a reader comparing this
report's numbers with PR #114's body will otherwise find a discrepancy and no
explanation.

---

## 4. Dependencies — a clean tree at both ends, and a real gate in the middle

| | Gate 1 baseline | **Now** |
|---|---:|---:|
| Dependencies | 669 (prod 119, dev 513) | **1,198** (prod 166, dev 994) |
| **Production-tree advisories** | **0** | **0** |
| Full-tree advisories | 0 | **13** — 10 high, 1 moderate, 2 low |
| Distinct upstream advisories | — | **6** |
| Audit gate in CI | **none** | `npm run audit:gate`, every PR |

Artifacts: [`npm-audit.json`](npm-audit.json) — byte-identical to
`npm audit --json`, so it is comparable line for line with
[`baseline/npm-audit.json`](../../baseline/npm-audit.json) — plus
[`npm-audit-prod.json`](npm-audit-prod.json) (`--omit=dev`, zero
vulnerabilities) and the gate's own output,
[`ci/audit-gate.log`](ci/audit-gate.log).

**"0 → 13" is not a regression, and the gate's shape is the reason.** D-012
ruling 1 splits it: the **production** tree is gated at zero with **no
exception mechanism at all** (`npm audit --audit-level=high --omit=dev`), and
that gate is green — 0 advisories across 166 production dependencies, up from
119. The **dev** tree is gated against `web/audit-exceptions.json`, which fails
on any unlisted advisory, on a stale entry, and on a *new* advisory against an
already-excepted package.

All ten excepted packages are dev-chain, and none ships to a browser or into
the container:

| Chain | Packages | Advisories | Accepted by |
|---|---:|---|---|
| `@storybook/nextjs-vite > vite-plugin-storybook-nextjs > image-size` | 3 | 1138808, 1138809 (`image-size` ICNS / JXL-HEIF infinite loops, **no fix published**) | WO-24, D-012 r1 |
| `@lhci/cli > {lighthouse > puppeteer-core > @puppeteer/browsers > extract-zip, tmp, uuid, inquirer > external-editor}` | 7 | 1139346, 1109537, 1120654, 1119441 | **WO-29** |

**Seven of the ten are new since Gate 3** — they arrived with `@lhci/cli`, the
tool WO-29 added to *close* a Gate 3 gap. That trade is worth naming: the
nightly Lighthouse gate cost seven dev-tree advisories in a package that runs
only on a runner. It is **RR-11**.

---

## 5. Tests — 78 to 3,499, and four tiers that did not exist

| Tier | Gate 1 baseline | **Now** |
|---|---|---|
| Vitest (unit + component + storybook) | **12 files, 78 tests** | **136 files, 3,080 tests** — 99 unit files / 2,796 tests, 37 story files / 284 stories |
| Coverage thresholds | **none — coverage not collected** | **97.61 / 93.37 / 88.10 / 98.57** enforced, [`coverage-summary.md`](coverage-summary.md) |
| Storybook | **none** | **284 stories**, each run as a component test with axe attached |
| Playwright | **none — `web/e2e/` did not exist** | **419 tests, 15 spec files, 5 projects** (303 on chromium, the PR path) |
| axe gate | **none** | 120-report matrix, empty allowlist, six non-suppressible rules |
| Visual regression | **none** | 48 committed PNGs, `darwin` only — **RR-01** |
| Contract drift | **none** | 4 checks, 129 assertions |
| CSP sweep | **none** | 20 states × 2 modes, [`ci/csp.md`](ci/csp.md) |

**3,080 + 419 = 3,499 automated tests, against 78.** The baseline had no e2e
tier, no Storybook, no MSW, no axe gate, no visual regression, no coverage
threshold, no Lighthouse CI and no size enforcement —
[`00-DISCOVERY.md`](../../00-DISCOVERY.md) says so as a single sentence, and
every one of those has a tier now except that visual regression is
platform-limited (RR-01) and Lighthouse is nightly rather than per-PR.

The vitest count is from an executed run reproduced for this pack (§8), not
from a collection listing: **136 passed / 3,080 passed, 0 failed**.

---

## 6. CI — 5 jobs to 8, and the frontend from 1 to 4

### Baseline, at `e6e8739`

`.github/workflows/` held exactly two files. `ci.yml` ran **5 jobs**:
`lint (ruff)`, `mypy (strict, src/)`, `pytest (unit + integration)`,
`docker build`, and **one** job named `web (typecheck + lint + test + build)` —
the entire frontend, four sequential steps. `eval-nightly.yml` ran 1 scheduled
job. CI built only the API image, never the web image, and never validated the
production Compose overlay.

### Now, at `80f6081`

`ci.yml` runs **8 jobs on every pull request and push** — measured on PR #118's
own checks, all green:

| Job | Frontend? | New since baseline? |
|---|:-:|:-:|
| `lint (ruff)` | | |
| `mypy (strict, src/)` | | |
| `pytest (unit + integration)` | | |
| `docker build` | | *extended* — now also validates `deploy/hetzner/compose.prod.yml` (C2) |
| `web (typecheck + lint + test + build)` | ✅ | *extended* — now also runs the audit gate, coverage thresholds and route budgets |
| **`web image smoke`** | ✅ | **new** — C1: the web image builds, boots, serves `/` and `/api/healthz`, and carries the CSP |
| **`web storybook (static build + story tests)`** | ✅ | **new** |
| **`web e2e (chromium + axe)`** | ✅ | **new** — 303 tests including the whole axe matrix |

Plus a second scheduled workflow that did not exist: **`nightly-lighthouse`**
(`nightly.yml`, one job, 05:10 UTC), and `ci.yml` itself now also runs on a
03:20 schedule with `web-e2e` in full-matrix mode across all five browser
projects.

**`docker build` and `web image smoke` close two named Gate 1 gaps.** The
baseline built the API image and nothing else; the production overlay was never
schema-checked and the web image was never booted. Both now run on every PR —
[`ci/compose-prod-config.log`](ci/compose-prod-config.log) and
[`ci/web-image.log`](ci/web-image.log).

---

## 7. The one threshold this programme moved upward, and why

Everything in §3 ratchets ceilings **down**. One moved up, in the last PR
before this pack, and it belongs in a before/after report rather than a
footnote.

The first two dispatched nightly Lighthouse runs on `main`
([33262680039](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33262680039)
and [33262721279](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33262721279),
52 seconds apart on the same commit) were each **69 of 70 assertions passing**,
failing only `total-blocking-time` on the plan-review mobile cell: medians
**180 ms** and **213.5 ms** against the ratified 150 ms, where the same cell
measures 10 ms locally.

The cause is mechanical, not luck. `throttlingMethod: "simulate"` means Lantern
*models* LCP, CLS and the category scores against a modelled network and CPU —
but **TBT is real main-thread blocking time on the host**, and the host is a
shared 2-core runner. Across both nightlies: 36 mobile TBT samples spanning
55–290 ms against 0–33 ms locally, while every other assertion on all ten cells
passed unchanged, and desktop TBT stayed at a 0 ms median in both runs because
that profile runs `cpuSlowdownMultiplier: 1`.

PR [#119](https://github.com/kudratsingh/arxiv-research-agent/pull/119) rules
on it by asserting TBT **twice**, and only TBT:

| Level | Mobile (412, 320) | Desktop (1350) |
|---|---:|---:|
| `error` — fails the run | 150 → **300 ms** | 50 → **100 ms** |
| `warn` — never fails | **150 ms** (the ratified §8.2 figure) | **50 ms** |

`error` is exactly 2× the ratified ceiling on both form factors. The assertion
inventory went 70 → 80; nothing was removed and no other metric was touched.
The headroom is stated against the *median*, which is what the gate reads:
worst observed median 214 ms against 300, i.e. **1.4×, not 1.67×** — and
`lighthouserc.json`'s own comment records the consequence: *"if a future
nightly fails here on plan-review mobile with no product change, the answer is
a dedicated runner or a narrower audit — not another doubling."*

**The ratified §8.2 number was demoted, not deleted.** A runner past 150 ms
still prints ⚠️ in the summary. This is a threshold moved to fit the
measuring instrument, and the honest reading is that **the nightly's TBT row
now gates the runner rather than the product** — **RR-10**.

### Nightly state, measured

The complete nightly history is three runs — the workflow is one day old and
all three were dispatched by hand.

| Run | Config | Result |
|---|---|---|
| [33262680039](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33262680039) | pre-#119 (70 assertions, TBT error @ 150) | **failure** — 69/70; plan-review mobile TBT median 180 ms |
| [33262721279](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33262721279) | pre-#119 | **failure** — 69/70; same cell, median 213.5 ms |
| [33265437903](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33265437903) | **post-#119** (80 assertions) | ✅ **SUCCESS** — **74 pass, 6 warn, 0 error**, all three profiles exit 0 |

**The gate is green on a real runner**, and the full log is committed as
[`ci/nightly-lighthouse.log`](ci/nightly-lighthouse.log). The six warnings are
exactly the two documented classes: four desktop `bf-cache` rows (the WO-30
consequence, D-014 ruling 3) and **two mobile TBT rows** — 158 ms on the
populated report and **265 ms on plan review**.

**Read the second one before reading the green tick.** The plan-review cell's
*worst single sample was 302 ms* — already past the 300 ms error ceiling #119
introduced — and it passed because the gate reads the median. On the same cell
a developer machine measures **10 ms**. The runner also produced one landing
LCP sample of **2,578 ms** against a 2,500 ms ceiling, passing on a median of
2,278 ms where the local measurement is 1.36 s. LCP has no warn tier, so that
one is visible only in the per-run spread.

This is a green run, and it is green with less margin than the word suggests.
**RR-10** carries it.

---

## 8. How every number here was produced

Committed artifacts were re-parsed with `node`/`jq`; nothing was transcribed
from prose. Three measurements were **reproduced** on `80f6081` for this pack:

```bash
cd web
npm ci                          # 1,055 packages
npm run budgets                 # -> budget-report.md      (§3)
npm run audit:gate              # -> npm-audit.json        (§4)
npm audit --omit=dev --json     # -> npm-audit-prod.json   (§4)
npm run test -- --coverage      # 136 files, 3,080 tests   (§5)
npx playwright test --list      # 419 tests, 15 files      (§5)
```

Two artifacts were **collected from CI** rather than re-run, because the check
*is* the CI job: [`ci/web-image.log`](ci/web-image.log) and Part 1 of
[`ci/compose-prod-config.log`](ci/compose-prod-config.log), both from run
[33264933325](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33264933325)
(PR #118, 8/8 green). Part 2 of the compose log is a local re-run without
`--quiet` so the resolved overlay is visible.

**No paid model call was made at any point.** No stack was started for this
report: the budget, audit and coverage runs need no backend, and the
Lighthouse and axe numbers are read out of corpora committed by WO-27, WO-29
and the Gate 3 pack. `docker compose config` validates a file and starts
nothing. See [`README.md` §6](README.md#6-the-cost-boundary).
