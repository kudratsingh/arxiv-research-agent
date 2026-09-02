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
3. `support/paid-path.ts` intercepts and **fulfils** every paid write in the
   browser — `POST /api/research`, `POST /api/conversations`, and WO-W13's
   two session writes, `POST /api/learn/sessions` and
   `POST /api/learn/sessions/{id}/turn` — so the submit leg never reaches the
   backend at all.

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

Container names are interpolated too — `E2E_APP_CONTAINER`,
`E2E_WEB_CONTAINER`, `E2E_REDIS_CONTAINER`, `E2E_POSTGRES_CONTAINER`, the same
variables `fixtures/seed.sh` reads. The defaults are the `arxiv-wo21-*` names
above, so nothing that already worked moves; a second worktree exports its own
alongside `E2E_COMPOSE_PROJECT` and the two stacks stop overlapping. Without
that, a `container_name` is global to the daemon and the second `up` renames
the first stack's containers out from under it.

Every default lives in `support/env.ts`. Nothing else hard-codes a port.

## API auth is ON in this tier, and why

`compose.e2e.yml` sets `ENABLE_API_AUTH=true`, `ENABLE_LEARNER_PROFILE=true`
and `ENABLE_SESSION_LOOP=true`. Not an option: `src/config.py` refuses the
session loop without the learner profile and refuses the learner profile
without auth, because a guided session is keyed on a principal. WO-W13
criterion 2 wants a real session rendered against a real stack, so the tier
runs with the whole ladder on.

Two consequences worth knowing before you debug something:

- **Every seeded row has an owner.** `_check_ownership`
  (`src/api/routes.py:85-110`) makes a `principal_key_id: NULL` row *invisible*
  under auth-on, so `fixtures/seed.sh` stamps `E2E_PRINCIPAL` (default `e2e`)
  on every job and both conversations. A fixture that 404s after a hand-edit is
  almost always a missing owner.
- **The browser still holds no credential.** The `web` service's server-side
  proxy injects `ARXIV_API_KEY`, exactly as it does in production. The
  side-effect is a good one: every request this suite makes now goes through
  the credential boundary `web/app/api/[...path]/route.ts` describes, so the
  boundary is exercised rather than merely asserted about.

`E2E_API_SECRET` is a committed local sentinel, not a secret. The stack has no
reachable model provider, and CI needs no repository secret to run this tier.

## Layout

| Path | What it is |
|---|---|
| `../playwright.config.ts` | five projects, tags, artifact locations |
| `support/env.ts` | ports, base URLs, seeded ids, thresholds — one definition each |
| `support/global-setup.ts` | refuses to run against an unseeded stack or a real key |
| `support/stack.sh` | `up` / `seed` / `url` / `logs` / `down` |
| `support/compose.e2e.yml` | the isolating overlay |
| `support/paid-path.ts` | the paid-write interceptor (research, conversations, and the two session writes) and its report |
| `support/intercept.ts` | interrupted-200 and `stream_timeout` streams |
| `support/states.ts` | §4's state matrix, as a walkable table |
| `support/measure.ts` | reflow, work surface, safe area, first paint |
| `support/axe.ts` | WO-22's axe run, allowlist parser, contrast probe |
| `axe-allowlist.json` | WO-22's suppression list — **empty, and stays empty** |
| `fixtures/seed.sh` | the promoted Gate 1 seed, extended |
| `__screenshots__/<platform>/` | WO-28's committed PNGs — 48 per platform |
| `*.spec.ts` | one file per criterion; see the header comment in each. `session.spec.ts` is WO-W13's — criteria 2 and 4 |

## Projects and tags

| Project | Runs | Why |
|---|---|---|
| `chromium` | everything except `@device` | the per-PR project |
| `firefox`, `webkit` | everything except `@device`, `@slice`, `@export`, `@axe`, `@cls`, `@csp`, `@a11y`, `@visual` | criteria 6 and 7 are pinned to chromium; the axe sweep is pinned there too, because the twelve retained baseline reports were taken in Chrome and a WebKit contrast measurement is a *different* measurement, not a stricter one; `@visual` because a snapshot's artefact *is* the engine's rasterisation. `playwright.config.ts` argues each one on the `CHROMIUM_ONLY` constant |
| `Pixel 7` | `@device`, `@theme` | 412 × 915 — the width 04 §8.3 audits |
| `iPhone 15` | `@device`, `@theme` | 393 × 852 on WebKit, where `env(safe-area-inset-*)` matters |

