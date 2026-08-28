# Preliminary frontend directions

Prepared: 2026-08-28  
Status: Gate 1 concepts; no implementation or final system architecture  
Recommendation: **A — Evidence Workbench**

## Shared product truth

All three directions preserve the same workflow and backend boundary:

```text
New question
    |
    v
Plan review -------- cancel
    |
    v
Live run / reconnect
    |
    v
Markdown report + aggregate metrics + MD/PDF/DOCX export
```

They do not invent structured papers, evidence claims, accounts, search, rename, post-approval cancellation, or a determinate percentage. Those concepts are absent from the frozen API.

The designs share these non-negotiables:

- Responsive shell: collapsible desktop rail, labelled mobile drawer/control, one `<main>`.
- Question-first entry and a dedicated plan-review boundary.
- Durable active-job URL and clear leave/return/reconnect treatment.
- Document-first report reader rather than chat bubbles or a dashboard card grid.
- Semantic status plus text/icon/shape—not color alone.
- Keyboard-visible controls, skip link, reduced motion, restrained live regions.
- Dark theme derived from semantic tokens, not a separate improvised palette.
- One signature interaction per direction; quiet supporting surfaces.

## Direction A — Evidence Workbench (recommended)

### Thesis

A modern scientific workbench: clear mineral surfaces, blueprint structure, and a single oxidized-copper research trace. It should feel like a serious instrument used to produce a defensible briefing—not like a chat app, a paper-themed magazine, or a generic SaaS dashboard.

### Mood and vocabulary

- Precise, calm, investigative, trustworthy.
- Moderate density: compact navigation/status, generous report line-height.
- Rectilinear structure with restrained 3–6 px radii; no blanket rounded cards.
- Fine rules appear only where they explain trace, grouping, or table structure.
- Small utility labels use sentence case or quiet technical labels, never ornamental all-caps everywhere.

### Token seed

| Role | Name | Hex | Use |
|---|---|---:|---|
| Canvas | Mineral White | `#F3F7F8` | App background and report surround |
| Ink | Carbon Ink | `#172B31` | Primary text and strong rules |
| Primary | Blueprint | `#275DAD` | Primary actions, focus, links |
| Signature | Oxidized Copper | `#167D7F` | Research trace and latest observed checkpoint |
| Review | Review Amber | `#C47A17` | Plan approval and non-error attention |
| Critical | Signal Red | `#B33A3A` | Destructive/error only |

Dark mode would remap semantic roles rather than invert hexes; the bright copper/blue chroma should remain limited to trace, focus, and action.

### Typography

| Role | Candidate | Treatment |
|---|---|---|
| Report/display | Literata | Restrained report title, executive-summary headings, long-form hierarchy |
| UI/body | Atkinson Hyperlegible Next or Source Sans 3 | Dense readable controls, navigation, forms, messages |
| Utility/data | IBM Plex Mono | Job ID disclosure, timestamps, metrics, event diagnostics only |

The final licensed/font-loading choice belongs in the Phase 2 brief. The system-font fallback must preserve metrics and prevent layout shift.

### Signature interaction — research trace spine

A thin vertical or horizontal spine connects the real phases the application knows. It is not a stepper claiming equal completion and never displays invented percentages.

```text
QUESTION      PLAN REVIEW       RUN                              REPORT
captured  o------o approved  o--● last completed: Search ----------o ready
                                  status: Running · updated 8s
                                  current internal stage unknown
                                  [show technical events]
```

- Active job: question, editable/approved plan, job-level status, elapsed/last update, and the latest `node_completed` checkpoint actually observed in this browser session.
- Reload/reconnect: the run segment becomes outlined with “Reconnecting; current checkpoint unknown.” A reconnect has no intermediate backlog, so the UI never reconstructs stages it did not receive.
- Historical success: the trace gracefully compresses to question → completed report and final metrics because terminal replay does not include the prior checkpoint history or a durable plan record.
- Failure: copy says “failed after [last observed completed checkpoint]” or simply “failed” when none was observed; the API does not reveal the failing node. Any permitted partial report remains available.

### Landing shell

