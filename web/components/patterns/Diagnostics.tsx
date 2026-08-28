"use client";

/**
 * Diagnostics — the disclosure that replaces `EventLog` (03 §4.5, WO-16).
 *
 * READ THE LIVE REGION FIRST (criterion 1). `role="log"` is on a WRAPPER
 * `<div aria-live="polite">` that contains a `<table>`. It is not on the
 * list, because there is no list: `components/EventLog.tsx:32-40` puts
 * `role="log"` on a `<ul>` whose children are `<li>` elements carrying a
 * three-column grid, and axe fails that twice — `aria-allowed-role`,
 * because `log` is not an allowed role for `ul`, and `listitem`, because
 * those `li`s are then inside an element that is no longer a list. Both
 * rules fail in plan-review, failed-partial and cancelled
 * (`docs/revamp/baseline/axe/plan-review.json`). A `div` takes `log`
 * legitimately, and a `table` inside it is a real table.
 *
 * COLLAPSED BY DEFAULT (criterion 2). The panel is `hidden` while closed,
 * so the live region is not in the accessibility tree and routine SSE
 * frames are not announced — which is the whole reason 03 §7.3 tolerates a
 * third live region at all. `defaultOpen` exists for the stories and for a
 * reader who has opened it; nothing in the product passes `true`.
 *
 * THE TRIGGER CARRIES NO COUNT, on purpose. Putting the retained-records
 * line on the button would make its accessible name change on every frame;
 * the line lives inside the panel, where it is content rather than a name.
 *
 * VERBATIM IS THE RENDERING RULE (criterion 3, H11). Event names, node
 * labels and `state_delta` keys are printed exactly as they arrived. There
 * is no name vocabulary, no key allow-list and no lookup that can miss:
 * `detailPairs` walks `Object.entries` and `formatDetailValue` never
 * throws, so `unknown_event_name.jsonl` and `unknown_state_delta_keys.jsonl`
 * render rather than blank.
 *
 * THE TABLE PANS, THE PAGE DOES NOT (criterion 4). The table sits in a
 * `ScrollRegion` — `overflow-x: auto`, `tabindex="0"`, `role="region"` and
 * a required non-empty name — so at 320px the columns scroll inside their
 * own box. The baseline's `grid-cols-[5.5rem_10rem_1fr]` is fixed at every
 * width and pushes the document instead.
 *
 * NO STRINGS OF ITS OWN. Every word comes from `@/lib/copy/diagnostics` —
 * one file, this surface's own, so a route that renders the disclosure does
 * not pull the whole dictionary into its chunk — and `copy/no-inline-text`
 * makes that structural for this directory. The only literals below are
 * class names, ARIA values, one `=` and the two wire-identifier keys in
 * `detailPairs`, which are field names for the same reason
 * `rawErrorEvidence()`'s labels are (RC-16): the reader is about to quote
 * them.
 *
 * PROPS ONLY, NO HOOKS THAT FETCH. Every state is reachable by passing
 * `records`, so the five stories need no MSW, no network and no
 * `JobRunProvider` (04 §5.1). WO-20 supplies the props from
 * `lib/diagnostics/useDiagnostics.ts`.
 */

import { useState, type ReactNode } from "react";

import { Button } from "@/components/primitives/Button";
import { Disclosure } from "@/components/primitives/Disclosure";
import { ScrollRegion } from "@/components/primitives/ScrollRegion";
import { VISUALLY_HIDDEN_CLASS } from "@/components/primitives/VisuallyHidden";
import {
  DIAGNOSTICS,
  DIAGNOSTICS_ACTIONS,
  DIAGNOSTICS_KIND_LABEL,
  DIAGNOSTICS_TABLE,
  DIAGNOSTICS_VITALS,
  diagnosticsDropped,
  diagnosticsRetained,
} from "@/lib/copy/diagnostics";
import { NOT_REPORTED, type RawEvidenceRow } from "@/lib/copy/errors";
// The capacity comes from `constants`, not from `ring`: a value import of
// the buffer would put a class no story exercises into the Storybook
// project's coverage graph. See lib/diagnostics/constants.ts.
import { RING_CAPACITY } from "@/lib/diagnostics/constants";
import type { DiagnosticRecord } from "@/lib/diagnostics/ring";

