// The suite's ONE EventSource stub (04-ARCHITECTURE.md §7.2).
//
// jsdom has no `EventSource`, and MSW's SSE support does not reach a polyfill
// the app never installs. So every tier below Playwright replays the *recorded*
// frame scripts in `web/contract/sse/` through this class instead of inventing
// frames inline. `web/tests/support/FakeEventSource.test.ts` asserts that no
// other stub exists anywhere under `web/tests/`.
//
// Three properties of the recordings drive the design, and getting any of them
// wrong turns a passing test into a lie:
//
//   1. **Directives are connection boundaries, not decoration.**
//      `reconnect_gap.jsonl` and `stream_timeout.jsonl` each hold TWO
//      connections' frames in one file. Replaying such a file start-to-finish
//      would hand the client frames the recording proves were LOST — there is
//      no replay backlog and no `Last-Event-ID` contract, because Redis
//      pub/sub drops messages with no subscriber (`routes.py:444-454`). So the
//      script is segmented at its directives and a connection can only ever
//      deliver its own segment. Crossing a boundary is an explicit
//      `endConnection()` + `reopen()`, which is what a real browser does.
//
//   2. **Comments are heartbeats and must vanish.** `: heartbeat` lines keep
//      the socket warm; a real `EventSource` never surfaces them. They are
//      consumed and counted (`heartbeats`), never dispatched.
//
//   3. **Event names are NOT validated.** `unknown_event_name.jsonl`
//      deliberately carries `node_started` and `paper_indexed`, which are
//      outside `SERVER_EVENT_NAMES` (`streaming.py:13-35` says `node_started`
//      does not exist at all). A stub that checked names against the union
//      could not replay the script that exists to prove unknown names are
//      tolerated. Node names and `state_delta` keys are opaque strings here.

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { TERMINAL_EVENTS } from "@/lib/api";

/** Vitest runs from `web/`, where its config lives. */
export const SSE_DIR = join(process.cwd(), "contract", "sse");

// ---------------------------------------------------------------------------
// Script format — pinned by `web/tests/contract/sse.test.ts` (WO-04).
// ---------------------------------------------------------------------------

/** Line 1 of every `.jsonl` script: where the recording came from. */
export interface ScriptHeader {
  type: "header";
  case: string;
  commit: string;
  source: string;
  authored: boolean;
  note: string;
  format: string;
}

/** One `event:` + `data:` frame off the wire. */
export interface EventRecord {
  type: "event";
  event: string;
  data: Record<string, unknown> | null;
}

/** An SSE comment line — a heartbeat. Never surfaces as an event. */
export interface CommentRecord {
  type: "comment";
  text: string;
}

/** A connection boundary: `disconnect` or `reopen`. */
export interface DirectiveRecord {
  type: "directive";
  directive: string;
  note: string;
}

export type SseRecord = EventRecord | CommentRecord | DirectiveRecord;

/** Everything a single connection can carry. Directives are boundaries. */
export type ConnectionRecord = EventRecord | CommentRecord;

/**
 * How a recorded connection ended.
 *
 * `disconnect` and `server-close` are indistinguishable to the client — both
 * leave a real `EventSource` in `CONNECTING` with `error` dispatched and an
 * automatic retry pending — but the recordings distinguish them, so this does
 * too.
 */
export type ConnectionEnd = "disconnect" | "server-close" | "end-of-script";

export interface RecordedConnection {
  /** 0-based position in the script. */
  index: number;
  /** Frames and heartbeats this connection carried, in receive order. */
  records: ConnectionRecord[];
  endedBy: ConnectionEnd;
  /** The directive's `note`, for diagnostics. `null` at end of script. */
  endedByNote: string | null;
}

export interface SseScript {
  name: string;
  header: ScriptHeader;
  /** Every record after the header, unsegmented. */
  records: SseRecord[];
  /** The same records, split at the directive boundaries. */
  connections: RecordedConnection[];
}

/**
 * The ten recordings on disk.
 *
 * Six are 04-ARCHITECTURE.md §7.2's scenarios; three are
 * 03-DESIGN-BRIEF.md §5.9's obligations. `listSseScripts()` reads the
 * directory, and a test asserts the two agree so this union cannot drift.
 */
export const SSE_SCRIPT_NAMES = [
  "live_success",
  "live_failure",
  "plan_review",
  "replay_terminal",
  "reconnect_gap",
  "stream_timeout",
  "unknown_event_name",
  "unknown_state_delta_keys",
  "terminal_replay_no_node",
  "session_turns",
] as const;

export type SseScriptName = (typeof SSE_SCRIPT_NAMES)[number];

