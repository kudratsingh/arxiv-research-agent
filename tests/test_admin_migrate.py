"""Tests for the legacy NULL-owner cleanup CLI (ADR 0038).

ADR 0036 made `principal_key_id=NULL` rows invisible to every
principal under auth-on. `src/api/admin_migrate.py` is the
operator-driven escape hatch for that state, and it is
destructive-capable, so the tests care as much about the safety
ergonomics as about the mutation logic:

- dry run is the default and must write nothing,
- an unknown `--owner` must be refused *before* anything is written,
- a rewritten terminal job must keep its retention TTL, otherwise a
  cleanup pass silently makes expiring rows immortal,
- `--limit` truncation must show up in the output rather than
  quietly leaving work behind.

Marked `integration`: these drive the real redis-py client against
`fakeredis`. The Postgres half is covered through its pure SQL
builders plus the "not configured" path, so the suite stays fast.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import fakeredis
import fakeredis.aioredis
import pytest

from src.api import admin_migrate
from src.api.admin_migrate import (
    EXIT_OK,
    EXIT_USAGE,
    SAMPLE_ROWS,
    NullOwnerRow,
    assign_job_owner,
    build_assign_sql,
    build_cascade_count_sql,
    build_count_sql,
    build_delete_sql,
    cutoff_epoch,
    delete_null_owner_jobs,
    main,
    truncate_preview,
)
from src.api.jobs import Job, JobStatus
from src.api.redis_store import JOB_KEY_PREFIX, _job_from_json, _job_to_json
from src.config import Settings

pytestmark = pytest.mark.integration

DAY = 86400.0


# ---- Fixtures / helpers ------------------------------------------------


def _client(server: fakeredis.FakeServer) -> fakeredis.aioredis.FakeRedis:
    """Fresh async client over a shared in-process Redis.

    `main()` owns (and closes) whatever `build_redis_client` hands it,
    so each helper takes its own client bound to the same `FakeServer`
    — closing one must not tear down the state the assertions read.
    """
    return fakeredis.aioredis.FakeRedis(server=server)


@pytest.fixture
def server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def redis_cli(
    server: fakeredis.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> fakeredis.FakeServer:
    """Point the CLI's client factory at the shared fake server."""
    monkeypatch.setattr(
        admin_migrate, "build_redis_client", lambda url: _client(server)
    )
    return server


