"""Lazy re-export contract of the `src.api` package (ADR 0045).

`src/api/__init__.py` resolves its public names via a PEP 562 module
`__getattr__` so that importing a light `src.api.*` submodule does not
drag the ML stack (torch / faiss / sentence-transformers / PyMuPDF /
reportlab) into the process. These tests pin both halves of that
contract: the heavy stack stays out until asked for, and the public
names still resolve to the same objects the submodules define.

The isolation tests run in a subprocess: `sys.modules` in the pytest
process already holds whatever previous tests imported, so an
in-process check would be vacuous.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

# Top-level distributions that betray an eager ML-stack import. `fitz`
# is PyMuPDF's import name.
_HEAVY_MODULES = ("torch", "faiss", "sentence_transformers", "fitz", "reportlab")


def _run_probe(code: str) -> str:
    """Run `code` in a fresh interpreter and return its stdout.

    Args:
        code: Python source for `python -c`.

    Returns:
        Captured stdout, stripped.

    Raises:
        AssertionError: If the interpreter exits non-zero.
    """
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_import_src_api_does_not_load_ml_stack() -> None:
    """`import src.api` alone must not pull torch/faiss/etc.

    This is the regression the lazy `__getattr__` exists to prevent:
    before ADR 0045 the package `__init__` eagerly imported
    `src.api.app`, which transitively loaded the full embedding +
    PDF + export stack (~3.5s) for every `src.api.*` import.
    """
    loaded = _run_probe(
        "import sys; import src.api; "
        f"print(sorted(m for m in {_HEAVY_MODULES!r} if m in sys.modules))"
    )
    assert loaded == "[]", f"eager heavy imports leaked into src.api: {loaded}"


def test_import_light_submodule_does_not_load_ml_stack() -> None:
    """Importing a light submodule must not trigger the package's app import.

    `src.api.schemas` is pure pydantic models; before the lazy rewrite
    it cost ~3.5s because importing it initialises the parent package.
    """
    loaded = _run_probe(
        "import sys; import src.api.schemas; "
        f"print(sorted(m for m in {_HEAVY_MODULES!r} if m in sys.modules))"
    )
    assert loaded == "[]", f"eager heavy imports leaked into src.api.schemas: {loaded}"


def test_lazy_names_resolve_to_submodule_objects() -> None:
    """The four public names resolve identically to direct submodule imports."""
    import src.api
    from src.api.app import create_app
    from src.api.jobs import Job, JobStatus, JobStore

    assert src.api.create_app is create_app
    assert src.api.Job is Job
    assert src.api.JobStatus is JobStatus
    assert src.api.JobStore is JobStore


def test_from_import_still_works_in_fresh_interpreter() -> None:
    """`from src.api import create_app` — the documented entry point — works."""
    out = _run_probe("from src.api import create_app; print(callable(create_app))")
    assert out == "True"


def test_unknown_attribute_raises_attribute_error() -> None:
    """PEP 562 fallback must raise AttributeError, not KeyError."""
    import src.api

    with pytest.raises(AttributeError, match="no attribute 'nope'"):
        _ = src.api.nope  # type: ignore[attr-defined]


def test_dir_advertises_public_names() -> None:
    """`dir(src.api)` lists the lazy exports for discoverability."""
    import src.api

    listing = dir(src.api)
    for name in ("Job", "JobStatus", "JobStore", "create_app"):
        assert name in listing
