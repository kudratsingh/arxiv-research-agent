# Gate W1 evidence pack

Assembled by [WO-W19](../../05-WEDGE-WORK-ORDERS.md#wo-w19--gate-w1-evidence-pack)
against `origin/main` at **`3ccb650`**, which carries every Phase W work order
merged to date — WO-W01 … WO-W18 plus the coordinator-added WO-W13b, nineteen
PRs, [#132](https://github.com/kudratsingh/arxiv-research-agent/pull/132) …
[#150](https://github.com/kudratsingh/arxiv-research-agent/pull/150). The merge
train is [§5](#5-the-merge-train).

**This pack assembles evidence. It produces none.** WO-W19's own risk note:
*"the pack is assembled, not produced, here."* The whole diff is this directory.
No product code, test, workflow or planning document was touched, and
[`STATUS.md`](../../STATUS.md) is not edited — the coordinator rules there.

**This pack does not close Gate W1 and does not claim to.** It recommends;
[§7](#7-recommendation) is the recommendation and nothing above it is a
ratification. §6's table has **ten rows**: seven resolve outright, one resolves
only at the no-cost boundary, one is this file, and **the funded-campaign row
is UNRESOLVED** — it stands for three separate runs that have never happened,
all waiting on **W-OD-1**.

**Main is HEALTHY at `3ccb650` on every tier.** Not by CI's word alone: the
**coordinator state-probe of main `3ccb650`, 2026-09-02** — an Opus agent run,
not a CI run — booted the merged stack and ran every tier against the composed
tree, which is the question a per-PR job structurally cannot answer.
[§6.1](#61-the-coordinators-state-probe--main-is-healthy-at-3ccb650) carries its
counts. It also corrected one entry in `known-gaps.md` and added another; both
corrections are left visible.

**This pack claims no learning outcome of any kind.** No real learner has been
observed, no funded campaign has ever run in this repository, and every
threshold in Phase W is a prior. [`known-gaps.md`](known-gaps.md) is the
seventeen-entry checklist, and it is required reading beside this index.

---

## 1. The §6 Gate W1 table — every row

[§6](../../05-WEDGE-WORK-ORDERS.md#6-gates-w1-and-w2--criteria-and-evidence)'s
Gate W1 table has **ten rows**, numbered 1–10 below in its own order. Row 7 —
the funded campaign — is written as one row there and stands for **three**
distinct runs, so it is split into 7a/7b/7c here; they are one §6 row and one
owner decision.

Statuses: **Resolved** · **Resolved (no-cost boundary)** — the mechanism is
proven and the measurement is not, by design · **UNRESOLVED — waits on
W-OD-1**.

| # | §6 criterion | Status | Evidence | Produced by |
|---|---|---|---|---|
| 1 | Full guided-read session end-to-end on the seeded local stack, disabled key, zero paid calls | ✅ **Resolved** | [`end-to-end-session.md`](end-to-end-session.md) — `web/e2e/session-flow.spec.ts` 2/2 and `web/e2e/session.spec.ts` 4/4 green in CI run [33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183) attempt 2 (`3ccb650`, job *web e2e (chromium + axe)*, **264 passed / 52 skipped / 0 failed**); `tests/test_guided_session_graph.py::TestTutorHonesty::test_mock_mode_never_constructs_a_client`; `session-flow.spec.ts:186-188` reads `llm_calls === 0` and `cost_usd === 0` back from the API | W03 (#137), W13 (#146), **W13b (#150)** |
| 2 | Mid-session reload resumes from checkpoint | ✅ **Resolved** | [`end-to-end-session.md`](end-to-end-session.md) §1 and §4 — `session-flow.spec.ts` *"a session started from the path view runs, survives a reload, and closes"*; `session.spec.ts` *"renders the checkpointed margin, and renders it again after a reload"*; `tests/test_guided_session_graph.py::TestCheckpointReattachment::test_a_new_graph_process_reads_the_parked_transcript` | W03 (#137), W13 (#146), W13b (#150) |
| 3 | Flags: all four default-off; flag-off behaviour identical | ✅ **Resolved**, with a wording discrepancy recorded | [`flags.md`](flags.md) — four flags, all `default=False`; the off-position proofs are `TestTheFlagIsARealOffSwitch`, `TestFlagGating`, `test_owner_scope_and_flag_off_are_real`, `test_flag_off_leaves_no_surface`, `test_flag_off_preserves_informal_recorded_ungraded_close`. **The four are not independent** and the full suite is not run twice — [§3](#3-the-flag-inventory-and-the-count-discrepancy) | W01–W07, W15; indexed by W19 |
| 4 | Paid path structurally interdicted for session routes | ✅ **Resolved** | [`paid-path-interdiction.md`](paid-path-interdiction.md) + [`artifacts/research-post-count.txt`](artifacts/research-post-count.txt), copied verbatim from `web-e2e-33630982183`. Three session rows with the `mode=` column; `POST /api/research=0` on every one | W13 (#146), W13b (#150) |
| 5 | Judges + benchmark green on their own tests; scripted simulation tier green in per-PR CI | ✅ **Resolved** | [`eval-harness.md`](eval-harness.md) §§1–2 + [`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md). CI on `3ccb650` printed `Scripted tier OK: 15/15 sessions, $0.0000 spent, 0 unmet expectations.` (job *pytest (unit + integration)*, 12:40:16Z). Suite: **2090 passed** in the same job | W08 (#132), W09 (#139), W10 (#145), W11 (#148) |
| 6 | Regression differ carries the learning metrics | ✅ **Resolved** | [`eval-harness.md`](eval-harness.md) §3 — `src/eval/regression_diff.py::LEARNING_LANE`; `tests/test_regression_diff.py` **113 tests** (66 → 113), incl. `TestLearningLaneEveryGatedField`, `TestLearningLaneResourceBands`, `TestLearningLaneHarnessCostIsNotGated`, `TestLaneIsolation` | W11 (#148) |
| **7a** | **First funded learning-eval campaign executed** — the **calibration** half — under `--max-budget-usd`; numbers recorded **as priors** | ❌ **UNRESOLVED — waits on W-OD-1** | [`eval-harness.md`](eval-harness.md) §4. Never run. `docs/eval.md`: *"Owner review and the funded campaign remain W-OD-1."* | **W09 c6** |
| **7b** | the same §6 row's **simulation** half | ❌ **UNRESOLVED — waits on W-OD-1** | [`eval-harness.md`](eval-harness.md) §4. Never run. Sized on the card: **≈15 sessions, roughly $2–6, ceiling proposed at $15** (`docs/eval.md` §"The first funded campaign is deferred — W-OD-1") | **W10 c5** |
| **7c** | *(§6 gives it no row of its own; W11 c4 belongs to the same decision)* the nightly learning lane's **first scheduled run** | ❌ **UNRESOLVED — waits on W-OD-1** | [`eval-harness.md`](eval-harness.md) §4. `eval-nightly.yml` is `disabled_manually` and stays disabled; the workflow's `DEFAULT_LEARNING_MAX_BUDGET_USD` is **$15** | **W11 c4** |
| 8 | Per-session cost accounting reconciles; cap enforcement proven | ⚠️ **Resolved (no-cost boundary)** | [`cost-reconciliation.md`](cost-reconciliation.md) — `tests/test_session_cost_cap.py`, **6 tests**. `round(job.cost_usd, 2) == 0.09` on two billed calls; both at-cap behaviours with `workflow.client_constructed is False`. **Every figure is a mock-mode figure**; the price is unmeasured | W06 (#144), ADR 0062 |
| 9 | Honesty inventory: provenance rules, no-inferred-as-fact, evidence-quoting judge, no-mastery-% gate | ✅ **Resolved** | [`honesty-inventory.md`](honesty-inventory.md) — `tests/test_learner_profile_store.py` **60**, `tests/test_learner_profile_serializer.py` **19**, `tests/test_progress_events.py` **76**, `tests/test_assessment_judge.py` **15**, `tests/test_learning_metrics.py` **23**, `web/tests/copy/forbidden.test.ts` **63** incl. the planted `"87% mastered"` fixture that MUST fail | W02 (#134), W04 (#142), W07 (#133), W14 (#147) |
| 10 | `known-gaps.md` — what W1 does *not* prove | ✅ **Resolved** | [`known-gaps.md`](known-gaps.md) — **17 entries**, non-empty | **W19** |

**Rows 1, 2, 4 and 5 were reproduced a second way.** Every citation in the
table above is a CI run or a committed test. The **coordinator state-probe of
main `3ccb650`, 2026-09-02** independently re-ran them against the merged tree
and agrees: chromium **313 passed / 3 skipped / 0 failed**, every
`research-post-count.txt` row PASS with `runtime=verified`, the guided-read row
`creates=1 turns=2 mode=mock-pass-through`, **zero paid calls**, and the
scripted campaign **15/15 at $0.0000**. Corroboration, not a second source of
truth — [§6.1](#61-the-coordinators-state-probe--main-is-healthy-at-3ccb650).

**Row 8's downgrade, stated plainly.** The row asks that accounting reconcile
and the cap be enforced. Both are proven deterministically and neither needs a
paid call, so the row *passes*. It is marked "no-cost boundary" rather than
plain Resolved because the numbers it reconciles are all zero or synthetic, and
an index that let `$0.0000` stand next to "cost accounting reconciles" without
saying so would be the kind of sales document the revamp's Gate 4 pack
([`docs/revamp/evidence/gate-4/`](../../../../docs/revamp/evidence/gate-4/README.md))
set the house rule against.

**Row 3's discrepancy** is [§3](#3-the-flag-inventory-and-the-count-discrepancy).

---

## 2. What is in here

| Path | What it is | Source |
|---|---|---|
| [`README.md`](README.md) | This index. | **W19** |
| [`known-gaps.md`](known-gaps.md) | **17 entries** (three — §6, §7 and §12 — now resolved and kept struck through). What Gate W1 does not prove, each with owner and what would change it. | **W19** |
| [`end-to-end-session.md`](end-to-end-session.md) | Rows 1–2. The browser proof, the three independent cost boundaries on it, the no-client-construction test, and the below-the-browser checkpoint reattachment. | W03/W13/W13b, collected by **W19** |
| [`paid-path-interdiction.md`](paid-path-interdiction.md) | Row 4. The interceptor's two claims and their different strengths, and the A/B control for the mock-mode pin. | W13/W13b, collected by **W19** |
| [`flags.md`](flags.md) | Row 3. The four-flag inventory, the ladder, the compose-default nuance, and every flag-off/flag-on test. | **W19** |
| [`eval-harness.md`](eval-harness.md) | Rows 5–6, and row 7 (7a/7b/7c) with its sizing and the exact owner action. | W08–W11, collected by **W19** |
| [`cost-reconciliation.md`](cost-reconciliation.md) | Row 8. The six tests, the three-payer split, and what the row does not prove. | W06, collected by **W19** |
| [`honesty-inventory.md`](honesty-inventory.md) | Row 9. Four items, four owning cards, named tests with counts. | W02/W04/W07/W14, collected by **W19** |
| [`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md) | **Copied verbatim.** `scripted-simulation-summary` artifact of CI run 33630982183 on `3ccb650`. 15 sessions, 0 errors, $0.0000 across all four cost columns. | CI, collected by **W19** |
| [`artifacts/research-post-count.txt`](artifacts/research-post-count.txt) | **Copied verbatim.** `web-e2e-33630982183` artifact, attempt 2 (the green one). Carries the `mode=` rows and the `[mock-mode]` precondition line. | CI, collected by **W19** |
| [`artifacts/ci-e2e-cls-failure.txt`](artifacts/ci-e2e-cls-failure.txt) | **Copied verbatim** from two GitHub Actions job logs: the `cls.spec.ts` failure on `4fbe239` and again on `3ccb650`. Cause found and fixed by WO-W13c (PR #155, `9fa99b8`, 2026-09-02); the log is kept as the record of the failure. See [`known-gaps.md`](known-gaps.md) §7. | CI, collected by **W19** |

**Cited, not copied** (too large, or of no use out of context): the whole
`web-e2e-33630982183` artifact (1.3 MB attempt 2 / 5.5 MB attempt 1 — axe
reports, CSP sweep, the Playwright HTML report, `proxy-log.txt` at 522 lines,
`results.json`); the `scripted-simulation-summary`'s fifteen per-scenario
records and its `summary.jsonl`; `web-coverage`, `web-budget-report`,
`web-npm-audit`, `web-storybook`. All are addressable by run id + artifact name
for 14 or 30 days.

**No producing work order wrote into this pack.**
[§5.4](../../05-WEDGE-WORK-ORDERS.md#54-fleet-coordination-hazards) names
`planning/07-learning-platform/evidence/gate-w*/` as W19/W20's, with producing
work orders writing *into* the pack and only W19/W20 authoring the index files.
In the event, this directory did not exist before this PR:
`git log --name-only -- planning/07-learning-platform/evidence/` shows three
writes, all into [`../gate-w2/`](../gate-w2/) and all correct — WO-W18
(`engagement-threshold.md`, `ac460b0`), WO-W16 (`static-launch.md`, `6f01412`)
and WO-W17 (`pilot-record.md`, `5bcf373`). So W19 collected everything here,
and every file in this directory is W19's authorship over other cards'
evidence.

---

## 3. The flag inventory, and the count discrepancy

Full detail in [`flags.md`](flags.md). The short version, because the §6 row's
wording invites two wrong readings:

**The count is four, and it is right by accident.** Phase W added exactly four
capability flags — `enable_learner_profile` (W02, shared by W07),
`enable_learn_content` (W15), `enable_session_loop` (W03),
`enable_assessment_judge` (W04) — all `default=False`. Seven cards changed
behaviour a reader would expect to sit behind a flag; three deliberately ship
without one (W01 ships the lifecycle only and says so in `src/config.py:462-465`;
W05 is a component of the graph; W07 shares W02's gate by design), and W06 adds
ceilings rather than switches.

**They are not independent, and §0's constraint says they should be.** Three of
the four sit in a ladder enforced by `model_validator`s at settings load:

```
enable_assessment_judge → enable_session_loop → enable_learner_profile → enable_api_auth
                                  ↘ enable_checkpointing
```

Only `enable_learn_content` is free-standing. The consequence is
[`known-gaps.md`](known-gaps.md) §3: **the zero-config auth-off
`docker compose up` demo cannot start a guided session.**

**"Full-suite runs both positions" is satisfied per test, not by two whole-suite
invocations.** CI runs the suite once, at the defaults (all four off), and the
on-positions are reached inside individual tests by constructing `Settings`.

**And "default-off" is true of the code but not of the container.**
`docker-compose.yml:103` sets `ENABLE_LEARN_CONTENT` to `true` for the demo,
deliberately and with its reason in the file; the production overlay sets it
back.

---

## 4. Execution record — the coordinator's rulings during Phase W

Recorded here as fact, because several explain why an ADR a reader would expect
does not exist. None of these is W19's ruling; W19 is writing them down.

1. **WO-W10 and WO-W11 were built to their no-cost boundary**, following the
   WO-W09 pattern: the scripted tiers are real and CI-run; the funded rows are
   deferred behind W-OD-1.
2. **No ADR for WO-W10's third cost-payer column** (`learner_cost_usd`) — it is
   an application of **ADR 0050**, not a new decision. (PR #145 flagged it for
   the coordinator; this is the answer.)
3. **No ADR for WO-W13's e2e overlay turning `ENABLE_API_AUTH` on** — a harness
   decision, documented in `web/e2e/support/compose.e2e.yml` and
   `web/e2e/README.md`. (PR #146 offered to write one; declined.)
4. **WO-W14's pedagogy list is learn-scoped**, on the `LEXICON_PHRASES`
   precedent. **Four WO-W13 session copy keys were reworded** to satisfy it;
   they are listed with before/after in [#147](https://github.com/kudratsingh/arxiv-research-agent/pull/147)'s
   body (`replyHint`, `workingBody`, `unassessedBody`, `recordedUngraded`).
5. **WO-W11 c7:** the `engineer-rlhf-profile-note-injection` expectation moved
   to the graph's documented rule. **Graph behaviour unchanged.**
6. **WO-W13b was coordinator-added** to close a plan gap: no card in §5 owned
   the session-start action, so Gate W1's end-to-end row had no starting point.
   **No ADR for its mock-mode pass-through** — argued in
   `web/e2e/support/mock-mode.ts`, `paid-path.ts`, `compose.e2e.yml` and
   `web/e2e/README.md` instead.
7. **WO-W17 merged at its no-cost half**, with **ADR 0063**. The identity-slot
   copy discrepancy it found is being fixed by **WO-W17b (in flight)** under an
   SR-07-compliant server-resolved descriptor.
8. **The `nightly-eval` workflow remains disabled. All model spend remains
   locked.**

Three more, for completeness, all after the §5 merge train:

- **WO-W03b merged** as PR [#151](https://github.com/kudratsingh/arxiv-research-agent/pull/151)
  / `1026534` on 2026-09-02, resolving the tutor's close line
  (`known-gaps.md` §6) and introducing the mirror coupling now recorded as
  `known-gaps.md` §17. **It is one commit past this pack's baseline**, so no §6
  status above moves on account of it.
- ~~**WO-W13c is in flight**~~ — **WO-W13c merged** as PR
  [#155](https://github.com/kudratsingh/arxiv-research-agent/pull/155) /
  `9fa99b8` on 2026-09-02, resolving the `cls.spec.ts` failure at its cause and
  interpolating the e2e overlay's daemon-global image tags (`known-gaps.md` §7,
  §8). **It is five commits past this pack's baseline**, so no §6 status above
  moves on account of it.
- ~~**WO-W17b is in flight**~~ — **WO-W17b merged** as PR
  [#153](https://github.com/kudratsingh/arxiv-research-agent/pull/153) /
  `72e65b9` on 2026-09-02, resolving the pilot identity copy under an
  SR-07-compliant server-resolved descriptor — `shared` / `pilot` /
  `unresolved`, derived per request on the server and handed to the shell as a
  prop, mode-off byte-identity proved twice, pilot e2e **5 passed** locally
  (`known-gaps.md` §12). **It is two commits past this pack's baseline, and
  merged six minutes before the pack itself**, so no §6 status above moves on
  account of it.

---

## 5. The merge train

Nineteen PRs, `08ee3fc` (the plan) → `3ccb650`. Merge SHAs and `mergedAt` from
`gh pr view`; dates are UTC.

| # | Card | Gate | Merge SHA | Merged (UTC) |
|---|---|:-:|---|---|
| [#132](https://github.com/kudratsingh/arxiv-research-agent/pull/132) | WO-W08 — guided-read benchmark + fixture machinery | W1 | `a884533` | 2026-08-30 08:26 |
| [#134](https://github.com/kudratsingh/arxiv-research-agent/pull/134) | WO-W02 — learner-lite profile store, provenance | W1 | `19e8b17` | 2026-08-30 08:37 |
| [#133](https://github.com/kudratsingh/arxiv-research-agent/pull/133) | WO-W07 — append-only progress ledger | W1 | `5d53514` | 2026-08-31 10:58 |
| [#135](https://github.com/kudratsingh/arxiv-research-agent/pull/135) | WO-W01 — job kinds, `awaiting_learner` | W1 | `0424186` | 2026-08-31 11:14 |
| [#136](https://github.com/kudratsingh/arxiv-research-agent/pull/136) | WO-W15 — flagship path manifest + licensing gate | W2 | `624e5c9` | 2026-08-31 11:29 |
| [#137](https://github.com/kudratsingh/arxiv-research-agent/pull/137) | WO-W03 — guided-read session graph | W1 | `eddc630` | 2026-08-31 23:18 |
| [#138](https://github.com/kudratsingh/arxiv-research-agent/pull/138) | WO-W12 — `(learn)` shell + path view | W1 | `054c83f` | 2026-09-01 07:47 |
| [#139](https://github.com/kudratsingh/arxiv-research-agent/pull/139) | WO-W09 — learning metrics + calibration harness | W1 | `2eb82d8` | 2026-09-01 10:59 |
| [#140](https://github.com/kudratsingh/arxiv-research-agent/pull/140) | WO-W18 — engagement + cost reporting | W2 | `ac460b0` | 2026-09-01 11:07 |
| [#141](https://github.com/kudratsingh/arxiv-research-agent/pull/141) | WO-W16 — static publication (guarded) | W2 | `6f01412` | 2026-09-01 11:16 |
| [#142](https://github.com/kudratsingh/arxiv-research-agent/pull/142) | WO-W04 — evidence-grounded assessment judge | W1 | `4d033fb` | 2026-09-01 11:25 |
| [#143](https://github.com/kudratsingh/arxiv-research-agent/pull/143) | WO-W05 — bounded Tier-1 session memory | W1 | `53c3c6c` | 2026-09-01 16:42 |
| [#144](https://github.com/kudratsingh/arxiv-research-agent/pull/144) | WO-W06 — per-session cost ceilings | W1 | `2114c47` | 2026-09-01 16:49 |
| [#145](https://github.com/kudratsingh/arxiv-research-agent/pull/145) | WO-W10 — learner-simulation benchmark (scripted tier) | W1 | `77a1798` | 2026-09-02 10:05 |
| [#146](https://github.com/kudratsingh/arxiv-research-agent/pull/146) | WO-W13 — guided-read session view | W1 | `4fbe239` | 2026-09-02 10:30 |
| [#148](https://github.com/kudratsingh/arxiv-research-agent/pull/148) | WO-W11 — eval wiring, nightly lane, recorded fixtures | W1 | `ba3e576` | 2026-09-02 10:51 |
| [#147](https://github.com/kudratsingh/arxiv-research-agent/pull/147) | WO-W14 — Ledger view + pedagogy honesty gate | W1 | `a9e26bf` | 2026-09-02 11:11 |
| [#149](https://github.com/kudratsingh/arxiv-research-agent/pull/149) | WO-W17 — pilot principals at the edge seam (no-cost half) | W2 | `5bcf373` | 2026-09-02 11:56 |
| [#150](https://github.com/kudratsingh/arxiv-research-agent/pull/150) | **WO-W13b** — start a guided-read session from the path view | W1 | `3ccb650` | 2026-09-02 12:37 |

ADRs **0057–0063**: 0057 job kinds and `awaiting_learner`; 0058 learner-profile
store and provenance; 0059 guided-read session graph; 0060 evidence-grounded
assessment judge; 0061 bounded Tier-1 session memory; 0062 session-specific cost
ceilings; 0063 pilot-principal edge mapping.

**Fifteen of the nineteen are Gate W1 cards.** #136, #140, #141 and #149 are
Gate W2's and are cited here only where they bear on a W1 row or a gap.

---

## 6. What CI proves, what the state probe proved, and what only a local run proved

CI is the canonical evidence for every row above. §6.1 is the one integrated
check that CI cannot perform on itself; §6.2 is what CI does not cover at all.

### 6.1 The coordinator's state probe — main is HEALTHY at `3ccb650`

**Cited throughout this pack as "coordinator state-probe of main `3ccb650`,
2026-09-02". It is an Opus agent run, not a CI run**, and it is named that way
everywhere so no reader mistakes it for a workflow artifact. What it adds that
CI cannot: CI proves each PR green against the tree *it* was built on; the probe
boots the merged stack and runs every tier against `3ccb650` itself, which is
the composition question a per-PR job structurally cannot answer.

**Verdict: HEALTHY on every tier.**

| Tier | Result |
|---|---|
| `ruff` · `mypy --strict src/` | pass, **83 source files** |
| `pytest -m "not e2e"` | **2038 passed, 52 skipped** |
| Scripted simulation campaign | **15/15**, **$0.0000**; `scripted_tier_check` OK |
| web typecheck · lint | pass |
| Vitest (unit + component + integration + story) | **3372 passed, 8 skipped**, 155 files |
| `npm run build` | **9 routes** |
| `npm run budgets` | **9/9 gated PASS** |
| `npm run audit:gate` | clean |
| `.next/static` key scan | **74 passed** |
| Playwright, chromium | **313 passed, 3 skipped, 0 failed** |
| Playwright, firefox + webkit + Pixel 7 + iPhone 15 | **113 passed, 10 skipped, 1 failed** — the one failure is [`known-gaps.md`](known-gaps.md) §16 |
| axe | **40 renders, 0 violations, 0 gated, 0 incomplete**; allowlist and `PENDING_COMPOSITION` both **empty** |
| Visual | **48 darwin snapshots compared, all passing** |
| `research-post-count.txt` | **every row PASS**, `runtime=verified`; the guided-read row `creates=1 turns=2 mode=mock-pass-through`; **zero paid calls** |

Three of those close gaps CI leaves open, and they are marked as such in §6.2:
the `.next/static` scan, the darwin visual set, and the full multi-browser
matrix. The probe also independently reproduced Gate W1 rows **1, 2, 4 and 5**
on the merged tree — the guided-read row with `runtime=verified` and zero paid
calls is the same evidence as
[`artifacts/research-post-count.txt`](artifacts/research-post-count.txt), and
the 15/15 at $0.0000 the same as
[`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md),
both obtained a second way.

**Two arithmetic reconciliations, because the numbers differ from CI's and both
are right.**

- **Playwright chromium.** The probe reads 313 passed / 3 skipped on darwin;
  CI's attempt 2 reads 264 passed / 52 skipped. Both total **316**: CI runs
  linux, where the 48 `@visual` snapshot comparisons and the rest of the darwin
  set skip by their own guard. The probe's 3 skips are WO-W17's `pilot.spec.ts`
  without `E2E_PILOT`.
- **Vitest.** The probe reads 3372 passed / 8 skipped over 155 files; PR #150's
  own run reported **3,380 passed**, 155 files, 0 failed. `3372 + 8 = 3380`.
  The pack does not claim to know which side re-classified the eight; it
  records both with their source.

**Added 2026-09-02, after WO-W13c reported: two of the probe's `cls.spec.ts`
findings were wrong, and PR
[#155](https://github.com/kudratsingh/arxiv-research-agent/pull/155)
(`9fa99b8`) overturned them.** The probe had listed *the Live badge mount*
among the causes it **eliminated by measurement**, and placed the regression
window at WO-W13's `web/lib/job/machine.ts` change. The badge mount **is** the
cause — its baseline grows the spine's status line by 3px — the machine is not
involved, and the defect **predates WO-W13**, whose change to this route was one
of timing rather than geometry. Per #155, the elimination *"was measuring the
settled DOM, where the badge is already gone"*: the sampling window did not
include the mount frame. What the probe classified correctly is the part that
held — deterministic and CI-environment-conditioned, not flaky, with the shape
(2 of 5 main runs, never on a PR, 80/80 green locally) unchanged. The verdict
above is unaffected: main was HEALTHY at `3ccb650` on every tier, and this is a
correction to one gap's diagnosis, not to a tier result. The full record is
[`known-gaps.md`](known-gaps.md) §7.

### 6.2 What CI does not cover

**CI proves**, on `3ccb650` (run
[33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
8/8 green on attempt 2): `ruff`, `mypy --strict src/` (83 files), the whole
Python suite (**2090 passed** — the 52 that skip locally run here because CI has
Postgres), the scripted simulation campaign end to end, the web tier
(typecheck / lint / test / coverage / build / budgets / audit), the Storybook
story tier with axe on every story, the chromium browser tier against the
seeded Compose stack (**264 passed, 52 skipped**), the docker builds and the web
image smoke.

**CI does not prove:**

| Not in CI | Why | Where it was proven | Re-proven by the probe? |
|---|---|---|---|
| **The darwin visual baselines** — 48 PNGs, 10 regenerated by #150 | CI runs linux; no snapshot set is committed for it and `visual.spec.ts` skips by its own guard | PR #150, locally, on the final tree; the comparison run is green | ✅ **48 compared, all passing** |
| **The `.next/static` key scan** | `npm test` runs before `npm run budgets`, so `.next/` does not exist and the test is `it.runIf`-skipped | PR #149, locally against a real build: 63 files, 0 hits | ✅ **74 passed** |
| **The multi-browser matrix** (firefox, webkit, Pixel 7, iPhone 15) | the `web-e2e` job runs `--project=chromium` only | the nightly browser matrix | ✅ **113 passed, 10 skipped, 1 failed** — §16 |
| **The pilot two-principal isolation spec** (`pilot.spec.ts`, 3 tests) | needs a third overlay and a Caddy edge; **no Phase W card edits a workflow** (§5.4). CI reports 3 skipped with the reason printed | PR #149, locally: 3 passed | ❌ skipped there too (no `E2E_PILOT`) |
| **`deploy/pilot/compose.pilot.yml`** | the `docker-build` job's compose step covers the base file and the Hetzner overlay only | PR #149, locally: `docker compose config --quiet` clean, `caddy validate` + `caddy fmt` against the pinned image | ❌ out of scope |

**And one difference worth naming.** The PR bodies report
`pytest -m "not e2e"` as *N passed, 52 skipped* (#150 and the state probe both:
**2038 passed, 52 skipped**); CI reports **2090 passed, 0 skipped** for the same
selection, because the runner has the Postgres service the 52 need. Both numbers
are real and they are the same suite. Where this pack quotes a count it says
which.

**One harness hazard the probe had to work around, and it is not fixed.** The
ordinary e2e overlay hardcodes daemon-global image tags —
`arxiv-research-agent:local` and `arxiv-research-agent-web:wo21-e2e`. Two stacks
on one machine therefore contend for the same tags, which is the
`container_name` hazard [§5.4](../../05-WEDGE-WORK-ORDERS.md#54-fleet-coordination-hazards)
already names, one layer down. The probe ran under a **scratchpad overlay with
its own tags**, as §5.4's mitigation requires. ~~Upstreaming interpolated tags
is **queued with WO-W13c**.~~ **Done 2026-09-02 by WO-W13c** (PR #155,
`9fa99b8`): both tags are now interpolated — `E2E_APP_IMAGE`, `E2E_WEB_IMAGE`,
defaults unchanged — and documented in `web/e2e/README.md`.

---

## 7. Recommendation

**W19's two acceptance criteria are met.** Every §6 Gate W1 row resolves to an
artifact in this directory or to an exact citation, each linked to its producing
work order (criterion 1); `known-gaps.md` exists and is non-empty, at seventeen
entries (criterion 2).

**What is resolved at the no-cost boundary.** Seven of §6's ten rows are
resolved outright, one is this pack's own `known-gaps.md`, and one —
per-session cost accounting — is resolved on its own terms with the honest
caveat that every figure it reconciles is a mock-mode figure.

Concretely: a guided-read session can be started from the path view, run,
survive a reload, and close, on the seeded local stack, with the key
disabled, with `llm_calls === 0` read back from the API; the paid path is
structurally interdicted for research and conditionally forwarded for exactly
two session routes under a precondition asserted in two places; four
default-off flags each have an off-position proof; the eval harness's judges,
benchmark, simulator, scripted tier and regression lane are green in per-PR CI;
and the honesty rules are enforced at the type, the merge, the table, the copy
dictionary and the painted page, with a planted fixture proving the last of
those can fire.

**What a ruling would require.** §6's funded-campaign row is **UNRESOLVED**,
and nothing engineering can do will change that. It stands for three runs that
have never happened — the first funded calibration run (W09 c6), the first
funded simulation campaign (W10 c5) and the nightly learning lane's first
scheduled run (W11 c4). They wait on one owner decision, **W-OD-1**: set the
`ANTHROPIC_API_KEY` repository secret, and approve the learning-eval budget
(§2's order of magnitude is **$25–75 per campaign**; WO-W10's card sizes its own
campaign at **$2–6** with a **$15** proposed ceiling, which is also the nightly
lane's default). Their results enter this pack **as priors**, not as
measurements.

So the coordinator has three shapes of ruling available, and this pack states
them rather than choosing:

1. **Close Gate W1 at the no-cost boundary**, with the three unrun campaigns
   carried as named, dated exceptions into Gate W2's memo — the position the
   merged tree supports today, and the one every producing card was built for.
2. **Hold Gate W1 open until W-OD-1 lands**, on the reading that "the agent is
   real and *measurable*" is not demonstrated until something has actually been
   measured with money.
3. **Close it, conditionally, on WO-W13c reporting**: the `cls.spec.ts`
   failure the state probe classifies as **deterministic and
   CI-environment-conditioned** — 2 of 5 main CI runs since `4fbe239`, never on
   a PR, 80/80 green locally, ~~regression window opening at WO-W13's
   `web/lib/job/machine.ts` change~~ (`known-gaps.md` §7). The tutor's
   mastery-frame close line is **no longer** a companion condition: WO-W03b
   closed it in PR #151 (`known-gaps.md` §6), one commit past this baseline.

   **Added 2026-09-02: WO-W13c has reported, and merged.** PR
   [#155](https://github.com/kudratsingh/arxiv-research-agent/pull/155) /
   `9fa99b8` fixed the failure at its cause — the `Live` badge, the only
   non-text item on a baseline-aligned status line, taking its baseline from a
   16px SVG and growing the line 20→23px — with a new browser test that goes
   red without the fix and **20/20 green** with it. **This option's condition is
   met.** The struck clause above is the probe's regression window, which #155
   overturned: the machine is not involved and the defect predates WO-W13
   (§6.1). The coordinator took option **1** on the day
   ([`../../STATUS.md`](../../STATUS.md)); nothing here reopens it, and no §6
   status above moves.

Whichever it is, it belongs in [`STATUS.md`](../../STATUS.md) and not here.
