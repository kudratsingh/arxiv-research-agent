"""Unit tests for `src.tools.arxiv_search`.

Covers the ADR 0033 hardening: HTTPS endpoint, defusedxml parsing,
plus the existing happy-path and dedupe paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from defusedxml.common import EntitiesForbidden

import src.tools.arxiv_search as arxiv_module
from src.config import Settings
from src.resilience import DEPENDENCY_ARXIV
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


class TestTheTimeoutIsASettingNow:
    """ADR 0068. `timeout=30` was the one un-tunable timeout in a
    codebase that centralises every other knob, and it was also the
    reason nothing could clamp the retry chain against the job budget:
    a clamp needs to know the per-attempt cost."""

    def test_the_request_timeout_comes_from_settings(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            arxiv_module, "settings", Settings(arxiv_timeout_sec=11.5)
        )
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = _mock_response(
                ATOM_TEMPLATE.format(title="T", abstract="A", pdf_url="https://x/p.pdf")
            )
            search_arxiv("rag")
            _, kwargs = fake_session_factory.return_value.get.call_args

        assert kwargs["timeout"] == 11.5

    def test_the_same_timeout_is_declared_to_the_session_builder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both, and it has to be both: urllib3 applies the timeout per
        *attempt*, so the retry count can only be clamped by a builder
        that was told what one attempt costs."""
        monkeypatch.setattr(
            arxiv_module, "settings", Settings(arxiv_timeout_sec=11.5)
        )
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = _mock_response(
                ATOM_TEMPLATE.format(title="T", abstract="A", pdf_url="https://x/p.pdf")
            )
            search_arxiv("rag")

        assert fake_session_factory.call_args.kwargs["timeout_sec"] == 11.5

    def test_arxiv_retries_are_charged_to_their_own_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An arXiv outage must not spend the retries PDF downloads need."""
        monkeypatch.setattr(
            arxiv_module, "settings", Settings(arxiv_timeout_sec=11.5)
        )
        with patch(
            "src.tools.arxiv_search.build_retrying_session"
        ) as fake_session_factory:
            fake_session_factory.return_value.get.return_value = _mock_response(
                ATOM_TEMPLATE.format(title="T", abstract="A", pdf_url="https://x/p.pdf")
            )
            search_arxiv("rag")

        assert fake_session_factory.call_args.kwargs["dependency"] == DEPENDENCY_ARXIV

    def test_no_hardcoded_timeout_survives_in_the_module(self) -> None:
        """A structural guard, because the failure it prevents is a
        *reintroduction*: the literal is easy to type and invisible
        until a job's whole budget has gone into one query."""
        source = Path(arxiv_module.__file__).read_text(encoding="utf-8")
        assert "timeout=30" not in source
