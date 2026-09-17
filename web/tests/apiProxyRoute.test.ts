/**
 * The same-origin proxy route handler, frozen (04-ARCHITECTURE.md §3.1).
 *
 * It drives `app/api/[...path]/route.ts` directly and proves what the handler
 * exists to do: the upstream path is encoded and the query preserved, the
 * server-only key is injected into the upstream request, request bodies and
 * upstream auth failures pass through unchanged, the auth-off local
 * configuration sends no header at all, a non-HTTP `API_INTERNAL_BASE` fails
 * closed, and an upstream network failure maps to a stable 502.
 *
 * THE FILE IS DELIBERATELY UNMODIFIED, AND THAT IS ITS SECOND JOB. WO-30
 * replaced the inline `process.env` read with `resolveUpstreamPrincipal()`
 * (MT-01 seam S1) and claimed the change was a no-op; the route's own header
 * names this test as the proof. Any edit here costs that proof.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  GET,
  POST,
} from "@/app/api/[...path]/route";

const originalFetch = globalThis.fetch;
const originalApiBase = process.env.API_INTERNAL_BASE;
const originalApiKey = process.env.ARXIV_API_KEY;

function context(...path: string[]) {
  return { params: Promise.resolve({ path }) };
}

beforeEach(() => {
  process.env.API_INTERNAL_BASE = "http://app:8000";
  process.env.ARXIV_API_KEY = "server-only-secret";
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalApiBase === undefined) delete process.env.API_INTERNAL_BASE;
  else process.env.API_INTERNAL_BASE = originalApiBase;
  if (originalApiKey === undefined) delete process.env.ARXIV_API_KEY;
  else process.env.ARXIV_API_KEY = originalApiKey;
});

describe("same-origin API proxy", () => {
  it("encodes the upstream path, preserves the query, and injects auth", async () => {
    let upstreamUrl = "";
    let upstreamInit: RequestInit | undefined;
    globalThis.fetch = vi.fn(async (input, init) => {
      upstreamUrl = String(input);
      upstreamInit = init;
      return new Response("event: job_started\ndata: {}\n\n", {
        headers: {
          "content-type": "text/event-stream",
          "cache-control": "no-cache",
          "x-accel-buffering": "no",
        },
      });
    }) as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/research/a%20b/stream?cursor=7", {
        headers: { accept: "text/event-stream", "last-event-id": "six" },
      }),
      context("research", "a b", "stream")
    );

    expect(upstreamUrl).toBe(
      "http://app:8000/research/a%20b/stream?cursor=7"
    );
    const headers = new Headers(upstreamInit?.headers);
    expect(headers.get("X-API-Key")).toBe("server-only-secret");
    expect(headers.get("accept")).toBe("text/event-stream");
    expect(headers.get("last-event-id")).toBe("six");
    expect(upstreamInit?.cache).toBe("no-store");
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("x-accel-buffering")).toBe("no");
    expect(await response.text()).toContain("job_started");
  });

  it("forwards request bodies and upstream auth failures unchanged", async () => {
    let postedBody = "";
    globalThis.fetch = vi.fn(async (_input, init) => {
      postedBody = new TextDecoder().decode(init?.body as ArrayBuffer);
      return Response.json(
        { detail: "invalid_api_key" },
        {
          status: 401,
          headers: { "www-authenticate": "ApiKey header=X-API-Key" },
        }
      );
    }) as unknown as typeof fetch;

    const response = await POST(
      new Request("http://web.local/api/research", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ query: "test" }),
      }),
      context("research")
    );

    expect(postedBody).toBe('{"query":"test"}');
    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toBe(
      "ApiKey header=X-API-Key"
    );
    await expect(response.json()).resolves.toEqual({
      detail: "invalid_api_key",
    });
  });

  it("omits the auth header in the auth-off local configuration", async () => {
    delete process.env.ARXIV_API_KEY;
    let headers = new Headers();
    globalThis.fetch = vi.fn(async (_input, init) => {
      headers = new Headers(init?.headers);
      return Response.json({ status: "ok" });
    }) as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/healthz"),
      context("healthz")
    );

    expect(headers.has("X-API-Key")).toBe(false);
    expect(response.status).toBe(200);
  });

  it("fails closed when the internal base is not an HTTP endpoint", async () => {
    process.env.API_INTERNAL_BASE = "file:///private/api";
    globalThis.fetch = vi.fn() as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/healthz"),
      context("healthz")
    );

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      detail: "api_proxy_misconfigured",
    });
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("maps upstream network failures to a stable 502", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("connection refused");
    }) as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/healthz"),
      context("healthz")
    );

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toEqual({
      detail: "api_upstream_unavailable",
    });
  });
});
