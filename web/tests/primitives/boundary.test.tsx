/**
 * WO-07 criteria 1 and 2 — the layer rule, and the inventory that has to
 * exist for it to mean anything.
 *
 *   1. "No primitive imports from `lib/api` or calls a fetching hook; an
 *      ESLint boundary rule enforces it and a fixture proves the rule
 *      fires."
 *   2. "Every primitive's full state set is reachable by props alone — a
 *      story needs no MSW and no network."
 *
 * The fixture pair follows WO-01's pattern exactly: a negative fixture that
 * MUST fail lint and a positive one that MUST pass, both outside
 * `npm run lint`'s scope (`eslint app components lib`) and inside the rule's
 * `files` list, so the repository lint stays green while the proof stays
 * executable.
 */

import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { WEB_ROOT } from "./support/css";

/** The eleven the card names. Listed, not globbed: a primitive that never
 *  got written would otherwise pass by being absent. */
const PRIMITIVES = [
  "Button",
  "Field",
  "Textarea",
  "Disclosure",
  "Dialog",
  "Menu",
  "StatusBadge",
  "Skeleton",
  "VisuallyHidden",
  "ScrollRegion",
  "SkipLink",
] as const;

const PRIMITIVES_DIR = path.join(WEB_ROOT, "components", "primitives");
const FIXTURES_DIR = path.join(WEB_ROOT, "tests", "fixtures");

function sourceFiles(): string[] {
  return readdirSync(PRIMITIVES_DIR)
    .filter((entry) => /\.tsx?$/.test(entry) && !entry.endsWith(".stories.tsx"))
    .map((entry) => path.join(PRIMITIVES_DIR, entry));
}

function storyFiles(): string[] {
  return readdirSync(PRIMITIVES_DIR)
    .filter((entry) => entry.endsWith(".stories.tsx"))
    .map((entry) => path.join(PRIMITIVES_DIR, entry));
}

describe("criterion 1 — the ESLint boundary rule fires on a real file", () => {
  it(
    "rejects the data-layer fixture and accepts the props fixture",
    { timeout: 120_000 },
    async () => {
      const { ESLint } = await import("eslint");
      const eslint = new ESLint({ cwd: WEB_ROOT });

      const [bad] = await eslint.lintFiles([
        path.join(FIXTURES_DIR, "primitive-boundary.fixture.tsx"),
      ]);
      const violations = (bad?.messages ?? []).filter(
        (message) => message.ruleId === "no-restricted-imports",
      );
      // Four imports: the client barrel, a module inside it, the SSE hook,
      // and MSW — the four ways a primitive reaches the network.
      expect(violations).toHaveLength(4);
      for (const violation of violations) {
        expect(violation.message).toContain("may not reach the data layer");
      }

      const [good] = await eslint.lintFiles([
        path.join(FIXTURES_DIR, "primitive-props.fixture.tsx"),
      ]);
      expect(good?.errorCount, JSON.stringify(good?.messages ?? [])).toBe(0);
    },
  );

  it("scopes the rule to the primitives and to the fixtures, and nowhere else", () => {
    const config = readFileSync(path.join(WEB_ROOT, "eslint.config.mjs"), "utf8");
    expect(config).toContain("primitives/no-data-layer");
    expect(config).toContain("components/primitives/**/*.{ts,tsx}");
    expect(config).toContain("tests/fixtures/primitive-*.fixture.{ts,tsx}");
    // A second `no-restricted-syntax` block would REPLACE WO-01's
    // no-literal-colour options for these files rather than merge with
    // them. The boundary therefore uses a different rule on purpose.
    expect(config).toContain("no-restricted-imports");
  });

  it("keeps the whole library clean under the repository lint", async () => {
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    const results = await eslint.lintFiles([path.join(PRIMITIVES_DIR, "**/*.{ts,tsx}")]);
    for (const result of results) {
      expect(result.errorCount, `${result.filePath}: ${JSON.stringify(result.messages)}`).toBe(
        0,
      );
    }
  }, 120_000);
});

