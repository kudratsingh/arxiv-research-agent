import { describe, it, expect, afterEach } from "vitest";
import {
  API_FAILURE_KINDS,
  normalizeFailure,
  type ApiFailure,
  type ApiFailureKind,
  type NormalizeContext,
} from "@/lib/api/errors";

/**
 * One table over every `ApiFailure` kind the normalizer can produce.
 *
 * The cases are transcribed from the shapes 04-ARCHITECTURE.md §3.4
 * observed in the backend, not invented: the 429 object `detail`
 * (`src/api/auth.py:176-184`) that renders as raw JSON today, the 409
 * with embedded state, the 422 array, non-JSON bodies, abort, timeout,
 * and offline.
 */

function jsonResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {}
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });
}

function textResponse(
  body: string,
  status: number,
  contentType = "text/html"
): Response {
  return new Response(body, {
    status,
    headers: { "content-type": contentType },
  });
}

function named(name: string, message = "boom"): Error {
  const err = new Error(message);
  err.name = name;
  return err;
}

interface Case {
  name: string;
  kind: ApiFailureKind;
  make: () => unknown;
  context?: NormalizeContext;
  /**
   * A distinctive token from the raw payload. `message` must never
   * contain it — raw codes are disclosure-only (§3.4).
   */
  rawToken?: string;
  assert?: (failure: ApiFailure) => void;
}

