/**
 * WO-16 criterion 6 — "'Copy diagnostics' produces redacted JSON with no
 * report text, no question text, no headers, and no URLs beyond the path
 * template; a test feeds a record containing all four and asserts none
 * survives."
 *
 * `THE_RECORD` below is that record. It carries all four in one object, and
 * `describe("criterion 6 — the four exclusions")` asserts against the
 * SERIALIZED blob rather than against the object graph: the promise
 * `DIAGNOSTICS.copyNote` makes is about what lands on the clipboard, and a
 * value hiding in a key name or a nested array would pass an object-level
 * check and still be pasted into an issue.
 *
 * The second half is the part that makes the first half mean something: the
 * evidence RC-16 requires — the raw `error` string, the raw `error_type` —
 * has to SURVIVE. A redactor that emptied the blob would pass every
 * exclusion assertion and be worthless.
 */

import { describe, expect, it } from "vitest";

import { RING_CAPACITY } from "@/lib/diagnostics/constants";
import {
  EVIDENCE_KEY_PARTS,
  MAX_PROSE_WORDS,
  MAX_VALUE_CHARS,
  PATH_ID,
  PATH_SEGMENT_VOCABULARY,
  REDACTED,
  REDACTED_KEY_PARTS,
  TRUNCATED,
  diagnosticsJson,
  pathTemplate,
  redactDetail,
  redactDiagnostics,
  redactRecord,
  redactString,
  redactValue,
  scrubUrls,
} from "@/lib/diagnostics/redact";
import type { DiagnosticRecord } from "@/lib/diagnostics/ring";

// ---------------------------------------------------------------------------
// The four things criterion 6 names, in one record.
// ---------------------------------------------------------------------------

const QUESTION = "What evaluation methods make research agents reliable?";

const REPORT =
  "## Findings\n\nRetrieval-augmented evaluation harnesses converge on three " +
  "families of metric, of which only the third survives contact with " +
  "adversarial paraphrase; the remainder degrade under distribution shift.";

const FULL_URL =
  "https://arxiv-agent.internal.example.com/api/research/9f3a1c2e-4b5d-6e7f-8a9b-0c1d2e3f4a5b/stream?api_key=sk-live-notarealkey123456";

const THREAD_URL = "https://arxiv-agent.internal.example.com/c/1f0e2d3c-4b5a-6978-8796-a5b4c3d2e1f0?job=9f3a1c2e";

const THE_RECORD: DiagnosticRecord = {
  seq: 7,
  at: Date.UTC(2026, 7, 28, 9, 14, 3, 120),
  kind: "frame",
  event: "job_started",
  jobId: "9f3a1c2e-4b5d-6e7f-8a9b-0c1d2e3f4a5b",
  phase: "live",
  from: null,
  failureKind: null,
  detail: {
    // (1) Question text, under the API's own field name.
    query: QUESTION,
    question: QUESTION,
    // (2) Report text, under three of the shapes it arrives in.
    report: REPORT,
    partial_report: REPORT,
    resultMarkdown: REPORT,
    // (3) Headers, as the object a fetch wrapper would hand over, and as
    //     the flattened string a logger would.
    headers: { authorization: "Bearer sk-live-notarealkey123456", cookie: "sid=abc" },
    request_header: "Authorization: Bearer sk-live-notarealkey123456",
    // (4) URLs, absolute and relative, in a field and inside prose.
    url: FULL_URL,
    thread_url: THREAD_URL,
    stream_path: "/api/research/9f3a1c2e-4b5d-6e7f-8a9b-0c1d2e3f4a5b/stream",
    error: `GET ${FULL_URL} failed`,
    // And the things that must survive.
    error_type: "AnthropicOverloadedError",
    node: "searcher",
    state_delta: { iteration: 1 },
  },
};

const BLOB = diagnosticsJson({ records: [THE_RECORD], capacity: RING_CAPACITY, dropped: 2 });

describe("criterion 6 — the four exclusions, against the serialized blob", () => {
  it("no question text survives", () => {
    expect(BLOB).not.toContain(QUESTION);
    expect(BLOB).not.toContain("evaluation methods");
    expect(BLOB).not.toMatch(/research agents reliable/);
  });

  it("no report text survives", () => {
    expect(BLOB).not.toContain(REPORT);
    expect(BLOB).not.toContain("adversarial paraphrase");
    expect(BLOB).not.toContain("Findings");
  });

  it("no headers survive, object or flattened", () => {
    expect(BLOB).not.toContain("Bearer");
    expect(BLOB).not.toContain("sk-live");
    expect(BLOB).not.toContain("sid=abc");
    expect(BLOB.toLowerCase()).not.toContain("authorization: ");
  });

  it("no URL beyond the path template survives", () => {
    expect(BLOB).not.toContain("https://");
    expect(BLOB).not.toContain("example.com");
    expect(BLOB).not.toContain("api_key");
    // No raw identifier is left inside any path.
    expect(BLOB).not.toContain("/api/research/9f3a1c2e");
  });

  it("keeps the path TEMPLATE, which is what the exclusion allows", () => {
    const blob = redactDiagnostics({ records: [THE_RECORD] });
    expect(blob.records[0]?.detail?.["stream_path"]).toBe("/api/research/{id}/stream");
    expect(blob.records[0]?.detail?.["url"]).toBe("/api/research/{id}/stream");
    expect(blob.records[0]?.detail?.["thread_url"]).toBe("/c/{id}");
  });

  it("does not throw, drop the record, or lose the envelope", () => {
    const blob = redactDiagnostics({ records: [THE_RECORD], capacity: 200, dropped: 2 });
    expect(blob.records).toHaveLength(1);
    expect(blob).toMatchObject({
      schema: "arxiv-research-agent/diagnostics",
      version: 1,
      capacity: 200,
      count: 1,
      dropped: 2,
    });
  });
});

