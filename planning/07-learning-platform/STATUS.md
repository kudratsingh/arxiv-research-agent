# Learning platform campaign — status

Updated: 2026-09-01

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

Still owed by the owner before their respective gates (unchanged):
eval funding (~first paid run), DEPLOY cost approval, MT-01 §8 answers
(deferred to Rung 3 / Phase L0), content licensing posture (02),
notification channel (01/03).

## Phase W execution

The plan is approved and implementation is in progress. Thirteen of the 20
cards are implemented and merged to their no-cost boundary through WO-W06:
W01–W09, plus W12, W15, W16, and W18. Owner-dependent funded/public/pilot
criteria on those cards remain visibly deferred. The merged work includes the
shared job/session lifecycle, learner profile,
guided-read graph, evidence-grounded assessment, bounded Tier-1 memory,
per-session cost enforcement, honest progress ledger, deterministic eval
fixtures/metrics, the path surface, guarded flagship content, static
publication package, and pre-committed engagement reporter.

The next no-cost critical-path cards are **W13** (session surface) and **W14**
(honest ledger view). W10/W11 remain built only after a newly approved funded
eval campaign; W17 remains blocked on pilot/deploy/inference approval; W19 can
assemble the no-cost Gate W1 evidence while marking funded rows unresolved;
W20 follows the 14-day pilot observation window.

Standing cost lock (2026-08-30, reaffirmed by continuation): the paid nightly
eval workflow is disabled, and no funded model run, deployment, public launch,
or pilot invitation may occur without a fresh explicit owner approval. Local,
mock, recorded-fixture, static, and CI validation continue under that lock.
