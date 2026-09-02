#!/usr/bin/env bash
#
# The seeded local stack for the Playwright suite.
#
# PROMOTED, NOT REWRITTEN, from
# `docs/revamp/baseline/fixtures/seed-local-baseline.sh` (04-ARCHITECTURE.md
# §7.3). Every fixture the Gate 1 evidence run used is here byte-for-byte, so
# the retained baseline screenshots and axe reports stay directly comparable
# to anything this harness produces. The additions are marked `# WO-21`.
#
# THE FOUR SAFETY PROPERTIES, UNCHANGED
#
#   1. It writes only `baseline-*` records. Every INSERT names a fixed
#      `baseline-*` id and every Redis key is `job:baseline-*` or
#      `joblease:baseline-*`. Nothing here can touch a real conversation.
#   2. Every write is an idempotent upsert (`ON CONFLICT ... DO UPDATE`,
#      `SET`), so re-seeding a stack that is already seeded is a no-op and
#      `npm run e2e:stack:seed` is safe to type twice.
#   3. Non-terminal synthetic jobs hold a Redis lease, so the production
#      redriver (`src/api/redriver.py:507`) leaves them alone instead of
#      rewriting them to `orphaned` mid-run. The redriver stays ENABLED in
#      the e2e overlay on purpose: a stack with it switched off would not
#      prove that this property works.
#   4. **It never calls `POST /research`.** No model provider is contacted,
#      no job is ever really run, and the stack itself is pinned to
#      `ANTHROPIC_API_KEY=local-preview-disabled` by
#      `web/e2e/support/compose.e2e.yml`. This is the cost boundary in
#      `06-WORK-ORDERS.md` §0, and it is why the fixtures are written
#      *behind* the API rather than through it.
#
# WHAT WO-21 ADDED, AND THE ONE PLACE THE ARCHITECTURE'S WORDING SPLITS
#
# §7.3 asks for rows covering "rate-limited, unauthorized, and stream-timeout".
# Those are not three of a kind, and pretending they were would have produced
# a fixture that lies:
#
#   * `stream-timeout` IS a run state. `job:baseline-stream-timeout` below is
#     a genuine leased `running` row — the row a `stream_timeout` frame is
#     delivered against. The frame itself comes from route interception
#     because a real stack emits it only after `api_sse_max_duration_sec`.
#
#   * `rate-limited` (429) and `unauthorized` (401) are **transport** states —
#     `ApiFailure.kind` in `web/lib/api/errors.ts`, mapped at
#     `web/lib/copy/errors.ts:97` and `:119`. They are not values of
#     `JobDetail.error_type`, whose nine members are enumerated at
#     `web/lib/copy/errors.ts:303` and re-derived from the Python sources by
#     `web/tests/copy/errorTypeDrift.test.ts`. No job row can carry them, so
#     the seed carries their **wire bodies** instead, in
#     `web/e2e/fixtures/transport-failures.json`, copied from the literals in
#     `src/api/auth.py:178` and `:508-516`. `web/e2e/support/intercept.ts`
#     replays them.
#
#     Rejected alternative, recorded because it is the obvious one: seed
#     `ratelimit:{key_id}` (`src/api/auth.py:45`, a real Redis ZSET) so the
#     backend emits a real 429. It works, and it poisons the bucket for every
#     other spec on the same principal — with auth off there is exactly one —
#     including the paid-path submissions. A shared mutable counter is not a
#     fixture.
#
#   * `baseline-partial-export` (WO-21) is the row slice step 5 needs: a
#     FAILED job that still carries a `result`. `src/api/routes.py:364-368`
#     lets it be exported and `web/components/ReportView.tsx:13-29` hides it,
#     which is R-14, and an export assertion needs a job the backend will
#     actually serve three formats for.
#
# USAGE
#
#   bash web/e2e/fixtures/seed.sh
#   E2E_COMPOSE_PROJECT=my-project bash web/e2e/fixtures/seed.sh
#
# Container names default to the `web/e2e/support/compose.e2e.yml` overlay's,
# not to the base file's — the base file's names collide across worktrees.

