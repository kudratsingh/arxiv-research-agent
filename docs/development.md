# Local development

Everything a contributor needs to get productive on the repo. If you're
reading this before writing code, you're doing it right.

## Prerequisites

- **Python 3.11+** — this repo is developed against 3.14 (pinned in
  `.python-version` for `pyenv` / `uv` users). Anything 3.11+ works,
  but stick close to the pin to avoid subtle stdlib differences.
- **Git** and **GitHub CLI** (`gh`) for the PR workflow.
- **Homebrew** on macOS or your distro's Python packages on Linux.

## First-time setup

```bash
git clone git@github.com:kudratsingh/arxiv-research-agent.git
cd arxiv-research-agent
make install-dev
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

`make install-dev` creates a fresh `.venv/` and installs the package
plus dev dependencies (`pytest`, `mypy`). It's idempotent — run it
again any time deps change.

## Common commands

All targets are documented by `make help`. The ones you'll use daily:

| Target | What it does |
|---|---|
| `make install-dev` | Fresh venv + runtime + dev deps |
| `make test` | Tests tagged `unit` only — see Troubleshooting; CI's per-PR gate is `pytest -m "not e2e"` |
| `make test-unit` | Same as `make test` (explicit) |
| `make test-integration` | Integration tier (external libs, fixtures) |
| `make test-e2e` | E2E tier (full workflow, cassettes) |
| `make test-all` | Every tier — slow, use before merging |
| `make typecheck` | `mypy src/` |
| `make run QUERY='...'` | Run the agent on a query |
| `make clean` | Nuke venv + caches |

See [`testing.md`](testing.md) for the full test taxonomy and how CI
selects tests per PR.

## Dependency locking

Two files describe dependencies, with different jobs (ADR 0045):

- **`pyproject.toml`** is authoritative for *ranges* — the floors and
  caps a version must fall inside to be worth trying. Floors are the
  oldest release that ships a wheel for the pinned Python and speaks
  the API the code targets; caps sit at the next major above the
  locked version.
- **`requirements-lock.txt`** is authoritative for *the tested set* —
  the exact versions the suite last ran green against. CI installs
  from it, so the gated set and the tested set are identical by
  construction.

To update dependencies:

```bash
# 1. Upgrade inside the venv (respects pyproject's ranges):
.venv/bin/pip install --upgrade -e ".[dev]"

# 2. Run the full local gate against the new set:
make test-all && make typecheck && .venv/bin/ruff check src/ tests/

# 3. Re-freeze, keeping the header comment block intact:
.venv/bin/pip freeze --exclude-editable | sort -f  # -> replace the
                                                   # pinned section of
                                                   # requirements-lock.txt

# 4. Commit pyproject.toml (if ranges moved) + requirements-lock.txt
#    together, with a line on *why* the set moved.
```

Never hand-edit an individual pin in the lock without running the
gate — a pin the suite has not seen is a lie about what was tested.
The lock is frozen on one platform and carries no hashes yet; the
hashed, cross-platform lock (`uv lock` / `pip-compile
--generate-hashes`) is recorded follow-up in ADR 0045.

## Dependency licensing

PyMuPDF (`fitz`, the PDF extractor behind `src/tools/pdf_parser.py`)
is **AGPL-3.0 dual-licensed** (AGPL or a commercial Artifex license).
AGPL §13 attaches a source-offer obligation to *network* use, which
is exactly how this service runs. The repo currently declares no
license of its own — adopting one (and deciding whether to keep
PyMuPDF, buy the commercial license, or swap to a permissive
extractor such as `pypdfium2`) is an explicit open decision recorded
in ADR 0045. Do not add copyleft dependencies without an ADR.

## The moved-repo venv trap

Python venvs bake absolute paths into their shebangs. If you move the
repo directory (or clone into a new location) **without recreating
the venv**, every command inside `.venv/bin/` will fail with:

```
bad interpreter: /old/path/.venv/bin/python3.14: no such file or directory
```

Fix: `make clean && make install-dev`. This is why the repo ships
with a `Makefile` — never recreate venvs manually or from memory.

## Branching and PRs

See the **Development Workflow** section in `CLAUDE-Agent-Proj-1.md`
for the branch-naming and PR conventions. Short version:

- Bundle related concerns into one cohesive PR (~400-800 additions);
  do not fragment cohesive work across PRs.
- Branches: `<type>/<slug>` — `feat/`, `fix/`, `docs/`, `chore/`, `test/`.
- Every PR ships with tests for its diff (see `testing.md`).
- Every PR that changes behavior updates the relevant doc in the same PR.

## Troubleshooting

- **`command not found: python`** — use `python3`. The Makefile does
  this for you.
- **`ANTHROPIC_API_KEY not set`** — copy `.env.example` to `.env` and
  fill in the key. `main.py` loads it via `python-dotenv`.
- **arXiv rate limiting** — set `USE_MOCK_DATA=true` to run against
  the built-in mock papers.
- **`make test` finds almost nothing** — `make test-unit` filters with
  `-m unit`, which selects only tests *explicitly* tagged
  `pytest.mark.unit`; most of the suite is unmarked and gets skipped
  by that filter. CI's actual gate is `pytest -m "not e2e"`. Use
  `make test-all` (or `pytest -m "not e2e"` directly) to run what CI
  runs.
