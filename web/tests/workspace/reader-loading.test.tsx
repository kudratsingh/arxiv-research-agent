import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveReader } from "@/components/workspace/Reader";
import type { ReaderContentComponent } from "@/lib/workspace/readerModule";
import type { WorkspaceState } from "@/lib/workspace/api";
import { loadDraft, storeDraft } from "@/lib/workspace/drafts";
import { work, workspace } from "./fixtures";

const loader = vi.hoisted(() => ({ peek: vi.fn(), load: vi.fn() }));
vi.mock("@/lib/workspace/readerModule", () => ({ readerModule: loader }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(location.search) }));
let data: WorkspaceState | null;
const reload = vi.fn(), setState = vi.fn();
vi.mock("@/lib/workspace/useWorkspace", () => ({ useWorkspace: () => ({ state: data, error: "", reload, setState }) }));

const Loaded: ReaderContentComponent = ({ item, requestedVersion, requestedEntry }) => <section>
  <h1>Loaded retained reader</h1>
  <p data-testid="forwarded">{item.work_id}|{requestedVersion}|{requestedEntry}|{location.hash}</p>
  <textarea aria-label="Retained draft" />
</section>;
function pendingContent() {
  let resolve!: (component: ReaderContentComponent) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<ReaderContentComponent>((accept, refuse) => { resolve = accept; reject = refuse; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  data = workspace(); loader.peek.mockReset().mockReturnValue(null); loader.load.mockReset(); reload.mockReset(); setState.mockReset(); localStorage.clear();
  history.replaceState(null, "", `/workspace/items/${encodeURIComponent(work().work_id)}?version=${encodeURIComponent(work().version_id)}#abstract:0`);
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("bounded retained Reader module loading", () => {
  it("deduplicates an inflight import and caches only the resolved component", async () => {
    const { createReaderModuleLoader } = await vi.importActual<typeof import("@/lib/workspace/readerModule")>("@/lib/workspace/readerModule");
    let finish!: (module: { default: ReaderContentComponent }) => void;
    const importer = vi.fn(() => new Promise<{ default: ReaderContentComponent }>(resolve => { finish = resolve; }));
    const cache = createReaderModuleLoader(importer);
    expect(cache.peek()).toBeNull(); const first = cache.load(), second = cache.load();
    expect(first).toBe(second); expect(importer).toHaveBeenCalledOnce();
    finish({ default: Loaded }); expect(await first).toBe(Loaded); expect(cache.peek()).toBe(Loaded);
    expect(await cache.load()).toBe(Loaded); expect(importer).toHaveBeenCalledOnce();
  });

  it("clears a rejected import so an explicit retry can acquire the module", async () => {
    const { createReaderModuleLoader } = await vi.importActual<typeof import("@/lib/workspace/readerModule")>("@/lib/workspace/readerModule");
    const importer = vi.fn().mockRejectedValueOnce(new Error("chunk unavailable")).mockResolvedValueOnce({ default: Loaded });
    const cache = createReaderModuleLoader(importer);
    await expect(cache.load()).rejects.toThrow("chunk unavailable"); expect(cache.peek()).toBeNull();
    expect(await cache.load()).toBe(Loaded); expect(importer).toHaveBeenCalledTimes(2);
  });

  it("skips the editor import without real item data and reuses cached code when available", () => {
    data = null; const view = render(<LiveReader id={work().work_id} />);
    expect(document.querySelector('[aria-busy="true"]')).toBeInTheDocument(); expect(loader.load).not.toHaveBeenCalled();
    data = workspace({ works: [] }); view.rerender(<LiveReader id={work().work_id} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("This source is not in the loaded workspace.");
    expect(loader.load).not.toHaveBeenCalled(); view.unmount();
    data = workspace(); loader.peek.mockReturnValue(Loaded); render(<LiveReader id={work().work_id} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Loaded retained reader"); expect(loader.load).not.toHaveBeenCalled();
  });

  it("shows a busy view, forwards the latest exact target after loading, and retains the mounted editor across hashes", async () => {
    const pending = pendingContent(); loader.load.mockReturnValue(pending.promise);
    const view = render(<LiveReader id={work().work_id} />);
    expect(screen.getByText("Opening the retained source reader…")).toHaveAttribute("aria-busy", "true");
    const other = work({ work_id: "arxiv:2611.99999", version_id: "arxiv:2611.99999:v3" }); data = workspace({ works: [other] });
    history.replaceState(null, "", `/workspace/items/${encodeURIComponent(other.work_id)}?version=${encodeURIComponent(other.version_id)}&entry=exact-entry#abstract:10:20`);
    view.rerender(<LiveReader id={other.work_id} />);
    await act(async () => pending.resolve(Loaded));
    expect(screen.getByTestId("forwarded")).toHaveTextContent(`${other.work_id}|${other.version_id}|exact-entry|#abstract:10:20`);
    const textarea = screen.getByRole("textbox", { name: "Retained draft" }); fireEvent.change(textarea, { target: { value: "Keep this draft" } });
    history.replaceState(null, "", `${location.pathname}${location.search}#notes`); view.rerender(<LiveReader id={other.work_id} />);
    expect(screen.getByRole("textbox", { name: "Retained draft" })).toBe(textarea); expect(textarea).toHaveValue("Keep this draft");
    expect(reload).not.toHaveBeenCalled(); expect(setState).not.toHaveBeenCalled();
  });

  it("reports chunk failure visibly and retries code only after the explicit retry action", async () => {
    const pending = pendingContent(); loader.load.mockRejectedValueOnce(new Error("chunk unavailable")).mockReturnValueOnce(pending.promise);
    render(<LiveReader id={work().work_id} />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("This source view could not be opened.");
    expect(screen.getByText("Your source and saved notes are unchanged. Retry to open this exact source version.")).toBeInTheDocument();
    expect(loader.load).toHaveBeenCalledOnce(); await userEvent.click(screen.getByRole("button", { name: "Retry source view" }));
    expect(screen.getByText("Opening the retained source reader…")).toHaveAttribute("aria-busy", "true"); expect(loader.load).toHaveBeenCalledTimes(2);
    await act(async () => pending.resolve(Loaded)); expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Loaded retained reader");
    expect(reload).not.toHaveBeenCalled(); expect(setState).not.toHaveBeenCalled();
  });

  it("clears an earlier import error when a new exact version loads, retaining its real draft and latest passage without writes", async () => {
    const pending = pendingContent(); loader.load.mockRejectedValueOnce(new Error("first chunk failed")).mockReturnValueOnce(pending.promise);
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const item = data!.works[0]!, version = item.versions[0]!;
    const draft = { id: "retained-version-draft", revision: 0, kind: "question" as const, body: "Keep this older source question", anchor: "abstract:1:5" };
    storeDraft(data!.principal_key_id, item.work_id, version.version_id, draft);
    const view = render(<LiveReader id={item.work_id} />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("This source view could not be opened.");
    history.replaceState(null, "", `${location.pathname}?version=${encodeURIComponent(version.version_id)}#abstract:3:8`);
    view.rerender(<LiveReader id={item.work_id} />);
    await waitFor(() => expect(loader.load).toHaveBeenCalledTimes(2));
    const actual = await vi.importActual<typeof import("@/components/workspace/ReaderContent")>("@/components/workspace/ReaderContent");
    await act(async () => pending.resolve(actual.default));
    expect(screen.queryByText("This source view could not be opened.")).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your question" })).toHaveValue(draft.body);
    expect(loadDraft(data!.principal_key_id, item.work_id, version.version_id)).toEqual(draft);
    expect(document.getElementById("source-anchor")?.textContent).toBe(Array.from(version.abstract).slice(3, 8).join(""));
    expect(new URLSearchParams(location.search).get("version")).toBe(version.version_id);
    expect(fetcher).not.toHaveBeenCalled(); expect(reload).not.toHaveBeenCalled(); expect(setState).not.toHaveBeenCalled();
  });

  it.each(["resolve", "reject"] as const)("ignores a delayed %s after unmount", async outcome => {
    const pending = pendingContent(); loader.load.mockReturnValue(pending.promise); const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const view = render(<LiveReader id={work().work_id} />); await waitFor(() => expect(loader.load).toHaveBeenCalledOnce()); view.unmount();
    await act(async () => { if (outcome === "resolve") pending.resolve(Loaded); else pending.reject(new Error("late chunk failure")); });
    expect(screen.queryByRole("heading")).not.toBeInTheDocument(); expect(errors).not.toHaveBeenCalled();
  });
});
