"""The path-manifest contract, with the licensing posture as code.

`planning/07-learning-platform/02-CONTENT.md` §2.2 states a licensing
posture for paper content, and WO-W15 acceptance criterion 2 requires it
"in code, not in prose". That is what this module is: every rule below is
a validator that refuses to load a manifest that breaks it, so the posture
cannot drift by someone editing a JSON file.

## The rules, and where they come from

| Rule | Source | What it refuses |
|---|---|---|
| `L1_ARXIV_ABS_ONLY` | `02` §2.2 posture table | A paper whose link is anything but an arXiv **abs** page |
| `L2_NO_FILE_URLS` | same, "never re-host or display" | Any URL pointing at a file (`.pdf`, `/pdf/`, `/e-print/`, `/ftp/`) |
| `L3_NO_REHOSTING_FIELDS` | `02` §1.2 ("`body` is NULL for anything we don't own") | A *field* that could hold full text, a PDF, or a transcript |
| `L4_ABSTRACT_ATTRIBUTED` | `02` §2.2 ("abstracts with attribution") | An abstract with no source and no link back to its arXiv abs page |
| `L5_S2_LINKS_BACK` | `02` §2.2 / §3.2 (ODC-BY attribution) | A citation-ancestry claim with no Semantic Scholar link-back |
| `L6_ID_MATCHES_URL` | `02` §1.2 (`resource_id` namespacing) | A `resource_id` that disagrees with the link it claims to describe |
| `L7_NO_YOUTUBE` | `02` §2.1 (30-day metadata clock) | YouTube metadata in a git-tracked file no refresh job can expire |
| `L8_NONCOMMERCIAL` | `02` §2.2, §6 Q2 | A manifest that does not carry the non-commercial posture, or an NC/SA link-out with no licence URL |
| `L9_QUOTES_ATTRIBUTED` | `02` §2.2 ("sparing, attributed, quote-marked") | A briefing that block-quotes without attribution, or quotes too much |

`L7` deserves its reason in full, because it *removes* a resource kind
`02` §1.1 defines. YouTube's Developer Policies cap non-authorized
metadata storage at 30 days, refreshed or deleted. A git-tracked manifest
has no expiry: the commit is permanent and Phase W ships no refresh job
(`02` §2.1's weekly `videos.list` batch is Phase L work). So a curated
video may not be committed here at all — not "should not", *cannot*. The
`video` kind returns when the refresh job that makes it lawful does.

## The status queue

`02` §3.1: "only a human moves anything past `proposed`". The queue is
`proposed → approved → published → stale`, and the two gates are
mechanical:

- `approved` and above require a named reviewer and a review date
  (`S1_REVIEW_REQUIRED`);
- a paper at `approved` and above requires a briefing file that exists,
  parses, and names the same reviewer (`S2_BRIEFING_REQUIRED`).

Because both gates are structural, an unreviewed briefing cannot reach
`approved` by any edit that leaves the manifest loadable — which is
WO-W15 acceptance criterion 1.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Final, Literal, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from src.errors import LearnContentInvalid
from src.tools.arxiv_search import canonical_paper_key

# --------------------------------------------------------------------------
# Rule identifiers. Stable strings so tests, the review queue, and the PR
# can all name the same rule; every raised message starts with one.
# --------------------------------------------------------------------------

#: Plain shape violations — a missing field, a wrong type, an unknown
#: key. Not a posture rule, but the CLI still wants one vocabulary.
RULE_SCHEMA: Final = "S0_SCHEMA"

RULE_ARXIV_ABS_ONLY: Final = "L1_ARXIV_ABS_ONLY"
RULE_NO_FILE_URLS: Final = "L2_NO_FILE_URLS"
RULE_NO_REHOSTING_FIELDS: Final = "L3_NO_REHOSTING_FIELDS"
RULE_ABSTRACT_ATTRIBUTED: Final = "L4_ABSTRACT_ATTRIBUTED"
RULE_S2_LINKS_BACK: Final = "L5_S2_LINKS_BACK"
RULE_ID_MATCHES_URL: Final = "L6_ID_MATCHES_URL"
RULE_NO_YOUTUBE: Final = "L7_NO_YOUTUBE"
RULE_NONCOMMERCIAL: Final = "L8_NONCOMMERCIAL"
RULE_QUOTES_ATTRIBUTED: Final = "L9_QUOTES_ATTRIBUTED"

RULE_REVIEW_REQUIRED: Final = "S1_REVIEW_REQUIRED"
RULE_BRIEFING_REQUIRED: Final = "S2_BRIEFING_REQUIRED"
RULE_PATH_PUBLISH_GATE: Final = "S3_PATH_PUBLISH_GATE"
RULE_POSITIONS_CONTIGUOUS: Final = "S4_POSITIONS_CONTIGUOUS"
RULE_UNIQUE_RESOURCE_IDS: Final = "S5_UNIQUE_RESOURCE_IDS"
RULE_GENERATED_NEEDS_RUN: Final = "S6_GENERATED_NEEDS_RUN"
RULE_FIXTURE_BANNER: Final = "S7_FIXTURE_BANNER"
RULE_RATIONALE_PRESENT: Final = "S8_RATIONALE_PRESENT"

#: Every rule this module enforces, for the review queue's header and the
#: PR's criteria→evidence map.
ALL_RULES: Final[tuple[str, ...]] = (
    RULE_ARXIV_ABS_ONLY,
    RULE_NO_FILE_URLS,
    RULE_NO_REHOSTING_FIELDS,
    RULE_ABSTRACT_ATTRIBUTED,
    RULE_S2_LINKS_BACK,
    RULE_ID_MATCHES_URL,
    RULE_NO_YOUTUBE,
    RULE_NONCOMMERCIAL,
    RULE_QUOTES_ATTRIBUTED,
    RULE_REVIEW_REQUIRED,
    RULE_BRIEFING_REQUIRED,
    RULE_PATH_PUBLISH_GATE,
    RULE_POSITIONS_CONTIGUOUS,
    RULE_UNIQUE_RESOURCE_IDS,
    RULE_GENERATED_NEEDS_RUN,
    RULE_FIXTURE_BANNER,
    RULE_RATIONALE_PRESENT,
)

# --------------------------------------------------------------------------
# Vocabularies.
# --------------------------------------------------------------------------

#: `02` §3.1's queue. Ordered — `_RANK` turns it into a comparison.
#:
#: `rejected` is the one addition to the queue the card sketches, and it
#: earns its place: `02` §3.1 says rejects are *kept* with their reason,
#: "giving the judge pass a growing calibration set". Without the state
#: a rejection is a deletion, and the reason lives only in a commit
#: message nobody will search.
Status = Literal["proposed", "approved", "published", "stale", "rejected"]

_RANK: Final[dict[str, int]] = {
    "proposed": 0,
    "approved": 1,
    "published": 2,
    # Neither of these is "above published": both are content that must
    # never be served, so both rank below `approved` for every serving
    # decision. `stale` is published content whose link-out broke
    # (`02` §3.3); `rejected` is a proposal a human turned down.
    "stale": -1,
    "rejected": -2,
}

#: The Phase W subset of `02` §1.1's five kinds. `video` is absent by
#: `L7_NO_YOUTUBE`; `lesson` and `exercise` are Phase L (they need the
#: `body` column this schema deliberately does not have).
ResourceKind = Literal["paper", "external_course"]

#: `02` §1.2: "non-nullable and three-valued ... so 'unlabeled' is
#: unrepresentable".
Provenance = Literal["curated", "generated", "authored"]

PathKind = Literal["flagship", "fixture"]

SequencingMethod = Literal["citation_ancestry", "chronological", "editorial"]

#: Field names that could hold somebody else's content. Asserted absent
#: from every manifest model by `rehosting_fields()`.
#:
#: `text` is deliberately *not* on this list: it is `Abstract.text`, the
#: one piece of third-party prose the posture permits (CC0 arXiv
#: metadata, and only alongside its attribution). It is bounded at 3,000
#: characters, which is an abstract and cannot be a paper. `body` is on
#: the list and `Briefing.body` is not checked against it, because a
#: briefing body is our own prose — the distinction the whole posture
#: turns on.
FORBIDDEN_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "body",
        "captions",
        "content",
        "full_text",
        "fulltext",
        "html",
        "markdown",
        "pdf",
        "pdf_url",
        "raw",
        "transcript",
    }
)

# `https://arxiv.org/abs/2305.18290` and the pre-2007 `abs/cs/0112017`
# form. A trailing `vN` is accepted because arXiv serves it; the
# canonical key erases it (`canonical_paper_key`).
_ARXIV_ABS_URL = re.compile(
    r"^https://arxiv\.org/abs/"
    r"(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)$"
)

# Anything that smells like a file rather than a landing page. `02` §2.2
# permits linking out; it does not permit deep-linking the artefact, and
# a landing-page-only rule is the version that is testable.
_FILE_URL = re.compile(
    r"(?:\.pdf$|\.ps$|\.gz$|/pdf/|/e-print/|/ftp/|/src/)", re.IGNORECASE
)

_YOUTUBE = re.compile(r"(?:youtube\.com|youtu\.be|ytimg\.com)", re.IGNORECASE)

_S2_HOST = re.compile(r"^https://(?:www\.|api\.)?semanticscholar\.org/", re.IGNORECASE)

_HTTPS_URL = re.compile(r"^https://[^\s\"'<>]+$")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Licences whose terms travel with the material (`02` §2.3's "sleeper
#: risk"). Linking out to them is fine; doing so without naming the
#: licence URL is not.
_COPYLEFT_LICENSES: Final[frozenset[str]] = frozenset(
    {"CC BY-NC-SA-4.0", "CC BY-SA-4.0", "CC BY-NC-4.0", "GPL-3.0"}
)


class ContentValidationError(LearnContentInvalid, ValueError):
    """A manifest or briefing broke a rule this module enforces.

    Carries the rule id so callers (the CLI, the tests, the review
    queue) can group failures without parsing prose.

    ADR 0064 gives it the code `learn_content_invalid` — the 503 the
    `/learn/*` routes already answer — and keeps the `ValueError`
    mixin, which is load-bearing twice over: Pydantic only converts a
    validator's `ValueError` into a `ValidationError` (see
    `_first_rule_violation` below, which unwraps exactly that), and
    `_coerce_date` catches `ValueError` from `date.fromisoformat`.
    """

    def __init__(self, rule: str, message: str) -> None:
        self.rule = rule
        super().__init__(f"{rule}: {message}")


def _require(condition: bool, rule: str, message: str) -> None:
    """Raise `ContentValidationError(rule, message)` unless `condition`."""
    if not condition:
        raise ContentValidationError(rule, message)


def _check_url(value: str, *, field: str) -> str:
    """Every URL in a manifest is https, is a landing page, is not YouTube."""
    _require(
        bool(_HTTPS_URL.match(value)),
        RULE_NO_FILE_URLS,
        f"{field} must be an absolute https URL; got {value!r}",
    )
    _require(
        not _FILE_URL.search(value),
        RULE_NO_FILE_URLS,
        f"{field} points at a file, not a landing page: {value!r}. "
        "02 §2.2 permits linking out to the abs page and nothing else.",
    )
    _require(
        not _YOUTUBE.search(value),
        RULE_NO_YOUTUBE,
        f"{field} is a YouTube URL: {value!r}. YouTube metadata may be "
        "stored for at most 30 days (02 §2.1) and a git-tracked manifest "
        "cannot expire, so no YouTube resource may be committed until the "
        "refresh job exists.",
    )
    return value


class _Strict(BaseModel):
    """Base for every manifest model: closed, immutable, no coercion.

    `extra="forbid"` is load-bearing, not tidiness. A manifest that grew
    a `"full_text"` key would otherwise load and silently carry it; here
    it fails at parse time with the offending key named.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Abstract(_Strict):
    """A paper abstract, displayed only with its attribution.

    arXiv metadata is CC0, but `02` §2.2 renders abstracts with
    attribution anyway ("some abstracts may contain third-party
    content"). The model makes that unconditional: there is no way to
    carry the text without the source and the link.
    """

    text: str = Field(min_length=1, max_length=3000)
    source: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def _abs_url(cls, value: str) -> str:
        _check_url(value, field="abstract.url")
        _require(
            bool(_ARXIV_ABS_URL.match(value)),
            RULE_ABSTRACT_ATTRIBUTED,
            f"abstract.url must be the paper's arXiv abs page; got {value!r}",
        )
        return value


