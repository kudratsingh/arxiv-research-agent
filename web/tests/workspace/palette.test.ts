import { readFileSync } from "node:fs";
import path from "node:path";
import postcss, { type Rule } from "postcss";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.join(process.cwd(), "app/tokens.css"), "utf8");
const fence = "/* ===== WORKSPACE CONTROLLER PALETTE (planning/12)";
const marker = css.indexOf(fence);
if (marker < 0) throw new Error("Workspace palette fence is missing");
const globalCss = postcss.parse(css.slice(0, marker));
const scopedCss = postcss.parse(css.slice(marker));

function rule(selector: string): Rule {
  const matches: Rule[] = [];
  scopedCss.walkRules(selector, (entry) => { matches.push(entry); });
  expect(matches, `one ${selector} rule`).toHaveLength(1);
  const match = matches[0];
  if (!match) throw new Error(`Missing palette rule: ${selector}`);
  return match;
}

function declarations(entry: Rule): Record<string, string> {
  const values: Record<string, string> = {};
  entry.walkDecls((decl) => {
    expect(values[decl.prop], `duplicate ${decl.prop}`).toBeUndefined();
    values[decl.prop] = decl.value;
  });
  return values;
}

const light = declarations(rule(".workspace-app"));
const dark = declarations(rule(':root[data-theme="dark"] .workspace-app'));
const darkMediaRule = rule(':root:not([data-theme="light"]) .workspace-app');
const darkMedia = declarations(darkMediaRule);

function luminance(value: string): number {
  if (!/^#[0-9a-f]{6}$/i.test(value)) {
    throw new Error(`Contrast value must be an opaque six-digit hex color: ${value}`);
  }
  const channel = (offset: number): number => {
    const v = parseInt(value.slice(offset, offset + 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(values: Record<string, string>, first: string, second: string): number {
  const firstValue = values[first];
  const secondValue = values[second];
  if (firstValue === undefined) throw new Error(`Missing palette value: ${first}`);
  if (secondValue === undefined) throw new Error(`Missing palette value: ${second}`);
  const a = luminance(firstValue);
  const b = luminance(secondValue);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

// Semantic use pairs, not a copy of the palette's color values.
const textPairs: [string, string][] = [
  ...["--color-ink", "--color-ink-muted", "--color-ink-faint", "--color-primary"].flatMap(
    (fg): [string, string][] => ["--color-canvas", "--color-surface", "--ws-raised"].map((bg) => [fg, bg]),
  ),
  ["--color-ink", "--color-sunken"],
  ["--color-ink-muted", "--color-sunken"],
  ["--color-ink", "--ws-accent-soft"],
  ["--color-primary", "--ws-accent-soft"],
  ["--color-signature-text", "--color-surface"],
  ["--color-signature-text", "--ws-accent-soft"],
  ["--color-primary-on", "--color-primary"],
  ["--color-primary-on", "--color-primary-strong"],
  ["--color-signature-on", "--color-signature"],
  ["--color-critical-on", "--color-critical"],
  ["--color-review-text", "--color-review-surface"],
  ["--color-review-text", "--color-surface"],
  ["--color-critical-text", "--color-critical-surface"],
  ["--color-critical-text", "--color-surface"],
];
const markPairs: [string, string][] = [
  ...["--color-surface", "--color-canvas", "--ws-raised"].map((bg): [string, string] => ["--color-border-strong", bg]),
  ["--color-focus", "--color-canvas"],
  ["--color-focus", "--color-surface"],
  // The subtle track is decorative; the fill identifies progress against
  // both that track and the surrounding panel.
  ["--color-primary", "--color-border-subtle"],
  ["--color-primary", "--color-surface"],
  ["--color-primary", "--color-canvas"],
  ["--color-primary", "--ws-raised"],
  ["--ws-success", "--color-surface"],
  ["--color-review", "--color-surface"],
  ["--color-critical", "--color-surface"],
];

describe("scoped workspace palette", () => {
  it("overrides exactly the global color roles and keeps both dark mechanisms identical", () => {
    let root: Rule | undefined;
    globalCss.walkRules(":root", (entry) => { if (!root && entry.parent?.type === "root") root = entry; });
    expect(root).toBeDefined();
    const roles = Object.keys(declarations(root!)).filter((name) => name.startsWith("--color-")).sort();
    expect(roles).toHaveLength(23);
    for (const values of [light, dark, darkMedia]) {
      expect(Object.keys(values).filter((name) => name.startsWith("--color-")).sort()).toEqual(roles);
    }
    expect(darkMediaRule.parent?.type).toBe("atrule");
    expect(darkMediaRule.parent && "params" in darkMediaRule.parent && darkMediaRule.parent.params).toBe("(prefers-color-scheme: dark)");
    expect(Object.keys(light).sort()).toEqual(Object.keys(dark).sort());
    expect(light["color-scheme"]).toBe("light");
    expect(dark["color-scheme"]).toBe("dark");
    expect(darkMedia).toEqual(dark);
  });

  it.each([["light", light], ["dark", dark]] as const)("meets text and UI mark contrast in %s", (_theme, values) => {
    for (const [fg, bg] of textPairs) {
      expect(contrast(values, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
    for (const [fg, bg] of markPairs) {
      expect(contrast(values, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  });
});
