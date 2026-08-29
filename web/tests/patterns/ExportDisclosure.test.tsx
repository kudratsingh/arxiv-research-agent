/**
 * WO-19 criteria 3, 4, 5 and 6 — the export disclosure.
 *
 * NOTHING IN THIS FILE CLICKS A DOWNLOAD LINK, and that is deliberate rather
 * than a gap. 05-MIGRATION.md B3 records the hazard: jsdom has no download
 * implementation, so activating an `<a download href="/api/…">` logs "Not
 * implemented: navigation" and asserts nothing about what a browser would
 * do. So the unit tier asserts what it can see honestly — the `href` and the
 * `download` attribute, criterion 6's first clause — and the real downloads
 * for `md`, `pdf` and `docx` with `content-disposition` intact are
 * `web/e2e/export.spec.ts` in the chromium project (criterion 6's second
 * clause, WO-21).
 *
 * The keyboard block is criterion 3's "a keyboard test covers open,
 * arrow/tab traversal, Escape, and focus restore", one `it` per clause.
 */

import { describe, expect, it, vi } from "vitest";

import {
  EXPORT_FORMATS,
  EXPORT_PROXY_BASE,
  ExportDisclosure,
  exportHref,
} from "@/components/patterns/ExportDisclosure";
import { API_BASE } from "@/lib/api";
import { EXPORT } from "@/lib/copy/exports";
import { BRIEFING } from "@/lib/copy/run";

import { render, screen, user, within } from "../support/render";

const JOB_ID = "baseline-succeeded";

/** The trigger, which is the whole control when the panel is closed. */
const trigger = (): HTMLElement => screen.getByRole("button", { name: EXPORT.label });

/** The three links, in document order. Empty while the panel is closed. */
const links = (): HTMLElement[] => screen.queryAllByRole("link");

// ===========================================================================
// Criterion 3 — a real button, over three real links.
// ===========================================================================

describe("criterion 3 — the shape", () => {
  it("is a real <button> carrying aria-expanded, not a role", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);

    const button = trigger();
    expect(button.tagName).toBe("BUTTON");
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the closed panel out of the accessibility tree", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    expect(links()).toHaveLength(0);

    // Hidden rather than unmounted, so `aria-controls` never dangles.
    const panel = document.getElementById(
      trigger().getAttribute("aria-controls") as string,
    );
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");
  });

  it("opens onto three links, and never onto a menu", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    await user().click(trigger());

    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(links().map((link) => link.textContent)).toEqual([
      EXPORT.markdown,
      EXPORT.pdf,
      EXPORT.word,
    ]);

    // `ExportDropdown.tsx:66-77` announces role="menu"/"menuitem" and then
    // behaves as a list. RC-09 and 03 §4.8 replace it with the honest shape.
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.queryAllByRole("menuitem")).toHaveLength(0);
  });

  it("reports every open and close to its caller", async () => {
    const onOpenChange = vi.fn();
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing onOpenChange={onOpenChange} />);

    await user().click(trigger());
    expect(onOpenChange).toHaveBeenLastCalledWith(true);
    await user().click(trigger());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
  });

  it("opens from defaultOpen without an interaction", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(links()).toHaveLength(3);
  });

  it("takes a caller-supplied trigger id, and still restores focus to it", async () => {
    // The id is what Escape's focus restore finds, so a supplied one has to
    // work as well as the generated one.
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen id="export-trigger" />);
    expect(trigger()).toHaveAttribute("id", "export-trigger");

    (links()[0] as HTMLElement).focus();
    await user().keyboard("{Escape}");
    expect(trigger()).toHaveFocus();
  });
});

// ===========================================================================
// Criterion 6, first clause — the anchors themselves (B3).
// ===========================================================================

