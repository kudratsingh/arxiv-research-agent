"""The log contract: correlation, a closed vocabulary, and bounds (ADR 0067).

Three claims are under test here, and each one failed before this
change:

  - **A line is joinable.** `run_id` alone could not connect a log
    record to the request that caused it, the job it ran under, the
    worker executing it, the principal paying for it, or the trace
    recording it. Every one of those now rides on the line — and
    `principal_hash` is a hash, which is the point of the field.
  - **The vocabulary is closed.** Event names and `extra` keys are
    registries, re-derived here from the source so a new call site that
    skips registration fails a test rather than shipping an unindexed
    field or an event no dashboard was told about.
  - **A line is bounded and scrubbed.** `extra` used to be an open door
    into an indexed store: unknown keys merged verbatim, a 100 KB
    report body merged verbatim, a raw user query merged verbatim.

The registry tests deliberately re-parse `src/` rather than asserting
against a checked-in list. A fixture would only prove the fixture and
the constant agree; parsing proves the *code* and the constant agree,
which is the invariant that matters when someone adds a log line.
"""

from __future__ import annotations

import ast
import json
import logging
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider

from src.observability import context as context_module
from src.observability import logging as logging_module
from src.observability.context import (
    RequestContext,
    bind_context,
    clear_context,
    current_context,
    hash_principal,
    reset_context,
)
from src.observability.logging import (
    ALLOWED_EXTRA_KEYS,
    CONTENT_CAPTURE_ENV,
    CONTENT_CAPTURE_ENV_ALIAS,
    KNOWN_EVENTS,
    MAX_EXTRA_ITEMS,
    MAX_EXTRA_VALUE_CHARS,
    USER_CONTENT_KEYS,
    JsonFormatter,
    dropped_extra_key_counts,
    propagate_run_context,
    reset_dropped_extra_key_counts,
)

pytestmark = pytest.mark.unit

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
_LOG_METHODS = frozenset(
    {"debug", "info", "warning", "error", "exception", "critical"}
)
_LOGGER_NAMES = frozenset({"log", "logger", "_log", "LOGGER"})


