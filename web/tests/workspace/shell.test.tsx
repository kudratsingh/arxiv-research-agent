import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { ControlBar, SidebarSection, StageHeaderSlot } from "@/components/workspace/Slots";
import { readSidebarCollapsed, serverSidebarCollapsed, serverSidebarViewport, setSidebarCollapsed, SIDEBAR_STORAGE_KEY } from "@/components/workspace/useSidebarPreference";

const route = vi.hoisted(() => ({ path: "/workspace/today" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.path }));
let width = 1440;
let media: Map<string, MediaQueryList>;
function resize(next: number) {
  act(() => {
    width = next;
    for (const query of media.values()) query.dispatchEvent(new Event("change"));
  });
}
beforeEach(() => {
  width = 1440;
  media = new Map();
  route.path = "/workspace/today";
  localStorage.clear();
  document.documentElement.setAttribute("data-theme-preference", "system");
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal("matchMedia", vi.fn((query: string) => {
    if (!media.has(query)) {
      const events = new EventTarget();
      media.set(query, {
        media: query, onchange: null,
        get matches() { return query.includes("767") ? width <= 767 : query.includes("1023") ? width <= 1023 : false; },
        addEventListener: events.addEventListener.bind(events), removeEventListener: events.removeEventListener.bind(events),
        dispatchEvent: events.dispatchEvent.bind(events), addListener: vi.fn(), removeListener: vi.fn(),
      } as MediaQueryList);
    }
    return media.get(query)!;
  }));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); act(() => setSidebarCollapsed(false)); localStorage.clear(); });
function Page() {
  return <><h1>Page title</h1><p>Reading content</p>
    <SidebarSection label="Reading controls"><button type="button">Page control</button></SidebarSection>
    <StageHeaderSlot position={{ n: 2, N: 4 }} sources={{ ok: 3, total: 5, worst: "limited" }} action={<button>Header action</button>} />
    <ControlBar><button type="button">Page bar action</button></ControlBar>
  </>;
}

