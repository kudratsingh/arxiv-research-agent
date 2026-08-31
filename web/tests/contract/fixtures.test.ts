// Drift check 3 of 4 (04-ARCHITECTURE.md §3.5): every recorded fixture is
// parsed by the typed client and validated against a Zod schema derived from
// the generated OpenAPI types.
//
// "Derived" is load-bearing and is enforced twice over:
//
//   1. `proves<Exact<z.infer<typeof schema>, Model>>(true)` fails to COMPILE
//      if the schema and the generated model stop describing the same shape —
//      in either direction, so neither a dropped field nor an invented one
//      survives `npm run typecheck`.
//   2. `.strictObject` fails at RUNTIME if a recorded body carries a key the
//      schema does not know about, which is what catches a backend that has
//      started sending something new.
//
// Check 2 (`npm run contract:check`) already proves the generated types match
// the committed OpenAPI snapshot, and check 1 (Python) proves that snapshot
// matches the live FastAPI document. This file closes the loop at the other
// end: real response bodies, through the real client, against those types.
//
// It also covers what OpenAPI does not describe at all — the seven error
// envelopes — because that is precisely where §3.5 says generation alone
// produces false confidence (R-06).

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { z } from "zod";
import {
  API_FAILURE_KINDS,
  ApiError,
  getConversation,
  getJob,
  legacyDetailMessage,
  listConversations,
  normalizeFailure,
  readErrorBody,
  type ApiFailureKind,
  type ConversationDetail,
  type ConversationListItem,
  type JobDetail,
  type JobStatus,
  type LearnerProfile,
  type LearnerProgressSummary,
  type Plan,
  type ProgressDailySessions,
  type ProgressEvidence,
  type ProgressSchedule,
} from "@/lib/api";

// Vitest runs from `web/`, where its config lives.
const FIXTURE_DIR = join(process.cwd(), "contract", "fixtures");

// ---------------------------------------------------------------------------
// The fixture envelope.
// ---------------------------------------------------------------------------

interface Recording {
  note: string;
  case: string;
  commit: string;
  request: string;
  transport: string;
  stack: string;
  authored: boolean;
  /** Present when anything in the file was authored rather than recorded. */
  authored_reason?: string;
  /** Present when one recorded value legitimately moves between runs. */
  volatile?: string;
}

interface Fixture {
  name: string;
  keys: string[];
  recording: Recording;
  status: number;
  statusText: string;
  headers: Record<string, string>;
  body: unknown;
}

function load(name: string): Fixture {
  const parsed = JSON.parse(
    readFileSync(join(FIXTURE_DIR, `${name}.json`), "utf8")
  ) as Record<string, unknown>;
  return {
    name,
    keys: Object.keys(parsed),
    recording: parsed["x-recording"] as Recording,
    status: parsed.status as number,
    statusText: parsed.statusText as string,
    headers: parsed.headers as Record<string, string>,
    body: parsed.body,
  };
}

/** The fixture as the client would receive it off the wire. */
function asResponse(fixture: Fixture): Response {
  return new Response(JSON.stringify(fixture.body), {
    status: fixture.status,
    statusText: fixture.statusText,
    headers: fixture.headers,
  });
}

// ---------------------------------------------------------------------------
// Compile-time derivation proofs.
// ---------------------------------------------------------------------------

/** `true` only when A and B are mutually assignable. */
type Exact<A, B> = [A] extends [B] ? ([B] extends [A] ? true : never) : never;

/** Reads as an assertion; the constraint is the whole point. */
function proves<T extends true>(_: T): void {
  /* the type parameter is the assertion */
}

// ---------------------------------------------------------------------------
// Schemas derived from `lib/api/models.ts`, which aliases the generated types.
// ---------------------------------------------------------------------------

const planSchema = z.strictObject({
  sub_questions: z.array(z.string()),
  search_queries: z.array(z.string()),
});
proves<Exact<z.infer<typeof planSchema>, Plan>>(true);

