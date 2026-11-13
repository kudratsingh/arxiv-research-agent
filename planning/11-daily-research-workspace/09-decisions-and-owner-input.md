# Decisions and owner input

## Decided in this conversation

| Decision | Owner direction |
|---|---|
| Main purpose | An everyday research tool for an ML student/researcher learning frontier systems, connecting ideas and building them |
| First workflow | Daily briefing plus guided deep dives |
| Fields | Broad selectable interests and fields of study, with detailed ML choices |
| Operation | Local first |
| Paid services | Approve separately; possessing a credential does not enable spending |
| Deliverable now | A researched direction kit for an implementation agent working with owner input |

The old Phase-W-first sequencing is revised by this direction. Reuse working
guided-reading components, but do not require course publication or educational
pilots before a personal daily radar. Broader product intent remains available.
Existing rights and paid-operation boundaries remain unchanged.

## Proposed defaults the agent can implement reversibly

- Private personal workspace using the existing stack and local Compose.
- Metadata-first intake, a finite briefing, no model calls by default.
- Start with arXiv and a few owner-approved primary RSS sources; manual
  URL/identifier save works across the topic catalogue.
- One local daily check, with catch-up and source freshness; no promise of
  notifications while the computer is off.
- A rich editable ML preset; a small adjacent-discovery allocation.
- Existing fonts, theme tokens, accessibility and route-quality conventions.
- Source-linked reading and notes before a complex knowledge graph.
- Downloadable Markdown and citation export before two-way Zotero sync.

These defaults should be shown in the first preview. They do not require a
new round of generic permission questions to build locally.

## Inputs that materially change implementation

Ask the owner in short groups at the stage that needs the answer. Provide a
working preview or concrete cost table first; keep unrelated work moving.

| Input | Needed for | Reversible fallback until answered |
|---|---|---|
| Main ML subfields, a current project/question, 3 seed papers and exclusions | Initial relevance tuning | Editable suggested ML lens and explicitly synthetic fixtures |
| Local briefing time, timezone and reading duration | Activating the local schedule | Manual refresh; app timezone defaults from browser but requires confirmation before scheduled delivery |
| Hardware and available experiment time | Personalized build briefs | Requirements marked unknown; no feasibility claim |
| Preferred deep-dive format and math/code depth | Reader tuning | Adjustable per-session depth, save explicit preference only |
| Private notes sensitivity, retention/export preference | Provider context and retention | Local notes, no background external sharing; explicit content scope per generated job |
| Daily/monthly inference cap, permitted models, permitted context | Enabling generated summaries or guided responses | Generation disabled; metadata and manual reader work |
| Desired alert channel | Any outbound email/push/desktop integration | In-app inbox only; setting preferences does not send a notification |
| Need for off-machine availability or another device | Hosted private deployment/sync | Local catch-up semantics, no hosted dependency |
| Existing Zotero/Obsidian library | Optional import/export workflow | Standard files/manual IDs; no writeback to another app |

Do not turn these into a mandatory giant onboarding questionnaire. Topics alone
should produce a first briefing. A project, seed papers and exclusions improve
tuning progressively and are optional at the first owner review. Review the
realistic Today/Reader flow before requesting extensive profile information.

## Later decisions

Additional scholarly connectors, broad web extraction, a graph view, GitHub/HF
event subscriptions, hosted operation, account identity, collaboration, code
execution, paid search and trained recommendation policies get their own
bounded proposals. A broad topic list is not authorization to enable them all.

For each consequential decision record: alternatives, recommendation, measured
or estimated cost, effect on the daily workflow, allowed data/source scope,
acceptance and rollback. Update the implementation ADR and the kit's decision
log when the owner answers; preserve older evidence reports.

## Implementation conversation, 2026-11-02

The owner supplied the initial editable lens:

- Core briefing: agentic systems/research automation; retrieval/RAG/knowledge
  organization; evaluation/verification/efficient inference.
- Dedicated Rocket Twin watch: scientific ML, digital twins, RL/model-based
  control, system identification, uncertainty and sim-to-real validation.
- Lighter exploration: spatial AI and AI-assisted 3D/game creation, with an
  Unreal production connection. This is an exploratory research link.

Current question: “How can I build a personalized research agent that identifies
useful developments, explains them against real sources, and turns them into
small, reproducible experiments within a controlled compute budget?”

These choices populate the editable preview. They do not activate a source,
schedule, generation budget or experiment. Check time and hardware remain
unknown until the corresponding feature needs them.
