"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { readingMaterial, type WorkItem } from "@/lib/workspace/api";
import { readerTarget } from "@/lib/workspace/queue";
import { CoverTile } from "./CoverTile";
import { Icon } from "./Icon";
import { Mascot } from "./Mascot";

export function PlayerBar({ item, versionId, href, index, count, onPrevious, onNext, busy = false, children }: {
  item: WorkItem; versionId?: string; href: string; index: number; count: number;
  onPrevious?: () => void; onNext?: () => void; busy?: boolean; children?: ReactNode;
}) {
  const { version } = readingMaterial(item, readerTarget(item, versionId).version);
  const title = version.title || item.title;
  return <div className="ws-player">
    <div className="ws-player-track">
      <div className="ws-player-cover">{busy ? <Mascot mood="busy" /> : <CoverTile work_id={item.work_id} title={title} source_id={item.source_id} size="bar" />}</div>
      <div className="ws-player-identity"><span className="ws-player-title">{title}</span><span>{item.source_id} · {version.version_label}</span></div>
      <div className="ws-player-navigation" role="group" aria-label="Move through papers">
        <button type="button" aria-label="Previous paper" title="Previous paper · K or ←" data-command="prev" aria-keyshortcuts="K ArrowLeft" disabled={!onPrevious} onClick={onPrevious}><Icon name="prev" /></button>
        <Link href={href} prefetch={false} scroll={false} className="ws-player-open" aria-label="Open in reader" data-command="open" aria-keyshortcuts="O Enter" title="Open in reader · O or Enter"><Icon name="open" /><span>Read</span></Link>
        <button type="button" aria-label="Next paper" title="Next paper · J or →" data-command="next" aria-keyshortcuts="J ArrowRight" disabled={!onNext} onClick={onNext}><Icon name="next" /></button>
      </div>
      <div className="ws-player-position"><progress aria-label="Reading queue progress" aria-valuetext={`Paper ${index + 1} of ${count}`} max={count} value={index + 1} />
        <span>{String(index + 1).padStart(2, "0")} / {String(count).padStart(2, "0")}</span>
      </div>
    </div>
    {children}
  </div>;
}
