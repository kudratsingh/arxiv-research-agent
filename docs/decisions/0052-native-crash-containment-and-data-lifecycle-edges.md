# 0052. Native-crash containment, and the data-lifecycle edges around it

- **Status**: accepted
- **Date**: 2026-08-20
- **Deciders**: kudratsingh
- **Follows**: [ADR 0028](0028-postgres-paper-cache-and-embedding-cache.md)
  (paper + embedding caches),
  [ADR 0036](0036-per-principal-store-scoping.md)
  (per-principal store scoping),
  [ADR 0039](0039-admin-null-owner-migration.md) (the NULL-owner
  migration tool), [ADR 0041](0041-retrieval-and-degradation-honesty.md)
  (retrieval + degradation honesty),
  [ADR 0048](0048-redriver-cas-and-store-edges.md) (redriver CAS +
  store edges)

## Context

A pre-flight audit of the CLI, the cache tier and the admin tooling
returned ten findings that split cleanly in two. One group is about a
process that dies without saying anything. The other is about work
that is finished and paid for, and then thrown away — or about a
delete that is far larger than the operator thinks it is. They ship
together because the second group is what the first group's crashes
land on: a worker that segfaults mid-run is exactly the caller that
needs the report already in the checkpoint to still be reachable.

### The native crash

`make test` on an Apple-silicon host has been dying with exit 139 and
a macOS crash-reporter dialog, with no Python traceback and no log
line, because a native crash unwinds nothing. Two independent causes,
both in the same layer:

1. **Device selection.** `SentenceTransformer(MODEL_NAME)` lets the
   library pick a device, and on Apple silicon it picks `mps`. A torch
   forward pass on the Metal backend has taken the whole process down
   under concurrent encodes. Nothing in the codebase recorded which
   device a run used, so the first diagnostic question — "was this run
   on MPS?" — was unanswerable after the fact.
2. **OpenMP duplication.** Three separate `libomp.dylib` copies ship
   in the venv (torch, faiss, scikit-learn) and torch defaults to one
   OpenMP thread per core. A pytest fleet running several MiniLM
   encodes at once tears down duplicate OpenMP runtimes concurrently,
   and that race aborts the interpreter.

`settings.embedding_device` (default `"cpu"`) landed pre-flight as a
config-only change; this ADR is where it becomes load-bearing.
`faulthandler` installation and process-level env hygiene are the
other half of this containment and land separately.

### The data-lifecycle edges

- **`admin_migrate delete --yes` is an unqualified wipe under
  auth-off.** The tool's entire premise is "a NULL `principal_key_id`
  means a row written before ADR 0036". That equivalence holds only
  while `enable_api_auth` is on. With auth off,
  `routes._principal_key_id` returns None for *every* request, so
  every row the deployment has ever written carries a NULL owner, the
  scan predicate matches the whole store, and the report screen that
  is supposed to be the operator's last look before pulling the
  trigger labels a live dataset as orphans. `enable_api_auth` defaults
  to False, so this is the *default* posture, not an exotic one.
- **A corrupt Redis job row silently disables the terminal-transition
  guard.** `_status_from_payload` fails open by design — a row that
  will not parse must not wedge a job — but failing open means ADR
  0040's guard is *off* for that job, and that happened with no log
  line at all.
- **A refused terminal write discarded a finished report with a
  bodyless warning.** The refusal is correct (ADR 0048), but the
  record said only that a write was refused: no result, no length, no
  cost. The report was billed in full and is unrecoverable from that
  log line.
- **`make run` threw away a completed report when a later node
  failed.** The synthesizer runs before the critic and the verifier,
  so a failure in a later node happens with a complete `draft_report`
  in the checkpoint. The CLI re-raised, and nothing on the CLI surface
  reads a checkpoint — the report existed on disk, in
  `.cache/checkpoints.sqlite`, with no documented way to get it out.
- **`make clean` deleted `.cache/checkpoints.sqlite`.** `.cache/`
  holds two different things: `pdfs/` is re-derivable from arxiv.org,
  and `checkpoints.sqlite` is LangGraph's durable graph state,
  including any run paused at the HITL breakpoint. A target named
  "clean" destroying job state is a trap.
