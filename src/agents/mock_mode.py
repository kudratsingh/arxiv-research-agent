"""Deterministic, model-free outputs for the five research agents.

`settings.use_mock_data` has always meant "serve the five fixture
papers instead of reaching arXiv" (`src/agents/search.py`, ADR 0041).
It did not mean "make no model call": planner, reader, synthesizer,
critic and verifier called `call_llm_json` under it exactly as they do
in production, so a deployment with no credential reached `POST
/research`, got a 202, and four seconds later had a `failed` job with
`error_type=upstream_model` and `llm_calls=0`. There was no path from
`docker compose up` to a briefing without a paid credential.

This module is the other half of that setting: one deterministic
generator per agent, derived from the run's own inputs, so the whole
research graph runs keyless and offline. See ADR 0080.

**Nothing here is a quality signal.** These functions do not model what
a model would say; they restate what the retrieved corpus already
contains, in the shape each agent's consumer expects. The critic's
score is a constant, the verifier's verdict is a constant, and a
briefing assembled here opens with `MOCK_BANNER` so it can never be
read as a real one.

Three properties every generator holds, and each is tested:

- **Pure.** No settings read, no I/O, no clock, no randomness. Every
  input arrives as an argument, which is also what makes the
  generators unit-testable without a graph.
- **Derived, never invented.** Analyses and evidence claims are
  verbatim spans of the paper's own abstract; citations carry the
  identifiers the run actually retrieved. Mock mode fabricates no
  source, which is the same rule ADR 0041 set for retrieval.
- **Quote-free.** The briefing contains no double-quoted span, so
  `src/eval/groundedness.py` reports `quote_verbatim_rate` as `null`
  with reason `no_quotes` rather than being handed a denominator this
  module manufactured. `src/eval/simulate_research.py`'s scripted
  synthesizer declines quotes for the same reason.

None of the five branches emits a log event of its own. `KNOWN_EVENTS`
in `src/observability/logging.py` is a closed registry owned by another
work order, and a mock run is already announced three times without it:
`search_mock_data_served` fires once per run, every node stamps
`(mock data)` on the message it appends to state, and the briefing
opens with `MOCK_BANNER`. Per-node events are a follow-up for whoever
holds that registry.
"""

from __future__ import annotations

from typing import Final

from src.graph.state import (
    Citation,
    EvidenceClaim,
    PaperAnalysis,
    PaperMetadata,
)

#: First line of every mock briefing, verbatim. The search agent has
#: announced its fixture corpus in the node message since ADR 0041; a
#: report is the artefact that outlives the run — it is exported,
#: checkpointed and pasted into other documents — so its label goes in
#: the document itself rather than only in a log line.
MOCK_BANNER: Final[str] = "Mock mode: fixture papers, no model call."

#: The critic's fixed approval score. **Not a quality measurement.**
#: The value matches the one `tests/fixtures/e2e/research_llm_responses.json`
#: and `src/eval/simulate_research.py` already can, so a mock run is
#: numerically indistinguishable from a canned one in that column —
#: which is exactly why the honesty lives in `MOCK_BANNER` and in the
#: critique text, where a reader cannot miss it, rather than in a
#: number a reader would have to know the convention to decode.
MOCK_QUALITY_SCORE: Final[float] = 0.88

#: Relevance every mock analysis reports. A constant because mock mode
#: has no relevance judgement to make: every fixture paper is served to
#: every query.
MOCK_RELEVANCE: Final[float] = 0.9

#: `EvidenceClaim.section` for a mock claim. The claim's text is a
#: verbatim span of the abstract, so `abstract` is the section it
#: actually came from — the reader's live path only ever writes a
#: chunker-assigned section here, and inventing one would misreport
#: where the verifier's substrate came from.
MOCK_EVIDENCE_SECTION: Final[str] = "abstract"

#: `EvidenceClaim.relevance_score` for a mock claim. The live value is
#: a cosine similarity from the chunk ranker; there is no ranker on
#: this path, so the field carries a constant rather than a number that
#: would read as a measurement.
MOCK_EVIDENCE_RELEVANCE: Final[float] = 0.5

#: Shortest span mock mode will promote to an evidence claim, in words.
#: Below this an abstract fragment is a clause rather than an
#: assertion. Six matches `groundedness.MIN_QUOTE_WORDS`, which draws
#: the same line for the same reason; the constant is repeated rather
#: than imported because `src/eval/` is the evaluation harness and the
#: agent layer must not depend on the thing that grades it.
MIN_CLAIM_WORDS: Final[int] = 6

