/**
 * WO-08 criterion 2, second half — `/c/[id]?job=` is byte-identical after
 * the move into the `(workspace)` route group — and WO-20 criterion 3, which
 * is the same claim about a different receiver.
 *
 * `web/tests/shell/routing.test.ts` proves the *pathname* is unchanged by
 * applying the App Router's route-group rule to the filesystem. This file
 * proves the other half, which is the half that costs money if it breaks:
 * the page still reads `?job=` out of the URL, and everything under it is
 * told about that run through exactly one machine.
 *
 * WHAT WO-20 CHANGED. The value used to be `ConversationThread`'s
 * `adoptJobId` prop; it is now `JobRunProvider`'s `jobId` — the provider
 * attaches, re-attaches when the value changes, and never POSTs (ADR 0053) —
 * and `ActiveRunPanel` is given the same value so it can tell "the URL
 * already says this" from "the URL has to be told" (criterion 1). Both are
 * asserted below, from the same render, which is what makes "one source of
 * truth" a property of the route rather than of a comment.
 *
 * The three features are stubbed on purpose. The real ones open an
 * EventSource and fetch a thread; this file is about what the ROUTE passes
 * down, and `web/tests/features/routeComposition.test.tsx` owns what the
 * composition does with it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConversationPage from "@/app/(workspace)/c/[id]/page";

import { render, screen } from "../support/render";

let params: { id: string } | null = { id: "conv-1" };
let search = new URLSearchParams();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useSearchParams: () => search,
  useRouter: () => ({ replace, push: vi.fn(), prefetch: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/job/provider", () => ({
  JobRunProvider: ({
    children,
    jobId,
    conversationId,
  }: {
    children: React.ReactNode;
    jobId?: string | null;
    conversationId?: string | null;
  }) => (
    <div
      data-testid="machine"
      data-job-id={jobId ?? ""}
      data-conversation-id={conversationId ?? ""}
    >
      {children}
    </div>
  ),
}));

vi.mock("@/components/features/ActiveRunPanel", () => ({
  ActiveRunPanel: ({
    conversationId,
    adoptJobId,
  }: {
    conversationId: string;
    adoptJobId: string | null;
  }) => (
    <div
      data-testid="run-panel"
      data-conversation-id={conversationId}
      data-adopt-job-id={adoptJobId ?? ""}
    />
  ),
}));

vi.mock("@/components/features/ThreadTimeline", () => ({
  ThreadTimeline: ({
    conversationId,
    runPanel,
    composer,
  }: {
    conversationId: string;
    runPanel?: React.ReactNode;
    composer?: React.ReactNode;
  }) => (
    <div data-testid="thread" data-conversation-id={conversationId}>
      {runPanel}
      {composer}
    </div>
  ),
  FollowUpComposer: ({ conversationId }: { conversationId: string }) => (
    <div data-testid="composer" data-conversation-id={conversationId} />
  ),
}));

beforeEach(() => {
  params = { id: "conv-1" };
  search = new URLSearchParams();
  replace.mockClear();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("criterion 2 — the `?job=` hand-off survives the route group", () => {
  it("adopts the job named in the URL", async () => {
    search = new URLSearchParams("job=job-1");
    render(<ConversationPage />);

    const machine = await screen.findByTestId("machine");
    expect(machine).toHaveAttribute("data-conversation-id", "conv-1");
    expect(machine).toHaveAttribute("data-job-id", "job-1");
  });

  it("adopts nothing when there is no `job` parameter", async () => {
    render(<ConversationPage />);

    const machine = await screen.findByTestId("machine");
    expect(machine).toHaveAttribute("data-conversation-id", "conv-1");
    expect(machine).toHaveAttribute("data-job-id", "");
  });

  it("carries a percent-encoded id through as the decoded segment", async () => {
    // `useParams` decodes; the landing composer encodes on the way in
    // (web/tests/HomePage.test.tsx). Both halves of that round trip are
    // unchanged by the move and by the rewrite.
    params = { id: "conv/1 2" };
    search = new URLSearchParams("job=job 1");
    render(<ConversationPage />);

    const machine = await screen.findByTestId("machine");
    expect(machine).toHaveAttribute("data-conversation-id", "conv/1 2");
    expect(machine).toHaveAttribute("data-job-id", "job 1");
  });

  it("renders an empty id rather than throwing when the segment is missing", async () => {
    params = null;
    render(<ConversationPage />);

    expect(await screen.findByTestId("thread")).toHaveAttribute(
      "data-conversation-id",
      "",
    );
  });

  it("renders no landmark of its own — the shell owns them", () => {
    const { container } = render(<ConversationPage />);
    expect(container.querySelector("main")).toBeNull();
    expect(container.querySelector("aside")).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
  });
});

describe("WO-20 criterion 3 — one machine, one job, told to everything under it", () => {
  it("gives the run panel the same `?job=` it gives the machine", async () => {
    search = new URLSearchParams("job=job-1");
    render(<ConversationPage />);

    const machine = await screen.findByTestId("machine");
    const panel = await screen.findByTestId("run-panel");
    expect(panel).toHaveAttribute("data-adopt-job-id", "job-1");
    expect(panel.getAttribute("data-adopt-job-id")).toBe(
      machine.getAttribute("data-job-id"),
    );
  });

  it("mounts exactly one machine, so there is nowhere else to look", async () => {
    search = new URLSearchParams("job=job-1");
    render(<ConversationPage />);

    await screen.findByTestId("machine");
    expect(screen.getAllByTestId("machine")).toHaveLength(1);
  });

  it("gives every surface the same thread id", async () => {
    render(<ConversationPage />);

    const thread = await screen.findByTestId("thread");
    const panel = await screen.findByTestId("run-panel");
    const composer = await screen.findByTestId("composer");
    for (const node of [thread, panel, composer]) {
      expect(node).toHaveAttribute("data-conversation-id", "conv-1");
    }
  });
});
