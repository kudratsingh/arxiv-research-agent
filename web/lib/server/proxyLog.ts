/**
 * WO-30 — structured proxy request logging (05-MIGRATION.md C6,
 * 04-ARCHITECTURE.md §9.2 item 3).
 *
 * ONE JSON LINE PER PROXIED REQUEST, TO STDOUT. C6 names the five fields and
 * the three prohibitions in one sentence: "method, path **template**,
 * upstream status, duration, response bytes. Never the key, never a body,
 * never a raw id." This module is where the redaction is *structural* rather
 * than a rule somebody has to remember.
 *
 * THE REDACTION IS A WHITELIST, NOT A SCRUB. `pathTemplate` never sees a
 * header, never sees a body and never sees the query string, and it emits a
 * segment only when that exact segment is a LITERAL in the API contract.
 * Anything else becomes `{id}`. So a job id, a conversation id, an export
 * filename or a value somebody puts in a path one day cannot reach the log
 * by being unusual — it can only reach it by being one of the contract words in
 * `LITERAL_SEGMENTS`, and `web/tests/proxyLogging.test.ts` derives that set
 * from `contract/openapi.json` so a new endpoint fails the test rather than
 * silently widening the whitelist.
 *
 * WHY THERE IS NO LOGGER LIBRARY. The Next server already writes to stdout
 * and Compose already collects it (`docker-compose.yml`); 04 §9.2 is explicit
 * that the frontend transmits nothing anywhere and adds no backend surface.
 * A dependency here would buy formatting this file does in six lines.
 */

/**
 * Every literal path segment in `web/contract/openapi.json`.
 *
 * Transcribed from the fifteen contract paths rather than imported from them:
 * importing the contract JSON would pull the whole document
 * into the server bundle to answer a small-set question. The transcription
 * is not trusted — `web/tests/proxyLogging.test.ts` rebuilds this set from
 * `contract/openapi.json` and fails on any difference, in both directions.
 *
 *   /research, /research/{job_id}, /research/{job_id}/review,
 *   /research/{job_id}/export, /research/{job_id}/stream,
 *   /conversations, /conversations/{conversation_id}, /healthz,
 *   /learn/profile, /learn/progress, /learn/paths,
 *   /learn/paths/{path_id}, /learn/sessions,
 *   /learn/sessions/{session_id}, /learn/sessions/{session_id}/turn
 *
 * The learner literals arrived with WO-W02's profile, WO-W07's ledger, and
 * WO-W15's paths. A `path_id` is a slug an editor chose, not a secret — but
 * it is still an id, and the whitelist does not make exceptions for ids
 * that look harmless.
 */
export const LITERAL_SEGMENTS: ReadonlySet<string> = new Set([
  "conversations",
  "export",
  "healthz",
  "learn",
  "paths",
  "profile",
  "progress",
  "research",
  "review",
  "sessions",
  "stream",
  "turn",
]);

/** What an unrecognised segment is replaced by. Never the value itself. */
export const REDACTED_SEGMENT = "{id}";

/**
 * Reduce the catch-all's path segments to a loggable template.
 *
 * Args:
 *   segments: The `[...path]` segments, exactly as Next parsed them — no
 *     query string, because `URL.search` is deliberately never passed in.
 *
 * Returns:
 *   `/research/{id}/stream` for `["research", "abc-123", "stream"]`. An empty
 *   segment list renders `/`, which is not a route the proxy serves but is
 *   the honest rendering of "nothing was addressed".
 *
 * A segment is kept only if it is a literal in the contract. That rule is
 * positional-blind on purpose: a positional rule would need a route table
 * kept in step with the backend by hand, and the failure mode of a stale
 * route table is a raw id in a log line.
 */
export function pathTemplate(segments: readonly string[]): string {
  const rendered = segments
    .map((segment) => (LITERAL_SEGMENTS.has(segment) ? segment : REDACTED_SEGMENT))
    .join("/");
  return `/${rendered}`;
}

/** Why a request did not reach FastAPI. Absent on the happy path. */
export type ProxyOutcome = "misconfigured" | "upstream_unavailable";

