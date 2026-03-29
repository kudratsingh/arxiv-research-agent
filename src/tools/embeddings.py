"""HuggingFace embeddings + FAISS ranking for paper relevance."""

import numpy as np
from sentence_transformers import SentenceTransformer

from src.graph.state import PaperMetadata

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence transformer model."""
    global _model
    if _model is None:
        _model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    return _model


def rank_papers_by_relevance(
    query: str,
    papers: list[PaperMetadata],
    top_k: int = 10,
) -> list[PaperMetadata]:
    """Rank papers by embedding similarity between query and abstracts using FAISS.

    Args:
        query: The original research query.
        papers: List of paper metadata with abstracts.
        top_k: Number of top papers to return.

    Returns:
        Papers sorted by descending relevance, capped at top_k.
    """
    if not papers:
        return []

    if len(papers) <= top_k:
        return papers

    import faiss

    model = _get_model()

    abstracts = [p["abstract"] for p in papers]
    abstract_embeddings = model.encode(abstracts, normalize_embeddings=True)
    query_embedding = model.encode([query], normalize_embeddings=True)

    dimension = abstract_embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(np.array(abstract_embeddings, dtype=np.float32))

    scores, indices = index.search(
        np.array(query_embedding, dtype=np.float32), min(top_k, len(papers))
    )

    ranked: list[PaperMetadata] = []
    for idx in indices[0]:
        if idx < len(papers):
            ranked.append(papers[idx])

    return ranked
