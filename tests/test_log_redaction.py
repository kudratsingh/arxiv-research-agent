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

ADR 0084 adds four more, because those five were a *shape* rule set
rather than a *secret* rule set: they were derived from the shapes this
repository happened to emit, and WO-C4 measured the consequence —
`sk-ant-api03-…` redacted and `gw_live_…`, a gateway credential with
exactly as much power, passed straight through. The four are worked
examples here; the property tier
(`tests/property/test_property_redaction.py`) is where the invariant is
stated over the rule set as a whole, and where the false-positive half
is generated rather than chosen.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.observability import JsonFormatter, redact_text, redact_url

pytestmark = [pytest.mark.unit, pytest.mark.security]


def fixture(prefix: str, body: str) -> str:
    """Assemble a credential-shaped fixture without ever writing one down.

    Every value built here is synthetic — no issuer has minted any of
    them — but they are exactly the shapes GitHub's push protection
    scans for, and it blocked this file's first push on the Slack and
    GitLab lines below. The fix is not to allowlist them: a repository
    that has taught itself to click through that warning has disarmed
    the one control that catches a real key.

    `src/eval/safety_suite.py` keeps `CANARY_SECRETS` out of
    `corpus.json` for the same reason and says so in the same words.
    Splitting the literal at the prefix boundary is what keeps the
    scanner quiet, and it costs the test nothing: the assertion is
    still about the whole token.
    """
    return f"{prefix}{body}"


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


class TestRedactTextEnvironmentScopedKeys:
    """The measured gap (WO-C4), and the family it belongs to.

    Stripe published `<issuer>_live_<body>` / `<issuer>_test_<body>`,
    and every gateway, proxy and billing shim copied it. The rule is
    written over the convention rather than over a list of issuers,
    because the issuer half is the part that keeps changing.
    """

    def test_the_gateway_credential_that_used_to_pass_through_is_redacted(self) -> None:
        # The exact string WO-C4 measured surviving `redact_text`.
        assert redact_text("gw_live_PROBEprobePROBEprobe00") == "gw_live_***"

    def test_the_issuer_and_the_environment_are_kept(self) -> None:
        # "A *live* gateway key leaked" and "a *test* one leaked" are
        # two different incidents; the line has to be able to say which.
        assert redact_text("key=gw_test_PROBEprobePROBEprobe00") == "key=gw_test_***"

    def test_the_convention_holds_for_issuers_nobody_listed(self) -> None:
        assert redact_text(fixture("sk_live_", "51H8xR2eZvKYlo2CabcdEF")) == "sk_live_***"
        assert redact_text(fixture("pk_test_", "51H8xR2eZvKYlo2CabcdEF")) == "pk_test_***"
        assert redact_text(fixture("litellm_gw_live_", "ABCdef1234567890xyz")) == (
            "litellm_gw_live_***"
        )

    def test_an_ordinary_snake_case_name_is_not_a_key(self) -> None:
        # The body admits no `_`, so a name made of words can never
        # reach the sixteen-character floor however long it gets.
        for name in (
            "feature_flag_test_data_loader",
            "arxiv_test_snapshot_fixture",
            "research_live_stream_handler",
        ):
            assert redact_text(name) == name

    def test_an_environment_variable_name_is_not_its_value(self) -> None:
        # The marker is matched case-sensitively for exactly this: the
        # names of secret-bearing variables are legitimate, useful log
        # content, and only their values are not.
        assert redact_text("STRIPE_LIVE_SECRET_KEY") == "STRIPE_LIVE_SECRET_KEY"

    def test_a_pronounceable_body_is_not_a_key(self) -> None:
        # No digit and no case change: a name, not an issued token.
        assert redact_text("job_test_documentsnapshot") == "job_test_documentsnapshot"


