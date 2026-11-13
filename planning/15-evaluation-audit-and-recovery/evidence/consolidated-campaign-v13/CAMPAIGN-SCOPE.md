# Frozen campaign scope and answerability

All inputs are retained public snapshots. The corpus is exposed; these are not fresh independent held-out cases. Human judgments are blank. Reference answerability is machine-authored and never included in the checker payload.

| Order | Case | Cohort | Selected units |
|---|---|---|---|
| 1 | campaign-dev-learn | development | 1 |
| 2 | campaign-dev-compare | development | 2 |
| 3 | campaign-eval-learn-mechanism | evaluation_exposed_corpus | 1 |
| 4 | campaign-eval-learn-conditions | evaluation_exposed_corpus | 1 |
| 5 | campaign-eval-learn-experiment | evaluation_exposed_corpus | 1 |
| 6 | campaign-eval-learn-measurement | evaluation_exposed_corpus | 1 |
| 7 | campaign-eval-research-memory | evaluation_exposed_corpus | 2 |
| 8 | campaign-eval-research-retrieval | evaluation_exposed_corpus | 2 |
| 9 | campaign-eval-research-verification | evaluation_exposed_corpus | 2 |
| 10 | campaign-eval-research-insufficient | evaluation_exposed_corpus | 2 |
| 11 | campaign-probe-1 | machine_reference_checker_diagnostic | 3 |
| 12 | campaign-probe-2 | machine_reference_checker_diagnostic | 3 |
| 13 | campaign-probe-3 | machine_reference_checker_diagnostic | 3 |
| 14 | campaign-probe-4 | machine_reference_checker_diagnostic | 3 |

Twenty checker records are10 supported /10 unsupported proposed machine controls, organised as10 matched pairs on6 distinct passages. Claims and evidence repeat. Conditional error rates expose decisive, abstaining and missing denominators; this is not a checker certification.

Answerability matrix: `fdf88e73d7a5691a9cc503f89cdd82dadb868b82344f416afb7032c3a485a8a5`. Scoring policy: `workspace-campaign-scoring-v13`.

## Exact requested parts and reference criteria

### campaign-eval-learn-mechanism

What sequence of operations does the selected source describe? Separate established steps from prerequisites unavailable in the retained text.

**p1 — partially_answerable / bounded_partial_answer**

What sequence of operations does the selected source describe? Separate established steps from prerequisites unavailable in the retained text.

Retained support: The AWM abstract describes hypothetical action, read-only environment queries, evidence-based reasoning and executable observation construction without changing the real environment.

Missing: No full implementation, query protocol or prerequisite specification is retained.

Limitation origins: available_text, extraction.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: The AWM abstract describes hypothetical action, read-only environment queries, evidence-based reasoning and executable observation construction without changing the real environment.

Missing: No full implementation, query protocol or prerequisite specification is retained.

Limitation origins: available_text, extraction.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: No full implementation, query protocol or prerequisite specification is retained.

Limitation origins: available_text, extraction.

Selected exact passages:

- `u0309644ac6e9b03471f1` · `arxiv:2610.40927` · `arxiv:2610.40927:v1:metadata-b09108e19893972e` · abstract · Unicode 0–1532 · parser `workspace-plain-text-v1`.

> Test-time scaling (TTS) improves large language model agents by sampling and selecting among multiple candidate trajectories, but common realizations assume that these trajectories can be executed in parallel. This assumption breaks in realistic deployments, where enterprise workspaces and cloud services are shared and persistent, costly or infeasible to replicate, and actions may introduce irreversible side effects or cross-trajectory interference. Existing generative world models avoid direct execution, but typically compress environment state into a single prompt, limiting their ability to reliably simulate transitions under partial observability. Instead, we introduce Agentic World Modeling (AWM), which reformulates next-observation prediction as a multi-turn evidence-acquisition task. For each hypothetical action, an agentic simulator adaptively queries the real environment through safe read-only interfaces, reasons over the returned evidence, and uses executable computation to construct the resulting observation without mutating shared state. Integrated with trajectory-level TTS, AWM enables parallel exploration over a single shared environment. Across $\tau$-bench, AppWorld, and OfficeBench, AWM outperforms a single-shot simulation baseline by 40.07% on average, and surpasses a trained world-model baseline by 12.36% on average. These results establish interactive, read-grounded simulation as a practical foundation for safe and scalable agentic test-time scaling in shared, non-resettable environments.


