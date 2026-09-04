/**
 * WO-18 criteria 1, 2, 3, 5, 6, 7, 8 and 9 — the reading surface.
 *
 * Every test below drives the REAL Markdown pipeline. `loadReportRenderer()`
 * is the product's own dynamic import, so what these assertions inspect is
 * what a browser renders — there is no stub renderer in this file, which is
 * the only way criterion 3's "no raw HTML passthrough" can mean anything.
 *
 * The computed-style tests read `web/app/tokens.css` off disk and inject it,
 * because the `unit` project runs with `css: false`. The three jsdom limits
 * that forces are documented in `tests/primitives/support/css.ts`; nothing
 * here restates a value from the stylesheet, it resolves them.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { afterEach, beforeAll, beforeEach, describe, expect, it } from "vitest";

import {
  ReportReader,
  headingKey,
  headingSlug,
  readHeadings,
} from "@/components/patterns/ReportReader";
import { REPORT, codeRegionLabel, tableRegionLabel } from "@/lib/copy/report";
import { loadReportRenderer, type ReportRenderer } from "@/lib/report/renderer";

import {
  WEB_ROOT,
  customProperties,
  installStylesheet,
  readWebFile,
  resolveComputed,
  stripComments,
} from "../primitives/support/css";
import { loadFixture } from "../support/msw";
import { render, screen, waitFor, within } from "../support/render";

// ---------------------------------------------------------------------------
// The one renderer, loaded once for the whole file.
// ---------------------------------------------------------------------------

let renderer: ReportRenderer;

beforeAll(async () => {
  renderer = await loadReportRenderer();
});

/** Render a briefing and wait for the heading pass to settle. */
async function readBriefing(
  markdown: string,
  props: Partial<React.ComponentProps<typeof ReportReader>> = {},
  options: Parameters<typeof render>[1] = {},
) {
  const result = render(
    <ReportReader markdown={markdown} renderer={renderer} {...props} />,
    options,
  );
  await waitFor(() => {
    expect(result.container.querySelector("[data-briefing]")).not.toBeNull();
  });
  return result;
}

const briefing = (container: HTMLElement): HTMLElement =>
  container.querySelector("[data-briefing]") as HTMLElement;

// ---------------------------------------------------------------------------
// Sample documents.
// ---------------------------------------------------------------------------

const HEADINGS = [
  "# Faithfulness",
  "",
  "Opening paragraph.",
  "",
  "## What the field measures",
  "",
  "Body.",
  "",
  "### Automatic metrics",
  "",
  "Body.",
  "",
  "## Limits",
  "",
  "Body.",
  "",
  "#### Deeper than the rail goes",
  "",
  "Body.",
].join("\n");

const NO_HEADINGS = [
  "Three of the eleven papers separate support from accuracy.",
  "",
  "Nothing else does.",
].join("\n");

const GFM = [
  "| Benchmark | Agreement |",
  "| --- | --- |",
  "| Alpha | 0.71 |",
  "| Beta | not reported |",
  "",
  "~~Retracted~~ and replaced.",
  "",
  "- [x] read",
  "- [ ] verified",
].join("\n");

const TWO_TABLES = [
  "| A | B |",
  "| --- | --- |",
  "| 1 | 2 |",
  "",
  "| C | D |",
  "| --- | --- |",
  "| 3 | 4 |",
].join("\n");

const CODE = ["```bash", "python -m src.eval.faithfulness --strict", "```"].join("\n");

/** The two shapes an LLM-authored briefing could smuggle markup in as. */
const RAW_HTML = [
  "<script>window.__owned = true;</script>",
  "",
  "<img src=x onerror=\"window.__owned = true\">",
  "",
  "Ordinary paragraph.",
].join("\n");

const FAILED_PARTIAL = loadFixture("job.failed_partial").body as {
  result: string;
  error: string;
  error_type: string;
};

// ===========================================================================
// Criterion 2 — exactly one Markdown renderer.
// ===========================================================================

