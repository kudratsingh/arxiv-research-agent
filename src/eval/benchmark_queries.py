"""Benchmark queries for the offline eval pipeline.

Twenty diverse ML/AI research questions covering a spread of topics
(hallucination, alignment, reasoning, efficiency, safety) and shapes
(broad survey questions, tradeoff questions, comparison questions).
`src/eval/runner.py` invokes the full workflow on each query, then scores
the resulting report against the query's `expected_topics` and the
citation-accuracy / faithfulness metrics in `src/eval/metrics.py`.

These queries are hand-curated, not scraped — the goal is coverage
across the kinds of research questions the system is expected to
handle in production, including a couple that stress the retrieval
pipeline (e.g. multi-hop, cross-domain).

**Dataset provenance (ADR 0070).** Every query names its author, its
creation date, its licence and its notes, because a benchmark whose
origin nobody recorded cannot support a claim about the system it
scores — NIST AI RMF MEASURE 2.1 asks for exactly this, and the
contamination note on `hallucination-mitigation` is the reason it
matters here rather than in the abstract: that query is *known* to be
covered by the built-in mock papers, so retrieval recall on it is scored
against papers hand-picked to match. That note has to survive every edit
to this file.

The dataset's version is not a constant somebody has to remember to
bump. `RESEARCH_DATASET_VERSION` is a fingerprint of the list's own
contents, so it moves the instant a query, a topic list or a provenance
field changes, and two campaigns can be joined on it.
"""

from typing import Final, TypedDict

from src.eval.provenance import dataset_fingerprint

#: Name this dataset is fingerprinted under, in every summary row.
DATASET_NAME: Final[str] = "research-benchmark"

#: Who hand-wrote these queries. One person, named rather than
#: euphemised: "the maintainers" is not a provenance record.
DATASET_AUTHOR: Final[str] = "Kudrat Singh"

#: SPDX-style licence token for the query text. This repository ships no
#: `LICENSE` file, so the queries carry no grant — `UNLICENSED` is the
#: honest value, not a placeholder to be filled in later by whoever
#: notices. It changes when the repository's licensing is settled, which
#: is an owner decision recorded as an open item rather than a code one.
DATASET_LICENSE: Final[str] = "UNLICENSED"


class BenchmarkQuery(TypedDict):
    """A single evaluation query, its coverage targets and its origin.

    Attributes:
        query_id: Stable kebab-case slug; the record's filename.
        query: The research question, verbatim.
        domain: Coarse topic bucket, used by `get_queries`.
        expected_topics: What a complete answer must cover. Also the
            denominator of `completeness` and `retrieval_recall`, which
            is why the list length is a scoring decision, not a label.
        notes: Free text about what the query is *for*, including any
            known contamination.
        author: Who wrote the query.
        created: ISO-8601 date the query entered the benchmark.
        license: Licence the query text is offered under.
    """

    query_id: str
    query: str
    domain: str
    expected_topics: list[str]
    notes: str
    author: str
    created: str
    license: str


