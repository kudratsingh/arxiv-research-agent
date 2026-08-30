#!/usr/bin/env bash
#
# Record the contract fixtures in `web/contract/` from a seeded local stack.
#
# ============================================================================
# THIS SCRIPT IS RUN BY HAND. IT NEVER RUNS IN CI, AND IT NEVER CALLS
# `POST /research`.
# ============================================================================
#
# Why by hand: it needs Docker, a Postgres, a Redis, and ~2 minutes of wall
# clock (one scenario deliberately holds an SSE connection open past the
# server's stream deadline). CI consumes the *recorded bytes* instead — see
# the four drift checks in 04-ARCHITECTURE.md §3.5, none of which needs a
# running API.
#
# Why never `POST /research`: that endpoint is non-idempotent and potentially
# billable, and the API has no idempotency key (`src/api/routes.py:179-197`).
# MUST-KEEP #3 / R-01. Nothing below submits a research job; the job rows come
# from `docs/revamp/baseline/fixtures/seed-local-baseline.sh`, which writes
# `baseline-*` records straight into Redis and Postgres.
#
# Why the dummy key: the stack must never receive a real Anthropic key. The
# script exports `ANTHROPIC_API_KEY=local-preview-disabled` itself and refuses
# to start if the caller's environment holds a different value, so a real key
# in a shell profile cannot leak into `docker compose`. This mirrors the Gate 1
# baseline (`docs/revamp/baseline/README.md`, "Test data and safety").
#
#   bash web/contract/record.sh              # everything
#   bash web/contract/record.sh http sse     # only those phases
#
# Phases: http sse ratelimited unauthorized learn proxy learner
#
# ---------------------------------------------------------------------------
# Reproducibility (R-10)
# ---------------------------------------------------------------------------
# A reviewer re-running this against the seeded stack gets byte-identical
# `status` / `headers` / `body` and byte-identical SSE frames. Two header
# fields are expected to move: `x-recording.commit` (whatever HEAD is at
# recording time) and, in `error.429.json`, `headers.retry-after`, which is
# the seconds remaining in the sliding rate-limit window and can differ by a
# second or two.
#
# ---------------------------------------------------------------------------
# What is recorded, and through what
# ---------------------------------------------------------------------------
# Every HTTP fixture is recorded through the Next.js `/api` proxy, because
# that — not FastAPI's port — is the surface `web/lib/api/client.ts` calls
# (`API_BASE = "/api"`). The stored `headers` are filtered to the proxy's own
# response allowlist (`web/app/api/[...path]/route.ts`), which is exactly the
# header set a browser sees; volatile transport headers (Date, Connection,
# Transfer-Encoding, ...) are dropped so the fixture is byte-stable.
#
# Each fixture carries an `x-recording` header block as its first key — the
# same trick `web/contract/openapi.json` uses, since JSON has no comments. It
# names the commit, the request, the transport, and whether anything in the
# file was authored rather than recorded.
#
# SSE scripts are JSON Lines. Line 1 is a `{"type":"header"}` record; every
# other line is `{"type":"event"|"comment"|"directive"}`. `web/tests/support/`
# (WO-05) drives `FakeEventSource` from these.

set -euo pipefail

DUMMY_KEY="local-preview-disabled"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIXTURE_DIR="$ROOT/web/contract/fixtures"
SSE_DIR="$ROOT/web/contract/sse"
SEED_SCRIPT="$ROOT/docs/revamp/baseline/fixtures/seed-local-baseline.sh"

APP_CONTAINER="arxiv-research-agent-app"
REDIS_CONTAINER="arxiv-research-agent-redis"
# Deliberately not compose's 8000/3000 defaults: a recording run should not
# fight whatever a developer already has bound there, and nothing in the
# fixtures depends on the number. Override either to move them.
APP_PORT="${APP_PORT:-8099}"
WEB_PORT="${WEB_PORT:-3099}"
PROXY="http://127.0.0.1:${WEB_PORT}/api"

# Rate-limit phase only. A local-only fixture credential for a disposable
# container; it authenticates nothing outside this script.
RECORD_API_KEY_ID="web"
RECORD_API_KEY_SECRET="record-fixture-key"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# Guards.
# ---------------------------------------------------------------------------

if [ -n "${CI:-}" ]; then
  echo "record.sh does not run in CI. CI consumes the committed fixtures." >&2
  exit 2
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ] && [ "${ANTHROPIC_API_KEY}" != "$DUMMY_KEY" ]; then
  echo "refusing to run: ANTHROPIC_API_KEY is set to something other than" >&2
  echo "'${DUMMY_KEY}'. The recording stack must never receive a real key." >&2
  exit 2
fi

# Set here rather than trusted from the environment: compose interpolates
# this into the app service, and this is the one place it is decided.
export ANTHROPIC_API_KEY="$DUMMY_KEY"
export APP_PORT WEB_PORT

COMMIT="$(git -C "$ROOT" rev-parse HEAD)"

PHASES="$*"
if [ -z "$PHASES" ]; then
  PHASES="http sse ratelimited unauthorized learn proxy learner"
fi

