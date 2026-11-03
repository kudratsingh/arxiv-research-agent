# Daily research workspace direction kit

Prepared **2026-11-02** for Kudrat Singh and the implementation agent.

Build a personal research workspace that helps an ML student and researcher
notice important work, understand it in context, and decide what to learn,
investigate or build. The first complete workflow is **daily briefing → guided
deep dive → saved understanding and next action**.

The owner selected **daily briefings plus guided deep dives** and **local-first
operation, approving paid services separately** in this conversation. Those
choices govern this kit. The detailed architecture, visual treatment and work
order boundaries below are recommendations for implementation with the owner.
No subscription, paid inference, hosted service or notification delivery is
enabled by this kit.

## Read and use the kit

| File | Purpose |
|---|---|
| [00-direction.md](00-direction.md) | Product intent, needs, differentiated features and first release boundary |
| [01-product-research.md](01-product-research.md) | Current tools and research patterns, sourced observations and implications |
| [02-sources-and-topic-coverage.md](02-sources-and-topic-coverage.md) | Scholarly/news/code sources, taxonomy, access boundaries and coverage |
| [03-experience-and-design.md](03-experience-and-design.md) | Routes, screen specifications, wireframes, interactions and visual direction |
| [04-architecture-and-technology.md](04-architecture-and-technology.md) | Reuse, technology decisions, data objects, scheduling and proposed APIs |
| [05-work-orders.md](05-work-orders.md) | Dependency-ordered build slices with acceptance and review points |
| [06-quality-cost-and-operations.md](06-quality-cost-and-operations.md) | Evaluation, freshness, reliability, privacy and budget gates |
| [07-topic-seed.json](07-topic-seed.json) | Machine-readable proposed topic-navigation seed; not a source-coverage guarantee |
| [08-agent-handoff.md](08-agent-handoff.md) | Copyable assignment for the next implementation agent |
| [09-decisions-and-owner-input.md](09-decisions-and-owner-input.md) | Settled choices, proposed defaults and the few inputs that materially change the build |
| [10-example-briefing.md](10-example-briefing.md) | Clearly fictional acceptance scenario from morning scan through experiment proposal |
| [11-source-starters.json](11-source-starters.json) | Ten disabled source options, including eight feed endpoints checked with bounded reads |

Start the implementation agent with **08**, then have it read **00, 03, 04,
05 and 06**. Use **01 and 02** for the rationale and integration details.
The source catalogue and taxonomy are deliberately broader than the first
release's live ingestion. Every selectable interest must show what coverage
is actually connected.

Current implementation checkpoint: [daily workflow and qualification readiness](20-readiness-and-qualification-walkthrough.md), [STATUS](STATUS.md), and the [unexecuted measurement proposal](15-grounded-generation-approval-packet.md).

## Relationship to the existing project

This is a transformation of `arxiv-research-agent`, retaining its Next.js
Evidence Workbench, FastAPI/SSE jobs, LangGraph research and reading machinery,
Postgres/Redis, exports and testing conventions. It advances the previously
adopted research-radar and reading-companion directions, with parts of the
personal-memory and literature-review directions. Course publishing and the
old learning pilot are no longer prerequisites to this new personal workflow.

The preceding [current-state review](../10-current-state-review-2026-11-02.md)
is the implementation inventory. At kit preparation, local `main` was
`dbd4bb8`, while `origin/main` was `88d283d`; do not build on the older checkout
without reconciling those six commits. The review's factual-metric,
source-retention, settings-enforcement, calibration and costing gaps remain
relevant when enabling generated analysis. Metadata discovery and manual
reading do not require completing the whole historical five-arm campaign.

## First useful release

Select and tune interests; ingest arXiv plus a few approved primary-source RSS
feeds; open a bounded daily briefing with source/freshness explanations; save
and annotate an item; enter an evidence-aware reader; retain questions and
notes across visits. Before approved paid inference, the briefing uses source
metadata/excerpts and manual reading. Generated summaries and guided responses
are a later opt-in capability of that same experience, with explicit evidence
scope and budgets.

The first owner review is a realistic, fixture-backed Today/Reader interaction.
The first daily-use milestone is reliable local intake and retrieval of saved
work. Neither a static mock nor a passing synthetic eval constitutes acceptance
of generated research quality. The implementation agent should make each
milestone runnable and reviewable before asking for its next consequential
decision.

## Implementation started

The owner authorized W0/W1 and supplied an initial lens and organizing question.
Use [STATUS.md](STATUS.md) for the live work record and
[the baseline and walkthrough](12-w0-w1-baseline-and-walkthrough.md) for the
first runnable milestone, checks and unresolved evidence. The broader product
is not complete at the fixture milestone.

The live follow-up is documented in [the local walkthrough](14-live-local-walkthrough.md), [current status](STATUS.md) and [unexecuted generation proposal](15-grounded-generation-approval-packet.md).

The current follow-up is [the personal review and fake-executor walkthrough](16-review-and-executor-walkthrough.md), with [scientific extraction limits](18-fulltext-qualification.md) and [disabled everyday operation](19-everyday-operation.md). Real generated summaries and guided dives remain explicit separately approved milestones.
