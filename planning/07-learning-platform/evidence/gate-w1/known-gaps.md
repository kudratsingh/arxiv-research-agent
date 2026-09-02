# Gate W1 — what this pack does *not* prove

WO-W19 acceptance criterion 2: *"`known-gaps.md` exists and is non-empty (an
empty gap list at a gate is the revamp's definition of dishonesty)."*

This is the honest list. Fifteen entries. Each says what is not proven, why it
is not proven, who owns it, and what would change it. Several are ordinary
consequences of the no-cost boundary; two (§6, §12) are inconsistencies inside
the merged tree that a reader would meet as a false or self-defeating sentence;
one (§7) is a real failure on `main` today that a re-run hides.

Assembled against `origin/main` at **`3ccb650`** on 2026-09-02.

---

## 1. No real learner has been observed. Every threshold is a prior.

The most important line in the pack, and it is the plan's own
(`01-LEARNING-AGENT.md` §7.4, restated at the top of every simulation summary):
**simulated learners are not learners.** Everything Gate W1 measures is a
*process* metric.

- The 15-scenario benchmark is authored fiction. Its personas, scripts and
  expected outcomes were written by this project.
- The assessment judge's calibration set is *"a Codex-assisted implementation
  fixture … not composed of real learner sessions, has not been ratified by the
  repository owner/operator, and has not been scored by a live judge"*
  (`docs/eval.md`). It tests data flow and agreement arithmetic and nothing
  else.
- The regression differ's learning bands *"are priors in exactly the same sense
  as the research lane's — reasoned from the mechanics, not measured"*
  (`docs/eval.md`).
- The engagement threshold (≥40% 7-day return) is unratified — it is W-OD-6 and
  it belongs to Gate W2.

**Owner:** the whole programme. **Changes when:** Gate W2's pilot produces
observations, which needs W-OD-5.

## 2. Nothing has ever measured what a guided read costs.

`cost-reconciliation.md` proves the arithmetic and the choke point, not the
price. The CI campaign's measured mean is `$0.0000` because it bought nothing.
`01` §6.1's **$0.07–0.17** per session is a plan estimate, printed beside the
measurement and labelled *not a measurement* in the artifact's own row.

**Owner:** W-OD-1 (the eval half), W-OD-5 (the pilot half).

## 3. The zero-config `docker compose up` demo cannot run a guided session.

`src/config.py` refuses `ENABLE_SESSION_LOOP` without `ENABLE_LEARNER_PROFILE`,
which it refuses without `ENABLE_API_AUTH` (`_check_learner_profile_requires_auth`,
`_check_session_loop_dependencies`). §0's standing constraint is that *"every
merged state leaves `docker compose up` a zero-config, auth-off, single-user
demo in which the learning surfaces render seeded fixture content."* Both hold
— the surfaces render, `ENABLE_LEARN_CONTENT` is on in the compose default —
but **a session cannot be started in that configuration.** `POST /learn/sessions`
answers `404 session_loop_disabled`, and `PathDetailSurface` maps it to *"This
deployment is not running guided sessions…"*.

So the browser evidence for Gate W1's first two rows runs on a **harness**
configuration, not the shipped default. `web/e2e/support/compose.e2e.yml` turns
the whole ladder on and `fixtures/seed.sh` stamps every `baseline-*` row with
the stack's single principal, *"because `_check_ownership` makes a NULL-owner
row invisible under auth-on"* (PR #146). PR #146 flags the blast radius for the
coordinator in its own Tradeoffs section; PR #150 adds the learner profile the
create requires.

**Owner:** unassigned. **Note:** this is a design consequence of ADR 0058 (a
guided session is keyed on a principal), not a bug — but it means the demo a
new reader boots is not the thing Gate W1 proves.

## 4. The browser evidence runs in mock mode. No real model has ever driven a session.

`USE_MOCK_DATA=true` is pinned on the e2e stack and asserted before either
session write is forwarded. Under it, *"the session graph constructs **no**
model client on any path"* — `check_in_agent` takes `_fallback_plan`, and
`_tutor_prompts` returns two constants (`web/e2e/support/mock-mode.ts`,
citing `src/agents/tutor.py:159` and `:248`).

That is the right posture for a cost boundary and it is a real limit on the
claim. What the end-to-end row proves is that **the machinery** — graph,
checkpoint, job lifecycle, transport, reload, close — works. It proves nothing
about the quality of a tutor turn, because no tutor turn has ever been
generated. Every sentence a reader sees on that run is a constant.

**Changes when:** W-OD-1 funds the simulation campaign (the funded tier runs
real models), or W-OD-5 starts the pilot.

## 5. Any change to the session graph or tutor copy must re-record the fixtures.