phase_requested() {
  case " $PHASES " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

log() { printf '\n=== %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Stack control.
# ---------------------------------------------------------------------------

compose() { (cd "$ROOT" && docker compose "$@"); }

# Bring the stack up with whatever auth/limit variables the current phase has
# exported. Compose recreates a container whose resolved environment changed,
# which is how the auth-on and auth-off phases share one compose file.
stack_up() {
  compose up -d --wait app redis postgres web
}

# Back to the default posture the recording phases assume: auth off, no
# limits, no key anywhere.
stack_reset() {
  unset ENABLE_API_AUTH API_KEYS API_KEY_HOURLY_LIMIT RATE_LIMIT_BACKEND WEB_API_KEY
  stack_up
}

seed() {
  # The Postgres schema is created on first use (`src/tools/postgres_pool.py`),
  # not at startup, so on a fresh volume the seed's INSERT would land on a
  # table that does not exist yet. One read creates it.
  curl -s -m 20 -o /dev/null "$PROXY/conversations" || true

  # Restores the five `baseline-*` job rows and two conversations to their
  # canonical values, so a re-run records the same bytes even after an
  # earlier phase mutated a row.
  bash "$SEED_SCRIPT" >/dev/null
}

# ---------------------------------------------------------------------------
# Fixture writer.
# ---------------------------------------------------------------------------

# write_fixture <name> <request-label> <transport> <authored-json> <headers-file> <body-file>
write_fixture() {
  RF_NAME="$1" RF_REQUEST="$2" RF_TRANSPORT="$3" RF_AUTHORED="$4" \
  RF_HEADERS="$5" RF_BODY="$6" RF_COMMIT="$COMMIT" RF_OUT="$FIXTURE_DIR/$1.json" \
  python3 - <<'PY'
import json
import os

ALLOWLIST = (
    # `web/app/api/[...path]/route.ts` RESPONSE_HEADERS — the exact set the
    # proxy forwards, i.e. the exact set the browser can see.
    "cache-control",
    "content-disposition",
    "content-type",
    "retry-after",
    "www-authenticate",
    "x-accel-buffering",
)

raw_headers = open(os.environ["RF_HEADERS"], encoding="utf-8").read()
lines = [line for line in raw_headers.splitlines() if line.strip()]
status_line = lines[0]
_, _, rest = status_line.partition(" ")
code, _, reason = rest.partition(" ")

headers = {}
for line in lines[1:]:
    name, sep, value = line.partition(":")
    if not sep:
        continue
    name = name.strip().lower()
    if name in ALLOWLIST:
        headers[name] = value.strip()

body_text = open(os.environ["RF_BODY"], encoding="utf-8").read()
body = json.loads(body_text) if body_text.strip() else None

authored = json.loads(os.environ["RF_AUTHORED"])

document = {
    "x-recording": {
        "note": (
            "Recorded response body and headers. DO NOT EDIT BY HAND — "
            "re-record with `bash web/contract/record.sh`. JSON has no "
            "comment syntax, so this key carries the header."
        ),
        "case": os.environ["RF_NAME"],
        "commit": os.environ["RF_COMMIT"],
        "request": os.environ["RF_REQUEST"],
        "transport": os.environ["RF_TRANSPORT"],
        "stack": (
            "docker compose (app + web + redis + postgres) with "
            "ANTHROPIC_API_KEY=local-preview-disabled, seeded by "
            "docs/revamp/baseline/fixtures/seed-local-baseline.sh"
        ),
        "headers": (
            "filtered to the proxy response allowlist in "
            "web/app/api/[...path]/route.ts; volatile transport headers "
            "are dropped so the fixture is byte-stable"
        ),
        **authored,
    },
    "status": int(code),
    "statusText": reason.strip(),
    "headers": headers,
    "body": body,
}

with open(os.environ["RF_OUT"], "w", encoding="utf-8") as handle:
    json.dump(document, handle, indent=2, ensure_ascii=False)
    handle.write("\n")
PY
  echo "  wrote fixtures/$1.json"
}

RECORDED='{"authored": false}'

# A non-terminal job has no `completed_at`, so `Job.elapsed_sec`
# (`src/api/jobs.py:102-107`) subtracts its fixed seeded `started_at` from
# `time.time()`. That one number therefore grows between recordings; the rest
# of the body is byte-stable.
LIVE_ELAPSED='{"authored": false, "volatile": "body.elapsed_sec is now() - started_at for a job with no completed_at (src/api/jobs.py:102-107), so it differs between recordings"}'

# record_get <name> <path> <request-label> [authored-json]
record_get() {
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" "$PROXY$2"
  write_fixture "$1" "$3" "Next.js /api proxy -> FastAPI" "${4:-$RECORDED}" \
    "$WORK/h" "$WORK/b"
}

# ---------------------------------------------------------------------------
# SSE recording.
# ---------------------------------------------------------------------------

# Publish frames through the app container's own `RedisJobStore.publish_event`
# — the identical call `src/api/runner.py:_put_event` makes — because the
# runner cannot be started without submitting a job. The frames therefore
# travel the real pub/sub channel, through the real streaming loop, onto a
# real socket; only the field *values* are transcribed from the runner's emit
# sites. Every SSE script whose frames come from here says so in its header.
publisher_py() {
  cat >"$WORK/publish.py" <<'PY'
import asyncio
import json
import sys

from src.api.redis_store import RedisJobStore, build_redis_client
from src.config import settings


async def main() -> None:
    job_id = sys.argv[1]
    script = json.loads(sys.argv[2])
    store = RedisJobStore(build_redis_client(settings.redis_url))
    for step in script:
        await asyncio.sleep(step.get("delay", 0.3))
        await store.publish_event(job_id, step["event"], step["data"])


asyncio.run(main())
PY
}

# publish <job_id> <script-json>
publish() {
  docker exec -i "$APP_CONTAINER" python - "$1" "$2" <"$WORK/publish.py"
}

TIMEOUT_APP="record-sse-timeout"
TIMEOUT_APP_PORT=8098
RATELIMIT_APP="record-ratelimit"
RATELIMIT_APP_PORT=8097
LEARNER_APP="record-learner"
LEARNER_APP_PORT=8096

# `docker-compose.yml` surfaces only a fixed set of variables to the app
# service, and two settings these recordings need — `api_sse_max_duration_sec`
# and `api_key_hourly_limit` — are not among them. Rather than edit the
# compose file (out of this work order's scope, and a change to a shipped
# artifact for a test's convenience), spin up a second container from the same
# image on the same network, carrying the compose app's own environment plus
# the overrides. Same code, same Redis, same Postgres.
#
# app_variant_up <container> <host-port> <extra-env-lines>
app_variant_up() {
  local container="$1" port="$2" extra="$3" i
  docker rm -f "$container" >/dev/null 2>&1 || true

  # PATH must not be inherited: the image puts its virtualenv first, and
  # copying the resolved PATH back in would shadow it.
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$APP_CONTAINER" \
    | grep -E '^[A-Z_]+=' \
    | grep -v -E '^(PATH|HOME|LANG)=' >"$WORK/$container.env"
  {
    echo "ENABLE_JOB_REDRIVER=false"
    printf '%s\n' "$extra"
  } >>"$WORK/$container.env"

  docker run -d --name "$container" \
    --network "$(docker inspect -f '{{range $net,$_ := .NetworkSettings.Networks}}{{$net}}{{end}}' "$APP_CONTAINER")" \
    --env-file "$WORK/$container.env" \
    -p "127.0.0.1:${port}:8000" \
    arxiv-research-agent:local python -m src.api.serve >/dev/null

  for i in $(seq 1 60); do
    if curl -s -m 2 -o /dev/null "http://127.0.0.1:${port}/healthz"; then
      return 0
    fi
    sleep 1
  done
  echo "container $container never became healthy" >&2
  docker logs "$container" | tail -20 >&2
  return 1
}

app_variant_down() {
  docker rm -f "$1" >/dev/null 2>&1 || true
}

# `--env-file` keeps duplicate keys' LAST value, so the overrides appended
# above win over the inherited ones.
timeout_app_up() {
  app_variant_up "$TIMEOUT_APP" "$TIMEOUT_APP_PORT" "API_SSE_MAX_DURATION_SEC=60"
}

timeout_app_down() {
  app_variant_down "$TIMEOUT_APP"
}

# Every conversation the recording itself created. `POST /conversations` is
# the only free way to reach the shared rate-limit bucket, and the accepted
# call really does write a row — which would then show up in
# `conversations.list.json` on the next run. The seed script owns every
# `baseline-*` row; anything else is ours to remove.
purge_recorded_conversations() {
  docker exec -i arxiv-research-agent-postgres \
    psql -v ON_ERROR_STOP=1 -U arxiv -d arxiv -q -c \
    "DELETE FROM conversation_jobs WHERE conversation_id NOT LIKE 'baseline-%';
     DELETE FROM conversations WHERE conversation_id NOT LIKE 'baseline-%';" \
    >/dev/null
}

# sse_start <raw-file> <job_id> <max-seconds> — opens a stream in the
# background and leaves its pid in SSE_PID. Not a command substitution, so
# the curl stays a child of this shell and `wait` can reach it.
sse_start() {
  curl -sS -N -m "$3" "$PROXY/research/$2/stream" >"$1" 2>/dev/null &
  SSE_PID=$!
}

# Turn one connection's raw SSE bytes into JSON Lines records.
#
# sse_frames <raw-file> <out-name> [header-json]
#
# With a header, the script is (re)written starting from it. Without one, the
# frames are appended — which is how a scenario made of two connections, like
# `reconnect_gap`, keeps both legs in receive order in a single file.
sse_frames() {
  SJ_RAW="$1" SJ_OUT="$SSE_DIR/$2.jsonl" SJ_HEADER="${3:-}" python3 - <<'PY'
import json
import os

raw = open(os.environ["SJ_RAW"], encoding="utf-8").read()
header = os.environ["SJ_HEADER"]
records = [json.loads(header)] if header else []

# Frames are separated by a blank line; a line starting with `:` is an SSE
# comment, which is how the heartbeat arrives (`streaming.py:135-142`).
for block in raw.split("\n\n"):
    block = block.strip("\n")
    if not block:
        continue
    if block.startswith(":"):
        records.append({"type": "comment", "text": block[1:].strip()})
        continue
    name = None
    data_lines = []
    for line in block.split("\n"):
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    if name is None:
        # A partial frame at the tail of a connection that was cut off.
        continue
    payload = "\n".join(data_lines)
    records.append(
        {
            "type": "event",
            "event": name,
            "data": json.loads(payload) if payload else None,
        }
    )

with open(os.environ["SJ_OUT"], "w" if header else "a", encoding="utf-8") as handle:
    for record in records:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
PY
  if [ -n "${3:-}" ]; then echo "  wrote sse/$2.jsonl"; fi
}

# Append a directive line to a script already written. Directives are not
# frames — they mark what the *client* did between connections.
# sse_directive <name> <directive> <note>
sse_directive() {
  SD_OUT="$SSE_DIR/$1.jsonl" SD_KIND="$2" SD_NOTE="$3" python3 - <<'PY'
import json
import os

with open(os.environ["SD_OUT"], "a", encoding="utf-8") as handle:
    handle.write(
        json.dumps(
            {
                "type": "directive",
                "directive": os.environ["SD_KIND"],
                "note": os.environ["SD_NOTE"],
            }
        )
        + "\n"
    )
PY
}

sse_header() {
  SH_CASE="$1" SH_SOURCE="$2" SH_AUTHORED="$3" SH_NOTE="$4" SH_COMMIT="$COMMIT" \
  python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "type": "header",
            "case": os.environ["SH_CASE"],
            "commit": os.environ["SH_COMMIT"],
            "source": os.environ["SH_SOURCE"],
            "authored": json.loads(os.environ["SH_AUTHORED"]),
            "note": os.environ["SH_NOTE"],
            "format": (
                "JSON Lines. Line 1 is this header; the rest are "
                "{'type':'event'|'comment'|'directive'} records in receive "
                "order. Recorded off the wire by web/contract/record.sh."
            ),
        }
    )
)
PY
}

