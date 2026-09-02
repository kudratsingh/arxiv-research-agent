/**
 * WO-W14 criteria 1, 3 and 4 — the Ledger, over the recorded fixture.
 *
 * Criterion 1 is the one this file exists for: "every rendered claim traces
 * to an event — a test asserts no rendered Ledger row lacks an
 * `evidence_ref`-bearing source event." It is asserted over the DOM rather
 * than over the builders, because a builder that returns honest rows and a
 * component that renders an extra line are two different things and only
 * one of them is what a reader sees.
 *
 * THE DATA IS THE RECORDED CONTRACT FIXTURE, not an invented summary:
 * `contract/fixtures/learn.progress.json` is the verbatim response of the
 * real `/learn/progress` route over the committed raw event log, and
 * `tests/test_progress_events.py::TestContractFixture` keeps the two
 * byte-identical. The hostile cases below are derived FROM it — a null
 * `evidence_ref`, a blank one, a schedule row with no event behind it —
 * so each one differs from the real shape in exactly one respect.
 */

import { describe, expect, it } from "vitest";

import progressFixture from "@/contract/fixtures/learn.progress.json";
import {
  LedgerUnavailable,
  LedgerView,
  evidenceRows,
  scheduleRows,
  withheldCount,
} from "@/components/patterns/LedgerView";
import type { LearnerProgressSummary, ProgressEvidence } from "@/lib/api";
import { LEDGER, scheduleFigure, withheldEvidence } from "@/lib/copy/ledger";

import { render, screen } from "../support/render";

const summary = progressFixture.body as LearnerProgressSummary;

const EMPTY: LearnerProgressSummary = {
  principal_key_id: summary.principal_key_id,
  event_count: 0,
  sessions_per_day: [],
  schedule_progress: [],
  resource_observations: [],
  assessments: [],
  artifacts: [],
};

/** Every event id the summary carries, from every list that names one. */
function everyEventId(source: LearnerProgressSummary): Set<string> {
  return new Set([
    ...source.sessions_per_day.flatMap((day) => day.event_ids),
    ...source.schedule_progress.flatMap((entry) => entry.event_ids),
    ...source.resource_observations.flatMap((entry) => entry.event_ids),
    ...source.assessments.map((event) => event.event_id),
    ...source.artifacts.map((event) => event.event_id),
  ]);
}

/** `event_id` → `evidence_ref`, for the events that carry one. */
function evidenceByEventId(source: LearnerProgressSummary): Map<string, string> {
  const found = new Map<string, string>();
  for (const event of [...source.assessments, ...source.artifacts]) {
    if (typeof event.evidence_ref === "string" && event.evidence_ref !== "") {
      found.set(event.event_id, event.evidence_ref);
    }
  }
  return found;
}

