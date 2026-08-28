// 05-MIGRATION.md B3: this file used to click a menu item and let jsdom try
// to follow the download link, which printed
// `Not implemented: navigation to another Document` on every clean run.
//
// jsdom has no download machinery, so the click proved nothing about the
// download — it only proved the anchor was clickable. What the component is
// actually responsible for is the *resolved* `href` and the `download`
// attribute the browser acts on, so that is what is asserted here, against
// `HTMLAnchorElement.href` (absolute, as the browser resolves it) rather than
// the raw attribute string. Real download verification — the response, its
// `Content-Disposition`, the saved file — belongs to the Playwright tier,
// where a browser exists to do it.

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ExportDropdown from "@/components/ExportDropdown";

/** The menu items, typed as the anchors they are. */
function menuAnchors(): HTMLAnchorElement[] {
  return screen.getAllByRole("menuitem") as HTMLAnchorElement[];
}

/** Absolute URL the browser would request for `jobId`/`format`. */
function expectedHref(jobId: string, format: string): string {
  return new URL(
    `/api/research/${encodeURIComponent(jobId)}/export?format=${format}`,
    window.location.origin
  ).href;
}

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

  it("menu items resolve to the three export URLs the browser would fetch", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc123" />);
    await user.click(screen.getByRole("button", { name: /export/i }));

    // `.href` is the resolved absolute URL, which is what the browser
    // requests — an assertion on the raw attribute would still pass if the
    // component started emitting a relative path that resolved elsewhere.
    expect(menuAnchors().map((anchor) => anchor.href)).toEqual([
      expectedHref("abc123", "md"),
      expectedHref("abc123", "pdf"),
      expectedHref("abc123", "docx"),
    ]);
  });

  it("marks every menu item as a download, not a navigation", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="abc123" />);
    await user.click(screen.getByRole("button", { name: /export/i }));

    for (const anchor of menuAnchors()) {
      // Bare `download`: present, and empty, so the filename comes from the
      // upstream `Content-Disposition` header rather than from the client.
      expect(anchor).toHaveAttribute("download", "");
      expect(anchor.download).toBe("");
    }
  });

  it("URL-encodes the job_id path segment", async () => {
    const user = userEvent.setup();
    render(<ExportDropdown jobId="a b/1" />);
    await user.click(screen.getByRole("button", { name: /export/i }));

    // Space and slash both get percent-encoded, and survive URL resolution:
    // a raw slash here would silently retarget the request at another route.
    const first = menuAnchors()[0]!;
    expect(first.href).toBe(expectedHref("a b/1", "md"));
    expect(first.href).toContain("/research/a%20b%2F1/export");

    // The job id stays ONE path segment and decodes back to what was passed
    // in: an unencoded slash would silently retarget the request at
    // `/api/research/a b/1/export`, which is a different route entirely.
    const segments = new URL(first.href).pathname.split("/");
    expect(segments).toEqual(["", "api", "research", "a%20b%2F1", "export"]);
    expect(decodeURIComponent(segments[3]!)).toBe("a b/1");
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

    // The click still has to happen — closing on select is the behaviour
    // under test — but its default action must not, or jsdom logs
    // `Not implemented: navigation to another Document` and the run is no
    // longer clean (B3). A real browser suppresses the navigation itself
    // because of the `download` attribute; jsdom does not implement that, so
    // the suppression is done here instead.
    const suppressNavigation = (event: Event): void => event.preventDefault();
    document.addEventListener("click", suppressNavigation, true);
    try {
      await user.click(menuAnchors()[0]!);
    } finally {
      document.removeEventListener("click", suppressNavigation, true);
    }

    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
