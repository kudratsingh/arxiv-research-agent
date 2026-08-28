import { afterEach, describe, expect, it } from "vitest";

import { SkipLink } from "@/components/primitives/SkipLink";
import { render, screen, user } from "../support/render";
import {
  installStylesheet,
  readWebFile,
  ruleBody,
  stripComments,
} from "./support/css";

const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));

const sheets: HTMLStyleElement[] = [];
afterEach(() => {
  while (sheets.length > 0) sheets.pop()?.remove();
});

describe("SkipLink", () => {
  it("is an anchor to #main by default", () => {
    render(<SkipLink />);
    const link = screen.getByRole("link", { name: "Skip to main content" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "#main");
  });

  it("points anywhere the caller asks", () => {
    render(<SkipLink targetId="report">Skip to the report</SkipLink>);
    expect(screen.getByRole("link", { name: "Skip to the report" })).toHaveAttribute(
      "href",
      "#report",
    );
  });

  it("is clipped rather than hidden, so it is still in the tab order", () => {
    sheets.push(installStylesheet(PRIMITIVES_CSS));
    render(<SkipLink />);
    const link = screen.getByRole("link", { name: "Skip to main content" });

    const style = getComputedStyle(link);
    expect(style.position).toBe("absolute");
    expect(style.width).toBe("1px");
    expect(style.display).not.toBe("none");
    expect(link).not.toHaveAttribute("aria-hidden");
  });

  it("is the first thing Tab reaches", async () => {
    render(
      <>
        <SkipLink />
        <button type="button">Header control</button>
      </>,
    );

    await user().tab();
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveFocus();
  });

  it("reveals itself on :focus-visible, not on :focus", () => {
    // jsdom cannot match either pseudo-class in a cascade, so this asserts
    // the authored rule. The reveal's declarations are checked for the four
    // properties that actually reverse the clip.
    const reveal = ruleBody(PRIMITIVES_CSS, ".ew-skip-link:focus-visible");
    expect(reveal).toMatch(/position:\s*fixed/);
    expect(reveal).toMatch(/width:\s*auto/);
    expect(reveal).toMatch(/clip:\s*auto/);
    expect(reveal).toMatch(/clip-path:\s*none/);
    expect(PRIMITIVES_CSS).not.toMatch(/\.ew-skip-link:focus(?!-visible)/);
  });

  it("carries the shared focus class so the revealed box takes the ring", () => {
    render(<SkipLink />);
    expect(screen.getByRole("link")).toHaveClass("ew-focusable", "ew-skip-link");
  });

  it("keeps a caller's class", () => {
    render(<SkipLink className="probe" />);
    expect(screen.getByRole("link")).toHaveClass("probe");
  });
});
