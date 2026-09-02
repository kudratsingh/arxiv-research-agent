# The learning eval harness — what is green, and what has never run

Gate W1 has three eval rows. Two resolve at the no-cost boundary; one does not
resolve at all.

> Judges + benchmark green on their own tests; scripted simulation tier green
> in per-PR CI | CI runs | W08–W11 — **Resolved**
>
> Regression differ carries the learning metrics | unit tests | W11 —
> **Resolved**
>
> **First funded learning-eval campaign executed** (calibration + simulation)
> under `--max-budget-usd`; numbers recorded **as priors** | campaign reports |
> W09 c6, W10 c5 — **waits on W-OD-1** — **UNRESOLVED**

---

## 1. The scripted simulation tier, in per-PR CI

**This is the load-bearing artifact of the row.** WO-W11 c3 added a step to
`ci.yml`'s Python job that runs the whole campaign — not a unit test — and
asserts the summary:

```yaml
- name: Scripted learner simulation (zero spend)
  env:
    USE_MOCK_DATA: "true"
    ANTHROPIC_API_KEY: local-preview-disabled
    ENABLE_CHECKPOINTING: "true"
  run: |
    python -m src.eval.simulate_learner --output-dir outputs/eval/ci-scripted-tier
    python -m src.eval.scripted_tier_check outputs/eval/ci-scripted-tier/summary.jsonl
```

(`.github/workflows/ci.yml:177-186` on `3ccb650`)