BENCHMARK_QUERIES: list[BenchmarkQuery] = [
    BenchmarkQuery(
        query_id="hallucination-mitigation",
        query="What are the latest approaches to reducing hallucination in large language models?",
        domain="hallucination",
        expected_topics=[
            "retrieval-augmented generation",
            "chain-of-verification",
            "self-consistency",
            "fine-tuning for factuality",
            "post-hoc verification",
        ],
        notes="Well-covered by the built-in mock papers; good smoke query.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="rag-multi-hop",
        query="How do retrieval-augmented generation systems handle multi-hop questions?",
        domain="retrieval",
        expected_topics=[
            "iterative retrieval",
            "query decomposition",
            "graph-based retrieval",
            "self-ask / self-RAG",
        ],
        notes="Tests whether the planner decomposes into method + evaluation sub-questions.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="alignment-beyond-rlhf",
        query="What methods exist for aligning LLMs with human preferences beyond RLHF?",
        domain="alignment",
        expected_topics=[
            "direct preference optimization",
            "constitutional AI",
            "reward modeling alternatives",
            "process supervision",
        ],
        notes="Broad question; report should compare methods and note tradeoffs.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="cot-reasoning-effects",
        query="How does chain-of-thought prompting affect model reasoning ability across model scales?",
        domain="reasoning",
        expected_topics=[
            "emergence at scale",
            "arithmetic and symbolic tasks",
            "self-consistency decoding",
            "faithfulness of intermediate steps",
        ],
        notes="Report should distinguish empirical findings from theoretical claims.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="lora-vs-full-finetune",
        query="What are the tradeoffs between LoRA and full fine-tuning for domain adaptation?",
        domain="fine-tuning",
        expected_topics=[
            "parameter efficiency",
            "quality gap on benchmarks",
            "compute and memory cost",
            "catastrophic forgetting",
        ],
        notes="Direct comparison question; synthesizer should produce a table-like structure.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="vlm-spatial-reasoning",
        query="How do modern vision-language models handle spatial reasoning?",
        domain="multimodal",
        expected_topics=[
            "grounding and bounding boxes",
            "compositional benchmarks",
            "chain-of-thought over images",
            "known failure modes on relations",
        ],
        notes="Cross-domain; may surface papers outside pure NLP.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="long-context-efficiency",
        query="What are the current techniques for efficient long-context inference in transformers?",
        domain="efficiency",
        expected_topics=[
            "KV cache compression",
            "attention approximations",
            "position encoding for length extrapolation",
            "sparse and sliding-window attention",
        ],
        notes="Technical; tests whether reader extracts algorithmic detail from methods sections.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="reasoning-benchmarks",
        query="What evaluation benchmarks best capture reasoning ability in large language models?",
        domain="evaluation",
        expected_topics=[
            "GSM8K and math benchmarks",
            "BIG-Bench Hard",
            "adversarial and contamination-resistant benchmarks",
            "process-based evaluation",
        ],
        notes="Meta-question about evaluation; synthesizer should address benchmark validity.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="moe-vs-dense",
        query="How do mixture-of-experts models compare to dense models at similar compute budgets?",
        domain="architecture",
        expected_topics=[
            "training compute efficiency",
            "inference cost and serving",
            "quality on downstream benchmarks",
            "routing failure modes",
        ],
        notes="Comparison; report should distinguish training-time vs inference-time tradeoffs.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="coding-agent-safety",
        query="What safety evaluations exist for autonomous coding agents?",
        domain="safety",
        expected_topics=[
            "sandbox and permissions",
            "prompt injection resistance",
            "capability elicitation benchmarks",
            "human-in-the-loop protocols",
        ],
        notes="Newer topic; tests search coverage of recent (2024+) work.",
        author=DATASET_AUTHOR,
        created="2026-07-05",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="tool-use-agents",
        query="How do modern LLM agents plan and execute tool-use across multi-step tasks?",
        domain="agents",
        expected_topics=[
            "ReAct-style planning",
            "tool selection and routing",
            "error recovery from tool failures",
            "trajectory-level evaluation",
        ],
        notes="Overlaps with agents / planning; report should distinguish "
              "single-tool vs multi-tool composition.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="synthetic-data-training",
        query="What role does synthetic data play in training frontier language models?",
        domain="training",
        expected_topics=[
            "self-distillation and self-play",
            "instruction generation pipelines",
            "quality filtering and dedup",
            "collapse and mode failure modes",
        ],
        notes="Meta-topic; expects coverage of both quality wins and pathologies.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="quantization-inference",
        query="How do modern low-bit quantization methods trade off inference cost and quality?",
        domain="efficiency",
        expected_topics=[
            "int4 / int8 post-training quantization",
            "activation-aware weight quantization",
            "kv-cache quantization",
            "quality degradation on reasoning tasks",
        ],
        notes="Technical; second efficiency query — pairs with long-context-efficiency for coverage.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="in-context-learning-mechanisms",
        query="What mechanisms explain in-context learning in transformer language models?",
        domain="theory",
        expected_topics=[
            "induction heads and pattern completion",
            "implicit gradient descent hypothesis",
            "task vectors and skill localization",
            "scaling and emergence claims",
        ],
        notes="Theoretical; report should note where evidence is mechanistic vs correlational.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="scaling-laws",
        query="How have empirical scaling laws for language models evolved beyond the original Chinchilla results?",
        domain="scaling",
        expected_topics=[
            "Chinchilla-optimal compute allocation",
            "downstream-loss vs pretraining-loss decoupling",
            "post-training / RLHF scaling",
            "data quality vs quantity tradeoffs",
        ],
        notes="Historical + current; expects comparison of scaling regimes.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="jailbreak-robustness",
        query="What defenses against LLM jailbreaks have proven robust in recent evaluations?",
        domain="safety",
        expected_topics=[
            "adversarial suffix defenses",
            "constitutional prompting",
            "circuit-level interventions",
            "evaluation methodology and reproducibility",
        ],
        notes="Adversarial; second safety query focused on robustness rather than agent-specific risks.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="reasoning-fine-tuning",
        query="How do post-training methods like RLVR and STaR improve LLM reasoning?",
        domain="reasoning",
        expected_topics=[
            "reinforcement learning with verifiable rewards",
            "self-taught reasoner (STaR)",
            "process reward models",
            "compute allocation between pretraining and post-training",
        ],
        notes="Method-comparison; complements cot-reasoning-effects with post-training angle.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="speculative-decoding",
        query="How do speculative decoding methods reduce LLM serving latency?",
        domain="efficiency",
        expected_topics=[
            "draft model + verifier architectures",
            "self-speculation techniques",
            "tree-based / lookahead speculation",
            "practical serving throughput gains",
        ],
        notes="Serving-time optimization; complements quantization + long-context queries.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="interpretability-methods",
        query="What interpretability methods are used to understand LLM internal computations?",
        domain="interpretability",
        expected_topics=[
            "sparse autoencoders",
            "activation patching / causal tracing",
            "probing and linear representations",
            "known limitations of current methods",
        ],
        notes="Broad interp survey; expects methodology grouping.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
    BenchmarkQuery(
        query_id="agentic-memory-architectures",
        query="What memory architectures have been proposed for long-horizon LLM agents?",
        domain="agents",
        expected_topics=[
            "episodic vs semantic memory stores",
            "retrieval-based memory (MemGPT style)",
            "summarization / distillation for context compression",
            "eval methodology on long-horizon tasks",
        ],
        notes="Second agents query; complements tool-use-agents with a memory-architecture focus.",
        author=DATASET_AUTHOR,
        created="2026-07-07",
        license=DATASET_LICENSE,
    ),
]


#: Content-derived version of the query set, recorded on every research
#: summary row. Computed at import rather than declared, so it cannot
#: drift from the list above: edit a query and the fingerprint moves, and
#: a regression diff can see that the benchmark changed rather than the
#: system (ADR 0070). Cheap — one SHA-256 over ~10 KB, once per process.
RESEARCH_DATASET_VERSION: Final[str] = dataset_fingerprint(
    DATASET_NAME, BENCHMARK_QUERIES
)


def get_queries(domain: str | None = None) -> list[BenchmarkQuery]:
    """Return benchmark queries, optionally filtered by domain.

    Args:
        domain: If provided, return only queries whose `domain` matches.
            Case-insensitive. `None` returns all queries.

    Returns:
        Filtered list of `BenchmarkQuery` items. Empty when no query matches.
    """
    if domain is None:
        return list(BENCHMARK_QUERIES)
    target = domain.lower()
    return [q for q in BENCHMARK_QUERIES if q["domain"].lower() == target]
