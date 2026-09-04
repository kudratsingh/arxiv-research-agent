"""The error taxonomy: one base class, one closed set of codes.

Before this module the repository had thirteen exception classes with no
common ancestor, `job.error = f"{type(exc).__name__}: {exc}"` handing
psycopg and httpx text (DSNs, hostnames, filesystem paths, unbounded
length) straight to API clients, and `error_type = type(exc).__name__` —
an *internal class name* — doing duty as both a public API field and a
metric attribute. Renaming a class silently broke client branching and
forked a metric series; nothing anywhere said which failures a client
could branch on.

`AppError` fixes the identity problem rather than the plumbing one. Four
attributes, and each exists because something downstream needs exactly
it:

- `code` — the stable, snake_case, machine-readable name. It is what
  reaches the client's `error.code`, `job.error`, `job.error_type` and
  the `research_jobs_total{error_type}` attribute. All four now say the
  same word.
- `http_status` — the boundary mapping, so a route never restates it.
- `retryable` — may the caller retry *this exact request*? A field,
  not a guess a client has to make from the status code.
- `public_message` — a sentence safe to show a human. It never contains
  upstream exception text, and the classes below are the only place
  those sentences are written.

`ERROR_CODES` is closed on purpose. An open string used as a metric
attribute is unbounded cardinality; an open string used as a client
field is an unversioned contract. `__init_subclass__` refuses a
duplicate code at import time, and `tests/test_errors.py` pins the set
against the registry in both directions.

## Naming: why some codes are not family-prefixed

`planning/08-assurance/03-ARCHITECTURE.md` §2.1 defines eleven families
— `invalid_*`, `not_found_*`, `conflict_*`, `rate_limited`,
`budget_exceeded_*`, `upstream_*`, `timeout_*`, `cancelled_*`,
`unauthorized`/`forbidden`, `internal_*`. The families are implemented
here as **base classes**, which is where the family's real content lives:
the HTTP status and the retryability. Every *new* code takes its
family's prefix.

Codes that were already on the wire before this module existed keep
their exact spelling — `job_not_found`, not `not_found_job`. Renaming
them would be the precise harm this taxonomy exists to prevent: they are
recorded in `web/contract/fixtures/*.json`, described in
`docs/revamp/04-ARCHITECTURE.md` §3.4, named in `src/config.py`'s own
setting descriptions (`error_type=hitl_timeout`, `error_type=orphaned`),
and three of them are live `research_jobs_total{error_type}` series that
a rename would fork. A cosmetic prefix is not worth any of that. The
family is still available to a client — through the HTTP status and the
`retryable` flag — and to us, through the class hierarchy.

## What is deliberately *not* here

The 122 ad-hoc `raise ValueError` sites are not a migration target. The
rule adopted instead is **boundary typing**: anything that can reach the
API surface, a job record, or a metric attribute is an `AppError`;
internal invariants stay `ValueError`. See ADR 0064.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Final

__all__ = [
    "ERROR_CODES",
    "JOB_ERROR_TYPES",
    "AppError",
    "BudgetExceededError",
    "CancellationError",
    "ConflictError",
    "ForbiddenError",
    "GatewayTimeoutError",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "UpstreamError",
    "error_class_for_code",
    "error_class_for_status",
    "error_envelope",
    "state_conflict_message",
    "registered_error_classes",
]


# Populated by `__init_subclass__`. Module-private because the two
# accessors below are the supported way in: a caller that wants "is this
# a real code?" should ask `ERROR_CODES`, and a caller that wants the
# class should ask `error_class_for_code`.
_BY_CODE: dict[str, type[AppError]] = {}


class AppError(Exception):
    """Base of every failure that may reach a client, a job or a metric.

    A bare `AppError` is, by definition, a failure with no more specific
    meaning — so the base itself carries the `internal_unexpected` code
    and a 500. There is deliberately no separate `InternalError` class
    to be forgotten about: the fall-through *is* the root.

    Subclasses set `code`, and override `http_status` / `retryable` /
    `public_message` where their family's default is wrong.

    Instances may carry three things the class cannot know:

    - `log_detail` — the human-readable, possibly sensitive explanation.
      It goes to the log and to `str(exc)`. It never reaches a client.
    - `public_message` — a per-instance override of the class sentence,
      for the few cases that can safely name a concrete state (a job's
      status, say). Still never upstream text.
    - `wire_detail` — what the response's legacy `detail` field carries.
      Defaults to `code`, which is what the contract says. It exists
      because two shapes predate this module and the current web client
      parses both: the 429's `{"error", "key_id", "limit_per_hour"}`
      object (`web/lib/api/errors.ts` reads `limit_per_hour` off it) and
      the conflict strings that carry `(status=running)` (the same file
      regexes the state out to build its sentence). Dropping either
      would silently downgrade a live surface to generic copy, so the
      envelope is additive over them rather than replacing them.
    """

    code: ClassVar[str] = "internal_unexpected"
    http_status: ClassVar[int] = 500
    retryable: ClassVar[bool] = False
    public_message: ClassVar[str] = "The server could not complete this request."

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Register the subclass's code, refusing a collision.

        Enforced at import time rather than only in a test, because two
        classes sharing a code is the one failure that makes every
        downstream consumer — client branch, log filter, metric series —
        quietly wrong rather than loudly broken.

        Only a class that declares `code` in its *own* body registers.
        A subclass that inherits its parent's code is a specialization,
        not a second entry in the contract.
        """
        super().__init_subclass__(**kwargs)
        own_code = cls.__dict__.get("code")
        if not isinstance(own_code, str) or not own_code:
            return
        existing = _BY_CODE.get(own_code)
        if existing is not None:
            raise ValueError(
                f"duplicate AppError code {own_code!r}: "
                f"{existing.__qualname__} and {cls.__qualname__}"
            )
        _BY_CODE[own_code] = cls

    def __init__(
        self,
        log_detail: str | None = None,
        *,
        public_message: str | None = None,
        wire_detail: str | Mapping[str, Any] | list[Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        # `str(exc)` is the log-side detail, never the client-side one.
        # Falling back to the code keeps a bare `raise JobNotFound()`
        # from producing an empty log line.
        super().__init__(log_detail if log_detail is not None else self.code)
        self.log_detail: Final = log_detail
        self._public_message = public_message
        self._wire_detail = wire_detail
        self.headers: Final = dict(headers) if headers is not None else None

    @property
    def message(self) -> str:
        """The sentence a client is allowed to see."""
        return (
            self._public_message
            if self._public_message is not None
            else self.public_message
        )

    @property
    def wire_detail(self) -> str | Mapping[str, Any] | list[Any]:
        """What the response's legacy `detail` field carries.

        The code, unless an instance overrode it for one of the two
        pre-existing shapes named in the class docstring.
        """
        return self._wire_detail if self._wire_detail is not None else self.code


# ---------------------------------------------------------------------------
# The families. Each base carries its family's HTTP status, retryability
# and generic code; the generic code is what an `HTTPException` raised
# outside this taxonomy maps onto, so every status has a name.
# ---------------------------------------------------------------------------


class InvalidRequestError(AppError):
    """`invalid_*` — the request itself is malformed or self-contradictory."""

    code = "invalid_request"
    http_status = 422
    public_message = "The request was rejected as invalid."


class NotFoundError(AppError):
    """`not_found_*` — no such resource, *or* it belongs to someone else.

    ADR 0036 answers 404 for both on purpose, so the sentence must never
    imply that the thing exists.
    """

    code = "not_found"
    http_status = 404
    public_message = "That resource is not available."


class UnauthorizedError(AppError):
    """`unauthorized*` — no acceptable credential was presented."""

    code = "unauthorized"
    http_status = 401
    public_message = "This request was not authorized."


class ForbiddenError(AppError):
    """`forbidden*` — the credential is real and the action is not allowed."""

    code = "forbidden"
    http_status = 403
    public_message = "This principal may not perform that action."


class ConflictError(AppError):
    """`conflict_*` — the request is well formed but the state moved."""

    code = "conflict"
    http_status = 409
    public_message = "This action is not available in the current state."


class RateLimitedError(AppError):
    """`rate_limited` — retryable, but only after `Retry-After`."""

    code = "rate_limited"
    http_status = 429
    retryable = True
    public_message = "Rate limit reached for this key."


class BudgetExceededError(ConflictError):
    """`budget_exceeded_*` — a spend ceiling stopped the work.

    409 rather than 402: nothing about the request was wrong, and the
    same request succeeds once the window or the cap moves. Not
    retryable — retrying immediately spends nothing and changes nothing.
    """

    code = "budget_exceeded"
    public_message = "This run reached its cost limit."


class UpstreamError(AppError):
    """`upstream_*` — a dependency outside this process failed."""

    code = "upstream_unavailable"
    http_status = 502
    retryable = True
    public_message = "An upstream dependency is unavailable."


class ServiceUnavailableError(UpstreamError):
    """`upstream_*` at 503 — this deployment cannot serve the request now."""

    code = "service_unavailable"
    http_status = 503
    public_message = "This service is temporarily unable to answer."


class GatewayTimeoutError(AppError):
    """`timeout_*` — something took longer than its budget allowed."""

    code = "timeout_upstream"
    http_status = 504
    retryable = True
    public_message = "The request took longer than its time budget allowed."


class CancellationError(AppError):
    """`cancelled_*` — the work was stopped deliberately, not by a fault."""

    code = "cancelled"
    http_status = 409
    public_message = "The work was cancelled before it finished."


# ---------------------------------------------------------------------------
# HTTP-boundary codes. Every one of these spellings is already on the
# wire; see the module docstring for why none of them is being renamed.
# ---------------------------------------------------------------------------


class JobNotFound(NotFoundError):
    code = "job_not_found"
    public_message = "That job is not available."


class ConversationNotFound(NotFoundError):
    code = "conversation_not_found"
    public_message = "That conversation is not available."


class SessionNotFound(NotFoundError):
    code = "session_not_found"
    public_message = "That session is not available."


class JobNotAwaitingReview(ConflictError):
    code = "job_not_awaiting_review"
    public_message = "This job is not waiting for a plan review."


class SessionNotAwaitingLearner(ConflictError):
    code = "session_not_awaiting_learner"
    public_message = "This session is not waiting for a reply."


class JobHasNoReport(ConflictError):
    code = "job_has_no_report"
    public_message = "This job has not produced a report to export."


class BriefingCompanionRequired(ConflictError):
    code = "briefing_companion_required"
    public_message = "That resource has no servable briefing companion."


class ReviseRequiresPlan(InvalidRequestError):
    code = "revise_requires_plan"
    public_message = "A `revise` action must carry the replacement plan."


class InvalidLearnerProfile(InvalidRequestError):
    """The domain rules Pydantic's schema cannot express.

    This replaces a `detail=str(exc)` that put a `ValueError` message
    from `src/learning/profile_store.py` into an API body. The rule that
    was broken is named in the log; the client gets one code.
    """

    code = "invalid_learner_profile"
    public_message = "The learner profile was rejected as invalid."


class MissingApiKey(UnauthorizedError):
    code = "missing_api_key"
    public_message = "This request carried no API key."


class InvalidApiKey(UnauthorizedError):
    code = "invalid_api_key"
    public_message = "This API key was not accepted."


class ApiAuthMisconfigured(AppError):
    """Auth is switched on and there is no keystore to check against.

    500, not 401: nothing the caller did produced this, and answering
    401 would tell an operator to look at the client.
    """

    code = "api_auth_misconfigured"
    public_message = "This deployment's authentication is misconfigured."


class LearnerProfileDisabled(NotFoundError):
    code = "learner_profile_disabled"
    public_message = "The learner profile surface is not enabled here."


class LearnerProfileRequiresAuth(NotFoundError):
    code = "learner_profile_requires_auth"
    public_message = "The learner profile surface requires an authenticated principal."


class LearnerProfileNotFound(NotFoundError):
    code = "learner_profile_not_found"
    public_message = "No learner profile has been recorded for this principal."


class LearnerProfileRequired(NotFoundError):
    code = "learner_profile_required"
    public_message = "This action needs a learner profile to exist first."


class LearnerProgressRequiresAuth(ServiceUnavailableError):
    """The ledger has no anonymous rows, so there is nothing to scope to.

    503 and *not* retryable: it is a deployment configuration, so the
    honest answer is "this deployment cannot serve it", not "try later".
    """

    code = "learner_progress_requires_auth"
    retryable = False
    public_message = "The progress ledger requires an authenticated principal."


class SessionLoopDisabled(NotFoundError):
    code = "session_loop_disabled"
    public_message = "The guided-read session surface is not enabled here."


class SessionLoopRequiresAuth(NotFoundError):
    code = "session_loop_requires_auth"
    public_message = "The session surface requires an authenticated principal."


class LearnContentDisabled(NotFoundError):
    code = "learn_content_disabled"
    public_message = "The learning-content surface is not enabled here."


class LearnPathNotFound(NotFoundError):
    code = "learn_path_not_found"
    public_message = "That learning path is not available."


class LearnResourceNotFound(NotFoundError):
    code = "learn_resource_not_found"
    public_message = "That learning resource is not available."


# ---------------------------------------------------------------------------
# Job-outcome codes. These are the `error_type` vocabulary: they reach
# `research_jobs_total{error_type}`, `JobDetail.error_type`, and the
# `job_failed` SSE frame. `web/lib/copy/errors.ts` maps each to a
# sentence, and `web/tests/copy/errorTypeDrift.test.ts` re-derives the
# set from `ERROR_CODES` on every run so a new one cannot arrive
# unmapped.
# ---------------------------------------------------------------------------


class HitlTimeout(GatewayTimeoutError):
    code = "hitl_timeout"
    public_message = "The plan was not reviewed before its deadline."


class SessionTurnTimeout(GatewayTimeoutError):
    code = "session_turn_timeout"
    public_message = "The session waited too long for a reply."


class JobTimeout(GatewayTimeoutError):
    """The whole-job wall clock, not one upstream call.

    Spelled `timeout` because that is the `error_type` this backend has
    always emitted and there is a live metric series under it.
    """

    code = "timeout"
    public_message = "The run took longer than this deployment allows."


class BudgetExceededRun(BudgetExceededError):
    """A research run crossed `RunCosts`' cap.

    The code is the existing `cost_budget_exceeded`. The *class* that
    gets raised is still `src.observability.costs.CostBudgetExceeded`,
    which this work order may not re-parent (`src/observability/**` is
    owned elsewhere); `as_app_error` maps it here at the boundary
    instead. ADR 0064 records the seam.
    """

    code = "cost_budget_exceeded"


class BudgetExceededSession(BudgetExceededError):
    code = "session_cost_cap_refused"
    public_message = "The session reached its cost limit before another model call."


class JobOrphaned(AppError):
    """The worker that owned the job exited without a terminal write.

    Retryable in the only sense that matters to a caller: resubmitting
    the query is expected to work. `src/api/redriver.py` still writes
    the literal `ORPHANED_ERROR_TYPE`; this class is what puts that
    value inside `ERROR_CODES`.
    """

    code = "orphaned"
    retryable = True
    public_message = "The run was interrupted by a worker restart."


class JobCancelled(CancellationError):
    """A cooperative cancel fired (`src.cancellation.JobCancelledError`).

    Same seam as `BudgetExceededRun`: `src/cancellation.py` is outside
    this work order's file ownership, so the mapping happens in
    `as_app_error` rather than by re-parenting.
    """

    code = "cancelled_job"
    public_message = "The run was stopped before it finished."


class HitlCancelled(CancellationError):
    """The reviewer chose `action=cancel`.

    Never becomes an `error_type`: the job lands `cancelled`, not
    `failed`, so no failure is recorded. It carries a code anyway
    because it crosses the runner boundary and a code is what the log
    and any future surface branch on.
    """

    code = "cancelled_by_reviewer"
    public_message = "The run was cancelled at plan review."


class UpstreamArxiv(UpstreamError):
    code = "upstream_arxiv"
    public_message = "arXiv could not be reached."


class UpstreamPaperRead(UpstreamError):
    code = "upstream_paper_read"
    public_message = "Papers were found but none of them could be read."


class UpstreamModelOutput(UpstreamError):
    code = "upstream_model_output"
    public_message = "The model's output could not be used."


class NoPapersFound(NotFoundError):
    code = "not_found_papers"
    public_message = "No matching arXiv papers were found for these queries."


# ---------------------------------------------------------------------------
# Domain-validation codes raised below the HTTP layer.
# ---------------------------------------------------------------------------


class InvalidProvenance(InvalidRequestError):
    code = "invalid_provenance"
    public_message = "A profile claim violated the provenance rules."


class ForbiddenAnonymousPrincipal(ForbiddenError):
    code = "forbidden_anonymous_principal"
    public_message = "The learner profile store has no anonymous principal."


class InvalidProgressEvent(InvalidRequestError):
    code = "invalid_progress_event"
    public_message = "The progress event was rejected as invalid."


class LearnContentInvalid(ServiceUnavailableError):
    """A manifest on disk failed validation.

    503 and not retryable by the caller: the content is broken until an
    operator fixes it, so "try again" would be a lie. Retryability is
    about the *caller's* next move, not about whether the condition can
    clear on its own.
    """

    code = "learn_content_invalid"
    retryable = False
    public_message = "The learning content on this deployment is not servable."


# ---------------------------------------------------------------------------
# The closed set.
#
# Written out as a literal rather than derived from `_BY_CODE`, because a
# contract that derives itself from its subject pins nothing — the same
# reason `tests/test_contract_sse_events.py` writes its event names out.
# `tests/test_errors.py` ties the two together in both directions.
# ---------------------------------------------------------------------------

ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        # Family fall-throughs.
        "internal_unexpected",
        "invalid_request",
        "not_found",
        "unauthorized",
        "forbidden",
        "conflict",
        "rate_limited",
        "budget_exceeded",
        "upstream_unavailable",
        "service_unavailable",
        "timeout_upstream",
        "cancelled",
        # HTTP boundary.
        "job_not_found",
        "conversation_not_found",
        "session_not_found",
        "job_not_awaiting_review",
        "session_not_awaiting_learner",
        "job_has_no_report",
        "briefing_companion_required",
        "revise_requires_plan",
        "invalid_learner_profile",
        "missing_api_key",
        "invalid_api_key",
        "api_auth_misconfigured",
        "learner_profile_disabled",
        "learner_profile_requires_auth",
        "learner_profile_not_found",
        "learner_profile_required",
        "learner_progress_requires_auth",
        "session_loop_disabled",
        "session_loop_requires_auth",
        "learn_content_disabled",
        "learn_path_not_found",
        "learn_resource_not_found",
        # Job outcomes.
        "hitl_timeout",
        "session_turn_timeout",
        "timeout",
        "cost_budget_exceeded",
        "session_cost_cap_refused",
        "orphaned",
        "cancelled_job",
        "cancelled_by_reviewer",
        "upstream_arxiv",
        "upstream_paper_read",
        "upstream_model_output",
        "not_found_papers",
        # Domain validation below the HTTP layer.
        "invalid_provenance",
        "forbidden_anonymous_principal",
        "invalid_progress_event",
        "learn_content_invalid",
    }
)