const CASES: Case[] = [
  {
    name: "401 with WWW-Authenticate",
    kind: "unauthorized",
    rawToken: "missing_api_key",
    make: () =>
      jsonResponse({ detail: "missing_api_key" }, 401, {
        "www-authenticate": "Bearer",
      }),
    assert: (f) => {
      expect(f).toMatchObject({ kind: "unauthorized", status: 401 });
      expect(f.raw).toEqual({ detail: "missing_api_key" });
    },
  },
  {
    name: "404 for a missing job",
    kind: "not_found",
    rawToken: "job_not_found",
    make: () => jsonResponse({ detail: "job_not_found" }, 404),
    assert: (f) => {
      expect(f).toMatchObject({ kind: "not_found", status: 404 });
      // Ownership mismatch is a 404, never a 403 (`routes.py:59-84`),
      // so the sentence may not claim deletion or a permission problem.
      expect(f.message.toLowerCase()).not.toMatch(
        /deleted|permission|forbidden/
      );
    },
  },
  {
    name: "409 with the state embedded in the detail string",
    kind: "conflict",
    rawToken: "job_not_awaiting_review",
    make: () =>
      jsonResponse(
        { detail: "job_not_awaiting_review (status=running)" },
        409
      ),
    assert: (f) => {
      expect(f).toMatchObject({ kind: "conflict", status: 409 });
      expect((f as Extract<ApiFailure, { kind: "conflict" }>).state).toBe(
        "running"
      );
      expect(f.message).toContain("running");
    },
  },
  {
    name: "409 export conflict with no embedded state",
    kind: "conflict",
    rawToken: "job_has_no_result",
    make: () => jsonResponse({ detail: "job_has_no_result" }, 409),
    assert: (f) => {
      expect((f as Extract<ApiFailure, { kind: "conflict" }>).state).toBe(
        undefined
      );
    },
  },
  {
    name: "422 array detail, one field",
    kind: "validation",
    rawToken: "string_too_long",
    make: () =>
      jsonResponse(
        {
          detail: [
            {
              loc: ["body", "query"],
              msg: "String should have at most 8000 characters",
              type: "string_too_long",
            },
          ],
        },
        422
      ),
    assert: (f) => {
      const fields = (f as Extract<ApiFailure, { kind: "validation" }>).fields;
      expect(fields).toEqual([
        {
          path: "query",
          message: "String should have at most 8000 characters",
          type: "string_too_long",
        },
      ]);
      expect(f.message).toBe(
        "query: String should have at most 8000 characters."
      );
    },
  },
  {
    name: "422 array detail, several fields",
    kind: "validation",
    make: () =>
      jsonResponse(
        {
          detail: [
            { loc: ["body", "query"], msg: "field required", type: "missing" },
            {
              loc: ["body", "plan", "sub_questions", 0],
              msg: "too long",
              type: "string_too_long",
            },
          ],
        },
        422
      ),
    assert: (f) => {
      const fields = (f as Extract<ApiFailure, { kind: "validation" }>).fields;
      expect(fields.map((issue) => issue.path)).toEqual([
        "query",
        "plan.sub_questions.0",
      ]);
      expect(f.message).toBe("2 fields need attention: query, plan.sub_questions.0.");
    },
  },
  {
    name: "422 with a bare string detail",
    kind: "validation",
    rawToken: "query_too_long",
    make: () => jsonResponse({ detail: "query_too_long" }, 422),
    assert: (f) => {
      expect((f as Extract<ApiFailure, { kind: "validation" }>).fields).toEqual(
        []
      );
      expect(f.raw).toEqual({ detail: "query_too_long" });
    },
  },
  {
    name: "429 with the object detail and Retry-After",
    kind: "rate_limited",
    rawToken: "rate_limited",
    make: () =>
      jsonResponse(
        {
          detail: {
            error: "rate_limited",
            key_id: "local-preview",
            limit_per_hour: 20,
          },
        },
        429,
        { "retry-after": "45" }
      ),
    assert: (f) => {
      const failure = f as Extract<ApiFailure, { kind: "rate_limited" }>;
      expect(failure.retryAfterSec).toBe(45);
      expect(failure.limitPerHour).toBe(20);
      expect(failure.message).toBe(
        "Rate limit reached. Try again in about 45 seconds. This key allows 20 requests per hour."
      );
      // This is the case that renders as raw JSON today
      // (`web/lib/api.ts:129-137`).
      expect(failure.message).not.toContain("key_id");
    },
  },
  {
    name: "429 with no Retry-After header",
    kind: "rate_limited",
    make: () => jsonResponse({ detail: { error: "rate_limited" } }, 429),
    assert: (f) => {
      const failure = f as Extract<ApiFailure, { kind: "rate_limited" }>;
      expect(failure.retryAfterSec).toBe(60);
      expect(failure.limitPerHour).toBe(undefined);
      expect(failure.message).toContain("1 minute");
    },
  },
  {
    name: "502 from the Next.js proxy",
    kind: "upstream_unavailable",
    rawToken: "api_upstream_unavailable",
    make: () => jsonResponse({ detail: "api_upstream_unavailable" }, 502),
    assert: (f) =>
      expect(f).toMatchObject({ kind: "upstream_unavailable", status: 502 }),
  },
  {
    name: "503 from the Next.js proxy",
    kind: "proxy_misconfigured",
    rawToken: "api_proxy_misconfigured",
    make: () => jsonResponse({ detail: "api_proxy_misconfigured" }, 503),
    assert: (f) =>
      expect(f).toMatchObject({ kind: "proxy_misconfigured", status: 503 }),
  },
  {
    name: "500 with a JSON detail",
    kind: "server_error",
    rawToken: "internal_error",
    make: () => jsonResponse({ detail: "internal_error" }, 500),
    assert: (f) => expect(f).toMatchObject({ kind: "server_error", status: 500 }),
  },
  {
    name: "non-JSON 500 body",
    kind: "server_error",
    rawToken: "<title>502 Bad Gateway",
    make: () => textResponse("<html><title>502 Bad Gateway</title></html>", 500),
    assert: (f) => {
      expect(f.raw).toBe("<html><title>502 Bad Gateway</title></html>");
      expect(f.message).not.toContain("<");
    },
  },
  {
    name: "non-JSON body at an unmapped status",
    kind: "unknown",
    rawToken: "teapot",
    make: () => textResponse("teapot", 418, "text/plain"),
    assert: (f) => {
      expect(f).toMatchObject({ kind: "unknown", status: 418 });
      expect(f.raw).toBe("teapot");
      expect(f.message).toContain("418");
    },
  },
  {
    name: "empty body",
    kind: "not_found",
    make: () => new Response(null, { status: 404 }),
    assert: (f) => expect(f.raw).toBe(undefined),
  },
  {
    name: "an AbortError from the caller's signal",
    kind: "cancelled",
    make: () => named("AbortError", "The operation was aborted."),
  },
  {
    name: "an explicit cancellation flag",
    kind: "cancelled",
    make: () => new Error("aborted"),
    context: { cancelled: true },
  },
  {
    name: "our timeout, which aborts through the same controller",
    kind: "timeout",
    make: () => named("AbortError", "The operation was aborted."),
    context: { timedOut: true },
    assert: (f) => expect(f.kind).toBe("timeout"),
  },
  {
    name: "a TimeoutError from a runtime that has AbortSignal.timeout",
    kind: "timeout",
    make: () => named("TimeoutError"),
  },
  {
    name: "a network failure while the browser reports offline",
    kind: "offline",
    make: () => new TypeError("Failed to fetch"),
    context: { online: false },
    assert: (f) => expect(f.message).toContain("offline"),
  },
  {
    name: "a network failure while the browser reports online",
    kind: "offline",
    rawToken: "Failed to fetch",
    make: () => new TypeError("Failed to fetch"),
    context: { online: true },
    assert: (f) => expect(f.message).toContain("Could not reach the server"),
  },
  {
    name: "a thrown value that is nothing else",
    kind: "unknown",
    rawToken: "something odd",
    make: () => new Error("something odd"),
    assert: (f) => expect(f).toMatchObject({ kind: "unknown", status: null }),
  },
];

