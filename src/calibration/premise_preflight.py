"""Offline, content-validated prereview binding. Never records authorization.

Review attribution is a reviewer declaration, not proof of a person's identity.
No labels are inferred, generated or sent in the checker request body.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import zlib
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_authorization import case_bindings
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_scope import limits_for

REVISION = "d5-premise-independent-preflight-v1"
CODE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ENVELOPE = {"jobs": 4, "messages": 4, "counts": 4, "usd": "0.60", "per_job_usd": "0.15"}


def pack_proof(proof: dict[str, Any]) -> str:
    raw = json.dumps(proof, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode()


def unpack_proof(value: Any) -> dict[str, Any]:
    """Keep the existing 32k input limit, with bounded local proof expansion."""
    try:
        if not isinstance(value, str) or len(value) > 24000:
            raise ValueError("missing_or_oversized_proof")
        decoder = zlib.decompressobj(wbits=31)
        raw = decoder.decompress(base64.b64decode(value, validate=True), 1_000_001)
        if len(raw) > 1_000_000 or not decoder.eof or decoder.unused_data:
            raise ValueError("oversized_or_incomplete_proof")
        proof = json.loads(raw)
        if not isinstance(proof, dict):
            raise ValueError("proof_object_required")
        return proof
    except (ValueError, TypeError, zlib.error) as exc:
        raise AdmissionError("premise_independent_preflight_required") from exc


def read_reviews(path: Path) -> dict[str, Any]:
    def distinct(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_review_json_key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if len(raw) > 1_000_000:
        raise AdmissionError("premise_review_file_too_large")
    value = json.loads(raw, object_pairs_hook=distinct)
    if not isinstance(value, dict):
        raise AdmissionError("premise_review_object_required")
    return value


def validate_reviews(packet: dict[str, Any], reviews: dict[str, Any]) -> dict[str, Any]:
    from src.calibration.question_premises import score, validate_packet

    validate_packet(packet)
    try:
        if reviews["revision"] != packet["revision"] or len(packet["probes"]) != 4:
            raise ValueError("four_item_review_revision_required")
        # Reuse the scorer's exact question/claim/evidence/prose bindings, duplicate
        # detection and attributed timestamp checks, without supplying any verdict.
        result = score(packet, {}, reviews)
        ids = [p["id"] for p in packet["probes"]]
        if {r["id"] for r in reviews["items"]} != set(ids):
            raise ValueError("all_four_independent_reviews_required")
        dispositions = set()
        for row in reviews["items"]:
            judgment = row["judgments"]
            if (
                row["provenance"] != "independent_human"
                or not isinstance(row["reviewer"], str)
                or not row["reviewer"].strip()
                or not isinstance(judgment["reason"], str)
                or not judgment["reason"].strip()
                or judgment["premise"]
                not in {"none", "supported_scored", "unsupported", "supported_unscored"}
                or judgment["expected_disposition"] not in {"accept", "reject"}
            ):
                raise ValueError("complete_independent_non_uncertain_review_required")
            reviewed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
            if reviewed.tzinfo is None or reviewed > datetime.now(UTC):
                raise ValueError("invalid_or_future_review_timestamp")
            expected = "accept" if judgment["premise"] in {"none", "supported_scored"} else "reject"
            if judgment["expected_disposition"] != expected:
                raise ValueError("review_disposition_conflicts_with_frozen_contract")
            dispositions.add(judgment["expected_disposition"])
        if dispositions != {"accept", "reject"}:
            raise ValueError("both_accept_and_reject_reviews_required")
        return {
            "worksheet_digest": _digest(reviews),
            "reviewed_items": result["counts"]["judged"],
            "accept": result["counts"]["acceptable"],
            "reject": result["counts"]["unacceptable"],
            "probe_ids": ids,
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise AdmissionError("premise_preflight_review_refused: " + str(exc)) from exc


def bind(
    packet: dict[str, Any], reviews: dict[str, Any], compiled: dict[str, Any], *, scope_id: str
) -> dict[str, Any]:
    """Produce exact prospective inputs/scope; no database, contact or grant."""
    checked = validate_reviews(packet, reviews)
    if not scope_id.startswith("d5-") or set(compiled) != set(checked["probe_ids"]):
        raise AdmissionError("premise_preflight_exact_scope_and_four_inputs_required")
    proof = {
        "revision": REVISION,
        "validator_sha256": CODE,
        "scope_id": scope_id,
        "packet": deepcopy(packet),
        "reviews": deepcopy(reviews),
        "worksheet_digest": checked["worksheet_digest"],
        "envelope": ENVELOPE,
    }
    bound = deepcopy(compiled)
    for probe in packet["probes"]:
        entry = bound[probe["id"]]
        if not entry["owner"].startswith("d5-") or entry["stage"] != "D":
            raise AdmissionError("premise_preflight_isolated_checker_principal_required")
        settings = entry["input"]["settings"]
        if any(
            settings.get(key) != expected
            for key, expected in {
                "d5_scope_id": scope_id,
                "d5_packet_digest": packet["packet_digest"],
                "d5_case_id": probe["id"],
                "d5_operation": "probe",
                "probe_wire_digest": probe["request_digest"],
                "d5_request_id": scope_id + "-" + probe["id"],
            }.items()
        ):
            raise AdmissionError("premise_preflight_input_request_binding_drift")
        settings["premise_calibration"]["pre_review_digest"] = checked["worksheet_digest"]
        settings["premise_calibration"]["preflight"] = pack_proof(proof)
        validate_bound_input(entry["input"])
        from src.calibration.question_premises import PremiseProbeAdapter
        from src.workspace.d5_freeze import restore_input

        # Reconstruct the transmitted body with the production implementation.
        # __init__ is deliberately not called: preflight has no client/DB path.
        renderer = PremiseProbeAdapter.__new__(PremiseProbeAdapter)
        renderer.inputs = restore_input(entry["input"])
        renderer.inputs.snapshot()  # Preserve the production sealed-input bound.
        if (
            renderer.inputs.model_id != packet["route"]["model"]
            or renderer._probe_wire() != probe["body"]
        ):
            raise AdmissionError("premise_preflight_transmitted_request_drift")
    cases = case_bindings(bound)
    scope = {
        "approved": False,
        "scope_id": scope_id,
        "packet_digest": packet["packet_digest"],
        "premise_preflight_revision": REVISION,
        "worksheet_digest": checked["worksheet_digest"],
        "validator_sha256": CODE,
        "members": sorted({e["owner"] for e in bound.values()}),
        "case_bindings": cases,
        "case_bindings_digest": _digest(cases),
        "limits": limits_for(next(iter(bound.values()))["input"]["settings"]),
        "contact_envelope": ENVELOPE,
    }
    return {
        "revision": REVISION,
        "status": "READY_FOR_APPROVAL",
        "approved": False,
        "reviews": checked,
        "scope": scope,
        "scope_digest": _digest(scope),
        "compiled": bound,
        "compiled_digest": _digest(bound),
        "new_provider_contacts": 0,
        "new_spend_usd": "0",
    }


def validate_bound_input(inputs: dict[str, Any]) -> None:
    settings = inputs["settings"]
    binding = settings.get("premise_calibration", {})
    proof = unpack_proof(binding.get("preflight"))
    if (
        proof.get("revision") != REVISION
        or proof.get("validator_sha256") != CODE
        or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != CODE
        or proof.get("envelope") != ENVELOPE
        or proof.get("scope_id") != settings.get("d5_scope_id")
        or proof["packet"]["packet_digest"] != settings.get("d5_packet_digest")
    ):
        raise AdmissionError("premise_preflight_scope_or_validator_drift")
    checked = validate_reviews(proof["packet"], proof["reviews"])
    if (
        proof.get("worksheet_digest") != checked["worksheet_digest"]
        or binding.get("pre_review_digest") != checked["worksheet_digest"]
    ):
        raise AdmissionError("premise_preflight_worksheet_digest_drift")
    probe = next(
        (p for p in proof["packet"]["probes"] if p["id"] == settings.get("d5_case_id")), None
    )
    if (
        probe is None
        or probe["request_digest"] != binding.get("request_digest")
        or probe["target"] != binding.get("target")
        or probe["request_digest"] != settings.get("probe_wire_digest")
        or settings.get("d5_operation") != "probe"
        or settings.get("d5_request_id") != proof["scope_id"] + "-" + probe["id"]
    ):
        raise AdmissionError("premise_preflight_exact_probe_drift")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        packet, reviews = read(args.packet), read_reviews(args.reviews)
        validate_reviews(packet, reviews)  # Refuse before even reading input templates.
        result = bind(packet, reviews, read(args.inputs), scope_id=args.scope_id)
        result["review_file_sha256"] = hashlib.sha256(args.reviews.read_bytes()).hexdigest()
        result["receipt_digest"] = _digest(result)
        write(args.out, result)
    except (AdmissionError, KeyError, TypeError, ValueError, OSError) as exc:
        refusal = {
            "revision": REVISION,
            "status": "HOLD",
            "approved": False,
            "reason": str(exc),
            "new_provider_contacts": 0,
            "new_spend_usd": "0",
            "scope_id": args.scope_id,
            "packet_file_sha256": hashlib.sha256(args.packet.read_bytes()).hexdigest()
            if args.packet.is_file()
            else None,
            "review_file_sha256": hashlib.sha256(args.reviews.read_bytes()).hexdigest()
            if args.reviews.is_file()
            else None,
        }
        write(args.out, refusal)
        print(json.dumps(refusal))
        raise SystemExit(2) from None
    print(
        json.dumps({k: result[k] for k in ("status", "scope_digest", "receipt_digest", "approved")})
    )


if __name__ == "__main__":
    main()
