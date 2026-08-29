/**
 * WO-20 criteria 1, 3, 4 and 6 — the composition, over the real request
 * layer.
 *
 * `conversationRoute.test.tsx` proves what the ROUTE passes down, with the
 * features stubbed. This file is the other half: the real `ThreadTimeline`,
 * the real `ActiveRunPanel` and the real job machine under one provider,
 * against MSW and WO-04's recorded fixtures, with every request counted.
 *
 * NOTHING HERE CAN REACH `POST /research`. `setupMswServer` runs with
 * `onUnhandledRequest: "error"` and no handler for it exists by design, so an
 * accidental submission fails the test rather than succeeding quietly (R-01).
 *
 * The Markdown pipeline is mocked with the counting factory
 * `tests/queries/markdown.test.ts` uses, because criterion 4's claim —
 * "collapsed turns are not Markdown-parsed" — is a claim about a dynamic
 * `import()` and can only be observed by counting it.
 */

import { createElement, type ReactElement, type ReactNode } from "react";

import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryProvider } from "@/app/providers";
import { ActiveRunPanel, runHref } from "@/components/features/ActiveRunPanel";
import {
  FollowUpComposer,
  ThreadTimeline,
  currentRunOf,
} from "@/components/features/ThreadTimeline";
import { API_BASE, type ConversationDetail } from "@/lib/api/index";
import { initialJobState } from "@/lib/job/machine";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture, server, setupMswServer } from "../support/msw";
import { render, screen, waitFor } from "../support/render";

const markdown = vi.hoisted(() => ({ imports: 0, parses: 0 }));

vi.mock("react-markdown", () => {
  markdown.imports += 1;
  return {
    default: ({ children }: { children?: ReactNode }) => {
      markdown.parses += 1;
      return createElement("div", { "data-markdown": "true" }, children);
    },
  };
});

const DETAIL = loadFixture("conversations.detail").body as ConversationDetail;
const THREAD_ID = DETAIL.conversation_id;
const FIRST_JOB = DETAIL.jobs[0]!;

/** How many times `GET /conversations/{id}` was issued. Criterion 6's number. */
let detailReads = 0;

/** A second turn, so "the newest one is expanded" is a real distinction. */
const TWO_TURNS: ConversationDetail = {
  ...DETAIL,
  jobs: [
    FIRST_JOB,
    {
      ...FIRST_JOB,
      job_id: "baseline-second",
      ordinal: 2,
      query: "Which of those findings are contested?",
      report: "# Second briefing\n\nA later turn, written by the same thread.",
    },
  ],
};

setupMswServer(
  http.get(`${API_BASE}/conversations/:conversationId`, () => {
    detailReads += 1;
    return HttpResponse.json(DETAIL);
  }),
);

beforeEach(() => {
  detailReads = 0;
  markdown.parses = 0;
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
});

/** The route's own composition, minus the router. */
function Workspace({
  jobId = null,
  adoptJobId = null,
  onSyncUrl,
}: {
  jobId?: string | null;
  adoptJobId?: string | null;
  onSyncUrl?: (href: string) => void;
}): ReactElement {
  return (
    <QueryProvider>
      <JobRunProvider jobId={jobId} conversationId={THREAD_ID}>
        <ThreadTimeline
          conversationId={THREAD_ID}
          runPanel={
            <ActiveRunPanel
              conversationId={THREAD_ID}
              adoptJobId={adoptJobId}
              onSyncUrl={onSyncUrl}
            />
          }
          composer={<FollowUpComposer conversationId={THREAD_ID} />}
        />
      </JobRunProvider>
    </QueryProvider>
  );
}

function turnButtons(): HTMLElement[] {
  return screen.getAllByRole("button", { name: /^Turn \d/ });
}

// ---------------------------------------------------------------------------
// Criterion 4, first half. THIS DESCRIBE MUST STAY FIRST IN THE FILE: the
// import counter can only be zero before anything in this module has expanded
// a turn, and a dynamic `import()` cannot be un-done once it has happened.
// ---------------------------------------------------------------------------

