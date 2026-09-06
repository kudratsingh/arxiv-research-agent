/**
 * WO-S8 — the spine speaks to a researcher.
 *
 * The frontend presentability survey's finding was that the product's most
 * distinctive surface reads as CONNECTION TELEMETRY rather than as research
 * progress, and that in one state it reads as DATA LOSS about a run that
 * worked. This file is that finding turned into assertions. Every test below
 * fails on `origin/main` at 3d0d588; the four they replace or extend are
 * named where they sit.
 *
 * THE ONE DISTINCTION THE WHOLE FILE IS ABOUT. "We did not observe this" and
 * "this did not happen" are different claims. 03 §5.5's qualifiers exist to
 * keep the first one honest — "on this connection" travels with every count,
 * "observed" with every name, "not reported" instead of "unknown" — and the
 * copy this work order replaces made the SECOND claim on the evidence for
 * the first: a succeeded run's spine printed "No longer available" three
 * times and told the reader its plan and checkpoints "are not stored". So
 * these tests are deliberately two-sided. They assert the alarm is gone AND
 * that the qualifiers survive, because a re-voicing that dropped "on this
 * connection" would be a different and worse defect wearing a friendlier
 * tone.
 *
 * WHAT IS NOT ASSERTED HERE, BECAUSE IT WAS CONSIDERED AND REFUSED. The
 * survey proposed re-voicing the four segments toward sub-questions, papers
 * and claims. The spine takes 03 §5.2's four inputs and no others, and the
 * only one of the three that exists in any of them is `plan.sub_questions` —
 * non-null during `pending_review` alone (`schemas.py:98-124`), where the
 * plan editor is already on screen showing every sub-question. There is no
 * paper count and no claim count in `JobDetail` at all. The last test in
 * this file pins that refusal so the next reader of the survey does not have
 * to rediscover it.
 */

import { describe, expect, it } from "vitest";

import { TraceSpine } from "@/components/patterns/TraceSpine";
import { LANDING } from "@/lib/copy/composer";
import { SPINE } from "@/lib/copy/spine";
import {
  RUN_STATUS_LINE,
  RUN_STATUS_WORD,
  SPINE_SEGMENTS,
  UNAVAILABLE_COPY,
} from "@/lib/copy/trace";
import { REPORT } from "@/lib/copy/report";
import { SEGMENT_WORD, SPINE_STATES, describeSpine } from "@/lib/spine/state";

import { render, screen, within } from "../support/render";

import { EVERY_STATE } from "./spineFixtures";

// ---------------------------------------------------------------------------
// 1. The naming split.
// ---------------------------------------------------------------------------

describe("the fourth segment is the Briefing, on every surface that names it", () => {
  it("says Briefing, and nothing anywhere in the spine says Report", () => {
    expect(SPINE_SEGMENTS[3]).toBe("Briefing");
    expect(SPINE_SEGMENTS).not.toContain("Report");
    for (const id of SPINE_STATES) {
      const names = describeSpine(EVERY_STATE[id]).segments.map(
        (segment) => segment.name,
      );
      expect(names, id).toEqual(["Question", "Plan", "Run", "Briefing"]);
    }
  });

  it("matches the two surfaces that had already chosen the word", () => {
    // 03 §1.4's landing legend is the shape `TraceSpine`'s own header says
    // the spine mirrors ("the same shape 03 §1.4's landing legend shows
    // before a question is asked"), and it has said Briefing since WO-13.
    expect(LANDING.process.at(-1)).toBe("Briefing");
    expect(SPINE_SEGMENTS.at(-1)).toBe(LANDING.process.at(-1));
    // And the document that segment points at is headed with the same word.
    expect(REPORT.heading).toBe("Briefing");
    expect(SPINE_SEGMENTS.at(-1)).toBe(REPORT.heading);
  });

  it("renders the word, and keeps the status word beside it unchanged", () => {
    const view = render(<TraceSpine inputs={EVERY_STATE.succeeded} legend="none" />);
    const root = view.container.querySelector("section") as HTMLElement;
    const fourth = root.querySelector('[data-segment="Briefing"]') as HTMLElement;
    expect(fourth).not.toBeNull();
    expect(root.querySelector('[data-segment="Report"]')).toBeNull();
    // Renaming a SEGMENT must not rename a STATUS: 03 §3.4's word column is
    // a different vocabulary and the mark's meaning did not move.
    expect(fourth.textContent).toContain(RUN_STATUS_WORD.succeeded);
    expect(fourth.getAttribute("data-status")).toBe("complete");
    view.unmount();
  });
});

