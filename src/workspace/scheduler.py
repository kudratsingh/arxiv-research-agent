"""Daily local occurrences: first fold, next valid DST instant, one bounded catch-up."""
from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from src.workspace.schemas import ScheduleWrite
from src.workspace.store import ConflictError, WorkspaceStore


def local_occurrence(day: datetime, local_time: str, zone: str) -> datetime:
    """Move nonexistent wall time forward to the first real minute; repeated hour uses fold0."""
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", local_time):
        raise ValueError("local_time must be HH:MM")
    tz = ZoneInfo(zone)
    hour, minute = map(int, local_time.split(":"))
    naive = datetime(day.year, day.month, day.day, hour, minute)
    for offset in range(181):
        candidate = (naive + timedelta(minutes=offset)).replace(tzinfo=tz, fold=0)
        if candidate.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == candidate.replace(tzinfo=None):
            return candidate.astimezone(UTC)
    raise ValueError("no valid daily occurrence within three hours")


def next_occurrence(now: datetime, local_time: str, zone: str) -> datetime:
    local = now.astimezone(ZoneInfo(zone))
    candidate = local_occurrence(local, local_time, zone)
    return candidate if candidate > now else local_occurrence(local + timedelta(days=1), local_time, zone)


def schedule(store: WorkspaceStore, owner: str) -> dict[str, Any]:
    store._owner(owner)
    store.migrate()
    with store.pool.connection() as conn:
        row = conn.execute("SELECT revision,data,next_check FROM workspace_schedules WHERE owner=%s", (owner,)).fetchone()
    return {"revision": row[0], **row[1], "next_check": row[2].isoformat() if row[2] else None} if row else {"revision": 0, "enabled": False, "timezone": "America/Los_Angeles", "local_time": "07:00", "next_check": None}


