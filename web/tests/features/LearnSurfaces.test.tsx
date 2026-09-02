import { QueryClient } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import listFixture from "@/contract/fixtures/learn.paths.json";
import progressFixture from "@/contract/fixtures/learn.progress.json";
import { QueryProvider } from "@/app/providers";
import { LearnLandingEntry } from "@/components/features/LearnLandingEntry";
import { PathDetailSurface } from "@/components/features/PathDetailSurface";
import { PathList } from "@/components/features/PathList";
import { PathListSurface } from "@/components/features/PathListSurface";
import { LEARN } from "@/lib/copy/learn";
import type { LearnPathList } from "@/lib/api";

import { render, screen, waitFor } from "../support/render";

// WO-W13b: `PathDetailSurface` now owns a write and routes on success, so it
// reads `useRouter`. Nothing here starts a session — that flow is
// `tests/features/PathDetailSurfaceStart.test.tsx` — but the hook still has to
// be mounted for the surface to render at all.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    refresh: vi.fn(),
  }),
}));

const originalFetch = globalThis.fetch;
const pathList = listFixture.body as LearnPathList;

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

describe("the learning landing entry", () => {
  it("links the existing workspace landing page to the path library", () => {
    render(<LearnLandingEntry />);
    expect(
      screen.getByRole("heading", { name: LEARN.landingHeading })
    ).toBeVisible();
    expect(screen.getByRole("link", { name: LEARN.landingAction })).toHaveAttribute(
      "href",
      "/learn"
    );
  });
});

describe("the path list surface", () => {
  it("renders a bounded loading state", () => {
    vi.mocked(globalThis.fetch).mockReturnValue(new Promise(() => undefined));
    renderWithQuery(<PathListSurface />);
    expect(screen.getByText(LEARN.listLoading)).toHaveAttribute("aria-busy", "true");
  });

  it("renders the recorded fixture and its honest label", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response(listFixture.body));
    renderWithQuery(<PathListSurface />);
    expect(
      await screen.findByRole("heading", { name: LEARN.listHeading })
    ).toBeVisible();
    expect(screen.getByText(LEARN.fixtureLabel)).toBeVisible();
    expect(screen.getByRole("link", { name: LEARN.openPath })).toHaveAttribute(
      "href",
      "/learn/paths/fixture-guided-read"
    );
  });

  it("does not label a reviewed path as fixture content", () => {
    const reviewed = { ...pathList.paths[0]!, fixture: false, banner: null };
    render(<PathList paths={[reviewed]} />);
    expect(screen.queryByText(LEARN.fixtureLabel)).toBeNull();
  });

  it("distinguishes an empty library from a failed read", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(response({ paths: [] }));
    renderWithQuery(<PathListSurface />);
    expect(await screen.findByText(LEARN.listEmptyBody)).toBeVisible();
    expect(screen.queryByText(LEARN.pathUnavailableBody)).toBeNull();
  });

  it("renders the unavailable state and retries only the idempotent read", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValue(
      response({ detail: "learn_content_disabled" }, 404)
    );
    renderWithQuery(<PathListSurface />);
    const retry = await screen.findByRole("button", { name: LEARN.retry });
    await userEvent.click(retry);
    await waitFor(() => expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(2));
  });
});

describe("the path detail surface", () => {
  it("renders content-only when progress is unavailable", async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) => {
      const url = String(input);
      return Promise.resolve(
        url.endsWith("/progress")
          ? response({ detail: "learner_profile_disabled" }, 404)
          : response(detailFixture.body)
      );
    });
    renderWithQuery(<PathDetailSurface pathId="fixture-guided-read" />);
    expect(await screen.findByText(LEARN.noProgress)).toBeVisible();
    expect(document.querySelectorAll('[data-observation="observed"]')).toHaveLength(0);
  });

  it("renders only the position folded from recorded events", async () => {
    const eventSummary = {
      ...progressFixture.body,
      schedule_progress: [
        {
          path_id: "fixture-guided-read",
          sessions_completed: 2,
          sessions_planned: 3,
          schedule_label: "2 of 3 sessions",
          assessments_recorded: 0,
          event_ids: ["evt-1", "evt-2"],
        },
      ],
      resource_observations: detailFixture.body.entries.slice(0, 2).map(
        (entry, index) => ({
          path_id: "fixture-guided-read",
          resource_id: entry.resource_id,
          sessions_completed: 1,
          last_observed_at: `2026-08-2${index + 4}T09:00:00.000000Z`,
          event_ids: [`evt-${index + 1}`],
        })
      ),
    };
    vi.mocked(globalThis.fetch).mockImplementation((input) =>
      Promise.resolve(
        String(input).endsWith("/progress")
          ? response(eventSummary)
          : response(detailFixture.body)
      )
    );
    renderWithQuery(<PathDetailSurface pathId="fixture-guided-read" />);
    await screen.findByText(LEARN.progressSource);
    expect(document.querySelectorAll('[data-observation="observed"]')).toHaveLength(2);
    expect(document.querySelectorAll('[data-observation="not-observed"]')).toHaveLength(1);
    for (const [input] of vi.mocked(globalThis.fetch).mock.calls) {
      expect(String(input)).not.toMatch(/\/pdf\/|full.?text/i);
    }
  });

  it("does not hide a content failure behind the independent progress read", async () => {
    vi.mocked(globalThis.fetch).mockImplementation((input) =>
      Promise.resolve(
        String(input).endsWith("/progress")
          ? response(progressFixture.body)
          : response({ detail: "learn_content_disabled" }, 404)
      )
    );
    renderWithQuery(<PathDetailSurface pathId="fixture-guided-read" />);
    expect(
      await screen.findByRole("heading", { name: LEARN.pathUnavailableHeading })
    ).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: LEARN.retry }));
    await waitFor(() => expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(3));
  });
});
