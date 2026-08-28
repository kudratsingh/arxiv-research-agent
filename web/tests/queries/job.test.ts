// WO-11 criterion 6 — the review mutation's two honest outcomes, plus
// the job query and its liveness poll.
//
// A 200 from `POST /research/{id}/review` is NOT "resumed"
// (`schemas.py:141-160`), and a 409 is NOT an error
// (`routes.py:261-264`). Both are asserted here against the recorded 409
// envelope and against a 200 body shaped exactly as `ReviewResponse`
// declares it — three fields, `status` always `pending_review`.

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { beforeEach, describe, expect, it } from "vitest";

import { API_BASE, type JobDetail, type ReviewRequest } from "@/lib/api/index";
import { createQueryClient } from "@/lib/queries/client";
import {
  JOB_POLL_BACKOFF_AFTER,
  JOB_POLL_INTERVAL_MS,
  JOB_POLL_SLOW_INTERVAL_MS,
  TERMINAL_JOB_STATUSES,
  isStaleReview,
  isTerminalJobStatus,
  jobPollIntervalMs,
  jobRefetchInterval,
  useJobDetail,
  useReviewPlan,
  type JobPollTracker,
} from "@/lib/queries/job";
import { queryKeys } from "@/lib/queries/keys";

import {
  JOB_FIXTURES_BY_ID,
  errorFixture,
  fixtureResponse,
  handlers,
  loadFixture,
  server,
  setupMswServer,
} from "../support/msw";
import { act, renderHook, waitFor } from "../support/render";

const JOB_ID = "baseline-plan-review";
const REVIEW_PATH = `${API_BASE}/research/:jobId/review`;

/** Every `GET /research/{id}` this file saw. */
const jobReads: string[] = [];

const countingJobRead = http.get(`${API_BASE}/research/:jobId`, ({ params }) => {
  const jobId = String(params.jobId);
  jobReads.push(jobId);
  const fixture = JOB_FIXTURES_BY_ID[jobId];
  return fixtureResponse(fixture ?? loadFixture("error.404"));
});

setupMswServer(countingJobRead, ...handlers);

beforeEach(() => {
  jobReads.length = 0;
});

/**
 * A 200 review response.
 *
 * No fixture records this call, so the body is written from
 * `src/api/schemas.py:141-160` — and `status` is hard-coded to
 * `pending_review` because that is what the schema says the server
 * always sends, which is the whole point of the criterion.
 */
const acceptedReview = http.post(REVIEW_PATH, async ({ params, request }) => {
  const body = (await request.json()) as ReviewRequest;
  return HttpResponse.json({
    job_id: String(params.jobId),
    status: "pending_review",
    action: body.action,
  });
});

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }): ReactElement {
    return createElement(QueryClientProvider, { client }, children);
  };
}

function testClient(): QueryClient {
  return createQueryClient({ defaultOptions: { queries: { retry: false } } });
}

function renderReviewSurface(client: QueryClient) {
  return renderHook(
    () => ({
      job: useJobDetail(JOB_ID),
      review: useReviewPlan(JOB_ID),
    }),
    { wrapper: wrapper(client) }
  );
}

const APPROVE: ReviewRequest = { action: "approve" };

// ---------------------------------------------------------------------------
// Criterion 6.
// ---------------------------------------------------------------------------

describe("a 200 review does not mean the run resumed (criterion 6)", () => {
  it("reports resumed: false and the server's pending_review snapshot", async () => {
    server.use(acceptedReview);
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));

    let outcome;
    await act(async () => {
      outcome = await result.current.review.mutateAsync(APPROVE);
    });

    expect(outcome).toMatchObject({ kind: "accepted", resumed: false });
    expect(outcome).toHaveProperty("response.status", "pending_review");
    expect(isStaleReview(outcome!)).toBe(false);
  });

  it("refetches the job instead of assuming what the review did", async () => {
    server.use(acceptedReview);
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));
    const before = jobReads.length;

    await act(async () => {
      await result.current.review.mutateAsync(APPROVE);
    });

    // The settled state comes from `GET /research/{id}`, never from the
    // review response.
    await waitFor(() => expect(jobReads.length).toBeGreaterThan(before));
  });
});

