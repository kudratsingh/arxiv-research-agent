import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { navigationState, navigateWorkspace, NAVIGATION_INTENT_KEY, requestPaperNavigation, requestWorkspaceNavigation, settleReaderTarget, settleWorkspaceContent, useWorkspaceNavigation } from "@/lib/workspace/navigation";
import { blockWorkspaceNavigation } from "@/lib/workspace/navigationGuard";

let frames: Map<number, FrameRequestCallback>;
let frameId: number;
let mobile: boolean;
let reduced: boolean;
let animate: ReturnType<typeof vi.fn>;
let cancelAnimation: ReturnType<typeof vi.fn>;
let order: string[];
let navigationGuards: (() => void)[];
function Paper({ id }: { id: string }) {
  return <article data-paper-key={id} className="ws-focus" data-paper-announcement={`Paper 2 of 4: ${id}`}><div className="ws-focus-heading" data-top="260"><h3>{id}</h3></div><p>{"Long actual abstract text. ".repeat(300)}</p></article>;
}
function Harness({ id = "Alpha", path = "/workspace/today", ready = true, paper = true }: { id?: string; path?: string; ready?: boolean; paper?: boolean }) {
  useWorkspaceNavigation(path);
  return <div className="ws-app" data-workspace-path={path}><a href="/workspace/library" data-testid="route">Library</a><span data-testid="announcement" data-workspace-announcement="" aria-live="polite" />
    <main className="ws-stage" id="main" data-top="40"><div className={`ws-${path.split("/")[2]}`}>{ready && <h1 data-top="120">Route heading</h1>}{ready && paper && <Paper id={id} />}</div>
      <section id="notes" tabIndex={-1} data-top="700">Exact saved entry</section><button>Next paper</button>
      <form className="ws-composer"><input name="q" defaultValue="memory" /></form>
    </main></div>;
}
function main() { return document.querySelector<HTMLElement>("main.ws-stage")!; }
function wireScroll() {
  const container = main(); container.scrollTop = 900;
  Object.defineProperty(container, "scrollTo", { configurable: true, value: vi.fn((options: ScrollToOptions) => { order.push("scroll"); container.scrollTop = options.top ?? 0; }) });
  return container;
}
async function flush() {
  await act(async () => { await import("@/lib/workspace/navigationRuntime"); });
  await act(async () => { const pending = [...frames.values()]; frames.clear(); pending.forEach((callback) => callback(0)); await Promise.resolve(); });
}
beforeEach(() => {
  frames = new Map(); frameId = 0; mobile = false; reduced = false; order = []; navigationGuards = [];
  history.replaceState(null, "", "/workspace/today"); sessionStorage.clear();
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId; }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn((id: number) => { frames.delete(id); }));
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ matches: query.includes("reduced-motion") ? reduced : mobile })));
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) { return { top: Number(this.dataset.top ?? 0), left: 0, bottom: 800, right: 390, width: 390, height: 800, x: 0, y: 0, toJSON: () => ({}) }; });
  Object.defineProperty(window, "scrollY", { configurable: true, value: 500 });
  vi.spyOn(window, "scrollTo").mockImplementation(() => { order.push("document-scroll"); });
  cancelAnimation = vi.fn(); animate = vi.fn(() => { order.push("animate"); return { cancel: cancelAnimation }; });
  Object.defineProperty(HTMLElement.prototype, "animate", { configurable: true, value: animate });
});
afterEach(async () => {
  navigationGuards.forEach(release => release());
  // Complete any intent before removing the host, matching a committed route.
  if (navigationState.engine) settleWorkspaceContent(document.body);
  await flush(); await flush();
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});

