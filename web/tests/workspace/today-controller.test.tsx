import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { FocusPaper } from "@/components/workspace/FocusPaper";
import { QueueList } from "@/components/workspace/Queue";
import { PlayerBar } from "@/components/workspace/PlayerBar";
import { SyntheticPreviewProvider } from "@/components/workspace/PreviewContext";
import { available } from "./materialFixtures";
import { LiveToday } from "@/components/workspace/Today";
import type { ReadingData, WorkspaceState } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({
  usePathname: () => "/workspace/today",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const titles = ["Alpha paper", "Beta paper", "Gamma paper", "Delta paper"];
const ids = titles.map((_, i) => `arxiv:2610.0000${i + 1}`);
const longAbstract = "A detailed abstract about a bounded research result. ".repeat(9);
function fixture(): WorkspaceState {
  const works = titles.map((title, i) => {
    const id = ids[i]!;
    return work({
      work_id: id, version_id: `${id}:v2`, title,
      url: `https://arxiv.org/abs/2610.0000${i + 1}v2`,
      abstract: `${title}: ${longAbstract}`,
      versions: [{
        ...work().versions[1]!, version_id: `${id}:v2`, version_label: "v2",
        title, abstract: `${title}: ${longAbstract}`,
        url: `https://arxiv.org/abs/2610.0000${i + 1}v2`,
      }],
    });
  });
  const edition = workspace().editions[0]!;
  return workspace({ works, editions: [{ ...edition, work_ids: ids, work_versions: {} }] });
}

let current: WorkspaceState;
let calls: Record<string, unknown>[];
let failReading: boolean;
beforeEach(() => {
  current = fixture(); calls = []; failReading = false;
  localStorage.clear(); sessionStorage.clear();
  history.replaceState(null, "", "/workspace/today");
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    media: query, matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
  })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    if (path === "state") return Response.json(current);
    if (path === "reading") {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      calls.push(body);
      if (failReading) return new Response(null, { status: 503 });
      const item = current.works.find((entry) => entry.work_id === body.work_id);
      if (!item) throw new Error("Unexpected work ID");
      item.reading = { ...item.reading, ...(body.data as ReadingData), revision: item.reading.revision + 1 };
      return Response.json(item.reading);
    }
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

async function mount() {
  const result = render(<WorkspaceShell><LiveToday /></WorkspaceShell>);
  await screen.findByRole("heading", { level: 1, name: /What changed/ });
  return result;
}
function focused(title: string) {
  const articles = screen.getAllByRole("article");
  expect(articles).toHaveLength(1);
  expect(within(articles[0]!).getByRole("heading", { level: 3 })).toHaveTextContent(title);
  return articles[0]!;
}
async function select(user: ReturnType<typeof userEvent.setup>, index: number) {
  await user.click(screen.getByRole("button", { name: `Show paper ${index + 1} of 4: ${titles[index]}` }));
}

describe("Today controller", () => {
  it("opens the frozen allocation receipt on demand without changing the focused paper or requesting a new edition", async () => {
    const user = userEvent.setup(); await mount();
    focused(titles[0]!);
    const summary = screen.getByText(/Edition details · 4 items/);
    expect(summary.closest("details")).not.toHaveAttribute("open");
    await user.click(summary);
    expect(await screen.findByText(/no recorded exploration allocation/)).toBeVisible();
    focused(titles[0]!); expect(calls).toHaveLength(0);
    await user.click(summary); expect(summary.closest("details")).not.toHaveAttribute("open");
  });
  it("keeps edition order in the queue and renders one focused article with its complete abstract once", async () => {
    await mount();
    const buttons = screen.getAllByRole("button", { name: /^Show paper \d of 4:/ });
    expect(buttons.map((button) => button.getAttribute("aria-label"))).toEqual(titles.map((title, i) => `Show paper ${i + 1} of 4: ${title}`));
    expect(buttons[0]).toHaveAttribute("aria-current", "true");
    const article = focused("Alpha paper");
    expect(within(article).getByRole("heading", { level: 3 }).querySelector("a")).not.toBeNull();
    expect(within(article).getByText(`Alpha paper: ${longAbstract.trim()}`)).toBeInTheDocument();
    expect(screen.getAllByText(`Alpha paper: ${longAbstract.trim()}`)).toHaveLength(1);
    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("navigates buttons and j/k without wrapping and respects editable, native and disabled controls", async () => {
    const user = userEvent.setup(); await mount();
    expect(screen.getByRole("button", { name: "Previous paper" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next paper" })); focused("Beta paper");
    fireEvent.keyDown(document.body, { key: "j" }); focused("Gamma paper");
    fireEvent.keyDown(document.body, { key: "k" }); focused("Beta paper");
    const field = screen.getByRole("searchbox", { name: "Search stored papers" });
    fireEvent.keyDown(field, { key: "j" }); focused("Beta paper");
    const next = screen.getByRole("button", { name: "Next paper" });
    fireEvent.keyDown(next, { key: "Enter" }); focused("Beta paper");
    await select(user, 3); focused("Delta paper");
    expect(screen.getByRole("button", { name: "Next paper" })).toBeDisabled();
    fireEvent.keyDown(document.body, { key: "j" }); focused("Delta paper");
  });

  it("uses focus in the URL, retains it on remount, handles unknown IDs and follows browser back and forward", async () => {
    history.replaceState(null, "", `/workspace/today?keep=yes&focus=${encodeURIComponent(ids[1]!)}`);
    const user = userEvent.setup(); const view = await mount(); focused("Beta paper");
    await select(user, 2); focused("Gamma paper");
    expect(new URL(location.href).searchParams.get("focus")).toBe(ids[2]);
    expect(new URL(location.href).searchParams.get("keep")).toBe("yes");
    view.unmount(); await mount(); focused("Gamma paper");
    act(() => { history.pushState(null, "", `/workspace/today?focus=${encodeURIComponent(ids[3]!)}`); window.dispatchEvent(new PopStateEvent("popstate")); });
    focused("Delta paper");
    act(() => { history.back(); }); await waitFor(() => focused("Gamma paper"));
    act(() => { history.forward(); }); await waitFor(() => focused("Delta paper"));
    act(() => { history.pushState(null, "", "/workspace/today?focus=unknown"); window.dispatchEvent(new PopStateEvent("popstate")); });
    focused("Alpha paper");
    act(() => { history.pushState(null, "", "/workspace/today"); window.dispatchEvent(new PopStateEvent("popstate")); });
    focused("Alpha paper");
  });

  it("keeps the edition version, saved anchor and focused return URL in the reader link; pinned activity retains its own source", async () => {
    const item = current.works[1]!;
    const oldVersion = { ...item.versions[0]!, version_id: `${item.work_id}:v1`, version_label: "v1", title: "Beta earlier version", abstract: "Earlier beta abstract." };
    item.versions.unshift(oldVersion);
    item.reading = { ...item.reading, revision: 2, version_id: oldVersion.version_id, anchor: "abstract:7" };
    current.editions[0]!.work_versions[item.work_id] = oldVersion.version_id;
    current.profile.data.pinned_entry_id = "entry-beta";
    current.latest_activity = { sequence: 1, kind: "entry", entry_id: "entry-beta", entry_kind: "question", body: "Pinned question", work_id: item.work_id, version_id: oldVersion.version_id, anchor: "abstract:7", revision: 2, updated_at: "2026-11-02T15:00:00Z" };
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 4: Beta earlier version" }));
    const article = focused("Beta earlier version");
    const href = within(article).getByRole("heading", { level: 3 }).querySelector("a")?.getAttribute("href");
    expect(href).toBe(`/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(oldVersion.version_id)}&return_to=${encodeURIComponent(`/workspace/today?focus=${encodeURIComponent(item.work_id)}`)}#abstract%3A7`);
    const pinned = screen.getByRole("link", { name: "Beta earlier version →" });
    expect(pinned.getAttribute("href")).toBe(`/workspace/items/${encodeURIComponent(item.work_id)}?version=${encodeURIComponent(oldVersion.version_id)}&entry=entry-beta&return_to=%2Fworkspace%2Ftoday#abstract%3A7`);
    expect(screen.getByText("Pinned question")).toBeInTheDocument();
  });

  it("shows the edition-pinned abstract instead of newer saved reading material", async () => {
    const item = current.works[1]!;
    const earlier = { ...item.versions[0]!, version_id: `${item.work_id}:v1`, version_label: "v1", title: "Beta earlier version", abstract: "The original beta abstract remains intact." };
    item.versions.unshift(earlier);
    item.reading = { ...item.reading, revision: 2, version_id: item.version_id, anchor: "abstract:9" };
    current.editions[0]!.work_versions[item.work_id] = earlier.version_id;
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 4: Beta earlier version" }));
    const article = focused("Beta earlier version");
    expect(within(article).getByText("The original beta abstract remains intact.")).toBeInTheDocument();
    expect(within(article).queryByText(`Beta paper: ${longAbstract.trim()}`)).not.toBeInTheDocument();
    const href = within(article).getByRole("heading", { level: 3 }).querySelector("a")?.getAttribute("href");
    expect(href).toContain(`version=${encodeURIComponent(earlier.version_id)}`);
    expect(href).toContain("#abstract%3A0");
    expect(href).not.toContain("abstract%3A9");
  });

  it("omits an unavailable pinned version rather than substituting the newer paper", async () => {
    current.editions[0]!.work_versions[ids[1]!] = `${ids[1]}:missing`;
    await mount();
    expect(screen.getAllByRole("button", { name: /^Show paper \d of 3:/ })).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /Show paper .*Beta paper/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Some source versions retained by this edition are unavailable/)).toBeInTheDocument();
    focused("Alpha paper");
    expect(screen.queryByText(`Beta paper: ${longAbstract.trim()}`)).not.toBeInTheDocument();
  });

  it("closes the mobile drawer after queue selection and restores focus to the selected paper", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      media: query, matches: query.includes("767"), addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
    })));
    const scroll = vi.fn(); vi.stubGlobal("scrollIntoView", scroll);
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(screen.getByRole("button", { name: "Show paper 2 of 4: Beta paper" }));
    expect(screen.queryByRole("dialog", { name: "Queue & controls" })).not.toBeInTheDocument();
    focused("Beta paper");
    expect(new URL(location.href).searchParams.get("focus")).toBe(ids[1]);
  });

  it("keeps synthetic preview source checks disabled with a clear explanation", async () => {
    render(<SyntheticPreviewProvider enabled><WorkspaceShell><LiveToday /></WorkspaceShell></SyntheticPreviewProvider>);
    await screen.findByRole("heading", { level: 1, name: /What changed/ });
    await userEvent.setup().click(screen.getByText(/Sample source checks:/));
    expect(screen.getByRole("button", { name: "Check sources now" })).toBeDisabled();
    expect(screen.getByText(/Live source checks are disabled in this synthetic design preview/)).toBeInTheDocument();
  });

  it.each([
    ["not_checked", false, "0/1 sources · limited"],
    ["error", false, "0/1 sources · failed"],
    ["ok", true, "1/1 sources · limited"],
  ])("labels %s source results honestly in the header", async (status, truncated, header) => {
    current.editions[0]!.coverage = [{ ...current.sources[0]!, status, receipt: { truncated } }];
    current.profile.data.research_question = "";
    await mount();
    expect(screen.getByText(header)).toBeInTheDocument();
    expect(screen.getByText("Add your current research question in Interests.")).toBeInTheDocument();
  });

  it("omits a source count when no checks exist", async () => {
    current.editions[0]!.coverage = [];
    await mount();
    expect(screen.queryByText(/\d+\/\d+ sources/)).not.toBeInTheDocument();
  });

  it("does not activate a page command while its main region is inert behind the mobile drawer", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      media: query, matches: query.includes("767"), addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(), onchange: null,
    })));
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    expect(document.querySelector("main")).toHaveAttribute("inert");
    fireEvent.keyDown(document.body, { key: "j" });
    expect(new URL(location.href).searchParams.get("focus")).not.toBe(ids[1]);
    expect(calls).toHaveLength(0);
  });

  it.each(["Dismiss", "Snooze one day"])("advances on %s and uses the previous item when removing the last", async (label) => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: new RegExp(`^${label} Alpha paper`) }));
    await waitFor(() => focused("Beta paper"));
    await user.click(screen.getByRole("button", { name: "Show paper 3 of 3: Delta paper" }));
    await user.click(screen.getByRole("button", { name: new RegExp(`^${label} Delta paper`) }));
    await waitFor(() => focused("Gamma paper"));
  });

  it("keeps mutations disabled during a pending save while allowing navigation, then applies the server response", async () => {
    const item = current.works[0]!;
    current.latest_activity = { sequence: 1, kind: "entry", entry_id: "entry-alpha", entry_kind: "question", body: "Saved question", work_id: item.work_id, version_id: item.version_id, anchor: "abstract:0", revision: 1, updated_at: "2026-11-02T15:00:00Z" };
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByText("Source and pin options"));
    await user.click(screen.getByText(/Source checks:/));
    const requests: { path: string; body: Record<string, unknown> }[] = [];
    const pending: { release?: (response: Response) => void } = {};
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const path = new URL(String(url), "http://localhost").pathname.replace("/api/workspace/", "");
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
      requests.push({ path, body });
      if (path !== "reading") throw new Error(`Unexpected mutation: ${path}`);
      return new Promise<Response>((resolve) => { pending.release = resolve; });
    });
    await user.click(screen.getByRole("button", { name: /^Save Alpha paper/ }));
    await waitFor(() => expect(requests).toHaveLength(1));
    expect(screen.getByRole("button", { name: /^Save Alpha paper/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Dismiss Alpha paper/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Snooze one day Alpha paper/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pin this question" })).toBeDisabled();
    for (const minutes of [5, 15, 45]) expect(screen.getByRole("button", { name: `${minutes} min` })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Check sources now" })).toBeDisabled();
    expect(screen.getByRole("status")).not.toHaveTextContent("Saved on the server");
    await user.click(screen.getByRole("button", { name: /^Save Alpha paper/ }));
    fireEvent.keyDown(document.body, { key: "s" });
    expect(requests).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Next paper" }));
    focused("Beta paper");
    expect(screen.getByRole("button", { name: /^Save Beta paper/ })).toBeDisabled();
    fireEvent.keyDown(document.body, { key: "s" });
    expect(requests).toHaveLength(1);
    const data = requests[0]?.body.data as ReadingData;
    const complete = pending.release;
    if (!complete) throw new Error("Pending reading request was not captured");
    await act(async () => complete(Response.json({ ...item.reading, ...data, revision: 7 })));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Saved on the server: saved"));
    expect(screen.getByRole("button", { name: /^Save Beta paper/ })).toBeEnabled();
    await select(user, 0);
    expect(screen.getByRole("button", { name: /^Unsave Alpha paper/ })).toHaveAttribute("aria-pressed", "true");
    expect(requests).toHaveLength(1);
  });

  it("retains focus and request identity after a failed write; retry advances only after success", async () => {
    const user = userEvent.setup(); await mount(); failReading = true;
    await user.click(screen.getByRole("button", { name: /^Dismiss Alpha paper/ }));
    await waitFor(() => expect(calls).toHaveLength(1)); focused("Alpha paper");
    expect(screen.getByRole("status")).not.toHaveTextContent("Saved on the server");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Dismiss Alpha paper/ })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /^Dismiss Alpha paper/ }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]?.request_id).toBe(calls[0]?.request_id); focused("Alpha paper");
    await waitFor(() => expect(screen.getByRole("button", { name: /^Dismiss Alpha paper/ })).toBeEnabled());
    failReading = false;
    await user.click(screen.getByRole("button", { name: /^Dismiss Alpha paper/ }));
    await waitFor(() => focused("Beta paper"));
    expect(calls[2]?.request_id).toBe(calls[0]?.request_id);
  });

  it("returns to the removed paper on successful Undo after navigation, and keeps the selected paper when Undo fails", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: /^Dismiss Alpha paper/ }));
    await waitFor(() => focused("Beta paper"));
    await user.click(screen.getByRole("button", { name: "Show paper 3 of 3: Delta paper" }));
    failReading = true; await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => expect(calls).toHaveLength(2)); focused("Delta paper");
    await waitFor(() => expect(screen.getByRole("button", { name: "Undo last change" })).toBeEnabled());
    failReading = false; await user.click(screen.getByRole("button", { name: "Undo last change" }));
    await waitFor(() => focused("Alpha paper"));
    expect(calls[2]?.request_id).toBe(calls[1]?.request_id);
  });
});


