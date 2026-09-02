// The public data-layer surface. UI code imports from here and from
// nowhere else inside `lib/api/`.
//
// It is also the abstraction that makes M0 free (05-MIGRATION.md
// §1.1): every name the superseded `web/lib/api.ts:16-137` and
// `web/lib/types.ts` exposed is re-exported here with an unchanged
// signature, so existing components keep compiling and the 78 existing
// tests keep passing while the implementation underneath becomes
// typed, normalized, and abortable.

export {
  API_BASE,
  DEFAULT_READ_TIMEOUT_MS,
  createConversation,
  createLearnSession,
  deleteConversation,
  getConversation,
  getJob,
  getLearnPath,
  getLearnSession,
  getLearnerProgress,
  listConversations,
  listLearnPaths,
  reviewPlan,
  streamUrl,
  submitResearch,
  submitLearnSessionTurn,
} from "./client";
export type { ListConversationsOptions, RequestOptions } from "./client";

export {
  API_FAILURE_KINDS,
  ApiError,
  legacyDetailMessage,
  normalizeFailure,
  readErrorBody,
} from "./errors";
export type {
  ApiFailure,
  ApiFailureKind,
  ErrorBody,
  FailureCommon,
  FieldIssue,
  NormalizeContext,
} from "./errors";

export type {
  ConversationCreateRequest,
  ConversationDetail,
  ConversationJobSummary,
  ConversationListItem,
  GoalClaim,
  HealthResponse,
  JobDetail,
  JobKind,
  JobStatus,
  LearnEntry,
  LearnPathDetail,
  LearnPathList,
  LearnPathSummary,
  LearnerProfile,
  LearnerProgressSummary,
  Plan,
  ProfileUpdateRequest,
  ProgressDailySessions,
  ProgressEvidence,
  ProgressResourceObservation,
  ProgressSchedule,
  ResearchAccepted,
  ResearchRequest,
  ResearchSubmitOptions,
  ReviewAction,
  ReviewRequest,
  ReviewResponse,
  SessionAccepted,
  SessionCreateRequest,
  SessionDetail,
  SessionTranscriptEntry,
  SessionTurnAccepted,
  SessionTurnRequest,
  SkillClaim,
  SkillSource,
  ValidationErrorItem,
} from "./models";

export {
  CLIENT_EVENT_NAMES,
  SERVER_EVENT_NAMES,
  STREAM_TIMEOUT_EVENT,
  TERMINAL_EVENTS,
} from "./events";
export type {
  JobCancelledPayload,
  JobCompletedPayload,
  JobFailedPayload,
  JobStartedPayload,
  NodeCompletedPayload,
  PlanReadyPayload,
  ServerSseEventName,
  SseEvent,
  SseEventName,
  StreamTimeoutPayload,
  TerminalReplayPayload,
} from "./events";

/** The generated OpenAPI types, for callers that need a raw schema. */
export type { components, operations, paths } from "./generated/schema";
