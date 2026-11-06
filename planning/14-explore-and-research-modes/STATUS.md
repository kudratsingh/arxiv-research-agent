# Two-mode implementation status

Updated **2026-11-06 UTC / November 5 Pacific**. D0–D4 are implemented and
verified locally. Application **`b261ddc5e0e034438a4dcc90bbbcb0ca42c76de3`**;
immutable production build **`PwbeWv0RU7h8JGqumje0V`**. Publication and exact-head remote CI are independently visible in the
[branch workflow record](https://github.com/kudratsingh/arxiv-research-agent/actions/workflows/ci.yml?query=branch%3Acodex%2Fworkspace-modes-d0-d4); the final owner checkpoint identifies the published SHA/run. Owner experience review and D5 paid quality qualification remain pending; the protected D5 implementation/offline checkpoint is recorded below.

## D5 protected qualification checkpoint — November 6

D5 implementation and offline verification are complete at application **`b7240cf34b1ef1331e33fb992870da71528105e2`**, build `Mh3EAZc3soYDoaWmy__H5`, branch `codex/workspace-d5-grounded-assistance`. Publication `57b7181` adds documentation/evidence. A subsequent helper-script lint correction does not change `src/`, `web/` or any sealed request. Exact published-head CI is reported independently in the final owner checkpoint.

**Preview: http://localhost:3192/workspace/today?mode=learn**. Isolated API8192, DB `workspace_d5_benchmark_final`, principal `d5-validation-run`, dedicated Postgres15488. Owner3137 and completed review3178 are preserved. New provider/count contacts **0**, actual new spend **$0**. Recurrence, notifications and everyday generation remain disabled; unmerged and undeployed.

The real production qualification adapter now consumes D5 multi-citation contracts, external packet-bound permission, the cumulative ledger, complete four-stage reservations and paired-count/contact journals. MockTransport uses the same controls. A-only permission forbids Messages; funded stages need explicit approval or append-only grants. The runner/Reader cannot approve themselves. The separate validation DB has no new policies/scopes/grants/fixture marker and refuses `owner_approval_required` before transport.

Active system packet v2 digest **`1e5716df09364be0db9501e9d2bc7ff3184fc65655dbbb77c6cd658a2ae6a76f`**; replay digest **`69966d4b4eb2f2a281527c78d3c194af735449c5e73541465e3c913a8afcc198`**. System v1 is preserved; v2 only fixes reporting language that conflated missing human review with missing provider measurements. No sources, questions, thresholds or limits changed. No paid D5 output was inspected. Prototype packets v2–v7 remain inactive.

| Local gate | Actual result and limit |
|---|---|
| Frozen end-to-end replay | 8/8 fresh system workflows, 2/2 separate fixed-evidence development cases, 4 checker batches/20 proposed items, 4 count-only helpers |
| Reproducibility | Checked-in snapshot/seal reproduce identical claims and denominators in another fresh isolated database |
| New accounting | 44 synthetic Messages / 48 synthetic counts; **0 real contacts, $0 actual new spend** |
| Quality | 15 generated claims total, 12 fresh; 0 human-supported facts / 0 human probe labels; all factual gates UNSCORED/HOLD, 0 accepted results |
| Python | 6,453 passed, 54 inherited skips, 53 separate-tier deselections; 94.54% total / 97% patch; package floors pass |
| Frontend | 4,261 tests / 219 files / 0 skips; 98.16% statements; lint/typecheck/mypy (187 source files)/production build pass |
| Budgets | 22/22 pass; CSS 24,868/25,600 B; Today 169,848/169,984 B; Reader 165,928/169,984 B |
| Other gates | 53/53 separate workflow e2e; 20/20 mock research at $0; registry 260 objects / 0 mismatches |
| Browser | 8 D5 journeys + 4 exact PDF checks across desktop/mobile and both themes; 0 serious/critical axe findings or console exceptions; unchanged live suite 16/16 on its separate exact CI fixture |
| Persistence | API/web restart preserves jobs/notes/threads/projects/reading/reservations; desktop/mobile Library resume and failed-read recovery pass |

The insufficient-case fake extraction is not semantic abstention or coverage proof. Original q01 development, q02/q03 failures, q04 stopped and the 0/9 historical aggregate remain unchanged. Preserved historical estimate **$0.109967**, 9 Messages / 15 counts, pending/unknown 0. Synthetic journals do not add to real provider usage.

[Overview](d5/README.md), [runnable commands](d5/RUNBOOK.md), [quality report](d5/OFFLINE-QUALITY.md), [evidence/logs/recordings](d5/evidence/README.md), [separate unexecuted proposal](d5/PAID-VALIDATION-PROPOSAL.md). Real token fit, remote schema acceptance, whole-claim support, checker error rates, owner usefulness and everyday paid assistance remain unmeasured release gates. Two retained PDF samples remain partial. Broader unsaved-draft browser-history reliability remains unresolved. No owner labels were filled or real key inspected.

## Publication repair and final application cohort

Application `b261ddc` fixes a real Library click-capture race found by exact-head
CI on publication `ff51664`. A cross-paper notebook click updated the focus cache
during capture, rerendering its advertised href before Next read it. The fix
leaves explicit queue selection in charge of Library focus and preserves the
launching view/focus, clicked source/version/passage and exact return destination.
The old unit test codified implicit promotion; its replacement pins the unchanged
advertised destination, exact version/anchor, account/view cache and remount.
No existing live assertion, timeout, coverage floor or request body was weakened.

The exact three-work CI fixture reproduced the old failure on both desktop and
mobile (10 passed,2 failed,4 serial dependents unrun). With the fix the unchanged
full live suite passes **16/16**, no retries/skips. The earlier40-work local pass
had not exposed the different-paper focus case; both cohorts remain recorded.

Final pre-push Python gate:6,318passed,54inherited skips,53separate-tier
deselections,98%patch. [Repair evidence](evidence/library-return-repair/README.md)
records commands, red/green proof and source attribution.

Final app `b261ddc`: **4,217/4,217 tests,216 files,zero skips**; coverage
statements98.20%, branches94.28%, functions93.88%, lines99.50%. Lint/typecheck,
production build and22/22 budgets pass, with no ceiling changes. CSS24,688/25,600B;
Library168,997/169,984B; Projects169,959/169,984B. The final app also passes all
64 route/theme/width/motion geometry and axe observations, and four fresh readable
example journeys/recordings. Source bindings and originals are retained separately
from the earlier62c761a and96-case mutation/restart cohorts.

Remote `ff51664` run [42146309700](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/42146309700)
finished **8 successful jobs /1 failed browser job**. Python all tiers/coverage,
package/patch gates, simulation, web build/coverage/budgets and all other jobs
passed. The browser job's classic multi-browser suite passed (one existing Pixel7
attempt retried); its durable workspace step exposed the race above. Earlier run
42143933569 was interrupted/cancelled and returned502 to cancellation attempts;
its state is retained without claiming a wider service outage. A new exact-head
workflow is required for this fixed publication; final result/URL is reported
in the owner checkpoint, not inferred from local results.

