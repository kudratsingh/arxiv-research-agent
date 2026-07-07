# 0013. Finish Sprint 1: shared HTTP retry, SQLite checkpointing, OTel tracing, retrieval recall, expanded benchmark

- **Status**: accepted
- **Date**: 2026-07-07

## Context

Sprint 1's roadmap called out five reliability/observability/evaluation
items still open after the observability core (ADR 0012) landed:

1. HTTP retry / backoff on the two outbound-request paths that aren't
   the Anthropic SDK — arXiv API search and PDF downloads.
2. LangGraph SqliteSaver checkpointing so an interrupted run can be
   resumed by re-invoking with the same `thread_id`.
3. OpenTelemetry tracing per agent node so a run can be inspected in
   any OTLP-compatible backend.
4. Retrieval recall metric to separate search-quality regressions from
   report-generation regressions.
5. Expanding the benchmark from 10 to 20 queries for broader domain
   coverage.

Per the PR-size preference established with the observability core PR,
these five items ship as one cohesive bundle rather than five nano-PRs.

## Decisions

### 1. `urllib3.util.Retry` via a shared `requests.Session` factory

`src/tools/http_session.py::build_retrying_session()` returns a
`requests.Session` with an `HTTPAdapter` mounted on both `http://` and
`https://` schemes, retry parameters pulled from `settings`:

- `http_max_retries: int = 3`
- `http_backoff_factor: float = 1.0`
- `status_forcelist = (408, 425, 429, 500, 502, 503, 504)`
- `allowed_methods = {"GET", "HEAD", "OPTIONS"}` — POSTs must opt in
  explicitly per session; arXiv and PDF requests are all GETs.
- `respect_retry_after_header=True` — arXiv returns `Retry-After` on
  429; honoring it beats exponential guessing.
- `raise_on_status=False` — the caller inspects `resp.status_code`,
  so we don't want `urllib3` throwing before our code sees the response.

Both `tools/arxiv_search.py::search_arxiv` and
`tools/pdf_parser.py::_download_pdf` were rewritten to use this
session instead of ad-hoc `time.sleep(5 * attempt)` loops. Bonus: the
`print`-based diagnostics in both files are now structured
`log.warning(...)` calls with `pdf_url` / `query` / `status` fields
that our observability layer indexes.

### 2. LangGraph `SqliteSaver` for interrupt/resume

`src/graph/workflow.py::build_workflow` now opens a `SqliteSaver` via
`langgraph.checkpoint.sqlite.SqliteSaver.from_conn_string(path)` and
compiles the graph with it. Config keys:

- `enable_checkpointing: bool = True` — on by default. SQLite writes
  after each node are fast (~1ms) and the resumability benefit is a
  Sprint-1 requirement.
- `checkpoint_db_path: str = ".cache/checkpoints.sqlite"` — same
  gitignored cache dir as the PDF cache.

`main.run` and `eval.runner._run_and_score` pass
`config={"configurable": {"thread_id": run_id}}` to `.invoke()` so
each run has its own thread (state isolated across runs; resuming a
specific run works by reusing its `run_id`).

The compiled graph carries an `ExitStack` on `_checkpointer_exit_stack`
so the `SqliteSaver` context stays alive for the graph's lifetime.

### 3. OpenTelemetry tracing (opt-in)

`src/observability/tracing.py`:

- `configure_tracing()` — installs a `TracerProvider` with a
  `Resource(service.name=...)` and either a `ConsoleSpanExporter`
  (default, for local dev — prints spans to stderr) or an
  `OTLPSpanExporter` over HTTP (when `settings.otel_exporter_endpoint`
  is set). Idempotent, called from `get_tracer()` and `traced_node`.
- `traced_node(name, fn)` — wraps an agent function so each execution
  becomes a span with attributes `run_id`, `state.query`,
  `state.iteration`, and `result.<key>_count` for the collection
  fields the state carries. On exception, records via
  `span.record_exception()` and sets `Status(ERROR)` before
  re-raising.
- **Off by default** (`settings.enable_tracing: bool = False`) —
  tracing costs ~10μs per span and needs a backend to matter. Ops
  turn it on when they connect to Jaeger / Tempo / Honeycomb.

Wired into every agent via `workflow.add_node("planner",
traced_node("planner", planner_agent))`. When tracing is off,
`traced_node` returns the original function reference — literally no
wrapper cost, not even an if-check per call.

### 4. Retrieval recall — LLM-as-judge separating search from generation

`measure_retrieval_recall(papers, expected_topics)` in
`src/eval/metrics.py`. Single batched LLM call — judge sees paper
titles + abstracts + topic list, returns per-topic
`{covered, paper_ids, reason}`. Score = `covered_topics / total_topics`.

Complements the completeness metric: **completeness measures what the
report says; retrieval recall measures what the search could support**.
Together they isolate whether a Sprint-N regression is retrieval-side
(search agent) or generation-side (reader / synthesizer / critic).
Cost cost is one Sonnet-priced judge call per eval run — same shape
as completeness / faithfulness.

