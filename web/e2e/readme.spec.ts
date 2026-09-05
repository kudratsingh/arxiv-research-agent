import { existsSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { settleForCapture } from "./support/capture";
import { FIXTURES } from "./support/env";
import { STATES, readyLocator } from "./support/states";
import type { ReadyCondition } from "./support/states";

/**
 * WO-D2 — the README's screenshots, as Playwright snapshots.
 *
 * WHAT THIS CLOSES. The assurance index's claim R14 is the README's sentence
 * that its screenshots cost nothing to produce. WO-C2 mechanised the
 * MECHANISM — `fixtures/seed.sh` writes through `psql` and `redis-cli` and
 * never issues `POST /research`, and the stack is pinned to an invalid
 * sentinel key — and then said plainly what was still missing: **nothing
 * bound the committed PNGs to any run**, so a hand-edited screenshot passed
 * every check in the repository. The five images `README.md` renders were
 * produced by hand, at three different geometries, and committed once
 * (`docs: README overhaul`, PR 110). Nothing has re-derived them since.
 *
 * This file re-derives them. Each README image is now a `toHaveScreenshot`
 * baseline whose snapshot path IS the file the README renders, so
 * regenerating one is a reviewable diff rather than a new opaque asset, and
 * an image edited by any other means fails this suite the next time it runs.
 *
 * THE SNAPSHOT PATH IS THE POINT, AND IT IS WHY THERE IS A SEPARATE PROJECT.
 * `playwright.config.ts`'s default `snapshotPathTemplate` puts committed
 * bytes under `e2e/__screenshots__/{platform}/`, which is right for
 * `visual.spec.ts` and wrong here: the README has to reference a stable path
 * that GitHub can render, and that path is `docs/images/`. So the `readme`
 * project overrides the template to point there and takes `@readme` alone.
 *
 * AND THAT MEANS THIS SUITE INHERITS THE PLATFORM TRAP, WHICH IS STATED
 * RATHER THAN PAPERED OVER. `visual.spec.ts` keeps `{platform}` in its path
 * because macOS and Linux rasterise the same font differently; a set shared
 * between them fails on whichever host did not produce it. These snapshots
 * CANNOT carry a platform segment — one README, one image path — so the
 * committed bytes are darwin's, and the suite skips on any other platform
 * exactly as the visual sweep does. **The `web-e2e` CI job runs on Linux, so
 * this gate does not run in CI.** It is a local gate: it goes red for the
 * developer who regenerates a screenshot on macOS and for nobody else. That
 * is a real limit and it is the same one WO-28 accepted and recorded; what
 * it still buys over the previous state is that the PNGs are now DERIVED —
 * there is a command that produces them, a table that says what each one is
 * a picture of, and a diff when they move. `tests/test_documented_claims.py`
 * holds the Python-tier half, which does run in CI: every image the README
 * renders has to be named by the table below.
 *
 * WHY THE GEOMETRIES ARE NOT `visual.spec.ts`'s. That suite captures the
 * audit widths — 412 and 1440, at the heights the accessibility matrix
 * measures — because its job is to gate the layouts the audit is about. This
 * one reproduces the README's own presentation, which is a different job: the
 * committed images were 1600 wide at device-scale 1, and the mobile shot was
 * 390 CSS px at device-scale 2, and a reader looking at the README should not
 * see the page's illustrations change shape because a test file was added.
 * Each geometry below is therefore the one the image it replaces was taken
 * at, measured off the committed PNG rather than guessed.
 *
 * THE COST BOUNDARY IS THE SAME ONE, UNCHANGED. This runs against the seeded
 * Compose stack pinned to `ANTHROPIC_API_KEY=local-preview-disabled`, over
 * fixtures written straight into Postgres and Redis. No render here submits
 * anything: three of the five are resting routes and two are seeded jobs, so
 * `POST /research` is never reached and the README's "no model call was made
 * to produce them" stays true of images that are now checkable.
 */

// ---------------------------------------------------------------------------
// The inventory
// ---------------------------------------------------------------------------

/**
 * Mirrors the `readme` project's `snapshotPathTemplate`. One meaning, two
 * uses — the guard below needs to know where the committed bytes are without
 * re-deriving the path from the template.
 */
const IMAGE_DIR = join(__dirname, "..", "..", "docs", "images");

/**
 * `--update-snapshots` modes that WRITE, so the skip below lifts for them.
 *
 * The same pair `visual.spec.ts` uses, and deliberately not `missing`:
 * Playwright's default writes a missing snapshot and then fails, which is
 * right for one new image beside an existing set and wrong for a platform
 * that has none.
 */
const REGENERATING = ["all", "changed"];

/**
 * The platform whose bytes are committed.
 *
 * Hard-coded rather than derived, unlike `visual.spec.ts`'s directory scan,
 * because there is no directory to scan: the images live at one path with no
 * platform segment, so "which platform produced these" is not recoverable
 * from the tree and has to be written down. It is `darwin` because that is
 * where PR 110 captured the originals and where WO-D2 re-derived them.
 */
const CAPTURE_PLATFORM = "darwin";

/**
 * The same bound `visual.spec.ts` uses, and for the same measured reason.
 *
 * Its note records that the only render whose pixels move between two forced
 * regenerations is the briefing at desktop width, where the `SectionRail` is
 * `position: sticky` and lays out at a fractional x offset — so the same two
 * links are rasterised either snapped to whole device pixels or not, half a
 * pixel apart, for 124 to 131 pixels of glyph coverage. Two of the five
 * images here are that render. The bound is on AREA rather than on
 * per-pixel `threshold`, so a colour change across a whole surface stays red
 * however small its per-pixel delta is.
 */
const MAX_DIFF_PIXELS = 200;

interface ReadmeShot {
  /** The committed file, without `.png`. Becomes the snapshot name. */
  file: string;
  /** What the README says this picture is, for the failure message. */
  subject: string;
  /** A `support/states.ts` row id, so no path or ready condition is retyped. */
  state: string;
  /**
   * The seeded job to attach to the row's route, for the pictures that are
   * of a RUN rather than of a resting thread.
   *
   * `states.ts` has no row for a succeeded run — its table is the twenty §4
   * states the axe and reflow sweeps walk, and a finished run is not one of
   * them — so the two briefing shots attach `baseline-succeeded` to the
   * `thread-populated` route. The route still comes from the table; only the
   * query string is added here, which is what keeps a rename in `states.ts`
   * failing loudly instead of silently capturing the wrong page.
   */
  job?: string;
  /**
   * Replaces the row's ready condition when `job` has changed what the page
   * settles into.
   *
   * `thread-populated`'s own condition is the thread title, which is on
   * screen before the attached run has resolved — right for its own row and
   * not enough here, where the subject IS the run.
   */
  ready?: ReadyCondition;
  theme: "light" | "dark";
  /** CSS pixels. See the geometry note in the header. */
  viewport: { width: number; height: number };
  /** 1 for the desktop set, 2 for the phone shot — as committed. */
  deviceScaleFactor: number;
  /**
   * Scrolled into view before the capture, when the subject is not already
   * in frame.
   *
   * ONE SHOT USES THIS AND TWO DELIBERATELY DO NOT, which is a measurement
   * rather than a preference. The plan editor scrolls inside
   * `.ew-thread__run`, a 224 px box, and that scroll is reproducible: three
   * consecutive verification runs are byte-identical.
   *
   * Scrolling the THREAD TIMELINE is not. The briefing shots first scrolled
   * to the metrics strip, and the second verification run differed by 3,870
   * pixels — every glyph in the scrolled region ghosted against itself,
   * nothing above or below it touched. The scroll offset was not the cause:
   * probed four times it was 384 every time, with the strip at
   * y = 518.921875 every time. That FRACTIONAL y is the cause, and it is the
   * mechanism `visual.spec.ts` measured for its sticky `SectionRail` — a
   * scrollable box is a candidate for compositor promotion, a promoted layer
   * rasterises snapped to whole device pixels and an unpromoted one does
   * not, so the same content is painted half a pixel apart between runs.
   * Over one sticky rail that is 124 pixels; over a scrolled timeline it is
   * twelve thousand, far past any tolerance a gate could carry and still
   * catch a regression.
   *
   * So the two briefing shots do not scroll the timeline, and their captions
   * describe what an unscrolled thread shows. The alternative — a
   * `maxDiffPixels` wide enough to swallow a re-rasterised viewport — is the
   * answer `visual.spec.ts` rejects in as many words, because it would
   * swallow the regression the gate exists to catch.
   */
  scrollTo?: string;
  /**
   * Capture this RECTANGLE of the viewport rather than the whole of it.
   *
   * One shot needs it, and what forced it is a finding rather than a
   * preference. The plan editor is 714 px tall and the row it lives in,
   * `.ew-thread__run`, is a **fixed 14 rem box** — `components/features/
   * workspace.css` says so and says why: a content-sized row moves when the
   * ledger gains a horizontal scrollbar, which Chromium scored at 0.038 CLS.
   * The clamp is therefore deliberate product design, it is the same 223 px
   * at every viewport height measured (900, 1000 and 1376), and the editor
   * scrolls inside it.
   *
   * So the picture PR 110 committed — the whole plan editor, unclipped — is
   * of a layout this product deliberately no longer has, and no capture can
   * reproduce it. An element screenshot does not escape it either: Playwright
   * photographs the element's box out of the rendered page, so the turn list
   * overlapping it comes too. What is left, and what this clip is, is the
   * region that genuinely exists: the spine, the review state, and the run
   * row. It also keeps the parked run's live-updating `Duration` — computed
   * against `now`, because this fixture has no `completed_at` — out of
   * frame, which is what makes this shot byte-stable at all.
   */
  clip?: { x: number; y: number; width: number; height: number };
  /**
   * Anything that has to HAPPEN after navigation to reach the picture.
   *
   * The two briefing shots need it and nothing else does. `ThreadTimeline`
   * renders the metrics strip only for the turn that is EXPANDED and only
   * when that turn's run detail has been fetched, and the turn a thread
   * opens expanded is its last one — which here is the partial-export run.
   * The README's sentence is about the finished run's metrics, so the
   * capture attaches `baseline-succeeded` and opens the turn that owns it.
   * Without this the picture is a real page that does not contain the thing
   * the sentence beside it names.
   */
  drive?: (page: Page) => Promise<void>;
}

/** One of WO-21's rows, by id, so a rename there fails here loudly. */
function row(id: string): { path: string; ready: ReadyCondition } {
  const entry = STATES.find((state) => state.id === id);
  if (entry === undefined) {
    throw new Error(
      `support/states.ts has no "${id}" row. This file names states by id so ` +
        "a rename there fails here instead of silently capturing the wrong " +
        "page into the README.",
    );
  }
  return { path: entry.path, ready: entry.ready };
}

/**
 * Open the turn the attached run belongs to.
 *
 * By accessible name rather than by index or by a `data-` hook: the button
 * is the turn's own question, which is seeded text, so this fails loudly if
 * the fixture changes rather than clicking whatever is first.
 */
async function expandFirstTurn(page: Page): Promise<void> {
  await page
    .getByRole("button", {
      name: /How should scientific research agents verify claims/i,
    })
    .first()
    .click();
}

/**
 * The five images `README.md` renders, in the order it renders them.
 *
 * `docs/images/social-preview.png` is deliberately absent. It is not a
 * product render and the README does not display it — it is the repository's
 * GitHub social-preview card, a designed graphic with no page behind it, so
 * there is nothing for a browser to reproduce. The Python-tier check is
 * scoped to the images the README actually renders for that reason.
 */
const SHOTS: readonly ReadmeShot[] = [
  {
    file: "workbench-briefing",
    subject:
      "a completed research thread: the thread rail, the checkpoint spine, " +
      "and the finished briefing in the report reader beside its section rail",
    state: "thread-populated",
    job: FIXTURES.succeeded,
    drive: expandFirstTurn,
    // The metrics strip itself, not the thread title: the title is on screen
    // before the run resolves, and the strip is the thing the README's
    // sentence names last and the thing this shot exists to show.
    ready: { kind: "selector", value: '[data-metrics="true"]' },
    theme: "light",
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
  },
  {
    file: "workbench-landing",
    subject: "the landing composer, which states the cost boundary",
    state: "landing",
    theme: "light",
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
  },
  {
    file: "workbench-plan-review",
    subject:
      "the spine at plan_ready above the plan editor: sub-questions beside " +
      "arXiv queries, both editable before anything is spent",
    state: "plan-review",
    /**
     * TWO REASONS, AND THE SECOND IS A DETERMINISM BUG THIS CAUGHT.
     *
     * The thread body opens scrolled to its latest turn, so the plan editor
     * — which is the subject — sat above the fold and the first capture was
     * a picture of the turn list with a sliver of the editor's banner.
     *
     * And what that capture DID contain was a metrics strip reading
     * `Duration 727244.0s`. `baseline-plan-review` is a parked run with
     * `completed_at: null`, so its duration is computed against `now` and is
     * a different number on every run — a snapshot that could never be
     * byte-stable and would have trained everybody to regenerate on sight.
     * Scrolling to the editor fixes the picture and takes the moving number
     * out of frame at the same time; the finished run's duration, in the two
     * briefing shots, is fixed because that job has a `completed_at`.
     */
    // Inside the run row, which scrolls independently: the row opens on the
    // spine and the editor is below it, and the row is 224 px whatever the
    // viewport does. Spine or editor, not both — that is what a fixed 14 rem
    // box means, and the editor is the subject the README's sentence is
    // about.
    scrollTo: '[data-surface="plan-editor"]',
    clip: { x: 0, y: 0, width: 1400, height: 356 },
    theme: "light",
    // The height is the viewport the clip is taken out of, not the picture's
    // — 356 px of a 1376 px page. Kept at the committed image's viewport so
    // the layout above the clip is the layout that image was taken in.
    viewport: { width: 1400, height: 1376 },
    deviceScaleFactor: 1,
  },
  {
    file: "workbench-dark",
    subject: "the same research thread in the dark theme",
    state: "thread-populated",
    job: FIXTURES.succeeded,
    drive: expandFirstTurn,
    ready: { kind: "selector", value: '[data-metrics="true"]' },
    theme: "dark",
    viewport: { width: 1600, height: 1000 },
    deviceScaleFactor: 1,
  },
  {
    file: "workbench-mobile",
    subject:
      "the workbench at 390 px: the rail collapsed to a Threads drawer button",
    state: "landing",
    theme: "light",
    // The width the README's own sentence names, at the device-scale the
    // committed 780 x 1688 image was taken at.
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
  },
];

// ---------------------------------------------------------------------------
// The sweep
// ---------------------------------------------------------------------------

for (const shot of SHOTS) {
  test.describe(`README ${shot.file}.png`, () => {
    // Per-shot rather than per-project: `deviceScaleFactor` is a context
    // option and cannot be changed by `setViewportSize`, and these five do
    // not share one geometry. The viewport is set here too, in the same
    // place, so the two halves of a geometry cannot drift apart.
    test.use({
      viewport: shot.viewport,
      deviceScaleFactor: shot.deviceScaleFactor,
    });

    test(
      `is the committed picture of ${shot.subject}`,
      { tag: "@readme" },
      async ({ page }, info) => {
        test.skip(
          process.platform !== CAPTURE_PLATFORM &&
            !REGENERATING.includes(info.config.updateSnapshots),
          `the README's images were captured on "${CAPTURE_PLATFORM}" and ` +
            `this is "${process.platform}". They live at one path with no ` +
            "platform segment, because README.md has to reference a path " +
            "GitHub can render, so there is no second set to compare " +
            "against and a comparison here would fail on font " +
            "rasterisation rather than on the product. This is why the gate " +
            "does not run in CI; see the header.",
        );

        // Theme and motion before navigation, and `emulateMedia` rather than
        // the persisted preference for the reason `visual.spec.ts` gives:
        // `theme.spec.ts` pins a live defect in which a stored `dark` is
        // overwritten by the hydration pass.
        await page.emulateMedia({
          colorScheme: shot.theme,
          reducedMotion: "reduce",
        });

        const entry = row(shot.state);
        const path =
          shot.job === undefined
            ? entry.path
            : `${entry.path}${entry.path.includes("?") ? "&" : "?"}job=${shot.job}`;
        const ready = shot.ready ?? entry.ready;
        await page.goto(path, { waitUntil: "domcontentloaded" });
        await shot.drive?.(page);

        // Never photograph a blank page, and never the wrong theme — the two
        // ways a screenshot suite goes quietly worthless.
        await expect(readyLocator(page, ready)).toBeVisible();
        await expect(page.locator("html")).toHaveAttribute(
          "data-theme",
          shot.theme,
        );
        if (shot.scrollTo !== undefined) {
          await page.locator(shot.scrollTo).first().scrollIntoViewIfNeeded();
        }
        await settleForCapture(page);

        await expect(page).toHaveScreenshot(`${shot.file}.png`, {
          clip: shot.clip,
          // The viewport, not the document: these are illustrations in a
          // README, and a several-thousand-pixel full-page render is both
          // committed bytes and a picture nobody can read at README width.
          fullPage: false,
          animations: "disabled",
          caret: "hide",
          // `device` rather than Playwright's `css` default, because here
          // the device scale IS part of the artefact: the committed phone
          // shot is a 2x image of a 390 px viewport, and `css` would
          // downscale it to 390 px wide and replace the README's picture
          // with a softer one. `visual.spec.ts` wants the opposite — it
          // compares CSS pixels so a run on a retina display and a run on a
          // 1x monitor produce the same bytes — and keeps the default.
          scale: "device",
          maxDiffPixels: MAX_DIFF_PIXELS,
        });
      },
    );
  });
}

// ---------------------------------------------------------------------------
// The inventory, asserted rather than described
// ---------------------------------------------------------------------------

test.describe("the README image set", () => {
  test("every shot names a distinct committed file", { tag: "@readme" }, () => {
    const files = SHOTS.map((shot) => shot.file);
    expect(
      new Set(files).size,
      "two shots writing one file means the second silently asserts against " +
        "the first's pixels",
    ).toBe(files.length);
  });

  test("every shot's baseline is committed", { tag: "@readme" }, () => {
    const missing = SHOTS.map((shot) => `${shot.file}.png`).filter(
      (file) => !existsSync(join(IMAGE_DIR, file)),
    );
    expect(
      missing,
      "these README images have no committed bytes under docs/images/. The " +
        "README renders them, so a missing file is a broken image on the " +
        "front page; regenerate with `npm run e2e:readme:update` on " +
        `${CAPTURE_PLATFORM} and commit the result.`,
    ).toEqual([]);
  });

  test("every shot names a real state row", { tag: "@readme" }, () => {
    // `row()` throws with the explanation; this makes the throw a named
    // failure rather than five identically-worded capture errors.
    expect(() => SHOTS.forEach((shot) => row(shot.state))).not.toThrow();
  });
});
