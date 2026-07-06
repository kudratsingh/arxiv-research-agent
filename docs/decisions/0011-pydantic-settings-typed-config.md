# 0011. Typed configuration via `pydantic-settings`

- **Status**: accepted
- **Date**: 2026-07-06

## Context

Tunables are scattered across the codebase — `MAX_RETRIES` and
`REQUEST_TIMEOUT_SEC` in `llm.py`, `USE_MOCK_DATA` / `MAX_PAPERS` /
`RESULTS_PER_QUERY` in `search.py`, `MAX_WORKERS` /
`MAX_CHUNKS_PER_PAPER` in `reader.py`, `DEFAULT_MAX_TOKENS` /
`DEFAULT_OVERLAP_TOKENS` in `chunker.py`, hardcoded `3` in `critic.py`.
Some read env vars ad-hoc via `os.environ.get(...)`; others don't. No
type validation anywhere. No single place to see every knob a deploy
can turn.

Sprint 1 calls out "typed config" as a foundation piece — cost
tracking, structured logging, and future observability all want a
shared surface to look up defaults and env overrides.

## Decision

Introduce `src/config.py` with a `Settings` class built on
`pydantic-settings`, and rewire every existing module-level tunable
through it. Callers import `settings` and reference fields:

```python
from src.config import settings
_client = anthropic.Anthropic(
    api_key=settings.anthropic_api_key,
    max_retries=settings.anthropic_max_retries,
    timeout=settings.anthropic_timeout_sec,
)
```

Configuration is:

- **Typed** — every field has an explicit type; env-var strings coerce
  automatically (bool: `1`/`0`, `true`/`false`, `yes`/`no`).
- **Validated** — `Field(ge=..., le=...)` on numeric fields; a
  bogus env var fails fast at import time, not deep in a workflow run.
- **Immutable** — `frozen=True`; `settings.max_papers = 42` at runtime
  raises. Prevents accidental mutation from thread A affecting thread B
  under the production-scale concurrency mandate.
- **Case-insensitive env vars** — `MAX_PAPERS`, `max_papers`, and
  `Max_Papers` all work.
- **Single source of truth** — one file lists every knob; deploy
  reviews have one place to audit.

Existing module constants (`DEFAULT_MODEL`, `MAX_RETRIES`,
`MAX_WORKERS`, etc.) are kept as back-compat re-exports so external
callers / tests that import them keep working. New code should
reference `settings.*` directly.

## Alternatives considered

- **Plain `os.environ.get(...)` at each call site.** What we had.
  Rejected. No typing, no validation, no discovery, no aggregation.
  Bugs where an env var is spelled wrong go silent.
- **Custom dataclass with manual `os.environ` parsing.** Rejected.
  Reinventing pydantic-settings poorly — would need bool coercion,
  numeric parsing, validation ranges. All bespoke, none tested at the
  library scale that pydantic-settings has.
- **`dynaconf` or `hydra`.** Powerful but overkill. `hydra` in
  particular reshapes the call-site experience with CLI overrides and
  composition — great for ML training, wrong ergonomics for an
  agent server. Revisit when we have hierarchical config needs (e.g.
  per-tenant overrides).
- **`click` for CLI + env.** Wrong tool. We don't have a rich CLI
  surface; `main.py` and `runner.py` take a query string or a
  `--queries` list respectively. Config lives outside the CLI.
- **`functools.lru_cache`d `get_settings()` factory.** Cleaner for
  test isolation, but modules would call `get_settings().max_papers`
  instead of `settings.max_papers` — every read incurs a function
  call. Module-level singleton keeps the ergonomics; tests use
  `monkeypatch.setattr` to override the singleton per-test.

## Consequences

- **Positive**:
  - Every tunable is discoverable from one file. Deploy audits look
    at `src/config.py` and know what's tunable.
  - Env-var typos fail at import time (via `ValidationError`), not
    inside a workflow node ten minutes later.
  - Ranges prevent obvious mistakes (`ANTHROPIC_MAX_RETRIES=999999`
    can't happen — capped at 10 with a validation error).
  - Frozen settings are safe under thread fan-out (reader's
    `ThreadPoolExecutor`, future async runners).
  - Cost tracking (`feat/cost-tracking`), structured logging
    (`feat/structured-logging`), and checkpointing
    (`feat/checkpointing-sqlite`) all have a home for their config.
- **Negative**:
  - Adds `pydantic-settings` as a dep (~60 KB, but pydantic itself
    was already a transitive dep via `langgraph`).
  - Module import order matters: modules that reference `settings`
    trigger a `Settings()` construction which reads `.env`. Tests
    that want a different value have to `monkeypatch.setattr(mod,
    "settings", ...)`. Documented in the module docstring.
- **Follow-ups**:
  - Migrate remaining ad-hoc env reads as they surface. Currently
    covered: `llm.py`, `search.py`, `reader.py`, `chunker.py`,
    `critic.py`.
  - Add `feat/pydantic-settings-config-file` if we grow past env-var
    ergonomics (e.g. a `config/development.toml`).
