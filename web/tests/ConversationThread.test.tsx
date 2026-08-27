// Pins the run page's adopt-don't-resubmit contract (ADR 0053).
//
// The thread must attach to the job named in the URL and must never
// POST /research on its own — not on mount, not on a reload, not when
// the URL-sync effect re-renders it with the id it is already
// streaming. Every assertion here counts: open EventSources, and
// POSTs to /research.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { StrictMode } from "react";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ConversationThread from "@/components/ConversationThread";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn() }),
}));

// ---------------------------------------------------------------------------
// EventSource stub — jsdom has none.
// ---------------------------------------------------------------------------

type Listener = (evt: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static readonly CLOSED = 2;

  public readonly url: string;
  public closed = false;
  public readyState = 1;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(name: string, fn: Listener): void {
    const existing = this.listeners.get(name) ?? [];
    existing.push(fn);
    this.listeners.set(name, existing);
  }

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  /** Deliver one SSE frame to the component under test. */
  emit(name: string, data: unknown): void {
    const payload = { data: JSON.stringify(data) } as MessageEvent;
    for (const fn of this.listeners.get(name) ?? []) fn(payload);
  }

  /**
   * What a browser does on a non-200 response (the stream route's
   * 404): fail the connection permanently — `readyState` goes to
   * CLOSED and no retry follows.
   */
  fatal(): void {
    this.readyState = FakeEventSource.CLOSED;
    for (const fn of this.listeners.get("error") ?? [])
      fn({} as MessageEvent);
  }

  /** A transient drop the browser will retry on its own. */
  transientDrop(): void {
    this.readyState = 0;
    for (const fn of this.listeners.get("error") ?? [])
      fn({} as MessageEvent);
  }
}

/** Sources not yet closed — the count that matters for double-streaming. */
function openSources(): FakeEventSource[] {
  return FakeEventSource.instances.filter((s) => !s.closed);
}

// ---------------------------------------------------------------------------
// fetch stub
// ---------------------------------------------------------------------------

const originalFetch = globalThis.fetch;
const originalEventSource = globalThis.EventSource;

let calls: string[] = [];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const JOB_DETAIL = {
  job_id: "job-1",
  status: "succeeded",
  query: "q",
  created_at: 0,
  started_at: 0,
  completed_at: 1,
  elapsed_sec: 1,
  result: "# Report\n\nbody",
  error: null,
  error_type: null,
  cost_usd: 0.1,
  llm_calls: 3,
  iterations: 1,
  quality_score: 0.9,
  plan: null,
  conversation_id: "conv-1",
};

function installFetch(): void {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const apiPath = url.pathname.replace(/^\/api/, "") || "/";
    calls.push(`${method} ${apiPath}`);
    if (apiPath === "/conversations/conv-1" && method === "GET") {
      return jsonResp({
        conversation_id: "conv-1",
        title: "A conversation",
        created_at: 0,
        updated_at: 0,
        jobs: [],
      });
    }
    if (apiPath === "/research/job-1" && method === "GET") {
      return jsonResp(JOB_DETAIL);
    }
    if (apiPath === "/research" && method === "POST") {
      return jsonResp({
        job_id: "job-2",
        status: "pending",
        status_url: "/research/job-2",
        stream_url: "/research/job-2/stream",
      });
    }
    if (apiPath === "/research/job-2" && method === "GET") {
      return jsonResp({ ...JOB_DETAIL, job_id: "job-2" });
    }
    throw new Error(`unexpected request: ${method} ${apiPath}`);
  }) as unknown as typeof fetch;
}

function countOf(key: string): number {
  return calls.filter((c) => c === key).length;
}

beforeEach(() => {
  calls = [];
  replace.mockClear();
  FakeEventSource.instances = [];
  globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  installFetch();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.EventSource = originalEventSource;
});

async function renderThread(adoptJobId: string | null = "job-1") {
  const view = render(
    <ConversationThread conversationId="conv-1" adoptJobId={adoptJobId} />
  );
  // The thread renders a loading placeholder until GET /conversations
  // resolves; wait so assertions run against the real tree.
  await screen.findByText("A conversation");
  return view;
}

