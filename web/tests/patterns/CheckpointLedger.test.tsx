/**
 * CheckpointLedger — WO-15 criterion 2, and the states the spine never
 * shows the ledger in.
 *
 * ==========================================================================
 * CRITERION 2 IS THE ONE THIS FILE EXISTS FOR
 *
 *   "The ledger never contains a label that did not arrive in a
 *    `node_completed` payload" — 03 §5.9 obligation 3, tested against
 *    `reconnect_gap.jsonl`.
 *
 * That recording is not a convenience. Between its two connections a
 * `node_completed` for `searcher` was published with nobody subscribed;
 * Redis pub/sub keeps no backlog (`routes.py:444-454`) and the stream
 * writes no `id:` line (`streaming.py:117-132`), so the frame is gone and
 * the recording's own header says so. The ONLY honest ledger is one that
 * shows `planner`, then nothing, then `synthesizer` — and the property
 * asserted below is the strong one: the string "searcher" never reaches the
 * DOM in ANY state the machine passes through, not merely in the states the
 * assertions happen to sample.
 *
 * The whole path is exercised — recording → `FakeEventSource` →
 * `useJobStream` → the reducer → `spineInputs` → this component — because a
 * ledger that is honest only when fed by hand is not evidence of anything.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { CheckpointLedger } from "@/components/patterns/CheckpointLedger";
import { SPINE } from "@/lib/copy/spine";
import { checkpointName, observedCheckpoint } from "@/lib/copy/trace";
import { observedNode } from "@/lib/job/machine";
import { useJobStream } from "@/lib/job/useJobStream";
import type { JobClient, JobState } from "@/lib/job/types";
import type { JobDetail } from "@/lib/api";
import { spineInputs } from "@/lib/spine/adapter";

import {
  installFakeEventSource,
  loadSseScript,
  onlySource,
  uninstallFakeEventSource,
} from "../support/FakeEventSource";
import { loadFixture } from "../support/handlers";
import { act, cleanup, render, renderHook, screen, within } from "../support/render";
import { THREE, UNLABELLED, checkpoint } from "./spineFixtures";

const RUNNING = loadFixture("job.running").body as JobDetail;
const SUCCEEDED = loadFixture("job.succeeded").body as JobDetail;

/** The label the recording proves was published while nobody was listening. */
const LOST = "searcher";

/** Read a file under `web/`. Vitest runs from there, where its config lives. */
function readSource(relative: string): string {
  return readFileSync(join(process.cwd(), relative), "utf8");
}

// ---------------------------------------------------------------------------
// Criterion 2 — the gap, end to end.
// ---------------------------------------------------------------------------

describe("criterion 2 — the ledger never invents the checkpoint it never saw", () => {
  const details: JobDetail[] = [];
  let client: Partial<JobClient>;

  beforeEach(() => {
    details.length = 0;
    details.push({ ...RUNNING, job_id: "baseline-running" });
    client = {
      getJob: () => Promise.resolve(details.shift() ?? SUCCEEDED),
      streamUrl: (jobId) => `/api/research/${jobId}/stream`,
      // `submitResearch` is never provided and never called: no test here
      // may reach the one billable endpoint.
    };
    installFakeEventSource({ script: "reconnect_gap" });
  });

  afterEach(() => {
    uninstallFakeEventSource();
  });

  it("the recording really is missing the frame — otherwise this proves nothing", () => {
    const script = loadSseScript("reconnect_gap");
    const nodes = script.records
      .filter((record) => record.type === "event")
      .map((record) => (record.data as { node?: string } | null)?.node)
      .filter((node): node is string => typeof node === "string");
    expect(nodes).toEqual(["planner", "synthesizer"]);
    expect(script.connections).toHaveLength(2);
    expect(nodes).not.toContain(LOST);
  });

  it("renders only what arrived, per connection, at every step of the replay", async () => {
    const history: JobState[] = [];
    const { result } = renderHook(() => {
      const controls = useJobStream({ client });
      history.push(controls.state);
      return controls;
    });

    /**
     * Render the ledger for the state as it stands, read it back, and
     * unmount only that view.
     *
     * `unmount()` and not `cleanup()`: Testing Library's `cleanup` unmounts
     * EVERY mounted tree, `renderHook`'s included, which would tear down
     * the stream half way through the replay and freeze the state this
     * test is walking.
     */
    function labelsOnScreen(): string[] {
      const inputs = spineInputs(result.current.state);
      const view = render(
        <CheckpointLedger
          checkpoints={inputs?.observation.checkpoints ?? []}
          current={inputs?.observation.current ?? false}
        />,
      );
      const labels = [...view.container.querySelectorAll("li")].map(
        (item) => item.querySelector("span[aria-hidden]")?.textContent ?? "",
      );
      view.unmount();
      return labels;
    }

    await act(async () => {
      result.current.attach("baseline-running");
    });
    const source = onlySource();

    // -- Connection 0: heartbeat, job_started, node_completed(planner).
    await act(async () => {
      source.play();
    });
    expect(labelsOnScreen()).toEqual(["planner"]);

    // -- The drop. The ticks are KEPT — they really were observed — and
    //    `current` goes false, which is what stops the surface implying
    //    they describe now (03 §5.4, "ticks kept, then a broken rule").
    await act(async () => {
      source.endConnection();
    });
    expect(labelsOnScreen()).toEqual(["planner"]);
    expect(spineInputs(result.current.state)?.observation.current).toBe(false);

    // -- The browser's own retry. Rule 2: a new connection observes
    //    nothing until it says so itself, so the ledger empties. It does
    //    NOT acquire `searcher`, which is the frame that was lost.
    await act(async () => {
      source.reopen();
    });
    expect(labelsOnScreen()).toEqual([]);
    expect(observedNode(result.current.state)).toBeNull();

    // -- Connection 1: heartbeat, node_completed(synthesizer).
    await act(async () => {
      source.playNext();
    });
    expect(labelsOnScreen()).toEqual(["synthesizer"]);

    // -- Connection 1: job_completed.
    await act(async () => {
      source.playNext();
    });

    // THE property, over every state the machine passed through rather
    // than the five this test happened to sample.
    expect(history.length).toBeGreaterThan(5);
    for (const state of history) {
      const inputs = spineInputs(state);
      const view = render(
        <CheckpointLedger checkpoints={inputs?.observation.checkpoints ?? []} />,
      );
      expect(view.container.textContent ?? "").not.toContain(LOST);
      // And every entry on screen is one that really arrived in a
      // `node_completed` payload on the connection that is open now.
      const shown = [...view.container.querySelectorAll("li")].map(
        (item) => item.getAttribute("data-checkpoint-index") ?? "",
      );
      expect(shown).toEqual(
        (inputs?.observation.checkpoints ?? []).map((_, index) => String(index)),
      );
      view.unmount();
    }
  });
});

