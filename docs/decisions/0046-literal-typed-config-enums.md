# 0046. Literal-typed enum settings + coverage for the untested control paths

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0011](0011-pydantic-settings-typed-config.md) (typed config surface)

## Context

The audit found a cluster of "silent fallback" hazards rooted in one
config-surface decision: every settings field that selects one of a
closed set of implementations was typed as a bare `str`:

- `job_store` (`memory` / `redis`)
- `conversation_store` (`memory` / `postgres`)
- `checkpoint_backend` (`sqlite` / `postgres`)
- `rate_limit_backend` (`memory` / `redis`)
- `paper_cache` (`disk` / `postgres`)
- `embedding_cache` (`none` / `postgres`)
- `log_level` (standard library level names)

Selection then happened downstream with `if settings.job_store ==
"redis": ... else: <fallback>`. A typo'd env var — `JOB_STORE=Redis`,
`PAPER_CACHE=postgress` — passed validation and silently selected the
fallback branch. The worst case is real: an operator who believes
they configured the Redis job store gets the in-memory store, jobs
die on restart, SSE breaks under multi-worker, and nothing in the
logs says "your env var was wrong". Only `checkpoint_backend` and
`rate_limit_backend` had a downstream raise-on-unknown; the other
four fell back quietly.

The same audit pass flagged five behavioural gaps where a load-bearing
control path had no test at all, so the suite stayed green under
mutations that break production behaviour:

1. No test drove `POST /research` past the hourly limit to a real
   HTTP 429.
2. No route-level test pinned that `principal_key_id` is stamped on
   jobs at submit — ownership on conversations was covered, jobs were
   not.
3. `run_job`'s `CostBudgetExceeded` and `TimeoutError` handlers had
   zero coverage.
4. Nothing pinned that a real `run_job` publishes its terminal SSE
   frame over Redis pub/sub — the existing ADR-0035 tests drove
   `publish_event` directly, bypassing the runner.
5. The hot-reload keystore and CORS wiring were never exercised
   through `create_app`.

Both clusters are one theme — configuration and control-flow paths
whose failure mode is silence — so they land together.

## Decision

### 1. Enum-valued settings are `Literal[...]`, never bare `str`

Every field above becomes a `Literal` of its documented values.
pydantic then rejects an unrecognized value at settings load with a
message that names the field and the accepted values
(`Input should be 'memory' or 'redis'`), before any traffic is
served. This is the project-wide convention going forward: a new
settings field with a closed value set MUST be `Literal`-typed.

`log_level` keeps its historical case-insensitivity via a
`mode="before"` validator that uppercases the input — `LOG_LEVEL=debug`
predates the Literal type and must keep booting.

Free-form fields (model IDs, URLs, file paths, key material) stay
`str`: their value sets are open.

### 2. The five missing tests

Each gap gets a test that was mutation-checked — the guarded
behaviour was broken by hand, the new test failed, the behaviour was
restored:

- `tests/test_api_auth.py` — drives `POST /research` past
  `api_key_hourly_limit=2` through the real app and asserts the 429
  body, the `Retry-After` header, and that read routes stay
  unthrottled. Also boots `create_app` with `api_keys_file` (initial
  load + on-disk rotation propagating without restart) and with
  `api_cors_allow_origins` (grant for listed origins, nothing for
  others, no middleware by default).
- `tests/test_per_principal_scoping.py` — principal A submits a job;
  B's GET / stream / review / export all 404; A's own requests
  succeed. The positive assertions are the mutation kill: dropping
  the `principal_key_id` stamp makes A's job invisible to A under
  auth-on.
- `tests/test_runner_cost_cap.py` — drives `run_job` with a stub
  workflow that overspends the cap (via the run's real cost
  accumulator) and one that hangs past `timeout_sec`; asserts status
  transitions, `error_type` values, and the exact terminal-frame
  payload. Assertions are behavioural only, so the tests survive the
  in-flight runner refactor.
- `tests/test_sse_cross_worker.py` — a real `run_job` against a
  RedisJobStore, with a subscriber on a second store instance;
  asserts the full frame sequence arrives, the terminal
  `job_completed` payload carries the documented fields, and the
  local queue stays empty.

## Alternatives considered

- **`StrEnum` classes per field** — same load-time validation, but
  every comparison site would need `settings.job_store ==
  JobStoreKind.redis` or rely on str-subclass equality; `Literal` is
  zero-migration (values are plain `str`, all existing `== "redis"`
  comparisons and log emissions are untouched) and pydantic's error
  message is better out of the box.
- **Downstream raise-on-unknown everywhere** — the pattern
  `workflow.py` already used for `checkpoint_backend`. Rejected as
  the primary defense: it fires at first use (possibly mid-request,
  possibly never on a code path not exercised), not at boot, and it
  must be re-implemented at every selection site.
- **Custom `field_validator` per field** — strictly more code than a
  `Literal` annotation for the same behaviour.

## Consequences

- **Positive**: misconfiguration dies at process start with the field
  name in the message — under the compose stack the container
  crash-loops visibly instead of running with the wrong backend. The
  five most safety-relevant control paths in the API layer are now
  pinned by behaviour-level tests.
- **Positive**: the downstream unknown-value fallback branches
  (`_default_store`'s memory fallback, `get_paper_cache` /
  `get_embedding_cache` defaults, `build_rate_limiter`'s
  `ValueError`, `_build_checkpointer`'s raise) are now unreachable
  via settings. They stay in place as cheap defense-in-depth for
  direct callers that bypass `settings`, and because removing them
  is other lanes' code.
- **Negative**: values are now case-sensitive except `log_level`. An
  env that previously "worked" by silently falling back (e.g.
  `JOB_STORE=Redis` behaving as `memory`) now refuses to boot — that
  is the point, but it is a behaviour change for broken configs.
- **Follow-ups**: none tracked; new enum-like fields adopt the
  convention as they land.
