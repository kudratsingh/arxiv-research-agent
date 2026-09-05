# Local development

Everything a contributor needs to get productive on the repo. If you're
reading this before writing code, you're doing it right.

## Prerequisites

- **Python 3.11+** — this repo is developed against 3.14 (pinned in
  `.python-version` for `pyenv` / `uv` users). Anything 3.11+ works,
  but stick close to the pin to avoid subtle stdlib differences.
- **Git** and **GitHub CLI** (`gh`) for the PR workflow.
- **Homebrew** on macOS or your distro's Python packages on Linux.

## First-time setup

```bash
git clone git@github.com:kudratsingh/arxiv-research-agent.git
cd arxiv-research-agent
make install-dev
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

`make install-dev` creates a fresh `.venv/` and installs the package
plus dev dependencies (`pytest`, `mypy`). It's idempotent — run it
again any time deps change.

### Four settings are secrets, and they read differently

Every field in `src/config.py` is a plain typed value except four:
`anthropic_api_key` (WO-C4), `log_principal_salt` (WO-C3), and
`api_keys` and `semantic_scholar_api_key` (WO-D3). All four are
`pydantic.SecretStr`, so reading one takes an extra call:

```python
from src.config import settings

client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key.get_secret_value(),  # not the field
)
```

Three things follow, and the second is the one that bites.

1. **They cannot leak into text.** `repr(settings)`, `str(settings)`,
   an f-string, `model_dump()`, `model_dump(mode="json")` and
   `model_dump_json()` all render `**********`. pydantic prints every
   field in a repr, so before this a `print(settings)` in a debugger,
   or a `-vv` assertion diff on a test that built a `Settings`, put the
   live credential in the clear. `src/observability/logging.py`'s
   `redact_text` also scrubs `sk-…` shapes on the way into the log
   stream, but that is a *shape* rule — it does not fire on a gateway
   or proxy key, on an S2 key (which carries no prefix at all), or on
   an operator-chosen inbound key, and it only sees text that reached
   the JSON formatter.

2. **Comparing one to a string is always `False`.**
   `settings.anthropic_api_key == "local-preview-disabled"` is `False`
   for the sentinel *and* for a real key, so a guard written that way
   stops guarding and says nothing. Call `get_secret_value()` first;
   `tests/test_config.py::TestTheApiKeyIsASecret` pins the trap, and
   `TestTheInboundKeystoreIsASecret` pins it again on the path where
   it decides who gets in.

3. **Unwrap once, at the point of use.** Never let the wrapper itself
   reach a string: an f-string of a `SecretStr` interpolates the mask,
   which would authenticate as `**********` (a key), salt the whole
   fleet with `**********` (the salt), or send `**********` to
   Semantic Scholar, which answers 403 and leaves enrichment silently
   empty. There are exactly four unwrap sites in `src/`, one per
   field: `src/llm.py`'s `_get_client`,
   `src/observability/context.py`'s `_resolve_salt`,
   `src/api/auth.py`'s `parse_api_keys` and
   `src/tools/semantic_scholar.py`'s `_headers`. `parse_api_keys`
   takes a `SecretStr` parameter rather than a `str` so mypy keeps it
   that way — unwrapping at its call site in `create_app` would put
   every inbound secret in a startup frame.

A blank value means *unset* for all four — `ANTHROPIC_API_KEY=`, or a
whitespace-only value, takes the "not configured" branch rather than
becoming a credential that earns you a 401. For
`SEMANTIC_SCHOLAR_API_KEY` that branch is the anonymous rate limit;
for `API_KEYS` it is "the string is not the keystore", which is how
`deploy/pilot/compose.pilot.yml` says the *file* is.

One rule the type cannot enforce: an error message is an output path
too. `parse_api_keys` reports a malformed entry by position and never
quotes it, because an entry with no `name:secret` separator is by
definition a bare secret and that `ValueError` is raised during
`create_app`, where it lands in a startup log.

`tests/property/test_property_secret_config.py` generalises all of
this: it reads the `SecretStr` fields off `Settings.model_fields`, so
the fifth secret is covered the day it lands rather than the day
somebody remembers to copy a test class.

## Common commands

All targets are documented by `make help`. The ones you'll use daily:

| Target | What it does |
|---|---|
| `make install-dev` | Fresh venv + runtime + dev deps |
| `make test` | Tests tagged `unit` only — see Troubleshooting; not the merge gate |
| `make test-unit` | Same as `make test` (explicit) |
| `make test-integration` | Integration tier (external libs, fixtures) |
| `make test-e2e` | E2E tier (whole workflows, mock mode, zero spend) — **gates a PR** |
| `make test-all` | Every tier — slow, use before merging |
| `make test-cov` | Coverage over `src/`, project + per-package floors — **gates a PR** |
| `make test-cov-diff` | Patch coverage for this branch vs `origin/main` — **gates a PR** |
| `make typecheck` | `mypy src/` |
| `make run QUERY='...'` | Run the agent on a query |
| `make eval` | Batch-run the benchmark (`QUERIES=id1,id2` to filter) — spends real Anthropic credits; see [`eval.md`](eval.md) |
| `make admin-migrate` | Operator CLI for legacy NULL-owner rows (`ARGS='report --store all'`, ADR 0039/0052) |
| `make clean` | Nuke venv + caches — keeps `.cache/checkpoints.sqlite` (graph state, ADR 0052) |
| `make clean-all` | `clean` + delete the graph checkpoints; paused HITL runs become unresumable |

Every test target runs under the `TEST_ENV` prefix
(`OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false`) — see
Troubleshooting below for why that exists.

See [`testing.md`](testing.md) for the full test taxonomy and how CI
selects tests per PR.

**What the `tests` job in CI actually runs**, in order, so that a green
PR and a green desk mean the same thing: `make test-cov` (unit and
integration under the project and per-package floors), `diff-cover` at
the `COV_DIFF` floor, `make test-e2e`, the adversarial safety suite
(`python -m src.eval.safety_suite`), and the scripted learner
simulation. CI invokes the Makefile targets as `make <target>
VENV_PYTHON=python` — the targets call `$(VENV_PYTHON)`, which is
`.venv/bin/python` here and does not exist on a runner — so the target
is the single definition of each gate and the workflow restates none of
the floors. Run the first three before pushing a change to `src/`; the
last two are seconds and free.

## Working in `web/`

The frontend has its own toolchain (`npm ci` in `web/`, Node
`>=22.22.2` per `web/package.json`'s `engines`) and its own eight test
tiers — commands for each are in
[`testing.md`](testing.md#the-web-suite). Two house rules bind every
change under `web/`, and both are enforced rather than trusted.

### Rule 1 — exactly two persisted client preferences

The product may write **two** keys to browser storage and no others
(RC-05). Both are defined in one place, `web/lib/tokens.ts`:

| Key | Values | What it is |
|---|---|---|
| `arxiv-agent.theme` | `"light"` \| `"dark"` \| `"system"` | The theme override, applied before first paint by an inline script in `app/layout.tsx` so there is no flash |
| `arxiv-agent.rail-collapsed` | `"1"` \| `"0"` | Whether the thread rail is collapsed. `"1"` means collapsed; anything else, including a throw, means expanded |

Both are **cosmetic and safely absent**, which is the property that
matters: no job id, plan, checkpoint or query is ever written to browser
storage, so nothing in storage can outlive `api_job_retention_sec`, and
a rollback loses nothing but a preference. The job id lives in the URL
as `?job=`, not in storage.

Every read and write is wrapped in `try`/`catch`, because
`localStorage` throws outright in a partitioned context. The failure
mode must always be "the preference does not persist" and never "the
control throws". If you add a third key, you are changing the rollback
argument — that needs a decision, not a commit.

### Rule 2 — the budget ratchet

Every route in `web/` carries a gzip byte ceiling in `web/budgets.json`,
checked by `npm run budgets` on every PR.

**A ceiling may only move in a PR that edits `web/budgets.json` in the
same commit and states the reason in the PR body.** There is no
override: `web/scripts/route-budgets.mjs` accepts no command-line
arguments and reads no environment variable, it errors if given any
argv, and `web/tests/budgets.test.ts` asserts those properties against
the script's own source text so they cannot quietly regress.

Two things follow for day-to-day work:

- **Measure before you argue.** A raise needs the measured number and
  the in-budget alternative you rejected, both in the PR body. Both
  raises on record carry theirs, and in one case the in-budget
  alternative was *built and measured* before being rejected — it hit
  the number but would have shipped a document with no `h1`, failing
  the accessibility gate. Accessibility gate beats budget row.
- **Ratchet down when you win bytes.** A ceiling left high after a
  cleanup is headroom nobody earned. Re-seed at the measured value plus
  modest headroom — never at a hairline over the measurement, because
  repeated builds of an unchanged tree oscillate by a few bytes.

Every movement is recorded inside `budgets.json`'s own `ratchet` array
and printed by every budget report, so the history is readable without
`git log`. The rule and the full history are ADR
[0056](decisions/0056-design-tokens.md); the same file also holds the
token contract, which is the other thing you cannot change casually
(literal colours are an ESLint error outside `web/app/tokens.css`).

## OpenTelemetry: traces + metrics

Both signals are off by default and share one exporter endpoint, so
one collector receives both (ADRs 0013 and 0049). Six env vars, and
like every other knob in this repository they are fields on `Settings`
in `src/config.py` — typed, defaulted and validated at load:

| Variable | Default | What it does |
|---|---|---|
| `ENABLE_TRACING` | `false` | Spans around each agent node |
| `ENABLE_METRICS` | `false` | Job / spend / concurrency / rate-limit instruments |
| `OTEL_EXPORTER_ENDPOINT` | `""` | OTLP **HTTP** base URL, e.g. `http://localhost:4318`. Empty = console exporter |
| `OTEL_METRIC_EXPORT_INTERVAL_SEC` | `60` | How often metrics are pushed |
| `TRACE_SAMPLE_RATIO` | unset | Head-sampling ratio in `[0.0, 1.0]`. Unset installs no sampler, leaving `OTEL_TRACES_SAMPLER` to the SDK. Out of range is refused at load, not clamped |
| `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` | `false` | Let user content stay in logs **and** on spans. `LOG_CAPTURE_USER_CONTENT` is the same setting under its older name |

