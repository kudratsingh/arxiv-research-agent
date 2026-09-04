// The failure half of the copy dictionary (WO-12 criteria 2, 3, 5, 6, 8).
//
// Two vocabularies live here and they are NOT the same thing:
//
//   1. `ApiFailure.kind` — what happened to an HTTP call we made. Twelve
//      variants, normalized by `lib/api/errors.ts` (04 §3.4).
//   2. `JobDetail.error_type` — what the backend says happened to a RUN.
//      Since ADR 0064 this is a CLOSED set of stable codes
//      (`JOB_ERROR_TYPES` in `src/errors.py`), not a mix of constants
//      and Python class names, and the drift test below reads it from
//      there. The fall-through stays anyway: a backend that has landed
//      a thirteenth code before this dictionary has must still say
//      something true.
//
// RC-16 governs the second one and is the reason this file exists rather
// than a `switch` inside a component:
//
//   > the mapped sentence is primary, the raw string never is, and the
//   > raw string always remains one disclosure away.
//
// So `describeErrorType()` returns a STRUCTURE, never a concatenation:
// `sentence` is ours and is gated by the forbidden-string test; `rawError`
// and `errorType` are the backend's, are never edited, and are never the
// primary message. A component that wants both renders both, in that
// order. A component that concatenates them would put backend text into a
// sentence the gate believes it has proven — which is exactly the failure
// mode the gate exists to prevent.

import type { ApiFailure, ApiFailureKind, JobStatus } from "@/lib/api";
import type { StatusSeverity } from "@/lib/tokens";

// ---------------------------------------------------------------------------
// The qualifier the API's silence earns (03 §5.5).
// ---------------------------------------------------------------------------

/**
 * "not reported" rather than "unknown".
 *
 * 03 §5.5: "silence is the API's behaviour, not a gap in our knowledge of
 * it". `unknown` describes us; `not reported` describes the response, and
 * only one of those two is a fact.
 */
export const NOT_REPORTED = "not reported";

// ---------------------------------------------------------------------------
// Severity words and marks (criterion 4; RC-17).
// ---------------------------------------------------------------------------

/**
 * The default word for each of `StatusBanner`'s five severities.
 *
 * RC-17 maps the five onto four roles — `review` and `warning` share the
 * review hue because the palette ships no `warning` colour — so the hue is
 * NOT what tells them apart. The word is, and after the word the mark
 * (`SEVERITY_MARK`, `components/primitives/StatusBadge.tsx`). Five words,
 * five shapes, four hues: a test asserts the first two are distinct
 * precisely because the third is not.
 *
 * A caller almost always overrides this with something specific ("Rate
 * limited", "Not available"). The default exists so that no banner can be
 * rendered wordless.
 */
export const SEVERITY_WORD = {
  info: "Note",
  review: "Review",
  live: "Live",
  warning: "Attention",
  critical: "Failed",
} as const satisfies Record<StatusSeverity, string>;

// ---------------------------------------------------------------------------
// `ApiFailure.kind` — one entry per variant (criterion 5).
// ---------------------------------------------------------------------------

/** What a surface needs to render one failure. */
export interface FailureCopy {
  /** Banner severity. Maps to a role through `STATUS_SEVERITY_ROLE`. */
  severity: StatusSeverity;
  /** The word. Never colour alone (03 §3.4). */
  word: string;
  /** The primary sentence. Never contains raw backend text. */
  sentence: string;
  /** What the user can actually do next. Never "retry automatically". */
  recovery: string;
}

/**
 * Every `ApiFailure.kind`, keyed by the union so a thirteenth variant is a
 * compile error here before it is a missing story.
 *
 * The 401 is the one to read twice. 03 §2.2 row 19 and §6: there is no
 * user identity to re-authenticate, so this is a **server configuration**
 * message. Not "sign in", not "your session expired", not a disabled login
 * button — "a disabled login button is still a fake login" (§6).
 *
 * The 404 is the second. H8: a 404 covers both "does not exist" and
 * "belongs to another principal" by design (`routes.py:59-84`), so the
 * copy says "not available" and never "deleted" or "no permission".
 */
