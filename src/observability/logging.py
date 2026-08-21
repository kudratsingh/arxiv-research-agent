"""Structured JSON logging with per-run context.

Design (ADR 0012):
  - Standard library `logging` module — no `structlog` / `loguru` dep.
  - JSON-line formatter for machine-consumable logs.
  - `run_id` is a `contextvars.ContextVar` — per-run isolation without
    threading it through every call. Propagates across threads when
    workers use `contextvars.copy_context().run(...)`.
  - Level from `settings.log_level` at logger construction; logs sink
    to stderr so eval / runner stdout stays report-only.

ADR 0051 adds two things to the one-time root configuration, both about
what *else* reaches stderr:

  - The ML stack's progress bars and INFO chatter are muted, because
    "logs sink to stderr" is only useful if stderr is parseable. A
    measured full-workflow run emitted 22 JSON lines and 34 non-JSON
    ones, with one JSON record physically split by an interleaved
    tqdm bar — records lost to a parser, not merely surrounded by noise.
  - `faulthandler` is enabled, so a native crash (a SIGSEGV inside
    MiniLM's forward pass, say) leaves a traceback on stderr instead of
    an exit code and nothing at all.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
        # UTC with millisecond precision and an explicit offset
        # (ADR 0042): local-time second-granularity stamps made
        # cross-host timelines ambiguous and hid sub-second ordering
        # between lease refreshes, redrive decisions and SSE frames.
        ts = datetime.fromtimestamp(
            record.created, tz=UTC
        ).isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "ts": ts,
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

# Libraries that write per-request / per-batch INFO lines. Demoted to
# WARNING so the JSON stream carries events, not narration.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "anthropic",
    "urllib3",
    # The ML stack (ADR 0051). `sentence_transformers` matters twice
    # over: its INFO lines are noise, AND its progress-bar default is
    # `logger.getEffectiveLevel() in (INFO, DEBUG)` — so demoting the
    # logger is also what turns the tqdm bars off, at the library's own
    # gate rather than by monkeypatching its call sites.
    "sentence_transformers",
    "transformers",
    "huggingface_hub",
    "faiss",
)

# The one library logger ADR 0051 pulls back OUT of the blanket
# demotion. `anthropic._base_client` emits exactly one non-DEBUG line —
# `"Retrying request to %s in %f seconds"` at INFO — and that line is
# the only in-process signal that the SDK is absorbing 429s / 529s /
# timeouts on our behalf. ADR 0042's demotion of the whole `anthropic`
# tree silenced it, which is how a rate-limited fleet came to look
# identical to a slow one. Re-opening the child rather than the parent
# keeps every other `anthropic.*` logger quiet.
_SDK_RETRY_LOGGER = "anthropic._base_client"

# Environment knobs the ML stack reads at import time. `setdefault`, so
# an operator debugging a model load can still export their own value.
# Progress bars and tokenizer fork-warnings write straight to stderr,
# bypassing `logging` entirely — a logger level cannot reach them
# (ADR 0051).
_QUIET_LIBRARY_ENV = {
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "TRANSFORMERS_VERBOSITY": "error",
}


def _enable_faulthandler() -> None:
    """Arm `faulthandler` so a native crash still leaves a traceback.

    A SIGSEGV in native code (torch, faiss and tokenizers all run there;
    an audit reproduced one inside MiniLM's pooling forward pass under
    the reader's thread-pool fan-out) kills the process with no
    Python-level output whatsoever — no log line, no traceback, no
    artifact, just exit 139. `faulthandler` costs nothing until that
    happens and then prints every thread's stack to stderr, which is the
    difference between a diagnosable crash and a mystery (ADR 0051).
    This is half of that fix; pinning the native thread pools is the
    other half and lives outside this module.

    Best-effort by design: `enable()` needs a real file descriptor and
    `sys.stderr` is not always one — pytest's capture and embedded hosts
    replace it with an object that has no `fileno()`. Crash diagnostics
    are a bonus, so an unavailable handler is logged and shrugged off
    rather than allowed to break logging setup for everyone.

    The three ways CPython refuses, all caught: `AttributeError` (a
    stderr with no `fileno`), `io.UnsupportedOperation` (a captured or
    closed stream — it subclasses both `ValueError` and `OSError`), and
    `RuntimeError` ("sys.stderr is None", which is what a stderr-detached
    process gets). Missing that last one would let a daemonised host take
    `_configure_root_once` down with it — losing *all* logging to save
    the crash handler, the exact trade this function exists to refuse.
    """
    if faulthandler.is_enabled():
        # Already armed by the host — pytest does this by default.
        return
    try:
        faulthandler.enable()
    except (AttributeError, ValueError, OSError, RuntimeError) as exc:
        logging.getLogger(__name__).debug(
            "faulthandler_unavailable", extra={"detail": str(exc)}
        )


def _configure_root_once() -> None:
    """Attach the JSON formatter to a stderr handler on the root logger.

    Idempotent — safe to call from every `get_logger`. Also quiets the
    HTTP clients and the ML stack so every line on stderr is a JSON
    record, and enables `faulthandler` so a native crash is not silent.
    """
    global _configured_root
    if _configured_root:
        return

    # Before any logging setup: these are read by `transformers` /
    # `huggingface_hub` / `tokenizers` when they import, and this module
    # is imported far earlier than they are.
    for key, value in _QUIET_LIBRARY_ENV.items():
        os.environ.setdefault(key, value)

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    _enable_faulthandler()

    # Prevent library debug noise from dominating output — but only
    # when the app itself isn't running at DEBUG (ADR 0042). An
    # unconditional demotion silently defeated `ANTHROPIC_LOG=debug`,
    # which is exactly the switch on-call reaches for when jobs fail
    # against the Anthropic API.
    if root.level > logging.DEBUG:
        for noisy in _NOISY_LOGGERS:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        # ...except the SDK's retry line (see `_SDK_RETRY_LOGGER`). A
        # child logger's own level wins over its parent's, and it is
        # held no lower than the app's own level so `LOG_LEVEL=WARNING`
        # still means WARNING rather than "WARNING plus retries".
        logging.getLogger(_SDK_RETRY_LOGGER).setLevel(
            max(logging.INFO, root.level)
        )

    _configured_root = True


def redact_url(url: str) -> str:
    """Strip credentials from a connection URL for safe logging.

    Replaces the userinfo section (`user:password@`, or just
    `user@`) with `***@`, keeping scheme, host, port, and path —
    the parts with diagnostic value. Postgres and Redis URLs both
    carry credentials inline, and `JsonFormatter` copies `extra`
    values verbatim into the indexed log payload, so any startup
    line logging a raw URL ships the production password to
    everyone with log-read access (ADR 0042).

    Args:
        url: Any URL-shaped string. Values that don't parse or have
            no userinfo are returned unchanged.

    Returns:
        The URL with userinfo replaced by `***`, or the input
        untouched when there is nothing to redact.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        # Unparseable input can't be proven credential-free, but it
        # also can't be rebuilt; hide everything past the scheme.
        return "***"
    if "@" not in parts.netloc:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=f"***@{host}"))