```text
┌───────────────┬────────────────────────────────────────────────────┐
│ arxiv / mark  │  RESEARCH WORKBENCH                   health/help │
│ + New research│                                                    │
│               │  What should we investigate?                       │
│ Recent        │  ┌──────────────────────────────────────────────┐  │
│ ● RAG evals   │  │ Ask a focused ML or AI research question…    │  │
│ ○ agents      │  └──────────────────────────────────────────────┘  │
│ ○ embeddings  │  8,000 chars · generating a plan may use the API  │
│               │  Review before search and downstream research     │
│               │                                   [Generate plan] │
│               │                                                    │
│               │  HOW IT WORKS                                      │
│               │  Question ─ Plan approval ─ Research ─ Briefing    │
└───────────────┴────────────────────────────────────────────────────┘
mobile: labelled menu above one-column composer; no persistent rail
```

### Conversation/report shell

```text
┌───────────────┬────────────────────────────────────────────────────┐
│ + New research│ RAG evaluation methods                   [Export] │
│               │ Question ─ Plan ─ ● Run ─ Report                    │
│ Conversations │           Running · last completed: reader · 12:41│
│ ● RAG evals   │           [Plan] [Technical events]                 │
│ ○ agents      ├───────────┬────────────────────────────────────────┤
│ ○ embeddings  │ Sections  │ Executive summary                      │
│               │ Summary   │                                        │
│               │ Methods   │ Markdown report body with calm measure │
│               │ Findings  │ and visible link/focus treatment.      │
│               │ Limits    │                                        │
│               │           │ ─────────────────────────────────────  │
│               │           │ Quality 0.86 · $0.42 · 11 calls        │
│               │           │ [Ask a follow-up…]            [Send]   │
└───────────────┴───────────┴────────────────────────────────────────┘
mobile: trace -> report -> metrics -> follow-up; section nav is disclosure
```

### Motion

- 120–180 ms state/focus transitions only.
- Active trace may use a low-frequency opacity shift while receiving events; disabled under reduced motion.
- No streaming typewriter, orbiting particles, skeleton shimmer, or continuous decorative motion.

### Why this is recommended

- The signature is grounded in existing question/plan/event/report contracts.
- It makes plan review and interruption recovery visible without turning raw events into the primary UI.
- It supports dense operational status and a calm reading surface in the same composition.
- It leaves a natural future insertion point for structured evidence without pretending that contract exists now.

### Anti-template critique

Avoid the familiar “AI research” formula: black/navy canvas, neon cyan/purple glow, pulsing brain icon, chat bubbles, and a grid of metric cards. Also avoid the 2020s editorial fallback of warm cream, decorative serif, terracotta buttons, and paper texture. Neither expresses this product's actual differentiator: a user-approved, inspectable research process.

## Direction B — Annotation Desk

### Thesis

A report-review desk inspired by blue-pencil annotation and academic copy editing. The report is the dominant object; navigation, plan, stage, and metrics behave like margin apparatus around it. This is warmer and more document-centric than Evidence Workbench, but still digital and precise.

### Mood and vocabulary

- Reflective, editorial, focused, humane.
- Lower UI density around a generous report; compact section and history rails.
- Squared paper planes, visible baseline rhythm, occasional bracket/underline marks.
- The report is one continuous surface, not a stack of cards.

### Token seed

| Role | Name | Hex | Use |
|---|---|---:|---|
| Canvas | Archive Mist | `#EEF1F0` | Workspace surround |
| Paper | Clean Sheet | `#FCFCF8` | Report surface |
| Ink | Editorial Ink | `#20282B` | Text |
| Primary | Blue Pencil | `#315C9B` | Links, actions, section marker |
| Signature | Viridian Mark | `#287568` | Active annotation/status mark |
| Critical | Proof Red | `#A63D40` | Error/destructive only |

### Typography

| Role | Candidate | Treatment |
|---|---|---|
| Report/display | Source Serif 4 | Long-form report and restrained titles |
| UI/body | IBM Plex Sans | Controls, navigation, messages |
| Utility/data | IBM Plex Mono | Footnote-like timestamps, job details, metrics |

### Signature interaction — section annotation rail

The report's parsed Markdown headings create a truthful section rail. Active run notes, metrics, and export status attach to the report as margin marks, but they never claim sentence-level citation support.

