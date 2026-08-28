/**
 * WO-06 — the parts of the Storybook setup that a rendered story cannot
 * prove about itself.
 *
 * The stories are their own test: the `storybook` project in
 * vitest.config.mts renders each one and runs axe over it (criterion 3).
 * What that cannot show is *which* axe tags ran, *which* viewports the
 * toolbar offers, or that the theme decorator writes the attribute the
 * product writes rather than one of its own. Those three are asserted here,
 * against their sources rather than against restated copies:
 *
 *   criterion 1  the decorator globals, the RC-14 viewport set, and the
 *                fact that the theme decorator's attribute is the one
 *                web/lib/tokens.ts exports
 *   criterion 2  the axe tag set, against docs/revamp/baseline/axe/*.json
 *   criterion 4  the build-storybook script, and that its output directory
 *                is one the repository-wide literal-colour scan skips
 */

import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { AXE_TAGS } from "../.storybook/axe";
import {
  DEFAULT_MOTION,
  DEFAULT_THEME,
  FORCED_COLORS_ATTRIBUTE,
  MOTION_OPTIONS,
  RC14_WIDTHS,
  REDUCED_MOTION_ATTRIBUTE,
  THEME_OPTIONS,
  VIEWPORTS,
} from "../.storybook/decorators";
import preview from "../.storybook/preview";
import { THEME_ATTRIBUTE, THEME_PREFERENCE_ATTRIBUTE } from "../lib/tokens";

