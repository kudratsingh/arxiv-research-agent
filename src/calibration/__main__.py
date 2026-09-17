"""Command-line entry point for the offline calibration packet workflow.

Two verbs and no third: ``packets`` renders a blinded set for offline
labeling, ``ingest`` takes a completed one back and reports agreement.
Neither calls a model, a provider or the network, and neither starts a
labeling campaign — see
``docs/agent-engineering/14-judge-calibration-protocol.md`` §12.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from src.calibration.packets import (
    DEFAULT_OUTPUT_ROOT,
    ingest_labels,
    render_report,
    write_packet_set,
)
from src.calibration.suite import CALIBRATION_REGISTRY_ROOT


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.calibration",
        description="Render blinded offline labeling packets, or ingest completed labels.",
    )
    parser.add_argument("--registry-root", type=Path, default=CALIBRATION_REGISTRY_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    packets = sub.add_parser(
        "packets",
        help="write one blinded packet set (two packets plus the evaluator-only manifest)",
    )
    packets.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="directory the packet set is created in (default: outputs/calibration)",
    )
    packets.add_argument(
        "--seed",
        type=int,
        default=None,
        help="presentation seed (default: the registered blinding plan's seed)",
    )

    ingest = sub.add_parser(
        "ingest",
        help="un-blind a completed label file via its manifest and report agreement",
    )
    ingest.add_argument("labels", type=Path, help="the completed packet or label file")
    ingest.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="the packet set's manifest.json — the blinding key",
    )
    ingest.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the report here instead of stdout",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    """Run one verb.

    Args:
        argv: Arguments, or ``None`` to read ``sys.argv``.

    Returns:
        ``0`` on success, ``2`` when an input is refused. A refusal is
        loud on purpose: a partially labelled packet that scored anyway
        would be a measurement nobody could reproduce.
    """
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "packets":
            for path in write_packet_set(args.output, seed=args.seed, root=args.registry_root):
                print(path)
            return 0
        rendered = render_report(
            ingest_labels(args.labels, args.manifest, root=args.registry_root)
        )
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