### campaign-eval-learn-conditions

Which population, task and evaluation conditions limit each reported result in this source? Keep comparator and metric definitions with the claims.

**p1 — insufficient / bounded_partial_answer**

Which population, task and evaluation conditions limit each reported result in this source? Keep comparator and metric definitions with the claims.

Retained support: The TensorSSM abstract describes tensor tokenisation, cross-mode dependencies and state updates.

Missing: No reported numerical result, population, task dataset, comparator, metric definition or evaluated condition is present. Do not fabricate result conditions.

Limitation origins: available_text.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: The TensorSSM abstract describes tensor tokenisation, cross-mode dependencies and state updates.

Missing: No reported numerical result, population, task dataset, comparator, metric definition or evaluated condition is present. Do not fabricate result conditions.

Limitation origins: available_text.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: No reported numerical result, population, task dataset, comparator, metric definition or evaluated condition is present. Do not fabricate result conditions.

Limitation origins: available_text.

Selected exact passages:

- `u6494dfd09e443b85a647` · `arxiv:2610.40871` · `arxiv:2610.40871:v1:metadata-0be4ee69b6741057` · abstract · Unicode 0–1428 · parser `workspace-plain-text-v1`.

> High-dimensional tensors are ubiquitous in real-world applications but lead to massive storage overhead. Functional tensor decomposition addresses this by employing neural networks to map element coordinates to tensor cores, significantly reducing the parameters for data compression. However, existing functional methods typically flatten high-order tensors into 1D sequences. This folding operation causes highly overlapping local coordinate sequences and struggles to capture complex cross-mode spatial dependencies, severely limiting their expressiveness on diverse datasets. To tackle these challenges, we propose TensorSSM, a novel Implicit Neural Representation (INR) for functional decomposition method that memorizes spatial positions within a dynamic State Space Model (SSM). Specifically, TensorSSM first decomposes mode-wise coordinates into sequences spit by K-ary rule, encoding spatial tokens from coarse to fine, which effectively captures spatial variations. Furthermore, we extend the SSM's state space to explicitly map cross-mode spatial dependencies, allowing inter-mode interactions to enhance the updates of each mode. By integrating cross-mode information from previous hidden states into the current state transitions, TensorSSM effectively expands tensor representation along two dimensions: the sequence dimension for coarse-to-fine spatial tokens, and the state dimension for cross-mode memorization.


### campaign-eval-learn-experiment

What information in this retained source is enough to outline a reproducible experiment, and which implementation or protocol details must be requested?

**p1 — partially_answerable / bounded_partial_answer**

What information in this retained source is enough to outline a reproducible experiment, and which implementation or protocol details must be requested?

Retained support: The personalization abstract supplies 250 personas, five languages, 25K turns and a separation of strategy selection from execution. It supports a high-level outline.

Missing: Model identities, exact prompts, splits, annotation and training recipes, metric definitions and reproducible implementation are absent.

Limitation origins: available_text, extraction.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: The personalization abstract supplies 250 personas, five languages, 25K turns and a separation of strategy selection from execution. It supports a high-level outline.

Missing: Model identities, exact prompts, splits, annotation and training recipes, metric definitions and reproducible implementation are absent.

Limitation origins: available_text, extraction.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: Model identities, exact prompts, splits, annotation and training recipes, metric definitions and reproducible implementation are absent.

Limitation origins: available_text, extraction.

Selected exact passages:

- `uaa962b619d4135eadc40` · `arxiv:2610.40930` · `arxiv:2610.40930:v1:metadata-b45059ef8928ae02` · abstract · Unicode 0–1489 · parser `workspace-plain-text-v1`.