```text
SECTIONS          REPORT                                  MARGIN
● Summary         # Executive summary                     run ready
│ Methods         …                                       quality .86
│ Findings        ## Findings                             cost $0.42
│ Limitations     …                                       [export]
└ Sources         ## References
```

This is feasible because Markdown headings and aggregate metrics already exist. “Evidence annotations” must not appear until the API exposes structured evidence.

### Landing shell

```text
┌──────────────┬─────────────────────────────────────────────────────┐
│ Research     │  Begin a research brief                            │
│ + New brief  │  ────────────────────────────────────────────────   │
│              │  What decision or question should the literature   │
│ Briefs       │  help you resolve?                                 │
│ RAG evals    │  ┌───────────────────────────────────────────────┐  │
│ Agents       │  │                                               │  │
│ Embeddings   │  └───────────────────────────────────────────────┘  │
│              │  Plan generation may be billable. Review before    │
│              │  literature search and downstream research.        │
│              │                                  [Generate plan]  │
└──────────────┴─────────────────────────────────────────────────────┘
```

### Conversation/report shell

```text
┌──────────────┬────────────┬─────────────────────────────┬─────────┐
│ Briefs       │ Sections   │ RAG evaluation methods      │ Margin  │
│ ● RAG evals  │ ● Summary  │                             │ Ready   │
│ ○ Agents     │   Methods  │ Executive summary           │ .86     │
│ ○ Embeddings │   Findings │ ──────────────────────────  │ $0.42   │
│              │   Limits   │ Long-form report…           │ Export  │
│              │            │                             │         │
│              │            │ [Follow-up question…]       │         │
└──────────────┴────────────┴─────────────────────────────┴─────────┘
mobile: report first; sections/status become top disclosures
```

### Motion

- Almost none: section-marker slide/fade, disclosure transitions, and progress/status replacement.
- Heading navigation uses instant or reduced-distance scroll when reduced motion is requested.

### Strength and risk

The report hierarchy would be excellent and the heading rail is fully feasible. The risk is over-indexing on “paper” styling and under-emphasizing the active workflow/HITL control. It could also drift into the generic cream-serif editorial trend. The cool archive palette and explicit operational margin are intended to prevent that.

### Anti-template critique

Do not use faux paper grain, torn edges, handwritten fonts, quotation-mark decoration, or endless beige cards. The direction is about editorial hierarchy and annotation behavior, not simulating stationery.

## Direction C — Field Instrument

### Thesis

A compact scientific instrument panel for research engineers: the pipeline is a measured signal path and the report is the recorded result. This direction is the densest and most operational, emphasizing stage visibility, failures, and cost without making raw logs the main experience.

### Mood and vocabulary

- Technical, high-confidence, efficient, controlled.
- High navigation/status density; medium report density.
- Graph-paper rhythm used sparingly in the trace header only.
- Square controls and segmented status, with soft report typography below.

### Token seed

| Role | Name | Hex | Use |
|---|---|---:|---|
| Canvas | Calibration Gray | `#E9EFF1` | App background |
| Surface | Instrument White | `#F9FBFA` | Working panes |
| Ink | Graphite | `#14262B` | Text and structure |
| Primary | Cobalt | `#1F5F99` | Controls and links |
| Signature | Signal Teal | `#008A83` | Latest checkpoint/ruler |
| Warning | Instrument Orange | `#C56622` | Review/attention |

Errors derive a separate semantic red in the full system; the six-token concept seed keeps warning and primary roles distinct.

### Typography

| Role | Candidate | Treatment |
|---|---|---|
| Display/UI | DIN-like licensed family or Archivo | Compact headings and controls; avoid faux-industrial styling |
| Report/body | Source Sans 3 | Long-form readability |
| Utility/data | Geist Mono or IBM Plex Mono | Stage, elapsed time, cost, and diagnostics |

### Signature interaction — checkpoint ruler

The checkpoint ruler maps only observed `node_completed` events onto a stable measurement-like strip. Completed checkpoints are ticks; job status sits beside the ruler; the current internal stage is explicitly unknown. Unknown events remain in diagnostics.

```text
PLAN ✓      SEARCH ✓     READ ?       SYNTHESIZE ?     CRITIQUE ?
|-----------|------------|------------|-----------------|
status: Running · last completed: Search · last event 8s
2 checkpoint events observed in this session · [diagnostics]
```

