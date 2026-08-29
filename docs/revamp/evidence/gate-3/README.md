# Gate 3 evidence pack

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack)
against `origin/main` at **`9b9278a`**, which carries every Gate 3
implementation work order (WO-01 … WO-25). `git diff f72ba96..9b9278a -- web/
.github/ src/ tests/ docs/revamp/06-WORK-ORDERS.md` is **empty**, so this is the
same code the work order names, plus docs-only commits.

**This pack produces evidence. It fixes nothing.** Where a criterion fails, the
failure is reported with the work order that owns the fix, and no product code,
test or CI file was touched — the whole diff is this directory.

**This pack claims no accessibility conformance.** See
[`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim).

---

## The ten criteria

| # | Criterion | Verdict | Where |
|---|---|:-:|---|
| 1 | State index with **zero** uncovered rows across both blocker lists | ❌ **FAIL** | [`storybook-states.md` §3](storybook-states.md#3-the-criterion-1-failure) — 2 §4 rows and 3 RC-10 modules have no story |
| 2 | Every story in light, dark, reduced-motion at 320/412/768/1024/1440 | ✅ **PASS** | [`storybook-states.md` §7](storybook-states.md#7-criterion-2--every-story-in-three-modes-at-five-widths) — 3,915/3,915 mounted |
| 3 | The five slice steps green on all five browser projects | ✅ **PASS** | [`playwright/README.md` §2](playwright/README.md#2-criterion-3--the-five-slice-steps-on-five-projects) — 45/45 |
| 4 | Exactly one `POST /api/research` per intentional submission | ✅ **PASS** | [`research-post-count.txt`](research-post-count.txt) — 28 rows, all PASS |
| 5 | `scrollWidth <= clientWidth` at 320/360/412 on every state | ✅ **PASS** | [`reflow/README.md` §2](reflow/README.md#2-results--60-samples-0-failures) — 60/60 |
| 6 | axe row-for-row vs the twelve baseline reports; six rules at zero; empty allowlist | ✅ **PASS** | [`axe-diff.md`](axe-diff.md) — 40 reports, 0 violations, −77 nodes |
| 7 | Four states × mobile + desktop + a 320 px audit, against §8.2, plus the bfcache row | ❌ **FAIL** | [`lighthouse-diff.md` §4](lighthouse-diff.md#4-the-three-breaches) — mobile CLS 0.134 vs 0.02 |
| 8 | All four contract drift checks green | ✅ **PASS** | [`contract/README.md`](contract/README.md) — 129 assertions, 0 failures |
| 9 | `known-gaps.md` states what is not done | ✅ **PASS** | [`known-gaps.md`](known-gaps.md) |
| 10 | The pack claims **no** accessibility conformance | ✅ **PASS** | [`known-gaps.md` §9](known-gaps.md#9-what-this-pack-does-not-claim) |

**Eight of ten pass. Two fail, and both failures belong to other work orders:**

| Failure | Owner | Summary |
|---|---|---|
| Criterion 1 — `ThreadTimeline/*`, `ActiveRunPanel/*` have no story; §4 rows 5 and B are therefore uncovered | **WO-20** | Its card has no story criterion at all |
| Criterion 1 — `EmptyState/*` has no story | **WO-14** | Criterion 9's story list omits it |
| Criterion 7 — mobile CLS 0.134 against 0.02, from one shift of `main#main` | **WO-08** | Mobile-only; desktop is 0.000 |
| Criterion 7 — `/c/[id]` mobile LCP 3.24–3.70 s against 2.50 s, Performance 85–88 against 95 | **WO-08 + WO-20** | `/` improved; route JS actually went *down* |

Neither failure is a regression this work order introduced, and neither is
patched here — see the risk note on the WO-26 card: *"This work order produces
evidence; it must not fix anything."*

---

## What is in here

| Path | Criterion | What it is |
|---|---|---|
| [`storybook/`](storybook/) | 1, 2 | The static Storybook build — every story, browsable offline. Open `storybook/index.html`. Plus [`render-matrix.json`](storybook/render-matrix.json), the machine-readable criterion-2 result. |
| [`storybook-states.md`](storybook-states.md) | 1, 2 | story ID → §4 state → the baseline screenshot it replaces → axe result, for both blocker lists, plus the decision-branch record. |
| [`playwright/`](playwright/) | 3 | HTML report and `results.json` for the full 208-test matrix, plus the separate all-five-projects slice run. |
| [`research-post-count.txt`](research-post-count.txt) | 4 | The paid-path ledger — one line per submission scenario, per project. |
| [`reflow/`](reflow/) | 5 | `scrollWidth` vs `clientWidth` for every state at 320/360/412, and after-shots against the two baseline phone captures. |
| [`axe/`](axe/) + [`axe-diff.md`](axe-diff.md) | 6 | 40 raw axe reports and 3 TSVs, and the row-for-row diff against the twelve retained baseline reports. |
| [`lighthouse/`](lighthouse/) + [`lighthouse-diff.md`](lighthouse-diff.md) | 7 | Ten `*.gate3.json` runs — four states × mobile/desktop plus two 320 px audits — and the bfcache row. |
| [`budget-report.md`](budget-report.md) | — | `npm run budgets`' own output, verbatim: per-route gzip against the §8.1 ceilings with the delta from the retained baseline. **All five gated rows pass.** |
| [`coverage-summary.md`](coverage-summary.md) | — | Measured coverage and the threshold now enforced. |
| [`contract/`](contract/) | 8 | All four drift checks, with their raw output. |
| [`fonts.md`](fonts.md) | — | **WO-02's**, not this work order's. Left untouched, as are the six Lighthouse runs it committed under `lighthouse/`. |
| [`known-gaps.md`](known-gaps.md) | 9, 10 | What Gate 3 does not establish. Read this one. |

---

## How it was produced

Everything ran against the seeded local Docker Compose stack, on an isolated
Compose project **and** isolated container names, so it could not collide with
another agent's stack. Tool versions: Node 22.23.2, Playwright 1.62.1,
axe-core 4.13.0, Lighthouse 13.4.1, Storybook 10 on the Vite builder.

```bash
# the stack (ports and container names overridden per run)
docker compose -p <project> -f docker-compose.yml \
  -f web/e2e/support/compose.e2e.yml up -d --build --wait
bash web/e2e/fixtures/seed.sh

cd web
npm ci
npm run build-storybook          # -> storybook/
npx playwright test              # -> playwright/, axe/, research-post-count.txt
npm run test -- --coverage       # -> coverage-summary.md
npm run budgets                  # -> budget-report.md
npm run audit:gate
npm run contract:check           # -> contract/
npx vitest run --project=storybook
```

Three measurements criterion 2, 3 and 5 need are not something the merged
tooling performs, so they were taken with evidence-only harnesses under
`web/build/`, which `.gitignore` excludes — **they are not part of this diff
and they do not run in CI**:

- the five-width × three-mode Storybook render matrix (the merged Vitest run
  executes each story once, in jsdom, at one viewport);
- the `@slice` suite with the per-project `grep` filters dropped (the merged
  config pins `@slice` to chromium);
- a recorder that re-runs the merged reflow sweep through the same `STATES`
  table and the same `measureReflow()` helper and writes the numbers down (the
  merged spec asserts them but writes nothing).

---

## The cost boundary

No paid model call was made at any point.
[`06` §0](../../06-WORK-ORDERS.md#0-conventions) states the rule:

> **Cost boundary.** No work order calls a paid model. `POST /research`
> against a real key is never exercised by any automated tier; the seeded
> local stack runs with `ANTHROPIC_API_KEY=local-preview-disabled` exactly as
> the Gate 1 baseline did ([`baseline/README.md`](../../baseline/README.md),
> "Test data and safety").

Four independent mechanisms held it during this run: the Compose overlay pins
the sentinel on the `app` container; `playwright.config.ts` overwrites
`ANTHROPIC_API_KEY` in the runner process before any test loads;
`e2e/support/global-setup.ts` refuses to start on any other value; and
`e2e/support/paid-path.ts` fulfils `POST /api/research` in the browser, so the
submit leg never reaches the backend at all. The seed writes `baseline-*` rows
straight into Postgres and Redis and never calls `POST /research`.

[`research-post-count.txt`](research-post-count.txt) is the ledger of every
submission the suite made — 28 rows, every one PASS.

---

## Decision provenance

WO-26 is decision-dependent: it inherits every Gate 2 ruling, and the state
index records which branch was taken wherever a ruling had alternatives —
including the trace-spine blind spot (the dimensioned static void, not the
status-only chip) and the healthcheck semantics (200 required, `degraded`
tolerated, and owned by WO-30 rather than exercised here). That record is
[`storybook-states.md` §5](storybook-states.md#5-which-ruling-branch-was-taken).
