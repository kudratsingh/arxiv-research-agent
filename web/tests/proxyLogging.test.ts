/**
 * WO-30 criterion 4 — C6's proxy request log, and the three things it must
 * never contain.
 *
 * THE CRITERION, VERBATIM: "A test feeds a request containing a key, a body,
 * and a raw job id and asserts none of the three appears in the log line."
 * That test is `the redaction proof` below, and it is written the hard way on
 * purpose — it drives the REAL route handler (the same `GET`/`POST` exports
 * `apiProxyRoute.test.ts` imports), captures the real `process.stdout.write`,
 * and searches the emitted bytes for each secret. A test that called
 * `formatProxyLogLine` with a hand-built record would prove the formatter
 * redacts, which is not the claim; the claim is that the *proxy* does.
 *
 * THE TEMPLATE SET IS DERIVED FROM THE CONTRACT, NOT FROM THE MODULE. C6 says
 * "path **template**", and a whitelist of literal segments is only a
 * redaction guarantee if the whitelist cannot quietly grow. So
 * `contract/openapi.json` — the same document `npm run contract:check` gates
 * the generated types against — is parsed here, every path in it is
 * round-tripped through `pathTemplate` with synthetic ids substituted, and
 * the literal set is compared with `LITERAL_SEGMENTS` in both directions. A
 * new endpoint, or a widened whitelist, is a red test.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "@/app/api/[...path]/route";
import {
  LITERAL_SEGMENTS,
  PROXY_LOG_EVENT,
  REDACTED_SEGMENT,
  countStreamedBytes,
  emitProxyLog,
  formatProxyLogLine,
  pathTemplate,
} from "@/lib/server/proxyLog";

const WEB_ROOT = path.resolve(__dirname, "..");
const CONTRACT = JSON.parse(
  readFileSync(path.join(WEB_ROOT, "contract", "openapi.json"), "utf8"),
) as { paths: Record<string, unknown> };

const originalFetch = globalThis.fetch;
const originalApiBase = process.env.API_INTERNAL_BASE;
const originalApiKey = process.env.ARXIV_API_KEY;

/** Every JSON line the code under test wrote to stdout during one test. */
let written: string[] = [];

function context(...segments: string[]) {
  return { params: Promise.resolve({ path: segments }) };
}

/** The proxy log lines, parsed. */
function logLines(): Record<string, unknown>[] {
  return written
    .filter((line) => line.includes(PROXY_LOG_EVENT))
    .map((line) => JSON.parse(line) as Record<string, unknown>);
}

beforeEach(() => {
  written = [];
  vi.spyOn(process.stdout, "write").mockImplementation(((chunk: unknown) => {
    written.push(String(chunk));
    return true;
  }) as typeof process.stdout.write);
  process.env.API_INTERNAL_BASE = "http://app:8000";
  process.env.ARXIV_API_KEY = "server-only-secret";
});

afterEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = originalFetch;
  if (originalApiBase === undefined) delete process.env.API_INTERNAL_BASE;
  else process.env.API_INTERNAL_BASE = originalApiBase;
  if (originalApiKey === undefined) delete process.env.ARXIV_API_KEY;
  else process.env.ARXIV_API_KEY = originalApiKey;
});

// ---------------------------------------------------------------- the template

