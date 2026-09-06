# Agent-capability lane — status

Updated: 2026-09-06

## Execution log

| Date | Event |
|---|---|
| 2026-09-05 | Owner assigns the agent-capability work to the Fable coordinator session; Opus workers in isolated worktrees; zero spend; funding deferred until all current build items across the three lanes close |
| 2026-09-05 | Charter and wave-1 work orders written (CAP-01 gateway request profiles, CAP-02 Arm C verify-and-repair); namespace `cap/*`, `/private/tmp/arxiv-cap-*`, `planning/09-agent-capability/` |
| 2026-09-05 | PR #202 merged (`ce19b26`); the lane's planning docs are on main |
| 2026-09-05 | CAP-07 promoted from optional wave 2 to authorized wave 1b after the assurance lane's frontend survey found no keyless path to a briefing; starts when CAP-01/CAP-02 PRs are open |
| 2026-09-05 | Coordination agreed with the assurance lane: `src/config.py` granted to it for one non-additive PR; the scripted research tier runs against CAP branches before merge; CAP-07 accepted as an optional wave-2 hand-over; `src/observability/**` and `src/eval/runner.py` recognised as fenced for Puma's W05–W08 |
| 2026-09-05 | Wave 1 closed: CAP-01 #212 (ADR 0077), CAP-02 #210 (ADR 0076), CAP-07 #216 (ADR 0080). Owner authorizes wave 2; funding packet only after the assurance lane's queue is also empty |
| 2026-09-05 | Wave 2 closed: CAP-08 #227 (all eight degradation rungs on the metric), CAP-04 #229 (ADR 0085, `compute_controller=off|deterministic`), CAP-03 #230 (ADR 0086, `research_policy=orchestrated_workers`) |
| 2026-09-05 | Owner: Codex session out of usage again; W07b and the P0 contract follow-ups return to this coordinator. Owner authorizes all remaining zero-spend work (wave 3 minus CAP-06) |
| 2026-09-05 | Wave 3 (zero-spend): CAP-05 #231 (ADR 0090, anthropic 1.4.0 + httpx2; every lane's local gate now needs a lock-exact venv). P0 closed at its no-cost boundary: W11 #228, W07b #234 (ADR 0088), contract follow-ups #236 (ADR 0089: `PolicySnapshot.policy_kind`, arm E redefined, one registry root), W07c #238 |
| 2026-09-05 | CAP-10 #235 (no ADR): the branch cost share reaches the reader's fan-out threads (ADR 0086 gap closed); the assurance lane's WO-D7 fence report's four stale claims corrected; dated amendments to ADRs 0076 and 0080 |
| 2026-09-06 | CAP-09 #239 (ADR 0091): listwise candidate selection + marginal-stop record; arm E runnable. Ruling R8: `ARM_SETTINGS["E"]` is the router, because ADR 0085 refuses a controller beside a shape-fixing policy. Pinned cost: T0×12/T1×8/T2×0 on `research-policy-v1` |
| 2026-09-06 | CAP-04b #241 (ADR 0087): the router reaches the branch tier on the benchmark (T2×0 → T2×8) through two entity-blind query-time rules; no threshold moved; defaults byte-identical. PR #240: a hypothesis-found flake in `tests/property/test_property_redaction.py` fixed as a disclosed one-line exception in the assurance lane's tree |
| 2026-09-06 | Coordinator queue empty of zero-spend work. Open: CAP-06 (funded smoke) and W12 (funded baseline) — both owner-gated; W12 packet at `docs/agent-engineering/16-w12-approval-packet-draft.md` §1.1 now states arm-E reachability |

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
| CAP-07 (mock mode) | The five research agents' mock branches had no log event of their own; `src/agents/mock_mode.py` recorded that as a follow-up for whoever held the closed registry. W08 registered the five names; P0-WO11 emits them. `src/agents/mock_mode.py`'s docstring said none is emitted; CAP-10 #235 replaced it with the verified table of the six emitted events. | **fixed (CAP-10)** |
| CAP-07 (coverage) | Mock mode did **not** cover `src/agents/supervisor.py`. Arm D reached a briefing only via `except Exception` on a provider client it had already tried to build, recording a degraded route as a decision. P0-WO11 adds the branch below the loop/cost short-circuits, returning `_default_next_action`'s route with a `mock_mode` stop reason. `src/agents/query_refiner.py` needs none: its node is registered only under `enable_query_refiner`, which every arm freezes off. | **fixed in P0-WO11** |
| CAP-07 (residual) | Arm D's mock route is the fixed order, so it never selects `verify`. A mock arm-D episode shows the supervisor shape at zero cost and does **not** exercise action selection. Closing that needs a mock router with a non-trivial policy, or a paid episode. | **open, this lane** |
| CAP-01 (request profiles) | The manifest's provider snapshot records routes, sampling, retry and prompt-cache mode per arm and carries no credential material; `metered` is the load-bearing field and flips the admission decision. No defect found. | **confirmed** |
| Artifact retention (W11-F1) | `src/contracts/artifact_store.py` refuses any text body matching `chain[ _-]of[ _-]thought`. Three of the four runnable arms lost their briefing bytes in qualification, because the evidence path quotes an abstract containing "chain-of-thought prompting". The loss is correlated with the benchmark's subject matter *and* falls on the evidence arms and not the control. Fenced from P0-WO11. | **open, owner to route** |

