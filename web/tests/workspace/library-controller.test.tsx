import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { LiveLibrary } from "@/components/workspace/Library";
import { INITIAL_DATA, PREVIEW_KEY } from "@/lib/daily/store";
import type { ReadingData, WorkspaceState } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/library", useSearchParams: () => new URLSearchParams(location.search) }));
const ids = [1, 2, 3, 4].map((n) => `arxiv:2610.0000${n}`);
const titles = ["Alpha", "Beta", "Gamma", "Delta"];
let current: WorkspaceState;
let calls: { path: string; body: Record<string, unknown> }[];
let failManual: boolean;
let failReading: boolean;
function fixture(): WorkspaceState {
  const statuses = ["saved", "unread", "saved", "archived"] as const;
  const works = ids.map((id, index) => {
    const template = work();
    const item = work({ work_id: id, title: titles[index], version_id: `${id}:v2`, abstract: `${titles[index]} abstract`,
      versions: [{ ...template.versions[1]!, version_id: `${id}:v2`, title: titles[index]!, abstract: `${titles[index]} abstract` }],
      reading: { ...template.reading, status: statuses[index]!, revision: 1, version_id: `${id}:v2`, anchor: "abstract:2:7" } });
    if (index > 0) item.entries = [{ id: `entry-${index}`, revision: 1, work_id: id, version_id: `${id}:v2`, kind: "question", body: `${titles[index]} saved question`, anchor: "abstract:2:7", updated_at: "2026-11-02T15:00:00Z", activity_sequence: index }];
    return item;
  });
  return workspace({ works });
}
beforeEach(() => {
  current = fixture(); calls = []; failManual = false; failReading = false;
  sessionStorage.clear(); localStorage.clear(); history.replaceState(null, "", "/workspace/library?view=notes");
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}; calls.push({ path, body });
    if (path === "context/state") return Response.json(current);
    if (path === "manual") { if (failManual) return new Response(null, { status: 503 }); return Response.json(work({ title: "Manual source", access_state: "metadata", abstract: "" })); }
    if (path === "import/preview" || path === "import/apply") return Response.json({ digest: "preview-digest", entries_new: 1, entries_existing: 0, conflicts: [], profile_will_change: false, original_retained: true });
    if (path === "context/reading") {
      if (failReading) return new Response(null, { status: 503 });
      const item = current.works.find((entry) => entry.work_id === body.work_id); if (!item) throw new Error("Unexpected work");
      item.reading = { ...item.reading, ...(body.data as ReadingData), revision: item.reading.revision + 1 };
      return Response.json(item.reading);
    }
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function mount() { const view = render(<WorkspaceShell><LiveLibrary /></WorkspaceShell>); await screen.findByRole("combobox", { name: "Library view" }); await waitFor(() => expect(screen.queryByText("Opening the selected paper…")).not.toBeInTheDocument()); return view; }
async function openImport(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByText("Import preview notes", { selector: "summary" }));
  await screen.findByRole("button", { name: "Preview browser import" });
}
function focused(title: string) {
  const articles = document.querySelectorAll("article.daily-item"); expect(articles).toHaveLength(1);
  expect(within(articles[0] as HTMLElement).getByRole("heading", { level: 3 })).toHaveTextContent(title);
}

