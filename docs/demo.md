# Demo — example run

The workflow's shape end-to-end, across the three surfaces it ships
on: the CLI, the HTTP API, and the browser workbench. One benchmark
query, the report the system produces from it, the wire traffic the
API emits while producing it, and the per-query line the eval runner
writes to `summary.jsonl` when the query lands in the nightly
benchmark.

The query below is `hallucination-mitigation` from
[`src/eval/benchmark_queries.py`](../src/eval/benchmark_queries.py) —
the canonical smoke query for the benchmark. It's well-covered by the
built-in mock paper set (`src/agents/search.py::MOCK_PAPERS`), so
this example can be reproduced with `USE_MOCK_DATA=true` and no live
arXiv *search*. It is not a network-free run: see
[What `USE_MOCK_DATA=true` does and does not skip](#what-use_mock_datatrue-does-and-does-not-skip)
below. Live-arXiv runs produce reports of the same shape against
fresher papers; the metrics on those runs live under
`outputs/eval/<run_id>/` and roll up into the nightly regression
diff.

## Provenance of everything on this page

Different blocks below were obtained different ways, and the
difference matters — one of them is a measurement and two of them are
not. Stated up front rather than left to inference:

| Block | Where it came from | Trust it for |
|---|---|---|
| [Report body](#report-body) + [citation list](#citation-list) | Captured from a `USE_MOCK_DATA=true` run when this page was written (2026-07-09, `0911ef0`) and **not re-captured since**; the retrieval and degradation paths have changed under it (ADRs 0041, 0052) | Shape, structure, citation style. The five citations still match `MOCK_PAPERS` exactly — that is checked. The prose is representative, not current. |
| [`summary.jsonl` line](#summaryjsonl-line) | **Hand-written.** The field names, order and types are verified against `src/eval/runner.py::_summary_line`; the *values* are illustrative | The schema. Not the numbers. |
| [HTTP + SSE samples](#the-same-run-over-the-http-api) | **Recorded off the wire** from the seeded local Compose stack with `ANTHROPIC_API_KEY=local-preview-disabled`, and committed under [`web/contract/`](../web/contract/). Each fixture carries its own `x-recording` header saying whether the bytes were observed or transcribed | Field names, framing, ordering, status codes. |

No number on this page is a benchmark result. **No eval campaign has
ever completed** — the nightly workflow has failed on a missing
`ANTHROPIC_API_KEY` secret every night since it landed, so there is no
`summary.jsonl` in CI and the README's results block still reads
`(pending)`. See [`docs/eval.md`](eval.md#status-no-green-campaign-yet).

## Query

```
What are the latest approaches to reducing hallucination in large
language models?
```

Domain: `hallucination`. Expected topics the eval scores against:
`retrieval-augmented generation`, `chain-of-verification`,
`self-consistency`, `fine-tuning for factuality`, `post-hoc
verification`. Full record:
[`src/eval/benchmark_queries.py`](../src/eval/benchmark_queries.py).

## Invocation — the CLI

Built-in mock papers, no live arXiv search (but see the note below —
the reader still fetches the five mock papers' PDFs on a cold cache):

```bash
USE_MOCK_DATA=true python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

Fixed pipeline. To exercise the supervisor loop with the verifier and
the evidence store, layer on the flags from ADRs 0014–0016:

```bash
USE_MOCK_DATA=true \
ENABLE_SUPERVISOR=true \
ENABLE_VERIFIER=true \
ENABLE_EVIDENCE_STORE=true \
python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

### What `USE_MOCK_DATA=true` does and does not skip

This page used to call the mock-data run "offline, no external API
calls beyond Anthropic". That was wrong, and ADR 0052 corrects it.
`USE_MOCK_DATA=true` replaces the *search* step only: the planner's
queries never reach arXiv's Atom feed, and `MOCK_PAPERS` is returned
instead. But every entry in `MOCK_PAPERS` carries a real `pdf_url` on
`arxiv.org` (`src/agents/search.py`), and the reader's job is to read
full text — so the fan-out calls `parse_pdf` on all five, and on a
cold cache that is **five real PDF downloads from arxiv.org**,
roughly 5–10 MB.

A cold mock-data run therefore talks to exactly two external hosts:

| Host | When | Skippable |
| --- | --- | --- |
| `api.anthropic.com` | Every node that calls the LLM | No — the workflow is the LLM |
| `arxiv.org` (`/pdf/...` ×5) | Reader fan-out, cold cache only | Yes — warm the cache once (below) |
| `export.arxiv.org` (search) | Live search | Yes — that is what `USE_MOCK_DATA` skips |

**The genuinely network-free-except-Anthropic run is the second one.**
`parse_pdf` caches extracted text through the `PaperCache`
(`.cache/pdfs/<key>.txt` on the default disk backend, ADR 0028), keyed
by arXiv ID, and the mock set is fixed — so once a first run has
populated it, every later `USE_MOCK_DATA=true` run on this query hits
the cache and issues no arXiv request at all:

```bash
# 1. Warm run: 5 PDF downloads from arxiv.org + Anthropic.
USE_MOCK_DATA=true python -m src.main "…"

# 2. Every run after this one: Anthropic only. The five extracted
#    texts come from .cache/pdfs/. `make clean` removes that cache
#    (it is re-derivable); `make clean-all` also removes the graph
#    checkpoints.
USE_MOCK_DATA=true python -m src.main "…"
```

There is deliberately **no `--no-pdf` switch**, and none of the
existing knobs is a usable substitute: `READER_MAX_CHUNKS_PER_PAPER`
is bounded `ge=1` and `PDF_MAX_BYTES` is bounded `ge=1MB`, so neither
can be turned down to "skip the fetch", and the second would abort
mid-download after the request had already gone out. If the reader
gets no full text it degrades to the abstract — that path is real and
now logs a `reader_paper_abstract_only` line per paper plus a
run-level summary (ADR 0052) — but the only supported way to reach it
without a network call is the warm cache above.

## Report body

Written by the synthesizer, scored by the critic, and (with the
verifier flag on) checked against the evidence-store excerpts before
being handed to the critic. `[Author, Year]` citations are inline,
citation list follows.

```markdown
# Reducing Hallucination in Large Language Models

Hallucination — LLM output that is nonsensical or unfaithful to the
provided source — is one of the primary quality risks in deploying
generative models. Recent work groups mitigation approaches into three
temporal categories: training-time, generation-time, and post-hoc
correction methods [Ji, 2023].

## Training-time approaches

Reinforcement Learning from Human Feedback (RLHF) is the dominant
training-time technique, and recent extensions target hallucination
specifically. RLHF-V collects **fine-grained correctional feedback
targeting specific hallucinated segments**, rather than holistic
preference labels, and optimizes a dense direct-preference objective
against those annotations. On image captioning benchmarks, RLHF-V
reduces hallucination rates by 34.8% relative to the base model while
preserving helpfulness [Yu, 2024].

## Generation-time approaches

Retrieval-Augmented Generation (RAG) grounds output in retrieved
documents to reduce factual hallucination. The canonical RAG
formulation combines a parametric generator with a non-parametric
dense retriever over a corpus like Wikipedia, achieving
state-of-the-art results on open-domain QA benchmarks and reducing
factual hallucinations relative to purely parametric models
[Lewis, 2020].

Self-RAG extends this by training a single model to adaptively decide
when retrieval is necessary and reflect on its own output. The
resulting system outperforms both vanilla LLMs and fixed RAG pipelines
across six tasks including fact verification and open-domain QA,
improving factuality by 20-30% while maintaining generation fluency
[Asai, 2023].

Chain-of-Verification (CoVe) is an in-loop verification technique that
requires no external tools: the model first drafts a response, plans
verification questions, answers those questions independently, then
generates a revised response. CoVe reduces hallucination rates by
30-50% across model sizes on list-based questions, closed-book QA, and
long-form generation, with larger models benefiting more from the
self-verification process [Dhuliawala, 2023].

## Post-hoc approaches

Post-hoc verification techniques operate on generated output rather
than during generation, and include self-consistency checking,
external knowledge verification, and citation-based validation
[Ji, 2023]. These approaches tend to add latency in exchange for
higher factuality guarantees.

## Comparing the three approaches

| Approach | Training cost | Inference cost | Scope |
|---|---|---|---|
| RLHF-V | High (fine-tuning) | Low | Model-wide |
| RAG / Self-RAG | Medium (retriever training) | Medium (retrieval hop) | Per-query |
| CoVe | None | High (multi-pass) | Per-response |
| Post-hoc verification | None | High | Per-response |

Training-time methods amortize their cost across every future
inference; generation- and post-hoc-time methods pay per-response but
require no model changes. Multimodal work has largely piggy-backed on
these three categories, with fine-grained feedback (as in RLHF-V) the
most-cited recent innovation.

## Key Takeaways

- Modern mitigation strategies fall into three temporal categories,
  each with distinct cost-quality tradeoffs.
- Retrieval-based grounding (RAG, Self-RAG) is the most-deployed
  approach at inference time.
- In-loop self-verification (CoVe) achieves 30-50% hallucination
  reduction without external tools.
- Fine-grained corrective feedback (RLHF-V) outperforms holistic
  preference labels for training-time mitigation.

## Open Questions

- Direct comparison of self-verification vs. retrieval-augmentation
  under matched compute is missing from the surveyed work.
- Whether CoVe-style verification generalizes to multi-modal settings
  is not yet shown.
- Long-tail factual claims (rare entities, specialized domains)
  remain the hardest hallucination category across all approaches.
```

### Citation list

The synthesizer's `citations` field, machine-readable, gets serialized
alongside the report body:

```json
[
  {
    "paper_id": "http://arxiv.org/abs/2311.09000",
    "title": "A Survey on Hallucination in Large Language Models",
    "authors": ["Ziwei Ji", "Nayeon Lee", "Rita Frieske", "Tiezheng Yu"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2311.09000"
  },
  {
    "paper_id": "http://arxiv.org/abs/2305.13269",
    "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus"],
    "year": "2020",
    "url": "http://arxiv.org/abs/2305.13269"
  },
  {
    "paper_id": "http://arxiv.org/abs/2310.01377",
    "title": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
    "authors": ["Akari Asai", "Zeqiu Wu", "Yizhong Wang", "Avirup Sil"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2310.01377"
  },
  {
    "paper_id": "http://arxiv.org/abs/2309.11495",
    "title": "Chain-of-Verification Reduces Hallucination in Large Language Models",
    "authors": ["Shehzaad Dhuliawala", "Mojtaba Komeili", "Jing Xu"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2309.11495"
  },
  {
    "paper_id": "http://arxiv.org/abs/2401.01313",
    "title": "RLHF-V: Towards Trustworthy MLLMs via Behavior Alignment from Fine-grained Correctional Human Feedback",
    "authors": ["Tianyu Yu", "Yuan Yao", "Haoye Zhang", "Taiwen He"],
    "year": "2024",
    "url": "http://arxiv.org/abs/2401.01313"
  }
]
```

## The same run over the HTTP API

The CLI invocation above is the shortest path to a report. The
production surface is the FastAPI job API
([`docs/architecture.md`](architecture.md) has the job model; the
committed OpenAPI document is
[`web/contract/openapi.json`](../web/contract/openapi.json)). Ten
operations across eight paths, of which five matter to a single
research run:

| Method | Path | What it does |
|---|---|---|
| `POST` | `/research` | Accept a query. **202**, not 200 — the work runs in the background. |
| `GET` | `/research/{job_id}` | Full lifecycle snapshot, including the report body once it exists. |
| `GET` | `/research/{job_id}/stream` | SSE stream of workflow events. |
| `POST` | `/research/{job_id}/review` | Resolve a `pending_review` job: `approve`, `revise`, or `cancel`. |
| `GET` | `/research/{job_id}/export?format=md\|pdf\|docx` | Download the report. |

The remaining five are `/healthz` and the four `/conversations`
routes (create, list, fetch, delete) that thread follow-up queries
together. There is **no `/readyz`** and no metrics route on the HTTP
app — `/healthz` carries the dependency pings and always returns 200,
because restarting the process does not fix a dead Redis (ADR 0042).

### Submit

```bash
curl -sS -X POST http://localhost:8000/research \
  -H 'content-type: application/json' \
  -d '{"query": "What are the latest approaches to reducing hallucination in large language models?"}'
```

```json
{"job_id": "2f8c1a9b7d4e6035", "status": "pending", "status_url": "/research/2f8c1a9b7d4e6035", "stream_url": "/research/2f8c1a9b7d4e6035/stream"}
```

`hitl_bypass: true` skips the plan-review pause for programmatic
callers; `conversation_id` runs the query as a follow-up, prepending
retrieved chunks of the earlier reports to the planner's prompt (ADR
0032). Under `ENABLE_API_AUTH=true` the route needs `X-API-Key` and
is the **only** rate-limited route — reads cost no LLM dollars (ADRs
0033, 0037).

### Watch it run

```
GET /research/{job_id}/stream
```

Eight event names, and the list is the contract clients code against
(`src/api/streaming.py`). There is deliberately no `node_started` —
the runner only emits after a node returns.

| Event | Payload | Terminal |
|---|---|---|
| `job_started` | `{job_id, query}` | no |
| `node_completed` | `{node, state_delta}` — scalars only; the papers/citations lists are fetched from `GET /research/{job_id}` instead, so frames stay small | no |
| `plan_ready` | `{job_id, plan: {sub_questions, search_queries}}` — the HITL breakpoint. **Not terminal**: the stream stays open through the review and the resumed nodes | no |
| `turn_ready` | `{job_id, turn}` — the guided-session pause (ADR 0057), `plan_ready`'s counterpart for a `kind="session"` job. **Not terminal**: the stream stays open across the learner's reply. The payload is a pause *signal*; a client reads the turn and the transcript from `GET /learn/sessions/{session_id}`, which is what makes a live turn and a reloaded one render identically | no |
| `job_completed` | `{job_id, iterations, quality_score, cost_usd, llm_calls, elapsed_sec}` | yes |
| `job_failed` | `{job_id, error, error_type, elapsed_sec}` | yes |
| `job_cancelled` | `{job_id, elapsed_sec}`, plus `reason` when a HITL `cancel` caused it | yes |
| `stream_timeout` | `{job_id, reason, max_duration_sec, reconnect}` — emitted by the *server*, never the runner. The job is still running; reconnect to the same URL | no (closes the connection) |

**The report body never arrives over SSE.** `job_completed` carries
the run's scalars only; a client reads `result` from
`GET /research/{job_id}` after the terminal frame. Heartbeats are SSE
comment frames (`: heartbeat`), invisible to `EventSource`, which is
why the browser client also polls the job while it is non-terminal.

A success stream, re-encoded into SSE wire form from
[`web/contract/sse/live_success.jsonl`](../web/contract/sse/live_success.jsonl).
Read that fixture's own `x-recording` header before quoting it
elsewhere: the framing, ordering, heartbeats and close behavior were
recorded off a real socket against the seeded stack, but the payload
*values* were transcribed from the runner's emit sites and published
through the store — because `POST /research` is exactly what the cost
boundary forbids, so no runner could have produced them.

```
: heartbeat

event: job_started
data: {"job_id":"baseline-running","query":"What evaluation methods make research agents reliable?"}

event: node_completed
data: {"node":"planner","state_delta":{"iteration":0,"sub_questions_count":3}}

event: node_completed
data: {"node":"searcher","state_delta":{"iteration":1,"papers_found":9,"tried_search_queries_count":3}}

event: node_completed
data: {"node":"synthesizer","state_delta":{"iteration":1,"report_chars":5140}}

event: job_completed
data: {"cost_usd":0.42,"elapsed_sec":74.0,"iterations":2,"job_id":"baseline-running","llm_calls":11,"quality_score":0.86}
```

Reconnecting to an already-terminal job replays one frame and closes,
which is what makes reconnects idempotent. That replay frame is a
slightly different shape — it adds `status` and drops `llm_calls` —
and it is one of the fixtures that *was* observed end to end
([`web/contract/sse/replay_terminal.jsonl`](../web/contract/sse/replay_terminal.jsonl),
`authored: false`).

### The HITL pause

Plan review is **on by default** (`ENABLE_HITL=true`): unless the
request sets `hitl_bypass`, the graph interrupts after the planner.
Programmatic callers pass `hitl_bypass: true`; the eval runner takes a
different route and compiles the graph with
`build_workflow(enable_hitl=False)` so a nightly benchmark cannot
stall on a human.

At the breakpoint the job moves to `pending_review`, `plan_ready` goes
out on the stream, and `GET /research/{job_id}` starts returning the
plan (abridged from
[`web/contract/fixtures/job.pending_review.json`](../web/contract/fixtures/job.pending_review.json)):

```json
{
  "job_id": "baseline-plan-review",
  "status": "pending_review",
  "query": "How should scientific research agents verify claims?",
  "result": null,
  "cost_usd": null, "llm_calls": null, "iterations": null, "quality_score": null,
  "plan": {
    "sub_questions": [
      "Which verification architectures are currently used?",
      "How is evidence provenance preserved?",
      "What evaluation methods detect unsupported claims?"
    ],
    "search_queries": [
      "retrieval augmented claim verification",
      "scientific evidence provenance language models",
      "factuality evaluation research agents"
    ]
  },
  "conversation_id": "baseline-populated"
}
```

Resolve it with one of three actions (ADR 0030):

```bash
curl -sS -X POST http://localhost:8000/research/$JOB/review \
  -H 'content-type: application/json' \
  -d '{"action": "approve"}'
```

- `approve` — resume as planned.
- `revise` — resume with an edited plan; `plan` is required, and both
  lists are bounded at 20 items x 500 chars, because each search query
  costs one arXiv call plus a hard 3-second politeness sleep (ADR
  0042).
- `cancel` — abandon the run; the job goes to `cancelled`.

**A 200 here does not mean "resumed".** `ReviewResponse.status` is the
status at the moment the review was *accepted* — always
`pending_review`. The resume is asynchronous, so clients poll the job
or watch the stream for the settled outcome. Reviewing a job that is
not paused is a 409:

```json
{"detail": "job_not_awaiting_review (status=running)"}
```

A job nobody reviews does not wait forever: after
`API_HITL_TIMEOUT_SEC` (default 1800, i.e. 30 minutes) the runner
gives up and fails it with `error_type=hitl_timeout`.

### The finished job, and exporting it

```json
{
  "job_id": "baseline-succeeded",
  "status": "succeeded",
  "query": "How should scientific research agents verify claims?",
  "created_at": 1787883362.0, "started_at": 1787883364.0, "completed_at": 1787883424.0,
  "elapsed_sec": 60.0,
  "result": "# Retrieval-Augmented Verification for Scientific Claims\n\n## Executive summary\n…",
  "error": null, "error_type": null,
  "cost_usd": 0.42, "llm_calls": 11, "iterations": 2, "quality_score": 0.86,
  "plan": null,
  "conversation_id": "baseline-populated"
}
```

(Abridged from the recorded
[`web/contract/fixtures/job.succeeded.json`](../web/contract/fixtures/job.succeeded.json)
— only `result` is truncated. `quality_score` is the in-workflow
critic's score, the same number `summary.jsonl` records as
`critic_score`; `iterations` is critic revisions used. Both are `null`
until the run produces them, which is why the browser's metrics strip
renders a dash rather than a zero.)

Three export formats (ADR 0031), one route, one query parameter:

| `format` | Media type | Filename |
|---|---|---|
| `md` | `text/markdown; charset=utf-8` | `research-<job_id>.md` |
| `pdf` | `application/pdf` | `research-<job_id>.pdf` |
| `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `research-<job_id>.docx` |

Every response is `Content-Disposition: attachment` and
`Cache-Control: no-store`. A job with no report body yet is a 409, not
an empty file.

## The same run in the browser

The web UI is the **Evidence Workbench** — the surface the frontend
revamp landed (Direction A; campaign index at
[`docs/revamp/STATUS.md`](revamp/STATUS.md)). Same API, same job
model; the browser just makes the trace legible. The README owns the
screenshots — this is the walkthrough.

The browser never calls the API directly. Every request goes to the
Next.js app's own `/api/<...>` route handler, which forwards to
`API_INTERNAL_BASE` (`http://app:8000` under Compose) and injects the
`X-API-Key` header server-side — so the key is never in client
JavaScript. It streams the upstream response body through unchanged,
which is what keeps SSE and file downloads working.

1. **Compose.** The landing route `/` is a single composer over a
   `max-w-3xl` column. Submitting creates a thread
   (`POST /conversations`) and then the run (`POST /research`), and
   hands off to `/c/<thread_id>?job=<job_id>`. Submission is guarded
   at three levels against a double-charge, and it is deliberately
   kept out of the mutation-retry layer — a retried research POST is
   a second paid run.
2. **Watch, on the trace spine.** The run panel renders a four-segment
   spine — *Question → Plan → Run → Report* — where each segment
   carries a mark for what the client actually observed:
   `observed`, `live`, `not-observed`, `awaiting-review`, `complete`,
   `failed`, `cancelled`, `unavailable`. `node_completed` frames land
   in a checkpoint ledger under the "Run" segment. The distinction the
   spine is built around is *observed* versus *inferred*: a client
   that attached late did not see the earlier nodes, and the dashed
   void says so rather than pretending.
3. **Review the plan.** On `plan_ready` the panel swaps in the plan
   editor: the sub-questions and search queries as editable fields,
   with **Approve plan**, **Save edits and approve**, and **Cancel
   this run**. A 409 from the review route (someone else resolved it,
   or it timed out) surfaces as a *stale* state that refetches rather
   than a dead form.
4. **Read the briefing.** The finished report renders as a *briefing*
   with a section rail built from its own headings, and a metrics
   strip showing exactly the five job fields: `iterations`,
   `quality_score`, `cost_usd`, `llm_calls`, `elapsed_sec`. A field
   the run did not report renders as an em dash with "not reported",
   never as a zero.
5. **Export.** The export control is a disclosure over three plain
   download links — Markdown, PDF, Word — hitting the same
   `/research/{job_id}/export` route. It renders whenever there is a
   briefing body, including on a failed run that retained a partial
   one, and disappears entirely when there is nothing to export.

### Driving it with no API key at all

The whole stack runs against canned data with a deliberately invalid
key, which is how the Playwright + axe tier runs in CI. The manual is
[`web/e2e/README.md`](../web/e2e/README.md):

```bash
cd web
npm run e2e:stack:up      # compose up --build --wait, ANTHROPIC_API_KEY=local-preview-disabled
npm run e2e:stack:seed    # idempotent baseline-* fixtures, written straight into Postgres + Redis
# browse http://127.0.0.1:13210 — e.g. /c/baseline-populated?job=baseline-plan-review
npm run e2e:stack:down
```

Seeded jobs cover the states this page describes and several it does
not: `baseline-succeeded`, `baseline-plan-review`, `baseline-running`,
`baseline-cancelled`, `baseline-failed`, `baseline-failed-partial`,
`baseline-partial-export`, `baseline-stream-timeout`, and
`baseline-expired` (seeded *by its absence*, so the route 404s
cleanly).

Three independent mechanisms keep this tier off a paid path, because
one would be a convention rather than a boundary: the Compose overlay
pins the disabled key on the app service, the Playwright config
overwrites it in the runner process and refuses to start if it is
anything else, and the browser fixture fulfils `POST /api/research`
so the submit leg never reaches the backend at all. The seed script
writes *behind* the API, straight into Postgres and Redis — there is
no code path from the seeded stack to a model.

**Always go through `web/e2e/support/stack.sh`** (which the npm
scripts do). `docker-compose.yml` hardcodes container names, and a
container name is global to the Docker daemon rather than scoped to
the Compose project — a bare `docker compose down` from the repo root
will take down somebody else's stack. `E2E_COMPOSE_PROJECT`,
`E2E_WEB_PORT` and `E2E_APP_PORT` override the defaults.

## `summary.jsonl` line

One line per query, written by
[`src/eval/runner.py::_summary_line`](../src/eval/runner.py) after
scoring the report. Field names, order and types match that function
exactly; **the values are illustrative**, for the reason given in
[Provenance](#provenance-of-everything-on-this-page).

```json
{"query_id": "hallucination-mitigation", "elapsed_sec": 42.7, "scoring_sec": 21.3, "error": null, "metrics_error": null, "citation_accuracy": 1.00, "completeness": 0.85, "faithfulness": 0.92, "retrieval_recall": 0.80, "total_citations": 5, "critic_score": 0.82, "iterations": 1, "cost_usd": 0.087, "llm_calls": 8, "judge_cost_usd": 0.031, "judge_llm_calls": 3, "total_cost_usd": 0.118, "loop_iterations": 0, "stop_reason": ""}
```

Field-by-field:

| Field | Value | Source |
|---|---|---|
| `query_id` | `hallucination-mitigation` | `benchmark_queries.py` |
| `elapsed_sec` | 42.7 | workflow wall-clock, runner |
| `scoring_sec` | 21.3 | wall-clock of the metric judges (ADR 0050) |
| `error` / `metrics_error` | `null` | populated when the workflow / a metric judge failed; a judge failure leaves its metric `null` and keeps the run (ADR 0050) |
| `citation_accuracy` | 1.00 | regex + citation-list join |
| `completeness` | 0.85 | batched LLM judge over `expected_topics` (ADR 0006) |
| `faithfulness` | 0.92 | per-claim LLM judge vs. abstracts (ADR 0007) |
| `retrieval_recall` | 0.80 | LLM judge over the retrieved paper set (ADR 0013) |
| `total_citations` | 5 | citation-accuracy denominator, surfaced for the README block's exclusion rule (ADR 0050) |
| `critic_score` | 0.82 | in-workflow critic average |
| `iterations` | 1 | critic revisions used (0 = no revision, capped by `max_iterations`) |
| `cost_usd` | 0.087 | the **workflow's** spend only (ADR 0012; split from judge spend by ADR 0050) |
| `llm_calls` | 8 | planner + 5 reader (per paper) + synthesizer + critic |
| `judge_cost_usd` / `judge_llm_calls` | 0.031 / 3 | the scoring judges' own spend (completeness + faithfulness + retrieval recall; citation accuracy is regex-only) |
| `total_cost_usd` | 0.118 | workflow + judges — what the benchmark query cost to run |
| `loop_iterations` | `0` | supervisor loop was off; positive under `enable_supervisor` |
| `stop_reason` | `""` | see above |

**`loop_iterations` and `stop_reason` are `0` and `""`, not `null`.**
The runner seeds every `ResearchState` key before invoking the graph
(`src/eval/runner.py::_initial_state`, matching
`src/graph/state.py::initial_state`) and `_serialize_state` keeps all
of them, so the two supervisor fields carry their type's zero value on
a fixed-pipeline run rather than being absent. A `null` in either
position would mean the *state itself* was missing — an errored query,
where `_summary_line` reads an empty dict.

At `enable_supervisor=true, enable_verifier=true,
enable_evidence_store=true`, both populate. The fields that move
(everything else is as above):

```json
{"query_id": "hallucination-mitigation", "elapsed_sec": 58.3, "citation_accuracy": 1.00, "completeness": 0.88, "faithfulness": 0.95, "retrieval_recall": 0.80, "critic_score": 0.85, "iterations": 1, "cost_usd": 0.142, "llm_calls": 14, "loop_iterations": 9, "stop_reason": "quality_reached"}
```

Higher cost (loop tax + verifier call), slightly higher faithfulness
+ completeness, `stop_reason` bucketed for downstream analysis. It is
one of `quality_reached`, `budget_reached`, `max_iterations_reached`
or `supervisor_stop` — the last being the fallback the parser
substitutes when the supervisor stops without naming a reason
(`src/agents/supervisor.py`). Full per-query `summary.jsonl` format
documented in [`docs/eval.md`](eval.md).

## Where the artifacts live

The eval runner writes a layered artifact per benchmark invocation:

```
outputs/eval/<run_id>/
    queries/<query_id>.json    # full per-query record (state + costs + metrics + trace)
    summary.jsonl              # machine-readable one-line-per-query rollup
    summary.md                 # human-readable table + aggregates
```

The nightly CI workflow
([`.github/workflows/eval-nightly.yml`](../.github/workflows/eval-nightly.yml))
runs the benchmark and uploads three artifacts, all under
`if: always()` so a truncated campaign still leaves its paid records
behind: `eval-run-<run_id>` (the whole directory above),
`eval-summary-latest` (`summary.jsonl` alone, overwritten each night —
this is what the *next* night diffs against), and
`regression-report-<run_id>` (the markdown diff). The diff itself is
[`src/eval/regression_diff.py`](../src/eval/regression_diff.py), and
it gates two metric classes differently:

- **Score metrics** (`citation_accuracy`, `completeness`,
  `faithfulness`, `retrieval_recall`, `critic_score`) — an absolute
  drop greater than `--threshold`, default `0.10`.
- **Resource metrics** (`iterations`, `llm_calls`, `cost_usd`) — a
  rise past **both** an absolute floor and a relative band: `+1` /
  `+50%` for `iterations`, `+4` / `+25%` for `llm_calls`, `+$0.10` /
  `+25%` for `cost_usd`. Both legs must be exceeded, so one extra
  critic revision or a two-cent wiggle cannot fail the nightly.

A baseline query missing from the current run is also a regression
(ADR 0050) unless `--allow-removed` is passed, which the nightly only
does on a deliberate `--queries` dispatch. See ADRs
[0008](decisions/0008-eval-runner-sequential-per-query-isolation.md),
[0010](decisions/0010-nightly-eval-ci.md) and
[0044](decisions/0044-eval-cost-accuracy-and-regression-thresholds.md).

None of this has run yet against real data — the workflow has never
got past its `ANTHROPIC_API_KEY` preflight. See
[`docs/eval.md`](eval.md#status-no-green-campaign-yet).

## Reproducing this demo

Four ways in, in ascending order of what they cost you. Only the
first is free.

**No key, canned data — the seeded stack.** The whole UI, every job
state, and no path to a model. This is the tier CI runs; see
[Driving it with no API key at all](#driving-it-with-no-api-key-at-all)
above.

Everything below spends real Anthropic credits.

**One report, mock papers — the CLI:**

```bash
# mock papers, no live search; the five mock PDFs are fetched from
# arxiv.org on a cold .cache/pdfs and served from it afterwards —
# see "What USE_MOCK_DATA=true does and does not skip" above
USE_MOCK_DATA=true python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

The single-query runner prints the report to stdout and saves it under
`outputs/report_<timestamp>.md`.

**One report, through the API and the workbench:** `docker compose up`
brings up app + web + Redis + Postgres, binding the API to
`127.0.0.1:8000` and the workbench to `127.0.0.1:3000`. Real jobs, real
spend — this is the demo, not a test tier.

**Scored metrics — the batch runner.** To get the metrics row instead
of just a report, use the batch runner with a filtered query set:

```bash
# metrics-scored run against the single benchmark query
python -m src.eval.runner --queries hallucination-mitigation
# writes outputs/eval/<run_id>/{queries/,summary.jsonl,summary.md}
```

The full 20-query benchmark runs sequentially and spends real
Anthropic credits — a few dollars on the base Sonnet configuration,
less with Sprint 3's Haiku routing + prompt caching. Cap a campaign
with `--max-budget-usd` and see [`docs/eval.md`](eval.md) for the
run-book (resume, exit codes, and the workflow-vs-judge cost split
in `summary.jsonl`).