The last two were read straight from `os.environ` until WO-B4 folded
them in; the variables did not change. `OTEL_SERVICE_NAME` is a seventh
and is left out of the table only because it never needs setting.

### The one setting you can change without a restart

`Settings` is a frozen singleton built at import, so every knob above
takes effect at process start — except content capture, which is
re-read from the environment on every log line. That is deliberate: it
is what an operator reaches for mid-incident. A live flip is checked
against the same true/false grammar pydantic used at load, and a value
that is neither leaves the configured value standing and warns once.
See `docs/observability.md` for the exposure trade it makes.

### Seeing it work without a collector

Leave `OTEL_EXPORTER_ENDPOINT` empty and both signals print to stderr —
spans as they finish, metrics every export interval. Useful for a quick
"is this instrumented" check; noisy for anything longer.

```bash
ENABLE_METRICS=true OTEL_METRIC_EXPORT_INTERVAL_SEC=5 \
  .venv/bin/python -m src.api.serve
```

### Pointing a real collector at it

The exporter speaks **OTLP over HTTP** and appends the standard signal
paths itself — give it the *base* URL, not `/v1/traces`. Any
OTLP-compatible backend works (Jaeger, Tempo, Grafana Cloud,
Honeycomb, the OpenTelemetry Collector). The repo ships no collector
service; run one alongside the stack:

