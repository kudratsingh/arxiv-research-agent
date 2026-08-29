import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Locator, Page } from "@playwright/test";

import type { AxeResults } from "./axe";

/**
 * WO-27 — the shared mechanism behind the Gate 4 accessibility pack.
 *
 * WO-22 built the axe gate (`support/axe.ts`) and was explicit about what it
 * could not establish: "Keyboard order, focus restoration, announcement
 * quality and screen-reader comprehension. Automation cannot establish any of
 * them." That sentence is still true of a *screen reader*, and
 * `evidence/gate-4/manual/screen-reader.md` says so at length. It is not true
 * of the other three in the same way, and this module is the line between
 * them:
 *
 *   * **Keyboard order and focus restoration are observable.** Where focus
 *     lands after a synthesised `Tab` is a property of the document, not of
 *     the person pressing the key, and reading it back is a measurement. What
 *     a scripted walk cannot tell you is whether the resulting order is
 *     *comprehensible* — that judgement is in `keyboard.md` as prose, marked
 *     as prose.
 *   * **Announcement CONTENT is observable; announcement DELIVERY is not.**
 *     This module can prove that the one `role="status"` region's text
 *     changed twice over a stream that delivered fifty frames. Whether a
 *     screen reader spoke those two changes, and whether a listener
 *     understood them, is `screen-reader.md`'s question and stays there.
 *
 * Everything below therefore returns DATA, and the spec files assert on it.
 * Nothing here decides what a pass looks like.
 */

/* =========================================================================
 * The matrix
 * ========================================================================= */

/**
 * WO-27 criterion 1's three widths.
 *
 * 320 is SC 1.4.10's reflow width and the narrowest phone `04 §8.3` audits;
 * 412 is the audit width WO-08's mobile repair is measured at and the width
 * the retained baseline screenshots were taken at; 1440 is the window the
 * twelve retained baseline axe reports were taken in
 * (`baseline/README.md`).
 */
export const A11Y_WIDTHS = [320, 412, 1440] as const;
export type A11yWidth = (typeof A11Y_WIDTHS)[number];

/**
 * The two widths **this** sweep navigates, and why the third is missing.
 *
 * WO-22's `axe.spec.ts` already audits every state in both themes at 1440 —
 * that is its `AUDIT_VIEWPORT`, pinned there so its reports stay diffable
 * against the baseline. Re-navigating the same 44 pages at the same width in
 * this file would add 44 navigations and 44 full-document axe runs to every
 * CI run and produce a second copy of reports that already exist.
 *
 * So the sweep below covers 320 and 412, one `npm run e2e` produces all three
 * widths, and `evidence/gate-4/axe/README.md` names which spec wrote which
 * leg. The matrix is complete; it is assembled from two specs rather than
 * duplicated across them.
 */
export const AXE_SWEEP_WIDTHS = [320, 412] as const;

/** Viewport heights, by width. Conventional device heights for each class. */
export const A11Y_HEIGHTS: Record<A11yWidth, number> = {
  320: 568,
  412: 915,
  1440: 900,
};

/** `--layout-breakpoint-md`, below which the rail is not in the layout. */
export const RAIL_ABSENT_BELOW = 768;

/* =========================================================================
 * Focus observation
 * ========================================================================= */

/**
 * One observed focus stop.
 *
 * `role` and `name` come from Playwright's ARIA snapshot, which runs the
 * real accessible-name computation rather than a heuristic over
 * `aria-label`/`textContent`. That distinction matters for the evidence: a
 * walk that derived the name from the DOM would be measuring this file's
 * guess at the algorithm, and a name it got wrong would look like a product
 * defect.
 */
