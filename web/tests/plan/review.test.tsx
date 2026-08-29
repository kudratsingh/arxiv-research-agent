/**
 * WO-17 criteria 3, 4, 5 and 6, against the real request layer.
 *
 * `PlanEditor.test.tsx` proves the surface's behaviour with `onReview` as a
 * spy. This file closes the loop: WO-11's `useReviewPlan`, WO-04's client and
 * a real `POST /research/{job_id}/review` over MSW, with every request
 * counted. That is what turns "no request is made" from a claim about a
 * callback into a claim about the network, and what lets the two contract
 * facts be exercised as facts rather than as props:
 *
 *   - a 200 does NOT mean the run resumed (`schemas.py:141-160`), and
 *   - a 409 is not an error but an instruction to refetch
 *     (`routes.py:261-264`).
 *
 * `ReviewSurface` below is deliberately the smallest honest composition of
 * the machine's outputs onto this surface — the shape WO-20 will build for
 * real. It derives the stale cause from the REFETCHED run rather than from
 * the 409's own text, because `job_not_awaiting_review (status=failed)` says
 * the review is over but not why; only `error_type` says that.
 */

import { useRef, useState, type ReactElement, type ReactNode } from "react";

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { HttpResponse, http } from "msw";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  PlanEditor,
  type PlanEditorStatus,
  type PlanStaleCause,
} from "@/components/patterns/PlanEditor";
import {
  API_BASE,
  ApiError,
  type FieldIssue,
  type JobDetail,
  type Plan,
  type ReviewRequest,
} from "@/lib/api/index";
import { describeErrorType } from "@/lib/copy/errors";
import { PLAN } from "@/lib/copy/plan";
import { createQueryClient } from "@/lib/queries/client";
import { useJobDetail, useReviewPlan } from "@/lib/queries/job";
import { MAX_PLAN_ITEM_LEN } from "@/lib/plan/schema";

import { loadFixture, server, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor } from "../support/render";

const JOB_ID = "baseline-plan-review";
const REVIEW_PATH = `${API_BASE}/research/:jobId/review`;
const JOB_PATH = `${API_BASE}/research/:jobId`;

/** Every review body this file sent, in order. Length is the request count. */
const reviews: ReviewRequest[] = [];
/** How many `GET /research/{id}` reads happened. */
let jobReads = 0;
/** What the next read should answer with. Mutated by a test to move truth. */
let jobBody: JobDetail;

const PENDING_REVIEW = loadFixture("job.pending_review").body as JobDetail;

const countingJobRead = http.get(JOB_PATH, () => {
  jobReads += 1;
  return HttpResponse.json(jobBody);
});

setupMswServer(countingJobRead);

beforeEach(() => {
  reviews.length = 0;
  jobReads = 0;
  jobBody = PENDING_REVIEW;
});

// ---------------------------------------------------------------------------
// Handlers, each one a recorded or schema-derived shape.
// ---------------------------------------------------------------------------

/** 200. `status` is `pending_review` because the schema says it always is. */
const accepted = http.post(REVIEW_PATH, async ({ params, request }) => {
  const body = (await request.json()) as ReviewRequest;
  reviews.push(body);
  return HttpResponse.json({
    job_id: String(params.jobId),
    status: "pending_review",
    action: body.action,
  });
});

/** 409, with `routes.py:262-264`'s exact detail shape. */
function conflict(state: string) {
  return http.post(REVIEW_PATH, async ({ request }) => {
    reviews.push((await request.json()) as ReviewRequest);
    return HttpResponse.json(
      { detail: `job_not_awaiting_review (status=${state})` },
      { status: 409 },
    );
  });
}

/** 422, in FastAPI's default `{detail: [{loc, msg, type}]}` shape. */
const rejected = http.post(REVIEW_PATH, async ({ request }) => {
  reviews.push((await request.json()) as ReviewRequest);
  return HttpResponse.json(
    {
      detail: [
        {
          type: "string_too_long",
          loc: ["body", "plan", "search_queries", 1],
          msg: "String should have at most 500 characters",
          ctx: { max_length: MAX_PLAN_ITEM_LEN },
        },
      ],
    },
    { status: 422 },
  );
});

// ---------------------------------------------------------------------------
// The composition WO-20 will build.
// ---------------------------------------------------------------------------

