/**
 * WO-S2c — the run panel's mount reservation, in the half jsdom can hold.
 *
 * `e2e/mount-reservation.spec.ts` owns the pixels, because layout is the one
 * thing jsdom does not have. What is assertable HERE is the mechanism the
 * pixels come out of, and it is the half that will actually rot: WHEN the
 * thread's loading frame is held, and — the regression that matters more —
 * when it must not be.
 *
 * THE DEFECT. On a cold load of `/c/{id}?job={id}` the two reads race.
 * `GET /conversations/{id}` usually wins, so the thread painted with the run
 * row reporting `attached` — the 224px bounded box — about a run nobody had
 * read yet, and `GET /research/{id}` then turned it into the 1,769px review
 * pause. At 412x915 that pushed the reading column and the composer entirely
 * off screen: 0.55191 against 04 §8.2's 0.02.
 *
 * THE HAZARD IN THE FIX, WHICH IS WHY THE THIRD TEST EXISTS. "`attaching`
 * with no detail" is also true a beat after any NEW attach — a follow-up
 * submission, or the rail moving to another run — and a thread that fell back
 * to a skeleton there would throw the whole transcript away every time
 * somebody asks a second question. The hold is a MOUNT reservation and holds
 * once.
 */

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import { ActiveRunPanel, isRunUnread } from "@/components/features/ActiveRunPanel";
import {
  FollowUpComposer,
  ThreadTimeline,
} from "@/components/features/ThreadTimeline";
import { API_BASE, type ConversationDetail, type JobDetail } from "@/lib/api/index";
import { initialJobState } from "@/lib/job/machine";
import { JobRunProvider } from "@/lib/job/provider";
import type { JobClient } from "@/lib/job/types";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture, setupMswServer } from "../support/msw";
import { render, screen, waitFor } from "../support/render";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children?: ReactNode }) =>
    createElement("div", { "data-markdown": "true" }, children),
}));

const DETAIL = loadFixture("conversations.detail").body as ConversationDetail;
const THREAD_ID = DETAIL.conversation_id;
const PAUSED = loadFixture("job.pending_review").body as JobDetail;

setupMswServer(
  http.get(`${API_BASE}/conversations/:conversationId`, () =>
    HttpResponse.json(DETAIL),
  ),
);

beforeEach(() => {
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
});

/** A `getJob` whose answer the test decides when to give. */
function deferredClient(): {
  client: Partial<JobClient>;
  resolve: (detail: JobDetail) => void;
  calls: () => number;
} {
  let settle: ((detail: JobDetail) => void) | null = null;
  let calls = 0;
  return {
    client: {
      getJob: (jobId: string) => {
        calls += 1;
        return new Promise<JobDetail>((resolvePromise) => {
          settle = (detail) => resolvePromise({ ...detail, job_id: jobId });
        });
      },
    },
    resolve: (detail) => settle?.(detail),
    calls: () => calls,
  };
}

/** The route's own composition, minus the router. */
function Workspace({
  jobId,
  client,
}: {
  jobId: string | null;
  client?: Partial<JobClient>;
}): ReactElement {
  return (
    <QueryProvider>
      <JobRunProvider jobId={jobId} conversationId={THREAD_ID} client={client}>
        <ThreadTimeline
          conversationId={THREAD_ID}
          runPanel={
            <ActiveRunPanel conversationId={THREAD_ID} adoptJobId={jobId} />
          }
          composer={<FollowUpComposer conversationId={THREAD_ID} />}
        />
      </JobRunProvider>
    </QueryProvider>
  );
}

const skeleton = () => document.querySelector('[data-recovery-surface="loading"]');
const runRow = () => document.querySelector(".ew-thread__run");

// ---------------------------------------------------------------------------
// The predicate.
// ---------------------------------------------------------------------------

describe("isRunUnread — the window in which the panel knows nothing about the run", () => {
  it("is true only while an attach is in flight with no detail in hand", () => {
    expect(isRunUnread({ ...initialJobState, phase: "attaching" })).toBe(true);
    // Every other phase has either an answer or no question.
    for (const phase of [
      "idle",
      "submitting",
      "live",
      "awaiting_review",
      "resolving",
      "settled",
      "unavailable",
    ] as const) {
      expect(isRunUnread({ ...initialJobState, phase }), phase).toBe(false);
    }
  });

  /**
   * THE 409, AND WHY THE PREDICATE READS `detail` RATHER THAN THE PHASE ALONE.
   *
   * `machine.ts`'s `review_conflict` cell sends the machine back through
   * `attaching` to re-read the run, and it keeps the detail it already has.
   * WO-S3 exists because reading the phase alone there took the plan editor —
   * with the user's edits and the conflict banner in it — off screen at
   * exactly the moment they needed it. A hold keyed on the phase alone would
   * be that defect again, one surface up: the whole transcript, replaced by a
   * skeleton, because somebody else resolved the review.
   */
  it("is false on the 409 re-attach, which carries the detail it already read", () => {
    expect(
      isRunUnread({
        ...initialJobState,
        phase: "attaching",
        jobId: PAUSED.job_id,
        detail: PAUSED,
      }),
    ).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// The hold.
// ---------------------------------------------------------------------------

describe("WO-S2c — the thread waits for the run it names", () => {
  it("holds the loading frame after the transcript lands, until the run is read", async () => {
    const run = deferredClient();
    render(<Workspace jobId={PAUSED.job_id} client={run.client} />);

    // The transcript has arrived — the query resolved and the title is
    // available — and the thread is still the loading frame, because the run
    // behind `?job=` has not answered.
    await waitFor(() => expect(run.calls()).toBe(1));
    await waitFor(() => expect(skeleton()).not.toBeNull());
    expect(
      screen.queryByRole("heading", { level: 1, name: DETAIL.title }),
      "the thread painted before the run it names had been read. The row " +
        "would have reported `attached` about a run with no status, and the " +
        "read would then have moved everything below it.",
    ).toBeNull();
    expect(runRow()).toBeNull();

    // The read lands. The thread paints once, already in the review pause's
    // shape — which is the whole reservation.
    run.resolve(PAUSED);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    expect(skeleton()).toBeNull();
    expect(runRow()?.getAttribute("data-run")).toBe("review");
  });

  it("never takes the thread away again once it has been on screen", async () => {
    const first = deferredClient();
    const { rerender } = render(
      <Workspace jobId={PAUSED.job_id} client={first.client} />,
    );
    first.resolve(PAUSED);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });

    // A NEW attach, with nothing read about it: `attach_requested` runs
    // `freshRun`, so this is `attaching` with a null detail — byte for byte
    // the state the hold above is keyed on. It is also what a follow-up
    // submission looks like a beat after `POST /research` answers.
    const second = deferredClient();
    rerender(<Workspace jobId="baseline-second" client={second.client} />);

    await waitFor(() => expect(runRow()?.getAttribute("data-run")).toBe("attached"));
    expect(
      screen.queryByRole("heading", { level: 1, name: DETAIL.title }),
      "the transcript was replaced by a skeleton on a re-attach. The hold is " +
        "a MOUNT reservation: it holds before the thread has ever been " +
        "painted and never afterwards.",
    ).not.toBeNull();
    expect(skeleton()).toBeNull();
  });

  /**
   * The `?job=`-less load, which is the commonest one on this route and must
   * not have been slowed down by any of the above: with no run named there is
   * nothing to wait for, and `isRunUnread` is false from the first render.
   */
  it("does not hold a thread that names no run", async () => {
    render(<Workspace jobId={null} />);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    expect(runRow()?.getAttribute("data-run")).toBe("none");
  });
});
