"""Deterministic groundedness — hallucination measurement with no judge (ADR 0074).

The corpus is arXiv papers, and that hands this repository an accuracy
signal most systems cannot have: two of the most valuable checks are
decidable without a model call.

- **Does every cited arXiv identifier resolve?** Not "does it exist on
  arxiv.org" — the check is against *the papers the run actually
  retrieved*. That is both the only thing an offline harness can ask and
  the more useful question: a citation to a paper the run never fetched
  is the interesting failure, and it is reported distinctly from an
  identifier that is not a well-formed arXiv id at all.
- **Does every quoted span appear verbatim in the paper's text?** Located
  by string matching under a normalization that is stated in full below
  and proved rule-by-rule in `tests/test_groundedness.py`.

Why this is worth more than the judge it sits beside: it costs nothing,
it does not drift when a model is upgraded, it cannot be argued with,
and it yields a **per-claim binary outcome** — the paired variable a
McNemar comparison needs (`03-ARCHITECTURE.md` §4.2, §4.4).

**The failure mode this module refuses to repeat.**
`metrics.measure_citation_accuracy` returns `1.0` for a report with zero
citations: it awards a perfect score to the exact failure it exists to
catch. Every metric here reports its **denominator**, and an empty
denominator is `None` with a reason code — never a score. The
replacement has landed: `metrics.measure_citation_resolution` adapts the
identifier check for the campaign, and `citation_resolution_rate` is what
the research gate reads. `citation_accuracy` survives as a diagnostic
only, for the reasons its own docstring gives. The quote path is still
waiting on a caller that passes `full_texts` (ADR 0074).

**No network, ever.** Nothing in this module performs I/O. Sources are
passed in by the caller. `tests/conftest.py` would block a socket anyway;
the design reason is stronger than the harness reason.

## What is normalized, exactly

Quote matching runs at three levels and reports which one matched, so a
reader can tell a byte-exact quotation from one that only survives
normalization:

| level | rule |
|---|---|
| `exact` | raw substring, no transformation at all |
| `folded` | format characters stripped, NFKC, line-break de-hyphenation, quote/dash folding, whitespace collapse, case-fold |
| `skeleton` | `folded`, then everything that is not a letter or digit removed |

`folded`, in order:

1. **Format characters removed** — Unicode category `Cf` plus U+00AD
   SOFT HYPHEN. PDF extraction emits soft hyphens, zero-width spaces and
   BOMs that no author typed.
2. **NFKC** — folds the ligatures a TeX-set PDF extracts as single code
   points (U+FB01 `ﬁ`, U+FB02 `ﬂ`, U+FB00/3/4), full-width forms, and
   U+2026 `…` to `...`.
3. **De-hyphenation across a line break** — a hyphen at end of line
   followed by a lowercase letter is joined: `inter-\nnational` →
   `international`. Deliberately *unsafe on its own*: it also turns
   `state-\nof-the-art` into `stateof-the-art`. That is acceptable
   because the `skeleton` level removes hyphens outright and catches the
   case; a dictionary-free rule cannot distinguish the two, and pairing
   a cheap-and-wrong rule with a fallback that subsumes it beats
   pretending the distinction is decidable.
4. **Quote and dash folding** — curly/angle quotes and primes to `'` and
   `"`, and the six dash code points to `-`.
5. **Whitespace collapse** — every run of whitespace (NBSP, thin space
   and friends included) to one space, then strip.
6. **Case-fold.**

What is **not** normalized, and will therefore fail a match: numbers,
units, spelling, word order, abbreviations, stemming, stopwords. There
is no edit-distance or fuzzy matching anywhere in this module. One
changed word is a failed quote, which is the whole point.

## Source completeness, and why it gates the denominator

A quote can only be *falsified* against a source that is complete. Given
only a paper's abstract, "not found" means "not in the abstract", which
is not evidence of anything. So each source carries a `completeness`:

- `full` — the parsed document text. A miss here is a real miss.
- `partial` — ranked evidence chunks, or the abstract. A hit still
  proves groundedness; a miss is `quote_source_incomplete` and leaves
  the denominator rather than failing.

That exclusion is the trap the work order names: a quote check that is
too strict measures the PDF parser instead of the agent. `source_coverage`
on the result reports how much of the corpus was complete, so a reader
can see how much the rate is actually standing on.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Final, Literal, TypedDict

from src.eval.provenance import RunProvenance
from src.graph.state import Citation, EvidenceClaim, PaperMetadata

# ---------------------------------------------------------------------------
# Identity of the check itself
# ---------------------------------------------------------------------------

#: Version of the deterministic check. It carries the same meaning a
#: judge rubric's version carries in ADR 0070: bumping it declares
#: "scores from before and after this edit are not comparable". Changing
#: `NORMALIZATION_SPEC` without bumping this fails a test, which is the
#: rubric-lock mechanism applied to a check that has no prompt.
GROUNDEDNESS_CHECK_VERSION: Final[str] = "1.0.0"

#: The normalization contract, as text, so it can be digested. This is
#: the deterministic analogue of a judge prompt: it is the thing whose
#: change invalidates a comparison, and the thing a row must be able to
#: name. Kept terse and machine-diffable rather than prose — the prose
#: is the module docstring.
NORMALIZATION_SPEC: Final[str] = "\n".join(
    (
        "groundedness-normalization/1",
        "fold.1 strip unicode category Cf and U+00AD",
        "fold.2 NFKC",
        "fold.3 join '-' + linebreak + lowercase letter",
        "fold.4 map curly quotes/primes to ASCII ' and \"",
        "fold.5 map U+2010..U+2015 and U+2212 to '-'",
        "fold.6 collapse whitespace runs to one space, strip",
        "fold.7 casefold",
        "skeleton.1 fold, then drop every non-alphanumeric character",
        "match order: exact, folded, skeleton",
        "no stemming, no stopword removal, no edit distance",
    )
)


def spec_digest() -> str:
    """SHA-256 of `NORMALIZATION_SPEC`, hex, full length.

    Full length rather than truncated for the same reason
    `provenance.Rubric.digest` is: it is compared against a checked-in
    constant, and there is no display cost to pay for.
    """
    return hashlib.sha256(NORMALIZATION_SPEC.encode("utf-8")).hexdigest()


class CheckIdentity(TypedDict):
    """What produced a groundedness result, beyond the run's provenance.

    A run's `provenance` block says which models and which commit; this
    says which *check*. Both are needed before two rows may be compared,
    and only one of them is a judge concern.
    """

    check_version: str
    spec_digest: str


def check_identity() -> CheckIdentity:
    """The `CheckIdentity` for the check as currently defined."""
    return CheckIdentity(
        check_version=GROUNDEDNESS_CHECK_VERSION, spec_digest=spec_digest()
    )


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------

#: Per-claim outcomes. Each is a distinct diagnosis, not a severity: the
#: work order's first requirement is that "cited a paper the run never
#: fetched" and "that is not an arXiv identifier" never collapse into one
#: bucket, because they are different defects with different owners.
CITATION_RESOLVED: Final[str] = "citation_resolved"
CITATION_NOT_RETRIEVED: Final[str] = "citation_not_retrieved"
CITATION_MALFORMED: Final[str] = "citation_malformed"

QUOTE_VERBATIM: Final[str] = "quote_verbatim"
QUOTE_NOT_FOUND: Final[str] = "quote_not_found"
QUOTE_MISATTRIBUTED: Final[str] = "quote_misattributed"
QUOTE_SOURCE_INCOMPLETE: Final[str] = "quote_source_incomplete"
QUOTE_UNATTRIBUTED: Final[str] = "quote_unattributed"
QUOTE_ELIDED_UNCHECKABLE: Final[str] = "quote_elided_uncheckable"

#: Every per-claim reason code, for a caller that wants to tabulate.
CLAIM_REASONS: Final[tuple[str, ...]] = (
    CITATION_RESOLVED,
    CITATION_NOT_RETRIEVED,
    CITATION_MALFORMED,
    QUOTE_VERBATIM,
    QUOTE_NOT_FOUND,
    QUOTE_MISATTRIBUTED,
    QUOTE_SOURCE_INCOMPLETE,
    QUOTE_UNATTRIBUTED,
    QUOTE_ELIDED_UNCHECKABLE,
)

#: Why a metric is `None`. Never a score — that is the defect this
#: module exists to not repeat.
NO_CITATIONS: Final[str] = "no_citations"
NO_QUOTES: Final[str] = "no_quotes"
NO_CHECKABLE_QUOTES: Final[str] = "no_checkable_quotes"
NO_CHECKABLE_CLAIMS: Final[str] = "no_checkable_claims"

EMPTY_METRIC_REASONS: Final[tuple[str, ...]] = (
    NO_CITATIONS,
    NO_QUOTES,
    NO_CHECKABLE_QUOTES,
    NO_CHECKABLE_CLAIMS,
)


# ---------------------------------------------------------------------------
# arXiv identifiers
# ---------------------------------------------------------------------------

#: Post-2007 identifier: `YYMM.NNNN` with four or five sequence digits.
_NEW_STYLE_ID: Final[str] = r"\d{4}\.\d{4,5}"

#: Pre-2007 identifier: `archive[.SUBJ]/YYMMNNN`, e.g. `cs.CL/0301001`,
#: `math/0309136`. Still cited constantly, still served by arxiv.org.
_OLD_STYLE_ID: Final[str] = r"[a-zA-Z][a-zA-Z-]{1,20}(?:\.[a-zA-Z]{2})?/\d{7}"

_VERSION_SUFFIX: Final[str] = r"(?:v\d+)?"

#: One character of an identifier token as it sits in prose: anything
#: that is not whitespace and not a closing delimiter or separator a
#: sentence would put after it.
_TOKEN_CHAR: Final[str] = r"""[^\s\]\)},;"']"""

