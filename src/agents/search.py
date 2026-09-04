"""Search agent: queries arXiv, deduplicates, and ranks papers by relevance.

When `settings.enable_semantic_scholar` is on, the search agent also
fetches one-hop references from Semantic Scholar for the top-K arXiv
seed papers and unions them into the candidate pool before the final
relevance ranking. Sprint 1 baseline is preserved byte-identical when
the flag is off. See ADR 0023.

Retrieval honesty (ADR 0041): the built-in `MOCK_PAPERS` demo fixture
is reachable *only* under `settings.use_mock_data`. A live search that
finds nothing raises a typed error instead — `NoPapersFoundError` when
arXiv answered with zero hits, `ArxivUnavailableError` when every
query failed at the transport level — so the job fails with an honest
`error_type` rather than delivering a fluent briefing built on five
hardcoded off-topic papers.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage

from src.config import settings
from src.errors import NoPapersFound
from src.graph.state import PaperMetadata, ResearchState
from src.observability import get_logger
from src.observability.semconv import TOOL_ARXIV_SEARCH, TOOL_TYPE_EXTENSION
from src.observability.tracing import tool_span
from src.resilience import interruptible_sleep
from src.tools.arxiv_search import (
    ArxivUnavailableError,
    deduplicate_papers,
    search_arxiv,
)
from src.tools.embeddings import rank_papers_by_relevance
from src.tools.semantic_scholar import (
    _arxiv_url_to_s2_id,
    get_references,
)

log = get_logger(__name__)

# Defense-in-depth cap on live arXiv queries per run. The planner's
# schema bounds the plan size, but a HITL-edited plan arrives from
# outside that schema — without a cap here, an oversized edited plan
# drives unbounded arXiv traffic (3s pacing x N queries) from a single
# job (ADR 0041).
MAX_SEARCH_QUERIES_PER_RUN = 12


class NoPapersFoundError(NoPapersFound):
    """A live arXiv search completed but matched zero papers.

    Raised only when arXiv actually answered — a transport-level
    failure raises `ArxivUnavailableError` instead, so the job's
    `error_type` (ADR 0064: the code `not_found_papers`, not this
    class's name) names the real cause. Never raised under
    `settings.use_mock_data`,
    and never raised when the state already carries papers from an
    earlier search (a supervisor-loop re-search that finds nothing
    keeps the prior result set instead of destroying it).
    """

# Offline demo fixture. Served ONLY under `settings.use_mock_data`
# (ADR 0041) — never as a fallback for a live search, where these five
# hallucination/RAG papers would masquerade as real retrieval results
# for whatever the user actually asked about.
MOCK_PAPERS: list[PaperMetadata] = [
    PaperMetadata(
        id="http://arxiv.org/abs/2311.09000",
        title="A Survey on Hallucination in Large Language Models",
        authors=["Ziwei Ji", "Nayeon Lee", "Rita Frieske", "Tiezheng Yu"],
        abstract="Large language models (LLMs) are prone to generate content that is nonsensical or unfaithful to the provided source. This phenomenon, termed hallucination, poses significant challenges. This survey provides a broad overview of recent advances in detecting and mitigating hallucinations in LLMs, categorizing approaches into training-time, generation-time, and post-hoc correction methods. Training-time methods include RLHF and factuality-aware fine-tuning. Generation-time methods include retrieval-augmented generation (RAG), constrained decoding, and chain-of-thought prompting. Post-hoc methods include self-consistency checking, external knowledge verification, and citation-based validation.",
        url="http://arxiv.org/abs/2311.09000",
        pdf_url="http://arxiv.org/pdf/2311.09000",
    ),
    PaperMetadata(
        id="http://arxiv.org/abs/2305.13269",
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        authors=["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus"],
        abstract="We explore retrieval-augmented generation (RAG) as a method to reduce hallucination in large language models by grounding outputs in retrieved documents. Our approach combines a pre-trained parametric model with a non-parametric retrieval component that accesses a dense vector index of Wikipedia. RAG models achieve state-of-the-art results on open-domain QA benchmarks while significantly reducing factual hallucinations compared to purely parametric models. We show that the retrieval component provides a form of implicit fact-checking during generation.",
        url="http://arxiv.org/abs/2305.13269",
        pdf_url="http://arxiv.org/pdf/2305.13269",
    ),
    PaperMetadata(
        id="http://arxiv.org/abs/2310.01377",
        title="Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
        authors=["Akari Asai", "Zeqiu Wu", "Yizhong Wang", "Avirup Sil"],
        abstract="We introduce Self-RAG, a framework that trains a single LLM to adaptively retrieve passages on-demand, generate text informed by retrieved passages, and reflect on its own output using special reflection tokens. Unlike conventional RAG, Self-RAG learns when retrieval is necessary and can self-evaluate the relevance and support of generated content. On six tasks including fact verification and open-domain QA, Self-RAG significantly outperforms both vanilla LLMs and fixed RAG pipelines, improving factuality by 20-30% while maintaining generation fluency.",
        url="http://arxiv.org/abs/2310.01377",
        pdf_url="http://arxiv.org/pdf/2310.01377",
    ),
    PaperMetadata(
        id="http://arxiv.org/abs/2309.11495",
        title="Chain-of-Verification Reduces Hallucination in Large Language Models",
        authors=["Shehzaad Dhuliawala", "Mojtaba Komeili", "Jing Xu"],
        abstract="We present Chain-of-Verification (CoVe), a method to reduce hallucinations by having the model first draft a response, then plan verification questions, answer those questions independently, and generate a revised response. CoVe leverages the model's own capabilities for self-verification without external tools. Experiments on tasks including list-based questions, closed-book QA, and long-form generation show CoVe reduces hallucination rates by 30-50% across model sizes, with larger models benefiting more from the self-verification process.",
        url="http://arxiv.org/abs/2309.11495",
        pdf_url="http://arxiv.org/pdf/2309.11495",
    ),
    PaperMetadata(
        id="http://arxiv.org/abs/2401.01313",
        title="RLHF-V: Towards Trustworthy MLLMs via Behavior Alignment from Fine-grained Correctional Human Feedback",
        authors=["Tianyu Yu", "Yuan Yao", "Haoye Zhang", "Taiwen He"],
        abstract="We present RLHF-V, a framework to align multimodal large language models (MLLMs) with human preferences to reduce hallucination. Unlike prior RLHF methods that use holistic preference labels, RLHF-V collects fine-grained correctional feedback targeting specific hallucinated segments. We introduce a dense direct preference optimization objective that learns from segment-level annotations. RLHF-V reduces hallucination rates in image captioning by 34.8% relative to the base model while preserving helpfulness, significantly outperforming standard RLHF approaches.",
        url="http://arxiv.org/abs/2401.01313",
        pdf_url="http://arxiv.org/pdf/2401.01313",
    ),
]


def _enrich_with_s2_references(
    query: str, seed_papers: list[PaperMetadata]
) -> list[PaperMetadata]:
    """Fetch one-hop references from Semantic Scholar for the top-K seeds.

    The seeds are pre-ranked by embedding similarity to the query, so
    we walk the highest-relevance arXiv papers and pull their cited
    references. Skips seeds that lack an arXiv ID (S2 needs an
    external ID form to look up references reliably). Silent on
    per-seed failures — enrichment is best-effort and must never
    derail the workflow.

    Returned papers are `PaperMetadata` mapped by the S2 adapter, so
    they dedupe against arXiv results by paper ID (arXiv URL wins
    whenever the reference has an arXiv external ID).
    """
    seed_count = settings.semantic_scholar_seed_count
    refs_per_seed = settings.semantic_scholar_refs_per_seed
    if seed_count <= 0 or refs_per_seed <= 0:
        return []

    pre_ranked = rank_papers_by_relevance(query, seed_papers, top_k=seed_count)
    references: list[PaperMetadata] = []
    for seed in pre_ranked:
        s2_id = _arxiv_url_to_s2_id(seed["id"])
        # Skip non-arXiv, non-S2 ids to avoid guessing at S2 lookup format.
        if not (s2_id.startswith("ARXIV:") or s2_id and not s2_id.startswith("http")):
            continue
        fetched = get_references(s2_id, limit=refs_per_seed)
        references.extend(fetched)
    return references


def search_agent(state: ResearchState) -> dict[str, Any]:
    """Search arXiv for papers matching the planned search queries.

    Runs each search query against the arXiv API, deduplicates results
    by canonical paper ID, optionally enriches via Semantic Scholar's
    citation graph (ADR 0023), then ranks by embedding similarity to
    the original research question. Caps at `settings.max_papers`.

    The `MOCK_PAPERS` demo fixture is served only under
    `settings.use_mock_data` — a live search never silently substitutes
    fabricated sources (ADR 0041).

    Args:
        state: Current research workflow state with search_queries populated.

    Returns:
        Partial state update with papers and a message.

    Raises:
        NoPapersFoundError: Live search answered with zero hits and the
            state carries no papers from an earlier search round.
        ArxivUnavailableError: Every live query failed at the transport
            level (outage / rate limit) and the state carries no papers
            from an earlier search round.
    """
    search_queries = state["search_queries"]
    query = state["query"]

    if settings.use_mock_data:
        log.info(
            "search_mock_data_served",
            extra={"n_papers": len(MOCK_PAPERS)},
        )
        ranked_mock = rank_papers_by_relevance(
            query, MOCK_PAPERS, top_k=settings.max_papers
        )
        return {
            "papers": ranked_mock,
            "messages": [
                AIMessage(
                    content=f"Found {len(ranked_mock)} papers (mock data).",
                    name="search",
                )
            ],
        }

    if len(search_queries) > MAX_SEARCH_QUERIES_PER_RUN:
        log.warning(
            "search_query_cap_applied",
            extra={
                "requested": len(search_queries),
                "cap": MAX_SEARCH_QUERIES_PER_RUN,
            },
        )
        search_queries = search_queries[:MAX_SEARCH_QUERIES_PER_RUN]

    all_papers: list[PaperMetadata] = []
    failed_queries = 0
    for i, sq in enumerate(search_queries):
        if i > 0:
            # Pacing, but cancellable. `time.sleep(3)` here held a node
            # thread for three seconds per query regardless of the
            # job's state, so a cancelled run with a twelve-query plan
            # could spend its entire 30s drain window asleep between
            # queries it was never going to issue (ADR 0068).
            interruptible_sleep(settings.arxiv_pacing_sec)
        try:
            # The `execute_tool` span is opened here rather than inside
            # `search_arxiv` only because `src/tools/arxiv_search.py`
            # belongs to a peer work order this wave; the other three
            # tools carry the decorator on the function itself. ADR 0066
            # records the fold-in.
            with tool_span(TOOL_ARXIV_SEARCH, tool_type=TOOL_TYPE_EXTENSION):
                results = search_arxiv(
                    sq,
                    max_results=settings.results_per_query,
                    raise_on_unavailable=True,
                )
        except ArxivUnavailableError:
            # Logged at WARNING inside search_arxiv; keep going — the
            # remaining queries may still succeed and a partial result
            # set beats no result set.
            failed_queries += 1
            continue
        all_papers.extend(results)

    unique_papers = deduplicate_papers(all_papers) if all_papers else []

    if not unique_papers:
        # A supervisor-loop re-search that comes up empty must not
        # destroy a result set an earlier round already paid for.
        prior_papers = state.get("papers") or []
        if prior_papers:
            log.warning(
                "search_empty_keeping_prior_papers",
                extra={
                    "n_prior": len(prior_papers),
                    "failed_queries": failed_queries,
                    "n_queries": len(search_queries),
                },
            )
            return {
                "papers": prior_papers,
                "messages": [
                    AIMessage(
                        content=(
                            f"Search returned no new papers; keeping "
                            f"{len(prior_papers)} papers from the "
                            f"previous round."
                        ),
                        name="search",
                    )
                ],
            }
        if search_queries and failed_queries == len(search_queries):
            raise ArxivUnavailableError(
                f"arXiv search failed for all {failed_queries} queries "
                f"(outage or rate limit) — no papers retrieved"
            )
        raise NoPapersFoundError(
            f"arXiv returned zero papers across "
            f"{len(search_queries)} search queries"
        )

    if failed_queries:
        log.warning(
            "search_partial_arxiv_failure",
            extra={
                "failed_queries": failed_queries,
                "n_queries": len(search_queries),
                "n_papers": len(unique_papers),
            },
        )

    s2_reference_count = 0
    if settings.enable_semantic_scholar:
        s2_papers = _enrich_with_s2_references(query, unique_papers)
        s2_reference_count = len(s2_papers)
        # `deduplicate_papers` keys off the canonical paper ID; arXiv
        # seeds collide with S2 references that carry an arXiv external
        # ID (version- and scheme-insensitively), so the union is
        # naturally deduped.
        unique_papers = deduplicate_papers(unique_papers + s2_papers)

    ranked_papers = rank_papers_by_relevance(
        query, unique_papers, top_k=settings.max_papers
    )

    if s2_reference_count:
        source_label = f"arXiv + {s2_reference_count} S2 references"
    else:
        source_label = "arXiv"

    return {
        "papers": ranked_papers,
        "messages": [
            AIMessage(
                content=f"Found {len(ranked_papers)} papers ({source_label}).",
                name="search",
            )
        ],
    }
