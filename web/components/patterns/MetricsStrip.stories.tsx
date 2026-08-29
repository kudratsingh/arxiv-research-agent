/**
 * Patterns/MetricsStrip — WO-19 criterion 7, first group.
 *
 * EVERY NUMBER BELOW IS A RECORDED ONE. The three stories take their values
 * from `web/contract/fixtures/job.succeeded.json` and
 * `job.failed_partial.json` — recorded against the local stack, not
 * authored — so what the strip is documented rendering is what the API
 * actually returns. `AllNull` is the third real case: `quality_score`,
 * `cost_usd`, `llm_calls` and `iterations` are all optional in the schema
 * (`lib/api/generated/schema.d.ts`), and a run that reported none of them is
 * a contract-reachable state rather than an invented one.
 *
 * They are TYPED here rather than read off disk: `loadFixture` is `node:fs`
 * and `process.cwd()`, which no browser build can run. The unit test drives
 * the same two fixtures through the real loader, so the values are pinned
 * where pinning them is possible.
 *
 * THE ARGS GO THROUGH `readRunMetrics`, which is the same adapter WO-20 will
 * call on a `JobDetail`. A story that hand-built a `RunMetrics` would
 * document a shape the product never produces.
 *
 * WHY THE IMPORT LIST IS SHORT. `web/vitest.config.mts` records the
 * measurement hazard for WO-13 … WO-19: a module both Vitest projects load
 * has its function list concatenated in the merged coverage report. These
 * stories import the component and nothing else — no `@/lib/api`, whose
 * value exports this component deliberately does not touch either.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { MetricsStrip, readRunMetrics } from "./MetricsStrip";

/** `job.succeeded.json` — every field reported. */
const SUCCEEDED = readRunMetrics({
  iterations: 2,
  quality_score: 0.86,
  cost_usd: 0.42,
  llm_calls: 11,
  elapsed_sec: 60.0,
});

/**
 * `job.failed_partial.json` — the run that failed with a briefing retained.
 *
 * `quality_score` is `null` because the run never got to score itself, and
 * the other four survived: $0.1800 across 4 LLM calls is the money 03 §8.1
 * says a hidden export throws away. One dash among four numbers is also the
 * case that matters most for criterion 2 — the reader has to be able to tell
 * "not reported" from "zero" at a glance.
 */
const PARTIAL = readRunMetrics({
  iterations: 1,
  quality_score: null,
  cost_usd: 0.18,
  llm_calls: 4,
  elapsed_sec: 36.0,
});

/** A run that reported nothing about itself. Every field is optional. */
const NONE = readRunMetrics({});

const meta = {
  title: "Patterns/MetricsStrip",
  component: MetricsStrip,
  args: { metrics: SUCCEEDED },
  render: (args) => (
    <div className="max-w-2xl p-6">
      <MetricsStrip {...args} />
    </div>
  ),
} satisfies Meta<typeof MetricsStrip>;

export default meta;
type Story = StoryObj<typeof meta>;

/** The five real fields, mono numerals, no dash and therefore no legend. */
export const AllPresent: Story = { args: { metrics: SUCCEEDED } };

/**
 * Criterion 2 at full strength: five em dashes and one visible explanation.
 * The rows stay — a strip that hid its missing fields would let the reader
 * think the run reported four numbers instead of none.
 */
export const AllNull: Story = { args: { metrics: NONE } };

/** 03 §2.2 row 14's numbers: one field missing, four paid for. */
export const PartialFailureMetrics: Story = { args: { metrics: PARTIAL } };

/** 03 §2.2 row 8 — the same strip on the dark token set. */
export const Dark: Story = {
  args: { metrics: PARTIAL },
  globals: { theme: "dark" },
};

/**
 * The dash survives without colour. `--color-ink-muted` is the only thing
 * separating a missing number from a present one visually, and 03 §3.4 says
 * colour may never be the sole carrier — here it is not, because the word
 * "dash" is spelled out in the legend and "not reported" is in the
 * accessibility tree.
 */
export const ForcedColours: Story = {
  args: { metrics: PARTIAL },
  globals: { theme: "forced-colors" },
};
