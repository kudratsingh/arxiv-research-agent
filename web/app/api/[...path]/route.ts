/**
 * Same-origin proxy from the browser-facing Next.js service to FastAPI.
 *
 * The API key is read only in the Node.js runtime and injected into the
 * upstream request. It never enters the client bundle, URL, browser storage,
 * or EventSource constructor. Returning the upstream ReadableStream directly
 * preserves SSE and export-download behavior without buffering whole reports.
 *
 * WO-30 CHANGED TWO THINGS HERE AND NO OTHERS (RC-08).
 *
 *   1. The inline `process.env.ARXIV_API_KEY` read became a call to
 *      `resolveUpstreamPrincipal(request)` — MT-01 seam S1
 *      (04-ARCHITECTURE.md §10). The shared implementation returns the same
 *      env key, so it is a no-op refactor and `tests/apiProxyRoute.test.ts`
 *      proves it by still passing **unmodified**.
 *   2. One structured JSON line per request goes to stdout (C6). It carries
 *      a path TEMPLATE, never the raw path, never the query string, never a
 *      header and never a body — see `lib/server/proxyLog.ts`.
 *
 * The contract 03 §2.1 calls "unchanged" is unchanged: credential injection,
 * the request and response header allowlists, `runtime = "nodejs"`,
 * `dynamic = "force-dynamic"`, and unbuffered stream/download pass-through.
 * If any of those had moved, the frozen test file would be red.
 *
 * MT-01 SEAM S2 — `/api/auth/*` IS RESERVED, AND NO FILE IMPLEMENTS IT.
 * Today `/api/auth/login` would fall into this catch-all and be forwarded
 * upstream, where FastAPI 404s it. That is the correct behaviour for a
 * product with no login, and it is also why the path is safe to reserve: in
 * the App Router a more specific segment (`app/api/auth/[...path]/route.ts`)
 * takes precedence over a catch-all, so MT-01 adds files and this file does
 * not change. Nothing is added now (04 §10 S2, D-009). `tests/principal.test.ts`
 * asserts the directory stays absent, and `docs/security.md` records the
 * reservation.
 */

import { resolveUpstreamPrincipal } from "@/lib/server/principal";
import type { UpstreamPrincipal } from "@/lib/server/principal";
import {
  countStreamedBytes,
  emitProxyLog,
  pathTemplate,
} from "@/lib/server/proxyLog";
import type { ProxyOutcome } from "@/lib/server/proxyLog";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface RouteContext {
  params: Promise<{ path: string[] }>;
}

const REQUEST_HEADERS = ["accept", "content-type", "last-event-id"] as const;
const RESPONSE_HEADERS = [
  "cache-control",
  "content-disposition",
  "content-type",
  "retry-after",
  "www-authenticate",
  "x-accel-buffering",
] as const;

/** Forward a GET request to FastAPI. */
export async function GET(
  request: Request,
  context: RouteContext
): Promise<Response> {
  return proxyRequest(request, context);
}

/** Forward a POST request to FastAPI. */
export async function POST(
  request: Request,
  context: RouteContext
): Promise<Response> {
  return proxyRequest(request, context);
}

/** Forward a DELETE request to FastAPI. */
export async function DELETE(
  request: Request,
  context: RouteContext
): Promise<Response> {
  return proxyRequest(request, context);
}

/**
 * Build a constrained upstream request and stream its response back.
 *
 * Args:
 *   request: Browser request received by the Next.js route handler.
 *   context: Catch-all route segments supplied by Next.js.
 *
 * Returns:
 *   The upstream status, selected safe headers, and streaming body. A local
 *   503/502 response is returned for invalid configuration/network failure.
 */
async function proxyRequest(
  request: Request,
  context: RouteContext
): Promise<Response> {
  const startedAt = Date.now();
  let segments: readonly string[] = [];

  // C6: the log line is built from the TEMPLATE, resolved once here. Nothing
  // downstream is handed the raw path, so nothing downstream can log it.
  const log = (
    status: number,
    bytes: number,
    outcome?: ProxyOutcome
  ): void => {
    emitProxyLog({
      method: request.method,
      pathTemplate: pathTemplate(segments),
      status,
      durationMs: Date.now() - startedAt,
      bytes,
      ...(outcome === undefined ? {} : { outcome }),
    });
  };

  let upstreamUrl: URL;
  try {
    segments = (await context.params).path;
    upstreamUrl = buildUpstreamUrl(request, segments);
  } catch {
    log(503, 0, "misconfigured");
    return Response.json(
      { detail: "api_proxy_misconfigured" },
      { status: 503 }
    );
  }

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }
  // MT-01 seam S1. Identical behaviour to the inline env read it replaced:
  // the header is set when a key is configured and omitted when it is not.
  //
  // WO-W17 WRAPPED THE CALL AND CHANGED NOTHING ELSE. With `PILOT_EDGE_AUTH`
  // off the seam cannot throw, so this `try` never fires and the frozen
  // `tests/apiProxyRoute.test.ts` still passes unmodified. With it on, a
  // refusal — spoofed username header, unknown username, broken or ambiguous
  // configuration — arrives here as an exception rather than as a value,
  // precisely so that it cannot be mistaken for `null` ("send no key") and
  // forwarded upstream unauthenticated.
  //
  // The catch is unqualified on purpose. `PrincipalUnresolvedError` is the
  // expected shape, but ANY failure to resolve a credential must fail closed,
  // and the response body is the same in every case so that "this username
  // does not exist" and "this deployment is misconfigured" are
  // indistinguishable from outside. Which one it was is in the resolver's own
  // `pilot_principal` log line, where the operator reads it and an attacker
  // does not.
  let principal: UpstreamPrincipal | null;
  try {
    principal = await resolveUpstreamPrincipal(request);
  } catch {
    log(503, 0, "principal_unresolved");
    return Response.json(
      { detail: "pilot_principal_unresolved" },
      { status: 503 }
    );
  }
  if (principal) headers.set("X-API-Key", principal.apiKey);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const body = hasBody ? await request.arrayBuffer() : undefined;

  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "manual",
      signal: request.signal,
    });
  } catch {
    log(502, 0, "upstream_unavailable");
    return Response.json(
      { detail: "api_upstream_unavailable" },
      { status: 502 }
    );
  }

  const responseHeaders = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value !== null) responseHeaders.set(name, value);
  }

  // Still the upstream stream, still unbuffered — see `countStreamedBytes`.
  const counted = countStreamedBytes(upstream.body, request.signal, (bytes) =>
    log(upstream.status, bytes)
  );

  return new Response(counted, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

/** Resolve the operator-controlled internal base and encoded route path. */
function buildUpstreamUrl(request: Request, path: readonly string[]): URL {
  const base = new URL(
    process.env.API_INTERNAL_BASE ?? "http://localhost:8000"
  );
  if (!["http:", "https:"].includes(base.protocol)) {
    throw new Error("unsupported API_INTERNAL_BASE protocol");
  }
  if (base.username || base.password) {
    throw new Error("API_INTERNAL_BASE must not contain credentials");
  }

  const encodedPath = path.map(encodeURIComponent).join("/");
  const baseWithSlash = base.href.endsWith("/") ? base.href : `${base.href}/`;
  const upstream = new URL(encodedPath, baseWithSlash);
  upstream.search = new URL(request.url).search;
  return upstream;
}