## Current gate table

| Gate | Delivered | Actual local evidence |
|---|---|---|
| D0 baseline | Controller `7e1bd97` reconciled with backend `10b4260` | Isolated DB/principals/ports; owner3137 untouched |
| D1 modes | Desktop/mobile mode switch, URL/project context, question-free Learn, independent editable learning preferences | Complete frontend gate plus four connected browser journeys |
| D2 persistence | Migration010, ownership/CAS/retry-safe projects/threads, shared source/note links and typed manual records | Real Postgres/API; fresh-browser resume after actual API/Node restart; private dump restored into a new disposable DB, all38 table/sequence fingerprints match |
| D3 discovery | Frozen `workspace-modes-lexical-v1`, distinct Learn/Research policies, context-bound editions/cursors |46 focused tests; ranking100% statement/branch; same40-work offline pool; proposed labels unjudged and chronology limited |
| D4 continuity | Explicit investigation, exact-version/passage evidence, prerequisite threads, shared Library resume, failed-save/conflict/draft protections |96/96 new browser cases;16/16 existing live regressions; actual restart, unlink and archive preserve shared data |
| D5 assistance | Implemented offline; paid/everyday disabled | Protected adapter + frozen executable benchmark + Reader results at b7240cf; independent quality/spending decision pending |
| Owner usefulness / longitudinal use | Pending | No owner labels filled; mechanical sessions are not five days of owner use |

