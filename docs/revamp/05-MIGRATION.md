# Frontend revamp migration plan

Phase: 3 (architecture) — input to **Gate 2**
Date: 2026-08-28
Branch: `docs/frontend-revamp-phase3-architecture`
Base commit: `0b6f291`
Status: proposal awaiting Gate 2 approval

Companion to [`04-ARCHITECTURE.md`](04-ARCHITECTURE.md), which defines the
target. This document defines the **order**, the **rollback story**, and the
**evidence** for Gates 3 and 4.

Everything described here is **planned**. Nothing in `src/`, `web/`,
`docker-compose.yml`, `deploy/`, or `.github/` is modified by this document.
The backend HTTP/SSE contract is frozen throughout every phase below.

---

## 1. Migration strategy

### 1.1 Shape: branch by abstraction, inside the same Next.js app

There is **one** `web/` application throughout. No parallel `/v2` route set,
no second Next app, no shadow deployment. New layers are introduced beneath
the existing components, the components move onto them one at a time, and
the old code is deleted when its last consumer is gone.

Five phases, each one mergeable PR (or a short series), each leaving `main`
shippable.

| Phase | What lands | Visible change | Reversible by |
|---|---|---|---|
| **M0 — foundation** | `app/tokens.css` + `lib/tokens.ts` + Tailwind wiring; `lib/api/*` typed client, error normalizer, contract fixtures; `components/primitives/`; Storybook, Playwright, axe, and budget tooling; `not-found.tsx`, `global-error.tsx`, `app/icon.svg` | Almost none. Product 404 and favicon appear; everything else looks identical | reverting the PR |
| **M1 — shell** | `(workspace)/layout.tsx` with one `<main>`, skip link, responsive rail/drawer, `ScrollRegion` | **Large.** Mobile becomes usable; every axe landmark failure clears at once | reverting the PR |
| **M2 — job machine** | `lib/job/machine.ts` + `JobRunProvider`, GET-first attach, checkpoint rule, `stream_timeout` listener, liveness poll | Honest run states replace the raw event log as the primary surface | reverting the PR |
| **M3 — surfaces** | `TraceSpine`, `PlanEditor`, `ReportReader`, `MetricsStrip`, `ExportMenu`, `ConversationList` — one PR each | Incremental; the Direction A visual system arrives here | reverting individual PRs |
| **M4 — cleanup** | delete `useResearchStream.ts`, `EventLog.tsx`, `ConversationsShell.tsx`, `ConversationThread.tsx` and the compatibility shims; ratchet coverage and budgets | None | reverting the PR |

The abstraction that makes M0 free: `web/lib/api/index.ts` re-exports the
**same function names and signatures** the current modules expose —
`submitResearch`, `getJob`, `reviewPlan`, `streamUrl`, `listConversations`,
`getConversation`, `createConversation`, `deleteConversation`, `ApiError`
(`web/lib/api.ts:16-137`). Existing components keep compiling and the 78
existing tests keep passing while the implementation underneath becomes
typed, normalized, and abortable. The shims are deleted in M4.

### 1.2 Coexistence, and why there are no runtime feature flags