Tags: `@paid-path`, `@stream`, `@reflow`, `@slice`, `@export`, `@theme`,
`@device`, `@axe`, `@cls`, `@csp`, `@a11y`, `@visual`.

## Artifacts

Everything is written under `web/build/e2e/`, which is gitignored:

| File | What |
|---|---|
| `research-post-count.txt` | one line per submission scenario — WO-21 criterion 3's evidence, plus WO-W13's session rows. Two row shapes, both legended in the file's own header: research rows count `/api/research` and `/api/conversations`, session rows count the two `/api/learn/sessions` writes |
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

## Visual regression (WO-28)

`visual.spec.ts` takes forty-eight committed screenshots — twelve renders ×
light/dark × 412/1440 px — and compares every later run against them. It closes
`00-DISCOVERY.md`'s missing "visual regression" tier with Playwright's own
`toHaveScreenshot`: no new dependency, no hosted service, no approval UI.

```bash
npm run e2e:visual            # compare against the committed set
npm run e2e:visual:update     # REGENERATE — read "Regenerating" first
```

The twelve renders are the five slice steps (`05-MIGRATION.md` §2.1) plus every
degraded state that has a retained Gate 1 screenshot to be compared against.
The list is in `visual.spec.ts` with each state's baseline file beside it, and
the file's own inventory tests fail if the count moves, if a slice step goes
missing, if a named baseline screenshot no longer exists on disk, or if **two
committed snapshots are byte-identical**.

That last one is not hypothetical. `toBeVisible()` means "has a box", not "is
on screen", so `reconnecting` at 412 passed its ready condition with the
spine's announcement below the fold and captured `running`'s viewport byte for
byte: two files, one picture, one of them asserting nothing about the state it
was named after. The fix is `scrollTo` on that row; the guard is permanent.

### Where the bytes live, and why the path has a platform in it

`e2e/__screenshots__/<platform>/<state>-<theme>-<width>.png`, set by
`snapshotPathTemplate` in `playwright.config.ts`. macOS and Linux rasterise the
same font at the same size differently, so a single set shared between them
fails on whichever host did not produce it. The committed set is `darwin`; a
Linux set is **additive** — run `e2e:visual:update` on Linux and a
`__screenshots__/linux/` directory appears beside it, with nothing to merge.

**A platform with no committed set skips, loudly, with the command that would
fix it.** That is deliberate: failing forty-eight comparisons for the absence
of bytes nobody wrote is a red build that means "no baseline" rather than
"regression", and letting the runner write its own and pass is a baseline the
runner produced and then agreed with, which proves nothing.
`--update-snapshots` turns the skip off, because that *is* the request to
generate the set. One test in the file never skips — "at least one platform's
baseline set is committed" — so deleting the whole tree turns the suite red
instead of quiet.

### Determinism, and what each measure removes

A visual gate that goes red for reasons other than a visual change is worse
than no visual gate: it teaches everybody to regenerate on sight, and a set
regenerated on sight asserts nothing. So:

| Measure | Where | The drift it removes |
|---|---|---|
| No `[data-skeleton-lines]` on screen | `settleForCapture` | A loading placeholder is *static*, so a DOM-quiescence check agrees with itself and photographs a page still waiting for data. This suite flaked on its own second run before this existed. |
| `settleForAudit` | `support/axe.ts`, reused | Two agreeing samples of the serialised DOM — a route paints its header from cache and fills the panel afterwards |
| `document.fonts.ready`, then `fonts.status` asserted | `settleForCapture` | The three faces are self-hosted with `font-display: swap`; a capture before the swap is the fallback metrics. `ready` also resolves on failure, hence the assertion |
| Two `requestAnimationFrame`s | `settleForCapture` | The compositor has painted what the DOM settled on |
| `emulateMedia({ colorScheme, reducedMotion: "reduce" })` | before navigation | The theme axis without `localStorage` (`theme.spec.ts` pins a live hydration defect that would capture dark states in light), and no animation mid-flight |
| `animations: "disabled"`, `caret: "hide"`, `scale: "css"`, `fullPage: false` | the `toHaveScreenshot` call | Passed explicitly, not left to defaults, because they *are* the determinism argument |
| Seeded `baseline-*` fixtures only | `fixtures/seed.sh` | The data is the same on every run by construction |
| Chromium only (`@visual` in `CHROMIUM_ONLY`) | `playwright.config.ts` | A snapshot's artefact *is* the engine's rasterisation; three engines would be three sets of bytes that disagree for reasons that are never product defects |

