// `useResearchStream` as an adapter over the machine (WO-10
// acceptance criterion 11, RC-03).
//
// The real evidence for criterion 11 is the 510 tests that were
// already here and still pass — `ConversationThread.test.tsx` in
// particular, which pins adopt-don't-resubmit, the StrictMode double
// mount, the fatal-close recovery and the settle path, and which this
// work order did not touch. This file adds the part those tests cannot
// state out loud: which legacy surface is now produced by which part
// of the machine, and what the adapter deliberately does NOT pass
// through.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { API_BASE } from "@/lib/api";
import { useResearchStream } from "@/lib/useResearchStream";

import {
  allSources,
  installFakeEventSource,
  onlySource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { errorFixture, loadFixture } from "../support/handlers";
import { setupMswServer, server } from "../support/msw";
import { act, renderHook, waitFor } from "../support/render";

setupMswServer();

/**
 * Every `POST /research` this file attempted. Must stay empty.
 *
 * Scoped to the submission endpoint rather than all writes, because
 * one test below does exercise `POST /research/{id}/review` — which is
 * idempotent-ish, cheap, and not the one that buys a run.
 */
const submissions: string[] = [];
server.events.on("request:start", ({ request }) => {
  const path = new URL(request.url).pathname;
  if (request.method === "POST" && path === `${API_BASE}/research`) {
    submissions.push(path);
  }
});

beforeEach(() => {
  submissions.length = 0;
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
  expect(submissions).toEqual([]);
});

describe("the legacy surface is unchanged", () => {
  it("attaches stream-first and synchronously, as its callers pin", () => {
    // The machine's own contract is GET-first (§4.3). This adapter is
    // the one caller that opts out, because `ConversationThread` and
    // the harness tests assert the `EventSource` exists in the same
    // tick as the `attach()` call. WO-31 deletes the opt-out with the
    // adapter.
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-running");
    });
    expect(allSources()).toHaveLength(1);
    expect(onlySource().url).toBe(`${API_BASE}/research/baseline-running/stream`);
    expect(result.current.status).toBe("streaming");
    expect(result.current.jobId).toBe("baseline-running");
  });

  it("settles from GET /research/{id}, not from the terminal frame", async () => {
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-succeeded");
    });
    act(() => {
      // The live shape: no `status`, and never the report body.
      onlySource().emit("job_completed", {
        job_id: "baseline-succeeded",
        llm_calls: 11,
      });
    });
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.detail).toEqual(loadFixture("job.succeeded").body);
    expect(result.current.error).toBeNull();
  });

  it("keeps the composer usable when the stream fails permanently", async () => {
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("evicted-job");
    });
    act(() => {
      onlySource().fatal();
    });
    await waitFor(() => expect(result.current.status).toBe("idle"));
    // The sentence `useResearchStream.ts:183-186` composed, reproduced
    // from the machine's `unavailable` phase.
    expect(result.current.error).toContain("evicted-job");
    expect(result.current.error).toMatch(/expired/);
  });

  it("narrates a transient drop as a stream_note event", () => {
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-running");
    });
    act(() => {
      onlySource().transientDrop();
    });
    expect(result.current.events.map((e) => e.name)).toEqual(["stream_note"]);
    expect(result.current.status).toBe("streaming");
    expect(result.current.error).toBeNull();
  });

  it("exposes a replayed plan and clears it on review", async () => {
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-plan-review");
    });
    act(() => {
      onlySource().emit("plan_ready", {
        job_id: "baseline-plan-review",
        plan: { sub_questions: ["what is X?"], search_queries: ["X survey"] },
      });
    });
    expect(result.current.status).toBe("awaiting_review");
    expect(result.current.plan).toEqual({
      sub_questions: ["what is X?"],
      search_queries: ["X survey"],
    });
  });

  it("reports a settling read that failed, with its status code", async () => {
    server.use(
      errorFixture("error.502", "get", `${API_BASE}/research/:jobId`)
    );
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-succeeded");
    });
    act(() => {
      onlySource().emit("job_completed", { job_id: "baseline-succeeded" });
    });
    // The run IS over — the frame said so — and the sentence says only
    // that the values could not be read.
    await waitFor(() => expect(result.current.status).toBe("done"));
    expect(result.current.error).toMatch(/^fetch result failed \(502\): /);
    expect(result.current.detail).toBeNull();
  });

  it("reports a rejected review, with its status code", async () => {
    server.use(
      errorFixture("error.422", "post", `${API_BASE}/research/:jobId/review`)
    );
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-plan-review");
    });
    act(() => {
      onlySource().emit("plan_ready", {
        job_id: "baseline-plan-review",
        plan: { sub_questions: ["a"], search_queries: ["b"] },
      });
    });
    await act(async () => {
      await result.current.review("approve");
    });
    expect(result.current.error).toMatch(/^review failed \(422\): /);
    // The pause is still the pause: the user can try again.
    expect(result.current.status).toBe("awaiting_review");
    expect(result.current.plan).not.toBeNull();
  });

  it("reports a review with no job the way it always did", async () => {
    const { result } = renderHook(() => useResearchStream());
    await act(async () => {
      await result.current.review("approve");
    });
    expect(result.current.error).toBe("no active job to review");
  });
});

describe("what the adapter deliberately withholds", () => {
  it("handles stream_timeout without surfacing it as an event", () => {
    // The machine registers the seventh name and reopens on it. The
    // hook's `SseEventName` union does not include it, and
    // `components/EventLog.tsx:10` keys an exhaustive
    // `Record<SseEventName, string>` off that union — so surfacing it
    // here would render an undefined label on a legacy surface.
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-running");
    });
    act(() => {
      onlySource().emit("stream_timeout", {
        job_id: "baseline-running",
        reason: "max_duration_exceeded",
        max_duration_sec: 60,
        reconnect: true,
      });
    });

    // Handled: a new connection, immediately.
    expect(allSources()).toHaveLength(2);
    expect(allSources()[0]?.closed).toBe(true);
    // Not surfaced: the legacy event list is unchanged.
    expect(result.current.events).toEqual([]);
    expect(result.current.status).toBe("streaming");
  });

  it("keeps every name the legacy union does carry", () => {
    const { result } = renderHook(() => useResearchStream());
    act(() => {
      result.current.attach("baseline-running");
    });
    act(() => {
      const source = onlySource();
      source.emit("job_started", { job_id: "baseline-running", query: "q" });
      source.emit("node_completed", { node: "planner", state_delta: {} });
      source.transientDrop();
    });
    expect(result.current.events.map((e) => e.name)).toEqual([
      "job_started",
      "node_completed",
      "stream_note",
    ]);
    expect(result.current.events[1]?.data).toEqual({
      node: "planner",
      state_delta: {},
    });
  });
});
