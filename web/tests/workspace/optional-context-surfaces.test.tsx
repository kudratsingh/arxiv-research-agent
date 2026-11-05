import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveInterests } from "@/components/workspace/Interests";
import ReaderQueue from "@/components/workspace/ReaderQueue";
import { workspace } from "./fixtures";
vi.mock("next/navigation", () => ({ usePathname: () => location.pathname }));
beforeEach(() => { sessionStorage.clear(); history.replaceState(null, "", "/workspace/interests"); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
function open(text: string) { const details = screen.getByText(text).closest("details")!; act(() => { details.open = true; details.dispatchEvent(new Event("toggle")); }); }
describe("optional context surfaces mounted from their real entry points", () => {
  it("copies only the saved organizing question into an explicit project, then links its saved identity", async () => {
    const state = workspace(), writes: { path: string; body: Record<string, unknown> }[] = [];
    state.profile.data.research_question = "Saved organizing question";
    const id = `project-${"e".repeat(32)}`;
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null;
      if (body) { writes.push({ path: url, body }); return Response.json({ id, revision: 1, data: body.data }); }
      return Response.json(state);
    }));
    render(<LiveInterests />); await screen.findByLabelText("Your current research question");
    fireEvent.change(screen.getByLabelText("Your current research question"), { target: { value: "Unsaved replacement" } });
    open("Use the saved organizing question for a project");
    expect(await screen.findByLabelText("Research question")).toHaveValue("Saved organizing question"); expect(writes).toEqual([]);
    fireEvent.change(screen.getByLabelText("Project title"), { target: { value: "Explicit investigation" } });
    fireEvent.submit(screen.getByRole("form", { name: "Create research project" }));
    expect(await screen.findByRole("link", { name: "Open saved project →" })).toHaveAttribute("href", expect.stringContaining(`project=${id}`));
    expect(writes).toHaveLength(1); expect(writes[0]!.path).toContain("/context/projects");
    expect(screen.getByLabelText("Your current research question")).toHaveValue("Unsaved replacement");
  });
  it("saves optional learning preferences and reloads context without rewriting interests", async () => {
    const state = workspace(), writes: string[] = []; let reads = 0;
    const preferences = { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.body) { writes.push(url); return Response.json({ revision: 2, data: JSON.parse(String(init.body)).data }); }
      if (url.endsWith("/context")) return Response.json({ principal_key_id: state.principal_key_id, preferences, projects: [], threads: [] });
      reads++; return Response.json(state);
    }));
    render(<LiveInterests />); await screen.findByLabelText("Your current research question");
    open("Learning preferences · optional background and goals");
    fireEvent.change(await screen.findByLabelText("Declared background (optional)"), { target: { value: "Linear algebra" } });
    fireEvent.submit(screen.getByRole("form", { name: "Learning preferences" }));
    await screen.findByText(/Learning preferences saved on the server/);
    await waitFor(() => expect(reads).toBeGreaterThan(1)); expect(writes).toEqual(["/api/workspace/context/preferences"]);
  });
  it("keeps queue links unfocusable and prevents their navigation during a pending write", () => {
    const target = { workId: "work", title: "Exact paper", href: "/workspace/items/work?version=v1#abstract:1:3" };
    const view = render(<ReaderQueue targets={[target]} currentId="work" blocked />);
    const link = screen.getByRole("link"); expect(link).toHaveAttribute("aria-current", "true"); expect(link).toHaveAttribute("tabindex", "-1");
    expect(fireEvent.click(link)).toBe(false);
    view.rerender(<ReaderQueue targets={[target]} currentId="other" blocked={false} />);
    expect(link).not.toHaveAttribute("aria-current"); expect(link).not.toHaveAttribute("aria-disabled"); expect(fireEvent.click(link)).toBe(true);
  });
});
