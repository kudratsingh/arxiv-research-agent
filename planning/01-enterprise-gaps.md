# Enterprise-Readiness Gaps

Foundation work before layering on features. These are the things enterprise buyers and reviewers always look for. The current codebase is a solid prototype; this doc lists what separates prototype from production.

## 1. Observability & Tracing

- **LangSmith / OpenTelemetry integration** — every agent invocation traced with token counts, latency, tool calls, retry attempts. Today we can't answer "why did this query take 40s and cost $0.30?"
- **Structured logging** (`structlog` or `loguru`) with a `run_id` propagated through `ResearchState` so a full trace can be reconstructed per query.
- **Cost tracking per run** — persist Claude input/output tokens per agent per iteration. Report `$/query` as a first-class metric.
- **Prompt/response persistence** — every LLM call logged to disk or a store, for later replay/debugging/eval.

## 2. Reliability

- **Retry with exponential backoff** on Anthropic 429/5xx, arXiv rate limits, PDF download failures. Use `tenacity`.
- **Circuit breakers** for external APIs — if arXiv is down, degrade gracefully instead of hanging.
- **Timeouts everywhere** — per-agent, per-tool, per-run. Currently `.invoke()` can block indefinitely.
- **Idempotency & checkpointing** — LangGraph `MemorySaver` or `SqliteSaver` so a crashed run resumes instead of restarting. Enterprise buyers care a lot about this.
- **Dead-letter queue** for failed runs with full state dump for post-mortem.

## 3. Security & Compliance

- **Secrets management** — currently just `.env`. Add support for AWS Secrets Manager / HashiCorp Vault / GCP Secret Manager via a pluggable `SecretsProvider` interface.
- **PII / secret redaction** in logs (queries could contain proprietary research directions).
- **Prompt injection defenses** — PDFs from arXiv can contain adversarial instructions. Add an isolation layer where paper text is passed as *data*, never mixed into system prompts unescaped. Consider a lightweight "prompt-injection classifier" before feeding chunks to the reader.
- **License & attribution tracking** — record each paper's license (arXiv preprints have varied licenses); enterprise legal teams will ask.
- **Audit log** — who ran what query, when, what was returned. SOC2-friendly.
- **RBAC hooks** — even a stub `User` model with `permissions` is enough to sell that you thought about it.

## 4. Config & Deployment

- **Pydantic Settings** replacing `os.environ.get` scattered around. Single typed `Settings` object.
- **Model configuration as YAML/TOML** — model IDs, temperature, max_tokens per agent externalized. Enterprise wants to swap Opus↔Sonnet↔Haiku without code changes.
- **Docker + docker-compose** with FAISS volume, Redis for caching, Postgres for run history.
- **CI/CD** — GitHub Actions with lint (ruff), type check (mypy strict — already configured), tests, and a golden-query smoke test.
- **Environment tiers** (dev/staging/prod) with separate configs.

## 5. Evaluation Infrastructure

`src/eval/` is currently a stub. Fill it in:

- **Golden dataset** — 20–50 curated queries with expected paper sets, ground-truth findings, and reference reports.
- **Automated eval harness** with metrics:
  - **Retrieval**: Recall@k, MRR against ground-truth paper IDs.
  - **Faithfulness**: LLM-as-judge, checks each claim in report against source papers.
  - **Citation accuracy**: every `[Author, Year]` in report actually maps to a real paper in state.
  - **Completeness**: does report cover all sub-questions?
  - **Coherence**: readability + logical flow (LLM-as-judge).
- **Regression suite** — every PR runs the golden set; fail if metrics drop >5%.
- **A/B harness** — swap agent prompts and compare on the same query set.

## 6. API & Interface Layer

- **FastAPI service** exposing `POST /research` with async job model (return `job_id`, poll `GET /research/{job_id}`).
- **Streaming endpoint** (`/research/stream`) using SSE — LangGraph supports `.astream_events()`.
- **Webhooks** for job-complete notifications.
- **OpenAPI schema** auto-generated → enterprise integrators love this.
