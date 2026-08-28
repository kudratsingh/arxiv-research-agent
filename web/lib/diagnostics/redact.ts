// "Copy diagnostics" — the redactor (WO-16 c6, 04 §9.2 item 1).
//
// "A 'Copy diagnostics' control in the failure disclosure produces a
// redacted JSON blob: no report text, no question text, no headers, no URLs
// beyond the path template."
//
// THE SHAPE OF THE GUARANTEE. Three of those four are properties of a KEY
// (`query`, `report`, `headers`) and one is a property of a VALUE (a URL
// can appear inside any string, including the backend's own error text). A
// key deny-list alone therefore cannot make the claim, and neither can a
// value scrub. Both run, in this order, on every value in the blob:
//
//   1. **Key deny-list.** A key that names user text, a document, a header
//      or a credential is replaced wholesale. Substring matching, so
//      `report`, `partial_report` and `reportUrl` are all covered.
//   2. **URL rewriting.** Every absolute URL and every `/api` or `/c` path
//      in a surviving string becomes its PATH TEMPLATE: origin dropped,
//      query dropped, fragment dropped, and every segment outside the
//      frozen API's own vocabulary replaced with `{id}`. The allow-list is
//      the mechanism — a length or shape heuristic would template
//      `conversations` and keep a 12-character run id.
//   3. **Credential shapes.** `Authorization: Bearer …` is three words and
//      would survive a prose heuristic, so it is matched directly.
//   4. **Prose.** Anything left that reads like sentences — over
//      `MAX_PROSE_WORDS` words or over `MAX_VALUE_CHARS` characters — is
//      dropped, because report and question text arriving under a key
//      nobody predicted is exactly the leak this control would otherwise
//      ship. The named evidence keys (`error`, `error_type`) are exempt
//      from the WORD test and truncated instead, because
//      `DIAGNOSTICS.copyNote` promises the raw error strings and RC-16
//      forbids editing them.
//
// The walk is ONE LEVEL DEEP and no deeper. That level is `state_delta`,
// whose keys are what an incident report is actually about; every inner
// value takes the same four steps. Arrays and anything nested further are
// replaced rather than walked, so the output has no unbounded shape and
// there is no recursion to reason about.
//
// LOADED ON DEMAND. `Diagnostics.tsx` imports this module inside its click
// handler, so the redactor is not in a route's first-load JS and a reader
// who never presses the button never downloads it (04 §8.1).

import { RING_CAPACITY } from "./constants";
import type { DiagnosticRecord } from "./ring";

/** What replaces a value that may not leave the browser. */
export const REDACTED = "[redacted]";

/** The placeholder every non-vocabulary path segment collapses to. */
export const PATH_ID = "{id}";

/** Longer than this and a surviving string is truncated. */
export const MAX_VALUE_CHARS = 200;

/** More words than this and a non-evidence string is dropped entirely. */
export const MAX_PROSE_WORDS = 12;

/** Appended to a truncated evidence string, so truncation is visible. */
export const TRUNCATED = "…[truncated]";

/**
 * The frozen API's own path vocabulary (`src/api/routes.py`), plus the two
 * client route segments.
 *
 * An ALLOW-list, not a deny-list: everything not named here is an
 * identifier and is templated. That is the only direction that is safe as
 * the API grows — a new endpoint appears as `{id}` in a report, which is
 * confusing; a new id shape appearing verbatim is a leak.
 */
export const PATH_SEGMENT_VOCABULARY: ReadonlySet<string> = new Set([
  "api",
  "research",
  "conversations",
  "stream",
  "review",
  "export",
  "cancel",
  "report",
  "healthz",
  "readyz",
  "c",
]);

/**
 * Keys whose VALUE never leaves the browser, matched as a substring.
 *
 * Four groups, in the order 04 §9.2 names them: the user's own words, the
 * documents this product produces, transport headers, and credentials. The
 * last group is belt-and-braces — the API key never enters the client
 * bundle at all (`app/api/[...path]/route.ts`) — and stays because a
 * deny-list that only covers what is reachable today is a deny-list that
 * decays.
 */