#: What every mock critique says, in place of a judgement.
MOCK_CRITIQUE: Final[str] = (
    "Mock mode approval: no model judged this briefing, so this score "
    "carries no quality signal."
)

#: What the mock verifier reports in place of a faithfulness judgement.
MOCK_VERIFICATION_SUMMARY: Final[str] = (
    "verified=True (mock data): every claim in a mock briefing is a "
    "restatement of the fixture corpus, and no model judged it."
)


def mock_plan(query: str) -> tuple[list[str], list[str]]:
    """The plan for a query, with no model asked.

    Reuses ADR 0041's plan-fallback shape — the raw query as the single
    sub-question and the single search query — rather than inventing a
    decomposition. That fallback is the one plan this repository
    already accepts as honest when no model spoke, and a mock
    decomposition would be a guess about the topic dressed as an
    analysis of it. It is also visibly shallow, which is the property
    ADR 0041 wanted from the fallback in the first place.

    Args:
        query: The user's research question.

    Returns:
        `(sub_questions, search_queries)`, each a one-item list. The
        search query is unused downstream under mock mode — the search
        agent serves `MOCK_PAPERS` regardless — but it is populated so
        the state a consumer reads is the same shape as a live run's.
    """
    stated = query.strip() or "(no question was given)"
    return [stated], [stated]


def mock_analysis(paper: PaperMetadata) -> PaperAnalysis:
    """One paper's analysis, built from its own abstract.

    `key_findings` are verbatim sentences of the abstract, so the
    briefing assembled from them restates the corpus instead of
    paraphrasing it into something the corpus does not say. The other
    three text fields name what mock mode did not do, because an empty
    string there reads as "the model had nothing to say" rather than
    "no model was asked".

    Args:
        paper: The fixture paper being read.

    Returns:
        A `PaperAnalysis` in exactly the shape `_analyze_paper` builds
        on the live path.
    """
    abstract = paper.get("abstract", "") or ""
    findings = _sentences(abstract)[:3]
    return PaperAnalysis(
        paper_id=paper["id"],
        title=paper["title"],
        key_findings=findings or [_ABSENT_ABSTRACT],
        methodology=(
            "Abstract-only reading: mock mode fetches no full text and "
            "makes no model call."
        ),
        results_summary=(
            "Not extracted — mock mode restates the abstract rather than "
            "summarising results."
        ),
        limitations=(
            "Mock analysis: this text is a verbatim excerpt of the "
            "paper's abstract, not a model's reading of the paper."
        ),
        relevance=MOCK_RELEVANCE,
    )


def mock_claims(
    paper: PaperMetadata,
    *,
    sub_questions: list[str],
    max_claims: int,
) -> list[EvidenceClaim]:
    """Evidence claims for one paper, quoted verbatim from its abstract.

    The live reader refuses to build a claim without a ranked chunk to
    pin `source_text` to, precisely so nothing fabricates the text the
    verifier judges against (ADR 0016). Mock mode honours the same
    rule by a different route: the source *is* the abstract, and both
    `claim` and `source_text` are the identical verbatim span of it, so
    a consumer that checks the claim against its source finds it there.

    Args:
        paper: The fixture paper.
        sub_questions: The plan's sub-questions. The first is attributed
            to every claim, because mock mode has no attribution
            judgement to make and the field must either name a
            sub-question the planner actually asked or be empty.
        max_claims: `settings.reader_max_claims_per_paper`, passed in so
            this module reads no configuration of its own.

    Returns:
        Up to `max_claims` claims, in abstract order. Empty when the
        abstract carries no span long enough to be an assertion.
    """
    if max_claims <= 0:
        return []
    supports = next((q for q in sub_questions if q.strip()), "")
    claims: list[EvidenceClaim] = []
    for sentence in _sentences(paper.get("abstract", "") or ""):
        if len(sentence.split()) < MIN_CLAIM_WORDS:
            continue
        claims.append(
            EvidenceClaim(
                claim=sentence,
                paper_id=paper["id"],
                section=MOCK_EVIDENCE_SECTION,
                source_text=sentence,
                relevance_score=MOCK_EVIDENCE_RELEVANCE,
                supports_question=supports,
            )
        )
        if len(claims) >= max_claims:
            break
    return claims


