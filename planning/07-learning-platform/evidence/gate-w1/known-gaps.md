# Gate W1 — what this pack does *not* prove

WO-W19 acceptance criterion 2: *"`known-gaps.md` exists and is non-empty (an
empty gap list at a gate is the revamp's definition of dishonesty)."*

This is the honest list. **Twenty entries, five of them now resolved.** Each
says what is not proven, why it is not proven, who owns it, and what would
change it. Several are ordinary consequences of the no-cost boundary; §12 was an
inconsistency inside the merged tree that a reader would meet as a false
sentence, and it is fixed; §7 and §16 were real test failures a re-run hides —
§7 was on `main` until WO-W13c fixed it, and §16 turned out not to be a flaky
probe at all but a product defect the probe was catching, which is the
correction this file's own classification needed.

**Five entries are resolved**, each kept, struck through and marked, because a
gap list that quietly loses its closed items cannot be audited:

- **§6** — by WO-W03b (PR #151, `1026534`), one commit after this pack's
  baseline. Its fix introduced **§17**.
- **§7** — by WO-W13c (PR #155, `9fa99b8`), five commits after it. That fix also
  closed the tag hazard recorded at the foot of **§8**, and overturned two of
  the state probe's findings, which §7 records rather than deletes.
- **§12** — by WO-W17b (PR #153, `72e65b9`), which merged six minutes *before*
  this pack did. What closed is the false statement about data separation; the
  entry's other half, WO-W17's deferred criterion 5, still waits on W-OD-5.
- **§16** — by PR #160 (`337dbe4`), 2026-09-04, **and reclassified in the
  closing**: what this entry called an undeclared intermittent was a product
  defect in `ThemeToggle`, permanent for the user who hits it, which the probe
  was reporting honestly.
- **§17** — by PR #157 (`93a6caa`), 2026-09-04, in the shape the entry's own
  "changes when" clause named: an equality assertion on the WO-W07 precedent.

**Added 2026-09-04 — a four-PR follow-up wave.** Merged the same day by the
coordinator under the standing delegation, in this order: #157 (`93a6caa`),
#158 (`5b7ec23`), #160 (`337dbe4`), #159 (`2001d1b`). It closes **§16** and
**§17** above and opens **§18**, **§19** and **§20** below. The execution
record — including two process findings that belong there and not here — is
[`../../STATUS.md`](../../STATUS.md). **No §6 status in
[`README.md`](README.md) moves on account of it**, for the same reason the
earlier late fixes moved none: they are commits past this pack's baseline.

Assembled against `origin/main` at **`3ccb650`** on 2026-09-02, and revised
against the **coordinator state-probe of main `3ccb650`, 2026-09-02** — an Opus
agent run, not a CI run. The probe found main **HEALTHY on every tier**
([`README.md`](README.md) §6.1); it also **corrected §7** and **added §16**,
and both corrections are kept visible rather than silently applied. Two of the
probe's own §7 findings were themselves wrong, and PR #155 corrected them; that
correction is kept visible too, in §7.

Two cards were in flight against three of the seventeen entries this pack was
assembled with, and **both have since merged**: **WO-W13c** (§7 and §8) as PR #155,
`9fa99b8`, and **WO-W17b** (§12) as PR #153, `72e65b9`. All three entries are
marked below. Neither card changes a §6 status in [`README.md`](README.md).

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
~~citing `src/agents/tutor.py:159` and `:248`~~). **Corrected 2026-09-04:**
`mock-mode.ts` no longer cites line numbers. PR #158 (`5b7ec23`) replaced eight
`src/agents/tutor.py:NNN` citations under `web/` with symbol references, having
first established that **all four distinct cited line numbers were already
stale** at `dce6e42` — including these two, which had drifted to `165` and `254`
and landed on neither symbol their own sentence names. The quotation above is
kept as this pack wrote it; the claim it supports is unchanged.

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
against `3ccb650`; `1026534` is its child. This entry and **§17** were the only
two places in this directory that describe anything but `3ccb650` — said here
rather than by silently re-basing the pack around a late fix. **§7, §8 and §12
now do too**, for the same reason and in the same way: WO-W13c merged as
`9fa99b8`, five commits past the baseline, and WO-W17b as `72e65b9`, two.

## 7. ~~`e2e/cls.spec.ts` fails on `main`, on 2 of the last 5 runs, and a re-run hides it.~~ — **RESOLVED**

**Resolved by WO-W13c, PR [#155](https://github.com/kudratsingh/arxiv-research-agent/pull/155),
merged 2026-09-02T13:47:17Z as `9fa99b8`.** The entry is kept rather than
deleted, and so is the diagnosis it carried, because a gap list that quietly
loses its closed items cannot be audited — and one that quietly loses its wrong
answers teaches the next probe nothing. **Two of the state probe's findings
below are wrong.** They are struck where they stand and corrected under *"What
the probe got right, and where its elimination failed"*.

**The cause.** The spine's status line is `flex flex-wrap items-baseline`, and
`StatusBadge` is the only item on it that is not text. As a flex item it is
blockified to `display:flex`, and a flex container's baseline is taken from its
**first** flex item — the 16px `Mark`, an SVG with no text baseline — so
Chromium synthesises the badge's baseline from its bottom edge, three pixels
below where the text beside it puts its own. Aligning the two **grows** the
line, and the growth pushes the paragraph's own children down. PR #155's direct
measurement, taken by parking the surface in the live state:

| | line height | announcement `top` | detail `top` |
|---|---|---|---|
| badge on the line | **23** | **253** | **253** |
| badge absent | 20 | 250 | 250 |

*"The CI numbers, exactly — and on macOS as well as Linux"* (#155). So the
geometry was never platform-specific; only the *painting* was environmental.
The badge mounts when the stream's headers land and unmounts when its body ends,
and **only a 2-vCPU runner is slow enough to paint the frame in between** —
everywhere else React coalesces the two commits into none.

An element that grows in place has not shifted, so it never appears in
Chromium's `sources`. That is why the entry's own tell was the *absence* of
movement: `span.ew-spine-void` reads `197→197` because it moved **35px
sideways**, not down, and *"nothing above y=250 moved down"* (#155).

**The fix** is one property: `.ew-spine-live { align-self: center }` in
`web/components/patterns/spine.css`, applied to the badge in `TraceSpine.tsx`.
The badge's height already equals `--text-ui-sm-line`, so a centred badge
occupies the line exactly and mounting or unmounting it moves nothing. **No
height is pinned** — the line still wraps at 320px, which a fixed height would
forbid, and `min-height` could not have caught a line that *grew*.

**What now catches it.** A new `cls.spec.ts` test parks the surface in the live
state with a real open stream and asserts the line's two numbers; on the Linux
container (`playwright:v1.62.1-noble`, `--repeat-each=10`) it was **1/1 red
including the retry** before the fix and **20/20 green** after, with the old
spec 10/10 green throughout. The full `chromium` project on macOS reads **314
passed, 3 skipped, 0 failed** after. `TraceSpine.test.tsx` holds the class to
the badge in exactly the states that render one, and holds the row to
`items-baseline` — the fix is the badge stepping out of that alignment, not the
row giving it up. **The CLS attribution itself is hardened**: it now prints
whole rects for both frames plus each source's *parent* with its computed
styles, because the thing that grew is the thing one level up. Budgets: no
ceiling moved (emitted CSS **11,335 → 11,365 B** against 12,288); coverage held.
Four darwin PNGs were retaken — `running` and `plan-review`, 1440px, light and
dark, the only sweep states whose stream stays open — because the committed
pixels had the defect baked in.

**What it was, as recorded before the fix**, kept below.

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
- ~~**Three candidate causes eliminated by measurement**: a mono-font swap, the
  Live badge mount, and the ledger reserve.~~ — **WRONG on one of the three.**
  The **Live badge mount is the cause** (#155). The mono-font swap and the
  ledger reserve stand eliminated.
- **Classified as deterministic and CI-environment-conditioned**, not as a
  random flake — which is a materially worse finding than "flaky", because a
  deterministic failure that only the CI environment expresses will keep
  recurring on `main` until the environmental condition is named.
- ~~**The regression window opens at WO-W13's `web/lib/job/machine.ts` change**,
  which is the first plausible edge in the range.~~ — **WRONG.** The machine is
  not involved; `awaiting_learner`/`turn_ready` and the transition table are
  untouched by the fix. **The defect predates WO-W13**, which changed this
  route's *timing* — auth on, a heavier stack — and not its geometry.

~~The spec is WO-20's (`e2e/cls.spec.ts:50`, criterion 5, `03` §5.6's
no-translation rule on `/c/[id]`), and neither WO-W13 nor WO-W13b touches what
that route renders — but the window makes W13 the place to start looking rather
than a coincidence to note.~~ The spec is still WO-20's, at the same line and
under the same rule; the sentence about the window is not — W13 is where the
*timing* changed, not where the defect entered.

### What the probe got right, and where its elimination failed

**Right, and it mattered.** The classification — *deterministic and
CI-environment-conditioned, not flaky* — is exactly what #155 found: fixed
geometry, reproducible on demand once the surface is parked in the live state,
with only the paint of the intermediate frame conditioned on a slow runner. The
shape it measured (2 of 5 main runs, never on a PR, 80/80 green locally at 4 and
at 12 workers) is unchanged, and it is what ruled out load and contention.

**Where it failed.** Per #155: *"the earlier elimination of 'the Live badge
mount' was measuring the settled DOM, where the badge is already gone."* The
probe's sampling window did not include the mount frame — the badge is on the
line only between the stream's headers landing and its body ending — so the one
state that expresses the defect was never in the sample. An elimination is only
as strong as the window it samples, and this one was measured outside it.

**Owner: WO-W13c — merged** (PR #155, `9fa99b8`). It did what its plan said, in
order: pulled the retained CI trace from run
[33630982183](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33630982183),
reproduced inside the Playwright **Linux** container, and **fixed at the
cause** — not by widening the assertion, which would have deleted the only
evidence that `03` §5.6's no-translation rule is being kept.

The same card also **interpolated the e2e overlay's daemon-global image tags**
(§8), because a reproduction attempt needs a second stack on one machine and
that is precisely what the hardcoded tags prevented.

**The rest of this pack cites attempt 2 of run 33630982183, which is green.** It
does so knowing that attempt 1 of the same run was not, and the pack does not
treat a passing re-run as evidence that the first run did not happen. **This
entry stayed open until WO-W13c reported**; it reported on 2026-09-02 with the
cause above, and the Gate W1 ruling in [`../../STATUS.md`](../../STATUS.md) had
already recorded that it did not block the close.

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
~~Upstreaming interpolated tags is **queued with WO-W13c**; until then, anyone
running a second stack must do what the probe did.~~ **Done: WO-W13c (PR #155,
`9fa99b8`, 2026-09-02) interpolated both tags** — `E2E_APP_IMAGE` and
`E2E_WEB_IMAGE`, defaults unchanged, documented in `web/e2e/README.md` with the
five exports a second worktree needs. The three local-only items in the table
above are unaffected; this paragraph's hazard is the part that closed.

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

## 12. ~~WO-W17 merged at half its scope; the identity copy on the pilot path is wrong.~~ — **RESOLVED**

**Resolved by WO-W17b, PR [#153](https://github.com/kudratsingh/arxiv-research-agent/pull/153),
merged 2026-09-02T13:22:38Z as `72e65b9`** — six minutes before this pack itself
landed (`f6fce61`, 13:29:05Z), so the entry was already describing a sentence
that had left `main`. It is kept, struck through and marked, for the same reason
§6 and §7 are.

**The fix, in one sentence.** `web/lib/server/identity.ts` derives a
serialisable per-request descriptor — `{kind:"shared"} | {kind:"pilot",
username} | {kind:"unresolved"}` — *"from the **same** environment and the
**same** two edge headers `lib/server/pilot.ts` already reads for the credential
seam"*, and hands it to the shell as a prop, so *"the shell renders what it is
handed and has no branch of its own to be wrong about"* (#153); **mode off is
byte-identical, proved twice** — in jsdom against the pre-change JSX, and by
diffing the SSR bytes of `/` between containers built on `3ccb650` and on the
branch — and the pilot e2e read **5 passed** on an isolated local stack. No
runtime flag was added to `web/`, per SR-07.

**What #153 did not close is a deferral, not a defect.** The heading's first
clause stands: WO-W17's criterion 5 — live pilot sessions — still waits on
**W-OD-5**, which §10 says must approve concrete SR-09 values rather than the
shipped defaults. What closed is the false statement about data separation.

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

**Owner: WO-W17b — merged** (PR #153, `72e65b9`), under an **SR-07-compliant
server-resolved descriptor** — the identity the shell states is resolved on the
server and handed down, rather than a client-side guess at which mode the
deployment is in. That shape is why it was a card and not a copy edit: the true
sentence differs per deployment, and only the server knows which.

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

## 16. ~~`theme.spec.ts:186` flakes on webkit, \~3 runs in 10.~~ — **RESOLVED**

**Resolved by PR [#160](https://github.com/kudratsingh/arxiv-research-agent/pull/160),
merged 2026-09-04T07:10:45Z as `337dbe4`.** The entry is kept, struck through
and marked, for the same reason §6, §7, §12 and §17 are.

**This entry's own classification was wrong, and that is the finding.** It
called the failure *an undeclared intermittent* — a flaky probe, owned by
nobody, not touching a Gate W1 row. It was **a product defect that the probe was
catching**, and the flake was only its most reproducible symptom. #160's own
words: *"The probe asserted exactly what a user expects."*

**What the defect is.** A label click on the theme control that lands **before
React attaches** checks the radio natively. `onChange` is not there yet, so
nothing is written; and React does not reset a hydrated input's checked state,
so after hydration the control sits showing **Dark** while `data-theme` stays
`light` and `localStorage` is empty — **permanently, not for a frame**. Anyone
on a slow connection gets a control that silently drops their click and then
lies about it.

**The evidence chain, and why the old classification could not see it.**

- Every failure landed on the **`data-theme` assertion** —
  `expect(html).toHaveAttribute("data-theme", "dark")`, received `light`, with
  `data-theme-preference="system"` — and **never** on the `toBeChecked()`
  assertion above it. The radio *was* checked; the theme *was not* applied.
- An in-page probe at the moment of the click found **no `__react*` keys** on
  the dark `<input>`: React had not attached.
- Holding `**/_next/static/chunks/**` until after the click made it
  deterministic — **4/4 on chromium and webkit alike**. So the engine only
  decided *how often the race was lost*, not whether the defect existed. "Webkit
  only" was a sampling artefact, exactly as §7's failed elimination was.

**Counts.** Before, on a seeded local stack at `--retries=0`:
`theme.spec.ts -g "exactly one key" --project=webkit --repeat-each=20` read
**3 failed, 17 passed**. After: **120 passed, 0 failed** on webkit and **120
passed, 0 failed** on chromium at the same repeat; the full chromium project
read **315 passed, 5 skipped, 0 failed** — one more test than before, the new
one.

**The fix.** One mount effect in `ThemeToggle.tsx` reads back the radio the
group actually carries and finishes the interaction. It writes only when that
value is neither the live preference (nothing happened) nor
`serverThemePreference()` (React has not re-rendered from the client snapshot
yet), so an ordinary load with a stored preference can never be mistaken for a
user choosing "system". Both guards are value comparisons, not assumptions about
when `useSyncExternalStore`'s re-render lands. It is declared **after** the
existing `system` effect deliberately, which would otherwise overwrite the
adopted choice a moment later.

Two new tests, **both red on the parent commit**: `e2e/theme.spec.ts`'s *"a
choice made before hydration is not dropped"*, which holds the client chunks
until after the click so the window is entered on purpose (red on chromium
**and** webkit without the fix), and three `tests/shell/themeToggle.test.tsx`
cases hydrating over `renderToString` markup mutated the way a native label
activation mutates it.

**The residual, recorded in the source.** A pre-hydration click on **the option
the server already rendered as checked** changes no DOM state and fires no
event, so the effect cannot see it and nothing can. That case stays undetectable
and is written down where the fix lives rather than claimed closed here.

**Untouched:** the `theme.spec.ts:123` hydration defect, which carries
`test.fail(true, …)`. It is still declared, still expected, and it *"still fails
as declared in all 40 post-fix runs"* (#160).

**What it was, as recorded before the fix**, kept below.

Found by the coordinator state-probe of main `3ccb650`, 2026-09-02, in the
nightly browser matrix: firefox + webkit + Pixel 7 + iPhone 15 read **113
passed, 10 skipped, 1 failed**, and the one failure is `e2e/theme.spec.ts:186`
— *"the theme control is reachable and writes exactly one key"* — on **webkit
only**, at roughly **3 in 10**.

**It is pre-existing and it is not this train's.** No theme, shell or token
source file changed across WO-W01 … WO-W13b. WO-W13's PR #146 already named the
same test as *"a flake: it passes on re-run"* on chromium; the probe establishes
that webkit expresses it far more often. — **This half stands**: the defect is
in `ThemeToggle`, which WO-08 shipped, and no Phase W card touched it.

It is distinct from the `theme.spec.ts:123` hydration defect, which is
`test.fail(true, …)` — declared, expected, and not a gap. ~~This one is an
undeclared intermittent.~~ — **WRONG.** It was an undeclared *defect*, expressed
intermittently. Calling the symptom the thing is what kept it unowned.

**Not in per-PR CI at all:** the `web-e2e` job runs `--project=chromium`, so
the multi-browser matrix is nightly-only and a webkit regression cannot fail a
PR. ~~**Owner:** unassigned; WO-01 owns the theme foundation and WO-08 owns
`ThemeToggle`.~~ — **Owner: PR #160, merged.** ~~It does not touch a Gate W1 row
— no learning surface is implicated —~~ and it is recorded because a pack that
lists only the failures inside its own scope is the sales document this file
exists to prevent. The struck clause is true of the *row* and was the wrong
reason to leave it alone: the reason to record it was that it was real, and it
turned out to be worse than recorded.

## 17. ~~The pedagogy deny-list now exists twice, and the copies are kept in step by hand.~~ — **RESOLVED**

**Resolved by PR [#157](https://github.com/kudratsingh/arxiv-research-agent/pull/157),
merged 2026-09-04T06:13:47Z as `93a6caa`** — in exactly the shape this entry's
"changes when" clause named, the second of the two options: *"an equality
assertion is added in the shape WO-W07 already uses."* The entry is kept, struck
through and marked, for the same reason §6, §7, §12 and §16 are.

**What now fails when the copies drift.**
`TestLearnerFacingCopyNamesNoPedagogyScalar::test_the_web_deny_list_and_the_python_mirror_are_the_same_list`
in `tests/test_simulate_learner.py` asserts three things:

1. **Same ids, same order** — the id lists compare as sequences, so an entry
   added on one side only, renamed, or reordered fails. That is the asymmetry
   this entry called *"the right way round"* and it is no longer free.
2. **Equal pattern sources**, entry by entry, after the **one** normalisation
   the two syntaxes honestly force — a `/` inside a TS regex literal is written
   `\/` and needs no escape in a Python pattern string. Nothing else: no
   case-folding, no whitespace stripping.
3. **Case-insensitive on both sides** — every TS entry must still carry its `i`
   flag, because `_pedagogy_offenders` applies the Python mirror with
   `re.IGNORECASE`. A dropped flag would be a narrower rule wearing an identical
   source, which assertion 2 alone would wave through. The Python half is
   checked behaviourally (`_pedagogy_offenders(["MASTERED"])` must still name
   `mastery`).

**It reads the TS side as text.** `_ts_pedagogy_phrases()` slices the
`PEDAGOGY_PHRASES` array literal out of `web/lib/copy/index.ts` and matches each
`{ id, pattern, why }` object with one regex — **no Node, no import, no new
dependency**, on the `tests/test_contract_sse_events.py` /
`tests/test_contract_learn_fixtures.py` precedent for reading `web/**`. The
argument this entry recorded for re-typing rather than generating is therefore
kept: *"a Node dependency in a Python unit test would be a worse coupling."*
What changed is that re-typing is now **safe** rather than merely cheap.

**The text parser answers for its own failure mode.** The reader asserts it
parsed as many entries as the array declares `id:` fields — **12 = 12** today —
so an entry shape it cannot read fails loudly instead of silently shrinking the
comparison.

**Red/green proven three ways**, each perturbation reverted: a Python entry
narrowed (`dashboards?` → `dashboard`), a TS entry stripped of its `i` flag
(`streak`), and an entry added to the TS list only (`leaderboard` — precisely
the previously-free asymmetry). Green as committed: **1 passed, 52 deselected**;
`pytest tests/test_simulate_learner.py tests/test_progress_events.py -q` →
**115 passed, 14 skipped**; the whole suite → **2042 passed, 52 skipped, 0
failed**.

**`web/lib/copy/index.ts` is untouched** — WO-W14's dictionary stays the
authority, and the fence is not crossed.

**The docstring quoted below is no longer what the module says.** #157 removed
both false sentences from it: the mirror is not kept in step by *"a list two
reviewers can diff by eye"*, and adding an entry on the web side without adding
it here no longer *"costs nothing"* — assertion 1 is what makes that false. The
docstring names the test instead.

**What it was, as recorded before the fix**, kept below.

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

~~**Owner:** unassigned.~~ — **Owner: PR #157, merged.** **Changes when:** either
a generated list replaces the re-typed one, or an equality assertion is added in
the shape WO-W07 already uses — **the second happened**, two days later. Neither
is Gate W1's to require — the gap is one release of drift wide, not a live
defect — but it should not go unrecorded, because the fix for a honesty gap
quietly created a second place honesty rules have to be maintained.

*(The second place still exists. What #157 removed is the silence around it: the
list is still typed twice, and now a test says so out loud when the two copies
stop agreeing.)*

## 18. `/` now loads three font faces where the gate-4 pack measured one, and the premise that allowed it is false.

Found by PR [#159](https://github.com/kudratsingh/arxiv-research-agent/pull/159)
(`2001d1b`, 2026-09-04) while fixing the landing route's nightly Lighthouse
failure. **Reported, deliberately not changed.**

`web/components/features/LearnLandingEntry.tsx` (WO-W12, #138) is the landing
route's only consumer of `--font-report` (Literata) and `--font-mono` (IBM Plex
Mono), through `font-report text-report-h2` on its heading and `font-mono
text-mono-xs` on its eyebrow. Both faces carry `preload: false` in
`web/app/fonts/fonts.ts` on a premise written before that card existed and
falsified by it:

> `--font-report` has exactly one consumer in the whole product … so it sets no
> pixel of any route's first paint: not the landing prompt

**Measured** (`/`, `mobile-412`, medians, committed collect settings):

| | gate-4 (`17e1fb6`) | today |
|---|---:|---:|
| Font requests on `/` | 1 (20,331 B, preloaded) | 3 (69,621 B; **49,290 B** of it at VeryHigh, discovered after CSS parse) |
| `total-byte-weight` on `/` | 205,331 B | 262,231 B (**+27.7 %**) |
| `mainthread-work-breakdown` | 220 ms | 276 ms |
| `bootup-time` | 98 ms | 124 ms |

**It is not currently costing an assertion.** With #159's `prefetch={false}` in
place `/` is back at the LCP floor even at ×20 CPU slowdown, and `npm run
budgets` passes with fonts at 103,476 B of a 109,568 B ceiling. **No ceiling
moved.** This is a premise that has gone stale in a comment, and a byte cost
that a reader of the gate-4 pack would not expect, not a live failure.

**Owner: the repository owner — a typography ruling.** #159 declined it by
design: *"correcting it means changing the typography of a shipped card to
something other than the visual language of the surface it teases — a design
ruling, not a perf repair."* **Changes when:** the owner rules — the heading and
eyebrow move to the surface's default face, or the two faces are preloaded on
`/` and the premise in `fonts.ts` is rewritten, or the ruling is that a card
teasing the report surface should look like it and the bytes stand. Whichever it
is, the false sentence in `web/app/fonts/fonts.ts` goes with it.

## 19. `?job=baseline-plan-review` misses `categories:performance` on the 2-vCPU runner, and no Phase W change explains it.

The second half of the nightly Lighthouse failure #159 fixed, and the half it
**did not** fix. Nightly run
[33740169240](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33740169240)
(2026-09-03), job `lighthouse ci (§8.2, 3 profiles x 3 runs)`, profile
`mobile-412`, state `/c/baseline-populated?job=baseline-plan-review`:

| Assertion | Measured | Ceiling |
|---|---:|---:|
| `categories:performance` | 0.92 | ≥ 0.95 |
| `total-blocking-time` | 237 ms | ≤ 300 error / ≤ 150 **warn** |

**No attributable Phase W regression.** The Phase W suspects do not touch this
state's render tree — W13 (#146), W13b (#150) and W14 (#147) add only
`/learn/**` surfaces; W17b (#153) adds a server-resolved prop and copy; W13c
(#155) adds one class name and one `align-self`. Against the gate-4 LHR for the
same state, the two *work* metrics — the ones a blocking-time breach would show
up in — are **down**, and the two byte counts are up by single-digit percents
inside their ceilings:

| | gate-4 | today |
|---|---:|---:|
| `total-byte-weight` | 376,477 B | 384,219 B (+2.1 %) |
| `mainthread-work-breakdown` | 499 ms | **480 ms** |
| `bootup-time` | 292 ms | **215 ms** |
| `/c/[id]` first-load JS | 182,814 B | 187,902 B (+2.8 %, ceiling 192,512 B) |

And the breach is not new: the gate-4 evidence pack already recorded this cell
over the ratified 150 ms **on the runner at ratification** — medians of 180 ms
and 214 ms across two nightlies of `17e1fb6`
(`docs/revamp/evidence/gate-4/lhci/README.md` §11.2), single samples to 290 ms.
237 ms is inside that band.

**What the time is actually spent on**, from #159's runner-regime probe: the
plan editor's lazy chunk is **296,426 B raw / 73,580 B gzip** and is a single
**277 ms long task**. It is all of **`zod@4.4.3`** — `toJSONSchema`, the locale
tables, the codecs, the `emoji`/`cuid`/`ulid` validators — pulled in by
`lib/plan/schema.ts` for a form with a handful of string and array rules, and
the plan-review state needs it at first render. **It predates Phase W: WO-17,
PR #93.**

**Owner:** the coordinator — #159 records the residual as *"a coordinator
decision"* — **and the owner for the one remedy that spends money.** **Changes
when:** one of the three remedies #159 names lands — a dedicated runner, a
narrower audit, or a work order that shrinks the chunk. `web/lighthouserc.json`
pre-committed against the fourth: *"a dedicated runner or a narrower audit — NOT
another doubling."* No ceiling moved in #159 and none should move to close this.

**Note the workflow's state.** `nightly.yml` is **disabled by owner order since
2026-09-03**, so nothing is currently measuring this cell. A single verification
run to confirm #159's fix on the runner — and to re-read this row — is a pending
owner decision, recorded in [`../../STATUS.md`](../../STATUS.md).

## 20. The follow-up-probe feedback string exists in two tiers with no test between them.

Found by PR [#158](https://github.com/kudratsingh/arxiv-research-agent/pull/158)
(`5b7ec23`, 2026-09-04) while replacing line-number citations with symbol
references. The card set out to check what it was about to claim, and found one
claim it could not make.

Three backend string literals are quoted **verbatim** in the `web/` tier. Two
are covered by WO-W11's recorded-fixture freshness test,
`tests/test_record_learning_fixtures.py::TestTheCheckedInSetIsFresh::test_a_fresh_recording_reproduces_the_committed_files`
(§5), which re-records the mock sessions and demands byte-identical output:

- the **mock tutor feedback** (`session-flow.spec.ts`'s `MOCK_TUTOR_FEEDBACK`)
  — present in the recorded fixtures, so the guard applies;
- the **explain-back prompt** (the `ExplainBack` story) — present in the
  recorded fixtures, so the guard applies to the backend copy.

The third is not covered by anything. Under mock mode `assessment_judge` returns
`unassessed`, so `route_after_assessment` never routes to the probe and **no
recording contains the string**. `grep` finds it in exactly two places —
`src/agents/tutor.py`, in `assessment_probe_agent`, and the `Probe` story — with
no test between them. Change one and nothing anywhere goes red.

**No guard was invented.** #158 wrote the fact into the comment beside the story
instead, which is the honest half of the trade and not a fix.

This is §14 seen from the other tier: the judge is default-off and *"no e2e
drives the judge, because the judge needs a model"*, so the probe turn is
unreachable in every environment this repository runs, and the story is the only
place its shape is rendered at all.

**Owner:** unassigned. **Changes when:** either the probe turn becomes
reachable under mock mode — which is §14's problem and needs a decision about
what a mock judge should return — or a direct equality assertion is added
between the story's literal and the backend's, in the shape §17's resolution now
uses for the pedagogy lists and WO-W07's `test_the_database_ban_and_the_python_ban_are_the_same_list`
established. The second is cheap and does not need the first.