## Runnable preview and isolation

**http://127.0.0.1:3178/workspace/today?mode=learn** — API8178, database
`workspace_modes`, principal`modes-preview`, Postgres15478.40 retained real
public works and an isolated copy of the actual saved11-interest/15-minute
profile. The saved organizing question is preserved but ignored by Learn;
it does not silently create a project. No owner notes/history/judgments copied.
Coverage is limited; retained records do not imply a fresh source check.

Write verification uses3179/API8179, database`workspace_modes_browser`,
principal`modes-browser-r15`. Its organizing question is explicitly empty.
Two clearly labelled synthetic works/four versions add Unicode/version fixtures
without rewriting the40 real retained works. All authored questions, projects,
notes and artifacts are mechanical-verification content. Existing live regression
uses separate3180/API8180/database/principal, with captured Nov3 source receipts,
not newly fetched metadata. Owner3137/API8137/storage15438 remain untouched.

See [walkthrough and exact launch commands](08-local-walkthrough.md),
[browser evidence](evidence/d1-d4-browser/README.md),
[frontend results](evidence/frontend/README.md) and
[backend results](evidence/backend/README.md).

## Checks and source attribution

- Application62c761a: complete combined Vitest/Storybook **4,217 tests /216 files,
  zero skips**. Statements98.22%, branches94.23%, functions93.80%, lines99.46%.
  Functions floor raised92.2→93.4 to satisfy existing measured-count/headroom
  policy. No floor lowered, coverage input/exclusion/tier removed or runtime
  dependency added. The incomplete concurrent-build run with5 skips is retained
  and superseded by the stable-build zero-skip run.
- Lint, typecheck, production build and **22/22 budgets** pass. CSS24,688/25,600B;
  Today169,862/169,984B; Projects169,959/169,984B; legacy conversation192,354/192,512B.
  No cap increased. Existing lockfile; installed dependency tree APFS-cloned from
  shared installation to resolve local Storybook symlink issues, without install.
- Python final patch gate: **6,318 passed**,54 inherited local skips,
  53 workflow-e2e deselections,94.77% overall, **98% patch**. Source tree
  `16cc0220cd060cead41eecdf08d641e8d0705dcb` is unchanged through application62c761a.
  The publication patch gate reran with the final4,217/216 measurement record:6,318
  passed,54 inherited skips,53 separate-tier deselections,98% patch. Package floors api88/agents96/security100/eval95 preserved.
  Host-Postgres binary skips do not substitute for new real Docker Postgres tests.
- Separate workflow e2e53/53, mock simulation20/20 at$0, registry parity260/0,
  global Ruff and strict mypy173 sources pass. Raw failed attempts/cohorts retained.
- Project/thread polish `cea881e` passes96/96 integrated browser cases across
  1440×1000/390×844 light/dark plus reduced motion, actual restart and archive.
  Final `62c761a` changes only selector CSS and passes64 additional route/theme/
  width/motion geometry and axe checks. Both64-scan cohorts have no serious/critical
  violations. Four readable example journeys and four untrimmed queue/Reader motion
  captures pass at62c761a. No console exceptions, blocked requests or provider/source contacts.
  Restart and archive are separately completed in the fresh-browser report;
  the immutable main report correctly retains its earlier awaiting-restart status.
- Actual isolated backup/restore: private dump,38 tables/sequences matched,
  source DB unchanged; only the newly created restore database removed.

## Corrections found during verification

