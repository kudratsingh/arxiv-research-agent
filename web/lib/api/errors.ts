// One error normalization contract — HAND-WRITTEN BY DESIGN.
//
// There is no single backend error envelope, and none of the shapes
// below appear in the OpenAPI document. The observed sources
// (04-ARCHITECTURE.md §3.4, 00-DISCOVERY.md "Error shape"):
//
//   common          {"detail": "job_not_found"}                routes.py:229
//   conflict+state  {"detail": "job_not_awaiting_review (status=running)"}
//                                                              routes.py:262-264
//   unauthorized    {"detail": "missing_api_key"} + WWW-Authenticate
//                                                              auth.py:507-516
//   rate limited    {"detail": {"error", "key_id", "limit_per_hour"}}
//                   + Retry-After                              auth.py:176-184
//   validation      {"detail": [{loc, msg, type}, ...]}        FastAPI default
//   proxy           {"detail": "api_proxy_misconfigured"} 503  route.ts:70-74
//                   {"detail": "api_upstream_unavailable"} 502 route.ts:98-101
//   transport       no body at all — network failure, abort, timeout
//
// Everything funnels through the single `normalizeFailure()` below.
//
// `message` is the user-facing sentence. `raw` is the untouched body
// (or thrown value), retained for the diagnostics disclosure and
// NEVER rendered as a primary message — that includes backend
// `error_type` codes, which are disclosure-only by design. The final
// copy for each sentence is WO-12's dictionary; these are the honest
// defaults it will replace.

// ---------------------------------------------------------------------------
// The union.
// ---------------------------------------------------------------------------

/** One field-level problem out of a 422 body. */
export interface FieldIssue {
  /** Dotted path with FastAPI's `body`/`query` prefix removed. */
  path: string;
  /** The backend's `msg`. */
  message: string;
  /** The backend's `type` discriminator, e.g. `string_too_long`. */
  type?: string;
}

/** Carried by every variant, without exception. */
export interface FailureCommon {
  /** The user-facing sentence. Safe to render as the primary message. */
  message: string;
  /** The untouched body or thrown value. Disclosure only. */
  raw: unknown;
  /**
   * Correlation id, when the response carried one.
   *
   * Optional because the Next.js proxy's response allowlist
   * (`web/app/api/[...path]/route.ts:18-25`) does not forward a
   * request-id header today. Reading it here costs nothing and means
   * the client is ready when WO-30's C6 proxy logging adds one.
   */
  requestId?: string;
}

export type ApiFailure =
  | (FailureCommon & { kind: "unauthorized"; status: 401 })
  | (FailureCommon & { kind: "not_found"; status: 404 })
  | (FailureCommon & { kind: "conflict"; status: 409; state?: string })
  | (FailureCommon & {
      kind: "rate_limited";
      status: 429;
      retryAfterSec: number;
      limitPerHour?: number;
    })
  | (FailureCommon & {
      kind: "validation";
      status: 422;
      fields: FieldIssue[];
    })
  | (FailureCommon & { kind: "upstream_unavailable"; status: 502 })
  | (FailureCommon & { kind: "proxy_misconfigured"; status: 503 })
  | (FailureCommon & { kind: "server_error"; status: number })
  | (FailureCommon & { kind: "offline" })
  | (FailureCommon & { kind: "timeout" })
  | (FailureCommon & { kind: "cancelled" })
  | (FailureCommon & { kind: "unknown"; status: number | null });

export type ApiFailureKind = ApiFailure["kind"];

/**
 * Every kind the normalizer can produce.
 *
 * Declared as a `Record` keyed by the union so adding a thirteenth
 * variant without listing it here is a compile error, and so the table
 * test can prove it covers all of them.
 */
const KIND_INDEX: Record<ApiFailureKind, true> = {
  unauthorized: true,
  not_found: true,
  conflict: true,
  rate_limited: true,
  validation: true,
  upstream_unavailable: true,
  proxy_misconfigured: true,
  server_error: true,
  offline: true,
  timeout: true,
  cancelled: true,
  unknown: true,
};

export const API_FAILURE_KINDS = Object.keys(KIND_INDEX) as ApiFailureKind[];

// ---------------------------------------------------------------------------
// Default copy. Replaced by WO-12's dictionary; never contains `raw`.
// ---------------------------------------------------------------------------

const COPY = {
  unauthorized:
    "This request was not authorized. The server rejected its credentials.",
  // Ownership mismatches return 404, never 403 (`routes.py:59-84`), so
  // this sentence must never say "deleted" or "no permission".
  not_found: "That item is not available.",
  conflict: "This action is not available in the job's current state.",
  validation: "The request was rejected as invalid.",
  upstream_unavailable:
    "The research service is unreachable right now. Try again shortly.",
  proxy_misconfigured:
    "The API proxy is misconfigured, so requests cannot reach the research service.",
  server_error: "The server could not complete this request.",
  offline: "You appear to be offline. Check your connection and try again.",
  unreachable: "Could not reach the server. Check your connection and try again.",
  timeout: "The request took too long and was stopped.",
  cancelled: "The request was cancelled.",
  unknown: "Something went wrong.",
} as const;

