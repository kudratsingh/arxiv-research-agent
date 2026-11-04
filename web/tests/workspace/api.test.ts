import { afterEach, describe, expect, it, vi } from "vitest";
import {
  displayDate,
  errorMessage,
  normalizeReaderReturnTo,
  readerHref,
  requestId,
  workspaceRequest,
  WorkspaceError,
} from "@/lib/workspace/api";
import {
  DRAFT_KEY,
  loadDraft,
  storeDraft,
  type ReaderDraft,
} from "@/lib/workspace/drafts";

describe("controller reader return focus", () => {
  it("retains Today focus, encoding it as data and dropping unrelated parameters", () => {
    expect(normalizeReaderReturnTo("/workspace/today?focus=arxiv%3A2610.00001&extra=1#notes"))
      .toBe("/workspace/today?focus=arxiv%3A2610.00001");
    expect(normalizeReaderReturnTo(`/workspace/today?focus=${"a".repeat(500)}`))
      .toBe(`/workspace/today?focus=${"a".repeat(500)}`);
    expect(normalizeReaderReturnTo("/workspace/today?focus=a%26return_to%3Dhttps%3A%2F%2Fevil.example"))
      .toBe("/workspace/today?focus=a%26return_to%3Dhttps%3A%2F%2Fevil.example");
  });
  it.each(["", "a".repeat(501), "%00bad", "a%0Ab", "a%5Cb", "%7Fbad"])(
    "drops empty, oversized, or unsafe focus %s", (focus) => {
      expect(normalizeReaderReturnTo(`/workspace/today?focus=${focus}`)).toBe("/workspace/today");
    });
  it("keeps exact Library and Review returns and retains Radar focus", () => {
    expect(normalizeReaderReturnTo("/workspace/library?view=notes&focus=a")).toBe("/workspace/library?view=notes");
    const packet = `review-${"a".repeat(32)}`;
    expect(normalizeReaderReturnTo(`/workspace/review?packet=${packet}&focus=a`)).toBe(`/workspace/review?packet=${packet}`);
    expect(normalizeReaderReturnTo("/workspace/radar?q=test&focus=a")).toBe("/workspace/radar?q=test&focus=a");
  });
  it("preserves the bounded Radar page snapshot and focused work through Reader", () => {
    const params = new URLSearchParams({ q: "retrieval", source_id: "arxiv-cs-lg", access_state: "excerpt", status: "saved", days: "30", cursor: "page-cursor", as_of: "2026-11-02T15:00:00Z", focus: "arxiv:2610.00001", extra: "discard" });
    const result = new URL(normalizeReaderReturnTo(`/workspace/radar?${params}#notes`), "http://localhost");
    params.delete("extra");
    expect(result.pathname).toBe("/workspace/radar");
    expect(result.searchParams.toString()).toBe(params.toString());
    expect(result.hash).toBe("");
  });
  it.each([["cursor", 2048], ["as_of", 80], ["focus", 500]] as const)("bounds Radar %s and rejects encoded control data", (key, limit) => {
    const accepted = new URLSearchParams({ [key]: "a".repeat(limit) });
    expect(normalizeReaderReturnTo(`/workspace/radar?${accepted}`)).toBe(`/workspace/radar?${accepted}`);
    for (const value of ["a".repeat(limit + 1), "unsafe\nvalue", "unsafe\\value", "unsafe\x7fvalue"]) {
      const rejected = new URLSearchParams({ [key]: value });
      expect(normalizeReaderReturnTo(`/workspace/radar?${rejected}`)).toBe("/workspace/radar");
    }
  });
  it.each(["https://evil.example/workspace/today?focus=a", "//evil.example/workspace/today?focus=a", "/workspace/today/../../evil?focus=a"])(
    "rejects hostile return destinations %s", (value) => expect(normalizeReaderReturnTo(value)).toBe("/workspace/today"));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  sessionStorage.clear();
});
describe("live workspace boundary", () => {
  it("uses the existing same-origin credential proxy and an explicit body", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ revision: 2 }));
    vi.stubGlobal("fetch", fetch);
    await expect(workspaceRequest("profile", { revision: 1 })).resolves.toEqual(
      { revision: 2 },
    );
    expect(fetch.mock.calls[0]![0]).toBe("/api/workspace/profile");
    const init = fetch.mock.calls[0]![1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(init.body).toBe('{"revision":1}');
    expect(init).not.toHaveProperty("credentials");
    expect(requestId()).toMatch(/-/);
  });
  it("performs noncached reads and preserves conflict semantics", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({}))
      .mockResolvedValueOnce(new Response(null, { status: 409 }));
    vi.stubGlobal("fetch", fetch);
    await workspaceRequest("state");
    expect(fetch.mock.calls[0]![1].method).toBe("GET");
    expect(fetch.mock.calls[0]![1].cache).toBe("no-store");
    await expect(workspaceRequest("entries", {})).rejects.toThrow(
      "another tab",
    );
  });
  it.each([401, 403, 503])(
    "keeps the save unconfirmed on HTTP %s",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response(null, { status })),
      );
      await expect(workspaceRequest("state")).rejects.toBeInstanceOf(
        WorkspaceError,
      );
    },
  );
  it("converts transport failures and caller cancellation into recoverable messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("private upstream details")),
    );
    await expect(workspaceRequest("state")).rejects.toThrow(
      "local workspace is unavailable",
    );
    const controller = new AbortController();
    controller.abort();
    await expect(
      workspaceRequest("state", undefined, controller.signal),
    ).rejects.toThrow("Your text is still here");
    expect(errorMessage(new WorkspaceError(409, "changed"))).toBe("changed");
    expect(errorMessage("internal")).toContain("could not be completed");
  });
  it("bounds requests with a timer and follows later caller abort", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_path, init: RequestInit) =>
          new Promise((_resolve, reject) =>
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            ),
          ),
      ),
    );
    const request = workspaceRequest("state");
    const result = expect(request).rejects.toThrow("unavailable");
    await vi.advanceTimersByTimeAsync(15000);
    await result;
    const controller = new AbortController();
    const other = workspaceRequest("refresh", {}, controller.signal);
    const stopped = expect(other).rejects.toThrow("unavailable");
    controller.abort();
    await stopped;
  });
  it("retains encoded identity/version/anchor and honest unknown dates", () => {
    expect(
      readerHref({ work_id: "arxiv:abc/def" }, "v:1", "abstract:2:5"),
    ).toBe("/workspace/items/arxiv%3Aabc%2Fdef?version=v%3A1#abstract%3A2%3A5");
    expect(readerHref({ work_id: "x" })).toBe("/workspace/items/x");
    expect(displayDate(null)).toBe("Date unknown");
    expect(displayDate("not-a-date")).toBe("Date unknown");
    expect(displayDate("2026-11-02T12:00:00Z")).toContain("2026");
  });
});