## Lane table (all work orders)

| WO | Branch | PR | Main | ADR | State |
|---|---|---|---|---|---|
| CAP-01 request profiles | `cap/01-gateway` | #212 | — | 0077 | merged |
| CAP-02 arm C verify-and-repair | `cap/02-verify-repair` | #210 | 8d3b61e | 0076 | merged |
| CAP-07 mock mode reaches every research agent | `cap/07-mock-mode` | #216 | db017d6 | 0080 | merged |
| CAP-08 degradation rungs on the metric | `cap/08-degradation-rungs` | #227 | 3f22e16 | — | merged |
| CAP-04 deterministic compute controller | `cap/04-compute-controller` | #229 | a71e975 | 0085 | merged |
| CAP-03 orchestrator-workers (T2) | `cap/03-orchestrator-workers` | #230 | c3371fd | 0086 | merged |
| CAP-05 SDK 1.x upgrade | `cap/05-sdk-1x` | #231 | 7c20601 | 0090 | merged |
| CAP-10 cost share → reader threads; docs-truth pass | `cap/10-truth-and-cost-share` | #235 | 344e90e | — (amends 0076, 0080, 0086) | merged |
| CAP-09 listwise selection + marginal stop | `cap/09-listwise-selection` | #239 | d14e137 | 0091 | merged |
| CAP-04b branch tier reachable on the benchmark | `cap/04b-tier-rules` | #241 | 03c825b | 0087 | merged |
| CAP-06 funded live smoke | — | — | — | checklist in ADR 0090 | **blocked on the owner (spend)** |

P0 work taken over from the Codex session and merged by this coordinator: W04 #203, W09 #205, W06 #214 (0079), W05 #215 (0078), W10 #217, W07 #221 (0082), W08 #222 (0083), W11 #228, W07b #234 (0088), W03b/W01b/W06b #236 (0089), W07c #238.

## Known residuals (this lane)

- Arm D's mock route is the fixed order and never selects `verify`; a mock arm-D episode does not exercise action selection (needs a mock router with a non-trivial policy, or a paid episode).
- Arm E on `research-policy-v1` after ADR 0087: T0×10 / T1×2 / T2×8. A T0-vs-T1 contrast from arm E alone rests on two cases; the branch rules make claims about retrieval this benchmark cannot score (ADR 0087 Consequences).
- Rule 12 `branch_plan_breadth` is structurally unreachable (both call sites decide from the query alone); the learning lane never reaches the controller (session jobs).
- Per-run classification of a T0 run in an arm-E deployment still reads as arm B; campaign trajectories carry no `compute.tier_selected` (ADR 0091 Consequences).
- `src.llm._get_client` constructs a real client under the `local-preview-disabled` sentinel outside pytest; only the invalid key prevents spend (candidate hardening, unscheduled).

## Open for the owner

- **CAP-06** funded live smoke of CAP-01/02/04/09 (checklist in ADR 0090) and **W12** funded baseline (`docs/agent-engineering/16-w12-approval-packet-draft.md`; §1.1 arm-E reachability; caps in §3.3 are proposals). Presented only when both this lane's and the assurance lane's queues are empty (owner ruling 2026-09-05).
- The shared main checkout is ~70 commits behind `origin/main` and is another session's working directory; nobody fast-forwards it (coordination ruling R7). Its `.venv` matches that old tree; current-main gates use the lock-exact venv outside the checkouts.
- W11-F1 artifact retention (`chain[ _-]of[ _-]thought` refusal loses briefing bytes on the evidence arms) — routing still owed.

- ~~`research_degradations_total` routing~~ — ruled by the orchestrator 2026-09-05: the assurance lane gets a one-PR exception in `src/observability/` before Puma's W08 starts (coordination board ruling R4).
- Hosted observability: the assurance lane's scoping recommends declining (no production to observe); wiring the collector into the default compose would reverse ADR 0073 §7. Both are owner calls; recorded on the coordination board.

## Coordination

- This lane: branches `cap/*`, worktrees `/private/tmp/arxiv-cap-*`, this directory, and the files listed in `00-CHARTER.md` §3.
- Assurance lane (bumblebee): `plan/08-assurance`, `assurance/*`, `/private/tmp/arxiv-asr-*`, `planning/08-assurance/**`, `docs/assurance/**`, `src/eval/simulate_research.py`, `scripted_tier_check.py`.
- Agent-engineering P0 (Puma, Codex): `codex/*`, `/private/tmp/arxiv-agent-eng-p0-*`, `docs/agent-engineering/**`, `src/contracts/**`, `planning/README.md`.
- The shared main checkout is a working directory of the other two sessions; this lane treats it as read-only and takes truth from `origin/main`.
