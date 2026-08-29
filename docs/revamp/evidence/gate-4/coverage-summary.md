# Coverage at Gate 4 — measured, and the floors it is measured against

Reproduced by [WO-33](../../06-WORK-ORDERS.md#wo-33--gate-4-evidence-pack-and-residual-risks)
on `origin/main` at **`80f6081`**, with no local modification:

```bash
cd web
npm ci
npm run test -- --coverage
```

Vitest v8 provider, two projects (`unit` in jsdom + `storybook`) merged into one
report. `include` is `app/**`, `components/**`, `lib/**`;
`lib/api/generated/**`, `**/*.stories.*`, `components/foundations/**` and
`**/*.d.ts` are excluded. Configuration and both hazard notes:
[`web/vitest.config.mts`](../../../../web/vitest.config.mts).

**The Gate 3 pack has no Gate 4 counterpart for this file, and that is the gap
it closes.** WO-31's ratcheted floors existed only as prose in the config's
comment and in PR [#114](https://github.com/kudratsingh/arxiv-research-agent/pull/114)'s
body; nothing in the evidence tree recorded a measurement against them.

---

## 1. The run

| | |
|---|---|
| Test files | **136** passed (136) |
| Tests | **3,080** passed (3,080), 0 failed, 0 skipped |
| Duration | 34.67 s |
| Instrumented files | **95** (`coverage/coverage-summary.json`) |
| Files at 100 % on all four metrics | **64 of 95** |

## 2. Measured against the enforced floors

The floors are `coverage.thresholds` in `web/vitest.config.mts`. A run below any
of them exits non-zero, and the `web` CI job runs exactly this command.

| Metric | Floor (WO-31) | Measured now | Covered / total | Margin |
|---|---:|---:|---:|---:|
| statements | **97.61** | **97.61** | 2,460 / 2,520 | +0.00 |
| branches | **93.37** | **93.38** | 1,681 / 1,800 | +0.01 |
| functions | **88.10** | **88.21** | 921 / 1,044 | +0.11 |
| lines | **98.57** | **98.57** | 2,006 / 2,035 | +0.00 |

**All four hold. Two of them hold with no margin at all**, and that is by
construction rather than by luck: WO-31 seeded `statements` and `lines` at the
figure it measured, so the very next uncovered line turns the job red. That is
what a ratchet is for, and it is worth a reader knowing before they read
"+0.00" as "nearly failing".

## 3. Movement since Gate 3

Gate 3's numbers are [`gate-3/coverage-summary.md`](../gate-3/coverage-summary.md).

| Metric | Gate 3 floor | Gate 3 measured | **Gate 4 floor** | **Gate 4 measured** |
|---|---:|---:|---:|---:|
| statements | 94.56 | 96.01 (2509/2613) | **97.61** | **97.61** (2460/2520) |
| branches | 88.50 | 91.14 (1792/1966) | **93.37** | **93.38** (1681/1800) |
| functions | 95.05 → 87.50¹ | 96.35 (845/877) | **88.10** | **88.21** (921/1044) |
| lines | 95.94 | 96.90 (2159/2228) | **98.57** | **98.57** (2006/2035) |
| Test files | | 136 | | **136** |
| Tests | | 2,970 | | **3,080** |

¹ Re-seeded during Gate 3's close, **[D-014](../../DECISIONS.md) ruling 1** — a
structural artifact of the dual-project function-list concatenation firing when
Storybook first loaded the route-composition import graph, not a quality drop.

**Three of the four denominators went *down* while the numerators barely moved,
and the honest reading of that is deletion, not new tests.** WO-31 removed
twelve modules that were inside `coverage.include` and that WO-20 had already
stopped composing: they were contributing statements, branches and lines to the
denominator while nothing rendered them. PR #114 says so in its own words —
*"deleting a module nothing exercises raises the ratio without covering a new
line."* The 110 additional tests (2,970 → 3,080) are real; the ratio movement is
mostly not theirs.

## 4. The `functions` column, and why it still lags

`functions` is 88.21 % against three columns in the mid-to-high nineties. This
is a **known measurement artifact, not a coverage hole**, and it is documented
where it happens (`web/vitest.config.mts`) rather than only here: the merged
report **concatenates** the two projects' function lists for every module both
projects load, so a module reached by `unit` *and* by a story is counted twice
in the denominator and once in the numerator. `lib/queries/` and `lib/job/` are
the modules this hits hardest, and the per-file rows show it — `lib/api`
functions read 56.16 % while its statements read 97.79 %.

**88.21 % is therefore a lower bound.** The proper fix — de-duplicating the
function lists in the merged report — belongs to the config's owner, is not a
deletion, and stayed out of WO-31's licence. It is carried as **RR-15** in
[`residual-risks.md`](residual-risks.md).

## 5. Where the uncovered lines are

The v8 text reporter lists only files below 100 %; 64 of 95 files are omitted
because they are complete. The largest single gap is
`components/features/ActiveRunPanel.tsx` at 72.22 % statements / 57.77 %
branches — the module PR #114's coverage note **C3** names, whose `unavailable`
sentence is exercised by a Storybook `play` function rather than by a vitest
`it`. `lib/job/useJobStream.ts` (89.15 % / 78.82 %) and
`lib/job/machine.ts` (98.88 % statements, 65.07 % functions) carry the rest,
and the machine's functions figure is the concatenation artifact of §4 rather
than untested transitions — `web/tests/job/machine.test.ts` walks the total
transition table.

## 6. What this file does **not** claim

- **Coverage is not correctness.** 97.61 % of statements executed says those
  statements ran under some assertion, not that the assertions are the right
  ones. The nine narrowings PR #114 recorded (C1–C9,
  [`rc-03-equivalence.md`](rc-03-equivalence.md)) are the specific places where
  a behaviour is pinned *indirectly*, and they are invisible to this number.
- **The e2e tier is not in it.** These 3,080 tests are Vitest only. Playwright
  contributes no coverage instrumentation; its 419 tests across five projects
  are counted in [`before-after.md` §5](before-after.md) and gated separately.
- **The backend is not in it.** `include` is `web/` only. `pytest (unit +
  integration)` is a separate CI job with its own thresholds.
