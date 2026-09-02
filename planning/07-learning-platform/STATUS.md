# Learning platform campaign — status

Updated: 2026-09-02

## The campaign

Five PROPOSED planning documents (2026-08-29/30), authored by concurrent
Fable planning agents and merged as records, not adoptions:

| Doc | Subject |
|---|---|
| [`00-VISION.md`](00-VISION.md) | Thesis, personas, competitive scan, UX pillars |
| [`01-LEARNING-AGENT.md`](01-LEARNING-AGENT.md) | Learner model, curriculum + daily-session graphs, cost economics, eval story |
| [`02-CONTENT.md`](02-CONTENT.md) | Content graph, curation pipelines, licensing reality, cold-start scope |
| [`03-ARCHITECTURE-ROADMAP.md`](03-ARCHITECTURE-ROADMAP.md) | Delta architecture, L0–L4 phases (~71 WOs), owner decisions OD-1–12 |
| [`04-STRATEGY-ALTERNATIVES.md`](04-STRATEGY-ALTERNATIVES.md) | Objective functions, alternatives, tradeoff matrix, cheap-test ladder |
| [`05-WEDGE-WORK-ORDERS.md`](05-WEDGE-WORK-ORDERS.md) | Phase W's 20 executable work orders, dependency graph, gates, and owner waits |
| [`06-DIRECTION-PORTFOLIO.md`](06-DIRECTION-PORTFOLIO.md) | The nine adopted directions: charters, shared core, evidence gates (LP-D2) |

## Owner decisions