describe("shared workspace navigation", () => {
  it("leaves early managed Search button clicks and submissions without checkpoints or intent when vetoed", async () => {
    render(<Harness />); const container = wireScroll();
    const form = container.querySelector<HTMLFormElement>(".ws-composer")!; form.dataset.guardedNavigation = "";
    const button = document.createElement("button"); button.type = "submit"; button.textContent = "Search"; form.append(button);
    form.addEventListener("submit", event => { event.preventDefault(); navigateWorkspace("/workspace/radar?q=private+early+query", "paper"); });
    const assign = vi.fn(); vi.stubGlobal("location", { ...window.location, assign }); const unblock = blockWorkspaceNavigation(vi.fn()); navigationGuards.push(unblock);
    expect(navigationState.engine).toBeNull(); history.replaceState({ __NA: true, retained: "metadata" }, "", location.href);
    fireEvent.click(button);
    expect(assign).not.toHaveBeenCalled(); expect(history.state).toEqual({ __NA: true, retained: "metadata" }); expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).toBeNull();
    await flush(); await flush(); expect(container.scrollTo).not.toHaveBeenCalled(); expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).toBeNull(); unblock();
  });
  it("records managed search intent and history only after the shared navigation veto succeeds", async () => {
    render(<Harness />); const container = wireScroll(); await flush();
    const assign = vi.fn(); vi.stubGlobal("location", { ...window.location, assign });
    const form = container.querySelector<HTMLFormElement>(".ws-composer")!; form.dataset.guardedNavigation = "";
    form.addEventListener("submit", event => { event.preventDefault(); navigateWorkspace("/workspace/radar?q=private+question&days=30&status=saved", "paper"); });
    history.replaceState({ __NA: true, workspaceScroll: 123 }, "", location.href); navigationState.readerHistory = true;
    const notify = vi.fn(), unblock = blockWorkspaceNavigation(notify); navigationGuards.push(unblock);
    fireEvent.submit(form); await flush();
    expect(assign).not.toHaveBeenCalled(); expect(notify).toHaveBeenCalledOnce(); expect(navigationState.readerHistory).toBe(true);
    expect(history.state).toEqual({ __NA: true, workspaceScroll: 123 }); expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).toBeNull();
    expect(container.scrollTo).not.toHaveBeenCalled();
    unblock(); fireEvent.submit(form);
    expect(assign).toHaveBeenCalledOnce(); expect(assign).toHaveBeenCalledWith("/workspace/radar?q=private+question&days=30&status=saved");
    expect(history.state).toMatchObject({ __NA: true, workspaceScroll: 900 });
    expect(JSON.parse(sessionStorage.getItem(NAVIGATION_INTENT_KEY)!)).toMatchObject({ kind: "paper", path: "/workspace/radar" });
    expect(sessionStorage.getItem(NAVIGATION_INTENT_KEY)).not.toContain("private");
  });
  it("positions a new paper header from a long abstract before a content-only 170ms transition, retaining player focus", async () => {
    const view = render(<Harness />); const container = wireScroll();
    const player = screen.getByRole("button", { name: "Next paper" }); player.focus();
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Beta" />);
    await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 1104, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled(); expect(player).toHaveFocus();
    await flush();
    expect(order).toEqual(["scroll", "animate"]);
    expect(animate).toHaveBeenCalledWith([{ opacity: .55, transform: "translateY(6px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 170, easing: "ease-out" });
    expect(animate.mock.instances[0]).toBe(document.querySelector("article"));
    expect(screen.getByTestId("announcement")).toHaveTextContent("Paper 2 of 4: Beta");
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("lets the final rapid selection win and cancels an active older animation", async () => {
    const view = render(<Harness />); const container = wireScroll();
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Beta" />); await flush(); await flush();
    expect(animate).toHaveBeenCalledTimes(1);
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Gamma" />);
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Delta" />);
    expect(cancelAnimation).toHaveBeenCalled();
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(2); expect(animate).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("announcement")).toHaveTextContent("Delta");
  });

  it("uses the mobile document and no motion for reduced-motion users", async () => {
    mobile = true; reduced = true; const view = render(<Harness />); const container = wireScroll();
    view.rerender(<Harness id="Beta" />); await flush(); await flush();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 744, behavior: "instant" });
    expect(container.scrollTo).not.toHaveBeenCalled(); expect(animate).not.toHaveBeenCalled();
  });

  it("checkpoints the real stage without losing Next metadata and restores history without motion or heading focus", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }); const view = render(<Harness />); const container = wireScroll(); await flush();
    history.replaceState({ __NA: true, tree: ["retained-router-state"] }, "", location.href);
    fireEvent.scroll(container); await act(async () => { vi.advanceTimersByTime(150); });
    expect(history.state).toEqual({ __NA: true, tree: ["retained-router-state"], workspaceScroll: 900 });
    act(() => { history.replaceState({ __NA: true, workspaceScroll: 321 }, "", "/workspace/today?focus=Beta"); window.dispatchEvent(new PopStateEvent("popstate", { state: history.state })); });
    view.rerender(<Harness id="Beta" />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 321, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled(); expect(screen.getByRole("heading", { level: 1 })).not.toHaveFocus();
    vi.mocked(container.scrollTo).mockClear();
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: null }))); await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
  });

  it("waits for the explicit route heading to exist and preserves Reader entry/anchor priority", async () => {
    const view = render(<Harness />); wireScroll();
    act(() => { requestWorkspaceNavigation("/workspace/library"); history.pushState({ __NA: true }, "", "/workspace/library"); });
    view.rerender(<Harness path="/workspace/library" ready={false} />); await flush(); expect(animate).not.toHaveBeenCalled();
    view.rerender(<Harness path="/workspace/library" paper={false} />); await flush(); await flush();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
    act(() => { requestWorkspaceNavigation("/workspace/items/example?entry=entry-1#abstract%3A2%3A8"); history.pushState({}, "", "/workspace/items/example?entry=entry-1#abstract%3A2%3A8"); });
    view.rerender(<Harness path="/workspace/items/example" paper={false} />);
    const entry = document.getElementById("notes")!;
    act(() => settleReaderTarget(entry)); await flush();
    expect(entry).toHaveFocus(); expect(animate).not.toHaveBeenCalled();
  });

  it("waits through a result-page loading gap and honors the latest paper intent when content arrives", async () => {
    const view = render(<Harness />); wireScroll();
    act(() => requestPaperNavigation()); view.rerender(<Harness ready={false} />); await flush();
    view.rerender(<Harness id="Page two result" />); wireScroll(); await flush(); await flush();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Page two result");
    expect(main().scrollTo).toHaveBeenCalledWith({ top: 1104, behavior: "instant" });
  });

  it("ignores disconnected obsolete targets, external destinations, and skips Reader auto-focus during history restoration", async () => {
    render(<Harness />); const container = wireScroll();
    const obsolete = document.createElement("h3"); settleWorkspaceContent(obsolete); await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    requestWorkspaceNavigation("https://example.org/workspace/library"); requestWorkspaceNavigation("/today"); await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 200 } })));
    const entry = document.getElementById("notes")!; settleReaderTarget(entry); expect(entry).not.toHaveFocus();
    settleReaderTarget(entry, true, true); expect(entry).toHaveFocus(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 1544, behavior: "instant" });
  });
  it("restores Reader return to the focused paper rather than the list introduction", async () => {
    history.replaceState({}, "", "/workspace/items/example?version=v1#abstract%3A0");
    const view = render(<Harness path="/workspace/items/example" paper={false} />); wireScroll();
    const route = screen.getByTestId("route");
    route.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(route);
    history.pushState({}, "", "/workspace/library?view=notes&focus=Gamma");
    view.rerender(<Harness path="/workspace/library" id="Gamma" />); wireScroll();
    await flush(); await flush();
    expect(main().scrollTo).toHaveBeenCalledWith({ top: 1104, behavior: "instant" });
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveFocus();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Gamma");
  });

  it("waits for the first ready result after composer search and ignores empty or slash commands", async () => {
    const view = render(<Harness />); wireScroll();
    const form = document.querySelector<HTMLFormElement>(".ws-composer")!;
    form.addEventListener("submit", (event) => event.preventDefault());
    const input = form.elements.namedItem("q") as HTMLInputElement;
    input.value = "/theme dark"; fireEvent.submit(form); await flush();
    expect(animate).not.toHaveBeenCalled();
    input.value = ""; fireEvent.submit(form); await flush(); expect(animate).not.toHaveBeenCalled();
    input.value = "retrieval"; fireEvent.submit(form);
    history.pushState({}, "", "/workspace/radar?q=retrieval");
    view.rerender(<Harness path="/workspace/radar" ready={false} />); await flush();
    view.rerender(<Harness path="/workspace/radar" id="Search result" />); wireScroll();
    await flush(); await flush();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Search result");
  });

  it("consumes a fresh explicit navigation after a full page load while ignoring stale storage", async () => {
    sessionStorage.setItem("arxiv.workspace.navigation-intent.v1", JSON.stringify({ kind: "route", path: "/workspace/today", at: Date.now() - 30_000 }));
    const stale = render(<Harness />); wireScroll(); await flush();
    expect(main().scrollTo).not.toHaveBeenCalled(); stale.unmount();
    sessionStorage.setItem("arxiv.workspace.navigation-intent.v1", JSON.stringify({ kind: "route", path: "/workspace/today", at: Date.now() }));
    render(<Harness />); wireScroll(); await flush();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
    expect(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")).toBeNull();
  });

  it("retains the final paper request while the deferred runtime is still loading", async () => {
    navigationState.engine = null;
    const view = render(<Harness />); const container = wireScroll();
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Queued Beta" />);
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Queued Delta" />);
    expect(container.scrollTo).not.toHaveBeenCalled();
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("announcement")).toHaveTextContent("Queued Delta");
    expect(navigationState.pending).toBeNull();
  });

  it("does not attach an obsolete Shell mount after its deferred import resolves", async () => {
    navigationState.engine = null;
    const stale = render(<Harness />); stale.unmount();
    await flush();
    expect(navigationState.engine).toBeNull();
    render(<Harness id="Current mount" />); wireScroll(); act(() => requestPaperNavigation());
    await flush(); await flush();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Current mount");
  });

  it("checkpoints an immediate scroll-to-Reader click before the debounce can lose the outgoing position", async () => {
    render(<Harness />); const container = wireScroll(); await flush();
    history.replaceState({ __NA: true, tree: ["keep"] }, "", location.href);
    container.scrollTop = 1780; fireEvent.scroll(container);
    act(() => requestWorkspaceNavigation("/workspace/items/paper#abstract%3A0"));
    expect(history.state).toEqual({ __NA: true, tree: ["keep"], workspaceScroll: 1780 });
  });

  it("does not let asynchronously loaded retained text override an already-restored history position", async () => {
    render(<Harness />); const container = wireScroll(); await flush();
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 380 } }))); await flush();
    vi.mocked(container.scrollTo).mockClear();
    const span = document.getElementById("notes")!;
    settleReaderTarget(span, false); await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    act(() => requestWorkspaceNavigation("/workspace/items/paper#material%3Aexact"));
    settleReaderTarget(span, false); await flush(); expect(container.scrollTo).toHaveBeenCalled();
  });

  it("cancels an active runtime animation and releases only its own engine when Shell is disposed", async () => {
    const view = render(<Harness />); wireScroll(); act(() => requestPaperNavigation()); await flush(); await flush();
    expect(navigationState.engine).not.toBeNull(); expect(animate).toHaveBeenCalled();
    view.unmount(); expect(cancelAnimation).toHaveBeenCalled(); expect(navigationState.engine).toBeNull();
    render(<Harness id="Replacement" />); wireScroll(); act(() => requestPaperNavigation()); await flush(); await flush();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Replacement");
  });

  it("keeps paper navigation and Reader focus working when session storage and history checkpoints are unavailable", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked storage"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked storage"); });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("blocked storage"); });
    const view = render(<Harness />); const container = wireScroll(); await flush();
    vi.spyOn(history, "replaceState").mockImplementation(() => { throw new Error("history quota"); });
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Storage independent" />);
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 1104, behavior: "instant" });
    expect(screen.getByTestId("announcement")).toHaveTextContent("Storage independent");
    const entry = document.getElementById("notes")!;
    act(() => settleReaderTarget(entry, true, true)); await flush();
    expect(entry).toHaveFocus();
  });

  it("settles mutation-driven changes after runtime initialization without an explicit navigation request", async () => {
    const view = render(<Harness />); const container = wireScroll(); await flush();
    view.rerender(<Harness id="After dismissal" />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("announcement")).toHaveTextContent("After dismissal");
    view.rerender(<Harness id="Undo restored" />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("announcement")).toHaveTextContent("Undo restored");
  });

  it("does not create a route intent for a link blocked by the document draft guard", async () => {
    const guard = (event: MouseEvent) => { event.preventDefault(); event.stopPropagation(); };
    const view = render(<Harness />); const container = wireScroll(); await flush();
    document.addEventListener("click", guard, true);
    fireEvent.click(screen.getByTestId("route"));
    document.removeEventListener("click", guard, true);
    // A blocked click must not leave an intent that moves the current page later.
    view.rerender(<Harness />); await flush(); await flush();
    expect(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")).toBeNull();
    expect(container.scrollTo).not.toHaveBeenCalled();
  });

  it("persists only a sanitized Radar intent when Composer submits before the runtime can load", async () => {
    navigationState.engine = null;
    const view = render(<Harness />);
    const form = document.querySelector<HTMLFormElement>(".ws-composer")!;
    form.addEventListener("submit", event => event.preventDefault());
    const input = form.elements.namedItem("q") as HTMLInputElement;
    input.value = " /help "; fireEvent.submit(form);
    expect(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")).toBeNull();
    input.value = "private query text"; fireEvent.submit(form);
    const stored = JSON.parse(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")!);
    expect(stored).toEqual({ kind: "paper", path: "/workspace/radar", at: expect.any(Number) });
    view.unmount(); navigationState.pending = null; // Simulate the document being replaced by location.assign.
    history.replaceState({}, "", "/workspace/radar?q=private");
    render(<Harness path="/workspace/radar" id="Returned search" />); wireScroll();
    await flush(); await flush();
    expect(screen.getByTestId("announcement")).toHaveTextContent("Returned search");
    expect(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")).toBeNull();
  });

  it("captures an allowed Next-style link before its normal bubble preventDefault", async () => {
    const view = render(<Harness />); wireScroll(); await flush();
    const link = screen.getByTestId("route");
    link.addEventListener("click", event => event.preventDefault());
    fireEvent.click(link);
    expect(JSON.parse(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")!).path).toBe("/workspace/library");
    history.pushState({}, "", "/workspace/library"); view.rerender(<Harness path="/workspace/library" paper={false} />); wireScroll();
    await flush(); expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

  it("never schedules a generic Reader heading before an exact-entry URL commits", async () => {
    history.replaceState({}, "", "/workspace/items/example?version=v1");
    render(<Harness path="/workspace/items/example" paper={false} />); const container = wireScroll(); await flush();
    act(() => requestWorkspaceNavigation("/workspace/items/example?version=v1&entry=retained#notes"));
    await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveFocus();
    history.replaceState({}, "", "/workspace/items/example?version=v1&entry=retained#notes");
    const entry = document.getElementById("notes")!;
    act(() => settleReaderTarget(entry)); await flush();
    expect(entry).toHaveFocus();
    expect(container.scrollTo).toHaveBeenCalledTimes(1);
  });

  it("settles automatic dismissal, snooze and Undo paper changes after Back restores a snapshot", async () => {
    const view = render(<Harness />); const container = wireScroll(); await flush();
    act(() => {
      history.replaceState({ __NA: true, workspaceScroll: 430 }, "", "/workspace/today?focus=Alpha");
      window.dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
    });
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 430, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled();
    expect(navigationState.readerHistory).toBe(true);
    const player = screen.getByRole("button", { name: "Next paper" }); player.focus();
    // Mutation responses change resolved identity without issuing navigation requests.
    for (const id of ["Beta after dismissal", "Gamma after snooze", "Alpha restored by Undo"]) {
      const before = container.scrollTop;
      view.rerender(<Harness id={id} />); await flush(); await flush();
      expect(container.scrollTo).toHaveBeenLastCalledWith({ top: before + 204, behavior: "instant" });
      expect(screen.getByTestId("announcement")).toHaveTextContent(id);
      expect(player).toHaveFocus();
    }
    expect(container.scrollTo).toHaveBeenCalledTimes(4);
    expect(animate).toHaveBeenCalledTimes(3);
    // Retained Reader text still cannot take over this history session implicitly.
    const calls = vi.mocked(container.scrollTo).mock.calls.length;
    settleReaderTarget(document.getElementById("notes")!, false); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(calls);
  });

  it("lands on the honest empty-result heading when a requested paper queue becomes empty", async () => {
    const view = render(<Harness />); const container = wireScroll(); await flush();
    act(() => requestPaperNavigation()); view.rerender(<Harness paper={false} />);
    const empty = document.createElement("section"); empty.className = "daily-empty";
    empty.innerHTML = '<h2 data-top="300">No papers remain in this queue</h2>';
    act(() => container.append(empty)); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 1144, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled();
  });

  it("does not write a delayed scroll checkpoint over a newer route or pending navigation", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    render(<Harness />); const container = wireScroll(); await flush();
    fireEvent.scroll(container);
    history.replaceState({ __NA: true, destination: true }, "", "/workspace/library");
    await act(async () => { vi.advanceTimersByTime(150); });
    expect(history.state).toEqual({ __NA: true, destination: true });
    act(() => requestWorkspaceNavigation("/workspace/radar"));
    fireEvent.scroll(container);
    await act(async () => { vi.advanceTimersByTime(150); });
    expect(history.state.destination).toBe(true);
  });

  it("leaves modified clicks, downloads, new tabs, anchors and unrelated forms outside workspace navigation", async () => {
    render(<Harness />); const container = wireScroll(); await flush();
    const link = screen.getByTestId("route") as HTMLAnchorElement;
    link.addEventListener("click", event => event.preventDefault());
    fireEvent.click(link, { ctrlKey: true }); await flush();
    link.download = "notes.md"; fireEvent.click(link); await flush(); link.removeAttribute("download");
    link.target = "_blank"; fireEvent.click(link); await flush(); link.removeAttribute("target");
    link.href = "#notes"; fireEvent.click(link); await flush();
    link.href = "https://example.org/workspace/library"; fireEvent.click(link); await flush();
    const form = document.createElement("form"); form.addEventListener("submit", event => event.preventDefault());
    main().append(form); fireEvent.submit(form); await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("arxiv.workspace.navigation-intent.v1")).toBeNull();
  });

  it("recovers a Back checkpoint when Next replaces the template before its pop listener attaches", async () => {
    const outgoing = render(<Harness />); wireScroll(); await flush();
    act(() => requestWorkspaceNavigation("/workspace/items/example#abstract:0"));
    history.pushState({}, "", "/workspace/items/example#abstract:0");
    outgoing.rerender(<Harness path="/workspace/items/example" ready={false} />); await flush();
    // Back can arrive before the Reader finishes loading and consumes its intent.
    outgoing.unmount();
    history.replaceState({ __NA: true, workspaceScroll: 870 }, "", "/workspace/today?focus=Alpha");
    const view = render(<Harness ready={false} />); const container = wireScroll(); await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
    view.rerender(<Harness />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 870, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveFocus();
  });

  it("reserves only the missing scroll extent for short desktop papers and recalculates it for the next target", async () => {
    const view = render(<Harness />); const container = wireScroll();
    vi.spyOn(container, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(container, "scrollHeight", "get").mockImplementation(() => 824 + Number.parseInt(container.querySelector<HTMLElement>("[data-workspace-scroll-tail]")?.style.height ?? "0"));
    container.scrollTop = 224;
    vi.mocked(container.scrollTo).mockImplementation(options => { container.scrollTop = Math.min((options as ScrollToOptions).top ?? 0, container.scrollHeight - container.clientHeight); });
    await flush(); expect(container.querySelector("[data-workspace-scroll-tail]")).toBeNull();
    act(() => requestPaperNavigation()); view.rerender(<Harness id="Short Beta" />); await flush(); await flush();
    expect(container.scrollTop).toBe(428);
    expect(container.querySelector("[data-workspace-scroll-tail]")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector<HTMLElement>("[data-workspace-scroll-tail]")!.style.height).toBe("204px");
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 100 } }))); await flush();
    expect(container.scrollTop).toBe(100);
    expect(container.querySelector("[data-workspace-scroll-tail]")).toBeNull();
  });

  it("reserves document space for a short mobile target and a larger history checkpoint without accumulating tails", async () => {
    mobile = true; render(<Harness />); const container = wireScroll();
    vi.stubGlobal("innerHeight", 600);
    vi.spyOn(document.documentElement, "scrollHeight", "get").mockImplementation(() => 900 + Number.parseInt(container.querySelector<HTMLElement>("[data-workspace-scroll-tail]")?.style.height ?? "0"));
    await flush(); act(() => requestPaperNavigation()); await flush(); await flush();
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 744, behavior: "instant" });
    expect(container.querySelector<HTMLElement>("[data-workspace-scroll-tail]")!.style.height).toBe("444px");
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 870 } }))); await flush();
    expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 870, behavior: "instant" });
    expect(container.querySelectorAll("[data-workspace-scroll-tail]")).toHaveLength(1);
    expect(container.querySelector<HTMLElement>("[data-workspace-scroll-tail]")!.style.height).toBe("570px");
  });

  it("ignores a simultaneous old Reader main while the matching Today route is still opening", async () => {
    const oldApp = document.createElement("div"); oldApp.className = "ws-app"; oldApp.dataset.workspacePath = "/workspace/items/old";
    oldApp.innerHTML = '<main class="ws-stage"><section class="ws-reader"><h1>Old Reader</h1></section></main>';
    document.body.prepend(oldApp);
    history.replaceState({ workspaceScroll: 870 }, "", "/workspace/today");
    const view = render(<Harness ready={false} />);
    const container = document.querySelector<HTMLElement>('.ws-app[data-workspace-path="/workspace/today"] main')!;
    Object.defineProperty(container, "scrollTo", { configurable: true, value: vi.fn() });
    await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    view.rerender(<Harness />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 870, behavior: "instant" });
    expect(oldApp.querySelector("h1")).not.toHaveFocus();
    oldApp.remove();
  });

  it("retains history through a stale restoration frame until replacement route content is ready", async () => {
    const view = render(<Harness />); const container = wireScroll(); await flush();
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 870 } })));
    view.rerender(<Harness ready={false} />); await flush();
    expect(container.scrollTo).not.toHaveBeenCalled();
    expect(container.querySelector("[data-workspace-scroll-tail]")).toBeNull();
    view.rerender(<Harness />); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(1);
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 870, behavior: "instant" });
    expect(animate).not.toHaveBeenCalled();
  });

  it("checkpoints explicit Reader entry even when an older paper navigation has not settled", async () => {
    render(<Harness />); const container = wireScroll(); await flush();
    act(() => requestPaperNavigation()); container.scrollTop = 870;
    act(() => requestWorkspaceNavigation("/workspace/items/paper#abstract:0"));
    expect(history.state.workspaceScroll).toBe(870);
  });

  it("does not let an older template cleanup release the newer template's engine", async () => {
    const stale = render(<Harness />); wireScroll(); await flush();
    const current = render(<Harness id="New template" />); await flush();
    const owner = navigationState.engine;
    stale.unmount(); expect(navigationState.engine).toBe(owner);
    const container = wireScroll(); act(() => requestPaperNavigation()); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalled();
    current.unmount(); expect(navigationState.engine).toBeNull();
  });

  it.each(["today", "radar", "library"])("settles a terminal %s failure without its success wrapper and resumes checkpoints", async route => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const path = `/workspace/${route}`; history.replaceState({}, "", path);
    const view = render(<Harness path={path} ready={false} />); const container = wireScroll(); await flush();
    act(() => requestWorkspaceNavigation(path));
    view.rerender(<Harness path={path} paper={false} />);
    act(() => { const wrapper = container.querySelector<HTMLElement>(`.ws-${route}`)!; wrapper.className = `ws-${route}-state`; wrapper.dataset.workspaceUnavailable = ""; });
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 964, behavior: "instant" });
    expect(container.querySelector("h1")).toHaveFocus();
    container.scrollTop = 432; fireEvent.scroll(container);
    await act(async () => { vi.advanceTimersByTime(150); });
    expect(history.state.workspaceScroll).toBe(432);
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: { workspaceScroll: 222 } })));
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 222, behavior: "instant" });
  });

  it.each(["data-reader-unavailable", "data-workspace-unavailable"])("settles a terminal %s view at its own heading while retaining history priority", async marker => {
    history.replaceState({}, "", "/workspace/items/missing?version=unavailable#abstract:2500:2520");
    const view = render(<Harness path="/workspace/items/missing" paper={false} ready={false} />);
    const container = wireScroll(); await flush();
    view.rerender(<Harness path="/workspace/items/missing" paper={false} />);
    act(() => { const heading = container.querySelector("h1")!; heading.parentElement!.setAttribute(marker, ""); heading.textContent = "Requested retained source is unavailable"; });
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 964, behavior: "instant" });
    expect(container.querySelector("h1")).toHaveFocus();
    history.replaceState({ workspaceScroll: 222 }, "", location.href);
    act(() => { window.dispatchEvent(new PopStateEvent("popstate", { state: history.state })); window.dispatchEvent(new HashChangeEvent("hashchange")); });
    await flush(); await flush();
    expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 222, behavior: "instant" });
  });

  it("waits for the requested exact mark and visible panel before settling a new fragment", async () => {
    history.replaceState({}, "", "/workspace/items/paper#abstract:2500:2520");
    render(<Harness path="/workspace/items/paper" paper={false} />); const container = wireScroll(); await flush();
    const panel = document.createElement("section"); panel.id = "source"; panel.dataset.sourceRequest = "abstract:10:20"; panel.dataset.sourceValid = "true";
    const mark = document.createElement("mark"); mark.id = "source-anchor"; mark.dataset.sourceAnchor = "abstract:10:20"; mark.dataset.top = "300"; panel.append(mark);
    act(() => container.append(panel)); await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    act(() => { panel.dataset.sourceRequest = "abstract:2500:2520"; }); await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    act(() => { panel.hidden = true; mark.dataset.sourceAnchor = "abstract:2500:2520"; }); await flush(); expect(container.scrollTo).not.toHaveBeenCalled();
    act(() => { panel.hidden = false; }); await flush(); await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 1144, behavior: "instant" });
  });

  it("lets a new Reader fragment without a checkpoint take priority after Forward, retaining real Back snapshots", async () => {
    history.replaceState({}, "", "/workspace/items/paper#abstract:0");
    render(<Harness path="/workspace/items/paper" paper={false} />); const container = wireScroll(); await flush();
    const mark = document.createElement("mark"); mark.id = "source-anchor"; mark.dataset.sourceAnchor = "abstract:2500:2520"; mark.dataset.top = "1298"; mark.textContent = "Exact retained range";
    const source = document.createElement("section"); source.id = "source"; source.dataset.sourceRequest = "abstract:2500:2520"; source.dataset.sourceValid = "true"; source.dataset.top = "100";
    source.append(mark); container.append(source);
    history.replaceState({ workspaceScroll: 359 }, "", location.href);
    act(() => window.dispatchEvent(new PopStateEvent("popstate", { state: history.state }))); await flush();
    expect(navigationState.readerHistory).toBe(true);
    vi.mocked(container.scrollTo).mockClear();
    history.pushState(null, "", "/workspace/items/paper#abstract:2500:2520");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(navigationState.readerHistory).toBe(false);
    await flush();
    expect(container.scrollTo).toHaveBeenCalledWith({ top: 1601, behavior: "instant" });
    const afterLanding = vi.mocked(container.scrollTo).mock.calls.length;
    act(() => { const notice = document.createElement("p"); notice.textContent = "Reading state saved"; container.append(notice); });
    await flush(); expect(container.scrollTo).toHaveBeenCalledTimes(afterLanding);
    history.replaceState({ workspaceScroll: 359 }, "", "/workspace/items/paper#abstract:0");
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate", { state: history.state }));
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await flush(); expect(container.scrollTo).toHaveBeenLastCalledWith({ top: 359, behavior: "instant" });
    const calls = vi.mocked(container.scrollTo).mock.calls.length;
    settleReaderTarget(mark, false); await flush();
    expect(container.scrollTo).toHaveBeenCalledTimes(calls);
  });

  it("checkpoints origin scroll before runtime loading and never replays it into the destination entry", async () => {
    Object.defineProperty(window, "scrollY", { configurable: true, value: 0 });
    const origin = render(<Harness />); const originMain = wireScroll(); originMain.scrollTop = 870;
    history.replaceState({ __NA: true, tree: ["origin"] }, "", location.href);
    const link = screen.getByTestId("route") as HTMLAnchorElement;
    link.href = "/workspace/items/paper#abstract:0";
    link.addEventListener("click", event => event.preventDefault());
    fireEvent.click(link);
    const originSnapshot = history.state;
    expect(originSnapshot).toEqual({ __NA: true, tree: ["origin"], workspaceScroll: 870 });
    origin.unmount();
    history.pushState({ __NA: true, tree: ["destination"] }, "", "/workspace/items/paper#abstract:0");
    const destination = render(<Harness path="/workspace/items/paper" paper={false} />); wireScroll();
    await flush(); await flush();
    expect(history.state).toEqual({ __NA: true, tree: ["destination"] });
    act(() => {
      history.replaceState(originSnapshot, "", "/workspace/today");
      window.dispatchEvent(new PopStateEvent("popstate", { state: originSnapshot }));
    });
    destination.rerender(<Harness />); const restoredMain = wireScroll();
    await flush(); await flush();
    expect(restoredMain.scrollTo).toHaveBeenLastCalledWith({ top: 870, behavior: "instant" });
  });

  it("keeps an early unblocked navigation usable when synchronous history checkpointing is denied", async () => {
    const view = render(<Harness />); wireScroll();
    const link = screen.getByTestId("route"); link.addEventListener("click", event => event.preventDefault());
    const denied = vi.spyOn(history, "replaceState").mockImplementation(() => { throw new Error("history denied"); });
    expect(() => fireEvent.click(link)).not.toThrow();
    denied.mockRestore();
    history.pushState({}, "", "/workspace/library"); view.rerender(<Harness path="/workspace/library" paper={false} />); wireScroll();
    await flush(); await flush();
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
  });

});
