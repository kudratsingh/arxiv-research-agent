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
| `fixtures/seed.sh` | the promoted Gate 1 seed, extended |
| `*.spec.ts` | one file per criterion; see the header comment in each |

## Projects and tags

| Project | Runs | Why |
|---|---|---|
| `chromium` | everything except `@device` | the per-PR project |
| `firefox`, `webkit` | everything except `@device`, `@slice`, `@export` | criteria 6 and 7 are pinned to chromium; running them three times adds wall clock, not evidence |
| `Pixel 7` | `@device`, `@theme` | 412 × 915 — the width 04 §8.3 audits |
| `iPhone 15` | `@device`, `@theme` | 393 × 852 on WebKit, where `env(safe-area-inset-*)` matters |

Tags: `@paid-path`, `@stream`, `@reflow`, `@slice`, `@export`, `@theme`,
`@device`.

## Artifacts

Everything is written under `web/build/e2e/`, which is gitignored:

| File | What |
|---|---|
| `research-post-count.txt` | one line per submission scenario — WO-21 criterion 3's evidence |
| `report/` | the HTML report |
| `results.json` | machine-readable results, for CI summaries |
| `test-results/` | traces, screenshots and video, retained on failure |

**They are under `build/` on purpose.** `web/tests/tokens.test.ts` walks all of
`web/` looking for literal colours in `.ts/.tsx/.css/.mjs/.js/.svg` and skips
only `node_modules`, `.next`, `out`, `build` and `.git`. Playwright's HTML
report is a JavaScript bundle full of literal colours, so a report written to
the default `playwright-report/` turns the unit suite red. WO-06 put the
Storybook static build under `build/` for the same reason.

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

**WO-22.** `axe.spec.ts` should import `STATES` from `support/states.ts` rather
than re-listing the state matrix: it already carries each state's path, its
route interception, and a ready condition that keeps a run from passing
against a blank page. `reflow.spec.ts`'s first test asserts that `STATES` and
`DEFERRED_STATES` together partition the whole of §4, so anything iterating
`STATES` inherits that coverage claim. Add `@axe` as a new tag and grep it into
whichever projects the axe job runs.
