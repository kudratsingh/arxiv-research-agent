# 0055. Confirm Next.js App Router + the same-origin Node proxy as the frontend architecture

- **Status**: accepted
- **Date**: 2026-08-29
- **Deciders**: EXEC coordinator under the D-010 delegation
  (`docs/revamp/DECISIONS.md` D-010 ruling 1); Gate 2 package reviewed and
  approved before ratification

## Context

D-002 (`docs/revamp/DECISIONS.md`) retained Next.js and its same-origin Node
proxy **preliminarily**, on the rationale that the proxy keeps the upstream
API key out of browser code. It was recorded as "preliminary; architecture
confirmation at Gate 2" precisely because the frontend revamp was about to
rewrite nearly every file under `web/` — and a stack decision made on a
one-line rationale is not a decision you want thirty work orders to depend on.

Phase 3 re-derived the rationale from the code rather than restating it, and
found a third property that D-002 never named and that changes the answer's
character. The proxy (`web/app/api/[...path]/route.ts`) has three load-bearing
properties:

1. **It is the only place the upstream credential exists.** `X-API-Key` is
   attached server-side (`route.ts:138-139`, via the `resolveUpstreamPrincipal`
   seam); every browser-side call is same-origin and carries no credential.
2. **It streams SSE and downloads without buffering.** It returns the raw
   upstream `ReadableStream` with an allowlisted subset of upstream headers
   (`route.ts:53-57`). That allowlist is why exports work — `content-disposition`
   survives — and why SSE stays unbuffered through a reverse proxy —
   `x-accel-buffering: no` survives. `retry-after` survives, which is the only
   way a 429 can be rendered usefully.
3. **Two browser APIs cannot carry a request header at all.** Native
   `EventSource` (`web/lib/job/useJobStream.ts:374`) accepts no request headers,
   and the export links are plain `<a download>` anchors
   (`web/components/patterns/ExportDisclosure.tsx:264`), not `fetch` calls.
   Under `ENABLE_API_AUTH=true` — which is exactly the production configuration
   (`deploy/hetzner/compose.prod.yml`) — **neither the stream nor any export can
   be authenticated from browser code.**

Property 3 is the decisive one. It converts "we would have to recreate the BFF"
into "any architecture without a same-origin server hop cannot stream or export
in production at all". Full derivation:
[`04-ARCHITECTURE.md` §1.1](../revamp/04-ARCHITECTURE.md).

## Decision

**D-002 is confirmed as binding.** The frontend stays on the Next.js App Router
with `web/app/api/[...path]/route.ts` as its server boundary, under three
constraints.

### Constraint 1 — the proxy is the sole credential boundary

`web/app/api/[...path]/route.ts` remains the **only** place an upstream
credential is read or attached. Two of its exports are pinned and are not to be
changed:

```ts
export const dynamic = "force-dynamic";   // route.ts:43
export const runtime = "nodejs";          // route.ts:44
```

`nodejs` because the Edge runtime cannot return an upstream `ReadableStream`
with the same streaming guarantees, and `force-dynamic` because a proxied
request must never be served from a route cache.

Data fetching stays **client-side through `/api`** for the whole revamp. Any
future React Server Component that fetches `API_INTERNAL_BASE` directly would
create a *second* credential path; that is explicitly out of scope and needs its
own ADR. Server-rendering the conversation list would be faster, but it needs
that second path and would fork the MT-01 identity seam
([`04-ARCHITECTURE.md` §10](../revamp/04-ARCHITECTURE.md)). Server Components
are used only for static shell chrome, which is where the bundle savings are
anyway.

### Constraint 2 — the proxy gains request logging and a CSP before rollout

This was a *precondition*, not an aspiration, and it is now **discharged**. The
web service ships a per-request nonce CSP (`web/middleware.ts`), one structured
JSON log line per proxied request that emits a path *template* rather than a raw
job or conversation id (`web/lib/server/proxyLog.ts`), and a container
healthcheck that probes `/api/healthz` through the proxy rather than `/`.
Details and the exact policy: [`../security.md`](../security.md).

### Constraint 3 — framework-level migrations stay out of this revamp

