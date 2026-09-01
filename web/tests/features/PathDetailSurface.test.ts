import { describe, expect, it } from "vitest";

import progressFixture from "@/contract/fixtures/learn.progress.json";
import { resourceObservationsFromEvents } from "@/components/features/PathDetailSurface";
import type { LearnerProgressSummary } from "@/lib/api";

const progress = progressFixture.body as LearnerProgressSummary;

describe("path position provenance", () => {
  it("returns no observations when no event summary names the path", () => {
    expect(resourceObservationsFromEvents(progress, "fixture-guided-read")).toEqual([]);
  });

  it("uses only resource observations folded from progress events", () => {
    expect(
      resourceObservationsFromEvents(progress, "attention-is-all-you-need").map(
        (observation) => observation.resource_id
      )
    ).toEqual([
      "arxiv:1706.03762",
      "arxiv:1810.04805",
      "arxiv:2305.18290",
    ]);
  });

  it("returns no observations when the progress endpoint is unavailable", () => {
    expect(resourceObservationsFromEvents(undefined, "attention-is-all-you-need")).toEqual([]);
  });
});
