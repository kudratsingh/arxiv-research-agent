"""Admin cleanup migration for legacy NULL-owner rows (ADR 0038).

WHAT: a standalone operator CLI — `python -m src.api.admin_migrate` —
that finds, reports on, re-owns, or deletes rows whose
`principal_key_id` is NULL, across both backing stores: Redis
(`job:*`) and Postgres (`conversations`).

WHY: ADR 0036 added `principal_key_id` ownership to `Job` and
`Conversation`. Every row written before that ADR carries NULL, and
`_check_ownership` in `src/api/routes.py` deliberately treats a NULL
owner as invisible to *every* principal once `enable_api_auth` is on
— a 404 for everyone. That is the correct default (assigning a wrong
owner leaks data), but it strands the data permanently. ADR 0036
explicitly rejected auto-assigning a placeholder owner during
rollout, precisely because the placeholder is arbitrary and the real
owner is usually only knowable by reading `Job.query`. Its listed
follow-up was an *operator-driven* cleanup tool. This is that tool.

Design constraints that fall out of "operator-driven, destructive-
capable":

- **Dry run by default.** Nothing mutates without `--yes`. A bare
  invocation prints what it would do and exits 0.
- **Bounded output.** `report` prints counts plus a small sample with
  the query/title truncated to `PREVIEW_MAX_CHARS`. Dumping full
  result bodies of other tenants' research into an operator's
  terminal (and their shell scrollback) is its own disclosure.
- **Owner validated against the live keystore.** Assigning to a key
  id that does not exist would bury the rows one level deeper —
  still invisible, but now invisible for a subtler reason. Resolution
  order mirrors `create_app`: `api_keys_file` when set, else the
  `api_keys` string.
- **TTL preserved on rewrite.** Terminal jobs carry a retention TTL
  set by `RedisJobStore.update` (ADR 0027). Reading such a key,
  stamping an owner on it, and writing it back with a plain `SET`
  would clear that TTL and resurrect rows that were scheduled to
  expire. Every rewrite re-applies the observed `PTTL`.
- **Idempotent.** A second run over the same store matches nothing
  and says so.

Output split, deliberately: human-facing report + summary go to
stdout via `print`, because this is a CLI whose output an operator
reads and pipes. Anything that belongs in an audit trail goes
through `src.observability.get_logger`, which writes structured JSON
to stderr — so `... > report.txt` keeps the two apart.

Exit codes: 0 success (a clean dry run included), 1 runtime failure,
2 usage / validation failure.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.api.auth import (
    ApiKeyPrincipal,
    load_keystore_from_file,
    parse_api_keys,
)
from src.api.jobs import Job
from src.api.redis_store import (
    JOB_KEY_PREFIX,
    _job_from_json,
    _job_to_json,
    build_redis_client,
)
from src.config import settings
from src.observability import get_logger

log = get_logger(__name__)

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2

#: Longest query/title fragment echoed to the terminal. Enough for an
#: operator to recognise a run, short enough that a report over a few
#: hundred orphans stays readable and does not spill full bodies.
PREVIEW_MAX_CHARS = 80

#: How many matched rows `report` names individually. The counts are
#: always exact; the sample is only there to help identify an owner.
SAMPLE_ROWS = 10

#: `SCAN` batch hint. Redis treats COUNT as advisory, but a larger
#: batch keeps a multi-thousand-key sweep to a sane number of round
#: trips without blocking the server the way `KEYS` would.
SCAN_COUNT = 500

STORE_JOBS = "jobs"
STORE_CONVERSATIONS = "conversations"

ACTION_REPORT = "report"
ACTION_ASSIGN = "assign"
ACTION_DELETE = "delete"

SECONDS_PER_DAY = 86400.0


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NullOwnerRow:
    """One orphaned row, reduced to what an operator needs to identify it.

    Attributes:
        row_id: `job_id` for the Redis store, `conversation_id` for
            Postgres.
        created_at: Epoch seconds. Used both for display and for the
            `--older-than-days` filter.
        preview: Truncated query (jobs) or title (conversations).
    """

    row_id: str
    created_at: float
    preview: str


@dataclass(frozen=True)
class ScanResult:
    """Outcome of scanning one store for NULL-owner rows.

    Attributes:
        store: `jobs` or `conversations`.
        backend: Backing technology (`redis` / `postgres`), or the
            reason string's subject when unavailable.
        matched: Rows meeting the NULL-owner filter (plus any
            `--older-than-days` predicate), capped by `--limit`.
        scanned: Rows or keys actually inspected. Larger than
            `matched` whenever owned rows share the keyspace.
        rows: Named rows. For Redis this is the full matched set (the
            actions mutate key-by-key and need the ids). For Postgres
            it is a bounded sample — the actions there run as single
            SQL statements and never need the ids.
        truncated: `--limit` cut the run short; more rows remain.
        available: False when the store is not configured for this
            deployment.
        reason: Why the store is unavailable. Empty when available.
    """

    store: str
    backend: str
    matched: int = 0
    scanned: int = 0
    rows: list[NullOwnerRow] = field(default_factory=list)
    truncated: bool = False
    available: bool = True
    reason: str = ""

    def sample(self, n: int = SAMPLE_ROWS) -> list[NullOwnerRow]:
        """Return at most `n` named rows for terminal display."""
        return self.rows[:n]


@dataclass(frozen=True)
class ActionResult:
    """Outcome of an `assign` or `delete` pass over one store.

    Attributes:
        store: `jobs` or `conversations`.
        action: `assign` or `delete`.
        matched: Rows the action was scoped to.
        changed: Rows actually written. Always 0 on a dry run.
        dry_run: True when `--yes` was absent.
        truncated: `--limit` cut the run short.
        cascaded: Child rows removed by referential cascade. Only
            non-zero for the Postgres delete path.
    """

    store: str
    action: str
    matched: int = 0
    changed: int = 0
    dry_run: bool = True
    truncated: bool = False
    cascaded: int = 0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def truncate_preview(text: str, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    """Collapse whitespace and clip a query/title for terminal display.

    Args:
        text: Raw query or title. May be empty.
        max_chars: Ceiling on the returned length, ellipsis included.

    Returns:
        A single-line string of at most `max_chars` characters, with a
        trailing `…` when it was clipped.
    """
    normalized = " ".join(text.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def cutoff_epoch(older_than_days: int | None, *, now: float | None = None) -> float | None:
    """Convert `--older-than-days` into an epoch-seconds cutoff.

    Args:
        older_than_days: Age threshold in days, or None for no filter.
        now: Injectable clock for tests. Defaults to `time.time()`.

    Returns:
        The epoch second before which a row counts as "old enough",
        or None when no age filter was requested.
    """
    if older_than_days is None:
        return None
    base = now if now is not None else time.time()
    return base - (older_than_days * SECONDS_PER_DAY)


def _format_ts(epoch: float) -> str:
    """Render epoch seconds as a UTC ISO-8601 stamp for the report."""
    return datetime.fromtimestamp(epoch, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_keystore() -> dict[str, ApiKeyPrincipal]:
    """Load the live keystore the running API would use.

    Mirrors the resolution order in `create_app`: when
    `settings.api_keys_file` is set that file is the source of truth
    (ADR 0037), otherwise the `settings.api_keys` string is. Kept as a
    read-only mirror rather than a shared helper because this CLI must
    not import the FastAPI app factory to look up a key id.

    Returns:
        `{secret: ApiKeyPrincipal}`, the same shape the API holds in
        `app.state.api_keys`.

    Raises:
        ValueError: The configured keystore is malformed.
        OSError: `api_keys_file` is set but unreadable.
    """
    if settings.api_keys_file:
        return load_keystore_from_file(settings.api_keys_file)
    return parse_api_keys(settings.api_keys)


def known_key_ids(keystore: dict[str, ApiKeyPrincipal]) -> set[str]:
    """Extract the assignable principal names from a keystore.

    Args:
        keystore: `{secret: ApiKeyPrincipal}` from `resolve_keystore`.

    Returns:
        The set of `key_id` values — what `--owner` must match.
    """
    return {principal.key_id for principal in keystore.values()}


# ---------------------------------------------------------------------------
# Redis (jobs)
# ---------------------------------------------------------------------------


def _job_key(row_id: str, key_prefix: str = JOB_KEY_PREFIX) -> str:
    return f"{key_prefix}{row_id}"


async def _load_job(client: Any, key: str) -> Job | None:
    """Read and deserialize one `job:*` key.

    A corrupt or foreign payload sharing the prefix returns None and is
    logged rather than raised: an admin sweep must not abort halfway
    through because one key is garbage.

    Args:
        client: Async Redis client.
        key: Full Redis key, prefix included.

    Returns:
        The reconstructed `Job`, or None when the key vanished or
        could not be parsed.
    """
    payload = await client.get(key)
    if payload is None:
        return None
    if isinstance(payload, bytes):
        payload = payload.decode()
    try:
        return _job_from_json(payload)
    except (ValueError, KeyError, TypeError) as exc:
        log.warning(
            "admin_migrate_unparsable_job",
            extra={"key": key, "error": str(exc)},
        )
        return None


async def _write_job_preserving_ttl(client: Any, key: str, job: Job) -> None:
    """Rewrite a job row without disturbing its retention TTL.

    Terminal jobs are stored with `EX settings.api_job_retention_sec`
    by `RedisJobStore.update` (ADR 0027), so Redis handles retention
    without a sweeper. A naive `SET` here would drop that TTL and make
    every rewritten terminal job immortal — silently undoing retention
    for exactly the rows an admin sweep touches. Read `PTTL` first and
    re-apply it.

    The read-then-write is not atomic; a concurrent `update()` between
    the two could have its TTL clobbered. That window is microseconds
    on a store this tool is only ever pointed at deliberately, and the
    failure mode (one job keeps its previous retention window) is
    strictly less bad than dropping TTLs wholesale.

    Args:
        client: Async Redis client.
        key: Full Redis key.
        job: The mutated job to serialize back.
    """
    remaining_ms = int(await client.pttl(key))
    payload = _job_to_json(job)
    if remaining_ms > 0:
        await client.set(key, payload, px=remaining_ms)
    else:
        # -1 = key exists with no TTL, -2 = key is gone. Either way a
        # plain SET is the right call.
        await client.set(key, payload)


async def scan_null_owner_jobs(
    client: Any,
    *,
    key_prefix: str = JOB_KEY_PREFIX,
    older_than_days: int | None = None,
    limit: int | None = None,
    now: float | None = None,
) -> ScanResult:
    """Sweep the Redis keyspace for jobs with no `principal_key_id`.

    Uses `SCAN`, never `KEYS`: this runs against a live production
    Redis, and `KEYS` blocks the single-threaded server for the whole
    sweep.

    Every matched row is retained in the result, because the assign
    and delete paths mutate key by key and need the ids. `--limit` is
    therefore the memory bound as well as the blast-radius bound; each
    retained row is an id, a timestamp, and an 80-character preview.

    Args:
        client: Async Redis client.
        key_prefix: Job key namespace. Defaults to `job:`.
        older_than_days: Only match rows created before this many days
            ago. None matches every age.
        limit: Stop after this many matches and flag the result
            truncated. None scans the whole keyspace.
        now: Injectable clock for the age filter.

    Returns:
        A `ScanResult` with `backend="redis"`.
    """
    cutoff = cutoff_epoch(older_than_days, now=now)
    rows: list[NullOwnerRow] = []
    scanned = 0
    truncated = False
    cursor = 0

    while True:
        cursor, keys = await client.scan(
            cursor=cursor, match=f"{key_prefix}*", count=SCAN_COUNT
        )
        for raw_key in keys:
            key = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            scanned += 1
            job = await _load_job(client, key)
            if job is None or job.principal_key_id is not None:
                continue
            if cutoff is not None and job.created_at >= cutoff:
                continue
            if limit is not None and len(rows) >= limit:
                truncated = True
                break
            rows.append(
                NullOwnerRow(
                    row_id=job.job_id,
                    created_at=job.created_at,
                    preview=truncate_preview(job.query),
                )
            )
        if truncated or cursor == 0:
            break

    return ScanResult(
        store=STORE_JOBS,
        backend="redis",
        matched=len(rows),
        scanned=scanned,
        rows=rows,
        truncated=truncated,
    )


async def assign_job_owner(
    client: Any,
    rows: Sequence[NullOwnerRow],
    owner: str,
    *,
    key_prefix: str = JOB_KEY_PREFIX,
    dry_run: bool = True,
) -> int:
    """Stamp `principal_key_id = owner` on the given job rows.

    Each row is re-read before the write. If it gained an owner (or
    expired) between the scan and now, it is skipped — the sweep must
    never overwrite an owner some other writer just set.

    Args:
        client: Async Redis client.
        rows: Rows from `scan_null_owner_jobs`.
        owner: A validated `key_id`.
        key_prefix: Job key namespace.
        dry_run: When True, write nothing and return 0.

    Returns:
        Number of rows actually rewritten.
    """
    if dry_run:
        return 0
    changed = 0
    for row in rows:
        key = _job_key(row.row_id, key_prefix)
        job = await _load_job(client, key)
        if job is None or job.principal_key_id is not None:
            continue
        job.principal_key_id = owner
        await _write_job_preserving_ttl(client, key, job)
        changed += 1
    log.info(
        "admin_migrate_jobs_assigned",
        extra={"owner": owner, "changed": changed, "matched": len(rows)},
    )
    return changed


async def delete_null_owner_jobs(
    client: Any,
    rows: Sequence[NullOwnerRow],
    *,
    key_prefix: str = JOB_KEY_PREFIX,
    dry_run: bool = True,
) -> int:
    """Delete the given job rows.

    Same re-read guard as `assign_job_owner`: a row that acquired an
    owner since the scan is left alone, so a concurrent submit can't
    be destroyed by an in-flight sweep.

    Args:
        client: Async Redis client.
        rows: Rows from `scan_null_owner_jobs`.
        key_prefix: Job key namespace.
        dry_run: When True, delete nothing and return 0.

    Returns:
        Number of keys actually deleted.
    """
    if dry_run:
        return 0
    changed = 0
    for row in rows:
        key = _job_key(row.row_id, key_prefix)
        job = await _load_job(client, key)
        if job is None or job.principal_key_id is not None:
            continue
        await client.delete(key)
        changed += 1
        # One record per destroyed row. A count alone is not an audit
        # trail for an irreversible operation: once the key is gone
        # there is no other surviving evidence of which job ids the
        # operator removed, and "we deleted 412 jobs" cannot answer
        # "was mine one of them?". Volume here is by definition the
        # blast radius, which `--limit` already bounds.
        log.info(
            "admin_migrate_job_deleted",
            extra={
                "job_id": row.row_id,
                "created_at": row.created_at,
                "preview": row.preview,
            },
        )
    log.info(
        "admin_migrate_jobs_deleted",
        extra={"changed": changed, "matched": len(rows)},
    )
    return changed


# ---------------------------------------------------------------------------
# Postgres (conversations)
# ---------------------------------------------------------------------------


def _conversation_predicate(older_than_days: int | None) -> tuple[str, list[Any]]:
    """Build the shared `WHERE` fragment for every conversations query.

    Args:
        older_than_days: Age threshold in days, or None.

    Returns:
        `(sql_fragment, params)`. The fragment never includes the
        `WHERE` keyword so callers can nest it.
    """
    clauses = ["principal_key_id IS NULL"]
    params: list[Any] = []
    if older_than_days is not None:
        # Parameterised interval arithmetic — `%s * INTERVAL '1 day'`
        # keeps the day count a bound parameter instead of splicing it
        # into the statement text.
        clauses.append("created_at < NOW() - (%s * INTERVAL '1 day')")
        params.append(older_than_days)
    return " AND ".join(clauses), params


def build_assign_sql(
    older_than_days: int | None, limit: int | None
) -> tuple[str, list[Any]]:
    """Compose the single `UPDATE` that re-owns NULL-owner conversations.

    Kept a pure function so the statement shape is testable without a
    live database. The owner is always the first bind parameter; the
    returned params follow it.

    Args:
        older_than_days: Age threshold, or None.
        limit: Row cap, or None for no cap.

    Returns:
        `(sql, params_after_owner)`.
    """
    where, params = _conversation_predicate(older_than_days)
    if limit is None:
        return (
            f"UPDATE conversations SET principal_key_id = %s WHERE {where}",
            params,
        )
    # A bare `UPDATE ... LIMIT` is not valid Postgres; scope it through
    # a subselect on the primary key instead. Still one statement, so
    # it is still one transaction.
    return (
        "UPDATE conversations SET principal_key_id = %s "
        "WHERE conversation_id IN ("
        f"SELECT conversation_id FROM conversations WHERE {where} "
        "ORDER BY created_at LIMIT %s)",
        [*params, limit],
    )


def build_delete_sql(
    older_than_days: int | None, limit: int | None
) -> tuple[str, list[Any]]:
    """Compose the single `DELETE` for NULL-owner conversations.

    `conversation_jobs.conversation_id` references
    `conversations(conversation_id)` with `ON DELETE CASCADE` (see the
    DDL in `src/tools/postgres_pool.py`), so this statement cannot
    violate the FK and cannot leave orphaned children — Postgres
    removes the child rows in the same transaction. That is also why
    the caller counts the children *before* issuing the delete: the
    operator should see how much transcript goes with the parents.

    Args:
        older_than_days: Age threshold, or None.
        limit: Row cap, or None for no cap.

    Returns:
        `(sql, params)`.
    """
    where, params = _conversation_predicate(older_than_days)
    if limit is None:
        return (f"DELETE FROM conversations WHERE {where}", params)
    return (
        "DELETE FROM conversations WHERE conversation_id IN ("
        f"SELECT conversation_id FROM conversations WHERE {where} "
        "ORDER BY created_at LIMIT %s)",
        [*params, limit],
    )


def build_count_sql(older_than_days: int | None) -> tuple[str, list[Any]]:
    """Compose the exact `COUNT(*)` of NULL-owner conversations.

    Args:
        older_than_days: Age threshold, or None.

    Returns:
        `(sql, params)`.
    """
    where, params = _conversation_predicate(older_than_days)
    return (f"SELECT COUNT(*) FROM conversations WHERE {where}", params)


def build_cascade_count_sql(
    older_than_days: int | None, limit: int | None
) -> tuple[str, list[Any]]:
    """Count the `conversation_jobs` rows a delete would cascade away.

    Args:
        older_than_days: Age threshold, or None.
        limit: Row cap matching the pending delete, or None.

    Returns:
        `(sql, params)`.
    """
    where, params = _conversation_predicate(older_than_days)
    inner = f"SELECT conversation_id FROM conversations WHERE {where}"
    if limit is not None:
        inner += " ORDER BY created_at LIMIT %s"
        params = [*params, limit]
    return (
        f"SELECT COUNT(*) FROM conversation_jobs WHERE conversation_id IN ({inner})",
        params,
    )


def _conversations_unavailable() -> ScanResult | None:
    """Return an unavailable `ScanResult` when Postgres isn't the conv store.

    Two independent gates, and both matter. `build_conversation_store`
    selects on `conversation_store`, *not* on `postgres_url` — and
    `postgres_url` is shared with the paper cache, the embedding cache
    and the ADR 0034 checkpointer, so it is routinely set on a
    deployment whose conversations still live in process memory (the
    shipped compose file is exactly that: `POSTGRES_URL` set,
    `CONVERSATION_STORE` left at its `memory` default). Gating on
    `postgres_url` alone would point this tool at a `conversations`
    table nothing reads, report its rows as the deployment's orphans,
    and — under `delete --yes` — destroy them while the live
    conversations sat untouched in another process's heap. Mirror the
    `job_store` check in `_jobs_unavailable`: ask which implementation
    is selected first, then whether it is reachable.

    Returns:
        A `ScanResult` carrying the reason, or None when the Postgres
        half of the tool can run.
    """
    if settings.conversation_store != "postgres":
        return ScanResult(
            store=STORE_CONVERSATIONS,
            # Same reasoning as `_jobs_unavailable`: name the backend
            # the deployment actually selected.
            backend=settings.conversation_store,
            available=False,
            reason=(
                f"conversation_store={settings.conversation_store!r} — "
                "conversations are held in process memory and vanish on "
                "restart, so there is nothing durable to migrate. Any "
                "rows in the `conversations` table belong to a "
                "different deployment; refusing to touch them."
            ),
        )
    if not settings.postgres_url:
        return ScanResult(
            store=STORE_CONVERSATIONS,
            backend="postgres",
            available=False,
            reason=(
                "conversation_store='postgres' but postgres_url is "
                "empty — the API could not reach the conversations "
                "table either, so there is nothing to migrate."
            ),
        )
    return None


def scan_null_owner_conversations(
    *,
    older_than_days: int | None = None,
    limit: int | None = None,
) -> ScanResult:
    """Count NULL-owner conversations and pull a bounded sample.

    Unlike the Redis path this does not materialise every matched id:
    the assign and delete paths run as single SQL statements scoped by
    the same predicate, so the ids are never needed client-side.

    Args:
        older_than_days: Age threshold in days, or None.
        limit: Row cap the pending action would apply. Only used to
            decide whether the run is truncated.

    Returns:
        A `ScanResult` with `backend="postgres"`, or an unavailable
        result when the conversations store isn't Postgres.
    """
    unavailable = _conversations_unavailable()
    if unavailable is not None:
        return unavailable

    from src.tools.postgres_pool import _connection, init_schema

    init_schema()
    count_sql, count_params = build_count_sql(older_than_days)
    where, where_params = _conversation_predicate(older_than_days)
    # The sample must not name rows the pending action will not reach.
    # `--limit 2` against 100 orphans matches 2, so showing 10 rows
    # would advertise 8 survivors as casualties — actively misleading
    # in the `delete` preview an operator is meant to eyeball. Same
    # `ORDER BY created_at` as `build_delete_sql`, so the sample is the
    # head of the set the statement will actually touch.
    sample_rows = SAMPLE_ROWS if limit is None else min(SAMPLE_ROWS, limit)

    with _connection() as conn, conn.cursor() as cur:
        cur.execute(count_sql, tuple(count_params))
        count_row = cur.fetchone()
        total = int(count_row[0]) if count_row else 0
        cur.execute(
            f"SELECT conversation_id, created_at, title FROM conversations "
            f"WHERE {where} ORDER BY created_at LIMIT %s",
            (*where_params, sample_rows),
        )
        sample = [
            NullOwnerRow(
                row_id=str(r[0]),
                created_at=r[1].timestamp() if r[1] else 0.0,
                preview=truncate_preview(str(r[2])),
            )
            for r in cur.fetchall()
        ]

    truncated = limit is not None and total > limit
    matched = min(total, limit) if limit is not None else total
    return ScanResult(
        store=STORE_CONVERSATIONS,
        backend="postgres",
        matched=matched,
        scanned=total,
        rows=sample,
        truncated=truncated,
    )


def assign_conversation_owner(
    owner: str,
    *,
    older_than_days: int | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    matched: int = 0,
    truncated: bool = False,
) -> ActionResult:
    """Re-own NULL-owner conversations in one `UPDATE`.

    Args:
        owner: A validated `key_id`.
        older_than_days: Age threshold, or None.
        limit: Row cap, or None.
        dry_run: When True, issue nothing and report 0 changed.
        matched: Pre-computed match count from the scan pass.
        truncated: Whether the scan flagged `--limit` truncation.

    Returns:
        An `ActionResult` for the conversations store.
    """
    if dry_run:
        return ActionResult(
            store=STORE_CONVERSATIONS,
            action=ACTION_ASSIGN,
            matched=matched,
            changed=0,
            dry_run=True,
            truncated=truncated,
        )

    from src.tools.postgres_pool import _connection, init_schema

    init_schema()
    sql, params = build_assign_sql(older_than_days, limit)
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (owner, *params))
        changed = int(cur.rowcount or 0)
        conn.commit()
    log.info(
        "admin_migrate_conversations_assigned",
        extra={"owner": owner, "changed": changed},
    )
    return ActionResult(
        store=STORE_CONVERSATIONS,
        action=ACTION_ASSIGN,
        matched=matched,
        changed=changed,
        dry_run=False,
        truncated=truncated,
    )


def delete_null_owner_conversations(
    *,
    older_than_days: int | None = None,
    limit: int | None = None,
    dry_run: bool = True,
    matched: int = 0,
    truncated: bool = False,
) -> ActionResult:
    """Delete NULL-owner conversations in one `DELETE`.

    Counts the `conversation_jobs` children first so the operator sees
    the cascade size in both the dry run and the real run.

    Args:
        older_than_days: Age threshold, or None.
        limit: Row cap, or None.
        dry_run: When True, count only and report 0 changed.
        matched: Pre-computed match count from the scan pass.
        truncated: Whether the scan flagged `--limit` truncation.

    Returns:
        An `ActionResult` for the conversations store.
    """
    from src.tools.postgres_pool import _connection, init_schema

    init_schema()
    cascade_sql, cascade_params = build_cascade_count_sql(older_than_days, limit)
    with _connection() as conn, conn.cursor() as cur:
        cur.execute(cascade_sql, tuple(cascade_params))
        cascade_row = cur.fetchone()
        cascaded = int(cascade_row[0]) if cascade_row else 0
        if dry_run:
            return ActionResult(
                store=STORE_CONVERSATIONS,
                action=ACTION_DELETE,
                matched=matched,
                changed=0,
                dry_run=True,
                truncated=truncated,
                cascaded=cascaded,
            )
        sql, params = build_delete_sql(older_than_days, limit)
        cur.execute(sql, tuple(params))
        changed = int(cur.rowcount or 0)
        conn.commit()
    log.info(
        "admin_migrate_conversations_deleted",
        extra={"changed": changed, "cascaded": cascaded},
    )
    return ActionResult(
        store=STORE_CONVERSATIONS,
        action=ACTION_DELETE,
        matched=matched,
        changed=changed,
        dry_run=False,
        truncated=truncated,
        cascaded=cascaded,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def report_lines(results: Sequence[ScanResult]) -> list[str]:
    """Render scan results as operator-readable stdout lines.

    Keeps the key=value shape the rest of the codebase logs in, so a
    report is greppable, but stays plain text — an operator reads this
    directly.

    Args:
        results: One `ScanResult` per store the run touched.

    Returns:
        Lines to print, without trailing newlines.
    """
    lines: list[str] = []
    for result in results:
        lines.append(f"[{result.store}] backend={result.backend}")
        if not result.available:
            lines.append(f"  unavailable: {result.reason}")
            continue
        lines.append(
            f"  null_owner_rows={result.matched} inspected={result.scanned} "
            f"truncated={str(result.truncated).lower()}"
        )
        sample = result.sample()
        if not sample:
            lines.append("  nothing to do — no NULL-owner rows matched.")
            continue
        lines.append(f"  sample (showing {len(sample)} of {result.matched}):")
        for row in sample:
            lines.append(
                f"    {row.row_id}  created={_format_ts(row.created_at)}  "
                f'"{row.preview}"'
            )
        if result.truncated:
            lines.append(
                "  note: --limit truncated this run; more NULL-owner rows "
                "remain. Re-run to continue."
            )
    return lines


def summary_line(
    *,
    action: str,
    store: str,
    dry_run: bool,
    results: Sequence[ActionResult],
) -> str:
    """Build the single closing key=value line for the run.

    Args:
        action: The action that ran.
        store: The `--store` selection.
        dry_run: Whether `--yes` was withheld.
        results: Per-store action results.

    Returns:
        One line, safe to grep or pipe.
    """
    parts = [
        "admin_migrate_summary",
        f"action={action}",
        f"store={store}",
        f"dry_run={str(dry_run).lower()}",
    ]
    truncated = False
    for result in results:
        parts.append(f"{result.store}_matched={result.matched}")
        parts.append(f"{result.store}_changed={result.changed}")
        if result.cascaded:
            parts.append(f"{result.store}_cascaded={result.cascaded}")
        truncated = truncated or result.truncated
    parts.append(f"truncated={str(truncated).lower()}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.api.admin_migrate",
        description=(
            "Report on, re-own, or delete rows left without a "
            "principal_key_id by pre-ADR-0036 code. Dry run unless "
            "--yes is passed."
        ),
        epilog=(
            "Examples:\n"
            "  report every orphan:      report --store all\n"
            "  preview a re-own:         assign --owner internal\n"
            "  actually re-own:          assign --owner internal --yes\n"
            "  drop stale orphans:       delete --older-than-days 90 --yes\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action",
        nargs="?",
        default=ACTION_REPORT,
        choices=(ACTION_REPORT, ACTION_ASSIGN, ACTION_DELETE),
        help="What to do. Defaults to 'report'.",
    )
    parser.add_argument(
        "--store",
        default="all",
        choices=(STORE_JOBS, STORE_CONVERSATIONS, "all"),
        help="Which backing store to operate on (default: all).",
    )
    parser.add_argument(
        "--owner",
        default=None,
        help=(
            "key_id to assign. Required by 'assign'; validated against "
            "the live keystore before anything is written."
        ),
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=None,
        help="Only touch rows created more than N days ago.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Cap rows touched per store in one invocation; truncation "
            "is reported. With --store all the cap applies to each "
            "half, so the run can touch up to 2N rows."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually write. Without it the run is a dry run.",
    )
    return parser.parse_args(argv)


def _jobs_unavailable() -> ScanResult | None:
    """Return an unavailable `ScanResult` when Redis isn't the job store.

    Returns:
        A `ScanResult` carrying the reason, or None when the jobs half
        of the tool can run.
    """
    if settings.job_store != "redis":
        return ScanResult(
            store=STORE_JOBS,
            # Report the backend actually in use, not the one this tool
            # knows how to migrate — `backend=redis / unavailable:
            # job_store='memory'` reads as a contradiction to whoever
            # is triaging the output.
            backend=settings.job_store,
            available=False,
            reason=(
                f"job_store={settings.job_store!r} — jobs are held in "
                "process memory and vanish on restart, so there is "
                "nothing durable to migrate."
            ),
        )
    return None


async def _run_jobs(
    *,
    action: str,
    owner: str | None,
    older_than_days: int | None,
    limit: int | None,
    dry_run: bool,
) -> tuple[ScanResult, ActionResult]:
    """Scan and (optionally) mutate the Redis half.

    Args:
        action: `report`, `assign`, or `delete`.
        owner: Validated `key_id`, present only for `assign`.
        older_than_days: Age threshold, or None.
        limit: Row cap, or None.
        dry_run: Whether `--yes` was withheld.

    Returns:
        `(scan_result, action_result)`.
    """
    client = build_redis_client(settings.redis_url)
    try:
        scan = await scan_null_owner_jobs(
            client, older_than_days=older_than_days, limit=limit
        )
        changed = 0
        if action == ACTION_ASSIGN and owner is not None:
            changed = await assign_job_owner(
                client, scan.rows, owner, dry_run=dry_run
            )
        elif action == ACTION_DELETE:
            changed = await delete_null_owner_jobs(
                client, scan.rows, dry_run=dry_run
            )
    finally:
        # The CLI owns this client; the API's pool is a separate
        # process. Release it explicitly so a long report against a
        # remote Redis doesn't leave a socket in TIME_WAIT.
        await client.aclose()

    return scan, ActionResult(
        store=STORE_JOBS,
        action=action,
        matched=scan.matched,
        changed=changed,
        dry_run=dry_run,
        truncated=scan.truncated,
    )


def _run_conversations(
    *,
    action: str,
    owner: str | None,
    older_than_days: int | None,
    limit: int | None,
    dry_run: bool,
) -> tuple[ScanResult, ActionResult]:
    """Scan and (optionally) mutate the Postgres half.

    Args:
        action: `report`, `assign`, or `delete`.
        owner: Validated `key_id`, present only for `assign`.
        older_than_days: Age threshold, or None.
        limit: Row cap, or None.
        dry_run: Whether `--yes` was withheld.

    Returns:
        `(scan_result, action_result)`.
    """
    scan = scan_null_owner_conversations(
        older_than_days=older_than_days, limit=limit
    )
    if not scan.available:
        return scan, ActionResult(
            store=STORE_CONVERSATIONS, action=action, dry_run=dry_run
        )

    if action == ACTION_ASSIGN and owner is not None:
        result = assign_conversation_owner(
            owner,
            older_than_days=older_than_days,
            limit=limit,
            dry_run=dry_run,
            matched=scan.matched,
            truncated=scan.truncated,
        )
    elif action == ACTION_DELETE:
        result = delete_null_owner_conversations(
            older_than_days=older_than_days,
            limit=limit,
            dry_run=dry_run,
            matched=scan.matched,
            truncated=scan.truncated,
        )
    else:
        result = ActionResult(
            store=STORE_CONVERSATIONS,
            action=ACTION_REPORT,
            matched=scan.matched,
            dry_run=dry_run,
            truncated=scan.truncated,
        )
    return scan, result


def _validate(args: argparse.Namespace) -> str | None:
    """Check argument combinations that argparse can't express.

    Args:
        args: Parsed namespace.

    Returns:
        An error message, or None when the invocation is valid.
    """
    if args.older_than_days is not None and args.older_than_days < 0:
        return "--older-than-days must be >= 0."
    if args.limit is not None and args.limit < 1:
        return "--limit must be >= 1."
    if args.action != ACTION_ASSIGN:
        if args.owner is not None:
            return f"--owner is only meaningful with 'assign', not {args.action!r}."
        return None
    if not args.owner:
        return "assign requires --owner KEY_ID."

    # Validating against the live keystore is the point of this check:
    # stamping an unknown key_id onto orphaned rows leaves them exactly
    # as invisible as they were, only harder to find next time (ADR
    # 0038).
    try:
        keystore = resolve_keystore()
    except (ValueError, OSError) as exc:
        return f"could not read the keystore: {exc}"
    valid = known_key_ids(keystore)
    if not valid:
        return (
            "no API keys are configured; set `api_keys` or "
            "`api_keys_file` so --owner can be validated."
        )
    if args.owner not in valid:
        return (
            f"--owner {args.owner!r} is not a configured key_id. "
            f"Known: {', '.join(sorted(valid))}"
        )
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument vector without the program name. Defaults to
            `sys.argv[1:]`.

    Returns:
        0 on success (a clean dry run counts), 1 on a runtime failure,
        2 on a usage or validation failure.
    """
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    error = _validate(args)
    if error is not None:
        print(f"Error: {error}", file=sys.stderr)
        return EXIT_USAGE

    # `report` never writes, so `report --yes` is a no-op rather than a
    # live run; saying `dry_run=false` on that line would tell an
    # operator grepping the summary that a mutation happened.
    dry_run = not args.yes or args.action == ACTION_REPORT
    want_jobs = args.store in (STORE_JOBS, "all")
    want_conversations = args.store in (STORE_CONVERSATIONS, "all")

    scans: list[ScanResult] = []
    actions: list[ActionResult] = []

    try:
        if want_jobs:
            unavailable = _jobs_unavailable()
            if unavailable is not None:
                scans.append(unavailable)
                actions.append(
                    ActionResult(
                        store=STORE_JOBS, action=args.action, dry_run=dry_run
                    )
                )
            else:
                scan, result = asyncio.run(
                    _run_jobs(
                        action=args.action,
                        owner=args.owner,
                        older_than_days=args.older_than_days,
                        limit=args.limit,
                        dry_run=dry_run,
                    )
                )
                scans.append(scan)
                actions.append(result)

        if want_conversations:
            scan, result = _run_conversations(
                action=args.action,
                owner=args.owner,
                older_than_days=args.older_than_days,
                limit=args.limit,
                dry_run=dry_run,
            )
            scans.append(scan)
            actions.append(result)
    except Exception as exc:  # noqa: BLE001
        # Anything that escapes here is an infrastructure failure — an
        # unreachable Redis, a Postgres that refused the connection.
        # Log the traceback for the operator's log pipeline, print the
        # short form for the terminal.
        log.exception("admin_migrate_failed", extra={"action": args.action})
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_RUNTIME

    # Human-facing report on stdout; the structured audit trail already
    # went to the logger (stderr) from the action helpers above.
    for line in report_lines(scans):
        print(line)

    if dry_run and args.action != ACTION_REPORT:
        print(
            f"Dry run: nothing was written. Re-run with --yes to apply "
            f"the {args.action} above."
        )

    print(
        summary_line(
            action=args.action,
            store=args.store,
            dry_run=dry_run,
            results=actions,
        )
    )
    log.info(
        "admin_migrate_completed",
        extra={
            "action": args.action,
            "store": args.store,
            "dry_run": dry_run,
            "changed": sum(r.changed for r in actions),
        },
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
