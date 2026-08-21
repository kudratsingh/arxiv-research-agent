"""Embedding device pinning + cache-write visibility (ADR 0052).

Two findings meet in `src/tools/embeddings.py`:

- The MiniLM encode ran on whatever device sentence-transformers
  picked. On an Apple-silicon host that is `mps`, and a torch forward
  pass on the Metal backend has taken the whole worker down with a
  SIGSEGV — a native crash, so no Python traceback, no `run_failed`
  log line, nothing but a missing process. `settings.embedding_device`
  now decides, defaults to `cpu`, and the choice is logged once at
  model load so the answer to "which backend did that run use?"
  survives the crash.
- The cache *write* was wrapped in a bare
  `contextlib.suppress(Exception)` while the read path logged. A
  backend that reads fine and refuses every write has a 0% hit rate
  forever, and the only symptom was the Anthropic bill.

Mutation-checked. Reverting `_get_model` to `SentenceTransformer(
MODEL_NAME)` fails `test_default_settings_force_cpu` and
`test_explicit_device_is_passed_through`; restoring the
`contextlib.suppress` fails `test_cache_write_failure_is_logged`;
dropping the `device=None` mapping for `"auto"` fails
`test_auto_defers_to_the_library`.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pytest

from src.config import Settings
from src.tools import embeddings as embeddings_module

pytestmark = pytest.mark.unit


class _FakeModel:
    """Records the constructor's `device` and encodes deterministically."""

    #: Constructor calls seen this test, as `(model_name, device)`.
    calls: list[tuple[str, str | None]] = []

    def __init__(self, name: str, *, device: str | None = None) -> None:
        type(self).calls.append((name, device))
        # Mirrors the real attribute the load log reads back: torch
        # reports what it actually bound to, which is not always what
        # was asked for.
        self.device = device or "cpu"

    def encode(self, texts: list[str], **_kw: Any) -> np.ndarray:
        return np.ones((len(texts), 4), dtype=np.float32)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> type[_FakeModel]:
    """Swap in the fake and clear the module-level singleton."""
    _FakeModel.calls = []
    monkeypatch.setattr(embeddings_module, "SentenceTransformer", _FakeModel)
    monkeypatch.setattr(embeddings_module, "_model", None)
    return _FakeModel


def _with_device(monkeypatch: pytest.MonkeyPatch, device: str) -> None:
    monkeypatch.setattr(
        embeddings_module, "settings", Settings(embedding_device=device)
    )


class TestDeviceSelection:
    def test_default_settings_force_cpu(
        self, monkeypatch: pytest.MonkeyPatch, fake_model: type[_FakeModel]
    ) -> None:
        """The shipped default must be an explicit `"cpu"`, not None.

        `None` is what the library reads as "choose for me", which is
        the pre-0052 behavior this exists to stop.
        """
        monkeypatch.setattr(embeddings_module, "settings", Settings())
        embeddings_module._get_model()
        assert fake_model.calls == [(embeddings_module.MODEL_NAME, "cpu")]

    @pytest.mark.parametrize("device", ["cpu", "mps", "cuda"])
    def test_explicit_device_is_passed_through(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        device: str,
    ) -> None:
        _with_device(monkeypatch, device)
        embeddings_module._get_model()
        assert fake_model.calls[0][1] == device

    def test_auto_defers_to_the_library(
        self, monkeypatch: pytest.MonkeyPatch, fake_model: type[_FakeModel]
    ) -> None:
        """`auto` is the escape hatch for a deployment that wants GPU
        encode: it must reach the constructor as `device=None`, which
        is the only value sentence-transformers treats as "pick"."""
        _with_device(monkeypatch, "auto")
        embeddings_module._get_model()
        assert fake_model.calls[0][1] is None

    def test_resolve_device_is_the_single_translation_point(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _with_device(monkeypatch, "auto")
        assert embeddings_module._resolve_device() is None
        _with_device(monkeypatch, "mps")
        assert embeddings_module._resolve_device() == "mps"


class TestLoadLogging:
    def test_device_is_logged_once_at_model_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The load line is the only artifact that outlives a SIGSEGV
        — the crash itself writes nothing to our logs."""
        _with_device(monkeypatch, "cpu")
        with caplog.at_level(logging.INFO, logger="src.tools.embeddings"):
            embeddings_module._get_model()
            # Second call is served from the singleton: no second line.
            embeddings_module._get_model()

        loaded = [
            r for r in caplog.records if r.message == "embedding_model_loaded"
        ]
        assert len(loaded) == 1
        assert loaded[0].configured_device == "cpu"  # type: ignore[attr-defined]
        assert loaded[0].resolved_device == "cpu"  # type: ignore[attr-defined]
        assert loaded[0].model == embeddings_module.MODEL_NAME  # type: ignore[attr-defined]

    def test_auto_load_line_reports_what_torch_actually_bound(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Under `auto` the configured value says nothing; the resolved
        value is the whole point of the record."""
        _with_device(monkeypatch, "auto")
        with caplog.at_level(logging.INFO, logger="src.tools.embeddings"):
            embeddings_module._get_model()

        loaded = [
            r for r in caplog.records if r.message == "embedding_model_loaded"
        ]
        assert loaded[0].configured_device == "auto"  # type: ignore[attr-defined]
        # The fake stands in for torch's own pick.
        assert loaded[0].resolved_device == "cpu"  # type: ignore[attr-defined]


class _WriteOnlyFailingCache:
    """Reads clean, refuses every write — the silent-degradation shape."""

    def __init__(self) -> None:
        self.put_calls = 0

    def get_many(self, hashes: list[str], model_name: str) -> dict[str, Any]:
        return {}

    def put_many(self, entries: Any, model_name: str) -> None:
        self.put_calls += 1
        raise TimeoutError("couldn't get a connection after 30.00 sec")


class TestCacheWriteVisibility:
    def test_cache_write_failure_is_logged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(embeddings_module, "settings", Settings())
        cache = _WriteOnlyFailingCache()
        monkeypatch.setattr(
            "src.tools.embedding_cache.get_embedding_cache", lambda: cache
        )

        with caplog.at_level(logging.WARNING, logger="src.tools.embeddings"):
            out = embeddings_module.encode_texts(["a", "b"])

        # The caller is unaffected: vectors still came back.
        assert out.shape == (2, 4)
        assert cache.put_calls == 1
        failures = [
            r
            for r in caplog.records
            if r.message == "embedding_cache_put_failed"
        ]
        assert len(failures) == 1
        assert failures[0].levelno == logging.WARNING
        assert failures[0].n_vectors == 2  # type: ignore[attr-defined]
        assert "connection" in failures[0].error  # type: ignore[attr-defined]
