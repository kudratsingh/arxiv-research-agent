# Project state and remaining plans

Review date: **2026-11-02**. This is a discussion baseline for the next phase.
It records implementation and remaining work; it does not adopt a new product
direction or authorize a live campaign.

The project has built the research assistant, its web workbench, a guided-read
wedge, assurance tooling, and the infrastructure for policy experiments. The
next dependency in the existing engineering plan is a valid measured baseline
and judge calibration. Several evaluation integration defects still need work
before that baseline can support a policy decision.

## Repository snapshot

| Surface | Verified state |
|---|---|
| Local working checkout at the start of review | Clean `main` at `dbd4bb8e1c8afceba92caf983f018db74cbdcd14` |
| GitHub `main` | `88d283d66a6f5a908caba0b1774b6c592c4f018e`, six commits ahead; latest commit on 2026-09-18 |
| Open GitHub PRs and issues | None returned by the repository searches |
| Review and test checkout | Separate detached worktree at the GitHub commit; the working checkout was not advanced |
| Live evaluation evidence | The tracked records say no funded campaign has run. The working checkout's `outputs/` contains no campaign episode record or `summary.jsonl` |
| Workflow state | `ci` active; `nightly-eval` and `nightly-lighthouse` both `disabled_manually` |
| Latest GitHub CI | [Run 41434132708](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/41434132708), 2026-11-02 UTC: dependency audit failed; Python test job cancelled before completion; seven other jobs succeeded |

Code links below are pinned to the reviewed GitHub commit. The local checkout
predates its six evaluation follow-ups, so local source files alone give an
incomplete account of what has landed.

The earlier ledger was found at
`/Users/kudratsingh/Downloads/arxiv-eval-fix-ledger.md`, reviewed against
`dbd4bb8`. Its SHA-256 is
`6d011baa599759f174c7d732c10403ec2f8cfb58e6f4933ce66853844e9cff12`.
The EL numbers below refer to that ledger. They are different from the
agent-engineering discussion page's D1-D15 decision numbers.

## Previously agreed direction

The learning-platform record adopted **a real product with users and
learning by building**, with additional investment in the agent and model
harness. Phase W was the first product wedge. The nine-direction portfolio
was adopted as long-term intent, with one direction built at a time behind
evidence gates. The ordering beyond Phase W was left open; W, research radar,
then newsletter distribution was a proposed sequence.

The agent-engineering conversation separately ratified:

- claim support and evidence completeness as the first optimization target;
- the fixed pipeline as the control;
- evidence, calibrated verifier abstention, and targeted repair as the first
  candidate;
- deterministic direct-versus-verify-and-repair routing as the first compute
  policy;
- training after consented trajectories and reliable rewards exist;
- self-improvement through offline proposals with external promotion control.

