# 0029. Next.js web UI as a separate compose service

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (job model),
  [0026](0026-sse-streaming-endpoint.md) (SSE streaming),
  [0027](0027-docker-compose-redis-job-store.md) (compose stack)

## Context

Sprint 4 made the HTTP API reachable, containerized, and
horizontally scalable. "Reachable" still meant `curl` or Postman —
a reviewer needed to know how to shape a POST and consume an
`EventSource`. That's a fine story for engineers who already
understand the shape; it's a bad story for a portfolio artifact
where the goal is a reviewer typing a query and watching the
workflow work.

Sprint 5 opens the product-surface arc. Item #1 in the roadmap
(`planning/03-roadmap.md`) is a "minimal web UI (Next.js or
Streamlit) with streaming." The choice shapes not just this PR
but the follow-ups — HITL breakpoint UI, multi-format export UI,
follow-up conversation mode UI all attach to whatever we pick
here.

## Decision

New `web/` Next.js 14 (App Router) application, TypeScript strict,
runs as a separate service in the compose stack on port 3000.
Talks to the FastAPI service over the browser (via the
host-published `APP_PORT`), not the compose network. Standard
modern stack: Tailwind for styling, ESLint (Next.js default) +
Vitest + Testing Library for the test tier, `output: 'standalone'`
for a minimal runtime image.

### Compose topology

```
docker-compose.yml
  web       Next.js on  :3000   (host-published)
  app       FastAPI on  :8000   (host-published)
  redis     JobStore on :6379   (internal network)
  postgres  Cache on    :5432   (internal network)
```

`web` `depends_on: {app: {condition: service_healthy}}` so the UI
never comes up pointing at a dead API. Compose injects
`NEXT_PUBLIC_API_BASE=http://localhost:${APP_PORT:-8000}` as a
`--build-arg` at image-build time — the value gets baked into the
client bundle, no runtime env plumbing needed for the browser.

### Directory layout

```
web/
├── app/
│   ├── layout.tsx        root layout + metadata
│   ├── page.tsx          server-rendered wrapper
│   └── globals.css       Tailwind directives + markdown prose styles
├── components/
│   ├── ResearchApp.tsx   client-side orchestrator (`use client`)
│   ├── QueryForm.tsx     query input + submit
│   ├── EventLog.tsx      live SSE event log
│   ├── JobSummary.tsx    metrics grid
│   └── ReportView.tsx    react-markdown + remark-gfm
├── lib/
│   ├── types.ts          mirrors src/api/schemas.py
│   ├── api.ts            typed fetch client + ApiError
│   └── useResearchStream.ts   custom hook owning the full lifecycle
├── tests/                Vitest + Testing Library
├── Dockerfile            multi-stage node:20-alpine, non-root
└── next.config.mjs       output: 'standalone'
```

### Client flow

The whole interactive surface is a `use client` boundary at
`ResearchApp.tsx`. The `useResearchStream` hook owns the
lifecycle:

1. `POST /research` — `submitResearch(query)` returns `{job_id,
   status_url, stream_url}`.
2. `new EventSource(stream_url)` — each frame lands in the hook's
   `events` state array in receive order.
3. On a terminal event (`job_completed` / `job_failed` /
   `job_cancelled`), `GET /research/{job_id}` — the settled
   `JobDetail` carries the report body + metrics (SSE stays
   compact per ADR 0026).

### Report rendering

`react-markdown` + `remark-gfm`. React-markdown emits sanitized
HTML by default (no raw HTML passthrough), so the LLM-generated
report body is safe to render without a separate DOMPurify pass.
GFM enables tables, strikethrough, and task lists — features the
synthesizer emits.

## Alternatives considered

- **Vanilla HTML + JS + CSS mounted from FastAPI** (attempted in
  the closed PR #35). Zero build step, single-image deploy, all
  the demo value in ~380 LOC. Rejected on maintainer preference:
  the "modern web stack" narrative — TypeScript, React, Tailwind,
  Vitest — is the story the portfolio needs to tell, and the
  Sprint 5 follow-ups (HITL, export, conversation mode) benefit
  from React state management rather than hand-rolled DOM
  updates. Vanilla was my initial recommendation; corrected.
- **Streamlit.** Fastest to prototype — one Python file with
  widgets. Rejected on the streaming story: Streamlit's
  rerun-on-interaction model doesn't play well with `EventSource`.
  The workarounds (websocket, background threads writing to
  `session_state`, `st.experimental_fragment`) all fight the
  framework. Also duplicates the FastAPI service on a separate
  port with a different tech stack.
- **Next.js as a monorepo child of the Python app** (single
  Dockerfile, multi-stage node → python → both). Rejected: the
  two services scale independently in production, and mixing
  their build graphs increases cold-cache build time for both.
  Two containers, one compose entry each.
- **Next.js with `rewrites()` proxying `/api/*` to FastAPI.**
  Cleaner dev UX because everything runs on `localhost:3000`.
  Rejected for the demo — SSE through a Next.js middleware
  layer adds an extra hop for zero benefit, and the client bundle
  can perfectly well fetch `http://localhost:8000/...` directly.
  A follow-up can add rewrites if we ever host under a single
  origin (e.g., behind an nginx that terminates TLS for both).
- **Server-side rendering the initial page state.** Considered
  and rejected: `EventSource` is a client-only API, and the
  initial page has no server-fetched data to display. Making the
  home page a Server Component that renders the Client Component
  is the right App Router shape here.
- **Redux / Zustand for state.** Rejected: three components share
  state (`events`, `detail`, `error`), and the useResearchStream
  hook is a one-file custom hook. A store library would be
  ceremony for its own sake.
- **Playwright end-to-end tests.** Deferred — component tests via
  Vitest cover the units well, and the hook's `EventSource`
  behavior is honestly best exercised in a browser. A Playwright
  suite fits nicely once the surface grows past two screens.

## Consequences

- **Positive.** `docker compose up` reveals `http://localhost:3000/`
  as a functional demo — the reviewer types a question, hits Run,
  watches nodes complete over SSE, and sees a markdown-rendered
  report with the metrics grid. The Next.js codebase gives every
  follow-up (HITL, export, conversation mode) a modern React
  runtime to build against. The API + UI stay decoupled: the UI
  is one HTTP client the FastAPI service could have many of, and
  the API surface is authoritative — every UI interaction is a
  documented API call.
- **Neutral — TypeScript strict.** `noUncheckedIndexedAccess` is
  on, which catches a whole class of client bugs but occasionally
  requires a defensive `?? ""` at boundaries. Worth the friction
  for a demo that hits the API for real.
- **Negative — two-image Docker build.** CI now builds the Python
  image (~13min cold) and the Next.js image (~2min cold) in
  parallel. Under warm cache both are near-instant, but a
  dependency change on either side pays its own cold cost. Also
  raises the total compose stack from 3 to 4 services.
- **Follow-ups.**
  - HITL breakpoint UI (Sprint 5 PR 2) — pause between supervisor
    plan step and node execution; edit the plan then resume.
  - Multi-format export UI (Sprint 5 PR 3) — dropdown on the
    report panel with PDF / DOCX / markdown options.
  - Follow-up conversation mode — extends the client store with
    a per-conversation timeline.
  - Auth on the FastAPI side once we host beyond localhost;
    the UI gets a login screen and the API gets bearer-token
    validation.
  - Server-side proxy via `next.config.mjs` `rewrites()` once we
    host the whole thing behind a single origin.