> Human preferences change over time: an established preference may remain valid over time, become uncertain as context shifts, or be explicitly revised. Effective personalization requires conversational AI to adapt its response strategy to evolving preferences rather than relying on passive memory retrieval. We formalize this capability as adaptive personalization under epistemic uncertainty. A human preference study further confirms that people favor state-contingent response strategies as preference uncertainty changes. To evaluate whether language models mirror this adaptation, we create a multilingual benchmark spanning 250 personas, 5 languages, and 25K conversational turns that decouples strategy selection from response execution. Across eight closed- and open-weight models, we uncover a recognition-generation gap: models reliably identify appropriate strategies when selecting among candidate options, but collapse during open-ended generation, suffering a 35-46% drop in strategy calibration. Crucially, this failure is systematic: models default to exploit-first behavior, over-relying on existing preferences regardless of preference epistemic uncertainty. We show this failure is addressable: while prompting interventions fail, targeted training that supervises models' internal strategy representations toward state-conditional human preferences narrows the user acceptability generalization gap by a third on out-of-distribution personas and conversational styles.


### campaign-eval-learn-measurement

Explain one reported empirical finding with its metric and scope, and distinguish it from hypothesised applications.

**p1 — partially_answerable / bounded_partial_answer**

Explain one reported empirical finding with its metric and scope, and distinguish it from hypothesised applications.

Retained support: EDB-Bio reports 96K episodes across three biological domains and a reported 2.5x experiment-selection efficiency advantage for Ibis0 against the best frontier models. Applications remain proposals.

Missing: The operational efficiency denominator, exact comparator identities, uncertainty and detailed evaluation conditions are not retained. No clinical efficacy or safety finding is established.

Limitation origins: available_text, extraction.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: EDB-Bio reports 96K episodes across three biological domains and a reported 2.5x experiment-selection efficiency advantage for Ibis0 against the best frontier models. Applications remain proposals.

Missing: The operational efficiency denominator, exact comparator identities, uncertainty and detailed evaluation conditions are not retained. No clinical efficacy or safety finding is established.

Limitation origins: available_text, extraction.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: The operational efficiency denominator, exact comparator identities, uncertainty and detailed evaluation conditions are not retained. No clinical efficacy or safety finding is established.

Limitation origins: available_text, extraction.

Selected exact passages:

- `u638d145f43da593f92c7` · `arxiv:2610.41015` · `arxiv:2610.41015:v1:metadata-9d3401c4c7c1014c` · abstract · Unicode 0–1516 · parser `workspace-plain-text-v1`.

> Expert scientists excel at weighing empirical findings from multiple sources that vary in both statistical reliability and epistemic relevance. To what extent are language models, which are increasingly driving autonomous discovery systems, capable of such evidence deliberation? We introduce EDB-Bio, a scientific reasoning benchmark curated from real-world data in three biological domains: drug-perturbation transcriptomics, CRISPR screens, and human genome-wide association studies (GWAS). Each of EDB-Bio's 96k episodes presents a sequence of experimental results from published studies and asks the model to predict the probability that a target hypothesis is true. Out-of-the-box, open-weight and frontier models alike demonstrate systematic underconfidence and attain Brier scores comparable to a trivial base-rate forecaster. Post-training against strictly proper scoring rules significantly improves both calibration and discrimination. This calibration pays off downstream: in a sequential experiment selection task, our Ibis0 model is 2.5 times more efficient than the best frontier model. Throughout, quantifying evidence weights as Bayes factors reveals how models update their beliefs over time, whether they agree with expert biologists on relevance, and where they exhibit inconsistencies and biases. Our work extends calibration training and uncertainty analysis to a realistic scientific forecasting setting with applications to human cancer biology. We release all code, data, and trained models.


### campaign-eval-research-memory

Which selected evidence explains how agent memory is updated and how incorrect information can persist? Separate mechanisms from measurements.

**p1 — partially_answerable / bounded_partial_answer**

Which selected evidence explains how agent memory is updated and how incorrect information can persist? Separate mechanisms from measurements.

Retained support: KEEPER separates memory auxiliary objectives and reports an incorrect claim persisting despite correction in one baseline trajectory. The harness source concerns portable versioned orchestration, not a second memory-error experiment.

