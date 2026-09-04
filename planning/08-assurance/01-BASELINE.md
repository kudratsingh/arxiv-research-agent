# Phase A baseline — what is actually true on `0caefa2`

Status: **MEASURED 2026-09-04**

Method: four independent read-only recon passes over `main` (error handling,
test architecture, evaluation, observability), each required to cite
`file:line` and to verify by reading code rather than inferring from a
filename. Local suite run for the headline number. Nothing in this page is a
projection; where a claim is a judgement call it says so.

Read this page before any work order. Phase A's value is entirely in closing
the specific distances recorded here, and several of them are *not* where a
reasonable person would guess.

## 0. Headline

```
pytest -m "not e2e" -q   →  2042 passed, 52 skipped in 35.22s
```

That is a genuinely strong suite by line count and it is the reason this
phase is about *proof*, not *volume*. The gaps below are almost all
structural: things the suite cannot detect no matter how many more tests of
the current kind are added to it.

## 1. What is already good, and must not regress

Phase A is a hardening phase on a codebase that has already done real work.
Naming the strengths matters, because several work orders are forbidden from
touching them.

- **LLM retry envelope** (`src/llm.py:62-91`). `(max_retries+1)*timeout` is
  clamped to 75% of the job timeout, and the clamp logs a WARNING when it
  bites. This is better than most production code and is the model the rest
  of the phase copies.
- **Cooperative cancellation** (`src/cancellation.py`, `graph/workflow.py:307-310`).
  Register-before-check ordering is deliberate and correct; drain holds the
  semaphore permit until threads return, then `abandon()` counts zombies into
  `/healthz`.
- **Graceful degradation is designed, not accidental** — cache miss on
  failure (`pdf_parser.py:305-313`), abstract-only reader fallback
  (`reader.py:151-160`), supervisor/verifier/refiner/assessment fallbacks,
  partial report preserved on budget exhaustion (`runner.py:1710`).
- **Cost enforcement** — `>=` pre-call check (`llm.py:148`), per-run
  `RunCosts`, price-table coverage test (`test_observability.py:239`).
- **Metric cardinality discipline** — `key_id` is deliberately excluded from
  attributes (`metrics.py:521`, `auth.py:161`).
- **Broad handlers are not silent.** ~50 `except Exception` sites, and every
  one logs at WARNING or ERROR with `exc_info`. The problem in §2 is their
  *typing*, not their silence.
- **The per-PR zero-spend eval lane works and gates.** `ci.yml:186-196` runs
  all 15 learning scenarios through the real compiled session graph in mock
  mode, then asserts 15 rows, `$0.0000`, zero call counts and zero unmet
  expectations. It is the only part of the eval system that has ever gated
  anything, and it is a good design.

## 2. Error handling — the shape of the gap

- **No exception hierarchy.** 13 custom classes, each inheriting directly
  from `Exception`/`RuntimeError`/`ValueError`, against **122 `raise
  ValueError`**. No `src/errors.py`. A caller cannot write `except AppError`,
  and nothing carries a stable machine code.
- **No FastAPI exception handlers exist at all.** `create_app`
  (`src/api/app.py:635-642`) registers none; grep for `exception_handler`
  across `src/` returns nothing. Any unhandled exception becomes an untyped
  Starlette 500 with no structured body and no ERROR log on that path.
- **Raw exception text reaches API clients.** `runner.py:1832-1834` sets
  `job.error = f"{type(exc).__name__}: {exc}"`, surfaced through
  `schemas.py:132` → `routes.py:139` and the SSE terminal frame
  (`routes.py:1267`). psycopg/redis/httpx messages embed DSNs, hostnames and
  paths; length is unbounded.
- **`error_type` is `type(exc).__name__`** — an internal class name used both
  as an API field and as a metric attribute (`runner.py:1834`,
  `metrics.py:431`). Renaming a class silently breaks client branching and
  forks a metric series.
- **Three inconsistent error shapes** ship today: `{"detail": "job_not_found"}`,
  the structured 429 (`auth.py:174-183`), and FastAPI's validation array.
- **No circuit breaker anywhere.** During an upstream outage every job pays
  the full retry envelope before failing.
- **Redis client has no socket or connect timeout and no health check**
  (`redis_store.py:1042-1048`). `app.py:435` already patches around this with
  a `wait_for` at one call site, which is the tell.
- **The rate limiter 500s on a Redis outage** (`auth.py:274-279` unguarded
  `pipe.execute()`), which combined with the missing handlers means a Redis
  blip returns opaque 500s to every submit.
- **`agents/search.py:202` blocks a node thread with `time.sleep(3)`** per
  query and never calls `check_cancelled()` in that loop, so a cancelled job
  can burn its 30s drain window on pacing alone.
