# Agent-capability lane — status

Updated: 2026-09-05

## Execution log

| Date | Event |
|---|---|
| 2026-09-05 | Owner assigns the agent-capability work to the Fable coordinator session; Opus workers in isolated worktrees; zero spend; funding deferred until all current build items across the three lanes close |
| 2026-09-05 | Charter and wave-1 work orders written (CAP-01 gateway request profiles, CAP-02 Arm C verify-and-repair); namespace `cap/*`, `/private/tmp/arxiv-cap-*`, `planning/09-agent-capability/` |
| 2026-09-05 | Coordination agreed with the assurance lane: `src/config.py` granted to it for one non-additive PR; the scripted research tier runs against CAP branches before merge; CAP-07 accepted as an optional wave-2 hand-over; `src/observability/**` and `src/eval/runner.py` recognised as fenced for Puma's W05–W08 |

## Wave 1

| WO | Branch | Worktree | PR | State |
|---|---|---|---|---|
| CAP-01 | `cap/01-gateway` | `/private/tmp/arxiv-cap-01` | — | assigned |
| CAP-02 | `cap/02-verify-repair` | `/private/tmp/arxiv-cap-02` | — | assigned |

## Open for the owner

- `research_degradations_total` does not exist (assurance infra-scoping finding): six of eight degradation rungs are log-only, so the quality SLI in `docs/reliability.md` is uncomputable. About ten lines in `src/observability/`, which is fenced for Puma's W05–W08. Needs a routing decision: Puma's W08, or a sanctioned assurance exception.

## Coordination

- This lane: branches `cap/*`, worktrees `/private/tmp/arxiv-cap-*`, this directory, and the files listed in `00-CHARTER.md` §3.
- Assurance lane (bumblebee): `plan/08-assurance`, `assurance/*`, `/private/tmp/arxiv-asr-*`, `planning/08-assurance/**`, `docs/assurance/**`, `src/eval/simulate_research.py`, `scripted_tier_check.py`.
- Agent-engineering P0 (Puma, Codex): `codex/*`, `/private/tmp/arxiv-agent-eng-p0-*`, `docs/agent-engineering/**`, `src/contracts/**`, `planning/README.md`.
- The shared main checkout is a working directory of the other two sessions; this lane treats it as read-only and takes truth from `origin/main`.
