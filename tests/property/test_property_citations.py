"""Invariants of inline-citation extraction (ADR 0069).

`measure_citation_accuracy` is the one eval metric that makes no model
call: it is a regex over a report the model wrote, and a report the
model wrote is arbitrary text. Two things follow, and both are
properties rather than examples.

First, it must never raise. It runs inside the eval loop after a paid
run has already happened, so an exception here throws away the run's
result to report on it.

Second, everything it reports has to be *in* the report. An unresolved
citation is a finding a human then goes looking for, so a metric that
can name a citation the report does not contain sends that human after
a string that never existed.
"""

from __future__ import annotations

import string
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from src.eval.metrics import (
    _cite_key_from_string,
    measure_citation_accuracy,
)
from src.graph.state import Citation

pytestmark = [pytest.mark.unit, pytest.mark.property]

#: The three inline styles the synthesizer emits, plus the year-suffix
#: form. `_normalize_first_author` exists to collapse all four onto the
#: same key, so all four belong in the strategy that tests it.
_STYLES: tuple[str, ...] = ("plain", "et al.", "two authors", "year suffix")

_NAME = st.text(alphabet=string.ascii_letters, min_size=1, max_size=12)
_YEAR = st.integers(min_value=1900, max_value=2099).map(str)

#: Report filler that cannot contain a citation: `_CITE_PATTERN`
#: requires a `[`, so text without one contributes no matches whatever
#: else it contains.
_FILLER = st.text(
    alphabet=string.ascii_letters + string.digits + " .,;:-()\n", max_size=80
)


@st.composite
def citation(draw: st.DrawFn) -> Citation:
    """One well-formed `Citation` with a single, unambiguous last name."""
    first = draw(_NAME)
    last = draw(_NAME)
    year = draw(_YEAR)
    return Citation(
        paper_id=f"https://arxiv.org/abs/{draw(_YEAR)}.00001",
        title=" ".join(draw(st.lists(_NAME, min_size=1, max_size=6))),
        authors=[f"{first} {last}"],
        year=year,
        url=f"https://arxiv.org/abs/{draw(_YEAR)}.00001",
    )


def inline_tag(last: str, year: str, style: str, other: str) -> str:
    """Render `(last, year)` in one of the four styles the synthesizer emits."""
    if style == "et al.":
        return f"[{last} et al., {year}]"
    if style == "two authors":
        return f"[{last} and {other}, {year}]"
    if style == "year suffix":
        return f"[{last}, {year}a]"
    return f"[{last}, {year}]"


def expected_key(entry: Citation) -> tuple[str, str]:
    """The `(lastname, year)` key the metric indexes `entry` under."""
    return entry["authors"][0].split()[-1].lower(), entry["year"]


@given(
    citations=st.lists(citation(), min_size=1, max_size=6),
    data=st.data(),
)
def test_a_report_that_cites_only_the_citation_list_resolves_completely(
    citations: list[Citation], data: st.DataObject
) -> None:
    """Every citation rendered in any supported style resolves to its entry.

    This is the metric's whole contract read forwards. It is stated
    over the four inline styles together because
    `_normalize_first_author` is the only thing standing between them
    and four different keys — and a report scoring 0.6 because the
    synthesizer wrote "et al." is a quality signal about the
    normalizer, reported as a quality signal about the model.
    """
    # Rendered with the last name's original casing, not the key's:
    # the index lowercases both sides, and a report that only resolved
    # when the model happened to match the metadata's capitalisation
    # would be scoring typography.
    tags = [
        inline_tag(
            entry["authors"][0].split()[-1],
            entry["year"],
            data.draw(st.sampled_from(_STYLES)),
            data.draw(_NAME),
        )
        for entry in citations
    ]
    report = " ".join(f"A grounded claim {tag}." for tag in tags)

    result = measure_citation_accuracy(report, citations)

    assert result["unresolved"] == []
    assert result["score"] == 1.0
    assert result["total_citations"] == len({expected_key(e) for e in citations})
    assert result["resolved"] == result["total_citations"]


