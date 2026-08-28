import { describe, expect, it, vi } from "vitest";

import { Textarea } from "@/components/primitives/Textarea";
import { render, screen, user } from "../support/render";

describe("Textarea", () => {
  it("associates the label with the control", () => {
    render(<Textarea label="Research question" />);
    expect(screen.getByLabelText("Research question")).toBeInstanceOf(HTMLTextAreaElement);
  });

  it("shows no counter without a limit", () => {
    render(<Textarea label="Research question" defaultValue="hello" />);
    expect(screen.queryByText(/\/\s*\d+/)).toBeNull();
    expect(screen.getByLabelText("Research question")).not.toHaveAttribute(
      "aria-describedby",
    );
  });

  it("counts a controlled value against the limit", () => {
    render(<Textarea label="Research question" value="12345" limit={10} readOnly />);
    expect(screen.getByText(/5 \/ 10/)).toBeInTheDocument();
  });

  it("counts an uncontrolled value as it is typed", async () => {
    render(<Textarea label="Research question" limit={10} />);
    expect(screen.getByText(/0 \/ 10/)).toBeInTheDocument();
    await user().type(screen.getByLabelText("Research question"), "abc");
    expect(screen.getByText(/3 \/ 10/)).toBeInTheDocument();
  });

  it("states the refusal in a word rather than truncating the value", () => {
    render(<Textarea label="Research question" value="abcdefghijkl" limit={10} readOnly />);
    const textarea = screen.getByLabelText("Research question");
    // Nothing was cut: the value is longer than the limit and still whole.
    expect(textarea).toHaveValue("abcdefghijkl");
    expect(textarea).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByText("Over the limit:")).toHaveClass("ew-visually-hidden");
  });

  it("warns before it refuses", () => {
    const { container } = render(
      <Textarea label="Research question" value="123456789" limit={10} readOnly />,
    );
    const counter = container.querySelector(".text-review-text");
    expect(counter).toHaveTextContent("9 / 10");
    expect(screen.getByLabelText("Research question")).not.toHaveAttribute("aria-invalid");
  });

  it("moves the warning threshold when asked", () => {
    const { container } = render(
      <Textarea
        label="Research question"
        value="12345"
        limit={10}
        nearLimitRatio={0.5}
        readOnly
      />,
    );
    expect(container.querySelector(".text-review-text")).toHaveTextContent("5 / 10");
  });

  it("describes the control with the hint, the counter and the error, in order", () => {
    render(
      <Textarea
        label="Research question"
        hint="One question at a time."
        limit={10}
        value=""
        readOnly
        error="Enter a question."
      />,
    );
    const ids = (
      screen.getByLabelText("Research question").getAttribute("aria-describedby") ?? ""
    )
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent);
    expect(ids).toEqual(["One question at a time.", "0 / 10", "Error:Enter a question."]);
  });

  it("does not make the counter or the error a live region", () => {
    render(<Textarea label="Research question" limit={10} error="Enter a question." />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("still calls the caller's onChange when uncontrolled", async () => {
    const onChange = vi.fn();
    render(<Textarea label="Research question" limit={10} onChange={onChange} />);
    await user().type(screen.getByLabelText("Research question"), "ab");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("lets a caller opt into native truncation explicitly", async () => {
    render(<Textarea label="Research question" maxLength={2} />);
    const textarea = screen.getByLabelText("Research question");
    await user().type(textarea, "abcd");
    expect(textarea).toHaveValue("ab");
  });
});
