/**
 * Patterns/ReportReader — WO-18 criterion 10, first group.
 *
 * THE RENDERER COMES FROM THE PRODUCT'S OWN BOUNDARY, through a loader:
 * `loadReportRenderer()` is the same dynamic import a route performs
 * (`lib/report/renderer.ts`), so what these stories parse is the real
 * `react-markdown` + `remark-gfm` pipeline and not a story-local
 * approximation. A second composition here would make criterion 2's "exactly
 * one renderer" false in the one place a reviewer looks at the output.
 *
 * The loader also removes the async frame: `loaders` resolve before the
 * story renders, so every story below is on screen — and under axe — in its
 * settled state rather than as a skeleton. `Loading` is the one story that
 * asks for the skeleton, and it gets it by passing `renderer={null}`.
 *
 * WHY THE IMPORT LIST IS SHORT. `web/vitest.config.mts` records the
 * measurement hazard for WO-13 … WO-19: a module both Vitest projects load
 * has its function list concatenated in the merged coverage report, so a
 * story that imports a module it does not exercise moves the functions
 * column without changing a line of product code. These stories import the
 * component, its copy file and the renderer boundary — all three of which
 * they drive end to end — and nothing else.
 *
 * NO STRING IS RENDERED AS TEXT HERE. The Markdown bodies below are sample
 * DOCUMENTS passed as a prop, which is what a briefing is; every word of
 * product copy on screen comes from `lib/copy/report` through the component.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { loadReportRenderer, type ReportRenderer } from "@/lib/report/renderer";

import { ReportReader } from "./ReportReader";

// ---------------------------------------------------------------------------
// Sample briefings.
// ---------------------------------------------------------------------------

const SHORT = [
  "Retrieval-augmented systems are evaluated on answer accuracy far more",
  "often than on whether the answer is *supported* by what was retrieved.",
  "",
  "Three of the eleven papers read here separate the two.",
].join("\n");

const LONG_WITH_HEADINGS = [
  "# Faithfulness in retrieval-augmented generation",
  "",
  "Eleven papers, read end to end. The through-line is that *faithfulness*",
  "and *accuracy* are measured as if they were one quantity, and they are",
  "not.",
  "",
  "## What the field measures today",
  "",
  "Answer-level exact match dominates. It rewards a system that guessed",
  "correctly from parametric memory exactly as much as one that read the",
  "retrieved passage.",
  "",
  "### Automatic metrics",
  "",
  "Entailment-based scoring is the most common substitute, and it inherits",
  "the entailment model's own failure modes.",
  "",
  "### Human protocols",
  "",
  "Annotator agreement on **support** is consistently lower than agreement",
  "on correctness — which is itself the finding.",
  "",
  "## Where the disagreement is",
  "",
  "Two camps: one treats unsupported-but-correct as a pass, the other as a",
  "failure. Nothing reconciles them.",
  "",
  "### Unsupported but correct",
  "",
  "> An answer the retrieval did not license is a coincidence, not a result.",
  "",
  "## What is missing",
  "",
  "1. A claim-level benchmark that survives paraphrase.",
  "2. A protocol that reports support and accuracy separately.",
  "3. Any agreement on what counts as a citation.",
  "",
  "## Limits",
  "",
  "The sample is arXiv-only and English-only, and stops at the retrieval",
  "date of this run.",
].join("\n");

const WITH_WIDE_TABLE = [
  "## Benchmarks compared",
  "",
  "The columns are wider than the reading column on purpose: this is the",
  "SC 1.4.10 case.",
  "",
  "| Benchmark | Claim-level | Paraphrase-robust | Human protocol published | Annotator agreement | Licence |",
  "| --- | --- | --- | --- | --- | --- |",
  "| Alpha-Verify | yes | partial | yes | 0.71 | CC BY 4.0 |",
  "| BetaSupport | no | no | no | not reported | research only |",
  "| GammaCite | yes | yes | yes | 0.64 | CC BY-SA 4.0 |",
  "| DeltaGround | partial | no | yes | 0.58 | Apache 2.0 |",
  "",
  "## Reading the table",
  "",
  "Only two of the four report agreement at all.",
].join("\n");

const WITH_CODE_BLOCKS = [
  "## Reproducing the scoring pass",
  "",
  "The verifier is a single call per extracted claim; `--strict` is what",
  "turns an unsupported claim into a failure rather than a warning.",
  "",
  "```bash",
  "python -m src.eval.faithfulness --input runs/2601.jsonl --strict --report out/faithfulness-report.json --max-claims 512",
  "```",
  "",
  "Its output is one record per claim:",
  "",
  "```json",
  '{"claim_id": "c-014", "supported": false, "evidence": [], "source": "arXiv:2601.00001"}',
  "```",
].join("\n");

/** The committed `failed-partial` fixture's body, verbatim. */
const PARTIAL = [
  "# Partial briefing",
  "",
  "The run retained an incomplete synthesis before verification failed.",
  "",
  "## What remains useful",
  "",
  "- Initial retrieval completed.",
  "- Final claim verification did not complete.",
].join("\n");