@pytest.fixture
def redis_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Redis job store, two known keys, Postgres deliberately absent."""
    overridden = Settings(
        job_store="redis",
        api_keys="internal:sk_int,partner:sk_partner",
        postgres_url="",
    )
    monkeypatch.setattr(admin_migrate, "settings", overridden)
    return overridden


def _job(
    job_id: str,
    *,
    owner: str | None = None,
    age_days: float = 0.0,
    status: JobStatus = JobStatus.succeeded,
    query: str = "how do transformers scale",
) -> Job:
    return Job(
        job_id=job_id,
        query=query,
        status=status,
        created_at=time.time() - age_days * DAY,
        principal_key_id=owner,
    )


def seed(
    server: fakeredis.FakeServer,
    jobs: list[Job],
    *,
    ttl_ms: dict[str, int] | None = None,
) -> None:
    """Write jobs straight into the fake store, optionally with a TTL."""

    async def _run() -> None:
        client = _client(server)
        try:
            for job in jobs:
                px = (ttl_ms or {}).get(job.job_id)
                await client.set(
                    f"{JOB_KEY_PREFIX}{job.job_id}",
                    _job_to_json(job),
                    **({"px": px} if px else {}),
                )
        finally:
            await client.aclose()

    asyncio.run(_run())


def owners(server: fakeredis.FakeServer) -> dict[str, str | None]:
    """Snapshot `{job_id: principal_key_id}` for every stored job."""

    async def _run() -> dict[str, str | None]:
        client = _client(server)
        try:
            keys = await client.keys(f"{JOB_KEY_PREFIX}*")
            out: dict[str, str | None] = {}
            for key in keys:
                payload = await client.get(key)
                job = _job_from_json(payload.decode())
                out[job.job_id] = job.principal_key_id
            return out
        finally:
            await client.aclose()

    return asyncio.run(_run())


def pttl(server: fakeredis.FakeServer, job_id: str) -> int:
    """Remaining TTL in milliseconds; -1 = persistent, -2 = missing."""

    async def _run() -> int:
        client = _client(server)
        try:
            return int(await client.pttl(f"{JOB_KEY_PREFIX}{job_id}"))
        finally:
            await client.aclose()

    return asyncio.run(_run())


# ---- Pure helpers ------------------------------------------------------


class TestPureHelpers:
    def test_truncate_preview_clips_and_marks(self) -> None:
        long = "x" * 200
        clipped = truncate_preview(long, max_chars=20)
        assert len(clipped) == 20
        assert clipped.endswith("…")

    def test_truncate_preview_collapses_whitespace(self) -> None:
        assert truncate_preview("  a\n\n b  ") == "a b"

    def test_cutoff_epoch_none_disables_the_filter(self) -> None:
        assert cutoff_epoch(None) is None

    def test_cutoff_epoch_subtracts_days(self) -> None:
        assert cutoff_epoch(3, now=1_000_000.0) == 1_000_000.0 - 3 * DAY

    def test_assign_sql_without_limit_is_a_flat_update(self) -> None:
        sql, params = build_assign_sql(None, None)
        assert sql == (
            "UPDATE conversations SET principal_key_id = %s "
            "WHERE principal_key_id IS NULL"
        )
        assert params == []

    def test_assign_sql_with_limit_uses_a_subselect(self) -> None:
        # A bare `UPDATE ... LIMIT` is invalid Postgres; the cap has to
        # ride on a primary-key subselect.
        sql, params = build_assign_sql(30, 5)
        assert "conversation_id IN (" in sql
        assert "LIMIT %s" in sql
        assert "INTERVAL '1 day'" in sql
        assert params == [30, 5]

    def test_assign_sql_binds_owner_before_the_predicate_params(self) -> None:
        # The caller executes `(owner, *params)`, so the returned params
        # must line up with the placeholders *after* the SET clause.
        # Getting this backwards would stamp the day count as the owner.
        sql, params = build_assign_sql(30, 5)
        head, _, tail = sql.partition("SET principal_key_id = %s")
        assert "%s" not in head
        assert tail.count("%s") == len(params) == 2

    def test_delete_sql_targets_conversations_only(self) -> None:
        # `conversation_jobs` cascades from the FK, so the statement
        # never names the child table.
        sql, params = build_delete_sql(None, None)
        assert sql == "DELETE FROM conversations WHERE principal_key_id IS NULL"
        assert params == []
        assert "conversation_jobs" not in sql

    def test_delete_sql_with_limit_orders_params_age_then_limit(self) -> None:
        sql, params = build_delete_sql(90, 25)
        assert params == [90, 25]
        # Placeholder order in the text must match the param order.
        assert sql.index("INTERVAL '1 day'") < sql.index("LIMIT %s")

    def test_count_sql_counts_only_null_owner_rows(self) -> None:
        sql, params = build_count_sql(None)
        assert sql == (
            "SELECT COUNT(*) FROM conversations WHERE principal_key_id IS NULL"
        )
        assert params == []

    def test_count_sql_applies_the_age_predicate(self) -> None:
        sql, params = build_count_sql(7)
        assert "created_at < NOW() - (%s * INTERVAL '1 day')" in sql
        assert params == [7]

    def test_cascade_count_sql_counts_children_of_the_same_set(self) -> None:
        # The cascade preview must be scoped by the identical predicate
        # the DELETE uses, or the operator is shown the wrong number of
        # transcript rows about to disappear.
        cascade_sql, cascade_params = build_cascade_count_sql(90, 25)
        delete_sql, delete_params = build_delete_sql(90, 25)
        assert cascade_sql.startswith("SELECT COUNT(*) FROM conversation_jobs")
        inner = "SELECT conversation_id FROM conversations WHERE"
        assert cascade_sql[cascade_sql.index(inner) :].rstrip(")") == (
            delete_sql[delete_sql.index(inner) :].rstrip(")")
        )
        assert cascade_params == delete_params

    def test_cascade_count_sql_without_limit_has_no_limit_clause(self) -> None:
        sql, params = build_cascade_count_sql(None, None)
        assert "LIMIT" not in sql
        assert params == []


# ---- report ------------------------------------------------------------


def test_report_counts_null_owner_rows_without_mutating(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(
        redis_cli,
        [
            _job("orphan1"),
            _job("orphan2"),
            _job("owned1", owner="internal"),
        ],
    )

    assert main(["report", "--store", "jobs"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "null_owner_rows=2" in out
    assert "inspected=3" in out
    assert "jobs_matched=2" in out
    assert "jobs_changed=0" in out
    # Report is read-only.
    assert owners(redis_cli) == {
        "orphan1": None,
        "orphan2": None,
        "owned1": "internal",
    }


def test_report_is_the_default_action(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("orphan1")])
    assert main(["--store", "jobs"]) == EXIT_OK
    assert "action=report" in capsys.readouterr().out


def test_report_sample_is_bounded_and_truncated(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Never dump full bodies into an operator's scrollback."""
    seed(redis_cli, [_job("orphan1", query="q" * 500)])
    main(["report", "--store", "jobs"])
    out = capsys.readouterr().out
    assert "…" in out
    assert "q" * 200 not in out