Missing: Exact update algorithm, error prevalence, replication and longitudinal calibration are unavailable. Do not generalise a single trajectory or treat harness scores as memory measurements.

Limitation origins: corpus, selection, available_text.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: KEEPER separates memory auxiliary objectives and reports an incorrect claim persisting despite correction in one baseline trajectory. The harness source concerns portable versioned orchestration, not a second memory-error experiment.

Missing: Exact update algorithm, error prevalence, replication and longitudinal calibration are unavailable. Do not generalise a single trajectory or treat harness scores as memory measurements.

Limitation origins: corpus, selection, available_text.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: Exact update algorithm, error prevalence, replication and longitudinal calibration are unavailable. Do not generalise a single trajectory or treat harness scores as memory measurements.

Limitation origins: corpus, selection, available_text.

Selected exact passages:

- `ucbe894d1356a18e9f328` · `arxiv:2610.41482` · `arxiv:2610.41482:v1:metadata-e5c832a06d88973f` · abstract · Unicode 0–875 · parser `workspace-plain-text-v1`.

> Recursive textual memory can carry earlier errors into later updates, yet task performance alone does not establish memory reliability. We define self-consistency bias as the persistence of incorrect claims already present in the incoming memory. We present KEEPER, a comparative analysis of four auxiliary objectives along information-content and update-sensitivity axes within a shared recursive interface, examining how supervision targets relate to agent performance. Among evaluated conditions, reward-related prediction achieve the highest task performance before and after offline reinforcement learning, outperforming joint supervision. A claim-level analysis of one baseline trajectory documents error persistence despite corrective observations. Together, these analyses motivate evaluating error persistence and valid-information retention alongside task outcomes.

- `u0b8e339ef860923aa8e9` · `arxiv:2610.40917` · `arxiv:2610.40917:v1:metadata-ed88c851cf4b1810` · abstract · Unicode 0–1216 · parser `workspace-plain-text-v1`.

> Large language models act only through the infrastructure that surrounds them. That infrastructure, the harness, determines what a model can accomplish and how it fails, yet it has no settled definition. To address this gap, we decompose the harness into eight functional components that can be specified and compared across systems, and we propose a portable specification framework that records which model ran in which harness. The record is needed because different harness configurations can yield several-fold differences in reported scores for the same model, and because much of an agent's attack surface lies in its harness. Existing model cards and agent cards provide release and operational information, but do not establish the sequence of effective configurations within a run. Harnesses can change between releases and between runs, and, where agents edit their own tools and configuration, within a run. Enacted AI laws contain documentation duties relevant to covered systems, subject to their respective scopes and application dates, but do not prescribe the common harness record proposed here. Therefore, the harness has to be explicitly described and specified as a versioned part of the system.


### campaign-eval-research-retrieval

Compare selected retrieval and RAG methods only on compatible evaluation evidence. State unavailable common tasks, baselines, relevance judgments and counterevidence.

**p1 — insufficient / comparison_only_abstention**

Compare selected retrieval and RAG methods only on compatible evaluation evidence. State unavailable common tasks, baselines, relevance judgments and counterevidence.

Retained support: The MTRAG/RETECO and SciFact-poisoning abstracts separately describe retrieval sufficiency and one-model evidence-majority sensitivity.

Missing: No shared task, model, metric, baseline or relevance judgments permit a comparative performance conclusion. Keep source notes independent and the requested comparison unanswered.

Limitation origins: corpus, ranking, selection, available_text.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: The MTRAG/RETECO and SciFact-poisoning abstracts separately describe retrieval sufficiency and one-model evidence-majority sensitivity.

Missing: No shared task, model, metric, baseline or relevance judgments permit a comparative performance conclusion. Keep source notes independent and the requested comparison unanswered.

Limitation origins: corpus, ranking, selection, available_text.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: No shared task, model, metric, baseline or relevance judgments permit a comparative performance conclusion. Keep source notes independent and the requested comparison unanswered.

Limitation origins: corpus, ranking, selection, available_text.

Selected exact passages:

- `u1aab0740f44dab2c5010` · `arxiv:2610.40966` · `arxiv:2610.40966:v1:metadata-55c0a56c8750035c` · abstract · Unicode 0–1545 · parser `workspace-plain-text-v1`.

> Conversational RAG benchmarks such as MTRAG and RETECO evaluate retrieval and generation end to end: each system answers from its own retrieval, so abstention must be scored against whether each retrieved context is sufficient. A convenient shortcut reads sufficiency off the relevance judgments and treats a context without gold documents as unanswerable. We re-run the official baselines exactly and test this shortcut on RECOR (RETECO track~2) with four retrievers (nDCG@10 from .18 to .59) and three Qwen3 readers. Two open LLM judges and a panel of four small open models label each context by content, and a model of another family audits 250 contexts blind, with adjudication. The stronger the retriever, the larger the share of no-gold contexts that still contain the answer (28\% to 72\%) and the lower the shortcut's precision (.68 to .10; .70 to .21 under the audit). A reader agrees: Qwen3-4B answers 62--67\% of these false misses correctly, against 23--30\% of no-gold contexts judged insufficient and 1\% with no documents. In most false misses, the answer comes from a hard negative mined for the same question, another turn's gold or a neighbouring chunk of the gold page. On MTRAG, whose judgments come from annotators, precision drops from .72 to .50. Under the shortcut, answerability AUROC is up to .19 too low, and the best sufficiency detector appears to be a retrieval score that never reads the documents. We release code, runs and labels, and recommend scoring refusals against content labels, not the presence of gold.

- `u51eb3c267dcf8b28d986` · `arxiv:2610.41012` · `arxiv:2610.41012:v1:metadata-f20dbad8ce03c4ef` · abstract · Unicode 0–1118 · parser `workspace-plain-text-v1`.

> Retrieval-augmented generation (RAG) can expose language models to misleading evidence in retrieved documents. We investigate whether increasing the number of mutually agreeing poisoned documents affects a model's ability to detect misinformation. We evaluate 200 randomly selected questions from SciFact (random seed 38), comparing contexts with one poisoned and six healthy documents against contexts with six mutually agreeing poisoned documents and one healthy document. For Gemma-3-12b, poison-detection rates decrease from 25% (50/200) in the minority condition to 10% (20/200) in the majority condition. Among the 38 questions with different outcomes across conditions, 34 change from detected to undetected, while only four change in the opposite direction (exact McNemar test, p = 6.04e-7). This pattern is consistent with a conformity-like response to a majority of mutually agreeing poisoned documents. Our results provide initial evidence of conformity bias in RAG-based misinformation detection: Gemma-3-12b is substantially less likely to detect poisoned claims when they dominate the retrieved evidence.


### campaign-eval-research-verification

What measurements in the selected sources support trustworthy claim verification? Preserve uncertainty, abstention and calibration limits.

**p1 — partially_answerable / bounded_partial_answer**

What measurements in the selected sources support trustworthy claim verification? Preserve uncertainty, abstention and calibration limits.

Retained support: The personalization and SciFact abstracts describe bounded calibration or failure risks. SciFact uses 200 questions, Gemma3-12B and unequal clean/poisoned evidence; the other measures personalization strategies.

Missing: Neither establishes a trustworthy general factual checker, calibrated abstention, or verifier precision/recall. Strategy calibration is not factual-verification accuracy.

Limitation origins: corpus, ranking, selection, available_text.

**p2 — partially_answerable / bounded_partial_answer**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: The personalization and SciFact abstracts describe bounded calibration or failure risks. SciFact uses 200 questions, Gemma3-12B and unequal clean/poisoned evidence; the other measures personalization strategies.

Missing: Neither establishes a trustworthy general factual checker, calibrated abstention, or verifier precision/recall. Strategy calibration is not factual-verification accuracy.

Limitation origins: corpus, ranking, selection, available_text.

**p3 — answerable / answer**

Identify missing evidence or required details without inventing findings.

Retained support: The retained scope and absent details above permit identifying bounded evidence gaps, without supplying missing findings.

