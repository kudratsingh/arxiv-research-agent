import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button } from "@/components/primitives/Button";
import { render, screen, user } from "../support/render";

describe("Button", () => {
  it("defaults to type=button rather than the HTML default of submit", () => {
    render(<Button>Review plan</Button>);
    expect(screen.getByRole("button", { name: "Review plan" })).toHaveAttribute(
      "type",
      "button",
    );
  });

  it("submits when asked to", () => {
    render(<Button type="submit">Ask</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  it.each(["primary", "secondary", "ghost", "critical"] as const)(
    "renders the %s variant from a prop alone",
    (variant) => {
      render(<Button variant={variant}>Go</Button>);
      expect(screen.getByRole("button", { name: "Go" })).toBeInTheDocument();
    },
  );

  it.each(["sm", "md", "lg"] as const)("carries the %s target class", (size) => {
    render(<Button size={size}>Go</Button>);
    expect(screen.getByRole("button")).toHaveClass("ew-target", `ew-target--${size}`);
  });

  it("is focusable and carries the shared focus class", () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole("button")).toHaveClass("ew-focusable");
  });

  it("disables permanently with the DOM attribute", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Go
      </Button>,
    );

    const button = screen.getByRole("button");
    expect(button).toBeDisabled();
    expect(button).not.toHaveAttribute("aria-disabled");
    await user().click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("stays focusable while busy, and refuses the click anyway", async () => {
    const onClick = vi.fn();
    render(
      <Button busy onClick={onClick}>
        Submitting
      </Button>,
    );

    const button = screen.getByRole("button");
    // The whole point of `busy`: announced as unavailable, still reachable.
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();

    button.focus();
    expect(button).toHaveFocus();

    await user().click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("calls onClick when it is neither disabled nor busy", async () => {
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Go</Button>);
    await user().click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("throws when an icon-only button has no accessible name", () => {
    // React logs the render error; the assertion is the throw itself.
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() =>
      render(
        <Button iconOnly>
          <svg />
        </Button>,
      ),
    ).toThrow(/iconOnly requires an accessible name/);
    error.mockRestore();
  });

  it("accepts an icon-only button named by aria-label or aria-labelledby", () => {
    render(
      <>
        <span id="close-label">Close</span>
        <Button iconOnly aria-label="Dismiss">
          <svg />
        </Button>
        <Button iconOnly aria-labelledby="close-label">
          <svg />
        </Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
  });

  it("stretches when asked", () => {
    render(<Button fullWidth>Go</Button>);
    expect(screen.getByRole("button")).toHaveClass("w-full");
  });

  it("forwards its ref, which is what lets Radix use it as a trigger", () => {
    const ref = createRef<HTMLButtonElement>();
    render(<Button ref={ref}>Go</Button>);
    expect(ref.current).toBe(screen.getByRole("button"));
  });

  it("passes arbitrary button attributes through", () => {
    render(
      <Button data-testid="probe" aria-describedby="note">
        Go
      </Button>,
    );
    const button = screen.getByTestId("probe");
    expect(button).toHaveAttribute("aria-describedby", "note");
  });
});