describe("the path template is a whitelist, so an id cannot leak by being unusual", () => {
  it("keeps contract literals and replaces everything else", () => {
    expect(pathTemplate(["research", "8f14e45f-ea8d-4b1a-9d0e-2f0a1c3b5d77", "stream"])).toBe(
      "/research/{id}/stream",
    );
    expect(pathTemplate(["conversations", "baseline-populated"])).toBe(
      "/conversations/{id}",
    );
    expect(pathTemplate(["healthz"])).toBe("/healthz");
  });

  it("redacts a segment that merely LOOKS harmless", () => {
    // Ids in this product are opaque strings, not always uuids: the seeded
    // fixtures are `baseline-populated`, and a conversation title could
    // become part of a path one day. The rule is "not a contract literal",
    // never "looks like an id".
    for (const segment of ["ok", "42", "me", "admin", "..", "%2e%2e"]) {
      expect(pathTemplate(["conversations", segment])).toBe(`/conversations/${REDACTED_SEGMENT}`);
    }
  });

  it("round-trips every path in contract/openapi.json", () => {
    for (const contractPath of Object.keys(CONTRACT.paths)) {
      const segments = contractPath
        .split("/")
        .filter((segment) => segment !== "")
        .map((segment) =>
          segment.startsWith("{") ? "01J8ZP-a-real-looking-identifier" : segment,
        );
      const expected = `/${segments
        .map((segment, index) =>
          contractPath.split("/").filter((s) => s !== "")[index]?.startsWith("{")
            ? REDACTED_SEGMENT
            : segment,
        )
        .join("/")}`;
      expect(pathTemplate(segments), `${contractPath} does not round-trip`).toBe(expected);
    }
  });

  it("whitelists exactly the literal segments the contract contains", () => {
    const fromContract = new Set<string>();
    for (const contractPath of Object.keys(CONTRACT.paths)) {
      for (const segment of contractPath.split("/")) {
        if (segment !== "" && !segment.startsWith("{")) fromContract.add(segment);
      }
    }
    // Both directions: a new endpoint fails until the set is updated, and a
    // segment added to the set with no endpoint behind it fails immediately.
    expect([...LITERAL_SEGMENTS].sort()).toEqual([...fromContract].sort());
  });

  it("renders an empty segment list rather than throwing", () => {
    expect(pathTemplate([])).toBe("/");
  });
});

// ------------------------------------------------------------- the line shape

describe("C6's five fields", () => {
  it("emits method, path template, status, duration and bytes", () => {
    const line = JSON.parse(
      formatProxyLogLine({
        method: "GET",
        pathTemplate: "/research/{id}/stream",
        status: 200,
        durationMs: 12,
        bytes: 4096,
      }),
    ) as Record<string, unknown>;
    expect(line).toEqual({
      event: PROXY_LOG_EVENT,
      method: "GET",
      path: "/research/{id}/stream",
      status: 200,
      duration_ms: 12,
      bytes: 4096,
    });
  });

  it("adds `outcome` only when the proxy answered locally", () => {
    const local = JSON.parse(
      formatProxyLogLine({
        method: "GET",
        pathTemplate: "/healthz",
        status: 502,
        durationMs: 1,
        bytes: 0,
        outcome: "upstream_unavailable",
      }),
    ) as Record<string, unknown>;
    // Without it, a 502 the upstream returned and a 502 the proxy invented
    // are the same line — and they are very different incidents.
    expect(local["outcome"]).toBe("upstream_unavailable");
  });

  it("survives a stdout that refuses to be written to", () => {
    vi.spyOn(process.stdout, "write").mockImplementation(() => {
      throw new Error("EPIPE");
    });
    expect(() =>
      emitProxyLog({
        method: "GET",
        pathTemplate: "/healthz",
        status: 200,
        durationMs: 1,
        bytes: 2,
      }),
    ).not.toThrow();
  });
});

// ------------------------------------------------------------- the whole route

describe("one line per proxied request, from the real route handler", () => {
  it("logs the template, the upstream status and the streamed bytes", async () => {
    globalThis.fetch = vi.fn(
      async () =>
        new Response("event: job_started\ndata: {}\n\n", {
          headers: { "content-type": "text/event-stream" },
        }),
    ) as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/research/job-abc/stream"),
      context("research", "job-abc", "stream"),
    );
    // The count is of bytes that reached the browser, so the body has to be
    // read before the line exists — which is also the honest moment for an
    // SSE stream's duration.
    const body = await response.text();

    expect(logLines()).toHaveLength(1);
    expect(logLines()[0]).toMatchObject({
      method: "GET",
      path: "/research/{id}/stream",
      status: 200,
      bytes: new TextEncoder().encode(body).length,
    });
    expect(logLines()[0]?.["duration_ms"]).toBeTypeOf("number");
  });

  it("logs a local 503 as misconfigured and a local 502 as unavailable", async () => {
    process.env.API_INTERNAL_BASE = "file:///private/api";
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
    await GET(new Request("http://web.local/api/healthz"), context("healthz"));

    process.env.API_INTERNAL_BASE = "http://app:8000";
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("connection refused");
    }) as unknown as typeof fetch;
    await GET(new Request("http://web.local/api/healthz"), context("healthz"));

    expect(logLines()).toMatchObject([
      { status: 503, outcome: "misconfigured", bytes: 0 },
      { status: 502, outcome: "upstream_unavailable", bytes: 0 },
    ]);
  });

  it("logs a bodiless upstream response as zero bytes", async () => {
    globalThis.fetch = vi.fn(
      async () => new Response(null, { status: 204 }),
    ) as unknown as typeof fetch;

    await GET(
      new Request("http://web.local/api/conversations/abc"),
      context("conversations", "abc"),
    );
    expect(logLines()).toMatchObject([
      { status: 204, path: "/conversations/{id}", bytes: 0 },
    ]);
  });
});

