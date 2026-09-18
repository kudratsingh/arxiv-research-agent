"""Build a blinded, representative calibration pool from persisted episodes."""
from __future__ import annotations

import hashlib, json
from collections import defaultdict
from pathlib import Path
from typing import Any

from src.calibration.blinding import blind_item_id, leaked_identity_terms

POOL_REVISION = "1.1.0"
DEFAULT_OUTPUT = Path("outputs/calibration/representative-pool-1.1.0.json")


def _verdict(raw: Any) -> tuple[str, str | None]:
    if raw is None:
        return "abstain", "missing verdict"
    if isinstance(raw, bool):
        return ("passed" if raw else "failed"), None
    if isinstance(raw, str):
        value = raw.lower()
        if value in {"true", "supported", "covered", "pass", "passed"}: return "passed", None
        if value in {"false", "unsupported", "not_covered", "fail", "failed"}: return "failed", None
        return "abstain", raw
    if isinstance(raw, dict):
        reason = raw.get("reason") or raw.get("abstention_reason")
        for key in ("supported", "covered", "value", "verdict", "decision"):
            if key in raw:
                state, why = _verdict(raw[key])
                return state, str(reason or why) if state == "abstain" else None
        return "abstain", str(reason or "unreadable verdict")
    return "abstain", "unreadable verdict"


def _source(state: dict[str, Any], paper_id: str | None) -> tuple[str, str]:
    papers = {str(p.get("id")): p for p in state.get("papers", []) if isinstance(p, dict)}
    paper = papers.get(str(paper_id), {})
    abstract = str(paper.get("abstract") or "")
    chunks = []
    for entry in state.get("reader", {}).get("chunks", []) if isinstance(state.get("reader", {}).get("chunks"), list) else []:
        if isinstance(entry, dict) and str(entry.get("paper_id")) == str(paper_id): chunks.append(str(entry.get("text") or entry.get("chunk") or ""))
    return abstract, "\n\n".join(c for c in chunks if c)


def build_pool(campaign_id: str, root: Path, *, output: Path = DEFAULT_OUTPUT, seed: str = "judge-calibration-representative-1.1.0") -> Path:
    states = sorted(root.rglob("episode-state.json"))
    items: list[dict[str, Any]] = []
    for path in states:
        state = json.loads(path.read_text(encoding="utf-8"))
        if str(state.get("campaign_id")) != campaign_id: continue
        record = {}
        for candidate in (path.parent / "record.json", path.parent / "scores.json"):
            if candidate.exists():
                try: record = json.loads(candidate.read_text(encoding="utf-8")); break
                except json.JSONDecodeError: pass
        metrics = record.get("scores", record.get("metrics", {})) if isinstance(record, dict) else {}
        if not isinstance(metrics, dict): metrics = {}
        for metric, key, source_scope in (("faithfulness", "claims", "abstract+chunks"), ("completeness", "coverage", "abstract+chunks")):
            rows = metrics.get(metric, {}).get(key, []) if isinstance(metrics.get(metric), dict) else []
            for index, verdict in enumerate(rows if isinstance(rows, list) else []):
                if not isinstance(verdict, dict): verdict = {"verdict": verdict}
                state_name, reason = _verdict(verdict)
                paper_id = verdict.get("paper_id") or verdict.get("source_id")
                abstract, chunks = _source(state, str(paper_id) if paper_id else None)
                real_id = f"{path}:{metric}:{index}"
                blinded = blind_item_id(seed, real_id)
                item = {"item_id": blinded, "real_id": real_id, "slice": metric, "judge_verdict": state_name, "abstention_reason": reason, "source_scope": source_scope, "abstract": abstract, "chunks": chunks, "claim": verdict.get("claim") or verdict.get("topic") or verdict.get("text") or ""}
                rendered = json.dumps({k: item[k] for k in ("slice", "source_scope", "abstract", "chunks", "claim")}, sort_keys=True)
                forbidden = [str(state.get("arm_id") or ""), str(state.get("campaign_id") or "")]
                leaks = leaked_identity_terms(rendered, [x for x in forbidden if x])
                if leaks: raise ValueError(f"blinding leak in {blinded}: {leaks}")
                items.append(item)
    if not items: raise ValueError(f"no episode verdicts found for campaign {campaign_id}")
    buckets = defaultdict(int)
    for item in items: buckets[(item["slice"], item["judge_verdict"])] += 1
    for item in items: item.pop("real_id", None)
    payload = {"schema_kind": "representative-calibration-pool", "schema_version": "1.0.0", "suite_id": "judge-calibration-v1", "suite_revision": POOL_REVISION, "campaign_id": campaign_id, "blinding_seed_digest": "sha256:" + hashlib.sha256(seed.encode()).hexdigest(), "items": items, "strata_counts": {f"{a}:{b}": n for (a,b), n in sorted(buckets.items())}, "stress_set_separate": True}
    output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
