"""Blinded follow-up-premise diagnostics. Build/score are offline, never approval.

Expected variants and matched keys are evaluator-only proposed annotations.
Independent reviewers label the blank worksheet before any checker verdict.
The checker sees one question variant in each independent production context.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from anthropic import transform_schema

from src.calibration.blinding import blind_item_id, leaked_identity_terms
from src.workspace.admission import AdmissionError, _digest
from src.workspace.assistance import Checks
from src.workspace.d5_adapter import D5ProbeAdapter, prepare_input, qualification_producer
from src.workspace.d5_benchmark import read, write
from src.workspace.d5_operations import ROUTES, wire

REVISION = "d5-followup-premise-calibration-v1"
VARIANTS = ("neutral", "scored_premise", "unsupported_premise", "supported_unscored")
MODEL = deepcopy(ROUTES["check_recheck_probe"])
_CODE = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def build(
    seeds: list[dict[str, Any]], *, seed: int, salt: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Vary only the target question; keep draft, slot and exact citations fixed."""
    if not salt or len({s["key"] for s in seeds}) != len(seeds):
        raise ValueError("distinct_matched_sets_and_private_salt_required")
    probes = []
    key = {}
    review = []
    for source in seeds:
        context = source["context"]
        slot = source["slot"]
        questions = context["unscored_prose"]["questions"]
        if type(slot) is not int or not 0 <= slot < len(questions):
            raise ValueError("existing_question_slot_required")
        cid = context["draft"]["claims"][0]["claim_id"]
        questions_by_variant = {
            "neutral": "What further evidence, if any, would clarify the selected claims and their limitations?",
            "scored_premise": f"Given cited and scored claim {cid}, what qualifications apply, if any?",
            "unsupported_premise": source["unsupported_question"],
            "supported_unscored": source["unscored_supported_question"],
        }
        for variant in VARIANTS:
            identifier = blind_item_id(salt, source["key"] + ":" + variant)
            # No set, variant, reference label or archived outcome enters payload.
            value = {k: deepcopy(context[k]) for k in ("draft", "claim_inputs", "unscored_prose")}
            value.update(
                phase="check",
                role="checker",
                sealed_request={
                    "schema_revision": context["sealed_request"]["schema_revision"],
                    "private_context": False,
                },
                output_schema=transform_schema(Checks),
            )
            value["unscored_prose"]["questions"][slot] = questions_by_variant[variant]
            body = wire(value, ROUTES)
            forbidden = [
                *VARIANTS,
                "expected_label",
                "matching_key",
                "variant_name",
                "fresh_calibration",
                source["key"],
            ]
            if leaked_identity_terms(json.dumps(body), forbidden):
                raise ValueError("calibration_blinding_leak")
            probes.append(
                {
                    "id": identifier,
                    "body": body,
                    "request_digest": _digest(body),
                    "target": {"field": "questions", "index": slot},
                }
            )
            key[identifier] = {
                "matched_set": source["key"],
                "variant": variant,
                "cohort": source["cohort"],
                "proposed_disposition": "accept"
                if variant in {"neutral", "scored_premise"}
                else "reject",
                "proposed_premise": {
                    "neutral": "none",
                    "scored_premise": "supported_scored",
                    "unsupported_premise": "unsupported",
                    "supported_unscored": "supported_unscored",
                }[variant],
                "annotation_basis": "machine-authored proposal; not independent human gold",
                "derivation": source["derivation"],
            }
            review.append(
                {
                    "id": identifier,
                    "request_digest": _digest(body),
                    "question_index": slot,
                    "question": questions_by_variant[variant],
                    "scored_claims": deepcopy(value["draft"]["claims"]),
                    "remaining_prose": deepcopy(value["unscored_prose"]),
                    "judgments": {"premise": None, "expected_disposition": None, "reason": None},
                    "reviewer": None,
                    "reviewed_at": None,
                    "provenance": None,
                }
            )
    if len({x["id"] for x in probes}) != len(probes):
        raise ValueError("blinded_probe_collision")
    random.Random(seed).shuffle(probes)
    order = {p["id"]: i for i, p in enumerate(probes)}
    review.sort(key=lambda r: order[r["id"]])
    evaluator = {"revision": REVISION, "private_salt": salt, "items": key}
    packet = {
        "revision": REVISION,
        "approved": False,
        "seed": seed,
        "probes": probes,
        "evaluator_key_digest": _digest(evaluator),
        "producer": qualification_producer(),
        "calibration_code_sha256": _CODE,
        "route": MODEL,
        "input_count_allowance": 16000,
        "policy": {
            "complete_response_coverage": 1,
            "false_pass_max": 0,
            "false_reject_max": 0,
            "acceptable_operational_blocks_max": 0,
            "missing_invalid": "Never a pass; fixed denominators and worst-case bounds include unresolved cases.",
            "human_missing": "HOLD",
            "claim_support": "Reported separately; never rescues prose.",
            "checker_qualified": False,
        },
    }
    packet["packet_digest"] = _digest(packet)
    worksheet = {
        "revision": REVISION,
        "packet_digest": packet["packet_digest"],
        "instructions": "Judge premise and expected disposition BEFORE viewing any checker verdict. Exact retained passages are inside scored_claims.evidence. These are correlated matched sets, not independent claim samples. Blank means unreviewed.",
        "items": review,
    }
    return packet, evaluator, worksheet