class Sequencing(_Strict):
    """Why this entry sits where it does.

    `02` §2.2's heuristic is "(a) citation-graph ancestry — a paper cited
    by the others comes first; (b) year; (c) judged difficulty". An entry
    ordered by ancestry is making a claim derived from Semantic Scholar
    data, and `02` §3.2 requires S2-derived facts to link back — so
    `evidence_url` stops being optional the moment `method` is
    `citation_ancestry`.
    """

    method: SequencingMethod
    cites: list[str] = Field(default_factory=list, max_length=32)
    evidence_url: str | None = None
    note: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def _ancestry_claims_link_back(self) -> Sequencing:
        if self.method == "citation_ancestry":
            _require(
                self.evidence_url is not None,
                RULE_S2_LINKS_BACK,
                "sequencing.method='citation_ancestry' is a claim derived "
                "from Semantic Scholar; 02 §3.2 requires it to link back, "
                "so evidence_url is mandatory here.",
            )
            _require(
                bool(self.cites),
                RULE_S2_LINKS_BACK,
                "sequencing.method='citation_ancestry' with an empty "
                "`cites` list claims an ancestry it does not name.",
            )
        if self.evidence_url is not None:
            _check_url(self.evidence_url, field="sequencing.evidence_url")
            _require(
                bool(_S2_HOST.match(self.evidence_url)),
                RULE_S2_LINKS_BACK,
                "sequencing.evidence_url must point at semanticscholar.org "
                f"so the derived fact links back; got {self.evidence_url!r}",
            )
        return self


