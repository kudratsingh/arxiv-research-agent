import { afterEach, describe, expect, it } from "vitest";

import {
  VISUALLY_HIDDEN_CLASS,
  VisuallyHidden,
} from "@/components/primitives/VisuallyHidden";
import { render, screen } from "../support/render";
import { installStylesheet, readWebFile, stripComments } from "./support/css";

const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));

const sheets: HTMLStyleElement[] = [];
afterEach(() => {
  while (sheets.length > 0) sheets.pop()?.remove();
});

describe("VisuallyHidden", () => {
  it("renders a span by default", () => {
    render(<VisuallyHidden>Opens in a new tab</VisuallyHidden>);
    const element = screen.getByText("Opens in a new tab");
    expect(element.tagName).toBe("SPAN");
    expect(element).toHaveClass(VISUALLY_HIDDEN_CLASS);
  });

  it.each(["div", "p", "h1", "h2", "h3", "h4", "h5", "h6", "legend"] as const)(
    "renders as a %s when asked",
    (tag) => {
      render(<VisuallyHidden as={tag}>Thread list</VisuallyHidden>);
      expect(screen.getByText("Thread list").tagName).toBe(tag.toUpperCase());
    },
  );

  it("stays in the accessibility tree", () => {
    // The whole point: clipped, never `aria-hidden`, never `display: none`.
    render(<VisuallyHidden as="h2">Thread list</VisuallyHidden>);
    expect(screen.getByRole("heading", { name: "Thread list", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("Thread list")).not.toHaveAttribute("aria-hidden");
  });

  it("can be referenced by id", () => {
    render(<VisuallyHidden id="hint">Markdown</VisuallyHidden>);
    expect(document.getElementById("hint")).toHaveTextContent("Markdown");
  });

  it("keeps a caller's class alongside its own", () => {
    render(<VisuallyHidden className="probe">Markdown</VisuallyHidden>);
    expect(screen.getByText("Markdown")).toHaveClass(VISUALLY_HIDDEN_CLASS, "probe");
  });

  it("is clipped to a single pixel and taken out of the flow", () => {
    sheets.push(installStylesheet(PRIMITIVES_CSS));
    render(<VisuallyHidden>Markdown</VisuallyHidden>);

    const style = getComputedStyle(screen.getByText("Markdown"));
    expect(style.position).toBe("absolute");
    expect(style.width).toBe("1px");
    expect(style.height).toBe("1px");
    expect(style.overflow).toBe("hidden");
  });

  it("clips with both the deprecated and the current mechanism", () => {
    // jsdom's CSSOM does not implement `clip` or `clip-path` as computed
    // values — it reports `auto` for both regardless of the cascade — so
    // this half is asserted against the authored rule. A user agent that
    // honours only the deprecated property still clips.
    const rule = /\.ew-visually-hidden\s*\{([^}]*)\}/.exec(PRIMITIVES_CSS)?.[1] ?? "";
    expect(rule).toMatch(/clip:\s*rect\(0 0 0 0\)/);
    expect(rule).toMatch(/clip-path:\s*inset\(50%\)/);
  });

  it("does not use display:none, which would remove it from the tree", () => {
    sheets.push(installStylesheet(PRIMITIVES_CSS));
    render(<VisuallyHidden>Markdown</VisuallyHidden>);
    expect(getComputedStyle(screen.getByText("Markdown")).display).not.toBe("none");
  });
});
