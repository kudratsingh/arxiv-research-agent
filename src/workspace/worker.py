"""Continuous local metadata worker; inert until schedule approval is configured.

Postgres remains the task/lease authority. The heartbeat is operational health,
not a queue, receipt of reading, or proof that sources succeeded. No external
message, full-text acquisition or generation is performed by this process.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_HEARTBEAT = Path("outputs/workspace-next/worker-heartbeat.json")


class WorkerStopping(RuntimeError):
    """A cooperative stop detected before publication; safe metadata may remain."""


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    pid: int
    state: str
    updated_at: str
    cycles: int = 0
    last_task_id: str | None = None
    last_ready_at: str | None = None
    last_error_class: str | None = None
    schema_version: str = "1.0.0"


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("worker_clock_requires_timezone")
    return now.astimezone(UTC).isoformat()


def write_heartbeat(path: Path, heartbeat: WorkerHeartbeat) -> None:
    """Atomic private diagnostic; never serialize owner notes or provider keys."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".worker-heartbeat-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.chmod(temporary, 0o600)
            json.dump(asdict(heartbeat), stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def health(path: Path, *, now: datetime | None = None, max_age: int = 360) -> dict[str, Any]:
    """Age/state health only; an idle approved worker may have no due occurrence."""
    if max_age < 1:
        raise ValueError("invalid_health_age")
    try:
        if path.stat().st_size > 16000:
            raise ValueError("oversized heartbeat")
        parsed = json.loads(path.read_text())
        # Whitelist the diagnostic shape rather than reflecting arbitrary file
        # fields into an operations command or health endpoint.
        heartbeat = WorkerHeartbeat(**parsed)
        if (
            not isinstance(heartbeat.state, str)
            or type(heartbeat.pid) is not int
            or type(heartbeat.cycles) is not int
        ):
            raise ValueError("invalid heartbeat fields")
        updated = datetime.fromisoformat(heartbeat.updated_at)
        if updated.tzinfo is None:
            raise ValueError("naive heartbeat")
        age = ((now or _now()) - updated).total_seconds()
    except (OSError, ValueError, TypeError):
        return {"healthy": False, "reason": "heartbeat_unavailable_or_invalid"}
    healthy = -10 <= age <= max_age and heartbeat.state in {
        "starting",
        "disabled",
        "checking",
        "idle",
        "ready",
        "lease_lost",
    }
    return {
        "healthy": healthy,
        "reason": "current" if healthy else "stale_stopped_or_clock_skew",
        "heartbeat": asdict(heartbeat),
        "age_seconds": round(age, 3),
    }


def run_worker(
    cycle: Callable[[Callable[[], bool], str], dict[str, Any] | None],
    *,
    enabled: bool,
    approved: bool,
    stop: threading.Event | None = None,
    heartbeat_path: Path = DEFAULT_HEARTBEAT,
    interval: int = 30,
    max_cycles: int | None = None,
    worker_id: str | None = None,
    now: Callable[[], datetime] = _now,
    wait: Callable[[float], Any] | None = None,
) -> WorkerHeartbeat:
    """Poll safe durable work, with injectable clock/wait for lifecycle tests.

    Approval false never invokes ``cycle`` (therefore no DB/network/provider
    construction). Errors are diagnostic classes only. A new per-cycle lease
    identity prevents a delayed attempt sharing a previous worker token.
    """
    if not 1 <= interval <= 300 or (max_cycles is not None and max_cycles < 1):
        raise ValueError("invalid_worker_bounds")
    stopper = stop or threading.Event()
    sleeper = wait or stopper.wait
    status = WorkerHeartbeat(worker_id or uuid.uuid4().hex, os.getpid(), "starting", _stamp(now()))
    while not stopper.is_set():
        status = replace(
            status,
            cycles=status.cycles + 1,
            updated_at=_stamp(now()),
            state="disabled" if not enabled or not approved else "checking",
        )
        # If diagnostic storage is broken, refuse to begin invisible work.
        write_heartbeat(heartbeat_path, status)
        if enabled and approved:
            try:
                result = cycle(stopper.is_set, status.worker_id + ":" + uuid.uuid4().hex)
                state = str(result.get("state") or "unknown") if result else "idle"
                status = replace(
                    status,
                    state=state,
                    updated_at=_stamp(now()),
                    last_task_id=str(result["id"])
                    if result and result.get("id")
                    else status.last_task_id,
                    last_ready_at=_stamp(now()) if state == "ready" else status.last_ready_at,
                    last_error_class="task_attempt_failed" if state == "failed_attempt" else None,
                )
            except Exception as exc:
                status = replace(
                    status,
                    state="degraded",
                    updated_at=_stamp(now()),
                    last_error_class=type(exc).__name__,
                )
            write_heartbeat(heartbeat_path, status)
        if max_cycles is not None and status.cycles >= max_cycles:
            break
        sleeper(interval)
    status = replace(status, state="stopped", updated_at=_stamp(now()))
    write_heartbeat(heartbeat_path, status)
    return status


def durable_cycle(
    store: Any,
    build: Callable[[str], dict[str, Any]],
    stop_requested: Callable[[], bool],
    worker_token: str,
) -> dict[str, Any] | None:
    """Use the existing lease/pause fence; source refresh is outside row locks.

    A stop during refresh allows committed public metadata to remain, then
    raises before returning the edition to the scheduler for publication. Task
    retry/lease recovery remains the scheduler's existing durable contract.
    """
    from src.workspace.scheduler import run_once

    if stop_requested():
        return None

    def guarded(owner: str) -> dict[str, Any]:
        if stop_requested():
            raise WorkerStopping("worker stop requested")
        edition = build(owner)
        if stop_requested():
            raise WorkerStopping("worker stop requested before publication")
        return edition

    return run_once(store, guarded, worker=worker_token)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heartbeat", type=Path, default=DEFAULT_HEARTBEAT)
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--max-cycles", type=int)
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--health-max-age", type=int, default=360)
    args = parser.parse_args(argv)
    if args.healthcheck:
        result = health(args.heartbeat, max_age=args.health_max_age)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["healthy"] else 1
    # No credential is required by this metadata-only process. Pin the sentinel
    # before importing application settings; a real key is never inherited.
    os.environ["ANTHROPIC_API_KEY"] = "local-preview-disabled"
    from src.config import settings

    stop = threading.Event()
    previous: dict[int, Any] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, lambda *_: stop.set())
    store: Any = None
    previous_rate_database = os.environ.get("WORKSPACE_RATE_DATABASE_URL")
    if settings.enable_workspace and settings.workspace_schedule_approved:
        # The native worker and container use the same database governor as
        # the API even though their local filesystem lock directories differ.
        os.environ["WORKSPACE_RATE_DATABASE_URL"] = settings.postgres_url

    def cycle(stopping: Callable[[], bool], token: str) -> dict[str, Any] | None:
        nonlocal store
        if store is None:
            from src.tools.postgres_pool import get_pool
            from src.workspace.store import WorkspaceStore

            store = WorkspaceStore(get_pool())
        from src.workspace import routes

        routes._store = store
        return durable_cycle(
            store, lambda owner: routes.refresh(owner, [], persist_edition=False), stopping, token
        )

    try:
        run_worker(
            cycle,
            enabled=settings.enable_workspace,
            approved=settings.workspace_schedule_approved,
            stop=stop,
            heartbeat_path=args.heartbeat,
            interval=args.poll_seconds,
            max_cycles=args.max_cycles,
        )
        return 0
    finally:
        if previous_rate_database is None:
            os.environ.pop("WORKSPACE_RATE_DATABASE_URL", None)
        else:
            os.environ["WORKSPACE_RATE_DATABASE_URL"] = previous_rate_database
        for restored_signum, handler in previous.items():
            signal.signal(restored_signum, handler)
        if store is not None:
            from src.tools.postgres_pool import close_pool

            close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
