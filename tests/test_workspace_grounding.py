"""Future grounding boundary: real IDs cannot certify false factual claims."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from src.workspace import grounding as g
from src.workspace.material import SourceMaterial, extract_text

pytestmark = pytest.mark.unit


@pytest.fixture
def abstract() -> SourceMaterial:
    return extract_text(
        "The method was evaluated on ten datasets. Only the abstract is available.",
        work_id="arxiv:2611.00001",
        version_id="arxiv:2611.00001:v1",
        scope="abstract",
        section="abstract",
    )


def claim(
    material: SourceMaterial,
    *,
    claim_id: str = "claim-1",
    text: str = "The method was evaluated on ten datasets.",
    **kwargs: Any,
) -> g.ResearchClaim:
    return g.ResearchClaim(
        claim_id,
        text,
        g.ClaimKind.FACTUAL,
        (g.evidence_ref(material, material.spans[0]),),
        **kwargs,
    )


def check(
    value: g.ResearchClaim,
    material: SourceMaterial,
    decision: g.SupportDecision = g.SupportDecision.SUPPORTED,
) -> g.SupportCheck:
    return g.SupportCheck(
        value.claim_id,
        g.claim_input_digest(value, [material]),
        decision,
        "synthetic-adversarial-fixture",
        "1.0.0",
        "Explicit synthetic checker verdict; not human or live-model evidence.",
    )


def test_selected_pdf_pages_resolve_original_page_numbers_without_aliasing(abstract: SourceMaterial) -> None:
    span = replace(abstract.spans[0], page=17, section="methods", scope="excerpt")
    selected = replace(abstract, scope="excerpt", page_count=20, page_numbers=(17,), spans=(span,), complete=False)
    value = claim(selected, required_scope="excerpt", required_section="methods")
    result = g.validate_claims([value], [selected], [check(value, selected)])
    assert result.supported == 1 and result.assessments[0].scope_compatible
    with pytest.raises(g.GroundingError, match="page_mapping"):
        g.validate_claims([value], [replace(selected, page_numbers=(18,))])
    for mapping in [(17, 17), (0,), (21,), (None,), (None, 17)]:
        with pytest.raises(g.GroundingError, match="page_mapping"):
            g.validate_claims([value], [replace(selected, page_numbers=mapping)])


def test_resolving_a_real_citation_is_only_identity_not_factual_support(
    abstract: SourceMaterial,
) -> None:
    false_claim = claim(abstract, text="The method was evaluated on one million datasets.")
    result = g.validate_claims([false_claim], [abstract])
    assessed = result.assessments[0]
    assert assessed.identity_resolved and assessed.scope_compatible
    assert assessed.decision == g.SupportDecision.ABSTAIN and not assessed.checked
    assert assessed.reason == "factual_support_unmeasured"
    assert result.total_factual == 1 and result.supported == 0 and result.abstained == 1
    assert result.support_ratio is None


def test_false_statement_with_real_reference_remains_unsupported(abstract: SourceMaterial) -> None:
    false_claim = claim(abstract, text="The method was evaluated on one million datasets.")
    verdict = check(false_claim, abstract, g.SupportDecision.UNSUPPORTED)
    result = g.validate_claims([false_claim], [abstract], [verdict])
    assert result.assessments[0].identity_resolved
    assert result.checked == 1 and result.unsupported == 1 and result.supported == 0
    assert result.support_ratio == 0.0
    assert result.assessments[0].checker_id == "synthetic-adversarial-fixture"


def test_explicit_checks_abstentions_and_nullable_denominators_are_separate(
    abstract: SourceMaterial,
) -> None:
    claims = [claim(abstract, claim_id=f"c{i}") for i in range(4)]
    checks = [
        check(claims[0], abstract),
        check(claims[1], abstract, g.SupportDecision.UNSUPPORTED),
        check(claims[2], abstract, g.SupportDecision.ABSTAIN),
    ]
    result = g.validate_claims(claims, [abstract], checks)
    assert (
        result.total_factual,
        result.checked,
        result.supported,
        result.unsupported,
        result.abstained,
        result.decided,
    ) == (4, 3, 1, 1, 2, 2)
    assert result.support_ratio == 0.5
    assert "abstentions excluded" in result.ratio_basis
    assert "includes checker abstentions" in result.check_basis
    assert g.validate_claims([], []).support_ratio is None
    abstained = g.validate_claims(
        [claims[0]], [abstract], [check(claims[0], abstract, g.SupportDecision.ABSTAIN)]
    )
    assert abstained.checked == 1 and abstained.decided == 0 and abstained.support_ratio is None


def test_abstract_missing_methods_forces_abstention_even_if_checker_says_supported(
    abstract: SourceMaterial,
) -> None:
    value = claim(
        abstract,
        text="The methods used stratified cross-validation.",
        required_scope="full_text",
        required_section="methods",
    )
    report = g.validate_claims([value], [abstract], [check(value, abstract)])
    assert report.assessments[0].identity_resolved
    assert not report.assessments[0].scope_compatible
    assert report.assessments[0].decision == g.SupportDecision.ABSTAIN
    assert report.assessments[0].reason == "source_scope_insufficient"
    assert report.checked == 0 and report.support_ratio is None
    # Weakening a generic scope field does not let an explicitly declared
    # methods/equation claim borrow absent body content from an abstract.
    weaker = replace(value, required_scope="abstract")
    assert g.validate_claims([weaker], [abstract], [check(weaker, abstract)]).support_ratio is None


def test_identified_method_excerpt_is_distinct_from_full_text_and_unknown_excerpt() -> None:
    method = extract_text(
        "We used five-fold stratified cross-validation.",
        work_id="w",
        version_id="v",
        scope="excerpt",
        section="methods",
    )
    value = claim(method, required_scope="excerpt", required_section="methods")
    assert g.validate_claims([value], [method], [check(value, method)]).supported == 1
    whole = replace(value, required_scope="full_text")
    assert g.validate_claims([whole], [method], [check(whole, method)]).abstained == 1
    unknown = extract_text(method.pages[0], work_id="w", version_id="v", scope="excerpt")
    unidentified = claim(unknown, required_scope="excerpt", required_section="methods")
    assert (
        g.validate_claims([unidentified], [unknown], [check(unidentified, unknown)]).abstained == 1
    )


def test_inference_requires_a_visible_label_and_is_never_a_verified_fact(
    abstract: SourceMaterial,
) -> None:
    value = replace(
        claim(abstract),
        kind=g.ClaimKind.INFERENCE,
        inference_label="Hypothesis to investigate; not an author-reported result",
    )
    result = g.validate_claims([value], [abstract])
    assert (
        result.inference_count == 1 and result.total_factual == 0 and result.support_ratio is None
    )
    assessed = result.assessments[0]
    assert assessed.decision is None and not assessed.checked and assessed.inference_label
    assert assessed.reason == "labelled_inference_not_factual_support"
    with pytest.raises(g.GroundingError, match="inference_cannot_be_verified"):
        g.validate_claims([value], [abstract], [check(value, abstract)])
    with pytest.raises(g.GroundingError, match="inference_label_required"):
        g.validate_claims([replace(value, inference_label=None)], [abstract])
    with pytest.raises(g.GroundingError, match="factual_claim_cannot_be_labelled_inference"):
        g.validate_claims([replace(value, kind=g.ClaimKind.FACTUAL)], [abstract])


def test_precise_partial_quote_offsets_are_bound_to_retained_unicode_text(
    abstract: SourceMaterial,
) -> None:
    ref = g.evidence_ref(abstract, abstract.spans[0], start=4, end=10)
    assert ref.quote == abstract.pages[0][4:10] == "method"
    value = replace(claim(abstract), evidence=(ref,))
    assert g.validate_claims([value], [abstract], [check(value, abstract)]).supported == 1
    with pytest.raises(g.GroundingError, match="quote_outside_retained_span"):
        g.evidence_ref(abstract, abstract.spans[0], start=-1)
    unrelated = extract_text("Other source.", work_id="other", version_id="v", scope="abstract")
    with pytest.raises(g.GroundingError, match="quote_outside_retained_span"):
        g.evidence_ref(abstract, unrelated.spans[0])


@pytest.mark.parametrize(
    "change",
    [
        {"version_id": "v2"},
        {"work_id": "another-work"},
        {"source_hash": "sha256:wrong"},
        {"parser_revision": "changed-parser"},
        {"scope": "full_text"},
        {"page": 9},
    ],
)
def test_reference_version_scope_parser_or_source_drift_is_rejected(
    abstract: SourceMaterial, change: dict[str, Any]
) -> None:
    original = claim(abstract)
    altered = replace(original, evidence=(replace(original.evidence[0], **change),))
    with pytest.raises(g.GroundingError, match="source_version_or_scope_drift"):
        g.validate_claims([altered], [abstract])


@pytest.mark.parametrize(
    "change", [{"quote": "Invented source quote"}, {"start": -1}, {"end": 9999}, {"quote": ""}]
)
def test_valid_span_id_cannot_attach_an_invented_or_out_of_bounds_quote(
    abstract: SourceMaterial, change: dict[str, Any]
) -> None:
    original = claim(abstract)
    altered = replace(original, evidence=(replace(original.evidence[0], **change),))
    with pytest.raises(g.GroundingError, match="quote_not_in_retained_span"):
        g.validate_claims([altered], [abstract])


def test_missing_reference_abstains_but_a_decided_check_cannot_use_it(
    abstract: SourceMaterial,
) -> None:
    original = claim(abstract)
    for ref in (
        replace(original.evidence[0], material_id="missing"),
        replace(original.evidence[0], span_id="missing"),
    ):
        missing = replace(original, evidence=(ref,))
        result = g.validate_claims([missing], [abstract])
        assert not result.assessments[0].identity_resolved and result.abstained == 1
        assert result.assessments[0].reason == "evidence_reference_missing"
        with pytest.raises(g.GroundingError, match="checker_input_unavailable"):
            g.claim_input_digest(missing, [abstract])
        with pytest.raises(g.GroundingError, match="check_references_missing"):
            g.validate_claims([missing], [abstract], [check(original, abstract)])
    no_refs = replace(original, evidence=())
    assert g.validate_claims([no_refs], []).support_ratio is None
    with pytest.raises(g.GroundingError, match="checker_input_unavailable"):
        g.claim_input_digest(no_refs, [])


def test_changed_claim_text_cannot_reuse_a_prior_support_check(abstract: SourceMaterial) -> None:
    original = claim(abstract)
    verdict = check(original, abstract)
    changed = replace(original, text="An entirely different factual assertion.")
    with pytest.raises(g.GroundingError, match="checker_input_drift"):
        g.validate_claims([changed], [abstract], [verdict])
    revised = extract_text(
        abstract.pages[0] + " Revised source.",
        work_id=abstract.work_id,
        version_id="v2",
        scope="abstract",
    )
    with pytest.raises(g.GroundingError, match="checker_input_drift"):
        g.validate_claims([claim(revised)], [revised], [verdict])


def test_retained_material_and_span_tampering_are_rejected(abstract: SourceMaterial) -> None:
    original = claim(abstract)
    with pytest.raises(g.GroundingError, match="retained_material_content_drift"):
        g.validate_claims([original], [replace(abstract, pages=("changed content",))])
    span = abstract.spans[0]
    with pytest.raises(g.GroundingError, match="retained_span_identity_drift"):
        g.validate_claims(
            [original], [replace(abstract, spans=(replace(span, version_id="wrong"),))]
        )
    with pytest.raises(g.GroundingError, match="retained_span_content_drift"):
        g.validate_claims(
            [original], [replace(abstract, spans=(replace(span, text="forged text"),))]
        )


@pytest.mark.parametrize(
    "change", [{"decision": "yes"}, {"checker_id": ""}, {"checker_revision": ""}, {"reason": ""}]
)
def test_incomplete_checker_provenance_is_not_admitted(
    abstract: SourceMaterial, change: dict[str, Any]
) -> None:
    value = claim(abstract)
    with pytest.raises(g.GroundingError, match="invalid_support_check"):
        g.validate_claims([value], [abstract], [replace(check(value, abstract), **change)])


def test_duplicates_unknown_checks_and_malformed_claims_refused(abstract: SourceMaterial) -> None:
    value = claim(abstract)
    verdict = check(value, abstract)
    for args, reason in [
        (([value, value], [abstract], []), "duplicate_claim_id"),
        (([value], [abstract, abstract], []), "duplicate_material_id"),
        (([value], [abstract], [verdict, verdict]), "duplicate_check"),
        (([], [abstract], [verdict]), "check_has_unknown_claim"),
    ]:
        with pytest.raises(g.GroundingError, match=reason):
            g.validate_claims(*args)
    for change in ({"claim_id": ""}, {"claim_id": "x" * 121}, {"text": ""}, {"text": "x" * 10001}):
        with pytest.raises(g.GroundingError, match="invalid_claim"):
            g.validate_claims([replace(value, **change)], [abstract])
    for change in ({"kind": "unsupported-kind"}, {"required_scope": "unknown"}):
        with pytest.raises(g.GroundingError, match="invalid_claim_kind_or_scope"):
            g.validate_claims([replace(value, **change)], [abstract])
    with pytest.raises(g.GroundingError, match="duplicate_evidence_span"):
        g.validate_claims([replace(value, evidence=value.evidence * 2)], [abstract])


def test_metadata_excerpt_and_complete_full_text_scope_rules() -> None:
    metadata = extract_text("Title: A study", work_id="w", version_id="v", scope="metadata")
    generic = claim(metadata, required_scope="metadata")
    assert g.validate_claims([generic], [metadata], [check(generic, metadata)]).supported == 1
    for scope in ("abstract", "excerpt"):
        value = replace(generic, required_scope=scope)
        assert g.validate_claims([value], [metadata], [check(value, metadata)]).abstained == 1
    full = extract_text(
        "Full retained source including its methods.",
        work_id="w",
        version_id="v",
        scope="full_text",
    )
    complete = claim(full, required_scope="full_text", required_section="methods")
    assert g.validate_claims([complete], [full], [check(complete, full)]).supported == 1
    partial = replace(full, complete=False)
    assert g.validate_claims([complete], [partial], [check(complete, partial)]).abstained == 1
    abstract_excerpt = extract_text(
        "An abstract excerpt.", work_id="w", version_id="v", scope="excerpt", section="abstract"
    )
    requested = claim(abstract_excerpt)
    assert (
        g.validate_claims(
            [requested], [abstract_excerpt], [check(requested, abstract_excerpt)]
        ).supported
        == 1
    )


def test_duplicate_retained_spans_and_changed_completeness_cannot_reuse_a_check(
    abstract: SourceMaterial,
) -> None:
    value = claim(abstract)
    with pytest.raises(g.GroundingError, match="duplicate_retained_span_id"):
        g.validate_claims([value], [replace(abstract, spans=abstract.spans * 2)])
    verdict = check(value, abstract)
    with pytest.raises(g.GroundingError, match="checker_input_drift"):
        g.validate_claims([value], [replace(abstract, complete=False)], [verdict])
