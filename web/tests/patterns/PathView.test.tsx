import { describe, expect, it, vi } from "vitest";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import { PathUnavailable, PathView } from "@/components/patterns/PathView";
import type { LearnPathDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import { render, screen, user } from "../support/render";

const path = detailFixture.body as LearnPathDetail;

describe("PathView", () => {
  it("labels the fixture and renders content-only when no events are available", () => {
    const { container } = render(<PathView path={path} />);
    expect(screen.getByText(LEARN.fixtureLabel)).toBeVisible();
    expect(screen.getByText(LEARN.noProgress)).toBeVisible();
    expect(container.querySelectorAll('[data-observation="not-observed"]')).toHaveLength(3);
    expect(container.querySelectorAll('[data-observation="observed"]')).toHaveLength(0);
  });

  it("marks only the entries supported by the event-derived position", () => {
    const observations = path.entries.slice(0, 2).map((entry, index) => ({
      path_id: path.path_id,
      resource_id: entry.resource_id,
      sessions_completed: 1,
      last_observed_at: `2026-08-2${index + 4}T09:00:00.000000Z`,
      event_ids: [`evt-${index + 1}`],
    }));
    const { container } = render(
      <PathView path={path} observations={observations} />
    );
    expect(container.querySelectorAll('[data-observation="observed"]')).toHaveLength(2);
    expect(container.querySelectorAll('[data-observation="not-observed"]')).toHaveLength(1);
    expect(screen.getByText(LEARN.progressSource)).toBeVisible();
  });

  it("links only to arXiv abstract pages and renders no paper body", () => {
    const { container } = render(<PathView path={path} />);
    const paperLinks = screen.getAllByRole("link", { name: LEARN.openPaper });
    expect(paperLinks).toHaveLength(3);
    for (const link of paperLinks) {
      expect(link).toHaveAttribute("href", expect.stringMatching(/^https:\/\/arxiv\.org\/abs\//));
      expect(link.getAttribute("href")).not.toMatch(/\/pdf\/|full.?text/i);
    }
    expect(container.textContent).not.toContain(path.entries[0]?.briefing_markdown);
    expect(container.querySelector("iframe, embed, object")).toBeNull();
  });

  it("states when an entry has no briefing and omits an empty vocabulary block", () => {
    const entry = path.entries[0]!;
    const sparsePath: LearnPathDetail = {
      ...path,
      fixture: false,
      banner: null,
      entry_count: 1,
      entries: [{ ...entry, briefing_markdown: null, vocabulary: [] }],
    };

    render(<PathView path={sparsePath} />);
    expect(screen.getByText(LEARN.briefingUnavailable)).toBeVisible();
    expect(screen.queryByText(LEARN.vocabulary)).toBeNull();
    expect(screen.queryByText(LEARN.fixtureLabel)).toBeNull();
  });

  it("has an honest unavailable state", () => {
    render(<PathUnavailable />);
    expect(
      screen.getByRole("heading", { name: LEARN.pathUnavailableHeading })
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// WO-W13b — the start affordance.
//
// The pattern never fetches, so every state here is a prop. That is what
// makes "no start control without a handler" assertable at all: the surface
// cannot offer a write it has no way to issue.
// ---------------------------------------------------------------------------

describe("PathView start action", () => {
  const first = path.entries[0]!;

  it("renders no start control when no handler is supplied", () => {
    const { container } = render(<PathView path={path} />);
    expect(container.querySelectorAll("[data-start-session]")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: LEARN.startSession })).toBeNull();
  });

  it("offers one start control per entry, described by that entry's title", () => {
    render(<PathView path={path} onStartSession={() => undefined} />);
    const buttons = screen.getAllByRole("button", { name: LEARN.startSession });
    expect(buttons).toHaveLength(path.entries.length);
    expect(buttons[0]).toHaveAccessibleDescription(first.title);
  });

  it("hands the whole entry to the handler, so the feature invents no id", async () => {
    const onStartSession = vi.fn();
    render(<PathView path={path} onStartSession={onStartSession} />);
    await user().click(
      screen.getAllByRole("button", { name: LEARN.startSession })[0]!
    );
    expect(onStartSession).toHaveBeenCalledTimes(1);
    expect(onStartSession).toHaveBeenCalledWith(first);
  });

  it("marks the started entry busy and the rest unavailable, with no progress claim", () => {
    const { container } = render(
      <PathView
        path={path}
        onStartSession={() => undefined}
        startingResourceId={first.resource_id}
      />
    );
    const started = screen.getByRole("button", { name: LEARN.startingSession });
    expect(started).toHaveAttribute("aria-busy", "true");
    expect(started).toHaveAttribute("aria-disabled", "true");

    const others = screen.getAllByRole("button", { name: LEARN.startSession });
    expect(others).toHaveLength(path.entries.length - 1);
    for (const button of others) {
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toHaveAttribute("aria-busy", "true");
    }
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(container.textContent ?? "").not.toMatch(/%/);
  });

  it("refuses the click while a start is outstanding", async () => {
    const onStartSession = vi.fn();
    render(
      <PathView
        path={path}
        onStartSession={onStartSession}
        startingResourceId={first.resource_id}
      />
    );
    await user().click(
      screen.getByRole("button", { name: LEARN.startingSession })
    );
    await user().click(
      screen.getAllByRole("button", { name: LEARN.startSession })[0]!
    );
    expect(onStartSession).not.toHaveBeenCalled();
  });

  it("renders a refusal on the refused entry only", () => {
    const { container } = render(
      <PathView
        path={path}
        onStartSession={() => undefined}
        startRefusal={{
          resourceId: first.resource_id,
          message: LEARN.startRefusedDisabled,
          detail: null,
        }}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedHeading);
    expect(alert).toHaveTextContent(LEARN.startRefusedDisabled);
    expect(
      container.querySelectorAll(`[data-start-refusal="${first.resource_id}"]`)
    ).toHaveLength(1);
    expect(container.querySelectorAll("[data-start-refusal]")).toHaveLength(1);
    // Nothing else on the path is affected by one entry's refusal.
    expect(
      screen.getAllByRole("button", { name: LEARN.startSession })
    ).toHaveLength(path.entries.length);
  });

  it("shows the service's own word verbatim when the refusal is unmapped", () => {
    render(
      <PathView
        path={path}
        onStartSession={() => undefined}
        startRefusal={{
          resourceId: first.resource_id,
          message: LEARN.startRefusedGeneric,
          detail: "some_code_from_the_service",
        }}
      />
    );
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(LEARN.startRefusedDetail);
    expect(alert).toHaveTextContent("some_code_from_the_service");
  });

  it("omits the service-detail block when there is nothing to quote", () => {
    render(
      <PathView
        path={path}
        onStartSession={() => undefined}
        startRefusal={{
          resourceId: first.resource_id,
          message: LEARN.startRefusedGeneric,
          detail: null,
        }}
      />
    );
    expect(screen.queryByText(LEARN.startRefusedDetail)).toBeNull();
  });
});
