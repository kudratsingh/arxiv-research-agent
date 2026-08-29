/**
 * WO-07 criteria 3, 4 and 9 — the three policies that belong to the library
 * rather than to any one primitive.
 *
 *   3. targets   >= 24 CSS px, 32 by default, 44 under (pointer: coarse),
 *                asserted as COMPUTED sizes at both pointer settings.
 *   4. focus     :focus-visible only, a 2px --focus ring at 2px offset, and
 *                no rule anywhere writing `outline: none` without a
 *                replacement in the same rule.
 *   9. motion    durations collapse to 1ms, transform entrances do not
 *                exist to be dropped, and no information is carried by
 *                motion alone.
 *
 * The jsdom limits these tests work within — no `var()` substitution, no
 * `@media` evaluation beyond `screen`, no `:focus-visible` matching — are
 * documented in ./support/css.ts, and each is handled by feeding the test
 * the AUTHOR'S OWN declarations rather than a restatement of them.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { Button } from "@/components/primitives/Button";
import { Disclosure } from "@/components/primitives/Disclosure";
import { Field } from "@/components/primitives/Field";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { render, screen } from "../support/render";
import {
  WEB_ROOT,
  blockBodyFrom,
  customProperties,
  installStylesheet,
  mediaBlockBody,
  readWebFile,
  resolveComputed,
  resolvePixels,
  ruleBody,
  stripComments,
} from "./support/css";

// Stripped of comments: both sheets quote their own selectors and at-rules
// in prose, so an unstripped search finds the sentence before the rule.
const TOKENS_CSS = stripComments(readWebFile("app/tokens.css"));
const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));
const TOKENS = customProperties(TOKENS_CSS);

const injected: HTMLStyleElement[] = [];

function inject(css: string): void {
  injected.push(installStylesheet(css));
}

/** tokens.css first, then primitives.css — the product's own order. */
function injectProductSheets(): void {
  inject(TOKENS_CSS);
  inject(PRIMITIVES_CSS);
}

afterEach(() => {
  while (injected.length > 0) injected.pop()?.remove();
});

/* =========================================================================
 * Criterion 3 — targets
 * ========================================================================= */

describe("criterion 3 — hit targets at both pointer settings", () => {
  it("carries the three sizes 03 §3.6 names as tokens", () => {
    expect(TOKENS.get("--size-target-min")).toBe("24px");
    expect(TOKENS.get("--size-target-default")).toBe("32px");
    expect(TOKENS.get("--size-target-coarse")).toBe("44px");
  });

  it.each([
    ["sm", 32],
    ["md", 40],
    ["lg", 44],
  ] as const)("a %s button computes to %ipx with a fine pointer", (size, expected) => {
    injectProductSheets();
    render(<Button size={size}>Review plan</Button>);

    const button = screen.getByRole("button", { name: "Review plan" });
    expect(resolvePixels(button, "min-height", TOKENS)).toBe(expected);
    expect(resolvePixels(button, "min-width", TOKENS)).toBe(expected);
    // SC 2.5.8's floor, restated as an assertion rather than as arithmetic
    // a reader has to do.
    expect(resolvePixels(button, "min-height", TOKENS)).toBeGreaterThanOrEqual(24);
  });

  it.each(["sm", "md", "lg"] as const)(
    "a %s button computes to 44px with a coarse pointer",
    (size) => {
      injectProductSheets();
      // The author's own `@media (pointer: coarse)` declarations, applied
      // unconditionally because jsdom will not evaluate the condition.
      inject(mediaBlockBody(PRIMITIVES_CSS, "(pointer: coarse)"));
      render(<Button size={size}>Review plan</Button>);

      const button = screen.getByRole("button", { name: "Review plan" });
      expect(resolvePixels(button, "min-height", TOKENS)).toBe(44);
      expect(resolvePixels(button, "min-width", TOKENS)).toBe(44);
    },
  );

  it("applies the same policy to a disclosure trigger and a field", () => {
    injectProductSheets();
    render(
      <>
        <Disclosure label="Diagnostics">42 frames</Disclosure>
        <Field label="Thread title" />
      </>,
    );

    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    const input = screen.getByLabelText("Thread title");
    expect(resolvePixels(trigger, "min-height", TOKENS)).toBe(32);
    expect(resolvePixels(input, "min-height", TOKENS)).toBe(40);
  });

  it("has no branch that can produce a target below the 24px floor", () => {
    // Every value --ew-target-size can take, read out of the stylesheet.
    const sizes = [...PRIMITIVES_CSS.matchAll(/--ew-target-size:\s*var\((--[a-z0-9-]+)\)/g)].map(
      (match) => match[1] as string,
    );
    expect(sizes.length).toBeGreaterThanOrEqual(4);
    for (const token of sizes) {
      const value = TOKENS.get(token);
      expect(value, `${token} is not a token`).toBeDefined();
      expect(Number.parseFloat(value as string), token).toBeGreaterThanOrEqual(24);
    }
  });
});

