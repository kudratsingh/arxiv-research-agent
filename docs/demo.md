# Demo — example run

The workflow's shape end-to-end: one benchmark query, the report the
system produces from it, and the per-query line the eval runner
writes to `summary.jsonl` when the query lands in the nightly
benchmark.

The query below is `hallucination-mitigation` from
[`src/eval/benchmark_queries.py`](../src/eval/benchmark_queries.py) —
the canonical smoke query for the benchmark. It's well-covered by the
built-in mock paper set (`src/agents/search.py::MOCK_PAPERS`), so
this example can be reproduced offline with `USE_MOCK_DATA=true` and
no arXiv fetch. Live-arXiv runs produce reports of the same shape
against fresher papers; the metrics on those runs live under
`outputs/eval/<run_id>/` and roll up into the nightly regression
diff.

> This document is a **canonical illustrative example** based on the
> mock paper set: the schema, the shape, and the numeric ranges are
> what a real run produces. The specific report text below is the
> workflow's actual output on the mock data.

## Query

```
What are the latest approaches to reducing hallucination in large
language models?
```

Domain: `hallucination`. Expected topics the eval scores against:
`retrieval-augmented generation`, `chain-of-verification`,
`self-consistency`, `fine-tuning for factuality`, `post-hoc
verification`. Full record:
[`src/eval/benchmark_queries.py`](../src/eval/benchmark_queries.py).

## Invocation

Offline (built-in mock papers, no external API calls beyond
Anthropic):

```bash
USE_MOCK_DATA=true python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

Fixed pipeline. To exercise the supervisor loop with the verifier and
the evidence store, layer on the flags from ADRs 0014–0016:

```bash
USE_MOCK_DATA=true \
ENABLE_SUPERVISOR=true \
ENABLE_VERIFIER=true \
ENABLE_EVIDENCE_STORE=true \
python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

## Report body

Written by the synthesizer, scored by the critic, and (with the
verifier flag on) checked against the evidence-store excerpts before
being handed to the critic. `[Author, Year]` citations are inline,
citation list follows.

```markdown
# Reducing Hallucination in Large Language Models

Hallucination — LLM output that is nonsensical or unfaithful to the
provided source — is one of the primary quality risks in deploying
generative models. Recent work groups mitigation approaches into three
temporal categories: training-time, generation-time, and post-hoc
correction methods [Ji, 2023].

## Training-time approaches

Reinforcement Learning from Human Feedback (RLHF) is the dominant
training-time technique, and recent extensions target hallucination
specifically. RLHF-V collects **fine-grained correctional feedback
targeting specific hallucinated segments**, rather than holistic
preference labels, and optimizes a dense direct-preference objective
against those annotations. On image captioning benchmarks, RLHF-V
reduces hallucination rates by 34.8% relative to the base model while
preserving helpfulness [Yu, 2024].

## Generation-time approaches

Retrieval-Augmented Generation (RAG) grounds output in retrieved
documents to reduce factual hallucination. The canonical RAG
formulation combines a parametric generator with a non-parametric
dense retriever over a corpus like Wikipedia, achieving
state-of-the-art results on open-domain QA benchmarks and reducing
factual hallucinations relative to purely parametric models
[Lewis, 2020].

Self-RAG extends this by training a single model to adaptively decide
when retrieval is necessary and reflect on its own output. The
resulting system outperforms both vanilla LLMs and fixed RAG pipelines
across six tasks including fact verification and open-domain QA,
improving factuality by 20-30% while maintaining generation fluency
[Asai, 2023].

Chain-of-Verification (CoVe) is an in-loop verification technique that
requires no external tools: the model first drafts a response, plans
verification questions, answers those questions independently, then
generates a revised response. CoVe reduces hallucination rates by
30-50% across model sizes on list-based questions, closed-book QA, and
long-form generation, with larger models benefiting more from the
self-verification process [Dhuliawala, 2023].

## Post-hoc approaches

Post-hoc verification techniques operate on generated output rather
than during generation, and include self-consistency checking,
external knowledge verification, and citation-based validation
[Ji, 2023]. These approaches tend to add latency in exchange for
higher factuality guarantees.

## Comparing the three approaches

| Approach | Training cost | Inference cost | Scope |
|---|---|---|---|
| RLHF-V | High (fine-tuning) | Low | Model-wide |
| RAG / Self-RAG | Medium (retriever training) | Medium (retrieval hop) | Per-query |
| CoVe | None | High (multi-pass) | Per-response |
| Post-hoc verification | None | High | Per-response |

Training-time methods amortize their cost across every future
inference; generation- and post-hoc-time methods pay per-response but
require no model changes. Multimodal work has largely piggy-backed on
these three categories, with fine-grained feedback (as in RLHF-V) the
most-cited recent innovation.

## Key Takeaways

- Modern mitigation strategies fall into three temporal categories,
  each with distinct cost-quality tradeoffs.
- Retrieval-based grounding (RAG, Self-RAG) is the most-deployed
  approach at inference time.
- In-loop self-verification (CoVe) achieves 30-50% hallucination
  reduction without external tools.
- Fine-grained corrective feedback (RLHF-V) outperforms holistic
  preference labels for training-time mitigation.

## Open Questions

- Direct comparison of self-verification vs. retrieval-augmentation
  under matched compute is missing from the surveyed work.
- Whether CoVe-style verification generalizes to multi-modal settings
  is not yet shown.
- Long-tail factual claims (rare entities, specialized domains)
  remain the hardest hallucination category across all approaches.
```

### Citation list

The synthesizer's `citations` field, machine-readable, gets serialized
alongside the report body:

