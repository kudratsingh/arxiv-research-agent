/**
 * WO-S3 — a failed plan approval must say what failed and what to do.
 *
 * THE DEFECT THIS FILE EXISTS TO KEEP FIXED. `POST /research/{job_id}/review`
 * is the request that commits money, and every way it can fail rendered
 * NOTHING. The machine records the failure without moving its phase — which
 * is correct, the server never heard the decision, so the run really is still
 * `pending_review` and the user's edits are still on screen — and the only
 * banner in the composition was gated on `phase === "submit_failed"`, a phase
 * a review failure never produces. So a rate limit, a 500 and a stale plan
 * were all indistinguishable from a click that missed the button.
 *
 * EVERY TEST BELOW FAILS ON `main`, on the assertion that the banner exists.
 *
 * THE TIER IS THE WHOLE POINT. This is the real `ActiveRunPanel`, the real
 * `JobRunProvider`, the real machine and the real request layer over MSW —
 * because the defect was not in any one of them. Each piece behaved as
 * documented; what was missing was the surface that reads `failureSource`.
 * Driving it by props alone would have proved nothing about that.
 *
 * NOTHING HERE CAN REACH `POST /research`. `setupMswServer` runs with
 * `onUnhandledRequest: "error"` and no handler for it exists by design
 * (`tests/support/handlers.ts`), so an accidental submission fails loudly
 * (R-01). The review handlers below are per-test overrides, and every one of
 * them is an error response.
 *
 * THE ENVELOPES ARE RECORDINGS, NOT INVENTIONS. `error.429` carries its own
 * `Retry-After: 3600` and `{"detail": {"limit_per_hour": 1}}`, and `error.409`
 * carries `job_not_awaiting_review (status=running)` — the two shapes
 * `lib/api/errors.ts` parses for structure. Asserting on copy derived from
 * those numbers is what proves the envelope survived the trip.
 */

import type { ReactElement } from "react";

import { HttpResponse, delay, http } from "msw";
import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import { ActiveRunPanel } from "@/components/features/ActiveRunPanel";
import { API_BASE } from "@/lib/api/index";
import { FAILURE_COPY, rateLimitRecovery } from "@/lib/copy/errors";
import { PLAN } from "@/lib/copy/plan";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { fixtureResponse, loadFixture, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor } from "../support/render";

/** The seeded run parked at the review pause (`job.pending_review.json`). */
const JOB_ID = "baseline-plan-review";
const CONVERSATION_ID = "baseline-populated";
const REVIEW_PATH = `${API_BASE}/research/:jobId/review`;

/** Every review body that reached the wire. Length is the request count. */
const reviews: unknown[] = [];

const server = setupMswServer();

beforeEach(() => {
  reviews.length = 0;
  // Manual mode: the stub owns `EventSource` and delivers no frames. The plan
  // reaches the surface from `GET /research/{id}` alone, which is 05 §2.1's
  // step 3 and the only path a story cannot take.
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
});

/** Cross the `React.lazy` boundary once; see `PlanEditor.test.tsx`. */
beforeAll(async () => {
  await import("@/components/patterns/PlanEditorFields");
});

/**
 * A review that answers with one recorded error envelope.
 *
 * The body is counted before the failure is returned, so "one attempt, and
 * no retry" stays assertable — `approve` resumes billable work and must never
 * be replayed for the user (H6, R-01).
 */
function reviewFails(status: number, body: Record<string, unknown>) {
  return http.post(REVIEW_PATH, async ({ request }) => {
    reviews.push(await request.json());
    return HttpResponse.json(body, { status });
  });
}

/**
 * The recorded envelope for a code, replayed byte for byte and counted.
 *
 * `errorFixture` would replay it too, but it cannot count the request, and
 * "one attempt, and no retry" is the half of each claim that matters most on
 * the call that spends money. So the recording is loaded and re-served here
 * with the same `fixtureResponse` the shared handlers use — status,
 * statusText, headers and body, unedited.
 */
function recordedFailure(
  name: "error.401" | "error.409" | "error.422" | "error.429",
) {
  const fixture = loadFixture(name);
  return http.post(REVIEW_PATH, async ({ request }) => {
    reviews.push(await request.json());
    return fixtureResponse(fixture);
  });
}

/**
 * The panel, its provider, and nothing else.
 *
 * `poll` is left at its default in most tests — they finish in milliseconds,
 * long before 20 s — and shortened deliberately in the one test that is about
 * what a poll does to the banner.
 */
function Panel({ pollMs }: { pollMs?: number } = {}): ReactElement {
  return (
    <JobRunProvider
      jobId={JOB_ID}
      conversationId={CONVERSATION_ID}
      poll={
        pollMs === undefined
          ? { enabled: false }
          : { enabled: true, intervalMs: pollMs, backoffIntervalMs: pollMs }
      }
    >
      <ActiveRunPanel conversationId={CONVERSATION_ID} adoptJobId={JOB_ID} />
    </JobRunProvider>
  );
}