Missing: Neither establishes a trustworthy general factual checker, calibrated abstention, or verifier precision/recall. Strategy calibration is not factual-verification accuracy.

Limitation origins: corpus, ranking, selection, available_text.

Selected exact passages:

- `uaa962b619d4135eadc40` · `arxiv:2610.40930` · `arxiv:2610.40930:v1:metadata-b45059ef8928ae02` · abstract · Unicode 0–1489 · parser `workspace-plain-text-v1`.

> Human preferences change over time: an established preference may remain valid over time, become uncertain as context shifts, or be explicitly revised. Effective personalization requires conversational AI to adapt its response strategy to evolving preferences rather than relying on passive memory retrieval. We formalize this capability as adaptive personalization under epistemic uncertainty. A human preference study further confirms that people favor state-contingent response strategies as preference uncertainty changes. To evaluate whether language models mirror this adaptation, we create a multilingual benchmark spanning 250 personas, 5 languages, and 25K conversational turns that decouples strategy selection from response execution. Across eight closed- and open-weight models, we uncover a recognition-generation gap: models reliably identify appropriate strategies when selecting among candidate options, but collapse during open-ended generation, suffering a 35-46% drop in strategy calibration. Crucially, this failure is systematic: models default to exploit-first behavior, over-relying on existing preferences regardless of preference epistemic uncertainty. We show this failure is addressable: while prompting interventions fail, targeted training that supervises models' internal strategy representations toward state-conditional human preferences narrows the user acceptability generalization gap by a third on out-of-distribution personas and conversational styles.

- `u51eb3c267dcf8b28d986` · `arxiv:2610.41012` · `arxiv:2610.41012:v1:metadata-f20dbad8ce03c4ef` · abstract · Unicode 0–1118 · parser `workspace-plain-text-v1`.

> Retrieval-augmented generation (RAG) can expose language models to misleading evidence in retrieved documents. We investigate whether increasing the number of mutually agreeing poisoned documents affects a model's ability to detect misinformation. We evaluate 200 randomly selected questions from SciFact (random seed 38), comparing contexts with one poisoned and six healthy documents against contexts with six mutually agreeing poisoned documents and one healthy document. For Gemma-3-12b, poison-detection rates decrease from 25% (50/200) in the minority condition to 10% (20/200) in the majority condition. Among the 38 questions with different outcomes across conditions, 34 change from detected to undetected, while only four change in the opposite direction (exact McNemar test, p = 6.04e-7). This pattern is consistent with a conformity-like response to a majority of mutually agreeing poisoned documents. Our results provide initial evidence of conformity bias in RAG-based misinformation detection: Gemma-3-12b is substantially less likely to detect poisoned claims when they dominate the retrieved evidence.


### campaign-eval-research-insufficient

Can the selected sources justify a learned controller for a vehicle whose configuration, operating conditions, safety criteria and validation data have not been supplied?

**p1 — insufficient / full_application_abstention**

Can the selected sources justify a learned controller for a vehicle whose configuration, operating conditions, safety criteria and validation data have not been supplied?

Retained support: Neither web-agent safety predictions nor a fairness protocol supplies evidence for the unspecified physical vehicle.

Missing: Vehicle/configuration, operating envelope, safety objectives and validation evidence are missing. All parts require full application abstention with no claims or source-note sections.

Limitation origins: application_context, corpus, ranking, selection, available_text.

**p2 — insufficient / full_application_abstention**

State separately cited source facts and retain study scope, comparator, metric definition and conditions.

Retained support: Neither web-agent safety predictions nor a fairness protocol supplies evidence for the unspecified physical vehicle.

Missing: Vehicle/configuration, operating envelope, safety objectives and validation evidence are missing. All parts require full application abstention with no claims or source-note sections.

Limitation origins: application_context, corpus, ranking, selection, available_text.

**p3 — insufficient / full_application_abstention**

Identify missing evidence or required details without inventing findings.

Retained support: Ask for the explicitly missing application context; no factual source notes.

Missing: Vehicle/configuration, operating envelope, safety objectives and validation evidence are missing. All parts require full application abstention with no claims or source-note sections.

