# Everyday local operation

These commands operate only the isolated `arxiv-workspace-live` Compose project.
They do not merge code, enable paid generation or activate recurring collection.
Use the reviewed checkout containing these scripts; the current build worktree
is `/private/tmp/arxiv-agent-eng-workspace-next`.

## Open or start the workspace

If it is already running, open
[Today](http://127.0.0.1:3137/workspace/today). The API uses loopback port
8137 and the isolated Postgres uses loopback port 15438. The fictional preview
at [port 3127](http://127.0.0.1:3127/today) is separate; it does not acquire live
sources or turn its browser notes into durable server records automatically.

To start a stopped workspace, first start Docker Desktop, then run:

```bash
cd /private/tmp/arxiv-agent-eng-workspace-next
bash scripts/workspace-everyday.sh run
```

Leave that terminal open. The launcher starts the isolated storage, applies
versioned migrations, preserves existing preferences, starts the API and builds
and serves the current web checkout. Occupied API/web ports cause a refusal;
use the existing workspace or stop its own foreground terminal before starting
another. Do not stop unrelated processes to free a port.

The launcher uses the existing locked Python at
`/Users/kudratsingh/Machine-Learning-Projects/arxiv-venv-lock/bin/python`.
A different installed compatible interpreter can be supplied explicitly through
`VENV_PYTHON`; never install packages into the shared locked environment.
For implementation work, `dev` selects the local development server instead of
the production web build. No hosting is provisioned by either command.

## Refresh and check health

While storage is running, use the in-app manual refresh, or:

```bash
bash scripts/workspace-everyday.sh refresh
curl -fsS http://127.0.0.1:8137/healthz
bash scripts/workspace-everyday.sh worker-health
```

Refresh performs bounded public metadata checks. Inspect the in-app source
receipts for actual success, failures, missing coverage and Retry-After; HTTP
process health alone does not prove a durable save or successful source check.
A successful empty source check is distinct from an outage.

`worker-health` currently reports `disabled_not_started` when no worker container
runs. The continuous worker service is behind the disabled `worker` Compose
profile, and `WORKSPACE_SCHEDULE_APPROVED=false` is hard-coded in both the
launcher and service. A worker module test or heartbeat is not schedule activation.
For a configuration-only inspection, without starting the worker:

```bash
bash scripts/workspace-everyday.sh worker-config
```

The packaged worker image build and container run have **not yet been verified**.
The Python lifecycle/lease/recovery tests are separate evidence. Do not infer a
running container or production readiness from a successful config printout.

The launcher and configured worker share a Postgres-backed source governor,
including the arXiv request group. If that shared governor is unavailable, the
fetch is refused instead of falling back to an independent limiter. Standalone
library use without the shared-database setting uses a local file governor; that
fallback is not coordination across containers or other computers.

## Stop, sleep and resume

Press **Ctrl+C in the workspace's own launch terminal** to stop the web process
and its API child. Postgres stays running so notes and backup commands remain
available. To stop this project's storage afterward:

```bash
bash scripts/workspace-everyday.sh stop-storage
```

This uses the explicit project/file and does not remove named data volumes.
Never add `--volumes` or use a bare Compose shutdown to tidy this workspace.
The optional worker profile remains off. If it is separately started after a
future reviewed activation, stop that explicit service before storage shutdown:

```bash
docker compose -p arxiv-workspace-live -f compose.workspace.yml --profile worker stop worker
```

A sleeping/offline computer does not fetch sources or deliver alerts. **Today,
with recurrence disabled, resume the app and refresh manually.** After a future
owner-confirmed local schedule is activated, the durable scheduler coalesces
missed queued/expired occurrences into one bounded catch-up rather than sending
a backlog. It does not claim delivery while the computer was asleep. External
email, push, SMS and chat delivery remain disabled.

## Private state locations

`workspace-everyday.sh` defaults its credential/log/backup directory to:

```text
~/Library/Application Support/arxiv-workspace
```

It delegates to `workspace-local.sh`, whose direct-use default is
`<checkout>/outputs/workspace-live`. Both accept `WORKSPACE_DATA_DIR`; use the
same value across launch, backup and health-related operator commands. Paths
with spaces are supported. The operator principal defaults to `personal-local`;
changing `WORKSPACE_OWNER` selects a different private namespace, not a rename.

Postgres records live in the named Docker volume for the isolated project,
independently of those directories. Moving the credential/backup directory does
not move the database. The `.api-key` stays private; the browser receives no
provider key. Raw qualification PDFs/renders under
`outputs/workspace-next/fulltext/` are separate local artifacts, while retained
text and provenance are database records. Do not commit private files or backups.

## Backup and verify a restore

With the isolated Postgres service running:

```bash
bash scripts/workspace-everyday.sh backup
```

The command prints a private `.dump` path and its `.sha256` sidecar under the
selected data directory's `backups/`. Incomplete dumps remain private partial
files with an explicit failure; they are not announced as successful backups.
Keep the dump and sidecar together. New sidecars use a basename-relative entry.
The restore checker also safely accepts an older absolute-path sidecar by
checking the digest against the **exact supplied dump bytes**, rather than
trusting the filename embedded in that sidecar.

Pass the exact backup path printed above, quoted for spaces:

```bash
bash scripts/workspace-everyday.sh restore-check "/absolute/path/to/workspace-backup.dump"
```

This checks the checksum first, creates a **new disposable database**, runs
`pg_restore --exit-on-error`, reports restored work/note counts, and removes only
that disposable database afterward. It never overwrites the original workspace.
The command tests restoration; switching the live app to a restored database is
a separate recovery action. The basic command does not assert row-by-row equality
of every table. Use only the workspace's own trusted backup files.

Isolated backup/restore verification, including paths containing spaces, has
succeeded. Operator regression tests separately use a fake Docker executable to
check relocated backups, exact-file checksum refusal, malformed sidecars and
failed-dump handling; those shell tests do not replace the real restore result.

A database dump preserves database notes/preferences/material/provenance. It does
not back up the checkout, `.api-key`, logs or raw PDF/render files. Preserve those
separately through the owner's private backup process when a full recovery bundle
is required. A Markdown notes export is useful for reading elsewhere, but is not
a database backup.