/**
 * The narrowing the OpenAPI document cannot express.
 *
 * `src/api/schemas.py` types `status` as a bare `str`, so the generated
 * member is `string`; `models.ts` narrows it by hand. That narrowing is a
 * claim about the backend, and this is where the claim gets tested — against
 * five recorded bodies rather than against the compiler, which is exactly the
 * R-06 surface the WO-03 risk notes named.
 */
const jobStatusSchema = z.enum([
  "pending",
  "running",
  "pending_review",
  "succeeded",
  "failed",
  "cancelled",
]);
proves<Exact<z.infer<typeof jobStatusSchema>, JobStatus>>(true);

/**
 * The second narrowing, and the one with a caveat (ADR 0057).
 *
 * `kind` is optional here because every fixture below was recorded
 * before `src/api/schemas.py` grew the field — that is what "the
 * field is additive" means in practice, and re-recording bodies just
 * to acquire a key nothing reads yet would be churn. `.optional()`
 * rather than a missing key is the load-bearing part: `.strictObject`
 * still rejects the fixture that starts carrying `kind: "curriculum"`,
 * which is the drift this file exists to catch.
 */
const jobKindSchema = z.enum(["research", "session"]);

const jobDetailSchema = z.strictObject({
  job_id: z.string(),
  status: jobStatusSchema,
  kind: jobKindSchema.optional(),
  query: z.string(),
  created_at: z.number(),
  started_at: z.number().nullable(),
  completed_at: z.number().nullable(),
  elapsed_sec: z.number().nullable(),
  result: z.string().nullable(),
  error: z.string().nullable(),
  error_type: z.string().nullable(),
  cost_usd: z.number().nullable(),
  llm_calls: z.number().nullable(),
  iterations: z.number().nullable(),
  quality_score: z.number().nullable(),
  plan: planSchema.nullable(),
  conversation_id: z.string().nullable(),
});
proves<Exact<z.infer<typeof jobDetailSchema>, JobDetail>>(true);

const conversationListItemSchema = z.strictObject({
  conversation_id: z.string(),
  title: z.string(),
  created_at: z.number(),
  updated_at: z.number(),
});
proves<Exact<z.infer<typeof conversationListItemSchema>, ConversationListItem>>(
  true
);

const conversationDetailSchema = z.strictObject({
  conversation_id: z.string(),
  title: z.string(),
  created_at: z.number(),
  updated_at: z.number(),
  jobs: z.array(
    z.strictObject({
      job_id: z.string(),
      ordinal: z.number(),
      query: z.string(),
      report: z.string(),
      created_at: z.number(),
    })
  ),
});
proves<Exact<z.infer<typeof conversationDetailSchema>, ConversationDetail>>(
  true
);

// ADR 0058. `source` is a real enum in the document — `src/api/schemas.py`
// types it `Literal[...]`, not a bare `str` — so unlike `JobStatus` there is
// no hand narrowing here and nothing to prove beyond the derivation. The
// asymmetry is the point: a consumer cannot render a skill claim without
// knowing where it came from, because provenance is neither optional nor
// nullable on the wire.
const learnerProfileSchema = z.strictObject({
  academic_level: z.enum([
    "",
    "self-taught",
    "undergrad",
    "grad",
    "postdoc",
    "industry",
  ]),
  time_budget_min_per_day: z.number(),
  goals: z.array(
    z.strictObject({
      goal_id: z.string(),
      statement: z.string(),
      target_date: z.string(),
      status: z.enum(["active", "paused", "reached", "abandoned"]),
      priority: z.number(),
    })
  ),
  skills: z.array(
    z.strictObject({
      skill: z.string(),
      level: z.enum(["none", "aware", "working", "solid"]),
      source: z.enum(["declared", "inferred", "assessed"]),
      evidence_ref: z.string(),
      confidence: z.number(),
      updated_at: z.string(),
    })
  ),
  profile_note: z.string(),
  created_at: z.number(),
  updated_at: z.number(),
});
proves<Exact<z.infer<typeof learnerProfileSchema>, LearnerProfile>>(true);

