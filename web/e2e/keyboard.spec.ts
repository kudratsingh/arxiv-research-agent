import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import {
  clearFocusMark,
  describeFocus,
  focusIsOnMark,
  markFocused,
  waitForRailMode,
  walkTabOrder,
  writeArtifact,
} from "./support/a11y";
import type { FocusStop } from "./support/a11y";
import { FIXTURES } from "./support/env";
import { REPORT_READER } from "./support/states";

/**
 * WO-27 criterion 2 — the keyboard walk.
 *
 * "`keyboard.md` walks skip link, rail, drawer, composer, plan arrays,
 * approve/revise/cancel, diagnostics disclosure, report headings/links/
 * tables, export, deletion dialog, and error recovery — each with observed
 * focus order **and** restoration."
 *
 * WHAT METHOD THIS IS, STATED BEFORE ANY RESULT. Every stop below is produced
 * by a **synthesised key event** — `page.keyboard.press("Tab")` — driving the
 * real product in a real Chromium, and read back from
 * `document.activeElement` plus Playwright's ARIA snapshot. That is a
 * legitimate keyboard measurement: the browser's own sequential focus
 * navigation algorithm decides where focus goes, not this file, and reading
 * where it landed is an observation.
 *
 * WHAT IT IS NOT. It is not a person. Three things it therefore cannot
 * establish, and `manual/keyboard.md` says so in the same words:
 *
 *   1. **Comprehensibility.** Whether the observed order makes sense to
 *      someone who cannot see the layout is a judgement. The order is
 *      recorded; the judgement is prose, marked as prose.
 *   2. **Visibility of the ring in practice.** `outlineOn` records that an
 *      indicator is painted and where. Whether it is *noticeable* against the
 *      surface behind it at a real screen size is not in this file.
 *   3. **Anything a screen reader does.** That is `manual/screen-reader.md`,
 *      which is a protocol awaiting a human operator and does not pretend
 *      otherwise.
 *
 * WHY THE ARTIFACT IS WRITTEN EVEN ON A PASS. `manual/keyboard.md` is
 * transcribed from these files. A walk that only wrote its output on failure
 * would leave the evidence pack quoting numbers nobody can reproduce.
 */

const POPULATED = `/c/${FIXTURES.populatedConversation}`;
const DESKTOP = { width: 1440, height: 900 } as const;
const PHONE = { width: 412, height: 915 } as const;

/** One row per stop, in the shape `keyboard.md`'s tables are built from. */
function table(title: string, stops: readonly FocusStop[]): string {
  const rows = stops.map((stop) =>
    [
      stop.index,
      stop.role,
      stop.name,
      stop.tag,
      stop.hook ?? "",
      stop.inMain ? "main" : stop.inRail ? "rail" : stop.inDialog ? "dialog" : "chrome",
      stop.outline,
      stop.outlineOn,
    ].join("\t"),
  );
  return [
    `# ${title}`,
    "stop\trole\taccessible name\ttag\thook\tregion\tfocus ring\tring on",
    ...rows,
  ].join("\n");
}

/** Assert every stop paints an indicator somewhere. 03 §7.2's other half. */
function expectEveryStopRinged(stops: readonly FocusStop[], where: string): void {
  const unringed = stops.filter(
    (stop) => stop.role !== "(document)" && stop.outlineOn === "none",
  );
  expect(
    unringed.map((stop) => `${stop.index}: ${stop.role} "${stop.name}" (${stop.hook})`),
    `${where}: these focus stops paint no outline on themselves, their next ` +
      "sibling or their parent. 03 §7.2: `outline: none` is never written " +
      "without an equivalent replacement in the same rule.",
  ).toEqual([]);
}

// ====================================================================== 1 + 2

