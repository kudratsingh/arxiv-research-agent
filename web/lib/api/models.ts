// App-facing model names, aliased into the generated OpenAPI types.
//
// Nothing here redeclares a generated shape. Every model is an alias
// or a derivation of `components["schemas"][...]`, so a backend field
// change in `src/api/schemas.py` becomes a **compile error** here
// rather than a runtime surprise — which is the failure mode the
// superseded hand-written `web/lib/types.ts` explicitly accepted
// ("If the schemas drift, contract tests on the Python side catch the
// producer end"). See 04-ARCHITECTURE.md §3.3.
//
// Regenerate the underlying types with `npm run generate:types`
// after refreshing `web/contract/openapi.json`.

import type { components } from "./generated/schema";

type Schemas = components["schemas"];

/**
 * Re-require the fields FastAPI serializes unconditionally.
 *
 * FastAPI marks a field `required: false` in the OpenAPI document
 * whenever its Pydantic model supplies a default. That is a statement
 * about the **request** direction: a response rendered through a
 * `response_model` always emits every field, defaults included. This
 * mapped type re-applies that fact so response consumers do not have
 * to guard keys the API always sends. `| null` is preserved — only
 * the `?` is removed.
 */
type Serialized<T> = { [K in keyof T]-?: T[K] };

// ---------------------------------------------------------------------------
// Narrowings the OpenAPI document cannot express.
//
// `src/api/schemas.py` types `status` and `action` as bare `str`, so
// the generated members are `string`. The real vocabularies are
// closed and are pinned server-side (`src/api/streaming.py:89-103`).
// Narrowing them is the R-06 false-confidence surface called out in
// the WO-03 risk notes: it is asserted by fixtures in WO-04, not by
// the compiler. Each narrowing is intersected with the generated
// member so that renaming the field upstream still fails to compile.
// ---------------------------------------------------------------------------

export type JobStatus =
  | "pending"
  | "running"
  | "pending_review"
  | "awaiting_learner"
  | "succeeded"
  | "failed"
  | "cancelled";

export type ReviewAction = "approve" | "revise" | "cancel";

/**
 * Which graph a job drives (`src/api/jobs.py::JobKind`, ADR 0057).
 *
 * Same narrowing as `JobStatus`: the backend types it `str`, the
 * vocabulary is closed, and pinning it here is a claim tested against
 * recorded bodies rather than proved by the compiler.
 */
export type JobKind = "research" | "session";

// ---------------------------------------------------------------------------
// Request and response models.
// ---------------------------------------------------------------------------

export type Plan = Serialized<Schemas["Plan"]>;

export type ResearchRequest = Schemas["ResearchRequest"];

export type ResearchAccepted = Schemas["ResearchAccepted"];

export type ReviewResponse = Schemas["ReviewResponse"];

export type ConversationCreateRequest = Schemas["ConversationCreateRequest"];

export type ConversationJobSummary = Schemas["ConversationJobSummary"];

export type ConversationListItem = Schemas["ConversationListItem"];

export type ConversationDetail = Serialized<Schemas["ConversationDetail"]>;

export type HealthResponse = Serialized<Schemas["HealthResponse"]>;

// ---------------------------------------------------------------------------
// The learner progress ledger (WO-W07), served by `GET /learn/progress`
// behind the default-off `enable_learner_profile` flag.
//
// Aliases only — there is no client function yet. The path surfaces
// land with the learning-surface work orders; these types and the
// `learn.progress` fixture exist now so those cards build against a
// shape the backend has already frozen.
//
// Note what is absent and must stay absent: there is no mastery,
// proficiency, or percentage member anywhere below.
// `01-LEARNING-AGENT.md` §4.1 bans knowledge scalars, and the backend
// enforces the ban structurally (see
// `src/learning/progress_store.py`). `schedule_progress` is
// arithmetic about sessions and is named so the UI cannot mistake it
// for knowledge.
// ---------------------------------------------------------------------------

export type ProgressDailySessions = Serialized<
  Schemas["ProgressDailySessions"]
>;

export type ProgressSchedule = Serialized<Schemas["ProgressSchedule"]>;

export type ProgressEvidence = Serialized<Schemas["ProgressEvidence"]>;

export type LearnerProgressSummary = Serialized<
  Schemas["LearnerProgressSummary"]
>;

/** FastAPI's per-field 422 entry (`{loc, msg, type}`). */
export type ValidationErrorItem = Schemas["ValidationError"];

