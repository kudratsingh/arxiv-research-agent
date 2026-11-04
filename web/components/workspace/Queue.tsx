"use client";

import { readingMaterial, type WorkItem } from "@/lib/workspace/api";
import { readerTarget } from "@/lib/workspace/queue";
import { Icon } from "./Icon";

export function QueueRow({ item, index, count, current, versionId, onSelect }: {
  item: WorkItem; index: number; count: number; current: boolean; versionId?: string; onSelect: (id: string) => void;
}) {
  const { version, pdf, scope } = readingMaterial(item, readerTarget(item, versionId).version);
  const title = version.title || item.title;
  return <li><button type="button" className="ws-queue-row" data-work-id={item.work_id} aria-current={current ? "true" : undefined}
    aria-label={`Show paper ${index + 1} of ${count}: ${title}`} onClick={() => onSelect(item.work_id)}>
    <span className="ws-queue-position" aria-hidden="true">
      <span className="ws-queue-number">{String(index + 1).padStart(2, "0")}</span>
      {current && <span className="ws-equalizer"><i /><i /><i /></span>}
    </span>
    <span className="ws-queue-text">
      <span className="ws-queue-title">{title}</span>
      <span className="ws-queue-meta">{item.source_id} · {pdf ? pdf.complete && pdf.scope === "full_text" ? "PDF text" : "PDF excerpts" : scope.replaceAll("_", " ")}
        {item.reading.status !== "unread" && <span> · {item.reading.status}</span>}
      </span>
    </span>
    {item.reading.status === "saved" && <Icon name="saved" className="ws-queue-state" />}
  </button></li>;
}

export function QueueList({ items, focusId, versionIds, onSelect }: {
  items: readonly WorkItem[]; focusId: string | null; versionIds?: Readonly<Record<string, string>>; onSelect: (id: string) => void;
}) {
  return <ol className="ws-queue" aria-label="Today's reading queue">{items.map((item, index) => <QueueRow key={item.work_id}
    item={item} index={index} count={items.length} current={focusId === item.work_id} versionId={versionIds?.[item.work_id]} onSelect={onSelect} />)}</ol>;
}
