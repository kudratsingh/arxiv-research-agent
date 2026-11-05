import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CompactActivityCard } from "@/components/workspace/CompactActivityCard";
import { AllocationReceipt } from "@/components/workspace/AllocationReceipt";
import { activityDestination } from "@/lib/workspace/activity";
import type { Activity, EntryRevision, ResumeContext } from "@/lib/workspace/api";
import { work } from "./fixtures";

const project = `project-${"a".repeat(32)}`, thread = `thread-${"b".repeat(32)}`;
const current = { mode: "learn" as const, project: null, thread: null, explicit: true, invalid: false };
const resume: ResumeContext = { mode: "research", project_id: project, thread_id: thread, return_to: `/workspace/projects?mode=research&project=${project}` };
const activity = (override: Partial<Activity> = {}): Activity => ({ sequence: 4, entry_id: null, work_id: work().work_id, version_id: work().version_id, kind: "reading", entry_kind: null, body: "", anchor: "abstract:3:18", revision: 1, updated_at: "2026-11-02T15:00:00Z", ...override });
const entry: EntryRevision = { id: "entry-a", revision: 2, work_id: work().work_id, version_id: work().version_id, kind: "question", body: "Saved question", anchor: "abstract:3:18", updated_at: "2026-11-02T15:00:00Z", activity_sequence: 4, context: resume };

describe("activity provenance and resume context", () => {
  it("resumes an exact entry revision in its saved mode and return destination", () => {
    const item = work({ entries: [entry] });
    const target = activityDestination(activity({ entry_id: entry.id, revision: 2 }), item, current);
    const url = new URL(target.href!, "http://localhost");
    expect(url.pathname).toBe(`/workspace/items/${encodeURIComponent(item.work_id)}`);
    expect(url.searchParams.get("version")).toBe(item.version_id);
    expect(url.searchParams.get("entry")).toBe("entry-a");
    expect(url.searchParams.get("mode")).toBe("research");
    expect(url.searchParams.get("project")).toBe(project);
    expect(url.searchParams.get("thread")).toBe(thread);
    expect(url.searchParams.get("return_to")).toBe(resume.return_to);
    expect(decodeURIComponent(url.hash)).toBe("#abstract:3:18");
  });
  it("does not use newer entry context or identify a newer revision as the saved one", () => {
    const target = activityDestination(activity({ entry_id: entry.id, revision: 1, version_id: "old:v1" }), work({ entries: [entry], versions: [] }), current);
    const url = new URL(target.href!, "http://localhost");
    expect(target.sourceTitle).toBe("Earlier retained source version");
    expect(url.searchParams.get("version")).toBe("old:v1");
    expect(url.searchParams.has("entry")).toBe(false);
    expect(url.searchParams.get("mode")).toBe("learn");
    expect(url.searchParams.get("return_to")).toBe("/workspace/today?mode=learn");
  });
  it("uses saved reading context only for the matching revision and preserves unknown sources", () => {
    const item = work(); item.reading = { ...item.reading, revision: 3, context: resume };
    expect(new URL(activityDestination(activity({ revision: 3 }), item, current).href!, "http://localhost").searchParams.get("mode")).toBe("research");
    expect(new URL(activityDestination(activity({ revision: 2 }), item, current).href!, "http://localhost").searchParams.get("mode")).toBe("learn");
    expect(activityDestination(activity(), undefined, current).href).toBeNull();
  });
});

describe("compact continuation options and receipt", () => {
  it("loads source metadata on disclosure and pins, unpins, and respects busy state", async () => {
    const user = userEvent.setup(), onPin = vi.fn();
    const saved = activity({ entry_id: "entry-a", entry_kind: "next-action", body: "Read the source" });
    const view = render(<CompactActivityCard activity={saved} work={work()} pinned={false} busy={false} onPin={onPin} context={current} />);
    expect(screen.queryByText(/Saved Nov/)).not.toBeInTheDocument();
    expect(screen.getByText("Read the source")).toBeInTheDocument();
    await user.click(screen.getByText("Source and pin options"));
    await user.click(await screen.findByRole("button", { name: "Pin this next action" }));
    expect(onPin).toHaveBeenCalledWith("entry-a");
    expect(screen.getByText(`${saved.version_id} · ${saved.anchor}`)).toBeInTheDocument();
    view.rerender(<CompactActivityCard activity={saved} work={work()} pinned busy onPin={onPin} context={current} />);
    expect(screen.getByRole("button", { name: "Unpin saved item" })).toBeDisabled();
    view.rerender(<CompactActivityCard activity={saved} work={work()} pinned busy={false} onPin={onPin} context={current} />);
    await user.click(screen.getByRole("button", { name: "Unpin saved item" })); expect(onPin).toHaveBeenLastCalledWith(null);
  });
  it("shows unavailable source, reading-only metadata, and compact allocation without inventing values", async () => {
    const user = userEvent.setup();
    render(<><CompactActivityCard activity={activity()} pinned={false} busy={false} onPin={vi.fn()} context={current} /><AllocationReceipt compact minutes={10} allocation={{ slots: 2, requested_fraction: .25, planned_max_exploration_slots: 0, max_exploration_slots: 0, actual_exploration_slots: 0, actual_items: 0, actual_fraction: null, unused_slots: 2 }} /></>);
    expect(screen.getByText(/source is unavailable/)).toBeInTheDocument();
    await user.click(screen.getByText("Source and pin options"));
    expect(await screen.findByText(/abstract:3:18/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pin/i })).not.toBeInTheDocument();
    expect(screen.getByText(/among 0 selected \(no items\)/)).toBeInTheDocument();
    expect(screen.getByText(/2 of 2 reading slots unused/)).toBeInTheDocument();
  });
});
