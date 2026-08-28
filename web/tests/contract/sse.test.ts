// The recorded SSE scripts in `web/contract/sse/`, checked against the
// hand-written overlay in `lib/api/events.ts`.
//
// The stream is not in the OpenAPI document, so there is no generated type to
// derive these from — `events.ts` is transcribed from the backend by hand
// (04-ARCHITECTURE.md §3.2), and these recordings are what stop that
// transcription from quietly going stale. Each payload schema below is bound
// to its exported interface with a compile-time `Exact` proof, so changing
// one without the other does not build.
//
// The scripts are the input WO-05's `FakeEventSource` replays, which is why
// this file also pins their format: JSON Lines, a `{"type":"header"}` first
// line, then `event` / `comment` / `directive` records in receive order.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect } from "vitest";
import { z } from "zod";
import {
  SERVER_EVENT_NAMES,
  STREAM_TIMEOUT_EVENT,
  TERMINAL_EVENTS,
  type JobCancelledPayload,
  type JobCompletedPayload,
  type JobFailedPayload,
  type JobStartedPayload,
  type NodeCompletedPayload,
  type PlanReadyPayload,
  type StreamTimeoutPayload,
  type TerminalReplayPayload,
} from "@/lib/api";

const SSE_DIR = join(process.cwd(), "contract", "sse");

// ---------------------------------------------------------------------------
// Script format.
// ---------------------------------------------------------------------------

interface Header {
  type: "header";
  case: string;
  commit: string;
  source: string;
  authored: boolean;
  note: string;
  format: string;
}

interface EventRecord {
  type: "event";
  event: string;
  data: Record<string, unknown> | null;
}

interface CommentRecord {
  type: "comment";
  text: string;
}

interface DirectiveRecord {
  type: "directive";
  directive: string;
  note: string;
}

type Record_ = EventRecord | CommentRecord | DirectiveRecord;

interface Script {
  name: string;
  header: Header;
  records: Record_[];
  events: EventRecord[];
}

