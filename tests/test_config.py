"""Unit tests for the typed config surface.

Verifies field types, validation ranges, env-var loading, defaults,
immutability, and the ADR-0046 Literal-typed enum fields. No
network, no side effects.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings

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
