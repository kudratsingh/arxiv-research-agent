import type {
  ConversationDetail,
  ConversationListItem,
  JobDetail,
  ResearchAccepted,
  ReviewRequest,
  ReviewResponse,
} from "./types";

// Base URL for the FastAPI service. In compose the browser hits it
// via the host-published port; NEXT_PUBLIC_API_BASE ships with the
// client bundle so it's readable from `use client` code.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  public readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export interface ResearchSubmitOptions {
  conversation_id?: string;
  hitl_bypass?: boolean;
}

export async function submitResearch(
  query: string,
  options: ResearchSubmitOptions = {}
): Promise<ResearchAccepted> {
  const body: Record<string, unknown> = { query };
  if (options.conversation_id) body.conversation_id = options.conversation_id;
  if (options.hitl_bypass) body.hitl_bypass = options.hitl_bypass;
  const resp = await fetch(`${API_BASE}/research`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ResearchAccepted;
}

// ---------------------------------------------------------------------------
// Conversation endpoints (ADR 0032).
// ---------------------------------------------------------------------------

export async function createConversation(
  title?: string
): Promise<ConversationDetail> {
  const resp = await fetch(`${API_BASE}/conversations`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(title ? { title } : {}),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ConversationDetail;
}

export async function listConversations(): Promise<ConversationListItem[]> {
  const resp = await fetch(`${API_BASE}/conversations`);
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ConversationListItem[];
}

export async function getConversation(
  conversationId: string
): Promise<ConversationDetail> {
  const resp = await fetch(
    `${API_BASE}/conversations/${encodeURIComponent(conversationId)}`
  );
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ConversationDetail;
}

export async function deleteConversation(
  conversationId: string
): Promise<void> {
  const resp = await fetch(
    `${API_BASE}/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" }
  );
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const resp = await fetch(`${API_BASE}/research/${encodeURIComponent(jobId)}`);
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as JobDetail;
}

export function streamUrl(jobId: string): string {
  return `${API_BASE}/research/${encodeURIComponent(jobId)}/stream`;
}

export async function reviewPlan(
  jobId: string,
  body: ReviewRequest
): Promise<ReviewResponse> {
  const resp = await fetch(
    `${API_BASE}/research/${encodeURIComponent(jobId)}/review`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }
  );
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ReviewResponse;
}

async function safeError(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body);
  } catch {
    return `HTTP ${resp.status} ${resp.statusText}`;
  }
}
