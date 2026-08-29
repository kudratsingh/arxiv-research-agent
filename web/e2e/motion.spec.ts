import { expect, test } from "@playwright/test";

import {
  checkpointStream,
  findMoving,
  readDurations,
  readLiveRegions,
  readMarks,
  readSpineChannels,
  readSpineVoid,
  recordLiveRegions,
  writeArtifact,
} from "./support/a11y";
import { FIXTURES } from "./support/env";

/**
 * WO-27 criteria 5 and 6 — reduced motion, and forced colours.
 *
 * They are one file because they are one question asked twice. `03 §3.4`
 * ranks the three channels a status is carried on — "a distinct word, a
 * distinct mark shape and a colour, in that order of precedence" — and each
 * criterion removes one of them and asks whether the information survived:
 *
 *   * **Criterion 5** removes motion. `03 §3.7`: "Because no state in the
 *     product is conveyed by motion alone, removing motion removes no
 *     information — that is the test the policy has to pass, not a promise."
 *   * **Criterion 6** removes colour. Forced-colors mode replaces the
 *     author's palette with the reader's, so anything that was only a hue is
 *     gone; the word and the shape have to still be there (RC-17).
 *
 * A NOTE ON WHAT `emulateMedia({ forcedColors: "active" })` DOES. It is not
 * only a media-query flip — the first test below proves that, on a synthetic
 * element, before any product assertion runs. That check is load-bearing: if
 * the emulation only matched the query and did not force colours, every
 * assertion after it would be a green tick over an unforced page, which is
 * exactly the sort of vacuous pass this pack exists not to produce.
 */

const POPULATED = `/c/${FIXTURES.populatedConversation}`;
const RUNNING = `${POPULATED}?job=${FIXTURES.running}`;
const DESKTOP = { width: 1440, height: 900 } as const;

/* ========================================================== criterion 5 */