// ---------------------------------------------------------------------------
// The learner progress ledger (WO-W07). Derived like the shapes above, and
// carrying one extra assertion the others do not need: every number here is
// accompanied by the `event_ids` it was counted from, and nothing in the
// shape can express a mastery percentage. `01-LEARNING-AGENT.md` §4.1 bans
// knowledge scalars; `strictObject` is what makes a backend that grows one
// fail here rather than reach a surface.
// ---------------------------------------------------------------------------

const progressDailySessionsSchema = z.strictObject({
  day: z.string(),
  sessions: z.number(),
  event_ids: z.array(z.string()),
});
proves<
  Exact<z.infer<typeof progressDailySessionsSchema>, ProgressDailySessions>
>(true);

const progressScheduleSchema = z.strictObject({
  path_id: z.string(),
  sessions_completed: z.number(),
  sessions_planned: z.number().nullable(),
  schedule_label: z.string(),
  assessments_recorded: z.number(),
  event_ids: z.array(z.string()),
});
proves<Exact<z.infer<typeof progressScheduleSchema>, ProgressSchedule>>(true);

const progressEvidenceSchema = z.strictObject({
  event_id: z.string(),
  ts: z.string(),
  kind: z.string(),
  evidence_ref: z.string().nullable(),
  path_id: z.string().nullable(),
});
proves<Exact<z.infer<typeof progressEvidenceSchema>, ProgressEvidence>>(true);

const learnerProgressSummarySchema = z.strictObject({
  principal_key_id: z.string(),
  event_count: z.number(),
  sessions_per_day: z.array(progressDailySessionsSchema),
  schedule_progress: z.array(progressScheduleSchema),
  assessments: z.array(progressEvidenceSchema),
  artifacts: z.array(progressEvidenceSchema),
});
proves<
  Exact<z.infer<typeof learnerProgressSummarySchema>, LearnerProgressSummary>
>(true);

// ---------------------------------------------------------------------------
// Error envelopes. Hand-written on purpose: none of these shapes is in the
// OpenAPI document (04-ARCHITECTURE.md §3.4), so there is nothing to derive
// them from and no compile-time proof to be had. They are transcribed from
// the backend and pinned by the recordings below.
// ---------------------------------------------------------------------------

/** `{"detail": "job_not_found"}` — and the 409 variant with state in it. */
const stringDetailSchema = z.strictObject({ detail: z.string() });

/** `{"detail": {"error", "key_id", "limit_per_hour"}}` — `auth.py:176-184`. */
const rateLimitedDetailSchema = z.strictObject({
  detail: z.strictObject({
    error: z.literal("rate_limited"),
    key_id: z.string(),
    limit_per_hour: z.number(),
  }),
});

/**
 * FastAPI's 422 list.
 *
 * Deliberately loose per entry: the document's `ValidationError` schema
 * declares only `loc` / `msg` / `type`, but the real body also carries
 * `input` and `ctx`. That gap is the reason this check exists — a generated
 * type alone would have said the recorded body was fully described.
 */
const validationDetailSchema = z.strictObject({
  detail: z.array(
    z.looseObject({
      loc: z.array(z.union([z.string(), z.number()])),
      msg: z.string(),
      type: z.string(),
    })
  ),
});

// ---------------------------------------------------------------------------
// The inventory §3.3 requires.
// ---------------------------------------------------------------------------

const JOB_FIXTURES: Record<string, JobStatus> = {
  "job.pending_review": "pending_review",
  "job.running": "running",
  "job.succeeded": "succeeded",
  "job.failed_partial": "failed",
  "job.cancelled": "cancelled",
};

const CONVERSATION_FIXTURES = ["conversations.list", "conversations.detail"];

/**
 * The learner surfaces (Phase W). Its own array rather than entries in
 * one of the others: the length assertions below are the inventory, and
 * a new group has to declare itself instead of hiding inside an existing
 * count.
 */
const LEARN_FIXTURES = ["learn.profile", "learn.progress"];

