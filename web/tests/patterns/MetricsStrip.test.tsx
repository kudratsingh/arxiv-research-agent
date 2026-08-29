/**
 * WO-19 criteria 1 and 2 — the metrics strip.
 *
 * THE NUMBERS COME OUT OF THE RECORDED FIXTURES, not out of this file.
 * `job.succeeded` and `job.failed_partial` are responses recorded against
 * the local stack (`web/contract/fixtures/`, `authored: false`), so what the
 * strip is asserted to render is what the API actually returns — including
 * `job.failed_partial`'s `quality_score: null`, which is the null state
 * criterion 2 is about and is a fact about the contract rather than a case
 * somebody imagined.
 *
 * The computed-style block reads `app/tokens.css` and
 * `components/patterns/metrics.css` off disk and injects them, because the
 * `unit` project runs with `css: false`. The three jsdom limits that forces
 * are documented in `tests/primitives/support/css.ts`; nothing here restates
 * a value from either stylesheet, it resolves them.
 */

import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  MetricsStrip,
  formatCost,
  formatCount,
  formatDuration,
  formatScore,
  readRunMetrics,
  type RunMetricsSource,
} from "@/components/patterns/MetricsStrip";
import { ReportReader } from "@/components/patterns/ReportReader";
import type { JobDetail } from "@/lib/api";
import { METRICS } from "@/lib/copy/metrics";
import { NOT_REPORTED } from "@/lib/copy/errors";
import { BRIEFING } from "@/lib/copy/run";
import { loadReportRenderer, type ReportRenderer } from "@/lib/report/renderer";
import { font } from "@/lib/tokens";

import {
  customProperties,
  installStylesheet,
  readWebFile,
  ruleBody,
  stripComments,
} from "../primitives/support/css";
import { loadFixture } from "../support/msw";
import { render, screen, waitFor, within } from "../support/render";

// ---------------------------------------------------------------------------
// The recorded runs.
// ---------------------------------------------------------------------------

const SUCCEEDED = loadFixture("job.succeeded").body as RunMetricsSource;
const PARTIAL = loadFixture("job.failed_partial").body as RunMetricsSource;

/**
 * `JobDetail` really is a `RunMetricsSource`.
 *
 * `MetricsStrip` declares the five fields structurally rather than importing
 * the generated type (see the note on `RunMetricsSource`), so this
 * assignment is the check that keeps the two in step: rename `cost_usd`
 * upstream and `npm run typecheck` fails here rather than the strip quietly
 * rendering a dash for a number the API sent.
 */
const CONTRACT_SHAPE: (detail: JobDetail) => RunMetricsSource = (detail) => detail;

/** Every `dd`, keyed by the field it reports. */
function values(container: HTMLElement): Record<string, HTMLElement> {
  const found: Record<string, HTMLElement> = {};
  for (const element of Array.from(container.querySelectorAll<HTMLElement>("dd[data-field]"))) {
    found[element.dataset.field as string] = element;
  }
  return found;
}

// ===========================================================================
// Criterion 1 — five real fields, in a <dl>, in JobSummary's order.
// ===========================================================================

describe("criterion 1 — the five fields", () => {
  it("renders exactly five dt/dd pairs inside one dl", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);

    const lists = container.querySelectorAll("dl");
    expect(lists).toHaveLength(1);
    expect(container.querySelectorAll("dt")).toHaveLength(5);
    expect(container.querySelectorAll("dd")).toHaveLength(5);
  });

  it("labels them with the dictionary's words, in JobSummary's order", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);

    // `JobSummary.tsx:12-16` — the order RC-21 preserves.
    expect(
      Array.from(container.querySelectorAll("dt")).map((node) => node.textContent),
    ).toEqual([
      METRICS.iterationsLabel,
      METRICS.qualityLabel,
      METRICS.costLabel,
      METRICS.callsLabel,
      METRICS.durationLabel,
    ]);
  });

  it("renders the recorded succeeded run's five numbers, formatted", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    const dd = values(container);

    expect(dd.iterations).toHaveTextContent(formatCount(SUCCEEDED.iterations as number));
    expect(dd.qualityScore).toHaveTextContent(formatScore(SUCCEEDED.quality_score as number));
    expect(dd.costUsd).toHaveTextContent(formatCost(SUCCEEDED.cost_usd as number));
    expect(dd.llmCalls).toHaveTextContent(formatCount(SUCCEEDED.llm_calls as number));
    expect(dd.elapsedSec).toHaveTextContent(formatDuration(SUCCEEDED.elapsed_sec as number));

    // The formats themselves, pinned to the values JobSummary produced.
    expect(dd.costUsd?.textContent).toBe("$0.4200");
    expect(dd.qualityScore?.textContent).toBe("0.86");
    expect(dd.elapsedSec?.textContent).toBe("60.0s");
  });

  it("names the region, so five bare numbers are not read out unattributed", () => {
    render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    expect(screen.getByRole("region", { name: METRICS.label })).toBeInTheDocument();
  });

  it("takes an id and a className without losing its own", () => {
    const { container } = render(
      <MetricsStrip metrics={readRunMetrics(SUCCEEDED)} id="strip" className="mine" />,
    );
    const strip = container.querySelector("#strip") as HTMLElement;
    expect(strip.className).toContain("ew-metrics");
    expect(strip.className).toContain("mine");
  });
});

