import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CandidateReview } from "@/components/workspace/CandidateReview";
import type { ReviewPacket, UsefulnessFeedback } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
let packet: ReviewPacket | null;
let packetHistory: ReviewPacket[];
let failures: Record<string, number>;
let calls: { path: string; body: Record<string, unknown> }[];
const PACKET_ID = `review-${"a".repeat(32)}`;
function candidates(count = 10): ReviewPacket {
  return {
    id: PACKET_ID,
    created_at: "2026-11-02T15:00:00Z",
    as_of: "2026-11-02T15:00:00Z",
    profile_revision: 1,
    policy_version: "workspace-lexical-v2",
    items: Array.from({ length: count }, (_, index) => ({
      work: work({
        work_id: `stored-${index}`,
        version_id: `stored-${index}:v1`,
        title: `Stored candidate ${index + 1}`,
        abstract:
          index === 1
            ? ""
            : index === 2
              ? "🧭".repeat(610)
              : "A retained abstract about agent memory and retrieval.",
        access_state: index === 1 ? "metadata" : "abstract",
        entries: [],
        versions: [],
        reading: work().reading,
      }),
      matching_reason: ["Matches declared retrieval terms."],
      evidence_scope: index === 1 ? "metadata" : "abstract",
      estimated_minutes: 5,
      feedback: { revision: 0, label: null, reason: "", updated_at: "" },
    })),
    coverage: workspace().sources,
    selection: "Ten actual stored candidates at a fixed cutoff.",
    limitations: [
      "No personal usefulness is measured until you supply labels.",
    ],
    labelled_count: 0,
  };
}
beforeEach(() => {
  packet = candidates();
  packetHistory = [];
  failures = {};
  calls = [];
  window.history.replaceState(null, "", "/workspace/review");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = new URL(url, "http://localhost").pathname.replace(
        "/api/workspace/",
        "",
      );
      const body = init?.body
        ? (JSON.parse(String(init.body)) as Record<string, unknown>)
        : {};
      calls.push({ path, body });
      if (failures[path]) return new Response(null, { status: failures[path] });
      if (path === "context/state") return Response.json(workspace());
      if (path === "review") {
        const selected = new URL(url, "http://localhost").searchParams.get(
          "packet_id",
        );
        return Response.json({
          packet:
            packetHistory.find((candidate) => candidate.id === selected) ??
            packet,
          packet_ids: packetHistory.length
            ? packetHistory.map((candidate) => candidate.id)
            : packet
              ? [packet.id]
              : [],
        });
      }
      if (path === "review/prepare") {
        packet ??= candidates();
        return Response.json(packet);
      }
      if (path === "review/feedback") {
        const feedback: UsefulnessFeedback = {
          revision: Number(body.revision) + 1,
          label: body.label as UsefulnessFeedback["label"],
          reason: String(body.reason).trim(),
          updated_at: "2026-11-02T16:00:00Z",
        };
        const candidate = packet!.items.find(
          (candidate) => candidate.work.work_id === body.work_id,
        )!;
        candidate.feedback = feedback;
        packet!.labelled_count = packet!.items.filter(
          (candidate) => candidate.feedback.label !== null,
        ).length;
        return Response.json(feedback);
      }
      return new Response(null, { status: 404 });
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("finite personal usefulness review", () => {
  it("reads an existing ten-candidate packet with blank choices and never supplies a label on page load", async () => {
    render(<CandidateReview />);
    expect(
      await screen.findByRole("heading", {
        name: "10 candidates · 0 labelled",
      }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(30);
    expect(
      screen
        .getAllByRole("radio")
        .every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
    expect(calls.every((call) => ["context/state", "review"].includes(call.path))).toBe(
      true,
    );
    const first = screen.getByRole("article", { name: "Stored candidate 1" });
    expect(
      within(first).getByRole("link", { name: "Inspect retained source →" }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(
        `return_to=%2Fworkspace%2Freview%3Fpacket%3D${PACKET_ID}`,
      ),
    );
    expect(
      screen.getByText(
        "Only source metadata and the original link are available for this item.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(`${"🧭".repeat(600)}…`)).toBeInTheDocument();
  });
  it("saves an explicit usefulness choice against its frozen source version and changes the count only after acknowledgement", async () => {
    const user = userEvent.setup();
    render(<CandidateReview />);
    const first = await screen.findByRole("article", {
      name: "Stored candidate 1",
    });
    await user.click(within(first).getByRole("radio", { name: "Useful" }));
    await user.type(
      within(first).getByRole("textbox", {
        name: "Optional reason for candidate 1",
      }),
      "Useful for my fixed-compute evaluation question",
    );
    expect(
      screen.getByRole("heading", { name: "10 candidates · 0 labelled" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path === "review/feedback")).toBe(false);
    await user.click(
      within(first).getByRole("button", {
        name: "Save judgment for candidate 1",
      }),
    );
    expect(
      screen.getByRole("heading", { name: "10 candidates · 1 labelled" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Your useful label is saved on the server",
    );
    expect(
      calls.find((call) => call.path === "review/feedback")!.body,
    ).toMatchObject({
      packet_id: PACKET_ID,
      work_id: "stored-0",
      version_id: "stored-0:v1",
      revision: 0,
      label: "useful",
      reason: "Useful for my fixed-compute evaluation question",
    });
    await user.click(
      within(first).getByRole("button", { name: "Clear this label" }),
    );
    expect(
      screen.getByRole("heading", { name: "10 candidates · 1 labelled" }),
    ).toBeInTheDocument();
    await user.click(
      within(first).getByRole("button", {
        name: "Save judgment for candidate 1",
      }),
    );
    expect(
      screen.getByRole("heading", { name: "10 candidates · 0 labelled" }),
    ).toBeInTheDocument();
  });
  it("retains a failed judgment and reason, then retries the same id without inventing owner feedback", async () => {
    failures["review/feedback"] = 503;
    const user = userEvent.setup();
    render(<CandidateReview />);
    const first = await screen.findByRole("article", {
      name: "Stored candidate 1",
    });
    await user.click(within(first).getByRole("radio", { name: "Maybe" }));
    const reason = within(first).getByRole("textbox", {
      name: "Optional reason for candidate 1",
    });
    await user.type(reason, "Need the methods before deciding");
    await user.click(
      within(first).getByRole("button", {
        name: "Save judgment for candidate 1",
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Your text is still here",
    );
    expect(reason).toHaveValue("Need the methods before deciding");
    expect(within(first).getByRole("radio", { name: "Maybe" })).toBeChecked();
    expect(
      screen.getByRole("heading", { name: "10 candidates · 0 labelled" }),
    ).toBeInTheDocument();
    delete failures["review/feedback"];
    await user.click(
      within(first).getByRole("button", {
        name: "Save judgment for candidate 1",
      }),
    );
    const attempts = calls.filter((call) => call.path === "review/feedback");
    expect(attempts[0]!.body.request_id).toBe(attempts[1]!.body.request_id);
  });
  it("keeps a conflicting draft separate from reloaded server feedback until explicit discard", async () => {
    const user = userEvent.setup();
    render(<CandidateReview />);
    const first = await screen.findByRole("article", {
      name: "Stored candidate 1",
    });
    await user.click(within(first).getByRole("radio", { name: "Irrelevant" }));
    await user.type(
      within(first).getByRole("textbox", {
        name: "Optional reason for candidate 1",
      }),
      "My unsaved explanation",
    );
    failures["review/feedback"] = 409;
    await user.click(
      within(first).getByRole("button", {
        name: "Save judgment for candidate 1",
      }),
    );
    packet!.items[0]!.feedback = {
      revision: 2,
      label: "useful",
      reason: "A newer saved explanation",
      updated_at: "2026-11-02T17:00:00Z",
    };
    packet!.labelled_count = 1;
    await user.click(
      screen.getByRole("button", { name: "Reload saved review" }),
    );
    expect(
      within(first).getByRole("textbox", {
        name: "Optional reason for candidate 1",
      }),
    ).toHaveValue("My unsaved explanation");
    expect(
      within(first).getByText(/saved judgment changed elsewhere/),
    ).toBeInTheDocument();
    await user.click(
      within(first).getByRole("button", {
        name: "Discard draft and load saved judgment",
      }),
    );
    expect(within(first).getByRole("radio", { name: "Useful" })).toBeChecked();
    expect(
      within(first).getByRole("textbox", {
        name: "Optional reason for candidate 1",
      }),
    ).toHaveValue("A newer saved explanation");
  });
  it("prepares a packet only on an explicit action, keeps an empty/short packet honest, and retries preparation safely", async () => {
    packet = null;
    failures["review/prepare"] = 409;
    const user = userEvent.setup();
    render(<CandidateReview />);
    expect(
      await screen.findByText("Choose a small set to review."),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path === "review/prepare")).toBe(false);
    await user.click(
      screen.getByRole("button", { name: "Prepare up to 10 candidates" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("another tab");
    delete failures["review/prepare"];
    packet = candidates(2);
    await user.click(
      screen.getByRole("button", { name: "Prepare up to 10 candidates" }),
    );
    expect(
      screen.getByRole("heading", { name: "2 candidates · 0 labelled" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(2);
    const attempts = calls.filter((call) => call.path === "review/prepare");
    expect(attempts[0]!.body.request_id).toBe(attempts[1]!.body.request_id);
    expect(window.location.search).toBe(`?packet=${PACKET_ID}`);
  });
  it("does not substitute a different or foreign review after a failed lookup", async () => {
    failures.review = 404;
    window.history.replaceState(
      null,
      "",
      `/workspace/review?packet=review-${"b".repeat(32)}`,
    );
    render(<CandidateReview />);
    expect(
      await screen.findByText(/unavailable in this account/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(calls.find((call) => call.path === "review")!.body).toEqual({});
  });
  it("switches explicitly between retained packets without creating or relabelling either set", async () => {
    const user = userEvent.setup();
    const earlier = { ...candidates(1), id: `review-${"b".repeat(32)}` };
    earlier.items[0]!.work.title = "Earlier frozen source";
    packetHistory = [packet!, earlier];
    render(<CandidateReview />);
    await user.selectOptions(
      await screen.findByLabelText("Saved candidate set"),
      earlier.id,
    );
    expect(
      await screen.findByRole("article", { name: "Earlier frozen source" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "1 candidates · 0 labelled" }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe(`?packet=${earlier.id}`);
    expect(calls.every((call) => ["context/state", "review"].includes(call.path))).toBe(
      true,
    );
    expect(
      screen
        .getAllByRole("radio")
        .every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
  });
  it("does not fill an empty stored packet and reports failed reloads while keeping the last saved review", async () => {
    packet = candidates(0);
    const user = userEvent.setup();
    render(<CandidateReview />);
    expect(
      await screen.findByRole("heading", {
        name: "No eligible stored candidates.",
      }),
    ).toBeInTheDocument();
    failures.review = 503;
    await user.click(
      screen.getByRole("button", { name: "Reload saved review" }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "could not complete this request",
    );
    expect(
      screen.getByRole("heading", { name: "No eligible stored candidates." }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.path === "review/feedback")).toBe(false);
  });
  it("leaves an unavailable review unavailable and can reload after the service recovers", async () => {
    failures.review = 503;
    const user = userEvent.setup();
    render(<CandidateReview />);
    expect(
      await screen.findByText(/The workspace could not complete this request/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    delete failures.review;
    await user.click(
      screen.getByRole("button", { name: "Reload saved review" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "10 candidates · 0 labelled",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved review reloaded",
    );
  });
  it("can explicitly prepare after a failed read and makes another set only on a new action", async () => {
    failures.review = 503;
    const user = userEvent.setup();
    render(<CandidateReview />);
    await screen.findByText(/The workspace could not complete this request/);
    delete failures.review;
    await user.click(
      screen.getByRole("button", { name: "Prepare up to 10 candidates" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "10 candidates · 0 labelled",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Prepare another candidate set" }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Candidate set prepared from stored metadata",
    );
    const requests = calls.filter((call) => call.path === "review/prepare");
    expect(requests).toHaveLength(2);
    expect(requests[0]!.body.request_id).not.toBe(requests[1]!.body.request_id);
    expect(
      screen
        .getAllByRole("radio")
        .every((radio) => !(radio as HTMLInputElement).checked),
    ).toBe(true);
  });
  it("prevents a pending initial read from racing with preparation and replacing its result", async () => {
    const original = fetch;
    let release: (value: Response) => void = () => {
      throw new Error("request not pending");
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        if (new URL(url, "http://localhost").pathname.endsWith("/review"))
          return new Promise<Response>((resolve) => {
            release = resolve;
          });
        return original(url, init);
      }),
    );
    render(<CandidateReview />);
    await screen.findByRole("heading", { level: 1 });
    expect(
      screen.getByRole("button", { name: "Prepare up to 10 candidates" }),
    ).toBeDisabled();
    expect(
      screen.getByText("Opening the saved candidate set…"),
    ).toBeInTheDocument();
    await act(async () =>
      release(Response.json({ packet, packet_ids: [packet!.id] })),
    );
    expect(
      screen.getByRole("button", { name: "Prepare another candidate set" }),
    ).toBeEnabled();
    expect(calls.some((call) => call.path === "review/prepare")).toBe(false);
  });
});
