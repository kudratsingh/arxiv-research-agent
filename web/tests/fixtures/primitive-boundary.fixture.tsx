/**
 * NEGATIVE fixture for the primitives/no-data-layer ESLint rule (WO-07
 * criterion 1).
 *
 * This file MUST fail `eslint`. web/tests/primitives/boundary.test.tsx lints
 * it and asserts one `no-restricted-imports` error per import below, which
 * is what proves the rule actually fires rather than merely being
 * configured. It stands in for a primitive that reached for the data layer:
 * the client, an error helper, a fetching hook, and MSW in what would be its
 * story.
 *
 * WO-31 SWAPPED THE THIRD IMPORT. It used to be `useResearchStream`, the
 * RC-03 adapter; that module is deleted, and the fetching hook a primitive
 * would reach for today is `@tanstack/react-query`'s — which the same
 * restricted group already names. The fixture still carries exactly four
 * restricted imports and still means the four ways a primitive reaches the
 * network.
 *
 * It is never imported by application code, and `npm run lint` walks only
 * app/ components/ lib/ and middleware.ts, so the repository lint stays
 * green. Do not "fix" the imports below.
 */

import { useQuery } from "@tanstack/react-query";
import { getJob } from "@/lib/api";
import { normalizeFailure } from "@/lib/api/errors";
import { http } from "msw";

export function PrimitiveBoundaryFixture() {
  const query = useQuery({ queryKey: ["job"], queryFn: () => getJob("job-1") });
  void normalizeFailure;
  void http;
  return <div>{query.status}</div>;
}