def test_report_sample_never_exceeds_sample_rows(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The counts are exact; the named rows are capped. A store with
    thousands of orphans must not page them all through the operator's
    scrollback."""
    seed(redis_cli, [_job(f"orphan{i}") for i in range(SAMPLE_ROWS * 3)])

    assert main(["report", "--store", "jobs"]) == EXIT_OK

    out = capsys.readouterr().out
    assert f"null_owner_rows={SAMPLE_ROWS * 3}" in out
    named = [line for line in out.splitlines() if "created=" in line]
    assert len(named) == SAMPLE_ROWS
    assert f"showing {SAMPLE_ROWS} of {SAMPLE_ROWS * 3}" in out


def test_report_says_nothing_to_do_on_a_clean_store(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("owned1", owner="internal")])
    assert main(["report", "--store", "jobs"]) == EXIT_OK
    assert "nothing to do" in capsys.readouterr().out


# ---- assign ------------------------------------------------------------


def test_dry_run_assign_mutates_nothing(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("orphan1"), _job("orphan2")])

    assert main(["assign", "--owner", "internal", "--store", "jobs"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "Dry run: nothing was written" in out
    assert "dry_run=true" in out
    assert "jobs_matched=2" in out
    assert "jobs_changed=0" in out
    assert owners(redis_cli) == {"orphan1": None, "orphan2": None}


def test_assign_with_yes_stamps_only_null_owner_rows(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(
        redis_cli,
        [
            _job("orphan1"),
            _job("orphan2"),
            _job("owned1", owner="partner"),
        ],
    )

    code = main(
        ["assign", "--owner", "internal", "--store", "jobs", "--yes"]
    )
    assert code == EXIT_OK
    assert "jobs_changed=2" in capsys.readouterr().out
    assert owners(redis_cli) == {
        "orphan1": "internal",
        "orphan2": "internal",
        # Someone else's row is never re-owned.
        "owned1": "partner",
    }


def test_assign_rejects_an_owner_that_is_not_in_the_keystore(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Assigning to a non-existent key would bury the rows one level
    deeper: still invisible, but now for a subtler reason."""
    seed(redis_cli, [_job("orphan1")])

    code = main(["assign", "--owner", "ghost", "--store", "jobs", "--yes"])

    assert code == EXIT_USAGE
    err = capsys.readouterr().err
    assert "not a configured key_id" in err
    assert "internal" in err  # the message lists what IS valid
    assert owners(redis_cli) == {"orphan1": None}


def test_assign_requires_an_owner(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("orphan1")])
    assert main(["assign", "--store", "jobs", "--yes"]) == EXIT_USAGE
    assert "requires --owner" in capsys.readouterr().err
    assert owners(redis_cli) == {"orphan1": None}