- **arXiv timeout is a hardcoded `timeout=30`** (`arxiv_search.py:93`) — the
  one un-tunable timeout in a codebase that centralizes every other knob —
  and the HTTP retry budget is never clamped against the job budget
  (`http_session.py:57-64`, `respect_retry_after_header=True`, no
  `backoff_max`), unlike the LLM envelope which does clamp.
- **Reader honesty stops at the log.** `n_abstract_only` is tallied
  (`reader.py:899-921`) and logged, but the state summary
  (`reader.py:842-846`) does not carry it, so a run where most papers were
  abstract-only produces a confident report with no marker — contradicting
  the module's own stated intent at `reader.py:45-49`.

## 3. Testing — the shape of the gap

98 test files, ~1,944 `def test_` functions, flat layout.

- **No `tests/conftest.py` anywhere in the repository.** Verified by `find`.
  Consequences follow from this single absence:
  - **No env isolation.** `src/config.py:53` sets `env_file=".env"`, a real
    `.env` exists at the repo root, and 30+ files construct a bare
    `Settings()`. A developer's local settings silently change test outcomes.
  - **No network guard.** Only `test_pdf_parser.py:215-322` touches sockets,
    and only to test SSRF. Nothing prevents an un-patched agent test from
    reaching arxiv.org or api.anthropic.com.
  - **No spend guard** beyond two `src.llm._get_client` patches
    (`test_simulate_learner.py:107`, `test_record_learning_fixtures.py:92`).
  - **No clock or seed control.** No `freezegun`/`time-machine`; `random.seed`
    appears zero times.
- **LLM fakes are per-module monkeypatches, not one seam.**
  `test_api_smoke_e2e.py:97` says so outright. `test_llm.py` carries 79
  `monkeypatch` calls, `test_supervisor.py` 75, `test_simulate_learner.py` 70.
  A renamed import silently reverts a test to the real client.
- **Python coverage is never measured.** No `pytest-cov`/`coverage` in
  `pyproject.toml`, the lock, the `Makefile` or CI. The web half, by
  contrast, enforces statements 98.15 / branches 94.0 / functions 88.8 /
  lines 99.11 (`web/vitest.config.mts`, `ci.yml:475`). The asymmetry is the
  finding.
- **38 of 98 files carry no tier marker**, so `make test` (`-m unit`) runs
  roughly half the suite and looks green. `docs/testing.md` already calls
  this a "known trap".
- **No `--strict-markers`, no `--strict-config`, no `xfail_strict`, no
  per-test timeout, no random ordering.** A typo'd `@pytest.mark.uni` never
  runs and never complains.
- **The `e2e` marker has zero members** while the `Makefile` target, the CI
  filter `-m "not e2e"` and `docs/testing.md` all reference it. The agent's
  full-workflow behaviour has no end-to-end test.
- **Zero property-based, fuzz, or mutation testing.** No `hypothesis`,
  `schemathesis`, `mutmut`, or `atheris` in any file. There are 24
  "Mutation-check:" *docstring notes* across 17 files — a convention that
  decays silently the moment the code moves.
- **`src/agents/assessment.py` has no test that imports it.** It is the judge
  that scores learner mastery.
- **No flake policy on the Python side** — no rerun plugin, no quarantine
  marker, no `xfail`.

## 4. Evaluation — the shape of the gap

Split deliberately into what costs nothing to fix and what does not.

**Zero-spend defects (all fixable this phase):**

- **Judges are not pinned.** `metrics.py:283,546,731` pass no model, so
  `llm.py:217` falls through to `settings.anthropic_model`. Upgrading the
  product model silently changes the judge — the system grades itself with a
  moving ruler.
- **No model id, rubric version, or code commit is recorded in any summary
  row** (`runner.py:441-467`, `simulate_learner.py:1027-1060`). A regression
  diff cannot distinguish a quality change from a model swap.
- **No rubric versioning.** `COMPLETENESS_SYSTEM_PROMPT` (`metrics.py:151`)
  and peers carry no version constant; a prompt edit silently rebaselines
  every metric.
- **`critic_score` gates the nightly and is the product grading itself**
  (`regression_diff.py:84-92`, `critic.py:140`), and `critic.py:386` coerces
  an unparseable response to `0.0`, which reads as a full-scale regression.