class Entry(_Strict):
    """One item in a path: a paper to read, or a link-out beside it.

    There is no field here for the paper. That is the point — see
    `L3_NO_REHOSTING_FIELDS`. What the entry carries is *ours*: the
    rationale, the sequencing claim, the vocabulary pointers, and a
    pointer to a briefing file we wrote.
    """

    position: int = Field(ge=1, le=200)
    resource_id: str = Field(min_length=3, max_length=120)
    kind: ResourceKind
    title: str = Field(min_length=1, max_length=300)
    authors: list[str] = Field(default_factory=list, max_length=40)
    # A 31-author paper listed with four names would read as a
    # four-author paper. `author_count` is the true figure, so a surface
    # can render "et al." because it knows the list is short, not
    # because someone typed it.
    author_count: int = Field(ge=0, le=5000)
    year: int = Field(ge=1900, le=2100)
    canonical_url: str
    license_note: str = Field(min_length=1, max_length=400)
    license_id: str | None = Field(default=None, max_length=60)
    license_url: str | None = None
    attribution: str = Field(min_length=1, max_length=300)
    provenance: Provenance
    status: Status
    rationale: str = Field(min_length=10, max_length=240)
    vocabulary: list[str] = Field(default_factory=list, max_length=12)
    est_minutes: int = Field(ge=1, le=600)
    sequencing: Sequencing
    abstract: Abstract | None = None
    briefing_file: str | None = Field(default=None, max_length=200)
    # The resource and our companion have *different* provenance, and
    # collapsing them is how a curated paper starts wearing the label
    # our generated prose earned. A paper is `curated` (someone else
    # made it, we chose it); the briefing beside it is `generated` or
    # `authored`, never `curated`.
    briefing_provenance: Provenance | None = None
    reviewed_by: str | None = Field(default=None, max_length=120)
    reviewed_at: str | None = None
    staleness_note: str | None = Field(default=None, max_length=400)
    rejection_reason: str | None = Field(default=None, max_length=400)

    @field_validator("canonical_url", "license_url")
    @classmethod
    def _urls(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _check_url(value, field="url")

    @field_validator("reviewed_at")
    @classmethod
    def _iso_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _require(
            bool(_ISO_DATE.match(value)),
            RULE_REVIEW_REQUIRED,
            f"reviewed_at must be an ISO date (YYYY-MM-DD); got {value!r}",
        )
        date.fromisoformat(value)
        return value

    @field_validator("rationale")
    @classmethod
    def _one_line(cls, value: str) -> str:
        _require(
            "\n" not in value,
            RULE_RATIONALE_PRESENT,
            "rationale is one line the owner can scan in the review queue; "
            "it must not contain a newline.",
        )
        return value

    @field_validator("briefing_file")
    @classmethod
    def _relative_briefing_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        _require(
            not value.startswith("/") and ".." not in value.split("/"),
            RULE_BRIEFING_REQUIRED,
            "briefing_file is a path relative to the manifest's own "
            f"directory; got {value!r}",
        )
        _require(
            value.endswith(".md"),
            RULE_BRIEFING_REQUIRED,
            f"briefing_file must be a markdown file; got {value!r}",
        )
        return value

    @model_validator(mode="after")
    def _posture(self) -> Entry:
        _require(
            self.author_count >= len(self.authors),
            RULE_SCHEMA,
            f"author_count={self.author_count} is smaller than the "
            f"{len(self.authors)} authors listed; it is the paper's real "
            "author count, which is what tells a surface when to say "
            "'et al.'",
        )
        if self.kind == "paper":
            _require(
                bool(_ARXIV_ABS_URL.match(self.canonical_url)),
                RULE_ARXIV_ABS_ONLY,
                "a paper entry links to its arXiv abs page and nothing "
                f"else (02 §2.2); got {self.canonical_url!r}",
            )
            expected = canonical_paper_key(self.canonical_url)
            _require(
                self.resource_id == expected,
                RULE_ID_MATCHES_URL,
                "resource_id must be the canonical arXiv key for its own "
                f"link ({expected!r}); got {self.resource_id!r}",
            )
        else:
            _require(
                self.resource_id.startswith("ext:"),
                RULE_ID_MATCHES_URL,
                "a non-paper resource_id is namespaced `ext:<slug>`; got "
                f"{self.resource_id!r}",
            )
        if self.abstract is not None:
            _require(
                canonical_paper_key(self.abstract.url)
                == canonical_paper_key(self.canonical_url),
                RULE_ABSTRACT_ATTRIBUTED,
                "abstract.url must be this entry's own abs page; got "
                f"{self.abstract.url!r} for {self.canonical_url!r}",
            )
        if self.license_id in _COPYLEFT_LICENSES:
            _require(
                self.license_url is not None,
                RULE_NONCOMMERCIAL,
                f"license_id={self.license_id!r} carries terms that travel "
                "with the material (02 §2.3); license_url is mandatory so "
                "the notice can be rendered beside it.",
            )
        _require(
            (self.briefing_file is None) == (self.briefing_provenance is None),
            RULE_BRIEFING_REQUIRED,
            "briefing_file and briefing_provenance travel together: a "
            "companion with no provenance is the unlabeled content 02 "
            "§1.2 makes unrepresentable.",
        )
        _require(
            self.briefing_provenance != "curated",
            RULE_BRIEFING_REQUIRED,
            "a briefing companion is ours — `generated` or `authored`. "
            "`curated` describes the paper, not the prose beside it.",
        )
        _require(
            (self.status == "rejected") == (self.rejection_reason is not None),
            RULE_REVIEW_REQUIRED,
            "a rejected entry records why it was rejected, and only a "
            "rejected entry carries a rejection reason. 02 §3.1 keeps "
            "rejects with their reason as a calibration set.",
        )
        if _RANK[self.status] >= _RANK["approved"]:
            _require(
                bool(self.reviewed_by) and bool(self.reviewed_at),
                RULE_REVIEW_REQUIRED,
                f"status={self.status!r} requires a named reviewer and a "
                "review date. 02 §3.1: only a human moves anything past "
                "`proposed`.",
            )
            if self.kind == "paper":
                _require(
                    self.briefing_file is not None,
                    RULE_BRIEFING_REQUIRED,
                    f"a paper at status={self.status!r} must name the "
                    "briefing companion that was reviewed.",
                )
        return self

    @property
    def servable(self) -> bool:
        """May this entry leave the API? `02` §3.1's gate, in one place."""
        return _RANK[self.status] >= _RANK["approved"]


class LicensingPosture(_Strict):
    """The W-OD-3 posture, carried by every manifest as literal values.

    Each field is a `Literal` with exactly one permitted value, so the
    posture is not configuration — it is an assertion the manifest makes
    about itself, and a manifest that tries to say something else fails
    to load. `counsel_confirmed` is the one honest variable: `02`'s
    header says every licensing note "needs owner/counsel confirmation
    before anything ships", and pretending otherwise would be the
    fabricated-green-checkmark failure this repo names.
    """

    posture_id: Literal["W-OD-3"]
    full_text: Literal["link-out-only"]
    abstracts: Literal["displayed-with-attribution"]
    quotes: Literal["sparing-and-attributed"]
    s2_derived_facts: Literal["link-back-required"]
    commercial_use: Literal["none-through-phase-w"]
    counsel_confirmed: bool
    source: str = Field(min_length=1, max_length=200)


class GenerationPlan(_Strict):
    """The briefing campaign this manifest is waiting for.

    WO-W15's content half is completion-gated on W-OD-2, so the campaign
    is *described* here rather than run: the exact command, the ceiling
    it would run under, and the estimate the owner is approving. When the
    decision lands, this block is the spec — nobody has to reconstruct
    what was proposed.
    """

    status: Literal["deferred-awaiting-W-OD-2", "complete"]
    decision: Literal["W-OD-2"]
    pipeline: str = Field(min_length=1, max_length=200)
    command: str = Field(min_length=1, max_length=600)
    max_budget_usd: float = Field(gt=0, le=500)
    est_cost_usd_per_briefing: float = Field(gt=0, le=50)
    est_review_hours_per_briefing: tuple[float, float]
    note: str = Field(min_length=1, max_length=600)


class ReviewPlan(_Strict):
    """Who reviews this path, and what the hours are budgeted at."""

    owner: str = Field(min_length=1, max_length=120)
    decisions: list[str] = Field(min_length=1, max_length=8)
    curation_minutes_per_entry: int = Field(ge=1, le=120)


class PathManifest(_Strict):
    """One learning path, versioned as content (`02` §1.2).

    A flagship path is "never silently mutated under a learner": edits
    that change what a learner sees bump `version`. Nothing enforces that
    mechanically here — it is an editorial rule the review queue restates
    — but the field exists so a surface can show it and a diff can catch
    it.
    """

    manifest_version: Literal[1]
    path_id: str = Field(min_length=3, max_length=80, pattern=r"^[a-z0-9\-]+$")
    kind: PathKind
    title: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=400)
    version: int = Field(ge=1, le=1000)
    status: Status
    updated_at: str
    fixture: bool
    banner: str | None = Field(default=None, max_length=400)
    licensing: LicensingPosture
    review: ReviewPlan
    generation: GenerationPlan | None = None
    entries: list[Entry] = Field(min_length=1, max_length=100)

    @field_validator("updated_at")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        _require(
            bool(_ISO_DATE.match(value)),
            RULE_REVIEW_REQUIRED,
            f"updated_at must be an ISO date (YYYY-MM-DD); got {value!r}",
        )
        date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def _structure(self) -> PathManifest:
        positions = [e.position for e in self.entries]
        _require(
            positions == list(range(1, len(self.entries) + 1)),
            RULE_POSITIONS_CONTIGUOUS,
            "entries must be listed in order with contiguous positions "
            f"1..{len(self.entries)}; got {positions}",
        )
        ids = [e.resource_id for e in self.entries]
        _require(
            len(set(ids)) == len(ids),
            RULE_UNIQUE_RESOURCE_IDS,
            "a resource may appear once per path; duplicates: "
            f"{sorted({i for i in ids if ids.count(i) > 1})}",
        )
        by_position = {e.resource_id: e.position for e in self.entries}
        for entry in self.entries:
            for cited in entry.sequencing.cites:
                _require(
                    cited in by_position,
                    RULE_S2_LINKS_BACK,
                    f"entry {entry.resource_id!r} cites {cited!r}, which is "
                    "not in this path — `cites` names earlier entries, not "
                    "the whole bibliography.",
                )
                _require(
                    by_position[cited] < entry.position,
                    RULE_S2_LINKS_BACK,
                    f"entry {entry.resource_id!r} at position "
                    f"{entry.position} cites {cited!r} at position "
                    f"{by_position[cited]}: a paper cited by another comes "
                    "first (02 §2.2).",
                )
        _require(
            self.fixture == (self.kind == "fixture"),
            RULE_FIXTURE_BANNER,
            "`fixture` and `kind` must agree: a fixture path is the one "
            "thing that may render without funded content, and the two "
            "flags saying different things is how that guarantee rots.",
        )
        if self.fixture:
            _require(
                bool(self.banner),
                RULE_FIXTURE_BANNER,
                "a fixture path must carry the banner every surface "
                "renders; unlabeled fixture content is the fake-state "
                "failure this repo refuses.",
            )
            for entry in self.entries:
                _require(
                    entry.briefing_provenance in (None, "authored"),
                    RULE_FIXTURE_BANNER,
                    f"fixture entry {entry.resource_id!r} claims "
                    f"briefing_provenance={entry.briefing_provenance!r}; "
                    "fixture scaffolding is authored placeholder prose and "
                    "may not borrow the `generated, human-reviewed` label "
                    "that a funded, reviewed briefing earns.",
                )
        else:
            _require(
                self.banner is None,
                RULE_FIXTURE_BANNER,
                "only a fixture path carries a banner; a real path with a "
                "banner would train users to ignore it.",
            )
        if self.status == "published":
            # Two different things can make an entry not-published, and
            # they are not the same failure. An entry still `proposed`
            # or `approved` has not been published yet, and publishing
            # the path around it publishes a path built on material the
            # reviewer has not finished with. An entry that has gone
            # `stale` or been `rejected` was withdrawn *after* the fact;
            # 02 §3.3 flags the path for editorial repair rather than
            # unpublishing it, and the loader already refuses to serve
            # the row.
            pending = [
                e.resource_id
                for e in self.entries
                if e.status in ("proposed", "approved")
            ]
            _require(
                not pending,
                RULE_PATH_PUBLISH_GATE,
                "a published path may not contain an entry still working "
                f"through the queue; these have not published: {pending}",
            )
            _require(
                any(e.status == "published" for e in self.entries),
                RULE_PATH_PUBLISH_GATE,
                "a published path with nothing published in it is an empty "
                "promise; publish at least one entry or leave the path "
                "below `published`.",
            )
        return self

    @property
    def servable_entries(self) -> list[Entry]:
        """Entries the API may return — `approved` and above, in order."""
        return [e for e in self.entries if e.servable]


