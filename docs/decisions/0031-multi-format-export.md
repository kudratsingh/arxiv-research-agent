# 0031. Multi-format export (Markdown, PDF, DOCX)

- **Status**: accepted
- **Date**: 2026-07-11
- **Depends on**: ADR
  [0025](0025-fastapi-async-job-model.md) (job model),
  [0029](0029-nextjs-web-ui.md) (web UI)

## Context

Sprint 5's product-surface arc ships the pieces that turn "the
API works" into "a reviewer can take something away." PR 1 (ADR
0029) gave the reviewer a live UI; PR 2 (ADR 0030) gave them
control over the plan. PR 3 closes the loop: the reviewer should
be able to download the completed briefing in a format that
survives outside the browser tab. Ad-hoc "copy the markdown out of
`<pre>`" is fine for engineers; a portfolio artifact should hand
back a real document.

Three formats are the reasonable minimum:

- **Markdown** — the synthesizer's native output. Zero-loss, plain
  text, greppable. The "power user" download.
- **PDF** — the "send this to someone" format. Print-friendly,
  format-stable across machines.
- **DOCX** — the "edit this into a longer document" format. Every
  reviewer's colleague uses Word; leaving the door open for
  further editing removes a friction point.

## Decision

New `GET /research/{job_id}/export?format=md|pdf|docx` returns the
report in the requested format with a `Content-Disposition:
attachment` header so browsers download rather than inline-render.
UI adds an "Export ▾" dropdown on the ReportView with three menu
items.

### Rendering stack

Pure-Python throughout — no external binaries, no LaTeX, nothing
that grows the Docker image beyond a few MB of wheels:

- **Markdown parsing**: `markdown-it-py`. CommonMark + GFM tables.
  Emits a token stream we walk once per format. ~200 KB, no C deps.
- **PDF**: `reportlab`. Pure Python, ~1 MB. Its `Paragraph`
  flowable understands a minimal HTML subset (`<b>`, `<i>`,
  `<font>`, `<br/>`, `<a>`) that maps directly to what
  `markdown-it-py` emits inline; block-level tokens (headings,
  paragraphs, lists, tables, code blocks, quotes) map to
  ReportLab's `Paragraph` / `ListFlowable` / `Table`. Non-trivial
  work but bounded.
- **DOCX**: `python-docx`. Pure Python, ~2 MB. Same token walker
  shape as the PDF renderer; emits Word paragraphs, headings,
  bullet/ordered lists, tables (with a light gray header row via
  low-level oxml manipulation).

The two renderers each declare a `render(job) -> bytes` function.
The registry `EXPORTERS[fmt] = (media_type, ext, render)` is what
the route dispatches on.

### Endpoint contract

- `200 OK` — payload in the requested format. Headers:
  `Content-Type` (format-specific), `Content-Disposition:
  attachment; filename="research-{job_id}.{ext}"`, `Cache-Control:
  no-store` (report content is per-user + unauthenticated; no
  intermediate should cache it).
- `404 Not Found` — no job with the given ID.
- `409 Conflict` — job exists but has no report body (still
  `pending` / `running` / `pending_review`, or `failed` /
  `cancelled` before it produced one).
- `422 Unprocessable Content` — `format` is not one of
  `md` / `pdf` / `docx`. FastAPI's `Query(pattern=...)` returns
  this automatically.

Every export includes a metadata block (job_id, completion time,
iterations, quality, cost, elapsed) so a downloaded file is
self-describing outside the API context.

### UI

`ExportDropdown` on the ReportView panel. Three `<a>` tags with
`download` attributes pointing at
`${API_BASE}/research/{id}/export?format=...`. Menu closes on
outside click and Escape. Deliberately does *not* fetch and
create a Blob — a plain anchor keeps semantics identical to
"right-click, save as" from the docs page, and Content-Disposition
does the heavy lifting.

## Alternatives considered

- **WeasyPrint for PDF.** Renders HTML → PDF, matches the demo
  UI's report styling more closely. Rejected: significant native
  deps (Pango, Cairo, GDK-PixBuf) push the Docker image up
  meaningfully, and rendering fidelity vs the browser view
  wasn't a load-bearing requirement.
- **Pandoc for both PDF and DOCX.** Highest-quality conversion of
  the three. Rejected: PDF path requires LaTeX (or a WeasyPrint
  wrapper — see above); DOCX path requires the pandoc binary,
  adding a ~50 MB apt install to the Dockerfile plus a
  `pypandoc` subprocess call at request time. The pure-Python
  stack is smaller, more predictable, and doesn't need runtime
  process management.
- **Client-side rendering.** Ship a JavaScript markdown→PDF or
  markdown→DOCX library, render in the browser. Rejected: `docx`
  and `pdf` client libraries are large (100-300 KB each) and
  render inconsistently across browsers; more importantly, the
  server already has the report body — asking the client to
  reconstruct it is wasted work. Server-side rendering keeps the
  UI thin and the API authoritative.
- **Presigned URL / streaming**. Overkill for reports that fit in
  a few hundred KB. If a future report grows into megabytes we
  can revisit.
- **XLSX / CSV.** Rejected: the report body is prose. Tabular
  data (metrics per query in the eval harness) belongs in a
  separate export surface if we ever add one.
- **Blob + `URL.createObjectURL` in the client.** Would give the
  UI more control (e.g. show a spinner while the server renders).
  Rejected: adds ~30 lines of code and a state machine for zero
  UX gain — the server responses land in ~50 ms for small
  reports and the browser download UI is already familiar.
- **`sse-starlette` for streaming the PDF as it renders.**
  Rejected: reportlab writes to an in-memory buffer and finalizes
  at the end; incremental streaming would require a very
  different rendering pipeline.

## Consequences

- **Positive.** The demo UI now hands back a real document. A
  reviewer can archive the briefing, forward it, or continue
  editing in Word. The pure-Python stack means the Docker image
  grows by ~4 MB total — negligible against the existing ML
  stack (torch + sentence-transformers). Renderers share a
  token-walker shape so a fourth format (e.g. HTML export) would
  reuse the plumbing.
- **Neutral — no fidelity guarantee.** Both PDF and DOCX render
  the synthesizer's markdown at a "good enough for a briefing"
  level; there's no promise of pixel-perfect parity with the
  browser view. Tables, headings, lists, and inline formatting
  work; complex nested markdown (a task list inside a table cell
  inside a block quote) may render inconsistently. Acceptable
  because the synthesizer's output stays in the "well-formed
  research briefing" register.
- **Negative — extra CPU per export.** Rendering a
  ~2000-word report as PDF takes ~50 ms of CPU on a small
  machine; DOCX ~100 ms. Amortized across the workflow (30-90
  seconds), that's noise. If export volume ever dominates,
  cache the rendered payloads per (job_id, format) in Redis with
  the same retention window as the job itself.
- **Follow-ups.**
  - **HTML export.** Same walker, third renderer; useful for
    email embeds.
  - **Cached exports.** Redis-backed cache per (job_id, format);
    matches the RedisJobStore pattern from ADR 0027.
  - **Style theming for PDF/DOCX.** Right now the styles are
    hardcoded; a future ADR can expose a `theme` query param
    (e.g. `theme=academic`, `theme=minimal`).
  - **Citations rendering.** The synthesizer inlines citations as
    `[Author, Year]` and doesn't emit a separate citation list.
    A follow-up could append the `citations` structured field
    from `Job` to each format's footer.