```yaml
# docker-compose.override.yml — a collector next to the app
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    command: ["--config=/etc/otelcol/config.yaml"]
    volumes:
      - ./otel-collector.yaml:/etc/otelcol/config.yaml:ro
    ports:
      - "4318:4318"   # OTLP/HTTP
  api:
    environment:
      ENABLE_TRACING: "true"
      ENABLE_METRICS: "true"
      OTEL_EXPORTER_ENDPOINT: "http://otel-collector:4318"
      OTEL_SERVICE_NAME: "arxiv-research-agent"
```

```yaml
# otel-collector.yaml — accept OTLP, expose metrics for Prometheus
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
  debug: {}
service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [debug]
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
```

### What you get

| Instrument | Kind | Attributes | Answers |
|---|---|---|---|
| `research_jobs_total` | counter | `status`, `error_type` | "how many jobs are failing right now, and why" |
| `research_job_duration_seconds` | histogram | `status` | "what is the p95 job duration" |
| `research_active_jobs` | gauge | — | "are we near the concurrency ceiling" (against `API_MAX_CONCURRENT_JOBS`) |
| `research_abandoned_node_threads` | gauge | — | zombie node threads a drain gave up on (ADR 0047) |
| `llm_cost_usd_total` | counter | `model` | fleet spend rate, by model |
| `llm_calls_total` | counter | `model` | call volume, by model |
| `llm_retries_total` | counter | `model` | SDK attempts discarded before a call succeeded (`retries_taken`, ADR 0051) |
| `llm_upstream_errors_total` | counter | `model`, `status` | calls that failed after the SDK exhausted its retries (`status` is the HTTP code, or `connection`) |
| `rate_limit_rejections_total` | counter | `backend` | 429s, by limiter backend |
| `research_degradations_total` | counter | `rung`, `component` | "how much of the traffic is being served degraded, and down which rung" — the quality SLI's instrument (ADR 0081) |

