/**
 * Reading real CSS in jsdom, with the three jsdom limits stated rather than
 * worked around silently.
 *
 * 1. THE `unit` PROJECT RUNS WITH `css: false`, so a component's
 *    `import "./primitives.css"` is a no-op there. These helpers read the
 *    stylesheet off disk and inject it as a `<style>` element instead, which
 *    jsdom does parse and cascade. The bytes under test are therefore the
 *    committed ones, not a Vite transformation of them.
 *
 * 2. JSDOM DOES NOT SUBSTITUTE `var()`. `getComputedStyle(el).minHeight`
 *    returns the literal string `var(--ew-target-size)`. `resolveLength`
 *    walks that chain itself — element first, then `:root`, then the token
 *    map parsed out of app/tokens.css — so the number a test asserts is the
 *    number the browser would compute, arrived at by the same lookups.
 *
 * 3. JSDOM ONLY APPLIES `@media` RULES WHOSE MEDIA LIST MENTIONS `screen`
 *    (jsdom/living/helpers/style-rules.js). `(pointer: coarse)` is therefore
 *    never evaluated, in either direction. `mediaBlockBody` extracts the
 *    author's own coarse-pointer declarations out of the file and hands them
 *    back so a test can apply them unconditionally: the rules under test are
 *    still the ones in primitives.css, never a restatement of them, and what
 *    the test simulates is the media query matching — nothing else.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

export const WEB_ROOT = path.resolve(__dirname, "..", "..", "..");

/** Read a file relative to web/. */
export function readWebFile(relative: string): string {
  return readFileSync(path.join(WEB_ROOT, relative), "utf8");
}

/** Append a `<style>` with this text and return it, so a test can remove it. */
export function installStylesheet(css: string): HTMLStyleElement {
  const style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
  return style;
}

/**
 * Drop `/* ... *\/` comments.
 *
 * Not cosmetic: these stylesheets document themselves by quoting their own
 * selectors and at-rules in prose, so a search for `@media (pointer: coarse)`
 * finds the sentence about it before it finds the block. Every structural
 * helper below reads stripped CSS for that reason.
 */
export function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/**
 * The balanced `{ ... }` body of the first block at or after `from`, with
 * the outer braces removed. Brace-counted rather than regex-matched,
 * because an at-rule's body contains nested rule braces.
 */
export function blockBodyFrom(css: string, from: number): string {
  const firstBrace = css.indexOf("{", from);
  if (firstBrace < 0) throw new Error(`No block opens at or after index ${from}`);

  let depth = 0;
  for (let index = firstBrace; index < css.length; index += 1) {
    if (css[index] === "{") depth += 1;
    else if (css[index] === "}") {
      depth -= 1;
      if (depth === 0) return css.slice(firstBrace + 1, index);
    }
  }
  throw new Error(`Unbalanced braces after index ${from}`);
}

/** The body of the first `@media <condition>` block. */
export function mediaBlockBody(css: string, condition: string): string {
  const opener = `@media ${condition}`;
  const start = css.indexOf(opener);
  if (start < 0) throw new Error(`No "${opener}" block in the stylesheet`);
  return blockBodyFrom(css, start);
}

/**
 * The declaration block of a rule, by exact selector text.
 *
 * jsdom cannot match `:focus-visible` — nwsapi rejects it and jsdom's
 * cascade helper skips selectors it cannot match — so a test that wants the
 * COMPUTED focus ring has to reattach the author's declarations to a
 * selector jsdom can match. This returns those declarations verbatim, so
 * only the selector is substituted and never the values.
 */
export function ruleBody(css: string, selector: string): string {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`No "${selector}" rule in the stylesheet`);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  if (close < 0) throw new Error(`Unterminated "${selector}" rule`);
  return css.slice(open + 1, close);
}

/** Every `--name: value` declared anywhere in a stylesheet's `:root` blocks. */
export function customProperties(css: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const match of css.matchAll(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/gim)) {
    const name = match[1];
    const value = match[2];
    if (name && value && !map.has(name)) map.set(name, value.trim());
  }
  return map;
}

const VAR_ONLY = /^var\(\s*(--[a-z0-9-]+)\s*(?:,[^)]*)?\)$/i;

/**
 * A computed property with its `var()` chain resolved. Returns the final
 * literal, e.g. `"32px"`.
 */
export function resolveComputed(
  element: Element,
  property: string,
  tokens: Map<string, string>,
): string {
  let value = getComputedStyle(element).getPropertyValue(property).trim();

  for (let hop = 0; hop < 10; hop += 1) {
    const name = VAR_ONLY.exec(value)?.[1];
    if (!name) return value;

    const fromElement = getComputedStyle(element).getPropertyValue(name).trim();
    const fromRoot = getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim();
    const next = fromElement || fromRoot || tokens.get(name) || "";
    if (!next) throw new Error(`${name} resolves to nothing`);
    value = next;
  }

  throw new Error(`${property} did not resolve in ten hops (circular var?)`);
}

/** `resolveComputed`, parsed as a pixel count. */
export function resolvePixels(
  element: Element,
  property: string,
  tokens: Map<string, string>,
): number {
  const value = resolveComputed(element, property, tokens);
  const pixels = Number.parseFloat(value);
  if (!value.endsWith("px") || Number.isNaN(pixels)) {
    throw new Error(`${property} resolved to "${value}", which is not a px length`);
  }
  return pixels;
}