const ERROR_FIXTURES: Record<string, { status: number; kind: ApiFailureKind }> =
  {
    "error.401": { status: 401, kind: "unauthorized" },
    "error.404": { status: 404, kind: "not_found" },
    "error.409": { status: 409, kind: "conflict" },
    "error.422": { status: 422, kind: "validation" },
    "error.429": { status: 429, kind: "rate_limited" },
    "error.502": { status: 502, kind: "upstream_unavailable" },
    "error.503": { status: 503, kind: "proxy_misconfigured" },
  };

const ALL_FIXTURES = [
  ...Object.keys(JOB_FIXTURES),
  ...CONVERSATION_FIXTURES,
  ...LEARN_FIXTURES,
  ...Object.keys(ERROR_FIXTURES),
];

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn() as unknown as typeof fetch;
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function serve(fixture: Fixture): void {
  (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue(
    asResponse(fixture)
  );
}

// ---------------------------------------------------------------------------

describe("contract/fixtures — inventory and provenance", () => {
  it("holds exactly the cases 04-ARCHITECTURE.md §3.3 lists", () => {
    const onDisk = readdirSync(FIXTURE_DIR)
      .filter((file) => file.endsWith(".json"))
      .map((file) => file.replace(/\.json$/, ""))
      .sort();
    expect(onDisk).toEqual([...ALL_FIXTURES].sort());
    // Five job states, two conversation shapes, two learner surfaces
    // (the profile and the progress ledger), seven error envelopes.
    expect(Object.keys(JOB_FIXTURES)).toHaveLength(5);
    expect(CONVERSATION_FIXTURES).toHaveLength(2);
    expect(LEARN_FIXTURES).toHaveLength(2);
    expect(Object.keys(ERROR_FIXTURES)).toHaveLength(7);
  });

  it.each(ALL_FIXTURES)(
    "%s names the commit it was recorded at, in its first key",
    (name) => {
      const fixture = load(name);
      // JSON has no comments, so the header is a key — and it has to be the
      // first one to read like the header comment §3.3 asks for.
      expect(fixture.keys[0]).toBe("x-recording");
      expect(fixture.recording.case).toBe(name);
      expect(fixture.recording.commit).toMatch(/^[0-9a-f]{40}$/);
      expect(fixture.recording.request).not.toBe("");
      expect(fixture.recording.transport).not.toBe("");
      // R-10: recorded, not invented. Anything authored has to say so and
      // say why — silence is the failure mode this asserts against.
      expect(typeof fixture.recording.authored).toBe("boolean");
      if (fixture.recording.authored) {
        expect(fixture.recording.authored_reason ?? "").not.toBe("");
      }
    }
  );

  it("was recorded against a stack with no real API key", () => {
    for (const name of ALL_FIXTURES) {
      expect(load(name).recording.stack).toContain(
        "ANTHROPIC_API_KEY=local-preview-disabled"
      );
    }
  });

  it("never records a POST /research response", () => {
    // MUST-KEEP #3 / R-01. The endpoint is non-idempotent and billable, so
    // no fixture may have come from it. `/research/{id}` and
    // `/research/{id}/review` are fine; a bare `POST /research` is not.
    for (const name of ALL_FIXTURES) {
      expect(load(name).recording.request).not.toMatch(
        /POST \/(api\/)?research(\s|$)/
      );
    }
  });
});

describe("contract/fixtures — the recorder's safety properties", () => {
  const script = readFileSync(
    join(process.cwd(), "contract", "record.sh"),
    "utf8"
  );

  /** The script with every comment line removed, i.e. what actually runs. */
  const code = script
    .split("\n")
    .filter((line) => !/^\s*#/.test(line))
    .join("\n");

  it("says in a comment that it is by hand, never CI, never POST /research", () => {
    expect(script).toContain("THIS SCRIPT IS RUN BY HAND");
    expect(script).toContain("NEVER RUNS IN CI");
    expect(script).toContain("NEVER CALLS");
    expect(script).toContain("`POST /research`");
  });

  it("refuses to run in CI", () => {
    expect(code).toContain('if [ -n "${CI:-}" ]; then');
    expect(code).toMatch(/exit 2/);
  });

  it("decides the Anthropic key itself and refuses any other value", () => {
    expect(code).toContain('DUMMY_KEY="local-preview-disabled"');
    expect(code).toContain('export ANTHROPIC_API_KEY="$DUMMY_KEY"');
    expect(code).toContain('!= "$DUMMY_KEY"');
    // Nothing that could be a real credential.
    expect(script).not.toMatch(/sk-[A-Za-z0-9-]{8}/);
  });

  it("never POSTs to the endpoint that submits a job", () => {
    // `POST /research` is the one non-idempotent, potentially billable call
    // on the surface (MUST-KEEP #3, R-01). Every POST the script makes goes
    // to `/research/{id}/review` or `/conversations`, both free.
    const invocations = code.split(/\bcurl\b/).slice(1);
    const posts = invocations.filter((body) => body.includes("-X POST"));
    expect(posts.length).toBeGreaterThan(0);

    const targets = posts.map((body) => {
      const url = /"((?:\$\{?PROXY\}?|\$\{?base\}?|https?:\/\/)[^"]*)"/.exec(
        body
      );
      return url?.[1] ?? "";
    });
    for (const target of targets) {
      expect(target).not.toBe("");
      expect(target).toMatch(/\/(review|conversations)$/);
    }
    expect(targets.some((target) => target.endsWith("/review"))).toBe(true);
    expect(targets.some((target) => target.endsWith("/conversations"))).toBe(
      true
    );
  });

  it("reads job state only from per-job sub-resources", () => {
    // The GET side of the same rule. Every path handed to the fixture
    // recorder is a single job or the conversations surface — reading a job
    // is free, and there is no GET that could start one.
    const paths = [...code.matchAll(/record_get \S+ (\S+)/g)].map(
      (match) => match[1] ?? ""
    );
    expect(paths).toHaveLength(7);
    for (const path of paths) {
      expect(path).toMatch(/^\/(research\/[a-z-]+|conversations)/);
      expect(path).not.toBe("/research");
    }
    expect(paths).toContain("/research/baseline-succeeded");
  });

  it("re-seeds before recording so a re-run produces the same bytes", () => {
    expect(code).toContain("bash \"$SEED_SCRIPT\"");
    expect(script).toContain(
      "docs/revamp/baseline/fixtures/seed-local-baseline.sh"
    );
  });
});