describe("criterion 6 — href and download", () => {
  it("points every link at the same-origin proxy, with the format in the query", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);

    expect(links().map((link) => link.getAttribute("href"))).toEqual([
      "/api/research/baseline-succeeded/export?format=md",
      "/api/research/baseline-succeeded/export?format=pdf",
      "/api/research/baseline-succeeded/export?format=docx",
    ]);
  });

  it("carries a bare download attribute, so the server names the file", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);

    for (const link of links()) {
      expect(link).toHaveAttribute("download");
      // RC-12: a value here would override the upstream Content-Disposition
      // (`src/api/routes.py:385`) and rename the export from the client.
      expect(link.getAttribute("download")).toBe("");
    }
  });

  it("never leaves the origin, whatever the id contains", () => {
    render(<ExportDisclosure jobId="a b/../etc?x=1#y" hasBriefing defaultOpen />);

    for (const link of links()) {
      const href = link.getAttribute("href") as string;
      // R-08: an absolute URL here would be the browser talking to the API
      // directly, which is how the server-only key stops being server-only.
      expect(href.startsWith(`${EXPORT_PROXY_BASE}/research/`)).toBe(true);
      expect(new URL(href, "https://example.invalid").origin).toBe("https://example.invalid");
    }
  });

  it("builds the same string the data layer would", () => {
    // The one duplicated constant in this component, pinned. See its note:
    // importing `@/lib/api` for a five-character prefix would put the whole
    // client into the Storybook project's module graph.
    expect(EXPORT_PROXY_BASE).toBe(API_BASE);
    expect(exportHref("a b", "md")).toBe("/api/research/a%20b/export?format=md");
    expect(EXPORT_FORMATS).toEqual(["md", "pdf", "docx"]);
  });

  /**
   * WO-31's RC-03 equivalence table, closing a narrowing.
   *
   * `tests/ExportDropdown.test.tsx › URL-encodes the job_id path segment`
   * split the href on `/` and asserted the id stayed ONE segment:
   * `["", "api", "research", "a%20b%2F1", "export"]`. The space-only case
   * above does not reach that claim — a `/` in the id would silently become
   * a path separator and the same-origin test would still pass, because a
   * traversal is still same-origin. The encoder is correct
   * (`ExportDisclosure.tsx:99`); this is what makes it checkable.
   */
  it("keeps the job id in one path segment, whatever it contains", () => {
    const href = exportHref("a b/1", "md");
    expect(href).toBe("/api/research/a%20b%2F1/export?format=md");
    expect(new URL(href, "https://example.invalid").pathname.split("/")).toEqual([
      "",
      "api",
      "research",
      "a%20b%2F1",
      "export",
    ]);
  });
});

// ===========================================================================
// Criterion 3, second clause — the keyboard.
// ===========================================================================

describe("criterion 3 — the keyboard", () => {
  it("opens on Enter and on Space, because a real button does", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    trigger().focus();

    await user().keyboard("{Enter}");
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    await user().keyboard(" ");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("opens on ArrowDown from the closed trigger and lands on the first link", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    trigger().focus();

    await user().keyboard("{ArrowDown}");
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(links()[0]).toHaveFocus();
  });

  it("opens on ArrowUp from the closed trigger and lands on the last", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    trigger().focus();

    await user().keyboard("{ArrowUp}");
    expect(links()[2]).toHaveFocus();
  });

  it("walks the list with the arrow keys, and wraps at both ends", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);
    const [markdown, pdf, word] = links();

    (markdown as HTMLElement).focus();
    await user().keyboard("{ArrowDown}");
    expect(pdf).toHaveFocus();
    await user().keyboard("{ArrowDown}");
    expect(word).toHaveFocus();
    // Wrapping, so a three-item list does not make the user reverse.
    await user().keyboard("{ArrowDown}");
    expect(markdown).toHaveFocus();
    await user().keyboard("{ArrowUp}");
    expect(word).toHaveFocus();
  });

  it("is reachable by Tab as well, because these are ordinary links", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing />);
    trigger().focus();

    await user().keyboard("{Enter}");
    await user().tab();
    expect(links()[0]).toHaveFocus();
    await user().tab();
    expect(links()[1]).toHaveFocus();
  });

  it("closes on Escape and puts focus back on the trigger", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);
    (links()[1] as HTMLElement).focus();

    await user().keyboard("{Escape}");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(trigger()).toHaveFocus();
  });

  /**
   * WO-31's RC-03 equivalence table, discharging a retirement nothing pinned.
   *
   * `tests/ExportDropdown.test.tsx › closes the menu when an item is clicked`
   * asserted `role="menu"` was gone after a click, because close-on-select is
   * a WAI-ARIA MENU behaviour. RC-09 replaced the menu with a disclosure of
   * `<a download>` links, and a disclosure has no activation-dismisses-the-
   * container contract — nor should it here, where taking the Markdown copy
   * and then the PDF is one intent, and a panel that closed under the cursor
   * would make the second one a re-open.
   *
   * So the behaviour is deliberately INVERTED rather than replaced, and it
   * was unpinned in both directions until this test: nothing asserted the
   * panel closed, and nothing asserted it stayed open either. Escape and the
   * trigger remain the two ways out, and the tests either side of this one
   * are them.
   */
  it("stays open when a format is taken, so a second one needs no re-open", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);

    await user().click(links()[0] as HTMLElement);

    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    expect(links()).toHaveLength(EXPORT_FORMATS.length);
  });

  it("closes on Escape pressed on the trigger itself", async () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);
    trigger().focus();

    await user().keyboard("{Escape}");
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    expect(trigger()).toHaveFocus();
  });

  it("lets Escape through when there is nothing to dismiss", async () => {
    const onEscape = vi.fn();
    render(
      // A surrounding dialog must still close on Escape when this panel is
      // already shut; only an OPEN panel consumes the key.
      <div onKeyDown={(event) => event.key === "Escape" && onEscape()}>
        <ExportDisclosure jobId={JOB_ID} hasBriefing />
      </div>,
    );

    trigger().focus();
    await user().keyboard("{Escape}");
    expect(onEscape).toHaveBeenCalledTimes(1);

    await user().keyboard("{Enter}");
    await user().keyboard("{Escape}");
    // Consumed this time: the user was dismissing the panel, not the dialog.
    expect(onEscape).toHaveBeenCalledTimes(1);
  });
});

