"""Local development entry point — `python -m src.api.serve`.

Boots uvicorn against the app factory. For production, a Dockerfile
(Sprint 4 PR 3) will invoke uvicorn directly with worker counts and
lifespan tuned by the container orchestrator, not this script.
"""

from __future__ import annotations

import uvicorn

from src.config import settings


def main() -> None:
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # defer to our JSON structured logger
    )


if __name__ == "__main__":
    main()
