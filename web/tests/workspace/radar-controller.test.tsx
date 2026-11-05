import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { LiveRadar } from "@/components/workspace/Radar";
import type { ReadingData, WorkspaceState } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/radar", useSearchParams: () => new URLSearchParams(location.search) }));
const ids = [1, 2, 3, 4].map((n) => `arxiv:2610.0000${n}`);
const titles = ["Alpha", "Beta", "Gamma", "Delta"];
let current: WorkspaceState;
let itemsRequests: string[];
let catalogue: WorkspaceState["works"];
let failItems: boolean;
let writes: Record<string, unknown>[];
let failWrite: boolean;
let searches: Map<string, (response: Response) => void>;
let holdSearch: boolean;
function fixture(): WorkspaceState {
  const works = ids.map((id, index) => work({ work_id: id, title: titles[index], version_id: `${id}:v2`,
    abstract: `${titles[index]} source abstract`, versions: [{ ...work().versions[1]!, version_id: `${id}:v2`, title: titles[index]!, abstract: `${titles[index]} source abstract` }] }));
  return workspace({ works });
}
function page(indices = [0, 1, 2, 3], next_cursor: string | null = "cursor-2") {
  return { items: indices.map((index) => catalogue[index]!), next_cursor, as_of: "2026-11-02T15:00:00Z" };
}
beforeEach(() => {
  current = fixture(); catalogue = [...current.works]; failItems = false; itemsRequests = []; writes = []; failWrite = false; searches = new Map(); holdSearch = false;
  sessionStorage.clear(); localStorage.clear(); history.replaceState(null, "", "/workspace/radar?q=initial&days=7");
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const parsed = new URL(url, "http://localhost"); const path = parsed.pathname.replace("/api/workspace/", "");
    if (path === "context/state") return Response.json(current);
    if (path === "context/items") {
      itemsRequests.push(parsed.search);
      if (failItems) return new Response(null, { status: 503 });
      if (holdSearch) return new Promise<Response>((resolve) => { searches.set(parsed.searchParams.get("q") ?? "", resolve); });
      return Response.json(parsed.searchParams.has("cursor") ? page([3], null) : page());
    }
    if (path === "context/reading") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>; writes.push(body);
      if (failWrite) return new Response(null, { status: 503 });
      const item = current.works.find((entry) => entry.work_id === body.work_id) ?? catalogue.find((entry) => entry.work_id === body.work_id);
      if (!item) throw new Error("Unexpected work");
      item.reading = { ...item.reading, ...(body.data as ReadingData), revision: item.reading.revision + 1 };
      return Response.json(item.reading);
    }
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function mount() { const view = render(<WorkspaceShell><LiveRadar /></WorkspaceShell>); await screen.findByRole("button", { name: "Show paper 1 of 4: Alpha" }); await waitFor(() => expect(screen.queryByText("Opening the selected paper…")).not.toBeInTheDocument()); return view; }
function focused(title: string) { const articles = screen.getAllByRole("article"); expect(articles).toHaveLength(1); expect(within(articles[0]!).getByRole("heading", { level: 3 })).toHaveTextContent(title); }

describe("Radar controller", () => {
  it("steps focus instantly in queue and keyboard without refetching or adding history entries", async () => {
    const user = userEvent.setup(); const view = await mount(); focused("Alpha");
    const count = itemsRequests.length; const historyLength = history.length;
    await user.click(screen.getByRole("button", { name: "Show paper 3 of 4: Gamma" })); focused("Gamma");
    expect(new URL(location.href).searchParams.get("focus")).toBe(ids[2]);
    fireEvent.keyDown(document.body, { key: "k" }); focused("Beta");
    fireEvent.keyDown(document.body, { key: "j" }); focused("Gamma");
    expect(itemsRequests).toHaveLength(count); expect(history.length).toBe(historyLength);
    const input = screen.getByRole("searchbox", { name: "Search titles and abstracts" });
    fireEvent.keyDown(input, { key: "j" }); focused("Gamma");
    const url = new URL(location.href); url.searchParams.set("focus", ids[3]!);
    act(() => { history.pushState(null, "", `${url.pathname}${url.search}`); window.dispatchEvent(new PopStateEvent("popstate")); });
    focused("Delta"); expect(itemsRequests).toHaveLength(count);
    act(() => { history.back(); }); await waitFor(() => focused("Gamma"));
    act(() => { history.forward(); }); await waitFor(() => focused("Delta"));
    expect(itemsRequests).toHaveLength(count);
    view.unmount(); await mount(); focused("Delta");
    expect(new URL(location.href).searchParams.get("focus")).toBe(ids[3]);
  });
  it("retains the observation cutoff for pagination and returns from the reader to the search context", async () => {
    const user = userEvent.setup(); await mount();
    const link = within(screen.getByRole("article")).getByRole("heading", { level: 3 }).querySelector("a");
    expect(link?.getAttribute("href")).toContain(`return_to=${encodeURIComponent("/workspace/radar?q=initial&days=7")}`);
    expect(screen.queryByRole("button", { name: "Next page →" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show paper 4 of 4: Delta" }));
    expect(screen.getAllByRole("button", { name: "Next page →" })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Next page →" }));
    await waitFor(() => focused("Delta"));
    const params = new URLSearchParams(itemsRequests.at(-1));
    expect(params.get("cursor")).toBe("cursor-2"); expect(params.get("as_of")).toBe("2026-11-02T15:00:00Z");
    expect(screen.getByRole("button", { name: "Next paper" })).toBeDisabled();
  });
  it("hides stale results during a new search and never restores an aborted older result or a failed result", async () => {
    const user = userEvent.setup(); await mount(); holdSearch = true;
    const search = screen.getByRole("searchbox", { name: "Search titles and abstracts" });
    await user.clear(search); await user.type(search, "older"); await user.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(searches.has("older")).toBe(true));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    act(() => { history.pushState(null, "", "/workspace/radar?q=newer&days=7"); window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(searches.has("newer")).toBe(true));
    await act(async () => searches.get("newer")?.(Response.json(page([2], null))));
    await waitFor(() => focused("Gamma"));
    await act(async () => searches.get("older")?.(Response.json(page([0], null))));
    focused("Gamma");
    act(() => { history.pushState(null, "", "/workspace/radar?q=failed&days=7"); window.dispatchEvent(new PopStateEvent("popstate")); });
    await waitFor(() => expect(searches.has("failed")).toBe(true));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    await act(async () => searches.get("failed")?.(new Response(null, { status: 503 })));
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).not.toHaveTextContent("Saved on the server");
  });
  it("retries a failed initial search without getting stuck loading", async () => {
    failItems = true; const user = userEvent.setup();
    render(<WorkspaceShell><LiveRadar /></WorkspaceShell>);
    await screen.findByRole("heading", { name: "This stored result window could not be loaded." });
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(itemsRequests).toHaveLength(1);
    failItems = false; await user.click(screen.getByRole("button", { name: "Retry stored results" }));
    await screen.findByRole("button", { name: "Show paper 1 of 4: Alpha" });
    focused("Alpha"); expect(itemsRequests).toHaveLength(2);
  });
  it("reflects Save and Undo for an item first observed after the workspace snapshot", async () => {
    current.works = current.works.filter((item) => item.work_id !== ids[0]);
    const user = userEvent.setup(); await mount(); focused("Alpha");
    await user.click(screen.getByRole("button", { name: /^Save Alpha/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Unsave Alpha/ })).toBeInTheDocument());
    expect(writes[0]?.work_id).toBe(ids[0]);
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Save Alpha/ })).toBeInTheDocument());
    expect(writes[1]?.revision).toBe(1);
    expect((writes[1]?.data as ReadingData).status).toBe("unread");
  });
  it("shows an unavailable saved source without substituting newer content", async () => {
    current.works[0]!.reading = { ...current.works[0]!.reading, revision: 2, version_id: `${ids[0]}:missing`, anchor: "abstract:2:5" };
    await mount();
    expect(screen.getByRole("heading", { name: "This retained source version is unavailable." })).toBeInTheDocument();
    expect(screen.getByText(/A newer version has not been substituted/)).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in reader" })).toHaveAttribute("href", expect.stringContaining(encodeURIComponent(`${ids[0]}:missing`)));
    expect(screen.queryByRole("button", { name: /^Save Alpha/ })).not.toBeInTheDocument();
  });
  it("does not change the current result or start another action during a pending write", async () => {
    const user = userEvent.setup(); await mount();
    const gate: { resolve?: (response: Response) => void; count: number } = { count: 0 };
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path.endsWith("/reading")) { gate.count++; return new Promise<Response>((resolve) => { gate.resolve = resolve; }); }
      throw new Error(`Unexpected request: ${path}`);
    });
    await user.click(screen.getByRole("button", { name: /^Save Alpha/ }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 4: Beta" })); focused("Alpha");
    fireEvent.keyDown(document.body, { key: "j" }); focused("Alpha");
    expect(screen.getByRole("button", { name: "Apply filters" })).toBeDisabled();
    expect(gate.count).toBe(1);
    const complete = gate.resolve; if (!complete) throw new Error("Reading request missing");
    await act(async () => complete(Response.json({ ...current.works[0]!.reading, status: "saved", revision: 1 })));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Unsave Alpha/ })).toBeEnabled());
  });
  it.each([["Dismiss", "dismissed"], ["Snooze one day", "snoozed"]] as const)("persists %s on the selected result and undoes it", async (label, status) => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: new RegExp(`^${label} Alpha`) }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.work_id).toBe(ids[0]); expect(writes[0]?.data).toMatchObject({ status, version_id: `${ids[0]}:v2`, anchor: "abstract:0" });
    if (status === "snoozed") expect((writes[0]?.data as ReadingData).snoozed_until).toEqual(expect.any(String));
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]?.data).toMatchObject({ status: "unread", anchor: "abstract:0" }); focused("Alpha");
  });
  it("renders the matching top-level version even when the version list is empty", async () => {
    current.works[0]!.versions = [];
    await mount(); focused("Alpha");
    expect(screen.queryByText("This retained source version is unavailable.")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in reader" })).toHaveAttribute("href", expect.stringContaining(encodeURIComponent(`${ids[0]}:v2`)));
  });
  it("closes the mobile drawer after result selection and applying filters", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); render(<WorkspaceShell><LiveRadar /></WorkspaceShell>);
    await screen.findByRole("heading", { level: 1 });
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(await screen.findByRole("button", { name: "Show paper 2 of 4: Beta" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); focused("Beta");
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    const search = screen.getByRole("searchbox", { name: "Search titles and abstracts" });
    await user.clear(search); await user.type(search, "query");
    await user.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(new URLSearchParams(itemsRequests.at(-1)).get("q")).toBe("query"));
  });
  it("preserves the selected result and request identity on failed actions, then supports Undo", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 4: Beta" }));
    failWrite = true; await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(writes).toHaveLength(1)); focused("Beta");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeEnabled());
    failWrite = false; await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Unsave Beta/ })).toBeInTheDocument());
    expect(writes[1]?.request_id).toBe(writes[0]?.request_id);
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeInTheDocument()); focused("Beta");
  });
});