/** Mount, and wait for the plan the seeded run is parked on. */
async function openEditor(props: { pollMs?: number } = {}): Promise<void> {
  render(<Panel {...props} />);
  await screen.findByLabelText("Sub-question 1", undefined, { timeout: 5000 });
}

/** Press the one primary control. */
async function approve(): Promise<void> {
  const typist = user();
  await typist.click(await screen.findByRole("button", { name: PLAN.approve }));
}

// ---------------------------------------------------------------------------
// The defect, one failure code at a time.
//
// Each case asserts the SENTENCE and the RECOVERY, because "what failed" and
// "what to do" are two different promises and a banner that keeps only the
// first is still a dead end.
// ---------------------------------------------------------------------------

describe("a rate-limited approval says so, and says how long", () => {
  it("renders the 429's sentence, its wait and its ceiling", async () => {
    server.use(recordedFailure("error.429"));
    await openEditor();
    await approve();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.word);
    expect(alert).toHaveTextContent(FAILURE_COPY.rate_limited.sentence);
    // `Retry-After: 3600` and `limit_per_hour: 1`, straight off the
    // recording — neither number is invented when the header is absent.
    expect(alert).toHaveTextContent(rateLimitRecovery(3600, 1));
    // One attempt. A rate limit must not be retried for the user.
    expect(reviews).toHaveLength(1);
  });

  it("leaves the plan editable, so the decision is not lost", async () => {
    server.use(recordedFailure("error.429"));
    await openEditor();
    await approve();
    await screen.findByRole("alert");

    // The machine never left `awaiting_review`: the server did not hear the
    // decision, so the run is still parked and the working copy is still the
    // thing on screen.
    expect(screen.getByLabelText("Sub-question 1")).not.toHaveAttribute("readonly");
    expect(screen.getByRole("button", { name: PLAN.approve })).toBeEnabled();
  });
});

describe("a server error on the approval says so", () => {
  it("renders the 500's sentence and its recovery", async () => {
    server.use(reviewFails(500, { detail: "internal_error" }));
    await openEditor();
    await approve();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.server_error.word);
    expect(alert).toHaveTextContent(FAILURE_COPY.server_error.sentence);
    expect(alert).toHaveTextContent(FAILURE_COPY.server_error.recovery);
    expect(reviews).toHaveLength(1);
  });

  it("never puts the backend's own string in the sentence (RC-16)", async () => {
    server.use(reviewFails(500, { detail: "internal_error" }));
    await openEditor();
    await approve();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").not.toContain("internal_error");
  });
});

describe("a 502 and a 503 are told apart, because the remedies differ", () => {
  it("says the research service is unreachable on a 502", async () => {
    server.use(reviewFails(502, { detail: "api_upstream_unavailable" }));
    await openEditor();
    await approve();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.upstream_unavailable.sentence);
  });

  it("says an operator has to act on a 503", async () => {
    server.use(reviewFails(503, { detail: "api_proxy_misconfigured" }));
    await openEditor();
    await approve();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.proxy_misconfigured.sentence);
    expect(alert).toHaveTextContent(FAILURE_COPY.proxy_misconfigured.recovery);
  });
});

describe("a stale plan keeps the editor on screen and offers the re-read", () => {
  it("states the conflict while it lasts, then re-renders rather than stranding", async () => {
    server.use(recordedFailure("error.409"));
    await openEditor();

    // Widen the conflict window deliberately. It is bounded by the re-read
    // the 409 itself triggers (`useJobStream`'s `review`), which over a local
    // MSW lands in well under a millisecond — so without the delay this
    // asserts a race rather than a state.
    server.use(
      http.get(`${API_BASE}/research/:jobId`, async () => {
        await delay(80);
        return fixtureResponse(loadFixture("job.pending_review"));
      }),
    );
    await approve();

    // `machine.ts` sends a 409 back through `attaching` to re-read the run.
    // On `main` that took the editor off screen and put nothing in its place.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(PLAN.conflict);
    expect(alert).toHaveTextContent(PLAN.conflictRecovery);
    expect(screen.getByRole("button", { name: PLAN.refresh })).toBeEnabled();

    // And then the read's own answer takes over. It says the run IS still
    // awaiting review, which contradicts the 409 outright — the read is
    // newer and is the authority on that question — so the surface comes
    // back ACTIONABLE rather than stranded behind a banner. `routes.py:
    // 261-264`'s answer to a conflict is to refetch and re-render, and
    // `e2e/slice.spec.ts` step 3 asserts the same end state in a browser.
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull(), {
      timeout: 3000,
    });
    expect(screen.getByRole("button", { name: PLAN.approve })).toBeEnabled();
    // One attempt. The recovery re-reads; it never re-decides.
    expect(reviews).toHaveLength(1);
  });
});

