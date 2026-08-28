/**
 * NEGATIVE fixture for the primitives/no-data-layer ESLint rule (WO-07
 * criterion 1).
 *
 * This file MUST fail `eslint`. web/tests/primitives/boundary.test.tsx lints
 * it and asserts one `no-restricted-imports` error per import below, which
 * is what proves the rule actually fires rather than merely being
 * configured. It stands in for a primitive that reached for the data layer:
 * the client, an error helper, the SSE hook, and MSW in what would be its
 * story.
 *
 * It is never imported by application code, and `npm run lint` walks only
 * app/ components/ lib/, so the repository lint stays green. Do not "fix"
 * the imports below.
 */

import { getJob } from "@/lib/api";
import { normalizeFailure } from "@/lib/api/errors";
import { useResearchStream } from "@/lib/useResearchStream";
import { http } from "msw";

export function PrimitiveBoundaryFixture() {
  const stream = useResearchStream();
  void getJob;
  void normalizeFailure;
  void http;
  return <div>{stream.status}</div>;
}
