import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import QualificationResult, { type QualificationJob } from "@/components/workspace/QualificationResult";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/workspace/api", async original => ({ ...await original<typeof import("@/lib/workspace/api")>(), workspaceRequest: mock.request, contextRequest: (p: string, b?: unknown, s?: AbortSignal) => mock.request(`context${p}`, b, s) }));
vi.mock("@/lib/workspace/useContextIndex", () => ({ invalidateContextIndex: vi.fn() }));
const JID = `gen-${"a".repeat(40)}`, PID = `project-${"b".repeat(32)}`;
const ref = { work_id: "one", version_id: "one:v1", material_id: `mat-${"c".repeat(32)}`, span_id: "s1", source_hash: "hash", parser_revision: "text-v1", scope: "abstract" as const, page: null, start: 0, end: 37, quote: "A retained result requires conditions." };
let jobs: QualificationJob[], fail: string | null, linked: boolean;
const onSource = vi.fn();
function job(): QualificationJob {
  return { id: JID, state: "ready", case_id: "learn-method", packet_digest: "packet", simulated: true, source_binding_intact: true,
    request: { assistance: { mode: "learn", work_id: "one", version_id: "one:v1", material_ids: [ref.material_id], span_ids: ["s1"], unit_ids: ["u1"], depth: "overview", direction: "overview", background: "", follow_up: "Explain the method", project_id: null, project_revision: null, parent_job: null, origin: null }, units: { u1: ref }, project_context: null },
    assistance_output: { claims: [{ claim_id: "c1", text: ref.quote, handles: ["u1"], required_scope: "abstract" }], background: "Unverified guide", comparison: "", comparison_basis: [], assumptions: ["Conditions apply"], gaps: ["Methods absent"], questions: ["What challenges it?"], proposal: "Proposed test", abstention: null },
    result: { grounding: { assessments: [{ claim_id: "c1", decision: "abstain", reason: "Unmeasured" }] } }, workflow_usd: "0", checker_usd: "0", unknown_usd: "0", steps: [], contacts: [] };
}
beforeEach(() => {
  jobs = [job()]; fail = null; linked = false; onSource.mockReset();
  mock.request.mockReset().mockImplementation(async (p: string, b?: Record<string, unknown>) => {
    if (fail === p) { fail = null; throw new Error("Synthetic save conflict"); }
    if (p.startsWith("qualification/results?")) return jobs;
    if (p === "context/entries") return { id: `qualification-${JID}`, revision: 1 };
    if (p === "context/threads") return { id: `thread-${"a".repeat(32)}` };
    if (p === `context/projects/${PID}`) return { revision: 3, entries: linked ? [{ entry_id: `qualification-${JID}`, entry_revision: 1 }] : [] };
    if (p === `context/projects/${PID}/entries`) { linked = true; return b; }
    throw new Error("Unexpected endpoint " + p);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function mount(selected = true) {
  history.replaceState(null, "", `/workspace/items/one?mode=learn${selected ? `&qualification=${JID}` : ""}`);
  return render(<QualificationResult workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={onSource} />);
}
it("loads persisted results read-only, opens an exact passage and preserves result identity", async () => {
  const user=userEvent.setup();await mount();await screen.findByRole("region",{name:"Persisted qualification result"});
  expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
  await user.click(screen.getByRole("button",{name:"Open qualification passage"}));expect(onSource).toHaveBeenCalledWith("abstract:0:37");
  await user.click(screen.getByText("Request, exact packet and split accounting"));expect(screen.getByText(/"packet_digest": "packet"/)).toBeInTheDocument();
  await user.click(screen.getByRole("button",{name:"Reload stored qualification results"}));await screen.findByRole("region",{name:"Persisted qualification result"});
});
it("selects a result explicitly without dispatch and keeps empty/error loading distinct",async()=>{
 const user=userEvent.setup();await mount(false);await screen.findByRole("button",{name:/learn-method · ready/});expect(screen.queryByRole("region",{name:"Persisted qualification result"})).not.toBeInTheDocument();
 await user.click(screen.getByRole("button",{name:/learn-method · ready/}));expect(location.search).toContain(JID);
 jobs=[];await user.click(screen.getByRole("button",{name:"Reload stored qualification results"}));await screen.findByText(/No qualification results for this exact version/);expect(screen.getByText(/No substitute was selected/)).toBeInTheDocument();
});
it("retains stable note/thread identities through failed saves",async()=>{
 const user=userEvent.setup();await mount();await screen.findByRole("region",{name:"Persisted qualification result"});fail="context/threads";
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/A note may already be saved/);
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);
 expect(screen.getByRole("link",{name:"Open experimental learning thread →"})).toHaveAttribute("href",`/workspace/threads/thread-${"a".repeat(32)}?mode=learn`);
 const saves=mock.request.mock.calls.filter(([p])=>p==="context/entries");expect(saves[0]![1]).toEqual(saves[1]![1]);expect(saves[0]![1].data).toMatchObject({version_id:"one:v1",anchor:"abstract:0:37"});
});
it("links a research result once and preserves separately cited sources",async()=>{
 const first=jobs[0]!;first.simulated=false;first.request.assistance.mode="research";first.request.assistance.project_id=PID;first.request.project_context={question:"Sealed comparison",revision:2};first.assistance_output!.comparison="Compare conditions";first.assistance_output!.comparison_basis=["c1","c2"];
 first.request.units.u2={...ref,work_id:"two",version_id:"two:v2",scope:"excerpt",page:3};first.assistance_output!.claims.push({claim_id:"c2",text:"Other conditions",handles:["u2"],required_scope:"excerpt"});
 const user=userEvent.setup();await mount();await screen.findByText("Sealed comparison");expect(screen.getByRole("link",{name:"Open qualification passage"}).getAttribute("href")).toContain("version=two%3Av2");
 await user.click(screen.getByRole("button",{name:"Link experimental result to project"}));await screen.findByText(/Experimental result saved with its exact source/);
 await user.click(screen.getByRole("button",{name:"Link experimental result to project"}));await waitFor(()=>expect(screen.getByRole("button",{name:"Link experimental result to project"})).toBeEnabled());expect(mock.request.mock.calls.filter(([p])=>p===`context/projects/${PID}/entries`)).toHaveLength(1);
});
it.each(["failed","cancelled","uncertain","stale"])("does not present %s as accepted content or offer replay",async state=>{
 jobs[0]!.state=state;jobs[0]!.assistance_output=null;jobs[0]!.result=null;jobs[0]!.source_binding_intact=state!=="stale";await mount();await screen.findByText(/No completed content is available/);expect(screen.queryByRole("button",{name:"Save experimental learning thread"})).not.toBeInTheDocument();
});
it("recovers a failed read without inventing an empty successful result",async()=>{
 fail="qualification/results?work_id=one&version_id=one%3Av1";const user=userEvent.setup();await mount();await screen.findByText(/request could not be completed/);expect(screen.queryByText(/No qualification results/)).not.toBeInTheDocument();await user.click(screen.getByRole("button",{name:"Reload stored qualification results"}));await screen.findByRole("region",{name:"Persisted qualification result"});
});
it("ignores a late load after leaving the Reader",async()=>{
 let release!:(value:unknown)=>void;mock.request.mockImplementation(()=>new Promise(resolve=>{release=resolve}));const view=await mount();expect(screen.getByText("Loading quarantined results…")).toBeInTheDocument();view.unmount();await act(async()=>release(jobs));expect(mock.request).toHaveBeenCalledTimes(1);
});
it("keeps explicit abstention visible and never fabricates an unavailable handle",async()=>{
 jobs[0]!.assistance_output!.abstention="Evidence insufficient";jobs[0]!.assistance_output!.claims[0]!.handles=["missing"];await mount();await screen.findByText("Abstention: Evidence insufficient");expect(screen.queryByRole("button",{name:"Open qualification passage"})).not.toBeInTheDocument();
});
it("refuses to save a result without the exact primary source reference",async()=>{
 jobs[0]!.request.units={};const user=userEvent.setup();await mount();await screen.findByRole("region",{name:"Persisted qualification result"});await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});

it("renders purpose-specific learning output without cross-source comparison fields", async () => {
 delete jobs[0]!.assistance_output!.comparison; delete jobs[0]!.assistance_output!.comparison_basis;
 await mount(); await screen.findByRole("region", {name: "Persisted qualification result"});
 expect(screen.getAllByText(ref.quote).length).toBeGreaterThan(0);
 expect(screen.queryByText("Comparison · independently cited basis")).not.toBeInTheDocument();
 expect(mock.request.mock.calls.every(([, body]) => body === undefined)).toBe(true);
});

it("renders new cited sections as links to scored claims without legacy factual prose", async () => {
 const out=jobs[0]!.assistance_output!;
 delete out.background; delete out.assumptions; delete out.comparison;
 out.background_claims=["c1"];out.assumption_claims=[];out.limitation_claims=["c1"];
 await mount();await screen.findByRole("region",{name:"Persisted qualification result"});
 const links=screen.getAllByRole("link",{name:`c1: ${ref.quote}`});
 expect(links).toHaveLength(2);
 for(const link of links)expect(link).toHaveAttribute("href",`#${JID}-c1`);
 expect(document.getElementById(`${JID}-c1`)).toHaveTextContent(ref.quote);
 expect(screen.queryByText("Unverified guide")).not.toBeInTheDocument();
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});