export const REDACTED_KEY_PARTS: readonly string[] = [
  // The user's words.
  "query",
  "question",
  "prompt",
  "sub_question",
  "subquestion",
  // The documents.
  "report",
  "result",
  "content",
  "markdown",
  "answer",
  "summary",
  "abstract",
  "title",
  "text",
  "body",
  "plan",
  // Transport.
  "header",
  "cookie",
  "referer",
  "referrer",
  "user-agent",
  "useragent",
  // Credentials.
  "authorization",
  "api_key",
  "apikey",
  "secret",
  "password",
  "credential",
  "session",
  "email",
];

/**
 * Keys whose value is the evidence the operator is copying this blob FOR.
 *
 * RC-16: "the raw string always remains one disclosure away… because it is
 * what a user pastes into an issue." These are still URL-scrubbed, still
 * credential-scanned and still truncated; they are exempt only from the
 * prose word count, which a real traceback would otherwise trip.
 */
export const EVIDENCE_KEY_PARTS: readonly string[] = [
  "error",
  "reason",
  "message",
  "shape",
];

/** Credential shapes that are short enough to pass every other test. */
const CREDENTIAL_VALUE =
  /\bbearer\s+\S|\bauthorization\s*[:=]|\bx-api-key\b|\bapi[_-]?key\s*[:=]|\bsk-[A-Za-z0-9_-]{8,}/i;

/**
 * Absolute URLs, any scheme, and absolute paths into this product's own
 * surfaces.
 *
 * BRACES ARE INSIDE THE CHARACTER CLASS ON PURPOSE, and that is the one
 * subtle thing in this file. `scrubUrls` runs both patterns in sequence, so
 * the second one re-matches what the first one already rewrote. Excluding
 * `{` and `}` would make it stop mid-placeholder and template the fragment
 * again — `/api/research/{id}/stream` would come out as
 * `/api/research/{id}}/stream`. Allowing them makes `pathTemplate`
 * idempotent instead: `{id}` is not in the vocabulary, so it maps to
 * `{id}`, and running the scrub twice changes nothing.
 */