# --------------------------------------------------------------------------
# Briefing companions.
# --------------------------------------------------------------------------

#: The machine-readable header every briefing file opens with. A markdown
#: comment so it stays invisible when rendered, JSON so it parses with the
#: standard library — the repo has no YAML dependency and this is not a
#: good reason to add one.
BRIEFING_HEADER_OPEN: Final = "<!-- provenance"
BRIEFING_HEADER_CLOSE: Final = "-->"

#: `02` §3.2: generated items are labeled "at the point of display — not
#: in a footer, not in an about page". The file's first visible line is
#: the point of display in the source, so it carries the label too.
_LABEL_LINE = re.compile(r"^>\s+\*\*(.+?)\*\*", re.MULTILINE)

_BLOCKQUOTE_LINE = re.compile(r"^>\s?(.*)$")

#: An attribution line closing a block quote: an em-dash, then a source.
_ATTRIBUTION_LINE = re.compile(r"^\s*(?:>\s*)?—\s+\S+")

#: `02` §2.2: quotes are "sparing". 1,200 characters is roughly a long
#: paragraph — enough to quote a definition or a claim, far short of
#: reproducing a section.
MAX_QUOTED_CHARS: Final = 1200
MAX_QUOTED_FRACTION: Final = 0.15

#: The fraction rule needs a body to be a fraction *of*. Below this it
#: would fail a three-paragraph note with one short quotation in it,
#: which is not the risk `02` §2.2 is describing — the hard character
#: ceiling above still applies at every length.
MIN_BODY_FOR_FRACTION: Final = 800


