# Lighthouse rerun — the four baseline states, plus 320 px

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criterion 7. Raw reports: [`lighthouse/*.gate3.json`](lighthouse/). Baseline:
[`../../baseline/lighthouse/`](../../baseline/README.md).

> **Verdict: criterion 7 FAILS on three mobile budgets and passes on every
> desktop budget.** Cumulative Layout Shift on mobile is **0.134** against a
> ceiling of 0.02, from a single shift of `main#main`; LCP and Performance on
> `/c/[id]` regress past their ceilings. Accessibility and Best Practices —
> the two §8.2 targets the baseline *missed* — are now **100 everywhere**.
> Details in [§4](#4-the-three-breaches) and
> [§5](#5-what-improved). Nothing here is fixed by this work order.

---

## 1. Provenance — repeated verbatim, because it is the whole caveat

[`04` §8.2](../../04-ARCHITECTURE.md#82-lab-performance-targets) sets the frame:

> Baseline Lighthouse numbers are single local lab runs on the seeded stack,
> not field p75 (`baseline/README.md`). Budgets are therefore **regression
> guards against the same lab setup**, and field Core Web Vitals SLOs stay
> deferred until real traffic exists (`01-RESEARCH.md` performance section).

And the retained baseline's own disclosure, quoted verbatim from
[`baseline/README.md`](../../baseline/README.md):

> Mobile emulation uses Lighthouse's default throttled profile. Scores are one
> local lab run, not field p75 values.

> Provenance: the six successful audits below were captured before the
> committed seed fixture existed, against an ad-hoc local conversation
> (`/c/a018b0b0ed454f1e`) on the default compose port 3000; only the
> plan-review audit was recaptured against the seeded `baseline-populated`
> stack (port 13000) that the "Reproduce safely" commands rebuild. All runs are
> on the same source commit; re-running the documented commands reproduces the
> plan-review audit exactly and the remaining states from equivalent seeded
> data.

**The same disclosure governs this rerun**, with one difference in its favour
and one caveat against it.

- *In its favour:* every run below is against the **seeded** stack
  (`baseline-populated` / `baseline-empty`), so the ad-hoc-conversation half of
  the baseline's caveat does not apply here. Only the baseline's
  `plan-review-mobile` was captured that way, which means five of the eight
  before/after pairs compare a seeded "after" against an unseeded "before".
- *Against it:* these are still **single local lab runs on one developer
  machine** — not field p75, not a median of repeats, and not the same hardware
  the baseline used. A few points of Performance is noise and is read as noise
  below. What is *not* noise is a metric crossing a §8.2 ceiling, and one of
  the breaches below is a factor of about seven.

### The two runs are directly comparable

Both corpora are **Lighthouse 13.4.1** and the emulation settings are
byte-identical — verified, not assumed:

| Setting | Baseline | This rerun |
|---|---|---|
| `formFactor` | mobile | mobile |
| `screenEmulation` | 412 × 823 @ 1.75 | 412 × 823 @ 1.75 |
| `throttlingMethod` | `simulate` | `simulate` |
| `throttling` | rtt 150 ms, 1638.4 kbps, latency 562.5 ms, CPU × 4 | identical |
| `emulatedUserAgent` | moto g power (2022) | identical |

Desktop runs use `--preset=desktop` on both sides. The 320 px audits are new
and have no baseline counterpart.

## 2. Why the filenames carry `.gate3`

`docs/revamp/evidence/gate-3/lighthouse/` was created by **WO-02**, which
committed six runs there as its CLS proof — `home-mobile.json`,
`home-desktop.json`, `conversation-populated-{mobile,desktop}.json` and two
`-fontswap` variants (see [`fonts.md` §5](fonts.md)). Those are WO-02's
evidence and are not this work order's to overwrite, so every report added here
carries a `.gate3` infix.

## 3. Results against the §8.2 budgets

| State | Form factor | Perf | A11y | BP | LCP | TBT | CLS | bf-cache |
|---|---|---:|---:|---:|---:|---:|---:|:-:|
| Landing | mobile | 95 | **100** | **100** | 1.81 s | 34 ms | **0.134** ❌ | ✅ |
| Landing | desktop | 100 | **100** | **100** | 0.41 s | 0 ms | 0.000 | ✅ |
| Empty thread | mobile | **88** ❌ | **100** | **100** | **3.24 s** ❌ | 20 ms | **0.134** ❌ | ✅ |
| Empty thread | desktop | 100 | **100** | **100** | 0.75 s | 0 ms | 0.000 | ❌ |
| Populated report | mobile | **85** ❌ | **100** | **100** | **3.62 s** ❌ | 19 ms | **0.134** ❌ | ✅ |
| Populated report | desktop | 99 | **100** | **100** | 0.82 s | 0 ms | 0.000 | ❌ |
| Plan review | mobile | **85** ❌ | **100** | **100** | **3.70 s** ❌ | 18 ms | **0.134** ❌ | ✅ |
| Plan review | desktop | 99 | **100** | **100** | 0.83 s | 0 ms | 0.000 | ❌ |
| Landing @ 320 | mobile | 98 | **100** | **100** | 1.81 s | 21 ms | **0.088** ❌ | ✅ |
| Populated report @ 320 | mobile | **88** ❌ | **100** | **100** | **3.61 s** ❌ | 20 ms | **0.088** ❌ | ✅ |
| **Budget (mobile)** | | **≥ 95** | **100** | **≥ 100** | **≤ 2.50 s** | **≤ 150 ms** | **≤ 0.02** | — |
| **Budget (desktop)** | | **≥ 98** | **100** | **≥ 100** | **≤ 1.20 s** | **≤ 50 ms** | **≤ 0.02** | — |

Every **desktop** budget holds, with room. Every **TBT** figure holds, on both
form factors, by a wide margin. **Accessibility and Best Practices are 100 on
all ten runs.**

## 4. The three breaches

### 4.1 CLS on mobile — 0.134 against 0.02, and it is one element

This is the serious one. The baseline measured **CLS 0** on every state.

| State | Baseline CLS | Now (412 px) | Now (320 px) |
|---|---:|---:|---:|
| Landing | 0 | **0.134** | 0.088 |
| Empty thread | 0 | **0.134** | — |
| Populated report | 0 | **0.134** | 0.088 |
| Plan review | 0 | **0.134** | — |

The `layout-shifts` audit names a single culprit, and it is **the same element
with the same score to five decimal places on all four routes**:

```
score 0.1335722986308643
body > div.ew-shell > main#main
<main id="main" aria-label="Workbench" class="ew-shell__main">
```

An identical score across four structurally different routes means the shift is
**the shell, not the content**: `.ew-shell__main` moves once, after first
paint, before anything route-specific has rendered. The only other shift
recorded anywhere is 0.0006 on the report article in the populated thread, and
0.0001 on the trace spine in `plan-review-desktop` — both negligible.

It is mobile-only: desktop is 0.000 on all four states, so the shift is in the
branch of the shell that runs below the `md` breakpoint — the branch that
resolves `data-rail-mode` to `drawer` and drops the rail from the layout.

**Owner: WO-08**, which owns `WorkbenchShell` and 04 §8.3's mobile repair.

**Why nothing caught it.** Three gates could each have seen this and none of
them was pointed at it:
- `web/e2e/cls.spec.ts` asserts CLS 0.000 — but it is tagged `@cls`, which
  `playwright.config.ts` pins to the chromium **desktop** project, and it
  measures the shift *during a live run* (checkpoints arriving), not the cold
  load. On desktop, cold load, this pack measures 0.000 too. The spec is right;
  it is simply not looking here.
- WO-02's CLS proof ([`fonts.md` §5](fonts.md)) measured 0.000 with fonts
  swapping — on a commit before WO-08's shell existed.
- Lighthouse is not wired into CI at all. That is **WO-29**, which has not
  started, and this is precisely the class of regression a nightly LHCI run
  exists to catch.

### 4.2 LCP on `/c/[id]` — up ~1.3 s on mobile

| State | Baseline mobile LCP | Now | Δ |
|---|---:|---:|---:|
| Landing | 1.96 s | **1.81 s** | −0.15 s ✅ |
| Empty thread | 2.38 s | 3.24 s | **+0.86 s** ❌ |
| Populated report | 2.38 s | 3.62 s | **+1.23 s** ❌ |
| Plan review | 2.28 s | 3.70 s | **+1.42 s** ❌ |

`/` **improved**. Every `/c/[id]` state regressed past the 2.50 s ceiling. The
route's first-load JS actually went *down* (199,425 → 182,793 B — see
[`budget-report.md`](budget-report.md)), so payload alone does not explain it;
the shell's mobile layout settling late is a plausible contributor given §4.1,
but this pack does not have the trace to prove causation and does not claim it.
**Owners: WO-08 and WO-20**, to diagnose jointly.

### 4.3 Performance score on `/c/[id]` mobile — 85–88 against ≥ 95

A consequence of §4.1 and §4.2 rather than an independent finding: CLS and LCP
are the two heaviest terms in the score. Desktop is 99–100 against a ≥ 98
ceiling.

## 5. What improved

Both of §8.2's *reachable, not aspirational* targets were reached, and the
baseline's own diagnosis of them was correct.

| Target | Baseline worst | Now | §8.2 budget |
|---|---:|---:|---:|
| Accessibility | 94 (plan review) | **100** on all ten | 100 |
| Best Practices | 96 | **100** on all ten | ≥ 100 |

- The accessibility gap was `landmark-one-main` on all six real baseline runs,
  plus `listitem` on plan review. **Zero accessibility audits score 0 in any of
  the ten runs.**
- The Best Practices gap was `errors-in-console` on all six baseline runs (the
  `/favicon.ico` 404). **Zero best-practices audits score 0 in any of the ten
  runs.**
- TBT improved or held everywhere; the worst mobile figure is 34 ms against a
  150 ms ceiling, versus a baseline worst of 56 ms.

## 6. The bfcache row (RC-18)

RC-18 requires the `bf-cache` audit to pass on `/c/[id]`, because an open
`EventSource` made the route bfcache-ineligible at baseline.

| Run | Baseline | Now |
|---|:-:|:-:|
| Landing, mobile | ✅ pass | ✅ pass |
| Landing, desktop | ✅ pass | ✅ pass |
| Empty thread, mobile | ❌ 2 reasons | ✅ **pass** |
| Empty thread, desktop | — | ❌ 2 reasons |
| Populated report, mobile | ❌ 2 reasons | ✅ **pass** |
| Populated report, desktop | ❌ 2 reasons | ❌ 2 reasons |
| Plan review, mobile | ❌ 2 reasons | ✅ **pass** |
| Plan review, desktop | — | ❌ 2 reasons |
| Populated report @ 320 | — | ✅ **pass** |

**`/c/[id]` now passes bfcache on every mobile run and still fails on every
desktop run.** That is an improvement on the baseline, and it is *not* the
clean pass RC-18 asks for, so it is recorded as a partial.

Two honest notes:

1. **The measured failure reason is not the one RC-18 predicted.** RC-18
   attributes the baseline failure to an open `EventSource`. Lighthouse's two
   `bf-cache` items say something else, on both the baseline and this rerun:
   *"Pages whose main resource has cache-control:no-store cannot enter
   back/forward cache"* and *"Back/forward cache is disabled because some
   JavaScript network request received resource with Cache-Control: no-store
   header"*, both classified **Not actionable**. `/c/[id]` is a dynamic route,
   so `no-store` on the document is expected; the second item points at a
   `/api/*` response through the proxy. Response headers on the proxy are
   **WO-30's** surface, in flight on `feat/wo-30-proxy-hardening`.
2. **The mobile/desktop split is not explained here.** The same URL passes on
   mobile and fails on desktop in the same batch of runs. This pack reports the
   audit output rather than a theory about it.

The other half of RC-18's evidence — the Playwright back-navigation assertion
that the same `job_id` is re-adopted with no second `POST /research` — is
**green on all five browser projects**: see
[`playwright/README.md` §2](playwright/README.md#2-criterion-3--the-five-slice-steps-on-five-projects),
"step 2 — back navigation re-adopts the same job, with no second POST", and the
`slice step 2 — back navigation (RC-18 bfcache)` rows in the paid-path ledger,
all `expected=0`, all 0.

## 7. What these numbers are not

- **Not field data.** Single local lab runs, one machine, no repeats. See §1.
- **Not a CI gate.** Nothing in `.github/workflows/ci.yml` runs Lighthouse.
  Encoding these budgets per state and form factor is **WO-29**'s.
- **Not an accessibility conformance claim.** A Lighthouse Accessibility score
  of 100 means the automated subset passed. It establishes nothing about
  keyboard order, focus restoration or announcement quality — see
  [`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim).
