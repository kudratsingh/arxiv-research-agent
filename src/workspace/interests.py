"""Authored topic terms and bounded connector coverage, separate from navigation.

Selecting an authored ML parent includes its declared descendants. Broad
scholarly field navigation never implicitly enables every child or connector.
Terms are inspectable lexical signals, not semantic or completeness claims.
"""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

CATALOGUE: dict[str, dict[str, Any]] = {
    node["id"]: node for node in json.loads(Path(__file__).with_name("topics.json").read_text())["topics"]
}
ALL_SOURCES = ("arxiv-cs-lg", "arxiv-cs-ai", "arxiv-cs-cl", "hugging-face-blog", "google-research")
GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "ml:foundations-and-statistical-learning": ("generalization", "representation learning", "self-supervised", "learning theory", "scaling laws", "optimization"),
    "ml:neural-architectures": ("transformer", "attention", "neural network", "convolution", "state space model", "mixture of experts"),
    "ml:foundation-model-pretraining": ("pretraining", "pre-training", "foundation model", "tokenization", "data curation", "scaling law"),
    "ml:post-training-and-alignment": ("post-training", "post training", "alignment", "rlhf", "dpo", "fine-tuning", "instruction tuning", "preference optimization"),
    "ml:language-and-information": ("natural language", "language model", "information extraction", "text classification", "machine translation", "named entity"),
    "ml:multimodal-and-perception": ("multimodal", "vision", "image", "audio", "3d", "perception"),
    "ml:generative-models": ("diffusion", "generative", "generation", "flow matching", "autoregressive", "gan"),
    "ml:causal-and-reliable-learning": ("causal", "causality", "robustness", "distribution shift", "out-of-distribution", "reliability", "conformal"),
}
LEAF_ALIASES: dict[str, tuple[str, ...]] = {
    "parameter-efficient-fine-tuning": ("lora", "qlora", "peft"),
    "reinforcement-learning-from-feedback": ("rlhf", "rlaif"),
    "direct-preference-optimization": ("dpo",),
    "retrieval-augmented-generation": ("rag", "retrieval augmented"),
    "graph-neural-networks": ("gnn", "graph neural"),
    "convolutional-networks": ("cnn", "convolution"),
}


def descendants(topic_id: str) -> list[str]:
    """Transitive authored descendants, in catalogue order, without broad expansion."""
    result: list[str] = []
    frontier = [topic_id]
    while frontier:
        parent = frontier.pop(0)
        for key, node in CATALOGUE.items():
            if parent in node["parents"] and key not in result and node["kind"].startswith("authored_ml"):
                result.append(key)
                frontier.append(key)
    return result


def topic_terms(topic_id: str, existing: Mapping[str, tuple[str, ...]]) -> tuple[str, ...]:
    node = CATALOGUE.get(topic_id)
    if node and node["kind"] in {"external_domain", "external_field"}:
        return ()
    base = list(existing.get(topic_id, ()))
    if node and node["kind"] == "authored_ml_group":
        base.extend(GROUP_ALIASES.get(topic_id, ()))
        for child in descendants(topic_id):
            base.extend(topic_terms(child, existing))
    elif node and node["kind"] in {"authored_ml_topic", "authored_study_area"}:
        slug = topic_id.rsplit("/", 1)[-1]
        base.extend((slug.replace("-", " "), node["label"].lower()))
        base.extend(LEAF_ALIASES.get(slug, ()))
    elif topic_id not in CATALOGUE and "/" in topic_id:
        base.append(topic_id.rsplit("/", 1)[-1].replace("-", " "))
    return tuple(dict.fromkeys(term.lower() for term in base if term.strip()))


def topic_stream(topic_id: str) -> str:
    if topic_id in {"study:22/control-systems", "ml:embodied-intelligence/model-based-reinforcement-learning"} or topic_id.startswith("ml:machine-learning-for-science"):
        return "rocket-twin"
    if topic_id.startswith(("ml:multimodal-and-perception", "ml:generative-models", "ml:embodied-intelligence")):
        return "spatial"
    return "core"


def coverage(profile: Mapping[str, Any], sources: Sequence[Mapping[str, Any]], existing: Mapping[str, tuple[str, ...]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    source_map = {source["source_id"]: source for source in sources}
    current = now or datetime.now(UTC)
    def recent(source: Mapping[str, Any]) -> bool:
        raw = source.get("last_success_at") or source.get("receipt", {}).get("fetched_at")
        try:
            stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return stamp.tzinfo is not None and current - timedelta(days=7) <= stamp <= current + timedelta(minutes=5)
        except ValueError:
            return False
    enabled = set(profile.get("streams", ("core", "rocket-twin", "spatial")))
    result = []
    selections = [(str(topic), False) for topic in profile.get("topics", [])]
    selections += [(str(term), True) for term in profile.get("custom_topics", [])]
    for topic, custom in selections:
        node = CATALOGUE.get(topic)
        terms = (topic,) if custom else topic_terms(topic, existing)
        stream = topic_stream(topic)
        disabled = not custom and stream not in enabled
        if disabled:
            terms = ()
        connected = list(ALL_SOURCES) if terms else []
        if not custom and stream == "rocket-twin":
            connected = [key for key in connected if key in {"arxiv-cs-lg", "arxiv-cs-ai", "google-research"}]
        elif not custom and stream == "spatial":
            connected = [key for key in connected if key in {"arxiv-cs-lg", "arxiv-cs-ai", "hugging-face-blog"}]
        successful = {"success", "not_modified", "ok", "empty"}
        state = "unconnected" if not connected else "active" if all(source_map.get(key, {}).get("status") in successful and recent(source_map.get(key, {})) for key in connected) else "limited"
        limitations = ["Literal matches in bounded stored metadata only; no comprehensive field monitoring or semantic relevance claim."]
        if not connected:
            limitations.append("This selection is browse-only or its stream is disabled; no matching connector watch is active.")
        else:
            limitations.append("Only the listed connectors are monitored; other publishers, archives and full text are outside this watch.")
            if state == "limited":
                limitations.append("One or more configured checks are partial, unavailable, stale or have not succeeded.")
        result.append({"topic_id": "custom:" + topic if custom else topic,
                       "label": topic if custom else node["label"] if node else topic,
                       "matching_mode": "browse_only" if not terms else "descendant_terms" if node and node["kind"] == "authored_ml_group" else "literal_terms",
                       "terms": list(terms), "descendant_ids": descendants(topic) if node and node["kind"] == "authored_ml_group" else [],
                       "source_ids": connected, "status": state, "limitations": limitations})
    return result
