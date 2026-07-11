# 0028. Postgres-backed PaperCache + EmbeddingCache

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0002](0002-section-aware-chunker.md) (chunker),
  [0027](0027-docker-compose-redis-job-store.md) (compose stack)

## Context

Two caches ran per-process and per-run before this PR:

- **Extracted paper text**: `parse_pdf(pdf_url)` in
  `src/tools/pdf_parser.py` wrote `.cache/pdfs/<key>.pdf` +
  `.cache/pdfs/<key>.txt`. Scoped to the container filesystem —
  another API worker or a fresh deploy re-downloaded and re-parsed
  the same papers on cold start.
- **MiniLM embeddings**: `encode_texts(list[str])` in
  `src/tools/embeddings.py` invoked
  `SentenceTransformer.encode(...)` on every call. FAISS then
  built a fresh in-memory index. Repeat encodings of the same
  abstract (a paper that shows up in multiple runs, chunks reread
  across the supervisor loop) paid MiniLM inference every time.

Neither hurt eval throughput visibly, but both were on the critical
path for the production-scale mandate: horizontal API workers can't
share disk-scoped caches, and MiniLM inference is CPU-bound work
we'd rather do once.

Sprint 4 PR 3 (ADR 0027) added Postgres to the compose stack —
sitting idle. This PR wires it up as the shared cache backend.

## Decision

Two new pluggable caches, each with a `Protocol` + two impls +
factory. Selection driven by `settings.paper_cache` (`disk` /
`postgres`) and `settings.embedding_cache` (`none` / `postgres`),
mirroring the `JobStore` pattern from ADR 0025.

### PaperCache (`src/tools/paper_cache.py`)

Read/write surface: `get_text(key) -> str | None`,
`put_text(key, pdf_url, full_text) -> None`.

- **`DiskPaperCache`**: extracted verbatim from the pre-refactor
  `parse_pdf`. Reads/writes `<cache_dir>/<key>.txt`. Byte-identical
  to Sprint 1 behavior — a running deployment can flip between
  disk and Postgres without wiping its local cache.
- **`PostgresPaperCache`**: `paper_cache` table via `psycopg` +
  `psycopg_pool`. UPSERT on write (`ON CONFLICT DO UPDATE`), one
  indexed lookup on read. Also stores `pdf_url` and `text_length`
  as audit columns — not read on the hot path, useful for offline
  analytics against the cache table.

`parse_pdf(pdf_url)` still writes the raw PDF bytes to
`<cache_dir>/<key>.pdf` regardless of `PaperCache` backend. Reason:
a future PyMuPDF upgrade might change extraction output; keeping
the raw bytes on the filesystem lets us re-parse without a
re-download. The PDF's semantic content — the extracted text —
goes through the cache.

### EmbeddingCache (`src/tools/embedding_cache.py`)

Read/write surface: `get_many(hashes, model) -> dict[str, ndarray]`,
`put_many(entries, model) -> None`. Batch-shaped because MiniLM
inputs are always batches; a single-item read would force N
round-trips per FAISS build.

Keys: `(content_hash, model_name)` where `content_hash` is SHA256
of the text. Model name is part of the key so a model swap
invalidates the whole cache implicitly — no explicit invalidation
pass required.

- **`NoOpEmbeddingCache`**: default. Every `get_many` returns
  empty, `put_many` is a no-op. Preserves Sprint 1 behavior
  byte-identical when the feature flag is off.
- **`PostgresEmbeddingCache`**: `embedding_cache` table. Vectors
  stored as `bytea` via `numpy.tobytes()` + `dimension` column.
  Rehydrated with `np.frombuffer(...).reshape(dim)`.

`encode_texts(texts)` gets a cache-aware path: hash each text, ask
the cache for all hashes at once, run MiniLM on misses only,
stitch hits + fresh vectors back into input order, and write
misses back to the cache. Full-hit fast path skips MiniLM entirely.
Write failures on the put-back are suppressed — callers already
got their vectors and a cache-write hiccup shouldn't block
encoding.

### Connection pool (`src/tools/postgres_pool.py`)

`psycopg_pool.ConnectionPool` opened lazily on first use, one per
process. Idempotent schema bootstrap runs once per process on
first Postgres cache access: `CREATE TABLE IF NOT EXISTS` for
both tables + a supporting index. No Alembic migrations yet — the
two-table schema is small enough that in-app DDL is the pragmatic
choice; Alembic adds real complexity that isn't paying for itself
at this scale.