On `3ccb650`, run
[33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
job *pytest (unit + integration)*, the step printed:

```
Scripted tier OK: 15/15 sessions, $0.0000 spent, 0 unmet expectations.
```

Its `scripted-simulation-summary` artifact is copied verbatim into
[`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md).
The numbers in it, quoted from that file: **15 sessions, 0 errors, 0 partial
scores, 0 sessions with unmet expectations, $0.0000 session cost, $0.0000
simulated-learner cost, $0.0000 judge cost, $0.0000 total.**

Three properties of that artifact are worth naming, because they are the
difference between a green check and evidence:

1. **A dollar figure can round to zero; a call count cannot.**
   `src/eval/scripted_tier_check.py` asserts four cost columns *and* three
   call-count columns *and* the session count *and* the unmet-expectation
   count. `tests/test_scripted_tier_check.py` (**22 tests**) mutates one
   property per test, including the sub-cent case where the dollar rounds to
   zero and the call count does not (PR [#148](https://github.com/kudratsingh/arxiv-research-agent/pull/148)).
2. **The summary states its own limits.** It opens with *"Simulated learners,
   not learners: these are process metrics"* and closes with a repeat-discipline
   WARNING — one repeat per scenario, where three is the bar before a delta is
   believable.
3. **The cost row labels itself.** *"Measured mean `cost_usd` over 15
   session(s) | 0.0000"* sits beside *"Plan estimate — **not a measurement** |
   0.07 – 0.17"*, with the source of the estimate quoted in the line below it.
   $0.0000 is what a mock run costs; it is not what a guided read costs.

## 2. Judges and benchmark, on their own tests

Counts from `pytest --collect-only` on `3ccb650` with the repo venv.

| Component | File | Tests | Card |
|---|---|---:|---|
| Learning benchmark + scenario schema | `tests/test_learning_benchmark.py` | **41** | W08 (#132) |
| Fixture machinery + provenance gate | `tests/test_learning_fixtures.py` | **36** | W08 (#132), completed by W11 |
| Learning metrics / judges | `tests/test_learning_metrics.py` | **23** | W09 (#139), +5 from W10 |
| Assessment judge | `tests/test_assessment_judge.py` | **15** | W04 (#142) |
| Learner simulation | `tests/test_simulate_learner.py` | **49** | W10 (#145) |
| Scripted-tier assertion | `tests/test_scripted_tier_check.py` | **22** | W11 (#148) |
| Recorded fixtures | `tests/test_record_learning_fixtures.py` | **15** | W11 (#148) |

PR [#145](https://github.com/kudratsingh/arxiv-research-agent/pull/145)'s test
plan: **1947 passed, 52 skipped, 0 failed**, of which 50 tests were new.
PR #148's: **2038 passed, 52 skipped**. CI on `3ccb650` runs the same suite with
the Postgres service present and reports **2090 passed** (= 2038 + the 52 that
skip locally).

## 3. The regression differ carries the learning metrics

**Resolved.** `src/eval/regression_diff.py` grows a `MetricLane`;
`--lane learning` reads `simulate_learner`'s summary keyed by `record_id`.
`tests/test_regression_diff.py` is **113 tests** (66 → 113, PR #148), including:

- `TestLearningLaneEveryGatedField` — both directions over all nine gated
  fields (18 cases), plus `test_every_gated_field_is_covered_by_this_class`,
  which fails if a field is added to the lane without a case.
- `TestLearningLaneResourceBands` — each band leg independently, plus the
  per-lane ADR 0044 invariant.
- `TestLearningLaneHarnessCostIsNotGated` — a 100× judge-cost rise does not
  fail a run but is still tabulated. ADR 0050's rule: the gate reads the
  product.
- `TestLaneIsolation` — `RESEARCH_LANE.metric_fields is METRIC_FIELDS` and the
  two siblings, so the research lane cannot drift onto a copy.

PR #148 also ran a byte-identity check of the research lane's rendered output
against `origin/main`'s module across six configurations.

**Its limit, from `docs/eval.md` §"Status: disabled, and no green campaign
yet", verbatim:**

> The regression gate has therefore never compared two real runs, on either
> lane. Its thresholds, its aggregate table and its exit codes are unit-tested
> (`tests/test_regression_diff.py`), not yet exercised on live data. The
> learning lane's bands are priors in exactly the same sense as the research
> lane's — reasoned from the mechanics, not measured.

## 4. The three funded rows — UNRESOLVED, waiting on W-OD-1

Nothing in this repository has ever run a paid learning campaign. The three
deferrals are each written into `docs/eval.md` by the card that deferred them.

| Row | Card | Sizing on record | Where the deferral is written |
|---|---|---|---|
| First funded **calibration** run | **WO-W09 c6** (#139) | none published beyond W-OD-1's order-of-magnitude | `docs/eval.md`: *"Owner review and the funded campaign remain W-OD-1"*; PR #139 body: *"Documents that W-OD-1 and paid calibration remain locked"* |
| First funded **simulation campaign** | **WO-W10 c5** (#145) | ≈15 sessions, roughly **$2–6**, ceiling proposed at **$15** (a judgment call) | `docs/eval.md` §"The first funded campaign is deferred — W-OD-1" |
| The nightly learning lane's **first scheduled run** | **WO-W11 c4** (#148) | the workflow's `DEFAULT_LEARNING_MAX_BUDGET_USD` is **$15**, WO-W10's proposed figure | `docs/eval.md` §"Status: disabled, and no green campaign yet" |

**§2's order of magnitude for W-OD-1**, verbatim from the owner-approval
ledger: *"The first funded eval campaigns in repo history; order **$25–75 per
campaign** per [`04` §5 Rung 0], enforced by `--max-budget-usd`."*

The exact owner action, from §2: **set the `ANTHROPIC_API_KEY` repository
secret** (54/54 nightly runs have failed without it) **and approve the
learning-eval budget** — the calibration scoring run (W09), the first
simulation campaign (W10), and a nightly-lane ceiling (W11).

**State of the workflow on `3ccb650`:** `.github/workflows/eval-nightly.yml`
is `disabled_manually` and stays disabled. WO-W11 edited it and *"did not
enable it, did not dispatch it, and did not add a secret"* (`docs/eval.md`).
Both lanes stop at an `ANTHROPIC_API_KEY` preflight with a titled annotation
naming the owner action — the same honest failure the research lane has had
**54 of 54 nights between 2026-07-07 and 2026-08-29** (`docs/eval.md`).

Consequences that follow, quoted from `docs/eval.md` because they are easy to
miss:

- *"No `summary.jsonl` has ever been produced by CI, and neither an
  `eval-summary-latest` nor a `learning-summary-latest` artifact exists in the
  repository's artifact store."*
- *"Every metric figure quoted anywhere in these docs … is illustrative of the
  *schema*, not a measured result."*

## 5. The recorded-fixture set, and the divergence

WO-W11 item 6 closed WO-W08's pending fixture slot:
`src/eval/record_learning_fixtures.py` replays every scenario through
`build_session_workflow()` in mock mode and writes fifteen transcripts with
commit + `mock_mode: true` provenance. `tests/test_record_learning_fixtures.py`
(**15 tests**) includes
`test_a_fresh_recording_reproduces_the_committed_files` — deliberately brittle,
and it obliges any future change to the session graph or tutor copy to re-run
`make record-learning-fixtures`. See [`known-gaps.md`](known-gaps.md) §5.

**WO-W11 c7** resolved the one W08/W03 divergence WO-W10 recorded, in favour of
the graph's documented rule: the `engineer-rlhf-profile-note-injection`
scenario's `max_plan_sections=1` expectation moved to `2`, because
`_fallback_plan` allocates 2 for a declared 15-minute budget (≤10 → 1, ≤20 → 2,
else 3) and nothing about that scenario is time-poor. **No graph behaviour
changed.** `test_unmet_expectations_are_exactly_the_recorded_baseline` still
pins the set exactly and now asserts it is empty — which is why the CI summary
above reads `0` unmet expectations where PR #145's own run read `1`.
