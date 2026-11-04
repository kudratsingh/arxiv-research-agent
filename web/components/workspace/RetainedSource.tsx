"use client";

import { useEffect, useRef, useState } from "react";
import { settleReaderTarget } from "@/lib/workspace/navigation";
import {
  errorMessage,
  workspaceRequest,
  type MaterialDocument,
  type MaterialInfo,
  type RetainedSpan,
} from "@/lib/workspace/api";

export function parseMaterialAnchor(value: string) {
  const match = /^material:([^:]+):page:(\d+):(\d+):(\d+)$/.exec(value);
  if (!match) return null;
  const page = Number(match[2]),
    start = Number(match[3]),
    end = Number(match[4]);
  return [page, start, end].every(Number.isSafeInteger) &&
    page > 0 &&
    start >= 0 &&
    end > start
    ? { materialId: match[1]!, page, start, end }
    : null;
}

function originalPDF(provenance: Record<string, unknown>) {
  const acquisition = provenance.acquisition;
  const candidates = [
    provenance.source_url,
    provenance.pdf_url,
    provenance.original_url,
  ];
  if (acquisition && typeof acquisition === "object") {
    for (const key of ["resolved_url", "requested_url"]) {
      if (key in acquisition)
        candidates.push((acquisition as Record<string, unknown>)[key]);
    }
  }
  for (const candidate of candidates) {
    if (typeof candidate !== "string") continue;
    try {
      const url = new URL(candidate);
      if (url.protocol === "https:" && !url.username && !url.password)
        return url.href;
    } catch {
      /* Invalid provenance links remain plain text in the receipt. */
    }
  }
  return null;
}