describe("criterion 1 — no rendered row without an event behind it", () => {
  it("gives every evidence row an evidence_ref that came from a real event", () => {
    const { container } = render(<LedgerView summary={summary} />);
    const rows = [...container.querySelectorAll("[data-ledger-row]")];
    const refs = evidenceByEventId(summary);

    // Not vacuous: the fixture has three referenced events and all three
    // are on screen.
    expect(rows).toHaveLength(3);

    for (const row of rows) {
      const ids = (row.getAttribute("data-event-ids") ?? "").split(" ").filter(Boolean);
      const ref = row.getAttribute("data-evidence-ref");

      expect(ids.length, row.outerHTML).toBeGreaterThan(0);
      expect(ref, row.outerHTML).toBeTruthy();
      // The reference is the SOURCE EVENT'S, not one this tier composed.
      expect(ids.map((id) => refs.get(id))).toContain(ref);
      // And the rendered text carries it, so a reader can follow it.
      expect(row.textContent).toContain(ref);
    }
  });

  it("gives every schedule row the events its arithmetic is made of", () => {
    const { container } = render(<LedgerView summary={summary} />);
    const rows = [...container.querySelectorAll("[data-ledger-schedule-row]")];
    const known = everyEventId(summary);

    expect(rows).toHaveLength(summary.schedule_progress.length);
    for (const row of rows) {
      const ids = (row.getAttribute("data-event-ids") ?? "").split(" ").filter(Boolean);
      expect(ids.length, row.outerHTML).toBeGreaterThan(0);
      for (const id of ids) expect(known.has(id), id).toBe(true);
    }
  });

  it("refuses to render an event whose evidence_ref is null or blank", () => {
    const unreferenced: ProgressEvidence[] = [
      {
        event_id: "evt-9001",
        ts: "2026-08-27T10:00:00.000000Z",
        kind: "artifact_produced",
        evidence_ref: null,
        path_id: "attention-is-all-you-need",
      },
      {
        event_id: "evt-9002",
        ts: "2026-08-27T11:00:00.000000Z",
        kind: "assessment",
        evidence_ref: "   ",
        path_id: "attention-is-all-you-need",
      },
    ];
    const hostile: LearnerProgressSummary = {
      ...summary,
      artifacts: [...summary.artifacts, ...unreferenced],
    };

    expect(evidenceRows(hostile).map((row) => row.eventId)).not.toContain("evt-9001");
    expect(evidenceRows(hostile).map((row) => row.eventId)).not.toContain("evt-9002");
    expect(withheldCount(hostile)).toBe(2);

    const { container } = render(<LedgerView summary={hostile} />);
    expect(container.querySelectorAll("[data-ledger-row]")).toHaveLength(3);
    // The schedule row for that path still counts them — they ARE events,
    // and a schedule row's backing set is not an evidence claim. What must
    // not exist is an EVIDENCE row for either of them.
    expect(
      container.querySelector('[data-ledger-row][data-event-ids~="evt-9001"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-ledger-row][data-event-ids~="evt-9002"]'),
    ).toBeNull();
  });

  it("counts what it withheld rather than presenting a filtered log as whole", () => {
    const hostile: LearnerProgressSummary = {
      ...summary,
      artifacts: summary.artifacts.map((event) => ({ ...event, evidence_ref: null })),
    };
    render(<LedgerView summary={hostile} />);
    expect(screen.getByText(withheldEvidence(1) as string)).toBeVisible();
  });

  it("says nothing at all when nothing was withheld", () => {
    const { container } = render(<LedgerView summary={summary} />);
    expect(container.querySelector("[data-ledger-withheld]")).toBeNull();
    expect(withheldEvidence(0)).toBeNull();
  });

  it("drops a schedule row that no event supports", () => {
    const invented: LearnerProgressSummary = {
      ...summary,
      schedule_progress: [
        ...summary.schedule_progress,
        {
          path_id: "a-path-nothing-recorded",
          sessions_completed: 0,
          sessions_planned: 12,
          schedule_label: "0 of 12 sessions",
          assessments_recorded: 0,
          event_ids: [],
        },
      ],
    };
    expect(scheduleRows(invented).map((row) => row.pathId)).not.toContain(
      "a-path-nothing-recorded",
    );
    const { container } = render(<LedgerView summary={invented} />);
    expect(container.textContent).not.toContain("a-path-nothing-recorded");
  });

  it("keeps a path whose only events are its assessments", () => {
    // `eval-harness-basics` has no completed session and one assessment.
    // The row is real — an event named the path — and it must not vanish.
    const row = scheduleRows(summary).find(
      (entry) => entry.pathId === "eval-harness-basics",
    );
    expect(row?.eventIds).toEqual(["evt-0008"]);
  });
});

describe("criterion 3 — schedule arithmetic is labelled as schedule", () => {
  it("renders the label and the figure inside one element", () => {
    const { container } = render(<LedgerView summary={summary} />);
    const figures = [...container.querySelectorAll("[data-ledger-schedule-figure]")];
    expect(figures).toHaveLength(3);
    for (const figure of figures) {
      expect(figure.textContent).toContain(LEDGER.scheduleLabel);
    }
    expect(figures[0]?.textContent).toBe(scheduleFigure("3 of 3 sessions"));
  });

  it("passes the backend's own schedule_label through unedited", () => {
    render(<LedgerView summary={summary} />);
    for (const entry of summary.schedule_progress) {
      expect(screen.getByText(scheduleFigure(entry.schedule_label))).toBeVisible();
    }
  });

  it("names the section as schedule progress and says what it is not", () => {
    render(<LedgerView summary={summary} />);
    expect(
      screen.getByRole("heading", { name: LEDGER.scheduleHeading }),
    ).toBeVisible();
    expect(screen.getByText(LEDGER.scheduleIntro)).toBeVisible();
  });

  it("marks a path with no assessment event unobserved, never as a zero", () => {
    const { container } = render(<LedgerView summary={summary} />);
    const unobserved = container.querySelectorAll(
      '[data-ledger-schedule-row][data-observation="not-observed"]',
    );
    expect(unobserved).toHaveLength(1);
    expect(screen.getByText(LEDGER.notObserved)).toBeVisible();
    expect(screen.getByText(LEDGER.notObservedBody)).toBeVisible();
    // Both markers are rendered, never one: the reader is told which rows
    // were observed AND which were not, rather than inferring the second
    // from a blank (00 §5.4).
    expect(screen.getAllByText(LEDGER.observed)).toHaveLength(2);
    // "0 assessments recorded" is the sentence this avoids.
    expect(container.textContent).not.toContain("0 assessment");
  });
});