/** Between a detail key and its value. Punctuation, not copy. */
const PAIR_SEPARATOR = "=";

/** What the copy control is doing. Not a live region; see `COPY_MESSAGE`. */
type CopyState = "idle" | "busy" | "done" | "failed";

/**
 * What the control says before and after it has been used.
 *
 * Deliberately NOT a live region. 03 §7.3 allows exactly two product-wide —
 * the spine's `role="status"` and the failure `role="alert"` — and a third
 * one announcing "Copied to the clipboard" would interrupt a screen-reader
 * user with the outcome of an action they just took. At rest the line is
 * `copyNote`, which states what the blob does and does not contain, so the
 * promise is made before the button is pressed rather than after.
 */
const COPY_MESSAGE: Record<CopyState, string> = {
  idle: DIAGNOSTICS.copyNote,
  busy: DIAGNOSTICS.copyNote,
  done: DIAGNOSTICS.copied,
  failed: DIAGNOSTICS_ACTIONS.copyFailed,
};

// ---------------------------------------------------------------------------
// Formatting. Pure, exported, and tested directly.
// ---------------------------------------------------------------------------

/**
 * `HH:MM:SS.mmm`, in UTC.
 *
 * UTC rather than `toLocaleTimeString`, which is what `EventLog.tsx:57-60`
 * uses, for two reasons that both matter here: a value pasted into an issue
 * is only comparable with a server log if the zone is fixed, and a
 * locale-dependent string makes the test for this row depend on the machine
 * that runs it. A timestamp that is not a time reads "not reported" rather
 * than `Invalid Date` (03 §5.5).
 */
export function formatRecordTime(at: number): string {
  const date = new Date(at);
  if (Number.isNaN(date.getTime())) return NOT_REPORTED;
  return date.toISOString().slice(11, 23);
}

/** One detail value, printed. Never throws, whatever arrived. */
export function formatDetailValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    // A circular or otherwise unserializable payload. The frame still
    // happened and still belongs in the table.
    return String(value);
  }
}

