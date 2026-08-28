/**
 * Criterion 6: "`ScrollRegion` renders `overflow-x:auto` + `tabindex="0"` +
 * `role="region"` with a required accessible name; a test fails when the
 * name is omitted."
 *
 * The last clause is the one worth reading. TypeScript makes `label`
 * required, but a type is not a test — a `label` computed from data can
 * still arrive empty at runtime, which is the case where the defect
 * actually ships. So the component throws, and the tests below are the ones
 * that fail if it ever stops.
 */

import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ScrollRegion } from "@/components/primitives/ScrollRegion";
import { render, screen } from "../support/render";
import { installStylesheet, readWebFile, stripComments } from "./support/css";

const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));

const sheets: HTMLStyleElement[] = [];
afterEach(() => {
  while (sheets.length > 0) sheets.pop()?.remove();
});

describe("ScrollRegion", () => {
  it("renders a named region", () => {
    render(
      <ScrollRegion label="Retrieval metrics table, scrollable">
        <p>rows</p>
      </ScrollRegion>,
    );
    expect(
      screen.getByRole("region", { name: "Retrieval metrics table, scrollable" }),
    ).toBeInTheDocument();
  });

  it("is a tab stop, so the pan is reachable from the keyboard", () => {
    render(<ScrollRegion label="Rows">rows</ScrollRegion>);
    const region = screen.getByRole("region", { name: "Rows" });
    expect(region).toHaveAttribute("tabindex", "0");
    region.focus();
    expect(region).toHaveFocus();
  });

  it("pans horizontally", () => {
    sheets.push(installStylesheet(PRIMITIVES_CSS));
    render(<ScrollRegion label="Rows">rows</ScrollRegion>);
    const style = getComputedStyle(screen.getByRole("region", { name: "Rows" }));
    expect(style.overflowX).toBe("auto");
    // The page must not pan with it: the region is capped at its container.
    expect(style.maxWidth).toBe("100%");
  });

  it("pans in both directions when asked", () => {
    render(
      <ScrollRegion label="Diagnostics frames" axis="both">
        rows
      </ScrollRegion>,
    );
    expect(screen.getByRole("region", { name: "Diagnostics frames" })).toHaveClass(
      "overflow-y-auto",
    );
  });

  it("carries the shared focus class, so the tab stop is visible", () => {
    render(<ScrollRegion label="Rows">rows</ScrollRegion>);
    expect(screen.getByRole("region", { name: "Rows" })).toHaveClass("ew-focusable");
  });

  it.each([
    ["an empty string", ""],
    ["whitespace", "   "],
  ])("fails when the name is %s", (_description, label) => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<ScrollRegion label={label}>rows</ScrollRegion>)).toThrow(
      /label is required and must be non-empty/,
    );
    error.mockRestore();
  });

  it("fails when the name is omitted entirely", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    // The cast is the point: this is what a JavaScript caller, or a caller
    // whose data did not arrive, actually hands the component.
    const Unlabelled = ScrollRegion as unknown as (props: {
      children: string;
    }) => ReactElement;
    expect(() => render(<Unlabelled>rows</Unlabelled>)).toThrow(
      /label is required and must be non-empty/,
    );
    error.mockRestore();
  });

  it("accepts an id and extra classes", () => {
    render(
      <ScrollRegion label="Rows" id="metrics" className="max-h-40">
        rows
      </ScrollRegion>,
    );
    const region = screen.getByRole("region", { name: "Rows" });
    expect(region).toHaveAttribute("id", "metrics");
    expect(region).toHaveClass("max-h-40");
  });

  it("renders its children unchanged", () => {
    render(
      <ScrollRegion label="Rows">
        <table>
          <tbody>
            <tr>
              <td>cell</td>
            </tr>
          </tbody>
        </table>
      </ScrollRegion>,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
