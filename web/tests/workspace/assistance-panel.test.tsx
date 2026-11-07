import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AssistancePanel from "@/components/workspace/AssistancePanel";
import { resetDraftMemory } from "@/lib/workspace/draftMemory";
import { passageAnchor, type AssistanceJob, type EvidenceUnit } from "@/lib/workspace/assistanceTypes";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/workspace/api", async original => ({ ...await original<typeof import("@/lib/workspace/api")>(), workspaceRequest: mock.request, contextRequest: (p: string, b?: unknown, s?: AbortSignal) => mock.request(`context${p}`, b, s) }));
vi.mock("@/lib/workspace/useContextIndex", () => ({ invalidateContextIndex: vi.fn() }));
const PID = `project-${"a".repeat(32)}`, JID = `fake-${"b".repeat(40)}`;
const units: EvidenceUnit[] = [
  { id: "u1", title: "Paper one", material_hash: "hash-one", warnings: ["Abstract only; methods unavailable."], complete: false, reference: { work_id: "one", version_id: "one:v1", material_id: `mat-${"a".repeat(32)}`, span_id: "s1", source_hash: "source-one", parser_revision: "text-v1", scope: "abstract", page: null, start: 0, end: 40, quote: "The result required tools. It is limited." } },
  { id: "u2", title: "Paper two", material_hash: "hash-two", warnings: [], complete: true, reference: { work_id: "two", version_id: "two:v2", material_id: `mat-${"b".repeat(32)}`, span_id: "s2", source_hash: "source-two", parser_revision: "pdf-v1", scope: "excerpt", page: 3, start: 10, end: 30, quote: "A separate source result." } },
];
let current: AssistanceJob | null, failures: Set<string>, entries: { entry_id: string; entry_revision: number }[], hold: Promise<void> | null;
const onSource = vi.fn();
function job(state = "queued", research = false): AssistanceJob {
  return { id: JID, state, revision: state === "queued" ? 0 : state === "checking" ? 2 : 4, kind: "deep_dive", request_digest: "digest",
    request: { assistance: { mode: research ? "research" : "learn", work_id: "one", version_id: "one:v1", material_ids: [units[0]!.reference.material_id], span_ids: ["s1"], unit_ids: ["u1"], depth: "overview", direction: "overview", background: "", follow_up: "", project_id: research ? PID : null, project_revision: research ? 3 : null, parent_job: null, origin: null }, units: { u1: units[0]!.reference, u2: units[1]!.reference }, project_context: research ? { question: "Sealed question", revision: 3 } : null },
    result: state.startsWith("ready") ? { simulated: true } : null,
    assistance_output: state.startsWith("ready") ? { claims: [{ claim_id: "c1", text: units[0]!.reference.quote, handles: ["u1"], required_scope: "abstract" }, ...(research ? [{ claim_id: "c2", text: units[1]!.reference.quote, handles: ["u2"], required_scope: "excerpt" }] : [])], background: "Unverified simulated background.", comparison: research ? "Inspect both sources." : "", comparison_basis: research ? ["c1", "c2"] : [], assumptions: ["Check conditions."], gaps: ["Methods missing."], questions: ["What challenges this?"], proposal: "Proposed manual experiment.", abstention: null } : null,
    usage: { used_calls: state === "queued" ? 0 : 2, actual_usd: "0.000000" }, error: null, steps: [], simulated: true, human_review: null, quality: { factual_acceptance: false, checker_qualified: false, basis: "Unmeasured", claim_checks: [{claim_id:"c1",decision:"abstain",reason:"Unmeasured interpretation"}] }, wire_records: [],
  } as unknown as AssistanceJob;
}
async function request(p: string, b?: Record<string, unknown>) {
  if (failures.delete(p)) throw new Error("Deliberate endpoint failure");
  if (p.startsWith("assistance/catalog")) return { units };
  if (p.startsWith("assistance/jobs?")) return current ? [current] : [];
  if (p === `context/projects/${PID}`) return { id: PID, revision: 3, data: { question: "Sealed question" }, entries };
  if (p === "assistance/preview") return { request_digest: "digest", request: { assistance: b!.input, capacity: { basis: "UTF8 bytes, not tokens", provider_token_counts: null }, candidate_initial_wire: { selected_only: true } } };
  if (p === "assistance/jobs") { current = job("queued", location.search.includes("research")); current.request.assistance = b!.input as AssistanceJob["request"]["assistance"]; return structuredClone(current); }
  if (p === `assistance/jobs/${JID}/advance`) {
    if (hold) await hold;
    if (current?.state !== "cancelled") { const input = current!.request.assistance; current = job(current?.state === "queued" ? "checking" : "ready", input.mode === "research"); current.request.assistance = input; }
    return structuredClone(current);
  }
  if (p === `assistance/jobs/${JID}/cancel`) { current = { ...current!, state: "cancelled", revision: 10 }; return current; }
  if (p.startsWith(`assistance/jobs/${JID}`)) return current;
  if (p === "context/entries") return { id: `assistance-${JID}`, revision: 1 };
  if (p === "context/threads") return { id: `thread-${JID.slice(5, 37)}` };
  if (p === `context/projects/${PID}/entries`) { entries.push({ entry_id: b!.entry_id as string, entry_revision: b!.entry_revision as number }); return {}; }
  throw new Error("Unexpected test endpoint " + p);
}
async function mount(research = false, saved = false) {
  history.replaceState(null, "", `/workspace/items/one?mode=${research ? `research&project=${PID}` : "learn"}${saved ? `&assistance=${JID}` : ""}`);
  const view = render(<AssistancePanel owner="verification" workId="one" versionId="one:v1" returnTo={research ? `/workspace/projects?mode=research&project=${PID}` : "/workspace/today?mode=learn"} onSource={onSource} />);
  await screen.findByText("Paper one · abstract"); return view;
}
async function select(user: ReturnType<typeof userEvent.setup>, both = false) {
  await user.click(screen.getByText("Paper one · abstract")); await user.click(screen.getAllByLabelText("Include this evidence unit")[0]!);
  if (both) { await user.click(screen.getByText("Paper two · excerpt · page 3")); await user.click(screen.getAllByLabelText("Include this evidence unit")[1]!); }
}
async function preview(user: ReturnType<typeof userEvent.setup>) { await user.click(screen.getByRole("button", { name: "Preview assistance request" })); await screen.findByRole("region", { name: "Sealed assistance request" }); }
async function run(user: ReturnType<typeof userEvent.setup>) { await user.click(screen.getByRole("button", { name: "Run local assistance simulation · $0" })); await screen.findByRole("region", { name: "Simulated assistance result" }); }

