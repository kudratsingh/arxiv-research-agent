"""Embedding native-thread pinning, device pinning, cache-write logs.

Three findings meet in `src/tools/embeddings.py` (ADR 0052):

- **The reader's fan-out segfaulted the process.** Torch defaults to
  one OpenMP worker per core, three `libomp.dylib` copies ship in this
  venv, and five concurrent `model.encode` calls put enough traffic
  through the OpenMP barrier to take the interpreter down —
  reproduced 10/10 on a reader-shaped probe, faulting in
  `libomp.dylib::__kmp_suspend_64`, and 0/15 once
  `torch.set_num_threads(1)` runs at model load. That measurement is
  what `test_torch_threads_are_pinned_at_model_load` guards; the
  crash itself cannot be asserted in-process, because a native crash
  takes the assertion with it.
- **The device was whatever sentence-transformers picked**, which on
  Apple silicon is `mps` — a backend with its own, separate crash
  (Metal driver, `fill_mps_kernel`, ~1/6 here even with the threads
  pinned). `settings.embedding_device` now decides, defaults to
  `cpu`, and the choice is logged at model load so "which backend did
  that run use?" survives a crash that logs nothing.
- **The cache write was silent.** A bare
  `contextlib.suppress(Exception)` while the read path logged: a
  backend that reads fine and refuses every write has a 0% hit rate
  forever, and the only symptom was the Anthropic bill.

Mutation-checked. Dropping `torch.set_num_threads` fails
`test_torch_threads_are_pinned_at_model_load` and
`test_thread_count_is_logged_at_load`; reverting `_get_model` to
`SentenceTransformer(MODEL_NAME)` fails `test_default_settings_force_cpu`
and `test_explicit_device_is_passed_through`; restoring the
`contextlib.suppress` fails `test_cache_write_failure_is_logged`;
dropping the `device=None` mapping for `"auto"` fails
`test_auto_defers_to_the_library`.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pytest
import torch

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


@pytest.fixture
def restore_torch_threads() -> Any:
    """Put torch's thread count back however the test left it.

    `set_num_threads` is process-global, so a test that perturbs it
    would leak into every later test in the session.
    """
    before = torch.get_num_threads()
    yield
    torch.set_num_threads(before)


class TestNativeThreadPinning:
    """The half of ADR 0052 that actually stops the segfault.

    A native crash cannot be caught, so there is nothing to assert
    about the crash itself — the assertion is on the pin that the
    soak measured (10/10 crashes without it, 0/15 with it).
    """

    def test_torch_threads_are_pinned_at_model_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        restore_torch_threads: None,
    ) -> None:
        monkeypatch.setattr(embeddings_module, "settings", Settings())
        # Whatever a fresh interpreter would have defaulted to — one
        # OpenMP worker per core, which is the pool that races.
        torch.set_num_threads(4)

        embeddings_module._get_model()

        assert torch.get_num_threads() == embeddings_module.TORCH_THREADS

    def test_the_pin_holds_on_every_device_including_auto(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        restore_torch_threads: None,
    ) -> None:
        """The CPU OpenMP pool exists whatever the forward pass runs
        on, so the pin cannot be conditional on the device."""
        _with_device(monkeypatch, "auto")
        torch.set_num_threads(4)

        embeddings_module._get_model()

        assert torch.get_num_threads() == embeddings_module.TORCH_THREADS

    def test_pinning_to_more_than_one_thread_is_not_a_tuning_knob(
        self,
    ) -> None:
        """Any value above 1 leaves an OpenMP pool for the barrier
        race to happen in. This is a tripwire on the constant, not a
        behavioural test — it exists so a future "let's give it 4
        threads back" edit has to read ADR 0052 first."""
        assert embeddings_module.TORCH_THREADS == 1


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

    def test_thread_count_is_logged_at_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        caplog: pytest.LogCaptureFixture,
        restore_torch_threads: None,
    ) -> None:
        """Read back from torch, not echoed from the constant: a build
        that ignored the request is the case that still crashes, and
        the load line is the only place it can show up."""
        monkeypatch.setattr(embeddings_module, "settings", Settings())
        torch.set_num_threads(4)

        with caplog.at_level(logging.INFO, logger="src.tools.embeddings"):
            embeddings_module._get_model()

        loaded = [
            r for r in caplog.records if r.message == "embedding_model_loaded"
        ]
        assert loaded[0].torch_threads == 1  # type: ignore[attr-defined]

    def test_a_torch_build_that_ignores_the_pin_is_visible_in_the_log(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_model: type[_FakeModel],
        caplog: pytest.LogCaptureFixture,
        restore_torch_threads: None,
    ) -> None:
        """The one case the log line exists for.

        If `set_num_threads` silently does nothing — a torch build
        without OpenMP, a runtime that has already committed its pool —
        the process is still in the crash window and nothing else says
        so. Echoing `TORCH_THREADS` into the record would report the
        request; reading it back reports the outcome.
        """
        monkeypatch.setattr(embeddings_module, "settings", Settings())
        torch.set_num_threads(4)
        monkeypatch.setattr(torch, "set_num_threads", lambda _n: None)

        with caplog.at_level(logging.INFO, logger="src.tools.embeddings"):
            embeddings_module._get_model()

        loaded = [
            r for r in caplog.records if r.message == "embedding_model_loaded"
        ]
        assert loaded[0].torch_threads == 4  # type: ignore[attr-defined]

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
