import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import listFixture from "@/contract/fixtures/learn.paths.json";
import progressFixture from "@/contract/fixtures/learn.progress.json";
import sessionFixture from "@/contract/fixtures/learn.session.awaiting.json";
import {
  DEFAULT_READ_TIMEOUT_MS,
  createLearnSession,
  getLearnPath,
  getLearnSession,
  getLearnerProgress,
  listLearnPaths,
  submitLearnSessionTurn,
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

describe("guided-session client writes", () => {
  /** The two calls that spend. Neither may be retried automatically. */
  function init(call = 0): RequestInit {
    return vi.mocked(globalThis.fetch).mock.calls[call]?.[1] as RequestInit;
  }

  it("starts a session with the path and resource, and no timeout", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({
        session_id: "abc123",
        status: "pending",
        status_url: "/learn/sessions/abc123",
        stream_url: "/research/abc123/stream",
      })
    );
    await expect(
      createLearnSession({
        path_id: "fixture-guided-read",
        resource_id: "arxiv:1706.03762",
      })
    ).resolves.toMatchObject({ session_id: "abc123" });

    expect(vi.mocked(globalThis.fetch).mock.calls[0]?.[0]).toBe(
      "/api/learn/sessions"
    );
    expect(init().method).toBe("POST");
  });

  it("reads a session snapshot, encoding the id", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(sessionFixture.body));
    await expect(getLearnSession("a b/c")).resolves.toEqual(sessionFixture.body);
    expect(String(vi.mocked(globalThis.fetch).mock.calls[0]?.[0])).toBe(
      "/api/learn/sessions/a%20b%2Fc"
    );
  });

  it("submits the learner's own words verbatim, with the end flag beside them", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({ session_id: "abc123", status: "awaiting_learner", accepted: true })
    );
    await expect(
      submitLearnSessionTurn("abc123", {
        message: "  I am unsure why the scaling matters.  ",
        end_session: true,
      })
    ).resolves.toMatchObject({ accepted: true });

    expect(String(vi.mocked(globalThis.fetch).mock.calls[0]?.[0])).toBe(
      "/api/learn/sessions/abc123/turn"
    );
    // Whitespace is the caller's to normalise: the client is a transport and
    // never edits a learner's prose on the way past.
    expect(JSON.parse(String(init().body))).toEqual({
      message: "  I am unsure why the scaling matters.  ",
      end_session: true,
    });
  });

  it.each([
    [
      "createLearnSession",
      () =>
        createLearnSession({
          path_id: "fixture-guided-read",
          resource_id: "arxiv:1706.03762",
        }),
      { session_id: "abc123", status: "pending", status_url: "", stream_url: "" },
    ],
    [
      "submitLearnSessionTurn",
      () => submitLearnSessionTurn("abc123", { message: "x", end_session: false }),
      { session_id: "abc123", status: "awaiting_learner", accepted: true },
    ],
  ])("leaves %s without a default timeout", async (_name, call, body) => {
    // Same argument as `POST /research` (see tests/api.test.ts): aborting a
    // billable write does not cancel the work the server already started, so
    // a client-side ceiling would only hide a turn the learner is still
    // paying for. A session turn resumes a graph that calls a model.
    vi.useFakeTimers();
    try {
      let release: ((value: Response) => void) | undefined;
      globalThis.fetch = vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          })
      ) as unknown as typeof fetch;

      const pending = call();
      await vi.advanceTimersByTimeAsync(DEFAULT_READ_TIMEOUT_MS * 10);
      release?.(response(body));
      await expect(pending).resolves.toMatchObject({ session_id: "abc123" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("gives a session read the same bounded timeout every other read has", async () => {
    vi.useFakeTimers();
    try {
      globalThis.fetch = vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError"))
            );
          })
      ) as unknown as typeof fetch;

      const pending = getLearnSession("abc123");
      const settled = expect(pending).rejects.toThrow();
      await vi.advanceTimersByTimeAsync(DEFAULT_READ_TIMEOUT_MS + 1);
      await settled;
    } finally {
      vi.useRealTimers();
    }
  });
});