def validate_packet(packet: dict[str, Any]) -> None:
    if packet.get("approved") is not False or packet.get("packet_digest") != _digest(
        {k: v for k, v in packet.items() if k != "packet_digest"}
    ):
        raise AdmissionError("premise_packet_digest_or_permission_drift")
    if (
        packet["producer"] != qualification_producer()
        or packet["calibration_code_sha256"] != _CODE
        or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE
        or packet["route"] != MODEL
    ):
        raise AdmissionError("premise_producer_route_drift")
    if len({p["id"] for p in packet["probes"]}) != len(packet["probes"]):
        raise AdmissionError("duplicate_probe_identity")
    for probe in packet["probes"]:
        if _digest(probe["body"]) != probe["request_digest"]:
            raise AdmissionError("premise_request_drift")
        ctx = json.loads(probe["body"]["messages"][0]["content"])
        if wire({**ctx, "output_schema": transform_schema(Checks)}, ROUTES) != probe["body"]:
            raise AdmissionError("premise_wire_schema_drift")


def compile_probe(
    sealed: dict[str, Any],
    probe: dict[str, Any],
    *,
    packet_digest: str,
    scope_id: str,
    amendment_digest: str | None = None,
    pre_review_digest: str | None = None,
) -> Any:
    """Same protected probe adapter/route/accounting. No authority writer."""
    from dataclasses import replace

    result = prepare_input(
        sealed,
        scope_id=scope_id,
        packet_digest=packet_digest,
        case_id=probe["id"],
        operation="probe",
        probe_wire=probe["body"],
        operation_routes=deepcopy(ROUTES),
        programme_amendment_digest=amendment_digest,
    )
    return replace(
        result,
        settings={
            **result.settings,
            "premise_calibration": {
                "revision": REVISION,
                "code_sha256": _CODE,
                "request_digest": probe["request_digest"],
                "target": probe["target"],
                "pre_review_digest": pre_review_digest,
            },
        },
    )


class PremiseProbeAdapter(D5ProbeAdapter):
    """A located flag/abstention is a diagnostic response, never a generated pass.

    Expected scientific rejects don't stop a diagnostic just because it found
    the target violation. Invalid/missing/off-target findings still stop safely.
    This is a new externally authorized diagnostic scope, never v7r2 Stage D.
    """

    def _context(self) -> Any:
        binding = self.inputs.settings.get("premise_calibration", {})
        if (
            binding.get("revision") != REVISION
            or binding.get("code_sha256") != _CODE
            or hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != _CODE
        ):
            raise AdmissionError("premise_calibration_producer_drift")
        if binding.get("request_digest") != self.inputs.settings.get("probe_wire_digest"):
            raise AdmissionError("premise_request_binding_drift")
        if self.mode == "provider" and not binding.get("pre_review_digest"):
            raise AdmissionError("premise_independent_pre_review_required")
        return super()._context()

    def _review_complete(self, grounding: Any, snapshot: dict[str, Any], checks: Any) -> bool:
        target = self.inputs.settings["premise_calibration"]["target"]
        if checks.prose_review != "procedural_only" and any(
            f.field != target["field"] or f.index != target["index"] for f in checks.prose_findings
        ):
            raise AdmissionError("premise_off_target_finding")
        return True


