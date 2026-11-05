"use client";

import Link from "next/link";
import type { ReadingRevision } from "@/lib/workspace/api";

/** Reading writes remain owned by Reader; these controls never reconstruct a request. */
export default function ReaderControls({ saved, busy, onReading, previousHref, nextHref, navigationBlocked, index, count }: {
  saved: boolean; busy: boolean; onReading: (status: ReadingRevision["status"]) => void;
  previousHref?: string; nextHref?: string; navigationBlocked: boolean; index: number; count: number;
}) {
  return <div className="ws-reader-controls">
    <div className="ws-reader-navigation" role="group" aria-label="Move through papers">
      {previousHref && !navigationBlocked
        ? <Link href={previousHref} prefetch={false} scroll={false} data-command="prev" aria-keyshortcuts="K ArrowLeft" title="Previous paper · K or ←">Previous paper</Link>
        : <button type="button" disabled data-command="prev">Previous paper</button>}
      {count > 0 && <span className="ws-reader-position">{index >= 0 ? index + 1 : "–"} / {count}</span>}
      {nextHref && !navigationBlocked
        ? <Link href={nextHref} prefetch={false} scroll={false} data-command="next" aria-keyshortcuts="J ArrowRight" title="Next paper · J or →">Next paper</Link>
        : <button type="button" disabled data-command="next">Next paper</button>}
    </div>
    <div className="ws-reader-actions" aria-busy={busy} role="group" aria-label="Reading actions">
      <button type="button" disabled={busy} aria-pressed={saved} data-command="save" aria-keyshortcuts="S" title="Save to Library · S" onClick={() => onReading(saved ? "unread" : "saved")}>{saved ? "Remove from saved items" : "Save to Library"}</button>
      <button type="button" disabled={busy} data-command="mark-read" onClick={() => onReading("read")}>Mark read</button>
      <button type="button" disabled={busy} data-command="dismiss" aria-keyshortcuts="D" title="Archive · D" onClick={() => onReading("archived")}>Archive</button>
    </div>
  </div>;
}