export const FAILURE_COPY = {
  unauthorized: {
    severity: "critical",
    word: "Not accepted",
    sentence: "This deployment is not accepting requests from this server.",
    // Deliberately free of login vocabulary, and tested for it. Naming
    // the thing you are not doing still puts the idea on the page.
    recovery:
      "An operator has to fix the deployment's API key. There is nothing on this page to change.",
  },
  not_found: {
    severity: "info",
    word: "Not available",
    sentence: "That record is not available.",
    recovery:
      "It may never have existed, or it may belong to another principal. The API answers the same way for both.",
  },
  conflict: {
    severity: "warning",
    word: "Already resolved",
    sentence: "This action is no longer available for this run.",
    recovery: "Reload to see where the run actually got to.",
  },
  rate_limited: {
    severity: "warning",
    word: "Rate limited",
    sentence: "This workspace has used its hourly research budget.",
    recovery: "Wait for the window to reset, then ask again.",
  },
  validation: {
    severity: "warning",
    word: "Needs a change",
    sentence: "The server rejected this as invalid.",
    recovery: "Fix the highlighted field and send it again.",
  },
  upstream_unavailable: {
    severity: "critical",
    word: "Unreachable",
    sentence: "The research service is not reachable.",
    recovery: "Nothing was started. Try again once it answers.",
  },
  proxy_misconfigured: {
    severity: "critical",
    word: "Misconfigured",
    sentence:
      "This site cannot reach the research service, because its own server is missing the settings it needs.",
    recovery: "An operator has to fix the deployment. Retrying will not help.",
  },
  server_error: {
    severity: "critical",
    word: "Server error",
    sentence: "The server could not complete this request.",
    recovery: "Try again. If it keeps happening, copy the diagnostics into an issue.",
  },
  offline: {
    severity: "warning",
    word: "No connection",
    sentence: "The server could not be reached from this browser.",
    recovery: "Check the connection, then try again by hand.",
  },
  timeout: {
    severity: "warning",
    word: "No answer",
    sentence: "The server did not answer in time, so the request was dropped.",
    recovery: "Try again by hand. Nothing is retried for you.",
  },
  cancelled: {
    severity: "info",
    word: "Cancelled",
    sentence: "The request was cancelled before it finished.",
    recovery: "Ask again when you are ready.",
  },
  unknown: {
    severity: "critical",
    word: "Unexpected",
    sentence: "Something went wrong that this page does not recognise.",
    recovery: "Copy the diagnostics into an issue; they carry the raw response.",
  },
} as const satisfies Record<ApiFailureKind, FailureCopy>;

/**
 * The status words, for the rare sentence that has to name one.
 *
 * The API's `status` values are snake_case identifiers
 * (`schemas.py:98-124`); rendering `pending_review` at a user would be
 * leaking a wire format into copy. RC-12 register 3 keeps the identifier
 * on the wire and register 1 keeps the lexicon on screen.
 */
export const JOB_STATUS_WORD = {
  pending: "queued",
  running: "running",
  pending_review: "waiting for your review",
  awaiting_learner: "waiting for your response",
  succeeded: "complete",
  failed: "failed",
  cancelled: "cancelled",
} as const satisfies Record<JobStatus, string>;

