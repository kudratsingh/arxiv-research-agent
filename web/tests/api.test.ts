import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ApiError, getJob, streamUrl, submitResearch } from "@/lib/api";

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