`ca81dce` fixes same-route Radar dispatch mixing new context with old cursor;
red/green tests preserve retry and stale-response behavior. `c834207` contains
project/thread/editor forms at390px. Independent review found the compact mobile
continuation had hidden the saved question/status; `031524f` restores both while
keeping full title plus two abstract lines clear of the player. `8e34670` makes
Library resume preserve saved mode/project/version/anchor while returning to the
current Library view/focus. Activity continuation intentionally resumes its saved
workflow origin. Source scopes and unavailable pinned versions never fall forward.

Supplementary untrimmed desktop/mobile recordings capture native queue changes,
Reader entry and return. Actual decoded native-frame sheets and screenshots were
manually inspected. Earlier misaligned wall-clock trims are rejected as motion
evidence and preserved locally. Owner experience review remains pending.

## Final targeted polish and useful examples

`cea881e` adds scannable project cards/current status and a stronger question,
next-action and evidence hierarchy. Goals, prerequisites and source excerpts lead
learning threads. Native disclosures retain source/version/material IDs, hashes,
scope/parser/offsets, and routine revisions; conflicts and unavailable/history
warnings stay visible. Forms and all exact hrefs/payloads/guards are preserved.
New presentation tests plus existing forms pass72/72. The carried-source test
now opens the native disclosure and pins each exact value, retaining payload pins.

Screenshot review found the selector inheriting a two-column filter grid.
`62c761a` fixes it: actual same-example desktop before/after measures93.328px→316px
in both themes. Only three lines of CSS differ from the96-case functional cohort.
All22 budgets pass after reducing redundant new empty-state copy; no ceiling moved.
An independent read-only source review found no actionable P0–P2 regression;
runtime/native-frame inspection supplies the separate visual evidence.

3178 has three clearly labelled agent-authored example projects/questions/threads,
using real retained ReAct, Self-RAG and retention sources. They are not owner work
or judgments. The explicit import replays without duplicate logical records and
refuses to overwrite edited examples; interests/profile/source-health remain
unchanged. Long mechanical fixtures remain on3179. The short readable walkthrough
opens saved examples; the96-case matrix separately proves new UI saves/creation.
Reader tabs may save only the example's reading position during that walkthrough.
Library resumes the saved question, then Source context opens its exact passage.

Reviewed actual decoded frames/contact sheets in all four themes/widths; native
motion frames inspect queue settling separately. Source/heading landings, exact
project return, Library passage, logical focus, player clearance and mobile drawer
flow checked. Reduced motion is independently asserted. This is implementation
review, not owner usefulness or physical-device acceptance. Original failures,
transient animation sampling and earlier wrongly timed clip trims remain local
and hash-indexed. Final axe waits for actual animation completion, with no scan,
assertion or floor removed. Copied preference values/bulk API abstracts are omitted
from committed receipts; originals and full personal-profile recordings remain
local. Selected labelled-example screenshots and neutral motion clips are committed.

## Remaining limits and publication

Browser-store Back/Forward recovery passes where storage works. With storage
unavailable, a full reload loses unsaved text after an explicit warning; this is
an unresolved reliability limit, not durable persistence. Corrupt storage warns,
keeps the current draft and preserves the corrupt bytes. Physical mobile OS
keyboard, Safari and real IME are not qualified by Chromium viewport/event tests.
Manual records and exact citations are not model factual-support/quality evidence.
Human usefulness/comprehension and longitudinal daily use remain unmeasured.

Local gates are attributed to exact application/source commits above. Remote CI
is a separate exact-published-head gate, available in the branch workflow record
and the final owner checkpoint; local success never substitutes for it. No merge
or deployment. The original failed browser runs remain
local and hash-indexed; accepted evidence does not relabel failures as passes.

## Preserved authority and accounting

No provider or token-count contacts, source acquisition, recurrence, notification
or everyday generation. Historical accounting receipt SHA256
`92c3c54c962171e3473344856276d6a5f81593ae5e3a129d45a0e28ad8c304ee`
remains unchanged: estimated$0.109967 (workflow$0.094655/checker$0.015312),
unknown0,9Messages/15counts/6jobs. q01 development,q02–q04 failed,q05–q10 unrun.
Scoped approval closed; later paid validation needs fresh explicit approval.
No new PR, merge or deployment. Existing PRs remain unmerged.

