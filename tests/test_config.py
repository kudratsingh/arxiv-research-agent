"""Unit tests for the typed config surface.

Verifies field types, validation ranges, env-var loading, defaults,
immutability, and the ADR-0046 Literal-typed enum fields. No
network, no side effects.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from src.config import (
    BOOL_FALSE_TOKENS,
    BOOL_TRUE_TOKENS,
    CONTENT_CAPTURE_ENV,
    CONTENT_CAPTURE_ENV_ALIAS,
    PRINCIPAL_SALT_ENV,
    TRACE_SAMPLE_RATIO_ENV,
    Settings,
    parse_bool_flag,
)

pytestmark = pytest.mark.unit


class TestDefaults:
    def test_anthropic_defaults(self) -> None:
        s = Settings(anthropic_api_key="sk-test")
        assert s.anthropic_model == "claude-sonnet-4-6"
        assert s.anthropic_max_retries == 4
        assert s.anthropic_timeout_sec == 120.0

    def test_search_defaults(self) -> None:
        s = Settings()
        assert s.use_mock_data is False
        assert s.max_papers == 10
        assert s.results_per_query == 5

    def test_reader_defaults(self) -> None:
        s = Settings()
        assert s.reader_max_workers == 5
        assert s.reader_max_chunks_per_paper == 5

    def test_chunker_defaults(self) -> None:
        s = Settings()
        assert s.chunker_max_tokens == 800
        assert s.chunker_overlap_tokens == 100

    def test_critic_defaults(self) -> None:
        s = Settings()
        assert s.max_iterations == 3

    def test_logging_defaults(self) -> None:
        s = Settings()
        assert s.log_level == "INFO"

    def test_content_capture_and_sampling_defaults_change_nothing(self) -> None:
        """WO-B4's whole obligation: the fold-in must be invisible.

        Content capture stays off, which is what the OpenTelemetry
        GenAI conventions require of an instrumentation, and the
        sampling ratio stays `None` — "install no sampler", so the
        SDK's own `OTEL_TRACES_SAMPLER` handling is left alone.
        """
        s = Settings()
        assert s.log_capture_user_content is False
        assert s.trace_sample_ratio is None


class TestEnvLoading:
    def test_reads_api_key_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-abc")
        s = Settings()
        assert s.anthropic_api_key == "sk-abc"

    def test_reads_use_mock_data_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("USE_MOCK_DATA", "true")
        s = Settings()
        assert s.use_mock_data is True

    def test_bool_coercion_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # pydantic-settings accepts "1"/"0", "true"/"false", "yes"/"no", case-insensitive.
        for value in ("True", "TRUE", "1", "yes"):
            monkeypatch.setenv("USE_MOCK_DATA", value)
            assert Settings().use_mock_data is True
        for value in ("False", "FALSE", "0", "no"):
            monkeypatch.setenv("USE_MOCK_DATA", value)
            assert Settings().use_mock_data is False

    def test_env_vars_override_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "7")
        monkeypatch.setenv("MAX_PAPERS", "20")
        s = Settings()
        assert s.anthropic_max_retries == 7
        assert s.max_papers == 20

    def test_case_insensitive_env_var_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # SettingsConfigDict has case_sensitive=False.
        monkeypatch.setenv("anthropic_model", "claude-haiku-4-5-20251001")
        assert (
            Settings().anthropic_model == "claude-haiku-4-5-20251001"
        )


class TestValidation:
    def test_max_retries_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            Settings(anthropic_max_retries=100)

    def test_max_retries_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            Settings(anthropic_max_retries=-1)

    def test_timeout_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(anthropic_timeout_sec=0)

    def test_timeout_over_sdk_default_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Settings(anthropic_timeout_sec=1000)

    def test_max_iterations_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            Settings(max_iterations=999)

    def test_chunker_max_tokens_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            Settings(chunker_max_tokens=1)


class TestImmutability:
    def test_settings_are_frozen(self) -> None:
        s = Settings()
        with pytest.raises(ValidationError):
            s.max_papers = 42  # type: ignore[misc]


class TestEnumFieldsAreLiteral:
    """ADR 0046: enum-valued settings die at load on unknown values.

    Before this, `job_store` and friends were bare `str` — a typo'd
    env var (`JOB_STORE=Redis`, `PAPER_CACHE=postgress`) sailed
    through validation and silently selected the downstream fallback
    branch (in-memory store, disk cache, ...). Every case here fails
    against the pre-ADR-0046 config surface.
    """

    @pytest.mark.parametrize(
        ("field", "bad_value"),
        [
            ("job_store", "Redis"),  # case matters — no silent memory fallback
            ("job_store", "postgres"),
            ("conversation_store", "redis"),
            ("checkpoint_backend", "sqllite"),
            ("rate_limit_backend", "in-memory"),
            ("paper_cache", "postgress"),
            ("embedding_cache", "disk"),
            ("log_level", "DEBG"),
        ],
    )
    def test_unknown_value_rejected_at_load(
        self, field: str, bad_value: str
    ) -> None:
        with pytest.raises(ValidationError) as exc_info:
            Settings(**{field: bad_value})
        # The error names the offending field so an operator reading
        # the crash log doesn't have to diff their whole env.
        assert field in str(exc_info.value)

    @pytest.mark.parametrize(
        ("field", "values"),
        [
            ("job_store", ("memory", "redis")),
            ("conversation_store", ("memory", "postgres")),
            ("checkpoint_backend", ("sqlite", "postgres")),
            ("rate_limit_backend", ("memory", "redis")),
            ("paper_cache", ("disk", "postgres")),
            ("embedding_cache", ("none", "postgres")),
        ],
    )
    def test_every_documented_value_accepted(
        self, field: str, values: tuple[str, ...]
    ) -> None:
        for value in values:
            assert getattr(Settings(**{field: value}), field) == value

    def test_unknown_value_rejected_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real failure path is an env var, not a kwarg."""
        monkeypatch.setenv("JOB_STORE", "redsi")
        with pytest.raises(ValidationError):
            Settings()

    def test_log_level_case_insensitive(self) -> None:
        """`LOG_LEVEL=debug` predates the Literal type — the before-
        validator uppercases so existing deployments keep booting."""
        assert Settings(log_level="debug").log_level == "DEBUG"  # type: ignore[arg-type]
        assert Settings(log_level="Warning").log_level == "WARNING"  # type: ignore[arg-type]


