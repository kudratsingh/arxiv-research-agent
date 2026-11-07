import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScoredSections } from "@/components/workspace/ScoredSections";
import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";
import { settleReaderTarget } from "@/lib/workspace/navigation";
vi.mock("@/lib/workspace/navigation", () => ({ settleReaderTarget: vi.fn() }));
const output: AssistanceOutput = { claims: [{ claim_id: "c1", text: "The source tentatively suggests a trade-off.", handles: ["u1"], required_scope: "excerpt" }], background_claims: ["c1"], assumption_claims: ["c1"], limitation_claims: ["c1"], comparison_claims: ["c1"], gaps: ["Inspect additional evidence before comparing performance."], questions: ["Does evidence establish a difference?"], proposal: "Inspect the methods.", abstention: null };
describe("scored section references", () => {
  it("links every displayed statement to its scored claim and existing citations", () => {
    render(<ScoredSections output={output} prefix="job" />);
    for (const link of screen.getAllByRole("link")) expect(link).toHaveAttribute("href", "#job-c1");
    expect(screen.getByRole("region", { name: "Comparison claim references" })).toBeVisible();
  });
  it("does not substitute a different claim for an unavailable reference", () => {
    render(<ScoredSections output={{ ...output, background_claims: ["c6"], assumption_claims: [], limitation_claims: [], comparison_claims: [] }} prefix="job" />);
    expect(screen.getByRole("link")).toHaveTextContent("c6: Claim unavailable");
    expect(screen.getByRole("link")).toHaveAttribute("href", "#job-c6");
  });
  it("allows empty sections for insufficient evidence without invented prose", () => {
    render(<ScoredSections output={{ ...output, claims: [], background_claims: [], assumption_claims: undefined, limitation_claims: [], comparison_claims: undefined }} prefix="job" />);
    expect(screen.queryAllByRole("link")).toHaveLength(0);
    expect(screen.getByText("Inspect additional evidence before comparing performance.")).toBeVisible();
  });
  it("restores only the selected result's existing claim after asynchronous result loading", () => {
    vi.mocked(settleReaderTarget).mockClear();
    history.replaceState(null, "", "#job-c1");
    const view=render(<><article id="job-c1">Scored claim with its original citations</article><ScoredSections output={output} prefix="job" /></>);
    expect(settleReaderTarget).toHaveBeenCalledWith(document.getElementById("job-c1"));
    view.unmount();vi.mocked(settleReaderTarget).mockClear();
    render(<ScoredSections output={output} prefix="job" />);
    expect(settleReaderTarget).not.toHaveBeenCalled();
    history.replaceState(null,"",location.pathname);
  });
});

// Evidence-request codes are rendered locally; historical prose stays verbatim.
it("renders prospective evidence requests and preserves historical gap text", () => {
  render(<ScoredSections output={{ ...output, gaps: ["evaluation", "ablations", "Historical retained gap"] }} prefix="job" />);
  expect(screen.getByText("Request evaluation sections, benchmarks, baselines and metrics from each selected source.")).toBeInTheDocument();
  expect(screen.getByText("Request ablations and controlled comparisons from each selected source.")).toBeInTheDocument();
  expect(screen.getByText("Historical retained gap")).toBeInTheDocument();
});