describe("contract/fixtures — job states through the typed client", () => {
  it.each(Object.entries(JOB_FIXTURES))(
    "%s parses as JobDetail and reports status %s",
    async (name, status) => {
      const fixture = load(name);
      serve(fixture);

      const job = await getJob("baseline");

      const parsed = jobDetailSchema.safeParse(job);
      expect(parsed.error?.issues ?? []).toEqual([]);
      expect(parsed.success).toBe(true);
      expect(job.status).toBe(status);
    }
  );

  it("covers all five states, and each recorded status is in the union", () => {
    const seen = Object.keys(JOB_FIXTURES).map(
      (name) => (load(name).body as JobDetail).status
    );
    expect(new Set(seen).size).toBe(5);
    for (const status of seen) {
      expect(jobStatusSchema.options).toContain(status);
    }
  });

  it("carries a plan exactly when the job is parked in review", () => {
    // ADR 0030: `plan` is populated for `pending_review` and null otherwise.
    for (const [name, status] of Object.entries(JOB_FIXTURES)) {
      const job = load(name).body as JobDetail;
      expect(job.plan === null).toBe(status !== "pending_review");
    }
  });

  it("keeps the partial report on a failed job", () => {
    // H5 / §3.1: a failed job with a partial report is still exportable, so
    // the UI may not treat `failed` as "nothing to show".
    const job = load("job.failed_partial").body as JobDetail;
    expect(job.status).toBe("failed");
    expect(job.result).not.toBeNull();
    expect(job.error_type).not.toBeNull();
  });
});

