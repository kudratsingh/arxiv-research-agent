# 0081. Count degradations on a closed rung vocabulary, and make the quality SLI computable

- **Status**: accepted
- **Date**: 2026-09-05
- **Deciders**: assurance lane (WO-D5), under a one-PR fence exception for `src/observability/**` granted on the coordination board

## Context

`docs/reliability.md` builds every objective it declares on one SLI, and
it chose that SLI deliberately. There is no credible published
methodology for LLM quality error budgets — the 2026 "AI agent SLO"
literature publishes thresholds with no derivation, no denominator and
no statement of the population measured — so the document reached for
something older and duller instead: the SRE Workbook's **quality** SLI,
*the proportion of responses served in an undegraded state*. Once
quality is expressed as good events over valid events, error budgets,
burn rates and the multiwindow alerting tables apply to it unmodified,
with no new theory and no vendor.

§5 then defines the eight-rung degradation ladder — cached/stale with a
disclosed age → reduced-tool mode → partial results with confidence →
streaming partials → model fallback → bounded queue → honest refusal —
and states the rule that makes the whole construction work:

> **Every rung must emit a distinct marker.** Otherwise degradation
> makes the dashboard look better while the product gets worse.

**Six of the eight rungs emitted only a log line.** `record_degradation`
in `src/resilience.py` kept an in-process `collections.Counter` and
wrote a `resilience_degraded` WARNING; no OpenTelemetry instrument
counted any of it. ADR 0068 recorded the fold-in as a named follow-up
rather than editing a peer work order's file mid-wave, and it stayed a
follow-up through two more waves. So the anchor metric of the whole
reliability document could not be computed, §3 had no quality row at
all, and §7's first entry — the largest gap in the document — was this.

The failure that produces is not hypothetical, and §5 names the
instance: when the reader falls back to abstract-only, the report ships,
the job-success SLI stays green, `research_job_duration_seconds`
*improves* because reading an abstract is faster than reading a paper,
and nobody is told the analysis was made from abstracts. Every
instrument moves in the reassuring direction while the product gets
worse. That is the exact shape of failure an instrument is supposed to
prevent, and no instrument could see it.

Two constraints shaped the answer. `src/observability/**` belongs to
another lane and this work held a **one-PR exception** for it, so the
edit there had to be additive and small. `src/agents/**` and
`src/graph/**` belong to the capability lane and no exception covered
them at all — and three of the eight rungs have all their call sites
inside `src/agents/`.

## Decision

**One counter, `research_degradations_total`, with two closed-set
attributes: `{rung, component}`.**

### The rung vocabulary is closed

`DEGRADATION_RUNGS` and `DEGRADATION_COMPONENTS` are `frozenset`
constants in `src/observability/metrics.py`, one value per rung of §5's
published ladder plus an `unregistered` overflow bucket. This is the
**third** closed vocabulary in this repository, and it is closed for the
two reasons the earlier two give:

- `ERROR_CODES` (ADR 0064) is closed because "an open string used as a
  metric attribute is unbounded cardinality". A metric attribute mints
  one time series per distinct value, permanently — this is the same
  reason `key_id` is deliberately excluded from metric attributes (ADR
  0049) even though the 429's log line carries it.
- `KNOWN_EVENTS` (ADR 0067) is closed so "a dashboard, an alert rule and
  a runbook can name an event and be told when the code stops emitting
  it under that name". That reason is *sharper* here than it was there:
  a panel querying a rung nobody emits renders a flat zero, and a flat
  zero on a **quality** panel reads as an undegraded fleet.

The repository has now made this call three times on the same reasoning,
and the precedent should hold.

`tests/test_degradation_ladder.py` enforces it. The check is **static**:
`src/` is parsed and every literal or named constant passed as `rung=` /
`component=` is looked up in the frozen set. Parsing the code rather
than comparing two fixtures is the distinction `tests/test_log_contract.py`
draws — a fixture only proves the fixture and the constant agree, while
a parse proves the *call sites* and the constant agree, which is the
invariant that matters when somebody adds a rung. An argument the parse
cannot resolve to a constant — an f-string, a variable — is itself a
failure, because that is exactly the shape an unbounded attribute
arrives in.

At runtime an unregistered value is recorded under `unregistered` and
logged as `degradation_rung_unregistered`, rather than passed through or
raised. Passing it through would mint the series the closed set exists
to prevent; raising would turn an observability bug into a job failure
at a call site whose entire purpose is surviving a failure. The static
check is the enforcement; the bucket is the containment. This is the
same trade `logging.py` makes with `FIELD_UNREGISTERED_EVENT`.

### `reason` is not an attribute

