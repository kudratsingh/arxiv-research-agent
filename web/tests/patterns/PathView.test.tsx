import { describe, expect, it } from "vitest";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import { PathUnavailable, PathView } from "@/components/patterns/PathView";
import type { LearnPathDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

import { render, screen } from "../support/render";

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

  it("has an honest unavailable state", () => {
    render(<PathUnavailable />);
    expect(
      screen.getByRole("heading", { name: LEARN.pathUnavailableHeading })
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
