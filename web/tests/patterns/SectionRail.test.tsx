/**
 * WO-18 criterion 4 — the section rail on its own.
 *
 * `ReportReader.test.tsx` proves the rail is DERIVED from rendered headings.
 * This file proves the rail itself: that an empty list produces no chrome at
 * all, that the tag is the level, that exactly one entry can be current, and
 * that the current one is not distinguished by colour alone (03 §3.4).
 *
 * The states here are the ones the reader group cannot reach — which is the
 * criterion's own reason for making `SectionRail/` a second story group.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SectionRail, type ReportHeading } from "@/components/patterns/SectionRail";
import { REPORT } from "@/lib/copy/report";

import {
  customProperties,
  installStylesheet,
  readWebFile,
  resolveComputed,
  stripComments,
} from "../primitives/support/css";
import { render, screen, within } from "../support/render";

const HEADINGS: ReportHeading[] = [
  { id: "what-the-field-measures", text: "What the field measures", level: 2 },
  { id: "automatic-metrics", text: "Automatic metrics", level: 3 },
  { id: "human-protocols", text: "Human protocols", level: 3 },
  { id: "limits", text: "Limits", level: 2 },
];

describe("absent, not empty-shelled", () => {
  it("renders nothing at all for a heading-free report", () => {
    const { container } = render(<SectionRail headings={[]} label={REPORT.railLabel} />);

    expect(container.innerHTML).toBe("");
    expect(screen.queryByRole("navigation")).toBeNull();
    // Not a hidden shell either: there is no node to hide.
    expect(container.querySelector("nav, ol, li")).toBeNull();
  });

  it("renders as soon as there is one heading", () => {
    render(<SectionRail headings={[HEADINGS[0] as ReportHeading]} label={REPORT.railLabel} />);

    const rail = screen.getByRole("navigation", { name: REPORT.railLabel });
    expect(within(rail).getAllByRole("link")).toHaveLength(1);
    expect(rail).toHaveAttribute("data-heading-count", "1");
  });
});

describe("the list is the document's own structure", () => {
  it("names itself from the dictionary and lists the headings in order", () => {
    render(<SectionRail headings={HEADINGS} label={REPORT.railLabel} />);

    const rail = screen.getByRole("navigation", { name: REPORT.railLabel });
    expect(within(rail).getAllByRole("link").map((link) => link.textContent)).toEqual([
      "What the field measures",
      "Automatic metrics",
      "Human protocols",
      "Limits",
    ]);
    // An ordered list, because a briefing's sections are in an order.
    expect(rail.querySelector("ol")).not.toBeNull();
  });

  it("carries the tag as the level, so nesting is reported and not inferred", () => {
    const { container } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} />,
    );

    expect(
      Array.from(container.querySelectorAll("li")).map((item) =>
        item.getAttribute("data-level"),
      ),
    ).toEqual(["2", "3", "3", "2"]);
  });

  it("links to the fragment the heading carries, and nothing else", () => {
    render(<SectionRail headings={HEADINGS} label={REPORT.railLabel} />);

    const rail = screen.getByRole("navigation", { name: REPORT.railLabel });
    expect(
      within(rail).getAllByRole("link").map((link) => link.getAttribute("href")),
    ).toEqual([
      "#what-the-field-measures",
      "#automatic-metrics",
      "#human-protocols",
      "#limits",
    ]);
  });

  it("keeps every link keyboard-reachable under the one focus policy", () => {
    const { container } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} />,
    );

    for (const link of Array.from(container.querySelectorAll("a"))) {
      expect(link.className).toContain("ew-focusable");
    }
  });
});

describe("the current section", () => {
  it("marks exactly one entry, and only when one is named", () => {
    const { container, rerender } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} />,
    );
    expect(container.querySelectorAll("[aria-current]")).toHaveLength(0);

    rerender(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} activeId="human-protocols" />,
    );
    const current = container.querySelectorAll('[aria-current="location"]');
    expect(current).toHaveLength(1);
    expect(current[0]?.textContent).toBe("Human protocols");
  });

  it("marks nothing when the active id is not one of the headings", () => {
    const { container } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} activeId="not-a-section" />,
    );

    expect(container.querySelectorAll("[aria-current]")).toHaveLength(0);
  });
});

describe("the current section is never colour alone (03 §3.4)", () => {
  const tokensCss = readWebFile("app/tokens.css");
  const tokens = customProperties(tokensCss);
  let sheet: HTMLStyleElement;

  beforeEach(() => {
    sheet = installStylesheet(tokensCss);
  });

  afterEach(() => {
    sheet.remove();
  });

  it("adds a rule and a weight, not just a hue", () => {
    const { container } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} activeId="limits" />,
    );

    const current = container.querySelector(
      '[aria-current="location"]',
    ) as HTMLElement;
    const other = container.querySelector("a:not([aria-current])") as HTMLElement;

    expect(resolveComputed(current, "font-weight", tokens)).toBe("600");
    expect(resolveComputed(other, "font-weight", tokens)).not.toBe("600");
    expect(resolveComputed(current, "border-left-color", tokens)).toBe(
      resolveComputed(document.documentElement, "--color-signature", tokens),
    );
    // cssstyle normalises `transparent` into a functional notation, which
    // web/tests/tokens.test.ts's repository-wide scan would read as a
    // literal colour if it were typed here. Probing for it keeps the
    // assertion exact and the file free of colour values.
    const probe = document.createElement("div");
    probe.style.borderLeftColor = "transparent";
    document.body.append(probe);
    const transparent = getComputedStyle(probe).getPropertyValue("border-left-color");
    probe.remove();

    expect(resolveComputed(other, "border-left-color", tokens)).toBe(transparent);
    expect(resolveComputed(other, "border-left-width", tokens)).toBe(
      resolveComputed(current, "border-left-width", tokens),
    );
  });

  it("is set in the chrome family, never the report one", () => {
    const layers = (stack: string): string => stack.replace(/\s*,\s*/g, ",").trim();
    const { container } = render(
      <SectionRail headings={HEADINGS} label={REPORT.railLabel} />,
    );
    const rail = container.querySelector(".ew-section-rail") as HTMLElement;

    expect(layers(resolveComputed(rail, "font-family", tokens))).toBe(
      layers(tokens.get("--font-ui") as string),
    );
  });

  it("becomes the sticky side column only at the width 03 §7.5 gives it", () => {
    // jsdom evaluates no width media query, so the rule is read rather than
    // computed — but it is read out of the committed sheet, not restated.
    const stripped = stripComments(tokensCss);
    const media = stripped.slice(stripped.indexOf("@media (min-width: 1280px)"));

    expect(media).toContain(".ew-section-rail");
    expect(media).toContain("position: sticky");
    // Below that width it is an ordinary block in the flow, ahead of the
    // briefing — a table of contents after the document indexes nothing.
    expect(stripped).toMatch(/\.ew-section-rail\s*\{[^}]*flex:\s*1 1 100%/);
  });
});
