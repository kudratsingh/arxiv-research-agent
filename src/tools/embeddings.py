"""HuggingFace embeddings + FAISS ranking for paper relevance.

Exposes a shared `encode_texts` helper so downstream retrieval modules
(paper ranking, chunk ranking) all use the same model and normalization
convention. Model is lazy-loaded and cached at module scope.
"""

import numpy as np
from sentence_transformers import SentenceTransformer

from src.graph.state import PaperMetadata

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Lazy-load the sentence transformer model (module-level singleton)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def encode_texts(texts: list[str]) -> np.ndarray:
    """Encode texts as L2-normalized sentence embeddings.

    Normalization means the inner product between two encoded vectors
    equals their cosine similarity, so `faiss.IndexFlatIP` yields a
    cosine-similarity search.

    Args:
        texts: Strings to encode.

    Returns:
        `(n, d)` float32 ndarray of L2-normalized embeddings. Returns an
        empty `(0, 0)` array when `texts` is empty.
    """
    if not texts:
        return np.empty((0, 0), dtype=np.float32)

    model = _get_model()
    encoded = model.encode(texts, normalize_embeddings=True)
    return np.asarray(encoded, dtype=np.float32)


def rank_papers_by_relevance(
    query: str,
    papers: list[PaperMetadata],
    top_k: int = 10,
) -> list[PaperMetadata]:
    """Rank papers by cosine similarity between query and abstracts using FAISS.

    Args:
        query: The original research query.
        papers: List of paper metadata with abstracts.
        top_k: Number of top papers to return.

    Returns:
        Papers sorted by descending relevance, capped at `top_k`.
    """
    if not papers:
        return []

    if len(papers) <= top_k:
        return papers

    import faiss

    abstract_embeddings = encode_texts([p["abstract"] for p in papers])
    query_embedding = encode_texts([query])

    dimension = abstract_embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(abstract_embeddings)

    _, indices = index.search(query_embedding, min(top_k, len(papers)))

    return [papers[idx] for idx in indices[0] if idx < len(papers)]