def test_assign_rejects_an_owner_when_no_keys_are_configured(
    redis_cli: fakeredis.FakeServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        admin_migrate,
        "settings",
        Settings(job_store="redis", api_keys="", postgres_url=""),
    )
    seed(redis_cli, [_job("orphan1")])
    assert main(["assign", "--owner", "internal", "--yes"]) == EXIT_USAGE
    assert owners(redis_cli) == {"orphan1": None}


def test_assign_reads_the_owner_from_a_keystore_file(
    redis_cli: fakeredis.FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resolution order mirrors `create_app`: `api_keys_file` wins."""
    keyfile = tmp_path / "keys.json"
    keyfile.write_text('{"fromfile": "sk_file"}', encoding="utf-8")
    monkeypatch.setattr(
        admin_migrate,
        "settings",
        Settings(
            job_store="redis",
            api_keys="internal:sk_int",
            api_keys_file=str(keyfile),
            postgres_url="",
        ),
    )
    seed(redis_cli, [_job("orphan1")])

    # The string keystore's `internal` is NOT valid once a file is set.
    assert main(["assign", "--owner", "internal", "--yes"]) == EXIT_USAGE
    assert main(["assign", "--owner", "fromfile", "--yes"]) == EXIT_OK
    assert owners(redis_cli) == {"orphan1": "fromfile"}


def test_assign_is_idempotent(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("orphan1"), _job("orphan2")])

    assert main(["assign", "--owner", "internal", "--store", "jobs", "--yes"]) == EXIT_OK
    capsys.readouterr()

    assert main(["assign", "--owner", "internal", "--store", "jobs", "--yes"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "null_owner_rows=0" in out
    assert "nothing to do" in out
    assert "jobs_changed=0" in out


# ---- Re-read guard (scan → write race) ---------------------------------


class TestReReadGuard:
    """A scan and the write that follows it are not one transaction.

    Between the two, a concurrent submit can hand the row a real owner.
    Both mutating paths re-read the key and skip it if that happened —
    otherwise an admin sweep would clobber (or destroy) a live job that
    was created microseconds after the scan started.
    """

    def test_assign_skips_a_row_that_gained_an_owner_since_the_scan(
        self, server: fakeredis.FakeServer
    ) -> None:
        seed(server, [_job("racer", owner="partner")])
        # The scan saw it as an orphan; by write time it is owned.
        stale = [NullOwnerRow(row_id="racer", created_at=time.time(), preview="q")]

        async def _run() -> int:
            client = _client(server)
            try:
                return await assign_job_owner(
                    client, stale, "internal", dry_run=False
                )
            finally:
                await client.aclose()

        assert asyncio.run(_run()) == 0
        assert owners(server) == {"racer": "partner"}

    def test_delete_skips_a_row_that_gained_an_owner_since_the_scan(
        self, server: fakeredis.FakeServer
    ) -> None:
        seed(server, [_job("racer", owner="partner")])
        stale = [NullOwnerRow(row_id="racer", created_at=time.time(), preview="q")]

        async def _run() -> int:
            client = _client(server)
            try:
                return await delete_null_owner_jobs(client, stale, dry_run=False)
            finally:
                await client.aclose()

        assert asyncio.run(_run()) == 0
        assert owners(server) == {"racer": "partner"}

    def test_assign_does_not_resurrect_a_row_that_vanished(
        self, server: fakeredis.FakeServer
    ) -> None:
        """A key that expired between the scan and the write must stay
        gone — a plain SET would recreate it, without its TTL."""
        stale = [NullOwnerRow(row_id="ghost", created_at=time.time(), preview="q")]

        async def _run() -> int:
            client = _client(server)
            try:
                return await assign_job_owner(
                    client, stale, "internal", dry_run=False
                )
            finally:
                await client.aclose()

        assert asyncio.run(_run()) == 0
        assert owners(server) == {}


# ---- TTL preservation --------------------------------------------------


def test_assign_preserves_an_existing_ttl(
    redis_cli: fakeredis.FakeServer, redis_settings: Settings
) -> None:
    """Terminal jobs carry a retention TTL from `RedisJobStore.update`
    (ADR 0027). Rewriting one with a plain SET would drop that TTL and
    make every row this tool touches immortal — silently undoing
    retention for exactly the rows an admin sweep visits."""
    seed(
        redis_cli,
        [_job("expiring", status=JobStatus.succeeded)],
        ttl_ms={"expiring": 60_000},
    )
    before = pttl(redis_cli, "expiring")
    assert 0 < before <= 60_000

    assert main(["assign", "--owner", "internal", "--store", "jobs", "--yes"]) == EXIT_OK

    after = pttl(redis_cli, "expiring")
    assert after > 0, "TTL was cleared — expired jobs would be resurrected"
    assert after <= before
    assert owners(redis_cli) == {"expiring": "internal"}


def test_assign_does_not_invent_a_ttl_on_a_persistent_row(
    redis_cli: fakeredis.FakeServer, redis_settings: Settings
) -> None:
    """The mirror of the above: a running job has no TTL and must not
    acquire one just because it was re-owned."""
    seed(redis_cli, [_job("running1", status=JobStatus.running)])
    assert pttl(redis_cli, "running1") == -1

    main(["assign", "--owner", "internal", "--store", "jobs", "--yes"])

    assert pttl(redis_cli, "running1") == -1


# ---- delete ------------------------------------------------------------


def test_delete_with_yes_removes_only_null_owner_rows(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(
        redis_cli,
        [
            _job("orphan1"),
            _job("orphan2"),
            _job("owned1", owner="internal"),
        ],
    )

    assert main(["delete", "--store", "jobs", "--yes"]) == EXIT_OK
    assert "jobs_changed=2" in capsys.readouterr().out
    assert owners(redis_cli) == {"owned1": "internal"}


def test_delete_dry_run_removes_nothing(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job("orphan1")])
    assert main(["delete", "--store", "jobs"]) == EXIT_OK
    assert "Dry run: nothing was written" in capsys.readouterr().out
    assert owners(redis_cli) == {"orphan1": None}


# ---- scope filters -----------------------------------------------------


def test_older_than_days_excludes_rows_newer_than_the_cutoff(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(
        redis_cli,
        [
            _job("ancient", age_days=120),
            _job("recent", age_days=1),
        ],
    )

    code = main(
        [
            "assign",
            "--owner",
            "internal",
            "--store",
            "jobs",
            "--older-than-days",
            "30",
            "--yes",
        ]
    )
    assert code == EXIT_OK
    assert "jobs_changed=1" in capsys.readouterr().out
    assert owners(redis_cli) == {"ancient": "internal", "recent": None}


def test_limit_truncation_is_reported_not_silent(
    redis_cli: fakeredis.FakeServer,
    redis_settings: Settings,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed(redis_cli, [_job(f"orphan{i}") for i in range(5)])

    code = main(
        ["assign", "--owner", "internal", "--store", "jobs", "--limit", "2", "--yes"]
    )
    assert code == EXIT_OK

    out = capsys.readouterr().out
    assert "truncated=true" in out
    assert "--limit truncated this run" in out
    assert "jobs_changed=2" in out
    assigned = [k for k, v in owners(redis_cli).items() if v == "internal"]
    assert len(assigned) == 2


# ---- store availability ------------------------------------------------


def test_jobs_half_is_skipped_when_the_job_store_is_memory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        admin_migrate,
        "settings",
        Settings(job_store="memory", api_keys="internal:sk_int", postgres_url=""),
    )
    assert main(["report", "--store", "jobs"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "unavailable" in out
    assert "job_store='memory'" in out


def test_conversations_half_is_skipped_when_the_store_is_memory(
    redis_cli: fakeredis.FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`postgres_url` is shared with the paper/embedding caches and the
    ADR 0034 checkpointer, so it is set on plenty of deployments whose
    conversations still live in process memory — the shipped compose
    file is one. Selecting on it instead of on `conversation_store`
    would point the tool at a `conversations` table nothing reads and,
    under `delete --yes`, destroy another deployment's rows."""
    monkeypatch.setattr(
        admin_migrate,
        "settings",
        Settings(
            job_store="redis",
            api_keys="internal:sk_int",
            conversation_store="memory",
            postgres_url="postgresql://unreachable:5432/nope",
        ),
    )
    seed(redis_cli, [_job("orphan1")])

    # No connection is attempted: an unreachable URL would raise.
    assert main(["delete", "--store", "all", "--yes"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "[conversations] backend=memory" in out
    assert "conversation_store='memory'" in out
    assert "conversations_changed=0" in out
    # The jobs half still ran.
    assert "jobs_changed=1" in out


def test_conversations_half_is_skipped_without_postgres_url(
    redis_cli: fakeredis.FakeServer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        admin_migrate,
        "settings",
        Settings(
            job_store="redis",
            api_keys="internal:sk_int",
            conversation_store="postgres",
            postgres_url="",
        ),
    )
    seed(redis_cli, [_job("orphan1")])
    assert main(["report", "--store", "all"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "[conversations] backend=postgres" in out
    assert "postgres_url is empty" in out
    # The jobs half still ran.
    assert "null_owner_rows=1" in out


# ---- exit codes --------------------------------------------------------


class TestExitCodes:
    def test_clean_report_is_zero(
        self, redis_cli: fakeredis.FakeServer, redis_settings: Settings
    ) -> None:
        assert main(["report"]) == EXIT_OK

    def test_owner_on_a_non_assign_action_is_usage_error(
        self, redis_cli: fakeredis.FakeServer, redis_settings: Settings
    ) -> None:
        assert main(["delete", "--owner", "internal"]) == EXIT_USAGE

    def test_non_positive_limit_is_usage_error(
        self, redis_cli: fakeredis.FakeServer, redis_settings: Settings
    ) -> None:
        assert main(["report", "--limit", "0"]) == EXIT_USAGE

    def test_negative_age_is_usage_error(
        self, redis_cli: fakeredis.FakeServer, redis_settings: Settings
    ) -> None:
        assert main(["report", "--older-than-days", "-1"]) == EXIT_USAGE

    def test_report_with_yes_still_reports_a_dry_run(
        self,
        redis_cli: fakeredis.FakeServer,
        redis_settings: Settings,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """`report` never writes, so `--yes` must not make the summary
        claim a live mutation happened."""
        seed(redis_cli, [_job("orphan1")])
        assert main(["report", "--store", "jobs", "--yes"]) == EXIT_OK
        out = capsys.readouterr().out
        assert "dry_run=true" in out
        assert owners(redis_cli) == {"orphan1": None}

    def test_unknown_action_exits_two_via_argparse(
        self, redis_settings: Settings
    ) -> None:
        # argparse exits 2 on an invalid choice, matching our usage code.
        with pytest.raises(SystemExit) as exc:
            main(["nonsense"])
        assert exc.value.code == EXIT_USAGE
