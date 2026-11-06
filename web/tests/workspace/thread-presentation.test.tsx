import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LiveLearningThread } from "@/components/workspace/LearningThread";
import { SourceReferenceDetails } from "@/components/workspace/SourceReferenceDetails";
import type { BoundSource, ContextIndex, LearningThread, ResumeContext } from "@/lib/workspace/api";

vi.mock("next/navigation", () => ({ usePathname: () => location.pathname, useSearchParams: () => new URLSearchParams(location.search) }));
const projectId = `project-${"c".repeat(32)}`, threadId = `thread-${"d".repeat(32)}`;
const origin: ResumeContext = { mode: "research", project_id: projectId, thread_id: null, return_to: `/workspace/projects?mode=research&project=${projectId}` };
const source: BoundSource = {
  work_id: "arxiv:2610.00001", version_id: "arxiv:2610.00001:v1", anchor: "material:retained-a:page:7:0:24",
  version_hash: "version-digest-1", material_id: "retained-a", material_hash: "material-digest-1", parser_revision: "parser-r3", source_scope: "excerpt",
  title: "Earlier retained source", source_url: "https://example.test/v1", page: 7, start: 0, end: 24,
  quote: "Exact retained quotation.", offset_basis: "page-local Unicode code points; end exclusive", available: true, unavailable_reason: null,
};
let thread: LearningThread;
beforeEach(() => {
  history.replaceState(null, "", `/workspace/threads/${threadId}?mode=learn&thread=${threadId}`);
  thread = { id: threadId, revision: 3, data: { title: "Understand the baseline", goal: "Explain why the retained baseline was chosen.", prerequisite: "Read the comparison on page seven.", status: "active", origin, source, entry: { entry_id: "entry-one", entry_revision: 2 } }, source, created_at: "now", updated_at: "now", activity_sequence: 0 };
  const index: ContextIndex = { principal_key_id: "owner-a", preferences: { revision: 1, data: { default_mode: "learn", learning_background: "", learning_goals: [] } }, projects: [], threads: [thread] };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => Response.json(new URL(url, location.origin).pathname.endsWith(`/threads/${threadId}`) ? thread : index)));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function expand(summary: string) {
  const toggle = screen.getByText(summary, { selector: "summary" });
  const details = toggle.closest("details")!;
  expect(details).not.toHaveAttribute("open");
  fireEvent.click(toggle);
  expect(details).toHaveAttribute("open");
  return within(details);
}