describe("workspace controller shell", () => {
  it("owns landmarks and fixed identity, but does not fetch page state or add a status region", () => {
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    const nav = screen.getByRole("navigation", { name: "Research workspace" });
    expect(within(nav).getAllByRole("link")).toHaveLength(6);
    expect(screen.getAllByRole("link", { name: "Radar" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute("href", "/workspace/review");
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("complementary", { name: "Workspace controls" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main");
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(screen.getByText("Real source metadata · private server saves · generation off").tagName).toBe("SPAN");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
    expect(container.querySelector(".workspace-app")?.firstElementChild).toBe(screen.getByRole("link", { name: "Skip to main content" }));
    expect(screen.getByRole("link", { name: /Fictional preview/ })).toHaveAttribute("href", "/today");
  });
  it("portals page controls exactly once, with the composer and bar last in main", () => {
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    expect(screen.getAllByRole("button", { name: "Page control" })).toHaveLength(1);
    expect(container.querySelector(".ws-sidebar-slot")).toContainElement(screen.getByRole("button", { name: "Page control" }));
    expect(container.querySelector(".ws-header-slot")).toContainElement(screen.getByRole("button", { name: "Header action" }));
    expect(screen.getByLabelText("Paper 2 of 4")).toHaveTextContent("02 / 04");
    expect(screen.getByText("3/5 sources · limited")).toBeInTheDocument();
    const bar = screen.getByRole("main").lastElementChild!;
    expect(bar).toHaveClass("ws-bar");
    expect(bar.firstElementChild).toHaveClass("ws-composer");
    expect(bar.lastElementChild).toContainElement(screen.getByRole("button", { name: "Page bar action" }));
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });
  it("keeps export exactly once when the old Library page supplies it", () => {
    route.path = "/workspace/library";
    render(<WorkspaceShell><a href="/api/workspace/export" download="research-notes.md">Export notes as Markdown ↗</a></WorkspaceShell>);
    expect(screen.getAllByRole("link", { name: /Export notes as Markdown/ })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
  });
  it("persists the desktop rail and restores controls using one command target", async () => {
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");
    expect(container.querySelector(".ws-sidebar-footer")).toHaveAttribute("hidden");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(container.querySelectorAll('[data-command="toggle-sidebar"]')).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByRole("button", { name: "Page control" })).toBeVisible();
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("false");
  });
  it("cycles the existing theme radios without creating another group", async () => {
    render(<WorkspaceShell><Page /></WorkspaceShell>);
    await userEvent.setup().click(screen.getByRole("button", { name: "Cycle color theme" }));
    expect(screen.getByRole("radio", { name: "Light" })).toBeChecked();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });
  it("retains one selectable queue mini-map in the rail without hiding or remounting it", async () => {
    const user = userEvent.setup();
    const select = vi.fn();
    const { container } = render(<WorkspaceShell><SidebarSection label="Up next">
      <ol className="ws-queue"><li><button aria-label="Show paper 1 of 1: Paper title" onClick={select}>
        <span className="ws-queue-number">01</span><span className="ws-queue-title">Paper title</span>
      </button></li></ol>
    </SidebarSection></WorkspaceShell>);
    const queue = container.querySelector(".ws-queue");
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(container.querySelectorAll(".ws-queue")).toHaveLength(1);
    expect(container.querySelector(".ws-queue")).toBe(queue);
    const button = screen.getByRole("button", { name: "Show paper 1 of 1: Paper title" });
    expect(button.closest("[hidden], [inert]")).toBeNull();
    await user.click(button);
    expect(select).toHaveBeenCalledOnce();
  });
  it("opens the compact mobile composer, preserves its draft on close, and restores toggle focus", async () => {
    width = 390;
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    const open = screen.getByRole("button", { name: "Open search" });
    const fields = container.querySelector(".ws-composer-fields");
    expect(fields).toHaveAttribute("hidden");
    expect(screen.queryByRole("searchbox", { name: "Search stored papers" })).not.toBeInTheDocument();
    expect(container.querySelector(".ws-composer")).toHaveAttribute("data-expanded", "false");
    await user.click(open);
    const input = screen.getByRole("searchbox", { name: "Search stored papers" });
    expect(input).toHaveFocus();
    expect(screen.getByRole("button", { name: "Close search" })).toBe(open);
    expect(open).toHaveAttribute("aria-controls", fields?.id);
    expect(container.querySelector(".ws-composer")).toHaveAttribute("data-expanded", "true");
    await user.type(input, "retrieval draft");
    await user.keyboard("{Escape}");
    expect(open).toHaveAccessibleName("Open search");
    expect(open).toHaveFocus();
    expect(fields).toHaveAttribute("hidden");
    await user.click(open);
    expect(screen.getByRole("searchbox", { name: "Search stored papers" })).toHaveValue("retrieval draft");
    await user.clear(input); await user.type(input, "/unknown-command");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(screen.getByText("No available command matches. Try another command.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Close search" }));
    expect(container.querySelector('.ws-composer [data-command="escape"]')).toBeNull();
    await user.click(open);
    expect(input).toHaveValue("/unknown-command");
    expect(screen.getByText("No available command matches. Try another command.")).toBeVisible();
  });
  it("opens and focuses mobile search with slash but does not dispatch into an inert main", async () => {
    width = 390;
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    fireEvent.keyDown(document.body, { key: "/" });
    expect(screen.getByRole("searchbox", { name: "Search stored papers" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(container.querySelector(".ws-composer-fields")).toHaveAttribute("hidden");
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    expect(screen.getByRole("main")).toHaveAttribute("inert");
    fireEvent.keyDown(document.body, { key: "/" });
    expect(container.querySelector(".ws-composer-fields")).toHaveAttribute("hidden");
    expect(screen.queryByRole("searchbox", { name: "Search stored papers" })).not.toBeInTheDocument();
  });
  it("does not execute a hidden composer form even if a submit is dispatched", async () => {
    width = 390;
    const user = userEvent.setup(); const command = vi.fn();
    const { container } = render(<WorkspaceShell><button data-command="next" onClick={command}>Next</button></WorkspaceShell>);
    const toggle = screen.getByRole("button", { name: "Open search" });
    await user.click(toggle);
    await user.type(screen.getByRole("searchbox"), "/next");
    await user.click(screen.getByRole("button", { name: "Close search" }));
    const form = container.querySelector("form.ws-composer");
    if (!form) throw new Error("Composer form missing");
    fireEvent.submit(form);
    expect(command).not.toHaveBeenCalled();
    expect(toggle).toHaveAccessibleName("Open search");
  });
  it("keeps desktop search open without a mobile toggle", () => {
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    expect(screen.getByRole("searchbox", { name: "Search stored papers" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open search" })).not.toBeInTheDocument();
    expect(container.querySelector(".ws-composer-fields")).not.toHaveAttribute("hidden");
  });
  it("keeps mobile navigation outside a closed drawer, then traps and restores focus", async () => {
    width = 390;
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    const toggle = screen.getByRole("button", { name: "Queue & controls" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("link", { name: "Library" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Page control" })).not.toBeInTheDocument();
    expect(container.querySelector(".ws-drawer")).toHaveAttribute("hidden");
    await user.click(toggle);
    const dialog = screen.getByRole("dialog", { name: "Queue & controls" });
    const close = within(dialog).getByRole("button", { name: "Close controls" });
    expect(close).toHaveFocus();
    expect(screen.getByRole("main")).toHaveAttribute("inert");
    await user.tab({ shift: true });
    expect(screen.getByRole("radio", { name: "System" })).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.click(screen.getByRole("radio", { name: "Light" }));
    await user.tab();
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
  });
  it("closes mobile controls from the scrim or close button without unmounting the slot", async () => {
    width = 390;
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    const toggle = screen.getByRole("button", { name: "Queue & controls" });
    const control = container.querySelector(".ws-sidebar-slot button");
    await user.click(toggle);
    fireEvent.click(container.querySelector(".ws-scrim")!);
    expect(toggle).toHaveFocus();
    await user.click(toggle);
    await user.click(screen.getByRole("button", { name: "Close controls" }));
    expect(toggle).toHaveFocus();
    expect(container.querySelector(".ws-sidebar-slot button")).toBe(control);
  });
  it("dismisses a cached drawer on Back or Forward and restores its toggle", async () => {
    width = 390;
    const user = userEvent.setup();
    render(<WorkspaceShell><Page /></WorkspaceShell>);
    const toggle = screen.getByRole("button", { name: "Queue & controls" });
    for (let step = 0; step < 2; step++) {
      await user.click(toggle);
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      fireEvent.popState(window);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(toggle).toHaveFocus();
      expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    }
  });
  it("uses a tablet rail and modal expansion, then restores desktop semantics on resize", async () => {
    width = 900;
    const user = userEvent.setup();
    const { container } = render(<WorkspaceShell><Page /></WorkspaceShell>);
    expect(container.querySelector(".ws-app")).toHaveAttribute("data-rail", "true");
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByRole("dialog", { name: "Workspace controls" })).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Close controls" })).toHaveFocus();
    resize(1440);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("main")).not.toHaveAttribute("inert");
    expect(screen.getByRole("complementary", { name: "Workspace controls" })).toBeInTheDocument();
  });
  it("has stable SSR snapshots and survives blocked preference storage", () => {
    expect(serverSidebarCollapsed()).toBe(false);
    expect(serverSidebarViewport()).toBe("desktop");
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(readSidebarCollapsed()).toBe(false);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    act(() => setSidebarCollapsed(true));
    expect(readSidebarCollapsed()).toBe(true);
    act(() => setSidebarCollapsed(false));
    expect(readSidebarCollapsed()).toBe(false);
  });
  it("applies the rail for this document when storage remains readable but writes fail", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota"); });
    act(() => setSidebarCollapsed(true));
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBeNull();
    expect(readSidebarCollapsed()).toBe(true);
  });
  it("labels item routes Reader and accepts an all-available header without a warning suffix", () => {
    route.path = "/workspace/items/source";
    render(<WorkspaceShell><StageHeaderSlot sources={{ ok: 5, total: 5, worst: "ok" }} /></WorkspaceShell>);
    expect(screen.getByText(/workspace.*reader/)).toBeInTheDocument();
    expect(screen.getByText("5/5 sources")).toBeInTheDocument();
  });
  it("keeps ordinary Tab native, excludes hidden controls, and recaptures escaped focus", async () => {
    width = 390;
    const user = userEvent.setup();
    render(<WorkspaceShell><Page /><SidebarSection label="Extra controls"><button hidden>Hidden</button><button tabIndex={-1}>Skipped</button></SidebarSection></WorkspaceShell>);
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    const close = screen.getByRole("button", { name: "Close controls" });
    await user.tab();
    expect(screen.getByRole("button", { name: "Page control" })).toHaveFocus();
    const main = screen.getByRole("main");
    main.focus();
    fireEvent.keyDown(main, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("radio", { name: "System" })).toHaveFocus();
    main.focus();
    fireEvent.keyDown(main, { key: "Tab" });
    expect(close).toHaveFocus();
    for (const radio of screen.getAllByRole("radio")) (radio as HTMLInputElement).checked = false;
    fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
    expect(screen.getByRole("radio", { name: "Light" })).toHaveFocus();
  });
  it("retains dialog focus if all child controls become untabbable", async () => {
    width = 390;
    render(<WorkspaceShell><Page /></WorkspaceShell>);
    await userEvent.setup().click(screen.getByRole("button", { name: "Queue & controls" }));
    const dialog = screen.getByRole("dialog", { name: "Queue & controls" });
    for (const control of dialog.querySelectorAll<HTMLElement>("a, button, input")) control.tabIndex = -1;
    const event = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    dialog.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(dialog).toHaveFocus();
  });
});
