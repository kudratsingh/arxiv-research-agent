"use client";
import Link from "next/link";
import {
  displayDate,
  readerHref,
  readingMaterial,
  type ReadingData,
  type WorkItem,
} from "@/lib/workspace/api";

export function WorkCard({
  item,
  lead = false,
  busy = false,
  versionId,
  returnTo,
  status,
}: {
  item: WorkItem;
  lead?: boolean;
  busy?: boolean;
  versionId?: string;
  returnTo?: string;
  status: (item: WorkItem, value: ReadingData["status"]) => void;
}) {
  const readingVersion =
    versionId || item.reading.version_id || item.version_id;
  const { version, pdf, scope } = readingMaterial(item, readingVersion);
  const readingAnchor =
    item.reading.revision > 0 && item.reading.version_id === readingVersion
      ? item.reading.anchor
      : pdf?.first_anchor ?? `${version.access_state}:0`;
  return (
    <article className={`daily-item${lead ? " daily-item-lead" : ""}`}>
      <div className="daily-item-meta">
        <span>{item.kind}</span>
        <span>{version.version_label}</span>
        <span>{pdf ? pdf.complete && pdf.scope === "full_text" ? "PDF text" : "PDF excerpts" : scope.replaceAll("_", " ")}</span>
        {item.reading.status !== "unread" && (
          <span className="daily-saved">{item.reading.status}</span>
        )}
      </div>
      <h3>
        <Link
          href={readerHref(
            item,
            readingVersion,
            readingAnchor,
            undefined,
            returnTo,
          )}
          prefetch={false}
        >
          {version.title || item.title}
        </Link>
      </h3>
      <p className="daily-item-change">
        {version.abstract
          ? `${version.abstract.slice(0, 320)}${version.abstract.length > 320 ? "…" : ""}`
          : pdf
            ? "Retained PDF excerpts are ready to read for this source version. Selected pages only; extraction limits remain visible in the reader."
            : "Source link and metadata are available. No abstract or full text was acquired."}
      </p>
      {!versionId &&
        item.reading.version_id &&
        item.reading.version_id !== item.version_id && (
          <p className="workspace-version-notice">
            A newer source version is available. Opening this item resumes your
            saved version; its notes remain attached there.
          </p>
        )}
      <details className="daily-reason">
        <summary>Why this appeared</summary>
        <p>
          {item.reasons.length
            ? item.reasons.join(" · ")
            : "Stored source metadata. No personal match has been inferred."}{" "}
          Ranking uses declared terms and source metadata; it is not a
          factual-quality score.
        </p>
      </details>
      <p className="daily-caveat">
        <strong>Available evidence</strong>{" "}
        {pdf
          ? pdf.complete && pdf.scope === "full_text"
            ? "Retained PDF text; equations, figures and table structure may be unreliable. Inspect the extraction receipt before relying on them."
            : "Selected original PDF pages; equations, figures and table structure may be unreliable. The complete paper is outside this retained reading scope."
          : scope === "abstract"
          ? "The source abstract; methods, tables and full text have not been read."
          : scope === "excerpt"
            ? "The publisher’s feed excerpt; the complete article has not been acquired."
            : "Metadata and the original link. Check access at the source."}
      </p>
      <div className="daily-item-footer">
        <span>
          {item.source_id} ·{" "}
          {item.published_at
            ? `Published ${displayDate(item.published_at)}`
            : "Publication date unknown"}
        </span>
        <Link
          className="daily-link"
          href={readerHref(
            item,
            readingVersion,
            readingAnchor,
            undefined,
            returnTo,
          )}
          prefetch={false}
        >
          Read & investigate →
        </Link>
      </div>
      <div className="workspace-card-actions">
        <button
          className="daily-text-button"
          disabled={busy}
          aria-label={`${item.reading.status === "saved" ? "Unsave" : "Save"} ${item.title}`}
          aria-pressed={item.reading.status === "saved"}
          onClick={() =>
            status(item, item.reading.status === "saved" ? "unread" : "saved")
          }
        >
          {item.reading.status === "saved" ? "Unsave" : "Save"}
          <span className="sr-only"> {item.title}</span>
        </button>
        <button
          className="daily-text-button"
          disabled={busy}
          aria-label={`Dismiss ${item.title}`}
          onClick={() => status(item, "dismissed")}
        >
          Dismiss<span className="sr-only"> {item.title}</span>
        </button>
        <button
          className="daily-text-button"
          disabled={busy}
          aria-label={`Snooze one day ${item.title}`}
          onClick={() => status(item, "snoozed")}
        >
          Snooze one day<span className="sr-only"> {item.title}</span>
        </button>
      </div>
    </article>
  );
}