describe("learning thread presentation", () => {
  it.each(["assistance-fake-", "qualification-gen-"])("resumes %s outputs with honest experimental wording and exact origin", async prefix => {
    thread.data.entry = { entry_id: prefix + "e".repeat(40), entry_revision: 1 };
    render(<LiveLearningThread id={threadId} />);
    const link = await screen.findByRole("link", { name: "Resume saved assistance →" });
    const url = new URL(link.getAttribute("href")!, location.origin);
    expect(url.searchParams.get("version")).toBe(source.version_id);
    expect(url.searchParams.get("project")).toBe(projectId);
    expect(screen.queryByText(/No explanation was generated/)).not.toBeInTheDocument();
    expect(screen.getByText(/Human support, usefulness and mastery remain unmeasured/)).toBeVisible();
    expect(screen.getByText(prefix.startsWith("qualification") ? /Quarantined experimental result; quality unmeasured/ : /Local simulation; quality unmeasured/)).toBeVisible();
  });
  it("leads with the declared goal and prerequisite while exact source bindings remain inspectable", async () => {
    render(<LiveLearningThread id={threadId} />);
    await screen.findByRole("heading", { name: "Understand the baseline" });
    expect(screen.getByRole("region", { name: "Learning goal" })).toHaveTextContent(thread.data.goal);
    expect(screen.getByRole("region", { name: "Declared prerequisite" })).toHaveTextContent(thread.data.prerequisite);
    expect(screen.getByText("Version 1 · Retained excerpt · Page 7")).toBeVisible();
    expect(screen.getByText(source.quote, { selector: "blockquote" })).toBeVisible();
    const exact = expand("Exact source details");
    for (const value of [source.work_id, source.version_id, source.anchor, source.version_hash!, source.material_id!, source.material_hash!, source.parser_revision!, source.source_scope!, source.source_url, source.offset_basis]) expect(exact.getByText(value, { exact: true })).toBeVisible();
    expect(exact.getByText("Start offset").nextElementSibling).toHaveTextContent("0");
    expect(exact.getByText("End offset").nextElementSibling).toHaveTextContent("24");
    expect(screen.getByText("Later edits are not substituted into this source link.")).toBeVisible();
    expect(expand("Linked note details").getByText(/entry-one · exact revision 2/)).toBeVisible();
    expect(expand("Learning thread details").getByText(`Thread ${threadId} · revision 3`)).toBeVisible();
    expect(screen.getByText(/No explanation was generated and reading does not establish mastery/)).toBeVisible();
  });

  it("keeps exact version, passage and project origin in its source and return actions", async () => {
    render(<LiveLearningThread id={threadId} />);
    const read = new URL((await screen.findByRole("link", { name: "Read this exact prerequisite source →" })).getAttribute("href")!, location.origin);
    expect(read.pathname).toBe("/workspace/items/arxiv%3A2610.00001");
    expect(read.searchParams.get("version")).toBe(source.version_id);
    expect(decodeURIComponent(read.hash.slice(1))).toBe(source.anchor);
    expect(read.searchParams.get("mode")).toBe("learn");
    expect(read.searchParams.get("thread")).toBe(threadId);
    expect(read.searchParams.get("return_to")).toBe(`/workspace/threads/${threadId}?mode=learn&thread=${threadId}`);
    const back = new URL(screen.getByRole("link", { name: "Return to project" }).getAttribute("href")!, location.origin);
    expect(back.searchParams.get("version")).toBe(source.version_id);
    expect(decodeURIComponent(back.hash.slice(1))).toBe(source.anchor);
    expect(back.searchParams.get("mode")).toBe("research");
    expect(back.searchParams.get("project")).toBe(projectId);
    expect(back.searchParams.get("return_to")).toBe(origin.return_to);
  });

  it("refuses unavailable pinned sources and preserves the original project return action", async () => {
    thread = { ...thread, source: { ...source, available: false, unavailable_reason: "Version unavailable", quote: "" } };
    render(<LiveLearningThread id={threadId} />);
    expect(await screen.findByText("This pinned source is unavailable; a newer version has not been substituted.")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Read this exact prerequisite source →" })).not.toBeInTheDocument();
    const back = new URL(screen.getByRole("link", { name: "Return to project" }).getAttribute("href")!, location.origin);
    expect(back.searchParams.get("version")).toBe(source.version_id);
    expect(back.searchParams.get("return_to")).toBe(origin.return_to);
    expect(expand("Exact source details").getByText(source.version_id)).toBeVisible();
  });

  it("keeps references without optional retained fields readable without inventing offsets or scope", () => {
    render(<SourceReferenceDetails reference={{ work_id: "saved-source", version_id: "opaque-version", anchor: "material:kept:page:1" }} />);
    expect(screen.getByText("Pinned source version · Retained source context")).toBeVisible();
    const exact = expand("Exact source details");
    expect(exact.getByText("opaque-version")).toBeVisible();
    expect(exact.queryByText("Start offset")).not.toBeInTheDocument();
    expect(exact.queryByText("Source scope")).not.toBeInTheDocument();
  });
});


it.each([
  ["metadata", "Source metadata"], ["abstract", "Abstract"],
  ["excerpt", "Retained excerpt"], ["full_text", "Full text"],
] as const)("labels an immutable metadata revision and its %s scope without exposing the identifier as the headline", (scope, label) => {
  render(<SourceReferenceDetails reference={{ work_id: "arxiv:1234.5678", version_id: "arxiv:1234.5678:v2:metadata-abcdef", anchor: `${scope}:0`, source_scope: scope }} />);
  expect(screen.getByText(`Version 2 · ${label}`)).toBeVisible();
  const summary = screen.getByText("Exact source details");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(summary);
  expect(within(summary.closest("details")!).getByText("arxiv:1234.5678:v2:metadata-abcdef")).toBeVisible();
});