// ===========================================================================
// Criterion 1, second clause — ATTACHED BENEATH THE BRIEFING.
// ===========================================================================

describe("criterion 1 — position, not just presence", () => {
  let renderer: ReportRenderer;

  beforeAll(async () => {
    renderer = await loadReportRenderer();
  });

  /**
   * The claim 03 §4.7 makes is about POSITION — "attached beneath the
   * briefing they describe rather than floating as a dashboard row" — and
   * `JobSummary` fails it by being rendered above the report
   * (`ConversationThread.tsx:239`, then `:242`). So the assertion is a
   * document-order comparison against the briefing body, not the presence of
   * a class name.
   */
  it("follows the briefing in document order, never precedes it", async () => {
    const { container } = render(
      <ReportReader
        markdown={"# Briefing\n\nBody."}
        renderer={renderer}
        metrics={<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />}
      />,
    );

    await waitFor(() => {
      expect(container.querySelector("[data-briefing]")).not.toBeNull();
    });

    const body = container.querySelector("[data-briefing]") as HTMLElement;
    const strip = container.querySelector("[data-metrics]") as HTMLElement;

    expect(
      body.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // And the strip is not INSIDE the reading column either: it describes the
    // briefing, it is not part of the document.
    expect(body.contains(strip)).toBe(false);
  });
});

// ===========================================================================
// Criterion 2 — the em dash, its explanation, and what it is not.
// ===========================================================================

describe("criterion 2 — a missing number", () => {
  it("renders an em dash, not a hyphen-minus", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics({})} />);

    for (const dd of Object.values(values(container))) {
      expect(dd.textContent).toContain("—");
      // `JobSummary.tsx:36` renders "-", which reads as a minus sign in a
      // column of figures.
      expect(dd.textContent).not.toContain("-");
    }
  });

  it("explains the dash in visible text, and never in a title attribute", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(PARTIAL)} />);

    expect(screen.getByText(METRICS.absentNote)).toBeInTheDocument();
    // 03 §4.7 asks for a "title-free explanation": a title is unreachable by
    // keyboard, invisible on touch and unread by most screen readers.
    expect(container.querySelectorAll("[title]")).toHaveLength(0);
  });

  it("does not print a legend for a symbol that is not on screen", () => {
    render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    expect(screen.queryByText(METRICS.absentNote)).toBeNull();
  });

  it("says the words to a screen reader and hides the glyph from it", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(PARTIAL)} />);
    const quality = values(container).qualityScore as HTMLElement;

    expect(quality.dataset.reported).toBe("false");
    expect(within(quality).getByText(METRICS.absent)).toHaveAttribute("aria-hidden", "true");
    expect(within(quality).getByText(NOT_REPORTED)).toBeInTheDocument();
  });

  it("keeps the four numbers the failed run did report", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(PARTIAL)} />);
    const dd = values(container);

    // 03 §8.1: "$0.1800 and 4 LLM calls" is the work already paid for.
    expect(dd.costUsd?.textContent).toBe("$0.1800");
    expect(dd.llmCalls?.textContent).toBe("4");
    expect(dd.iterations?.textContent).toBe("1");
    expect(dd.elapsedSec?.textContent).toBe("36.0s");
    expect(dd.qualityScore?.dataset.reported).toBe("false");
  });

  it("flags the strip itself, so a composition can see there is a dash in it", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    expect(container.querySelector("[data-metrics]")).toHaveAttribute("data-absent", "false");

    const partial = render(<MetricsStrip metrics={readRunMetrics(PARTIAL)} />);
    expect(partial.container.querySelector("[data-metrics]")).toHaveAttribute(
      "data-absent",
      "true",
    );
  });
});

// ===========================================================================
// readRunMetrics — the one adapter between JobDetail and this pattern.
// ===========================================================================

describe("readRunMetrics", () => {
  it("maps the five snake_case fields onto the five props", () => {
    expect(readRunMetrics(SUCCEEDED)).toEqual({
      iterations: 2,
      qualityScore: 0.86,
      costUsd: 0.42,
      llmCalls: 11,
      elapsedSec: 60,
    });
  });

  it("treats an absent field as not reported", () => {
    expect(readRunMetrics({})).toEqual({
      iterations: null,
      qualityScore: null,
      costUsd: null,
      llmCalls: null,
      elapsedSec: null,
    });
  });

  it("treats a non-finite number as not reported, rather than rendering NaN", () => {
    const metrics = readRunMetrics({
      cost_usd: Number.NaN,
      elapsed_sec: Number.POSITIVE_INFINITY,
      iterations: 0,
    });
    expect(metrics.costUsd).toBeNull();
    expect(metrics.elapsedSec).toBeNull();
    // Zero is a number the run reported, and it is not absent.
    expect(metrics.iterations).toBe(0);
  });

  it("accepts a JobDetail, structurally", () => {
    // The assignment is the assertion; it is checked by `npm run typecheck`.
    expect(typeof CONTRACT_SHAPE).toBe("function");
  });
});

