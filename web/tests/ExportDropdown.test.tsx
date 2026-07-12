import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExportDropdown from "@/components/ExportDropdown";

describe("ExportDropdown", () => {
  it("is collapsed by default and shows an Export button", () => {
    render(<ExportDropdown jobId="abc123" />);
    const button = screen.getByRole("button", { name: /export/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "false");
    // Menu shouldn't render before it's opened.
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens the menu on click with all three formats", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc123" />);
    await user.click(screen.getByRole("button", { name: /export/i }));
    const menu = screen.getByRole("menu");
    expect(menu).toBeInTheDocument();
    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent(/Markdown/);
    expect(items[1]).toHaveTextContent(/PDF/);
    expect(items[2]).toHaveTextContent(/Word/);
  });

  it("menu items are download anchors with correct hrefs", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc123" />);
    await user.click(screen.getByRole("button", { name: /export/i }));
    const items = screen.getAllByRole("menuitem");
    for (const item of items) {
      expect(item).toHaveAttribute("download");
    }
    expect(items[0]).toHaveAttribute(
      "href",
      expect.stringContaining("/research/abc123/export?format=md")
    );
    expect(items[1]).toHaveAttribute(
      "href",
      expect.stringContaining("/research/abc123/export?format=pdf")
    );
    expect(items[2]).toHaveAttribute(
      "href",
      expect.stringContaining("/research/abc123/export?format=docx")
    );
  });

  it("URL-encodes the job_id path segment", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="a b/1" />);
    await user.click(screen.getByRole("button", { name: /export/i }));
    const first = screen.getAllByRole("menuitem")[0];
    // Space and slash both get percent-encoded.
    expect(first).toHaveAttribute(
      "href",
      expect.stringContaining("/research/a%20b%2F1/export?format=md")
    );
  });

  it("closes the menu on Escape", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc" />);
    await user.click(screen.getByRole("button", { name: /export/i }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes the menu when an item is clicked", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc" />);
    await user.click(screen.getByRole("button", { name: /export/i }));
    await user.click(screen.getAllByRole("menuitem")[0]!);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
