"""Benchmark queries for the offline eval pipeline.

Ten diverse ML/AI research questions covering a spread of topics
(hallucination, alignment, reasoning, efficiency, safety) and shapes
(broad survey questions, tradeoff questions, comparison questions).
The eval runner (`src/eval/runner.py`, follow-up PR) will invoke the
full workflow on each query, then score the resulting report against
the query's `expected_topics` and the citation-accuracy / faithfulness
metrics in `src/eval/metrics.py`.

These queries are hand-curated, not scraped — the goal is coverage
across the kinds of research questions the system is expected to
handle in production, including a couple that stress the retrieval
pipeline (e.g. multi-hop, cross-domain).
"""

from typing import TypedDict


class BenchmarkQuery(TypedDict):
    """A single evaluation query and its expected-coverage targets."""

    query_id: str
    query: str
    domain: str
    expected_topics: list[str]
    notes: str


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
    ),
]


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
