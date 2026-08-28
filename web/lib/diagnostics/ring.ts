// The client-side diagnostics ring buffer (04 §9.2 item 1, WO-16 c5).
//
// "The last 200 lifecycle records — event name, receive timestamp, job id,
// machine transition, normalized `ApiFailure.kind` — held in memory only,
// cleared on reload."
//
// MEMORY ONLY IS A STRUCTURAL CLAIM, NOT A COMMENT. There is no
// `localStorage`, no `sessionStorage`, no `indexedDB`, no cookie and no
// `caches` call anywhere in this directory, and
// `web/tests/diagnostics/ring.test.ts` asserts that against the source text
// as well as against behaviour. The buffer is a module-scope array; a
// reload evaluates a fresh module and gets an empty one, which is the whole
// of "cleared on reload" and the only version of it that cannot drift.
//
// WHY A SEPARATE BUFFER FROM `JobState.frames`. The machine already keeps a
// receive-ordered frame log capped at `MAX_FRAMES` (`lib/job/machine.ts`),
// and that log is per-machine, per-route and reducer-owned: it holds frames
// and nothing else, it is discarded when the provider unmounts, and it
// resets with the machine. §9.2's record is wider — a phase change, a
// connection break and a normalized failure are lifecycle records that
// carry no frame — and it has to survive across the job the user is
// looking at, because the interesting incident is usually the one BEFORE
// the current attach. So this observes the machine rather than living
// inside it, through the `subscribe`/`getSnapshot` seam
// `lib/job/provider.tsx` exposes for exactly this kind of consumer.
//
// H11 IS PRESERVED BY DOING NOTHING. Event names, node labels and
// `state_delta` keys are copied through as opaque strings. Nothing here
// validates a name against a vocabulary, and nothing here parses a delta —
// `unknown_event_name.jsonl` and `unknown_state_delta_keys.jsonl` are
// replayed through the real harness in
// `web/tests/diagnostics/Diagnostics.test.tsx` to prove it.

import type {
  ConnectionPhase,
  JobPhase,
  JobState,
} from "@/lib/job/types";

import { RING_CAPACITY } from "./constants";

export { RING_CAPACITY };

/**
 * What produced a record.
 *
 * Six kinds rather than one `event` string, because the redactor and the
 * table both branch on provenance: a `frame`'s detail is a server payload
 * and is treated as hostile, a `vital`'s is three numbers this page
 * measured about itself.
 */
export const DIAGNOSTIC_KINDS = [
  "frame",
  "transition",
  "connection",
  "terminal",
  "failure",
  "vital",
] as const;

export type DiagnosticKind = (typeof DIAGNOSTIC_KINDS)[number];

/**
 * One lifecycle record.
 *
 * `event` is verbatim: a frame name off the wire, a machine phase, a
 * connection phase, or a metric name. It is never mapped, never validated
 * and never rendered through a vocabulary (H11).
 */
export interface DiagnosticRecord {
  /** Monotonic, assigned by the ring. Survives the buffer wrapping. */
  seq: number;
  /** Receive time, in epoch milliseconds. */
  at: number;
  kind: DiagnosticKind;
  /** The verbatim name. Never mapped (H11). */
  event: string;
  /** The run this record is about, or `null` before one is adopted. */
  jobId: string | null;
  /** The machine's phase when the record was taken. */
  phase: JobPhase;
  /** What it moved FROM, for `transition` and `connection` records. */
  from: string | null;
  /** The normalized `ApiFailure.kind`, never the raw body. */
  failureKind: string | null;
  /**
   * Everything else, as an open map.
   *
   * Copied through untouched — including `state_delta` keys no client has
   * heard of. Redaction happens on the way OUT (`redact.ts`), never on the
   * way in, so what the table renders is what the stream actually sent.
   */
  detail: Record<string, unknown> | null;
}

/** A record before the ring assigns it a sequence number. */
export type DiagnosticInput = Omit<DiagnosticRecord, "seq">;

