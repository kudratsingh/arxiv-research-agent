"""Cache read paths degrade to recompute instead of failing the job (ADR 0041).

ADR 0028 promised that a broken cache backend "degrades to recompute,
only shows up in the logs" — but only the WRITE paths were guarded.
These tests pin the READ-side guards: a `get_many` / `get_text` that
raises (PoolTimeout, OperationalError, a restarting Postgres) is
treated as a miss, logged at WARNING, and the caller recomputes.

Also pins the `_get_model` double-checked lock: concurrent cold-start
callers construct exactly one SentenceTransformer.

Mutation-checked: the degradation tests fail against the pre-fix code
(the backend exception propagated out of `encode_texts` / `parse_pdf`).
"""

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from src.tools import embeddings as embeddings_module
from src.tools import pdf_parser as pdf_parser_module
from src.tools.embeddings import encode_texts
from src.tools.pdf_parser import parse_pdf

pytestmark = [pytest.mark.unit, pytest.mark.fault]


class _ExplodingEmbeddingCache:
    """get_many raises like a timed-out pool; put_many raises too."""

    def get_many(self, hashes: list[str], model_name: str) -> dict[str, Any]:
        raise TimeoutError("couldn't get a connection after 30.00 sec")

    def put_many(self, entries: Any, model_name: str) -> None:
        raise TimeoutError("couldn't get a connection after 30.00 sec")


class _ExplodingPaperCache:
    """get_text raises like a timed-out pool; put_text raises too."""

    def get_text(self, paper_key: str) -> str | None:
        raise TimeoutError("couldn't get a connection after 30.00 sec")

    def put_text(self, paper_key: str, pdf_url: str, full_text: str) -> None:
        raise TimeoutError("couldn't get a connection after 30.00 sec")


class TestEncodeTextsCacheDegradation:
    def test_cache_read_failure_degrades_to_recompute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import src.tools.embedding_cache as cache_module

        monkeypatch.setattr(
            cache_module, "get_embedding_cache", lambda: _ExplodingEmbeddingCache()
        )
        fresh = np.ones((2, 4), dtype=np.float32)
        monkeypatch.setattr(
            embeddings_module, "_encode_uncached", lambda texts: fresh[: len(texts)]
        )

        out = encode_texts(["alpha", "beta"])

        # The whole batch recomputed — no exception escaped, and the
        # (also failing) write-back was suppressed as before.
        assert out.shape == (2, 4)
        assert np.array_equal(out, fresh)


class TestParsePdfCacheDegradation:
    def test_cache_read_failure_treated_as_miss(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def fake_download(url: str, dest: Path) -> bool:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b"%PDF-fake")
            return True

        monkeypatch.setattr(pdf_parser_module, "_download_pdf", fake_download)
        monkeypatch.setattr(
            pdf_parser_module, "_extract_text", lambda _p: "extracted text"
        )

        text = parse_pdf(
            "https://arxiv.org/pdf/2311.09000",
            cache_dir=tmp_path,
            cache=_ExplodingPaperCache(),
        )

        # Read failure -> miss -> download + extract still delivered
        # the text; the failing write was logged, not raised.
        assert text == "extracted text"


class TestModelSingletonLock:
    def test_concurrent_cold_start_constructs_model_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        constructed = {"n": 0}

        class _SlowFakeModel:
            # `device` is keyword-only in the real constructor call
            # site since ADR 0052 pinned the embedding device; a fake
            # that rejects it turns "the lock works" into "the
            # constructor raised in every thread", which asserts the
            # same way for the wrong reason.
            def __init__(self, _name: str, *, device: str | None = None) -> None:
                constructed["n"] += 1
                # Long enough that an unlocked check-then-set lets every
                # waiting thread through before the first assignment.
                time.sleep(0.05)

        monkeypatch.setattr(embeddings_module, "SentenceTransformer", _SlowFakeModel)
        monkeypatch.setattr(embeddings_module, "_model", None)

        start = threading.Barrier(4)

        def _load() -> None:
            start.wait()
            embeddings_module._get_model()

        threads = [threading.Thread(target=_load) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert constructed["n"] == 1
