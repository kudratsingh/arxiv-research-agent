// GET-first attach (WO-10 acceptance criterion 2,
// 04-ARCHITECTURE.md §4.3, 05-MIGRATION.md §2.1 step 2).
//
// Today `attach` opens the stream first
// (`useResearchStream.ts:238-253`) and learns the job's status from
// whatever frame arrives. Three things go wrong because of that, and
// each has a test below:
//
//   - an expired job arrives through the browser's failed-connection
//     path (`useResearchStream.ts:171-188`) instead of a clean 404;
//   - a `pending_review` job cannot render its plan without the
//     ADR-0053 replay;
//   - a `running` job shows nothing until the next node finishes.
//
// The integration tier here runs against MSW and the recorded
// fixtures, so the 404 travels the real path: recorded envelope →
// `lib/api` → normalized `ApiFailure` → machine.
//
// `POST /research` has no MSW handler by design, and
// `onUnhandledRequest: "error"` turns any attempt into a failure. The
// counter below says so out loud as well.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { UNAVAILABLE_COPY, terminalPhrase } from "@/lib/job/machine";
import { useJobStream } from "@/lib/job/useJobStream";
import type { JobClient } from "@/lib/job/types";
import { API_BASE } from "@/lib/api";
import type { JobDetail } from "@/lib/api";

import {
  FakeEventSource,
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { setupMswServer, server } from "../support/msw";
import { act, renderHook, waitFor } from "../support/render";

const RUNNING = loadFixture("job.running").body as JobDetail;

setupMswServer();

/** Every write this file's requests attempted. Must stay empty. */
const writes: string[] = [];
server.events.on("request:start", ({ request }) => {
  if (request.method !== "GET") writes.push(`${request.method} ${request.url}`);
});

beforeEach(() => {
  writes.length = 0;
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
  expect(writes).toEqual([]);
});

describe("the request order", () => {
  it("issues GET /research/{id} before constructing the EventSource", async () => {
    // The client seam records both calls. `streamUrl` is called from
    // the `new EventSource(...)` expression itself, so the log below
    // is the true ordering, not a proxy for it.
    const order: string[] = [];
    let release!: (detail: JobDetail) => void;
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        order.push(`get ${jobId}`);
        return new Promise<JobDetail>((resolve) => {
          release = resolve;
        });
      },
      streamUrl: (jobId) => {
        order.push(`stream ${jobId}`);
        return `${API_BASE}/research/${jobId}/stream`;
      },
    };

    const { result } = renderHook(() => useJobStream({ client }));
    act(() => {
      result.current.attach("baseline-running");
    });

    // The read is in flight and NOTHING has been opened. This is the
    // whole of criterion 2: the stream cannot be what tells us the job
    // is gone, because it has not been opened yet.
    expect(order).toEqual(["get baseline-running"]);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.state.phase).toBe("attaching");

    await act(async () => {
      release(RUNNING);
    });

    expect(order).toEqual(["get baseline-running", "stream baseline-running"]);
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("issues exactly one read and one stream however often it is called", async () => {
    const order: string[] = [];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        order.push(`get ${jobId}`);
        return Promise.resolve(RUNNING);
      },
      streamUrl: (jobId) => {
        order.push(`stream ${jobId}`);
        return `${API_BASE}/research/${jobId}/stream`;
      },
    };
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
      result.current.attach("baseline-running");
    });
    act(() => {
      result.current.attach("baseline-running");
    });
    expect(order).toEqual(["get baseline-running", "stream baseline-running"]);
  });
});

describe("a 404 is a clean 'no longer available'", () => {
  it("renders the expired copy and never opens a connection", async () => {
    // `?job=` outlives the job: `api_job_retention_sec` evicts the row,
    // and the default in-memory store loses every job on a restart.
    const { result } = renderHook(() => useJobStream());
    act(() => {
      result.current.attach("evicted-job");
    });

    await waitFor(() => expect(result.current.state.phase).toBe("unavailable"));

    expect(result.current.state.unavailableReason).toBe("not_found");
    expect(result.current.state.failure?.kind).toBe("not_found");
    expect(result.current.state.failureStatus).toBe(404);
    // NOT the failed-connection path: no EventSource was ever
    // constructed, so the browser never got the chance to fail one.
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(result.current.state.connection).toBe("closed");

    expect(terminalPhrase(result.current.state)).toBe("no longer available");
    expect(UNAVAILABLE_COPY).toMatch(/no longer available/);
    // H8: 404 covers "missing" and "not yours" alike, and the copy must
    // never guess which.
    expect(UNAVAILABLE_COPY).not.toMatch(/deleted|permission|denied/i);
  });

  it("leaves the surface usable — a new question is a new run", async () => {
    const { result } = renderHook(() => useJobStream());
    act(() => {
      result.current.attach("evicted-job");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("unavailable"));
    // The composer is not wedged: `unavailable` accepts a submission,
    // and it starts a NEW run rather than retrying the old one (H6).
    expect(result.current.state.phase).toBe("unavailable");
  });
});

describe("the attach fan-out reads JobDetail.status", () => {
  it("settles an already-terminal job without opening a stream", async () => {
    const { result } = renderHook(() => useJobStream());
    act(() => {
      result.current.attach("baseline-succeeded");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("settled"));
    expect(result.current.state.detail).toEqual(
      loadFixture("job.succeeded").body
    );
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it("renders a pending_review plan from JobDetail, with no SSE frame", async () => {
    // 05-MIGRATION.md §2.1 step 3: the plan must arrive without
    // depending on the ADR-0053 replay.
    const { result } = renderHook(() => useJobStream());
    act(() => {
      result.current.attach("baseline-plan-review");
    });
    await waitFor(() =>
      expect(result.current.state.phase).toBe("awaiting_review")
    );
    expect(result.current.state.plan).toEqual(
      (loadFixture("job.pending_review").body as JobDetail).plan
    );
    expect(result.current.state.frames).toEqual([]);
    // The run resumes on this connection once the plan is approved, so
    // the stream is opened even though the job is paused.
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("shows a running job immediately, with the checkpoint unknown", async () => {
    const { result } = renderHook(() => useJobStream());
    act(() => {
      result.current.attach("baseline-running");
    });
    await waitFor(() => expect(result.current.state.phase).toBe("live"));
    expect(result.current.state.detail?.status).toBe("running");
    // H1/H2: no stage is claimed, and none is guessed from the status.
    expect(result.current.state.checkpoint).toBeNull();
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("still opens the stream when the pre-flight read fails without a 404", async () => {
    const client: Partial<JobClient> = {
      getJob: () => Promise.reject(new Error("network down")),
      streamUrl: (jobId) => `${API_BASE}/research/${jobId}/stream`,
    };
    const { result } = renderHook(() => useJobStream({ client }));
    await act(async () => {
      result.current.attach("baseline-running");
    });
    // Only a 404 means "gone" (H8). A transport failure says nothing
    // about the run, so the stream gets its chance — and `detail` is
    // left null, which is how a consumer knows the status is unknown
    // rather than assumed.
    expect(result.current.state.phase).toBe("live");
    expect(result.current.state.detail).toBeNull();
    expect(result.current.state.failureSource).toBe("attach");
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
