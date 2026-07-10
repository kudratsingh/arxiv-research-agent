"""HTTP API surface over the research workflow.

Public entry point:

    from src.api import create_app
    app = create_app()

`create_app` returns a FastAPI application with the research routes
mounted and a lifespan that owns the async job runner + in-memory
job store. See ADR 0025 (API + job model) and ADR 0026 (SSE
streaming).
"""

from src.api.app import create_app
from src.api.jobs import Job, JobStatus, JobStore

__all__ = ["Job", "JobStatus", "JobStore", "create_app"]