export function RetainedSourceReader({
  workId,
  versionId,
  anchor,
  onNavigate,
  onSelect,
  onActive,
  announce,
}: {
  workId: string;
  versionId: string;
  anchor: string;
  onNavigate: (anchor: string) => void;
  onSelect: (anchor: string, quote: string) => void;
  onActive: (active: boolean) => void;
  announce: (message: string) => void;
}) {
  const [materials, setMaterials] = useState<MaterialInfo[] | null>(null);
  const [document, setDocument] = useState<MaterialDocument | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const parsed = parseMaterialAnchor(anchor);
  const wantedMaterial = parsed?.materialId,
    wantedPage = parsed?.page,
    wantedStart = parsed?.start;
  useEffect(() => {
    if (!wantedMaterial) {
      onActive(false);
      return;
    }
    const pending = new AbortController();
    workspaceRequest<MaterialDocument>(
      `materials/${encodeURIComponent(wantedMaterial)}`,
      undefined,
      pending.signal,
    )
      .then((value) => {
        if (value.work_id !== workId || value.version_id !== versionId)
          throw new Error("source mismatch");
        setDocument(value);
        setError("");
        onActive(true);
      })
      .catch((failure: unknown) => {
        if (!pending.signal.aborted) {
          setError(errorMessage(failure));
          onActive(false);
        }
      });
    return () => pending.abort();
  }, [wantedMaterial, workId, versionId, onActive]);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (
      !wantedMaterial ||
      wantedStart === undefined ||
      document?.material_id !== wantedMaterial
    )
      return;
    const span = document.spans.find(
      (candidate) =>
        candidate.page === wantedPage &&
        candidate.start <= wantedStart &&
        candidate.end > wantedStart,
    );
    const target = span
      ? window.document.getElementById(`retained-span-${span.span_id}`)
      : null;
    if (target) settleReaderTarget(target, false);
  }, [wantedMaterial, wantedPage, wantedStart, document]);
  async function list() {
    setLoading(true);
    try {
      const values = await workspaceRequest<MaterialInfo[]>(
        `materials?work_id=${encodeURIComponent(workId)}&version_id=${encodeURIComponent(versionId)}`,
      );
      setMaterials(values.filter((material) => material.page_count !== null));
      setError("");
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setLoading(false);
    }
  }
  async function open(id: string) {
    controller.current?.abort();
    const pending = new AbortController();
    controller.current = pending;
    setLoading(true);
    try {
      const value = await workspaceRequest<MaterialDocument>(
        `materials/${encodeURIComponent(id)}`,
        undefined,
        pending.signal,
      );
      if (value.work_id !== workId || value.version_id !== versionId)
        throw new Error("source mismatch");
      setDocument(value);
      setError("");
      onActive(true);
      const first = value.spans.find(
        (span) => span.page !== null && span.end > span.start,
      );
      if (first)
        onNavigate(
          `material:${value.material_id}:page:${first.page}:${first.start}:${first.end}`,
        );
      announce(
        "Opened retained source text. The extraction receipt states which original pages and structures are available.",
      );
    } catch (failure) {
      if (!pending.signal.aborted) setError(errorMessage(failure));
    } finally {
      if (!pending.signal.aborted) setLoading(false);
    }
  }
  function select(
    event:
      | React.MouseEvent<HTMLParagraphElement>
      | React.KeyboardEvent<HTMLParagraphElement>,
    span: RetainedSpan,
  ) {
    if (span.page === null) return;
    const selection = window.getSelection();
    if (!selection?.rangeCount) return;
    const range = selection.getRangeAt(0),
      paragraph = event.currentTarget;
    if (
      !paragraph.contains(range.startContainer) ||
      !paragraph.contains(range.endContainer) ||
      !range.toString().trim()
    )
      return;
    const before = range.cloneRange();
    before.selectNodeContents(paragraph);
    before.setEnd(range.startContainer, range.startOffset);
    const start = span.start + Array.from(before.toString()).length,
      end = start + Array.from(range.toString()).length;
    onSelect(
      `material:${span.material_id}:page:${span.page}:${start}:${end}`,
      Array.from(range.toString()).slice(0, 400).join(""),
    );
  }
  const visible =
    document && wantedMaterial === document.material_id ? document : null;
  const pdf = visible ? originalPDF(visible.provenance) : null;
  return (
    <section
      className="workspace-retained-source"
      aria-labelledby="retained-document-title"
    >
      <div className="workspace-toolbar">
        <h3 id="retained-document-title">Retained document text</h3>
        <button
          className="daily-secondary"
          disabled={loading}
          onClick={() => void list()}
        >
          {loading
            ? "Opening retained material…"
            : "Find retained PDF excerpts"}
        </button>
      </div>
      {materials && materials.length === 0 && (
        <p className="daily-muted">
          No document pages are retained for this version. The available source
          record and original link remain usable.
        </p>
      )}
      {materials && materials.length > 0 && (
        <label>
          Retained document
          <select
            value={visible?.material_id ?? ""}
            onChange={(event) => {
              if (event.target.value) void open(event.target.value);
            }}
          >
            <option value="">Choose retained material</option>
            {materials.map((material) => (
              <option key={material.material_id} value={material.material_id}>
                {material.scope} ·{" "}
                {material.page_numbers
                  ? `original pages ${material.page_numbers.join(", ")}`
                  : "original page numbers in retained passages"}{" "}
                · {material.quality}
              </option>
            ))}
          </select>
        </label>
      )}
      {error && (
        <p className="workspace-version-notice">
          Retained material could not be opened. Your notes and saved anchor are
          unchanged. {error}
        </p>
      )}
      {wantedMaterial && !visible && !error && (
        <p className="daily-muted">
          Opening the exact retained material behind this anchor…
        </p>
      )}
      {visible && (
        <>
          <button
            className="daily-text-button"
            onClick={() => {
              setDocument(null);
              onActive(false);
              onNavigate("abstract:0");
            }}
          >
            Return to this version’s abstract or metadata
          </button>
          <div className="workspace-version-notice">
            <strong>
              {visible.complete
                ? "Complete retained extraction"
                : "Selected pages or partial extraction"}{" "}
              · {visible.scope}
            </strong>
            <p>
              {visible.complete
                ? "Completeness describes this extraction, not the correctness of scientific claims."
                : "This is an excerpt of the paper. Omitted pages have not been read or reconstructed."}
            </p>
            <p>
              Extraction quality: {visible.quality}. Equation and table
              structure is not reconstructed by this plain-text view; inspect
              the original PDF for those structures.
            </p>
            {visible.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
            {pdf && (
              <a
                className="daily-link"
                href={pdf}
                target="_blank"
                rel="noopener noreferrer"
              >
                Open original PDF ↗
              </a>
            )}
          </div>
          <details className="workspace-source-receipt">
            <summary className="daily-link">
              Source version, hash and extraction receipt
            </summary>
            <p className="workspace-origin">
              {visible.work_id}
              <br />
              {visible.version_id}
              <br />
              Material {visible.material_id}
              <br />
              Source {visible.source_hash}
              <br />
              Text {visible.content_hash}
              <br />
              Parser {visible.parser_revision}
              <br />
              Offsets: {visible.offset_basis}
            </p>
            <pre
              tabIndex={0}
              role="region"
              aria-label="Retained source provenance"
              className="workspace-receipt"
            >
              {JSON.stringify(visible.provenance, null, 2)}
            </pre>
          </details>
          {visible.spans.map((span) => {
            const chars = Array.from(span.text);
            const selected =
              parsed?.materialId === visible.material_id &&
              parsed.page === span.page &&
              parsed.end > span.start &&
              parsed.start < span.end;
            const start = selected ? Math.max(0, parsed.start - span.start) : 0,
              end = selected
                ? Math.min(chars.length, parsed.end - span.start)
                : 0;
            return (
              <section
                key={span.span_id}
                id={`retained-span-${span.span_id}`}
                tabIndex={-1}
                className="workspace-retained-passage"
                aria-label={
                  span.page === null
                    ? "Retained passage without page information"
                    : `Original page ${span.page}, characters ${span.start} to ${span.end}`
                }
              >
                <p className="workspace-note-context">
                  {span.page === null
                    ? "Original page unknown"
                    : `Original page ${span.page}`}{" "}
                  · characters {span.start}–{span.end}
                  {span.section
                    ? ` · ${span.section}`
                    : " · section not identified"}
                </p>
                <p
                  className="workspace-retained-text"
                  onMouseUp={(event) => select(event, span)}
                  onKeyUp={(event) => select(event, span)}
                >
                  {selected ? (
                    <>
                      {chars.slice(0, start).join("")}
                      <mark>{chars.slice(start, end).join("")}</mark>
                      {chars.slice(end).join("")}
                    </>
                  ) : (
                    span.text
                  )}
                </p>
              </section>
            );
          })}
        </>
      )}
    </section>
  );
}
