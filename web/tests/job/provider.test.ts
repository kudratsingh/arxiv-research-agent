// `JobRunProvider` (WO-10 acceptance criteria 6, 9 and 10;
// 04-ARCHITECTURE.md §4.1, §4.4; RC-18).
//
// Three things the provider owns and the reducer cannot:
//
//   - the liveness poll, because heartbeats are SSE *comments*
//     (`streaming.py:142`) and are invisible to `EventSource`, so a
//     client cannot tell an idle stream from a dead one;
//   - `pagehide`/`pageshow`, because an open `EventSource` makes
//     `/c/[id]` bfcache-ineligible;
//   - `POST /research`, which is a plain guarded function and must
//     never become a replayable mutation.
//
// `submitResearch` is stubbed in every test in this file and throws if
// anything reaches it unexpectedly. No tier below Playwright may call
// the one billable endpoint on the surface.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createElement } from "react";
import type { ReactNode } from "react";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_POLL,
  JobRunProvider,
  pollIntervalFor,
  useJobRun,
} from "@/lib/job/provider";
import type { JobRunProviderProps } from "@/lib/job/provider";
import { initialJobState } from "@/lib/job/machine";
import type { JobClient } from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";

import {
  allSources,
  installFakeEventSource,
  openSources,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, renderHook } from "../support/render";

const RUNNING = loadFixture("job.running").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;

/** Nothing in this file may reach the billable endpoint. */
function forbiddenSubmit(): never {
  throw new Error("POST /research must never be called from a unit test");
}

function render(props: Omit<JobRunProviderProps, "children">) {
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(JobRunProvider, { ...props, children });
  return renderHook(() => useJobRun(), { wrapper });
}

beforeEach(() => {
  installFakeEventSource();
});

afterEach(() => {
  uninstallFakeEventSource();
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Criterion 6 — the liveness poll.
// ---------------------------------------------------------------------------

describe("the liveness poll", () => {
  it("computes 20 s, then 60 s after five unchanged polls", () => {
    // The rule, before any wiring: §4.4's `refetchInterval: 20_000`
    // backing off to 60 s.
    expect(DEFAULT_POLL.intervalMs).toBe(20_000);
    expect(DEFAULT_POLL.backoffIntervalMs).toBe(60_000);
    expect(DEFAULT_POLL.backoffAfterUnchanged).toBe(5);
    for (const [unchangedPolls, expected] of [
      [0, 20_000],
      [4, 20_000],
      [5, 60_000],
      [12, 60_000],
    ] as const) {
      expect(
        pollIntervalFor({ ...initialJobState, unchangedPolls })
      ).toBe(expected);
    }
  });

  it("re-reads every 20 s and backs off to 60 s, reading only", async () => {
    vi.useFakeTimers();
    const reads: string[] = [];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        reads.push(jobId);
        return Promise.resolve(RUNNING);
      },
      submitResearch: forbiddenSubmit,
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({ jobId: "baseline-running", client });

    await act(async () => {});
    // The attach read. Nothing has been polled yet.
    expect(reads).toHaveLength(1);
    expect(result.current.state.phase).toBe("live");

    // Five polls at 20 s. The attach read is the baseline, so every one
    // of them is unchanged.
    for (let i = 0; i < 5; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(20_000);
      });
    }
    expect(reads).toHaveLength(6);
    expect(result.current.state.unchangedPolls).toBe(5);
    expect(pollIntervalFor(result.current.state)).toBe(60_000);

    // Backed off: 20 s buys nothing now.
    await act(async () => {
      vi.advanceTimersByTime(20_000);
    });
    expect(reads).toHaveLength(6);

    await act(async () => {
      vi.advanceTimersByTime(40_000);
    });
    expect(reads).toHaveLength(7);

    // Read-only throughout: one call, `GET /research/{id}`, no spend.
    expect(new Set(reads)).toEqual(new Set(["baseline-running"]));
  });

  it("stops the moment the run is over", async () => {
    vi.useFakeTimers();
    const reads: string[] = [];
    const details = [RUNNING, SUCCEEDED];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        reads.push(jobId);
        return Promise.resolve(details.shift() ?? SUCCEEDED);
      },
      submitResearch: forbiddenSubmit,
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({ jobId: "baseline-running", client });
    await act(async () => {});
    expect(reads).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(20_000);
    });
    expect(result.current.state.phase).toBe("settled");
    expect(reads).toHaveLength(2);

    await act(async () => {
      vi.advanceTimersByTime(300_000);
    });
    expect(reads).toHaveLength(2);
    // The poll also takes the stream down with it.
    expect(openSources()).toHaveLength(0);
  });

  it("never polls a surface with no job on it", async () => {
    vi.useFakeTimers();
    const reads: string[] = [];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        reads.push(jobId);
        return Promise.resolve(RUNNING);
      },
      submitResearch: forbiddenSubmit,
    };
    render({ jobId: null, client });
    await act(async () => {
      vi.advanceTimersByTime(300_000);
    });
    expect(reads).toEqual([]);
    expect(allSources()).toHaveLength(0);
  });

  it("adds no dependency: the timer is the platform's", () => {
    // TanStack Query is in `package.json` — WO-11 put it there, and
    // `refetchInterval` would indeed be one line. The machine still
    // does not reach for it: the job lifecycle's correctness must not
    // sit downstream of a cache's refetch policy, and WO-11 integrates
    // through the subscribe/getSnapshot seam below instead.
    const source = readFileSync(
      join(process.cwd(), "lib", "job", "provider.tsx"),
      "utf8"
    );
    expect(source).toMatch(/setInterval/);
    // Comments are stripped: the module explains at length why it does
    // not use `refetchInterval`, and a scan that could not tell the
    // explanation from the call would forbid writing the explanation.
    const code = source
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/\/\/.*$/gm, "");
    expect(code).not.toMatch(/@tanstack/);
    expect(code).not.toMatch(/useQuery|refetchInterval/);
  });
});