def write_schedule(store: WorkspaceStore, owner: str, write: ScheduleWrite, *, approved: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    due = next_occurrence(now, write.data.local_time, write.data.timezone)
    if write.data.enabled and not approved:
        raise ValueError("owner confirmation of the recurring local time is required")
    def action(conn: Any) -> dict[str, Any]:
        row = conn.execute("SELECT revision FROM workspace_schedules WHERE owner=%s", (owner,)).fetchone()
        if (row[0] if row else 0) != write.revision:
            raise ConflictError("schedule changed; reload before saving")
        data = write.data.model_dump()
        revision = write.revision + 1
        conn.execute("INSERT INTO workspace_schedules VALUES (%s,%s,%s,%s) ON CONFLICT(owner) DO UPDATE SET revision=EXCLUDED.revision,data=EXCLUDED.data,next_check=EXCLUDED.next_check", (owner, revision, Jsonb(data), due if data["enabled"] else None))
        if not data["enabled"]:
            conn.execute("UPDATE workspace_tasks SET state='cancelled',reason='schedule paused' WHERE owner=%s AND state IN ('queued','running')", (owner,))
        store._history(conn, owner, "schedule", owner, revision, data)
        return {"revision": revision, **data, "next_check": due.isoformat() if data["enabled"] else None}
    return store._mutate(owner, write.request_id, write.model_dump(), action)


def enqueue_due(store: WorkspaceStore, *, now: datetime) -> int:
    store.migrate()
    count = 0
    with store.pool.connection() as conn:
        rows = conn.execute("SELECT owner,data,next_check FROM workspace_schedules WHERE next_check<=%s AND (data->>'enabled')::boolean FOR UPDATE SKIP LOCKED", (now,)).fetchall()
        for owner, data, due in rows:
            local_date = now.astimezone(ZoneInfo(data["timezone"])).date().isoformat()
            key = "daily:" + local_date
            # A queued/expired occurrence can already exist when the laptop
            # sleeps. Coalesce it before creating today's single catch-up.
            conn.execute("UPDATE workspace_tasks SET state='cancelled',reason=%s WHERE owner=%s AND occurrence_key LIKE 'daily:%%' AND occurrence_key<>%s AND (state='queued' OR (state='running' AND lease_until<=%s))", ("coalesced into " + key, owner, key, now))
            row = conn.execute("INSERT INTO workspace_tasks(id,owner,occurrence_key,state,due_at,reason) VALUES (%s,%s,%s,'queued',%s,%s) ON CONFLICT(owner,occurrence_key) DO NOTHING RETURNING id", (uuid.uuid4().hex, owner, key, now, "catch-up from " + due.isoformat() if now - due > timedelta(hours=1) else "scheduled local check")).fetchone()
            count += int(row is not None)
            conn.execute("UPDATE workspace_schedules SET next_check=%s WHERE owner=%s", (next_occurrence(now, data["local_time"], data["timezone"]), owner))
    return count


def claim(store: WorkspaceStore, worker: str, *, now: datetime) -> dict[str, Any] | None:
    store.migrate()
    with store.pool.connection() as conn:
        conn.execute("UPDATE workspace_tasks SET state='failed',reason='lease expired after final attempt' WHERE state='running' AND attempts>=3 AND lease_until<=%s", (now,))
        row = conn.execute("SELECT t.id,t.owner,t.attempts FROM workspace_tasks t JOIN workspace_schedules s USING(owner) WHERE (s.data->>'enabled')::boolean AND t.attempts<3 AND ((t.state='queued' AND t.due_at<=%s) OR (t.state='running' AND t.lease_until<=%s)) ORDER BY t.due_at,t.id FOR UPDATE OF t SKIP LOCKED LIMIT 1", (now, now)).fetchone()
        if not row:
            return None
        id_, owner, attempts = row
        conn.execute("UPDATE workspace_tasks SET state='running',lease_owner=%s,lease_until=%s,attempts=attempts+1 WHERE id=%s", (worker, now + timedelta(minutes=5), id_))
        return {"id": id_, "owner": owner, "attempts": attempts + 1, "worker": worker}


def run_once(store: WorkspaceStore, build: Callable[[str], dict[str, Any]], *, now: datetime | None = None, worker: str | None = None) -> dict[str, Any] | None:
    controlled = now is not None
    now = now or datetime.now(UTC)
    enqueue_due(store, now=now)
    task = claim(store, worker or uuid.uuid4().hex, now=now)
    if not task:
        return None
    try:
        # No DB row locks are held during fetch/ranking. Publication is fenced by lease.
        edition = build(task["owner"])
    except Exception as exc:
        with store.pool.connection() as conn:
            conn.execute("UPDATE workspace_tasks SET state=%s,reason=%s,due_at=%s,lease_until=NULL WHERE id=%s AND lease_owner=%s AND state='running'", ("failed" if task["attempts"] >= 3 else "queued", type(exc).__name__, now + timedelta(minutes=task["attempts"]), task["id"], task["worker"]))
        return {**task, "state": "failed_attempt"}
    finished = now if controlled else datetime.now(UTC)
    with store.pool.connection() as conn:
        row = conn.execute("UPDATE workspace_tasks SET state='ready',lease_until=NULL WHERE id=%s AND lease_owner=%s AND state='running' AND lease_until>%s RETURNING owner", (task["id"], task["worker"], finished)).fetchone()
        if row:
            conn.execute("INSERT INTO workspace_editions(owner,id,data) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (task["owner"], edition["id"], Jsonb(edition)))
            conn.execute("INSERT INTO workspace_delivery_intents(owner,task_id,edition_id,channel) VALUES (%s,%s,%s,'in-app') ON CONFLICT DO NOTHING", (task["owner"], task["id"], edition["id"]))
    return {**task, "state": "ready" if row else "lease_lost"}


def tasks(store: WorkspaceStore, owner: str) -> list[dict[str, Any]]:
    store._owner(owner)
    store.migrate()
    with store.pool.connection() as conn:
        rows = conn.execute("SELECT id,state,due_at,attempts,reason,lease_until FROM workspace_tasks WHERE owner=%s ORDER BY due_at DESC LIMIT 30", (owner,)).fetchall()
    return [dict(zip(("id", "state", "due_at", "attempts", "reason", "lease_until"), (v.isoformat() if isinstance(v, datetime) else v for v in row), strict=True)) for row in rows]