def score(
    packet: dict[str, Any], responses: dict[str, Any], reviews: dict[str, Any]
) -> dict[str, Any]:
    """Fixed intended denominators, separate observed errors and operational blocks."""
    validate_packet(packet)
    ids = {p["id"] for p in packet["probes"]}
    if set(responses) - ids or reviews.get("packet_digest") != packet["packet_digest"]:
        raise ValueError("unknown_probe_or_stale_review")
    labels = {}
    for r in reviews["items"]:
        if r["id"] not in ids or r["id"] in labels:
            raise ValueError("unknown_or_duplicate_review")
        probe = next(p for p in packet["probes"] if p["id"] == r["id"])
        context = json.loads(probe["body"]["messages"][0]["content"])
        if (
            r["request_digest"] != probe["request_digest"]
            or r["question_index"] != probe["target"]["index"]
            or r["question"] != context["unscored_prose"]["questions"][r["question_index"]]
            or r["scored_claims"] != context["draft"]["claims"]
            or r["remaining_prose"] != context["unscored_prose"]
        ):
            raise ValueError("stale_or_mutated_review_binding")
        if r["judgments"]["expected_disposition"] is not None and (
            not r["reviewer"]
            or not r["reviewed_at"]
            or r["provenance"] not in {"independent_human", "synthetic"}
            or r["judgments"]["premise"]
            not in {
                "none",
                "supported_scored",
                "supported_unscored",
                "unsupported",
                "uncertain",
            }
            or r["judgments"]["expected_disposition"] not in {"accept", "reject", "abstain"}
        ):
            raise ValueError("attributed_premise_review_required")
        if (
            r["judgments"]["expected_disposition"] is not None
            and datetime.fromisoformat(r["reviewed_at"].replace("Z", "+00:00")).tzinfo is None
        ):
            raise ValueError("premise_review_timestamp_timezone_required")
        labels[r["id"]] = r
    counts = {
        k: 0
        for k in [
            "planned",
            "judged",
            "acceptable",
            "unacceptable",
            "false_pass",
            "false_reject",
            "acceptable_abstentions",
            "unacceptable_abstentions",
            "acceptable_missing_invalid",
            "unacceptable_missing_invalid",
            "missing",
            "invalid",
            "complete",
            "unjudged",
        ]
    }
    claim_support = {k: 0 for k in ["supported", "unsupported", "abstain"]}
    rows = []
    for probe in packet["probes"]:
        identifier = probe["id"]
        label = labels.get(identifier)
        truth = label["judgments"]["expected_disposition"] if label else None
        counts["planned"] += 1
        counts["unjudged" if truth is None else "judged"] += 1
        if truth in {"accept", "reject"}:
            counts["acceptable" if truth == "accept" else "unacceptable"] += 1
        payload = responses.get(identifier)
        decision = None
        error = None
        if payload is None:
            counts["missing"] += 1
            decision = "missing"
        else:
            try:
                checks = Checks.model_validate(payload)
                ctx = json.loads(probe["body"]["messages"][0]["content"])
                checks.validate_locations(ctx["unscored_prose"])
                expected = {c["claim_id"]: c["input_digest"] for c in ctx["claim_inputs"]}
                actual = {c.claim_id: c.input_digest for c in checks.checks}
                if len(actual) != len(checks.checks) or actual != expected:
                    raise ValueError("missing_duplicate_or_mismatched_claim_verdicts")
                if any(
                    f.field != probe["target"]["field"] or f.index != probe["target"]["index"]
                    for f in checks.prose_findings
                ):
                    raise ValueError("wrong_target_field_or_index")
                decision = {
                    "procedural_only": "pass",
                    "unscored_factual_content": "reject",
                    "abstain": "abstain",
                }[checks.prose_review]
                counts["complete"] += 1
                for c in checks.checks:
                    claim_support[c.decision] += 1
            except (ValueError, KeyError, TypeError) as exc:
                counts["invalid"] += 1
                decision = "invalid"
                error = str(exc)
        if truth == "reject" and decision == "pass":
            counts["false_pass"] += 1
        if truth == "accept" and decision == "reject":
            counts["false_reject"] += 1
        if truth in {"accept", "reject"} and decision == "abstain":
            counts[
                "acceptable_abstentions" if truth == "accept" else "unacceptable_abstentions"
            ] += 1
        if truth in {"accept", "reject"} and decision in {"missing", "invalid"}:
            counts[
                "acceptable_missing_invalid"
                if truth == "accept"
                else "unacceptable_missing_invalid"
            ] += 1
        rows.append(
            {
                "id": identifier,
                "human_disposition": truth,
                "human_premise": label["judgments"]["premise"] if label else None,
                "checker_prose": decision,
                "error": error,
            }
        )

    def fraction(n: int, d: int) -> dict[str, Any]:
        return {"numerator": n, "denominator": d, "rate": n / d if d else None}

    blocked = (
        counts["false_reject"]
        + counts["acceptable_abstentions"]
        + counts["acceptable_missing_invalid"]
    )
    qualified_reviews = (
        all(r["provenance"] == "independent_human" for r in labels.values())
        and all(
            r["judgments"]["expected_disposition"] in {"accept", "reject"} for r in labels.values()
        )
        and counts["judged"] == counts["planned"]
    )
    failures = (
        counts["false_pass"]
        + counts["false_reject"]
        + blocked
        + counts["missing"]
        + counts["invalid"]
        + counts["unacceptable_abstentions"]
    )
    return {
        "revision": REVISION,
        "packet_digest": packet["packet_digest"],
        "counts": counts,
        "prose": {
            "false_pass": fraction(counts["false_pass"], counts["unacceptable"]),
            "false_reject": fraction(counts["false_reject"], counts["acceptable"]),
            "acceptable_abstentions": fraction(
                counts["acceptable_abstentions"], counts["acceptable"]
            ),
            "acceptable_operational_blocks": fraction(blocked, counts["acceptable"]),
            "worst_case_false_pass": fraction(
                counts["false_pass"] + counts["unacceptable_missing_invalid"],
                counts["unacceptable"],
            ),
            "response_coverage": fraction(counts["complete"], counts["planned"]),
            "worst_case_false_reject": fraction(
                counts["false_reject"] + counts["acceptable_missing_invalid"], counts["acceptable"]
            ),
        },
        "claim_support_machine_only": claim_support,
        "false_pass_by_premise": {
            kind: fraction(
                sum(
                    r["human_disposition"] == "reject"
                    and r["human_premise"] == kind
                    and r["checker_prose"] == "pass"
                    for r in rows
                ),
                sum(
                    r["human_disposition"] == "reject" and r["human_premise"] == kind for r in rows
                ),
            )
            for kind in ("unsupported", "supported_unscored")
        },
        "rows": rows,
        "outcome": "HOLD"
        if not qualified_reviews or not counts["acceptable"] or not counts["unacceptable"]
        else "FAIL"
        if failures
        else "PASS_OBSERVED_SMALL_SAMPLE",
        "human_review_basis": "independent_human"
        if qualified_reviews
        else "missing or synthetic; not measured human agreement",
        "checker_qualified": False,
        "everyday_generation": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verb", choices=["build", "score"])
    parser.add_argument("--seeds", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--seed", type=int, default=7319)
    parser.add_argument("--salt-file", type=Path)
    args = parser.parse_args()
    if args.verb == "build":
        if not args.seeds or not args.salt_file:
            parser.error("build needs --seeds and evaluator-only --salt-file")
        packet, key, worksheet = build(
            read(args.seeds)["seeds"], seed=args.seed, salt=args.salt_file.read_text().strip()
        )
        write(args.out / "packet.json.gz", packet)
        write(args.out / "evaluator-key.json", key)
        (args.out / "evaluator-key.json").chmod(0o600)
        write(args.out / "reviewer-blank.json", worksheet)
        print(
            json.dumps(
                {
                    "packet_digest": packet["packet_digest"],
                    "probes": len(packet["probes"]),
                    "provider_contacts": 0,
                    "approved": False,
                }
            )
        )
    else:
        if not args.packet or not args.responses or not args.reviews:
            parser.error("score needs --packet --responses --reviews")
        write(args.out, score(read(args.packet), read(args.responses), read(args.reviews)))


if __name__ == "__main__":
    main()
