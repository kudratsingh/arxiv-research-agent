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
  | "succeeded"
  | "failed"
  | "cancelled";

export type ReviewAction = "approve" | "revise" | "cancel";

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

/** FastAPI's per-field 422 entry (`{loc, msg, type}`). */
export type ValidationErrorItem = Schemas["ValidationError"];

export type JobDetail = Omit<
  Serialized<Schemas["JobDetail"]>,
  "status" | "plan"
> & {
  /** Narrowed from the generated `string`; see the note above. */
  status: JobStatus & Schemas["JobDetail"]["status"];
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
