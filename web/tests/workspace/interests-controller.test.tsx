import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkspaceShell } from "@/components/workspace/Shell";
import { LiveInterests } from "@/components/workspace/Interests";
import { loadInterestDraft } from "@/lib/workspace/interestDrafts";
import type { ProfileData, WorkspaceState } from "@/lib/workspace/api";
import { workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => "/workspace/interests" }));
let current: WorkspaceState;
let calls: { path: string; body: Record<string, unknown> }[];
let profileFailure: number;
let failStage: "edition" | "state" | "";
let mismatch: boolean;
let acknowledged: { id: string; revision: number; data: ProfileData } | null;
let pending: { resolve?: (response: Response) => void } | null;
const key = (owner: string) => `arxiv.workspace.interest-draft.v1:${encodeURIComponent(owner)}`;
beforeEach(() => {
  current = workspace(); calls = []; profileFailure = 0; failStage = ""; mismatch = false; acknowledged = null; pending = null;
  sessionStorage.clear(); localStorage.clear(); history.replaceState(null, "", "/workspace/interests");
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: false, onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, "http://localhost").pathname.replace("/api/workspace/", "");
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}; calls.push({ path, body });
    if (path === "state") {
      if (acknowledged && failStage === "state") return new Response(null, { status: 503 });
      if (acknowledged && mismatch) return Response.json({ ...current, profile: { revision: acknowledged.revision + 1, data: { ...current.profile.data, research_question: "Remote update" } } });
      return Response.json(current);
    }
    if (path === "profile") {
      if (pending) return new Promise<Response>((resolve) => { pending!.resolve = resolve; });
      if (profileFailure) return new Response(null, { status: profileFailure });
      const id = String(body.request_id); if (!acknowledged || acknowledged.id !== id) acknowledged = { id, revision: current.profile.revision + 1, data: body.data as ProfileData };
      current.profile = { revision: acknowledged.revision, data: acknowledged.data }; return Response.json(current.profile);
    }
    if (path === "edition") return failStage === "edition" ? new Response(null, { status: 503 }) : Response.json({});
    throw new Error(`Unexpected request: ${path}`);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
async function mount() { const view = render(<WorkspaceShell><LiveInterests /></WorkspaceShell>); await screen.findByRole("textbox", { name: "Your current research question" }); return view; }
function changeQuestion(value: string) { fireEvent.change(screen.getByRole("textbox", { name: "Your current research question" }), { target: { value } }); }

