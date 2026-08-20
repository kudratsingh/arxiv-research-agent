"""Local development entry point — `python -m src.api.serve`.

Boots uvicorn against the app factory. For production, a Dockerfile
(Sprint 4 PR 3) will invoke uvicorn directly with worker counts and
lifespan tuned by the container orchestrator, not this script.
"""

from __future__ import annotations

import uvicorn

from src.config import settings

# ADR 0042: cap the graceful-shutdown wait. Without it uvicorn
# blocks SIGTERM indefinitely on any open SSE connection — clients
# hold `/research/{id}/stream` open for the whole job — so the
# lifespan `finally` (cancel in-flight jobs, close the checkpointer
# + Redis pool) never runs and the orchestrator's SIGKILL converts
# healthy jobs into `orphaned` failures on the next redrive. 10s is
# enough for one SSE heartbeat interval to flush; deployments must
# keep the orchestrator grace period (compose `stop_grace_period`,
# k8s `terminationGracePeriodSeconds`) ABOVE this so the lifespan
# cleanup that follows the drain also gets to run.
GRACEFUL_SHUTDOWN_TIMEOUT_SEC = 10


def main() -> None:
    uvicorn.run(
        "src.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # defer to our JSON structured logger
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SEC,
    )


if __name__ == "__main__":
    main()