class TestExtraKeysIgnored:
    def test_unknown_env_vars_dont_break_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # extra="ignore" in the model_config — random extra env vars shouldn't crash.
        monkeypatch.setenv("SOMETHING_UNRELATED", "value")
        Settings()  # should not raise


class TestTheContentCaptureFlagKeepsBothItsNames:
    """WO-B4. One field, two environment variables, no migration.

    `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT` is the name the
    OpenTelemetry GenAI conventions define; `LOG_CAPTURE_USER_CONTENT`
    is the repo-local name ADR 0067 shipped. Both were read directly
    from `os.environ` before this work order. An operator who set either
    one has to keep getting content capture whatever `Settings` calls
    the field internally, so the fold-in is an alias rather than a
    rename.
    """

    def test_the_conventional_name_still_turns_it_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONTENT_CAPTURE_ENV, "true")
        assert Settings().log_capture_user_content is True

    def test_the_repo_local_name_still_turns_it_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CONTENT_CAPTURE_ENV_ALIAS, "true")
        assert Settings().log_capture_user_content is True

    def test_the_conventional_name_is_the_one_opentelemetry_defines(self) -> None:
        # Using any other spelling would let an operator who had already
        # set the standard variable believe they had opted in.
        assert CONTENT_CAPTURE_ENV == (
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        )
        assert CONTENT_CAPTURE_ENV_ALIAS == "LOG_CAPTURE_USER_CONTENT"

    def test_the_conventional_name_wins_when_the_two_disagree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Alias order is precedence, and it is a deliberate narrowing.

        While these lived in `logging.py` the rule was "either being
        truthy enables capture", so this combination turned content on.
        `AliasChoices` takes the first name that is *present*, so the
        conventional flag now decides — and the direction of the change
        is content staying off, which is the safe one.
        """
        monkeypatch.setenv(CONTENT_CAPTURE_ENV, "false")
        monkeypatch.setenv(CONTENT_CAPTURE_ENV_ALIAS, "true")
        assert Settings().log_capture_user_content is False

    def test_the_field_is_still_settable_by_its_own_name(self) -> None:
        # `populate_by_name` — without it the alias would make every
        # `Settings(log_capture_user_content=...)` in the suite a
        # validation error.
        assert Settings(log_capture_user_content=True).log_capture_user_content is True

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_value_is_off_rather_than_a_boot_failure(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        """`LOG_CAPTURE_USER_CONTENT=` is how Compose spells "unset".

        pydantic's `bool` parser rejects the empty string, so without
        the before-validator this fold-in would turn a blank line in a
        `.env` into a process that will not start.
        """
        monkeypatch.setenv(CONTENT_CAPTURE_ENV_ALIAS, blank)
        assert Settings().log_capture_user_content is False

    def test_a_value_that_is_neither_true_nor_false_is_refused_at_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point of the fold-in, on the flag where it matters most.

        `LOG_CAPTURE_USER_CONTENT=ture` used to read as off — the right
        answer by accident, from a resolver that treated everything
        non-truthy as false. An operator who typo'd while trying to turn
        capture *on* got silence.
        """
        monkeypatch.setenv(CONTENT_CAPTURE_ENV_ALIAS, "ture")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        message = str(exc_info.value)
        assert "'ture'" in message
        # pydantic reports the *first* alias whichever one supplied the
        # value, so without the validator's own message an operator who
        # typo'd `LOG_CAPTURE_USER_CONTENT` would be told about a
        # variable they have never set.
        assert CONTENT_CAPTURE_ENV_ALIAS in message

    def test_the_live_grammar_is_the_grammar_pydantic_uses(self) -> None:
        """`parse_bool_flag` is re-read live, and must not drift.

        `content_capture_enabled()` re-parses the environment on every
        call rather than reconstructing frozen `Settings`, so it does
        not go through pydantic. If a release widened pydantic's
        boolean grammar, a value that this field accepted at load would
        stop being honoured on a live flip — silently, and in the
        direction of leaking content or hiding it. This is the test
        that would go red first.
        """
        adapter = TypeAdapter(bool)
        for token in BOOL_TRUE_TOKENS:
            assert parse_bool_flag(token) is True
            assert adapter.validate_python(token) is True
        for token in BOOL_FALSE_TOKENS:
            assert parse_bool_flag(token) is False
            assert adapter.validate_python(token) is False
        assert parse_bool_flag("ture") is None
        with pytest.raises(ValidationError):
            adapter.validate_python("ture")
        # Case and surrounding whitespace are the operator's, not a typo.
        assert parse_bool_flag("  TRUE  ") is True
        # A blank is "unset", which for a flag that defaults off is off.
        assert parse_bool_flag("") is False


