import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiError, getJob, streamUrl, submitResearch } from "@/lib/api";
import * as shim from "@/lib/api";
import * as surface from "@/lib/api/index";
import {
  DEFAULT_READ_TIMEOUT_MS,
  createConversation,
  deleteConversation,
  getConversation,
  listConversations,
  reviewPlan,
} from "@/lib/api";

// Vitest runs from `web/`, where its config lives.
const WEB_ROOT = process.cwd();

// Assembled at runtime — including in this file's own describe title —
// so `tests/` can be scanned for the literal alongside everything else.
const BYPASS_FIELD = ["hitl", "bypass"].join("_");

function readWebFile(relative: string): string {
  return readFileSync(join(WEB_ROOT, relative), "utf8");
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("submitResearch", () => {
  it("POSTs the query and returns the acceptance envelope", async () => {
    const envelope = {
      job_id: "j1",
      status: "pending",
      status_url: "/research/j1",
      stream_url: "/research/j1/stream",
    };
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(envelope, 202)
    );

    const got = await submitResearch("hallucination");
    expect(got).toEqual(envelope);

    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call?.[0]).toContain("/research");
    expect(call?.[1]?.method).toBe("POST");
    expect(JSON.parse(call?.[1]?.body as string)).toEqual({
      query: "hallucination",
    });
  });

  it("throws ApiError on non-2xx with the server's detail", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ detail: "query_too_long" }, 422)
    );
    try {
      await submitResearch("x".repeat(9000));
      throw new Error("expected submitResearch to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(422);
      expect((err as Error).message).toMatch(/query_too_long/);
    }
  });
});

describe("getJob", () => {
  it("fetches the job detail", async () => {
    const body = {
      job_id: "j1",
      status: "succeeded",
      query: "q",
      created_at: 0,
      started_at: 0,
      completed_at: 1,
      elapsed_sec: 1,
      result: "# hi",
      error: null,
      error_type: null,
      cost_usd: 0.01,
      llm_calls: 1,
      iterations: 1,
      quality_score: 0.9,
    };
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(body)
    );
    const got = await getJob("j1");
    expect(got.job_id).toBe("j1");
    expect(got.result).toBe("# hi");
  });

  it("throws ApiError when the job is missing", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse({ detail: "job_not_found" }, 404)
    );
    await expect(getJob("nope")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("streamUrl", () => {
  it("encodes the job_id path segment", () => {
    expect(streamUrl("j 1")).toContain("/research/j%201/stream");
  });
});

// ---------------------------------------------------------------------------
// WO-03 additions. Everything above this line is unchanged.
// ---------------------------------------------------------------------------

/** A fetch that only settles when its signal aborts. */
function hangingFetch(): ReturnType<typeof vi.fn> {
  return vi.fn(
    (_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        if (!signal) return;
        signal.addEventListener("abort", () => {
          const err = new Error("The operation was aborted.");
          err.name = "AbortError";
          reject(err);
        });
      })
  );
}

async function failureOf(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (err) {
    return err as ApiError;
  }
  throw new Error("expected the call to reject");
}

describe("abort and timeout on reads", () => {
  it("aborts a read when the caller's signal fires", async () => {
    globalThis.fetch = hangingFetch() as unknown as typeof fetch;
    const controller = new AbortController();
    const pending = failureOf(getJob("j1", { signal: controller.signal }));
    controller.abort();
    const err = await pending;

    expect(err).toBeInstanceOf(ApiError);
    expect(err.failure.kind).toBe("cancelled");
    expect(err.status).toBe(0);
  });

  it("never sends a request when the signal is already aborted", async () => {
    const fetchMock = hangingFetch();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const err = await failureOf(
      getJob("j1", { signal: AbortSignal.abort() })
    );

    expect(err.failure.kind).toBe("cancelled");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes a signal to fetch even when the caller supplies none", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse({ job_id: "j1", status: "succeeded" })
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    await getJob("j1");

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(init?.signal).toBeInstanceOf(AbortSignal);
    expect(init?.signal?.aborted).toBe(false);
  });

  it("times out a read with an explicit ceiling", async () => {
    globalThis.fetch = hangingFetch() as unknown as typeof fetch;
    const err = await failureOf(listConversations({ timeoutMs: 5 }));

    expect(err.failure.kind).toBe("timeout");
    expect(err.failure.message).toContain("too long");
  });

  it("applies a default timeout to every read with no options", async () => {
    vi.useFakeTimers();
    try {
      globalThis.fetch = hangingFetch() as unknown as typeof fetch;
      const reads = [
        getJob("j1"),
        listConversations(),
        getConversation("c1"),
      ].map((promise) => failureOf(promise));

      await vi.advanceTimersByTimeAsync(DEFAULT_READ_TIMEOUT_MS + 1);

      for (const err of await Promise.all(reads)) {
        expect(err.failure.kind).toBe("timeout");
      }
    } finally {
      vi.useRealTimers();
    }
  });

  it("leaves billable writes without a default timeout", async () => {
    // Aborting POST /research does not cancel the job the server
    // already created, so a client-side ceiling would only hide a run
    // the user is still paying for.
    vi.useFakeTimers();
    try {
      let release: ((value: Response) => void) | undefined;
      globalThis.fetch = vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          })
      ) as unknown as typeof fetch;

      const pending = submitResearch("q");
      await vi.advanceTimersByTimeAsync(DEFAULT_READ_TIMEOUT_MS * 10);

      release?.(
        jsonResponse(
          {
            job_id: "j1",
            status: "pending",
            status_url: "/research/j1",
            stream_url: "/research/j1/stream",
          },
          202
        )
      );
      await expect(pending).resolves.toMatchObject({ job_id: "j1" });
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("normalized failures reach callers", () => {
  it("carries the normalized failure alongside the legacy message", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { error: "rate_limited", key_id: "k", limit_per_hour: 20 },
        }),
        {
          status: 429,
          headers: {
            "content-type": "application/json",
            "retry-after": "30",
          },
        }
      )
    );
    const err = await failureOf(submitResearch("q"));

    expect(err.status).toBe(429);
    expect(err.failure.kind).toBe("rate_limited");
    // The user-facing sentence never contains the payload...
    expect(err.failure.message).not.toContain("key_id");
    // ...while the legacy `message` channel stays byte-compatible with
    // the superseded `safeError()` so existing UI copy is unchanged.
    expect(err.message).toContain("rate_limited");
  });

  it("falls back to HTTP status text for a non-JSON body", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response("<html>nope</html>", {
        status: 500,
        statusText: "Internal Server Error",
        headers: { "content-type": "text/html" },
      })
    );
    const err = await failureOf(getJob("j1"));

    expect(err.message).toBe("HTTP 500 Internal Server Error");
    expect(err.failure.kind).toBe("server_error");
  });

  it("wraps a transport failure without losing its message", async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch;
    const err = await failureOf(getConversation("c1"));

    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
    expect(err.failure.kind).toBe("offline");
    expect(err.message).toBe("Failed to fetch");
  });
});