```json
[
  {
    "paper_id": "http://arxiv.org/abs/2311.09000",
    "title": "A Survey on Hallucination in Large Language Models",
    "authors": ["Ziwei Ji", "Nayeon Lee", "Rita Frieske", "Tiezheng Yu"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2311.09000"
  },
  {
    "paper_id": "http://arxiv.org/abs/2305.13269",
    "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
    "authors": ["Patrick Lewis", "Ethan Perez", "Aleksandra Piktus"],
    "year": "2020",
    "url": "http://arxiv.org/abs/2305.13269"
  },
  {
    "paper_id": "http://arxiv.org/abs/2310.01377",
    "title": "Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection",
    "authors": ["Akari Asai", "Zeqiu Wu", "Yizhong Wang", "Avirup Sil"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2310.01377"
  },
  {
    "paper_id": "http://arxiv.org/abs/2309.11495",
    "title": "Chain-of-Verification Reduces Hallucination in Large Language Models",
    "authors": ["Shehzaad Dhuliawala", "Mojtaba Komeili", "Jing Xu"],
    "year": "2023",
    "url": "http://arxiv.org/abs/2309.11495"
  },
  {
    "paper_id": "http://arxiv.org/abs/2401.01313",
    "title": "RLHF-V: Towards Trustworthy MLLMs via Behavior Alignment from Fine-grained Correctional Human Feedback",
    "authors": ["Tianyu Yu", "Yuan Yao", "Haoye Zhang", "Taiwen He"],
    "year": "2024",
    "url": "http://arxiv.org/abs/2401.01313"
  }
]
```

## `summary.jsonl` line

One line per query, written by
[`src/eval/runner.py::_summary_line`](../src/eval/runner.py) after
scoring the report. Fields exactly match the schema in that function:

```json
{"query_id": "hallucination-mitigation", "elapsed_sec": 42.7, "error": null, "citation_accuracy": 1.00, "completeness": 0.85, "faithfulness": 0.92, "retrieval_recall": 0.80, "critic_score": 0.82, "iterations": 1, "cost_usd": 0.087, "llm_calls": 8, "loop_iterations": null, "stop_reason": null}
```

Field-by-field:

| Field | Value | Source |
|---|---|---|
| `query_id` | `hallucination-mitigation` | `benchmark_queries.py` |
| `elapsed_sec` | 42.7 | wall-clock, runner |
| `citation_accuracy` | 1.00 | regex + citation-list join (ADR 0006 background) |
| `completeness` | 0.85 | batched LLM judge over `expected_topics` (ADR 0006) |
| `faithfulness` | 0.92 | per-claim LLM judge vs. abstracts (ADR 0007) |
| `retrieval_recall` | 0.80 | LLM judge over the retrieved paper set (ADR 0013) |
| `critic_score` | 0.82 | in-workflow critic average |
| `iterations` | 1 | critic revisions used (0 = no revision, capped by `max_iterations`) |
| `cost_usd` | 0.087 | per-run cost accumulator, all Sonnet (ADR 0012) |
| `llm_calls` | 8 | planner + 5 reader (per paper) + synthesizer + critic |
| `loop_iterations` | `null` | supervisor loop was off; would be positive under `enable_supervisor` |
| `stop_reason` | `null` | see above |

At `enable_supervisor=true, enable_verifier=true,
enable_evidence_store=true`, `loop_iterations` and `stop_reason`
populate. Typical shape:

```json
{"query_id": "hallucination-mitigation", "elapsed_sec": 58.3, "error": null, "citation_accuracy": 1.00, "completeness": 0.88, "faithfulness": 0.95, "retrieval_recall": 0.80, "critic_score": 0.85, "iterations": 1, "cost_usd": 0.142, "llm_calls": 14, "loop_iterations": 9, "stop_reason": "quality_reached"}
```

Higher cost (loop tax + verifier call), slightly higher faithfulness
+ completeness, `stop_reason` bucketed for downstream analysis. Full
per-query `summary.jsonl` format documented in
[`docs/eval.md`](eval.md).

## Where the artifacts live

The eval runner writes a layered artifact per benchmark invocation:

```
outputs/eval/<run_id>/
    queries/<query_id>.json    # full per-query record (state + costs + metrics + trace)
    summary.jsonl              # machine-readable one-line-per-query rollup
    summary.md                 # human-readable table + aggregates
```

The nightly CI workflow
([`.github/workflows/eval-nightly.yml`](../.github/workflows/eval-nightly.yml))
runs the benchmark, uploads `summary.md` as the run's markdown-formatted
result, and diffs its `summary.jsonl` against the previous night's via
[`src/eval/regression_diff.py`](../src/eval/regression_diff.py).
Regressions greater than 0.10 on the LLM-judged metrics, or > 25% on
cost/iterations/llm_calls, fail the workflow. See ADRs
[0008](decisions/0008-eval-runner-sequential-per-query-isolation.md)
and [0010](decisions/0010-nightly-eval-ci.md).

## Reproducing this demo

```bash
# offline path — no arXiv fetch, no live search
USE_MOCK_DATA=true python -m src.main \
  "What are the latest approaches to reducing hallucination in large language models?"
```

The single-query runner prints the report to stdout and saves it under
`outputs/report_<timestamp>.md`. To get the metrics row instead, use
the batch runner with a filtered query set:

```bash
# metrics-scored run against the single benchmark query
python -m src.eval.runner --queries hallucination-mitigation
# writes outputs/eval/<run_id>/{queries/,summary.jsonl,summary.md}
```

The full 20-query benchmark takes ~10 minutes on the base Sonnet
configuration and costs roughly $1.50 at Sprint 1 pricing; see
[`docs/eval.md`](eval.md) for the running-cost breakdown and how
Sprint 3's Haiku routing + prompt caching change those numbers.
