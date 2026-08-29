// Pins the landing page's submit → hand-off contract (ADR 0053).
//
// The bug this file exists for: the page POSTed /research, threw the
// accepted job_id away, and pushed a bare `/c/[id]`. The user was
// billed for a planner call and then watched a page that never
// streamed it. The load-bearing assertions here are therefore about
// *counting* — exactly one POST /research per submit — and about the
// pushed URL carrying the job_id.
//
// WO-20 REWROTE THE PAGE UNDER THIS FILE AND LEFT THE FILE'S JOB ALONE.
// `/` is now `JobRunProvider` + `LandingComposer` rather than `QueryForm` and
// a hand-rolled `handleSubmit`, so the labels moved — "Research question" and
// "Generate plan" are 03 §1.4's own words — and refusal is `aria-disabled`
// rather than `disabled`, because a `disabled` button drops out of the tab
// order and takes its own explanation with it (WO-13 criterion 7). Every
// assertion below is the same claim as before against the composed route:
// one thread, one run, in that order, with both ids percent-encoded in the
// pushed URL, and nothing pushed when the submission failed.
//
// `web/tests/features/LandingComposer.test.tsx` makes the same claims one
// layer down, against the component. This file is the ROUTE's copy of them,
// which is what makes criterion 2 a statement about `/` rather than about a
// component that `/` might or might not mount.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// WO-08 moved the page into the `(workspace)` route group. The group adds
// no URL segment — `/` is still `/` — but it does add a path segment, so
// this import moved with the file.
import HomePage from "@/app/(workspace)/page";
import { FAILURE_COPY } from "@/lib/copy/errors";
import { LANDING } from "@/lib/copy/composer";

import {
  installFakeEventSource,
  uninstallFakeEventSource,
} from "./support/FakeEventSource";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), refresh: vi.fn() }),
}));

const originalFetch = globalThis.fetch;

/** Every request the page made, in order, as `METHOD path`. */
let calls: string[] = [];

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/**
 * Route the app's real `lib/api` calls, recording each one.
 *
 * Mocking `fetch` rather than the api module keeps the assertion on
 * the thing that costs money — an HTTP POST to /research — instead of
 * on a JS function nobody is billed for.
 */
function installFetch(overrides: Record<string, () => Response> = {}): void {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const apiPath = url.pathname.replace(/^\/api/, "") || "/";
    const key = `${method} ${apiPath}`;
    calls.push(key);
    const override = overrides[key];
    if (override) return override();
    if (key === "GET /conversations") return jsonResp([]);
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
    // The machine reads the accepted run once it has adopted it. Free and
    // read-only (`routes.py:215-232`); it is not what this file counts.
    if (method === "GET" && apiPath.startsWith("/research/")) {
      return jsonResp({
        // Echoed, not hard-coded: this stub also answers the percent-encoded
        // id, and returning a different one would let the machine adopt a run
        // the submission never accepted.
        job_id: decodeURIComponent(apiPath.slice("/research/".length)),
        status: "pending",
        query: "retrieval augmented verification",
        created_at: 0,
        completed_at: null,
        result: null,
        error: null,
        error_type: null,
        cost_usd: null,
        llm_calls: null,
        iterations: null,
        quality_score: null,
        plan: null,
      });
    }
    throw new Error(`unexpected request: ${key}`);
  }) as unknown as typeof fetch;
}

function countOf(key: string): number {
  return calls.filter((c) => c === key).length;
}

beforeEach(() => {
  calls = [];
  push.mockClear();
  replace.mockClear();
  installFakeEventSource();
  installFetch();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  uninstallFakeEventSource();
});

function submitButton(): HTMLElement {
  return screen.getByRole("button", { name: LANDING.submit });
}

async function submitQuery(query: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(LANDING.questionLabel), query);
  await user.click(submitButton());
}

describe("HomePage submit hand-off (ADR 0053)", () => {
  it("carries the accepted job_id into the run page URL", async () => {
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/c/conv-1?job=job-1");
  });

  it("submits exactly one billed job per click", async () => {
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(countOf("POST /research")).toBe(1);
    expect(countOf("POST /conversations")).toBe(1);
  });

  it("creates the thread before it buys the run, and only then hands off", async () => {
    // MUST-KEEP 1 is an ORDERING as well as a URL shape: the run has to be
    // submitted into a thread that already exists, or the id in the pushed
    // URL names nothing.
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    const writes = calls.filter((call) => call.startsWith("POST "));
    expect(writes).toEqual(["POST /conversations", "POST /research"]);
  });

  it("stays refusing after the hand-off, so a second click cannot double-bill", async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));

    // The redirect is the router's job and does not unmount the page in this
    // test, so this is the real window: `submit()` has resolved, the run is
    // adopted, and the browser has not left `/` yet. The control stays
    // FOCUSABLE and refuses — `aria-disabled`, never `disabled` — so the
    // reason travels with it (WO-13 criterion 7).
    const pendingButton = screen.getByRole("button", {
      name: LANDING.submitPending,
    });
    expect(pendingButton).toHaveAttribute("aria-disabled", "true");
    await user.click(pendingButton);
    expect(countOf("POST /research")).toBe(1);
    expect(countOf("POST /conversations")).toBe(1);
  });

  it("percent-encodes the ids it puts in the URL", async () => {
    installFetch({
      "POST /conversations": () =>
        jsonResp({
          conversation_id: "conv/1 2",
          title: "untitled",
          created_at: 0,
          updated_at: 0,
          jobs: [],
        }),
      "POST /research": () =>
        jsonResp({
          job_id: "job 1",
          status: "pending",
          status_url: "/research/job%201",
          stream_url: "/research/job%201/stream",
        }),
    });
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    expect(push).toHaveBeenCalledWith("/c/conv%2F1%202?job=job%201");
  });

  it("reports a failed submit and does not navigate", async () => {
    installFetch({
      "POST /research": () =>
        jsonResp(
          { detail: { error: "rate_limited", key_id: "local", limit_per_hour: 20 } },
          429,
        ),
    });
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    // The normalized sentence, not the wire body: RC-16 keeps the raw string
    // one disclosure away rather than making it the message.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      FAILURE_COPY.rate_limited.sentence,
    );
    expect(push).not.toHaveBeenCalled();
    // Re-enabled, because there is no run to watch on the other page: the
    // same single control is the manual resubmit, and there is no automatic
    // one anywhere on this path (R-01).
    expect(submitButton()).not.toHaveAttribute("aria-disabled", "true");
  });
});
