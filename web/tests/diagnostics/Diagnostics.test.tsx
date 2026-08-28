/**
 * WO-16 criteria 1, 2, 3, 4, 6 and 7 — the surface.
 *
 * The half of this file that matters most is `describe("criterion 3")`. It
 * does not construct frames: it installs `FakeEventSource` with the two
 * recordings 03 §5.9 obliges the client to survive —
 * `web/contract/sse/unknown_event_name.jsonl` and
 * `unknown_state_delta_keys.jsonl` — mounts a real `JobRunProvider`, wires
 * the recorder to it exactly as WO-20 will, and replays the script. What
 * ends up on screen is what the machine really observed.
 *
 * That harness also proves the thing an inline fixture would have hidden.
 * `node_started` and `paper_indexed` are NAMED events, and a real
 * `EventSource` drops named events nobody registered a listener for — which
 * `lib/job/useJobStream.ts:413-417` says in as many words. So they never
 * reach the client at all, and the honest assertion is that the replay does
 * not throw and does not invent rows for them. The seam a future server
 * event actually arrives through is an UNNAMED `message` frame, which the
 * machine turns into `unknown_frame`; that path is driven here too, and its
 * payload renders verbatim.
 */

import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Diagnostics, detailPairs, formatDetailValue, formatRecordTime, metricWord, ratingWord } from "@/components/patterns/Diagnostics";
import { DIAGNOSTICS, DIAGNOSTICS_TABLE, DIAGNOSTICS_VITALS } from "@/lib/copy/diagnostics";
import { NOT_REPORTED, rawErrorEvidence } from "@/lib/copy/errors";
import { DiagnosticsRing, type DiagnosticRecord } from "@/lib/diagnostics/ring";
import {
  useDiagnosticsRecorder,
  useDiagnosticsRecords,
} from "@/lib/diagnostics/useDiagnostics";
import { JobRunProvider, useJobRun } from "@/lib/job/provider";
import type { JobClient } from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";

import {
  installFakeEventSource,
  onlySource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, render, screen, user, waitFor, within } from "../support/render";

const RUNNING = loadFixture("job.running").body as JobDetail;

const AT = Date.UTC(2026, 7, 28, 9, 14, 3, 120);

let seq = 0;

function record(
  overrides: Partial<DiagnosticRecord> & Pick<DiagnosticRecord, "kind" | "event">,
): DiagnosticRecord {
  const next = seq++;
  return {
    seq: next,
    at: AT + next,
    jobId: "baseline-running",
    phase: "live",
    from: null,
    failureKind: null,
    detail: null,
    ...overrides,
  };
}

beforeEach(() => {
  seq = 0;
});

// ---------------------------------------------------------------------------
// Criterion 1 — the live region.
// ---------------------------------------------------------------------------