**Measured result:** 45 of the 48 are byte-identical between two forced
regenerations; the other three differ by 4, 9 and 14 raw pixels, below
Playwright's per-pixel threshold. `maxDiffPixels` is **200**, and
`MAX_DIFF_PIXELS` in `visual.spec.ts` carries the measurement, the cause
(a `position: sticky` `SectionRail` at a fractional x offset, snapped or not
depending on compositor promotion) and the fixes that were tried and rejected.
For scale: a deliberate 2 px shift moves 1,441–13,703 pixels.

### Regenerating

**`e2e:visual:update` is legitimate in exactly one situation: you changed how
something looks, on purpose, and the new pixels are part of the same PR as the
change that produced them.** Then the regenerated PNGs are the *evidence* for
that change and a reviewer looks at them the way they look at a diff.

It is **not** legitimate for:

- **A red run you did not expect.** That is the gate working. Open
  `web/build/e2e/report/` and look at the three-up expected/actual/diff before
  touching the bytes.
- **A red run on a machine that did not produce the set.** A different OS is a
  different rasterisation, not a regression — generate that platform's own
  directory instead (see above).
- **Flake.** If a render is unstable, the fix is a determinism measure in
  `settleForCapture`, not a wider tolerance and not fresh bytes. The table
  above is where such a fix goes, with the drift it removes written next to it.

A regeneration commit should touch only `__screenshots__/`, should say which
change caused it, and should never appear in a PR that changes no styles, no
markup and no copy.

## For WO-24 (CI wiring)

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

**WO-28 — a note for whoever owns CI, not a change to it.** `visual.spec.ts` is
tagged `@visual` and grepped into the `chromium` project, so
`npm run e2e -- --project=chromium` already runs it and the `web-e2e` job above
needs **no new step**. Two things that job's owner has to decide, because this
work order deliberately did not edit a workflow:

- **The runner is Linux and the committed set is `darwin`, so on CI the
  forty-eight comparisons currently SKIP.** They report the reason and the
  command that fixes it, and the guard test above them still runs, so the
  situation is visible in the job log rather than silent. Nothing is red and
  nothing is falsely green — but nothing is gating on the runner either.
  To make it gate: generate `e2e/__screenshots__/linux/` on a Linux host
  (`mcr.microsoft.com/playwright:v1.62.1-noble` against the seeded stack, or
  the runner itself with a one-off `--update-snapshots`), **look at the
  forty-eight images**, and commit them. The suite then activates with no
  code change. Do **not** wire CI to write its own — a baseline the runner
  produced and immediately agreed with proves nothing, which is why
  `--update-snapshots` was left out of the job rather than added to it.
- **Where it belongs once a Linux set exists.** Per-PR in the existing
  `web-e2e` job is the natural home: it is +17 s on the `chromium` project
  against a stack the job already has up, and a visual regression is exactly
  the kind of thing that should block the PR that caused it rather than
  surface in a nightly. WO-29's nightly is the alternative if the Linux set is
  not wanted per-PR — in which case grep `@visual` out of the `web-e2e`
  invocation so the skip does not sit in the log forever.

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

**WO-24's Storybook half.** `support/axe.ts` is written to be reused for WO-22
criterion 5: `analyze(page, { include: "#storybook-root" })` runs the same tag
set scoped to a story root, and `partition(...)` applies the same empty
allowlist. `web/build/e2e/axe/` is already inside the `web/build/e2e` upload
path above, so no extra artifact step is needed.
