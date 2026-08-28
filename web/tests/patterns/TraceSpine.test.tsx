/**
 * TraceSpine — WO-15 criteria 1, 3, 4, 5, 6, 7, 8, 9 and 10.
 *
 * ==========================================================================
 * WHAT THIS FILE CAN AND CANNOT PROVE, STATED UP FRONT
 *
 * Criterion 7 is "a test asserts CLS 0.000 while ticks arrive". jsdom has
 * no layout engine: `getBoundingClientRect` is all zeros, `offsetHeight` is
 * 0, and there is no `LayoutShift` entry to observe. A test here that
 * claimed to measure CLS would be measuring nothing, which is worse than
 * measuring less.
 *
 * So the claim is split, and the split is the honest one:
 *
 *   - HERE: the two properties that MAKE CLS zero, asserted mechanically.
 *     (a) nothing in `spine.css` can move anything — the tick entrance
 *         declares one property, `opacity`, and the file contains no
 *         transform, translate, inset, margin or size animation at all;
 *     (b) an arriving checkpoint changes nothing above it — the segments
 *         before the ledger are byte-identical across the rerender, and the
 *         two rows a tick can land in reserve their height before the first
 *         tick exists.
 *   - WO-21 (Playwright, per-PR chromium): the MEASUREMENT, against
 *     04 §8.2's budget and RC-06's "0.000 is the design intent and the
 *     measured baseline". A local Playwright run is not available in this
 *     work order — Playwright is not a dependency of `web/` and adding one
 *     is out of scope for a component PR — so the measurement is deferred
 *     with this annotation rather than faked with a jsdom stand-in.
 *
 * Everything else below is asserted for real.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { CheckpointLedger } from "@/components/patterns/CheckpointLedger";
import {
  SEGMENT_MARK,
  SEGMENT_TONE,
  TraceSpine,
} from "@/components/patterns/TraceSpine";
import { DENY_LIST, LEXICON_PHRASES, findForbidden } from "@/lib/copy";
import { RUN_STATUS_WORD, SPINE_LEGEND } from "@/lib/copy/trace";
import { SPINE } from "@/lib/copy/spine";
import { initialJobState } from "@/lib/job/machine";
import { useJobStream } from "@/lib/job/useJobStream";
import type { JobClient, JobState } from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";
import { spineInputs } from "@/lib/spine/adapter";
import {
  SEGMENT_STATUSES,
  SEGMENT_WORD,
  SPINE_STATES,
  describeSpine,
  type SegmentStatus,
  type SpineInputs,
  type SpineStateId,
} from "@/lib/spine/state";

import {
  blockBodyFrom,
  customProperties,
  installStylesheet,
  readWebFile,
  resolvePixels,
  ruleBody,
  stripComments,
} from "../primitives/support/css";
import {
  FakeEventSource,
  installFakeEventSource,
  loadSseScript,
  openSources,
  uninstallFakeEventSource,
  type SseScriptName,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, render, renderHook, within } from "../support/render";
import { EVERY_STATE, ONE, STATUS_UNKNOWN, THREE, checkpoint } from "./spineFixtures";

const SPINE_CSS = stripComments(readWebFile("components/patterns/spine.css"));
const PRIMITIVES_CSS = stripComments(readWebFile("components/primitives/primitives.css"));

function source(relative: string): string {
  return readFileSync(join(process.cwd(), relative), "utf8");
}

/**
 * Both comment forms, gone.
 *
 * `stripComments` from the primitives' CSS helpers removes `/* … *\/` only,
 * which is all a stylesheet has. TypeScript files in this repository
 * document their own rules by quoting them — StatusBanner's header says
 * `role="status"` four times in line comments to explain why it never emits
 * one — so a source scan that missed `//` would accuse the file that is
 * being careful.
 */
function code(relative: string): string {
  return stripComments(source(relative)).replace(/^\s*\/\/.*$/gm, "");
}

/** The four segments: the region's own `<ol>`, not the ledger's. */
function segmentItems(root: HTMLElement): Element[] {
  return [...(root.querySelector("ol") as HTMLElement).children];
}

/** Render one state and hand back its root, without touching document scope. */
function spine(inputs: SpineInputs | null, props: Partial<{ legend: "open" | "disclosure" | "none" }> = {}) {
  const view = render(<TraceSpine inputs={inputs} legend={props.legend ?? "open"} />);
  const root = view.container.querySelector("section") as HTMLElement;
  return { view, root };
}

// ===========================================================================
// Criterion 1 — the four inputs, and nothing else.
// ===========================================================================

