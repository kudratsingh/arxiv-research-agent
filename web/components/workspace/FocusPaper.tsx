"use client";

import Link from "next/link";
import { displayDate, readingMaterial, type WorkItem } from "@/lib/workspace/api";
import { readerTarget } from "@/lib/workspace/queue";
import { CoverTile } from "./CoverTile";

/** The reading surface owns evidence presentation; its actions live in the bar. */
export function FocusPaper({ item, versionId, href, position }: { item: WorkItem; versionId?: string; href: string; position?: { index: number; count: number } }) {
  const target = readerTarget(item, versionId);
  const { version, pdf, scope } = readingMaterial(item, target.version);
  const title = version.title || item.title;
  return <article data-paper-key={`${item.work_id}:${target.version}`} className="daily-item ws-focus" data-paper-announcement={position ? `Paper ${position.index + 1} of ${position.count}: ${title}` : title}>
    <div className="ws-focus-heading">
      <CoverTile work_id={item.work_id} title={title} source_id={item.source_id} />
      <div className="ws-focus-identity">
        <div className="daily-item-meta ws-focus-chips">
          <span>{item.kind}</span><span>{version.version_label}</span>
          <span>{pdf ? pdf.complete && pdf.scope === "full_text" ? "PDF text" : "PDF excerpts" : scope.replaceAll("_", " ")}</span>
          {item.reading.status !== "unread" && <span className="daily-saved">{item.reading.status}</span>}
        </div>
        <h3><Link href={href} prefetch={false} scroll={false}>{title}</Link></h3>
        <p className="ws-focus-byline">{version.authors.join(", ") || "Authors not recorded for this source version"}</p>
        <p className="ws-focus-source">{item.source_id} · {item.published_at ? `Published ${displayDate(item.published_at)}` : "Publication date unknown"}</p>
      </div>
    </div>
    <p className="daily-item-change ws-focus-abstract">{version.abstract || (pdf
      ? pdf.complete && pdf.scope === "full_text"
        ? "Retained PDF text is ready to read for this source version. Extraction limits remain visible in the reader."
        : "Retained PDF excerpts are ready to read for this source version. Selected pages only; extraction limits remain visible in the reader."
      : "Source link and metadata are available. No abstract or full text was acquired.")}</p>
    {!versionId && item.reading.version_id && item.reading.version_id !== item.version_id && <p className="workspace-version-notice">
      A newer source version is available. Opening this item resumes your saved version; its notes remain attached there.
    </p>}
    <details className="daily-reason ws-focus-reason" open>
      <summary>Why this appeared</summary>
      <p>{item.reasons.length ? item.reasons.join(" · ") : "Stored source metadata. No personal match has been inferred."}{" "}
        Ranking uses declared terms and source metadata; it is not a factual-quality score.</p>
    </details>
    <p className="daily-caveat ws-focus-evidence"><strong>Available evidence</strong>{" "}{pdf
      ? pdf.complete && pdf.scope === "full_text"
        ? "Retained PDF text; equations, figures and table structure may be unreliable. Inspect the extraction receipt before relying on them."
        : "Selected original PDF pages; equations, figures and table structure may be unreliable. The complete paper is outside this retained reading scope."
      : scope === "abstract"
        ? "The source abstract; methods, tables and full text have not been read."
        : scope === "excerpt"
          ? "The publisher’s feed excerpt; the complete article has not been acquired."
          : "Metadata and the original link. Check access at the source."}</p>
  </article>;
}
