import type { Page } from "@playwright/test";

/**
 * The two measurements 04 §8.3 asks for, plus the CSSOM read that makes the
 * safe-area claim checkable on a real device profile.
 *
 * Everything here runs inside the page and returns plain data, so a failure
 * message can quote numbers rather than a locator.
 */

export interface ReflowSample {
  /** `document.scrollingElement.scrollWidth`. */
  scrollWidth: number;
  /** `document.scrollingElement.clientWidth`. */
  clientWidth: number;
  /** The widest element that overflows the viewport, if any. Diagnostic. */
  widestOverflow: { selector: string; width: number } | null;
}

/**
 * 04 §8.3's assertion, verbatim: "`document.scrollingElement.scrollWidth <=
 * document.scrollingElement.clientWidth`".
 *
 * The `widestOverflow` half is not part of the assertion — it exists so that
 * when this DOES go red, the failure names the element instead of leaving a
 * reader to bisect a stylesheet.
 */
export async function measureReflow(page: Page): Promise<ReflowSample> {
  return page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    const clientWidth = root.clientWidth;

    let widest: { selector: string; width: number } | null = null;
    for (const element of Array.from(document.body.querySelectorAll("*"))) {
      const rect = element.getBoundingClientRect();
      const right = rect.right;
      if (right <= clientWidth + 1) continue;
      if (widest !== null && right <= widest.width) continue;
      const id = element.id ? `#${element.id}` : "";
      const cls =
        typeof element.className === "string" && element.className.length > 0
          ? `.${element.className.trim().split(/\s+/).slice(0, 3).join(".")}`
          : "";
      widest = {
        selector: `${element.tagName.toLowerCase()}${id}${cls}`,
        width: Math.round(right),
      };
    }

    return { scrollWidth: root.scrollWidth, clientWidth, widestOverflow: widest };
  });
}

export interface WorkSurfaceSample {
  /** Rendered width of the column the route's content occupies, in CSS px. */
  width: number;
  /** Which candidate matched. Named in the evidence so it is not a mystery. */
  matched: string;
}

/**
 * The width of the work surface — WO-08 criterion 4's number, and the
 * assertion that genuinely goes red→green where the reflow sweep does not.
 *
 * WHY A CANDIDATE CHAIN AND NOT ONE SELECTOR. This same function has to
 * measure two different shells: WO-08's (`.ew-shell__surface` inside
 * `[data-workbench-shell]`) and the pre-shell one at `1f3f45a`, whose content
 * column is the unnamed `<div class="flex-1 overflow-hidden">` at
 * `ConversationsShell.tsx:27` and which has no `<main>` at all — that missing
 * landmark is the defect WO-08 fixed. Without the chain the "before" run
 * cannot be taken, and criterion 5's red half would be an assertion nobody
 * could reproduce.
 */
export async function measureWorkSurface(page: Page): Promise<WorkSurfaceSample> {
  return page.evaluate(() => {
    const candidates: readonly string[] = [
      // WO-08's shell.
      "[data-workbench-shell] .ew-shell__surface",
      "[data-workbench-shell] main#main",
      // Any shell that at least has the landmark.
      "main",
      // Pre-WO-08: ConversationsShell.tsx:27.
      "div.flex.h-screen > div.flex-1",
    ];
    for (const selector of candidates) {
      const element = document.querySelector(selector);
      if (element === null) continue;
      return {
        width: Math.round(element.getBoundingClientRect().width),
        matched: selector,
      };
    }
    return { width: 0, matched: "none" };
  });
}

export interface SafeAreaSample {
  /** How many live CSS rules declare a bottom inset from `env()`. */
  insetDeclarations: number;
  /** Whether the media condition carrying them matches at this viewport. */
  mediaMatchesHere: boolean;
  /** The media condition text, for the evidence table. */
  mediaCondition: string | null;
  /** Computed `position` of the reserved composer slot. */
  composerPosition: string;
  /** Computed `bottom` of the reserved composer slot. */
  composerBottom: string;
}

