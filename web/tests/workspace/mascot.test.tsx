import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Mascot } from "@/components/workspace/Mascot";

describe("Jazzy", () => {
  it.each(["idle", "busy", "sleepy", "alert"] as const)("renders %s as decorative separate parts", (mood) => {
    const { container } = render(<Mascot mood={mood} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("data-mood", mood);
    expect(svg.querySelectorAll("path")).toHaveLength(8);
    for (const part of ["body", "shade", "highlight", "whites", "pupils", "mouth", "closed", "alert-pupils"]) {
      expect(svg.querySelector(`.ws-mascot-${part}`)).toHaveAttribute("d", expect.any(String));
    }
    expect(svg.querySelector(".ws-mascot-eyes .ws-mascot-whites")).not.toBeNull();
    expect(svg.querySelector(".ws-mascot-eyes .ws-mascot-pupils")).not.toBeNull();
    expect(svg.querySelector(".ws-mascot-mouth")?.closest(".ws-mascot-eyes")).toBeNull();
    expect(svg.querySelector("style, text")).toBeNull();
  });
});