export interface FocusStop {
  /** 1-based position in the walk. */
  index: number;
  /** Lowercased tag name, for the cases where the role is generic. */
  tag: string;
  /** ARIA role, as Playwright's snapshot reports it. */
  role: string;
  /** Accessible name, as Playwright's snapshot reports it. `""` if none. */
  name: string;
  /**
   * The first `data-*` hook on the element or its nearest ancestor that has
   * one, so a stop can be pointed at in the source. Diagnostic only.
   */
  hook: string | null;
  /** Is the stop inside `<main>`? The tab-order claim in 03 §7.2 needs it. */
  inMain: boolean;
  /** Is the stop inside the shell's `nav[aria-label]` rail? */
  inRail: boolean;
  /** Is the stop inside an open dialog? Focus-trap evidence. */
  inDialog: boolean;
  /**
   * The focus indicator, read from the composited style while focused.
   *
   * 03 §7.2 forbids `outline: none` without an equivalent replacement in the
   * same rule, so a stop with no visible indicator is a finding rather than a
   * footnote — but "on the focused element" is the wrong place to look for
   * one control in this product. `ThemeToggle` is three native
   * `<input type="radio">` clipped out of the layout with the ring painted on
   * the adjacent `<span>` (`ThemeToggle.css`), which is the standard way to
   * keep the platform's arrow-key semantics; reading only `activeElement`
   * reports the user-agent's `auto 1px` there and calls a correct control a
   * defect. So the sibling and the parent are checked too, and `outlineOn`
   * records which one paid.
   */
  outline: string;
  /** Where the indicator was found: the element, its next sibling, or a parent. */
  outlineOn: "self" | "sibling" | "parent" | "none";
}

/** No element is focused (focus is on `<body>` or the document). */
export const NO_FOCUS: Omit<FocusStop, "index"> = {
  tag: "body",
  role: "(document)",
  name: "",
  hook: null,
  inMain: false,
  inRail: false,
  inDialog: false,
  outline: "none",
  outlineOn: "none",
};

interface FocusDom {
  tag: string;
  hook: string | null;
  inMain: boolean;
  inRail: boolean;
  inDialog: boolean;
  outline: string;
  outlineOn: "self" | "sibling" | "parent" | "none";
}

/** Everything about the focused element that has to be read in the page. */
async function readFocusDom(page: Page): Promise<FocusDom | null> {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (element === null || element === document.body || element === document.documentElement) {
      return null;
    }

    let hook: string | null = null;
    for (let node: Element | null = element; node !== null; node = node.parentElement) {
      const attribute = Array.from(node.attributes).find(
        (candidate) => candidate.name.startsWith("data-") && candidate.name !== "data-testid",
      );
      if (attribute !== undefined) {
        hook = attribute.value === "" ? attribute.name : `${attribute.name}="${attribute.value}"`;
        break;
      }
    }

    // A ring is a ring wherever it is painted, as long as it is painted for
    // THIS element's focus.
    //
    // `outline-style: auto` is the user agent's own default ring, not the
    // product's, so it does not end the search. That distinction is
    // load-bearing exactly once: `ThemeToggle`'s clipped radio inputs carry
    // the UA's `auto 1px` while the product's `2px @ 2px` is painted on the
    // adjacent `<span>` (`ThemeToggle.css`). Stopping at the first non-`none`
    // outline reported that control as an off-policy 1px ring, which is a
    // finding about this function rather than about the product.
    const ringOf = (node: Element | null): string | null => {
      if (node === null) return null;
      const style = window.getComputedStyle(node);
      const width = Number.parseFloat(style.outlineWidth);
      if (style.outlineStyle === "none" || Number.isNaN(width) || width === 0) return null;
      return `${style.outlineStyle} ${style.outlineWidth} @ ${style.outlineOffset}`;
    };
    const authored = (ring: string | null): boolean =>
      ring !== null && !ring.startsWith("auto ");

    const self = ringOf(element);
    const sibling = ringOf(element.nextElementSibling);
    const parent = ringOf(element.parentElement);

    // Prefer an authored ring wherever it is; fall back to the user agent's
    // only when the product painted none at all.
    const found: [FocusDomOutlineOn, string | null][] = [
      ["self", authored(self) ? self : null],
      ["sibling", authored(sibling) ? sibling : null],
      ["parent", authored(parent) ? parent : null],
      ["self", self],
      ["sibling", sibling],
      ["parent", parent],
    ];
    const hit = found.find(([, ring]) => ring !== null);
    const outline = hit?.[1] ?? "none";
    const outlineOn: FocusDomOutlineOn = hit === undefined ? "none" : hit[0];

    return {
      tag: element.tagName.toLowerCase(),
      hook,
      inMain: element.closest("main") !== null,
      // `#workbench-rail` rather than `[data-workbench-shell] nav`: the
      // report's own section rail is a `nav` inside the shell too, and
      // counting its links as rail stops would put half the reading column
      // in the wrong column of the evidence table.
      inRail: element.closest("#workbench-rail") !== null,
      inDialog: element.closest('[role="dialog"]') !== null,
      outline,
      outlineOn,
    };
  });
}