describe("criterion 1 — the spine reads exactly 03 §5.2's four inputs", () => {
  it("renders identically for two job states that differ in everything else", () => {
    const base: JobState = {
      ...initialJobState,
      jobId: "baseline-running",
      detail: { job_id: "a", status: "running" } as JobDetail,
      connection: "open",
      checkpoint: checkpoint("planner"),
      observed: [checkpoint("planner")],
      lastFrameAt: 1_000,
    };
    // Every field a `JobState` carries that is NOT one of the four inputs,
    // set to something loud. Including the job id: it names the run, it
    // does not describe it.
    const noisy: JobState = {
      ...base,
      jobId: "an-entirely-different-run",
      frames: [{ name: "job_started", data: { query: "a question" }, receivedAt: 1 }],
      terminal: { name: "job_failed", shape: "live", receivedAt: 9 },
      failure: { kind: "timeout", message: "", raw: null },
      failureMessage: "a thrown message nobody should see here",
      failureStatus: 504,
      failureSource: "poll",
      review: { action: "cancel", inFlight: true },
      unchangedPolls: 7,
      detailSignature: "whatever",
      connectionOpenedAt: 3,
      suspended: true,
    };

    // `legend="open"` rather than the default disclosure: `useId` hands out
    // a fresh `_r_N_` per mount, so a disclosure would differ between two
    // renders of IDENTICAL inputs and the comparison would be about React's
    // id counter rather than about the spine.
    const a = render(<TraceSpine inputs={spineInputs(base, 2_000)} legend="open" />);
    const first = a.container.innerHTML;
    a.unmount();

    const b = render(<TraceSpine inputs={spineInputs(noisy, 2_000)} legend="open" />);
    expect(b.container.innerHTML).toBe(first);
    // …and it is a real render, not two empty divs.
    expect(first).toContain("data-spine-state=\"running_observed\"");
  });

  it("takes no data prop but `inputs`", () => {
    // The props type is `inputs` plus three presentational names. A data
    // prop cannot be added without this failing, which is the point.
    const declared = source("components/patterns/TraceSpine.tsx");
    const props = declared.slice(
      declared.indexOf("export interface TraceSpineProps"),
      declared.indexOf("export function TraceSpine"),
    );
    const names = [...props.matchAll(/^\s{2}(\w+)\??:/gm)].map((match) => match[1]);
    expect(names.sort()).toEqual(["className", "id", "inputs", "legend"]);
  });

  it("presentational props move the wrapper and nothing inside the region", () => {
    const a = render(<TraceSpine inputs={EVERY_STATE.running_observed} legend="none" />);
    const first = (a.container.querySelector("ol") as HTMLElement).innerHTML;
    a.unmount();
    const b = render(
      <TraceSpine
        inputs={EVERY_STATE.running_observed}
        legend="none"
        className="border p-8"
      />,
    );
    expect((b.container.querySelector("ol") as HTMLElement).innerHTML).toBe(first);
  });
});

// ===========================================================================
// Criterion 3 — the forbidden-string sweep, over all twelve states.
// ===========================================================================

describe("criterion 3 — no §5.5 forbidden string is producible by any spine state", () => {
  /** The twelve, plus the two renderings that are not one of them. */
  const RENDERINGS: Array<[string, SpineInputs | null]> = [
    ...SPINE_STATES.map((id): [string, SpineInputs] => [id, EVERY_STATE[id]]),
    ["status_unknown", STATUS_UNKNOWN],
    ["no_run", null],
  ];

  it("sweeps all twelve rows of 03 §5.4 and nothing is skipped", () => {
    expect(SPINE_STATES).toHaveLength(12);
    expect(RENDERINGS).toHaveLength(14);
    for (const id of SPINE_STATES) {
      expect(describeSpine(EVERY_STATE[id]).id).toBe(id);
    }
  });

  it.each(RENDERINGS)("%s says nothing on the deny-list", (_name, inputs) => {
    const { view, root } = spine(inputs);
    const text = root.textContent ?? "";
    expect(text.length).toBeGreaterThan(0);
    expect(findForbidden(text, DENY_LIST)).toEqual([]);
    // The disclosure's collapsed panel is in the DOM too, so the legend is
    // swept whether it is open or not.
    expect(findForbidden(view.container.textContent ?? "", DENY_LIST)).toEqual([]);
    view.unmount();
  });

  it.each(RENDERINGS)("%s says nothing off RC-12's lexicon, outside the ledger", (_name, inputs) => {
    // The ledger's entries are node labels, passed through verbatim (H11) —
    // they are the API's words, not ours, exactly as `forbidden.test.ts`
    // exempts `MAPPED_ERROR_TYPES`. Everything the PRODUCT wrote is swept.
    const { view, root } = spine(inputs);
    for (const item of root.querySelectorAll("[data-checkpoint-index]")) item.remove();
    const text = root.textContent ?? "";
    for (const phrase of LEXICON_PHRASES) {
      expect(phrase.pattern.test(text), `${phrase.id}: ${phrase.why}`).toBe(false);
    }
    view.unmount();
  });

  it("never claims a current position, in any of the twelve", () => {
    for (const id of SPINE_STATES) {
      const { view, root } = spine(EVERY_STATE[id]);
      const text = root.textContent ?? "";
      // H1 and H4, as sentences rather than as a rule nobody re-reads.
      expect(text, id).not.toMatch(/currently|right now|in progress|working on/i);
      expect(text, id).not.toMatch(/\d+\s*%/);
      expect(text, id).not.toMatch(/failed (?:in|during|at)\b/i);
      view.unmount();
    }
  });

  it("says 'not reported' where the API is silent, and never 'unknown'", () => {
    const { view, root } = spine(STATUS_UNKNOWN);
    expect(root.textContent).toContain("not reported");
    expect(root.textContent ?? "").not.toMatch(/\bunknown\b/i);
    view.unmount();

    const ledger = render(<CheckpointLedger checkpoints={[checkpoint("")]} />);
    expect(ledger.container.textContent).toContain("not reported");
    ledger.unmount();
  });
});

