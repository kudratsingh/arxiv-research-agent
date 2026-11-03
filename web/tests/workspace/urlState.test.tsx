import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { serverQueryParam, setQueryParam, useQueryParam, WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";

afterEach(() => { vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

describe("workspace URL selection store", () => {
  it("has a stable server snapshot and preserves unrelated URL and history state", () => {
    expect(serverQueryParam()).toBeNull();
    const routerState = { __NA: true, tree: ["preserved"] };
    window.history.replaceState(routerState, "", "/workspace/today?q=term#notes");
    const replace = vi.spyOn(window.history, "replaceState");
    const listener = vi.fn();
    window.addEventListener(WORKSPACE_URL_EVENT, listener);
    const { result, unmount } = renderHook(() => useQueryParam("focus"));
    expect(result.current).toBeNull();
    act(() => setQueryParam("focus", "arxiv:1 & 2"));
    expect(result.current).toBe("arxiv:1 & 2");
    expect(window.location.search).toBe("?q=term&focus=arxiv%3A1+%26+2");
    expect(window.location.hash).toBe("#notes");
    expect(window.history.state).toEqual(routerState);
    expect(replace).toHaveBeenCalledOnce();
    expect(listener).toHaveBeenCalledOnce();
    act(() => setQueryParam("focus", null));
    expect(result.current).toBeNull();
    expect(window.location.search).toBe("?q=term");
    unmount();
    window.removeEventListener(WORKSPACE_URL_EVENT, listener);
  });
  it("supports explicit push, popstate, parameter changes, and unsubscribes on unmount", () => {
    window.history.replaceState(null, "", "/workspace/library?view=notes");
    const push = vi.spyOn(window.history, "pushState");
    const remove = vi.spyOn(window, "removeEventListener");
    const { result, rerender, unmount } = renderHook(({ name }) => useQueryParam(name), { initialProps: { name: "focus" } });
    act(() => setQueryParam("focus", "a", "push"));
    expect(push).toHaveBeenCalledOnce();
    expect(result.current).toBe("a");
    act(() => {
      window.history.replaceState(null, "", "/workspace/library?view=saved&focus=b");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(result.current).toBe("b");
    rerender({ name: "view" });
    expect(result.current).toBe("saved");
    act(() => setQueryParam("view", "", "replace"));
    expect(result.current).toBe("");
    unmount();
    expect(remove).toHaveBeenCalledWith("popstate", expect.any(Function));
    expect(remove).toHaveBeenCalledWith(WORKSPACE_URL_EVENT, expect.any(Function));
  });
});
