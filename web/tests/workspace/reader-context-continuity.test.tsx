import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveReader } from "@/components/workspace/Reader";
import { storeDraft } from "@/lib/workspace/drafts";
import { WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";
import { workspace, work } from "./fixtures";
import { MAT, retained, available } from "./materialFixtures";
import type { WorkspaceState } from "@/lib/workspace/api";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(location.search) }));
const project = `project-${"a".repeat(32)}`;
const item = work(), version = item.versions[0]!.version_id;
function snapshot(mode: "learn" | "research"): WorkspaceState {
  return { ...workspace(), works: [work()], context: { mode, project_id: mode === "research" ? project : null, thread_id: null, project_revision: mode === "research" ? 1 : null, policy_version: "continuity-test", unavailable_reason: null }, active_edition: null };
}
beforeEach(() => {
  sessionStorage.clear(); history.replaceState(null, "", `/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(version)}&mode=learn#notes`);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
describe("one exact Reader editor across product context reads", () => {
  it("retries failed context loading without losing the current exact source or author draft", async () => {
    let fail = true;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("mode=research") && fail ? new Response(null, { status: 503 }) : Response.json(snapshot(url.includes("mode=research") ? "research" : "learn"))));
    render(<LiveReader id={item.work_id} />);
    const editor = await screen.findByRole("textbox", { name: "Your question" });
    fireEvent.change(editor, { target: { value: "Keep my question through a context failure" } });
    act(() => { history.pushState(null, "", `${location.pathname}?version=${encodeURIComponent(version)}&mode=research&project=${project}#notes`); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
    const retry = await screen.findByRole("button", { name: "Retry selected context" });
    expect(editor).toHaveValue("Keep my question through a context failure"); expect(screen.getByRole("button", { name: "Save question" })).toBeDisabled();
    fail = false; fireEvent.click(retry);
    await waitFor(() => expect(screen.getByRole("button", { name: "Save question" })).toBeEnabled());
    expect(screen.getByRole("textbox", { name: "Your question" })).toBe(editor);
  });
  it("opens the real exact-source tools lazily and refreshes their bound context only explicitly", async () => {
    const owner = workspace().principal_key_id;
    vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(url.endsWith("/context") ? { principal_key_id: owner, preferences: { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } }, projects: [], threads: [] } : snapshot("learn"))));
    render(<LiveReader id={item.work_id} />);
    await screen.findByRole("textbox", { name: "Your question" });
    const disclosure = screen.getByText("Investigate this · learning and project links").closest("details")!;
    act(() => { disclosure.open = true; disclosure.dispatchEvent(new Event("toggle")); });
    await screen.findByLabelText("Project for this source");
    expect(screen.getByRole("button", { name: "Attach source to project" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Use current viewed source context" }));
    await screen.findByLabelText("Project for this source");
    fireEvent.click(screen.getByRole("button", { name: "Learn this prerequisite" }));
    expect(await screen.findByLabelText("Thread title")).toHaveValue("");
  });

  it("carries the exact retained-material identity into evidence links without converting it to abstract scope", async () => {
    const state = snapshot("research"), current = state.works[0]!, document = { ...retained(), work_id: current.work_id, version_id: version };
    const material = available({ version_id: version });
    Object.assign(current.versions[0]!, { retained_materials: [material] });
    const projectDetail = { id: project, revision: 1, data: { title: "Exact material project", question: "What does this passage say?", scope: "", constraints: "", next_actions: [], status: "active" }, sources: [], entries: [], artifacts: [], threads: [] };
    const writes: Record<string, unknown>[] = [];
    history.replaceState(null, "", `${location.pathname}?version=${encodeURIComponent(version)}&mode=research&project=${project}#material:${MAT}:page:7:10:20`);
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.body) { writes.push(JSON.parse(String(init.body))); return Response.json({ ...projectDetail, revision: 2 }); }
      if (url.includes("/materials/")) return Response.json(document);
      if (url.endsWith("/context")) return Response.json({ principal_key_id: state.principal_key_id, preferences: { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } }, projects: [projectDetail], threads: [] });
      return Response.json(state);
    }));
    render(<LiveReader id={current.work_id} />);
    await screen.findByRole("textbox", { name: "Your question" });
    const disclosure = screen.getByText("Investigate this · learning and project links").closest("details")!;
    act(() => { disclosure.open = true; disclosure.dispatchEvent(new Event("toggle")); });
    fireEvent.change(await screen.findByLabelText("Link role"), { target: { value: "evidence" } });
    fireEvent.click(screen.getByRole("button", { name: "Attach source to project" }));
    await screen.findByText(/Exact source link saved/);
    expect(writes).toHaveLength(1);
    expect(writes[0]).toMatchObject({ role: "evidence", reference: { work_id: current.work_id, version_id: version, material_id: MAT, source_scope: "excerpt", anchor: `material:${MAT}:page:7:10:20` } });
  });

  it.each([false, true])("preserves the mounted textarea, text and anchor with storageUnavailable=%s", async unavailable => {
    const owner = workspace().principal_key_id;
    storeDraft(owner, item.work_id, version, { id: "current-draft", revision: 0, kind: "question", body: "Initial private draft", anchor: "abstract:4:13" });
    let release!: (response: Response) => void, held = true;
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") { posts.push(url); throw new Error("No write authorized in continuity test"); }
      if (url.includes("mode=research") && held) return new Promise<Response>(resolve => { release = resolve; });
      return Promise.resolve(Response.json(snapshot(url.includes("mode=research") ? "research" : "learn")));
    }));
    const view = render(<LiveReader id={item.work_id} />);
    const editor = await screen.findByRole("textbox", { name: "Your question" });
    if (unavailable) {
      vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("disabled"); });
      vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("disabled"); });
    }
    fireEvent.change(editor, { target: { value: "Keep this θ question and its exact selected passage" } });
    act(() => { history.pushState(null, "", `${location.pathname}?version=${encodeURIComponent(version)}&mode=research&project=${project}#notes`); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
    await screen.findByText(/Loading the selected context/);
    expect(screen.getByRole("textbox", { name: "Your question" })).toBe(editor);
    expect(editor).toHaveValue("Keep this θ question and its exact selected passage");
    expect(screen.getByText("Anchor: abstract:4:13")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save question" })).toBeDisabled();
    await act(async () => { held = false; release(Response.json(snapshot("research"))); });
    await waitFor(() => expect(screen.getByRole("button", { name: "Save question" })).toBeEnabled());
    expect(screen.getByRole("textbox", { name: "Your question" })).toBe(editor);
    expect(editor).toHaveValue("Keep this θ question and its exact selected passage");
    view.unmount(); render(<LiveReader id={item.work_id} />);
    expect(await screen.findByRole("textbox", { name: "Your question" })).toHaveValue("Keep this θ question and its exact selected passage");
    expect(screen.getByText("Anchor: abstract:4:13")).toBeInTheDocument(); expect(posts).toEqual([]);
  });
});
