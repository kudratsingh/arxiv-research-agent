// Pins the landing page's submit → hand-off contract (ADR 0053).
//
// The bug this file exists for: the page POSTed /research, threw the
// accepted job_id away, and pushed a bare `/c/[id]`. The user was
// billed for a planner call and then watched a page that never
// streamed it. The load-bearing assertions here are therefore about
// *counting* — exactly one POST /research per submit — and about the
// pushed URL carrying the job_id.

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HomePage from "@/app/page";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), refresh: vi.fn() }),
}));

// The sidebar renders `next/link`; the real component needs an app
// router context this bare render has no reason to build.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
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
  installFetch();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

async function submitQuery(query: string): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText(/research question/i), query);
  await user.click(screen.getByRole("button", { name: /run research/i }));
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

  it("stays busy after submitting, so a second click cannot double-bill", async () => {
    const user = userEvent.setup();
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));

    // The redirect is the router's job and does not unmount the page
    // in this test; the form must stay disabled meanwhile or an
    // impatient second click buys a second planner run.
    const button = screen.getByRole("button", { name: /running…/i });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(countOf("POST /research")).toBe(1);
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
      "POST /research": () => jsonResp({ detail: "rate limited" }, 429),
    });
    render(<HomePage />);
    await submitQuery("retrieval augmented verification");

    expect(await screen.findByRole("alert")).toHaveTextContent(/rate limited/);
    expect(push).not.toHaveBeenCalled();
    // Re-enabled, because there is no job to watch on the other page.
    expect(
      screen.getByRole("button", { name: /run research/i })
    ).toBeEnabled();
  });
});
