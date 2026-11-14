import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import QualificationResult, { type QualificationJob } from "@/components/workspace/QualificationResult";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/workspace/api", async original => ({ ...await original<typeof import("@/lib/workspace/api")>(), workspaceRequest: mock.request, contextRequest: (path: string, body?: unknown, signal?: AbortSignal) => mock.request(`context${path}`, body, signal) }));
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

it.each([false, true])("saves a deterministic %s-sized result with its exact source link", async long => {
  const ref = { work_id: "one", version_id: "one:v1", material_id: "mat-source", span_id: "s1", source_hash: "hash", parser_revision: "v1", scope: "abstract" as const, page: null, start: 0, end: 12, quote: "Source quote" };
  const text = long ? "雪🙂 claim ".repeat(1800) + "complete ending" : "short result";
  const job: QualificationJob = {
    id: "gen-save", state: "ready", case_id: "synthetic-save", packet_digest: "synthetic", simulated: true, source_binding_intact: true,
    request: { assistance: { mode: "research", work_id: "one", version_id: "one:v1", material_ids: [ref.material_id], span_ids: [ref.span_id], unit_ids: ["u1"], depth: "overview", direction: "overview", background: "", follow_up: "", project_id: `project-${"a".repeat(32)}`, project_revision: null, parent_job: null, origin: null }, units: { u1: ref }, project_context: null },
    assistance_output: { claims: [{ claim_id: "c12", text, handles: ["u1"], required_scope: "abstract" }], gaps: [], questions: [], proposal: "Proposed test", abstention: null }, result: null,
    workflow_usd: "0", checker_usd: "0", unknown_usd: "0", contacts: [], steps: [],
  };
  let threadAttempt = 0;
  mock.request.mockReset().mockImplementation(async (path: string) => {
    if (path.startsWith("qualification/results?")) return [job];
    if (path === "context/entries") return { id: "qualification-gen-save", revision: 1 };
    if (path === "context/threads") { if (threadAttempt++ === 0) throw new Error("synthetic conflict"); return { id: "thread-synthetic" }; }
    throw new Error(`Unexpected ${path}`);
  });
  history.replaceState(null, "", "/workspace/items/one?qualification=gen-save");
  const user = userEvent.setup();
  render(<QualificationResult workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={vi.fn()} />);
  const region = await screen.findByRole("region", { name: "Persisted qualification result" });
  expect(within(region).getByRole("heading", { name: "Claim c12" }).parentElement?.textContent).toContain(text);
  if (long) expect(within(region).getByText(/saved note links to the complete retained/)).toBeVisible();
  await user.click(within(region).getByRole("button", { name: "Save experimental learning thread" }));
  await screen.findByText(/A note may already be saved/);
  await user.click(within(region).getByRole("button", { name: "Save experimental learning thread" }));
  await screen.findByText(/Experimental result saved with its exact source/);
  const entries = mock.request.mock.calls.filter(([path]) => path === "context/entries");
  expect(entries).toHaveLength(2);
  expect(entries[0]![1]).toEqual(entries[1]![1]);
  const saved = entries[0]![1] as { id: string; request_id: string; data: { body: string; anchor: string } };
  expect(saved.id).toBe("qualification-gen-save");
  expect(saved.request_id).toBe("save-gen-save");
  expect(saved.data.anchor).toBe("abstract:0:12");
  if (long) {
    expect(Array.from(saved.data.body).length).toBeLessThanOrEqual(10000);
    expect(saved.data.body).toContain("complete retained experimental qualification result");
    expect(saved.data.body).toContain(`/workspace/items/one?version=one%3Av1&qualification=gen-save&mode=research&project=project-${"a".repeat(32)}#abstract%3A0%3A12`);
    expect(saved.data.body).not.toContain(text.slice(0, 200));
    expect(screen.getByRole("status")).toHaveTextContent(/note links to the complete retained experimental result/);
  } else {
    expect(saved.data.body).toBe(`Offline simulated qualification result · not quality evidence.\n\nc12: ${text}\n\nProposed next action: Proposed test\n\nQualification record: gen-save`);
  }
});
