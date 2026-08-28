import { describe, expect, it, vi } from "vitest";

import { Field } from "@/components/primitives/Field";
import { render, screen, user } from "../support/render";

describe("Field", () => {
  it("associates the label with the control", () => {
    render(<Field label="Thread title" />);
    expect(screen.getByLabelText("Thread title")).toBeInstanceOf(HTMLInputElement);
  });

  it("keeps the name when the label is clipped", () => {
    render(<Field label="Search threads" labelHidden type="search" />);
    const input = screen.getByLabelText("Search threads");
    expect(input).toBeInTheDocument();
    // Clipped, not removed: the label element is still there.
    expect(screen.getByText("Search threads")).toHaveClass("ew-visually-hidden");
  });

  it("describes the control with its hint", () => {
    render(<Field label="Thread title" hint="80 characters or fewer." />);
    const input = screen.getByLabelText("Thread title");
    const hintId = input.getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId as string)).toHaveTextContent(
      "80 characters or fewer.",
    );
  });

  it("marks the control invalid and describes the error", () => {
    render(<Field label="Thread title" error="Enter a title before saving." />);
    const input = screen.getByLabelText("Thread title");
    expect(input).toHaveAttribute("aria-invalid", "true");
    const errorId = input.getAttribute("aria-describedby");
    expect(document.getElementById(errorId as string)).toHaveTextContent(
      "Enter a title before saving.",
    );
  });

  it("names the hint before the error, in reading order", () => {
    render(<Field label="Thread title" hint="Shown in the rail." error="Required." />);
    const ids = (screen.getByLabelText("Thread title").getAttribute("aria-describedby") ?? "")
      .split(" ")
      .map((id) => document.getElementById(id)?.textContent);
    expect(ids).toEqual(["Shown in the rail.", "Error:Required."]);
  });

  it("does not make the error a live region", () => {
    // 03 §7.3 allows exactly two live regions product-wide, and a field is
    // neither of them.
    render(<Field label="Thread title" error="Required." />);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("carries a mark and a clipped word beside the error, not colour alone", () => {
    const { container } = render(<Field label="Thread title" error="Required." />);
    expect(container.querySelector('[data-mark="slashed-square"]')).not.toBeNull();
    expect(screen.getByText("Error:")).toHaveClass("ew-visually-hidden");
  });

  it("does not describe the control when there is nothing to say", () => {
    render(<Field label="Thread title" />);
    expect(screen.getByLabelText("Thread title")).not.toHaveAttribute("aria-describedby");
    expect(screen.getByLabelText("Thread title")).not.toHaveAttribute("aria-invalid");
  });

  it("says required in the label and on the control", () => {
    render(<Field label="Thread title" required />);
    const input = screen.getByLabelText(/Thread title/);
    expect(input).toBeRequired();
    expect(screen.getByText("(required)")).toBeInTheDocument();
  });

  it("accepts a caller-supplied id", () => {
    render(<Field label="Thread title" id="thread-title" />);
    expect(screen.getByLabelText("Thread title")).toHaveAttribute("id", "thread-title");
  });

  it("disables without losing its name", () => {
    render(<Field label="Job id" disabled defaultValue="job_1" />);
    expect(screen.getByLabelText("Job id")).toBeDisabled();
  });

  it("types like an ordinary input", async () => {
    const onChange = vi.fn();
    render(<Field label="Thread title" onChange={onChange} />);
    await user().type(screen.getByLabelText("Thread title"), "abc");
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(screen.getByLabelText("Thread title")).toHaveValue("abc");
  });
});
