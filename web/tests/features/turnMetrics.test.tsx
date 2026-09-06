/**
 * WO-S8 — the metrics survive a reload.
 *
 * THE DEFECT, IN ONE SENTENCE. `MetricsStrip` was rendered only when
 * `ThreadTimeline` had a `JobDetail` in hand, and the only `JobDetail` it
 * ever had was the JOB MACHINE's — passed down as `briefing.live ?
 * state.detail : null`. So the five numbers, the dollar figure among them,
 * were on screen while this tab happened to be the one attached to the run
 * and nowhere else. Reload the thread, or reach it from the rail without
 * `?job=`, and the cost of a run the user has already paid for was gone.
 *
 * IT WAS NEVER A CONTRACT LIMIT, WHICH IS WHY THIS IS A BUG AND NOT A GAP.
 * `GET /research/{id}` is free and read-only (`routes.py:215-232`) and
 * reports all five fields for as long as the record is retained. What
 * carries no metrics is `ConversationJobSummary` (`schemas.py:207-214`) —
 * job id, ordinal, query, report, created_at — so the THREAD read cannot
 * supply them and the turn has to ask for its own.
 *
 * WHAT THESE TESTS PIN BESIDES "the numbers are there". Three limits, each
 * of which is a way the fix could have been worse than the defect:
 *
 *   1. A COLLAPSED TURN ASKS FOR NOTHING. The same rule criterion 4 applies
 *      to the Markdown pipeline: a ten-turn thread must not issue ten reads
 *      to show one turn.
 *   2. THE LIVE TURN KEEPS ONE AUTHORITY. The machine is already reading
 *      that job; a second reader for the same run is the shape of the
 *      double-render defect `selectBriefings` exists to prevent.
 *   3. A RETIRED RUN CONTRIBUTES NOTHING. Records expire
 *      (`api_job_retention_sec`) and the read 404s. The strip is then absent
 *      rather than showing five em dashes, because "not reported" is a claim
 *      about a run that answered, and a 404 did not answer.
 *
 * Every test here fails on `origin/main` at 3d0d588 except the two that
 * assert a limit main also holds (the collapsed-turn count, and the live
 * turn) — those are green on both sides on purpose, so a fix that bought the
 * numbers with a request storm would go red here rather than pass quietly.
 */

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import { ActiveRunPanel } from "@/components/features/ActiveRunPanel";
import { ThreadTimeline } from "@/components/features/ThreadTimeline";
import { API_BASE, type ConversationDetail, type JobDetail } from "@/lib/api/index";
import { METRICS } from "@/lib/copy/metrics";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture, server, setupMswServer } from "../support/msw";
import { render, screen, user, waitFor, within } from "../support/render";

vi.mock("react-markdown", () => ({
  default: ({ children }: { children?: ReactNode }) =>
    createElement("div", { "data-markdown": "true" }, children),
}));

const DETAIL = loadFixture("conversations.detail").body as ConversationDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;
const THREAD_ID = DETAIL.conversation_id;
const FIRST_JOB = DETAIL.jobs[0]!;

/** The recorded run's own cost, formatted the way `MetricsStrip` formats it. */
const COST = `$${(SUCCEEDED.cost_usd as number).toFixed(4)}`;

/** Two turns, so "only the expanded one reads" is a real distinction. */
const TWO_TURNS: ConversationDetail = {
  ...DETAIL,
  jobs: [
    {
      ...FIRST_JOB,
      job_id: "baseline-older",
      ordinal: 1,
      query: "What did the earlier turn ask?",
      report: "# An older briefing\n\nWritten before the newest turn.",
    },
    { ...FIRST_JOB, ordinal: 2 },
  ],
};

/** Every `GET /research/{id}`, in order. The request-count assertions' source. */
let jobReads: string[] = [];

setupMswServer(
  http.get(`${API_BASE}/conversations/:conversationId`, () =>
    HttpResponse.json(TWO_TURNS),
  ),
  http.get(`${API_BASE}/research/:jobId`, ({ params }) => {
    const jobId = String(params.jobId);
    jobReads.push(jobId);
    if (jobId === SUCCEEDED.job_id) return HttpResponse.json(SUCCEEDED);
    // Everything else is a run this deployment no longer has — the same
    // answer the backend gives for "missing" and for "someone else's"
    // (`routes.py:59-84`).
    return HttpResponse.json({ detail: "Job not found" }, { status: 404 });
  }),
);

