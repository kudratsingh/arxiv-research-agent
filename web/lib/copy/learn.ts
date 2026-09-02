// The `(learn)` surface dictionary.
//
// Imports NOTHING at runtime, deliberately. WO-W14 measured that pulling
// `lib/copy/errors` in for a single word costs `/learn` 2,317 B and
// `/learn/progress` 2,033 B, and every string here is route JavaScript. The
// one import below is a `type` and is erased.
import type { ApiFailure } from "@/lib/api";

export const LEARN = {
  navLabel: "Learning paths",
  landingEyebrow: "Guided reading",
  landingHeading: "Read papers with a path, not a pile.",
  landingBody:
    "Follow a deliberate paper sequence, use a briefing to orient yourself, then read the source on arXiv.",
  landingAction: "Explore the reading path",
  listEyebrow: "Path library",
  listHeading: "Choose what to read next",
  listBody:
    "Each path orders primary sources and explains why they belong together. The paper always stays the source of record.",
  listLoading: "Loading paths…",
  listEmptyHeading: "No paths are published",
  listEmptyBody: "There is no published reading sequence to show yet.",
  pathLabel: "Reading path",
  pathLoading: "Loading the path…",
  pathUnavailableHeading: "This path is unavailable",
  pathUnavailableBody:
    "Learning content is not available from the research service right now.",
  retry: "Try again",
  backToPaths: "All paths",
  openPath: "Open path",
  entriesLabel: "Paper sequence",
  papers: "papers",
  minutes: "minutes",
  updated: "Updated",
  fixtureLabel: "Fixture content",
  fixtureShort:
    "Demo scaffolding only. These placeholder briefings are not reviewed learning material.",
  noProgress: "No reading activity has been observed for this path.",
  progressSource: "Position is shown only from recorded session events.",
  observed: "Observed",
  notObserved: "Not yet observed",
  nextObserved: "Current observed position",
  briefingAvailable: "Briefing available",
  briefingUnavailable: "Briefing not yet available",
  openPaper: "Open on arXiv",
  whyHere: "Why it is here",
  vocabulary: "Vocabulary",
  attribution: "Source attribution",
  linkOutOnly:
    "This path links to arXiv and does not fetch or display paper full text.",
  // --- WO-W13b: starting a session from the path view --------------------
  startSession: "Start a session",
  // The honest in-flight label. No spinner standing in for progress and no
  // ellipsis pretending the tutor is already writing: the only fact the
  // browser holds at this moment is that one POST is outstanding.
  startingSession: "Starting the session",
  startRefusedHeading: "This session was not started",
  startRefusedDisabled:
    "This deployment is not running guided sessions. Nothing was started and nothing was recorded.",
  startRefusedPrincipal:
    "A guided session belongs to one reader, and the service holds no learner profile for the credential it received. Nothing was started.",
  startRefusedContent:
    "The service is not serving this paper as a guided session; its briefing companion is not published here. Nothing was started.",
  startRefusedRateLimited:
    "The service is refusing new work from this credential for now. Nothing was started; try again shortly.",
  startRefusedUnreachable:
    "The research service could not be reached, so nothing was started.",
  startRefusedGeneric: "The service did not start a session. Nothing was recorded.",
  /** Label for the service's own words, shown unedited (RC-16). */
  startRefusedDetail: "What the service reported",
  sessionEyebrow: "Guided paper session",
  sessionLoading: "Reattaching to your reading session…",
  sessionUnavailableHeading: "This reading session is unavailable",
  sessionUnavailableBody:
    "The session may have expired, belong to another reader, or be turned off. No distinction is exposed.",
  backToPath: "Back to the reading path",
  sourceLabel: "Primary source",
  passageLabel: "Briefing companion",
  passageEmpty: "No briefing companion is available for this paper.",
  conversationLabel: "Reading margin",
  tutorLabel: "Tutor note",
  learnerLabel: "Your note",
  currentTurnLabel: "Your turn",
  replyLabel: "Write your response",
  // WO-W14 reworded: "is not scored as failure" tripped the pedagogy gate's
  // `score` entry. A learning surface does not use the word even to deny it —
  // the same discipline 03 §5.5 applies to "unknown".
  replyHint:
    "Use your own words. Uncertainty is useful evidence, and saying so is not a failure.",
  submitTurn: "Continue the session",
  submittingTurn: "Recording your response…",
  endSession: "End after this response",
  workingHeading: "The tutor is preparing the next prompt",
  // WO-W14 reworded: "No percentage" tripped the pedagogy gate. The sentence
  // still refuses the estimate; it just no longer names the banned form.
  workingBody:
    "No completion estimate is shown. The next observed checkpoint will appear when the service publishes it.",
  reconnecting: "Connection interrupted. The browser is reattaching to the same session.",
  resumed: "Session restored from its durable checkpoint.",
  transcriptUnavailable:
    "The session is available, but its saved reading margin could not be loaded. Nothing has been reconstructed from stream events.",
  costCapHeading: "Session cost limit reached",
  costCapRefused:
    "The next model call was refused before spending beyond this session’s limit.",
  costCapDegraded:
    "The session closed with a bounded fallback instead of spending beyond its limit.",
  unassessedHeading: "No assessment was recorded",
  // WO-W14 reworded: "not a grade or a claim of mastery" tripped `grade` and
  // `mastery`. Both refusals survive — nothing judged, nothing claimed —
  // without planting the frame the sentence exists to reject.
  unassessedBody:
    "This is an explicit missing assessment. Nothing was judged and nothing is claimed.",
  // WO-W14 reworded: "turned into a grade" tripped `grade`. "Recorded, not
  // judged" is the wire state (`recorded_ungraded`) said plainly.
  recordedUngraded:
    "Your explain-back was saved as evidence. It was recorded, not judged.",
  completeHeading: "Session complete",
  completeAdvance:
    "This session advanced one guided reading and preserved your own explain-back as evidence.",
  failedHeading: "The session stopped",
  failedBody:
    "Your saved reading margin remains visible when available. The service did not claim completion.",
  emptyTurn: "The server has not published a learner turn yet.",
  retrySession: "Try to reattach",
} as const;