/** Named so the in-page closure above can annotate its own return. */
type FocusDomOutlineOn = FocusDom["outlineOn"];

/**
 * `- button "Threads" [expanded]` → `{ role: "button", name: "Threads" }`.
 *
 * The leading quote strip is not defensive padding: an ARIA snapshot wraps a
 * whole entry in single quotes when the accessible name contains a colon, and
 * the rail's overflow menus are named `Thread actions: <title>`. Without it
 * every one of those stops reads back as `(unknown)` — which is what the
 * first run of this walk reported, and it was the parser's fault, not the
 * product's.
 */
function parseAriaLine(snapshot: string): { role: string; name: string } {
  const first = (snapshot.split("\n", 1)[0] ?? "").replace(/^\s*-\s+'?/, "- ");
  const match = /^-\s+([a-zA-Z]+)(?:\s+"([^"]*)")?/.exec(first);
  return { role: match?.[1] ?? "(unknown)", name: match?.[2] ?? "" };
}

/**
 * Describe wherever focus currently is.
 *
 * Never throws on "nothing is focused": a walk that runs off the end of the
 * document is a real observation and the evidence has to be able to record
 * it rather than fail the run.
 */
export async function describeFocus(page: Page, index: number): Promise<FocusStop> {
  const dom = await readFocusDom(page);
  if (dom === null) return { index, ...NO_FOCUS };

  let aria = "";
  try {
    aria = await page.locator(":focus").first().ariaSnapshot({ timeout: 2_000 });
  } catch {
    // An element that is focusable but not in the accessibility tree (or one
    // that moved between the two reads) has no snapshot. Recorded as such
    // rather than guessed at.
  }
  const { role, name } = parseAriaLine(aria);
  return { index, role, name, ...dom };
}

/**
 * Press `Tab` `count` times and describe where focus lands each time.
 *
 * `Shift+Tab` when `backwards`, because 03 §7.2's order claim is a claim
 * about a sequence and a sequence that is not reversible is a different
 * defect from one that is in the wrong order.
 */
export async function walkTabOrder(
  page: Page,
  count: number,
  { backwards = false }: { backwards?: boolean } = {},
): Promise<FocusStop[]> {
  const stops: FocusStop[] = [];
  for (let index = 1; index <= count; index += 1) {
    await page.keyboard.press(backwards ? "Shift+Tab" : "Tab");
    stops.push(await describeFocus(page, index));
  }
  return stops;
}

/**
 * Walk forwards until a stop matches, or give up.
 *
 * Returns every stop it passed through, so a walk that misses its target
 * still produces the evidence a reader needs to see why.
 */
export async function tabUntil(
  page: Page,
  matches: (stop: FocusStop) => boolean,
  { limit = 40 }: { limit?: number } = {},
): Promise<{ stops: FocusStop[]; found: FocusStop | null }> {
  const stops: FocusStop[] = [];
  for (let index = 1; index <= limit; index += 1) {
    await page.keyboard.press("Tab");
    const stop = await describeFocus(page, index);
    stops.push(stop);
    if (matches(stop)) return { stops, found: stop };
  }
  return { stops, found: null };
}

/**
 * A stable identity for "the element focus was on", for restoration checks.
 *
 * Compares by a marker attribute rather than by an element handle: a handle
 * survives a re-render that replaces the node, and a restoration that landed
 * on a *different* node with the same handle is exactly the bug this is
 * looking for. The attribute is removed again so it cannot leak into an axe
 * run or a snapshot.
 */