// ---------------------------------------------------------------------------
// Reading a failed response.
// ---------------------------------------------------------------------------

/** A response body read exactly once. */
export interface ErrorBody {
  /** Parsed JSON when the body was JSON, otherwise the raw text. */
  raw: unknown;
  /** Whether the body parsed as JSON. */
  json: boolean;
  /** The body as text, empty when it could not be read. */
  text: string;
}

/**
 * Consume a failed response's body once.
 *
 * Exported so a caller that also needs the legacy `ApiError.message`
 * can pass the result back into `normalizeFailure()` through
 * `context.body` instead of reading the stream twice.
 */
export async function readErrorBody(response: Response): Promise<ErrorBody> {
  let text = "";
  try {
    text = await response.text();
  } catch {
    return { raw: undefined, json: false, text: "" };
  }
  if (text === "") return { raw: undefined, json: false, text };
  try {
    return { raw: JSON.parse(text), json: true, text };
  } catch {
    return { raw: text, json: false, text };
  }
}

export interface NormalizeContext {
  /** Our own timeout controller fired. Wins over a bare AbortError. */
  timedOut?: boolean;
  /** The caller's `AbortSignal` fired. */
  cancelled?: boolean;
  /** Overrides `navigator.onLine`; present so tests stay deterministic. */
  online?: boolean;
  /** A body already read with `readErrorBody()`. */
  body?: ErrorBody;
}

// ---------------------------------------------------------------------------
// The one normalizer.
// ---------------------------------------------------------------------------

/**
 * Turn anything a request can fail with into exactly one `ApiFailure`.
 *
 * Accepts a failed `Response` or a thrown transport value, which is
 * what makes it the single entry point: there is no second code path
 * that can invent a thirteenth error model.
 */
export async function normalizeFailure(
  source: unknown,
  context: NormalizeContext = {}
): Promise<ApiFailure> {
  if (isResponseLike(source)) {
    const body = context.body ?? (await readErrorBody(source));
    return fromResponse(source, body);
  }
  return fromTransport(source, context);
}

function fromResponse(response: Response, body: ErrorBody): ApiFailure {
  const status = response.status;
  const raw = body.raw;
  const requestId = readRequestId(response);
  const base = (message: string): FailureCommon =>
    requestId === undefined ? { message, raw } : { message, raw, requestId };
  const detail = readDetail(raw);

  switch (status) {
    case 401:
      return { ...base(COPY.unauthorized), kind: "unauthorized", status: 401 };
    case 404:
      return { ...base(COPY.not_found), kind: "not_found", status: 404 };
    case 409: {
      // `{"detail": "job_not_awaiting_review (status=running)"}`.
      const state =
        typeof detail === "string"
          ? (/\(status=([^)]+)\)/.exec(detail)?.[1] ?? undefined)
          : undefined;
      const message =
        state === undefined
          ? COPY.conflict
          : `This action is not available while the job is ${state}.`;
      return state === undefined
        ? { ...base(message), kind: "conflict", status: 409 }
        : { ...base(message), kind: "conflict", status: 409, state };
    }
    case 422: {
      const fields = readFieldIssues(detail);
      return {
        ...base(validationMessage(fields)),
        kind: "validation",
        status: 422,
        fields,
      };
    }
    case 429: {
      const retryAfterSec = readRetryAfter(response);
      const limitPerHour = readLimitPerHour(detail);
      const message = rateLimitMessage(retryAfterSec, limitPerHour);
      return limitPerHour === undefined
        ? { ...base(message), kind: "rate_limited", status: 429, retryAfterSec }
        : {
            ...base(message),
            kind: "rate_limited",
            status: 429,
            retryAfterSec,
            limitPerHour,
          };
    }
    case 502:
      return {
        ...base(COPY.upstream_unavailable),
        kind: "upstream_unavailable",
        status: 502,
      };
    case 503:
      return {
        ...base(COPY.proxy_misconfigured),
        kind: "proxy_misconfigured",
        status: 503,
      };
    default:
      if (status >= 500) {
        return { ...base(COPY.server_error), kind: "server_error", status };
      }
      return {
        ...base(`${COPY.unknown} (HTTP ${status})`),
        kind: "unknown",
        status,
      };
  }
}

function fromTransport(source: unknown, context: NormalizeContext): ApiFailure {
  const name = errorName(source);

  // Our timeout aborts through the same controller as a caller
  // cancellation, so the flag has to win over the AbortError name.
  if (context.timedOut === true || name === "TimeoutError") {
    return { message: COPY.timeout, raw: source, kind: "timeout" };
  }
  if (context.cancelled === true || name === "AbortError") {
    return { message: COPY.cancelled, raw: source, kind: "cancelled" };
  }
  if (source instanceof TypeError) {
    // `fetch` rejects with a TypeError when the request never reached
    // the server. The union has one kind for that; the sentence tells
    // the two situations apart.
    const online = context.online ?? readOnline();
    return {
      message: online ? COPY.unreachable : COPY.offline,
      raw: source,
      kind: "offline",
    };
  }
  return { message: COPY.unknown, raw: source, kind: "unknown", status: null };
}