class TestTheSamplingRatioIsAValidatedFloat:
    """WO-B4. `TRACE_SAMPLE_RATIO` was parsed and clamped by hand."""

    def test_the_environment_variable_still_sets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TRACE_SAMPLE_RATIO_ENV, "0.1")
        assert Settings().trace_sample_ratio == pytest.approx(0.1)

    @pytest.mark.parametrize("value", [0.0, 1.0, 0.5])
    def test_the_whole_closed_interval_is_accepted(self, value: float) -> None:
        assert Settings(trace_sample_ratio=value).trace_sample_ratio == value

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_value_means_install_no_sampler(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        monkeypatch.setenv(TRACE_SAMPLE_RATIO_ENV, blank)
        assert Settings().trace_sample_ratio is None

    @pytest.mark.parametrize("raw", ["9", "10", "-3", "1.0001"])
    def test_a_ratio_outside_the_unit_interval_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """This used to clamp, and clamping was the hazard.

        `TRACE_SAMPLE_RATIO=10` from somebody who meant 10% became 1.0
        and sampled every trace in production — the exact shape of the
        typo ADR 0046 made every other enum-valued knob refuse.
        """
        monkeypatch.setenv(TRACE_SAMPLE_RATIO_ENV, raw)
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "trace_sample_ratio" in str(exc_info.value)

    def test_an_unparseable_ratio_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(TRACE_SAMPLE_RATIO_ENV, "loads")
        with pytest.raises(ValidationError):
            Settings()


class TestThePrincipalSaltIsASecretSetting:
    """WO-C3. The last flag that read `os.environ` directly, folded in.

    WO-B4 took the other three and left this one, for two reasons ADR
    0067 wrote down: it is a *secret*, and its "empty means ephemeral"
    branch is load-bearing. Both survive the fold-in or the fold-in was
    not worth doing — the secret half is pinned here, the ephemeral half
    in `tests/test_log_contract.py`, where the salt is actually used.
    """

    def test_the_environment_variable_still_sets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The whole compatibility requirement in one line: an operator
        # who exported this before the fold-in exports it after.
        monkeypatch.setenv(PRINCIPAL_SALT_ENV, "fleet-wide-salt")
        assert Settings().log_principal_salt.get_secret_value() == "fleet-wide-salt"

    def test_the_variable_is_the_name_that_is_already_deployed(self) -> None:
        assert PRINCIPAL_SALT_ENV == "LOG_PRINCIPAL_SALT"

    def test_the_field_is_settable_by_its_own_name(self) -> None:
        assert (
            Settings(log_principal_salt="inline").log_principal_salt.get_secret_value()
            == "inline"
        )

    def test_the_default_is_empty_because_empty_is_what_ephemeral_reads(self) -> None:
        """Not a required field, and not a shared literal default.

        A required field would make every process that has not chosen a
        salt refuse to boot; a non-empty default would ship one salt to
        the whole world, which is worse than no salt at all because it
        looks like one.
        """
        assert Settings().log_principal_salt.get_secret_value() == ""

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_value_is_unset_rather_than_a_salt(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        # `LOG_PRINCIPAL_SALT=` in a Compose file means "not setting
        # this". Accepting it as a salt would be a fleet whose hashes
        # agree with each other and with nothing an operator configured.
        monkeypatch.setenv(PRINCIPAL_SALT_ENV, blank)
        assert Settings().log_principal_salt.get_secret_value() == ""

    def test_a_configured_salt_is_not_stripped(self) -> None:
        # Only a *blank* is special. Trimming a real salt would renumber
        # every `principal_hash` in the fleet on upgrade.
        salt = " pad ded\n"
        assert Settings(log_principal_salt=salt).log_principal_salt.get_secret_value() == salt

    def test_the_salt_cannot_reach_a_repr(self) -> None:
        """`Settings` is built in ~30 test modules and printed by pytest.

        A plain `str` field would put the fleet-wide salt into every
        `-vv` assertion diff and every traceback that carried a
        `Settings` — and a leaked salt returns `principal_hash` to a
        word-list attack, which is the one thing the field exists to
        prevent.
        """
        secret = "salt-that-must-not-appear"
        rendered = Settings(log_principal_salt=secret)
        assert secret not in repr(rendered)
        assert secret not in str(rendered)
        assert secret not in f"{rendered.log_principal_salt}"
        assert secret not in repr(rendered.log_principal_salt)

    def test_the_salt_cannot_reach_a_dump(self) -> None:
        # Both dump shapes, and the stringified dict a debug line would
        # actually emit. `model_dump()` keeps the wrapper, so even a
        # caller that never asked for `mode="json"` gets the mask.
        secret = "salt-that-must-not-appear"
        dumped = Settings(log_principal_salt=secret)
        assert secret not in dumped.model_dump_json()
        assert secret not in str(dumped.model_dump())
        assert secret not in str(dumped.model_dump(mode="json"))
        assert dumped.model_dump()["log_principal_salt"].get_secret_value() == secret


@pytest.mark.unit
def test_lease_refresh_must_leave_margin_under_the_ttl() -> None:
    """A refresh interval with no margin orphans healthy jobs (ADR 0038).

    Both fields validate individually but combine into a broken pair:
    one missed refresh on an ordinary GC pause and a peer's redrive
    sweep reclaims work that is still running.
    """
    Settings(job_lease_refresh_sec=30, job_lease_ttl_sec=90)  # ok

    with pytest.raises(ValidationError):
        Settings(job_lease_refresh_sec=60, job_lease_ttl_sec=90)
    with pytest.raises(ValidationError):
        Settings(job_lease_refresh_sec=45, job_lease_ttl_sec=90)
