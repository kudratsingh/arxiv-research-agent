import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AssistanceTaskContext, RequestCoverage, taskDefaults } from "@/components/workspace/AssistanceTaskContext";
import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";
afterEach(cleanup);
const output = { claims: [], gaps: [], questions: [], proposal: "", abstention: null } satisfies AssistanceOutput;
it("keeps unanswered comparison distinct from separately cited context and omissions", () => {
  render(<RequestCoverage prefix="job" output={{ ...output, coverage_complete: false, request_coverage: [
    { id: "p1", request: "Compare relevance", kind: "comparison", status: "lacks_evidence", gap_text: "Request common evaluation", context_claim_ids: ["c1"] },
    { id: "p2", request: "Metric definition", kind: "answer", status: "answered", gap_text: "", answer_claim_ids: ["c2"] },
    { id: "p3", request: "Secondary detail", kind: "answer", status: "omitted", gap_text: "Six-claim budget" },
  ] }} />);
  expect(screen.getByRole("heading", { name: "Request only partially answered or unanswered" })).toBeVisible();
  expect(screen.getByText(/Context only · does not answer/)).toBeVisible();
  expect(screen.getByRole("link", {name:"c1"})).toHaveAttribute("href", "#job-c1");
  expect(screen.getByText(/Omitted from this response/)).toBeVisible();
  expect(screen.getByText(/Lacks evidence/)).toBeVisible();
  expect(screen.getByText(/human review unmeasured/)).toBeVisible();
});
it("handles archived absent coverage and declared completion without truth claims", () => {
 const view=render(<RequestCoverage prefix="job" output={output} />);
 expect(screen.queryByRole("region")).toBeNull();
 view.rerender(<RequestCoverage prefix="job" output={{...output, coverage_complete:true, coverage_basis:"Machine proposed; not qualified",request_coverage:[]}} />);
 expect(screen.getByRole("heading", {name:"All requested parts declared answered"})).toBeVisible();
 expect(screen.getByText("Machine proposed; not qualified")).toBeVisible();
});
it("records editable parts before generation and leaves old recovered drafts usable", () => {
 const change=vi.fn();const view=render(<AssistanceTaskContext values={{intent:"answer"}} research={false} busy={false} change={change} />);
 const input=screen.getByLabelText(/Requested parts/);expect(input).toHaveValue("");
 fireEvent.change(input,{target:{value:"Mechanism\nConditions"}});
 expect(change).toHaveBeenCalledWith("requested_parts","Mechanism\nConditions");
 view.rerender(<AssistanceTaskContext values={taskDefaults} research={false} busy={true} change={change} />);
 expect(screen.getByLabelText(/Requested parts/)).toBeDisabled();
});

 it("renders normalized v9 missing-protocol c5 as context only, never an answer", async () => {
  const normalized = await import("./fixtures/coverage-shapes.json");
  render(<RequestCoverage prefix="v9" output={{ ...output, coverage_complete: false, request_coverage: normalized.request_coverage as AssistanceOutput["request_coverage"] }} />);
  expect(screen.getByText("Unspecified protocol and breakdowns")).toBeVisible();
  expect(screen.getByText(/Lacks evidence/)).toBeVisible();
  expect(screen.getByText(/Context only · does not answer/)).toBeVisible();
  expect(screen.getByRole("link", {name:"c5"})).toHaveAttribute("href", "#v9-c5");
  expect(screen.queryByText("Declared answered")).toBeNull();
 });
