"""Synthetic v19 workflow builders; all transport and judgments are test data."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator

from src.workspace import d5_adapter as adapter_module
from src.workspace.admission import _digest
from src.workspace.assistance import capacity
from src.workspace.assistance_policy import CoverageTaskContext
from src.workspace.d5_campaign_v16_packet import upgrade
from src.workspace.d5_capacity_policy import DEADLINES, POLICY, ROUTES
from src.workspace.d5_operations import wire
from tests import test_workspace_consistency_contract as checks_fixture
from tests import test_workspace_d5_adapter as legacy


def setup(store, monkeypatch, mode, *, source_setup=None, comparison_request=None):
    """Seal selected evidence through production admission with synthetic grant."""
    from src.workspace import assistance_comparison_contract as codec

    prepare = adapter_module.prepare_input

    def prospective(sealed, **kwargs):
        sealed = deepcopy(sealed)
        sealed["assistance"]["task_context"] = CoverageTaskContext.model_validate(
            {
                "intent": "comparison" if mode == "research" else "answer",
                "requested_parts": [
                    {
                        "id": "p1",
                        "request": comparison_request or "Compare the selected source descriptions, preserving unknown methods and protocols."
                        if mode == "research"
                        else "Explain the selected reported result, preserving unknown methods and protocols.",
                        "kind": "comparison" if mode == "research" else "answer",
                    },
                    {
                        "id": "p2",
                        "request": "Summarize the selected source evidence with remaining methods and protocol gaps.",
                        "kind": "answer",
                    },
                ],
            }
        ).model_dump(mode="json")
        sealed = upgrade(sealed, union_safe=True)
        sealed["task_policy"][codec.KEY] = codec.REVISION
        sealed["response_schemas"] = codec.schemas(
            list(sealed["units"]), sealed["response_purpose"], sealed["task_policy"]
        )
        for stage in ["draft", "repair"]:
            sealed["stage_contracts"][stage]["output_schema"] = sealed["response_schemas"]["wire"]
        sealed["candidate_initial_wire"] = wire(adapter_module.initial_context(sealed), ROUTES)
        sealed["capacity"] = capacity(sealed)
        kwargs.update(
            capacity_policy=POLICY,
            operation_routes=ROUTES,
            operation_deadlines=DEADLINES,
            repair_located_prose=True,
        )
        return prepare(sealed, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(adapter_module, "prepare_input", prospective)
        return legacy.setup(
            store, mode=mode, comparison=mode == "research" and source_setup is None,
            source_setup=source_setup,
        )


def draft(context, *, repaired=False, notes_only=False):
    """New synthetic output only; do not upgrade or edit archived model text."""
    sealed = context["sealed_request"]
    by_work = {}
    for handle, reference in sealed["units"].items():
        by_work.setdefault(reference["work_id"], handle)
    selected = list(by_work.values())
    first, second = selected[0], selected[-1]
    refs = sealed["units"]
    claims = [
        {
            "text": refs[first]["quote"],
            "handles": [first],
            "required_scope": refs[first]["scope"],
        },
        {
            "text": refs[second]["quote"],
            "handles": [second],
            "required_scope": refs[second]["scope"],
        },
    ]
    research = sealed["assistance"]["mode"] == "research"
    if research and not notes_only:
        claims.append(
            {
                "text": "The selected descriptions report different outcomes and scope: source A says "
                + refs[first]["quote"]
                + " Source B says "
                + refs[second]["quote"]
                + (" No shared evaluation protocol is established by these excerpts." if repaired else ""),
                "handles": [first, second],
                "required_scope": "abstract",
            }
        )
    elif repaired:
        claims[0]["text"] += " This is the selected passage's reported result."
    ids = [f"c{i + 1}" for i in range(len(claims))]
    coverage = {}
    for part in sealed["task_policy"]["requested_parts"]:
        comparison = part["kind"] == "comparison"
        if comparison and notes_only:
            coverage[part["id"]] = {
                "status": "lacks_evidence",
                "gap_reasons": ["methods", "protocol"],
                "answer_claim_ids": [],
                "context_claim_ids": ids,
            }
        else:
            answers = ["c3"] if comparison else ids[:2]
            coverage[part["id"]] = {
                "status": "partial",
                "gap_reasons": ["methods", "protocol"],
                "answer_claim_ids": answers,
                "context_claim_ids": [key for key in ids if key not in answers],
            }
    return {
        "response": {
            "disposition": "answer",
            "claims": claims,
            "background_claims": ids[:2],
            "assumption_claims": [],
            "limitation_claims": [],
            "gaps": ["source_scope"],
            "questions": [
                {"intent": "methods", "context_claim_ids": ["c1"], "premise_claim_ids": []},
                {"intent": "investigate_claim", "context_claim_ids": [], "premise_claim_ids": ["c2"]},
            ],
            "proposal": "inspect_methods",
            "coverage": coverage,
        }
    }


class SyntheticTransport:
    def __init__(self, scenario="repair"):
        self.scenario = scenario
        self.contacts = []
        self.phases = []
        self.outputs = []
        self.checks = 0

    async def __call__(self, request):
        body = json.loads(request.content)
        self.contacts.append((request.url.path, body))
        if request.url.path.endswith("count_tokens"):
            return httpx.Response(200, json={"input_tokens": 100})
        context = json.loads(body["messages"][0]["content"])
        phase = context["phase"]
        self.phases.append(phase)
        if phase == "check":
            self.checks += 1
            if (self.scenario == "uncertain_check" and self.checks == 1) or (
                self.scenario == "uncertain_recheck" and self.checks == 2
            ):
                raise httpx.ReadTimeout("Synthetic uncertain v19 checker; no external contact", request=request)
            if context["sealed_request"]["assistance"]["mode"] == "research":
                assert "comparison" in context["quality_rubric"]
                assert "p1" in context["comparison_answer_basis"]
                assert context["comparison_answer_basis"]["p1"]["requested_part"]
            value = checks_fixture.synthetic_verdict(context)
            if self.scenario == "unsupported_performance":
                value["claim_reviews"]["c3"].update(
                    decision="unsupported",
                    reason="Synthetic semantic judgment: separate resolving citations do not establish the asserted performance superiority under compatible tasks, metrics and conditions.",
                )
                value["coverage_checks"]["p1"].update(
                    decision="lacks_evidence",
                    critiques=["The selected studies lack compatible evaluation evidence for this performance ordering."],
                )
            elif self.scenario == "false_full_comparison":
                value["coverage_checks"]["p1"].update(
                    decision="partial",
                    critiques=["The qualitative description is supported, but the requested compatible performance comparison remains unanswered."],
                )
            if (self.checks == 1 and self.scenario not in {"clear", "source_notes", "full_abstention", "unsupported_performance", "false_full_comparison"}) or self.scenario in {"residual", "uncertain_quality"}:
                first = next(iter(value["coverage_checks"]))
                value["coverage_checks"][first]["critiques"] = [
                    "Synthetic requested-detail critique requiring the one bounded repair."
                ]
                if self.scenario == "residual" and self.checks == 2:
                    key = next(iter(value["prose_findings"]))
                    value["prose_findings"][key] = [
                        "Synthetic final unscored factual assertion remains unsupported."
                    ]
            if self.scenario == "uncertain_quality" and self.checks == 2:
                first = next(iter(value["coverage_checks"]))
                value["coverage_checks"][first]["decision"] = "uncertain"
                key = next(iter(value["prose_uncertainties"]))
                value["prose_uncertainties"][key] = ["Synthetic unresolved factual premise remains uncertain."]
        else:
            value = draft(
                context, repaired=phase == "repair", notes_only=self.scenario == "source_notes"
            )
            if self.scenario == "unsupported_performance":
                value["response"]["claims"][2]["text"] = (
                    "The first selected method outperforms the second across compatible tasks, "
                    "evaluation protocols and accuracy metrics."
                )
            elif self.scenario == "false_full_comparison":
                for row in value["response"]["coverage"].values():
                    row.update(status="answered", gap_reasons=["none"])
            if self.scenario == "full_abstention":
                value = {"response": {
                    "disposition": "full_abstention",
                    "reason": "insufficient_selected_evidence", "next_action": "request_context",
                    "coverage": {part["id"]: {
                        "status": "lacks_evidence", "gap_reasons": ["methods", "protocol"],
                    } for part in context["sealed_request"]["task_policy"]["requested_parts"]},
                }}
            if self.scenario == "single_source_comparison":
                value["response"]["claims"][2]["handles"] = value["response"]["claims"][0]["handles"]
            elif self.scenario == "pooled_source_comparison":
                value["response"]["coverage"]["p1"].update(
                    answer_claim_ids=["c1", "c2"], context_claim_ids=["c3"]
                )
            if self.scenario == "invalid_draft":
                # Deliberately schema-valid but semantically inconsistent. The
                # provider returned complete JSON/usage; no repair is permitted.
                first = next(iter(value["response"]["coverage"]))
                value["response"]["coverage"][first]["status"] = "answered"
            self.outputs.append(deepcopy(value))
        Draft202012Validator(body["output_config"]["format"]["schema"]).validate(value)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-v19-pipeline-" + str(len(self.contacts)),
                "type": "message",
                "model": body["model"],
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )


def assert_paired_contacts(final, handler, message_count):
    """Check exact count bodies and retained production journals, not totals only."""
    assert len(handler.contacts) == len(final["contacts"]) == 2 * message_count
    for index in range(message_count):
        ordinal = index * 2
        count, generation = final["contacts"][ordinal : ordinal + 2]
        count_path, count_body = handler.contacts[ordinal]
        message_path, message_body = handler.contacts[ordinal + 1]
        assert count_path.endswith("/messages/count_tokens")
        assert message_path.endswith("/messages")
        assert count_body == {k: v for k, v in message_body.items() if k not in {"max_tokens", "temperature"}}
        assert count["body"] == count_body and generation["body"] == message_body
        assert count["ordinal"] == ordinal and generation["ordinal"] == ordinal + 1
        assert count["generation_request_digest"] == generation["request_digest"] == _digest(message_body)
        assert count["request_digest"] == _digest(count_body)
        assert generation["generation_request_digest"] == generation["request_digest"]
        assert count["stage"] == generation["stage"]
        assert count["state"] == "completed"
        assert count["response"] == {"input_tokens": 100}


def retain_report(mode, scenario, report):
    """Keep derived reports beside immutable row exports before schema teardown."""
    from src.workspace.d5_benchmark import write

    base = Path(os.environ.get("D5_TEST_EVIDENCE_DIR", "build/d5-v19-test-evidence/ledger"))
    destination = base.parent / ("report-" + mode + "-" + scenario + "-" + uuid4().hex + ".json.gz")
    write(destination, {
        "basis": "Synthetic isolated regression; machine judgments are not human scientific validation.",
        "report": report,
    })
    return destination
