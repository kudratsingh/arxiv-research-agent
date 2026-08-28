import { describe, expect, it } from "vitest";

import { Skeleton } from "@/components/primitives/Skeleton";
import { render, screen } from "../support/render";
import { customProperties, readWebFile, stripComments } from "./support/css";

const TOKENS = customProperties(stripComments(readWebFile("app/tokens.css")));
const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));

describe("Skeleton", () => {
  it("renders one bar by default", () => {
    const { container } = render(<Skeleton />);
    expect(container.querySelectorAll(".ew-skeleton")).toHaveLength(1);
  });

  it("renders the number of bars asked for", () => {
    const { container } = render(<Skeleton lines={4} />);
    expect(container.querySelectorAll(".ew-skeleton")).toHaveLength(4);
  });

  it("never renders fewer than one bar, whatever it is handed", () => {
    const { container } = render(<Skeleton lines={0} />);
    expect(container.querySelectorAll(".ew-skeleton")).toHaveLength(1);
  });

  it("hides every bar from assistive technology", () => {
    const { container } = render(<Skeleton lines={3} />);
    for (const bar of container.querySelectorAll(".ew-skeleton")) {
      expect(bar).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("ends a multi-line block short, the way a paragraph ends", () => {
    const { container } = render(<Skeleton lines={3} />);
    const bars = [...container.querySelectorAll<HTMLElement>(".ew-skeleton")];
    expect(bars[0]?.style.width).toBe("100%");
    expect(bars.at(-1)?.style.width).toBe("60%");
  });

  it("takes a width and a height from props", () => {
    const { container } = render(<Skeleton width="40%" height="2rem" />);
    const bar = container.querySelector<HTMLElement>(".ew-skeleton");
    expect(bar?.style.width).toBe("40%");
    expect(bar?.style.height).toBe("2rem");
  });

  it("carries a clipped name when the region has no other one", () => {
    render(<Skeleton lines={2} label="Loading the thread list" />);
    expect(screen.getByText("Loading the thread list")).toHaveClass("ew-visually-hidden");
  });

  it("has no name at all unless one is asked for", () => {
    const { container } = render(<Skeleton />);
    expect(container.textContent).toBe("");
  });

  it("does not shimmer — 03 §3.7 forbids it by name", () => {
    const { container } = render(<Skeleton lines={3} />);
    for (const bar of container.querySelectorAll(".ew-skeleton")) {
      expect(bar).not.toHaveClass("ew-pulse");
      expect(bar).not.toHaveClass("ew-enter");
    }
    // And the class itself declares no animation, so nothing can be added
    // to it by a stylesheet the component does not control.
    expect(PRIMITIVES_CSS).toMatch(/\.ew-skeleton\s*\{[^}]*\}/);
    const rule = /\.ew-skeleton\s*\{([^}]*)\}/.exec(PRIMITIVES_CSS)?.[1] ?? "";
    expect(rule).not.toMatch(/animation/);
    expect(rule).not.toMatch(/transition/);
  });

  it("paints from tokens rather than literals", () => {
    // Asserted against the stylesheet rather than a computed value:
    // jsdom's CSSOM validates colour properties eagerly and discards a
    // `var()` it cannot resolve, so a computed background-color here would
    // be measuring jsdom, not the product.
    const rule = /\.ew-skeleton\s*\{([^}]*)\}/.exec(PRIMITIVES_CSS)?.[1] ?? "";
    expect(rule).toContain("var(--color-sunken)");
    expect(rule).toContain("var(--radius-sm)");
    expect(TOKENS.get("--color-sunken")).toBeDefined();
  });
});