export async function markFocused(page: Page, marker: string): Promise<boolean> {
  return page.evaluate((name) => {
    const element = document.activeElement;
    if (element === null || element === document.body) return false;
    element.setAttribute(name, "");
    return true;
  }, marker);
}

/** Is focus back on the element `markFocused` marked? */
export async function focusIsOnMark(page: Page, marker: string): Promise<boolean> {
  return page.evaluate((name) => {
    const element = document.activeElement;
    return element !== null && element.hasAttribute(name);
  }, marker);
}

export async function clearFocusMark(page: Page, marker: string): Promise<void> {
  await page.evaluate((name) => {
    document.querySelectorAll(`[${name}]`).forEach((node) => node.removeAttribute(name));
  }, marker);
}

/* =========================================================================
 * Live regions
 * ========================================================================= */

/**
 * A record of what the two sanctioned live regions said, and when.
 *
 * 03 §7.3 allows exactly two product-wide — one `role="status"` and one
 * `role="alert"` — plus the diagnostics `role="log"`, which is tolerated
 * only because the disclosure holding it is collapsed by default. Criterion
 * 5's second half is that live regions "do not announce every frame", and
 * the only way to know that is to count *changes to the region's text*
 * against *frames delivered*.
 */
export interface LiveRegionSample {
  /** `status`, `alert` or `log`. */
  role: string;
  /** The text at the moment of the sample. */
  text: string;
  /** `performance.now()` when the mutation was seen. */
  at: number;
}

/**
 * Install a MutationObserver over every live region and record each change.
 *
 * Installed before navigation via `addInitScript`, so a region that appears
 * mid-stream is observed from its first paint rather than from whenever the
 * test remembered to look.
 */
export async function recordLiveRegions(page: Page): Promise<void> {
  await page.addInitScript(() => {
    interface Sample {
      role: string;
      text: string;
      at: number;
    }
    const samples: Sample[] = [];
    const last = new Map<Element, string>();
    (window as unknown as { __wo27LiveRegions: Sample[] }).__wo27LiveRegions = samples;

    const SELECTOR = '[role="status"], [role="alert"], [role="log"], [aria-live]';

    const sample = (element: Element): void => {
      const text = (element.textContent ?? "").replace(/\s+/g, " ").trim();
      if (last.get(element) === text) return;
      last.set(element, text);
      samples.push({
        role: element.getAttribute("role") ?? `aria-live=${element.getAttribute("aria-live")}`,
        text,
        at: performance.now(),
      });
    };

    const observer = new MutationObserver((records) => {
      for (const record of records) {
        const target =
          record.target.nodeType === Node.ELEMENT_NODE
            ? (record.target as Element)
            : record.target.parentElement;
        const region = target?.closest(SELECTOR) ?? null;
        if (region !== null) sample(region);
        // A region that was just ADDED is a change too, and its own
        // mutations never fired because it did not exist yet.
        for (const node of Array.from(record.addedNodes)) {
          if (node.nodeType !== Node.ELEMENT_NODE) continue;
          const element = node as Element;
          if (element.matches(SELECTOR)) sample(element);
          element.querySelectorAll(SELECTOR).forEach(sample);
        }
      }
    });

    const start = (): void => {
      document.querySelectorAll(SELECTOR).forEach(sample);
      observer.observe(document.documentElement, {
        subtree: true,
        childList: true,
        characterData: true,
        attributes: true,
        attributeFilter: ["role", "aria-live"],
      });
    };

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", start, { once: true });
    } else {
      start();
    }
  });
}

/** Read back what `recordLiveRegions` collected. */
export async function readLiveRegions(page: Page): Promise<LiveRegionSample[]> {
  return page.evaluate(() => {
    const samples = (window as unknown as { __wo27LiveRegions?: LiveRegionSample[] })
      .__wo27LiveRegions;
    return samples === undefined ? [] : [...samples];
  });
}

/* =========================================================================
 * Motion
 * ========================================================================= */

