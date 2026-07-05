# Testing strategy

Every piece of code merged into `main` has tests. Untested code doesn't
merge. But we do **not** run the full suite on every PR — tests are
organized so CI selects the appropriate subset based on the PR's changed
paths and pytest markers.

## Taxonomy

Three tiers, mirroring the industry-standard test pyramid.

### Unit — `tests/unit/`

- Pure functions. No I/O, no network, no LLM calls, no subprocess.
- Fast (<1s per test), deterministic.
- Mirror the `src/` layout: `tests/unit/tools/test_chunker.py`
  corresponds to `src/tools/chunker.py`.
- Marked `@pytest.mark.unit` (implicit — this is the default tier).
- **Runs on every PR.**
- Coverage target: >=80% on the module under test.

Existing examples: `tests/test_chunker.py`, `tests/test_pdf_parser.py`
(cache-key + cache-hit paths), `tests/test_smoke.py`.

### Integration — `tests/integration/`

- Exercises external libraries against local fixtures:
  - PyMuPDF on a small checked-in sample PDF
  - `sentence-transformers` model loading and single-batch encode
  - `arxiv_search` against a canned XML response file
  - `pdf_parser` end-to-end on a local file server or fixture PDF
- Slower (seconds per test).
- Marked `@pytest.mark.integration`.
- **Runs when the PR diff intersects integration-adjacent code** or on
  the nightly job.

### End-to-end — `tests/e2e/`

- Runs the full LangGraph workflow through all five agents.
- Uses recorded LLM cassettes (VCR-style — one recorded response per
  prompt) to stay deterministic and free of API cost in CI. Live-API
  mode gated behind an env flag (e.g. `E2E_LIVE=1`) for local debug.
- Marked `@pytest.mark.e2e`.
- **Runs on merge to `main` and nightly. Does not run on individual PRs.**

## Selective execution

CI must not run the full suite on every PR. Selection strategies:

1. **Path-based selection.** The PR-open workflow inspects the diff
   and runs `pytest` scoped to the corresponding test files (unit tier
   always; integration if the diff touches integration-adjacent code).
2. **Marker-based selection.** The three tiers use pytest markers so a
   single CI job can pick a subset:
   - PR checks: `pytest -m unit`
   - Merge to `main`: `pytest -m "unit or integration"`
   - Nightly: `pytest -m "unit or integration or e2e"`
3. **Fallback.** If the path resolver cannot map a diff (e.g. changes
   to `pyproject.toml`, `CLAUDE-Agent-Proj-1.md`, or shared
   infrastructure), run the full unit + integration suite for that PR.

Marker configuration lives in `pyproject.toml` under
`[tool.pytest.ini_options].markers`. The CI wiring is tracked as a
separate deliverable in `docs/roadmap.md`.

## Test writing standards

- Mirror the `src/` layout in `tests/`. One test module per source module.
- Prefer parametrized tests (`@pytest.mark.parametrize`) over copy-paste.
- Fixtures live next to the tests that use them (`conftest.py` per dir).
- Never hit real external services in unit or integration tiers. E2E
  uses recorded cassettes by default.
- Every PR ships with tests for its diff. Untested behavior fails review.

## What "tested" means for LLM-heavy code

Non-determinism means we cannot assert on exact model output. Instead:

- Assert on the **structure** of the response — JSON parses, required
  keys present, types correct, scores in `[0, 1]`.
- Assert on the **prompt shape** — inputs are packed correctly into the
  prompt (unit tests on prompt-builder helpers).
- Cassette-based e2e checks that the pipeline as a whole produces a
  well-formed report with citations that resolve.
- Every LLM-calling module has at least one integration test with a
  stubbed / recorded response to catch prompt-format regressions.
