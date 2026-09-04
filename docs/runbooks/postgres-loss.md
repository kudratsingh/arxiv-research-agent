# Runbook — Postgres loss

Postgres holds six things, and they fail differently:

| What | Setting | Loss means |
|---|---|---|
| LangGraph checkpoints | `CHECKPOINT_BACKEND=postgres` | **Running jobs die.** A graph that cannot checkpoint cannot advance, and a HITL job paused at its breakpoint cannot be resumed by any worker. |
| Conversations | `CONVERSATION_STORE=postgres` | `/conversations` 5xx; prior-report context is lost, so a follow-up question runs as a cold query. |
| Learner profiles | `LEARNER_PROFILE_STORE=postgres` | Guided sessions lose the learner's history mid-pilot. |
| Progress events | the `progress_events` table | The engagement measurement the pilot exists to produce stops being recorded. |
| Paper cache | `PAPER_CACHE=postgres` | Slower and **more expensive** — every paper is re-fetched and re-parsed. Not an outage. |
| Embedding cache | `EMBEDDING_CACHE=postgres` | Slower. Not an outage. |

The first four are an incident. The last two are a cost event that looks
like a latency regression, which is why they are on this page at all:
`SpendRateHigh` firing with Postgres degraded is usually cache misses,
not a runaway agent.

Redis, not Postgres, is what breaks `POST /research` — see
[`redis-loss.md`](redis-loss.md) if submits are failing.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `api_health_dependency_degraded` with `dependency="postgres"` | log | The probe (`SELECT 1` through the shared pool, 2s bound) failed. One WARNING on the edge only. |
| `research_jobs_total{error_type="orphaned"}` | metric | Workers dying mid-run and the redriver reclaiming their rows. A checkpointer that cannot write is one way that happens. |
| `research_jobs_total{error_type="internal_unexpected"}` | metric | The catch-all. A database error inside a node lands here, because ADR 0064 refuses to put driver text on the wire — psycopg messages embed the host, port and user. |
| `api_job_terminal_persist_failed`, `api_job_terminal_persist_retry` | log | The job finished and the terminal write did not land. The work succeeded; only the record of it is missing. |
| `conversation_append_failed`, `api_prior_context_failed` | log | Conversation writes and reads failing. |
| `paper_cache_get_failed`, `paper_cache_put_failed`, `embedding_cache_get_failed`, `embedding_cache_put_failed` | log | Cache degradation. Jobs still succeed; they cost more. |
| `postgres_pool_opened`, `postgres_schema_initialized` | log | Present at startup. Their **absence** after a restart is how you tell a boot failure from a mid-life failure. |

Alert rules: `JobsOrphanedByDeadWorkers`, and `TerminalStateOrStreamLost`
in [`log-alerts.yml`](../../deploy/observability/log-alerts.yml).

## 2. The first three commands

```bash
# 1. Which dependency, in this deployment's own words. Postgres appears
#    in `dependencies` only when POSTGRES_URL is configured.
dc exec app curl -fsS http://localhost:8000/healthz | jq '{status, dependencies}'

# 2. Is the server up and accepting connections?
dc ps postgres && dc exec postgres pg_isready

# 3. Is it out of disk? This is the single most common cause and the
#    one a restart makes worse.
dc exec postgres df -h /var/lib/postgresql/data
```

Command 3 is third because it is the answer often enough to be worth
asking before anything is restarted. A full data volume produces a
Postgres that starts, accepts connections and fails every write.

## 3. Containment

**Out of disk.** Do not restart. Reclaim first — the caches are the only
tables that are safe to shrink, and they are *caches*: deleting them
costs money on the next run and nothing else.

```bash
dc exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "\dt+" -c "SELECT pg_size_pretty(pg_database_size(current_database()));"
```

Truncate a cache table only after confirming its size is the problem,
and never truncate `conversations`, `learner_profiles`, `progress_events`
or the LangGraph checkpoint tables — those are user data and job state,
and there is no undo. If the checkpoint tables are what is large, the
right fix is a retention job that does not exist yet, not a truncate
during an incident.

**Server down, disk fine.**

```bash
dc up -d postgres
dc exec postgres pg_isready
dc restart app        # re-opens the pool; `postgres_pool_opened` proves it
```

**Server down and staying down.** The deployment can still serve
research jobs if — and only if — you accept losing what the first four
rows of the table above hold. Do not do this quietly:
`CHECKPOINT_BACKEND=sqlite` is per-worker and single-writer, so under
multi-worker uvicorn a HITL job resumed on a different worker cannot
find its checkpoint. That is a worse failure than being down, because it
is intermittent. Stop the app instead:

```bash
dc stop app
```

## 4. Rollback

If a release or a migration preceded the incident, the rollback is
ordered and the order matters: **schema first, code second**, because
this repository has no down-migrations.

```bash
# 1. Confirm what the running image thinks the schema should be.
dc logs --since 1h app | jq -c 'select(.message | startswith("admin_migrate"))'

# 2. Deploy the previous SHA.
git checkout --detach <previous-release-commit>
dc up --build -d

# 3. Prove the pool opened and the probe passes.
dc logs --since 5m app | jq -c 'select(.message == "postgres_pool_opened")'
dc exec app curl -fsS http://localhost:8000/healthz | jq .dependencies
```

If step 1 shows a migration ran, the previous image may not tolerate the
new schema. Restore from the logical dump
(`deploy/hetzner/README.md` §Data protection) rather than guessing —
and if there is no dump, that is the finding of this incident.

**Never `dc down -v`.** It deletes the Postgres volume.

## 5. What this runbook does not cover

- **Backups.** The named volume is persistence, not a backup. Taking
  and testing a logical dump is a standing task, not an incident action,
  and this page assumes one exists.
- **Connection-pool exhaustion.** It presents as slow, not down, and the
  `/healthz` probe would pass while every job stalls. There is no
  instrument for pool waiters today; it is recorded as a gap in
  [`../reliability.md`](../reliability.md) §7.
- **Data loss triage.** What a lost checkpoint means for one specific
  paused HITL job is a per-job question; `GET /research/{job_id}` is
  still the answer to it.