def get_logger(name: str) -> logging.Logger:
    """Return a JSON-formatted logger named after the calling module.

    Standard usage:

        log = get_logger(__name__)
        log.info("event_name", extra={"k": "v"})
    """
    _configure_root_once()
    return logging.getLogger(name)


def propagate_run_context(fn: Any) -> Any:
    """Wrap `fn` so it inherits the caller's run context.

    Three ContextVars ride along: `run_id`, the cost accumulator, and
    the job's cancel token (ADR 0047 — without it, LLM calls made from
    a fan-out worker cannot see that their job was cancelled and keep
    spending after the runner gave up).

    `ThreadPoolExecutor` does not propagate `contextvars` state to
    worker threads, and `Context.run()` can only be entered once per
    context object — so `copy_context()` alone isn't safe for reuse
    across multiple `executor.map` calls. This helper snapshots the
    calling thread's values once (at wrap time) and rebinds them per
    invocation in whichever worker thread runs the wrapped call.
    Cleanup is guaranteed via try/finally.

    Idiomatic usage inside a per-paper / per-item fan-out:

        with ThreadPoolExecutor(...) as executor:
            analyses = list(executor.map(
                propagate_run_context(lambda p: _analyze(p, ...)),
                items,
            ))
    """
    # Local imports: `costs` would be a circular import at module
    # level, and `cancellation` follows the same shape for symmetry.
    from src.cancellation import _current_cancel_token
    from src.observability import costs as _costs

    parent_run_id = _run_id.get()
    parent_costs = _costs._current_costs.get()
    parent_cancel = _current_cancel_token.get()

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        rid_token = _run_id.set(parent_run_id)
        cost_token = _costs._current_costs.set(parent_costs)
        cancel_token = _current_cancel_token.set(parent_cancel)
        try:
            return fn(*args, **kwargs)
        finally:
            _run_id.reset(rid_token)
            _costs._current_costs.reset(cost_token)
            _current_cancel_token.reset(cancel_token)

    return wrapped
