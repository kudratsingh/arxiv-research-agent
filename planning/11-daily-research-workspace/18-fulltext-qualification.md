# Bounded scientific full-text qualification

Observed 2026-11-02. This is a small manual-reader extraction qualification,
not generated-summary evaluation or owner usefulness approval. No model or
provider calls occurred. Existing abstracts remain separate from PDF material.

## Acquired sources and bounds

Exactly **two PDF GET attempts succeeded**, with **2,038,932 bytes** received
in total. No HEAD probes, second GETs, redirects, retries, article crawling,
code downloads or paid calls were used. The application adapter permits only
the two exact versioned PDF URLs below, 8 MiB each and 16 MiB per batch.

| Source | Exact version | Observed PDF | Rights checked from the official source |
|---|---|---|---|
| [ReAct](https://arxiv.org/abs/2210.03629v3), Yao et al. | `2210.03629v3` | 633,805 bytes; 33 pages | Official arXiv page links [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source and authors remain attributed. |
| [Self-RAG](https://arxiv.org/abs/2310.11511v1), Asai et al. | `2310.11511v1` | 1,405,127 bytes; 30 pages | Official arXiv page links [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Source and authors remain attributed. |

The observed PDF sizes above are actual response-body lengths, not arXiv's
submission-history upload sizes. The latter are not a download receipt.
ReAct's first submission was 2022-10-06; this selected version was revised
2023-03-10. Self-RAG's selected first version was submitted 2023-10-17.
These are source dates, not newly published papers from today's intake.

[arXiv's API terms](https://info.arxiv.org/help/api/tou.html) were rechecked:
the local shared arXiv governor serializes requests and spaces starts by at
least 3.1 seconds. The download pins public DNS results with original TLS
hostname verification, disables environmental proxy use, and streams under
size/time bounds. A failed acquisition records a receipt and leaves the
abstract available. The worker does not automatically acquire full text.

## Retained versions and original pages

An initial extraction retained only page 1 to obtain the title/page count.
The same local bytes were then reused; no second network request occurred.
The final selection contains page 1 and at most 12 distinct original pages per
paper. It includes methods, mathematical material, tables and later appendix
examples, while preserving original PDF page numbers.

| Source | Final original pages | Retained characters | Scope |
|---|---|---:|---|
| ReAct v3 | 1, 2, 3, 4, 5, 6, 8, 12, 18, 24, 30, 33 | 53,048 | `excerpt`; `complete=false` |
| Self-RAG v1 | 1, 2, 3, 4, 5, 6, 7, 8, 14, 18, 24, 30 | 59,339 | `excerpt`; `complete=false` |

These selections do **not** establish that omitted pages or the full document
were read. The parser remains a bounded child process: 20-second wall/CPU
limits, 120,000 retained characters, at most 12 pages, and a Linux child
address-space ceiling. macOS has byte/output/time bounds, not a complete memory
sandbox. No OCR was performed.

`SourceMaterial.page_numbers` maps the retained strings to original PDF pages.
`SourceSpan.page` is the original 1-based PDF page; start/end are exact Unicode
code-point offsets into that page's retained text, with end exclusive. PDF
section headings are not inferred. The source PDF hash, work/version, parser
revision and selected page mapping are sealed into material/span identity.
The default extraction path preserves its previous identities and behavior.

## Actual visual comparison and quality exclusions

Ten comparison pages were rendered with the existing PyMuPDF engine at 1.5x
and inspected alongside their retained text. Poppler was unavailable; no new
dependency was installed. Rendered source images remain local ignored artifacts.
The observations below describe this sample only; no population accuracy rate
or automatic equation/table reconstruction is claimed.

| Region | Original pages inspected | Result and limitation |
|---|---|---|
| ReAct methods prose and mathematical setup | 3 | Methods paragraph is retained with real offsets. Line wrapping/ligatures remain; mathematical mapping typography is not semantically qualified. |
| ReAct figure labels | 2 | Visually readable figure labels become corrupted glyph strings and flattened parallel trajectories in extracted text. **Unreliable; excluded from extracted figure support.** |
| ReAct results table | 5 | Caption/labels/numeric strings survive, but table columns and adjacent chart labels interleave. **Table-cell associations remain unqualified.** |
| ReAct appendix prompt and failure examples | 24, 33 | Caption/transcript text is readable. Visual group boundaries are not a typed extraction. Source instructions remain untrusted data and were never executed. |
| Self-RAG inference prose/algorithm | 4 | Prose is retained; indentation and linked annotations are not semantically parsed. |
| Self-RAG equations 3 and 4 | 6 | Summation, superscripts and fraction layout flatten into running text; one sum appears as an ordinary letter. **Unreliable for equation semantics.** No formula was repaired or invented. |
| Self-RAG results table | 8 | Multi-level task/metric headers, boldface meaning and numeric row/column associations are not a typed table. **Table-cell associations remain unqualified.** |
| Self-RAG appendix training algorithm and prompt examples | 18, 30 | Readable source text is retained, with original-page links. Algorithm/table structure remains subject to source review. Instructions remain data. |

The persisted material warnings and qualification receipts retain the specific
observed problems. The general exclusions are equation semantics, table-cell
structure, diagram content and unretained pages. Usable prose and stable anchors
support manual reading; these records do not certify generated factual claims.
Generation remains separately disabled pending the exact owner-approved trial.

## Local evidence and integration boundary

All raw PDFs, rendered pages, receipts and retained material JSON are under
`outputs/workspace-next/fulltext/` and are ignored by Git. Relevant files:

- `acquisition-summary.json`: two GET attempts and actual byte counts.
- `qualification-summary.json`: exact source hashes and material IDs.
- `react-v3-qualification.json`, `self-rag-v1-qualification.json`: selected pages,
  parser identity, region offsets/span IDs and actual visual observations.
- `react-v3-material.json`, `self-rag-v1-material.json`: immutable retained text,
  original-page mapping and specific quality warnings.
- `*-page-*.png`: the ten inspected source-page renders.

The qualification did not write the owner's database. The integration owner
registers these as public `scientific-sample` works, preserves original
publication/version dates, and stores retained material independently of
abstracts. These old qualification papers must remain outside the current
Today feed candidate set. Existing 83 real intake records are preserved.

The reader must display the selected-page/extraction warnings and navigate
using original page numbers. It must retain an abstract fallback on acquisition
or parser failure. Owner experience review and any later generated-summary
acceptance remain pending.