class BriefingHeader(_Strict):
    """Provenance for one briefing companion (`02` §3.2, WO-W15 c5).

    `generated_by` is the run id of the pipeline run that drafted it.
    `S6_GENERATED_NEEDS_RUN` makes it mandatory whenever the file claims
    the `generated` label, so a hand-written file cannot wear a
    provenance it did not earn — and, symmetrically, a generated file
    cannot hide that it was generated.
    """

    resource_id: str = Field(min_length=3, max_length=120)
    path_id: str = Field(min_length=3, max_length=80)
    provenance: Provenance
    label: str = Field(min_length=1, max_length=120)
    briefing_version: int = Field(ge=1, le=1000)
    generated_by: str | None = Field(default=None, max_length=120)
    generated_at: str | None = None
    reviewed_by: str | None = Field(default=None, max_length=120)
    reviewed_at: str | None = None

    @model_validator(mode="after")
    def _label_matches_provenance(self) -> BriefingHeader:
        if self.provenance == "generated":
            _require(
                bool(self.generated_by),
                RULE_GENERATED_NEEDS_RUN,
                "a briefing labeled `generated` must name the pipeline run "
                "that produced it; an empty `generated_by` is an "
                "unattributable claim.",
            )
            _require(
                self.label == "generated, human-reviewed",
                RULE_GENERATED_NEEDS_RUN,
                "02 §3.2 fixes the display label for generated content: "
                f"'generated, human-reviewed'; got {self.label!r}",
            )
        return self


