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
    if (p === "context/entries") {
      const context = b!.context as { mode: string; project_id: string | null; thread_id: string | null; return_to: string };
      const url = new URL(context.return_to, "http://localhost");
      for (const [key, expected] of [["mode", context.mode], ["project", context.project_id], ["thread", context.thread_id]] as const) {
        const values = url.searchParams.getAll(key);
        if (values.length && (values.length !== 1 || values[0] !== expected)) throw new Error("return_context_identity_mismatch");
      }
      if (url.pathname.startsWith("/workspace/threads/") && url.pathname.split("/").pop() !== context.thread_id) throw new Error("return_context_thread_identity_mismatch");
      return { id: `qualification-${JID}`, revision: 1 };
    }
    if (p === "context/threads") return { id: `thread-${"a".repeat(32)}` };
    if (p === `context/projects/${PID}`) return { revision: 3, entries: linked ? [{ entry_id: `qualification-${JID}`, entry_revision: 1 }] : [] };
    if (p === `context/projects/${PID}/entries`) { linked = true; return b; }
    throw new Error("Unexpected endpoint " + p);
  });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
async function mount(selected = true, search = "mode=learn", returnTo = "/workspace/today") {
  history.replaceState(null, "", `/workspace/items/one?${search}${selected ? `&qualification=${JID}` : ""}`);
  return render(<QualificationResult workId="one" versionId="one:v1" returnTo={returnTo} onSource={onSource} />);
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
 const entry=mock.request.mock.calls.find(([p])=>p==="context/entries")![1];expect(entry.context).toEqual({mode:"research",project_id:PID,thread_id:null,return_to:`/workspace/today?mode=research&project=${PID}`});
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

it("keeps partial legacy sections inspectable without inventing assumptions or comparison bases",async()=>{
 const out=jobs[0]!.assistance_output!;delete out.assumptions;delete out.comparison_basis;
 out.comparison="Inspect the independently cited sources before comparing them.";
 await mount();await screen.findByRole("region",{name:"Persisted qualification result"});
 expect(screen.getByText(out.comparison)).toBeInTheDocument();
 expect(screen.queryByText("Conditions apply")).not.toBeInTheDocument();
 expect(screen.getByText(/Basis: \. Compatible conditions and omissions require human review/)).toBeInTheDocument();
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});

it.each([null,{grounding:undefined},{grounding:{assessments:[]}}])("does not infer a supported verdict from an absent checker assessment",async result=>{
 jobs[0]!.result=result;await mount();await screen.findByRole("region",{name:"Persisted qualification result"});
 expect(screen.getByText("Machine checker: unscored. Human support: unmeasured.")).toBeInTheDocument();
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});

it("saves a continued result against its sealed origin and exact passage rather than the current route",async()=>{
 const stored=jobs[0]!.request.assistance;
 stored.origin={mode:"learn",project_id:null,thread_id:`thread-${"f".repeat(32)}`,return_to:"/workspace/library?mode=learn&view=notes"};stored.follow_up="";
 const user=userEvent.setup();await mount();await screen.findByRole("region",{name:"Persisted qualification result"});
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);
 const entry=mock.request.mock.calls.find(([p])=>p==="context/entries")![1];
 expect(entry.context).toEqual(stored.origin);expect(entry.data).toMatchObject({work_id:"one",version_id:"one:v1",anchor:"abstract:0:37"});
 expect(mock.request.mock.calls.find(([p])=>p==="context/threads")![1].data).toMatchObject({origin:stored.origin,goal:"Inspect the retained evidence"});
});

