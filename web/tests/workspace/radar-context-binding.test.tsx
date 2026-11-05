import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveRadar } from "@/components/workspace/Radar";
import { WORKSPACE_URL_EVENT } from "@/lib/workspace/urlState";
import { work, workspace } from "./fixtures";
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(location.search) }));
const firstProject = `project-${"a".repeat(32)}`, secondProject = `project-${"b".repeat(32)}`;
beforeEach(() => { sessionStorage.clear(); history.replaceState(null, "", `/workspace/radar?mode=research&project=${firstProject}&days=0&cursor=old-project-cursor&as_of=2026-11-01T00%3A00%3A00Z`); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe("Radar applied-page context binding", () => {
  it.each(["learn", "other-project"])("never sends an old project's cursor under %s and ignores its delayed response", async target => {
    const requests: URL[] = [];
    let release!: (response: Response) => void, oldCalls = 0;
    const oldItem = work({ title: "Old project candidate" }), newItem = work({ title: "New context candidate" });
    vi.stubGlobal("fetch", vi.fn((input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname.endsWith("/context/items")) {
        requests.push(url);
        if (url.searchParams.get("project") === firstProject) {
          if (++oldCalls > 1) return new Promise<Response>(resolve => { release = resolve; });
          return Promise.resolve(Response.json({ items: [oldItem], next_cursor: null, as_of: "2026-11-01T00:00:00Z" }));
        }
        return Promise.resolve(Response.json({ items: [newItem], next_cursor: null, as_of: "2026-11-05T00:00:00Z" }));
      }
      return Promise.resolve(Response.json(workspace()));
    }));
    const view = render(<LiveRadar />);
    await screen.findByRole("heading", { name: "Old project candidate", level: 3 });
    // A legitimate old-context query may still be outstanding when navigation occurs.
    act(() => { history.replaceState(null, "", `${location.pathname}${location.search}&q=old-query`); window.dispatchEvent(new Event(WORKSPACE_URL_EVENT)); });
    await waitFor(() => expect(release).toBeTypeOf("function"));
    const next = target === "learn" ? "/workspace/radar?mode=learn&days=0" : `/workspace/radar?mode=research&project=${secondProject}&days=0`;
    // Next can commit a same-route URL by rerendering, without the local URL event.
    act(() => { history.pushState(null, "", next); view.rerender(<LiveRadar />); });
    await screen.findByRole("heading", { name: "New context candidate", level: 3 });
    const newRequests = requests.filter(url => target === "learn" ? url.searchParams.get("mode") === "learn" : url.searchParams.get("project") === secondProject);
    expect(newRequests.length).toBeGreaterThan(0);
    for (const url of newRequests) {
      expect(url.searchParams.has("cursor")).toBe(false);
      expect(url.searchParams.has("as_of")).toBe(false);
      expect(url.searchParams.get("q") ?? "").toBe("");
    }
    await act(async () => release(Response.json({ items: [oldItem], next_cursor: null, as_of: "2026-11-01T00:00:00Z" })));
    expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("New context candidate");
    expect(new URLSearchParams(location.search).get("as_of")).toBe("2026-11-05T00:00:00Z");
  });
});