describe("criterion 6 — what MUST survive, or the blob is useless", () => {
  const redacted = redactRecord(THE_RECORD);

  it("keeps the raw error_type verbatim (RC-16)", () => {
    expect(redacted.detail?.["error_type"]).toBe("AnthropicOverloadedError");
  });

  it("keeps the raw error string, with only its URL templated", () => {
    expect(redacted.detail?.["error"]).toBe("GET /api/research/{id}/stream failed");
  });

  it("keeps the opaque node label and the state_delta keys (H11)", () => {
    // The one-level walk exists for this: `state_delta` is the open scalar
    // map an incident report is about, and collapsing it would make the
    // blob safe and useless at the same time.
    expect(redacted.detail?.["node"]).toBe("searcher");
    expect(redacted.detail?.["state_delta"]).toEqual({ iteration: 1 });
  });

  it("keeps the machine's own fields, which are not user data", () => {
    expect(redacted).toMatchObject({
      seq: 7,
      at: THE_RECORD.at,
      kind: "frame",
      event: "job_started",
      phase: "live",
    });
  });

  it("keeps the run id, because 04 §9.2 names it as part of the record", () => {
    // The correlation key a maintainer needs to find the run in the
    // server's own logs. Server-minted, opaque, and not one of the four
    // things criterion 6 excludes.
    expect(redacted.jobId).toBe(THE_RECORD.jobId);
  });

  it("keeps the previous phase and the normalized failure kind", () => {
    const transition = redactRecord({
      ...THE_RECORD,
      kind: "failure",
      from: "live",
      failureKind: "upstream_unavailable",
      detail: null,
    });
    expect(transition.from).toBe("live");
    expect(transition.failureKind).toBe("upstream_unavailable");
    expect(transition.detail).toBeNull();
  });
});

describe("pathTemplate", () => {
  it.each([
    ["https://host.example/api/research/abc-123/stream", "/api/research/{id}/stream"],
    ["http://localhost:3000/api/conversations/xyz", "/api/conversations/{id}"],
    ["/api/research/abc/review", "/api/research/{id}/review"],
    ["/api/research/abc/export", "/api/research/{id}/export"],
    ["/c/thread-1", "/c/{id}"],
    ["/api/healthz", "/api/healthz"],
    ["https://host.example", "/"],
    ["https://host.example/", "/"],
  ])("%s -> %s", (input, expected) => {
    expect(pathTemplate(input)).toBe(expected);
  });

  it("drops the query and the fragment, which is where secrets hide", () => {
    expect(pathTemplate("/api/research/abc/stream?api_key=secret#frag")).toBe(
      "/api/research/{id}/stream",
    );
  });

  it("is idempotent, so the two scrub passes cannot double-template", () => {
    const once = pathTemplate("/api/research/abc/stream");
    expect(pathTemplate(once)).toBe(once);
    expect(scrubUrls(scrubUrls("see https://h.example/api/research/x/stream"))).toBe(
      scrubUrls("see https://h.example/api/research/x/stream"),
    );
  });

  it("leaves a string that is not a URL or an absolute path alone", () => {
    expect(pathTemplate("searcher")).toBe("searcher");
    expect(pathTemplate("")).toBe("");
    expect(scrubUrls("no urls here at all")).toBe("no urls here at all");
  });

  it("templates every segment outside the API's own vocabulary", () => {
    // The allow-list is the mechanism. A length or shape heuristic would
    // template `conversations` (13 characters) and keep a 12-character run
    // id, which is the wrong way round.
    expect(PATH_SEGMENT_VOCABULARY.has("conversations")).toBe(true);
    expect(PATH_SEGMENT_VOCABULARY.has("research")).toBe(true);
    expect(pathTemplate("/api/conversations/aaaaaaaaaaaa")).toBe(
      `/api/conversations/${PATH_ID}`,
    );
    expect(pathTemplate("/api/newendpoint/1")).toBe(`/api/${PATH_ID}/${PATH_ID}`);
  });
});

