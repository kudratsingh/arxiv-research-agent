import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveProjects } from "@/components/workspace/Projects";
import type { BoundSource, ContextIndex, EntryRevision, ProjectDetail } from "@/lib/workspace/api";
import { resetDraftMemory } from "@/lib/workspace/draftMemory";
import { work } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => location.pathname, useSearchParams: () => new URLSearchParams(location.search) }));

const projectId = `project-${"a".repeat(32)}`, otherId = `project-${"b".repeat(32)}`;
const reference: BoundSource = {
  work_id: work().work_id, version_id: `${work().work_id}:v1`, anchor: "abstract:3:9",
  version_hash: "digest-1", source_scope: "abstract", material_id: null, material_hash: null, parser_revision: null,
  title: "Pinned baseline source", source_url: "https://example.test/v1", page: null,
  start: 3, end: 9, quote: "earlie", offset_basis: "Unicode code points", available: true, unavailable_reason: null,
};
const note: EntryRevision = {
  ...reference, id: "entry-question", revision: 4, kind: "question", body: "How does the fixed baseline behave?",
  updated_at: "2026-11-05T00:00:00Z", activity_sequence: 3,
};
let current: ProjectDetail, index: ContextIndex;
let writes: string[];

beforeEach(() => {
  resetDraftMemory(); sessionStorage.clear();
  history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`);
  current = {
    id: projectId, revision: 3, data: {
      title: "Controlled baseline study", question: "Can a fixed baseline explain retrieval?", scope: "Retained abstracts",
      constraints: "Fixed compute", next_actions: ["Inspect the retained methods", "Compare baseline assumptions"], status: "active",
    },
    created_at: "now", updated_at: "now", activity_sequence: 2,
    sources: [{ id: "evidence-a", role: "evidence", label: "Check the baseline", status: "active", reference }],
    entries: [{ entry_id: note.id, entry_revision: 4, current_revision: 6, entry: note, available: true }],
    artifacts: [{ id: "artifact-one", revision: 2, authorship: "manual", verification: "unverified", data: { kind: "hypothesis", body: "A confound may remain.", entry: null, evidence_link_ids: ["evidence-a"] } }], threads: [],
  };
  index = {
    principal_key_id: "owner-a", preferences: { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } },
    projects: [current, { ...current, id: otherId, data: { ...current.data, title: "A separate archived study", status: "archived" } }], threads: [],
  };
  writes = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.body) writes.push(url);
    return Response.json(url.endsWith("/context") ? index : current);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("project presentation", () => {
  it("makes project titles, status and the current selection scannable without revision noise", async () => {
    render(<LiveProjects />);
    const list = await screen.findByRole("list", { name: "Owned projects" });
    const selected = within(list).getByRole("link", { name: current.data.title });
    expect(selected).toHaveAttribute("aria-current", "page");
    expect(selected).toHaveAttribute("href", `/workspace/projects?mode=research&project=${projectId}`);
    expect(within(selected.closest("li")!).getByText("Current project")).toBeVisible();
    expect(within(selected.closest("li")!).getByText("active")).toBeVisible();
    const other = within(list).getByRole("link", { name: "A separate archived study" });
    expect(other).not.toHaveAttribute("aria-current");
    expect(within(other.closest("li")!).getByText("archived")).toBeVisible();
    expect(list).not.toHaveTextContent(/revision|project-[a-f0-9]/);
    expect(writes).toEqual([]);
  });

  it("groups the question, next steps and evidence into a readable research hierarchy", async () => {
    render(<LiveProjects />);
    const workspace = await screen.findByRole("region", { name: "Project workspace" });
    expect(within(workspace).getByRole("heading", { name: current.data.title, level: 2 })).toBeVisible();
    const question = within(workspace).getByRole("heading", { name: "Research question", level: 3 });
    expect(question.parentElement).toHaveTextContent(current.data.question);
    expect(question.parentElement).toHaveTextContent("ScopeRetained abstractsConstraintsFixed compute");
    const actions = within(workspace).getByRole("region", { name: "Next actions" });
    expect(within(actions).getAllByRole("listitem").map(item => item.textContent)).toEqual(current.data.next_actions);
    const evidence = within(workspace).getByRole("region", { name: "Sources and exact evidence" });
    expect(within(evidence).getByRole("heading", { name: reference.title, level: 4 })).toBeVisible();
    expect(within(evidence).getByText(reference.quote!)).toBeVisible();
    expect(within(evidence).getByText("Retained evidence passage · active")).toBeVisible();
    expect(within(workspace).getByText("Manual · unverified")).toBeVisible();
  });

  it("keeps record and exact source identity in native disclosures without changing the Reader href", async () => {
    render(<LiveProjects />); await screen.findByRole("region", { name: "Project workspace" });
    for (const label of ["Project details", "Exact source details", "Linked note details", "Authored record details"]) {
      const summary = screen.getByText(label, { selector: "summary" });
      const disclosure = summary.closest("details")!;
      expect(disclosure).not.toHaveAttribute("open");
      fireEvent.click(summary);
      expect(disclosure).toHaveAttribute("open");
    }
    expect(screen.getByText(`Project ID: ${projectId}`)).toBeVisible();
    expect(screen.getByText("Project revision 3")).toBeVisible();
    expect(screen.getByText(reference.version_id)).toBeVisible();
    expect(screen.getByText(reference.anchor)).toBeVisible();
    expect(screen.getByText("Record revision 2")).toBeVisible();
    const params = new URLSearchParams({ version: reference.version_id, return_to: `/workspace/projects?mode=research&project=${projectId}`, mode: "research", project: projectId });
    expect(screen.getByRole("link", { name: "Open exact project passage →" })).toHaveAttribute("href", `/workspace/items/${encodeURIComponent(reference.work_id)}?${params}#${encodeURIComponent(reference.anchor)}`);
    expect(writes).toEqual([]);
  });

  it("leaves later-note-revision warnings visible while preserving the historical passage", async () => {
    render(<LiveProjects />); await screen.findByRole("region", { name: "Project workspace" });
    const notes = screen.getByRole("region", { name: "Linked shared notes" });
    const revisionWarning = within(notes).getByText("linked revision 4 · current revision 6");
    expect(revisionWarning).toBeVisible(); expect(revisionWarning.closest("details")).toBeNull();
    expect(within(notes).getByText(/without substituting a later note revision/)).toBeVisible();
    expect(within(notes).getByText(note.body)).toBeVisible();
    const link = new URL(within(notes).getByRole("link", { name: "Open linked note source →" }).getAttribute("href")!, location.origin);
    expect(link.searchParams.has("entry")).toBe(false);
    expect(link.searchParams.get("version")).toBe(reference.version_id);
    expect(link.searchParams.get("project")).toBe(projectId);
    expect(link.searchParams.get("return_to")).toBe(`/workspace/projects?mode=research&project=${projectId}`);
    expect(decodeURIComponent(link.hash)).toBe(`#${reference.anchor}`);
  });

  it("keeps unavailable and archived decisions visible outside the identity disclosures", async () => {
    current.data.status = "archived";
    current.sources[0]!.reference = { ...reference, available: false, unavailable_reason: "Missing pinned version" };
    current.entries[0] = { entry_id: note.id, entry_revision: 4, current_revision: null, entry: null, available: false };
    render(<LiveProjects />); await screen.findByRole("region", { name: "Project workspace" });
    expect(screen.getByText(/This pinned source is unavailable/)).toBeVisible();
    expect(screen.queryByRole("link", { name: "Open exact project passage →" })).not.toBeInTheDocument();
    expect(screen.getByText("linked revision 4 · current revision unavailable")).toBeVisible();
    expect(screen.getByText(/This linked entry is unavailable/)).toBeVisible();
    expect(screen.getByText(/This project is archived/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Remove project link" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add authored research record" })).toBeDisabled();
    expect(writes).toEqual([]);
  });
});