PUBLISHED_NOTE="Frames were published through RedisJobStore.publish_event inside the app container — the same call src/api/runner.py:_put_event makes — because POST /research is forbidden (MUST-KEEP #3), so no runner could produce them. The wire framing, ordering, heartbeats and close behaviour are recorded off a real SSE socket; the payload field values are transcribed from the runner's emit sites."

# ---------------------------------------------------------------------------
# Phase: http
# ---------------------------------------------------------------------------

record_http() {
  log "phase http — job states, conversations, 404 / 409 / 422"
  seed
  purge_recorded_conversations

  record_get job.succeeded /research/baseline-succeeded \
    "GET /api/research/baseline-succeeded"
  record_get job.running /research/baseline-running \
    "GET /api/research/baseline-running" "$LIVE_ELAPSED"
  record_get job.pending_review /research/baseline-plan-review \
    "GET /api/research/baseline-plan-review" "$LIVE_ELAPSED"
  record_get job.failed_partial /research/baseline-failed-partial \
    "GET /api/research/baseline-failed-partial"
  record_get job.cancelled /research/baseline-cancelled \
    "GET /api/research/baseline-cancelled"

  record_get conversations.list /conversations "GET /api/conversations"
  record_get conversations.detail /conversations/baseline-populated \
    "GET /api/conversations/baseline-populated"

  # 404 — ownership mismatch and "never existed" are the same status by
  # design (`routes.py:59-84`), which is why the UI copy may not say
  # "deleted" or "no permission".
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    "$PROXY/research/baseline-does-not-exist"
  write_fixture error.404 "GET /api/research/baseline-does-not-exist" \
    "Next.js /api proxy -> FastAPI" "$RECORDED" "$WORK/h" "$WORK/b"

  # 409 — the envelope that embeds the state in the detail string
  # (`routes.py:262-264`). `normalizeFailure` parses `(status=...)` out of it.
  # This is a review POST, not `POST /research`: the handler records the
  # decision and signals a runner. There is no runner on a seeded row, so
  # nothing resumes and no model is contacted — and this call 409s before any
  # of that anyway.
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    -X POST -H 'content-type: application/json' \
    -d '{"action":"approve"}' \
    "$PROXY/research/baseline-running/review"
  write_fixture error.409 \
    "POST /api/research/baseline-running/review {\"action\":\"approve\"}" \
    "Next.js /api proxy -> FastAPI" "$RECORDED" "$WORK/h" "$WORK/b"

  # 422 — FastAPI's per-field list. `MAX_TITLE_LEN = 80`
  # (`src/api/schemas.py:168`); 81 characters trips it. Validation fails
  # before the handler runs, so no conversation is created.
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    -X POST -H 'content-type: application/json' \
    -d '{"title":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}' \
    "$PROXY/conversations"
  write_fixture error.422 \
    "POST /api/conversations with an 81-character title (MAX_TITLE_LEN = 80)" \
    "Next.js /api proxy -> FastAPI" "$RECORDED" "$WORK/h" "$WORK/b"
}