- **A third, stale copy of the initial `ResearchState`.** The CLI, the
  API runner and the eval runner each carried a literal; the CLI's had
  drifted ten keys behind. `ResearchState` is a *total* TypedDict, so
  a run started from that literal was already invalid against its own
  schema, surviving only because every consumer reads through `.get()`
  with a default.
- **`docs/demo.md` claimed the mock-data run made no external calls
  beyond Anthropic.** Every entry in `MOCK_PAPERS` carries a real
  `pdf_url` on `arxiv.org`, and the reader's job is full text — a cold
  mock-data run downloads five real PDFs.
- **Two silent degradations.** The reader's fall back to abstract-only
  analysis was unreported in aggregate and, on the empty-`pdf_url`
  path, unreported entirely (`parse_pdf("")` short-circuits before any
  code that could log). And the embedding cache's *write* path was a
  bare `contextlib.suppress(Exception)` while its read path logged: a
  backend that reads fine and refuses every write has a 0% hit rate
  forever and no symptom but the bill.

## Decision

**Device selection is explicit, and logged.** `_get_model()` resolves
`settings.embedding_device` through `_resolve_device()` and passes it
to the constructor. `"auto"` maps to `None` — the library's own pick,
preserved as an opt-in for deployments that want GPU encode — and
every other value is passed verbatim. One `embedding_model_loaded`
INFO line at construction records the configured value *and* what
torch actually bound to.

**The test targets pin native thread counts.** A `TEST_ENV` variable
(`OMP_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false`) prefixes every test
tier's recipe, with the reasoning inline so it does not read as a
performance tweak someone will helpfully delete.

**`admin_migrate` refuses to mutate under auth-off without an explicit
opt-in.** `assign` and `delete` exit 2 when `enable_api_auth` is False
unless the operator passes `--include-all-auth-off`. Deliberately not
`--yes`: `--yes` means "I mean it", the new flag means "I understand
the predicate selects everything". `report` is never refused — reading
is how an operator discovers the problem — but its output now opens
with the auth mode, and under auth-off says in as many words that the
counts below are the size of the whole store rather than a legacy
backlog.

**Both silent store failures become log records.**
`_status_from_payload` takes the key and logs `job_status_bad_payload`
at WARNING naming the consequence
(`terminal_transition_guard_bypassed`); a *missing* key stays silent,
because an expired retention TTL is routine and a warning per expired
job would bury the case this exists to surface. The refusal record
carries `result_len`, the first `RESULT_PREVIEW_CHARS` (200) of the
body, both statuses, `cost_usd` and `llm_calls`, and a refused
`succeeded` write — a discarded finished report — logs at ERROR rather
than WARNING, while a refused `failed` write (which loses nothing the
stored status does not already say) stays at WARNING.

**The CLI salvages the checkpoint on failure.** On any exception,
`run()` reads the failed run's own `thread_id` from the checkpoint and,
if it holds a non-empty `draft_report`, writes it to
`outputs/<run_id>-recovered.md` and names the path on stderr. The
salvage is best-effort in the strict sense: it runs from an `except`
block, so every step is guarded and a miss returns None rather than
masking the real exception, which is always re-raised unchanged. The
`thread_id` is logged on *every* failure, salvage or no salvage, so
manual recovery stays possible.

**`clean` and `clean-all` are separate targets.** `clean` removes the
venv, the tool caches and `.cache/pdfs`; `clean-all` depends on it and
additionally removes `.cache`. `make help` states the difference.

**One canonical initial state.** `initial_research_state(query,
run_id, *, prior_context="")` lives in `src/graph/state.py`, beside
the TypedDict it mirrors so the two are edited together, and the CLI
uses it. A parametrized drift test asserts the API runner's and eval
runner's private copies still match it key-for-key, and skips itself
once those copies are gone.

**`docs/demo.md` tells the truth about the network.** A table of the
hosts a mock-data run actually contacts, and the honest offline
recipe: the *second* run, against a warm `.cache/pdfs`, is the one
that talks only to Anthropic. There is no `--no-pdf` switch and none
of the existing knobs is a substitute
(`READER_MAX_CHUNKS_PER_PAPER` is bounded `ge=1`, `PDF_MAX_BYTES`
`ge=1MB` and would abort only after the request went out).

