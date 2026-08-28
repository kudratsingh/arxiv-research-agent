import type { Page } from "@playwright/test";

/**
 * Route interception for the two stream failures a seeded stack cannot
 * produce on demand (criterion 4; 04 §7.2, last paragraph).
 *
 * Everything else in this suite runs against the real backend over a real
 * SSE connection. These two do not, and the reasons are specific:
 *
 *   * **The interrupted 200.** A valid `text/event-stream` response that
 *     closes without a terminal frame. The server never does this on purpose,
 *     and the only way to get one from a real stack is to kill it mid-run —
 *     which is neither deterministic nor repeatable. The technique is the one
 *     already proven at
 *     `docs/revamp/baseline/fixtures/capture-baseline.spec.ts:63-76`, carried
 *     over unchanged: fulfil with a comment-only body, which is a
 *     *well-formed* stream that simply ends, leaving `EventSource` in the
 *     browser-managed retry state. It is deliberately distinct from an
 *     expired-job 404, which means something else entirely (H8).
 *
 *   * **`stream_timeout`.** `src/api/streaming.py:295-309` emits it when the
 *     response reaches `api_sse_max_duration_sec` — minutes of wall clock,
 *     configurable but not addressable from a test. The frame below is that
 *     call site's payload, field for field.
 *
 * Both count the stream opens, because the observable consequence of a
 * `stream_timeout` is a REOPEN (`web/lib/job/useJobStream.ts:387`), and a
 * count is the only way to see one from outside.
 */

/** Encodes one frame exactly as `src/api/streaming.py:117-132` does. */
export function sseFrame(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** The SSE response headers the backend sets (`streaming.py`). */
const SSE_HEADERS = {
  "cache-control": "no-cache",
  connection: "keep-alive",
  "x-accel-buffering": "no",
} as const;

export interface StreamInterceptor {
  /** How many times the browser has opened the stream for this job. */
  opens(): number;
}

/**
 * The interrupted 200: a well-formed stream that closes with no terminal
 * frame.
 *
 * The body is a single SSE comment. Comments are legal and are discarded by
 * the client, so the response is a *valid* event stream carrying no events —
 * which is precisely the failure being reproduced. `EventSource` sees a clean
 * end-of-stream on a 200 and enters its own retry, and the app narrates that
 * rather than racing it (`web/lib/job/machine.ts:352-358`).
 */
export async function interruptStream(
  page: Page,
  jobId: string,
): Promise<StreamInterceptor> {
  let opens = 0;
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      opens += 1;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: SSE_HEADERS,
        body: ": synthetic connection interruption\n\n",
      });
    },
  );
  return { opens: () => opens };
}

/**
 * A stream that ends with `stream_timeout` the first time and stays open (as
 * an interrupted stream) afterwards.
 *
 * The point of the second response is that there IS one: the assertion is
 * that the client reopened, so the interceptor has to still be there to be
 * asked. Reopening onto a second timeout frame would make an infinite loop
 * out of an assertion.
 */
export async function timeoutThenHold(
  page: Page,
  jobId: string,
  maxDurationSec = 300,
): Promise<StreamInterceptor> {
  let opens = 0;
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      opens += 1;
      const body =
        opens === 1
          ? // `src/api/streaming.py:300-308`, payload field for field.
            sseFrame("stream_timeout", {
              job_id: jobId,
              reason: "max_duration_exceeded",
              max_duration_sec: maxDurationSec,
              reconnect: true,
            })
          : ": reopened after stream_timeout\n\n";
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: SSE_HEADERS,
        body,
      });
    },
  );
  return { opens: () => opens };
}

/**
 * Count stream opens without changing what the stack sends.
 *
 * Used by the attach/bfcache proofs, where the assertion is about how many
 * connections were made to a REAL stream, not about what came back.
 */
export async function countStreamOpens(
  page: Page,
  jobId: string,
): Promise<StreamInterceptor> {
  let opens = 0;
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      opens += 1;
      await route.fallback();
    },
  );
  return { opens: () => opens };
}