/**
 * WO-08 criterion 7's device half, which WO-08 explicitly deferred here:
 * "The device-level proof is WO-21's `iPhone 15` project."
 *
 * WHAT CAN AND CANNOT BE PROVEN IN A BROWSER. `env(safe-area-inset-bottom)`
 * resolves to `0px` under Playwright's device emulation — Playwright emulates
 * a viewport and a user agent, not a display cutout — so asserting a non-zero
 * computed padding would assert a thing no headless run can produce, and any
 * number it did produce would be fiction.
 *
 * What IS device-specific and therefore worth asserting here: that the media
 * query the inset lives in actually **matches at this device's width**, that
 * the declaration exists exactly once in the live CSSOM (so it cannot double
 * when WO-20 fills the composer slot — WO-08's own worry), and that the slot
 * is genuinely `position: sticky; bottom: 0` on the device rather than only
 * in the stylesheet source. WO-08's `layout.test.ts` asserts the source; this
 * asserts the render.
 */
export async function measureSafeArea(page: Page): Promise<SafeAreaSample> {
  return page.evaluate(() => {
    let insetDeclarations = 0;
    let mediaCondition: string | null = null;
    let mediaMatchesHere = false;

    const visit = (rules: CSSRuleList): void => {
      for (const rule of Array.from(rules)) {
        if (rule instanceof CSSMediaRule) {
          const condition = rule.conditionText;
          for (const inner of Array.from(rule.cssRules)) {
            if (
              inner instanceof CSSStyleRule &&
              /padding-bottom:\s*env\(\s*safe-area-inset-bottom/.test(inner.cssText)
            ) {
              insetDeclarations += 1;
              mediaCondition = condition;
              mediaMatchesHere = window.matchMedia(condition).matches;
            }
          }
          visit(rule.cssRules);
        }
      }
    };

    for (const sheet of Array.from(document.styleSheets)) {
      try {
        visit(sheet.cssRules);
      } catch {
        // Cross-origin sheet; the app has none, but never throw from a probe.
      }
    }

    const slot = document.getElementById("workbench-composer");
    const style = slot === null ? null : window.getComputedStyle(slot);
    return {
      insetDeclarations,
      mediaMatchesHere,
      mediaCondition,
      composerPosition: style?.position ?? "missing",
      composerBottom: style?.bottom ?? "missing",
    };
  });
}

export interface FirstPaintSample {
  /** `data-theme` on `<html>` as of the first animation frame. */
  theme: string | null;
  /** `data-theme-preference` on `<html>` as of the first animation frame. */
  preference: string | null;
  /** Relative luminance of the painted background, 0 (black) to 1 (white). */
  luminance: number;
}

/**
 * WO-01's deferred no-flash proof, which `web/app/layout.tsx:38` names:
 * "WO-21 asserts the absence of the flash in Playwright".
 *
 * HOW IT AVOIDS BEING A TAUTOLOGY. Reading `data-theme` after `load` proves
 * nothing — the toggle could have written it from an effect, which *is* the
 * flash. This probe is installed with `addInitScript`, so it runs before any
 * page script including the inline theme script, and it samples inside the
 * FIRST `requestAnimationFrame` callback — the frame immediately before the
 * browser's first paint. If the theme were applied by React instead of by the
 * synchronous `<head>` script, the sample would be light.
 *
 * WHY LUMINANCE AND NOT A COLOUR STRING. `web/tests/tokens.test.ts` walks all
 * of `web/` and fails on any literal colour outside `app/tokens.css`, so a
 * hard-coded expected value could not be written here even if it were a good
 * idea — and it would not be, because it would pin this assertion to one
 * revision of the palette. Luminance is a property of "dark", not of a hex.
 */
export async function installFirstPaintProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const sample = (): void => {
      const root = document.documentElement;
      const target = document.body ?? root;
      const painted = window.getComputedStyle(target).backgroundColor;
      // Parse whatever channel triple the engine returns without naming a
      // colour function in this source file (see the doc comment above).
      const channels = (painted.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
      const linear = channels.map((value) => {
        const v = value / 255;
        return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      });
      const [r = 1, g = 1, b = 1] = linear;
      (window as unknown as Record<string, unknown>).__wo21FirstPaint = {
        theme: root.getAttribute("data-theme"),
        preference: root.getAttribute("data-theme-preference"),
        luminance: 0.2126 * r + 0.7152 * g + 0.0722 * b,
      };
    };
    requestAnimationFrame(sample);
  });
}

/** Read what `installFirstPaintProbe` recorded. */
export async function readFirstPaint(page: Page): Promise<FirstPaintSample | null> {
  return page.evaluate(
    () =>
      ((window as unknown as Record<string, unknown>).__wo21FirstPaint as
        | FirstPaintSample
        | undefined) ?? null,
  );
}
