import { describe, expect, it } from "vitest";

import sessionFixture from "@/contract/fixtures/learn.session.awaiting.json";
import type { SessionDetail } from "@/lib/api";
import { sessionAsJobDetail } from "@/lib/job/session";

describe("sessionAsJobDetail", () => {
  it("keeps server status and identity while inventing no research metrics", () => {
    const session = sessionFixture.body as SessionDetail;
    const job = sessionAsJobDetail(session);

    expect(job).toMatchObject({
      job_id: session.session_id,
      status: "awaiting_learner",
      kind: "session",
      query: session.title,
      plan: null,
      iterations: null,
      quality_score: null,
    });
  });
});