describe("criterion 1 — role=log on a wrapper div, containing a table", () => {
  it("puts the role and the politeness on a div, not on the list", () => {
    render(<Diagnostics records={[record({ kind: "frame", event: "job_started" })]} defaultOpen />);

    const log = screen.getByRole("log");
    expect(log.tagName).toBe("DIV");
    expect(log).toHaveAttribute("aria-live", "polite");
    // The baseline's shape, gone: `role="log"` on a `<ul>` fails
    // `aria-allowed-role`, and its `<li>` children then fail `listitem`.
    expect(log.tagName).not.toBe("UL");
    expect(log.querySelector("ul")).toBeNull();
    expect(log.querySelector("li")).toBeNull();
  });

  it("contains a real table with the three columns 03 §4.5 names", () => {
    render(<Diagnostics records={[record({ kind: "frame", event: "job_started" })]} defaultOpen />);
    const table = within(screen.getByRole("log")).getByRole("table");
    const headers = within(table).getAllByRole("columnheader");
    expect(headers.map((header) => header.textContent)).toEqual([
      DIAGNOSTICS_TABLE.columns.time,
      DIAGNOSTICS_TABLE.columns.event,
      DIAGNOSTICS_TABLE.columns.detail,
    ]);
  });

  it("names the table with a clipped caption rather than a visible title", () => {
    render(<Diagnostics records={[]} defaultOpen />);
    const table = within(screen.getByRole("log")).getByRole("table");
    expect(table).toHaveAccessibleName(DIAGNOSTICS_TABLE.caption);
  });

  it("is the ONLY live region this component emits", () => {
    // 03 §7.3 allows exactly two others product-wide, and neither is here:
    // `role="status"` belongs to the spine and `role="alert"` to
    // user-triggered failures.
    const { container } = render(
      <Diagnostics
        records={[record({ kind: "frame", event: "job_started" })]}
        defaultOpen
        showVitals
        evidence={rawErrorEvidence("orphaned", "boom")}
      />,
    );
    expect(container.querySelectorAll("[role='status']")).toHaveLength(0);
    expect(container.querySelectorAll("[role='alert']")).toHaveLength(0);
    expect(container.querySelectorAll("[aria-live]")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// Criterion 2 — collapsed by default.
// ---------------------------------------------------------------------------

describe("criterion 2 — collapsed by default, so frames are not announced", () => {
  it("renders closed, with the panel hidden and the log out of the tree", () => {
    render(<Diagnostics records={[record({ kind: "frame", event: "job_started" })]} />);
    const trigger = screen.getByRole("button", { name: DIAGNOSTICS.label });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("log")).toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("opens on activation and closes again", async () => {
    const events = user();
    render(<Diagnostics records={[record({ kind: "frame", event: "job_started" })]} />);
    const trigger = screen.getByRole("button", { name: DIAGNOSTICS.label });

    await events.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("log")).toBeInTheDocument();

    await events.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("log")).toBeNull();
  });

  it("keeps the trigger's accessible name stable as records arrive", () => {
    // A count on the trigger would rename the control on every frame.
    const { rerender } = render(<Diagnostics records={[]} />);
    const name = screen.getByRole("button", { name: DIAGNOSTICS.label }).textContent;
    rerender(
      <Diagnostics
        records={Array.from({ length: 30 }, () => record({ kind: "frame", event: "f" }))}
      />,
    );
    expect(screen.getByRole("button", { name: DIAGNOSTICS.label }).textContent).toBe(name);
  });
});

// ---------------------------------------------------------------------------
// Criterion 3 — unknown names and unknown keys, from the recordings.
// ---------------------------------------------------------------------------

/** Nothing in this file may reach the one billable endpoint. */
function forbiddenSubmit(): never {
  throw new Error("POST /research must never be called from a unit test");
}

function client(): Partial<JobClient> {
  return {
    getJob: () => Promise.resolve(RUNNING),
    submitResearch: forbiddenSubmit,
    streamUrl: (jobId) => `/api/research/${jobId}/stream`,
  };
}

/** Exactly the wiring WO-20 will write, and nothing else. */
function Harness({ ring }: { ring: DiagnosticsRing }): ReactNode {
  const run = useJobRun();
  useDiagnosticsRecorder(run, ring);
  const records = useDiagnosticsRecords(ring);
  return createElement(Diagnostics, {
    records,
    capacity: ring.capacity,
    dropped: ring.dropped,
    defaultOpen: true,
    onCopy: () => undefined,
  });
}

function mount(ring: DiagnosticsRing) {
  return render(
    <JobRunProvider jobId="baseline-running" client={client()} poll={{ enabled: false }}>
      <Harness ring={ring} />
    </JobRunProvider>,
  );
}

describe("criterion 3 — the recordings, replayed through the harness", () => {
  let ring: DiagnosticsRing;

  beforeEach(() => {
    ring = new DiagnosticsRing();
  });

  afterEach(() => {
    uninstallFakeEventSource();
  });

  it("survives unknown_event_name.jsonl without throwing", async () => {
    installFakeEventSource({ script: "unknown_event_name" });
    mount(ring);
    await act(async () => {});
    await act(async () => {
      onlySource().playScript();
    });

    // The recording's two unrecognised names never reach the client: a
    // real EventSource drops named events nobody listens for, and the stub
    // reproduces that. Nothing throws, and no row is invented for them.
    const rows = screen.getAllByRole("row");
    const events = rows.map((row) => row.getAttribute("data-event"));
    expect(events).not.toContain("node_started");
    expect(events).not.toContain("paper_indexed");
    // What the recording DOES deliver is on screen, verbatim.
    expect(screen.getByText("job_started")).toBeInTheDocument();
    expect(screen.getByText("searcher")).toBeInTheDocument();
    expect(screen.getByText("papers_found")).toBeInTheDocument();
    expect(screen.getByText("9")).toBeInTheDocument();
  });

  it("renders unknown_state_delta_keys.jsonl verbatim, keys and all", async () => {
    installFakeEventSource({ script: "unknown_state_delta_keys" });
    mount(ring);
    await act(async () => {});
    await act(async () => {
      onlySource().playScript();
    });

    // A node label from no graph, and four delta keys from no vocabulary.
    expect(screen.getByText("claim_decomposer")).toBeInTheDocument();
    for (const key of [
      "planner_confidence",
      "sub_questions_count",
      "unreleased_feature_flag",
      "claims_extracted",
      "decomposition_strategy",
    ]) {
      expect(screen.getByText(key), key).toBeInTheDocument();
    }
    expect(screen.getByText("per-sentence")).toBeInTheDocument();
    // The empty delta is not a crash and not a missing row.
    const nodeRows = screen
      .getAllByRole("row")
      .filter((row) => row.getAttribute("data-event") === "node_completed");
    expect(nodeRows).toHaveLength(3);
  });

  it("renders an unnamed frame — the seam a future event arrives through", async () => {
    installFakeEventSource();
    mount(ring);
    await act(async () => {});
    await act(async () => {
      onlySource().emit("message", { future_field: "future_value", node: "unheard_of" });
    });

    const row = screen
      .getAllByRole("row")
      .find((entry) => entry.getAttribute("data-kind") === "frame");
    expect(row).toBeDefined();
    expect(within(row as HTMLElement).getByText("message")).toBeInTheDocument();
    expect(screen.getByText("future_field")).toBeInTheDocument();
    expect(screen.getByText("future_value")).toBeInTheDocument();
  });

  it("records the machine's own transitions beside the frames", async () => {
    installFakeEventSource({ script: "unknown_state_delta_keys" });
    mount(ring);
    await act(async () => {});
    await act(async () => {
      onlySource().playScript();
    });
    const kinds = new Set(
      screen.getAllByRole("row").map((row) => row.getAttribute("data-kind")),
    );
    expect(kinds.has("frame")).toBe(true);
    expect(kinds.has("transition")).toBe(true);
    expect(kinds.has("terminal")).toBe(true);
  });

  it("throws on nothing a malformed or hostile payload can be", () => {
    // The formatter is the last line of defence, so it is driven directly
    // with everything a payload can contain.
    const circular: Record<string, unknown> = {};
    circular["self"] = circular;
    expect(() => formatDetailValue(circular)).not.toThrow();
    expect(formatDetailValue(undefined)).toBe("undefined");
    expect(formatDetailValue(null)).toBe("null");
    expect(formatDetailValue(false)).toBe("false");
    expect(formatDetailValue(0)).toBe("0");
    expect(formatDetailValue("x")).toBe("x");
    expect(formatDetailValue([1, 2])).toBe("[1,2]");
    expect(formatDetailValue(() => 1)).toBe(String(() => 1));
  });
});

// ---------------------------------------------------------------------------
// Criterion 4 — the table pans, the page does not.
// ---------------------------------------------------------------------------

describe("criterion 4 — the table scrolls inside a labelled region", () => {
  it("wraps the table in a focusable, named ScrollRegion", () => {
    render(<Diagnostics records={[record({ kind: "frame", event: "job_started" })]} defaultOpen />);
    const region = screen.getByRole("region", { name: DIAGNOSTICS_TABLE.scrollLabel });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region.className).toContain("ew-scroll-region");
    expect(within(region).getByRole("table")).toBeInTheDocument();
  });

  it("keeps the region inside the log, so the announced content is the table", () => {
    render(<Diagnostics records={[]} defaultOpen />);
    const log = screen.getByRole("log");
    expect(
      within(log).getByRole("region", { name: DIAGNOSTICS_TABLE.scrollLabel }),
    ).toBeInTheDocument();
  });

  it("uses no fixed column track, which is the baseline's actual defect", () => {
    // `EventLog.tsx:40` sets `grid-cols-[5.5rem_10rem_1fr]` at every width,
    // so at 320px the three columns push the DOCUMENT sideways. The
    // `scrollWidth <= clientWidth` assertion at 320 / 360 / 412px is WO-08's
    // Playwright job (`ScrollRegion.tsx`'s header says so); what belongs
    // here is that the track is not fixed and the pan surface is present.
    const { container } = render(
      <Diagnostics records={[record({ kind: "frame", event: "job_started" })]} defaultOpen />,
    );
    expect(container.innerHTML).not.toMatch(/grid-cols-\[/);
    const region = screen.getByRole("region", { name: DIAGNOSTICS_TABLE.scrollLabel });
    // The primitive's rule is `max-width: 100%; overflow-x: auto`, so the
    // table pans inside the box rather than widening its parent.
    expect(region.className).toContain("ew-scroll-region");
    expect(region.className).toContain("overflow-y-auto");
  });

  it("gives the vitals table its own region, and adds no landmark of its own", () => {
    render(
      <Diagnostics
        defaultOpen
        showVitals
        records={[record({ kind: "vital", event: "LCP", detail: { value: 1, rating: "good" } })]}
      />,
    );
    // EXACTLY two: the two ScrollRegions. The vitals block is a plain div
    // with a heading, not a `<section aria-labelledby>` — a named section
    // is a landmark, and content inside a disclosure is not a navigable
    // area of the page.
    const regions = screen.getAllByRole("region");
    expect(regions.map((region) => region.getAttribute("aria-label"))).toEqual([
      DIAGNOSTICS_TABLE.scrollLabel,
      DIAGNOSTICS_VITALS.scrollLabel,
    ]);
  });
});

// ---------------------------------------------------------------------------
// The empty, dropped and evidence states.
// ---------------------------------------------------------------------------

describe("03 §4.5's states", () => {
  it("says so when nothing has been received, keeping the table's shape", () => {
    render(<Diagnostics records={[]} defaultOpen />);
    expect(screen.getByText(DIAGNOSTICS.empty)).toBeInTheDocument();
    expect(within(screen.getByRole("log")).getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("log")).toHaveAttribute("data-record-count", "0");
  });

  it("states what is retained, and says nothing about drops when there are none", () => {
    render(<Diagnostics records={[]} defaultOpen />);
    expect(screen.getByText(/0 records held in memory/)).toBeInTheDocument();
    expect(screen.queryByText(/fell off the end/)).toBeNull();
  });

  it("names the drop count once the buffer has wrapped", () => {
    render(<Diagnostics records={[]} defaultOpen dropped={12} />);
    expect(screen.getByText(/12 older records fell off the end/)).toBeInTheDocument();
  });

  it("renders rawErrorEvidence()'s labelled rows (RC-16)", () => {
    render(
      <Diagnostics
        records={[]}
        defaultOpen
        evidence={rawErrorEvidence("SomeFutureExceptionName", null)}
      />,
    );
    expect(screen.getByText("error_type")).toBeInTheDocument();
    expect(screen.getByText("SomeFutureExceptionName")).toBeInTheDocument();
    // Absence is "not reported", never "unknown" and never a blank row.
    expect(screen.getByText(NOT_REPORTED)).toBeInTheDocument();
  });

  it("prints times in UTC, and says 'not reported' for a time that is not one", () => {
    expect(formatRecordTime(AT)).toBe("09:14:03.120");
    expect(formatRecordTime(Number.NaN)).toBe(NOT_REPORTED);
  });

  it("labels every record kind, including the connection notes (03 §2.2 row 11)", () => {
    render(
      <Diagnostics
        defaultOpen
        records={[
          record({ kind: "connection", event: "reconnecting", from: "open" }),
          record({ kind: "frame", event: "stream_timeout", detail: { reason: "max_duration" } }),
          record({
            kind: "failure",
            event: "poll",
            failureKind: "upstream_unavailable",
            detail: { status: 502 },
          }),
        ]}
      />,
    );
    expect(screen.getByText("reconnecting")).toBeInTheDocument();
    expect(screen.getByText("stream_timeout")).toBeInTheDocument();
    expect(screen.getByText("upstream_unavailable")).toBeInTheDocument();
    expect(screen.getAllByText("connection").length).toBeGreaterThan(0);
  });

  it("builds the detail pairs from `from`, the failure kind and the payload", () => {
    expect(
      detailPairs(
        record({
          kind: "failure",
          event: "poll",
          from: "live",
          failureKind: "timeout",
          detail: { status: null, state_delta: { a: 1 }, other: [1] },
        }),
      ),
    ).toEqual([
      { key: "from", value: "live" },
      { key: "failure_kind", value: "timeout" },
      { key: "status", value: "null" },
      { key: "a", value: "1" },
      { key: "other", value: "[1]" },
    ]);
    expect(detailPairs(record({ kind: "frame", event: "x" }))).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// Criterion 6 — the copy control.
// ---------------------------------------------------------------------------

describe("criterion 6 — Copy diagnostics", () => {
  it("hands over a redacted blob with none of the four exclusions in it", async () => {
    const events = user();
    const copied: string[] = [];
    render(
      <Diagnostics
        defaultOpen
        onCopy={(json) => {
          copied.push(json);
        }}
        records={[
          record({
            kind: "frame",
            event: "job_started",
            detail: {
              query: "What evaluation methods make research agents reliable?",
              report: "## Findings\n\nA long briefing that must not travel.",
              headers: { authorization: "Bearer sk-live-abcdefghij" },
              url: "https://host.example/api/research/abc-123/stream?api_key=secret",
            },
          }),
        ]}
      />,
    );

    await events.click(screen.getByRole("button", { name: DIAGNOSTICS.copyAction }));
    await waitFor(() => {
      expect(copied).toHaveLength(1);
    });

    const blob = copied[0] as string;
    expect(blob).not.toContain("evaluation methods");
    expect(blob).not.toContain("Findings");
    expect(blob).not.toContain("Bearer");
    expect(blob).not.toContain("https://");
    expect(blob).toContain("/api/research/{id}/stream");
    expect(screen.getByText(DIAGNOSTICS.copied)).toBeInTheDocument();
  });

  it("states the promise before the button is pressed, not after", () => {
    render(<Diagnostics records={[]} defaultOpen />);
    expect(screen.getByText(DIAGNOSTICS.copyNote)).toBeInTheDocument();
  });

  it("falls back to the clipboard when no seam is supplied", async () => {
    const events = user();
    const writeText = vi.fn((_text: string) => Promise.resolve());
    const original = Object.getOwnPropertyDescriptor(navigator, "clipboard");
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    try {
      render(<Diagnostics records={[record({ kind: "frame", event: "x" })]} defaultOpen />);
      await events.click(screen.getByRole("button", { name: DIAGNOSTICS.copyAction }));
      await waitFor(() => {
        expect(writeText).toHaveBeenCalledTimes(1);
      });
      expect(String(writeText.mock.calls[0]?.[0])).toContain(
        "arxiv-research-agent/diagnostics",
      );
    } finally {
      if (original) Object.defineProperty(navigator, "clipboard", original);
      else Reflect.deleteProperty(navigator, "clipboard");
    }
  });

  it("says what to do instead when the clipboard refuses", async () => {
    const events = user();
    render(
      <Diagnostics
        records={[]}
        defaultOpen
        onCopy={() => {
          throw new Error("denied");
        }}
      />,
    );
    await events.click(screen.getByRole("button", { name: DIAGNOSTICS.copyAction }));
    await waitFor(() => {
      expect(screen.getByText(/copy them by hand/)).toBeInTheDocument();
    });
    // Not an alert: 03 §7.3 allows exactly two live regions, and neither
    // of them is this one.
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Criterion 7 — the vitals block.
// ---------------------------------------------------------------------------

describe("criterion 7 — vitals render only behind ?debug=perf", () => {
  const VITALS: DiagnosticRecord[] = [
    record({
      kind: "vital",
      event: "LCP",
      detail: { value: 1840, rating: "good", unit: "ms", navigationType: "navigate" },
    }),
    record({
      kind: "vital",
      event: "CLS",
      detail: { value: 0.021, rating: "needs-improvement", unit: "" },
    }),
  ];

  it("is absent — not disabled, not empty — when the flag is off", () => {
    render(<Diagnostics records={VITALS} defaultOpen />);
    expect(screen.queryByText(DIAGNOSTICS_VITALS.label)).toBeNull();
    expect(
      screen.queryByRole("region", { name: DIAGNOSTICS_VITALS.scrollLabel }),
    ).toBeNull();
  });

  it("keeps vitals out of the frames table either way", () => {
    render(<Diagnostics records={VITALS} defaultOpen />);
    // The frames table is for what the stream sent; a metric this page
    // measured about itself is not a frame.
    expect(screen.getByText(DIAGNOSTICS.empty)).toBeInTheDocument();
  });

  it("renders the three metrics, their values and the library's rating word", () => {
    render(<Diagnostics records={VITALS} defaultOpen showVitals />);
    expect(screen.getByText(DIAGNOSTICS_VITALS.metric.LCP)).toBeInTheDocument();
    expect(screen.getByText(DIAGNOSTICS_VITALS.metric.CLS)).toBeInTheDocument();
    expect(screen.getByText("1840ms")).toBeInTheDocument();
    expect(screen.getByText("0.021")).toBeInTheDocument();
    expect(screen.getByText(DIAGNOSTICS_VITALS.rating.good)).toBeInTheDocument();
    expect(
      screen.getByText(DIAGNOSTICS_VITALS.rating["needs-improvement"]),
    ).toBeInTheDocument();
    expect(screen.getByText(DIAGNOSTICS_VITALS.note)).toBeInTheDocument();
  });

  it("renders a metric whose record carries no unit at all", () => {
    render(
      <Diagnostics
        defaultOpen
        showVitals
        records={[record({ kind: "vital", event: "INP", detail: { value: 43 } })]}
      />,
    );
    expect(screen.getByText("43")).toBeInTheDocument();
    expect(screen.getByText(NOT_REPORTED)).toBeInTheDocument();
  });

  it("says so when the flag is on and nothing has been measured yet", () => {
    render(<Diagnostics records={[]} defaultOpen showVitals />);
    expect(screen.getByText(DIAGNOSTICS_VITALS.empty)).toBeInTheDocument();
  });

  it("passes a metric or a rating it has never heard of straight through", () => {
    expect(metricWord("LCP")).toBe(DIAGNOSTICS_VITALS.metric.LCP);
    expect(metricWord("FUTURE_METRIC")).toBe("FUTURE_METRIC");
    expect(ratingWord("good")).toBe(DIAGNOSTICS_VITALS.rating.good);
    expect(ratingWord("catastrophic")).toBe("catastrophic");
    expect(ratingWord(undefined)).toBe(NOT_REPORTED);
  });

  it("gives the vitals table its own labelled region, outside the live region", () => {
    render(<Diagnostics records={VITALS} defaultOpen showVitals />);
    const vitalsRegion = screen.getByRole("region", {
      name: DIAGNOSTICS_VITALS.scrollLabel,
    });
    expect(screen.getByRole("log").contains(vitalsRegion)).toBe(false);
  });
});