describe("criterion 4 — the empty state, and the export that does not exist", () => {
  it("is honest and calm, and states no arithmetic", () => {
    const { container } = render(<LedgerView summary={EMPTY} />);
    expect(screen.getByRole("heading", { name: LEDGER.emptyHeading })).toBeVisible();
    expect(screen.getByText(LEDGER.emptyBody)).toBeVisible();
    expect(container.querySelector("[data-empty-state]")).not.toBeNull();
    expect(container.querySelectorAll("[data-ledger-row]")).toHaveLength(0);
    expect(container.querySelectorAll("[data-ledger-schedule-row]")).toHaveLength(0);
  });

  it("offers no control of any kind while there is nothing to show", () => {
    const { container } = render(<LedgerView summary={EMPTY} />);
    expect(container.querySelectorAll("button, a, [role='button']")).toHaveLength(0);
  });

  it("pretends nothing about exporting the record, in either state", () => {
    for (const state of [EMPTY, summary]) {
      const { container, unmount } = render(<LedgerView summary={state} />);
      expect(container.textContent).not.toMatch(/export|download|share|print|save as/i);
      expect(container.querySelector("a[download]")).toBeNull();
      expect(container.querySelector("form")).toBeNull();
      unmount();
    }
  });
});

describe("the surface's own honesty rules", () => {
  it("states where the page came from without claiming more than the page", () => {
    render(<LedgerView summary={summary} />);
    expect(screen.getByRole("heading", { level: 1, name: LEDGER.heading })).toBeVisible();
    expect(screen.getByText(LEDGER.lead)).toBeVisible();
  });

  it("never renders the principal key, which is identity and not a record", () => {
    const { container } = render(<LedgerView summary={summary} />);
    expect(container.textContent).not.toContain(summary.principal_key_id);
  });

  it("orders the log newest first, and totally", () => {
    const ordered = evidenceRows(summary).map((row) => row.eventId);
    expect(ordered).toEqual(["evt-0008", "evt-0005", "evt-0002"]);

    const sameSecond: LearnerProgressSummary = {
      ...summary,
      artifacts: summary.artifacts.map((event) => ({
        ...event,
        ts: summary.assessments[0]!.ts,
      })),
    };
    expect(evidenceRows(sameSecond).map((row) => row.eventId)).toEqual([
      "evt-0008",
      "evt-0002",
      "evt-0005",
    ]);
  });

  it("renders no date element when the timestamp carries none", () => {
    const undated: LearnerProgressSummary = {
      ...summary,
      assessments: summary.assessments.map((event) => ({ ...event, ts: "" })),
    };
    const { container } = render(<LedgerView summary={undated} />);
    expect(container.querySelectorAll("[data-ledger-row]")).toHaveLength(3);
    // Only the one event that still carries a date renders one. The other
    // two render no date line at all rather than a placeholder.
    expect(container.textContent?.match(/Recorded 20/g) ?? []).toHaveLength(1);
  });

  it("omits the path row for an event that named no path", () => {
    const artifact = summary.artifacts[0]!;
    const pathless: LearnerProgressSummary = {
      ...summary,
      artifacts: [{ ...artifact, path_id: null }],
    };
    const { container } = render(<LedgerView summary={pathless} />);
    const row = container.querySelector(
      `[data-ledger-row][data-event-ids~="${artifact.event_id}"]`,
    );
    expect(row).not.toBeNull();
    expect(row?.textContent).toContain(artifact.evidence_ref);
    expect(row?.textContent).not.toContain(LEDGER.pathLabel);
  });

  it("has an honest unavailable state with an optional retry", () => {
    const { unmount } = render(<LedgerUnavailable />);
    expect(
      screen.getByRole("heading", { name: LEDGER.unavailableHeading }),
    ).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();

    render(<LedgerUnavailable onRetry={() => undefined} />);
    expect(screen.getByRole("button", { name: LEDGER.retry })).toBeVisible();
  });
});
