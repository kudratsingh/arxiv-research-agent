"""Offline, richer demo seed for local screenshots. NOT for CI, never touches the network.

Feeds hand-written RSS bytes through the real intake parser via fetch_source's
`transport=` injection, then ingests and freezes an edition exactly like
POST /workspace/refresh would. arXiv IDs use the 2611.99xxx range so they do
not collide with real papers. Run from repo root: python - < rich_seed.py
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

OWNER = os.environ.get("WORKSPACE_OWNER", "e2e")
if "127.0.0.1" not in os.environ.get("POSTGRES_URL", "") and "localhost" not in os.environ.get("POSTGRES_URL", ""):
    raise SystemExit("rich seed only runs against a loopback Postgres")
if os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled":
    raise SystemExit("rich seed requires ANTHROPIC_API_KEY=local-preview-disabled")

ARXIV = {
    "arxiv-cs-lg": ("cs.LG", [
        ("Budgeted Retrieval for Long-Horizon Agents: When to Stop Searching",
         "Mara Lindqvist, Tobias Ekwueme, Ana Ruiz",
         "Retrieval-augmented agents often over-query. We study a stopping rule that trades marginal evidence gain against a fixed compute budget and evaluate it on multi-hop question answering. The rule cuts retrieval calls by 41% with no loss in exact match on three benchmarks, and we release the evaluation harness."),
        ("Sparse Mixture-of-Experts Inference on a Single GPU via Expert Caching",
         "Hiro Tanaka, Lena Vogt",
         "We describe an expert caching policy for serving sparse mixture-of-experts language models on commodity hardware. Profiling shows expert reuse is highly skewed; a frequency-aware cache reaches 2.3x throughput over offloading baselines while preserving accuracy. We discuss memory-latency tradeoffs for ML systems."),
        ("Calibrated Uncertainty for Learned Simulators in Fluid Dynamics",
         "Priya Raman, Jonas Feldt, Chen Wei",
         "Machine learning for science increasingly relies on learned simulators. We propose a conformal wrapper that produces calibrated rollout uncertainty for graph-network fluid simulators and show coverage holds across Reynolds numbers outside the training distribution."),
        ("Reward Model Overoptimization Is Predictable from Early Checkpoints",
         "Sam Okafor, Ines Duarte",
         "We show that the onset of reward hacking during RLHF can be forecast from the first 5% of training by tracking the divergence between proxy and held-out preference scores. A simple early-stopping criterion recovers most of the gold-reward peak."),
    ]),
    "arxiv-cs-ai": ("cs.AI", [
        ("Tool-Use Agents Need Memory Hygiene: Evaluating Stale Context in Multi-Step Tasks",
         "Rosa Kim, Daniel Abara, Yusuf Demir",
         "Agents that accumulate tool outputs in memory frequently act on stale state. We introduce a benchmark of 600 multi-step tasks with controlled state changes and evaluate retrieval and memory policies. Explicit invalidation improves task success from 54% to 71%."),
        ("Verifying Scientific Claims with Retrieval and Small Verifier Models",
         "Elif Sahin, Marco Bellini",
         "We pair a dense retriever with a 1B-parameter verifier fine-tuned for claim-evidence entailment. On SciFact-style evaluation the system matches a 70B judge at 3% of the inference cost, and errors concentrate on numerical claims and negations."),
        ("Planning with Language Models Under Partial Observability in Embodied Environments",
         "Ola Nordmann, Kwame Mensah",
         "We evaluate inference-time reasoning strategies for embodied agents that must plan with incomplete observations. Tree search over belief states outperforms chain-of-thought prompting by 18 points in household rearrangement tasks, at four times the token cost."),
        ("A Control-Theoretic View of Agent Self-Correction Loops",
         "Ivan Petrov, Hannah Cole",
         "We model iterative self-correction in research agents as a feedback control system and derive stability conditions on critique gain. Experiments confirm oscillation when critique is overweighted, and a damped update rule removes it."),
    ]),
    "arxiv-cs-cl": ("cs.CL", [
        ("Long-Context Evaluation Is Mostly Retrieval: A Diagnostic Suite",
         "Noor Haddad, Felix Brandt",
         "We decompose popular long-context benchmarks into retrieval, aggregation and reasoning components. Most items are solvable by retrieval alone; we propose a diagnostic suite that isolates reasoning over long inputs and report results for twelve language models."),
        ("Citation Faithfulness in Generated Literature Reviews",
         "Grace Liu, Tomasz Nowak, Aisha Bello",
         "We audit 1,200 citations produced by research assistants and find 19% do not support the sentence they are attached to. A retrieval-grounded rewrite step halves the rate. We release annotations for claim verification research."),
        ("Instruction Following Degrades Predictably with Prompt Length",
         "Leo Martins, Sara Kowalski",
         "We measure instruction adherence as prompts grow and fit a simple power law. Placement of constraints matters more than total length, with mid-prompt constraints dropped most often."),
    ]),
}
BLOGS = {
    "hugging-face-blog": ("https://huggingface.co/blog/", [
        ("Open evaluation harnesses for research agents", "A walkthrough of an open harness for evaluating tool-using research agents, covering task design, retrieval baselines and cost reporting."),
        ("Smaller verifiers, bigger impact", "How compact verifier models can check generated claims against retrieved evidence at a fraction of the inference cost."),
    ]),
    "google-research": ("https://research.google/blog/", [
        ("Learned simulators that know when they are wrong", "An excerpt on uncertainty-aware learned simulators for scientific machine learning and why calibration matters for downstream decisions."),
    ]),
}


def arxiv_rss(category: str, rows: list[tuple[str, str, str]], now: datetime, start: int) -> bytes:
    items = []
    for offset, (title, authors, abstract) in enumerate(rows):
        aid = f"2611.{99000 + start + offset:05d}"
        version = "v2" if offset == 1 else "v1"
        kind = "replace" if version == "v2" else "new"
        stamp = format_datetime(now - timedelta(hours=6 + offset * 3))
        items.append(
            f"<item><title>{escape(title)}</title><link>https://arxiv.org/abs/{aid}</link>"
            f"<description>arXiv:{aid}{version} Announce Type: {kind} \nAbstract: {escape(abstract)}</description>"
            f"<guid isPermaLink=\"false\">oai:arXiv.org:{aid}{version}</guid><category>{category}</category>"
            f"<pubDate>{stamp}</pubDate><arxiv:announce_type>{kind}</arxiv:announce_type>"
            f"<dc:creator>{escape(authors)}</dc:creator></item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom"><channel><title>arXiv</title>' + "".join(items) + "</channel></rss>"
    ).encode()


def blog_rss(base: str, rows: list[tuple[str, str]], now: datetime) -> bytes:
    items = []
    for offset, (title, text) in enumerate(rows):
        slug = title.lower().replace(" ", "-").replace(",", "")
        items.append(
            f"<item><title>{escape(title)}</title><link>{base}{slug}</link><description>{escape(text)}</description>"
            f"<guid>{base}{slug}</guid><pubDate>{format_datetime(now - timedelta(days=1 + offset))}</pubDate></item>"
        )
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Blog</title>' + "".join(items) + "</channel></rss>").encode()


def main() -> None:
    from src.tools.postgres_pool import close_pool, get_pool
    from src.workspace.intake import SOURCES, HttpResponse, fetch_source
    from src.workspace.routes import prepare_edition
    from src.workspace.schemas import ProfileData, ProfileWrite
    from src.workspace.store import WorkspaceStore

    store = WorkspaceStore(get_pool())
    try:
        store.migrate()
        now = datetime.fromisoformat(store.cutoff()).astimezone(UTC)
        bodies: dict[str, bytes] = {}
        start = 0
        for source_id, (category, rows) in ARXIV.items():
            bodies[source_id] = arxiv_rss(category, rows, now, start)
            start += 100
        for source_id, (base, rows) in BLOGS.items():
            bodies[source_id] = blog_rss(base, rows, now)
        profile = store.profile(OWNER)
        minutes = int(os.environ.get("WORKSPACE_MINUTES", "45"))
        if profile["revision"] == 0 or profile["data"].get("minutes") != minutes:
            store.write_profile(OWNER, ProfileWrite(
                revision=profile["revision"],
                request_id=f"rich-demo-profile-{profile['revision']}-{minutes}",
                data=ProfileData(**{**profile["data"], "minutes": minutes}),
            ))
        counts = {}
        for source_id in SOURCES:
            body = bodies[source_id]

            def transport(url: str, headers: dict[str, str], body: bytes = body) -> HttpResponse:
                return HttpResponse(200, {"content-type": "application/rss+xml"}, body, url)

            result = fetch_source(source_id, store.validators(source_id), now=now, transport=transport)
            result.receipt["limitations"].append("Offline demo seed: hand-written feed bytes, no provider contacted.")
            store.ingest(source_id, result.items, result.receipt, result.validators)
            counts[source_id] = (result.receipt["status"], len(result.items))
        edition = prepare_edition(store, OWNER)
        print(json.dumps({"owner": OWNER, "sources": counts, "edition_id": edition["id"], "edition_items": len(edition["work_ids"]), "minutes": edition["minutes"]}))
    finally:
        close_pool()


if __name__ == "__main__":
    main()
