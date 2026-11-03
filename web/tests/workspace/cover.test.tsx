import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CoverTile } from "@/components/workspace/CoverTile";
import { coverMonogram, coverSeed, coverSource } from "@/lib/workspace/cover";

describe("cover tiles", () => {
  it("uses FNV-1a and distributes patterns deterministically", () => {
    expect(coverSeed("")).toBe(2166136261);
    expect(coverSeed("hello")).toBe(1335831723);
    expect(coverSeed("研究")).toBe(coverSeed("研究"));
    expect(new Set(Array.from({ length: 100 }, (_, n) => coverSeed(`work-${n}`) % 6)).size).toBe(6);
    const { container, rerender } = render(<CoverTile work_id="work-1" title="A study of agents" source_id="arxiv:cs.LG" />);
    const cover = container.firstElementChild!;
    const hash = coverSeed("work-1");
    expect(cover).toHaveAttribute("aria-hidden", "true");
    expect(cover).toHaveAttribute("data-pattern", String(hash % 6));
    expect(cover).toHaveAttribute("data-turn", String((hash >>> 3) % 4));
    expect(cover).toHaveAttribute("data-invert", String((hash >>> 5) % 2));
    expect(cover).toHaveTextContent("cs.LG");
    expect(cover).toHaveTextContent("SA");
    rerender(<CoverTile work_id="work-1" title="A study of agents" source_id="arxiv:cs.LG" />);
    expect(container.firstElementChild).toHaveAttribute("data-pattern", String(hash % 6));
  });
  it("extracts Unicode words around punctuation and stop words", () => {
    expect(coverMonogram("The café: a 世界 of agents")).toBe("C世");
    expect(coverMonogram("the and")).toBe("TA");
    expect(coverMonogram("...!")).toBe("");
    expect(coverSource("arxiv-cs-lg")).toBe("cs.LG");
    expect(coverSource("arxiv")).toBe("ARXIV");
    expect(coverSource("research-blog")).toBe("BLOG");
  });
});