it("resumes the cited-section contract without adding unscored scientific statements",async()=>{
 current=job("ready",true);const out=current.assistance_output!;
 delete out.background;delete out.assumptions;delete out.comparison;
 out.background_claims=["c1"];out.assumption_claims=["c1"];out.limitation_claims=[];out.comparison_claims=["c1","c2"];
 await mount(true,true);await screen.findByRole("region",{name:"Simulated assistance result"});
 const source=screen.getByRole("region",{name:"Comparison claim references"});
 expect(within(source).getByRole("link",{name:/^c1:/})).toHaveAttribute("href",`#${JID}-c1`);
 expect(within(source).getByRole("link",{name:/^c2:/})).toHaveAttribute("href",`#${JID}-c2`);
 expect(document.getElementById(`${JID}-c2`)).toHaveTextContent(out.claims[1]!.text);
 expect(screen.queryByText("Unverified simulated background.")).not.toBeInTheDocument();
 expect(mock.request.mock.calls.every(([,body])=>body===undefined)).toBe(true);
});
beforeEach(() => { current = null; failures = new Set(); entries = []; hold = null; resetDraftMemory(); sessionStorage.clear(); mock.request.mockReset().mockImplementation(request); onSource.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("D5 assistance interaction contract", () => {
  it("requires explicit preview and execution, binds editable context, then navigates an exact citation", async () => {
    const user = userEvent.setup(); await mount(); expect(mock.request.mock.calls.every(([, b]) => b === undefined)).toBe(true);
    await user.selectOptions(screen.getByLabelText("Explanation depth"), "technical"); await user.selectOptions(screen.getByLabelText("Dive direction"), "assumptions");
    await user.type(screen.getByLabelText("Background to include explicitly"), "Probability"); await select(user); await preview(user);
    expect(mock.request.mock.calls.filter(([p]) => p === "assistance/jobs")).toHaveLength(0);
    await user.click(screen.getByText("Exact candidate request · selected evidence only")); expect(within(screen.getByText("Exact candidate request · selected evidence only").closest("details")!).getByText(/"selected_only": true/)).toBeInTheDocument();
    await run(user); expect(mock.request.mock.calls.find(([p]) => p === "assistance/jobs")![1].input).toMatchObject({ mode: "learn", depth: "technical", background: "Probability", direction: "assumptions", project_id: null });
    await user.click(screen.getByRole("button", { name: "Open exact cited passage" })); expect(onSource).toHaveBeenCalledWith("abstract:0:40");
    await user.click(screen.getByRole("button", { name: "Inspect stored status" })); await user.click(screen.getByRole("button", { name: "Recover interrupted status" }));
    await user.click(screen.getByRole("button", { name: "What challenges this?" })); expect(screen.getByLabelText("Follow-up question")).toHaveValue("What challenges this?");
    await user.click(screen.getByRole("button", { name: "Discard assistance edits" })); expect(screen.getByLabelText("Follow-up question")).toHaveValue("");
    await user.click(screen.getByText("Resume saved assistance for this version")); await user.click(screen.getByRole("button", { name: /learn · assumptions · Completed simulation/ })); expect(location.search).toContain("assistance=");
  });
  it("keeps a two-source comparison and retry-safe project note links", async () => {
    const user = userEvent.setup(); await mount(true); await select(user, true); await preview(user); await run(user);
    expect(mock.request.mock.calls.find(([p]) => p === "assistance/jobs")![1].input).toMatchObject({ project_id: PID, project_revision: 3, unit_ids: ["u1", "u2"] });
    const href = screen.getByRole("link", { name: "Open exact cited passage" }).getAttribute("href")!;
    expect(decodeURIComponent(href)).toContain(passageAnchor(units[1]!.reference)); expect(href).toContain("version=two%3Av2"); expect(href).toContain(PID);
    expect(screen.getByText(/Separate evidence basis: c1, c2/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save simulation to project notes" })); await screen.findByText(/saved as a shared note and linked/);
    await user.click(screen.getByRole("button", { name: "Save simulation to project notes" })); await waitFor(() => expect(screen.getByRole("button", { name: "Save simulation to project notes" })).toBeEnabled());
    expect(mock.request.mock.calls.filter(([p]) => p === `context/projects/${PID}/entries`)).toHaveLength(1);
  });
  it("saves shared notes and exact-origin threads with the same identity after a failed save", async () => {
    const user = userEvent.setup(); await mount(); await select(user); await preview(user); await run(user); failures.add("context/threads");
    await user.click(screen.getByRole("button", { name: "Save simulation to a learning thread" })); await screen.findByText(/A shared note may already be saved/);
    await user.click(screen.getByRole("button", { name: "Save simulation to a learning thread" })); await screen.findByRole("link", { name: "Open saved learning thread" });
    const attempts = mock.request.mock.calls.filter(([p]) => p === "context/entries"); expect(attempts[0]![1]).toEqual(attempts[1]![1]); expect(attempts[0]![1].data).toMatchObject({ version_id: "one:v1", anchor: "abstract:0:40" });
    expect(attempts[0]![1].data.body).toContain("human support unmeasured");
  });
  it.each(["assistance/preview", "assistance/jobs", `assistance/jobs/${JID}/advance`])("keeps edits and refuses blind retry after %s fails", async endpoint => {
    const user = userEvent.setup(); await mount(); await select(user); failures.add(endpoint);
    await user.click(screen.getByRole("button", { name: "Preview assistance request" }));
    if (endpoint !== "assistance/preview") { await screen.findByRole("region", { name: "Sealed assistance request" }); await user.click(screen.getByRole("button", { name: "Run local assistance simulation · $0" })); }
    await screen.findByText(/request could not be completed/); expect(screen.getAllByLabelText("Include this evidence unit")[0]).toBeChecked(); expect(mock.request.mock.calls.filter(([p]) => p === endpoint)).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Simulated assistance result" })).not.toBeInTheDocument();
  });
  it("recovers a failed context load without fabricating evidence", async () => {
    failures.add("assistance/catalog?work_id=one&version_id=one%3Av1"); const user = userEvent.setup(); history.replaceState(null, "", "/workspace/items/one?mode=learn");
    render(<AssistancePanel owner="a" workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={onSource} />);
    await screen.findByText(/request could not be completed/); expect(screen.getByRole("button", { name: "Preview assistance request" })).toBeDisabled(); await user.click(screen.getByRole("button", { name: "Retry loading assistance" })); await screen.findByText("Paper one · abstract");
  });
  it("recovers unsaved edits across remount and reports a storage outage", async () => {
    const user = userEvent.setup(); const view = await mount(); vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("storage offline"); });
    await user.type(screen.getByLabelText("Follow-up question"), "Keep this question"); expect(screen.getByText(/Draft recovery is unavailable/)).toBeInTheDocument(); view.unmount(); await mount(); expect(screen.getByLabelText("Follow-up question")).toHaveValue("Keep this question");
  });
  it("cancels a pending local stage without starting a second one", async () => {
    const user = userEvent.setup(); await mount(); await select(user); await preview(user); let release!: () => void; hold = new Promise<void>(resolve => { release = resolve; });
    await user.click(screen.getByRole("button", { name: "Run local assistance simulation · $0" })); await screen.findByRole("heading", { name: "Running local pipeline" });
    await user.click(screen.getByRole("button", { name: "Cancel simulation" })); await waitFor(() => expect(current?.state).toBe("cancelled")); await act(async () => release());
    await waitFor(() => expect(screen.getByRole("button", { name: "Preview assistance request" })).toBeEnabled()); expect(mock.request.mock.calls.filter(([p]) => p === `assistance/jobs/${JID}/advance`)).toHaveLength(1);
  });
  it("loads a failed durable job by URL without executing or accepting its output", async () => {
    current = job("failed"); current.error = "invalid_fake_draft_or_checks"; await mount(false, true); await screen.findByRole("heading", { name: "Failed" });
    expect(screen.getByText(/Failed or interrupted output is not an accepted result/)).toBeInTheDocument(); expect(mock.request.mock.calls.every(([, b]) => b === undefined)).toBe(true);
    expect(screen.queryByRole("region", { name: "Simulated assistance result" })).not.toBeInTheDocument();
  });
  it("resumes a queued durable job only after explicit activation", async () => {
    current = job("queued"); const user = userEvent.setup(); await mount(); await user.click(screen.getByText("Resume saved assistance for this version")); await user.click(screen.getByRole("button", { name: /learn · overview · Queued/ }));
    expect(mock.request.mock.calls.every(([, b]) => b === undefined)).toBe(true); await user.click(screen.getByRole("button", { name: "Continue saved simulation" })); await screen.findByRole("region", { name: "Simulated assistance result" });
  });
});

describe("D5 durable boundary failures", () => {
  it("clears stale selection deliberately and retains a blank, useful evidence state", async () => {
    const user = userEvent.setup(); await mount(); await select(user); await user.click(screen.getAllByLabelText("Include this evidence unit")[0]!);
    expect(screen.getByRole("button", { name: "Preview assistance request" })).toBeDisabled();
    mock.request.mockImplementation(async (p: string, b?: Record<string, unknown>) => p.startsWith("assistance/catalog") ? { units: [] } : request(p, b));
    await user.click(screen.getByRole("button", { name: "Reload assistance context" })); await screen.findByText(/No coherent retained passages/);
  });
  it("renders partial abstentions, stale revisions and recovers inspection failures without a new job", async () => {
    current = job("ready_partial", true); current.request.project_context!.revision = 2;
    current.assistance_output!.abstention = "Insufficient scope";
    const user = userEvent.setup(); await mount(true, true);
    await screen.findByText(/Abstention: Insufficient scope/); expect(screen.getByText(/The project has changed/)).toBeInTheDocument();
    failures.add(`assistance/jobs/${JID}`); await user.click(screen.getByRole("button", { name: "Inspect stored status" })); await screen.findByText(/request could not be completed/);
    await user.click(screen.getByRole("button", { name: "Inspect stored status" })); expect(mock.request.mock.calls.filter(([p]) => p === "assistance/jobs")).toHaveLength(0);
    failures.add(`context/projects/${PID}/entries`); await user.click(screen.getByRole("button", { name: "Save simulation to project notes" })); await screen.findByText(/A shared note may already be saved/);
  });
  it("preserves pending work across component disposal instead of retrying", async () => {
    const user = userEvent.setup(); const view = await mount(); await select(user); await preview(user);
    let release!: () => void; hold = new Promise<void>(resolve => { release = resolve; });
    await user.click(screen.getByRole("button", { name: "Run local assistance simulation · $0" })); await screen.findByRole("heading", {name:"Running local pipeline"});
    view.unmount(); await act(async () => release()); expect(mock.request.mock.calls.filter(([p]) => p === `assistance/jobs/${JID}/advance`)).toHaveLength(1);
  });
  it("shows an unavailable project, refuses preview, and never dispatches on context load", async () => {
    const user = userEvent.setup(); history.replaceState(null, "", "/workspace/items/one?mode=research");
    render(<AssistancePanel owner="verification" workId="one" versionId="one:v1" returnTo="/workspace/projects?mode=research" onSource={onSource}/>);
    await screen.findByText(/Select a Research project/); await select(user);
    expect(screen.getByRole("button", {name:"Preview assistance request"})).toBeDisabled();
  });
});

it("saves against the current source even when JSONB returns the comparison source first", async () => {
  current=job("ready",true);current.request.units={u2:units[1]!.reference,u1:units[0]!.reference};current.request.assistance.origin={mode:"research",project_id:PID,thread_id:null,return_to:"/workspace/projects?mode=research&project="+PID};
  const user=userEvent.setup();await mount(true,true);await screen.findByRole("region",{name:"Simulated assistance result"});
  await user.click(screen.getByRole("button",{name:"Save simulation to project notes"}));await screen.findByText(/saved as a shared note and linked/);
  expect(mock.request.mock.calls.find(([p])=>p==="context/entries")![1].data).toMatchObject({work_id:"one",version_id:"one:v1",anchor:"abstract:0:40"});
});
it("retains a removed selection until explicit discard, never silently rebinding",async()=>{
 const user=userEvent.setup();await mount();await select(user);
 mock.request.mockImplementation(async(p:string,b?:Record<string,unknown>)=>p.startsWith("assistance/catalog")?{units:[]}:request(p,b));
 await user.click(screen.getByRole("button",{name:"Reload assistance context"}));await screen.findByText(/Some selected passages are unavailable/);
 await user.click(screen.getByRole("button",{name:"Discard assistance edits"}));expect(screen.queryByText(/Some selected passages are unavailable/)).not.toBeInTheDocument();
});
it("pauses at four persisted stages and never starts a fifth automatically",async()=>{
 current=job("queued");const user=userEvent.setup();await mount(false,true);await screen.findByRole("heading",{name:"Queued"});
 mock.request.mockImplementation(async(p:string,b?:Record<string,unknown>)=>p.endsWith('/advance')?current:request(p,b));
 await user.click(screen.getByRole("button",{name:"Continue saved simulation"}));await screen.findByText(/Paused at a durable stage/);
 expect(mock.request.mock.calls.filter(([p])=>p.endsWith('/advance'))).toHaveLength(4);
});

it.each(["not-json","[3]"])("refuses recovered malformed evidence selection %s without a request", async units => {
 sessionStorage.setItem(`arxiv.workspace.manual-draft.v1:${JSON.stringify(["verification","assistance:one:one:v1:learn:"])}`,JSON.stringify({id:"assistance",revision:0,values:{depth:"overview",background:"",direction:"overview",follow_up:"",units}}));
 await mount();expect(screen.getByRole("button",{name:"Preview assistance request"})).toBeDisabled();expect(mock.request.mock.calls.every(([,b])=>b===undefined)).toBe(true);
});
it("does not fabricate a citation when a stored result's selected handle is unavailable", async()=>{
 current=job("ready_partial");current.assistance_output!.claims[0]!.handles=["missing"];
 await mount(false,true);await screen.findByRole("region",{name:"Simulated assistance result"});
 expect(screen.queryByRole("button",{name:"Open exact cited passage"})).not.toBeInTheDocument();expect(screen.getByText(/Simulated checker: abstain/)).toBeInTheDocument();
});
it("ignores a late catalog response after navigation without starting work",async()=>{
 let release!:(value:unknown)=>void;const pending=new Promise(resolve=>{release=resolve});
 mock.request.mockImplementation((p:string,b?:Record<string,unknown>)=>p.startsWith("assistance/catalog")?pending:request(p,b));
 history.replaceState(null,"","/workspace/items/one?mode=learn");const view=render(<AssistancePanel owner="verification" workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={onSource}/>);
 expect(screen.getByText("Loading retained evidence…")).toBeInTheDocument();expect(screen.queryByText(/No coherent retained passages/)).not.toBeInTheDocument();view.unmount();await act(async()=>release({units}));expect(mock.request.mock.calls.every(([,b])=>b===undefined)).toBe(true);
});
it("distinguishes unavailable project context from an empty project selection",async()=>{
 failures.add(`context/projects/${PID}`);history.replaceState(null,"",`/workspace/items/one?mode=research&project=${PID}`);
 render(<AssistancePanel owner="verification" workId="one" versionId="one:v1" returnTo="/workspace/projects" onSource={onSource}/>);
 await screen.findByText(/Research project context is unavailable/);expect(screen.getByRole("button",{name:"Preview assistance request"})).toBeDisabled();expect(mock.request.mock.calls.every(([,b])=>b===undefined)).toBe(true);
});

it("renders a single-paper explanation without cross-source comparison fields", async () => {
 current=job("ready"); delete current.assistance_output!.comparison; delete current.assistance_output!.comparison_basis;
 history.replaceState(null, "", `/workspace/items/one?mode=learn&assistance=${JID}`);
 render(<AssistancePanel owner="test" workId="one" versionId="one:v1" returnTo="/workspace/today" onSource={onSource} />);
 expect((await screen.findAllByText(units[0]!.reference.quote)).length).toBeGreaterThan(0);
 expect(screen.queryByText(/Comparison interpretation/)).not.toBeInTheDocument();
});
