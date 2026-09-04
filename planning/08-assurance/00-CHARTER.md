# Phase A — Assurance

Status: **PLANNED — authorized by the owner 2026-09-04**

Baseline: `0caefa2` on `main`

Owner instruction this phase executes, verbatim:

> "expand and build out the testing, evaluation, error handling, logging
> and observability for this project ... we need to follow the true typical
> testing and evaluation arc an agent takes to prove its reliable safe
> accurate compliant and does exactly what we say because we can build on
> top of this and add mcp and other agent tools and infra to our system"

## 1. What this phase is

Phase A is a **production-assurance** phase, not a capability phase. It adds
no agent, no route, and no user-visible feature. It makes the system's
existing behaviour *provable*: every claim the repository makes about
reliability, safety, accuracy and compliance gets a mechanism that fails
loudly when the claim stops being true.

The organizing idea is that "it works" is not a property of code. It is a
property of the evidence around code. The repository already has a large
amount of working code — 35,925 lines of `src/`, 2,042 passing tests, four
eval metrics, an OTel exporter, a cost enforcer. What it does not yet have is
a chain of custody from "we say the agent does X" to "here is the artifact
that fails when it stops doing X."

## 2. What this phase is not

- **Not a rewrite.** Every work order is additive or a bounded edit at a named
  seam. No agent prompt, graph topology, or product surface changes.
- **Not the agent-engineering program.** `docs/agent-engineering/` is the
  forward-looking measurement architecture (TaskSpec, RunManifest,
  TrajectoryEvent, benchmark registry, adaptive compute, post-training). That
  program is a design package and is explicitly not implementation authority.
  Phase A does not implement any of its four P0 contracts and does not write
  in its directory. See §6.
- **Not funded evaluation.** No work order in this phase spends a cent on
  model calls. Every gate Phase A adds must be satisfiable with
  `ANTHROPIC_API_KEY=local-preview-disabled`.
- **Not deployment.** No hosted collector, no dashboards standing up
  anywhere, no infrastructure that costs money. Phase A ships alert *rules*
  and dashboard *definitions* as reviewable files; running them is a later,
  owner-approved decision.

## 3. The assurance arc

The phase is sequenced as the arc a system actually climbs to become
trustworthy. Each rung is only meaningful if the rung below it holds.

| Rung | Question it answers | Phase A work |
|---|---|---|
| R0 Specification | What do we claim? | Error contract, invariant catalogue, SLO definitions, safety policy |
| R1 Isolation | Can the tests lie to us? | No network, no key, no ambient env, fixed clock/seed, strict markers, per-test timeout |
| R2 Component correctness | Do the parts work on inputs we did not think of? | Coverage floor, property-based tests |
| R3 Contract conformance | Do the boundaries still match? | Error envelope, OpenAPI, SSE, web-consumer parity |
| R4 Failure behaviour | What happens when things break? | Fault injection: dependency loss, timeout, cancel, crash/resume, poison message, budget trip |
| R5 End-to-end behaviour | Does the whole agent run do what we say? | The Python e2e tier that `docs/testing.md` has called "planned, not built" |
| R6 Measured accuracy | Is a score a fact or a coincidence? | Judge pinning, rubric versioning, run provenance, repeats, variance, confidence intervals |
| R7 Adversarial safety | Does it hold under attack? | Attack corpus, attack-success-rate, isolation and refusal metrics, OWASP-mapped gate |
| R8 Runtime truth | Can we see what production is doing? | Correlated traces/logs/metrics, GenAI semantic conventions, RED/USE coverage |
| R9 Operability | Can a human respond at 3am? | Readiness split, runbooks, alert rules, dashboard definitions |
| R10 Assurance evidence | Can a reviewer check us? | Model card, data provenance, eval and safety reports, framework mapping |

R0–R5 are "does exactly what we say". R6–R7 are "accurate and safe". R8–R9
are "reliable". R10 is "compliant". The owner's sentence is the arc.

## 4. Why now, and what it unlocks

The owner's stated reason is the load-bearing one: *"we can build on top of
this and add mcp and other agent tools and infra."* Every item on that list
multiplies the blast radius of a defect.

- An MCP server turns third-party text into instructions the agent may act
  on. Today's injection evidence is five regexes and a literal-canary
  substring check on 2 of 15 scenarios (R7 fixes the measurement before the
  attack surface grows).
- New tools mean new failure modes. Today a dependency outage produces an
  untyped Starlette 500 with the raw exception string handed to the client
  (R0/R3/R4).