@given(
    report=st.text(max_size=400),
    citations=st.lists(
        st.fixed_dictionaries(
            {
                "paper_id": st.text(max_size=20),
                "title": st.text(max_size=20),
                "authors": st.lists(st.text(max_size=20), max_size=3),
                "year": st.text(max_size=8),
                "url": st.text(max_size=20),
            }
        ),
        max_size=5,
    ),
)
def test_the_metric_never_raises_and_always_reports_a_consistent_tally(
    report: str, citations: list[dict[str, Any]]
) -> None:
    """Arbitrary text and a ragged citation list still produce a coherent result.

    The `Citation` fields are typed `str` but arrive from a model's
    JSON, so "a four-digit year" is a hope rather than a guarantee.
    The tally has to add up whatever they contain: a score in `[0, 1]`,
    and `resolved` plus `unresolved` accounting for every citation
    counted.
    """
    result = measure_citation_accuracy(report, [Citation(**c) for c in citations])

    assert 0.0 <= result["score"] <= 1.0
    assert result["resolved"] + len(result["unresolved"]) == result["total_citations"]
    assert result["resolved"] >= 0


@given(report=st.text(max_size=400), citations=st.lists(citation(), max_size=4))
def test_every_unresolved_citation_is_one_the_report_actually_contains(
    report: str, citations: list[Citation]
) -> None:
    """The metric only ever names citations present in the text it was given.

    The unresolved list is a to-do list for a human. A metric that can
    report a string the report does not contain sends that human
    looking for something that was never there — which is how a
    reporting bug gets diagnosed as a synthesis bug.
    """
    result = measure_citation_accuracy(report, citations)

    for entry in result["unresolved"]:
        assert entry.startswith("[") and entry.endswith("]")
        author_field, _, year = entry[1:-1].rpartition(", ")
        assert author_field in report, f"{author_field!r} is not in the report"
        assert year in report, f"{year!r} is not in the report"


@given(
    report=st.text(max_size=200),
    filler=_FILLER,
    citations=st.lists(citation(), max_size=4),
)
def test_text_carrying_no_bracket_cannot_change_the_score(
    report: str, filler: str, citations: list[Citation]
) -> None:
    """Appending citation-free prose leaves the result identical.

    `_CITE_PATTERN` requires brackets, so prose without one carries no
    citation by construction. The property is what keeps the pattern
    from being loosened into something that matches ordinary sentences
    — the failure mode of every citation regex that has ever been
    widened to "also catch this one case".
    """
    assert measure_citation_accuracy(report + filler, citations) == (
        measure_citation_accuracy(report, citations)
    )


@given(last=_NAME, year=_YEAR, other=_NAME, style=st.sampled_from(_STYLES))
def test_a_rendered_citation_key_parses_back_to_the_key_it_was_rendered_from(
    last: str, year: str, other: str, style: str
) -> None:
    """`_cite_key_from_string` inverts every style, bracketed or not.

    The judge returns cite keys as free strings and sometimes drops
    the brackets, so the parser accepts both. A round-trip is the only
    way to state that the two accepted spellings mean the same thing.
    """
    # "and"/"et" as a last name is genuinely ambiguous with the
    # two-author and et-al. separators, and the normalizer resolves
    # that ambiguity in favour of the separator. Out of scope here:
    # this property is about the styles, not about the tie-break.
    assume(last.lower() not in {"and", "et"})

    tag = inline_tag(last, year, style, other)

    assert _cite_key_from_string(tag) == (last.lower(), year)
    assert _cite_key_from_string(tag[1:-1]) == (last.lower(), year)


@given(text=st.text(max_size=120))
def test_parsing_an_arbitrary_cite_key_returns_a_key_or_nothing(text: str) -> None:
    """`_cite_key_from_string` answers with a key or `None`, never an exception.

    Its input is whatever the judge model returned. The two-branch
    shape (try as given, then try wrapped in brackets) is exactly the
    kind of code that grows a third branch and starts raising on the
    input the second one no longer handles.
    """
    key = _cite_key_from_string(text)

    if key is not None:
        lastname, year = key
        assert lastname == lastname.lower() and lastname
        assert year.isdigit() and len(year) == 4
