import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { expect, within } from "storybook/test";

import detailFixture from "@/contract/fixtures/learn.path.detail.json";
import type { ApiFailure, LearnPathDetail } from "@/lib/api";
import { LEARN, describeSessionStart } from "@/lib/copy/learn";

import { PathUnavailable, PathView } from "./PathView";

const fixturePath = detailFixture.body as LearnPathDetail;

/** A path with no fixture banner, so the start states are the only novelty. */
const plainPath: LearnPathDetail = {
  ...fixturePath,
  fixture: false,
  banner: null,
};

const firstEntry = fixturePath.entries[0]!;

/**
 * Refusals built from real `ApiFailure` shapes, not from hand-written props.
 *
 * The story renders whatever `describeSessionStart` produces, so the mapping
 * table and the surface cannot drift: change a sentence and the assertion
 * below moves with it; delete a mapping and the mapped story shows the
 * generic sentence and fails.
 */
const FLAG_OFF: ApiFailure = {
  kind: "not_found",
  status: 404,
  message: "",
  raw: { detail: "session_loop_disabled" },
};

/**
 * A `detail` this dictionary has no sentence for.
 *
 * RC-16: the generic sentence AND the service's own word, unedited. Written
 * as a code nothing in `src/api/sessions.py` raises today, because that is
 * exactly the situation the fall-through exists for.
 */
const UNMAPPED: ApiFailure = {
  kind: "conflict",
  status: 409,
  message: "",
  raw: { detail: "a_refusal_this_surface_has_never_seen" },
};

const meta = {
  title: "PathView",
  component: PathView,
  args: { path: fixturePath },
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof PathView>;

export default meta;
type Story = StoryObj<typeof meta>;

export const FixtureLabeled: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.fixtureLabel)).toBeVisible();
    await expect(canvas.getAllByRole("link", { name: LEARN.openPaper })).toHaveLength(3);
  },
};

export const NoProgress: Story = {
  args: { path: { ...fixturePath, fixture: false, banner: null } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(LEARN.noProgress)).toBeVisible();
    await expect(canvas.getAllByText(LEARN.notObserved)).toHaveLength(3);
  },
};

export const WithProgress: Story = {
  args: {
    path: { ...fixturePath, fixture: false, banner: null },
    observations: fixturePath.entries.slice(0, 2).map((entry, index) => ({
      path_id: fixturePath.path_id,
      resource_id: entry.resource_id,
      sessions_completed: 1,
      last_observed_at: `2026-08-2${index + 4}T09:00:00.000000Z`,
      event_ids: [`evt-${index + 1}`],
    })),
  },
  play: async ({ canvasElement }) => {
    const entries = canvasElement.querySelectorAll("[data-path-entry]");
    await expect(entries[0]).toHaveAttribute("data-observation", "observed");
    await expect(entries[1]).toHaveAttribute("data-observation", "observed");
    await expect(entries[2]).toHaveAttribute("data-observation", "not-observed");
  },
};

// ---------------------------------------------------------------------------
// WO-W13b — the start action. Three states, one story each, axe on all three.
// ---------------------------------------------------------------------------

export const StartAvailable: Story = {
  args: { path: plainPath, onStartSession: () => undefined },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const buttons = canvas.getAllByRole("button", { name: LEARN.startSession });
    await expect(buttons).toHaveLength(3);
    for (const button of buttons) {
      await expect(button).not.toHaveAttribute("aria-disabled", "true");
      await expect(button).not.toHaveAttribute("aria-busy", "true");
    }
    // Every start control names the paper it would start, for a reader who
    // arrives on the control rather than on the heading above it.
    await expect(buttons[0]).toHaveAccessibleDescription(firstEntry.title);
  },
};

export const Starting: Story = {
  args: {
    path: plainPath,
    onStartSession: () => undefined,
    startingResourceId: firstEntry.resource_id,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const started = canvas.getByRole("button", { name: LEARN.startingSession });
    await expect(started).toHaveAttribute("aria-busy", "true");
    await expect(started).toHaveAttribute("aria-disabled", "true");

    // The other two are unavailable and NOT busy: nothing is happening on
    // them, and `aria-busy` there would announce work that does not exist.
    const others = canvas.getAllByRole("button", { name: LEARN.startSession });
    await expect(others).toHaveLength(2);
    for (const button of others) {
      await expect(button).toHaveAttribute("aria-disabled", "true");
      await expect(button).not.toHaveAttribute("aria-busy", "true");
    }

    // No spinner standing in for progress, and no invented percentage:
    // the only fact this state holds is that one POST is outstanding.
    await expect(canvas.queryAllByRole("progressbar")).toHaveLength(0);
    await expect(canvasElement.textContent ?? "").not.toMatch(/%/);
  },
};

export const StartRefused: Story = {
  args: {
    path: plainPath,
    onStartSession: () => undefined,
    startRefusal: {
      resourceId: firstEntry.resource_id,
      ...describeSessionStart(FLAG_OFF),
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const alert = canvas.getByRole("alert");
    await expect(alert).toHaveTextContent(LEARN.startRefusedHeading);
    await expect(alert).toHaveTextContent(LEARN.startRefusedDisabled);
    // A mapped refusal needs no wire code beside it.
    await expect(canvas.queryByText(LEARN.startRefusedDetail)).toBeNull();
    // One entry refused is one entry refused: the other two still offer it.
    await expect(
      canvas.getAllByRole("button", { name: LEARN.startSession })
    ).toHaveLength(3);
  },
};

export const StartRefusedUnmapped: Story = {
  args: {
    path: plainPath,
    onStartSession: () => undefined,
    startRefusal: {
      resourceId: firstEntry.resource_id,
      ...describeSessionStart(UNMAPPED),
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const alert = canvas.getByRole("alert");
    await expect(alert).toHaveTextContent(LEARN.startRefusedGeneric);
    // RC-16: the service's own word, verbatim, under its own label.
    await expect(alert).toHaveTextContent(LEARN.startRefusedDetail);
    await expect(alert).toHaveTextContent("a_refusal_this_surface_has_never_seen");
  },
};

export const Unavailable: Story = {
  render: () => <PathUnavailable onRetry={() => undefined} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: LEARN.pathUnavailableHeading })
    ).toBeVisible();
    await expect(canvas.getByRole("button", { name: LEARN.retry })).toBeVisible();
  },
};