Limitation origins: application_context, corpus, ranking, selection, available_text.

Selected exact passages:

- `u199bc87ac63c4d9e8535` · `arxiv:2610.40798` · `arxiv:2610.40798:v1:metadata-c1a34fa53cba3d51` · abstract · Unicode 0–1588 · parser `workspace-plain-text-v1`.

> Web world models increasingly predict the consequences of candidate actions before agents act, yet a plausible predicted future does not necessarily support the correct safety decision. In a matched human evaluation of 3,000 predictions from ten frozen open models, 86.1% are judged semantically plausible. However, several models exhibit highly asymmetric authorisation behaviour, combining low false-safe execution with poor recall of clarifiable ASK cases and a strong preference for BLOCK. This motivates safety sufficiency: whether a predictive interface preserves and exposes the policy-decisive information required to distinguish actions that may be EXECUTED, require clarification through ASK, or should be BLOCKED. We introduce SafeWebWorld, a benchmark for evaluating safety sufficiency across five web-safety domains through action-conditioned futures, policy-decisive evidence, and policy-conditioned decisions. Under a controlled Security-Aligned Supervised Fine-Tuning protocol, evidence preservation can improve substantially while authorisation-sensitive decisions deteriorate. To determine whether this deterioration reflects loss of authorisation-sensitive score structure or a failure of the decision readout, we introduce Latent Authorisation Recovery (LAR). Frozen-score recalibration reveals substantial but backbone-dependent recovery, while paired recovery provides only a modest additional gain. Yet within-family and matched-authorisation evaluations remain poor, showing that aggregate recoverability does not imply robust fine-grained authorisation behaviour.

- `ub314a0bb598e7e9dfabe` · `arxiv:2610.40893` · `arxiv:2610.40893:v1:metadata-018e69b4ec3841a0` · abstract · Unicode 0–1403 · parser `workspace-plain-text-v1`.

> Fairness benchmarks for large language models (LLMs) are overwhelmingly English-born and American in their social categories; translated versions carry those categories into societies where they do not apply, and almost none fix their hypotheses before the models are run. We present Qistas (Arabic qistas, "the just balance"), a protocol for evaluating how LLMs treat the social, confessional, and regional constituencies of a society, portable across countries and instantiated first for Iraq. In its pilot form it measures only what needs no verdict on contested truth: procedural symmetry across matched counterfactual pairs, differential refusal, stereotype reliance under ambiguity, and terminological framing of documented events. Every measurement is paired by construction and analysed with paired machinery (sign-flip permutation tests, exact McNemar tests, template-clustered bootstrap intervals, Holm-corrected families), with a power analysis that states, before any data exist, the smallest effect each axis can detect after the design effect of template clustering. We release the authoring apparatus (a pruned 3x5 taxonomy with four cells closed by design, per-type checklists, a cumulative rulings log, a structural audit, and a human review notebook) and report its first field test: a semantic review of a 58-item seed bank in which 24 of 25 template groups failed at least one check.

## Frozen interpretation

Execution, provenance, whole-claim support, qualifications/atomicity, coverage, abstention and checker error counts remain separate. Valid citations alone establish neither relevance nor factual support. A positive coverage association is not proof the whole request was answered.

A faithful retrieval/comparison abstention can agree with the reference and still leave the research need unmet. The conditions abstract supplies no reported evaluation result to explain. The safety case requires full application abstention without background claims. Abstract-only experiment outlines are not reproducible protocols.

The unchanged evidence minimums are8 evaluation workflows,20 generated evaluation claims and20 probe records. Development facts do not fill evaluation minimums. Insufficient evidence, missing labels or too few actual factual claims remain HOLD; no filler is generated. The prospective overall request-fulfillment gate requires met parts; bounded partial answers and appropriate abstention are visible separately and do not become a fabricated overall PASS. Any retained unsupported assertion, bundled claim, lost qualification or invalid provenance still fails its quality gate.

Human qualification, usefulness, fresh intake, literature recall and reliable full-paper extraction remain unmeasured. All old results and their original scorers remain separate.

All rights reserved. No license or reuse permission is granted.