#: A bare identifier, anchored — used by `canonical_arxiv_id` after the
#: surrounding syntax (a URL path, an `arXiv:` prefix) has been peeled off.
_BARE_ID = re.compile(rf"^(?:{_NEW_STYLE_ID}|{_OLD_STYLE_ID}){_VERSION_SUFFIX}$")

#: Identifiers as they appear *inside running prose*. Deliberately
#: requires a context marker — an `arXiv:` prefix or an arxiv.org URL.
#: A bare `2311.09000` in a sentence is not extracted: the false-positive
#: rate on numeric text is not worth the handful of extra citations, and
#: a report that names a paper without saying it is an arXiv id has not
#: made a checkable claim.
_REPORT_REFERENCE = re.compile(
    rf"""
    (?:
        (?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/
        (?P<url_id>(?:{_NEW_STYLE_ID}|{_OLD_STYLE_ID}){_VERSION_SUFFIX})
      |
        \barxiv[ \t]*:[ \t]*
        (?P<prefixed_id>(?:{_NEW_STYLE_ID}|{_OLD_STYLE_ID}){_VERSION_SUFFIX})
      |
        # An `arXiv:` prefix followed by something containing a digit but
        # not parsing as an id. The digit requirement is what keeps prose
        # ("arXiv: a preprint server") out of the metric while still
        # catching a fabricated identifier.
        \barxiv[ \t]*:[ \t]*
        (?P<bad_id>{_TOKEN_CHAR}{{0,32}}\d{_TOKEN_CHAR}{{0,32}})
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

#: Canonical prefix. Matches the form `src/eval/learning_benchmark.py`
#: already calls canonical (`arxiv:<id>`), so a groundedness row joins
#: against the learning lane's paper ids without a second convention.
CANONICAL_PREFIX: Final[str] = "arxiv:"


def canonical_arxiv_id(raw: str) -> str | None:
    """Canonicalise one arXiv identifier, or `None` if it is not one.

    Accepts every surface form this repository actually produces or
    consumes: the Atom feed's `http://arxiv.org/abs/2311.09000`, the PDF
    URL, the learning lane's `arxiv:1706.03762`, a bare `2311.09000`,
    old-style `cs.CL/0301001`, and any of those with a `vN` suffix.

    Version suffixes are **stripped**, so `2311.09000v2` and
    `2311.09000` canonicalise to the same key. A citation to v2 of a
    paper the run fetched at v1 is not a hallucination, and treating it
    as one would make the metric measure arXiv's revision history.

    Old-style ids are lower-cased whole (`cs.CL/0301001` →
    `arxiv:cs.cl/0301001`) because the archive and subject class are
    case-insensitive in practice and two spellings of one paper must not
    look like two papers.

    Args:
        raw: Any of the surface forms above, with or without surrounding
            whitespace. Not a sentence — this parses one identifier.

    Returns:
        `"arxiv:<id>"`, or `None` when `raw` is not a well-formed arXiv
        identifier.
    """
    text = raw.strip()
    if not text:
        return None

    # Peel a URL down to its path tail. `find` rather than urlparse: the
    # value may be a bare id, and a scheme-less `arxiv.org/abs/...` is a
    # form the corpus actually contains.
    lowered = text.lower()
    for marker in ("arxiv.org/abs/", "arxiv.org/pdf/"):
        index = lowered.find(marker)
        if index >= 0:
            text = text[index + len(marker) :]
            break
    else:
        if lowered.startswith(CANONICAL_PREFIX):
            text = text[len(CANONICAL_PREFIX) :]

    text = text.strip().strip("/")
    # `.pdf` is how arxiv.org/pdf/<id>.pdf spells the same paper.
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    if not _BARE_ID.match(text):
        return None

    text = re.sub(r"v\d+$", "", text)
    if "/" in text:  # old style — archive and subject class fold to lower
        text = text.lower()
    return f"{CANONICAL_PREFIX}{text}"


# ---------------------------------------------------------------------------
# Normalization and matching
# ---------------------------------------------------------------------------

#: Quotation marks and apostrophes, folded to ASCII. A report written in
#: markdown and a PDF set in TeX spell the same punctuation differently
#: — and TeX's `` `` ``/`''` convention means even the ASCII forms are
#: not reliable — so none of these may decide whether a quote matches.
#: NFKC does not fold them; this table is what does.
_QUOTE_FOLD: Final[dict[int, str]] = {
    0x2018: "'",  # LEFT SINGLE QUOTATION MARK
    0x2019: "'",  # RIGHT SINGLE QUOTATION MARK
    0x201A: "'",  # SINGLE LOW-9 QUOTATION MARK
    0x201B: "'",  # SINGLE HIGH-REVERSED-9 QUOTATION MARK
    0x2032: "'",  # PRIME
    0x00B4: "'",  # ACUTE ACCENT
    0x0060: "'",  # GRAVE ACCENT — TeX's opening single quote
    0x2039: "'",  # SINGLE LEFT-POINTING ANGLE QUOTATION MARK
    0x203A: "'",  # SINGLE RIGHT-POINTING ANGLE QUOTATION MARK
    0x201C: '"',  # LEFT DOUBLE QUOTATION MARK
    0x201D: '"',  # RIGHT DOUBLE QUOTATION MARK
    0x201E: '"',  # DOUBLE LOW-9 QUOTATION MARK
    0x201F: '"',  # DOUBLE HIGH-REVERSED-9 QUOTATION MARK
    0x2033: '"',  # DOUBLE PRIME
    0x00AB: '"',  # LEFT-POINTING DOUBLE ANGLE QUOTATION MARK
    0x00BB: '"',  # RIGHT-POINTING DOUBLE ANGLE QUOTATION MARK
}

_DASH_FOLD: Final[dict[int, str]] = {
    codepoint: "-"
    for codepoint in (
        0x2010,  # ‐ hyphen
        0x2011,  # ‑ non-breaking hyphen
        0x2012,  # ‒ figure dash
        0x2013,  # – en dash
        0x2014,  # — em dash
        0x2015,  # ― horizontal bar
        0x2212,  # − minus sign
    )
}

#: End-of-line hyphenation, as a TeX-set PDF extracts it. Requires a
#: letter immediately before the hyphen and a letter after the break;
#: `_dehyphenate` additionally requires that letter to be lower-case, so
#: a line ending in a compound before a proper noun ("Anglo-\nAmerican")
#: is left alone.
_LINE_HYPHEN = re.compile(r"(?<=[^\W\d_])-[ \t]*\r?\n[ \t]*(?=[^\W\d_])")

_WHITESPACE = re.compile(r"\s+")

#: The three-dot and single-code-point ellipsis, as an elision marker
#: inside a quotation. Bracketed forms (`[...]`) are the convention in
#: academic writing and are matched too.
_ELLIPSIS = re.compile(r"\s*[\[\(]?\s*(?:\.\s*\.\s*\.|…)\s*[\]\)]?\s*")

MatchLevel = Literal["exact", "folded", "skeleton"]

#: Match levels in the order they are tried. Reported per quote so the
#: metric can be read as "how many quotations were byte-exact" as well as
#: "how many were the paper's words".
MATCH_LEVELS: Final[tuple[MatchLevel, ...]] = ("exact", "folded", "skeleton")


def _strip_format_chars(text: str) -> str:
    """Drop Unicode `Cf` format characters and the soft hyphen.

    Zero-width spaces, joiners, BOMs and soft hyphens are extraction
    artefacts or invisible authoring accidents. None of them is a
    difference a reader could see, so none of them may decide whether a
    quote is verbatim.
    """
    return "".join(
        # U+00AD is category Cf in current Unicode, but it has moved
        # category historically; naming it explicitly means the rule does
        # not depend on which Python built the interpreter.
        ch
        for ch in text
        if ch != "\u00ad" and unicodedata.category(ch) != "Cf"
    )


def _dehyphenate(text: str) -> str:
    """Join words broken by a hyphen at the end of a line.

    The lower-case test is on the character *after* the break, read from
    the subject string because the pattern's lookahead is zero-width.
    """
    return _LINE_HYPHEN.sub(
        lambda m: "" if m.string[m.end()].islower() else m.group(0), text
    )


def fold(text: str) -> str:
    """Apply the `folded` normalization level. See the module docstring.

    Order is load-bearing: format characters go before NFKC (NFKC does
    not remove them), and de-hyphenation goes before whitespace collapse
    (it needs the line break it is joining across to still exist).
    """
    text = _strip_format_chars(text)
    text = unicodedata.normalize("NFKC", text)
    text = _dehyphenate(text)
    text = text.translate(_QUOTE_FOLD).translate(_DASH_FOLD)
    return _WHITESPACE.sub(" ", text).strip().casefold()


def skeleton(text: str) -> str:
    """Apply the `skeleton` level: `fold`, then keep only letters and digits.

    This is what makes hyphenation-across-a-line-break survivable in the
    general case. `state-\\nof-the-art` and `state-of-the-art` differ
    under `fold` — the de-hyphenation rule mangles the first — and are
    identical here.

    The cost is stated rather than hidden: removing spaces makes
    `the rapist` and `therapist` one string, so a match at this level is
    weaker evidence than a match at `folded`. Which level matched is
    recorded on every quote so the weakness is visible in the data
    instead of buried in the rate.
    """
    return "".join(ch for ch in fold(text) if ch.isalnum())


def _project(text: str, level: MatchLevel) -> str:
    """Project `text` into the comparison space of `level`."""
    if level == "exact":
        return text
    if level == "folded":
        return fold(text)
    return skeleton(text)


def _fragments(quote: str) -> list[str]:
    """Split a quotation on its elision markers.

    A quotation containing `...` is not one span; it is an ordered
    sequence of spans with material removed between them. Splitting and
    requiring the fragments to occur *in order* is the honest check —
    concatenating across the ellipsis would look for text that was never
    written, and skipping such quotes entirely would let the most
    heavily edited quotations escape measurement.
    """
    # Stripped: the quotation's delimiters are its quote marks, so
    # whitespace just inside them is not part of what was quoted, and
    # leaving it on would fail an otherwise byte-exact match.
    return [part.strip() for part in _ELLIPSIS.split(quote) if part.strip()]


def locate_quote(quote: str, source: str) -> MatchLevel | None:
    """Find `quote` in `source`, returning the weakest level that matched.

    Tries `exact`, then `folded`, then `skeleton`, and returns the first
    that succeeds — so the returned level is also a statement about how
    much normalization the match needed.

    A quote with elision markers is matched fragment by fragment, in
    order: fragment *n+1* is searched from the end of fragment *n*. That
    means an elided quotation whose fragments appear in the source in the
    wrong order is correctly *not* found.

    Args:
        quote: The span as written in the report, without its delimiters.
        source: The paper text to search.

    Returns:
        The match level, or `None` when the quote is not in the source at
        any level.
    """
    parts = _fragments(quote)
    if not parts:
        return None
    for level in MATCH_LEVELS:
        haystack = _project(source, level)
        cursor = 0
        for part in parts:
            needle = _project(part, level)
            if not needle:
                # An elision fragment that normalizes away carries no
                # evidence; skipping it cannot create a false match
                # because the remaining fragments still must be ordered.
                continue
            found = haystack.find(needle, cursor)
            if found < 0:
                break
            cursor = found + len(needle)
        else:
            return level
    return None


def locate_quote_in_segments(quote: str, segments: Sequence[str]) -> MatchLevel | None:
    """`locate_quote` over several segments, never matching across two.

    Returns the strongest available verdict: if the quote is `exact` in
    one segment and `skeleton` in another, `exact` is reported, because
    the claim being made is "this quotation exists in this paper" and the
    best evidence for it is the honest answer.
    """
    best: MatchLevel | None = None
    for segment in segments:
        level = locate_quote(quote, segment)
        if level is None:
            continue
        if best is None or MATCH_LEVELS.index(level) < MATCH_LEVELS.index(best):
            best = level
    return best


# ---------------------------------------------------------------------------
# The run's corpus, and the text each paper can be checked against
# ---------------------------------------------------------------------------

SourceCompleteness = Literal["full", "partial"]
SourceOrigin = Literal["pdf_text", "evidence_chunks", "abstract"]


class SourceText(TypedDict):
    """One paper's checkable text, and how much of the paper it is.

    Attributes:
        paper_id: Canonical `arxiv:<id>`, or the paper's raw id when it
            is not an arXiv paper (a Semantic Scholar `s2:` result).
        segments: Contiguous runs of the paper's text. A quote is
            matched **within** one segment and never across two: the
            ranked evidence chunks are non-contiguous, and the
            `skeleton` level deletes whitespace, so a joined string would
            let a quotation bridge a gap that exists in the paper. One
            segment for a parsed document or an abstract; one per chunk
            for the evidence store.
        text: The segments joined, for the audit trail and for a caller
            that wants to show what was searched. Never matched against.
        completeness: `full` when a miss is evidence of a defect,
            `partial` when it is only evidence of a short source.
        origin: Where the text came from, for the audit trail.
    """

    paper_id: str
    segments: list[str]
    text: str
    completeness: SourceCompleteness
    origin: SourceOrigin


class SourceCoverage(TypedDict):
    """How much of the retrieved corpus the quote check could falsify against.

    Published beside `quote_verbatim_rate` because the rate is otherwise
    unreadable: a high rate over two complete sources and a high rate
    over forty are different claims.
    """

    papers: int
    full_text: int
    evidence_chunks: int
    abstract_only: int


def paper_key(paper_id: str) -> str:
    """The index key for a paper id: canonical when arXiv, raw when not.

    Semantic Scholar results enter the corpus with an `s2:` id (see
    `src/tools/semantic_scholar.py`). They are real retrieved papers and
    a citation to one must resolve, so they are indexed under their own
    identity rather than discarded for not being arXiv ids.
    """
    canonical = canonical_arxiv_id(paper_id)
    return canonical if canonical is not None else paper_id.strip()


def build_corpus_index(papers: Sequence[PaperMetadata]) -> dict[str, PaperMetadata]:
    """Index the papers the run actually retrieved, by `paper_key`.

    This — and nothing else — is what a cited identifier is resolved
    against. `docs/eval.md` states the reasoning; the short version is
    that arxiv.org is both unreachable from the harness and the wrong
    oracle, because a citation to a real paper the run never read is
    still a fabricated citation.
    """
    index: dict[str, PaperMetadata] = {}
    for paper in papers:
        key = paper_key(paper.get("id", ""))
        if key:
            index.setdefault(key, paper)
    return index


def build_source_index(
    papers: Sequence[PaperMetadata],
    *,
    full_texts: Mapping[str, str] | None = None,
    evidence: Sequence[EvidenceClaim] | None = None,
) -> dict[str, SourceText]:
    """Assemble the best available checkable text for each retrieved paper.

    Priority, best first:

    1. `full_texts[paper_id]` — the parsed PDF, from whatever the caller
       has (`src.tools.pdf_parser.parse_pdf` writes it to the paper
       cache). Marked `full`.
    2. The paper's `EvidenceClaim.source_text` chunks, concatenated.
       These are verbatim ranked excerpts (ADR 0016) and so are real
       evidence of a hit — but they are a *subset* of the document, so
       they are marked `partial`.
    3. The abstract. Also `partial`, for the same reason.

    Deliberately takes its sources as arguments and performs no I/O: a
    metric module that reaches for a cache is a metric module that can
    fail differently in CI than on a laptop.

    Args:
        papers: `state["papers"]`.
        full_texts: Parsed document text keyed by anything
            `canonical_arxiv_id` accepts, or by the paper's raw id.
        evidence: `state["evidence"]`, when the evidence store is on.

    Returns:
        `paper_key` → `SourceText`, one entry per paper that has any text
        at all.
    """
    by_key: dict[str, str] = {}
    for raw_id, text in (full_texts or {}).items():
        key = paper_key(raw_id)
        if key and text.strip():
            by_key[key] = text

    chunks: dict[str, list[str]] = {}
    for claim in evidence or ():
        key = paper_key(claim.get("paper_id", ""))
        source_text = claim.get("source_text", "")
        if key and source_text.strip():
            chunks.setdefault(key, []).append(source_text)

    index: dict[str, SourceText] = {}
    for paper in papers:
        key = paper_key(paper.get("id", ""))
        if not key:
            continue
        if key in by_key:
            index[key] = _source(key, [by_key[key]], "full", "pdf_text")
        elif key in chunks:
            index[key] = _source(key, chunks[key], "partial", "evidence_chunks")
        elif paper.get("abstract", "").strip():
            index[key] = _source(key, [paper["abstract"]], "partial", "abstract")
    return index


def _source(
    key: str,
    segments: list[str],
    completeness: SourceCompleteness,
    origin: SourceOrigin,
) -> SourceText:
    """Assemble a `SourceText` from its segments."""
    return SourceText(
        paper_id=key,
        segments=segments,
        text="\n\n".join(segments),
        completeness=completeness,
        origin=origin,
    )


def source_coverage(sources: Mapping[str, SourceText]) -> SourceCoverage:
    """Tally the source index by origin, for publication beside the rate."""
    origins = [source["origin"] for source in sources.values()]
    return SourceCoverage(
        papers=len(sources),
        full_text=origins.count("pdf_text"),
        evidence_chunks=origins.count("evidence_chunks"),
        abstract_only=origins.count("abstract"),
    )


# ---------------------------------------------------------------------------
# Extraction: identifiers, and quoted spans
# ---------------------------------------------------------------------------

CitationOrigin = Literal["report_body", "citation_list"]


class CitedIdentifier(TypedDict):
    """One identifier the report or its citation list asserts.

    Attributes:
        raw: Exactly what was written, for the failure message.
        canonical: `canonical_arxiv_id(raw)`, or `None` when malformed.
        origin: Which surface asserted it.
        locator: Where to find it — `report@<offset>` or
            `citations[<n>].<field>`.
    """

    raw: str
    canonical: str | None
    origin: CitationOrigin
    locator: str


#: Fenced code blocks and inline code. Masked before extraction so a
#: JSON example in a report does not become a citation or a quotation.
_CODE_SPAN = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)


def _mask_code(report: str) -> str:
    """Blank out code spans, preserving length so offsets stay valid."""
    return _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), report)


def extract_report_identifiers(report: str) -> list[CitedIdentifier]:
    """Pull every arXiv identifier the report body asserts.

    Only identifiers carrying a context marker (`arXiv:` or an arxiv.org
    URL) are extracted — see `_REPORT_REFERENCE` for why bare numbers are
    not. An `arXiv:` prefix followed by something that is *not* a
    well-formed id is still extracted, with `canonical=None`: the report
    claimed an arXiv identifier and did not produce one, which is a
    citation defect and must not be silently dropped.
    """
    masked = _mask_code(report)
    found: list[CitedIdentifier] = []
    for match in _REPORT_REFERENCE.finditer(masked):
        raw = (
            match.group("url_id") or match.group("prefixed_id") or match.group("bad_id")
        )
        found.append(
            CitedIdentifier(
                raw=raw,
                canonical=canonical_arxiv_id(raw),
                origin="report_body",
                locator=f"report@{match.start()}",
            )
        )
    return found


def extract_citation_list_identifiers(
    citations: Sequence[Citation],
) -> list[CitedIdentifier]:
    """Pull the identifier each citation-list entry asserts.

    This is the surface `citation_accuracy` never looks at. It joins the
    report's `[Author, Year]` tags to a `(lastname, year)` set built from
    the same list, so a synthesizer that invents a whole entry —
    plausible authors, plausible year, fabricated `paper_id` — scores
    1.0. Here the entry's own identifier has to resolve.

    `paper_id` is preferred over `url`; `url` is read only when
    `paper_id` yields nothing, since the two are the same value in every
    entry the synthesizer emits and reporting both would double-count.
    """
    found: list[CitedIdentifier] = []
    for index, citation in enumerate(citations):
        paper_id = str(citation.get("paper_id", "") or "").strip()
        url = str(citation.get("url", "") or "").strip()
        field, raw = ("paper_id", paper_id) if paper_id else ("url", url)
        if not raw:
            # An entry with neither is not an assertion about a paper;
            # `src/agents/synthesizer.py` already drops incomplete
            # entries, so this is defence against a hand-built row.
            continue
        found.append(
            CitedIdentifier(
                raw=raw,
                canonical=canonical_arxiv_id(raw),
                origin="citation_list",
                locator=f"citations[{index}].{field}",
            )
        )
    return found


#: Minimum words for a quoted span to count as a *quotation*. Below this
#: a pair of quote marks is terminology or scare quotes — `the "attention"
#: mechanism`, `a "hallucination"` — and checking those against a paper
#: would measure the report's punctuation habits. Calibrated in
#: `docs/eval.md`; changing it changes the denominator, so it is stated
#: on the result.
MIN_QUOTE_WORDS: Final[int] = 6

#: Upper bound on a quoted span. A "quotation" longer than this is
#: almost always a mismatched delimiter that swallowed several
#: paragraphs, and treating it as a claim would fail the report for a
#: typo.
MAX_QUOTE_CHARS: Final[int] = 1000

#: Minimum words per fragment of an elided quotation. Two words either
#: side of an ellipsis can be found in almost any paper; requiring three
#: keeps a fragment from being evidence-free.
MIN_FRAGMENT_WORDS: Final[int] = 3

#: How far from a quotation to look for the citation that attributes it.
#: One sentence of trailing attribution (`"…" [Smith, 2023]`) or a lead-in
#: (`As [Smith, 2023] puts it, "…"`), not a whole paragraph. A citation
#: further away than this is attributing something else.
ATTRIBUTION_WINDOW_CHARS: Final[int] = 160

_QUOTE_SPAN = re.compile(
    rf'"(?P<straight>[^"]{{1,{MAX_QUOTE_CHARS}}})"'
    rf"|“(?P<curly>[^”]{{1,{MAX_QUOTE_CHARS}}})”"
)

_BLANK_LINE = re.compile(r"\n[ \t]*\n")

#: `[Author, Year]`, the inline form `src/agents/synthesizer.py` emits.
#: Deliberately a private copy of `metrics._CITE_PATTERN` rather than an
#: import: that module belongs to a different work order, its pattern is
#: private, and the two must be able to move independently until the
#: follow-up in ADR 0074 merges them.
_AUTHOR_YEAR = re.compile(r"\[([^\[\]]+?),\s*(\d{4})[a-zA-Z]?\]")


class ExtractedQuote(TypedDict):
    """One quoted span the report presents as a quotation.

    Attributes:
        text: The span, delimiters removed, otherwise untouched.
        start: Character offset of the opening delimiter in the report.
        attributed_to: `paper_key` of the paper the surrounding text
            attributes it to, or `None`.
        attribution: How the attribution was made — `arxiv_id`,
            `author_year`, or `none`.
    """

    text: str
    start: int
    attributed_to: str | None
    attribution: Literal["arxiv_id", "author_year", "none"]


def _first_author_lastname(author_field: str) -> str:
    """Lowercased last name of the first author named in a cite tag.

    Handles the three inline forms the synthesizer emits: `Smith`,
    `Smith et al.`, `Smith and Jones`.
    """
    cleaned = author_field.strip().rstrip(",").strip()
    lowered = cleaned.lower()
    for suffix in (" et al.", " et al", " et. al.", " et. al"):
        if lowered.endswith(suffix):
            cleaned = cleaned[: len(cleaned) - len(suffix)].rstrip()
            break
    if " and " in cleaned:
        cleaned = cleaned.split(" and ", 1)[0].strip()
    tokens = cleaned.split()
    return tokens[-1].lower() if tokens else ""


def _author_year_index(citations: Sequence[Citation]) -> dict[tuple[str, str], str]:
    """`(lastname, year)` → `paper_key`, from the citation list.

    Used only to *attribute* a quotation to a paper. Whether the tag
    itself resolves is `citation_accuracy`'s question, not this module's.
    """
    index: dict[tuple[str, str], str] = {}
    for citation in citations:
        authors = citation.get("authors") or []
        year = str(citation.get("year", "")).strip()[:4]
        if not authors or not year:
            continue
        tokens = str(authors[0]).strip().split()
        if not tokens:
            continue
        key = paper_key(str(citation.get("paper_id", "") or citation.get("url", "")))
        if key:
            index.setdefault((tokens[-1].lower(), year), key)
    return index


def _attribute(
    window: str, author_year: Mapping[tuple[str, str], str]
) -> tuple[str | None, Literal["arxiv_id", "author_year", "none"]]:
    """Resolve the paper a window of text points at.

    An explicit arXiv identifier wins over an `[Author, Year]` tag: it
    names the paper directly, where the tag names it only through a list
    the same model wrote.
    """
    ids = extract_report_identifiers(window)
    for identifier in ids:
        if identifier["canonical"] is not None:
            return identifier["canonical"], "arxiv_id"
    for match in _AUTHOR_YEAR.finditer(window):
        key = author_year.get((_first_author_lastname(match.group(1)), match.group(2)))
        if key:
            return key, "author_year"
    return None, "none"


def _window_after(report: str, end: int) -> str:
    """Text following a quote, up to the window or the next blank line."""
    tail = report[end : end + ATTRIBUTION_WINDOW_CHARS]
    blank = _BLANK_LINE.search(tail)
    return tail[: blank.start()] if blank else tail


def _window_before(report: str, start: int) -> str:
    """Text preceding a quote, back to the window or the previous blank line."""
    head = report[max(0, start - ATTRIBUTION_WINDOW_CHARS) : start]
    blanks = list(_BLANK_LINE.finditer(head))
    return head[blanks[-1].end() :] if blanks else head


def extract_quotes(
    report: str, citations: Sequence[Citation] = ()
) -> list[ExtractedQuote]:
    """Pull every span the report presents as a verbatim quotation.

    Straight `"…"` and curly `“…”` pairs, outside code spans, at least
    `MIN_QUOTE_WORDS` words long and containing no blank line. Markdown
    blockquotes (`> …`) are **not** treated as quotations: in this
    repository's reports a blockquote is as often the model's own summary
    as it is a citation of source text, and a check that fails on the
    former measures formatting.

    Attribution looks forward first — `"…" [Smith, 2023]` is the form the
    synthesizer emits — then backwards for a lead-in.

    Args:
        report: The report markdown.
        citations: `state["citations"]`, used only to resolve
            `[Author, Year]` tags to papers.

    Returns:
        Quotes in document order.
    """
    masked = _mask_code(report)
    author_year = _author_year_index(citations)
    quotes: list[ExtractedQuote] = []
    for match in _QUOTE_SPAN.finditer(masked):
        text = match.group("straight")
        if text is None:
            text = match.group("curly")
        if _BLANK_LINE.search(text):
            continue
        if len(fold(text).split()) < MIN_QUOTE_WORDS:
            continue
        attributed, how = _attribute(_window_after(masked, match.end()), author_year)
        if attributed is None:
            attributed, how = _attribute(
                _window_before(masked, match.start()), author_year
            )
        quotes.append(
            ExtractedQuote(
                text=text, start=match.start(), attributed_to=attributed, attribution=how
            )
        )
    return quotes


# ---------------------------------------------------------------------------
# Per-claim outcomes and the metrics over them
# ---------------------------------------------------------------------------

ClaimKind = Literal["citation", "quote"]


class ClaimOutcome(TypedDict):
    """One deterministic, binary, per-claim verdict.

    This is the shape WO-A09's paired comparison consumes. Two arms
    scored on the same query pair on `claim_id`, which is derived from
    the claim's content and not from its position, so it is stable across
    runs and across arms.

    Attributes:
        claim_id: `<kind>:<sha256(subject)[:16]>`. Deterministic.
        kind: `citation` or `quote`.
        subject: The canonical identifier, or the folded quotation. What
            `claim_id` digests.
        locator: Where in the report or citation list this came from.
        grounded: `True` / `False`, or `None` when the claim could not be
            decided — which removes it from every denominator rather than
            scoring it either way.
        reason: One of `CLAIM_REASONS`.
        detail: One short human-readable sentence.
    """

    claim_id: str
    kind: ClaimKind
    subject: str
    locator: str
    grounded: bool | None
    reason: str
    detail: str


def _claim_id(kind: ClaimKind, subject: str) -> str:
    """Content-derived, stable claim identity.

    Sixteen hex characters: enough that a collision inside one report is
    not a practical concern, short enough to read in a diff. The kind is
    a prefix rather than part of the digest so a row is legible without
    a lookup.
    """
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


class Metric(TypedDict):
    """A metric that cannot report a score it did not earn.

    Attributes:
        name: Stable metric name.
        value: The rate, or the count for a count metric. `None` exactly
            when `denominator` is 0 — the defect this module was written
            to stop repeating.
        numerator: What counted toward the value.
        denominator: What the value is *of*. Always published: a rate
            without one is not a measurement.
        excluded: Claims of this kind that existed but could not be
            decided, and so left the denominator. Publishing it is what
            stops the exclusion rule from quietly emptying the metric.
        reason: Why `value` is `None`, or `None` when it is not.
    """

    name: str
    value: float | None
    numerator: int
    denominator: int
    excluded: int
    reason: str | None


def _metric(
    name: str, numerator: int, denominator: int, excluded: int, empty_reason: str
) -> Metric:
    """Build a `Metric`, refusing to score an empty denominator."""
    if denominator <= 0:
        return Metric(
            name=name,
            value=None,
            numerator=numerator,
            denominator=0,
            excluded=excluded,
            reason=empty_reason,
        )
    return Metric(
        name=name,
        value=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        excluded=excluded,
        reason=None,
    )


class GroundednessResult(TypedDict):
    """Everything one report's deterministic groundedness check produced.

    `provenance` carries the run's `RunProvenance` block when the caller
    supplied one, under the same key `src/eval/provenance.py` uses, so a
    groundedness row is attributable on exactly the terms ADR 0070 set
    for every other eval row.
    """

    check: CheckIdentity
    citation_resolution_rate: Metric
    quote_verbatim_rate: Metric
    unsupported_claim_count: Metric
    exact_quote_count: int
    claims: list[ClaimOutcome]
    report_grounded: bool | None
    source_coverage: SourceCoverage
    min_quote_words: int
    provenance: RunProvenance | None


def _check_citations(
    identifiers: Sequence[CitedIdentifier], corpus: Mapping[str, PaperMetadata]
) -> list[ClaimOutcome]:
    """Resolve each cited identifier against the run's own corpus.

    Deduplicated by `(canonical-or-raw, origin)`: a paper cited five
    times is one claim about one paper, and counting it five times would
    let citation density move the score.
    """
    outcomes: list[ClaimOutcome] = []
    seen: set[tuple[str, str]] = set()
    for identifier in identifiers:
        canonical = identifier["canonical"]
        raw = identifier["raw"]
        subject = canonical if canonical is not None else raw
        key = (subject, identifier["origin"])
        if key in seen:
            continue
        seen.add(key)

        if canonical is None:
            # Not an arXiv id — but a Semantic Scholar paper the run did
            # retrieve is indexed under its raw id, so check that before
            # calling it malformed.
            if raw.strip() in corpus:
                outcomes.append(
                    ClaimOutcome(
                        claim_id=_claim_id("citation", raw.strip()),
                        kind="citation",
                        subject=raw.strip(),
                        locator=identifier["locator"],
                        grounded=True,
                        reason=CITATION_RESOLVED,
                        detail="non-arXiv identifier matching a retrieved paper",
                    )
                )
                continue
            outcomes.append(
                ClaimOutcome(
                    claim_id=_claim_id("citation", raw),
                    kind="citation",
                    subject=raw,
                    locator=identifier["locator"],
                    grounded=False,
                    reason=CITATION_MALFORMED,
                    detail=f"{raw!r} is not a well-formed arXiv identifier",
                )
            )
            continue

        if canonical in corpus:
            outcomes.append(
                ClaimOutcome(
                    claim_id=_claim_id("citation", canonical),
                    kind="citation",
                    subject=canonical,
                    locator=identifier["locator"],
                    grounded=True,
                    reason=CITATION_RESOLVED,
                    detail=f"{canonical} was retrieved by this run",
                )
            )
        else:
            outcomes.append(
                ClaimOutcome(
                    claim_id=_claim_id("citation", canonical),
                    kind="citation",
                    subject=canonical,
                    locator=identifier["locator"],
                    grounded=False,
                    reason=CITATION_NOT_RETRIEVED,
                    detail=(
                        f"{canonical} is well-formed but this run never "
                        "retrieved it"
                    ),
                )
            )
    return outcomes


def _check_one_quote(
    quote: ExtractedQuote, sources: Mapping[str, SourceText]
) -> tuple[ClaimOutcome, MatchLevel | None]:
    """Decide one quotation, and report which level matched.

    The order of the branches is the argument:

    1. No attribution → undecidable. We will not guess which paper a
       quotation came from and then fail the report for our guess.
    2. Fragments too short after elision → undecidable.
    3. Found in the attributed paper → grounded.
    4. Not found there, and that source is `full`, and found in some
       other paper's `full` source → **misattributed**: a real, specific
       defect that only a deterministic check can name.
    5. Not found anywhere, attributed source `full` → not found.
    6. Anything else → the source was `partial`, so a miss proves
       nothing. Undecidable.
    """
    subject = fold(quote["text"])
    claim_id = _claim_id("quote", subject)
    attributed = quote["attributed_to"]

    def outcome(grounded: bool | None, reason: str, detail: str) -> ClaimOutcome:
        return ClaimOutcome(
            claim_id=claim_id,
            kind="quote",
            subject=subject,
            locator=f"report@{quote['start']}",
            grounded=grounded,
            reason=reason,
            detail=detail,
        )

    if attributed is None:
        return (
            outcome(
                None,
                QUOTE_UNATTRIBUTED,
                "no citation within the attribution window",
            ),
            None,
        )

    parts = _fragments(quote["text"])
    if len(parts) > 1 and any(
        len(fold(part).split()) < MIN_FRAGMENT_WORDS for part in parts
    ):
        return (
            outcome(
                None,
                QUOTE_ELIDED_UNCHECKABLE,
                f"elided quotation with a fragment under {MIN_FRAGMENT_WORDS} words",
            ),
            None,
        )

    target = sources.get(attributed)
    if target is not None:
        level = locate_quote_in_segments(quote["text"], target["segments"])
        if level is not None:
            return (
                outcome(
                    True,
                    QUOTE_VERBATIM,
                    f"found in {attributed} ({target['origin']}, {level} match)",
                ),
                level,
            )

    attributed_is_full = target is not None and target["completeness"] == "full"
    if attributed_is_full:
        for key, source in sources.items():
            if key == attributed or source["completeness"] != "full":
                continue
            if locate_quote_in_segments(quote["text"], source["segments"]) is not None:
                return (
                    outcome(
                        False,
                        QUOTE_MISATTRIBUTED,
                        f"attributed to {attributed} but found verbatim in {key}",
                    ),
                    None,
                )
        return (
            outcome(
                False,
                QUOTE_NOT_FOUND,
                f"not present in the parsed text of {attributed}",
            ),
            None,
        )

    have = "no text at all" if target is None else f"only {target['origin']}"
    return (
        outcome(
            None,
            QUOTE_SOURCE_INCOMPLETE,
            f"cannot falsify: this run has {have} for {attributed}",
        ),
        None,
    )


def measure_groundedness(
    report: str,
    papers: Sequence[PaperMetadata],
    citations: Sequence[Citation],
    *,
    full_texts: Mapping[str, str] | None = None,
    evidence: Sequence[EvidenceClaim] | None = None,
    provenance: RunProvenance | None = None,
) -> GroundednessResult:
    """Score one report's groundedness deterministically. No model call.

    Two checks, over two surfaces each:

    - **Identifier resolution** over the arXiv ids in the report body and
      the ids the citation list asserts, resolved against
      `build_corpus_index(papers)`.
    - **Verbatim quotation** over the quoted spans in the report body,
      located in `build_source_index(...)`.

    Args:
        report: The synthesized report markdown, `state["final_report"]`.
        papers: `state["papers"]` — the papers this run actually
            retrieved. The *only* oracle for identifier resolution.
        citations: `state["citations"]`.
        full_texts: Parsed PDF text per paper, when the caller has it.
            Without it, no quote can be falsified and
            `quote_verbatim_rate` will honestly report that.
        evidence: `state["evidence"]`, when the evidence store is on.
        provenance: The run's provenance block, attached verbatim.

    Returns:
        `GroundednessResult`. Every metric carries its denominator, and
        an empty denominator is `None` with a reason.
    """
    corpus = build_corpus_index(papers)
    sources = build_source_index(papers, full_texts=full_texts, evidence=evidence)

    identifiers = [
        *extract_report_identifiers(report),
        *extract_citation_list_identifiers(citations),
    ]
    citation_claims = _check_citations(identifiers, corpus)

    quote_claims: list[ClaimOutcome] = []
    exact_quotes = 0
    for quote in extract_quotes(report, citations):
        claim, level = _check_one_quote(quote, sources)
        quote_claims.append(claim)
        if level == "exact":
            exact_quotes += 1

    resolved = sum(1 for claim in citation_claims if claim["grounded"] is True)
    citation_metric = _metric(
        "citation_resolution_rate",
        numerator=resolved,
        denominator=len(citation_claims),
        excluded=0,
        empty_reason=NO_CITATIONS,
    )

    verbatim = sum(1 for claim in quote_claims if claim["grounded"] is True)
    checkable_quotes = sum(1 for claim in quote_claims if claim["grounded"] is not None)
    quote_metric = _metric(
        "quote_verbatim_rate",
        numerator=verbatim,
        denominator=checkable_quotes,
        excluded=len(quote_claims) - checkable_quotes,
        # Two distinct emptinesses. "The report quoted nothing" and "the
        # report quoted, and we had no complete source to check against"
        # are different facts about a run, and collapsing them would hide
        # a missing PDF cache behind a clean-looking metric.
        empty_reason=NO_QUOTES if not quote_claims else NO_CHECKABLE_QUOTES,
    )

    claims = [*citation_claims, *quote_claims]
    decided = [claim for claim in claims if claim["grounded"] is not None]
    unsupported = sum(1 for claim in decided if claim["grounded"] is False)
    unsupported_metric = Metric(
        name="unsupported_claim_count",
        # A count, not a rate — but under the same rule: zero unsupported
        # claims out of zero checked is not "nothing wrong", it is
        # "nothing measured".
        value=float(unsupported) if decided else None,
        numerator=unsupported,
        denominator=len(decided),
        excluded=len(claims) - len(decided),
        reason=None if decided else NO_CHECKABLE_CLAIMS,
    )

    return GroundednessResult(
        check=check_identity(),
        citation_resolution_rate=citation_metric,
        quote_verbatim_rate=quote_metric,
        unsupported_claim_count=unsupported_metric,
        exact_quote_count=exact_quotes,
        claims=claims,
        report_grounded=(
            None if not decided else all(claim["grounded"] for claim in decided)
        ),
        source_coverage=source_coverage(sources),
        min_quote_words=MIN_QUOTE_WORDS,
        provenance=provenance,
    )


def paired_outcomes(result: GroundednessResult) -> dict[str, bool]:
    """Project a result onto `{claim_id: grounded}` for paired comparison.

    The shape WO-A09's McNemar path pairs on: two arms scored over the
    same query produce two of these, and the discordant pairs are the
    claim ids present in both with different values. Undecided claims are
    dropped rather than defaulted — a claim that could not be checked in
    one arm is not evidence about the other.

    Claim ids present in only one arm are, deliberately, not resolved
    here: whether an appearing/disappearing claim is discordant or simply
    out of scope is a statistical decision, and it belongs to the module
    that owns the test. This function's contract is only that the ids are
    stable and content-derived.
    """
    paired: dict[str, bool] = {}
    for claim in result["claims"]:
        grounded = claim["grounded"]
        if grounded is not None:
            paired[claim["claim_id"]] = grounded
    return paired
