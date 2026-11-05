import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CandidateReview } from "@/components/workspace/CandidateReview";
import { WorkspaceShell } from "@/components/workspace/Shell";
import type { ReviewPacket, UsefulnessFeedback } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/review", useSearchParams: () => new URLSearchParams(location.search) }));
const packetId = `review-${"a".repeat(32)}`;
const otherId = `review-${"b".repeat(32)}`;
let packet: ReviewPacket;
let calls: { path: string; body: Record<string, unknown> }[];
let failSave: boolean;
let holdSave: boolean;
let release: (response: Response) => void;
function fixture(): ReviewPacket {
  return { id: packetId, created_at: "2026-11-02T15:00:00Z", as_of: "2026-11-02T15:00:00Z", profile_revision: 1,
    policy_version: "workspace-lexical-v2", selection: "Four stored versions at a fixed cutoff.", limitations: ["Owner labels start blank."], coverage: workspace().sources, labelled_count: 0,
    items: [1, 2, 3, 4].map((n) => ({ work: work({ work_id: `candidate-${n}`, version_id: `candidate-${n}:v1`, title: `Frozen source ${n}`, versions: [], entries: [] }), matching_reason: ["Declared retrieval terms."], evidence_scope: "abstract", estimated_minutes: 5,
      feedback: { revision: 0, label: null, reason: "", updated_at: "" } })) };
}
beforeEach(() => {
  packet = fixture(); calls = []; failSave = false; holdSave = false; release = () => { throw new Error("No pending save"); };
  sessionStorage.clear(); localStorage.clear(); history.replaceState(null, "", `/workspace/review?packet=${packetId}`);
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    calls.push({ path, body });
    if (path === "context/state") return Response.json(workspace());
    if (path === "review") return Response.json({ packet, packet_ids: [packetId, otherId] });
    if (path === "review/prepare") return Response.json(packet);
    if (path === "review/feedback") {
      if (holdSave) return new Promise<Response>((resolve) => { release = resolve; });
      if (failSave) return new Response(null, { status: 409 });
      const feedback = { revision: Number(body.revision) + 1, label: body.label, reason: body.reason, updated_at: "2026-11-02T16:00:00Z" };
      return Response.json(feedback);
    }
    throw new Error(`Unexpected request ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function mount() { render(<WorkspaceShell><CandidateReview /></WorkspaceShell>); await screen.findByRole("heading", { name: "4 candidates · 0 labelled" }); }
function candidate(n: number) { return screen.getByRole("article", { name: `Frozen source ${n}` }); }

describe("Review controller", () => {
  it("vetoes ordinary and slash navigation for dirty judgments without changing the query, labels or reason", async () => {
    const user = userEvent.setup(); await mount(); const reason = within(candidate(1)).getByRole("textbox"); await user.type(reason, "Keep this unsaved judgment reason");
    const assign = vi.fn(); vi.stubGlobal("location", { ...window.location, assign }); const search = await screen.findByRole("searchbox");
    for (const query of ["review query", "/radar"]) { fireEvent.change(search, { target: { value: query } }); fireEvent.submit(search.closest("form")!); expect(search).toHaveValue(query); }
    expect(assign).not.toHaveBeenCalled(); expect(reason).toHaveValue("Keep this unsaved judgment reason");
    expect(screen.getByRole("status")).toHaveTextContent("Save or discard your unsaved judgments");
    expect(within(candidate(1)).getAllByRole("radio").every(radio => !(radio as HTMLInputElement).checked)).toBe(true);
    expect(calls.filter(call => call.path === "review/feedback")).toHaveLength(0);
  });
  it("keeps an unsaved judgment when browser history selects another packet", async () => {
    const user = userEvent.setup();
    const view = render(<WorkspaceShell><CandidateReview /></WorkspaceShell>);
    await screen.findByRole("heading", { name: "4 candidates · 0 labelled" });
    await user.type(within(candidate(1)).getByRole("textbox"), "Keep my judgment");
    act(() => { history.pushState(null, "", `/workspace/review?packet=${otherId}`); view.rerender(<WorkspaceShell><CandidateReview /></WorkspaceShell>); });
    await waitFor(() => expect(location.search).toBe(`?packet=${packetId}`));
    expect(within(candidate(1)).getByRole("textbox")).toHaveValue("Keep my judgment");
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes(otherId))).toBe(false);
    expect(screen.getByRole("status")).toHaveTextContent("Save or explicitly discard");
  });
  it("clears a saved usefulness label only after server acknowledgement", async () => {
    packet.items[0]!.feedback = { revision: 2, label: "useful", reason: "Prior judgment", updated_at: "2026-11-02T16:00:00Z" };
    packet.labelled_count = 1;
    const user = userEvent.setup(); render(<WorkspaceShell><CandidateReview /></WorkspaceShell>);
    await screen.findByRole("heading", { name: "4 candidates · 1 labelled" });
    await user.click(within(candidate(1)).getByRole("button", { name: "Clear this label" }));
    expect(screen.getByRole("heading", { name: "4 candidates · 1 labelled" })).toBeInTheDocument();
    await user.click(within(candidate(1)).getByRole("button", { name: "Save judgment for candidate 1" }));
    await screen.findByRole("heading", { name: "4 candidates · 0 labelled" });
    expect(calls.find((call) => call.path === "review/feedback")?.body).toMatchObject({ revision: 2, label: null, reason: "" });
  });
  it.each(["failure", "success"])("ignores an older initial read that ends in %s after reload and an edit", async (result) => {
    const originalFetch = vi.mocked(fetch).getMockImplementation();
    if (!originalFetch) throw new Error("Missing workspace fetch mock");
    let finishInitial: ((response: Response) => void) | undefined;
    let reads = 0;
    vi.mocked(fetch).mockImplementation((url, init) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path === "/api/workspace/review" && reads++ === 0) {
        return new Promise<Response>((resolve) => { finishInitial = resolve; });
      }
      return originalFetch(url, init);
    });
    const user = userEvent.setup();
    render(<WorkspaceShell><CandidateReview /></WorkspaceShell>);
    await screen.findByRole("button", { name: "Reload saved review" });
    await user.click(screen.getByRole("button", { name: "Reload saved review" }));
    await screen.findByRole("heading", { name: "4 candidates · 0 labelled" });
    const reason = within(candidate(1)).getByRole("textbox");
    await user.type(reason, "Keep this judgment");
    const stale = fixture(); stale.items[0]!.work.title = "Stale candidate";
    if (!finishInitial) throw new Error("Initial review read was not started");
    const finish = finishInitial;
    await act(async () => finish(result === "failure" ? new Response(null, { status: 503 }) : Response.json({ packet: stale, packet_ids: [packetId] })));
    expect(within(candidate(1)).getByRole("textbox")).toHaveValue("Keep this judgment");
    expect(screen.getByText("1 unsaved judgment")).toBeInTheDocument();
    expect(screen.queryByText("Stale candidate")).not.toBeInTheDocument();
  });
  it("keeps all four forms mounted in order while queue and keyboard navigate, retaining each unsaved draft", async () => {
    const user = userEvent.setup(); await mount();
    const articles = screen.getAllByRole("article"); expect(articles).toHaveLength(4); expect(articles.flatMap((article) => within(article).getAllByRole("radio"))).toHaveLength(12);
    expect(articles.map((article) => within(article).getByRole("heading").textContent)).toEqual([1, 2, 3, 4].map((n) => `Frozen source ${n}`));
    fireEvent.keyDown(document.body, { key: "1" });
    expect(within(candidate(1)).getByRole("radio", { name: "Useful" })).toBeChecked();
    await user.type(within(candidate(1)).getByRole("textbox"), "My first unsaved reason");
    await user.click(screen.getByRole("button", { name: "Show candidate 3 of 4: Frozen source 3" }));
    fireEvent.keyDown(document.body, { key: "2" });
    expect(candidate(3)).toHaveAttribute("aria-current", "true");
    expect(within(candidate(3)).getByRole("radio", { name: "Maybe" })).toBeChecked();
    fireEvent.keyDown(document.body, { key: "k" }); expect(candidate(2)).toHaveAttribute("aria-current", "true");
    fireEvent.keyDown(document.body, { key: "j" }); expect(candidate(3)).toHaveAttribute("aria-current", "true");
    expect(screen.getAllByRole("article")).toEqual(articles);
    expect(within(candidate(1)).getByRole("textbox")).toHaveValue("My first unsaved reason");
    expect(screen.getByText("2 unsaved judgments")).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "review/feedback")).toHaveLength(0);
    expect(history.state).toBeNull(); expect(location.search).toBe(`?packet=${packetId}`);
  });

  it("guards number keys in fields and native Enter, and only assigns commands to the current radios", async () => {
    const user = userEvent.setup(); await mount();
    const first = candidate(1); const reason = within(first).getByRole("textbox");
    await user.click(reason); await user.keyboard("123jk");
    expect(reason).toHaveValue("123jk"); expect(screen.getAllByRole("article").flatMap((article) => within(article).getAllByRole("radio")).some((radio) => (radio as HTMLInputElement).checked)).toBe(false);
    expect(document.querySelectorAll('[data-command^="label-"]')).toHaveLength(3);
    await user.click(within(first).getByRole("radio", { name: "Useful" }));
    const save = within(first).getByRole("button", { name: "Save judgment for candidate 1" }); save.focus(); await user.keyboard("{Enter}");
    expect(calls.filter((call) => call.path === "review/feedback")).toHaveLength(1);
    expect(candidate(1)).toHaveAttribute("aria-current", "true");
    expect(calls.at(-1)?.body).toMatchObject({ packet_id: packetId, work_id: "candidate-1", version_id: "candidate-1:v1", revision: 0, label: "useful", reason: "123jk" });
    const link = within(first).getByRole("link", { name: "Inspect retained source →" });
    const href = new URL(link.getAttribute("href")!, location.origin);
    expect(href.searchParams.get("return_to")).toBe(`/workspace/review?packet=${packetId}`);
    expect(href.searchParams.get("version")).toBe("candidate-1:v1"); expect(href.hash).toBe("#abstract%3A0");
  });

  it("requires explicit discard before packet preparation or switching and preserves the saved labels", async () => {
    const user = userEvent.setup(); await mount();
    await user.type(within(candidate(2)).getByRole("textbox"), "Reason-only draft is still a draft");
    expect(screen.getByRole("button", { name: "Prepare another candidate set" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Saved candidate set" })).toBeDisabled();
    expect(screen.getByText(/Save or explicitly discard your unsaved judgments/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard unsaved judgments" }));
    expect(within(candidate(2)).getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Prepare another candidate set" })).toBeEnabled();
    expect(screen.getByRole("combobox", { name: "Saved candidate set" })).toBeEnabled();
    expect(calls.filter((call) => call.path === "review/feedback")).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "4 candidates · 0 labelled" })).toBeInTheDocument();
  });

  it("locks a pending save against editor loss and freezes packet controls until acknowledgement", async () => {
    const user = userEvent.setup(); await mount(); holdSave = true;
    const first = candidate(1); await user.click(within(first).getByRole("radio", { name: "Irrelevant" }));
    const reason = within(first).getByRole("textbox"); await user.type(reason, "Owned reason");
    await user.click(within(first).getByRole("button", { name: "Save judgment for candidate 1" }));
    expect(reason).toBeDisabled(); expect(within(first).getByRole("radio", { name: "Useful" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next candidate" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reload saved review" })).toBeDisabled();
    await user.type(reason, " accidental edit"); expect(reason).toHaveValue("Owned reason");
    expect(screen.getByRole("heading", { name: "4 candidates · 0 labelled" })).toBeInTheDocument();
    const feedback: UsefulnessFeedback = { revision: 1, label: "irrelevant", reason: "Owned reason", updated_at: "2026-11-02T16:00:00Z" };
    await act(async () => release(Response.json(feedback)));
    expect(reason).toBeEnabled(); expect(reason).toHaveValue("Owned reason");
    expect(screen.getByText("No unsaved judgments")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "4 candidates · 1 labelled" })).toBeInTheDocument();
  });

  it("retains failed and conflicting drafts across reload and retries the same write id", async () => {
    const user = userEvent.setup(); await mount(); failSave = true;
    const first = candidate(1); await user.click(within(first).getByRole("radio", { name: "Maybe" }));
    await user.type(within(first).getByRole("textbox"), "My judgment");
    const save = within(first).getByRole("button", { name: "Save judgment for candidate 1" });
    await user.click(save); await user.click(save);
    const writes = calls.filter((call) => call.path === "review/feedback"); expect(writes[0]!.body.request_id).toBe(writes[1]!.body.request_id);
    packet.items[0]!.feedback = { revision: 2, label: "useful", reason: "Other tab", updated_at: "2026-11-02T17:00:00Z" }; packet.labelled_count = 1;
    await user.click(screen.getByRole("button", { name: "Reload saved review" }));
    expect(within(first).getByRole("textbox")).toHaveValue("My judgment");
    await waitFor(() => expect(within(first).getByRole("button", { name: "Discard draft and load saved judgment" })).toBeEnabled());
    await user.click(within(first).getByRole("button", { name: "Discard draft and load saved judgment" }));
    expect(within(first).getByRole("textbox")).toHaveValue("Other tab");
    expect(within(first).getByRole("radio", { name: "Useful" })).toBeChecked();
    expect(screen.getByText("No unsaved judgments")).toBeInTheDocument();
  });
  it("keeps the current packet and draft when reload returns a different packet", async () => {
    const user = userEvent.setup(); await mount();
    await user.type(within(candidate(1)).getByRole("textbox"), "Keep my judgment");
    packet = { ...fixture(), id: otherId };
    await user.click(screen.getByRole("button", { name: "Reload saved review" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("requested candidate set was not returned"));
    expect(within(candidate(1)).getByRole("textbox")).toHaveValue("Keep my judgment");
    expect(screen.getByText("1 unsaved judgment")).toBeInTheDocument();
  });
  it("closes the mobile drawer after choosing a candidate without discarding drafts", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null, addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); await mount();
    await user.type(within(candidate(1)).getByRole("textbox"), "Keep my judgment");
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(screen.getByRole("button", { name: "Show candidate 3 of 4: Frozen source 3" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(candidate(3)).toHaveAttribute("aria-current", "true");
    expect(within(candidate(1)).getByRole("textbox")).toHaveValue("Keep my judgment");
  });
  it("blocks leaving after saving one of two drafts until every remaining judgment is saved or explicitly discarded", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(within(candidate(1)).getByRole("radio", { name: "Useful" }));
    await user.type(within(candidate(2)).getByRole("textbox"), "Another unsaved owner judgment");
    await user.click(within(candidate(1)).getByRole("button", { name: "Save judgment for candidate 1" }));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("label is saved on the server");
      expect(screen.getByText("1 unsaved judgment")).toBeInTheDocument();
    });
    const source = within(candidate(1)).getByRole("link", { name: "Inspect retained source →" });
    await user.click(source);
    expect(screen.getByRole("status")).toHaveTextContent("Save or discard your unsaved judgments before leaving this review");
    expect(within(candidate(2)).getByRole("textbox")).toHaveValue("Another unsaved owner judgment");
    expect(calls.filter((call) => call.path === "review/feedback")).toHaveLength(1);
    const unload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(unload); expect(unload.defaultPrevented).toBe(true);
    const newTab = vi.fn((event: Event) => { expect(event.defaultPrevented).toBe(false); event.preventDefault(); });
    source.addEventListener("click", newTab, { once: true });
    fireEvent.click(source, { ctrlKey: true }); expect(newTab).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Discard unsaved judgments" }));
    expect(screen.getByText("No unsaved judgments")).toBeInTheDocument();
    const leaving = vi.fn((event: Event) => { expect(event.defaultPrevented).toBe(false); event.preventDefault(); });
    const restoredSource = within(candidate(1)).getByRole("link", { name: "Inspect retained source →" });
    restoredSource.addEventListener("click", leaving, { once: true });
    await user.click(restoredSource); expect(leaving).toHaveBeenCalledOnce();
    const safeUnload = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(safeUnload); expect(safeUnload.defaultPrevented).toBe(false);
    expect(calls.filter((call) => call.path === "review/feedback")).toHaveLength(1);
  });

});