describe("criterion 2 — one renderer, and one only", () => {
  /**
   * The two legacy components WO-20 stopped composing and WO-31 DELETED.
   *
   * They were named rather than globbed precisely so that this list would
   * empty on the day they went, rather than silently go on covering
   * something new — and that day is this commit. The list is kept, empty,
   * because the assertion below is now the strong form of criterion 2:
   * `lib/report/renderer.ts` is the ONLY importer of `react-markdown` in
   * the whole tree, full stop, with no exception carried for anything.
   */
  const LEGACY_RENDERERS: string[] = [];

  /** What those two files were, so the deletion has a name here too. */
  const DELETED_RENDERERS = [
    "components/ConversationThread.tsx",
    "components/ReportView.tsx",
  ];

  /** The one module the new surface renders through. */
  const BOUNDARY = "lib/report/renderer.ts";

  const IMPORTS_MARKDOWN =
    /(?:^|[\s{,])from\s+["']react-markdown["']|import\(\s*["']react-markdown["']\s*\)/m;

  function sourceFiles(): string[] {
    const roots = ["app", "components", "lib"].map((entry) =>
      path.join(WEB_ROOT, entry),
    );
    const found: string[] = [];
    const walk = (directory: string): void => {
      for (const entry of readdirSync(directory)) {
        const absolute = path.join(directory, entry);
        if (statSync(absolute).isDirectory()) walk(absolute);
        else if (/\.tsx?$/.test(entry)) found.push(path.relative(WEB_ROOT, absolute));
      }
    };
    for (const root of roots) walk(root);
    return found.sort();
  }

  it("is imported by exactly one module in the whole tree", () => {
    const importers = sourceFiles().filter((relative) =>
      IMPORTS_MARKDOWN.test(readFileSync(path.join(WEB_ROOT, relative), "utf8")),
    );
    expect(importers).toEqual([...LEGACY_RENDERERS, BOUNDARY].sort());
  });

  it("is not reachable from any pattern or feature but through that module", () => {
    const surfaces = sourceFiles().filter(
      (relative) =>
        relative.startsWith("components/patterns/") ||
        relative.startsWith("components/features/") ||
        relative.startsWith("app/"),
    );
    expect(surfaces.length).toBeGreaterThan(0);
    for (const relative of surfaces) {
      const source = readFileSync(path.join(WEB_ROOT, relative), "utf8");
      expect(IMPORTS_MARKDOWN.test(source), relative).toBe(false);
    }
  });

  it("is not vacuous: the boundary really imports it, and the legacy pair is gone", () => {
    // This test used to guard against WO-31 landing before the list above
    // was updated — an empty LEGACY_RENDERERS would have made the assertion
    // green for the wrong reason. WO-31 has landed, so the guard inverts:
    // the ONE importer must really import react-markdown (otherwise the
    // regex has drifted and "exactly one" means nothing), and the two files
    // that used to be exempted must really be gone (otherwise they were
    // dropped from the list rather than from the tree).
    const boundary = readFileSync(path.join(WEB_ROOT, BOUNDARY), "utf8");
    expect(IMPORTS_MARKDOWN.test(boundary), BOUNDARY).toBe(true);

    for (const relative of DELETED_RENDERERS) {
      expect(existsSync(path.join(WEB_ROOT, relative)), relative).toBe(false);
    }
  });

  it("renders identical DOM for a current turn and a historical turn", async () => {
    // The divergence 04 §5.1 records is exactly this: `ReportView.tsx:39-48`
    // wraps the body in a bordered card with an export control inside it,
    // `ConversationThread.tsx:301-306` does not, and nothing stops the two
    // drifting further. Here the two configurations differ in every
    // surrounding prop a surface can set — a failure banner, an actions slot,
    // a metrics slot — and the briefing itself is byte-identical.
    const historical = await readBriefing(HEADINGS);
    const current = await readBriefing(HEADINGS, {
      failure: { errorType: FAILED_PARTIAL.error_type, error: FAILED_PARTIAL.error },
      actions: <button type="button">x</button>,
      metrics: <dl />,
    });

    expect(briefing(current.container).innerHTML).toBe(
      briefing(historical.container).innerHTML,
    );
    expect(briefing(historical.container).innerHTML).toContain("What the field measures");
  });
});

// ===========================================================================
// Criterion 3 — GFM, and no raw HTML passthrough (MUST-KEEP 7).
// ===========================================================================

describe("criterion 3 — GFM without raw HTML", () => {
  it("renders a <script> as text and never as an element", async () => {
    const { container } = await readBriefing(RAW_HTML);

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(briefing(container).textContent).toContain("window.__owned = true;");
    expect(briefing(container).textContent).toContain("onerror");
    expect((globalThis as Record<string, unknown>).__owned).toBeUndefined();
  });

  it("still parses the GFM the synthesizer emits", async () => {
    const { container } = await readBriefing(GFM);
    const body = briefing(container);

    expect(body.querySelector("table")).not.toBeNull();
    expect(body.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(body.querySelector("del")?.textContent).toBe("Retracted");
    expect(body.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
  });
});

// ===========================================================================
// Criterion 4 — the section rail is read off the rendered headings.
// ===========================================================================

describe("criterion 4 — the rail is derived, never declared", () => {
  it("lists exactly the h2 and h3 the report rendered, in order", async () => {
    const { container } = await readBriefing(HEADINGS);
    const rail = await screen.findByRole("navigation", { name: REPORT.railLabel });
    const links = within(rail).getAllByRole("link");

    expect(links.map((link) => link.textContent)).toEqual([
      "What the field measures",
      "Automatic metrics",
      "Limits",
    ]);
    // The h1 is the document's own title and the h4 is below the rail's
    // depth; neither is a section the rail claims exists.
    expect(container.querySelector("h1")?.textContent).toBe("Faithfulness");
    expect(within(rail).queryByText("Faithfulness")).toBeNull();
    expect(within(rail).queryByText("Deeper than the rail goes")).toBeNull();
  });

  it("points every link at a heading that is really in the document", async () => {
    const { container } = await readBriefing(HEADINGS);
    const rail = await screen.findByRole("navigation", { name: REPORT.railLabel });

    for (const link of within(rail).getAllByRole("link")) {
      const fragment = (link.getAttribute("href") ?? "").slice(1);
      expect(fragment).not.toBe("");
      const target = container.querySelector(`[data-briefing] [id="${fragment}"]`);
      expect(target, fragment).not.toBeNull();
      expect(target?.textContent).toBe(link.textContent);
    }
  });

  it("leaves the rail ABSENT for a heading-free report, not empty-shelled", async () => {
    const { container } = await readBriefing(NO_HEADINGS);

    // Give the heading effect every chance to add something.
    await waitFor(() => {
      expect(briefing(container).textContent).toContain("eleven papers");
    });
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(container.querySelector(".ew-section-rail")).toBeNull();
    expect(container.querySelector("nav")).toBeNull();
  });

  it("marks the active heading, and only when one is given", async () => {
    const { container } = await readBriefing(HEADINGS, { activeHeadingId: "limits" });
    const rail = await screen.findByRole("navigation", { name: REPORT.railLabel });

    const current = within(rail).getAllByRole("link").filter(
      (link) => link.getAttribute("aria-current") === "location",
    );
    expect(current.map((link) => link.textContent)).toEqual(["Limits"]);
    expect(container.querySelectorAll('[aria-current="location"]')).toHaveLength(1);
  });
});

describe("criterion 4 — the derivation itself", () => {
  it("numbers colliding slugs so two sections named the same are both reachable", () => {
    const root = document.createElement("div");
    root.innerHTML = "<h2>Limits</h2><h3>Limits</h3><h2>Limits</h2>";
    expect(readHeadings(root).map((heading) => heading.id)).toEqual([
      "limits",
      "limits-2",
      "limits-3",
    ]);
  });

  it("keeps the tag as the level and skips a heading with no text", () => {
    const root = document.createElement("div");
    root.innerHTML = "<h2>Alpha</h2><h3>  </h3><h3>Beta</h3>";
    expect(readHeadings(root)).toEqual([
      { id: "alpha", text: "Alpha", level: 2 },
      { id: "beta", text: "Beta", level: 3 },
    ]);
  });

  it("falls back rather than transliterating a heading it cannot slug", () => {
    expect(headingSlug("What the field measures")).toBe("what-the-field-measures");
    expect(headingSlug("  Limits  ")).toBe("limits");
    expect(headingSlug("→ ✦ →")).toBe("section");
  });

  it("is idempotent, so a re-run of the effect changes nothing", () => {
    const root = document.createElement("div");
    root.innerHTML = "<h2>Limits</h2><h2>Limits</h2>";
    expect(readHeadings(root)).toEqual(readHeadings(root));
    expect(root.querySelector("h2")?.id).toBe("limits");
  });

  it("keys a heading list so an unchanged one cannot loop the effect", () => {
    const root = document.createElement("div");
    root.innerHTML = "<h2>Alpha</h2><h3>Beta</h3>";
    const first = readHeadings(root);

    expect(headingKey(first)).toBe(headingKey(readHeadings(root)));
    expect(headingKey([])).toBe("");
    // Every field is in the key: a renamed, re-levelled or re-slugged
    // heading is a different rail.
    expect(headingKey(first)).not.toBe(
      headingKey([{ ...(first[0] as (typeof first)[number]), level: 3 }]),
    );
  });

  it("re-renders without churning the rail when the report has not changed", async () => {
    const { rerender } = await readBriefing(HEADINGS);
    const before = (await screen.findByRole("navigation", { name: REPORT.railLabel }))
      .innerHTML;

    rerender(<ReportReader markdown={HEADINGS} renderer={renderer} activeHeadingId={null} />);
    rerender(<ReportReader markdown={HEADINGS} renderer={renderer} />);

    const rail = await screen.findByRole("navigation", { name: REPORT.railLabel });
    expect(rail.innerHTML).toBe(before);
    expect(screen.getAllByRole("navigation")).toHaveLength(1);
  });

  it("rebuilds the rail when the briefing itself changes", async () => {
    const { rerender, container } = await readBriefing(HEADINGS);
    expect(
      within(await screen.findByRole("navigation")).getAllByRole("link"),
    ).toHaveLength(3);

    rerender(<ReportReader markdown={NO_HEADINGS} renderer={renderer} />);
    await waitFor(() => {
      expect(container.querySelector("nav")).toBeNull();
    });

    rerender(<ReportReader markdown={"## Only one"} renderer={renderer} />);
    await waitFor(() => {
      expect(
        within(screen.getByRole("navigation")).getAllByRole("link"),
      ).toHaveLength(1);
    });
  });
});

// ===========================================================================
// Criterion 6 — wide tables and code blocks pan; the page does not.
// ===========================================================================

describe("criterion 6 — the table pans inside a labelled region", () => {
  it("wraps every table in its own named, focusable ScrollRegion", async () => {
    const { container } = await readBriefing(TWO_TABLES);

    const first = screen.getByRole("region", { name: tableRegionLabel(1) });
    const second = screen.getByRole("region", { name: tableRegionLabel(2) });
    expect(within(first).getByRole("table")).toBeInTheDocument();
    expect(within(second).getByRole("table")).toBeInTheDocument();
    // Focusable, or a keyboard user cannot pan it (SC 2.1.1).
    for (const region of [first, second]) {
      expect(region).toHaveAttribute("tabindex", "0");
      expect(region.className).toContain("ew-scroll-region");
    }
    expect(container.querySelectorAll("table")).toHaveLength(2);
  });

  it("does the same for a fenced code block", async () => {
    const { container } = await readBriefing(CODE);
    const region = screen.getByRole("region", { name: codeRegionLabel(1) });

    expect(within(region).getByText(/faithfulness --strict/)).toBeInTheDocument();
    expect(region.querySelector("pre")).not.toBeNull();
    expect(container.querySelectorAll("pre")).toHaveLength(1);
  });

  it("keeps a table's ordinal stable across a re-render", async () => {
    const { rerender } = await readBriefing(TWO_TABLES);
    rerender(<ReportReader markdown={TWO_TABLES} renderer={renderer} activeHeadingId="x" />);

    expect(screen.getByRole("region", { name: tableRegionLabel(1) })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: tableRegionLabel(2) })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: tableRegionLabel(3) })).toBeNull();
  });
});

