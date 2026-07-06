# Feature Ideas

Idea catalog grouped by category. Not prioritized here — see [03-roadmap.md](03-roadmap.md) for sequencing.

## Research Quality (raise the ceiling of what the agent can produce)

1. **Multi-source retrieval beyond arXiv**
   - Semantic Scholar API (has citation graph — huge unlock)
   - OpenReview (peer reviews for ICLR/NeurIPS/etc — high-signal criticism)
   - PubMed / bioRxiv for adjacent domains
   - Papers With Code (linked benchmarks + implementations)
   - GitHub (find reference implementations)
   - A pluggable `SourceAdapter` interface so new sources drop in.

2. **Citation graph traversal** — after finding N seed papers, walk 1–2 hops of citations/references (via Semantic Scholar). Massively improves recall for "what's the state of the art?" queries.

3. **Temporal awareness** — filter/prioritize by date, detect "outdated consensus," track how conclusions evolved over time. Add a `--since 2024` flag.

4. **Contradiction detection agent** — a dedicated agent that surfaces where papers disagree, with quotes from each side. Research teams love this.

5. **Reproducibility scoring** — flag which papers have code/data/checkpoints released. Score each finding by reproducibility.

6. **Benchmark extraction** — dedicated tool that pulls result tables from papers (methodology-aware; a lot of "SOTA" claims collapse when you compare apples-to-apples).

7. **Author reputation signal** — careful, can bias. Use citation counts, h-index, or affiliation as *one* input, never the only one.

8. **Method taxonomy** — auto-cluster papers by approach (e.g., "RLHF-based," "constitutional AI," "process reward models") and structure the report around the taxonomy instead of a flat list.

9. **Follow-up question generation** — critic proposes 3–5 "what you should ask next" questions. Great for interactive UX.

10. **Report formats** — executive brief (1 page), technical deep dive (10 pages), slide deck outline, literature review skeleton. Same underlying analysis, multiple renderers.

## Agent Architecture

11. **Human-in-the-loop breakpoints** — LangGraph `interrupt_before=["search"]` so a user reviews sub-questions before spending $$ downstream. Already listed in Phase 3 of the original CLAUDE.md.

12. **Parallel reader** — currently reader appears sequential. Fan out per-paper reads with `asyncio.gather` or LangGraph's `Send` API. Biggest latency win available.

13. **Dynamic agent routing** — critic decides not just "revise" but *which* agent to re-run, with structured feedback per target. Skeleton exists; make the feedback richer (e.g., critic emits a list of missing topics that the planner consumes as constraints).

14. **Tool-using reader** — reader can call sub-tools: `extract_table`, `extract_equation`, `find_related_work_section`. Not just "give me text."

15. **Memory across queries** — long-term memory of which papers a user has already seen; suppress or highlight repeats. Persist to SQLite/Postgres per user.

16. **Adversarial debate agents** — spawn two synthesizer variants ("optimist" and "skeptic"), then a judge agent picks. Improves calibration on hype-heavy topics.

17. **Cost-aware routing** — planner decides Haiku vs. Sonnet vs. Opus per sub-question based on complexity. Big enterprise sell.

18. **Cache-aware prompts** — leverage Claude prompt caching for the paper corpus (long paper text in cache; short question varies). Can cut costs 5–10×.

## Data & Storage

19. **Vector store beyond in-memory FAISS** — pluggable backend (FAISS local, Qdrant, Pinecone, pgvector). Persist paper embeddings so you don't re-embed the same PDF twice.

20. **Paper cache** — every downloaded PDF + parsed text + chunk embeddings persisted keyed by arXiv ID. Second query on same paper is free.

21. **User workspaces** — saved reports, saved paper collections, tags, notes.

22. **Versioned reports** — every revision iteration saved; user can diff.

23. **Export pipeline** — Markdown → PDF (WeasyPrint), DOCX (python-docx), LaTeX, Notion API, Google Docs API.

## UX

24. **Web UI** (Next.js or Streamlit for MVP) with:
    - Live streaming of agent progress (which agent is running, what it's seeing)
    - Clickable citations that open the paper
    - Inline PDF viewer with highlighted snippets the reader used
    - Feedback thumbs (feeds eval dataset)

25. **Slack / Teams bot** — enterprise research teams live in Slack. `/research <query>` → thread with progress + final report.

26. **CLI polish** — Rich/Textual for pretty terminal output, progress bars per agent, colorized citations.

27. **Query templates** — "compare methods X and Y", "SOTA on benchmark Z", "survey of domain W". Each template biases the planner differently.

28. **Follow-up conversations** — turn the one-shot pipeline into a chat where the user can drill down: "expand on paper 3", "find critiques of this approach".

## Enterprise-Specific

29. **Private corpus support** — bring your own PDF collection (internal research, competitor whitepapers). Same pipeline, private index.

30. **Multi-tenancy** — orgs, users, isolated data, per-org rate limits and budgets.

31. **Budget controls** — hard $ cap per query, per user, per org per day.

32. **Compliance mode** — deterministic runs (temperature=0), full provenance chain for every claim, exportable audit trail.

33. **On-prem / VPC deployment** — Docker + Helm chart, Bedrock/Vertex/Azure OpenAI adapters so customers can use their own cloud LLM contract.

34. **SSO** (SAML/OIDC) — Auth0 or WorkOS integration.

35. **Fine-tuning feedback loop** — user rates reports → dataset for DPO on smaller open-weights critic/synthesizer. Long-term differentiator.
