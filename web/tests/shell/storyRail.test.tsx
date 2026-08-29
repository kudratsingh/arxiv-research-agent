/**
 * WO-27 criterion 7 — the six viewport- and motion-dependent play functions.
 *
 * WHAT WAS WRONG. The Gate 3 pack ran all 261 stories in a real browser at
 * RC-14's five widths in three modes and recorded 48 play-function assertion
 * errors across 6 stories (`evidence/gate-3/known-gaps.md` §2d). They fell
 * into two groups with two different causes:
 *
 *   group 1  three Radix overlay stories asserting `toBeVisible()` on content
 *            whose enter transition had not finished. They failed in light and
 *            dark at every width and PASSED under `prefers-reduced-motion` at
 *            every width, because `app/tokens.css` collapses the durations to
 *            1ms there. Fixed by retrying the visibility check.
 *   group 2  three `Shell` stories looking for the rail at 320 and 412, where
 *            04 §8.3 repair step 1 deliberately takes it out of the layout.
 *            Fixed by branching on `.storybook/storyRail.ts`.
 *
 * WHAT THIS FILE PROVES, AND WHAT IT CANNOT. The merged Vitest Storybook
 * project runs each story ONCE, in jsdom, at one viewport — which is exactly
 * why it could not see any of this. This file runs the three group-2 play
 * functions **twice each**: once with the rail laid out and once with the rail
 * hidden the way `workbench.css` hides it below `md`. That is a real second
 * presentation, produced by injecting the author's own declaration rather than
 * a restatement of it (the technique `tests/primitives/support/css.ts`
 * documents for `(pointer: coarse)`, and for the same jsdom reason: no `@media`
 * block that omits `screen` is ever evaluated here).
 *
 * It does NOT reproduce group 1's cause. A CSS enter transition needs a
 * compositor, and jsdom has none — `toBeVisible()` there is a `display` /
 * `visibility` / inline-`opacity` check with nothing animating behind it. So
 * group 1's fix is proven by shape (`waitFor` around the visibility
 * assertion, asserted below) and by the render matrix when it is next run,
 * and this file says so rather than implying a coverage it does not have.
 *
 * The stories are invoked as the plain objects they are — `story.play({
 * canvasElement, canvas })` over a container this file rendered. `composeStories`
 * is the usual route and is not available here: it pulls
 * `@storybook/nextjs-vite`, whose browser chunk needs the `sb-original` alias
 * that only the Storybook Vite plugin installs, and the `unit` project does
 * not have it.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import ErrorBoundaryMeta, { Workspace } from "@/components/app/ErrorBoundary.stories";
import NotFoundMeta, { Default as NotFoundDefault } from "@/components/app/NotFoundFramework.stories";
import WorkbenchMeta, { RailCollapseToggle } from "@/components/app/WorkbenchShell.stories";
import { WorkbenchShell } from "@/components/app/WorkbenchShell";
import { RAIL_COLLAPSED_STORAGE_KEY } from "@/lib/tokens";
import { railIsAvailable, railPresentation } from "@/.storybook/storyRail";

import { render, screen, within } from "../support/render";
import { installMatchMedia, uninstallMatchMedia } from "./support";

const WEB_ROOT = path.resolve(__dirname, "..", "..");
const read = (relative: string): string =>
  readFileSync(path.join(WEB_ROOT, relative), "utf8");

/**
 * `workbench.css`'s own narrow-viewport declaration, applied unconditionally.
 *
 * Read out of the file rather than typed, so the simulation cannot drift from
 * the rule it simulates: if WO-08 ever hides the rail some other way, this
 * stops matching and the test says so instead of quietly testing a fiction.
 */
