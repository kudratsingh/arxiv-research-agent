import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ProjectsPage from "@/app/(live)/workspace/projects/page";
import ThreadPage from "@/app/(live)/workspace/threads/[id]/page";
import ReviewPage from "@/app/(live)/workspace/review/page";

// Route boundaries only. Durable forms and API ownership are exercised by the
// mounted context suites; these spies detect an invalid identifier reaching them.
const mounted = vi.hoisted(() => ({ thread: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("not found"); } }));
vi.mock("@/components/workspace/Projects", () => ({ LiveProjects: () => <h1>Owned projects entry</h1> }));
vi.mock("@/components/workspace/CandidateReview", () => ({ CandidateReview: () => <h1>Existing candidate review entry</h1> }));
vi.mock("@/components/workspace/LearningThread", () => ({ LiveLearningThread: ({ id }: { id: string }) => { mounted.thread(id); return <h1>{id}</h1>; } }));

describe("new contextual route boundaries", () => {
  it.each(["../project-owner", "thread-short", `project-${"a".repeat(32)}`, `thread-${"A".repeat(32)}`, `thread-${"a".repeat(33)}`])("refuses malformed learning-thread id %s before mounting a data reader", async id => {
    mounted.thread.mockClear();
    await expect(ThreadPage({ params: Promise.resolve({ id }) })).rejects.toThrow("not found");
    expect(mounted.thread).not.toHaveBeenCalled();
  });
  it("passes a valid exact durable thread identity without decoding or substituting it", async () => {
    const id = `thread-${"a".repeat(32)}`;
    render(await ThreadPage({ params: Promise.resolve({ id }) }));
    expect(screen.getByRole("heading")).toHaveTextContent(id);
    expect(mounted.thread).toHaveBeenLastCalledWith(id);
  });
  it("keeps owned projects reachable through the real route export", () => {
    render(<ProjectsPage />); expect(screen.getByRole("heading")).toHaveTextContent("Owned projects entry");
  });
  it("keeps the existing usefulness review route pointed at its own component", () => {
    render(<ReviewPage />); expect(screen.getByRole("heading")).toHaveTextContent("Existing candidate review entry");
  });
});
