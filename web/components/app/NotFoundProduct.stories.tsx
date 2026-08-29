/**
 * Shell/NotFoundProduct — 03 §2.2 row 21, the 404 the PRODUCT raises.
 *
 * This is the state the Gate 1 baseline fails `page-has-heading-one` on —
 * the single such failure in the whole audit set
 * (docs/revamp/baseline/axe/conversation-not-found.json, 03 §7.1). The
 * baseline rendered one red sentence and no heading at all
 * (docs/revamp/baseline/screenshots/conversation-not-found-desktop.png).
 *
 * THE SENTENCE IS THE POINT OF THIS STORY (criterion 3, H8).
 * `GET /conversations/{id}` answers 404 in two different situations and
 * gives the client no way to tell them apart: the thread never existed, or
 * it belongs to another principal. `_check_ownership`
 * (`src/api/routes.py:59`) says why in its own docstring — "leaking 'this
 * exists but you can't touch it' is an info-disclosure vector. From the
 * client's perspective, resources owned by other principals simply don't
 * exist." So the copy names BOTH causes and claims NEITHER. It never says
 * "deleted" (which asserts the thread existed) and never says "no
 * permission" (which asserts it exists and is someone else's). The play
 * function below asserts both absences on the rendered text, and
 * web/tests/copy/recovery-copy.test.ts asserts them on the dictionary.
 *
 * TWO ROUTES OUT (03 §2.2 row 21). The primary is `/`, the landing
 * composer. The second is the thread rail itself — an in-page link to the
 * `nav` landmark WO-08 gives every route, which is where the threads this
 * deployment *does* have are listed. It is passed by the caller rather than
 * built into `NotFound`, because below 768px the rail is not rendered at
 * all and the surface that renders this state is the one that knows.
 */

import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import { NotFound } from "@/components/patterns/NotFound";
import { THREAD } from "@/lib/copy/threads";

import { RAIL_ID, WorkbenchShell } from "./WorkbenchShell";

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
  title: "Shell/NotFoundProduct",
  component: NotFound,
  parameters: { nextjs: { appDirectory: true } },
  // Through `render`, not `decorators`: story-level decorators COMPOSE with
  // the meta's, so the narrow-mode story below would otherwise sit inside
  // two shells and fail `landmark-no-duplicate-main` for a reason that
  // exists only in the harness.
  render: (args) => (
    <WorkbenchShell rail={RAIL} railMode="expanded" railCollapsed={false}>
      <NotFound {...args} />
    </WorkbenchShell>
  ),
  args: {
    heading: THREAD.notFoundHeading,
    body: THREAD.notFoundBody,
    actionLabel: THREAD.notFoundBackToStart,
    actionHref: "/",
    secondaryLabel: THREAD.notFoundBackToList,
    secondaryHref: `#${RAIL_ID}`,
  },
} satisfies Meta<typeof NotFound>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);

    // Criterion 2: the heading the baseline does not have.
    const heading = canvas.getByRole("heading", {
      level: 1,
      name: THREAD.notFoundHeading,
    });
    await expect(heading).toBeInTheDocument();

    // Criterion 3, on the rendered text rather than on the constant.
    const body = canvas.getByText(THREAD.notFoundBody);
    await expect(body).toHaveTextContent(/never have existed/i);
    await expect(body).toHaveTextContent(/another principal/i);
    await expect(body.textContent ?? "").not.toMatch(/deleted/i);
    await expect(body.textContent ?? "").not.toMatch(/no permission/i);

    // Two routes out, at two different destinations.
    await expect(
      canvas.getByRole("link", { name: THREAD.notFoundBackToStart }),
    ).toHaveAttribute("href", "/");
    await expect(
      canvas.getByRole("link", { name: THREAD.notFoundBackToList }),
    ).toHaveAttribute("href", `#${RAIL_ID}`);
  },
};

/**
 * The same state with only the primary way out — what a surface renders
 * below 768px, where the rail is absent from the layout and an in-page link
 * to it would point at nothing.
 */
export const WithoutTheRail: Story = {
  globals: { viewport: { value: "w412" } },
  args: { secondaryLabel: undefined, secondaryHref: undefined },
  render: (args) => (
    <WorkbenchShell rail={RAIL} railMode="drawer">
      <NotFound {...args} />
    </WorkbenchShell>
  ),
};
