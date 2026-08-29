# Documentation

Deep documentation for `arxiv-research-agent`. The top-level
[`README.md`](../README.md) is the entry point — it summarizes the
project, states the principles, and points here for anything that needs
more space. This page is the map of what "here" holds.

## Layout

- [`architecture.md`](architecture.md) — system-level architecture: the
  two workflow shapes, the API layer (job model, SSE, HITL,
  auth/scoping), the storage matrix, and the cross-cutting concerns.
  Points at ADRs rather than duplicating them.
- [`agents/`](agents/) — per-agent design docs (inputs, outputs, prompt
  design, known failure modes). One page per agent in `src/agents/`.
- [`decisions/`](decisions/README.md) — Architecture Decision Records
  (ADRs). Every non-trivial design choice gets one. See
  [`decisions/TEMPLATE.md`](decisions/TEMPLATE.md) for the format and
  [`decisions/README.md`](decisions/README.md) for the index.
- [`proposals/`](proposals/README.md) — pre-ADR documents for work that
  has **not** been approved. Every page is labelled `PROPOSED`, none of
  them describes behavior on `main`, and none authorizes an
  implementation. An ADR records a decision that was made; a proposal
  stops at the human decision point.
- [`revamp/`](revamp/STATUS.md) — the frontend-revamp campaign
  (Direction A, the "Evidence Workbench"): discovery, design brief +
  tokens, architecture, migration plan, work orders, decision log,
  risks, and the independent gate reviews.
  [`revamp/STATUS.md`](revamp/STATUS.md) is the index — read it first;
  the rest of the directory is only navigable through it.
- [`testing.md`](testing.md) — testing strategy: the flat Python layout
  and its markers, the web suite's tiers (coverage, dependency audit,
  route budgets, Storybook, Playwright + axe), what CI actually runs,
  and the planned-but-unbuilt Python e2e cassette tier.
- [`development.md`](development.md) — local setup, Makefile targets,
  the optional OpenTelemetry collector wiring, dependency locking and
  licensing, and troubleshooting.
- [`security.md`](security.md) — threat model and the prompt-injection
  defenses.
- [`eval.md`](eval.md) — evaluation: the benchmark, the four metrics,
  the runner's isolation and resume behavior, the campaign run-book,
  the regression gate, and the nightly workflow.
- [`demo.md`](demo.md) — a canonical end-to-end example run, across all
  three surfaces: CLI, HTTP API, and the browser workbench.

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
