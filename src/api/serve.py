"""Serving entry point — `python -m src.api.serve`.

Boots uvicorn against the app factory. Both local development and
the compose stack run this module (ADR 0042): it is the one place
that sets `log_config=None` (the uvicorn CLI cannot express that —
`--log-config` demands a parseable file) and the bounded graceful
shutdown below, so the two environments cannot drift. Host and port
come from `settings`, so a container sets API_HOST/API_PORT env
vars rather than flags.

WO-A10 turns uvicorn's own access log off here. With `log_config=None`
its `uvicorn.access` records propagate to our root handler and are
emitted as JSON whose `message` is the prose
`'127.0.0.1:52344 - "GET /research/9f2c HTTP/1.1" 200'` — one string
carrying five facts, none of them a field, and with the raw path
inside it. `ObservabilityMiddleware` emits `api_request_completed`
instead, with `method`, `route` (the *template*), `http_status` and
`elapsed_ms` as fields, joined to the trace and the request id. Two
access logs for one request would be strictly worse than either, so
this is a replacement rather than an addition.
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
        # WO-A10: `ObservabilityMiddleware` owns the access line now.
        # This clears `uvicorn.access`'s handlers and stops it
        # propagating, so the prose line cannot reach the JSON stream.
        access_log=False,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SEC,
    )


if __name__ == "__main__":
    main()
