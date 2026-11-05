import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ControlBar, SidebarSection } from "@/components/workspace/Slots";
import { WorkspaceShell } from "@/components/workspace/Shell";
import WorkspaceDialogs from "@/components/workspace/WorkspaceDialogs";
import CommandSuggestions from "@/components/workspace/CommandSuggestions";
import { enabledWorkspaceCommands, filterWorkspaceCommands, prefixWorkspaceCommands } from "@/lib/workspace/commandRegistry";
import { dispatchWorkspaceCommand } from "@/lib/workspace/dispatch";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/today", useSearchParams: () => new URLSearchParams() }));
const save = vi.fn();
const assign = vi.fn();
const label = vi.fn();
const modal = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "showModal");
const close = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, "close");
beforeEach(() => {
  save.mockReset(); assign.mockReset(); label.mockReset(); localStorage.clear();
  vi.stubGlobal("location", { ...window.location, assign });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value(this: HTMLDialogElement) { this.removeAttribute("open"); } });
});
afterEach(() => {
  cleanup(); vi.unstubAllGlobals();
  if (modal) Object.defineProperty(HTMLDialogElement.prototype, "showModal", modal); else Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
  if (close) Object.defineProperty(HTMLDialogElement.prototype, "close", close); else Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
});
function Fixture({ disabled = false }: { disabled?: boolean }) {
  return <WorkspaceShell><h1>Test paper</h1><button data-command="save" aria-keyshortcuts="S" disabled={disabled} onClick={save}>Save current paper</button>
    <button data-command="label-useful" onClick={label}>Useful judgment</button><button data-command="dismiss" disabled>Unavailable action</button><button data-command="next" aria-label="Next paper">Next</button></WorkspaceShell>;
}
async function open() {
  await userEvent.click(screen.getByRole("button", { name: "Open command palette" }));
  return screen.findByRole("combobox", { name: "Find a command" });
}

