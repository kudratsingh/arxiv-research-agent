/**
 * Shell/ErrorBoundary — WO-09's three error boundaries, in the order of how
 * much of the document survives each one.
 *
 *   Workspace  `app/(workspace)/error.tsx`. The shell survives: header,
 *              rail, theme control. Only the route's own subtree is
 *              replaced.
 *   Thread     `app/(workspace)/c/[id]/error.tsx`. The same, one segment
 *              deeper, with the narrower sentence a boundary reached during
 *              a run is allowed to make, and with `error.digest` shown as
 *              labelled evidence rather than as the message (RC-16).
 *   Global     `app/global-error.tsx`. NOTHING survives — it replaces
 *              `<html>` — so this story renders with the design tokens
 *              deliberately unset. That is criterion 5, and it is why the
 *              three are one story set rather than three files.
 *
 * `onReset` is a spy, not a no-op, so the control is demonstrably wired.
 * What it is NOT is a retry: `reset()` re-renders the segment that threw
 * and issues no request. H6 and R-01 — a mutation is never retried for
 * anyone — hold on these surfaces exactly as they hold everywhere else.
 *
 * The meta declares no `component`, deliberately: `Global` renders a
 * different component from the other two, and a single args table over
 * `RouteError` would describe two of the three stories and mislead about
 * the third.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { CSSProperties, ReactElement } from "react";
import { expect, fn, within } from "storybook/test";

import { railIsAvailable } from "@/.storybook/storyRail";
import { GlobalErrorSurface } from "@/components/patterns/GlobalErrorSurface";
import { RouteError } from "@/components/patterns/RouteError";
import { GLOBAL_ERROR } from "@/lib/copy/globalError";
import { RECOVERY, ROUTE_ERROR } from "@/lib/copy/recovery";
import {
  color,
  duration,
  ease,
  elevation,
  font,
  layout,
  radius,
  space,
  text,
} from "@/lib/tokens";

import { WorkbenchShell } from "./WorkbenchShell";

/** The rail's shape, with no `GET /conversations` behind it. */
const RAIL = (
  <ul className="flex flex-col gap-1 p-3">
    {["Retrieval-augmented verification", "Sparse attention survey"].map((title, index) => (
      <li key={title}>
        <a
          href={`/c/thread-${index + 1}`}
          className="ew-focusable block truncate rounded-md px-3 py-2 text-ui-sm text-ink hover:bg-sunken"
        >
          {title}
        </a>
      </li>
    ))}
  </ul>
);

function InShell({ children }: { children: ReactElement }) {
  return (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      {children}
    </WorkbenchShell>
  );
}

/**
 * EVERY design token, set to `initial` — the risk note's "rendered with
 * tokens deliberately absent", as a thing the story does rather than a
 * thing its comment claims.
 *
 * The names are read out of `web/lib/tokens.ts`, which is generated from
 * `web/app/tokens.css`, so this cannot fall behind the token set: a token
 * added tomorrow is unset here tomorrow. `initial` on a custom property
 * makes it invalid at computed-value time, so every `var(--…)` inside this
 * subtree — whether it arrived through a Tailwind utility or through an
 * inline style — resolves to nothing.
 *
 * `.storybook/preview.tsx` imports the product's stylesheets globally and a
 * story cannot unload them, so this is the faithful version of "absent":
 * the sheet is loaded and every value it defines is switched off for this
 * subtree.
 */
const TOKENS_UNSET = Object.fromEntries(
  [
    ...new Set(
      Array.from(
        JSON.stringify([
          color,
          duration,
          ease,
          elevation,
          font,
          layout,
          radius,
          space,
          text,
        ]).matchAll(/--[a-z0-9-]+/g),
        (match) => match[0],
      ),
    ),
  ].map((name) => [name, "initial"]),
) as CSSProperties;

const meta: Meta = {
  title: "Shell/ErrorBoundary",
  parameters: { nextjs: { appDirectory: true } },
};

export default meta;
type Story = StoryObj<typeof meta>;