/** Script names actually on disk, sorted. */
export function listSseScripts(): string[] {
  return readdirSync(SSE_DIR)
    .filter((file) => file.endsWith(".jsonl"))
    .map((file) => file.replace(/\.jsonl$/, ""))
    .sort();
}

/**
 * Split a record stream into connections at its directives.
 *
 * `disconnect` ends the current connection (the client dropped).
 * `reopen` either consumes a pending disconnect boundary, or — when no
 * disconnect preceded it — ends the current connection as a server close,
 * which is the `stream_timeout` shape: the server emits the frame and closes
 * the response itself.
 */
function segment(records: SseRecord[]): RecordedConnection[] {
  const connections: RecordedConnection[] = [];
  let current: ConnectionRecord[] = [];
  let awaitingReopen = false;

  const push = (endedBy: ConnectionEnd, note: string | null): void => {
    connections.push({
      index: connections.length,
      records: current,
      endedBy,
      endedByNote: note,
    });
    current = [];
  };

  for (const record of records) {
    if (record.type === "directive") {
      if (record.directive === "disconnect") {
        push("disconnect", record.note);
        awaitingReopen = true;
        continue;
      }
      if (record.directive === "reopen") {
        if (awaitingReopen) {
          awaitingReopen = false;
        } else {
          push("server-close", record.note);
        }
        continue;
      }
      throw new Error(
        `FakeEventSource: unknown directive "${record.directive}" — the ` +
          "script format allows only disconnect and reopen"
      );
    }
    current.push(record);
  }

  push("end-of-script", null);
  return connections;
}

/** Read and segment one recording. */
export function loadSseScript(name: SseScriptName): SseScript {
  const lines = readFileSync(join(SSE_DIR, `${name}.jsonl`), "utf8")
    .split("\n")
    .filter((line) => line.trim() !== "");
  const [first, ...rest] = lines;
  const header = JSON.parse(first ?? "{}") as ScriptHeader;
  if (header.type !== "header") {
    throw new Error(`FakeEventSource: ${name}.jsonl does not open with a header`);
  }
  const records = rest.map((line) => JSON.parse(line) as SseRecord);
  return { name, header, records, connections: segment(records) };
}

// ---------------------------------------------------------------------------
// Terminal payload shapes.
//
// Three event names, two payloads: a LIVE frame has `llm_calls` and no
// `status` (`runner.py:1278-1288`); an attach-time REPLAY has `status` and no
// `llm_calls` (`routes.py:857-867`). This is the discriminator
// `web/tests/contract/sse.test.ts` already uses — same predicate, one home.
// ---------------------------------------------------------------------------

export function isTerminalFrame(record: EventRecord): boolean {
  return (TERMINAL_EVENTS as ReadonlySet<string>).has(record.event);
}

/** A terminal frame carrying `status` is the attach-time replay shape. */
export function isReplayShape(record: EventRecord): boolean {
  return (
    isTerminalFrame(record) && record.data !== null && "status" in record.data
  );
}

/** A terminal frame with no `status` is a live outcome. */
export function isLiveShape(record: EventRecord): boolean {
  return isTerminalFrame(record) && !isReplayShape(record);
}

// ---------------------------------------------------------------------------
// The stub.
// ---------------------------------------------------------------------------

/**
 * A scriptable stand-in for the browser's `EventSource`.
 *
 * Two modes:
 *
 *   - **Manual** (no script installed): drive it by hand with `emit`, `open`,
 *     `transientDrop`, `fatal`, `serverClose`. This is what the pre-existing
 *     `ConversationThread` tests use.
 *   - **Scripted** (`installFakeEventSource({ script })`): each instance
 *     adopts the next unconsumed connection of the recording and replays it
 *     with `playNext` / `play` / `playScript`.
 *
 * `readyState` starts at `OPEN` and no `open` event is dispatched from the
 * constructor: a caller cannot have attached listeners yet, so dispatching
 * there would be unobservable theatre. Call `open()` (or `play`/`playScript`,
 * which do it for you) once listeners are wired.
 */