// ===========================================================================
// Criteria 4 and 5 — when the control exists at all.
// ===========================================================================

describe("criterion 4 — absent, not disabled-and-silent", () => {
  it("renders nothing at all when there is no briefing", () => {
    const { container } = render(<ExportDisclosure jobId={JOB_ID} hasBriefing={false} />);

    expect(container).toBeEmptyDOMElement();
    // Not a disabled button, which would be a control that explains nothing.
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names the cause inline when a 409 still comes back", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing refused />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(EXPORT.refused);
    // The control goes: the server has said there is nothing to export, and
    // offering the links beside the explanation would contradict it.
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the refusal even when the client still thinks a briefing exists", () => {
    render(<ExportDisclosure jobId={JOB_ID} hasBriefing refused />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});

describe("criterion 5 — a failed run keeps its export", () => {
  /**
   * The strongest form of this criterion is a fact about the component's
   * API, not about a rendering: there is no `status` prop and no way to pass
   * one. `export_research` gates on a falsy `result` and does not look at
   * status (`src/api/routes.py:364-368`), so a run that failed with a
   * briefing retained is indistinguishable here from one that succeeded —
   * which is exactly what D-010 ruling 2 asks for.
   */
  it("offers the same three links for a failed run's retained briefing", () => {
    render(<ExportDisclosure jobId="baseline-failed-partial" hasBriefing defaultOpen />);

    expect(links()).toHaveLength(3);
    expect(links()[0]).toHaveAttribute(
      "href",
      "/api/research/baseline-failed-partial/export?format=md",
    );
  });
});

// ===========================================================================
// The dictionary is the single edit site (WO-12 criterion 1).
// ===========================================================================

describe("copy", () => {
  it("uses WO-12's words, character for character", () => {
    expect(EXPORT.label).toBe(BRIEFING.exportLabel);
    expect(EXPORT.markdown).toBe(BRIEFING.exportMarkdown);
    expect(EXPORT.pdf).toBe(BRIEFING.exportPdf);
    expect(EXPORT.refused).toBe(BRIEFING.exportRefused);
  });

  it("renders no word of its own", () => {
    const { container } = render(<ExportDisclosure jobId={JOB_ID} hasBriefing defaultOpen />);
    const panel = within(container).getByRole("group", { name: EXPORT.label });

    expect(panel.textContent).toBe(`${EXPORT.markdown}${EXPORT.pdf}${EXPORT.word}`);
  });
});
