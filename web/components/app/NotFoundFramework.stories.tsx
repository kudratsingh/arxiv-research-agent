/**
 * Shell/NotFoundFramework — 03 §2.2 row 22, the 404 the FRAMEWORK raises.
 *
 * WHY THE NAME. WO-09 owns two different 404s and criterion 6 names a story
 * for each. They are told apart by who raised them, which is also what
 * decides where each one renders:
 *
 *   NotFoundFramework  the address matches no route. Next raises it and
 *                      `app/not-found.tsx` catches it, so it is a whole
 *                      page. This file.
 *   NotFoundProduct    `GET /conversations/{id}` answered 404. The API
 *                      raised it and the thread renders it inline, inside
 *                      a page that is otherwise fine. ./NotFoundProduct.stories.tsx.
 *
 * WHAT IS BEING REPLACED. Next's default is `next-error-h1`: the numeral
 * 404 beside "This page could not be found", centred on an otherwise empty
 * document (docs/revamp/baseline/screenshots/framework-not-found-desktop.png).
 * It has no rail, no landmarks and no way back into the product. This story
 * is rendered inside `WorkbenchShell` for that reason — criterion 1's "the
 * rail intact" is a claim about the surrounding page, so the story has to
 * contain the surrounding page or it proves nothing.
 *
 * The rail is a stand-in with no network behind it, exactly as
 * ./WorkbenchShell.stories.tsx does it: 04 §5.1's layer rule is that a
 * story needs no MSW and no network, and the shell's `rail` prop is the
 * seam that keeps that true.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { NotFound } from "@/components/patterns/NotFound";
import { ROUTE_ERROR } from "@/lib/copy/recovery";

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

const meta = {
  title: "Shell/NotFoundFramework",
  component: NotFound,
  parameters: {
    // Both the surface's actions and the shell's collapsed-rail control are
    // `next/link`, which needs the App Router context rather than the Pages
    // Router default.
    nextjs: { appDirectory: true },
  },
  // The shell is applied through `render` rather than through `decorators`
  // on purpose: story-level decorators COMPOSE with the meta's, so a
  // narrow-mode story that wrapped itself in a second shell would produce
  // two `<main>` elements and fail `landmark-no-duplicate-main` — an axe
  // failure caused entirely by the story harness. A story-level `render`
  // replaces this one instead.
  render: (args) => (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <NotFound {...args} />
    </WorkbenchShell>
  ),
  args: {
    heading: ROUTE_ERROR.notFoundHeading,
    body: ROUTE_ERROR.notFoundBody,
    actionLabel: ROUTE_ERROR.notFoundAction,
    actionHref: "/",
  },
} satisfies Meta<typeof NotFound>;

export default meta;
type Story = StoryObj<typeof meta>;

/**
 * Criterion 1, as a rendered assertion: a real `h1`, the rail still there,
 * and "Start a new question" as the primary action.
 */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    // The `h1` the framework default does not give the product. (Next's own
    // 404 has an `h1` reading "404"; what it has no version of is a heading
    // that says what happened, in a document with landmarks.)
    await expect(
      canvas.getByRole("heading", { level: 1, name: ROUTE_ERROR.notFoundHeading }),
    ).toBeInTheDocument();

    // The rail, intact — the whole difference from the baseline screenshot.
    await expect(canvas.getByRole("navigation", { name: "Threads" })).toBeInTheDocument();

    const action = canvas.getByRole("link", { name: ROUTE_ERROR.notFoundAction });
    await expect(action).toHaveAttribute("href", "/");
  },
};

/**
 * Below 768px the rail is not rendered at all (WO-08's structural repair),
 * so this is the state where "the rail intact" is not available and the
 * primary action carries the whole recovery. It is still one `h1` and still
 * inside `<main>`.
 */
export const Narrow: Story = {
  globals: { viewport: { value: "w412" } },
  render: (args) => (
    <WorkbenchShell rail={RAIL} railMode="drawer">
      <NotFound {...args} />
    </WorkbenchShell>
  ),
};