Sources: [learning owner decisions](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/07-learning-platform/STATUS.md),
[ratified engineering answers](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/06-decisions-and-discussion.md#ratified-answers-from-the-first-conversation).

## Implemented tracks and their remaining work

| Track | Implemented | Remaining from its plan |
|---|---|---|
| Original Sprints 1-5 | Research planning, arXiv search, PDF parsing/chunking/ranking, parallel reading, synthesis, critic revisions, supervisor/verifier/recovery options, caching and model routing; API, SSE, HITL, conversations and exports | The empirical baseline and results table; optional Slack bot; later enterprise features. Old unchecked sprint bullets do not reliably indicate current implementation |
| Service hardening | Redis jobs/pub-sub/rate limits, Postgres checkpoints/conversations/caches, ownership checks, worker leases/redriver, bounded executor, cancellation, cost controls, typed errors and dead letters | End-user identity, global multi-user spend control, production operation and its measurements |
| Evidence Workbench revamp | All 33 work orders merged; Gates 1-4 recorded closed, Gate 4 with a human accessibility reservation; design system, browser tests, axe, Storybook and budgets | Human screen-reader pass RR-02; deployment; MT-01; GitHub social-preview upload. S2d and visual-comparator work later merged despite stale status rows |
| Guided-read Phase W | Nineteen of twenty planned cards merged at their no-cost boundary: session lifecycle/graph, learner profile provenance, assessment, bounded Tier-1 memory, caps, progress events, path/session/Ledger views, simulation/eval infrastructure, content review and pilot tooling | W20 requires the 14-day pilot observation window. Paid evaluation, real briefing generation/review, publication, pilot limits/invitations and engagement threshold decisions remain |
| Learning content | Repo-versioned content manifests and publishing validators; a fixture path is published | The real flagship path remains proposed. Its briefing companions have not been generated/reviewed. This is not a finished real course catalogue |
| Assurance | Gates A1-A3 and follow-up waves: coverage/harness guards, property/fault/security tests, error and degradation contracts, GenAI telemetry, safety evaluation, statistics, system card, claim enforcement and runbooks | Real quality/judge calibration and operational evidence. Recorded provider-response cassettes are still absent. Current dependency audit and CI completion require attention |
| Agent capability | Model-aware gateway; fixed verify-and-repair; branch workers; deterministic T0-T2 routing; listwise selector; marginal-stop record; full mock graph; SDK upgrade | CAP-06 live observations; measured quality/cost/latency comparisons; selector/verifier calibration. T3 and a learned compute router remain future work |
| Engineering P0 | TaskSpec, sealed RunManifest, canonical trajectory, registry, campaign matrix/ledger/resume/report, Stage-0 qualification and funded-path scaffolding | W12 repeated live baseline and a representative human-labelled calibration set; integration gaps described below |

Sources: [planning index](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/README.md),
[Phase W status](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/07-learning-platform/STATUS.md),
[content status](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/content/README.md),
[assurance status](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/08-assurance/STATUS.md),
[capability status](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/09-agent-capability/STATUS.md),
[P0 implementation table](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/README.md#p0-implementation-status).

The four research graph shapes and the five experiment arms are different
counts. A is the fixed pipeline, B adds evidence, C adds fixed verification and
repair, D uses the verified supervisor, and E uses adaptive routing over the
available tiers. B reuses the fixed graph; E chooses a graph per task. The
guided-read session has its own separate graph.

## Six follow-ups beyond the local checkout

| Commit and PR | Landed change |
|---|---|
| `b1affff`, [275](https://github.com/kudratsingh/arxiv-research-agent/pull/275) | LE-J, ADR 0100: identified sources, collision-aware citation resolution, optional reader chunks, null empty denominators, judge temperature/schema metadata, three rubric versions at 2.0.0 |
| `c7f62e5`, [277](https://github.com/kudratsingh/arxiv-research-agent/pull/277) | LE-S, ADR 0101: live scorer, isolated judge accounting/cap, state snapshots, recovery before completion, workflow cap binding, drift/judge-failure stops, expanded rehearsal and CAP-06 smoke command |
| `628dae5`, [278](https://github.com/kudratsingh/arxiv-research-agent/pull/278) | LE-K part 1: retrieval labels, staged labelling text and measured-verdict ingest |
| `1cc68dd`, [279](https://github.com/kudratsingh/arxiv-research-agent/pull/279) | LE-V: paper-id runtime verifier sources, publication dates, request-id retention, durable reader fallback reasons |
| `1ca83f0`, [280](https://github.com/kudratsingh/arxiv-research-agent/pull/280) | LE-K part 2: representative calibration-pool builder |
| `88d283d`, [276](https://github.com/kudratsingh/arxiv-research-agent/pull/276) | LE-C, ADR 0102: per-query statistics, query-first bootstrap intervals, baseline difficulty, measured-token estimator, protocol setting digests and plan amendments |

These additions substantially change the September ledger's implementation
status. Merged code still needs the cross-module corrections below.

## Evaluation gaps verified in this review

**The primary metric still accepts false factual claims.** The campaign
continues to declare `supported_claim_precision` as its primary metric. Even
the live scorer copies `free.primary_score` into that field. A no-network
probe using the current groundedness code and three false cited statements
produced three decided observations, three passes, and **1.0**. Their
identifiers resolved; their factual support was not assessed. Faithfulness is
computed separately and has not replaced the primary. This leaves EL-06 open.
See [primary score assignment](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/scoring.py#L474).

**Arm A still loses the reader material required by Option A.** Episode
snapshots build `reader.chunks` from `state.evidence`. Arm A disables the
evidence store, so its reader chunks are absent and its faithfulness check
falls back to abstracts. Evidence arms can receive abstracts plus chunks.
The report also has no source-scope grouping or refusal before aggregation.
Comparable source material must be captured independently of the policy's
evidence feature before A-versus-C can answer the intended question. See
[chunk retention](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/execute.py#L1288),
[arm settings](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/arms.py),
[report aggregation](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/report.py#L821).

**Protocol settings are recorded without being enforced at execution.** A
zero-spend probe planned temperature **0.3**, then executed the same plan with
configuration temperature **0.9**. The runner received 0.9; the episode
completed and the campaign did not refuse it. The frozen mapping contributes
to a newly planned campaign's digest, but `execute_campaign` does not check
the supplied configuration against it. The explicit frozen subset also omits
several values in doc 07's common-settings table. See
[frozen subset](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/manifest.py#L63)
and [execution setup](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/execute.py#L1690).

**The calibration pool builder does not consume actual campaign output.** A
zero-spend campaign with injected per-claim/per-topic scores wrote the real
artifact layout. Calling `build_pool` on it raised `no episode verdicts found`.
The builder looks for `record.json` or `scores.json`; the campaign writes
`episode-record.json`, while `scores.json` holds only the ledger receipt.
Actual judged metrics are nested at `record.scores.metrics`. The builder also
expects a list of chunks while snapshots store a mapping by paper, and it
hard-codes the source-scope label. Existing pool tests use a fabricated
`scores.json` shape, so they pass without exercising this integration. See
[pool reader](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/calibration/pool.py#L38)
and [campaign artifact writer](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/execute.py#L2678).

**The measured-token estimator still has incorrect call-count semantics.**
With `revision_count=0`, a probe produced no critic line. With two revisions,
only the critic count changed: planner, reader and synthesizer counts stayed
at one nominal pass. The calculator applies 1.25 to the median expected total,
while the packet describes a worst-case basis. It also hard-codes the workflow
model. These are additional reasons to repair the costing contract before
using the estimator to set caps. See
[estimator](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/calibration/estimate.py#L247).

**Judge temperature is separate; structured-output activation is still shared.**
Judge calls now supply schemas and use `eval_judge_temperature`, default 0.0.
The gateway still enables schemas through the shared
`enable_structured_outputs` setting, default false. There is no judge-only
activation override. Passing a schema therefore does not itself establish
that the production judge request enforced it. See
[request profile](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/llm.py#L350).

**Re-judging and representative calibration remain incomplete.** The campaign
CLI has eight verbs, including `smoke`, and no `rejudge`. Interrupted episodes
can recover their first score from a snapshot, but there is no immutable
multi-pass judge-noise experiment. Measured-verdict ingest validates/counts
submitted verdicts; the representative pool, human packet generation,
adjudication and judge-human calibration are not yet one working pipeline.
See [CLI](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/campaign/cli.py),
[verdict ingest](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/src/calibration/packets.py#L1070).

**The live-eval plan is not yet one consistent executable protocol.** Doc 07
retains its original 50-episode, five-arm screening stage and adds a
20-episode checkpoint below it. The later ledger instead specifies a
60-episode arm-A baseline in 20-plus-40 tranches. The new checkpoint omits
several of the ledger's intended checks. The saturation sentence in doc 07
says to stop widening at high completeness and widen otherwise, reversing
the ledger's response to a ceiling. The Stage-1 note names query shapes that
do not correspond to actual benchmark case IDs. The approval packet still
quotes the old $22.48/$75 arithmetic and old expert-time figures. See
[stages and checkpoint](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/07-first-policy-experiment.md#6-staged-execution-plan),
[saturation wording](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/07-first-policy-experiment.md#L430),
[Stage 1 note](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/18-stage1-plan.md),
[approval packet](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/16-w12-approval-packet-draft.md).

## Reconciliation of the 28 ledger findings

“Implemented” below describes the reviewed code and no-cost checks. Live
provider behavior and quality outcomes still require their own observations.

| Finding | Current assessment | Remaining work |
|---|---|---|
| EL-01 live scorer | Implemented | Observe against the provider after the definition/integration fixes |
| EL-02 judge accounting/cap isolation | Implemented | Measure real judge usage |
| EL-03 scorer crash recovery | Core recovery implemented | Explicit fill-missing/rejudge tooling remains EL-14 |
| EL-04 SDK smoke script | Implemented | CAP-06 has not been observed live |
| EL-05 diagnostic state persistence | Partial | Arm-independent reader chunks and an agreed retention period |
| EL-06 primary claim-support metric | Open | Choose and implement a factual support primary; preserve deterministic citation/quote diagnostics under truthful names |
| EL-07 task-rubric success | Proxy documented | Doc 07 now explicitly uses completeness as the stand-in; a separate task rubric remains future work |
| EL-08 source collisions | Implemented | Both metric and runtime verifier now preserve paper identity; real collision rates unmeasured |
| EL-09 full reader material for judges | Partial | Arm A has no retained chunks; scope comparability/aggregation needs enforcement |
| EL-10 perfect scores for empty denominators | Implemented | New null/reason definitions are versioned at 2.0.0 |
| EL-11 judge sampling/schema | Partial | Separate temperature and schema arguments exist; judge-only structured-output activation is absent |
| EL-12 coarse completeness ceiling | Partial and inconsistent | Reconcile the reversed saturation sentence and checkpoint action; data remains coarse |
| EL-13 per-query variance | Substantially implemented | Query means/spread, seeded intervals and difficulty exist; requested explicit between/within variance decomposition is absent |
| EL-14 rejudge passes | Open | CLI, immutable pass artifacts, cap/approval, noise reporting and fill-missing mode |
| EL-15 drift/judge-failure stops | Added rules implemented | Confirm live behavior and keep the process/safety rules distinct from these automated checks |
| EL-16 rehearsal coverage | Implemented | State retention, stop rules and scorer resolution added; rehearsal is not live validation |
| EL-17 mid-episode workflow cap | Implemented | Measure fan-out overshoot under real usage |
| EL-18 reader costing/caps | Partial | Three judge calls now budgeted; fix estimator semantics and collect measured tokens before repricing |
| EL-19 frozen settings | Partial | Recording/digesting exists; reject or restore mismatched runtime settings and cover the full instrument definition |
| EL-20 representative item builder | Partial and broken at integration | Read actual artifact names/nesting/chunks, preserve source scope, connect to representative registration/packets |
| EL-21 calibrate production instrument | Partial | Production-verdict ingest exists; complete the human-label comparison and rejudge path |
| EL-22 calibration label coverage | Partial | Retrieval label type added and pairwise removed from first-pass estimates; pool construction still omits retrieval items |
| EL-23 staged independent annotation | Plan updated | Start with 40-50 items; name a second annotator or report agreement unmeasured; resolve label retention |
| EL-24 live approval packet | Partial | Live scope and drift wording updated; reconcile all costs, checkpoints and stale after-credential claims |
| EL-25 mixed Stage-1 slice | Partial | Bind three real registry case IDs/text/revisions and define the actual report/caps |
| EL-26 20-plus-40 baseline | Partial | `--max-episodes 20` exists; write the correct baseline checkpoint and continuation rule in the authoritative runbook |
| EL-27 fresh interleaved A+C | Plan corrected in part | Fresh campaign is stated; retrieval-overlap analysis and a real record/replay corpus remain absent |
| EL-28 prices and judge model choice | Open operational decision | Price table remains dated 2026-08-20; verify provider facts and record the judge/workflow model choice before any funded stage |

The ledger's **$35-45 expected total for Stages 1-3**, **$6 Stage-1 cap** and
**5-10 hours for an initial annotation pass** remain planning estimates. They
are not current quotes, approved budgets or measured costs. The old $75 cap
must not be carried forward automatically.

## Work still planned beyond evaluation

The agent-engineering roadmap has seven phases. Implementing pieces out of
order has not closed their evidence gates.

| Phase | Previous plan | Current boundary |
|---|---|---|
| P0 | Measurement contracts, registry, calibration and repeated baseline | Contracts/tooling largely built; baseline and representative calibration outstanding |
| P1 | Evidence graph v2, source quality/freshness, deterministic validators, calibrated verifier cascade, targeted repair | Existing claims and repair policy are foundations; the complete graph/cascade and measured gains remain |
| P2 | Difficulty features, candidate protocol, listwise selection, deterministic routing, ablations, optional learned router | T0-T2 controller/branches/selection already built; validation, matched-budget experiments and learned routing remain |
| P3 | Consented feedback store, curation/credit assignment, offline prompt/policy search, shadow promotion | Planned |
| P4 | Web research, sandboxed analysis code, hierarchical project ledger, loss-checked compaction, long-horizon benchmark and Deep Research mode | Planned |
| P5 | Model ownership/serving, distillation, preference optimization, value/verifier models, narrow RL and scaling studies | Planned and conditional on data/reward/operating-cost evidence |
| P6 | Bounded self-improvement proposals, archive/lineage and isolated evaluation fleet | Planned; external promotion remains the intended boundary |

Source: [engineering roadmap](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/docs/agent-engineering/04-roadmap.md).

The broader learning platform is also still a proposal beyond Phase W:

| Phase | Remaining scope |
|---|---|
| L0 | Real end-user identity/MT-01, global spend safety and account/profile surfaces |
| L1 | Persistent content graph, courses, lesson generation/review and read-only learning |
| L2 | Scheduler, daily preparation, notifications, preferences and 14-day daily-loop pilot |
| L3 | Assessment/progress/retention, spaced repetition and recomputable mastery records |
| L4 | Scale hardening, quotas, possible public signup, load tests, operations and provider cassettes |

Phase W pulled forward narrow profile/session/assessment surfaces. That does
not mean the L0-L4 plans have shipped wholesale. The deferred wedge list also
includes curriculum planning/replanning, in-session research, Tier-2/3 memory,
notifications, the content database and a study of actual human learning.
Sources: [learning roadmap](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/07-learning-platform/03-ARCHITECTURE-ROADMAP.md#6-phased-roadmap),
[wedge exclusions](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/07-learning-platform/05-WEDGE-WORK-ORDERS.md#7-not-scheduled).

The nine adopted product directions remain: research radar, literature-review
workbench, lab/team workspace, R&D/investor briefings, paper-reading companion,
personal research memory, claims/code/benchmark tracking, newsletter/media,
and API/platform access. Their portfolio entries are charters and evidence
gates. They are not nine completed implementation plans. See
[direction portfolio](https://github.com/kudratsingh/arxiv-research-agent/blob/88d283d66a6f5a908caba0b1774b6c592c4f018e/planning/07-learning-platform/06-DIRECTION-PORTFOLIO.md).

## Documentation and decisions needed for the next phase

The immediate documentation task is to reconcile the existing plans before
extending them. Several status pages predate the six evaluation commits, the
agent-engineering index stops at document 17, and old open rows include work
that merged later. The user has not yet specified the next phase's new scope.

A useful next planning package would contain:

1. One live-evaluation runbook separating the original five-arm screening/full
   experiment from the later four-stage arm-A baseline/calibration/A+C plan.
   It should bind actual case IDs, instrument versions, source scope, tranche
   checkpoints, annotation workflow, and a reproducible costing method.
2. A metric/instrument decision covering the factual support primary,
   completeness proxy, judge schema activation, claim extraction coverage,
   missing denominators, source material and calibration thresholds.
3. Bounded work orders for the remaining integration defects, each with a
   cross-module acceptance check against actual emitted artifacts.
4. A next-phase charter defining the intended user or capability outcome,
   exclusions, dependencies, evidence needed to accept it, costs and rollback.

Existing owner decisions still include live funding/model/prices; annotation
people and retention; Phase W generation/publication/pilot thresholds and
limits; deployment; MT-01; the human screen-reader pass; and the later
engineering tool/data/autonomy choices. The licensing decision is already
recorded as all rights reserved and should not be reopened accidentally.

## Verification evidence

The reviewed source and tests came from GitHub `main` at `88d283d`, executed
with the existing local Python **3.13.7** environment in the detached review
worktree. These are local results, without coverage collection, and do not
replace the cancelled Linux CI run.

| Check | Result |
|---|---|
| Focused evaluation, persistence, smoke, calibration, verifier and plan tests | **374 passed** |
| Full Python suite excluding e2e | **5,582 passed, 54 skipped, 53 deselected**, 226.35 s |
| Python mock e2e tier | **53 passed, 5,636 deselected**, 13.15 s |
| False cited-claim probe | Three false statements received deterministic primary value **1.0** |
| Actual campaign artifact to pool probe | Builder raised **no episode verdicts found** |
| Runtime settings probe | Planned **0.3**, executed **0.9**, episode completed |
| Cost-estimator probe | Zero revisions omitted the critic; two revisions changed only its count |

The campaign integration probes used a scripted runner and a counting tripwire
over provider-client construction and socket connections; both probes
reported **zero touches**. No funded episode or live model judge was run.

GitHub's current dependency-audit log reports **three blocking production
dependency entries**: `next` (critical), `sharp` (high), and `source-map-js`
(high). It also reports additional development-tree findings and stale
exceptions. The Python job was cancelled at about 45% of its test run after
roughly 15 minutes. These are separate maintenance items from factual
evaluation validity. Sources: [audit job](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/41434132708/job/125239670308),
[Python job](https://github.com/kudratsingh/arxiv-research-agent/actions/runs/41434132708/job/125239670232).

This review did not rerun the browser/Compose tiers locally, provision a host,
invite pilots, alter workflow state, or verify the provider's November model
catalogue/pricing. GitHub's browser, web, Storybook, image and lint/type jobs
were read from the linked current run. No existing plan, product source file,
campaign result or GitHub record was changed by this review.
