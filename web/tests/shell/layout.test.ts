/**
 * WO-08 criteria 3, 5 and 7 — the parts of the repair that are CSS.
 *
 * WHY THIS FILE READS A STYLESHEET RATHER THAN A COMPUTED STYLE. jsdom
 * performs no layout and evaluates no media query, so `getComputedStyle`
 * inside a `@media (min-width: 1024px)` block returns nothing at all. The
 * honest options are (a) assert against the authored rules, or (b) claim
 * the property is covered when nothing checked it. This file does (a), the
 * same way web/tests/storybook.test.ts asserts .storybook/preview.css, and
 * says plainly which half of each criterion is still owed to WO-21:
 *
 *   criterion 3  `minmax(0, 1fr)` and `min-width: 0` in every mode — HERE.
 *                The rendered widths at 320/412/768/1024/1440 — WO-21.
 *   criterion 5  the structural cause of the horizontal pan — HERE.
 *                `scrollWidth <= clientWidth` — WO-21 (and the throwaway
 *                red→green run in this PR's body).
 *   criterion 7  `position: sticky` + `env(safe-area-inset-bottom)` below
 *                768px — HERE. That it clears the home indicator on a real
 *                iPhone — WO-21's `iPhone 15` project.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { COMPACT_QUERY, EXPANDED_QUERY } from "@/components/app/WorkbenchShell";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const WORKBENCH_CSS = readFileSync(
  path.join(WEB_ROOT, "components", "app", "workbench.css"),
  "utf8",
);
const TOKENS_CSS = readFileSync(path.join(WEB_ROOT, "app", "tokens.css"), "utf8");
const THEME_TOGGLE_CSS = readFileSync(
  path.join(WEB_ROOT, "components", "patterns", "ThemeToggle.css"),
  "utf8",
);

/** The body of one `@media (...)` block, by its condition. */
function mediaBlock(css: string, condition: string): string {
  const start = css.indexOf(`@media ${condition}`);
  expect(start, `no @media ${condition} block`).toBeGreaterThan(-1);
  let depth = 0;
  let index = css.indexOf("{", start);
  const open = index;
  for (; index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    else if (css[index] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, index);
    }
  }
  throw new Error(`unterminated @media ${condition}`);
}

/** The declarations of one rule, by selector. */
function rule(css: string, selector: string): string {
  const pattern = new RegExp(
    `(^|\\})\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`,
    "m",
  );
  const match = pattern.exec(css);
  expect(match, `no rule for ${selector}`).not.toBeNull();
  return match?.[2] ?? "";
}

/** A `--layout-*` token's declared value. */
function token(name: string): string {
  const match = new RegExp(`${name}:\\s*([^;]+);`).exec(TOKENS_CSS);
  expect(match, `${name} is not declared in app/tokens.css`).not.toBeNull();
  return (match?.[1] ?? "").trim();
}

describe("criterion 3 / 5 — the grid, and the two declarations that do the work", () => {
  it("gives the content column `minmax(0, 1fr)` — the min-content floor flex cannot remove", () => {
    // 04 §8.3 item 2. The base rule is a single column; the two media
    // queries below add the rail column beside it. Every one of them ends
    // in `minmax(0, 1fr)`.
    expect(rule(WORKBENCH_CSS, ".ew-shell")).toContain("grid-template-columns: minmax(0, 1fr)");

    const md = mediaBlock(WORKBENCH_CSS, "(min-width: 768px)");
    expect(md).toContain("grid-template-columns: var(--ew-rail-width) minmax(0, 1fr)");

    // And the body row, for the same reason in the other axis.
    expect(rule(WORKBENCH_CSS, ".ew-shell")).toContain("grid-template-rows: auto minmax(0, 1fr)");
  });

  it("carries `min-width: 0` on the content column in every mode", () => {
    // 04 §8.3 item 3: "The content column carries min-w-0 regardless of
    // layout mode." Declared on the base rule and overridden by no media
    // query, which is what "regardless" has to mean.
    expect(rule(WORKBENCH_CSS, ".ew-shell__main")).toContain("min-width: 0");
    expect(rule(WORKBENCH_CSS, ".ew-shell__surface")).toContain("min-width: 0");
    for (const condition of ["(max-width: 767px)", "(min-width: 768px)", "(min-width: 1024px)"]) {
      expect(mediaBlock(WORKBENCH_CSS, condition)).not.toMatch(
        /\.ew-shell__(main|surface)[^}]*min-width:\s*(?!0)/,
      );
    }
  });

  it("keeps `min-width: 0` on the shell and the header too, so nothing upstream re-floors it", () => {
    expect(rule(WORKBENCH_CSS, ".ew-shell")).toContain("min-width: 0");
    expect(rule(WORKBENCH_CSS, ".ew-shell__header")).toContain("min-width: 0");
    expect(rule(WORKBENCH_CSS, ".ew-shell__workspace")).toContain("min-width: 0");
  });

  it("lets the header wrap rather than push its controls off the edge", () => {
    expect(rule(WORKBENCH_CSS, ".ew-shell__header")).toContain("flex-wrap: wrap");
  });
});