describe("normalizeFailure", () => {
  it.each(CASES.map((entry) => [entry.name, entry] as const))(
    "normalizes %s",
    async (_name, entry) => {
      const failure = await normalizeFailure(entry.make(), entry.context);

      expect(failure.kind).toBe(entry.kind);
      if (entry.assert) entry.assert(failure);

      // Criterion 3: every variant carries `{ message, raw }` and the
      // message is a sentence, never the payload.
      expect(typeof failure.message).toBe("string");
      expect(failure.message.length).toBeGreaterThan(0);
      expect("raw" in failure).toBe(true);
      expect(failure.message).not.toContain("{");
      expect(failure.message).not.toContain("[");
      expect(failure.message).not.toBe(JSON.stringify(failure.raw));
      if (entry.rawToken !== undefined) {
        expect(failure.message).not.toContain(entry.rawToken);
      }
    }
  );

  it("covers every one of the twelve ApiFailure kinds", async () => {
    const produced = new Set<ApiFailureKind>();
    for (const entry of CASES) {
      const failure = await normalizeFailure(entry.make(), entry.context);
      produced.add(failure.kind);
    }
    expect(API_FAILURE_KINDS).toHaveLength(12);
    expect([...produced].sort()).toEqual([...API_FAILURE_KINDS].sort());
  });

  it("reads a correlation id when the response carries one", async () => {
    const failure = await normalizeFailure(
      jsonResponse({ detail: "job_not_found" }, 404, {
        "x-request-id": "req-42",
      })
    );
    expect(failure.requestId).toBe("req-42");
  });

  it("leaves requestId absent when no header is present", async () => {
    const failure = await normalizeFailure(
      jsonResponse({ detail: "job_not_found" }, 404)
    );
    expect(failure.requestId).toBe(undefined);
    expect("requestId" in failure).toBe(false);
  });

  it("consumes the body only once", async () => {
    const response = jsonResponse({ detail: "job_not_found" }, 404);
    await normalizeFailure(response);
    // A second normalization of the same (now-drained) response must
    // still produce a usable failure rather than throwing.
    const second = await normalizeFailure(response);
    expect(second.kind).toBe("not_found");
  });
});

describe("offline detection without an injected flag", () => {
  const descriptor = Object.getOwnPropertyDescriptor(
    Navigator.prototype,
    "onLine"
  );

  afterEach(() => {
    if (descriptor) {
      Object.defineProperty(Navigator.prototype, "onLine", descriptor);
    }
  });

  it("falls back to navigator.onLine", async () => {
    Object.defineProperty(Navigator.prototype, "onLine", {
      configurable: true,
      get: () => false,
    });
    const failure = await normalizeFailure(new TypeError("Failed to fetch"));
    expect(failure.kind).toBe("offline");
    expect(failure.message).toContain("offline");
  });
});