class Briefing(_Strict):
    """A parsed briefing companion: its header and its markdown body."""

    header: BriefingHeader
    body: str = Field(min_length=1)


def parse_briefing(text: str) -> Briefing:
    """Split a briefing file into its provenance header and its body.

    Args:
        text: The file's full contents.

    Returns:
        The parsed briefing.

    Raises:
        ContentValidationError: The header is missing, unparseable, or
            fails `BriefingHeader`'s own rules.
    """
    stripped = text.lstrip()
    _require(
        stripped.startswith(BRIEFING_HEADER_OPEN),
        RULE_BRIEFING_REQUIRED,
        "a briefing file opens with its provenance header "
        f"({BRIEFING_HEADER_OPEN} ... {BRIEFING_HEADER_CLOSE}); this one "
        f"starts {stripped[:40]!r}",
    )
    end = stripped.find(BRIEFING_HEADER_CLOSE)
    _require(
        end != -1,
        RULE_BRIEFING_REQUIRED,
        f"the provenance header is never closed with {BRIEFING_HEADER_CLOSE}",
    )
    raw = stripped[len(BRIEFING_HEADER_OPEN) : end]
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContentValidationError(
            RULE_BRIEFING_REQUIRED,
            f"the provenance header is not valid JSON: {exc}",
        ) from exc
    _require(
        isinstance(payload, dict),
        RULE_BRIEFING_REQUIRED,
        "the provenance header must be a JSON object",
    )
    try:
        header = BriefingHeader.model_validate(payload)
    except ValidationError as exc:
        rendered = str(exc)
        rule = next((r for r in ALL_RULES if r in rendered), RULE_SCHEMA)
        raise ContentValidationError(rule, rendered) from exc
    body = stripped[end + len(BRIEFING_HEADER_CLOSE) :].strip()
    _require(
        bool(body),
        RULE_BRIEFING_REQUIRED,
        f"briefing {header.resource_id!r} has a header and no body",
    )
    return Briefing(header=header, body=body)