/** The four duration tokens `03 §3.7` collapses under reduced motion. */
export const DURATION_TOKENS = [
  "--duration-fast",
  "--duration-base",
  "--duration-slow",
  "--duration-ambient",
] as const;

/** Read the duration tokens off `:root` as the cascade resolved them. */
export async function readDurations(page: Page): Promise<Record<string, string>> {
  return page.evaluate((names) => {
    const style = window.getComputedStyle(document.documentElement);
    const out: Record<string, string> = {};
    for (const name of names) out[name] = style.getPropertyValue(name).trim();
    return out;
  }, DURATION_TOKENS as unknown as string[]);
}

/** Every element that is animating or transitioning, right now. */
export interface MovingElement {
  selector: string;
  animationName: string;
  animationDuration: string;
  transitionProperty: string;
  transitionDuration: string;
}

/**
 * Find everything with a non-zero animation or transition duration.
 *
 * Criterion 5's first half is that no status meaning is motion-only; its
 * enforcement half is that under `prefers-reduced-motion: reduce` nothing is
 * still moving. "Still moving" has to be read off the composited style
 * rather than off the source, because `var(--duration-fast)` in a stylesheet
 * tells you nothing about what the media query did to it.
 */
export async function findMoving(page: Page): Promise<MovingElement[]> {
  return page.evaluate(() => {
    const positive = (value: string): boolean =>
      value
        .split(",")
        .map((part) => part.trim())
        .some((part) => {
          const seconds = part.endsWith("ms")
            ? Number.parseFloat(part) / 1000
            : Number.parseFloat(part);
          // 1ms IS the reduced-motion policy's value (03 §3.7), so the
          // threshold sits just above it rather than at zero.
          return !Number.isNaN(seconds) && seconds > 0.0015;
        });

    const describe = (element: Element): string => {
      const id = element.id === "" ? "" : `#${element.id}`;
      const cls =
        typeof element.className === "string" && element.className.trim() !== ""
          ? `.${element.className.trim().split(/\s+/).slice(0, 2).join(".")}`
          : "";
      return `${element.tagName.toLowerCase()}${id}${cls}`;
    };

    const out: MovingElement[] = [];
    for (const element of Array.from(document.querySelectorAll("*"))) {
      const style = window.getComputedStyle(element);
      const animating = style.animationName !== "none" && positive(style.animationDuration);
      const transitioning =
        style.transitionProperty !== "none" &&
        style.transitionProperty !== "" &&
        positive(style.transitionDuration);
      if (!animating && !transitioning) continue;
      out.push({
        selector: describe(element),
        animationName: style.animationName,
        animationDuration: style.animationDuration,
        transitionProperty: style.transitionProperty,
        transitionDuration: style.transitionDuration,
      });
    }
    return out;
  });
}

/* =========================================================================
 * Status channels — 03 §3.4's word / mark / colour precedence
 * ========================================================================= */

/**
 * One status indicator, split into the three channels §3.4 names.
 *
 * The point of reading all three is that criteria 5 and 6 are the same
 * question asked twice: remove motion (reduced motion) or remove colour
 * (forced colours) and the *word* and the *mark* have to still be there.
 * A channel that is present in one condition and absent in the other is the
 * finding.
 */
export interface StatusChannels {
  /** `data-segment` — the checkpoint name (`Question`, `Plan`, …). */
  id: string;
  /** `data-status` — the spine state this segment resolved to. */
  status: string;
  /**
   * Everything the segment renders as text: the visible name, the clipped
   * `"Question · observed"` line a reader hears, and the visible status
   * word. §3.4's *word* channel is a pass when the status word is in here.
   *
   * Read as one string rather than picked apart by selector because the
   * visible word span carries no hook — and adding one to the product so a
   * test could find it would be the test writing the component.
   */
  text: string;
  /** The `data-mark` shape, or null when no mark is rendered. */
  mark: string | null;
  /** The composited colour of the mark. */
  colour: string;
  /** Is the mark's SVG actually painted (non-zero box)? */
  markPainted: boolean;
}

