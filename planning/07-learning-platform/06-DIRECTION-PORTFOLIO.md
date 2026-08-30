# 06 — Direction portfolio: the platform beyond education

Status: **PROPOSED structure, ADOPTED intent** (owner ruling LP-D2,
2026-08-30 — see [`STATUS.md`](STATUS.md)). The owner has ruled that all
nine directions below are long-term intents of the platform: "those
options for directions are great lets add all of them to docs because I
want to build all of them into the platform." This document records
them faithfully and structures them so they compound instead of
competing: **one shared core, one direction built at a time, each
behind an evidence gate.**

## 1. The shared core

Every direction below consumes the same organ set, most of which exists
or is being planned in [`05-WEDGE-WORK-ORDERS.md`](05-WEDGE-WORK-ORDERS.md):

| Organ | State |
|---|---|
| Literature pipeline (search → read → synthesize → critique, cited) | Shipped (`src/agents/`, `src/graph/`) |
| Job API, SSE, HITL review | Shipped (`src/api/`) |
| Per-principal scoping; MT-01 identity seams | Shipped / dormant |
| Evidence Workbench design system + surfaces | Shipped (`web/`) |
| Guided session engine + user model + progress events | Phase W (planned) |
| Learning-agent eval harness | Phase W (planned) |
| Scheduler / recurring runs | Phase L2 of [`03`](03-ARCHITECTURE-ROADMAP.md); pulled earlier if D1 leads |
| Content/resource graph | [`02-CONTENT.md`](02-CONTENT.md) |

Phase W is therefore **direction-agnostic infrastructure**: it advances
all nine directions regardless of which ships second.

## 2. The nine directions

Each entry: what it is → who uses it daily → what it reuses → the delta
→ earliest sensible phase → the evidence gate that green-lights it.

### D1 — Research radar (standing monitors)
Watch a subfield, get agent-briefed diffs weekly. **Users:** grad
students, ML engineers, researchers. **Reuses:** the whole pipeline +
conversations. **Delta:** scheduler + monitor configs + digest surface
(S/M). **Earliest:** immediately after Phase W (smallest delta of all
nine). **Gate:** ≥N pilot monitors re-opened in week 2 (threshold set at
proposal time).

### D2 — Literature-review workbench
Structured reviews: evidence tables, contradiction surfacing,
related-work drafts, BibTeX/LaTeX export. **Users:** academics near
deadlines (real willingness to pay). **Reuses:** reader/synthesizer/
critic, export pipeline, ReportReader. **Delta:** review templates,
table extraction, citation export (M). **Gate:** pilot users complete a
real related-work section with it.

### D3 — Lab/team workspace
Shared threads, reading groups, collaborative briefings. **Users:**
labs, ML teams. **Reuses:** conversations, MT-01. **Delta:** orgs/
sharing model on top of MT-01, presence/comments (L) + a B2B motion.
**Earliest:** after MT-01 (Phase L0). **Gate:** one real lab asks for it
unprompted.

### D4 — R&D / investor intelligence briefings
Living "state of X" reports for VCs, corporate R&D, policy analysts —
few customers, real money. **Reuses:** pipeline + radar (D1) + report
surfaces. **Delta:** voice/packaging per audience, tracked-topic
curation (M). **Gate:** one paying design partner.

### D5 — Paper-reading companion
Guided annotation and "explain this at my level" for any paper — the
Phase W engine with the pedagogy framing removed. **Reuses:** Phase W
wholesale. **Delta:** arbitrary-paper entry point, reader-mode UI (S/M);
browser-extension variant later (M). **Earliest:** concurrent with W2
pilots — the same sessions, second framing. **Gate:** W2 pilots observed
using sessions as "help me read" (the built-in experiment).

### D6 — Personal research memory
"Everything I've read": answers grounded in the user's own accumulated
library. **Reuses:** paper cache, embeddings/retriever, prior-context.
**Delta:** per-user library model, import surfaces, retrieval scoping
(M). **Earliest:** after MT-01. **Gate:** retention among W2/D5 users
who accumulate ≥20 read papers.

### D7 — Papers-with-Code successor (claims/code/benchmark tracking)
Papers → claims → code links → benchmark deltas. PwC shut down
2025-07-25 ([`00-VISION.md`](00-VISION.md) scan) — a vacant,
high-traffic niche. **Reuses:** reader/extraction, evidence claims,
S2 enrichment. **Delta:** claim/benchmark schema, code-link resolution,
public browse surfaces, curation queue (L, plus an ongoing curation
treadmill). **Gate:** extraction precision proven on a 100-paper sample
before any public surface.

### D8 — Newsletter / media hybrid
Agent-drafted, human-edited weekly subfield digests. **Strategic role:**
this is the **distribution asset** — the #2 untested assumption in
[`04`](04-STRATEGY-ALTERNATIVES.md) is that nothing here has an
acquisition channel; D8 builds the channel that feeds every other
direction. **Reuses:** D1's digests verbatim. **Delta:** publication
pipeline + editorial hour/week (S). **Earliest:** as soon as D1's
digests exist — arguably the second build. **Gate:** open/subscribe
rates over 8 issues.

### D9 — API / agent-platform play
The pipeline as a service others embed. **Reuses:** the API surface
as-is + keys/rate limiting. **Delta:** docs, quotas, billing (M).
**Ranked weakest-moat in [`04`](04-STRATEGY-ALTERNATIVES.md)**; parked
until an external party actually asks. **Gate:** inbound demand.

## 3. Sequencing principles (how "all of them" stays buildable)

1. **One direction in build at a time**, behind the evidence gate of the
   previous — the revamp's gate discipline, applied to product bets.
2. **Phase W first, always** — it is load-bearing for education, D1, D2,
   D5, and D6.
3. **Distribution early**: D1 → D8 is the cheapest path to an audience,
   and every later direction inherits it.
4. **MT-01 unlocks the multi-user tier** (D3, D6, education's L-phases);
   it is scheduled once, not per-direction.
5. **Paid-spend items** (eval runs, pilot inference, D4 partners, D8
   sending infra) each wait on an explicit owner approval, per the
   standing cost boundary.
6. Each direction gets its own deep-dive planning doc (07+, Fable
   planners) before its build fleet (Opus) launches — this portfolio
   entry is its charter, not its plan.

## 4. What LP-D2 does NOT decide

Order beyond "Phase W first" (proposed default: W → D1 → D8 → then
evidence decides among education-L1 / D2 / D5-deepening); pricing; any
paid spend; MT-01 answers. Those remain owner decisions at their gates.