describe("contract/fixtures — conversations through the typed client", () => {
  it("conversations.list parses as a bare array with no pagination envelope", async () => {
    const fixture = load("conversations.list");
    serve(fixture);

    const list = await listConversations();

    const parsed = z.array(conversationListItemSchema).safeParse(list);
    expect(parsed.error?.issues ?? []).toEqual([]);
    expect(parsed.success).toBe(true);
    // §3.1: the endpoint returns a bare array — no `total`, no `has_more`.
    expect(Array.isArray(list)).toBe(true);
    expect(list.length).toBeGreaterThan(0);
  });

  it("conversations.detail parses with every job body inline", async () => {
    const fixture = load("conversations.detail");
    serve(fixture);

    const detail = await getConversation("baseline-populated");

    const parsed = conversationDetailSchema.safeParse(detail);
    expect(parsed.error?.issues ?? []).toEqual([]);
    expect(parsed.success).toBe(true);
    expect(detail.jobs.length).toBeGreaterThan(0);
    expect(detail.jobs[0]?.report).not.toBe("");
  });
});

describe("contract/fixtures — the learner profile (ADR 0058)", () => {
  it("learn.profile parses with provenance on every claim", () => {
    const profile = load("learn.profile").body as LearnerProfile;

    const parsed = learnerProfileSchema.safeParse(profile);
    expect(parsed.error?.issues ?? []).toEqual([]);
    expect(parsed.success).toBe(true);
    expect(profile.skills.length).toBeGreaterThan(0);
    for (const claim of profile.skills) {
      expect(["declared", "inferred", "assessed"]).toContain(claim.source);
    }
  });

  it("carries all three provenance values, so no consumer sees only one", () => {
    // A fixture with only `declared` claims would let a surface render
    // provenance as decoration and still pass. The recording deliberately
    // holds one of each.
    const profile = load("learn.profile").body as LearnerProfile;

    expect(new Set(profile.skills.map((claim) => claim.source))).toEqual(
      new Set(["declared", "assessed", "inferred"])
    );
  });

  it("shows a contradiction as two claims, not one downgraded number", () => {
    // 01 §1.2 / ADR 0058: an assessment that disagrees with a declaration
    // lands *beside* it. The recorded body is the proof that the backend
    // really does this, and the pin that stops a surface from collapsing
    // the pair into one row.
    const profile = load("learn.profile").body as LearnerProfile;
    const backprop = profile.skills.filter(
      (claim) => claim.skill === "backprop"
    );

    expect(backprop).toHaveLength(2);
    const declared = backprop.find((claim) => claim.source === "declared");
    const assessed = backprop.find((claim) => claim.source === "assessed");
    expect(declared?.level).toBe("solid");
    expect(assessed?.level).toBe("aware");
  });

  it("keeps confidence 1.0 for declared claims alone", () => {
    const profile = load("learn.profile").body as LearnerProfile;

    for (const claim of profile.skills) {
      if (claim.source === "declared") {
        expect(claim.confidence).toBe(1);
        expect(claim.evidence_ref).toBe("");
      } else {
        expect(claim.confidence).toBeLessThan(1);
        expect(claim.evidence_ref).not.toBe("");
      }
      if (claim.source === "inferred") {
        expect(claim.confidence).toBeLessThanOrEqual(0.6);
      }
    }
  });
});