def _quoted_runs(body: str) -> list[tuple[int, list[str]]]:
    """Return `(start_line_index, lines)` for each block-quote run."""
    runs: list[tuple[int, list[str]]] = []
    current: list[str] = []
    start = 0
    for index, line in enumerate(body.splitlines()):
        match = _BLOCKQUOTE_LINE.match(line)
        if match is not None:
            if not current:
                start = index
            current.append(match.group(1))
            continue
        if current:
            runs.append((start, current))
            current = []
    if current:
        runs.append((start, current))
    return runs


def check_quotes(briefing: Briefing) -> None:
    """Enforce `02` §2.2's "sparing, attributed, quote-marked" on a body.

    A block-quote run must be closed by an attribution line (`— source`)
    within the run itself or on the line immediately after it, and the
    quoted material must stay under both a hard character ceiling and a
    fraction of the briefing. The first block quote is exempt when it is
    the provenance label line, which every briefing opens with.

    Raises:
        ContentValidationError: On an unattributed or oversized quote.
    """
    lines = briefing.body.splitlines()
    quoted = 0
    for start, run in _quoted_runs(briefing.body):
        joined = "\n".join(run).strip()
        if _LABEL_LINE.match("> " + joined.split("\n")[0]) and start == 0:
            # The provenance label line, not a quotation.
            continue
        attributed = any(_ATTRIBUTION_LINE.match(line) for line in run)
        if not attributed:
            # The first non-empty line after the quote. A blank line has
            # to be allowed here: in markdown a non-blank line directly
            # under a block quote is lazy continuation and joins the
            # quote, so "attribute on the very next line" would forbid
            # the only formatting that renders correctly.
            for line in lines[start + len(run) :]:
                if not line.strip():
                    continue
                attributed = bool(_ATTRIBUTION_LINE.match(line))
                break
        _require(
            attributed,
            RULE_QUOTES_ATTRIBUTED,
            f"the block quote at line {start + 1} of "
            f"{briefing.header.resource_id!r} is not attributed. 02 §2.2: "
            "quotes are sparing, attributed, and quote-marked — close the "
            "run with an `— <source>` line.",
        )
        quoted += len(joined)
    _require(
        quoted <= MAX_QUOTED_CHARS,
        RULE_QUOTES_ATTRIBUTED,
        f"{briefing.header.resource_id!r} quotes {quoted} characters; the "
        f"ceiling is {MAX_QUOTED_CHARS}. A briefing is our prose about a "
        "paper, not a reproduction of it.",
    )
    body_len = len(briefing.body)
    if body_len >= MIN_BODY_FOR_FRACTION:
        _require(
            quoted / body_len <= MAX_QUOTED_FRACTION,
            RULE_QUOTES_ATTRIBUTED,
            f"{briefing.header.resource_id!r} is "
            f"{quoted / body_len:.0%} quoted material; the ceiling is "
            f"{MAX_QUOTED_FRACTION:.0%}.",
        )