// ===========================================================================
// Criteria 5, 7 and 8 — the computed reading surface.
// ===========================================================================

describe("criteria 5, 7, 8 — computed styles", () => {
  const tokensCss = readWebFile("app/tokens.css");
  const tokens = customProperties(tokensCss);
  let sheet: HTMLStyleElement;

  beforeEach(() => {
    sheet = installStylesheet(tokensCss);
  });

  afterEach(() => {
    sheet.remove();
  });

  /**
   * The two stacks, read out of app/tokens.css rather than spelled here.
   *
   * `web/tests/fonts.test.ts` forbids naming a family anywhere but the four
   * files that compose the stacks, and it is right to: a family name typed
   * into a test is a second source of truth for which face the report is set
   * in. Comparing against the declaration makes the assertion stronger as
   * well as legal — it fails if the stack is edited, not only if the wrong
   * one is applied.
   */
  /** jsdom drops the spaces after the commas; the layers are what matter. */
  const layers = (stack: string): string =>
    stack.replace(/\s*,\s*/g, ",").trim();

  const REPORT_STACK = layers(tokens.get("--font-report") as string);
  const UI_STACK = layers(tokens.get("--font-ui") as string);

  it("criterion 5 — the reading column is the report family at 68ch, 17/1.65", async () => {
    const { container } = await readBriefing(HEADINGS);
    const column = briefing(container);

    expect(resolveComputed(column, "max-width", tokens)).toBe("68ch");
    expect(resolveComputed(column, "font-size", tokens)).toBe("17px");
    expect(resolveComputed(column, "line-height", tokens)).toBe("1.65");

    expect(REPORT_STACK).toBeTruthy();
    expect(REPORT_STACK).not.toBe(UI_STACK);
    expect(layers(resolveComputed(column, "font-family", tokens))).toBe(REPORT_STACK);
  });

  it("criterion 5 — the chrome around it is the UI family, and never the report one", async () => {
    const { container } = await readBriefing(HEADINGS);

    const title = container.querySelector(".ew-report-reader__title") as HTMLElement;
    const rail = (await screen.findByRole("navigation", {
      name: REPORT.railLabel,
    })) as HTMLElement;

    for (const element of [title, rail]) {
      const family = layers(resolveComputed(element, "font-family", tokens));
      expect(family).toBe(UI_STACK);
      expect(family).not.toBe(REPORT_STACK);
    }
  });

  it("criterion 7 — code, th and td are themed by tokens in BOTH directions", async () => {
    const surfaces = async (theme: "light" | "dark") => {
      const { container, unmount } = await readBriefing(GFM + "\n\nInline `code` here.", {}, {
        theme,
      });
      const body = briefing(container);
      const read = {
        code: resolveComputed(
          body.querySelector("code") as HTMLElement,
          "background-color",
          tokens,
        ),
        th: resolveComputed(
          body.querySelector("th") as HTMLElement,
          "background-color",
          tokens,
        ),
        td: resolveComputed(
          body.querySelector("td") as HTMLElement,
          "border-top-color",
          tokens,
        ),
        sunken: getComputedStyle(document.documentElement)
          .getPropertyValue("--color-sunken")
          .trim(),
        borderSubtle: getComputedStyle(document.documentElement)
          .getPropertyValue("--color-border-subtle")
          .trim(),
      };
      unmount();
      return read;
    };

    const light = await surfaces("light");
    const dark = await surfaces("dark");

    // Each of the three resolves to the token, not to a hard-coded value.
    for (const measured of [light, dark]) {
      expect(measured.sunken).not.toBe("");
      expect(measured.code).toBe(measured.sunken);
      expect(measured.th).toBe(measured.sunken);
      expect(measured.td).toBe(measured.borderSubtle);
    }
    // And the two themes really are different, which is the whole of the
    // 03 §3.3 gap: globals.css:33-58 covers these three under
    // prefers-color-scheme only, so a persisted override does not reach them.
    expect(dark.sunken).not.toBe(light.sunken);
    expect(dark.code).not.toBe(light.code);
    expect(dark.th).not.toBe(light.th);
    expect(dark.td).not.toBe(light.td);
  });

  it("criterion 7 — the fix is token resolution, not a second media query", () => {
    const fence = stripComments(tokensCss).slice(
      stripComments(tokensCss).indexOf(".ew-report-reader"),
    );
    expect(fence).not.toContain("prefers-color-scheme");
    // The legacy block is left standing until WO-31, and is not ours.
    expect(readWebFile("app/globals.css")).toContain("prefers-color-scheme");
  });

  it("criterion 8 — emphasis renders in the committed italic face, not a synthesised one", async () => {
    const { container } = await readBriefing("Support is *not* accuracy.");
    const emphasis = briefing(container).querySelector("em") as HTMLElement;

    expect(emphasis.textContent).toBe("not");
    // RC-20's whole point: with a real face available the browser must be
    // told not to slant the roman instead.
    const stripped = stripComments(tokensCss);
    expect(stripped).toMatch(/\.ew-report\s*\{[^}]*font-synthesis-style:\s*none/);
    expect(stripped).toMatch(/\.ew-report em\s*\{[^}]*font-style:\s*italic/);

    // The face itself is committed and declared for the report family. The
    // file name is read out of app/fonts/fonts.ts rather than written here,
    // because web/tests/fonts.test.ts forbids naming a family outside the
    // four files that compose the stacks — and because a name typed into a
    // test would keep passing after the face was swapped.
    const fonts = readWebFile("app/fonts/fonts.ts");
    const reportBlock = fonts.slice(
      fonts.indexOf("export const fontReport"),
      fonts.indexOf("export const fontMono"),
    );
    expect(reportBlock).toContain('variable: "--font-report-face"');
    const italic = /path:\s*"\.\/([^"]+\.woff2)",\s*weight:\s*"400",\s*style:\s*"italic"/.exec(
      reportBlock,
    );
    expect(italic, "the report family declares no italic 400 face (RC-20)").not.toBeNull();
    expect(
      statSync(
        path.join(WEB_ROOT, "app", "fonts", (italic as RegExpExecArray)[1] as string),
      ).size,
    ).toBeGreaterThan(0);
  });
});

