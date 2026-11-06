"""Versioned review sidecars. No database, approval, provider or raw-output writes.

An import is append-only and bound to the original observed run. Adjudication
must name the active predecessor imports; a new scorer never relabels old jobs.
"""

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import os
import platform
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.workspace.admission import AdmissionError, _digest

REVIEW_FORMAT = "d5-human-review-v1"
SCORER_VERSION = "d5-reviewed-quality-v1"
Support = Literal["supported", "unsupported", "insufficient", "unreviewable"]
Applicable = bool | Literal["not_applicable"] | None


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Judgments(Strict):
    support: Support | None = None
    atomic: bool | None = None
    qualifications_retained: bool | None = None
    complete: bool | None = None
    material_omissions: bool | None = None
    comparison_compatible: Applicable = None
    counterevidence_handled: Applicable = None
    appropriate_abstention: Applicable = None
    prose_support: Support | Literal["procedural_only"] | None = None
    usefulness: Literal["useful", "maybe", "irrelevant"] | None = None
    relevance: Literal["relevant", "irrelevant", "insufficient", "unreviewable"] | None = None
    known_reference: bool | None = None


FIELDS = {
    "claim": {"support", "atomic", "qualifications_retained"},
    "probe": {"support", "atomic", "qualifications_retained"},
    "case": {
        "complete",
        "material_omissions",
        "comparison_compatible",
        "counterevidence_handled",
        "appropriate_abstention",
        "prose_support",
        "usefulness",
    },
    "retrieval": {"relevance", "known_reference"},
}


class ReviewItem(Strict):
    target: str
    kind: Literal["claim", "probe", "case", "retrieval"]
    case_id: str
    job_id: str
    binding: str
    observed: dict[str, Any]
    judgments: Judgments = Field(default_factory=Judgments)
    reviewer_role: Literal["owner", "expert", "synthetic"] | None = None
    reviewer: str | None = None
    reviewed_at: str | None = None
    provenance: Literal["independent_human", "machine_assisted_human", "synthetic"] | None = None
    method: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def attribution(self) -> ReviewItem:
        labels = self.judgments.model_dump(exclude_none=True)
        if set(labels) - FIELDS[self.kind]:
            raise ValueError("judgment_not_applicable_to_item_kind")
        if labels:
            if self.reviewer_role is None or (self.provenance == "synthetic") != (
                self.reviewer_role == "synthetic"
            ):
                raise ValueError("review_role_provenance_required")
            if labels.get("usefulness") is not None and self.reviewer_role not in {
                "owner",
                "synthetic",
            }:
                raise ValueError("owner_usefulness_requires_owner_review")
            if (
                not self.reviewer
                or not self.reviewer.strip()
                or not self.method
                or not self.method.strip()
                or not self.provenance
                or not self.reviewed_at
            ):
                raise ValueError("review_attribution_required")
            when = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
            if when.tzinfo is None:
                raise ValueError("review_timestamp_timezone_required")
        return self


class Adjudication(Strict):
    supersedes: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)


class ReviewFile(Strict):
    format: Literal["d5-human-review-v1"] = "d5-human-review-v1"
    review_revision: int = Field(default=1, ge=1)
    packet_digest: str
    run_id: str
    result_digest: str
    instructions: str
    items: list[ReviewItem]
    adjudication: Adjudication | None = None