test.describe("criterion 5 — the reduced-motion policy", () => {
  test(
    "the four duration tokens collapse to 1ms and nothing is left moving",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);

      // Half one: the durations the product ships with motion allowed. Taken
      // first, so "collapsed to 1ms" is a measured change rather than a
      // measurement of a page that never moved.
      await page.goto(RUNNING, { waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();
      // The diagnostics disclosure holds the only transform transition on the
      // route, so it is opened deliberately: a sweep that only looked at the
      // resting page would report "nothing moves" and mean "nothing was
      // mounted".
      await page.getByRole("button", { name: "Technical events" }).click();
      const fullDurations = await readDurations(page);
      const fullMoving = await findMoving(page);

      // Half two: the same route under `prefers-reduced-motion: reduce`.
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();
      await page.getByRole("button", { name: "Technical events" }).click();
      const reducedDurations = await readDurations(page);
      const reducedMoving = await findMoving(page);

      writeArtifact(
        info.outputDir,
        "motion/durations.tsv",
        [
          "# 03 §3.7's four duration tokens, read off :root in a real render",
          "token\tno-preference\treduce",
          ...Object.keys(fullDurations).map(
            (token) => `${token}\t${fullDurations[token]}\t${reducedDurations[token]}`,
          ),
        ].join("\n"),
      );
      writeArtifact(
        info.outputDir,
        "motion/moving-elements.tsv",
        [
          "# Every element with a non-zero animation or transition duration",
          "# (threshold 1.5ms, because 1ms IS the reduced-motion value)",
          "condition\tselector\tanimation\tanimation-duration\ttransition\ttransition-duration",
          ...fullMoving.map((row) =>
            [
              "no-preference",
              row.selector,
              row.animationName,
              row.animationDuration,
              row.transitionProperty,
              row.transitionDuration,
            ].join("\t"),
          ),
          ...reducedMoving.map((row) =>
            [
              "reduce",
              row.selector,
              row.animationName,
              row.animationDuration,
              row.transitionProperty,
              row.transitionDuration,
            ].join("\t"),
          ),
        ].join("\n"),
      );

      // The policy, as 03 §3.7 writes it.
      for (const [token, value] of Object.entries(reducedDurations)) {
        expect(value, `${token} did not collapse under prefers-reduced-motion`).toBe("1ms");
      }
      // The premise: there WAS motion to remove.
      expect(
        fullMoving.length,
        "nothing on the route animates or transitions even with motion " +
          "allowed, so the reduced-motion assertion below would be vacuous.",
      ).toBeGreaterThan(0);
      expect(
        reducedMoving.map(
          (row) => `${row.selector} (${row.animationName} ${row.animationDuration} / ${row.transitionProperty} ${row.transitionDuration})`,
        ),
        "these elements are still animating or transitioning under " +
          "`prefers-reduced-motion: reduce`. Every duration in the product " +
          "must come through a `--duration-*` token, which app/tokens.css " +
          "collapses to 1ms; an element still moving here has a hard-coded " +
          "duration.",
      ).toEqual([]);
    },
  );

  test(
    "no status meaning is motion-only: every mark and word survives",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.setViewportSize(DESKTOP);
      await page.goto(RUNNING, { waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();
      const full = await readSpineChannels(page);
      const fullVoid = await readSpineVoid(page);

      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();
      const reduced = await readSpineChannels(page);
      const reducedVoid = await readSpineVoid(page);

      writeArtifact(
        info.outputDir,
        "motion/status-channels.tsv",
        [
          "# 03 §3.4's three channels, with motion allowed and with it removed",
          "condition\tsegment\tstatus\tmark\tmark painted\ttext",
          ...full.map((row) =>
            ["no-preference", row.id, row.status, row.mark ?? "(none)", row.markPainted, row.text].join("\t"),
          ),
          ...reduced.map((row) =>
            ["reduce", row.id, row.status, row.mark ?? "(none)", row.markPainted, row.text].join("\t"),
          ),
          "",
          "# The dashed/dotted void — 03 §5.8, spine.css: 'a break is a shape'",
          "condition\tdata-current\tborder-style\tborder-width",
          `no-preference\t${fullVoid?.current}\t${fullVoid?.style}\t${fullVoid?.width}`,
          `reduce\t${reducedVoid?.current}\t${reducedVoid?.style}\t${reducedVoid?.width}`,
        ].join("\n"),
      );

      expect(full.length, "the spine rendered no segments").toBeGreaterThan(0);
      // The word channel and the mark channel are IDENTICAL in both
      // conditions. That equality is the whole claim: what motion carried was
      // decoration, and removing it removed nothing.
      expect(
        reduced.map((row) => `${row.id}/${row.status}/${row.mark}/${row.text}`),
        "the spine says something different under `prefers-reduced-motion`, " +
          "so some part of its meaning was being carried by the animation.",
      ).toEqual(full.map((row) => `${row.id}/${row.status}/${row.mark}/${row.text}`));
      for (const row of reduced) {
        expect(row.markPainted, `${row.id}'s mark is not painted`).toBe(true);
        expect(row.text, `${row.id} renders no status word`).not.toBe("");
      }
      // The void keeps its shape, which is the one status the spine draws
      // rather than writes.
      expect(reducedVoid?.style).toBe(fullVoid?.style);
      expect(reducedVoid?.width).toBe(fullVoid?.width);
    },
  );

  test(
    "the ambient Live indicator is a mark plus a word, not a pulse",
    { tag: "@a11y" },
    async ({ page }) => {
      // 03 §3.7: "the ambient receiving indicator becomes a static filled
      // mark plus the word *Live*". The word is what makes the pulse
      // removable, so the test is that the word is there in both conditions
      // and the animation is gone in one of them.
      await page.setViewportSize(DESKTOP);
      await page.emulateMedia({ reducedMotion: "reduce" });
      await page.goto(RUNNING, { waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();

      const live = page.locator('[data-severity="live"]').first();
      await expect(live).toBeVisible();
      await expect(live).toHaveText(/Live/);
      const marks = await readMarks(page);
      expect(
        marks.some((mark) => mark.mark === "ring" && mark.width > 0),
        "the live indicator's ring mark is not painted under reduced motion.",
      ).toBe(true);
      const animation = await live
        .locator("[data-mark]")
        .first()
        .evaluate((node) => window.getComputedStyle(node).animationName);
      expect(
        animation,
        "`.ew-pulse` is still running under reduced motion. " +
          "primitives.css disables it outright, because a 1ms *infinite* " +
          "pulse is a flicker rather than a still mark.",
      ).toBe("none");
    },
  );

  test(
    "the status region narrates transitions, not frames",
    { tag: "@a11y" },
    async ({ page }, info) => {
      // Criterion 5's second half. The ratio needs a denominator, so the
      // stream is replaced with a known burst of real `node_completed`
      // frames — see `checkpointStream` for why a seeded row cannot supply
      // one.
      const FRAMES = 40;
      await page.setViewportSize(DESKTOP);
      await recordLiveRegions(page);
      await checkpointStream(page, FIXTURES.running, FRAMES);
      await page.goto(RUNNING, { waitUntil: "domcontentloaded" });
      await page.locator('[data-surface="active-run"]').first().waitFor();

      // Wait for the burst to have been consumed: the diagnostics ring
      // counts every frame, so it is the honest signal that all of them
      // arrived rather than a sleep.
      await expect
        .poll(
          async () =>
            Number(
              (await page.locator("[data-record-count]").first().getAttribute("data-record-count")) ??
                "0",
            ),
          { timeout: 15_000 },
        )
        .toBeGreaterThanOrEqual(FRAMES);

      const samples = await readLiveRegions(page);
      const status = samples.filter((sample) => sample.role === "status");
      const alert = samples.filter((sample) => sample.role === "alert");
      const log = samples.filter((sample) => sample.role === "log");

      writeArtifact(
        info.outputDir,
        "motion/live-regions.tsv",
        [
          `# ${FRAMES} node_completed frames delivered on one connection`,
          `# frames recorded by the diagnostics ring: ${await page
            .locator("[data-record-count]")
            .first()
            .getAttribute("data-record-count")}`,
          "role\tat (ms)\ttext",
          ...samples.map(
            (sample) => `${sample.role}\t${Math.round(sample.at)}\t${sample.text}`,
          ),
        ].join("\n"),
      );

      // 03 §7.3: exactly two live regions product-wide.
      expect(
        [...new Set(samples.map((sample) => sample.role))].sort(),
        "a live region appeared that 03 §7.3 does not sanction. There are " +
          'exactly two — one role="status" and one role="alert" — plus the ' +
          'diagnostics role="log", which is tolerated only because its ' +
          "disclosure is collapsed by default.",
      ).toEqual(expect.arrayContaining(["status"]));
      for (const sample of samples) {
        expect(["status", "alert", "log"]).toContain(sample.role);
      }

      // The claim: the status region changed a handful of times, not once
      // per frame. The bound is deliberately generous — the point is the
      // ORDER OF MAGNITUDE, not a golden number that would go red the day a
      // legitimate transition is added.
      expect(
        status.length,
        `the status region changed ${status.length} times over ${FRAMES} ` +
          "frames. It carries `model.announcement` only; the checkpoint " +
          "count and the age live OUTSIDE it (`data-spine-part=\"detail\"`) " +
          "precisely so that per-frame churn is never announced. Changes:\n" +
          status.map((sample) => `  ${Math.round(sample.at)}ms  ${sample.text}`).join("\n"),
      ).toBeLessThanOrEqual(5);
      expect(status.length, "the status region never said anything").toBeGreaterThan(0);
      expect(alert, "a user-triggered alert fired during a passive stream").toEqual([]);

      // …and the region that DOES see every frame is the collapsed one, which
      // is exactly the trade 03 §7.3 makes.
      expect(
        log.length,
        "the diagnostics log recorded no change, so the burst it is supposed " +
          "to absorb never reached it.",
      ).toBeGreaterThan(0);
    },
  );
});

/* ========================================================== criterion 6 */

test.describe("criterion 6 — forced colours on the spine and the status marks", () => {
  test(
    "the emulation really forces colours, not just the media query",
    { tag: "@a11y" },
    async ({ page }, info) => {
      await page.emulateMedia({ forcedColors: "active", colorScheme: "light" });
      await page.setViewportSize(DESKTOP);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await page.getByText("What should the literature settle?").first().waitFor();

      // The three author values are CSS colour KEYWORDS rather than
      // functional notation, and that is not style: `web/tests/tokens.test.ts`
      // scans every `.ts` under `web/` for a literal colour, and it is right
      // to — one exemption for a test probe would be one exemption too many.
      // The composited values come back as the browser reports them, which is
      // functional notation, and those are the numbers the evidence records.
      const AUTHOR = { colour: "red", background: "lime", border: "blue" } as const;
      const probe = await page.evaluate((author) => {
        const node = document.createElement("p");
        node.style.color = author.colour;
        node.style.backgroundColor = author.background;
        node.style.borderTop = `2px dashed ${author.border}`;
        node.textContent = "forced-colours probe";
        document.body.append(node);
        const style = window.getComputedStyle(node);
        const out = {
          media: window.matchMedia("(forced-colors: active)").matches,
          colour: style.color,
          background: style.backgroundColor,
          borderColour: style.borderTopColor,
          borderStyle: style.borderTopStyle,
          // The same keyword resolved WITHOUT forcing, so the comparison
          // below is against what this browser would otherwise paint rather
          // than against a value typed here.
          unforced: (() => {
            const canvas = document.createElement("canvas").getContext("2d");
            if (canvas === null) return "";
            canvas.fillStyle = author.colour;
            return canvas.fillStyle;
          })(),
        };
        node.remove();
        return out;
      }, AUTHOR);

      writeArtifact(
        info.outputDir,
        "forced-colors/emulation-proof.tsv",
        [
          "# A synthetic element with author colours, measured under",
          "# emulateMedia({ forcedColors: 'active' }).",
          "property\tauthor value\tcomposited value",
          `media (forced-colors: active)\t—\t${probe.media}`,
          `color\t${AUTHOR.colour} (${probe.unforced} unforced)\t${probe.colour}`,
          `background-color\t${AUTHOR.background}\t${probe.background}`,
          `border-top-color\t${AUTHOR.border}\t${probe.borderColour}`,
          `border-top-style\tdashed\t${probe.borderStyle}`,
        ].join("\n"),
      );

      expect(probe.media).toBe(true);
      expect(
        probe.colour,
        "the emulation matched the media query but did not replace author " +
          "colours, so every assertion in this describe block would be a " +
          "green tick over an unforced page.",
      ).not.toContain("255, 0, 0");
      expect(probe.background).not.toContain("0, 255, 0");
      // …and the thing forced colours does NOT take: border STYLE, which is
      // how the spine's dashed/dotted void keeps meaning something.
      expect(probe.borderStyle).toBe("dashed");
    },
  );

  for (const scheme of ["light", "dark"] as const) {
    test(
      `the spine keeps its word and its shape in the ${scheme} forced palette`,
      { tag: "@a11y" },
      async ({ page }, info) => {
        await page.emulateMedia({ forcedColors: "active", colorScheme: scheme });
        await page.setViewportSize(DESKTOP);
        await page.goto(RUNNING, { waitUntil: "domcontentloaded" });
        await page.locator('[data-surface="active-run"]').first().waitFor();

        const segments = await readSpineChannels(page);
        const voidRule = await readSpineVoid(page);
        const marks = (await readMarks(page)).filter((mark) => mark.width > 0);
        const palette = await page.evaluate(() => {
          const system = (name: string): string => {
            const probe = document.createElement("span");
            probe.style.color = name;
            document.body.append(probe);
            const value = window.getComputedStyle(probe).color;
            probe.remove();
            return value;
          };
          return {
            canvas: window.getComputedStyle(document.body).backgroundColor,
            canvasText: system("CanvasText"),
            linkText: system("LinkText"),
          };
        });

        writeArtifact(
          info.outputDir,
          `forced-colors/spine.${scheme}.tsv`,
          [
            `# Trace spine and status marks, ${scheme} forced palette`,
            `# Canvas ${palette.canvas} · CanvasText ${palette.canvasText} · LinkText ${palette.linkText}`,
            "segment\tstatus\tmark\tpainted\tmark colour\ttext",
            ...segments.map((row) =>
              [row.id, row.status, row.mark ?? "(none)", row.markPainted, row.colour, row.text].join("\t"),
            ),
            "",
            "# Every painted [data-mark] on the page",
            "mark\tcolour\tw×h",
            ...marks.map((mark) => `${mark.mark}\t${mark.colour}\t${mark.width}×${mark.height}`),
            "",
            "# The void",
            `data-current\t${voidRule?.current}`,
            `border-top-style\t${voidRule?.style}`,
            `border-top-color\t${voidRule?.colour}`,
          ].join("\n"),
        );

        expect(segments.length).toBeGreaterThan(0);

        // THE CHANNEL THAT MUST SURVIVE #1 — the word.
        for (const segment of segments) {
          expect(segment.text, `${segment.id} has no text in forced colours`).not.toBe("");
          expect(segment.text.toLowerCase()).toContain(
            segment.status.replace(/-/g, " ").toLowerCase(),
          );
        }

        // THE CHANNEL THAT MUST SURVIVE #2 — the shape.
        for (const segment of segments) {
          expect(segment.mark, `${segment.id} renders no mark`).not.toBeNull();
          expect(segment.markPainted, `${segment.id}'s mark is not painted`).toBe(true);
        }

        // THE CHANNEL THAT MUST NOT SURVIVE — the hue. Every mark has to be
        // painted in a colour the READER chose, not one the product did.
        // Chromium's user-agent sheet puts `forced-color-adjust:
        // preserve-parent-color` on SVG, so an `<svg>` carrying its own
        // `color` opts out of the forced palette entirely — which is what
        // this project's marks did until WO-27 added the rule in
        // primitives.css. In a reader's own high-contrast theme that is a
        // shape drawn in a colour they cannot necessarily see.
        const forced = new Set([palette.canvasText, palette.linkText]);
        const unforced = marks.filter((mark) => !forced.has(mark.colour));
        expect(
          unforced.map((mark) => `${mark.mark} @ ${mark.colour}`),
          `these status marks keep an author colour in the ${scheme} forced ` +
            `palette instead of taking the reader's (Canvas ${palette.canvas}, ` +
            `CanvasText ${palette.canvasText}). 03 §3.4 puts colour third, and ` +
            "forced-colors mode is the one condition where the reader's " +
            "palette must replace the author's outright.",
        ).toEqual([]);

        // …and the one status the spine DRAWS rather than writes keeps its
        // shape, because forced colours replaces `border-color` and leaves
        // `border-style` alone.
        expect(voidRule?.style, "the void's dashed/dotted rule was flattened").toMatch(
          /dashed|dotted/,
        );
        expect(voidRule?.width).not.toBe("0px");
      },
    );
  }

  test(
    "the theme control's selected option is visible in forced colours",
    { tag: "@a11y" },
    async ({ page }, info) => {
      // The classic forced-colors failure, and one this product had: a
      // selected state carried by `background-color` alone disappears,
      // because forced colours replaces every author background with Canvas.
      // System colour keywords are the exception — they are honoured rather
      // than replaced — which is why the fix in ThemeToggle.css is
      // `Highlight`/`HighlightText` rather than `forced-color-adjust: none`.
      await page.emulateMedia({ forcedColors: "active", colorScheme: "light" });
      await page.setViewportSize(DESKTOP);
      await page.goto("/", { waitUntil: "domcontentloaded" });
      await page.locator(".ew-theme-option").first().waitFor();

      const options = await page.evaluate(() =>
        Array.from(document.querySelectorAll(".ew-theme-option")).map((label) => {
          const input = label.querySelector("input");
          const span = label.querySelector("span");
          const style = span === null ? null : window.getComputedStyle(span);
          return {
            value: input?.value ?? "?",
            checked: input?.checked === true,
            colour: style?.color ?? "",
            background: style?.backgroundColor ?? "",
          };
        }),
      );

      writeArtifact(
        info.outputDir,
        "forced-colors/theme-control.tsv",
        [
          "# ThemeToggle's three options in the light forced palette",
          "option\tchecked\tcolor\tbackground-color",
          ...options.map((option) =>
            [option.value, option.checked, option.colour, option.background].join("\t"),
          ),
        ].join("\n"),
      );

      const checked = options.filter((option) => option.checked);
      expect(checked, "no theme option is checked").toHaveLength(1);
      const selected = checked[0];
      const others = options.filter((option) => !option.checked);
      expect(selected).toBeDefined();
      if (selected === undefined) return;

      expect(
        others.map((option) => `${option.value}: ${option.colour} on ${option.background}`),
        `the selected theme option (${selected.value}) is painted ` +
          `${selected.colour} on ${selected.background}, which is what every ` +
          "unselected option is painted too. In forced colours the selection " +
          "is therefore invisible: SC 1.4.1, and the reason `Highlight` / " +
          "`HighlightText` exist.",
      ).not.toContainEqual(`${selected.colour} on ${selected.background}`);
    },
  );
});
