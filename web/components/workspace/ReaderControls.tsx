"use client";

import Link from "next/link";
import type { ReadingRevision } from "@/lib/workspace/api";
import { Message } from "./Common";
import { ControlBar } from "./Slots";

export const DRAFT_NAVIGATION_NOTICE = "Save or copy your unsaved text before leaving this source version. Browser draft recovery is unavailable.";
export interface ReaderQueueTarget { workId: string; title: string; href: string }

export function ReaderQueue({ targets, currentId, blocked }: {
  targets: readonly ReaderQueueTarget[]; currentId: string; blocked: boolean;
}) {
  return <ol className="ws-queue" aria-label="Reader queue">{targets.map((target, index) =>
    <li key={target.workId}><Link href={target.href} prefetch={false} className="ws-queue-row"
      aria-label={`Show paper ${index + 1} of ${targets.length}: ${target.title}`}
      aria-current={target.workId === currentId ? "true" : undefined} aria-disabled={blocked || undefined}
      tabIndex={blocked ? -1 : undefined} onClick={(event) => { if (blocked) event.preventDefault(); }}>
      <span className="ws-queue-position" aria-hidden="true"><span className="ws-queue-number">{String(index + 1).padStart(2, "0")}</span></span>
      <span className="ws-queue-text"><span className="ws-queue-title">{target.title}</span></span>
    </Link></li>)}</ol>;
}

/** Reading writes remain owned by Reader; these controls never reconstruct a request. */
export function ReaderControls({ saved, busy, notice, onReading, previousHref, nextHref, navigationBlocked, index, count }: {
  saved: boolean; busy: boolean; notice: string; onReading: (status: ReadingRevision["status"]) => void;
  previousHref?: string; nextHref?: string; navigationBlocked: boolean; index: number; count: number;
}) {
  return <ControlBar><div className="ws-reader-controls">
    <div className="ws-reader-navigation" role="group" aria-label="Move through papers">
      {previousHref && !navigationBlocked
        ? <Link href={previousHref} prefetch={false} data-command="prev" aria-keyshortcuts="K ArrowLeft" title="Previous paper · K or ←">Previous paper</Link>
        : <button type="button" disabled data-command="prev">Previous paper</button>}
      {count > 0 && <span className="ws-reader-position">{index >= 0 ? index + 1 : "–"} / {count}</span>}
      {nextHref && !navigationBlocked
        ? <Link href={nextHref} prefetch={false} data-command="next" aria-keyshortcuts="J ArrowRight" title="Next paper · J or →">Next paper</Link>
        : <button type="button" disabled data-command="next">Next paper</button>}
    </div>
    <div className="ws-reader-actions" role="group" aria-label="Reading actions">
      <button type="button" disabled={busy} aria-pressed={saved} data-command="save" aria-keyshortcuts="S" title="Save to Library · S" onClick={() => onReading(saved ? "unread" : "saved")}>{saved ? "Remove from saved items" : "Save to Library"}</button>
      <button type="button" disabled={busy} data-command="mark-read" onClick={() => onReading("read")}>Mark read</button>
      <button type="button" disabled={busy} data-command="dismiss" aria-keyshortcuts="D" title="Archive · D" onClick={() => onReading("archived")}>Archive</button>
    </div>
  </div><Message>{notice}</Message></ControlBar>;
}