describe("redactValue — the key deny-list", () => {
  it.each(REDACTED_KEY_PARTS)("redacts anything whose key contains %s", (part) => {
    expect(redactValue(part, "some value")).toBe(REDACTED);
    expect(redactValue(`prefix_${part}_suffix`, 42)).toBe(REDACTED);
    expect(redactValue(part.toUpperCase(), "some value")).toBe(REDACTED);
  });

  it("keeps scalars under keys that name nothing sensitive", () => {
    expect(redactValue("iteration", 1)).toBe(1);
    expect(redactValue("papers_found", 9)).toBe(9);
    expect(redactValue("unreleased_feature_flag", true)).toBe(true);
    expect(redactValue("elapsed_sec", 74.3)).toBe(74.3);
    expect(redactValue("shape", "replay")).toBe("replay");
    expect(redactValue("nothing", null)).toBeNull();
  });

  it("walks an object exactly one level, with the same rules", () => {
    expect(redactValue("payload", { a: 1, query: QUESTION })).toEqual({
      a: 1,
      query: REDACTED,
    });
    // One level and no deeper: no recursion, no unbounded output shape.
    expect(redactValue("payload", { nested: { deeper: 1 } })).toEqual({
      nested: REDACTED,
    });
  });

  it("replaces everything else rather than walking it", () => {
    // An array has no keys, so the key deny-list has nothing to work with.
    expect(redactValue("payload", [1, 2, 3])).toBe(REDACTED);
    expect(redactValue("payload", undefined)).toBe(REDACTED);
    expect(redactValue("payload", () => 1)).toBe(REDACTED);
    expect(redactValue("payload", { a: [1] })).toEqual({ a: REDACTED });
  });

  it("catches a headers object by its own key, before the walk starts", () => {
    expect(
      redactValue("headers", { authorization: "Bearer sk-live-abcdefghij" }),
    ).toBe(REDACTED);
  });

  it("redacts a whole detail map key by key, keeping unknown key NAMES", () => {
    expect(redactDetail({ iteration: 1, query: QUESTION, novel_key: "ok" })).toEqual({
      iteration: 1,
      query: REDACTED,
      novel_key: "ok",
    });
    expect(redactDetail(null)).toBeNull();
  });
});

describe("redactString — the value rules", () => {
  it("drops prose, whatever key it arrived under", () => {
    const prose = Array.from({ length: MAX_PROSE_WORDS + 1 }, () => "word").join(" ");
    expect(redactString(prose, false)).toBe(REDACTED);
    expect(redactString("short enough", false)).toBe("short enough");
  });

  it("drops an over-long string even when it is one word", () => {
    expect(redactString("x".repeat(MAX_VALUE_CHARS + 1), false)).toBe(REDACTED);
    expect(redactString("x".repeat(MAX_VALUE_CHARS), false)).toHaveLength(MAX_VALUE_CHARS);
  });

  it("TRUNCATES rather than drops an evidence string, visibly", () => {
    // RC-16 forbids editing the backend's message; truncation is stated in
    // the value rather than silent, and a real traceback is longer than a
    // dozen words.
    const traceback = `Traceback: ${"frame ".repeat(80)}`;
    const out = redactString(traceback, true);
    expect(out.endsWith(TRUNCATED)).toBe(true);
    expect(out.startsWith("Traceback: frame")).toBe(true);
    expect(redactString("short error", true)).toBe("short error");
  });

  it("kills a credential shape even when it is short", () => {
    // Three words, well under the prose ceiling: the deny-lists alone
    // would let this through.
    expect(redactString("Bearer sk-live-abcdefghij", true)).toBe(REDACTED);
    expect(redactString("authorization: whatever", false)).toBe(REDACTED);
    expect(redactString("x-api-key present", true)).toBe(REDACTED);
  });

  it("names the evidence keys explicitly, so the exemption is reviewable", () => {
    expect([...EVIDENCE_KEY_PARTS].sort()).toEqual(["error", "message", "reason", "shape"]);
  });
});

describe("the blob a reader pastes into an issue", () => {
  it("is indented JSON with the envelope first", () => {
    const parsed = JSON.parse(BLOB) as { schema: string; records: unknown[] };
    expect(parsed.schema).toBe("arxiv-research-agent/diagnostics");
    expect(parsed.records).toHaveLength(1);
    expect(BLOB).toContain("\n  ");
  });

  it("defaults the envelope to the ring's own ceiling", () => {
    const blob = redactDiagnostics({ records: [] });
    expect(blob).toMatchObject({ capacity: RING_CAPACITY, count: 0, dropped: 0 });
    expect(blob.records).toEqual([]);
  });

  it("scrubs a URL that arrived in the event NAME itself", () => {
    const odd = redactRecord({
      ...THE_RECORD,
      event: "https://host.example/api/research/abc/stream",
      detail: null,
    });
    expect(odd.event).toBe("/api/research/{id}/stream");
  });

  it("survives a record whose jobId is a full URL", () => {
    const odd = redactRecord({ ...THE_RECORD, jobId: FULL_URL, detail: null });
    expect(odd.jobId).not.toContain("https://");
    expect(odd.jobId).not.toContain("api_key");
  });

  it("keeps a null jobId null", () => {
    expect(redactRecord({ ...THE_RECORD, jobId: null, detail: null }).jobId).toBeNull();
  });
});