The repository has no feature-flag system today (`00-DISCOVERY.md`
architecture characteristics: "There is no query cache, global store,
form/schema library, component library, message layer, or feature-flag
system"). Adding one for this migration would be a net risk increase:

- It doubles the state space every Playwright and axe run must cover — each
  §2.2 state × flag on/off.
- It adds a way for production to be in a configuration no CI job tested.
- Its main benefit — instant rollback without a redeploy — is worth much
  less here than in a multi-tenant SaaS, because the deployment is a single
  Compose stack (`docker-compose.yml`) behind one Caddy origin
  (`deploy/hetzner/Caddyfile:29`), where redeploy *is* the rollback.

**Coexistence is by merge order instead.** Old and new components coexist
inside one build during M2–M3 because they sit on the same data layer, not
because a flag switches between them. At every commit exactly one code path
ships.

One deliberate exception, and it is not a product flag: the Playwright and
Storybook harnesses need deterministic stubs. Those live in test
configuration, never in the shipped bundle.

### 1.3 Rollback

| Failure | Rollback | Cost |
|---|---|---|
| A phase regresses in review | Close the PR | zero |
| A phase regresses after merge, before deploy | `git revert` the merge commit | one PR |
| A phase regresses in production | `git revert`, rebuild, `docker compose up -d --build web` (or redeploy the CI-built image, §3) | one rebuild of the `web` service only; `app`, `redis`, `postgres` untouched |

Three properties make rollback genuinely safe rather than nominally safe:

1. **The backend never changes.** No migration, no schema version, no
   compatibility window. A rolled-back frontend talks to the same API.
2. **No client-side persistence is introduced.** The job handle stays in the
   URL (`/c/{id}?job={job_id}`), never in `localStorage`
   ([`04-ARCHITECTURE.md` §4.3](04-ARCHITECTURE.md#43-reload-safe-resumption)).
   A rolled-back build has nothing stale to read. The only persisted
   preference introduced at all is the rail collapse state, which is
   cosmetic and safely absent.
3. **URLs are unchanged in every phase.** `/` and `/c/[id]?job=` are
   byte-identical from M0 to M4 (D-003; the `(workspace)` route group adds
   no segment). An in-flight paid job started on the new build is adopted
   correctly by the rolled-back build, and vice versa. This is the property
   that makes rollback safe *while a user's money is in flight* — the case
   that actually matters here.

### 1.4 Why this beats a big-bang replacement

The evidence, not the preference:

- **The risk is concentrated in exactly the files a big-bang would replace
  simultaneously.** Discovery's churn analysis names four:
  `web/lib/useResearchStream.ts` (paid mutation + EventSource + replay +
  HITL + terminal reconciliation), `web/components/ConversationThread.tsx`,
  `web/lib/api.ts`, and `web/app/api/[...path]/route.ts`
  (`00-DISCOVERY.md`, "Git history and risk concentration"). Replacing all
  four in one change means a regression has four plausible causes and no
  bisect boundary.
- **The existing tests are the safety net, and a big-bang throws them
  away.** 78 tests pass today, and the ones that matter most —
  no-double-submit, reload-safe `?job=` handoff, EventSource
  attach/reconnect/terminal, proxy credential handling — are precisely the
  paid and security contracts. Incremental migration keeps them green
  through M0–M2 and retires them only when an equivalent replacement is
  proven.
- **A parallel `/v2` surface would violate D-003 and double the evidence
  burden.** Lighthouse, axe, and screenshots would have to cover both URL
  sets for the whole migration, and the baseline in
  [`baseline/`](baseline/README.md) is anchored to `/` and `/c/[id]`.
- **The budget gate needs a stable comparison point.** Route budgets
  ([`04-ARCHITECTURE.md` §8.1](04-ARCHITECTURE.md#81-route-javascript-budgets))
  are deltas against measured baselines for `/` and `/c/[id]`. A parallel
  route set has no baseline.

**The honest counter-case.** M1 *is* a big-bang for layout, deliberately. A
half-migrated shell cannot satisfy `landmark-one-main` (there would be two
mains or none), cannot satisfy WCAG 1.4.10 reflow (the old fixed 256 px rail
would still be in the layout), and cannot produce a coherent screenshot for
Gate 3. So the shell swaps in one change, and that change is scoped to
layout only — it renders the *existing* feature components unmodified,
which keeps its blast radius auditable and its revert clean.

---

## 2. Rollout order — the approved vertical slice

D-009 approved the first vertical slice as: **new question → reload-safe job
→ plan review → stream/reconnect → report/metrics/export.** The slice runs
*after* M0 and M1 have landed, and it is delivered by M2 + M3.

The requirement is that **architecture risk surfaces in the first slice**.
It does, because this path traverses every load-bearing decision: the
credential boundary, the non-idempotent mutation, the URL contract, the SSE
machine, the token system, the responsive shell, and the budgets.

### 2.1 Step by step

**Step 1 — New question (composer + non-idempotent submit).**
Surfaces: the credential boundary (every call goes through
`web/app/api/[...path]/route.ts`), R-01 (duplicate paid run), R-08 (secret
boundary), the 8,000-character bound (`src/api/schemas.py:17`), and the
two-writes-per-landing-submission rate-limit cost (`src/api/routes.py:157`
and `:545`).
Must fail loudly: a Playwright interceptor counts `POST /api/research` and
asserts **exactly one** per intentional submission across double-click,
Enter-key, React StrictMode double-mount, and an offline→online transition.
Evidence: interceptor count assertion; Storybook `ComposerCard/*`;
`FailureNotice` stories for 429 and 422.

**Step 2 — Reload-safe job (GET-first attach).**
Surfaces: R-02 (lost `?job=` hides paid work) and the whole §2.2 attach
state family.
Must fail loudly: E2E reloads mid-run and asserts the same `job_id` is
adopted with **no** second `POST /research`; a seeded expired job renders
"no longer available" from a clean 404 (`src/api/routes.py:229`) rather than
a stuck busy state — the failure mode the current code path explains at
`web/lib/useResearchStream.ts:171-188`.
Evidence: E2E traces; `TraceSpine/StatusUnknown`,
`RunningNoCheckpoint`, `Unavailable` stories.

**Step 3 — Plan review.**
Surfaces: the HITL boundary, the 409 path, the async-settle contract
(`src/api/schemas.py:141-160`), the plan bounds
(`src/api/schemas.py:26-27`), and R-09 (dynamic forms and keyboard/SR).
Must fail loudly: a seeded `pending_review` job renders its plan from
`JobDetail.plan` **without** an SSE frame; submitting `revise` with an
over-length item is blocked client-side, not by a 422; a 409 refetches and
re-renders instead of showing a dead end.
Evidence: `PlanEditor/*` stories including `Conflict409` and
`HitlTimedOut`; axe on the plan-review state, which must clear the
`aria-allowed-role` / `listitem` / `color-contrast` failures the baseline
records for it ([`baseline/README.md`](baseline/README.md) axe table, 5
violations — tied for the worst state in the matrix with
`failed-partial` and `cancelled`).

**Step 4 — Stream and reconnect.**
Surfaces: R-05 (live/replay divergence), the last-observed-checkpoint rule,
`stream_timeout`, and the heartbeat-invisibility problem
([`04-ARCHITECTURE.md` §4.4](04-ARCHITECTURE.md#44-sse-reconnect-and-the-last-observed-checkpoint-rule)).
Must fail loudly: after an interrupted stream the UI shows **"checkpoint
unknown"** and never re-displays the checkpoint it saw before the break; a
`stream_timeout` frame triggers an immediate reopen; a terminal frame always
triggers `GET /research/{id}` before any success is claimed.
Evidence: recorded frame scripts `reconnect_gap.jsonl` and
`stream_timeout.jsonl`; the interrupted-200 Playwright interception already
proven at
[`baseline/fixtures/capture-baseline.spec.ts:63-76`](baseline/fixtures/capture-baseline.spec.ts);
`TraceSpine/Reconnecting` and `/StreamTimeout` stories.

**Step 5 — Report, metrics, export.**
Surfaces: R-14 (partial reports lost), Markdown rendering without raw HTML
(MUST-KEEP #7), the export download path through the proxy, and the
reading-surface half of the §8 budgets.
Must fail loudly: a seeded failed-with-partial-result job **shows** the
report labelled partial and offers export — the backend permits it
(`src/api/routes.py:364-368`) and the current UI hides it
(`web/components/ReportView.tsx:13-29`); export anchors resolve through
`/api` with `content-disposition` intact.
Evidence: `ReportReader/PartialFromFailedRun`, `MetricsStrip/*`,
`ExportMenu/*` stories; E2E download assertions for `md`, `pdf`, `docx`;
the route budget report.

### 2.2 Risk coverage of the slice

| Risk | Retired or materially reduced by |
|---|---|
| R-01 duplicate paid run | Step 1 |
| R-02 lost active job | Step 2 |
| R-04 mobile unusable | M1, proven across all five steps by the reflow assertion |
| R-05 SSE divergence | Step 4 |
| R-08 secret boundary | Steps 1 and 5 (stream and download both go through the proxy) |
| R-09 keyboard/SR on dynamic forms | Step 3 (automated); Gate 4 for manual |
| R-10 mocks diverge | All steps — fixtures are recorded, not authored |
| R-11 budget consumed by dependencies | Step 3 forces the RHF/Zod dynamic import |
| R-14 partial report lost | Step 5, pending the Gate 2 ruling |

R-03 (invented structured evidence) and R-07 (shared principal mistaken for
multi-tenancy) are not touched by the slice, by design: nothing is invented
and no identity is faked.

---

## 3. CI and operational additions (planned)

Each item names the exact gap from `00-DISCOVERY.md` ("CI, security, and
deployment" → Gaps, and ranked problem 10) that it closes. All are
**planned**; none exists on `main`.

| # | Item | Where | Gap closed |
|---|---|---|---|
| C1 | **Web image CI smoke.** `docker build ./web`, `docker run` it against a stub upstream, assert HTTP 200 on `/` and on `/api/healthz` through the proxy | new `web-image` job in `.github/workflows/ci.yml` | "CI builds only the API image, not the web image/runtime" |
| C2 | **Production overlay validation.** `docker compose -f docker-compose.yml -f deploy/hetzner/compose.prod.yml config --quiet` with dummy env, mirroring the existing base-file check at `.github/workflows/ci.yml:150-154` | extend `docker-build` | "CI does not validate the production Compose overlay" |
| C3 | **CSP.** Ship `Content-Security-Policy-Report-Only` first via Next `headers()`, verified by a Playwright test asserting zero CSP console violations across the §2.2 state matrix; then flip to enforcing. Target policy: `default-src 'self'; script-src 'self' 'nonce-…' 'strict-dynamic'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'`. Honest caveat: a nonce-based policy needs `web/middleware.ts` to generate a per-request nonce, so C3 is the one item that adds a file the architecture otherwise deliberately omits — it is also the natural home for the MT-01 session check later ([`04-ARCHITECTURE.md` §10](04-ARCHITECTURE.md#10-identity-ready-seams-for-mt-01), seam S3). `connect-src 'self'` is sufficient because SSE is same-origin | `web/next.config.mjs` + `web/middleware.ts` | "there is no dependency-audit gate or CSP" |
| C4 | **Dependency audit gate.** `npm audit --audit-level=high` in the `web` job. Baseline is 0 vulnerabilities across 669 dependencies ([`baseline/npm-audit.json`](baseline/npm-audit.json)), so the gate starts green | extend `web` | same gap as C3 |
| C5 | **Meaningful web healthcheck.** Probe `/api/healthz` instead of only `/` (`web/Dockerfile:45-46`, `docker-compose.yml:131-140`). Require HTTP 200 — which proves the proxy path and `API_INTERNAL_BASE` resolve — but **do not** fail on `status: degraded`, or a Redis blip would restart the web container for a backend fault (`src/api/routes.py:786-802`) | `web/Dockerfile`, `docker-compose.yml` | "the web healthcheck proves Next `/` only, not `/api/healthz`" |
| C6 | **Proxy request logging.** One structured JSON line per proxied request: method, path **template**, upstream status, duration, response bytes. Never the key, never a body, never a raw id | `web/app/api/[...path]/route.ts` | "no browser error reporting, web-vitals reporting, or proxy observability exists" |
| C7 | **Route budget check.** `web/scripts/route-budgets.mjs` + `web/budgets.json`, exits non-zero on breach, uploads `budget-report.md` | extend `web` | "no CI budget exists and the manifest association is not currently generated as a stable report" |
| C8 | **E2E + axe job.** Compose up with `ANTHROPIC_API_KEY=local-preview-disabled`, seed, run Playwright + `@axe-core/playwright`, upload traces/screenshots/axe JSON. Chromium per PR; full matrix nightly | new `web-e2e` job | missing Playwright / axe / responsive / offline / timeout tiers |
| C9 | **Storybook build + story tests.** Static build uploaded as an artifact | new `web-storybook` job | missing Storybook tier |
| C10 | **Coverage thresholds.** `--coverage` with thresholds seeded at the first measured value and ratcheted per phase | extend `web` | missing "coverage collection and thresholds" |
| C11 | **Lighthouse CI.** `lhci autorun` with the assertions from [`04-ARCHITECTURE.md` §8.2](04-ARCHITECTURE.md#82-lab-performance-targets), nightly against the seeded stack | new nightly workflow | missing "Lighthouse CI and route-size budgets" |

### 3.1 Build-path fixes

| # | Item | Detail |
|---|---|---|
| B1 | **Favicon 404.** Every completed Lighthouse audit logs a missing `/favicon.ico`, costing Best Practices on all six successful audits. Fixed by `web/app/icon.svg`, which Next emits into the build output — **no `public/` directory is introduced**, so `web/Dockerfile:36`'s "public/ is optional; conditional copy pattern via a placeholder" comment stays accurate. If a `public/` directory is ever added, `web/Dockerfile` must gain the matching `COPY` in the same commit; a checklist line in the Dockerfile comment records that |
| B2 | **`vitest.config.mts` `__dirname`.** Reproduced on this branch: *"Your Vite config uses features that are unsupported by `configLoader: 'native'` … `__dirname` (vitest.config.mts:15:25). Use `import.meta.dirname` instead"*. One-line fix; Node 22 (`web/package.json:7`) supports `import.meta.dirname` |
| B3 | **jsdom download warning.** Reproduced: `Not implemented: navigation to another Document` during the export test. Resolved by asserting the anchor's resolved `href`/`download` attributes rather than clicking through, and by moving real download verification to the Playwright tier |
| B4 | **Build tool stays pinned.** `web/package.json:11` uses `next build --webpack`. Turbopack is a separate ADR (R-15) and is not part of this migration |
| B5 | **CX23 build path (R-12).** Source-building the ML image on a 4 GB CX23 is the deployment risk. Preference is CI-built images pushed to a registry and pulled on the host, so the box never compiles. This is a **DEPLOY-workstream** item and remains paused pending server availability and explicit cost approval; it is recorded here only so the migration does not assume on-box `--build` |

---

## 4. Gate evidence plans

Gate definitions follow the supplied protocol as restored in
[`REVIEW.md`](REVIEW.md): **Gate 3** after the foundation plus the vertical
slice; **Gate 4** after quality and documentation, before ship.

All artifacts land under `docs/revamp/evidence/`, versioned in-repo, so a
reviewer can verify claims against files rather than prose — the standard
the Gate 1 review applied and the second pass explicitly checked.

### 4.1 Gate 3 — foundation + first vertical slice

Produced into `docs/revamp/evidence/gate-3/`:

| Artifact | Path | What it must show |
|---|---|---|
| Storybook static build | `storybook/` | Every story from [`04-ARCHITECTURE.md` §5.3](04-ARCHITECTURE.md#53-the-degraded-state-matrix-as-stories) renders in light, dark, and reduced-motion, at 320/412/768/1440 |
| State index | `storybook-states.md` | story ID → §2.2 state → the baseline screenshot it replaces → axe result. **A §2.2 state with no story is a Gate 3 blocker** |
| Playwright report | `playwright/` (HTML report + traces) | The five slice steps green on chromium/firefox/webkit + `Pixel 7`/`iPhone 15` |
| Paid-path proof | `playwright/research-post-count.txt` | Exactly one `POST /api/research` per intentional submission across the four double-submit scenarios in §2.1 Step 1 |
| Reflow proof | `reflow/` | `scrollWidth <= clientWidth` at 320/360/412 px on every §2.2 state, with before/after screenshots against `baseline/screenshots/home-mobile-full.png` and `conversation-populated-mobile-full.png` |
| axe rerun + diff | `axe/*.json` + `axe-diff.md` | Same tag set as the baseline; **zero** violations of `landmark-one-main`, `region`, `aria-allowed-role`, `listitem`, `color-contrast`, `page-has-heading-one`; a row-for-row diff against [`baseline/axe/`](baseline/README.md)'s twelve reports; empty allowlist |
| Lighthouse rerun | `lighthouse/*.json` + `lighthouse-diff.md` | The four baseline states (landing, empty conversation, populated report, plan review) on mobile + desktop, plus a new 320 px audit, against the §8.2 budgets. Same provenance disclosure the baseline uses: single local lab runs on the seeded stack, not field p75 |
| Budget report | `budget-report.md` | Per-route gzip vs. §8.1 budget with the delta from the retained baseline |
| Coverage summary | `coverage-summary.md` | Measured coverage plus the threshold now enforced |
| Contract drift proof | `contract/` | OpenAPI snapshot check green, generated-type diff empty, fixture parse green, SSE name pinning green |
| Honest limits | `known-gaps.md` | What is **not** done at Gate 3: manual keyboard/screen-reader passes, visual regression baselines, CSP enforcement, LHCI wired to a nightly, M3 surfaces not yet started, and any budget that needed raising with its justification |

Gate 3 explicitly does **not** claim accessibility conformance. Automation
cannot establish keyboard order, focus restoration, announcement quality, or
reflow usability — the same limit the Gate 1 baseline recorded.

### 4.2 Gate 4 — quality and documentation, before ship

Produced into `docs/revamp/evidence/gate-4/`:

| Artifact | Path | What it must show |
|---|---|---|
| Full-matrix axe | `axe/` | Every §2.2 state × light/dark × 320/412/1440, zero violations, allowlist still empty or each entry justified in review |
| Keyboard walkthrough | `manual/keyboard.md` | Skip link, rail/drawer, composer, plan arrays, approve/revise/cancel, event disclosure, report headings/links/tables, export menu, deletion dialog, error recovery — each with observed focus order and restoration |
| Screen-reader logs | `manual/screen-reader.md` | VoiceOver + Safari (macOS and iOS) and NVDA + Firefox: the plan-review decision, a reconnect announcement, and a terminal outcome, each transcribed |
| Reflow and zoom | `manual/reflow/` | 320 CSS px, phone landscape, 200% and 400% zoom, and a very long unbroken report |
| Motion | `manual/reduced-motion.md` | `prefers-reduced-motion` honoured; no status meaning conveyed by motion alone; live regions do not announce every frame |
| Lighthouse CI | `lhci/` | Assertion run green against §8.2, with the lab-vs-field caveat restated |
| Budgets | `budget-report.md` | Final per-route numbers vs. budget; any raised budget carries its PR link |
| Dependency audit | `npm-audit.json` | Exact `npm audit --json` output, comparable to [`baseline/npm-audit.json`](baseline/npm-audit.json) |
| Web image smoke | `ci/web-image.log` | C1 green: image builds, boots, serves `/` and `/api/healthz` |
| Production overlay | `ci/compose-prod-config.log` | C2 green |
| CSP | `ci/csp.md` | Report-Only run with zero violations across the state matrix, then the enforcing header in `next.config.mjs`, plus the exact policy shipped |
| Proxy observability | `ci/proxy-log-sample.txt` | A redacted sample proving no key, no body, no raw id is logged |
| ADRs | `docs/decisions/` | Frontend architecture confirmation (the D-002 decision from [`04-ARCHITECTURE.md` §1.3](04-ARCHITECTURE.md#13-recommendation-for-gate-2)) and a design-token ADR. Numbers assigned at authoring time; 0054 is currently the highest |
| Docs | `docs/architecture.md`, `docs/testing.md`, `docs/development.md` | Updated to describe the shell, the data layer, the test tiers, and the budget gate. `docs/architecture.md:165-168` currently describes `web/` as "a Next.js single-page client (query form, live …)" and needs to match reality |
| Residual risk | `residual-risks.md` | What is accepted at ship, with owners: field CWV still unmeasured, visual-regression coverage depth, browser matrix limits, and the MT-01 dependency for real multi-tenancy |

### 4.3 What Gate 4 must not claim

- **Not** that Core Web Vitals are met in the field. There is no field data;
  every number is a local lab run on a seeded stack.
- **Not** WCAG 2.2 AA conformance as a certification. The claim is: the
  automated gate is green, the manual checks in `manual/` were performed on
  the listed platforms, and the residual gaps are listed.
- **Not** that multi-tenancy exists. MT-01 is a separate backend workstream
  with its own gated proposal and ADR; this revamp ships identity-ready
  seams and nothing more
  ([`04-ARCHITECTURE.md` §10](04-ARCHITECTURE.md#10-identity-ready-seams-for-mt-01)).
- **Not** that the frozen contract's ambiguities are resolved. The twelve
  items in
  [`04-ARCHITECTURE.md` §11](04-ARCHITECTURE.md#11-contract-ambiguities-to-resolve-at-gate-2)
  are frontend *assumptions* until ratified; items 7 (partial-report export)
  and 12 (web healthcheck semantics) need explicit human answers.
