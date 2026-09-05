"""One correlation context for every telemetry signal (ADR 0067).

Before this module the observability layer carried a single ContextVar,
`run_id`, and nothing else: a log line could not be joined to the HTTP
request that caused it, to the job it belonged to, to the worker that
ran it, to the principal that paid for it, or to the trace that
recorded it. Grouping by `run_id` answers "what did this one run do";
it cannot answer "which requests did that key make", "which worker is
stuck", or "show me the trace behind this error".

So: one frozen dataclass in one ContextVar. One place that knows the
field names, so the log payload (`JsonFormatter`) and — when WO-A07
lands — span attributes cannot drift apart. Frozen because a context
that a fan-out worker can mutate is a context that leaks across jobs;
every change makes a new instance and a new `Token`, which is what
makes `reset` honest.

`service` and `version` are resolved once at import rather than per
record: they are process constants, and paying `importlib.metadata` on
every log line to re-learn a value that cannot change would be absurd.

Two field choices are deliberate and load-bearing:

  - **`principal_hash`, never the key id.** The metrics layer already
    refused to attribute by `key_id` (ADR 0049, `_raise_429`) because
    it is unbounded operator-supplied cardinality *and* because it is
    the credential's identity. A log field that undid that would leak
    across the whole retention window rather than across one metric
    scrape. The hash is salted so a short, guessable key id cannot be
    recovered by hashing the candidate space.
  - **`run_id` keeps its `"-"` default.** Every existing consumer —
    log queries, `tracing.py`, the lease tests — reads `"-"` as "no run
    bound". A `None` here would be a silent format change in a field
    that has shipped since ADR 0012.
"""

from __future__ import annotations

import hashlib
import secrets
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from typing import Final

# Re-exported, not merely used: this module has always been where the
# salt's variable name is looked up, and `src.config` owns the string
# now that `Settings.log_principal_salt` answers to it (WO-C3).
from src.config import PRINCIPAL_SALT_ENV as PRINCIPAL_SALT_ENV
from src.config import settings

_DISTRIBUTION = "arxiv-research-agent"

#: Written when the distribution is not installed — a source checkout
#: run with `PYTHONPATH=.` rather than `pip install -e .`. Better an
#: honest sentinel than a hardcoded number that silently goes stale.
UNKNOWN_VERSION: Final = "unknown"


def _resolve_version() -> str:
    """Read the package version from installed metadata, once."""
    try:
        return _distribution_version(_DISTRIBUTION)
    except PackageNotFoundError:
        return UNKNOWN_VERSION


#: `service.name` as OTel already understands it — the same value the
#: tracer's `Resource` carries, so logs and spans agree about who
#: emitted them without a second setting to keep in sync.
SERVICE_NAME: Final[str] = settings.otel_service_name
SERVICE_VERSION: Final[str] = _resolve_version()


@dataclass(frozen=True, slots=True)
class RequestContext:
    """The correlation identifiers that ride with a unit of work.

    Every field except `run_id` is `None` until something binds it, and
    the formatter omits `None` fields rather than emitting nulls — an
    unbound field is absent from the line, not present and empty.

    Attributes:
        run_id: The workflow invocation. `"-"` when nothing is bound,
            preserving the ADR 0012 sentinel every consumer reads.
        job_id: The API job, when the work came through the queue.
        request_id: The inbound HTTP request that started the work.
            Survives into the queued job so an API call and its
            background execution share one key.
        job_kind: `research` / `session` (ADR 0057) — the axis job
            SLOs are cut along.
        principal_hash: Salted digest of the API key id. Never the id.
        worker_id: The process that is executing, so a stuck lease can
            be traced to a host without correlating by timestamp.
    """

    run_id: str = "-"
    job_id: str | None = None
    request_id: str | None = None
    job_kind: str | None = None
    principal_hash: str | None = None
    worker_id: str | None = None


#: The unbound context. A module-level singleton because it is the
#: ContextVar's default and comparing identity against it is how
#: `clear_context` proves it did something.
EMPTY_CONTEXT: Final = RequestContext()

_context: ContextVar[RequestContext] = ContextVar(
    "request_context", default=EMPTY_CONTEXT
)

#: Order matters only for readability of the emitted line; the set is
#: what the formatter uses to decide which caller-supplied `extra` keys
#: it must not let overwrite a bound value.
#:
#: These names, plus `FIELD_SERVICE` / `FIELD_VERSION` below and the
#: envelope block in `logging.py`, are the whole log schema. They are
#: constants in two places rather than literals in many because
#: ISO/IEC FDIS 24970 (AI system logging, stage 50.20) is close to
#: publication and is the likely reference schema for exactly these
#: fields — remapping should be an edit here, not a search.
CONTEXT_FIELDS: Final = (
    "run_id",
    "job_id",
    "request_id",
    "job_kind",
    "principal_hash",
    "worker_id",
)

#: Process identity, on every line so a record found in an aggregated
#: stream says which build of which service produced it.
FIELD_SERVICE: Final = "service"
FIELD_VERSION: Final = "version"


def current_context() -> RequestContext:
    """Return the context bound to this task/thread, or the empty one."""
    return _context.get()


