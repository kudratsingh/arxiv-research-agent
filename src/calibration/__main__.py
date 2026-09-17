"""Command-line entry point for offline calibration packet workflows."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from src.calibration.packets import ingest_labels, render_report, write_packets
from src.calibration.suite import CALIBRATION_REGISTRY_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.calibration",
        description="Render blinded offline packets or report completed labels.",
    )
    parser.add_argument(
        "--registry-root", type=Path, default=CALIBRATION_REGISTRY_ROOT
    )
    sub = parser.add_subparsers(dest="command", required=True)
    packets = sub.add_parser("packets", help="write two expert packets and a dry-run file")
    packets.add_argument("--output", type=Path, required=True)
    report = sub.add_parser(
        "report", help="validate a filled packet or label file and print a per-slice report"
    )
    report.add_argument("--labels", type=Path, required=True)
    report.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "packets":
            paths = write_packets(args.output, args.registry_root)
            for path in paths:
                print(path)
            return 0
        rendered = render_report(ingest_labels(args.labels, args.registry_root))
        if args.output is None:
            print(rendered, end="")
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(args.output)
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        print(f"calibration input refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