it("renders task-bound full abstention as missing details without claim sections", async () => {
 const output=jobs[0]!.assistance_output!;
 Object.assign(output,{response_disposition:"full_abstention",claims:[],background_claims:[],assumption_claims:[],limitation_claims:[],comparison_claims:[],context_requests:["Provide the vehicle and configuration.","Provide the operating envelope.","Provide safety objectives.","Provide validation evidence."],abstention:"Application context required",comparison_unanswered:false});
 await mount();await screen.findByRole("heading",{name:"No assessment or factual answer produced"});
 for(const request of output.context_requests!)expect(screen.getByText(request)).toBeInTheDocument();
 expect(screen.getByRole("heading",{name:"Missing details · next action"})).toBeInTheDocument();
 expect(screen.queryByRole("article")).not.toBeInTheDocument();
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});
it("retains cited qualification notes while declaring the comparison unanswered", async () => {
 Object.assign(jobs[0]!.assistance_output!,{response_disposition:"comparison_abstention",comparison_unanswered:true,background_claims:["c1"],assumption_claims:[],limitation_claims:[],comparison_claims:[],abstention:"Comparison evidence required"});
 await mount();await screen.findByRole("heading",{name:"Requested comparison remains unanswered"});
 expect(screen.getByRole("button",{name:"Open qualification passage"})).toBeInTheDocument();
 expect(screen.getByRole("region",{name:"Background claim references"})).toHaveTextContent(ref.quote);
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});
it("saves every declared gap and disposition with its original coverage metadata", async () => {
 const out=jobs[0]!.assistance_output!; out.claims=[]; out.response_disposition="full_abstention"; out.coverage_complete=false;
 const row={id:"p1",request:"Assess",kind:"answer",status:"lacks_evidence",gap:"methods",gap_text:"First gap",gap_reasons:["methods","protocol"],gap_texts:["First gap","Second gap"],answer_claim_ids:[],context_claim_ids:[]};
 out.request_coverage=[row]; const user=userEvent.setup(); await mount(); await screen.findByRole("region",{name:"Persisted qualification result"});
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"})); await screen.findByText(/Experimental result saved with its exact source/);
 const body=mock.request.mock.calls.find(([p])=>p==="context/entries")![1].data.body as string;
 expect(body).toContain('"response_disposition":"full_abstention"'); expect(body).toContain(JSON.stringify(row)); expect(body).not.toContain("c1: ");
});
it("downloads the complete abstention and eight multi-gap rows with exact source references", async()=>{
 const job=jobs[0]!,out=job.assistance_output!;out.claims=[];out.response_disposition="full_abstention";out.request_coverage=Array.from({length:8},(_,i)=>({id:`p${i+1}`,request:`Part ${i+1} `+"x".repeat(1800),kind:"answer",status:"lacks_evidence",gap:"methods",gap_text:"First Second Third",gap_reasons:["methods","protocol","data_splits"],gap_texts:["First","Second","Third"],answer_claim_ids:[],context_claim_ids:[]}));
 const blobs:Blob[]=[];Object.defineProperty(URL,"createObjectURL",{configurable:true,value:vi.fn((blob:Blob)=>{blobs.push(blob);return "blob:test";})});Object.defineProperty(URL,"revokeObjectURL",{configurable:true,value:vi.fn()});vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
 const user=userEvent.setup();await mount();await screen.findByRole("region",{name:"Persisted qualification result"});await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source context. The note links/);
 const body=mock.request.mock.calls.find(([p])=>p==="context/entries")![1].data.body as string;expect(Array.from(body).length).toBeLessThanOrEqual(10000);expect(body).toContain(JID);expect(body).toContain(`qualification=${JID}`);
 await user.click(screen.getByRole("button",{name:"Download qualification result JSON"}));const json=await new Promise<string>(resolve=>{const r=new FileReader();r.onload=()=>resolve(String(r.result));r.readAsText(blobs[0]!);});const saved=JSON.parse(json);expect(saved.assistance_output).toEqual(out);expect(saved.source_references).toEqual(job.request.units);expect(saved.job_id).toBe(JID);expect(saved).not.toHaveProperty("contacts");
});


it("uses sealed Learn context when inspected from Research and clears an unsealed thread",async()=>{
 const thread=`thread-${"f".repeat(32)}`;const user=userEvent.setup();
 await mount(true,`mode=research&project=${PID}&thread=${thread}`,`/workspace/threads/${thread}?mode=research&project=${PID}&thread=${thread}`);
 await screen.findByRole("region",{name:"Persisted qualification result"});await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);
 const entry=mock.request.mock.calls.find(([p])=>p==="context/entries")![1];expect(entry.context).toEqual({mode:"learn",project_id:null,thread_id:null,return_to:"/workspace/today?mode=learn"});
 expect(mock.request.mock.calls.find(([p])=>p==="context/threads")![1].data.origin).toEqual(entry.context);
});

it("removes unsealed project and thread query parameters from the fallback return",async()=>{
 const thread=`thread-${"f".repeat(32)}`;const user=userEvent.setup();
 await mount(true,`mode=research&project=${PID}&thread=${thread}`,`/workspace/library?mode=research&project=${PID}&thread=${thread}&view=notes`);
 await screen.findByRole("region",{name:"Persisted qualification result"});await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);
 const entry=mock.request.mock.calls.find(([p])=>p==="context/entries")![1];expect(entry.context).toEqual({mode:"learn",project_id:null,thread_id:null,return_to:"/workspace/today?mode=learn"});
});


it("keeps the same fallback save payload across inspection modes and return paths",async()=>{
 const stored=jobs[0]!.request.assistance;stored.mode="research";stored.project_id=PID;const user=userEvent.setup();
 const first=await mount(true,"mode=learn","/workspace/library?mode=learn&view=notes");await screen.findByRole("region",{name:"Persisted qualification result"});
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);first.unmount();
 await mount(true,`mode=research&project=${PID}`,`/workspace/projects?mode=research&project=${PID}`);await screen.findByRole("region",{name:"Persisted qualification result"});
 await user.click(screen.getByRole("button",{name:"Save experimental learning thread"}));await screen.findByText(/Experimental result saved with its exact source/);
 const entries=mock.request.mock.calls.filter(([p])=>p==="context/entries");expect(entries).toHaveLength(2);expect(entries[0]![1]).toEqual(entries[1]![1]);
 expect(entries[0]![1].context).toEqual({mode:"research",project_id:PID,thread_id:null,return_to:`/workspace/today?mode=research&project=${PID}`});
});
