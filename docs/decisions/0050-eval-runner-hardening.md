# 0050. Make the eval campaign survivable: isolate judges, persist incrementally, and stop lying about cost and exit status

- **Status**: accepted
- **Date**: 2026-08-21
- **Deciders**: maintainer

## Context

The eval campaign is the next thing this repo spends real money on: 20
benchmark queries, each a full multi-agent research run plus three
LLM-as-judge scoring calls. A pre-flight audit of `src/eval/runner.py`
found the harness could not be trusted to hold onto work it had already
paid for.

**The batch was all-or-nothing.** `_run_and_score` guarded the workflow
invocation with `except Exception` but computed the four metrics
*outside* that guard. Three of the four are judge calls
(`src/eval/metrics.py:283`, `:540`, `:725`), each a bare
`call_llm_json`, and `src/llm.py` lets both `json.JSONDecodeError` and
every Anthropic SDK error propagate once `anthropic_max_retries` is
spent. `main()`'s loop caught `KeyboardInterrupt` and nothing else, so
one 529 on query 12's faithfulness judge took down the run: query 12's
completed workflow output — already paid for — was never appended to
`records`, and queries 13-20 were never attempted. That directly
violated two written contracts: ADR 0008 chose per-query error
isolation over fail-fast ("Fail-fast on first error. Rejected."), and
`_run_and_score`'s own docstring claimed "Never raises".

**Nothing reached disk until the end.** `_write_output` ran once, after
the loop. A kill, an OOM, an Actions cancellation or a laptop lid at
query 15 of 20 destroyed fifteen finished runs. SIGTERM was worse than
SIGINT: its default disposition terminates without unwinding, so
`docker stop` and a cancelled workflow ran no `finally` and flushed
nothing. There was no way to re-enter a campaign — re-running meant
re-paying for every query.

**The published cost figure was the harness's, not the product's.** The
record's single `costs` snapshot was taken after scoring, so the
judges' three calls were billed to the workflow. That number flows into
the README's "mean cost per research run" and into
`regression_diff`'s `cost_usd` band: the gate was policing eval-rig
noise alongside product spend, and the README overstated what one
research run costs.

**Three ways to be green while being wrong.** (1) An empty
`draft_report` scored `citation_accuracy=1.0` and `faithfulness=1.0` by
short-circuit — a run that produced nothing published as a perfect one,
at the price of two wasted judge calls. (2) A report with zero
citations also scored a free 1.0, which `readme_update` averaged into
the published citation figure — inflating it exactly when the agent
cited least. (3) `regression_diff` classified a query missing from the
current run as `removed` and did not gate on it, while
`_aggregate_over_shared` silently re-averaged the aggregate row over
the survivors: a batch truncated at query 15 passed green on a shrunken
denominator, with nothing in the report saying the denominator moved.

**`make eval` returned 0 when every query failed.** `main()` returned
`0` unconditionally on the non-interrupt path, so no wrapper, Makefile
target or workflow step could tell a clean campaign from a total
outage.

**And the nightly had been silently red for 15+ consecutive nights** on
an unset `ANTHROPIC_API_KEY` secret, dying inside `Run eval` with a
"copy .env.example to .env" message that reads like a code bug. The
three artifact steps were unconditional, so a run that died partway
uploaded nothing at all — including `eval-summary-latest`, which is the
*next* night's baseline, compounding one bad night into two.

## Decision

Nine changes across `src/eval/runner.py`, `src/eval/regression_diff.py`,
`src/eval/readme_update.py` and `.github/workflows/eval-nightly.yml`.

### 1. Per-metric judge isolation

`_compute_metrics` computes each of the four metrics inside its own
`try/except Exception`. A failed metric lands as `None` (which
`_get_score` already reads as "no score"), its message joins a
`"; "`-separated `metrics_error` on the record, and `state`, `costs`
and `elapsed_sec` are kept. `except Exception` — not `BaseException` —
so a Ctrl-C still unwinds. `reset_run_id(token)` moved into `finally`;
previously the failure paths left the dead query's `run_id` bound into
the next query's log lines.

### 2. Incremental persistence, `--resume`, and a SIGTERM handler

`persist_record()` writes `queries/<id>.json` and appends one flushed
line to `summary.jsonl` immediately after each query. `summary.md` is
regenerated once at the end, from disk, by `rebuild_summaries()`. A
hard kill now loses at most the in-flight query.

`--resume` skips queries whose `queries/<id>.json` already exists and
loads those records so the final summary covers the whole campaign. The
per-query files are the durable layer; `summary.jsonl` and `summary.md`
are derived from them, so the end-of-run rebuild also de-duplicates the
lines a resumed run appends beside the first attempt's.

`_install_interrupt_handler()` maps SIGTERM onto `KeyboardInterrupt`, so
`kill`, `docker stop` and an Actions cancellation take the same
graceful path Ctrl-C already had. `_run_and_score` catches
`KeyboardInterrupt` and re-raises `EvalInterrupted` — a
`KeyboardInterrupt` subclass carrying the in-flight partial record — so
`main()` can write down the spend that already happened before
unwinding.

