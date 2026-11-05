import { afterEach, describe, expect, it, vi } from "vitest";
import { contextHref, changeContextHref, commitContextNavigation, parseProductContext } from "@/lib/workspace/productContext";
import { blockWorkspaceNavigation } from "@/lib/workspace/navigationGuard";
import { navigationState } from "@/lib/workspace/navigation";

const project = `project-${"a".repeat(32)}`;
const thread = `thread-${"b".repeat(32)}`;
afterEach(() => { navigationState.pending = null; vi.restoreAllMocks(); history.replaceState(null, "", "/"); });
describe("product context identity and navigation", () => {
  it("defaults without mutation and refuses malformed identifiers", () => {
    expect(parseProductContext(new URLSearchParams()).mode).toBe("learn");
    expect(parseProductContext(new URLSearchParams(), "research").mode).toBe("research");
    expect(parseProductContext(new URLSearchParams("mode=unknown&project=other&thread=bad"))).toMatchObject({ mode: "learn", project: null, thread: null, invalid: true });
  });
  it("carries exact version, entry, Unicode anchor and opaque list context", () => {
    const context = parseProductContext(new URLSearchParams({ mode: "research", project, thread }));
    const href = contextHref("/workspace/items/a?version=v1&entry=e&return_to=%2Fworkspace%2Fradar%3Fcursor%3Dopaque#abstract%3A17%3A22", context);
    const url = new URL(href, location.origin);
    expect(url.searchParams.get("version")).toBe("v1"); expect(url.searchParams.get("entry")).toBe("e");
    expect(url.searchParams.get("return_to")).toBe("/workspace/radar?cursor=opaque"); expect(url.hash).toBe("#abstract%3A17%3A22");
    expect(url.searchParams.get("project")).toBe(project);
    expect(contextHref("/workspace/today", parseProductContext(new URLSearchParams()))).toBe("/workspace/today");
    expect(contextHref("https://external.example/workspace/today", context)).toBe("https://external.example/workspace/today");
  });
  it("invalidates only snapshot pagination on deliberate context changes", () => {
    const href = changeContextHref(`/workspace/radar?mode=research&project=${project}&cursor=old&as_of=clock&q=agents&focus=a#source`, { mode: "learn", project: null, thread: null, explicit: true, invalid: false });
    const params = new URL(href, location.origin).searchParams;
    expect(params.get("q")).toBe("agents"); expect(params.get("focus")).toBe("a");
    expect(params.get("mode")).toBe("learn"); expect(params.has("project")).toBe(false); expect(params.has("cursor")).toBe(false); expect(params.has("as_of")).toBe(false);
  });
  it("vetoes a context change before intent, commit or history and permits later explicit retry", () => {
    history.replaceState({ workspaceScroll: 27 }, "", "/workspace/today?focus=a");
    const replace = vi.spyOn(history, "replaceState"), commit = vi.fn(), refused = vi.fn();
    const release = blockWorkspaceNavigation(refused);
    expect(commitContextNavigation("/workspace/projects?mode=research", commit)).toBe(false);
    expect(commit).not.toHaveBeenCalled(); expect(replace).not.toHaveBeenCalled(); expect(navigationState.pending).toBeNull(); expect(refused).toHaveBeenCalledOnce();
    release(); expect(commitContextNavigation("/workspace/projects?mode=research", commit)).toBe(true);
    expect(commit).toHaveBeenCalledOnce(); expect(navigationState.pending).toHaveLength(1);
  });
});
