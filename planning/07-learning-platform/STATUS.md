# Learning platform campaign — status

Updated: 2026-09-04

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
(W-OD-4/5/6). *(Eight more PRs have merged since — #156 on 2026-09-02 and #161
on 09-04, this file's own bookkeeping; the four of the follow-up wave below;
and the two merged PRs of its closing. None is a card, and the card counts
above are unchanged.)*

Nothing was in flight when this train closed, at `9fa99b8`. The follow-up wave
below and its closing carry `main` to `737caa4`, and **this file is written
against `737caa4`**.

### Follow-up wave (2026-09-04)

Four PRs, merged the same morning by the coordinator under the standing
delegation, squash, in this order. **None is a card** — they are not in
`05-WEDGE-WORK-ORDERS.md` §5 and no WO number is claimed for them. **Two close
known gaps (§16, §17); two open three more (§18, §19, §20).**

| PR | Squash SHA | Merged (UTC) | Subject |
|---|---|---|---|
| [#157](https://github.com/kudratsingh/arxiv-research-agent/pull/157) | `93a6caa` | 06:13:47 | the two pedagogy deny-lists must be the same list |
| [#158](https://github.com/kudratsingh/arxiv-research-agent/pull/158) | `5b7ec23` | 06:38:38 | cite `tutor.py` by symbol, not by line number |
| [#160](https://github.com/kudratsingh/arxiv-research-agent/pull/160) | `337dbe4` | 07:10:45 | the theme control adopts a pre-hydration click |
| [#159](https://github.com/kudratsingh/arxiv-research-agent/pull/159) | `2001d1b` | 07:16:04 | the landing entry no longer prefetches a `no-store` route |

- **#157 closes `known-gaps.md` §17**, in the shape the entry's own "changes
  when" clause named. `test_the_web_deny_list_and_the_python_mirror_are_the_same_list`
  parses `PEDAGOGY_PHRASES` out of `web/lib/copy/index.ts` **as text** — no Node,
  no import — and asserts same ids in the same order, equal pattern sources
  entry by entry after the one normalisation the two syntaxes force (`\/` → `/`),
  every TS entry still carrying its `i` flag, and that the reader parsed as many
  entries as the array declares (12 = 12). Red/green proven three ways, each
  perturbation reverted. Suite **2042 passed, 52 skipped**;
  `web/lib/copy/index.ts` untouched.
- **#158 opens `known-gaps.md` §20.** It replaced the `src/agents/tutor.py:NNN`
  citations at **eight sites** under `web/` — the e2e README, `compose.e2e.yml`,
  `mock-mode.ts`, `paid-path.ts`, `session-flow.spec.ts`,
  `GuidedSessionView.stories.tsx` — with symbol references, having first
  established that **all four distinct cited line numbers were already stale**
  at `dce6e42`. Comments and a README only; no behaviour change. Checking what keeps three
  verbatim backend literals in step found that one of them is unguarded: the
  follow-up-probe feedback string lives in exactly two places
  (`assessment_probe_agent` in `src/agents/tutor.py`, and the `Probe` story)
  with **no test between them**, because under mock mode the judge returns
  `unassessed` and the probe never runs, so no recorded fixture contains it. The
  recorded-fixture freshness test covers the other two. No guard was invented;
  the comment says so instead. Nine `machine.ts`/`client.ts`-style web→web line
  refs were found stale and **left alone**, listed in the PR body.
- **#160 closes `known-gaps.md` §16 — and reclassifies it.** The record had it as
  a flaky probe: *"`theme.spec.ts:186` flakes on webkit, ~3 runs in 10 …
  undeclared intermittent."* It is a **product defect**. A label click on the
  theme control that lands before React attaches checks the radio natively;
  `onChange` is not there yet, so nothing is written, and React does not reset a
  hydrated input's checked state — the control shows **Dark** while `data-theme`
  stays `light`, **permanently**. The evidence is that every failure hit the
  `data-theme` assertion and **never** the `toBeChecked()` above it; no React
  internals were on the input at click time; and holding
  `_next/static/chunks/**` until after the click reproduced it **4/4 on chromium
  *and* webkit** — the engine only decided how often the race was lost. Fixed by
  a mount effect in `ThemeToggle.tsx` that adopts the checked radio when it is
  neither the live preference nor the server preference. Counts: webkit
  `--repeat-each=20` **3 failed / 17 passed → 120/120**, chromium **120/120**,
  full chromium project **315 passed, 5 skipped, 0 failed**. The declared
  `test.fail` at `theme.spec.ts:123` is untouched and still fails as declared.
  **Residual, recorded in the source:** a pre-hydration click on the option the
  server already rendered as checked changes no DOM state and fires no event, so
  it stays undetectable.
- **#159 fixes the nightly Lighthouse `mobile-412` failure and opens §18 and
  §19.** The profile failed on the nightly runs of 2026-09-02 and 09-03 (run
  [33740169240](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33740169240)
  is the second); the workflow (`nightly.yml`) has been **disabled by owner
  order since 09-03**. One cause for both `/`
  breaches — `bf-cache` 0 and LCP 2715.962 ms against a 2500 ms ceiling:
  `LearnLandingEntry.tsx` (WO-W12) is the only in-viewport `<Link>` to another
  document route at 412×823, so the App Router prefetched `/learn?_rsc=…`; every
  document route is dynamic because the root layout reads the CSP nonce, so the
  prefetch answered `no-store`, and Chrome blocks bfcache for a script-initiated
  no-store response (`JsNetworkRequestReceivedCacheControlNoStoreResource`).
  `mobile-320` corroborates: the card is below the fold there, no prefetch
  fires, and `/` passes. Fixed with `prefetch={false}` plus
  `LearnLandingEntryPrefetch.test.tsx` as the per-PR guard, since the prop is
  invisible in the DOM. All three profiles pass locally. **No ceiling moved.**

**The two it did not fix are now `known-gaps.md` §18 and §19**, and both are
owner decisions rather than engineering ones — see the ledger below.

#### Closing (2026-09-04)

Three more PRs close the wave, after it was recorded as merged
([#161](https://github.com/kudratsingh/arxiv-research-agent/pull/161),
`a7dd452`). Two are merged, in this order, by the coordinator under the standing
delegation, squash; **the third is open at the time of writing, by owner order.**
**None is a card.** Between them they close **both** gaps the wave opened — §18
on an owner's ruling, §19 on a work order plus the first runner run since 09-03
— and one of them changes the gate that merges them.

| PR | Squash SHA | Merged (UTC) | Subject |
|---|---|---|---|
| [#163](https://github.com/kudratsingh/arxiv-research-agent/pull/163) | `c93662d` | 08:18:44 | the dependency audit is its own bounded job |
| [#164](https://github.com/kudratsingh/arxiv-research-agent/pull/164) | `737caa4` | 09:35:18 | the plan editor stops paying for zod at mount |
| [#162](https://github.com/kudratsingh/arxiv-research-agent/pull/162) | — | **open at the time of writing** | `fonts.ts` states which faces `/` loads, and why |

**Why #162 is still open, and why §18 closes anyway.** Its diff is
**comment-only**, one file, no export and no value. Eight of its nine checks
are green; the ninth, `web dependency audit`, is red on the same npm
advisory-endpoint outage finding (ii) records, and repeated reruns did not
clear it. **It stays open by owner order** — the owner chose to skip that check
rather than wait on a data source that was returning nothing. So what closes
`known-gaps.md` §18 is the **owner's ruling of 2026-09-04**, which is what that
entry always said would close it; #162 records the ruling in the source, and
the merge only publishes it.

- **#163 takes the audit out of the `web` job.** The audit gate is a **network
  call to npm's advisory endpoint** and it ran as a step inside `web` with no
  bound of its own, so finding (ii)'s outage did not merely make it answer
  wrong — it made the other four gates report **nothing**. Two main runs:
  [33847548135](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33847548135)
  (`337dbe4`) spent **9m37s** in the audit step and was **cancelled at 15
  minutes** during Vitest;
  [33847950556](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33847950556)
  (`2001d1b`) spent **4m52s** and was cancelled during the build. A healthy run
  spends **1s**. So `web dependency audit` is now its own top-level job —
  `timeout-minutes: 10`, a **5-minute** step bound on `npm ci` and a
  **6-minute** one on `npm run audit:gate` — and it owns the `web-npm-audit`
  artifact. Every `npm ci` in `ci.yml` **and** in `nightly.yml` now carries
  `NPM_CONFIG_FETCH_TIMEOUT=60000` (npm's own default is **300000** — five
  minutes *per request*), `NPM_CONFIG_FETCH_RETRIES=2` (npm's default, kept:
  the defect was the attempt, not the retry) and
  `NPM_CONFIG_FETCH_RETRY_MAXTIMEOUT=20000`. `web/tests/ci.test.ts` pins the
  shape; `README.md` and `docs/testing.md` now say **nine jobs**. **What the
  gate asserts is unchanged** — `audit-gate.mjs` and `audit-exceptions.json`
  are untouched, and there is **no `continue-on-error`**: an audit that could
  not run is red, not green. Its own PR run was a live test of exactly this,
  because the registry was still degraded: **`web` 3m26s** (install 22s, four
  gates clean) beside **`web dependency audit` 3m56s** (install 1m21s, gate
  2m21s) — under the old shape those were one job with the slow half in front.
  The gate also **answered correctly** there: ten exceptions, all ten `ok`,
  including the three the degraded endpoint had called stale. Main's first run
  with the split,
  [33852825449](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33852825449)
  on `c93662d`, is **green in all nine jobs**, with the audit job at **3m47s**
  (install 56s, gate 2m44s).
- **#164 closes `known-gaps.md` §19 at the error ceiling.**
  `PlanEditorFields.tsx` built its Zod schema **at module evaluation**, so all
  of `zod@4.4.3` ran the instant the lazy plan-review chunk loaded —
  **314,066 B raw / 73,605 B gzip**, a **232–255 ms long task** — on a state
  whose whole point is that the run is paused waiting for an interaction. Of
  the three approaches #164 weighed, (c) landed: the client resolver is now a
  pure `planResolver` over `planIssues`, **the function the submit path always
  used**, so the form and `reviewRequestFor` can no longer disagree about what
  is valid. **Validation is not weakened and that is measured**: the Zod schema
  moved *verbatim* into `web/tests/plan/schema.test.ts` as a differential
  oracle asserting the two error trees **deep-equal** over **8 cases** (5
  before), and `bundle.test.ts` asserts Zod is in no shipped chunk. Chunk
  **314,066 → 37,113 B raw (−88.2 %)**, **73,605 → 12,839 B gzip**. Local ×20
  runner-regime probe, medians of 5: `categories:performance` **0.88 → 0.93**,
  TBT **387 → 296.5 ms**; the residual long tasks are the Next app-router
  client runtime and React DOM, *"not ours to cut"* in `budgets.json`'s own
  words. **No budget row moved and no ceiling moved** — the saving is entirely
  in a lazy chunk, and the only row that would carry it, `total-transferred-js`,
  is `enforcement: external`. What actually closed §19 is the runner run below.
- **#162 closes `known-gaps.md` §18 — by ruling, not by code**, which is why
  an open PR can close it. The owner ruled on 2026-09-04, in their own label
  **option A** and the third of the three the entry listed: **accept the bytes,
  correct the false premise in the source.** The premise was that
  `--font-report` *"has exactly one consumer in the whole product … so it sets
  no pixel of any route's first paint"*; it was true at WO-02 and stopped being
  true at **WO-W12 (#138)**, which put `LearnLandingEntry` on `/` carrying
  `font-report` and `font-mono`. The correction is **comment-only, one file** —
  no export, no value, no import moved — and it carries #159's measured numbers
  (`/` font requests **1 / 20,331 B → 3 / 69,621 B**; `total-byte-weight`
  **205,331 → 262,231 B**), the narrower reason `preload: false` still holds
  (neither face paints `/`'s LCP element), and the ruling itself: accepted, the
  bytes are inside every asserted ceiling, and **restyling the landing card
  away from the learn surface's typography was declined**.

**The merge gate now counts nine.** Finding (i)'s corrected gate — watch the
run, then require `gh pr checks N --json name,bucket` to return every entry
`bucket == "pass"`, never `--auto` — was written against **≥8** entries. From
`c93662d` on it is **nine**: `web dependency audit` is top-level, has no
`needs:`, and carries no `continue-on-error`, so it is required in exactly the
sense the other eight are.

**One more lesson, alongside the wave's own two below: inside `web/`, cite a PR
as `PR NNN` and never `#NNN`** — #162's `#159` / `#138` citations failed the
`web` job because `web/tests/tokens.test.ts` criterion 1 (*"tokens.css is the
only file in web/ with a literal colour"*) reads them as three-digit hex, and
one fix commit on the branch (`b300f75`) rewrote them.

**`nightly.yml` was re-enabled to verify, and is off again.** Pending item 1
below was answered on 2026-09-04: the owner re-enabled `nightly-lighthouse` for
verification, it ran **twice** and passed twice, and the owner then ordered it
off — *"remove the nightly job when done"*, carried out as `gh workflow
disable` with the file kept.

- [33850155834](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33850155834)
  on `2001d1b` — **PASS**. #159's `/` fix confirmed on the 2-vCPU runner it was
  conditioned on.
- [33859118052](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/33859118052)
  on `737caa4` — **PASS**, all three profiles, **80 assertions, `lhci autorun`
  exit 0**. `mobile-412`, `/c/baseline-populated?job=baseline-plan-review`,
  medians of 3: `categories:performance` **0.96** (0.95, 0.97, 0.96) against
  ≥ 0.95 — it read **0.92** the day before; `total-blocking-time` **204 ms**
  (204, 204, 219), inside the **300 ms error** row and still over the ratified
  **150 ms warn** row, which `web/lighthouserc.json` keeps as a *warning* by
  the WO-29 follow-up ruling; LCP **1871 ms**; `bf-cache` **1**. On `/`:
  performance **0.98**, LCP **2264 ms**, TBT **99 ms**, `bf-cache` **1**.

**So §19 is resolved at the error ceiling, and its residual is re-scoped**: the
150 ms warn row is owned by the Next app-router runtime and React DOM, not by
product code, and no ceiling moved to close it. **§18 is resolved by owner
ruling.** Both are struck through and kept in
[`evidence/gate-w1/known-gaps.md`](evidence/gate-w1/known-gaps.md), now **twenty
entries, seven resolved**. **§20 is untouched**, and so is the W-OD ledger:
**the owner has deferred the ledger decisions and WO-W20 to a later date**, and
no numbering moves for it. **Re-enable `nightly.yml` only on a fresh owner
instruction.**

### Two process findings from the wave

Execution record, not gaps. Both are about how the coordinator merged, and the
second is about believing a tool.

**(i) The merge gate was wrong, and is corrected.** `gh pr checks N && gh pr
merge N` is **unsafe on gh 2.89.0**: a job that hits `timeout-minutes` ends
*cancelled*, and `gh pr checks` exits **0** for a cancelled job. #157 merged that
way with its `web (typecheck + lint + test + build)` job **cancelled at 15
minutes**. It was harmless in the event — the diff was Python-only, and main's
own run on `93a6caa` passed every job — but it was not verified, and "harmless
in the event" is not a gate. **The gate is now:** watch the run, then require
that `gh pr checks N --json name,bucket` return **≥8 entries, every one
`bucket == "pass"`**, then merge. **Never `--auto`.**

**(ii) `npm audit` was down on 2026-09-04, and the failure it produced looked
exactly like a real one.** For several hours `npm audit` answered with **zero
advisories for the whole tree**, after **4–12 minutes** per call. So
`web/scripts/audit-gate.mjs` reported all **ten** entries in
`web/audit-exceptions.json` stale and failed **by design** — that is what the
gate is for. Main's CI on `5b7ec23` was red at that step and **only** that step,
and the web job on two PRs was cancelled at its 15-minute timeout with install +
audit taking **7–11 minutes** where a normal call is under a minute. **The
exceptions were not deleted.** The coordinator checked each against the GitHub
advisory database instead and found every one still live for the installed
version — `image-size@2.0.2` (GHSA-w3rx-r6r6-pgpr, GHSA-5p2g-fcmc-qvqq),
`tmp@0.1.0` (GHSA-ph9p-34f9-6g65), `extract-zip@2.0.1` (GHSA-jmr9-qjv8-65gv).
Later runs (#160, #159) passed the step as the service recovered.

**The lesson, stated as a rule:** a stale-exception failure that appears for
**every entry at once** is a data-source failure until an advisory lookup says
otherwise. The tempting fix — deleting the exceptions the gate calls stale —
would have removed four real advisories from the repository's record on the
word of a service that was returning nothing.

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
#153; §7, the `cls.spec.ts` failure, by #155 later the same day). *(As of
2026-09-04 the file reads **twenty entries, five resolved**: the follow-up wave
closed §16 and §17 and opened §18–§20. The ruling above is unchanged — none of
the five is a §6 row, and the funded row is still the only UNRESOLVED one.)* The
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

(h) **The state probe read a product defect as an engine-specific flake**, which
is (g)'s failure a second time and from the same cause: a window too narrow to
contain the thing. `known-gaps.md` §16 recorded *"`theme.spec.ts:186` flakes on
webkit, ~3 runs in 10 … an undeclared intermittent"* and left it unowned on the
strength of that reading. #160 showed the defect reproduces **4/4 on chromium as
well as webkit** once the client chunks are held until after the click; webkit
only loses the race more often. Recorded here so the next probe asks, of any
intermittent, **what the failing assertion actually was** — every failure here
hit `data-theme` and never `toBeChecked()`, and that one fact separates "the
test is flaky" from "the product drops the click" without any further
measurement.

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

**Deferred by the owner, 2026-09-04:** the W-OD ledger decisions above and
**WO-W20** are put to a later date, so nothing in this list is waiting on the
coordinator.

**Three more awaited a ruling as of 2026-09-04, from the follow-up wave — and
all three were answered the same day.** They are **not** numbered W-OD-7/8/9:
the W-OD series is the plan's, these are execution's, and adding to it would
rewrite a document that stands as merged. **The three are kept below as
recorded, with their outcomes; the numbering does not move.**

1. **Re-enable `nightly.yml` for one verification run.** — **ANSWERED: run,
   passed twice, off again.** Re-enabled by owner order on 2026-09-04; runs
   33850155834 (`2001d1b`) and 33859118052 (`737caa4`) both PASS; disabled
   again by owner order. Re-enable only on a fresh owner instruction. *As
   recorded:* It has been disabled by
   owner order since 2026-09-03. #159 fixed the `mobile-412` `/` failure and all
   three profiles pass locally, but nothing has confirmed it **on the 2-vCPU
   runner**, which is the machine the failure was conditioned on. The ask is one
   run, not a re-enable; the standing cost lock is unaffected — the Lighthouse
   lane buys nothing.
2. **A typography ruling on the landing card's fonts** (`known-gaps.md` §18). —
   **ANSWERED: option A, the third of the three below** — the bytes stand and
   the false premise in `web/app/fonts/fonts.ts` is corrected; restyling the
   card was declined. Recorded in the source by #162, open at the time of
   writing. *As recorded:*
   `LearnLandingEntry` puts Literata and IBM Plex Mono on `/`, where the gate-4
   pack measured one face: `total-byte-weight` **205,331 → 262,231 B**. It costs
   no assertion today and no ceiling moved. #159 declined to fix it because the
   fix changes the typography of a shipped card — *"a design ruling, not a perf
   repair"*. The options are: move the heading and eyebrow to the surface's
   default face; preload the two faces on `/` and correct the now-false premise
   in `web/app/fonts/fonts.ts`; or rule that the card should look like the
   surface it teases and let the bytes stand.
3. **A remedy for plan-review's runner performance** (`known-gaps.md` §19). —
   **ANSWERED: the third remedy, and it spent nothing.** #164 (`737caa4`)
   shrank the chunk; the runner then read **0.96** against ≥ 0.95 and TBT
   **204 ms** against the 300 ms error row. No ceiling moved. What is left is
   the 150 ms **warn** row, re-scoped to the Next runtime and React DOM. *As
   recorded:* `?job=baseline-plan-review` reads `categories:performance` **0.92** against a
   **≥0.95** ceiling on the runner, with **no attributable Phase W regression**
   — main-thread work and bootup are both *down* against gate-4. The 277 ms long
   task is the plan editor's lazy chunk, **all of `zod@4.4.3`**, pulled in by
   `lib/plan/schema.ts`, and it **predates Phase W** (WO-17, #93). Three
   remedies: a dedicated runner, a narrower audit, or a work order to shrink the
   chunk. `web/lighthouserc.json` pre-committed against the fourth — *"NOT
   another doubling"* — and no ceiling should move to close this.

Items 2 and 3 cost engineering time or money and neither is Gate W1's; item 1 is
a workflow the owner switched off and only the owner switches back on. **All
three are now settled** — item 3 cost engineering time and no money, item 2 cost
a ruling and a comment, and item 1's workflow is switched off again. **Nothing
in this list is now waiting on the coordinator**; the W-OD ledger and WO-W20
wait on the owner, at a date the owner sets.

Standing cost lock (2026-08-30, reaffirmed by continuation): the paid nightly
eval workflow is disabled, and no funded model run, deployment, public launch,
or pilot invitation may occur without a fresh explicit owner approval. Local,
mock, recorded-fixture, static, and CI validation continue under that lock.