export class FakeEventSource
  extends EventTarget
  // `implements` so a drift in `readyState`, `url`, `close`, the `on*`
  // handlers or the three constants fails `npm run typecheck` rather than a
  // test somewhere. The two listener methods are omitted because `EventSource`
  // narrows them to `EventSourceEventMap`, while the frames here are named
  // events outside that map — `EventTarget`'s own broader signatures are what
  // this stub needs, and they are behaviourally identical.
  implements Omit<EventSource, "addEventListener" | "removeEventListener">
{
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  /** Every instance constructed since the last install, open or closed. */
  static instances: FakeEventSource[] = [];
  /** The recording new instances replay. `null` is manual mode. */
  static script: SseScript | null = null;
  /** Index of the next connection an instance (or `reopen`) will adopt. */
  static nextConnection = 0;

  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSED = 2;

  readonly url: string;
  /** From the constructor's `EventSourceInit`, as the real thing reports it. */
  readonly withCredentials: boolean;

  readyState: number = FakeEventSource.OPEN;
  /** `close()` was called. The count that matters for double-streaming. */
  closed = false;

  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;

  /** The connection being replayed, or `null` in manual mode. */
  connection: RecordedConnection | null = null;
  /** Heartbeat comments consumed and dropped, as a real EventSource does. */
  heartbeats = 0;
  /** Frames dispatched by this instance, in order. */
  delivered: EventRecord[] = [];

  private cursor = 0;
  /** Whether `open` has been dispatched for the current connection. */
  private opened = false;

  constructor(url: string | URL, init?: EventSourceInit) {
    super();
    this.url = String(url);
    this.withCredentials = init?.withCredentials ?? false;
    const script = FakeEventSource.script;
    if (script !== null) {
      const next = script.connections[FakeEventSource.nextConnection];
      if (next === undefined) {
        throw new Error(
          `FakeEventSource: script "${script.name}" records ` +
            `${script.connections.length} connection(s); a connection at ` +
            `index ${FakeEventSource.nextConnection} was opened. The ` +
            "recording has no frames for it, and inventing some is the bug " +
            "these scripts exist to catch."
        );
      }
      this.connection = next;
      FakeEventSource.nextConnection += 1;
    }
    FakeEventSource.instances.push(this);
  }

  // -- EventSource surface ---------------------------------------------------

  close(): void {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }

  // -- Controls --------------------------------------------------------------

  /** The connection is established: `readyState` OPEN, `open` dispatched. */
  open(): void {
    this.readyState = FakeEventSource.OPEN;
    this.closed = false;
    this.opened = true;
    this.dispatch(new Event("open"));
  }

  /** Deliver one frame by hand, serializing `data` the way the wire does. */
  emit(name: string, data: unknown): void {
    this.emitRaw(name, JSON.stringify(data));
  }

  /**
   * Deliver an already-serialized payload — the seam for malformed JSON,
   * which the client must survive rather than throw on.
   */
  emitRaw(name: string, data: string): void {
    this.dispatch(new MessageEvent(name, { data }));
  }

  /**
   * A transient interruption the browser retries on its own: `readyState`
   * goes to CONNECTING and `error` is dispatched. The client owns no retry
   * here — it may only narrate.
   */
  transientDrop(): void {
    this.readyState = FakeEventSource.CONNECTING;
    this.dispatch(new Event("error"));
  }

  /**
   * The server ended the response body (the `stream_timeout` shape, and the
   * normal end of any SSE response). Indistinguishable from `transientDrop`
   * at the client — the browser reconnects either way — but named separately
   * because the recordings distinguish the two.
   */
  serverClose(): void {
    this.transientDrop();
  }

  /**
   * What a browser does on a non-200 response (the stream route's 404): fail
   * the connection permanently — `readyState` goes to CLOSED and no retry
   * follows.
   */
  fatal(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.dispatch(new Event("error"));
  }

  // -- Scripted replay -------------------------------------------------------

  /** How the recording says the current connection ends. */
  get endedBy(): ConnectionEnd {
    return this.requireConnection().endedBy;
  }

  /** Records left in the current connection, heartbeats included. */
  get remaining(): number {
    return this.requireConnection().records.length - this.cursor;
  }

  /**
   * Deliver the next frame of the current connection.
   *
   * Heartbeats in the way are consumed and counted, never dispatched — which
   * is the whole of a real `EventSource`'s comment handling. Returns `null`
   * once the connection's own records are exhausted; it never reaches into
   * the next connection's frames.
   */
  playNext(): EventRecord | null {
    const connection = this.requireConnection();
    while (this.cursor < connection.records.length) {
      const record = connection.records[this.cursor]!;
      this.cursor += 1;
      if (record.type === "comment") {
        this.heartbeats += 1;
        continue;
      }
      this.delivered.push(record);
      this.emitRaw(record.event, JSON.stringify(record.data));
      return record;
    }
    return null;
  }

  /**
   * Deliver every remaining frame of the CURRENT connection, opening it
   * first if nothing has been played yet. Stops at the boundary.
   */
  play(): EventRecord[] {
    if (!this.opened) this.open();
    const frames: EventRecord[] = [];
    for (let frame = this.playNext(); frame !== null; frame = this.playNext()) {
      frames.push(frame);
    }
    return frames;
  }

  /**
   * End the current connection the way the recording says it ended.
   *
   * A no-op at `end-of-script`: the script simply has nothing more to say,
   * and the client's own terminal handling (or `close()`) owns what happens.
   */
  endConnection(): void {
    const connection = this.requireConnection();
    if (connection.endedBy === "end-of-script") return;
    this.transientDrop();
  }

  /**
   * Reopen onto the NEXT recorded connection and dispatch `open`.
   *
   * The cursor restarts inside that connection's own records, so frames
   * published while nothing was subscribed stay lost — which is precisely
   * what `reconnect_gap.jsonl` records.
   */
  reopen(): this {
    const script = FakeEventSource.script;
    if (script === null) {
      throw new Error(
        "FakeEventSource: reopen() needs a script — install one with " +
          "installFakeEventSource({ script })"
      );
    }
    const next = script.connections[FakeEventSource.nextConnection];
    if (next === undefined) {
      throw new Error(
        `FakeEventSource: script "${script.name}" records ` +
          `${script.connections.length} connection(s) and they are all ` +
          "consumed; there is nothing recorded for another reopen."
      );
    }
    FakeEventSource.nextConnection += 1;
    this.connection = next;
    this.cursor = 0;
    this.opened = false;
    this.open();
    return this;
  }

  /**
   * Replay the whole remaining script on this instance, honouring every
   * boundary: play a connection, fire its recorded ending, reopen onto the
   * next, repeat. Returns the frames actually delivered — never the ones the
   * recording proves were dropped in a gap.
   */
  playScript(): EventRecord[] {
    const frames: EventRecord[] = [];
    for (;;) {
      frames.push(...this.play());
      if (this.endedBy === "end-of-script") break;
      this.endConnection();
      this.reopen();
    }
    return frames;
  }

  // -- Internals -------------------------------------------------------------

  private requireConnection(): RecordedConnection {
    if (this.connection === null) {
      throw new Error(
        "FakeEventSource: no script installed — this instance is in manual " +
          "mode. Use installFakeEventSource({ script: 'live_success' }) to " +
          "replay a recording, or emit() to drive it by hand."
      );
    }
    return this.connection;
  }

  /** Dispatch to `addEventListener` first, then the `on*` property. */
  private dispatch(event: Event): void {
    this.dispatchEvent(event);
    const self = this as unknown as EventSource;
    if (event.type === "open") this.onopen?.call(self, event);
    else if (event.type === "error") this.onerror?.call(self, event);
    else if (event.type === "message") {
      this.onmessage?.call(self, event as MessageEvent);
    }
  }
}