def bind_context(
    *,
    run_id: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
    job_kind: str | None = None,
    principal_hash: str | None = None,
    worker_id: str | None = None,
) -> Token[RequestContext]:
    """Merge the given fields onto the current context.

    Merge rather than replace: the API binds `request_id` and
    `principal_hash` at the edge, the runner binds `job_id` and
    `worker_id` when it picks the job up, and the graph binds `run_id`
    when it starts. Each of those is a separate `bind_context` at a
    different depth of the same call stack, and a replacing setter
    would make the last one silently erase the first two.

    `None` means "leave whatever is bound alone", which is why there is
    no way to unset a single field — use `clear_context` for that. A
    field that could be nulled by an ordinary bind would let an inner
    scope hide an outer scope's principal.

    Args:
        run_id: Workflow invocation id.
        job_id: API job id.
        request_id: Inbound HTTP request id.
        job_kind: Job kind (`research` / `session`).
        principal_hash: Output of `hash_principal`, never a raw key id.
        worker_id: Executing process id.

    Returns:
        A `Token` for `reset_context`, in the try/finally shape
        `bind_run_id` established.
    """
    updates = {
        name: value
        for name, value in (
            ("run_id", run_id),
            ("job_id", job_id),
            ("request_id", request_id),
            ("job_kind", job_kind),
            ("principal_hash", principal_hash),
            ("worker_id", worker_id),
        )
        if value is not None
    }
    return _context.set(replace(_context.get(), **updates))


def attach_context(ctx: RequestContext) -> Token[RequestContext]:
    """Bind an existing context wholesale, replacing rather than merging.

    The thread-boundary primitive: `propagate_run_context` snapshots the
    submitting thread's context and re-attaches it inside the worker.
    Merging would be wrong there — a pooled thread that ran another
    job's callable a moment ago must not keep that job's `job_id`
    because the new parent happens not to set one.
    """
    return _context.set(ctx)


def reset_context(token: Token[RequestContext]) -> None:
    """Restore the context this token was issued against."""
    _context.reset(token)


def clear_context() -> Token[RequestContext]:
    """Bind the empty context, returning a token to restore the old one.

    For an executor thread or a long-lived task that moves on to
    unrelated work: without this, the previous job's `job_id` and
    `principal_hash` stay bound and attribute the next job's lines to
    the wrong tenant.
    """
    return _context.set(EMPTY_CONTEXT)


# ---------------------------------------------------------------------------
# Principal hashing
# ---------------------------------------------------------------------------

#: 48 bits of digest. Enough that two live principals colliding is a
#: curiosity rather than an expectation, short enough that the field
#: stays readable in a terminal.
PRINCIPAL_HASH_CHARS: Final = 12


def _resolve_salt() -> tuple[str, bool]:
    """Return this process's salt, and whether it invented that salt.

    Configured — `LOG_PRINCIPAL_SALT`, which is
    `Settings.log_principal_salt` since WO-C3 — and a principal's lines
    join across every process in the fleet; unset, and each process
    invents its own, so grouping still works *within* a process but not
    across one. Unsalted was never an option: key ids are short,
    operator-chosen strings, and a bare digest of one is recoverable by
    hashing a word list.

    Read through `settings` rather than `os.environ` so the variable is
    declared in one typed surface with every other tunable — but the
    salt is a `SecretStr`, so `get_secret_value()` is the only way the
    raw value may be taken. An f-string of the wrapper would interpolate
    `**********` and salt the entire fleet with the mask: consistent
    with itself, and matching no key id anybody holds.

    A function rather than two module-level expressions because both
    branches have to stay reachable from a test. The resolution itself
    still happens exactly once, at import: the ephemeral salt is a
    property of *this process*, and re-resolving per call would hand out
    a different salt every time and make `principal_hash` ungroupable.

    Returns:
        The salt to hash with, and `True` when it was generated here
        rather than configured.
    """
    configured = settings.log_principal_salt.get_secret_value()
    if configured:
        return configured, False
    return secrets.token_hex(16), True


_principal_salt, _principal_salt_is_ephemeral = _resolve_salt()


def principal_salt_is_ephemeral() -> bool:
    """True when the salt was generated per-process rather than configured.

    Operationally this is the difference between "I can follow this key
    across the fleet" and "I can follow it until the line came from
    another container", so the startup path has something to warn about
    and the runbook has something to check.
    """
    return _principal_salt_is_ephemeral


def hash_principal(key_id: str) -> str | None:
    """Return a salted, truncated digest of an API key id.

    Args:
        key_id: The principal identifier from the keystore. Never
            emitted anywhere by this function.

    Returns:
        A 12-character hex digest, or `None` for an empty id so an
        anonymous request binds nothing rather than binding the hash of
        the empty string — which would make every unauthenticated
        caller look like one principal.
    """
    if not key_id:
        return None
    salted = f"{_principal_salt}\x00{key_id}".encode()
    return hashlib.sha256(salted).hexdigest()[:PRINCIPAL_HASH_CHARS]


def context_fields() -> dict[str, str]:
    """The context as log-payload fields, `None`s omitted.

    The single place that maps dataclass attributes to wire names, so
    the formatter never grows its own opinion about what a context
    looks like and WO-A07's span attributes can reuse it verbatim.
    """
    ctx = _context.get()
    fields: dict[str, str] = {
        CONTEXT_FIELDS[0]: ctx.run_id,
        FIELD_SERVICE: SERVICE_NAME,
        FIELD_VERSION: SERVICE_VERSION,
    }
    for name in CONTEXT_FIELDS[1:]:
        value: str | None = getattr(ctx, name)
        if value is not None:
            fields[name] = value
    return fields
