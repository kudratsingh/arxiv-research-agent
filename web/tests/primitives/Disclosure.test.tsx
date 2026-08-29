/**
 * Criterion 5, second clause: "`Disclosure` uses `aria-expanded` on a real
 * `<button>`". "Real" is doing work in that sentence — a `<div role="button">`
 * would satisfy a role query and fail on Space, on form participation and on
 * the browser's own focus handling, so the element type is asserted directly.
 */

import { describe, expect, it, vi } from "vitest";

import { Disclosure } from "@/components/primitives/Disclosure";
import { render, screen, user } from "../support/render";
import { installStylesheet, readWebFile, ruleBody, stripComments } from "./support/css";

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

/**
 * WO-27 criterion 7 — the regression test for a defect the manual pass found
 * and that no automated gate could see.
 *
 * WHAT WENT WRONG. `hidden` hides through the user-agent stylesheet's
 * `[hidden] { display: none }`. The cascade resolves ORIGIN before
 * specificity, so any author declaration of `display` — including a one-class
 * utility — beats it outright. `Diagnostics` passes `panelClassName="flex
 * flex-col gap-3"`, so its panel was displayed while its trigger reported
 * `aria-expanded="false"`: the controls inside it were in the tab order, and
 * its `role="log" aria-live="polite"` region was live, which made it a third
 * announcing live region where 03 §7.3 allows two.
 *
 * WHY NOTHING CAUGHT IT. axe has no rule for "aria-expanded disagrees with
 * what is displayed", so WO-22's sweep and WO-27's full matrix were both
 * green over it in two themes at three widths. The tests above assert the
 * `hidden` ATTRIBUTE, which was present and correct the whole time. It took
 * pressing Tab and watching where focus went.
 *
 * WHY THIS TEST IS SHAPED LIKE THIS. The `unit` project runs with
 * `css: false`, so the component's own `import "./primitives.css"` is a
 * no-op; `installStylesheet` puts the committed bytes into the document the
 * way `support/css.ts` documents. The Tailwind utility is written out here
 * because Tailwind generates it at build time and there is no file to read it
 * from — it is one declaration, `display: flex`, and it is the whole of what
 * the caller contributed.
 */
describe("Disclosure — a closed panel stays closed under a caller's layout class", () => {
  const PRIMITIVES_CSS = readWebFile("components/primitives/primitives.css");

  function withStylesheets<T>(run: () => T): T {
    const utility = installStylesheet(".flex { display: flex; }");
    const primitives = installStylesheet(PRIMITIVES_CSS);
    try {
      return run();
    } finally {
      primitives.remove();
      utility.remove();
    }
  }

  it("computes display:none for a hidden panel whose caller passed `flex`", () => {
    withStylesheets(() => {
      render(
        <Disclosure label="Technical events" panelClassName="flex flex-col gap-3">
          42 frames
        </Disclosure>,
      );
      const trigger = screen.getByRole("button", { name: "Technical events" });
      const panel = document.getElementById(
        trigger.getAttribute("aria-controls") as string,
      );
      expect(panel).not.toBeNull();
      expect(trigger).toHaveAttribute("aria-expanded", "false");
      expect(
        panel === null ? "" : getComputedStyle(panel).display,
        "the panel is displayed while its trigger says `aria-expanded=false`. " +
          "`.ew-disclosure-panel[hidden]` in primitives.css is what keeps a " +
          "caller's `display` utility from un-hiding it.",
      ).toBe("none");
    });
  });

  it("still lays the panel out with the caller's class once it is open", () => {
    withStylesheets(() => {
      render(
        <Disclosure label="Technical events" panelClassName="flex flex-col gap-3" defaultOpen>
          42 frames
        </Disclosure>,
      );
      const panel = document.getElementById(
        screen.getByRole("button", { name: "Technical events" }).getAttribute(
          "aria-controls",
        ) as string,
      );
      // The other direction: the fix must not turn `panelClassName` into a
      // no-op. An open panel is still whatever the caller asked for.
      expect(panel === null ? "" : getComputedStyle(panel).display).toBe("flex");
    });
  });

  it("carries the hook the rule is keyed on, on every panel", () => {
    render(<Disclosure label="Technical events">42 frames</Disclosure>);
    const panel = document.getElementById(
      screen.getByRole("button", { name: "Technical events" }).getAttribute(
        "aria-controls",
      ) as string,
    );
    expect(
      panel?.className,
      "the rule in primitives.css is keyed on `.ew-disclosure-panel`, so a " +
        "panel that stops carrying the class silently loses the fix.",
    ).toContain("ew-disclosure-panel");
  });

  it("declares the rule at a specificity a single utility class cannot beat", () => {
    // Read the committed bytes rather than trusting the computed result
    // above: jsdom's cascade is not Chromium's, and the property this
    // depends on — (0,2,0) over (0,1,0) — is a fact about the selector.
    const css = stripComments(PRIMITIVES_CSS);
    expect(css).toContain(".ew-disclosure-panel[hidden]");
    expect(ruleBody(css, ".ew-disclosure-panel[hidden]")).toContain("display: none");
  });
});