/** One request, as it will be serialised. */
export interface ProxyLogRecord {
  method: string;
  /** Already reduced by `pathTemplate`. This type cannot express a raw path. */
  pathTemplate: string;
  /** The status returned to the browser — upstream's, or the local failure. */
  status: number;
  /** Wall clock from route entry to the last response byte, in milliseconds. */
  durationMs: number;
  /** Response bytes streamed to the browser. `0` for a local failure. */
  bytes: number;
  /** Present only when the proxy answered locally instead of forwarding. */
  outcome?: ProxyOutcome;
}

/** The stable `event` value, so the line is greppable in a mixed stdout. */
export const PROXY_LOG_EVENT = "api_proxy_request";

/**
 * Serialise one record.
 *
 * Key order is fixed so a human scanning `docker compose logs` reads the same
 * shape every time, and so `ci/proxy-log-sample.txt` is diffable.
 */
export function formatProxyLogLine(record: ProxyLogRecord): string {
  const line: Record<string, string | number> = {
    event: PROXY_LOG_EVENT,
    method: record.method,
    path: record.pathTemplate,
    status: record.status,
    duration_ms: record.durationMs,
    bytes: record.bytes,
  };
  if (record.outcome !== undefined) line["outcome"] = record.outcome;
  return JSON.stringify(line);
}

/**
 * Write one record to stdout.
 *
 * `process.stdout.write` rather than `console.log`: the route pins
 * `runtime = "nodejs"`, and `console` in a Next server is decorated
 * (prefixes, colour, occasional grouping) in ways that would stop the line
 * being parseable JSON. Failure to write is swallowed — a broken pipe on a
 * log stream must never turn a working proxy response into a 500.
 */
export function emitProxyLog(record: ProxyLogRecord): void {
  try {
    process.stdout.write(`${formatProxyLogLine(record)}\n`);
  } catch {
    // Observability is not allowed to break the thing it observes.
  }
}

/**
 * Wrap an upstream body so its bytes are counted as they stream past.
 *
 * WHY A TRANSFORM AND NOT `await response.arrayBuffer()`. The proxy's whole
 * reason for returning `upstream.body` directly is that SSE must not be
 * buffered and a 40 MB export must not be held in memory
 * (`route.ts`'s opening comment). A counting `TransformStream` preserves
 * both: it enqueues each chunk as it arrives and propagates backpressure, so
 * the stream stays the stream.
 *
 * WHEN THE LINE IS EMITTED. On the last byte, not on the response headers —
 * which means an SSE stream held open for an hour logs when it closes, and
 * `duration_ms` is then the lifetime of the stream rather than the latency of
 * the proxy. That is the correct reading of "one line per proxied request",
 * and it is why `settle` is also wired to the request's abort signal: a
 * browser that navigates away closes the stream without ever reaching
 * `flush`.
 *
 * Args:
 *   body: The upstream stream. `null` for a bodiless response.
 *   signal: The browser request's abort signal.
 *   done: Called exactly once with the byte count.
 *
 * Returns:
 *   The stream to hand to `new Response(...)`, or `null`.
 */
export function countStreamedBytes(
  body: ReadableStream<Uint8Array> | null,
  signal: AbortSignal,
  done: (bytes: number) => void,
): ReadableStream<Uint8Array> | null {
  let bytes = 0;
  let settled = false;
  const settle = (): void => {
    if (settled) return;
    settled = true;
    done(bytes);
  };

  if (body === null) {
    settle();
    return null;
  }

  signal.addEventListener("abort", settle, { once: true });

  const counter = new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      bytes += chunk.byteLength;
      controller.enqueue(chunk);
    },
  });

  // `pipeTo` rather than `pipeThrough` for one reason: it returns a promise
  // that settles on close AND on error, so a stream that dies mid-flight
  // still logs what it managed to send. `pipeThrough` would only give us
  // `flush`, which a broken source never reaches.
  void body.pipeTo(counter.writable).then(settle, settle);
  return counter.readable;
}
