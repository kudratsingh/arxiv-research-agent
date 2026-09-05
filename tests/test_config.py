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

    def test_standalone_storage_defaults(self) -> None:
        """`README.md`'s R11: outside Compose, nothing needs a service.

        These three defaults existed only as Pydantic field values until
        WO-C2, and no test asserted any of them — which left the
        sentence a reader trusts before their first `make run` (an
        in-memory job store, SQLite checkpoints, a disk paper cache)
        free to drift against the code. Flipping any one of them to its
        service-backed option would leave every Python-only quickstart
        failing to reach something the quickstart never says to start.

        `tests/test_documented_claims.py::TestTheStandaloneDefaults` is
        the other half: it reads the same three backends out of the
        README sentence and compares them against these fields, so the
        sentence and the shipped values cannot part company either.
        """
        s = Settings()
        assert s.job_store == "memory"
        assert s.checkpoint_backend == "sqlite"
        assert s.paper_cache == "disk"

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
        # `.get_secret_value()` since WO-C4 made the field a
        # `SecretStr`. The bare `==` this line used to carry is exactly
        # the comparison a `SecretStr` silently loses, which is what
        # `TestTheApiKeyIsASecret` below exists to pin.
        assert s.anthropic_api_key.get_secret_value() == "sk-abc"

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


