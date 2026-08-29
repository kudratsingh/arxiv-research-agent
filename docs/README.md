# Documentation

Deep documentation for `arxiv-research-agent`. The top-level
This page is the entry point — the pages below summarize the project,
states the principles, and points here for anything that needs more space.

## Layout

- `architecture.md` — system-level architecture: the two workflow
  shapes, the API layer (job model, SSE, HITL, auth/scoping), and the
  storage matrix. Points at ADRs rather than duplicating them.
- `agents/` — per-agent design docs (inputs, outputs, prompt design,
  known failure modes). One page per agent in `src/agents/`.
- `decisions/` — Architecture Decision Records (ADRs). Every non-trivial
  design choice gets one. See `decisions/TEMPLATE.md` for the format and
  `decisions/README.md` for the index.
- `testing.md` — testing strategy: the flat Python layout and its
  markers, the web suite's tiers (coverage, dependency audit, route
  budgets, Storybook, Playwright + axe), what CI actually runs, and the
  planned-but-unbuilt Python e2e cassette tier.
- `development.md` — local setup, Makefile targets, troubleshooting.
- `security.md` — threat model and the prompt-injection defenses.
- `eval.md` — evaluation strategy: benchmark, metrics, nightly CI.
- `demo.md` — a canonical end-to-end example run.

The roadmap and sprint log live in
[`planning/03-roadmap.md`](../planning/03-roadmap.md) — that file is
the single source of truth for sprint status; docs link to it rather
than restating it.

## How to contribute docs

- Every non-trivial code change updates the relevant doc in the **same
  PR**. Doc drift is a bug.
- Long-form content lives here, not in the top-level README. The
  top-level file is an index and mandate, not a manual.
- Architecture decisions land as ADRs before or alongside the code that
  implements them. Never renumber ADRs; supersede them instead.
- Docs describe the repo as it is on `main`. Planned or aspirational
  behavior must be labelled as such — an unlabelled description of
  something that doesn't exist is how the testing-doc gap happened.
