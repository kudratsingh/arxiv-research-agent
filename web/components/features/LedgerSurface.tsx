"use client";

/**
 * LedgerSurface — the fetching half of `/learn/progress` (WO-W14).
 *
 * The split is `04-ARCHITECTURE.md` §5.1's and `PathDetailSurface`'s,
 * followed to the letter: the pattern takes the summary as a prop and can
 * be driven to every state from a story with no network; this component is
 * the only one that knows the record is read over HTTP. It reads through
 * `lib/queries/learn.ts` → `lib/api` → `/api`, the same-origin proxy — no
 * component in this tree ever sees `API_INTERNAL_BASE`.
 *
 * Three states, all of them honest about which one they are: bounded
 * loading with `aria-busy`, the unavailable surface with a retry (the
 * learner-profile flag is off by default, so a 404 here is the ordinary
 * case rather than an incident), and the record itself — whose own empty
 * state lives in the pattern, because "no sessions yet" is a fact about the
 * ledger and not a fact about the request.
 */

import { LedgerUnavailable, LedgerView } from "@/components/patterns/LedgerView";
import { LEDGER } from "@/lib/copy/ledger";
import { useLearnerProgress } from "@/lib/queries/learn";

export function LedgerSurface() {
  const progress = useLearnerProgress();

  if (progress.isPending) {
    return (
      <div
        aria-busy="true"
        className="mx-auto flex h-full w-full max-w-content items-center px-6 py-10 text-ui-sm text-ink-muted"
      >
        {LEDGER.loading}
      </div>
    );
  }

  if (progress.isError) {
    return <LedgerUnavailable onRetry={() => void progress.refetch()} />;
  }

  return <LedgerView summary={progress.data} />;
}
