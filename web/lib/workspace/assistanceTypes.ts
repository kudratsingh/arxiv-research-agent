import type { FakeJob, FakeRequestPreview, ResumeContext } from "./api";

export interface EvidenceReference {
  work_id: string; version_id: string; material_id: string; span_id: string;
  source_hash: string; parser_revision: string;
  scope: "metadata" | "abstract" | "excerpt" | "full_text";
  page: number | null; start: number; end: number; quote: string;
}
export interface EvidenceUnit { id: string; title: string; reference: EvidenceReference; material_hash: string; warnings: string[]; complete: boolean }
export interface AssistanceInput {
  mode: "learn" | "research"; work_id: string; version_id: string;
  material_ids: string[]; span_ids: string[]; unit_ids: string[];
  depth: "overview" | "technical"; background: string;
  direction: "overview" | "method" | "assumptions" | "implementation";
  follow_up: string; project_id: string | null; project_revision: number | null;
  parent_job: string | null; origin: ResumeContext | null;
  task_context?: { intent: "answer" | "comparison" | "application_assessment"; application_context: Record<string, string> } | null;
}
export interface AssistanceOutput {
  claims: { claim_id: string; text: string; handles: string[]; required_scope: string }[];
  background?: string; comparison?: string; comparison_basis?: string[];
  background_claims?: string[]; assumption_claims?: string[]; limitation_claims?: string[]; comparison_claims?: string[];
  assumptions?: string[]; gaps: string[]; questions: string[];
  proposal: string; abstention: string | null;
  response_disposition?: "answer" | "full_abstention" | "comparison_abstention";
  context_requests?: string[]; comparison_unanswered?: boolean;
}
export type AssistanceJob = Omit<FakeJob, "request"> & {
  request: { assistance: AssistanceInput; units: Record<string, EvidenceReference>; project_context: { question: string; revision: number } | null; [key: string]: unknown };
  assistance_output: AssistanceOutput | null;
  simulated: true; human_review: null;
  quality: { factual_acceptance: false; checker_qualified: false; basis: string; claim_checks?: {claim_id:string;decision:string|null;reason:string}[] };
  wire_records: { phase: string; digest: string; request: unknown; response: unknown }[];
};
export type AssistancePreview = Omit<FakeRequestPreview, "request"> & { request: AssistanceJob["request"] & { capacity: { basis: string; stage_input_bytes_max: Record<string, number>; input_bytes_reserved: number; provider_token_counts: null } } };
export function passageAnchor(reference: EvidenceReference) {
  return reference.page === null ? `${reference.scope}:${reference.start}:${reference.end}`
    : `material:${reference.material_id}:page:${reference.page}:${reference.start}:${reference.end}`;
}
