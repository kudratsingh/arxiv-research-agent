import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RootLayout from "@/app/layout";
import * as tokens from "@/lib/tokens";
import tailwindConfig from "@/tailwind.config";

/**
 * WO-01 acceptance criteria 1, 2, 3, 4, 5, 6, 7.
 *
 * docs/revamp/design/tokens.json is the source of truth. The tables in
 * 03-DESIGN-BRIEF.md sections 3.2 and 3.3 are curated excerpts that omit
 * twelve tokens (RC-15), so nothing here reads the brief; the
 * enumeration below IS the authoritative implementation list.
 */

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const WEB_ROOT = path.resolve(TESTS_DIR, "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const TOKENS_CSS = path.join(WEB_ROOT, "app", "tokens.css");
const TOKENS_JSON = path.join(REPO_ROOT, "docs", "revamp", "design", "tokens.json");

// --------------------------------------------------------------- tokens.json

interface ScaleStep {
  size: string;
  line: string;
  tracking?: string;
  weight?: number;
  use?: string;
}

interface ContrastCheck {
  pair: string;
  fg: string;
  bg: string;
  ratio: number;
  requires: string;
  result: string;
}

interface Regression {
  baseline: string;
  ratio: number;
  source: string;
  replacedBy: string;
}

interface TokensJson {
  color: Record<"light" | "dark", Record<string, string>>;
  contrastChecks: ContrastCheck[];
  regressionsFixed: Regression[];
  typography: {
    families: Record<string, { stack: string; license: string; role: string; weights: number[] }>;
    loading: Record<string, string>;
    scale: Record<string, ScaleStep>;
    rules: string[];
  };
  space: { unit: string; scale: Record<string, string>; layout: Record<string, string> };
  size: Record<string, string>;
  radius: Record<string, string>;
  elevation: Record<"light" | "dark", Record<string, string>> & { rules: string[] };
  motion: {
    duration: Record<string, string>;
    easing: Record<string, string>;
    assignments: Record<string, string>;
    reducedMotion: { query: string; policy: string[] };
  };
  status: Record<string, unknown>;
}

const json = JSON.parse(readFileSync(TOKENS_JSON, "utf8")) as TokensJson;
const css = readFileSync(TOKENS_CSS, "utf8");

type Theme = "light" | "dark";
const THEMES: Theme[] = ["light", "dark"];

// ------------------------------------------------------- the naming contract

/**
 * How a tokens.json key becomes a CSS custom property. This is the whole
 * of RC-02's reconciled namespace: --color-* --space-* --radius-*
 * --font-* --text-* --duration-* --ease-*, plus --elevation-*, --layout-*
 * and --size-* for the families 04 section 6.1 had no namespace for.
 */
const NAME = {
  color: (key: string) => `--color-${key}`,
  elevation: (key: string) => `--elevation-${key.replace(/^elev-/, "")}`,
  space: (key: string) => `--${key}`,
  layout: (key: string) => `--layout-${key}`,
  size: (key: string) => `--size-${key}`,
  radius: (key: string) => `--${key}`,
  font: (key: string) => `--font-${key}`,
  text: (step: string, facet: string) => `--text-${step}-${facet}`,
  duration: (key: string) => `--duration-${key.replace(/^dur-/, "")}`,
  ease: (key: string) => `--${key}`,
};

/** Facets of a type step that become custom properties. `use` is prose. */
const TEXT_FACETS = ["size", "line", "tracking", "weight"] as const;

/** The properties whose value depends on the active theme. */
function themedTokens(theme: Theme): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(json.color[theme])) out.set(NAME.color(key), value);
  for (const [key, value] of Object.entries(json.elevation[theme])) {
    out.set(NAME.elevation(key), value);
  }
  return out;
}

/** The properties that are the same in both themes. */
function sharedTokens(): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(json.space.scale)) out.set(NAME.space(key), value);
  for (const [key, value] of Object.entries(json.space.layout)) out.set(NAME.layout(key), value);
  for (const [key, value] of Object.entries(json.size)) out.set(NAME.size(key), value);
  for (const [key, value] of Object.entries(json.radius)) {
    if (key === "rule") continue; // prose, not a token
    out.set(NAME.radius(key), value);
  }
  for (const [key, family] of Object.entries(json.typography.families)) {
    out.set(NAME.font(key), family.stack);
  }
  for (const [step, facets] of Object.entries(json.typography.scale)) {
    for (const facet of TEXT_FACETS) {
      const value = facets[facet];
      if (value === undefined) continue;
      out.set(NAME.text(step, facet), String(value));
    }
  }
  for (const [key, value] of Object.entries(json.motion.duration)) {
    out.set(NAME.duration(key), value);
  }
  for (const [key, value] of Object.entries(json.motion.easing)) out.set(NAME.ease(key), value);
  return out;
}

