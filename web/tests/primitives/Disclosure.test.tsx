/**
 * Criterion 5, second clause: "`Disclosure` uses `aria-expanded` on a real
 * `<button>`". "Real" is doing work in that sentence — a `<div role="button">`
 * would satisfy a role query and fail on Space, on form participation and on
 * the browser's own focus handling, so the element type is asserted directly.
 */

import { describe, expect, it, vi } from "vitest";

import { Disclosure } from "@/components/primitives/Disclosure";
import { render, screen, user } from "../support/render";

describe("Disclosure", () => {
  it("uses a real button element, not a role", () => {
    render(<Disclosure label="Diagnostics">42 frames</Disclosure>);
    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).toHaveAttribute("type", "button");
  });

  it("starts closed, with aria-expanded=false and the panel hidden", () => {
    render(<Disclosure label="Diagnostics">42 frames</Disclosure>);
    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    const panel = document.getElementById(trigger.getAttribute("aria-controls") as string);
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");
  });

  it("points aria-controls at a panel that always exists", () => {
    render(<Disclosure label="Diagnostics">42 frames</Disclosure>);
    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    // Closed rather than unmounted, so the reference is never dangling.
    expect(document.getElementById(trigger.getAttribute("aria-controls") as string))
      .toHaveTextContent("42 frames");
  });

  it("opens from defaultOpen without an interaction", () => {
    render(
      <Disclosure label="Diagnostics" defaultOpen>
        42 frames
      </Disclosure>,
    );
    expect(screen.getByRole("button", { name: "Diagnostics" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("42 frames")).not.toHaveAttribute("hidden");
  });

  it("toggles on click", async () => {
    render(<Disclosure label="Diagnostics">42 frames</Disclosure>);
    const trigger = screen.getByRole("button", { name: "Diagnostics" });

    await user().click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user().click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("toggles on Enter and on Space, because a real button does", async () => {
    render(<Disclosure label="Diagnostics">42 frames</Disclosure>);
    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    trigger.focus();

    await user().keyboard("{Enter}");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    await user().keyboard(" ");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("obeys a controlled open prop and reports the intent", async () => {
    const onOpenChange = vi.fn();
    render(
      <Disclosure label="Diagnostics" open={false} onOpenChange={onOpenChange}>
        42 frames
      </Disclosure>,
    );
    const trigger = screen.getByRole("button", { name: "Diagnostics" });

    await user().click(trigger);
    expect(onOpenChange).toHaveBeenCalledWith(true);
    // Controlled: the component does not move on its own.
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("reports the intent in uncontrolled mode too", async () => {
    const onOpenChange = vi.fn();
    render(
      <Disclosure label="Diagnostics" onOpenChange={onOpenChange}>
        42 frames
      </Disclosure>,
    );
    await user().click(screen.getByRole("button", { name: "Diagnostics" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(screen.getByRole("button", { name: "Diagnostics" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("names the panel with the trigger", () => {
    render(
      <Disclosure label="Diagnostics" defaultOpen>
        42 frames
      </Disclosure>,
    );
    const trigger = screen.getByRole("button", { name: "Diagnostics" });
    const panel = screen.getByRole("group", { name: "Diagnostics" });
    expect(panel).toHaveAttribute("aria-labelledby", trigger.id);
  });

  it("renders an aside beside the label without stealing the button's name", () => {
    render(
      <Disclosure label="Export" aside={<span>Partial</span>}>
        Formats
      </Disclosure>,
    );
    // The aside is inside the button, so it joins the name — which is what a
    // status beside a label should do. (The two spans are adjacent with no
    // whitespace between them, so the computed name has no space either.)
    expect(screen.getByRole("button", { name: "ExportPartial" })).toBeInTheDocument();
  });

  it("accepts a caller-supplied trigger id", () => {
    render(
      <Disclosure label="Diagnostics" id="diag">
        42 frames
      </Disclosure>,
    );
    expect(screen.getByRole("button", { name: "Diagnostics" })).toHaveAttribute("id", "diag");
  });
});