**Tailwind 4, TypeScript 7, and Turbopack each need their own ADR.** None is
adopted here. The build tool pin is a gate, not a sentence: `web/package.json`'s
build script is exactly `next build --webpack`, and `web/tests/ci.test.ts`
asserts that exact string. Keeping these three out is what makes any regression
in this revamp attributable to the revamp.

### Reserved names, deliberately not created

So that nothing else claims them:

| Path | Status |
|---|---|
| `web/app/login/` and `web/app/settings/` | Reserved route names. No files. |
| `web/app/api/auth/[...path]/route.ts` | Reserved. Falls into the catch-all today; the App Router's more-specific segment will take precedence when MT-01 adds it, so the login surface lands without editing the credential boundary. |

## What changed since the constraint was written

One architecture fact moved, and it is recorded here so the next reader does not
treat the Phase 3 text as current:

**`/` is dynamically rendered.** D-014 ruling 3
(`docs/revamp/DECISIONS.md`) accepted this as *inherent to the nonce CSP*: a
per-request nonce cannot live in a cached document. Two consequences were
recorded rather than smoothed over — `/` fails the desktop bfcache audit by
design (`no-store`), and the route-budget script's manifest cross-check for `/`
reads "skipped — not statically prerendered". The bfcache gate is `/c/[id]`,
which is unchanged cell for cell.

This does **not** weaken Constraint 1. `force-dynamic` on the proxy route was
always pinned; what changed is that the *document* route is now dynamic too, for
a security reason rather than a data-fetching one.

Line numbers also moved: [`04-ARCHITECTURE.md` §1.3](../revamp/04-ARCHITECTURE.md)
cites `route.ts:10-11` for the two exports; after WO-30 they are `route.ts:43-44`.
The pins themselves are unchanged.

## Alternatives considered

- **Vite/React SPA + a separate Node (Hono/Express) BFF** — rebuilds properties
  1–3 in a new service; adds a fourth image to Compose, a second CI build job,
  and a second origin for Caddy to route. Loses Next's per-route code splitting,
  which is what makes the route budgets measurable at all. *Rejected — strictly
  more moving parts for identical capability.*
- **Another full-stack framework (Remix / React Router 7 / TanStack Start)** —
  equivalent capability. Migration cost is the whole `web/` tree plus
  `web/Dockerfile` (`output: "standalone"`) plus the Compose healthcheck. No
  evidence of a benefit this product needs. *Rejected — cost with no named
  benefit.*
- **Server-rendered non-React (SvelteKit, HTMX + templates)** — discards React,
  the passing web suite, and the reconnect/HITL logic that discovery flags as the
  highest-churn, highest-risk code. *Rejected.*
- **Next.js with `next.config` rewrites or Edge middleware instead of the route
  handler** — `rewrites` cannot inject a per-request secret header, and Edge
  middleware would move the key into the Edge runtime and cannot return an
  upstream `ReadableStream` with the same streaming guarantees. *Rejected.*

## Consequences

- **Positive**: zero migration cost — the boundary already existed and was
  already tested (`web/tests/apiProxyRoute.test.ts`), and WO-30 changed nothing
  about its behaviour. The MT-01 identity seams stay one-directional: a session
  is resolved at `resolveUpstreamPrincipal` (`web/lib/server/principal.ts`) and
  no call site changes. Per-route code splitting keeps the budget gate in
  ADR [0056](0056-design-tokens.md) meaningful.
- **Negative**: every browser→API call takes an extra same-origin hop, and the
  web container is on the critical path for the API's availability — a dead
  `web` service means a dead product even when FastAPI is healthy (which is why
  the healthcheck now probes through the proxy). CSRF is **not** addressed and
  is out of scope pending MT-01: the proxy has no per-user session to protect
  today, but the moment MT-01 introduces one, every state-changing route behind
  this proxy becomes forgeable without a token. See
  [`../security.md`](../security.md).
- **Follow-ups**: Tailwind 4, TypeScript 7 and Turbopack remain unadopted and
  each needs its own ADR. MT-01 (multi-tenancy) owns the CSRF requirement, the
  `/api/auth/*` route file, and the `/login` and `/settings` routes; it is a
  separate backend workstream with its own gated proposal and is **reserved for
  the user**, not delegated.