/** `app/(workspace)/error.tsx`: the shell is still there, and still works. */
export const Workspace: Story = {
  render: () => (
    <InShell>
      <RouteError
        heading={ROUTE_ERROR.errorHeading}
        body={ROUTE_ERROR.errorBody}
        actionLabel={ROUTE_ERROR.errorAction}
        onReset={fn()}
        digestLabel={RECOVERY.referenceLabel}
        digestRecovery={RECOVERY.referenceRecovery}
      />
    </InShell>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { level: 1, name: ROUTE_ERROR.errorHeading }),
    ).toBeInTheDocument();

    // WO-27: "the shell survives" means something different either side of
    // `md`, and this story is rendered at all five RC-14 widths. Above the
    // breakpoint the rail is the visible proof; below it the rail is out of
    // the layout by design (04 §8.3 repair step 1) and what survives is the
    // landmark structure and the heading. Asserting the first unconditionally
    // was 6 of the 48 play-function errors in
    // `evidence/gate-3/known-gaps.md` §2d.
    if (railIsAvailable()) {
      await expect(canvas.getByRole("navigation", { name: "Threads" })).toBeInTheDocument();
    } else {
      await expect(canvas.queryByRole("navigation", { name: "Threads" })).toBeNull();
      // The boundary still renders inside the shell's single `<main>`, which
      // is the part of "the shell survives" that holds at every width.
      await expect(canvasElement.querySelector("main#main")).not.toBeNull();
    }

    // No digest was passed, so no evidence row is invented for it.
    await expect(canvas.queryByText(RECOVERY.referenceLabel)).toBeNull();
  },
};

/**
 * `app/(workspace)/c/[id]/error.tsx`, with the server's correlation hash.
 * The digest is labelled, in mono, under the sentence — never the sentence.
 */
export const Thread: Story = {
  render: () => (
    <InShell>
      <RouteError
        heading={RECOVERY.threadErrorHeading}
        body={RECOVERY.threadErrorBody}
        actionLabel={ROUTE_ERROR.errorAction}
        onReset={fn()}
        digest="3f1c9ad0c2b74e6a"
        digestLabel={RECOVERY.referenceLabel}
        digestRecovery={RECOVERY.referenceRecovery}
      />
    </InShell>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { level: 1, name: RECOVERY.threadErrorHeading }),
    ).toBeInTheDocument();
    await expect(canvas.getByText("3f1c9ad0c2b74e6a")).toBeInTheDocument();
    await expect(canvas.getByText(RECOVERY.referenceLabel)).toBeInTheDocument();
  },
};

/**
 * `app/global-error.tsx` — no shell, no stylesheet, no token.
 *
 * The surface is built out of CSS system colours (`Canvas`, `CanvasText`,
 * `ButtonFace`) and inline styles, so it renders the same whether or not
 * the token sheet loaded. The play function proves the load-bearing half of
 * that rather than asserting it: not one element in the subtree carries a
 * `class`, which is the only way a Tailwind utility — and therefore a
 * `var(--…)` — could get in.
 */
export const Global: Story = {
  render: () => (
    <div style={TOKENS_UNSET} data-tokens-unset="">
      <GlobalErrorSurface digest="3f1c9ad0c2b74e6a" onReload={fn()} />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    await expect(
      canvas.getByRole("heading", { level: 1, name: GLOBAL_ERROR.heading }),
    ).toBeInTheDocument();
    await expect(
      canvas.getByRole("button", { name: GLOBAL_ERROR.action }),
    ).toBeInTheDocument();

    const surface = canvasElement.querySelector<HTMLElement>(
      '[data-recovery-surface="global-error"]',
    );
    await expect(surface).not.toBeNull();

    // No class anywhere in the subtree: no Tailwind utility, therefore no
    // custom property, therefore nothing the missing token sheet could have
    // taken away.
    await expect(surface?.querySelectorAll("[class]").length).toBe(0);
    await expect(surface?.hasAttribute("class")).toBe(false);
    // It does style itself — with inline declarations only.
    await expect(surface?.getAttribute("style") ?? "").not.toBe("");
  },
};
