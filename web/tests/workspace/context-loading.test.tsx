import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWorkspace } from "@/lib/workspace/useWorkspace";
import { WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";
import { workspace } from "./fixtures";
import type { WorkspaceState } from "@/lib/workspace/api";

const project = `project-${"a".repeat(32)}`;
function state(mode: "learn" | "research"): WorkspaceState { return { ...workspace(), context: { mode, project_id: mode === "research" ? project : null, thread_id: null, project_revision: mode === "research" ? 1 : null, policy_version: "test-v1", unavailable_reason: null }, active_edition: null }; }
beforeEach(() => { history.replaceState(null, "", "/workspace/today?mode=learn"); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("context request identity", () => {
  it("rejects a delayed old manual reload and old action callback after context changes", async () => {
    let release!: (value: Response) => void;
    let learns = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("mode=research")) return Promise.resolve(Response.json(state("research")));
      if (++learns === 1) return Promise.resolve(Response.json(state("learn")));
      return new Promise<Response>(resolve => { release = resolve; });
    }));
    const { result } = renderHook(() => useWorkspace());
    await waitFor(() => expect(result.current.state?.context?.mode).toBe("learn"));
    const staleSetState = result.current.setState;
    let reload!: Promise<void>;
    act(() => { reload = result.current.reload(); });
    act(() => { history.pushState(null, "", `/workspace/today?mode=research&project=${project}`); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
    await waitFor(() => expect(result.current.state?.context?.mode).toBe("research"));
    act(() => staleSetState(state("learn")));
    await act(async () => { release(Response.json(state("learn"))); await reload; });
    expect(result.current.state?.context?.mode).toBe("research"); expect(result.current.loading).toBe(false);
  });
  it("does not clear a new context's loading state when an old reload fails", async () => {
    let rejectOld!: (reason: Error) => void, releaseNew!: (response: Response) => void;
    let learns = 0;
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("mode=research")) return new Promise<Response>(resolve => { releaseNew = resolve; });
      return ++learns === 1 ? Promise.resolve(Response.json(state("learn"))) : new Promise<Response>((_, reject) => { rejectOld = reject; });
    }));
    const { result } = renderHook(() => useWorkspace());
    await waitFor(() => expect(result.current.state).not.toBeNull());
    let pending!: Promise<void>; act(() => { pending = result.current.reload(); });
    act(() => { history.pushState(null, "", `/workspace/today?mode=research&project=${project}`); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
    await act(async () => { rejectOld(new Error("old failure")); await pending; });
    expect(result.current.loading).toBe(true); expect(result.current.error).toBe(""); expect(result.current.state).toBeNull();
    await act(async () => { releaseNew(Response.json(state("research"))); });
    expect(result.current.state?.context?.mode).toBe("research");
  });
});