#: The subset of `ERROR_CODES` that can end up on a *job* — in
#: `JobDetail.error_type`, in the `job_failed` SSE frame, and as the
#: `research_jobs_total{error_type}` attribute.
#:
#: It is a subset because most codes are HTTP-boundary answers: a
#: `job_not_found` is something a route says, never something a run
#: becomes. Separating the two is what lets the frontend's copy
#: dictionary require a sentence for every value a *run* can carry
#: without also demanding one for forty route answers it will never see.
#:
#: `web/tests/copy/errorTypeDrift.test.ts` reads this block out of this
#: file rather than transcribing it, and
#: `tests/test_errors.py::TestTheJobVocabulary` derives it from the
#: runner, the redriver and the job-path packages — so neither side is
#: a hand-copied list.
JOB_ERROR_TYPES: Final[frozenset[str]] = frozenset(
    {
        "cancelled_job",
        "cost_budget_exceeded",
        "hitl_timeout",
        "internal_unexpected",
        "not_found_papers",
        "orphaned",
        "session_cost_cap_refused",
        "session_turn_timeout",
        "timeout",
        "upstream_arxiv",
        "upstream_model_output",
        "upstream_paper_read",
    }
)


# ---------------------------------------------------------------------------
# Accessors.
# ---------------------------------------------------------------------------