`docs/reliability.md` §7 sketched the instrument as `{component,reason}`,
matching `record_degradation`'s existing signature. It shipped as
`{rung,component}`, and `reason` stays a log field.

A reason is a specific machine token (`redis_unavailable`) whose whole
value is being specific, which makes it right for a log line and wrong
for a metric attribute — the same split `record_rate_limit_rejection`
already makes for `key_id`: "the metric answers how much and where, the
log answers why". The rung is what the SLI is computed from and what a
runbook is written against; the reason is what an operator greps for
once the panel has told them where to look.

### The rungs are counted at their own sites, not folded onto one event

The obvious reading of §7 was to route every rung through
`resilience.record_degradation`, which already logs and counts. That is
wrong, and the reason is concrete rather than aesthetic:
`deploy/observability/log-alerts.yml` pages at **threshold 1 in 15
minutes** on `resilience_degraded`, because today its only emitter is
the rate limiter losing Redis. Routing a Postgres cache blip through
that event would wake somebody at three in the morning for a rung that
is working exactly as designed.

So `record_degradation` gains the metric (and a required `rung`), and
the other rungs call the metric helper `record_degradation_rung`
directly, keeping their own distinct log events. §5's rule — every rung
emits a *distinct* marker — is preserved rather than collapsed.

`rung` is a **required** keyword on `record_degradation` rather than a
defaulted one. The only possible default is `weakened_guarantee`, the
rung of the only caller on this branch, so the next caller degrading
down a different rung would be counted under the wrong one with no
signal at all — "degradation makes the dashboard look better"
reintroduced one layer above the function that exists to prevent it.

### The instrument lives beside `research_jobs_total`, not in a new module

`metrics.py` holds every synchronous instrument in one frozen
`_Instruments` bundle behind a single module global, so each record
helper does one load and one `None` check on the hot path, and
`shutdown_metrics` re-arms the disabled path with a single assignment
rather than leaving half the instruments live. A separate module would
be a second provider lifecycle to configure, flush and disarm — and the
failure mode is asymmetric: a bundle left armed after shutdown records
into a dying pipeline, which is precisely the race the single-assignment
design was built to close. The counter is also an attribute-vocabulary
neighbour of `NO_ERROR` and `STATUS_DEGRADED_CLOSE`, which already live
there for the same reason.

### Which rungs are instrumented

| Rung | Token | State |
|---|---|---|
| 1. Cached / stale | `cache_stale` | **Instrumented** — `src/tools/pdf_parser.py`, `src/tools/embeddings.py` |
| 2. Reduced tool | `reduced_tool` | Not instrumented — `src/agents/search.py`, capability lane |
| 3. Partial with confidence | `partial_results` | Not instrumented — `src/agents/reader.py`, capability lane |
| 4. Streaming partials | `streaming_partial` | **Instrumented** — `src/api/streaming.py` |
| 5. Model fallback | `model_fallback` | Not instrumented — four files in `src/agents/`, capability lane |
| 6. Bounded queue | `bounded_queue` | Already metered, on its own gauges (ADR 0049) |
| 6b. Weakened guarantee | `weakened_guarantee` | **Instrumented** — `src/resilience.py` via `src/api/auth.py` |
| 7. Honest refusal | `refusal` | Already metered, on `rate_limit_rejections_total` and `research_jobs_total` |

Rungs 6 and 7 are **deliberately not also counted here**. A second
counter at a site that already has one can disagree with the first about
a single event — `metrics.py` declines to instrument the semaphore for
exactly that reason, to keep a gauge from contradicting `/healthz`. The
price is that a complete quality query sums three instruments instead of
one, which §3's Quality row writes out rather than hides.

Rungs 2, 3 and 5 are uninstrumented because a fence, not a design,
stopped them: every one of their call sites is in another lane's files,
and an honest five-of-eight beats a fence breach.
`tests/test_degradation_ladder.py` pins exactly which three, with the
owning lane and file named, and asserts the set in **both** directions —
so wiring the reader turns the suite red until the declaration and
`docs/reliability.md` §5's column are corrected. The gap closes itself
rather than waiting to be remembered, which is the difference between
this and the two waves ADR 0068's follow-up spent unclosed.

## Alternatives considered

- **Fold every rung onto `resilience_degraded`, as §7 sketched** — the
  smallest diff, and it pages on cache misses. `log-alerts.yml` sets
  threshold 1 / 15m / severity `page` on that event on the assumption
  that its only emitter is the rate limiter losing Redis. Rejected: it
  would have converted the most routine rung of the ladder into an
  out-of-hours page, and the fix would then have been to raise the
  threshold, which would have degraded the alert that was working.
