/**
 * WO-12 criterion 1 — the copy module is the single edit site, and lint is
 * what makes that true rather than aspirational.
 *
 * "One copy module is the single edit site for every user-facing string; a
 * lint rule rejects string literals rendered as text in
 * `components/patterns` and `components/features`."
 *
 * Three things are proved here, in the order that matters:
 *
 *   1. The rule FIRES. A committed fixture that really violates it is
 *      linted by a real ESLint instance and the violation count is exact.
 *      A configured-but-silent rule would pass a source-text assertion and
 *      fail this one.
 *   2. The rule does not fire on the legitimate shape. The positive
 *      fixture renders a whole failure banner out of the dictionary,
 *      including aria-labels, data attributes and class names, and is
 *      clean.
 *   3. The rule did not switch WO-01's no-literal-colour OFF. Flat config
 *      REPLACES a rule's options rather than merging them, so a second
 *      `no-restricted-syntax` block scoped to components/patterns/** is the
 *      one way to silently un-token-ise the newest files in the repository.
 *      The resolved config for a real patterns file is read back and both
 *      selector families must be in it.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const FIXTURES = path.join(WEB_ROOT, "tests", "fixtures");
const PATTERNS = path.join(WEB_ROOT, "components", "patterns");

const COPY_MESSAGE = "single edit site for every user-facing string";
const COLOUR_MESSAGE = "Literal colours are not allowed here";

async function lint(files: string[]) {
  const { ESLint } = await import("eslint");
  const eslint = new ESLint({ cwd: WEB_ROOT });
  return eslint.lintFiles(files);
}

describe("criterion 1 — the rule fires on a real committed file", () => {
  it(
    "rejects every rendered-text shape in the negative fixture",
    { timeout: 120_000 },
    async () => {
      const [result] = await lint([path.join(FIXTURES, "copy-inline.fixture.tsx")]);
      const messages = (result?.messages ?? []).filter(
        (message) => message.ruleId === "no-restricted-syntax",
      );
      const copy = messages.filter((message) => message.message.includes(COPY_MESSAGE));
      const colour = messages.filter((message) =>
        message.message.includes(COLOUR_MESSAGE),
      );

      // Nine rendered strings, one per shape the rule claims: a JSX text
      // node, a literal child, a template child, BOTH arms of a ternary,
      // a `&&` child, BOTH sides of a concatenation, and a fragment child.
      expect(copy).toHaveLength(9);
      // The fixture carries no hex, on purpose — WO-01's repository-wide
      // scan would fail on it. The colour rule's survival is proved by
      // the third describe instead.
      expect(colour).toHaveLength(0);
    },
  );

  it(
    "leaves the dictionary-driven fixture alone, aria-labels and all",
    { timeout: 120_000 },
    async () => {
      const [result] = await lint([
        path.join(FIXTURES, "copy-dictionary.fixture.tsx"),
      ]);
      expect(
        result?.errorCount,
        JSON.stringify(result?.messages ?? []),
      ).toBe(0);
    },
  );

  it("keeps the real pattern and its stories clean", { timeout: 120_000 }, async () => {
    const results = await lint([path.join(PATTERNS, "**/*.{ts,tsx}")]);
    expect(results.length).toBeGreaterThan(0);
    for (const result of results) {
      expect(
        result.errorCount,
        `${result.filePath}: ${JSON.stringify(result.messages)}`,
      ).toBe(0);
    }
  });
});

