# Frontend revamp architecture

Phase: 3 (architecture) — input to **Gate 2**
Date: 2026-08-28
Branch: `docs/frontend-revamp-phase3-architecture`
Base commit: `0b6f291` (Gate 1 docs merged)
Status: proposal awaiting Gate 2 approval

## How to read this document

This document describes **`main` as it is today** and proposes a target
architecture. Everything that does not exist yet is labelled **planned**.
No source, config, or CI file is modified by this document.

The backend HTTP/SSE contract is **frozen**. Every claim about it below
carries a `file:line` citation into `src/api/`, and every claim about the
current frontend carries one into `web/`. Where the contract is ambiguous
or asymmetric, it is recorded in [§11](#11-contract-ambiguities-to-resolve-at-gate-2)
rather than silently designed around.

Inputs: [`00-DISCOVERY.md`](00-DISCOVERY.md), [`01-RESEARCH.md`](01-RESEARCH.md),
[`02-DIRECTIONS.md`](02-DIRECTIONS.md) (Direction A), [`REVIEW.md`](REVIEW.md),
[`DECISIONS.md`](DECISIONS.md), [`RISKS.md`](RISKS.md),
[`baseline/README.md`](baseline/README.md).
Migration sequencing lives in [`05-MIGRATION.md`](05-MIGRATION.md).

Design values (palette, type scale, spacing rhythm, motion) are **not** in
this document. They are authored in Phase 2 at `docs/revamp/03-DESIGN-BRIEF.md`,
concurrently on branch `docs/frontend-revamp-phase2-brief`. This document
defines only the *technical contract* the brief plugs into — see
[§6](#6-styling-and-token-integration). The path is written as plain text,
not as a Markdown link, because the file does not exist on this branch and a
link to it would not resolve.

### Verification run on this branch

```text
web $ npm ci            -> added 589 packages
web $ npm run typecheck -> exit 0
web $ npm run test      -> 12 files, 78 tests passed (3.22 s)
```

Two known warnings reproduced, both already recorded in discovery
(`00-DISCOVERY.md` "Current test warnings"): `vitest.config.mts:15` uses
`__dirname`, and jsdom prints `Not implemented: navigation to another Document`
during the export-download test. Repairs for both are planned work items in
[`05-MIGRATION.md`](05-MIGRATION.md#3-ci-and-operational-additions-planned).

---

## 1. Target frontend architecture and the D-002 decision

### 1.1 What the current boundary actually does

Three properties of the existing Next.js route handler are load-bearing, and
all three are visible in the code:

1. **It is the only place the upstream credential exists.**
   `web/app/api/[...path]/route.ts:81-82` reads `process.env.ARXIV_API_KEY`
   and sets `X-API-Key` on the upstream request. The browser client never
   sees it — `web/lib/api.ts:14` hard-codes `API_BASE = "/api"` and every
   call in that module is same-origin. The upstream header name is the one
   FastAPI expects (`src/api/auth.py:44`, enforced at
   `src/api/auth.py:481-516`).

2. **It streams SSE and downloads without buffering.**
   `route.ts:110-114` returns `upstream.body` — the raw `ReadableStream` —
   with an allowlisted subset of upstream headers (`route.ts:18-25`). That
   allowlist is why exports work: `content-disposition` survives
   (`src/api/routes.py:385` sets `attachment; filename=...`), as does
   `x-accel-buffering: no` (`src/api/routes.py:517`) which is what keeps SSE
   unbuffered through a reverse proxy. `retry-after` also survives
   (`route.ts:22`), which is the only way a 429 (`src/api/auth.py:183`) can
   be rendered usefully.

3. **Two browser APIs cannot carry a header at all.**
   Native `EventSource` (`web/lib/useResearchStream.ts:121`) accepts no
   request headers, and the export links are plain anchors
   (`web/components/ExportDropdown.tsx:51-52`, `href` + `download`, no
   `fetch`). Under `ENABLE_API_AUTH=true` — which is exactly the production
   configuration, `deploy/hetzner/compose.prod.yml:14-15` — **neither the
   stream nor any export can be authenticated from browser code.** A
   same-origin server hop is not a convenience here; it is the only
   mechanism that makes those two surfaces work at all.

Property 3 is the decisive one and it does not appear in D-002's original
rationale. It converts "we would have to recreate the BFF" into "any
architecture without a same-origin server hop cannot stream or export in
production".

### 1.2 Alternatives evaluated

| Option | What it would cost | Verdict |
|---|---|---|
| **A. Keep Next.js App Router + the Node route handler** (D-002) | Nothing; it already exists and is tested (`web/tests/apiProxyRoute.test.ts`, 144 lines covering key injection, header allowlists, misconfiguration, and network failure) | **Recommended** |
| B. Vite/React SPA + a separate Node (Hono/Express) BFF | Rebuilds properties 1–3 in a new service; adds a fourth image to Compose (`docker-compose.yml` currently has app/web/redis/postgres), a second CI build job, and a second thing Caddy must route (`deploy/hetzner/Caddyfile:29` proxies one origin today). Loses Next's per-route code splitting, which is what makes the route budgets in [§8](#8-performance-and-quality-budgets) measurable at all | Rejected — strictly more moving parts for identical capability |
| C. Another full-stack framework (Remix / React Router 7 / TanStack Start) | Equivalent capability. Migration cost is the whole `web/` tree plus `web/Dockerfile` (`output: "standalone"` at `web/next.config.mjs:7` feeds `web/Dockerfile:34`) plus the Compose healthcheck (`docker-compose.yml:131-140`). No evidence of a benefit this product needs | Rejected — cost with no named benefit |
| D. Server-rendered non-React (SvelteKit, HTMX + templates) | Discards React 19.2.8, the 78 passing tests, and the reconnect/HITL logic that discovery flags as the highest-churn, highest-risk code (`00-DISCOVERY.md` "Git history and risk concentration") | Rejected |
| E. Next.js with `next.config` rewrites or Edge middleware instead of the route handler | `rewrites` cannot inject a per-request secret header. Edge middleware would move the key into the Edge runtime and cannot return an upstream `ReadableStream` with the same streaming guarantees. `route.ts:11` pins `runtime = "nodejs"` deliberately | Rejected |

### 1.3 Recommendation for Gate 2

**Confirm D-002 as binding**, with three constraints attached:

1. `web/app/api/[...path]/route.ts` remains the **sole** credential
   boundary. `runtime = "nodejs"` (`route.ts:11`) and
   `dynamic = "force-dynamic"` (`route.ts:10`) are not to be changed. Any
   future React Server Component that fetches `API_INTERNAL_BASE` directly
   would create a *second* credential path; that is explicitly out of scope
   and would need its own ADR.
2. The proxy gains **request logging and a CSP** before rollout (planned;
   closes the `00-DISCOVERY.md` operational gaps "no proxy observability"
   and "there is no dependency-audit gate or CSP"). See
   [§9](#9-degradation-honesty-and-frontend-observability) and
   [`05-MIGRATION.md`](05-MIGRATION.md#3-ci-and-operational-additions-planned).
3. Framework-level migrations stay out of this revamp: Tailwind 4,
   TypeScript 7, and Turbopack (`web/package.json:11` pins
   `next build --webpack`) each need their own ADR. This restates R-15.

Data fetching stays **client-side through `/api`** for the whole revamp.
Server-rendering the conversation list would be faster, but it needs a second
credential path and would fork the MT-01 identity seam in
[§10](#10-identity-ready-seams-for-mt-01). Server Components are used only
for static shell chrome, which is where the bundle savings are anyway.

An ADR recording this confirmation is a **planned** Gate 4 deliverable
(`docs/decisions/0055-frontend-architecture-confirmation.md`, number
provisional — 0054 is the current highest).

---

## 2. Route and app structure

D-003 holds: **no new URLs are invented.** There are two user-facing route
templates and one internal proxy route, exactly as today
(`web/app/page.tsx`, `web/app/c/[id]/page.tsx`, `web/app/api/[...path]/route.ts`).
What changes is the shell around them and the missing framework boundaries.

### 2.1 Target file layout (planned)

```text
web/app/
  layout.tsx                    root <html lang="en"> — theme script, font vars,
                                color-scheme, skip link target
  globals.css                   @tailwind layers + import tokens.css
  tokens.css                    semantic custom properties (see §6)
  icon.svg                      fixes the /favicon.ico 404 that costs Lighthouse
                                Best Practices on every audited state
  not-found.tsx                 product 404 with navigation and an <h1>
                                (today: framework default only)
  global-error.tsx              last-resort boundary (today: framework default)
  (workspace)/
    layout.tsx                  the shell: header, IdentitySlot, responsive
                                conversation rail/drawer, exactly one <main>
    page.tsx                    "/"  — landing composer
    error.tsx                   shell-level recovery boundary
    c/[id]/
      page.tsx                  "/c/[id]" — conversation workspace
      loading.tsx               route-level skeleton (replaces the ad-hoc
                                "Loading conversation…" string)
      error.tsx                 route-level recovery boundary
  api/[...path]/route.ts        UNCHANGED contract; gains logging (planned)
```

`(workspace)` is a route group: it introduces no URL segment, so `/` and
`/c/[id]` are byte-identical to today. It exists so the shell is a real
layout instead of a component every page must remember to wrap
(`web/app/page.tsx:54` and `web/app/c/[id]/page.tsx:12` both wrap manually
today, which is how the missing `<main>` went unnoticed across every state).

Four of these files close confirmed baseline failures directly:
`not-found.tsx` closes the "framework 404 lacks product recovery" finding
(`baseline/README.md` state matrix); `icon.svg` closes the favicon 404;
`(workspace)/layout.tsx` closes `landmark-one-main` and `region`, which fail
in **all twelve** audited states (`baseline/README.md` axe table);
`loading.tsx` replaces the string at `web/app/c/[id]/page.tsx:19`.

### 2.2 State variants per route

`/` — landing composer.

| Variant | Source of truth | Note |
|---|---|---|
| rail loading / empty / populated / error | `GET /conversations` (`src/api/routes.py:560-600`) | error must not blank the composer |
| composer empty / filled / over-length | client; bound is `MAX_QUERY_LEN = 8000` (`src/api/schemas.py:17`, enforced `schemas.py:36-40`) | counter is shown before submit, not after a 422 |
| submitting | in-flight `POST /conversations` then `POST /research` | two writes, both rate-limited (`src/api/routes.py:545`, `routes.py:157`) |
| submit failed | normalized `ApiFailure` (§3.4) | a failed submit can leave an orphan conversation — see honesty rule H7 |
| handoff | `router.push('/c/{id}?job={job_id}')` (`web/app/page.tsx:37-40`) | the `?job=` contract, MUST-KEEP #1 |

`/c/[id]` — conversation workspace.

| Variant | Source of truth | Note |
|---|---|---|
| loading / not found / load error | `GET /conversations/{id}` (`routes.py:603-624`) | 404 also means "not yours" (`routes.py:59-84`) |
| empty thread | `ConversationDetail.jobs == []` (`schemas.py:194-201`) | |
| populated thread | `jobs[]` with full report bodies (`schemas.py:184-191`) | unpaginated; render collapsed |
| no active job | no `?job=` | |
| attached — status unknown | `GET /research/{id}` in flight | honest interim state |
| attached — running, no checkpoint observed | `JobDetail.status == running`, no `node_completed` this session | the reload case |
| attached — running, checkpoint observed | last `node_completed` on the open stream (`src/api/runner.py:952-956`) | never persisted |
| attached — reconnecting | `EventSource.readyState === CONNECTING` | browser owns retry |
| attached — awaiting review | `status == pending_review`; plan from `JobDetail.plan` (`schemas.py:115-120`) or the `plan_ready` frame | |
| review submitted, not settled | `ReviewResponse.status` is always `pending_review` (`schemas.py:141-160`) | 200 ≠ resumed |
| review conflict | 409 `job_not_awaiting_review` (`routes.py:261-264`) | refetch and re-render |
| succeeded | `GET /research/{id}` after terminal frame | SSE never carries the report |
| failed, no report | `status == failed`, `result` empty | |
| failed, partial report retained | `status == failed`, `result` non-empty (`runner.py:1093`) | today hidden by `web/components/ReportView.tsx:13-29` |
| cancelled | `job_cancelled` / `status == cancelled` | only reachable at the review pause |
| expired / unknown job | stream 404 (`routes.py:429-431`) after `api_job_retention_sec` (default 86400, `src/config.py:307`) | |
| stream deadline | `stream_timeout` after `api_sse_max_duration_sec` (default 3600, `src/config.py:332`) | not handled today — see §11.2 |
| rate limited | 429 object detail (`src/api/auth.py:176-184`) | |
| unauthorized | 401 `missing_api_key` / `invalid_api_key` (`auth.py:507-516`) | proxy misconfiguration, not a user action |
| proxy misconfigured / upstream down | 503 `api_proxy_misconfigured` (`route.ts:70-74`), 502 `api_upstream_unavailable` (`route.ts:98-101`) | |

This table is the **canonical state matrix**. Storybook ([§5](#5-component-architecture-and-storybook))
and Playwright ([§7](#7-testing-strategy)) both index off it.

---

## 3. Typed API client layer

### 3.1 The frozen HTTP surface, endpoint by endpoint

Every row is an endpoint the frontend actually uses. "Web caller" is where
it is invoked today.

| Endpoint | Backend definition | Request / response schema | Web caller today |
|---|---|---|---|
| `POST /research` → 202 | `src/api/routes.py:127-212` | `ResearchRequest` `schemas.py:33-56`; `ResearchAccepted` `schemas.py:59-65` | `web/lib/api.ts:31-47` |
| `GET /research/{job_id}` → 200 | `routes.py:215-232` | `JobDetail` `schemas.py:98-124` | `web/lib/api.ts:99-105` |
| `POST /research/{job_id}/review` → 200 | `routes.py:235-322` | `ReviewRequest` `schemas.py:127-138`; `ReviewResponse` `schemas.py:141-161` | `web/lib/api.ts:111-127` |
| `GET /research/{job_id}/export?format=` → 200 | `routes.py:325-391` | `format` pattern `^(md\|pdf\|docx)$` `routes.py:341-345`; body is bytes | `web/components/ExportDropdown.tsx:51-52` (anchor, no fetch) |
| `GET /research/{job_id}/stream` → 200 SSE | `routes.py:394-520` | see §3.2 | `web/lib/api.ts:107-109` + `web/lib/useResearchStream.ts:121` |
| `POST /conversations` → 201 | `routes.py:523-557` | `ConversationCreateRequest` `schemas.py:171-181` (`MAX_TITLE_LEN = 80`, `schemas.py:168`); `ConversationDetail` `schemas.py:194-201` | `web/lib/api.ts:53-65` |
| `GET /conversations?limit=&offset=` → 200 array | `routes.py:560-600` | `ConversationListItem[]` `schemas.py:204-210`; `limit` 1..200, `offset` ≥0 (`routes.py:568-579`, bounds `src/api/conversations.py:35-36`) | `web/lib/api.ts:67-73` — **sends neither parameter** |
| `GET /conversations/{id}` → 200 | `routes.py:603-624` | `ConversationDetail` with every `ConversationJobSummary` (`schemas.py:184-191`) | `web/lib/api.ts:75-85` |
| `DELETE /conversations/{id}` → 204 | `routes.py:627-657` | no body | `web/lib/api.ts:87-97` |
| `GET /healthz` → 200 | `routes.py:780-827` | `HealthResponse` `schemas.py:213-247` | **not consumed by product UI**; only `web/tests/apiProxyRoute.test.ts:105` exercises it |

Notes that constrain the client:

- `POST /research` is **non-idempotent and potentially billable**, and the
  API has no idempotency key (`routes.py:179-197` creates a job and spawns
  the task unconditionally). MUST-KEEP #3.
- `POST /research` and `POST /conversations` share one rate-limit bucket
  (`routes.py:157` and `routes.py:545` both call `enforce_rate_limit`), so
  the landing-page flow costs **two** of `api_key_hourly_limit`
  (`src/config.py:196`, default 100; production sets 20 at
  `deploy/hetzner/compose.prod.yml:18`, i.e. **ten** fresh landing-page
  runs per hour).
- Ownership mismatch returns **404, never 403** (`routes.py:59-84`). The UI
  must never say "deleted" or "no permission" for a 404.
- Export 409s only when `job.result` is falsy (`routes.py:364-368`) — a
  *failed* job with a partial report **is** exportable. See H5.
- `GET /conversations` returns a bare array with no `total` / `has_more`.

### 3.2 The frozen SSE surface

The wire format is `event:` + `data:` JSON with no `id:` line
(`src/api/streaming.py:117-132`). The authoritative event list is the module
docstring at `src/api/streaming.py:13-35`. There is **no `node_started`** —
the runner emits only after a node returns.

| Event | Emitted at | Payload (live) | Payload (replay on attach) |
|---|---|---|---|
| `job_started` | `runner.py:986-990` | `{job_id, query}` | not replayed |
| `node_completed` | `runner.py:952-956` | `{node, state_delta}` — `state_delta` filtered to scalars only, `messages` dropped (`runner.py:947-951`) | **not replayed; no backlog** |
| `plan_ready` | `runner.py:409-414` | `{job_id, plan:{sub_questions, search_queries}}` | replayed on attach when `pending_review` (`routes.py:463-464`, payload `routes.py:838-854`, byte-identical by design) |
| `job_completed` | `runner.py:1278-1288` | `{job_id, iterations, quality_score, cost_usd, llm_calls, elapsed_sec}` — **no `status`** | `routes.py:857-867`: `{job_id, status, elapsed_sec, error, error_type, iterations, quality_score, cost_usd}` — **no `llm_calls`** |
| `job_failed` | `runner.py:1063-1072`, `1097-1108`, `1155-1166`, `1224-1235` | `{job_id, error, error_type, elapsed_sec}` | as above (`routes.py:857-867`) |
| `job_cancelled` | `runner.py:1128-1135` (`reason: "hitl_cancelled"`), `runner.py:1196-1199` (no `reason`) | `{job_id, elapsed_sec, reason?}` | as above (`routes.py:857-867`) |
| `heartbeat` | `streaming.py:135-142` | SSE **comment** `": heartbeat"` | n/a — invisible to `EventSource` |
| `stream_timeout` | `streaming.py:300-308` | `{job_id, reason, max_duration_sec, reconnect}` | server-generated; **not** a job outcome (`streaming.py:108-114`) |

Terminal names and their asserted job statuses are pinned server-side at
`streaming.py:89-103`; the attach-time replay names come from
`routes.py:830-835`.

Invariants the client must obey:

- **The report body never arrives over SSE.** Every terminal frame must be
  reconciled with `GET /research/{id}` (already done at
  `web/lib/useResearchStream.ts:92-106`; keep it).
- **There is no replay backlog and no `Last-Event-ID` contract.** Redis
  pub/sub drops messages with no subscriber (`routes.py:444-454`). A
  reconnect therefore *cannot* reconstruct missed `node_completed` frames.
- **`plan_ready` may arrive twice** on the in-memory path — deliberate, and
  documented at `routes.py:456-462`. The handler must be idempotent.
- **Unknown event names and unknown `state_delta` keys must be tolerated.**
  Node names are opaque strings; no fixed vocabulary may be assumed
  (this is also the standing constraint from `REVIEW.md` second-pass
  finding on the Direction C sketch).

### 3.3 Where types live (planned)

```text
web/contract/
  openapi.json                  committed snapshot of the FastAPI document
  fixtures/                     recorded response bodies, one file per case
    job.pending_review.json     job.running.json      job.succeeded.json
    job.failed_partial.json     job.cancelled.json
    conversations.list.json     conversations.detail.json
    error.401.json  error.404.json  error.409.json
    error.422.json  error.429.json  error.502.json  error.503.json
  sse/                          recorded frame scripts, one per scenario
    live_success.jsonl  live_failure.jsonl  plan_review.jsonl
    replay_terminal.jsonl  reconnect_gap.jsonl  stream_timeout.jsonl

web/lib/api/
  generated/schema.d.ts         openapi-typescript output; NEVER hand-edited
  models.ts                     app-facing aliases into generated/schema.d.ts
  events.ts                     SSE overlay — handwritten, see §3.2
  errors.ts                     the single ApiFailure normalization type
  client.ts                     typed fetch wrappers (AbortSignal + timeout)
  index.ts                      public surface; the only import UI code uses
```

`models.ts` aliases rather than redeclares:
`export type JobDetail = components["schemas"]["JobDetail"]`. That makes a
backend field change a **compile error**, not a runtime surprise — which is
the failure mode the current handwritten `web/lib/types.ts:1-7` explicitly
accepts ("If the schemas drift, contract tests on the Python side catch the
producer end").

`events.ts` stays handwritten because SSE payloads, export bodies, and the
error shapes are **not** in the OpenAPI document — discovery already
established this (`00-DISCOVERY.md`, "JSON operations": ten operations,
thirteen schemas, no auth/401/404/409/429/SSE/export coverage). Generation
without the overlay is the false-confidence risk R-06.

### 3.4 One error normalization contract

There is no single backend error envelope. The observed shapes:

| Source | Shape | Citation |
|---|---|---|
| common | `{"detail": "job_not_found"}` | `routes.py:229`, `routes.py:257`, `routes.py:430` |
| conflict, with state | `{"detail": "job_not_awaiting_review (status=running)"}` | `routes.py:262-264`; export: `routes.py:366-368` |
| unauthorized | `{"detail": "missing_api_key"}` + `WWW-Authenticate` | `auth.py:507-509`, `auth.py:515-516` |
| rate limited | `{"detail": {"error": "rate_limited", "key_id", "limit_per_hour"}}` + `Retry-After` | `auth.py:176-184` |
| validation | `{"detail": [ {loc, msg, type}, ... ]}` | FastAPI default for `schemas.py` bounds |
| proxy | `{"detail": "api_proxy_misconfigured"}` 503, `{"detail": "api_upstream_unavailable"}` 502 | `route.ts:70-74`, `route.ts:98-101` |
| transport | no body at all — network failure, abort, timeout | — |

Today `web/lib/api.ts:129-137` handles only the string case and falls back
to `JSON.stringify(body)`. **A rate-limited user therefore sees raw JSON.**

Target: one discriminated union in `errors.ts`, produced by one function.

```ts
type ApiFailure =
  | { kind: "unauthorized";        status: 401 }
  | { kind: "not_found";           status: 404 }
  | { kind: "conflict";            status: 409; state?: string }
  | { kind: "rate_limited";        status: 429; retryAfterSec: number; limitPerHour?: number }
  | { kind: "validation";          status: 422; fields: FieldIssue[] }
  | { kind: "upstream_unavailable"; status: 502 }
  | { kind: "proxy_misconfigured";  status: 503 }
  | { kind: "server_error";        status: number }
  | { kind: "offline" }
  | { kind: "timeout" }
  | { kind: "cancelled" }
  | { kind: "unknown";             status: number | null };
// every variant additionally carries: { message: string; raw: unknown; requestId?: string }
```

`message` is the **user-facing sentence**; `raw` is retained for the
diagnostics disclosure ([§9](#9-degradation-honesty-and-frontend-observability)).
Raw `error_type` strings from the backend (`schemas.py:110`) are shown in
disclosure only, never as the primary message — this answers discovery's
"can wait" question 3 in the frontend's favour and is flagged for Gate 2.

### 3.5 Drift detection without a live backend in CI

Four independent checks, none of which needs a running API:

1. **Producer snapshot (Python CI, existing job).** A test asserts
   `create_app().openapi() == json.load(open("web/contract/openapi.json"))`.
   Changing `src/api/schemas.py` without regenerating the snapshot fails
   the existing `tests` job. Pure in-process; no network. *(planned)*
2. **Consumer compile check (web CI).** `openapi-typescript` regenerates
   `web/lib/api/generated/schema.d.ts` from the committed snapshot; CI fails
   if the regenerated file differs from the committed one, and any field
   change that UI code depends on additionally fails `npm run typecheck`.
   *(planned)*
3. **Fixture parse tests (Vitest).** Every file in `web/contract/fixtures/`
   is parsed by the typed client and validated by a Zod schema derived from
   the generated types. This is what catches the parts OpenAPI does not
   describe: error envelopes, export headers, and SSE frames. *(planned)*
4. **SSE name pinning (both sides).** A Python test asserts the event-name
   set equals `TERMINAL_EVENT_NAMES ∪ {job_started, node_completed,
   plan_ready}` plus `STREAM_TIMEOUT_EVENT` (`streaming.py:75`,
   `streaming.py:89-114`), and a Vitest test asserts `events.ts` declares
   exactly that set. Adding a backend event breaks both. *(planned)*

Fixtures are **recorded**, not invented: a repo script
(`web/contract/record.sh`, planned) replays the seeded local stack from
[`baseline/fixtures/seed-local-baseline.sh`](baseline/fixtures/seed-local-baseline.sh)
and writes the response bodies verbatim. It is run by hand, with
`ANTHROPIC_API_KEY=local-preview-disabled`, and never in CI. Each fixture
carries a header comment with the commit it was recorded at.

---

## 4. State management for the job lifecycle

### 4.1 The chosen approach

| Concern | Choice | Why |
|---|---|---|
| Idempotent JSON reads (conversation list, conversation detail, job detail) | **TanStack Query 5.102.2** | Gives cache/dedupe/stale-refetch/`refetchInterval` — the poll fallback in §4.4 is one line. No hand-rolled cache. |
| Idempotent JSON writes (`createConversation`, `deleteConversation`, `reviewPlan`) | TanStack Query `useMutation`, `retry: false` | Invalidation is declarative and correct. |
| **`POST /research`** | **Deliberately outside TanStack Query.** A plain function called from the job machine, guarded by a submission token | Query's default `networkMode: "online"` **pauses** a mutation while offline and **resumes it when connectivity returns** — that is an automatic replay of a paid, non-idempotent submission. This is R-01 with a library making it worse. Keeping it out is simpler than remembering `networkMode: "always"` forever. The existing no-double-submit tests (`web/tests/HomePage.test.tsx`) survive unchanged. |
| Job lifecycle | **A `useReducer` finite-state machine** in `web/lib/job/machine.ts`, exposed via a `JobRunProvider` context | The machine is one per route instance; it does not need a global store. A pure reducer is exhaustively testable as a transition table with zero mocking. |
| Not chosen: XState | ~15 KB gzip for a machine with 9 states; Redux/Zustand: a global store for per-route state; SWR: TanStack Query has the better mutation controls we need to switch off | |
| Plan-editor form | **React Hook Form 7.86 + Zod 4.4** | Dynamic arrays with per-field errors is exactly its remit. Not used for the trivial question textarea. |

### 4.2 The machine

```text
idle
 └─ submit ─────────► submitting ──error──► submit_failed  (terminal for this attempt;
                          │                                 retry is a NEW run, never automatic)
                          └─ 202 ─► attaching

attaching  (always GET /research/{id} FIRST, then open EventSource)
 ├─ 404 ──────────► unavailable        "no longer available"
 ├─ pending_review ► awaiting_review   plan from JobDetail.plan
 ├─ pending|running► live { checkpoint: unknown }
 └─ terminal ─────► settled

live ─ node_completed ─► live { checkpoint: <node>, observedAt }
     ─ EventSource error, readyState=CONNECTING ─► live { reconnecting: true, checkpoint: unknown }
     ─ stream_timeout ─► reopen stream immediately (do not wait for browser retry)
     ─ EventSource error, readyState=CLOSED ────► unavailable
     ─ plan_ready ─────► awaiting_review
     ─ terminal frame ─► reconciling ─ GET /research/{id} ─► settled

awaiting_review ─ POST review 200 ─► resolving   (status is still pending_review — see §11.5)
                ─ 409 ─────────────► attaching   (refetch truth, re-render)
resolving ─ next SSE frame or poll ─► live | settled
```

### 4.3 Reload-safe resumption

The URL keeps the contract: `/c/{conversation_id}?job={job_id}` is the only
persisted handle (`web/app/page.tsx:37-40`, read at
`web/app/c/[id]/page.tsx:55`). Nothing is stored in `localStorage` or
`sessionStorage` — a job id in browser storage would outlive its server row
(`api_job_retention_sec`, `src/config.py:307`) and produce phantom runs.

The change from today: **`GET /research/{id}` runs before the EventSource is
opened.** Today `attach` opens the stream first
(`web/lib/useResearchStream.ts:238-253`) and learns the job's status only
from whatever frame arrives. GET-first fixes three things at once:

- An **expired** job renders a truthful "this run is no longer available"
  from a clean 404 (`routes.py:229`), instead of arriving via the browser's
  failed-connection path (`useResearchStream.ts:171-188`).
- A **`pending_review`** job renders the plan from `JobDetail.plan`
  (`schemas.py:115-120`) without depending on the ADR-0053 replay.
- A **`running`** job renders "running · no checkpoint observed" instantly
  rather than showing nothing until the next node finishes (which can be
  tens of seconds).

`GET /research/{id}` is free and read-only (`routes.py:215-232`) — it costs
one request and no model spend.

### 4.4 SSE reconnect and the last-observed-checkpoint rule

This is the binding constraint from [`REVIEW.md`](REVIEW.md) and it is
implemented as four hard rules in the reducer:

1. `checkpoint` is set **only** by a `node_completed` frame received on the
   currently-open EventSource in this browser session.
2. `checkpoint` is reset to `unknown` on every `open` of a new EventSource —
   including the browser's own automatic retry — because there is no replay
   backlog (`routes.py:444-454`) and no `Last-Event-ID` contract
   (`streaming.py:117-132` writes no `id:` line).
3. `checkpoint` is **never persisted** across a reload and never derived
   from `JobDetail`. `JobDetail` has no node field (`schemas.py:98-124`).
4. Terminal copy is `"failed after <checkpoint>"` when one was observed and
   plain `"failed"` otherwise. **Never** "failed in <node>": no terminal
   frame carries a node — not the live payloads (`runner.py:1063-1072`) nor
   the replay payload (`routes.py:857-867`).

Two additions the current client lacks:

- **A `stream_timeout` listener.** `web/lib/useResearchStream.ts:59-66`
  registers six event names; `stream_timeout` is not among them, so the
  frame is dropped and the client waits for the browser's default retry
  after the server closes at `api_sse_max_duration_sec`. The machine
  registers it and reopens immediately.
- **A liveness poll.** Heartbeats are SSE *comments* (`streaming.py:142`)
  and are invisible to `EventSource`, so a client **cannot distinguish an
  idle stream from a dead one**. While the job is non-terminal, the job
  detail query runs with `refetchInterval: 20_000`, backing off to 60 s
  after five unchanged polls. That is the safety net for a silently dropped
  connection; it is read-only and costs no model spend.

Progress is rendered as job status + elapsed + last update + last observed
checkpoint. **No determinate percentage**, because there is no denominator
— `node_completed` gives no total (`runner.py:952-956`).

### 4.5 HITL plan review

- Plan source: `plan_ready` frame (`runner.py:409-414`) or `JobDetail.plan`
  (`schemas.py:115-120`), whichever arrives first; the handler is idempotent
  because the frame can legitimately repeat (`routes.py:456-462`).
- Client bounds mirror server bounds exactly — Zod schema derived from
  `MAX_PLAN_ITEMS = 20` and `MAX_PLAN_ITEM_LEN = 500`
  (`src/api/schemas.py:26-27`), so over-length input is prevented in the
  form rather than surfaced as a 422.
- `revise` requires a plan (`routes.py:265-269`); the form cannot submit
  `revise` without one.
- **The 200 does not mean resumed.** `ReviewResponse.status` is always
  `pending_review` by design (`schemas.py:141-160`); the machine moves to
  `resolving` and waits for an SSE frame or a poll.
- **409 means the truth moved.** `job_not_awaiting_review`
  (`routes.py:261-264`) is not an error to shout about — it is a signal to
  refetch and re-render. Most likely causes: another tab resolved it, or
  `api_hitl_timeout_sec` fired (default 1800 s, `src/config.py:354`;
  produces `error_type = "hitl_timeout"`, `runner.py:1053-1057`).
- **Cancel exists only here.** There is no cancel endpoint after approval.
  The review surface says so in plain words rather than offering a control
  that will 409.

### 4.6 Conversation list and detail

- List: `useQuery(['conversations', principal, {limit, offset}])` sending
  **explicit `limit` and `offset`** (`routes.py:568-579`), which the current
  client omits entirely (`web/lib/api.ts:67-73`) and therefore silently
  truncates at `DEFAULT_LIST_LIMIT = 50` (`src/api/conversations.py:35`).
- Because the contract has no `total` / `has_more`, pagination is
  **"Load more", hidden when a page returns fewer than `limit` rows.** No
  page count, no "showing 50 of N" — the API cannot support either.
- Detail: one query per conversation. Report bodies come down in full
  (`schemas.py:184-191`), so turns render collapsed and Markdown is parsed
  lazily on expand. Virtualization is deferred until measured (R-11).
- Delete: `useMutation` with a confirmation dialog, optimistic removal, and
  rollback on failure. Copy names exactly what the API deletes.

---

## 5. Component architecture and Storybook

### 5.1 Layers

```text
web/lib/tokens.ts        typed token names (§6)
web/components/
  primitives/            Button Field Textarea Disclosure Dialog Menu
                         StatusBadge Skeleton VisuallyHidden ScrollRegion
                         — no data hooks, no imports from lib/api
  patterns/              TraceSpine PlanEditor ReportReader MetricsStrip
                         ExportMenu ConversationList EmptyState FailureNotice
                         — plain props in, no data hooks
  features/              ComposerCard  ActiveRunPanel  ThreadTimeline
                         ConversationRail
                         — own their queries and the job machine
web/app/(workspace)/     routes wire features together
```

**The rule that makes Storybook cheap:** primitives and patterns take plain
props and never call a hook that fetches. Every state they can be in is
reachable by passing props, so their stories need no MSW and no network.
Only `features/` stories need MSW, and only for JSON — SSE is driven by the
deterministic stub described in §7.

This layering also removes the concrete duplication discovery found:
conversation loading exists twice (`web/components/ConversationThread.tsx:38-59`
and `:61-93`), sidebar loading exists twice
(`web/components/ConversationSidebar.tsx:26-34` and `:36-57`), and current
vs. historical Markdown rendering diverge
(`ReportView.tsx:39-48` vs `ConversationThread.tsx:301-306`). One
`ReportReader` and one query per resource collapse all three.

### 5.2 Storybook setup (planned)

Storybook 10.5.10 with `@storybook/nextjs-vite`, plus `addon-a11y` (axe per
story) and the Vitest addon so stories execute as component tests in the
same run. The production Next webpack build (`web/package.json:11`) stays
authoritative for what ships; Storybook is documentation and a test host.

Global toolbar decorators, applied to every story: **theme** (light / dark /
forced-colors), **viewport** (320 / 412 / 768 / 1440), and
**reduced-motion**. That means the degraded-state matrix is covered at every
breakpoint without writing 4× the stories.

### 5.3 The degraded-state matrix as stories

Gate 3 requires state evidence for the merged foundation. Every row of the
§2.2 table gets at least one story. Explicit coverage, grouped:

| Group | Stories |
|---|---|
| ConversationRail | `Loading` `Empty` `Populated` `PopulatedWithMore` `Error` `DeleteConfirm` `Drawer/Closed` `Drawer/Open` |
| ComposerCard | `Empty` `Filled` `NearLimit` `OverLimit` `Submitting` `RateLimited` `Unauthorized` `UpstreamDown` `ProxyMisconfigured` |
| TraceSpine | `NoJob` `StatusUnknown` `RunningNoCheckpoint` `RunningWithCheckpoint` `Reconnecting` `StreamTimeout` `AwaitingReview` `Succeeded` `Failed` `FailedAfterCheckpoint` `Cancelled` `Unavailable` |
| PlanEditor | `Default` `Edited` `EmptyLists` `MaxItems` `ItemAtMaxLength` `Submitting` `Conflict409` `HitlTimedOut` |
| ReportReader | `Empty` `Short` `LongWithHeadings` `WithWideTable` `WithCodeBlocks` `PartialFromFailedRun` |
| MetricsStrip | `AllPresent` `AllNull` `PartialFailureMetrics` |
| ExportMenu | `Closed` `Open` `KeyboardFocus` `UnavailableNoReport` |
| FailureNotice | one per `ApiFailure.kind` (12 stories, §3.4) |
| Shell | `Skeleton` `NotFoundProduct` `NotFoundFramework` `ErrorBoundary` `SkipLinkFocused` |

Gate 3 artifact: a static Storybook build plus
`docs/revamp/evidence/gate-3/storybook-states.md` mapping **story ID →
§2.2 state → baseline screenshot it replaces → axe result**. A state in
§2.2 with no story is a Gate 3 blocker.

---

## 6. Styling and token integration

`docs/revamp/03-DESIGN-BRIEF.md` is authored in Phase 2 on branch
`docs/frontend-revamp-phase2-brief`. **This section defines only the
mechanism; the brief owns the values.** Nothing here duplicates or
pre-empts it, and nothing here blocks on it.

### 6.1 The contract between Phase 2 and Phase 3

**Phase 2 supplies** a table of semantic roles with a light value and a dark
value each, plus scales for space, radius, type, duration, and easing.
**Phase 3 guarantees** the names, the file locations, and that the values
are consumed in exactly one place.

Naming is fixed here so the brief can be written against it:

```text
--color-{role}        canvas surface raised ink ink-muted rule
                      primary primary-ink accent review critical
                      focus success warning
--space-{n}           0 1 2 3 4 6 8 12 16 24
--radius-{name}       sm md lg full
--font-{role}         display ui data
--text-{step}         xs sm base lg xl 2xl 3xl
--duration-{name}     instant fast base slow
--ease-{name}         standard enter exit
```

### 6.2 Mechanism

1. **`web/app/tokens.css`** — the only file containing literal values.
   Declares `:root { color-scheme: light dark; --color-canvas: …; }`, a dark
   block under **both** `@media (prefers-color-scheme: dark)` and
   `:root[data-theme="dark"]`, and a light override under
   `:root[data-theme="light"]`. Supporting both is what allows a user theme
   control, which the baseline lacks (`00-DISCOVERY.md`: dark mode exists
   through `prefers-color-scheme` with no user control, persistence, or
   `color-scheme` declaration).
2. **`web/lib/tokens.ts`** — a typed module that maps names to
   `var(--…)` references and exports the union types:
   ```ts
   export const color = { canvas: "var(--color-canvas)", /* … */ } as const;
   export type ColorToken = keyof typeof color;
   ```
   No hex values here. It is the single source of *names*.
3. **`web/tailwind.config.ts`** — builds `theme.extend.colors`, `spacing`,
   `borderRadius`, `fontFamily`, and `transitionDuration` **from
   `tokens.ts`**, so a Tailwind class and a CSS variable can never disagree.
   `darkMode` changes from `"media"` (`web/tailwind.config.ts:4`) to
   `["class", '[data-theme="dark"]']`.
4. **Enforcement.** A Vitest test parses `tokens.css` and asserts every name
   in `tokens.ts` resolves to a declared custom property in both themes
   (and vice versa — orphan properties fail too). An ESLint
   `no-restricted-syntax` rule rejects literal hex/rgb/hsl colours in
   `app/` and `components/`, with `tokens.css` the only exemption.
5. **Fonts.** `next/font/local` with subset woff2 and a metric-matched
   `size-adjust` fallback so the swap causes no shift (CLS budget in §8).
   Faces and weights are the brief's call; the loading mechanism and the
   ≤120 KB total budget are this document's.
6. **Tailwind stays on 3.4.19.** Tailwind 4 is a separate ADR (R-15,
   `01-RESEARCH.md` "Why not upgrade everything first").

If the brief renames a role or changes a value, **only `tokens.css` and
`tokens.ts` change.** No component is touched. That is the whole point of
the contract.

---

## 7. Testing strategy

### 7.1 Tiers

| Tier | Tool | Scope | Runs |
|---|---|---|---|
| Unit | Vitest 4.1.11 | `lib/api/*` normalizers, the job reducer as an exhaustive transition table, token/Tailwind consistency | every PR |
| Component | Vitest + Testing Library 16.3.2 | primitives and patterns; behaviour and a11y, not snapshots | every PR |
| Story | Storybook + Vitest addon + `addon-a11y` | every story renders and passes axe | every PR |
| Integration | Vitest + MSW 2.15.0 | features against recorded fixtures (§3.3) | every PR |
| Contract | Vitest + `web/contract/` | fixture parse, generated-type diff, SSE name pinning | every PR |
| E2E | Playwright 1.62.1 | the five-step vertical slice against the seeded local stack | every PR (chromium) / nightly (full matrix) |
| Accessibility | `@axe-core/playwright` 4.13.0 | every §2.2 state | with E2E |
| Budgets | repo script + Lighthouse CI 0.15.1 | §8 | budgets every PR; LHCI nightly |

### 7.2 SSE in tests

jsdom has no `EventSource`, and MSW's SSE support does not reach a polyfill
the app never installs. The existing suite already solves this by stubbing
`EventSource` in tests, and that approach is kept and formalised: a
`FakeEventSource` in `web/tests/support/` is driven by the `.jsonl` frame
scripts in `web/contract/sse/`, so unit, component, and integration tiers
replay **recorded** frames rather than invented ones. Scenarios that must
exist: live success, live failure, plan review then approve, terminal
replay on attach, reconnect with a gap (proving no checkpoint is invented),
and `stream_timeout` followed by a reopen.

For Playwright, SSE comes from the real seeded stack, plus route
interception for the two failures a seeded stack cannot produce on demand —
the interrupted 200 stream (already proven at
[`baseline/fixtures/capture-baseline.spec.ts:63-76`](baseline/fixtures/capture-baseline.spec.ts))
and the `stream_timeout` frame.

### 7.3 Playwright against the seeded local stack

The Gate 1 fixtures are promoted, not rewritten:
[`baseline/fixtures/seed-local-baseline.sh`](baseline/fixtures/seed-local-baseline.sh)
becomes `web/e2e/fixtures/seed.sh`, extended with rows for the states it
does not yet cover (rate-limited, unauthorized, stream-timeout). It keeps
its current safety properties: idempotent upserts of `baseline-*` records
only, Redis leases so the redriver does not reclaim synthetic non-terminal
jobs, and **no call to `POST /research`**.

Projects: `chromium`, `firefox`, `webkit`, plus `Pixel 7` and `iPhone 15`
device profiles. `ANTHROPIC_API_KEY=local-preview-disabled` throughout, as
in the baseline (`baseline/README.md` "Test data and safety").

**The one paid-path rule:** the "new question" journey never submits to a
real model. The submit + stream leg runs against route interception; the
assertion that matters is *exactly one* `POST /api/research` per intentional
submission, counted at the interceptor. That is the automated proof for
R-01 and MUST-KEEP #3.

### 7.4 axe in CI

`@axe-core/playwright` with WCAG 2 A/AA + 2.1 A/AA + 2.2 AA + best-practice
tags — the same tag set the baseline used, so results are directly
comparable to [`baseline/axe/`](baseline/README.md).

The gate asserts **zero** violations for the six rules the baseline
currently fails: `landmark-one-main`, `region`, `aria-allowed-role`,
`listitem`, `color-contrast`, `page-has-heading-one`. Any other rule may be
suppressed only via a checked-in `web/e2e/axe-allowlist.json`, which starts
empty and requires a written justification per entry in review.

Automation cannot establish keyboard order, focus restoration, announcement
quality, or screen-reader comprehension. Those stay **manual Gate 4
evidence** — this is unchanged from `baseline/README.md`.

### 7.5 What is added to `.github/workflows/ci.yml` (planned)

The existing `web` job (`.github/workflows/ci.yml:168-197`) does typecheck,
lint, test, build. Additions:

| Change | Job | Closes |
|---|---|---|
| `npm run test -- --coverage` with thresholds seeded at the measured value and ratcheted | `web` (extend) | `00-DISCOVERY.md` missing tier "coverage collection and thresholds" |
| `npm audit --audit-level=high` | `web` (extend) | gap "no dependency-audit gate" |
| `npm run budgets` (build + route-budget check) uploading `budget-report.md` | `web` (extend) | gap "no CI budget exists" |
| Storybook static build + story tests, artifact uploaded | `web-storybook` (new) | missing tier "Storybook component/state/interaction documentation" |
| Compose up (invalid model key) → seed → Playwright + axe → upload traces/screenshots/axe JSON | `web-e2e` (new) | missing tiers "Playwright projects", "component and route axe assertions" |
| `docker build ./web` + `docker run` + probe `/` and `/api/healthz` against a stub upstream | `web-image` (new) | gap "CI builds only the API image, not the web image/runtime" |
| `docker compose -f docker-compose.yml -f deploy/hetzner/compose.prod.yml config --quiet` with dummy env | `docker-build` (extend) | gap "CI does not validate the production Compose overlay" |
| Lighthouse CI against the seeded stack with §8 assertions | nightly workflow | missing tier "Lighthouse CI and route-size budgets" |

E2E and Lighthouse are the slow tiers; only chromium E2E runs per PR, the
full browser matrix and LHCI run nightly, so PR wall-clock stays bounded.

---

## 8. Performance and quality budgets

### 8.1 Route JavaScript budgets

Anchored to the retained baseline (`baseline/README.md` "Bundle baseline"),
which is measured gzip from the production build and route manifests.

| Scope | Baseline (gzip) | Budget (gzip) | Headroom |
|---|---:|---:|---:|
| `/` first-load JS, excl. polyfill | 137,272 B (134.1 KB) | **145 KB** | +10.9 KB |
| `/c/[id]` first-load JS, excl. polyfill | 184,745 B (180.4 KB) | **195 KB** | +14.6 KB |
| Shared framework/runtime chunk | — (subset of the above) | **120 KB** | — |
| All emitted CSS | 4,288 B (4.2 KB) | **12 KB** | +7.8 KB |
| Total transferred JS on a settled report route, incl. lazy chunks | — | **240 KB** | — |
| All self-hosted font files (woff2, subset) | 0 B | **120 KB** | — |

The headroom is deliberately tight and it is a forcing function. TanStack
Query is ~13 KB gzip; React Hook Form ~9 KB; Zod ~14 KB. Only Query fits in
`/`'s headroom, so **RHF + Zod must be dynamically imported by the plan
editor** and Radix primitives must be imported per-component, never as a
barrel. If a budget cannot be met, the correct response is a documented
budget change at review — not a silent breach.

### 8.2 Lab performance targets

Baseline Lighthouse numbers are single local lab runs on the seeded stack,
not field p75 (`baseline/README.md`). Budgets are therefore **regression
guards against the same lab setup**, and field Core Web Vitals SLOs stay
deferred until real traffic exists (`01-RESEARCH.md` performance section).

| Metric | Mobile baseline (worst) | Mobile budget | Desktop baseline (worst) | Desktop budget |
|---|---:|---:|---:|---:|
| LCP | 2.38 s | **≤ 2.50 s** | 0.51 s | **≤ 1.20 s** |
| TBT | 56 ms | **≤ 150 ms** | 0 ms | **≤ 50 ms** |
| CLS | 0 | **≤ 0.02** | 0 | **≤ 0.02** |
| Lighthouse Performance | 98 | **≥ 95** | 100 | **≥ 98** |
| Lighthouse Accessibility | 94 (plan review) | **100** | 98 | **100** |
| Lighthouse Best Practices | 96 | **≥ 100** | 96 | **≥ 100** |

Accessibility 100 and Best Practices 100 are reachable, not aspirational:
the accessibility gap is `landmark-one-main` plus the plan-review
`role="log"` / `listitem` conflict (`web/components/EventLog.tsx:31-52`),
and the Best Practices gap is the `/favicon.ico` 404 — one file
(`app/icon.svg`). Both are fixed by §2.1.

States audited: landing, empty conversation, populated report, plan review
(the four with retained baseline JSON), plus a new 320 px reflow audit.

### 8.3 The mobile narrow-strip repair

**Root cause, precisely.** `web/components/ConversationsShell.tsx:22` is
`flex h-screen`; `web/components/ConversationSidebar.tsx:89` is
`flex h-full w-64 shrink-0`. The rail is 256 px at every viewport with no
breakpoint. At the 412 px audit width the remainder is 156 px, and
`px-6` padding on the content column (`ConversationThread.tsx:200`,
`:189`, `:248`) removes 48 more — roughly **108 px of usable work
surface**, which is what every mobile screenshot shows. A second, quieter
cause: `web/components/ConversationsShell.tsx:27` is `flex-1` without
`min-w-0`, so the flex item's automatic minimum size prevents inner grids
from shrinking even when they have breakpoints — which is exactly the
"some internal grids have breakpoints, but the shell prevents them from
becoming useful" observation in `00-DISCOVERY.md`.

**The repair, specifically.**

1. Below `md` (768 px) the rail is **not in the layout at all.** The shell
   is one column; a labelled "Conversations" disclosure button in the
   header opens the list as an overlay drawer with focus trapping, Escape
   to close, and focus restored to the trigger (APG Dialog).
2. At `md` and above the shell is
   `grid grid-cols-[16rem_minmax(0,1fr)]` — CSS Grid rather than flex, so
   `minmax(0, 1fr)` removes the min-content floor by construction. The rail
   gains a collapse toggle whose state persists in `localStorage`.
3. The content column carries `min-w-0` regardless of layout mode.
4. Report tables are wrapped in a `ScrollRegion` primitive:
   `overflow-x: auto`, `tabindex="0"`, `role="region"` with an accessible
   name, so the **table** pans and the **page** does not (WCAG 1.4.10
   Reflow). The same primitive replaces the fixed
   `grid-cols-[5.5rem_10rem_1fr]` event rows at
   `web/components/EventLog.tsx:40`.
5. Horizontal padding moves to a `--space-*` token that steps down below
   `md`.

**The proof it worked.** A Playwright assertion at 320, 360, and 412 px on
every §2.2 state: `document.scrollingElement.scrollWidth <=
document.scrollingElement.clientWidth`. This fails today and must pass
after M1. Plus a 320 px Lighthouse audit and a screenshot diff against the
retained `baseline/screenshots/home-mobile-full.png` and
`conversation-populated-mobile-full.png`.

Lighthouse cannot catch this class of bug — it scored 98–99 on mobile while
the UI was unusable (`baseline/README.md`: "Lighthouse can measure a fast
page whose usable content is squeezed into a narrow strip"). The
no-horizontal-scroll assertion is the gate that actually holds.

### 8.4 Enforcement — a CI check, not an aspiration

**Bundle budgets.** `web/scripts/route-budgets.mjs` (planned) reads
`.next/app-build-manifest.json` and `.next/build-manifest.json` after
`npm run build`, gzips the file union per route entry, compares to
`web/budgets.json`, writes a Markdown table to `budget-report.md`, and
**exits non-zero on any breach**. A repo script rather than `size-limit`
because size-limit has no notion of Next route→chunk association, and
discovery specifically records that "the manifest association is not
currently generated as a stable report". The report is uploaded as a CI
artifact on every run so a PR shows the delta, not just pass/fail.

**Lighthouse budgets.** `lhci autorun` with `assert.assertions` encoding
§8.2 per state and form factor, run nightly against the seeded stack.
Nightly rather than per-PR because it needs the full Compose stack; a
regression is caught within a day and blocks the next Gate 3/4 evidence
run.

**Reflow.** The `scrollWidth <= clientWidth` assertion is an ordinary
Playwright expectation in the per-PR chromium E2E job.

**Ratchet rule.** Budgets may only move in a PR that says why, in the PR
body, and updates `web/budgets.json` in the same commit. No environment
variable or flag may skip the check.

---

## 9. Degradation honesty and frontend observability

### 9.1 Honesty rules

These are testable rules, each with the contract fact that forces it.

| # | Rule | Because |
|---|---|---|
| H1 | Never display a "current" or "in-progress" stage. Only *last observed completed checkpoint*. | Only `node_completed` exists; there is no `node_started` (`streaming.py:25-29`), and it fires *after* the node returns (`runner.py:952-956`). |
| H2 | After any reload or reconnect the checkpoint is **unknown** until a new frame arrives, and the UI says so. | No replay backlog (`routes.py:444-454`), no `id:`/`Last-Event-ID` contract (`streaming.py:117-132`). |
| H3 | Failure copy is "failed after \<checkpoint\>" or plain "failed". Never "failed in \<node\>". | No terminal payload carries a node (`runner.py:1063-1072`, `routes.py:857-867`). |
| H4 | No determinate percentage or progress bar. Job status, elapsed, last update, last observed checkpoint only. | No denominator exists in any frame. |
| H5 | A `failed` job with a non-empty `result` shows the report, labelled "partial result from a failed run", **with export available**. | `routes.py:364-368` 409s only on a falsy `result`; `runner.py:1093` deliberately retains the partial report. Today `ReportView.tsx:13-29` returns early and hides it. **Flagged for Gate 2** — this resolves discovery "can wait" question 1. |
| H6 | `POST /research` is never retried automatically — not by the client, not by a query library, not after regaining connectivity. Any retry is an explicit user action, labelled as starting a **new** run. | No idempotency key (`routes.py:179-197`). R-01. |
| H7 | A failed first submission that already created a conversation says so, and offers the orphan thread rather than silently leaving it in the rail. | `web/app/page.tsx:33-36` creates the conversation before submitting; both writes consume rate-limit budget. |
| H8 | A 404 is rendered as "not available", never "deleted" or "no permission". | 404 covers both missing and not-yours, by design (`routes.py:59-84`). |
| H9 | Success is only claimed after `GET /research/{id}` confirms it. | SSE never carries the report; the live `job_completed` frame does not even carry `status` (`runner.py:1278-1288`). |
| H10 | If health is ever surfaced, parse `status` and `dependencies`. HTTP 200 alone never means healthy. | `/healthz` is always 200 by design (`routes.py:786-802`, `schemas.py:213-226`). MUST-KEEP #11. |
| H11 | Node names are opaque strings passed through, never mapped to a fixed stage vocabulary or pre-labelled ticks. | `state_delta` is an open scalar map (`runner.py:947-951`); no vocabulary is guaranteed. Standing constraint from `REVIEW.md`. |
| H12 | `hitl_bypass` is never exposed in the UI. | `schemas.py:41-48` accepts it from any caller; it skips the human control boundary. Discovery "can wait" question 4. |

Each rule gets at least one Storybook story and one test. H6 additionally
gets the interceptor count assertion in §7.3.

### 9.2 Frontend observability

**Nothing is transmitted anywhere.** No analytics SDK, no error-tracking
SaaS, no new backend endpoint. Two reasons: adding a telemetry route to
FastAPI would breach the frozen-backend rule, and shipping a private
research workspace's queries to a third party is not acceptable for this
product (`01-RESEARCH.md` open question on acceptable field telemetry).

What exists instead:

1. **A client-side diagnostics ring buffer.** The last 200 lifecycle
   records — event name, receive timestamp, job id, machine transition,
   normalized `ApiFailure.kind` — held in memory only, cleared on reload.
   A "Copy diagnostics" control in the failure disclosure produces a
   redacted JSON blob: **no report text, no question text, no headers, no
   URLs beyond the path template**. The operator pastes it into an issue.
   This gives incident evidence with zero data egress.
2. **Web Vitals measured, not sent.** `web-vitals` reports LCP/INP/CLS to
   the ring buffer and renders them only behind `?debug=perf`. Field p75
   remains unavailable, and this document does not pretend otherwise.
3. **Proxy request logging (planned).** One structured JSON line per
   proxied request from `web/app/api/[...path]/route.ts` to stdout:
   method, **path template** (not the raw path — job and conversation ids
   are not logged), upstream status, duration, response bytes. Never the
   API key, never a body. This is the Next.js server we already own and
   already run under Compose (`docker-compose.yml:111-140`), so it adds no
   backend surface. It closes the `00-DISCOVERY.md` gap "no browser error
   reporting, web-vitals reporting, or proxy observability exists" on the
   one axis that can be closed without new infrastructure.
4. **Explicitly not done:** session replay, RUM, breadcrumb upload, source
   maps published to a third party.

---

## 10. Identity-ready seams for MT-01

D-009 is binding: **the revamp must not fake login or per-user views.** MT-01
is a separate backend workstream with its own gated proposal and ADR. This
section reserves the shape so MT-01 does not require re-architecture, and
implements none of it.

| Seam | Where | Today | What MT-01 would change |
|---|---|---|---|
| **S1 — credential resolution** | `web/app/api/[...path]/route.ts:81-82` | `process.env.ARXIV_API_KEY` read inline | Extract to `resolveUpstreamPrincipal(request): Promise<{keyId, apiKey} \| null>` in `web/lib/server/principal.ts`. The shared-principal implementation returns the env key unchanged, so extracting the function is a **no-op refactor** today and the only edit site later. |
| **S2 — reserved auth path** | `web/app/api/[...path]/route.ts` catch-all | `/api/auth/login` would be forwarded upstream and 404 | Document `/api/auth/*` as **reserved**. A more specific route segment (`web/app/api/auth/[...]/route.ts`) takes precedence over the catch-all in the App Router, so MT-01 adds files without touching the proxy. Nothing is added now. |
| **S3 — session middleware** | `web/middleware.ts` | does not exist | The session check point when it does. Not created now — an empty middleware costs a hop on every request for no benefit. |
| **S4 — shell slot** | `(workspace)/layout.tsx` header | n/a | An `<IdentitySlot />` component that **returns `null`**. No avatar, no "Sign in", no placeholder. It reserves layout position and a component name, nothing else. |
| **S5 — cache partitioning** | TanStack Query keys | n/a | Every key is `['conversations', principal, …]` with `principal` a module constant `"shared"`. When principal becomes session-derived, caches partition automatically and no call site changes. |
| **S6 — ownership copy** | all copy | n/a | No "your conversations", no "my workspace". Deletion copy names exactly what the API deletes (`routes.py:627-657`). |
| **S7 — the boundary that is *not* identity** | `deploy/hetzner/Caddyfile:8-10` | site-level HTTP basic auth | Documented as a **deployment gate, not a user account**. The UI must never render it as a signed-in user. |

The backend already scopes by principal when auth is on (`routes.py:59-84`,
`routes.py:582-591`, ADR 0036) — MT-01's most plausible shape is a web
login mapped to per-user principals at S1, exactly as D-009 anticipates.
That is a proposal for MT-01 to make, not a commitment here.

---

## 11. Contract ambiguities to resolve at Gate 2

Found while designing against the frozen API. None is a bug report; each is
a place where the frontend must choose a behaviour and the choice should be
ratified rather than assumed.

1. **`last-event-id` is forwarded but inert.** The proxy allowlists it
   (`route.ts:17`), but `format_sse` never writes an `id:` line
   (`streaming.py:117-132`), so no client can ever set it and the backend
   would ignore it. Either drop it from the allowlist or declare it
   reserved for a future resume contract. *Frontend assumption: reserved,
   unused.*
2. **`stream_timeout` has no client handler.**
   `web/lib/useResearchStream.ts:59-66` registers six names; the server's
   seventh (`streaming.py:75`, emitted `streaming.py:300-308`) is dropped
   silently and the client falls back to the browser's default retry after
   the server closes at 3600 s (`src/config.py:332`). *Frontend
   assumption: handle it and reopen immediately (§4.4).*
3. **Terminal payloads are asymmetric between live and replay, in both
   directions.** Live `job_completed` (`runner.py:1278-1288`) has
   `llm_calls` but **no `status`**; the replay
   (`routes.py:857-867`) has `status` but **no `llm_calls`**. Live
   `job_cancelled` carries `reason` at `runner.py:1128-1135` but not at
   `runner.py:1196-1199`, and the replay never does. One event name, three
   shapes. *Frontend assumption: treat every terminal frame as a signal
   only; read all values from `GET /research/{id}` (H9).*
4. **`plan_ready` can legitimately arrive twice** on the in-memory path —
   deliberate and documented (`routes.py:456-462`). *Frontend assumption:
   idempotent handling; no duplicate-detection warning shown.*
5. **`ReviewResponse.status` is always `pending_review`**
   (`schemas.py:141-160`). A 200 does not mean the run resumed. *Frontend
   assumption: enter `resolving` and wait for SSE or a poll (§4.5).*
6. **`GET /conversations` has no `total` or `has_more`**
   (`routes.py:560-600`), and the current client sends no `limit`/`offset`
   (`web/lib/api.ts:67-73`) so it silently truncates at 50
   (`conversations.py:35`). *Frontend assumption: explicit paging with
   "Load more"; no page counts (§4.6).*
7. **Export permits a failed job's partial report** (`routes.py:364-368`
   gates only on falsy `result`) while the UI hides it
   (`ReportView.tsx:13-29`). This is discovery's "can wait" question 1 and
   it now has a concrete UI consequence. *Frontend assumption: show and
   allow export, clearly labelled partial (H5). **Needs a product
   ruling.***
8. **The 429 `detail` is an object** (`auth.py:176-184`) while every other
   error is a string, and `web/lib/api.ts:129-137` therefore renders raw
   JSON to the user. *Frontend assumption: normalize in `errors.ts` (§3.4).*
9. **404 means both "missing" and "not yours"** (`routes.py:59-84`).
   Correct by design; the UI must never guess which (H8).
10. **`node_completed.state_delta` has no schema** — scalars only, filtered
    at `runner.py:947-951`, with an unfixed node vocabulary. *Frontend
    assumption: opaque pass-through, unknown keys tolerated (H11).*
11. **`hitl_bypass` is accepted from any caller** (`schemas.py:41-48`) and
    the proxy would forward it. *Frontend assumption: never exposed (H12).
    Confirmed as discovery "can wait" question 4.*
12. **The web container healthcheck proves only Next `/`**
    (`web/Dockerfile:45-46`, `docker-compose.yml:131-140`) — it never
    exercises the proxy path, so a misconfigured `API_INTERNAL_BASE` yields
    a *healthy* web container serving a broken app. *Proposed: probe
    `/api/healthz` and require HTTP 200, but **not** fail on
    `status: degraded` — otherwise a Redis blip would restart the web
    container for a backend fault (`routes.py:786-802`). Planned; see
    [`05-MIGRATION.md`](05-MIGRATION.md#3-ci-and-operational-additions-planned).*

Items 7 and 12 are the two that most want an explicit human answer at
Gate 2. The rest are recorded so the assumptions are reviewable rather than
implicit.

---

## 12. Risk register deltas

Effect of this architecture on [`RISKS.md`](RISKS.md). No risk is closed by
a document; these are the mitigations this design commits to.

| Risk | Addressed by |
|---|---|
| R-01 duplicate paid run | §4.1 (`POST /research` outside Query — no offline replay), H6, §7.3 interceptor count assertion |
| R-02 lost `?job=` | §4.3 URL is the sole handle; GET-first attach; §2.2 unknown/expired states |
| R-05 SSE live/replay divergence | §3.2 asymmetry table, §7.2 recorded frame scripts, H9 always-final-GET |
| R-04 mobile unusable | §8.3 structural repair + the `scrollWidth` gate |
| R-06 generated-type false confidence | §3.3 generated JSON types + handwritten SSE/export/error overlay, §3.5 four-check drift detection |
| R-08 weakened secret boundary | §1.3 constraints, proxy stays sole boundary, CSP + proxy tests planned |
| R-09 dynamic forms fail keyboard/SR | §5 native-first primitives, §7.4 axe gate, Gate 4 manual evidence |
| R-10 mocks diverge from reality | §3.5 fixtures are recorded from the seeded stack, never authored |
| R-11 dependencies eat the budget | §8.1 tight headroom forces dynamic import of RHF/Zod |
| R-14 partial reports lost | H5 — pending the Gate 2 ruling in §11.7 |
| R-03 / R-07 | Unchanged: no structured evidence is invented; no identity is faked (§10) |