// ---------------------------------------------------------------------------
// Criterion 10 — POST /research is a guarded plain function.
// ---------------------------------------------------------------------------

describe("POST /research", () => {
  it("is called once however many times submit is invoked in a tick", async () => {
    // R-01: the endpoint has no idempotency key
    // (`routes.py:179-197`), so a double click is a second paid run.
    const posts: string[] = [];
    let release!: (accepted: { job_id: string }) => void;
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(RUNNING),
      submitResearch: (query) => {
        posts.push(query);
        return new Promise((resolve) => {
          release = resolve;
        });
      },
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({ jobId: null, client, autoAttach: false });

    await act(async () => {
      void result.current.submit("what makes agents reliable?");
      void result.current.submit("what makes agents reliable?");
      void result.current.submit("what makes agents reliable?");
    });
    expect(posts).toHaveLength(1);
    expect(result.current.state.phase).toBe("submitting");

    // And again while the first is still in flight, from a later tick.
    await act(async () => {
      void result.current.submit("what makes agents reliable?");
    });
    expect(posts).toHaveLength(1);

    await act(async () => {
      release({ job_id: "baseline-running" });
    });
    expect(posts).toHaveLength(1);
    expect(result.current.state.jobId).toBe("baseline-running");
  });

  it("is a plain function, never a query-library mutation", () => {
    // `networkMode: "online"` pauses a mutation while offline and
    // resumes it on reconnect, which is an automatic replay of a paid
    // submission (H6). The only defence that survives a refactor is
    // that no mutation exists to configure.
    for (const name of ["machine.ts", "types.ts", "useJobStream.ts", "provider.tsx"]) {
      const source = readFileSync(join(process.cwd(), "lib", "job", name), "utf8");
      expect({ name, mutation: /useMutation|mutationFn|@tanstack/.test(source) }).toEqual(
        { name, mutation: false }
      );
    }
  });

  it("a failed submission leaves the surface usable, with no retry", async () => {
    const posts: string[] = [];
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(RUNNING),
      submitResearch: (query) => {
        posts.push(query);
        return Promise.reject(new Error("rate limited"));
      },
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({ jobId: null, client, autoAttach: false });
    await act(async () => {
      await result.current.submit("q");
    });
    expect(result.current.state.phase).toBe("submit_failed");
    expect(result.current.state.failureSource).toBe("submit");
    // Nothing retried it. A second attempt is an explicit user action
    // and starts a NEW run.
    expect(posts).toHaveLength(1);
    await act(async () => {
      await result.current.submit("q");
    });
    expect(posts).toHaveLength(2);
  });

  it("carries the conversation the provider was given", async () => {
    const seen: Array<{ conversation_id?: string }> = [];
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(RUNNING),
      submitResearch: (_query, options) => {
        seen.push(options);
        return Promise.resolve({ job_id: "baseline-running" });
      },
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({
      jobId: null,
      conversationId: "baseline-populated",
      client,
      autoAttach: false,
    });
    await act(async () => {
      await result.current.submit("q");
    });
    expect(seen).toEqual([{ conversation_id: "baseline-populated" }]);
  });
});

// ---------------------------------------------------------------------------
// Criterion 9 — RC-18, bfcache.
// ---------------------------------------------------------------------------

