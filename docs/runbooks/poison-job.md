# Runbook — poison job

A job that reliably kills the worker that takes it. The redriver
reclaims it, puts it back in flight, the next worker dies on it, and the
loop runs forever — each pass costing a worker and whatever model calls
it made before it died.

ADR 0068 bounded that loop: after `JOB_REDRIVE_MAX_ATTEMPTS` requeues
(default **3**) the redriver **dead-letters** the job instead of
resubmitting it, writing terminal status `failed` with
`error_type="internal_dead_letter"`. The bound is what turns an
unbounded outage into a single alert, and the alert is this page.

**On the shipped defaults this alert cannot fire.**
`JOB_REDRIVE_REQUEUE_PENDING` defaults to `false`, so an orphaned job is
failed rather than resubmitted and there is no loop to bound — only a
deployment that has turned requeueing on can produce a poison job. That
is worth knowing before you spend the first minute of this incident
looking for one: check the setting (§2, command 3) and if it is off, the
alert is telling you something else went wrong.

The distinction that matters and is easy to get backwards: an
`orphaned` job is one whose worker vanished and which is *expected to
work* on resubmission — that is a restart, and the redriver's advice to
resubmit is correct. A **dead-lettered** job has already been
resubmitted three times. Resubmitting it a fourth time is how you spend
a fourth worker.

## 1. The signal

| Signal | Where | What it means |
|---|---|---|
| `research_jobs_total{error_type="internal_dead_letter"}` | metric | The alarm. Any non-zero increase is one poison job that has already taken three workers down. |
| `research_jobs_total{error_type="orphaned"}` | metric | The precursor. A rising orphan rate with no restarts is workers dying, and a poison job is one of the reasons they do. |
| `job_redriver_dead_lettered` | log | Carries `job_id`, `attempt` and `cap` — the identity of the job and the proof the bound fired rather than the sweep giving up. |
| `job_redriver_requeued`, `job_redriver_reclaimed`, `job_redriver_swept` | log | The sweep's own accounting. `job_redriver_swept` reports `orphaned == failed + requeued + dead_lettered`, which is the row to read to see whether one job or many is involved. |
| `api_shutdown` **absent** before a burst of `job_redriver_reclaimed` | log | Workers exited without a clean shutdown. Crash or OOM kill, not a deploy. |

Alert rule: `PoisonJobDeadLettered`.

`kind` on the dead-letter metric reads `"unknown"`, not `research` or
`session` — the redriver has `job.kind` in hand and does not pass it.
That is a known gap (`docs/observability.md` §Known gaps 7), and it
means the alert cannot tell you which workflow the poison job belongs
to. The log line's `job_id` can.

## 2. The first three commands

```bash
# 1. Which job, and how many attempts did it take before the bound fired?
dc logs --since 6h app | jq -c 'select(.message == "job_redriver_dead_lettered") | {job_id, attempt, cap, worker_id}'

# 2. What is the row now, and what was it asked to do?
dc exec redis redis-cli --no-raw GET "job:<job_id>"

# 3. Is requeueing even on, and what is the bound?
dc exec app python -c "from src.config import settings; print(settings.job_redrive_requeue_pending, settings.job_redrive_max_attempts, settings.enable_job_redriver)"
```

Then the diagnosis, once command 1 has given you a `job_id`:

```bash
dc logs --since 6h app | jq -c 'select(.job_id == "<job_id>") | {ts, level, message, error_type}'
```

That last one is the whole story. The `job_id` is on every line the job
emitted, because the runner binds it into the correlation context — so
this is the whole story of the job in one filter, ending at whatever
killed the worker. If the last line is a node span with no terminal
event after it, the worker died *inside* that node, and the node name is
the finding.

## 3. Containment

**The job is already contained.** Dead-lettering is the containment: the
row is terminal, the redriver will not pick it up again, and its
`redriveattempts:` counter has been dropped. Nothing is still burning.

The action is to stop it from coming back, and there are exactly two
ways it can:

**A client resubmits it.** The API cannot distinguish a resubmission
from a new job — there is no dedupe on query text. If the alert repeats
with a different `job_id` and the same shape, that is what is happening,
and the containment is at the principal, not the job: lower
`API_KEY_HOURLY_LIMIT`, or revoke the key
([`pilot.md`](pilot.md) §5 is the procedure).

**The redriver requeues pending jobs.** `JOB_REDRIVE_REQUEUE_PENDING`
is the setting that makes requeueing possible at all, and it is `false`
by default — so if this alert fired, this deployment turned it on. If a
poison job is actively cycling and you have not yet found it, turning it
back off stops the cycle immediately at the cost of leaving orphaned
`pending` jobs for a human to resubmit:

```bash
# in .env: JOB_REDRIVE_REQUEUE_PENDING=false
dc up -d app
```

That is a blunt instrument and it should be reverted once the specific
job is identified. The bound (`JOB_REDRIVE_MAX_ATTEMPTS`) exists so that
this lever is almost never needed.

**If the row itself must go** — a corrupt payload that breaks the
scanner rather than the worker — it is a Redis delete, and it is
irreversible:

```bash
dc exec redis redis-cli DEL "job:<job_id>" "joblease:<job_id>" "redriveattempts:<job_id>"
```

Copy the payload out with command 2 before deleting it. It is the only
evidence of what killed three workers.

## 4. Rollback

A poison job is usually **input**, not a release — one paper that breaks
the PDF parser, one query that produces a state the graph mishandles. So
the first question is whether anything was deployed at all.

If it was, roll back and *then* resubmit the job deliberately, once, and
watch it:

```bash
git checkout --detach <previous-release-commit>
dc up --build -d app
# resubmit by hand, with the payload from command 2, and watch:
dc logs -f app | jq -c 'select(.job_id == "<new_job_id>")'
```

If it was not a release, there is nothing to roll back and the fix is a
code change with a fault-tier test for the input that caused it — which
is what the fault tier is for.

## 5. What this runbook does not cover

- **Why the worker died.** This page finds the job. The traceback is in
  the log under the same `request_id`/`job_id`; an OOM kill leaves
  nothing at all in the app's stream and shows only as `docker inspect`
  exit code 137.
- **A dead-letter queue you can browse.** There is not one. Dead-lettered
  jobs are ordinary terminal rows with a distinctive `error_type`, and
  `scan_jobs` is the only enumeration.
- **Replay.** There is no replay mechanism. Resubmitting means creating a
  new job with the same input, by hand, and it is deliberately manual —
  automatic replay of a job that killed three workers is the loop this
  whole bound exists to break.