/**
 * WO-31 DELETED `lib/api.ts`, THE M0 COMPATIBILITY SHIM.
 *
 * This block used to assert that the shim re-exported the surface rather
 * than re-implementing it. There is no shim any more, so that claim has no
 * subject — but the claim underneath it is now MORE load-bearing than it
 * was, not less, and it is the reason criterion 1 ("no module imports a
 * deleted file") holds without touching ~50 import sites:
 *
 * `@/lib/api` used to name `lib/api.ts`. With that file gone the SAME
 * specifier resolves, by directory-index resolution, to `lib/api/index.ts`
 * — the real module the shim only ever re-exported. So no call site changed
 * spelling, nothing points at a deleted file, and the build and typecheck
 * prove it for the whole tree.
 *
 * What this block pins is that the resolution really is the real surface
 * and not some other module that happens to answer to the name: every
 * pinned export is the SAME BINDING as `@/lib/api/index`'s. Deleting the
 * file without this would leave "it still resolves" as an assumption.
 */
describe("`@/lib/api` resolves to the real surface, with the shim deleted", () => {
  const NAMES = [
    "submitResearch",
    "getJob",
    "reviewPlan",
    "streamUrl",
    "listConversations",
    "getConversation",
    "createConversation",
    "deleteConversation",
    "ApiError",
  ] as const;

  it("is not a file: lib/api.ts is gone and lib/api/index.ts is what answers", () => {
    expect(existsSync(join(WEB_ROOT, "lib/api.ts"))).toBe(false);
    expect(existsSync(join(WEB_ROOT, "lib/api/index.ts"))).toBe(true);
    // `lib/types.ts`, the other M0 shim, had no consumer outside the nine
    // deleted components and resolves to nothing at all.
    expect(existsSync(join(WEB_ROOT, "lib/types.ts"))).toBe(false);
  });

  it("carries every name 05-MIGRATION.md §1.1 pins, as the same binding", () => {
    for (const name of NAMES) {
      expect(shim).toHaveProperty(name);
      expect(shim[name]).toBe(surface[name]);
    }
  });

  it("keeps the callable surface callable", () => {
    for (const name of NAMES) {
      expect(typeof shim[name]).toBe("function");
    }
    expect(
      [
        submitResearch,
        getJob,
        reviewPlan,
        createConversation,
        listConversations,
        getConversation,
        deleteConversation,
      ].every((fn) => typeof fn === "function")
    ).toBe(true);
  });

  it("keeps API_BASE pointing at the same-origin proxy", () => {
    expect(shim.API_BASE).toBe("/api");
    expect(shim.API_BASE).toBe(surface.API_BASE);
  });
});