describe("Library controller", () => {
  it("keeps the notes view native, includes unread works and lists every note with focused work first", async () => {
    const user = userEvent.setup(); await mount();
    expect(screen.getByRole("combobox", { name: "Library view" })).toHaveValue("notes");
    expect(screen.getByRole("button", { name: "Show paper 1 of 3: Beta" })).toBeInTheDocument();
    focused("Beta");
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 3: Gamma" })); focused("Gamma");
    const notes = Array.from(document.querySelectorAll("article.daily-notebook-entry"));
    expect(notes).toHaveLength(3);
    expect(notes.map((node) => node.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("Beta saved question"), expect.stringContaining("Gamma saved question"), expect.stringContaining("Delta saved question")]));
    expect(notes[0]).toHaveTextContent("Gamma saved question");
    const beta = notes.find((node) => node.textContent?.includes("Beta saved question"));
    if (!beta) throw new Error("Unread work note missing");
    const resume = within(beta as HTMLElement).getByRole("link", { name: "Resume this question →" });
    expect(resume.getAttribute("href")).toContain(`version=${encodeURIComponent(`${ids[1]}:v2`)}`);
    expect(resume.getAttribute("href")).toContain("entry=entry-1");
    expect(resume.getAttribute("href")).toContain("return_to=%2Fworkspace%2Flibrary%3Fview%3Dnotes");
    expect(new URL(resume.getAttribute("href")!, location.origin).searchParams.get("return_to")).toContain("focus=arxiv%3A2610.00003");
    expect(resume.getAttribute("href")).toContain("#abstract%3A2%3A7");
  });
  it("restores focus on Reader return per account and view without changing the exact return URL", async () => {
    const user = userEvent.setup(); const first = await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 3: Gamma" })); focused("Gamma");
    first.unmount(); history.replaceState(null, "", "/workspace/library?view=notes"); const restored = await mount(); focused("Gamma");
    expect(location.search).toBe("?view=notes"); restored.unmount();
    history.replaceState(null, "", "/workspace/library?view=saved"); const saved = await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 1 of 2: Alpha" })); focused("Alpha");
    saved.unmount(); history.replaceState(null, "", "/workspace/library?view=notes");
    const notes = await mount(); focused("Gamma"); notes.unmount();
    current.principal_key_id = "owner-b"; await mount(); focused("Beta");
  });
  it("remembers the source of a different notebook link on activation and restores it on exact notes return", async () => {
    const user = userEvent.setup(); const view = await mount(); focused("Beta");
    const article = screen.getByText("Gamma saved question").closest("article");
    if (!article) throw new Error("Gamma note missing");
    const resume = within(article).getByRole("link", { name: "Resume this question →" });
    resume.addEventListener("click", (event) => event.preventDefault());
    await user.click(resume);
    view.unmount(); history.replaceState(null, "", "/workspace/library?view=notes"); await mount();
    focused("Gamma"); expect(location.search).toBe("?view=notes");
  });
  it.each(["paper", "question"] as const)("keeps the current Library return view while restoring a %s's saved Research identity", async kind => {
    const project = `project-${"c".repeat(32)}`;
    const origin = { mode: "research" as const, project_id: project, thread_id: null, return_to: `/workspace/projects?mode=research&project=${project}` };
    const item = current.works[1]!; item.reading.context = origin; item.entries[0]!.context = origin;
    history.replaceState(null, "", `/workspace/library?mode=learn&view=notes&focus=${encodeURIComponent(item.work_id)}`);
    await mount();
    const link = kind === "paper" ? screen.getByRole("link", { name: "Open in reader" }) : within(screen.getByText("Beta saved question").closest("article")!).getByRole("link", { name: "Resume this question →" });
    const target = new URL(link.getAttribute("href")!, location.origin), back = new URL(target.searchParams.get("return_to")!, location.origin);
    expect(target.searchParams.get("mode")).toBe("research"); expect(target.searchParams.get("project")).toBe(project);
    expect(target.searchParams.get("version")).toBe(item.version_id); expect(decodeURIComponent(target.hash)).toBe("#abstract:2:7");
    if (kind === "question") expect(target.searchParams.get("entry")).toBe(item.entries[0]!.id);
    expect(back.pathname).toBe("/workspace/library"); expect(back.searchParams.get("view")).toBe("notes");
    expect(back.searchParams.get("focus")).toBe(item.work_id); expect(back.searchParams.get("mode")).toBe("learn");
    expect(back.searchParams.has("project")).toBe(false);
  });
  it("supports keyboard next and previous within the current view", async () => {
    await mount(); focused("Beta");
    fireEvent.keyDown(document.body, { key: "j" }); focused("Gamma");
    fireEvent.keyDown(document.body, { key: "k" }); focused("Beta");
  });
  it.each([["Dismiss", "dismissed"], ["Snooze one day", "snoozed"]] as const)("persists %s and restores the original reading state on Undo", async (label, status) => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: new RegExp(`^${label} Beta`) }));
    await waitFor(() => expect(calls.filter(({ path }) => path === "context/reading")).toHaveLength(1));
    const first = calls.find(({ path }) => path === "context/reading")!.body;
    expect(first.work_id).toBe(ids[1]); expect(first.data).toMatchObject({ status, version_id: `${ids[1]}:v2`, anchor: "abstract:2:7" });
    if (status === "snoozed") expect((first.data as ReadingData).snoozed_until).toEqual(expect.any(String));
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(calls.filter(({ path }) => path === "context/reading")).toHaveLength(2));
    expect(calls.filter(({ path }) => path === "context/reading")[1]?.body.data).toMatchObject({ status: "unread", anchor: "abstract:2:7" });
  });
  it("accepts a matching top-level retained version when no version list is available", async () => {
    current.works[1]!.versions = [];
    await mount(); focused("Beta");
    expect(screen.queryByText("This retained source version is unavailable.")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in reader" })).toHaveAttribute("href", expect.stringContaining(encodeURIComponent(`${ids[1]}:v2`)));
  });
  it("closes the mobile drawer after queue and view selection", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); render(<WorkspaceShell><LiveLibrary /></WorkspaceShell>);
    await screen.findByRole("heading", { level: 1 });
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(await screen.findByRole("button", { name: "Show paper 2 of 3: Gamma" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); focused("Gamma");
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Library view" }), "saved");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(new URL(location.href).searchParams.get("view")).toBe("saved");
  });
  it("honours URL focus and browser history, while filtering each view independently", async () => {
    history.replaceState(null, "", `/workspace/library?view=notes&focus=${encodeURIComponent(ids[3]!)}`);
    await mount(); focused("Delta");
    act(() => { history.pushState(null, "", `/workspace/library?view=notes&focus=${encodeURIComponent(ids[1]!)}`); window.dispatchEvent(new PopStateEvent("popstate")); });
    focused("Beta"); act(() => { history.back(); }); await waitFor(() => focused("Delta"));
    act(() => { history.forward(); }); await waitFor(() => focused("Beta"));
    const select = screen.getByRole("combobox", { name: "Library view" });
    await userEvent.setup().selectOptions(select, "saved");
    expect(new URL(location.href).searchParams.get("view")).toBe("saved");
    expect(screen.queryByRole("button", { name: /Show paper .*Beta/ })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Show paper \d of 2:/ })).toHaveLength(2);
  });
  it("preserves failed reading actions and idempotent retry, with a working Undo", async () => {
    const user = userEvent.setup(); await mount(); failReading = true;
    await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(calls.filter(({ path }) => path === "context/reading")).toHaveLength(1)); focused("Beta");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeEnabled());
    failReading = false; await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Unsave Beta/ })).toBeInTheDocument());
    const writes = calls.filter(({ path }) => path === "context/reading"); expect(writes[1]?.body.request_id).toBe(writes[0]?.body.request_id);
    await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeInTheDocument());
  });
  it("shows an unavailable saved version without substituting the newer source", async () => {
    const item = current.works[1]!; item.reading.version_id = `${item.work_id}:missing`;
    await mount();
    expect(screen.getByRole("heading", { name: "This retained source version is unavailable." })).toBeInTheDocument();
    expect(screen.getByText(/A newer version has not been substituted/)).toBeInTheDocument();
    expect(document.querySelector("article.daily-item")).toBeNull();
    expect(screen.getByRole("link", { name: "Open retained source context →" })).toHaveAttribute("href", expect.stringContaining(encodeURIComponent(`${item.work_id}:missing`)));
    expect(screen.queryByRole("link", { name: "Open in reader" })).not.toBeInTheDocument();
    expect(screen.getByText("Beta saved question")).toBeInTheDocument();
  });
  it("keeps URL selection usable when browser focus storage is unavailable", async () => {
    const getItem = Storage.prototype.getItem; const setItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(function (this: Storage, key) {
      if (this === sessionStorage) throw new Error("blocked"); return getItem.call(this, key);
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (this === sessionStorage) throw new Error("blocked"); return setItem.call(this, key, value);
    });
    const user = userEvent.setup(); const view = await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 3: Gamma" })); focused("Gamma");
    expect(new URL(location.href).searchParams.get("focus")).toBe(ids[2]);
    expect(screen.getByRole("status")).toHaveTextContent(/selection cannot be remembered/);
    view.unmount(); history.replaceState(null, "", "/workspace/library?view=notes"); await mount(); focused("Beta");
  });
  it("blocks view, quick add and import while a reading write is pending", async () => {
    const user = userEvent.setup(); await mount(); await openImport(user);
    const gate: { resolve?: (response: Response) => void; paths: string[] } = { paths: [] };
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = new URL(String(url), "http://localhost").pathname; gate.paths.push(path);
      if (path.endsWith("/reading")) return new Promise<Response>((resolve) => { gate.resolve = resolve; });
      throw new Error(`Unexpected mutation: ${path}`);
    });
    await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    expect(screen.getByRole("combobox", { name: "Library view" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save source link" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preview browser import" })).toBeDisabled();
    const form = screen.getByRole("textbox", { name: "Save an arXiv ID, DOI or source URL" }).closest("form");
    if (!form) throw new Error("Quick add form missing");
    fireEvent.submit(form); expect(gate.paths).toHaveLength(1);
    const complete = gate.resolve; if (!complete) throw new Error("Reading request missing");
    await act(async () => complete(Response.json({ ...current.works[1]!.reading, status: "saved", revision: 2 })));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Library view" })).toBeEnabled());
  });
  it("blocks reading, view and quick add while import preview is pending", async () => {
    const user = userEvent.setup(); await mount(); await openImport(user); localStorage.setItem(PREVIEW_KEY, JSON.stringify(INITIAL_DATA));
    const gate: { resolve?: (response: Response) => void; paths: string[] } = { paths: [] };
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = new URL(String(url), "http://localhost").pathname; gate.paths.push(path);
      if (path.endsWith("/import/preview")) return new Promise<Response>((resolve) => { gate.resolve = resolve; });
      throw new Error(`Unexpected mutation: ${path}`);
    });
    await user.click(screen.getByRole("button", { name: "Preview browser import" }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    expect(screen.getByRole("combobox", { name: "Library view" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save source link" })).toBeDisabled();
    fireEvent.keyDown(document.body, { key: "s" }); expect(gate.paths).toHaveLength(1);
    const complete = gate.resolve; if (!complete) throw new Error("Preview request missing");
    await act(async () => complete(Response.json({ digest: "preview-digest", entries_new: 1, entries_existing: 0, conflicts: [], profile_will_change: false, original_retained: true })));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Library view" })).toBeEnabled());
  });
  it("guards mobile queue and view selection while a reading write is pending", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); render(<WorkspaceShell><LiveLibrary /></WorkspaceShell>);
    await screen.findByRole("button", { name: /^Save Beta/ });
    const gate: { resolve?: (response: Response) => void } = {};
    vi.mocked(fetch).mockImplementation(async () => new Promise<Response>((resolve) => { gate.resolve = resolve; }));
    await user.click(screen.getByRole("button", { name: /^Save Beta/ }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    expect(screen.getByRole("combobox", { name: "Library view" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 3: Gamma" }));
    expect(document.querySelector("article.daily-item h3")).toHaveTextContent("Beta");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    const complete = gate.resolve; if (!complete) throw new Error("Reading request missing");
    await act(async () => complete(Response.json({ ...current.works[1]!.reading, status: "saved", revision: 2 })));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Library view" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 3: Gamma" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); focused("Gamma");
  });
  it("holds a quick-add draft through a pending request and submits only once", async () => {
    const user = userEvent.setup(); await mount(); await openImport(user);
    const input = screen.getByRole("textbox", { name: "Save an arXiv ID, DOI or source URL" });
    const gate: { resolve?: (response: Response) => void; count: number } = { count: 0 };
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = new URL(String(url), "http://localhost").pathname;
      if (path.endsWith("/state")) return Response.json(current);
      if (path.endsWith("/manual")) { gate.count++; return new Promise<Response>((resolve) => { gate.resolve = resolve; }); }
      throw new Error(`Unexpected request: ${path}`);
    });
    await user.type(input, "https://example.org/source");
    const form = input.closest("form"); if (!form) throw new Error("Quick add form missing");
    await user.click(screen.getByRole("button", { name: "Save source link" }));
    await waitFor(() => expect(gate.resolve).toBeDefined());
    expect(input).toHaveAttribute("readonly"); expect(input).toHaveValue("https://example.org/source");
    expect(screen.getByRole("button", { name: "Saving source…" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Library view" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Save Beta/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Preview browser import" })).toBeDisabled();
    fireEvent.keyDown(document.body, { key: "s" });
    fireEvent.submit(form); expect(gate.count).toBe(1);
    const complete = gate.resolve; if (!complete) throw new Error("Pending manual request missing");
    await act(async () => complete(Response.json(work({ title: "Manual source", access_state: "metadata" }))));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(screen.getByRole("status")).toHaveTextContent("Access remains metadata");
  });
  it("retains pasted import and its preview across closing, without applying until confirmation", async () => {
    const user = userEvent.setup(); await mount();
    expect(calls.some(({ path }) => path.startsWith("import/"))).toBe(false);
    await openImport(user);
    await user.click(screen.getByText("Import an export from a different preview address"));
    const input = screen.getByRole("textbox", { name: "Or paste exported preview JSON" });
    const original = JSON.stringify(INITIAL_DATA);
    fireEvent.change(input, { target: { value: original } });
    expect(calls.some(({ path }) => path.startsWith("import/"))).toBe(false);
    await user.click(screen.getByRole("button", { name: "Preview exported JSON" }));
    expect(calls.filter(({ path }) => path === "import/preview")).toHaveLength(1);
    expect(calls.some(({ path }) => path === "import/apply")).toBe(false);
    await user.click(screen.getByText("Import preview notes", { selector: "summary" }));
    await user.click(screen.getByText("Import preview notes", { selector: "summary" }));
    expect(screen.getByRole("textbox", { name: "Or paste exported preview JSON" })).toHaveValue(original);
    expect(screen.getByText("1 new notes/questions/actions")).toBeInTheDocument();
    expect(calls.filter(({ path }) => path === "import/preview")).toHaveLength(1);
    expect(calls.some(({ path }) => path === "import/apply")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm import" }));
    expect(calls.filter(({ path }) => path === "import/apply")).toHaveLength(1);
  });
  it("retains quick add failure, explicit preview import and a single export link", async () => {
    const user = userEvent.setup(); await mount(); failManual = true;
    const input = screen.getByRole("textbox", { name: "Save an arXiv ID, DOI or source URL" });
    await user.type(input, "https://example.org/source"); await user.click(screen.getByRole("button", { name: "Save source link" }));
    expect(input).toHaveValue("https://example.org/source");
    failManual = false; await user.click(screen.getByRole("button", { name: "Save source link" }));
    await waitFor(() => expect(input).toHaveValue(""));
    expect(calls.find(({ path }) => path === "manual")?.body.value).toBe("https://example.org/source");
    const original = JSON.stringify(INITIAL_DATA); localStorage.setItem(PREVIEW_KEY, original);
    await openImport(user);
    await user.click(screen.getByRole("button", { name: "Preview browser import" }));
    expect(calls.some(({ path }) => path === "import/preview")).toBe(true);
    expect(calls.some(({ path }) => path === "import/apply")).toBe(false);
    expect(localStorage.getItem(PREVIEW_KEY)).toBe(original);
    await user.click(screen.getByRole("button", { name: "Confirm import" }));
    expect(calls.find(({ path }) => path === "import/apply")?.body.digest).toBe("preview-digest");
    expect(localStorage.getItem(PREVIEW_KEY)).toBe(original);
    expect(screen.getAllByRole("link", { name: /Export notes as Markdown/ })).toHaveLength(1);
  });
});
