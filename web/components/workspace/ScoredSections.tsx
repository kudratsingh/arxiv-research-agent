import type { AssistanceOutput } from "@/lib/workspace/assistanceTypes";
import { useEffect } from "react";
import { settleReaderTarget } from "@/lib/workspace/navigation";

/** Sections reference the same scored claim and citation; never new factual prose. */
export function ScoredSections({ output, prefix }: { output: AssistanceOutput; prefix: string }) {
  useEffect(() => {
    const target = location.hash.slice(1);
    if (!output.claims.some(c => `${prefix}-${c.claim_id}` === target)) return;
    const element = document.getElementById(target);
    if (element) settleReaderTarget(element);
  }, [output, prefix]);
  const sections = [
    ["Background", output.background_claims],
    ["Assumptions", output.assumption_claims],
    ["Limitations", output.limitation_claims],
    ["Comparison", output.comparison_claims],
  ] as const;
  return <>{sections.map(([label, ids]) => ids && ids.length > 0 && <section key={label} aria-label={`${label} claim references`}>
    <h4>{label} · scored claims</h4>
    <ul>{ids.map(id => { const claim = output.claims.find(c => c.claim_id === id); return <li key={id}><a href={`#${prefix}-${id}`}>{id}: {claim?.text ?? "Claim unavailable; inspect the stored result."}</a></li>; })}</ul>
  </section>)}<h4>Missing evidence · next checks</h4><ul>{output.gaps.map((text, i) => <li key={i}>{text}</li>)}</ul></>;
}