def _format(
    msg: str = "api_job_submitted",
    *,
    logger: str = "src.api.routes",
    level: int = logging.INFO,
    **extra: Any,
) -> dict[str, Any]:
    """Format one record the way the root handler would, and parse it."""
    record = logging.LogRecord(
        name=logger,
        level=level,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    payload: dict[str, Any] = json.loads(JsonFormatter().format(record))
    return payload


@pytest.fixture(autouse=True)
def _isolated_context() -> Any:
    """Leave no context or drop tally behind for the next test."""
    token = clear_context()
    reset_dropped_extra_key_counts()
    yield
    reset_context(token)
    reset_dropped_extra_key_counts()


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


class TestCorrelationFieldsOnTheLine:
    def test_a_bound_context_puts_every_identifier_on_the_record(self) -> None:
        token = bind_context(
            run_id="rid-1",
            job_id="job-1",
            request_id="req-1",
            job_kind="research",
            principal_hash=hash_principal("acme-prod"),
            worker_id="worker-3",
        )
        try:
            payload = _format()
        finally:
            reset_context(token)

        assert payload["run_id"] == "rid-1"
        assert payload["job_id"] == "job-1"
        assert payload["request_id"] == "req-1"
        assert payload["job_kind"] == "research"
        assert payload["worker_id"] == "worker-3"
        assert payload["principal_hash"] == hash_principal("acme-prod")

    def test_the_principal_field_is_a_hash_and_not_the_key_id(self) -> None:
        # The metric layer refused to carry `key_id` (ADR 0049) and the
        # log layer must not quietly undo that: a metric label lives
        # until the next scrape, a log field lives for the retention
        # window.
        key_id = "acme-prod"
        token = bind_context(principal_hash=hash_principal(key_id))
        try:
            line = JsonFormatter().format(
                logging.LogRecord(
                    "src.api.auth", logging.INFO, "t.py", 1, "api_startup", (), None
                )
            )
        finally:
            reset_context(token)

        assert key_id not in line
        assert json.loads(line)["principal_hash"] != key_id

    def test_an_unbound_context_still_reports_the_run_id_sentinel(self) -> None:
        # `"-"` has meant "no run bound" since ADR 0012; consumers read
        # it, so it is format, not an implementation detail.
        assert _format()["run_id"] == "-"
        assert "job_id" not in _format()
        assert "principal_hash" not in _format()

    def test_every_line_names_the_service_and_version(self) -> None:
        payload = _format()
        assert payload["service"] == context_module.SERVICE_NAME
        assert payload["version"] == context_module.SERVICE_VERSION

    def test_an_empty_key_id_hashes_to_nothing_rather_than_a_shared_bucket(
        self,
    ) -> None:
        # Hashing "" would give every anonymous caller one identical
        # `principal_hash`, which reads as a single very busy principal.
        assert hash_principal("") is None

    def test_the_hash_is_salted_so_a_guessable_key_id_is_not_recoverable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(context_module, "_principal_salt", "salt-a")
        with_a = hash_principal("acme-prod")
        monkeypatch.setattr(context_module, "_principal_salt", "salt-b")
        with_b = hash_principal("acme-prod")

        assert with_a != with_b
        # Stable within one salt, or grouping by principal is impossible.
        assert with_b == hash_principal("acme-prod")


class TestTraceCorrelation:
    def test_an_active_span_puts_its_ids_on_the_record(self) -> None:
        # A local provider, never installed globally: `get_current_span`
        # reads the context the span manager set, so this needs no
        # process-wide tracer and leaks nothing into other tests.
        tracer = TracerProvider().get_tracer(__name__)
        with tracer.start_as_current_span("probe") as span:
            payload = _format()
            span_context = span.get_span_context()

        assert payload["trace_id"] == format(span_context.trace_id, "032x")
        assert payload["span_id"] == format(span_context.span_id, "016x")

    def test_no_active_span_means_no_trace_fields_rather_than_nulls(self) -> None:
        payload = _format()
        assert "trace_id" not in payload
        assert "span_id" not in payload


class TestContextCrossesTheThreadPoolBoundary:
    def test_a_fan_out_worker_inherits_the_whole_context_not_just_the_run_id(
        self,
    ) -> None:
        token = bind_context(
            run_id="rid-parent",
            job_id="job-parent",
            request_id="req-parent",
            principal_hash="deadbeef1234",
        )
        try:
            wrapped = propagate_run_context(current_context)
            with ThreadPoolExecutor(max_workers=2) as pool:
                observed = list(pool.map(lambda _: wrapped(), range(3)))
        finally:
            reset_context(token)

        assert observed == [
            RequestContext(
                run_id="rid-parent",
                job_id="job-parent",
                request_id="req-parent",
                principal_hash="deadbeef1234",
            )
        ] * 3

    def test_a_pooled_thread_keeps_nothing_after_the_wrapped_call_returns(
        self,
    ) -> None:
        # The leak that matters: a thread that ran job A's callable must
        # not attribute job B's lines to job A's principal.
        with ThreadPoolExecutor(max_workers=1) as pool:
            token = bind_context(job_id="job-a", principal_hash="aaaa1111bbbb")
            try:
                pool.submit(propagate_run_context(current_context)).result()
            finally:
                reset_context(token)

            after = pool.submit(current_context).result()

        assert after == RequestContext()


# ---------------------------------------------------------------------------
# The closed vocabulary
# ---------------------------------------------------------------------------


def _emitted_from_source() -> tuple[set[tuple[str, int, str]], set[tuple[str, int, str]]]:
    """Every literal event name and `extra` key `src/` emits.

    Returns two sets of `(file, line, name)` so a failure names the call
    site rather than only the offending string. Only `extra={...}`
    literals are visible — dicts built elsewhere and splatted in are
    registered by hand, and the module comment beside them says so.
    """
    events: set[tuple[str, int, str]] = set()
    keys: set[tuple[str, int, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
            ):
                continue
            base = node.func.value
            base_name = (
                base.id
                if isinstance(base, ast.Name)
                else base.attr
                if isinstance(base, ast.Attribute)
                else ""
            )
            if base_name not in _LOGGER_NAMES:
                continue
            where = str(path.relative_to(_SRC.parent))
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                events.add((where, node.lineno, first.value))
            for keyword in node.keywords:
                if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                    continue
                for key in keyword.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        keys.add((where, node.lineno, key.value))
    return events, keys


class TestTheEventNameSetIsClosed:
    def test_every_event_the_source_emits_is_registered(self) -> None:
        events, _ = _emitted_from_source()
        unregistered = sorted(e for e in events if e[2] not in KNOWN_EVENTS)
        assert not unregistered, (
            "log events missing from KNOWN_EVENTS — register the name in "
            f"src/observability/logging.py: {unregistered}"
        )

    def test_the_registry_reads_as_event_names_rather_than_prose(self) -> None:
        # A closed set only helps if its members are the kind of thing a
        # dashboard filters on. Sentences leak in when a call site
        # passes a message instead of an event.
        malformed = sorted(
            name for name in KNOWN_EVENTS if not re.fullmatch(r"[a-z][a-z0-9_]*", name)
        )
        assert not malformed

    def test_the_formatter_flags_an_unregistered_event_from_our_own_logger(
        self,
    ) -> None:
        assert _format("brand_new_event_nobody_registered").get(
            "unregistered_event"
        )
        assert "unregistered_event" not in _format("api_job_submitted")

    def test_a_library_logger_is_not_held_to_our_registry(self) -> None:
        # httpx logs prose. Flagging it would make the field noise.
        payload = _format("HTTP Request: GET /x 200 OK", logger="httpx")
        assert "unregistered_event" not in payload


class TestTheExtraKeyAllowlistIsClosed:
    def test_every_extra_key_the_source_passes_is_allowlisted(self) -> None:
        _, keys = _emitted_from_source()
        unregistered = sorted(k for k in keys if k[2] not in ALLOWED_EXTRA_KEYS)
        assert not unregistered, (
            "extra keys missing from ALLOWED_EXTRA_KEYS — register the field in "
            f"src/observability/logging.py: {unregistered}"
        )

    def test_an_unknown_key_is_dropped_and_counted(self) -> None:
        payload = _format(job_id="job-1", surprise_field="whatever")

        assert "surprise_field" not in payload
        assert payload["dropped_extra_keys"] == ["surprise_field"]
        assert payload["dropped_extra_count"] == 1
        assert dropped_extra_key_counts()["surprise_field"] == 1
        # The registered key alongside it still gets through.
        assert payload["job_id"] == "job-1"

    def test_the_drop_report_itself_stays_bounded(self) -> None:
        extras = {f"unknown_{i}": i for i in range(40)}
        payload = _format(**extras)

        assert payload["dropped_extra_count"] == 40
        assert len(payload["dropped_extra_keys"]) == (
            logging_module.MAX_REPORTED_DROPPED_KEYS
        )

    def test_a_bound_context_field_cannot_be_overwritten_by_an_extra(self) -> None:
        # Otherwise any call site could attribute its line to another
        # principal, or to a job it is not running.
        token = bind_context(job_id="real-job", principal_hash="realhash1234")
        try:
            payload = _format(job_id="forged-job", principal_hash="forgedhash12")
        finally:
            reset_context(token)

        assert payload["job_id"] == "real-job"
        assert payload["principal_hash"] == "realhash1234"

    def test_an_unbound_context_field_may_still_be_filled_by_an_extra(self) -> None:
        # How today's call sites keep working: the runner passes
        # `job_id` in `extra` and nothing binds a context yet.
        payload = _format(job_id="job-from-extra", worker_id="worker-from-extra")

        assert payload["job_id"] == "job-from-extra"
        assert payload["worker_id"] == "worker-from-extra"


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


class TestValuesAreBounded:
    def test_a_hundred_kilobyte_value_is_truncated_with_a_marker(self) -> None:
        payload = _format(reason="x" * 100_000)
        value = payload["reason"]

        assert len(value) < 100_000
        assert value.startswith("x" * MAX_EXTRA_VALUE_CHARS)
        assert "truncated" in value

    def test_a_value_under_the_cap_is_left_alone(self) -> None:
        assert _format(reason="short")["reason"] == "short"

    def test_a_long_list_is_clipped_and_says_how_many_it_dropped(self) -> None:
        payload = _format(nodes=[f"node-{i}" for i in range(500)])
        value = payload["nodes"]

        assert len(value) == MAX_EXTRA_ITEMS + 1
        assert value[-1] == f"+{500 - MAX_EXTRA_ITEMS} more items"

    def test_a_nested_mapping_is_bounded_at_every_level(self) -> None:
        payload = _format(per_model={"claude": {"note": "y" * 100_000}})
        assert len(payload["per_model"]["claude"]["note"]) < 100_000

    def test_numbers_pass_through_untouched(self) -> None:
        payload = _format(cost_usd=0.42, iterations=3, dry_run=True)
        assert payload["cost_usd"] == 0.42
        assert payload["iterations"] == 3
        assert payload["dry_run"] is True

    def test_bytes_are_reported_by_size_rather_than_decoded(self) -> None:
        # Decoding is how a binary payload becomes indexed text.
        assert _format(raw_type=b"\x00\x01\x02")["raw_type"] == "<3 bytes>"


class TestUserContentIsRedactedByDefault:
    def test_a_report_body_passed_as_extra_never_reaches_the_output(self) -> None:
        body = "SECRET REPORT BODY about diffusion models. " * 2000
        line = JsonFormatter().format(
            _record("api_job_terminal_persist_failed", result=body)
        )

        assert "SECRET REPORT BODY" not in line
        assert json.loads(line)["result"] == f"[redacted: {len(body)} chars]"

    def test_a_raw_user_query_never_reaches_the_output(self) -> None:
        query = "what does my company's internal benchmark say about RAG"
        line = JsonFormatter().format(_record("api_job_submitted", query=query))

        assert query not in line
        assert json.loads(line)["query"].startswith("[redacted:")

    def test_the_elision_keeps_the_size_because_that_is_the_operational_fact(
        self,
    ) -> None:
        # "Did the model produce anything" is answerable without the text.
        assert _format(result="a" * 41_832)["result"] == "[redacted: 41832 chars]"

    def test_a_non_string_content_value_is_named_by_type_only(self) -> None:
        assert _format(payload={"turn": "learner text"})["payload"] == (
            "[redacted: dict]"
        )

    @pytest.mark.parametrize(
        "flag", [CONTENT_CAPTURE_ENV, CONTENT_CAPTURE_ENV_ALIAS]
    )
    def test_either_opt_in_flag_lets_content_through(
        self, monkeypatch: pytest.MonkeyPatch, flag: str
    ) -> None:
        monkeypatch.setenv(flag, "1")
        assert _format(query="how do transformers work")["query"] == (
            "how do transformers work"
        )

    def test_the_conventional_flag_is_the_one_opentelemetry_defines(self) -> None:
        # The GenAI conventions define exactly one opt-in variable for
        # message content; using another name would make an operator
        # who already set the standard one think they had.
        assert CONTENT_CAPTURE_ENV == (
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        )

    def test_an_unset_flag_is_off_and_a_falsey_one_stays_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONTENT_CAPTURE_ENV, "false")
        monkeypatch.setenv(CONTENT_CAPTURE_ENV_ALIAS, "0")
        assert _format(query="secret")["query"].startswith("[redacted:")

    def test_every_content_key_that_is_live_today_is_also_allowlisted(self) -> None:
        # A content key outside the allowlist is dropped rather than
        # elided, which is safe but silent — worth knowing which is which.
        _, keys = _emitted_from_source()
        live = {name for _, _, name in keys}
        for key in USER_CONTENT_KEYS & live:
            assert key in ALLOWED_EXTRA_KEYS


def _record(msg: str, **extra: Any) -> logging.LogRecord:
    record = logging.LogRecord(
        "src.api.runner", logging.ERROR, "t.py", 1, msg, (), None
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record
