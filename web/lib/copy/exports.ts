// The export half of the copy dictionary (WO-19).
//
// Why this is a second file rather than three more keys in `./metrics.ts`:
// 06-WORK-ORDERS.md §5.6 gives each SURFACE its own copy file, and the strip
// and the disclosure are two surfaces that happen to share a work order.
// `MetricsStrip` is a server component with no interaction; `ExportDisclosure`
// is a client component. Keeping their strings apart keeps the strip's copy
// out of the route JavaScript the disclosure needs (04 §8.1).
//
// The `BRIEFING` duplication rule and its reason are stated once, in
// `./metrics.ts`. `label`, `markdown`, `pdf` and `refused` are asserted
// character-identical to their `BRIEFING` counterparts by
// `web/tests/copy/metrics-copy.test.ts`.
//
// RC-12, IN ONE SENTENCE: the LINK LABELS below are ours, and the FILENAME
// is not. The downloaded file is named by the upstream `Content-Disposition`
// (`src/api/routes.py:385`), which the proxy passes through unmodified
// (`web/app/api/[...path]/route.ts`), so it stays `research-{job_id}.{ext}`
// and does not follow the lexicon. Renaming it is a backend exporter change
// and is not scheduled; claiming otherwise on screen would be the lie.

/**
 * The disclosure's trigger, its three format labels, and the 409.
 *
 * THERE IS NO `docx` LABEL IN `BRIEFING`. WO-12 wrote `exportMarkdown` and
 * `exportPdf` and stopped, so `word` is new here rather than duplicated, and
 * the equality test asserts exactly the three that do exist. "Word" is the
 * application a `.docx` opens in, which is what a person choosing a format
 * is actually choosing between; "DOCX" would name the container instead.
 *
 * `refused` is 03 §2.2 row 23. It is only ever rendered after the proxy has
 * actually answered 409 — the control's resting behaviour when no briefing
 * exists is to be ABSENT, not to be present and explain itself, because a
 * disabled control that says nothing is the thing the row rules out and a
 * present control that always apologises is not much better. The sentence
 * names the cause (`export_research` refuses on an empty `result`,
 * `src/api/routes.py:364-368`) rather than the status code.
 */
export const EXPORT = {
  /** Identical to `BRIEFING.exportLabel`; asserted. */
  label: "Export",
  /** Identical to `BRIEFING.exportMarkdown`; asserted. */
  markdown: "Markdown",
  /** Identical to `BRIEFING.exportPdf`; asserted. */
  pdf: "PDF",
  /** New in WO-19: `BRIEFING` names no `docx` label. */
  word: "Word",
  /** Identical to `BRIEFING.exportRefused`; asserted. */
  refused: "There is nothing to export yet: this run produced no briefing.",
} as const;