// ===========================================================================
// Criterion 4 — the seven contract fixtures.
// ===========================================================================

const RUNNING = loadFixture("job.running").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;
const FAILED = loadFixture("job.failed_partial").body as JobDetail;

/**
 * 03 §5.9 obligation 1's seven, by the name each is recorded under.
 *
 * "reload-with-no-checkpoints" is `replay_terminal`: a stream that opens on
 * a run that already finished replays one terminal frame and nothing else,
 * so the ledger is empty for the reason the obligation names.
 */
const OBLIGATION_1: Array<{ script: SseScriptName; details: JobDetail[]; why: string }> = [
  { script: "live_success", details: [RUNNING, SUCCEEDED], why: "live checkpoints" },
  { script: "replay_terminal", details: [RUNNING, SUCCEEDED], why: "reload with no checkpoints" },
  { script: "reconnect_gap", details: [RUNNING, SUCCEEDED], why: "reconnect gap" },
  { script: "stream_timeout", details: [RUNNING, SUCCEEDED], why: "stream_timeout" },
  { script: "terminal_replay_no_node", details: [RUNNING, FAILED], why: "terminal replay, no node" },
  { script: "unknown_event_name", details: [RUNNING, SUCCEEDED], why: "unknown event name" },
  { script: "unknown_state_delta_keys", details: [RUNNING, SUCCEEDED], why: "unknown state_delta keys" },
];

/**
 * Replay a whole recording, honouring both kinds of boundary.
 *
 * `playScript()` is not usable here. It assumes the CLIENT never reopens on
 * its own, and `stream_timeout` is precisely the case where it does:
 * `useJobStream` reopens immediately rather than waiting out the browser's
 * default retry (`streaming.py:300-308` — the stream ended, the run did
 * not), which constructs a second `FakeEventSource` that has already
 * adopted the next recorded connection. So the loop below always drives
 * whichever source is currently open, and only crosses a boundary by hand
 * when the client did not cross it first.
 */
async function replay(name: SseScriptName): Promise<void> {
  const total = loadSseScript(name).connections.length;
  const played = new Set<FakeEventSource>();

  for (let guard = 0; guard < total * 3 + 4; guard += 1) {
    const source = openSources().at(-1);
    if (source === undefined) break;
    if (!played.has(source) || source.remaining > 0) {
      played.add(source);
      await act(async () => {
        source.play();
      });
      continue;
    }
    if (source.endedBy === "end-of-script") break;
    if (FakeEventSource.nextConnection >= total) break;
    await act(async () => {
      source.endConnection();
      source.reopen();
    });
  }
}