/**
 * Read the status channels off the trace spine's segments.
 *
 * Scoped to the spine because that is what criterion 6 names — "a
 * forced-colors pass on the trace spine and status marks" — and because the
 * spine is the one surface that renders several statuses at once, which is
 * what makes "the shapes are distinct" an observable claim rather than a
 * per-page one.
 */
export async function readSpineChannels(page: Page): Promise<StatusChannels[]> {
  return page.evaluate(() => {
    const out: StatusChannels[] = [];
    for (const segment of Array.from(document.querySelectorAll("[data-segment]"))) {
      const mark = segment.querySelector("[data-mark]");
      const box = mark?.getBoundingClientRect();
      out.push({
        id: segment.getAttribute("data-segment") ?? "(unnamed)",
        status: segment.getAttribute("data-status") ?? "(none)",
        text: (segment.textContent ?? "").replace(/\s+/g, " ").trim(),
        mark: mark?.getAttribute("data-mark") ?? null,
        colour: mark === null ? "" : window.getComputedStyle(mark).color,
        markPainted: box !== undefined && box.width > 0 && box.height > 0,
      });
    }
    return out;
  });
}

/**
 * The dashed/dotted void's border, which is the one place in the spine where
 * a *break in observation* is drawn rather than written.
 *
 * `spine.css` makes a stale observation dotted and a current one dashed, and
 * says so in as many words: "a break is a shape". Forced colours replaces
 * `border-color` and leaves `border-style` alone, so the distinction has to
 * survive — and this is what proves it did.
 */
export async function readSpineVoid(
  page: Page,
): Promise<{ current: string; style: string; colour: string; width: string } | null> {
  return page.evaluate(() => {
    const element = document.querySelector('[data-spine-part="void"]');
    if (element === null) return null;
    const style = window.getComputedStyle(element);
    return {
      current: element.getAttribute("data-current") ?? "(unset)",
      style: style.borderTopStyle,
      colour: style.borderTopColor,
      width: style.borderTopWidth,
    };
  });
}

/** Every `[data-mark]` on the page, with the colour it is painted in. */
export async function readMarks(
  page: Page,
): Promise<{ mark: string; colour: string; width: number; height: number }[]> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("[data-mark]")).map((element) => {
      const box = element.getBoundingClientRect();
      return {
        mark: element.getAttribute("data-mark") ?? "(none)",
        colour: window.getComputedStyle(element).color,
        width: box.width,
        height: box.height,
      };
    }),
  );
}

/* =========================================================================
 * Evidence artifacts
 * ========================================================================= */

/**
 * Where WO-27's artifacts go, derived from Playwright's `outputDir` for the
 * same reason `support/axe.ts` derives its own that way: `outputDir` is
 * already absolute and already honours `E2E_ARTIFACT_DIR`, whereas
 * `process.cwd()` depends on where the operator typed `npm run e2e`.
 */
export function a11yDirFrom(outputDir: string, sub = ""): string {
  return join(outputDir, "..", "..", "a11y", sub);
}

/** Write one artifact, creating its directory. Returns the absolute path. */
export function writeArtifact(
  outputDir: string,
  relative: string,
  contents: string,
): string {
  const file = join(a11yDirFrom(outputDir), relative);
  mkdirSync(join(file, ".."), { recursive: true });
  writeFileSync(file, contents.endsWith("\n") ? contents : `${contents}\n`, "utf8");
  return file;
}

/**
 * An axe report trimmed to what the Gate 4 pack can afford to retain.
 *
 * WHY IT IS TRIMMED AND WHAT IS LOST. The Gate 3 pack retained 44 untrimmed
 * reports at ~280 kB each — 12 MB — because `resultTypes` is left at its
 * default and `passes` therefore carries every node axe checked. This matrix
 * is three times as large, and 36 MB of mostly-`passes` in a docs directory
 * is not evidence anybody can read or diff.
 *
 * So the retained report keeps the engine, the tag set, the URL, the counts
 * and **every violation and incomplete result in full**, and drops the
 * `passes` array. What that costs is the ability to re-derive a contrast
 * measurement for a node that PASSED, which is WO-22 criterion 4's
 * instrument, not this one's — and WO-22's untrimmed 1440 reports still
 * carry it. The untrimmed reports for this sweep exist in the CI artifact
 * (`web/build/e2e/axe/`); they are not committed.
 */