// ---------------------------------------------------------------------------
// Starting a session, refused (WO-W13b).
// ---------------------------------------------------------------------------

/** What the path view renders when a start request came back refused. */
export interface SessionStartRefusal {
  /** The sentence a reader sees. Always one of the strings above. */
  message: string;
  /**
   * The service's own words, verbatim and unedited (RC-16), or `null`.
   *
   * Only ever the backend's `detail` string. A transport failure produces no
   * service words, and a refusal this dictionary already has a sentence for
   * does not need the wire code beside it, so both carry `null`.
   */
  detail: string | null;
}

/**
 * The `detail` codes `POST /learn/sessions` can answer with, mapped.
 *
 * Every key is raised by `src/api/sessions.py`, and the list is exactly what
 * that file can produce for this endpoint — nothing is mapped speculatively,
 * because a sentence for a refusal the API cannot issue is a sentence no
 * reader can ever check:
 *
 *   `session_loop_disabled`        `_require_session_enabled`, flag off
 *   `session_loop_requires_auth`   `_principal_id`, no principal
 *   `learner_profile_required`     `create_session`, no profile for the key
 *   `learn_content_invalid`        `_content_entry`, manifests do not load
 *   `learn_path_not_found`         `_content_entry`, no such published path
 *   `learn_resource_not_found`     `_content_entry`, no such entry
 *   `briefing_companion_required`  `_content_entry`, entry has no companion
 *
 * The first three collapse to one sentence on purpose: `src/config.py`'s
 * ladder refuses the session loop without the learner profile and refuses
 * that without API auth, so from a reader's side they are one situation —
 * this service holds no learner record for whoever asked — and three shades
 * of it would imply the surface can tell apart configurations it cannot see.
 * The four content codes collapse for the reason `routes.py` answers 404
 * rather than 403 on an ownership mismatch: the distinction is about the
 * server's content tree, not about the reader.
 *
 * WO-W06's `session_cost_cap_refused` is deliberately ABSENT. It is an
 * `error_type` on a session that already exists (`src/api/runner.py:1672`),
 * reached only after the graph has run; `POST /learn/sessions` cannot answer
 * with it, and the surface that renders it is the session view's cost-cap
 * fact (`GuidedSessionView`, WO-W13). If the endpoint ever did return it,
 * the fall-through below shows the service's own word unedited rather than a
 * sentence this file guessed.
 */
const START_REFUSAL_SENTENCE: Readonly<Record<string, string>> = {
  session_loop_disabled: LEARN.startRefusedDisabled,
  session_loop_requires_auth: LEARN.startRefusedPrincipal,
  learner_profile_required: LEARN.startRefusedPrincipal,
  learn_content_invalid: LEARN.startRefusedContent,
  learn_path_not_found: LEARN.startRefusedContent,
  learn_resource_not_found: LEARN.startRefusedContent,
  briefing_companion_required: LEARN.startRefusedContent,
};

/**
 * The backend's `detail`, when it is a plain string.
 *
 * Five lines rather than an import: `lib/api/errors.ts` keeps its own reader
 * private, and pulling `lib/copy/errors` in for it would ship that failure
 * dictionary into `/learn/paths/[id]` for one field read — the cost WO-W14
 * measured when `lib/copy/ledger.ts` briefly imported it.
 */
function detailCode(raw: unknown): string {
  if (raw === null || typeof raw !== "object" || !("detail" in raw)) return "";
  const detail = (raw as { detail: unknown }).detail;
  return typeof detail === "string" ? detail : "";
}

/**
 * The one accessor for start-refusal copy.
 *
 * The sentence is ALWAYS from this dictionary, so the pedagogy gate and the
 * §5.5 deny-list both see it. The backend's words appear only as `detail`,
 * beside the sentence and unedited — RC-16's rule, the same one
 * `describeErrorType` follows for a run's raw `error`.
 */
export function describeSessionStart(
  failure: ApiFailure | null
): SessionStartRefusal {
  if (failure === null) {
    return { message: LEARN.startRefusedGeneric, detail: null };
  }
  const code = detailCode(failure.raw);
  const mapped = START_REFUSAL_SENTENCE[code];
  if (mapped !== undefined) return { message: mapped, detail: null };
  if (failure.kind === "rate_limited") {
    return { message: LEARN.startRefusedRateLimited, detail: null };
  }
  if (failure.kind === "offline" || failure.kind === "timeout") {
    return { message: LEARN.startRefusedUnreachable, detail: null };
  }
  return {
    message: LEARN.startRefusedGeneric,
    detail: code === "" ? null : code,
  };
}