/* =========================================================================
 * Criterion 4 — focus
 * ========================================================================= */

/**
 * A rule offends if it kills the outline and puts nothing back in the SAME
 * rule. `outline: none` with a `box-shadow` beside it is fine; `outline:
 * none` alone is not.
 */
function outlineOffenders(css: string): string[] {
  const offenders: string[] = [];
  const REPLACEMENTS = new Set(["outline-width", "outline-style", "outline-color", "box-shadow"]);

  for (const match of stripComments(css).matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const selector = (match[1] ?? "").trim();
    const declarations = (match[2] ?? "")
      .split(";")
      .map((declaration) => declaration.trim())
      .filter(Boolean)
      .map((declaration) => {
        const colon = declaration.indexOf(":");
        return [
          declaration.slice(0, colon).trim().toLowerCase(),
          declaration.slice(colon + 1).trim().toLowerCase(),
        ] as const;
      });

    const suppresses = declarations.some(
      ([property, value]) => property === "outline" && (value === "none" || value === "0"),
    );
    if (!suppresses) continue;

    const replaces = declarations.some(
      ([property, value]) =>
        REPLACEMENTS.has(property) ||
        (property === "outline" && value !== "none" && value !== "0"),
    );
    if (!replaces) offenders.push(selector);
  }
  return offenders;
}

function walkFiles(directory: string, extensions: Set<string>, found: string[] = []): string[] {
  const skip = new Set(["node_modules", ".next", "out", "build", ".git", "coverage"]);
  for (const entry of readdirSync(directory)) {
    if (skip.has(entry)) continue;
    const absolute = path.join(directory, entry);
    if (statSync(absolute).isDirectory()) walkFiles(absolute, extensions, found);
    else if (extensions.has(path.extname(entry))) found.push(absolute);
  }
  return found;
}

