# Implementation agent assignment

Copy the assignment below into the implementation agent that already has the
repository. Send the whole kit directory with it if that agent cannot access
the local checkout. This is an additive direction handoff, not repo onboarding.

## Copyable assignment

You are transforming `arxiv-research-agent` into Kudrat's personal daily
research workspace. Read this direction kit before choosing an implementation:

```text
planning/11-daily-research-workspace/README.md
planning/11-daily-research-workspace/00-direction.md
planning/11-daily-research-workspace/03-experience-and-design.md
planning/11-daily-research-workspace/04-architecture-and-technology.md
planning/11-daily-research-workspace/05-work-orders.md
planning/11-daily-research-workspace/06-quality-cost-and-operations.md
planning/11-daily-research-workspace/09-decisions-and-owner-input.md
planning/10-current-state-review-2026-11-02.md
```

Consult 01/02 for current research/source constraints, 07 for the topic seed,
10 for a clearly fictional design scenario and 11 for starter source choices.
The product outcome is **daily briefing → guided deep dive → durable question,
insight or next experiment** for an ML student/researcher. The owner explicitly
selected **daily briefings plus guided deep dives**, **local first**, and
**paid services approved separately**. Preserve those choices.

### First actions

1. Verify your local branch/head, remote head, dirty files and applicable
   AGENTS/CLAUDE instructions. The source review saw local `dbd4bb8` behind
   GitHub `88d283d`; establish the present truth. Create an isolated `codex/`
   working branch/worktree when needed. Preserve the kit and unrelated edits;
   do not reset or advance the owner's shared checkout without instruction.
2. Read existing architecture, source/job/auth boundaries, the current-state
   review and relevant Next.js docs under the installed package as required by
   `web/AGENTS.md`. Check current dependencies and gate health rather than
   assuming the previous green snapshot is current.
3. Record the new direction and the small set of architecture/API decisions
   that affect the first slice. Revise the old Phase-W-first ordering explicitly;
   course publishing and educational pilots do not block the personal radar.
4. Execute W0 and W1. Produce one connected fixture experience with Today,
   broad interests, item/reader, a saved question and return continuity,
   including mobile and a failed source. Use the existing visual system and
   quality gates; give it a deliberate research-oriented information hierarchy.
5. Present the runnable walkthrough and screenshots to the owner. Ask concise
   questions about density, sources/interests, reading depth and workflow. Keep
   independent storage/intake work moving while awaiting optional preferences.

### Implementation constraints

- Evolve the existing Next.js/FastAPI/LangGraph/Postgres/Redis app. Add small
  source parsing and durable task capabilities where justified; do not rebuild
  the stack or introduce an autonomous framework/graph DB by default.
- The no-key workflow must support real metadata, attributed abstracts/excerpts,
  manual source reading, notes and local catch-up. It is an intermediate useful
  release. Deliver the approved grounded generated-summary/deep-dive stages
  after their evidence and budget gates; do not quietly reduce the full goal
  to a bookmark dashboard.
- Offer expansive topic navigation and detailed ML interests. Keep custom
  topics, aliases and cross-field lenses. Label actual live coverage, access
  and last successful check. The topic seed does not prove global coverage.
- Distinguish logical work, source record, source version, story cluster,
  article/news, code, model and dataset. Preserve dates/precision, provenance,
  authorship, read/save state and updates; do not merge by title alone.
- Local scheduling requires a real worker and durable state. Define timezone,
  DST, retry and sleep/catch-up behavior. The current job redriver is not a
  complete scheduler. A closed laptop cannot guarantee a morning alert.
- Generated statements need source/version/span links and declared access
  scope. Preserve independent source material even if a policy has no evidence
  store. Fix false citation-resolution-as-support, settings drift, real
  artifact calibration input and costing errors relevant to these features.
- Ideas and build briefs are hypotheses/proposals with premises, related-work
  search limits, falsifiers and resource requirements. Unknown hardware remains
  unknown. Reading does not authorize repository execution or model downloads.
- Preserve principal scope, safe fetching/rendering, existing demo and API
  contracts, secrets isolation and export/deletion behavior.
- Use source fixtures and no-network fake-provider checks before live access.
  Any selected live connector must be bounded, permitted and verified against
  its current official quota/terms. Keep paid generation and delivery disabled
  until their concrete approved configuration exists.

### Acceptance and stop conditions

Use W0-W12 and Q0-Q5 as the build/evidence map. Every PR or reviewable slice
should report what changed, why, relevant checks and remaining evidence.
Update OpenAPI/TypeScript, migrations, tests and docs with changed contracts.
Run the checks appropriate to each slice and mandatory repository gates.

Stop dependent work and ask the owner when the next step would incur paid
usage, create a subscription/host, publish material, send an external message,
delete owner data or require a consequential product decision with no safe
reversible default. Make the work concrete first: show the exact scope,
price/call envelope, data flow, destination or before/after. A secret/key or a
proposed cap is not spending authorization. Continue unrelated reversible work.

Stop and report an integrity failure if a source cannot support the claimed
analysis, an adapter requires disallowed access, billing is uncertain, or
runtime settings differ from sealed scope. Preserve partial output and
lineage. Do not weaken evaluation, dependency or privacy gates to declare done.

The end result must include a real owner walkthrough of a daily briefing,
grounded guided reading, saved context and a return visit; source/cost/failure
evidence; and the unresolved decisions. A static mock, fixture-only pass or
generated architecture document is not completion of that product outcome.

### Non-claims

Do not claim exhaustive literature coverage, independently verified publisher
performance, scientific novelty, human learning gains, reproduction success,
hardware feasibility or reliable delivery while the local machine is off.
Report what was actually observed and expose the rest as unknown or proposed.
