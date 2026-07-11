import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QueryForm from "@/components/QueryForm";

describe("QueryForm", () => {
  it("renders the query textarea and submit button", () => {
    render(
      <QueryForm onSubmit={vi.fn()} busy={false} jobId={null} error={null} />
    );
    expect(screen.getByLabelText(/research question/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /run research/i })
    ).toBeInTheDocument();
  });

  it("disables submit while busy", () => {
    render(
      <QueryForm onSubmit={vi.fn()} busy={true} jobId={null} error={null} />
    );
    const button = screen.getByRole("button", { name: /running…/i });
    expect(button).toBeDisabled();
  });

  it("disables submit when query is empty", () => {
    render(
      <QueryForm onSubmit={vi.fn()} busy={false} jobId={null} error={null} />
    );
    expect(
      screen.getByRole("button", { name: /run research/i })
    ).toBeDisabled();
  });

  it("calls onSubmit with the trimmed query on submit", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <QueryForm onSubmit={onSubmit} busy={false} jobId={null} error={null} />
    );
    const textarea = screen.getByLabelText(/research question/i);
    await user.type(textarea, "  hallucination mitigation  ");
    await user.click(screen.getByRole("button", { name: /run research/i }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith("hallucination mitigation");
  });

  it("shows the job id when provided", () => {
    render(
      <QueryForm
        onSubmit={vi.fn()}
        busy={true}
        jobId="abc123"
        error={null}
      />
    );
    expect(screen.getByText(/job abc123/)).toBeInTheDocument();
  });

  it("renders errors as an alert", () => {
    render(
      <QueryForm
        onSubmit={vi.fn()}
        busy={false}
        jobId={null}
        error="submit failed"
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("submit failed");
  });

  it("does not submit when query is only whitespace", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <QueryForm onSubmit={onSubmit} busy={false} jobId={null} error={null} />
    );
    await user.type(screen.getByLabelText(/research question/i), "   ");
    // Button is disabled — nothing should fire.
    expect(
      screen.getByRole("button", { name: /run research/i })
    ).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