## Historical records (superseded implementation snapshots)

The following entries describe their original dates, not the current gate table.

## First reviewable milestone after controller/benchmark checkpoints

A model-free connected loop: Explore Today with no question → exact-version
Reader → saved question → Investigate this → durable Research project → question
match outside the interest profile → Learn prerequisite → return to the same
project passage → Library resume after reload/restart.

Keep owner3137/data/preferences untouched; use isolated DB/principal and explicit
fixture labels. Record actual checks against the final application commit and
remote CI separately. Recurrence and everyday paid generation remain disabled.

## Documentation verification

Prepared in fresh branch `codex/workspace-two-modes` from controllerdff860e.
All53 local Markdown file links across the7documents and2indexes resolve.
`tests/test_documented_claims.py tests/test_repo_hygiene.py` pass **66/66**;
normal process access rerun8.95s finishes cleanly. The initial sandbox run also
passed66 assertions but emitted a psutil process-list cleanup permission error;
it is not the final clean result. `git diff --check` passes.

An independent read-only review confirmed owner direction, code inventory,
current G6 limitations, dependencies and benchmark preservation. Its one
consequential finding was fixed: a later paid set explicitly requires fresh
owner approval; unused headroom cannot broaden q04–q10. No frontend/backend
source, frozen input, service, preference or human label changed. No remote CI
or product acceptance is claimed for these planning documents.

## Diagnostic update, 2026-11-05 UTC / Nov4Pacific

The prospectively sealed V8 continuation stopped onq04 after the checker abstained
on one claim and the permitted repair count6765exceeded6400usable input tokens.
q04 remains failed/resultNone; q05–q10 were not dispatched. No replay or further
adaptive paid continuation. The scoped approval is closed.

Audited cumulative estimate$0.109967(workflow$0.094655/checker$0.015312),unknown
liability$0,9Messages/15counts/6newgenerationjobs. Original nine-primary scope
remains0completed,3failed,6unrun; human quality/usefulness is unmeasured. This
changes no mode implementation status or benchmark threshold. The separate
offline ranking followup informs future Research policy, not owner learning
usefulness. Later paid validation requires fresh explicit owner approval.


## Controller integration verification

The four planning commits were cherry-picked after G7 runtime release. The
controller application remains frozen at `6b2eccf069537d90423359fc74c033f27e665cd6`;
its current local G7 result is recorded above, independently of this kit's
`dff860e` starting snapshot. Fresh integrated documented-claims/repository-hygiene
checks pass **66/66 in 9.18 s**. Publication and exact pushed-head CI are pending
root integration. No mode UI, backend, source acquisition or owner data changed.

## D0 baseline, 2026-11-05

Controller base `7e1bd9792ef60c64ee13c94a88b7783cc30b512a`; reconciled backend
`10b4260f734c88a250880cb07d284a467e273529`; unchanged web tree
`e4f4f72d1b49f1647fb116e52105c90b03c0335c`. See [baseline](05-d0-implementation-baseline.md),
[API contract](06-context-api-contract.md), [predeclared policy](07-ranking-policy-v1.md)
and [browser evidence](evidence/d0-browser/README.md).

Fresh local results:179 qualification/accounting/source/API regressions passed;
20/20 production budgets passed;28 route observations and28 axe scans passed
across desktop/mobile and both themes. Zero browser writes, provider/source
requests, overflow, console or hydration errors. These establish the existing
controller baseline, not new-mode acceptance. Remote CI is not yet run for this
batch. CSS23,940/25,600B; original JS ceilings unchanged.

Preview http://127.0.0.1:3178/workspace/today uses40 copied public works and an
isolated copy of the actual saved11-interest/15-minute profile. It shows honest
limited coverage and retained source dates. No owner notes/history/labels copied;
owner3137 untouched. New projects/threads remain under implementation.

Paid dispatch, including counts, is stopped. Historical estimate$0.109967,
9Messages/15counts/6jobs,unknown0; closed approval; q01 development, q02–q04
failed, q05–q10 unrun. Everyday generation and recurrence remain disabled.
