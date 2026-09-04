import Link from "next/link";

import { LEARN } from "@/lib/copy/learn";

import "@/components/primitives/primitives.css";

/**
 * The landing route's entry point into the guided-reading surface (WO-W12).
 *
 * `prefetch={false}` IS A BACK/FORWARD-CACHE REPAIR, AND IT IS MEASURED.
 *
 * This is the only in-viewport `<Link>` to another document route anywhere in
 * the audited surface, and at 412 x 823 it sits above the fold. The App
 * Router's default prefetch therefore fires as soon as `/` settles and
 * fetches `/learn?_rsc=...` — twice per load, in the audited waterfall.
 *
 * Every document route in this application is dynamically rendered, because
 * `app/layout.tsx` reads the per-request CSP nonce out of `headers()`
 * (WO-30). Next serves a dynamic document — RSC payload included — with
 * `Cache-Control: private, no-cache, no-store, max-age=0, must-revalidate`.
 * A *script-initiated* request that comes back `no-store` is a bfcache
 * blocker in its own right: Chrome reports
 * `JsNetworkRequestReceivedCacheControlNoStoreResource`, which is a second,
 * separate reason from the `MainResourceHasCacheControlNoStore` that
 * `web/lighthouserc.json` already documents. The first one Chrome forgives
 * under mobile emulation; this one it does not.
 *
 * So since WO-W12 the `bf-cache` audit has failed on `/` at 412 px and passed
 * on all three `/c/[id]` states, which have no in-viewport link — and passed
 * on `/` at 320 x 568, where this card falls below the fold and the prefetch
 * never fires. That asymmetry is the evidence: it is this link, not the
 * dynamic document, that costs `/` the RC-18 assertion.
 *
 * What it costs to switch off: the first click into `/learn` pays its own
 * navigation instead of a warm one. What it buys: the audit RC-18 gates at
 * `error` on every mobile cell, plus two fewer requests and one less RSC
 * payload to parse on the landing route's main thread. `/learn` is a
 * dynamic, `no-store` route, so what the prefetch warmed was never reusable
 * for long anyway.
 */
export function LearnLandingEntry() {
  return (
    <aside
      aria-labelledby="learn-entry-heading"
      data-learn-entry=""
      className="border-l-2 border-signature bg-surface px-5 py-4"
    >
      <p className="font-mono text-mono-xs uppercase tracking-wide text-signature-text">
        {LEARN.landingEyebrow}
      </p>
      <h2
        id="learn-entry-heading"
        className="mt-2 font-report text-report-h2 text-ink"
      >
        {LEARN.landingHeading}
      </h2>
      <p className="mt-2 max-w-measure text-ui-sm text-ink-muted">
        {LEARN.landingBody}
      </p>
      <Link
        href="/learn"
        prefetch={false}
        className="ew-focusable ew-target mt-4 inline-flex items-center border-b border-primary pb-0.5 text-ui-sm font-medium text-primary hover:text-primary-strong"
      >
        {LEARN.landingAction}
      </Link>
    </aside>
  );
}
