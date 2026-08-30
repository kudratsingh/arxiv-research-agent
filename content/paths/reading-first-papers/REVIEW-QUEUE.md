# Review queue — Reading your first papers

> **Generated file — do not edit by hand.** Regenerate with `.venv/bin/python -m src.content.review_queue --write`.
> Source of truth: `content/paths/reading-first-papers/path.json` (version 1, updated 2026-08-30).

This is the human half of the vetting pipeline (`planning/07-learning-platform/02-CONTENT.md` §3.1). Nothing on this path publishes until the reviewer named below moves it past `proposed`, and the loader refuses to serve anything that has not moved.

**Reviewer:** kudratsingh
**Owner decisions this path waits on:** `W-OD-2`, `W-OD-3`
**Path status:** `proposed`

## The hours, split by what blocks them

| Work | Items | Estimate | Blocked by |
|---|---|---|---|
| Curation review | 14 | 2.3 h | — **can start now** |
| Briefing review | 10 | 10–20 h | `W-OD-2` |
| **Total** | | **12.3–22.3 h** | |

The briefing figure is `02` §5's 1–2 review-hours per briefing carried verbatim, not re-estimated. It is the long pole, and nobody should pretend otherwise.

## 1. Curation review — available now, no spend

| # | Entry | Kind | Rationale as written |
|---|---|---|---|
| 1 | [Efficient Estimation of Word Representations in Vector Sp…](https://arxiv.org/abs/1301.3781)<br>`arxiv:1301.3781` | paper | Opens the path on the one idea everything later assumes: meaning as geometry. It is also the shortest paper here, so the first read is a win rather than an ordeal. |
| 2 | [Sequence to Sequence Learning with Neural Networks](https://arxiv.org/abs/1409.3215)<br>`arxiv:1409.3215` | paper | The encoder-decoder shape, made concrete. Its own weakness — one fixed-size vector for a whole sentence — is the problem the next entry was written to solve. |
| 3 | [Neural Machine Translation by Jointly Learning to Align a…](https://arxiv.org/abs/1409.0473)<br>`arxiv:1409.0473` | paper | Attention arrives as a fix for a named bottleneck, not as an architecture. Read here it is an answer; read after the Transformer it is a design choice, which is the wrong lesson. |
| 4 | [The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/)<br>`ext:illustrated-transformer` | external_course | The pictures most readers need before the next entry's notation lands. Offered as a warm-up, not a substitute: it explains the architecture, not the paper's argument. |
| 5 | [Attention Is All You Need](https://arxiv.org/abs/1706.03762)<br>`arxiv:1706.03762` | paper | The architecture everything after this runs on. Reached in this order it reads as 'remove the recurrence', which is one idea, rather than as eight new ideas at once. |
| 6 | [The Annotated Transformer](https://nlp.seas.harvard.edu/annotated-transformer/)<br>`ext:annotated-transformer` | external_course | The previous entry with a runnable implementation beside each equation. Pairs with it rather than following it; readers who prefer code first can start here. |
| 7 | [BERT: Pre-training of Deep Bidirectional Transformers for…](https://arxiv.org/abs/1810.04805)<br>`arxiv:1810.04805` | paper | One half of the lineage split: encoder-only, bidirectional, fine-tuned per task. Read for the pre-training objective; the benchmark tables have not aged into anything useful. |
| 8 | [Scaling Laws for Neural Language Models](https://arxiv.org/abs/2001.08361)<br>`arxiv:2001.08361` | paper | Placed before GPT-3 because GPT-3 cites it: the prediction came first and the demonstration followed. In that order GPT-3 reads as a confirmation, not a surprise. |
| 9 | [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165)<br>`arxiv:2005.14165` | paper | The other half of the lineage, and the paper that changed what people ask a model to do. Seventy-five pages: the close read is the few-shot setup, not the per-task appendices. |
| 10 | [Training Compute-Optimal Large Language Models](https://arxiv.org/abs/2203.15556)<br>`arxiv:2203.15556` | paper | The correction, read directly after the two entries it revises so the disagreement is visible on the page. This is the path's worked example of 'what superseded it'. |
| 11 | [Training language models to follow instructions with huma…](https://arxiv.org/abs/2203.02155)<br>`arxiv:2203.02155` | paper | Where a pre-trained model becomes a product: supervised fine-tuning, a reward model, then PPO. The pipeline every alignment paper since has been arguing with. |
| 12 | [Direct Preference Optimization: Your Language Model is Se…](https://arxiv.org/abs/2305.18290)<br>`arxiv:2305.18290` | paper | The current-paper slot, frozen. Closes the path by deleting the reward model the previous entry introduced — a clean, recent example of a pipeline being simplified away. |
| 13 | [Neural Networks: Zero to Hero (course repository)](https://github.com/karpathy/nn-zero-to-hero)<br>`ext:nn-zero-to-hero` | external_course | A parallel track for readers who want to build what they are reading about. Listed for the MIT-licensed notebooks; the video series stays out under the YouTube storage rule. |
| 14 | [Practical Deep Learning for Coders](https://course.fast.ai/)<br>`ext:fastai-course` | external_course | The recommended parallel track named in 02 §2.3. It teaches the practice this path deliberately skips; link-out only, which is what its licence permits. |

For each entry, confirm:

- [ ] The paper belongs on this path at all.
- [ ] Its position is right: a reader arriving from the previous entry is ready for this one.
- [ ] The rationale is true, and is a reason rather than a description.
- [ ] The vocabulary list is what a reader must already hold — not a summary of the paper's contributions.
- [ ] The time estimate is honest for someone reading this for the first time.
- [ ] The attribution names the right people.

Then edit the manifest entry: set `status` to `approved`, and set `reviewed_by` and `reviewed_at`. To reject, set `status` to `rejected` and write `rejection_reason` — `02` §3.1 keeps rejects and their reasons as a calibration set, so a rejection is an edit, not a deletion.

## 2. Briefing review — blocked

Blocked on **`W-OD-2`**. Status: `deferred-awaiting-W-OD-2`.

- Pipeline: src/graph/workflow.py, one research run per paper entry
- Ceiling: `$12.00` total, ~`$0.75` per briefing
- Command: `MAX_COST_USD=1.00 ANTHROPIC_API_KEY=<real key> .venv/bin/python -m src.api.serve  # then per paper: curl -sS -XPOST localhost:8000/research -H 'content-type: application/json' -d '{"query":"<briefing prompt for <resource_id>>","hitl_bypass":true}'`

The ceiling is enforced by the API runner between graph nodes (src/config.py max_cost_usd, ADR 0033); the CLI does not enforce it, which is why the campaign runs through POST /research and not `python -m src.main`. 10 paper entries x $1.00 ceiling + ~20% headroom for re-runs = $12.00. Not authorised: no briefing has been generated and no paid call has been made.

| # | Entry | Companion | Estimate |
|---|---|---|---|
| 1 | `arxiv:1301.3781` | not generated yet: `briefings/01-word2vec.md` | 1–2 h |
| 2 | `arxiv:1409.3215` | not generated yet: `briefings/02-seq2seq.md` | 1–2 h |
| 3 | `arxiv:1409.0473` | not generated yet: `briefings/03-bahdanau-attention.md` | 1–2 h |
| 5 | `arxiv:1706.03762` | not generated yet: `briefings/05-transformer.md` | 1–2 h |
| 7 | `arxiv:1810.04805` | not generated yet: `briefings/07-bert.md` | 1–2 h |
| 8 | `arxiv:2001.08361` | not generated yet: `briefings/08-scaling-laws.md` | 1–2 h |
| 9 | `arxiv:2005.14165` | not generated yet: `briefings/09-gpt3.md` | 1–2 h |
| 10 | `arxiv:2203.15556` | not generated yet: `briefings/10-chinchilla.md` | 1–2 h |
| 11 | `arxiv:2203.02155` | not generated yet: `briefings/11-instructgpt.md` | 1–2 h |
| 12 | `arxiv:2305.18290` | not generated yet: `briefings/12-dpo.md` | 1–2 h |

For each briefing, confirm:

- [ ] Every factual claim about the paper is correct.
- [ ] The 'read closely vs skim' guidance matches the paper's actual sections.
- [ ] The 'what superseded it' section is dated and is not overstated.
- [ ] Nothing is quoted that should be paraphrased, and every quote is attributed.
- [ ] The prose is worth a reader's time — this is the differentiator, and a mediocre briefing is worse than no path.

Then set `reviewed_by` / `reviewed_at` in **both** the manifest entry and the briefing file's provenance header, and move the entry to `approved`. The loader refuses to start if the two disagree.

## What you do not have to check

`src/content/schema.py` refuses to load a manifest that breaks any of these, so a loading path has already passed them:

- `L1_ARXIV_ABS_ONLY`
- `L2_NO_FILE_URLS`
- `L3_NO_REHOSTING_FIELDS`
- `L4_ABSTRACT_ATTRIBUTED`
- `L5_S2_LINKS_BACK`
- `L6_ID_MATCHES_URL`
- `L7_NO_YOUTUBE`
- `L8_NONCOMMERCIAL`
- `L9_QUOTES_ATTRIBUTED`
- `S1_REVIEW_REQUIRED`
- `S2_BRIEFING_REQUIRED`
- `S3_PATH_PUBLISH_GATE`
- `S4_POSITIONS_CONTIGUOUS`
- `S5_UNIQUE_RESOURCE_IDS`
- `S6_GENERATED_NEEDS_RUN`
- `S7_FIXTURE_BANNER`
- `S8_RATIONALE_PRESENT`

In particular: every paper link is an arXiv abs page, no field exists that could hold full text or a PDF, abstracts cannot be stored without attribution, citation-ancestry claims carry a Semantic Scholar link-back, and nothing unreviewed can reach `approved`. Spend the review hours on judgement, not on re-checking the machine.

