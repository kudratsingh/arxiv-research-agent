import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import pathFixture from "@/contract/fixtures/learn.path.detail.json";
import sessionFixture from "@/contract/fixtures/learn.session.awaiting.json";
import {
  GuidedSessionView,
  readSessionTurn,
} from "@/components/patterns/GuidedSessionView";
import type { LearnPathDetail, SessionDetail } from "@/lib/api";
import { LEARN } from "@/lib/copy/learn";

const path = pathFixture.body as LearnPathDetail;
const session = sessionFixture.body as SessionDetail;
const entry = path.entries[0]!;

function view(overrides: Partial<SessionDetail> = {}) {
  const onSubmit = vi.fn();
  render(
    <GuidedSessionView
      session={{ ...session, ...overrides }}
      entry={entry}
      renderer={null}
      machinePhase={
        overrides.status === "succeeded" ? "settled" : "awaiting_learner"
      }
      connection="open"
      response="A response in my own words"
      onResponseChange={vi.fn()}
      onSubmit={onSubmit}
    />
  );
  return onSubmit;
}

describe("GuidedSessionView", () => {
  it("keeps the paper source beside a bounded learner turn", () => {
    const onSubmit = view();
    expect(screen.getByRole("link", { name: LEARN.openPaper })).toHaveAttribute(
      "href",
      entry.canonical_url
    );
    fireEvent.click(screen.getByRole("button", { name: LEARN.submitTurn }));
    expect(onSubmit).toHaveBeenCalledWith(false);
  });

  it("states an unassessed close as a fact, never a score", () => {
    view({
      status: "succeeded",
      turn: null,
      result: "The session closed.",
      assessment_status: "unassessed",
    });
    expect(screen.getByText(LEARN.unassessedBody)).toBeVisible();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("preserves the margin while stating a refused cost-cap call", () => {
    view({
      status: "failed",
      turn: null,
      transcript: [{ role: "learner", text: "My saved observation" }],
      cost_cap_status: "refused",
    });
    expect(screen.getByText("My saved observation")).toBeVisible();
    expect(screen.getByText(LEARN.costCapRefused)).toBeVisible();
  });

  it("shows no assessment block at all when the judge did record one", () => {
    // `assessed` is the one outcome with nothing to announce: the judge ran
    // and the result belongs in the ledger, not in a banner on the reader.
    // The two banners above exist because a MISSING result is the thing worth
    // saying out loud.
    view({
      status: "succeeded",
      turn: null,
      result: "The session closed.",
      assessment_status: "assessed",
    });
    expect(screen.queryByText(LEARN.unassessedHeading)).toBeNull();
    expect(screen.queryByText(LEARN.recordedUngraded)).toBeNull();
  });
});

describe("readSessionTurn", () => {
  const turn = session.turn as Record<string, unknown>;

  it("reads a recorded turn without inventing the optional feedback", () => {
    expect(readSessionTurn({ ...turn, feedback: undefined })).toMatchObject({
      turnNumber: turn.turn_number,
      kind: turn.kind,
      feedback: "",
    });
  });

  it("refuses a turn whose shape the row does not actually carry", () => {
    // A Redis job row can outlive the worker that wrote it, so the payload is
    // `dict[str, Any]` on the wire (`src/api/sessions.py`) and this is the
    // only place that narrows it. Returning null makes the surface fall back
    // to the honest "no turn published yet" line rather than rendering
    // `undefined` at the learner.
    expect(readSessionTurn(null)).toBeNull();
    expect(readSessionTurn({ ...turn, turn_number: "2" })).toBeNull();
    expect(readSessionTurn({ ...turn, kind: 7 })).toBeNull();
    expect(readSessionTurn({ ...turn, prompt: undefined })).toBeNull();
  });
});
