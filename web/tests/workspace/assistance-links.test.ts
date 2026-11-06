import { describe, expect, it } from "vitest";
import { assistanceResumeHref } from "@/lib/workspace/assistanceLinks";
import { passageAnchor } from "@/lib/workspace/assistanceTypes";

describe("saved assistance links", () => {
  const source = { work_id: "paper/with spaces", version_id: "paper:v1" };
  const origin = { mode: "research" as const, project_id: `project-${"a".repeat(32)}`, thread_id: `thread-${"b".repeat(32)}`, return_to: "/workspace/projects" };
  it("preserves the exact source, original mode/project and current Library return", () => {
    const href = assistanceResumeHref(`assistance-fake-${"c".repeat(40)}`, source, origin, "/workspace/library?view=notes&focus=other");
    const url = new URL(href!, "https://workspace.invalid");
    expect(decodeURIComponent(url.pathname)).toBe("/workspace/items/paper/with spaces");
    expect(url.searchParams.get("version")).toBe("paper:v1");
    expect(url.searchParams.get("return_to")).toBe("/workspace/library?view=notes&focus=other");
    expect(url.searchParams.get("project")).toBe(origin.project_id); expect(url.searchParams.get("thread")).toBe(origin.thread_id);
    expect(url.hash).toBe("#understand");
  });
  it("never treats an arbitrary note identifier as a job or remote address", () => {
    for (const id of ["ordinary", "assistance-https://example.com", "assistance-fake-short"]) expect(assistanceResumeHref(id, source, origin)).toBeNull();
    const result = assistanceResumeHref(`assistance-fake-${"d".repeat(40)}`, source, { ...origin, mode: "learn", project_id: null, thread_id: null });
    expect(result).not.toContain("project="); expect(result).not.toContain("thread=");
  });
  it("uses page-local Unicode offsets without reconstructing or searching quotations", () => {
    const value = { material_id: "mat-one", page: 17, start: 4, end: 23, scope: "excerpt" };
    expect(passageAnchor(value as Parameters<typeof passageAnchor>[0])).toBe("material:mat-one:page:17:4:23");
    expect(passageAnchor({ ...value, page: null, scope: "abstract" } as Parameters<typeof passageAnchor>[0])).toBe("abstract:4:23");
  });
});
