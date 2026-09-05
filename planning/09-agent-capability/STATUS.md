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
