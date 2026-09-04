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

ADR 0067 turns "one line per event" into a contract, because a payload
whose shape nobody agreed on is not a schema, it is a hope. The
formatter had merged **every** non-standard `LogRecord` attribute
verbatim with no allowlist and no size cap, which is how a raw user
query and — on a store failure — a whole report body came to be indexed
under the same retention as an error code. Four rules now hold:

  - **Correlation.** `run_id` alone cannot join a line to the request,
    job, worker, principal or trace behind it. `context.py`'s single
    `RequestContext` supplies all of those, and `trace_id` / `span_id`
    join the payload whenever a span is live.
  - **A closed event-name set.** `KNOWN_EVENTS` is the registry; a name
    emitted from `src.*` that is not in it is flagged on the line
    itself and fails a test.
  - **An allowlist and a size cap for `extra`.** Unknown keys are
    dropped and counted; oversized values are truncated with a marker.
    An unbounded field is a bill and a leak, not a diagnostic.
  - **Redaction by default.** User content is elided unless capture is
    explicitly opted into, and every string that does survive is
    scrubbed for credentials — URL userinfo (ADR 0042's original rule),
    bearer tokens, `sk-` keys, email addresses and long base64 blobs.
"""

from __future__ import annotations

import faulthandler
import json
import logging
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from contextvars import Token
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit

from src.config import settings
from src.observability.context import (
    CONTEXT_FIELDS,
    FIELD_SERVICE,
    FIELD_VERSION,
    RequestContext,
    attach_context,
    bind_context,
    context_fields,
    current_context,
    reset_context,
)

try:  # pragma: no cover - exercised by whichever branch the env has
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - opentelemetry-api is a hard dep
    # The API package is declared in `pyproject.toml`, so this branch
    # should be unreachable. It exists because logging is the one
    # subsystem that must survive a broken environment: a process that
    # cannot import its logger cannot tell anyone why it died.
    _otel_trace = None  # type: ignore[assignment]

# Anything on `LogRecord` not in this set is treated as caller-attached
# structured data and considered for the payload.
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


# ---------------------------------------------------------------------------
# The log contract (ADR 0067)
# ---------------------------------------------------------------------------

#: Every event name `src/` is allowed to emit. Closed, in the same
#: sense the error-code registry is closed: adding a log line means
#: adding its name here, and `tests/test_log_contract.py` fails on any
#: name that skipped the step. The value of a closed set is not
#: tidiness — it is that a dashboard, an alert rule and a runbook can
#: name an event and be told when the code stops emitting it under that
#: name, instead of quietly matching nothing forever.
#:
#: Pruning is deliberately *not* enforced: deleting the last emitter of
#: an event is rare and leaving the name registered for a release is
#: how a still-deployed older worker's lines stay recognised.
KNOWN_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "admin_migrate_completed",
        "admin_migrate_conversations_assigned",
        "admin_migrate_conversations_deleted",
        "admin_migrate_failed",
        "admin_migrate_job_deleted",
        "admin_migrate_jobs_assigned",
        "admin_migrate_jobs_deleted",
        "admin_migrate_unparsable_job",
        "api_conversation_created",
        "api_conversation_deleted",
        "api_cors_enabled",
        "api_health_dependency_degraded",
        "api_health_dependency_recovered",
        "api_job_cancelled",
        "api_job_completed",
        "api_job_cost_budget_exceeded",
        "api_job_evict_sweep_failed",
        "api_job_exported",
        "api_job_failed",
        "api_job_hitl_cancelled",
        "api_job_hitl_timeout",
        "api_job_interrupt_auto_resumed",
        "api_job_node_drain_completed",
        "api_job_node_drain_expired",
        "api_job_plan_revised",
        "api_job_review_submitted",
        "api_job_session_turn_timeout",
        "api_job_submitted",
        "api_job_terminal_persist_failed",
        "api_job_terminal_persist_retry",
        "api_job_timeout",
        "api_job_unknown_kind",
        "api_jobs_evicted",
        "api_learner_profile_deleted",
        "api_learner_profile_written",
        "api_node_executor_drain_timeout",
        "api_prior_context_failed",
        # ADR 0064's four exception handlers. `api_request_rejected` is
        # every 4xx the boundary answers; `api_request_failed` is the
        # 5xx line that did not exist at all before those handlers did.
        "api_request_failed",
        "api_request_rejected",
        "api_session_cost_cap_reached",
        "api_session_submitted",
        "api_session_transcript_unavailable",
        "api_session_turn_submitted",
        "api_shutdown",
        "api_startup",
        "api_store_selected",
        "arxiv_search_rate_limited",
        "arxiv_search_request_failed",
        "assessment_judge_unassessed",
        "conversation_append_failed",
        "conversation_context_retrieved",
        "critic_response_not_an_object",
        "critic_response_unparseable",
        "critic_revision_target_invalid",
        "critic_score_unparseable",
        "embedding_cache_get_failed",
        "embedding_cache_put_failed",
        "embedding_cache_selected",
        "embedding_model_loaded",
        "eval_checkpointer_close_failed",
        "eval_metric_failed",
        "eval_query_completed",
        "eval_query_failed",
        "eval_query_no_report",
        "eval_query_started",
        "eval_record_malformed",
        "eval_record_unreadable",
        "event_queue_full_dropped",
        # Emitted through `logging.getLogger(__name__).debug(...)` in
        # `_enable_faulthandler` rather than a module-level `log`, so
        # the contract test's scan cannot see it and it is registered
        # by hand. The one hand-written entry in the registry; every
        # other name is derivable from the code.
        "faulthandler_unavailable",
        "hitl_resume_bad_payload",
        "hitl_resume_publish_failed",
        "hitl_resume_received_via_pubsub",
        "job_cas_write_aborted",
        "job_cas_write_stale",
        "job_kind_unknown",
        "job_lease_acquire_error",
        "job_lease_acquired_late",
        "job_lease_contended",
        "job_lease_lost",
        "job_redriver_periodic_failed",
        "job_redriver_periodic_reclaimed",
        "job_redriver_periodic_timeout",
        "job_redriver_publish_failed",
        "job_redriver_reclaim_lost_race",
        "job_redriver_reclaimed",
        "job_redriver_requeue_failed",
        "job_redriver_requeue_unavailable",
        "job_redriver_requeued",
        "job_redriver_scan_capped",
        "job_redriver_skipped_locked",
        "job_redriver_startup_failed",
        "job_redriver_startup_timeout",
        "job_redriver_store_unsupported",
        "job_redriver_swept",
        "job_scan_bad_payload",
        "job_status_bad_payload",
        "job_terminal_transition_refused",
        "keystore_file_missing",
        "keystore_initial_load",
        "keystore_reload_parse_failed",
        "keystore_reloaded",
        "keystore_reloader_iteration_failed",
        "keystore_reloader_stopped",
        "learn_content_invalid",
        "learner_profile_skill_evicted",
        "learning_fixture_recorded",
        "learning_session_node_cost",
        "llm_call",
        "llm_client_configured",
        "llm_retry_budget_clamped",
        "llm_upstream_error",
        "metrics_configured",
        "metrics_shutdown_failed",
        "paper_cache_get_failed",
        "paper_cache_put_failed",
        "paper_cache_selected",
        "pdf_download_failed",
        "pdf_download_http_error",
        "pdf_download_not_a_pdf",
        "pdf_download_oversize_declared",
        "pdf_download_oversize_streamed",
        "pdf_download_redirect_without_location",
        "pdf_download_too_many_redirects",
        "pdf_extraction_failed",
        "pdf_url_rejected_bad_address",
        "pdf_url_rejected_dns",
        "pdf_url_rejected_non_public",
        "pdf_url_rejected_scheme",
        "planner_plan_fallback_to_query",
        "planner_response_not_an_object",
        "planner_response_unparseable",
        "postgres_pool_opened",
        "postgres_schema_initialized",
        "progress_events_erased",
        "query_refiner_kept_current",
        "reader_completed",
        "reader_degraded_to_abstract_only",
        "reader_paper_abstract_only",
        "reader_paper_analysis_failed",
        "revision_target_undispatchable",
        "route_after_supervisor_disabled_action_endpoint",
        "route_after_supervisor_unknown_action_endpoint",
        "run_completed",
        "run_failed",
        "run_recovery_nothing_to_recover",
        "run_recovery_state_unavailable",
        "run_recovery_write_failed",
        "run_recovery_wrote_partial",
        "run_started",
        "search_empty_keeping_prior_papers",
        "search_mock_data_served",
        "search_partial_arxiv_failure",
        "search_query_cap_applied",
        "semantic_scholar_bad_json",
        "semantic_scholar_bad_status",
        "semantic_scholar_request_failed",
        "session_check_in_safe_fallback",
        "session_check_in_unparseable",
        "session_memory_generation_degraded",
        "session_resume_publish_failed",
        "session_tutor_safe_reask",
        "session_tutor_turn_prepared",
        "session_tutor_unparseable",
        "simulated_learner_unparseable",
        "simulated_metric_failed",
        "simulated_session_completed",
        "simulated_session_failed",
        "simulated_session_pause_bound_hit",
        "simulated_session_started",
        "sse_client_disconnected",
        "sse_drainer_close_failed",
        "sse_drainer_read_failed",
        "sse_event_bad_payload",
        "sse_event_bad_shape",
        "sse_publish_failed",
        "sse_stream_deadline_reached",
        "sse_terminal_frame_flushed_at_deadline",
        "sse_terminal_frame_suppressed",
        "sse_terminal_publish_failed",
        "sse_terminal_publish_gave_up",
        "supervisor_cost_budget_stop",
        "supervisor_invalid_action_fallback",
        "supervisor_llm_failed_fallback_to_default",
        "supervisor_max_iterations_stop",
        "synthesizer_citations_dropped",
        "synthesizer_citations_not_a_list",
        "synthesizer_response_not_an_object",
        "synthesizer_response_unparseable",
        "synthesizer_retrying_malformed_response",
        "tracing_configured",
        "unknown_model_pricing_fallback",
        "verifier_llm_failed_fallback",
    }
)

#: Every `extra=` key the formatter will carry into the payload.
#: Everything else is dropped and counted rather than merged, which is
#: the whole point: `extra` was an open door into an indexed, retained
#: store, and the cost of a field nobody vetted is paid in storage, in
#: cardinality, and — for a report body or a user query — in exposure.
#:
#: The list was derived by reading every `log.*(..., extra=...)` site in
#: `src/`, including the ones that splat a dict built elsewhere
#: (`RunCosts.as_dict`, `RedriveReport.as_dict`, the runner's cost
#: snapshots). `tests/test_log_contract.py` re-derives it and fails when
#: a new key appears without being registered.
ALLOWED_EXTRA_KEYS: Final[frozenset[str]] = frozenset(
    {
        "abandoned_node_threads",
        "abandoned_nodes",
        "action",
        "address",
        "api_job_timeout_sec",
        "api_keys_configured",
        "attempt",
        "attempted_status",
        "auth_enabled",
        "available",
        "behavior",
        "bytes",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "call_count",
        "cancelled_jobs",
        "cap",
        "cap_usd",
        "cascaded",
        "changed",
        "checkpoint_backend",
        "citation_accuracy",
        "completeness",
        "configured_device",
        "configured_max_retries",
        "consecutive",
        "consequence",
        "content_length",
        "conversation_id",
        "conversation_store",
        "cost_usd",
        "costs",
        "count",
        "created_at",
        "declared_skills",
        "dependency",
        "dependency_status",
        "detail",
        "domain",
        "drain_budget_sec",
        "drain_sec",
        "dropped",
        "dry_run",
        "elapsed_ms",
        "elapsed_sec",
        "enable_api_auth",
        "end_session",
        "endpoint",
        "erased_events",
        "error",
        "error_type",
        "event",
        "existed",
        "expectation_failures",
        "expected_status",
        "export_interval_sec",
        "failed",
        "failed_queries",
        "faithfulness",
        "fallback",
        "fallback_reasons",
        "format",
        "goals",
        "has_plan",
        "hitl_timeout_sec",
        "impl",
        "include_all_auth_off",
        "input_tokens",
        "iterations",
        "job_id",
        "job_kind",
        "job_redrive_interval_sec",
        "job_redriver_enabled",
        "job_redriver_periodic",
        "judge_cost_usd",
        "judge_costs",
        "kept",
        "key",
        "keystore_source",
        "kind",
        "latency_ms",
        "learner_profile_enabled",
        "learner_profile_store",
        "llm_calls",
        "loop_iter",
        "matched",
        "max_bytes",
        "max_concurrent_jobs",
        "max_duration_sec",
        "max_redirects",
        "max_retries",
        "max_scan",
        "metric",
        "metrics",
        "metrics_enabled",
        "metrics_error",
        "model",
        "n_abstract_only",
        "n_chunks_indexed",
        "n_claims",
        "n_failed",
        "n_keys",
        "n_papers",
        "n_prior",
        "n_queries",
        "n_returned",
        "n_search_queries",
        "n_sub_questions",
        "n_texts",
        "n_vectors",
        "node",
        "nodes",
        "observed_status",
        "origins",
        "orphaned",
        "output_tokens",
        "owner",
        "paper_id",
        "paper_key",
        "parsed_keys",
        "partial_report_chars",
        "path",
        "path_id",
        "pause_number",
        "payload",
        "pdf_path",
        "pdf_url",
        "per_model",
        "preview",
        "previous_public_turn",
        "previous_status",
        "prices_last_verified",
        "processed_turns",
        "progress_event_store",
        "progress_events",
        "quality_score",
        "query",
        "query_id",
        "rate_limit_backend",
        "raw",
        "raw_type",
        "read_bytes",
        "reason",
        "received",
        "recovered_path",
        "redrive_failed",
        "redrive_orphaned",
        "redrive_requeued",
        "redrive_scan_capped",
        "redrive_skipped_live",
        "repeat",
        "report_chars",
        "request_id",
        "requested",
        "requeued",
        "resolved_device",
        "resource_id",
        "result",
        "result_head",
        "result_len",
        "retries",
        "revision_target",
        "rule",
        "run_id",
        "scan_capped",
        "scanned",
        "scenario_id",
        "scoring_sec",
        "service",
        "session_turn_timeout_sec",
        "skill",
        "skipped_live",
        "source",
        "spent_usd",
        "state_turn_number",
        "status",
        "status_code",
        "stop_reason",
        "store",
        "stored_status",
        "thread_id",
        "threshold",
        "tier",
        "timeout_sec",
        "torch_threads",
        "total_cache_creation_input_tokens",
        "total_cache_read_input_tokens",
        "total_cost_usd",
        "total_input_tokens",
        "total_output_tokens",
        "traceback",
        "turn_number",
        "turns",
        "turns_delivered",
        "url",
        "worker_id",
        "worst_case_request_sec",
    }
)

#: Keys whose values carry user or model text rather than machine
#: facts: the submitted query, a generated report, a learner's turn, an
#: unparseable model response. Elided unless capture is opted into.
#:
#: Membership is by *key*, not by inspection of the value, because a
#: heuristic that guesses whether a string is user content is a
#: heuristic that will be wrong on the day it matters. A few names here
#: are not in `ALLOWED_EXTRA_KEYS` yet — they are the obvious names a
#: future call site would reach for, and pre-registering them means the
#: redaction is in place before the leak is.
USER_CONTENT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "answer",
        "completion",
        "content",
        "goals",
        "learner_text",
        "payload",
        "preview",
        "prompt",
        "query",
        "raw",
        "received",
        "report",
        "result",
        "result_head",
        "revision_target",
        "text",
        "turn",
    }
)

#: The OpenTelemetry GenAI conventions' content-capture flag, and the
#: only opt-in environment variable those conventions define. The spec
#: says instrumentations "SHOULD NOT capture [message content] by
#: default, but SHOULD provide an option for users to opt in" — this is
#: that option, under the name the standard already gave it, so an
#: operator who has made the content decision once does not have to
#: discover a second switch to make it stick in a second sink.
CONTENT_CAPTURE_ENV: Final = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"

#: A repo-local alias, and the narrower of the two: it turns content on
#: for *logs* without also turning it on for spans, which is what an
#: operator debugging a parse failure actually wants. Either variable
#: being truthy enables capture; neither is the default.
#:
#: Read from the environment rather than from `Settings` only because
#: `src/config.py` belongs to another work order this wave; WO-A12
#: folds both names in (ADR 0067).
CONTENT_CAPTURE_ENV_ALIAS: Final = "LOG_CAPTURE_USER_CONTENT"

_TRUTHY: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})

# --- Envelope field names --------------------------------------------------
#
# The payload keys that are not `extra` and not context. Named as
# constants in one place rather than written as literals inside
# `format`, because ISO/IEC FDIS 24970 — the AI-system-logging standard
# — is at stage 50.20 and likely to become the reference schema for
# exactly these fields. When it lands, remapping should be an edit to
# this block plus `context.context_fields`, not a hunt through a
# formatter. The context half of the schema lives there for the same
# reason.
FIELD_TIMESTAMP: Final = "ts"
FIELD_LEVEL: Final = "level"
FIELD_LOGGER: Final = "logger"
FIELD_MESSAGE: Final = "message"
FIELD_TRACE_ID: Final = "trace_id"
FIELD_SPAN_ID: Final = "span_id"
FIELD_EXCEPTION: Final = "exception"
FIELD_DROPPED_KEYS: Final = "dropped_extra_keys"
FIELD_DROPPED_COUNT: Final = "dropped_extra_count"
FIELD_UNREGISTERED_EVENT: Final = "unregistered_event"

#: Per-value ceiling. 2 KiB holds any legitimate diagnostic — a URL, a
#: stack frame, an error message — and refuses the 100 KB report body
#: that motivated the cap.
MAX_EXTRA_VALUE_CHARS: Final = 2048

#: Per-container ceiling, so a list of 10,000 paper ids becomes a list
#: of 50 and a count rather than a line no one can read and no index
#: wants.
MAX_EXTRA_ITEMS: Final = 50

#: How far into nested containers the bounding walks before giving up
#: and stringifying. Three levels covers `per_model` (dict of dicts);
#: anything deeper is a structure that does not belong in a log line.
MAX_EXTRA_DEPTH: Final = 3

#: Dropped key names named on the line itself. Capped because a caller
#: splatting an unexpected dict could otherwise turn the drop report
#: into the very unbounded field the allowlist exists to prevent.
MAX_REPORTED_DROPPED_KEYS: Final = 10

#: Distinct dropped keys the process-wide counter will track. Bounded
#: for the same reason.
_MAX_TRACKED_DROPPED_KEYS: Final = 256

_dropped_extra_keys: Counter[str] = Counter()

#: Contract fields a caller may still *fill* from `extra` when nothing
#: is bound — `job_id` and `worker_id` are passed explicitly at most
#: call sites today — but may never *overwrite*. Without that
#: asymmetry an `extra={"principal_hash": ...}` could attribute a line
#: to a principal that did not make the request.
_CONTRACT_FIELDS: Final[frozenset[str]] = frozenset(
    {*CONTEXT_FIELDS, FIELD_SERVICE, FIELD_VERSION, FIELD_TRACE_ID, FIELD_SPAN_ID}
)

#: `run_id`'s unbound sentinel (ADR 0012). Treated as "not bound" when
#: deciding whether an `extra` may fill a contract field.
_UNBOUND_RUN_ID: Final = "-"


def content_capture_enabled() -> bool:
    """True when user content may stay in the log stream.

    Either the conventional flag or the log-only alias turns it on;
    absent both, content is elided. Read per call rather than cached at
    import so an operator can flip it for a debugging session without a
    restart, and so a test can exercise both halves with
    `monkeypatch.setenv`.
    """
    return any(
        os.environ.get(name, "").strip().lower() in _TRUTHY
        for name in (CONTENT_CAPTURE_ENV, CONTENT_CAPTURE_ENV_ALIAS)
    )


# --- Redaction rules -------------------------------------------------------

# Order is load-bearing. URL userinfo goes first because
# `postgres://user:pw@host` would otherwise match the email rule on its
# `pw@host` tail — the secret would still be hidden, but under the wrong
# rule and with the wrong replacement, which is how a rule ends up
# looking correct in a test and wrong in production.
_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^\s/@]+@")
_BEARER_RE = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9\-._~+/]+=*)")
_API_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
# The lookbehind excludes only the base64 alphabet, deliberately *not*
# `=`: `token=QWxh…` is the commonest shape a blob arrives in, and an
# `=` in the lookbehind made the rule miss every one of them.
_BLOB_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/=])")

#: A token this long is a token whatever it is made of.
_UNCONDITIONAL_TOKEN_CHARS = 20


def _redact_bearer(match: re.Match[str]) -> str:
    """Replace the credential after `Bearer`, but only a credential.

    `\\bbearer\\s+\\S+` also matches "the bearer of bad news", and a
    redaction rule that eats English is a rule someone will disable.
    A real token is either long, or short and visibly not a word —
    it carries a digit, a capital, or one of the base64url separators.
    """
    scheme, token = match.group(1), match.group(2)
    looks_like_a_token = len(token) >= _UNCONDITIONAL_TOKEN_CHARS or (
        len(token) >= 8
        and any(c.isdigit() or c.isupper() or c in "-._~+/=" for c in token)
    )
    return f"{scheme} ***" if looks_like_a_token else match.group(0)


def _redact_blob(match: re.Match[str]) -> str:
    """Replace a run of base64-ish characters, but only a plausible one.

    A bare "40+ characters from the base64 alphabet" also describes a
    lowercase-hex digest, a UUID with the dashes stripped, and a long
    snake_case identifier — redacting those would delete the very ids
    an operator joins on. Requiring mixed case *and* a digit is the
    cheap discriminator between an encoded secret and a name.
    """
    text = match.group(0)
    if not any(c.islower() for c in text) or not any(c.isupper() for c in text):
        return text
    if not any(c.isdigit() for c in text):
        return text
    return f"***[{len(text)} chars]"


def redact_text(text: str) -> str:
    """Scrub credentials and personal identifiers out of free text.

    Applied to every string the formatter emits — message, `extra`
    values, and the formatted exception — because the leak that
    actually happened was not a call site logging a password on
    purpose; it was a connection error whose *message* carried the URL
    (ADR 0042), and a stack trace that repeated it.

    Five rules, each with its own test:

      - URL userinfo (`scheme://user:pw@host` → `scheme://***@host`),
        the same property `redact_url` guarantees for a whole-string URL.
      - `Bearer <token>` in an Authorization header echoed into a log.
      - `sk-…` API keys, the shape Anthropic and several others use.
      - Email addresses, local part removed, domain kept — the domain
        is the diagnostic half and the local part is the personal one.
      - Long base64-ish blobs, which is what an encoded token or an
        embedded credential looks like once it has lost its prefix.

    Args:
        text: Any string bound for the log payload.

    Returns:
        The string with each matched secret replaced by a marker. Text
        containing none of the shapes is returned unchanged.
    """
    text = _URL_USERINFO_RE.sub(r"\1***@", text)
    text = _BEARER_RE.sub(_redact_bearer, text)
    text = _API_KEY_RE.sub("sk-***", text)
    text = _EMAIL_RE.sub(r"***@\1", text)
    return _BLOB_RE.sub(_redact_blob, text)


def _truncate(text: str) -> str:
    """Cap a string at `MAX_EXTRA_VALUE_CHARS`, saying how much was cut."""
    if len(text) <= MAX_EXTRA_VALUE_CHARS:
        return text
    dropped = len(text) - MAX_EXTRA_VALUE_CHARS
    return f"{text[:MAX_EXTRA_VALUE_CHARS]}…[truncated {dropped} chars]"


def _scrub(text: str) -> str:
    """Bound then redact — in that order.

    Truncating first is the cheaper pass over a 100 KB value, and it is
    also the safer one: redacting first and truncating after would run
    five regexes across the whole blob to protect bytes that were never
    going to be emitted. Redacting *after* the cut is what guarantees a
    token straddling the boundary is still caught.
    """
    return redact_text(_truncate(text))


def _bound_value(value: Any, depth: int = 0) -> Any:
    """Return `value` reduced to something a log line can afford.

    Numbers and booleans pass through — they cannot be large and cannot
    hide a secret. Everything else is walked, with strings scrubbed,
    containers clipped to `MAX_EXTRA_ITEMS`, and anything past
    `MAX_EXTRA_DEPTH` flattened to a bounded string.
    """
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, (bytes, bytearray)):
        # Never decode: bytes in a log line are a payload nobody meant
        # to read, and decoding one is how binary content becomes text
        # content in an index.
        return f"<{len(value)} bytes>"
    if depth >= MAX_EXTRA_DEPTH:
        return _scrub(str(value))
    if isinstance(value, Mapping):
        clipped = {
            str(k): _bound_value(v, depth + 1)
            for k, v in list(value.items())[:MAX_EXTRA_ITEMS]
        }
        if len(value) > MAX_EXTRA_ITEMS:
            clipped["__truncated__"] = f"+{len(value) - MAX_EXTRA_ITEMS} more keys"
        return clipped
    if isinstance(value, (list, tuple, set, frozenset)) or (
        isinstance(value, Sequence) and not isinstance(value, str)
    ):
        items = list(value)
        bounded: list[Any] = [_bound_value(v, depth + 1) for v in items[:MAX_EXTRA_ITEMS]]
        if len(items) > MAX_EXTRA_ITEMS:
            bounded.append(f"+{len(items) - MAX_EXTRA_ITEMS} more items")
        return bounded
    return _scrub(str(value))


def _elide(value: Any) -> str:
    """Stand-in for a user-content value that capture is not enabled for.

    Keeps the one operational fact the value carried — roughly how much
    there was — and discards the content. "The report was 41,832
    characters" answers "did the model produce anything" without
    putting the report in the index.
    """
    if isinstance(value, str):
        return f"[redacted: {len(value)} chars]"
    return f"[redacted: {type(value).__name__}]"


def _note_dropped(key: str) -> None:
    """Count one dropped `extra` key, with the tracked set bounded."""
    if key in _dropped_extra_keys or len(_dropped_extra_keys) < _MAX_TRACKED_DROPPED_KEYS:
        _dropped_extra_keys[key] += 1


def dropped_extra_key_counts() -> dict[str, int]:
    """Process-wide tally of `extra` keys the allowlist refused.

    The counter exists so a drop is discoverable without reading the
    lines it happened on: a key that appears here is either a call site
    that forgot to register a field or a dependency attaching its own
    attributes to our records.
    """
    return dict(_dropped_extra_keys)


def reset_dropped_extra_key_counts() -> None:
    """Clear the tally. For tests and for a long-lived process's own hygiene."""
    _dropped_extra_keys.clear()


def _trace_fields() -> dict[str, str]:
    """`trace_id` / `span_id` of the active span, or nothing.

    Reads the OTel API only — creating spans is WO-A07's job, and a
    logger that started spans would be a logger that changed sampling
    decisions. When no provider is configured the current span is the
    invalid one and this costs a ContextVar read and a boolean.
    """
    if _otel_trace is None:  # pragma: no cover - see the import guard
        return {}
    span_context = _otel_trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return {}
    return {
        FIELD_TRACE_ID: format(span_context.trace_id, "032x"),
        FIELD_SPAN_ID: format(span_context.span_id, "016x"),
    }


# ---------------------------------------------------------------------------
# Run scope — the ADR 0012 surface, now backed by the ADR 0067 context
# ---------------------------------------------------------------------------


def current_run_id() -> str:
    """Return the current run's identifier, or `"-"` when no run is bound."""
    return current_context().run_id


def bind_run_id(run_id: str) -> Token[RequestContext]:
    """Set the run_id on the current context; return a `Token` to reset later.

    Kept as the narrow entry point it has always been — `main.run`, the
    eval runner and the API runner all call it — while the value it
    writes now lives on the one `RequestContext` rather than in a
    ContextVar of its own. The `Token` is passed straight back to
    `reset_run_id`, so callers never see the type change.

    Idiomatic usage:

        token = bind_run_id(run_id)
        try:
            ...
        finally:
            reset_run_id(token)
    """
    return bind_context(run_id=run_id)


def reset_run_id(token: Token[RequestContext]) -> None:
    """Reset the context to its value before the matching `bind_run_id`."""
    reset_context(token)


class _RunIdCompatVar:
    """`logging._run_id` as it looked before ADR 0067 — a view, not a var.

    There is still exactly one ContextVar; this is a `get`/`set`/`reset`
    facade over the `run_id` field of the context that replaced it.
    It exists because `_run_id` had become a de-facto private API:
    `tests/test_observability.py`'s teardown fixture resets it directly,
    and that file belongs to no work order this wave. Breaking it to
    save three lines here would have meant editing a file this change
    does not own, which is the more expensive mistake.

    Deprecated on arrival. The next change that touches
    `tests/test_observability.py` should switch the fixture to
    `context.clear_context()` and delete this class.
    """

    __slots__ = ()

    def get(self) -> str:
        return current_context().run_id

    def set(self, value: str) -> Token[RequestContext]:
        return bind_context(run_id=value)

    def reset(self, token: Token[RequestContext]) -> None:
        reset_context(token)


_run_id: Final = _RunIdCompatVar()


class JsonFormatter(logging.Formatter):
    """One-line JSON per record: timestamp, level, name, context, message.

    `extra={...}` fields land as top-level keys when they are on
    `ALLOWED_EXTRA_KEYS`, bounded by `MAX_EXTRA_VALUE_CHARS` and scrubbed
    by `redact_text`. Anything else is dropped, named in
    `dropped_extra_keys` on the line, and counted process-wide.
    """

    def format(self, record: logging.LogRecord) -> str:
        # UTC with millisecond precision and an explicit offset
        # (ADR 0042): local-time second-granularity stamps made
        # cross-host timelines ambiguous and hid sub-second ordering
        # between lease refreshes, redrive decisions and SSE frames.
        ts = datetime.fromtimestamp(
            record.created, tz=UTC
        ).isoformat(timespec="milliseconds")
        message = record.getMessage()
        payload: dict[str, Any] = {
            FIELD_TIMESTAMP: ts,
            FIELD_LEVEL: record.levelname,
            FIELD_LOGGER: record.name,
            FIELD_MESSAGE: _scrub(message),
        }
        # Context before extras so a caller cannot forge a correlation
        # field, and so the joinable keys sit at the front of the line
        # where a human reading raw stderr will find them.
        payload.update(context_fields())
        payload.update(_trace_fields())

        dropped: list[str] = []
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOG_KEYS or key.startswith("_"):
                continue
            if key not in ALLOWED_EXTRA_KEYS:
                dropped.append(key)
                _note_dropped(key)
                continue
            if key in _CONTRACT_FIELDS and payload.get(key) not in (
                None,
                _UNBOUND_RUN_ID,
            ):
                # A bound context outranks an `extra` of the same name.
                # The reverse — filling `job_id` from `extra` when
                # nothing bound it — is how today's call sites keep
                # working before WO-A10 binds the context at the edge.
                continue
            if key in USER_CONTENT_KEYS and not content_capture_enabled():
                payload[key] = _elide(value)
                continue
            payload[key] = _bound_value(value)

        if dropped:
            reported = sorted(dropped)[:MAX_REPORTED_DROPPED_KEYS]
            payload[FIELD_DROPPED_KEYS] = [_truncate(k) for k in reported]
            payload[FIELD_DROPPED_COUNT] = len(dropped)

        if record.exc_info:
            # A traceback repeats whatever the failing call was holding
            # — including the connection URL that started ADR 0042.
            payload[FIELD_EXCEPTION] = _scrub(self.formatException(record.exc_info))

        # Only our own loggers are held to the registry: a library's
        # log message is prose, not an event name, and flagging every
        # httpx line would make the field meaningless.
        if record.name.startswith("src.") and message not in KNOWN_EVENTS:
            payload[FIELD_UNREGISTERED_EVENT] = True

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

    Retained as a whole-string function even though `redact_text` now
    scrubs URL userinfo out of free text: this one parses, so it is
    exact where the regex is heuristic, and it returns `***` for input
    it cannot parse rather than passing an unproven string through.
    Call sites that know they hold a URL should keep using it.

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

    Three ContextVars ride along: the `RequestContext` (ADR 0067 — one
    frozen record holding `run_id`, `job_id`, `request_id`, `job_kind`,
    `principal_hash` and `worker_id`, where ADR 0012 carried `run_id`
    alone), the cost accumulator, and the job's cancel token (ADR 0047 —
    without it, LLM calls made from a fan-out worker cannot see that
    their job was cancelled and keep spending after the runner gave up).

    Widening the snapshot from one field to the whole context is what
    makes a reader thread's LLM call attributable to the request and
    principal that paid for it, rather than only to the run. The
    signature is unchanged on purpose: the runner's thread pools call
    this, and they belong to another work order.

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

    parent_context = current_context()
    parent_costs = _costs._current_costs.get()
    parent_cancel = _current_cancel_token.get()

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        ctx_token = attach_context(parent_context)
        cost_token = _costs._current_costs.set(parent_costs)
        cancel_token = _current_cancel_token.set(parent_cancel)
        try:
            return fn(*args, **kwargs)
        finally:
            reset_context(ctx_token)
            _costs._current_costs.reset(cost_token)
            _current_cancel_token.reset(cancel_token)

    return wrapped