`tests/test_record_learning_fixtures.py::test_a_fresh_recording_reproduces_the_committed_files`
is deliberately brittle: a re-recording must reproduce the committed transcripts
byte for byte. PR #148 states the consequence in its own Tradeoffs: *"any change
to tutor copy or plan shape fails [it] … it does mean a future card touching the
session graph re-records."* The fix is `make record-learning-fixtures`, and the
failure message names it.

This is a live constraint on **WO-W03b** (§6 below), which changes a tutor
string.

## 6. The tutor's close line plants the frame WO-W14's gate bans one tier down.

`src/agents/tutor.py:486` emits **"This is an activity record, not a mastery
score."** WO-W14 removed exactly this construction from the copy dictionary,
under 03 §5.5's ruling that *the dictionary does not use the word even to deny
it, because a denial plants the frame it rejects*; four WO-W13 sentences were
reworded for it (PR #147's table).

The agent string is outside `web/lib/copy/**` and so outside the gate.
`session-flow.spec.ts` subtracts that one service-authored string before running
the pedagogy scan over the painted page, and says in the code why. PR #150
declined to fix it: *"it is WO-W03's agent, outside this card, and changing it
moves a string the recorded learning fixtures may pin"* (§5 above).

**Owner: WO-W03b, in flight.** Until it merges, a learner who finishes a
guided session reads the word "mastery" on the close.

## 7. `e2e/cls.spec.ts` fails on `main`, on two consecutive commits, and a re-run hides it.

Not a one-off. Verbatim log in
[`artifacts/ci-e2e-cls-failure.txt`](artifacts/ci-e2e-cls-failure.txt).

| Run | Head | Attempt 1 | Attempt 2 |
|---|---|---|---|
| [33619832961](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33619832961) | `4fbe239` (#146) | **`web e2e` failed** — cls only | 8/8 success |
| [33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183) | `3ccb650` (#150) | **`web e2e` failed** — 1 failed, 52 skipped, 263 passed | 8/8 success — **264 passed, 52 skipped, 0 failed** |

Identical signature both times: `Received: "0.039"` against `Expected:
"0.000"`, from two shift entries whose nodes move **282→285 / 326→329 /
250→253** — three pixels down on one frame and three pixels back on the next,
14 ms later. It survives Playwright's own retry (`retry #1` fails too) and
passes on a fresh job.

`theme.spec.ts`'s *"a stored dark preference survives hydration"* also prints
`✘` in both runs, but it carries `test.fail(true, …)` — a **known, documented**
defect, expected to fail, not counted. The cls failure is the only real one.

**The rest of this pack cites attempt 2 of run 33630982183, which is green.**
It does so knowing that attempt 1 of the same run was not, and the pack does not
treat a passing re-run as evidence that the first run did not happen: two
consecutive heads needed one to go green. **Owner:** unassigned — it is WO-20's
spec (`e2e/cls.spec.ts`, `03` §5.6's no-translation rule) and neither WO-W13 nor
WO-W13b touches what `/` renders. It should be assigned before Gate W1 closes.

## 8. Three parts of the browser evidence exist only as local runs.

CI is the canonical evidence everywhere else in this pack. These three are not
in it, and each PR says so.

| Not in CI | Why | Where it ran |
|---|---|---|
| **The darwin visual baselines** (48 PNGs, 10 regenerated by #150) | CI runs linux, where no snapshot set is committed and `visual.spec.ts` skips by its own guard | PR #150, locally, on the final tree |
| **The pilot two-principal spec** (`pilot.spec.ts`, 3 tests) | needs a third overlay and a Caddy edge, and *"no Phase W card edits a workflow"* (§5.4). CI reports **3 skipped, with the reason printed** | PR #149, locally |
| **The `.next/static` key scan** | `npm test` runs *before* `npm run budgets`, so `.next/` does not exist and the test is `it.runIf`-skipped | PR #149, locally against a real build — 63 files, 0 hits |

`deploy/pilot/compose.pilot.yml` is likewise not validated by CI (PR #149).

## 9. `total-transferred-js` is still an unmeasured EXTERNAL budget row.

`web/budgets.json:255` carries it as `"kind": "external-total-transferred-js"`,
`"enforcement": "external"`. ADR 0056 already recorded that it *"has no
measurement behind it"*; PR #146's Deferred note repeats it —
*"the WO-21 Playwright transfer assertion it names was never written, unchanged
by this PR."* Nine gated rows pass on `3ccb650`; this is the tenth and it is
not one of them.

## 10. SR-09 at the shipped defaults computes to $67,200.

PR #149's runbook work found it: at the repository's committed defaults SR-09's
formula gives `5 × 20 × 336 × $2.00 = $67,200`. PR #149: *"That is not a bound
anyone would accept, which means **W-OD-5 cannot approve 'the defaults' — it
has to approve values**."* The runbook inverts the formula and ranks the
levers; `evidence/gate-w2/pilot-record.md` §2 holds the table with every number
`_pending_`.

Gate W2's problem, recorded here because it is a *consequence of Phase W's
shipped defaults* and Gate W1 is where those defaults were set.

## 11. Gate W1's end-to-end row was unreachable in a browser until six hours ago.

WO-W13 shipped `/learn/sessions/[id]` and said so in its own Deferred note:
*"Nothing in the browser calls `createLearnSession` yet."* Until PR
[#150](https://github.com/kudratsingh/arxiv-research-agent/pull/150) merged as
`3ccb650` at **2026-09-02T12:37:38Z**, Gate W1's first row had no starting point
and its second could only be tested against a session seeded by hand.

WO-W13b was **coordinator-added** to close that plan gap — no card in the
original §5 owned the session-start action. The consequence for this pack: the
end-to-end row rests on a spec that has been on `main` for one CI run, and that
run's `web e2e` job failed for the unrelated reason in §7.

## 12. WO-W17 merged at half its scope; the identity copy on the pilot path is wrong.

PR #149 shipped the no-cost half (ADR 0063). Criterion 5 — live pilot sessions —
is **deferred to W-OD-5** and *"nothing here is authorised to run."*

It also found a string it could not fix: the shell renders *"Shared workspace —
Everyone with access to this deployment sees these threads. There are no
separate accounts."* (`web/lib/copy/threads.ts:204-206`). Under
`PILOT_EDGE_AUTH=on` **neither clause is true**. `web/lib/copy/**` was WO-W14's
this wave, so the discrepancy was written into ADR 0063 §Consequences,
`docs/security.md`, `docs/architecture.md` and `evidence/gate-w2/pilot-record.md`
§6 instead of being edited. PR #149: *"This must be resolved before an
invitation is sent. It is a false statement about data separation, shown to the
people the separation is for."*

**Owner: WO-W17b, in flight**, under an SR-07-compliant server-resolved
descriptor.

## 13. The recorded W08/W03 divergence was resolved by moving an expectation.

WO-W11 c7 resolved `engineer-rlhf-profile-note-injection`'s
`max_plan_sections=1` in favour of **the graph's documented rule**: the
scenario's expectation moved to `2`, and no graph behaviour changed. The
reasoning is written out in PR #148 and `docs/eval.md` (the scenario is
adversarial, not time-poor; the two genuinely time-poor scenarios declare 10
minutes and expect 1; the two other 15-minute scenarios both expect 2).

It is defensible and it is recorded, and it is still a case where the
**benchmark moved to match the implementation**. The benchmark is this
project's own fiction (§1), so nothing external disagreed — which is exactly
why it belongs on this list rather than in a passing test's shadow.

## 14. The judge is never driven end-to-end, and the assessment path has no browser proof.

`ENABLE_ASSESSMENT_JUDGE` is default-off and *"remains tutor guidance until its
calibration prior is owner-ratified"* (`src/config.py`). The `Session/Probe`
story renders the `follow_up_probe` turn shape; PR #146's Deferred note:
*"no e2e drives the judge, because the judge needs a model."* Every recorded
fixture closes `recorded_ungraded`, and the CI campaign's Assessment column
reads `recorded_ungraded` or `none` on all 15 rows
([`artifacts/scripted-simulation-summary.md`](artifacts/scripted-simulation-summary.md)).

So the honesty inventory's evidence-quoting row (§3 of
[`honesty-inventory.md`](honesty-inventory.md)) is proven **at the unit
boundary** and nowhere above it.

## 15. Small-N, single-repeat, and one snapshot's worth of coverage.

- **The simulation ran one repeat per scenario.** The summary prints its own
  WARNING: *"3 repeats are the bar before a delta against a baseline is
  believable on an LLM-judged benchmark this small … Read single-run
  differences as noise, not as a regression."*
- **The Ledger has no state in the browser tier's `states.ts` table** (PR
  #147's Deferred note) — the story tier covers all four states in both themes,
  and the axe sweep's report-for-report diff has nothing to compare a new row
  against.
- **`web/vitest.config.mts`'s `branches` floor sits inside measured variance.**
  Three PRs in a row recorded it: #147 saw 93.82 / 93.87 / 93.82, #150 saw
  94.07 three times and 94.03 on a fourth and seeded at 94.0 for that reason.
  The floors are honest; they are not tight.
- **Ledger export is not built**, and §7 not-scheduled says it will not be.
  `sessions_per_day` is deliberately not rendered, *"because a per-day grid is
  one CSS change from a streak calendar"* (PR #147).
