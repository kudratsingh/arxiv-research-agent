# Agent-capability lane — status

Updated: 2026-09-17

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
| 2026-09-06 | Codex session (puma) resumed and closed three follow-ups: W13 #245 (ADR 0092, tier provenance in campaign trajectories + arm-E per-run classification), W14 #246 (ADR 0093, state-aware mock supervisor route — arm D exercises one verify action under mock), W15 #247 (the `local-preview-disabled` sentinel refuses client construction structurally). All sessions then stopped by owner order |
| 2026-09-17 | Resumed after eleven idle days. CI was red repo-wide on new npm advisories → #250. W18 #248 (ADR 0094: rule 12 `branch_plan_breadth` retired with evidence; rule 7 shares the defect, open). W16 memo #251 → owner ruling R9 (option C) → W16b #253 (ADR 0096: the artifact screen is structural; W11-F1 closed; lesson recorded). Evaluation queue: E1 #249 (ADR 0095, mock judge — all five metrics execute under mock), E2 #252 (calibration packets + ingest/agreement report; a draft hazard removed), E3 #254 (`python -m src.campaign report`). Repo-wide comments-only pass, AST-proved: #258, #257, #260, #255, #256, #259. Docs currency #261 (README evaluation section; GitHub description + topics; owner ruling R10: no license, all rights reserved). Zero spend throughout |
| 2026-09-17 | In flight: C5 (API docstrings with the OpenAPI snapshot regenerated) → E4 (ADR 0097, degradation reasons on the trajectory so campaign reports count them); the assurance golden pass (28 @visual + 3 README images stale since #244) |

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

### Follow-ups landed after the lane closed

| WO | PR | Main | ADR | State |
|---|---|---|---|---|
| W13 tier provenance + arm-E per-run classification (puma) | #245 | 4073476 | 0092 | merged |
| W14 mock supervisor route for arm D (puma) | #246 | 05a4387 | 0093 | merged |
| W15 sentinel refuses client construction (puma) | #247 | 18c3990 | — | merged |
| Audit-gate fix (2026-09 npm advisories) | #250 | 00447cf | — | merged |
| W18 rule 12 retired | #248 | a395998 | 0094 | merged |
| W16 retention options memo | #251 | ef3daad | — | merged |
| W16b artifact screen structural (owner R9, option C) | #253 | c6d4bdf | 0096 | merged |
| E1 mock judge path | #249 | 529160f | 0095 | merged |
| E2 calibration packets + agreement report | #252 | — | — | merged |
| E3 campaign report generator | #254 | a3b112f | — | merged |
| Comments-only pass C1–C4 (six PRs) | #255 #256 #257 #258 #259 #260 | 12dd643 | — | merged |
| Docs currency + GitHub profile (owner R10) | #261 | a59c5f8 | — | merged |
| C5 API docstrings + OpenAPI snapshot | — | — | — | in flight |
| E4 degradation reasons on the trajectory | — | — | 0097 | in flight |
| Assurance golden pass (S8 debt) | — | — | — | in flight |

## Known residuals (this lane)

- ~~Arm D's mock route never selects `verify`~~ — closed by W14 #246 (ADR 0093).
- Arm E on `research-policy-v1` after ADR 0087: T0×10 / T1×2 / T2×8. A T0-vs-T1 contrast from arm E alone rests on two cases; the branch rules make claims about retrieval this benchmark cannot score (ADR 0087 Consequences).
- ~~Rule 12 `branch_plan_breadth` unreachable~~ — retired by W18 #248 (ADR 0094). **Rule 7 `plan_breadth` (T1) has the identical defect** but sits in `REASON_CODES`, a published vocabulary; needs its own decision (owner).
- ~~Per-run classification / `compute.tier_selected` in campaign trajectories~~ — closed by W13 #245 (ADR 0092).
- ~~`src.llm._get_client` constructs a real client under the sentinel~~ — closed by W15 #247: the sentinel now refuses client construction structurally.
- Eight taxonomy error codes exist only as log lines and cannot be counted from campaign records — E4 (ADR 0097) in flight.
- The learning lane never reaches the compute controller (session jobs) — by design, recorded.

## Open for the owner

- **CAP-06** funded live smoke of CAP-01/02/04/09 (checklist in ADR 0090) and **W12** funded baseline (`docs/agent-engineering/16-w12-approval-packet-draft.md`; §1.1 arm-E reachability; caps in §3.3 are proposals). The packet's own recommendation: one real episode under a separately approved micro-cap first. Both queues have been empty since 2026-09-06; presented, undecided.
- **Rule 7 `plan_breadth`**: retire (same evidence as ADR 0094) or keep — it is in the published reason-code vocabulary.
- **Owner rulings recorded 2026-09-17:** R9 W11-F1 → option C (done, ADR 0096); R10 no license — all rights reserved, "maybe later".
- The shared main checkout is synced only on an explicit owner order (R7; synced 2026-09-06 and 2026-09-17); its `.venv` is lock-exact after the 2026-09-06 rebuild.
- Social preview image (GitHub web UI only); `SECURITY.md`/`CONTRIBUTING.md` deliberately absent under R10.

## Coordination

- This lane: branches `cap/*`, worktrees `/private/tmp/arxiv-cap-*`, this directory, and the files listed in `00-CHARTER.md` §3.
- Assurance lane (bumblebee): `plan/08-assurance`, `assurance/*`, `/private/tmp/arxiv-asr-*`, `planning/08-assurance/**`, `docs/assurance/**`, `src/eval/simulate_research.py`, `scripted_tier_check.py`.
- Agent-engineering P0 (Puma, Codex): `codex/*`, `/private/tmp/arxiv-agent-eng-p0-*`, `docs/agent-engineering/**`, `src/contracts/**`, `planning/README.md`.
- The shared main checkout is a working directory of the other two sessions; this lane treats it as read-only and takes truth from `origin/main`.