// ---------------------------------------------------------------------------
// Install / uninstall.
// ---------------------------------------------------------------------------

export interface InstallOptions {
  /** A script name from `web/contract/sse/`, or one already loaded. */
  script?: SseScriptName | SseScript;
}

let savedEventSource: typeof globalThis.EventSource | undefined;
let installed = false;

/**
 * Put `FakeEventSource` on `globalThis` and reset its bookkeeping.
 *
 * Idempotent, and safe to call in a `beforeEach`: the real global (jsdom
 * supplies none, so normally `undefined`) is saved once and restored by
 * `uninstallFakeEventSource`, which `web/vitest.setup.ts` runs after every
 * test so a stub can never leak into the next file.
 */
export function installFakeEventSource(
  options: InstallOptions = {}
): typeof FakeEventSource {
  if (!installed) {
    savedEventSource = globalThis.EventSource;
    installed = true;
  }
  FakeEventSource.instances = [];
  FakeEventSource.nextConnection = 0;
  FakeEventSource.script =
    typeof options.script === "string"
      ? loadSseScript(options.script)
      : (options.script ?? null);
  globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  return FakeEventSource;
}

/** Restore the real global and drop every recorded instance. */
export function uninstallFakeEventSource(): void {
  if (!installed) return;
  globalThis.EventSource = savedEventSource as typeof EventSource;
  installed = false;
  FakeEventSource.instances = [];
  FakeEventSource.script = null;
  FakeEventSource.nextConnection = 0;
}

/** `true` while the stub owns `globalThis.EventSource`. */
export function isFakeEventSourceInstalled(): boolean {
  return installed;
}

/** Every source constructed since install, open or closed. */
export function allSources(): FakeEventSource[] {
  return FakeEventSource.instances;
}

/** Sources not yet closed — the count that matters for double-streaming. */
export function openSources(): FakeEventSource[] {
  return FakeEventSource.instances.filter((source) => !source.closed);
}

/** The single open source, asserting there is exactly one. */
export function onlySource(): FakeEventSource {
  const open = openSources();
  if (open.length !== 1) {
    throw new Error(
      `FakeEventSource: expected exactly one open source, found ${open.length}`
    );
  }
  return open[0]!;
}