function narrowRailRule(): string {
  const css = read("components/app/workbench.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const start = css.indexOf("@media (max-width: 767px)");
  expect(
    start,
    "workbench.css no longer has an `@media (max-width: 767px)` block, so " +
      "the presentation this file simulates may no longer be the product's.",
  ).toBeGreaterThan(-1);
  const body = css.slice(css.indexOf("{", start));
  expect(body).toContain(".ew-shell__rail");
  expect(body).toContain("display: none");
  // `#workbench-rail` rather than `.ew-shell__rail`: the id is what
  // `storyRail.ts` reads, and using it here keeps the simulation honest about
  // WHICH element the media query removes.
  return "#workbench-rail { display: none; }";
}

let injected: HTMLStyleElement | null = null;

function hideRail(): void {
  const style = document.createElement("style");
  style.textContent = narrowRailRule();
  document.head.append(style);
  injected = style;
}

beforeEach(() => {
  installMatchMedia({ width: 1440, prefersDark: false });
  window.localStorage.clear();
});

afterEach(() => {
  injected?.remove();
  injected = null;
  uninstallMatchMedia();
  window.localStorage.clear();
});

/* =========================================================================
 * The helper the three group-2 stories branch on
 * ========================================================================= */

describe("storyRail — the three presentations, told apart", () => {
  const RAIL = <p>rail contents</p>;

  it("reports `in-layout` when the rail is rendered and laid out", () => {
    render(
      <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
        <p>surface</p>
      </WorkbenchShell>,
    );
    expect(railPresentation()).toBe("in-layout");
    expect(railIsAvailable()).toBe(true);
  });

  it("reports `hidden-by-css` when the narrow rule removes it", () => {
    hideRail();
    render(
      <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
        <p>surface</p>
      </WorkbenchShell>,
    );
    // This is the case the three stories got wrong: the `<nav>` IS in the
    // document, so a `querySelector` finds it, and it is NOT in the
    // accessibility tree, so `getByRole` throws.
    expect(document.querySelector("#workbench-rail")).not.toBeNull();
    expect(railPresentation()).toBe("hidden-by-css");
    expect(railIsAvailable()).toBe(false);
  });

  it("reports `not-rendered` when the shell resolved the drawer mode", () => {
    render(
      <WorkbenchShell rail={RAIL} railMode="drawer">
        <p>surface</p>
      </WorkbenchShell>,
    );
    expect(railPresentation()).toBe("not-rendered");
    expect(railIsAvailable()).toBe(false);
  });
});

/* =========================================================================
 * The play functions themselves, in both presentations
 * ========================================================================= */

/** Render a story and run its `play`, the way a Storybook runner would. */
async function runStory(
  element: React.ReactElement,
  play: ((context: never) => Promise<void> | void) | undefined,
): Promise<HTMLElement> {
  const { container } = render(element);
  const canvasElement = container as HTMLElement;
  expect(play, "the story has no play function to run").toBeDefined();
  await (play as (context: {
    canvasElement: HTMLElement;
    canvas: ReturnType<typeof within>;
  }) => Promise<void>)({ canvasElement, canvas: within(canvasElement) });
  return canvasElement;
}

describe("Shell/NotFoundFramework · Default holds at every width", () => {
  // `NotFoundMeta.args` narrows every string to a literal (the exact copy in
  // `lib/copy/recovery`), and spreading widens them back, so the merged object
  // is described through `render`'s OWN parameter type rather than through the
  // inferred one. The values are still the meta's; nothing is typed here.
  const element = () => {
    const args = { ...NotFoundMeta.args, ...NotFoundDefault.args } as Parameters<
      typeof NotFoundMeta.render
    >[0];
    return NotFoundMeta.render(args);
  };

  it("passes with the rail laid out, and finds it", async () => {
    const canvas = await runStory(element(), NotFoundDefault.play);
    expect(within(canvas).getByRole("navigation", { name: "Threads" })).toBeInTheDocument();
  });

  it("passes with the rail hidden below md, and does not look for it", async () => {
    hideRail();
    const canvas = await runStory(element(), NotFoundDefault.play);
    expect(within(canvas).queryByRole("navigation", { name: "Threads" })).toBeNull();
    // …and the assertion that carries the story at that width still holds.
    expect(within(canvas).getByRole("heading", { level: 1 })).toBeInTheDocument();
  });
});

describe("Shell/ErrorBoundary · Workspace holds at every width", () => {
  const element = () =>
    (Workspace.render as () => React.ReactElement)();

  it("passes with the rail laid out", async () => {
    const canvas = await runStory(element(), Workspace.play);
    expect(within(canvas).getByRole("navigation", { name: "Threads" })).toBeInTheDocument();
  });

  it("passes with the rail hidden below md", async () => {
    hideRail();
    const canvas = await runStory(element(), Workspace.play);
    expect(within(canvas).queryByRole("navigation", { name: "Threads" })).toBeNull();
    // The shell's single `<main>` is what "the shell survives" means below md.
    expect(canvas.querySelector("main#main")).not.toBeNull();
  });
});

describe("Shell/WorkbenchShell · RailCollapseToggle holds at every width", () => {
  const element = () => {
    const args = { ...WorkbenchMeta.args, ...RailCollapseToggle.args };
    return <WorkbenchShell {...args} />;
  };

  /** The story's own `beforeEach`, run the way Storybook runs it. */
  async function withStoryFixture(run: () => Promise<void>): Promise<void> {
    const cleanup = await (
      RailCollapseToggle.beforeEach as () => (() => void) | Promise<() => void>
    )();
    try {
      await run();
    } finally {
      await cleanup();
    }
  }

  it("clicks the toggle and writes the preference where the rail exists", async () => {
    await withStoryFixture(async () => {
      await runStory(element(), RailCollapseToggle.play);
      expect(screen.getByRole("button", { name: "Expand the rail" })).toBeInTheDocument();
    });
  });

  it("asserts the toggle's absence where the rail is hidden below md", async () => {
    hideRail();
    await withStoryFixture(async () => {
      const canvas = await runStory(element(), RailCollapseToggle.play);
      expect(within(canvas).queryByRole("button", { name: "Collapse the rail" })).toBeNull();
      // The story took the other branch, so it must NOT have written the
      // preference — a play function that silently no-ops is not a fix.
      expect(window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe("0");
    });
  });
});

/* =========================================================================
 * Group 1 — the shape of the fix, since jsdom cannot reproduce the cause
 * ========================================================================= */

describe("the three overlay stories retry their visibility assertions", () => {
  // A CSS enter transition needs a compositor. jsdom has none, so the race
  // these three lost cannot be reproduced here and this is a source-shape
  // assertion, stated as one. What it defends against is the specific
  // regression: somebody replacing the `waitFor` with a bare assertion,
  // seeing green in the Vitest Storybook project, and reintroducing 30 of the
  // 48 render-matrix errors.
  const CASES = [
    ["components/patterns/ThreadList.stories.tsx", ["DeleteConfirm", "RowMenuOpen"]],
    ["components/features/ThreadDrawer.stories.tsx", ["Open"]],
  ] as const;

  for (const [file, stories] of CASES) {
    it(`${file} wraps its overlay visibility checks in waitFor`, () => {
      // Comments stripped first: these stories explain the fix in prose that
      // quotes `toBeVisible()`, so an unstripped scan finds the sentence
      // about the assertion before it finds the assertion.
      const source = read(file)
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^[ \t]*\/\/.*$/gm, "");
      expect(source, `${file} does not import waitFor`).toContain("waitFor");
      for (const story of stories) {
        const start = source.indexOf(`export const ${story}`);
        expect(start, `${file} has no story called ${story}`).toBeGreaterThan(-1);
        const next = source.indexOf("\nexport const ", start + 1);
        const body = source.slice(start, next === -1 ? undefined : next);
        // Every `toBeVisible()` in the story has to be inside a waitFor
        // callback. Counting is enough here because these bodies contain one
        // waitFor each; the assertion that matters is that none is left
        // outside it.
        const visible = body.match(/toBeVisible\(\)/g)?.length ?? 0;
        expect(visible, `${story} asserts no visibility at all`).toBeGreaterThan(0);
        expect(
          body,
          `${story} asserts toBeVisible() outside a waitFor, which races the ` +
            "Radix enter transition at every width where motion is allowed.",
        ).toMatch(/waitFor\(async \(\) => \{[\s\S]*toBeVisible\(\)/);
        const beforeWaitFor = body.slice(0, body.indexOf("waitFor("));
        expect(
          beforeWaitFor,
          `${story} has a toBeVisible() before its waitFor.`,
        ).not.toContain("toBeVisible()");
      }
    });
  }
});