test.describe("criterion 2 — skip link, header, rail, composer", () => {
  test(
    "the tab order is skip link → header → rail → main → composer",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await waitForRailMode(page, "expanded");
      await page.locator("[data-thread-row-link]").first().waitFor();

      // Stop at the point the walk leaves the document. Tabbing past the last
      // control moves focus to the browser's own chrome — reported here as
      // `(document)` — and the next press re-enters at the skip link. Those
      // stops are a real observation (the document HAS an end, which is what
      // makes the order a sequence rather than a loop) but they are not
      // product stops, and counting them as header stops is how the first
      // draft of this test reported a phantom finding.
      const walked = await walkTabOrder(page, 12);
      const end = walked.findIndex((stop) => stop.role === "(document)");
      const stops = end === -1 ? walked : walked.slice(0, end);
      writeArtifact(
        info.outputDir,
        "keyboard/landing-desktop.tsv",
        `${table("Landing · 1440", stops)}\n# document end after stop ${
          end === -1 ? "(not reached in 12 presses)" : String(end)
        }`,
      );

      // The sequence 03 §7.2 states, asserted as a sequence rather than as a
      // set: "skip link → header → thread rail → main → composer".
      const first = stops[0];
      expect(first?.role).toBe("link");
      expect(first?.name).toBe("Skip to content");

      const railStops = stops.filter((stop) => stop.inRail);
      const mainStops = stops.filter((stop) => stop.inMain);
      expect(railStops.length, "the rail contributes no focus stops").toBeGreaterThan(0);
      expect(mainStops.length, "main contributes no focus stops").toBeGreaterThan(0);

      const lastRail = Math.max(...railStops.map((stop) => stop.index));
      const firstMain = Math.min(...mainStops.map((stop) => stop.index));
      expect(
        lastRail,
        "a rail stop comes after a main stop, so the order is not " +
          "rail → main. Observed:\n" + table("order", stops),
      ).toBeLessThan(firstMain);

      // The header sits between the skip link and the rail. `ThemeToggle` is
      // its only focusable, and it is a radio group, so exactly one of the
      // three options is in the tab order (the platform's roving focus, which
      // is the whole reason it is three native radios).
      const header = stops.filter((stop) => !stop.inRail && !stop.inMain && stop.index > 1);
      expect(
        header.map((stop) => `${stop.role} "${stop.name}"`),
        "the header should contribute exactly the theme control",
      ).toEqual(["radio \"System\""]);

      // …and the composer is the last thing in main.
      const composer = stops.filter((stop) => stop.hook?.includes("landing") === true);
      expect(composer.map((stop) => stop.name)).toEqual([
        "Research question",
        "Generate plan",
      ]);

      expectEveryStopRinged(stops, "landing at 1440");
    },
  );

  test("the order is reversible with Shift+Tab", { tag: "@a11y" }, async ({ page }, info) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await waitForRailMode(page, "expanded");
    await page.locator("[data-thread-row-link]").first().waitFor();

    const forwards = await walkTabOrder(page, 8);
    const backwards = await walkTabOrder(page, 7, { backwards: true });
    writeArtifact(
      info.outputDir,
      "keyboard/landing-reverse.tsv",
      `${table("forwards", forwards)}\n\n${table("backwards", backwards)}`,
    );

    // Shift+Tab from stop 8 must retrace 7 → 1. A sequence that is not
    // reversible is a different defect from one in the wrong order, which is
    // why it is asserted separately rather than assumed.
    expect(
      backwards.map((stop) => `${stop.role} "${stop.name}"`),
      "Shift+Tab does not retrace the forward order.",
    ).toEqual(
      forwards
        .slice(0, 7)
        .reverse()
        .map((stop) => `${stop.role} "${stop.name}"`),
    );
  });

  test(
    "the skip link moves focus into main and nothing before it",
    { tag: "@a11y" },
    async ({ page }) => {
      await page.setViewportSize(DESKTOP);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await waitForRailMode(page, "expanded");

      await page.keyboard.press("Tab");
      const skip = await describeFocus(page, 1);
      expect(skip.name).toBe("Skip to content");
      // Reversing the clip on focus is the whole mechanism: a skip link that
      // stays clipped is reachable and invisible, which is the failure mode
      // SC 2.4.1 is usually implemented into rather than out of.
      await expect(page.locator("a.ew-skip-link")).toBeInViewport();

      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(/#main$/);
      const after = await walkTabOrder(page, 1);
      expect(
        after[0]?.inMain,
        "after following the skip link, the next Tab must land inside " +
          `<main>, not back in the rail. Landed on ${after[0]?.role} ` +
          `"${after[0]?.name}".`,
      ).toBe(true);
    },
  );
});