// ===========================================================================
// The formats, carried over from JobSummary unchanged.
// ===========================================================================

describe("formats", () => {
  it("prints cost to four places, because a run can cost $0.0002", () => {
    expect(formatCost(0.0002)).toBe("$0.0002");
    expect(formatCost(0)).toBe("$0.0000");
  });

  it("prints quality to two and duration to one", () => {
    expect(formatScore(0.8649)).toBe("0.86");
    expect(formatDuration(36)).toBe("36.0s");
  });

  it("prints counts as they arrived", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(11)).toBe("11");
  });
});

// ===========================================================================
// Criterion 1, third clause — MONO NUMERALS.
// ===========================================================================

describe("criterion 1 — mono numerals", () => {
  const tokensCss = readWebFile("app/tokens.css");
  // Stripped, because this file documents itself by quoting its own
  // selectors in prose (`tests/primitives/support/css.ts`).
  const stripCss = stripComments(readWebFile("components/patterns/metrics.css"));
  const tokens = customProperties(tokensCss);
  let sheet: HTMLStyleElement;

  beforeEach(() => {
    sheet = installStylesheet(`${tokensCss}\n${stripCss}`);
  });

  afterEach(() => {
    sheet.remove();
  });

  /**
   * The family is asserted through the utility, because that is where it is.
   *
   * `web/tests/fonts.test.ts` (WO-02 criterion 6) allows a family
   * declaration in app/tokens.css and nowhere else in the repository, so a
   * pattern's stylesheet cannot carry one and the element takes Tailwind's
   * `font-mono` / `font-ui` instead. Those utilities are generated at build
   * time from `lib/tokens.ts` — which is the second half of this assertion,
   * and is what makes "carries the class" mean "is set in the mono stack".
   * `web/tests/tokens.test.ts` asserts the config↔token mapping in both
   * directions; nothing here restates a stack.
   */
  it("sets the numerals in the mono family and the labels in the UI one", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);

    const value = container.querySelector(".ew-metrics__value") as HTMLElement;
    const label = container.querySelector(".ew-metrics__label") as HTMLElement;
    const note = render(
      <MetricsStrip metrics={readRunMetrics(PARTIAL)} />,
    ).container.querySelector(".ew-metrics__note") as HTMLElement;

    expect(value.className.split(/\s+/)).toContain("font-mono");
    // 03 §3.5: the chrome around a number is not set in the number's family.
    expect(label.className.split(/\s+/)).toContain("font-ui");
    expect(note.className.split(/\s+/)).toContain("font-ui");

    expect(font.mono).toBe("var(--font-mono)");
    expect(font.ui).toBe("var(--font-ui)");
    expect(tokens.get("--font-mono")).toBeTruthy();
    expect(tokens.get("--font-mono")).not.toBe(tokens.get("--font-ui"));
  });

  /**
   * `font-variant-numeric` is asserted against the committed declaration
   * rather than against `getComputedStyle`, and the reason is jsdom's, not a
   * preference: cssstyle implements a bounded set of properties and drops
   * the ones it does not know on the way into a computed declaration, so a
   * computed assertion here would pass on an empty string. The element under
   * test is still shown to carry the class the rule is written for, which is
   * the other half of the claim.
   */
  it("lines the figures up, which is the half a family alone does not buy", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    const value = container.querySelector(".ew-metrics__value") as HTMLElement;

    expect(value).not.toBeNull();
    expect(ruleBody(stripCss, ".ew-metrics__value")).toContain(
      "font-variant-numeric: tabular-nums;",
    );
  });

  it("is attached by a rule rather than boxed as a card", () => {
    const { container } = render(<MetricsStrip metrics={readRunMetrics(SUCCEEDED)} />);
    const list = container.querySelector(".ew-metrics__list") as HTMLElement;

    expect(getComputedStyle(list).borderTopWidth).toBe("1px");

    // `JobSummary.tsx:11` is `rounded-md border ... bg-white p-4`: a card.
    // 03 §4.7 rules that out, so neither the strip nor its list may declare
    // a fill, a radius or an elevation.
    for (const selector of [".ew-metrics", ".ew-metrics__list"]) {
      expect(ruleBody(stripCss, selector)).not.toMatch(
        /background|box-shadow|border-radius|border-bottom/,
      );
    }
  });
});

// ===========================================================================
// The dictionary is the single edit site (WO-12 criterion 1).
// ===========================================================================

describe("copy", () => {
  it("uses WO-12's words, character for character", () => {
    // The strip and `BRIEFING` cannot drift; `tests/copy/metrics-copy.test.ts`
    // asserts the whole set, and this is the render-side half of it.
    expect(METRICS.label).toBe(BRIEFING.metricsLabel);
    expect(METRICS.costLabel).toBe(BRIEFING.costLabel);
  });
});
