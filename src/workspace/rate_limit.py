"""Cross-process source spacing without holding a workspace transaction open.

The dedicated autocommit session holds an advisory lock through the caller's
bounded fetch. A committed DB-clock timestamp survives crashes/restarts; closing
the session releases the lock. Configured database failures never fall back to
an independent local governor. No source URL or credentials enter error text.
"""

from __future__ import annotations

import contextlib
import math
import time
from collections.abc import Iterator

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

_KEY_PREFIX = "workspace-source-rate:"
_ERROR = "shared_source_rate_unavailable"


class SharedRateError(ValueError):
    """Safe, stable refusal when shared source admission cannot be established."""


def _number(value: float) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@contextlib.contextmanager
def shared_rate_slot(
    postgres_url: str, group: str, interval: float, *, max_wait: float = 10.0
) -> Iterator[None]:
    """Serialize a source group and commit each start before yielding.

    Lock/spacing admission waits at most ``max_wait`` (capped at ten seconds),
    with separate libpq connection and server statement bounds of two seconds.
    Body exceptions are preserved, including cancellation/BaseException.
    """
    if (
        not isinstance(postgres_url, str)
        or not postgres_url.strip()
        or not isinstance(group, str)
        or not group.strip()
        or len(group) > 200
        or any(ord(character) < 32 for character in group)
        or not _number(interval)
        or interval < 0
        or not _number(max_wait)
        or not 0 < max_wait <= 10
    ):
        raise SharedRateError(_ERROR)
    connection = None
    locked = False
    key = _KEY_PREFIX + group
    try:
        try:
            deadline = time.monotonic() + max_wait
            parameters = conninfo_to_dict(postgres_url)
            options = (
                str(parameters.get("options") or "")
                + f" -c statement_timeout={max(1, int(min(2, max_wait) * 1000))}"
                + " -c idle_in_transaction_session_timeout=2000"
            ).strip()
            dsn = make_conninfo(
                postgres_url,
                options=options,
                connect_timeout=2,
                application_name="workspace-source-rate",
                tcp_user_timeout=2000,
            )
            connection = psycopg.connect(dsn, autocommit=True)
            while True:
                if time.monotonic() >= deadline:
                    raise SharedRateError(_ERROR)
                row = connection.execute(
                    "SELECT pg_try_advisory_lock(hashtextextended(%s,0))", (key,)
                ).fetchone()
                if row and row[0]:
                    locked = True
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            while True:
                row = connection.execute(
                    "SELECT clock_timestamp(), (SELECT last_started_at FROM workspace_source_rate WHERE group_id=%s)",
                    (group,),
                ).fetchone()
                if row is None:
                    raise SharedRateError(_ERROR)
                now, previous = row
                delay = max(0.0, interval - (now - previous).total_seconds()) if previous else 0.0
                remaining = deadline - time.monotonic()
                if remaining <= 0 or delay > remaining:
                    raise SharedRateError(_ERROR)
                if not delay:
                    break
                time.sleep(delay)
            connection.execute(
                "INSERT INTO workspace_source_rate(group_id,last_started_at) VALUES (%s,clock_timestamp()) ON CONFLICT(group_id) DO UPDATE SET last_started_at=EXCLUDED.last_started_at",
                (group,),
            )
        except Exception:
            raise SharedRateError(_ERROR) from None
        yield
    finally:
        if connection is not None:
            try:
                if locked:
                    with contextlib.suppress(psycopg.Error):
                        connection.execute(
                            "SELECT pg_advisory_unlock(hashtextextended(%s,0))", (key,)
                        )
            finally:
                connection.close()