// ========================================================================== 3

test.describe("criterion 2 — the mobile drawer traps and restores", () => {
  test("open, trap, Escape, restore", { tag: "@a11y" }, async ({ page }, info) => {
    await page.setViewportSize(PHONE);
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await waitForRailMode(page, "drawer");

    const before = await walkTabOrder(page, 6);
    writeArtifact(info.outputDir, "keyboard/drawer-closed.tsv", table("Landing · 412 · closed", before));

    // Below md the rail is not in the layout at all, so the only route to it
    // is the labelled header button — and it must be reachable by keyboard.
    const trigger = before.find((stop) => stop.hook === "data-drawer-trigger");
    expect(
      trigger,
      "no focus stop carries `data-drawer-trigger` at 412px. 04 §8.3 removes " +
        "the rail from the layout below `md`, so a drawer trigger that is not " +
        `in the tab order makes the rail unreachable. Observed:\n${table("closed", before)}`,
    ).toBeDefined();

    await page.locator("[data-drawer-trigger]").first().focus();
    await markFocused(page, "data-wo27-opener");
    await page.keyboard.press("Enter");

    const dialog = page.getByRole("dialog", { name: "Threads" });
    await expect(dialog).toBeVisible();
    // Wait for the rail's rows, not just for the dialog. Below `md` the shell
    // does not mount `ThreadRailBridge` until the drawer is asked for, so the
    // first frame of the open drawer holds a skeleton — and a walk taken then
    // records a two-stop trap and calls it the evidence. The trap is real
    // either way; the TABLE would be wrong.
    await expect(dialog.locator("[data-thread-row-link]").first()).toBeVisible();
    const landed = await describeFocus(page, 0);
    expect(
      landed.inDialog,
      `opening the drawer left focus outside it (${landed.role} "${landed.name}").`,
    ).toBe(true);

    const inside = await walkTabOrder(page, 12);
    writeArtifact(info.outputDir, "keyboard/drawer-open.tsv", table("Drawer · 412 · open", inside));
    expect(
      inside.filter((stop) => !stop.inDialog).map((stop) => `${stop.role} "${stop.name}"`),
      "Tab escaped the drawer. It is one of the two surfaces 03 §7.2 allows " +
        "to trap focus, and a trap with a hole is not a trap.",
    ).toEqual([]);
    // Twelve presses over a six-stop dialog must wrap, not stall.
    expect(new Set(inside.map((stop) => stop.name)).size).toBeGreaterThan(1);
    expectEveryStopRinged(inside, "drawer at 412");

    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Threads" })).toBeHidden();
    expect(
      await focusIsOnMark(page, "data-wo27-opener"),
      "closing the drawer did not restore focus to the control that opened " +
        `it; focus is on ${JSON.stringify(await describeFocus(page, 0))}.`,
    ).toBe(true);
    await clearFocusMark(page, "data-wo27-opener");
  });
});

// ==================================================================== 5, 6