const draft: ReaderDraft = {
  id: "new",
  revision: 0,
  body: "A private question",
  kind: "question",
  anchor: "abstract:4:20",
};
describe("unsaved draft recovery", () => {
  it("scopes recovery to account, work and exact version and deletes only on request", () => {
    expect(loadDraft("a", "w", "v1")).toBeNull();
    storeDraft("a", "w", "v1", draft);
    expect(loadDraft("a", "w", "v1")).toEqual(draft);
    expect(loadDraft("b", "w", "v1")).toBeNull();
    expect(loadDraft("a", "w", "v2")).toBeNull();
    storeDraft("a", "w", "v1", null);
    expect(loadDraft("a", "w", "v1")).toBeNull();
  });
  it("refuses malformed and oversized storage without erasing it", () => {
    sessionStorage.setItem(DRAFT_KEY, '{"version":2,"entries":{}}');
    expect(() => loadDraft("a", "w", "v")).toThrow("format");
    expect(() => storeDraft("a", "w", "v", draft)).toThrow();
    expect(sessionStorage.getItem(DRAFT_KEY)).toContain('"version":2');
    sessionStorage.setItem(DRAFT_KEY, "x".repeat(250001));
    expect(() => loadDraft("a", "w", "v")).toThrow("full");
  });
  it("validates recovered data and bounds aggregate drafts", () => {
    storeDraft("a", "w", "v", { ...draft, body: "x".repeat(10001) });
    expect(() => loadDraft("a", "w", "v")).toThrow("Malformed");
    sessionStorage.clear();
    for (let index = 0; index < 40; index++)
      storeDraft("a", `w${index}`, "v", draft);
    expect(() => storeDraft("a", "overflow", "v", draft)).toThrow("full");
  });
});
