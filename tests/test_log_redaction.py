"""Log hygiene: URL redaction, UTC timestamps, library-logger opt-out.

Covers the ADR 0042 observability fixes: `redact_url` keeps
connection-string credentials out of the indexed log stream, the
`JsonFormatter` timestamp is UTC with millisecond precision (so
cross-host timelines are unambiguous and sub-second ordering is
visible), and the httpx/anthropic logger demotion no longer defeats
`LOG_LEVEL=DEBUG` + `ANTHROPIC_LOG=debug`.

ADR 0067 widens redaction from that one rule with one call site to five
rules applied to every string the formatter emits. The reason is what
actually leaked: not a call site logging a password on purpose, but a
connection error whose *message* carried the URL, and the traceback
that repeated it. So the rules run over the message and the formatted
exception too, and each one has its own test below — a rule with no
test is a rule nobody will notice regressing.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.observability import JsonFormatter, redact_text, redact_url

pytestmark = pytest.mark.unit


class TestRedactUrl:
    def test_postgres_url_password_is_stripped(self) -> None:
        assert (
            redact_url("postgresql://arxiv_prod:S3cr3t@db.internal:5432/arxiv")
            == "postgresql://***@db.internal:5432/arxiv"
        )

    def test_redis_password_only_userinfo_is_stripped(self) -> None:
        # Redis auth URLs often carry `:token@` with an empty user.
        assert (
            redact_url("rediss://:R3d1sTok3n@cache.internal:6380/0")
            == "rediss://***@cache.internal:6380/0"
        )

    def test_user_without_password_is_still_hidden(self) -> None:
        # A bare username is identity data; hide it the same way.
        assert (
            redact_url("postgresql://arxiv@db:5432/arxiv")
            == "postgresql://***@db:5432/arxiv"
        )

    def test_url_without_userinfo_is_unchanged(self) -> None:
        assert (
            redact_url("redis://redis:6379/0") == "redis://redis:6379/0"
        )

    def test_empty_string_is_unchanged(self) -> None:
        assert redact_url("") == ""

    def test_redacted_value_never_contains_the_password(self) -> None:
        # The property the log platform depends on, stated directly.
        secret = "Sup3r-S3cret-Pw"
        assert secret not in redact_url(
            f"postgresql://user:{secret}@host:5432/db"
        )


class TestRedactTextUrlCredentials:
    """The `redact_url` property, restated for credentials found in prose.

    `redact_url` parses; this one matches. Both must hold the same
    property — the secret does not appear in the output — because the
    place a connection string usually shows up is inside a sentence
    somebody else wrote.
    """

    def test_a_url_inside_a_sentence_loses_its_userinfo(self) -> None:
        assert redact_text(
            "connection to postgresql://arxiv:S3cr3t@db.internal:5432/arxiv refused"
        ) == "connection to postgresql://***@db.internal:5432/arxiv refused"

    def test_the_password_is_gone_whatever_the_surrounding_text(self) -> None:
        secret = "Sup3r-S3cret-Pw"
        assert secret not in redact_text(
            f"ConnectionError: redis://user:{secret}@cache:6379/0 timed out"
        )

    def test_a_url_without_credentials_survives_intact(self) -> None:
        # The host and path are the diagnostic half; deleting them to be
        # safe would make the rule useless and the logs worse.
        assert redact_text("GET https://arxiv.org/abs/2401.00001") == (
            "GET https://arxiv.org/abs/2401.00001"
        )


class TestRedactTextBearerTokens:
    def test_an_authorization_header_echoed_into_a_log_is_scrubbed(self) -> None:
        assert redact_text("Authorization: Bearer abc123.def456-ghi789") == (
            "Authorization: Bearer ***"
        )

    def test_the_scheme_is_matched_case_insensitively(self) -> None:
        # Clients send `bearer`, `Bearer` and `BEARER`; a case-sensitive
        # rule would catch two of three.
        assert "tok3nvalue" not in redact_text("bearer tok3nvalue")
        assert "tok3nvalue" not in redact_text("BEARER tok3nvalue")

    def test_the_word_bearer_in_ordinary_prose_is_left_alone(self) -> None:
        assert redact_text("the bearer of bad news") == "the bearer of bad news"


class TestRedactTextApiKeys:
    def test_an_sk_style_key_is_replaced_by_its_prefix(self) -> None:
        assert redact_text("using sk-ant-api03-AbCdEf123456ghijkl") == "using sk-***"

    def test_the_key_body_never_survives_anywhere_in_the_output(self) -> None:
        body = "AbCdEf123456ghijklMnOpQr"
        assert body not in redact_text(f"auth failed for sk-{body} on retry 2")

    def test_a_short_sk_prefixed_word_is_not_a_key(self) -> None:
        # `sk-` is not rare enough on its own to redact a three-letter
        # tail; the length floor is what makes the rule specific.
        assert redact_text("sk-1") == "sk-1"


class TestRedactTextEmailAddresses:
    def test_the_local_part_goes_and_the_domain_stays(self) -> None:
        # The domain says which tenant; the local part is the person.
        assert redact_text("contact a.researcher+arxiv@example.ac.uk") == (
            "contact ***@example.ac.uk"
        )

    def test_an_address_inside_a_larger_record_is_still_caught(self) -> None:
        assert "jane.doe" not in redact_text(
            "paper metadata: author=Jane Doe <jane.doe@lab.example.org>"
        )

    def test_an_at_sign_that_is_not_an_address_is_left_alone(self) -> None:
        assert redact_text("decorator @property on line 12") == (
            "decorator @property on line 12"
        )


class TestRedactTextBase64Blobs:
    def test_a_long_encoded_blob_is_replaced_by_its_length(self) -> None:
        blob = "QWxhZGRpbjpvcGVuIHNlc2FtZQ" * 3
        redacted = redact_text(f"token={blob}")

        assert blob not in redacted
        assert redacted == f"token=***[{len(blob)} chars]"

    def test_a_long_lowercase_hex_digest_is_not_a_blob(self) -> None:
        # A job id is a 32-character hex string and a checkpoint hash is
        # 64. Redacting those would delete the ids operators join on —
        # mixed case plus a digit is what separates a secret from a name.
        digest = "a" * 40
        assert redact_text(digest) == digest

    def test_a_long_identifier_without_digits_is_not_a_blob(self) -> None:
        name = "SomeVeryLongCamelCaseIdentifierThatKeepsGoingAndGoing"
        assert redact_text(name) == name


class TestRedactionReachesEveryStringOnTheLine:
    """Message, `extra` and traceback — the three places the leak lived."""

    def _line(self, msg: str, *, exc: BaseException | None = None, **extra: object) -> str:
        record = logging.LogRecord(
            name="src.tools.postgres_pool",
            level=logging.ERROR,
            pathname="t.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return JsonFormatter().format(record)

    def test_a_credential_in_the_message_is_scrubbed(self) -> None:
        line = self._line("postgres://arxiv:S3cr3t@db:5432/arxiv unreachable")
        assert "S3cr3t" not in line

    def test_a_credential_in_an_extra_value_is_scrubbed(self) -> None:
        line = self._line("postgres_pool_opened", url="redis://:R3d1sTok3n@c:6379/0")
        assert "R3d1sTok3n" not in line
        assert json.loads(line)["url"] == "redis://***@c:6379/0"

    def test_a_credential_in_the_traceback_is_scrubbed(self) -> None:
        # This is the one that bit: the call site logged nothing
        # sensitive, and the exception it re-raised carried the URL.
        try:
            raise ConnectionError("could not connect to postgres://u:P4ss@db/x")
        except ConnectionError as exc:
            line = self._line("postgres_pool_opened", exc=exc)

        assert "P4ss" not in line
        assert "postgres://***@db/x" in json.loads(line)["exception"]


class TestJsonFormatterTimestamp:
    def _format_record(self) -> tuple[logging.LogRecord, dict[str, object]]:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="event",
            args=(),
            exc_info=None,
        )
        payload = json.loads(JsonFormatter().format(record))
        return record, payload

    def test_ts_is_timezone_aware_utc(self) -> None:
        _, payload = self._format_record()
        ts = datetime.fromisoformat(str(payload["ts"]))
        assert ts.tzinfo is not None
        assert ts.utcoffset() == timedelta(0)

    def test_ts_round_trips_to_record_created_within_a_millisecond(
        self,
    ) -> None:
        record, payload = self._format_record()
        ts = datetime.fromisoformat(str(payload["ts"]))
        assert abs(ts.timestamp() - record.created) < 0.001


_LIBRARY_LOGGERS = ("httpx", "httpcore", "anthropic", "urllib3")


class TestLibraryLoggerDemotion:
    """`_configure_root_once` demotes noisy HTTP-client loggers to
    WARNING — but only when the app itself isn't at DEBUG, so the
    documented `ANTHROPIC_LOG=debug` escape hatch works (ADR 0042).
    """

    def _run_configure(
        self, monkeypatch: pytest.MonkeyPatch, level: str
    ) -> None:
        import src.observability.logging as logging_module

        root = logging.getLogger()
        saved_level = root.level
        saved_handlers = list(root.handlers)
        saved_lib = {
            name: logging.getLogger(name).level for name in _LIBRARY_LOGGERS
        }
        monkeypatch.setattr(
            logging_module, "settings", SimpleNamespace(log_level=level)
        )
        monkeypatch.setattr(logging_module, "_configured_root", False)
        try:
            for name in _LIBRARY_LOGGERS:
                logging.getLogger(name).setLevel(logging.NOTSET)
            logging_module._configure_root_once()
            self.observed = {
                name: logging.getLogger(name).getEffectiveLevel()
                for name in _LIBRARY_LOGGERS
            }
        finally:
            # Undo the side effects on the process-global logging tree
            # so other tests see the state they expect.
            root.setLevel(saved_level)
            for handler in list(root.handlers):
                if handler not in saved_handlers:
                    root.removeHandler(handler)
            for name, lib_level in saved_lib.items():
                logging.getLogger(name).setLevel(lib_level)

    def test_info_level_demotes_library_loggers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run_configure(monkeypatch, "INFO")
        assert all(
            level == logging.WARNING for level in self.observed.values()
        )

    def test_debug_level_leaves_library_loggers_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._run_configure(monkeypatch, "DEBUG")
        assert all(
            level == logging.DEBUG for level in self.observed.values()
        )
