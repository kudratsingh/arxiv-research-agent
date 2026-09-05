# Agent-capability lane — status

Updated: 2026-09-05

## Execution log

| Date | Event |
|---|---|
| 2026-09-05 | Owner assigns the agent-capability work to the Fable coordinator session; Opus workers in isolated worktrees; zero spend; funding deferred until all current build items across the three lanes close |
| 2026-09-05 | Charter and wave-1 work orders written (CAP-01 gateway request profiles, CAP-02 Arm C verify-and-repair); namespace `cap/*`, `/private/tmp/arxiv-cap-*`, `planning/09-agent-capability/` |
| 2026-09-05 | PR #202 merged (`ce19b26`); the lane's planning docs are on main |
| 2026-09-05 | CAP-07 promoted from optional wave 2 to authorized wave 1b after the assurance lane's frontend survey found no keyless path to a briefing; starts when CAP-01/CAP-02 PRs are open |
| 2026-09-05 | Coordination agreed with the assurance lane: `src/config.py` granted to it for one non-additive PR; the scripted research tier runs against CAP branches before merge; CAP-07 accepted as an optional wave-2 hand-over; `src/observability/**` and `src/eval/runner.py` recognised as fenced for Puma's W05–W08 |

## Wave 1 — CLOSED 2026-09-05

CAP-01 #212 (ADR 0077), CAP-02 #210 (ADR 0076), CAP-07 #216 (ADR 0080) merged on nine-check green, each tier-checked byte-identical with default settings. P0 (taken over from the Codex session): W04 #203, W09 #205, W06 #214 (ADR 0079), W05 #215 (ADR 0078), W10 #217, W07 #221 (ADR 0082), W08 #222 (ADR 0083) merged; W11 in flight. Owner rulings 2026-09-05: wave 2 authorized; funding packet only after the assurance lane's queue is also empty.

## What P0-WO11 found about this lane's work

P0-WO11's Stage-0 qualification exercised CAP-01, CAP-02 and CAP-07 through
the real compiled graphs. Recorded here because three of the findings are
this lane's to act on, not the agent-engineering lane's.

| Item | Finding | State |
|---|---|---|
| CAP-02 (arm C) | The compiled `verify`/`repair` stage is real: arm C classifies structurally, earns all three of `ARM_REQUIRED_CAPABILITIES["C"]`, seals a manifest distinct from B's, and the impostor combination (`ENABLE_VERIFIER=true`, fixed graph) is refused as arm A. 07 §3's "implementation status: not present" is closed. | **confirmed** |
| CAP-02 + W05 | `shadow_bridge.graph_shape`'s cache key omitted `research_policy`, so arms B and C — identical in all four keyed flags — collided and the second to ask received the first's shape. A campaign would have sealed arm C against B's graph. | **fixed in P0-WO11** |
| CAP-07 (mock mode) | The five research agents' mock branches had no log event of their own; `src/agents/mock_mode.py` recorded that as a follow-up for whoever held the closed registry. W08 registered the five names; P0-WO11 emits them. `src/agents/mock_mode.py`'s docstring still says none is emitted and is **stale** — fenced from P0-WO11, one sentence for this lane. | **fixed; one stale docstring left** |
| CAP-07 (coverage) | Mock mode did **not** cover `src/agents/supervisor.py`. Arm D reached a briefing only via `except Exception` on a provider client it had already tried to build, recording a degraded route as a decision. P0-WO11 adds the branch below the loop/cost short-circuits, returning `_default_next_action`'s route with a `mock_mode` stop reason. `src/agents/query_refiner.py` needs none: its node is registered only under `enable_query_refiner`, which every arm freezes off. | **fixed in P0-WO11** |
| CAP-07 (residual) | Arm D's mock route is the fixed order, so it never selects `verify`. A mock arm-D episode shows the supervisor shape at zero cost and does **not** exercise action selection. Closing that needs a mock router with a non-trivial policy, or a paid episode. | **open, this lane** |
| CAP-01 (request profiles) | The manifest's provider snapshot records routes, sampling, retry and prompt-cache mode per arm and carries no credential material; `metered` is the load-bearing field and flips the admission decision. No defect found. | **confirmed** |
| Artifact retention (W11-F1) | `src/contracts/artifact_store.py` refuses any text body matching `chain[ _-]of[ _-]thought`. Three of the four runnable arms lost their briefing bytes in qualification, because the evidence path quotes an abstract containing "chain-of-thought prompting". The loss is correlated with the benchmark's subject matter *and* falls on the evidence arms and not the control. Fenced from P0-WO11. | **open, owner to route** |

## Wave 1 table

| WO | Branch | Worktree | PR | State |
|---|---|---|---|---|
| CAP-01 | `cap/01-gateway` | `/private/tmp/arxiv-cap-01` | — | assigned |
| CAP-02 | `cap/02-verify-repair` | `/private/tmp/arxiv-cap-02` | — | assigned |
| CAP-07 | (wave 1b) | — | — | authorized; starts after CAP-01/CAP-02 PRs open |

## Open for the owner

- ~~`research_degradations_total` routing~~ — ruled by the orchestrator 2026-09-05: the assurance lane gets a one-PR exception in `src/observability/` before Puma's W08 starts (coordination board ruling R4).
- Hosted observability: the assurance lane's scoping recommends declining (no production to observe); wiring the collector into the default compose would reverse ADR 0073 §7. Both are owner calls; recorded on the coordination board.

## Coordination

- This lane: branches `cap/*`, worktrees `/private/tmp/arxiv-cap-*`, this directory, and the files listed in `00-CHARTER.md` §3.
- Assurance lane (bumblebee): `plan/08-assurance`, `assurance/*`, `/private/tmp/arxiv-asr-*`, `planning/08-assurance/**`, `docs/assurance/**`, `src/eval/simulate_research.py`, `scripted_tier_check.py`.
- Agent-engineering P0 (Puma, Codex): `codex/*`, `/private/tmp/arxiv-agent-eng-p0-*`, `docs/agent-engineering/**`, `src/contracts/**`, `planning/README.md`.
- The shared main checkout is a working directory of the other two sessions; this lane treats it as read-only and takes truth from `origin/main`.
