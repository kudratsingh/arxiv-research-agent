"""Synthetic review logic only, disposable filesystem stores; no human gold/API.

Public retained inputs are reused for exact provenance. Fabricated outputs and
labels have new fixture job IDs and synthetic attribution, never owner reviews.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.workspace import d5_reviews as d
from src.workspace.admission import AdmissionError, _digest
from src.workspace.d5_review_scoring import checker_metrics

ROOT = Path(__file__).resolve().parents[1]
D5 = ROOT / "planning/14-explore-and-research-modes/d5"
pytestmark = pytest.mark.unit


@pytest.fixture
def data():
    return d.read(D5 / "d5-system-validation-v2.json.gz"), d.read(
        D5 / "evidence/benchmark-results.json.gz"
    )


def labels(value, *, only=None):
    value = deepcopy(value)
    for item in value["items"]:
        if only and item["kind"] not in only:
            continue
        item.update(
            reviewer="synthetic-review-fixture",
            reviewer_role="synthetic",
            reviewed_at="2026-11-06T12:00:00+00:00",
            provenance="synthetic",
            method="Offline grading fixture; no human judgment",
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
        else:
            item["judgments"].update(relevance="relevant", known_reference=True)
    return value


def record_map(p, r, value):
    return {
        i.target: i
        for i in d.validate(p, r, value).items
        if i.judgments.model_dump(exclude_none=True)
    }


def enough(p, raw):
    """New synthetic outputs, not edits to the original archived run or database."""
    raw = deepcopy(raw)
    raw["basis"] = "SYNTHETIC GRADING FIXTURE. Not independent human/model evidence."
    for key, job in raw["raw_results"].items():
        job["id"] = "synthetic-" + job["id"]
        if key.startswith("probe-"):
            for step in job["steps"]:
                for c in step["output"].get("checks", []):
                    c["decision"] = "unsupported"
    for case in p["cases"]:
        job = raw["raw_results"][case["id"]]
        works = [s for s in job["steps"] if s["stage"] in {"draft", "repair"}]
        output = deepcopy(works[-1]["output"])
        if case["cohort"] == "fresh_system":
            handles = list(case["sealed"]["units"])
            output["claims"] = [
                {
                    "claim_id": "c" + str(i + 1),
                    "text": f"Synthetic fixture {case['id']} assertion {i + 1}.",
                    "handles": [handles[i % len(handles)]],
                }
                for i in range(4)
            ]
            output["comparison"] = ""
            output["comparison_basis"] = []
            if case["id"] == "research-insufficient":
                output["claims"] = []
                output["abstention"] = (
                    "Synthetic fixture: evidence does not establish hardware safety."
                )
            works[-1]["output"] = output
        for step in job["steps"]:
            if step["stage"] in {"check", "recheck"}:
                step["output"]["checks"] = [
                    {
                        "claim_id": c["claim_id"],
                        "decision": "supported",
                        "reason": "Synthetic",
                        "input_digest": "fixture",
                    }
                    for c in output["claims"]
                ]
    return raw


def test_blank_partial_and_reproducible_scoring_do_not_mutate_evidence(data):
    p, r = data
    before = _digest(r)
    blank = d.worksheet(p, r)
    report = d.recompute(p, r, {}, [])
    assert report["quality"]["outcome"] == "HOLD"
    assert report["quality"]["basis"] == "unreviewed"
    assert report["denominators"]["eligible_generated_claims"] == 12
    assert report["denominators"]["accepted_results"] == 0
    assert report["denominators"]["cost_per_accepted_result"] is None
    assert d.validate(p, r, blank)
    partial = labels(blank, only={"claim"})
    for item in partial["items"]:
        if item["kind"] == "claim":
            item["judgments"]["atomic"] = None
    records = record_map(p, r, partial)
    graded = d.recompute(p, r, records, ["synthetic"])
    assert graded["quality"]["outcome"] == "HOLD"
    assert graded["denominators"]["generated_fact_reviews_for_minimum"] == 0
    assert d.recompute(p, r, records, ["synthetic"]) == graded
    assert _digest(r) == before
    assert all(i["reviewer"] is None for i in blank["items"])


def test_complete_synthetic_labels_can_pass_logic_but_never_qualify(data):
    p, original = data
    r = enough(p, original)
    value = labels(d.worksheet(p, r, retrieval=True))
    report = d.recompute(p, r, record_map(p, r, value), ["synthetic"])
    assert report["quality"]["outcome"] == "PASS", report["quality"]["reasons"]
    assert report["quality"]["qualification_outcome"] == "HOLD"
    assert report["quality"]["basis"] == "synthetic"
    assert report["denominators"]["accepted_results"] == 8
    assert report["denominators"]["generated_fact_reviews_for_minimum"] == 28
    assert report["denominators"]["human_supported_generated_claims"] == 0
    assert report["denominators"]["adversarial_reviews_for_minimum"] == 20
    assert report["quality"]["checker"]["false_pass_rate"] == 0
    assert report["denominators"]["cost_per_accepted_result"] == "0"
    assert not report["checker_qualified"] and not report["everyday_generation"]
    assert all(c["retrieval"]["known_reference_recall"] is not None for c in report["cases"])
    receipt = report["analysis_receipt"]
    assert receipt["packet_digest"] == original["packet_digest"]
    assert receipt["result_digest"] == _digest(r)
    assert receipt["scorer_code"] == d.scorer_binding()
    assert report["accounting"] == original["accounting"]


@pytest.mark.parametrize(
    "field,value",
    [("support", "unsupported"), ("atomic", False), ("qualifications_retained", False)],
)
def test_claim_failures_fail_despite_valid_quote(data, field, value):
    p, raw = data
    r = enough(p, raw)
    review = labels(d.worksheet(p, r))
    item = next(
        i for i in review["items"] if i["kind"] == "claim" and i["case_id"] == "learn-method"
    )
    item["judgments"][field] = value
    result = d.recompute(p, r, record_map(p, r, review), [])
    assert result["quality"]["outcome"] == "FAIL"
    case = next(c for c in result["cases"] if c["id"] == "learn-method")
    assert case["provenance"] is True and case["factual_gate"] == "FAIL"


@pytest.mark.parametrize(
    "field,value",
    [
        ("complete", False),
        ("material_omissions", True),
        ("comparison_compatible", False),
        ("counterevidence_handled", False),
        ("appropriate_abstention", False),
        ("prose_support", "unsupported"),
    ],
)
def test_case_rubric_failures_are_not_hidden_in_optional_prose(data, field, value):
    p, raw = data
    r = enough(p, raw)
    review = labels(d.worksheet(p, r))
    item = next(
        i for i in review["items"] if i["kind"] == "case" and i["case_id"] == "research-retrieval"
    )
    item["judgments"][field] = value
    result = d.recompute(p, r, record_map(p, r, review), [])
    assert result["quality"]["outcome"] == "FAIL"


@pytest.mark.parametrize("support", ["insufficient", "unreviewable", None])
def test_indeterminate_labels_and_missing_denominators(data, support):
    p, r = data
    review = labels(d.worksheet(p, r), only={"claim"})
    for i in review["items"]:
        if i["kind"] == "claim":
            i["judgments"]["support"] = support
    report = d.recompute(p, r, record_map(p, r, review), [])
    counts = report["quality"]["claims_by_cohort"]["fresh_system"]
    assert counts["factual_support"] is None
    assert counts["reviewed"] == (12 if support else 0)
    assert report["quality"]["outcome"] == "HOLD"
    assert report["quality"]["checker"]["false_pass_rate"] is None
    assert report["quality"]["checker"]["false_fail_rate"] is None


@pytest.mark.parametrize("defect", ["quote", "offset", "version", "unselected"])
def test_mechanical_failure_cannot_be_rescued_by_positive_human_labels(data, defect):
    p, raw = data
    p = deepcopy(p)
    r = enough(p, raw)
    case = next(c for c in p["cases"] if c["id"] == "learn-method")
    unit = next(iter(case["sealed"]["units"].values()))
    if defect == "quote":
        unit["quote"] = "Fabricated quotation"
    elif defect == "offset":
        unit["start"] += 1
    elif defect == "version":
        unit["version_id"] = "wrong-version"
    else:
        step = [
            s for s in r["raw_results"][case["id"]]["steps"] if s["stage"] in {"draft", "repair"}
        ][-1]
        step["output"]["claims"][0]["handles"] = ["unselected"]
    p["packet_digest"] = _digest({k: v for k, v in p.items() if k != "packet_digest"})
    r["packet_digest"] = p["packet_digest"]
    for job in r["raw_results"].values():
        job["packet_digest"] = p["packet_digest"]
    result = d.recompute(p, r, record_map(p, r, labels(d.worksheet(p, r))), [])
    case = next(c for c in result["cases"] if c["id"] == "learn-method")
    assert case["provenance"] is False and case["review_outcome"] == "FAIL"
    assert result["quality"]["outcome"] == "FAIL"


def test_checker_actual_labels_not_proposed_negativity_and_abstentions():
    rows = [
        {"human": "supported", "machine": "unsupported", "target": "a"},
        {"human": "unsupported", "machine": "supported", "target": "b"},
        {"human": "unsupported", "machine": "abstain", "target": "c"},
        {"human": "insufficient", "machine": "supported", "target": "d"},
        {"human": "unreviewable", "machine": None, "target": "e"},
        {"human": None, "machine": "supported", "target": "f"},
        {"human": "supported", "machine": None, "target": "g"},
    ]
    result = checker_metrics(rows)
    assert result["false_passes"] == result["false_failures"] == 1
    assert result["false_pass_rate"] == result["false_fail_rate"] == 1
    assert result["agreement"] == 0
    assert result["abstention_rate"] == 1 / 3
    assert result["human_indeterminate"] == 2 and result["machine_missing"] == 1
    assert len(result["disagreements"]) == 2
    assert checker_metrics(rows[:1])["false_pass_rate"] is None
    assert checker_metrics(rows[1:2])["false_fail_rate"] is None
    assert checker_metrics([])["abstention_rate"] is None


def test_development_and_exact_duplicates_do_not_fill_heldout_minimum(data):
    p, r = data
    review = labels(d.worksheet(p, r))
    review["items"] = [i for i in review["items"] if i["case_id"].startswith("dev-")]
    report = d.recompute(p, r, record_map(p, r, review), [])
    assert report["denominators"]["generated_fact_reviews_for_minimum"] == 0
    assert report["quality"]["claims_by_cohort"]["development"]["reviewed"] == 3
    r = enough(p, r)
    for case in p["cases"]:
        if case["cohort"] != "fresh_system":
            continue
        step = [
            s for s in r["raw_results"][case["id"]]["steps"] if s["stage"] in {"draft", "repair"}
        ][-1]
        for claim in step["output"]["claims"]:
            claim["text"] = "Same synthetic fact."
            claim["handles"] = step["output"]["claims"][0]["handles"]
    result = d.recompute(p, r, record_map(p, r, labels(d.worksheet(p, r))), [])
    assert result["denominators"]["generated_fact_reviews_for_minimum"] == 7
    assert result["quality"]["outcome"] == "HOLD"


def test_import_idempotence_conflicts_and_explicit_adjudication(data, tmp_path):
    p, r = data
    value = labels(d.worksheet(p, r))
    value["items"] = value["items"][:1]
    first = d.import_review(tmp_path, p, r, value)
    assert first["imported"] and not first["idempotent"]
    assert d.import_review(tmp_path, p, r, value)["idempotent"]
    changed = deepcopy(value)
    changed["items"][0]["judgments"]["complete"] = False
    with pytest.raises(AdmissionError, match="adjudication"):
        d.import_review(tmp_path, p, r, changed)
    changed["adjudication"] = {"supersedes": ["unknown"], "reason": "Synthetic conflict"}
    with pytest.raises(AdmissionError, match="unknown_adjudication"):
        d.import_review(tmp_path, p, r, changed)
    changed["adjudication"]["supersedes"] = [first["review_digest"]]
    with pytest.raises(AdmissionError, match="adjudication"):
        d.import_review(tmp_path, p, r, changed)
    changed["review_revision"] = 2
    second = d.import_review(tmp_path, p, r, changed)
    active, digests = d.imported(tmp_path, p, r)
    assert len(digests) == 2 and next(iter(active.values())).judgments.complete is False
    stale = deepcopy(value)
    stale["review_revision"] = 3
    stale["adjudication"] = {"supersedes": [first["review_digest"]], "reason": "Stale parent"}
    with pytest.raises(AdmissionError, match="adjudication"):
        d.import_review(tmp_path, p, r, stale)
    assert len(list((tmp_path / "imports").glob("*.json"))) == 2
    assert second["review_digest"] != first["review_digest"]


@pytest.mark.parametrize(
    "defect",
    [
        "packet",
        "result",
        "target",
        "binding",
        "cross_case",
        "duplicate",
        "unknown_field",
        "kind_label",
        "attribution",
        "timestamp",
        "role",
        "owner",
    ],
)
def test_review_validation_refuses_stale_unknown_or_mismatched_labels(data, defect):
    p, r = data
    value = labels(d.worksheet(p, r))
    item = value["items"][0]
    if defect == "packet":
        value["packet_digest"] = "stale"
    elif defect == "result":
        value["result_digest"] = "stale"
    elif defect == "target":
        item["target"] = "unknown"
    elif defect == "binding":
        item["binding"] = "wrong"
    elif defect == "cross_case":
        item["case_id"] = "other-case"
    elif defect == "duplicate":
        value["items"].append(deepcopy(item))
    elif defect == "unknown_field":
        item["unknown"] = True
    elif defect == "kind_label":
        item["judgments"]["atomic"] = True
    elif defect == "attribution":
        item["reviewer"] = None
    elif defect == "timestamp":
        item["reviewed_at"] = "2026-11-06T12:00:00"
    elif defect == "role":
        item["reviewer_role"] = None
    else:
        item.update(provenance="independent_human", reviewer_role="expert")
        item["judgments"]["usefulness"] = "useful"
    with pytest.raises((AdmissionError, ValidationError)):
        d.validate(p, r, value)


def test_import_receipt_tampering_and_original_identity_are_refused(data, tmp_path):
    p, r = data
    d.import_review(tmp_path, p, r, labels(d.worksheet(p, r)))
    file = next((tmp_path / "imports").glob("*.json"))
    receipt = d.read(file)
    receipt["review_digest"] = "changed"
    file.write_text(__import__("json").dumps(receipt))
    with pytest.raises(AdmissionError, match="integrity"):
        d.imported(tmp_path, p, r)
    bad = deepcopy(p)
    bad["clock"] = "changed"
    with pytest.raises(AdmissionError, match="packet_integrity"):
        d.worksheet(bad, r)
    bad = deepcopy(r)
    next(iter(bad["raw_results"].values()))["case_id"] = "other"
    with pytest.raises(AdmissionError, match="cross_case"):
        d.worksheet(p, bad)
    bad = deepcopy(r)
    jobs = list(bad["raw_results"].values())
    jobs[1]["id"] = jobs[0]["id"]
    with pytest.raises(AdmissionError, match="duplicate_or_missing"):
        d.worksheet(p, bad)
    bad = deepcopy(r)
    bad["packet_digest"] = "wrong"
    with pytest.raises(AdmissionError, match="original_packet"):
        d.worksheet(p, bad)


def test_cli_full_export_validate_import_score_path(data, tmp_path, monkeypatch, capsys):
    p, r = data
    packet = tmp_path / "packet.json.gz"
    results = tmp_path / "raw.json.gz"
    worksheet = tmp_path / "blank.json"
    review = tmp_path / "review.json"
    store = tmp_path / "reviews"
    d.write_new(packet, p)
    d.write_new(results, r)

    def command(verb, *args):
        monkeypatch.setattr(
            "sys.argv",
            [
                "d5_reviews",
                verb,
                "--packet",
                str(packet),
                "--results",
                str(results),
                *map(str, args),
            ],
        )
        d.main()

    command("export", "--out", worksheet)
    assert all(i["reviewer"] is None for i in d.read(worksheet)["items"])
    d.write_new(review, labels(d.read(worksheet)))
    command("validate", "--review", review)
    command("import", "--review", review, "--store", store)
    command("import", "--review", review, "--store", store)
    command("score", "--store", store, "--out", tmp_path / "report")
    report = d.read(tmp_path / "report/results.json")
    assert report["quality"]["basis"] == "synthetic"
    assert "synthetic" in (tmp_path / "report/REPORT.md").read_text()
    assert (tmp_path / "report/index.html").exists()
    assert report["analysis_receipt"]["accounting_digest"] == _digest(r["accounting"])
    assert "idempotent" in capsys.readouterr().out
    assert d.read(results) == r and all(i["reviewer"] is None for i in d.read(worksheet)["items"])
    with pytest.raises(FileExistsError):
        d.write_new(worksheet, {})


@pytest.mark.parametrize("unknown", ["0.0000", "0.10", None, "NaN", "invalid", "-1"])
def test_cost_per_accepted_result_requires_known_nonnegative_costs(data, unknown):
    p, raw = data
    r = enough(p, raw)
    for case in p["cases"]:
        r["raw_results"][case["id"]].update(
            workflow_usd="0.10", checker_usd="0.02", unknown_usd=unknown
        )
    result = d.recompute(p, r, record_map(p, r, labels(d.worksheet(p, r))), [])
    assert result["denominators"]["cost_per_accepted_result"] == (
        "0.12" if unknown == "0.0000" else None
    )
    assert result["accounting"] == raw["accounting"]


def test_incomplete_failed_and_no_assertion_cases_do_not_pass(data):
    p, raw = data
    empty = deepcopy(raw)
    empty["raw_results"] = {}
    assert d.worksheet(p, empty)["items"] == []
    result = d.recompute(p, empty, {}, [])
    assert result["quality"]["outcome"] == "HOLD"
    assert result["denominators"]["eligible_generated_claims"] == 0
    failed = enough(p, raw)
    failed["raw_results"]["learn-method"]["state"] = "failed"
    assert (
        d.recompute(p, failed, record_map(p, failed, labels(d.worksheet(p, failed))), [])[
            "quality"
        ]["outcome"]
        == "FAIL"
    )
    empty_output = enough(p, raw)
    job = empty_output["raw_results"]["learn-method"]
    step = [s for s in job["steps"] if s["stage"] in {"draft", "repair"}][-1]
    step["output"].update(claims=[], abstention=None)
    result = d.recompute(
        p, empty_output, record_map(p, empty_output, labels(d.worksheet(p, empty_output))), []
    )
    assert next(c for c in result["cases"] if c["id"] == "learn-method")["review_outcome"] != "PASS"


def test_partial_retrieval_labels_do_not_claim_complete_reference_recall(data):
    p, raw = data
    review = labels(d.worksheet(p, raw, retrieval=True), only={"retrieval"})
    review["items"] = [i for i in review["items"] if i["kind"] == "retrieval"][:1]
    report = d.recompute(p, raw, record_map(p, raw, review), [])
    assert all(c["retrieval"]["known_reference_recall"] is None for c in report["cases"])
    assert (
        report["denominators"]["known_reference_judgments"] == 0
    )  # First item belongs to development.


def test_malformed_claims_changed_evidence_and_cross_run_store_are_rejected(data, tmp_path):
    p, raw = data
    review = labels(d.worksheet(p, raw))
    wrong = deepcopy(review)
    wrong["items"][1]["observed"]["output_digest"] = "different-output"
    with pytest.raises(AdmissionError, match="binding"):
        d.validate(p, raw, wrong)
    d.import_review(tmp_path, p, raw, review)
    modified = deepcopy(raw)
    modified["basis"] += " changed analysis"
    with pytest.raises(AdmissionError, match="import_identity"):
        d.imported(tmp_path, p, modified)
    malformed = deepcopy(raw)
    job = malformed["raw_results"]["learn-method"]
    output = [s["output"] for s in job["steps"] if s["stage"] in {"draft", "repair"}][-1]
    output["claims"].append(deepcopy(output["claims"][0]))
    with pytest.raises(AdmissionError, match="malformed_observed"):
        d.worksheet(p, malformed)
    records = record_map(p, raw, review)
    record = next(iter(records.values()))
    with pytest.raises(AdmissionError, match="record_key"):
        d.recompute(p, raw, {"wrong-key": record}, [])


@pytest.mark.parametrize(
    "verb,extras", [("export", []), ("validate", []), ("import", ["--review"]), ("score", [])]
)
def test_cli_requires_explicit_paths_and_never_overwrites(
    data, tmp_path, monkeypatch, verb, extras
):
    p, r = data
    packet, results, review = tmp_path / "p.json", tmp_path / "r.json", tmp_path / "review.json"
    d.write_new(packet, p)
    d.write_new(results, r)
    d.write_new(review, d.worksheet(p, r))
    args = ["d5_reviews", verb, "--packet", str(packet), "--results", str(results)]
    if extras:
        args += ["--review", str(review)]
    monkeypatch.setattr("sys.argv", args)
    with pytest.raises(SystemExit):
        d.main()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]")
    with pytest.raises(AdmissionError, match="object_required"):
        d.read(invalid)


def test_attributed_owner_usefulness_and_machine_assisted_basis_remain_separate(data):
    p, r = data
    review = labels(d.worksheet(p, r))
    item = next(i for i in review["items"] if i["kind"] == "case")
    # A parser/role fixture, not a claim that a human or owner actually reviewed.
    item.update(
        provenance="machine_assisted_human",
        reviewer_role="owner",
        method="Synthetic role-validation test",
    )
    item["judgments"]["usefulness"] = "maybe"
    review["items"] = [item]
    report = d.recompute(p, r, record_map(p, r, review), [])
    assert report["quality"]["basis"] == "machine_assisted_human"
    assert report["cases"][0]["retrieval"]["owner_usefulness"] == "maybe"
    assert report["quality"]["qualification_outcome"] == "HOLD"
    item["provenance"] = "independent_human"
    report = d.recompute(p, r, record_map(p, r, review), [])
    assert report["quality"]["basis"] == "independent_human"
    assert not report["checker_qualified"]


def test_duplicate_json_fields_are_not_silently_last_wins(tmp_path):
    file = tmp_path / "ambiguous.json"
    file.write_text('{"support":"supported","support":"unsupported"}')
    with pytest.raises(AdmissionError, match="duplicate_json_key"):
        d.read(file)
