"""Log hygiene: URL redaction, UTC timestamps, library-logger opt-out.

Covers the ADR 0042 observability fixes: `redact_url` keeps
connection-string credentials out of the indexed log stream, the
`JsonFormatter` timestamp is UTC with millisecond precision (so
cross-host timelines are unambiguous and sub-second ordering is
visible), and the httpx/anthropic logger demotion no longer defeats
`LOG_LEVEL=DEBUG` + `ANTHROPIC_LOG=debug`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.observability import JsonFormatter, redact_url

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