const WEB_ROOT = path.resolve(__dirname, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const BASELINE_AXE = path.join(REPO_ROOT, "docs", "revamp", "baseline", "axe");

describe("criterion 2 — the axe tag set matches the Gate 1 baseline", () => {
  const baselineFiles = readdirSync(BASELINE_AXE).filter((file) => file.endsWith(".json"));

  it("reads a real baseline directory", () => {
    expect(baselineFiles.length).toBeGreaterThan(0);
  });

  it.each(baselineFiles)("%s ran the same tags Storybook runs", (file) => {
    const report = JSON.parse(readFileSync(path.join(BASELINE_AXE, file), "utf8")) as {
      toolOptions?: { runOnly?: { type?: string; values?: string[] } };
    };
    expect(report.toolOptions?.runOnly?.type).toBe("tag");
    // Order included: a diff of two axe reports is only readable if the
    // option objects are identical, not merely equivalent.
    expect(report.toolOptions?.runOnly?.values).toEqual([...AXE_TAGS]);
  });

  it("hands that tag set to axe through the a11y parameter", () => {
    const a11y = preview.parameters?.["a11y"] as
      | { test?: string; options?: { runOnly?: { type?: string; values?: string[] } } }
      | undefined;
    expect(a11y?.options?.runOnly).toEqual({ type: "tag", values: [...AXE_TAGS] });
    // "error" is what makes the run a gate inside `npm run test` rather
    // than a panel in the Storybook UI (criterion 3).
    expect(a11y?.test).toBe("error");
  });
});

describe("criterion 1 — the three toolbars are global", () => {
  it("offers light, dark and forced-colors", () => {
    expect(THEME_OPTIONS).toEqual(["light", "dark", "forced-colors"]);
    expect(preview.globalTypes?.["theme"]?.toolbar?.items).toHaveLength(THEME_OPTIONS.length);
    expect(preview.initialGlobals?.["theme"]).toBe(DEFAULT_THEME);
  });

  it("offers the five RC-14 viewports and nothing else", () => {
    const widths = Object.values(VIEWPORTS).map((viewport) =>
      Number.parseInt(viewport.styles.width, 10),
    );
    expect(widths).toEqual([...RC14_WIDTHS]);
    // 04-ARCHITECTURE.md section 5.2 proposed four; 1024 is RC-14's addition
    // and the only sample of the "rail expanded, no section rail" mode.
    expect(widths).toContain(1024);
    const options = (preview.parameters?.["viewport"] as { options?: unknown } | undefined)
      ?.options;
    expect(options).toBe(VIEWPORTS);
  });

  it("offers a reduced-motion preference", () => {
    expect(MOTION_OPTIONS).toEqual(["no-preference", "reduce"]);
    expect(preview.globalTypes?.["motion"]?.toolbar?.items).toHaveLength(MOTION_OPTIONS.length);
    expect(preview.initialGlobals?.["motion"]).toBe(DEFAULT_MOTION);
  });

  it("wires every decorator once, for every story", () => {
    // Three decorators, no per-story wiring anywhere: a story author writes
    // a meta and a StoryObj and gets all three toolbars.
    expect(preview.decorators).toHaveLength(3);
  });
});

describe("criterion 1 — the theme decorator drives the product's own mechanism", () => {
  const source = readFileSync(path.join(WEB_ROOT, ".storybook", "decorators", "theme.tsx"), "utf8");

  it("writes data-theme, not a Storybook-only class", () => {
    expect(THEME_ATTRIBUTE).toBe("data-theme");
    expect(source).toContain("THEME_ATTRIBUTE");
    expect(source).toContain("THEME_PREFERENCE_ATTRIBUTE");
    expect(THEME_PREFERENCE_ATTRIBUTE).toBe("data-theme-preference");
  });

  it("keys the forced-colours and reduced-motion emulations off attributes preview.css declares", () => {
    const css = readFileSync(path.join(WEB_ROOT, ".storybook", "preview.css"), "utf8");
    expect(css).toContain(`:root[${FORCED_COLORS_ATTRIBUTE}="active"]`);
    expect(css).toContain(`:root[${REDUCED_MOTION_ATTRIBUTE}="reduce"]`);
    // The reduced-motion emulation must set the same four durations
    // app/tokens.css sets under the media query, and no others.
    for (const name of ["--duration-fast", "--duration-base", "--duration-slow", "--duration-ambient"]) {
      expect(css, `${name} is not collapsed`).toContain(`${name}: 1ms;`);
    }
  });

  it("rebinds every colour token in the forced-colours emulation", () => {
    const css = readFileSync(path.join(WEB_ROOT, ".storybook", "preview.css"), "utf8");
    const tokensCss = readFileSync(path.join(WEB_ROOT, "app", "tokens.css"), "utf8");
    const declared = new Set(
      [...tokensCss.matchAll(/^\s*(--color-[a-z-]+):/gm)].map((match) => match[1] as string),
    );
    expect(declared.size).toBe(23);
    for (const name of declared) {
      expect(css, `${name} keeps its authored value under forced colours`).toContain(`${name}:`);
    }
  });
});

describe("criterion 4 — build-storybook", () => {
  const packageJson = JSON.parse(readFileSync(path.join(WEB_ROOT, "package.json"), "utf8")) as {
    scripts: Record<string, string>;
    devDependencies: Record<string, string>;
  };

  it("has a storybook and a build-storybook script", () => {
    expect(packageJson.scripts["storybook"]).toContain("storybook dev");
    expect(packageJson.scripts["build-storybook"]).toContain("storybook build");
  });

  it("writes the static build where the literal-colour scan will not walk it", () => {
    // tokens.test.ts skips node_modules, .next, out, build and .git. A
    // bundle emitted anywhere else is full of hex and fails that scan the
    // moment anyone builds locally.
    expect(packageJson.scripts["build-storybook"]).toContain("--output-dir build/");
  });

  it("keeps Storybook in devDependencies only", () => {
    const dependencies = JSON.parse(readFileSync(path.join(WEB_ROOT, "package.json"), "utf8"))
      .dependencies as Record<string, string>;
    for (const name of Object.keys(dependencies)) {
      expect(name.startsWith("@storybook/"), `${name} is a runtime dependency`).toBe(false);
      expect(name).not.toBe("storybook");
    }
    // Exact pins, per the repo's precedent for tools that gate a build.
    for (const [name, range] of Object.entries(packageJson.devDependencies)) {
      if (name === "storybook" || name.startsWith("@storybook/")) {
        expect(range, `${name} is not exact-pinned`).toMatch(/^\d+\.\d+\.\d+$/);
      }
    }
  });
});
