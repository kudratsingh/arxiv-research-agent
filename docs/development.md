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

## Common commands

All targets are documented by `make help`. The ones you'll use daily:

| Target | What it does |
|---|---|
| `make install-dev` | Fresh venv + runtime + dev deps |
| `make test` | Tests tagged `unit` only — see Troubleshooting; CI's per-PR gate is `pytest -m "not e2e"` |
| `make test-unit` | Same as `make test` (explicit) |
| `make test-integration` | Integration tier (external libs, fixtures) |
| `make test-e2e` | E2E tier (full workflow, cassettes) |
| `make test-all` | Every tier — slow, use before merging |
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

## OpenTelemetry: traces + metrics

Both signals are off by default and share one exporter endpoint, so
one collector receives both (ADRs 0013 and 0049). Four env vars:

| Variable | Default | What it does |
|---|---|---|
| `ENABLE_TRACING` | `false` | Spans around each agent node |
| `ENABLE_METRICS` | `false` | Job / spend / concurrency / rate-limit instruments |
| `OTEL_EXPORTER_ENDPOINT` | `""` | OTLP **HTTP** base URL, e.g. `http://localhost:4318`. Empty = console exporter |
| `OTEL_METRIC_EXPORT_INTERVAL_SEC` | `60` | How often metrics are pushed |

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

# 3. Re-freeze, keeping the header comment block intact:
.venv/bin/pip freeze --exclude-editable | sort -f  # -> replace the
                                                   # pinned section of
                                                   # requirements-lock.txt

# 4. Regenerate and check the production subset:
.venv/bin/python scripts/derive_runtime_lock.py
.venv/bin/python scripts/derive_runtime_lock.py --check

# 5. Commit pyproject.toml (if ranges moved) + both lock files
#    together, with a line on *why* the set moved.
```

Never hand-edit an individual pin in the lock without running the
gate — a pin the suite has not seen is a lie about what was tested.
The lock is frozen on one platform and carries no hashes yet; the
hashed, cross-platform lock (`uv lock` / `pip-compile
--generate-hashes`) is recorded follow-up in ADR 0045.

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
  filters with `-m unit`, which selects only tests *explicitly* tagged
  `pytest.mark.unit`; about half the suite is unmarked and gets
  skipped by that filter. CI's actual gate is `pytest -m "not e2e"`.
  Use `make test-all` (or `pytest -m "not e2e"` directly) to run what
  CI runs.
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