def check_briefing_urls(briefing: Briefing) -> None:
    """No briefing may deep-link a PDF, a mirror, or a YouTube video.

    The manifest's URLs are validated field by field; a briefing body is
    free prose, so its links are swept here with the same rules.

    Raises:
        ContentValidationError: On a file URL or a YouTube URL.
    """
    for url in re.findall(r"https?://[^\s\)\]\>\"']+", briefing.body):
        trimmed = url.rstrip(".,;:")
        _require(
            not _FILE_URL.search(trimmed),
            RULE_NO_FILE_URLS,
            f"briefing {briefing.header.resource_id!r} links to a file: "
            f"{trimmed!r}. Link to the abs page (02 §2.2).",
        )
        _require(
            not _YOUTUBE.search(trimmed),
            RULE_NO_YOUTUBE,
            f"briefing {briefing.header.resource_id!r} links to YouTube: "
            f"{trimmed!r}. See L7_NO_YOUTUBE.",
        )


def check_display_label(briefing: Briefing) -> None:
    """The file's first visible line carries the provenance label.

    `02` §3.2 puts the label "at the point of display — not in a footer".
    In a markdown source the first line *is* the point of display, so the
    rule is enforceable here rather than left to whichever surface
    renders it later.

    Raises:
        ContentValidationError: The label line is missing or disagrees
            with the header.
    """
    first = briefing.body.lstrip().splitlines()[0] if briefing.body.strip() else ""
    match = _LABEL_LINE.match(first)
    _require(
        match is not None,
        RULE_GENERATED_NEEDS_RUN,
        f"briefing {briefing.header.resource_id!r} must open with its "
        "provenance label as a bold block-quote line, e.g. "
        "'> **Generated by the learning agent, reviewed by <name>.**'",
    )
    assert match is not None  # narrowed by `_require`
    label_text = match.group(1).lower()
    if briefing.header.provenance == "generated":
        _require(
            "generated" in label_text and "review" in label_text,
            RULE_GENERATED_NEEDS_RUN,
            f"briefing {briefing.header.resource_id!r} is labeled "
            f"{first!r}, which does not say it was generated and "
            "reviewed.",
        )


def rehosting_fields(*models: type[BaseModel]) -> set[str]:
    """Return any field in `models` that could hold others' content.

    `L3_NO_REHOSTING_FIELDS` is a rule about the *shape* of the schema,
    not about a value, so it is checked by walking the models. `02` §1.2:
    "the schema physically cannot 'accidentally' store a video transcript
    or a paper's full text".

    A `Literal`-typed field is exempt, because the rule is about capacity
    and a `Literal` has none: `LicensingPosture.full_text` is spelled
    `Literal["link-out-only"]` and can hold that string or fail to
    validate. Naming a field after the thing it forbids is the clearest
    way to write the posture down, and it is not a place a paper could
    ever land.
    """
    found: set[str] = set()
    for model in models:
        for name, field in model.model_fields.items():
            if name not in FORBIDDEN_FIELD_NAMES:
                continue
            if get_origin(field.annotation) is Literal:
                continue
            found.add(f"{model.__name__}.{name}")
    return found


MANIFEST_MODELS: Final[tuple[type[BaseModel], ...]] = (
    Abstract,
    Sequencing,
    Entry,
    LicensingPosture,
    GenerationPlan,
    ReviewPlan,
    PathManifest,
    BriefingHeader,
)


def parse_manifest(payload: Any) -> PathManifest:
    """Validate a decoded manifest document.

    Pydantic wraps a validator's `ContentValidationError` in a
    `ValidationError`, which buries the rule id in a multi-line report.
    Callers of this module — the CLI, the loader, the tests — want one
    error type with one rule on it, so the wrapper is unwrapped here.

    Args:
        payload: The object `json.load` produced.

    Returns:
        The validated manifest.

    Raises:
        ContentValidationError: Carrying the first rule id the document
            broke, or `S0_SCHEMA` for a plain shape violation.
    """
    try:
        return PathManifest.model_validate(payload)
    except ValidationError as exc:
        rendered = str(exc)
        for rule in ALL_RULES:
            if rule in rendered:
                raise ContentValidationError(rule, rendered) from exc
        raise ContentValidationError(RULE_SCHEMA, rendered) from exc
