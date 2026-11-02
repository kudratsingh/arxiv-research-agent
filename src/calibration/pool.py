"""Build a blinded, representative calibration pool from persisted episodes."""

from __future__ import annotations

import hashlib
import json
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
        if value in {"true", "supported", "covered", "pass", "passed"}:
            return "passed", None
        if value in {"false", "unsupported", "not_covered", "fail", "failed"}:
            return "failed", None
        return "abstain", raw
    if isinstance(raw, dict):
        reason = raw.get("reason") or raw.get("abstention_reason")
        for key in ("supported", "covered", "value", "verdict", "decision"):
            if key in raw:
                state, why = _verdict(raw[key])
                return state, str(reason or why) if state == "abstain" else None
        return "abstain", str(reason or "unreadable verdict")
    return "abstain", "unreadable verdict"


def _source(
    state: dict[str, Any],
    paper_id: str | None,
    *,
    include_chunks: bool = True,
) -> tuple[str, str]:
    """Read the persisted paper and grouped ranked chunks, without re-ranking.

    Legacy list-shaped fixtures remain readable, but current campaign snapshots
    use ``reader.chunks[paper_id]``. Chunks are shown only for a metric whose
    provenance says it consumed them: retained text is not proof it was judged.
    """
    papers = {str(p.get("id")): p for p in state.get("papers", []) if isinstance(p, dict)}
    paper = papers.get(str(paper_id), {})
    abstract = str(paper.get("abstract") or "")
    reader = state.get("reader")
    raw_chunks = reader.get("chunks") if isinstance(reader, dict) else None
    chunks: list[str] = []
    if include_chunks:
        if isinstance(raw_chunks, dict):
            entries = raw_chunks.get(str(paper_id), [])
        else:
            entries = (
                [
                    entry
                    for entry in raw_chunks
                    if isinstance(entry, dict) and str(entry.get("paper_id")) == str(paper_id)
                ]
                if isinstance(raw_chunks, list)
                else []
            )
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict):
                chunks.append(str(entry.get("text") or entry.get("chunk") or ""))
    return abstract, "\n\n".join(c for c in chunks if c)