- More agent hops mean longer traces. Today every node span is a root span
  and LLM calls are not spans at all, so "where did 400 seconds go" is
  unanswerable (R8).

Phase A is the floor those additions stand on.

## 5. Hard constraints

These are inherited locks and they are not negotiable inside this phase.

1. **Zero model spend.** `ANTHROPIC_API_KEY=local-preview-disabled` for every
   local and CI path. No work order may introduce a gate that requires a paid
   call. Funded evaluation remains blocked on the owner's W-OD-1.
2. **Both nightly workflows stay disabled** (`nightly-eval`,
   `nightly-lighthouse`) unless a work order names re-enabling as a
   deliverable and the owner approves it.
3. **No secrets** are added to the repository, CI, or any example file.
4. **`web/audit-exceptions.json` entries are never deleted** to work around a
   registry outage.
5. **Builders never merge.** A work-order agent opens a PR and stops. The
   coordinator merges, and only on a strictly-verified green.
6. **Never `gh pr merge --auto`** — there is no branch protection on this
   repository, so `--auto` merges immediately rather than on green.
7. **Dependency changes follow ADR 0045**: ranges in `pyproject.toml`, exact
   pins in `requirements-lock.txt`, the runtime subset regenerated by
   `scripts/derive_runtime_lock.py`. Exactly one work order (WO-A02) is
   allowed to move the lock, so the phase has one dependency diff, not seven.
8. **Doc drift is a bug.** A code change and its documentation land in the
   same PR.

## 6. Boundary with the agent-engineering program

Both programs touch evaluation, so the seam is stated explicitly rather than
left to chance.

| | Phase A (this) | Agent-engineering program |
|---|---|---|
| Question | Is the system we have provably correct, safe and operable? | What capability and measurement architecture should we build next? |
| Status | Authorized, executing | Design package, not implementation authority |
| Horizon | The code on `main` today | Adaptive compute, feedback learning, post-training, long-horizon |
| Spend | Zero, structurally | Its G2+ gates require owner-approved spend |
| Artifacts | Tests, instruments, contracts, runbooks, evidence | RFCs, roadmap, experiment designs |

Phase A does **not** create anything named `TaskSpec`, `RunManifest`,
`TrajectoryEvent`, or a benchmark registry, and does not write under
`docs/agent-engineering/`. Where Phase A needs a concept that program will
later formalize — a stable run identity in logs, a dataset provenance
record — it uses the smallest thing that satisfies today's requirement and
records the seam in `03-ARCHITECTURE.md` §7 so the later contract can absorb
it rather than collide with it.

The relationship runs the other way too, and this is the useful part: that
program's promotion ladder opens with **G0 "contract: schema, unit, security,
property, and mutation tests — no paid calls"** and **G1 "replay: recorded
trajectory regression and adversarial cases — no paid calls."** Neither gate
is executable on `main` today: there are no property tests, no security tier
that can be run on its own, no adversarial corpus, and no coverage floor.
Phase A is what makes G0 and G1 real, at zero cost, before anyone asks the
owner to fund G2.

## 7. Ways of working

- One work order, one branch, one PR, one reviewable diff.
- Work-order agents run concurrently in their own `git worktree`, never in
  the shared checkout.
- Every PR must leave the full local gate green — `pytest -m "not e2e"`,
  `mypy src/`, `ruff check src/ tests/`, and for any `web/` change
  `npm test -- --run` — and must state in its body what it ran.
- The coordinator merges only after `gh pr checks` reports **every** check in
  the `pass` bucket, counted from JSON rather than trusted from an exit code.
  (A cancelled check exits 0 in `gh` 2.89.0; that mistake merged PR #157 with
  a cancelled job and is why this rule is written down.)
- After each wave merges, `main` is re-verified as a whole. Individually green
  PRs do not prove they compose.

## 8. Definition of done

Phase A is done when the three gates in [`05-GATES.md`](05-GATES.md) close:

- **Gate A1 — Foundations.** The test harness cannot silently reach the
  network, a real key, or a developer `.env`; every failure has a stable code
  and a bounded public message; every log line can be correlated to a run.
- **Gate A2 — Behaviour.** Fault injection, property tests, an end-to-end
  tier, GenAI-conventional telemetry, and an adversarial suite all gate on
  every PR at zero cost.
- **Gate A3 — Assurance.** A reviewer can open one index and follow every
  claim in the README to the artifact that enforces it, including the
  framework mapping and the model card.

Each gate closes with an evidence pack under
[`evidence/`](evidence/), assembled from CI artifacts and runner-verified
locally, never from a number typed by hand.
