/**
 * WO-02 — typography, self-hosted fonts, and CLS proof.
 *
 * Criterion 6 in two halves: the three `--font-*` variables resolve, and no
 * component names a family directly.
 *
 * "Resolve" is checked as a chain rather than as a string, because every
 * link in it can break independently: tokens.css puts `var(--font-ui-face)`
 * at the head of `--font-ui`, app/fonts/fonts.ts asks next/font/local for
 * exactly that custom property, app/layout.tsx puts the returned class on
 * <html>, and the woff2 file the declaration points at is committed. A test
 * that only asserted the CSS text would pass with no fonts in the repo.
 *
 * The remaining criteria are evidence, not assertions, and live in
 * docs/revamp/evidence/gate-3/fonts.md: the per-face byte table against the
 * RC-01 budget, the measured fallback metrics, and the Lighthouse CLS runs.
 * What is mechanically checkable about them is checked here -- the budget
 * total, the licences, and that fallback.css carries a measured triple for
 * every family.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import RootLayout from "@/app/layout";
import { fontMono, fontReport, fontUi, fontVariables } from "@/app/fonts/fonts";
import { font } from "@/lib/tokens";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const FONT_DIR = path.join(WEB_ROOT, "app", "fonts");

const tokensCss = readFileSync(path.join(WEB_ROOT, "app", "tokens.css"), "utf8");
const fallbackCss = readFileSync(path.join(FONT_DIR, "fallback.css"), "utf8");
const fontsSource = readFileSync(path.join(FONT_DIR, "fonts.ts"), "utf8");

/** RC-01, ratified at Gate 2: all self-hosted woff2 files, 120 KiB. */
const FONT_BUDGET_BYTES = 120 * 1024;

/**
 * The three families, and for each: the token, the next/font variable at
 * the head of its stack, the metric-adjusted fallback family that follows
 * it, and the family name that must appear nowhere else in the app.
 */
const FAMILIES = [
  {
    id: "ui",
    faceVariable: "--font-ui-face",
    adjusted: "Atkinson Hyperlegible Next Fallback",
    familyName: "Atkinson Hyperlegible Next",
    module: fontUi,
  },
  {
    id: "report",
    faceVariable: "--font-report-face",
    adjusted: "Literata Fallback",
    familyName: "Literata",
    module: fontReport,
  },
  {
    id: "mono",
    faceVariable: "--font-mono-face",
    adjusted: "IBM Plex Mono Fallback",
    familyName: "IBM Plex Mono",
    module: fontMono,
  },
] as const;

