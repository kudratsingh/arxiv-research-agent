# Playwright — the browser tier

Produced by [WO-26](../../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack),
criteria 3 and 4.

| Path | What |
|---|---|
| [`report/`](report/) | HTML report for the full matrix. Open `report/index.html`. |
| [`results.json`](results.json) | The same run, machine-readable. |
| [`slice-matrix/`](slice-matrix/) | A second run: the nine `@slice` tests on **all five** browser projects (§2). |
| [`../research-post-count.txt`](../research-post-count.txt) | The paid-path ledger for the full matrix. |
| [`slice-matrix/research-post-count.txt`](slice-matrix/research-post-count.txt) | The ledger for the five-project slice run. |

Everything ran against the seeded local Compose stack described in
`web/e2e/README.md`, on its own Compose project **and** its own container
names, so it could not collide with another agent's stack.

---

## 1. The full matrix

**208 tests, 208 expected, 0 unexpected, 0 flaky, 0 skipped** — 3 m 7 s.

| Project | Tests | Result |
|---|---:|---|
| chromium | 100 | all green |
| firefox | 38 | all green |
| webkit | 38 | all green |
| `Pixel 7` | 16 | all green |
| `iPhone 15` | 16 | all green |

The projects run different subsets by design, and the config says why:
`@device` is mobile-only; `@slice`, `@export`, `@axe` and `@cls` are pinned to
chromium (axe because the twelve retained baseline reports were taken in
Chrome and a WebKit `color-contrast` measurement is a *different* measurement,
not a stricter one; `@cls` because the `layout-shift` performance entry does
not exist outside Chromium, so the observer elsewhere would collect nothing and
pass without measuring anything).

Three tests report as `✘` in the console and still count as expected: they are
`web/e2e/theme.spec.ts:123`, declared `test.fail(true, …)` against a known
`ThemeToggle` hydration defect. That defect is written up in
[`../known-gaps.md` §3](../known-gaps.md#3-a-pinned-product-defect).

### One flaky assertion, observed on an earlier run of the same commit

`web/e2e/stream.spec.ts:30` — *"an interrupted 200 stream is narrated, not
raced"* — was green in this run, but **3 of 12 earlier observations on this same
commit were red** (chromium, webkit and firefox alike), with
`expect(stream.opens()).toBe(1)` receiving `2`. It is a harness defect, not a
product one, and it is written up in
[`../known-gaps.md` §2](../known-gaps.md#2-a-flaky-assertion-in-the-merged-suite).
Owner: **WO-21 criterion 4**.

---

## 2. Criterion 3 — the five slice steps on five projects

WO-26 criterion 3 asks for the five slice steps green on chromium, firefox,
webkit, `Pixel 7` and `iPhone 15`.

**The merged harness does not run them there, by design.**
`web/playwright.config.ts` puts `@slice` in `CHROMIUM_ONLY`:

```ts
const CHROMIUM_ONLY = /@slice|@export|@axe|@cls/;
```

That matches **WO-21 criterion 6**, whose wording is "The five slice steps run
green end to end **on chromium**", and the config's comment gives the reason —
"running them three times would add wall clock and no evidence."

The two work orders disagree, so this pack settles it by **measuring** rather
than by choosing. An evidence-only config under `web/build/wo26/` — gitignored,
so not part of this diff — takes the repository's own config and drops the
per-project `grep` / `grepInvert` filters for one run. Nothing else changes:
same `testDir`, same `globalSetup`, same paid-path interceptor, same seeded
stack, same spec file, same nine tests.

**Result: 45 tests, 45 expected, 0 unexpected — 9 tests × 5 projects, 37.2 s.**

| Slice step | Test | chromium | firefox | webkit | Pixel 7 | iPhone 15 |
|---|---|:-:|:-:|:-:|:-:|:-:|
| 1 | a new question submits once and hands off with `?job=` | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2 | reloading mid-run re-adopts the same job and buys nothing | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2 | an expired job is a dead end that says so | ✅ | ✅ | ✅ | ✅ | ✅ |
| 2 | back navigation re-adopts the same job, with no second POST | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3 | a seeded `pending_review` job renders its plan with no SSE frame | ✅ | ✅ | ✅ | ✅ | ✅ |
| 3 | a 409 on review refetches and re-renders, and is not a dead end | ✅ | ✅ | ✅ | ✅ | ✅ |
| 4 | a terminal frame is reconciled against `GET /research/{id}` | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5 | the newest turn reads, an older one expands, and both export | ✅ | ✅ | ✅ | ✅ | ✅ |
| 5 | an attached failed run shows its partial briefing, labelled, with export | ✅ | ✅ | ✅ | ✅ | ✅ |

**The finding this leaves behind:** the slice steps *pass* on all five
projects, but nothing in CI runs them there — not even the nightly full matrix,
because `E2E_FULL_MATRIX` changes which projects are installed and invoked, not
which tests each project greps. Whether the config should be widened is
**WO-21's** call. This work order reports it and changes nothing.

---

## 3. Criterion 4 — the paid-path ledger

`POST /api/research` has no idempotency key, so a duplicate request is a
duplicate paid run (R-01, MUST-KEEP #3). `web/e2e/support/paid-path.ts` counts
every attempt **in the browser** and appends one line per scenario to
[`../research-post-count.txt`](../research-post-count.txt).

**28 rows, every one PASS.** The four double-submit scenarios criterion 4 names
run on all three desktop projects:

| Scenario | Expected | chromium | firefox | webkit |
|---|---:|:-:|:-:|:-:|
| `single click` | 1 | 1 ✅ | 1 ✅ | 1 ✅ |
| `double click` | 1 | 1 ✅ | 1 ✅ | 1 ✅ |
| `Enter key (ControlOrMeta+Enter)` | 1 | 1 ✅ | 1 ✅ | 1 ✅ |
| `repeated keyboard submit` | 1 | 1 ✅ | 1 ✅ | 1 ✅ |

Three further scenarios ledger a submission that must **not** be a purchase:

| Scenario | Expected | chromium | firefox | webkit |
|---|---:|:-:|:-:|:-:|
| `StrictMode double mount (attach path, next dev)` | 0 | 0 ✅ | 0 ✅ | 0 ✅ |
| `offline then online (offline attempt counted as 0)` | 1 | 1 ✅ | 1 ✅ | 1 ✅ |
| `interrupted stream (recovery is never a purchase)` | 0 | 0 ✅ | 0 ✅ | 0 ✅ |

…plus seven chromium-only rows from the slice and CLS specs, all `expected=0`
except `slice step 1 — new question`, which is `expected=1` and got 1.

**One row deserves reading twice.** chromium's `offline then online` shows
`POST /api/conversations=2` against `POST /api/research=1`. That is correct and
is the point of the scenario: the offline attempt created a thread before the
research call was blocked, and the retry created another. The number that is
gated — and the number that costs money — is the research count, and it is 1.
`POST /conversations` is free and idempotent-by-consequence.

The StrictMode row is the one that needs a development build: `reactStrictMode`
is set in `next.config.mjs`, but React's double invocation of effects is a
**development-only** behaviour, so asserting it against the production
container would prove nothing. The config therefore starts a real `next dev` on
its own port, proxying to the same seeded stack.

---

## 4. What the browser tier does not establish

The suite proves behaviour against a seeded stack in five browser profiles. It
does not establish keyboard order, focus restoration, or announcement quality —
those are manual passes scheduled in WO-27 — and it takes no visual-regression
snapshots, which are WO-28's. See [`../known-gaps.md`](../known-gaps.md).
