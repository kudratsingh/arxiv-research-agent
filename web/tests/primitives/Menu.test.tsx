/**
 * Criterion 5, third clause: "`Menu` implements roving focus — the defect
 * `ExportDropdown.tsx:69` exhibits".
 *
 * The defect, precisely: that component announces `role="menu"` over anchors
 * that keep their natural tab stops, have no `tabindex="-1"`, respond to no
 * arrow key, and never receive focus when the menu opens. The assertions
 * below are the inverse of each of those four, one at a time, so a
 * regression names which half of the contract broke.
 */

import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/primitives/Button";
import { Menu, MenuItem, MenuSeparator } from "@/components/primitives/Menu";
import { render, screen, user, waitFor } from "../support/render";

function ThreadMenu({
  onRename,
  defaultOpen,
  label,
}: {
  onRename?: () => void;
  defaultOpen?: boolean;
  label?: string;
}) {
  return (
    <Menu
      trigger={<Button aria-label="Thread actions" iconOnly children={<svg />} />}
      defaultOpen={defaultOpen}
      label={label}
    >
      <MenuItem onSelect={onRename}>Rename</MenuItem>
      <MenuItem disabled>Duplicate</MenuItem>
      <MenuSeparator />
      <MenuItem tone="critical">Delete</MenuItem>
    </Menu>
  );
}

describe("Menu", () => {
  it("announces itself on the trigger before it opens", () => {
    render(<ThreadMenu />);
    const trigger = screen.getByRole("button", { name: "Thread actions" });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("opens from a prop, and is named by its trigger", () => {
    render(<ThreadMenu defaultOpen />);
    // The APG pattern: the menu takes its name from the button that owns it.
    expect(screen.getByRole("menu", { name: "Thread actions" })).toBeInTheDocument();
  });

  it("takes an explicit name when the trigger's is not the right one", () => {
    render(<ThreadMenu defaultOpen label="Actions for “Sparse attention”" />);
    expect(
      screen.getByRole("menu", { name: "Actions for “Sparse attention”" }),
    ).toBeInTheDocument();
  });

  it("gives the items a single tab stop — the roving tabindex", () => {
    render(<ThreadMenu defaultOpen />);
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(3);
    // This is the assertion ExportDropdown.tsx:69 fails: its anchors keep
    // their own tab stops, so Tab walks the menu instead of leaving it.
    for (const item of items) expect(item).toHaveAttribute("tabindex", "-1");
  });

  it("moves focus into the menu when it is opened from the keyboard", async () => {
    render(<ThreadMenu />);
    screen.getByRole("button", { name: "Thread actions" }).focus();
    await user().keyboard("{Enter}");

    const items = await screen.findAllByRole("menuitem");
    await waitFor(() => expect(items[0]).toHaveFocus());
  });

  it("roves with the arrow keys, and skips the disabled item", async () => {
    render(<ThreadMenu />);
    screen.getByRole("button", { name: "Thread actions" }).focus();
    await user().keyboard("{Enter}");

    const [rename, duplicate, remove] = await screen.findAllByRole("menuitem");
    await waitFor(() => expect(rename).toHaveFocus());

    await user().keyboard("{ArrowDown}");
    // "Duplicate" is disabled, so the rove passes over it entirely.
    await waitFor(() => expect(remove).toHaveFocus());
    expect(duplicate).not.toHaveFocus();

    await user().keyboard("{ArrowUp}");
    await waitFor(() => expect(rename).toHaveFocus());
  });

  it("jumps to the last item on End and the first on Home", async () => {
    render(<ThreadMenu />);
    screen.getByRole("button", { name: "Thread actions" }).focus();
    await user().keyboard("{Enter}");
    const items = await screen.findAllByRole("menuitem");

    await user().keyboard("{End}");
    await waitFor(() => expect(items.at(-1)).toHaveFocus());
    await user().keyboard("{Home}");
    await waitFor(() => expect(items[0]).toHaveFocus());
  });

  it("selects with Enter and closes", async () => {
    const onRename = vi.fn();
    render(<ThreadMenu onRename={onRename} />);
    screen.getByRole("button", { name: "Thread actions" }).focus();
    await user().keyboard("{Enter}");
    await screen.findAllByRole("menuitem");

    await user().keyboard("{Enter}");
    expect(onRename).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    render(<ThreadMenu />);
    const trigger = screen.getByRole("button", { name: "Thread actions" });
    trigger.focus();
    await user().keyboard("{Enter}");
    await screen.findAllByRole("menuitem");

    await user().keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("marks the disabled item as disabled rather than hiding it", () => {
    render(<ThreadMenu defaultOpen />);
    const duplicate = screen.getByRole("menuitem", { name: "Duplicate" });
    expect(duplicate).toHaveAttribute("aria-disabled", "true");
  });

  it("does not hide the rest of the page, because it is not modal", () => {
    render(
      <div>
        <button type="button">Outside</button>
        <ThreadMenu defaultOpen />
      </div>,
    );
    // Radix's modal mode would put aria-hidden on this button's ancestors,
    // which for a menu (no `role=dialog` for axe to find) is a real
    // aria-hidden-focus violation rather than a forgiven one.
    expect(screen.getByRole("button", { name: "Outside" })).toBeInTheDocument();
    expect(document.querySelector("[aria-hidden='true'][data-radix-popper-content-wrapper]"))
      .toBeNull();
  });

  it("renders in place when the portal is turned off", () => {
    const { container } = render(<ThreadMenu defaultOpen />);
    const portalled = container.querySelector("[role='menu']");
    expect(portalled).toBeNull();

    const inline = render(
      <Menu trigger={<Button aria-label="More" iconOnly children={<svg />} />} defaultOpen portal={false}>
        <MenuItem>Rename</MenuItem>
      </Menu>,
    );
    expect(inline.container.querySelector("[role='menu']")).not.toBeNull();
  });

  it("reports opening and closing to the caller", async () => {
    const onOpenChange = vi.fn();
    render(
      <Menu
        trigger={<Button aria-label="Thread actions" iconOnly children={<svg />} />}
        onOpenChange={onOpenChange}
      >
        <MenuItem>Rename</MenuItem>
      </Menu>,
    );

    await user().click(screen.getByRole("button", { name: "Thread actions" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});