describe("criterion 1 — no primitive reaches the network by any other route", () => {
  it.each(sourceFiles())("%s imports nothing from the data layer", (file) => {
    const source = readFileSync(file, "utf8");
    expect(source).not.toMatch(/from\s+["'][^"']*lib\/api/);
    expect(source).not.toMatch(/useResearchStream/);
  });

  it.each(sourceFiles())("%s calls no fetch primitive directly", (file) => {
    const source = readFileSync(file, "utf8");
    // The lint rule catches imports; a global has no import to catch.
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/new\s+EventSource\b/);
    expect(source).not.toMatch(/\bXMLHttpRequest\b/);
  });
});

describe("criterion 2 — every state is reachable by props alone", () => {
  it.each(storyFiles())("%s needs no MSW and no network", (file) => {
    const source = readFileSync(file, "utf8");
    expect(source).not.toMatch(/from\s+["']msw/);
    expect(source).not.toMatch(/\bfetch\s*\(/);
    expect(source).not.toMatch(/from\s+["'][^"']*tests\/support\/(msw|handlers)/);
  });

  it.each(PRIMITIVES)("%s has a component, a story and a test", (name) => {
    expect(existsSync(path.join(PRIMITIVES_DIR, `${name}.tsx`)), `${name}.tsx`).toBe(true);
    expect(
      existsSync(path.join(PRIMITIVES_DIR, `${name}.stories.tsx`)),
      `${name}.stories.tsx`,
    ).toBe(true);
    expect(
      existsSync(path.join(WEB_ROOT, "tests", "primitives", `${name}.test.tsx`)),
      `tests/primitives/${name}.test.tsx`,
    ).toBe(true);
  });

  it("ships no story that is not one of the eleven's", () => {
    const named = storyFiles().map((file) => path.basename(file, ".stories.tsx"));
    expect(named.sort()).toEqual([...PRIMITIVES].sort());
  });
});

describe("R-11 — Radix is imported per component, never through a barrel", () => {
  const packageJson = JSON.parse(
    readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"),
  ) as { dependencies: Record<string, string>; devDependencies: Record<string, string> };

  it("declares only the two per-component packages the library actually uses", () => {
    const radix = Object.keys(packageJson.dependencies).filter((name) =>
      name.startsWith("@radix-ui/"),
    );
    expect(radix.sort()).toEqual([
      "@radix-ui/react-dialog",
      "@radix-ui/react-dropdown-menu",
    ]);
    // The mono-package barrel is the leak R-11 names: importing `radix-ui`
    // pulls every primitive it re-exports into the route's chunk union.
    expect(packageJson.dependencies["radix-ui"]).toBeUndefined();
    expect(packageJson.devDependencies["radix-ui"]).toBeUndefined();
  });

  it("pins both exactly, because they ship", () => {
    for (const [name, range] of Object.entries(packageJson.dependencies)) {
      if (!name.startsWith("@radix-ui/")) continue;
      expect(range, `${name} is not exact-pinned`).toMatch(/^\d+\.\d+\.\d+$/);
    }
  });

  it.each(sourceFiles())("%s imports no Radix barrel", (file) => {
    const source = readFileSync(file, "utf8");
    expect(source).not.toMatch(/from\s+["']radix-ui["']/);
  });

  it("exposes no barrel of its own either", () => {
    // A `components/primitives/index.ts` would do to WO-07 exactly what the
    // `radix-ui` package does to Radix: a surface importing one Button would
    // pull Dialog's and Menu's module graphs — and their Radix packages —
    // into its route. Surfaces import the module they need.
    for (const barrel of ["index.ts", "index.tsx"]) {
      expect(existsSync(path.join(PRIMITIVES_DIR, barrel)), barrel).toBe(false);
    }
  });

  it("keeps Radix out of every module except Dialog and Menu", () => {
    const importers = sourceFiles().filter((file) =>
      /from\s+["']@radix-ui\//.test(readFileSync(file, "utf8")),
    );
    expect(importers.map((file) => path.basename(file)).sort()).toEqual([
      "Dialog.tsx",
      "Menu.tsx",
    ]);
  });
});
