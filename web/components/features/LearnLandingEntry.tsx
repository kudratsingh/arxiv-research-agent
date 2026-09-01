import Link from "next/link";

import { LEARN } from "@/lib/copy/learn";

import "@/components/primitives/primitives.css";

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
        className="ew-focusable ew-target mt-4 inline-flex items-center border-b border-primary pb-0.5 text-ui-sm font-medium text-primary hover:text-primary-strong"
      >
        {LEARN.landingAction}
      </Link>
    </aside>
  );
}
