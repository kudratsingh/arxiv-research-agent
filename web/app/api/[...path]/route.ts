/**
 * Same-origin proxy from the browser-facing Next.js service to FastAPI.
 *
 * The API key is read only in the Node.js runtime and injected into the
 * upstream request. It never enters the client bundle, URL, browser storage,
 * or EventSource constructor. Returning the upstream ReadableStream directly
 * preserves SSE and export-download behavior without buffering whole reports.
 */

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
  let upstreamUrl: URL;
  try {
    upstreamUrl = await buildUpstreamUrl(request, context);
  } catch {
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
  const apiKey = process.env.ARXIV_API_KEY;
  if (apiKey) headers.set("X-API-Key", apiKey);

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

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

/** Resolve the operator-controlled internal base and encoded route path. */
async function buildUpstreamUrl(
  request: Request,
  context: RouteContext
): Promise<URL> {
  const base = new URL(
    process.env.API_INTERNAL_BASE ?? "http://localhost:8000"
  );
  if (!["http:", "https:"].includes(base.protocol)) {
    throw new Error("unsupported API_INTERNAL_BASE protocol");
  }
  if (base.username || base.password) {
    throw new Error("API_INTERNAL_BASE must not contain credentials");
  }

  const { path } = await context.params;
  const encodedPath = path.map(encodeURIComponent).join("/");
  const baseWithSlash = base.href.endsWith("/") ? base.href : `${base.href}/`;
  const upstream = new URL(encodedPath, baseWithSlash);
  upstream.search = new URL(request.url).search;
  return upstream;
}
