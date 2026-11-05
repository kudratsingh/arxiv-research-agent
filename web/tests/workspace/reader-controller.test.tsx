import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { LiveReader } from "@/components/workspace/Reader";
import { DRAFT_KEY, loadDraft } from "@/lib/workspace/drafts";
import { navigationState, NAVIGATION_INTENT_KEY } from "@/lib/workspace/navigation";
import type { WorkspaceState } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";
import { MAT, retained, text as retainedText } from "./materialFixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => window.location.pathname,
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
const ids = [1, 2, 3, 4].map((n) => `arxiv:2610.0000${n}`);
const titles = ["Alpha", "Beta", "Gamma", "Delta"];
let current: WorkspaceState;
let calls: { path: string; body: Record<string, unknown> }[];
let pending: { resolve?: (value: Response) => void };
let holdReading: boolean;
let returnedPacketId: string | null;
let packetFailure: boolean;
let packetWorks: WorkspaceState["works"];
const packetId = `review-${"a".repeat(32)}`;
function fixture(): WorkspaceState {
  const works = ids.map((id, i) => {
    const template = work();
    const versions = template.versions.map((version, index) => ({ ...version,
      version_id: `${id}:v${index + 1}`, title: `${titles[i]} v${index + 1}`,
      abstract: `${titles[i]} retained abstract version ${index + 1}`,
      url: `https://arxiv.org/abs/2610.0000${i + 1}v${index + 1}`,
    }));
    return work({ work_id: id, version_id: `${id}:v2`, title: `${titles[i]} v2`, versions,
      reading: { ...template.reading, revision: 2, status: "saved", version_id: `${id}:v2`, anchor: "abstract:3:9" } });
  });
  const base = workspace();
  return workspace({ works, editions: [{ ...base.editions[0]!, work_ids: ids,
    work_versions: { [ids[0]!]: `${ids[0]}:v1`, [ids[2]!]: `${ids[2]}:v1` } }] });
}
function pathFor(index: number, returnTo: string, version = `${ids[index]}:v2`) {
  const params = new URLSearchParams({ version, return_to: returnTo });
  return `/workspace/items/${encodeURIComponent(ids[index]!)}?${params}#abstract%3A3%3A9`;
}
function openPath(index: number, returnTo: string, version = `${ids[index]}:v2`) {
  history.replaceState(null, "", pathFor(index, returnTo, version));
}
async function mount(index = 1) {
  const result = render(<WorkspaceShell><LiveReader id={ids[index]!} /></WorkspaceShell>);
  await screen.findByRole("heading", { level: 1 });
  return result;
}
beforeEach(() => {
  current = fixture(); calls = []; pending = {}; holdReading = false; returnedPacketId = packetId; packetFailure = false; packetWorks = [current.works[3]!, current.works[1]!, current.works[0]!];
  localStorage.clear(); sessionStorage.clear(); openPath(1, `/workspace/today?focus=${encodeURIComponent(ids[1]!)}`);
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    calls.push({ path, body });
    if (path === "state") return Response.json(current);
    if (path === "review") {
      if (packetFailure) return new Response(null, { status: 503 });
      return Response.json({ packet: returnedPacketId ? { id: returnedPacketId, items: packetWorks.map((candidate) => ({ work: candidate })) } : null, packet_ids: [] });
    }
    if (path === "reading") {
      if (holdReading) return new Promise<Response>((resolve) => { pending.resolve = resolve; });
      const item = current.works.find((entry) => entry.work_id === body.work_id);
      if (!item) throw new Error("Unknown work");
      return Response.json({ ...item.reading, ...(body.data as object), revision: item.reading.revision + 1 });
    }
    throw new Error(`Unexpected workspace request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("Reader controller", () => {
  it("vetoes ordinary and slash search during a real pending entry save with working recovery, then permits search after acknowledgement", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!; let finish!: (response: Response) => void;
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      if (String(url).endsWith("/entries")) { calls.push({ path: "entries", body: JSON.parse(String(init?.body)) }); return new Promise<Response>(resolve => { finish = resolve; }); }
      return original(url, init);
    });
    const user = userEvent.setup(); await mount(); await user.click(screen.getByRole("link", { name: "Your notes" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Pending exact-version question");
    const draft = loadDraft(current.principal_key_id, ids[1]!, `${ids[1]}:v2`)!;
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(window.dispatchEvent(new Event("beforeunload", { cancelable: true }))).toBe(true);
    const assign = vi.fn(); vi.stubGlobal("location", { ...window.location, assign });
    const input = await screen.findByRole("searchbox"); const before = history.state;
    const requests = navigationState.pending?.filter(action => action.type === "request").length ?? 0; sessionStorage.removeItem(NAVIGATION_INTENT_KEY);
    fireEvent.change(input, { target: { value: "keep pending query" } }); fireEvent.submit(input.closest("form")!);
    expect(assign).not.toHaveBeenCalled(); expect(input).toHaveValue("keep pending query");
    expect(screen.getByText("Search stayed here. Finish your save or save/copy your draft before leaving.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Wait for the current save");
    fireEvent.change(input, { target: { value: "/radar" } }); fireEvent.submit(input.closest("form")!);
    expect(input).toHaveValue("/radar"); expect(assign).not.toHaveBeenCalled();
    expect(history.state).toEqual(before); expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).toBeNull();
    expect(navigationState.pending?.filter(action => action.type === "request").length ?? 0).toBe(requests);
    expect(loadDraft(current.principal_key_id, ids[1]!, `${ids[1]}:v2`)).toEqual(draft);
    const request = calls.find(call => call.path === "entries")!;
    await act(async () => finish(Response.json({ id: request.body.id, revision: 1, ...(request.body.data as object), updated_at: "2026-11-02T17:00:00Z", activity_sequence: 99 })));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Your question" })).not.toHaveAttribute("readonly"));
    fireEvent.change(input, { target: { value: "permitted query" } }); fireEvent.submit(input.closest("form")!);
    expect(assign).toHaveBeenCalledOnce(); expect(assign).toHaveBeenCalledWith("/workspace/radar?q=permitted+query&days=7");
    expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).not.toContain("permitted query"); expect(calls.filter(call => call.path === "entries")).toHaveLength(1);
  });
  it.each(["source", "understand", "abstract:10:15"])("keeps the initial saved entry above conflicting #%s while allowing later explicit hashes", async fragment => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn(callback => { frames.push(callback); return frames.length; }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const item = current.works[1]!;
    item.entries = [{ id: "saved-entry", revision: 1, work_id: item.work_id, version_id: item.version_id,
      kind: "question", body: "Keep this exact saved-entry context", anchor: "abstract:2:5", updated_at: "2026-11-02T15:00:00Z", activity_sequence: 2 }];
    history.replaceState(null, "", `${location.pathname}${location.search}&entry=saved-entry#${fragment}`);
    await mount(); await waitFor(() => expect(frames.length).toBeGreaterThan(0));
    act(() => { for (const callback of frames.splice(0)) callback(0); });
    expect(document.getElementById("notes")).toHaveAttribute("data-active", "true");
    expect(document.getElementById("source")).toHaveAttribute("data-source-request", "abstract:2:5");
    expect(screen.getByText("Keep this exact saved-entry context")).toBeInTheDocument();
    act(() => { history.replaceState(null, "", `${location.pathname}${location.search}#source`); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(document.getElementById("source")).toHaveAttribute("data-active", "true");
    expect(calls.filter(call => call.path !== "state")).toHaveLength(0);
  });

  it("synchronizes typed same-document material anchors and retains exact work/version refusal without writes", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!;
    const document = { ...retained(), work_id: ids[1]!, version_id: `${ids[1]}:v2` };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/materials/")) {
        calls.push({ path: "materials", body: {} });
        return Response.json(String(url).endsWith(MAT) ? document : { ...document, material_id: "wrong", version_id: `${ids[1]}:v1` });
      }
      return original(url, init);
    }));
    await mount();
    act(() => { history.replaceState(null, "", `${location.pathname}${location.search}#material:${MAT}:page:7:10:20`); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByText(retainedText)).toBeInTheDocument();
    expect(window.document.getElementById("source")).toHaveAttribute("data-source-request", `material:${MAT}:page:7:10:20`);
    act(() => { history.replaceState(null, "", `${location.pathname}${location.search}#material:wrong:page:7:10:20`); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByText(/Retained material could not be opened/)).toBeInTheDocument();
    expect(screen.queryByText(retainedText)).not.toBeInTheDocument();
    expect(calls.filter(call => !["state", "materials"].includes(call.path))).toHaveLength(0);
  });

  it("synchronizes same-document Unicode ranges without remounting or changing a pending note's anchor", async () => {
    const text = "α🙂 exact retained passage. ".repeat(180);
    current.works[1]!.versions[1]!.abstract = text;
    const original = vi.mocked(fetch).getMockImplementation()!;
    let finish: ((response: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).endsWith("/entries")) {
        calls.push({ path: "entries", body: JSON.parse(String(init?.body)) });
        return new Promise<Response>(resolve => { finish = resolve; });
      }
      return original(url, init);
    }));
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    const textarea = screen.getByRole("textbox", { name: "Your question" });
    await user.type(textarea, "Preserve my question and its original anchor.");
    const before = loadDraft(current.principal_key_id, ids[1]!, `${ids[1]}:v2`)!;
    await user.click(screen.getByRole("button", { name: "Save question" }));
    expect(textarea).toHaveAttribute("readonly");
    const entryRequest = calls.find(call => call.path === "entries")!;
    const version = new URLSearchParams(location.search).get("version");
    for (const [start, end, event] of [[2500, 2520, "hashchange"], [50, 70, "popstate"], [2500, 2520, "popstate"]] as const) {
      act(() => {
        history.replaceState({ workspaceScroll: 123 }, "", `${location.pathname}${location.search}#abstract:${start}:${end}`);
        window.dispatchEvent(event === "hashchange" ? new HashChangeEvent(event) : new PopStateEvent(event, { state: history.state }));
      });
      await waitFor(() => expect(document.getElementById("source-anchor")?.textContent).toBe(Array.from(text).slice(start, end).join("")));
      expect(screen.getByRole("textbox", { name: "Your question" })).toBe(textarea);
      expect(textarea).toHaveValue(before.body); expect(textarea).toHaveAttribute("readonly");
      expect(loadDraft(current.principal_key_id, ids[1]!, `${ids[1]}:v2`)).toEqual(before);
      expect(new URLSearchParams(location.search).get("version")).toBe(version);
    }
    act(() => { history.replaceState({ workspaceScroll: 123 }, "", `${location.pathname}${location.search}#abstract:0`); window.dispatchEvent(new PopStateEvent("popstate", { state: history.state })); });
    expect(document.getElementById("source-anchor")).toBeNull();
    expect(textarea).toHaveValue(before.body); expect(textarea).toHaveAttribute("readonly");
    expect(loadDraft(current.principal_key_id, ids[1]!, `${ids[1]}:v2`)).toEqual(before);
    expect((entryRequest.body.data as Record<string, unknown>).anchor).toBe(before.anchor);
    expect((entryRequest.body.data as Record<string, unknown>).version_id).toBe(`${ids[1]}:v2`);
    expect(calls.filter(call => call.path === "entries")).toHaveLength(1);
    const data = entryRequest.body.data as Record<string, unknown>;
    await act(async () => finish!(Response.json({ id: entryRequest.body.id, revision: 1, ...data,
      updated_at: "2026-11-02T17:00:00Z", activity_sequence: 99 })));
    await waitFor(() => expect(textarea).not.toHaveAttribute("readonly"));
    expect(screen.getByRole("status")).toHaveTextContent("saved on the server");
  });

  it("catches a fragment changed during mount before the first synchronization frame", async () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal("requestAnimationFrame", vi.fn(callback => { frames.push(callback); return frames.length; }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    render(<LiveReader id={ids[1]!} />);
    await screen.findByRole("heading", { level: 1 });
    await waitFor(() => expect(frames.length).toBeGreaterThan(0));
    history.replaceState(null, "", `${location.pathname}${location.search}#abstract:10:15`);
    act(() => { for (const callback of frames.splice(0)) callback(0); });
    expect(document.getElementById("source-anchor")).toHaveAttribute("data-source-anchor", "abstract:10:15");
    expect(calls.filter(call => call.path !== "state")).toHaveLength(0);
  });

  it("refuses invented hash ranges and ignores malformed/cross-work/cross-version events", async () => {
    await mount();
    function hash(fragment: string, path = location.pathname, version = `${ids[1]}:v2`) {
      act(() => { history.replaceState(null, "", `${path}?version=${encodeURIComponent(version)}#${fragment}`); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    }
    hash("abstract:999999:9999999");
    expect(document.getElementById("source-anchor")).toBeNull();
    expect(screen.getByText(/This passage is unavailable/)).toBeInTheDocument();
    hash("excerpt:3:9"); expect(document.getElementById("source-anchor")).toBeNull();
    hash("abstract:3:9"); expect(document.getElementById("source-anchor")).toHaveAttribute("data-source-anchor", "abstract:3:9");
    const mark = document.getElementById("source-anchor");
    hash("%"); expect(document.getElementById("source-anchor")).toBe(mark);
    hash("abstract:5:10", `/workspace/items/${encodeURIComponent(ids[0]!)}`); expect(document.getElementById("source-anchor")).toBe(mark);
    hash("abstract:5:10", `/workspace/items/${encodeURIComponent(ids[1]!)}`, `${ids[1]}:missing`); expect(document.getElementById("source-anchor")).toBe(mark);
    hash("notes"); expect(document.getElementById("notes")).toHaveAttribute("data-active", "true");
    hash("understand"); expect(document.getElementById("understand")).toHaveAttribute("data-active", "true");
    expect(calls.filter(call => call.path !== "state")).toHaveLength(0);
  });

  it("keeps Source, Understand and Your notes links in main and preserves native note form order and unique controls", async () => {
    const user = userEvent.setup(); await mount();
    const main = screen.getByRole("main");
    expect(within(main).getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    for (const name of ["Source", "Understand", "Your notes"]) expect(within(main).getAllByRole("link", { name })).toHaveLength(1);
    expect(within(main).getByRole("link", { name: "← Today" })).toBeInTheDocument();
    for (const name of ["Remove from saved items", "Mark read", "Archive"]) expect(screen.getAllByRole("button", { name })).toHaveLength(1);
    await user.click(within(main).getByRole("link", { name: "Your notes" }));
    const form = screen.getByRole("combobox", { name: "Save as" }).closest("form");
    if (!form) throw new Error("Notes form missing");
    const controls = Array.from(form.querySelectorAll("select, textarea, button"));
    expect(controls[0]).toBe(screen.getByRole("combobox", { name: "Save as" }));
    expect(controls[1]).toBe(screen.getByRole("textbox", { name: "Your question" }));
    expect(controls[2]).toBe(screen.getByRole("button", { name: "Save question" }));
  });

  it("uses Today edition order and retained versions with focused return contexts", async () => {
    await mount();
    const previous = screen.getByRole("link", { name: "Previous paper" });
    const next = screen.getByRole("link", { name: "Next paper" });
    const firstReturn = `/workspace/today?focus=${encodeURIComponent(ids[0]!)}`;
    const thirdReturn = `/workspace/today?focus=${encodeURIComponent(ids[2]!)}`;
    expect(previous).toHaveAttribute("href", `/workspace/items/${encodeURIComponent(ids[0]!)}?${new URLSearchParams({ version: `${ids[0]}:v1`, return_to: firstReturn })}#abstract%3A0`);
    expect(next).toHaveAttribute("href", `/workspace/items/${encodeURIComponent(ids[2]!)}?${new URLSearchParams({ version: `${ids[2]}:v1`, return_to: thirdReturn })}#abstract%3A0`);
    expect(screen.getAllByRole("link", { name: /^Show paper \d of 4:/ })).toHaveLength(4);
    expect(screen.getByRole("link", { name: "Show paper 2 of 4: Beta v2" })).toHaveAttribute("aria-current", "true");
  });

  it("uses the Library view and saved anchors for neighbours, and disables controls at boundaries", async () => {
    const returnTo = "/workspace/library?view=saved";
    openPath(0, returnTo); const view = await mount(0);
    expect(screen.getByRole("link", { name: "← Library" })).toHaveAttribute("href", returnTo);
    expect(screen.getByRole("button", { name: "Previous paper" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Next paper" })).toHaveAttribute("href", pathFor(1, returnTo));
    view.unmount(); openPath(3, returnTo); await mount(3);
    expect(screen.getByRole("button", { name: "Next paper" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Previous paper" })).toHaveAttribute("href", pathFor(2, returnTo));
  });

  it("dispatches keyboard navigation to the enabled current link, while ignoring fields", async () => {
    const user = userEvent.setup(); await mount();
    const next = screen.getByRole("link", { name: "Next paper" });
    const click = vi.spyOn(next, "click").mockImplementation(() => {});
    fireEvent.keyDown(document.body, { key: "j" });
    expect(click).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Your question" }), { key: "j" });
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("omits a neighbour whose edition-pinned version is unavailable", async () => {
    current.editions[0]!.work_versions[ids[2]!] = `${ids[2]}:missing`;
    await mount();
    expect(screen.queryByRole("link", { name: /Show paper .*Gamma/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Next paper" })).toHaveAttribute("href", pathFor(3, `/workspace/today?focus=${encodeURIComponent(ids[3]!)}`));
  });

  it("keeps Radar back-only and its return context", async () => {
    const returnTo = "/workspace/radar?q=agents&days=7"; openPath(1, returnTo); await mount();
    expect(screen.getByRole("link", { name: "← Radar" })).toHaveAttribute("href", returnTo);
    expect(screen.queryByRole("link", { name: /^Show paper/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Next paper" })).not.toBeInTheDocument();
  });

  it("uses the selected Review packet order and preserves its return context", async () => {
    const returnTo = `/workspace/review?packet=${packetId}`;
    packetWorks[0] = { ...packetWorks[0]!, version_id: `${ids[3]}:v1` };
    openPath(1, returnTo); await mount();
    const queue = await screen.findAllByRole("link", { name: /^Show paper \d of 3:/ });
    expect(queue.map((link) => link.getAttribute("aria-label"))).toEqual([
      "Show paper 1 of 3: Delta v1", "Show paper 2 of 3: Beta v2", "Show paper 3 of 3: Alpha v2",
    ]);
    expect(screen.getByRole("link", { name: "← Candidate review" })).toHaveAttribute("href", returnTo);
    expect(screen.getByRole("link", { name: "Previous paper" })).toHaveAttribute("href", `/workspace/items/${encodeURIComponent(ids[3]!)}?${new URLSearchParams({ version: `${ids[3]}:v1`, return_to: returnTo })}#abstract%3A0`);
    expect(screen.getByRole("link", { name: "Next paper" })).toHaveAttribute("href", pathFor(0, returnTo));
    expect(calls.filter(({ path }) => path === "review")).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith(`/api/workspace/review?packet_id=${packetId}`, expect.anything());
  });

  it("does not invent Review neighbours when the returned packet is different", async () => {
    returnedPacketId = `review-${"b".repeat(32)}`;
    openPath(1, `/workspace/review?packet=${packetId}`); await mount();
    await waitFor(() => expect(calls.some(({ path }) => path === "review")).toBe(true));
    expect(screen.queryByRole("link", { name: /^Show paper/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Next paper" })).not.toBeInTheDocument();
  });

  it("does not invent neighbours when Review fetch fails", async () => {
    packetFailure = true; openPath(1, `/workspace/review?packet=${packetId}`); await mount();
    await waitFor(() => expect(calls.some(({ path }) => path === "review")).toBe(true));
    expect(screen.queryByRole("link", { name: /^Show paper/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← Candidate review" })).toBeInTheDocument();
  });

  it("keeps packet queue links while refusing to admit a candidate absent from loaded workspace", async () => {
    const missing = work({ work_id: "arxiv:external", version_id: "arxiv:external:v2", title: "External candidate" });
    packetWorks = [current.works[1]!, missing];
    const returnTo = `/workspace/review?packet=${packetId}`; openPath(1, returnTo);
    const view = await mount();
    const next = await screen.findByRole("link", { name: "Next paper" });
    const destination = next.getAttribute("href"); if (!destination) throw new Error("Candidate link missing");
    view.unmount(); history.replaceState(null, "", destination);
    render(<WorkspaceShell><LiveReader id="arxiv:external" /></WorkspaceShell>);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("This source is not in the loaded workspace.");
    expect(screen.getByText(/No fictional source was substituted/)).toBeInTheDocument();
  });

  it("does not attribute newer authors to an older version with no retained authors", async () => {
    current.works[1]!.versions[0]!.authors = [];
    current.works[1]!.authors = ["Newer author"];
    openPath(1, "/workspace/today", `${ids[1]}:v1`); await mount();
    expect(screen.getByText(/Authors not retained for this version/)).toBeInTheDocument();
    expect(screen.queryByText(/Newer author/)).not.toBeInTheDocument();
  });

  it("moves focus to the chosen section after rendering it", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(document.getElementById("notes")).toHaveFocus();
    await user.click(screen.getByRole("link", { name: "Source" }));
    expect(document.getElementById("source")).toHaveFocus();
  });

  it("does not substitute a newer source when the requested retained version is missing", async () => {
    openPath(1, "/workspace/today", `${ids[1]}:missing`); await mount();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This retained source version is unavailable.");
    expect(screen.getByText(/A newer version has not been substituted/)).toBeInTheDocument();
    expect(screen.queryByText("Beta retained abstract version 2")).not.toBeInTheDocument();
  });

  it("recovers unsaved drafts for each owner, work and version after moving between readers", async () => {
    const user = userEvent.setup(); const view = await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Beta unsaved thought");
    expect(screen.getByRole("status")).toHaveTextContent("Unsaved draft");
    expect(loadDraft("owner-a", ids[1]!, `${ids[1]}:v2`)?.body).toBe("Beta unsaved thought");
    expect(loadDraft("owner-a", ids[0]!, `${ids[0]}:v2`)).toBeNull();
    expect(loadDraft("owner-b", ids[1]!, `${ids[1]}:v2`)).toBeNull();
    expect(loadDraft("owner-a", ids[1]!, `${ids[1]}:v1`)).toBeNull();
    const nextHref = screen.getByRole("link", { name: "Next paper" }).getAttribute("href");
    if (!nextHref) throw new Error("Next reader link missing");
    view.unmount(); history.replaceState(null, "", nextHref); const other = await mount(2);
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("");
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Gamma separate draft");
    other.unmount(); openPath(1, `/workspace/today?focus=${encodeURIComponent(ids[1]!)}`); await mount();
    expect(screen.getByRole("status")).toHaveTextContent(/Recovered.*unsaved draft/);
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("Beta unsaved thought");
    expect(screen.getByText(/Only a successful server response confirms a durable save/)).toBeInTheDocument();
    expect(calls.filter(({ path }) => path === "entries")).toHaveLength(0);
    expect(sessionStorage.getItem(DRAFT_KEY)).toContain("Gamma separate draft");
  });

  it("blocks leaving an unstorable draft via queue, back or version change and explains why", async () => {
    const user = userEvent.setup(); await mount();
    const setItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (this === sessionStorage) throw new Error("storage unavailable");
      return setItem.call(this, key, value);
    });
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Keep this text");
    expect(screen.getByText(/Save or copy your unsaved text before leaving this source version/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Previous paper" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next paper" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Source version" })).toBeDisabled();
    const back = screen.getByRole("link", { name: "← Today" });
    expect(back).toHaveAttribute("aria-disabled", "true");
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => { back.dispatchEvent(click); }); expect(click.defaultPrevented).toBe(true);
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("Keep this text");
    const assign = vi.fn(); vi.stubGlobal("location", { ...window.location, assign });
    const search = await screen.findByRole("searchbox"); fireEvent.change(search, { target: { value: "preserve unsafe draft" } }); fireEvent.submit(search.closest("form")!);
    expect(assign).not.toHaveBeenCalled(); expect(search).toHaveValue("preserve unsafe draft");
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("Keep this text");
  });

  it("guards shell and saved-entry navigation while draft recovery is unavailable", async () => {
    const item = current.works[1]!;
    const base = { id: "entry-current", revision: 2, work_id: item.work_id, version_id: item.version_id,
      kind: "question" as const, body: "Saved current question", anchor: "abstract:2:5", updated_at: "2026-11-02T15:00:00Z", activity_sequence: 2 };
    item.entries = [base, { ...base, id: "entry-old", version_id: item.versions[0]!.version_id, body: "Older version question" }];
    const user = userEvent.setup(); await mount();
    const setItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (this === sessionStorage) throw new Error("storage unavailable");
      return setItem.call(this, key, value);
    });
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Unrecoverable draft");
    for (const link of [screen.getByRole("link", { name: "Library" }), screen.getByRole("link", { name: "Source context →" }), screen.getByRole("link", { name: /Older version question/ })]) {
      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      act(() => { link.dispatchEvent(event); });
      expect(event.defaultPrevented).toBe(true);
    }
    const unload = new Event("beforeunload", { cancelable: true });
    expect(window.dispatchEvent(unload)).toBe(false);
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue("Unrecoverable draft");
    await user.click(screen.getByRole("link", { name: "Source" }));
    expect(document.getElementById("source")).toHaveFocus();
    const external = screen.getByRole("link", { name: "Open original source ↗" });
    const reached = vi.fn((event: Event) => event.preventDefault());
    external.addEventListener("click", reached);
    fireEvent.click(external);
    expect(reached).toHaveBeenCalledOnce();
  });

  it("allows normal links and unload when the draft is recoverable", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await user.type(screen.getByRole("textbox", { name: "Your question" }), "Recoverable draft");
    const link = screen.getByRole("link", { name: "Library" });
    const reached = vi.fn((event: Event) => event.preventDefault());
    link.addEventListener("click", reached);
    fireEvent.click(link);
    expect(reached).toHaveBeenCalledOnce();
    expect(window.dispatchEvent(new Event("beforeunload", { cancelable: true }))).toBe(true);
  });

  it("keeps edited saved-entry text and recovery after a pending save fails", async () => {
    const item = current.works[1]!;
    item.entries = [{ id: "saved-entry", revision: 2, work_id: item.work_id, version_id: item.version_id,
      kind: "question", body: "Old saved question", anchor: "abstract:2:5", updated_at: "2026-11-02T15:00:00Z", activity_sequence: 2 }];
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Reading state saved on the server/));
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    const input = screen.getByRole("textbox", { name: "Your question" });
    await user.clear(input); await user.type(input, "Edited question pending");
    const gate: { resolve?: (response: Response) => void } = {};
    vi.mocked(fetch).mockImplementation(async () => new Promise<Response>((resolve) => { gate.resolve = resolve; }));
    await user.click(screen.getByRole("button", { name: "Save question" }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    expect(screen.getByRole("button", { name: "Edit question" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Edit question" }));
    const complete = gate.resolve; if (!complete) throw new Error("Pending entry missing");
    await act(async () => complete(new Response(null, { status: 503 })));
    await waitFor(() => expect(screen.getByRole("button", { name: "Edit question" })).toBeEnabled());
    expect(input).toHaveValue("Edited question pending");
    expect(loadDraft("owner-a", item.work_id, item.version_id)?.body).toBe("Edited question pending");
    expect(screen.getByText("Old saved question")).toBeInTheDocument();
  });

  it("protects edits made while an entry save is pending", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("link", { name: "Your notes" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Reading state saved on the server/));
    const input = screen.getByRole("textbox", { name: "Your question" });
    await user.type(input, "First saved text");
    const gate: { resolve?: (response: Response) => void; request?: Record<string, unknown>; count: number } = { count: 0 };
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (!path.endsWith("/entries")) throw new Error(`Unexpected request: ${path}`);
      gate.count += 1;
      gate.request = JSON.parse(String(init?.body)) as Record<string, unknown>;
      return new Promise<Response>((resolve) => { gate.resolve = resolve; });
    });
    await user.click(screen.getByRole("button", { name: "Save question" }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    const form = input.closest("form"); if (!form) throw new Error("Notes form missing");
    fireEvent.submit(form);
    expect(gate.count).toBe(1);
    const editable = !input.hasAttribute("readonly") && !input.hasAttribute("disabled");
    if (editable) {
      await user.type(input, " newer unsaved text");
      expect(loadDraft("owner-a", ids[1]!, `${ids[1]}:v2`)?.body).toBe("First saved text newer unsaved text");
    } else {
      expect(screen.getByRole("combobox", { name: "Save as" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Discard unsaved draft" })).toBeDisabled();
    }
    const complete = gate.resolve; const captured = gate.request;
    if (!complete || !captured) throw new Error("Entry request not captured");
    const data = captured.data as Record<string, unknown>;
    const entryId = captured.id;
    await act(async () => complete(Response.json({ ...data, id: entryId, revision: 1,
      updated_at: "2026-11-02T15:00:00Z", activity_sequence: 1 })));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/saved on the server/));
    expect(screen.getByText("First saved text")).toBeInTheDocument();
    if (editable) {
      expect(input).toHaveValue("First saved text newer unsaved text");
      expect(loadDraft("owner-a", ids[1]!, `${ids[1]}:v2`)?.body).toBe("First saved text newer unsaved text");
    } else {
      expect(input).toHaveValue("");
      expect(loadDraft("owner-a", ids[1]!, `${ids[1]}:v2`)).toBeNull();
    }
  });

  it("blocks navigation and actions during a pending server write and does not claim a save prematurely", async () => {
    holdReading = true; const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Mark read" }));
    await waitFor(() => expect(calls.filter(({ path }) => path === "reading")).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Next paper" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Previous paper" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Source version" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "← Today" })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("status")).not.toHaveTextContent("saved on the server");
    expect(window.dispatchEvent(new Event("beforeunload", { cancelable: true }))).toBe(true);
    const library = screen.getByRole("link", { name: "Library" });
    const blocked = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => { library.dispatchEvent(blocked); });
    expect(blocked.defaultPrevented).toBe(true);
    const reached = vi.fn((event: Event) => event.preventDefault());
    library.addEventListener("click", reached);
    fireEvent.click(library, { ctrlKey: true });
    fireEvent.click(library, { button: 1 });
    expect(reached).toHaveBeenCalledTimes(2);
    const alreadyPrevented = new MouseEvent("click", { bubbles: true, cancelable: true });
    alreadyPrevented.preventDefault();
    act(() => { library.dispatchEvent(alreadyPrevented); });
    expect(reached).toHaveBeenCalledTimes(3);
    const external = screen.getByRole("link", { name: "Open original source ↗" });
    external.addEventListener("click", reached); fireEvent.click(external);
    const download = document.createElement("a"); download.href = "/download"; download.download = "sample";
    download.addEventListener("click", reached); document.body.append(download); fireEvent.click(download); download.remove();
    const fragment = screen.getByRole("link", { name: "Source" });
    fragment.addEventListener("click", reached); fireEvent.click(fragment);
    expect(reached).toHaveBeenCalledTimes(6);
    const ordinaryButton = document.createElement("button"); const clicked = vi.fn(); ordinaryButton.onclick = clicked;
    document.body.append(ordinaryButton); fireEvent.click(ordinaryButton); ordinaryButton.remove();
    expect(clicked).toHaveBeenCalledOnce();
    fireEvent.keyDown(document.body, { key: "j" });
    expect(calls.filter(({ path }) => path === "reading")).toHaveLength(1);
    const complete = pending.resolve; if (!complete) throw new Error("Pending request not captured");
    await act(async () => complete(Response.json({ ...current.works[1]!.reading, status: "read", revision: 3 })));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(/Reading state saved on the server/));
    expect(screen.getByRole("link", { name: "Next paper" })).toBeInTheDocument();
    fireEvent.click(library);
    expect(reached).toHaveBeenCalledTimes(7);
  });
});
