"""Smoke tests for the eval benchmark query set.

These tests protect the invariants of the query list — no duplicates,
no empty fields, IDs are stable slugs — so accidental edits (a
truncated query, a duplicate ID) fail loudly instead of silently
skewing eval results.
"""

import re

from src.eval.benchmark_queries import BENCHMARK_QUERIES, get_queries

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class TestBenchmarkQueriesInvariants:
    def test_query_set_is_non_empty_and_has_at_least_ten(self) -> None:
        assert len(BENCHMARK_QUERIES) >= 10

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
