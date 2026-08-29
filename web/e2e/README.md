# The browser tier

Playwright 1.62.1 against the seeded local Compose stack. This is the tier
that turns "browser evidence deferred" into browser evidence (WO-21, R-13);
[`04-ARCHITECTURE.md` §7.3](../../docs/revamp/04-ARCHITECTURE.md) is its
specification.

## Run it

```bash
cd web
npm run e2e:stack:up      # build + start the stack, wait for healthy
npm run e2e:stack:seed    # idempotent baseline-* fixtures
npm run e2e               # playwright test
npm run e2e:stack:down    # stop and remove, keeping the volumes
```

Browsers are not vendored: `npm run e2e:install` fetches chromium, firefox and
webkit once.

`npm run e2e` takes the usual Playwright arguments —
`npm run e2e -- --project=chromium reflow.spec.ts`,
`npm run e2e -- --ui`, `npm run e2e -- -g "double click"`.

## The cost boundary

**No automated tier ever runs a research job.** Three independent mechanisms,
because one would be a convention rather than a boundary:

1. `compose.e2e.yml` pins `ANTHROPIC_API_KEY=local-preview-disabled` on the
   `app` service, so the stack cannot reach a provider even if a real key is
   exported in the shell that starts it.
2. `playwright.config.ts` overwrites `ANTHROPIC_API_KEY` in the runner process
   before any test loads, and `global-setup.ts` refuses to start if it is
   anything else.
3. `support/paid-path.ts` intercepts and **fulfils** `POST /api/research` in
   the browser, so the submit leg never reaches the backend at all.

`fixtures/seed.sh` writes fixtures *behind* the API — direct Postgres and
Redis — for the same reason: there is no code path from this tier to a model.

## Ports, container names, and not breaking somebody else's stack

`docker-compose.yml` hardcodes `container_name` on every service, and a
container name is global to the Docker daemon rather than scoped to the
Compose project. Two checkouts cannot run the stack at once, and
`docker compose down` in one removes the other's containers
([`06-WORK-ORDERS.md` §5.4](../../docs/revamp/06-WORK-ORDERS.md)).

`support/compose.e2e.yml` renames all four containers and republishes both
ports. **Always go through `support/stack.sh`**, which passes `-p` and both
`-f` files on every invocation. A bare `docker compose down` from `web/` or
from the repository root will take down whatever else is running.

| | default | override |
|---|---|---|
| Compose project | `arxiv-wo21-e2e` | `E2E_COMPOSE_PROJECT` |
| Web (browser target) | `127.0.0.1:13210` | `E2E_WEB_PORT`, or `E2E_BASE_URL` outright |
| App (proxy target) | `127.0.0.1:18210` | `E2E_APP_PORT` |
| Dev server (StrictMode only) | `localhost:13211` | `E2E_DEV_PORT`, `E2E_SKIP_DEV_SERVER=1` |
| Containers | `arxiv-wo21-{app,web,redis,postgres}` | edit the overlay |

Every default lives in `support/env.ts`. Nothing else hard-codes a port.

## Layout

| Path | What it is |
|---|---|
| `../playwright.config.ts` | five projects, tags, artifact locations |
| `support/env.ts` | ports, base URLs, seeded ids, thresholds — one definition each |
| `support/global-setup.ts` | refuses to run against an unseeded stack or a real key |
| `support/stack.sh` | `up` / `seed` / `url` / `logs` / `down` |
| `support/compose.e2e.yml` | the isolating overlay |
| `support/paid-path.ts` | the `POST /api/research` interceptor and its report |
| `support/intercept.ts` | interrupted-200 and `stream_timeout` streams |
| `support/states.ts` | §4's state matrix, as a walkable table |
| `support/measure.ts` | reflow, work surface, safe area, first paint |
| `support/axe.ts` | WO-22's axe run, allowlist parser, contrast probe |
| `axe-allowlist.json` | WO-22's suppression list — **empty, and stays empty** |
| `fixtures/seed.sh` | the promoted Gate 1 seed, extended |
| `*.spec.ts` | one file per criterion; see the header comment in each |

## Projects and tags

| Project | Runs | Why |
|---|---|---|
| `chromium` | everything except `@device` | the per-PR project |
| `firefox`, `webkit` | everything except `@device`, `@slice`, `@export`, `@axe` | criteria 6 and 7 are pinned to chromium; the axe sweep is pinned there too, because the twelve retained baseline reports were taken in Chrome and a WebKit contrast measurement is a *different* measurement, not a stricter one |
| `Pixel 7` | `@device`, `@theme` | 412 × 915 — the width 04 §8.3 audits |
| `iPhone 15` | `@device`, `@theme` | 393 × 852 on WebKit, where `env(safe-area-inset-*)` matters |

Tags: `@paid-path`, `@stream`, `@reflow`, `@slice`, `@export`, `@theme`,
`@device`, `@axe`.

## Artifacts

Everything is written under `web/build/e2e/`, which is gitignored:

| File | What |
|---|---|
| `research-post-count.txt` | one line per submission scenario — WO-21 criterion 3's evidence |
| `axe/<state>.<theme>.json` | one full axe report per §4 state per theme, in the same shape as `docs/revamp/baseline/axe/*.json` so the two diff directly |
| `axe/summary.tsv` | one row per state per theme: violations, gated, incomplete, contrast passes |
| `axe/baseline-map.tsv` | which live report each retained baseline report corresponds to (WO-26 diffs these pairs) |
| `axe/contrast-proof.tsv` | WO-22 criterion 4 — the three §3.1 replacement pairs, documented ratio beside the measured one |
| `report/` | the HTML report |
| `results.json` | machine-readable results, for CI summaries |
| `test-results/` | traces, screenshots and video, retained on failure |

**They are under `build/` on purpose.** `web/tests/tokens.test.ts` walks all of
`web/` looking for literal colours in `.ts/.tsx/.css/.mjs/.js/.svg` and skips
only `node_modules`, `.next`, `out`, `build` and `.git`. Playwright's HTML
report is a JavaScript bundle full of literal colours, so a report written to
the default `playwright-report/` turns the unit suite red. WO-06 put the
Storybook static build under `build/` for the same reason.

## The axe gate (WO-22)

`axe.spec.ts` runs `@axe-core/playwright` 4.13.0 over every §4 state in both
themes with the baseline's tag set (WCAG 2 A/AA + 2.1 A/AA + 2.2 AA +
best-practice), asserts **zero** violations of `landmark-one-main`, `region`,
`aria-allowed-role`, `listitem`, `color-contrast` and `page-has-heading-one`,
and confirms the three `03 §3.1` replacement colour pairs in a real render.
`04-ARCHITECTURE.md` §7.4 is its specification.

```bash
npm run e2e -- e2e/axe.spec.ts --project=chromium
```

`axe-allowlist.json` is a JSON array and is **empty**. An entry needs `rule`,
`state`, `selector`, `owner` and a written `justification`; `parseAllowlist`
refuses anything less, and refuses outright to suppress one of the six gated
rules. What automation cannot establish — keyboard order, focus restoration,
announcement quality, screen-reader comprehension — is WO-27's manual Gate 4
evidence and is not claimed here.

## For WO-24 (CI wiring) and WO-22 (axe)

**WO-24.** The `web-e2e` job is three commands after `npm ci`:

```yaml
- run: npx playwright install --with-deps chromium
- run: npm run e2e:stack:up
  working-directory: web
- run: npm run e2e:stack:seed
  working-directory: web
- run: npm run e2e -- --project=chromium
  working-directory: web
- uses: actions/upload-artifact@v4
  if: always()
  with:
    name: web-e2e
    path: web/build/e2e
```

Notes it will need:

- `stack.sh up` runs `docker compose up -d --build --wait`, so the healthchecks
  are already waited on; no sleep is needed before seeding.
- `stack.sh` exports `ANTHROPIC_API_KEY=local-preview-disabled` itself, so the
  job needs no secret and must not be given one.
- The `chromium` project is the per-PR set. Nightly is
  `--project=chromium --project=firefox --project=webkit --project="Pixel 7"
  --project="iPhone 15"`, i.e. no argument at all.
- One test starts a `next dev` server for the React StrictMode scenario
  (see `playwright.config.ts`); it needs `node_modules` present, which the job
  already has. `E2E_SKIP_DEV_SERVER=1` turns it off and the test skips itself
  rather than passing vacuously.
- `retries` is 1 and `workers` is 2 under `CI`; `forbidOnly` is on.

**WO-22 — landed.** `axe.spec.ts` iterates `STATES` in both themes (forty
renders), so it inherits `reflow.spec.ts`'s partition claim that `STATES ∪
DEFERRED_STATES` is the whole of §4. `@axe` is grepped into `chromium` only.
Three notes for anyone touching it:

- **The audit viewport is load-bearing.** It is 1440 × 1200, the baseline's
  (`baseline/fixtures/axe-baseline.spec.ts:47`). axe cannot resolve a
  composited background for an element below the fold, so it downgrades those
  `color-contrast` findings to `incomplete`. At Playwright's default 1280 × 720
  the sweep reported *three fewer* real violations than the retained baseline —
  a gate that looked greener than the thing it was auditing.
- **`settleForAudit` is not a sleep.** A thread route paints its header from
  cache and fills the run panel and the event list afterwards; auditing between
  those moments under-reports. It waits for two consecutive samples of the
  serialised DOM to agree, capped, so a live stream still gets audited.
- **`PENDING_COMPOSITION` is not an allowlist.** It pins the gated violations
  that survive in the legacy components WO-20 has not replaced yet, each with
  its file, its line and its owning work order. It fails in *both* directions:
  a new gated violation anywhere goes red, and so does an entry that stops
  matching — at which point the entry must be deleted, not kept.

**WO-24.** `support/axe.ts` is written to be reused for the Storybook half of
WO-22 criterion 5: `analyze(page, { include: "#storybook-root" })` runs the same
tag set scoped to a story root, and `partition(...)` applies the same empty
allowlist. Upload `web/build/e2e/axe/` with the rest of `web/build/e2e`.
