import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";

export const taskDefaults = { intent: "answer", requested_parts: "", vehicle_configuration: "", operating_envelope: "", safety_objectives: "", validation_evidence: "" };
const contextLabels = {
  vehicle_configuration: "Vehicle and configuration",
  operating_envelope: "Operating envelope",
  safety_objectives: "Safety objectives",
  validation_evidence: "Validation evidence",
};

export function AssistanceTaskContext({ values, research, busy, change }: {
  values: Record<string, string>; research: boolean; busy: boolean; change: (key: string, value: string) => void;
}) {
  return <fieldset disabled={busy}><legend>Task intent · recorded before generation</legend>
    <label>Task intent<select value={values.intent} onChange={e => change("intent", e.target.value)}>
      <option value="answer">Explain or answer</option>
      {research && <><option value="comparison">Compare sources</option><option value="application_assessment">Assess an application</option></>}
    </select></label>
    {values.intent === "application_assessment" && <>
      <p>Missing required context permits only full abstention. Supplied context is unverified and does not establish safety.</p>
      {Object.entries(contextLabels).map(([key, label]) => <label key={key}>{label}<textarea rows={2} maxLength={1000} value={values[key]} onChange={e => change(key, e.target.value)} /></label>)}
    </>}
    <label>Requested parts · one per line, highest priority first<textarea rows={3} maxLength={32007} value={values.requested_parts ?? ""} onChange={e => change("requested_parts", e.target.value)} /></label>
    <p>Up to eight parts are sealed before generation. Leave blank to record the whole question as one part. Six factual claims maximum: prioritize the question, split independent findings and preserve scope, comparator, metric and conditions. Missing evidence and omitted parts stay visible.</p>
    {values.intent === "comparison" && <p>If the comparison is unanswerable, separately cited source notes may remain. They do not establish the requested comparison.</p>}
  </fieldset>;
}

export function AssistanceDisposition({ output }: { output: AssistanceOutput }) {
  if (output.response_disposition === "full_abstention") return <section aria-label="Full abstention">
    <h4>No assessment or factual answer produced</h4>
    <p>{output.context_requests?.length ? "Provide the missing application details before requesting an assessment." : "The selected evidence does not establish the requested answer."}</p>
    <ul>{output.context_requests?.map(request => <li key={request}>{request}</li>)}</ul>
  </section>;
  if (output.comparison_unanswered) return <section aria-label="Comparison unanswered"><h4>Requested comparison remains unanswered</h4><p>The following are separately cited source notes. They are not a completed comparison.</p></section>;
  return null;
}


export function RequestCoverage({ output, prefix }: { output: AssistanceOutput; prefix: string }) {
  if (!output.request_coverage) return null;
  return <section aria-label="Request coverage"><h4>{output.coverage_complete ? "All requested parts declared answered" : "Request only partially answered or unanswered"}</h4>
    <p>{output.coverage_basis ?? "Declared coverage · machine checks unqualified; human review unmeasured."}</p>
    <ol>{output.request_coverage.map(part => <li key={part.id}><strong>{part.request}</strong><p>{part.status === "answered" ? "Declared answered" : part.status === "lacks_evidence" ? "Lacks evidence" : "Omitted from this response"}{part.status !== "answered" && ` · ${part.gap_text}`}</p>
      {!!part.answer_claim_ids?.length && <p>Answer claims: {part.answer_claim_ids.map(id => <a key={id} href={`#${prefix}-${id}`}>{id} </a>)}</p>}
      {!!part.context_claim_ids?.length && <p>Context only · does not answer this part: {part.context_claim_ids.map(id => <a key={id} href={`#${prefix}-${id}`}>{id} </a>)}</p>}
    </li>)}</ol></section>;
}