describe("criterion 4 — all seven contract fixtures render a defined state", () => {
  afterEach(() => {
    uninstallFakeEventSource();
  });

  it("there are seven of them, and they are the seven §5.9 obligation 1 names", () => {
    expect(OBLIGATION_1).toHaveLength(7);
    expect(new Set(OBLIGATION_1.map((entry) => entry.script)).size).toBe(7);
  });

  it.each(OBLIGATION_1)("$script ($why)", async ({ script, details }) => {
    const queue = [...details];
    const client: Partial<JobClient> = {
      getJob: () => Promise.resolve(queue.shift() ?? (details[details.length - 1] as JobDetail)),
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
    };
    installFakeEventSource({ script });

    const history: JobState[] = [];
    const { result } = renderHook(() => {
      const controls = useJobStream({ client });
      history.push(controls.state);
      return controls;
    });

    await act(async () => {
      result.current.attach("baseline-running");
    });
    await replay(script);

    expect(history.length).toBeGreaterThan(2);

    let defined = 0;
    for (const state of history) {
      const inputs = spineInputs(state, 60_000);
      // Every state the machine passed through renders, and every one of
      // them lands on one of the twelve rows — never a fall-through.
      const view = render(<TraceSpine inputs={inputs} legend="none" />);
      const rendered = view.container.querySelector("section") as HTMLElement;
      const id = rendered.getAttribute("data-spine-state") as SpineStateId | "none";
      if (id !== "none") {
        expect(SPINE_STATES, `${script}: ${id}`).toContain(id);
        expect(describeSpine(inputs as SpineInputs).id).toBe(id);
        defined += 1;
      }
      // Four segments, always, whatever arrived.
      expect(segmentItems(rendered)).toHaveLength(4);
      expect(findForbidden(rendered.textContent ?? "", DENY_LIST)).toEqual([]);
      view.unmount();
    }
    expect(defined, script).toBeGreaterThan(0);
  });
});

// ===========================================================================
// Criterion 5 — the eight statuses, with colour and images unavailable.
// ===========================================================================

describe("criterion 5 — every mark has a text equivalent on the same line", () => {
  it("eight statuses, eight distinct words, eight distinct shapes", () => {
    expect(SEGMENT_STATUSES).toHaveLength(8);
    const words = SEGMENT_STATUSES.map((status) => SEGMENT_WORD[status]);
    const marks = SEGMENT_STATUSES.map((status) => SEGMENT_MARK[status]);
    expect(new Set(words).size).toBe(8);
    expect(new Set(marks).size).toBe(8);
    // Colour is third and is the only one of the three that repeats.
    expect(new Set(SEGMENT_STATUSES.map((s) => SEGMENT_TONE[s])).size).toBeLessThan(8);
  });

  it("all eight appear across 03 §5.4's twelve states", () => {
    const seen = new Set<SegmentStatus>();
    for (const id of SPINE_STATES) {
      for (const segment of describeSpine(EVERY_STATE[id]).segments) seen.add(segment.status);
      if (describeSpine(EVERY_STATE[id]).live) seen.add("live");
    }
    expect([...seen].sort()).toEqual([...SEGMENT_STATUSES].sort());
  });

  it("with colour and images taken away, the eight are still told apart", () => {
    // Images disabled: every mark is an inline <svg>, so removing them all
    // is the strictly harsher version of the test. Colour disabled: the
    // words below are compared as STRINGS, so no hue participates.
    const texts: string[] = [];
    for (const id of SPINE_STATES) {
      const { view, root } = spine(EVERY_STATE[id]);
      for (const svg of root.querySelectorAll("svg")) svg.remove();
      texts.push(root.textContent ?? "");
      view.unmount();
    }
    const all = texts.join("\n");
    for (const status of SEGMENT_STATUSES) {
      expect(all, status).toContain(SEGMENT_WORD[status]);
    }
  });

  it("the word sits beside the mark, inside the same segment", () => {
    const { view, root } = spine(EVERY_STATE.awaiting_review);
    const plan = root.querySelector('[data-segment="Plan"]') as HTMLElement;
    expect(plan.querySelector("svg")).not.toBeNull();
    expect(plan.textContent).toContain(RUN_STATUS_WORD.pendingReview);
    expect(plan.getAttribute("data-status")).toBe("awaiting-review");
    expect(plan.querySelector("svg")?.getAttribute("data-mark")).toBe(
      SEGMENT_MARK["awaiting-review"],
    );
    view.unmount();
  });

  it("marks are aria-hidden, so the word is what a screen reader hears", () => {
    const { view, root } = spine(EVERY_STATE.succeeded);
    for (const svg of root.querySelectorAll("svg")) {
      expect(svg.getAttribute("aria-hidden")).toBe("true");
    }
    view.unmount();
  });
});

// ===========================================================================
// Criterion 6 — structure, and the product's single live region.
// ===========================================================================