**Both degradations are audible.** Every `[]` return from
`_gather_ranked_chunks` names its stage (`no_pdf_url`, `no_text`,
`no_chunks`, `no_ranked_chunks`) in one INFO line per paper, tallied
through a ContextVar bound *inside* each worker thread; the node
closes with a `reader_completed` summary carrying `n_abstract_only`,
plus a run-level WARNING past `ABSTRACT_ONLY_WARN_THRESHOLD` (2). The
embedding cache's write failure logs `embedding_cache_put_failed` at
WARNING, mirroring its read path.

## Alternatives considered

- **Default `embedding_device` to `"auto"` and only document the
  risk.** Rejected. The failure mode is a native crash with no
  traceback on the platform most development happens on; a default
  that crashes is not a default. `"auto"` remains one setting away.
- **Catch the segfault.** Not possible in-process: SIGSEGV from inside
  a torch kernel is not a Python exception. Pinning the device removes
  the trigger; `faulthandler` (separate change) is what makes any
  residual crash legible.
- **Warn instead of refusing on `admin_migrate` mutations under
  auth-off.** Rejected. The Postgres half cascades into
  `conversation_jobs` and none of it is recoverable, and a warning
  printed above a wall of scan output is not a speed bump. A flag the
  operator has to type is.
- **Log the full report body on a refused terminal write.** Rejected.
  Reports run to tens of kilobytes, log pipelines drop or truncate
  oversized records — so the record most worth keeping is the one most
  likely to be dropped — and a full body at WARNING puts one tenant's
  research into a shared log stream on a path that fires whenever a
  redriver and a worker disagree. Length plus the opening 200
  characters identifies the run; the truncation is justified inline at
  the call site.
- **A full checkpoint-recovery CLI (`--resume`, a state dumper).**
  Rejected as scope. The finding is "a finished report is
  unreachable", and writing it to a file next to the report the run
  would have produced closes it. Resume is a larger design with a
  cost model of its own.
- **Make `clean` prompt before deleting checkpoints.** Rejected: a
  prompt in a Makefile target breaks CI and non-interactive use. Two
  targets, one of which says what it does, is the standard answer.
- **Move the canonical initializer into `src/api/runner.py` and import
  it from the CLI.** Rejected: the CLI would then import the API layer
  (and FastAPI, and the store tier) to build a dict. `src/graph/state.py`
  already owns the schema and imports nothing heavy.
- **Return the fallback tally from `_analyze_paper` instead of a
  ContextVar.** Rejected: its 3-tuple is load-bearing for a dozen call
  sites in the test suite. A module-global counter was also rejected —
  it would interleave two concurrent API jobs into one number.

## Consequences

- **Positive**: the default embedding path no longer touches the
  backend that has been killing workers, and every run records which
  device it used. Two silent store failures, two silent degradations
  and one silently-discarded report all became log records with enough
  in them to act on. The most dangerous default-configuration command
  in the tree (`admin_migrate delete --yes` with auth off) now refuses.
  A CLI run that fails after synthesis keeps its report. `make clean`
  stops destroying job state. `make run` and a `POST /research` for the
  same query now start from the same state, and a test fails if that
  stops being true.
- **Negative**: `"cpu"` gives up GPU encode by default — measured as
  irrelevant for MiniLM at this corpus size, but a larger embedding
  model would want `"auto"` and would then re-enter the crash window.
  `--include-all-auth-off` is one more thing an operator can learn to
  paste reflexively; it is rejected when auth is *on* partly to keep
  it from becoming muscle memory. The recovered-report file is a
  partial artifact with no metrics, no critique and no verification —
  it is a salvage, not a run. The reader's per-paper INFO lines add
  one line per paper to every run's log volume.
- **Follow-ups**: the API runner and eval runner still carry their own
  `_initial_state` copies (owned by other lanes this cycle); the drift
  test guards them until they adopt `initial_research_state` and then
  skips itself. A truly offline demo path — a checked-in fixture text
  set, or a `--no-pdf` flag — is not built; the warm-cache recipe is
  documented instead. `faulthandler` + process env hygiene land
  separately.