beforeEach(() => {
  jobReads = [];
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
});

/**
 * The route's composition, minus the router — and, by default, with NO run
 * attached, which is precisely the reloaded thread this work order is about.
 */
function Workspace({ jobId = null }: { jobId?: string | null }): ReactElement {
  return (
    <QueryProvider>
      <JobRunProvider jobId={jobId} conversationId={THREAD_ID}>
        <ThreadTimeline
          conversationId={THREAD_ID}
          runPanel={<ActiveRunPanel conversationId={THREAD_ID} adoptJobId={jobId} />}
        />
      </JobRunProvider>
    </QueryProvider>
  );
}

function strip(): HTMLElement | null {
  return document.querySelector("[data-metrics='true']");
}

function turnButtons(): HTMLElement[] {
  return screen.getAllByRole("button", { name: /^Turn \d/ });
}

// ---------------------------------------------------------------------------

describe("a reloaded thread still shows what the run cost", () => {
  it("renders the five numbers for the newest turn with no run attached", async () => {
    render(<Workspace />);
    await screen.findByRole("button", { name: /^Turn 2/ });

    const found = await waitFor(() => {
      const element = strip();
      expect(element).not.toBeNull();
      return element as HTMLElement;
    });

    // The strip is named, and it is the run's own recorded figures — not a
    // placeholder and not a computed one.
    expect(found.getAttribute("aria-label")).toBe(METRICS.label);
    expect(found.textContent).toContain(COST);
    expect(within(found).getByText(METRICS.costLabel)).toBeInTheDocument();
    expect(
      (found.querySelector("[data-field='costUsd']") as HTMLElement).textContent,
    ).toBe(COST);
    expect(jobReads).toEqual([SUCCEEDED.job_id]);
  });

  it("asks for nothing on behalf of a collapsed turn", async () => {
    // Green on `origin/main` too, deliberately: it is the limit, not the
    // fix. Turn 1 is collapsed on arrival and stays collapsed here.
    render(<Workspace />);
    await screen.findByRole("button", { name: /^Turn 1/ });
    await waitFor(() => expect(strip()).not.toBeNull());
    expect(jobReads).not.toContain("baseline-older");
    expect(jobReads).toEqual([SUCCEEDED.job_id]);
  });

  it("reads the older turn's run only once the reader opens it", async () => {
    const reader = user();
    render(<Workspace />);
    await screen.findByRole("button", { name: /^Turn 1/ });
    await waitFor(() => expect(strip()).not.toBeNull());
    expect(jobReads).toEqual([SUCCEEDED.job_id]);

    const [older] = turnButtons();
    await reader.click(older as HTMLElement);
    await waitFor(() => expect(jobReads).toContain("baseline-older"));
  });
});

describe("a run the server no longer has says nothing rather than saying zero", () => {
  it("renders no strip at all for a 404", async () => {
    server.use(
      http.get(`${API_BASE}/conversations/:conversationId`, () =>
        HttpResponse.json({
          ...DETAIL,
          jobs: [{ ...FIRST_JOB, job_id: "baseline-retired" }],
        }),
      ),
    );
    render(<Workspace />);
    await screen.findByRole("button", { name: /^Turn 1/ });
    await waitFor(() => expect(jobReads).toContain("baseline-retired"));

    // Five em dashes would be a claim: "the run reported no cost". A run the
    // server cannot find reported nothing at all, and the difference matters
    // to a reader deciding whether a number is missing or a run is.
    expect(strip()).toBeNull();
    expect(screen.queryByText(METRICS.absentNote)).toBeNull();
  });
});

describe("the run this browser is watching keeps one authority", () => {
  it("does not open a second read for the live turn", async () => {
    // Green on `origin/main` too. The machine attaches, reads the job and
    // owns `state.detail`; the turn must consume that rather than fetch the
    // same run again, which is the shape of the double-render defect
    // `selectBriefings` was written to prevent.
    render(<Workspace jobId={SUCCEEDED.job_id} />);
    await waitFor(() => expect(strip()).not.toBeNull());
    expect(strip()?.textContent).toContain(COST);
    // One read, and it is the machine's attach — never two for one run.
    expect(jobReads.filter((id) => id === SUCCEEDED.job_id)).toHaveLength(1);
  });
});