set -euo pipefail

# WO-W13. `ENABLE_API_AUTH` is on in `web/e2e/support/compose.e2e.yml` (the
# session loop cannot be mounted without it), and `_check_ownership`
# (`src/api/routes.py:85-110`) makes a row whose `principal_key_id` is NULL
# invisible under auth-on. So every fixture below is stamped with the single
# principal the stack issues. The value is the NAME half of `API_KEYS`, not
# the secret: it is what lands on a row and what the API compares.
principal="${E2E_PRINCIPAL:-e2e}"
api_secret="${E2E_API_SECRET:-sk_e2e_local_preview_disabled}"

# WO-W17. Under `E2E_PILOT=1` the stack issues TWO principals and no `e2e`
# one (`web/e2e/support/compose.pilot.yml`), so the schema-warming call below
# has to present a key the stack will actually accept — otherwise it 401s,
# the lazy DDL never runs, and every INSERT after it fails with a confusing
# `relation "conversations" does not exist`. The `baseline-*` rows are still
# written under `principal`, deliberately: they belong to a third principal
# neither pilot holds a key for, which makes "each pilot sees only their own"
# an assertion about isolation rather than about an empty database.
pilot="${E2E_PILOT:-}"
pilot_a_key_id="${E2E_PILOT_A_KEY_ID:-pilot-a}"
pilot_b_key_id="${E2E_PILOT_B_KEY_ID:-pilot-b}"
if [ "${pilot}" = "1" ]; then
  api_secret="${E2E_PILOT_A_SECRET:-sk_pilot_a_local_preview_disabled}"
fi

# Substitute the placeholder without unquoting the heredocs. The JSON rows
# below are copied byte-for-byte from the Gate 1 baseline and must not start
# being interpreted by the shell (`\n` inside a report body, `$` inside a
# future one), so they stay `<<'JSON'` and the owner is patched on the way
# past instead.
seed_job() {
  sed "s/__PRINCIPAL__/${principal}/g" \
    | docker exec -i "$redis_container" redis-cli -x SET "$1"
}

# WO-W17. The same substitution with the owner passed in, because the pilot
# rows below deliberately belong to two different principals.
seed_job_owned_by() {
  sed "s/__PRINCIPAL__/${2}/g" \
    | docker exec -i "$redis_container" redis-cli -x SET "$1"
}

postgres_container="${E2E_POSTGRES_CONTAINER:-${BASELINE_POSTGRES_CONTAINER:-arxiv-wo21-postgres}}"
redis_container="${E2E_REDIS_CONTAINER:-${BASELINE_REDIS_CONTAINER:-arxiv-wo21-redis}}"
app_container="${E2E_APP_CONTAINER:-arxiv-wo21-app}"

# WO-21. The conversation tables are created LAZILY, not at boot:
# `src/api/conversations.py:264` opens every `_run` closure with
# `init_schema()` (`src/tools/postgres_pool.py:177`), whose DDL is
# `CREATE TABLE IF NOT EXISTS`. Against a cold stack the INSERTs below
# therefore fail with `relation "conversations" does not exist` — which is
# what happened the first time this ran, and is a confusing error for a
# problem whose fix is one read.
#
# One `GET /conversations` from inside the app container runs the DDL. It is
# a read: no job, no write, no model. `|| true` because a stack whose
# conversation store is not Postgres has no schema to create and no reason to
# fail the seed here.
docker exec "$app_container" \
  curl -fsS -o /dev/null -H "X-API-Key: ${api_secret}" \
  "http://localhost:8000/conversations?limit=1" || true