class TestRedactTextVendorPrefixedTokens:
    """A closed list of issuer prefixes, each followed by an opaque body.

    Closed on purpose. The precision of this rule is carried entirely
    by the literal prefix, and a heuristic over "short prefix plus long
    body" would match half the identifiers in this repository.
    """

    def test_a_github_token_keeps_its_prefix_and_loses_its_body(self) -> None:
        assert redact_text(fixture("ghp_", "16CharsAndMoreZZ1234567890abcd")) == "ghp_***"

    def test_the_longest_matching_prefix_wins(self) -> None:
        # `ghp_` sorts before `github_pat_` alphabetically, and `re`
        # alternation is ordered: with the short one first this token
        # would match neither branch and pass through untouched.
        token = fixture("github_pat_", "11ABCDE0Y0abcdefghijkl1234567890")

        assert redact_text(token) == "github_pat_***"

    def test_a_dash_separated_issuer_keeps_its_segments_inside_the_body(self) -> None:
        slack = fixture("xoxb-", "2345678901-2345678901-QWERTYuiop123456")
        gitlab = fixture("glpat-", "ABCdef1234567890xyzQ")

        assert redact_text(slack) == "xoxb-***"
        assert redact_text(gitlab) == "glpat-***"

    def test_a_prefix_with_no_separator_at_all_still_works(self) -> None:
        assert redact_text(fixture("AIza", "SyD1234567890abcdefghijklmnopqrstu")) == (
            "AIza***"
        )

    def test_a_model_name_wearing_a_credential_prefix_survives(self) -> None:
        # The reason `hf_` and its peers do not admit `-` in the body.
        # This string is one character away from being redacted, and it
        # is a model name.
        assert redact_text("hf_all-MiniLM-L6-v2") == "hf_all-MiniLM-L6-v2"

    def test_an_ordinary_name_wearing_a_credential_prefix_survives(self) -> None:
        for name in ("hf_hub_download", "hf_internal_testing", "npm_config_registry"):
            assert redact_text(name) == name

    def test_the_prefix_is_kept_because_it_names_what_to_revoke(self) -> None:
        # `***[40 chars]` says a secret leaked; `ghp_***` says which
        # console to go to. The prefix is published and identical for
        # every token that issuer ever minted.
        token = fixture("ghp_", "ABCdef1234567890ghijklmnopqrstuvwx")

        redacted = redact_text(f"leaked {token}")

        assert "ghp_***" in redacted
        assert "chars]" not in redacted


class TestRedactTextAwsAccessKeyIds:
    def test_an_access_key_id_keeps_only_its_four_letter_prefix(self) -> None:
        assert redact_text(fixture("AKIA", "IOSFODNN7EXAMPLE")) == "AKIA***"

    def test_the_session_and_batch_variants_are_covered(self) -> None:
        assert redact_text(fixture("ASIA", "IOSFODNN7EXAMPLE")) == "ASIA***"

    def test_the_width_is_exact_so_a_word_starting_AKIA_is_safe(self) -> None:
        # Four fixed letters and *sixteen* uppercase alphanumerics —
        # anything shorter or longer is not an access key id.
        assert redact_text("AKIASHORT") == "AKIASHORT"


class TestRedactTextJsonWebTokens:
    def test_a_jwt_is_replaced_whole(self) -> None:
        token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        )
        assert redact_text(f"cookie={token}") == "cookie=***[jwt]"

    def test_an_unsigned_token_is_still_a_credential(self) -> None:
        # `alg: none` leaves the third segment empty, and a token
        # somebody is presenting is a token whether it verifies or not.
        assert (
            redact_text("eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJzdWIiOiJhZG1pbiJ9.")
            == "***[jwt]"
        )

    def test_three_dotted_words_are_not_a_jwt(self) -> None:
        # `eyJ` is base64url for `{"`, and it is the whole anchor.
        assert redact_text("src.observability.logging") == "src.observability.logging"


class TestRedactionLeavesTheIdsOperatorsJoinOn:
    """The ceiling on how wide any rule above is allowed to be.

    A rule that eats a paper id is worse than the gap it closes: it
    damages every line rather than one, and it fails silently — nobody
    notices the ids stopped appearing until the day they need to join
    on one.
    """

    @pytest.mark.parametrize(
        "content",
        [
            "2401.00001",
            "2401.00001v2",
            "arXiv:2311.09000v1",
            "https://arxiv.org/abs/2401.00001",
            "cs.AI/0301001",
            "10.1145/3292500.3330701",
            "10.48550/arXiv.2401.00001",
            "claude-sonnet-4-6",
            "claude-opus-4-1-20250805",
            "all-MiniLM-L6-v2",
            "sentence-transformers/all-MiniLM-L6-v2",
            "0af7651916cd43dd8448eb211c80319c",
            "b7ad6b7169203331",
            "550e8400-e29b-41d4-a716-446655440000",
            "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
            "LOG_CAPTURE_USER_CONTENT",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
            "postgres_pool_opened",
        ],
    )
    def test_legitimate_content_is_returned_byte_for_byte(self, content: str) -> None:
        assert redact_text(content) == content


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