// ------------------------------------------------------------- the CSS parser

interface Rule {
  chain: string[];
  declarations: Map<string, string>;
}

function parseDeclarations(body: string): Map<string, string> {
  const out = new Map<string, string>();
  const pattern = /([-a-zA-Z][-a-zA-Z0-9]*)\s*:\s*([^;]+);/g;
  let match = pattern.exec(body);
  while (match !== null) {
    out.set(match[1] as string, (match[2] as string).trim());
    match = pattern.exec(body);
  }
  return out;
}

/** Flat list of every rule in the sheet, keyed by its at-rule/selector chain. */
function parseRules(source: string): Rule[] {
  const stripped = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules: Rule[] = [];

  const walk = (input: string, chain: string[]): void => {
    let prelude = "";
    let index = 0;
    while (index < input.length) {
      const character = input[index] as string;
      if (character !== "{") {
        prelude += character;
        index += 1;
        continue;
      }
      let depth = 1;
      let end = index + 1;
      while (end < input.length && depth > 0) {
        if (input[end] === "{") depth += 1;
        else if (input[end] === "}") depth -= 1;
        end += 1;
      }
      const body = input.slice(index + 1, end - 1);
      const nextChain = [...chain, prelude.trim().replace(/\s+/g, " ")];
      if (body.includes("{")) walk(body, nextChain);
      else rules.push({ chain: nextChain, declarations: parseDeclarations(body) });
      prelude = "";
      index = end;
    }
  };

  walk(stripped, []);
  return rules;
}

const rules = parseRules(css);

function ruleFor(...chain: string[]): Rule {
  const found = rules.filter(
    (rule) =>
      rule.chain.length === chain.length && rule.chain.every((part, i) => part === chain[i]),
  );
  if (found.length !== 1) {
    throw new Error(
      `expected exactly one rule for [${chain.join(" > ")}] in app/tokens.css, found ${found.length}`,
    );
  }
  return found[0] as Rule;
}

const customProperties = (rule: Rule): Map<string, string> =>
  new Map([...rule.declarations].filter(([name]) => name.startsWith("--")));

const ROOT = ruleFor(":root");
const DARK_MEDIA = ruleFor("@media (prefers-color-scheme: dark)", ":root");
const DARK_ATTRIBUTE = ruleFor(':root[data-theme="dark"]');
const LIGHT_ATTRIBUTE = ruleFor(':root[data-theme="light"]');
const REDUCED_MOTION = ruleFor("@media (prefers-reduced-motion: reduce)", ":root");

const sorted = (map: Map<string, string>) =>
  [...map.entries()].sort(([a], [b]) => a.localeCompare(b));

// ------------------------------------------------------------- colour helpers

function relativeLuminance(hex: string): number {
  const digits = hex.replace("#", "");
  const full =
    digits.length === 3
      ? digits
          .split("")
          .map((digit) => digit + digit)
          .join("")
      : digits;
  const [r = 0, g = 0, b = 0] = [0, 2, 4]
    .map((offset) => parseInt(full.slice(offset, offset + 2), 16) / 255)
    .map((channel) =>
      channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4),
    );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2.x: (L1 + 0.05) / (L2 + 0.05), exactly as tokens.json $meta records. */
function contrastRatio(foreground: string, background: string): number {
  const a = relativeLuminance(foreground);
  const b = relativeLuminance(background);
  const [lighter, darker] = a > b ? [a, b] : [b, a];
  return (lighter + 0.05) / (darker + 0.05);
}

/** Every colour declared for a theme in tokens.css, as name -> hex. */
function declaredColours(theme: Theme): Map<string, string> {
  const rule = theme === "light" ? ROOT : DARK_ATTRIBUTE;
  return new Map(
    [...customProperties(rule)]
      .filter(([name]) => name.startsWith("--color-"))
      .map(([name, value]) => [name, value.toUpperCase()]),
  );
}

