import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ActivityCard } from "@/components/workspace/ActivityCard";
import { AllocationReceipt } from "@/components/workspace/AllocationReceipt";
import { InterestCoverage } from "@/components/workspace/InterestCoverage";
import type { Activity } from "@/lib/workspace/api";
import { work, workspace } from "./fixtures";
const activity = (overrides: Partial<Activity> = {}): Activity => ({
  sequence: 4,
  entry_id: null,
  work_id: work().work_id,
  version_id: work().version_id,
  kind: "reading",
  entry_kind: null,
  body: "",
  anchor: "abstract:3:18",
  revision: 1,
  updated_at: "2026-11-02T15:00:00Z",
  ...overrides,
});
describe("continuity under incomplete retained metadata", () => {
  it("preserves an unavailable source's activity without inventing a return destination", () => {
    render(
      <ActivityCard
        activity={activity()}
        pinned={false}
        busy={false}
        onPin={vi.fn()}
      />,
    );
    expect(
      screen.getByText(/source is unavailable in the loaded view/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("A reading location is saved for this source version."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
  it("uses the actual current title when no version list survives and retains an earlier unknown version separately", () => {
    const item = work({ versions: [] });
    const view = render(
      <ActivityCard
        activity={activity()}
        work={item}
        pinned={false}
        busy={false}
        onPin={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("link", { name: `${item.title} →` }),
    ).toHaveAttribute(
      "href",
      expect.stringContaining(encodeURIComponent(item.version_id)),
    );
    view.rerender(
      <ActivityCard
        activity={activity({ version_id: "old:retained:v1" })}
        work={item}
        pinned={false}
        busy={false}
        onPin={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Earlier retained source version →" }),
    ).toHaveAttribute("href", expect.stringContaining("old%3Aretained%3Av1"));
  });
  it("pins a next-action proposal and supports legacy entry records whose kind is unavailable", async () => {
    const user = userEvent.setup(),
      onPin = vi.fn();
    const view = render(
      <ActivityCard
        activity={activity({
          entry_id: "action-id",
          entry_kind: "next-action",
          kind: "entry",
          body: "Try a bounded retrieval comparison",
        })}
        work={work()}
        pinned={false}
        busy={false}
        onPin={onPin}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Pin this next action" }),
    );
    expect(onPin).toHaveBeenCalledWith("action-id");
    view.rerender(
      <ActivityCard
        activity={activity({ entry_id: "legacy-entry" })}
        work={work()}
        pinned={false}
        busy={false}
        onPin={onPin}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Pin this item" }));
    expect(onPin).toHaveBeenLastCalledWith("legacy-entry");
  });
  it("does not fabricate allocation or monitoring from missing receipts", () => {
    render(
      <>
        <AllocationReceipt
          allocation={{ actual_items: 3, actual_fraction: Number.NaN }}
        />
        <InterestCoverage
          coverage={[
            {
              topic_id: "browse:field",
              label: "A broad field",
              matching_mode: "browse_only",
              terms: [],
              descendant_ids: [],
              source_ids: ["not-configured"],
              status: "unconnected",
              limitations: [],
            },
          ]}
          draft={false}
          sources={workspace().sources}
        />
      </>,
    );
    expect(
      screen.getByText(/no recorded exploration allocation/),
    ).toBeInTheDocument();
    expect(screen.getByText(/not-configured/)).toBeInTheDocument();
  });
  it("distinguishes a missing historical allocation from one actual exploration item and an unconnected custom interest", () => {
    const view = render(<AllocationReceipt allocation={undefined} />);
    expect(
      screen.getByText(/no recorded exploration allocation/),
    ).toBeInTheDocument();
    view.rerender(
      <>
        <AllocationReceipt
          allocation={{
            slots: 9,
            requested_fraction: 0.15,
            planned_max_exploration_slots: 1,
            max_exploration_slots: 1,
            actual_exploration_slots: 1,
            actual_items: 9,
            actual_fraction: 1 / 9,
            unused_slots: 0,
            rounding: "floor_final_count",
          }}
        />
        <InterestCoverage
          draft={false}
          coverage={[
            {
              topic_id: "custom:embodied navigation",
              label: "Embodied navigation",
              matching_mode: "literal_terms",
              terms: ["embodied navigation"],
              descendant_ids: [],
              source_ids: [],
              status: "unconnected",
              limitations: [
                "No adapter currently monitors this custom interest.",
              ],
            },
          ]}
          sources={workspace().sources}
        />
      </>,
    );
    expect(
      screen.getByText("1 exploration item", { exact: true }),
    ).toBeInTheDocument();
    expect(screen.getByText(/among 9 selected \(11.1%\)/)).toBeInTheDocument();
    expect(
      screen.getByText("Matching terms available · no connected source"),
    ).toBeInTheDocument();
    expect(screen.getByText("None for this selection")).toBeInTheDocument();
    expect(
      screen.getByText("No adapter currently monitors this custom interest."),
    ).toBeInTheDocument();
  });
});
