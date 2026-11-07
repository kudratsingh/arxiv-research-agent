import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScoredSections } from "@/components/workspace/ScoredSections";
import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";
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
});