describe("ConversationThread job adoption (ADR 0053)", () => {
  it("attaches to the job named in the URL without submitting one", async () => {
    await renderThread("job-1");

    await waitFor(() => expect(openSources()).toHaveLength(1));
    expect(openSources()[0]!.url).toBe("/api/research/job-1/stream");
    expect(countOf("POST /research")).toBe(0);
  });

  it("re-attaches on a reload instead of resubmitting", async () => {
    const first = await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));

    // A browser reload is a fresh mount of the same URL.
    first.unmount();
    expect(openSources()).toHaveLength(0);
    await renderThread("job-1");

    await waitFor(() => expect(openSources()).toHaveLength(1));
    expect(FakeEventSource.instances).toHaveLength(2);
    expect(countOf("POST /research")).toBe(0);
  });

  it("opens exactly one stream under StrictMode's double mount", async () => {
    render(
      <StrictMode>
        <ConversationThread conversationId="conv-1" adoptJobId="job-1" />
      </StrictMode>
    );
    await screen.findByText("A conversation");

    await waitFor(() => expect(openSources()).toHaveLength(1));
    expect(countOf("POST /research")).toBe(0);
  });

  it("does not re-open the stream when the URL sync feeds the id back", async () => {
    const view = await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));
    const source = openSources()[0]!;

    // The URL-sync effect rewrites `?job=` for jobs this thread starts
    // itself; the resulting re-render hands the same id back as
    // `adoptJobId`, and that must be a no-op.
    view.rerender(
      <ConversationThread conversationId="conv-1" adoptJobId="job-1" />
    );

    expect(openSources()).toHaveLength(1);
    expect(openSources()[0]).toBe(source);
    expect(countOf("POST /research")).toBe(0);
  });

  it("renders the review panel from a replayed plan_ready frame", async () => {
    await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));

    // The server replays this on attach for a job parked in
    // pending_review (ADR 0053, stream route).
    act(() => {
      openSources()[0]!.emit("plan_ready", {
        job_id: "job-1",
        plan: {
          sub_questions: ["what is X?"],
          search_queries: ["X survey"],
        },
      });
    });

    expect(
      await screen.findByRole("button", { name: /approve as-is/i })
    ).toBeInTheDocument();
    expect(countOf("POST /research")).toBe(0);
  });

  it("settles the adopted job on a terminal frame and reloads the thread", async () => {
    await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));
    const source = openSources()[0]!;

    act(() => {
      source.emit("job_completed", { job_id: "job-1", status: "succeeded" });
    });

    await waitFor(() => expect(countOf("GET /research/job-1")).toBe(1));
    // The terminal frame closes the stream, and `onDone` refreshes the
    // transcript so the finished turn shows up above the composer.
    expect(source.closed).toBe(true);
    await waitFor(() => expect(countOf("GET /conversations/conv-1")).toBe(2));
  });

  it("keeps the live stream when its own submit feeds the URL back", async () => {
    const user = userEvent.setup();
    const view = await renderThread(null);

    // A follow-up turn: the thread submits it and starts streaming.
    await user.type(screen.getByLabelText(/research question/i), "follow-up");
    await user.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(openSources()).toHaveLength(1));
    const source = openSources()[0]!;
    expect(source.url).toBe("/api/research/job-2/stream");

    act(() => {
      source.emit("node_completed", { node: "planner", elapsed_sec: 1 });
    });
    expect(await screen.findByText("node_completed")).toBeInTheDocument();

    // The URL sync writes the new id into the route, which comes back
    // as `adoptJobId` on the next render. Adopting the job we are
    // already streaming must not tear the stream down and must not
    // wipe the frames received so far.
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/c/conv-1?job=job-2")
    );
    view.rerender(
      <ConversationThread conversationId="conv-1" adoptJobId="job-2" />
    );

    expect(openSources()).toHaveLength(1);
    expect(openSources()[0]).toBe(source);
    expect(screen.getByText("node_completed")).toBeInTheDocument();
    expect(countOf("POST /research")).toBe(1);
  });

  it("writes the URL once per job, so `?job=` can be dropped", async () => {
    const user = userEvent.setup();
    const view = await renderThread(null);
    await user.type(screen.getByLabelText(/research question/i), "follow-up");
    await user.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledTimes(1));

    // Navigating back to the bare thread URL (the sidebar link) must
    // stick: re-adding `?job=` from stale hook state would make the
    // parameter impossible to get rid of.
    view.rerender(
      <ConversationThread conversationId="conv-1" adoptJobId={null} />
    );

    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("recovers the composer when the adopted job no longer exists", async () => {
    // `?job=` outlives the job itself: `job_retention_sec` evicts the
    // row, and the default in-memory store loses every job on an `api`
    // restart. Reloading that URL then streams a 404, which the
    // browser fails permanently. Without a fatal-close branch the
    // thread stayed on status "streaming" — composer disabled forever,
    // nothing on screen saying why.
    const user = userEvent.setup();
    await renderThread("evicted-job");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0]!.fatal();
    });

    // The dead-end is explained, not silent...
    expect(await screen.findByRole("alert")).toHaveTextContent(/evicted-job/);
    // ...and the thread is usable again: the user can ask the question
    // a second time rather than staring at a disabled "Running…".
    expect(countOf("POST /research")).toBe(0);
    await user.type(screen.getByLabelText(/research question/i), "ask again");
    await user.click(screen.getByRole("button", { name: /run research/i }));
    await waitFor(() => expect(countOf("POST /research")).toBe(1));
  });

  it("does not report a settled stream's close as a failure", async () => {
    // The terminal handler closes the source itself, which is also
    // `readyState === CLOSED`. Treating that as the fatal case would
    // overwrite a finished run with "stream unavailable" and throw the
    // report away.
    await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));
    const source = FakeEventSource.instances[0]!;

    act(() => {
      source.emit("job_completed", { job_id: "job-1", status: "succeeded" });
    });
    await waitFor(() => expect(countOf("GET /research/job-1")).toBe(1));

    act(() => {
      source.fatal();
    });

    expect(screen.queryByRole("alert")).toBeNull();
    // The settled report body is still on screen.
    expect(await screen.findByText("body")).toBeInTheDocument();
  });

  it("keeps streaming through a drop the browser will retry", async () => {
    // The other half of the same handler: a transient interruption
    // must stay a note, not unlock the composer mid-run.
    await renderThread("job-1");
    await waitFor(() => expect(openSources()).toHaveLength(1));

    act(() => {
      openSources()[0]!.transientDrop();
    });

    expect(await screen.findByText("stream_note")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /running/i })).toBeDisabled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("opens no stream at all when the URL names no job", async () => {
    await renderThread(null);

    expect(FakeEventSource.instances).toHaveLength(0);
    expect(countOf("POST /research")).toBe(0);
    expect(replace).not.toHaveBeenCalled();
  });
});
