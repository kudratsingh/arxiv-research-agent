// Typed fetch wrappers over the frozen HTTP surface
// (04-ARCHITECTURE.md §3.1).
//
// Every call funnels through one `request()` so there is exactly one
// place that builds a URL, links abort signals, applies a timeout, and
// converts a failure into an `ApiError` carrying a normalized
// `ApiFailure`.

import {
  ApiError,
  legacyDetailMessage,
  normalizeFailure,
  readErrorBody,
} from "./errors";
import type {
  ConversationDetail,
  ConversationListItem,
  JobDetail,
  ResearchAccepted,
  ResearchSubmitOptions,
  ReviewRequest,
  ReviewResponse,
} from "./models";

// Browser calls stay same-origin. The Next.js route handler at /api
// forwards them to FastAPI and injects the server-only API key, which
// keeps credentials out of the client bundle and lets native
// EventSource/export links use the authenticated path too.
export const API_BASE = "/api";

/**
 * Default ceiling for read calls.
 *
 * Every GET on this surface is an in-memory or Redis lookup
 * (`src/api/routes.py:215-232`, `:560-624`); fifteen seconds is far
 * past a healthy response and short enough that a wedged proxy
 * surfaces as a `timeout` failure rather than a spinner that never
 * resolves.
 */
export const DEFAULT_READ_TIMEOUT_MS = 15_000;

export interface RequestOptions {
  /** Caller cancellation. Composed with the timeout, never replaced. */
  signal?: AbortSignal;
  /** Override the default ceiling; `null` disables it entirely. */
  timeoutMs?: number | null;
}

// ---------------------------------------------------------------------------
// The one request path.
// ---------------------------------------------------------------------------

interface LinkedAbort {
  signal: AbortSignal;
  state: { timedOut: boolean; cancelled: boolean };
  dispose: () => void;
}

/**
 * Compose the caller's signal with a timeout into one signal.
 *
 * Written by hand rather than with `AbortSignal.any()` /
 * `AbortSignal.timeout()` because those are not present in every
 * runtime this bundle targets (notably the jsdom test environment),
 * and because the `state` flags are what let the normalizer tell a
 * timeout apart from a cancellation — both arrive as the same
 * `AbortError`.
 */
function linkAbort(
  callerSignal: AbortSignal | undefined,
  timeoutMs: number | null
): LinkedAbort {
  const controller = new AbortController();
  const state = { timedOut: false, cancelled: false };
  let timer: ReturnType<typeof setTimeout> | undefined;

  const onCallerAbort = (): void => {
    state.cancelled = true;
    controller.abort();
  };

  if (callerSignal !== undefined) {
    if (callerSignal.aborted) {
      state.cancelled = true;
      controller.abort();
    } else {
      callerSignal.addEventListener("abort", onCallerAbort, { once: true });
    }
  }

  if (timeoutMs !== null && timeoutMs > 0 && !controller.signal.aborted) {
    timer = setTimeout(() => {
      state.timedOut = true;
      controller.abort();
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    state,
    dispose: () => {
      if (timer !== undefined) clearTimeout(timer);
      callerSignal?.removeEventListener("abort", onCallerAbort);
    },
  };
}

function abortError(): Error {
  const err = new Error("The operation was aborted.");
  err.name = "AbortError";
  return err;
}

async function request(
  path: string,
  init: RequestInit,
  options: RequestOptions | undefined,
  defaultTimeoutMs: number | null
): Promise<Response> {
  const timeoutMs = options?.timeoutMs ?? defaultTimeoutMs;
  const link = linkAbort(options?.signal, timeoutMs ?? null);
  try {
    // A caller that already cancelled gets no request at all.
    if (link.signal.aborted) throw abortError();

    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: link.signal,
    });
    if (!response.ok) {
      const body = await readErrorBody(response);
      throw new ApiError(
        response.status,
        legacyDetailMessage(response, body),
        await normalizeFailure(response, { body })
      );
    }
    return response;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const failure = await normalizeFailure(err, {
      timedOut: link.state.timedOut,
      cancelled: link.state.cancelled,
    });
    // `status: 0` — there was no response. The message stays the
    // thrown error's own so M0 does not change what existing UI
    // renders; `failure.message` is the user-facing sentence.
    throw new ApiError(0, transportMessage(err, failure.message), failure);
  } finally {
    link.dispose();
  }
}

function transportMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message !== "" ? err.message : fallback;
}

const JSON_HEADERS = { "content-type": "application/json" } as const;

async function json<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Research.
// ---------------------------------------------------------------------------

/**
 * Submit a query. **Non-idempotent and potentially billable**, and the
 * API has no idempotency key (`src/api/routes.py:179-197`): never
 * retry this automatically.
 *
 * No default timeout, deliberately. Aborting the HTTP request does not
 * cancel the job the server already created, so a client-side ceiling
 * here would only hide a run the user is still paying for. A caller
 * may still pass its own `signal` or `timeoutMs`.
 */
export async function submitResearch(
  query: string,
  options: ResearchSubmitOptions = {},
  request_?: RequestOptions
): Promise<ResearchAccepted> {
  const body: Record<string, unknown> = { query };
  if (options.conversation_id) body.conversation_id = options.conversation_id;
  if (options.hitl_bypass) body.hitl_bypass = options.hitl_bypass;
  const resp = await request(
    "/research",
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) },
    request_,
    null
  );
  return json<ResearchAccepted>(resp);
}

export async function getJob(
  jobId: string,
  options?: RequestOptions
): Promise<JobDetail> {
  const resp = await request(
    `/research/${encodeURIComponent(jobId)}`,
    {},
    options,
    DEFAULT_READ_TIMEOUT_MS
  );
  return json<JobDetail>(resp);
}

/**
 * Resolve the review pause. `action: "approve"` resumes billable work,
 * so this shares `submitResearch`'s no-default-timeout rule.
 */
export async function reviewPlan(
  jobId: string,
  body: ReviewRequest,
  options?: RequestOptions
): Promise<ReviewResponse> {
  const resp = await request(
    `/research/${encodeURIComponent(jobId)}/review`,
    { method: "POST", headers: JSON_HEADERS, body: JSON.stringify(body) },
    options,
    null
  );
  return json<ReviewResponse>(resp);
}

/**
 * URL for the SSE stream. A plain string because the browser's native
 * `EventSource` opens it, not `fetch` — see `web/lib/api/events.ts`
 * for the frames it carries.
 */
export function streamUrl(jobId: string): string {
  return `${API_BASE}/research/${encodeURIComponent(jobId)}/stream`;
}

// ---------------------------------------------------------------------------
// Conversations (ADR 0032).
// ---------------------------------------------------------------------------

/**
 * Create a conversation.
 *
 * Shares `POST /research`'s rate-limit bucket (`routes.py:157` and
 * `routes.py:545`), so the landing-page flow costs two of
 * `api_key_hourly_limit` — which is why this is a write with no
 * default timeout rather than a read.
 */
export async function createConversation(
  title?: string,
  options?: RequestOptions
): Promise<ConversationDetail> {
  const resp = await request(
    "/conversations",
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(title ? { title } : {}),
    },
    options,
    null
  );
  return json<ConversationDetail>(resp);
}

/**
 * List conversations. The endpoint accepts `limit` / `offset`
 * (`routes.py:568-579`) and returns a bare array with no `total`;
 * neither parameter is sent today, and adding one is a behaviour
 * change that belongs to the surface work order, not to M0.
 */
export async function listConversations(
  options?: RequestOptions
): Promise<ConversationListItem[]> {
  const resp = await request(
    "/conversations",
    {},
    options,
    DEFAULT_READ_TIMEOUT_MS
  );
  return json<ConversationListItem[]>(resp);
}

export async function getConversation(
  conversationId: string,
  options?: RequestOptions
): Promise<ConversationDetail> {
  const resp = await request(
    `/conversations/${encodeURIComponent(conversationId)}`,
    {},
    options,
    DEFAULT_READ_TIMEOUT_MS
  );
  return json<ConversationDetail>(resp);
}

export async function deleteConversation(
  conversationId: string,
  options?: RequestOptions
): Promise<void> {
  await request(
    `/conversations/${encodeURIComponent(conversationId)}`,
    { method: "DELETE" },
    options,
    null
  );
}
