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


settings = Settings()
"""Module-level singleton. Import this everywhere instead of instantiating."""