def mock_briefing(
    *,
    query: str,
    sub_questions: list[str],
    papers: list[PaperMetadata],
    analyses: list[PaperAnalysis],
    evidence: list[EvidenceClaim],
    evidence_path: bool,
) -> tuple[str, list[Citation]]:
    """Assemble the briefing and its citation list, with no model asked.

    Two surfaces carry every identifier, because
    `src/eval/groundedness.py` checks both and a briefing that cited
    only one of them would leave half the check untested: an inline
    `arXiv:<id>` reference in the body, and a complete `citations`
    entry. Both dedupe onto the same claim id, so a five-paper corpus
    yields five claims rather than ten.

    Sections follow the plan. Papers are dealt round-robin across the
    sub-questions in retrieval order, so every retrieved paper appears
    exactly once and a sub-question the corpus cannot answer says so
    rather than being dropped from the document.

    Args:
        query: The research question, reproduced at the top.
        sub_questions: The plan. One `##` section each; a plan with no
            sub-questions falls back to a single findings section.
        papers: `state["papers"]` — the corpus the run retrieved, and
            the only thing this briefing is allowed to cite.
        analyses: `state["paper_analyses"]`, keyed back to papers by id.
        evidence: `state["evidence"]`, used only on the evidence path.
        evidence_path: Whether the reader produced claims and the
            evidence store is on. Adds the grounded excerpt under each
            paper; changes nothing about the citation surfaces, so the
            two paths score identically.

    Returns:
        `(draft_report, citations)`. The report's first line is exactly
        `MOCK_BANNER`.
    """
    analysis_by_id = {a["paper_id"]: a for a in analyses}
    evidence_by_id: dict[str, list[EvidenceClaim]] = {}
    for claim in evidence:
        evidence_by_id.setdefault(claim["paper_id"], []).append(claim)

    headings = [q.strip() for q in sub_questions if q.strip()] or ["Findings"]
    buckets: list[list[PaperMetadata]] = [[] for _ in headings]
    for index, paper in enumerate(papers):
        buckets[index % len(headings)].append(paper)

    lines = [
        MOCK_BANNER,
        "",
        "# Research briefing (mock mode)",
        "",
        f"Question: {query}",
        "",
        (
            f"This briefing was assembled from {len(papers)} fixture paper(s) "
            "without a model call. Every sentence below is a restatement of "
            "the retrieved abstracts; nothing here is a synthesis, and the "
            "quality score attached to it is a constant."
        ),
    ]

    for heading, bucket in zip(headings, buckets, strict=True):
        lines.extend(["", f"## {heading}", ""])
        if not bucket:
            lines.append(
                "No retrieved paper was assigned to this sub-question."
            )
            continue
        for paper in bucket:
            lines.extend(
                _paper_block(
                    paper,
                    analysis_by_id.get(paper["id"]),
                    evidence_by_id.get(paper["id"], []) if evidence_path else [],
                )
            )

    lines.extend(
        [
            "",
            "## Key Takeaways",
            "",
            f"- {len(papers)} paper(s) were retrieved from the built-in "
            "fixture corpus and read from their abstracts.",
            "- No model was called, so this document contains no synthesis, "
            "no comparison and no judgement.",
            "",
            "## Open Questions",
            "",
            "- Everything the question actually asks. Run with a configured "
            "ANTHROPIC_API_KEY and USE_MOCK_DATA=false for a real briefing.",
            "",
        ]
    )
    return "\n".join(lines), [_citation(paper) for paper in papers]


def mock_critique() -> tuple[str, float]:
    """The critic's fixed approval.

    Returns:
        `(critique, quality_score)`. The score is `MOCK_QUALITY_SCORE`
        and means nothing; the critique text is where that is said.
    """
    return MOCK_CRITIQUE, MOCK_QUALITY_SCORE


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

#: Stand-in finding for a paper whose abstract is empty. The fixture
#: corpus always has one, but `PaperMetadata` does not require it and a
#: `key_findings` list that is empty reads as "the paper said nothing".
_ABSENT_ABSTRACT: Final[str] = (
    "This paper carries no abstract, so mock mode has nothing to restate."
)


