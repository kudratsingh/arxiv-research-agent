import { afterEach, describe, expect, it, vi } from "vitest";
import { checkTodaySources, saveTodayProfile } from "@/lib/workspace/todayActions";
import { resolveWorkspaceCommand } from "@/lib/workspace/commandTargets";
import { workspace } from "./fixtures";

afterEach(() => { vi.unstubAllGlobals(); document.body.replaceChildren(); history.replaceState(null, "", "/"); });

describe("deferred Today actions", () => {
  it("retries the exact profile revision and request identity, then creates an edition only when requested", async () => {
    const calls: { path: string; body: unknown }[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ path: String(input), body: JSON.parse(String(init?.body)) });
      return calls.length === 1 ? new Response(null, { status: 503 }) : Response.json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const state = workspace(), pending = new Map<string, string>(), patch = { minutes: 45 as const };
    await expect(saveTodayProfile(state, patch, pending, true)).rejects.toThrow();
    expect(calls).toHaveLength(1);
    await saveTodayProfile(state, patch, pending, true);
    expect(calls).toHaveLength(3);
    expect(calls[0]).toEqual(calls[1]);
    expect(calls[1]).toEqual({ path: "/api/workspace/profile", body: {
      revision: state.profile.revision, data: { ...state.profile.data, minutes: 45 }, request_id: expect.any(String),
    } });
    expect(calls[2]).toEqual({ path: "/api/workspace/edition", body: {} });
    await saveTodayProfile(state, { pinned_entry_id: "entry-1" }, pending);
    expect(calls[3]).toEqual({ path: "/api/workspace/profile", body: {
      revision: state.profile.revision, data: { ...state.profile.data, pinned_entry_id: "entry-1" }, request_id: expect.any(String),
    } });
    expect((calls[3]!.body as { request_id: string }).request_id).not.toBe((calls[1]!.body as { request_id: string }).request_id);
    expect(calls).toHaveLength(4);
  });

  it("checks sources with an empty source selection and makes no model request", async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json({})); vi.stubGlobal("fetch", fetchMock);
    await checkTodaySources();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]![0]).toBe("/api/workspace/refresh");
    expect(JSON.parse(String((fetchMock.mock.calls[0]![1] as RequestInit).body))).toEqual({ source_ids: [] });
  });
});

describe("command targets follow the live controls", () => {
  it("resolves navigation in context, rejects hidden targets, and falls back only when the link is absent", () => {
    history.replaceState(null, "", "/workspace/today?mode=research");
    document.body.innerHTML = '<main class="workspace-app"><nav class="ws-navigation"><a data-workspace-route="/workspace/library" href="/workspace/library">Library</a></nav></main>';
    const link = document.querySelector("a")!;
    expect(resolveWorkspaceCommand("go-library")).toEqual({ element: link, action: "click" });
    link.hidden = true; expect(resolveWorkspaceCommand("go-library")).toBeNull();
    link.remove(); expect(resolveWorkspaceCommand("go-library")).toEqual({ href: "/workspace/library?mode=research" });
  });
  it("ignores disabled or hidden page actions while allowing enabled menu controls", () => {
    document.body.innerHTML = `<main class="workspace-app"><button data-command="save" disabled>Save</button><div aria-hidden="true"><button data-command="save">Copy</button></div><button data-command="save" style="visibility:hidden">Hidden</button><button data-command="save">Save now</button><div hidden><input type="radio" name="theme-preference" value="dark"><a href="/api/workspace/export">Export</a><button data-command="shortcuts">Shortcuts</button><div class="ws-sidebar-footer"><a href="/today">Preview</a><a href="/">Research</a></div></div></main>`;
    const buttons = document.querySelectorAll('[data-command="save"]');
    expect(resolveWorkspaceCommand("save")).toEqual({ element: buttons[3], action: "click" });
    expect(resolveWorkspaceCommand("theme-dark")).toEqual({ element: document.querySelector('input[value="dark"]'), action: "click" });
    expect(resolveWorkspaceCommand("export")).toEqual({ element: document.querySelector('a[href="/api/workspace/export"]'), action: "click" });
    expect(resolveWorkspaceCommand("shortcuts")).toEqual({ element: document.querySelector('[data-command="shortcuts"]'), action: "click" });
    expect(resolveWorkspaceCommand("go-preview")).toEqual({ element: document.querySelector('a[href="/today"]'), action: "click" });
    expect(resolveWorkspaceCommand("go-research")).toEqual({ element: document.querySelector('a[href="/"]'), action: "click" });
    buttons[3]!.setAttribute("aria-disabled", "true");
    expect(resolveWorkspaceCommand("save")).toBeNull();
    document.body.replaceChildren(); expect(resolveWorkspaceCommand("save")).toBeNull();
  });
  it("focuses a usable composer, opens a collapsed one, and escapes through close or editable focus", () => {
    document.body.innerHTML = '<main class="workspace-app"><button class="ws-composer-toggle">Open</button><input class="ws-composer-input" hidden><button data-command="escape">Close</button></main>';
    const input = document.querySelector<HTMLInputElement>("input")!, opener = document.querySelector(".ws-composer-toggle"), close = document.querySelector('[data-command="escape"]')!;
    expect(resolveWorkspaceCommand("focus-composer")).toEqual({ element: opener, action: "click" });
    input.hidden = false; expect(resolveWorkspaceCommand("focus-composer")).toEqual({ element: input, action: "focus" });
    expect(resolveWorkspaceCommand("escape")).toEqual({ element: close, action: "click" });
    close.remove(); input.focus(); expect(resolveWorkspaceCommand("escape")).toEqual({ element: input, action: "blur" });
    input.blur(); expect(resolveWorkspaceCommand("escape")).toBeNull();
  });
});
