/**
 * WO-08 criterion 2, second half — `/c/[id]?job=` is byte-identical after
 * the move into the `(workspace)` route group.
 *
 * `web/tests/shell/routing.test.ts` proves the *pathname* is unchanged by
 * applying the App Router's route-group rule to the filesystem. This file
 * proves the other half, which is the half that costs money if it breaks:
 * the page still reads `?job=` out of the URL and hands it to the thread as
 * `adoptJobId`. ADR 0053 exists because that id was once thrown away — the
 * user was billed for a planner call and then watched a page that never
 * streamed it — so "the shell moved and nothing else changed" is a claim
 * that needs an assertion, not a comment.
 *
 * `ConversationThread` is stubbed on purpose. The real component opens an
 * EventSource and fetches a conversation; this file is about what the ROUTE
 * passes down, and web/tests/ConversationThread.test.tsx already owns what
 * the component does with it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConversationPage from "@/app/(workspace)/c/[id]/page";

import { render, screen } from "../support/render";

let params: { id: string } | null = { id: "conv-1" };
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useParams: () => params,
  useSearchParams: () => search,
}));

vi.mock("@/components/ConversationThread", () => ({
  default: ({
    conversationId,
    adoptJobId,
  }: {
    conversationId: string;
    adoptJobId?: string | null;
  }) => (
    <div
      data-testid="thread"
      data-conversation-id={conversationId}
      data-adopt-job-id={adoptJobId ?? ""}
    />
  ),
}));

beforeEach(() => {
  params = { id: "conv-1" };
  search = new URLSearchParams();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("criterion 2 — the `?job=` hand-off survives the route group", () => {
  it("adopts the job named in the URL", async () => {
    search = new URLSearchParams("job=job-1");
    render(<ConversationPage />);

    const thread = await screen.findByTestId("thread");
    expect(thread).toHaveAttribute("data-conversation-id", "conv-1");
    expect(thread).toHaveAttribute("data-adopt-job-id", "job-1");
  });

  it("adopts nothing when there is no `job` parameter", async () => {
    render(<ConversationPage />);

    const thread = await screen.findByTestId("thread");
    expect(thread).toHaveAttribute("data-conversation-id", "conv-1");
    expect(thread).toHaveAttribute("data-adopt-job-id", "");
  });

  it("carries a percent-encoded id through as the decoded segment", async () => {
    // `useParams` decodes; the landing page encodes on the way in
    // (web/tests/HomePage.test.tsx). Both halves of that round trip are
    // unchanged by the move.
    params = { id: "conv/1 2" };
    search = new URLSearchParams("job=job 1");
    render(<ConversationPage />);

    const thread = await screen.findByTestId("thread");
    expect(thread).toHaveAttribute("data-conversation-id", "conv/1 2");
    expect(thread).toHaveAttribute("data-adopt-job-id", "job 1");
  });

  it("renders an empty id rather than throwing when the segment is missing", async () => {
    params = null;
    render(<ConversationPage />);

    const thread = await screen.findByTestId("thread");
    expect(thread).toHaveAttribute("data-conversation-id", "");
  });

  it("renders no landmark of its own — the shell owns them", () => {
    const { container } = render(<ConversationPage />);
    expect(container.querySelector("main")).toBeNull();
    expect(container.querySelector("aside")).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
  });
});