describe("contract/fixtures — the learner progress ledger", () => {
  // No `serve()` here: there is no client function for `/learn/progress`
  // yet, so the fixture is validated against the derived schema directly.
  // The client lands with the learning surfaces; freezing the shape now
  // is the point of recording the fixture ahead of them.

  it("learn.progress parses as the derived summary shape", () => {
    const parsed = learnerProgressSummarySchema.safeParse(
      load("learn.progress").body
    );
    expect(parsed.error?.issues ?? []).toEqual([]);
    expect(parsed.success).toBe(true);
  });

  it("says out loud that it was authored rather than recorded", () => {
    // The other thirteen fixtures come off a seeded stack. This one
    // cannot: the endpoint is behind a default-off flag with no producer
    // wired yet. The `authored_reason` is where that has to be admitted.
    const recording = load("learn.progress").recording;
    expect(recording.authored).toBe(true);
    expect(recording.authored_reason ?? "").toContain(
      "tests/fixtures/learning/progress_events_raw.json"
    );
  });

  it("carries the events behind every number it reports", () => {
    // 01-LEARNING-AGENT.md §4.4: no displayed claim without an event
    // behind it. Each count equals the length of its own provenance list.
    const body = learnerProgressSummarySchema.parse(
      load("learn.progress").body
    );
    for (const day of body.sessions_per_day) {
      expect(day.event_ids).toHaveLength(day.sessions);
    }
    for (const path of body.schedule_progress) {
      expect(path.event_ids).toHaveLength(path.sessions_completed);
    }
    for (const record of [...body.assessments, ...body.artifacts]) {
      expect(record.evidence_ref).not.toBe(null);
      expect(record.evidence_ref).not.toBe("");
    }
  });

  it("offers no mastery percentage anywhere in the payload", () => {
    // The 01 §4.1 ban, checked on the wire bytes. The backend enforces
    // it structurally (a payload-key CHECK plus a write-boundary walk);
    // this is the consumer-side half of the same rule, and the same
    // vocabulary WO-W14's copy gate uses.
    const serialized = JSON.stringify(load("learn.progress").body);
    for (const banned of [
      "master",
      "proficien",
      "competenc",
      "percent",
      "pct",
      "score",
    ]) {
      expect(serialized.toLowerCase()).not.toContain(banned);
    }
    expect(serialized).not.toContain("%");
    // What it does carry is session arithmetic, explicitly labeled.
    const body = learnerProgressSummarySchema.parse(
      load("learn.progress").body
    );
    for (const path of body.schedule_progress) {
      expect(path.schedule_label).toMatch(
        /^\d+ of \d+ sessions$|^\d+ sessions? recorded$/
      );
    }
  });
});

