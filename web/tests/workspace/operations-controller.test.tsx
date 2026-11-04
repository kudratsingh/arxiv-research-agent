import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { LiveOperations } from "@/components/workspace/Operations";
import { SyntheticPreviewProvider } from "@/components/workspace/PreviewContext";
import type { WorkspaceState } from "@/lib/workspace/api";
import { workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/operations" }));
let current: WorkspaceState;
let calls: { path: string; body: Record<string, unknown> }[];
let scheduleFailure: number;
let refreshFailure: number;
let gate: { resolve?: (response: Response) => void } | null;
function fixture(): WorkspaceState {
  const base = workspace();
  return workspace({ sources: [
    { source_id: "first", name: "First source", status: "ok", last_success_at: "2026-11-02T15:00:00Z", receipt: { request_count: 1 } },
    { source_id: "second", name: "Second source", status: "failed", last_success_at: null, receipt: { error: "Source timeout" } },
    { source_id: "third", name: "Third source", status: "partial", last_success_at: null, receipt: { truncated: true } },
    { source_id: "fourth", name: "Fourth source", status: "not_checked", last_success_at: null, receipt: {} },
  ], schedule: { ...base.schedule, revision: 3 }, tasks: [{ id: "task-1", kind: "check", status: "waiting", due_at: "2026-11-03T15:00:00Z", attempts: 2, reason: "Waiting for an explicit time" }] });
}
beforeEach(() => {
  current = fixture(); calls = []; scheduleFailure = 0; refreshFailure = 0; gate = null;
  localStorage.clear(); sessionStorage.clear(); history.replaceState(null, "", "/workspace/operations");
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {};
    calls.push({ path, body });
    if (path === "state") return Response.json(current);
    if (path === "refresh") return refreshFailure ? new Response(null, { status: refreshFailure }) : Response.json(current);
    if (path === "schedule") {
      if (gate) return new Promise<Response>((resolve) => { gate!.resolve = resolve; });
      if (scheduleFailure) return new Response(null, { status: scheduleFailure });
      current.schedule = { ...(body.data as WorkspaceState["schedule"]), revision: current.schedule.revision + 1, next_check: null };
      return Response.json(current.schedule);
    }
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function mount() { const view = render(<WorkspaceShell><LiveOperations /></WorkspaceShell>); await screen.findByRole("heading", { name: "First source" }); return view; }

describe("Sources and checks controller", () => {
  it("opens without a mutation and shows one focused source with explicit queue status and receipt", async () => {
    const user = userEvent.setup(); await mount();
    expect(calls.map((call) => call.path)).toEqual(["state"]);
    expect(screen.getAllByRole("article").filter((article) => article.classList.contains("workspace-source"))).toHaveLength(1);
    const queue = screen.getByRole("list", { name: "Source checks queue" });
    expect(within(queue).getAllByRole("button")).toHaveLength(4);
    expect(within(queue).getByRole("button", { name: "Show source 2 of 4: Second source · failed" })).toHaveTextContent("failed");
    await user.click(within(queue).getByRole("button", { name: "Show source 2 of 4: Second source · failed" }));
    expect(screen.getByRole("heading", { name: "Second source" })).toBeInTheDocument();
    expect(new URL(location.href).searchParams.get("focus")).toBe("second");
    await user.click(screen.getByText("Inspect this check’s receipt"));
    expect(screen.getByRole("region", { name: "Second source check receipt" })).toHaveTextContent("Source timeout");
    expect(screen.getByText("No successful check recorded")).toBeInTheDocument();
    expect(screen.getAllByText("Recurring schedule disabled")).toHaveLength(1);
    expect(screen.getByText(/Metadata checks do not construct model clients/)).toBeInTheDocument();
  });
  it("navigates source buttons and keyboard without wrapping or refetching", async () => {
    const user = userEvent.setup(); await mount();
    expect(screen.getByRole("button", { name: "Previous source" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Next source" }));
    expect(screen.getByRole("heading", { name: "Second source" })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "j" }); expect(screen.getByRole("heading", { name: "Third source" })).toBeInTheDocument();
    fireEvent.keyDown(document.body, { key: "k" }); expect(screen.getByRole("heading", { name: "Second source" })).toBeInTheDocument();
    const zone = screen.getByRole("textbox", { name: "IANA timezone" }); fireEvent.keyDown(zone, { key: "j" });
    expect(screen.getByRole("heading", { name: "Second source" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show source 4 of 4: Fourth source · not checked" }));
    expect(screen.getByRole("button", { name: "Next source" })).toBeDisabled();
    expect(calls).toHaveLength(1);
  });
  it("restores the selected source from its URL and falls back safely for an unknown source", async () => {
    history.replaceState(null, "", "/workspace/operations?focus=third");
    const view = render(<WorkspaceShell><LiveOperations /></WorkspaceShell>);
    expect(await screen.findByRole("heading", { name: "Third source" })).toBeInTheDocument();
    view.unmount();
    render(<WorkspaceShell><LiveOperations /></WorkspaceShell>);
    expect(await screen.findByRole("heading", { name: "Third source" })).toBeInTheDocument();
    act(() => { history.pushState(null, "", "/workspace/operations?focus=unknown"); window.dispatchEvent(new PopStateEvent("popstate")); });
    expect(screen.getByRole("heading", { name: "First source" })).toBeInTheDocument();
  });
  it("closes the mobile drawer after selecting a source", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); render(<WorkspaceShell><LiveOperations /></WorkspaceShell>);
    await screen.findByRole("heading", { name: "First source" });
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(screen.getByRole("button", { name: "Show source 2 of 4: Second source · failed" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Second source" })).toBeInTheDocument();
    expect(calls.map((call) => call.path)).toEqual(["state"]);
  });
  it("sends only the explicitly requested source or all sources and never calls a model", async () => {
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Check First source now" }));
    await waitFor(() => expect(calls.filter((call) => call.path === "refresh")).toHaveLength(1));
    expect(calls.find((call) => call.path === "refresh")?.body).toEqual({ source_ids: ["first"] });
    await waitFor(() => expect(screen.getByRole("button", { name: "Check sources now" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Check sources now" }));
    await waitFor(() => expect(calls.filter((call) => call.path === "refresh")).toHaveLength(2));
    expect(calls.filter((call) => call.path === "refresh")[1]?.body).toEqual({ source_ids: [] });
    expect(calls.every((call) => ["state", "refresh"].includes(call.path))).toBe(true);
  });
  it("uses a native associated form, disables controls during a save and forces recurrence off", async () => {
    const user = userEvent.setup(); await mount(); gate = {};
    const zone = screen.getByRole("textbox", { name: "IANA timezone" });
    fireEvent.change(zone, { target: { value: "Europe/London" } });
    fireEvent.change(screen.getByLabelText("Proposed local check time"), { target: { value: "08:15" } });
    expect(screen.getByText("Unsaved schedule preferences.")).toBeInTheDocument();
    const submit = screen.getByRole("button", { name: "Save preferences · keep schedule disabled" });
    const form = zone.closest("form"); expect((submit as HTMLButtonElement).form).toBe(form);
    await user.click(submit); await waitFor(() => expect(gate?.resolve).toBeDefined());
    expect(zone).toBeDisabled(); expect(screen.getByLabelText("Proposed local check time")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Check First source now" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Check sources now" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Show source 2 of 4: Second source · failed" })).toBeDisabled();
    const sent = calls.find((call) => call.path === "schedule")?.body;
    expect(sent).toMatchObject({ revision: 3, data: { enabled: false, timezone: "Europe/London", local_time: "08:15" } });
    if (!form || !gate?.resolve) throw new Error("Schedule request missing");
    fireEvent.submit(form); expect(calls.filter((call) => call.path === "schedule")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Check First source now" }));
    fireEvent.click(screen.getByRole("button", { name: "Show source 2 of 4: Second source · failed" }));
    fireEvent.keyDown(document.body, { key: "j" });
    expect(screen.getByRole("heading", { name: "First source" })).toBeInTheDocument();
    expect(calls.filter((call) => call.path === "refresh")).toHaveLength(0);
    const complete = gate.resolve; await act(async () => complete(Response.json({ revision: 4, enabled: false, timezone: "Europe/London", local_time: "08:15", next_check: null })));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("remain disabled"));
    expect(screen.queryByText("Unsaved schedule preferences.")).not.toBeInTheDocument();
  });
  it("keeps the draft base revision across a source refresh that returns a newer schedule", async () => {
    const user = userEvent.setup(); await mount();
    fireEvent.change(screen.getByRole("textbox", { name: "IANA timezone" }), { target: { value: "Europe/London" } });
    current.schedule = { ...current.schedule, revision: 8, timezone: "Asia/Tokyo" };
    await user.click(screen.getByRole("button", { name: "Check First source now" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Source check finished"));
    expect(screen.getByRole("textbox", { name: "IANA timezone" })).toHaveValue("Europe/London");
    scheduleFailure = 409;
    await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("another tab"));
    expect(calls.find((call) => call.path === "schedule")?.body).toMatchObject({ revision: 3, data: { timezone: "Europe/London", enabled: false } });
    expect(screen.getByRole("textbox", { name: "IANA timezone" })).toHaveValue("Europe/London");
  });
  it("retains a conflicted draft and its original revision and retry identity", async () => {
    const user = userEvent.setup(); await mount();
    fireEvent.change(screen.getByRole("textbox", { name: "IANA timezone" }), { target: { value: "Europe/London" } });
    scheduleFailure = 409; await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("another tab"));
    expect(screen.getByRole("textbox", { name: "IANA timezone" })).toHaveValue("Europe/London");
    expect(screen.getByText("Unsaved schedule preferences.")).toBeInTheDocument();
    scheduleFailure = 0; await user.click(screen.getByRole("button", { name: /Save preferences/ }));
    await waitFor(() => expect(calls.filter((call) => call.path === "schedule")).toHaveLength(2));
    const attempts = calls.filter((call) => call.path === "schedule");
    expect(attempts[0]?.body.revision).toBe(3); expect(attempts[1]?.body.revision).toBe(3);
    expect(attempts[1]?.body.request_id).toBe(attempts[0]?.body.request_id);
  });
  it("reports a failed check without replacing the last receipt, then retries", async () => {
    const user = userEvent.setup(); await mount(); refreshFailure = 503;
    await user.click(screen.getByRole("button", { name: "Check First source now" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("retry when the service is available"));
    expect(screen.getByRole("heading", { name: "First source" })).toBeInTheDocument();
    refreshFailure = 0; await user.click(screen.getByRole("button", { name: "Check First source now" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Source check finished"));
    expect(calls.filter((call) => call.path === "refresh")).toHaveLength(2);
  });
  it("can pause an enabled schedule while preserving the proposed fields", async () => {
    current.schedule = { ...current.schedule, enabled: true };
    const user = userEvent.setup(); await mount();
    expect(screen.getByText("A recurring schedule is enabled")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pause schedule and save preferences" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("remain disabled"));
    expect(calls.find((call) => call.path === "schedule")?.body.data).toMatchObject({ enabled: false, timezone: "America/Los_Angeles", local_time: "07:00" });
    expect(screen.getByText("Recurring schedule disabled")).toBeInTheDocument();
  });
  it("shows honest empty source and task states without an automatic check", async () => {
    current.sources = []; current.tasks = [];
    render(<WorkspaceShell><LiveOperations /></WorkspaceShell>);
    expect(await screen.findByText("No sources are configured.")).toBeInTheDocument();
    expect(screen.getByText(/No queued or recorded scheduled tasks/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous source" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next source" })).toBeDisabled();
    expect(calls.map((call) => call.path)).toEqual(["state"]);
  });
  it("shows missing task metadata as unrecorded rather than inventing a result", async () => {
    current.tasks = [{ id: "minimal-task" }, { id: "legacy-task", kind: "source scan", state: "waiting", attempt: 2 }];
    await mount();
    const articles = screen.getAllByRole("article").filter((article) => article.classList.contains("workspace-inline-note"));
    expect(articles).toHaveLength(2);
    expect(articles[0]).toHaveTextContent("metadata check · unknown");
    expect(articles[0]).toHaveTextContent("Attempt not recorded");
    expect(articles[1]).toHaveTextContent("source scan · waiting");
    expect(articles[1]).toHaveTextContent("Attempt 2");
    expect(calls.map((call) => call.path)).toEqual(["state"]);
  });
  it("disables live source checks in the synthetic design preview", async () => {
    current.tasks = [];
    render(<SyntheticPreviewProvider enabled><WorkspaceShell><LiveOperations /></WorkspaceShell></SyntheticPreviewProvider>);
    await screen.findByRole("heading", { name: "First source" });
    expect(screen.getByRole("button", { name: "Check First source now" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Check sources now" })).toBeDisabled();
    expect(screen.getByText(/Live source checks are disabled in this synthetic design preview/)).toBeInTheDocument();
    expect(screen.getByText(/Source checks disabled in this synthetic preview/)).toBeInTheDocument();
    expect(screen.queryByText(/Manual source checks remain available/)).not.toBeInTheDocument();
    expect(calls.map((call) => call.path)).toEqual(["state"]);
  });
});