export interface RetainedAxeReport {
  state: string;
  theme: string;
  width: number;
  url: string;
  timestamp: string;
  testEngine: AxeResults["testEngine"];
  toolOptions: AxeResults["toolOptions"];
  counts: {
    violations: number;
    passes: number;
    incomplete: number;
    inapplicable: number;
  };
  violations: AxeResults["violations"];
  incomplete: AxeResults["incomplete"];
}

export function retainAxe(
  results: AxeResults,
  meta: { state: string; theme: string; width: number },
): RetainedAxeReport {
  return {
    ...meta,
    url: results.url,
    timestamp: results.timestamp,
    testEngine: results.testEngine,
    toolOptions: results.toolOptions,
    counts: {
      violations: results.violations.length,
      passes: results.passes.length,
      incomplete: results.incomplete.length,
      inapplicable: results.inapplicable.length,
    },
    violations: results.violations,
    incomplete: results.incomplete,
  };
}

/* =========================================================================
 * Navigation helpers
 * ========================================================================= */

/**
 * Open the thread drawer, which below `md` is the only way to the rail.
 *
 * Not a workaround: 04 §8.3 repair step 1 removes the rail from the layout
 * below 768px and `WorkbenchShell` does not even mount `ThreadRailBridge`
 * until the drawer has been asked for, so at 320 and 412 the rail states do
 * not exist until the header's disclosure button is pressed. `reflow.spec.ts`
 * does the same thing for the same reason.
 */
export async function openRailDrawer(page: Page): Promise<Locator> {
  const trigger = page.locator("[data-drawer-trigger]").first();
  await trigger.click();
  return trigger;
}

/**
 * Wait until the shell has decided which rail mode the viewport is in.
 *
 * `WorkbenchShell` renders `expanded` on the server and corrects it during
 * hydration through `useSyncExternalStore`, so a tab walk that starts on the
 * first paint at 412px measures a document in which the drawer trigger does
 * not exist yet. That is a real intermediate state, but it is not the one
 * criterion 2 is about, and a walk that hit it recorded a tab order missing
 * its second stop — which looked exactly like a product defect and was not.
 */
export async function waitForRailMode(page: Page, mode: "drawer" | "compact" | "expanded") {
  await page.locator(`[data-workbench-shell][data-rail-mode="${mode}"]`).waitFor();
}

/**
 * Serve a run's stream as `count` checkpoint frames, delivered fast.
 *
 * Criterion 5's second half — "live regions do not announce every frame" —
 * is a ratio, and a ratio needs a denominator. The seeded `baseline-running`
 * row is a genuine leased row with a genuine open stream, but nothing is
 * driving it, so it delivers no checkpoints at all and the region trivially
 * says one thing forever. This delivers a known number of real
 * `node_completed` frames (`lib/api/events.ts`'s `NodeCompletedPayload`,
 * `{ node, state_delta }`) so the count of live-region text changes can be
 * measured against them.
 *
 * The frames are real in shape and synthetic in origin, which is the same
 * trade `support/intercept.ts` documents for `stream_timeout`: a real stack
 * emits these only by running a job, and running a job is the one thing this
 * suite may never do.
 */
export async function checkpointStream(page: Page, jobId: string, count: number): Promise<void> {
  const frames = Array.from(
    { length: count },
    (_, index) =>
      `event: node_completed\ndata: ${JSON.stringify({
        node: `checkpoint_${index + 1}`,
        state_delta: { papers_read: index + 1 },
      })}\n\n`,
  ).join("");

  await page.route(
    (url) => url.pathname === `/api/research/${jobId}/stream`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        headers: { "cache-control": "no-cache", connection: "keep-alive", "x-accel-buffering": "no" },
        // No terminal frame: the run is still going, which is the state the
        // spine's status line is supposed to narrate once and not repeat.
        body: `${frames}: synthetic checkpoint burst\n\n`,
      });
    },
  );
}
