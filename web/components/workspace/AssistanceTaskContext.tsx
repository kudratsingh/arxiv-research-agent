import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";

export const taskDefaults = { intent: "answer", vehicle_configuration: "", operating_envelope: "", safety_objectives: "", validation_evidence: "" };
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