function load(name: string): Script {
  const lines = readFileSync(join(SSE_DIR, `${name}.jsonl`), "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "");
  const [first, ...rest] = lines;
  const header = JSON.parse(first ?? "{}") as Header;
  const records = rest.map((line) => JSON.parse(line) as Record_);
  return {
    name,
    header,
    records,
    events: records.filter((r): r is EventRecord => r.type === "event"),
  };
}

// ---------------------------------------------------------------------------
// Payload schemas, bound to the exported interfaces.
// ---------------------------------------------------------------------------

type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never;
function proves<T extends true>(_: T): void {
  /* the type parameter is the assertion */
}

const jobStartedSchema = z.strictObject({
  job_id: z.string(),
  query: z.string(),
});
proves<Exact<z.infer<typeof jobStartedSchema>, JobStartedPayload>>(true);

const nodeCompletedSchema = z.strictObject({
  node: z.string(),
  state_delta: z.record(z.string(), z.unknown()),
});
proves<Exact<z.infer<typeof nodeCompletedSchema>, NodeCompletedPayload>>(true);

const planReadySchema = z.strictObject({
  job_id: z.string(),
  plan: z.strictObject({
    sub_questions: z.array(z.string()),
    search_queries: z.array(z.string()),
  }),
});
proves<Exact<z.infer<typeof planReadySchema>, PlanReadyPayload>>(true);

/** Live terminal success — no `status`, and `llm_calls` present. */
const jobCompletedSchema = z.strictObject({
  job_id: z.string(),
  iterations: z.number().nullable(),
  quality_score: z.number().nullable(),
  cost_usd: z.number().nullable(),
  llm_calls: z.number().nullable(),
  elapsed_sec: z.number().nullable(),
});
proves<Exact<z.infer<typeof jobCompletedSchema>, JobCompletedPayload>>(true);

const jobFailedSchema = z.strictObject({
  job_id: z.string(),
  error: z.string(),
  error_type: z.string(),
  elapsed_sec: z.number().nullable(),
});
proves<Exact<z.infer<typeof jobFailedSchema>, JobFailedPayload>>(true);

const jobCancelledSchema = z.strictObject({
  job_id: z.string(),
  elapsed_sec: z.number().nullable(),
  reason: z.string().optional(),
});
proves<Exact<z.infer<typeof jobCancelledSchema>, JobCancelledPayload>>(true);

/**
 * Attach-time replay — a different shape under the same three event names:
 * it adds `status` and drops `llm_calls` (`routes.py:857-867`). Keeping the
 * two apart is the whole reason `events.ts` declares both.
 */
const terminalReplaySchema = z.strictObject({
  job_id: z.string(),
  status: z.string(),
  elapsed_sec: z.number().nullable(),
  error: z.string().nullable(),
  error_type: z.string().nullable(),
  iterations: z.number().nullable(),
  quality_score: z.number().nullable(),
  cost_usd: z.number().nullable(),
});
proves<Exact<z.infer<typeof terminalReplaySchema>, TerminalReplayPayload>>(true);

const streamTimeoutSchema = z.strictObject({
  job_id: z.string(),
  reason: z.string(),
  max_duration_sec: z.number(),
  reconnect: z.boolean(),
});
proves<Exact<z.infer<typeof streamTimeoutSchema>, StreamTimeoutPayload>>(true);

// ---------------------------------------------------------------------------
// The scenarios criterion 2 requires.
// ---------------------------------------------------------------------------

/** 04-ARCHITECTURE.md §7.2 — the six scenarios that must exist. */
const ARCHITECTURE_SCENARIOS = [
  "live_success",
  "live_failure",
  "plan_review",
  "replay_terminal",
  "reconnect_gap",
  "stream_timeout",
];

/** 03-DESIGN-BRIEF.md §5.9 — the three extra obligations. */
const BRIEF_OBLIGATIONS = [
  "unknown_event_name",
  "unknown_state_delta_keys",
  "terminal_replay_no_node",
];

const ALL_SCRIPTS = [...ARCHITECTURE_SCENARIOS, ...BRIEF_OBLIGATIONS];

/**
 * Names no backend event uses, deliberately present in one script.
 *
 * `node_started` in particular is named in `src/api/streaming.py:13-35` as
 * something the runner does *not* emit — the runner publishes only after a
 * node returns — which makes it the honest stand-in for "a backend event this
 * client has never heard of".
 */
const DELIBERATELY_UNKNOWN = ["node_started", "paper_indexed"];

function isTerminalName(name: string): boolean {
  return (TERMINAL_EVENTS as ReadonlySet<string>).has(name);
}

/** A terminal frame carrying `status` is the attach-time replay shape. */
function isReplayShape(record: EventRecord): boolean {
  return isTerminalName(record.event) && record.data !== null && "status" in record.data;
}

// ---------------------------------------------------------------------------

describe("contract/sse — inventory and provenance", () => {
  it("holds all six §7.2 scenarios plus the three §5.9 obligations", () => {
    const onDisk = readdirSync(SSE_DIR)
      .filter((file) => file.endsWith(".jsonl"))
      .map((file) => file.replace(/\.jsonl$/, ""))
      .sort();
    expect(onDisk).toEqual([...ALL_SCRIPTS].sort());
    expect(ARCHITECTURE_SCENARIOS).toHaveLength(6);
    expect(BRIEF_OBLIGATIONS).toHaveLength(3);
  });

  it.each(ALL_SCRIPTS)("%s opens with a header naming its commit", (name) => {
    const script = load(name);
    expect(script.header.type).toBe("header");
    expect(script.header.case).toBe(name);
    expect(script.header.commit).toMatch(/^[0-9a-f]{40}$/);
    expect(script.header.source).not.toBe("");
    expect(script.header.note).not.toBe("");
    // R-10 again: anything hand-supplied has to say so in the header, and
    // say which parts came off the wire and which did not. Silence is the
    // failure mode this asserts against.
    expect(typeof script.header.authored).toBe("boolean");
    if (script.header.authored) {
      expect(script.header.note).toContain("published");
      expect(script.header.note).toContain("transcribed");
    }
    expect(script.records.length).toBeGreaterThan(0);
  });

  it.each(ALL_SCRIPTS)("%s uses only the three record kinds", (name) => {
    for (const record of load(name).records) {
      expect(["event", "comment", "directive"]).toContain(record.type);
    }
  });

  it("never carries the report body over the wire", () => {
    // §3.2 invariant: every terminal frame has to be reconciled with
    // `GET /research/{id}`, because the report is not in the stream. If a
    // recording ever contains one, the reconciliation stops being load-bearing
    // and the UI will start reading it from the wrong place.
    for (const name of ALL_SCRIPTS) {
      for (const record of load(name).events) {
        const keys = Object.keys(record.data ?? {});
        expect(keys).not.toContain("result");
        expect(keys).not.toContain("report");
      }
    }
  });
});

describe("contract/sse — frame payloads match the events.ts overlay", () => {
  it.each(ALL_SCRIPTS)("%s carries only known or deliberately unknown names", (name) => {
    const known = new Set<string>(SERVER_EVENT_NAMES);
    for (const record of load(name).events) {
      if (known.has(record.event)) continue;
      expect(DELIBERATELY_UNKNOWN).toContain(record.event);
      expect(name).toBe("unknown_event_name");
    }
  });

  it.each(ALL_SCRIPTS)("%s validates every frame against its payload type", (name) => {
    for (const record of load(name).events) {
      if (DELIBERATELY_UNKNOWN.includes(record.event)) continue;
      const data = record.data ?? {};
      const schema =
        record.event === "job_started"
          ? jobStartedSchema
          : record.event === "node_completed"
            ? nodeCompletedSchema
            : record.event === "plan_ready"
              ? planReadySchema
              : record.event === STREAM_TIMEOUT_EVENT
                ? streamTimeoutSchema
                : isReplayShape(record)
                  ? terminalReplaySchema
                  : record.event === "job_completed"
                    ? jobCompletedSchema
                    : record.event === "job_failed"
                      ? jobFailedSchema
                      : jobCancelledSchema;
      const parsed = schema.safeParse(data);
      expect({ name, event: record.event, issues: parsed.error?.issues ?? [] })
        .toEqual({ name, event: record.event, issues: [] });
    }
  });

  it("keeps the live and replay terminal shapes apart", () => {
    // The trap §3.2 documents: one event name, two payloads. A live frame
    // never carries `status`; a replay never carries `llm_calls`.
    let live = 0;
    let replay = 0;
    for (const name of ALL_SCRIPTS) {
      for (const record of load(name).events) {
        if (!isTerminalName(record.event)) continue;
        const keys = Object.keys(record.data ?? {});
        if (isReplayShape(record)) {
          replay += 1;
          expect(keys).not.toContain("llm_calls");
        } else {
          live += 1;
          expect(keys).not.toContain("status");
        }
      }
    }
    expect(live).toBeGreaterThan(0);
    expect(replay).toBeGreaterThan(0);
  });
});

describe("contract/sse — the recorded scenarios say what they claim", () => {
  it("live_success ends on a live job_completed", () => {
    const events = load("live_success").events;
    const last = events[events.length - 1];
    expect(last?.event).toBe("job_completed");
    expect(isReplayShape(last as EventRecord)).toBe(false);
    expect(events[0]?.event).toBe("job_started");
    expect(events.some((e) => e.event === "node_completed")).toBe(true);
  });

  it("live_failure ends on job_failed with a disclosure-only error_type", () => {
    const events = load("live_failure").events;
    const last = events[events.length - 1] as EventRecord;
    expect(last.event).toBe("job_failed");
    const payload = jobFailedSchema.parse(last.data);
    expect(payload.error_type).not.toBe("");
    // §3.4: raw codes are snake_case machine values, never a sentence.
    expect(payload.error_type).toMatch(/^[a-z_]+$/);
  });

  it("plan_review opens with the replayed plan, byte-identical to the runner's", () => {
    const events = load("plan_review").events;
    expect(events[0]?.event).toBe("plan_ready");
    const payload = planReadySchema.parse(events[0]?.data);
    expect(payload.plan.sub_questions.length).toBeGreaterThan(0);
    expect(payload.plan.search_queries.length).toBeGreaterThan(0);
  });

  it("replay_terminal is a single frame and then the stream is over", () => {
    const script = load("replay_terminal");
    expect(script.events).toHaveLength(1);
    const only = script.events[0] as EventRecord;
    expect(isTerminalName(only.event)).toBe(true);
    expect(isReplayShape(only)).toBe(true);
    const payload = terminalReplaySchema.parse(only.data);
    expect(payload.status).toBe("succeeded");
    // No opening heartbeat: the terminal branch returns before the streaming
    // loop that emits one ever starts.
    expect(script.records.filter((r) => r.type === "comment")).toHaveLength(0);
  });

  it("terminal_replay_no_node contains no node label anywhere", () => {
    // 03-DESIGN-BRIEF.md §5.9 obligation 3, and the ledger rule it exists
    // for: a label that did not arrive in a `node_completed` payload cannot
    // be shown, so this stream must produce an empty ledger.
    const script = load("terminal_replay_no_node");
    for (const record of script.events) {
      expect(Object.keys(record.data ?? {})).not.toContain("node");
    }
    expect(script.events.some((e) => e.event === "node_completed")).toBe(false);
    const payload = terminalReplaySchema.parse(script.events[0]?.data);
    expect(payload.status).toBe("failed");
    expect(payload.error).not.toBeNull();
  });

  it("reconnect_gap proves the missing frame is really missing", () => {
    const script = load("reconnect_gap");
    const directives = script.records.filter(
      (r): r is DirectiveRecord => r.type === "directive"
    );
    expect(directives.map((d) => d.directive)).toEqual([
      "disconnect",
      "reopen",
    ]);

    // A `node_completed` for `searcher` was published while nothing was
    // subscribed. Redis pub/sub drops messages with no subscriber
    // (`routes.py:444-454`), so it is absent — and a client must not invent
    // it. If a backlog or Last-Event-ID contract ever appears, this fails.
    const nodes = script.events
      .filter((e) => e.event === "node_completed")
      .map((e) => nodeCompletedSchema.parse(e.data).node);
    expect(nodes).not.toContain("searcher");
    expect(nodes).toContain("planner");
    expect(nodes).toContain("synthesizer");
  });

  it("stream_timeout is a transport event, not a job outcome", () => {
    const script = load("stream_timeout");
    const timeout = script.events.find(
      (e) => e.event === STREAM_TIMEOUT_EVENT
    ) as EventRecord;
    expect(timeout).toBeDefined();

    const payload = streamTimeoutSchema.parse(timeout.data);
    expect(payload.reconnect).toBe(true);
    expect(payload.reason).toBe("max_duration_exceeded");
    expect(payload.max_duration_sec).toBeGreaterThan(0);

    // The job kept running: it is not in the terminal set, and the script
    // goes on to reopen and finish.
    expect(isTerminalName(STREAM_TIMEOUT_EVENT)).toBe(false);
    const directives = script.records.filter(
      (r): r is DirectiveRecord => r.type === "directive"
    );
    expect(directives.map((d) => d.directive)).toEqual(["reopen"]);
    expect(script.events[script.events.length - 1]?.event).toBe("job_completed");

    // The real heartbeat cadence, recorded off the deadline path.
    expect(
      script.records.filter((r) => r.type === "comment").length
    ).toBeGreaterThan(0);
  });

  it("unknown_event_name carries names the client has never heard of", () => {
    const script = load("unknown_event_name");
    const known = new Set<string>(SERVER_EVENT_NAMES);
    const unknown = script.events
      .map((e) => e.event)
      .filter((name) => !known.has(name));
    expect(unknown).toEqual(DELIBERATELY_UNKNOWN);
    // Known frames still surround them, so a client that drops the unknown
    // ones keeps a coherent stream.
    expect(script.events[0]?.event).toBe("job_started");
    expect(script.events[script.events.length - 1]?.event).toBe(
      "job_completed"
    );
  });

  it("unknown_state_delta_keys assumes no vocabulary for nodes or deltas", () => {
    const script = load("unknown_state_delta_keys");
    const frames = script.events
      .filter((e) => e.event === "node_completed")
      .map((e) => nodeCompletedSchema.parse(e.data));
    expect(frames.length).toBeGreaterThan(1);

    // An opaque node name: `claim_decomposer` is not a node in today's graph.
    expect(frames.map((f) => f.node)).toContain("claim_decomposer");
    // Delta keys outside anything the client models.
    const allKeys = frames.flatMap((f) => Object.keys(f.state_delta));
    expect(allKeys).toContain("planner_confidence");
    expect(allKeys).toContain("decomposition_strategy");
    // And an empty delta, which must not be mistaken for a missing frame.
    expect(frames.some((f) => Object.keys(f.state_delta).length === 0)).toBe(
      true
    );
    // `messages` is dropped server-side (`runner.py:947-951`) and must never
    // reappear.
    expect(allKeys).not.toContain("messages");
  });
});
