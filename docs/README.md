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
  and its two marker axes (tier and purpose), the web suite's tiers
  (coverage, dependency audit, route budgets, Storybook, Playwright +
  axe), and what CI actually runs — which since WO-A13 is every Python
  tier under enforced project, per-package and patch coverage floors.
  The Python e2e tier is built and gating, on mock mode rather than the
  cassettes originally planned; that page records the difference,
  because it is not the same tier.
- [`development.md`](development.md) — local setup, Makefile targets,
  the optional OpenTelemetry collector wiring, dependency locking and
  licensing, and troubleshooting.
- [`security.md`](security.md) — threat model and the prompt-injection
  defenses.
- [`observability.md`](observability.md) — the log contract (envelope,
  event names, the `extra` allowlist, redaction) and the telemetry
  contract (spans, metrics, the GenAI conventional names), plus what the
  one HTTP middleware does to every request.
- [`reliability.md`](reliability.md) — how this service fails and what
  "working" is defined to mean: the error contract, the SLIs with the
  exact instrument behind each one, the error budgets and their
  burn-rate arithmetic, the degradation ladder, and an explicit list of
  what cannot be measured yet.
- [`runbooks/`](runbooks/README.md) — operational procedures for the
  things a human does by hand, where a wrong step costs money or data.
  [`runbooks/README.md`](runbooks/README.md) is the index: one page per
  incident the instruments make visible — model-provider outage, Redis
  loss, Postgres loss, cost-cap storm, queue saturation, poison job,
  injection alarm — each naming the signal, the first three commands,
  the containment and the rollback.
  [`runbooks/pilot.md`](runbooks/pilot.md) is the bounded pilot:
  issuing and revoking a per-pilot key, the never-reassign rule, the
  worst-case spend arithmetic, and the note that goes to each invitee.
- [`assurance/`](assurance/README.md) — the assurance evidence pack, and
  the answer to "how do you know?". `assurance/README.md` is the index and
  carries the **claim → enforcement table**: every claim in the top-level
  README and in `architecture.md`, and the test, gate or instrument that
  fails when it stops being true — including the ones nothing enforces and
  the ones that are no longer true. Alongside it, a **system** card (this
  project trains no model), a data-provenance record on the NIST AI 300-1
  field set, and the framework mapping across NIST, OWASP, ISO 42001 and
  the EU AI Act, with a deliberately non-empty out-of-reach column.
- [`eval.md`](eval.md) — evaluation: the benchmark, the four metrics,
  the runner's isolation and resume behavior, the campaign run-book,
  the regression gate, and the nightly workflow.
- [`demo.md`](demo.md) — a canonical end-to-end example run, across all
  three surfaces: CLI, HTTP API, and the browser workbench.

Alert rules, a Grafana dashboard, a collector config and the compose
overlay that would run them live outside this directory, in
[`deploy/observability/`](../deploy/observability/README.md). They are
reviewable files and **nothing runs them** — standing up a collector
costs money and is the owner's call. `docs/reliability.md` derives every
objective they watch.

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
