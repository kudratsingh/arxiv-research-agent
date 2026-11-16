import type { AssistanceOutput, EvidenceReference } from "@/lib/workspace/assistanceTypes";

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
  const rows = output.request_coverage.map(part => {
    const gaps = [...new Set((part.gap_texts ?? (part.status === "answered" ? [] : [part.gap_text])).filter(Boolean))];
    const inconsistent = part.status === "answered" && (gaps.length > 0 || output.response_disposition === "full_abstention" || (output.comparison_unanswered && part.kind === "comparison"));
    const label = inconsistent ? "Coverage status inconsistent" : part.status === "answered" ? "Declared answered" : part.status === "partial" ? "Partially answered · remaining gaps" : part.status === "lacks_evidence" ? "Lacks evidence" : part.status === "omitted" ? "Omitted from this response" : "Coverage status unavailable";
    return { part, gaps, label, inconsistent };
  });
  const complete = output.coverage_complete && rows.every(({ part, inconsistent }) => part.status === "answered" && !inconsistent);
  return <section aria-label="Request coverage"><h4>{complete ? "All requested parts declared answered" : "Request only partially answered or unanswered"}</h4>
    <p>{output.coverage_basis ?? "Declared coverage · machine checks unqualified; human review unmeasured."}</p>
    <ol>{rows.map(({ part, gaps, label }) => <li key={part.id}><strong>{part.request}</strong><p>{label}{gaps.map(text => ` · ${text}`)}</p>
      {output.response_disposition !== "full_abstention" && !!part.answer_claim_ids?.length && <p>Answer claims: {part.answer_claim_ids.map(id => <a key={id} href={`#${prefix}-${id}`}>{id} </a>)}</p>}
      {output.response_disposition !== "full_abstention" && !!part.context_claim_ids?.length && <p>Context only · does not answer this part: {part.context_claim_ids.map(id => <a key={id} href={`#${prefix}-${id}`}>{id} </a>)}</p>}
    </li>)}</ol></section>;
}

/** Preserve the complete declared coverage and disposition in saved notes. */
export function coverageNote(output: AssistanceOutput): string[] {
  if (!output.request_coverage && !output.response_disposition && output.comparison_unanswered === undefined) return [];
  return ["Declared coverage and disposition (not independently verified):\n" + JSON.stringify({
    response_disposition: output.response_disposition,
    comparison_unanswered: output.comparison_unanswered,
    coverage_complete: output.coverage_complete,
    coverage_basis: output.coverage_basis,
    request_coverage: output.request_coverage,
  })];
}

/** Export only the retained result and exact source references, not request or wire records. */
export function downloadAssistanceResult(id: string, simulated: boolean, output: AssistanceOutput, units: Record<string, EvidenceReference>) {
  const data = { job_id: id, basis: simulated ? "Offline simulation; quality unqualified" : "Quarantined experimental result; human review pending", assistance_output: output, source_references: units };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = `${id}-result.json`; document.body.appendChild(link); link.click(); link.remove();
  URL.revokeObjectURL(url);
}