It is deliberately not a percentage or a current-stage claim. If a future event supplies “8 of 20 papers,” the count can appear under the related completed event without implying overall completion.

### Landing shell

```text
┌───────────────┬────────────────────────────────────────────────────┐
│ ARXIV RA      │ NEW RESEARCH                                      │
│ [+ NEW]       │ ┌──────────────────────────────────────────────┐   │
│               │ │ Research question                            │   │
│ RUNS          │ └──────────────────────────────────────────────┘   │
│ ● RAG evals   │ LIMIT 8000 · PLAN REVIEW ON · SERVER READY         │
│ ○ Agents      │ PLAN GENERATION MAY BE BILLABLE                    │
│ ○ Embeddings  │ REVIEW BEFORE SEARCH              [GENERATE PLAN] │
│               │ PROCESS                                            │
│               │ Question | Approve | Run | Review                  │
└───────────────┴────────────────────────────────────────────────────┘
```

### Conversation/report shell

```text
┌───────────────┬────────────────────────────────────────────────────┐
│ RUNS          │ RAG EVALUATION METHODS                EXPORT [v]  │
│ ● RAG evals   │ PLAN ✓ | SEARCH ✓ | READ ? | SYNTH ? | CRIT ?     │
│ ○ Agents      │ RUNNING · LAST DONE SEARCH · UPDATED 8S            │
│ ○ Embeddings  ├─────────────┬──────────────────────────────────────┤
│               │ RUN         │ Executive summary                    │
│               │ Quality .86 │ Long-form report…                    │
│               │ Cost $0.42  │                                      │
│               │ Calls 11    │                                      │
│               │ [Details]   │ [Follow-up…]                  [Send] │
└───────────────┴─────────────┴──────────────────────────────────────┘
mobile: compact checkpoint scroller with text summary; metrics below report
```

### Motion

- Ruler updates are discrete, not continuously animated.
- Reconnect uses a static interrupted-line treatment plus text.
- Reduced-motion mode removes all transform transitions.

### Strength and risk

This best serves research engineers who care about operational transparency. Its risk is making the product feel like internal observability software and crowding out the briefing. The report must remain the visual center after completion, and the graphite/teal palette must not become the generic near-black dashboard with one acid accent.

### Anti-template critique

Avoid terminal cosplay, scanlines, tiny all-caps labels on every surface, neon-on-black, animated waveforms, and detached telemetry cards. The instrument metaphor should clarify observed checkpoints and measurements, not decorate the page or guess at hidden work.

## Comparison

| Criterion | A — Evidence Workbench | B — Annotation Desk | C — Field Instrument |
|---|---:|---:|---:|
| Fits existing API | **High** | High | High |
| Plan/HITL visibility | **High** | Medium | High |
| Long-form reading | High | **Highest** | Medium-high |
| Operational transparency | High | Medium | **Highest** |
| Broad user fit | **Highest** | Medium-high | Medium |
| Mobile adaptability | **High** | High | Medium-high |
| Risk of category cliché | Low-medium | Medium-high | High |
| Natural future evidence expansion | **High** | High | Medium |

## Recommendation and Gate 1 decision

Choose **A — Evidence Workbench** as the Phase 2 foundation.

Its research trace is truthful under today's contracts, carries the plan-review differentiator, and balances operational state with report reading. Borrow Annotation Desk's section rail for long reports and Field Instrument's compact diagnostic disclosure, but do not blend their visual metaphors. The chosen system should still read unmistakably as Evidence Workbench.

Gate 1 asks the user to:

1. Choose A, B, C, or request a specific hybrid.
2. Confirm the product is intentionally a private shared-principal/single-owner workspace for this deployment.
3. Confirm unsupported backend concepts should be omitted and separately proposed rather than simulated.
4. Approve the first vertical slice: new question → reload-safe job → plan review → stream/reconnect → report/metrics/export.

After those decisions, Phase 2 can produce the detailed design brief, full state matrix, responsive layouts, typography/iconography rules, content standards, motion policy, accessibility plan, and measurable acceptance criteria. No product implementation should begin before that gate is approved.