/** Resolve a hex back to the tokens.css declaration(s) that produce it. */
function fromTokensCss(hex: string, theme: Theme): string {
  const wanted = hex.toUpperCase();
  const names = [...declaredColours(theme)]
    .filter(([, value]) => value === wanted)
    .map(([name]) => name);
  expect(
    names,
    `${hex} is used by a contrast check but is not declared in the ${theme} theme of app/tokens.css`,
  ).not.toHaveLength(0);
  return declaredColours(theme).get(names[0] as string) as string;
}

// =============================================================================

describe("criterion 2 — tokens.css / tokens.ts / tokens.json parity, both themes", () => {
  it("declares exactly the shared and light-theme tokens on :root", () => {
    const expected = new Map([...sharedTokens(), ...themedTokens("light")]);
    expect(sorted(customProperties(ROOT))).toEqual(sorted(expected));
  });

  it.each(["@media (prefers-color-scheme: dark)", ':root[data-theme="dark"]'])(
    "declares exactly the dark themed tokens under %s",
    (selector) => {
      const rule = selector.startsWith("@media") ? DARK_MEDIA : DARK_ATTRIBUTE;
      expect(sorted(customProperties(rule))).toEqual(sorted(themedTokens("dark")));
    },
  );

  it('declares exactly the light themed tokens under :root[data-theme="light"]', () => {
    expect(sorted(customProperties(LIGHT_ATTRIBUTE))).toEqual(sorted(themedTokens("light")));
  });

  it("declares 23 colour tokens in each theme (RC-15: the brief's tables omit 12)", () => {
    for (const theme of THEMES) {
      expect(Object.keys(json.color[theme])).toHaveLength(23);
      expect(declaredColours(theme).size).toBe(23);
    }
    expect(Object.keys(json.color.light).sort()).toEqual(Object.keys(json.color.dark).sort());
  });

  it("creates no success or warning hue, and maps the severities instead (RC-17)", () => {
    for (const invented of ["success", "warning"]) {
      expect(Object.keys(tokens.color)).not.toContain(invented);
      expect(customProperties(ROOT).has(`--color-${invented}`)).toBe(false);
    }
    expect(Object.keys(tokens.STATUS_SEVERITY_ROLE).sort()).toEqual([
      "critical",
      "info",
      "live",
      "review",
      "warning",
    ]);
    for (const role of Object.values(tokens.STATUS_SEVERITY_ROLE)) {
      expect(Object.keys(json.color.light)).toContain(role);
    }
    // Each severity still carries a distinct word and mark (03 3.4), which
    // is what differentiates warning from review without a second hue.
    expect(Object.keys(json.status).length).toBeGreaterThan(1);
  });

  it("declares all five durations, including dur-instant (RC-02's union)", () => {
    const durations = [...customProperties(ROOT)].filter(([name]) =>
      name.startsWith("--duration-"),
    );
    expect(durations).toHaveLength(5);
    expect(customProperties(ROOT).get("--duration-instant")).toBe("0ms");
  });

  it("maps every tokens.ts name onto a declared property, and no property is orphaned", () => {
    const references = new Map<string, string>();
    const record = (family: string, key: string, reference: string) => {
      const match = /^var\((--[a-z0-9-]+)\)$/.exec(reference);
      expect(match, `${family}.${key} must be a bare var() reference, got ${reference}`).not.toBeNull();
      const property = (match as RegExpExecArray)[1] as string;
      expect(references.has(property), `${property} is referenced twice in tokens.ts`).toBe(false);
      references.set(property, `${family}.${key}`);
    };

    const flat: [string, Readonly<Record<string, string>>][] = [
      ["color", tokens.color],
      ["elevation", tokens.elevation],
      ["space", tokens.space],
      ["layout", tokens.layout],
      ["size", tokens.size],
      ["radius", tokens.radius],
      ["font", tokens.font],
      ["duration", tokens.duration],
      ["ease", tokens.ease],
    ];
    for (const [family, group] of flat) {
      for (const [key, reference] of Object.entries(group)) record(family, key, reference);
    }
    for (const [step, facets] of Object.entries(tokens.text)) {
      for (const [facet, reference] of Object.entries(facets as Record<string, string>)) {
        record("text", `${step}.${facet}`, reference);
      }
    }

    // Both directions: no name in tokens.ts is undeclared, and no
    // declared property is missing from tokens.ts.
    expect([...references.keys()].sort()).toEqual([...customProperties(ROOT).keys()].sort());
  });

  it("keeps tokens.ts free of literal values", () => {
    const source = readFileSync(path.join(WEB_ROOT, "lib", "tokens.ts"), "utf8");
    const code = source.replace(/\/\*\*[\s\S]*?\*\//g, "");
    for (const [, value] of Object.entries(json.color.light)) {
      expect(code).not.toContain(value);
    }
    for (const [, value] of Object.entries(json.color.dark)) {
      expect(code).not.toContain(value);
    }
  });

  it("treats every key in tokens.json as either a token or documented prose", () => {
    // Guards the orphan direction against tokens.json growing: a new key
    // anywhere below fails here until it is either mapped or declared
    // non-token on purpose.
    expect(Object.keys(json).sort()).toEqual(
      [
        "$meta",
        "color",
        "contrastChecks",
        "elevation",
        "motion",
        "radius",
        "regressionsFixed",
        "size",
        "space",
        "status",
        "typography",
      ].sort(),
    );
    expect(Object.keys(json.space).sort()).toEqual(["layout", "scale", "unit"]);
    expect(Object.keys(json.elevation).sort()).toEqual(["dark", "light", "rules"]);
    expect(Object.keys(json.motion).sort()).toEqual([
      "assignments",
      "duration",
      "easing",
      "reducedMotion",
    ]);
    expect(Object.keys(json.typography).sort()).toEqual([
      "families",
      "loading",
      "rules",
      "scale",
    ]);
    expect(Object.keys(json.radius).filter((key) => key === "rule")).toEqual(["rule"]);
    for (const family of Object.values(json.typography.families)) {
      expect(Object.keys(family).sort()).toEqual(["license", "role", "stack", "weights"]);
    }
    for (const [step, facets] of Object.entries(json.typography.scale)) {
      const unknown = Object.keys(facets).filter(
        (facet) => !(TEXT_FACETS as readonly string[]).includes(facet) && facet !== "use",
      );
      expect(unknown, `unmapped facet on type step ${step}`).toEqual([]);
    }
  });
});

describe("criterion 3 — every recorded contrast ratio recomputes from tokens.css", () => {
  it.each(json.contrastChecks.map((check) => [check.pair, check] as const))(
    "%s",
    (_pair, check) => {
      const theme: Theme = check.pair.startsWith("dark ") ? "dark" : "light";
      const ratio = contrastRatio(fromTokensCss(check.fg, theme), fromTokensCss(check.bg, theme));
      expect(
        Math.abs(ratio - check.ratio),
        `${check.pair}: recomputed ${ratio.toFixed(4)}, tokens.json records ${check.ratio}`,
      ).toBeLessThanOrEqual(0.01);
    },
  );

  it("covers both themes", () => {
    const dark = json.contrastChecks.filter((check) => check.pair.startsWith("dark "));
    expect(dark.length).toBeGreaterThan(0);
    expect(json.contrastChecks.length - dark.length).toBeGreaterThan(0);
  });

  it.each(json.regressionsFixed.map((entry) => [entry.baseline, entry] as const))(
    "baseline regression %s is fixed by a token pair",
    (_baseline, regression) => {
      // The baseline pair: hexes that no longer exist anywhere in web/.
      const baselinePair = regression.baseline.match(/#[0-9a-fA-F]{6}/g);
      expect(baselinePair, `could not read a colour pair from "${regression.baseline}"`).toHaveLength(2);
      const [baselineFg, baselineBg] = baselinePair as string[];
      const baselineRatio = contrastRatio(baselineFg as string, baselineBg as string);
      expect(Math.abs(baselineRatio - regression.ratio)).toBeLessThanOrEqual(0.01);
      expect(regression.ratio).toBeLessThan(4.5);

      // The replacement pair: named tokens, recomputed from tokens.css.
      const parsed =
        /^([a-z-]+) (#[0-9a-fA-F]{6}) on ([a-z-]+) (#[0-9a-fA-F]{6})(?: at ([\d.]+)px)? = ([\d.]+)$/.exec(
          regression.replacedBy,
        );
      expect(parsed, `could not read a replacement from "${regression.replacedBy}"`).not.toBeNull();
      const [, fgName, fgHex, bgName, bgHex, size, expectedRatio] = parsed as RegExpExecArray;

      const light = declaredColours("light");
      expect(light.get(`--color-${fgName}`)).toBe((fgHex as string).toUpperCase());
      expect(light.get(`--color-${bgName}`)).toBe((bgHex as string).toUpperCase());

      const fixed = contrastRatio(
        fromTokensCss(fgHex as string, "light"),
        fromTokensCss(bgHex as string, "light"),
      );
      expect(Math.abs(fixed - Number(expectedRatio))).toBeLessThanOrEqual(0.01);
      expect(fixed).toBeGreaterThanOrEqual(4.5);
      if (size !== undefined) expect(Number(size)).toBeGreaterThanOrEqual(12);
    },
  );

  it("records three baseline regressions, matching 03 section 3.1", () => {
    expect(json.regressionsFixed).toHaveLength(3);
  });
});

describe("criterion 4 — both dark mechanisms, the light override, and Tailwind's darkMode", () => {
  it("declares color-scheme on :root and pins it under each override", () => {
    expect(ROOT.declarations.get("color-scheme")).toBe("light dark");
    expect(DARK_ATTRIBUTE.declarations.get("color-scheme")).toBe("dark");
    expect(LIGHT_ATTRIBUTE.declarations.get("color-scheme")).toBe("light");
  });

  it("gives the media fallback and the attribute override identical dark values", () => {
    expect(sorted(customProperties(DARK_MEDIA))).toEqual(sorted(customProperties(DARK_ATTRIBUTE)));
  });

  it("lets the attribute override win over the media query by specificity", () => {
    // (0,2,0) for :root[data-theme=...] against (0,1,0) for :root, so
    // source order inside the sheet cannot change the outcome.
    const rootIndex = css.indexOf("@media (prefers-color-scheme: dark)");
    const overrideIndex = css.indexOf(':root[data-theme="light"]');
    expect(rootIndex).toBeGreaterThan(-1);
    expect(overrideIndex).toBeGreaterThan(-1);
    for (const selector of [':root[data-theme="dark"]', ':root[data-theme="light"]']) {
      expect(css).toContain(selector);
    }
  });

  it("collapses every non-zero duration under prefers-reduced-motion", () => {
    const collapsed = customProperties(REDUCED_MOTION);
    const nonZero = Object.entries(json.motion.duration).filter(([, value]) => value !== "0ms");
    expect([...collapsed.keys()].sort()).toEqual(
      nonZero.map(([key]) => NAME.duration(key)).sort(),
    );
    for (const [, value] of collapsed) expect(value).toBe("1ms");
  });

  it("configures Tailwind darkMode as the class + attribute pair", () => {
    expect(tailwindConfig.darkMode).toEqual(["class", '[data-theme="dark"]']);
  });

  it("builds every Tailwind theme value from tokens.ts", () => {
    const extend = (tailwindConfig.theme?.extend ?? {}) as Record<string, unknown>;
    const strip = (group: Readonly<Record<string, string>>, prefix: string) =>
      Object.fromEntries(
        Object.entries(group).map(([key, value]) => [key.replace(prefix, ""), value]),
      );

    expect(extend.colors).toEqual({ ...tokens.color });
    expect(extend.spacing).toEqual({
      ...strip(tokens.space, "space-"),
      "gutter-narrow": tokens.layout["gutter-narrow"],
      "gutter-wide": tokens.layout["gutter-wide"],
    });
    expect(extend.borderRadius).toEqual(strip(tokens.radius, "radius-"));
    expect(extend.boxShadow).toEqual({ ...tokens.elevation });
    expect(extend.transitionDuration).toEqual(strip(tokens.duration, "dur-"));
    expect(extend.transitionTimingFunction).toEqual(strip(tokens.ease, "ease-"));
    expect(extend.fontFamily).toEqual({ ...tokens.font, sans: tokens.font.ui });
    expect(Object.keys(extend.fontSize as object).sort()).toEqual(
      Object.keys(tokens.text).sort(),
    );
  });

  it("maps every custom property into Tailwind except the documented omissions", () => {
    const referenced = new Set<string>();
    const collect = (value: unknown): void => {
      if (typeof value === "string") {
        for (const match of value.matchAll(/var\((--[a-z0-9-]+)\)/g)) {
          referenced.add(match[1] as string);
        }
      } else if (Array.isArray(value)) value.forEach(collect);
      else if (value && typeof value === "object") Object.values(value).forEach(collect);
    };
    collect(tailwindConfig.theme?.extend);

    const unmapped = [...customProperties(ROOT).keys()]
      .filter((property) => !referenced.has(property))
      .sort();
    const expectedUnmapped = [
      ...Object.keys(json.size).map(NAME.size),
      ...Object.keys(json.space.layout)
        .filter((key) => key.startsWith("breakpoint-"))
        .map(NAME.layout),
    ].sort();
    // Both lists are stated in the comment at the foot of
    // web/tailwind.config.ts. Anything else falling out of Tailwind is a
    // mistake, not a decision.
    expect(unmapped).toEqual(expectedUnmapped);
  });
});

describe("criterion 5 — the pre-paint theme script", () => {
  const matches = { value: false };

  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-theme-preference");
    matches.value = false;
    vi.stubGlobal("matchMedia", (query: string) => ({
      media: query,
      matches: matches.value,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      onchange: null,
      dispatchEvent: () => false,
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  const run = () => {
    new Function(tokens.themeInitScript)();
    return {
      theme: document.documentElement.getAttribute("data-theme"),
      preference: document.documentElement.getAttribute("data-theme-preference"),
    };
  };

  it("documents exactly the two persisted keys (RC-05)", () => {
    expect(tokens.THEME_STORAGE_KEY).toBe("arxiv-agent.theme");
    expect(tokens.RAIL_COLLAPSED_STORAGE_KEY).toBe("arxiv-agent.rail-collapsed");
    expect(tokens.THEME_PREFERENCES).toEqual(["light", "dark", "system"]);
    // No job handle is ever persisted; 04 section 4.4 depends on it.
    expect(tokens.themeInitScript).toContain(tokens.THEME_STORAGE_KEY);
    expect(tokens.themeInitScript).not.toContain("job");
  });

  it.each(["dark", "light"] as const)("applies the stored %s override", (preference) => {
    window.localStorage.setItem(tokens.THEME_STORAGE_KEY, preference);
    matches.value = preference === "light"; // the OS disagrees, on purpose
    expect(run()).toEqual({ theme: preference, preference });
  });

  it.each([
    [true, "dark"],
    [false, "light"],
  ])("resolves the system preference when nothing is stored (dark=%s)", (dark, expected) => {
    matches.value = dark as boolean;
    expect(run()).toEqual({ theme: expected, preference: "system" });
  });

  it("treats an unrecognised stored value as system", () => {
    window.localStorage.setItem(tokens.THEME_STORAGE_KEY, "sepia");
    matches.value = true;
    expect(run()).toEqual({ theme: "dark", preference: "system" });
  });

  it("survives storage being unavailable without throwing before paint", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage is partitioned");
    });
    expect(() => run()).not.toThrow();
    expect(document.documentElement.getAttribute("data-theme")).toBeNull();
  });

  it("is inlined in the document head, ahead of the body", async () => {
    // `await RootLayout(...)` rather than `createElement(RootLayout, ...)`:
    // WO-30 made the root layout async so it can read the per-request CSP
    // nonce, and `renderToStaticMarkup` is the legacy synchronous renderer.
    // Every assertion below is unchanged, and the one WO-30 could have
    // broken — "no defer, no async" — is exactly the one that matters: the
    // nonce is an attribute, not a loading mode, so the script stays
    // synchronous and still runs before first paint.
    const markup = renderToStaticMarkup(
      await RootLayout({ children: createElement("main") }),
    );
    // Attribute-wise rather than string-wise: WO-02 added the three
    // next/font variable classes to this element, and WO-08 will add more.
    // What criterion 5 is about is the lang and the inline script, not the
    // exact attribute set.
    expect(markup).toMatch(/<html\b[^>]*\blang="en"/);
    expect(markup).toContain(tokens.THEME_STORAGE_KEY);
    const scriptIndex = markup.indexOf(tokens.themeInitScript);
    expect(scriptIndex, "the theme script is not inlined in the layout").toBeGreaterThan(-1);
    expect(scriptIndex).toBeLessThan(markup.indexOf("<body"));
    // Synchronous: a deferred or async script paints light first.
    expect(markup).not.toMatch(/<script[^>]*\b(defer|async)\b/);
  });
});

describe("criterion 6 — app/icon.svg, and no public/ directory", () => {
  it("ships app/icon.svg so Next emits a site icon", () => {
    const icon = path.join(WEB_ROOT, "app", "icon.svg");
    expect(existsSync(icon)).toBe(true);
    const source = readFileSync(icon, "utf8");
    expect(source).toContain("<svg");
    expect(source).toContain('viewBox="0 0 32 32"');
  });

  it("introduces no public/ directory, keeping web/Dockerfile's comment true", () => {
    expect(existsSync(path.join(WEB_ROOT, "public"))).toBe(false);
    const dockerfile = readFileSync(path.join(WEB_ROOT, "Dockerfile"), "utf8");
    expect(dockerfile).toContain("public/ is optional");
  });
});

describe("criterion 7 — minimum rendered size is 12px anywhere", () => {
  const declaredSizes = [...customProperties(ROOT)]
    .filter(([name]) => name.startsWith("--text-") && name.endsWith("-size"))
    .map(([name, value]) => [name, Number.parseFloat(value)] as const);

  it("declares a size for every type step", () => {
    expect(declaredSizes).toHaveLength(Object.keys(json.typography.scale).length);
  });

  it.each(declaredSizes)("%s is at least 12px", (_name, size) => {
    expect(size).toBeGreaterThanOrEqual(12);
  });

  it("reproduces no step at the baseline's deleted 10.4px job-id size", () => {
    // Read the forbidden size out of the regression record rather than
    // hard-coding it: deleting that label is one of the three contrast
    // fixes in 03 section 3.1, so the two facts share a source.
    const jobIdLabel = json.regressionsFixed[0] as Regression;
    const forbidden = Number(/at ([\d.]+)px/.exec(jobIdLabel.baseline)?.[1]);
    expect(forbidden).toBe(10.4);
    for (const [, size] of declaredSizes) expect(size).not.toBe(forbidden);
    expect(css.replace(/\/\*[\s\S]*?\*\//g, "")).not.toContain(`${forbidden}px`);
  });

  it("keeps tokens.json's own scale above the floor", () => {
    for (const [step, facets] of Object.entries(json.typography.scale)) {
      expect(Number.parseFloat(facets.size), `${step} is below the 12px floor`).toBeGreaterThanOrEqual(12);
    }
    expect(json.typography.rules[0]).toContain("12px");
  });
});

describe("criterion 1 — tokens.css is the only file in web/ with a literal colour", () => {
  // Deliberately narrower than the ESLint selectors, because this scan
  // also reads prose, CSS and SVG: the lookbehind spares HTML numeric
  // entities (&#9662;), and requiring a digit after the paren spares a
  // sentence that merely names rgb() or hsl(). The trailing (?!\w)
  // spares hex-like prefixes of longer words — no real colour is ever
  // followed by a word character, but Next's client-reference-manifest
  // module keys end in hash-default, whose first four letters after the
  // hash all happen to be valid hex digits.
  const HEX = /(?<!&)#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?!\w)/;
  const FUNCTIONAL = /\b(?:rgb|rgba|hsl|hsla)\(\s*[\d.]/;
  const SCANNED = new Set([".ts", ".tsx", ".css", ".mjs", ".js", ".svg"]);
  const SKIP = new Set(["node_modules", ".next", "out", "build", ".git"]);

  /**
   * The complete exemption list, and why each entry is on it:
   *   app/tokens.css   the single source of values (criterion 1)
   *   app/icon.svg     a favicon has no CSS context to inherit from
   *   the fixture      is required to fail lint (criterion 1's proof)
   */
  const EXEMPT = new Set([
    "app/tokens.css",
    "app/icon.svg",
    "tests/fixtures/literal-colour.fixture.tsx",
  ]);

  const walk = (directory: string, found: string[] = []): string[] => {
    for (const entry of readdirSync(directory)) {
      if (SKIP.has(entry)) continue;
      const absolute = path.join(directory, entry);
      if (statSync(absolute).isDirectory()) walk(absolute, found);
      else if (SCANNED.has(path.extname(entry))) found.push(absolute);
    }
    return found;
  };

  it("finds no literal colour outside the exemption list", () => {
    const offenders: string[] = [];
    for (const file of walk(WEB_ROOT)) {
      const relative = path.relative(WEB_ROOT, file);
      if (EXEMPT.has(relative)) continue;
      const source = readFileSync(file, "utf8");
      if (HEX.test(source) || FUNCTIONAL.test(source)) offenders.push(relative);
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

describe("criterion 1 — the ESLint rule fires on a real file", () => {
  const fixtures = path.join(WEB_ROOT, "tests", "fixtures");

  it(
    "rejects the literal-colour fixture and accepts the token fixture",
    { timeout: 120_000 },
    async () => {
      const { ESLint } = await import("eslint");
      const eslint = new ESLint({ cwd: WEB_ROOT });

      const [bad] = await eslint.lintFiles([
        path.join(fixtures, "literal-colour.fixture.tsx"),
      ]);
      const violations = (bad?.messages ?? []).filter(
        (message) => message.ruleId === "no-restricted-syntax",
      );
      // Six literals: two hex constants, one rgb(), one hsl(), one hex
      // in a Tailwind arbitrary value, one hex in a template literal.
      expect(violations.length).toBeGreaterThanOrEqual(6);
      for (const violation of violations) {
        expect(violation.message).toContain("Literal colours are not allowed here");
      }

      const [good] = await eslint.lintFiles([path.join(fixtures, "token-colour.fixture.tsx")]);
      expect(good?.errorCount, JSON.stringify(good?.messages ?? [])).toBe(0);
    },
  );

  /**
   * WO-31 acceptance criterion 3 — enforced with NO path allow-list.
   *
   * This test used to assert the opposite: that every legacy component was
   * named in an `ignores` array "until WO-31". WO-01 needed that array
   * because the nine components predated the token layer; WO-20 rewrote the
   * two route files that were also on it, and this work order deleted the
   * nine. Nothing is exempt any more, and the assertion is now the ratchet
   * that keeps it that way — a per-file exemption added to silence a red
   * lint fails here.
   *
   * The rule's `files` list still names `tests/fixtures/**`, which is not an
   * exemption but its opposite: it is how `literal-colour.fixture.tsx` gets
   * linted at all, and the test above is what proves the rule fires.
   */
  it("carries no path allow-list — the rule is enforced everywhere", () => {
    const config = readFileSync(path.join(WEB_ROOT, "eslint.config.mjs"), "utf8");

    // The rule's own config block, from its `name` to the end of its
    // `rules` key. An `ignores` anywhere inside it is an exemption.
    const start = config.indexOf('name: "tokens/no-literal-colour"');
    expect(start, "the no-literal-colour block is gone").toBeGreaterThan(-1);
    const end = config.indexOf('"no-restricted-syntax": ["error", ...noLiteralColour]', start);
    expect(end).toBeGreaterThan(start);
    expect(config.slice(start, end)).not.toContain("ignores");

    // And no entry the array used to name appears anywhere else in it.
    // Nine were components WO-31 deleted; two were WO-08's route paths,
    // which are alive and now in scope of the rule.
    const DELETED_COMPONENTS = [
      "components/ConversationSidebar.tsx",
      "components/ConversationThread.tsx",
      "components/ConversationsShell.tsx",
      "components/EventLog.tsx",
      "components/ExportDropdown.tsx",
      "components/JobSummary.tsx",
      "components/PlanReview.tsx",
      "components/QueryForm.tsx",
      "components/ReportView.tsx",
    ];
    const EXEMPTED_ROUTES = ["app/(workspace)/page.tsx", "app/(workspace)/c/**/page.tsx"];

    for (const entry of [...DELETED_COMPONENTS, ...EXEMPTED_ROUTES]) {
      expect(config, `${entry} is still named in the lint config`).not.toContain(entry);
    }
    for (const component of DELETED_COMPONENTS) {
      expect(existsSync(path.join(WEB_ROOT, component)), `${component} still exists`).toBe(
        false,
      );
    }
  });

  /**
   * The rule now really does reach the two route files WO-01 exempted.
   * Without this, "no allow-list" would be a claim about the config text
   * rather than about what ESLint enforces.
   */
  it("lints the route files WO-01 had exempted", { timeout: 120_000 }, async () => {
    const { ESLint } = await import("eslint");
    const eslint = new ESLint({ cwd: WEB_ROOT });
    const routes = ["app/(workspace)/page.tsx", "app/(workspace)/c/[id]/page.tsx"];

    for (const route of routes) {
      const [result] = await eslint.lintFiles([path.join(WEB_ROOT, route)]);
      const config = await eslint.calculateConfigForFile(path.join(WEB_ROOT, route));
      // In scope: the rule is configured for this file. `calculateConfig`
      // normalizes the severity to its numeric form, so 2 IS "error".
      const [severity, ...options] = config.rules?.["no-restricted-syntax"] ?? [];
      expect(severity, `${route} is not linted`).toBe(2);
      // ...and it is WO-01's colour selectors that are configured, not some
      // other no-restricted-syntax block that replaced them.
      expect(
        JSON.stringify(options),
        `${route} does not carry the colour selectors`,
      ).toContain("Literal colours are not allowed here");
      // ...and clean under it.
      expect(result?.errorCount, `${route}: ${JSON.stringify(result?.messages ?? [])}`).toBe(0);
    }
  });
});
