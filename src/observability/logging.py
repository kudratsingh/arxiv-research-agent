"""Structured JSON logging with per-run context.

Design (ADR 0012):
  - Standard library `logging` module — no `structlog` / `loguru` dep.
  - JSON-line formatter for machine-consumable logs.
  - `run_id` is a `contextvars.ContextVar` — per-run isolation without
    threading it through every call. Propagates across threads when
    workers use `contextvars.copy_context().run(...)`.
  - Level from `settings.log_level` at logger construction; logs sink
    to stderr so eval / runner stdout stays report-only.
"""

import json
import logging
import sys
from contextvars import ContextVar, Token
from typing import Any

from src.config import settings

# Anything on `LogRecord` not in this set is treated as caller-attached
# structured data and merged into the JSON payload.
_STANDARD_LOG_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "taskName",
        "getMessage",
    }
)


_run_id: ContextVar[str] = ContextVar("run_id", default="-")


def current_run_id() -> str:
    """Return the current run's identifier, or `"-"` when no run is bound."""
    return _run_id.get()


def bind_run_id(run_id: str) -> Token[str]:
    """Set the run_id ContextVar; return a `Token` to reset later.

    Idiomatic usage:

        token = bind_run_id(run_id)
        try:
            ...
        finally:
            reset_run_id(token)
    """
    return _run_id.set(run_id)


def reset_run_id(token: Token[str]) -> None:
    """Reset the run_id ContextVar to its previous value."""
    _run_id.reset(token)


class JsonFormatter(logging.Formatter):
    """One-line JSON per record with timestamp, level, name, run_id, message.

    Any `extra={...}` fields passed to `logger.info(...)` land as
    top-level keys in the payload so downstream log processors can
    filter / aggregate on them.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "run_id": _run_id.get(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_KEYS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


_configured_root = False


def _configure_root_once() -> None:
    """Attach the JSON formatter to a stderr handler on the root logger.

    Idempotent — safe to call from every `get_logger`. Also silences
    the noisy httpx / anthropic HTTP client debug logs which spam the
    stream with per-request lines.
    """
    global _configured_root
    if _configured_root:
        return

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Prevent library debug noise from dominating output.
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured_root = True


def get_logger(name: str) -> logging.Logger:
    """Return a JSON-formatted logger named after the calling module.

    Standard usage:

        log = get_logger(__name__)
        log.info("event_name", extra={"k": "v"})
    """
    _configure_root_once()
    return logging.getLogger(name)


def propagate_run_context(fn: Any) -> Any:
    """Wrap `fn` so it inherits the caller's run_id + cost accumulator.

    `ThreadPoolExecutor` does not propagate `contextvars` state to
    worker threads, and `Context.run()` can only be entered once per
    context object — so `copy_context()` alone isn't safe for reuse
    across multiple `executor.map` calls. This helper snapshots the
    calling thread's `run_id` and cost accumulator once (at wrap time)
    and rebinds them per invocation in whichever worker thread runs
    the wrapped call. Cleanup is guaranteed via try/finally.

    Idiomatic usage inside a per-paper / per-item fan-out:

        with ThreadPoolExecutor(...) as executor:
            analyses = list(executor.map(
                propagate_run_context(lambda p: _analyze(p, ...)),
                items,
            ))
    """
    # Local import breaks a small circular between logging and costs.
    from src.observability import costs as _costs

    parent_run_id = _run_id.get()
    parent_costs = _costs._current_costs.get()

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        rid_token = _run_id.set(parent_run_id)
        cost_token = _costs._current_costs.set(parent_costs)
        try:
            return fn(*args, **kwargs)
        finally:
            _run_id.reset(rid_token)
            _costs._current_costs.reset(cost_token)

    return wrapped