/** Fill in the fields a caller usually does not care about. */
function record(input: Partial<DiagnosticInput> & Pick<DiagnosticInput, "kind" | "event" | "at" | "phase">): DiagnosticInput {
  return {
    jobId: null,
    from: null,
    failureKind: null,
    detail: null,
    ...input,
  };
}

// ---------------------------------------------------------------------------
// The buffer.
// ---------------------------------------------------------------------------

/**
 * A fixed-capacity, in-memory, append-only-with-wrap record buffer.
 *
 * A real ring — one array of `capacity` slots and a write cursor — rather
 * than `push()` + `slice(-200)`. At 200 records and a frame every few
 * seconds the difference in cost is nothing; the difference that matters is
 * that a ring cannot grow, so a stream that misbehaves for an hour cannot
 * turn the diagnostics buffer into the memory leak it exists to help
 * diagnose.
 *
 * `getSnapshot()` returns a cached, stable array reference so the class
 * satisfies `useSyncExternalStore`'s contract directly: the same snapshot
 * is returned until something is pushed, and React therefore does not
 * re-render forever.
 */
export class DiagnosticsRing {
  readonly capacity: number;

  private readonly slots: (DiagnosticRecord | undefined)[];
  /** Where the next record goes. */
  private cursor = 0;
  /** How many have ever been pushed. `seq` comes from here. */
  private written = 0;
  private listeners = new Set<() => void>();
  private snapshot: readonly DiagnosticRecord[] = [];

  constructor(capacity: number = RING_CAPACITY) {
    if (!Number.isInteger(capacity) || capacity <= 0) {
      throw new Error(
        `DiagnosticsRing: capacity must be a positive integer, received ` +
          `${String(capacity)}. 04 §9.2 fixes it at ${RING_CAPACITY}.`,
      );
    }
    this.capacity = capacity;
    this.slots = new Array<DiagnosticRecord | undefined>(capacity);
  }

  /** How many records the buffer currently holds. Never above `capacity`. */
  get size(): number {
    return Math.min(this.written, this.capacity);
  }

  /** How many fell off the end. `0` until the buffer has wrapped once. */
  get dropped(): number {
    return Math.max(0, this.written - this.capacity);
  }

  /** Append one record and return it, with its assigned `seq`. */
  push(input: DiagnosticInput): DiagnosticRecord {
    const stored: DiagnosticRecord = { ...input, seq: this.written };
    this.slots[this.cursor] = stored;
    this.cursor = (this.cursor + 1) % this.capacity;
    this.written += 1;
    this.snapshot = this.read();
    this.emit();
    return stored;
  }

  /** Append several, notifying listeners once rather than per record. */
  pushAll(inputs: readonly DiagnosticInput[]): DiagnosticRecord[] {
    if (inputs.length === 0) return [];
    const stored: DiagnosticRecord[] = [];
    for (const input of inputs) {
      const entry: DiagnosticRecord = { ...input, seq: this.written };
      this.slots[this.cursor] = entry;
      this.cursor = (this.cursor + 1) % this.capacity;
      this.written += 1;
      stored.push(entry);
    }
    this.snapshot = this.read();
    this.emit();
    return stored;
  }

  /** Oldest first. A fresh array; the caller may not mutate the buffer. */
  records(): readonly DiagnosticRecord[] {
    return this.snapshot;
  }

  /** `useSyncExternalStore`'s getter. Stable between pushes, by contract. */
  getSnapshot = (): readonly DiagnosticRecord[] => this.snapshot;

  /** `useSyncExternalStore`'s subscriber. */
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /** Drop everything, including the sequence counter. */
  clear(): void {
    this.slots.fill(undefined);
    this.cursor = 0;
    this.written = 0;
    this.snapshot = [];
    this.emit();
  }

