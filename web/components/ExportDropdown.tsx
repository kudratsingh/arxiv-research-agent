"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";

interface ExportDropdownProps {
  jobId: string;
}

type ExportFormat = { format: string; label: string };

const FORMATS: ExportFormat[] = [
  { format: "md", label: "Markdown (.md)" },
  { format: "pdf", label: "PDF (.pdf)" },
  { format: "docx", label: "Word (.docx)" },
];

/**
 * Small popover with three download links. Uses vanilla anchor tags
 * pointing at the export endpoint; the server's Content-Disposition
 * header triggers the browser download. No JavaScript fetch is
 * needed, which keeps the download semantics identical to a
 * "right-click, save as" from the docs page.
 *
 * Closes on outside click and on Escape — the usual dropdown
 * ergonomics.
 */
export default function ExportDropdown({ jobId }: ExportDropdownProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (evt: MouseEvent) => {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(evt.target as Node)) {
        setOpen(false);
      }
    };
    const onEscape = (evt: KeyboardEvent) => {
      if (evt.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  const href = (fmt: string) =>
    `${API_BASE}/research/${encodeURIComponent(jobId)}/export?format=${fmt}`;

  return (
    <div ref={rootRef} className="relative inline-block text-left">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="inline-flex items-center gap-1 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        Export
        <span aria-hidden className="text-xs">
          &#9662;
        </span>
      </button>
      {open && (
        <ul
          role="menu"
          className="absolute right-0 z-10 mt-1 w-44 overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg dark:border-slate-700 dark:bg-slate-900"
        >
          {FORMATS.map(({ format, label }) => (
            <li key={format} role="none">
              <a
                role="menuitem"
                href={href(format)}
                download
                onClick={() => setOpen(false)}
                className="block px-3 py-2 text-sm text-slate-700 hover:bg-slate-100 focus:bg-slate-100 focus:outline-none dark:text-slate-200 dark:hover:bg-slate-800 dark:focus:bg-slate-800"
              >
                {label}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
