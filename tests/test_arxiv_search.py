"""Unit tests for `src.tools.arxiv_search`.

Covers the ADR 0033 hardening: HTTPS endpoint, defusedxml parsing,
plus the existing happy-path and dedupe paths.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from defusedxml.common import EntitiesForbidden

from src.tools.arxiv_search import (
    ARXIV_API_URL,
    deduplicate_papers,
    search_arxiv,
)

pytestmark = pytest.mark.unit


ATOM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2311.09000v1</id>
    <title>{title}</title>
    <summary>{abstract}</summary>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <link title="pdf" href="{pdf_url}"/>
  </entry>
</feed>
"""


def _mock_response(text: str, status: int = 200) -> Any:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    return resp


def test_arxiv_endpoint_uses_https() -> None:
    """MITM protection: the endpoint constant must be TLS-only.

    An http:// endpoint lets a network attacker inject arbitrary
    paper metadata that then drives Claude prompts + PDF fetches.
    Regression guard for ADR 0033.
    """
    assert ARXIV_API_URL.startswith("https://")


def test_search_arxiv_parses_entries() -> None:
    xml = ATOM_TEMPLATE.format(
        title="A Study of RAG",
        abstract="We study retrieval-augmented generation.",
        pdf_url="https://arxiv.org/pdf/2311.09000v1.pdf",
    )
    with patch(
        "src.tools.arxiv_search.build_retrying_session"
    ) as fake_session_factory:
        fake_session_factory.return_value.get.return_value = _mock_response(xml)
        papers = search_arxiv("rag", max_results=5)
    assert len(papers) == 1
    assert papers[0]["title"] == "A Study of RAG"
    assert papers[0]["authors"] == ["Alice", "Bob"]
    assert papers[0]["pdf_url"].startswith("https://arxiv.org/pdf/")


def test_search_arxiv_rejects_entity_expansion() -> None:
    """XXE guard: defusedxml must refuse entity-expansion payloads.

    A malicious feed carrying a DOCTYPE + billion-laughs entity would
    let a compromised upstream (or MITM before we flipped to https)
    OOM the parser. `defusedxml` raises `EntitiesForbidden` before
    expansion even starts.
    """
    malicious = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>&lol2;</title></entry>
</feed>
"""
    with patch(
        "src.tools.arxiv_search.build_retrying_session"
    ) as fake_session_factory:
        fake_session_factory.return_value.get.return_value = _mock_response(malicious)
        with pytest.raises(EntitiesForbidden):
            search_arxiv("evil", max_results=1)


def test_search_arxiv_returns_empty_on_rate_limit() -> None:
    with patch(
        "src.tools.arxiv_search.build_retrying_session"
    ) as fake_session_factory:
        fake_session_factory.return_value.get.return_value = _mock_response(
            "Rate exceeded", status=200
        )
        papers = search_arxiv("q", max_results=5)
    assert papers == []


def test_deduplicate_papers_keeps_first_by_id() -> None:
    seen = deduplicate_papers(
        [
            {"id": "a", "title": "A", "authors": [], "abstract": "", "url": "", "pdf_url": ""},
            {"id": "b", "title": "B", "authors": [], "abstract": "", "url": "", "pdf_url": ""},
            {"id": "a", "title": "A dupe", "authors": [], "abstract": "", "url": "", "pdf_url": ""},
        ]
    )
    ids = [p["id"] for p in seen]
    titles = [p["title"] for p in seen]
    assert ids == ["a", "b"]
    assert titles == ["A", "B"]  # first-seen wins