function ReviewSurface(): ReactElement | null {
  const job = useJobDetail(JOB_ID);
  const review = useReviewPlan(JOB_ID);

  const [outcome, setOutcome] = useState<"open" | "accepted" | "stale">("open");
  const [issues, setIssues] = useState<readonly FieldIssue[]>([]);
  const [action, setAction] = useState<ReviewRequest["action"] | null>(null);
  // The last plan seen. `JobDetail.plan` is `None` once the run moves on
  // (`runner.py:454`), and the surface must not blank out mid-sentence.
  const lastPlan = useRef<Plan | null>(null);
  if (job.data?.plan != null) lastPlan.current = job.data.plan;

  const plan = lastPlan.current;
  if (plan === null) return null;

  const status: PlanEditorStatus =
    outcome === "stale"
      ? "stale"
      : outcome === "accepted"
        ? "resolving"
        : review.isPending
          ? action === "cancel"
            ? "cancelling"
            : "submitting"
          : "editing";

  // Derived from the run itself, never from the 409's text.
  const staleCause: PlanStaleCause =
    job.data?.error_type === "hitl_timeout" ? "hitl_timeout" : "resolved_elsewhere";

  return (
    <main>
      <p data-testid="run-status">{job.data?.status ?? ""}</p>
      <PlanEditor
        plan={plan}
        status={status}
        staleCause={staleCause}
        issues={issues}
        onReview={(request) => {
          setAction(request.action);
          setIssues([]);
          review.mutate(request, {
            onSuccess: (result) => {
              setOutcome(result.kind === "stale" ? "stale" : "accepted");
            },
            onError: (error) => {
              if (error instanceof ApiError && error.failure.kind === "validation") {
                setIssues(error.failure.fields);
              }
              setOutcome("open");
            },
          });
        }}
        onRefetch={() => {
          void job.refetch();
        }}
      />
    </main>
  );
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }): ReactElement {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

function mount(): QueryClient {
  const client = createQueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = wrapper(client);
  render(
    <Wrapper>
      <ReviewSurface />
    </Wrapper>,
  );
  return client;
}

/** See the note in `PlanEditor.test.tsx`: cross the lazy boundary once. */
beforeAll(async () => {
  await import("@/components/patterns/PlanEditorFields");
});

async function openEditor(): Promise<void> {
  await screen.findByLabelText("Sub-question 1", undefined, { timeout: 5000 });
}

// ---------------------------------------------------------------------------
// The plan comes from JobDetail, with no SSE frame (05 §2.1 step 3).
// ---------------------------------------------------------------------------

describe("a seeded pending_review run renders its plan from GET alone", () => {
  it("needs no frame and no stream", async () => {
    mount();
    await openEditor();
    expect(screen.getByLabelText("Sub-question 1")).toHaveValue(
      (PENDING_REVIEW.plan as Plan).sub_questions[0],
    );
    expect(jobReads).toBe(1);
    expect(reviews).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Criterion 3, at the network.
// ---------------------------------------------------------------------------

describe("criterion 3 — an over-length entry never reaches the wire", () => {
  it("sends zero requests for 501 characters", async () => {
    server.use(accepted);
    const typist = user();
    mount();
    await openEditor();

    const row = screen.getByLabelText("arXiv query 1");
    await typist.clear(row);
    await typist.click(row);
    await typist.paste("x".repeat(MAX_PLAN_ITEM_LEN + 1));

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    await screen.findByText(/1 character over the limit/);

    expect(reviews).toHaveLength(0);
  });

  it("sends exactly one request when the entry is inside the bound", async () => {
    server.use(accepted);
    const typist = user();
    mount();
    await openEditor();

    const row = screen.getByLabelText("arXiv query 1");
    await typist.clear(row);
    await typist.type(row, "faithfulness evaluation");

    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));
    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]?.action).toBe("revise");
    expect(reviews[0]?.plan?.search_queries[0]).toBe("faithfulness evaluation");
  });
});

// ---------------------------------------------------------------------------
// Criterion 6 — the 200.
// ---------------------------------------------------------------------------

describe("criterion 6 — a 200 does not claim resumption", () => {
  it("enters resolving and waits for a frame or a poll", async () => {
    server.use(accepted);
    const typist = user();
    mount();
    await openEditor();

    await typist.click(screen.getByRole("button", { name: PLAN.approve }));

    await waitFor(() =>
      expect(screen.getByTestId("plan-status-line")).toHaveTextContent(PLAN.resolving),
    );
    // The wire said `pending_review`, and the surface repeats nothing else.
    expect(document.body.textContent).not.toMatch(/\bresumed\b/i);
    expect(screen.getByTestId("run-status")).toHaveTextContent("pending_review");
  });

  it("re-reads the run rather than assuming what the review did", async () => {
    server.use(accepted);
    const typist = user();
    mount();
    await openEditor();
    const before = jobReads;

    await typist.click(screen.getByRole("button", { name: PLAN.approve }));

    // WO-11's mutation invalidates the job on settle; the next truth about
    // this run comes from `GET /research/{id}` and from nowhere else.
    await waitFor(() => expect(jobReads).toBeGreaterThan(before));
  });

  it("shows the run moving only once the server says it moved", async () => {
    server.use(accepted);
    const typist = user();
    const client = mount();
    await openEditor();

    await typist.click(screen.getByRole("button", { name: PLAN.approve }));
    await waitFor(() =>
      expect(screen.getByTestId("plan-status-line")).toHaveTextContent(PLAN.resolving),
    );

    jobBody = { ...PENDING_REVIEW, status: "running", plan: null };
    await client.invalidateQueries();
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("running"),
    );
  });
});