// ------------------------------------------------------------- the redaction

describe("the redaction proof — a key, a body and a raw job id", () => {
  const API_KEY = "server-only-secret";
  const RAW_JOB_ID = "9c1b7e42-raw-job-id-that-must-not-be-logged";
  const BODY_SECRET = "a research question nobody else may read";
  const QUERY_SECRET = "cursor-token-7";

  it("puts none of the three, nor the query string, in the log line", async () => {
    let sawKey = "";
    globalThis.fetch = vi.fn(async (_input, init) => {
      sawKey = new Headers(init?.headers).get("X-API-Key") ?? "";
      return Response.json({ status: "accepted" });
    }) as unknown as typeof fetch;

    const response = await POST(
      new Request(
        `http://web.local/api/research/${RAW_JOB_ID}/review?cursor=${QUERY_SECRET}`,
        {
          method: "POST",
          headers: {
            "content-type": "application/json",
            // A header a client should never send, sent anyway. It must not
            // survive into the log any more than the injected one does.
            authorization: `Bearer ${API_KEY}`,
          },
          body: JSON.stringify({ query: BODY_SECRET }),
        },
      ),
      context("research", RAW_JOB_ID, "review"),
    );
    await response.text();

    // The key really was injected upstream — otherwise this test would be
    // asserting the absence of something that never existed.
    expect(sawKey).toBe(API_KEY);

    const emitted = written.join("");
    expect(emitted).not.toContain(API_KEY);
    expect(emitted).not.toContain(RAW_JOB_ID);
    expect(emitted).not.toContain(BODY_SECRET);
    expect(emitted).not.toContain(QUERY_SECRET);
    expect(emitted).not.toContain("Bearer");
    expect(emitted).not.toContain("X-API-Key");

    expect(logLines()).toMatchObject([
      { method: "POST", path: "/research/{id}/review", status: 200 },
    ]);
  });

  it("cannot be defeated by an id that contains the whole secret", async () => {
    // A path segment is redacted wholesale, never pattern-matched, so an id
    // that embeds a key-shaped substring is redacted for the same reason a
    // plain one is.
    expect(pathTemplate(["research", `${API_KEY}-and-more`])).toBe(
      `/research/${REDACTED_SEGMENT}`,
    );
  });

  it("logs no header, no body and no URL anywhere in the emitted JSON", async () => {
    globalThis.fetch = vi.fn(
      async () => Response.json({ detail: "invalid_api_key" }, { status: 401 }),
    ) as unknown as typeof fetch;

    const response = await GET(
      new Request("http://web.local/api/research/secret-id?x=y", {
        headers: { accept: "application/json", cookie: "session=leak-me" },
      }),
      context("research", "secret-id"),
    );
    await response.text();

    const keys = Object.keys(logLines()[0] ?? {});
    // An allowlist of KEYS, not a search for known secrets: a field added
    // later cannot smuggle a value in without failing here first.
    expect(keys.sort()).toEqual(
      ["bytes", "duration_ms", "event", "method", "path", "status"].sort(),
    );
    expect(written.join("")).not.toContain("leak-me");
    expect(written.join("")).not.toContain("secret-id");
  });
});

// ---------------------------------------------------------- the retained sample