describe("local command surfaces", () => {
  it("submits the displayed slash action once and refuses a stale paper context before the observer updates", async () => {
    render(<Fixture />);
    const paper = document.createElement("article"); paper.className = "ws-focus"; paper.dataset.paperKey = "paper-a:v1";
    act(() => { screen.getByRole("main").append(paper); });
    const input = await screen.findByRole("searchbox");
    fireEvent.change(input, { target: { value: "/save" } });
    await screen.findByRole("region", { name: "Available local commands" });
    act(() => { paper.dataset.paperKey = "paper-b:v2"; fireEvent.submit(input.closest("form")!); });
    expect(save).not.toHaveBeenCalled(); expect(input).toHaveValue("/save");
    expect(screen.getByText("No available command matches. Try another command.")).toBeInTheDocument();
    await act(async () => { await Promise.resolve(); });
    expect(within(screen.getByRole("region", { name: "Available local commands" })).getByRole("button", { name: "Save current paper" })).toBeInTheDocument();
    fireEvent.submit(input.closest("form")!);
    expect(save).toHaveBeenCalledOnce(); expect(input).toHaveValue("");
    expect(screen.queryByRole("region", { name: "Available local commands" })).not.toBeInTheDocument();
    expect(screen.queryByText("No available command matches. Try another command.")).not.toBeInTheDocument();
  });

  it.each([{ metaKey: true }, { ctrlKey: true }])("opens lazily from a field with %s, then Esc restores the invoker", async modifiers => {
    render(<Fixture />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    const input = await screen.findByRole("searchbox"); input.focus();
    fireEvent.keyDown(input, { key: "k", ...modifiers });
    const search = await screen.findByRole("combobox");
    expect(search).toHaveFocus();
    fireEvent.keyDown(search, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(input).toHaveFocus();
  });

  it("filters current enabled actions, dispatches Enter once, and preserves navigation guards", async () => {
    render(<Fixture />);
    const search = await open();
    expect(screen.queryByRole("option", { name: "Unavailable action" })).not.toBeInTheDocument();
    fireEvent.change(search, { target: { value: "save current" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    expect(screen.getByRole("button", { name: "Open command palette" })).toHaveFocus();
    const guarded = vi.fn((event: Event) => event.preventDefault());
    screen.getByRole("link", { name: "Radar" }).addEventListener("click", guarded);
    const again = await open(); fireEvent.change(again, { target: { value: "go to radar" } });
    fireEvent.keyDown(again, { key: "Enter" });
    await waitFor(() => expect(guarded).toHaveBeenCalledOnce());
    expect(assign).not.toHaveBeenCalled();
  });

  it("wraps arrow navigation, tolerates no matches, and closes via button/cancel", async () => {
    render(<Fixture />); const search = await open();
    const scroll = vi.fn();
    for (const option of screen.getAllByRole("option")) option.scrollIntoView = scroll;
    const first = search.getAttribute("aria-activedescendant");
    fireEvent.keyDown(search, { key: "ArrowUp" });
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
    expect(search).toHaveFocus();
    expect(search.getAttribute("aria-activedescendant")).not.toBe(first);
    fireEvent.keyDown(search, { key: "ArrowDown" });
    expect(search).toHaveAttribute("aria-activedescendant", first);
    fireEvent.change(search, { target: { value: "no command could match this phrase" } });
    for (const key of ["ArrowDown", "ArrowUp", "Enter"]) fireEvent.keyDown(search, { key });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    expect(search).not.toHaveAttribute("aria-activedescendant");
    fireEvent(screen.getByRole("dialog"), new Event("cancel", { bubbles: false, cancelable: true }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await open(); await userEvent.click(screen.getByRole("button", { name: /^Close/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("observes disabled controls while open and re-resolves stale rows before execution", async () => {
    render(<Fixture />); const search = await open();
    fireEvent.change(search, { target: { value: "save current" } });
    const button = screen.getByRole("button", { name: "Save current paper" });
    act(() => { button.setAttribute("disabled", ""); });
    await waitFor(() => expect(screen.queryByRole("option")).not.toBeInTheDocument());
    act(() => { button.removeAttribute("disabled"); });
    await screen.findByRole("option", { name: "Save current paper" });
    fireEvent.keyDown(search, { key: "Enter" });
    button.setAttribute("disabled", "");
    await new Promise(resolve => setTimeout(resolve, 5));
    expect(save).not.toHaveBeenCalled();
  });

  it("opens current shortcut help from ? and its visible footer control", async () => {
    render(<Fixture />);
    fireEvent.keyDown(document.body, { key: "?", shiftKey: true });
    await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
    expect(screen.getByText("Save current paper", { selector: "dd" })).toBeInTheDocument();
    expect(screen.queryByText("Unavailable action", { selector: "dd" })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await userEvent.click(screen.getByRole("button", { name: /^Keyboard shortcuts/ }));
    await screen.findByRole("dialog", { name: "Keyboard shortcuts" });
  });

  it.each(["palette", "shortcuts"])("%s owns bare shortcuts from its Close button", async kind => {
    render(<Fixture />);
    if (kind === "palette") await open();
    else { fireEvent.keyDown(document.body, { key: "?", shiftKey: true }); await screen.findByRole("dialog"); }
    const closeButton = screen.getByRole("button", { name: /^Close/ }); closeButton.focus();
    for (const key of ["s", "d", "j", "1", "2", "3", "g", "l"]) fireEvent.keyDown(closeButton, { key });
    expect(save).not.toHaveBeenCalled(); expect(label).not.toHaveBeenCalled(); expect(assign).not.toHaveBeenCalled();
    expect(dispatchWorkspaceCommand("save")).toBe(false);
    expect(dispatchWorkspaceCommand("label-useful")).toBe(false);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(closeButton, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "s" });
    expect(save).toHaveBeenCalledOnce();
  });

  it("leaves IME composition keys to the input without dispatch or selection movement", async () => {
    render(<Fixture />); const search = await open();
    fireEvent.change(search, { target: { value: "save current" } });
    const before = search.getAttribute("aria-activedescendant");
    for (const key of ["ArrowDown", "ArrowUp", "Enter", "Escape"]) fireEvent.keyDown(search, { key, isComposing: true });
    expect(search).toHaveAttribute("aria-activedescendant", before);
    expect(screen.getByRole("dialog")).toBeInTheDocument(); expect(save).not.toHaveBeenCalled();
    fireEvent.keyDown(search, { key: "Enter" });
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
  });

  it("observes pending bar/sidebar portal targets and does not retarget a removed selection", async () => {
    const undo = vi.fn();
    function PortalPage({ pending, hasUndo }: { pending: boolean; hasUndo: boolean }) {
      return <WorkspaceShell><h1>Portal controls</h1>
        <ControlBar><button data-command="save" disabled={pending} onClick={save}>Save staged paper</button>
          {hasUndo && <button data-command="undo" onClick={undo}>Undo last change</button>}</ControlBar>
        <SidebarSection label="Reading controls"><button data-command="time-15" disabled={pending}>15 min</button></SidebarSection>
      </WorkspaceShell>;
    }
    const view = render(<PortalPage pending={false} hasUndo={false} />);
    const search = await open();
    expect(screen.getByRole("option", { name: "Save staged paper" })).toHaveAttribute("aria-selected", "true");
    view.rerender(<PortalPage pending hasUndo />);
    await screen.findByRole("option", { name: "Undo last change" });
    expect(screen.queryByRole("option", { name: "Save staged paper" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "15 min" })).not.toBeInTheDocument();
    expect(search).not.toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(search, { key: "Enter" });
    expect(undo).not.toHaveBeenCalled(); expect(save).not.toHaveBeenCalled();
    view.rerender(<PortalPage pending={false} hasUndo />);
    await screen.findByRole("option", { name: "15 min" });
    expect(document.querySelector('.ws-sidebar-slot [data-command="time-15"]')).not.toBeNull();
    expect(document.querySelector('.ws-bar-slot [data-command="undo"]')).not.toBeNull();
    await userEvent.click(screen.getByRole("option", { name: "Undo last change" }));
    await waitFor(() => expect(undo).toHaveBeenCalledOnce());
  });

  it("updates slash labels after the current action changes and excludes CSS-hidden page controls", async () => {
    render(<Fixture />);
    const input = await screen.findByRole("searchbox");
    fireEvent.change(input, { target: { value: "/s" } });
    const region = await screen.findByRole("region", { name: "Available local commands" });
    const target = document.querySelector<HTMLButtonElement>('[data-command="save"]')!;
    act(() => { target.textContent = "Unsave current paper"; });
    await waitFor(() => expect(within(region).getByRole("button", { name: /Unsave current paper/ })).toBeInTheDocument());
    act(() => { target.setAttribute("disabled", ""); });
    await waitFor(() => expect(within(region).queryByRole("button", { name: /Unsave current paper/ })).not.toBeInTheDocument());
    const next = screen.getByRole("button", { name: "Next paper" });
    const wrapper = document.createElement("div"); next.replaceWith(wrapper); wrapper.append(next); wrapper.style.display = "none";
    expect(enabledWorkspaceCommands().some(row => row.id === "next")).toBe(false);
    expect(dispatchWorkspaceCommand("next")).toBe(false);
    wrapper.style.display = "block"; next.style.visibility = "hidden";
    expect(enabledWorkspaceCommands().some(row => row.id === "next")).toBe(false);
    const footer = document.querySelector<HTMLElement>(".ws-sidebar-footer")!; footer.style.display = "none";
    expect(enabledWorkspaceCommands().some(row => row.id === "theme-dark")).toBe(true);
  });

  it("feature-detects dialog methods and does not refocus a detached invoker", () => {
    Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal");
    Reflect.deleteProperty(HTMLDialogElement.prototype, "close");
    const invoker = document.createElement("button");
    const onClose = vi.fn();
    const view = render(<div className="workspace-app"><WorkspaceDialogs onCommand={dispatchWorkspaceCommand} request={{ kind: "palette", invoker }} onClose={onClose} /></div>);
    expect(screen.getByRole("dialog")).toHaveAttribute("open");
    fireEvent.click(screen.getByRole("button", { name: /^Close/ }));
    expect(onClose).toHaveBeenCalledOnce(); view.unmount();
  });

  it("uses one registry for scoped page actions, routes, menu globals, and slash suggestions", async () => {
    expect(enabledWorkspaceCommands()).toEqual([]);
    render(<Fixture />);
    const footer = document.querySelector(".ws-sidebar-footer")!; footer.setAttribute("hidden", "");
    const rows = enabledWorkspaceCommands();
    expect(rows.find(row => row.id === "theme-dark")).toBeDefined();
    expect(dispatchWorkspaceCommand("theme-dark")).toBe(true);
    expect(screen.getByRole("radio", { name: "Dark", hidden: true })).toBeChecked();
    expect(filterWorkspaceCommands("/time 30")).toEqual([]);
    const link = screen.getByRole("link", { name: "Library" }); link.setAttribute("aria-disabled", "true");
    expect(enabledWorkspaceCommands().some(row => row.id === "go-library")).toBe(false);
    expect(prefixWorkspaceCommands("/s")[0]?.id).toBe("save");
    expect(prefixWorkspaceCommands("/r")).toEqual([]);
    expect(prefixWorkspaceCommands("/radar")[0]?.id).toBe("go-radar");
    const choices = vi.fn();
    const view = render(<CommandSuggestions onCommand={dispatchWorkspaceCommand} query="/save" onChoose={choices} />);
    await userEvent.click(within(screen.getByRole("region", { name: "Available local commands" })).getByRole("button", { name: /^Save current paper/ }));
    expect(save).toHaveBeenCalledOnce(); expect(choices).toHaveBeenCalledOnce();
    view.rerender(<CommandSuggestions onCommand={dispatchWorkspaceCommand} query="unavailable nonsense" onChoose={choices} />);
    expect(screen.getByText("No available command matches.")).toBeInTheDocument();
  });

  it("clicks an option without moving input focus and retains current command labels", async () => {
    render(<Fixture />);
    const target = screen.getByRole("button", { name: "Next paper" });
    const next = vi.fn(); target.addEventListener("click", next);
    const search = await open();
    fireEvent.change(search, { target: { value: "next paper" } });
    await userEvent.click(screen.getByRole("option", { name: "Next paper" }));
    await waitFor(() => expect(next).toHaveBeenCalledOnce());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    target.removeAttribute("aria-label"); target.textContent = "";
    expect(enabledWorkspaceCommands().find(row => row.id === "next")?.label).toBe("next");
  });
});
