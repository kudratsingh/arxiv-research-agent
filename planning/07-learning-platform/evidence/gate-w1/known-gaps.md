# Gate W1 — what this pack does *not* prove

WO-W19 acceptance criterion 2: *"`known-gaps.md` exists and is non-empty (an
empty gap list at a gate is the revamp's definition of dishonesty)."*

This is the honest list. **Seventeen entries, one of them now resolved.** Each
says what is not proven, why it is not proven, who owns it, and what would
change it. Several are ordinary consequences of the no-cost boundary; §12 is an
inconsistency inside the merged tree that a reader would meet as a false
sentence; §7 and §16 are real test failures a re-run hides, and §7 is on `main`.

**§6 is resolved** — by WO-W03b (PR #151, `1026534`), one commit after this
pack's baseline. It is kept, struck through and marked, because a gap list that
quietly loses its closed items cannot be audited. Its fix introduced **§17**.

Assembled against `origin/main` at **`3ccb650`** on 2026-09-02, and revised
against the **coordinator state-probe of main `3ccb650`, 2026-09-02** — an Opus
agent run, not a CI run. The probe found main **HEALTHY on every tier**
([`README.md`](README.md) §6.1); it also **corrected §7** and **added §16**,
and both corrections are kept visible rather than silently applied.

Two cards are in flight against three of the seventeen: **WO-W13c**
(`fix/w13c-cls-conversation-route` — §7 and §8) and **WO-W17b**
(`feat/w17b-pilot-identity-slot` — §12). Neither is merged, and neither changes
a §6 status in [`README.md`](README.md).

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

It bound **WO-W03b** immediately: PR #151 changed one tutor string and
re-recorded **all fifteen** fixtures in the same commit (§6). The first real
encounter with this test went exactly as PR #148 said it would.

## 6. ~~The tutor's close line plants the frame WO-W14's gate bans one tier down.~~ — **RESOLVED**

**Resolved by WO-W03b, PR [#151](https://github.com/kudratsingh/arxiv-research-agent/pull/151),
merged 2026-09-02T13:08:18Z as `1026534`.** The entry is kept rather than
deleted, because a gap list that quietly loses its closed items cannot be
audited.

**What it was.** `src/agents/tutor.py:486` emitted **"This is an activity
record, not a mastery score."** WO-W14 removed exactly this construction from
the copy dictionary, under 03 §5.5's ruling that *the dictionary does not use
the word even to deny it, because a denial plants the frame it rejects*; four
WO-W13 sentences were reworded for it (PR #147's table). The agent string sat
outside `web/lib/copy/**` and so outside the gate, and PR #150 declined to fix
it: *"it is WO-W03's agent, outside this card, and changing it moves a string
the recorded learning fixtures may pin"* (§5 above).

**What replaced it**, `src/agents/tutor.py:492` at `1026534`:

> The lines above are this session's activity record, drawn from the events it
> wrote.

It states what the session did instead of denying a scalar. PR #151's own
summary: *"The two system prompts keep their prohibitions — they address the
model, not the learner."*

**Three consequences worth recording.**

1. **WO-W13b's carve-out is gone.** `session-flow.spec.ts` no longer subtracts
   a service-authored string before scanning the painted page — PR #151: *"The
   subtraction is gone; the whole page is asserted."* The pedagogy gate now
   covers the rendered session end to end.
2. **§5 fired exactly as predicted.** All **fifteen** recorded fixtures were
   re-recorded in the same PR, which is the brittle freshness test doing its
   job on its first real encounter.
3. **It added a new, smaller gap** — the hand-maintained backend mirror. See
   **§17**.

**This landed one commit *after* this pack's baseline.** The pack is assembled
against `3ccb650`; `1026534` is its child. This entry and **§17** are the only
two places in this directory that describe anything but `3ccb650` — said here
rather than by silently re-basing the pack around a late fix.

## 7. `e2e/cls.spec.ts` fails on `main`, on 2 of the last 5 runs, and a re-run hides it.

Not a one-off. Verbatim log in
[`artifacts/ci-e2e-cls-failure.txt`](artifacts/ci-e2e-cls-failure.txt).

| Run | Head | Attempt 1 | Attempt 2 |
|---|---|---|---|
| [33619832961](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33619832961) | `4fbe239` (#146) | **`web e2e` failed** — cls only | 8/8 success |
| [33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183) | `3ccb650` (#150) | **`web e2e` failed** — 1 failed, 52 skipped, 263 passed | 8/8 success — **264 passed, 52 skipped, 0 failed** |

Identical signature both times: `Received: "0.039"` against `Expected:
"0.000"`, from two shift entries whose nodes move **282→285 / 326→329 /
250→253** — three pixels down on one frame and three pixels back on the next,
~15 ms later. It survives Playwright's own retry (`retry #1` fails too) and
passes on a fresh job.

`theme.spec.ts`'s *"a stored dark preference survives hydration"* also prints
`✘` in both runs, but it carries `test.fail(true, …)` — a **known, documented**
defect, expected to fail, not counted. The cls failure is the only real one.

### What the state probe established, and what it corrects

An earlier draft of this entry called it "two consecutive heads of `main`".
**That was wrong**, and the coordinator state-probe of main `3ccb650`,
2026-09-02 measured the real shape:

- **2 of 5 main CI runs since `4fbe239`** — the runs for `4fbe239` and
  `3ccb650`. Three green runs sit between them (`ba3e576`, `a9e26bf`,
  `5bcf373`), so the two occurrences are **not** consecutive.
- **Never on a PR run.** Only on `main`.
- **80/80 green locally**, at **4 and at 12 workers** — so it is not a load or
  contention effect that local oversubscription can reproduce.
- **Three candidate causes eliminated by measurement**: a mono-font swap, the
  Live badge mount, and the ledger reserve.
- **Classified as deterministic and CI-environment-conditioned**, not as a
  random flake — which is a materially worse finding than "flaky", because a
  deterministic failure that only the CI environment expresses will keep
  recurring on `main` until the environmental condition is named.
- **The regression window opens at WO-W13's `web/lib/job/machine.ts` change**,
  which is the first plausible edge in the range.

The spec is WO-20's (`e2e/cls.spec.ts:50`, criterion 5, `03` §5.6's
no-translation rule on `/c/[id]`), and neither WO-W13 nor WO-W13b touches what
that route renders — but the window makes W13 the place to start looking rather
than a coincidence to note.

**Owner: WO-W13c, in flight** (`fix/w13c-cls-conversation-route`). Its plan, in
order: pull the retained CI trace from run
[33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
reproduce inside the Playwright **Linux** container, and **fix at the cause** —
not by widening the assertion, which would delete the only evidence that `03`
§5.6's no-translation rule is being kept.

The same card also **interpolates the e2e overlay's daemon-global image tags**
(§8), because a reproduction attempt needs a second stack on one machine and
that is precisely what the hardcoded tags prevent.

**The rest of this pack cites attempt 2 of run 33630982183, which is green.** It
does so knowing that attempt 1 of the same run was not, and the pack does not
treat a passing re-run as evidence that the first run did not happen. **This
entry stays open until WO-W13c reports**, and a Gate W1 ruling should say
explicitly whether it blocks.

## 8. Three parts of the browser evidence exist only as local runs.

CI is the canonical evidence everywhere else in this pack. These three are not
in it, and each PR says so.

| Not in CI | Why | Where it ran | Probe |
|---|---|---|---|
| **The darwin visual baselines** (48 PNGs, 10 regenerated by #150) | CI runs linux, where no snapshot set is committed and `visual.spec.ts` skips by its own guard | PR #150, locally, on the final tree | ✅ 48 compared, all passing |
| **The `.next/static` key scan** | `npm test` runs *before* `npm run budgets`, so `.next/` does not exist and the test is `it.runIf`-skipped | PR #149, locally against a real build — 63 files, 0 hits | ✅ 74 passed |
| **The pilot two-principal spec** (`pilot.spec.ts`, 3 tests) | needs a third overlay and a Caddy edge, and *"no Phase W card edits a workflow"* (§5.4). CI reports **3 skipped, with the reason printed** | PR #149, locally | ❌ skipped there too |

`deploy/pilot/compose.pilot.yml` is likewise not validated by CI (PR #149), and
the probe did not cover it either.

**The coordinator state-probe of main `3ccb650`, 2026-09-02 shrank this gap
from three items to one.** The darwin set and the `.next/static` scan are now
proven on the merged tree by something other than the PR that wrote them, which
is the stronger claim; the pilot spec still rests on PR #149's own local run and
will until a pilot deployment exists (W-OD-5). The probe is an Opus agent run,
not a CI job, so it does not make either item *automated* — it makes them
**independently reproduced once, on `main`**.

**And the harness has a hazard of its own.** The ordinary e2e overlay hardcodes
daemon-global image tags (`arxiv-research-agent:local`,
`arxiv-research-agent-web:wo21-e2e`), so two stacks on one machine contend for
the same tags — the `container_name` hazard §5.4 already names, one layer down.
The probe worked around it with a scratchpad overlay carrying its own tags.
Upstreaming interpolated tags is **queued with WO-W13c**; until then, anyone
running a second stack must do what the probe did.

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

**Owner: WO-W17b, in flight** (`feat/w17b-pilot-identity-slot`), under an
**SR-07-compliant server-resolved descriptor** — the identity the shell states
is resolved on the server and handed down, rather than a client-side guess at
which mode the deployment is in. That shape is why it is a card and not a copy
edit: the true sentence differs per deployment, and only the server knows
which.

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

## 16. `theme.spec.ts:186` flakes on webkit, ~3 runs in 10.

Found by the coordinator state-probe of main `3ccb650`, 2026-09-02, in the
nightly browser matrix: firefox + webkit + Pixel 7 + iPhone 15 read **113
passed, 10 skipped, 1 failed**, and the one failure is `e2e/theme.spec.ts:186`
— *"the theme control is reachable and writes exactly one key"* — on **webkit
only**, at roughly **3 in 10**.

**It is pre-existing and it is not this train's.** No theme, shell or token
source file changed across WO-W01 … WO-W13b. WO-W13's PR #146 already named the
same test as *"a flake: it passes on re-run"* on chromium; the probe establishes
that webkit expresses it far more often.

It is distinct from the `theme.spec.ts:123` hydration defect, which is
`test.fail(true, …)` — declared, expected, and not a gap. This one is an
undeclared intermittent.

**Not in per-PR CI at all:** the `web-e2e` job runs `--project=chromium`, so
the multi-browser matrix is nightly-only and a webkit regression cannot fail a
PR. **Owner:** unassigned; WO-01 owns the theme foundation and WO-08 owns
`ThemeToggle`. It does not touch a Gate W1 row — no learning surface is
implicated — and it is recorded because a pack that lists only the failures
inside its own scope is the sales document this file exists to prevent.

## 17. The pedagogy deny-list now exists twice, and the copies are kept in step by hand.

Introduced by the fix for §6. WO-W03b (PR
[#151](https://github.com/kudratsingh/arxiv-research-agent/pull/151), `1026534`)
needed the pedagogy ban to bind the **backend's** strings, because the session
surface renders `SessionDetail.result` verbatim (RC-16/H11) — so a phrase the
copy dictionary may not contain can still reach a learner if the tutor emits it.
It added `PEDAGOGY_DENY_LIST` in `tests/test_simulate_learner.py:315`: twelve
`(phrase id, regex)` pairs mirroring WO-W14's `PEDAGOGY_PHRASES` in
`web/lib/copy/index.ts`.

**The mirror is hand-maintained, and the module says so in its own docstring:**

> The canonical list is `PEDAGOGY_PHRASES` in `web/lib/copy/index.ts` (owned by
> WO-W14, inside the append-only fence); that gate is the authority […] Kept
> small and deliberately re-typed rather than generated — a Node dependency in
> a Python unit test would be a worse coupling than a list two reviewers can
> diff by eye. Adding an entry there without adding it here costs nothing; the
> reverse is what this guard is for.

**The trade is argued and it is still a trade.** The asymmetry is real and it is
the right way round: a phrase added to the web list but not the Python one
leaves the backend guard *weaker*, never wrong, and the web gate still holds
every copy module. But there is **no test that the two lists agree**, and
nothing fails when they drift — unlike WO-W07's ledger ban, where
`test_the_database_ban_and_the_python_ban_are_the_same_list` asserts exactly
that property across its two copies. The precedent for a cross-tier list
equality check exists in this repository; this pair does not use it.

**Owner:** unassigned. **Changes when:** either a generated list replaces the
re-typed one, or an equality assertion is added in the shape WO-W07 already
uses. Neither is Gate W1's to require — the gap is one release of drift wide,
not a live defect — but it should not go unrecorded, because the fix for a
honesty gap quietly created a second place honesty rules have to be maintained.