Both gauges are **per worker** — they report the process that emits
them, so aggregate across workers by summing on the resource's
instance attribute. `research_active_jobs` is deliberately the same
figure `/healthz` reports (in-flight jobs *plus* abandoned node
threads), read from the same accounting rather than a second counter.

Note the two gauges reset when a worker restarts and the counters are
monotonic within a process lifetime — query them as rates, and expect
a counter reset on every deploy.

`research_jobs_total` also counts the jobs a *startup sweep* reclaims
from a worker that died mid-job (`error_type="orphaned"`, ADR 0038), so
a crash-looping worker shows up as a failure rate rather than only as
falling throughput.

### Metrics are an API-server signal

`ENABLE_METRICS` is read by the API lifespan and nowhere else, so it
does nothing under `make run` or `make eval` — those processes install
no meter provider and every record point returns on its `None` check.
Tracing is different: `ENABLE_TRACING` works everywhere, because the
tracer configures lazily on the first span. Cost accounting is
unaffected either way — the per-run `cost_usd` in the logs is the same
with the flag on or off.

## Dependency locking

Two files describe dependencies, with different jobs (ADR 0045):

- **`pyproject.toml`** is authoritative for *ranges* — the floors and
  caps a version must fall inside to be worth trying. Floors are the
  oldest release that ships a wheel for the pinned Python and speaks
  the API the code targets; caps sit at the next major above the
  locked version.
- **`requirements-lock.txt`** is authoritative for *the tested set* —
  the exact versions the suite last ran green against. CI installs
  from it, so the gated set and the tested set are identical by
  construction.
- **`requirements-runtime-lock.txt`** is the generated production
  subset of that tested set. It excludes pytest/mypy/ruff and packages
  reachable only from the dev extras; the Docker image installs it
  after selecting the same locked Torch version from PyTorch's CPU
  index (ADR 0054). Never edit it by hand.

To update dependencies:

```bash
# 1. Upgrade inside the venv (respects pyproject's ranges):
.venv/bin/pip install --upgrade -e ".[dev]"

# 2. Run the full local gate against the new set:
make test-all && make typecheck && .venv/bin/ruff check src/ tests/

# 3. Re-freeze, SCOPED TO THE LOCK, keeping the header comment block
#    intact. `pip freeze` reports the whole interpreter, which is not
#    the same set as this project's closure — see "The freeze is wider
#    than the lock" below.
mkdir -p build
sed -n 's/^\([A-Za-z0-9._-]*\)==.*/\1/p' requirements-lock.txt \
  > build/locked-names.txt
.venv/bin/pip freeze --exclude-editable | sort -f > build/freeze.txt

#    a) the new pinned section — every name the lock already carries, at
#       the version now installed:
grep -if <(sed 's/^/^/;s/$/==/' build/locked-names.txt) build/freeze.txt

#    b) everything else the venv holds. Add only the distributions step 1
#       actually pulled in — pip names them in its own output — and leave
#       the rest, which belongs to other work sharing this interpreter:
grep -ivf <(sed 's/^/^/;s/$/==/' build/locked-names.txt) build/freeze.txt

# 4. Consistency check, also scoped: complaints about distributions the
#    lock does not name are not this lock's problem.
.venv/bin/python -m pip check \
  | grep -if <(sed 's/^/^/;s/$/ /' build/locked-names.txt) \
  && echo "INCONSISTENT — fix before committing" \
  || echo "the locked set is consistent"

# 5. Regenerate and check the production subset:
.venv/bin/python scripts/derive_runtime_lock.py
.venv/bin/python scripts/derive_runtime_lock.py --check

# 6. Commit pyproject.toml (if ranges moved) + both lock files
#    together, with a line on *why* the set moved.
```

**The freeze is wider than the lock, and the difference is silent.**
Steps 3 and 4 are scoped because this repository's venv is shared with
other work in the same interpreter, and neither `pip freeze` nor `pip
check` knows which distributions belong to this project. Measured on
2026-09-05: the venv held **147** non-editable distributions against
the lock's **126**, the extra 21 being `google-*`, `groq`, `grpcio`,
`cryptography`, `feedparser` and their transitive closures. The
procedure as it stood before — replace the pinned section with a bare
`pip freeze --exclude-editable` — would have written all 21 into
`requirements-lock.txt`, which is what CI installs; nothing downstream
would have caught it, because `derive_runtime_lock.py` walks the
*project's* dependency graph and would have produced an identical
runtime subset, so `--check` stays green while the tested set has
quietly grown a Google-API stack.

For the same reason a bare `pip check` exits 1 here, on four unlocked
distributions that disagree with the installed protobuf
(`google-ai-generativelanguage`, `google-api-core`, `proto-plus`,
`grpcio-status` against `protobuf 7.35.1`). Scoped to the 126 locked
names, as in step 4, it is clean — verified by WO-A02 and again on
2026-09-05.

