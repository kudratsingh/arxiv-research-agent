import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlanReview from "@/components/PlanReview";
import type { Plan } from "@/lib/types";

function makePlan(overrides: Partial<Plan> = {}): Plan {
  return {
    sub_questions: ["what is X", "how does Y compare"],
    search_queries: ["X survey", "Y benchmarks"],
    ...overrides,
  };
}

describe("PlanReview", () => {
  it("renders each planner-produced sub_question and search_query", () => {
    render(<PlanReview plan={makePlan()} onReview={vi.fn()} />);
    expect(screen.getByDisplayValue("what is X")).toBeInTheDocument();
    expect(screen.getByDisplayValue("how does Y compare")).toBeInTheDocument();
    expect(screen.getByDisplayValue("X survey")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Y benchmarks")).toBeInTheDocument();
  });

  it("Approve as-is is enabled until the user edits", () => {
    render(<PlanReview plan={makePlan()} onReview={vi.fn()} />);
    expect(
      screen.getByRole("button", { name: /approve as-is/i })
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /save edits/i })
    ).toBeDisabled();
  });

  it("Save edits enables + Approve as-is disables after editing", async () => {
    const user = userEvent.setup();
    render(<PlanReview plan={makePlan()} onReview={vi.fn()} />);

    const input = screen.getByRole("textbox", { name: /sub-questions #1/i });
    await user.clear(input);
    await user.type(input, "revised question");

    expect(
      screen.getByRole("button", { name: /save edits/i })
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: /approve as-is/i })
    ).toBeDisabled();
  });

  it("calls onReview with action=approve when Approve as-is is clicked", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<PlanReview plan={makePlan()} onReview={onReview} />);

    await user.click(
      screen.getByRole("button", { name: /approve as-is/i })
    );
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(onReview).toHaveBeenCalledWith("approve", undefined);
  });

  it("submits action=revise with the edited plan on Save edits", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<PlanReview plan={makePlan()} onReview={onReview} />);

    const input = screen.getByRole("textbox", { name: /sub-questions #1/i });
    await user.clear(input);
    await user.type(input, "revised Q1");

    await user.click(screen.getByRole("button", { name: /save edits/i }));
    expect(onReview).toHaveBeenCalledTimes(1);
    expect(onReview).toHaveBeenCalledWith("revise", {
      sub_questions: ["revised Q1", "how does Y compare"],
      search_queries: ["X survey", "Y benchmarks"],
    });
  });

  it("filters empty entries out of the revised plan", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<PlanReview plan={makePlan()} onReview={onReview} />);

    const input = screen.getByRole("textbox", { name: /sub-questions #2/i });
    await user.clear(input);
    // Now sub_questions is ["what is X", ""] — one non-empty entry.

    await user.click(screen.getByRole("button", { name: /save edits/i }));
    expect(onReview).toHaveBeenCalledWith("revise", {
      sub_questions: ["what is X"],
      search_queries: ["X survey", "Y benchmarks"],
    });
  });

  it("Reset restores the original plan after edits", async () => {
    const user = userEvent.setup();
    render(<PlanReview plan={makePlan()} onReview={vi.fn()} />);

    const input = screen.getByRole("textbox", { name: /sub-questions #1/i });
    await user.clear(input);
    await user.type(input, "modified");
    expect(screen.getByRole("button", { name: /^reset$/i })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: /^reset$/i }));
    expect(screen.getByDisplayValue("what is X")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^reset$/i })).toBeDisabled();
  });

  it("adds and removes items in each list", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<PlanReview plan={makePlan()} onReview={onReview} />);

    // Remove sub_questions[1].
    await user.click(
      screen.getByRole("button", { name: /remove sub-questions #2/i })
    );

    // Add a new empty search_queries item and fill it.
    await user.click(
      screen.getByRole("button", { name: /add search querie/i })
    );
    const newInput = screen.getByRole("textbox", {
      name: /search queries #3/i,
    });
    await user.type(newInput, "extra search");

    await user.click(screen.getByRole("button", { name: /save edits/i }));
    expect(onReview).toHaveBeenCalledWith("revise", {
      sub_questions: ["what is X"],
      search_queries: ["X survey", "Y benchmarks", "extra search"],
    });
  });

  it("calls onReview with action=cancel on Cancel job", async () => {
    const user = userEvent.setup();
    const onReview = vi.fn();
    render(<PlanReview plan={makePlan()} onReview={onReview} />);

    await user.click(screen.getByRole("button", { name: /cancel job/i }));
    expect(onReview).toHaveBeenCalledWith("cancel", undefined);
  });

  it("disables all buttons while onReview is pending", async () => {
    const user = userEvent.setup();
    let resolve: () => void = () => {};
    const pending = new Promise<void>((r) => {
      resolve = r;
    });
    const onReview = vi.fn(() => pending);

    render(<PlanReview plan={makePlan()} onReview={onReview} />);
    await user.click(
      screen.getByRole("button", { name: /approve as-is/i })
    );

    expect(
      screen.getByRole("button", { name: /cancel job/i })
    ).toBeDisabled();
    resolve();
  });
});
