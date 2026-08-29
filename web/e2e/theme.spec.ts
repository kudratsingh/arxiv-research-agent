import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { installFirstPaintProbe, readFirstPaint } from "./support/measure";

/**
 * WO-01's deferred proof, discharged here.
 *
 * `web/app/layout.tsx:38` names this work order by number: "the localStorage
 * key has exactly one definition; **WO-21 asserts the absence of the flash in
 * Playwright**". `web/lib/tokens.ts:249` says the same and specifies the
 * method: "by loading with the key pre-seeded to 'dark' and sampling the
 * painted background colour". That is what happens below.
 *
 * WHY THIS CANNOT BE A UNIT TEST, AND WHY WO-01 AND WO-08 BOTH DEFERRED IT.
 * The flash is a *paint*. jsdom does not paint, does not run
 * `requestAnimationFrame` against a compositor, and does not resolve a
 * stylesheet cascade to a background colour — so the property "the dark theme
 * was already applied when the first frame was composed" has no meaning
 * outside a browser. WO-08's own unit tests assert the input to this
 * (`ThemeToggle` writes the key in a form the init script accepts, and
 * deliberately does NOT apply the theme from an effect, because a control that
 * did would *be* the flash). This asserts the output.
 *
 * HOW THE SAMPLE AVOIDS BEING A TAUTOLOGY. `installFirstPaintProbe` is an
 * init script, so it runs before every page script including the inline
 * `<head>` one, and it samples inside the FIRST `requestAnimationFrame`
 * callback — the frame immediately before the browser's first paint. If the
 * theme were applied by React after hydration, that sample would be light and
 * these tests would go red.
 *
 * The threshold is relative luminance rather than a colour value, for two
 * reasons: `web/tests/tokens.test.ts` fails the build on any literal colour
 * outside `app/tokens.css`, and pinning a hex here would tie a
 * flash-detection test to one revision of the palette. "Dark" is a property
 * of the luminance, not of the hex.
 */

const THEME_STORAGE_KEY = "arxiv-agent.theme";

/** Seed the persisted preference before ANY page script has run. */
async function seedPreference(page: Page, value: string): Promise<void> {
  await page.addInitScript(
    ([key, preference]) => {
      try {
        window.localStorage.setItem(key as string, preference as string);
      } catch {
        // Matches the init script's own posture: a storage-blocked context
        // must never throw before first paint.
      }
    },
    [THEME_STORAGE_KEY, value] as const,
  );
}

/** Comfortably below mid-grey / above it. Not a palette value. */
const DARK_CEILING = 0.2;
const LIGHT_FLOOR = 0.5;

