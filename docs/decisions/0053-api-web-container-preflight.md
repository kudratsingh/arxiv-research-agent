# 0053. Make the shipped demo path survive its own first run

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: maintainer

## Context

Everything here was found by walking the path a first-time operator
actually takes — `docker compose up`, open the web UI, type a query —
rather than by reading a module in isolation. That path was broken at
five points, and every one of them was invisible to the test suite
because no test drove the *sequence*.

**The landing page burned a billed job.** `web/app/page.tsx` created a
conversation, `POST`ed `/research`, threw the returned `job_id` away,
and pushed `/c/{conversation_id}`. Nothing downstream could recover
the id: `ConversationThread` reads `useParams` only, and the job never
appears in `GET /conversations/{id}` either — the runner appends a job
to its conversation on the success path alone
(`src/api/runner.py`, `_append_to_conversation`). With
`enable_hitl=True` by default and the UI never sending `hitl_bypass`,
the run parked in `pending_review`, published `plan_ready` to a
channel nobody was subscribed to, and died 30 minutes later on
`api_hitl_timeout_sec`. The user paid for a planner call and watched
an empty page. README even claimed the page "renders a `PlanReview`
panel when this state is reached" — it could not.

**`plan_ready` was never replayed on attach.** The frame is published
exactly once, when the runner parks the job. Neither transport keeps a
backlog: Redis pub/sub drops messages with no live subscriber (ADR
0035) and the in-memory queue is single-consumer. So *any* client that
attached after the pause — the browser's own EventSource retry after a
wifi blip, a reconnect after `api_sse_max_duration_sec` closed the
stream, a second tab — saw nothing but heartbeats until the HITL
timeout failed the job. The stream route already had exactly the right
idiom one status later: terminal jobs replay one frame and close.

