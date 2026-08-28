/**
 * Criterion 7: "`StatusBadge` renders word + mark + colour, in that
 * precedence; a test asserts the word survives with colour removed."
 *
 * "Survives with colour removed" is tested twice, in the two ways colour
 * actually goes away: the author's classes stripped (a stylesheet that
 * failed to load, a print sheet, a reader mode) and every severity's hue
 * collapsed onto one keyword (a forced-colours user agent, reproduced here
 * from .storybook/preview.css's own emulation). Neither takes a word or a
 * shape with it.
 */

import { describe, expect, it, vi } from "vitest";

import { STATUS_MARKS } from "@/components/primitives/marks";
import { SEVERITY_MARK, StatusBadge } from "@/components/primitives/StatusBadge";
import { STATUS_SEVERITY_ROLE, type StatusSeverity } from "@/lib/tokens";
import { render, screen } from "../support/render";

const SEVERITIES = Object.keys(STATUS_SEVERITY_ROLE) as StatusSeverity[];

describe("StatusBadge", () => {
  it("renders the word", () => {
    render(<StatusBadge severity="live">Live</StatusBadge>);
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("renders a mark that is hidden from assistive technology", () => {
    const { container } = render(<StatusBadge severity="live">Live</StatusBadge>);
    const mark = container.querySelector("svg");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveAttribute("focusable", "false");
  });

  it("refuses to render without a word", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<StatusBadge severity="live">{""}</StatusBadge>)).toThrow(
      /the word is required/,
    );
    error.mockRestore();
  });

  it.each(SEVERITIES)("maps %s onto the role web/lib/tokens.ts assigns it", (severity) => {
    const { container } = render(<StatusBadge severity={severity}>Word</StatusBadge>);
    // The severity → role mapping is RC-17's and lives in the token module;
    // this component may not invent a second one.
    expect(container.firstElementChild).toHaveAttribute(
      "data-role",
      STATUS_SEVERITY_ROLE[severity],
    );
    expect(container.firstElementChild).toHaveAttribute("data-severity", severity);
  });

  it("gives review and warning the same hue and different shapes", () => {
    // RC-17: the palette ships no `warning` colour, so the shape and the
    // word are what separate the two severities.
    expect(STATUS_SEVERITY_ROLE.warning).toBe(STATUS_SEVERITY_ROLE.review);
    expect(SEVERITY_MARK.warning).not.toBe(SEVERITY_MARK.review);
  });

  it("gives every severity a mark no other severity uses", () => {
    const marks = SEVERITIES.map((severity) => SEVERITY_MARK[severity]);
    expect(new Set(marks).size).toBe(marks.length);
  });

  it.each(STATUS_MARKS)("draws the %s mark", (mark) => {
    const { container } = render(
      <StatusBadge severity="info" mark={mark}>
        Word
      </StatusBadge>,
    );
    const drawn = container.querySelector(`[data-mark="${mark}"]`);
    expect(drawn).not.toBeNull();
    // A shape, not an empty box: every mark draws at least one child.
    expect((drawn as SVGElement).children.length).toBeGreaterThan(0);
  });

  it("keeps the word and the mark when every class is stripped", () => {
    const { container } = render(
      <StatusBadge severity="critical" emphasis="surface">
        Failed
      </StatusBadge>,
    );

    // Colour lives entirely in the class list. Remove it from the badge and
    // from everything inside it, and see what is left.
    for (const element of container.querySelectorAll("*")) element.removeAttribute("class");
    container.firstElementChild?.removeAttribute("class");

    expect(container).toHaveTextContent("Failed");
    expect(container.querySelector('[data-mark="slashed-square"]')).not.toBeNull();
  });

  it("keeps every severity distinguishable when the hues collapse onto one", () => {
    // What a forced-colours user agent does, and what
    // .storybook/preview.css emulates: signature, review and critical all
    // become CanvasText. If the word and the mark were not carrying the
    // state, five severities would become one.
    const rendered = SEVERITIES.map((severity) => {
      const { container } = render(
        <StatusBadge severity={severity} mark={SEVERITY_MARK[severity]}>
          {`the ${severity} word`}
        </StatusBadge>,
      );
      return {
        word: container.textContent,
        mark: container.querySelector("[data-mark]")?.getAttribute("data-mark"),
      };
    });

    expect(new Set(rendered.map((entry) => entry.word)).size).toBe(SEVERITIES.length);
    expect(new Set(rendered.map((entry) => entry.mark)).size).toBe(SEVERITIES.length);
  });

  it("pulses only when the severity is live and the caller asked", () => {
    const live = render(
      <StatusBadge severity="live" ambient>
        Live
      </StatusBadge>,
    );
    expect(live.container.querySelector(".ew-pulse")).not.toBeNull();

    const still = render(<StatusBadge severity="live">Live</StatusBadge>);
    expect(still.container.querySelector(".ew-pulse")).toBeNull();

    const review = render(
      <StatusBadge severity="review" ambient>
        Waiting for your review
      </StatusBadge>,
    );
    // `ambient` on a non-live severity is ignored: 03 §3.7 allows the
    // receiving indicator only while a stream is open.
    expect(review.container.querySelector(".ew-pulse")).toBeNull();
  });

  it("adds a bordered chip only in the surface emphasis", () => {
    const quiet = render(<StatusBadge severity="info">Queued</StatusBadge>);
    expect(quiet.container.firstElementChild).not.toHaveClass("border");

    const surface = render(
      <StatusBadge severity="info" emphasis="surface">
        Queued
      </StatusBadge>,
    );
    expect(surface.container.firstElementChild).toHaveClass("border");
  });

  it("is not a live region", () => {
    render(<StatusBadge severity="live">Live</StatusBadge>);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
