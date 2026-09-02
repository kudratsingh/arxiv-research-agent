/**
 * WO-W14 — the fetching half of the Ledger, over the recorded fixture.
 *
 * `LedgerView.test.tsx` proves what the PATTERN renders from a summary.
 * This is the other half: that the summary arrives from `/api/learn/progress`
 * through the query layer, that the two non-content states are honest about
 * which one they are, and that the pattern's own empty state — not a
 * request-level message — is what a reader sees when the ledger is empty.
 *
 * The proxy is the only origin any of it may reach (04 §7.2), so the URL is
 * asserted rather than assumed.
 */

import { QueryClient } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import progressFixture from "@/contract/fixtures/learn.progress.json";
import { QueryProvider } from "@/app/providers";
import { LedgerSurface } from "@/components/features/LedgerSurface";
import { LEDGER } from "@/lib/copy/ledger";
import type { LearnerProgressSummary } from "@/lib/api";

import { render, screen, user, waitFor } from "../support/render";

const originalFetch = globalThis.fetch;
const summary = progressFixture.body as LearnerProgressSummary;

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function renderWithQuery(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryProvider client={client}>{node}</QueryProvider>);
}

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("the Ledger surface", () => {
  it("renders a bounded loading state rather than an empty page", () => {
    vi.mocked(globalThis.fetch).mockReturnValue(new Promise(() => undefined));
    renderWithQuery(<LedgerSurface />);
    expect(screen.getByText(LEDGER.loading)).toHaveAttribute("aria-busy", "true");
  });

  it("reads the record through the same-origin proxy and renders its rows", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(progressFixture.body));
    const { container } = renderWithQuery(<LedgerSurface />);

    expect(
      await screen.findByRole("heading", { level: 1, name: LEDGER.heading }),
    ).toBeVisible();
    expect(container.querySelectorAll("[data-ledger-row]")).toHaveLength(3);
    expect(container.querySelectorAll("[data-ledger-schedule-row]")).toHaveLength(
      summary.schedule_progress.length,
    );

    const [url] = vi.mocked(globalThis.fetch).mock.calls[0] as [string | URL];
    expect(String(url)).toContain("/api/learn/progress");
  });

  it("shows the pattern's empty state, not an error, for an empty record", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({
        principal_key_id: "pilot-01",
        event_count: 0,
        sessions_per_day: [],
        schedule_progress: [],
        resource_observations: [],
        assessments: [],
        artifacts: [],
      }),
    );
    renderWithQuery(<LedgerSurface />);
    expect(
      await screen.findByRole("heading", { name: LEDGER.emptyHeading }),
    ).toBeVisible();
    expect(screen.queryByText(LEDGER.unavailableBody)).toBeNull();
  });

  it("is honest when the record cannot be read, and retries on request", async () => {
    // The learner-profile flag is off by default, so 404 is the ordinary
    // answer here rather than an incident.
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({ detail: "learner_profile_disabled" }, 404),
    );
    renderWithQuery(<LedgerSurface />);

    expect(
      await screen.findByRole("heading", { name: LEDGER.unavailableHeading }),
    ).toBeVisible();
    const calls = vi.mocked(globalThis.fetch).mock.calls.length;

    vi.mocked(globalThis.fetch).mockResolvedValue(response(progressFixture.body));
    await user().click(screen.getByRole("button", { name: LEDGER.retry }));

    await waitFor(() => {
      expect(vi.mocked(globalThis.fetch).mock.calls.length).toBeGreaterThan(calls);
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: LEDGER.heading }),
    ).toBeVisible();
  });

  it("offers nothing that pretends the record can be exported", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(progressFixture.body));
    const { container } = renderWithQuery(<LedgerSurface />);
    await screen.findByRole("heading", { level: 1, name: LEDGER.heading });
    expect(container.textContent).not.toMatch(/export|download|share|print/i);
    expect(container.querySelector("a[download]")).toBeNull();
  });
});