describe("a 409 means the truth moved, not that something broke", () => {
  it("resolves to a stale outcome and never enters an error state", async () => {
    server.use(errorFixture("error.409", "post", REVIEW_PATH));
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));

    let outcome;
    await act(async () => {
      outcome = await result.current.review.mutateAsync(APPROVE);
    });

    expect(outcome).toMatchObject({ kind: "stale", resumed: false });
    expect(isStaleReview(outcome!)).toBe(true);
    await waitFor(() => expect(result.current.review.isSuccess).toBe(true));
    expect(result.current.review.isError).toBe(false);

    // And it carries the conflict's own state, so the surface can say
    // which one it was. The recorded envelope is
    // `job_not_awaiting_review (status=running)`.
    expect(outcome).toHaveProperty("failure.kind", "conflict");
    expect(outcome).toHaveProperty("failure.state", "running");
  });

  it("refetches and re-renders from the server's truth", async () => {
    server.use(errorFixture("error.409", "post", REVIEW_PATH));
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));
    const before = jobReads.length;

    await act(async () => {
      await result.current.review.mutateAsync(APPROVE);
    });

    await waitFor(() => expect(jobReads.length).toBeGreaterThan(before));
    expect(client.getQueryState(queryKeys.jobs.detail(JOB_ID))?.data).toBeDefined();
  });
});

describe("a real failure is still a failure", () => {
  it("throws a 502 rather than swallowing it as 'stale'", async () => {
    server.use(errorFixture("error.502", "post", REVIEW_PATH));
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));

    await act(async () => {
      await result.current.review.mutateAsync(APPROVE).catch(() => undefined);
    });

    await waitFor(() => expect(result.current.review.isError).toBe(true));
  });

  it("does not retry the review — approve is billable", async () => {
    let attempts = 0;
    server.use(
      http.post(REVIEW_PATH, () => {
        attempts += 1;
        return fixtureResponse(loadFixture("error.502"));
      })
    );
    const client = testClient();
    const { result } = renderReviewSurface(client);
    await waitFor(() => expect(result.current.job.isSuccess).toBe(true));

    await act(async () => {
      await result.current.review.mutateAsync(APPROVE).catch(() => undefined);
    });

    expect(attempts).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// The job query and the liveness poll (§4.4).
// ---------------------------------------------------------------------------

describe("useJobDetail", () => {
  it("reads the recorded job detail", async () => {
    const client = testClient();
    const { result } = renderHook(() => useJobDetail("baseline-succeeded"), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(loadFixture("job.succeeded").body);
  });

  it("does not fetch without a job id", () => {
    const client = testClient();
    const { result } = renderHook(() => useJobDetail(null), {
      wrapper: wrapper(client),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(jobReads).toEqual([]);
  });

  it("polls a live job and settles without one", async () => {
    const client = testClient();
    const { result } = renderHook(
      () => useJobDetail("baseline-running", { poll: true }),
      { wrapper: wrapper(client) }
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("running");
  });
});

describe("the poll interval", () => {
  const running = loadFixture("job.running").body as JobDetail;
  const succeeded = loadFixture("job.succeeded").body as JobDetail;

  function tracker(): JobPollTracker {
    return { seen: undefined, polls: 0 };
  }

  it("polls a live job at the fast interval", () => {
    expect(jobRefetchInterval(running, tracker())).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("polls at the fast interval before the first response arrives", () => {
    expect(jobRefetchInterval(undefined, tracker())).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("stops entirely once the job is terminal", () => {
    expect(jobRefetchInterval(succeeded, tracker())).toBe(false);
  });

  it("backs off after five polls that learned nothing, and resets on news", () => {
    const state = tracker();
    const intervals = Array.from({ length: 7 }, () =>
      jobRefetchInterval(running, state)
    );
    expect(intervals).toEqual([
      JOB_POLL_INTERVAL_MS,
      JOB_POLL_INTERVAL_MS,
      JOB_POLL_INTERVAL_MS,
      JOB_POLL_INTERVAL_MS,
      JOB_POLL_INTERVAL_MS,
      JOB_POLL_SLOW_INTERVAL_MS,
      JOB_POLL_SLOW_INTERVAL_MS,
    ]);

    // A different payload object is news; the backoff starts over.
    expect(jobRefetchInterval({ ...running }, state)).toBe(JOB_POLL_INTERVAL_MS);
  });

  it("names every terminal status and nothing else", () => {
    expect([...TERMINAL_JOB_STATUSES].sort()).toEqual([
      "cancelled",
      "failed",
      "succeeded",
    ]);
    expect(isTerminalJobStatus("running")).toBe(false);
    expect(isTerminalJobStatus("pending")).toBe(false);
    expect(isTerminalJobStatus("pending_review")).toBe(false);
    expect(isTerminalJobStatus("failed")).toBe(true);
  });

  it("backs off after five polls that changed nothing", () => {
    expect(jobPollIntervalMs(0)).toBe(JOB_POLL_INTERVAL_MS);
    expect(jobPollIntervalMs(JOB_POLL_BACKOFF_AFTER - 1)).toBe(
      JOB_POLL_INTERVAL_MS
    );
    expect(jobPollIntervalMs(JOB_POLL_BACKOFF_AFTER)).toBe(
      JOB_POLL_SLOW_INTERVAL_MS
    );
  });
});