- **No variance, N, or confidence anywhere.** `regression_diff.py:504`
  compares exactly two records. `docs/eval.md:445` ("The statistics,
  honestly") already admits this.
- **`--repeats` exists on the learning lane but produces `r1/r2/r3` record
  ids that the diff compares pairwise rather than aggregating**
  (`simulate_learner.py:829`), so three repeats cost triple and still yield
  three single-run comparisons. The research lane has **no `--repeats` flag
  at all** (`runner.py:771`), while `REPEATS_FOR_CONFIDENCE = 3` is
  advertised (`simulate_learner.py:167`).
- **`citation_accuracy` returns 1.0 for a report with zero citations**
  (`metrics.py:85`). The metric rewards the failure mode it exists to catch;
  only the README mean compensates, not the gate.
- **The score epsilon is inoperative for two of four research metrics** —
  completeness and recall quantize at 0.20–0.25 against a ±0.10 band
  (`regression_diff.py:76-80`), so one flipped judge decision is a guaranteed
  red.
- **Injection containment is a literal-canary substring test on 2 of 15
  scenarios** (`learning_benchmark.py:910,1095`). A model that *obeys* an
  injection while paraphrasing the canary scores as contained.
- **No red-team corpus and no attack-success-rate.**
  `security/prompt_isolation.py:83` is five regexes tested against ~6
  synthetic payloads.
- **The pedagogy deny-list fails pytest but never appears in
  `summary.jsonl`** (`simulate_learner.py:638` scans only the 8-phrase shame
  lexicon), so a pedagogy violation is invisible to the campaign gate.
- **No dataset provenance.** The `BenchmarkQuery` TypedDict
  (`benchmark_queries.py:20`) has no license, author, or date field, and one
  query is annotated "Well-covered by the built-in mock papers" — scoring
  retrieval recall against papers hand-picked to match.

**Requires paid calls (out of scope, recorded for the owner):** judge–human
agreement is unmeasured on all four research metrics; the nightly research
lane has failed 54/54 runs and no CI `summary.jsonl` has ever existed; the
regression gate has never compared two real runs; the explain-back
calibration set is synthetic and `owner_ratified: false`.

## 5. Logging and observability — the shape of the gap

- **Exactly one ContextVar: `_run_id`** (`logging.py:70`). No request id, no
  trace id, no span id, no principal, no worker id, no service name, no
  version. Log-to-trace correlation is impossible.
- **No trace context crosses API → queued job → worker → LLM.**
  `tracing.py:110` is the only `start_as_current_span`, and `inject`/`extract`
  appear nowhere in `src/`. A job is N disconnected root spans.
- **LLM calls are not spans at all** (`llm.py:270` records a call but opens no
  span). The largest latency contributor is invisible to tracing.
- **Zero `gen_ai.*` attributes.** Names are `llm_calls_total`,
  `llm_cost_usd_total`, `llm.cost_usd`. No off-the-shelf GenAI dashboard or
  vendor cost view will parse this repository's telemetry.
- **No HTTP server RED metrics.** The only request-path instrument is
  `rate_limit_rejections_total`; `app.py:649` adds CORS and nothing else. API
  availability and latency cannot be measured, so no SLO can exist.
- **`JsonFormatter` copies every `extra` verbatim with no allowlist and no
  size cap** (`logging.py:120-123`), and callers log raw user queries
  (`routes.py:232`) and, on a store failure, whole report bodies
  (`runner.py:1046-1049`).
- **Redaction is one rule with one call site** — `redact_url`
  (`logging.py:256-284`) used at `postgres_pool.py:354`. Nothing covers API
  keys, learner text, prompts, or paper content.
- **`degraded_close` sessions record `status="succeeded", error_type="none"`**
  (`runner.py:1652-1656`), so budget exhaustion is indistinguishable from
  success in metrics.
- **Job metrics carry no `kind`**, so research and learning-session jobs share
  one series and session SLOs cannot be built.
- **Metrics only exist inside API workers** — `configure_metrics()`'s sole
  caller is `app.py:379`, so CLI and eval runs emit nothing.
- **`/healthz` always returns HTTP 200**, including when `status: degraded`
  (`routes.py:1177-1211`). There is no `/readyz`, so an orchestrator cannot
  drain a worker whose Redis is dead.
- **No tracer flush on shutdown** (`tracing.py` has no `shutdown`), so the
  last `BatchSpanProcessor` window is lost on every SIGTERM — precisely when
  failures happen.
- **No collector, dashboards, alert rules, SLOs, or incident runbooks.**
  `docs/runbooks/` contains only `pilot.md`. ADR 0049 already concedes the
  collector gap.
- **Price-table staleness is enforced by a hand-edited string**,
  `PRICES_LAST_VERIFIED = "2026-08-20"` (`costs.py:53`), with no test that
  fails on age.

## 6. What the baseline implies for sequencing

Three findings drive the wave order in [`04-WORK-ORDERS.md`](04-WORK-ORDERS.md):

1. **The missing `conftest.py` is upstream of almost everything.** Property
   tests, fault injection and an e2e tier all need a harness that cannot
   reach the network or a real key. It is the first merge of the phase.
2. **The missing error taxonomy is upstream of the API envelope, the metric
   attribute enum, and the log allowlist.** Three later work orders consume
   `AppError.code`, so it lands in the same wave as the harness and before
   they start.
3. **Everything else is genuinely parallel.** Evaluation integrity,
   telemetry conventions, resilience policy and the adversarial corpus touch
   disjoint files and can run concurrently once the two foundations exist.
