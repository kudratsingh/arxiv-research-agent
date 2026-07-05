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
| `make test` | Unit tier (default per-PR check) |
| `make test-unit` | Same as `make test` (explicit) |
| `make test-integration` | Integration tier (external libs, fixtures) |
| `make test-e2e` | E2E tier (full workflow, cassettes) |
| `make test-all` | Every tier — slow, use before merging |
| `make typecheck` | `mypy src/` |
| `make run QUERY='...'` | Run the agent on a query |
| `make clean` | Nuke venv + caches |

See [`testing.md`](testing.md) for the full test taxonomy and how CI
selects tests per PR.

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

- One differential piece per PR. No bundled edits.
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
- **`pytest` finds nothing** — the marker-driven default (`-m unit`)
  filters to unit-tagged tests. Use `make test-all` to run every
  collected test regardless of marker (useful before markers are
  fully wired up).
