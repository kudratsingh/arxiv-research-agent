"use client";

/**
 * ExportDisclosure — three download links behind one button (WO-19).
 *
 * A DISCLOSURE, NOT A MENU (03 §4.8, RC-09). `ExportDropdown.tsx:64-88` is a
 * `role="menu"` over `role="menuitem"` anchors with no roving focus, no
 * typeahead and no arrow keys — which is to say it announces itself as a
 * menu to a screen reader and then behaves as a list, the "half-built menu"
 * 01-RESEARCH.md names. This is the honest shape: a real `<button
 * aria-expanded>` from WO-07's `Disclosure`, and three ordinary links under
 * it. The arrow keys below are an ADDITION to Tab, not a replacement for it;
 * both reach every link, which is what a list of links has to do.
 *
 * THE LINKS ARE ANCHORS AND NOTHING FETCHES (RC-09, R-08). `<a download>`
 * pointing at the same-origin proxy is what makes the download work: the
 * browser saves the response because the UPSTREAM set `Content-Disposition:
 * attachment` (`src/api/routes.py:385`) and the route handler at
 * `web/app/api/[...path]/route.ts` passed the header through untouched. A
 * `fetch` + blob would take the credential path out of the server's hands
 * and hand the client the job of naming the file — which RC-12 says is not
 * ours to do.
 *
 * ABSENT, NOT DISABLED-AND-SILENT (criterion 4, 03 §2.2 row 23). With no
 * briefing there is nothing to export and the control does not render at
 * all. A disabled button would be a control that explains nothing, and a
 * present-but-apologetic one would put an error on screen before the user
 * has done anything. The 409 message is the other half of the same rule: it
 * appears only after an export attempt has actually been refused, and then
 * it names the cause rather than the status code.
 *
 * PRESENT ON A FAILED RUN (criterion 5, D-010 ruling 2, H5). This component
 * has no `status` prop and cannot acquire one: `export_research` gates on a
 * falsy `result` and does not look at status (`src/api/routes.py:364-368`),
 * so "was there a briefing" is the only question there is. A failed run that
 * wrote something is a run the user has already paid for.
 *
 * NO STRING IS WRITTEN IN THIS FILE — `lib/copy/exports` holds all four.
 */

import { useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { flushSync } from "react-dom";

import { Disclosure } from "@/components/primitives/Disclosure";
// primitives.css is imported for `ew-focusable` and `ew-target`: the links
// are the only focusable thing this file renders itself, and both policies
// have exactly one definition (WO-07). `Disclosure` imports it too; a
// stylesheet is idempotent, a dependency on somebody else's import is not.
import "@/components/primitives/primitives.css";
import { FOCUSABLE_CLASS, cx, targetClass } from "@/components/primitives/styles";
import { EXPORT } from "@/lib/copy/exports";

import "./export.css";

// ---------------------------------------------------------------------------
// The URL, and the one constant this file does not import.
// ---------------------------------------------------------------------------

/**
 * The proxy prefix, which is `API_BASE` (`lib/api/client.ts:29`) written a
 * second time on purpose.
 *
 * `import { API_BASE } from "@/lib/api"` is what `ExportDropdown.tsx:4`
 * does, and it is a five-character string behind a barrel that also exports
 * eight request functions, the error normaliser and the SSE event tables.
 * Two costs follow, and the second is the decisive one:
 *
 *   1. every byte of that module enters the route bundle for a component
 *      that needs a prefix; and
 *   2. `lib/api` enters the STORYBOOK project's module graph through this
 *      component's stories, and `web/vitest.config.mts` records what that
 *      does — a module both Vitest projects load has its function list
 *      CONCATENATED in the merged coverage report, and an early WO-12 draft
 *      that imported `@/lib/api` from a story drove the functions column
 *      from 94.7% to 85.08% without changing a line of product code.
 *
 * So it is declared here and `web/tests/patterns/ExportDisclosure.test.tsx`
 * asserts it is character-identical to `API_BASE`, in the unit project where
 * that module is already loaded and fully covered. The two cannot drift
 * without a red run — the same device `lib/copy/report.ts` uses for the five
 * strings it shares with `BRIEFING`.
 */
export const EXPORT_PROXY_BASE = "/api";

/** The three the backend accepts — `^(md|pdf|docx)$`, `routes.py:341-345`. */
export const EXPORT_FORMATS = ["md", "pdf", "docx"] as const;

export type ExportFormat = (typeof EXPORT_FORMATS)[number];

/**
 * One export link's `href`.
 *
 * `encodeURIComponent` on the id for the same reason `streamUrl` does it
 * (`lib/api/client.ts:231`): the id is data, and data goes in a path segment
 * encoded. Exported so the unit test can assert the string without going
 * through the DOM, and so WO-20 never rebuilds it by hand.
 */
export function exportHref(jobId: string, format: ExportFormat): string {
  return `${EXPORT_PROXY_BASE}/research/${encodeURIComponent(jobId)}/export?format=${format}`;
}

/** Label per format. The extension is in the filename, which is not ours. */
const FORMAT_LABEL: Record<ExportFormat, string> = {
  md: EXPORT.markdown,
  pdf: EXPORT.pdf,
  docx: EXPORT.word,
};

// ---------------------------------------------------------------------------
// The component.
// ---------------------------------------------------------------------------

export interface ExportDisclosureProps {
  /** The run whose briefing is exported. */
  jobId: string;
  /**
   * Whether a briefing exists. `false` renders nothing at all (criterion 4).
   * Status is deliberately not a prop — see the header.
   */
  hasBriefing: boolean;
  /**
   * Set once an export attempt has been refused with 409. Renders the
   * inline explanation in place of the control.
   */
  refused?: boolean;
  defaultOpen?: boolean;
  /** Fired on every open and close, including the ones Escape causes. */
  onOpenChange?: (open: boolean) => void;
  /** The trigger's id. Generated when absent. */
  id?: string;
  className?: string;
}

export function ExportDisclosure({
  jobId,
  hasBriefing,
  refused = false,
  defaultOpen = false,
  onOpenChange,
  id,
  className,
}: ExportDisclosureProps) {
  const generated = useId();
  const triggerId = id ?? `${generated}-export`;
  const listRef = useRef<HTMLUListElement>(null);

  /**
   * Uncontrolled on purpose, unlike the `Disclosure` primitive underneath.
   *
   * Escape has to close this component and put focus back on the trigger.
   * A controlled parent that ignored `onOpenChange` would leave the panel
   * open with focus already moved out of it, which is a worse state than
   * either of the two the prop was meant to select between. The parent is
   * still told what happened.
   */
  const [open, setOpen] = useState(defaultOpen);

  function change(next: boolean) {
    setOpen(next);
    onOpenChange?.(next);
  }

  function focusTrigger() {
    document.getElementById(triggerId)?.focus();
  }

  /**
   * Escape and the arrow keys, on the wrapper rather than on the document.
   *
   * React's synthetic events bubble through the React tree, so one handler
   * here sees keys pressed on the trigger AND on any link — without the two
   * `document` listeners `ExportDropdown.tsx:32-51` installs, and therefore
   * without a global Escape that would also fire for a dialog this control
   * happens to be inside.
   */
  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      if (!open) return;
      // Consumed: a surrounding dialog must not close because the user was
      // dismissing this panel.
      event.stopPropagation();
      event.preventDefault();
      change(false);
      focusTrigger();
      return;
    }

    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;

    const links = readLinks(listRef.current);
    if (links.length === 0) return;
    // Arrow keys scroll the page by default; here they are navigation.
    event.preventDefault();

    if (!open) {
      /**
       * `flushSync`, and not a state-plus-effect dance.
       *
       * The panel is `hidden` until the open state commits, and
       * `HTMLElement.focus()` on a hidden subtree does nothing at all — so
       * the link cannot be focused in this tick without forcing the render
       * first. The alternative is to record the intent in state and spend it
       * in an effect, which is a cascading render the
       * `react-hooks/set-state-in-effect` rule rejects and which React's own
       * documentation says to solve exactly this way: this is a DOM read
       * that must happen after a specific commit, inside an event handler,
       * which is where `flushSync` is legal and cheap.
       */
      flushSync(() => {
        change(true);
      });
      const opened = readLinks(listRef.current);
      opened[event.key === "ArrowDown" ? 0 : opened.length - 1]?.focus();
      return;
    }

    const current = links.indexOf(document.activeElement as HTMLAnchorElement);
    if (current === -1) {
      // Focus is on the trigger: enter the list at the end nearest the key.
      links[event.key === "ArrowDown" ? 0 : links.length - 1]?.focus();
      return;
    }

    // Wraps, because a three-item list that stops at both ends makes the
    // user reverse direction to reach the item they just passed.
    const step = event.key === "ArrowDown" ? 1 : -1;
    const next = (current + step + links.length) % links.length;
    links[next]?.focus();
  }

  // Criterion 4, both halves. The refusal wins over the control: a 409 is
  // the server saying there is nothing to export, so offering the links
  // again beside the explanation would contradict it.
  if (refused) {
    return (
      <p role="alert" className={cx("ew-export__refusal font-ui", className)}>
        {EXPORT.refused}
      </p>
    );
  }
  if (!hasBriefing) return null;

  return (
    <div
      onKeyDown={onKeyDown}
      data-export="true"
      className={cx("ew-export", className)}
    >
      <Disclosure
        id={triggerId}
        label={EXPORT.label}
        open={open}
        onOpenChange={change}
        panelClassName="ew-export__panel"
      >
        <ul ref={listRef} className="ew-export__list">
          {EXPORT_FORMATS.map((format) => (
            <li key={format}>
              <a
                href={exportHref(jobId, format)}
                // Bare, with no filename of our own: the browser then uses
                // the upstream Content-Disposition, which is the only place
                // the export's name is decided (RC-12).
                download
                data-export-link="true"
                data-format={format}
                className={cx("ew-export__link font-ui", FOCUSABLE_CLASS, targetClass("sm"))}
              >
                {FORMAT_LABEL[format]}
              </a>
            </li>
          ))}
        </ul>
      </Disclosure>
    </div>
  );
}

/** The panel's links, in document order. `[]` before the list mounts. */
function readLinks(list: HTMLUListElement | null): HTMLAnchorElement[] {
  return list === null ? [] : Array.from(list.querySelectorAll("a[data-export-link]"));
}
