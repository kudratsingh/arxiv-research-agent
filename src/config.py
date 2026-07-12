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
"""

from pydantic import Field
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
    log_level: str = Field(
        default="INFO",
        description="Standard-library logging level name (DEBUG/INFO/WARNING/ERROR)",
    )

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
            "API process. Under a proper job queue (Sprint 4 PR 3+) "
            "this becomes a per-worker cap; today it caps the whole "
            "single-process app."
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
    api_job_retention_sec: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description=(
            "How long a completed job's record + result stays queryable "
            "before it's evicted. In-memory: age check on evict_older_than; "
            "Redis: TTL on the job key. Same knob honored by both stores."
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
    job_store: str = Field(
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

    # ------ Postgres (paper cache + embedding cache) ------------------
    # Sprint 4 PR 4 wires this up. Empty URL = feature disabled: the
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
    paper_cache: str = Field(
        default="disk",
        description=(
            "PaperCache implementation. `disk` (default) = "
            "`.cache/pdfs/<key>.txt` per Sprint 1; `postgres` = "
            "PostgresPaperCache backed by `postgres_url`. See ADR 0028."
        ),
    )
    embedding_cache: str = Field(
        default="none",
        description=(
            "EmbeddingCache implementation. `none` (default) preserves "
            "Sprint 1 behavior byte-identically — every call re-encodes "
            "via MiniLM. `postgres` skips MiniLM inference for texts "
            "we've seen before, indexed by content hash + model name. "
            "See ADR 0028."
        ),
    )
    conversation_store: str = Field(
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
        description="Persist LangGraph state to SQLite for interrupt/resume",
    )
    checkpoint_db_path: str = Field(
        default=".cache/checkpoints.sqlite",
        description="SQLite file for the LangGraph SqliteSaver checkpointer",
    )

    # ------ Tracing (OpenTelemetry) -----------------------------------
    enable_tracing: bool = Field(
        default=False,
        description="Emit OpenTelemetry spans around each agent node",
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
        description="Supervisor refuses further LLM calls above this per-run spend",
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


settings = Settings()
"""Module-level singleton. Import this everywhere instead of instantiating."""
