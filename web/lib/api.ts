import type {
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

export async function submitResearch(query: string): Promise<ResearchAccepted> {
  const resp = await fetch(`${API_BASE}/research`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, await safeError(resp));
  }
  return (await resp.json()) as ResearchAccepted;
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
