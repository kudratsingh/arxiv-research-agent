"""HTTP API surface over the research workflow.

Public entry point:

    from src.api import create_app
    app = create_app()

`create_app` returns a FastAPI application with the research routes
mounted and a lifespan that owns the async job runner + in-memory
job store. See ADR 0025 (API + job model) and ADR 0026 (SSE
streaming).

The re-exports below are lazy (PEP 562 module ``__getattr__``): an
eager ``from src.api.app import create_app`` here would drag the
whole ML stack (torch, faiss, sentence-transformers, PyMuPDF,
reportlab — ~3.5s, ~550MB) into *every* ``src.api.*`` import,
including CLIs like ``admin_migrate`` that need none of it. Lazy
resolution keeps ``import src.api.<submodule>`` proportional to what
the submodule actually uses (ADR 0045).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Static-only imports so mypy/IDEs see the same public names the
    # runtime `__getattr__` serves, without paying the import cost.
    from src.api.app import create_app
    from src.api.jobs import Job, JobStatus, JobStore

__all__ = ["Job", "JobStatus", "JobStore", "create_app"]

# Public name -> defining submodule, resolved on first attribute access.
_LAZY_EXPORTS = {
    "create_app": "src.api.app",
    "Job": "src.api.jobs",
    "JobStatus": "src.api.jobs",
    "JobStore": "src.api.jobs",
}


def __getattr__(name: str) -> object:
    """Resolve public re-exports on first access (PEP 562).

    Args:
        name: Attribute being looked up on the package.

    Returns:
        The re-exported object from its defining submodule.

    Raises:
        AttributeError: If `name` is not a public re-export.
    """
    try:
        module_name = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from None
    import importlib

    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    """Advertise lazy exports to `dir()` alongside real module globals."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
