import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import ProjectEditor from "@/components/workspace/ProjectEditor";
import ThreadEditor from "@/components/workspace/ThreadEditor";
import ArtifactEditor from "@/components/workspace/ArtifactEditor";
import LearningPreferences from "@/components/workspace/LearningPreferences";
import ReaderContextActions from "@/components/workspace/ReaderContextActions";
import { LiveProjects } from "@/components/workspace/Projects";
import { LiveLearningThread } from "@/components/workspace/LearningThread";
import { resetDraftMemory } from "@/lib/workspace/draftMemory";
import type { BoundSource, ContextIndex, EntryRevision, LearningThread, ProjectDetail, ResumeContext } from "@/lib/workspace/api";
import { work } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => location.pathname, useSearchParams: () => new URLSearchParams(location.search) }));
const projectId = `project-${"a".repeat(32)}`, threadId = `thread-${"b".repeat(32)}`;
const source: NonNullable<LearningThread["data"]["source"]> = { work_id: work().work_id, version_id: `${work().work_id}:v1`, anchor: "abstract:3:9", version_hash: "digest-1", source_scope: "abstract", material_id: null, material_hash: null, parser_revision: null };
const bound: BoundSource = { ...source, version_hash: "digest-1", material_id: null, material_hash: null, parser_revision: null, source_scope: "abstract", title: "Pinned v1 source", source_url: "https://example.test/v1", page: null, start: 3, end: 9, quote: "earlie", offset_basis: "Unicode code points", available: true, unavailable_reason: null };
const origin: ResumeContext = { mode: "research", project_id: projectId, thread_id: null, return_to: `/workspace/projects?mode=research&project=${projectId}` };
const note: EntryRevision = { id: "entry-question", revision: 4, ...source, kind: "question", body: "How does the fixed baseline behave?", updated_at: "2026-11-05T00:00:00Z", activity_sequence: 3 };
function project(overrides: Partial<ProjectDetail> = {}): ProjectDetail { return { id: projectId, revision: 3, data: { title: "Baseline study", question: "Can the baseline explain retrieval?", scope: "Retained abstracts", constraints: "Fixed compute", next_actions: ["Inspect methods"], status: "active" }, created_at: "now", updated_at: "now", activity_sequence: 2, sources: [], entries: [], artifacts: [], threads: [], ...overrides }; }
function thread(overrides: Partial<LearningThread> = {}): LearningThread { return { id: threadId, revision: 2, data: { title: "Understand retrieval", goal: "Explain the fixed baseline", prerequisite: "Recall", status: "active", origin, source, entry: { entry_id: note.id, entry_revision: note.revision } }, source: bound, created_at: "now", updated_at: "now", activity_sequence: 4, ...overrides }; }
let index: ContextIndex, current: ProjectDetail, savedThread: LearningThread;
let writes: { path: string; body: Record<string, unknown> }[];
function edit(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
function submit(name: string) { fireEvent.click(screen.getByRole("button", { name })); }
beforeEach(() => {
  resetDraftMemory(); sessionStorage.clear(); history.replaceState(null, "", "/workspace/projects");
  current = project(); savedThread = thread(); writes = [];
  index = { principal_key_id: "owner-a", preferences: { revision: 7, data: { default_mode: "learn", learning_background: "", learning_goals: [] } }, projects: [current], threads: [] };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, location.origin).pathname.replace("/api/workspace/context", "");
    if (!init?.body) return Response.json(path === "" ? index : path.startsWith("/threads/") ? savedThread : current);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>; writes.push({ path, body });
    return Response.json(path === "/preferences" ? { revision: 8, data: body.data } : path === "/threads" ? savedThread : current);
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("explicit manual context writes", () => {
  it("creates only after submission and carries the selected source and exact owned question revision", async () => {
    const onSaved = vi.fn(); render(<ProjectEditor owner="owner-a" source={source} entry={{ entry_id: note.id, entry_revision: 4 }} question={note.body} onSaved={onSaved} />);
    expect(writes).toEqual([]); expect(screen.getByLabelText("Research question")).toHaveValue(note.body);
    edit("Project title", "Controlled baseline"); edit("Scope", "Only v1"); edit("Constraints", "No new experiments"); edit("Next actions, one per line", "  Read methods  \n\n Compare assumptions ");
    submit("Create project"); await waitFor(() => expect(onSaved).toHaveBeenCalledWith(current));
    expect(writes).toEqual([{ path: "/projects", body: { id: expect.stringMatching(/^project-[a-f0-9]{32}$/), revision: 0, request_id: expect.any(String), data: { title: "Controlled baseline", question: note.body, scope: "Only v1", constraints: "No new experiments", next_actions: ["Read methods", "Compare assumptions"], status: "active" }, initial_source: source, origin_entry: { entry_id: note.id, entry_revision: 4 } } }]);
    expect(screen.getByRole("status")).toHaveTextContent("Shared Library records are unchanged");
  });

  it("edits and archives the owned project without sending source or note mutations", async () => {
    render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />);
    edit("Research question", "Which assumptions remain?"); edit("Status", "archived"); submit("Save project changes");
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({ path: "/projects", body: { id: projectId, revision: 3, request_id: expect.any(String), data: { ...current.data, question: "Which assumptions remain?", status: "archived" } } });
  });

  it("starts a learning thread with exact source, entry revision and the originating research return context", async () => {
    render(<ThreadEditor owner="owner-a" source={source} entry={{ entry_id: note.id, entry_revision: 4 }} origin={origin} onSaved={vi.fn()} />);
    edit("Thread title", "Learn recall"); edit("What do you want to understand?", "Explain the baseline metric"); edit("Prerequisite or term to learn", "Recall at k"); submit("Save learning thread");
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({ path: "/threads", body: { id: expect.stringMatching(/^thread-[a-f0-9]{32}$/), revision: 0, request_id: expect.any(String), data: { title: "Learn recall", goal: "Explain the baseline metric", prerequisite: "Recall at k", status: "active", origin, source, entry: { entry_id: note.id, entry_revision: 4 } } } });
    expect(screen.getByRole("status")).toHaveTextContent("not a generated explanation or a mastery judgment");
  });

  it("preserves the saved learning origin when edited from another context", async () => {
    render(<ThreadEditor owner="owner-a" thread={savedThread} origin={{ ...origin, mode: "learn", project_id: null }} source={{ ...source, version_id: "newer-version" }} onSaved={vi.fn()} />);
    edit("Status", "archived"); submit("Save learning thread"); await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]?.body).toMatchObject({ id: threadId, revision: 2, data: { ...savedThread.data, status: "archived" } });
  });

  it.each(["observation", "assumption", "hypothesis", "comparison", "proposed-experiment"])("saves a %s as authored reasoning with only explicitly chosen evidence", async kind => {
    current.sources = [{ id: "evidence-a", role: "evidence", label: "", status: "active", reference: bound }, { id: "metadata", role: "source", label: "", status: "active", reference: { ...bound, title: "Metadata only" } }, { id: "removed", role: "evidence", label: "", status: "removed", reference: { ...bound, title: "Removed evidence" } }];
    render(<ArtifactEditor owner="owner-a" project={current} onSaved={vi.fn()} />);
    expect(screen.queryByRole("checkbox", { name: /Metadata|Removed/ })).not.toBeInTheDocument();
    edit("Record type", kind); edit("Your text", "The baseline may omit a confound."); const evidence = screen.getByRole("checkbox", { name: /Pinned v1 source/ }); fireEvent.click(evidence);
    if (kind === "observation") { fireEvent.click(evidence); expect(evidence).not.toBeChecked(); fireEvent.click(evidence); }
    submit("Save authored record");
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({ path: `/projects/${projectId}/artifacts`, body: { id: expect.stringMatching(/^artifact-[a-f0-9]{32}$/), revision: 3, artifact_revision: 0, request_id: expect.any(String), data: { kind, body: "The baseline may omit a confound.", evidence_link_ids: ["evidence-a"] } } });
    expect(screen.getByRole("status")).toHaveTextContent("manual and unverified. No experiment was executed");
  });

  it("saves preferences with their independent revision and never writes legacy profile or question data", async () => {
    render(<LearningPreferences onSaved={vi.fn()} />); await screen.findByLabelText("Declared background (optional)");
    expect(writes).toEqual([]); edit("Default workspace mode", "research"); edit("Declared background (optional)", "Linear algebra"); edit("Learning goals, one per line (optional)", "  Explain recall \n\n Read methods "); submit("Save learning preferences");
    await screen.findByText(/Learning preferences saved on the server at revision 8/);
    expect(writes).toEqual([{ path: "/preferences", body: { revision: 7, request_id: expect.any(String), data: { default_mode: "research", learning_background: "Linear algebra", learning_goals: ["Explain recall", "Read methods"] } } }]);
    expect(screen.getByText(/Learning preferences saved on the server/)).toHaveTextContent("legacy interests and organizing question are unchanged");
  });

  it("does not import a legacy question when the owner explicitly opens a blank project form", async () => {
    index.projects = []; render(<LiveProjects />); await screen.findByText(/saved organizing question has not been imported/); expect(writes).toEqual([]);
    submit("Create a project"); expect(await screen.findByLabelText("Research question")).toHaveValue(""); expect(writes).toEqual([]);
    edit("Project title", "An unsubmitted title"); submit("Discard local project edits"); expect(screen.queryByLabelText("Research question")).not.toBeInTheDocument(); expect(writes).toEqual([]);
  });

  it("selects the acknowledged new project in the canonical URL after its form closes", async () => {
    index.projects = []; render(<LiveProjects />); await screen.findByRole("button", { name: "Create a project" }); submit("Create a project"); await screen.findByLabelText("Project title");
    edit("Project title", "An explicit new study"); edit("Research question", "What does this baseline explain?"); submit("Create project");
    await waitFor(() => expect(new URLSearchParams(location.search).get("project")).toBe(projectId));
    expect(new URLSearchParams(location.search).get("mode")).toBe("research"); expect(screen.queryByLabelText("Project title")).not.toBeInTheDocument(); await screen.findByRole("region", { name: "Project workspace" });
    expect(writes).toHaveLength(1); expect(writes[0]!.path).toBe("/projects");
  });

  it("attaches the source and chosen shared-note revision in separate explicit requests", async () => {
    render(<ReaderContextActions owner="owner-a" source={source} entries={[note]} returnTo={origin.return_to} />); await screen.findByLabelText("Project for this source");
    expect(screen.getByRole("button", { name: "Link selected saved note" })).toBeDisabled(); edit("Project for this source", projectId); edit("Link role", "evidence"); edit("Project link label (optional)", "Check this assumption");
    submit("Attach source to project"); await screen.findByText(/Exact source link saved/);
    expect(writes[0]).toEqual({ path: `/projects/${projectId}/sources`, body: { revision: 3, role: "evidence", label: "Check this assumption", reference: source, request_id: expect.any(String) } });
    edit("Explicit shared note link (optional)", note.id); submit("Link selected saved note"); await screen.findByText(/Existing note revision linked/);
    expect(writes[1]).toEqual({ path: `/projects/${projectId}/entries`, body: { revision: 3, entry_id: note.id, entry_revision: 4, request_id: expect.any(String) } });
    expect(new URL(screen.getByRole("link", { name: "Open saved project →" }).getAttribute("href")!, location.origin).searchParams.get("project")).toBe(projectId);
  });

  it("renders exact project passage and historical note links without substituting the latest note", async () => {
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`);
    current.sources = [{ id: "evidence-a", role: "evidence", label: "Baseline", status: "active", reference: bound }];
    current.entries = [{ entry_id: note.id, entry_revision: 4, current_revision: 6, entry: note, available: true }];
    render(<LiveProjects />); await screen.findByRole("region", { name: "Project workspace" });
    const passage = new URL(screen.getByRole("link", { name: "Open exact project passage →" }).getAttribute("href")!, location.origin);
    expect(passage.searchParams.get("version")).toBe(source.version_id); expect(decodeURIComponent(passage.hash)).toBe(`#${source.anchor}`); expect(passage.searchParams.get("project")).toBe(projectId);
    const historical = new URL(screen.getByRole("link", { name: "Open linked note source →" }).getAttribute("href")!, location.origin);
    expect(historical.searchParams.has("entry")).toBe(false); expect(historical.searchParams.get("version")).toBe(source.version_id);
    expect(screen.getByText(/linked revision 4 · current revision 6/)).toBeInTheDocument(); expect(screen.getByText(note.body)).toBeInTheDocument();
    submit("Remove project link"); await waitFor(() => expect(writes).toHaveLength(1)); expect(writes[0]).toEqual({ path: `/projects/${projectId}/unlink`, body: { revision: 3, request_id: expect.any(String), link_id: "evidence-a" } });
  });

  it("returns a persisted learning thread to its pinned source and originating project after remount", async () => {
    history.replaceState(null, "", `/workspace/threads/${threadId}?mode=learn&thread=${threadId}`);
    const first = render(<LiveLearningThread id={threadId} />); await screen.findByText(/exact revision 4/); first.unmount(); render(<LiveLearningThread id={threadId} />);
    const link = await screen.findByRole("link", { name: "Return to project" }); const url = new URL(link.getAttribute("href")!, location.origin);
    expect(url.searchParams.get("version")).toBe(source.version_id); expect(url.searchParams.get("project")).toBe(projectId); expect(url.searchParams.get("mode")).toBe("research"); expect(url.searchParams.get("return_to")).toBe(origin.return_to); expect(decodeURIComponent(url.hash)).toBe(`#${source.anchor}`);
    const exact = new URL(screen.getByRole("link", { name: "Read this exact prerequisite source →" }).getAttribute("href")!, location.origin);
    expect(exact.searchParams.get("thread")).toBe(threadId); expect(exact.searchParams.has("entry")).toBe(false); expect(exact.searchParams.get("version")).toBe(source.version_id);
    expect(writes).toEqual([]);
  });

  it("shows manual artifacts and preserves unavailable source and note identities", async () => {
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`);
    current.sources = [{ id: "old-source", role: "source", label: "", status: "removed", reference: { ...bound, quote: "", available: false, unavailable_reason: "Pinned version missing" } }];
    current.entries = [{ entry_id: "unavailable-entry", entry_revision: 1, current_revision: null, entry: null, available: false }, { entry_id: note.id, entry_revision: 4, current_revision: 4, entry: note, available: true }];
    current.artifacts = [{ id: "artifact-one", revision: 2, authorship: "manual", verification: "unverified", data: { kind: "hypothesis", body: "A manual claim", entry: null, evidence_link_ids: [] } }, { id: "artifact-two", revision: 1, authorship: "manual", verification: "unverified", data: { kind: "proposed-experiment", body: "", entry: { entry_id: note.id, entry_revision: 4 }, evidence_link_ids: ["old-source"] } }];
    current.threads = [savedThread]; render(<LiveProjects />); await screen.findByText("A manual claim");
    expect(screen.getByText(/This pinned source is unavailable/)).toBeInTheDocument(); expect(screen.queryByRole("link", { name: "Open exact project passage →" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "Remove project link" })).not.toBeInTheDocument();
    expect(screen.getByText(/This linked entry is unavailable/)).toBeInTheDocument(); expect(screen.getByText(/current revision unavailable/)).toBeInTheDocument(); expect(screen.getAllByText(/Manual · unverified/)).toHaveLength(2);
    expect(screen.getByText(`Linked entry ${note.id}`)).toBeInTheDocument();
    const live = new URL(screen.getByRole("link", { name: "Open linked note source →" }).getAttribute("href")!, location.origin); expect(live.searchParams.get("entry")).toBe(note.id); expect(live.searchParams.get("version")).toBe(source.version_id);
    const learning = new URL(screen.getByRole("link", { name: savedThread.data.title }).getAttribute("href")!, location.origin); expect(learning.searchParams.get("mode")).toBe("learn"); expect(learning.searchParams.get("thread")).toBe(threadId);
    expect(writes).toEqual([]);
  });

  it("creates authored records and learning threads from the project workspace and updates its visible saved records", async () => {
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`); render(<LiveProjects />); await screen.findByRole("region", { name: "Project workspace" });
    submit("Edit project"); await screen.findByLabelText("Scope"); edit("Scope", "Discard this change"); submit("Discard local project edits"); expect(screen.queryByLabelText("Scope")).not.toBeInTheDocument(); expect(writes).toEqual([]);
    submit("Add authored research record"); await screen.findByLabelText("Your text"); edit("Your text", "A local observation");
    current = { ...current, revision: 4, artifacts: [{ id: "artifact-created", revision: 1, authorship: "manual", verification: "unverified", data: { kind: "observation", body: "A local observation", entry: null, evidence_link_ids: [] } }] };
    submit("Save authored record"); await screen.findByText("A local observation"); expect(screen.queryByLabelText("Your text")).not.toBeInTheDocument();
    submit("Learn this prerequisite"); await screen.findByLabelText("Thread title"); submit("Discard local thread edits"); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument();
    submit("Learn this prerequisite"); await screen.findByLabelText("Thread title"); edit("Thread title", savedThread.data.title); edit("What do you want to understand?", savedThread.data.goal); submit("Save learning thread");
    await screen.findByRole("link", { name: savedThread.data.title }); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument();
    expect(writes.map(write => write.path)).toEqual([`/projects/${projectId}/artifacts`, "/threads"]); expect(writes[1]!.body).toMatchObject({ data: { origin, source: null, entry: null } });
  });

  it("opens, discards and saves edits to a persisted learning thread without changing its source context", async () => {
    render(<LiveLearningThread id={threadId} />); await screen.findByRole("heading", { name: savedThread.data.title }); submit("Edit learning thread"); await screen.findByLabelText("Thread title");
    edit("What do you want to understand?", "Discard me"); submit("Discard local thread edits"); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument();
    submit("Edit learning thread"); await screen.findByLabelText("Thread title"); edit("What do you want to understand?", "A revised learning goal"); savedThread = { ...savedThread, revision: 3, data: { ...savedThread.data, goal: "A revised learning goal" } }; submit("Save learning thread");
    await screen.findByText("A revised learning goal"); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument(); expect(writes[0]!.body).toMatchObject({ revision: 2, data: { origin, source, entry: { entry_id: note.id, entry_revision: 4 } } });
  });
});
