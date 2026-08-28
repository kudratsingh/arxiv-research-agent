/**
 * WO-13 criterion 5 — `LandingComposer`'s OWN duplicate-submit guard.
 *
 * There are three guards between a click and a second charge on
 * `POST /research`, and `web/tests/features/LandingComposer.test.tsx`
 * exercises them through the real `QueryComposer`, which means it can only
 * ever reach the outermost one: the composer's in-flight ref refuses the
 * second call before `LandingComposer` is asked at all.
 *
 * That is the right ordering and it is also why this file exists. The guard
 * underneath it covers a window nothing else can see — between
 * `POST /conversations` being issued and `POST /research` starting, the job
 * machine is still `idle` and would accept a submission — and it protects a
 * caller that is NOT `QueryComposer`: `LandingComposer` is a public
 * component, and WO-20 composes it. A guard on a non-idempotent, billable
 * endpoint (`routes.py:179-197`) that is only correct because of a *different
 * component's* ref is not a guard, so it is tested against a caller with no
 * ref of its own.
 *
 * The stub is deliberately hostile: one click, two `onSubmit` calls, same
 * tick, no `pending` prop plumbed back. Exactly one thread and exactly one
 * run must come out.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LandingComposer } from "@/components/features/LandingComposer";
import { JobRunProvider } from "@/lib/job/provider";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { render, screen, user } from "../support/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  }),
}));

/**
 * A composer with no guard of its own: one press, two submissions, in one
 * tick. Nothing else about `QueryComposer` matters to this file.
 */
vi.mock("@/components/features/QueryComposer", () => ({
  QueryComposer: ({ onSubmit }: { onSubmit: (query: string) => unknown }) => (
    <button
      type="button"
      onClick={() => {
        void onSubmit("retrieval augmented verification");
        void onSubmit("retrieval augmented verification");
      }}
    >
      submit twice
    </button>
  ),
}));

const originalFetch = globalThis.fetch;
let calls: string[] = [];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

beforeEach(() => {
  calls = [];
  installFakeEventSource();
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname.replace(/^\/api/, "") || "/"}`;
    calls.push(key);
    if (key === "POST /conversations") {
      return jsonResp({
        conversation_id: "conv-1",
        title: "untitled",
        created_at: 0,
        updated_at: 0,
        jobs: [],
      });
    }
    if (key === "POST /research") {
      return jsonResp({
        job_id: "job-1",
        status: "pending",
        status_url: "/research/job-1",
        stream_url: "/research/job-1/stream",
      });
    }
    return jsonResp({
      job_id: "job-1",
      status: "pending",
      result: null,
      error: null,
      error_type: null,
      cost_usd: null,
      llm_calls: null,
      iterations: null,
      quality_score: null,
      plan: null,
      created_at: 0,
      started_at: null,
      completed_at: null,
      elapsed_sec: null,
    });
  }) as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  uninstallFakeEventSource();
});

describe("the guard that does not depend on QueryComposer having one", () => {
  it("buys one thread and one run from two submissions in one tick", async () => {
    render(
      <JobRunProvider>
        <LandingComposer onHandoff={vi.fn()} />
      </JobRunProvider>,
    );

    await user().click(screen.getByRole("button"));

    expect(calls.filter((c) => c === "POST /conversations")).toHaveLength(1);
    expect(calls.filter((c) => c === "POST /research")).toHaveLength(1);
  });
});
