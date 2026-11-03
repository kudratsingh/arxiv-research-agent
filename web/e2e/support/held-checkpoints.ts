import type { Page } from "@playwright/test";

declare global {
  interface Window {
    __clsCheckpointStream?: {
      ready: boolean;
      delivered: number;
      lastInputAt: number;
      release: () => Promise<number>;
    };
  }
}

/** Layout-only transport: open before the mark; emit checkpoints without EOF.
 * Actual SSE framing/reconnection is covered by the stream specs. Closing a
 * fulfilled response introduces a different state transition into a CLS test.
 */
export async function holdCheckpoints(page: Page, jobId: string, nodes: string[]) {
  await page.addInitScript(({ jobId, nodes }) => {
    const Native = window.EventSource;
    const path = `/api/research/${encodeURIComponent(jobId)}/stream`;
    let current: EventTarget & { readyState: number };
    const controller = {
      ready: false, delivered: 0, lastInputAt: 0,
      async release() {
        if (!controller.ready || current.readyState !== 1) throw new Error("checkpoint stream not open");
        for (const node of nodes) {
          current.dispatchEvent(new MessageEvent("node_completed", {
            data: JSON.stringify({job_id: jobId, node, state_delta: {papers_seen: 3}}),
          }));
          controller.delivered++;
          await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        }
        return controller.delivered;
      },
    };
    class HeldSource extends EventTarget {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials: boolean;
      readyState = 0;
      constructor(url: string | URL, options?: EventSourceInit) {
        super();
        this.url = new URL(String(url), location.href).href;
        this.withCredentials = options?.withCredentials ?? false;
        if (new URL(this.url).pathname !== path)
          return new Native(url, options) as unknown as HeldSource;
        current = this;
        controller.ready = false;
        queueMicrotask(() => {
          if (this.readyState === 2 || current !== this) return;
          this.readyState = 1;
          controller.ready = true;
          this.dispatchEvent(new Event("open"));
        });
      }
      close() {
        this.readyState = 2;
        if (current === this) controller.ready = false;
      }
    }
    window.EventSource = HeldSource as unknown as typeof EventSource;
    window.__clsCheckpointStream = controller;
    for (const name of ["pointerdown", "keydown"])
      window.addEventListener(name, () => {controller.lastInputAt = performance.now();}, {capture: true});
  }, {jobId, nodes});
  return {
    async ready() { await page.waitForFunction(() => window.__clsCheckpointStream?.ready); },
    async outsideRecentInput() {
      // CLS excludes the 500ms after input; use the actual last input rather
      // than guessing when page/font/network work might have settled.
      await page.waitForFunction(() => {
        const stream = window.__clsCheckpointStream;
        return stream && performance.now() - stream.lastInputAt > 600;
      });
    },
    async release() { return page.evaluate(() => window.__clsCheckpointStream!.release()); },
    async drainLayout() {
      await page.evaluate(async () => {
        for (let frame = 0; frame < 3; frame++)
          await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
      });
    },
  };
}