describe("Interests controller", () => {
  it("shows the server's saved reading-window allocation without recalculating it", async () => {
    current.allocation_previews = [{ minutes: 15, slots: 3, requested_fraction: 0.3, planned_max_exploration_slots: 0, max_exploration_slots: 0, actual_exploration_slots: 0, actual_items: 3, actual_fraction: 0, unused_slots: 0 }];
    await mount();
    expect(screen.getByText(/15 min · 0 exploration items/)).toBeInTheDocument();
    expect(screen.getByText(/among 3 selected \(0%\).*Requested cap: 30%/)).toBeInTheDocument();
    expect(calls.every((call) => call.path === "state")).toBe(true);
  });
  it("retains the private draft when explicit discard cannot reload the saved profile", async () => {
    const user = userEvent.setup(); await mount(); changeQuestion("Retain my draft");
    const originalFetch = vi.mocked(fetch).getMockImplementation();
    if (!originalFetch) throw new Error("Missing workspace fetch mock");
    vi.mocked(fetch).mockImplementation((url, init) => new URL(String(url), "http://localhost").pathname.endsWith("/state")
      ? Promise.resolve(new Response(null, { status: 503 })) : originalFetch(url, init));
    await user.click(screen.getByRole("button", { name: "Discard draft and reload saved profile" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("retry when the service is available"));
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Retain my draft");
    expect(loadInterestDraft("owner-a")?.data.research_question).toBe("Retain my draft");
    expect(calls.every((call) => call.path === "state")).toBe(true);
  });
  it("opens and navigates the section index without any writes and keeps the native save form association", async () => {
    const user = userEvent.setup(); await mount();
    expect(calls.map((call) => call.path)).toEqual(["state"]);
    const nav = screen.getByRole("navigation", { name: "Interest sections" });
    expect(within(nav).getAllByRole("link")).toHaveLength(5);
    await user.click(within(nav).getByRole("link", { name: "Topics" }));
    expect(calls.map((call) => call.path)).toEqual(["state"]);
    const input = screen.getByRole("textbox", { name: "Your current research question" });
    const save = screen.getByRole("button", { name: "Save interests and question" });
    expect((save as HTMLButtonElement).form).toBe(input.closest("form"));
  });
  it("recovers raw multiline terms per account without posting on open", async () => {
    const first = await mount();
    const raw = "  agent memory  \n\n  evaluation \n"; const exclusions = "  adverts\n\n  spam ";
    fireEvent.change(screen.getByRole("textbox", { name: /Custom interests or watch terms/ }), { target: { value: raw } });
    fireEvent.change(screen.getByRole("textbox", { name: /Exclude these terms/ }), { target: { value: exclusions } });
    changeQuestion("Account A draft");
    expect(loadInterestDraft("owner-a")?.customRaw).toBe(raw); first.unmount();
    current.principal_key_id = "owner-b"; const second = await mount();
    expect(screen.getByRole("textbox", { name: "Your current research question" })).not.toHaveValue("Account A draft");
    changeQuestion("Account B draft"); second.unmount();
    current.principal_key_id = "owner-a"; await mount();
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Account A draft");
    expect(screen.getByRole("textbox", { name: /Custom interests or watch terms/ })).toHaveValue(raw);
    expect(screen.getByRole("textbox", { name: /Exclude these terms/ })).toHaveValue(exclusions);
    expect(loadInterestDraft("owner-b")?.data.research_question).toBe("Account B draft");
    expect(calls.every((call) => call.path === "state")).toBe(true);
  });
  it("normalizes raw terms only on confirmed save and keeps the submitted revision", async () => {
    const user = userEvent.setup(); await mount();
    fireEvent.change(screen.getByRole("textbox", { name: /Custom interests or watch terms/ }), { target: { value: "  agent memory  \n\n evaluation \n" } });
    fireEvent.change(screen.getByRole("textbox", { name: /Exclude these terms/ }), { target: { value: "  ads  \n spam \n" } });
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved on the server"));
    const profile = calls.find((call) => call.path === "profile")?.body;
    expect(profile).toMatchObject({ revision: 1, data: { custom_topics: ["agent memory", "evaluation"], exclusions: ["ads", "spam"] } });
    expect(calls.filter((call) => call.path === "edition")).toHaveLength(1);
    expect(loadInterestDraft("owner-a")).toBeNull();
  });
  it("guards all fields, save and discard while the profile request is pending", async () => {
    const user = userEvent.setup(); await mount(); changeQuestion("Pending private draft"); pending = {};
    const question = screen.getByRole("textbox", { name: "Your current research question" });
    const form = question.closest("form"); if (!form) throw new Error("Interests form missing");
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(pending?.resolve).toBeDefined());
    expect(question).toBeDisabled(); expect(screen.getByRole("button", { name: "Saving interests…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard draft and reload saved profile" })).toBeDisabled();
    fireEvent.submit(form); expect(calls.filter((call) => call.path === "profile")).toHaveLength(1);
    expect(screen.getByRole("status")).not.toHaveTextContent("saved on the server");
    const complete = pending?.resolve; if (!complete) throw new Error("Profile request missing");
    await act(async () => complete(new Response(null, { status: 503 })));
    await waitFor(() => expect(question).toBeEnabled()); expect(question).toHaveValue("Pending private draft");
  });
  it("preserves an unreadable recovery copy that appears before an acknowledged save completes", async () => {
    const user = userEvent.setup(); await mount(); changeQuestion("Saved question"); pending = {};
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(pending?.resolve).toBeDefined());
    const original = "{new private recovery copy";
    sessionStorage.setItem(key("owner-a"), original);
    const request = calls.find((call) => call.path === "profile");
    if (!request || !pending?.resolve) throw new Error("Profile request missing");
    current.profile = { revision: 2, data: request.body.data as ProfileData };
    const complete = pending.resolve;
    await act(async () => complete(Response.json(current.profile)));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved on the server. The local recovery copy could not be cleared"));
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Saved question");
    expect(sessionStorage.getItem(key("owner-a"))).toBe(original);
    expect(calls.filter((call) => call.path === "profile")).toHaveLength(1);
  });
  it("retries a failed profile request with the same identity after remount", async () => {
    const user = userEvent.setup(); const view = await mount(); changeQuestion("Retry draft"); profileFailure = 503;
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("retry when the service is available"));
    const firstId = calls.find((call) => call.path === "profile")?.body.request_id; expect(firstId).toEqual(expect.any(String));
    view.unmount(); profileFailure = 0; await mount();
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Retry draft");
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved on the server"));
    expect(calls.filter((call) => call.path === "profile")[1]?.body.request_id).toBe(firstId);
  });
  it("retains a 409 draft and its base revision until explicit discard reloads server data", async () => {
    const user = userEvent.setup(); await mount(); changeQuestion("Conflicted draft"); profileFailure = 409;
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("another tab"));
    expect(loadInterestDraft("owner-a")?.baseRevision).toBe(1);
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Conflicted draft");
    current.profile = { revision: 2, data: { ...current.profile.data, research_question: "Remote saved question" } };
    await user.click(screen.getByRole("button", { name: "Discard draft and reload saved profile" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Remote saved question"));
    expect(loadInterestDraft("owner-a")).toBeNull();
  });
  it.each(["edition", "state"] as const)("keeps the draft and request identity if %s fails after profile acknowledgment", async (failed) => {
    const user = userEvent.setup(); const view = await mount(); changeQuestion("Acknowledged but unfinished"); failStage = failed;
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("retry when the service is available"));
    const first = calls.find((call) => call.path === "profile")?.body; expect(loadInterestDraft("owner-a")?.data.research_question).toBe("Acknowledged but unfinished");
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Acknowledged but unfinished");
    view.unmount(); failStage = ""; await mount();
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved on the server"));
    const second = calls.filter((call) => call.path === "profile")[1]?.body;
    expect(second?.revision).toBe(1); expect(second?.request_id).toBe(first?.request_id);
    expect(loadInterestDraft("owner-a")).toBeNull();
  });
  it("retains the acknowledged request identity across equivalent raw edits and remount", async () => {
    const user = userEvent.setup(); const view = await mount();
    const terms = screen.getByRole("textbox", { name: /Custom interests or watch terms/ });
    fireEvent.change(terms, { target: { value: "agent memory" } });
    failStage = "edition";
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("retry when the service is available"));
    const first = calls.find((call) => call.path === "profile")?.body;
    expect(first?.request_id).toEqual(expect.any(String));
    fireEvent.change(terms, { target: { value: "agent memory\nextra term" } });
    fireEvent.change(terms, { target: { value: "agent memory\n" } });
    expect(loadInterestDraft("owner-a")?.attempt?.id).toBe(first?.request_id);
    view.unmount(); failStage = ""; await mount();
    expect(screen.getByRole("textbox", { name: /Custom interests or watch terms/ })).toHaveValue("agent memory\n");
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("saved on the server"));
    const retry = calls.filter((call) => call.path === "profile")[1]?.body;
    expect(retry?.request_id).toBe(first?.request_id);
    expect(retry?.revision).toBe(first?.revision);
    expect(retry?.data).toEqual(first?.data);
  });
  it("keeps local edits when the reloaded profile differs from the acknowledged revision", async () => {
    const user = userEvent.setup(); await mount(); changeQuestion("Keep local draft"); mismatch = true;
    await user.click(screen.getByRole("button", { name: "Save interests and question" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("different profile revision"));
    expect(screen.getByRole("textbox", { name: "Your current research question" })).toHaveValue("Keep local draft");
    expect(loadInterestDraft("owner-a")?.data.research_question).toBe("Keep local draft");
  });
  it("does not overwrite malformed recovery text and guards leaving an unrecoverable draft", async () => {
    const original = "{malformed private original"; sessionStorage.setItem(key("owner-a"), original);
    await mount(); changeQuestion("Unsaved local text");
    expect(sessionStorage.getItem(key("owner-a"))).toBe(original);
    expect(screen.getByRole("status")).toHaveTextContent("Browser recovery is unavailable");
    const link = screen.getByRole("link", { name: "Library" }); const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => { link.dispatchEvent(event); }); expect(event.defaultPrevented).toBe(true);
    expect(window.dispatchEvent(new Event("beforeunload", { cancelable: true }))).toBe(false);
    expect(calls.every((call) => call.path === "state")).toBe(true);
    await userEvent.setup().click(screen.getByRole("button", { name: "Discard draft and reload saved profile" }));
    await waitFor(() => expect(sessionStorage.getItem(key("owner-a"))).toBeNull());
  });
  it("keeps another account's recovery intact when this account cannot write browser storage", async () => {
    const other = JSON.stringify({ version: 1, baseRevision: 5, data: { ...current.profile.data, research_question: "Other account text" }, customRaw: null, exclusionsRaw: null });
    sessionStorage.setItem(key("owner-b"), other);
    await mount();
    const setItem = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, name, value) {
      if (this === sessionStorage) throw new Error("storage unavailable");
      return setItem.call(this, name, value);
    });
    changeQuestion("Cannot recover this edit");
    expect(screen.getByRole("status")).toHaveTextContent("Browser recovery is unavailable");
    expect(sessionStorage.getItem(key("owner-b"))).toBe(other);
    expect(sessionStorage.getItem(key("owner-a"))).toBeNull();
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => { screen.getByRole("link", { name: "Library" }).dispatchEvent(event); });
    expect(event.defaultPrevented).toBe(true);
    expect(calls.every((call) => call.path === "state")).toBe(true);
  });
  it("closes the mobile drawer when choosing a section without writing preferences", async () => {
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({ media: query, matches: query.includes("767"), onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() })));
    const user = userEvent.setup(); await mount();
    await user.click(screen.getByRole("button", { name: "Queue & controls" }));
    await user.click(within(screen.getByRole("navigation", { name: "Interest sections" })).getByRole("link", { name: "Terms & boundaries" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(document.getElementById("interest-terms")).toHaveFocus());
    expect(calls.map((call) => call.path)).toEqual(["state"]);
  });
});