/** The same fixture's two backend strings, unedited (RC-16). */
const PARTIAL_FAILURE = {
  errorType: "verification_incomplete",
  error: "Verification stopped before all claims could be checked.",
};

// ---------------------------------------------------------------------------

function rendererFrom(context: { loaded: Record<string, unknown> }): ReportRenderer {
  return context.loaded.renderer as ReportRenderer;
}

const meta = {
  title: "Patterns/ReportReader",
  component: ReportReader,
  loaders: [async () => ({ renderer: await loadReportRenderer() })],
  args: {
    markdown: SHORT,
    renderer: null,
  },
  render: (args, context) => (
    <div className="p-6">
      <ReportReader {...args} renderer={rendererFrom(context)} />
    </div>
  ),
} satisfies Meta<typeof ReportReader>;

export default meta;
type Story = StoryObj<typeof meta>;

/** No briefing yet. Not a spinner, not a card with nothing in it. */
export const Empty: Story = { args: { markdown: "" } };

export const Short: Story = { args: { markdown: SHORT } };

/** Long enough that the section rail earns its place. */
export const LongWithHeadings: Story = { args: { markdown: LONG_WITH_HEADINGS } };

/** Criterion 6: the table pans inside a labelled region; the page does not. */
export const WithWideTable: Story = { args: { markdown: WITH_WIDE_TABLE } };

/** Criterion 7's other half — `code` and `pre` on the token surfaces. */
export const WithCodeBlocks: Story = { args: { markdown: WITH_CODE_BLOCKS } };

/**
 * Criterion 1 / H5 / D-010 ruling 2. The failure is a banner ABOVE a
 * briefing that still renders, and the raw `error_type` sits under it
 * unedited (RC-16). `ReportView.tsx:13-27` returns before this content.
 */
export const PartialFromFailedRun: Story = {
  args: { markdown: PARTIAL, failure: PARTIAL_FAILURE },
};

/** 03 §2.2 row 15: failed, and there is genuinely nothing to show. */
export const FailedWithNoBriefing: Story = {
  args: { markdown: "", failure: PARTIAL_FAILURE },
};

/** The pipeline has not resolved yet. A still skeleton — 03 §3.7. */
export const Loading: Story = {
  args: { markdown: LONG_WITH_HEADINGS },
  render: (args) => (
    <div className="p-6">
      <ReportReader {...args} renderer={null} />
    </div>
  ),
};

/** A heading the reader is currently at, marked in the rail. */
export const ActiveSection: Story = {
  args: { markdown: LONG_WITH_HEADINGS, activeHeadingId: "where-the-disagreement-is" },
};

/** 03 §2.2 row 8 — the same layout on the dark token set. */
export const Dark: Story = {
  args: { markdown: WITH_WIDE_TABLE },
  globals: { theme: "dark" },
};

/** The same, with the hue taken away entirely (RC-17). */
export const ForcedColours: Story = {
  args: { markdown: PARTIAL, failure: PARTIAL_FAILURE },
  globals: { theme: "forced-colors" },
};
