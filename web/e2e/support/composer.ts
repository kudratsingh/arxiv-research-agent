import { expect } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

/**
 * Fill the landing composer, safely with respect to hydration.
 *
 * WHY THIS IS NOT `await box.fill(text)`.
 *
 * `/` is prerendered, so the textarea and the submit button are in the server
 * markup and `toBeVisible()` passes long before React has attached anything to
 * them. `QueryForm`'s textarea is a CONTROLLED input — its `value` comes from
 * `useState` and the state only moves when `onChange` fires. Fill it before
 * hydration and the DOM value is set, no handler runs, React's `query` stays
 * `""`, and the next render puts the empty string back. The submit button,
 * whose `disabled` is `busy || !query.trim()`, then stays disabled **forever**,
 * and the test fails 15 seconds later with "element is not enabled" — a
 * failure that looks like a product defect and is not one.
 *
 * That is not a hypothetical: it is what the first five-project run did, on
 * chromium and on webkit, once four workers were competing for one container
 * and hydration slipped past the fill.
 *
 * `expect(...).toPass()` retries the whole fill-and-check block, so the first
 * attempt that lands after hydration is the one that sticks. The alternative —
 * waiting on some hydration sentinel — would need the app to publish one, and
 * WO-08's hooks are all present in the server markup too.
 */
export async function fillComposer(
  page: Page,
  text: string,
): Promise<{ box: Locator; submit: Locator }> {
  const box = page.getByRole("textbox", { name: "Research question" });
  const submit = page.getByRole("button", { name: "Run research" });

  await expect(box).toBeVisible();
  await expect(async () => {
    // A pre-hydration attempt leaves `text` in the DOM without updating
    // React's controlled state. Filling that same value again after hydration
    // is not guaranteed to dispatch a fresh input event, so every retry could
    // otherwise repeat the stale state forever. Clear first to make each
    // attempt an observable state transition for the hydrated component.
    await box.fill("");
    await box.fill(text);
    // Enabled is the observable that proves React saw the change: `disabled`
    // is derived from the controlled value.
    await expect(submit).toBeEnabled({ timeout: 2_000 });
    // 45 s, and it costs nothing when things are healthy: a hydrated page
    // passes on the first attempt in milliseconds. The budget exists because
    // the full five-project run also compiles a `next dev` server for the
    // StrictMode scenario while four workers drive one container, and on a
    // machine that loaded, hydration has been measured past 20 s.
  }).toPass({ timeout: 45_000 });

  return { box, submit };
}