// ---------------------------------------------------------------------------
// The legacy error class (M0 compatibility; deleted with the shims in M4).
// ---------------------------------------------------------------------------

/**
 * The thrown error, unchanged in shape from `web/lib/api.ts:16-24`.
 *
 * `message` is deliberately still the **legacy** string — the raw
 * `detail`, or `JSON.stringify(body)`, or `HTTP <status> <statusText>`
 * — because the 78 existing tests assert on it and M0 must be
 * behaviour-neutral. New code reads `failure.message` instead, which
 * is the user-facing sentence that never contains `raw`. The legacy
 * channel disappears when M4 deletes the shims.
 */
export class ApiError extends Error {
  public readonly status: number;

  /** The normalized failure. Always present. */
  public readonly failure: ApiFailure;

  constructor(status: number, message: string, failure?: ApiFailure) {
    super(message);
    this.status = status;
    this.name = "ApiError";
    this.failure = failure ?? {
      message: COPY.unknown,
      raw: message,
      kind: "unknown",
      status: status === 0 ? null : status,
    };
  }
}

/**
 * The pre-normalization message string, reproduced exactly.
 *
 * Mirrors the superseded `safeError()` at `web/lib/api.ts:129-137`.
 */
export function legacyDetailMessage(
  response: Response,
  body: ErrorBody
): string {
  if (!body.json) return `HTTP ${response.status} ${response.statusText}`;
  const detail = readDetail(body.raw);
  if (typeof detail === "string") return detail;
  return JSON.stringify(body.raw);
}

// ---------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Duck-typed rather than `instanceof Response` so a response built in
 * another realm (jsdom, a test double, an undici polyfill) is still
 * recognized.
 */
function isResponseLike(value: unknown): value is Response {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Response).status === "number" &&
    typeof (value as Response).text === "function" &&
    "headers" in value
  );
}

function readDetail(raw: unknown): unknown {
  return isRecord(raw) ? raw.detail : undefined;
}

function errorName(source: unknown): string | undefined {
  return isRecord(source) && typeof source.name === "string"
    ? source.name
    : source instanceof Error
      ? source.name
      : undefined;
}

function readOnline(): boolean {
  return typeof navigator === "undefined" ? true : navigator.onLine !== false;
}

function readRequestId(response: Response): string | undefined {
  const headers = response.headers;
  if (typeof headers?.get !== "function") return undefined;
  return (
    headers.get("x-request-id") ?? headers.get("x-correlation-id") ?? undefined
  );
}

/** `Retry-After` in seconds; the header is forwarded by the proxy. */
function readRetryAfter(response: Response): number {
  const header =
    typeof response.headers?.get === "function"
      ? response.headers.get("retry-after")
      : null;
  const parsed = header === null ? Number.NaN : Number.parseInt(header, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : DEFAULT_RETRY_AFTER_SEC;
}

const DEFAULT_RETRY_AFTER_SEC = 60;

function readLimitPerHour(detail: unknown): number | undefined {
  if (!isRecord(detail)) return undefined;
  const limit = detail.limit_per_hour;
  return typeof limit === "number" ? limit : undefined;
}

function rateLimitMessage(
  retryAfterSec: number,
  limitPerHour: number | undefined
): string {
  const wait =
    retryAfterSec >= 60
      ? `${Math.ceil(retryAfterSec / 60)} minute${Math.ceil(retryAfterSec / 60) === 1 ? "" : "s"}`
      : `${retryAfterSec} second${retryAfterSec === 1 ? "" : "s"}`;
  const ceiling =
    limitPerHour === undefined
      ? ""
      : ` This key allows ${limitPerHour} request${limitPerHour === 1 ? "" : "s"} per hour.`;
  return `Rate limit reached. Try again in about ${wait}.${ceiling}`;
}

function readFieldIssues(detail: unknown): FieldIssue[] {
  if (!Array.isArray(detail)) return [];
  const issues: FieldIssue[] = [];
  for (const entry of detail) {
    if (!isRecord(entry)) continue;
    const loc = Array.isArray(entry.loc) ? entry.loc : [];
    // Drop FastAPI's `body` / `query` container prefix.
    const segments = loc.length > 1 ? loc.slice(1) : loc;
    const message = typeof entry.msg === "string" ? entry.msg : "is invalid";
    const type = typeof entry.type === "string" ? entry.type : undefined;
    const path = segments.map(String).join(".");
    issues.push(type === undefined ? { path, message } : { path, message, type });
  }
  return issues;
}

function validationMessage(fields: FieldIssue[]): string {
  const first = fields[0];
  if (first === undefined) return COPY.validation;
  if (fields.length === 1) {
    return first.path === ""
      ? `${COPY.validation} ${capitalize(first.message)}.`
      : `${first.path}: ${first.message}.`;
  }
  return `${fields.length} fields need attention: ${fields
    .map((field) => field.path)
    .join(", ")}.`;
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