  private read(): readonly DiagnosticRecord[] {
    if (this.written <= this.capacity) {
      return this.slots.slice(0, this.written) as DiagnosticRecord[];
    }
    return [
      ...(this.slots.slice(this.cursor) as DiagnosticRecord[]),
      ...(this.slots.slice(0, this.cursor) as DiagnosticRecord[]),
    ];
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}

/**
 * The one buffer the product uses.
 *
 * Module scope is what makes "cleared on reload" true: a reload evaluates
 * this module again and gets a new, empty `DiagnosticsRing`. There is no
 * hydration path, no persistence and nothing to restore.
 */
export const diagnosticsRing = new DiagnosticsRing();

// ---------------------------------------------------------------------------
// Deriving records from the machine.
// ---------------------------------------------------------------------------

/**
 * Every record a machine state change produced, oldest first.
 *
 * A pure function over two snapshots rather than a listener wired into the
 * reducer, for the reason `lib/job/provider.tsx` gives for its own seam:
 * the machine must not know that diagnostics exist. WO-20 hands this the
 * provider's `subscribe`/`getSnapshot` pair and nothing else changes.
 *
 * `at` is the wall clock at observation time and is used only for the
 * records that carry no timestamp of their own — a frame uses its own
 * `receivedAt`, and a terminal signal uses the signal's.
 */
export function recordsFromTransition(
  previous: JobState | null,
  next: JobState,
  at: number,
): DiagnosticInput[] {
  const out: DiagnosticInput[] = [];
  const jobId = next.jobId;
  const phase = next.phase;

  // -- Frames, by object identity ------------------------------------------
  //
  // Not by length: `withFrame` caps the log at MAX_FRAMES, so once it is
  // full the length stops changing while the contents keep moving. The
  // reducer builds `[...state.frames, frame]`, so every surviving frame
  // keeps its reference and set membership is exact.
  const seen = new Set(previous?.frames ?? []);
  for (const frame of next.frames) {
    if (seen.has(frame)) continue;
    out.push(
      record({
        kind: "frame",
        event: frame.name,
        at: frame.receivedAt,
        jobId,
        phase,
        detail: frame.data,
      }),
    );
  }

  // -- The terminal signal's SHAPE -----------------------------------------
  //
  // `lib/job/types.ts` records it "for the diagnostics disclosure (WO-16)"
  // and says it "is never rendered as a value". It is not: it is rendered
  // as evidence of which of the three shapes of one event name arrived
  // (live `job_completed` carries `llm_calls` and no `status`; the replay
  // carries `status` and no `llm_calls`), which is exactly the asymmetry a
  // bug report needs and the surface must never read a value out of.
  if (next.terminal !== null && next.terminal !== previous?.terminal) {
    out.push(
      record({
        kind: "terminal",
        event: next.terminal.name,
        at: next.terminal.receivedAt,
        jobId,
        phase,
        detail: { shape: next.terminal.shape },
      }),
    );
  }

  // -- Connection ----------------------------------------------------------
  if (previous !== null && previous.connection !== next.connection) {
    out.push(
      record({
        kind: "connection",
        event: next.connection satisfies ConnectionPhase,
        at,
        jobId,
        phase,
        from: previous.connection,
      }),
    );
  }

  // -- The machine's own transition ----------------------------------------
  if (previous !== null && previous.phase !== next.phase) {
    out.push(
      record({
        kind: "transition",
        event: next.phase satisfies JobPhase,
        at,
        jobId,
        phase,
        from: previous.phase,
      }),
    );
  }

  // -- Failures ------------------------------------------------------------
  //
  // The normalized kind and the status, plus the raw message — which
  // `DIAGNOSTICS.copyNote` promises is copied ("the raw error strings") and
  // RC-16 requires stay unedited. `redact.ts` scrubs URLs out of it on the
  // way to the clipboard; it is never edited here.
  if (next.failure !== null && next.failure !== previous?.failure) {
    out.push(
      record({
        kind: "failure",
        event: next.failureSource ?? next.failure.kind,
        at,
        jobId,
        phase,
        failureKind: next.failure.kind,
        detail: {
          status: next.failureStatus,
          error: next.failureMessage,
        },
      }),
    );
  }

  return out;
}
