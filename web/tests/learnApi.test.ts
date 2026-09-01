import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import listFixture from "@/contract/fixtures/learn.paths.json";
import progressFixture from "@/contract/fixtures/learn.progress.json";
import {
  getLearnPath,
  getLearnerProgress,
  listLearnPaths,
} from "@/lib/api";

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function response(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("learning content reads", () => {
  it("lists committed path summaries through the same-origin proxy", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(listFixture.body));
    await expect(listLearnPaths()).resolves.toEqual(listFixture.body);
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe(
      "/api/learn/paths"
    );
  });

  it("encodes the path id and never requests paper full text", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(detailFixture.body));
    await expect(getLearnPath("fixture/guided read")).resolves.toEqual(
      detailFixture.body
    );
    const url = String(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]);
    expect(url).toBe("/api/learn/paths/fixture%2Fguided%20read");
    expect(url).not.toMatch(/pdf|full.?text/i);
  });

  it("reads the event-derived progress summary independently", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(progressFixture.body));
    await expect(getLearnerProgress()).resolves.toEqual(progressFixture.body);
    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe(
      "/api/learn/progress"
    );
  });
});