describe("criterion 6 — an <ol> of four in a labelled region, with a nested <ol>", () => {
  it("names the region, and puts four segments in one ordered list", () => {
    const { view, root } = spine(EVERY_STATE.running_observed);
    expect(root.getAttribute("aria-labelledby")).toBe("trace-spine-label");
    expect(within(root).getByRole("heading", { level: 2 })).toHaveTextContent(
      SPINE.regionLabel,
    );
    expect(segmentItems(root).map((child) => child.tagName)).toEqual([
      "LI",
      "LI",
      "LI",
      "LI",
    ]);
    expect(segmentItems(root).map((child) => child.getAttribute("data-segment"))).toEqual([
      "Question",
      "Plan",
      "Run",
      "Report",
    ]);
    view.unmount();
  });

  it("nests the ledger's <ol> inside the Run segment's own <li>", () => {
    const { view, root } = spine(EVERY_STATE.running_observed);
    const run = root.querySelector('[data-segment="Run"]') as HTMLElement;
    const nested = run.querySelector("ol") as HTMLElement;
    expect(nested).not.toBeNull();
    expect(nested.getAttribute("data-checkpoint-count")).toBe("3");
    expect(nested.closest("li")).toBe(run);
    // Every <li> is a direct child of a list, which is what axe's
    // `listitem` rule asks and what the baseline failed.
    for (const item of root.querySelectorAll("li")) {
      expect(["OL", "UL"]).toContain(item.parentElement?.tagName);
    }
    view.unmount();
  });

  it("renders exactly one role=status, in every state including no-run", () => {
    for (const inputs of [...SPINE_STATES.map((id) => EVERY_STATE[id]), STATUS_UNKNOWN, null]) {
      const view = render(<TraceSpine inputs={inputs} />);
      const regions = view.container.querySelectorAll('[role="status"]');
      expect(regions.length).toBeLessThanOrEqual(1);
      if (inputs !== null) expect(regions).toHaveLength(1);
      view.unmount();
    }
  });

  it("is the ONLY role=status in the component tree, product-wide", () => {
    // 03 §7.3 allows exactly one. WO-12's StatusBanner documents that it
    // has no branch producing one; this is the mechanical half.
    const files = listFiles("components").filter((file) => file.endsWith(".tsx"));
    expect(files.length).toBeGreaterThan(10);
    const owners = files.filter((file) => /role=\{?["']status["']\}?/.test(code(file)));
    expect(owners).toEqual(["components/patterns/TraceSpine.tsx"]);
  });

  it("announces material transitions and never an individual checkpoint", () => {
    const one = render(<TraceSpine inputs={{ ...EVERY_STATE.running_observed, observation: { checkpoints: ONE, connection: "open", current: true } }} />);
    const before = (one.container.querySelector("[data-spine-part='announcement']") as HTMLElement).textContent;
    const detailBefore = (one.container.querySelector("[data-spine-part='detail']") as HTMLElement).textContent;
    one.unmount();

    const three = render(<TraceSpine inputs={EVERY_STATE.running_observed} />);
    const after = (three.container.querySelector("[data-spine-part='announcement']") as HTMLElement).textContent;
    const detailAfter = (three.container.querySelector("[data-spine-part='detail']") as HTMLElement).textContent;
    three.unmount();

    // Two more checkpoints arrived. The live region did not move.
    expect(after).toBe(before);
    expect(after).toBe(SPINE.running);
    // The count did. It is outside the live region, which is the whole
    // reason the sentence is split in two.
    expect(detailAfter).not.toBe(detailBefore);
    expect(detailAfter).toContain("3 checkpoints observed on this connection");
  });

  it("never puts a checkpoint label inside the live region", () => {
    for (const id of SPINE_STATES) {
      const { view, root } = spine(EVERY_STATE[id]);
      const announcement = root.querySelector('[role="status"]')?.textContent ?? "";
      for (const observed of EVERY_STATE[id].observation.checkpoints) {
        // The one sanctioned exception is H3's failure sentence, which
        // names the LAST observed checkpoint because §5.4 requires it.
        if (id === "failed_observed" && announcement.includes("Failed after")) continue;
        expect(announcement, `${id}/${observed.node}`).not.toContain(observed.node);
      }
      view.unmount();
    }
  });

  it("announces each material transition with its own sentence", () => {
    const announcements = SPINE_STATES.map(
      (id) => describeSpine(EVERY_STATE[id]).announcement,
    );
    // Awaiting review, reconnecting, recycled, complete, failed, cancelled,
    // expired — 03 §5.7's list, each distinguishable from the others.
    expect(new Set(announcements).size).toBe(announcements.length);
  });
});

// ===========================================================================
// Criterion 7 — the tick arrives with opacity, and moves nothing.
// ===========================================================================

describe("criterion 7 — an arriving checkpoint never moves the reading column", () => {
  it("the tick entrance animates opacity and nothing else", () => {
    const keyframes = blockBodyFrom(SPINE_CSS, SPINE_CSS.indexOf("@keyframes ew-spine-tick-in"));
    const properties = [...keyframes.matchAll(/([a-z-]+)\s*:/g)].map((match) => match[1]);
    expect(new Set(properties)).toEqual(new Set(["opacity"]));
    expect(ruleBody(SPINE_CSS, ".ew-spine-tick").trim()).toMatch(/^animation:/);
  });

  it("nothing in the stylesheet can translate, scale or resize anything", () => {
    for (const property of [
      "transform",
      "translate",
      "scale",
      "rotate",
      "inset",
      "top:",
      "left:",
      "right:",
      "bottom:",
      "margin",
    ]) {
      expect(SPINE_CSS, property).not.toContain(property);
    }
    // And there is no transition either: an entrance is the only motion.
    expect(SPINE_CSS).not.toContain("transition");
  });

  it("the two rows a tick can land in reserve their height before it exists", () => {
    const style = installStylesheet(SPINE_CSS);
    const tokens = customProperties(readWebFile("app/tokens.css"));
    const { view, root } = spine(EVERY_STATE.rejoined);
    const run = root.querySelector(".ew-spine-run") as HTMLElement;
    // 24px, reserved with an empty ledger — so the first checkpoint fades
    // in rather than pushing the sentence below it down.
    expect(resolvePixels(run, "min-height", tokens)).toBe(24);
    view.unmount();

    const withTicks = spine(EVERY_STATE.running_observed);
    const ledger = withTicks.root.querySelector(".ew-spine-ledger") as HTMLElement;
    expect(resolvePixels(ledger, "min-height", tokens)).toBe(24);
    withTicks.view.unmount();
    style.remove();
  });

  it("the void keeps a floor width, so a long ledger cannot squeeze it away", () => {
    const style = installStylesheet(SPINE_CSS);
    const tokens = customProperties(readWebFile("app/tokens.css"));
    const { view, root } = spine(EVERY_STATE.running_observed);
    const empty = root.querySelector(".ew-spine-void") as HTMLElement;
    expect(resolvePixels(empty, "min-width", tokens)).toBe(64);
    view.unmount();
    style.remove();
  });

  it("everything above the ledger is byte-identical when a checkpoint arrives", () => {
    const one = render(
      <TraceSpine
        inputs={{ ...EVERY_STATE.running_observed, observation: { checkpoints: ONE, connection: "open", current: true }, secondsSinceLastFrame: 41 }}
        legend="none"
      />,
    );
    const before = [...(one.container.querySelector("ol") as HTMLElement).children].map(
      (child) => child.outerHTML,
    );
    one.unmount();

    const three = render(
      <TraceSpine
        inputs={{ ...EVERY_STATE.running_observed, observation: { checkpoints: THREE, connection: "open", current: true }, secondsSinceLastFrame: 41 }}
        legend="none"
      />,
    );
    const after = [...(three.container.querySelector("ol") as HTMLElement).children].map(
      (child) => child.outerHTML,
    );
    three.unmount();

    // Question, Plan and Report are untouched; only the Run segment grew,
    // and it grew INSIDE a pan surface with a reserved height.
    expect(after[0]).toBe(before[0]);
    expect(after[1]).toBe(before[1]);
    expect(after[3]).toBe(before[3]);
    expect(after[2]).not.toBe(before[2]);
  });

  it("DEFERRED TO WO-21: the CLS number itself", () => {
    // See this file's header. jsdom has no layout, so the measurement is
    // WO-21's Playwright tier; what is asserted above is every property
    // that makes the number zero. This test exists so the deferral is a
    // line in the suite rather than a sentence in a comment.
    expect(SPINE_CSS).toContain("opacity");
    expect(SPINE_CSS).not.toContain("transform");
  });
});

// ===========================================================================
// Criterion 8 — the static void, and ambient motion that needs a socket.
// ===========================================================================

describe("criterion 8 — the blind spot is static under every motion setting", () => {
  it("no rule anywhere in the stylesheet animates the void", () => {
    // Every rule whose selector mentions the void, in every media block.
    const rules = [...SPINE_CSS.matchAll(/([^{}]*ew-spine-void[^{}]*)\{([^}]*)\}/g)];
    expect(rules.length).toBeGreaterThan(0);
    for (const [, selector, body] of rules) {
      expect(body, selector).not.toMatch(/animation|transition/);
    }
  });

  it("the reduced-motion block does not mention it, because it has nothing to stop", () => {
    const reduced = blockBodyFrom(
      SPINE_CSS,
      SPINE_CSS.indexOf("@media (prefers-reduced-motion: reduce)"),
    );
    expect(reduced).toContain("ew-spine-tick");
    expect(reduced).not.toContain("ew-spine-void");
  });

  it("computes to no animation with the real stylesheet attached", () => {
    const style = installStylesheet(SPINE_CSS);
    const { view, root } = spine(EVERY_STATE.running_observed);
    const empty = root.querySelector(".ew-spine-void") as HTMLElement;
    const animation = getComputedStyle(empty).animationName;
    expect(animation === "" || animation === "none").toBe(true);
    expect(empty.className).not.toContain("ew-pulse");
    expect(empty.className).not.toContain("ew-enter");
    view.unmount();
    style.remove();
  });

  it("is dimensioned in every state, and carries a word beside it", () => {
    for (const id of SPINE_STATES) {
      const { view, root } = spine(EVERY_STATE[id]);
      const run = root.querySelector('[data-segment="Run"]') as HTMLElement;
      expect(run.querySelector(".ew-spine-void"), id).not.toBeNull();
      // "not observed" is either the segment's own word or the one printed
      // beside the void; one of the two, never neither.
      expect(run.textContent, id).toContain(SPINE.voidWord);
      view.unmount();
    }
  });

  it("states what it does not know, in words, under the spine", () => {
    const { view, root } = spine(EVERY_STATE.running_observed);
    expect(root.textContent).toContain(SPINE.voidDescription);
    expect(SPINE.voidDescription).toContain("not reported");
    view.unmount();
  });
});

describe("criterion 8 — the ambient indicator runs only while a socket is open", () => {
  it("appears exactly when the connection is open, across all twelve states", () => {
    for (const id of SPINE_STATES) {
      const inputs = EVERY_STATE[id];
      const { view, root } = spine(inputs);
      const open = inputs.observation.connection === "open";
      expect(root.getAttribute("data-live"), id).toBe(open ? "true" : "false");
      expect(Boolean(root.querySelector(".ew-pulse")), id).toBe(open);
      if (open) expect(root.textContent, id).toContain(RUN_STATUS_WORD.live);
      view.unmount();
    }
  });

  it("stops the moment the connection ends, ticks and all", () => {
    // `checkpointIsCurrent` goes false with the connection, which is what
    // 03 §5.4's reconnect row needs: ticks kept, claim dropped.
    const { view, root } = spine(EVERY_STATE.reconnecting);
    expect(root.querySelector(".ew-pulse")).toBeNull();
    expect(root.querySelectorAll("[data-checkpoint-index]")).toHaveLength(3);
    expect(root.querySelector(".ew-spine-void")?.getAttribute("data-current")).toBe("false");
    view.unmount();
  });

  it("becomes a static mark plus the word Live under reduced motion", () => {
    // The pulse is removed at the tokens and again at the class, both in
    // WO-07's primitives.css; the word is not conditional on anything.
    const reduced = blockBodyFrom(
      PRIMITIVES_CSS,
      PRIMITIVES_CSS.indexOf("@media (prefers-reduced-motion: reduce)"),
    );
    expect(reduced).toContain(".ew-pulse");
    expect(reduced).toContain("animation: none");

    const { view, root } = spine(EVERY_STATE.running_observed);
    const badge = root.querySelector('[data-severity="live"]') as HTMLElement;
    expect(badge.textContent).toBe(RUN_STATUS_WORD.live);
    expect(badge.querySelector("svg")).not.toBeNull();
    view.unmount();
  });
});

// ===========================================================================
// Criterion 9 — marks measure >= 3:1 against their surface, in both themes.
// ===========================================================================

const TOKENS_CSS = stripComments(readWebFile("app/tokens.css"));

function themeColours(theme: "light" | "dark"): Map<string, string> {
  const selector = theme === "light" ? ":root {" : ':root[data-theme="dark"]';
  return customProperties(blockBodyFrom(TOKENS_CSS, TOKENS_CSS.indexOf(selector)));
}

function relativeLuminance(hex: string): number {
  const digits = hex.replace("#", "");
  const [r = 0, g = 0, b = 0] = [0, 2, 4]
    .map((offset) => Number.parseInt(digits.slice(offset, offset + 2), 16) / 255)
    .map((channel) =>
      channel <= 0.03928 ? channel / 12.92 : Math.pow((channel + 0.055) / 1.055, 2.4),
    );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(a: string, b: string): number {
  const [x, y] = [relativeLuminance(a), relativeLuminance(b)];
  const [lighter, darker] = x > y ? [x, y] : [y, x];
  return (lighter + 0.05) / (darker + 0.05);
}

describe("criterion 9 — every mark reads at 3:1 or better against its surface", () => {
  /** `text-signature-text` -> `--color-signature-text`. */
  const tokenFor = (utility: string) => `--color-${utility.replace(/^text-/, "")}`;

  const SURFACES = ["--color-canvas", "--color-surface", "--color-sunken"];

  it.each(["light", "dark"] as const)("%s theme", (theme) => {
    const colours = themeColours(theme);
    expect(colours.get("--color-canvas")).toBeDefined();

    for (const status of SEGMENT_STATUSES) {
      const mark = colours.get(tokenFor(SEGMENT_TONE[status]));
      expect(mark, `${status} resolves to a declared colour`).toBeDefined();
      for (const surface of SURFACES) {
        const ratio = contrastRatio(mark as string, colours.get(surface) as string);
        expect(
          ratio,
          `${theme}: ${SEGMENT_TONE[status]} on ${surface} is ${ratio.toFixed(2)}:1`,
        ).toBeGreaterThanOrEqual(3);
      }
    }
  });

  it("uses only roles that app/tokens.css actually declares", () => {
    const declared = new Set(themeColours("light").keys());
    for (const status of SEGMENT_STATUSES) {
      expect(declared, status).toContain(tokenFor(SEGMENT_TONE[status]));
    }
  });
});

// ===========================================================================
// Criterion 10 — the documented insertion point.
// ===========================================================================

describe("criterion 10 — structured evidence has a home, and no code", () => {
  const spineSource = source("components/patterns/TraceSpine.tsx");

  it("the insertion point is written down where it would be built", () => {
    expect(spineSource).toContain("INSERTION POINT — STRUCTURED EVIDENCE");
    expect(spineSource).toContain("criterion 10");
    expect(spineSource).toContain("versioned backend contract");
  });

  it("and it is only a comment: nothing reads state_delta", () => {
    for (const file of [
      "components/patterns/TraceSpine.tsx",
      "components/patterns/CheckpointLedger.tsx",
      "lib/spine/state.ts",
    ]) {
      expect(stripComments(source(file)), file).not.toContain("stateDelta");
    }
  });

  it("the story group carries the same note for a reviewer who never opens the file", () => {
    const stories = source("components/patterns/TraceSpine.stories.tsx");
    expect(stories).toContain("structured evidence");
    expect(stories).toContain("insertion point");
  });
});

// ===========================================================================
// The legend, and the no-run rendering.
// ===========================================================================

describe("the legend and the inert spine", () => {
  it("renders the legend inline, behind a disclosure, or not at all", () => {
    const open = render(<TraceSpine inputs={EVERY_STATE.running_observed} legend="open" />);
    expect(open.container.querySelector("[data-spine-part='legend']")).not.toBeNull();
    expect(within(open.container).queryByRole("button")).toBeNull();
    open.unmount();

    const behind = render(
      <TraceSpine inputs={EVERY_STATE.running_observed} legend="disclosure" />,
    );
    expect(
      within(behind.container).getByRole("button", { name: SPINE.legendLabel }),
    ).toHaveAttribute("aria-expanded", "false");
    behind.unmount();

    const none = render(<TraceSpine inputs={EVERY_STATE.running_observed} legend="none" />);
    expect(none.container.querySelector("[data-spine-part='legend']")).toBeNull();
    none.unmount();
  });

  it("the legend is WO-12's, mark for mark", () => {
    const { view, root } = spine(EVERY_STATE.running_observed);
    const entries = [...(root.querySelector("[data-spine-part='legend']") as HTMLElement).children];
    expect(entries).toHaveLength(SPINE_LEGEND.length);
    expect(entries.map((entry) => entry.querySelector("svg")?.getAttribute("data-mark"))).toEqual(
      SPINE_LEGEND.map((entry) => entry.mark),
    );
    view.unmount();
  });

  it("with no run, says nothing about one", () => {
    const { view, root } = spine(null);
    expect(root.getAttribute("data-spine-state")).toBe("none");
    expect(segmentItems(root)).toHaveLength(4);
    expect(root.querySelector('[role="status"]')).toBeNull();
    expect(root.querySelector(".ew-pulse")).toBeNull();
    // The four names, and the honest absence of everything else.
    expect(root.textContent).toContain("Question");
    expect(root.textContent).toContain("Report");
    view.unmount();
  });

  it("carries its own id prefix so a page may hold more than one", () => {
    const view = render(<TraceSpine inputs={EVERY_STATE.succeeded} id="second-spine" />);
    const root = view.container.querySelector("section") as HTMLElement;
    expect(root.id).toBe("second-spine");
    expect(root.getAttribute("aria-labelledby")).toBe("second-spine-label");
    view.unmount();
  });
});

// ---------------------------------------------------------------------------

/** Every file under `web/<dir>`, recursively, as web-relative paths. */
function listFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(join(process.cwd(), dir), { withFileTypes: true })) {
    const relative = `${dir}/${entry.name}`;
    if (entry.isDirectory()) out.push(...listFiles(relative));
    else out.push(relative);
  }
  return out;
}

// The `beforeEach` below keeps the theme attributes the render helper
// writes from leaking between the CSS-reading tests, which read computed
// values off `:root`.
beforeEach(() => {
  document.documentElement.setAttribute("data-theme", "light");
});