// ===========================================================================
// Criterion 1 — P5 / H5, against the committed failed-partial fixture.
// ===========================================================================

describe("criterion 1 — failure keeps the work", () => {
  it("renders the retained briefing with the failure banner ABOVE it", async () => {
    const { container } = await readBriefing(FAILED_PARTIAL.result, {
      failure: {
        errorType: FAILED_PARTIAL.error_type,
        error: FAILED_PARTIAL.error,
      },
    });

    const body = briefing(container);
    // The briefing the fixture retained is on screen, in full.
    expect(body.textContent).toContain("What remains useful");
    expect(body.textContent).toContain("Initial retrieval completed.");

    const banner = container.querySelector("[data-severity]") as HTMLElement;
    expect(banner).not.toBeNull();
    expect(banner.textContent).toContain(REPORT.partialWord);
    expect(banner.textContent).toContain(REPORT.partial);
    expect(banner.textContent).toContain(REPORT.partialDetail);

    // ABOVE, not merely present.
    expect(
      banner.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(container.querySelector("[data-report-reader]")).toHaveAttribute(
      "data-partial",
      "true",
    );
  });

  it("shows the backend's own strings under it, unedited (RC-16)", async () => {
    const { container } = await readBriefing(FAILED_PARTIAL.result, {
      failure: {
        errorType: FAILED_PARTIAL.error_type,
        error: FAILED_PARTIAL.error,
      },
    });

    const banner = container.querySelector("[data-severity]") as HTMLElement;
    expect(banner.textContent).toContain(FAILED_PARTIAL.error_type);
    expect(banner.textContent).toContain(FAILED_PARTIAL.error);
    // `verification_incomplete` is not one of the nine mapped values, so the
    // fall-through sentence is what the reader gets — plus the raw strings.
    expect(banner.textContent).toContain("The run failed.");
  });

  it("has no branch that suppresses a briefing, whatever the failure", async () => {
    // `ReportView.tsx:13-27` returns before the report for every failed job
    // that carries an `error`. Nine mapped error types and an unmapped one,
    // all with the same retained body: the body renders every time. The
    // five class names became ADR 0064 codes; the property under test is
    // unchanged.
    for (const errorType of [
      "hitl_timeout",
      "cost_budget_exceeded",
      "timeout",
      "orphaned",
      "not_found_papers",
      "upstream_arxiv",
      "upstream_paper_read",
      "upstream_model_output",
      "cancelled_job",
      "some_future_code",
    ]) {
      const { container, unmount } = await readBriefing(FAILED_PARTIAL.result, {
        failure: { errorType, error: FAILED_PARTIAL.error },
      });
      expect(briefing(container).textContent, errorType).toContain(
        "What remains useful",
      );
      unmount();
    }
  });

  it("says the true thing when the run failed with nothing retained (row 15)", async () => {
    const { container } = render(
      <ReportReader
        markdown=""
        renderer={renderer}
        failure={{
          errorType: FAILED_PARTIAL.error_type,
          error: FAILED_PARTIAL.error,
        }}
      />,
    );

    expect(container.querySelector("[data-briefing]")).toBeNull();
    expect(screen.getByText(REPORT.noBriefing)).toBeInTheDocument();
    // Not `REPORT.empty` — "One is written when the run finishes" is a
    // promise this run will never keep.
    expect(screen.queryByText(REPORT.empty)).toBeNull();
    expect(container.querySelector("[data-report-reader]")).toHaveAttribute(
      "data-partial",
      "false",
    );
  });

  it("says the other true thing when nothing has failed and nothing exists yet", () => {
    const { container } = render(<ReportReader markdown="" renderer={renderer} />);

    expect(screen.getByText(REPORT.empty)).toBeInTheDocument();
    expect(container.querySelector("[data-severity]")).toBeNull();
    expect(container.querySelector("[data-briefing]")).toBeNull();
  });
});

// ===========================================================================
// The loading state, and criterion 9's invariant.
// ===========================================================================

describe("the pipeline is still loading", () => {
  it("reserves the column with a still skeleton and says what is happening", () => {
    const { container } = render(<ReportReader markdown={HEADINGS} renderer={null} />);

    expect(container.querySelector('[aria-busy="true"]')).not.toBeNull();
    expect(screen.getByText(REPORT.loading)).toBeInTheDocument();
    expect(container.querySelector("[data-briefing]")).toBeNull();
    // 03 §3.7 forbids skeleton shimmer; WO-07's Skeleton has no animation at
    // all, and this surface adds none.
    expect(container.querySelector(".ew-skeleton")).not.toBeNull();
  });
});

describe("criterion 9 — one briefing on screen, once", () => {
  /**
   * THE HOOK FOR WO-21.
   *
   * The investigation item carried from `00-DISCOVERY.md` — "the terminal
   * path may render a successful report twice, once as the newly reloaded
   * historical turn and once as retained current-job detail" — is a ROUTE
   * property, not a component one, so the committed browser spec belongs to
   * WO-21's Playwright tier and the verdict is recorded in this work order's
   * PR body. What can be pinned here is the invariant that spec asserts
   * against: one `ReportReader` puts exactly one briefing in the document,
   * so any second copy on a route is the composer rendering the same job
   * twice and not this component duplicating it.
   */
  it("renders exactly one briefing article per reader", async () => {
    const { container } = await readBriefing(HEADINGS, {
      failure: { errorType: FAILED_PARTIAL.error_type, error: FAILED_PARTIAL.error },
      actions: <button type="button">x</button>,
      metrics: <dl />,
    });

    expect(container.querySelectorAll("[data-briefing]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-report-reader]")).toHaveLength(1);
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });
});
