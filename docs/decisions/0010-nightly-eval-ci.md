# 0010. Nightly eval CI with artifact-based baseline and regression diff

- **Status**: accepted
- **Date**: 2026-07-06

## Context

The eval pipeline (ADRs
[0005](0005-custom-eval-over-ragas.md) →
[0009](0009-anthropic-sdk-native-retry.md)) can now be invoked reliably
via `make eval`. What's missing is the automated loop: a scheduled run
against `main` whose output we compare to the previous run to catch
quality regressions before someone notices in production.

Key constraints:

- **Cost**. A full 10-query benchmark fires ~300 Claude Sonnet calls
  and takes 15-30 minutes wall time. Nightly cadence is ~$5-15/day.
  Anything more frequent (per-PR) is a serious cost item.
- **Baseline storage**. We need somewhere to keep "the last main run's
  scores" so today's run has something to diff against.
- **Supply chain**. Under the production-scale mandate we should prefer
  built-in tooling to third-party GitHub Actions.
- **Failure semantics**. A regression on `main` should page the
  maintainer, not silently rot.

## Decision

Ship `.github/workflows/eval-nightly.yml` that:

1. Runs on `cron: "0 4 * * *"` (04:00 UTC nightly) and on
   `workflow_dispatch` for on-demand runs.
2. Installs the project via `pip install -e ".[dev]"` on
   `ubuntu-latest`, pinning Python from `.python-version`.
3. Pulls the previous nightly's `eval-summary-latest` artifact via the
   built-in `gh` CLI (no third-party action).
4. Runs `python -m src.eval.runner` with `ANTHROPIC_API_KEY` from
   `secrets.ANTHROPIC_API_KEY`.
5. Uploads the full run as `eval-run-<run_id>` (90-day retention) and
   overwrites the `eval-summary-latest` artifact — that becomes the
   next nightly's baseline.
6. Runs `src.eval.regression_diff` against the baseline, uploads the
   markdown report, and **fails the workflow** if any query regressed
   beyond the `--threshold` (default 0.10).
7. Uses `concurrency: nightly-eval` so overlapping runs (cron + manual
   dispatch) don't race.

Regression diff module (`src/eval/regression_diff.py`) is a standalone
CLI so it can also be run locally against two `summary.jsonl` files.
Exit codes: `0` clean, `1` regression detected, `2` invalid input.

## Alternatives considered

### Baseline storage

- **Commit results to the repo.** Rejected. Bloats history with a
  10-query summary + full state JSONs every night; noisy diffs on
  every scheduled run.
- **Separate `eval-results` branch.** Cleaner than main-branch commits
  but still adds a background branch to maintain. Overkill for our
  needs; artifact retention on GitHub Actions covers ~3 months.
- **External object store (S3).** Right answer at scale — decouples
  history from GitHub Actions retention windows. Deferred until we
  have a reason to keep years of history (e.g. published eval
  numbers).
- **GitHub Actions artifacts (chosen).** Free within our usage tier,
  90-day retention comfortably covers regression detection, no
  external infra.

### Baseline discovery

- **Third-party action `dawidd6/action-download-artifact`.**
  Popular and does exactly what we need. Rejected on supply-chain
  grounds — production-scale mandate prefers built-in tooling. The
  `gh` CLI ships on `ubuntu-latest` runners and gives us the same
  behavior with a few more lines of shell.

### Cadence

- **Per-PR eval.** Great signal, but a full run is $5-15 and 15-30
  minutes — not compatible with fast CI feedback. Deferred to a
  future `feat/eval-on-pr-demand` triggered only by an explicit label
  or comment.
- **Weekly.** Cheaper (~$25/month) but slower to catch regressions.
  Nightly is defensible while we're actively changing prompts and
  agents; revisit after the codebase stabilizes.
- **On merge to main.** Attractive as a "block bad merges" gate, but
  a single 20-minute merge check is a UX regression. Nightly cron
  detects the same regressions with only ~24h latency and doesn't
  block merges.

### Failure semantics

- **Warn but don't fail.** Rejected. Silent regressions are exactly
  what we're trying to catch. A failed nightly emails the maintainer
  by default — that's the paging channel.
- **Auto-file a GitHub issue on regression.** Attractive but
  requires more scaffolding (issue templates, dedup logic). Deferred
  to `feat/eval-regression-issue-bot`. In the interim, the failed
  workflow + regression-report artifact is enough for a human.

### Regression threshold

- **0.10 (chosen).** Score deltas below 10 points are typical
  metric-noise on LLM-as-judge outputs. Bigger drops are real signal.
- **Per-metric thresholds.** More precise but harder to reason about.
  Start with a single global threshold; tighten per-metric when we
  have real data.

## Consequences

- **Positive**:
  - Regressions surface within 24 hours instead of "next time someone
    runs eval manually." Substantial improvement on the current
    zero-CI baseline.
  - Baseline lives in Actions artifacts — no repo pollution, no
    external infra.
  - Regression detection is a standalone module usable locally
    (`python -m src.eval.regression_diff a.jsonl b.jsonl`).
  - `workflow_dispatch` inputs let a maintainer trigger a subset run
    on demand (e.g. after tweaking the reader — only run
    reasoning-heavy queries).
- **Negative**:
  - **Cost**. ~$5-15/day at Sonnet prices, ~$150-450/month. Real,
    not free. Mitigation: `workflow_dispatch` for cheaper on-demand
    runs; consider Haiku for the LLM-as-judge metrics
    (`feat/eval-cheaper-judge`).
  - **Flakiness**. Anthropic 429s (partially mitigated by ADR 0009)
    or arXiv outages can produce false regressions. Mitigation:
    error status is separate from score regression; only real score
    drops fail the run. arXiv retry (`feat/arxiv-download-retry`)
    will further reduce noise.
  - **Baseline is one point in time**. A gradual quality drift across
    30 days won't trip the threshold on any single day. Mitigation:
    follow-up dashboard that shows week-over-week aggregates
    (`feat/eval-dashboard`).
- **Follow-ups**:
  - `feat/eval-regression-issue-bot` — file / update a tracking issue
    when a regression persists across two nightlies.
  - `feat/eval-on-pr-demand` — label-triggered eval on a PR branch
    for pre-merge validation of risky changes.
  - `feat/eval-cheaper-judge` — switch faithfulness/completeness
    judges to Haiku to cut cost by ~5x. Requires calibration
    validation against Sonnet-graded baselines.
  - `feat/eval-dashboard` — track score trends over weeks/months, not
    just yesterday-vs-today.