const ABSOLUTE_URL = /\b[a-z][a-z0-9+.-]*:\/\/[^\s"'<>)\]]+/gi;

const ABSOLUTE_PATH = /\/(?:api|c)\/[^\s"'<>)\]]*/g;

function matchesKey(key: string, parts: readonly string[]): boolean {
  const lower = key.toLowerCase();
  return parts.some((part) => lower.includes(part));
}

// ---------------------------------------------------------------------------
// URLs -> path templates.
// ---------------------------------------------------------------------------

/**
 * A URL or path, reduced to its path template.
 *
 * `https://api.example.internal/api/research/9f3a…/stream?key=abc`
 * becomes `/api/research/{id}/stream`. The origin is dropped because it
 * names a deployment, the query is dropped because it is where credentials
 * hide, and every segment the API does not itself use becomes `{id}`.
 *
 * A string that is not a URL and not an absolute path comes back unchanged,
 * so this is safe to run over ordinary text.
 */
export function pathTemplate(input: string): string {
  let path = input;

  const schemeAt = path.indexOf("://");
  if (schemeAt !== -1) {
    const afterHost = path.indexOf("/", schemeAt + 3);
    path = afterHost === -1 ? "/" : path.slice(afterHost);
  }
  if (!path.startsWith("/")) return input;

  const cut = Math.min(
    ...[path.indexOf("?"), path.indexOf("#")].filter((index) => index !== -1),
    path.length,
  );
  path = path.slice(0, cut);

  const segments = path.split("/").map((segment, index) => {
    if (index === 0) return segment; // The empty string before the leading "/".
    if (segment === "") return segment;
    return PATH_SEGMENT_VOCABULARY.has(segment.toLowerCase()) ? segment : PATH_ID;
  });

  return segments.join("/");
}

/** Rewrite every URL and product path inside a string to its template. */
export function scrubUrls(value: string): string {
  return value
    .replace(ABSOLUTE_URL, (match) => pathTemplate(match))
    .replace(ABSOLUTE_PATH, (match) => pathTemplate(match));
}

// ---------------------------------------------------------------------------
// Values.
// ---------------------------------------------------------------------------

function truncate(value: string): string {
  return value.length <= MAX_VALUE_CHARS
    ? value
    : `${value.slice(0, MAX_VALUE_CHARS)}${TRUNCATED}`;
}

function wordCount(value: string): number {
  const trimmed = value.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
}

/** A string that survived the key test, put through steps 2 to 4. */
export function redactString(value: string, evidence: boolean): string {
  const scrubbed = scrubUrls(value);
  if (CREDENTIAL_VALUE.test(scrubbed)) return REDACTED;
  if (evidence) return truncate(scrubbed);
  if (wordCount(scrubbed) > MAX_PROSE_WORDS) return REDACTED;
  if (scrubbed.length > MAX_VALUE_CHARS) return REDACTED;
  return scrubbed;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * One value of a `detail` map, under the key it arrived with.
 *
 * `depth` bounds the walk at ONE level. That level exists for exactly one
 * payload and it is the important one: `state_delta` is a nested object
 * (`runner.py:947-951`) whose keys are the thing an incident report is
 * about, and collapsing it to `[redacted]` would leave the blob technically
 * safe and practically useless. Every inner value goes through the same key
 * deny-list and the same string rules, so `headers: { authorization: … }`
 * is still caught — by its OWN key, before the walk starts. Anything
 * nested deeper than one level is replaced rather than walked, so there is
 * no recursion and no payload of unbounded shape in the output.
 *
 * Arrays are replaced at every depth: an array has no keys, so the key
 * deny-list has nothing to work with.
 */
export function redactValue(key: string, value: unknown, depth = 0): unknown {
  if (matchesKey(key, REDACTED_KEY_PARTS)) return REDACTED;
  if (value === null) return null;
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") {
    return redactString(value, matchesKey(key, EVIDENCE_KEY_PARTS));
  }
  if (depth === 0 && isPlainObject(value)) {
    const nested: Record<string, unknown> = {};
    for (const [innerKey, innerValue] of Object.entries(value)) {
      nested[innerKey] = redactValue(innerKey, innerValue, depth + 1);
    }
    return nested;
  }
  // Arrays, functions, symbols, undefined, and anything deeper than one
  // level. Not walked; replaced.
  return REDACTED;
}

/** A whole `detail` map, key by key. Unknown keys are kept, by name. */
export function redactDetail(
  detail: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (detail === null) return null;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(detail)) {
    out[key] = redactValue(key, value);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Records and the blob.
// ---------------------------------------------------------------------------

/** A record that is safe to put on the clipboard. Same shape, scrubbed. */
export type RedactedRecord = DiagnosticRecord;

/**
 * One record, redacted.
 *
 * `jobId` survives on purpose. 04 §9.2 names it as a field of the record,
 * and it is the correlation key the whole blob is useless without: the
 * operator pastes it into an issue so a maintainer can find the run in the
 * server's own logs. It is a server-minted opaque id, not user text, and
 * criterion 6's four exclusions do not name it.
 */
export function redactRecord(input: DiagnosticRecord): RedactedRecord {
  return {
    seq: input.seq,
    at: input.at,
    kind: input.kind,
    // The event NAME. Verbatim by contract (H11) — an unknown name is
    // exactly what a bug report is about — but scrubbed all the same,
    // because "verbatim" is a promise about mapping, not about egress.
    event: redactString(input.event, false),
    jobId: input.jobId === null ? null : redactString(input.jobId, false),
    phase: input.phase,
    from: input.from,
    failureKind: input.failureKind,
    detail: redactDetail(input.detail),
  };
}

/** The blob's envelope, so a pasted issue says what it is. */
export interface DiagnosticsBlob {
  schema: "arxiv-research-agent/diagnostics";
  version: 1;
  /** The ring's ceiling, so a reader knows whether anything was dropped. */
  capacity: number;
  count: number;
  dropped: number;
  records: RedactedRecord[];
}

export interface RedactInput {
  records: readonly DiagnosticRecord[];
  capacity?: number;
  dropped?: number;
}

/** Every record, redacted, inside the envelope. */
export function redactDiagnostics({
  records,
  capacity = RING_CAPACITY,
  dropped = 0,
}: RedactInput): DiagnosticsBlob {
  return {
    schema: "arxiv-research-agent/diagnostics",
    version: 1,
    capacity,
    count: records.length,
    dropped,
    records: records.map(redactRecord),
  };
}

/** The blob as the string the clipboard receives. */
export function diagnosticsJson(input: RedactInput): string {
  return JSON.stringify(redactDiagnostics(input), null, 2);
}
