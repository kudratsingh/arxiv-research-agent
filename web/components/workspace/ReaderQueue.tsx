"use client";

import Link from "next/link";

export interface ReaderQueueTarget { workId: string; title: string; href: string }

export default function ReaderQueue({ targets, currentId, blocked }: {
  targets: readonly ReaderQueueTarget[]; currentId: string; blocked: boolean;
}) {
  return <ol className="ws-queue" aria-label="Reader queue">{targets.map((target, index) =>
    <li key={target.workId}><Link href={target.href} prefetch={false} scroll={false} className="ws-queue-row"
      aria-label={`Show paper ${index + 1} of ${targets.length}: ${target.title}`}
      aria-current={target.workId === currentId ? "true" : undefined} aria-disabled={blocked || undefined}
      tabIndex={blocked ? -1 : undefined} onClick={(event) => { if (blocked) event.preventDefault(); }}>
      <span className="ws-queue-position" aria-hidden="true"><span className="ws-queue-number">{String(index + 1).padStart(2, "0")}</span></span>
      <span className="ws-queue-text"><span className="ws-queue-title">{target.title}</span></span>
    </Link></li>)}</ol>;
}