// ---------------------------------------------------------------------------
// Criterion 5 — the 409.
// ---------------------------------------------------------------------------

describe("criterion 5 — a 409 refetches and re-renders", () => {
  it("resolves the conflict rather than throwing, and reads the run again", async () => {
    server.use(conflict("running"));
    const typist = user();
    mount();
    await openEditor();
    const before = jobReads;

    jobBody = { ...PENDING_REVIEW, status: "running", plan: null };
    await typist.click(screen.getByRole("button", { name: PLAN.approve }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(PLAN.conflict);
    await waitFor(() => expect(jobReads).toBeGreaterThan(before));
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("running"),
    );
    // One attempt, and no retry: `approve` resumes billable work.
    expect(reviews).toHaveLength(1);
  });

  it("drives the hitl_timeout cause and names it from the refetched run", async () => {
    server.use(conflict("failed"));
    const typist = user();
    mount();
    await openEditor();

    // What `api_hitl_timeout_sec` firing leaves behind
    // (`runner.py:1053-1057`): a failed run carrying `hitl_timeout`.
    jobBody = {
      ...PENDING_REVIEW,
      status: "failed",
      plan: null,
      error: "plan review timed out",
      error_type: "hitl_timeout",
    };

    await typist.click(screen.getByRole("button", { name: PLAN.approve }));

    const alert = await screen.findByRole("alert");
    await waitFor(() =>
      expect(alert).toHaveTextContent(describeErrorType("hitl_timeout").sentence),
    );
    await waitFor(() =>
      expect(screen.getByTestId("run-status")).toHaveTextContent("failed"),
    );
    // Still no countdown, in the one state a countdown would have described.
    expect(alert.textContent ?? "").not.toMatch(/\b\d+\s*(?:minutes?|seconds?)\b/i);
  });

  it("does not dead-end: the recovery control reads the run again", async () => {
    server.use(conflict("cancelled"));
    const typist = user();
    mount();
    await openEditor();

    jobBody = { ...PENDING_REVIEW, status: "cancelled", plan: null };
    await typist.click(screen.getByRole("button", { name: PLAN.approve }));
    await screen.findByRole("alert");

    const after = jobReads;
    await typist.click(screen.getByRole("button", { name: PLAN.refresh }));
    await waitFor(() => expect(jobReads).toBeGreaterThan(after));
    // And no second review was attempted by the recovery.
    expect(reviews).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — the 422.
// ---------------------------------------------------------------------------

describe("criterion 4 — a 422 that still arrives lands on the row", () => {
  it("marks the field FastAPI named, and nothing else", async () => {
    server.use(rejected);
    const typist = user();
    mount();
    await openEditor();

    const row = screen.getByLabelText("arXiv query 2");
    await typist.clear(row);
    await typist.type(row, "another query");
    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));

    await waitFor(() =>
      expect(screen.getByLabelText("arXiv query 2")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(screen.getByLabelText("arXiv query 2")).toHaveAccessibleDescription(
      expect.stringContaining("String should have at most 500 characters"),
    );
    // No page-level banner: the baseline mapped nothing and shouted instead.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByLabelText("arXiv query 1")).not.toHaveAttribute("aria-invalid");
  });

  it("leaves the surface usable — one attempt, still editable", async () => {
    server.use(rejected);
    const typist = user();
    mount();
    await openEditor();

    const row = screen.getByLabelText("arXiv query 2");
    await typist.clear(row);
    await typist.type(row, "another query");
    await typist.click(await screen.findByRole("button", { name: PLAN.revise }));

    await waitFor(() => expect(reviews).toHaveLength(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: PLAN.revise })).toBeEnabled(),
    );
    expect(screen.getByLabelText("arXiv query 2")).not.toHaveAttribute("readonly");
  });
});

// ---------------------------------------------------------------------------
// Cancel.
// ---------------------------------------------------------------------------

describe("cancel is the one stop, and it goes to the wire as itself", () => {
  it("sends action: cancel with no plan", async () => {
    server.use(accepted);
    const typist = user();
    mount();
    await openEditor();

    await typist.type(screen.getByLabelText("Sub-question 1"), " edited");
    await typist.click(screen.getByRole("button", { name: PLAN.cancel }));

    await waitFor(() => expect(reviews).toHaveLength(1));
    expect(reviews[0]).toEqual({ action: "cancel" });
  });
});