test.describe("criterion 2 — the plan editor's arrays and decisions", () => {
  async function openPlan(page: Page): Promise<void> {
    await page.setViewportSize(DESKTOP);
    await page.goto(`${POPULATED}?job=${FIXTURES.planReview}`, {
      waitUntil: "domcontentloaded",
    });
    await page.getByRole("button", { name: "Remove sub-question 1" }).waitFor();
  }

  test(
    "the array reaches every row, add and remove by keyboard alone",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await openPlan(page);
      await page.getByRole("textbox", { name: "Sub-question 1" }).focus();
      const stops = await walkTabOrder(page, 16);
      writeArtifact(info.outputDir, "keyboard/plan-editor.tsv", table("Plan editor · 1440", stops));

      const names = stops.map((stop) => stop.name);
      // Every remove control keeps the stable, indexed name 03 §7.2 requires
      // — "Remove sub-question 2", not "Remove" three times.
      expect(names).toContain("Remove sub-question 1");
      expect(names).toContain("Add sub-question");
      expect(names).toContain("Approve plan");
      expect(names).toContain("Cancel this run");
      expectEveryStopRinged(stops, "plan editor");

      // The decision controls are reachable in the order the surface reads:
      // approve, then cancel, and cancel is last because it is destructive.
      const approve = names.indexOf("Approve plan");
      const cancel = names.indexOf("Cancel this run");
      expect(approve).toBeGreaterThanOrEqual(0);
      expect(cancel).toBeGreaterThan(approve);
    },
  );

  test(
    "removing a row moves focus to the next row, and to Add when the list empties",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await openPlan(page);
      const trail: string[] = ["action\tfocus after"];

      // Driven from the KEYBOARD, not by clicking. `:focus-visible` follows
      // the interaction modality, so a mouse-driven removal moves focus
      // correctly and paints no ring — and an evidence table built that way
      // would report a phantom "no focus ring" finding on a control that has
      // one. The whole claim here is about keyboard use, so the walk uses
      // keys throughout.
      await page.getByRole("button", { name: "Remove sub-question 2" }).focus();
      await page.keyboard.press("Enter");
      const afterMiddle = await describeFocus(page, 0);
      trail.push(`remove sub-question 2\t${afterMiddle.role} "${afterMiddle.name}" [${afterMiddle.outlineOn}]`);
      expect(
        afterMiddle.name,
        "removing a middle row must move focus to the row that took its " +
          "place (03 §7.2), not to the document.",
      ).toBe("Sub-question 2");

      await page.getByRole("button", { name: "Remove sub-question 2" }).focus();
      await page.keyboard.press("Enter");
      const afterLast = await describeFocus(page, 0);
      trail.push(`remove the new last row\t${afterLast.role} "${afterLast.name}" [${afterLast.outlineOn}]`);
      expect(
        afterLast.name,
        "removing the last row must clamp focus to the row before it.",
      ).toBe("Sub-question 1");

      await page.getByRole("button", { name: "Remove sub-question 1" }).focus();
      await page.keyboard.press("Enter");
      const afterEmpty = await describeFocus(page, 0);
      trail.push(`remove the only row\t${afterEmpty.role} "${afterEmpty.name}" [${afterEmpty.outlineOn}]`);
      expect(
        afterEmpty.name,
        "emptying the list must move focus to the add control (03 §7.2), " +
          "because there is no row left to hold it.",
      ).toBe("Add sub-question");
      expect(
        afterEmpty.outlineOn,
        "focus reached `Add sub-question` from a keyboard activation, so the " +
          "focus-visible ring has to be painted. `outlineOn: none` here means " +
          "either the ring is missing or the modality was lost.",
      ).not.toBe("none");

      writeArtifact(info.outputDir, "keyboard/plan-removal.tsv", trail.join("\n"));
    },
  );
});

// =================================================================== 7, 8, 9