#: Job statuses in the register a person reads, for the two 409s that
#: are allowed to name the state they refused. The status is a wire
#: identifier (`src/api/schemas.py`), never user content, so naming it
#: in a public message leaks nothing — and it is the difference between
#: "not available" and "not available *yet*".
_STATUS_WORDS: Final[Mapping[str, str]] = {
    "pending": "queued",
    "running": "still running",
    "pending_review": "waiting for a plan review",
    "awaiting_learner": "waiting for a learner reply",
    "succeeded": "already finished",
    "failed": "failed",
    "cancelled": "cancelled",
}


def state_conflict_message(action: str, job_status: str) -> str:
    """Public copy for a 409 whose cause is the job's current status.

    The legacy `detail` string carried the state as `"(status=running)"`
    and the current web client regexes it back out to build this same
    sentence (`web/lib/api/errors.ts`). Both survive: `detail` keeps the
    suffix for that client, and the envelope says it in words for one
    that reads `error.message` instead.
    """
    word = _STATUS_WORDS.get(job_status, "in a state that does not allow it")
    return f"Cannot {action}: the job is {word}."


def registered_error_classes() -> Mapping[str, type[AppError]]:
    """Every code that a class declares, mapped to the class.

    A read-only view of the import-time registry. `AppError` itself is
    included under `internal_unexpected` — it is the `internal_*`
    family's only member by design.
    """
    return {AppError.code: AppError, **_BY_CODE}