/** Group thousands without `toLocaleString`, whose output is host-dependent. */
function groupDigits(value: number): string {
  return String(Math.trunc(Math.abs(value))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * How long to wait, in words, from a `Retry-After` count of seconds
 * (criterion 5's 429 variant).
 *
 * Deliberately vague — "about 2 minutes" — because the header is a floor,
 * not a promise, and a countdown would be an ETA. 03 §5.5 forbids ETAs.
 */
export function retryAfterPhrase(retryAfterSec: number): string {
  const seconds = Math.max(1, Math.ceil(retryAfterSec));
  if (seconds < 60) {
    return `about ${seconds} second${seconds === 1 ? "" : "s"}`;
  }
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) {
    return `about ${minutes} minute${minutes === 1 ? "" : "s"}`;
  }
  const hours = Math.ceil(minutes / 60);
  return `about ${hours} hour${hours === 1 ? "" : "s"}`;
}

/** The hourly ceiling sentence, when the 429 body carried one. */
export function rateLimitCeiling(limitPerHour: number): string {
  return `This key allows ${groupDigits(limitPerHour)} request${limitPerHour === 1 ? "" : "s"} an hour.`;
}

/**
 * The composed recovery line for a 429.
 *
 * 03 §2.2 row 18: "Uses `Retry-After` when present. The composer surfaces
 * remaining-budget copy only if a future header supplies it; it does not
 * guess." So the wait comes from the header and the ceiling comes from the
 * body; neither is invented when absent.
 */
export function rateLimitRecovery(
  retryAfterSec: number,
  limitPerHour?: number,
): string {
  const wait = `Try again in ${retryAfterPhrase(retryAfterSec)}.`;
  return limitPerHour === undefined ? wait : `${wait} ${rateLimitCeiling(limitPerHour)}`;
}

/** The line naming which field the server rejected (03 §2.2 row 20). */
export function validationRecovery(
  fields: ReadonlyArray<{ path: string; message: string }>,
): string {
  const named = fields.filter((field) => field.path !== "");
  if (named.length === 0) return FAILURE_COPY.validation.recovery;
  if (named.length === 1) {
    const only = named[0] as { path: string; message: string };
    return `${only.path}: ${only.message}.`;
  }
  return `${named.length} fields need a change: ${named
    .map((field) => field.path)
    .join(", ")}.`;
}

/**
 * One `ApiFailure` → the four strings a banner renders.
 *
 * This is the accessor every surface uses. It takes the normalized union
 * and never a `Response`, so there is no second normalization path and no
 * way for a component to reach the raw body while composing a sentence.
 */
export function describeFailure(failure: ApiFailure): FailureCopy {
  const base = FAILURE_COPY[failure.kind];
  switch (failure.kind) {
    case "rate_limited":
      return {
        ...base,
        recovery: rateLimitRecovery(failure.retryAfterSec, failure.limitPerHour),
      };
    case "validation":
      return { ...base, recovery: validationRecovery(failure.fields) };
    case "conflict": {
      // `{"detail": "job_not_awaiting_review (status=running)"}` — the
      // state is an API identifier and is translated, never echoed. A
      // status this client has never heard of falls back to the qualifier
      // rather than to the wire string.
      if (failure.state === undefined) return base;
      const word =
        (Object.hasOwn(JOB_STATUS_WORD, failure.state)
          ? JOB_STATUS_WORD[failure.state as JobStatus]
          : undefined) ?? NOT_REPORTED;
      return {
        ...base,
        sentence: `This action is no longer available: the run's status is ${word}.`,
      };
    }
    default:
      return base;
  }
}

// ---------------------------------------------------------------------------
// `JobDetail.error_type` — the twelve codes, and the visible
// fall-through (criteria 6, 7, 8; 03 §8.3; RC-16; ADR 0064).
// ---------------------------------------------------------------------------

/** A mapped run failure: our sentence, and what to do about it. */
export interface ErrorTypeCopy {
  sentence: string;
  recovery: string;
}

/**
 * The `error_type` values this backend can produce, mapped.
 *
 * ADR 0064 changed what these keys ARE. They used to be a mix of six
 * deliberate string constants and five Python class names, because the
 * runner's generic handler wrote `error_type = type(exc).__name__` —
 * which meant a class rename in `src/` silently unmapped a sentence
 * here, and an exception from a dependency put its own class name on a
 * user's screen. Every key is now a stable `AppError.code` out of the
 * closed set in `src/errors.py`, and the five class names have become
 * the five codes that replaced them:
 *
 *   NoPapersFoundError          -> not_found_papers
 *   ArxivUnavailableError       -> upstream_arxiv
 *   AllPaperAnalysesFailedError -> upstream_paper_read
 *   SynthesizerOutputError      -> upstream_model_output
 *   JobCancelledError           -> cancelled_job
 *
 * `internal_unexpected` is the new twelfth entry and the important one:
 * it is what *every* untyped failure now becomes, so it is the sentence
 * a user sees when a database or an upstream library falls over. It
 * previously reached them as the fall-through plus a raw psycopg
 * message.
 *
 * `web/tests/copy/errorTypeDrift.test.ts` re-derives the complete list
 * from `src/errors.py`'s `JOB_ERROR_TYPES` on every run, so a new value
 * still cannot arrive silently. The sentences are unchanged from 03
 * §8.3 wherever §8.3 wrote one.
 */
export const ERROR_TYPE_COPY = {
  hitl_timeout: {
    sentence: "The plan was not reviewed in time, so the run stopped.",
    recovery: "Ask again to start a new run.",
  },
  session_turn_timeout: {
    // ADR 0057's parked session. No surface renders this yet — WO-W13
    // builds the one that will — but the drift test below derives the
    // producible set from `src/`, so a backend `error_type` without a
    // sentence is a gap the moment it exists, not the moment it is
    // first seen. Names the timeout without naming a duration: the
    // deadline is server configuration (`session_turn_timeout_sec`),
    // not an API field, the same reason plan review has no countdown.
    sentence: "The session was waiting for an answer for too long, so it ended.",
    recovery: "Start the session again to carry on from where it stopped.",
  },
  session_cost_cap_refused: {
    // ADR 0062: the shared LLM choke point refused the next call. This copy
    // never implies that a final tutor response was generated after the cap.
    sentence: "The session reached its cost limit before another tutor response.",
    recovery: "Start the session again to continue from the work already recorded.",
  },
  cost_budget_exceeded: {
    sentence: "The run reached this workspace's cost limit.",
    recovery: "Ask again with a narrower plan.",
  },
  timeout: {
    sentence: "The run took longer than this workspace allows.",
    recovery: "Ask again with a narrower plan.",
  },
  orphaned: {
    sentence:
      "The run was interrupted by a server restart and could not be resumed safely.",
    recovery: "Ask again to start a new run.",
  },
  internal_dead_letter: {
    // ADR 0068's poison-message bound. Its whole reason for being a
    // separate value from `orphaned` is that the recovery line has to
    // differ: an orphan should be resubmitted, and this one has already
    // been resubmitted several times and stopped its worker every time.
    // Telling the reader to try again would be advice the server has
    // just finished disproving.
    sentence:
      "The run could not be started after several attempts, so it was stopped.",
    recovery: "Ask again with a different question, or copy the diagnostics into an issue.",
  },
  not_found_papers: {
    sentence: "No matching arXiv papers were found for these queries.",
    recovery: "Ask again and edit the arXiv queries at review.",
  },
  upstream_arxiv: {
    sentence: "arXiv could not be reached.",
    recovery: "Ask again later.",
  },
  upstream_paper_read: {
    sentence: "Papers were found but none could be read.",
    recovery: "Ask again and edit the arXiv queries.",
  },
  upstream_model: {
    // The provider, not the output. `upstream_model_output` below is
    // the opposite failure — the model answered and what it said could
    // not be used — and the two recovery lines have to differ, because
    // this one clears on its own and that one does not.
    sentence: "The model provider could not be reached.",
    recovery: "Ask again in a few minutes.",
  },
  upstream_model_output: {
    sentence: "The briefing could not be assembled from what was read.",
    recovery: "Ask again to start a new run.",
  },
  cancelled_job: {
    sentence: "The run was stopped before it finished.",
    recovery: "Ask again to start a new run.",
  },
  internal_unexpected: {
    // ADR 0064's fall-through, promoted to a mapped value. It says "not
    // this run's fault" without pretending to know more than the code
    // does — the raw `error` is still one disclosure away, and it is now
    // the code itself rather than a driver's message.
    sentence: "The run stopped because of a fault on the server.",
    recovery:
      "Ask again. If it keeps happening, copy the diagnostics into an issue.",
  },
} as const satisfies Record<string, ErrorTypeCopy>;

/** The keys, as a list, for the drift test and for stories. */
export const MAPPED_ERROR_TYPES = Object.keys(
  ERROR_TYPE_COPY,
) as Array<keyof typeof ERROR_TYPE_COPY>;

/**
 * 03 §8.3's *anything else* row: "The run failed." **plus the raw `error`
 * message**.
 *
 * The "plus" is not decoration and is not optional. It is the difference
 * between a mapping table and a filter: an `error_type` nobody has written
 * a sentence for still reaches the user as something they can act on and
 * paste into an issue.
 */
export const UNMAPPED_ERROR_TYPE_COPY: ErrorTypeCopy = {
  sentence: "The run failed.",
  recovery: "Ask again to start a new run.",
};

/** What `describeErrorType()` hands a component. */
export interface ErrorTypeDescription extends ErrorTypeCopy {
  /** The backend's string, verbatim. Disclosure and diagnostics only. */
  errorType: string | null;
  /** The backend's `error` message, verbatim. Never edited. */
  rawError: string | null;
  /** `false` when the fall-through produced the sentence. */
  mapped: boolean;
  /**
   * `true` when the raw `error` text MUST be rendered beside the sentence
   * rather than only in a disclosure (03 §8.3's "shows the generic
   * sentence **and** the raw `error` text").
   */
  showRawError: boolean;
}

/**
 * The one accessor for run-failure copy (criterion 6).
 *
 * Returns a structure, never a concatenated string — see the file header.
 * `sentence` is always ours and always safe to render as the primary
 * message (RC-16); `rawError` is always the backend's and is never it.
 */
export function describeErrorType(
  errorType: string | null | undefined,
  error?: string | null,
): ErrorTypeDescription {
  const raw = typeof errorType === "string" && errorType !== "" ? errorType : null;
  const rawError = typeof error === "string" && error !== "" ? error : null;
  const mappedCopy =
    raw !== null && Object.hasOwn(ERROR_TYPE_COPY, raw)
      ? ERROR_TYPE_COPY[raw as keyof typeof ERROR_TYPE_COPY]
      : undefined;

  if (mappedCopy !== undefined) {
    return {
      ...mappedCopy,
      errorType: raw,
      rawError,
      mapped: true,
      showRawError: false,
    };
  }
  return {
    ...UNMAPPED_ERROR_TYPE_COPY,
    errorType: raw,
    rawError,
    mapped: false,
    // The fall-through is VISIBLE. Even with no `error` text to show, the
    // flag stays true so the surface renders the "not reported" row rather
    // than quietly dropping the disclosure.
    showRawError: true,
  };
}

// ---------------------------------------------------------------------------
// Diagnostics (criterion 8; RC-16; 04 §9.2).
// ---------------------------------------------------------------------------

/** One labelled raw value in the diagnostics disclosure. */
export interface RawEvidenceRow {
  label: string;
  value: string;
  /** `false` when the API simply did not report this one. */
  present: boolean;
}

/**
 * The raw strings, labelled, for the diagnostics disclosure — the accessor
 * WO-16 imports.
 *
 * RC-16's second half: "the raw string always remains one disclosure
 * away… because it is what a user pastes into an issue." The labels are
 * the API's own field names on purpose. This is the one place in the
 * product where a wire identifier is the right thing to show, because the
 * reader is about to quote it in a bug report.
 *
 * Absence is rendered as "not reported", never as "unknown" and never as
 * an empty row that reads like a bug in this page.
 */
export function rawErrorEvidence(
  errorType: string | null | undefined,
  error?: string | null,
): RawEvidenceRow[] {
  const raw = typeof errorType === "string" && errorType !== "" ? errorType : null;
  const rawError = typeof error === "string" && error !== "" ? error : null;
  return [
    {
      label: "error_type",
      value: raw ?? NOT_REPORTED,
      present: raw !== null,
    },
    {
      label: "error",
      value: rawError ?? NOT_REPORTED,
      present: rawError !== null,
    },
  ];
}
