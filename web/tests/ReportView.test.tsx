import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ReportView from "@/components/ReportView";
import type { JobDetail } from "@/lib/types";

function makeDetail(overrides: Partial<JobDetail> = {}): JobDetail {
  return {
    job_id: "abc",
    status: "succeeded",
    query: "q",
    created_at: 0,
    started_at: 0,
    completed_at: 1,
    elapsed_sec: 1,
    result: "# Report\n\nBody paragraph.",
    error: null,
    error_type: null,
    cost_usd: null,
    llm_calls: null,
    iterations: null,
    quality_score: null,
    plan: null,
    conversation_id: null,
    ...overrides,
  };
}

describe("ReportView", () => {
  it("renders markdown body as HTML", () => {
    render(<ReportView detail={makeDetail()} />);
    expect(
      screen.getByRole("heading", { level: 1, name: /report/i })
    ).toBeInTheDocument();
    expect(screen.getByText("Body paragraph.")).toBeInTheDocument();
  });

  it("renders failure UI when status is failed", () => {
    render(
      <ReportView
        detail={makeDetail({
          status: "failed",
          result: null,
          error: "workflow blew up",
          error_type: "RuntimeError",
        })}
      />
    );
    expect(screen.getByText(/Job failed/i)).toBeInTheDocument();
    expect(screen.getByText("RuntimeError")).toBeInTheDocument();
    expect(screen.getByText(/workflow blew up/)).toBeInTheDocument();
  });

  it("returns null when there's nothing to show", () => {
    const { container } = render(
      <ReportView
        detail={makeDetail({ result: null, status: "cancelled", error: null })}
      />
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders GFM table syntax", () => {
    render(
      <ReportView
        detail={makeDetail({
          result:
            "| a | b |\n| --- | --- |\n| 1 | 2 |\n",
        })}
      />
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
  });
});
