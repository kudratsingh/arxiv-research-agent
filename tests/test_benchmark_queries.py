"""Smoke tests for the eval benchmark query set.

These tests protect the invariants of the query list — no duplicates,
no empty fields, IDs are stable slugs — so accidental edits (a
truncated query, a duplicate ID) fail loudly instead of silently
skewing eval results.
"""

import re
from datetime import date

import pytest

from src.eval.benchmark_queries import (
    BENCHMARK_QUERIES,
    DATASET_AUTHOR,
    DATASET_LICENSE,
    DATASET_NAME,
    RESEARCH_DATASET_VERSION,
    get_queries,
)
from src.eval.provenance import dataset_fingerprint

pytestmark = pytest.mark.unit

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class TestBenchmarkQueriesInvariants:
    def test_query_set_has_at_least_twenty(self) -> None:
        # Sprint 1 target — expanded from the initial 10.
        assert len(BENCHMARK_QUERIES) >= 20

    def test_query_ids_are_unique(self) -> None:
        ids = [q["query_id"] for q in BENCHMARK_QUERIES]
        assert len(ids) == len(set(ids))

    def test_query_ids_are_kebab_case_slugs(self) -> None:
        for q in BENCHMARK_QUERIES:
            assert SLUG_PATTERN.match(q["query_id"]), q["query_id"]

    def test_every_query_has_non_empty_required_fields(self) -> None:
        for q in BENCHMARK_QUERIES:
            assert q["query_id"], q
            assert q["query"].strip(), q
            assert q["domain"].strip(), q
            assert q["expected_topics"], q
            # notes may be empty in principle; require non-None
            assert isinstance(q["notes"], str)

    def test_expected_topics_are_non_empty_strings(self) -> None:
        for q in BENCHMARK_QUERIES:
            for topic in q["expected_topics"]:
                assert isinstance(topic, str) and topic.strip(), (
                    q["query_id"],
                    topic,
                )

    def test_queries_end_with_question_mark(self) -> None:
        for q in BENCHMARK_QUERIES:
            assert q["query"].rstrip().endswith("?"), q["query_id"]

    def test_domain_coverage_is_diverse(self) -> None:
        # Guard against the whole benchmark being about one topic.
        domains = {q["domain"].lower() for q in BENCHMARK_QUERIES}
        assert len(domains) >= 5


class TestGetQueries:
    def test_returns_all_queries_when_no_filter(self) -> None:
        assert get_queries() == BENCHMARK_QUERIES

    def test_returns_copy_not_reference(self) -> None:
        result = get_queries()
        result.clear()
        assert BENCHMARK_QUERIES, "get_queries() should not expose internal list"

    def test_filters_by_domain_case_insensitive(self) -> None:
        # "alignment" is one of our domains.
        exact = get_queries(domain="alignment")
        upper = get_queries(domain="ALIGNMENT")
        assert exact and exact == upper

    def test_unknown_domain_returns_empty(self) -> None:
        assert get_queries(domain="nonexistent-domain") == []


class TestDatasetProvenance:
    """ADR 0070: a benchmark whose origin nobody recorded cannot support
    a claim about the system it scores (NIST AI RMF MEASURE 2.1)."""

    def test_every_query_names_an_author(self) -> None:
        for q in BENCHMARK_QUERIES:
            assert q["author"].strip(), q["query_id"]

    def test_every_query_carries_an_iso_creation_date(self) -> None:
        for q in BENCHMARK_QUERIES:
            date.fromisoformat(q["created"])

    def test_every_query_declares_a_licence(self) -> None:
        for q in BENCHMARK_QUERIES:
            assert q["license"].strip(), q["query_id"]

    def test_the_licence_says_unlicensed_rather_than_guessing(self) -> None:
        # This repository ships no LICENSE file. `UNLICENSED` is the
        # honest value; inventing an SPDX id here would be a licensing
        # claim the repository does not make.
        assert DATASET_LICENSE == "UNLICENSED"
        assert {q["license"] for q in BENCHMARK_QUERIES} == {DATASET_LICENSE}

    def test_creation_dates_match_the_two_authoring_sessions(self) -> None:
        # Ten queries landed with the eval scaffold, ten with the Sprint 1
        # expansion; a single blanket date would be a fabricated record.
        assert {q["created"] for q in BENCHMARK_QUERIES} == {
            "2026-07-05",
            "2026-07-07",
        }

    def test_the_contamination_note_survives(self) -> None:
        # `hallucination-mitigation` is known to be covered by the
        # built-in mock papers, so its retrieval recall is scored against
        # papers hand-picked to match. Losing that annotation would make
        # the query look like any other.
        smoke = next(
            q for q in BENCHMARK_QUERIES if q["query_id"] == "hallucination-mitigation"
        )
        assert "built-in mock papers" in smoke["notes"]

    def test_the_author_constant_is_what_the_queries_carry(self) -> None:
        assert {q["author"] for q in BENCHMARK_QUERIES} == {DATASET_AUTHOR}


class TestDatasetVersion:
    def test_the_version_names_the_dataset_and_its_size(self) -> None:
        assert RESEARCH_DATASET_VERSION.startswith(
            f"{DATASET_NAME}@{len(BENCHMARK_QUERIES)}:"
        )

    def test_the_version_is_derived_rather_than_declared(self) -> None:
        # Editing a query must move the fingerprint without anyone
        # remembering to bump a constant.
        edited = [dict(q) for q in BENCHMARK_QUERIES]
        edited[0]["query"] = edited[0]["query"] + " (edited)"
        assert dataset_fingerprint(DATASET_NAME, edited) != RESEARCH_DATASET_VERSION

    def test_the_version_is_stable_for_an_unchanged_dataset(self) -> None:
        assert (
            dataset_fingerprint(DATASET_NAME, BENCHMARK_QUERIES)
            == RESEARCH_DATASET_VERSION
        )
