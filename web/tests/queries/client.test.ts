// The QueryClient defaults (04-ARCHITECTURE.md §4.1) and the half of
// WO-11 criterion 4 that is about configuration: every mutation is
// `retry: false`, and nothing can override it back.
//
// The `networkMode` assertions matter as much as the retry ones. With
// TanStack's default (`"online"`) a mutation fired while offline is
// PAUSED and REPLAYED when connectivity returns — for `reviewPlan`
// (`action: "approve"`) that is a delayed resume of billable work that
// the user has stopped watching. `"always"` makes it fail where it
// happened.

import { describe, expect, it } from "vitest";

import { ApiError, type ApiFailure, type ApiFailureKind } from "@/lib/api/index";
import {
  MAX_READ_RETRIES,
  MAX_RETRY_DELAY_MS,
  QUERY_CLIENT_DEFAULTS,
  RETRYABLE_READ_FAILURES,
  createQueryClient,
  readRetryDelayMs,
  shouldRetryRead,
} from "@/lib/queries/client";

function failure(kind: ApiFailureKind): ApiError {
  return new ApiError(0, "boom", {
    kind,
    message: "boom",
    raw: null,
  } as unknown as ApiFailure);
}

describe("mutation defaults (criterion 4)", () => {
  it("declares retry: false", () => {
    expect(QUERY_CLIENT_DEFAULTS.mutations?.retry).toBe(false);
  });

  it("never queues a write for replay after reconnecting", () => {
    expect(QUERY_CLIENT_DEFAULTS.mutations?.networkMode).toBe("always");
  });

  it("carries both onto a real client", () => {
    const defaults = createQueryClient().getDefaultOptions();
    expect(defaults.mutations?.retry).toBe(false);
    expect(defaults.mutations?.networkMode).toBe("always");
  });

  it("cannot be overridden back into retrying or queueing", () => {
    // The factory re-applies both after the merge, so a future caller
    // cannot reintroduce automatic replay by passing a config.
    const defaults = createQueryClient({
      defaultOptions: { mutations: { retry: 5, networkMode: "online" } },
    }).getDefaultOptions();
    expect(defaults.mutations?.retry).toBe(false);
    expect(defaults.mutations?.networkMode).toBe("always");
  });

  it("still lets an unrelated mutation default through", () => {
    const defaults = createQueryClient({
      defaultOptions: { mutations: { gcTime: 1_234 } },
    }).getDefaultOptions();
    expect(defaults.mutations?.gcTime).toBe(1_234);
    expect(defaults.mutations?.retry).toBe(false);
  });
});

describe("read defaults", () => {
  it("does not refetch on every window focus, but does on reconnect", () => {
    const queries = createQueryClient().getDefaultOptions().queries;
    expect(queries?.refetchOnWindowFocus).toBe(false);
    expect(queries?.refetchOnReconnect).toBe(true);
  });

  it("accepts a query override", () => {
    const queries = createQueryClient({
      defaultOptions: { queries: { retry: false } },
    }).getDefaultOptions().queries;
    expect(queries?.retry).toBe(false);
    // Untouched defaults survive the merge.
    expect(queries?.refetchOnWindowFocus).toBe(false);
  });

  it("passes non-defaultOptions config straight through", () => {
    const client = createQueryClient({
      defaultOptions: undefined,
    });
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });
});

describe("shouldRetryRead", () => {
  it("retries only the failures a second attempt could fix", () => {
    for (const kind of RETRYABLE_READ_FAILURES) {
      expect(shouldRetryRead(0, failure(kind)), kind).toBe(true);
    }
  });

  it("never retries a fact about the request", () => {
    const facts: ApiFailureKind[] = [
      "unauthorized",
      "not_found",
      "conflict",
      "validation",
      "proxy_misconfigured",
      "unknown",
    ];
    for (const kind of facts) {
      expect(shouldRetryRead(0, failure(kind)), kind).toBe(false);
    }
  });

  it("never retries a rate limit — that would spend more of the budget", () => {
    expect(shouldRetryRead(0, failure("rate_limited"))).toBe(false);
  });

  it("never retries a cancellation — the caller asked for it", () => {
    expect(shouldRetryRead(0, failure("cancelled"))).toBe(false);
  });

  it("stops at the ceiling", () => {
    expect(shouldRetryRead(MAX_READ_RETRIES - 1, failure("timeout"))).toBe(true);
    expect(shouldRetryRead(MAX_READ_RETRIES, failure("timeout"))).toBe(false);
  });

  it("does not retry something that is not an ApiError at all", () => {
    expect(shouldRetryRead(0, new Error("who knows"))).toBe(false);
    expect(shouldRetryRead(0, undefined)).toBe(false);
  });
});

describe("readRetryDelayMs", () => {
  it("backs off exponentially and then stops growing", () => {
    expect(readRetryDelayMs(0)).toBe(1_000);
    expect(readRetryDelayMs(1)).toBe(2_000);
    expect(readRetryDelayMs(9)).toBe(MAX_RETRY_DELAY_MS);
  });
});
