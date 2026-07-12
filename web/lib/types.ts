// Types mirroring the FastAPI schemas from src/api/schemas.py.
//
// Hand-written rather than generated from OpenAPI so the client
// surface stays legible in review. If the schemas drift, contract
// tests on the Python side (tests/test_api_routes.py) catch the
// producer end; a follow-up can auto-generate this file from
// /openapi.json if drift becomes a real problem.

export type JobStatus =
  | "pending"
  | "running"
  | "pending_review"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Plan {
  sub_questions: string[];
  search_queries: string[];
}

export type ReviewAction = "approve" | "revise" | "cancel";

export interface ReviewRequest {
  action: ReviewAction;
  plan?: Plan;
}

export interface ReviewResponse {
  job_id: string;
  status: string;
  action: string;
}

export interface ResearchAccepted {
  job_id: string;
  status: string;
  status_url: string;
  stream_url: string;
}

export interface JobDetail {
  job_id: string;
  status: JobStatus;
  query: string;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  elapsed_sec: number | null;
  result: string | null;
  error: string | null;
  error_type: string | null;
  cost_usd: number | null;
  llm_calls: number | null;
  iterations: number | null;
  quality_score: number | null;
  plan: Plan | null;
  conversation_id: string | null;
}

// ---------------------------------------------------------------------------
// Conversation types (Sprint 5 PR 4, ADR 0032).
// ---------------------------------------------------------------------------

export interface ConversationListItem {
  conversation_id: string;
  title: string;
  created_at: number;
  updated_at: number;
}

export interface ConversationJobSummary {
  job_id: string;
  ordinal: number;
  query: string;
  report: string;
  created_at: number;
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  created_at: number;
  updated_at: number;
  jobs: ConversationJobSummary[];
}

export type SseEventName =
  | "job_started"
  | "node_completed"
  | "plan_ready"
  | "job_completed"
  | "job_failed"
  | "job_cancelled"
  | "stream_note"
  | "error";

export interface SseEvent {
  name: SseEventName;
  data: Record<string, unknown> | null;
  receivedAt: number;
}

export const TERMINAL_EVENTS: ReadonlySet<SseEventName> = new Set<SseEventName>(
  ["job_completed", "job_failed", "job_cancelled"]
);
