# Gate 4 — residual risks accepted at ship

What is **knowingly not covered** when this ships, why that was accepted, and
what would change the decision. [`05-MIGRATION.md`
§4.2](../../05-MIGRATION.md#42-gate-4--quality-and-documentation-before-ship)
requires this file and names its contents: "field CWV still unmeasured,
visual-regression coverage depth, browser matrix limits, and the MT-01
dependency for real multi-tenancy".

**Opened by [WO-28](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines)
with the one entry that work order owns, and completed by
[WO-33](../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks)**,
whose criterion 3 is that all four §4.2 risks are named with owners. WO-33
appended **RR-02 … RR-19** and did not edit RR-01. Entries are in `RR-NN` order
and each keeps the same seven fields, so the list can be read as a table
without reading the prose.

The four §4.2 risks are **RR-01** (visual-regression coverage depth),
**RR-03** (field CWV unmeasured), **RR-05** (browser matrix limits) and
**RR-06** (the MT-01 dependency). The other fifteen are risks this programme
found while doing the work, and they are here for the same reason: an evidence
pack that lists only its four required limits is still a sales document.

A residual risk is **not** a defect and **not** a gap that was missed. It is a
decision: something that could have been covered, was costed, and was
deliberately left uncovered — with the reasoning written down while the person
who made it still remembers why.

---

## Index

**§4.2**-named risks are marked ★. **Status** is the state of the *risk*, not
of the work: `accepted` means it ships this way on purpose; `open` means a
named follow-up exists and is not scheduled; `blocker` means Gate 4 does not
close on it.

| # | Risk | Owner | Status | Revisit trigger |
|---|---|---|---|---|
| ★ [RR-01](#rr-01--visual-regression-coverage-is-the-slice-not-the-matrix) | Visual-regression coverage is the slice, not the matrix | WO-28 | accepted | Per-tenant theming; a visual regression reaching a user in an uncovered state; literals leaking out of the token layer |
| [RR-02](#rr-02--the-screen-reader-pass-has-not-been-executed) | The screen-reader pass has not been executed | WO-27 | **blocker** | A human runs the protocol. Nothing else clears it |
| ★ [RR-03](#rr-03--field-core-web-vitals-are-unmeasured-every-number-is-a-lab-run) | Field Core Web Vitals are unmeasured — every number is a lab run | WO-29 / whoever owns deployment | accepted | Real traffic; any SLO or contractual CWV commitment |
| [RR-04](#rr-04--attachmode-stream-first-outlived-the-adapter-it-existed-for) | `attachMode: "stream-first"` outlived the adapter it existed for | WO-31 → the `lib/job/` owner | open | Any second product caller; any rework of `machine.ts`'s transition table |
| ★ [RR-05](#rr-05--browser-matrix-limits-one-engine-gates-most-of-what-is-gated) | Browser matrix limits — one engine gates most of what is gated | WO-21 | accepted | A user-visible Gecko or WebKit defect; a nightly matrix failure the PR path missed |
| ★ [RR-06](#rr-06--real-multi-tenancy-depends-on-mt-01-which-is-not-this-programme) | Real multi-tenancy depends on MT-01, which is not this programme | MT-01 (backend) — reserved for the user | accepted | The user approves MT-01's proposal, cost and rollout |
| [RR-07](#rr-07--there-is-no-linux-visual-baseline-so-the-visual-gate-is-inert-in-ci) | There is no Linux visual baseline, so the visual gate is inert in CI | WO-28 → the `e2e/visual.spec.ts` owner | open | Someone will review Linux pixel diffs; a regression escapes because the gate skipped |
| [RR-08](#rr-08--the--manifest-cross-check-is-gone-and-was-not-replaced) | The `/` manifest cross-check is gone, and was not replaced | WO-23 → WO-31 | open | The chunk-union derivation is changed; a budget row is disputed |
| [RR-09](#rr-09--the-nightly-gate-runs-a-lighthouse-a-major-version-behind-the-corpus) | The nightly gate runs a Lighthouse a major version behind the corpus | WO-29 | accepted | `@lhci/cli` bumps its pin — that run is the re-baselining moment |
| [RR-10](#rr-10--the-nightlys-tbt-row-now-gates-the-runner-not-the-product) | The nightly's TBT row now gates the runner, not the product | WO-29 | accepted (ruling pending ratification) | A nightly TBT failure with no product change; a dedicated runner |
| [RR-11](#rr-11--ten-dev-tree-dependency-advisories-are-accepted-by-name) | Ten dev-tree dependency advisories are accepted by name | WO-24 (3) + WO-29 (7) | accepted | A fix is published; the package reaches the production tree; a new advisory on an excepted package |
| [RR-12](#rr-12--style-src-attr-unsafe-inline-is-a-source-fix-deferred) | `style-src-attr 'unsafe-inline'` is a source fix deferred | WO-30 → `docs/security.md` follow-up | open | A second consumer of inline `style`; any CSP review |
| [RR-13](#rr-13--csrf-is-unaddressed-and-out-of-scope-pending-mt-01) | CSRF is unaddressed, and out of scope pending MT-01 | MT-01 | accepted | **The moment MT-01 introduces a session at seam S1 or S3** |
| [RR-14](#rr-14--last-event-ids-reservation-is-ruled-but-unpinned) | `last-event-id`'s reservation is ruled but unpinned | WO-30 / the proxy owner | open | A backend resume contract; anyone touching the header allowlist |
| [RR-15](#rr-15--the-merged-coverage-reports-function-denominator-is-inflated) | The merged coverage report's function denominator is inflated | the `vitest.config.mts` owner | open | A real functions regression hidden by the inflated floor |
| [RR-16](#rr-16--total-transferred-js-is-a-ceiling-nothing-measures) | `total-transferred-js` is a ceiling nothing measures | WO-21 | open | A lazy chunk grows; any dispute about real page weight |
| [RR-17](#rr-17--two-e2e-specs-are-sensitive-to-host-load) | Two e2e specs are sensitive to host load | WO-21 | accepted | A red `web-e2e` job that a `--failed` re-run turns green twice running |
| [RR-18](#rr-18--a-pinned-product-defect-the-theme-hydration-flash) | A pinned product defect: the theme-hydration flash | WO-01 + WO-08 | open | Anyone fixing it — the suite goes red until `test.fail()` is deleted |
| [RR-19](#rr-19--two-unwired-composer-edges-and-two-query-caches-on-cid) | Two unwired composer edges, and two Query caches on `/c/[id]` | WO-20 → the route owner | accepted | `/` gaining ~8 KB of headroom; a second cross-cache write appearing |

---

## RR-01 — Visual-regression coverage is the slice, not the matrix

| Field | |
|---|---|
| **Risk** | A visual regression in a state the snapshot suite does not cover ships unnoticed. |
| **Owner** | [WO-28](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines), and after ship whoever owns [`web/e2e/visual.spec.ts`](../../../../web/e2e/visual.spec.ts). |
| **Accepted at** | Gate 4, on the branch that introduced the tier. |
| **Covered** | Forty-eight committed PNGs: the five slice steps (`05` §2.1) plus every degraded state that has a retained Gate 1 screenshot — twelve renders × light/dark × 412/1440 px, Chromium on `darwin`. |
| **Not covered** | The other nine `states.ts` rows; the third audit width (320); every `DEFERRED_STATES` transition; Firefox and WebKit; forced-colours; reduced-motion as a *separate* axis; every Storybook story; and — until a `linux` set is generated and reviewed — the CI runner, where the sweep skips rather than gates. |
| **Why accepted** | Below. |
| **What would change it** | Below. |

### What is covered, exactly

The inventory is asserted rather than described:
`visual.spec.ts`'s "the inventory is what the criterion asks for" block fails if
the count moves, if a slice step is missing, if a degraded state is also
claimed as a slice step, if two renders would write one file, or if a named
retained baseline screenshot no longer exists under
[`docs/revamp/baseline/screenshots/`](../../baseline/screenshots).

| Half | States |
|---|---|
| The five slice steps | `landing`, `running`, `plan-review`, `reconnecting`, `thread-populated` |
| Degraded, with a retained Gate 1 screenshot | `cancelled`, `failed-partial`, `expired`, `submission-error-500`, `rail-error-upstream`, `thread-not-found-inline`, `route-not-found` |

### Why this depth was accepted

1. **The matrix is 20 states × 2 themes × 3 widths = 120 renders**, and WO-27's
   axe pack already walks exactly that. As *screenshots* those 120 PNGs are
   roughly 8 MB of committed binary that a single legitimate change to a shared
   token — one step on the space scale, one line-height — invalidates in one
   commit. The cost of a visual baseline is not taking it; it is re-taking it,
   and re-taking 120 files by hand is how a team learns to run
   `--update-snapshots` without looking at the diff. At that point the gate
   asserts nothing while still costing every reviewer a large binary diff.
   [WO-28's own risk note](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines)
   states the same conclusion: "a full-matrix visual baseline is maintenance
   debt disproportionate to a single-deployment product."
2. **This is a single-deployment product.** There is no matrix of customer
   themes, no white-labelling, no per-tenant CSS
   ([MT-01](../../DECISIONS.md), and see RR-0x when WO-33 writes it). One
   deployment renders one way, and a regression that escapes the slice is
   found by looking at the product rather than by a bisect across tenants.
3. **The uncovered states are not uncovered by every tier.** Each of the nine
   states without a snapshot is still swept by axe in both themes at three
   widths (WO-22, WO-27), measured for reflow and work-surface floor (WO-21),
   and rendered as a Storybook story with an a11y run (WO-06, `04` §5.3). What
   is missing for them is *pixel* comparison specifically — a class of
   regression that is real but narrow: spacing, colour and typography drift
   inside a component, which the token tests
   (`web/tests/tokens.test.ts` forbids literal colours outside
   `app/tokens.css`) already constrain from the other side.
4. **Chromium-only and `darwin`-only are the same argument, one level down.**
   A snapshot's artefact *is* the engine's rasterisation: text hinting,
   form-control metrics and scrollbar geometry differ between Chromium, Gecko
   and WebKit, and between macOS and Linux. Committing three engines × two
   platforms would be six sets of bytes that go stale independently and
   disagree for reasons that are never product defects. The platform is a
   directory segment (`e2e/__screenshots__/{platform}/`) rather than a silent
   assumption, so a second platform is *additive* and never a conflict; the
   engine limit is `@visual` in `CHROMIUM_ONLY` in
   [`web/playwright.config.ts`](../../../../web/playwright.config.ts).

### The tolerance, stated rather than buried

The comparison runs at Playwright's default per-pixel `threshold` (0.2) with
`maxDiffPixels: 200`. That is not a comfort margin: 45 of the 48 snapshots are
**byte-identical** between two forced regenerations, and the only render that
ever moved is `thread-populated` at 1440, by 124 (dark) / 131 (light) pixels,
bimodally, because the briefing's `position: sticky` `SectionRail` lays out at a
fractional x offset and is rasterised snapped or unsnapped depending on
compositor layer promotion. The reasoning, the measurements and the rejected
fixes are on `MAX_DIFF_PIXELS` in `visual.spec.ts`. For scale: a deliberate 2 px
shift moves **1,441 to 13,703** pixels, so the tolerance is between 7× and 68×
below the smallest regression the gate exists to catch.

### What would change this decision

Any one of these, and the depth should be revisited rather than defended:

- **The product stops being single-deployment.** Per-tenant theming (MT-01)
  turns "one deployment renders one way" into a false premise, and the visual
  tier would have to grow a theme axis before the first tenant ships.
- **A visual regression reaches a user in a state the suite does not cover.**
  One is an argument for adding that state; two in the same area is an argument
  for the full matrix.
- **The token layer stops being the only place values live.** The narrowness
  above leans on `web/tests/tokens.test.ts` — if literal colours or spacings
  start appearing in components, pixel comparison becomes the only check left.
- **CI gains a Linux visual leg.** Today it does not: the `web-e2e` job runs on
  a Linux runner with no `e2e/__screenshots__/linux/`, so the forty-eight
  comparisons **skip there**, loudly, naming the command that would fix it. The
  gate is real on a developer's macOS and inert on the runner, and that is a
  second residual limit inside this one. Closing it is additive — generate the
  Linux set, *look at the images*, commit them — and costs a second set of
  bytes; it is worth doing once someone will actually review Linux diffs. See
  [`web/e2e/README.md`](../../../../web/e2e/README.md), "For WO-24 (CI
  wiring)".

### Evidence

| What | Where |
|---|---|
| The suite | [`web/e2e/visual.spec.ts`](../../../../web/e2e/visual.spec.ts) |
| The committed set | `web/e2e/__screenshots__/darwin/` — 48 PNGs |
| Determinism measures and the regeneration rule | [`web/e2e/README.md`](../../../../web/e2e/README.md), "Visual regression (WO-28)" |
| Engine and platform pinning | [`web/playwright.config.ts`](../../../../web/playwright.config.ts) — `CHROMIUM_ONLY`, `snapshotPathTemplate` |
| The 2 px demonstration | WO-28's PR body |

---

## RR-02 — The screen-reader pass has not been executed

| Field | |
|---|---|
| **Risk** | The product ships with **no evidence of how it sounds.** Announcement quality, order and timing — the things a screen reader user actually experiences — are unmeasured. |
| **Owner** | [WO-27](../../06-WORK-ORDERS.md#wo-27--accessibility-hardening-and-manual-evidence) criterion 3, and after ship whoever schedules the operator. |
| **Accepted at** | **Not accepted.** This is the one entry in this file that is a **Gate 4 blocker**, not a residual. It is here so the list is complete, and marked so it cannot be mistaken for a decision. |
| **Covered** | The *protocol* is written and ready: [`manual/screen-reader.md`](manual/screen-reader.md) — three environments (VoiceOver + Safari on macOS and iOS, NVDA + Firefox), three scenarios (the plan-review decision, a reconnect announcement, a terminal outcome), exact steps, what a pass sounds like, a verdict table per scenario, and blank transcription blocks. Two structural questions WO-27 declined to rule on are carried into it for the operator: the two `<h1>` elements on a populated thread, and the plan editor's mixed `disabled` / `aria-disabled`. |
| **Not covered** | Every transcription block is empty. Nothing about screen readers is claimed anywhere in this pack. |
| **Why it is not done** | Below. |
| **What would change it** | A person runs the protocol. Nothing else. |

WO-27 was executed by an automated agent on macOS. **NVDA does not run on
macOS**, and a VoiceOver transcript cannot be synthesised: VoiceOver's speech is
produced by the platform from the accessibility tree *plus* its own verbosity,
punctuation and rotor state, and the tree is the **input** to a screen reader,
not its output. Writing out what a reader "would have said" would be a
fabrication in the shape of evidence.

**Gate 4 does not close on this criterion until a human executes it.**
[`a11y-hardening.md` §1](a11y-hardening.md#criterion-3-stated-plainly) says the
same thing at length, and [`README.md` §1](README.md) carries the ❌ into the
pack's own verdict table rather than rounding six-of-seven up to "the
accessibility work is done".

---

## RR-03 — Field Core Web Vitals are unmeasured; every number is a lab run

| Field | |
|---|---|
| **Risk** | Every performance figure this programme produced is a **single local lab run against a seeded stack**. Real users on real networks and real devices may experience something else entirely, and nothing here would detect it. |
| **Owner** | [WO-29](../../06-WORK-ORDERS.md#wo-29--lighthouse-ci-and-performance-hardening) for the lab gate; **field CWV has no owner because there is no field** — it belongs to whoever owns the deployment once real traffic exists. |
| **Accepted at** | Gate 2, in the ratified architecture: [`04` §8.2](../../04-ARCHITECTURE.md#82-lab-performance-targets) states that budgets are "regression guards against the same lab setup" and that field SLOs "stay deferred until real traffic exists". Re-affirmed at Gate 4 by [`05` §4.3](../../05-MIGRATION.md#43-what-gate-4-must-not-claim), which **forbids** claiming field CWV. |
| **Covered** | Ten §8.2-asserted cells on three profiles, three runs each, nightly ([`lhci/`](lhci/)); an 11-run Lighthouse 13.4.1 corpus at Gate 3 ([`gate-3/ADDENDUM.md`](../gate-3/ADDENDUM.md)); a merged Playwright `layout-shift` observer on four device-width states ([`web/e2e/cls.spec.ts`](../../../../web/e2e/cls.spec.ts)) that measures the **cold load** through `addInitScript`; and a build-time byte gate on every PR ([`budget-report.md`](budget-report.md)). |
| **Not covered** | p75 of anything. Real devices, real networks, real CPU contention, real cache states, real third-party conditions. Any percentile at all — every number is n=1 or the median of three, on one machine. |
| **Why accepted** | Below. |
| **What would change it** | Below. |

There is no field data because **there is no field**: the product is a
single-deployment research workbench behind a deployment gate, with no RUM, no
session replay and no error-tracking SaaS — all four are in
[`06` §7 "not scheduled"](../../06-WORK-ORDERS.md#7-not-scheduled) with reasons.
Instrumenting CWV before there is traffic would produce a dashboard of one
person's browser.

What the lab numbers *are* good for is the thing they are used for: **catching
a regression against the same setup.** That is not a theoretical benefit here —
it is exactly how the mobile CLS regression was found and fixed
([`before-after.md` §2.1](before-after.md)), and the fact that it took a Gate 3
evidence run rather than CI to find it is why WO-29 exists.

**What would change this decision.** Real traffic; a second deployment; any SLO
or contractual commitment expressed in CWV terms; or the first user report of
slowness the lab cannot reproduce. At that point the answer is field RUM, not a
tighter lab budget — and the caveat sentence carried by every artifact here
(*"single local lab runs on a seeded stack, not field p75"*) is what makes that
switch legible rather than embarrassing.

---

## RR-04 — `attachMode: "stream-first"` outlived the adapter it existed for

| Field | |
|---|---|
| **Risk** | A code path exists that **no product module may use**, kept alive by one test. A future caller could set it and quietly opt out of the GET-first attach contract ([`04` §4.3](../../04-ARCHITECTURE.md)), which is what makes a reload-safe rejoin correct. |
| **Owner** | [WO-31](../../06-WORK-ORDERS.md#wo-31--legacy-removal-and-ratchet) recorded it; after ship, whoever owns `web/lib/job/`. |
| **Accepted at** | Gate 4, in PR [#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114)'s Residuals section, and carried here by [`rc-03-equivalence.md`](rc-03-equivalence.md). |
| **Covered** | Every product caller uses the default. `web/lib/job/useJobStream.ts` documents the mode's status in capitals — *"WO-31 DELETED THAT ADAPTER, AND LEFT THIS MODE IN PLACE. **No product module sets it, and none may.**"* — and the sibling comments in `types.ts` and `machine.ts` were corrected in the same PR so none of them asserts something false. `web/tests/job/attach.test.ts` pins the GET-first order for the real path. |
| **Not covered** | **Nothing enforces the "none may".** There is no lint rule, no import-ratchet test and no type-level barrier: a new call site passing `attachMode: "stream-first"` would compile, build and pass CI. |
| **Why accepted** | Below. |
| **What would change it** | A second exerciser appearing; or any rework of `machine.ts`'s transition table, which is when the removal becomes cheap rather than risky. |

`useResearchStream.ts` is deleted, and the mode that existed for it is not.
That reads like an oversight and is not: **removing it is not a deletion but a
change to the reducer's event shape.** `AttachRequested.prefetch` would go, and
with it two branches of `machine.ts`'s total transition table plus five test
constructions. WO-31's licence is *removal*, and rewriting a state machine's
event vocabulary inside a removal PR is how a "safe" cleanup breaks a job
machine for no product gain.

Its one remaining exerciser is `web/tests/support/msw.test.tsx`, the harness
composition test, which needs the old request order to replay a recorded script
against an already-settled fixture. So the mode is not dead code by the coverage
tool's definition — which is precisely why an unenforced comment is the weakest
part of this entry.

---

## RR-05 — Browser matrix limits: one engine gates most of what is gated

| Field | |
|---|---|
| **Risk** | Almost every quality gate this programme added runs on **Chromium only**, so a Gecko- or WebKit-specific defect ships unnoticed. |
| **Owner** | [WO-21](../../06-WORK-ORDERS.md#wo-21--playwright-harness-seeded-stack-and-the-paid-path-interceptor), which owns `web/playwright.config.ts`'s tag routing. |
| **Accepted at** | Gate 3 (WO-21 criterion 6 reads "green end to end *on chromium*"), re-affirmed at Gate 4 as the axe, CSP, visual, motion and forced-colours tiers each landed chromium-only. |
| **Covered** | 419 Playwright tests exist across five projects — `chromium`, `firefox`, `webkit`, `Pixel 7`, `iPhone 15`. Firefox and WebKit carry 38 tests each; the two device projects 20 each. Gate 3 measured the five slice steps green on **all five projects, 45 of 45** ([`gate-3/playwright/README.md`](../gate-3/playwright/README.md)). WO-27 measured its `stream.spec.ts` reconnect fix 6/6 on firefox and webkit. |
| **Not covered** | **The per-PR CI job runs `--project=chromium` only — 303 of the 419.** `@a11y`, `@axe`, `@csp`, `@visual` and `@cls` are all in `CHROMIUM_ONLY`, so *none* of the accessibility, CSP, visual or layout-shift gates has ever run on Gecko or WebKit in CI. `@slice` is chromium-pinned too, so even the nightly full matrix does not run the slice steps on the other four projects — `E2E_FULL_MATRIX` changes which **projects** are installed, not which tests each project greps. |
| **Why accepted** | Below. |
| **What would change it** | A user-visible defect in Firefox or Safari; a nightly matrix failure the chromium path did not predict; or WebKit gaining `forcedColors` emulation, which would remove the strongest of the three technical reasons. |

Three reasons, written on the tag in `web/playwright.config.ts` rather than
inferred:

1. **axe comparability.** The whole point of the 120-report matrix is that it is
   the same engine, the same axe version and the same viewport as the retained
   baseline. A Gecko run would produce a different, incomparable corpus —
   useful, but not the thing the gate claims.
2. **`forcedColors` emulation exists only in Chromium.** RC-17's forced-colours
   pass is not portable, and two of WO-27's four defects were found by it.
3. **Sequential focus navigation genuinely differs between engines.** A keyboard
   walk asserted cross-engine would encode one engine's tab order as the
   specification.

The honest summary is that **the cross-engine evidence that exists is a
snapshot, not a gate**: it was measured once, by hand, at Gate 3, and nothing
re-measures it. That is a smaller claim than "five browser projects" suggests,
which is why this entry exists rather than pointing at the project list.

---

## RR-06 — Real multi-tenancy depends on MT-01, which is not this programme

| Field | |
|---|---|
| **Risk** | The product ships with **no user identity of any kind.** Everyone who reaches it is the same principal, sees the same threads, and can delete any of them. |
| **Owner** | **MT-01**, a separate backend workstream with its own gated proposal ([`docs/proposals/multi-tenancy.md`](../../../proposals/multi-tenancy.md)) and its own ADR. **Reserved for the user** — D-010 records that the cost-bearing follow-ons and MT-01 are not delegated. |
| **Accepted at** | **Gate 1**, [D-009](../../DECISIONS.md) answers 2 and 3: the shared-principal model is *not* accepted as the end state, and until MT-01 ships the revamp "must not fake login or per-user views". |
| **Covered** | The **seams**, and only the seams ([`04` §10](../../04-ARCHITECTURE.md#10-identity-ready-seams-for-mt-01), D-010 r14): S1, `resolveUpstreamPrincipal(request)`, extracted as the single place a principal is resolved; S2, the `/api/auth/*` path reserved by App Router precedence with **no files created**; S5, the reserved navigation slot. `web/tests/principal.test.ts` asserts the auth directory stays absent. |
| **Not covered** | Everything else: accounts, login, sessions, per-user scoping, sharing, avatars, ownership affordances. Also **CSRF** (RR-13), which is dormant only because there is no ambient browser credential. |
| **Why accepted** | Below. |
| **What would change it** | The user approving MT-01's proposal, cost and rollout. Nothing in this revamp advances it, and nothing in this revamp may. |

The frozen-backend rule is what makes this a decision rather than a gap: **an
unsupported concept is omitted, not simulated.** A login screen over a
single-principal proxy would be a lie told to every user, and a per-user view
that filters a shared store client-side would be a security claim the backend
cannot honour.

One thing a reader must not misread, and it has its own WO-32 criterion for that
reason: **the Caddy site-level HTTP basic auth at `deploy/hetzner/Caddyfile` is
a deployment gate, not a user account** (seam S7). The UI must never render that
prompt as a signed-in user. [`docs/architecture.md`](../../../architecture.md)
and [`docs/security.md`](../../../security.md) say so; without it written down,
the next reader mistakes the basic-auth prompt for the identity D-009 says does
not exist yet.

---

## RR-07 — There is no Linux visual baseline, so the visual gate is inert in CI

| Field | |
|---|---|
| **Risk** | The 48-PNG visual tier is **real on a developer's macOS and does nothing on the CI runner.** A visual regression merged from a machine that never ran the suite locally is caught by nobody. |
| **Owner** | [WO-28](../../06-WORK-ORDERS.md#wo-28--visual-regression-baselines), and after ship whoever owns [`web/e2e/visual.spec.ts`](../../../../web/e2e/visual.spec.ts). |
| **Accepted at** | Gate 4, on the branch that introduced the tier. Named inside RR-01 as *"a second residual limit inside this one"*; broken out here because it is a different risk with a different fix. |
| **Covered** | 48 committed PNGs under `e2e/__screenshots__/darwin/`, compared on every local `npm run e2e:visual`. The platform is a **directory segment** in `snapshotPathTemplate`, not a silent assumption, so a Linux set is purely additive and can never conflict with the macOS one. The skip is **loud**: it names the command that would fix it. |
| **Not covered** | The runner. `web-e2e` runs on `ubuntu-latest` with no `e2e/__screenshots__/linux/`, so all 48 comparisons **skip**. The gate has never failed a pull request, and on that runner it could not. |
| **Why accepted** | Below. |
| **What would change it** | Someone committing to actually review Linux pixel diffs; or a visual regression escaping into a release *because* the gate skipped. |

Generating the Linux set is not the hard part — it is one command in a
container. Reviewing it is. **A baseline nobody looks at is worse than no
baseline**, because the first legitimate token change produces dozens of red
comparisons and teaches the team to run `--update-snapshots` without opening the
images; from then on the gate asserts nothing while still costing every reviewer
a large binary diff. That is the same failure mode RR-01 argues against for the
full matrix, one level down.

So the sequencing is deliberate: **generate the Linux set when there is a person
who will review Linux diffs**, not before. Until then the tier is a local
pre-commit aid, and this entry exists so nobody reads a green `web-e2e` job as
"the screenshots matched".

---

## RR-08 — The `/` manifest cross-check is gone, and was not replaced

| Field | |
|---|---|
| **Risk** | The budget script's independent corroboration that its derived chunk union matches what Next actually ships **no longer runs for either route**. A derivation error in `route-budgets.mjs` would silently mis-measure the row it gates. |
| **Owner** | [WO-23](../../06-WORK-ORDERS.md#wo-23--route-budget-script-and-budgetsjson) owns the script; [WO-31](../../06-WORK-ORDERS.md#wo-31--legacy-removal-and-ratchet) was asked to restore equivalent corroboration "if cheap" and reported that it is not. |
| **Accepted at** | **[D-014](../../DECISIONS.md) ruling 3**, which accepts `/`'s dynamic rendering as inherent to the nonce CSP and records this as its consequence. |
| **Covered** | The report is now **honest about which case each route is in**, which was WO-31's cheap half: `/` reads *"skipped — server-rendered on demand — the per-request CSP nonce (WO-30) makes this route dynamic, so Next writes no HTML to compare against"* and `/c/[id]` reads *"skipped — dynamic route segment"*. Reproduced on this pack's own build, [`budget-report.md`](budget-report.md). The `/c/[id]` derivation is separately corroborated: it reproduces the retained Gate 1 figure of 184,745 B **to the byte**, and no gzip level other than 6 does. |
| **Not covered** | Any live cross-check, on either route. Next 16 also no longer emits `.next/app-build-manifest.json`, so the union is rebuilt from three other manifests — more derivation, less corroboration. |
| **Why accepted** | Below. |
| **What would change it** | Anyone changing the chunk-union derivation; or a disputed budget row, where "the script says so" stops being enough. |

Recovering the real script set for a dynamic route means booting `next start`
and fetching it — turning a hermetic, build-only script that runs in seconds
into one that needs a port and a live server on every PR. That is a real cost
against a real but bounded risk, and it was **weighed and declined**, not
overlooked.

What keeps the risk bounded is that the derivation is not unverified in general:
`/c/[id]` reproducing the retained baseline to the byte proves the method and
the compression settings, and `web/tests/budgets.test.ts` pins the script's
shape. What is lost is the *independent* check on the one route whose union the
other route does not share.

---

## RR-09 — The nightly gate runs a Lighthouse a major version behind the corpus

| Field | |
|---|---|
| **Risk** | The standing performance gate and every historical performance number in this programme were produced by **different major versions of Lighthouse**, so no before/after delta across them is sound. |
| **Owner** | [WO-29](../../06-WORK-ORDERS.md#wo-29--lighthouse-ci-and-performance-hardening). |
| **Accepted at** | Gate 4, with the difference stated at length rather than glossed — [`lhci/README.md` §7](lhci/README.md). |
| **Covered** | The gate is internally consistent: **Lighthouse 12.6.1** on all ten cells, all three profiles, three runs each. The corpora are consistent with each other too: baseline, Gate 3 pack and Gate 3 addendum are all **13.4.1**, and the addendum verified its `configSettings` match the pack's field for field. |
| **Not covered** | Any delta between the two. [`before-after.md` §2](before-after.md) therefore differences only within 13.4.1 and reports the 12.6.1 gate as an absolute measurement against §8.2. |
| **Why accepted** | Below. |
| **What would change it** | `@lhci/cli` bumping its Lighthouse pin — a dependency change with a lockfile diff, whose first nightly afterwards is the re-baselining moment. |

`@lhci/cli@0.15.1` pins Lighthouse 12.6.1 as an **exact** dependency and offers
no supported way to run a different one. The alternative was to keep driving
`npx lighthouse@latest` by hand, which is what Gate 3 did and exactly what a
nightly gate exists to stop.

The pin is also a **feature** for a regression guard: a budget file measured by
a floating Lighthouse compares against a moving scoring curve, and the failure
mode is a red nightly caused by a scoring change nobody shipped. Two things
bound the risk — both versions were run against the same stack on the same
machine in the same work order and land in the same metric range, and the
desktop `bf-cache` failure reproduces identically on both.

---

## RR-10 — The nightly's TBT row now gates the runner, not the product

| Field | |
|---|---|
| **Risk** | `total-blocking-time`'s **error** threshold is 2× the ratified [§8.2](../../04-ARCHITECTURE.md#82-lab-performance-targets) figure (mobile 300 ms, desktop 100 ms). A genuine product regression between the ratified ceiling and the doubled one now produces a **warning that fails nothing**. |
| **Owner** | [WO-29](../../06-WORK-ORDERS.md#wo-29--lighthouse-ci-and-performance-hardening). |
| **Accepted at** | Gate 4, PR [#119](https://github.com/kudratsingh/arxiv-research-agent/pull/119), under the D-010 delegation. **The ruling is not yet in [`DECISIONS.md`](../../DECISIONS.md)** — #119 deliberately did not touch that file, deferring it to the Gate 4 close. That is an open bookkeeping item for the coordinator; this pack records evidence and rules on nothing. |
| **Covered** | The ratified figure is **demoted, not deleted**: TBT is asserted twice per cell, `error` at 2× and `warn` at the §8.2 number, so a median past 150 ms still prints ⚠️ in the summary and appears in `assertion-results.json`. Only TBT was touched; the inventory went 70 → 80 with ten `warn` rows added and nothing removed. `web/tests/lighthouserc.test.ts` asserts that `error` is **exactly** 2× ratified, and that TBT is the only metric carrying a runner ceiling. |
| **Not covered** | The band between 150 and 300 ms on mobile (50–100 ms desktop). Nothing fails there. |
| **Why accepted** | Below. |
| **What would change it** | A nightly TBT failure on plan-review mobile **with no product change** — at which point the answer is a dedicated runner or a narrower audit, **not another doubling**. `lighthouserc.json`'s own comment says so in those words. |

The cause is mechanical rather than bad luck, and that is the whole argument.
`throttlingMethod: "simulate"` means Lantern *models* LCP, CLS and the category
scores against a modelled network and CPU — but **TBT is real main-thread
blocking time on the host machine**, and the host is a shared 2-core runner.
Across the two dispatched nightlies: 36 mobile TBT samples spanning
**55–290 ms** against **0–33 ms** on a developer machine, while every other
assertion on all ten cells passed unchanged in both runs. Desktop TBT held a
**0 ms median on every cell in both runs**, because that profile runs
`cpuSlowdownMultiplier: 1` and barely blocks at all.

**The ruling works, and the first green run is also the best argument for this
entry.** The post-#119 nightly
([33265437903](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33265437903),
log committed as [`ci/nightly-lighthouse.log`](ci/nightly-lighthouse.log))
passed: **74 assertions pass, 6 warn, 0 error**, all three profiles exit 0.
Two of the six warnings are mobile TBT — 158 ms on the populated report and
**265 ms on plan review** — so on the very first passing run the ratified
ceiling was exceeded on two of ten cells, invisibly to the gate.

Two honesty notes the pack owes the reader.

- **The headroom is thinner than the factor suggests.** The gate reads the
  median. On that green run the plan-review cell's **worst single sample was
  302 ms** — already past the 300 ms error ceiling — and it passed on a median
  of 264.5 ms. Against the same cell's 10 ms on a developer machine, the
  runner's variance is the dominant term, not the product's.
- **The same effect is invisible on LCP, which has no warn tier.** That green
  run's landing page produced LCP samples of 2,578 / 2,278 / 1,363 ms against a
  2,500 ms ceiling: one sample over, median under, nothing reported. LCP is
  Lantern-modelled and *should* be host-independent, so a sample that far out is
  itself a runner artifact. If a second metric starts behaving like TBT, the
  answer is the dedicated runner, not a second doubling.

---

## RR-11 — Ten dev-tree dependency advisories are accepted by name

| Field | |
|---|---|
| **Risk** | Ten packages in the development dependency tree carry six upstream advisories, four of them high-severity, and the gate is configured to pass anyway. |
| **Owner** | [WO-24](../../06-WORK-ORDERS.md#wo-24--ci-wiring-web-job-extensions-storybook-job-e2eaxe-job) for the three `image-size` entries; **[WO-29](../../06-WORK-ORDERS.md#wo-29--lighthouse-ci-and-performance-hardening) for the seven `@lhci/cli` entries.** |
| **Accepted at** | **[D-012](../../DECISIONS.md) ruling 1** (the gate's shape and the first three entries); the seven lhci entries were added under the same ruling by WO-29. |
| **Covered** | The **production** tree is gated at **zero high/critical with no exception mechanism at all** (`npm audit --audit-level=high --omit=dev`), and it is green: [`npm-audit-prod.json`](npm-audit-prod.json) reports 0 vulnerabilities across 166 production dependencies. The dev gate is not a mute button — `web/audit-exceptions.json` fails on an **unlisted** advisory, on a **stale** entry, and on a **new** advisory against an already-excepted package, because entries key on the advisory-id **set**, not on the package name. Output: [`ci/audit-gate.log`](ci/audit-gate.log). |
| **Not covered** | The advisories themselves. Two of the six (`image-size` 1138808 / 1138809) have **no published fix**. The other four are "fixable" only by `@lhci/cli@0.1.0` — a major downgrade npm proposes and which would remove the tool entirely. |
| **Why accepted** | Below. |
| **What would change it** | A fix being published; any of these packages reaching the production tree; or a new advisory against an excepted package, which the gate fails on by design. |

| Chain | Packages | Advisories | What it is |
|---|---:|---|---|
| `@storybook/nextjs-vite > vite-plugin-storybook-nextjs > image-size` | 3 | 1138808, 1138809 | CWE-835 infinite loops in the ICNS and JXL/HEIF parsers. Runs at Storybook build time so `next/image` can be mocked; the only images it is ever handed are this repository's. |
| `@lhci/cli > {lighthouse > puppeteer-core > @puppeteer/browsers > extract-zip, tmp, uuid, inquirer > external-editor}` | 7 | 1139346, 1120654, 1109537, 1119441 | symlink path traversal in `extract-zip`; path traversal and symlink write in `tmp`; a missing buffer bounds check in `uuid`. Runs on a CI runner against a localhost stack. |

**Seven of the ten are new since Gate 3, and they arrived with the tool that
closed a Gate 3 gap.** That trade deserves naming rather than burying: the
nightly Lighthouse gate cost seven dev-tree advisories. And the reported total of
ten is **ten packages carrying six upstream advisories, not ten distinct
defects** — `audit-exceptions.json` says so itself.

Nothing here ships. The production image contains neither Storybook nor
`@lhci/cli`, and the production audit that gates it consults no exception list
whatsoever.

---

## RR-12 — `style-src-attr 'unsafe-inline'` is a source fix deferred

| Field | |
|---|---|
| **Risk** | The shipped CSP is one directive weaker than C3's ratified policy. Inline `style` **attributes** are permitted anywhere in the document. |
| **Owner** | [WO-30](../../06-WORK-ORDERS.md#wo-30--proxy-hardening-csp-request-logging-healthcheck-mt-01-seams); the follow-up is recorded in [`docs/security.md`](../../../security.md). |
| **Accepted at** | **[D-014](../../DECISIONS.md) ruling 2.** |
| **Covered** | The widening is **as narrow as CSP3 allows**. `style-src 'self'` is intact and unmodified — `<style>` elements and stylesheet URLs remain same-origin only — and all three engines were **measured** honouring the separate `style-src-attr` fallback rather than assumed to. `script-src` carries no `'unsafe-inline'` and no `'unsafe-eval'`; `web/tests/csp.test.ts` asserts there is **exactly one** `'unsafe-inline'` in the entire policy and that the only addition to C3's list is this one directive. |
| **Not covered** | The source. `components/primitives/Skeleton.tsx` still writes caller-supplied geometry as inline `style` attributes, and any future component may do the same without any gate objecting. |
| **Why accepted** | Below. |
| **What would change it** | A second consumer of inline `style` appearing; or any review of the CSP, where a directive that exists for one component is the first thing to question. |

The Report-Only sweep produced **exactly three violations across the whole
twenty-state matrix, all `style-src-attr`, all from one component**. The
alternative was to fix the source across seven call sites — moving geometry to
CSS custom properties — inside a work order already carrying the nonce
middleware, the proxy logging, the healthcheck and the MT-01 seams.

The instructive comparison is the *other* violation the same sweep found: a
`script-src` `eval` from zod 4's JIT feature probe, which was fixed **at source**
(`z.config({ jitless: true })`) rather than by widening `script-src`. That is the
line WO-30 drew — a `script-src` weakening is not tradeable, a `style-src-attr`
one is — and it is a defensible line rather than a uniform one, which is exactly
why it is written down.

---

## RR-13 — CSRF is unaddressed, and out of scope pending MT-01

| Field | |
|---|---|
| **Risk** | The `/api` proxy performs **no origin check, no `Sec-Fetch-Site` check and no CSRF token validation** on its mutating routes. |
| **Owner** | **MT-01.** [`docs/proposals/multi-tenancy.md`](../../../proposals/multi-tenancy.md) carries it as threat **T2** against `web/app/api/[...path]/route.ts`. |
| **Accepted at** | Gate 4, as an explicit scope statement rather than an omission — [WO-30 criterion 10](../../06-WORK-ORDERS.md#wo-30--proxy-hardening-csp-request-logging-healthcheck-mt-01-seams) requires it be *named as unaddressed, not quietly implied*. |
| **Covered** | The statement, and a test that keeps it. [`docs/security.md`](../../../security.md) states plainly that CSRF is not addressed and is out of scope pending MT-01, and `web/tests/principal.test.ts` — *"criterion 10 — CSRF is named as unaddressed, not quietly implied"* — fails if that sentence disappears. [ADR 0055](../../../decisions/0055-frontend-architecture-confirmation.md) repeats it. |
| **Not covered** | CSRF. It is **dormant, not mitigated**. |
| **Why accepted** | Below. |
| **What would change it** | **The moment MT-01 introduces a session at seam S1 or S3.** Not "when MT-01 ships" — the day a cookie exists. |

Today there is **no ambient browser credential to forge**: the upstream key is
injected server-side by `resolveUpstreamPrincipal`, never reaches the browser,
and there is no cookie or session for a cross-site request to ride. A CSRF token
in that world guards nothing.

The reason this is a residual risk rather than a non-issue is the transition.
`docs/proposals/multi-tenancy.md` calls T2 *"the sharpest delta"*: the instant a
session cookie exists, every mutating proxy route becomes forgeable, and the
proxy's behaviour will not have changed. **"Proxy hardened" must never be read as
"CSRF considered"** — WO-30's card says exactly that, and it is repeated here
because a hardening work order's title is precisely the kind of thing a later
reader trusts too much.

---

## RR-14 — `last-event-id`'s reservation is ruled but unpinned

| Field | |
|---|---|
| **Risk** | The proxy allowlists a request header that nothing sets and the backend ignores. **Its "reserved" status is recorded only in `DECISIONS.md`** — nothing in the code says so, and nothing would go red if a client started setting it or a reader deleted the entry. |
| **Owner** | [WO-30](../../06-WORK-ORDERS.md#wo-30--proxy-hardening-csp-request-logging-healthcheck-mt-01-seams) / whoever owns `web/app/api/[...path]/route.ts`. |
| **Accepted at** | **[D-010](../../DECISIONS.md) ruling 15** — *"declared reserved in the proxy allowlist; no code change either way."* |
| **Covered** | The forwarding half is pinned (`web/tests/apiProxyRoute.test.ts` sends the header and asserts it reaches upstream). The absence half is provable indirectly: `web/tests/contract/sse.test.ts`'s reconnect-gap test states *"if a backlog or Last-Event-ID contract ever appears, this fails"*, and `web/tests/job/checkpoint.test.ts` pins that every stream open resets the checkpoint to unknown — the behaviour a resume contract would change. |
| **Not covered** | The reservation itself. No test is named for it, and `route.ts:50` carries no comment marking the entry as reserved. |
| **Why accepted** | Below. |
| **What would change it** | The backend gaining a resume contract (`format_sse` writing an `id:` line); or anyone editing the header allowlist. |

D-010 ruling 15's whole content is *no code change either way*, and that was the
right call: dropping the header from the allowlist narrows the contract for no
benefit, and adding a client that sets it would invent a resume protocol the
server does not implement. But "decide nothing" leaves the decision undefended,
and this is a three-line fix whenever someone is next in the file — a comment on
the constant, and one test named for the reservation. It is recorded here rather
than done, because [WO-33 fixes nothing](README.md).

[`contract-ambiguities.md`](contract-ambiguities.md) carries the same finding as
the one row of the twelve whose pin is weaker than its claim.

---

## RR-15 — The merged coverage report's function denominator is inflated

| Field | |
|---|---|
| **Risk** | The enforced `functions` floor is **88.1 %** while the other three columns sit between 93 and 99. The gap is a measurement artifact, so that floor is looser than it looks and a real functions regression could hide under it. |
| **Owner** | Whoever owns [`web/vitest.config.mts`](../../../../web/vitest.config.mts) — the ruling that created the hazard, [D-014](../../DECISIONS.md) ruling 1, calls the fix "the config owner's" and queues it. |
| **Accepted at** | Gate 3 close (D-014 r1, the 95.05 → 87.5 re-seed) and again at Gate 4, when WO-31 ratcheted the other three columns up and this one only 87.5 → 88.1. |
| **Covered** | The hazard is documented **where it happens** — a comment in `vitest.config.mts` that WO-31 kept verbatim — and restated in [`gate-3/coverage-summary.md`](../gate-3/coverage-summary.md) §3 and [`coverage-summary.md` §4](coverage-summary.md). Statements, branches and lines are unaffected, and all three are seeded at or just under their measurement. |
| **Not covered** | The de-duplication. The merged report still **concatenates** the two projects' function lists for every module both `unit` and `storybook` load, so those modules are counted twice in the denominator and once in the numerator. |
| **Why accepted** | Below. |
| **What would change it** | A functions regression that the inflated floor lets through; or any other reason to open the coverage config, at which point fixing it is cheap. |

The inflation is not uniform, which is why it cannot simply be subtracted: it
scales with how many modules the Storybook project pulls in, so it moved when
PR #108 added stories that loaded the route-composition import graph. That is
exactly what produced the 95.05 → 87.5 re-seed, and it is why seeding
`functions` at the luckier of two readings would put a red build on somebody
else's PR for no reason of theirs.

**88.21 % is a lower bound, not a quality statement.** The per-file rows make the
artifact visible: `lib/api` reads 56.16 % functions against 97.79 % statements,
which is not a module with half its functions untested.

---

## RR-16 — `total-transferred-js` is a ceiling nothing measures

| Field | |
|---|---|
| **Risk** | One of RC-01's seven budget rows — **240 KiB of total transferred JS on a settled report route, including lazy chunks** — has never been measured and is enforced by nobody. It is the only row that describes what a user actually downloads. |
| **Owner** | [WO-21](../../06-WORK-ORDERS.md#wo-21--playwright-harness-seeded-stack-and-the-paid-path-interceptor). `budgets.json` names it: *"WO-21 — a Playwright network-transfer assertion on a settled report route, in the per-PR chromium job."* **That assertion was never written.** |
| **Accepted at** | Gate 4, in PR [#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114)'s Residuals section, which flagged it as *"a candidate for WO-33's `residual-risks.md`"*. |
| **Covered** | The **omission is asserted rather than silent**, which is the part WO-31 did fix. `budget-report.md` prints the row under a heading reading *"Rows this script does NOT gate"* with the sentence *"NOT MEASURED HERE"*, and `web/tests/budgets.test.ts` pins that the row's `enforcement` is `"external"`, that it carries no measurement anywhere, and that it appears in no `ratchet` entry — so it cannot quietly acquire a fake number. The row's *components* are all gated: `/c/[id]` first-load JS at 192,512 B, CSS at 11,264 B, fonts at 109,568 B, with their derived sum reported at 295,894 B against 313,344 B. |
| **Not covered** | Lazy chunks. `PlanEditorFields` (RHF + Zod) and `ReportReader`'s Markdown pipeline are dynamically imported precisely so they leave the first-load rows — and nothing measures them when they arrive. |
| **Why accepted** | Below. |
| **What would change it** | A lazily-imported dependency growing; a third dynamic boundary being added; or any dispute about real page weight, where a first-load figure is not the answer. |

This row **cannot** come from the build manifests — that is why WO-23 marked it
external rather than skipping it — and the Playwright assertion that would
supply it needs a settled report route with every lazy chunk resolved, which the
e2e harness can produce but does not measure. It is the one row where the budget
system's design and its implementation disagree, and WO-31 could not ratchet it
because there was no measurement to ratchet to.

The honest consequence: **the tightest thing this programme can say about page
weight is a first-load figure.** Everything the dynamic boundaries were built to
defer is unmeasured — and RC-11's tight headroom was the reason for deferring it
in the first place.

---

## RR-17 — Two e2e specs are sensitive to host load

| Field | |
|---|---|
| **Risk** | Two Playwright specs fail on a contended machine and pass on an idle one. A reader who sees them red concludes there is a defect; a reader who has seen them red twice starts re-running the job on principle. |
| **Owner** | [WO-21](../../06-WORK-ORDERS.md#wo-21--playwright-harness-seeded-stack-and-the-paid-path-interceptor). |
| **Accepted at** | Gate 4, PR [#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114), which reproduced both on **unmodified `main`** before concluding they were not its own. |
| **Covered** | The reproduction method is the evidence: WO-31 detached onto unmodified `main` at `d3460a7`, rebuilt the image from it, and ran the same specs — **both failed there too**, and `main` additionally failed a third that the branch passed. CI settled it: `web e2e (chromium + axe)` green in 4m54s. Per-PR CI runs chromium with `retries: 1`. Gate 3 recorded two *unit* tests with the same character ([`gate-3/known-gaps.md` §2b](../gate-3/known-gaps.md)). |
| **Not covered** | The sensitivity itself. `e2e/paid-path.spec.ts`'s StrictMode case runs against its **own `next dev` server**, spawned by `playwright.config.ts`'s `webServer` block with a **180 s** startup budget, and `next dev` compiles each route on first request; on a machine running three Compose stacks and sibling builds, first paint does not arrive in time. `e2e/theme.spec.ts` moves between runs under the same conditions. |
| **Why accepted** | Below. |
| **What would change it** | A red `web-e2e` job that a `--failed` re-run turns green **twice running** — at which point it is a defect in the test, not in the host. |

The `next dev` server is not incidental and cannot simply be removed: **the
StrictMode double-mount the paid-path spec exists to catch only happens in a
development build.** R-01's whole claim — that a duplicate response cannot buy a
second paid run — rests on that one scenario, so the spec has to pay for a
development server. The cost is a test whose slowest path is a compile.

This entry is deliberately `accepted` rather than `open`, because the mitigation
that matters is already in place: **it is written down, and the reproduction on
unmodified `main` is committed with it.** A flake nobody has documented is what
teaches a team to re-run CI; a flake with a reproduction is a known cost.

---

## RR-18 — A pinned product defect: the theme-hydration flash

| Field | |
|---|---|
| **Risk** | A user who chooses dark sees dark before first paint, then watches the page turn light a few hundred milliseconds later. It is a **real defect, shipping**, and the test suite is green while it exists. |
| **Owner** | **WO-01** owns the theme foundation; **WO-08** owns `ThemeToggle`. |
| **Accepted at** | Gate 3, recorded in [`gate-3/known-gaps.md` §3](../gate-3/known-gaps.md#3-a-pinned-product-defect); carried unchanged into Gate 4 because no work order in the hardening wave owned it. |
| **Covered** | The pin. `web/e2e/theme.spec.ts:123` — *"a stored dark preference survives hydration"* — is declared `test.fail(true, …)` with the cause written above it, so the defect is **asserted to still exist**. The cause is diagnosed rather than suspected: `serverThemePreference()` returns `"system"`, so React's hydration render uses that snapshot; the effect runs once with `preference === "system"`, passes its `if (preference !== "system") return` guard, writes `data-theme = resolve("system")` = `light`, and never restores it when the client snapshot (`"dark"`) arrives. The pre-paint script and the storage key are both innocent — `data-theme-preference` stays `"dark"` throughout. |
| **Not covered** | The fix. |
| **Why accepted** | Below. |
| **What would change it** | Anyone fixing it. **The suite goes red the moment they do** — deleting the `test.fail()` line is part of the fix, which is the property that stops this pin rotting into a permanent exception. |

Nothing in the Gate 4 wave owned `ThemeToggle`'s hydration path: WO-27 was
accessibility, WO-28 visual baselines, WO-29 Lighthouse, WO-30 the proxy, WO-31
deletions, WO-32 documentation. Fixing a hydration bug inside any of them would
have been an unscoped product change in a work order whose diff was supposed to
be provably narrow.

It is worth being blunt about severity: **this is the most user-visible defect
in this file.** It is not a measurement caveat or an unenforced rule — a person
picks a colour and the product overrides them. It carries a diagnosis, a
regression test that already exists, and two named owners, which is the most a
pack that fixes nothing can leave behind.

---

## RR-19 — Two unwired composer edges, and two Query caches on `/c/[id]`

| Field | |
|---|---|
| **Risk** | `LandingComposer`'s `createThread` mutation and its `unreachable` prop are **wired to nothing**, and as a consequence `/c/[id]` runs **two React Query caches** whose only shared key is `conversations.detail`. |
| **Owner** | [WO-20](../../06-WORK-ORDERS.md#wo-20--route-composition-threadtimeline-activerunpanel-both-pages) → whoever owns the route composition. |
| **Accepted at** | **[D-012](../../DECISIONS.md) ruling 7**, which also required the residual be restated in WO-26's `known-gaps.md` — [`gate-3/known-gaps.md` §4](../gate-3/known-gaps.md#4-wo-20s-two-unwired-edges) — and it is carried forward here unchanged. |
| **Covered** | The behaviour a user sees. Thread creation happens on the landing composer's submit path, which is the only permitted route to `POST /research`; the paid-path ledger is 28 rows, every one PASS. The two caches' only cross-cache write **navigates away**, so there is no window in which a stale second cache is displayed. |
| **Not covered** | The unification. A shared `QueryClient` across `/` and `/c/[id]` would cost `/` roughly **8 KB** it does not have — the same route that needed a budget raise, under D-012 ruling 4, to keep its `h1`. |
| **Why accepted** | Below. |
| **What would change it** | `/` gaining headroom (a dependency shrinking, or the composer's payload falling); or a **second** cross-cache write appearing, which is the day "navigates away" stops being the whole argument. |

This is the cheapest entry in the file to misread as sloppiness, so the shape
matters: nothing is *broken*, and the two edges are not half-finished code left
behind. They are a deliberate refusal to pay 8 KB on the most budget-pressed
route for an abstraction whose only current benefit is tidiness.

The reason it stays on the list is that **the argument is load-bearing on a fact
that could change quietly.** "The only cross-cache write navigates away" is true
of today's composition and is asserted by nobody. A future mutation that writes
to both caches without navigating would reintroduce a real staleness window, and
no test would notice.
