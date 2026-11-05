import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import ProjectSelector from "@/components/workspace/ProjectSelector";
import LearningThreadList from "@/components/workspace/LearningThreadList";
import { ContextUnavailable } from "@/components/workspace/ContextUnavailable";
import { invalidateContextIndex, useContextIndex } from "@/lib/workspace/useContextIndex";
import { blockWorkspaceNavigation } from "@/lib/workspace/navigationGuard";
import type { ContextIndex } from "@/lib/workspace/api";
const router = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
const id = `project-${"a".repeat(32)}`, thread = `thread-${"b".repeat(32)}`;
let index: ContextIndex;
beforeEach(() => {
  router.push.mockReset(); history.replaceState(null, "", "/workspace/today?mode=research");
  index = { principal_key_id: "owner", preferences: { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } }, projects: [], threads: [] };
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(index)));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("real context sidebar surfaces", () => {
  it("loads projects, preserves focus and hash, removes thread/cursor, and respects navigation veto", async () => {
    index.projects = [{ id, revision: 1, data: { title: "Archived study", question: "Why?", scope: "", constraints: "", next_actions: [], status: "archived" }, created_at: "now", updated_at: "now", activity_sequence: 1 }];
    history.replaceState(null, "", `/workspace/today?mode=research&thread=${thread}&cursor=old&focus=paper#source`);
    render(<ProjectSelector />);
    expect(screen.getByRole("combobox")).toBeDisabled();
    await screen.findByRole("option", { name: "Archived study (archived)" });
    const blocked = vi.fn(), release = blockWorkspaceNavigation(blocked);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: id } });
    expect(blocked).toHaveBeenCalledOnce(); expect(router.push).not.toHaveBeenCalled(); release();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: id } });
    const href = router.push.mock.calls[0]![0] as string;
    expect(href).toContain(`project=${id}`); expect(href).toContain("focus=paper"); expect(href).toContain("#source"); expect(href).not.toMatch(/thread=|cursor=/);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "" } });
    expect(router.push.mock.calls[1]![0]).not.toContain("project=");
  });
  it("shows unavailable projects and retries a failed index without a write", async () => {
    history.replaceState(null, "", `/workspace/today?mode=research&project=${id}`);
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 503 }));
    render(<ProjectSelector />); await screen.findByRole("button", { name: "Retry projects" });
    expect(screen.getByRole("option", { name: "Unavailable project" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry projects" }));
    await waitFor(() => expect(screen.getByRole("combobox")).toBeEnabled());
    expect(screen.getByRole("link", { name: "Create or select a project" })).toHaveAttribute("href", expect.stringContaining(`project=${id}`));
    expect(vi.mocked(fetch).mock.calls.every(([, init]) => !init?.body)).toBe(true);
  });
  it("offers the selected project's workspace", async () => {
    index.projects = [{ id, revision: 1, data: { title: "Study", question: "Why?", scope: "", constraints: "", next_actions: [], status: "active" }, created_at: "now", updated_at: "now", activity_sequence: 1 }];
    history.replaceState(null, "", `/workspace/today?project=${id}`); render(<ProjectSelector />);
    expect(await screen.findByRole("link", { name: "Open project workspace" })).toHaveAttribute("title", "Open project question and details");
  });
  it.each(["select_or_create_project", "project_archived", "unknown"])("explains %s without substituting a context", reason => {
    render(<ContextUnavailable reason={reason} context={{ mode: "research", project: id, thread, explicit: true, invalid: false }} />);
    expect(screen.getByRole("heading")).toHaveTextContent(reason === "select_or_create_project" ? "Choose a research project." : "This context is unavailable.");
    expect(screen.getByRole("link", { name: /Create or select/ }).getAttribute("href")).toBe("/workspace/projects?mode=research");
    expect(screen.getByRole("link", { name: /Open shared Library/ })).toHaveAttribute("href", expect.stringContaining(`thread=${thread}`));
  });
  it("shows empty threads, and refuses a different account's index", async () => {
    const view = render(<LearningThreadList owner="owner" />); expect(screen.getByText(/Loading your saved/)).toHaveAttribute("aria-busy", "true");
    await screen.findByText(/No saved learning threads/); view.rerender(<LearningThreadList owner="other" />);
    expect(screen.getByRole("alert")).toHaveTextContent("different local account");
  });
  it("retries thread loading and links both project and source origins", async () => {
    index.threads = [null, id].map((project, i) => ({ id: `thread-${String(i).repeat(32)}`, revision: 1, data: { title: `Thread ${i}`, goal: "Learn", prerequisite: "", status: "active", origin: { mode: "learn", project_id: project, thread_id: null, return_to: "/workspace/today" }, source: null, entry: null }, source: null, created_at: "now", updated_at: "now", activity_sequence: i }));
    vi.mocked(fetch).mockResolvedValueOnce(new Response(null, { status: 503 })); render(<LearningThreadList owner="owner" />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry learning threads" }));
    expect(await screen.findByRole("link", { name: "Thread 0" })).toHaveAttribute("href", expect.stringContaining("mode=learn"));
    expect(screen.getByText(/source-linked/)).toBeInTheDocument(); expect(screen.getByText(/project-linked/)).toBeInTheDocument();
  });
  it("rejects stale success/failure and unmounted reloads while accepting a fresh invalidation", async () => {
    const pending: { resolve: (r: Response) => void; reject: (e: Error) => void }[] = [];
    vi.mocked(fetch).mockImplementation(() => new Promise((resolve, reject) => pending.push({ resolve, reject })));
    const view = renderHook(() => useContextIndex());
    act(() => invalidateContextIndex());
    await act(async () => pending[1]!.resolve(Response.json(index)));
    await act(async () => pending[0]!.reject(new Error("stale initial")));
    expect(view.result.current.error).toBe(""); expect(view.result.current.index?.principal_key_id).toBe("owner");
    let old!: Promise<unknown>, fresh!: Promise<unknown>;
    act(() => { old = view.result.current.reload(); fresh = view.result.current.reload(); });
    await act(async () => { pending[2]!.resolve(Response.json({ ...index, principal_key_id: "stale" })); await old; });
    await act(async () => { pending[3]!.reject(new Error("current failure")); await fresh; });
    expect(view.result.current.error).toContain("local workspace is unavailable"); expect(view.result.current.index?.principal_key_id).toBe("owner");
    act(() => { old = view.result.current.reload(); }); view.unmount();
    await act(async () => { pending[4]!.reject(new Error("unmounted")); await old; });
  });
});