// ---------------------------------------------------------------------------
// The component's own rules.
// ---------------------------------------------------------------------------

describe("the ledger has no vocabulary of its own", () => {
  it("renders exactly the entries it was given, in receive order, verbatim", () => {
    render(<CheckpointLedger checkpoints={THREE} />);
    const items = screen.getAllByRole("listitem");
    // The clipped sentence, then the visible label: "observed planner" for
    // a screen reader, `planner` on screen, and the qualifier travelling
    // with the name either way (03 §5.5).
    expect(items.map((item) => item.textContent)).toEqual(
      ["planner", "searcher", "synthesizer"].map(
        (node) => `${observedCheckpoint(node)}${checkpointName(node)}`,
      ),
    );
  });

  it("passes an opaque label through untouched (H11)", () => {
    // `claim_decomposer` is not a node in today's graph, and the
    // supervisor graph's set is configuration-dependent anyway. There is
    // nothing to look it up in and nothing that could reject it.
    render(<CheckpointLedger checkpoints={[checkpoint("claim_decomposer")]} />);
    expect(screen.getByText("claim_decomposer")).toBeInTheDocument();
  });

  it("says 'not reported' — never 'unknown' — for a payload that named nothing", () => {
    // WO-10's KNOWN ISSUE, closed here: `checkpointLabel()` still returns
    // the literal "unknown" and is a diagnostic; the surface renders
    // `checkpointName()`, which is the dictionary's answer.
    render(<CheckpointLedger checkpoints={UNLABELLED} />);
    expect(screen.getByText(checkpointName(""))).toBeInTheDocument();
    expect(screen.getByText("not reported")).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/\bunknown\b/i);
  });

  it("names no node anywhere in its source", () => {
    // A default label, a lookup table or a placeholder would all be a
    // vocabulary, and 03 §5.1 says there is none.
    const source = readSource("components/patterns/CheckpointLedger.tsx");
    for (const node of ["planner", "searcher", "reader", "synthesizer", "critic", "supervisor"]) {
      expect(source, node).not.toContain(`"${node}"`);
    }
  });
});

describe("the states the spine never shows it in", () => {
  it("Empty — states the count in words, with the qualifier that makes it true", () => {
    render(<CheckpointLedger checkpoints={[]} />);
    expect(screen.getByText(SPINE.ledgerEmpty)).toBeInTheDocument();
    expect(SPINE.ledgerEmpty).toContain("on this connection");
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("Empty, hidden — renders nothing at all, which is what the spine asks for", () => {
    const { container } = render(<CheckpointLedger checkpoints={[]} empty="hidden" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("SingleCheckpoint — one entry, one tick", () => {
    render(<CheckpointLedger checkpoints={[checkpoint("planner")]} />);
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByRole("list")).toHaveAttribute("data-checkpoint-count", "1");
  });

  it("Many — pans inside a labelled ScrollRegion rather than reflowing the page", () => {
    const many = Array.from({ length: 24 }, (_, index) => checkpoint(`node_${index}`, index));
    render(<CheckpointLedger checkpoints={many} />);
    const region = screen.getByRole("region", { name: SPINE.ledgerLabel });
    expect(region).toHaveClass("ew-scroll-region");
    // Focusable, or it is a scroll container no keyboard can reach.
    expect(region).toHaveAttribute("tabindex", "0");
    expect(within(region).getAllByRole("listitem")).toHaveLength(24);
  });

  it("carries the connection's currency as data, for the spine's trailing rule", () => {
    render(<CheckpointLedger checkpoints={THREE} current={false} />);
    expect(screen.getByRole("list")).toHaveAttribute("data-current", "false");
    cleanup();
    render(<CheckpointLedger checkpoints={THREE} current />);
    expect(screen.getByRole("list")).toHaveAttribute("data-current", "true");
  });

  it("labels the list with the qualifier, so the count is never a claim about the run", () => {
    render(<CheckpointLedger checkpoints={THREE} />);
    expect(screen.getByRole("list", { name: SPINE.ledgerLabel })).toBeInTheDocument();
  });
});
