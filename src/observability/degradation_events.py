"""Degradation reasons, on their way to the trajectory (ADR 0097).

ADR 0081 put the degradation *ladder* on a metric:
`research_degradations_total{rung,component}` answers **how much** and
**where**, and it deliberately refuses to carry the reason, because a
reason is a specific machine token and a metric attribute is the one
place where specificity is expensive. The reason stayed a log field.

That left a second gap, one rung down from the one ADR 0081 closed. A
campaign record keeps no log, so eight degradation codes existed only as
log lines and `src/campaign/report.py` printed `not detected from
records` for the taxonomy classes whose only evidence they were —
planning/decomposition had *no* record-borne signal at all. The failure
is ADR 0081's own, one level up: a class the report cannot see reads as
a class that did not happen.

This module is the third record, and the narrow one: it carries the
reason to the run's trajectory, where a campaign *can* read it back.

- The **metric** is untouched. `record_degradation_rung` still owns the
  counter and is still called at the sites that count a rung; nothing
  here loads an instrument, and a degradation is recorded here whether
  or not `enable_metrics` is on. That independence is the point — the
  campaign matrix runs with metrics off.
- The **log line** is untouched. Every site keeps its own distinct
  event, which is `docs/reliability.md` §5's rule and the reason ADR
  0081 declined to fold the rungs onto one event.
- The **observer** is a `ContextVar`, for exactly the reason
  `bind_llm_call_observer` is one (ADR 0078): the reader's per-paper
  fan-out records from a thread pool, the runner copies its context into
  every node thread, and a process-global callback would attribute one
  run's degradations to whichever run registered last.

Nothing is bound by default, so an unobserved process — `make run`, a
unit test, any code path with no trajectory open — pays one `ContextVar`
read and records nothing. That is what keeps a trajectory that fires no
degradation byte-identical to the one it was before this module existed.

The two vocabularies are closed for ADR 0081's reasons, and checked the
way that ADR's are: `tests/test_degradation_ladder.py` parses `src/` and
looks every literal up, because a fixture only proves the fixture and
the constant agree while a parse proves the *call sites* do.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Final

from src.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# The two closed vocabularies
# ---------------------------------------------------------------------------

#: The overflow bucket, named the same way `metrics.py` names its own.
UNREGISTERED: Final = "unregistered"

#: 15 §7.1's class ids, for the five classes a degradation can land in.
#: The same strings `src/campaign/report.py`'s `TAXONOMY` uses, because
#: the producer naming its own class is what stops the report keeping a
#: second code-to-class table that can drift from the sites.
TAXONOMY_PLANNING_DECOMPOSITION: Final = "planning_decomposition"
TAXONOMY_RETRIEVAL_MISS: Final = "retrieval_miss"
TAXONOMY_PARSING_CHUNKING_RANKING: Final = "parsing_chunking_ranking"
TAXONOMY_SYNTHESIS_ORGANIZATION: Final = "synthesis_organization"
TAXONOMY_CITATION_PROVENANCE: Final = "citation_provenance"

DEGRADATION_TAXONOMY_CLASSES: Final[frozenset[str]] = frozenset(
    {
        TAXONOMY_PLANNING_DECOMPOSITION,
        TAXONOMY_RETRIEVAL_MISS,
        TAXONOMY_PARSING_CHUNKING_RANKING,
        TAXONOMY_SYNTHESIS_ORGANIZATION,
        TAXONOMY_CITATION_PROVENANCE,
    }
)

#: The codes this repository records. Every one of them is also a
#: `KNOWN_EVENTS` log event, and deliberately so: the code on the
#: trajectory and the event name in the log are the same string, so an
#: operator who greps a log and an analyst who reads a campaign are
#: naming the same thing. `tests/test_degradation_ladder.py` asserts the
#: containment in both directions.
DEGRADATION_CODES: Final[frozenset[str]] = frozenset(
    {
        "planner_plan_fallback_to_query",
        "planner_response_unparseable",
        "reader_degraded_to_abstract_only",
        "reader_paper_abstract_only",
        "search_empty_keeping_prior_papers",
        "synthesizer_citations_dropped",
        "synthesizer_response_unparseable",
        "synthesizer_retry_budget_exhausted",
    }
)


# ---------------------------------------------------------------------------
# The observation, and the observer that may be listening for it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DegradationObservation:
    """One degradation, as its own call site described it.

    A frozen value for `LlmCallObservation`'s reason: the observer is a
    *reader* of something that already happened, and it must not be able
    to change the run that handed it over.

    Attributes:
        taxonomy_class: Which of 15 §7.1's classes this degradation is
            an instance of, named by the site rather than inferred later.
        code: The machine token, identical to the site's log event name.
        component: ADR 0081's component attribute — which part degraded.
    """

    taxonomy_class: str
    code: str
    component: str


DegradationObserver = Callable[[DegradationObservation], None]
"""Notified once per recorded degradation, after the site's own log line."""


_degradation_observer: ContextVar[DegradationObserver | None] = ContextVar(
    "degradation_observer", default=None
)


def bind_degradation_observer(
    observer: DegradationObserver,
) -> Token[DegradationObserver | None]:
    """Observe every degradation recorded in this context (ADR 0097).

    The observer is a pure sink and must not raise; if it does, the
    failure is absorbed and logged rather than allowed to reach a call
    site whose entire purpose is surviving a failure. That rule is ADR
    0081's — "an observability bug must not become a job failure" — and
    it is why the containment lives here rather than being left to the
    caller to remember.

    Returns:
        The reset token, for `reset_degradation_observer`.
    """
    return _degradation_observer.set(observer)


def reset_degradation_observer(token: Token[DegradationObserver | None]) -> None:
    """Restore the previous observer after a run leaves its context."""
    _degradation_observer.reset(token)


def record_degradation_reason(
    *, taxonomy_class: str, code: str, component: str
) -> None:
    """Offer one degradation to whatever is observing this run.

    Called *in addition to* the site's own log line and its
    `record_degradation_rung` call, never instead of either: the three
    records answer different questions and ADR 0081's argument for
    keeping them distinct is unchanged.

    An unregistered class or code is recorded under `unregistered`
    rather than dropped or raised — ADR 0081's containment, for its
    reason: the static check in `tests/test_degradation_ladder.py` is
    the enforcement, and a call site on a failure path is the worst
    possible place to discover a typo by raising.
    """
    observer = _degradation_observer.get()
    if observer is None:
        return
    try:
        observer(
            DegradationObservation(
                taxonomy_class=(
                    taxonomy_class
                    if taxonomy_class in DEGRADATION_TAXONOMY_CLASSES
                    else UNREGISTERED
                ),
                code=code if code in DEGRADATION_CODES else UNREGISTERED,
                component=component,
            )
        )
    except Exception:
        # The degradation is already logged and already counted; this
        # record is the third and least of the three. Losing it must not
        # cost the run the rung it was surviving.
        log.warning(
            "contract_shadow_failed",
            extra={"hook": "degradation_observer"},
            exc_info=True,
        )


__all__ = [
    "DEGRADATION_CODES",
    "DEGRADATION_TAXONOMY_CLASSES",
    "TAXONOMY_CITATION_PROVENANCE",
    "TAXONOMY_PARSING_CHUNKING_RANKING",
    "TAXONOMY_PLANNING_DECOMPOSITION",
    "TAXONOMY_RETRIEVAL_MISS",
    "TAXONOMY_SYNTHESIS_ORGANIZATION",
    "UNREGISTERED",
    "DegradationObservation",
    "DegradationObserver",
    "bind_degradation_observer",
    "record_degradation_reason",
    "reset_degradation_observer",
]