Score wired into `summary.jsonl`, `summary.md`, and the nightly
`regression_diff` so a search-quality drop shows up alongside the
other three metrics.

### 5. Expanded benchmark 10 → 20

Ten new queries covering: agentic tool use, agentic memory,
synthetic-data training, low-bit quantization, in-context-learning
mechanisms, scaling laws (post-Chinchilla), jailbreak robustness,
reasoning fine-tuning (RLVR / STaR), speculative decoding,
interpretability methods. Domain diversity guard (`>= 5` distinct
domains) still holds; the new invariant test asserts `len >= 20`.

## Alternatives considered

### Retry

- **`tenacity`** — a purpose-built retry library. Rejected in ADR
  0009 for Anthropic; same argument here — `urllib3.Retry` is already
  a dep (transitive through `requests`) and knows how to integrate
  with the `requests` connection pool. Adding `tenacity` would give
  us two retry libraries in one codebase.
- **Custom `time.sleep(5 * attempt)` loops.** What we had. Rejected —
  doesn't respect `Retry-After`, no jitter, no adapter pooling.
- **Async retry via `httpx`.** Attractive long-term but changing the
  HTTP client on top of adding retry is scope creep. Track as
  `feat/httpx-async-http`.

### Checkpointing

- **Postgres via `PostgresSaver`.** The right answer for a
  multi-tenant / production deployment; overkill for local
  interrupt/resume. Straightforward to swap when we hit that
  milestone.
- **In-memory `MemorySaver`.** Loses state on restart — defeats the
  purpose of checkpointing. Useful for tests only.
- **Custom serialization to JSON.** Reinvents the LangGraph
  checkpoint API poorly.

### Tracing

- **LangSmith.** Superb LangGraph integration but a paid SaaS with
  vendor lock-in. Rejected on the industry-standard-tech and
  production-scale-portability mandates. OTLP data can go into
  LangSmith anyway via an exporter.
- **`langfuse`.** Same vendor concern. Also possible via OTLP.
- **Manual `logging.info` at agent boundaries.** We already do that.
  Tracing gives us span hierarchies, timing rollups, and distributed
  correlation across a future async runner — logs don't.
- **On by default.** Rejected. Console spans on every eval run is
  noise; ops enable when they wire up a backend.

### Retrieval recall

- **Deterministic overlap: expected_topic keywords vs paper
  abstracts.** Attractive because zero LLM cost, but topic strings
  are prose ("retrieval-based memory (MemGPT style)"), not keywords.
  Would produce false negatives on any synonym.
- **Use sentence-transformers similarity between topic and
  abstract.** Also zero-LLM, but a similarity score isn't the same
  question as "does this paper cover this topic" — a paper that's
  semantically similar to a topic may still not usefully cover it.
- **Ground-truth relevance labels from a domain expert.** The correct
  answer for a published-quality eval. Punts on that for now — same
  reason we can't do faithfulness against ground-truth citation lists.

### Benchmark expansion

- **Scraping from arXiv trend lists / Papers with Code.** Considered
  and rejected — hand-curated queries with intentional domain
  coverage produce a more diagnostic benchmark than scraped topics.
  ~30 queries would be nicer; 20 is the roadmap target and we can
  extend gradually.

## Consequences

- **Positive**:
  - arXiv rate limits are no longer eval-run killers — 429s retry
    transparently with Retry-After honored.
  - PDF downloads survive transient 5xx from arXiv's CDN, reducing
    "fell back to abstract" noise in reader diagnostics.
  - A crashed / Ctrl-C'd run is now resumable — `--run-id <rid>` +
    same `thread_id` picks up mid-workflow (follow-up wiring in
    `main.py` to expose that flag).
  - OpenTelemetry gives us per-node timing rollups and error
    attribution without vendor lock — pointing at any OTLP backend
    is one env var.
  - Retrieval recall separates search-side regressions (planner /
    search) from generation-side regressions (reader / synthesizer /
    critic) — makes the nightly diff actionable.
  - Benchmark diversity: 20 queries across 12+ domains, harder to
    game with a single-topic prompt tweak.

- **Negative**:
  - Fourth judge call per eval run. Cost per run rises ~25% (from 3
    to 4 LLM-as-judge calls plus the workflow). Real number: ~$5-15
    → ~$6-18 per nightly. Mitigated by `feat/eval-cheaper-judge`.
  - `SqliteSaver` writes add ~1ms per node. Not observable in
    end-to-end timings but real.
  - OTel deps (~4 packages, ~1.5 MB) added even for users who don't
    enable tracing. Acceptable.
  - Checkpoint DB grows over time. Not gc'd. Track as
    `chore/checkpoint-gc`.

- **Follow-ups**:
  - `feat/main-resume-flag` — expose a `--run-id` CLI arg on
    `main.py` so users can resume a checkpointed run.
  - `chore/checkpoint-gc` — periodically prune old
    checkpoint threads.
  - `feat/eval-cheaper-judge` — Haiku for judges; cuts cost ~5x.
  - `feat/httpx-async-http` — replace `requests` with `httpx` and
    make the arXiv / PDF path async; then converge with future
    async reader.