- **An open `rung` string** — no vocabulary to maintain. Rejected on the
  precedent this repository has already set twice, on the cardinality
  argument in ADR 0064 and the silent-rot argument in ADR 0067, both of
  which apply here without modification.
- **Keep `{component,reason}` as §7 specified** — faithful to the
  written plan. Rejected because `reason` is unbounded in practice: it
  is the free half of the pair, the half that gets a new value every
  time a new failure mode is handled, and a metric attribute is the one
  place where that is expensive rather than merely untidy. §7's sketch
  was written before `record_degradation` had callers beyond the rate
  limiter; the document is updated to say so.
- **Raise on an unregistered rung** — strongest enforcement. Rejected:
  every call site is on a failure path whose contract is to survive, and
  a helper that raised there would convert an observability bug into a
  job failure. The static test enforces; the runtime contains.
- **A separate `src/observability/degradations.py`** — smaller edit to a
  fenced file. Rejected: a second provider lifecycle that
  `shutdown_metrics` does not disarm is a bundle that keeps recording
  into a torn-down pipeline, and the whole point of the single frozen
  bundle is that one assignment disarms everything.
- **Instrument rungs 2, 3 and 5 anyway** — would have made the SLI
  complete. Rejected: the files belong to the capability lane and no
  exception covered them. A complete number obtained by a fence breach
  is worth less than an incomplete one that says so.

## Consequences

- **Positive**: the quality SLI is computable, and
  `docs/reliability.md` §3 carries a Quality row for the first time —
  §4's burn-rate machinery applies to it unchanged, exactly as §2
  predicted it would. Five of eight rungs are on a metric where two
  were.
- **Positive, and this is the whole argument for a separate counter**:
  **a degraded run succeeds.** `research_jobs_total{status="succeeded"}`
  is the *correct* answer for it and is useless for seeing it, and
  `research_job_duration_seconds` moves in the reassuring direction
  because a degraded path is a faster path. So no existing instrument
  could ever have measured quality, however it was queried — this is
  the first instrument in the fault tier's `LIVE_INSTRUMENTS` that
  measures a **success**. Every other one measures a failure, which is
  why the tier's triple — code, event, metric — could only ever supply
  two thirds for these faults, and why the missing third was structural
  rather than an oversight. `test_resilience_faults.py` had held a
  `skip` open since WO-A06 whose docstring specified this exact
  counter, including that it must stay separate from
  `rate_limit_rejections_total`; that decorator is now deleted and the
  assertion made.
- **Negative**: the SLI is a **lower bound**. Three rungs are missing
  from it, and one of them — the reader's abstract-only fallback — is
  likely not rare. An objective computed from a lower bound cannot be
  missed by the amount it is wrong, and §3 says so on the row rather
  than in a footnote.
- **Negative**: a quality query spans three instruments, because rungs 6
  and 7 keep their own counters. Written out in §3 as PromQL.
- **Negative**: one more closed set to maintain. Adding a rung now means
  a constant, a ladder row and a test update. That is the cost the two
  previous closed sets also pay, and it is the reason those sets have
  not rotted.
- **Cardinality**: bounded by construction at 9 rungs × 5 components =
  45 series, against 4 actually emitted (one per instrumented call
  site), because each component belongs to exactly one rung in practice.
  Nothing operator-supplied, nothing derived from an exception, no
  `key_id`.
- **Watched from the first commit.** `_UNWATCHED_INSTRUMENTS` in
  `tests/test_operability_docs.py` stays empty. An instrument that
  exists specifically to make the quality SLI computable has to be on a
  rule and a panel in the same change that creates it; parking it on the
  escape hatch would have been scheduling work already intended, which
  is not what that list is for. So `alerts.yml` gains a `quality` group
  — `QualityBudgetBurnFast` (14.4x the 3% budget, with the same
  small-denominator floor the other burn rules carry) and
  `CacheTierDegradedSustained` — and `dashboard.json` gains a Quality
  row with two panels.
- **Follow-ups**: (1) the capability lane wires rungs 2, 3 and 5 — the
  test names the files and fails when they land, and
  `docs/reliability.md` §5's column and the alert group's "lower bound"
  caveat both have to be corrected at the same time; (2)
  `docs/reliability.md` §5 row 1 still discloses no cache age to the
  user, which remains a product change and not this ADR's; (3) an eval
  campaign still installs no meter provider (§7 item 6), so a rung taken
  under `make eval` is a real degradation counted nowhere — that matters
  more for this instrument than for the server-shaped ones; (4) the SLI
  is a rate rather than a proportion, because this counter counts rungs
  and one job can take several. Turning it into the good-events /
  valid-events form every other row on §3 uses needs a per-job degraded
  flag on the terminal record, not a change to this instrument. Recorded
  as §7 item 9.
