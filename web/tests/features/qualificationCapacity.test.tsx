import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import QualificationResult, { type QualificationJob } from "@/components/workspace/QualificationResult";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/workspace/api", async original => ({ ...await original<typeof import("@/lib/workspace/api")>(), workspaceRequest: mock.request }));
vi.mock("@/lib/workspace/useContextIndex", () => ({ invalidateContextIndex: vi.fn() }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("shows all synthetic qualification claims and full Unicode checker reasons", async () => {
  const longText = `Synthetic Ω漢🙂 "quoted" \\ path\n${"scope λ ".repeat(130)}end`;
  const longReason = `Synthetic reason: "scope" \\ condition\n${"雪🙂 ".repeat(150)}end`;
  const claims = Array.from({ length: 12 }, (_, index) => ({ claim_id: `c${index + 1}`, text: `${index + 1}: ${longText}`, handles: [], required_scope: "abstract" }));
  const job: QualificationJob = {
    id: "gen-synthetic", state: "ready", case_id: "synthetic-capacity", packet_digest: "synthetic", simulated: true, source_binding_intact: true,
    request: { assistance: { mode: "research", work_id: "one", version_id: "one:v1", material_ids: [], span_ids: [], unit_ids: [], depth: "overview", direction: "overview", background: "", follow_up: "", project_id: null, project_revision: null, parent_job: null, origin: null }, units: {}, project_context: null },
    assistance_output: { claims, gaps: [], questions: [], proposal: "", abstention: null }, result: null,
    workflow_usd: "0", checker_usd: "0", unknown_usd: "0", contacts: [],
    steps: [{ stage: "check", output: { checks: [{ claim_id: "c12", decision: "uncertain", reason: longReason }] } }],
  };
  mock.request.mockResolvedValue([job]);
  history.replaceState(null, "", "/workspace/items/one?qualification=gen-synthetic");
  render(<QualificationResult workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={vi.fn()} />);
  const region = await screen.findByRole("region", { name: "Persisted qualification result" });
  for (const claim of claims) {
    const heading = within(region).getByRole("heading", { name: `Claim ${claim.claim_id}` });
    expect(heading.parentElement?.textContent).toContain(claim.text);
  }
  await userEvent.setup().click(within(region).getByText("Stored machine checker reasons"));
  expect(within(region).getByText(longReason, { exact: true, normalizer: text => text })).toBeVisible();
  expect(mock.request.mock.calls.every(([, body]) => body === undefined)).toBe(true);
});