describe("contract/fixtures — error envelopes", () => {
  it.each(Object.entries(ERROR_FIXTURES))(
    "%s normalizes to a single failure kind",
    async (name, expected) => {
      const fixture = load(name);
      expect(fixture.status).toBe(expected.status);

      const failure = await normalizeFailure(asResponse(fixture));

      expect(failure.kind).toBe(expected.kind);
      expect(API_FAILURE_KINDS).toContain(failure.kind);
      expect(failure.message).not.toBe("");
      expect(failure.raw).toEqual(fixture.body);
    }
  );

  it.each(Object.keys(ERROR_FIXTURES))(
    "%s surfaces through the typed client as an ApiError carrying the failure",
    async (name) => {
      const fixture = load(name);
      serve(fixture);

      const err = await getJob("baseline").then(
        () => null,
        (caught: unknown) => caught
      );

      expect(err).toBeInstanceOf(ApiError);
      const apiError = err as ApiError;
      expect(apiError.status).toBe(fixture.status);
      expect(apiError.failure.kind).toBe(ERROR_FIXTURES[name]?.kind);
    }
  );

  it.each(Object.keys(ERROR_FIXTURES))(
    "%s keeps backend codes out of the user-facing sentence",
    async (name) => {
      const failure = await normalizeFailure(asResponse(load(name)));
      // §3.4: `raw` is disclosure-only. Every observed backend code is
      // snake_case, and no default sentence contains an underscore, so this
      // catches a normalizer that starts echoing `detail` verbatim.
      expect(failure.message).not.toMatch(/[a-z]+_[a-z]+/);
    }
  );

  it("401 carries the WWW-Authenticate challenge the proxy forwards", () => {
    const fixture = load("error.401");
    expect(fixture.headers["www-authenticate"]).toMatch(/^ApiKey /);
    expect(stringDetailSchema.parse(fixture.body).detail).toBe(
      "missing_api_key"
    );
  });

  it("404 is the same answer for missing and for someone else's", () => {
    // `routes.py:59-84` returns 404, never 403, so the copy may not say
    // "deleted" or "no permission".
    const fixture = load("error.404");
    expect(stringDetailSchema.parse(fixture.body).detail).toBe("job_not_found");
  });

  it("409 embeds the job state in the detail string, and it is parsed out", async () => {
    const fixture = load("error.409");
    const detail = stringDetailSchema.parse(fixture.body).detail;
    expect(detail).toMatch(/\(status=[^)]+\)/);

    const failure = await normalizeFailure(asResponse(fixture));

    expect(failure.kind).toBe("conflict");
    if (failure.kind !== "conflict") throw new Error("unreachable");
    expect(failure.state).toBe("running");
    expect(failure.message).toContain("running");
  });

  it("422 strips FastAPI's body/query prefix off every field path", async () => {
    const fixture = load("error.422");
    const parsed = validationDetailSchema.parse(fixture.body);
    expect(parsed.detail[0]?.loc[0]).toBe("body");

    const failure = await normalizeFailure(asResponse(fixture));

    expect(failure.kind).toBe("validation");
    if (failure.kind !== "validation") throw new Error("unreachable");
    expect(failure.fields).toHaveLength(1);
    expect(failure.fields[0]?.path).toBe("title");
    expect(failure.fields[0]?.type).toBe("string_too_long");
  });

  it("422 bodies carry keys the OpenAPI ValidationError schema omits", () => {
    // Not a defect to fix here — evidence for why check 3 exists. The
    // document describes `loc` / `msg` / `type`; the wire adds `input` and
    // `ctx`, and only a recorded body shows that.
    const entry = validationDetailSchema.parse(load("error.422").body)
      .detail[0] as Record<string, unknown>;
    expect(Object.keys(entry)).toContain("input");
    expect(Object.keys(entry)).toContain("ctx");
  });

  it("429 detail is an OBJECT, and the user never sees the JSON", async () => {
    const fixture = load("error.429");
    const parsed = rateLimitedDetailSchema.parse(fixture.body);
    expect(parsed.detail.limit_per_hour).toBe(1);
    expect(fixture.headers["retry-after"]).toMatch(/^\d+$/);

    const failure = await normalizeFailure(asResponse(fixture));

    expect(failure.kind).toBe("rate_limited");
    if (failure.kind !== "rate_limited") throw new Error("unreachable");
    expect(failure.retryAfterSec).toBe(
      Number(fixture.headers["retry-after"])
    );
    expect(failure.limitPerHour).toBe(1);
    // The bug §3.4 names: today's client renders `JSON.stringify(body)` here.
    expect(failure.message).not.toContain("{");
    expect(failure.message).not.toContain("key_id");
  });

  it("502 and 503 come from the proxy, not from FastAPI", () => {
    expect(stringDetailSchema.parse(load("error.502").body).detail).toBe(
      "api_upstream_unavailable"
    );
    expect(stringDetailSchema.parse(load("error.503").body).detail).toBe(
      "api_proxy_misconfigured"
    );
    for (const name of ["error.502", "error.503"]) {
      expect(load(name).recording.transport).toContain("proxy");
    }
  });

  it("normalizes from a body read exactly once", async () => {
    // The seam that keeps the legacy `ApiError.message` and the normalized
    // failure from consuming the same stream twice.
    const response = asResponse(load("error.409"));
    const body = await readErrorBody(response);
    expect(body.json).toBe(true);

    const failure = await normalizeFailure(response, { body });
    const legacy = legacyDetailMessage(response, body);

    expect(failure.kind).toBe("conflict");
    expect(legacy).toBe("job_not_awaiting_review (status=running)");
    // The normalized sentence is not the legacy one.
    expect(failure.message).not.toBe(legacy);
  });

  it("the seven envelopes map onto seven distinct kinds, all declared", () => {
    const kinds = Object.values(ERROR_FIXTURES).map((entry) => entry.kind);
    expect(new Set(kinds).size).toBe(7);
    for (const kind of kinds) expect(API_FAILURE_KINDS).toContain(kind);
    // The remaining five kinds are transport-only, so no HTTP fixture can
    // exist for them; `web/tests/apiErrors.test.ts` covers those.
    expect(API_FAILURE_KINDS).toHaveLength(12);
  });
});