# ---------------------------------------------------------------------------
# Phase: sse
# ---------------------------------------------------------------------------

record_sse() {
  log "phase sse — nine frame scripts"
  seed
  publisher_py

  # -- replay_terminal: a terminal job replays one frame and closes. Wholly
  #    server-produced; nothing is published.
  local raw
  raw="$WORK/replay_terminal.sse"
  sse_start "$raw" baseline-succeeded 15
  wait "$SSE_PID" || true
  sse_frames "$raw" replay_terminal "$(sse_header replay_terminal \
    "GET /api/research/baseline-succeeded/stream (job already succeeded)" \
    false \
    "Attach-time terminal replay (routes.py:438-441, payload routes.py:857-867). Note the shape differs from the live job_completed frame: it carries status and drops llm_calls. Entirely server-generated — no frame was published for this recording.")"

  # -- terminal_replay_no_node: 03 §5.9 obligation 3. Same replay path on the
  #    failed-with-partial-report row, so error/error_type are populated and
  #    there is still no `node` anywhere in the stream.
  raw="$WORK/terminal_replay_no_node.sse"
  sse_start "$raw" baseline-failed-partial 15
  wait "$SSE_PID" || true
  sse_frames "$raw" terminal_replay_no_node "$(sse_header terminal_replay_no_node \
    "GET /api/research/baseline-failed-partial/stream (job already failed)" \
    false \
    "03-DESIGN-BRIEF.md §5.9 obligation 3: terminal replay with no node. No frame in this script carries a node key, so a ledger built from this stream must stay empty — a label here would have to have been invented. Entirely server-generated.")"

  # -- plan_review: the pending_review replay is real (routes.py:463-464,
  #    byte-identical to the runner's frame by design). What follows an
  #    approve is published, because a live approve would resume the workflow
  #    against a model.
  raw="$WORK/plan_review.sse"
  sse_start "$raw" baseline-plan-review 12
  sleep 1
  publish baseline-plan-review '[
    {"delay":0.4,"event":"node_completed","data":{"node":"searcher","state_delta":{"iteration":1,"papers_found":7}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"synthesizer","state_delta":{"iteration":1,"report_chars":4820}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-plan-review","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":62.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" plan_review "$(sse_header plan_review \
    "GET /api/research/baseline-plan-review/stream, then frames published on events:baseline-plan-review" \
    true \
    "04-ARCHITECTURE.md §7.2 scenario 'plan review then approve'. The opening plan_ready frame is a real attach-time replay off the seeded pending_review row. The frames after it are published: approving for real resumes the workflow against a model, which the cost boundary forbids. $PUBLISHED_NOTE")"

  # -- live_success
  raw="$WORK/live_success.sse"
  sse_start "$raw" baseline-running 15
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"job_started","data":{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}},
    {"delay":0.4,"event":"node_completed","data":{"node":"planner","state_delta":{"iteration":0,"sub_questions_count":3}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"searcher","state_delta":{"iteration":1,"papers_found":9,"tried_search_queries_count":3}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"synthesizer","state_delta":{"iteration":1,"report_chars":5140}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-running","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":74.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" live_success "$(sse_header live_success \
    "GET /api/research/baseline-running/stream, frames published on events:baseline-running" \
    true \
    "04-ARCHITECTURE.md §7.2 scenario 'live success'. Note job_completed carries no status — the report body never arrives over SSE, so a client must reconcile with GET /research/{id}. $PUBLISHED_NOTE")"

  # -- live_failure
  seed
  raw="$WORK/live_failure.sse"
  sse_start "$raw" baseline-running 15
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"job_started","data":{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}},
    {"delay":0.4,"event":"node_completed","data":{"node":"planner","state_delta":{"iteration":0,"sub_questions_count":3}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"searcher","state_delta":{"iteration":1,"papers_found":2}}},
    {"delay":0.4,"event":"job_failed","data":{"job_id":"baseline-running","error":"Verification stopped before all claims could be checked.","error_type":"verification_incomplete","elapsed_sec":41.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" live_failure "$(sse_header live_failure \
    "GET /api/research/baseline-running/stream, frames published on events:baseline-running" \
    true \
    "04-ARCHITECTURE.md §7.2 scenario 'live failure'. error_type is a raw backend code and belongs in the diagnostics disclosure, never in the primary message. $PUBLISHED_NOTE")"

  # -- reconnect_gap: the no-backlog invariant, recorded rather than asserted.
  #    A frame published while nothing is subscribed is gone: Redis pub/sub
  #    drops messages with no subscriber (routes.py:444-454).
  seed
  raw="$WORK/reconnect_gap_1.sse"
  sse_start "$raw" baseline-running 6
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"job_started","data":{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}},
    {"delay":0.4,"event":"node_completed","data":{"node":"planner","state_delta":{"iteration":0,"sub_questions_count":3}}}
  ]'
  sleep 0.5
  kill "$SSE_PID" 2>/dev/null || true
  wait "$SSE_PID" 2>/dev/null || true
  sse_frames "$raw" reconnect_gap "$(sse_header reconnect_gap \
    "two GET /api/research/baseline-running/stream connections with frames published in between" \
    true \
    "04-ARCHITECTURE.md §7.2 scenario 'reconnect with a gap'. Between the two connections a node_completed frame for node 'searcher' was published with nobody subscribed. It is absent below, and that absence is the recording: there is no replay backlog and no Last-Event-ID contract, so a client MUST NOT invent the missing checkpoint. $PUBLISHED_NOTE")"
  sse_directive reconnect_gap disconnect \
    "client connection dropped; the frames published while it was gone are lost"
  # Published into the gap. Nothing is subscribed, so this frame is dropped.
  publish baseline-running '[
    {"delay":0.1,"event":"node_completed","data":{"node":"searcher","state_delta":{"iteration":1,"papers_found":9}}}
  ]'
  sse_directive reconnect_gap reopen \
    "client reopens the same stream URL; the server offers no backlog"
  raw="$WORK/reconnect_gap_2.sse"
  sse_start "$raw" baseline-running 12
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"node_completed","data":{"node":"synthesizer","state_delta":{"iteration":1,"report_chars":5140}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-running","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":74.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" reconnect_gap

  # -- stream_timeout: wholly server-generated, and the one leg that cannot
  #    use the compose app. `api_sse_max_duration_sec` defaults to 3600 and
  #    `docker-compose.yml` does not surface it, so this brings up a second
  #    app container — same image, same entry point, same Redis and Postgres
  #    on the compose network — with the deadline at its floor of 60
  #    (`src/config.py`, ge=60). Recorded straight off FastAPI rather than
  #    through the proxy, which passes the stream body through untouched
  #    (`route.ts`: `new Response(upstream.body)`).
  seed
  timeout_app_up
  log "  holding a stream open past api_sse_max_duration_sec=60 (~65s)"
  raw="$WORK/stream_timeout_1.sse"
  curl -sS -N -m 75 \
    "http://127.0.0.1:${TIMEOUT_APP_PORT}/research/baseline-running/stream" \
    >"$raw" 2>/dev/null &
  SSE_PID=$!
  wait "$SSE_PID" || true
  sse_frames "$raw" stream_timeout "$(sse_header stream_timeout \
    "GET /research/baseline-running/stream on an app with api_sse_max_duration_sec=60, held past the deadline, then reopened" \
    true \
    "04-ARCHITECTURE.md §7.2 scenario 'stream_timeout followed by a reopen'. Everything up to and including the stream_timeout frame is server-generated (streaming.py:300-308) — the heartbeat cadence and the frame itself are real output from the deadline path, and nothing about them is authored. stream_timeout is NOT a job outcome: the job kept running, so a client must reconnect rather than report a result. The frames after the reopen directive are published, which is why the script as a whole is marked authored. $PUBLISHED_NOTE")"
  timeout_app_down
  sse_directive stream_timeout reopen \
    "reconnect: the payload's reconnect flag is true and the job is still running"
  raw="$WORK/stream_timeout_2.sse"
  sse_start "$raw" baseline-running 12
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"node_completed","data":{"node":"synthesizer","state_delta":{"iteration":1,"report_chars":5140}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-running","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":74.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" stream_timeout

  # -- unknown_event_name: 03 §5.9 obligation. The server forwards any event
  #    name a publisher puts on the channel, so this is what an added backend
  #    event looks like to today's client.
  seed
  raw="$WORK/unknown_event_name.sse"
  sse_start "$raw" baseline-running 12
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"job_started","data":{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}},
    {"delay":0.4,"event":"node_started","data":{"node":"searcher"}},
    {"delay":0.4,"event":"paper_indexed","data":{"node":"searcher","arxiv_id":"2601.00001","score":0.71}},
    {"delay":0.4,"event":"node_completed","data":{"node":"searcher","state_delta":{"iteration":1,"papers_found":9}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-running","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":74.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" unknown_event_name "$(sse_header unknown_event_name \
    "GET /api/research/baseline-running/stream with two names the backend does not emit today" \
    true \
    "03-DESIGN-BRIEF.md §5.9 obligation: unknown event name. node_started and paper_indexed are NOT in SERVER_EVENT_NAMES — node_started in particular does not exist (src/api/streaming.py:13-35 says so explicitly). A client must ignore them without breaking, and must not render them as ledger entries. $PUBLISHED_NOTE")"

  # -- unknown_state_delta_keys: node names are opaque strings and state_delta
  #    is filtered to scalars but otherwise open-ended (runner.py:947-951).
  seed
  raw="$WORK/unknown_state_delta_keys.sse"
  sse_start "$raw" baseline-running 12
  sleep 1
  publish baseline-running '[
    {"delay":0.3,"event":"job_started","data":{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}},
    {"delay":0.4,"event":"node_completed","data":{"node":"planner","state_delta":{"iteration":0,"sub_questions_count":3,"planner_confidence":0.62,"unreleased_feature_flag":true}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"claim_decomposer","state_delta":{"iteration":1,"claims_extracted":14,"decomposition_strategy":"per-sentence"}}},
    {"delay":0.4,"event":"node_completed","data":{"node":"searcher","state_delta":{}}},
    {"delay":0.4,"event":"job_completed","data":{"job_id":"baseline-running","iterations":2,"quality_score":0.86,"cost_usd":0.42,"llm_calls":11,"elapsed_sec":74.0}}
  ]'
  wait "$SSE_PID" || true
  sse_frames "$raw" unknown_state_delta_keys "$(sse_header unknown_state_delta_keys \
    "GET /api/research/baseline-running/stream with open-ended state_delta payloads" \
    true \
    "03-DESIGN-BRIEF.md §5.9 obligation: unknown state_delta keys. claim_decomposer is not a node in today's graph and several delta keys are not in any vocabulary; one frame carries an empty delta. No fixed vocabulary may be assumed for either. $PUBLISHED_NOTE")"

  seed
}

# ---------------------------------------------------------------------------
# Phase: ratelimited — the 429 envelope, whose detail is an OBJECT.
# ---------------------------------------------------------------------------

record_ratelimited() {
  log "phase ratelimited — 429 with the object detail and Retry-After"
  # Auth on with a ceiling of one request per hour and the Redis-backed
  # counter. `POST /conversations` shares the `POST /research` rate-limit
  # bucket (routes.py:157 / routes.py:545), which is what makes the 429
  # reachable without ever submitting research.
  #
  # Recorded straight off FastAPI on a variant container, because
  # `API_KEY_HOURLY_LIMIT` is not one of the variables the compose app
  # service surfaces. The proxy would only add its allowlist filter, which
  # `write_fixture` applies anyway.
  app_variant_up "$RATELIMIT_APP" "$RATELIMIT_APP_PORT" \
"ENABLE_API_AUTH=true
API_KEYS=${RECORD_API_KEY_ID}:${RECORD_API_KEY_SECRET}
API_KEY_HOURLY_LIMIT=1
RATE_LIMIT_BACKEND=redis"

  local base="http://127.0.0.1:${RATELIMIT_APP_PORT}"

  # Clear any counter a previous run left behind, so the first call below is
  # always the one that fits inside the ceiling.
  docker exec "$REDIS_CONTAINER" sh -c \
    "redis-cli --scan --pattern 'ratelimit:*' | xargs -r redis-cli DEL" >/dev/null

  # First request consumes the single slot.
  curl -sS -m 20 -o /dev/null -X POST \
    -H 'content-type: application/json' \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" \
    -d '{"title":"rate limit probe"}' "$base/conversations"
  # Second is rejected.
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" -X POST \
    -H 'content-type: application/json' \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" \
    -d '{"title":"rate limit probe"}' "$base/conversations"
  write_fixture error.429 \
    "POST /conversations, second call under API_KEY_HOURLY_LIMIT=1" \
    "FastAPI directly, ENABLE_API_AUTH=true, RATE_LIMIT_BACKEND=redis" \
    '{"authored": false, "volatile": "headers.retry-after is the seconds left in the sliding hour window and can differ by a second or two between recordings"}' \
    "$WORK/h" "$WORK/b"

  app_variant_down "$RATELIMIT_APP"
  purge_recorded_conversations
}

# ---------------------------------------------------------------------------
# Phase: learner — the profile surface (ADR 0058).
# ---------------------------------------------------------------------------

record_learner() {
  log "phase learner — GET /learn/profile with declared + inferred claims"
  # Recorded straight off FastAPI on a variant container, for the same
  # reason `ratelimited` is: `ENABLE_LEARNER_PROFILE` is not one of the
  # variables the compose app service surfaces, and the flag refuses to
  # load without `ENABLE_API_AUTH` (ADR 0058), which is not the posture
  # the other HTTP fixtures are recorded in. The proxy would only add
  # its allowlist filter, which `write_fixture` applies anyway.
  #
  # Every call below is free: the profile surface contacts no model.
  app_variant_up "$LEARNER_APP" "$LEARNER_APP_PORT" \
"ENABLE_API_AUTH=true
API_KEYS=${RECORD_API_KEY_ID}:${RECORD_API_KEY_SECRET}
ENABLE_LEARNER_PROFILE=true
LEARNER_PROFILE_STORE=postgres"

  local base="http://127.0.0.1:${LEARNER_APP_PORT}"

  # Start from a known state so a re-run records the same bytes.
  curl -sS -m 20 -o /dev/null -X DELETE \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" "$base/learn/profile"

  # The learner declares. `PUT` can only ever write `declared` claims —
  # the request schema has no provenance field at all.
  curl -sS -m 20 -o /dev/null -X PUT \
    -H 'content-type: application/json' \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" \
    -d '{"academic_level":"grad","time_budget_min_per_day":20,
         "goals":[{"goal_id":"g-rlhf","statement":"read modern RLHF papers critically","target_date":"2026-12-01","status":"active","priority":1}],
         "skills":[{"skill":"backprop","level":"solid"},{"skill":"transformers","level":"working"}],
         "profile_note":"Self-taught; I learn best from worked examples."}' \
    "$base/learn/profile"

  # An inferred claim and an assessed one, written through the store's
  # own API rather than HTTP — which is the point: nothing a client can
  # send produces either of these, so the fixture has to make them the
  # way the session loop will (ADR 0058). The `assessed` claim
  # deliberately contradicts the `declared` one so the recorded body
  # shows both claims standing side by side.
  docker exec -i "$LEARNER_APP" python - <<'PY' >/dev/null
import asyncio

from src.learning.profile_store import PostgresProfileStore, SkillEntry

STAMP = "2026-08-30T00:00:00+00:00"
entries = (
    SkillEntry(
        skill="backprop",
        level="aware",
        source="assessed",
        evidence_ref="assessment:baseline-explain-back",
        confidence=0.7,
        updated_at=STAMP,
    ),
    SkillEntry(
        skill="attention",
        level="working",
        source="inferred",
        evidence_ref="session:baseline-guided-read",
        confidence=0.5,
        updated_at=STAMP,
    ),
)
asyncio.run(PostgresProfileStore().record_skill_entries("web", entries))
PY

  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" "$base/learn/profile"
  write_fixture learn.profile \
    "GET /learn/profile for a learner with declared, assessed and inferred claims" \
    "FastAPI directly, ENABLE_API_AUTH=true, ENABLE_LEARNER_PROFILE=true" \
    '{"authored": false, "volatile": "body.created_at, body.updated_at, and updated_at on the two declared claims are wall-clock write times and differ between recordings; the assessed and inferred claims carry a pinned timestamp because the store API writes the value it is handed"}' \
    "$WORK/h" "$WORK/b"

  # Leave the shared Postgres as it was found — the deletion promise,
  # exercised as cleanup.
  curl -sS -m 20 -o /dev/null -X DELETE \
    -H "X-API-Key: ${RECORD_API_KEY_SECRET}" "$base/learn/profile"

  app_variant_down "$LEARNER_APP"
}

# ---------------------------------------------------------------------------
# Phase: unauthorized — 401 with WWW-Authenticate.
# ---------------------------------------------------------------------------

record_unauthorized() {
  log "phase unauthorized — 401 with WWW-Authenticate"
  # Auth on and the proxy holding NO key: it forwards no X-API-Key, so
  # FastAPI answers 401 `missing_api_key`. This is the real deployment
  # failure the 401 copy describes — a server configuration problem, not a
  # user who needs to log in (03-DESIGN-BRIEF.md §6).
  export ENABLE_API_AUTH=true
  export API_KEYS="${RECORD_API_KEY_ID}:${RECORD_API_KEY_SECRET}"
  export WEB_API_KEY=""
  stack_up

  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" "$PROXY/conversations"
  write_fixture error.401 \
    "GET /api/conversations with the proxy holding no API key" \
    "Next.js /api proxy -> FastAPI, ENABLE_API_AUTH=true, ARXIV_API_KEY unset" \
    "$RECORDED" "$WORK/h" "$WORK/b"

  stack_reset
}

# ---------------------------------------------------------------------------
# Phase: learn — the read-only learning-content surface (WO-W15).
# ---------------------------------------------------------------------------
#
# Unlike every other phase, this one needs no seed. `GET /learn/paths*` reads
# the manifests committed under `content/` and opens no store, so the body is
# a pure function of the repository — which is why
# `tests/test_contract_learn_fixtures.py` can re-derive these two bodies from
# the app on every CI run instead of trusting the recorded bytes. Running this
# phase is therefore optional: it exists so a reviewer can confirm the proxy
# transport agrees with the in-process recording, and so the fixtures have the
# same re-recording story as their neighbours.
#
# The flag is off by default (`src/config.py: enable_learn_content`), so the
# stack is brought up with it on and reset afterwards.

record_learn() {
  log "phase learn — published paths and one path detail"
  export ENABLE_LEARN_CONTENT=true
  stack_up

  record_get learn.paths /learn/paths "GET /api/learn/paths"
  record_get learn.path.detail /learn/paths/fixture-guided-read \
    "GET /api/learn/paths/fixture-guided-read"

  unset ENABLE_LEARN_CONTENT
  stack_up
}

# ---------------------------------------------------------------------------
# Phase: proxy — 502 and 503, which FastAPI never emits.
# ---------------------------------------------------------------------------

record_proxy() {
  log "phase proxy — 502 and 503 from the Next.js route handler"
  local name port
  port=3098

  # 502: the upstream is unreachable, so the proxy's fetch throws
  # (route.ts:98-101). Port 9 is the discard port; nothing listens there.
  name="record-proxy-502"
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" -p "127.0.0.1:${port}:3000" \
    -e API_INTERNAL_BASE=http://127.0.0.1:9 \
    arxiv-research-agent-web:local >/dev/null
  wait_for_web "$port"
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    "http://127.0.0.1:${port}/api/conversations"
  write_fixture error.502 \
    "GET /api/conversations with API_INTERNAL_BASE pointing at a closed port" \
    "Next.js /api proxy, generated locally — the upstream was never reached" \
    "$RECORDED" "$WORK/h" "$WORK/b"
  docker rm -f "$name" >/dev/null

  # 503: `API_INTERNAL_BASE` fails the route handler's own validation, so no
  # request is attempted at all (route.ts:70-74).
  name="record-proxy-503"
  docker rm -f "$name" >/dev/null 2>&1 || true
  docker run -d --name "$name" -p "127.0.0.1:${port}:3000" \
    -e API_INTERNAL_BASE=ftp://app:8000 \
    arxiv-research-agent-web:local >/dev/null
  wait_for_web "$port"
  curl -sS -m 20 -D "$WORK/h" -o "$WORK/b" \
    "http://127.0.0.1:${port}/api/conversations"
  write_fixture error.503 \
    "GET /api/conversations with an API_INTERNAL_BASE the proxy rejects" \
    "Next.js /api proxy, generated locally — the upstream was never reached" \
    "$RECORDED" "$WORK/h" "$WORK/b"
  docker rm -f "$name" >/dev/null
}

wait_for_web() {
  local i
  for i in $(seq 1 40); do
    if curl -s -m 2 -o /dev/null "http://127.0.0.1:$1/api/conversations"; then
      return 0
    fi
    sleep 0.5
  done
  echo "web container on port $1 never answered" >&2
  return 1
}

# ---------------------------------------------------------------------------

mkdir -p "$FIXTURE_DIR" "$SSE_DIR"

log "stack up (ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY, APP_PORT=$APP_PORT, WEB_PORT=$WEB_PORT)"
stack_up

if phase_requested http; then record_http; fi
if phase_requested sse; then record_sse; fi
if phase_requested ratelimited; then record_ratelimited; fi
if phase_requested unauthorized; then record_unauthorized; fi
if phase_requested learn; then record_learn; fi
if phase_requested proxy; then record_proxy; fi
if phase_requested learner; then record_learner; fi

log "done. Stop the stack with: docker compose down"
