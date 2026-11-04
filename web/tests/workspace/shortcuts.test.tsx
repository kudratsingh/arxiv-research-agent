import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/workspace/Composer";
import { useWorkspaceShortcuts } from "@/components/workspace/useWorkspaceShortcuts";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";

const assign = vi.fn();
function Fixture({ next, disabled = false, onLight }: { next: () => void; disabled?: boolean; onLight?: () => void }): React.ReactElement {
  useWorkspaceShortcuts();
  return <div className="workspace-app"><main id="main" tabIndex={-1}>
    <button data-command="next" disabled={disabled} onClick={next}>Next</button>
    <button data-command="open" onClick={next}>Open</button>
    <button data-command="toggle-sidebar" onClick={next}>Sidebar</button>
    <input type="radio" name="theme-preference" value="dark" onClick={next} />
    {onLight && <input type="radio" name="theme-preference" value="light" onClick={onLight} />}
    {/* The real export is a download link, not client-side page navigation. */}
    {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
    <a href="/api/workspace/export" onClick={(event) => { event.preventDefault(); next(); }}>Export</a>
    <Composer />
  </main></div>;
}
function key(target: Element | Document | Window, keyName: string, options: Record<string, unknown> = {}): void {
  fireEvent.keyDown(target, { key: keyName, ...options });
}
beforeEach(() => { assign.mockReset(); vi.stubGlobal("location", { assign }); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("workspace shortcuts and composer", () => {
  it("binds the Radar query while preserving filters and starting a new observation window", () => {
    const current = { assign, pathname: "/workspace/radar", search: "?q=old&days=30&source_id=arxiv-cs-lg&access_state=excerpt&status=saved&cursor=old-page&as_of=old-cutoff&focus=old-work" };
    vi.stubGlobal("location", current);
    render(<Fixture next={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: "Search stored papers" });
    expect(input).toHaveValue("old");
    fireEvent.change(input, { target: { value: "new research" } });
    fireEvent.submit(input.closest("form")!);
    expect(assign).toHaveBeenCalledOnce();
    const result = new URL(assign.mock.calls[0]![0], "http://localhost");
    expect(Object.fromEntries(result.searchParams)).toEqual({ q: "new research", days: "30", source_id: "arxiv-cs-lg", access_state: "excerpt", status: "saved" });
    current.search = "?q=history-query&days=30";
    fireEvent(window, new PopStateEvent("popstate"));
    expect(screen.getByRole("searchbox", { name: "Search stored papers" })).toHaveValue("history-query");
  });

  it("executes the current enabled scoped button, never a stale or outside control", () => {
    const outside = vi.fn(); const first = vi.fn(); const replacement = vi.fn();
    const other = document.createElement("button"); other.dataset.command = "next"; other.onclick = outside;
    document.body.append(other);
    const view = render(<Fixture next={first} />);
    key(document.body, "j");
    expect(first).toHaveBeenCalledTimes(1);
    view.rerender(<Fixture next={replacement} disabled />);
    key(document.body, "j");
    expect(replacement).not.toHaveBeenCalled();
    view.rerender(<Fixture next={replacement} />);
    key(document.body, "j");
    expect(replacement).toHaveBeenCalledTimes(1);
    expect(outside).not.toHaveBeenCalled();
    other.remove();
  });

  it("re-resolves replaced elements and skips aria-disabled or detached controls", () => {
    const first = vi.fn(); const second = vi.fn();
    render(<Fixture next={first} />);
    const old = screen.getByRole("button", { name: "Next" });
    const current = document.createElement("button");
    current.dataset.command = "next";
    current.setAttribute("aria-disabled", "true");
    current.onclick = second;
    old.replaceWith(current);
    key(document.body, "j");
    expect(first).not.toHaveBeenCalled(); expect(second).not.toHaveBeenCalled();
    current.removeAttribute("aria-disabled");
    key(document.body, "j");
    expect(second).toHaveBeenCalledTimes(1);
  });

  it("routes keyboard commands through the same guarded navigation control when Shell is mounted", () => {
    render(<Fixture next={vi.fn()} />);
    const nav = document.createElement("nav"); nav.className = "ws-navigation";
    const link = document.createElement("a"); link.href = "/workspace/library"; link.textContent = "Library";
    nav.append(link); document.querySelector(".workspace-app")!.append(nav);
    const guarded = vi.fn((event: MouseEvent) => event.preventDefault());
    link.addEventListener("click", guarded);
    key(document.body, "g"); key(document.body, "l");
    expect(guarded).toHaveBeenCalledOnce(); expect(assign).not.toHaveBeenCalled();
    link.setAttribute("aria-disabled", "true");
    expect(dispatchWorkspaceCommand("go-library")).toBe(false);
    expect(assign).not.toHaveBeenCalled();
  });

  it("handles route sequences and guards fields, modifiers and native Enter", () => {
    const action = vi.fn(); render(<Fixture next={action} />);
    key(document.body, "g"); key(document.body, "l");
    expect(assign).toHaveBeenCalledWith("/workspace/library");
    const input = screen.getByRole("searchbox", { name: "Search stored papers" });
    key(input, "j"); key(document.body, "j", { ctrlKey: true });
    key(document.body, "j", { altKey: true }); key(document.body, "j", { isComposing: true });
    key(screen.getByRole("button", { name: "Sidebar" }), "Enter");
    key(document.body, "k", { metaKey: true }); key(document.body, "?", { shiftKey: true });
    expect(action).not.toHaveBeenCalled();
    expect(assign).toHaveBeenCalledTimes(1);
    key(document.body, "/"); expect(input).toHaveFocus();
  });

  it("searches Radar and runs first available slash command without navigation for unknowns", () => {
    const action = vi.fn(); render(<Fixture next={action} disabled />);
    const input = screen.getByRole("searchbox", { name: "Search stored papers" });
    const form = screen.getByRole("search");
    fireEvent.change(input, { target: { value: "graph neural nets" } }); fireEvent.submit(form);
    expect(assign).toHaveBeenCalledWith("/workspace/radar?q=graph+neural+nets&days=7");
    fireEvent.change(input, { target: { value: "/n" } }); fireEvent.submit(form);
    expect(action).not.toHaveBeenCalled();
    expect(screen.getByText("No available command matches. Try another command.")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "/op" } }); fireEvent.submit(form);
    expect(action).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue("");
    expect(assign).toHaveBeenCalledTimes(1);
  });

  it("offers the same search through a visible submit control", async () => {
    render(<Fixture next={vi.fn()} />);
    const input = screen.getByRole("searchbox", { name: "Search stored papers" });
    fireEvent.change(input, { target: { value: "source evidence" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(assign).toHaveBeenCalledWith("/workspace/radar?q=source+evidence&days=7");
    expect(input).toHaveAttribute("aria-keyshortcuts", "/");
  });

  it("handles unavailable, inert and removed controls without action", () => {
    expect(dispatchWorkspaceCommand("next")).toBe(false);
    const action = vi.fn(); const view = render(<Fixture next={action} />);
    expect(dispatchWorkspaceCommand("command-palette")).toBe(false);
    expect(dispatchWorkspaceCommand("shortcuts")).toBe(false);
    expect(dispatchWorkspaceCommand("escape")).toBe(false);
    expect(dispatchWorkspaceCommand("theme-light")).toBe(false);
    screen.getByRole("searchbox").remove();
    expect(dispatchWorkspaceCommand("focus-composer")).toBe(false);
    const next = screen.getByRole("button", { name: "Next" });
    next.setAttribute("aria-hidden", "true");
    expect(dispatchWorkspaceCommand("next")).toBe(false);
    view.unmount();
    key(document.body, "j");
    expect(action).not.toHaveBeenCalled();
  });

  it("runs available slash commands by prefix, including time, theme and route", () => {
    const action = vi.fn(); render(<Fixture next={action} />);
    const time = document.createElement("button"); time.dataset.command = "time-5"; time.onclick = action;
    document.querySelector(".workspace-app")?.append(time);
    const input = screen.getByRole("searchbox"); const form = screen.getByRole("search");
    for (const value of ["/time-5", "/theme-dark", "/go-review"]) {
      fireEvent.change(input, { target: { value } }); fireEvent.submit(form);
    }
    expect(action).toHaveBeenCalledTimes(2);
    expect(assign).toHaveBeenCalledWith("/workspace/review");
  });

  it("uses human-readable arguments and route aliases without choosing a wrong setting", () => {
    const action = vi.fn(); const time5 = vi.fn(); const time15 = vi.fn(); const light = vi.fn();
    render(<Fixture next={action} onLight={light} />);
    const scope = document.querySelector(".workspace-app");
    const five = document.createElement("button"); five.dataset.command = "time-5"; five.onclick = time5;
    const fifteen = document.createElement("button"); fifteen.dataset.command = "time-15"; fifteen.onclick = time15;
    scope?.append(five, fifteen);
    const input = screen.getByRole("searchbox"); const form = screen.getByRole("search");
    function submit(value: string): void {
      fireEvent.change(input, { target: { value } }); fireEvent.submit(form);
    }
    submit("/theme dark");
    expect(action).toHaveBeenCalledTimes(1); expect(light).not.toHaveBeenCalled();
    submit("/time 15");
    expect(time15).toHaveBeenCalledTimes(1); expect(time5).not.toHaveBeenCalled();
    submit("/radar"); expect(assign).toHaveBeenCalledWith("/workspace/radar");
    for (const value of ["/theme purple", "/theme dark extra", "/time 30", "/time", "/radar extra", "/constructor"]) {
      submit(value);
      expect(screen.getByText("No available command matches. Try another command.")).toBeInTheDocument();
    }
    expect(action).toHaveBeenCalledTimes(1); expect(light).not.toHaveBeenCalled();
    expect(time15).toHaveBeenCalledTimes(1); expect(time5).not.toHaveBeenCalled();
    expect(assign).toHaveBeenCalledTimes(1);
  });

  it("leaves blank or missing form input untouched and reports an empty slash", () => {
    render(<Fixture next={vi.fn()} />);
    const input = screen.getByRole("searchbox"); const form = screen.getByRole("search");
    fireEvent.change(input, { target: { value: "   " } }); fireEvent.submit(form);
    expect(assign).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "/" } }); fireEvent.submit(form);
    expect(screen.getByText("No available command matches. Try another command.")).toBeInTheDocument();
    input.removeAttribute("name"); fireEvent.submit(form);
    expect(assign).not.toHaveBeenCalled();
  });

  it("dispatches theme, export and sidebar controls and Escape closes or blurs", () => {
    const action = vi.fn(); render(<Fixture next={action} />);
    expect(dispatchWorkspaceCommand("theme-dark")).toBe(true);
    expect(dispatchWorkspaceCommand("export")).toBe(true);
    expect(dispatchWorkspaceCommand("toggle-sidebar")).toBe(true);
    expect(action).toHaveBeenCalledTimes(3);
    const input = screen.getByRole("searchbox"); input.focus(); key(input, "Escape");
    expect(input).not.toHaveFocus();
    const close = document.createElement("button"); close.dataset.command = "escape";
    const onClose = vi.fn(); close.onclick = onClose;
    document.querySelector(".workspace-app")?.append(close);
    input.focus(); key(input, "Escape");
    expect(onClose).toHaveBeenCalledTimes(1); expect(input).toHaveFocus();
  });
});