**The container was not running the tested dependency set.** ADR 0045
locked the dependency graph and pointed CI at
`requirements-lock.txt`, but the Dockerfile still ran `pip install .`,
which re-resolves pyproject's ranges at build time. The caps are `<
next major`, so every untested minor of langgraph, anthropic and redis
was in scope for the image — and `/healthz` would report `ok` straight
through such a break, because it probes Redis and Postgres, not
imports.

**The first live job downloaded its own model.** `MODEL_NAME =
"sentence-transformers/all-MiniLM-L6-v2"` is lazy-loaded on first
encode (`src/tools/embeddings.py`). In a fresh container that is a
~90MB download from HuggingFace, inside the job's own
`api_job_timeout_sec` budget, on the search node's critical path —
while `/healthz` says `ok`, because a missing model file is not a
dependency this endpoint knows about. Compose mounts no HF cache
volume, so every `docker compose down && up` paid it again.

**A fast container restart stranded a job forever.** ADR 0038's
redriver sweeps once, at startup. That misses the failure leases exist
for: a container SIGKILLed (OOM, `docker compose kill`, a grace-period
overrun) and restarted by `restart: unless-stopped` *within*
`job_lease_ttl_sec` comes back to find its own dead lease still live
in Redis. The boot sweep correctly declines to touch the job — from
the outside a live lease is indistinguishable from a healthy peer
mid-run — and then no later sweep ever happens. The row stays
`running` forever, with `GET /research/{id}` and the SSE stream both
waiting on a terminal frame nobody will publish. PR #59 added
`job_redrive_interval_sec` for exactly this and left it unread.

**`/healthz` reported a degraded dependency and logged nothing.** ADR
0042 made the endpoint honest in its *body*; the log stream stayed
silent, so an outage left no trace in the place an operator greps
after the fact.

## Decision

Six fixes, one lane, because they are one user journey.

### 1. Carry the job id to the run page; adopt, never resubmit

The landing page keeps its submit — it is the page with the form —
and pushes `/c/{conversation_id}?job={job_id}`. The run page reads
`?job=` (inside a `Suspense` boundary, as `useSearchParams` requires)
and passes it to `ConversationThread` as `adoptJobId`. The thread
attaches to that job through a new `useResearchStream.attach(jobId)`,
which is `submit` minus the POST: same stream reader, same frame
handling, no second billed job.

`attach` returns early when the hook is already streaming that id.
The guard is the live `EventSource`, not a "have attached" flag, so
React StrictMode's mount → cleanup → mount still ends with exactly one
open stream rather than none. The thread also `router.replace`s the
URL whenever it starts a job of its own, so the invariant holds for
follow-up turns too: **the URL always names the job in flight**, and
reloading re-attaches to it.

Handing the id over in the URL rather than in router state or
`sessionStorage` is the whole point: a reload, a restored tab and a
pasted link all rejoin the same job.

### 2. Replay `plan_ready` on attach

In the stream route's attach path, a job whose status is
`pending_review` *and* whose `plan` is populated yields one
`plan_ready` frame before subscribing. The payload is built by
`_plan_ready_data` to be byte-identical to the runner's
(`{job_id, plan: {sub_questions, search_queries}}`), so a client
handles one shape for one event name.

Both halves of the condition matter. `pending_review` without a plan
is a torn write, and replaying an empty plan would invite a reviewer
to approve nothing; a plan on a `running` job belongs to a review that
was already resolved, and replaying it would re-open a settled
decision.

On the in-memory transport the plan can legitimately arrive twice
(this snapshot, then the queued frame, if no earlier client consumed
it). That is deliberate — the frame carries the whole plan, so
applying it twice is idempotent, and suppressing the replay to avoid
the duplicate would reopen the silence this closes.

### 3. Install the lock in the image

`COPY pyproject.toml README.md requirements-lock.txt ./`, then
`pip install -r requirements-lock.txt`, then — after `COPY src` —
`pip install --no-deps .`. pip performs no resolution for the app's
dependencies at all, so the image runs the set CI tested. The
manifest-first ordering keeps the expensive layer cached against
source edits.

### 4. Bake the model into the image

`HF_HOME=/opt/hf-cache` in *both* stages; the builder runs a tiny
script that reads `MODEL_NAME` out of `src/tools/embeddings.py` and
constructs a `SentenceTransformer`, and the runtime stage copies the
populated cache with `--chown=app:app` (huggingface_hub writes lock
files into the cache root even on a pure read, and a read-only cache
falls back to the network). The bake step copies `embeddings.py`
alone, before `COPY src`, so an edit elsewhere does not re-download
the weights.

The model id is *read*, never repeated: a second literal in the
Dockerfile would drift from the runtime's, and drift's only symptom is
a slow first job. `tests/test_container_contract.py` pins that
coupling — the regex, the shared `HF_HOME`, the lock install, and the
absence of a compose volume over the cache path — without building.

Explicitly out of scope: readiness logic. `/healthz` stays a liveness
+ dependency probe.

### 5. Sweep on an interval, not only at boot

`_redrive_forever(redriver, settings.job_redrive_interval_sec)` runs
as a lifespan-owned task, guarded by `enable_job_redriver` *and* by
the store advertising `scan_jobs` (under `InMemoryJobStore` nothing
survives a restart, so a recurring sweep would burn a task to log
`job_redriver_store_unsupported` forever). It waits a jittered
fraction of one interval before its first full interval —
`REDRIVE_JITTER_RATIO = 0.25` — because a fleet started by one
`docker compose up` boots in lockstep and an unjittered timer would
put every worker's sweep on the same second.

Each sweep is bounded by `REDRIVE_LOCK_TTL_SEC`, mirroring the startup
sweep; failures and timeouts log and continue, because reconciliation
is housekeeping and must not take a serving worker down. Cross-worker
serialization needs nothing new: every sweep takes the redrive lock,
so one worker reclaims per tick and the rest no-op. The task is
cancelled at shutdown *before* in-flight jobs are cancelled, so it
cannot publish a second terminal frame for a job the runner is about
to mark `cancelled`.

### 6. Log health *edges*

`/healthz` logs one WARNING when a dependency goes bad and one INFO
when it recovers, naming the dependency. Not one line per probe: the
compose healthcheck polls every 15s, so a weekend outage would bury
the timeline in ~17k identical lines. Only the exception *type* is
carried, matching what the probe helpers already return — ADR 0042
drops the message because a connection error's text tends to contain
the URL, and `redis_url` / `postgres_url` carry credentials inline.

The latch set lives on `app.state`, not in a module global, so two
apps in one process do not swallow each other's edges. It is reached
through its own accessor rather than through `_get_state`: that helper
reads every key eagerly for every route, so a new required attribute
there breaks any caller holding a partial app state — including the
hand-built stubs in the stream tests. The accessor creates the set on
first use, so `/healthz` also works on an app assembled without our
lifespan.

## Alternatives considered

- **Stop submitting on `/` and let the thread submit on mount** —
  the audit's own suggestion. Moves the POST rather than removing the
  handoff problem: the thread still has to decide, on every mount,
  whether the query in the URL is a fresh instruction or one it
  already ran, and a reload of `?q=...` resubmits. Carrying the
  *job id* makes the reload case correct by construction.
- **Extend `GET /conversations/{id}` to list in-flight jobs** — a
  real fix for adoption after a lost URL, and worth doing eventually.
  It is an API change plus a store-level index of non-terminal jobs
  per conversation, which is a larger and riskier change than the
  P0 warranted. Recorded as a follow-up.
- **Suppress the duplicate `plan_ready` on the in-memory path** —
  requires the route to know whether the queued frame was consumed,
  which the queue does not expose. Costs a real reconnect fix to save
  a client an idempotent state write.
- **Mount an HF cache volume in compose instead of baking** — keeps
  the image small, but the first run after every `down -v`, on every
  fresh host and in every CI job still pays the download, and a
  volume mounted over `/opt/hf-cache` would *shadow* the baked
  weights. A test asserts compose does not do that.
- **Download the model in an entrypoint script at container start** —
  moves the cost out of the job's timeout budget but into the startup
  path, where it delays readiness on every restart and needs network
  at boot. Bake-time is paid once, by the builder.
- **A readiness endpoint that fails until the model is warm** —
  correct in the abstract and explicitly out of scope here; it needs
  a warmup path and a probe contract, and this ADR is about removing
  the download, not describing it.
- **APScheduler / a cron sidecar for the periodic sweep** — a
  dependency and a second process to reason about, for a loop that is
  a `while True` with one `sleep`.
- **Log every `/healthz` probe at DEBUG** — invisible at the shipped
  `LOG_LEVEL=INFO`, so the outage still leaves no trace where anyone
  looks.

## Consequences

- **Positive**: the demo path works end to end. One query bills one
  job; a reload rejoins it; a reconnect during review sees the plan;
  a restarted container reclaims its own stranded job within an
  interval; the image runs the tested dependency set with the model
  already on disk; a dependency outage is greppable.
- **Negative — image size**: the baked weights add 88MB to the
  runtime image, and installing the whole lock brings the dev tooling
  (pytest, mypy, ruff) along with it, because the lock is a
  whole-venv freeze. Both are deliberate: exact parity with the
  tested set beats a smaller image, and the alternative to baking is
  paying the same 88MB on the critical path of the first real job.
  Splitting the lock into runtime and dev halves is the recorded
  follow-up and would take the tooling back out.

  Measured on the first real build of this Dockerfile (linux/arm64):
  **5.88GB total** — `/opt/venv` 5.4GB, the baked cache 88MB, the
  app 2.7MB. The weights are 1.5% of the image. The actual weight is
  torch: `site-packages/nvidia/*` is 2.9GB and `torch` itself 927MB,
  because the lock was frozen on macOS (ADR 0045's recorded limit) and
  so pins no platform wheels — pip resolves torch's Linux extras at
  install time and picks the CUDA build for a service that runs the
  model on CPU (`embedding_device` defaults to `"cpu"`). That is
  pre-existing, not caused by this change: `pip install .` resolved
  the same graph. But it is now measured, so it is a recorded
  follow-up rather than folklore: pinning the CPU-only torch build
  takes ~3GB out of the image.
- **Negative — build time**: the bake adds a download to the build.
  It sits in its own layer keyed on `src/tools/embeddings.py`, so it
  is paid on a model change, not on a source change.
- **Negative — one more always-on task per worker**: the periodic
  sweep wakes every `job_redrive_interval_sec` (default 300s) and, in
  the steady state, takes the redrive lock, scans, finds nothing, and
  logs nothing. Cost is one Redis round trip per worker per interval.
- **Negative — the `?job=` parameter is now load-bearing**: a link
  shared without it opens the thread without attaching, and the
  running job is invisible until it completes. That is the gap the
  conversation-level in-flight listing would close.
- **Follow-ups**:
  - Pin the CPU-only torch build for the image so pip stops resolving
    the CUDA extras — 2.9GB of `nvidia/*` wheels in a service whose
    `embedding_device` defaults to `"cpu"`.
  - Split `requirements-lock.txt` into runtime and dev sets so the
    image stops shipping test tooling.
  - List in-flight jobs on `GET /conversations/{id}` so a thread can
    adopt without the URL.
  - Send `X-API-Key` from the web UI so the demo works with
    `ENABLE_API_AUTH=true` (still open from ADR 0042).
  - A readiness probe distinct from `/healthz`, if a future
    deployment needs one.
