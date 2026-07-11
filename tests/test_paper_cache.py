"""Tests for the pluggable `PaperCache`: disk + Postgres implementations.

Postgres tests use `pytest-postgresql` which spins up a real Postgres
process per session using the system's `pg_config`. Marked
`integration` since they exercise a real driver + real Postgres,
even though the process is local and fast (~2s startup).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from src.config import Settings
from src.tools import paper_cache as paper_cache_module
from src.tools import postgres_pool
from src.tools.paper_cache import (
    DEFAULT_CACHE_DIR,
    DiskPaperCache,
    PaperCache,
    PostgresPaperCache,
    get_paper_cache,
)

# pytest-postgresql spawns a real Postgres process; skip it entirely
# when the local machine doesn't have the `postgres` server binary
# (e.g. libpq-only Homebrew installs). CI runs on ubuntu-latest with
# the full postgres server available.
_postgres_available = shutil.which("postgres") is not None
pytestmark_postgres = pytest.mark.skipif(
    not _postgres_available,
    reason="postgres server binary not found; install `postgresql` locally to run",
)

if _postgres_available:
    from pytest_postgresql import factories

    postgresql_proc = factories.postgresql_proc(
        port=None,  # random free port
        unixsocketdir="/tmp",
    )
    postgresql_db = factories.postgresql("postgresql_proc")


def _override_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    """Rebuild `Settings` and swap the module-scoped singletons.

    `Settings` is `frozen=True` so per-attribute monkeypatching is
    impossible. Constructing a fresh instance with the overrides is
    the documented pattern (see the module docstring in
    `src.config`).
    """
    fresh = Settings(**overrides)  # type: ignore[arg-type]
    monkeypatch.setattr(paper_cache_module, "settings", fresh)
    monkeypatch.setattr(postgres_pool, "settings", fresh)


class TestDiskPaperCache:
    def test_get_returns_none_for_missing_key(self, tmp_path: Path) -> None:
        cache = DiskPaperCache(tmp_path)
        assert cache.get_text("missing") is None

    def test_put_then_get_roundtrip(self, tmp_path: Path) -> None:
        cache = DiskPaperCache(tmp_path)
        cache.put_text("k1", "http://x/pdf", "hello world")
        assert cache.get_text("k1") == "hello world"

    def test_put_creates_cache_dir(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "cache"
        cache = DiskPaperCache(target)
        cache.put_text("k1", "http://x/pdf", "body")
        assert (target / "k1.txt").exists()

    def test_repeat_put_overwrites(self, tmp_path: Path) -> None:
        cache = DiskPaperCache(tmp_path)
        cache.put_text("k1", "http://x/pdf", "v1")
        cache.put_text("k1", "http://x/pdf", "v2")
        assert cache.get_text("k1") == "v2"

    def test_pdf_url_argument_is_ignored_by_disk(
        self, tmp_path: Path
    ) -> None:
        # The Protocol carries `pdf_url` for the Postgres variant's
        # audit column. The disk cache stores by key only, so a
        # different URL for the same key still lands in the same file.
        cache = DiskPaperCache(tmp_path)
        cache.put_text("k1", "http://a/pdf", "body")
        cache.put_text("k1", "http://b/different", "updated")
        assert cache.get_text("k1") == "updated"


if _postgres_available:

    @pytest.fixture
    def pg_url(
        postgresql_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[str]:
        """Yield a `postgresql://` URL for the per-test database, and
        reset the shared connection pool before + after so no state
        leaks between tests. Also overrides `settings.postgres_url` in
        the pool module so `init_schema()` picks up the test URL.
        """
        info = postgresql_db.info
        url = (
            f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"
        )
        _override_settings(monkeypatch, postgres_url=url)
        postgres_pool._reset_for_test(None)
        yield url
        postgres_pool.close_pool()


@pytestmark_postgres
@pytest.mark.integration
class TestPostgresPaperCache:
    def test_schema_init_creates_paper_cache_table(self, pg_url: str) -> None:
        postgres_pool.init_schema()

        with psycopg.connect(pg_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.paper_cache')::text")
            row = cur.fetchone()
        assert row is not None and row[0] == "paper_cache"

    def test_init_schema_is_idempotent(self, pg_url: str) -> None:
        # Calling twice must not raise even though the schema
        # already exists.
        postgres_pool.init_schema()
        postgres_pool.init_schema()

    def test_get_missing_returns_none(self, pg_url: str) -> None:
        cache = PostgresPaperCache()
        assert cache.get_text("nope") is None

    def test_put_then_get_roundtrip(self, pg_url: str) -> None:
        cache = PostgresPaperCache()
        cache.put_text("k1", "http://x/pdf", "hello world")
        assert cache.get_text("k1") == "hello world"

    def test_repeat_put_updates_via_upsert(self, pg_url: str) -> None:
        cache = PostgresPaperCache()
        cache.put_text("k1", "http://x/pdf", "v1")
        cache.put_text("k1", "http://x/pdf", "v2")
        assert cache.get_text("k1") == "v2"

    def test_stores_pdf_url_and_length(self, pg_url: str) -> None:
        # Audit fields the disk cache doesn't have. Non-critical to
        # the read path, but worth verifying so a future analytics
        # query against the cache table sees consistent data.
        cache = PostgresPaperCache()
        cache.put_text("k1", "http://arxiv.org/pdf/2311.09000", "some body")
        with psycopg.connect(pg_url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pdf_url, text_length FROM paper_cache WHERE paper_key = %s",
                ("k1",),
            )
            row = cur.fetchone()
        assert row is not None
        assert row[0] == "http://arxiv.org/pdf/2311.09000"
        assert row[1] == len("some body")


class TestFactory:
    def test_defaults_to_disk_impl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, paper_cache="disk")
        paper_cache_module._reset_for_test(None)
        cache = get_paper_cache()
        assert isinstance(cache, DiskPaperCache)

    def test_postgres_setting_returns_postgres_impl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, paper_cache="postgres")
        paper_cache_module._reset_for_test(None)
        cache = get_paper_cache()
        assert isinstance(cache, PostgresPaperCache)

    def test_returns_same_instance_on_repeat_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, paper_cache="disk")
        paper_cache_module._reset_for_test(None)
        first = get_paper_cache()
        second = get_paper_cache()
        assert first is second

    def test_default_cache_dir_matches_sprint_1_path(self) -> None:
        # Regression: a running deployment can be flipped between
        # disk and Postgres without wiping its local cache. That
        # relies on the disk path staying at `.cache/pdfs/`.
        assert str(DEFAULT_CACHE_DIR) == ".cache/pdfs"


class TestProtocolContract:
    """Cross-impl parity tests — assert both stores satisfy the same
    behavioral contract for the calls parse_pdf makes."""

    def _run_parity(self, cache: PaperCache) -> None:
        assert cache.get_text("k1") is None
        cache.put_text("k1", "http://x/pdf", "body")
        assert cache.get_text("k1") == "body"
        cache.put_text("k1", "http://x/pdf", "body2")
        assert cache.get_text("k1") == "body2"

    def test_disk_impl_satisfies_contract(self, tmp_path: Path) -> None:
        self._run_parity(DiskPaperCache(tmp_path))

    @pytestmark_postgres
    @pytest.mark.integration
    def test_postgres_impl_satisfies_contract(self, pg_url: str) -> None:
        self._run_parity(PostgresPaperCache())
