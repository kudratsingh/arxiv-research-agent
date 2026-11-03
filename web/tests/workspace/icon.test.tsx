import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import { Icon, type IconName } from "@/components/workspace/Icon";

it("renders each decorative icon with the shared stroke treatment", () => {
  const names: IconName[] = ["today", "radar", "library", "interests", "sources", "review", "prev", "next", "open", "save", "saved", "dismiss", "snooze", "undo", "search", "command", "sidebar", "theme", "menu", "external", "warning", "plus"];
  for (const name of names) {
    const { container, unmount } = render(<Icon name={name} />);
    const icon = container.querySelector("svg")!;
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon).toHaveAttribute("stroke", "currentColor");
    expect(icon.childElementCount).toBeGreaterThan(0);
    unmount();
  }
});