/** The `--font-*` declarations on :root, as name -> value. */
function fontDeclarations(): Map<string, string> {
  const root = /:root\s*\{([\s\S]*?)\n\}/.exec(tokensCss.replace(/\/\*[\s\S]*?\*\//g, ""));
  expect(root, "app/tokens.css has no :root block").not.toBeNull();
  const found = new Map<string, string>();
  const pattern = /(--font-[a-z-]+)\s*:\s*([^;]+);/g;
  let match = pattern.exec((root as RegExpExecArray)[1] as string);
  while (match !== null) {
    found.set(match[1] as string, (match[2] as string).trim());
    match = pattern.exec((root as RegExpExecArray)[1] as string);
  }
  return found;
}

describe("criterion 6 — the three --font-* variables resolve", () => {
  it("declares exactly --font-ui, --font-report and --font-mono on :root", () => {
    expect([...fontDeclarations().keys()].sort()).toEqual([
      "--font-mono",
      "--font-report",
      "--font-ui",
    ]);
  });

  it("exposes each one through lib/tokens.ts as a bare var() reference", () => {
    expect(Object.keys(font).sort()).toEqual(["mono", "report", "ui"]);
    for (const family of FAMILIES) {
      expect(font[family.id]).toBe(`var(--font-${family.id})`);
    }
  });

  it.each(FAMILIES.map((family) => [family.id, family] as const))(
    "%s: leads with its next/font variable, then the adjusted fallback, then the generic stack",
    (_id, family) => {
      const value = fontDeclarations().get(`--font-${family.id}`);
      expect(value, `--font-${family.id} is not declared`).toBeDefined();
      const layers = (value as string).split(",").map((layer) => layer.trim());

      // The self-hosted face first, so nothing on the reader's machine
      // outranks the subset that was measured.
      expect(layers[0]).toBe(`var(${family.faceVariable})`);
      // The metric-adjusted face second: this is what paints during swap.
      expect(layers[1]).toBe(`"${family.adjusted}"`);
      // Something generic last, for a platform with none of the above.
      expect(layers.length).toBeGreaterThan(2);
      expect(layers[layers.length - 1]).toMatch(/^(sans-serif|serif|monospace)$/);

      // The bare family name must NOT be a layer: it would let a stale
      // locally installed copy win over the subset.
      expect(layers).not.toContain(`"${family.familyName}"`);
      expect(layers).not.toContain(family.familyName);
    },
  );

  it("asks next/font/local for exactly the variables tokens.css references", () => {
    const requested = [...fontsSource.matchAll(/variable:\s*"(--font-[a-z-]+)"/g)].map(
      (match) => match[1],
    );
    expect(requested.sort()).toEqual(FAMILIES.map((family) => family.faceVariable).sort());
  });

  it("puts all three variable classes on <html> so the var() references have a scope", () => {
    for (const family of FAMILIES) {
      expect(family.module.variable, `${family.id} has no variable class`).toBeTruthy();
      expect(fontVariables).toContain(family.module.variable);
    }
    const markup = renderToStaticMarkup(
      createElement(RootLayout, { children: createElement("main") }),
    );
    const className = /<html\b[^>]*\bclass="([^"]*)"/.exec(markup);
    expect(className, "<html> carries no className").not.toBeNull();
    const classes = ((className as RegExpExecArray)[1] as string).split(/\s+/);
    for (const family of FAMILIES) {
      expect(classes).toContain(family.module.variable);
    }
  });

  it("points every declaration at a committed woff2", () => {
    const declared = [...fontsSource.matchAll(/path:\s*"\.\/([^"]+\.woff2)"/g)].map(
      (match) => match[1] as string,
    );
    expect(declared.length).toBeGreaterThanOrEqual(FAMILIES.length);
    for (const file of declared) {
      expect(existsSync(path.join(FONT_DIR, file)), `${file} is declared but not committed`).toBe(
        true,
      );
    }
    // And nothing is committed that no declaration uses.
    const committed = readdirSync(FONT_DIR).filter((name) => name.endsWith(".woff2"));
    expect(committed.sort()).toEqual([...declared].sort());
  });
});