docker exec -i "$postgres_container" psql -v ON_ERROR_STOP=1 -v principal="$principal" -U arxiv -d arxiv <<'SQL'
INSERT INTO conversations (
  conversation_id, title, created_at, updated_at, principal_key_id
) VALUES (
  'baseline-populated',
  'Scientific claim verification',
  '2026-08-28T02:16:02Z',
  '2026-08-28T02:17:04Z',
  :'principal'
) ON CONFLICT (conversation_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = EXCLUDED.updated_at,
  principal_key_id = EXCLUDED.principal_key_id;

INSERT INTO conversations (
  conversation_id, title, created_at, updated_at, principal_key_id
) VALUES (
  'baseline-empty',
  'Empty research thread',
  '2026-08-28T02:18:02Z',
  '2026-08-28T02:18:02Z',
  :'principal'
) ON CONFLICT (conversation_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = EXCLUDED.updated_at,
  principal_key_id = EXCLUDED.principal_key_id;

INSERT INTO conversation_jobs (
  conversation_id, job_id, ordinal, query, report, created_at
) VALUES (
  'baseline-populated',
  'baseline-succeeded',
  1,
  'How should scientific research agents verify claims?',
  E'# Retrieval-Augmented Verification for Scientific Claims\n\n## Executive summary\n\nRecent systems combine retrieval, claim decomposition, and post-generation verification to reduce unsupported statements. The strongest pattern is to preserve source provenance throughout synthesis rather than adding citations after generation.\n\n## Findings\n\n- Evidence retrieval works best when queries are decomposed into independently verifiable claims.\n- Verification models should be calibrated separately from generation models.\n- Human review remains valuable for ambiguous or conflicting evidence.\n\n| Approach | Strength | Limitation |\n|---|---|---|\n| Retrieval-first | Strong provenance | Recall-sensitive |\n| Post-hoc verification | Flexible | Can miss omitted evidence |\n| Human review | High precision | Slower and expensive |\n\n## Recommendation\n\nUse a retrieval-first pipeline with explicit claim-to-source links, confidence labels, and a human review breakpoint for low-confidence conclusions.\n\n## References\n\n1. Example et al. (2026). Evidence-aware synthesis. arXiv:2601.00001.',
  '2026-08-28T02:17:04Z'
) ON CONFLICT (conversation_id, ordinal) DO UPDATE SET
  job_id = EXCLUDED.job_id,
  query = EXCLUDED.query,
  report = EXCLUDED.report,
  created_at = EXCLUDED.created_at;

-- WO-21. Slice step 5 needs a turn in the transcript whose job FAILED but
-- still has a report, so the export assertions have something the backend
-- will serve `md`/`pdf`/`docx` for (`src/api/routes.py:364-368`). Ordinal 2
-- so it renders below the succeeded turn and is the one auto-expanded on
-- load (`ConversationThread.tsx:44-50` expands the last job).
INSERT INTO conversation_jobs (
  conversation_id, job_id, ordinal, query, report, created_at
) VALUES (
  'baseline-populated',
  'baseline-partial-export',
  2,
  'Which verification failures are worth reporting partially?',
  E'# Partial briefing (verification incomplete)\n\nThe run retained an incomplete synthesis before verification failed. It is\nshown because a partial answer the user paid for is not the same thing as no\nanswer (R-14).\n\n## What completed\n\n- Retrieval over the three sub-questions finished.\n- Two of five claims were checked against their sources.\n\n| Stage | Status |\n|---|---|\n| Retrieval | complete |\n| Reading | complete |\n| Verification | stopped |\n\n## What did not\n\nFinal claim verification did not complete, so nothing below the fold was\nchecked and no confidence label is reported.',
  '2026-08-28T02:19:04Z'
) ON CONFLICT (conversation_id, ordinal) DO UPDATE SET
  job_id = EXCLUDED.job_id,
  query = EXCLUDED.query,
  report = EXCLUDED.report,
  created_at = EXCLUDED.created_at;
SQL

seed_job job:baseline-succeeded <<'JSON'
{"job_id":"baseline-succeeded","query":"How should scientific research agents verify claims?","status":"succeeded","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883424.0,"result":"# Retrieval-Augmented Verification for Scientific Claims\n\n## Executive summary\n\nRecent systems combine retrieval, claim decomposition, and post-generation verification to reduce unsupported statements.\n\n## Findings\n\n- Evidence retrieval works best when queries are decomposed into independently verifiable claims.\n- Verification models should be calibrated separately from generation models.","error":null,"error_type":null,"cost_usd":0.42,"llm_calls":11,"iterations":2,"quality_score":0.86,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

seed_job job:baseline-plan-review <<'JSON'
{"job_id":"baseline-plan-review","query":"How should scientific research agents verify claims?","status":"pending_review","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":{"sub_questions":["Which verification architectures are currently used?","How is evidence provenance preserved?","What evaluation methods detect unsupported claims?"],"search_queries":["retrieval augmented claim verification","scientific evidence provenance language models","factuality evaluation research agents"]},"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

seed_job job:baseline-running <<'JSON'
{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?","status":"running","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

seed_job job:baseline-cancelled <<'JSON'
{"job_id":"baseline-cancelled","query":"Compare retrieval strategies for scientific agents","status":"cancelled","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883380.0,"result":null,"error":null,"error_type":null,"cost_usd":0.03,"llm_calls":1,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

seed_job job:baseline-failed-partial <<'JSON'
{"job_id":"baseline-failed-partial","query":"How can ML teams detect unsupported scientific claims?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883400.0,"result":"# Partial briefing\n\nThe run retained an incomplete synthesis before verification failed.\n\n## What remains useful\n\n- Initial retrieval completed.\n- Final claim verification did not complete.","error":"Verification stopped before all claims could be checked.","error_type":"verification_incomplete","cost_usd":0.18,"llm_calls":4,"iterations":1,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

# WO-21. The row a `stream_timeout` frame is delivered against: non-terminal,
# so the stream stays open, and leased below so the redriver leaves it alone.
# The frame itself is injected by `web/e2e/support/intercept.ts`, because a
# real stack emits `stream_timeout` only when the SSE response reaches
# `api_sse_max_duration_sec` — minutes of wall clock, and not on demand.
seed_job job:baseline-stream-timeout <<'JSON'
{"job_id":"baseline-stream-timeout","query":"Which reconnect strategies keep a long research stream honest?","status":"running","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

# WO-21. The failed-with-partial-result job behind the `baseline-partial-export`
# turn above. `error_type` is one of the nine mapped values
# (`web/lib/copy/errors.ts:303`) rather than an invented string, so the copy
# layer renders a real sentence for it.
seed_job job:baseline-partial-export <<'JSON'
{"job_id":"baseline-partial-export","query":"Which verification failures are worth reporting partially?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883440.0,"result":"# Partial briefing (verification incomplete)\n\nThe run retained an incomplete synthesis before verification failed. It is shown because a partial answer the user paid for is not the same thing as no answer (R-14).\n\n## What completed\n\n- Retrieval over the three sub-questions finished.\n- Two of five claims were checked against their sources.\n\n| Stage | Status |\n|---|---|\n| Retrieval | complete |\n| Reading | complete |\n| Verification | stopped |\n\n## What did not\n\nFinal claim verification did not complete, so nothing below the fold was checked and no confidence label is reported.","error":"The briefing could not be assembled from what was read.","error_type":"SynthesizerOutputError","cost_usd":0.21,"llm_calls":6,"iterations":1,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

# WO-21. §4 row 15 — failed with NO result — has no fixture in the Gate 1 set:
# `baseline-failed-partial` carries a report, which is row 14. The two states
# render differently and the reflow sweep needs both. `error_type` is
# `hitl_timeout`, a deliberate backend constant (`src/agents/../runner.py:1057`),
# not an invented string.
seed_job job:baseline-failed <<'JSON'
{"job_id":"baseline-failed","query":"Which planner failures leave nothing to show?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883368.0,"result":null,"error":"The plan was not reviewed within the allowed window.","error_type":"hitl_timeout","cost_usd":0.02,"llm_calls":1,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

# Non-terminal test rows need a lease so the production redriver correctly
# leaves the deliberately synthetic state untouched during the evidence run.
docker exec "$redis_container" redis-cli SET joblease:baseline-plan-review baseline-fixture EX 86400 >/dev/null
docker exec "$redis_container" redis-cli SET joblease:baseline-running baseline-fixture EX 86400 >/dev/null
# WO-21: same rule, same reason, for the new non-terminal row.
docker exec "$redis_container" redis-cli SET joblease:baseline-stream-timeout baseline-fixture EX 86400 >/dev/null

# `baseline-expired` is seeded by its ABSENCE and must stay absent: `?job=`
# outlives the job, and `GET /research/baseline-expired` returning a clean 404
# is what slice step 2 asserts. Deleting it makes re-seeding deterministic
# even if a previous run created it.
docker exec "$redis_container" redis-cli DEL job:baseline-expired >/dev/null

# ---------------------------------------------------------------------------
# WO-W13 — the guided-read session, mid-session.
#
# WHY IT IS SEEDED BEHIND THE API, LIKE EVERYTHING ELSE HERE. The only way to
# reach `awaiting_learner` through the front door is `POST /learn/sessions`,
# which runs the session graph, which calls a model. This stack has no
# reachable provider on purpose (property 4 above), so the state is written
# rather than produced — the same rule as `baseline-plan-review`.
#
# IT IS TWO WRITES, NOT ONE, AND THAT IS THE POINT. `GET /learn/sessions/{id}`
# reads the *job row* for lifecycle and the parked turn, and the *LangGraph
# checkpoint* for the transcript (`src/api/sessions.py:248-262`). WO-W13
# criterion 2 is about the second one: a reload that re-renders the reading
# margin is only evidence if the margin came out of durable checkpointed
# state rather than out of stream frames the browser happened to still hold.
# Seeding only the job row would leave `transcript: []` and the assertion
# would pass against nothing.

seed_job job:baseline-guided-session <<'JSON'
{"job_id":"baseline-guided-session","query":"Guided read: Attention Is All You Need","status":"awaiting_learner","kind":"session","input_payload":{"principal_key_id":"__PRINCIPAL__","tier1":{},"session_spec":{"path_id":"fixture-guided-read","resource_id":"arxiv:1706.03762","title":"Attention Is All You Need","canonical_url":"https://arxiv.org/abs/1706.03762","briefing_companion":"briefings/01-fixture-transformer.md","briefing_label":"Briefing companion","reading_guidance":[{"name":"Introduction","mode":"close"},{"name":"Method","mode":"skim"}],"available_minutes":20,"path_position":1,"path_entry_count":3}},"created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_cap_status":"","cost_cap_message":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":null,"plan":null,"turn":{"turn_number":2,"phase":"passage","kind":"guided_question","prompt":"You have read the Method section. Which connection between self-attention and the older recurrent approach feels least obvious to you?","feedback":"Your opening expectation is saved in the margin below.","activity":{"kind":"guided_question","instructions":"You have read the Method section. Which connection between self-attention and the older recurrent approach feels least obvious to you?"}},"resume_action":null,"resume_plan":null,"resume_payload":null,"principal_key_id":"__PRINCIPAL__"}
JSON

# Non-terminal, so it needs a lease for the same reason the two rows above do.
docker exec "$redis_container" redis-cli SET joblease:baseline-guided-session baseline-fixture EX 86400 >/dev/null

# The durable half. `aupdate_state` writes a checkpoint WITHOUT running a
# node — verified before this was committed — so this reuses the app's own
# graph and its own configured checkpointer instead of hand-writing
# LangGraph's serialised channel rows, and it contacts nothing. `run_id` and
# `turn_number` are set so the snapshot is a coherent session rather than a
# bag of messages; `assessment` carries WO-W06's informal close, which is the
# `recorded_ungraded` state WO-W13 renders as a fact rather than a grade.
#
# THE THREAD IS DELETED FIRST, AND THAT IS WHAT MAKES THIS IDEMPOTENT
# (property 2 at the top of this file). Two things go wrong against an
# already-seeded stack otherwise, and both were observed: `messages` reduces
# with `add_messages`, so a second write APPENDS a second copy of the margin;
# and `aupdate_state` on a thread that already has a checkpoint cannot infer
# which node the update came from and raises `InvalidUpdateError: Ambiguous
# update, specify as_node`. Naming a node would answer the second and not the
# first. Deleting answers both, and leaves exactly one state to write into.
docker exec -i "$app_container" python - <<'PY'
import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from src.graph.session_workflow import build_session_workflow

THREAD = "baseline-guided-session"
MARGIN = [
    AIMessage(
        content=(
            "Before we read Attention Is All You Need, what do you expect it "
            "to help you understand?"
        ),
        name="tutor",
    ),
    HumanMessage(
        content=(
            "I expected attention to replace recurrence as the way a model "
            "relates distant tokens."
        ),
        name="learner",
    ),
    AIMessage(
        content=(
            "Hold on to that. Read section 3.2 and watch for what the paper "
            "claims recurrence cost it."
        ),
        name="tutor",
    ),
]


async def main() -> None:
    workflow = await build_session_workflow(async_checkpointer=True)
    config = {"configurable": {"thread_id": THREAD}}
    await workflow.checkpointer.adelete_thread(THREAD)
    await workflow.aupdate_state(
        config,
        {
            "run_id": THREAD,
            "messages": MARGIN,
            "turn_number": 2,
            "assessment": {"status": "recorded_ungraded"},
        },
    )
    snapshot = await workflow.aget_state(config)
    got = len(snapshot.values.get("messages", []))
    if got != len(MARGIN):
        raise SystemExit(f"checkpoint seed wrote {got} messages, expected {len(MARGIN)}")


asyncio.run(main())
PY


# ---------------------------------------------------------------------------
# WO-W13b. The learner profile the START of a session needs.
#
# `create_session` refuses with 404 `learner_profile_required` when the
# calling principal has no profile (`src/api/sessions.py`), and a profile is
# per-principal by construction (ADR 0058) — there is no default row, and
# inventing one on read would make "the learner has told us nothing" and "the
# learner told us they are a beginner" indistinguishable
# (`src/api/routes.py::get_learner_profile`). WO-W13's session spec never met
# this because it READ a session that was already seeded; WO-W13b's flow spec
# STARTS one, so the record has to exist first.
#
# WRITTEN THROUGH THE STORE, NOT THROUGH `PUT /learn/profile` AND NOT AS
# HAND-WRITTEN SQL. The same argument the checkpoint block above makes: this
# reuses the application's own `build_profile_store()` and its validation, so
# a schema or constraint change fails the seed instead of producing a row the
# API cannot read back. It contacts nothing — one Postgres upsert on the pool
# the stack already has open.
#
# IDEMPOTENT: `put` is an upsert keyed on `principal_key_id`
# (`src/learning/profile_store.py`), so re-seeding is a no-op.
#
# `time_budget_min_per_day` is the fallback `create_session` uses when a
# request omits `available_minutes`. 20 is the figure the seeded
# `baseline-guided-session` spec already carries, so the two fixtures agree.
docker exec -i -e E2E_PRINCIPAL="$principal" "$app_container" python - <<'PY'
import asyncio
import os

from src.learning.profile_store import LearnerProfile, build_profile_store
from src.tools.postgres_pool import close_pool

PRINCIPAL = os.environ["E2E_PRINCIPAL"]


async def main() -> None:
    store = build_profile_store()
    await store.put(
        LearnerProfile(
            principal_key_id=PRINCIPAL,
            academic_level="undergrad",
            time_budget_min_per_day=20,
            profile_note=(
                "Seeded browser-tier learner. Fixture scaffolding for the "
                "end-to-end guided-read run; not a real reader."
            ),
        )
    )
    if await store.get(PRINCIPAL) is None:
        raise SystemExit("learner profile seed wrote nothing")


asyncio.run(main())
# Closed explicitly: the pool's `__del__` cannot join its worker thread at
# interpreter shutdown, which prints a `PythonFinalizationError` traceback
# after a seed that in fact succeeded. A confusing traceback on a green run
# is how people learn to ignore tracebacks.
close_pool()
PY


echo "Seeded baseline-populated, baseline-empty, job:baseline-*, the guided-session checkpoint and the e2e learner profile."

# ---------------------------------------------------------------------------
# WO-W17 — two pilot principals, and one of each thing a pilot has.
#
# ONLY UNDER `E2E_PILOT=1`. Without the pilot overlay the stack issues one
# principal and these rows would be owned by nobody who can read them, which
# is not a fixture, it is litter.
#
# WHAT IS SEEDED, AND WHY EACH ONE. WO-W17 criterion 3 is "two pilot
# principals each see only their own threads/sessions/profile/ledger", so
# there is exactly one row of each of those four kinds per pilot, with a
# distinguishable value in it. The assertion the spec makes is symmetric —
# each pilot sees theirs AND does not see the other's — because a test that
# only checked the first half would pass against a stack that showed
# everything to everyone.
#
# Written behind the API for the same reason everything else here is: the only
# front door to a session is `POST /learn/sessions`, which runs the graph,
# which calls a model. This stack has no reachable provider (property 4).
if [ "${pilot}" = "1" ]; then
  docker exec -i "$postgres_container" psql -v ON_ERROR_STOP=1 \
    -v a="$pilot_a_key_id" -v b="$pilot_b_key_id" -U arxiv -d arxiv <<'SQL'
-- Threads. One each, with a title only its owner may ever see.
INSERT INTO conversations (
  conversation_id, title, created_at, updated_at, principal_key_id
) VALUES (
  'baseline-pilot-a-thread',
  'Pilot A private thread',
  '2026-09-01T09:00:00Z',
  '2026-09-01T09:05:00Z',
  :'a'
), (
  'baseline-pilot-b-thread',
  'Pilot B private thread',
  '2026-09-01T09:10:00Z',
  '2026-09-01T09:15:00Z',
  :'b'
) ON CONFLICT (conversation_id) DO UPDATE SET
  title = EXCLUDED.title,
  updated_at = EXCLUDED.updated_at,
  principal_key_id = EXCLUDED.principal_key_id;

INSERT INTO conversation_jobs (
  conversation_id, job_id, ordinal, query, report, created_at
) VALUES (
  'baseline-pilot-a-thread',
  'baseline-pilot-a-run',
  1,
  'What does pilot A ask about?',
  E'# Pilot A briefing\n\nOnly pilot A may read this.',
  '2026-09-01T09:05:00Z'
), (
  'baseline-pilot-b-thread',
  'baseline-pilot-b-run',
  1,
  'What does pilot B ask about?',
  E'# Pilot B briefing\n\nOnly pilot B may read this.',
  '2026-09-01T09:15:00Z'
) ON CONFLICT (conversation_id, ordinal) DO UPDATE SET
  job_id = EXCLUDED.job_id,
  query = EXCLUDED.query,
  report = EXCLUDED.report,
  created_at = EXCLUDED.created_at;

-- Profiles. `academic_level` differs so a leak is visible rather than
-- inferred; empty `goals`/`skills` keep the row inside every ADR 0058 CHECK
-- without pretending the pilot declared anything.
INSERT INTO learner_profiles (
  principal_key_id, academic_level, time_budget_min_per_day, profile_note
) VALUES (
  :'a', 'grad', 25, 'Pilot A profile note'
), (
  :'b', 'undergrad', 45, 'Pilot B profile note'
) ON CONFLICT (principal_key_id) DO UPDATE SET
  academic_level = EXCLUDED.academic_level,
  time_budget_min_per_day = EXCLUDED.time_budget_min_per_day,
  profile_note = EXCLUDED.profile_note,
  updated_at = NOW();

-- Ledgers. `progress_events` refuses UPDATE outright (WO-W07's append-only
-- trigger), so this is `DO NOTHING` rather than an upsert — which is also
-- what makes re-seeding idempotent here.
INSERT INTO progress_events (
  event_id, principal_key_id, ts, kind, payload, evidence_ref
) VALUES (
  'baseline-pilot-a-event',
  :'a',
  '2026-09-01T09:06:00Z',
  'session_completed',
  '{"session_id": "baseline-pilot-a-session", "minutes": 18}'::jsonb,
  NULL
), (
  'baseline-pilot-b-event',
  :'b',
  '2026-09-01T09:16:00Z',
  'session_completed',
  '{"session_id": "baseline-pilot-b-session", "minutes": 22}'::jsonb,
  NULL
) ON CONFLICT (event_id) DO NOTHING;
SQL

  # Sessions. Parked at `awaiting_learner`, one per pilot, no checkpoint:
  # `src/api/sessions.py::_checkpoint_values` returns an empty transcript for
  # a thread that has none, and criterion 3 is about ownership rather than
  # about rehydration (which `session.spec.ts` already proves).
  seed_job_owned_by job:baseline-pilot-a-session "$pilot_a_key_id" <<'JSON'
{"job_id":"baseline-pilot-a-session","query":"Guided read: pilot A","status":"awaiting_learner","kind":"session","input_payload":{"principal_key_id":"__PRINCIPAL__","tier1":{},"session_spec":{"path_id":"fixture-guided-read","resource_id":"arxiv:1706.03762","title":"Pilot A private session","canonical_url":"https://arxiv.org/abs/1706.03762","reading_guidance":[],"available_minutes":20,"path_position":1,"path_entry_count":1}},"created_at":1788339600.0,"started_at":1788339660.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_cap_status":"","cost_cap_message":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":null,"plan":null,"turn":null,"resume_action":null,"resume_plan":null,"resume_payload":null,"principal_key_id":"__PRINCIPAL__"}
JSON

  seed_job_owned_by job:baseline-pilot-b-session "$pilot_b_key_id" <<'JSON'
{"job_id":"baseline-pilot-b-session","query":"Guided read: pilot B","status":"awaiting_learner","kind":"session","input_payload":{"principal_key_id":"__PRINCIPAL__","tier1":{},"session_spec":{"path_id":"fixture-guided-read","resource_id":"arxiv:1706.03762","title":"Pilot B private session","canonical_url":"https://arxiv.org/abs/1706.03762","reading_guidance":[],"available_minutes":20,"path_position":1,"path_entry_count":1}},"created_at":1788340200.0,"started_at":1788340260.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_cap_status":"","cost_cap_message":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":null,"plan":null,"turn":null,"resume_action":null,"resume_plan":null,"resume_payload":null,"principal_key_id":"__PRINCIPAL__"}
JSON

  # Non-terminal, so both need a lease for the reason the rows above do: the
  # production redriver would otherwise rewrite them to `orphaned` mid-run.
  docker exec "$redis_container" redis-cli SET joblease:baseline-pilot-a-session baseline-fixture EX 86400 >/dev/null
  docker exec "$redis_container" redis-cli SET joblease:baseline-pilot-b-session baseline-fixture EX 86400 >/dev/null

  # The runs behind the two threads, so each thread renders a transcript.
  seed_job_owned_by job:baseline-pilot-a-run "$pilot_a_key_id" <<'JSON'
{"job_id":"baseline-pilot-a-run","query":"What does pilot A ask about?","status":"succeeded","created_at":1788339600.0,"started_at":1788339660.0,"completed_at":1788339700.0,"result":"# Pilot A briefing\n\nOnly pilot A may read this.","error":null,"error_type":null,"cost_usd":0.11,"llm_calls":3,"iterations":1,"quality_score":0.8,"hitl_bypass":false,"conversation_id":"baseline-pilot-a-thread","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

  seed_job_owned_by job:baseline-pilot-b-run "$pilot_b_key_id" <<'JSON'
{"job_id":"baseline-pilot-b-run","query":"What does pilot B ask about?","status":"succeeded","created_at":1788340200.0,"started_at":1788340260.0,"completed_at":1788340300.0,"result":"# Pilot B briefing\n\nOnly pilot B may read this.","error":null,"error_type":null,"cost_usd":0.12,"llm_calls":3,"iterations":1,"quality_score":0.8,"hitl_bypass":false,"conversation_id":"baseline-pilot-b-thread","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":"__PRINCIPAL__"}
JSON

  echo "Seeded the two WO-W17 pilot principals: threads, sessions, profiles and ledgers."
fi
