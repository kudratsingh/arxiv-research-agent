"""Typed configuration surface for the project.

Central place to configure every tunable in the workflow. Values load
from environment variables and `.env`, with per-field validation and
type coercion via `pydantic-settings`. Module callers import `settings`
directly:

    from src.config import settings
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key,
        max_retries=settings.anthropic_max_retries,
    )

Under the production-scale mandate, config lives in one typed surface
so runtime tuning is safe (no string-typed env vars scattered across
call sites) and Deploy-time reviews have one file to audit.

See ADR 0011 for the design rationale (pydantic-settings vs alternatives).

## Overriding for tests

`Settings` is frozen — instances are immutable. Tests that need
different values should either (a) construct a new `Settings(...)`
inline and monkeypatch the module-level `settings` attribute, or (b)
set env vars via `monkeypatch.setenv` before importing.

## Enum-valued fields are `Literal`, not `str`

Every field that selects one of a closed set of implementations
(`job_store`, `conversation_store`, `checkpoint_backend`,
`rate_limit_backend`, `paper_cache`, `embedding_cache`, `log_level`)
is typed `Literal[...]` so a typo'd env var dies at settings load
with pydantic's "unexpected value" message instead of silently
selecting a downstream fallback. See ADR 0046.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime tunables for the arxiv research agent.

    Fields group by concern (Anthropic, search, reader, chunker, critic,
    logging) and map to `SCREAMING_SNAKE_CASE` environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    # ------ Anthropic / LLM --------------------------------------------
    anthropic_api_key: str = Field(default="", description="Claude API key")
    anthropic_model: str = Field(
        default="claude-sonnet-4-6",
        description="Model ID used by every agent unless overridden per-call",
    )
    anthropic_max_retries: int = Field(
        default=4,
        ge=0,
        le=10,
        description="Retries after the first attempt on 408/409/429/5xx",
    )
    anthropic_timeout_sec: float = Field(
        default=120.0,
        gt=0.0,
        le=600.0,
        description="Per-request timeout; must be below SDK's 600s default",
    )

    # ------ Search -----------------------------------------------------
    use_mock_data: bool = Field(
        default=False,
        description="Force built-in mock papers instead of hitting arXiv",
    )
    max_papers: int = Field(
        default=10, ge=1, le=50, description="Cap on ranked paper count"
    )
    results_per_query: int = Field(
        default=5,
        ge=1,
        le=20,
        description="arXiv results fetched per sub-question search",
    )

    # ------ Reader -----------------------------------------------------
    reader_max_workers: int = Field(
        default=5,
        ge=1,
        le=20,
        description="ThreadPool workers for per-paper LLM calls",
    )
    reader_max_chunks_per_paper: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Top-K ranked chunks fed to Claude per paper",
    )

    # ------ Chunker ----------------------------------------------------
    chunker_max_tokens: int = Field(
        default=800, ge=100, le=4000, description="Target chunk token budget"
    )
    chunker_overlap_tokens: int = Field(
        default=100,
        ge=0,
        le=500,
        description="Overlap between consecutive chunks in a section",
    )

    # ------ Critic -----------------------------------------------------
    max_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Hard cap on critic-driven revision loops",
    )

    # ------ Logging ----------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description=(
            "Standard-library logging level name. Literal so a typo "
            "(`LOG_LEVEL=DEBG`) fails at settings load instead of "
            "surfacing as a `logging` error at first emission. See "
            "ADR 0046."
        ),
    )

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: Any) -> Any:
        """Uppercase before Literal validation.

        `LOG_LEVEL=debug` has always worked because the logging setup
        calls `.upper()` at use; keep that contract now that the field
        is a case-sensitive `Literal`.
        """
        return value.upper() if isinstance(value, str) else value

    # ------ HTTP retry (arXiv API + PDF downloads) ---------------------
    http_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Retries on 429/5xx for arXiv API and PDF downloads",
    )
    http_backoff_factor: float = Field(
        default=1.0,
        ge=0.0,
        le=10.0,
        description="urllib3 Retry backoff_factor (delay = factor * 2**attempt)",
    )
    pdf_max_bytes: int = Field(
        default=50 * 1024 * 1024,
        ge=1024 * 1024,
        le=500 * 1024 * 1024,
        description=(
            "Hard cap on a single PDF download. Reader streams bytes "
            "and aborts once the cap is reached so a 500MB adversarial "
            "PDF can't OOM the process. See ADR 0033."
        ),
    )

    # ------ API auth + rate limiting (ADR 0033) ------------------------
    enable_api_auth: bool = Field(
        default=False,
        description=(
            "Gate every /research and /conversations route behind the "
            "X-API-Key header. Off by default so local dev + eval + "
            "existing tests keep working. Turn on for any exposed "
            "deployment: without it, an anonymous caller can drive "
            "the workflow at ANTHROPIC_API_KEY's expense. ADR 0033."
        ),
    )
    api_keys: str = Field(
        default="",
        description=(
            "Comma-separated `name:key` pairs used when "
            "`enable_api_auth` is on. Example: "
            "`internal:sk_a123,partner:sk_b456`. Names appear in "
            "logs; the raw key is compared with `hmac.compare_digest` "
            "so lookups run in constant time. This field is read once "
            "at app startup, so rotating through it requires a restart; "
            "set `api_keys_file` for hot reload instead (ADR 0037)."
        ),
    )
    api_key_hourly_limit: int = Field(
        default=100,
        ge=1,
        le=100_000,
        description=(
            "Per-API-key ceiling on `POST /research` submits per "
            "sliding hour. Correct across workers under "
            "`rate_limit_backend=redis`; per-worker under `memory`."
        ),
    )
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "Backend for the per-key rate limiter. `memory` (default) "
            "is single-process — under multi-worker uvicorn the "
            "effective limit becomes `api_key_hourly_limit * n_workers`. "
            "`redis` uses a shared ZSET on `ratelimit:{key_id}`; "
            "requires `job_store=redis` — the limiter reuses the "
            "RedisJobStore's client rather than opening a second pool "
            "from `redis_url`, and startup fails without one. See "
            "ADR 0037."
        ),
    )
    api_keys_file: str = Field(
        default="",
        description=(
            "Optional path to a JSON file `{name: secret, ...}` used "
            "as the keystore. When set, overrides `api_keys` and "
            "enables hot reload — a background task polls mtime "
            "every `api_keys_reload_interval_sec` and swaps the "
            "in-memory keystore on change without a restart. See "
            "ADR 0037."
        ),
    )
    api_keys_reload_interval_sec: int = Field(
        default=30,
        ge=1,
        le=3600,
        description=(
            "Poll interval for the hot-reload keystore watcher. "
            "Lower = faster propagation, more disk stats. Ignored "
            "when `api_keys_file` is empty."
        ),
    )
    api_cors_allow_origins: str = Field(
        default="",
        description=(
            "Comma-separated origins allowed by CORS. Empty (default) "
            "installs no CORS middleware — same-origin only. Set to "
            "`*` for full permissive (dev only); production should "
            "list explicit origins, e.g. "
            "`https://arxiv-agent.example.com,https://staging...`."
        ),
    )

    # ------ HTTP API (Sprint 4) ---------------------------------------
    # Tunables for the FastAPI surface layered on top of the workflow.
    # See ADR 0025.
    api_host: str = Field(
        default="127.0.0.1",
        description=(
            "Bind address for `python -m src.api.serve`. Use 0.0.0.0 in "
            "a container so the port is reachable from outside."
        ),
    )
    api_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Bind port for `python -m src.api.serve`",
    )
    api_max_concurrent_jobs: int = Field(
        default=10,
        ge=1,
        le=1000,
        description=(
            "Semaphore-limited ceiling on concurrent workflow runs per "
            "API process. Each uvicorn worker holds its own semaphore, "
            "so a multi-worker deployment admits up to n_workers times "
            "this many jobs in flight."
        ),
    )
    api_job_timeout_sec: int = Field(
        default=600,
        ge=10,
        le=3600,
        description=(
            "Hard timeout applied to a single workflow invocation via "
            "the API. Jobs exceeding this are marked failed with "
            "`timeout` error type. Independent of the client's HTTP "
            "read timeout on the streaming endpoint."
        ),
    )
    api_job_drain_timeout_sec: int = Field(
        default=30,
        ge=1,
        le=300,
        description=(
            "How long the runner holds a job's concurrency permit after "
            "a timeout or shutdown, waiting for the graph node's thread "
            "to actually return. A node thread cannot be killed, so the "
            "permit has to outlive the cancelled coroutine or "
            "`api_max_concurrent_jobs` stops bounding real work. Past "
            "this budget the runner gives up, logs "
            "`api_job_node_drain_expired`, and the abandoned thread is "
            "counted into `/healthz`'s `active_jobs` until it returns. "
            "The shutdown path caps this further at "
            "`runner.SHUTDOWN_DRAIN_SEC`, so raising this cannot push "
            "SIGTERM past the container's grace period. See ADR 0047."
        ),
    )
    api_job_retention_sec: int = Field(
        default=86400,
        ge=60,
        le=86400,
        description=(
            "How long a completed job's record + result stays queryable "
            "before it's evicted. In-memory: age check on evict_older_than; "
            "Redis: TTL on the job key. Same knob honored by both stores. "
            "Default is 24h, not 1h: the job row is the only durable copy "
            "of a report unless the caller exports it or attached a "
            "conversation, so an aggressive TTL silently destroys results."
        ),
    )
    api_sse_heartbeat_sec: float = Field(
        default=15.0,
        gt=0.0,
        le=300.0,
        description=(
            "Idle interval between SSE keepalive comment frames on "
            "`GET /research/{id}/stream`. Must stay comfortably under "
            "the shortest idle timeout of any proxy in front of the "
            "app (nginx `proxy_read_timeout` defaults to 60s). See "
            "ADR 0038."
        ),
    )
    api_sse_max_duration_sec: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description=(
            "Ceiling on how long a single SSE connection stays open. "
            "A stream on a job that never reaches a terminal state "
            "would otherwise pin a worker connection forever; at the "
            "deadline the server emits `stream_timeout` and closes so "
            "the client can reconnect. See ADR 0038."
        ),
    )
    enable_hitl: bool = Field(
        default=True,
        description=(
            "When true, the workflow interrupts after the planner so a "
            "human can review + edit the plan (sub_questions, "
            "search_queries) before search runs. See ADR 0030. Per-query "
            "bypass via `POST /research { hitl_bypass: true }` — the eval "
            "runner uses that path so nightly benchmarks don't stall."
        ),
    )
    api_hitl_timeout_sec: int = Field(
        default=1800,
        ge=30,
        le=86400,
        description=(
            "How long a job sits in `pending_review` before the runner "
            "gives up and marks it failed with error_type=hitl_timeout. "
            "Independent of `api_job_timeout_sec`, which caps only the "
            "workflow's own wall-clock (not the human's decision time)."
        ),
    )
    job_store: Literal["memory", "redis"] = Field(
        default="memory",
        description=(
            "Which JobStore implementation the API uses. `memory` = "
            "in-process InMemoryJobStore (single-worker only, jobs die "
            "with the process). `redis` = RedisJobStore backed by "
            "`redis_url`, safe for horizontal API scaling. See ADR 0027."
        ),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description=(
            "Async Redis URL used by `RedisJobStore` when `job_store=redis`. "
            "In compose the default is `redis://redis:6379/0`."
        ),
    )

    # ------ Job redriver + worker leases (ADR 0038) -------------------
    # A worker that dies mid-job leaves its Redis row stuck in a
    # non-terminal status forever: `GET /research/{id}` reports
    # `running` and the SSE stream hangs waiting for a terminal frame
    # that nobody will ever publish. The lease is what distinguishes
    # "orphaned" from "running on a worker that is still alive", so a
    # rolling restart of worker 3 does not reap worker 1's jobs.
    enable_job_redriver: bool = Field(
        default=True,
        description=(
            "Run the startup reconciliation sweep that reclaims jobs "
            "orphaned by a dead worker. No-op unless `job_store=redis` "
            "(nothing survives a restart under the in-memory store). "
            "See ADR 0038."
        ),
    )
    job_lease_ttl_sec: int = Field(
        default=90,
        ge=10,
        le=3600,
        description=(
            "TTL on `joblease:{job_id}`, the key a worker holds while "
            "it runs a job. Expiry is what marks the job orphaned, so "
            "this is also the worst-case delay before a crashed "
            "worker's jobs become reclaimable. Must be > "
            "`job_lease_refresh_sec` with margin for a GC pause."
        ),
    )
    job_lease_refresh_sec: int = Field(
        default=30,
        ge=5,
        le=1800,
        description=(
            "How often the runner's background task re-expires its "
            "job lease. Keep at roughly a third of `job_lease_ttl_sec` "
            "so two consecutive missed refreshes still do not orphan a "
            "healthy job."
        ),
    )
    job_redrive_requeue_pending: bool = Field(
        default=False,
        description=(
            "When true, orphaned jobs still in `pending` (accepted but "
            "never started, so no partial work and no spend) are "
            "resubmitted instead of failed. `running` and "
            "`pending_review` jobs are always failed with "
            "`error_type=orphaned` — resuming them would double-charge "
            "for LLM calls already made."
        ),
    )
    job_redrive_max_scan: int = Field(
        default=10000,
        ge=100,
        le=1000000,
        description=(
            "Upper bound on job keys examined in one redrive sweep, so "
            "a huge keyspace cannot stall startup. Hitting the cap is "
            "logged as `job_redriver_scan_capped` rather than silently "
            "truncating the sweep."
        ),
    )
    job_redrive_interval_sec: int = Field(
        default=300,
        ge=30,
        le=86400,
        description=(
            "Interval for the periodic redrive sweep. The startup "
            "sweep alone misses a real case: a container restarted "
            "before its old lease expires sees the job as live at "
            "boot, and no later sweep ever runs — the row stays "
            "`running` forever. Periodic sweeps close that. Only "
            "meaningful when `enable_job_redriver` is on and the "
            "store is Redis."
        ),
    )

    # ------ Postgres (paper cache + embedding cache) ------------------
    # Wired up in ADR 0028. Empty URL = feature disabled: the
    # paper cache falls back to on-disk `.cache/pdfs/` (Sprint 1
    # behavior, byte-identical), and the embedding cache is a no-op.
    postgres_url: str = Field(
        default="",
        description=(
            "libpq-style Postgres URL (`postgresql://user:pass@host/db`) "
            "for the paper cache + embedding cache. Empty = disabled, "
            "falls back to on-disk paper cache and no embedding cache. "
            "In compose the default is "
            "`postgresql://arxiv:arxiv@postgres:5432/arxiv`."
        ),
    )
    paper_cache: Literal["disk", "postgres"] = Field(
        default="disk",
        description=(
            "PaperCache implementation. `disk` (default) = "
            "`.cache/pdfs/<key>.txt` per Sprint 1; `postgres` = "
            "PostgresPaperCache backed by `postgres_url`. See ADR 0028."
        ),
    )
    embedding_cache: Literal["none", "postgres"] = Field(
        default="none",
        description=(
            "EmbeddingCache implementation. `none` (default) preserves "
            "Sprint 1 behavior byte-identically — every call re-encodes "
            "via MiniLM. `postgres` skips MiniLM inference for texts "
            "we've seen before, indexed by content hash + model name. "
            "See ADR 0028."
        ),
    )
    embedding_device: Literal["cpu", "auto", "mps", "cuda"] = Field(
        default="cpu",
        description=(
            "Device for the sentence-transformers embedding model. "
            "`cpu` (default) is deliberate: MiniLM encodes are small "
            "enough that CPU latency is negligible, while the torch "
            "MPS backend has segfaulted inside the Metal driver under "
            "concurrent processes — a native crash kills the worker "
            "with no traceback. `auto` restores the library's own "
            "device pick for deployments that want GPU encode."
        ),
    )
    conversation_store: Literal["memory", "postgres"] = Field(
        default="memory",
        description=(
            "ConversationStore implementation. `memory` = in-process "
            "InMemoryConversationStore (single-worker only, dies with "
            "the process). `postgres` = PostgresConversationStore, "
            "durable across restarts + shared across workers. See ADR "
            "0032. Compose sets this to `postgres` alongside the "
            "paper + embedding caches."
        ),
    )
    conversation_context_top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "How many prior-report chunks the retriever pulls into the "
            "planner's system prompt when a job runs in a conversation. "
            "Higher = more continuity, more tokens; lower = leaner, may "
            "lose thread. See ADR 0032."
        ),
    )

    # ------ Checkpointing ---------------------------------------------
    enable_checkpointing: bool = Field(
        default=True,
        description="Persist LangGraph state for interrupt/resume",
    )
    checkpoint_backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        description=(
            "Backend for LangGraph checkpoints. `sqlite` uses "
            "`checkpoint_db_path` — single-writer, per-worker only. "
            "`postgres` shares checkpoints across API workers via "
            "`postgres_url`; required for multi-worker HITL and "
            "horizontal scaling. See ADR 0034."
        ),
    )
    checkpoint_db_path: str = Field(
        default=".cache/checkpoints.sqlite",
        description="SQLite file used when `checkpoint_backend=sqlite`",
    )

    # ------ Telemetry (OpenTelemetry: tracing + metrics) ---------------
    enable_tracing: bool = Field(
        default=False,
        description="Emit OpenTelemetry spans around each agent node",
    )
    enable_metrics: bool = Field(
        default=False,
        description=(
            "Emit OpenTelemetry metrics (job counts + durations, LLM "
            "cost/calls, concurrency gauges, rate-limit rejections). "
            "Off by default and gated exactly like `enable_tracing`: "
            "with it off no meter provider is installed and every "
            "record point returns on a single `None` check. Shares "
            "`otel_exporter_endpoint` with tracing — one collector "
            "receives both signals. See ADR 0049."
        ),
    )
    otel_service_name: str = Field(
        default="arxiv-research-agent",
        description="OTel `service.name` resource attribute",
    )
    otel_exporter_endpoint: str = Field(
        default="",
        description=(
            "OTLP HTTP endpoint (e.g. http://localhost:4318). Empty = console exporter."
        ),
    )
    otel_metric_export_interval_sec: int = Field(
        default=60,
        ge=1,
        le=3600,
        description=(
            "How often the periodic metric reader exports to the OTLP "
            "collector. Bounded (ADR 0046): below 1s the export thread "
            "costs more than the signal is worth, and above an hour a "
            "worker that dies takes its last window's counters with it."
        ),
    )

    # ------ Supervisor loop (Sprint 2) --------------------------------
    enable_supervisor: bool = Field(
        default=False,
        description=(
            "Use the supervisor loop instead of the fixed pipeline. Off by "
            "default so behavior stays stable; flip on to run the agentic path."
        ),
    )
    min_quality_score: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Supervisor stops when critic quality_score >= this",
    )
    max_cost_usd: float = Field(
        default=2.00,
        gt=0.0,
        le=100.0,
        description=(
            "Per-run LLM spend ceiling in USD. Enforced by the API "
            "runner between graph nodes (both fixed-DAG and supervisor "
            "shapes) — see ADR 0033. The supervisor also checks this "
            "independently as a stop condition."
        ),
    )
    max_loop_iterations: int = Field(
        default=20,
        ge=1,
        le=200,
        description=(
            "Hard cap on supervisor invocations per run — orthogonal to "
            "`max_iterations` (critic-revision cap). Prevents thrash."
        ),
    )
    enable_verifier: bool = Field(
        default=False,
        description=(
            "Adds `verify` to the supervisor's action space. Independent "
            "of `enable_supervisor` so the two can be A/B'd separately "
            "against the Sprint 1 baseline. Verifier is a no-op under "
            "the fixed pipeline. See ADR 0015."
        ),
    )
    enable_evidence_store: bool = Field(
        default=False,
        description=(
            "Reader also emits `EvidenceClaim`s traced to ranked chunks; "
            "verifier judges against `source_text` instead of abstracts. "
            "Independent of `enable_supervisor` / `enable_verifier` so "
            "the substrate upgrade can be A/B'd separately. Fixed "
            "pipeline stays unchanged. See ADR 0016."
        ),
    )
    reader_max_claims_per_paper: int = Field(
        default=5,
        ge=1,
        le=20,
        description=(
            "Cap on claims the reader extracts per paper when the "
            "evidence store is enabled. Bounds prompt cost."
        ),
    )
    enable_query_refiner: bool = Field(
        default=False,
        description=(
            "Adds `refine_query` to the supervisor's action space. "
            "Without it, the supervisor's 'search again' choice re-runs "
            "the same failing queries. Independent of other Sprint 2 "
            "flags. No-op under the fixed pipeline. See ADR 0018."
        ),
    )
    query_refiner_max_queries: int = Field(
        default=5,
        ge=1,
        le=15,
        description=(
            "Cap on new queries the refiner emits per invocation. "
            "Bounds fan-out on the next search round."
        ),
    )
    enable_reader_recovery: bool = Field(
        default=False,
        description=(
            "Reader emits `analysis_complete` / `missing_context` / "
            "`request_more_sections` so the supervisor can re-invoke "
            "it with a narrower brief. On re-invocation, the ranker "
            "reserves slots for chunks from the requested sections. "
            "Independent of other Sprint 2 flags. Fixed pipeline "
            "unchanged. See ADR 0019."
        ),
    )
    enable_prompt_isolation: bool = Field(
        default=False,
        description=(
            "Wrap PDF-derived text in untrusted-content tags in reader "
            "prompts and sanitize reader control-field outputs. "
            "Recommended whenever `enable_supervisor` is on because "
            "supervisor routing now consumes reader-emitted control "
            "signals derived from arXiv text. Default off to preserve "
            "Sprint 1 baseline byte-for-byte. See ADR 0020."
        ),
    )

    # ------ Per-agent model routing (ADR 0021, Sprint 3) --------------
    # Each field defaults to "" — empty means "fall back to
    # anthropic_model". Set to a Claude model ID to route a specific
    # agent's calls to a cheaper (Haiku) or richer (Opus) tier.
    # See ADR 0021 for the recommended defaults and cost impact.
    reader_model: str = Field(
        default="",
        description=(
            "Model for the reader's per-paper analysis calls. Highest-"
            "volume agent (one call per paper); Haiku is the "
            "recommended override. Empty falls back to anthropic_model."
        ),
    )
    planner_model: str = Field(
        default="",
        description="Model for the planner. Empty falls back to anthropic_model.",
    )
    synthesizer_model: str = Field(
        default="",
        description=(
            "Model for the synthesizer's report generation. Writing "
            "quality benefits from the base model; overrides only if "
            "you need to trade quality for cost. Empty = anthropic_model."
        ),
    )
    critic_model: str = Field(
        default="",
        description=(
            "Model for the critic's quality judgment. Empty falls back "
            "to anthropic_model."
        ),
    )
    verifier_model: str = Field(
        default="",
        description=(
            "Model for the runtime faithfulness verifier. Empty falls "
            "back to anthropic_model."
        ),
    )
    supervisor_model: str = Field(
        default="",
        description=(
            "Model for the supervisor's per-turn routing decision. "
            "High-volume under a full loop (~1 call per action); Haiku "
            "is the recommended override. Empty = anthropic_model."
        ),
    )
    query_refiner_model: str = Field(
        default="",
        description=(
            "Model for the query refiner. Short generation task; Haiku "
            "is the recommended override. Empty = anthropic_model."
        ),
    )

    # ------ Prompt caching (ADR 0022, Sprint 3) -----------------------
    enable_prompt_caching: bool = Field(
        default=False,
        description=(
            "Mark each agent's system prompt for Anthropic's ephemeral "
            "prompt cache. Reads on cache hits bill at 10% of the input "
            "rate; writes bill at 125% (25% first-write premium). Best "
            "hit rate on the reader (parallel fan-out) and supervisor "
            "(loop iterations). Default off — preserves Sprint 1 "
            "baseline byte-identical. See ADR 0022."
        ),
    )

    # ------ Semantic Scholar (ADR 0023, Sprint 3) ---------------------
    enable_semantic_scholar: bool = Field(
        default=False,
        description=(
            "Enrich arXiv search results with Semantic Scholar's "
            "citation graph. Search agent fetches one-hop references "
            "for the top-K arXiv seed papers and unions them with the "
            "arXiv set before ranking. Broader retrieval (conferences, "
            "journals) + related work discovery via cited papers. "
            "Default off preserves Sprint 1 baseline. See ADR 0023."
        ),
    )
    semantic_scholar_api_key: str = Field(
        default="",
        description=(
            "Optional Semantic Scholar API key. Unset = anonymous rate "
            "limit (~100 req / 5 min per IP); set = 1 req/sec sustained."
        ),
    )
    semantic_scholar_seed_count: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "How many top-ranked arXiv papers to expand via S2 "
            "references. Zero disables enrichment even with the flag "
            "on. Bounds outbound S2 API calls per run."
        ),
    )
    semantic_scholar_refs_per_seed: int = Field(
        default=3,
        ge=1,
        le=20,
        description=(
            "How many references to fetch per seed paper (one-hop). "
            "Total S2 references per run bounded at "
            "`seed_count * refs_per_seed`."
        ),
    )
    semantic_scholar_timeout_sec: float = Field(
        default=30.0,
        gt=0.0,
        le=120.0,
        description="Per-request timeout for S2 API calls.",
    )


    @model_validator(mode="after")
    def _check_lease_invariant(self) -> Settings:
        """Reject a lease TTL a refresh cycle cannot keep alive.

        `job_lease_refresh_sec`'s own description promises that "two
        consecutive missed refreshes still do not orphan a healthy
        job" — which only holds while three refresh cycles fit inside
        `job_lease_ttl_sec`. Below that margin a healthy job loses its
        lease on an ordinary GC pause and a peer's redrive sweep
        reclaims work that is still running. Both fields have
        individually valid ranges that combine into a broken pair, so
        the check has to live here rather than on either Field.

        Raises:
            ValueError: When the refresh interval leaves no margin.
        """
        if self.job_lease_refresh_sec * 3 > self.job_lease_ttl_sec:
            raise ValueError(
                "job_lease_refresh_sec must be at most a third of "
                f"job_lease_ttl_sec so two missed refreshes are "
                f"survivable; got refresh={self.job_lease_refresh_sec} "
                f"ttl={self.job_lease_ttl_sec}. See ADR 0038."
            )
        return self



settings = Settings()
"""Module-level singleton. Import this everywhere instead of instantiating."""