### 3. Workflow spend and judge spend are separate fields

The record snapshots `costs` *before* the judges run and stores the
difference as `judge_costs`. In `summary.jsonl`:

| Field | Means |
|---|---|
| `cost_usd`, `llm_calls`, `elapsed_sec` | the **workflow** only |
| `judge_cost_usd`, `judge_llm_calls`, `scoring_sec` | the **judges** only |
| `total_cost_usd` | their sum — "what did this benchmark query cost me" |

**The naming call:** `cost_usd` keeps its name and changes its meaning
rather than being renamed. Renaming would have silently zeroed the
`cost_usd` band in `regression_diff` (a missing field diffs as `None`,
which is never a regression) against every pre-existing baseline —
turning a cost gate off is the one failure mode worth avoiding here.
The cost of the choice is that summaries written before this ADR are
not comparable on `cost_usd` with ones written after; they read a few
percent high. That is stated in `_summary_line`'s docstring, in
`regression_diff`'s module docstring, and here.

The regression gate therefore now tracks product spend, and the README
row answers "what does one research run cost" without the eval rig in
it.

### 4. An empty report is an error, not a perfect score

A blank or whitespace `draft_report` records
`error="NoReportProduced: stop_reason=..."` and skips all four metrics
— saving two wasted judge calls per occurrence. The workflow's state
and costs are still recorded.

### 5. Uncited reports leave the citation-accuracy mean

`readme_update` excludes rows with `total_citations == 0` from the
citation-accuracy mean only, and states the exclusion and its
denominator under the table. Other metrics keep the full denominator.
Rows from pre-ADR-0050 summaries carry no `total_citations` field at
all; those are treated as unknown and kept, so the historical mean does
not retroactively empty itself.

### 6. A vanished query is a regression

