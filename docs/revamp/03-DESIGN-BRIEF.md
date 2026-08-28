# Evidence Workbench — Phase 2 design brief

Prepared: 2026-08-28
Branch: `docs/frontend-revamp-phase2-brief`
Baseline commit: `e6e87396d32be5ae985c2d7cc0dd5ed6cf84b351`
Direction: **A — Evidence Workbench**, chosen by the user at Gate 1 ([`DECISIONS.md` D-009](DECISIONS.md#d-009--gate-1-human-decisions))
Status: **Gate 2 candidate.** No implementation. No backend change. No paid call.

Inputs this brief is built from: [`00-DISCOVERY.md`](00-DISCOVERY.md),
[`01-RESEARCH.md`](01-RESEARCH.md), [`02-DIRECTIONS.md`](02-DIRECTIONS.md),
[`REVIEW.md`](REVIEW.md), [`RISKS.md`](RISKS.md),
[`baseline/README.md`](baseline/README.md), the 27 committed baseline
screenshots and 12 axe reports, and a direct read of `web/` and the
frozen FastAPI surface in `src/api/`.

Companion file: [`design/tokens.json`](design/tokens.json) — the same tokens,
machine-readable, with every contrast ratio recorded next to the pair it
was measured on.

---

## 0. One new finding this brief is built around

While mapping the plan-review surface, Phase 2 read the runner and found a
contract fact that Gate 1 did not record and that changes the design:

> **The approved plan is erased from the job record the moment review
> resolves.** `src/api/runner.py:454` sets `job.plan = None` as the job
> returns to `running`. `JobDetail.plan` is therefore non-null **only**
> while `status == "pending_review"` (`src/api/routes.py:95-119`), and
> `ConversationJobSummary` never carried a plan at all
> (`web/lib/types.ts:72-78`).

So the frozen API cannot tell you, after the fact, which plan produced a
briefing. The browser that ran the review knows; nothing else does.

This is the same epistemic shape as the checkpoint constraint the Gate 1
reviewer imposed on the trace (see [§5](#5-signature-interaction--the-research-trace-spine)),
and it is now the thesis of the whole design rather than a caveat inside
one component:

> **The Evidence Workbench reports what it witnessed, states plainly what
> it did not witness, and never interpolates between the two.**

Everything specific about this product — the plan you edited, the
checkpoints that happened to arrive on this connection, the run that
failed without naming a stage — is a fact about observation. That is the
material the design is made from. Recommended for the coordinator to add
to [`RISKS.md`](RISKS.md) as a new row; this brief does not edit that file.

---

## 1. Product narrative and experience principles

### 1.1 The real contract

Every screen in this brief serves one loop, and the loop is not a chat:

```text
  question              POST /research                      202 + job_id
     |                  non-idempotent, starts a billable planner run
     v
  plan generated        SSE plan_ready · status pending_review
     |                  JobDetail.plan is readable ONLY here
     v
  human review          POST /research/{id}/review  approve | revise | cancel
     |                  the last moment cancellation exists
     v
  long-running job      SSE node_completed (after each node, never before)
     |                  no backlog, no event ids, no current-stage claim
     v
  terminal frame        job_completed | job_failed | job_cancelled
     |                  carries metrics, never the report body
     v
  GET /research/{id}    the briefing, cost, quality, calls, elapsed
     |
     v
  GET .../export        md | pdf | docx — allowed whenever result is non-empty
```

Two properties of this loop dominate the design:

1. **The expensive, irreversible action happens first.** Pressing the
   landing button spends money before the user has seen anything. The
   review is a *brake applied after the engine starts*, not a gate before
   it. Landing copy must say exactly that ([§1.4](#14-landing-copy)).
2. **Everything after submission is recovered, not remembered.** SSE has
   no replay backlog and no `Last-Event-ID`
   (`src/api/streaming.py:14-46`); a terminal replay frame carries
   `status`, `elapsed_sec`, `error`, `error_type`, `iterations`,
   `quality_score`, `cost_usd` — and no `node` and no `result`
   (`src/api/routes.py:857-867`). The report always comes from a fresh
   `GET`.

### 1.2 Narrative — three moments

**Ask.** A researcher opens the workbench with a question they intend to
defend to someone else. The landing screen has one job: get a
well-formed question, and be honest that pressing the button starts
spending. Nothing else competes with the field.

**Approve.** Ninety seconds later the workflow stops and hands back its
own plan: sub-questions in English, arXiv search queries as literal
strings. This is the product's differentiator and the only point where
the user's judgement changes what gets read. The plan editor is not a
settings panel tucked into a sidebar — it is a full-width work surface
that takes over the main column, because the run is paused and there is
nothing more important on screen.

**Read.** The briefing arrives as a document, and it is treated as a
document: a serif reading column, a section rail derived from its real
Markdown headings, its cost and quality attached beneath it rather than
floating in a dashboard, and export one control away. Beside it, the
trace spine records what this browser actually saw happen — including
the parts it did not see.

### 1.3 Experience principles

| # | Principle | What it forbids |
|---|---|---|
| P1 | **Say what was observed; mark what was not.** Every status the UI shows must trace to a job status field or an SSE frame this browser received. | Inferred "current stage", progress percentages, ETAs, a spinner that implies knowledge. |
| P2 | **Spend is disclosed before the click that causes it.** | Burying billability in a tooltip, a help page, or post-submission copy. |
| P3 | **The plan is the product's control surface.** It gets the main column, native inputs, and one unambiguous approve action. | Cramming plan review into a log panel; two half-disabled approve buttons ([baseline](baseline/screenshots/plan-review-desktop.png)). |
| P4 | **The briefing is a document, not a card.** | Chat bubbles, metric-card grids above the report, truncating the report into a preview. |
| P5 | **Failure keeps the work.** A failed job with a retained `result` still has a readable, exportable briefing. | `ReportView`'s early return, which currently hides a non-empty partial report behind the failure panel (`web/components/ReportView.tsx:13-27`). |
| P6 | **One surface can be dense; the other must be calm.** Chrome, trace and diagnostics may be tight; the report column may not. | Applying the same density everywhere and calling it a design system. |
| P7 | **Nothing is simulated.** Concepts the API does not expose are absent, with a named reason, not mocked. | Paper lists, citation graphs, claim ledgers, rename, search, post-approval cancel, fake accounts. |

### 1.4 Landing copy

Verbatim, including the Gate-1 disclosure carried from
[`REVIEW.md`](REVIEW.md) first-pass finding 4. The disclosure is
persistent body copy directly above the button — not a tooltip, not a
footnote, not revealed on hover.

```text
[eyebrow]     Evidence Workbench
[h1]          What should the literature settle?

[label]       Research question
[textarea]    e.g. How do current systems evaluate faithfulness in
              retrieval-augmented generation?
[counter]     0 / 8,000

[disclosure]  Generating a plan starts a billable run. You review and
              edit the plan before any arXiv search or paper reading
              happens.

[button]      Generate plan

[process]     Question  ·  Plan you approve  ·  arXiv run  ·  Briefing
```

Notes on each string:

- "Generate plan", not "Run research": the button's true immediate effect
  is a planner run that pauses. The action keeps this name through the
  flow — the pending state reads *Generating plan…*, and the surface it
  produces is titled *Plan*.
- The 8,000 limit is the real `MAX_QUERY_LEN` bound on `ResearchRequest`
  (`src/api/schemas.py:36-40`). The counter is visible from zero
  characters, not only on overflow.
- The process strip lists four things that genuinely exist. It is a
  legend for the trace spine the user is about to meet, not decoration.
- No claim about *how long* review may take. The review deadline is
  `settings.api_hitl_timeout_sec` (`src/config.py:354`), which the HTTP
  API does not expose, so the UI must not name a number. See
  [§10](#10-what-gate-2-must-decide).

### 1.5 Product lexicon

One word per concept, everywhere, including error copy and export
filenames. Named after what the user controls, per the design skill's
writing guidance.

| Concept | We say | We never say |
|---|---|---|
| `Conversation` | **Thread** | Conversation, chat, session, project |
| `Job` | **Run** | Task, request, execution |
| `JobDetail.result` | **Briefing** | Answer, response, output, result |
| `Plan.sub_questions` | **Sub-questions** | Steps, tasks |
| `Plan.search_queries` | **arXiv queries** | Keywords, terms |
| `node_completed` | **Checkpoint** | Stage, step, phase, node |
| Job status | **Status** | Progress, state |
| `cost_usd` | **Cost** | Spend, usage, credits |
| `quality_score` | **Quality score** | Confidence, accuracy, score |
| The signed-in nobody | **This workspace** | Your account, my library |

---

## 2. Information architecture

### 2.1 Routes

Nothing is invented beyond the frozen HTTP API. Two user-facing
templates stay; two framework fallbacks become real product surfaces.

| Route | Change | Rendering |
|---|---|---|
| `/` | Restyled and restructured; keeps static prerender | Server shell + client composer |
| `/c/[id]` | Restructured; `?job=` contract preserved byte-for-byte | Dynamic; client thread inside a server shell |
| `/api/[...path]` | **Unchanged.** The server-only key boundary is not touched by this brief (D-002, R-08) | Force-dynamic Node route |
| `app/not-found.tsx` | **New.** Replaces the framework 404 ([baseline](baseline/screenshots/framework-not-found-desktop.png)) | Static, inside the workbench shell |
| `app/global-error.tsx` | **New.** Replaces the framework error boundary | Client |
| `app/c/[id]/error.tsx` | **New.** Route-level recovery so a thread crash does not blank the shell | Client |
| `/login`, `/settings` | **Reserved names, not created.** See [§6](#6-identity-ready-shell) | — |

The `?job=` contract is a MUST-KEEP (`00-DISCOVERY.md` §MUST-KEEP 1) and
the mitigation for R-02. Rules the new shell inherits unchanged:

- The landing submit still does `POST /conversations` → `POST /research`
  → `router.push('/c/{id}?job={job_id}')` (`web/app/page.tsx:33-40`).
- The thread still writes `?job=` at most once per job id
  (`web/components/ConversationThread.tsx:132-142`).
- **New:** a thread row in the rail that points at the thread you are
  currently running loses `?job=`. Today that silently detaches a paid
  run. The new rail keeps the active run's `?job=` on its own row and
  marks that row *Live*, so navigation cannot orphan it.

### 2.2 State matrix

Every reachable state from the discovery matrix and the baseline capture
set, mapped to a designed surface. "Evidence" links the committed
baseline artefact this state was designed against.

| # | State | Evidence | Designed surface |
|---|---|---|---|
| 1 | **Landing** | [desktop](baseline/screenshots/home-desktop-full.png) · [phone](baseline/screenshots/home-mobile-full.png) | Single-column composer centred in `<main>`; process strip; billability disclosure; rail collapsed to a drawer below 768px. In the baseline capture the `h1` does not start until roughly 440px down a 1200px-tall viewport; the new prompt is the first thing on screen. |
| 2 | **Sidebar loading** | [desktop](baseline/screenshots/sidebar-loading-desktop.png) | Three skeleton rows at real row height inside the rail. Rail chrome (New research, "Threads") renders immediately so nothing shifts. `aria-busy` on the list; no spinner. |
| 3 | **Sidebar empty** | — (reachable; `items.length === 0`, `ConversationSidebar.tsx:109`) | "No threads yet. Your first question starts one." Distinct from state 2 and from state 12. |
| 4 | **Sidebar / backend error** | [desktop](baseline/screenshots/backend-offline-desktop.png) | The baseline puts a 12px red string in the rail's bottom corner while the composer stays enabled and inviting. New: an inline `role="alert"` at the top of the rail, **plus** the composer's submit is disabled with the reason attached to it ("The research service is not reachable"), plus a **Retry** that re-runs `GET /conversations` only. Never auto-retries a mutation. |
| 5 | **Empty thread** | [desktop](baseline/screenshots/conversation-empty-desktop.png) · [phone](baseline/screenshots/conversation-empty-mobile-full.png) | Thread header with real turn count; empty-state body that names what a turn is; composer at rest. |
| 6 | **Thread loading** | [desktop](baseline/screenshots/conversation-loading-desktop.png) | Header + report skeleton at reserved height. CLS budget 0.00. |
| 7 | **Populated briefing** | [desktop](baseline/screenshots/conversation-populated-desktop-full.png) · [phone](baseline/screenshots/conversation-populated-mobile-full.png) | Reading column (Literata, 68ch) with a section rail derived from the report's own `h2`/`h3` nodes; metrics strip beneath the report; export beside the title. Turns collapse to a question row; newest expanded. |
| 8 | **Dark mode** | [desktop](baseline/screenshots/conversation-populated-dark-desktop.png) | Same layout on the dark token set, plus the two things the baseline lacks: `color-scheme: light dark` on `:root` (so form controls, scrollbars and the caret follow), and a persisted user override (`light` / `dark` / `system`) written before first paint to avoid a flash. |
| 9 | **Plan review** | [desktop](baseline/screenshots/plan-review-desktop.png) · [phone](baseline/screenshots/plan-review-mobile-full.png) | Takes over the main column. Two labelled lists; sub-questions in the UI face, arXiv queries in mono; one primary action; cancel separated and last. Detail in [§4.6](#46-planreview-replaced). |
| 10 | **Running** | [desktop](baseline/screenshots/running-desktop.png) | Trace spine pinned under the thread header; checkpoint ledger; *Live* indicator; diagnostics collapsed. The report column keeps whatever is already readable — incoming events never push the reader. |
| 11 | **Reconnecting** | [desktop](baseline/screenshots/reconnecting-desktop.png) | Spine's run segment breaks to an interrupted rule; status line "Reconnecting. Checkpoints during the gap are not replayed." The baseline's raw `stream_note` row moves into diagnostics. |
| 12 | **Rejoined after reload** | Reachable via `attach` (`useResearchStream.ts:238-253`) | Same as 10 but the ledger is explicitly empty: "Rejoined this run. Earlier checkpoints are not replayed." A `plan_ready` replay *does* arrive for a parked job (`src/api/routes.py:461-464`), so review is fully recoverable — that difference is stated, not smoothed over. |
| 13 | **Cancelled** | [desktop](baseline/screenshots/cancelled-desktop.png) | Terminal, neutral (not an error — the user chose it). "Cancelled at plan review. Nothing was searched." Primary recovery: ask again, labelled as a new billable run. |
| 14 | **Failed with partial briefing** | [desktop](baseline/screenshots/failed-partial-desktop.png) · [phone](baseline/screenshots/failed-partial-mobile.png) | The failure becomes a banner **above** a still-rendered briefing, not a panel replacing it. Export stays available because the backend allows it whenever `job.result` is non-empty (`src/api/routes.py:364-368`). See [§8.1](#81-partial-report-export-exposure). |
| 15 | **Failed, no result** | Same code path, `result` empty | Failure banner alone, with normalized `error_type` copy ([§8.3](#83-error_type-vocabulary)) and the raw string in diagnostics. |
| 16 | **Expired run** | [desktop](baseline/screenshots/expired-job-desktop.png) | The stream 404s and the browser will not retry (`useResearchStream.ts:171-188`). Spine renders entirely unknown. Copy: "This run is no longer available. Run records are kept for a limited time." Recovery is "Ask the question again", explicitly labelled as starting a new billable run. |
| 17 | **Submission error** | [desktop](baseline/screenshots/submission-error-desktop.png) | The composer keeps the typed question, shows a `role="alert"` with normalized cause, and offers a **manual** resubmit only. R-01: no automatic retry, ever, on `POST /research`. |
| 18 | **Rate limited (429)** | Contract-reachable; `enforce_rate_limit` on `POST /research` and `POST /conversations` (`src/api/routes.py:157`, `:545`) | Named state, not a generic error: "This workspace has used its hourly research budget." Uses `Retry-After` when present. Design note: a landing submission spends **two** slots (thread + run), and the production overlay sets the ceiling to 20/hour (`deploy/hetzner/compose.prod.yml:18`), so a fresh landing question costs 10% of the hour's budget. The composer surfaces remaining-budget copy only if a future header supplies it; it does not guess. |
| 19 | **Unauthorized (401)** | Contract-reachable when `enable_api_auth` is on and the server key is wrong | "This deployment is not accepting requests from this server." Explicitly a server-configuration message, not a login prompt — there is no user identity to re-authenticate ([§6](#6-identity-ready-shell)). |
| 20 | **Validation (422)** | `POST /research` and `/review` both bound-check | Field-level messages mapped onto the offending plan row or the question field. The baseline maps nothing. |
| 21 | **Thread not found (inline)** | [desktop](baseline/screenshots/conversation-not-found-desktop.png) | Baseline: one red sentence, no `h1`, axe `page-has-heading-one` failure ([axe](baseline/axe/conversation-not-found.json)). New: a proper `h1`, an explanation that a thread can also be missing because it belongs to another principal (the API returns 404 for both — `_check_ownership`, `src/api/routes.py:59`), and two routes out. |
| 22 | **Route not found (404)** | [desktop](baseline/screenshots/framework-not-found-desktop.png) | `app/not-found.tsx` inside the workbench shell: `h1`, rail intact, "Start a new question" as the primary action. |
| 23 | **Export refused (409)** | Contract-reachable when `result` is empty | The export control is *absent*, not disabled-and-silent, until a briefing exists; if a 409 still returns, an inline message names why. |
| 24 | **Delete confirmation** | `confirm()` today (`ConversationSidebar.tsx:74`) | APG modal dialog with focus containment and restore; copy per [§8.2](#82-deletion-copy). |
| 25 | **Stream recycled at the duration ceiling** | `stream_timeout` (`src/api/streaming.py:75`) | **Currently unhandled by the client**: `EVENT_NAMES` in `useResearchStream.ts:59-66` does not listen for it, so a server-side recycle at `api_sse_max_duration_sec` renders as a generic "connection interrupted". New: register the listener and say the true thing — "Connection recycled by the server. The run is still going." |

### 2.3 Omitted concepts

Per D-007 and D-009 item 3: unsupported concepts are **omitted with a
stated reason**, never simulated. Nothing in this list appears anywhere
in the shipped revamp, including as a disabled control or a "coming
soon" affordance.

| Omitted | Why | Where it would go |
|---|---|---|
| Structured paper / evidence inspection (paper cards, citation lists, claim→source links, per-chunk provenance) | Papers, analyses, citations and evidence exist inside workflow state but are absent from `JobDetail` (`src/api/routes.py:95-119`). Markdown parsing would be a shadow schema. | Separate versioned backend contract; the trace spine has a documented insertion point. |
| Plan lineage on finished runs | `job.plan = None` on resume (`src/api/runner.py:454`). Not retrievable after review. | A durable plan snapshot is a backend change. |
| Thread rename | No `PATCH /conversations/{id}`. | Backend proposal. |
| Search / filter over threads or briefings | No search endpoint; `GET /conversations` offers only `limit`/`offset`. | Backend proposal. |
| Post-approval cancellation | Cancel exists only at the review pause (`review` action `cancel`); there is no general cancel endpoint. | Backend proposal. |
| Determinate progress, percentage, ETA, "step 3 of 5" | No denominator exists; node set is configuration-dependent ([§5.1](#51-the-binding-constraint)). | Never, unless events gain a denominator. |
| "Currently running: reader" | `node_completed` fires *after* a node; there is no `node_started` (`src/api/streaming.py:26-29`). | Never, under this contract. |
| "Failed in stage X" | Terminal frames carry no `node` (`src/api/routes.py:857-867`). | Never, under this contract. |
| Retry this run | `POST /research` has no idempotency key and is non-idempotent (R-01). Only a *manual, explicitly-labelled new run* exists. | Backend idempotency key. |
| Page numbers / total counts in the rail | `GET /conversations` returns a bare array with no `total` or `has_more`. Only "Load more" is honest. | Backend proposal. |
| Accounts, login, avatars, sharing, per-user views | Single shared principal today; D-009 routes real multi-tenancy to MT-01. | MT-01. |
| Completion notification (email/push/desktop) | No delivery channel in the API. | Out of scope. |
| Cost estimate before submission | No pricing or estimation endpoint. | Out of scope. |
| Review countdown timer | `api_hitl_timeout_sec` is server config, not an API field. | See [§10](#10-what-gate-2-must-decide). |

---

## 3. Design tokens

Concrete values, both themes. Machine-readable twin:
[`design/tokens.json`](design/tokens.json), which records a `ratio` for
every pair below.

### 3.1 How the ratios were produced

Each ratio is the standard WCAG relative-luminance formula
`(L1 + 0.05) / (L2 + 0.05)` computed on the exact hex values printed
here. They are arithmetic on the token set, not a browser measurement —
so the axe gate in Phase 4 must confirm them in a real render before the
tokens are considered proven. Where a pair fails, the failure is written
down together with the rule that prevents the combination.

The three contrast failures in the committed baseline are named
explicitly so the fix is checkable:

| Baseline pair | Ratio | Source | Replacement | Ratio |
|---|---:|---|---|---:|
| `#94A3B8` on `#F8FAFC`, 10.4px (job-id label) | 2.45 | [axe/running.json](baseline/axe/running.json) | `ink-muted #4A636B` on `sunken #E7EEF0`, 12px | 5.44 |
| `#94A3B8` on `#FFFFFF`, 12px (event timestamps) | 2.56 | [axe/failed-partial.json](baseline/axe/failed-partial.json) | `ink-muted #4A636B` on `surface #FFFFFF`, 12px | 6.39 |
| `#D97706` on `#FFFFFF`, 12px (review label) | 3.18 | [axe/plan-review.json](baseline/axe/plan-review.json) | `review-text #8C5610` on `surface #FFFFFF` | 6.08 |

### 3.2 Colour — light

Built from Direction A's token seed ([`02-DIRECTIONS.md`](02-DIRECTIONS.md)
§Token seed). The seed's six hexes are preserved as the canonical
`canvas`, `ink`, `primary`, `signature`, `review` and `critical`; the rest
of the ramp is derived to make those six survive an AA audit.

| Token | Hex | Role | Checked against | Ratio |
|---|---|---|---|---:|
| `--canvas` | `#F3F7F8` | App background (seed: Mineral White) | — | — |
| `--surface` | `#FFFFFF` | Report and panel surface | — | — |
| `--sunken` | `#E7EEF0` | Rail, inset wells, diagnostics | vs canvas | 1.09 (separation is a border, not a fill) |
| `--ink` | `#172B31` | Primary text (seed: Carbon Ink) | surface / canvas / sunken | 14.72 / 13.65 / 12.54 |
| `--ink-muted` | `#4A636B` | Secondary text, all metric captions | surface / canvas / sunken | 6.39 / 5.92 / 5.44 |
| `--ink-faint` | `#5A737B` | Tertiary text | surface / canvas | 5.03 / 4.67 · **forbidden on sunken (4.29)** |
| `--ink-disabled` | `#7C9198` | Disabled control text | canvas 3.06 | 1.4.3 exempts disabled text; the state also carries `aria-disabled` and a reason string |
| `--border-subtle` | `#D2DFE2` | Grouping hairline only | surface 1.36 | never the sole boundary of a control |
| `--border-strong` | `#74898F` | Input, control and table borders | surface / canvas | 3.67 / 3.41 (≥3 per 1.4.11) |
| `--primary` | `#275DAD` | Actions, links (seed: Blueprint) | surface / canvas / sunken | 6.45 / 5.98 / 5.49 |
| `--primary-strong` | `#1E4C91` | Hover, and the focus ring | surface / canvas / sunken | 8.41 / 7.79 / 7.16 |
| `--primary-on` | `#FFFFFF` | Text on filled primary | on `#275DAD` / `#1E4C91` | 6.45 / 8.41 |
| `--signature` | `#167D7F` | Trace spine and observed checkpoints (seed: Oxidized Copper) | surface / canvas | 4.91 / 4.56 · **on sunken use `--signature-text`** |
| `--signature-text` | `#10666A` | Signature text on sunken | sunken | 5.71 |
| `--review` | `#C47A17` | Review marks and rules (seed: Review Amber) | surface / canvas (non-text) | 3.42 / 3.17 · **forbidden on sunken (2.91)** |
| `--review-text` | `#8C5610` | All review text | surface / review-surface | 6.08 / 5.44 |
| `--review-surface` | `#FBF1E1` | Plan-review panel field | ink on it | 13.16 |
| `--critical` | `#B33A3A` | Destructive fills, error rules (seed: Signal Red) | white on it | 5.86 |
| `--critical-text` | `#A32C2C` | Error text | surface / critical-surface | 7.11 / 6.20 |
| `--critical-surface` | `#FBECEC` | Error panel field | ink on it | 12.84 |

### 3.3 Colour — dark

Semantic roles are **remapped, not inverted**, per Direction A. The
bright chroma stays confined to trace, focus and action.

| Token | Hex | Checked against | Ratio |
|---|---|---|---:|
| `--canvas` | `#0E1A1E` | — | — |
| `--surface` | `#15252B` | vs canvas | 1.12 luminance step; elevation always adds a `border-strong` outline because shadows carry no signal here |
| `--sunken` | `#0A1418` | vs canvas | 1.05 |
| `--ink` | `#E8F1F3` | canvas / surface | 15.45 / 13.75 |
| `--ink-muted` | `#A6BEC4` | canvas / surface | 9.10 / 8.10 |
| `--ink-faint` | `#8CA5AC` | surface | 6.08 |
| `--ink-disabled` | `#6E888F` | surface 4.19 | exempt, same rule as light |
| `--border-subtle` | `#273B42` | surface 1.34 | grouping hairline only |
| `--border-strong` | `#61828B` | surface / canvas | 3.81 / 4.28 |
| `--primary` | `#8FB8EC` | surface / canvas | 7.69 / 8.64 |
| `--primary-on` | `#0E1A1E` | on `#8FB8EC` | 8.64 |
| `--focus` | `#9CC7F5` | canvas / surface | 10.04 / 8.94 |
| `--signature` | `#58C7C2` | surface / canvas | 7.78 / 8.74 |
| `--review` | `#EDB458` | surface / canvas | 8.47 / 9.51 |
| `--critical` | `#F2908A` | surface / canvas | 6.86 / 7.70 |

Dark-mode mechanics the baseline lacks entirely: `color-scheme: light dark`
on `:root`, a user-selectable override persisted and applied before first
paint, and dark values for the report's `code`/`th`/`td` treatments that
today only exist as `prefers-color-scheme` overrides in
`web/app/globals.css:33-58`.

### 3.4 Status is never colour alone

Each status carries a distinct **word**, a distinct **mark shape** and a
colour — in that order of precedence.

| Status | Word | Mark | Colour |
|---|---|---|---|
| Observed checkpoint | observed | filled circle `●` | signature |
| Stream open | Live | filled circle with ring | signature |
| Gap in observation | not observed | dashed rule `┈` | ink-faint |
| `pending_review` | Waiting for your review | outlined diamond `◇` | review |
| `succeeded` | Complete | filled square `■` | signature |
| `failed` | Failed | slashed square | critical |
| `cancelled` | Cancelled | hollow square `□` | ink-muted |
| Expired / unknown | No longer available | dashed square | ink-faint |

### 3.5 Typography

| Role | Family | Licence | Why this one |
|---|---|---|---|
| Report / display | **Literata** | SIL OFL 1.1 | A screen-first reading serif. It gives the briefing a physical identity distinct from the chrome that produced it — the reader can tell at a glance whether they are looking at the product or at its output. |
| UI / body | **Atkinson Hyperlegible Next** | SIL OFL 1.1 | The interface's most consequential text is short, dense and full of near-homoglyphs: job ids, arXiv identifiers (`arXiv:2601.00001`), and quality scores where `0.86` and `0.36` mean different things. A face engineered by the Braille Institute for character disambiguation is a choice derived from this content, and it directly supports the accessibility commitments in [§7](#7-accessibility-commitments). |
| Utility / data | **IBM Plex Mono** | SIL OFL 1.1 | Reserved for **anything the machine reads or writes back literally**: arXiv query strings, job ids, timestamps, `error_type` values, metric numerals, diagnostic rows, report code spans. |

**The typographic risk, stated plainly.** In the plan editor, the two
columns are set in *different families*: sub-questions in Atkinson (human
language you are free to rewrite), arXiv queries in IBM Plex Mono (literal
strings that will be sent to arXiv). Nothing labels this; the typeface
does. It is a real risk — it makes one form visually asymmetric — and it
is justified because the single most consequential edit in the product is
made in that form, and the user needs to know which field is prose and
which is a query string before they touch it.

Scale (full values in [`design/tokens.json`](design/tokens.json)):

| Token | Size / line | Use |
|---|---|---|
| `ui-xs` | 12 / 16 | Utility labels, timestamps, metric captions |
| `ui-sm` | 14 / 20 | Dense UI, thread rows, buttons, helper text |
| `ui-base` | 16 / 24 | Body UI and **all text inputs** (16px prevents iOS focus zoom) |
| `ui-lg` | 18 / 26 | Section headings in chrome |
| `ui-xl` | 22 / 28 | Thread title (`h1`) |
| `report-small` | 15 / 1.5 | Report tables and captions |
| `report-body` | 17 / 1.65 | Report paragraphs, measure capped at 68ch |
| `report-h3 / h2 / h1` | 18 / 22 / 27 | Report hierarchy, weight 600 |
| `display` | 34 / 1.18 | Landing prompt only, one per page |
| `mono-xs / mono-sm` | 12 / 16 · 13 / 20 | Ids and timestamps · query inputs and diagnostics |

Rules: minimum rendered size is **12px anywhere** (the baseline's 10.4px
job-id label is deleted, which is also one of the three contrast fixes);
uppercase only for one- or two-word eyebrows; the report never uses the UI
family and the chrome never uses the report family.

Loading: self-hosted woff2, latin subset, `font-display: swap`, with
metric-matched fallbacks. **The `size-adjust` / `ascent-override` values
are deliberately not written here** — they must be measured per family and
verified at CLS = 0, which is the baseline's measured value across all six
Lighthouse states. Inventing them would be exactly the kind of unbacked
number this project's review pass rejects.

### 3.6 Space, size, radii, elevation

**Space** — 4px unit: `2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 96`.
Layout constants: rail 260px (56px collapsed), report measure 68ch,
content max 1180px, gutters 16px narrow / 32px wide. Breakpoints
480 / 768 / 1024 / 1280.

**Size** — target minimum 24px (WCAG 2.2 SC 2.5.8), product default
32px, **44px under `@media (pointer: coarse)`**. Control heights 32 / 40 /
44. Focus ring 2px with 2px offset. Trace dot 7px; trace rule 2px.

**Radii** — `0 / 3 / 5 / 6px`, and nothing above 6px. The single
exception is the fully-round trace checkpoint dot, which is a data mark
rather than a container. This is Direction A's "restrained 3–6px, no
blanket rounded cards" made enforceable.

**Elevation** — the default is `elev-0`: separation comes from a 1px
`border-subtle` rule. `elev-1` (`0 1px 2px rgba(23,43,49,.06)`) only for
sticky chrome once content scrolls under it; `elev-2`
(`0 4px 12px /.10`) for the export disclosure and thread overflow menu;
`elev-3` (`0 12px 32px /.16`) for the delete dialog and the mobile
drawer. In dark mode every elevated surface must additionally step
canvas → surface and carry a `border-strong` outline, because the dark
shadow values (`.45`–`.65` black) carry almost no signal on their own.

### 3.7 Motion

| Token | Value | Applied to |
|---|---|---|
| `dur-fast` | 120ms | Focus ring, hover tint, checkpoint tick appearing (opacity only) |
| `dur-base` | 160ms | Disclosure open/close |
| `dur-slow` | 240ms | Mobile drawer — the only duration above 180ms, justified because it travels the full viewport width |
| `dur-ambient` | 2400ms | The *receiving* indicator: opacity 1 → 0.55 → 1, only while an EventSource is open |
| `ease-standard` | `cubic-bezier(.2,0,.2,1)` | Default |
| `ease-enter` / `ease-exit` | `cubic-bezier(0,0,.2,1)` / `cubic-bezier(.4,0,1,1)` | Entrances / exits |

Forbidden outright: streaming typewriter effects, skeleton shimmer,
orbiting particles, scroll-linked animation, any continuous decorative
motion, and any animation on the report column while the user is reading.

**Reduced motion.** Under `@media (prefers-reduced-motion: reduce)` all
transition and animation durations become 1ms, transform-based entrances
are removed, the drawer appears without translation, heading anchors use
`scroll-behavior: auto`, and the ambient receiving indicator becomes a
static filled mark plus the word *Live*. Because no state in the product
is conveyed by motion alone ([§3.4](#34-status-is-never-colour-alone)),
removing motion removes no information — that is the test the policy has
to pass, not a promise.

---

## 4. Component inventory

Ten existing components in `web/components/` plus one hook. "Replaced"
means the module is rewritten against a new contract; "restyled" means
the behaviour and props survive.

| Existing | Disposition | Reason |
|---|---|---|
| `ConversationsShell.tsx` | **Replaced** | Fixed two-column `div` with no landmarks; it is the direct cause of `landmark-one-main` + `region` in all 12 axe reports and of the mobile failure. |
| `ConversationSidebar.tsx` | **Replaced** | Becomes the Thread rail + drawer; the `opacity-0` delete control and `confirm()` both go. |
| `QueryForm.tsx` | **Replaced** | Needs counter, billability disclosure, error retention, and two different contexts (landing vs follow-up). |
| `ConversationThread.tsx` | **Replaced and split** | 310-line hotspot with duplicated load logic (`:38-59` and `:61-93`) and four responsibilities. |
| `EventLog.tsx` | **Replaced** | `role="log"` on a `<ul>` invalidates its own `<li>` children — the `aria-allowed-role`/`listitem` failures in plan-review, failed-partial and cancelled. |
| `PlanReview.tsx` | **Replaced** | Two mutually-disabled approve buttons; no field-level server-error mapping; amber label fails contrast. |
| `JobSummary.tsx` | **Restyled** | Shape is right (five real fields, `<dl>`); needs tokens, mono numerals, and a place attached to the briefing. |
| `ReportView.tsx` | **Replaced** | Early return hides a retained partial briefing (P5). |
| `ExportDropdown.tsx` | **Replaced** | Half-implemented APG menu (`role="menu"` with no roving focus); 01-RESEARCH recommends a disclosure instead. |
| `useResearchStream.ts` | **Extended, not replaced** | Its attach/reconnect/terminal behaviour is the best-tested thing in the frontend and is a MUST-KEEP. Additions only: `stream_timeout` listener, last-observed-checkpoint derivation, `pagehide`/`pageshow` handling for bfcache, and an explicit `observation` record. |
| `lib/api.ts`, `lib/types.ts` | **Extended** | One normalization contract for string / object / array / non-JSON / timeout / offline failures (`00-DISCOVERY.md` §Error shape). |
| `app/api/[...path]/route.ts` | **Untouched** | Security boundary. Not in scope (D-002, R-08). |

New components: `WorkbenchShell`, `SkipLink`, `ThreadRail`,
`ThreadDrawer`, `TraceSpine`, `CheckpointLedger`, `Diagnostics`,
`ReportReader`, `SectionRail`, `MetricsStrip`, `ExportDisclosure`,
`ConfirmDialog`, `StatusBanner`, `ThemeToggle`, `NotFound`, `RouteError`.

### 4.1 WorkbenchShell (new; replaces `ConversationsShell`)

States: rail expanded (≥1024px) · rail collapsed to 56px icons
(768–1023px) · drawer closed (<768px) · drawer open (<768px) · offline.

Structure: `SkipLink` → `<header>` with workspace identity and the
reserved account slot ([§6](#6-identity-ready-shell)) → `<nav aria-label="Threads">`
→ exactly one `<main id="main">`. This single change closes
`landmark-one-main` and `region` across all twelve baseline states.

### 4.2 ThreadRail / ThreadDrawer (replaces `ConversationSidebar`)

States: loading (skeleton rows) · empty · list · list with active-run row
marked *Live* · load-more available · error with retry · deleting ·
delete-confirm dialog open.

Two behavioural fixes: the destructive control is a **permanently
focusable** overflow button (never `opacity-0`, never revealed only by
hover — `ConversationSidebar.tsx:133`), and the row for the thread whose
run is currently attached preserves `?job=` so navigation cannot orphan
paid work (R-02).

### 4.3 QueryComposer (replaces `QueryForm`)

Variants: **landing** (display prompt, disclosure, "Generate plan") and
**follow-up** (compact, sticky at the bottom of the thread).
States: empty · typing with counter · over 8,000 (submit blocked, counter
in critical) · submitting · disabled because a run is in flight ·
disabled because the backend is unreachable · error with the question
retained.

The `Cmd/Ctrl+Enter` shortcut survives and gets a test — `00-DISCOVERY.md`
notes it is currently untested (`QueryForm.tsx:26-32`).

### 4.4 TraceSpine + CheckpointLedger (new)

Full spec in [§5](#5-signature-interaction--the-research-trace-spine).

### 4.5 Diagnostics (replaces `EventLog`)

A disclosure, collapsed by default, containing a `<table>` of received
frames (time · event · detail) wrapped in
`<div role="log" aria-live="polite">`. Putting the live-region role on
the *wrapper* rather than on the list is the fix for `aria-allowed-role`
and `listitem`. Collapsed by default also means routine frames are not
announced, which is what `01-RESEARCH.md` reads out of WCAG 4.1.3.

States: collapsed · expanded · empty ("No frames received on this
connection") · unknown event received (rendered verbatim; the client must
tolerate unknown names and fields per the SSE invariants).

The baseline's three fixed grid columns (`EventLog.tsx:40`) overflow on
phones; the new table scrolls inside its own labelled region.

### 4.6 PlanReview (replaced)

States: editing · unedited · edited · submitting (approve) · submitting
(cancel) · field validation error · server 409 (review no longer pending)
· server 422 (bounds) · resolved (surface removed, spine advances).

Changes from baseline:

- **One primary action.** The baseline ships two approve buttons that are
  never both usable — "Approve as-is" is disabled once you edit, "Save
  edits & approve" is disabled until you do (`PlanReview.tsx:90-106`).
  The new surface has a single **Approve plan** button that relabels to
  **Save edits and approve** when the working copy differs, and sends
  `approve` or `revise` accordingly. One intent, one control.
- **Cancel is separated** to the far end, styled as a destructive
  secondary, and its copy states the consequence: "Cancel run — nothing
  will be searched."
- Fields get visible labels; the arXiv query column gets an
  `aria-describedby` hint that these strings go to arXiv verbatim.
- Add/remove buttons meet the 24px minimum and 44px on coarse pointers;
  the baseline's `&times;` button is a 1-unit-padded glyph.
- A status line states the two true facts: the run is paused and not
  spending, and it will stop on its own if it is not reviewed. No
  countdown, because the deadline is not in the API.

### 4.7 ReportReader + SectionRail + MetricsStrip

`ReportReader` states: absent · present · present-with-failure-banner ·
loading skeleton · very long (section rail becomes sticky) · contains
wide table (table scrolls inside a labelled region, page does not pan).

`SectionRail` is derived from the report's own rendered `h2`/`h3` nodes —
truthful because those headings genuinely exist in the Markdown. It is
borrowed from Direction B exactly as `02-DIRECTIONS.md` recommends,
without importing that direction's visual metaphor.

`MetricsStrip` keeps `JobSummary`'s five real fields (iterations,
quality, cost, LLM calls, elapsed) in mono numerals, attached beneath the
briefing they describe rather than floating as a dashboard row. Null
metrics render an em dash with a `title`-free explanation, not `-`.

Known investigation item carried from `00-DISCOVERY.md`: the terminal
path may render a successful briefing twice — once as the reloaded
historical turn and once as retained current-run detail. The new split
gives the current run and the thread history one shared source of truth
for "which job is on screen", and Phase 4 owes a deterministic browser
test that confirms or retires this.

### 4.8 ExportDisclosure (replaces `ExportDropdown`)

A `<button aria-expanded>` disclosure over a plain list of three
`<a download>` links to the same-origin proxy — the pattern
`01-RESEARCH.md` recommends over a half-built menu. States: closed ·
open · absent (no briefing) · error after 409.

Present wherever a briefing exists, **including on a failed run with a
retained partial briefing** ([§8.1](#81-partial-report-export-exposure)).

### 4.9 StatusBanner / ConfirmDialog / NotFound / RouteError / ThemeToggle

`StatusBanner` — one component, five severities (info, review, live,
warning, critical), used for submission errors, review errors, expiry,
rate limiting, backend-offline and stream recycling. `role="alert"` only
for user-triggered failures; everything else is ordinary content plus a
single `role="status"` region.

`ConfirmDialog` — APG modal dialog, focus contained and restored,
labelled by its heading. Replaces `confirm()`.

`NotFound` / `RouteError` — both render inside `WorkbenchShell` with a
real `h1`, closing `page-has-heading-one`.

`ThemeToggle` — light / dark / system, persisted, applied before first
paint.

---

## 5. Signature interaction — the research trace spine

### 5.1 The binding constraint

Carried verbatim in force from the Gate 1 review's blocking finding 2 and
its second-pass minor finding 2 ([`REVIEW.md`](REVIEW.md)):

> The trace may be driven **only** by job status plus the last observed
> completed `node_completed` checkpoint. It must never claim a live
> "current stage" or that a run "failed in stage X". After a reload the
> position may be unknown. Failure is *after the last observed
> checkpoint*. Stage labels derive only from observed events — there is
> no pre-labelled fixed node vocabulary.

Why this is a contract fact and not caution:

- `node_completed` is emitted *after* a node returns; there is no
  `node_started` (`src/api/streaming.py:14-29`).
- Redis pub/sub keeps no backlog and the stream has no `id:` /
  `Last-Event-ID`, so a reconnect recovers nothing that was missed
  (`00-DISCOVERY.md` §SSE invariants).
- Terminal replay carries no `node` field
  (`src/api/routes.py:857-867`), so failure can never be attributed to a
  stage.
- **The node set is configuration-dependent.** The fixed graph has
  `planner, search, reader, synthesizer, critic`; the supervisor graph
  adds `supervisor` and conditionally `verifier` and `query_refiner`
  behind `enable_verifier` / `enable_query_refiner`
  (`src/graph/workflow.py:366-430`, `src/config.py:585-660`). The
  supervisor may also revisit a node. Any pre-drawn ruler of expected
  stages would be wrong on some deployments and on some runs.
- `node_completed.state_delta` is deliberately open and scalar-filtered
  (`src/api/runner.py:943-955`); clients must tolerate unknown keys.

### 5.2 What the spine may read

Exactly four inputs. Anything else is out of bounds.

| Input | Source | Truth value |
|---|---|---|
| Job status | `JobDetail.status`, or the terminal SSE frame | Authoritative |
| Checkpoints observed **on this connection** | `node_completed` frames, label taken verbatim from `data.node` | Observation, not history |
| Plan | `JobDetail.plan` / `plan_ready`, non-null only during `pending_review` | Observation; erased on resume |
| Time since last frame | Client clock | Observation |

### 5.3 Anatomy

Four segments, and they are **workflow phases the HTTP contract actually
models via status transitions** — not pipeline node names. The run
segment holds a variable-length, append-only ledger of observed
checkpoints whose labels come from the event payload verbatim.

```text
 Question ──● Plan ──● Run ─●──●──●┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈  Report
 captured    approved       planner search reader
                                          └ last observed 41s ago

 Running · 3 checkpoints observed on this connection
 Position after the last checkpoint is not reported.   [Technical events]
```

Legend, rendered in the UI once per session and available from a
disclosure thereafter:

```text
 ●  observed on this connection      ┈  not observed
 ◇  waiting for your review          ■  complete
 □  cancelled                         ?  no longer available
```

### 5.4 State-by-state

| Situation | Spine | Status line |
|---|---|---|
| Submitting | `Question ─◌` rest inert | "Generating plan…" |
| `pending_review` | `Question ──● Plan ──◇` | "Waiting for your review. The run is paused and not spending." |
| Running, checkpoints seen | ticks appended; trailing dashed rule | "Running · N checkpoints observed on this connection · updated 41s ago" |
| Running, **rejoined after reload** | run segment fully dashed, ledger empty | "Rejoined this run. Earlier checkpoints are not replayed." |
| Reconnecting | ticks kept, then a broken rule | "Reconnecting. Checkpoints during the gap are not replayed." |
| Stream recycled (`stream_timeout`) | unchanged | "Connection recycled by the server. The run is still going." |
| Succeeded | `… Run ──● Report ■` | "Complete in 74.3 s · quality 0.86 · $0.4231 · 11 calls" |
| Succeeded, loaded from thread history | `Question ──? Plan ──? Run ──? Report ■` | "This briefing was produced outside this session. Its plan and checkpoints are not stored." |
| Failed, checkpoints seen | ticks then a slashed square | "Failed after the last observed checkpoint (`reader`)." |
| Failed, none seen | dashed run then slashed square | "Failed. No checkpoints were observed on this connection." |
| Cancelled | `Question ──● Plan ──□` | "Cancelled at plan review. Nothing was searched." |
| Expired | every segment dashed with `?` | "This run is no longer available. Run records are kept for a limited time." |

### 5.5 Copy rules

Forbidden strings anywhere in the product, enforceable by a lint rule
over the copy dictionary: *currently running*, *in progress: <node>*,
*step N of M*, any `%`, any ETA, *failed during*, *failed in*, *stage*,
*almost done*, and any label for a node that was not observed.

Required qualifiers: "on this connection" wherever a checkpoint count
appears; "observed" wherever a checkpoint is named; "not reported" rather
than "unknown" when the API is simply silent — silence is the API's
behaviour, not a gap in our knowledge of it.

### 5.6 Motion

The last observed tick fades in over `dur-fast`, opacity only, no
translation — a checkpoint arriving must never move the reading column
(CLS budget 0.00). The *receiving* indicator is the only ambient motion
in the product (`dur-ambient`, 2400ms opacity cycle) and runs only while
an EventSource is open. Under reduced motion it becomes a static mark
plus the word *Live*. The dashed "not observed" rule is **static** — the
one thing that must never animate is the region the UI knows nothing
about, because motion there would read as activity.

### 5.7 Accessibility

The spine is an `<ol>` of four segments inside a labelled region; the
checkpoint ledger is a nested `<ol>`. The status line is the product's
single `role="status"` live region and announces only material
transitions — awaiting review, reconnecting, recycled, complete, failed,
cancelled, expired — never individual checkpoints. Every mark has a text
equivalent in the same visual line, so the spine is fully usable with
images or colour unavailable. Marks are drawn at ≥3:1 against their
surface ([§3.2](#32-colour--light)).

### 5.8 The one aesthetic risk, and why it is worth it

Almost every long-running AI interface draws a confident animated bar.
This one draws its own blind spot: the unobserved portion of the run is a
visible, dimensioned, deliberately static dashed void, and the copper
signature colour is spent **only** on the spine. The design's most
memorable element is the shape of what it does not know.

That is a real risk — it is less reassuring than a progress bar, and a
stakeholder may read it as an unfinished UI. It is the right risk for
this product: the thing being sold is a *defensible* briefing, and a
tool that fabricates its own progress has already shown it will
fabricate. If Gate 2 rejects this, the fallback is a status-only chip
with no spine at all — **not** a spine with invented stages.

### 5.9 Test obligations before this ships

1. Contract fixtures for: live checkpoints, reload-with-no-checkpoints,
   reconnect gap, `stream_timeout`, terminal replay (no `node`), unknown
   event name, unknown `state_delta` keys.
2. A test asserting that no forbidden string from
   [§5.5](#55-copy-rules) can be produced by any spine state.
3. A test asserting the ledger never contains a label that did not arrive
   in a `node_completed` payload.

---

## 6. Identity-ready shell

Per D-009: the user **rejected** the shared-principal model as the end
state, and real multi-tenancy is a separate backend workstream (MT-01)
outside this revamp's frozen-backend boundary. Until MT-01 lands, the
shell must not fake login or per-user views.

**What is reserved (built now, occupied by truthful content):**

| Reservation | Occupied today by | Becomes under MT-01 |
|---|---|---|
| A fixed slot at the end of the workbench header | A workspace indicator: "Shared workspace — everyone with access to this deployment sees these threads." | Account control |
| An `owner` slot in every thread row (rendered, empty, zero-height today) | Nothing | Owner name/avatar, without reflowing the list |
| A `principal` concept in the client data layer, single and implicit | The one server key | Per-user principal; a **value** change, not a shape change |
| Route names `/login` and `/settings` | **Not created.** Documented as reserved so nothing else claims them | Real routes |
| A scoping parameter on the thread query, always the implicit principal | — | Per-user scoping |
| 401 handling that is a *server configuration* message | "This deployment is not accepting requests from this server." | A re-authentication path |

**What is explicitly not built:** avatar menus, sign-in/sign-out,
"My threads" vs "All threads", sharing, per-user settings, ownership
badges, or any disabled control hinting at accounts. A disabled login
button is still a fake login.

The backend already has the substrate MT-01 would build on — per-principal
scoping and 404-on-foreign-resource (`_check_ownership`,
`src/api/routes.py:59`; ADRs [0033](../decisions/0033-safety-hardening-bundle.md),
[0036](../decisions/0036-per-principal-store-scoping.md),
[0037](../decisions/0037-redis-rate-limiter-and-keystore-reload.md)) — so
the most plausible shape is a web session in the Next proxy mapped to a
per-user principal. That is MT-01's proposal to make, not this brief's.

One honest consequence the copy must carry today: because the API
returns 404 both for "does not exist" and "belongs to another principal",
the thread-not-found state ([§2.2](#22-state-matrix) row 21) says so.

---

## 7. Accessibility commitments

Target: WCAG 2.2 AA, plus task-based keyboard and screen-reader proof.

### 7.1 Baseline axe findings this redesign fixes

| Rule | States affected | Fix |
|---|---|---|
| `landmark-one-main` | 12 of 12 | `WorkbenchShell` renders exactly one `<main id="main">` |
| `region` | 12 of 12 | All content inside `header` / `nav[aria-label]` / `main` / `aside[aria-label]` |
| `aria-allowed-role` + `listitem` | plan-review, failed-partial, cancelled | `role="log"` moves to a wrapper `<div>`; list semantics restored ([§4.5](#45-diagnostics-replaces-eventlog)) |
| `color-contrast` | plan-review, running, failed-partial, cancelled, expired-job | The three exact pairs in [§3.1](#31-how-the-ratios-were-produced) are replaced with measured-AA tokens |
| `page-has-heading-one` | conversation-not-found | Every state, including inline not-found, renders an `h1` |

Non-axe baseline defects also fixed: the `opacity-0` keyboard-invisible
delete control (`ConversationSidebar.tsx:133`), the half-implemented ARIA
menu (`ExportDropdown.tsx:69`), `confirm()` as a destructive dialog, the
missing `/favicon.ico` (a Best-Practices deduction in all six Lighthouse
runs), and the missing `color-scheme` declaration.

**Not claimed as fixed:** keyboard order, focus restoration, announcement
quality, reflow usability and screen-reader comprehension cannot be
established by automation. `baseline/README.md` defers them to manual
checks, and this brief does the same — with the difference that
[§7.6](#76-what-must-be-proven-not-asserted) names the evidence owed.

### 7.2 Keyboard and focus

- `:focus-visible` only; a 2px `--focus` ring at 2px offset, verified
  ≥3:1 against canvas, surface and sunken in both themes
  ([§3.2](#32-colour--light), [§3.3](#33-colour--dark)).
- `outline: none` is never written without an equivalent replacement in
  the same rule.
- Tab order: skip link → header → thread rail → main → composer.
- Focus is trapped only in the delete dialog and the mobile drawer, and
  restored to the trigger on close.
- Nothing is reachable by hover alone; nothing is revealed only by hover.
- The plan editor's remove buttons keep a stable accessible name
  (`Remove sub-question 2`) and removal moves focus to the next row, or
  to the add control when the list empties.

### 7.3 Live regions

Exactly two, product-wide: one `role="status"` (the spine's status line;
material transitions only) and one `role="alert"` (user-triggered
failures: submission, review, delete, export). The diagnostics
`role="log"` is collapsed by default, so routine SSE frames are not
announced.

### 7.4 Targets and reduced motion

Minimum 24×24 CSS px (SC 2.5.8), product default 32×32, and 44×44 under
`@media (pointer: coarse)`. Reduced-motion policy in
[§3.7](#37-motion); the test is that no information is lost when motion
is removed.

### 7.5 The mobile repair

The documented failure: at the 412px audit viewport the permanent 256px
`<aside>` plus main padding leaves roughly **100px** of work surface
([`baseline/README.md`](baseline/README.md) · [screenshot](baseline/screenshots/home-mobile-full.png)).
The cause is structural — `ConversationsShell.tsx:22-28` renders
`flex h-screen` with a `w-64 shrink-0` rail at every width — so component
wrapping cannot fix it.

The repair:

| Width | Layout |
|---|---|
| < 768px | Single column. Threads become a modal drawer behind a labelled header button. No persistent rail. Composer sticky at the bottom with `env(safe-area-inset-bottom)`. |
| 768–1023px | Rail collapses to a 56px icon strip with accessible names; expands over content on demand. |
| ≥ 1024px | Persistent 260px rail; report column at 68ch; section rail appears ≥1280px. |

Plus: report tables scroll inside `overflow-x: auto` regions that are
labelled and keyboard-focusable, so the **page** never pans (SC 1.4.10);
the diagnostics table does the same; all inputs are 16px to prevent iOS
focus zoom.

Acceptance: at 412px the work surface is ≥ viewport width minus 32px of
gutters (~380px, versus ~100px today); at a 320px equivalent there is no
horizontal page scroll; the layout survives 400% zoom.

### 7.6 What must be proven, not asserted

Owed before Gate 4: axe at component and route level with zero
violations across the full state matrix; a keyboard walkthrough of skip
link, rail, drawer, composer, plan arrays, approve/cancel, diagnostics
disclosure, report headings and tables, export, deletion and error
recovery; screen-reader passes on VoiceOver + Safari and NVDA + Firefox;
reflow at 320px equivalent and 400% zoom; and a reduced-motion pass
confirming no state is motion-only.

Separate performance item with an accessibility flavour: `/c/[id]`
currently fails the back/forward-cache audit. An open `EventSource`
makes a page bfcache-ineligible, so the fix is to close the stream on
`pagehide` and re-attach on `pageshow` — which must be built to preserve
the `?job=` contract exactly, and is therefore listed here as a design
requirement rather than an optimisation.

---

## 8. Proposed answers to the four "can wait" questions

These are **recommendations for the human to ratify at Gate 2**
([`00-DISCOVERY.md` §Gate 1 questions](00-DISCOVERY.md#can-wait)), not
decisions taken.

### 8.1 Partial-report export exposure

**Recommendation: expose it.** A failed run whose `result` is non-empty
shows its briefing with a failure banner above it, and keeps export.

Rationale. The backend already permits this — `export_research` refuses
only when `job.result` is empty, and does not consider status
(`src/api/routes.py:364-368`). The hiding is a frontend accident:
`ReportView` returns early on `status === "failed" && detail.error`
(`web/components/ReportView.tsx:13-27`), which the committed
`failed-partial` fixture proves discards a retained briefing
([evidence](baseline/screenshots/failed-partial-desktop.png)). The user
has already paid for that work — the failed-partial fixture carries
`$0.1800` and 4 LLM calls. Discarding it converts a partial success into
a total loss, and the export is the only durable copy once
`api_job_retention_sec` elapses. Mitigation for the obvious objection:
the export **must** be marked as partial — the banner is above the
briefing on screen, and Gate 2 should decide whether the exported file
itself carries a partial-result header, which would be a backend change
to the exporters. Closes R-14.

### 8.2 Deletion copy

**Recommendation: "Delete thread".** Full dialog copy:

> **Delete "Retrieval-augmented evaluation"?**
> This removes the thread and its briefings from this workspace. Run
> records are kept separately and expire on their own schedule.
> [Cancel] [Delete thread]

Rationale. The baseline's `confirm("Delete this conversation and all its
jobs?")` (`ConversationSidebar.tsx:74`) is wrong twice: "conversation" is
not the product's word ([§1.5](#15-product-lexicon)), and "all its jobs"
overstates what happens. The Postgres cascade removes the conversation's
job rows, but the job store's own records live under
`api_job_retention_sec` (`src/config.py:307`, default 24h) on a separate
lifecycle — so a deleted thread does not necessarily make an in-flight or
recently-finished run unreachable by id. The proposed copy names the
user's object, states the real effect, and does not promise erasure the
system does not perform. Gate 2 should confirm the second sentence is
accurate for the deployed store combination before it ships.

### 8.3 `error_type` vocabulary

**Recommendation: map to a small user-facing vocabulary, and always keep
the raw string one disclosure away.**

The backend produces four deliberate values —
`hitl_timeout` (`src/api/runner.py:1057`),
`cost_budget_exceeded` (`:1085`), `timeout` (`:1150`),
`orphaned` (`src/api/redriver.py:507`) — plus, for anything else,
`type(exc).__name__` (`src/api/runner.py:1219`), which today yields
`NoPapersFoundError`, `AllPaperAnalysesFailedError`,
`SynthesizerOutputError`, `ArxivUnavailableError`, `JobCancelledError`
and any future exception class name.

Proposed mapping:

| `error_type` | User-facing | Recovery offered |
|---|---|---|
| `hitl_timeout` | "The plan was not reviewed in time, so the run stopped." | Ask again (new run) |
| `cost_budget_exceeded` | "The run reached this workspace's cost limit." | Ask again with a narrower plan |
| `timeout` | "The run took longer than this workspace allows." | Ask again with a narrower plan |
| `orphaned` | "The run was interrupted by a server restart and could not be resumed safely." | Ask again |
| `NoPapersFoundError` | "No matching arXiv papers were found for these queries." | Ask again and edit the arXiv queries at review |
| `ArxivUnavailableError` | "arXiv could not be reached." | Ask again later |
| `AllPaperAnalysesFailedError` | "Papers were found but none could be read." | Ask again and edit the arXiv queries |
| `SynthesizerOutputError` | "The briefing could not be assembled from what was read." | Ask again |
| *anything else* | "The run failed." + the raw `error` message | Ask again |

Two rules make this safe rather than lossy. The default branch must never
swallow an unmapped value — it shows the generic sentence **and** the raw
`error` text. And the raw `error_type` string always remains visible in
the diagnostics disclosure, because it is what a user pastes into an
issue. A drift test should assert that every value the backend can
produce is either mapped or falls through visibly.

### 8.4 `hitl_bypass` availability

**Recommendation: keep it unavailable in the UI, and make that a stated
design rule rather than an omission.**

`hitl_bypass` exists for programmatic HTTP callers
(`src/api/schemas.py:41-47`); the eval runner reaches the same outcome a
different way — it builds the workflow with `enable_hitl=False`
(`src/eval/runner.py:297`), so the field has no non-test consumer in
this repository. It is already plumbed through the client
(`ResearchSubmitOptions.hitl_bypass`, `web/lib/api.ts:26-37`) and simply
never set.

Exposing it would remove the one human control that makes this product
what it is, and would move the only cancellation point in the entire
lifecycle — cancel exists **only** at the review pause. A user who
bypasses review has no way to stop a run at all. That is a materially
worse product, not a power-user convenience.

Keep the field in the typed client (removing it would be a false
narrowing of the real API), keep it unset from every UI path, and add a
test asserting no UI code path passes it. If Gate 2 disagrees, the right
shape is a workspace-level deployment setting, not a per-question
checkbox — because it changes what the product *is*, not what one run
does.

---

## 9. Constraints carried from review

Binding on everything above; sourced from [`REVIEW.md`](REVIEW.md) and
[`DECISIONS.md`](DECISIONS.md).

1. **Checkpoint honesty** (blocking finding 2, reinforced by second-pass
   minor finding 2). Job status plus last observed completed checkpoint
   only. No current stage, no failing stage, no pre-labelled node
   vocabulary, unknown after reload. Implemented as
   [§5](#5-signature-interaction--the-research-trace-spine) and
   testable via [§5.9](#59-test-obligations-before-this-ships).
2. **Billability disclosure** (major finding 4). Landing copy states that
   plan generation may be billable and that review happens before
   literature search and downstream research. Implemented verbatim in
   [§1.4](#14-landing-copy).
3. **Omit, do not simulate** (D-007, D-009 item 3). Enumerated with
   reasons in [§2.3](#23-omitted-concepts).
4. **Shared principal is not the end state** (D-009 item 2). Reserve the
   shell, ship no fake identity — [§6](#6-identity-ready-shell).
5. **Anti-generic specificity** (first-pass minor finding 7, explicitly
   deferred to Phase 2). The design's distinctiveness has to come from
   plan lineage, arXiv/query language, checkpoints and report behaviour —
   not decoration. Where that is spent: the trace spine's visible blind
   spot ([§5.8](#58-the-one-aesthetic-risk-and-why-it-is-worth-it)), the
   two-family plan editor ([§3.5](#35-typography)), and the "observed /
   not observed" vocabulary that runs through every state.
6. **Frozen backend** (D-002/D-009). No response shape, endpoint or SSE
   contract changes. `app/api/[...path]/route.ts` is untouched.
7. **First vertical slice as approved** (D-009 item 4): new question →
   reload-safe job → plan review → stream/reconnect →
   report/metrics/export. Every component in
   [§4](#4-component-inventory) is on that path, or is a shell/error
   surface that path passes through.
8. **Evidence, not assertion** (the standing review policy). Every claim
   here cites a screenshot, an axe report, or a file and line. Where a
   number could not be established — `size-adjust` values, the review
   deadline, field performance — this brief says so instead of inventing
   it.

---

## 10. What Gate 2 must decide

**Blocking — the brief cannot proceed to work orders without these:**

1. **The four can-wait answers in [§8](#8-proposed-answers-to-the-four-can-wait-questions).**
   Ratify, amend, or reject each. §8.1 also asks a follow-on: should a
   *partial* export carry a marker inside the file? That is a backend
   exporter change and needs its own approval.
2. **The trace spine's blind-spot treatment
   ([§5.8](#58-the-one-aesthetic-risk-and-why-it-is-worth-it)).** Accept
   the visible unobserved region, or fall back to a status-only chip.
   There is no third option that stays truthful.
3. **The three typefaces ([§3.5](#35-typography))** — Literata, Atkinson
   Hyperlegible Next, IBM Plex Mono, all SIL OFL 1.1, self-hosted. This
   is a bundle-budget commitment as well as an aesthetic one (R-11).
4. **The two-family plan editor.** The deliberate typographic asymmetry
   between sub-questions and arXiv queries.
5. **The lexicon change ([§1.5](#15-product-lexicon))** — "thread",
   "run", "briefing", "checkpoint". It touches copy, URLs users read,
   export filenames and every error string.

**Needed before implementation, but not blocking this document:**

6. **Architecture confirmation (D-002)** — Next + the same-origin proxy
   retained; TanStack Query for idempotent reads with retry explicitly
   disabled on `POST /research`; the custom EventSource adapter kept
   separate. `01-RESEARCH.md` §Preliminary stack recommendation is the
   input.
7. **Route bundle budgets.** The baseline is 137,272 B gzip for `/` and
   184,745 B for `/c/[id]`. Three self-hosted families and new primitives
   will move both. Gate 2 should set the ceiling before the work orders,
   not after.
8. **Whether `job.plan = None` on resume
   ([§0](#0-one-new-finding-this-brief-is-built-around)) is accepted as
   permanent.** If plan lineage on finished runs is a product
   requirement, it is a backend proposal — a durable plan snapshot on the
   job record — and belongs beside MT-01, not inside this revamp.
9. **Whether the API should expose the review deadline.** Today
   `api_hitl_timeout_sec` is server config, so the UI cannot show a
   countdown on the one screen where a deadline has real consequences.
   Also a backend proposal, also outside this revamp's boundary.
10. **MT-01 sequencing.** Nothing here implements identity, but the
    reserved slots in [§6](#6-identity-ready-shell) are cheaper to build
    now than to retrofit. Gate 2 should confirm they are wanted.

---

## Appendix — anti-template self-critique

What was considered and cut, and why, per the design skill's
"remove one accessory" pass:

- **A metrics dashboard row above the report.** Cut. It is the template
  answer for "we have five numbers", and it puts operational telemetry
  above the artefact the user came for. The five real metrics now sit
  beneath the briefing they describe.
- **A pre-drawn stage ruler** (Direction C's shape). Cut at the source:
  the node set is deployment-dependent and the supervisor can revisit
  nodes ([§5.1](#51-the-binding-constraint)). It was also the
  second-pass reviewer's specific objection to the Direction C sketch.
- **Warm cream + serif display + terracotta accent**, and **near-black +
  one acid accent.** Both are the current defaults of machine-generated
  design; both were rejected by Direction A's own anti-template critique
  before this brief started. The palette here is a cool mineral ramp with
  one oxidised-copper signature spent on exactly one element.
- **A second accent colour for "success".** Cut. The baseline's emerald
  approve button is a sixth colour doing a job the signature already
  does. Completion is a filled copper square; approval is primary
  Blueprint, because approving is an *action*, not an *outcome*.
- **Skeleton shimmer.** Cut. Reserved space at the right height is the
  same information without the animation.
- **A conversation search box.** Cut — there is no search endpoint, and
  a client-side filter over a `limit`-capped list would silently lie
  about coverage.
- **Uppercase eyebrow labels on every panel** (visible throughout the
  baseline). Reduced to one- or two-word eyebrows only.

What was kept despite being uncomfortable: the visible unobserved region
in the spine, the asymmetric plan editor, and the absence of any control
that would let a user skip review.
