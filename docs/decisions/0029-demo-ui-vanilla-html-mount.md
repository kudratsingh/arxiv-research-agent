# 0029. Demo UI: vanilla HTML + JS + CSS mounted from FastAPI

- **Status**: accepted
- **Date**: 2026-07-10
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (job model),
  [0026](0026-sse-streaming-endpoint.md) (SSE streaming)

## Context

Sprint 4 made the HTTP API reachable, containerized, and horizontally
scalable. But "reachable" still meant `curl` or Postman — the demo
story required the reviewer to know how to shape a POST and how to
consume an `EventSource`. That's a fine story for engineers who
already know the shape; it's a bad story for a portfolio artifact
where the goal is a reviewer typing a query and watching the workflow
work.

Sprint 5 opens the product-surface arc. Item #1 in the roadmap
(`planning/03-roadmap.md`) is a "minimal web UI (Next.js or
Streamlit) with streaming." Two axes to pick on:

- **Framework**: Next.js, Streamlit, or vanilla HTML/JS/CSS.
- **Deployment**: separate service (Node + Next.js build), same
  service (mounted under FastAPI as static files), or something in
  between.

The UI is a demo surface for the API, not a customer-facing
application. That framing is what shapes the trade-off.

## Decision

Vanilla HTML + JavaScript + CSS in `src/api/ui/`, served by the
existing FastAPI app through a `StaticFiles` mount at `/static` plus
an explicit `GET /` handler that returns `index.html`. No Node, no
build step, no separate service.

### Layout

```
src/api/ui/
    index.html   — the page (~65 LOC)
    app.js       — submit + EventSource + rendering (~170 LOC)
    style.css    — minimal dark-first styling (~180 LOC)
```

### Mount pattern

```python
app.include_router(router)
app.mount("/static", StaticFiles(directory=UI_DIR), name="static")

@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")
```

Order matters: `include_router(router)` first, so the concrete API
routes (`/research`, `/research/{job_id}`, `/healthz`, `/openapi.json`,
`/docs`) take precedence. Then the static mount + root handler.
`StaticFiles(html=True)` at `/` would work too but shadows the
OpenAPI schema, so we take the explicit `GET /` route instead.

### Client architecture

Single-file `app.js` with no framework. Flow:

1. On submit, `POST /research` with `{query}` — get `{job_id,
   status_url, stream_url}`.
2. Open `EventSource(stream_url)`; listen for `job_started`,
   `node_completed`, `job_completed`, `job_failed`, `job_cancelled`.
3. Each event appends to the live log with node name + scalar
   deltas.
4. On terminal event, `GET status_url` to pick up the full report
   body (the SSE frames stay compact per ADR 0026 — the report goes
   through the polling endpoint, not the stream).

Report rendering is `<pre>` with the raw markdown. Markdown-to-HTML
rendering is a follow-up; the demo value is watching the workflow
progress, not the typography of the final report.

### Packaging

`pyproject.toml` gets a `[tool.setuptools.package-data]` entry:

```toml
"src.api" = ["ui/*.html", "ui/*.js", "ui/*.css"]
```

Without this, a non-editable `pip install .` (the Dockerfile path)
would ship the `.py` files but drop the UI assets. Verified by
`pip install --target=/tmp/wheeltest .` before merge.

## Alternatives considered

- **Next.js.** Modern React, industry-standard for web apps,
  first-class `EventSource`. Cost: a whole Node toolchain (~200 MB
  more base image if bundled, or a separate service and a
  cross-service auth story). Adds Jest/Vitest, TypeScript config,
  a `next build` step to CI. Rejected: the UI's job is to prove the
  API works; Next.js buys features (routing, SSR, edge functions)
  that a demo surface doesn't need. Rewrite in Next.js as a
  Sprint 6+ concern if a real customer-facing product emerges.
- **Streamlit.** Fastest to prototype in — one Python file with
  widgets. Rejected on the streaming story: Streamlit's rerun-on-
  interaction model doesn't play well with `EventSource`. The
  workarounds (websocket, background threads writing to
  `session_state`, `st.experimental_fragment`) all fight the
  framework. Also duplicates the FastAPI service (a Streamlit
  process runs on a separate port) so `docker compose up`
  becomes a two-service story.
- **HTMX + Alpine.** Nice sweet spot — declarative SSE via
  `hx-sse`, no build step. Rejected as marginal: another dep
  (~40 KB HTMX + ~40 KB Alpine) for functionality vanilla JS
  handles in ~170 LOC, and the tests would need to reason about
  HTMX attribute semantics.
- **Vendor `marked.js` for markdown rendering.** Would let the
  report render as HTML instead of preformatted text. Rejected
  for PR 1: `<pre>` is honest about "here's what the model
  produced" and dodges the XSS surface of user-controlled HTML
  through a client-side sanitizer. Markdown rendering can land
  as a Sprint 5 follow-up once we have a sanitizer story
  (DOMPurify + marked, or server-side render via `markdown-it`).
- **Serve from a separate CDN / static hosting.** Right pattern
  for a product-scale UI. Rejected for the demo: `docker compose
  up` should be the one command that reveals the whole thing.
- **`StaticFiles(html=True)` at `/`.** Would auto-serve
  `index.html` at the root. Rejected because it catches every
  unmatched request and shadows the OpenAPI schema surface at
  `/openapi.json`. The explicit `GET /` handler is one line and
  more predictable.

## Consequences

- **Positive.** `docker compose up` gets a reviewer a live demo
  UI at `http://localhost:8000/` — no additional setup, no
  toolchain to install. The API surface stays authoritative:
  every UI interaction is a documented API call, so what the
  reviewer sees in the browser is the same thing an API
  consumer would build against. Total footprint is ~380 LOC of
  static assets + ~20 LOC of mount plumbing.
- **Neutral.** UI has no build-time type checking (TypeScript
  would give us that). At ~170 LOC of JS with well-defined
  message payloads (ADR 0026's event schema), the type-safety
  gap is small and the test suite catches contract regressions
  at the API boundary. A future TypeScript rewrite is a
  drop-in when the surface grows past what's reasonable to
  hand-type.
- **Negative.** No client-side routing. Adding /jobs/<id> as a
  standalone URL that reconnects to a job's stream is a small
  change (History API) if a follow-up wants it.
- **Follow-ups.**
  - Markdown rendering for the report body (with sanitizer).
  - History-based routing so a job URL is bookmarkable.
  - Cancel button wired to a `POST /research/{id}/cancel`
    endpoint (endpoint doesn't exist yet — runner already
    supports the CancelledError path from ADR 0025).
  - Multi-format export (Sprint 5 PR 3) surfaces as an
    "Export" dropdown on the report panel.