describe("source scope presentation", () => {
  it("does not attribute newer authors to an older retained source with no author list", () => {
    const item = work({ authors: ["Newer version author"] });
    item.versions[0]!.authors = [];
    render(<FocusPaper item={item} versionId={item.versions[0]!.version_id} href="/reader" />);
    const article = screen.getByRole("article");
    expect(within(article).getByRole("heading", { level: 3 })).toHaveTextContent("An earlier controlled retrieval study");
    expect(within(article).getByText("Authors not recorded for this source version")).toBeInTheDocument();
    expect(within(article).queryByText("Newer version author")).not.toBeInTheDocument();
  });
  it.each([
    ["complete PDF", "full_text", true, "PDF text", "Retained PDF text is ready", "Retained PDF text;"],
    ["partial PDF", "excerpt", false, "PDF excerpts", "Retained PDF excerpts are ready", "Selected original PDF pages;"],
  ] as const)("distinguishes %s in the paper and queue", (_label, scope, complete, chip, fallback, evidence) => {
    const item = work({ abstract: "", available_scopes: [scope], retained_materials: [available({ scope, complete })] });
    render(<><FocusPaper item={item} href="/reader" /><QueueList items={[item]} focusId={item.work_id} onSelect={vi.fn()} /></>);
    expect(screen.getByText(chip)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(fallback))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(evidence))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show paper 1 of 1/ })).toHaveTextContent(chip);
  });

  it.each([
    ["excerpt", "The publisher’s feed excerpt; the complete article has not been acquired."],
    ["metadata", "Metadata and the original link. Check access at the source."],
  ] as const)("states the %s boundary when no abstract is present", (scope, evidence) => {
    const item = work({ abstract: "", available_scopes: [scope], authors: [], published_at: null, reasons: [] });
    item.versions[1]!.authors = []; item.versions[1]!.title = "";
    item.reading = { ...item.reading, status: "saved", version_id: item.versions[0]!.version_id };
    render(<><FocusPaper item={item} versionId={item.version_id} href="/reader" />
      <QueueList items={[item]} focusId={null} onSelect={vi.fn()} />
      <PlayerBar item={item} href="/reader" index={0} count={1} /></>);
    expect(screen.getByRole("heading", { level: 3, name: item.title })).toBeInTheDocument();
    expect(screen.getByText("Authors not recorded for this source version")).toBeInTheDocument();
    expect(screen.getByText(/Publication date unknown/)).toHaveTextContent(item.source_id);
    expect(screen.getByText(/Publication date unknown/)).toBeInTheDocument();
    expect(screen.getByText(/No abstract or full text was acquired/)).toBeInTheDocument();
    expect(screen.getByText(/No personal match has been inferred/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(evidence.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show paper 1 of 1/ })).toHaveTextContent("saved");
  });

  it("warns when resuming an older saved source version", () => {
    const item = work(); item.reading = { ...item.reading, revision: 1, status: "read", version_id: item.versions[0]!.version_id };
    render(<FocusPaper item={item} href="/reader" />);
    expect(screen.getByText(/Opening this item resumes your saved version/)).toBeInTheDocument();
  });
});