def _sentences(text: str) -> list[str]:
    """Split on sentence-final periods, returning verbatim substrings.

    Index-based rather than `str.split`, because every returned span
    has to be findable in the source: `source_text` is what the
    verifier and `src/eval/groundedness.py` judge against, and a
    reconstructed sentence that differs from the abstract by one
    character is exactly the fabrication this module refuses to make.
    `strip()` only removes surrounding whitespace, so a stripped slice
    is still a substring of the original.

    A period counts as a boundary only when whitespace or the end of
    the text follows it, which keeps `34.8%` and `20-30%` inside their
    sentences. Abbreviations followed by a space (`e.g. `) do split;
    the cost is a short fragment that `MIN_CLAIM_WORDS` then drops.

    Args:
        text: The paper's abstract.

    Returns:
        Non-empty sentences, in order.
    """
    spans: list[str] = []
    start = 0
    for index, char in enumerate(text):
        if char != ".":
            continue
        if index + 1 < len(text) and not text[index + 1].isspace():
            continue
        spans.append(text[start : index + 1].strip())
        start = index + 1
    spans.append(text[start:].strip())
    return [span for span in spans if span]


def arxiv_tail(paper_id: str) -> str:
    """The bare identifier from an arXiv abs URL, or the id unchanged.

    `http://arxiv.org/abs/2311.09000` -> `2311.09000`, which is the
    form `arXiv:<id>` wants in the report body.

    Args:
        paper_id: `PaperMetadata.id`.

    Returns:
        The last path segment, or the input when it has none.
    """
    tail = paper_id.rstrip("/").rsplit("/", 1)[-1]
    return tail or paper_id


def arxiv_year(paper_id: str) -> str:
    """Publication year read off an arXiv identifier's `YYMM` prefix.

    `2311.09000` -> `2023`. Empty for anything that is not a new-style
    identifier, which `_parse_citations` accepts — only `title` is
    load-bearing there.

    Args:
        paper_id: `PaperMetadata.id`.

    Returns:
        A four-digit year, or `""`.
    """
    for token in paper_id.replace("/", " ").replace(":", " ").split():
        head, _, _ = token.partition(".")
        if len(head) == 4 and head.isdigit():
            return f"20{head[:2]}"
    return ""


def _cite_key(paper: PaperMetadata) -> str:
    """The `[Lastname, Year]` tag the report's prose carries.

    Matches the tag shape `src/eval/metrics.py` and the verifier's
    dossier already key on, so a mock report is parseable by every
    citation surface a live one is.
    """
    authors = [a for a in (paper.get("authors") or []) if a.strip()]
    surname = authors[0].strip().split()[-1] if authors else "Anon"
    return f"[{surname}, {arxiv_year(paper['id'])}]"


def _paper_block(
    paper: PaperMetadata,
    analysis: PaperAnalysis | None,
    claims: list[EvidenceClaim],
) -> list[str]:
    """One paper's lines inside a section: heading, reference, excerpts.

    The two substrates are exclusive, mirroring the live synthesizer's
    two prompt paths: with evidence claims in hand the block is built
    from `source_text` — the thing the verifier judges against — and
    without them it falls back to the analysis's findings. Both are the
    same verbatim abstract spans, so printing both would repeat every
    sentence twice.
    """
    title = str(paper.get("title") or "").strip() or f"Untitled paper {paper['id']}"
    lines = [
        f"### {title}",
        "",
        (
            f"Retrieved from the fixture corpus as arXiv:{arxiv_tail(paper['id'])} "
            f"and read from its abstract alone {_cite_key(paper)}."
        ),
    ]
    if claims:
        lines.extend(
            f"- Evidence ({claim['section']}): {claim['source_text']}"
            for claim in claims
        )
    elif analysis is not None:
        lines.extend(f"- {finding}" for finding in analysis["key_findings"])
    lines.append("")
    return lines


def _citation(paper: PaperMetadata) -> Citation:
    """One citation-list entry, carrying the identifier the run retrieved."""
    paper_id = paper["id"]
    title = str(paper.get("title") or "").strip()
    return Citation(
        paper_id=paper_id,
        # `_parse_citations` drops a titleless entry, which would shrink
        # the claim set without saying so. Naming the paper by its
        # identifier keeps the entry and keeps the gap visible.
        title=title or f"Untitled paper {paper_id}",
        authors=[str(a) for a in (paper.get("authors") or [])],
        year=arxiv_year(paper_id),
        url=str(paper.get("url") or paper_id),
    )