def _metrics(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prefer the actual writer's filename/nesting, retaining legacy imports.

    ``scores.json`` from the campaign is a ledger receipt and has no metric
    judgments. Falling through to it must never conceal an invalid real record.
    """
    for filename in ("episode-record.json", "record.json", "scores.json"):
        candidate = path.parent / filename
        if not candidate.exists():
            continue
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            if filename == "episode-record.json":
                raise ValueError(f"invalid emitted episode record: {candidate}") from exc
            continue
        if not isinstance(record, dict):
            return {}, {}
        scores = record.get("scores", record)
        if not isinstance(scores, dict):
            return {}, {}
        metrics = scores.get("metrics", scores)
        return (metrics if isinstance(metrics, dict) else {}), scores
    return {}, {}


def _report(state: dict[str, Any]) -> str:
    report = state.get("report")
    return str(report.get("text") or "") if isinstance(report, dict) else ""


def _material(
    state: dict[str, Any],
    metric: str,
    entry: dict[str, Any],
    verdict: dict[str, Any],
) -> dict[str, Any]:
    """Keep the substrate used by each rubric distinct and provenance labelled."""
    if metric == "completeness":
        report = _report(state)
        raw_report = state.get("report")
        retained = isinstance(raw_report, dict) and "text" in raw_report
        return {
            "source_scope": "report",
            "abstract": "",
            "chunks": "",
            "report": report,
            "material_complete": retained,
            "material_gap": None if retained else "report_text_not_retained",
        }
    if metric == "retrieval_recall":
        papers = [
            {
                "index": index,
                "paper_id": str(paper.get("id") or ""),
                "title": str(paper.get("title") or ""),
                "abstract": str(paper.get("abstract") or ""),
            }
            for index, paper in enumerate(state.get("papers", []))
            if isinstance(paper, dict)
        ]
        return {
            "source_scope": "retrieved_titles_and_abstracts",
            "abstract": "",
            "chunks": "",
            "papers": papers,
            "material_complete": all(bool(p["title"]) for p in papers),
            "material_gap": None,
        }
    scope = str(entry.get("source_scope") or "unrecorded")
    paper_id = verdict.get("paper_id") or verdict.get("source_id")
    abstract, chunks = _source(
        state, str(paper_id) if paper_id else None, include_chunks=scope == "abstract_and_chunks"
    )
    papers_by_id = {str(p.get("id")): p for p in state.get("papers", []) if isinstance(p, dict)}
    paper = papers_by_id.get(str(paper_id), {})
    gap = None
    if not paper_id or not paper:
        gap = str(verdict.get("resolution") or "source_unavailable")
    elif scope == "unrecorded":
        gap = "judge_source_scope_not_recorded"
    elif not abstract and not chunks:
        gap = "source_text_not_retained"
    elif scope == "abstract_and_chunks":
        reader = state.get("reader")
        if isinstance(reader, dict) and reader.get("chunk_text_retained") is False:
            gap = "judged_chunk_text_not_retained"
    # The dossier-wide scope may contain another paper's chunks. Do not invent
    # missing per-paper chunks, or attach an unresolved claim to a random source.
    return {
        "source_scope": scope,
        "abstract": abstract,
        "chunks": chunks,
        "paper_id": str(paper_id) if paper_id else None,
        "source_title": str(paper.get("title") or ""),
        "cite": str(verdict.get("cite") or ""),
        "material_complete": gap is None,
        "material_gap": gap,
    }


def build_pool(
    campaign_id: str,
    root: Path,
    *,
    output: Path = DEFAULT_OUTPUT,
    seed: str = "judge-calibration-representative-1.1.0",
) -> Path:
    states = sorted(root.rglob("episode-state.json"))
    items: list[dict[str, Any]] = []
    unscored: list[dict[str, Any]] = []
    for path in states:
        state = json.loads(path.read_text(encoding="utf-8"))
        if str(state.get("campaign_id")) != campaign_id:
            continue
        metrics, scores = _metrics(path)
        for metric, key in (
            ("faithfulness", "claims"),
            ("completeness", "coverage"),
            ("retrieval_recall", "coverage"),
        ):
            entry = metrics.get(metric)
            rows = entry.get(key, []) if isinstance(entry, dict) else []
            if metric in metrics and (
                entry is None
                or (isinstance(entry, dict) and entry.get("score", "present") is None and not rows)
            ):
                failures = scores.get("judge_failure_reasons")
                reason = (
                    entry.get("reason")
                    if isinstance(entry, dict)
                    else failures.get(metric)
                    if isinstance(failures, dict)
                    else None
                )
                unscored.append(
                    {
                        "episode_id": blind_item_id(
                            seed, str(state.get("run_id") or path.parent.name)
                        ),
                        "metric": metric,
                        "score": None,
                        "verdict": "abstain",
                        "reason": reason or "no_per_item_verdicts",
                    }
                )
            for index, row in enumerate(rows if isinstance(rows, list) else []):
                verdict = row if isinstance(row, dict) else {"verdict": row}
                state_name, reason = _verdict(verdict)
                episode_identity = str(
                    state.get("run_id") or state.get("episode_key") or path.relative_to(root)
                )
                real_id = f"{campaign_id}:{episode_identity}:{metric}:{index}"
                blinded = blind_item_id(seed, real_id)
                claim = verdict.get("claim") or verdict.get("topic") or verdict.get("text") or ""
                item: dict[str, Any] = {
                    "item_id": blinded,
                    "real_id": real_id,
                    "slice": metric,
                    "judge_verdict": state_name,
                    "abstention_reason": reason,
                    "claim": claim,
                    "label_type": {
                        "faithfulness": "claim_support",
                        "completeness": "rubric_coverage",
                        "retrieval_recall": "retrieval_recall",
                    }[metric],
                    "judge_provenance": entry.get("judge") if isinstance(entry, dict) else None,
                    **_material(state, metric, entry if isinstance(entry, dict) else {}, verdict),
                }
                rendered = json.dumps(
                    {
                        k: value
                        for k, value in item.items()
                        if k
                        not in {
                            "item_id",
                            "real_id",
                            "judge_verdict",
                            "abstention_reason",
                            "judge_provenance",
                        }
                    },
                    sort_keys=True,
                )
                # Bare arm "A" matches the English article "a". Scan qualified
                # arm identities rather than rejecting ordinary scientific text.
                arm = str(state.get("arm_id") or "")
                forbidden = (
                    [
                        f"arm-{arm}",
                        f"arm {arm}",
                        str(state.get("campaign_id") or ""),
                        str(state.get("run_id") or ""),
                    ]
                    if arm
                    else [str(state.get("campaign_id") or "")]
                )
                leaks = leaked_identity_terms(rendered, [x for x in forbidden if x])
                if leaks:
                    raise ValueError(f"blinding leak in {blinded}: {leaks}")
                items.append(item)
    if not items and not unscored:
        raise ValueError(f"no episode verdicts found for campaign {campaign_id}")
    buckets: defaultdict[tuple[str, str], int] = defaultdict(int)
    for item in items:
        buckets[(str(item["slice"]), str(item["judge_verdict"]))] += 1
    for item in items:
        item.pop("real_id", None)
    payload = {
        "schema_kind": "representative-calibration-pool",
        "schema_version": "1.0.0",
        "suite_id": "judge-calibration-v1",
        "suite_revision": POOL_REVISION,
        "campaign_id": campaign_id,
        "blinding_seed_digest": "sha256:" + hashlib.sha256(seed.encode()).hexdigest(),
        "items": items,
        "unscored_metrics": unscored,
        "handling": "EVALUATOR ONLY: includes judge verdicts and campaign identity; render blinded labeling packets before expert use.",
        "strata_counts": {f"{a}:{b}": n for (a, b), n in sorted(buckets.items())},
        "stress_set_separate": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output
