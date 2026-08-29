# Coverage — measured, and the threshold now enforced

Produced by [WO-26](../../06-WORK-ORDERS.md#wo-26--gate-3-evidence-pack).
[`05` §4.1](../../05-MIGRATION.md#41-gate-3--foundation--first-vertical-slice)
asks for "measured coverage plus the threshold now enforced"; both are below.

Command: `npm run test -- --coverage` from `web/` — the same invocation the
`web` CI job runs. Provider **v8**; reporters `text`, `text-summary`,
`json-summary`; report written to `web/coverage/` (gitignored).

**Result: 136 test files, 2,970 tests, all passing, exit 0.**

---

## 1. Measured against enforced

| Metric | Measured | Covered / total | Enforced floor | Margin |
|---|---:|---:|---:|---:|
| Statements | **96.01 %** | 2,509 / 2,613 | 94.56 % | +1.45 pt |
| Branches | **91.14 %** | 1,792 / 1,966 | 88.50 % | +2.64 pt |
| Functions | **96.35 %** | 845 / 877 | 95.05 % | +1.30 pt |
| Lines | **96.90 %** | 2,159 / 2,228 | 95.94 % | +0.96 pt |

104 files are instrumented.

Thresholds live in `web/vitest.config.mts` and are quoted here verbatim:

```js
thresholds: {
  statements: 94.56,
  branches: 88.5,
  functions: 95.05,
  lines: 95.94,
},
```

There are **no** per-file or per-directory overrides — that block is the whole
of `thresholds`.

## 2. What the threshold means, and what it does not

The thresholds are a **ratchet, not a target**. They were last re-seeded by
WO-08 at 1,570 tests (1461/1545 statements, 955/1079 branches, 442/465
functions, 1300/1355 lines), replacing WO-12's 93.98 / 87.99 / 95 / 95.26. The
governing sentence is WO-05's risk note: *"a threshold set aspirationally is a
threshold that gets skipped."* The gate is "do not regress", and nothing else.

The suite has since grown from 1,570 tests to 2,970 — a 89 % increase — while
every metric moved up rather than down. Re-seeding the floors to the numbers in
§1 is **WO-31's** job, not this work order's.

## 3. Scope

Included: `app/**/*.{ts,tsx}`, `components/**/*.{ts,tsx}`, `lib/**/*.{ts,tsx}`.

Excluded, with the config's own reasons:

| Excluded | Why |
|---|---|
| `lib/api/generated/**` | Generated from `contract/openapi.json`; `npm run contract:check` is what guards it, and a `.d.ts` has no statements to cover. |
| `**/*.stories.{ts,tsx}` | Stories are harness, not shipped code; nothing in the product imports them. |
| `components/foundations/**` | The foundations pages and their story-only helper module. |

Two Vitest projects contribute to one merged report: `unit` (jsdom, the
`tests/**` tree) and `storybook` (the stories, executed as component tests with
the per-story axe run attached).

**One measurement hazard, recorded in the config and repeated here:** a module
loaded by both projects has its *function denominator* doubled, because the
merged report concatenates function lists. The functions percentage is
therefore a lower bound, not an exact figure.

## 4. The lowest-covered files, and why

| File | Statements | Reason |
|---|---:|---|
| `components/ConversationsShell.tsx` | **0.00 %** | Retired from the render path by WO-08; nothing imports it. Deletion is WO-31's. |
| `components/ConversationThread.tsx` | 61.97 % | Retired from the render path by WO-20, replaced by `ThreadTimeline`. Deletion is WO-31's. |
| `components/features/ActiveRunPanel.tsx` | 70.58 % | Live; **has no Storybook story** — see [`known-gaps.md` §1](known-gaps.md#1-the-criterion-1-failure). |
| `components/QueryForm.tsx` | 76.92 % | Retired from the render path by WO-13, replaced by `QueryComposer`. Deletion is WO-31's. |
| `components/ConversationSidebar.tsx` | 81.39 % | Retired from the render path by WO-14, replaced by `ThreadRail`. Deletion is WO-31's. |
| `components/features/ThreadTimeline.tsx` | 88.88 % | Live; **has no Storybook story** — same gap. |

Four of the six are legacy modules that no longer render anywhere: they are
still on disk because WO-31 owns the deletion, and they drag the aggregate
down without indicating anything about the shipped surface. The two that are
*not* legacy — `ActiveRunPanel` and `ThreadTimeline` — are the two features
whose missing stories are this pack's criterion-1 failure, and the coverage
number is a second, independent signal of the same gap.

## 5. What coverage does not establish

Line coverage says a line executed, not that it was asserted about. The
evidence that the product behaves correctly is the Playwright slice
([`playwright/`](playwright/)), the axe gate ([`axe-diff.md`](axe-diff.md)) and
the contract drift checks ([`contract/`](contract/)) — not this number.
