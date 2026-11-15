"""Complete prospective v16 gate using production controls and mock-only storage.

Synthetic authority and usage are confined to disposable marked Postgres. The
legacy campaign gate remains separate; this never contacts a provider.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from src.workspace.admission import AdmissionError


def main() -> None:
    from src.workspace.d5_benchmark import write
    from src.workspace.d5_campaign import run
    from src.workspace.d5_campaign_report import markdown
    from src.workspace.d5_keyed_transport import KeyedCampaignTransport
    from tests.d5_campaign_gate import storage
    from tests.d5_capacity_gate import export_rows
    from tests.test_workspace_d5_v16_integration import setup_keyed

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--union-safe", action="store_true")
    args = parser.parse_args()
    if (
        os.environ.get("ANTHROPIC_API_KEY") != "local-preview-disabled"
        or os.environ.get("WORKSPACE_D5_OFFLINE") != "1"
    ):
        raise AdmissionError("keyed_gate_offline_only")
    if args.out.exists():
        raise AdmissionError("keyed_gate_output_must_be_new")
    args.out.mkdir(parents=True)
    os.environ["D5_TEST_EVIDENCE_DIR"] = str(args.out / "ledger")
    with storage() as store:
        try:
            packet = asyncio.run(setup_keyed(store, authorize=not args.union_safe))
            if args.union_safe:
                from src.workspace.d5_campaign_operator import authorize_fixture
                from src.workspace.d5_campaign_v16_packet import capture, freeze

                packet = freeze(store, capture(store, packet["program_id"]), union_safe=True)
                authorize_fixture(store, packet)
            transports = []

            def transport(key):
                value = KeyedCampaignTransport(key, repair_all=True, scenario="long_narratives")
                transports.append(value)
                return value

            report = asyncio.run(
                run(
                    store,
                    packet,
                    offline=True,
                    transport_factory=transport,
                    progress=lambda row: print(row["case_id"], row["state"], flush=True),
                )
            )
            if args.union_safe:
                import hashlib
                import json

                from src.workspace.provider_schema_compat import guard

                receipts = []
                for handler in transports:
                    for contact, raw in zip(handler.contacts, handler.request_bodies, strict=True):
                        if contact[0].endswith("/messages"):
                            receipts.append(
                                {
                                    "case_id": handler.key,
                                    "raw_body_sha256": hashlib.sha256(raw).hexdigest(),
                                    **guard(json.loads(raw)),
                                }
                            )
                assert len(receipts) == 44
                write(
                    args.out / "PROVIDER-COMPATIBILITY-RECEIPTS.json.gz",
                    {"synthetic": True, "remote_acceptance": "UNMEASURED", "receipts": receipts},
                )
            write(args.out / "packet.json.gz", packet)
            write(args.out / "results.json.gz", report)
            (args.out / "REPORT.md").write_text(markdown(report))
            assert report["stop"] is None, report["stop"]
            assert len(report["outcomes"]) == 14
            assert (
                report["accounting"]["new_scope"]["messages"]
                == report["accounting"]["new_scope"]["counts"]
                == 44
            )
            assert report["accounting"]["cumulative"]["funded_programme_jobs"] == 51
            assert report["accounting"]["cumulative"]["messages"] == 115
            assert report["accounting"]["cumulative"]["counts"] == 140
            assert report["accounting"]["retained_hold_usd"] == "0.875066"
            assert report["human_labels"] is None and report["human_qualification"] is False
            assert all(case["assessment_binding"]["status"] == "bound" for case in report["cases"])
            print(
                "v16 protected mock gate:14 jobs/44 Messages/44 paired counts; quality unqualified; real contacts0"
            )
        finally:
            export_rows(store, "v16-complete-gate")


if __name__ == "__main__":
    main()
