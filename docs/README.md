# Documentation

Deep documentation for `arxiv-research-agent`. The top-level
`CLAUDE-Agent-Proj-1.md` is the entry point — it summarizes the project,
states the principles, and points here for anything that needs more space.

## Layout

- `agents/` — per-agent design docs (inputs, outputs, prompt design,
  known failure modes). One page per agent.
- `decisions/` — Architecture Decision Records (ADRs). Every non-trivial
  design choice gets one. See `decisions/TEMPLATE.md` for the format.
- `testing.md` — testing strategy: taxonomy (unit / integration / e2e),
  markers, selective execution per PR.
- `architecture.md` — system-level architecture (to be added; see
  Architecture section in `CLAUDE-Agent-Proj-1.md` for now).
- `roadmap.md` — phased build plan with per-phase deliverables (to be
  added; see Phased Build Plan in `CLAUDE-Agent-Proj-1.md` for now).

## How to contribute docs

- Every non-trivial code change updates the relevant doc in the **same
  PR**. Doc drift is a bug.
- Long-form content lives here, not in `CLAUDE-Agent-Proj-1.md`. The
  top-level file is an index and mandate, not a manual.
- Architecture decisions land as ADRs before or alongside the code that
  implements them. Never renumber ADRs; supersede them instead.