def error_class_for_code(code: str) -> type[AppError] | None:
    """The class that owns `code`, or `None` if nothing does."""
    return registered_error_classes().get(code)


#: Status → the family class that names it. Used when an `HTTPException`
#: raised outside this taxonomy reaches the boundary: it still gets a
#: code, drawn from `ERROR_CODES`, rather than a bare number.
_BY_STATUS: Final[Mapping[int, type[AppError]]] = {
    400: InvalidRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    422: InvalidRequestError,
    429: RateLimitedError,
    500: AppError,
    502: UpstreamError,
    503: ServiceUnavailableError,
    504: GatewayTimeoutError,
}


def error_class_for_status(http_status: int) -> type[AppError]:
    """The family class for an HTTP status, falling back by class.

    4xx with no exact entry is a client error and gets
    `invalid_request`; anything else is ours and gets the base.
    """
    exact = _BY_STATUS.get(http_status)
    if exact is not None:
        return exact
    if 400 <= http_status < 500:
        return InvalidRequestError
    return AppError


def error_envelope(
    *,
    code: str,
    message: str,
    retryable: bool,
    request_id: str | None,
    detail: str | Mapping[str, Any] | list[Any] | None = None,
) -> dict[str, Any]:
    """Build the one response body every error handler returns.

    ```json
    {"error": {"code", "message", "retryable", "request_id"},
     "detail": "<code>"}
    ```

    `detail` is retained rather than replaced. It is what the current
    web client reads (`web/lib/api/errors.ts`), what the recorded
    contract fixtures in `web/contract/fixtures/` hold, and what the
    Next.js proxy passes through — so the envelope is *additive* over
    it. It defaults to the code, and carries the legacy shape verbatim
    for the two cases that predate this module and are parsed for
    structure: the 429 object and FastAPI's validation array.
    """
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": request_id,
        },
        "detail": code if detail is None else detail,
    }
