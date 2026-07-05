"""Search agent: queries arXiv, deduplicates, and ranks papers by relevance."""

import os
import time

from langchain_core.messages import AIMessage

from src.graph.state import PaperMetadata, ResearchState
from src.tools.arxiv_search import deduplicate_papers, search_arxiv
from src.tools.embeddings import rank_papers_by_relevance

MAX_PAPERS = 10
RESULTS_PER_QUERY = 5

# Fallback mock data used when arXiv is rate-limiting or unavailable.
# Set USE_MOCK_DATA=true to force offline mode without hitting the arXiv API.
USE_MOCK_DATA = os.environ.get("USE_MOCK_DATA", "false").lower() == "true"

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


def search_agent(state: ResearchState) -> dict:
    """Search arXiv for papers matching the planned search queries.

    Runs each search query against the arXiv API, deduplicates results
    by paper ID, then ranks by embedding similarity to the original
    research question. Caps at 10 papers. Falls back to mock data if
    arXiv is unavailable.

    Args:
        state: Current research workflow state with search_queries populated.

    Returns:
        Partial state update with papers and a message.
    """
    search_queries = state["search_queries"]
    query = state["query"]

    # Try live arXiv search first
    all_papers: list[PaperMetadata] = []
    if not USE_MOCK_DATA:
        for i, sq in enumerate(search_queries):
            if i > 0:
                time.sleep(3)
            results = search_arxiv(sq, max_results=RESULTS_PER_QUERY)
            all_papers.extend(results)

    unique_papers = deduplicate_papers(all_papers) if all_papers else []

    # Fall back to mock data if no results
    if not unique_papers:
        print("  [search] Using mock paper data (arXiv unavailable)")
        unique_papers = MOCK_PAPERS

    ranked_papers = rank_papers_by_relevance(query, unique_papers, top_k=MAX_PAPERS)

    return {
        "papers": ranked_papers,
        "messages": [
            AIMessage(
                content=(
                    f"Found {len(ranked_papers)} papers "
                    f"({'mock data' if not all_papers else 'arXiv'})."
                ),
                name="search",
            )
        ],
    }