describe("criterion 6 — no component references a family name directly", () => {
  const SCANNED = new Set([".ts", ".tsx", ".css", ".mjs", ".js"]);
  const SKIP = new Set(["node_modules", ".next", "out", "build", ".git"]);

  /**
   * The complete exemption list, and why each entry is on it:
   *   app/tokens.css              the single place the stacks are composed
   *   app/fonts/fonts.ts          the next/font/local declarations
   *   app/fonts/fallback.css      the metric-adjusted faces
   *   scripts/measure-fonts.mjs   the measurement harness names the fonts
   *                               it measures
   *   tailwind.config.ts          the token bridge: its fontFamily entries
   *                               are var(--font-*) references and nothing
   *                               else, which tokens.test.ts asserts
   *                               exactly
   *   tests/stubs/*               the next/font stand-in returns the shape
   *                               the real loader returns
   *   tests/fonts.test.ts         this file
   */
  const EXEMPT = new Set([
    "app/tokens.css",
    "app/fonts/fonts.ts",
    "app/fonts/fallback.css",
    "scripts/measure-fonts.mjs",
    "tailwind.config.ts",
    "tests/stubs/next-font-local.ts",
    "tests/fonts.test.ts",
  ]);

  const NAMES = FAMILIES.map((family) => family.familyName);

  const walk = (directory: string, found: string[] = []): string[] => {
    for (const entry of readdirSync(directory)) {
      if (SKIP.has(entry)) continue;
      const absolute = path.join(directory, entry);
      if (statSync(absolute).isDirectory()) walk(absolute, found);
      else if (SCANNED.has(path.extname(entry))) found.push(absolute);
    }
    return found;
  };

  it("finds no family name outside the exemption list", () => {
    const offenders: string[] = [];
    for (const file of walk(WEB_ROOT)) {
      const relative = path.relative(WEB_ROOT, file);
      if (EXEMPT.has(relative)) continue;
      const source = readFileSync(file, "utf8");
      for (const name of NAMES) {
        if (source.includes(name)) offenders.push(`${relative} names ${name}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("finds no font-family declaration or Tailwind arbitrary family outside tokens.css", () => {
    const offenders: string[] = [];
    for (const file of walk(WEB_ROOT)) {
      const relative = path.relative(WEB_ROOT, file);
      if (EXEMPT.has(relative)) continue;
      const source = readFileSync(file, "utf8");
      // `font-family:` in CSS or JSX style objects, and font-['...'] in a
      // Tailwind arbitrary value. Components use the font-ui / font-report
      // / font-mono utilities, which resolve through the tokens.
      if (/font-family\s*:/.test(source)) offenders.push(`${relative} sets font-family`);
      if (/\bfont-\[/.test(source)) offenders.push(`${relative} uses an arbitrary font value`);
      if (/\bfontFamily\s*:/.test(source)) offenders.push(`${relative} sets fontFamily`);
    }
    expect(offenders).toEqual([]);
  });

  it("scans a meaningful number of files", () => {
    expect(walk(WEB_ROOT).length).toBeGreaterThan(20);
  });

  it("keeps every exempt path real", () => {
    for (const relative of EXEMPT) {
      expect(existsSync(path.join(WEB_ROOT, relative)), `${relative} is missing`).toBe(true);
    }
  });
});

describe("criteria 1, 4, 5 — what is mechanically checkable about the evidence", () => {
  const woff2 = readdirSync(FONT_DIR)
    .filter((name) => name.endsWith(".woff2"))
    .sort();

  it("self-hosts every face: no external font host is referenced", () => {
    // The C3 CSP's font-src 'self' would refuse one anyway.
    for (const source of [tokensCss, fallbackCss, fontsSource]) {
      expect(source).not.toMatch(/https?:\/\/[^\s"')]*(fonts\.|font|typekit|cdn)/i);
    }
    expect(fallbackCss).not.toContain("url(");
  });

  it("declares font-display: swap for every self-hosted family", () => {
    const displays = [...fontsSource.matchAll(/display:\s*"([a-z]+)"/g)].map((m) => m[1]);
    expect(displays).toHaveLength(FAMILIES.length);
    expect(new Set(displays)).toEqual(new Set(["swap"]));
  });

  it("commits an SIL OFL 1.1 licence for each of the three families", () => {
    const licences = readdirSync(FONT_DIR).filter((name) => name.startsWith("OFL-"));
    expect(licences).toHaveLength(FAMILIES.length);
    for (const licence of licences) {
      const text = readFileSync(path.join(FONT_DIR, licence), "utf8");
      expect(text, `${licence} is not the OFL`).toContain("SIL OPEN FONT LICENSE Version 1.1");
    }
  });

  it("carries a measured size-adjust triple for each family in fallback.css", () => {
    for (const family of FAMILIES) {
      const block = new RegExp(
        `font-family:\\s*"${family.adjusted}";[\\s\\S]*?\\}`,
      ).exec(fallbackCss);
      expect(block, `fallback.css has no face for ${family.adjusted}`).not.toBeNull();
      const rule = (block as RegExpExecArray)[0] as string;
      for (const descriptor of ["size-adjust", "ascent-override", "descent-override"]) {
        expect(rule, `${family.adjusted} is missing ${descriptor}`).toMatch(
          new RegExp(`${descriptor}:\\s*\\d+(\\.\\d+)?%`),
        );
      }
      // line-gap-override is 0% because every shipped face has hhea
      // lineGap 0; measure-fonts.mjs re-checks that from the woff2 files.
      expect(rule).toMatch(/line-gap-override:\s*0%/);
      expect(rule, "the adjusted face must name concrete local fonts").toContain("local(");
    }
  });

  it("includes Literata Italic 400 per RC-20", () => {
    expect(woff2).toContain("Literata-Italic-400.woff2");
    expect(fontsSource).toMatch(/path:\s*"\.\/Literata-Italic-400\.woff2",\s*\n?\s*weight:\s*"400",\s*\n?\s*style:\s*"italic"/);
  });

  it("keeps the committed woff2 total inside the RC-01 font budget", () => {
    const total = woff2.reduce(
      (sum, name) => sum + statSync(path.join(FONT_DIR, name)).size,
      0,
    );
    expect(
      total,
      `committed woff2 total is ${total} B against a ${FONT_BUDGET_BYTES} B budget; ` +
        "raise it under the ratchet rule with the fonts.md table as justification, " +
        "or ship smaller faces -- do not edit this number",
    ).toBeLessThanOrEqual(FONT_BUDGET_BYTES);
  });
});