describe("criterion 4 — the focus policy", () => {
  it("detects a rule that suppresses the outline and one that replaces it", () => {
    // The checker is self-tested, so the repository-wide assertion below is
    // a real gate rather than a regex that happens to find nothing.
    expect(outlineOffenders(".probe:focus { outline: none; }")).toEqual([".probe:focus"]);
    expect(
      outlineOffenders(".probe:focus { outline: none; box-shadow: 0 0 0 2px currentColor; }"),
    ).toEqual([]);
    expect(
      outlineOffenders(".probe:focus { outline: none; outline-color: currentColor; }"),
    ).toEqual([]);
  });

  it("finds no offending rule in any stylesheet under web/", () => {
    const sheets = walkFiles(WEB_ROOT, new Set([".css"]));
    expect(sheets.length).toBeGreaterThan(3);
    for (const sheet of sheets) {
      const relative = path.relative(WEB_ROOT, sheet);
      expect(outlineOffenders(readFileSync(sheet, "utf8")), relative).toEqual([]);
    }
  });

  it("finds no primitive suppressing the outline with a utility class", () => {
    const sources = walkFiles(
      path.join(WEB_ROOT, "components", "primitives"),
      new Set([".tsx", ".ts"]),
    );
    expect(sources.length).toBeGreaterThanOrEqual(11);
    for (const source of sources) {
      const relative = path.relative(WEB_ROOT, source);
      // `outline-none` is Tailwind's suppression utility; `focus:` rather
      // than `focus-visible:` is the other half of the policy.
      expect(readFileSync(source, "utf8"), relative).not.toMatch(/["' ]outline-none[ "']/);
      expect(readFileSync(source, "utf8"), relative).not.toMatch(/["' ]focus:[a-z]/);
    }
  });

  it("rings on :focus-visible and never on :focus", () => {
    expect(PRIMITIVES_CSS).toContain(".ew-focusable:focus-visible {");
    // No bare `:focus` selector anywhere in the library's stylesheet.
    const selectors = [...PRIMITIVES_CSS.matchAll(/([^{}]+)\{/g)].map((match) =>
      (match[1] ?? "").trim(),
    );
    for (const selector of selectors) {
      expect(selector, `${selector} uses :focus rather than :focus-visible`).not.toMatch(
        /:focus(?!-visible)/,
      );
    }
  });

  it("computes a 2px --focus ring at 2px offset", () => {
    injectProductSheets();
    // jsdom cannot match :focus-visible, so the AUTHOR'S declarations are
    // reattached to a selector it can match. Only the selector changes.
    inject(`.focus-probe { ${ruleBody(PRIMITIVES_CSS, ".ew-focusable:focus-visible")} }`);

    const probe = document.createElement("span");
    probe.className = "focus-probe";
    document.body.append(probe);

    expect(resolvePixels(probe, "outline-width", TOKENS)).toBe(2);
    expect(resolvePixels(probe, "outline-offset", TOKENS)).toBe(2);
    expect(resolveComputed(probe, "outline-color", TOKENS)).toBe(
      TOKENS.get("--color-focus"),
    );
    expect(getComputedStyle(probe).getPropertyValue("outline-style")).toBe("solid");

    probe.remove();
  });

  it("takes the ring's width, offset and colour from tokens rather than literals", () => {
    const ring = ruleBody(PRIMITIVES_CSS, ".ew-focusable:focus-visible");
    expect(ring).toContain("var(--size-focus-ring-width)");
    expect(ring).toContain("var(--color-focus)");
    expect(ring).toContain("var(--size-focus-ring-offset)");
    expect(TOKENS.get("--size-focus-ring-width")).toBe("2px");
    expect(TOKENS.get("--size-focus-ring-offset")).toBe("2px");
  });
});

/* =========================================================================
 * Criterion 9 — reduced motion
 * ========================================================================= */

/**
 * Everything a user could learn from the tree that is NOT motion: the text,
 * and every ARIA attribute on every element. If this is identical with the
 * animation running and with it removed, then nothing was being carried by
 * the animation.
 */
function accessibleSnapshot(root: ParentNode): string {
  const parts: string[] = [];
  for (const element of root.querySelectorAll("*")) {
    const aria = [...element.attributes]
      .filter((attribute) => attribute.name.startsWith("aria-") || attribute.name === "role")
      // React's useId counter advances across renders, so the id itself is
      // noise. What matters is that the SAME wiring exists in both trees.
      .map((attribute) => `${attribute.name}=${attribute.value.replace(/_r_[0-9a-z]+_/g, "«id»")}`)
      .sort()
      .join(",");
    parts.push(`${element.tagName}[${aria}]`);
  }
  parts.push(`text:${(root as HTMLElement).textContent ?? ""}`);
  return parts.join("\n");
}

/** Every state in the library that animates, in one tree. */
function AnimatedStates() {
  return (
    <div>
      <StatusBadge severity="live" ambient>
        Live
      </StatusBadge>
      <Disclosure label="Diagnostics" defaultOpen>
        42 frames received.
      </Disclosure>
    </div>
  );
}

describe("criterion 9 — reduced motion", () => {
  const reducedTokens = mediaBlockBody(TOKENS_CSS, "(prefers-reduced-motion: reduce)");
  const reducedPrimitives = mediaBlockBody(
    PRIMITIVES_CSS,
    "(prefers-reduced-motion: reduce)",
  );

  it("collapses every duration token to 1ms", () => {
    const collapsed = customProperties(reducedTokens);
    expect([...collapsed.keys()].sort()).toEqual([
      "--duration-ambient",
      "--duration-base",
      "--duration-fast",
      "--duration-slow",
    ]);
    for (const [name, value] of collapsed) expect(value, name).toBe("1ms");
  });

  it("times every animation off a duration token, never a literal", () => {
    const timings = [...PRIMITIVES_CSS.matchAll(/^\s*(animation|transition)\s*:\s*([^;]+);/gm)].map(
      (match) => match[2] as string,
    );
    expect(timings.length).toBeGreaterThan(0);
    for (const timing of timings) {
      if (timing.trim() === "none") continue;
      expect(timing, `"${timing}" hardcodes a duration`).not.toMatch(/\d+\s*m?s/);
      expect(timing, `"${timing}" does not use a duration token`).toContain("var(--duration-");
    }
  });

  it("has no transform entrance to drop", () => {
    // Every keyframe block in the library, checked for a transform. 03 §3.7
    // requires transform-based entrances to be removed under reduced motion;
    // the library never writes one, which is the stronger version.
    const keyframes = [...PRIMITIVES_CSS.matchAll(/@keyframes\s+[a-z-]+/g)];
    expect(keyframes.length).toBeGreaterThanOrEqual(2);
    for (const match of keyframes) {
      const body = blockBodyFrom(PRIMITIVES_CSS, match.index);
      expect(body, match[0]).not.toMatch(/transform\s*:/);
      expect(body, match[0]).toMatch(/opacity\s*:/);
    }
  });

  it("stops the two animations outright rather than running them for 1ms", () => {
    expect(reducedPrimitives).toContain(".ew-enter");
    expect(reducedPrimitives).toContain(".ew-pulse");
    expect(reducedPrimitives).toMatch(/animation\s*:\s*none/);
  });

  it("keeps the pulsing mark out of the accessibility tree and the word in it", () => {
    render(
      <StatusBadge severity="live" ambient>
        Live
      </StatusBadge>,
    );
    const badge = screen.getByText("Live");
    const pulsing = badge.querySelector(".ew-pulse");
    expect(pulsing).not.toBeNull();
    // The only animated element is the mark, and the mark is hidden from
    // assistive technology — so the animation cannot be anyone's only signal.
    expect(pulsing).toHaveAttribute("aria-hidden", "true");
    expect(badge).toHaveTextContent("Live");
  });

  it("conveys no information by motion alone", () => {
    injectProductSheets();
    const withMotion = render(<AnimatedStates />);
    const before = accessibleSnapshot(withMotion.container);
    withMotion.unmount();

    // Both bodies are complete rules already (`:root { ... }` in tokens.css,
    // `.ew-enter, .ew-pulse { ... }` here), so they apply as written.
    inject(reducedTokens);
    inject(reducedPrimitives);
    const withoutMotion = render(<AnimatedStates />);
    const after = accessibleSnapshot(withoutMotion.container);

    expect(after).toBe(before);
  });
});

/* =========================================================================
 * WO-27 criteria 6 and 7 — the marks under forced colours
 * ========================================================================= */

/**
 * THE DEFECT. 03 §3.4 ranks the channels a status is carried on — "a distinct
 * word, a distinct mark shape and a colour, in that order of precedence" —
 * and forced-colors mode is the condition that removes the third one on the
 * reader's terms. It did remove it from the words. It did not remove it from
 * the marks: Chromium's user-agent sheet sets `forced-color-adjust:
 * preserve-parent-color` on SVG content, which means "inherit the parent's
 * already-forced colour", and a `<svg>` carrying its OWN `color` — which
 * every `Mark` does, through the tone class that gives it its hue — has
 * nothing to inherit and keeps the author value.
 *
 * WO-27 measured it on this commit: in both of Chromium's forced palettes the
 * spine's marks kept `--color-signature-text` and `--color-ink-faint` while
 * every word beside them came back as `CanvasText`. A shape drawn in a hue
 * the product chose is exactly what the mode exists to prevent.
 *
 * WHY THE PROOF IS SPLIT. jsdom evaluates no `@media` block that does not
 * mention `screen` (./support/css.ts, limit 3), so `(forced-colors: active)`
 * cannot match here in either direction and a computed-style assertion would
 * be a fiction. The COMPOSITED proof is `web/e2e/motion.spec.ts`, "the spine
 * keeps its word and its shape in the {light,dark} forced palette", which
 * measures every painted `[data-mark]` against the palette the browser really
 * substituted and is red on this commit without the rule below. What is
 * provable here is the pair of facts about the source: the rule exists and
 * says `color: inherit`, and every `Mark` renders an `svg[data-mark]` for it
 * to match.
 */
describe("WO-27 criterion 6 — status marks take the reader's palette", () => {
  const FORCED = mediaBlockBody(PRIMITIVES_CSS, "(forced-colors: active)");

  it("declares `color: inherit` for the marks under forced colours", () => {
    expect(FORCED).toContain("svg[data-mark]");
    // `inherit` rather than `CanvasText`: 03 §3.4 makes the mark the
    // redundant channel BESIDE ITS WORD, so the right forced colour is
    // whatever that word ended up being — CanvasText in the spine, LinkText
    // inside a link, the button's forced colour inside a button. Inheriting
    // gets all three right and hard-codes none of them.
    expect(ruleBody(FORCED, "svg[data-mark]")).toContain("color: inherit");
    expect(
      FORCED,
      "`forced-color-adjust: none` would keep the product's own hues and " +
        "defeat the mode outright.",
    ).not.toContain("forced-color-adjust: none");
  });

  it("selects with an element+attribute pair a tone utility cannot outrank", () => {
    // `svg[data-mark]` is (0,1,1) and beats the (0,1,0) of
    // `.text-signature-text`. Written as a bare `[data-mark]` the two would
    // tie, and the winner would be whichever stylesheet Next happened to
    // inject last — which is not a property anyone should have to reason
    // about at 3am.
    expect(FORCED).toMatch(/svg\[data-mark\]/);
    expect(FORCED.replace(/svg\[data-mark\]/g, "")).not.toContain("[data-mark]");
  });

  it("renders every mark as an svg[data-mark], so the rule can match it", () => {
    render(<StatusBadge severity="live">Live</StatusBadge>);
    const mark = screen.getByText("Live").querySelector("[data-mark]");
    expect(mark).not.toBeNull();
    expect(
      mark?.tagName.toLowerCase(),
      "the forced-colours rule is written against `svg[data-mark]`; a mark " +
        "that stopped being an svg would silently lose the fix.",
    ).toBe("svg");
    // …and the mark is still aria-hidden, so nothing above changed which
    // channel is the announced one.
    expect(mark).toHaveAttribute("aria-hidden", "true");
  });
});