The scoping is a workaround for the venv, not a property of the lock.
The authoritative consistency check is the one CI already runs in a
clean environment: `pip install -r requirements-lock.txt` followed by
`python -m pip check`, in both the `typecheck` and `tests` jobs. Do not
try to clean the shared venv to make the bare commands work; build a
throwaway environment if you want the unscoped check locally.

Never hand-edit an individual pin in the lock without running the
gate — a pin the suite has not seen is a lie about what was tested.
The lock is frozen on one platform and carries no hashes yet; the
hashed, cross-platform lock (`uv lock` / `pip-compile
--generate-hashes`) is recorded follow-up in ADR 0045, and it would
retire the scoping above along with the rest of the freeze step.

The container image installs the generated runtime subset (`pip
install -r requirements-runtime-lock.txt`, then `pip install --no-deps
.`), so every production package is still pinned to the version in the
CI-tested set without carrying its dev-only closure. It also bakes the
MiniLM weights into `/opt/hf-cache` so the first live job does not
download them (ADRs 0053/0054). Both properties are pinned without a
Docker build by `tests/test_container_contract.py`; if you touch the
Dockerfile, that module tells you what must stay true.

Linux CI preinstalls the locked Torch version from the official CPU
index before installing the full lock. Do the same in any new Linux
workflow: otherwise the public PyPI artifact adds CUDA-only metadata and
the job no longer represents the production runtime.

## Dependency licensing

PyMuPDF (`fitz`, the PDF extractor behind `src/tools/pdf_parser.py`)
is **AGPL-3.0 dual-licensed** (AGPL or a commercial Artifex license).
AGPL §13 attaches a source-offer obligation to *network* use, which
is exactly how this service runs. The repo currently declares no
license of its own — adopting one (and deciding whether to keep
PyMuPDF, buy the commercial license, or swap to a permissive
extractor such as `pypdfium2`) is an explicit open decision recorded
in ADR 0045. Do not add copyleft dependencies without an ADR.

## The moved-repo venv trap

Python venvs bake absolute paths into their shebangs. If you move the
repo directory (or clone into a new location) **without recreating
the venv**, every command inside `.venv/bin/` will fail with:

```
bad interpreter: /old/path/.venv/bin/python3.14: no such file or directory
```

Fix: `make clean && make install-dev`. This is why the repo ships
with a `Makefile` — never recreate venvs manually or from memory.

## Branching and PRs

See the **Development Workflow** conventions below
for the branch-naming and PR conventions. Short version:

- Bundle related concerns into one cohesive PR (~400-800 additions);
  do not fragment cohesive work across PRs.
- Branches: `<type>/<slug>` — `feat/`, `fix/`, `docs/`, `chore/`, `test/`.
- Every PR ships with tests for its diff (see `testing.md`).
- Every PR that changes behavior updates the relevant doc in the same PR.

## Troubleshooting

- **`command not found: python`** — use `python3`. The Makefile does
  this for you.
- **`ANTHROPIC_API_KEY not set`** — copy `.env.example` to `.env` and
  fill in the key. `main.py` loads it via `python-dotenv`.
- **arXiv rate limiting** — set `USE_MOCK_DATA=true` to run against
  the built-in mock papers.
- **`make test` finds only part of the suite** — `make test-unit`
  filters with `-m unit`, which since WO-A02 selects a real tier
  (2,826 of 3,277 tests) rather than an arbitrary subset, but a tier is
  still not the suite. CI's gate is `make test-cov` (which selects
  `-m "not e2e"`) followed by `make test-e2e`. `make test-all` runs
  every tier in one pass, without the coverage floors.
- **Exit 139 / a macOS crash-reporter dialog with no traceback** —
  a native crash in the embedding path. The fix is in-process
  (`torch.set_num_threads(1)` at model load, plus
  `EMBEDDING_DEVICE=cpu` as the default device — ADR 0052), and the
  Makefile's `TEST_ENV` prefix (`OMP_NUM_THREADS=1
  TOKENIZERS_PARALLELISM=false`) adds a second layer covering
  faiss's and scikit-learn's own libomp copies at import time. If
  you see this crash again, do not raise `TORCH_THREADS` or default
  the device to `auto` without re-reading ADR 0052 — `auto` picks
  `mps` on Apple silicon, which still crashes ~1/6 inside the Metal
  driver. The `embedding_model_loaded` log line records the device
  and thread count actually bound — it is the one artifact that
  survives a SIGSEGV.