`diff_summaries` gates on `removed` alongside `regressed` and
`errored`. `--allow-removed` opts a deliberate subset run out. The
report states its denominator explicitly ("over the 15 of 20 baseline
queries present in both runs") so a shrunken aggregate can no longer
read as a full one.

### 7. Honest exit codes

`0` clean · `1` config (no API key) · `2` usage (non-empty output dir
without `--resume`) · `3` partial failure · `4` every query failed ·
`5` budget ceiling · `130` interrupted. Precedence is "why is the
campaign incomplete" before "how did the queries go". The closing
stdout line states succeeded/errored/reused counts and total spend.

### 8. A populated `--output-dir` is refused without `--resume`

Re-running into last night's directory used to truncate its
`summary.jsonl` and overwrite some of its `queries/*.json` while
leaving the rest stranded — silent destruction of records that cost
real money. It is now a usage error naming the two ways forward.

### 9. `--max-budget-usd`, and the nightly's failure modes

`--max-budget-usd` is a CLI argument (no `Settings` change): checked
*between* queries against accumulated workflow+judge spend, including
spend reused from a resumed campaign. On trip it stops cleanly, writes
everything, prints how many queries were skipped, and exits `5`. It is
a campaign ceiling, not a per-call one — a single query can overshoot
it by its own cost. Per-call enforcement is ADR 0051's.

In the workflow: a fail-fast first step that errors with an
owner-actionable message when `ANTHROPIC_API_KEY` is absent (the fix is
adding a repository secret, or disabling the schedule — not a code
change); `if: always()` on the locate + two upload steps and on the
diff, so a campaign that died at query 15 still uploads fourteen paid
records and still refreshes the baseline artifact; `requirements-lock.txt`
instead of `pip install -e ".[dev]"` so the nightly measures the same
dependency resolution CI gated (the lock-then-`--no-deps` pattern
ci.yml already uses, ADR 0045); and 120 minutes instead of 60, which is
what 20 queries at 2-4 minutes each actually needs.

Two guards follow from the new gate semantics. A manual `--queries`
dispatch passes `--allow-removed` to the diff — a subset run is
*meant* to omit queries — while the scheduled nightly never does, which
is exactly where a missing query means the batch died. And the README
block is patched on full runs only, since publishing a hand-picked
three-query subset as "3 / 3 queries" is the same claim-inflation this
ADR closes elsewhere.

Also closed here: the per-query `ExitStack` leak (one compiled graph per
query meant one leaked checkpointer connection per query — inert
against SQLite at benchmark size, a real drain against a Postgres
connection ceiling), and exception text in `summary.md` table cells is
now pipe-escaped, newline-collapsed and length-capped, since an SDK
error body containing a `|` corrupted the table from that row down.

### 10. What judge isolation costs the consumers, and how they say so

Decision 1 buys the campaign's survival with a new hole: a metric that
used to abort the run now goes `null`, and both consumers of
`summary.jsonl` average over whatever is left without saying so.
`readme_update._mean_or_none` skips nulls, so `Mean faithfulness 0.420`
can be the mean of two runs inside a row headed `20 / 20`;
`regression_diff` turns a null into a `None` delta, which is never a
regression, so the same night classifies every query `unchanged` and
exits `0`. That is decision 6's shrunken denominator one level down —
`metrics_error` was being written by the runner and read by nobody.

Both consumers now state their denominator:

- The README block names any metric whose mean covers fewer runs than
  the count in the row ("faithfulness over 2 of 20"), alongside the
  citation-accuracy exclusion from decision 5. The workflow-cost caveat
  is printed unconditionally; it used to ride inside the uncited-rows
  note and so vanished on a night where every report cited something.
- The diff report carries a `Compared` column per metric and, when the
  baseline scored something this run did not, a line naming the metric
  and the count.
- The runner's closing line adds `N partially scored`.

**Not gated.** A flaky judge is a harness fault, not a product
regression, and 20 queries make ~60 judge calls a night — gating on one
truncated JSON response would put the nightly back where this ADR found
it, red for reasons nobody acts on. The signal loss is reported at
three levels instead, and a *query* that produced nothing at all is
still `removed` or `errored` and still gates.

## Alternatives considered

- **Fail the whole batch on a judge error (status quo)** — the
  fail-fast option ADR 0008 already rejected for workflow errors. There
  is no argument for applying it to the *scoring* half that does not
  apply more strongly to the half that costs ten times as much.
- **Fail the gate when a metric goes unscored** — symmetric with the
  `removed` decision and rejected on frequency: a single truncated
  judge response out of ~60 a night would redden the nightly for a
  harness fault, which is the alarm fatigue this ADR is trying to end.
  Reported at three levels instead; see decision 10.
- **Retry the failed judge instead of degrading to `None`** — the SDK
  already retries (ADR 0009: 4 retries, exponential backoff). A second
  application-level retry loop doubles the worst-case latency of a
  nightly that already needs two hours, to rescue a metric whose
  absence the record now states plainly.
- **Rename `cost_usd` to `workflow_cost_usd`** — cleaner name,
  unacceptable failure mode: the gate would read `None` against every
  existing baseline and quietly stop policing cost. Rejected; see the
  naming call above.
- **Drop uncited rows from every metric, not just citation accuracy** —
  a report with no citations is still a real report with real
  completeness and recall. Only the citation metric is undefined on it.
- **Annotate rather than exclude the free 1.0s** — considered, and it
  is what the note under the table does *in addition*. Leaving them in
  the mean keeps a number that is wrong in a knowable direction, which
  is the kind of number that gets quoted.
- **Version the output directory automatically (`run-a`, `run-a.1`)
  instead of refusing it** — silently writing somewhere other than
  where the operator pointed is its own surprise. An error naming
  `--resume` teaches the flag; a silent redirect teaches nothing.
- **Put the budget ceiling in `Settings`** — the ceiling is a property
  of one campaign, not of the deployment, and the eval runner is the
  only caller. A CLI flag keeps it where it is decided.
- **Enforce the budget per call inside `call_llm`** — that is the right
  choke point for the *product* and it is ADR 0051's decision. Doing it
  here too would mean two ceilings with two behaviours on trip.
- **Parallelise the campaign to shrink the interrupt window** — the
  window is a symptom; ADR 0008's sequential choice stands on arXiv and
  Anthropic rate limits, and parallelism would make partial-failure
  accounting harder, not easier.

## Consequences

- **Positive**: a killed, cancelled, OOM'd or budget-stopped campaign
  keeps every query it finished, and `--resume` re-enters it without
  re-paying. A judge outage costs one metric, not the batch. The
  published cost figure and the regression gate describe the agent
  rather than the eval rig. A truncated batch, an empty report and a
  total outage are each now visibly red instead of green. The nightly's
  failure message names the owner action that fixes it.
- **Negative**: two extra file writes per query (negligible beside a
  multi-minute LLM run, but the output directory is now written
  throughout rather than once). `summary.jsonl` can hold duplicate
  lines *during* a resumed run until the end-of-run rebuild collapses
  them — a consumer reading it mid-campaign must tolerate that.
  Summaries older than this ADR are not comparable on `cost_usd`.
  `--resume` skips *errored* queries too, since their record file
  exists; retrying one means deleting its `queries/<id>.json` first.
  And the SIGTERM handler makes a `kill` unwind rather than die
  immediately, so a second signal may be needed to stop a wedged run.
- **Follow-ups**: `summary.md` is still only regenerated at the end, so
  a SIGKILL leaves it stale beside a current `summary.jsonl`. The
  budget ceiling cannot stop a query already in flight. Nothing yet
  re-derives the regression thresholds from measured run-to-run spread
  — ADR 0044's open follow-up, unchanged. And the nightly's missing
  `ANTHROPIC_API_KEY` is now *legible*, not fixed: funding the campaign
  remains an owner action.
