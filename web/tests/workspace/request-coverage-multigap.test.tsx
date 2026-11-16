import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { AssistanceDisposition, RequestCoverage } from "@/components/workspace/AssistanceTaskContext";
import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";

afterEach(cleanup);
const base = { claims: [], gaps: [], questions: [], proposal: "", abstention: null } satisfies AssistanceOutput;

it("shows every distinct gap, preserves links and falls back for archived rows", () => {
  render(<RequestCoverage prefix="job" output={{ ...base, comparison_unanswered: true, request_coverage: [
    { id: "p1", request: "Compare", kind: "comparison", status: "lacks_evidence", gap_text: "First gap", gap_reasons: ["one", "two"], gap_texts: ["First gap", "Second gap", "First gap"], context_claim_ids: ["c1"] },
    { id: "p2", request: "Definition", kind: "answer", status: "answered", gap_text: "", answer_claim_ids: ["c2"] },
    { id: "p3", request: "Legacy", kind: "answer", status: "omitted", gap_text: "Legacy gap" },
  ] }} />);
  const compare = screen.getByText("Compare").closest("li")!;
  expect(compare).toHaveTextContent("Lacks evidence · First gap · Second gap");
  expect(compare.textContent?.match(/First gap/g)).toHaveLength(1);
  expect(within(compare).getByRole("link", { name: "c1" })).toHaveAttribute("href", "#job-c1");
  expect(within(compare).queryByText(/Declared answered/)).toBeNull();
  expect(screen.getByRole("link", { name: "c2" })).toHaveAttribute("href", "#job-c2");
  expect(screen.getByText(/Omitted from this response · Legacy gap/)).toBeVisible();
});

it("does not invent an omission or complete status for an unknown row", () => {
  render(<RequestCoverage prefix="job" output={{ ...base, coverage_complete: true, request_coverage: [
    { id: "p1", request: "Unscored", kind: "answer", status: "unscored", gap_text: "Unavailable" },
  ] }} />);
  expect(screen.getByText(/Coverage status unavailable · Unavailable/)).toBeVisible();
  expect(screen.queryByText(/Omitted from this response/)).toBeNull();
  expect(screen.queryByText(/All requested parts declared answered/)).toBeNull();
});

it("does not show claim links or answered status for a full abstention", () => {
  const output: AssistanceOutput = { ...base, response_disposition: "full_abstention", coverage_complete: true, request_coverage: [
    { id: "p1", request: "Assess", kind: "answer", status: "answered", gap_text: "", answer_claim_ids: ["c1"], context_claim_ids: ["c2"] },
  ] };
  render(<><AssistanceDisposition output={output} /><RequestCoverage prefix="job" output={output} /></>);
  expect(screen.getByText("No assessment or factual answer produced")).toBeVisible();
  expect(screen.getByText("Coverage status inconsistent")).toBeVisible();
  expect(screen.queryByRole("link")).toBeNull();
  expect(screen.queryByText(/All requested parts declared answered/)).toBeNull();
});

it("does not declare an unanswered comparison answered", () => {
  render(<RequestCoverage prefix="job" output={{ ...base, comparison_unanswered: true, coverage_complete: true, request_coverage: [
    { id: "p1", request: "Compare", kind: "comparison", status: "answered", gap_text: "" },
  ] }} />);
  expect(screen.getByText("Coverage status inconsistent")).toBeVisible();
  expect(screen.queryByText(/All requested parts declared answered/)).toBeNull();
});
it("keeps the legacy no-gap message hidden on answered rows", () => {
  render(<RequestCoverage prefix="job" output={{ ...base, coverage_complete: true, request_coverage: [
    { id: "p1", request: "Answered", kind: "answer", status: "answered", gap: "none", gap_text: "No evidence gap declared." },
  ] }} />);
  expect(screen.getByText("Declared answered")).toBeVisible();
  expect(screen.queryByText(/No evidence gap declared/)).toBeNull();
});


// The successor's partial declaration preserves genuine gaps without full credit.
it("shows partial answers and every remaining gap without declaring completion", () => {
  render(<RequestCoverage prefix="partial-job" output={{ ...base, coverage_complete: true, request_coverage: [
    { id: "p1", request: "Explain the method and protocol", kind: "answer", status: "partial", gap_text: "Protocol unavailable", gap_reasons: ["protocol", "data_splits"], gap_texts: ["Protocol unavailable", "Data split unavailable"], answer_claim_ids: ["c1"], context_claim_ids: ["c2"] },
  ] }} />);
  expect(screen.getByText(/Partially answered · remaining gaps · Protocol unavailable · Data split unavailable/)).toBeVisible();
  expect(screen.getByRole("link", { name: "c1" })).toHaveAttribute("href", "#partial-job-c1");
  expect(screen.getByRole("link", { name: "c2" })).toHaveAttribute("href", "#partial-job-c2");
  expect(screen.queryByText(/All requested parts declared answered/)).toBeNull();
  expect(screen.queryByText("Declared answered")).toBeNull();
});