// ---------------------------------------------------------------------------
// 2. The succeeded run that this browser did not watch.
// ---------------------------------------------------------------------------

describe("a succeeded run is reported as a success, not as an absence", () => {
  it("leads with the outcome instead of with what the observer missed", () => {
    const model = describeSpine(EVERY_STATE.historic);
    // The whole defect in one assertion: the announcement for a run whose
    // status is `succeeded` never once said so.
    expect(model.announcement.startsWith(RUN_STATUS_WORD.succeeded)).toBe(true);
    expect(RUN_STATUS_LINE.historic).toBe(model.announcement);
    // And it no longer reports the erasure of a plan that is erased for
    // EVERY run, watched or not (D-010), which is what made this state look
    // degraded beside `succeeded` when it is not.
    expect(model.announcement).not.toMatch(/not stored/i);
    expect(model.announcement).not.toMatch(/\bplan\b/i);
  });

  it("never wears the word an expired run wears", () => {
    const history = describeSpine(EVERY_STATE.historic);
    for (const segment of history.segments) {
      expect(segment.status, segment.name).not.toBe("unavailable");
      expect(segment.word, segment.name).not.toBe(RUN_STATUS_WORD.expired);
    }
    // The word is not retired — a run the server answered 404 for is still
    // the thing it describes, and that state keeps every one of them.
    const gone = describeSpine(EVERY_STATE.expired);
    expect(gone.segments.every((segment) => segment.status === "unavailable")).toBe(
      true,
    );
    expect(gone.announcement).toBe(UNAVAILABLE_COPY);
  });

  it("prints no alarm anywhere in the rendered spine", () => {
    const view = render(<TraceSpine inputs={EVERY_STATE.historic} legend="none" />);
    const root = view.container.querySelector("section") as HTMLElement;
    expect(root.getAttribute("data-spine-state")).toBe("historic");
    // `SEGMENT_WORD.unavailable` is "No longer available". On `origin/main`
    // this string is on screen three times, beside a briefing the reader can
    // open and export.
    expect(root.textContent).not.toContain(SEGMENT_WORD.unavailable);
    expect(within(root).getByRole("status").textContent).toContain(
      RUN_STATUS_WORD.succeeded,
    );
    view.unmount();
  });

  it("still says the observational thing, with 03 §5.5's qualifier on it", () => {
    // The re-voicing is not a softening. The reason the checkpoints are not
    // listed is still stated, and it is still stated as a fact about this
    // connection rather than about the run.
    expect(RUN_STATUS_LINE.historic).toContain("no checkpoints were observed");
    expect(RUN_STATUS_LINE.historic).toContain("on this connection");
    expect(describeSpine(EVERY_STATE.historic).ledger).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// 3. The run in flight.
// ---------------------------------------------------------------------------

describe("a run still under way reports the run before the connection", () => {
  it("opens on the run's own condition, not on the observer's", () => {
    const model = describeSpine(EVERY_STATE.rejoined);
    const [first, second] = model.announcement.split(". ");
    expect(first).toMatch(/\brun\b/i);
    expect(first).not.toMatch(/\brejoined\b/i);
    // H2 is untouched: the second clause is still the honest one about what
    // this connection will and will not show.
    expect(second).toContain("Earlier checkpoints are not replayed");
  });

  it("does not claim the run is progressing, because `pending` reaches here", () => {
    // `spineStateId` routes `pending` and `awaiting_learner` to `rejoined`
    // as readily as `running`, so "still going" — which `recycled` may say,
    // because a recycled stream is by definition a stream — would be an
    // invention here for a run that has not started.
    expect(RUN_STATUS_LINE.rejoined).not.toMatch(/still going|under way|in flight/i);
    expect(RUN_STATUS_LINE.recycled).toContain("The run is still going");
  });

  it("leaves the state where the API has said nothing alone", () => {
    // §4 state C is a different claim — attached, and no status reported —
    // and it was already voiced correctly.
    expect(SPINE.notReportedYet).toBe(
      "Attached to this run. Its status is not reported yet.",
    );
  });
});

// ---------------------------------------------------------------------------
// 4. What a checkpoint label is.
// ---------------------------------------------------------------------------

describe("the ledger's labels are explained rather than translated", () => {
  it("says what kind of word `reader` is, in the legend", () => {
    const view = render(
      <TraceSpine inputs={EVERY_STATE.running_observed} legend="open" />,
    );
    const root = view.container.querySelector("section") as HTMLElement;
    const note = root.querySelector(
      "[data-spine-part='legend-note']",
    ) as HTMLElement;
    expect(note).not.toBeNull();
    expect(note.textContent).toBe(SPINE.ledgerNote);
    expect(note.textContent).toMatch(/\blabel\b/i);
    view.unmount();
  });

  it("does not appear when the composing surface asked for no legend", () => {
    const view = render(
      <TraceSpine inputs={EVERY_STATE.running_observed} legend="none" />,
    );
    const root = view.container.querySelector("section") as HTMLElement;
    expect(root.querySelector("[data-spine-part='legend-note']")).toBeNull();
    view.unmount();
  });

  it("translates nothing: the label on screen is still the frame's, verbatim", () => {
    // THE REFUSAL, PINNED. A node vocabulary in this tier would be a second
    // authority beside the frame, maintained here while `src/graph/` is
    // edited there — and `src/graph/` gained verify, repair, lead, workers,
    // merge and a router in one campaign wave. WO-15 criterion 2 and 03 §1.5
    // forbid it; this test is what stops a future reader of the survey
    // adding one anyway.
    const view = render(
      <TraceSpine inputs={EVERY_STATE.running_observed} legend="none" />,
    );
    const root = view.container.querySelector("section") as HTMLElement;
    const ledger = root.querySelector("ol[data-checkpoint-count]") as HTMLElement;
    const labels = EVERY_STATE.running_observed.observation.checkpoints.map(
      (entry) => entry.node,
    );
    expect(labels.length).toBeGreaterThan(0);
    for (const label of labels) {
      expect(within(ledger).getAllByText(label).length).toBeGreaterThan(0);
    }
    view.unmount();
  });
});

// ---------------------------------------------------------------------------
// 5. The refusal the survey asked about.
// ---------------------------------------------------------------------------

describe("the spine says nothing it does not have an input for", () => {
  it("names no sub-question, paper or claim in any of the twelve states", () => {
    // 03 §5.2's four inputs are status, the observed ledger, the plan and a
    // clock. Papers and claims are in none of them and in no field of
    // `JobDetail`; sub-questions are in the plan, which is non-null only at
    // the review pause, where `PlanEditor` already lists every one of them.
    // A segment named "Papers" would therefore be blank in eleven of twelve
    // states and redundant in the twelfth.
    const forbidden = /\bpapers?\b|\bclaims?\b|\bsub-?questions?\b/i;
    for (const id of SPINE_STATES) {
      const model = describeSpine(EVERY_STATE[id]);
      expect(forbidden.test(model.announcement), `${id}: ${model.announcement}`).toBe(
        false,
      );
      for (const segment of model.segments) {
        expect(forbidden.test(segment.name), id).toBe(false);
        expect(forbidden.test(segment.word), id).toBe(false);
      }
    }
  });

  it("keeps the count honest wherever it prints one", () => {
    const model = describeSpine(EVERY_STATE.running_observed);
    expect(model.detail).not.toBeNull();
    expect(model.detail as string).toContain("on this connection");
    expect(SPINE.ledgerLabel).toContain("on this connection");
  });
});

// ---------------------------------------------------------------------------

describe("the region is still one status, one region, one legend", () => {
  it("adds no second live region and no second landmark", () => {
    render(<TraceSpine inputs={EVERY_STATE.historic} legend="open" />);
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getAllByRole("region")).toHaveLength(1);
  });
});