def read(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise AdmissionError("d5_review_duplicate_json_key")
            value[key] = item
        return value

    value = json.loads(
        gzip.decompress(raw) if path.suffix == ".gz" else raw, object_pairs_hook=unique
    )
    if not isinstance(value, dict):
        raise AdmissionError("d5_review_object_required")
    return value


def write_new(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, suffix=".pending", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(gzip.compress(raw, mtime=0) if path.suffix == ".gz" else raw)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)  # Atomic publish; never replaces an existing artifact.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def identities(packet: dict[str, Any], results: dict[str, Any]) -> dict[str, str]:
    if packet.get("packet_digest") != _digest(
        {k: v for k, v in packet.items() if k != "packet_digest"}
    ):
        raise AdmissionError("d5_review_packet_integrity_failed")
    if results.get("packet_digest") != packet["packet_digest"]:
        raise AdmissionError("d5_review_original_packet_mismatch")
    jobs = results["raw_results"]
    ids = [v.get("id") for v in jobs.values()]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
        raise AdmissionError("d5_review_duplicate_or_missing_job_identity")
    if any(
        v.get("case_id") != key or v.get("packet_digest") != packet["packet_digest"]
        for key, v in jobs.items()
    ):
        raise AdmissionError("d5_review_cross_case_job_identity")
    result_digest = _digest(results)
    return {
        "packet_digest": packet["packet_digest"],
        "result_digest": result_digest,
        "run_id": "d5-run-"
        + _digest(
            {
                "packet": packet["packet_digest"],
                "jobs": {k: v["id"] for k, v in results["raw_results"].items()},
            }
        )[:32],
    }


def catalog(packet: dict[str, Any], results: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Observed assertions/prose, not guessed future outputs or proposed truth labels."""
    identities(packet, results)
    found: dict[str, dict[str, Any]] = {}

    def add(
        kind: str, case_id: str, job: dict[str, Any], key: str, observed: dict[str, Any]
    ) -> None:
        target = _digest([kind, case_id, job["id"], key])
        item = {
            "target": target,
            "kind": kind,
            "case_id": case_id,
            "job_id": job["id"],
            "observed": observed,
        }
        item["binding"] = _digest(item)
        found[target] = item

    for case in packet["cases"]:
        job = results["raw_results"].get(case["id"])
        if not job:
            continue
        steps = [s for s in job.get("steps", []) if s["stage"] in {"draft", "repair"}]
        output = steps[-1]["output"] if steps else {}
        units = (case.get("sealed") or {}).get("units", {})
        output_digest = _digest(output)
        add(
            "case",
            case["id"],
            job,
            "case",
            {
                "question": case["question"],
                "cohort": case["cohort"],
                "output": output,
                "output_digest": output_digest,
                "evidence_digest": _digest(units),
            },
        )
        claim_ids: set[str] = set()
        for claim in output.get("claims", []):
            cid = claim.get("claim_id")
            if not isinstance(cid, str) or cid in claim_ids:
                raise AdmissionError("d5_review_malformed_observed_claim_ids")
            claim_ids.add(cid)
            add(
                "claim",
                case["id"],
                job,
                cid,
                {
                    "claim_id": cid,
                    "claim": claim,
                    "output_digest": output_digest,
                    "evidence": {h: units.get(h) for h in claim.get("handles", [])},
                },
            )
        for work in packet["corpus"]:
            add(
                "retrieval",
                case["id"],
                job,
                work["work_id"],
                {
                    "work": work,
                    "ranking": case["ranking"],
                    "edition": case["edition"],
                    "cohort": case["cohort"],
                },
            )
    for probe in packet["probes"]:
        job = results["raw_results"].get(probe["id"])
        if not job or not job.get("steps"):
            continue
        for claim in json.loads(probe["wire"]["messages"][0]["content"])["draft"]["claims"]:
            add(
                "probe",
                probe["id"],
                job,
                claim["claim_id"],
                {
                    "claim_id": claim["claim_id"],
                    "claim": claim,
                    "output_digest": _digest(job["steps"][-1]["output"]),
                    "evidence": claim.get("evidence", []),
                },
            )
    return found


def worksheet(
    packet: dict[str, Any], results: dict[str, Any], *, retrieval: bool = False
) -> dict[str, Any]:
    items = [
        ReviewItem(**i).model_dump()
        for i in catalog(packet, results).values()
        if retrieval or i["kind"] != "retrieval"
    ]
    return ReviewFile.model_validate(
        {
            **identities(packet, results),
            "instructions": "Supply only judgments you performed. Reviewer, timezone timestamp, provenance and method are required for any label. Null means missing. Synthetic labels are software fixtures, never independent human evidence. Retrieval is optional; export with --retrieval for the entire frozen pool.",
            "items": items,
        }
    ).model_dump()


def validate(packet: dict[str, Any], results: dict[str, Any], value: dict[str, Any]) -> ReviewFile:
    review = ReviewFile.model_validate(value)
    for key, expected_identity in identities(packet, results).items():
        if getattr(review, key) != expected_identity:
            raise AdmissionError("d5_review_stale_" + key)
    expected_items = catalog(packet, results)
    seen: set[str] = set()
    for item in review.items:
        if item.target in seen:
            raise AdmissionError("d5_review_duplicate_target")
        seen.add(item.target)
        if item.target not in expected_items:
            raise AdmissionError("d5_review_unknown_target")
        expected = expected_items[item.target]
        if any(getattr(item, k) != expected[k] for k in expected):
            raise AdmissionError("d5_review_observed_binding_mismatch")
    return review


def _state(
    directory: Path, packet: dict[str, Any], results: dict[str, Any]
) -> tuple[dict[str, ReviewItem], list[str], dict[str, str], dict[str, int]]:
    active: dict[str, ReviewItem] = {}
    origins: dict[str, str] = {}
    revisions: dict[str, int] = {}
    digests: list[str] = []
    for path in sorted((directory / "imports").glob("*.json")):
        receipt = read(path)
        if receipt.get("format") != REVIEW_FORMAT or any(
            receipt.get(k) != v for k, v in identities(packet, results).items()
        ):
            raise AdmissionError("d5_review_import_identity_failed")
        review = validate(packet, results, receipt["review"])
        digest = _digest(review.model_dump())
        if receipt["review_digest"] != digest or receipt["receipt_digest"] != _digest(
            {k: v for k, v in receipt.items() if k != "receipt_digest"}
        ):
            raise AdmissionError("d5_review_import_integrity_failed")
        _merge(active, origins, revisions, review, digest, digests)
        digests.append(digest)
    return active, digests, origins, revisions


def _merge(
    active: dict[str, ReviewItem],
    origins: dict[str, str],
    revisions: dict[str, int],
    review: ReviewFile,
    digest: str,
    previous: list[str],
) -> None:
    supersedes = review.adjudication.supersedes if review.adjudication else []
    if any(d not in previous for d in supersedes):
        raise AdmissionError("d5_review_unknown_adjudication_parent")
    for item in review.items:
        if not item.judgments.model_dump(exclude_none=True):
            continue
        if (
            item.target in active
            and active[item.target] != item
            and (
                origins[item.target] not in supersedes
                or review.review_revision <= revisions[item.target]
            )
        ):
            raise AdmissionError("d5_review_conflict_requires_adjudication")
        active[item.target], origins[item.target], revisions[item.target] = (
            item,
            digest,
            review.review_revision,
        )


def imported(
    directory: Path, packet: dict[str, Any], results: dict[str, Any]
) -> tuple[dict[str, ReviewItem], list[str]]:
    active, digests, _, _ = _state(directory, packet, results)
    return active, digests


def import_review(
    directory: Path, packet: dict[str, Any], results: dict[str, Any], value: dict[str, Any]
) -> dict[str, Any]:
    review = validate(packet, results, value)
    digest = _digest(review.model_dump())
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        active, previous, origins, revisions = _state(directory, packet, results)
        if digest in previous:
            return {"review_digest": digest, "idempotent": True, "imported": False}
        _merge(active, origins, revisions, review, digest, previous)
        receipt = {
            "format": REVIEW_FORMAT,
            **identities(packet, results),
            "review_digest": digest,
            "review": review.model_dump(),
        }
        receipt["receipt_digest"] = _digest(receipt)
        write_new(directory / "imports" / f"{len(previous):06d}-{digest}.json", receipt)
        return {"review_digest": digest, "idempotent": False, "imported": True}


def scorer_binding() -> dict[str, str]:
    root = Path(__file__).parent
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in (
            "d5_reviews.py",
            "d5_review_scoring.py",
            "d5_scoring.py",
            "grounding.py",
            "assistance_contract.py",
            "material.py",
            "admission.py",
        )
    }


def recompute(
    packet: dict[str, Any],
    results: dict[str, Any],
    records: dict[str, ReviewItem],
    review_digests: list[str],
) -> dict[str, Any]:
    from src.workspace.d5_review_scoring import grade_report
    from src.workspace.d5_scoring import score_case
    from src.workspace.material import SourceMaterial, SourceSpan

    if any(k != item.target for k, item in records.items()):
        raise AdmissionError("d5_review_record_key_mismatch")
    validate(
        packet,
        results,
        {**worksheet(packet, results), "items": [i.model_dump() for i in records.values()]},
    )
    materials = tuple(
        SourceMaterial(**{**m, "spans": tuple(SourceSpan(**s) for s in m["spans"])})
        for m in packet["materials"]
    )
    mechanical = {
        **results,
        "cases": [
            score_case(c, results["raw_results"].get(c["id"]), materials) for c in packet["cases"]
        ],
    }
    report = grade_report(packet, mechanical, records)
    receipt = {
        "format": "d5-analysis-receipt-v1",
        **identities(packet, results),
        "scorer_version": SCORER_VERSION,
        "runtime_python": platform.python_version(),
        "scorer_code": scorer_binding(),
        "review_digests": review_digests,
        "review_set_digest": _digest({k: v.model_dump() for k, v in records.items()}),
        "report_version": SCORER_VERSION,
        "scoring_policy": packet["scoring"],
        "accounting_digest": _digest(results["accounting"]),
    }
    receipt["analysis_digest"] = _digest(receipt)
    report["analysis_receipt"] = receipt
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["export", "validate", "import", "score"])
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--retrieval", action="store_true")
    args = parser.parse_args()
    packet, results = read(args.packet), read(args.results)
    identities(packet, results)
    if args.verb == "export":
        if args.out is None:
            parser.error("export requires --out")
        write_new(args.out, worksheet(packet, results, retrieval=args.retrieval))
    elif args.verb in {"validate", "import"}:
        if args.review is None:
            parser.error("validate/import require --review")
        review = read(args.review)
        value = validate(packet, results, review)
        if args.verb == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "review_digest": _digest(value.model_dump()),
                        "labels": sum(
                            bool(i.judgments.model_dump(exclude_none=True)) for i in value.items
                        ),
                    }
                )
            )
        else:
            if args.store is None:
                parser.error("import requires --store")
            print(json.dumps(import_review(args.store, packet, results, review)))
    else:
        if args.store is None or args.out is None:
            parser.error("score requires --store and --out (new directory)")
        records, digests = imported(args.store, packet, results)
        report = recompute(packet, results, records, digests)
        from html import escape

        from src.workspace.d5_scoring import markdown

        write_new(args.out / "results.json", report)
        write_new(args.out / "analysis-receipt.json", report["analysis_receipt"])
        for name, body in [
            ("REPORT.md", markdown(report)),
            (
                "index.html",
                "<!doctype html><meta charset=utf-8><title>D5 reviewed quality</title><pre>"
                + escape(markdown(report))
                + "</pre>",
            ),
        ]:
            with (args.out / name).open("x") as f:
                f.write(body)
        print(
            json.dumps(
                {
                    "report": str(args.out),
                    "outcome": report["quality"]["outcome"],
                    "basis": report["quality"]["basis"],
                    "provider_contacts": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
