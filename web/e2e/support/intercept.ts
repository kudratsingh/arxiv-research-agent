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
  /**
   * `Date.now()` at each open, in order.
   *
   * WHY A COUNT IS NOT ENOUGH, AND WHY THIS EXISTS (WO-27).
   * `docs/revamp/evidence/gate-3/known-gaps.md` §2 records
   * `stream.spec.ts`'s "an interrupted 200 stream is narrated, not raced" as
   * intermittently red — 3 failures in 12 runs — with the diagnosis: "The
   * assertion cannot distinguish the browser's retry from a client-initiated
   * second open, which is the only thing it means to forbid."
   *
   * That is exactly right, and it is a property of the counter rather than
   * of the product: `opens()` conflates two events that mean opposite things.
   * `EventSource`'s own reconnection is the CORRECT behaviour the test exists
   * to confirm the UI narrates; a second connection opened by the client is
   * the defect. They are indistinguishable at the network layer and trivially
   * distinguishable in TIME — the browser waits its reconnection interval
   * (3 s in Chromium and WebKit, 5 s in Firefox) while a client-initiated
   * reopen lands in the same task.
   *
   * So this records when, and `RACE_FLOOR_MS` below is the line between them.
   */
  openTimes(): number[];
}

/**
 * The shortest gap between two opens that can still be the browser's own
 * backoff rather than a client racing it.
 *
 * An order of magnitude below the smallest default reconnection interval any
 * of the three engines uses, and two orders above the sub-10 ms a
 * same-task reopen would show. The gap it has to separate is not close.
 */
export const RACE_FLOOR_MS = 1_000;

/** The gaps between consecutive opens, in ms. */
export function openGaps(interceptor: StreamInterceptor): number[] {
  const times = interceptor.openTimes();
  return times.slice(1).map((time, index) => time - (times[index] as number));
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
  const times: number[] = [];
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      times.push(Date.now());
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: SSE_HEADERS,
        body: ": synthetic connection interruption\n\n",
      });
    },
  );
  return { opens: () => times.length, openTimes: () => [...times] };
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
  const times: number[] = [];
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      times.push(Date.now());
      const body =
        times.length === 1
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
  return { opens: () => times.length, openTimes: () => [...times] };
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
  const times: number[] = [];
  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      times.push(Date.now());
      await route.fallback();
    },
  );
  return { opens: () => times.length, openTimes: () => [...times] };
}