**LP-D1 (2026-08-30) — Rung 0 objective picked.** The owner rules:
the objective is **a real product with users, and learning-by-building**
("no this will be a real product with users or learning by building so
we need to build more out, even more so on the agentic and model
harness side, i dont see any alternatives"). The 04 alternatives
(stop-and-polish, OSS-flagship, API play, research-only double-down)
are **rejected** by the owner. Under the ruled objectives, 04's ranking
selects the guided-read wedge (its option B) as the first build — which
is executed **as Phase W of the platform**, not instead of it, with the
agentic/model-harness investment front-loaded per the owner's emphasis.

Consequences accepted by this ruling per 04 §5: recurring costs are in
scope once the owner explicitly approves each (deploy, eval funding,
pilot inference); operator load is real; the pre-committed engagement
thresholds (04 Rung 2; 03 LG-gates) stand and will be measured, not
waived.

**LP-D2 (2026-08-30) — the nine-direction portfolio adopted.** The
owner rules that the nine alternative directions surveyed after LP-D1
(research radar, literature-review workbench, lab/team workspace, R&D
intelligence briefings, paper-reading companion, personal research
memory, Papers-with-Code successor, newsletter/media, API play) are all
long-term intents of the platform ("lets add all of them to docs
because I want to build all of them into the platform"). Recorded and
structured in [`06-DIRECTION-PORTFOLIO.md`](06-DIRECTION-PORTFOLIO.md):
one shared core (Phase W), one direction in build at a time, each
behind an evidence gate; order beyond "Phase W first" is decided at the
gates, not now.

Still owed by the owner before their respective gates: eval funding
(~first paid run, now W-OD-1 and the one blocker on Gate W1's funded
row), DEPLOY cost approval (inside W-OD-4/5), content licensing posture
(02, W-OD-3), MT-01 §8 answers (deferred to Rung 3 / Phase L0),
notification channel (01/03, not needed in Phase W). The current state
of each is "Owner decisions now due" below.

## Phase W execution

The plan is approved. Every planned card except WO-W20 is merged at its
no-cost boundary, Gate W1's evidence pack is on `main`, and the gate is
ruled below.

### Merge train, 2026-09-02

Earlier merges (2026-08-30 → 09-01, thirteen cards, `a884533` … `2114c47`):
WO-W08 #132, W02 #134, W07 #133, W01 #135, W15 #136, W03 #137, W12 #138,
W09 #139, W18 #140, W16 #141, W04 #142, W05 #143, W06 #144.

Today, in merge order:

| Card | PR | Squash SHA | Subject |
|---|---|---|---|
| WO-W10 | #145 | `77a1798` | learner-simulation benchmark, scripted tier |
| WO-W13 | #146 | `4fbe239` | the guided-read session view |
| WO-W11 | #148 | `ba3e576` | eval wiring, nightly lane, recorded fixtures |
| WO-W14 | #147 | `a9e26bf` | the Ledger view and the pedagogy honesty gate |
| WO-W17 | #149 | `5bcf373` | pilot principals at the edge seam, the no-cost half (ADR 0063) |
| WO-W13b | #150 | `3ccb650` | start a guided-read session from the path view |
| WO-W03b | #151 | `1026534` | the tutor close line no longer names the frame it rejects |
| WO-W17b | #153 | `72e65b9` | the identity slot tells the truth under pilot mode |
| WO-W19 | #152 | `f6fce61` | the Gate W1 evidence pack and known gaps |
| WO-W13c | #155 | `9fa99b8` | the Live badge no longer grows the spine's status line |

Twenty-three PRs, #132 … #155 (#154 is this file's own bookkeeping, not a
card). **Nineteen of the twenty planned cards are merged to their no-cost
boundary**, plus the four coordinator-added cards (W13b, W03b, W17b, W13c);
the owner-dependent funded/public/pilot criteria on them stay visibly deferred.
**WO-W20 remains**, and waits on the 14-day pilot observation window
(W-OD-4/5/6).

Nothing is in flight. This section is written against `9fa99b8`.

### Coordinator rulings made under the standing delegation

All dated 2026-09-02. The owner may reopen any of them.

1. **W10 and W11 were built to their no-cost boundary**, on the W09
   precedent: the scripted tiers are real and CI-run; W09 c6, W10 c5 and
   W11 c4 are deferred behind W-OD-1. Recorded in `docs/eval.md` and in
   each card's PR body.
2. **No ADR for W10's third cost-payer column** (`learner_cost_usd`) — it is
   an application of ADR 0050, not a new decision. #145 flagged it; this is
   the answer, documented in `docs/eval.md`.
3. **No ADR for W13's e2e overlay turning `ENABLE_API_AUTH` on** and stamping
   the seeded `baseline-*` rows with the stack's single principal — a harness
   decision, documented in `web/e2e/support/compose.e2e.yml` and
   `web/e2e/README.md`. #146 offered to write one; declined.
4. **W14's pedagogy vocabulary is learn-scoped**, on the `LEXICON_PHRASES`
   precedent ("Quality score" is the research metric's real name). Four W13
   session copy keys — `replyHint`, `workingBody`, `unassessedBody`,
   `recordedUngraded` — were reworded to satisfy it, before and after in
   #147's body.
5. **W11 c7**: the `engineer-rlhf-profile-note-injection` expectation moved to
   the graph's documented rule; **graph behaviour unchanged**. W08's
   recorded-fixture gate is closed with it, at fifteen transcripts (#148).
6. **WO-W13b was added** to close a plan gap: no card in the plan owned the
   session start action, so Gate W1's end-to-end row was unreachable in a
   browser until #150. **No ADR for its mock-mode pass-through** — argued in
   `web/e2e/support/mock-mode.ts`, `paid-path.ts` and `web/e2e/README.md`
   instead. `session_cost_cap_refused` is **not** a start refusal (re-scope
   confirmed): it is an `error_type` on a session that already exists.
7. **WO-W03b was added**: the tutor's close line "This is an activity record,
   not a mastery score." plants the frame W14's gate bans one tier down. #151
   fixed three learner-facing denials in `src/agents/tutor.py` and added a
   backend `PEDAGOGY_DENY_LIST` mirror; W14's dictionary stays the authority.
8. **WO-W17b was added, and has closed it**: the identity slot's "Shared
   workspace … There are no separate accounts." copy was false under
   `PILOT_EDGE_AUTH=on`. The SR-07-compliant fix — a server-resolved
   per-request descriptor (`shared` / `pilot` / `unresolved`) derived at seam
   S1 and handed to the shell as a prop, not a runtime flag in `web/` —
   merged as #153: mode-off byte-identical, pilot e2e 5/5 locally. The
   W17 discrepancy recorded in ADR 0063 §Consequences, `docs/security.md`,
   `docs/architecture.md` and `evidence/gate-w2/pilot-record.md` §6 is
   **resolved**; nothing now blocks an invitation on that count (W-OD-5
   still does).
9. **WO-W13c was added, and has closed the failure**: `e2e/cls.spec.ts`'s 3-px
   layout shift on `/c/[id]` failed on main's runs for `4fbe239` and `3ccb650`
   with an identical signature, never on a PR run, and passed on rerun. The
   coordinator's state probe of main `3ccb650` classified it **deterministic
   and CI-environment-conditioned**, not flaky — which held. Its cause, found
   by #155: the spine's status line is `items-baseline` and the `Live` badge is
   its only non-text item, so Chromium takes the badge's baseline from the 16px
   SVG that leads it and grows the line 20→23px whenever the badge is painted,
   which only a 2-vCPU runner is slow enough to do. Fixed with
   `align-self: center` on the badge, no height pinned, plus a new test that is
   red without the fix and 20/20 green with it, a hardened CLS attribution, and
   the e2e overlay's daemon-global image tags interpolated. Merged as #155
   (`9fa99b8`); `known-gaps.md` §7 is resolved and §8's tag hazard with it.
   **The probe's diagnosis was wrong in two places** — see erratum (g).
10. **The `nightly-eval` workflow remains disabled and all model spend
    remains locked** — unchanged since 2026-08-30.

### Gate W1 ruling — closed at the no-cost boundary

**2026-09-02, under the standing delegation; the owner may reopen it: Gate W1
is closed at the no-cost boundary.**

WO-W19's pack (PR #152, merged as `f6fce61`) states three shapes of ruling
rather than choosing one — close at the no-cost boundary "with the three
unrun campaigns carried as named, dated exceptions into Gate W2's memo … the
position the merged tree supports today, and the one every producing card was
built for"; hold Gate W1 open until W-OD-1 lands; or close conditionally on
WO-W13c reporting. **The
first is taken.** The merged tree supports it, and nothing engineering can do
resolves the funded row: it waits on money, not on code.

Per the pack: seven of §6's ten rows resolve outright; the per-session cost
row resolves on its own terms with every figure it reconciles a mock-mode
figure; `known-gaps.md` is non-empty at **seventeen entries, three of them now
resolved** (§6, the tutor close line, by #151; §12, the pilot identity copy, by
#153; §7, the `cls.spec.ts` failure, by #155 later the same day). The
funded-campaign row — the first funded calibration run (W09 c6), the first
funded simulation campaign (W10 c5) and the nightly learning lane's first
scheduled run (W11 c4) — is **UNRESOLVED**, and is carried into Gate W2's memo
as a named, dated exception pending **W-OD-1**.

The two conditional items the pack's third shape names are assigned rather
than left pending: WO-W13c owns the `cls.spec.ts` failure — **and closed it the
same day, #155, `9fa99b8`** — and WO-W03b closed the tutor's mastery-frame
close line (#151, `known-gaps.md` §6, struck through in the merged pack).
Neither blocked this close, and the pack's conditional third shape is now
satisfied on its own terms as well. The pack's own §6.1 carries the
coordinator state-probe verdict — main HEALTHY on every tier at `3ccb650` —
as the corroboration the close rests on beside CI.

### Plan errata found in execution

Recorded, not rewritten. The plan stands as merged; these are the places
execution diverged from it.

(a) **The four Phase W flags** are `enable_learner_profile` (W02, shared by
W07), `enable_learn_content` (W15), `enable_session_loop` (W03) and
`enable_assessment_judge` (W04) — all `default=False`. W01, W05, W06 and W07
ship no flag of their own, each for a reason recorded in the tree.

(b) **They are not independent.** A validator-enforced ladder —
`enable_assessment_judge` → `enable_session_loop` → `enable_learner_profile`
→ `enable_api_auth`, plus `enable_checkpointing` — raises at settings load,
against §0's "independent default-off flag" constraint. A consequence: the
zero-config auth-off `docker compose up` demo **cannot run a guided session**;
the e2e overlay turns auth on in order to test one.

(c) `docker-compose.yml` sets `ENABLE_LEARN_CONTENT` to `true` for the demo
(the production overlay sets it back), so "default-off" is true of the code
and not of the container a reader actually starts.

(d) `session_cost_cap_refused` is an `error_type` on a session that already
exists (`src/api/runner.py:1672`), not a create refusal — the W13 card reads
it as a start refusal, and `POST /learn/sessions` cannot answer with it.

(e) **SR-09 at the shipped defaults computes to `5 × 20 × 336 × $2.00 =
$67,200`** worst case (#149's runbook work). W-OD-5 therefore cannot approve
"the defaults"; it has to approve concrete values, withholding
`POST /research` first per OD-7's posture.

(f) `pytest -m "not e2e"` counts differ by environment and both are real:
**2038 passed / 52 skipped** locally, which has no Postgres, against **2090
passed / 0 skipped** in CI, which has the service those 52 need.

(g) **The state probe's elimination of the Live badge mount was wrong**, and so
was the regression window it drew at WO-W13's `web/lib/job/machine.ts`. The
badge mount is the cause of the `cls.spec.ts` shift; the machine is not
involved; the defect predates W13, whose change to that route was one of timing
and not geometry (#155, `known-gaps.md` §7). The probe eliminated the badge by
measuring the settled DOM, where the badge has already unmounted — recorded
here so the next probe samples **across the stream's open and close frames**,
and treats an element that grows in place as invisible to a shift attribution.

### Owner decisions now due

**W-OD-1 (eval funding) is the only blocker on Gate W1's funded row.** Sizing,
from the cards: WO-W10's campaign is ≈15 sessions at roughly **$2–6** with a
**$15** proposed ceiling — the same figure as the nightly lane's
`DEFAULT_LEARNING_MAX_BUDGET_USD` — against §2's stated order of **$25–75 per
campaign**. Setting the `ANTHROPIC_API_KEY` repository secret and approving
that budget is the whole action.

W-OD-2 (briefing generation, W15's content half), W-OD-3 (licensing posture),
W-OD-4 (Rung 1 publication), W-OD-5 (pilots — which must approve concrete
SR-09 values per erratum (e)) and W-OD-6 (threshold ratification, before any
pilot starts) all remain open. W-OD-4/5/6 together gate WO-W20.

Standing cost lock (2026-08-30, reaffirmed by continuation): the paid nightly
eval workflow is disabled, and no funded model run, deployment, public launch,
or pilot invitation may occur without a fresh explicit owner approval. Local,
mock, recorded-fixture, static, and CI validation continue under that lock.