function isRecordValue(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The `key=value` pairs a record's Detail cell renders.
 *
 * `state_delta` is flattened one level on purpose: it is the open scalar
 * map of H11, and its keys are the thing a reader is looking for. Every
 * other value is printed as it is, nested objects included.
 */
export function detailPairs(
  record: DiagnosticRecord,
): { key: string; value: string }[] {
  const pairs: { key: string; value: string }[] = [];
  if (record.from !== null) pairs.push({ key: "from", value: record.from });
  if (record.failureKind !== null) {
    pairs.push({ key: "failure_kind", value: record.failureKind });
  }
  for (const [key, value] of Object.entries(record.detail ?? {})) {
    if (key === "state_delta" && isRecordValue(value)) {
      for (const [inner, entry] of Object.entries(value)) {
        pairs.push({ key: inner, value: formatDetailValue(entry) });
      }
      continue;
    }
    pairs.push({ key, value: formatDetailValue(value) });
  }
  return pairs;
}

/** The library's rating word, spelled out, or the raw word if it is new. */
export function ratingWord(rating: unknown): string {
  if (typeof rating !== "string") return NOT_REPORTED;
  return Object.hasOwn(DIAGNOSTICS_VITALS.rating, rating)
    ? DIAGNOSTICS_VITALS.rating[rating as keyof typeof DIAGNOSTICS_VITALS.rating]
    : rating;
}

/** The metric's long name, or its raw name if `web-vitals` adds one. */
export function metricWord(name: string): string {
  return Object.hasOwn(DIAGNOSTICS_VITALS.metric, name)
    ? DIAGNOSTICS_VITALS.metric[name as keyof typeof DIAGNOSTICS_VITALS.metric]
    : name;
}

// ---------------------------------------------------------------------------
// Component.
// ---------------------------------------------------------------------------

export interface DiagnosticsProps {
  /** Oldest first, straight off the ring. */
  records: readonly DiagnosticRecord[];
  /** The ring's ceiling, for the retained line. */
  capacity?: number;
  /** How many the ring has already dropped. */
  dropped?: number;
  /**
   * `?debug=perf` (criterion 7). `false` hides the vitals block entirely —
   * not disabled, not empty: absent.
   */
  showVitals?: boolean;
  /** `rawErrorEvidence()`'s labelled rows — RC-16's "one disclosure away". */
  evidence?: readonly RawEvidenceRow[];
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /**
   * Where the redacted JSON goes. Defaults to the clipboard.
   *
   * A seam rather than a mock: jsdom has no `navigator.clipboard`, and a
   * story must not need one.
   */
  onCopy?: (json: string) => void | Promise<void>;
  id?: string;
  className?: string;
}

export function Diagnostics({
  records,
  capacity = RING_CAPACITY,
  dropped = 0,
  showVitals = false,
  evidence,
  defaultOpen = false,
  open,
  onOpenChange,
  onCopy,
  id,
  className,
}: DiagnosticsProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");

  const frames = records.filter((entry) => entry.kind !== "vital");
  const vitals = records.filter((entry) => entry.kind === "vital");
  const droppedLine = diagnosticsDropped(dropped);
  const evidenceRows = evidence ?? [];

  async function handleCopy(): Promise<void> {
    setCopyState("busy");
    try {
      // Imported HERE, not at module scope. The redactor is only needed by
      // a reader who presses the button, so it stays out of the route's
      // first-load JS — and out of the story graph, which keeps the
      // Storybook project from inflating this module's coverage
      // denominator (vitest.config.mts's measurement-hazard note).
      const { diagnosticsJson } = await import("@/lib/diagnostics/redact");
      const json = diagnosticsJson({ records, capacity, dropped });
      if (onCopy !== undefined) await onCopy(json);
      else await navigator.clipboard.writeText(json);
      setCopyState("done");
    } catch {
      setCopyState("failed");
    }
  }

  return (
    <Disclosure
      id={id}
      className={className}
      label={DIAGNOSTICS.label}
      defaultOpen={defaultOpen}
      open={open}
      onOpenChange={onOpenChange}
      panelClassName="flex flex-col gap-3"
    >
      <p className="text-ui-xs text-ink-muted">
        {diagnosticsRetained(records.length, capacity)}
      </p>

      {droppedLine === null ? null : (
        <p className="text-ui-xs text-ink-muted">{droppedLine}</p>
      )}

      {evidenceRows.length === 0 ? null : (
        <dl className="flex flex-col gap-1">
          {evidenceRows.map((row) => (
            <div key={row.label} className="flex flex-wrap gap-2">
              <dt className="font-mono text-mono-sm text-ink-muted">{row.label}</dt>
              <dd
                className="break-words font-mono text-mono-sm text-ink"
                data-present={row.present ? "true" : "false"}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {/*
        THE LIVE REGION (criterion 1). The role and the politeness are on
        this div; the table is its content. Nothing else in this component
        carries a live-region role, and 03 §7.3's other two — the spine's
        role="status" and the failure role="alert" — are elsewhere.
      */}
      <div
        role="log"
        aria-live="polite"
        aria-label={DIAGNOSTICS.logLabel}
        data-record-count={records.length}
      >
        <ScrollRegion
          label={DIAGNOSTICS_TABLE.scrollLabel}
          axis="both"
          className="max-h-96 rounded-md border border-border-subtle bg-sunken"
        >
          <table className="w-max min-w-full border-collapse text-left">
            <caption className={VISUALLY_HIDDEN_CLASS}>
              {DIAGNOSTICS_TABLE.caption}
            </caption>
            <thead>
              <tr className="border-b border-border-subtle">
                <ColumnHeader>{DIAGNOSTICS_TABLE.columns.time}</ColumnHeader>
                <ColumnHeader>{DIAGNOSTICS_TABLE.columns.event}</ColumnHeader>
                <ColumnHeader>{DIAGNOSTICS_TABLE.columns.detail}</ColumnHeader>
              </tr>
            </thead>
            <tbody>
              {frames.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-3 py-3 text-ui-sm text-ink-muted">
                    {DIAGNOSTICS.empty}
                  </td>
                </tr>
              ) : (
                frames.map((entry) => (
                  <tr
                    key={entry.seq}
                    data-kind={entry.kind}
                    data-event={entry.event}
                    className="border-b border-border-subtle align-baseline last:border-b-0"
                  >
                    <td className="whitespace-nowrap px-3 py-1 font-mono text-mono-xs text-ink-muted">
                      {formatRecordTime(entry.at)}
                    </td>
                    <td className="px-3 py-1">
                      <span className="block text-mono-xs text-ink-muted">
                        {DIAGNOSTICS_KIND_LABEL[entry.kind]}
                      </span>
                      <span className="font-mono text-mono-sm text-ink">
                        {entry.event}
                      </span>
                    </td>
                    <td className="px-3 py-1">
                      <span className="flex flex-wrap gap-x-3 gap-y-1">
                        {detailPairs(entry).map((pair) => (
                          <span
                            key={pair.key}
                            className="font-mono text-mono-xs text-ink"
                          >
                            <span className="text-ink-muted">{pair.key}</span>
                            <span className="text-ink-muted">{PAIR_SEPARATOR}</span>
                            {pair.value}
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </ScrollRegion>
      </div>

      {!showVitals ? null : (
        // A plain div with a heading, NOT a `<section aria-labelledby>`: a
        // named section is a `region` landmark, and this block is content
        // inside a disclosure rather than a navigable area of the page. The
        // two `region`s in this component are the two ScrollRegions, which
        // are regions because they are focusable scroll containers.
        <div className="flex flex-col gap-2">
          <h3 className="text-ui-sm font-medium text-ink">
            {DIAGNOSTICS_VITALS.label}
          </h3>
          <p className="text-ui-xs text-ink-muted">{DIAGNOSTICS_VITALS.note}</p>
          {vitals.length === 0 ? (
            <p className="text-ui-sm text-ink-muted">{DIAGNOSTICS_VITALS.empty}</p>
          ) : (
            <ScrollRegion
              label={DIAGNOSTICS_VITALS.scrollLabel}
              className="rounded-md border border-border-subtle bg-sunken"
            >
              <table className="w-max min-w-full border-collapse text-left">
                <caption className={VISUALLY_HIDDEN_CLASS}>
                  {DIAGNOSTICS_VITALS.label}
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle">
                    <ColumnHeader>{DIAGNOSTICS_VITALS.columns.metric}</ColumnHeader>
                    <ColumnHeader>{DIAGNOSTICS_VITALS.columns.value}</ColumnHeader>
                    <ColumnHeader>{DIAGNOSTICS_VITALS.columns.rating}</ColumnHeader>
                  </tr>
                </thead>
                <tbody>
                  {vitals.map((entry) => (
                    <tr
                      key={entry.seq}
                      data-metric={entry.event}
                      className="border-b border-border-subtle last:border-b-0"
                    >
                      <th
                        scope="row"
                        className="whitespace-nowrap px-3 py-1 text-ui-sm font-normal text-ink"
                      >
                        {metricWord(entry.event)}
                      </th>
                      <td className="whitespace-nowrap px-3 py-1 font-mono text-mono-sm text-ink">
                        {formatDetailValue(entry.detail?.["value"])}
                        {formatDetailValue(entry.detail?.["unit"] ?? "")}
                      </td>
                      <td className="whitespace-nowrap px-3 py-1 text-ui-sm text-ink-muted">
                        {ratingWord(entry.detail?.["rating"])}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            void handleCopy();
          }}
          busy={copyState === "busy"}
        >
          {copyState === "busy" ? DIAGNOSTICS_ACTIONS.copying : DIAGNOSTICS.copyAction}
        </Button>
        <p className="text-ui-xs text-ink-muted" data-copy-state={copyState}>
          {COPY_MESSAGE[copyState]}
        </p>
      </div>
    </Disclosure>
  );
}

function ColumnHeader({ children }: { children: ReactNode }) {
  return (
    <th
      scope="col"
      className="whitespace-nowrap px-3 py-1 text-ui-xs font-medium text-ink-muted"
    >
      {children}
    </th>
  );
}