export type JobDetail = Omit<
  Serialized<Schemas["JobDetail"]>,
  "status" | "kind" | "plan"
> & {
  /** Narrowed from the generated `string`; see the note above. */
  status: JobStatus & Schemas["JobDetail"]["status"];
  /**
   * Which graph the job drives (ADR 0057). Narrowed like `status`, and
   * the one field `Serialized` is deliberately *not* applied to.
   *
   * A response from today's server always carries it — FastAPI
   * renders the Pydantic default — so the general `Serialized`
   * argument holds. What does not carry it is every body recorded
   * before the field existed, which is the entire corpus
   * `tests/contract/fixtures.test.ts` parses, plus any older worker
   * still answering during a rolling deploy. Optional is therefore
   * the true statement about what a consumer can find here today.
   *
   * WO-W13 is the card that makes it required: it is the first
   * surface that reads `kind`, and re-recording the job fixtures
   * against a session-aware stack is part of its work.
   */
  kind?: JobKind & Schemas["JobDetail"]["kind"];
  /** Populated when `status === "pending_review"` (ADR 0030). */
  plan: (Plan & NonNullable<Schemas["JobDetail"]["plan"]>) | null;
};

export type ReviewRequest = Omit<Schemas["ReviewRequest"], "action" | "plan"> & {
  /** Narrowed from the generated `string`; see the note above. */
  action: ReviewAction & Schemas["ReviewRequest"]["action"];
  /** Required when `action === "revise"`, ignored otherwise. */
  plan?: (Plan & NonNullable<Schemas["ReviewRequest"]["plan"]>) | null;
};

/**
 * Caller-facing options for `submitResearch`.
 *
 * Not a wire schema: this is the client's option bag, which is why it
 * is hand-written rather than aliased.
 */
export interface ResearchSubmitOptions {
  conversation_id?: string;
  /**
   * Skip the human plan-review pause.
   *
   * **Deliberately unavailable to the UI** (03-DESIGN-BRIEF.md §8.4,
   * ratified at Gate 2). It exists for programmatic callers such as
   * the eval runner (`src/eval/runner.py:295`) and is kept here only
   * so the typed client is not a false narrowing of the real API.
   * Review is the single cancellation point in the whole lifecycle,
   * so a run that bypasses it cannot be stopped at all.
   *
   * No module outside `web/lib/api/` may reference this field; the
   * containment test in `web/tests/api.test.ts` enforces it (H12).
   */
  hitl_bypass?: boolean;
}

// ---------------------------------------------------------------------------
// Learner profile (ADR 0058).
//
// `SkillClaim.source` is a real enum in the document — `src/api/schemas.py`
// types it `Literal[...]`, not a bare `str` — so unlike `JobStatus` it needs
// no hand narrowing, and a consumer cannot render a skill without knowing
// where the claim came from. That is the point of the field.
// ---------------------------------------------------------------------------

export type SkillClaim = Serialized<Schemas["SkillClaim"]>;

export type GoalClaim = Serialized<Schemas["GoalClaim"]>;

export type LearnerProfile = Serialized<Schemas["LearnerProfileResponse"]>;

export type ProfileUpdateRequest = Schemas["ProfileUpdateRequest"];

/** `declared` | `inferred` | `assessed` — never nullable, never absent. */
export type SkillSource = SkillClaim["source"];

// Learning content (WO-W12). These aliases preserve the generated
// OpenAPI contract all the way to the path surfaces.
export type LearnPathSummary = Schemas["LearnPathSummary"];
export type LearnPathList = Schemas["LearnPathList"];
export type LearnEntry = Schemas["LearnEntry"];
export type LearnPathDetail = Schemas["LearnPathDetail"];

export type SessionCreateRequest = Schemas["SessionCreateRequest"];
export type SessionAccepted = Schemas["SessionAccepted"];
export type SessionTranscriptEntry = Schemas["SessionTranscriptEntry"];
export type SessionTurnRequest = Schemas["SessionTurnRequest"];
export type SessionTurnAccepted = Schemas["SessionTurnAccepted"];
export type SessionDetail = Omit<
  Serialized<Schemas["SessionDetail"]>,
  "status"
> & {
  status: JobStatus & Schemas["SessionDetail"]["status"];
};

export type ProgressResourceObservation =
  Schemas["ProgressResourceObservation"];