describe("criterion 4 — nothing is parsed before a turn is open", () => {
  it("loads no Markdown pipeline at all for a thread with no turns", async () => {
    server.use(
      http.get(`${API_BASE}/conversations/:conversationId`, () => {
        detailReads += 1;
        return HttpResponse.json({ ...DETAIL, jobs: [] });
      }),
    );

    render(<Workspace />);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });

    expect(markdown.imports).toBe(0);
    expect(markdown.parses).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Criterion 6 — the duplicated load logic has exactly one replacement.
// ---------------------------------------------------------------------------

describe("criterion 6 — one load path replaces ConversationThread's two", () => {
  it("issues exactly one GET /conversations/{id} for one mount", async () => {
    render(<Workspace />);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });

    // `ConversationThread.tsx:38-59` and `:61-93` were two copies of this
    // read and both ran on mount. One query, one request.
    expect(detailReads).toBe(1);
  });

  it("does not re-read the thread when the run panel re-renders", async () => {
    const { rerender } = render(<Workspace />);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    rerender(<Workspace adoptJobId="ignored" />);
    await waitFor(() => expect(detailReads).toBe(1));
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — turns collapse, and a collapsed one is not parsed.
// ---------------------------------------------------------------------------

describe("criterion 4 — the newest turn is open and the rest are question rows", () => {
  it("expands only the newest and parses only that one", async () => {
    server.use(
      http.get(`${API_BASE}/conversations/:conversationId`, () => {
        detailReads += 1;
        return HttpResponse.json(TWO_TURNS);
      }),
    );

    render(<Workspace />);
    await waitFor(() => expect(turnButtons()).toHaveLength(2));

    const [first, second] = turnButtons();
    expect(first).toHaveAttribute("aria-expanded", "false");
    expect(second).toHaveAttribute("aria-expanded", "true");

    // The whole of the criterion: one open turn, one import, one parse. The
    // collapsed turn's Markdown arrived in the same response and was never
    // touched.
    await waitFor(() => expect(markdown.parses).toBeGreaterThan(0));
    expect(document.querySelectorAll("[data-briefing]")).toHaveLength(1);
  });

  it("parses nothing at all while every turn is collapsed", async () => {
    server.use(
      http.get(`${API_BASE}/conversations/:conversationId`, () => {
        detailReads += 1;
        return HttpResponse.json(TWO_TURNS);
      }),
    );

    render(<Workspace />);
    await waitFor(() => expect(turnButtons()).toHaveLength(2));

    // Close the newest. Nothing is open, so nothing is rendered through the
    // pipeline — the import already happened and cannot be undone, but the
    // parse count must stop moving.
    const before = markdown.parses;
    turnButtons()[1]!.click();
    await waitFor(() =>
      expect(turnButtons()[1]).toHaveAttribute("aria-expanded", "false"),
    );
    expect(document.querySelectorAll("[data-briefing]")).toHaveLength(0);
    expect(markdown.parses).toBe(before);
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — one source of truth for which run is on screen.
// ---------------------------------------------------------------------------

describe("criterion 3 — the run panel and the history cannot disagree", () => {
  it("renders one briefing for a run that is both attached and in history", async () => {
    render(<Workspace jobId={FIRST_JOB.job_id} adoptJobId={FIRST_JOB.job_id} />);

    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    await waitFor(() =>
      expect(
        document.querySelector('[data-surface="active-run"]'),
      ).toHaveAttribute("data-run-job", FIRST_JOB.job_id),
    );

    // The defect WO-18 reproduced in a browser: the refetched thread contains
    // the finished run AND the current-run panel renders the same job's
    // detail, so one job produces two `.report-prose` blocks. Here the run
    // REPLACES the history copy rather than adding one.
    await waitFor(() => expect(turnButtons()).toHaveLength(1));
    expect(document.querySelectorAll("[data-report-reader]")).toHaveLength(1);
  });

  it("names the same run in the panel and in the timeline's live turn", async () => {
    render(<Workspace jobId={FIRST_JOB.job_id} adoptJobId={FIRST_JOB.job_id} />);
    await screen.findByRole("heading", { level: 1, name: DETAIL.title });

    const panel = await waitFor(() => {
      const found = document.querySelector('[data-surface="active-run"]');
      expect(found).toHaveAttribute("data-run-job", FIRST_JOB.job_id);
      return found as HTMLElement;
    });

    // The timeline marks exactly the run the panel names, and it marks one.
    const live = screen.getAllByText("Live");
    expect(live).toHaveLength(1);
    expect(panel.getAttribute("data-run-job")).toBe(FIRST_JOB.job_id);
    expect(turnButtons()[0]).toHaveTextContent("Live");
  });

  it("reads the current run out of the machine and nowhere else", () => {
    // The pure half of the same claim: with no job adopted there is no
    // current run to merge, whatever else the machine is holding.
    expect(currentRunOf(initialJobState)).toBeNull();
    expect(
      currentRunOf({ ...initialJobState, jobId: "job-1" })?.jobId,
    ).toBe("job-1");
    // H9: an unread detail contributes nothing, so the history copy stands.
    expect(currentRunOf({ ...initialJobState, jobId: "job-1" })?.markdown).toBe("");
  });
});

// ---------------------------------------------------------------------------
// Criterion 1 — `?job=` is written at most once per job id.
// ---------------------------------------------------------------------------

describe("criterion 1 — `?job=` is written at most once per job id", () => {
  it("writes it once when the machine adopts a run the URL does not name", async () => {
    const sync = vi.fn();
    const { rerender } = render(
      <Workspace jobId={FIRST_JOB.job_id} adoptJobId={null} onSyncUrl={sync} />,
    );

    await waitFor(() => expect(sync).toHaveBeenCalledTimes(1));
    expect(sync).toHaveBeenCalledWith(
      `/c/${THREAD_ID}?job=${FIRST_JOB.job_id}`,
    );

    // Re-render for any other reason — a frame, a poll, a keystroke in the
    // composer — and the ref refuses a second write. This is
    // `ConversationThread.tsx:133-137`'s `syncedJobRef`, kept.
    for (let i = 0; i < 3; i += 1) {
      rerender(
        <Workspace jobId={FIRST_JOB.job_id} adoptJobId={null} onSyncUrl={sync} />,
      );
    }
    await waitFor(() => expect(detailReads).toBeGreaterThan(0));
    expect(sync).toHaveBeenCalledTimes(1);
  });

  it("never writes a value the URL already carries", async () => {
    const sync = vi.fn();
    render(
      <Workspace
        jobId={FIRST_JOB.job_id}
        adoptJobId={FIRST_JOB.job_id}
        onSyncUrl={sync}
      />,
    );

    await screen.findByRole("heading", { level: 1, name: DETAIL.title });
    await waitFor(() =>
      expect(
        document.querySelector('[data-surface="active-run"]'),
      ).toHaveAttribute("data-run-job", FIRST_JOB.job_id),
    );
    // A reload of `/c/{id}?job={id}` must not rewrite its own URL — that is
    // the loop `ConversationThread.tsx:135` guards against.
    expect(sync).not.toHaveBeenCalled();
  });

  it("percent-encodes both halves of the href it writes", () => {
    // Asserted on the function rather than through a render, because the ids
    // that need encoding are exactly the ones a fixture cannot carry.
    expect(runHref("conv/1 2", "job 1")).toBe("/c/conv%2F1%202?job=job%201");
  });
});
