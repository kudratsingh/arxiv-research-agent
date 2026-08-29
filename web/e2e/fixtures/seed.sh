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
  curl -fsS -o /dev/null "http://localhost:8000/conversations?limit=1" || true

docker exec -i "$postgres_container" psql -v ON_ERROR_STOP=1 -U arxiv -d arxiv <<'SQL'
INSERT INTO conversations (
  conversation_id, title, created_at, updated_at, principal_key_id
) VALUES (
  'baseline-populated',
  'Scientific claim verification',
  '2026-08-28T02:16:02Z',
  '2026-08-28T02:17:04Z',
  NULL
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
  NULL
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

docker exec -i "$redis_container" redis-cli -x SET job:baseline-succeeded <<'JSON'
{"job_id":"baseline-succeeded","query":"How should scientific research agents verify claims?","status":"succeeded","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883424.0,"result":"# Retrieval-Augmented Verification for Scientific Claims\n\n## Executive summary\n\nRecent systems combine retrieval, claim decomposition, and post-generation verification to reduce unsupported statements.\n\n## Findings\n\n- Evidence retrieval works best when queries are decomposed into independently verifiable claims.\n- Verification models should be calibrated separately from generation models.","error":null,"error_type":null,"cost_usd":0.42,"llm_calls":11,"iterations":2,"quality_score":0.86,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

docker exec -i "$redis_container" redis-cli -x SET job:baseline-plan-review <<'JSON'
{"job_id":"baseline-plan-review","query":"How should scientific research agents verify claims?","status":"pending_review","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":{"sub_questions":["Which verification architectures are currently used?","How is evidence provenance preserved?","What evaluation methods detect unsupported claims?"],"search_queries":["retrieval augmented claim verification","scientific evidence provenance language models","factuality evaluation research agents"]},"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

docker exec -i "$redis_container" redis-cli -x SET job:baseline-running <<'JSON'
{"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?","status":"running","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

docker exec -i "$redis_container" redis-cli -x SET job:baseline-cancelled <<'JSON'
{"job_id":"baseline-cancelled","query":"Compare retrieval strategies for scientific agents","status":"cancelled","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883380.0,"result":null,"error":null,"error_type":null,"cost_usd":0.03,"llm_calls":1,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

docker exec -i "$redis_container" redis-cli -x SET job:baseline-failed-partial <<'JSON'
{"job_id":"baseline-failed-partial","query":"How can ML teams detect unsupported scientific claims?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883400.0,"result":"# Partial briefing\n\nThe run retained an incomplete synthesis before verification failed.\n\n## What remains useful\n\n- Initial retrieval completed.\n- Final claim verification did not complete.","error":"Verification stopped before all claims could be checked.","error_type":"verification_incomplete","cost_usd":0.18,"llm_calls":4,"iterations":1,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

# WO-21. The row a `stream_timeout` frame is delivered against: non-terminal,
# so the stream stays open, and leased below so the redriver leaves it alone.
# The frame itself is injected by `web/e2e/support/intercept.ts`, because a
# real stack emits `stream_timeout` only when the SSE response reaches
# `api_sse_max_duration_sec` — minutes of wall clock, and not on demand.
docker exec -i "$redis_container" redis-cli -x SET job:baseline-stream-timeout <<'JSON'
{"job_id":"baseline-stream-timeout","query":"Which reconnect strategies keep a long research stream honest?","status":"running","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":null,"result":null,"error":null,"error_type":null,"cost_usd":null,"llm_calls":null,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

# WO-21. The failed-with-partial-result job behind the `baseline-partial-export`
# turn above. `error_type` is one of the nine mapped values
# (`web/lib/copy/errors.ts:303`) rather than an invented string, so the copy
# layer renders a real sentence for it.
docker exec -i "$redis_container" redis-cli -x SET job:baseline-partial-export <<'JSON'
{"job_id":"baseline-partial-export","query":"Which verification failures are worth reporting partially?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883440.0,"result":"# Partial briefing (verification incomplete)\n\nThe run retained an incomplete synthesis before verification failed. It is shown because a partial answer the user paid for is not the same thing as no answer (R-14).\n\n## What completed\n\n- Retrieval over the three sub-questions finished.\n- Two of five claims were checked against their sources.\n\n| Stage | Status |\n|---|---|\n| Retrieval | complete |\n| Reading | complete |\n| Verification | stopped |\n\n## What did not\n\nFinal claim verification did not complete, so nothing below the fold was checked and no confidence label is reported.","error":"The briefing could not be assembled from what was read.","error_type":"SynthesizerOutputError","cost_usd":0.21,"llm_calls":6,"iterations":1,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
JSON

# WO-21. §4 row 15 — failed with NO result — has no fixture in the Gate 1 set:
# `baseline-failed-partial` carries a report, which is row 14. The two states
# render differently and the reflow sweep needs both. `error_type` is
# `hitl_timeout`, a deliberate backend constant (`src/agents/../runner.py:1057`),
# not an invented string.
docker exec -i "$redis_container" redis-cli -x SET job:baseline-failed <<'JSON'
{"job_id":"baseline-failed","query":"Which planner failures leave nothing to show?","status":"failed","created_at":1787883362.0,"started_at":1787883364.0,"completed_at":1787883368.0,"result":null,"error":"The plan was not reviewed within the allowed window.","error_type":"hitl_timeout","cost_usd":0.02,"llm_calls":1,"iterations":null,"quality_score":null,"hitl_bypass":false,"conversation_id":"baseline-populated","plan":null,"resume_action":null,"resume_plan":null,"principal_key_id":null}
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

echo "Seeded baseline-populated, baseline-empty, and job:baseline-* local fixtures."
