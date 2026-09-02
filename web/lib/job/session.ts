import type { JobDetail, SessionDetail } from "@/lib/api";

/**
 * Adapt the learning snapshot to the lifecycle fields the shared machine
 * consumes. Session-only fields stay on the original `SessionDetail`; this
 * projection exists solely so transport, reconnect, and terminal handling do
 * not grow a second ad-hoc state machine.
 */
export function sessionAsJobDetail(session: SessionDetail): JobDetail {
  return {
    job_id: session.session_id,
    status: session.status,
    kind: "session",
    query: session.title,
    created_at: session.created_at,
    started_at: session.started_at,
    completed_at: session.completed_at,
    elapsed_sec: session.elapsed_sec,
    result: session.result,
    error: session.error,
    error_type: session.error_type,
    cost_usd: session.cost_usd,
    llm_calls: session.llm_calls,
    iterations: null,
    quality_score: null,
    plan: null,
    conversation_id: null,
  };
}