class TestTheApiKeyIsASecret:
    """WO-C4. The paid credential gets the treatment the salt already had.

    WO-C3 made `log_principal_salt` a `SecretStr` and proved the mask
    against pydantic itself. It recorded, and did not fix, that the
    field sitting two lines above it — the Anthropic API key — was
    still a plain `str` and therefore still printed in full by every
    `Settings` repr. This class is the same proof for the credential,
    plus the half the salt never needed: the zero-spend sentinel runs
    through this field on every local and CI path, and a `SecretStr`
    compared to a `str` is *always* unequal, so a guard written that
    way stops guarding without saying anything.
    """

    KEY = "sk-ant-api03-MUSTNOTAPPEARmustnotappear"

    def test_the_environment_variable_still_sets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The compatibility requirement in one line: an operator who
        # exported this before the retype exports it after.
        monkeypatch.setenv("ANTHROPIC_API_KEY", self.KEY)
        assert Settings().anthropic_api_key.get_secret_value() == self.KEY

    def test_the_field_is_settable_by_its_own_name(self) -> None:
        # ~Thirty test modules construct `Settings(anthropic_api_key=...)`
        # with a plain string. pydantic coerces; none of them had to change.
        built = Settings(anthropic_api_key="sk-inline")
        assert built.anthropic_api_key.get_secret_value() == "sk-inline"

    def test_the_default_is_empty_because_empty_means_not_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Not a required field: importing `src.config` must not need a key.

        The CLI, every test module and every mock-mode run construct
        `Settings` without one, and `src/llm.py` is the single place
        that decides an empty key is a refusal.

        The `delenv` is not ceremony: `tests/conftest.py` pins the
        zero-spend sentinel into the environment for the whole session,
        so a bare `Settings()` here reads *that*, not the field default.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert Settings().anthropic_api_key.get_secret_value() == ""

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_a_blank_value_is_unset_rather_than_a_key(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        # `SecretStr` accepts any string, so without the before-validator
        # a whitespace key would be *configured* and truthy: `src/llm.py`
        # would build a live client with it and the operator's answer
        # would be a 401 rather than "not set in .env".
        monkeypatch.setenv("ANTHROPIC_API_KEY", blank)
        assert Settings().anthropic_api_key.get_secret_value() == ""

    def test_a_configured_key_is_not_stripped(self) -> None:
        # Only a blank is special. The bytes an operator exported are
        # the bytes that authenticate; trimming a credential is a
        # behaviour change dressed as hygiene.
        padded = " sk-pad ded\n"
        built = Settings(anthropic_api_key=padded)
        assert built.anthropic_api_key.get_secret_value() == padded

    def test_the_key_cannot_reach_a_repr(self) -> None:
        """The measured defect. Every one of these printed the key before.

        `Settings` is constructed in ~30 test modules and pydantic's
        `__repr__` prints every field, so the live credential was one
        `-vv` assertion diff, one `print(settings)` or one deliberate
        settings dump away from wherever that text goes next.
        """
        rendered = Settings(anthropic_api_key=self.KEY)
        assert self.KEY not in repr(rendered)
        assert self.KEY not in str(rendered)
        assert self.KEY not in f"{rendered}"
        assert self.KEY not in f"{rendered.anthropic_api_key}"
        assert self.KEY not in repr(rendered.anthropic_api_key)
        assert self.KEY not in str(rendered.anthropic_api_key)

    def test_the_key_cannot_reach_a_dump(self) -> None:
        # Both dump shapes plus the stringified dict a debug line would
        # actually emit. `model_dump()` keeps the wrapper, so even a
        # caller that never asked for `mode="json"` gets the mask.
        dumped = Settings(anthropic_api_key=self.KEY)
        assert self.KEY not in dumped.model_dump_json()
        assert self.KEY not in str(dumped.model_dump())
        assert self.KEY not in str(dumped.model_dump(mode="json"))
        assert dumped.model_dump()["anthropic_api_key"].get_secret_value() == self.KEY

    def test_masking_does_not_depend_on_the_key_looking_like_a_key(self) -> None:
        """The reason a type beats the `sk-` redaction rule in the log layer.

        `redact_text` scrubs `sk-…` shapes out of anything that reaches
        the JSON formatter. A gateway, proxy or self-hosted credential
        carries no such prefix and would pass that rule untouched. The
        wrapper does not care what the value looks like.
        """
        odd = "gw_live_MUSTNOTAPPEARmustnotappear"
        rendered = Settings(anthropic_api_key=odd)
        assert odd not in repr(rendered)
        assert odd not in rendered.model_dump_json()

    # -- the sentinel ---------------------------------------------------
    #
    # Every local and CI path in this repository runs with
    # `ANTHROPIC_API_KEY=local-preview-disabled`. The sentinel is taken
    # from `harness_environment` rather than retyped, so these cannot
    # drift from the value the harness actually pins.

    def test_the_zero_spend_sentinel_survives_the_wrapper(
        self, harness_environment: tuple[frozenset[str], dict[str, str]]
    ) -> None:
        _scrubbed, declared = harness_environment
        sentinel = declared["ANTHROPIC_API_KEY"]
        built = Settings(anthropic_api_key=sentinel)
        assert built.anthropic_api_key.get_secret_value() == sentinel

    def test_the_sentinel_stays_truthy_so_the_spend_guard_still_fires(
        self, harness_environment: tuple[frozenset[str], dict[str, str]]
    ) -> None:
        """`tests/conftest.py` chose a *non-empty* sentinel on purpose.

        An empty key sends `src.llm._get_client` down its "not
        configured" branch and the suite's spend guard — which fires at
        the client constructor — is never reached, hiding a would-be
        spend behind a different error. The wrapper must not quietly
        turn the sentinel falsy.
        """
        _scrubbed, declared = harness_environment
        built = Settings(anthropic_api_key=declared["ANTHROPIC_API_KEY"])
        assert bool(built.anthropic_api_key) is True
        assert bool(Settings(anthropic_api_key="").anthropic_api_key) is False

    def test_comparing_the_wrapper_to_a_string_is_always_false(
        self, harness_environment: tuple[frozenset[str], dict[str, str]]
    ) -> None:
        """The failure mode this class exists to make loud.

        A guard written `settings.anthropic_api_key == SENTINEL` is not
        a guard: it is `False` for the sentinel *and* for a real key,
        so it stops refusing to spend and reports nothing. Pinned here
        so the next person who writes that comparison sees why it can't
        work, and reaches for `get_secret_value()`.
        """
        _scrubbed, declared = harness_environment
        sentinel = declared["ANTHROPIC_API_KEY"]
        wrapped = Settings(anthropic_api_key=sentinel).anthropic_api_key
        assert wrapped != sentinel
        assert wrapped.get_secret_value() == sentinel


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


class TestTheInboundKeystoreIsASecret:
    """WO-D3. `api_keys` — the last plain-`str` secret on the way *in*.

    The two conversions before this one protected a single credential
    each. This field is a whole keystore in one string: every secret
    the deployment will accept, comma-separated, so the plain `str` it
    used to be put *all* of them into one repr rather than one.

    It also has a property the other three do not — it is read for its
    *structure*, not its value. `src/api/auth.py::parse_api_keys`
    splits it and builds the map every request is authenticated
    against, so the retype has to prove two things at once: the string
    is masked everywhere text goes, and the keystore built from it
    still authenticates the real secret. A conversion that got the
    first without the second would be a guard that stopped guarding.
    """

    KEYSTORE = "internal:sk-MUSTNOTAPPEARmustnotappear"
    SECRET = "sk-MUSTNOTAPPEARmustnotappear"

    def test_the_environment_variable_still_sets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The compatibility requirement in one line. `API_KEYS` is set
        # by docker-compose.yml, the production overlay, both e2e
        # overlays and `web/contract/record.sh`; none of them changed.
        monkeypatch.setenv("API_KEYS", self.KEYSTORE)
        assert Settings().api_keys.get_secret_value() == self.KEYSTORE

    def test_the_field_is_settable_by_its_own_name(self) -> None:
        # Nine test modules construct `Settings(api_keys="...")` with a
        # plain string. pydantic coerces; none of them had to change.
        built = Settings(api_keys=self.KEYSTORE)
        assert built.api_keys.get_secret_value() == self.KEYSTORE

    def test_the_default_is_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Auth is off by default and `parse_api_keys` turns an empty
        # string into an empty map, so importing `src.config` must not
        # need a keystore.
        monkeypatch.delenv("API_KEYS", raising=False)
        assert Settings().api_keys.get_secret_value() == ""

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_a_blank_keystore_is_unset_rather_than_a_keystore(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        """`deploy/pilot/compose.pilot.yml` sets `API_KEYS: ""` on purpose.

        That is how a Compose file spells "the file is the keystore,
        not the string" (ADR 0037). `parse_api_keys` has always
        ignored empty entries so the *parse* was never in doubt; the
        validator is what makes the wrapper agree, so a caller that
        asks the field rather than the parse gets the same answer.
        """
        monkeypatch.setenv("API_KEYS", blank)
        assert Settings().api_keys.get_secret_value() == ""
        assert bool(Settings().api_keys) is False

    def test_a_configured_keystore_is_not_stripped(self) -> None:
        # Only a blank is special, exactly as for the other three
        # secrets. `parse_api_keys` does its own per-entry stripping;
        # a second pass here would be a silent second edit of a
        # credential string.
        padded = "  internal:sk_a  "
        assert Settings(api_keys=padded).api_keys.get_secret_value() == padded

    def test_the_keystore_cannot_reach_a_repr(self) -> None:
        rendered = Settings(api_keys=self.KEYSTORE)
        assert self.SECRET not in repr(rendered)
        assert self.SECRET not in str(rendered)
        assert self.SECRET not in f"{rendered}"
        assert self.SECRET not in f"{rendered.api_keys}"
        assert self.SECRET not in repr(rendered.api_keys)
        assert self.SECRET not in str(rendered.api_keys)

    def test_the_keystore_cannot_reach_a_dump(self) -> None:
        dumped = Settings(api_keys=self.KEYSTORE)
        assert self.SECRET not in dumped.model_dump_json()
        assert self.SECRET not in str(dumped.model_dump())
        assert self.SECRET not in str(dumped.model_dump(mode="json"))
        assert dumped.model_dump()["api_keys"].get_secret_value() == self.KEYSTORE

    def test_the_parsed_keystore_still_authenticates_the_real_secret(
        self,
    ) -> None:
        """The half a masking test cannot see, and the reason this is D3.

        `parse_api_keys` is the inbound authentication path. Masking
        the field and unwrapping it in the wrong place produces a
        keystore keyed on `**********` — one that masks perfectly and
        authenticates nobody, or worse, authenticates anyone who sends
        the mask. Assert against the comparator the request path
        actually uses rather than against the dict.
        """
        from src.api.auth import _lookup_principal, parse_api_keys

        keystore = parse_api_keys(Settings(api_keys=self.KEYSTORE).api_keys)
        principal = _lookup_principal(self.SECRET, keystore)
        assert principal is not None
        assert principal.key_id == "internal"
        assert _lookup_principal("**********", keystore) is None

    def test_comparing_the_wrapper_to_a_string_is_always_false(self) -> None:
        # Pinned for the same reason `TestTheApiKeyIsASecret` pins it:
        # so the next person who writes `settings.api_keys == "..."`
        # sees why it cannot work and reaches for `get_secret_value()`.
        wrapped = Settings(api_keys=self.KEYSTORE).api_keys
        assert wrapped != self.KEYSTORE
        assert wrapped.get_secret_value() == self.KEYSTORE


class TestTheSemanticScholarKeyIsASecret:
    """WO-D3. The outbound half — a credential this repo *sends*.

    Optional, and free to omit, which is why it sat as a plain `str`
    for three sprints: an unset key costs nothing but the anonymous
    rate limit, so nobody had to think about the set case. A set one
    is a real credential on a real request, and it was printed in full
    by every `Settings` repr like the other three.

    The truthiness check in `_headers` is the interesting part. `if
    settings.semantic_scholar_api_key:` kept working across the
    retype — but only through pydantic's `__len__`, the implementation
    detail `src/llm.py` already declined to rest a spend guard on.
    """

    KEY = "s2-MUSTNOTAPPEARmustnotappear"

    def test_the_environment_variable_still_sets_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", self.KEY)
        assert Settings().semantic_scholar_api_key.get_secret_value() == self.KEY

    def test_the_field_is_settable_by_its_own_name(self) -> None:
        built = Settings(semantic_scholar_api_key=self.KEY)
        assert built.semantic_scholar_api_key.get_secret_value() == self.KEY

    def test_the_default_is_empty_because_the_key_is_optional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)
        assert Settings().semantic_scholar_api_key.get_secret_value() == ""

    @pytest.mark.parametrize("blank", ["", "   ", "\n"])
    def test_a_blank_key_is_unset_rather_than_a_key(
        self, monkeypatch: pytest.MonkeyPatch, blank: str
    ) -> None:
        """A blank here fails *closed*, and quietly, without the validator.

        `_headers` sends `x-api-key` whenever the key is non-empty, so
        a whitespace value would put `x-api-key: " "` on every S2
        request. S2 answers a bad key with 403, `_get_json` swallows a
        non-2xx as a warning, and the operator's symptom is enrichment
        that silently returns nothing — rather than the anonymous
        fallback the unset case is designed to take.
        """
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", blank)
        assert Settings().semantic_scholar_api_key.get_secret_value() == ""

    def test_a_configured_key_is_not_stripped(self) -> None:
        padded = " s2-pad ded\n"
        built = Settings(semantic_scholar_api_key=padded)
        assert built.semantic_scholar_api_key.get_secret_value() == padded

    def test_the_key_cannot_reach_a_repr(self) -> None:
        rendered = Settings(semantic_scholar_api_key=self.KEY)
        assert self.KEY not in repr(rendered)
        assert self.KEY not in str(rendered)
        assert self.KEY not in f"{rendered}"
        assert self.KEY not in f"{rendered.semantic_scholar_api_key}"
        assert self.KEY not in repr(rendered.semantic_scholar_api_key)
        assert self.KEY not in str(rendered.semantic_scholar_api_key)

    def test_the_key_cannot_reach_a_dump(self) -> None:
        dumped = Settings(semantic_scholar_api_key=self.KEY)
        assert self.KEY not in dumped.model_dump_json()
        assert self.KEY not in str(dumped.model_dump())
        assert self.KEY not in str(dumped.model_dump(mode="json"))
        assert (
            dumped.model_dump()["semantic_scholar_api_key"].get_secret_value()
            == self.KEY
        )

    def test_masking_does_not_depend_on_the_key_looking_like_a_key(self) -> None:
        # S2 keys carry no recognisable prefix at all, so the log
        # layer's `sk-…` shape rule was never going to catch this one.
        # The wrapper does not care what the value looks like.
        odd = "MUSTNOTAPPEARmustnotappear0123456789"
        rendered = Settings(semantic_scholar_api_key=odd)
        assert odd not in repr(rendered)
        assert odd not in rendered.model_dump_json()

    def test_the_wrapper_must_not_reach_the_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mask on the wire is the failure this retype could cause.

        `{"x-api-key": settings.semantic_scholar_api_key}` type-checks
        as `dict[str, str]` nowhere, but `f"{...}"` and `str(...)`
        both do — and both send `**********` to Semantic Scholar,
        which 403s, which `_get_json` swallows into a warning. Pin the
        raw value at the header instead.
        """
        from src.tools import semantic_scholar as s2_module

        monkeypatch.setattr(
            s2_module, "settings", Settings(semantic_scholar_api_key=self.KEY)
        )
        assert s2_module._headers() == {"x-api-key": self.KEY}

    def test_no_key_still_means_no_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The anonymous fallback, asserted through the unwrapped
        # emptiness test rather than through `bool(SecretStr(""))`.
        from src.tools import semantic_scholar as s2_module

        monkeypatch.setattr(
            s2_module, "settings", Settings(semantic_scholar_api_key="")
        )
        assert s2_module._headers() == {}


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


class TestTheRequestProfileIsRefusedWhenTheModelWouldRefuseIt:
    """CAP-01 / ADR 0076 — a config that cannot make one call must not boot.

    `llm_thinking` and an effort level are checked at settings load
    because there is no good runtime answer to either: a model with no
    adaptive mode, or one that does not list the level, answers with an
    HTTP 400 — every call, on every node, for the whole deployment. The
    two settings that *degrade* (`enable_structured_outputs`,
    `llm_temperature`) are deliberately not checked, and the last two
    tests below are what stop that asymmetry from being read as an
    oversight.
    """

    def test_the_defaults_boot(self) -> None:
        config = Settings()
        assert config.llm_thinking == "off"
        assert config.llm_effort == ""
        assert config.llm_temperature == 0.3
        assert config.enable_structured_outputs is False

    def test_thinking_is_refused_on_a_model_without_an_adaptive_mode(self) -> None:
        with pytest.raises(ValidationError, match="llm_thinking"):
            Settings(llm_thinking="adaptive", anthropic_model="claude-haiku-4-5")

    def test_thinking_is_refused_when_one_agent_routes_to_such_a_model(self) -> None:
        """The routing case, which is the one that actually happens.

        ADR 0021 recommends `READER_MODEL=claude-haiku-4-5` by name. A
        check that only looked at `anthropic_model` would pass this
        configuration and then fail every reader call in production.
        """
        with pytest.raises(ValidationError, match="claude-haiku-4-5"):
            Settings(llm_thinking="adaptive", reader_model="claude-haiku-4-5")

    def test_thinking_is_accepted_where_every_routed_model_supports_it(self) -> None:
        config = Settings(
            llm_thinking="adaptive",
            anthropic_model="claude-opus-5",
            eval_judge_model="claude-sonnet-5",
        )
        assert config.llm_thinking == "adaptive"

    def test_an_effort_level_the_default_model_lacks_is_refused(self) -> None:
        """`xhigh` arrived with Opus 4.7; the shipped default is Sonnet 4.6.

        The case a boolean `effort` capability could not have caught,
        and the reason `ModelCapabilities` carries a level set.
        """
        with pytest.raises(ValidationError, match="xhigh"):
            Settings(llm_effort="xhigh")

    def test_the_same_level_is_accepted_on_a_model_that_lists_it(self) -> None:
        config = Settings(
            llm_effort="xhigh",
            anthropic_model="claude-opus-5",
            eval_judge_model="claude-opus-5",
        )
        assert config.effort_for() == "xhigh"

    def test_a_global_level_is_refused_on_a_model_that_rejects_effort(self) -> None:
        with pytest.raises(ValidationError, match="rejects output_config.effort"):
            Settings(llm_effort="high", reader_model="claude-haiku-4-5")

    def test_off_is_how_one_agent_opts_out_of_a_global_level(self) -> None:
        """Without it, `LLM_EFFORT` plus ADR 0021's reader recommendation
        is a configuration with no expression and no fix — an empty
        override *inherits*, so there would be no way to say "everything
        at high, except the reader"."""
        config = Settings(
            llm_effort="high", reader_model="claude-haiku-4-5", reader_effort="off"
        )
        assert config.effort_for("reader") == ""
        assert config.effort_for("planner") == "high"

    def test_a_per_agent_level_is_judged_against_that_agent_s_model(self) -> None:
        with pytest.raises(ValidationError, match="planner_effort"):
            Settings(planner_effort="xhigh", planner_model="claude-sonnet-4-6")
        assert (
            Settings(planner_effort="xhigh", planner_model="claude-opus-5").effort_for(
                "planner"
            )
            == "xhigh"
        )

    def test_the_judge_model_is_checked_like_any_other_routed_id(self) -> None:
        """`eval_judge_model` receives a global effort like every other call.

        It is a routed id in its own right (ADR 0070), not an
        `<agent>_model` override, and a deployment that upgraded the
        base model but not the judge would otherwise 400 only inside the
        eval harness.
        """
        with pytest.raises(ValidationError, match="claude-sonnet-4-6"):
            Settings(
                llm_effort="xhigh",
                anthropic_model="claude-opus-5",
                # left at its default, which does not list `xhigh`
            )

    def test_structured_outputs_are_not_refused_on_an_unsupporting_model(self) -> None:
        """It degrades to the pre-ADR-0076 parse path, so it boots.

        Refusing to start over a feature that has a working fallback
        would make the strict check above indistinguishable from a
        strictness preference.
        """
        config = Settings(
            enable_structured_outputs=True, anthropic_model="some-proxy-model"
        )
        assert config.enable_structured_outputs is True

    def test_a_temperature_a_model_would_reject_is_not_refused_either(self) -> None:
        """Opus 5 rejects sampling parameters; the gateway just omits them."""
        config = Settings(llm_temperature=0.9, anthropic_model="claude-opus-5")
        assert config.llm_temperature == 0.9

    def test_the_temperature_stays_inside_zero_and_one(self) -> None:
        with pytest.raises(ValidationError):
            Settings(llm_temperature=1.5)
        with pytest.raises(ValidationError):
            Settings(llm_temperature=-0.1)


@pytest.mark.unit
def test_the_routed_id_derivation_matches_the_billing_one() -> None:
    """`src/config.py` re-derives `resolved_model_ids` rather than importing.

    It has to: `src.observability` imports `src.config`, so importing it
    back to validate a field would close a cycle while this module's
    body is still executing. A second copy of four lines is fine; a
    second copy that *disagrees* would validate effort against a
    different model set than the one being billed, so the two are held
    equal here.
    """
    from src.config import _routed_model_ids
    from src.observability.costs import resolved_model_ids

    for config in (
        Settings(),
        Settings(anthropic_model="claude-opus-5", reader_model="claude-haiku-4-5"),
        Settings(eval_judge_model="claude-sonnet-5", critic_model="claude-opus-4-6"),
    ):
        assert _routed_model_ids(config) == resolved_model_ids(config)


@pytest.mark.unit
class TestTheAgentResolvers:
    """`model_for` and `effort_for` — the two `override or base` rules.

    Small enough to look obviously right and load-bearing enough to be
    wrong quietly: `_check_request_profile_is_supported` decides which
    model an agent's effort has to be legal for by asking these, so a
    resolver that fell back the wrong way would validate the right
    field against the wrong model.
    """

    def test_model_for_falls_back_to_the_base_model(self) -> None:
        config = Settings(anthropic_model="claude-opus-5", planner_model="")
        assert config.model_for("planner") == "claude-opus-5"
        assert config.model_for() == "claude-opus-5"

    def test_model_for_honours_an_override(self) -> None:
        config = Settings(
            anthropic_model="claude-opus-5", planner_model="claude-haiku-4-5"
        )
        assert config.model_for("planner") == "claude-haiku-4-5"

    def test_effort_for_distinguishes_inherit_from_opt_out(self) -> None:
        """`""` inherits and `"off"` does not — the whole reason both exist."""
        config = Settings(
            llm_effort="medium", planner_effort="", critic_effort="off"
        )
        assert config.effort_for("planner") == "medium"
        assert config.effort_for("critic") == ""
        assert config.effort_for() == "medium"
