# Exact retained source selection

Frozen public inputs, not fresh acquisition. Excerpt/abstract scope remains limited; omitted pages and extraction reliability are not established here. No private notes, reading history, preferences or drafts are submitted.

## uf800ed16cb52eb251690

Work: arxiv:2210.03629

Version: arxiv:2210.03629:v3

Material: mat-2b7a38f3cfa1449f7728f044688ca2c2

Span: span-55b2971cd5f40c431b738813c7ef10cd

Scope: excerpt; page: 1; Unicode offsets: [2443, 3888)

Source hash: sha256:f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69

Parser: workspace-pymupdf-1.28.0-text-sort-v1-selected-pages-v1

> Furthermore, on two interactive decision making benchmarks (ALFWorld and
>                            WebShop), ReAct outperforms imitation and reinforcement learning methods by
>                             an absolute success rate of 34% and 10% respectively, while being prompted with
>                               only one or two in-context examples.
>
>
>                 1  INTRODUCTION
>
>               A unique feature of human intelligence is the ability to seamlessly combine task-oriented actions with
>                         verbal reasoning (or inner speech, Alderson-Day & Fernyhough, 2015), which has been theorized toarXiv:2210.03629v3                      play an important role in human cognition for enabling self-regulation or strategization (Vygotsky,
>                      1987; Luria, 1965; Fernyhough, 2010) and maintaining a working memory (Baddeley, 1992). Con-
>                          sider the example of cooking up a dish in the kitchen. Between any two speciﬁc actions, we may
>                        reason in language in order to track progress (“now that everything is cut, I should heat up the pot of
>                         water”), to handle exceptions or adjust the plan according to the situation (“I don’t have salt, so let
>                 me use soy sauce and pepper instead”), and to realize when external information is needed (“how do
>                              I prepare dough? Let me search on the Internet”).

## ua6f0f4d05fd72b2b86b2

Work: arxiv:2210.03629

Version: arxiv:2210.03629:v3

Material: mat-2b7a38f3cfa1449f7728f044688ca2c2

Span: span-b615625987cdbfe74682109ab6dc0e19

Scope: excerpt; page: 6; Unicode offsets: [2005, 3379)

Source hash: sha256:f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69

Parser: workspace-pymupdf-1.28.0-text-sort-v1-selected-pages-v1

> B) While interleaving reasoning, action and observation steps improves ReAct’s grounded-
> ness and trustworthiness, such a structural constraint also reduces its ﬂexibility in formulating
> reasoning steps, leading to more reasoning error rate than CoT. we note that there is one frequent
> error pattern speciﬁc to ReAct, in which the model repetitively generates the previous thoughts and
> actions, and we categorize it as part of “reasoning error” as the model fails to reason about what the
> proper next action to take and jump out of the loop4.
>
>   C) For ReAct, successfully retrieving informative knowledge via search is critical. Non-
> informative search, which counts for 23% of the error cases, derails the model reasoning and gives
> it a hard time to recover and reformulate thoughts. This is perhaps an expected trade-off between
> factuality and ﬂexibility, which motivates our proposed strategies of combining two methods.
>
> We provide examples for each success and failure modes in Appendix E.1. We also ﬁnd some
> HotpotQA questions may contain outdated answer labels, see Figure 4 for example.
>
> ReAct + CoT-SC perform best for prompting LLMs  Also shown in Table 1, the best prompting
> method on HotpotQA and Fever are ReAct →CoT-SC and CoT-SC →ReAct respectively.
> Furthermore, Figure 2 shows how different methods perform with respect to the number of CoT-SC
> samples used.

## u423a5ed5c10153d66367

Work: arxiv:2310.11511

Version: arxiv:2310.11511:v1

Material: mat-f98fbd73f423776117f60cac36edc90a

Span: span-f021c711415ab7488317517d7cbe41d5

Scope: excerpt; page: 3; Unicode offsets: [2058, 3616)

Source hash: sha256:d9eaa1398abac0df67a9d0933a5bf8b6d9d83d2e72da2a486073cd842dd52978

Parser: workspace-pymupdf-1.28.0-text-sort-v1-selected-pages-v1

> While their value function
> simply indicates an overall score of each generation, SELF-RAG trains to an arbitrary LM to learn to
> generate fine-grained self-reflection and customizable inference.
>
> Training and generating with critics. Training LLMs with reinforcement learning (e.g., Proximal
> Policy Optimization or PPO; Schulman et al. 2017) from human feedback (RLHF) has proven
> effective in aligning LLMs with human preferences (Ouyang et al., 2022). Wu et al. (2023) introduce
> fine-grained RLHF with multiple reward models. Though our work also studies fine-grained critique
> on retrieval and generation, we train our target LM on task examples augmented with reflection
> tokens from a critic model offline, with a far lower training cost compared to RLHF. In addition,
> reflection tokens in SELF-RAG enable controllable generation at inference, while RLHF focuses on
> human preference alignment during training. Other works use general control tokens to guide LM
> generation (Lu et al., 2022; Korbak et al., 2023), while SELF-RAG uses reflection tokens to decide the
> need for retrieval and to self-evaluate generation quality. Xie et al. (2023) propose a self-evaluation-
> guided decoding framework, but they focus only on reasoning tasks with one evaluation dimension
> (reasoning path consistency) and without retrieval. Recent work on LLM refinement (Dhuliawala
> et al., 2023; Madaan et al., 2023; Paul et al., 2023) prompts a model to generate task output, natural
> language feedback and refined task output iteratively, but at the cost of inference efficiency.
