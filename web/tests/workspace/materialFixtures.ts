import type { MaterialDocument } from "@/lib/workspace/api";
import { work } from "./fixtures";
export const MAT = `mat-${"a".repeat(32)}`;
export const SPAN = `span-${"b".repeat(32)}`;
export const text =
  "🧭 A retrieval result on the original page. Equation layout is excluded.";
export function retained(
  overrides: Partial<MaterialDocument> = {},
): MaterialDocument {
  return {
    material_id: MAT,
    work_id: work().work_id,
    version_id: work().version_id,
    source_hash: "source-sha",
    content_hash: "content-sha",
    scope: "excerpt",
    parser_revision: "pdf-safe-v1",
    quality: "partial",
    warnings: ["Equations, tables and omitted methods are not reconstructed."],
    complete: false,
    page_count: 10,
    page_numbers: [3, 7],
    offset_basis: "unicode_codepoints_per_page",
    provenance: {
      source_url: "https://arxiv.org/pdf/2610.00001v2",
      extraction_method: "bounded-text",
      scope: "selected-pages",
    },
    pages: [text, "Original seventh page with more retained text."],
    spans: [
      {
        span_id: SPAN,
        material_id: MAT,
        work_id: work().work_id,
        version_id: work().version_id,
        source_hash: "source-sha",
        scope: "excerpt",
        parser_revision: "pdf-safe-v1",
        page: 3,
        section: null,
        start: 0,
        end: Array.from(text).length,
        text,
      },
      {
        span_id: `span-${"c".repeat(32)}`,
        material_id: MAT,
        work_id: work().work_id,
        version_id: work().version_id,
        source_hash: "source-sha",
        scope: "excerpt",
        parser_revision: "pdf-safe-v1",
        page: 7,
        section: "Discussion",
        start: 0,
        end: 45,
        text: "Original seventh page with more retained text.",
      },
    ],
    ...overrides,
  };
}
