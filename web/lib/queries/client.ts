// The QueryClient and its defaults (04-ARCHITECTURE.md §4.1).
//
// Two rules govern everything here, and both come from the cost
// boundary rather than from taste:
//
//   Reads are idempotent, so they may be retried — but only for the
//   failures a retry can actually fix. A 404, a 422 or a 409 is a fact
//   about the request; retrying it three times is three requests and the
//   same answer.
//
//   Writes are never replayed. TanStack's default `networkMode: "online"`
//   PAUSES a mutation while the browser is offline and RESUMES it when
//   connectivity returns. For `POST /research` that would be an automatic
//   replay of a paid run, which is why §4.1 keeps submission out of this
//   library entirely (H6). The same reasoning applies to the writes that
//   ARE here: `reviewPlan({action: "approve"})` resumes billable work, so
//   `networkMode: "always"` makes an offline write fail immediately and
//   visibly instead of being queued behind the user's back.
//
// `createQueryClient` forces `mutations.retry: false` after any override,
// so "all mutations use retry: false" is a property of the factory rather
// than a convention every call site has to remember.

import { QueryClient, type DefaultOptions, type QueryClientConfig } from "@tanstack/react-query";

import { ApiError, type ApiFailureKind } from "@/lib/api/index";

/**
 * The failure kinds a second attempt can plausibly resolve.
 *
 * `rate_limited` is excluded on purpose: retrying spends more of the
 * hour's budget (`auth.py:176-184`) and the honest response is to show
 * the `Retry-After` the server sent. `cancelled` is excluded because the
 * caller asked for the abort.
 */
export const RETRYABLE_READ_FAILURES: readonly ApiFailureKind[] = [
  "offline",
  "timeout",
  "upstream_unavailable",
  "server_error",
];

/** Attempts after the first. Three requests total, worst case. */
export const MAX_READ_RETRIES = 2;

/** Ceiling on the exponential backoff between read attempts. */
export const MAX_RETRY_DELAY_MS = 8_000;

/** How long a read stays fresh before a remount refetches it. */
export const DEFAULT_STALE_TIME_MS = 30_000;

/** How long an unobserved read is kept before it is collected. */
export const DEFAULT_GC_TIME_MS = 5 * 60_000;

/**
 * Retry policy for reads. Exported so it is testable as a pure function
 * rather than only through a client's behaviour.
 */
export function shouldRetryRead(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_READ_RETRIES) return false;
  if (!(error instanceof ApiError)) return false;
  return RETRYABLE_READ_FAILURES.includes(error.failure.kind);
}

/** Exponential backoff, capped. */
export function readRetryDelayMs(attemptIndex: number): number {
  return Math.min(1_000 * 2 ** attemptIndex, MAX_RETRY_DELAY_MS);
}

export const QUERY_CLIENT_DEFAULTS: DefaultOptions = {
  queries: {
    staleTime: DEFAULT_STALE_TIME_MS,
    gcTime: DEFAULT_GC_TIME_MS,
    retry: shouldRetryRead,
    retryDelay: readRetryDelayMs,
    // A refetch on every window focus is a request per tab switch for a
    // surface that already polls while a job is live (§4.4). Reconnect
    // is different: coming back online is real news about staleness.
    refetchOnWindowFocus: false,
    refetchOnReconnect: true,
    // The default, stated rather than inherited: pausing a *read* while
    // offline is harmless, which is exactly why the mutation default
    // below has to differ.
    networkMode: "online",
  },
  mutations: {
    // Criterion 4. Also forced by `createQueryClient` below.
    retry: false,
    // Never queue-and-replay a write. See the header.
    networkMode: "always",
  },
};

/**
 * The app's QueryClient.
 *
 * `overrides` exists for tests and for a future server-side prefetch
 * client; it cannot weaken the two safety properties. `retry: false` and
 * `networkMode: "always"` are re-applied to mutations after the merge, so
 * no caller — including a future one — can turn a write into something
 * a library will repeat on its own.
 */
export function createQueryClient(overrides: QueryClientConfig = {}): QueryClient {
  const { defaultOptions, ...rest } = overrides;
  return new QueryClient({
    ...rest,
    defaultOptions: {
      ...QUERY_CLIENT_DEFAULTS,
      ...defaultOptions,
      queries: { ...QUERY_CLIENT_DEFAULTS.queries, ...defaultOptions?.queries },
      mutations: {
        ...QUERY_CLIENT_DEFAULTS.mutations,
        ...defaultOptions?.mutations,
        retry: false,
        networkMode: "always",
      },
    },
  });
}