test.describe("criterion 2 — diagnostics, the report and export", () => {
  test(
    "the diagnostics disclosure opens from the keyboard and keeps focus on its trigger",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto(`${POPULATED}?job=${FIXTURES.running}`, {
        waitUntil: "domcontentloaded",
      });
      const trigger = page.getByRole("button", { name: "Technical events" });
      await trigger.waitFor();

      // Collapsed by default is not a nicety: 03 §7.3 allows two live regions
      // product-wide, and the diagnostics `role="log"` is a third that is
      // tolerated *only* because a collapsed disclosure keeps it out of the
      // accessibility tree.
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      await expect(page.getByRole("log", { name: "Received frames" })).toBeHidden();

      await trigger.focus();
      await page.keyboard.press("Enter");
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
      const held = await describeFocus(page, 0);
      expect(
        held.name,
        "opening a disclosure must leave focus on the trigger — the panel is " +
          "the next tab stop, not a focus steal.",
      ).toBe("Technical events");

      const stops = await walkTabOrder(page, 4);
      writeArtifact(info.outputDir, "keyboard/diagnostics.tsv", table("Diagnostics · 1440", stops));
      // The scrollable table is a focus stop on purpose: a region a keyboard
      // user cannot scroll is a region they cannot read (SC 2.1.1).
      expect(stops.map((stop) => stop.name)).toContain("Diagnostics table");
      expect(stops.map((stop) => stop.name)).toContain("Copy diagnostics");
      expectEveryStopRinged(stops, "diagnostics");

      await page.keyboard.press("Escape");
      // Escape is not a disclosure gesture; the panel stays open, which is
      // the APG behaviour and is recorded so the evidence does not imply one.
      await expect(trigger).toHaveAttribute("aria-expanded", "true");
    },
  );

  test(
    "the report's headings, links and tables are all reachable",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto(POPULATED, { waitUntil: "domcontentloaded" });
      await page.locator(REPORT_READER).first().waitFor();

      // The section rail is derived from the briefing's own h2/h3 nodes
      // (03 §5), so it is the keyboard route to a heading.
      const rail = page.getByRole("navigation", { name: "Sections" });
      await expect(rail).toBeVisible();
      const anchors = await rail.getByRole("link").all();
      expect(anchors.length, "the briefing rendered no section anchors").toBeGreaterThan(0);

      const first = anchors[0];
      if (first === undefined) throw new Error("no section anchor");
      const href = await first.getAttribute("href");
      await first.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(new RegExp(`${(href ?? "#").replace("#", "\\#")}$`));

      // Every markdown table is wrapped in a focusable scroll region, which
      // is what makes a table wider than the reading column readable without
      // a pointer.
      const tables = page.getByRole("region", { name: /Table \d+ in this briefing/ });
      await expect(tables.first()).toBeVisible();
      await tables.first().focus();
      const onTable = await describeFocus(page, 0);
      expect(onTable.role).toBe("region");
      expect(onTable.name).toMatch(/^Table \d+ in this briefing$/);

      const stops = await walkTabOrder(page, 10);
      writeArtifact(info.outputDir, "keyboard/report.tsv", table("Report reader · 1440", stops));
      expectEveryStopRinged(stops, "report reader");
    },
  );

  test(
    "export opens, cycles, and Escape returns focus to its trigger",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto(POPULATED, { waitUntil: "domcontentloaded" });
      await page.locator(REPORT_READER).first().waitFor();

      const trigger = page.getByRole("button", { name: "Export" }).first();
      await trigger.focus();
      await markFocused(page, "data-wo27-export-trigger");
      await page.keyboard.press("Enter");
      await expect(trigger).toHaveAttribute("aria-expanded", "true");

      const inside = await walkTabOrder(page, 3);
      writeArtifact(info.outputDir, "keyboard/export.tsv", table("Export · 1440", inside));
      expect(inside.map((stop) => stop.name)).toEqual(["Markdown", "PDF", "Word"]);
      expectEveryStopRinged(inside, "export panel");

      await page.keyboard.press("Escape");
      await expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(
        await focusIsOnMark(page, "data-wo27-export-trigger"),
        "Escape inside the export panel must return focus to the Export " +
          `button; focus is on ${JSON.stringify(await describeFocus(page, 0))}.`,
      ).toBe(true);

      // The arrow keys are an ADDITION to Tab, not a replacement for it: they
      // open the panel and move inside it, and the panel is still tabbable.
      await page.keyboard.press("ArrowDown");
      const viaArrow = await describeFocus(page, 0);
      expect(viaArrow.name).toBe("Markdown");
      await page.keyboard.press("Escape");
      expect(await focusIsOnMark(page, "data-wo27-export-trigger")).toBe(true);
      await clearFocusMark(page, "data-wo27-export-trigger");
    },
  );
});

// ======================================================================== 10

