"""Disposable grading demo, not provider execution or independent human review.

Run with Python stdin from the worktree root. The original observed run and
blank worksheet are preserved; every supplied label below is synthetic.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from src.workspace import d5_reviews as d


def filled(blank: dict) -> dict:
    result = deepcopy(blank)
    for item in result["items"]:
        item.update(
            reviewer="synthetic-grading-demo",
            reviewer_role="synthetic",
            provenance="synthetic",
            reviewed_at=datetime.now(UTC).isoformat(),
            method="Scripted software fixture, no independent human judgment",
        )
        if item["kind"] in {"claim", "probe"}:
            item["judgments"].update(
                support="unsupported" if item["kind"] == "probe" else "supported",
                atomic=True,
                qualifications_retained=True,
            )
        elif item["kind"] == "case":
            item["judgments"].update(
                complete=True,
                material_omissions=False,
                comparison_compatible=True,
                counterevidence_handled="not_applicable",
                appropriate_abstention=True,
                prose_support="procedural_only",
            )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True)  # Refuse replacing earlier evidence.
    before = hashlib.sha256(args.results.read_bytes()).hexdigest()
    packet = d.read(args.packet)
    env = {**os.environ, "ANTHROPIC_API_KEY": "local-preview-disabled", "WORKSPACE_D5_OFFLINE": "1"}

    def run(verb: str, *options: str) -> None:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "src.workspace.d5_reviews",
                verb,
                "--packet",
                str(args.packet),
                "--results",
                str(args.results),
                *options,
            ],
            env=env,
            check=True,
        )

    run("export", "--out", str(args.out / "owner-blank.json"))
    run(
        "score",
        "--store",
        str(args.out / "real-reviews-empty"),
        "--out",
        str(args.out / "unreviewed"),
    )
    blank = d.read(args.out / "owner-blank.json")
    synthetic = filled(blank)
    d.write_new(args.out / "synthetic-review.json", synthetic)
    run("validate", "--review", str(args.out / "synthetic-review.json"))
    for _ in range(2):
        run(
            "import",
            "--review",
            str(args.out / "synthetic-review.json"),
            "--store",
            str(args.out / "synthetic-store"),
        )
    run(
        "score",
        "--store",
        str(args.out / "synthetic-store"),
        "--out",
        str(args.out / "synthetic-graded"),
    )
    negative = deepcopy(synthetic)
    target = next(
        i for i in negative["items"] if i["kind"] == "claim" and i["case_id"] == "learn-method"
    )
    target["judgments"]["support"] = "unsupported"
    d.write_new(args.out / "synthetic-negative.json", negative)
    run(
        "import",
        "--review",
        str(args.out / "synthetic-negative.json"),
        "--store",
        str(args.out / "negative-store"),
    )
    run(
        "score",
        "--store",
        str(args.out / "negative-store"),
        "--out",
        str(args.out / "synthetic-failed"),
    )
    assert hashlib.sha256(args.results.read_bytes()).hexdigest() == before
    assert all(i["reviewer"] is None for i in d.read(args.out / "owner-blank.json")["items"])
    report = d.read(args.out / "synthetic-graded/results.json")
    failed = d.read(args.out / "synthetic-failed/results.json")
    assert report["quality"]["basis"] == "synthetic" and failed["quality"]["outcome"] == "FAIL"
    d.write_new(
        args.out / "proof.json",
        {
            "format": "d5-synthetic-review-demo-v1",
            "packet_digest": packet["packet_digest"],
            "original_result_sha256": before,
            "raw_results_unchanged": True,
            "actual_owner_worksheet_blank": True,
            "synthetic_outcome": report["quality"]["outcome"],
            "synthetic_negative_outcome": failed["quality"]["outcome"],
            "provider_contacts": 0,
            "paid_authorization_created": False,
        },
    )


if __name__ == "__main__":
    main()
