"use client";

import Link from "next/link";
import type { ReadingRevision } from "@/lib/workspace/api";
import { Message } from "./Common";
import { ControlBar } from "./Slots";

export const DRAFT_NAVIGATION_NOTICE = "Save or copy your unsaved text before leaving this source version. Browser draft recovery is unavailable.";
/** Reading writes remain owned by Reader; these controls never reconstruct a request. */
export function ReaderControls({ saved, busy, notice, onReading, previousHref, nextHref, navigationBlocked, index, count }: {
  saved: boolean; busy: boolean; notice: string; onReading: (status: ReadingRevision["status"]) => void;
  previousHref?: string; nextHref?: string; navigationBlocked: boolean; index: number; count: number;
}) {
  return <ControlBar><div className="ws-reader-controls">
    <div className="ws-reader-navigation" role="group" aria-label="Move through papers">
      {previousHref && !navigationBlocked
        ? <Link href={previousHref} prefetch={false} scroll={false} data-command="prev" aria-keyshortcuts="K ArrowLeft" title="Previous paper · K or ←">Previous paper</Link>
        : <button type="button" disabled data-command="prev">Previous paper</button>}
      {count > 0 && <span className="ws-reader-position">{index >= 0 ? index + 1 : "–"} / {count}</span>}
      {nextHref && !navigationBlocked
        ? <Link href={nextHref} prefetch={false} scroll={false} data-command="next" aria-keyshortcuts="J ArrowRight" title="Next paper · J or →">Next paper</Link>
        : <button type="button" disabled data-command="next">Next paper</button>}
    </div>
    <div className="ws-reader-actions" role="group" aria-label="Reading actions">
      <button type="button" disabled={busy} aria-pressed={saved} data-command="save" aria-keyshortcuts="S" title="Save to Library · S" onClick={() => onReading(saved ? "unread" : "saved")}>{saved ? "Remove from saved items" : "Save to Library"}</button>
      <button type="button" disabled={busy} data-command="mark-read" onClick={() => onReading("read")}>Mark read</button>
      <button type="button" disabled={busy} data-command="dismiss" aria-keyshortcuts="D" title="Archive · D" onClick={() => onReading("archived")}>Archive</button>
    </div>
  </div><Message>{notice}</Message></ControlBar>;
}
