// `/learn/progress` — the reading ledger (WO-W14).
//
// A mount point for `LedgerSurface`, which owns the fetch and the
// unavailable state. The route is reachable only from the path library's
// one link: 00 §5.5 allows four surfaces, not a second navigation row.

import { LedgerSurface } from "@/components/features/LedgerSurface";

/** The `/learn/progress` route entry. */
export default function LearnProgressPage() {
  return <LedgerSurface />;
}