describe("a 422 lands on the rows, and not in a banner", () => {
  it("marks the field the server named", async () => {
    server.use(
      reviewFails(422, {
        detail: [
          {
            type: "string_too_long",
            loc: ["body", "plan", "search_queries", 1],
            msg: "String should have at most 500 characters",
          },
        ],
      }),
    );
    await openEditor();
    await approve();

    // WO-17 criterion 4, reached at last: on `main` the panel passed no
    // `issues` at all, so a 422 on the review marked nothing anywhere.
    await waitFor(() =>
      expect(screen.getByLabelText("arXiv query 2")).toHaveAttribute(
        "aria-invalid",
        "true",
      ),
    );
    expect(screen.getByLabelText("arXiv query 1")).not.toHaveAttribute(
      "aria-invalid",
    );
    // And no page-level shouting: the baseline mapped nothing and shouted.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("still speaks when the 422 names no field at all", async () => {
    // `revise_requires_plan` shape with nothing this editor has a row for.
    server.use(reviewFails(422, { detail: "revise_requires_plan" }));
    await openEditor();
    await approve();

    // No row to land on is exactly where the silence used to be.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(FAILURE_COPY.validation.sentence);
  });
});

// ---------------------------------------------------------------------------
// The banner has to outlive the reads that follow it.
// ---------------------------------------------------------------------------

describe("the explanation survives the liveness poll", () => {
  it("is still on screen after several reads that change nothing", async () => {
    server.use(recordedFailure("error.429"));
    await openEditor({ pollMs: 20 });
    await approve();
    await screen.findByRole("alert");

    // `GET /research/{id}` answering `pending_review` is proof the decision
    // did NOT take effect — not proof it was never made. Before WO-S3 the
    // read cleared the failure, so the one sentence explaining a
    // rate-limited approval erased itself within twenty seconds of appearing.
    await waitFor(
      () =>
        expect(screen.getByRole("alert")).toHaveTextContent(
          FAILURE_COPY.rate_limited.sentence,
        ),
      { timeout: 1000 },
    );
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(screen.getByRole("alert")).toHaveTextContent(
      FAILURE_COPY.rate_limited.sentence,
    );
  });

  it("clears when the user tries again, not before", async () => {
    server.use(recordedFailure("error.429"));
    await openEditor();
    await approve();
    await screen.findByRole("alert");

    // The next attempt is a new decision, so the machine clears the old
    // failure at `review_requested`. This one is allowed to succeed.
    server.use(
      http.post(REVIEW_PATH, async ({ params, request }) => {
        reviews.push(await request.json());
        return HttpResponse.json({
          job_id: String(params.jobId),
          status: "pending_review",
          action: "approve",
        });
      }),
    );
    await approve();

    await waitFor(() => expect(reviews).toHaveLength(2));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

// ---------------------------------------------------------------------------
// The success path, unchanged.
// ---------------------------------------------------------------------------

describe("nothing regresses when the approval is accepted", () => {
  it("sends one decision, shows no failure, and stands the editor down", async () => {
    server.use(
      http.post(REVIEW_PATH, async ({ params, request }) => {
        reviews.push(await request.json());
        // `ReviewResponse.status` is always `pending_review` by design
        // (`schemas.py:141-160`); a 200 does not mean the run resumed.
        return HttpResponse.json({
          job_id: String(params.jobId),
          status: "pending_review",
          action: "approve",
        });
      }),
    );
    await openEditor();
    await approve();

    // Unchanged from `main`, and asserted so it stays that way: a 200 sends
    // the machine to `resolving` with `plan: null` (`machine.ts`'s
    // `review_accepted`), so the editor stands down and the spine carries
    // the pause from there. No banner of any kind appears.
    await waitFor(() =>
      expect(
        document.querySelector('[data-surface="plan-editor"]'),
      ).toBeNull(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      document.querySelector('[data-surface="active-run"]'),
    ).toHaveAttribute("data-run-phase", "resolving");
    expect(reviews).toEqual([{ action: "approve" }]);
  });
});

// ---------------------------------------------------------------------------
// The warning that was written, tested, and rendered by nothing.
// ---------------------------------------------------------------------------

describe("the irreversibility hint is on screen before the commitment", () => {
  it("describes the primary control", async () => {
    await openEditor();
    const primary = await screen.findByRole("button", { name: PLAN.approve });
    expect(primary).toHaveAccessibleDescription(
      expect.stringContaining(PLAN.cancelHint),
    );
  });

  it("is visible, not only announced", async () => {
    await openEditor();
    expect(screen.getByText(PLAN.cancelHint)).toBeVisible();
  });
});
