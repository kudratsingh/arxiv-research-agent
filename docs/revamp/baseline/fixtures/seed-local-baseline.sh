#!/usr/bin/env bash

# Local-only Gate 1 evidence fixture. This writes only the two fixed
# `baseline-*` conversations below and `job:baseline-*` Redis keys in the
# repository's disposable Docker Compose stack. It never invokes the research
# endpoint or a model provider.

set -euo pipefail

postgres_container="${BASELINE_POSTGRES_CONTAINER:-arxiv-research-agent-postgres}"
redis_container="${BASELINE_REDIS_CONTAINER:-arxiv-research-agent-redis}"

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

# Non-terminal test rows need a lease so the production redriver correctly
# leaves the deliberately synthetic state untouched during the evidence run.
docker exec "$redis_container" redis-cli SET joblease:baseline-plan-review baseline-fixture EX 86400 >/dev/null
docker exec "$redis_container" redis-cli SET joblease:baseline-running baseline-fixture EX 86400 >/dev/null

echo "Seeded baseline-populated, baseline-empty, and job:baseline-* local fixtures."
