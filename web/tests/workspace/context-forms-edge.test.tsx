import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import ProjectEditor from "@/components/workspace/ProjectEditor";
import ThreadEditor from "@/components/workspace/ThreadEditor";
import ArtifactEditor from "@/components/workspace/ArtifactEditor";
import LearningPreferences from "@/components/workspace/LearningPreferences";
import ReaderContextActions from "@/components/workspace/ReaderContextActions";
import { LiveProjects } from "@/components/workspace/Projects";
import { LiveLearningThread } from "@/components/workspace/LearningThread";
import { LiveInterests } from "@/components/workspace/Interests";
import { ModeSwitch } from "@/components/workspace/ModeSwitch";
import { CandidateReview } from "@/components/workspace/CandidateReview";
import { resetDraftMemory } from "@/lib/workspace/draftMemory";
import type { ContextIndex, EntryRevision, LearningThread, ProjectDetail, ResumeContext, ReviewPacket, SourceReference } from "@/lib/workspace/api";
import { allowWorkspaceNavigation } from "@/lib/workspace/navigationGuard";
import { work, workspace } from "./fixtures";

vi.mock("next/navigation", () => ({ usePathname: () => location.pathname, useSearchParams: () => new URLSearchParams(location.search) }));
const projectId = `project-${"c".repeat(32)}`, threadId = `thread-${"d".repeat(32)}`;
const source: SourceReference = { work_id: work().work_id, version_id: `${work().work_id}:v1`, anchor: "abstract:3:9" };
const origin: ResumeContext = { mode: "research", project_id: projectId, thread_id: null, return_to: `/workspace/projects?mode=research&project=${projectId}` };
const entry: EntryRevision = { ...source, id: "entry-one", revision: 2, kind: "question", body: "Which baseline?", activity_sequence: 0, updated_at: "now" };
function project(): ProjectDetail { return { id: projectId, revision: 3, data: { title: "Saved project", question: "A saved question?", scope: "", constraints: "", next_actions: [], status: "active" }, created_at: "now", updated_at: "now", activity_sequence: 0, sources: [], entries: [], artifacts: [], threads: [] }; }
let current: ProjectDetail, index: ContextIndex, savedThread: LearningThread;
let status: number, readsFail: boolean, writes: { path: string; body: Record<string, unknown> }[];
let hold: boolean, finish: ((response: Response) => void) | undefined;
function edit(name: string, value: string) { fireEvent.change(screen.getByLabelText(name), { target: { value } }); }
function click(name: string) { fireEvent.click(screen.getByRole("button", { name })); }
beforeEach(() => {
  resetDraftMemory(); sessionStorage.clear(); history.replaceState(null, "", "/workspace/projects");
  current = project(); status = 200; readsFail = false; writes = []; hold = false; finish = undefined;
  index = { principal_key_id: "owner-a", preferences: { revision: 3, data: { default_mode: "learn", learning_background: "Saved background", learning_goals: [] } }, projects: [current], threads: [] };
  savedThread = { id: threadId, revision: 1, data: { title: "Saved thread", goal: "Learn the baseline", prerequisite: "", status: "active", origin, source: null, entry: null }, source: null, created_at: "now", updated_at: "now", activity_sequence: 0 };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url, location.origin).pathname.replace("/api/workspace/context", "");
    if (!init?.body) return readsFail ? new Response(null, { status: 503 }) : Response.json(path === "" ? index : path.startsWith("/threads/") ? savedThread : current);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>; writes.push({ path, body });
    if (hold) return new Promise<Response>(resolve => { finish = resolve; });
    return status === 200 ? Response.json(path === "/threads" ? savedThread : path === "/preferences" ? index.preferences : current) : new Response(null, { status });
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("manual form failure and recovery", () => {
  it("retains a failed create across a document restart and retries the identical request id and entity id", async () => {
    status = 503; const first = render(<ProjectEditor owner="owner-a" onSaved={vi.fn()} />);
    edit("Project title", "Unsaved investigation"); edit("Research question", "Can this be reproduced?"); click("Create project");
    await screen.findByText(/workspace could not complete/); const original = structuredClone(writes[0]); first.unmount(); resetDraftMemory();
    status = 200; render(<ProjectEditor owner="owner-a" onSaved={vi.fn()} />); expect(screen.getByLabelText("Project title")).toHaveValue("Unsaved investigation");
    expect(screen.getByText(/Recovered local edits/)).toBeInTheDocument(); click("Create project"); await waitFor(() => expect(writes).toHaveLength(2)); expect(writes[1]).toEqual(original);
    expect(screen.getByText(/Project saved on the server/)).toBeInTheDocument(); expect(sessionStorage.length).toBe(0);
  });

  it("uses a fresh idempotency key when the owner changes a failed request", async () => {
    status = 503; render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />); click("Save project changes"); await screen.findByText(/workspace could not complete/);
    const first = writes[0]!.body; edit("Scope", "Revised scope"); click("Save project changes"); await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]!.body.request_id).not.toBe(first.request_id); expect(writes[1]!.body.id).toBe(first.id); expect(writes[1]!.body.revision).toBe(first.revision);
  });

  it("retains a 409 draft during server reload and requires explicit review and save to reapply against the new revision", async () => {
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`); render(<LiveProjects />);
    await screen.findByRole("region", { name: "Project workspace" }); click("Edit project"); await screen.findByLabelText("Research question"); edit("Research question", "My retained local question?");
    status = 409; click("Save project changes"); await screen.findByText(/record changed in another tab/);
    current = { ...current, revision: 4, data: { ...current.data, question: "A concurrent server question?", next_actions: ["Inspect the concurrent plan"] } }; index.projects = [current]; click("Reload saved project");
    await screen.findByText(/Saved project revision 4/); expect(screen.getByLabelText("Research question")).toHaveValue("My retained local question?"); expect(screen.getByText(/Saved project revision 4/)).toHaveTextContent("local edit base 3");
    expect(screen.getByRole("region", { name: "Latest saved project for review" })).toHaveTextContent("A concurrent server question?");
    click("Keep my edits on reviewed revision"); expect(writes).toHaveLength(1); expect(screen.getByLabelText("Research question")).toHaveValue("My retained local question?");
    expect(screen.getByText(/Saved project revision 4/)).toHaveTextContent("local edit base 4"); status = 200; click("Save project changes"); await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]!.body).toMatchObject({ id: projectId, revision: 4, data: { question: "My retained local question?" } }); expect(writes[1]!.body.request_id).not.toBe(writes[0]!.body.request_id);
  });

  it("preserves conflicting preference declarations until the owner reviews and explicitly reapplies them", async () => {
    render(<LearningPreferences onSaved={vi.fn()} />); await screen.findByLabelText("Declared background (optional)"); edit("Declared background (optional)", "My retained background"); status = 409;
    click("Save learning preferences"); await screen.findByText(/record changed in another tab/);
    index.preferences = { revision: 4, data: { default_mode: "research", learning_background: "Concurrent background", learning_goals: ["A server goal"] } };
    click("Reload saved learning preferences"); await screen.findByRole("region", { name: "Latest saved learning preferences for review" });
    expect(screen.getByLabelText("Declared background (optional)")).toHaveValue("My retained background"); expect(screen.getByText(/Saved preferences revision 4/)).toHaveTextContent("local edit base 3");
    click("Keep my edits on reviewed revision"); expect(writes).toHaveLength(1); status = 200; click("Save learning preferences"); await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]!.body).toMatchObject({ revision: 4, data: { learning_background: "My retained background", default_mode: "learn" } }); expect(writes[1]!.body.request_id).not.toBe(writes[0]!.body.request_id);
  });

  it("reloads a conflicting thread for review while preserving its local goal until explicit reapply", async () => {
    render(<LiveLearningThread id={threadId} />); await screen.findByRole("heading", { name: savedThread.data.title }); click("Edit learning thread"); await screen.findByLabelText("Thread title");
    edit("What do you want to understand?", "My retained thread goal"); status = 409; click("Save learning thread"); await screen.findByText(/record changed in another tab/);
    savedThread = { ...savedThread, revision: 2, data: { ...savedThread.data, goal: "A concurrent thread goal" } }; click("Reload saved thread");
    await screen.findByRole("region", { name: "Latest saved thread for review" }); expect(screen.getByLabelText("What do you want to understand?")).toHaveValue("My retained thread goal");
    click("Keep my edits on reviewed revision"); expect(writes).toHaveLength(1); status = 200; click("Save learning thread"); await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1]!.body).toMatchObject({ revision: 2, data: { goal: "My retained thread goal", origin } }); expect(writes[1]!.body.request_id).not.toBe(writes[0]!.body.request_id);
  });

  it.each(["project", "thread", "artifact", "preferences"])("prevents duplicate %s submissions and navigation while its save is pending", async kind => {
    hold = true;
    const cancel = vi.fn();
    if (kind === "project") render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} onCancel={cancel} />);
    if (kind === "thread") render(<ThreadEditor owner="owner-a" thread={savedThread} origin={origin} onSaved={vi.fn()} onCancel={cancel} />);
    if (kind === "artifact") { render(<ArtifactEditor owner="owner-a" project={current} onSaved={vi.fn()} />); edit("Your text", "An authored hypothesis"); }
    if (kind === "preferences") { render(<LearningPreferences onSaved={vi.fn()} />); await screen.findByLabelText("Declared background (optional)"); }
    const name = { project: "Save project changes", thread: "Save learning thread", artifact: "Save authored record", preferences: "Save learning preferences" }[kind]!;
    const button = screen.getByRole("button", { name }); fireEvent.click(button); fireEvent.click(button);
    await waitFor(() => expect(writes).toHaveLength(1)); expect(button).toBeDisabled();
    fireEvent.submit(button.closest("form")!); expect(writes).toHaveLength(1);
    act(() => { expect(allowWorkspaceNavigation("/workspace/library")).toBe(false); }); expect(screen.getByText(/Wait for this save to finish/)).toBeInTheDocument();
    const result = kind === "thread" ? savedThread : kind === "preferences" ? index.preferences : current;
    await act(async () => { finish!(Response.json(result)); }); expect(cancel).not.toHaveBeenCalled();
    expect(allowWorkspaceNavigation("/workspace/library")).toBe(true);
  });

  it.each(["thread", "artifact", "preferences"])("retains failed %s text, retries the same request and explicitly discards local edits", async kind => {
    status = 503;
    if (kind === "thread") render(<ThreadEditor owner="owner-a" thread={savedThread} origin={origin} onSaved={vi.fn()} />);
    if (kind === "artifact") render(<ArtifactEditor owner="owner-a" project={current} onSaved={vi.fn()} />);
    if (kind === "preferences") { render(<LearningPreferences onSaved={vi.fn()} />); await screen.findByLabelText("Declared background (optional)"); }
    const field = { thread: "What do you want to understand?", artifact: "Your text", preferences: "Declared background (optional)" }[kind]!;
    const save = { thread: "Save learning thread", artifact: "Save authored record", preferences: "Save learning preferences" }[kind]!;
    const discard = { thread: "Discard local thread edits", artifact: "Discard local record edits", preferences: "Discard local learning edits" }[kind]!;
    edit(field, "Keep my exact authored text"); click(save); await screen.findByText(/workspace could not complete/); expect(screen.getByLabelText(field)).toHaveValue("Keep my exact authored text");
    click(save); await waitFor(() => expect(writes).toHaveLength(2)); expect(writes[1]).toEqual(writes[0]);
    await screen.findByText(/workspace could not complete/); click(discard);
    expect(screen.getByLabelText(field)).toHaveValue(kind === "thread" ? savedThread.data.goal : kind === "preferences" ? "Saved background" : ""); expect(sessionStorage.length).toBe(0);
  });

  it("recovers local edits when browser storage is unavailable and reports the full-reload limitation", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); }); vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    const first = render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />); edit("Scope", "Current document only");
    expect(screen.getByText(/Browser recovery is unavailable/)).toBeInTheDocument(); first.unmount(); render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />);
    expect(screen.getByLabelText("Scope")).toHaveValue("Current document only"); expect(screen.getByText(/Recovered local edits/)).toBeInTheDocument();
  });

  it.each(["thread", "preferences"])("shows the storage recovery limitation for %s while still allowing an explicit save", async kind => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    if (kind === "thread") render(<ThreadEditor owner="owner-a" thread={savedThread} origin={origin} onSaved={vi.fn()} />);
    else { render(<LearningPreferences onSaved={vi.fn()} />); await screen.findByLabelText("Declared background (optional)"); }
    expect(screen.getByText(/Browser recovery is unavailable/)).toBeInTheDocument(); click(kind === "thread" ? "Save learning thread" : "Save learning preferences");
    await waitFor(() => expect(writes).toHaveLength(1));
  });

  it.each(["not-json", JSON.stringify({ id: "bad", revision: -1, values: {} }), JSON.stringify({ id: "bad", revision: 0, values: { title: "x", question: "q", scope: "", constraints: "", actions: "", status: "active" }, attempt: { id: 4, fingerprint: false } })])("refuses a malformed recovery record without writing it to the server", raw => {
    sessionStorage.setItem(`arxiv.workspace.manual-draft.v1:${JSON.stringify(["owner-a", projectId])}`, raw);
    render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />); expect(screen.getByLabelText("Project title")).toHaveValue("Saved project"); expect(screen.getByText(/Browser recovery is unavailable/)).toBeInTheDocument(); expect(writes).toEqual([]);
    click("Discard local project edits"); expect(sessionStorage.length).toBe(0);
  });

  it("never lets a well-formed draft for another project redirect the displayed project's save", async () => {
    const otherProject = `project-${"e".repeat(32)}`;
    sessionStorage.setItem(`arxiv.workspace.manual-draft.v1:${JSON.stringify(["owner-a", projectId])}`, JSON.stringify({ id: otherProject, revision: 3, values: { title: "Different project draft", question: "A private second question?", scope: "", constraints: "", actions: "", status: "active" } }));
    render(<ProjectEditor owner="owner-a" project={current} onSaved={vi.fn()} />); edit("Scope", "Apply to the displayed project"); click("Save project changes");
    await waitFor(() => expect(writes).toHaveLength(1)); expect(writes[0]!.body.id).toBe(projectId); expect(writes[0]!.body.id).not.toBe(otherProject);
  });

  it("keeps new-project drafts separate when exact source passage or selected entry changes", () => {
    const first = render(<ProjectEditor owner="owner-a" source={source} entry={{ entry_id: entry.id, entry_revision: 2 }} onSaved={vi.fn()} />); edit("Project title", "Private first passage title"); first.unmount();
    const second = render(<ProjectEditor owner="owner-a" source={{ ...source, anchor: "abstract:10:20" }} entry={{ entry_id: entry.id, entry_revision: 2 }} onSaved={vi.fn()} />); expect(screen.getByLabelText("Project title")).toHaveValue(""); second.unmount();
    render(<ProjectEditor owner="owner-a" source={source} entry={{ entry_id: entry.id, entry_revision: 3 }} onSaved={vi.fn()} />); expect(screen.getByLabelText("Project title")).toHaveValue(""); expect(writes).toEqual([]);
  });

  it("keeps new-thread drafts separate when originating project or exact saved-entry revision changes", () => {
    const first = render(<ThreadEditor owner="owner-a" source={source} entry={{ entry_id: entry.id, entry_revision: 2 }} origin={origin} onSaved={vi.fn()} />); edit("Thread title", "First project's private goal"); first.unmount();
    const second = render(<ThreadEditor owner="owner-a" source={source} entry={{ entry_id: entry.id, entry_revision: 2 }} origin={{ ...origin, project_id: `project-${"f".repeat(32)}` }} onSaved={vi.fn()} />); expect(screen.getByLabelText("Thread title")).toHaveValue(""); second.unmount();
    render(<ThreadEditor owner="owner-a" source={source} entry={{ entry_id: entry.id, entry_revision: 3 }} origin={origin} onSaved={vi.fn()} />); expect(screen.getByLabelText("Thread title")).toHaveValue(""); expect(writes).toEqual([]);
  });
});

describe("owned associations and honest unavailable context", () => {
  it.each(["abstract:0", "abstract:5:5", "abstract:9:3", "metadata:0"])("does not offer a passage-evidence claim for %s", async anchor => {
    render(<ReaderContextActions owner="owner-a" source={{ ...source, anchor }} entries={[]} returnTo="/workspace/library" />); await screen.findByLabelText("Link role");
    expect(screen.getByRole("option", { name: "Selected retained passage — evidence link" })).toBeDisabled(); edit("Project for this source", projectId); click("Attach source to project");
    await screen.findByText(/Exact source link saved/); expect(writes[0]!.body).toMatchObject({ role: "source", reference: { anchor, version_id: source.version_id } });
  });

  it("refuses a mismatched account before exposing association writes", async () => {
    index.principal_key_id = "owner-b"; render(<ReaderContextActions owner="owner-a" source={source} entries={[entry]} returnTo="/workspace/library" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("different local account"); expect(screen.queryByRole("button", { name: "Attach source to project" })).not.toBeInTheDocument(); expect(writes).toEqual([]);
  });

  it("requires an explicit question selection before using it to create a project", async () => {
    render(<ReaderContextActions owner="owner-a" source={source} entries={[entry]} returnTo="/workspace/library" />); await screen.findByLabelText("Explicit shared note link (optional)");
    edit("Explicit shared note link (optional)", entry.id); click("Investigate this in a new project"); expect(await screen.findByLabelText("Research question")).toHaveValue(entry.body);
    expect(screen.getByText(/Explicit saved-entry link/)).toHaveTextContent("entry-one · revision 2"); expect(writes).toEqual([]); click("Discard local project edits"); expect(screen.queryByLabelText("Research question")).not.toBeInTheDocument();
    click("Learn this prerequisite"); await screen.findByLabelText("Thread title"); click("Discard local thread edits"); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument();
  });

  it("can create a project and a learning thread from a retained material passage without auto-linking a note", async () => {
    const passage = { ...source, anchor: "material:retained-a:page:2:10:25", material_id: "retained-a" };
    render(<ReaderContextActions owner="owner-a" source={passage} entries={[entry]} returnTo="/workspace/library" />); await screen.findByLabelText("Link role");
    expect(screen.getByRole("option", { name: "Selected retained passage — evidence link" })).toBeEnabled(); click("Investigate this in a new project"); await screen.findByLabelText("Research question");
    expect(screen.getByLabelText("Research question")).toHaveValue(""); edit("Project title", "Material study"); edit("Research question", "Which passage explains this?"); click("Create project");
    await screen.findByRole("link", { name: "Open saved project →" }); expect(screen.queryByLabelText("Research question")).not.toBeInTheDocument(); expect(writes[0]!.body).toMatchObject({ initial_source: passage }); expect(writes[0]!.body).not.toHaveProperty("origin_entry");
    click("Learn this prerequisite"); await screen.findByLabelText("Thread title"); edit("Thread title", "Learn this passage"); edit("What do you want to understand?", "Explain page two"); click("Save learning thread");
    await screen.findByRole("link", { name: "Open saved learning thread →" }); expect(screen.queryByLabelText("Thread title")).not.toBeInTheDocument(); expect(writes[1]!.body).toMatchObject({ data: { source: passage, entry: null, origin: { mode: "learn", project_id: null, thread_id: null, return_to: "/workspace/library" } } });
  });

  it("discards local association edits without changing shared records and excludes archived projects", async () => {
    index.projects.push({ ...current, id: `project-${"e".repeat(32)}`, data: { ...current.data, title: "Archived project", status: "archived" } });
    render(<ReaderContextActions owner="owner-a" source={source} entries={[entry]} returnTo="/workspace/library" />); await screen.findByLabelText("Project for this source"); expect(screen.queryByRole("option", { name: "Archived project" })).not.toBeInTheDocument();
    edit("Project for this source", projectId); edit("Project link label (optional)", "Unsaved local annotation"); edit("Explicit shared note link (optional)", entry.id); click("Discard local link edits");
    expect(screen.getByLabelText("Project link label (optional)")).toHaveValue(""); expect(screen.getByLabelText("Explicit shared note link (optional)")).toHaveValue(""); expect(screen.getByRole("button", { name: "Attach source to project" })).toBeDisabled(); expect(writes).toEqual([]);
  });

  it("keeps a project unlink pending until acknowledgement and preserves its records on failure", async () => {
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`);
    current.sources = [{ id: "link-a", role: "source", status: "active", label: "", reference: { ...source, version_hash: null, material_id: null, material_hash: null, parser_revision: null, source_scope: "abstract", title: "Kept source", source_url: "https://example.test", page: null, start: null, end: null, quote: "", offset_basis: "Unicode code points", available: true, unavailable_reason: null } }];
    render(<LiveProjects />); await screen.findByRole("button", { name: "Remove project link" }); hold = true; click("Remove project link");
    await waitFor(() => expect(writes).toHaveLength(1)); expect(screen.getByRole("button", { name: "Remove project link" })).toBeDisabled(); act(() => { expect(allowWorkspaceNavigation("/workspace/library")).toBe(false); });
    expect(screen.getByText(/Wait for this project request to finish/)).toBeInTheDocument(); await act(async () => { finish!(new Response(null, { status: 409 })); });
    await screen.findByText(/record changed in another tab/); expect(screen.getByText("Kept source")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Remove project link" })).toBeEnabled();
    click("Reload saved project"); await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4)); expect(writes).toHaveLength(1);
  });

  it("leaves an unavailable pinned learning source unavailable while retaining its original return context", async () => {
    savedThread = { ...savedThread, data: { ...savedThread.data, origin: { ...origin, project_id: null, mode: "learn", return_to: "/workspace/radar?q=baseline" } }, source: { ...source, version_hash: null, material_id: null, material_hash: null, parser_revision: null, source_scope: "abstract", title: "Missing v1", source_url: "https://example.test", page: null, start: null, end: null, quote: "", offset_basis: "Unicode code points", available: false, unavailable_reason: "Version unavailable" } };
    render(<LiveLearningThread id={threadId} />); await screen.findByText(/This pinned source is unavailable/); expect(screen.queryByRole("link", { name: "Read this exact prerequisite source →" })).not.toBeInTheDocument();
    const back = new URL(screen.getByRole("link", { name: "Return to originating source" }).getAttribute("href")!, location.origin); expect(back.searchParams.get("version")).toBe(source.version_id); expect(back.searchParams.get("return_to")).toBe("/workspace/radar?q=baseline"); expect(writes).toEqual([]);
  });

  it("retains source-link labels and idempotency keys after a conflict, with an explicit revision reload", async () => {
    render(<ReaderContextActions owner="owner-a" source={source} entries={[]} returnTo="/workspace/library" />); await screen.findByLabelText("Project for this source");
    edit("Project for this source", projectId); edit("Project link label (optional)", "Retain this annotation"); status = 409; click("Attach source to project"); await screen.findByText(/record changed in another tab/);
    click("Attach source to project"); await waitFor(() => expect(writes).toHaveLength(2)); expect(writes[1]).toEqual(writes[0]);
    current = { ...current, revision: 4 }; index.projects = [current]; click("Reload project versions"); await waitFor(() => expect(fetch).toHaveBeenCalledTimes(4));
    expect(screen.getByLabelText("Project link label (optional)")).toHaveValue("Retain this annotation"); status = 200; click("Attach source to project"); await screen.findByText(/Exact source link saved/);
    expect(writes[2]!.body.revision).toBe(4); expect(writes[2]!.body.request_id).not.toBe(writes[0]!.body.request_id); expect(screen.getByLabelText("Project link label (optional)")).toHaveValue("");
  });

  it.each(["preferences", "projects", "thread"])("retries an unavailable %s read without creating any authored record", async kind => {
    readsFail = true;
    if (kind === "preferences") render(<LearningPreferences onSaved={vi.fn()} />);
    if (kind === "projects") { history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`); render(<LiveProjects />); }
    if (kind === "thread") render(<LiveLearningThread id={threadId} />);
    const retry = { preferences: "Retry learning preferences", projects: "Retry project", thread: "Retry thread" }[kind]!;
    await screen.findByRole("button", { name: retry }); readsFail = false; click(retry);
    if (kind === "preferences") await screen.findByLabelText("Declared background (optional)");
    if (kind === "projects") { click("Retry project list"); await screen.findByRole("region", { name: "Project workspace" }); }
    if (kind === "thread") { await screen.findByRole("heading", { name: "Saved thread" }); expect(screen.getByRole("link", { name: "Return to project" })).toHaveAttribute("href", origin.return_to); expect(screen.getByText("No prerequisite declared.")).toBeInTheDocument(); }
    expect(writes).toEqual([]);
  });
});

describe("adversarial context regressions", () => {
  it("honors a saved research default on Projects without an explicit mode query", async () => {
    index.preferences.data.default_mode = "research";
    render(<><ModeSwitch path="/workspace/projects" /><LiveProjects /></>);
    await screen.findByRole("button", { name: "Create a project" });
    await waitFor(() => expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("aria-current", "true"));
    expect(screen.getByRole("link", { name: "Explore & Learn" })).not.toHaveAttribute("aria-current");
    expect(location.search).toBe(""); expect(writes).toEqual([]);
  });

  it("pins an open project creation draft to its original passage when Reader selection changes", async () => {
    const view = render(<ReaderContextActions owner="owner-a" source={source} entries={[]} returnTo="/workspace/library" />);
    await screen.findByLabelText("Project for this source"); click("Investigate this in a new project"); await screen.findByLabelText("Project title");
    edit("Project title", "Reasoning about the original passage"); edit("Research question", "Why does the original passage say this?");
    view.rerender(<ReaderContextActions owner="owner-a" source={{ ...source, anchor: "abstract:40:60" }} entries={[]} returnTo="/workspace/radar?q=other" />);
    const carried = screen.getByRole("heading", { name: "Carried source" }).closest("section")!;
    fireEvent.click(within(carried).getByText("Exact source details"));
    expect(within(carried).getByText("abstract:3:9", { exact: true })).toBeVisible(); click("Create project");
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]!.body).toMatchObject({ initial_source: source, data: { question: "Why does the original passage say this?" } });
  });

  it("pins a create-from-question preview to the selected saved entry revision despite later edits", async () => {
    const view = render(<ReaderContextActions owner="owner-a" source={source} entries={[entry]} returnTo="/workspace/library" />);
    await screen.findByLabelText("Explicit shared note link (optional)"); edit("Explicit shared note link (optional)", entry.id); click("Investigate this in a new project");
    await screen.findByLabelText("Project title"); edit("Project title", "Investigate the selected question");
    view.rerender(<ReaderContextActions owner="owner-a" source={source} entries={[{ ...entry, revision: 3, body: "A different newly saved question?" }]} returnTo="/workspace/library" />);
    expect(screen.getByLabelText("Research question")).toHaveValue(entry.body); expect(screen.getByText(/Explicit saved-entry link:/)).toHaveTextContent("revision 2"); click("Create project");
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]!.body).toMatchObject({ data: { question: entry.body }, origin_entry: { entry_id: entry.id, entry_revision: 2 } });
  });

  it("retains a pending preference save's navigation veto when its disclosure closes", async () => {
    const original = vi.mocked(fetch).getMockImplementation()!;
    vi.mocked(fetch).mockImplementation(async (url, init) => String(url).includes("/context/state") ? Response.json(workspace()) : original(url, init));
    render(<LiveInterests />); const summary = await screen.findByText("Learning preferences · optional background and goals"); const disclosure = summary.closest("details")!;
    disclosure.open = true; fireEvent(disclosure, new Event("toggle")); await screen.findByLabelText("Declared background (optional)");
    edit("Declared background (optional)", "A pending authored background"); hold = true; click("Save learning preferences"); await waitFor(() => expect(writes).toHaveLength(1));
    act(() => { expect(allowWorkspaceNavigation("/workspace/library")).toBe(false); });
    disclosure.open = false; fireEvent(disclosure, new Event("toggle"));
    await waitFor(() => expect(disclosure.open).toBe(false));
    act(() => { expect(allowWorkspaceNavigation("/workspace/library")).toBe(false); });
    expect(disclosure.open).toBe(true); expect(screen.getByLabelText("Declared background (optional)")).toHaveValue("A pending authored background");
    await act(async () => { finish!(Response.json(index.preferences)); });
    expect(allowWorkspaceNavigation("/workspace/library")).toBe(true);
  });

  it("reloads and reviews an artifact conflict before explicitly reapplying the retained authored text", async () => {
    current.sources = [{ id: "evidence-before-conflict", role: "evidence", status: "active", label: "", reference: { ...source, version_hash: null, material_id: null, material_hash: null, parser_revision: null, source_scope: "abstract", title: "A retained evidence passage", source_url: "https://example.test", page: null, start: 3, end: 9, quote: "source", offset_basis: "Unicode code points", available: true, unavailable_reason: null } }];
    history.replaceState(null, "", `/workspace/projects?mode=research&project=${projectId}`); render(<LiveProjects />);
    await screen.findByRole("region", { name: "Project workspace" }); click("Add authored research record"); await screen.findByLabelText("Your text"); edit("Your text", "A hypothesis worth retaining");
    fireEvent.click(screen.getByRole("checkbox", { name: /A retained evidence passage/ }));
    status = 409; click("Save authored record"); await screen.findByText(/record changed in another tab/); const first = writes[0]!.body;
    current = { ...current, revision: 4, data: { ...current.data, question: "A concurrent project question?" }, sources: current.sources.map(link => ({ ...link, status: "removed" as const })) }; index.projects = [current];
    fireEvent.click(within(screen.getByRole("form", { name: "Authored research record" })).getByRole("button", { name: "Reload saved project" }));
    await screen.findByRole("region", { name: "Latest saved project for authored record review" });
    expect(screen.getByLabelText("Your text")).toHaveValue("A hypothesis worth retaining"); expect(writes).toHaveLength(1);
    const unavailable = screen.getByRole("checkbox", { name: /Unavailable evidence link evidence-before-conflict/ }); expect(unavailable).toBeChecked();
    click("Keep my edits on reviewed revision"); expect(writes).toHaveLength(1); fireEvent.click(unavailable); expect(screen.queryByRole("checkbox", { name: /Unavailable evidence link/ })).not.toBeInTheDocument();
    status = 200; click("Save authored record");
    await waitFor(() => expect(writes).toHaveLength(2)); expect(writes[1]!.body).toMatchObject({ id: first.id, revision: 4, data: { body: "A hypothesis worth retaining", evidence_link_ids: [] } }); expect(writes[1]!.body.request_id).not.toBe(first.request_id);
  });

  it("preserves a research project through candidate-review source inspection and return", async () => {
    const packetId = `review-${"b".repeat(32)}`;
    const packet: ReviewPacket = { id: packetId, created_at: "now", as_of: "now", profile_revision: 1, policy_version: "test", items: [{ work: work(), matching_reason: [], evidence_scope: "abstract", estimated_minutes: 5, feedback: { revision: 0, label: null, reason: "", updated_at: "" } }], coverage: [], selection: "Stored candidates", limitations: [], labelled_count: 0 };
    history.replaceState(null, "", `/workspace/review?mode=research&project=${projectId}`);
    vi.mocked(fetch).mockImplementation(async url => Response.json(String(url).includes("/context/state") ? workspace() : { packet, packet_ids: [packetId] }));
    render(<CandidateReview />); const link = await screen.findByRole("link", { name: "Inspect retained source →" }); const url = new URL(link.getAttribute("href")!, location.origin);
    expect(url.searchParams.get("project")).toBe(projectId); expect(url.searchParams.get("mode")).toBe("research"); expect(url.searchParams.get("version")).toBe(work().version_id);
    const back = new URL(url.searchParams.get("return_to")!, location.origin); expect(back.pathname).toBe("/workspace/review"); expect(back.searchParams.get("packet")).toBe(packetId); expect(back.searchParams.get("project")).toBe(projectId); expect(back.searchParams.get("mode")).toBe("research");
    expect(writes).toEqual([]);
  });
});