test.describe("criterion 2 — the deletion dialog", () => {
  test(
    "reached by keyboard, opens on Cancel, and restores focus to the row menu",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await waitForRailMode(page, "expanded");
      const menu = page.locator("[data-thread-row-menu]").first();
      await menu.waitFor();

      await menu.focus();
      await markFocused(page, "data-wo27-menu-trigger");
      await page.keyboard.press("Enter");
      // Wait for the menu to exist before reading focus. Radix portals it and
      // moves focus in a layout effect, so a read taken in the same tick as
      // the keypress is a race — and one that fails intermittently is worse
      // than one that fails always.
      await expect(page.getByRole("menu")).toBeVisible();
      const inMenu = await describeFocus(page, 0);
      expect(
        inMenu.role,
        "Enter on the row's overflow trigger must open the menu and move " +
          "focus into it (the roving focus RC-09 kept the Menu primitive for).",
      ).toBe("menuitem");
      expect(inMenu.name).toBe("Open thread");

      await page.keyboard.press("ArrowDown");
      await expect(page.getByRole("menuitem", { name: "Delete thread" })).toBeFocused();
      const second = await describeFocus(page, 0);
      expect(second.name).toBe("Delete thread");
      await page.keyboard.press("Enter");

      const dialog = page.getByRole("dialog", { name: /^Delete/ });
      await expect(dialog).toBeVisible();
      // Same reason as above: `initialFocusRef` lands in an effect, so the
      // read waits for the element rather than for a tick.
      await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
      const landed = await describeFocus(page, 0);
      // Initial focus is deliberately Cancel, not the destructive control:
      // Enter on an accidental open must do nothing.
      expect(
        landed.name,
        "the delete dialog must open with focus on Cancel, so that a stray " +
          "Enter cannot delete a thread.",
      ).toBe("Cancel");
      expect(landed.inDialog).toBe(true);

      const inside = await walkTabOrder(page, 8);
      writeArtifact(info.outputDir, "keyboard/delete-dialog.tsv", table("Delete dialog", inside));
      expect(
        inside.filter((stop) => !stop.inDialog).map((stop) => stop.name),
        "Tab escaped the delete dialog. It is the other surface 03 §7.2 " +
          "allows to trap focus.",
      ).toEqual([]);
      expectEveryStopRinged(inside, "delete dialog");

      await page.keyboard.press("Escape");
      await expect(dialog).toBeHidden();
      expect(
        await focusIsOnMark(page, "data-wo27-menu-trigger"),
        "closing the delete dialog must restore focus to the row's overflow " +
          `menu; focus is on ${JSON.stringify(await describeFocus(page, 0))}.`,
      ).toBe(true);
      await clearFocusMark(page, "data-wo27-menu-trigger");
    },
  );
});

// ======================================================================== 11

test.describe("criterion 2 — error recovery", () => {
  for (const [name, path, ready] of [
    ["route not found", "/baseline-no-such-route", '[data-recovery-surface="not-found"]'],
    [
      "thread not found",
      `/c/${FIXTURES.missingConversation}`,
      "text=This thread is not available",
    ],
  ] as const) {
    test(`${name}: the recovery action is reachable and ringed`, { tag: "@a11y" }, async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto(path, { waitUntil: "domcontentloaded" });
      await page.locator(ready).first().waitFor();

      const stops = await walkTabOrder(page, 12);
      writeArtifact(
        info.outputDir,
        `keyboard/recovery-${name.replace(/\s+/g, "-")}.tsv`,
        table(`${name} · 1440`, stops),
      );

      const recovery = stops.filter((stop) => stop.inMain);
      expect(
        recovery.length,
        `${name} offers no focusable recovery inside <main>. A recovery ` +
          "surface a keyboard user cannot act on is a dead end.",
      ).toBeGreaterThan(0);
      expectEveryStopRinged(stops, name);

      // …and the shell is still there, so the rail is still a way out.
      expect(stops.some((stop) => stop.inRail)).toBe(true);
    });
  }

  test(
    "the rail's own error offers a Retry that is reachable by keyboard",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.route(
        (url) => url.pathname === "/api/conversations",
        async (route) => {
          await route.fulfill({
            status: 502,
            contentType: "application/json",
            body: JSON.stringify({ detail: "synthetic local upstream failure" }),
          });
        },
      );
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await page.locator('[data-thread-rail-state="error"]').waitFor();

      const stops = await walkTabOrder(page, 8);
      writeArtifact(info.outputDir, "keyboard/recovery-rail-error.tsv", table("Rail error · 1440", stops));
      expect(stops.map((stop) => stop.name)).toContain("Retry");
      expectEveryStopRinged(stops, "rail error");
    },
  );
});