describe(`${BYPASS_FIELD} containment (H12)`, () => {
  const FIELD = BYPASS_FIELD;
  const ROOTS = ["app", "components", "lib", "tests"];
  const ALLOWED_PREFIX = join("lib", "api") + "/";

  function walk(dir: string, acc: string[] = []): string[] {
    for (const entry of readdirSync(join(WEB_ROOT, dir), {
      withFileTypes: true,
    })) {
      const relative = join(dir, entry.name);
      if (entry.isDirectory()) walk(relative, acc);
      else if (/\.tsx?$/.test(entry.name)) acc.push(relative);
    }
    return acc;
  }

  it("is referenced by no module outside lib/api", () => {
    const offenders = ROOTS.flatMap((root) => walk(root)).filter(
      (relative) =>
        !relative.startsWith(ALLOWED_PREFIX) &&
        readWebFile(relative).includes(FIELD)
    );
    expect(offenders).toEqual([]);
  });

  it("is still offered by the typed client", () => {
    // Removing it would be a false narrowing of the real API
    // (03-DESIGN-BRIEF.md §8.4).
    expect(readWebFile(join("lib", "api", "models.ts"))).toContain(
      `${FIELD}?: boolean`
    );
  });

  it("is never sent unless a caller opts in", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () =>
      jsonResponse(
        {
          job_id: "j1",
          status: "pending",
          status_url: "/research/j1",
          stream_url: "/research/j1/stream",
        },
        202
      )
    );
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    await submitResearch("q");
    await submitResearch("q", { conversation_id: "c1" });

    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      expect(Object.keys(JSON.parse(init.body as string))).not.toContain(FIELD);
    }
  });
});

describe("the committed OpenAPI snapshot", () => {
  const snapshot = JSON.parse(
    readWebFile(join("contract", "openapi.json"))
  ) as Record<string, unknown>;

  it("records the commit it was generated at", () => {
    const provenance = snapshot["x-provenance"] as Record<string, string>;
    expect(provenance).toBeDefined();
    expect(provenance.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(provenance.source).toContain("create_app().openapi()");
    expect(provenance.generated).toContain("DO NOT EDIT");
  });

  it("describes the frozen HTTP surface 04-ARCHITECTURE.md §3.1 lists", () => {
    expect(Object.keys(snapshot.paths as object).sort()).toEqual([
      "/conversations",
      "/conversations/{conversation_id}",
      "/healthz",
      // ADR 0058 and WO-W15. All learner paths are mounted unconditionally:
      // SR-07
      // keeps feature gating backend-only, so the document is identical
      // in every position of `enable_learner_profile` and
      // `enable_learn_content`; generated types never depend on a flag.
      "/learn/paths",
      "/learn/paths/{path_id}",
      "/learn/profile",
      "/learn/progress",
      "/research",
      "/research/{job_id}",
      "/research/{job_id}/export",
      "/research/{job_id}/review",
      "/research/{job_id}/stream",
    ]);
  });

  it("is the only source the generated types are built from", () => {
    const generated = readWebFile(
      join("lib", "api", "generated", "schema.d.ts")
    );
    expect(generated).toContain("auto-generated by openapi-typescript");
    expect(generated).toContain("Do not make direct changes to the file");
  });

  it("is aliased by models.ts rather than duplicated", () => {
    const models = readWebFile(join("lib", "api", "models.ts"));
    const schemaNames = Object.keys(
      (snapshot.components as { schemas: object }).schemas
    );
    const exported = [...models.matchAll(/^export type (\w+)/gm)].map(
      (match) => match[1]
    );
    const shared = exported.filter((name) =>
      schemaNames.includes(name as string)
    );

    expect(shared.length).toBeGreaterThanOrEqual(8);
    for (const name of shared) {
      expect(models).toContain(`Schemas["${name}"]`);
    }
  });
});
