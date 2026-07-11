"""Tests for the pluggable `EmbeddingCache`: no-op + Postgres impls.

Postgres tests use `pytest-postgresql`; same integration profile as
`test_paper_cache.py`.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import numpy as np
import psycopg
import pytest

from src.config import Settings
from src.tools import embedding_cache as embedding_cache_module
from src.tools import postgres_pool
from src.tools.embedding_cache import (
    NoOpEmbeddingCache,
    PostgresEmbeddingCache,
    content_hash,
    get_embedding_cache,
)

MODEL = "sentence-transformers/all-MiniLM-L6-v2"

_postgres_available = shutil.which("postgres") is not None
pytestmark_postgres = pytest.mark.skipif(
    not _postgres_available,
    reason="postgres server binary not found; install `postgresql` locally to run",
)

if _postgres_available:
    from pytest_postgresql import factories

    postgresql_proc = factories.postgresql_proc(
        port=None,
        unixsocketdir="/tmp",
    )
    postgresql_db = factories.postgresql("postgresql_proc")


def _override_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    fresh = Settings(**overrides)  # type: ignore[arg-type]
    monkeypatch.setattr(embedding_cache_module, "settings", fresh)
    monkeypatch.setattr(postgres_pool, "settings", fresh)


class TestContentHash:
    def test_stable_for_same_input(self) -> None:
        assert content_hash("hello") == content_hash("hello")

    def test_differs_for_different_input(self) -> None:
        assert content_hash("a") != content_hash("b")

    def test_returns_hex_string_of_expected_length(self) -> None:
        # SHA256 hex digest is 64 chars.
        h = content_hash("some text")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestNoOpEmbeddingCache:
    def test_get_many_always_returns_empty(self) -> None:
        cache = NoOpEmbeddingCache()
        assert cache.get_many(["h1", "h2"], MODEL) == {}

    def test_put_many_is_a_noop(self) -> None:
        cache = NoOpEmbeddingCache()
        cache.put_many([("h1", np.array([1.0], dtype=np.float32))], MODEL)
        # Still empty after the put.
        assert cache.get_many(["h1"], MODEL) == {}


if _postgres_available:

    @pytest.fixture
    def pg_url(
        postgresql_db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> Iterator[str]:
        info = postgresql_db.info
        url = f"postgresql://{info.user}:@{info.host}:{info.port}/{info.dbname}"
        _override_settings(monkeypatch, postgres_url=url)
        postgres_pool._reset_for_test(None)
        yield url
        postgres_pool.close_pool()


@pytestmark_postgres
@pytest.mark.integration
class TestPostgresEmbeddingCache:
    def test_get_many_empty_input_returns_empty_dict(self, pg_url: str) -> None:
        cache = PostgresEmbeddingCache()
        # Note: no schema init needed for an empty query — it never
        # touches Postgres. Defensive path lives in the impl.
        assert cache.get_many([], MODEL) == {}

    def test_roundtrip_preserves_vector_bytes_exactly(self, pg_url: str) -> None:
        cache = PostgresEmbeddingCache()
        vec = np.array([0.1, -0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        cache.put_many([("h1", vec)], MODEL)
        got = cache.get_many(["h1"], MODEL)
        assert "h1" in got
        np.testing.assert_array_equal(got["h1"], vec)

    def test_get_returns_only_hits(self, pg_url: str) -> None:
        # The cache-miss set is what drives the MiniLM re-encode
        # path in `embeddings.encode_texts`; misses must not appear
        # in the return dict.
        cache = PostgresEmbeddingCache()
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        cache.put_many([("h_present", vec)], MODEL)

        got = cache.get_many(["h_present", "h_missing"], MODEL)
        assert set(got.keys()) == {"h_present"}

    def test_model_name_is_part_of_key(self, pg_url: str) -> None:
        # Regression: an embedding stored under one model name must
        # not surface under a different model name. This is how a
        # model swap invalidates the whole cache implicitly.
        cache = PostgresEmbeddingCache()
        cache.put_many(
            [("h1", np.array([0.5], dtype=np.float32))],
            "model-a",
        )
        assert cache.get_many(["h1"], "model-a") != {}
        assert cache.get_many(["h1"], "model-b") == {}

    def test_repeat_put_updates_via_upsert(self, pg_url: str) -> None:
        cache = PostgresEmbeddingCache()
        v1 = np.array([1.0, 2.0], dtype=np.float32)
        v2 = np.array([9.0, 8.0], dtype=np.float32)
        cache.put_many([("h1", v1)], MODEL)
        cache.put_many([("h1", v2)], MODEL)
        got = cache.get_many(["h1"], MODEL)
        np.testing.assert_array_equal(got["h1"], v2)

    def test_batch_put_and_batch_get(self, pg_url: str) -> None:
        cache = PostgresEmbeddingCache()
        entries = [
            (f"h{i}", np.array([float(i), float(-i)], dtype=np.float32))
            for i in range(20)
        ]
        cache.put_many(entries, MODEL)

        got = cache.get_many([f"h{i}" for i in range(20)], MODEL)
        assert len(got) == 20
        for key, vec in entries:
            np.testing.assert_array_equal(got[key], vec)


class TestFactory:
    def test_defaults_to_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, embedding_cache="none")
        embedding_cache_module._reset_for_test(None)
        assert isinstance(get_embedding_cache(), NoOpEmbeddingCache)

    def test_postgres_setting_returns_postgres_impl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, embedding_cache="postgres")
        embedding_cache_module._reset_for_test(None)
        assert isinstance(get_embedding_cache(), PostgresEmbeddingCache)

    def test_singleton_is_reused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _override_settings(monkeypatch, embedding_cache="none")
        embedding_cache_module._reset_for_test(None)
        first = get_embedding_cache()
        second = get_embedding_cache()
        assert first is second


class TestEncodeTextsIntegration:
    """`embeddings.encode_texts` is the cache's real caller. Verify
    the cache-integration path in-process without hitting MiniLM by
    injecting a pre-populated NoOp variant."""

    def test_full_hit_skips_encode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An in-memory cache instance whose `get_many` returns
        # everything the caller asked for.
        class DictCache:
            def __init__(self, mapping: dict[str, np.ndarray]) -> None:
                self._mapping = mapping

            def get_many(
                self, hashes: list[str], model_name: str
            ) -> dict[str, np.ndarray]:
                return {h: self._mapping[h] for h in hashes if h in self._mapping}

            def put_many(
                self,
                entries: list[tuple[str, np.ndarray]],
                model_name: str,
            ) -> None:
                for k, v in entries:
                    self._mapping[k] = v

        texts = ["hello", "world"]
        vectors = {
            content_hash(t): np.array([float(i), float(i + 1)], dtype=np.float32)
            for i, t in enumerate(texts)
        }
        embedding_cache_module._reset_for_test(DictCache(vectors))

        from src.tools import embeddings as embeddings_module

        # Sentinel — this must NOT be called on a full-hit run.
        called = {"n": 0}

        def spy_encode(texts_arg: list[str]) -> np.ndarray:
            called["n"] += 1
            return np.zeros((len(texts_arg), 2), dtype=np.float32)

        monkeypatch.setattr(
            embeddings_module, "_encode_uncached", spy_encode
        )
        result = embeddings_module.encode_texts(texts)

        assert called["n"] == 0
        # Order-preserving: index 0 -> hash(texts[0]) -> vectors[hash(texts[0])].
        for i, t in enumerate(texts):
            np.testing.assert_array_equal(result[i], vectors[content_hash(t)])