describe("criterion 1 — the rule's scope is the two surface directories", () => {
  const config = readFileSync(path.join(WEB_ROOT, "eslint.config.mjs"), "utf8");

  it("names both directories and the fixture glob", () => {
    expect(config).toContain("copy/no-inline-text");
    expect(config).toContain("components/patterns/**/*.{ts,tsx}");
    expect(config).toContain("components/features/**/*.{ts,tsx}");
    expect(config).toContain("tests/fixtures/copy-*.fixture.{ts,tsx}");
  });

  it("allow-lists nothing", () => {
    // WO-08 is landing ThemeToggle.tsx and ThreadDrawer.tsx into these two
    // directories concurrently. The coordination is the rule's SHAPE —
    // rendered text only, non-rendered strings out of scope — and not an
    // entry here naming somebody's files. A per-file exemption in this
    // block would be the beginning of the end of the rule.
    const block = config.slice(config.indexOf('name: "copy/no-inline-text"'));
    const nextBlock = block.indexOf("globalIgnores");
    expect(block.slice(0, nextBlock)).not.toContain("ignores");
  });

  it("anchors the child-slot selectors so attributes stay out of scope", () => {
    // An unanchored `JSXExpressionContainer > Literal` would also match
    // `data-open={open ? "true" : "false"}`. The fixture proves the
    // anchoring works; this proves it was deliberate.
    expect(config).toContain("JSXElement");
    expect(config).toContain("JSXFragment");
    expect(config).toContain("CHILD_SLOT");
  });
});

describe("criterion 1 — WO-01's colour rule survived the second block", () => {
  it("still FIRES on a literal colour inside components/patterns", async () => {
    // Flat config replaces a rule's options rather than merging them, so
    // `copy/no-inline-text` is the one way to silently un-token-ise the
    // newest files in the repository. Linted as text against a patterns
    // path rather than as a committed file, because a hex committed
    // anywhere under web/ fails WO-01's own repository-wide scan.
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    // Assembled rather than written: WO-01's scan reads THIS file too, and
    // a literal hex anywhere under web/ fails it.
    const hex = ["#", "b9", "1c", "1c"].join("");
    const [result] = await eslint.lintText(
      `export const style = { color: "${hex}" };\n`,
      { filePath: path.join(PATTERNS, "ColourProbe.tsx") },
    );
    const messages = (result?.messages ?? []).filter(
      (message) => message.ruleId === "no-restricted-syntax",
    );
    expect(messages).toHaveLength(1);
    expect(messages[0]?.message).toContain(COLOUR_MESSAGE);
  }, 120_000);

  it("fires on rendered text in the same synthetic file", async () => {
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    const [result] = await eslint.lintText(
      "export function Probe() {\n  return <p>The run failed.</p>;\n}\n",
      { filePath: path.join(PATTERNS, "TextProbe.tsx") },
    );
    const messages = (result?.messages ?? []).filter(
      (message) => message.ruleId === "no-restricted-syntax",
    );
    expect(messages).toHaveLength(1);
    expect(messages[0]?.message).toContain(COPY_MESSAGE);
  }, 120_000);

  it("resolves both selector families for a real patterns file", async () => {
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    const resolved = (await eslint.calculateConfigForFile(
      path.join(PATTERNS, "StatusBanner.tsx"),
    )) as { rules?: Record<string, unknown[]> };
    const options = resolved.rules?.["no-restricted-syntax"] ?? [];
    const messages = options
      .slice(1)
      .map((entry) => (entry as { message: string }).message);

    expect(messages.some((message) => message.includes(COLOUR_MESSAGE))).toBe(true);
    expect(messages.some((message) => message.includes(COPY_MESSAGE))).toBe(true);
    // Six colour selectors survive from WO-01's block (four) plus the two
    // functional-notation ones; eleven copy selectors are added. The exact
    // count matters less than that neither family is empty, but a drop to
    // one family is exactly the regression this asserts against.
    expect(options.slice(1).length).toBeGreaterThanOrEqual(15);
  }, 120_000);

  it("resolves the same union for components/features, which WO-08 is creating", async () => {
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    const resolved = (await eslint.calculateConfigForFile(
      path.join(WEB_ROOT, "components", "features", "ThreadRail.tsx"),
    )) as { rules?: Record<string, unknown[]> };
    const messages = (resolved.rules?.["no-restricted-syntax"] ?? [])
      .slice(1)
      .map((entry) => (entry as { message: string }).message);
    expect(messages.some((message) => message.includes(COPY_MESSAGE))).toBe(true);
    expect(messages.some((message) => message.includes(COLOUR_MESSAGE))).toBe(true);
  }, 120_000);
});
