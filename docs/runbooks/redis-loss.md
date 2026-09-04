# Runbook — Redis loss

Redis holds the job rows, the SSE event streams, the worker leases and
the per-principal rate-limit counters. It is the only backend whose loss
breaks the **write** path: with Redis gone, `POST /research` cannot
create a job at all, so the request never becomes work and — before
WO-A07 — moved no instrument whatsoever. A fleet whose Redis had died
read as idle rather than as failing. Closing that is why this page has a
metric signal to name.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `rate_limit_rejections_total{backend="memory"}` | metric | **The sharpest one.** Under `RATE_LIMIT_BACKEND=redis` a 429 attributed to the `memory` backend can only mean the Redis limiter raised and the fail-open fallback answered. The per-principal hourly cap has silently become per-*worker*: N workers now allow N × `api_key_hourly_limit`. |
| `http.server.request.duration` count on `http.route="/research"` with a `5xx` status | metric | Submits are failing. Redis is the first suspect; the log names the actual dependency. |
| `research_jobs_total{error_type="orphaned"}` | metric | Leases expired while Redis was away and the redriver reclaimed the rows on recovery. Expect a burst *after* the outage, not during it. |
| `resilience_degraded` with `component="rate_limiter"`, `reason="redis_unavailable"` | log | The degradation itself, at the moment it happens — hours before anybody is actually rejected. |
| `api_health_dependency_degraded` with `dependency="redis"` | log | The discriminator. One WARNING on the edge, one INFO (`api_health_dependency_recovered`) when it comes back; never the steady state, so a weekend outage does not bury the timeline in 17k identical lines. |
| `sse_publish_failed`, `sse_terminal_publish_gave_up` | log | A job finished and its client was never told. |

Alert rules: `RateLimiterFellBackToMemory`, `SubmitPathFailing`,
`SubmitLatencyP95High`.

## 2. The first three commands

```bash
# 1. Which dependency, in this deployment's own words.
dc exec app curl -fsS http://localhost:8000/healthz | jq '{status, dependencies, active_jobs, max_concurrent_jobs}'

# 2. Is the container up, and is Redis answering at all?
dc ps redis && dc exec redis redis-cli ping

# 3. What did the app see, and when did it start?
dc logs --since 1h app | jq -c 'select(.message | test("^(api_health_dependency|resilience_degraded)"))'
```

Command 1 is the one that ends the guessing. `/healthz` is **always
200** — it answers "is this process alive", and restarting a worker does
not fix a dead Redis — so the answer is in the body's `dependencies`
map, never in the status code.

## 3. Containment

**If Redis is up but the app cannot reach it**, it is configuration or
the network, and a restart of `app` is cheap and correct:

```bash
dc restart app
```

**If Redis is down**, bring it back before anything else. The volume is
named and survives `down`/`up`; `--appendonly yes` means the job rows
survive a container restart.

```bash
dc up -d redis
dc exec redis redis-cli ping         # PONG
dc exec redis redis-cli dbsize       # non-zero if the AOF replayed
```

**If Redis is down and will stay down**, the deployment can serve reads
and nothing else. There is no in-memory failover worth reaching for:
`JOB_STORE=memory` is per-worker and dies with the process, so
switching to it under multi-worker uvicorn produces a fleet where
`GET /research/{job_id}` 404s about half the time. Stop the app instead.

```bash
dc stop app
```

**The one thing to do while it is down**: nothing is enforcing the
per-principal hourly limit correctly. If auth is on and the deployment
is a pilot, the fail-open fallback is deliberate (a defence that becomes
the outage is worse than a defence that over-serves) — but it is a
weaker guarantee than the configuration claims, and if that matters more
than availability, `dc stop app` is the only way to reassert it.

## 4. Rollback

Redis loss is rarely a deploy, but two changes cause it and both roll
back the same way:

- `REDIS_URL`, `REDIS_CONNECT_TIMEOUT_SEC`, `REDIS_SOCKET_TIMEOUT_SEC`
  or `REDIS_MAX_RETRIES` changed in `.env` → restore the previous values
  and `dc up -d app`. `.env` is not in Git, so the previous values are
  wherever you keep them; this is the argument for keeping them.
- A release changed the store → deploy the previous SHA:

```bash
git checkout --detach <previous-release-commit>
dc up --build -d
```

**Never `dc down -v`.** It deletes the Redis volume, which is every job
row and every event stream on the box.

After recovery, expect and do not panic about:

- a burst of `research_jobs_total{error_type="orphaned"}` and
  `job_redriver_reclaimed` lines — the redriver reconciling rows whose
  worker vanished. That is the mechanism working.
- `rate_limit_rejections_total{backend="memory"}` continuing for up to
  one window; the fallback limiter holds its own counts.

## 5. What this runbook does not cover

- **Which key holds what.** `job:{job_id}`, `joblease:{job_id}`,
  `redriveattempts:{job_id}`, `redrive:lock`. Reading them is
  [`poison-job.md`](poison-job.md)'s business, not this page's.
- **Redis as a cache.** It is not one here. Everything in it is state,
  and `FLUSHALL` is data loss, not a remedy.
- **A Redis that is up and wrong** — resharded, out of memory, evicting
  keys under a `maxmemory-policy` that is not `noeviction`. The shipped
  compose stack sets no eviction policy, so this cannot happen on it;
  on a managed Redis it can, and it presents as jobs that vanish rather
  than as an outage.