describe("ci/proxy-log-sample.txt is evidence, not decoration", () => {
  const SAMPLE = path.join(WEB_ROOT, "..", "ci", "proxy-log-sample.txt");
  const lines = readFileSync(SAMPLE, "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "" && !line.startsWith("#"));

  it("is a real capture: every line parses and carries C6's fields", () => {
    expect(lines.length).toBeGreaterThan(5);
    for (const line of lines) {
      const parsed = JSON.parse(line) as Record<string, unknown>;
      expect(parsed["event"]).toBe(PROXY_LOG_EVENT);
      for (const field of ["method", "path", "status", "duration_ms", "bytes"]) {
        expect(parsed[field], `${field} missing from: ${line}`).toBeDefined();
      }
    }
  });

  it("shows every outcome shape, including the two the proxy answers itself", () => {
    // A sample of only happy-path lines would not show that a locally
    // generated 502 is distinguishable from an upstream one, which is the
    // field an operator reads first during an incident.
    const outcomes = new Set(
      lines.map((line) => (JSON.parse(line) as { outcome?: string }).outcome ?? "proxied"),
    );
    expect([...outcomes].sort()).toEqual([
      "misconfigured",
      "proxied",
      "upstream_unavailable",
    ]);
  });

  it("contains no raw identifier — every dynamic segment is redacted", () => {
    for (const line of lines) {
      const { path: template } = JSON.parse(line) as { path: string };
      for (const segment of template.split("/").filter((s) => s !== "")) {
        // The whole redaction guarantee, re-read off the committed artifact:
        // a segment is either a contract literal or the placeholder. There is
        // no third possibility, and a sample containing one would mean the
        // running service had produced it.
        expect(
          LITERAL_SEGMENTS.has(segment) || segment === REDACTED_SEGMENT,
          `${segment} in ${template} is neither a contract literal nor redacted`,
        ).toBe(true);
      }
    }
  });

  it("contains no query string, header name, or seeded fixture id", () => {
    const raw = readFileSync(SAMPLE, "utf8");
    const body = lines.join("\n");
    for (const forbidden of ["?", "X-API-Key", "authorization", "cookie", "Bearer"]) {
      expect(body, `sample lines contain ${forbidden}`).not.toContain(forbidden);
    }
    // The capture ran against the seeded stack, so these ids were in every
    // request URL. None may be in the log.
    for (const id of ["baseline-populated", "baseline-succeeded", "baseline-running"]) {
      expect(body).not.toContain(id);
    }
    // …and the header comment has to say where the file came from, or it is
    // a file nobody can date or trust.
    expect(raw).toContain("PROVENANCE");
  });
});

// ------------------------------------------------------------- the byte count

describe("byte counting does not buffer the stream", () => {
  it("passes chunks through as they arrive and settles once", async () => {
    const chunks = [new Uint8Array([1, 2, 3]), new Uint8Array([4, 5])];
    const source = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(chunk);
        controller.close();
      },
    });
    let counted: number[] = [];
    const out = countStreamedBytes(source, new AbortController().signal, (bytes) => {
      counted.push(bytes);
    });
    expect(out).not.toBeNull();

    const reader = (out as ReadableStream<Uint8Array>).getReader();
    const first = await reader.read();
    // The first chunk is readable before the source has closed — which is
    // what "unbuffered" means for SSE, and what a naive `arrayBuffer()` would
    // have destroyed.
    expect(first.value).toEqual(chunks[0]);
    let done = false;
    while (!done) done = (await reader.read()).done;

    await vi.waitFor(() => expect(counted).toEqual([5]));
  });

  it("settles on a client disconnect, so an abandoned stream still logs", async () => {
    const controller = new AbortController();
    const never = new ReadableStream<Uint8Array>({ start() {} });
    let counted: number | null = null;
    countStreamedBytes(never, controller.signal, (bytes) => {
      counted = bytes;
    });
    controller.abort();
    expect(counted).toBe(0);
  });

  it("returns null for a bodiless response and still settles", () => {
    let counted: number | null = null;
    expect(
      countStreamedBytes(null, new AbortController().signal, (bytes) => {
        counted = bytes;
      }),
    ).toBeNull();
    expect(counted).toBe(0);
  });
});