test.describe("WO-01 deferred proof — no theme flash before first paint", () => {
  test(
    "a stored dark preference is already painted on the first frame",
    { tag: "@theme" },
    async ({ page }) => {
      await seedPreference(page, "dark");
      await installFirstPaintProbe(page);

      await page.goto("/", { waitUntil: "domcontentloaded" });
      const firstPaint = await readFirstPaint(page);

      expect(firstPaint, "the first-paint probe did not run").not.toBeNull();
      expect(
        firstPaint?.theme,
        "`data-theme` must be on <html> before the first frame — that is what " +
          "the synchronous inline script in app/layout.tsx exists for",
      ).toBe("dark");
      expect(firstPaint?.preference).toBe("dark");
      expect(
        firstPaint?.luminance ?? 1,
        `the background painted on the first frame had luminance ` +
          `${firstPaint?.luminance}; anything above ${DARK_CEILING} means the ` +
          "light theme was painted first and the user saw a flash",
      ).toBeLessThan(DARK_CEILING);
    },
  );

  /**
   * 🔴 A DEFECT THIS WORK ORDER FOUND, PINNED SO IT CANNOT BE FORGOTTEN.
   *
   * `test.fail()` — this assertion is **expected to fail on this commit**, so
   * the suite is green while the bug exists and goes RED the moment somebody
   * fixes it. Whoever fixes it deletes the `test.fail()` line and the test
   * becomes an ordinary guard. That is deliberate: a bug found by the browser
   * tier and then quietly not asserted is a bug the browser tier did not find.
   *
   * WHAT HAPPENS. With `arxiv-agent.theme` stored as `"dark"`, `<html>` is
   * correctly `data-theme="dark"` before first paint (asserted above) and
   * then flips to `light` a few hundred milliseconds later, while
   * `data-theme-preference` stays `"dark"`. The user picked dark, sees dark,
   * and then watches the page turn light. Measured on the seeded stack:
   *
   *     stored=dark  early={theme:dark, preference:dark}
   *                  late ={theme:light, preference:dark, stored:dark}
   *
   * WHY. `ThemeToggle.tsx:135` reads the preference through
   * `useSyncExternalStore(subscribe, readThemePreference,
   * serverThemePreference)`, and `serverThemePreference()` returns `"system"`
   * (`:99`) — correctly, because a server render cannot know the choice. React
   * uses that server snapshot for the HYDRATION render, so the effect at
   * `:143-158` runs once with `preference === "system"`, passes its
   * `if (preference !== "system") return` guard, and calls
   * `apply()` → `setAttribute("data-theme", resolve("system"))` → `light`.
   * When the client snapshot (`"dark"`) then arrives, the effect re-runs,
   * returns early at the same guard — and never restores what the first pass
   * overwrote.
   *
   * The pre-paint script is not at fault and neither is the storage key. The
   * fix belongs with the control: the effect must not write `data-theme` on
   * the hydration pass, or must re-resolve from the *current* preference
   * rather than only bailing out. WO-01 owns the theme foundation and WO-08
   * owns `ThemeToggle`; this work order deliberately does not edit either.
   */
  test(
    "a stored dark preference survives hydration",
    { tag: "@theme" },
    async ({ page }) => {
      test.fail(
        true,
        "Known defect: ThemeToggle's hydration-pass effect overwrites " +
          "data-theme with the OS resolution. See the comment above this test.",
      );

      await seedPreference(page, "dark");
      await page.goto("/", { waitUntil: "domcontentloaded" });

      // Long enough for hydration and the effect that follows it.
      await page.waitForTimeout(2_000);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await expect(page.locator("html")).toHaveAttribute(
        "data-theme-preference",
        "dark",
      );
    },
  );

  test(
    "a stored light preference wins over a dark OS setting, from the first frame",
    { tag: "@theme" },
    async ({ page }) => {
      // The OS says dark. The stored explicit choice says light and must win,
      // before paint — the case where a naive `prefers-color-scheme`-only
      // implementation flashes the wrong way round.
      await page.emulateMedia({ colorScheme: "dark" });
      await seedPreference(page, "light");
      await installFirstPaintProbe(page);

      await page.goto("/", { waitUntil: "domcontentloaded" });
      const firstPaint = await readFirstPaint(page);

      expect(firstPaint?.theme).toBe("light");
      expect(firstPaint?.preference).toBe("light");
      expect(firstPaint?.luminance ?? 0).toBeGreaterThan(LIGHT_FLOOR);
    },
  );

  test(
    "with no stored preference the OS decides, also before first paint",
    { tag: "@theme" },
    async ({ page }) => {
      await page.emulateMedia({ colorScheme: "dark" });
      await installFirstPaintProbe(page);

      await page.goto("/", { waitUntil: "domcontentloaded" });
      const firstPaint = await readFirstPaint(page);

      expect(
        firstPaint?.preference,
        "an absent or unrecognised stored value resolves to `system`, never to " +
          "a hard-coded theme (lib/tokens.ts:262)",
      ).toBe("system");
      expect(firstPaint?.theme).toBe("dark");
      expect(firstPaint?.luminance ?? 1).toBeLessThan(DARK_CEILING);
    },
  );

  test(
    "the theme control is reachable and writes exactly one key",
    { tag: "@theme" },
    async ({ page }) => {
      await page.goto("/", { waitUntil: "domcontentloaded" });

      const toggle = page.locator("[data-theme-toggle]");
      await expect(toggle).toBeVisible();

      // The radio inputs carry `VISUALLY_HIDDEN_CLASS`, so `check()` cannot
      // reach them — the visible control is the label. Clicking the label is
      // also what a user does, and it is what proves the label is actually
      // associated with its input rather than merely sitting next to it.
      await toggle.getByText("Dark", { exact: true }).click();
      await expect(toggle.getByRole("radio", { name: "Dark" })).toBeChecked();

      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

      const storage = await page.evaluate(() => ({
        length: window.localStorage.length,
        theme: window.localStorage.getItem("arxiv-agent.theme"),
      }));
      expect(storage.theme).toBe("dark");
      expect(
        storage.length,
        "the theme control must persist its preference and nothing else — " +
          "one key, one meaning",
      ).toBe(1);
    },
  );
});