describe("criterion 3 — the breakpoints and widths are the tokens, not new numbers", () => {
  it("uses --layout-breakpoint-md and --layout-breakpoint-lg, to the pixel", () => {
    expect(token("--layout-breakpoint-md")).toBe("768px");
    expect(token("--layout-breakpoint-lg")).toBe("1024px");
    expect(WORKBENCH_CSS).toContain("@media (min-width: 768px)");
    expect(WORKBENCH_CSS).toContain("@media (min-width: 1024px)");
    // The `drawer` block is the complement of md, one pixel below it.
    expect(WORKBENCH_CSS).toContain("@media (max-width: 767px)");
  });

  it("uses the same two numbers in the module that decides which mode is live", () => {
    expect(COMPACT_QUERY).toBe(`(min-width: ${token("--layout-breakpoint-md")})`);
    expect(EXPANDED_QUERY).toBe(`(min-width: ${token("--layout-breakpoint-lg")})`);
  });

  it("takes the rail widths from --layout-rail-width and --layout-rail-collapsed-width", () => {
    // RC-04 resolves the 256px/260px disagreement in favour of the token.
    expect(token("--layout-rail-width")).toBe("260px");
    expect(token("--layout-rail-collapsed-width")).toBe("56px");

    expect(mediaBlock(WORKBENCH_CSS, "(min-width: 768px)")).toContain(
      "--ew-rail-width: var(--layout-rail-collapsed-width)",
    );
    const lg = mediaBlock(WORKBENCH_CSS, "(min-width: 1024px)");
    expect(lg).toContain("--ew-rail-width: var(--layout-rail-width)");
    expect(lg).toContain('.ew-shell[data-rail-collapsed="true"]');
    expect(lg).toContain("--ew-rail-width: var(--layout-rail-collapsed-width)");
  });

  it("hides the rail below md as well as not rendering it", () => {
    // The base rule is the VISIBLE one and the narrow media query turns it
    // off, not the other way round: jsdom applies unconditional rules but
    // not media overrides, so a `display: none` default would hide the
    // landmark from every story's axe run.
    expect(rule(WORKBENCH_CSS, ".ew-shell__rail")).toContain("display: block");
    expect(mediaBlock(WORKBENCH_CSS, "(max-width: 767px)")).toMatch(
      /\.ew-shell__rail\s*\{[^}]*display:\s*none/,
    );
  });
});

describe("criterion 7 — the composer area below 768px", () => {
  const narrow = mediaBlock(WORKBENCH_CSS, "(max-width: 767px)");

  it("is sticky", () => {
    expect(narrow).toMatch(/\.ew-shell__composer\s*\{[^}]*position:\s*sticky/);
    expect(narrow).toMatch(/\.ew-shell__composer\s*\{[^}]*bottom:\s*0/);
  });

  it("carries env(safe-area-inset-bottom), exactly once, at the shell's bottom edge", () => {
    expect(narrow).toContain("env(safe-area-inset-bottom");
    // Once, not twice: a second declaration on the slot itself would double
    // the inset the moment WO-20 occupies it.
    expect(narrow.match(/env\(safe-area-inset-bottom/g)).toHaveLength(1);
    expect(narrow).toMatch(/\.ew-shell__main\s*\{[^}]*padding-bottom:\s*env\(safe-area-inset-bottom/);
  });

  it("is the last row of main's grid, so it cannot scroll away", () => {
    expect(rule(WORKBENCH_CSS, ".ew-shell__main")).toContain(
      "grid-template-rows: minmax(0, 1fr) auto",
    );
  });
});

describe("the stylesheets stay inside the token layer", () => {
  it("declares no literal colour in either file", () => {
    // web/tests/tokens.test.ts scans the whole repository for this; the
    // assertion is repeated here so a failure names the file that broke it.
    for (const [name, css] of [
      ["workbench.css", WORKBENCH_CSS],
      ["ThemeToggle.css", THEME_TOGGLE_CSS],
    ] as const) {
      expect(css, `${name} has a hex colour`).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
      expect(css, `${name} has a functional colour`).not.toMatch(/\b(rgb|rgba|hsl|hsla)\(/);
    }
  });

  it("writes the focus ring with the same four longhands the primitives use", () => {
    const focus = rule(THEME_TOGGLE_CSS, ".ew-theme-option input:focus-visible + span");
    expect(focus).toContain("outline-width: var(--size-focus-ring-width)");
    expect(focus).toContain("outline-style: solid");
    expect(focus).toContain("outline-color: var(--color-focus)");
    expect(focus).toContain("outline-offset: var(--size-focus-ring-offset)");
    // 03 §7.2: `outline: none` is never written without a replacement in the
    // same rule. There is none to replace here.
    expect(THEME_TOGGLE_CSS).not.toMatch(/outline:\s*none/);
    expect(WORKBENCH_CSS).not.toMatch(/outline:\s*none/);
  });
});