describe("pagehide closes the stream and pageshow re-attaches", () => {
  function bfcacheClient() {
    const streams: string[] = [];
    const reads: string[] = [];
    const client: Partial<JobClient> = {
      getJob: (jobId) => {
        reads.push(jobId);
        return Promise.resolve(RUNNING);
      },
      submitResearch: forbiddenSubmit,
      streamUrl: (jobId) => {
        streams.push(jobId);
        return `/api/research/${jobId}/stream`;
      },
    };
    return { client, streams, reads };
  }

  it("closes the EventSource so the page can enter the cache", async () => {
    const { client, streams } = bfcacheClient();
    const { result } = render({ jobId: "baseline-running", client });
    await act(async () => {});
    expect(openSources()).toHaveLength(1);

    await act(async () => {
      window.dispatchEvent(new Event("pagehide"));
    });

    // An open EventSource is what makes `/c/[id]` bfcache-ineligible.
    expect(openSources()).toHaveLength(0);
    expect(result.current.state.suspended).toBe(true);
    expect(result.current.state.connection).toBe("closed");
    // H2: the connection is gone, so what it observed is not current.
    expect(result.current.state.checkpoint).toBeNull();
    expect(streams).toEqual(["baseline-running"]);
  });

  it("re-attaches the same job on pageshow, preserving ?job=", async () => {
    const { client, streams, reads } = bfcacheClient();
    const { result } = render({ jobId: "baseline-running", client });
    await act(async () => {});

    await act(async () => {
      window.dispatchEvent(new Event("pagehide"));
    });
    await act(async () => {
      window.dispatchEvent(new Event("pageshow"));
    });

    // The same id, GET-first again, and a fresh connection. The machine
    // never writes the URL, so `?job=` is preserved by construction —
    // it is the input, not something re-derived.
    expect(result.current.state.jobId).toBe("baseline-running");
    expect(streams).toEqual(["baseline-running", "baseline-running"]);
    expect(reads).toEqual(["baseline-running", "baseline-running"]);
    expect(openSources()).toHaveLength(1);
    expect(result.current.state.suspended).toBe(false);
    expect(result.current.state.phase).toBe("live");
    // No second POST: `submitResearch` would have thrown.
  });

  it("ignores the pageshow of a normal first load", async () => {
    const { client, streams } = bfcacheClient();
    render({ jobId: "baseline-running", client });
    await act(async () => {});

    await act(async () => {
      window.dispatchEvent(new Event("pageshow"));
    });
    // Nothing was suspended, so nothing is restored — otherwise every
    // cold load would open a second stream.
    expect(streams).toEqual(["baseline-running"]);
    expect(openSources()).toHaveLength(1);
  });

  it("removes its listeners on unmount", async () => {
    const { client, streams } = bfcacheClient();
    const view = render({ jobId: "baseline-running", client });
    await act(async () => {});
    view.unmount();

    await act(async () => {
      window.dispatchEvent(new Event("pagehide"));
      window.dispatchEvent(new Event("pageshow"));
    });
    expect(streams).toEqual(["baseline-running"]);
    expect(openSources()).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// The WO-11 seam.
// ---------------------------------------------------------------------------

describe("the external-store seam WO-11 integrates against", () => {
  it("notifies subscribers and hands them the state they were told about", async () => {
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(RUNNING),
      submitResearch: forbiddenSubmit,
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({ jobId: null, client, autoAttach: false });

    const seen: string[] = [];
    const unsubscribe = result.current.subscribe(() => {
      seen.push(result.current.getSnapshot().phase);
    });

    await act(async () => {
      result.current.attach("baseline-running");
    });
    expect(seen).toContain("live");
    expect(result.current.getSnapshot()).toBe(result.current.state);

    unsubscribe();
    const before = seen.length;
    await act(async () => {
      await result.current.refresh();
    });
    expect(seen).toHaveLength(before);
  });

  it("hands every JobDetail read to onDetail, for a cache to seed from", async () => {
    const observed: string[] = [];
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(RUNNING),
      submitResearch: forbiddenSubmit,
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    const { result } = render({
      jobId: "baseline-running",
      client,
      onDetail: (detail) => observed.push(detail.job_id),
    });
    await act(async () => {});
    await act(async () => {
      await result.current.refresh();
    });
    expect(observed).toEqual(["baseline-running", "baseline-running"]);
  });

  it("refuses to render job state without a provider", () => {
    // A surface reading the machine outside one would show a permanent
    // `idle`, which is a lie that is hard to see.
    expect(() => renderHook(() => useJobRun())).toThrow(/JobRunProvider/);
  });
});