### Docker compose

`PAPER_CACHE=postgres` + `EMBEDDING_CACHE=postgres` are set on the
`app` service so a fresh `docker compose up` gets the shared
caches by default. `POSTGRES_URL` was already wired to the
compose Postgres service in ADR 0027; this PR just puts it to
work.

## Alternatives considered

- **pgvector for the embedding cache.** Right shape for
  similarity search, but we don't do similarity search in Postgres
  — FAISS does it in memory once vectors are loaded. Pgvector
  would add extension setup to the compose image and the Docker
  build path (needs a pgvector-enabled Postgres image, e.g.
  `pgvector/pgvector:pg16`). Rejected: bytea storage covers the
  actual use case (key-value cache of vectors) at zero
  operational cost. Trivial to swap later if we ever want
  Postgres-side ANN search.
- **`asyncpg` instead of `psycopg`.** `asyncpg` is faster
  microbenchmark-for-microbenchmark, but the callers
  (`parse_pdf` from the reader's `ThreadPoolExecutor`,
  `encode_texts` from a similar fan-out) are sync. Async would
  force `asyncio.run(...)` inside a thread, which is a footgun.
  Rejected. `psycopg` v3 supports both sync and async modes so
  switching later is a local change.
- **Alembic-managed schema.** Right answer for a schema that
  evolves. Two tables, one index, additive migrations only —
  overkill today. Idempotent `CREATE TABLE IF NOT EXISTS` on
  startup is enough. Revisit when the schema starts churning.
- **Redis for the embedding cache.** Redis is already in the
  compose stack. Rejected: embedding vectors are ~1-3 KB each
  and we want them durable, not TTL-scoped. Redis for hot ephemeral
  state (jobs, ADR 0027); Postgres for durable content-addressed
  data (papers, embeddings).
- **Keep the raw PDF in Postgres too.** Could store `pdf_bytes`
  as `bytea` alongside `full_text`. Rejected: the raw PDF is
  large (~500 KB - 5 MB per paper) and only re-read when the
  parser changes, which is rare. Filesystem is the right storage
  for that; the extracted text is the semantic content.
- **Move Docker builds to `pgvector/pgvector:pg16` proactively.**
  Would eliminate the extension setup cost of a future pgvector
  swap. Rejected as premature — the extra ~200 MB base image for
  functionality we don't use yet doesn't earn its keep.
- **Test with `testcontainers-python` instead of
  `pytest-postgresql`.** Testcontainers is Docker-based, which
  works in CI but requires Docker Desktop locally. `pytest-postgresql`
  spawns a real Postgres process (via `pg_ctl`), which works
  identically in CI (ubuntu-latest ships `postgresql-16`) and on
  any dev machine with `postgresql` installed. Less operational
  surface, faster fixture setup.

## Consequences

- **Positive.** Horizontal API workers share the cache — a paper
  fetched by worker A is instantly available to worker B without
  re-downloading. Reader parallelism benefits from
  read-once-encode-once semantics on repeat abstracts. The
  content-hash + model-name key lets us upgrade MiniLM without a
  cache-wipe pass. Under the eval harness's daily benchmark
  (same 20 queries), embedding cache hits go from 0% to nearly
  100% on the second run onward; paper cache hits scale with
  paper overlap across queries.
- **Neutral.** The disk PaperCache stays functional and default,
  so local dev without Postgres works exactly as it did in
  Sprint 1. A running deployment can flip between disk and
  Postgres via env var without wiping the local cache.
- **Negative.** Adds a runtime dependency on Postgres for the
  Postgres-mode path. Cache misses that also fail to write back
  (Postgres transient error) still return the extracted text —
  suppressed at the `put_text` / `put_many` boundary — but a
  persistently unreachable Postgres would degrade to
  encode-every-time throughput. Documented; the fallback is
  invisible to callers and only shows up in the logs.
- **Follow-ups.**
  - **pgvector when ANN search matters.** If we ever want
    similarity search against a large cross-run paper corpus,
    swap the bytea column for `vector(384)` and add an `ivfflat`
    index. Two-line schema change, zero call-site impact.
  - **Alembic** if the schema starts churning past a couple of
    columns.
  - **Cache-invalidation UX** — a CLI command to purge one paper
    (`arxiv-cache purge <arxiv_id>`) once operators want it.
  - **Metrics** — cache hit-rate counters on the observability
    surface (ADR 0012), surfaced in the nightly eval summary so
    we can watch the cache warm across runs.
