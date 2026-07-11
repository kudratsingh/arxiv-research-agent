import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import JobSummary from "@/components/JobSummary";
import type { JobDetail } from "@/lib/types";

function makeDetail(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    job_id: "abc",
    status: "succeeded",
    query: "q",
    created_at: 0,
    started_at: 0,
    completed_at: 42.7,
    elapsed_sec: 42.7,
    result: "# Report",
    error: null,
    error_type: null,
    cost_usd: 0.087,
    llm_calls: 8,
    iterations: 1,
    quality_score: 0.9,
    ...overrides,
  };
}

describe("JobSummary", () => {
  it("renders every metric label", () => {
    render(<JobSummary detail={makeDetail()} />);
    for (const label of [
      "Iterations",
      "Quality",
      "Cost",
      "LLM calls",
      "Elapsed",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("formats numbers per column convention", () => {
    render(<JobSummary detail={makeDetail()} />);
    expect(screen.getByText("1")).toBeInTheDocument(); // iterations
    expect(screen.getByText("0.90")).toBeInTheDocument(); // quality
    expect(screen.getByText("$0.0870")).toBeInTheDocument(); // cost
    expect(screen.getByText("8")).toBeInTheDocument(); // llm_calls
    expect(screen.getByText("42.7s")).toBeInTheDocument(); // elapsed
  });

  it("shows dashes for nulls", () => {
    render(
      <JobSummary
        detail={makeDetail({
          iterations: null,
          quality_score: null,
          cost_usd: null,
          llm_calls: null,
          elapsed_sec: null,
        })}
      />
    );
    const dashes = screen.getAllByText("-");
    expect(dashes).toHaveLength(5);
  });
});
