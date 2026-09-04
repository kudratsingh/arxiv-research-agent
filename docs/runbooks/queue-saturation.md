# Runbook — queue saturation

Every concurrency permit on a worker is held, so an accepted job sits in
`pending` behind `API_MAX_CONCURRENT_JOBS` instead of starting. Jobs are
minutes long here, so this is not the transient burst it would be on a
request-serving system: a saturated worker stays saturated, and the
queue in front of it grows at whatever rate submissions arrive.

The baseline finding this page exists for: **saturation used to be
visible only after the ceiling was hit.** There was no wait time, no
depth, no utilisation — only jobs that had started and jobs that had
not. The three instruments below are the USE triple that closed it.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `research_job_queue_wait_seconds` | metric | The **U**SE wait: seconds between acceptance and start. Rises first, because a queue that drains slowly still drains. This is the signal to act on. |
| `research_queue_saturation_ratio` | metric | Owned jobs ÷ `api_max_concurrent_jobs`, per worker. `1.0` means every permit is held; above `1.0` means work is queueing behind it. |
| `research_queue_depth` | metric | `active_jobs − ceiling`, floored at zero. An **upper bound**: abandoned node threads are counted as though they still held a permit, so it errs toward "more contended than it is" — the useful direction. |
| `research_active_jobs` | metric | Queued + running + abandoned node threads, per worker. The same figure `/healthz` reports. |
| `research_abandoned_node_threads` | metric | Threads whose drain budget expired and that the worker no longer waits for (ADR 0047). **They never come back.** They hold pool slots and can still spend, so a worker that accumulates them loses capacity and gains cost at the same time. |
| `http.server.active_requests` | metric | In-flight HTTP requests. An SSE stream correctly holds this up for a whole job, so a high value here alongside a low `research_active_jobs` is watchers, not work. |
| `api_job_node_drain_expired`, `api_node_executor_drain_timeout` | log | A node thread was abandoned. One of these per increment of the gauge above. |

Alert rules: `QueueWaitP95High`, `QueueSaturated`, `AbandonedNodeThreads`.

**`/readyz` already knows.** It returns 503 when
`active_jobs >= max_concurrent_jobs`, precisely so a load balancer sends
the next request to a worker that can start it now. **Nothing in the
shipped compose stack polls it** — the healthcheck polls `/healthz`,
which is always 200 by design — so on that deployment the alert rule is
the only thing that will tell you.

## 2. The first three commands

```bash
# 1. How full is each worker, and how much of it is real work?
dc exec app curl -fsS http://localhost:8000/healthz | jq '{active_jobs, abandoned_node_threads, max_concurrent_jobs}'

# 2. Is the readiness endpoint already shedding? 503 here is the answer.
dc exec app curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/readyz

# 3. Are jobs finishing, or are they stuck?
dc logs --since 30m app | jq -c 'select(.message | test("^(api_job_submitted|run_completed|api_job_timeout|api_job_node_drain_expired)$")) | {message, job_id, elapsed_sec}' | tail -30
```

Command 1 splits the two causes immediately. If `abandoned_node_threads`
is a large share of `active_jobs`, the worker is not busy — it is
**leaking**, and no amount of waiting recovers those permits. If it is
zero, the worker is genuinely full and this is a capacity question.

## 3. Containment

**Leaked permits (`abandoned_node_threads > 0`).** The only containment
is a restart of that worker. Nothing reclaims an abandoned thread.

```bash
dc restart app
```

In-flight jobs drain and any that do not become reclaimable when their
leases expire; the redriver picks them up. Expect a burst of
`research_jobs_total{error_type="orphaned"}` afterwards — that is the
mechanism, not a second incident.

**Genuinely full.** Two levers, and only one of them is free.

*Raise the ceiling.* `API_MAX_CONCURRENT_JOBS` is per worker, and each
permit is a job that will make model calls — so raising it raises the
worst-case spend rate proportionally, and it is bounded in practice by
the node thread pool and by memory, not by the setting. Raise it in
small steps and watch `research_job_duration_seconds`: if p95 job
duration rises as you raise concurrency, the box is the constraint and
the extra permits are buying queueing rather than throughput.

```bash
# in .env: API_MAX_CONCURRENT_JOBS
dc up -d app
```

*Shed instead.* Lower `API_KEY_HOURLY_LIMIT` so submissions are refused
at the edge with a 429 and a `Retry-After` rather than accepted into a
queue nobody can see. An honest refusal is the last rung of the
degradation ladder and it is a better answer than a job that sits in
`pending` for twenty minutes and then times out having done nothing.

**Do not** raise `API_JOB_TIMEOUT_SEC` to make queued jobs stop timing
out. The timeout is wall clock from start, not from submission, so it is
not what is killing them — and raising it makes each stuck permit held
for longer, which is the opposite of the fix.

## 4. Rollback

If saturation began at a deploy, the suspect is anything that made a job
slower rather than anything that made the queue longer: a model change,
`READER_MAX_CHUNKS_PER_PAPER`, `MAX_ITERATIONS`, a new node.

```bash
git checkout --detach <previous-release-commit>
dc up --build -d app
dc exec app curl -fsS http://localhost:8000/healthz | jq '{active_jobs, max_concurrent_jobs}'
```

If it began at a config change, restore `API_MAX_CONCURRENT_JOBS` and
`API_KEY_HOURLY_LIMIT` to their previous values together — they are two
halves of one decision about how much work this deployment accepts.

## 5. What this runbook does not cover

- **A fleet-wide queue.** Every gauge here is **per worker** and the
  metrics carry no worker identity — the process is what emits them, so
  a fleet's view is the sum across scrape targets. There is no
  cross-worker queue depth, because there is no cross-worker queue:
  each worker owns its own permits.
- **Horizontal scaling.** Adding workers is the real answer to genuine
  saturation and it is a deployment decision with a cost, not an
  incident action. `deploy/hetzner/` is one box.
- **Why a specific job is slow.** That is a trace, not a gauge: one job
  is one trace (`docs/observability.md` §Traces), and the node spans
  under it say where the time went.
