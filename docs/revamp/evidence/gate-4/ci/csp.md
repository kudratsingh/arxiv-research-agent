# CSP — the Report-Only sweep, the enforcing header, and the exact policy

[`05` §4.2](../../../05-MIGRATION.md#42-gate-4--quality-and-documentation-before-ship)
asks this artifact for three things: *"Report-Only run with zero violations
across the state matrix, then the enforcing header … plus the exact policy
shipped."*

**Produced by [WO-30](../../../06-WORK-ORDERS.md#wo-30--proxy-hardening-csp-request-logging-healthcheck-mt-01-seams)
(PR [#109](https://github.com/kudratsingh/arxiv-research-agent/pull/109),
`633b901`); collected and written up here by
[WO-33](../../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks).**
WO-30 shipped the measurement — [`csp-sweep.tsv`](csp-sweep.tsv), 40 data
rows — but not the §4.2-named markdown wrapper. This file is that wrapper. It
adds no measurement and changes nothing.

---

## 1. The policy, exactly as shipped

One source of truth: the `DIRECTIVES` table in
[`web/lib/server/csp.ts`](../../../../../web/lib/server/csp.ts), rendered by
`buildCspPolicy(nonce)`. Eleven directives, in this order, joined with `"; "`,
no trailing semicolon:

```
default-src 'self'; script-src 'self' 'nonce-{nonce}' 'strict-dynamic'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'
```

That string is not transcribed from a document. It is the header a running
container emitted, captured in CI on 2026-08-29 at `9268b54`
([`web-image.log`](web-image.log), step *"Probe the CSP header and the
container healthcheck"*):

```
content-security-policy: default-src 'self'; script-src 'self' 'nonce-vYj5xKATOEf4YbfdUsz5OA==' 'strict-dynamic'; style-src 'self'; style-src-attr 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'
```

### The header is set in the middleware, not in `next.config.mjs`

[`05` §4.2](../../../05-MIGRATION.md#42-gate-4--quality-and-documentation-before-ship)
says "the enforcing header in `next.config.mjs`". **That is wrong as shipped,
and this pack does not repeat it.** The document-route policy is minted
per request by [`web/middleware.ts`](../../../../../web/middleware.ts), which
generates a fresh 128-bit nonce and writes both `x-nonce` and the CSP header.
`next.config.mjs` carries only the *inert* policy for the three paths the
middleware matcher excludes (§3 below). The doc line is recorded as a finding
in [`../README.md` §7](../README.md#7-findings-this-pack-did-not-fix); WO-33
fixes nothing.

### The rollout switch

| `CSP_MODE` | Header | Where it comes from |
|---|---|---|
| `enforce` (default) | `content-security-policy` | `cspModeFor(env)` in `web/lib/server/csp.ts`; `docker-compose.yml` sets `CSP_MODE: ${CSP_MODE:-enforce}` on the `web` service |
| `report-only` | `content-security-policy-report-only` | the C3 first run, §2 |
| `off` | no header | `next dev` only — HMR needs `eval` and inline `<style>` |

`cspModeFor` accepts **only** those three exact strings; anything else —
including `""` and `reportonly` — falls back to `NODE_ENV === "development" ?
"off" : "enforce"`. An unconfigured production deployment therefore gets the
strong policy, not no policy.

### `style-src-attr 'unsafe-inline'` — the one addition to C3's ratified policy

C3 ([`05` §3.1](../../../05-MIGRATION.md#31-build-path-fixes)) does not list
`style-src-attr`. WO-30 added it, and the reason is measured rather than
asserted: the Report-Only sweep produced **exactly three violations across the
whole state matrix, all `style-src-attr`**, all from
`components/primitives/Skeleton.tsx`, which writes caller-supplied width and
height as inline `style` attributes. CSP3 falls `style-src-attr` back to
`style-src`, so `style-src 'self'` was blocking them.

It was deliberately **not** widened to `style-src 'self' 'unsafe-inline'`.
Naming `style-src-attr` separately leaves `style-src 'self'` verbatim, so
`<style>` elements and stylesheet URLs stay same-origin only. A three-engine
probe (Chromium, Firefox, WebKit) confirmed all three honour the narrow form —
measured, not assumed.

This was ratified as **[D-014](../../../DECISIONS.md) ruling 2**, with the
source fix (seven call sites) recorded as a follow-up in
[`docs/security.md`](../../../../security.md). It is carried in
[`../residual-risks.md`](../residual-risks.md) as **RR-12**.

---

## 2. Criterion: Report-Only first, zero violations across the state matrix

[`csp-sweep.tsv`](csp-sweep.tsv) — WO-30's raw output, copied here byte for
byte from the repository-root `ci/csp-sweep.tsv`.

| | |
|---|---|
| States | **20** — every `web/e2e/support/states.ts` row with a distinct rendered layout on that commit |
| Modes | **2** — `report-only` and `enforce` |
| Rows | **40** |
| CSP violations | **0**, in every row |
| CSP console errors | **0**, in every row |
| Blocked directives | none (`—` in every `directives` cell) |

The two runs are evidence for each other only because they observed the **same
policy**: `CSP_MODE` switches the header *name* and nothing else, so both runs
came from one image and one build of `web/e2e/csp.spec.ts`.

```
CSP_MODE=report-only  docker compose up -d --build --wait
npm run e2e -- --project=chromium   # csp.spec.ts: 26 passed
CSP_MODE=enforce      docker compose up -d --build --wait
npm run e2e -- --project=chromium   # csp.spec.ts: 26 passed
```

**The one violation the first Report-Only run found was fixed at source, not
by widening the policy.** It was a `script-src` `eval` from zod 4's JIT feature
probe on plan-review; the fix is `z.config({ jitless: true })` in
`components/patterns/PlanEditorFields.tsx`. That is the whole point of running
Report-Only first, and it is the only thing the first run caught that the
`style-src-attr` decision did not.

The 20 audited states are not a selection: `csp.spec.ts` asserts that
`states.ts` and `DEFERRED_STATES` **partition all 31 rows** of
[`06` §4](../../../06-WORK-ORDERS.md#4-state-coverage-map) exactly, so a row
cannot fall out of the sweep unnoticed.

---

## 3. The three excluded paths, and their inert policy

The middleware matcher is
`["/((?!api/|_next/static/|icon\\.svg).*)"]`. Those three paths get a
different, tighter policy from
[`web/next.config.mjs`](../../../../../web/next.config.mjs) instead:

```
default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'
```

plus `X-Content-Type-Options: nosniff`. Captured on the wire in the same CI
step:

```
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'
```

`/_next/image` is deliberately absent from both lists because the product uses
no `next/image`.

---

## 4. What holds it

| Gate | Where | What it asserts |
|---|---|---|
| Unit | `web/tests/csp.test.ts` (237 lines) | C3's directives transcribed **independently** as `C3_DIRECTIVES` and compared; `added` must equal exactly `["style-src-attr"]`; exactly one `'unsafe-inline'` in the whole policy and none in `script-src`; no `'unsafe-eval'`; exactly one `'nonce-`; nonce freshness over 64 mints and its 24-char base64 shape; the mode switch's fallback semantics; and that the middleware matcher and `next.config.mjs` describe the same three exclusions |
| E2E (`@csp`, chromium) | `web/e2e/csp.spec.ts` (319 lines) | the §4 row partition; zero violations and zero CSP console messages per state; all eleven directives on the wire with a **different nonce on two successive `/` loads**; the inert policy on `/api/healthz` and `/icon.svg`; a real in-page `EventSource` opening under `connect-src 'self'`; the pre-paint theme script carrying the advertised nonce, with first paint themed |
| Harness | `web/e2e/support/csp.ts` | two independent detectors — `securitypolicyviolation` events installed through `addInitScript`, and a console-wording match — so a violation cannot be missed by one channel alone |
| CI (every PR) | `.github/workflows/ci.yml`, job `web image smoke` | the running container's `/` header must contain `'nonce-` **and** `'strict-dynamic'`, and `/api/healthz` must carry `default-src 'none'` — see [`web-image.log`](web-image.log) |
| CI (every PR) | `web/tests/ci.test.ts` | the workflow text still contains `'strict-dynamic'`, so the probe cannot be quietly deleted |

---

## 5. The priced consequence: `/` is no longer statically rendered

A per-request nonce cannot live in a cached document. Reading the nonce in the
root layout opts every document route into dynamic rendering, so `/` moved from
`○` (prerendered) to `ƒ` (server-rendered on demand) and its document now
carries `Cache-Control: private, no-cache, no-store, max-age=0,
must-revalidate`.

Two measured consequences, both already ruled on as
**[D-014](../../../DECISIONS.md) ruling 3**:

1. **`/` fails the desktop `bf-cache` audit by design.** The two reasons are
   Lighthouse's `MainResourceHasCacheControlNoStore` and
   `JsNetworkRequestReceivedCacheControlNoStoreResource`, both classified *Not
   actionable*. RC-18's gate is `/c/[id]`, which is unchanged cell for cell —
   [`gate-3/ADDENDUM.md` §3](../../gate-3/ADDENDUM.md#3-the-bfcache-row-rc-18-stated-precisely)
   and [`../lhci/README.md` §5](../lhci/README.md).
2. **WO-23's manifest cross-check for `/` reads "skipped".** There is no
   prerendered HTML to compare the derived chunk union against. Reproduced on
   this pack's own build — [`../budget-report.md`](../budget-report.md),
   "Manifest cross-check". Carried as **RR-08** in
   [`../residual-risks.md`](../residual-risks.md).

---

## 6. What this file does **not** claim

- **Not that the product is proof against XSS.** A CSP is a mitigation layer.
  What is measured is that the policy is present, is enforcing, carries a fresh
  per-request nonce, and blocks nothing the product legitimately does across
  twenty states.
- **Not that CSRF is addressed.** It is not, and it is out of scope pending
  MT-01 — [`docs/security.md`](../../../../security.md) §CSRF says so in as
  many words, `web/tests/principal.test.ts` asserts that the sentence stays
  there, and it is **RR-13** in [`../residual-risks.md`](../residual-risks.md).
  "Proxy hardened" must never be read as "CSRF considered".
- **Not one engine's word for three.** The sweep is chromium-only
  (`@csp` is in `CHROMIUM_ONLY`). The three-engine claim in §1 is narrower and
  specific: it is about `style-src-attr` fallback behaviour, and WO-30
  measured it directly.
- **Not a report endpoint.** The policy carries no `report-uri` /
  `report-to`; violations were collected in-browser by the harness during the
  sweep, and a deployed instance reports nowhere. Adding a collector is
  out of scope and is not claimed.
